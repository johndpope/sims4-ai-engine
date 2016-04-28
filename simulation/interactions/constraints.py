import _resourceman
import collections
import math
from animation import get_throwaway_animation_context
from animation.asm import Asm, do_params_match
from animation.posture_manifest import PostureManifest, AnimationParticipant, SlotManifest, SlotManifestEntry, MATCH_ANY, PostureManifestEntry, UPPER_BODY, FULL_BODY, MATCH_NONE, PostureManifestOverrideValue, _get_posture_type_for_posture_name
from interactions.liability import Liability
from interactions.utils.animation import StubActor
from interactions.utils.animation_reference import TunableAnimationConstraint
from objects.slots import RuntimeSlot
from placement import find_good_location
from postures import PostureTrack, posture_state_spec
from postures.posture_specs import PostureSpec, PostureSpecVariable, PostureAspectSurface
from postures.posture_state_spec import PostureStateSpec, create_body_posture_state_spec
from routing import SURFACETYPE_WORLD
from sims.sim_info_types import SimInfoSpawnerTags
from sims4.collections import frozendict
from sims4.repr_utils import standard_repr
from sims4.tuning.geometric import TunableVector3
from sims4.tuning.tunable import Tunable, TunableTuple, TunableAngle, TunableEnumEntry, TunableVariant, TunableRange, TunableSingletonFactory, TunableList, OptionalTunable, TunableReference, HasTunableSingletonFactory, TunableSet, AutoFactoryInit
from sims4.utils import ImmutableType, InternMixin
from singletons import DEFAULT, SingletonType
from tag import Tag
import animation
import animation.animation_utils
import api_config
import caches
import enum
import interactions.utils.routing
import objects.slots
import placement
import postures
import routing
import services
import sims.sim_info_types
import sims4.geometry
import sims4.log
import sims4.math
import sims4.resources
logger = sims4.log.Logger('Constraints')
with sims4.reload.protected(globals()):

    def _create_stub_actor(animation_participant):
        return StubActor(int(animation_participant), debug_name=str(animation_participant))

    GLOBAL_STUB_ACTOR = _create_stub_actor(AnimationParticipant.ACTOR)
    GLOBAL_STUB_TARGET = _create_stub_actor(AnimationParticipant.TARGET)
    GLOBAL_STUB_CARRY_TARGET = _create_stub_actor(AnimationParticipant.CARRY_TARGET)
    GLOBAL_STUB_CREATE_TARGET = _create_stub_actor(AnimationParticipant.CREATE_TARGET)
    GLOBAL_STUB_SURFACE = _create_stub_actor(AnimationParticipant.SURFACE)
    GLOBAL_STUB_CONTAINER = _create_stub_actor(AnimationParticipant.CONTAINER)
    del _create_stub_actor

class IntersectPreference(enum.Int, export=False):
    __qualname__ = 'IntersectPreference'
    UNIVERSAL = 0
    SPECIAL = 1
    GEOMETRIC_PLUS = 2
    REQUIREDSLOT = 3
    GEOMETRIC = 4

class ScoringFunctionBase:
    __qualname__ = 'ScoringFunctionBase'

    def get_score(self, position, orientation, routing_surface):
        return 1.0

    def get_combined_score(self, position, orientation, routing_surface):
        return (self.get_score(position, orientation, routing_surface), 0.0)

    def get_posture_cost_attenuation(self, body_target):
        return 1.0

    @property
    def force_route(self):
        return False

class ScoringFunctionNative(ScoringFunctionBase):
    __qualname__ = 'ScoringFunctionNative'

    def __init__(self, scoring_function):
        self._c_scoring_function = scoring_function

    def get_score(self, position, orientation, routing_surface):
        score = self._c_scoring_function.get_score(position, routing_surface)
        return score

class ConstraintScoringFunctionLinear(ScoringFunctionNative):
    __qualname__ = 'ConstraintScoringFunctionLinear'

    def __init__(self, line_point1, line_point2, ideal_distance, max_distance):
        super().__init__(placement.ScoringFunctionLinear(line_point1, line_point2, ideal_distance, max_distance))

class ConstraintScoringFunctionRadial(ScoringFunctionNative):
    __qualname__ = 'ConstraintScoringFunctionRadial'

    def __init__(self, center, optimal_distance_from_center, optimal_width, max_distance_from_optimal, force_route=False):
        super().__init__(placement.ScoringFunctionRadial(center, optimal_distance_from_center, optimal_width, max_distance_from_optimal))
        self._force_route = force_route

    @property
    def force_route(self):
        return self._force_route

class ConstraintScoringFunctionAngular(ScoringFunctionNative):
    __qualname__ = 'ConstraintScoringFunctionAngular'

    def __init__(self, center, ideal_angle, ideal_angle_width, max_angle):
        super().__init__(placement.ScoringFunctionAngular(center, ideal_angle, ideal_angle_width, max_angle))

def _get_score_cache_key_fn(constraint, position, orientation):
    return (constraint.geometry, constraint._routing_surface, frozenset(constraint._scoring_functions), position, orientation.x, orientation.y, orientation.z, orientation.w)

