from _weakrefset import WeakSet
from collections import defaultdict, namedtuple
from contextlib import contextmanager
from animation import AnimationContext, get_throwaway_animation_context
from animation.posture_manifest import PostureManifest, AnimationParticipant, PostureManifestEntry, MATCH_ANY, MATCH_NONE
from carry import PARAM_CARRY_STATE, set_carry_track_param_if_needed
from element_utils import build_critical_section
from interactions.interaction_finisher import FinishingType
from interactions.utils.animation import flush_all_animations, get_auto_exit
from interactions.utils.animation_reference import TunableAnimationReference
from interactions.utils.routing import RouteTargetType
from objects.components.censor_grid_component import CensorState
from postures import PostureTrack, PostureEvent, get_best_supported_posture
from postures.posture_primitive import PosturePrimitive
from sims.sim_outfits import TunableOutfitChange
from sims4.collections import frozendict
from sims4.repr_utils import standard_repr
from sims4.tuning.geometric import TunablePolygon, TunableVector3
from sims4.tuning.instances import TunedInstanceMetaclass
from sims4.tuning.tunable import Tunable, TunableTuple, TunableList, TunableReference, TunableResourceKey, OptionalTunable, TunableEnumFlags, TunableEnumEntry
from sims4.tuning.tunable_base import SourceQueries, GroupNames, FilterTag
from sims4.utils import classproperty, flexmethod
from singletons import DEFAULT, UNSET
from snippets import define_snippet, POSTURE_TYPE_LIST
from uid import unique_id
import animation
import animation.arb
import animation.asm
import caches
import element_utils
import enum
import interactions.constraints
import services
import sims4.log
TRANSITION_POSTURE_PARAM_NAME = 'transitionPosture'
logger = sims4.log.Logger('Postures')

class PosturePreconditions(enum.IntFlags):
    __qualname__ = 'PosturePreconditions'
    NONE = 0
    SAME_TARGET = 1

class PostureSupportInfo(TunableTuple):
    __qualname__ = 'PostureSupportInfo'

    def __init__(self, **kwargs):
        super().__init__(posture_type=TunableReference(services.posture_manager(), description='Posture that is supported by this object.'), required_clearance=OptionalTunable(Tunable(float, 1, description='Amount of clearance you need in front of the object or part for this posture to be supported.')), **kwargs)

(TunablePostureTypeListReference, TunablePostureTypeListSnippet) = define_snippet(POSTURE_TYPE_LIST, TunableList(PostureSupportInfo(), description='\n                                        A list of postures this object supports and any information about how\n                                        that posture can be used on the object in game.\n                                        '))

