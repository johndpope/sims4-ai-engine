from _math import Transform
from collections import defaultdict
import _collection_utils
import weakref
import native.animation
from animation.animation_bc_cache import read_bc_cache_from_resource
from animation.animation_utils import partition_boundary_on_params
from animation.posture_manifest import PostureManifest, PostureManifestEntry, _NOT_SPECIFIC_ACTOR, MATCH_ANY, Hand
from paths import USE_CACHED_CONSTRAINTS
from sims.sim_info_types import Age
from sims4.callback_utils import CallableList
from sims4.collections import frozendict
from sims4.sim_irq_service import yield_to_irq
from singletons import DEFAULT, UNSET
import caches
import sims4.callback_utils
import sims4.geometry
import sims4.hash_util
import sims4.log
logger = sims4.log.Logger('Animation')
with sims4.reload.protected(globals()):
    GLOBAL_SINGLE_PART_CONDITION_CACHE = {}
    GLOBAL_MULTI_PART_CONDITION_CACHE = {}
    _verbose_logging_asms = []

def add_boundary_condition_logging(pattern):
    _verbose_logging_asms.append(pattern)

def clear_boundary_condition_logging():
    global _verbose_logging_asms
    _verbose_logging_asms = []

def purge_cache():
    Asm._bc_cache.clear()
    Asm._bc_cache_error_keys.clear()

sims4.callback_utils.add_callbacks(sims4.callback_utils.CallbackEvent.TUNING_CODE_RELOAD, purge_cache)
do_params_match = _collection_utils.dictionary_intersection_values_match

def _consolidate_carry_info2(posture_manifest):
    if posture_manifest is None:
        return
    result = PostureManifest()
    for p0 in posture_manifest:
        free_hands = set()
        for p1 in posture_manifest:
            while p0.actor == p1.actor and (p0.specific == p1.specific and (p0.family == p1.family and (p0.level == p1.level and p0.surface == p1.surface))) and p0.provides == p1.provides:
                if p0.left in _NOT_SPECIFIC_ACTOR and (p1.left in _NOT_SPECIFIC_ACTOR and p0.right in _NOT_SPECIFIC_ACTOR) and p1.right in _NOT_SPECIFIC_ACTOR:
                    free_hands.update(p1.free_hands)
        left = p0.left
        right = p0.right
        left = MATCH_ANY if Hand.LEFT in free_hands else left
        right = MATCH_ANY if Hand.RIGHT in free_hands else right
        entry = PostureManifestEntry(p0.actor, p0.specific, p0.family, p0.level, left, right, p0.surface, p0.provides)
        result.add(entry)
    return result