class Constraint(ImmutableType, InternMixin):
    __qualname__ = 'Constraint'
    DEFAULT_FACING_RANGE = TunableAngle(sims4.math.PI/2, description='The size of the angle-range that sims should use when determining facing constraints.')
    INTERSECT_PREFERENCE = IntersectPreference.GEOMETRIC
    ROUTE_GOAL_COUNT_FOR_SCORING_FUNC = Tunable(int, 40, description='The number of points to sample when routing to a simple constraint that can be scored natively.')
    ROUTE_DISTANCE_WEIGHT_FACTOR = Tunable(float, 3, description="The multiplier on the 'diameter' of the constraint area for determining routing weight.  If constraints are vaguely circular, a value of 1 would zero-out distance attenuation.  Values above 1 will prefer the weight while values below 1 will prefer to minimize route distance.")
    MINIMUM_VALID_AREA = TunableRange(float, 2, minimum=0, description='The minimum area, in square meters, of the polygon for constraints to be considered valid (unless they have allow_small_intersections set).')
    IS_CONSTRAINT_SET = False
    IGNORE_OUTER_PENALTY_THRESHOLD = 0.8
    __slots__ = ('_hash',)

    @property
    def _debug_name(self):
        return ''

    def __init__(self, geometry=None, routing_surface=None, scoring_functions=(), posture_state_spec=None, age=None, slot_offset_info=None, debug_name='', allow_small_intersections=DEFAULT, flush_planner=False, allow_geometry_intersections=True, los_reference_point=DEFAULT, ignore_outer_penalty_threshold=IGNORE_OUTER_PENALTY_THRESHOLD, cost=0, objects_to_ignore=None, create_jig_fn=None):
        self._geometry = geometry
        self._routing_surface = routing_surface
        if routing_surface is None and geometry is not None and geometry.polygon is not None:
            logger.callstack('Trying to create a constraint with geometry that has no routing surface.', level=sims4.log.LEVEL_ERROR)
        self._posture_state_spec = posture_state_spec
        self._slot_offset_info = slot_offset_info
        self._age = age
        if allow_small_intersections is DEFAULT:
            allow_small_intersections = True if geometry is not None else False
        self._allow_small_intersections = allow_small_intersections
        self._flush_planner = flush_planner
        self._scoring_functions = scoring_functions
        weight_route_factor = 1
        if self._geometry is not None and self._geometry.polygon is not None:
            area = self._geometry.polygon.area()
            if area > 0:
                weight_route_factor = self.ROUTE_DISTANCE_WEIGHT_FACTOR*math.sqrt(area/sims4.math.PI)
        self._weight_route_factor = weight_route_factor
        self._allow_geometry_intersections = allow_geometry_intersections
        self._los_reference_point = los_reference_point
        self._ignore_outer_penalty_threshold = ignore_outer_penalty_threshold
        self._cost = cost
        self._objects_to_ignore = None if objects_to_ignore is None else frozenset(objects_to_ignore)
        self._create_jig_fn = create_jig_fn

    def __hash__(self):
        try:
            return self._hash
        except AttributeError:
            self._hash = h = hash(frozenset(self.__dict__.items()))
            return h

    def __eq__(self, other):
        if other is self:
            return True
        return other.__class__ == self.__class__ and (other.__hash__() == self.__hash__() and other.__dict__ == self.__dict__)

    def _copy(self, **overrides):
        inst = self.__class__.__new__(self.__class__)
        inst.__dict__.update(self.__dict__, **overrides)
        return inst

    def __repr__(self):
        if not __debug__:
            return 'Constraint(...)'
        args = []
        if self._debug_name:
            args.append(self._debug_name)
        if self._geometry is not None:
            args.append('geometry')
        if self._posture_state_spec is not None:
            args.append(str(self._posture_state_spec))
        return standard_repr(self, *args)

    def get_python_scoring_functions(self):
        return [fn for fn in self._scoring_functions if not isinstance(fn, ScoringFunctionNative)]

    def get_native_scoring_functions(self):
        return [fn for fn in self._scoring_functions if isinstance(fn, ScoringFunctionNative)]

    @property
    def geometry(self):
        return self._geometry

    def get_geometry_for_point(self, pos):
        if self._geometry is not None and self._geometry.contains_point(pos):
            return self._geometry

    def generate_geometry_only_constraint(self):
        constraints = [Constraint(geometry=constraint.geometry, scoring_functions=constraint._scoring_functions, allow_small_intersections=constraint._allow_small_intersections, routing_surface=constraint.routing_surface, allow_geometry_intersections=constraint._allow_geometry_intersections, cost=constraint.cost, objects_to_ignore=constraint._objects_to_ignore) for constraint in self if constraint.geometry is not None]
        if not constraints:
            return Anywhere()
        return create_constraint_set(constraints)

    def generate_alternate_geometry_constraint(self, alternate_geometry):
        constraints = self._copy(_geometry=alternate_geometry)
        if not constraints:
            return Anywhere()
        return create_constraint_set(constraints)

    def generate_forbid_small_intersections_constraint(self):
        return self._copy(_allow_small_intersections=False)

    def generate_constraint_with_cost(self, cost):
        return self._copy(_cost=cost)

    def generate_constraint_with_slot_info(self, actor, slot_target, chosen_slot):
        if self.posture_state_spec is None:
            return self
        (posture_manifest, slot_manifest, body_target) = self.posture_state_spec
        new_slot_manifest = SlotManifest()
        for manifest_entry in slot_manifest:
            if manifest_entry.actor == actor:
                overrides = {}
                if not isinstance(manifest_entry.target, RuntimeSlot):
                    overrides['target'] = slot_target
                if not isinstance(manifest_entry.slot, RuntimeSlot):
                    overrides['slot'] = chosen_slot
                manifest_entry = manifest_entry.with_overrides(**overrides)
            new_slot_manifest.add(manifest_entry)
        posture_state_spec = PostureStateSpec(posture_manifest, new_slot_manifest, body_target)
        return self._copy(_posture_state_spec=posture_state_spec)

    def generate_posture_only_constraint(self):
        posture_constraints = []
        for constraint in self:
            if constraint == Anywhere():
                posture_constraints.append(constraint)
            if constraint.posture_state_spec is None:
                pass
            posture_constraints.append(Constraint(posture_state_spec=constraint.posture_state_spec))
        if not posture_constraints:
            return Anywhere()
        return create_constraint_set(posture_constraints)

    def generate_body_posture_only_constraint(self):
        body_posture_constraints = []
        for constraint in self:
            if constraint == Anywhere():
                body_posture_constraints.append(constraint)
            if constraint.posture_state_spec is None:
                pass
            override = PostureManifestOverrideValue(MATCH_ANY, MATCH_ANY, None)
            posture_manifest_entries = []
            for posture_manifest_entry in constraint.posture_state_spec.posture_manifest:
                new_manifest_entries = posture_manifest_entry.get_entries_with_override(override)
                posture_manifest_entries.extend(new_manifest_entries)
            posture_manifest_new = PostureManifest(posture_manifest_entries)
            posture_state_spec_simplified = create_body_posture_state_spec(posture_manifest_new, body_target=constraint.posture_state_spec.body_target)
            body_posture_constraints.append(Constraint(posture_state_spec=posture_state_spec_simplified))
        if not body_posture_constraints:
            return Anywhere()
        return create_constraint_set(body_posture_constraints)

    @property
    def routing_surface(self):
        return self._routing_surface

    @property
    def posture_state_spec(self):
        return self._posture_state_spec

    @property
    def age(self):
        return self._age

    @property
    def create_jig_fn(self):
        return self._create_jig_fn

    @property
    def polygons(self):
        if hasattr(self.geometry, 'polygon'):
            return (self.geometry.polygon,)
        return ()

    @property
    def average_position(self):
        count = 0
        position = None
        for compound_polygon in self.polygons:
            for polygon in compound_polygon:
                for point in polygon:
                    if position is None:
                        position = point
                    else:
                        position += point
                    count += 1
        if position is None:
            return
        position /= count
        return position

    def single_point(self):
        point = None
        routing_surface = None
        for constraint in self:
            if constraint.geometry is None:
                return (None, None)
            if len(constraint.geometry.polygon) != 1:
                return (None, None)
            if len(constraint.geometry.polygon[0]) != 1:
                return (None, None)
            test_point = constraint.geometry.polygon[0][0]
            test_routing_surface = constraint.routing_surface
            if point is not None and (not sims4.math.vector3_almost_equal_2d(point, test_point) or test_routing_surface != routing_surface):
                return (None, None)
            point = test_point
            routing_surface = test_routing_surface
        return (point, routing_surface)

    @property
    def slot_offset_info(self):
        return self._slot_offset_info

    @property
    def cost(self):
        return self._cost

    def __iter__(self):
        yield self

    def get_posture_specs(self, resolver=None):
        posture_state_spec = self._posture_state_spec
        if posture_state_spec is not None:
            if resolver is not None:
                posture_state_spec = posture_state_spec.get_concrete_version(resolver)
            return [(spec, var_map, self) for (spec, var_map) in posture_state_spec.get_posture_specs_gen()]
        return [(PostureSpec((None, None, None)), frozendict(), self)]

    def get_connectivity_handles(self, *args, los_reference_point=None, entry=True, weight_route_factor=None, **kwargs):
        if not self.geometry or not self.geometry.polygon:
            return ()
        kwargs['geometry'] = self.geometry
        los_reference_point = los_reference_point if self._los_reference_point is DEFAULT else self._los_reference_point
        if weight_route_factor is None:
            weight_route_factor = self._weight_route_factor
        connectivity_handle = routing.connectivity.RoutingHandle(constraint=self, los_reference_point=los_reference_point, weight_route_factor=weight_route_factor, *args, **kwargs)
        return (connectivity_handle,)

    def get_posture_cost_attenuation(self, body_target):
        multiplier = 1.0
        for scoring_function in self._scoring_functions:
            multiplier *= scoring_function.get_posture_cost_attenuation(body_target)
        return multiplier

    @caches.cached(maxsize=None, key=_get_score_cache_key_fn)
    def get_score(self, position, orientation):
        if self.geometry is not None and not self.geometry.test_position_and_orientation(position, orientation):
            return 0
        total_score = 1.0
        routing_surface = self._routing_surface
        scores = [scoring_function.get_combined_score(position, orientation, routing_surface) for scoring_function in self._scoring_functions]
        for (multiplier, _) in scores:
            total_score *= multiplier
        for (_, offset) in scores:
            total_score += offset
        return total_score

    def get_routing_cost(self, position, orientation):
        return (1 - self.get_score(position, orientation))*self._weight_route_factor

    @caches.cached(maxsize=None)
    def _intersect_base(self, other_constraint):
        if self == other_constraint:
            return self
        if not self._allow_geometry_intersections:
            for sub_constraint in other_constraint:
                while sub_constraint.geometry is not None:
                    return Nowhere()
        if not other_constraint._allow_geometry_intersections:
            for sub_constraint in self:
                while sub_constraint.geometry is not None:
                    return Nowhere()
        if self.INTERSECT_PREFERENCE <= other_constraint.INTERSECT_PREFERENCE:
            result = self._intersect(other_constraint)
        else:
            result = other_constraint._intersect(self)
        return result

    def apply(self, other_constraint):
        intersection = self.intersect(other_constraint)
        if intersection.valid:
            return self
        return Nowhere()

    def intersect(self, other_constraint):
        if self is other_constraint or other_constraint is ANYWHERE:
            return self
        if other_constraint is NOWHERE:
            return NOWHERE
        return self._intersect_base(other_constraint)

    @staticmethod
    def _combine_debug_names(value0, value1):
        if not value1:
            return value0
        if not value0:
            return value1
        src = str(value0) + '&' + str(value1)
        if len(src) < 100:
            return src
        return src[:100] + '...'

    def _intersect_kwargs(self, other):
        if other._geometry in (None, self._geometry):
            geometry = self._geometry
        elif self._geometry is None:
            geometry = other._geometry
        else:
            geometry = self._geometry.intersect(other._geometry)
            if not geometry:
                return (NOWHERE, None)
        if other._posture_state_spec in (None, self._posture_state_spec):
            posture_state_spec = self._posture_state_spec
        elif self._posture_state_spec is None:
            posture_state_spec = other._posture_state_spec
        else:
            posture_state_spec = self._posture_state_spec.intersection(other._posture_state_spec)
            if not posture_state_spec:
                return (NOWHERE, None)
            if posture_state_spec.slot_manifest:
                for manifest_entry in posture_state_spec.posture_manifest:
                    while manifest_entry.surface == MATCH_NONE:
                        return (NOWHERE, None)
        if self.age is not None and other.age is not None and self.age != other.age:
            return (NOWHERE, None)
        age = self.age or other.age
        if self.routing_surface is not None and other.routing_surface is not None and self.routing_surface != other.routing_surface:
            return (NOWHERE, None)
        routing_surface = self.routing_surface or other.routing_surface
        scoring_functions = self._scoring_functions + other._scoring_functions
        scoring_functions = tuple(set(scoring_functions))
        if self._slot_offset_info is None:
            slot_offset_info = other._slot_offset_info
        else:
            slot_offset_info = self._slot_offset_info
        allow_small_intersections = self._allow_small_intersections or other._allow_small_intersections
        allow_geometry_intersections = self._allow_geometry_intersections and other._allow_geometry_intersections
        if self._los_reference_point is DEFAULT:
            los_reference_point = other._los_reference_point
        else:
            los_reference_point = self._los_reference_point
        outer_penalty_threshold = min(self._ignore_outer_penalty_threshold, other._ignore_outer_penalty_threshold)
        cost = max(self._cost, other._cost)
        objects_to_ignore = self._objects_to_ignore
        if objects_to_ignore is None:
            objects_to_ignore = other._objects_to_ignore
        elif other._objects_to_ignore is not None:
            objects_to_ignore = objects_to_ignore | other._objects_to_ignore
        create_jig_fn = self._create_jig_fn or other._create_jig_fn
        flush_planner = self._flush_planner or other._flush_planner
        kwargs = {'geometry': geometry, 'routing_surface': routing_surface, 'scoring_functions': scoring_functions, 'posture_state_spec': posture_state_spec, 'age': age, 'slot_offset_info': slot_offset_info, 'allow_small_intersections': allow_small_intersections, 'allow_geometry_intersections': allow_geometry_intersections, 'los_reference_point': los_reference_point, 'cost': cost, 'objects_to_ignore': objects_to_ignore, 'flush_planner': flush_planner, 'ignore_outer_penalty_threshold': outer_penalty_threshold, 'create_jig_fn': create_jig_fn}
        return (None, kwargs)

    @property
    def intersect_factory(self):
        return type(self)

    def _intersect(self, other_constraint):
        (early_out, kwargs) = self._intersect_kwargs(other_constraint)
        if early_out is not None:
            return early_out
        return self.intersect_factory(**kwargs)

    @property
    def force_route(self):
        return any(sf.force_route for sf in self._scoring_functions)

    @property
    def locked_params(self):
        pass

    @property
    def valid(self):
        if self._geometry is None:
            return True
        if self._geometry.polygon is None:
            return True
        if self._geometry.polygon:
            if not self._allow_small_intersections:
                area = self._geometry.polygon.area()
                if area < self.MINIMUM_VALID_AREA:
                    return False
            return True
        return False

    @property
    def tentative(self):
        return False

    def _get_posture_state_constraint(self, posture_state, target_resolver):
        if self.tentative and posture_state is not None:
            raise AssertionError('Tentative constraints must provide an implementation of apply_posture_state().')
        if self.age is not None:
            participant = AnimationParticipant.ACTOR
            actor = target_resolver(participant, participant)
            if actor is not None:
                if self.age != actor.age.age_for_animation_cache:
                    return Nowhere()
        if posture_state is None:
            return Anywhere()
        posture_state_constraint = posture_state.posture_constraint
        return posture_state_constraint

    def apply_posture_state(self, posture_state, target_resolver, **_):
        (early_out, intersect_kwargs) = self._intersect_kwargs(Anywhere())
        if early_out is not None:
            return early_out
        posture_state_spec = intersect_kwargs.get('posture_state_spec')
        if posture_state_spec is not None:
            intersect_kwargs['posture_state_spec'] = posture_state_spec.get_concrete_version(target_resolver)
        self_constraint = self.intersect_factory(**intersect_kwargs)
        posture_state_constraint = self._get_posture_state_constraint(posture_state, target_resolver)
        intersection = self_constraint.intersect(posture_state_constraint)
        return intersection

    def get_holster_version(self):
        (early_out, kwargs) = self._intersect_kwargs(Anywhere())
        if early_out is not None:
            return early_out
        posture_state_spec = kwargs.get('posture_state_spec')
        if posture_state_spec is not None:
            kwargs['posture_state_spec'] = posture_state_spec.get_holster_version()
        self_constraint = self.intersect_factory(**kwargs)
        return self_constraint

    def create_concrete_version(self, interaction):
        return self

    def add_slot_constraints_if_possible(self, sim):
        new_constraints = [sub_constraint for sub_constraint in self]
        for sub_constraint in self:
            if sub_constraint.posture_state_spec is None:
                pass
            body_target = sub_constraint.posture_state_spec.body_target
            while not body_target is None:
                if isinstance(body_target, PostureSpecVariable):
                    pass
                posture_type = None
                for posture_manifest_entry in sub_constraint.posture_state_spec.posture_manifest:
                    posture_type_entry = posture_manifest_entry.posture_type_specific or posture_manifest_entry.posture_type_family
                    if posture_type is not None and posture_type is not posture_type_entry:
                        raise RuntimeError('Mismatched posture types within a single posture state spec! [maxr]')
                    posture_type = posture_type_entry
                while not posture_type is None:
                    if posture_type.unconstrained:
                        pass
                    new_constraints.remove(sub_constraint)
                    if body_target.parts:
                        targets = (part for part in body_target.parts if part.supports_posture_type(posture_type))
                    else:
                        targets = (body_target,)
                    slot_constraints = []
                    for target in targets:
                        target_body_posture = postures.create_posture(posture_type, sim, target)
                        resolver = {body_target: target}.get
                        create_posture_state_spec_fn = lambda *_, **__: sub_constraint.posture_state_spec.get_concrete_version(resolver)
                        slot_constraint = target_body_posture.build_slot_constraint(create_posture_state_spec_fn=create_posture_state_spec_fn)
                        slot_constraints.append(slot_constraint)
                    slot_constraint_set = create_constraint_set(slot_constraints)
                    new_constraint = sub_constraint.intersect(slot_constraint_set)
                    new_constraints.append(new_constraint)
        constraint = create_constraint_set(new_constraints)
        return constraint

    @property
    def is_required_slot(self):
        return False

class _SingletonConstraint(SingletonType, Constraint):
    __qualname__ = '_SingletonConstraint'

    def __init__(self, *args, **kwargs):
        return super().__init__()

    def _copy(self, *args, **kwargs):
        return self

class Anywhere(_SingletonConstraint):
    __qualname__ = 'Anywhere'
    INTERSECT_PREFERENCE = IntersectPreference.UNIVERSAL

    @property
    def intersect_factory(self):
        return Constraint

    def apply_posture_state(self, *args, **kwargs):
        return self

    def intersect(self, other_constraint):
        return other_constraint

    def _intersect(self, other_constraint):
        return other_constraint

    def get_holster_version(self):
        return self

    @property
    def valid(self):
        return True

ANYWHERE = Anywhere()

class Nowhere(_SingletonConstraint):
    __qualname__ = 'Nowhere'
    INTERSECT_PREFERENCE = IntersectPreference.UNIVERSAL

    def intersect(self, other_constraint):
        return self

    def _intersect(self, other_constraint):
        return self

    def apply_posture_state(self, *args, **kwargs):
        return self

    def get_holster_version(self):
        return self

    @property
    def valid(self):
        return False

NOWHERE = Nowhere()

class ResolvePostureContext:
    __qualname__ = 'ResolvePostureContext'

    def __init__(self, posture_manifest_entry, create_target_name, asm_key, state_name, actor_name, target_name, carry_target_name, override_manifests, required_slots, initial_state):
        self._posture_manifest_entry = posture_manifest_entry
        self._create_target_name = create_target_name
        self._asm_key = asm_key
        self._state_name = state_name
        self._actor_name = actor_name
        self._target_name = target_name
        self._carry_target_name = carry_target_name
        self._override_manifests = override_manifests
        self._required_slots = required_slots
        self._initial_state = initial_state

    def __repr__(self):
        return standard_repr(self, **self.__dict__)

    def __getstate__(self):
        state = self.__dict__.copy()
        del state['_required_slots']
        del state['_asm_key']
        required_slots_list = []
        for required_slot in self._required_slots:
            slot_tuple = (required_slot.actor_name, required_slot.parent_name, required_slot.slot_type.__name__)
            required_slots_list.append(slot_tuple)
        state['custom_require_slots'] = required_slots_list
        state['custom_asm_key'] = (self._asm_key.type, self._asm_key.instance, self._asm_key.group)
        return state

    def __setstate__(self, state):
        required_slots = state['custom_require_slots']
        del state['custom_require_slots']
        asm_key = state['custom_asm_key']
        del state['custom_asm_key']
        slot_list = []
        instance_manager = services.get_instance_manager(sims4.resources.Types.SLOT_TYPE)
        for (slot_actor_name, parent_name, slot_type_name) in required_slots:
            slot_type = None
            for tuning_file in instance_manager.types.values():
                while slot_type_name == tuning_file.__name__:
                    slot_type = tuning_file
                    break
            slot_list.append(interactions.utils.animation.RequiredSlotOverride(slot_actor_name, parent_name, slot_type))
        self.__dict__.update(state)
        self._required_slots = slot_list
        self._asm_key = _resourceman.Key(*asm_key)

    def resolve(self, somewhere, posture_state, target_resolver, invalid_expected=False, posture_state_spec=None, affordance=None):
        actor = target_resolver(AnimationParticipant.ACTOR)
        if actor is not None and somewhere.age is not None and somewhere.age != actor.age.age_for_animation_cache:
            return Nowhere()
        if posture_state is None and posture_state_spec is None:
            return somewhere
        if posture_state is not None:
            if type(posture_state.body) != self._posture_manifest_entry.posture_type_specific:
                posture_type_family = self._posture_manifest_entry.posture_type_family
                if posture_type_family is None or not posture_state.body.is_same_posture_or_family(posture_type_family):
                    return Nowhere()
        elif posture_state_spec.body_target is None or isinstance(posture_state_spec.body_target, PostureSpecVariable):
            return somewhere
        surface_target = None
        if posture_state is not None:
            surface_target = posture_state.surface_target
            body = posture_state.body
        else:
            for entry in posture_state_spec.posture_manifest:
                posture_type = entry.posture_type_specific or entry.posture_type_family
                surface_target = entry.surface_target
                while surface_target is not None:
                    break
            if isinstance(surface_target, PostureSpecVariable):
                return somewhere
            body = DEFAULT
        if surface_target is None:
            posture_specs = somewhere.get_posture_specs(None)
            for (posture_spec_template, _, _) in posture_specs:
                while posture_spec_template._at_surface:
                    if posture_state is not None:
                        return Nowhere()
                    return somewhere
        target = target_resolver(AnimationParticipant.TARGET)
        if target is None and posture_state is None:
            return somewhere
        if self._create_target_name is not None:
            carry_target = GLOBAL_STUB_CREATE_TARGET
        elif self._carry_target_name is not None:
            carry_target = target_resolver(AnimationParticipant.CARRY_TARGET) or target
        else:
            carry_target = None
        if target is None or not target.parts:
            targets = (target,)
        else:
            targets = (part for part in target.parts if affordance is None or part.supports_affordance(affordance))
        constraints = []
        for target_or_part in targets:
            if body is DEFAULT:
                body_target = posture_state_spec.body_target
                if posture_state_spec.body_target.is_same_object_or_part(target_or_part):
                    body_posture = postures.create_posture(posture_type, actor, target_or_part)
                    bodies = (body_posture,)
                else:
                    if body_target is None or not body_target.parts:
                        body_targets = (body_target,)
                    else:
                        body_targets = body_target.parts
                    bodies = []
                    for body_target in body_targets:
                        body_posture = postures.create_posture(posture_type, actor, body_target)
                        bodies.append(body_posture)
            else:
                bodies = (body,)
            final_posture_state_spec = posture_state_spec if posture_state_spec is not None else somewhere.posture_state_spec
            for body_posture in bodies:
                constraint = RequiredSlot.create_required_slot_set(actor, target_or_part, carry_target, self._asm_key, self._state_name, self._actor_name, self._target_name, self._carry_target_name, self._create_target_name, self._override_manifests, self._required_slots, body_posture, surface_target, final_posture_state_spec, initial_state_name=self._initial_state, age=somewhere.age, invalid_expected=invalid_expected)
                if not constraint.valid and posture_state is None:
                    return somewhere
                if not constraint.valid and not invalid_expected:
                    logger.error("Tentative constraint resolution failure:\n                    This is not expected and indicates a disagreement between\n                    the information we have from Swing and tuning and what we\n                    encountered when actually running the game, perhaps one of\n                    the following:\n                      * The ASM uses parameterized animation (string parameters determine\n                        animation names) and the different possible Maya files\n                        don't all have exactly the same namespaces and\n                        constraints.\n                      * One or more actors aren't set to valid objects.\n                    ASM: {}".format(sims4.resources.get_debug_name(self._asm_key)))
                constraints.append(constraint)
        return create_constraint_set(constraints)