@unique_id('id')
class Posture(metaclass=TunedInstanceMetaclass, manager=services.posture_manager()):
    __qualname__ = 'Posture'
    ASM_SOURCE = '_asm_key'
    INSTANCE_TUNABLES = {'mobile': Tunable(bool, False, tuning_filter=FilterTag.EXPERT_MODE, description='If True, the Sim can route in this posture.'), 'unconstrained': Tunable(bool, False, description='If True, the Sim can stand anywhere in this posture.'), 'ownable': Tunable(bool, True, description="If True, This posture is ownable by interactions. Ex: A posture like carry_nothing should not be ownable, because it will cause strange cancelations that don't make sense."), 'social_geometry': TunableTuple(social_space=TunablePolygon(description="\n             The special geometry override for socialization in this posture. This defines\n             where the Sim's attention is focused and informs the social positioning system where\n             each Sim should stand to look most natural when interacting with this Sim. \n             Ex: we override the social geometry for a Sim who is bartending to be a wider cone \n             and be in front of the bar instead of embedded within the bar. This encourages Sims \n             to stand on the customer-side of the bar to socialize with this Sim instead of coming \n             around the back."), focal_point=TunableVector3(sims4.math.Vector3.ZERO(), description='Focal point when socializing in this posture, relative to Sim'), tuning_filter=FilterTag.EXPERT_MODE, description='The special geometry for socialization in this posture.'), ASM_SOURCE: TunableResourceKey(None, [sims4.resources.Types.STATEMACHINE], tuning_group=GroupNames.ANIMATION, description='The posture ASM.', category='asm'), '_actor_param_name': Tunable(str, 'x', source_location=ASM_SOURCE, source_query=SourceQueries.ASMActorSim, tuning_group=GroupNames.ANIMATION, description="\n             The name of the actor parameter in this posture's ASM. By default, this is x, and you should probably\n             not change it."), '_target_name': Tunable(str, None, source_location=ASM_SOURCE, source_query=SourceQueries.ASMActorAll, tuning_group=GroupNames.ANIMATION, description="\n             The actor name for the target object of this posture. Leave empty for postures with no target. \n             In the case of a posture that targets an object, it should be the name of the object actor in \n             this posture's ASM. \n             ."), '_enter_state_name': Tunable(str, None, source_location=ASM_SOURCE, source_query=SourceQueries.ASMState, tuning_group=GroupNames.ANIMATION, description='\n             The name of the entry state for the posture in the ASM. \n             All postures should have two public states, not including entry and exit.\n             This should be the first of the two states.'), '_exit_state_name': Tunable(str, 'exit', source_location=ASM_SOURCE, source_query=SourceQueries.ASMState, tuning_group=GroupNames.ANIMATION, description='\n             The name of the exit state in the ASM. By default, this is exit.'), '_state_name': Tunable(str, None, source_location=ASM_SOURCE, source_query=SourceQueries.ASMState, tuning_group=GroupNames.ANIMATION, description='\n             The main state name for the looping posture pose in the ASM.\n             All postures should have two public states, not including entry and exit.\n             This should be the second of the two states.'), '_supported_postures': TunableList(TunableTuple(posture_type=TunableReference(services.posture_manager(), description='A supported posture.'), entry=Tunable(bool, True, description=''), exit=Tunable(bool, True, description=''), transition_cost=OptionalTunable(Tunable(float, 1, description="Cost of the transition to this posture then calculating the Sim's transition sequence.")), preconditions=TunableEnumFlags(PosturePreconditions, PosturePreconditions.NONE), description='A list of postures that this posture supports entrance from and exit to. Defaults to [stand]')), '_supports_carry': Tunable(description='\n            Whether or not there should be a carry version of this posture in\n            the posture graph.\n            ', tunable_type=bool, default=True), 'censor_level': TunableEnumEntry(CensorState, None, tuning_filter=FilterTag.EXPERT_MODE, description="\n                                                                                The type of censor grid that will be applied to any Sim in this posture.  \n                                                                                A censor grid obscures different parts of a Sim's body depending on what censor level it is set at.  \n                                                                                For example, the LHAND censor level will obscure a Sim's left hand.  \n                                                                                By default, postures have no censor level association, which means no censor grid will be applied to them \n                                                                                and every part of their body will be visible when in this posture.\n                                                                                "), 'outfit_change': TunableOutfitChange(description='\n            Define what outfits the Sim is supposed to wear when entering or\n            exiting this posture.\n            '), 'cost': Tunable(float, 0, description='( >= 0 ) The distance a sim is willing to pay to avoid using this posture (higher number discourage using the posture)'), 'idle_animation': TunableAnimationReference(callback=None, tuning_group=GroupNames.ANIMATION, description='The animation for a Sim to play while in this posture and waiting for interaction behavior to start.'), 'jig': OptionalTunable(TunableReference(manager=services.definition_manager(), description='The jig to place while the Sim is in this posture.'), description='An optional Jig to place while the Sim is in this posture.'), 'allow_affinity': Tunable(bool, True, description="\n                            If True, Sims will prefer to use this posture if someone\n                            they're interacting with is using the posture.\n                            \n                            Ex: If you chat with a sitting sim, you will prefer to\n                            sit with them and chat.\n                            "), 'additional_put_down_distance': Tunable(description="\n            An additional distance in front of the Sim to start searching for\n            valid put down locations when in this posture.\n            \n            This tunable is only respected for the Sim's body posture.\n            ", tunable_type=float, default=0.5), 'additional_interaction_jig_fgl_distance': Tunable(description='\n            An additional distance (in meters) in front of the Sim to start \n            searching when using FGL to place a Jig to run an interaction.', tunable_type=float, default=0)}
    DEFAULT_POSTURE = TunableReference(services.get_instance_manager(sims4.resources.Types.POSTURE), description="The default affordance to use as the supported posture if nothing is tuned in a Posture's 'Supported Postures'")
    IS_BODY_POSTURE = True

    def test(self):
        return True

    @classproperty
    def target_name(cls):
        return cls._target_name

    def __init__(self, sim, target, track, animation_context=None):
        self._create_asm(animation_context=animation_context)
        self._source_interaction = None
        self._primitive = None
        self._owning_interactions = set()
        self._sim = None
        self._target = None
        self._target_part = None
        self._surface_target_ref = None
        self._track = None
        self._slot_constraint = UNSET
        self._context = None
        self._asm_registry = defaultdict(dict)
        self._asms_with_posture_info = set()
        self._failed_parts = set()
        self._bind(sim, target, track)
        self._linked_posture = None
        self._entry_anim_complete = False
        self._exit_anim_complete = False
        self.external_transition = False
        self._active_cancel_aops = WeakSet()
        self._saved_exit_clothing_change = None

    @classproperty
    def name(cls):
        return cls._posture_name or cls.__name__

    @property
    def posture_context(self):
        return self._context

    @property
    def animation_context(self):
        return self._animation_context

    @property
    def surface_target(self):
        return self.sim.posture_state.surface_target

    @property
    def source_interaction(self):
        return self._source_interaction

    @source_interaction.setter
    def source_interaction(self, value):
        if value is None:
            logger.error('Posture {} get a None source interaction set', self)
            return
        self._source_interaction = value

    @property
    def owning_interactions(self):
        return self._owning_interactions

    def last_owning_interaction(self, interaction):
        if interaction not in self.owning_interactions:
            return False
        for owning_interaction in self.owning_interactions:
            while owning_interaction is not interaction and not owning_interaction.is_finishing:
                return False
        return True

    def add_owning_interaction(self, interaction):
        self._owning_interactions.add(interaction)

    def remove_owning_interaction(self, interaction):
        self._owning_interactions.remove(interaction)

    def clear_owning_interactions(self):
        from interactions.base.interaction import OWNS_POSTURE_LIABILITY
        try:
            for interaction in list(self._owning_interactions):
                interaction.remove_liability((OWNS_POSTURE_LIABILITY, self.track))
        finally:
            self._owning_interactions.clear()

    def add_cancel_aop(self, cancel_aop):
        self._active_cancel_aops.add(cancel_aop)

    def kill_cancel_aops(self):
        for interaction in self._active_cancel_aops:
            interaction.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='PostureOwnership. This posture wasgoing to be canceled, but another interaction took ownership over the posture. Most likely the current posture was already valid for the new interaction.')

    def get_idle_behavior(self):
        if self.idle_animation is None:
            logger.error('{} has no idle animation tuning! This tuning is required for all body postures!', self)
            return
        if self.source_interaction is None:
            logger.error('Posture({}) on sim:{} has no source interaction.', self, self.sim, owner='Maxr', trigger_breakpoint=True)
            return
        if self.owning_interactions and not self.multi_sim:
            interaction = list(self.owning_interactions)[0]
        else:
            interaction = self.source_interaction
        idle = self.idle_animation(interaction)
        auto_exit = get_auto_exit((self.sim,), asm=idle.get_asm())
        return build_critical_section(auto_exit, idle, flush_all_animations)

    def log_info(self, phase, msg=None):
        from sims.sim_log import log_posture
        log_posture(phase, self, msg=msg)

    def _create_asm(self, animation_context=None):
        self._animation_context = animation_context or AnimationContext()
        self._animation_context.add_posture_owner(self)
        self._asm = animation.asm.Asm(self._asm_key, self._animation_context)

    _provided_postures = PostureManifest().intern()
    _posture_name = None
    family_name = None

    @classproperty
    def posture_type(cls):
        return cls

    @classmethod
    def is_same_posture_or_family(cls, other_cls):
        if cls == other_cls:
            return True
        return cls.family_name is not None and cls.family_name == other_cls.family_name

    @classmethod
    def _tuning_loading_callback(cls):

        def delclassattr(name):
            if name in cls.__dict__:
                delattr(cls, name)

        delclassattr('_provided_postures')
        delclassattr('_posture_name')
        delclassattr('family_name')

    PostureTransitionData = namedtuple('PostureTransitionData', ('preconditions', 'transition_cost'))
    _posture_transitions = {}

    @staticmethod
    def _add_posture_transition(source_posture, dest_posture, transition_data):
        Posture._posture_transitions[(source_posture, dest_posture)] = transition_data

    @contextmanager
    def __reload_context__(oldobj, newobj):
        posture_transitions = dict(oldobj._posture_transitions)
        yield None
        oldobj._posture_transitions.update(posture_transitions)

    @classmethod
    def _tuning_loaded_callback(cls):
        for posture_data in cls._supported_postures:
            transition_data = cls.PostureTransitionData(posture_data.preconditions, posture_data.transition_cost)
            if posture_data.entry:
                cls._add_posture_transition(posture_data.posture_type, cls, transition_data)
            while posture_data.exit:
                cls._add_posture_transition(cls, posture_data.posture_type, transition_data)
        asm = animation.asm.Asm(cls._asm_key, get_throwaway_animation_context())
        provided_postures = asm.provided_postures
        if not provided_postures:
            return
        specific_name = None
        family_name = None
        for entry in provided_postures:
            entry_specific_name = entry.specific
            if not entry_specific_name:
                raise ValueError('{} must provide a specific posture for all posture definition rows.'.format(asm.name))
            if specific_name is None:
                specific_name = entry_specific_name
            elif entry_specific_name != specific_name:
                raise ValueError('{}: {} provides multiple specific postures: {}'.format(cls, asm.name, [specific_name, entry_specific_name]))
            entry_family_name = entry.family
            while entry_family_name:
                if family_name is None:
                    family_name = entry_family_name
                elif entry_family_name != family_name:
                    raise ValueError('{}: {} provides multiple family postures: {}'.format(cls, asm.name, [family_name, entry_family_name]))
        cls._provided_postures = provided_postures
        cls._posture_name = specific_name
        cls.family_name = family_name
        if cls.idle_animation is None:
            logger.error('{} has no idle_animation tuned. Every posture must have an idle animation suite!', cls)

    @flexmethod
    def get_provided_postures(cls, inst, surface_target=DEFAULT, concrete=False):
        if inst is None:
            return cls._provided_postures
        provided_postures = inst._provided_postures
        surface_target = inst._resolve_surface_target(surface_target)
        if surface_target is None or surface_target == MATCH_NONE:
            surface_restriction = MATCH_NONE
        elif surface_target == MATCH_ANY:
            surface_restriction = surface_target
        else:
            surface_restriction = surface_target if concrete else AnimationParticipant.SURFACE
        if surface_restriction is not None:
            filter_entry = PostureManifestEntry(MATCH_ANY, MATCH_ANY, MATCH_ANY, MATCH_ANY, MATCH_ANY, MATCH_ANY, surface_restriction, True)
            provided_postures = provided_postures.intersection_single(filter_entry)
        return provided_postures

    def _resolve_surface_target(self, surface_target):
        if surface_target is DEFAULT:
            return self.surface_target
        return surface_target

    def _bind(self, sim, target, track):
        if self.sim is sim and self.target is target and self.target_part is None or self.target_part is target and self._track == track:
            return
        if self.target is not None and track == PostureTrack.BODY:
            part_suffix = self.get_part_suffix()
            for asm in self._asms_with_posture_info:
                while not asm.remove_virtual_actor(self._target_name, self.target, suffix=part_suffix):
                    logger.error('Failed to remove previously-bound virtual posture container {} from asm {} on posture {}.', self.target, asm, self)
        if sim is not None:
            self._sim = sim.ref()
        else:
            self._sim = None
        self._intersection = None
        self._asm_registry.clear()
        self._asms_with_posture_info.clear()
        if target is not None:
            if self._target_name is not None and target is not sim:
                (route_type, _) = target.route_target
                if self._target is not None and (self._target() is not None and self._target().parts is not None) and target in self._target().parts:
                    self._target_part = target.ref()
                else:
                    self._target_part = None
                    self._target = target.ref()
            else:
                self._target = target.ref()
        else:
            self._target_part = None
            self._target = None
        if track is not None:
            self._track = track
        else:
            self._track = None
        self._slot_constraint = UNSET

    def rebind(self, target, animation_context=None):
        self._release_animation_context()
        self._create_asm(animation_context=animation_context)
        self._bind(self.sim, target, self.track)

    def reset(self):
        if self._saved_exit_clothing_change is not None:
            self.sim.sim_info.set_current_outfit(self._saved_exit_clothing_change)
            self._saved_exit_clothing_change = None
        self._entry_anim_complete = False
        self._exit_anim_complete = False
        self._release_animation_context()
        self._source_interaction = None

    def _release_animation_context(self):
        if self._animation_context is not None:
            self._animation_context.remove_posture_owner(self)
            self._animation_context = None

    def kickstart_gen(self, timeline, posture_state):
        if PostureTrack.is_carry(self.track):
            is_body = False
            self.asm.set_parameter('location', 'inventory')
        else:
            is_body = True
            self.source_interaction = self.sim.create_default_si()
        idle_arb = animation.arb.Arb()
        self.append_transition_to_arb(idle_arb, None)
        self.append_idle_to_arb(idle_arb)
        begin_element = self.get_begin(idle_arb, posture_state)
        yield element_utils.run_child(timeline, begin_element)
        if is_body:
            default_si = self.source_interaction
            yield default_si.prepare_gen(timeline)
            yield default_si.enter_si_gen(timeline)
            yield default_si.setup_gen(timeline)
            result = yield default_si.perform_gen(timeline)
            if not result:
                raise RuntimeError('Sim: {} failed to enter default si: {}'.format(self, default_si))

    def get_asm(self, animation_context, asm_key, setup_asm_func, use_cache=True, cache_key=DEFAULT, interaction=None, posture_manifest_overrides=None, **kwargs):
        dict_key = animation_context if cache_key is DEFAULT else cache_key
        if use_cache:
            asm_dict = self._asm_registry[dict_key]
            asm = asm_dict.get(asm_key)
            if asm is None:
                asm = animation.asm.Asm(asm_key, context=animation_context, posture_manifest_overrides=posture_manifest_overrides)
                if interaction is not None:
                    asm.on_state_changed_events.append(interaction.on_asm_state_changed)
                asm_dict[asm_key] = asm
        else:
            asm = animation.asm.Asm(asm_key, context=animation_context)
            if interaction is not None:
                asm.on_state_changed_events.append(interaction.on_asm_state_changed)
        if asm.current_state == 'exit':
            asm.set_current_state('entry')
        if not (setup_asm_func is not None and setup_asm_func(asm)):
            return
        return asm

    def remove_from_cache(self, cache_key):
        if cache_key in self._asm_registry:
            for asm in self._asm_registry[cache_key].values():
                del asm._on_state_changed_events[:]
            del self._asm_registry[cache_key]

    def _create_primitive(self, animate_in, dest_state):
        return PosturePrimitive(self, animate_in, dest_state, self._context)

    def _on_reset(self):
        self._primitive = None

    def __str__(self):
        return '{0}:{1}'.format(self.name, self.id)

    def __repr__(self):
        return standard_repr(self, self.id, self.target)

    @property
    def sim(self):
        if self._sim is not None:
            return self._sim()

    @property
    def target(self):
        if self._target_part is not None:
            return self._target_part()
        if self._target is not None:
            return self._target()

    @property
    def target_part(self):
        if self._target_part is not None:
            return self._target_part()

    @property
    def track(self):
        return self._track

    @property
    def is_active_carry(self):
        return PostureTrack.is_carry(self.track) and self.target is not None

    def get_slot_offset_locked_params(self, anim_overrides=None):
        locked_params = self._locked_params
        if anim_overrides is not None:
            locked_params += anim_overrides.params
        locked_params += {'transitionPosture': 'stand'}
        return locked_params

    def build_slot_constraint(self, create_posture_state_spec_fn=None):
        if self.target is not None and PostureTrack.is_body(self.track):
            return interactions.constraints.RequiredSlot.create_slot_constraint(self, create_posture_state_spec_fn=create_posture_state_spec_fn)

    @property
    def slot_constraint_simple(self):
        if self._slot_constraint is UNSET:
            self._slot_constraint = self.build_slot_constraint(create_posture_state_spec_fn=lambda *_, **__: None)
        return self._slot_constraint

    @property
    def slot_constraint(self):
        if self._slot_constraint is UNSET:
            self._slot_constraint = self.build_slot_constraint()
        return self._slot_constraint

    @classproperty
    def multi_sim(cls):
        return False

    @property
    def is_puppet(self):
        return False

    @property
    def is_mirrored(self):
        if self.target is not None and self.target.is_part:
            return self.target.is_mirrored() or False
        return False

    @property
    def linked_posture(self):
        return self._linked_posture

    @linked_posture.setter
    def linked_posture(self, posture):
        self._linked_posture = posture

    @property
    def asm(self):
        return self._asm

    @property
    def _locked_params(self):
        anim_overrides_actor = self.sim.get_anim_overrides(self._actor_param_name)
        params = anim_overrides_actor.params
        if self.target is not None:
            anim_overrides_target = self.target.get_anim_overrides(self.target_name)
            if anim_overrides_target is not None:
                params += anim_overrides_target.params
            if self.target.is_part:
                part_suffix = self.target.part_suffix
                if part_suffix is not None:
                    params += {'subroot': part_suffix}
        if self.is_mirrored is not None:
            params += {'isMirrored': self.is_mirrored}
        return params

    @property
    def locked_params(self):
        if self.slot_constraint is None or self.slot_constraint.locked_params is None:
            return self._locked_params
        return self._locked_params + self.slot_constraint.locked_params

    def _setup_asm_container_parameter(self, asm, target, actor_name, part_suffix, target_name=None):
        if asm in self._asms_with_posture_info:
            return True
        if target_name is None:
            target_name = self._target_name
        result = False
        if target is not None and target_name is not None:
            result = asm.add_potentially_virtual_actor(actor_name, self.sim, target_name, target, part_suffix, target_participant=AnimationParticipant.CONTAINER)
            if not self._setup_custom_posture_target_name(asm, target):
                logger.error('Failed to set custom posture target {}', target)
                result = False
        if result:
            self._asms_with_posture_info.add(asm)
        return result

    def _setup_custom_posture_target_name(self, asm, target):
        _custom_target_name = target.custom_posture_target_name
        if _custom_target_name in asm.actors:
            (_custom_target_actor, _) = asm.get_actor_and_suffix(_custom_target_name)
            if _custom_target_actor is None:
                return asm.set_actor(target.custom_posture_target_name, target, suffix=None, actor_participant=AnimationParticipant.CONTAINER)
        return True

    def _setup_asm_carry_parameter(self, asm, target):
        pass

    def get_part_suffix(self, target=DEFAULT):
        if target is DEFAULT:
            target = self.target
        if target is not None:
            return target.part_suffix

    def setup_asm_posture(self, asm, sim, target, locked_params=frozendict(), actor_param_name=DEFAULT):
        if actor_param_name is DEFAULT:
            actor_param_name = self._actor_param_name
        if asm is None:
            logger.error('Attempt to setup an asm whose value is None.')
            return False
        if sim is None:
            logger.error('Attempt to setup an asm {0} on a sim whose value is None.', asm)
            return False
        if not asm.set_actor(actor_param_name, sim, actor_participant=AnimationParticipant.ACTOR):
            logger.error('Failed to set actor sim: {0} on asm {1}', actor_param_name, asm)
            return False
        sim.set_mood_asm_parameter(asm, actor_param_name)
        sim.set_trait_asm_parameters(asm, actor_param_name)
        if target.is_part:
            is_mirrored = target.is_mirrored()
            if is_mirrored is not None:
                locked_params += {'isMirrored': is_mirrored}
        part_suffix = self.get_part_suffix()
        if not (target is not None and self._target_name is not None and self._setup_asm_container_parameter(asm, target, actor_param_name, part_suffix)):
            logger.error('Failed to set actor target: {0} on asm {1}', self._target_name, asm)
            return False
        if not PostureTrack.is_body(self.track):
            self._update_non_body_posture_asm()
            sim.on_posture_event.append(self._update_on_posture_event)
        if locked_params:
            virtual_actor_map = {self._target_name: self.target}
            asm.update_locked_params(locked_params, virtual_actor_map)
        self._setup_asm_carry_parameter(asm, target)
        return True

    def _update_on_posture_event(self, change, dest_state, track, old_value, new_value):
        if change == PostureEvent.POSTURE_CHANGED:
            if track != self.track:
                if new_value is not None:
                    self._update_non_body_posture_asm()
                    if new_value != self:
                        self.sim.on_posture_event.remove(self._update_on_posture_event)
            elif new_value != self:
                self.sim.on_posture_event.remove(self._update_on_posture_event)

    def _update_non_body_posture_asm(self):
        if self.sim.posture.target is not None:
            (previous_target, previous_suffix) = self.asm.get_virtual_actor_and_suffix(self._actor_param_name, self.sim.posture._target_name)
            if previous_target is not None:
                self.asm.remove_virtual_actor(self.sim.posture._target_name, previous_target, previous_suffix)
        self.sim.posture.setup_asm_interaction(self.asm, self.sim, self.target, self._actor_param_name, self._target_name)

    def _setup_asm_interaction_add_posture_info(self, asm, sim, target, actor_name, target_name, carry_target, carry_target_name, surface_target=DEFAULT, carry_track=DEFAULT):

        def set_posture_param(posture_param_str, carry_param_str, carry_actor_name, surface_actor_name):
            if not asm.set_actor_parameter(actor_name, sim, 'posture', posture_param_str):
                if not asm.set_parameter('posture', posture_param_str):
                    return False
                logger.warn('Backwards compatibility with old posture parameter required by {}', asm.name)
            if not asm.set_actor_parameter(actor_name, sim, PARAM_CARRY_STATE, carry_param_str):
                asm.set_parameter('carry', carry_param_str)
            asm.set_parameter('isMirrored', self.is_mirrored)
            if target_name == carry_actor_name and target is not None:
                set_carry_track_param_if_needed(asm, sim, target_name, target, carry_track=carry_track)
            if carry_actor_name is not None and carry_target_name == carry_actor_name and carry_target is not None:
                set_carry_track_param_if_needed(asm, sim, carry_target_name, carry_target, carry_track=carry_track)
            if surface_actor_name is not None:
                _surface_target = self._resolve_surface_target(surface_target)
                if _surface_target:
                    asm.add_potentially_virtual_actor(actor_name, sim, surface_actor_name, _surface_target, target_participant=AnimationParticipant.SURFACE)
                else:
                    return False
            return True

        def build_carry_str(carry_state):
            if carry_state[0]:
                if carry_state[1]:
                    return 'both'
                return 'left'
            if carry_state[1]:
                return 'right'
            return 'none'

        def setup_asm_container_parameter(chosen_posture_type):
            container_name = chosen_posture_type.target_name
            if not container_name:
                return True
            part_suffix = self.get_part_suffix()
            if self._setup_asm_container_parameter(asm, self.target, actor_name, part_suffix, target_name=container_name):
                return True
            return False

        carry_state = sim.posture_state.get_carry_state()
        supported_postures = asm.get_supported_postures_for_actor(actor_name)
        if supported_postures is None:
            return True
        filtered_supported_postures = self.sim.filter_supported_postures(supported_postures)
        if surface_target is DEFAULT:
            surface_target = self._resolve_surface_target(surface_target)
            if surface_target is not None:
                surface_target_provided = MATCH_ANY
            else:
                surface_target_provided = MATCH_NONE
        elif surface_target is not None:
            surface_target_provided = MATCH_ANY
        else:
            surface_target_provided = MATCH_NONE
        provided_postures = self.get_provided_postures(surface_target=surface_target_provided)
        best_supported_posture = get_best_supported_posture(provided_postures, filtered_supported_postures, carry_state)
        if best_supported_posture is None:
            logger.debug('Failed to find supported posture for actor {} on {} for posture ({}) and carry ({}).  Interaction info claims this should work.', actor_name, asm, self, carry_state)
            return False
        carry_param_str = build_carry_str(carry_state)
        carry_actor_name = best_supported_posture.carry_target
        surface_actor_name = best_supported_posture.surface_target
        if not isinstance(surface_actor_name, str):
            surface_actor_name = None
        param_str_specific = best_supported_posture.posture_param_value_specific
        if best_supported_posture.is_overlay:
            return True
        if param_str_specific and set_posture_param(param_str_specific, carry_param_str, carry_actor_name, surface_actor_name) and setup_asm_container_parameter(best_supported_posture.posture_type_specific):
            return True
        param_str_family = best_supported_posture.posture_param_value_family
        if best_supported_posture.is_overlay:
            return True
        if param_str_family and set_posture_param(param_str_family, carry_param_str, carry_actor_name, surface_actor_name) and setup_asm_container_parameter(best_supported_posture.posture_type_family):
            return True
        return False

    def setup_asm_interaction(self, asm, sim, target, actor_name, target_name, carry_target=None, carry_target_name=None, create_target_name=None, surface_target=DEFAULT, carry_track=DEFAULT, actor_participant=AnimationParticipant.ACTOR, invalid_expected=False):
        if target_name is not None and (target_name == self._target_name and (target is not None and self.target is not None)) and target.id != self.target.id:
            if not invalid_expected:
                logger.error('Animation targets a different object than its posture, but both use the same actor name for the object. This is impossible to resolve. Actor name: {}, posture target: {}, interaction target: {}', target_name, target, self.target)
            return False
        if not asm.set_actor(actor_name, sim, actor_participant=actor_participant):
            logger.error('Failed to set actor: {0} on asm {1}', actor_name, asm)
            return False
        if sim.asm_auto_exit.apply_carry_interaction_mask:
            asm._set_actor_trackmask_override(actor_name, 50000, 'Trackmask_CarryInteraction')
        if target is not None and target_name is not None:
            from sims.sim import Sim
            if isinstance(target, Sim):
                if not target.posture.setup_asm_interaction(asm, target, None, target_name, None, actor_participant=AnimationParticipant.TARGET):
                    return False
            else:
                asm.add_potentially_virtual_actor(actor_name, sim, target_name, target, target_participant=AnimationParticipant.TARGET)
                anim_overrides = target.get_anim_overrides(target_name)
                if anim_overrides is not None and anim_overrides.params:
                    virtual_actor_map = {self._target_name: self.target}
                    asm.update_locked_params(anim_overrides.params, virtual_actor_map)
            if not self._setup_custom_posture_target_name(asm, target):
                logger.error('Unable to setup custom posture target name for {} on {}', target, asm)
        _carry_target_name = carry_target_name or create_target_name
        if carry_target is not None and _carry_target_name is not None:
            asm.add_potentially_virtual_actor(actor_name, sim, _carry_target_name, carry_target, target_participant=AnimationParticipant.CARRY_TARGET)
        if not self._setup_asm_interaction_add_posture_info(asm, sim, target, actor_name, target_name, carry_target, carry_target_name, surface_target, carry_track):
            return False
        return True

    def get_begin(self, animate_in, dest_state):
        if self._primitive is not None:
            raise RuntimeError('Posture Entry({}) called multiple times without a paired exit.'.format(self))
        self._primitive = self._create_primitive(animate_in, dest_state)
        return self._primitive.next_stage()

    def begin(self, animate_in, dest_state, context):
        self._context = context

        def _do_begin(timeline):
            logger.debug('{} begin Posture: {}', self.sim, self)
            begin = self.get_begin(animate_in, dest_state)
            result = yield element_utils.run_child(timeline, begin)
            return result

        return _do_begin

    def get_end(self):
        if self._primitive is None:
            raise RuntimeError('Posture Exit({}) called multiple times without a paired entry. Sim: {}'.format(self, self.sim))
        exit_behavior = self._primitive.next_stage()
        self._primitive = None
        return exit_behavior

    def end(self):

        def _do_end(timeline):
            logger.debug('{} end Posture: {}', self.sim, self)
            end = self.get_end()
            result = yield element_utils.run_child(timeline, end)
            return result

        return _do_end

    def add_transition_extras(self, sequence):
        return sequence

    def enumerate_goal_list_ids(self, goal_list):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        if goal_list is not None:
            for (index, goal) in enumerate(goal_list):
                goal.tag = index

    def get_locked_params(self, source_posture):
        if source_posture is None:
            return self._locked_params
        updates = {TRANSITION_POSTURE_PARAM_NAME: source_posture.name}
        if source_posture.target is None:
            return self._locked_params + updates
        if source_posture.target.is_part and self.target is not None and self.target.is_part:
            if self.target.is_mirrored(source_posture.target):
                direction = 'fromSimLeft'
            else:
                direction = 'fromSimRight'
            updates['direction'] = direction
        return self._locked_params + updates

    def append_transition_to_arb(self, arb, source_posture, locked_params=frozendict(), **kwargs):
        if not self._entry_anim_complete:
            locked_params += self.get_locked_params(source_posture)
            if source_posture is not None:
                locked_params += {TRANSITION_POSTURE_PARAM_NAME: source_posture.name}
            if not self.setup_asm_posture(self.asm, self.sim, self.target, locked_params=locked_params):
                logger.error('Failed to setup the asm for the posture {}', self)
                return
            self._setup_asm_target_for_transition(source_posture)
            self.asm.request(self._enter_state_name, arb)
            linked_posture = self.linked_posture
            if linked_posture is not None:
                locked_params = linked_posture.get_locked_params(source_posture)
                linked_posture.setup_asm_posture(linked_posture._asm, linked_posture.sim, linked_posture.target, locked_params=locked_params)
                if not self.multi_sim:
                    linked_posture._asm.request(linked_posture._enter_state_name, arb)
            self._entry_anim_complete = True

    def append_idle_to_arb(self, arb):
        self.asm.request(self._state_name, arb)
        if self._linked_posture is not None:
            self._linked_posture.append_idle_to_arb(arb)

    def append_exit_to_arb(self, arb, dest_state, dest_posture, var_map, locked_params=frozendict()):
        if not self._exit_anim_complete:
            self._setup_asm_target_for_transition(dest_posture)
            locked_params += self.locked_params
            if dest_posture is not None:
                locked_params += {TRANSITION_POSTURE_PARAM_NAME: dest_posture.name}
            if locked_params:
                virtual_actor_map = {self._target_name: self.target}
                self.asm.update_locked_params(locked_params, virtual_actor_map)
            self.asm.request(self._exit_state_name, arb)
            self._exit_anim_complete = True

    def _setup_asm_target_for_transition(self, transition_posture):
        if transition_posture is not None and transition_posture._target_name != self._target_name and transition_posture._target_name in self.asm.actors:
            (previous_target, previous_suffix) = self.asm.get_virtual_actor_and_suffix(self._actor_param_name, transition_posture._target_name)
            if previous_target is not None:
                self.asm.remove_virtual_actor(transition_posture.target_name, previous_target, previous_suffix)
            if not transition_posture._setup_asm_container_parameter(self.asm, transition_posture.target, self._actor_param_name, transition_posture.get_part_suffix()):
                logger.error('Failed to setup target container {} on {} from transition posture {}', transition_posture._target_name, self, transition_posture)
                return False
        return True

    def post_route_clothing_change(self, interaction, do_spin=True, **kwargs):
        si_outfit_change = interaction.outfit_change
        if si_outfit_change is not None and si_outfit_change.posture_outfit_change_overrides is not None:
            overrides = si_outfit_change.posture_outfit_change_overrides.get(self.posture_type)
            if overrides is not None:
                entry_outfit = overrides.get_on_entry_outfit(interaction)
                if entry_outfit is not None:
                    return overrides.get_on_entry_change(interaction, do_spin=do_spin, **kwargs)
        if self.outfit_change is not None:
            return self.outfit_change.get_on_entry_change(interaction, do_spin=do_spin, **kwargs)

    @property
    def saved_exit_clothing_change(self):
        return self._saved_exit_clothing_change

    def transfer_exit_clothing_change(self, clothing_change):
        self._saved_exit_clothing_change = clothing_change

    def prepare_exit_clothing_change(self, interaction):
        si_outfit_change = interaction.outfit_change
        if si_outfit_change is not None and si_outfit_change.posture_outfit_change_overrides is not None:
            overrides = si_outfit_change.posture_outfit_change_overrides.get(self.posture_type)
            if overrides is not None:
                exit_outfit = overrides.get_on_exit_outfit(interaction)
                if exit_outfit is not None:
                    self._saved_exit_clothing_change = overrides.get_on_exit_outfit(interaction)
                    return
        if self.outfit_change and self._saved_exit_clothing_change is None:
            self._saved_exit_clothing_change = self.outfit_change.get_on_exit_outfit(interaction)

    def exit_clothing_change(self, interaction, *, sim=DEFAULT, do_spin=True, **kwargs):
        if self._saved_exit_clothing_change is None or interaction is None:
            return
        if sim is DEFAULT:
            sim = interaction.sim
        sim_info = sim.sim_info
        return build_critical_section(sim_info.sim_outfits.get_change_outfit_element(self._saved_exit_clothing_change, do_spin=do_spin), flush_all_animations)

    def ensure_exit_clothing_change_application(self):
        if self.sim.posture_state.body is not self and self._saved_exit_clothing_change is not None:
            self.sim.sim_info.set_current_outfit(self._saved_exit_clothing_change)
            self._saved_exit_clothing_change = None

    @classmethod
    def supports_posture_type(cls, posture_type):
        return (cls, posture_type) in cls._posture_transitions or (posture_type, cls) in cls._posture_transitions

    @classmethod
    def is_valid_transition(cls, source_posture_type, destination_posture_type, targets_match):
        transition_data = cls._posture_transitions.get((source_posture_type, destination_posture_type))
        if transition_data is None:
            return False
        if targets_match:
            return True
        preconditions = transition_data.preconditions
        if preconditions is not None and preconditions & PosturePreconditions.SAME_TARGET:
            return False
        return True

    @classmethod
    def get_transition_cost(cls, posture_type):
        transition_data = cls._posture_transitions.get((cls, posture_type))
        if transition_data is None:
            transition_data = cls._posture_transitions.get((posture_type, cls))
        if transition_data is not None:
            return transition_data.transition_cost

    @classmethod
    def is_valid_target(cls, sim, target, **kwargs):
        return True