class Asm(native.animation.NativeAsm):
    __qualname__ = 'Asm'
    _bc_cache = {}
    _bc_cache_error_keys = set()

    def _log_bc_error(self, log, currently_set_actor_names, key, headline, actor_info):
        set_actor_names = []
        unset_actor_names = set(self.actors)
        for e in currently_set_actor_names:
            if isinstance(e, tuple):
                unset_actor_names.discard(e[1])
                e = '{1}[{0}]'.format(*e)
            else:
                unset_actor_names.discard(e)
            set_actor_names.append(e)
        set_actor_names.sort()
        unset_actor_names = sorted(unset_actor_names)
        log("Boundary condition error: {}\n    {}\n        {} (Unset actors: {})\n    The boundary information we're looking for is:\n        {}: {} from {} --> {} (Posture: {})".format(headline, actor_info, ', '.join(set_actor_names), ', '.join(unset_actor_names), *key))

    @staticmethod
    def transform_almost_equal_2d(a, b):
        return sims4.math.transform_almost_equal_2d(a, b, epsilon=sims4.geometry.ANIMATION_SLOT_EPSILON, epsilon_orientation=sims4.geometry.ANIMATION_SLOT_EPSILON)

    class BoundaryConditionRelative:
        __qualname__ = 'Asm.BoundaryConditionRelative'
        __slots__ = ('pre_condition_reference_object_name', 'pre_condition_transform', 'post_condition_reference_object_name', 'post_condition_transform', 'required_slots', 'debug_info')

        def __str__(self):
            pre_str = '0'
            if self.pre_condition_transform != Transform.IDENTITY():
                n = list(self.pre_condition_transform.translation)
                n.extend(self.pre_condition_transform.orientation)
                pre_str = '({:0.3},{:0.3},{:0.3}/{:0.3},{:0.3},{:0.3},{:0.3})'.format(*n)
            post_str = '0'
            if self.post_condition_transform != Transform.IDENTITY():
                n = list(self.post_condition_transform.translation)
                n.extend(self.post_condition_transform.orientation)
                post_str = '({:0.3},{:0.3},{:0.3}/{:0.3},{:0.3},{:0.3},{:0.3})'.format(*n)
            return '{}+{} -> {}+{} {}'.format(self.pre_condition_reference_object_name, pre_str, self.post_condition_reference_object_name, post_str, self.required_slots)

        def __init__(self, pre_condition_reference_object_name, pre_condition_transform, post_condition_reference_object_name, post_condition_transform, required_slots, debug_info):
            self.pre_condition_reference_object_name = pre_condition_reference_object_name
            self.pre_condition_transform = pre_condition_transform
            self.post_condition_reference_object_name = post_condition_reference_object_name
            self.post_condition_transform = post_condition_transform
            self.required_slots = required_slots
            self.debug_info = debug_info

        def get_pre_condition_reference_object_id(self, asm):
            actor = asm.get_actor_by_name(self.pre_condition_reference_object_name)
            if actor is not None:
                return actor.id

        def get_post_condition_reference_object_id(self, asm):
            actor = asm.get_actor_by_name(self.post_condition_reference_object_name)
            if actor is not None:
                return actor.id

        def get_relative_object_id(self, asm):
            return self.get_pre_condition_reference_object_id(asm) or (self.get_post_condition_reference_object_id(asm) or None)

        def get_transforms(self, asm, part):
            pre_condition_transform = self.pre_condition_transform
            post_condition_transform = self.post_condition_transform
            pre_condition_reference_object = asm.get_actor_by_name(self.pre_condition_reference_object_name)
            if pre_condition_reference_object is not None:
                pre_obj_transform = pre_condition_reference_object.transform
                pre_condition_transform = Transform.concatenate(pre_condition_transform, pre_obj_transform)
            if self.post_condition_reference_object_name is None:
                return (pre_condition_transform, pre_condition_transform)
            post_condition_reference_object = asm.get_actor_by_name(self.post_condition_reference_object_name)
            if post_condition_reference_object is not None:
                post_obj_transform = post_condition_reference_object.transform
                post_condition_transform = Transform.concatenate(post_condition_transform, post_obj_transform)
            return (pre_condition_transform, post_condition_transform)

    def __init__(self, asm_key, context, posture_manifest_overrides=None):
        super().__init__(asm_key)
        self.context = context
        self._posture_manifest_overrides = posture_manifest_overrides
        self._prop_overrides = {}
        self._prop_state_values = {}
        self._vfx_overrides = {}
        self._sound_overrides = {}
        self._actors = {}
        self._virtual_actors = defaultdict(set)
        self._virtual_actor_relationships = {}
        self._on_state_changed_events = CallableList()

    @property
    def name(self):
        return self.state_machine_name

    @property
    def context(self):
        if self._context_ref is not None:
            return self._context_ref()

    @context.setter
    def context(self, value):
        if value is not None:
            self._context_ref = weakref.ref(value)
            value.add_asm(self)
        else:
            self._context_ref = None

    @property
    def vfx_overrides(self):
        return self._vfx_overrides

    @property
    def sound_overrides(self):
        return self._sound_overrides

    @property
    def on_state_changed_events(self):
        return self._on_state_changed_events

    def _validate_actor(self, actor):
        for existing_actor in self.actors_gen():
            while existing_actor == actor:
                return
        raise AssertionError("Attempt to get boundary conditions for an actor {} that doesn't exist in the ASM {}.".format(actor, self))

    def get_actor_by_name(self, actor_name):
        actor_info = self._actors.get(actor_name)
        if actor_info is not None:
            return actor_info[0]()
        actor_infos = self._virtual_actors.get(actor_name)
        if actor_infos:
            for actor_info in actor_infos:
                pass

    def get_actor_name_from_id(self, object_id):
        if not object_id:
            return
        for (actor_name, actor_info) in self._actors.items():
            boundary_actor = actor_info[0]()
            while object_id == boundary_actor.id:
                return actor_name
        for (actor_name, actor_infos) in self._virtual_actors.items():
            for actor_info in actor_infos:
                boundary_actor = actor_info[0]()
                while object_id == boundary_actor.id:
                    return actor_name

    def _get_all_set_actor_names(self):
        names = set(self._actors.keys())
        virtual_names = set(e[1] for e in self._virtual_actor_relationships.keys())
        return frozenset(names | virtual_names)

    def _get_param_sequences_for_cache(self, actor, actor_name, to_state_name, from_state_name, posture):
        internal_param_sequence_list = self._get_param_sequences(actor.id, to_state_name, from_state_name, None)
        param_sequence_list = []
        posture_key = ('posture', actor_name)
        exact_str = posture.name + '-'
        family_str = posture.family_name
        if family_str is not None:
            family_str = '-' + family_str + '-'
        for param_sequence in internal_param_sequence_list or (None,):
            if param_sequence:
                posture_param_value = param_sequence.get(posture_key)
                if posture_param_value is not None:
                    if not posture_param_value.startswith(exact_str):
                        while not family_str is None:
                            if family_str not in posture_param_value:
                                pass
                            for age in Age.get_ages_for_animation_cache():
                                new_sequence = frozendict(param_sequence, {('age', actor_name): age.animation_age_param})
                                param_sequence_list.append(new_sequence)
            for age in Age.get_ages_for_animation_cache():
                new_sequence = frozendict(param_sequence, {('age', actor_name): age.animation_age_param})
                param_sequence_list.append(new_sequence)
        return param_sequence_list

    def _create_containment_slot_data_list(self, key, actor, actor_name, to_state_name, from_state_name, posture, entry, verbose_logging):
        cache_containment_slot_data_list = True
        param_sequence_list = self._get_param_sequences_for_cache(actor, actor_name, to_state_name, from_state_name, posture)
        boundary_to_params = {}
        for param_sequence in param_sequence_list:
            self.set_param_sequence(param_sequence)
            yield_to_irq()
            if verbose_logging:
                logger.warn('  Setting parameter list on ASM:')
                for (key, value) in param_sequence.items():
                    logger.warn('    {}:\t{}', key, value)
            boundary = self.get_boundary_conditions(actor, to_state_name, from_state_name)
            boundary.debug_info = None
            pre_condition_reference_object_name = self.get_actor_name_from_id(boundary.pre_condition_reference_object_id)
            post_condition_reference_object_name = self.get_actor_name_from_id(boundary.post_condition_reference_object_id)
            if verbose_logging:
                logger.warn('    Pre conditions')
                logger.warn('      Object: {}', pre_condition_reference_object_name)
                logger.warn('      Translation: {}', boundary.pre_condition_transform.translation)
                logger.warn('      Orientation: {}', boundary.pre_condition_transform.orientation)
                logger.warn('    Post conditions')
                logger.warn('      Object: {}', post_condition_reference_object_name)
                logger.warn('      Translation: {}', boundary.post_condition_transform.translation)
                logger.warn('      Orientation: {}', boundary.post_condition_transform.orientation)
            required_slots = []
            currently_set_actor_names = self._get_all_set_actor_names()
            if boundary.required_slots:
                for required_slot in boundary.required_slots:
                    pre_condition_surface_child_id = required_slot[0]
                    pre_condition_surface_object_id = required_slot[1]
                    pre_condition_surface_child_name = self.get_actor_name_from_id(pre_condition_surface_child_id)
                    pre_condition_surface_object_name = self.get_actor_name_from_id(pre_condition_surface_object_id)
                    if pre_condition_surface_child_name and pre_condition_surface_object_name:
                        required_slots.append((pre_condition_surface_child_name, pre_condition_surface_object_name, required_slot[2]))
                    else:
                        cache_containment_slot_data_list = False
                        self._log_bc_error(logger.error, currently_set_actor_names, key, 'missing parent or child object', "The parent or child in Maya isn't one of the following actors:")
            if not required_slots and boundary.pre_condition_reference_object_id is None:
                pass
            if boundary.pre_condition_reference_object_id is not None and pre_condition_reference_object_name is None:
                pass
            for (boundary_existing, params_list) in boundary_to_params.items():
                while pre_condition_reference_object_name == boundary_existing.pre_condition_reference_object_name and (post_condition_reference_object_name == boundary_existing.post_condition_reference_object_name and (self.transform_almost_equal_2d(boundary.pre_condition_transform, boundary_existing.pre_condition_transform) and self.transform_almost_equal_2d(boundary.post_condition_transform, boundary_existing.post_condition_transform))) and required_slots == boundary_existing.required_slots:
                    params_list.append(param_sequence)
                    break
            boundary_relative = self.BoundaryConditionRelative(pre_condition_reference_object_name, boundary.pre_condition_transform, post_condition_reference_object_name, boundary.post_condition_transform, required_slots, boundary.debug_info)
            boundary_to_params[boundary_relative] = [param_sequence]
        if verbose_logging:
            logger.warn('  Boundary -> Param Sequences')
            for (key, value) in boundary_to_params.items():
                logger.warn('    {}', key)
                for param_sequence in value:
                    logger.warn('      {}', param_sequence)
        boundary_list = []
        if len(boundary_to_params) > 0:
            if len(boundary_to_params) == 1:
                boundary_list.append((boundary_to_params.popitem()[0], [{}]))
            else:
                boundary_param_sets = partition_boundary_on_params(boundary_to_params)
                for (boundary, param_set) in boundary_param_sets.items():
                    boundary_params_list_minimal = {frozendict({k: v for (k, v) in boundary_params.items() if k in param_set}) for boundary_params in boundary_to_params[boundary]}
                    boundary_list.append((boundary, boundary_params_list_minimal))
        relative_object_name = None
        containment_slot_data_list = []
        for (boundary_condition, slot_params_list) in boundary_list:
            relative_object_name_key = boundary_condition.pre_condition_reference_object_name or boundary_condition.post_condition_reference_object_name
            if entry:
                if boundary_condition.post_condition_reference_object_name is not None:
                    containment_transform = boundary_condition.post_condition_transform
                else:
                    containment_transform = boundary_condition.pre_condition_transform
            else:
                containment_transform = boundary_condition.pre_condition_transform
            for (containment_transform_existing, slots_to_params) in containment_slot_data_list:
                while self.transform_almost_equal_2d(containment_transform, containment_transform_existing):
                    slots_to_params.append((boundary_condition, slot_params_list))
                    break
            containment_slot_data_list.append((containment_transform, [(boundary_condition, slot_params_list)]))
        if cache_containment_slot_data_list:
            self._bc_cache[key] = tuple(containment_slot_data_list)
        return containment_slot_data_list

    def _make_boundary_conditions_list(self, actor, to_state_name, from_state_name, locked_params, entry=True, posture=DEFAULT):
        if any(pattern in str(self) for pattern in _verbose_logging_asms):
            verbose_logging = True
        else:
            verbose_logging = False
        if not Asm._bc_cache and should_use_boundary_condition_cache():
            Asm._bc_cache.update(read_bc_cache_from_resource())
        actor_name = self.get_actor_name_from_id(actor.id)
        if verbose_logging:
            logger.warn('Traversing as {} ({} -> {})', actor_name, from_state_name, to_state_name)
        posture = actor.posture if posture is DEFAULT else posture
        key = (self.name, actor_name, from_state_name, to_state_name, posture.name)
        containment_slot_data_list = self._bc_cache.get(key)
        if containment_slot_data_list is None:
            containment_slot_data_list = self._create_containment_slot_data_list(key, actor, actor_name, to_state_name, from_state_name, posture, entry, verbose_logging)
        if not containment_slot_data_list:
            return ()
        if actor.age is not UNSET:
            real_age_param = {('age', actor_name): actor.age.animation_age_param}
            locked_params += {('age', actor_name): actor.age.age_for_animation_cache.animation_age_param}
        else:
            real_age_param = {}
        containment_slot_data_list_filtered = []
        for (containment_slot, slots_to_params) in containment_slot_data_list:
            slots_to_params_valid = []
            for (boundary_condition, param_sequences) in slots_to_params:
                param_sequences_valid = [frozendict(param_sequence, real_age_param) for param_sequence in param_sequences if do_params_match(param_sequence, locked_params)]
                while param_sequences_valid:
                    slots_to_params_valid.append((boundary_condition, tuple(param_sequences_valid)))
            while slots_to_params_valid:
                containment_slot_data_list_filtered.append((containment_slot, tuple(slots_to_params_valid)))
        return tuple(containment_slot_data_list_filtered)

    def get_boundary_conditions_list(self, actor, to_state_name, from_state_name=DEFAULT, entry=True, locked_params=frozendict(), posture=DEFAULT):
        if from_state_name is DEFAULT:
            from_state_name = 'entry'
        boundary_list = self._make_boundary_conditions_list(actor, to_state_name, from_state_name, locked_params, entry=entry, posture=posture)
        return boundary_list

    def set_prop_override(self, prop_name, override_tuning):
        self._prop_overrides[prop_name] = override_tuning

    def store_prop_state_values(self, prop_name, state_values):
        self._prop_state_values[prop_name] = state_values

    def set_vfx_override(self, vfx_object_name, vfx_override_name):
        self._vfx_overrides[sims4.hash_util.hash32(vfx_object_name)] = vfx_override_name

    def set_sound_override(self, sound_name, sound_id):
        self._sound_overrides[sims4.hash_util.hash64(sound_name)] = sound_id

    def get_props_in_traversal(self, from_state, to_state):
        prop_keys = super().get_props_in_traversal(from_state, to_state)
        if not prop_keys:
            return prop_keys
        result = {}
        for (prop_name, prop_key) in prop_keys.items():
            if prop_name in self._prop_overrides and self._prop_overrides[prop_name].definition is not None:
                result[prop_name] = self._prop_overrides[prop_name].definition.id
            else:
                result[prop_name] = prop_key.instance
        return result

    def get_prop_state_override(self, prop_name):
        if prop_name in self._prop_overrides:
            override_tuple = self._prop_overrides[prop_name]
            if override_tuple.from_actor is not None:
                actor = self.get_actor_by_name(override_tuple.from_actor)
                if actor is not None:
                    return (actor, override_tuple.states_to_override)
        return (None, None)

    def set_prop_state_values(self, prop_name, prop):
        state_values = self._prop_state_values.get(prop_name)
        if state_values is None:
            return
        for state_value in state_values:
            while state_value is not None:
                prop.set_state(state_value.state, state_value)

    def request(self, state_name, arb, *args, context=None, **kwargs):
        context = context or self.context
        current_state = self.current_state
        self._on_state_changed_events(self, state_name)
        context._pre_request(self, arb, state_name)
        result = super().request(state_name, arb, request_id=context.request_id, *args, **kwargs)
        context._post_request(self, arb, state_name)
        if result == native.animation.ASM_REQUESTRESULT_SUCCESS:
            return True
        if result == native.animation.ASM_REQUESTRESULT_TARGET_JUMPED_TO_TARGET_STATE:
            raise RuntimeError('{}: Attempt to traverse between two states ({} -> {}) where no valid path exists! Actors {}'.format(self, current_state, state_name, self._actors))
        else:
            if result == native.animation.ASM_REQUESTRESULT_TARGET_STATE_NOT_FOUND:
                logger.error("{}: Attempt to request state that doesn't exist - {}.", self, state_name)
                return False
            logger.error('{}: Unknown result code when requesting state - {}.', self, state_name)

    def traverse(self, from_state_name, to_state_name, arb, *args, context=None, from_boundary_conditions=False, **kwargs):
        context = context or self.context
        if not from_boundary_conditions:
            self._on_state_changed_events(self, to_state_name)
            context._pre_request(self, arb, to_state_name)
        success = super().traverse(from_state_name, to_state_name, arb, request_id=context.request_id, from_boundary_conditions=from_boundary_conditions, *args, **kwargs)
        if not from_boundary_conditions:
            context._post_request(self, arb, to_state_name)
        return success

    def set_current_state(self, state_name):
        self._on_state_changed_events(self, state_name)
        return super().set_current_state(state_name)

    def exit(self, arb, *args, context=None, **kwargs):
        context = context or self.context
        self._on_state_changed_events(self, 'exit')
        context._pre_request(self, arb, 'exit')
        success = super().exit(arb, request_id=context.request_id, *args, **kwargs)
        context._post_request(self, arb, 'exit')
        return success

    def set_actor(self, actor_name, actor, suffix=DEFAULT, actor_participant=None, **kwargs):
        actor_set = False
        if actor is None:
            if actor_name in self._actors:
                del self._actors[actor_name]
            return super().set_actor(actor_name, None)
        if suffix is DEFAULT:
            suffix = actor.part_suffix
        if actor_name in self._actors:
            (old_actor, old_suffix, _) = self._actors[actor_name]
            old_actor = old_actor() if old_actor is not None else None
            if old_actor == actor and old_suffix == suffix:
                actor_set = True
            else:
                return False
        if not actor_set:
            if super().set_actor(actor_name, actor, suffix=suffix, **kwargs):
                self._actors[actor_name] = (actor.ref(), suffix, actor_participant)
                actor_set = True
            else:
                logger.warn('{}: Failed to set actor {} to {}:{}', self.name, actor_name, actor, suffix)
        if not actor_set:
            return False
        overrides = actor.get_anim_overrides(actor_name)
        if overrides:
            overrides.override_asm(self, actor, suffix)
        return True

    def add_virtual_actor(self, actor_name, actor, suffix=DEFAULT):
        actor_set = False
        if suffix is DEFAULT:
            suffix = actor.part_suffix
        if actor_name in self._virtual_actors:
            for (old_actor, old_suffix) in self._virtual_actors[actor_name]:
                old_actor = old_actor() if old_actor is not None else None
                while old_actor.id == actor.id and old_suffix == suffix:
                    actor_set = True
                    break
        if not actor_set:
            if super().add_virtual_actor(actor_name, actor, suffix):
                self._virtual_actors[actor_name].add((actor.ref(), suffix))
                actor_set = True
            else:
                logger.warn('{}: Failed to add virtual actor {}: {}:{}', self.name, actor_name, actor, suffix)
        if not actor_set:
            return False
        overrides = actor.get_anim_overrides(actor_name)
        if overrides:
            overrides.override_asm(self, actor, suffix)
        return True

    def remove_virtual_actor(self, name, actor, suffix=None):
        if not super().remove_virtual_actor(name, actor, suffix):
            return False
        self._virtual_actors[name].remove((actor.ref(), suffix))
        deletes = []
        for (key, (target_ref, target_suffix)) in self._virtual_actor_relationships.items():
            target = target_ref() if target_ref is not None else None
            while target == actor and target_suffix == suffix:
                deletes.append(key)
        for key in deletes:
            del self._virtual_actor_relationships[key]
        return True

    def specialize_virtual_actor_relationship(self, actor_name, actor, actor_suffix, target_name, target, target_suffix):
        result = super().specialize_virtual_actor_relationship(actor_name, actor, actor_suffix, target_name, target, target_suffix)
        if result:
            self._virtual_actor_relationships[(actor_name, target_name)] = (target.ref(), target_suffix)
        return result

    def add_potentially_virtual_actor(self, actor_name, actor, target_name, target, part_suffix=DEFAULT, target_participant=None):
        if part_suffix is DEFAULT:
            part_suffix = target.part_suffix
        target_definition = self.get_actor_definition(target_name)
        if target_definition is None:
            logger.error("Failed to add potentially virtual actor '{}' on asm '{}'. The actor does not exist.", target_name, self.name)
            return False
        if target_definition.is_virtual:
            if not self.add_virtual_actor(target_name, target, part_suffix):
                logger.error('Failed to add virtual actor {}, suffix {} on asm {}.', target_name, part_suffix, self.name)
                return False
            if not self.specialize_virtual_actor_relationship(actor_name, actor, None, target_name, target, part_suffix):
                logger.error('Failed to specialize virtual actor for (name: {}, rig: {}, suffix: {}) for ASM: {} and Sim: {}.', target_name, target.rig, part_suffix, self.name, actor)
                return False
        elif not self.set_actor(target_name, target, suffix=part_suffix, actor_participant=target_participant):
            return False
        return True

    def update_locked_params(self, locked_params, virtual_actor_map=None):
        for (param_name, param_value) in locked_params.items():
            actor = None
            if not isinstance(param_name, tuple):
                self.set_parameter(param_name, param_value)
            (param_name, actor_name) = param_name
            if actor_name in self._virtual_actors:
                if virtual_actor_map is None or actor_name not in virtual_actor_map:
                    raise RuntimeError('{}: virtual_actor_map does not contain entry for {}: {}'.format(self.name, actor_name, virtual_actor_map))
                actor = virtual_actor_map[actor_name]
                if actor is None:
                    raise RuntimeError('{}: Virtual actors for {} do not include {}: {}'.format(self.name, actor_name, actor, self._virtual_actors[actor_name]))
                suffix = self.get_suffix(actor_name, actor)
            else:
                (actor, suffix) = self.get_actor_and_suffix(actor_name)
            if actor is not None:
                self.set_actor_parameter(actor_name, actor, param_name, param_value, suffix)
            else:
                self.set_parameter(param_name, param_value)

    def get_actor_and_suffix(self, actor_name):
        if actor_name in self._actors:
            (actor, suffix, _) = self._actors[actor_name]
            actor = actor() if actor is not None else None
            return (actor, suffix)
        return (None, None)

    def get_virtual_actor_and_suffix(self, actor_name, target_name):
        if (actor_name, target_name) in self._virtual_actor_relationships:
            (target, suffix) = self._virtual_actor_relationships[(actor_name, target_name)]
            target = target() if target is not None else None
            return (target, suffix)
        return (None, None)

    def get_suffix(self, actor_name, actor):
        if actor_name in self._actors:
            (existing_actor, suffix, _) = self._actors[actor_name]
            if existing_actor is not None:
                existing_actor = existing_actor()
                if existing_actor == actor:
                    return suffix
        if actor_name in self._virtual_actors:
            for (existing_actor, suffix) in self._virtual_actors[actor_name]:
                while existing_actor is not None:
                    existing_actor = existing_actor()
                    if existing_actor == actor:
                        return suffix

    def actors_gen(self):
        for (actor, _, _) in self._actors.values():
            actor = actor() if actor is not None else None
            while actor is not None:
                yield actor
        for actor_list in self._virtual_actors.values():
            for (actor, _) in actor_list:
                actor = actor() if actor is not None else None
                while actor is not None:
                    yield actor

    def actors_info_gen(self):
        for (name, (actor, suffix, _)) in self._actors.items():
            actor = actor() if actor is not None else None
            while actor is not None:
                yield (name, actor, suffix)
        for (name, actor_list) in self._virtual_actors.items():
            for (actor, suffix) in actor_list:
                actor = actor() if actor is not None else None
                while actor is not None:
                    yield (name, actor, suffix)

    def get_actor_name(self, obj):
        for (name, actor, _) in self.actors_info_gen():
            while actor == obj:
                return name

    def _apply_posture_manifest_overrides(self, manifest):
        result = manifest
        if self._posture_manifest_overrides and manifest:
            result = PostureManifest()
            for entry in manifest:
                for (override_key, override_value) in self._posture_manifest_overrides.items():
                    if entry.matches_override_key(override_key):
                        extra_entries = entry.get_entries_with_override(override_value)
                        result.update(extra_entries)
                    else:
                        result.add(entry)
        return result

    _provided_posture_cache = {}
    _supported_posture_cache = {}

    @property
    def provided_postures(self):
        cache_key = self.state_machine_name
        if cache_key in self._provided_posture_cache:
            manifest = self._provided_posture_cache[cache_key]
        else:
            manifest = None
            postures = super().provided_postures
            if postures is not None:
                manifest = PostureManifest(PostureManifestEntry(provides=True, from_asm=True, *entry) for entry in postures)
                manifest = _consolidate_carry_info2(manifest)
                manifest = manifest.intern()
            self._provided_posture_cache[cache_key] = manifest
        manifest = self._apply_posture_manifest_overrides(manifest)
        return manifest

    def get_supported_postures_for_actor(self, actor_name):
        cache_key = (self.state_machine_name, actor_name)
        if cache_key in self._supported_posture_cache:
            manifest = self._supported_posture_cache[cache_key]
        else:
            manifest = None
            postures = super().get_supported_postures_for_actor(actor_name)
            if postures is not None:
                manifest = PostureManifest(PostureManifestEntry(*entry) for entry in postures)
                manifest = _consolidate_carry_info2(manifest)
                manifest = manifest.intern()
            self._supported_posture_cache[cache_key] = manifest
        manifest = self._apply_posture_manifest_overrides(manifest)
        return manifest

BoundaryConditionRelative = Asm.BoundaryConditionRelative

def should_use_boundary_condition_cache():
    return USE_CACHED_CONSTRAINTS

def get_boundary_condition_cache_debug_information():
    return [('BC_CACHE SIZE', len(Asm._bc_cache), 'dict size of _bc_cache')]