class TentativeIntersection(Constraint):
    __qualname__ = 'TentativeIntersection'
    INTERSECT_PREFERENCE = IntersectPreference.GEOMETRIC_PLUS

    def __init__(self, constraints, **kwargs):
        super().__init__(**kwargs)
        self_constraints = []
        for other_constraint in constraints:
            if isinstance(other_constraint, type(self)):
                self_constraints.extend(other_constraint._constraints)
            else:
                self_constraints.append(other_constraint)
        self._constraints = frozenset(self_constraints)

    def _intersect(self, other_constraint):
        (early_out, kwargs) = self._intersect_kwargs(other_constraint)
        if early_out is not None:
            return early_out
        constraints = set(self._constraints)
        constraints.add(other_constraint)
        return TentativeIntersection(constraints, **kwargs)

    def create_concrete_version(self, *args, **kwargs):
        return TentativeIntersection((constraint.create_concrete_version(*args, **kwargs) for constraint in self._constraints), debug_name=self._debug_name)

    @property
    def valid(self):
        for constraint in self._constraints:
            while not constraint.valid:
                return False
        return True

    @property
    def tentative(self):
        return True

    def apply_posture_state(self, *args, **kwargs):
        intersection = Anywhere()
        for other_constraint in self._constraints:
            other_constraint = other_constraint.apply_posture_state(*args, **kwargs)
            intersection = intersection.intersect(other_constraint)
        return intersection

    def get_holster_version(self):
        (early_out, kwargs) = self._intersect_kwargs(Anywhere())
        if early_out is not None:
            return early_out
        posture_state_spec = kwargs.get('posture_state_spec')
        if posture_state_spec is not None:
            kwargs['posture_state_spec'] = posture_state_spec.get_holster_version()
        constraints = []
        for constraint in self._constraints:
            constraints.append(constraint.get_holster_version())
        return TentativeIntersection(constraints, **kwargs)

class Somewhere(Constraint):
    __qualname__ = 'Somewhere'
    INTERSECT_PREFERENCE = IntersectPreference.GEOMETRIC_PLUS

    def __init__(self, apply_posture_context, **kwargs):
        super().__init__(**kwargs)
        self._apply_posture_context = apply_posture_context
        if not isinstance(apply_posture_context, ResolvePostureContext):
            logger.warn('Non class init of somewhere')

    def _intersect(self, other_constraint):
        (early_out, kwargs) = self._intersect_kwargs(other_constraint)
        if early_out is not None:
            return early_out
        return TentativeIntersection((self, other_constraint), **kwargs)

    @property
    def valid(self):
        return True

    @property
    def tentative(self):
        return True

    @property
    def intersect_factory(self):
        return lambda **kwargs: type(self)(self._apply_posture_context, **kwargs)

    def apply_posture_state(self, posture_state, target_resolver, **kwargs):
        if self._posture_state_spec is not None:
            posture_state_spec = self._posture_state_spec.get_concrete_version(target_resolver)
        else:
            posture_state_spec = None
        result = self._apply_posture_context.resolve(self, posture_state, target_resolver, posture_state_spec=posture_state_spec, **kwargs)
        if result is self:
            return super().apply_posture_state(posture_state, target_resolver, **kwargs)
        return result.apply_posture_state(posture_state, target_resolver, **kwargs)

    def get_holster_version(self):
        (early_out, kwargs) = self._intersect_kwargs(Anywhere())
        if early_out is not None:
            return early_out
        posture_state_spec = kwargs.get('posture_state_spec')
        if posture_state_spec is not None:
            kwargs['posture_state_spec'] = posture_state_spec.get_holster_version()
        return Somewhere(self._apply_posture_context, **kwargs)

def create_constraint_set(constraint_list, debug_name=''):
    if not constraint_list:
        return NOWHERE
    flattened_constraints = []
    for constraint in constraint_list:
        if constraint.IS_CONSTRAINT_SET:
            flattened_constraints.extend(constraint._constraints)
        else:
            flattened_constraints.append(constraint)
    if len(flattened_constraints) == 1:
        return flattened_constraints[0]
    similar_constraints = collections.defaultdict(list)
    for constraint in flattened_constraints:
        similar_constraints[frozendict(vars(constraint), _cost=0)].append(constraint)
    if len(similar_constraints) == 1:
        (_, constraints) = similar_constraints.popitem()
        return min(constraints, key=lambda c: c._cost)
    constraint_set = frozenset({min(constraints, key=lambda c: c._cost) for constraints in similar_constraints.values()})
    return _ConstraintSet(constraint_set, debug_name=debug_name)

class _ConstraintSet(Constraint):
    __qualname__ = '_ConstraintSet'
    INTERSECT_PREFERENCE = IntersectPreference.SPECIAL
    IS_CONSTRAINT_SET = True

    def __init__(self, constraints, debug_name=''):
        if not isinstance(constraints, frozenset):
            raise TypeError('constraints must be in a frozenset')
        if len(constraints) <= 1:
            raise ValueError('There must be more than 1 constraint in a _ConstraintSet')
        self._constraints = constraints
        super().__init__(debug_name=debug_name)

    def _copy(self, **overrides):
        return create_constraint_set((constraint._copy(**overrides) for constraint in self._constraints), debug_name=self._debug_name)

    def __iter__(self):
        return iter(self._constraints)

    def __len__(self):
        return len(self._constraints)

    def apply(self, other_constraint):
        valid_constraints = []
        for constraint in self._constraints:
            applied_constraint = constraint.apply(other_constraint)
            while applied_constraint.valid:
                valid_constraints.append(applied_constraint)
        return create_constraint_set(valid_constraints)

    def get_geometry_for_point(self, pos):
        for constraint in self._constraints:
            geometry = constraint.get_geometry_for_point(pos)
            while geometry is not None:
                return geometry

    @property
    def _member_property(self):
        raise AttributeError("ConstraintSets don't have this attribute, but their members might.")

    geometry = _member_property
    posture_state_spec = _member_property
    polygons = _member_property
    slot_offset_info = _member_property
    del _member_property

    @property
    def cost(self):
        return min(constraint.cost for constraint in self._constraints)

    @property
    def create_jig_fn(self):

        def create_all_jigs():
            for constraint in self._constraints:
                fn = constraint.create_jig_fn
                while fn is not None:
                    fn()

        return create_all_jigs

    @property
    def average_position(self):
        count = 0
        total_position = sims4.math.Vector3.ZERO()
        for constraint in self:
            average_position = constraint.average_position
            while average_position is not None:
                count += 1
                total_position += average_position
        if count == 0:
            return
        return total_position/count

    @property
    def force_route(self):
        raise NotImplementedError

    def get_posture_cost_attenuation(self, body_target):
        return min(constraint.get_posture_cost_attenuation(body_target) for constraint in self)

    def get_score(self, position, orientation):
        return max(constraint.get_score(position, orientation) for constraint in self)

    def get_routing_cost(self, position, orientation):
        return min(constraint.get_routing_cost(position, orientation) for constraint in self)

    def get_posture_specs(self, resolver=None):
        posture_state_specs_to_constraints = collections.defaultdict(list)
        for constraint in self:
            if constraint.posture_state_spec is not None:
                key_carries = set()
                key_surfaces = set()
                key_unconstrained = False
                for manifest_entry in constraint.posture_state_spec.posture_manifest:
                    entry_posture_str = manifest_entry.specific or manifest_entry.family
                    if entry_posture_str:
                        entry_posture = _get_posture_type_for_posture_name(entry_posture_str)
                        if entry_posture is not None and entry_posture.unconstrained:
                            key_unconstrained = True
                    if manifest_entry.carry_target is not None:
                        key_carries.add(manifest_entry.carry_target)
                    while manifest_entry.surface_target is not None:
                        key_surfaces.add(manifest_entry.surface_target)
                if constraint.posture_state_spec.slot_manifest:
                    for slot_manifest_entry in constraint.posture_state_spec.slot_manifest:
                        key_surfaces.add((slot_manifest_entry.actor, slot_manifest_entry.target))
                key_carries = frozenset(key_carries)
                key_surfaces = frozenset(key_surfaces)
                key = (key_carries, key_surfaces, key_unconstrained)
            else:
                key = None
            posture_state_specs_to_constraints[key].append(constraint)
        results = set()
        for similar_constraints in posture_state_specs_to_constraints.values():
            similar_constraint_set = create_constraint_set(similar_constraints)
            for similar_constraint in similar_constraints:
                for (posture_spec, var_map, _) in similar_constraint.get_posture_specs(resolver):
                    results.add((posture_spec, var_map, similar_constraint_set))
        return list(results)

    def get_connectivity_handles(self, *args, **kwargs):
        return [handle for constraint in self._constraints for handle in constraint.get_connectivity_handles(*args, **kwargs)]

    def _intersect(self, other_constraint):
        valid_constraints = []
        if other_constraint.IS_CONSTRAINT_SET:
            for constraint in self._constraints:
                for inner_constraint in other_constraint._constraints:
                    intersection = inner_constraint.intersect(constraint)
                    while intersection.valid:
                        valid_constraints.append(intersection)
        else:
            for constraint in self._constraints:
                intersection = constraint.intersect(other_constraint)
                while intersection.valid:
                    valid_constraints.append(intersection)
        return create_constraint_set(valid_constraints, debug_name=self._debug_name)

    def get_holster_version(self):
        holster_constraints = []
        for constraint in self._constraints:
            holster_constraint = constraint.get_holster_version()
            holster_constraints.append(holster_constraint)
        return create_constraint_set(holster_constraints, debug_name=self._debug_name)

    def generate_constraint_with_slot_info(self, actor, slot_target, chosen_slot):
        return create_constraint_set((constraint.generate_constraint_with_slot_info(actor, slot_target, chosen_slot) for constraint in self._constraints), debug_name=self._debug_name)

    @property
    def tentative(self):
        return any(constraint.tentative for constraint in self._constraints)

    def apply_posture_state(self, *args, **kwargs):
        valid_constraints = []
        for constraint in self._constraints:
            new_constraint = constraint.apply_posture_state(*args, **kwargs)
            while new_constraint.valid:
                valid_constraints.append(new_constraint)
        return create_constraint_set(valid_constraints, debug_name=self._debug_name)

    def create_concrete_version(self, *args, **kwargs):
        return create_constraint_set((constraint.create_concrete_version(*args, **kwargs) for constraint in self._constraints), debug_name=self._debug_name)

    @property
    def locked_params(self):
        return {}

    @property
    def valid(self):
        for constraint in self._constraints:
            while constraint.valid:
                return True
        return False

    def __repr__(self):
        return 'ConstraintSet(...)'

class SmallAreaConstraint(Constraint):
    __qualname__ = 'SmallAreaConstraint'

    def __init__(self, *args, allow_small_intersections=True, **kwargs):
        super().__init__(allow_small_intersections=True, *args, **kwargs)

    def generate_forbid_small_intersections_constraint(self):
        return self

def AbsoluteFacing(angle, facing_range=None, debug_name=DEFAULT, **kwargs):
    if debug_name is DEFAULT:
        debug_name = 'AbsoluteFacing'
    if facing_range is None:
        facing_range = Constraint.DEFAULT_FACING_RANGE
    interval = sims4.geometry.interval_from_facing_angle(angle, facing_range)
    abs_facing_range = sims4.geometry.AbsoluteOrientationRange(interval)
    facing_geometry = sims4.geometry.RestrictedPolygon(None, (abs_facing_range,))
    return Constraint(debug_name=debug_name, geometry=facing_geometry, **kwargs)

def Facing(target=None, facing_range=None, inner_radius=None, target_position=DEFAULT, debug_name=DEFAULT, **kwargs):
    if debug_name is DEFAULT:
        debug_name = 'Facing'
    if target_position is DEFAULT:
        target_position = target.intended_position
    if facing_range is None:
        facing_range = Constraint.DEFAULT_FACING_RANGE
    relative_facing_range = sims4.geometry.RelativeFacingRange(target_position, facing_range)
    facing_geometry = sims4.geometry.RestrictedPolygon(None, (relative_facing_range,))
    return Constraint(debug_name=debug_name, geometry=facing_geometry, **kwargs)

class TunedFacing:
    __qualname__ = 'TunedFacing'

    def __init__(self, range, inner_radius):
        self._facing_range = range
        self._inner_radius = inner_radius

    def create_constraint(self, sim, target=None, target_position=DEFAULT, **kwargs):
        if target is not None and target.is_in_inventory():
            if target.is_in_sim_inventory():
                return Anywhere()
            logger.error('Attempt to create a tuned Facing constraint on a target: {} which is in the inventory.  This will not work correctly.', target, owner='mduke')
            return Nowhere()
        if target is None and target_position is DEFAULT:
            return Anywhere()
        return Facing(target, facing_range=self._facing_range, inner_radius=self._inner_radius, target_position=target_position, **kwargs)

class TunableFacing(TunableSingletonFactory):
    __qualname__ = 'TunableFacing'
    FACTORY_TYPE = TunedFacing

    def __init__(self, description=None, **kwargs):
        super().__init__(range=TunableAngle(sims4.math.PI/2, description='The size of the angle-range that sims should use when determining facing constraints.'), inner_radius=Tunable(float, 1.0, description="A radius around the center of the constraint that defines an area in which the Sim's facing is unrestricted."), description=description, **kwargs)

class TunedLineOfSight:
    __qualname__ = 'TunedLineOfSight'

    def __init__(self, temporary_los):
        self._temporary_los = temporary_los

    def create_constraint(self, sim, target, target_position=DEFAULT, **kwargs):
        if isinstance(target, StubActor):
            return Anywhere()
        if target is None:
            logger.warn('Attempting to create a LineOfSight constraint on a None target. This is expected if the target has been destroyed.', owner='epanero')
            return ANYWHERE
        if target.is_in_inventory():
            logger.error('Attempt to tune a LineOfSight constraint on a target {} that is in the inventory. This will not work.', target, owner='mduke')
            return Nowhere()
        if target_position is DEFAULT:
            target_position = target.intended_position
            target_forward = target.intended_forward
            target_routing_surface = target.intended_routing_surface
        else:
            target_forward = target.forward
            target_routing_surface = target.routing_surface
            if target.is_sim and target.lineofsight_component is not None:
                target.refresh_los_constraint(target_position=target_position)
        if not isinstance(target_routing_surface, routing.SurfaceIdentifier):
            logger.error('Target {} does not have a valid routing surface {}, type {}.', target, target_routing_surface, type(target_routing_surface), owner='tastle')
            return Nowhere()
        if target.lineofsight_component is None:
            if self._temporary_los is not None:
                from objects.components.line_of_sight_component import LineOfSight
                los = LineOfSight(self._temporary_los.max_line_of_sight_radius, self._temporary_los.map_divisions, self._temporary_los.simplification_ratio, self._temporary_los.boundary_epsilon)
                position = target_position + target_forward*self._temporary_los.facing_offset
                los.generate(position, target_routing_surface)
                return los.constraint
            logger.error('{} has no LOS and no temporary LOS was specified', target, owner='epanero')
        return target.lineofsight_component.constraint

class TunableLineOfSightData(TunableTuple):
    __qualname__ = 'TunableLineOfSightData'

    def __init__(self, *args, **kwargs):
        super().__init__(facing_offset=Tunable(description='\n                The LOS origin is offset from the object origin by this amount\n                (mainly to avoid intersecting walls).\n                ', tunable_type=float, default=0.1), max_line_of_sight_radius=Tunable(description='\n                The maximum possible distance from this object than an\n                interaction can reach.\n                ', tunable_type=float, default=10), map_divisions=Tunable(description='\n                The number of points around the object to check collision from.\n                More points means higher accuracy.\n                ', tunable_type=int, default=30), simplification_ratio=Tunable(description='\n                A factor determining how much to combine edges in the line of\n                sight polygon.\n                ', tunable_type=float, default=0.35), boundary_epsilon=Tunable(description='\n                The LOS origin is allowed to be outside of the boundary by this\n                amount.\n                ', tunable_type=float, default=0.01), *args, **kwargs)

class TunableLineOfSight(TunableSingletonFactory):
    __qualname__ = 'TunableLineOfSight'
    FACTORY_TYPE = TunedLineOfSight

    def __init__(self, **kwargs):
        super().__init__(temporary_los=OptionalTunable(description="\n                 If enabled, a Line of Sight component will be temporarily created\n                 when constraints are needed. This should be used if the affordance\n                 requires LOS on an object that doesn't have an LOS component (i.e. a\n                 Sim needs to see another Sim WooHoo to play the jealousy reactions\n                 but Sims don't have LoS components.)\n                 ", tunable=TunableLineOfSightData()), **kwargs)

class TunedSpawnPoint:
    __qualname__ = 'TunedSpawnPoint'

    def __init__(self, tags=None):
        self.tags = tags

    def create_constraint(self, sim, target=None, lot_id=None, **kwargs):
        return services.current_zone().get_spawn_points_constraint(sim_info=sim.sim_info, lot_id=lot_id, sim_spawner_tags=self.tags)

class TunableSpawnPoint(TunableSingletonFactory):
    __qualname__ = 'TunableSpawnPoint'
    FACTORY_TYPE = TunedSpawnPoint

    def __init__(self, description='\n        A tunable type for creating Spawn Point\n        constraints. If no Tags are tuned, then the system will use whatever\n        information is saved on the sim_info. The saved info will rely on\n        information about where the Sim spawned from.\n        ', **kwargs):
        super().__init__(tags=OptionalTunable(tunable=TunableSet(tunable=TunableEnumEntry(tunable_type=Tag, default=Tag.INVALID)), enabled_by_default=False, disabled_name='Use_Saved_Spawn_Point_Options', enabled_name='Spawn_Point_Tags', description=description), **kwargs)

def create_animation_constraint_set(constraints, asm_name, state_name, **kwargs):
    debug_name = 'AnimationConstraint({}.{})'.format(asm_name, state_name)
    return create_constraint_set(constraints, debug_name=debug_name)

def _create_slot_manifest(boundary_condition, required_slots, resolve_actor_name_fn):
    slot_manifest = SlotManifest()
    if required_slots is None:
        for (child_name, parent_name, bone_name_hash) in boundary_condition.required_slots:
            entry = SlotManifestEntry(child_name, parent_name, bone_name_hash)
            entry = entry.apply_actor_map(resolve_actor_name_fn)
            slot_manifest.add(entry)
    else:
        for (child_name, parent_name, slot_type) in required_slots:
            entry = SlotManifestEntry(child_name, parent_name, slot_type.bone_name_hash)
            entry = entry.apply_actor_map(resolve_actor_name_fn)
            slot_manifest.add(entry)
    return slot_manifest

def _resolve_slot_and_surface_constraints(boundary_condition, animation_overrides, target, target_name, carry_target, carry_target_name, surface_target, surface_target_name, slot_manifest):
    surface = None
    slot_manifest_entry = None
    if animation_overrides is None or not animation_overrides.required_slots:
        for (child_id, parent_id, bone_name_hash) in boundary_condition.required_slots:
            if target is not None and child_id == target.id:
                target_var = PostureSpecVariable.INTERACTION_TARGET
            elif carry_target is not None and child_id == carry_target.id:
                target_var = PostureSpecVariable.CARRY_TARGET
            else:
                target_var = None
            slot_type = objects.slots.get_slot_type_for_bone_name_hash(bone_name_hash)
            if slot_type is None:
                msg = 'Could not find tuning matching a surface slot specified in Maya:'
                bone_name = animation.animation_utils.unhash_bone_name(bone_name_hash)
                if bone_name:
                    msg += " the bone named '{}' does not have a SlotType defined.".format(bone_name)
                else:
                    msg += " a bone whose name hash is '{:#x}' does not have a SlotType defined.".format(bone_name_hash)
                if api_config.native_supports_new_api('native.animation.arb.BoundaryConditionInfo'):
                    msg += ' (Clip is in ASM {})'.format(boundary_condition.debug_info)
                logger.error(msg)
            for entry in slot_manifest:
                while slot_type in entry.slot_types:
                    slot_manifest_entry = entry
                    break
            if slot_type is not None:
                slot_type = PostureSpecVariable.SLOT
            if target is not None and parent_id == target.id:
                surface_var = PostureSpecVariable.INTERACTION_TARGET
            elif surface_target is not None and parent_id == surface_target.id:
                surface_var = PostureSpecVariable.SURFACE_TARGET
            else:
                surface_var = PostureSpecVariable.ANYTHING
            surface = PostureAspectSurface((surface_var, slot_type, target_var))
            break
    else:
        for (child_name, parent_name, slot_type) in animation_overrides.required_slots:
            if child_name == target_name:
                target_var = PostureSpecVariable.INTERACTION_TARGET
            elif child_name == carry_target_name:
                target_var = PostureSpecVariable.CARRY_TARGET
            else:
                target_var = None
            if parent_name == target_name:
                surface_var = PostureSpecVariable.INTERACTION_TARGET
            elif parent_name == surface_target_name:
                surface_var = PostureSpecVariable.SURFACE_TARGET
            else:
                surface_var = PostureSpecVariable.ANYTHING
            for entry in slot_manifest:
                while slot_type in entry.slot_types:
                    slot_manifest_entry = entry
                    break
            if slot_type is not None:
                slot_type = PostureSpecVariable.SLOT
            surface = PostureAspectSurface((surface_var, slot_type, target_var))
            break
    return (surface, slot_manifest_entry)

def create_animation_constraint(asm_key, actor_name, target_name, carry_target_name, create_target_name, initial_state, begin_states, animation_overrides):
    constraints = []
    tentative_posture_spec_var_pairs = set()
    concrete_posture_spec_var_pairs = set()
    age_name_lower_to_enum = {age.animation_age_param: age for age in sims.sim_info_types.Age.get_ages_for_animation_cache()}
    state_name = begin_states[0]
    animation_context = get_throwaway_animation_context()
    asm = Asm(asm_key, animation_context, posture_manifest_overrides=animation_overrides.manifests)
    posture_manifest = asm.get_supported_postures_for_actor(actor_name).get_constraint_version()
    for posture_manifest_entry in posture_manifest:
        if not posture_manifest_entry.posture_types:
            logger.error('Manifest entry has no posture types: {}.{}.', asm.name, posture_manifest_entry)
        posture_type = posture_manifest_entry.posture_types[0]
        actor_name_to_animation_participant_map = {}
        actor_name_to_stub_actor_map = {}

        def add_mapping(animation_participant, tuned_name, default_stub_actor):
            if tuned_name is None:
                return
            if tuned_name in actor_name_to_stub_actor_map:
                return actor_name_to_stub_actor_map[tuned_name]
            actor_name_to_animation_participant_map[tuned_name] = animation_participant
            actor_name_to_stub_actor_map[tuned_name] = default_stub_actor
            return default_stub_actor

        surface_target_name = posture_manifest_entry.surface_target
        asm = Asm(asm_key, animation_context, posture_manifest_overrides=animation_overrides.manifests)
        posture = posture_type(GLOBAL_STUB_ACTOR, GLOBAL_STUB_CONTAINER, PostureTrack.BODY, animation_context=animation_context)
        target = add_mapping(AnimationParticipant.TARGET, target_name, GLOBAL_STUB_TARGET)
        actor = add_mapping(AnimationParticipant.ACTOR, actor_name, GLOBAL_STUB_ACTOR)
        container_target = add_mapping(AnimationParticipant.CONTAINER, posture.target_name, GLOBAL_STUB_CONTAINER)
        surface_target = add_mapping(AnimationParticipant.SURFACE, surface_target_name, GLOBAL_STUB_SURFACE)
        carry_target = add_mapping(AnimationParticipant.CARRY_TARGET, carry_target_name, GLOBAL_STUB_CARRY_TARGET)
        create_target = add_mapping(AnimationParticipant.CREATE_TARGET, create_target_name, GLOBAL_STUB_CREATE_TARGET)
        for (prop_name, definition_id) in asm.get_props_in_traversal(initial_state or 'entry', begin_states[-1]).items():
            prop_definition = services.definition_manager().get(definition_id)
            add_mapping(None, prop_name, prop_definition)
        actor = actor or GLOBAL_STUB_ACTOR
        container_target = container_target or GLOBAL_STUB_CONTAINER
        if posture.multi_sim:
            if actor_name == posture_type._actor_param_name:
                posture = posture_type(actor, container_target, PostureTrack.BODY, master=True, animation_context=animation_context)
            else:
                posture = posture_type(actor, container_target, PostureTrack.BODY, master=False, animation_context=animation_context)
        else:
            posture = posture_type(actor, container_target, PostureTrack.BODY, animation_context=animation_context)
        if surface_target_name is None:
            if posture_manifest_entry.allow_surface:
                surface = None
            else:
                surface = PostureAspectSurface((None, None, None))
        else:
            surface = PostureAspectSurface((PostureSpecVariable.SURFACE_TARGET, None, None))
        if posture.multi_sim:
            target_posture = posture_type(target, container_target, PostureTrack.BODY, animation_context=animation_context)
            posture.linked_posture = target_posture
        if not posture.setup_asm_interaction(asm, actor, target, actor_name, target_name, carry_target=carry_target, carry_target_name=carry_target_name, surface_target=surface_target, invalid_expected=True):
            logger.error('Could not set up AnimationConstraint asm with stub actors: {}', asm.name)
        if create_target is not None:
            asm.set_actor(create_target_name, create_target)
        body_target_var = PostureSpecVariable.ANYTHING
        if target_name is not None and target_name == posture.target_name:
            body_target_var = PostureSpecVariable.INTERACTION_TARGET
        try:
            actor.posture = posture
            containment_slot_to_slot_data = asm.get_boundary_conditions_list(actor, state_name, from_state_name=initial_state)
        finally:
            actor.posture = None
        if not containment_slot_to_slot_data:
            bound_posture_manifest_entry = posture_manifest_entry.apply_actor_map(actor_name_to_animation_participant_map.get)
            bound_posture_manifest_entry = bound_posture_manifest_entry.intern()
            if animation_overrides is not None and animation_overrides.required_slots:
                slot_manifest = _create_slot_manifest(None, animation_overrides.required_slots, actor_name_to_animation_participant_map.get)
            else:
                slot_manifest = SlotManifest()
            slot_manifest = slot_manifest.intern()
            posture_manifest = PostureManifest((bound_posture_manifest_entry,))
            posture_manifest = posture_manifest.intern()
            posture_state_spec = PostureStateSpec(posture_manifest, slot_manifest, body_target_var)
            entry = (bound_posture_manifest_entry, posture_state_spec, None)
            concrete_posture_spec_var_pairs.add(entry)
        boundary_conditions = []
        for (_, slot_data) in containment_slot_to_slot_data:
            for (boundary_condition, locked_params_list) in slot_data:
                for locked_params in locked_params_list:
                    while locked_params is not None:
                        age_param = None
                        if ('age', actor_name) in locked_params:
                            age_str = locked_params[('age', actor_name)]
                            if age_str in age_name_lower_to_enum:
                                age_param = age_name_lower_to_enum[age_str]
                        boundary_conditions.append((boundary_condition, age_param))
        for (boundary_condition, age) in boundary_conditions:
            tentative = False
            bc_body_target_var = body_target_var
            if target_name is not None or surface_target is not None:
                relative_object_name = boundary_condition.pre_condition_reference_object_name or boundary_condition.post_condition_reference_object_name
                if relative_object_name is not None:
                    tentative = posture_type.unconstrained
                    if posture.target_name is None and bc_body_target_var == PostureSpecVariable.ANYTHING:
                        if relative_object_name == target_name:
                            bc_body_target_var = PostureSpecVariable.INTERACTION_TARGET
            required_slots = None
            if animation_overrides is not None:
                required_slots = animation_overrides.required_slots
            slot_manifest = _create_slot_manifest(boundary_condition, required_slots, actor_name_to_animation_participant_map.get)
            slot_manifest = slot_manifest.intern()
            (surface_from_constraint, _) = _resolve_slot_and_surface_constraints(boundary_condition, animation_overrides, target, target_name, carry_target, carry_target_name, surface_target, surface_target_name, slot_manifest)
            surface = surface_from_constraint or surface
            bound_posture_manifest_entry = posture_manifest_entry.apply_actor_map(actor_name_to_animation_participant_map.get)
            bound_posture_manifest_entry = bound_posture_manifest_entry.intern()
            posture_manifest = PostureManifest((bound_posture_manifest_entry,))
            posture_manifest = posture_manifest.intern()
            posture_state_spec = PostureStateSpec(posture_manifest, slot_manifest, bc_body_target_var)
            entry = (bound_posture_manifest_entry, posture_state_spec, age)
            if tentative:
                tentative_posture_spec_var_pairs.add(entry)
            else:
                concrete_posture_spec_var_pairs.add(entry)
    if tentative_posture_spec_var_pairs:
        for (posture_manifest_entry, posture_state_spec, age_param) in tentative_posture_spec_var_pairs:
            override_manifests = None
            required_slots = None
            if animation_overrides is not None:
                override_manifests = animation_overrides.manifests
                required_slots = animation_overrides.required_slots
            resolve_context = ResolvePostureContext(posture_manifest_entry, create_target_name, asm_key, state_name, actor_name, target_name, carry_target_name, override_manifests, required_slots, initial_state)
            debug_name = None
            slot_offset_info = (asm_key, actor_name, target_name, state_name)
            constraint = Somewhere(resolve_context, debug_name=debug_name, posture_state_spec=posture_state_spec, age=age_param, slot_offset_info=slot_offset_info)
            constraints.append(constraint)
    for (posture_manifest_entry, posture_state_spec, age_param) in concrete_posture_spec_var_pairs:
        debug_name = None
        constraint = Constraint(debug_name=debug_name, posture_state_spec=posture_state_spec, age=age_param)
        constraints.append(constraint)
    if constraints:
        return create_animation_constraint_set(constraints, asm.name, state_name)

class RequiredSlot:
    __qualname__ = 'RequiredSlot'

    @staticmethod
    def _setup_asm(sim, target, asm, posture, *args, **kwargs):
        if posture is None:
            raise RuntimeError('Attempt to create a RequiredSlot with no posture.')
        if asm is posture.asm:
            if posture.setup_asm_posture(asm, sim, target):
                return True
            logger.debug('Failed to setup posture ASM {0} on posture {1} for RequiredSlotSingle constraint.', asm, posture)
            return False
        if posture.setup_asm_interaction(asm, sim, target, *args, **kwargs):
            return True
        logger.debug('Failed to setup interaction ASM {0} with posture {1} for RequiredSlotSingle constraint.', asm, posture)
        return False

    @staticmethod
    def _get_and_setup_asm_for_required_slot_set(asm_key, sim, target, actor_name, target_name, posture, posture_manifest_overrides=None, asm=None, **kwargs):
        anim_context = get_throwaway_animation_context()
        if asm is None:
            asm = Asm(asm_key, anim_context, posture_manifest_overrides=posture_manifest_overrides)
        if not RequiredSlot._setup_asm(sim, target, asm, posture, actor_name, target_name, **kwargs):
            return
        return asm

    @staticmethod
    def _build_relative_slot_data(asm, sim, target, actor_name, target_name, posture, state_name, exit_slot_start_state=None, exit_slot_end_state='exit', locked_params=frozendict(), initial_state_name=DEFAULT):
        anim_overrides_target = target.get_anim_overrides(target_name)
        if anim_overrides_target is not None and anim_overrides_target.params:
            locked_params += anim_overrides_target.params
        containment_slot_to_slot_data_entry = asm.get_boundary_conditions_list(sim, state_name, locked_params=locked_params, from_state_name=initial_state_name, posture=posture)
        if exit_slot_start_state is not None:
            containment_slot_to_slot_data_exit = asm.get_boundary_conditions_list(sim, exit_slot_end_state, locked_params=locked_params, from_state_name=exit_slot_start_state, entry=False)
        else:
            containment_slot_to_slot_data_exit = ()
        return (containment_slot_to_slot_data_entry, containment_slot_to_slot_data_exit)

    @staticmethod
    def _build_posture_state_spec_for_boundary_condition(boundary_condition, asm, sim, target, carry_target, surface_target, actor_name, target_name, carry_target_name, create_target_name, posture, state_name, posture_state_spec, required_slots):
        object_manager = services.object_manager()
        if posture is not None and posture.asm == asm:
            supported_postures = asm.provided_postures
        elif posture_state_spec is None:
            supported_postures = asm.get_supported_postures_for_actor(actor_name)
        else:
            supported_postures = posture_state_spec.posture_manifest
        matching_supported_postures = PostureManifest()
        body_target = posture.target if posture is not None else target
        surface_target = posture.surface_target if surface_target is DEFAULT else surface_target
        surface_target_name = None
        if posture is not None:
            for posture_manifest_entry in supported_postures:
                for body_type in posture_manifest_entry.posture_types:
                    while isinstance(posture, body_type):
                        matching_supported_postures.add(posture_manifest_entry)
                surface_target_name = posture_manifest_entry.surface_target
        actor_name_to_game_object_map = {}
        valid_relative_object_ids = set()

        def add_actor_map(name, obj, is_valid_relative_object):
            if name is None or obj is None:
                return
            actor_name_to_game_object_map[name] = obj
            if name not in actor_name_to_game_object_map and is_valid_relative_object:
                valid_relative_object_ids.add(obj.id)

        add_actor_map(target_name, target, True)
        add_actor_map(actor_name, sim, False)
        if posture is not None:
            add_actor_map(posture.target_name, posture.target, True)
        add_actor_map(carry_target_name, carry_target, False)
        add_actor_map(create_target_name, AnimationParticipant.CREATE_TARGET, False)
        add_actor_map(surface_target_name, surface_target, True)
        actor_name_to_game_object_map[AnimationParticipant.ACTOR] = sim
        actor_name_to_game_object_map[AnimationParticipant.TARGET] = target
        actor_name_to_game_object_map[AnimationParticipant.CONTAINER] = posture.target
        actor_name_to_game_object_map[AnimationParticipant.CARRY_TARGET] = carry_target
        actor_name_to_game_object_map[AnimationParticipant.SURFACE] = surface_target
        matching_supported_postures = matching_supported_postures.apply_actor_map(actor_name_to_game_object_map.get)
        relative_object_id = boundary_condition.get_relative_object_id(asm)
        relative_object = object_manager.get(relative_object_id)
        if relative_object is not None and relative_object.parent is sim:
            raise RuntimeError('[bhill/maxr] ASM is trying to generate a bogus required slot constraint relative to {}: {}.{}\nMost likely this means the base object for this clip was set incorrectly in Maya.\nContact an animator to fix this or Max R.'.format(relative_object, asm.name, state_name))
        if posture_state_spec is not None:
            slot_manifest = posture_state_spec.slot_manifest
        else:
            slot_manifest = _create_slot_manifest(boundary_condition, required_slots, actor_name_to_game_object_map.get)
        posture_state_spec = PostureStateSpec(PostureManifest(matching_supported_postures), slot_manifest, body_target)
        return posture_state_spec

    @staticmethod
    def _build_required_slot_set_from_relative_data(asm, asm_key, sim, target, posture, actor_name, target_name, state_name, containment_slot_to_slot_data_entry, containment_slot_to_slot_data_exit, get_posture_state_spec_fn, age=None, invalid_expected=False):
        slot_constraints = []
        for (_, slots_to_params_entry) in containment_slot_to_slot_data_entry:
            posture_state_spec = None
            slots_to_params_entry_absolute = []
            containment_transform = None
            for (boundary_condition_entry, param_sequences_entry) in slots_to_params_entry:
                if target.is_part:
                    for param_sequence in param_sequences_entry:
                        subroot_parameter = param_sequence.get('subroot')
                        while subroot_parameter is None or subroot_parameter == target.part_suffix:
                            break
                relative_obj_id = boundary_condition_entry.get_relative_object_id(asm)
                if relative_obj_id is not None and target.id != relative_obj_id:
                    while not invalid_expected:
                        logger.callstack('Unexpected relative object in required slot for {}: {}', asm, boundary_condition_entry.pre_condition_reference_object_name or boundary_condition_entry.post_condition_reference_object_name, level=sims4.log.LEVEL_ERROR)
                        (routing_transform_entry, containment_transform) = boundary_condition_entry.get_transforms(asm, target)
                        slots_to_params_entry_absolute.append((routing_transform_entry, param_sequences_entry))
                        while posture_state_spec is None and get_posture_state_spec_fn is not None:
                            posture_state_spec = get_posture_state_spec_fn(boundary_condition_entry)
                (routing_transform_entry, containment_transform) = boundary_condition_entry.get_transforms(asm, target)
                slots_to_params_entry_absolute.append((routing_transform_entry, param_sequences_entry))
                while posture_state_spec is None and get_posture_state_spec_fn is not None:
                    posture_state_spec = get_posture_state_spec_fn(boundary_condition_entry)
            if containment_transform is None:
                pass
            slots_to_params_exit_absolute = []
            if containment_slot_to_slot_data_exit:
                for (_, slots_to_params_exit) in containment_slot_to_slot_data_exit:
                    containment_transform_exit = None
                    for (boundary_condition_exit, param_sequences_exit) in slots_to_params_exit:
                        if target.is_part:
                            for param_sequence in param_sequences_exit:
                                subroot_parameter = param_sequence.get('subroot')
                                while subroot_parameter is None or subroot_parameter == target.part_suffix:
                                    break
                        relative_obj_id = boundary_condition_exit.get_relative_object_id(asm)
                        if relative_obj_id is not None and target.id != relative_obj_id:
                            logger.callstack('Unexpected relative object in required slot for {}: {}', asm, boundary_condition_exit.pre_condition_reference_object_name or boundary_condition_exit.post_condition_reference_object_name, level=sims4.log.LEVEL_ERROR)
                        (containment_transform_exit, routing_transform_exit) = boundary_condition_exit.get_transforms(asm, target)
                        if not Asm.transform_almost_equal_2d(containment_transform_exit, containment_transform):
                            logger.warn(" The animations for getting into and\n                            out of this object don't use the same transform for\n                            the containment Slot. This means that the Sim won't\n                            be able to use the exit animation when in the slot\n                            specified by the entry animation and will fail to\n                            get out or play a weird clip. Make sure base object\n                            is set on the posture animations. \n                            \n                            ASM: {}\n                            Actor: {}\n                            Target: {}\n                            Posture: {}\n                            State: {}\n                            Containment Transform Exit: {} \n                            Containment Transform: {}\n                            ", asm, sim, target, posture, state_name, containment_transform_exit, containment_transform)
                        slots_to_params_exit_absolute.append((routing_transform_exit, param_sequences_exit))
            slot_constraint = RequiredSlotSingle(sim, target, asm, asm_key, posture, actor_name, target_name, state_name, containment_transform, tuple(slots_to_params_entry_absolute), tuple(slots_to_params_exit_absolute), posture_state_spec=posture_state_spec, asm_name=asm.name, age=age)
            slot_constraints.append(slot_constraint)
        if slot_constraints:
            return create_constraint_set(slot_constraints)
        return Anywhere()

    _required_slot_cache = {}

    @classmethod
    def clear_required_slot_cache(cls):
        cls._required_slot_cache.clear()

    @staticmethod
    def _get_cache_key(sim, posture_type, target, actor_name):
        target_anim_overrides = target.get_anim_overrides(None) if target is not None else None
        key = (posture_type, sim.age, target.is_mirrored() if target is not None and target.is_part else None, target_anim_overrides.params if target_anim_overrides is not None else None, actor_name)
        return key

    @staticmethod
    def create_slot_constraint(posture, create_posture_state_spec_fn=None):
        asm_key = posture._asm_key
        sim = posture.sim
        target = posture.target
        if posture.unconstrained:
            return Anywhere()
        if create_posture_state_spec_fn is None:

            def create_posture_state_spec_fn(*_, **__):
                posture_manifest = posture.get_provided_postures(surface_target=MATCH_ANY)
                return PostureStateSpec(posture_manifest, SlotManifest(()), posture.target)

        key = RequiredSlot._get_cache_key(sim, posture.posture_type, target, posture._actor_param_name)
        slots_cached = RequiredSlot._required_slot_cache.get(key)
        if slots_cached is not None:
            slots_new = []
            for slot in slots_cached:
                posture_state_spec = create_posture_state_spec_fn()
                slot_new = slot.clone_slot_for_new_target_and_posture(posture, posture_state_spec)
                slots_new.append(slot_new)
            return create_constraint_set(slots_new)
        state_name = posture._enter_state_name
        exit_slot_start_state = posture._state_name
        actor_name = posture._actor_param_name
        target_name = posture._target_name
        asm = RequiredSlot._get_and_setup_asm_for_required_slot_set(asm_key, sim, target, actor_name, target_name, posture, asm=posture.asm)
        (containment_slot_to_slot_data_entry, containment_slot_to_slot_data_exit) = RequiredSlot._build_relative_slot_data(asm, sim, target, actor_name, target_name, posture, state_name, exit_slot_start_state=exit_slot_start_state)
        if not containment_slot_to_slot_data_entry:
            return Nowhere()
        required_slots = RequiredSlot._build_required_slot_set_from_relative_data(asm, asm_key, sim, target, posture, actor_name, target_name, state_name, containment_slot_to_slot_data_entry, containment_slot_to_slot_data_exit, create_posture_state_spec_fn)
        if required_slots is ANYWHERE:
            posture_state_spec = create_posture_state_spec_fn()
            required_slots = Constraint(posture_state_spec=posture_state_spec)
        else:
            RequiredSlot._required_slot_cache[key] = required_slots
        return required_slots

    @staticmethod
    def create_required_slot_set(sim, target, carry_target, asm_key, state_name, actor_name, target_name, carry_target_name, create_target_name, posture_manifest_overrides, required_slots, posture, surface_target, posture_state_spec, age=None, initial_state_name=DEFAULT, invalid_expected=False):
        if carry_target is not None and (target_name is not None and (target_name != carry_target_name and surface_target is not None)) and target.carryable_component is not None:
            target = surface_target
        if target is None:
            raise RuntimeError('Posture transition failed due to invalid tuning: Trying to create a required slot set with no target. \n  Sim: {}\n  Asm_Key: {}\n  State Name: {}\n  Actor Name: {}\n  Target Name: {}'.format(sim, asm_key, state_name, actor_name, target_name))
        if target.is_sim:
            return Constraint(posture_state_spec=posture_state_spec)
        asm = RequiredSlot._get_and_setup_asm_for_required_slot_set(asm_key, sim, target, actor_name, target_name, posture, carry_target=carry_target, carry_target_name=carry_target_name, create_target_name=create_target_name, surface_target=surface_target, posture_manifest_overrides=posture_manifest_overrides, invalid_expected=invalid_expected)
        if asm is None:
            return Nowhere()
        posture_state_spec_target = target

        def get_posture_state_spec(boundary_condition):
            return RequiredSlot._build_posture_state_spec_for_boundary_condition(boundary_condition, asm, sim, posture_state_spec_target, carry_target, surface_target, actor_name, target_name, carry_target_name, create_target_name, posture, state_name, posture_state_spec, required_slots)

        if target_name is None and target is None and posture is not None:
            target = posture.target
        (route_type, route_target) = target.route_target
        (containment_slot_to_slot_data_entry, _) = RequiredSlot._build_relative_slot_data(asm, sim, target, actor_name, target_name, posture, state_name, initial_state_name=initial_state_name)
        if not containment_slot_to_slot_data_entry:
            return Nowhere()
        if surface_target is DEFAULT:
            surface_target = posture.surface_target
        actual_route_target = None
        for (_, slot_data) in containment_slot_to_slot_data_entry:
            for (boundary_condition, _) in slot_data:
                relative_object_id = boundary_condition.get_relative_object_id(asm)
                while relative_object_id and relative_object_id != target.id:
                    if posture.target is not None and posture.target.id == relative_object_id:
                        actual_route_target = posture.target
                    elif surface_target is not None and surface_target.id == relative_object_id:
                        actual_route_target = surface_target
                    elif sim.id == relative_object_id:
                        actual_route_target = sim
                    else:
                        raise RuntimeError('Unexpected relative object ID: not target, container, or surface.')
                    (route_type, route_target) = actual_route_target.route_target
                    break
        if route_type == interactions.utils.routing.RouteTargetType.PARTS:
            part_owner = actual_route_target or target
            if part_owner.is_part:
                part_owner = part_owner.part_owner
            if len(route_target) > 1:
                route_target = part_owner.get_compatible_parts(posture)
                if not route_target:
                    logger.error('No parts are compatible with {}!', posture)
                    if route_target[0] not in part_owner.get_compatible_parts(posture):
                        return Nowhere()
            elif route_target[0] not in part_owner.get_compatible_parts(posture):
                return Nowhere()
        elif route_type == interactions.utils.routing.RouteTargetType.OBJECT:
            route_target = (route_target,)
        else:
            raise ValueError('Unexpected routing target type {} for object {}'.format(route_type, target))
        slot_constraints = []
        for target in route_target:
            slot_constraints_part = RequiredSlot._build_required_slot_set_from_relative_data(asm, asm_key, sim, target, posture, actor_name, target_name, state_name, containment_slot_to_slot_data_entry, None, get_posture_state_spec, age=age, invalid_expected=invalid_expected)
            slot_constraints.extend(slot_constraints_part)
        if slot_constraints:
            return create_constraint_set(slot_constraints)
        return Nowhere()

class RequiredSlotSingle(SmallAreaConstraint):
    __qualname__ = 'RequiredSlotSingle'
    INTERSECT_PREFERENCE = IntersectPreference.REQUIREDSLOT

    def __init__(self, sim, target, asm, asm_key, posture, actor_name, target_name, state_name, containment_transform, slots_to_params_entry, slots_to_params_exit, geometry=DEFAULT, routing_surface=DEFAULT, slot_offset_info=DEFAULT, asm_name=None, debug_name=DEFAULT, objects_to_ignore=None, **kwargs):
        if routing_surface is DEFAULT:
            routing_surface = target.routing_surface
        if slot_offset_info is DEFAULT:
            slot_offset_info = (asm_key, actor_name, target_name, state_name)
        geometry = create_transform_geometry(containment_transform)
        objects_to_ignore = set(objects_to_ignore or ())
        objects_to_ignore.add(target.id)
        if target.parent is not None:
            objects_to_ignore.add(target.parent.id)
        super().__init__(geometry=geometry, routing_surface=routing_surface, slot_offset_info=slot_offset_info, debug_name=debug_name, objects_to_ignore=objects_to_ignore, **kwargs)
        self._sim_ref = sim.ref()
        self._target = target
        self._asm = asm
        self._asm_key = asm_key
        self._posture = posture
        self._actor_name = actor_name
        self._target_name = target_name
        self._state_name = state_name
        self._containment_transform = containment_transform
        self._slots_to_params_entry = slots_to_params_entry
        self._slots_to_params_exit = slots_to_params_exit
        self._target_transform = target.transform

    @property
    def _sim(self):
        if self._sim_ref is not None:
            return self._sim_ref()

    @property
    def is_required_slot(self):
        return True

    def get_connectivity_handles(self, *args, locked_params=frozendict(), entry=True, weight_route_factor=None, **kwargs):
        if entry or not self._slots_to_params_exit:
            slots_to_params = self._slots_to_params_entry
        else:
            slots_to_params = self._slots_to_params_exit
        if slots_to_params is None:
            return []
        if weight_route_factor is None:
            weight_route_factor = self._weight_route_factor
        handles = []
        for (routing_transform, my_locked_params_list) in slots_to_params:
            for my_locked_params in my_locked_params_list:
                if not do_params_match(my_locked_params, locked_params):
                    pass
                geometry = create_transform_geometry(routing_transform)
                connectivity_handle = routing.connectivity.SlotRoutingHandle(constraint=self, geometry=geometry, locked_params=my_locked_params, weight_route_factor=weight_route_factor, *args, **kwargs)
                handles.append(connectivity_handle)
                break
        return handles

    def _get_goal_from_transform(self, sim, my_locked_params, locked_params, transform):
        locked_params_final = frozendict(my_locked_params, locked_params)
        goal_location = routing.Location(transform.translation, transform.orientation, self._target.routing_surface)
        slot_goal = interactions.utils.routing.SlotGoal(goal_location, self.containment_transform, slot_params=locked_params_final, part=self._target if self._target.is_part else None, cost=self.get_routing_cost(self.containment_transform.translation, self.containment_transform.orientation), group=id(self))
        return slot_goal

    def get_score(self, *args, **kwargs):
        return 1

    @property
    def containment_transform(self):
        return self._containment_transform

    @property
    def average_position(self):
        return self.containment_transform.translation

    def _posture_state_spec_target_resolver(self, target, default=None):
        if target == AnimationParticipant.ACTOR:
            return self._sim
        if target == AnimationParticipant.CONTAINER:
            return self._posture.target
        if target == AnimationParticipant.TARGET:
            return self._target
        return default

    def _intersect(self, other_constraint):
        resolved_constraint = other_constraint.apply_posture_state(None, self._posture_state_spec_target_resolver)
        if not resolved_constraint.valid:
            return Nowhere()
        (early_out, kwargs) = self._intersect_kwargs(resolved_constraint)
        if early_out is not None:
            return early_out
        if not (isinstance(other_constraint, RequiredSlotSingle) and Asm.transform_almost_equal_2d(self.containment_transform, resolved_constraint.containment_transform)):
            return Nowhere()
        if kwargs is None:
            kwargs = {}
        result = RequiredSlotSingle(self._sim, self._target, self._asm, self._asm_key, self._posture, self._actor_name, self._target_name, self._state_name, self.containment_transform, self._slots_to_params_entry, self._slots_to_params_exit, **kwargs)
        return result

    def get_holster_version(self):
        (early_out, kwargs) = self._intersect_kwargs(Anywhere())
        if early_out is not None:
            return early_out
        posture_state_spec = kwargs.get('posture_state_spec')
        if posture_state_spec is not None:
            kwargs['posture_state_spec'] = posture_state_spec.get_holster_version()
        result = RequiredSlotSingle(self._sim, self._target, self._asm, self._asm_key, self._posture, self._actor_name, self._target_name, self._state_name, self.containment_transform, self._slots_to_params_entry, self._slots_to_params_exit, **kwargs)
        return result

    def apply_posture_state(self, posture_state, target_resolver, **kwargs):
        (early_out, constraint_kwargs) = self._intersect_kwargs(Anywhere())
        if early_out is not None:
            return early_out
        slot_constraint = RequiredSlotSingle(self._sim, self._target, self._asm, self._asm_key, self._posture, self._actor_name, self._target_name, self._state_name, self.containment_transform, self._slots_to_params_entry, self._slots_to_params_exit, **constraint_kwargs)
        posture_state_constraint = self._get_posture_state_constraint(posture_state, target_resolver)
        intersection = slot_constraint.intersect(posture_state_constraint)
        return intersection

    def clone_slot_for_new_target_and_posture(self, posture, posture_state_spec):
        sim = posture.sim
        target = posture.target
        original_obj_inverse = sims4.math.get_difference_transform(self._target_transform, sims4.math.Transform())
        transform_between_objs = sims4.math.Transform.concatenate(original_obj_inverse, target.transform)
        containment_transform_new = sims4.math.Transform.concatenate(self._containment_transform, transform_between_objs)
        slots_to_params_entry_new = []
        for (routing_transform_entry, param_sequences) in self._slots_to_params_entry:
            routing_transform_entry_new = sims4.math.Transform.concatenate(routing_transform_entry, transform_between_objs)
            slots_to_params_entry_new.append((routing_transform_entry_new, param_sequences))
        slots_to_params_entry_new = tuple(slots_to_params_entry_new)
        slots_to_params_exit_new = None
        if self._slots_to_params_exit:
            slots_to_params_exit_new = []
            for (routing_transform_exit, param_sequences) in self._slots_to_params_exit:
                routing_transform_exit_new = sims4.math.Transform.concatenate(routing_transform_exit, transform_between_objs)
                slots_to_params_exit_new.append((routing_transform_exit_new, param_sequences))
            slots_to_params_exit_new = tuple(slots_to_params_exit_new)
        (early_out, kwargs) = self._intersect_kwargs(Anywhere())
        if early_out is not None:
            return early_out
        del kwargs['geometry']
        del kwargs['posture_state_spec']
        del kwargs['routing_surface']
        result = RequiredSlotSingle(sim, target, self._asm, self._asm_key, posture, self._actor_name, self._target_name, self._state_name, containment_transform_new, slots_to_params_entry_new, slots_to_params_exit_new, geometry=DEFAULT, routing_surface=target.routing_surface, posture_state_spec=posture_state_spec, **kwargs)
        return result

def Position(position, debug_name=DEFAULT, **kwargs):
    if debug_name is DEFAULT:
        debug_name = 'Position'
    position = sims4.math.vector_flatten(position)
    geometry = sims4.geometry.RestrictedPolygon(sims4.geometry.CompoundPolygon(sims4.geometry.Polygon((position,))), ())
    return SmallAreaConstraint(geometry=geometry, debug_name=debug_name, **kwargs)

class TunedPosition:
    __qualname__ = 'TunedPosition'

    def __init__(self, relative_position):
        self._relative_position = relative_position

    def create_constraint(self, sim, target, **kwargs):
        offset = sims4.math.Transform(self._relative_position, sims4.math.Quaternion.IDENTITY())
        transform = sims4.math.Transform.concatenate(offset, target.intended_transform)
        return Position(transform.translation, routing_surface=target.intended_routing_surface)

class TunablePosition(TunableSingletonFactory):
    __qualname__ = 'TunablePosition'
    FACTORY_TYPE = TunedPosition

    def __init__(self, relative_position, description='A tunable type for creating positional constraints.', **kwargs):
        super().__init__(relative_position=TunableVector3(relative_position, description='Position'), description=description, **kwargs)

def Transform(transform, debug_name=DEFAULT, **kwargs):
    if debug_name is DEFAULT:
        debug_name = 'Transform'
    transform_geometry = create_transform_geometry(transform)
    return SmallAreaConstraint(geometry=transform_geometry, debug_name=debug_name, **kwargs)

def create_transform_geometry(transform):
    if transform.orientation != sims4.math.Quaternion.ZERO():
        facing_direction = transform.transform_vector(sims4.math.FORWARD_AXIS)
        facing_angle = sims4.math.atan2(facing_direction.x, facing_direction.z)
        transform_facing_range = sims4.geometry.AbsoluteOrientationRange(sims4.geometry.interval_from_facing_angle(facing_angle, 0))
        facing_restriction = (transform_facing_range,)
    else:
        facing_restriction = ()
    return sims4.geometry.RestrictedPolygon(sims4.geometry.CompoundPolygon(sims4.geometry.Polygon((sims4.math.vector_flatten(transform.translation),))), facing_restriction)

_DEFAULT_CONE_ROTATION_OFFSET = 0
_DEFAULT_CONE_RADIUS_MIN = 0.25
_DEFAULT_CONE_RADIUS_MAX = 0.75
_DEFAULT_CONE_IDEAL_ANGLE = 0.25
_DEFAULT_CONE_VERTEX_COUNT = 8

def build_weighted_cone(pos, forward, min_radius, max_radius, angle, rotation_offset=_DEFAULT_CONE_ROTATION_OFFSET, ideal_radius_min=_DEFAULT_CONE_RADIUS_MIN, ideal_radius_max=_DEFAULT_CONE_RADIUS_MAX, ideal_angle=_DEFAULT_CONE_IDEAL_ANGLE):
    cone_polygon = sims4.geometry.generate_cone_constraint(pos, forward, min_radius, max_radius, angle, rotation_offset, _DEFAULT_CONE_VERTEX_COUNT)
    cone_polygon.normalize()
    cone_geometry = sims4.geometry.RestrictedPolygon(sims4.geometry.CompoundPolygon(cone_polygon), ())
    ideal_radius_min = min_radius + ideal_radius_min*(max_radius - min_radius)
    ideal_radius_max = min_radius + ideal_radius_max*(max_radius - min_radius)
    ideal_angle_range = ideal_angle*angle*0.5
    max_angle_range = angle*0.5
    center = pos
    forward_theta = sims4.math.vector3_angle(forward) + rotation_offset
    ideal_radius = (ideal_radius_min + ideal_radius_max)*0.5
    scoring_function_radial = ConstraintScoringFunctionRadial(center, ideal_radius, ideal_radius_max - ideal_radius, max(max_radius - ideal_radius, ideal_radius - min_radius))
    scoring_function_angular = ConstraintScoringFunctionAngular(center, forward_theta, ideal_angle_range, max_angle_range)
    scoring_functions = (scoring_function_radial, scoring_function_angular)
    return (cone_geometry, scoring_functions)

def Cone(pos, forward, min_radius, max_radius, angle, routing_surface, rotation_offset=_DEFAULT_CONE_ROTATION_OFFSET, ideal_radius_min=_DEFAULT_CONE_RADIUS_MIN, ideal_radius_max=_DEFAULT_CONE_RADIUS_MAX, ideal_angle=_DEFAULT_CONE_IDEAL_ANGLE, scoring_functions=(), debug_name=DEFAULT, **kwargs):
    if debug_name is DEFAULT:
        debug_name = 'Cone'
    (cone_geometry, cone_scoring_functions) = build_weighted_cone(pos, forward, min_radius, max_radius, angle, rotation_offset=rotation_offset, ideal_radius_min=ideal_radius_min, ideal_radius_max=ideal_radius_max, ideal_angle=ideal_angle)
    scoring_functions = scoring_functions + cone_scoring_functions
    return Constraint(geometry=cone_geometry, scoring_functions=scoring_functions, routing_surface=routing_surface, debug_name=debug_name, **kwargs)

class TunedCone:
    __qualname__ = 'TunedCone'

    def __init__(self, min_radius, max_radius, angle, offset, ideal_radius_min, ideal_radius_max, ideal_angle):
        self._min_radius = min_radius
        self._max_radius = max_radius
        self._angle = angle
        self._offset = offset
        self._ideal_radius_min = ideal_radius_min
        self._ideal_radius_max = ideal_radius_max
        self._ideal_angle = ideal_angle

    def create_constraint(self, sim, target, target_position=DEFAULT, target_forward=DEFAULT, **kwargs):
        if target is not None and target.is_in_inventory():
            if target.is_in_sim_inventory():
                return Anywhere()
            logger.error('Attempt to create a tuned Cone constraint on a target: {} which is in the inventory.  This will not work correctly.', target, owner='mduke')
            return Nowhere()
        if target_position is DEFAULT:
            target_position = target.intended_position
        if target_forward is DEFAULT:
            target_forward = target.intended_forward
        return Cone(target_position, target_forward, self._min_radius, self._max_radius, self._angle, target.intended_routing_surface, self._offset, self._ideal_radius_min, self._ideal_radius_max, self._ideal_angle, **kwargs)

class TunableCone(TunableSingletonFactory):
    __qualname__ = 'TunableCone'
    FACTORY_TYPE = TunedCone

    def __init__(self, min_radius, max_radius, angle, description='A tunable type for creating cone constraints.', callback=None, **kwargs):
        super().__init__(min_radius=Tunable(float, min_radius, description='Minimum cone radius'), max_radius=Tunable(float, max_radius, description='Maximum cone radius'), angle=TunableAngle(angle, description='Cone angle in degrees'), offset=TunableAngle(_DEFAULT_CONE_ROTATION_OFFSET, description='Cone offset (rotation) in degrees'), ideal_radius_min=TunableRange(float, _DEFAULT_CONE_RADIUS_MIN, minimum=0, maximum=1, description='The radial lower bound of an ideal region, as a fraction of the difference between max_radius and min_radius.'), ideal_radius_max=TunableRange(float, _DEFAULT_CONE_RADIUS_MAX, minimum=0, maximum=1, description='The radial upper bound of an ideal region, as a fraction of the difference between max_radius and min_radius.'), ideal_angle=TunableRange(float, _DEFAULT_CONE_IDEAL_ANGLE, minimum=0, maximum=1, description='The angular extents of an ideal region, as a fraction of angle.'), description=description, **kwargs)

class Circle(Constraint):
    __qualname__ = 'Circle'
    NUM_SIDES = Tunable(int, 8, description='The number of polygon sides to use when approximating a circle constraint.')

    def __init__(self, center, radius, routing_surface, ideal_radius=None, ideal_radius_width=0, force_route=False, **kwargs):
        circle_geometry = sims4.geometry.RestrictedPolygon(sims4.geometry.CompoundPolygon(sims4.geometry.generate_circle_constraint(self.NUM_SIDES, center, radius)), ())
        self._center = center
        self._radius = radius
        self._radius_sq = radius*radius
        if ideal_radius is not None:
            scoring_function = ConstraintScoringFunctionRadial(self._center, ideal_radius, ideal_radius_width, self._radius, force_route=force_route)
            scoring_functions = (scoring_function,)
        else:
            scoring_functions = ()
        super().__init__(geometry=circle_geometry, routing_surface=routing_surface, scoring_functions=scoring_functions, **kwargs)

    @property
    def intersect_factory(self):
        return Constraint

class PointRadius(Constraint):
    __qualname__ = 'PointRadius'
    NUM_SIDES = Tunable(int, 8, description='The number of polygon sides to use when approximating a circle constraint.')

    def __init__(self, center, radius, num=None, spacing=1.0, face_center=False, **kwargs):
        circle_geometry = sims4.geometry.RestrictedPolygon(sims4.geometry.CompoundPolygon(sims4.geometry.generate_circle_constraint(self.NUM_SIDES, center, radius)), ())
        self._center = center
        self._radius = radius
        self._radius_sq = radius*radius
        self._num = num
        self._spacing = spacing
        self._face_center = face_center
        super().__init__(geometry=circle_geometry, **kwargs)

    @property
    def intersect_factory(self):
        return Constraint

class TunedCircle:
    __qualname__ = 'TunedCircle'

    def __init__(self, radius, ideal_radius, ideal_radius_width, force_route, require_los):
        self._radius = radius
        self._ideal_radius = ideal_radius
        self._ideal_radius_width = ideal_radius_width
        self._force_route = force_route
        self._require_los = require_los

    def create_constraint(self, sim, target=None, target_position=DEFAULT, routing_surface=DEFAULT):
        if target is not None and target.is_in_inventory():
            if target.is_in_sim_inventory():
                return Anywhere()
            logger.error('Attempt to create a tuned Circle constraint on a target: {} which is in the inventory.  This will not work correctly.', target, owner='mduke')
            return Nowhere()
        if target is None:
            target = sim
        if target_position is DEFAULT:
            target_position = target.intended_position
        if routing_surface is DEFAULT:
            routing_surface = target.intended_routing_surface
        los_reference_point = DEFAULT if self._require_los else None
        return Circle(target_position, self._radius, routing_surface, ideal_radius=self._ideal_radius, ideal_radius_width=self._ideal_radius_width, force_route=self._force_route, los_reference_point=los_reference_point)

class TunableCircle(TunableSingletonFactory):
    __qualname__ = 'TunableCircle'
    FACTORY_TYPE = TunedCircle

    def __init__(self, radius, description='A tunable type for creating Circle constraints.', callback=None, **kwargs):
        super().__init__(radius=Tunable(float, radius, description='Circle radius'), ideal_radius=Tunable(description='\n                                                ideal distance for this circle constraint, points \n                                                closer to the ideal distance will score higher.\n                                                ', tunable_type=float, default=None), ideal_radius_width=Tunable(description='\n                                                This creates a band around the ideal_radius that also\n                                                scores to 1 instead of starting to fall off to 0 in scoring. ex: If you\n                                                have a circle of radius 5, with an ideal_radius of 2.5, and a\n                                                ideal_radius_width of 0.5, any goals in the radius 2 to radius 3 range\n                                                will all score optimially.\n                                                ', tunable_type=float, default=0), force_route=Tunable(description='\n                                               If checked, the Sim will not be allowed to use their current\n                                               position even if it is within the circle constraint.\n                                               ', tunable_type=bool, default=False), require_los=Tunable(description="\n                                               If checked, the Sim will require line of sight to the actor.  Positions where a sim\n                                               can't see the actor (e.g. there's a wall in the way) won't be valid.\n                                               ", tunable_type=bool, default=True), description=description, **kwargs)

class TunedWelcomeConstraint:
    __qualname__ = 'TunedWelcomeConstraint'

    def __init__(self, radius, ideal_radius, find_front_door):
        self._radius = radius
        self._ideal_radius = ideal_radius
        self._find_front_door = find_front_door

    def create_constraint(self, sim, target=None, routing_surface=DEFAULT, **kwargs):
        zone = services.current_zone()
        if zone is None:
            logger.error('Attempting to create welcome constraint when zone is None.', owner='jjacobson')
            return Nowhere()
        active_lot = zone.lot
        if active_lot is None:
            logger.error('Attempting to create welcome constraint when active lot is None.', owner='jjacobson')
            return Nowhere()
        front_door = None if not self._find_front_door else services.object_manager().get(active_lot.front_door_id)
        if front_door is not None:
            position = front_door.position
            routing_surface = front_door.routing_surface
        else:
            spawn_point = zone.get_spawn_point(lot_id=active_lot.lot_id, sim_spawner_tags=SimInfoSpawnerTags.SIM_SPAWNER_TAGS)
            position = spawn_point.center
            routing_surface = routing.SurfaceIdentifier(zone.id, 0, SURFACETYPE_WORLD)
        return Circle(position, self._radius, routing_surface=routing_surface, ideal_radius=self._ideal_radius)

class TunableWelcomeConstraint(TunableSingletonFactory):
    __qualname__ = 'TunableWelcomeConstraint'
    FACTORY_TYPE = TunedWelcomeConstraint

    def __init__(self, radius, description='A tunable type for creating circle constraints to an object that has the Welcome component', callback=None, **kwargs):
        super().__init__(radius=Tunable(float, radius, description='Circle radius'), ideal_radius=Tunable(float, None, description='ideal distance for this front door constraint, points closer to the ideal distance will score higher.'), find_front_door=Tunable(bool, True, description='\n                            If True the constraint will try and locate the front door on the lot\n                            and use that location before using the spawn points. If False\n                            the spawn points will always be used. The tuning for the spawn\n                            tags is in sim_info_types.tuning.\n                            '), description=description, **kwargs)

class FrontDoorOption(enum.Int):
    __qualname__ = 'FrontDoorOption'
    OUTSIDE_FRONT_DOOR = 0
    INSIDE_FRONT_DOOR = 1

class TunedFrontDoorConstraint:
    __qualname__ = 'TunedFrontDoorConstraint'

    def __init__(self, ideal_radius, line_of_sight, front_door_position_option):
        self._ideal_radius = ideal_radius
        self._line_of_sight = line_of_sight
        self._front_door_position_option = front_door_position_option

    def create_constraint(self, sim, target=None, routing_surface=DEFAULT, **kwargs):
        zone = services.current_zone()
        if zone is None:
            logger.error('Attempting to create Inside Front Door constraint when zone is None.', owner='nbaker')
            return Nowhere()
        active_lot = zone.lot
        if active_lot is None:
            logger.error('Attempting to create Inside Front Door constraint when active lot is None.', owner='nbaker')
            return Nowhere()
        front_door = services.object_manager().get(active_lot.front_door_id)
        if front_door is not None:
            if self._front_door_position_option == FrontDoorOption.OUTSIDE_FRONT_DOOR:
                position = front_door.front_pos
            else:
                position = front_door.back_pos
            routing_surface = front_door.routing_surface
        else:
            return Nowhere()
        los_factory = self._line_of_sight()
        los_factory.generate(position, routing_surface)
        los_constraint = los_factory.constraint
        circle_constraint = Circle(position, self._line_of_sight.max_line_of_sight_radius, routing_surface=routing_surface, ideal_radius=self._ideal_radius)
        return circle_constraint.intersect(los_constraint)

class TunableFrontDoorConstraint(TunableSingletonFactory):
    __qualname__ = 'TunableFrontDoorConstraint'
    FACTORY_TYPE = TunedFrontDoorConstraint

    def __init__(self, description='A tunable type for creating a constraint inside or outside the front door', callback=None, **kwargs):
        from objects.components.line_of_sight_component import TunableLineOfSightFactory
        super().__init__(ideal_radius=Tunable(description='\n                            ideal distance for this front door constraint, \n                            points closer to the ideal distance will score higher.\n                            ', tunable_type=float, default=2), line_of_sight=TunableLineOfSightFactory(description='\n                            Tuning to generate a light of sight constraint\n                            either inside or outside the front door in\n                            order to get the sims to move there.\n                            '), front_door_position_option=TunableEnumEntry(description='\n                             The option of whether to use the inside or outside\n                             side of the front door in order to generate the\n                             constraint.\n                             ', tunable_type=FrontDoorOption, default=FrontDoorOption.OUTSIDE_FRONT_DOOR), description=description, **kwargs)

class TunableShape(TunableVariant):
    __qualname__ = 'TunableShape'

    def __init__(self, *args, **kwargs):
        super().__init__(circle=TunableCircle(0.3), cone=TunableCone(0, 1, sims4.math.PI), *args, **kwargs)

class PostureConstraintFactory(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'PostureConstraintFactory'

    @staticmethod
    def on_tunable_loaded_callback(instance_class, tunable_name, source, value):
        posture_manifest = PostureManifest()
        for tuning in value.posture_manifest_tuning:
            posture_manifest_entry = value._create_manifest_entry(**tuning)
            posture_manifest.add(posture_manifest_entry)
        posture_manifest = posture_manifest.intern()
        body_target = value.body_target_tuning
        if value.slot_manifest_tuning:
            constraints = []
            for tuning in value.slot_manifest_tuning:
                slot_manifest = SlotManifest()
                slot_manifest_entry = SlotManifestEntry(tuning.child, tuning.parent, tuning.slot)
                slot_manifest.add(slot_manifest_entry)
                posture_state_spec = PostureStateSpec(posture_manifest, slot_manifest, body_target)
                constraint = Constraint(posture_state_spec=posture_state_spec, debug_name='TunablePostureConstraint')
                constraints.append(constraint)
            value._constraint = create_constraint_set(constraints)
        else:
            posture_state_spec = PostureStateSpec(posture_manifest, SlotManifest(), body_target)
            value._constraint = Constraint(posture_state_spec=posture_state_spec, debug_name='TunablePostureConstraint')

    FACTORY_TUNABLES = {'posture_manifest_tuning': TunableList(description='A list of posture manifests this interaction should support.', tunable=TunableTuple(description='A posture manifests this interaction should support.', actor=OptionalTunable(TunableEnumEntry(AnimationParticipant, AnimationParticipant.ACTOR, description='The animation participant of this posture test.')), posture_type=OptionalTunable(TunableReference(services.get_instance_manager(sims4.resources.Types.POSTURE), description='The posture required by this constraint')), compatibility=TunableVariant(default='Any', locked_args={'Any': MATCH_ANY, 'UpperBody': UPPER_BODY, 'FullBody': FULL_BODY}, description='posture level. upper body, full body or any'), carry_left=TunableVariant(default='Any', actor=TunableEnumEntry(AnimationParticipant, AnimationParticipant.CARRY_TARGET), locked_args={'Any': MATCH_ANY, 'None': MATCH_NONE}, description='tuning for requirements for carry left. either any, none, or animation participant'), carry_right=TunableVariant(default='Any', actor=TunableEnumEntry(AnimationParticipant, AnimationParticipant.CARRY_TARGET), locked_args={'Any': MATCH_ANY, 'None': MATCH_NONE}, description='tuning for requirements for carry right. either any, none, or animation participant'), surface=TunableVariant(default='Any', actor=TunableEnumEntry(AnimationParticipant, AnimationParticipant.SURFACE), locked_args={'Any': MATCH_ANY, 'None': MATCH_NONE}, description='tuning for requirements for surface. either any, none, or animation participant'))), 'slot_manifest_tuning': TunableList(description="\n                    A list of slot requirements that will be OR'd together \n                    for this interaction.  \n                    ", tunable=TunableTuple(description='A slot requirement for this interaction.  Adding a slot manifest will require the specified relationship between actors to exist before the interaction runs.  If the child object is carryable, the transition system will attempt to have the Sim move the child object into the correct type of slot.', child=TunableVariant(default='participant', participant=TunableEnumEntry(AnimationParticipant, AnimationParticipant.TARGET, description='If this is CREATE_TARGET, the transition system will find an empty slot of the specified type in which the object being created by the interaction will fit.'), definition=TunableReference(description='\n                            If used, the transition system will find an empty slot of the specified type in which an object of this definition can fit.\n                            ', manager=services.definition_manager())), parent=TunableEnumEntry(AnimationParticipant, AnimationParticipant.SURFACE), slot=TunableReference(services.get_instance_manager(sims4.resources.Types.SLOT_TYPE)))), 'body_target_tuning': TunableEnumEntry(description='The body target of the posture.', tunable_type=PostureSpecVariable, default=PostureSpecVariable.ANYTHING), 'callback': on_tunable_loaded_callback}

    def __init__(self, *args, **kwargs):
        self._constraint = None
        super().__init__(*args, **kwargs)

    def _create_manifest_entry(self, actor, posture_type, compatibility, carry_left, carry_right, surface):
        posture_name = MATCH_ANY
        posture_family_name = MATCH_ANY
        if posture_type is not None:
            posture_name = posture_type.name
            posture_family_name = posture_type.family_name
        return PostureManifestEntry(actor, posture_name, posture_family_name, compatibility, carry_left, carry_right, surface)

    def create_constraint(self, *_, **__):
        return self._constraint

class ObjectJigConstraint(SmallAreaConstraint, HasTunableSingletonFactory):
    __qualname__ = 'ObjectJigConstraint'
    INTERSECT_PREFERENCE = IntersectPreference.SPECIAL
    JIG_CONSTRAINT_LIABILITY = 'JigConstraintLiability'

    class JigConstraintLiability(Liability):
        __qualname__ = 'ObjectJigConstraint.JigConstraintLiability'

        def __init__(self, jig, constraint):
            self.jig = jig
            self.constraint = constraint

        def release(self):
            self.jig.destroy(source=self, cause='Destroying Jig in ObjectJigConstraint.')

    def __init__(self, jig_definition, sim=None, target=None, ignore_sim=True, **kwargs):
        super().__init__(**kwargs)
        self._jig_definition = jig_definition
        self._ignore_sim = ignore_sim

    @property
    def intersect_factory(self):
        return lambda **kwargs: type(self)(self._jig_definition, **kwargs)

    def _intersect(self, other_constraint):
        (early_out, kwargs) = self._intersect_kwargs(other_constraint)
        if early_out is not None:
            return early_out
        return TentativeIntersection((self, other_constraint), **kwargs)

    def create_concrete_version(self, interaction):
        fgl_context = interactions.utils.routing.get_fgl_context_for_jig_definition(self._jig_definition, interaction.sim, ignore_sim=self._ignore_sim)
        (translation, orientation) = find_good_location(fgl_context)
        if translation is None or orientation is None:
            logger.warn('Failed to find a good location for {}', interaction, owner='bhill')
            return NOWHERE
        transform = sims4.math.Transform(translation, orientation)

        def create_jig_object():
            liability = interaction.get_liability(self.JIG_CONSTRAINT_LIABILITY)
            if liability is not None:
                if liability.jig.definition is not self._jig_definition:
                    logger.error('Interaction {} is tuned to have multiple jig constraints, which is not allowed.', interaction)
                raise AssertionError("Liability should not have a tentative constraint, it's set just below this to a concrete constraint. [bhill]")
            else:
                jig_object = objects.system.create_object(self._jig_definition)
                jig_object.opacity = 0
                jig_object.move_to(translation=translation, orientation=orientation, routing_surface=interaction.sim.routing_surface)
                liability = JigConstraint.JigConstraintLiability(jig_object, concrete_constraint)
                interaction.add_liability(self.JIG_CONSTRAINT_LIABILITY, liability)

        concrete_constraint = self._get_concrete_constraint(transform, interaction.sim.routing_surface, create_jig_object)
        return concrete_constraint

    def _get_concrete_constraint(self, transform, routing_surface, create_jig_fn):
        object_slots = self._jig_definition.get_slots_resource(0)
        slot_transform = object_slots.get_slot_transform_by_index(sims4.ObjectSlots.SLOT_ROUTING, 0)
        transform = sims4.math.Transform.concatenate(transform, slot_transform)
        return Transform(transform, routing_surface=routing_surface, create_jig_fn=create_jig_fn)

    @property
    def tentative(self):
        return True

class JigConstraint(ObjectJigConstraint):
    __qualname__ = 'JigConstraint'
    FACTORY_TUNABLES = {'description': '\n            A constraint defined by a location on a specific jig object,\n            which will be placed when the constraint is bound and will\n            live for the duration of the interaction owning the constraint.\n            ', 'jig': TunableReference(description='\n            The jig defining the constraint.', manager=services.definition_manager())}

    def __init__(self, jig, sim=None, target=None, **kwargs):
        super().__init__(jig, **kwargs)

    def create_constraint(self, *args, **kwargs):
        return JigConstraint(self._jig_definition, *args, **kwargs)

class ObjectPlacementConstraint(ObjectJigConstraint):
    __qualname__ = 'ObjectPlacementConstraint'
    FACTORY_TUNABLES = {'description': '\n            A constraint defined by a location on a specific jig object,\n            which will be placed when the constraint is bound and will\n            live for the duration of the interaction owning the constraint.\n            '}

    def __init__(self, jig_definition=None, sim=None, target=None, **kwargs):
        if jig_definition is None and target is not None:
            jig_definition = target.definition
        super().__init__(jig_definition, **kwargs)

    def create_constraint(self, *args, **kwargs):
        return ObjectPlacementConstraint(self._jig_definition, ignore_sim=False, *args, **kwargs)

    def _get_concrete_constraint(self, transform, routing_surface, create_jig_fn):
        footprint = self._jig_definition.get_footprint(0)
        polygon = placement.get_placement_footprint_polygon(transform.translation, transform.orientation, routing_surface, footprint)
        radius = polygon.radius()
        circle = Circle(transform.translation, radius + 0.5, routing_surface, ideal_radius=radius, allow_small_intersections=True, create_jig_fn=create_jig_fn)
        return circle.intersect(Facing(target_position=transform.translation))

class RelativeCircleConstraint(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'RelativeCircleConstraint'
    FACTORY_TUNABLES = {'minimum_radius': OptionalTunable(description='\n            If enabled, the generated constraint will have a radius no smaller\n            than the specified amount.\n            ', tunable=TunableRange(description="\n                The constraint's minimum radius.\n                ", tunable_type=float, minimum=0, default=1)), 'maximum_radius': OptionalTunable(description='\n            If enabled, the generated constraint will have a radius no larger\n            that the specified amount.\n            ', tunable=TunableRange(description="\n                The constraint's maximum radius.\n                ", tunable_type=float, minimum=0, default=1)), 'relative_radius': TunableRange(description="\n            The constraint's radius relative to the size of the object. This is\n            a simple multiplier applied to the area generated by the object's\n            footprint\n            ", tunable_type=float, minimum=1, default=1), 'relative_ideal_radius': OptionalTunable(description="\n            If enabled, specify an ideal radius relative to the constraint's\n            radius. \n            ", tunable=TunableTuple(description='\n                Ideal radius data.\n                ', radius=TunableRange(description="\n                    The constraint's relative ideal radius. A value of 1 would\n                    mean the ideal location is on the outskirt of the\n                    constraint; values towards 0 approach the constraint's\n                    center.\n                    ", tunable_type=float, minimum=0, maximum=1, default=1), width=Tunable(description='\n                    This creates a band around the ideal_radius that also scores\n                    to 1 instead of starting to fall off to 0 in scoring. ex: If\n                    you have a circle of radius 5, with an ideal_radius of 2.5,\n                    and a ideal_radius_width of 0.5, any goals in the radius 2\n                    to radius 3 range will all score optimially.\n                    ', tunable_type=float, default=0)))}

    def create_constraint(self, sim, target, **kwargs):
        footprint = target.definition.get_footprint() if target is not None and target.definition is not None else None
        if footprint is not None:
            polygon = placement.get_placement_footprint_polygon(target.position, target.orientation, target.routing_surface, footprint)
            if polygon:
                radius = polygon.radius()*self.relative_radius
                if self.minimum_radius is not None:
                    radius = max(self.minimum_radius, radius)
                if self.maximum_radius is not None:
                    radius = min(self.maximum_radius, radius)
                ideal_radius = None if self.relative_ideal_radius is None else radius*self.relative_ideal_radius.radius
                ideal_radius_width = 0 if self.relative_ideal_radius is None else self.relative_ideal_radius.width
                return Circle(polygon.centroid(), radius, target.routing_surface, ideal_radius=ideal_radius, ideal_radius_width=ideal_radius_width)
        logger.warn('Object {} does not support relative circle constraints, possibly because it has no footprint. Using Anywhere instead.', target, owner='epanero')
        return Anywhere()

class TunableGeometricConstraintVariant(TunableVariant):
    __qualname__ = 'TunableGeometricConstraintVariant'

    def __init__(self, **kwargs):
        super().__init__(facing=TunableFacing(description='Existential tunable that requires the sim to face the object.'), line_of_sight=TunableLineOfSight(description='Existential tunable that creates a line of sight constraint.'), cone=TunableCone(0, 1, sims4.math.PI, description='The relative cone geometry required for a sim/posture to use the object.'), circle=TunableCircle(1, description='The relative circle geometry required for a sim/posture to use the object.'), spawn_points=TunableSpawnPoint(description='A constraint that represents all of the spawn locations on the lot.'), relative_circle=RelativeCircleConstraint.TunableFactory(), **kwargs)

class TunableConstraintVariant(TunableGeometricConstraintVariant):
    __qualname__ = 'TunableConstraintVariant'

    def __init__(self, **kwargs):
        super().__init__(position=TunablePosition(sims4.math.Vector3(0, 0, 0), description='The relative position geometry required for a sim/posture to use the object.'), posture=PostureConstraintFactory.TunableFactory(), welcome=TunableWelcomeConstraint(1, description='A constraint that requires the sim be at the object with the highest scoring Welcome Component'), front_door=TunableFrontDoorConstraint(), jig=JigConstraint.TunableFactory(), animation=TunableAnimationConstraint(), object_placement=ObjectPlacementConstraint.TunableFactory(), **kwargs)

