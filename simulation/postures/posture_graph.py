from collections import OrderedDict, namedtuple, defaultdict
from contextlib import contextmanager
import collections
import functools
import itertools
import operator
import weakref
import xml.etree
from animation.posture_manifest import SlotManifestEntry
from carry.carry_postures import CarryingObject
from element_utils import build_element, maybe
from event_testing.results import TestResult
from indexed_manager import CallbackTypes
from interactions import ParticipantType
from interactions.aop import AffordanceObjectPair
from interactions.base.interaction import ReservationLiability, RESERVATION_LIABILITY
from interactions.constraints import create_transform_geometry, Anywhere, ANYWHERE
from interactions.context import InteractionContext, QueueInsertStrategy, InteractionSource
from interactions.interaction_finisher import FinishingType
from interactions.priority import Priority
from interactions.utils.balloon import PassiveBalloons
from interactions.utils.reserve import MultiReserveObjectHandler
from interactions.utils.routing import FollowPath, get_route_element_for_path, SlotGoal
from interactions.utils.routing_constants import TransitionFailureReasons
from objects.definition import Definition
from objects.helpers.user_footprint_helper import push_route_away
from placement import NON_SUPPRESSED_FAILURE_GOAL_SCORE
from postures import DerailReason
from postures.base_postures import create_puppet_postures
from postures.posture_scoring import PostureScoring
from postures.posture_specs import PostureSpecVariable, PostureSpec, PostureOperation, get_origin_spec, get_origin_spec_carry, with_caches, SURFACE_INDEX, BODY_INDEX, SURFACE_TARGET_INDEX, BODY_TARGET_INDEX, BODY_POSTURE_TYPE_INDEX, CARRY_INDEX, CARRY_TARGET_INDEX, SURFACE_SLOT_TYPE_INDEX, SURFACE_SLOT_TARGET_INDEX, get_pick_up_spec_sequence, get_put_down_spec_sequence, node_matches_spec, destination_test, PostureAspectBody, PostureAspectSurface
from sims4 import reload
from sims4.callback_utils import CallableTestList
from sims4.collections import frozendict
from sims4.geometry import test_point_in_compound_polygon
from sims4.log import Logger
from sims4.repr_utils import standard_angle_repr, suppress_quotes
from sims4.service_manager import Service
from sims4.sim_irq_service import yield_to_irq
from sims4.tuning.tunable import Tunable, TunableReference, TunableList
from sims4.utils import enumerate_reversed
from singletons import DEFAULT
import algos
import build_buy
import caches
import debugvis
import element_utils
import elements
import enum
import gsi_handlers.posture_graph_handlers
import interactions.utils.routing
import postures
import primitives.routing_utils
import routing
import services
import sims4.geometry
import sims4.math
import sims4.reload
MAX_RIGHT_PATHS = 30
NON_OPTIMAL_PATH_DESTINATION = 1000
logger = Logger('PostureGraph')
with sims4.reload.protected(globals()):
    SIM_DEFAULT_POSTURE_TYPE = None
    SIM_DEFAULT_AOP = None
    SIM_DEFAULT_OPERATION = None
    STAND_AT_NONE = None
    STAND_AT_NONE_CARRY = None
    STAND_AT_NONE_NODES = None
    enable_goal_scoring_visualization = False
InsertionIndexAndSpec = namedtuple('InsertionIndexAndSpec', ['index', 'spec'])

class DistanceEstimator:
    __qualname__ = 'DistanceEstimator'

    def __init__(self, posture_service, sim, interaction, constraint):
        self.posture_service = posture_service
        self.sim = sim
        self.interaction = interaction
        preferred_objects = interaction.preferred_objects
        self.preferred_objects = preferred_objects
        self.constraint = constraint

        @caches.BarebonesCache
        def estimate_crows_flight_distance(objects):
            return primitives.routing_utils._estimate_distance_helper(*objects)

        self.estimate_crows_flight_distance = estimate_crows_flight_distance

        @caches.BarebonesCache
        def estimate_connectivity_distance(objects):
            (obj_a, obj_b) = objects
            if obj_a is None or obj_b is None:
                return 0.0
            distance = primitives.routing_utils.estimate_distance_between_points(obj_a.position_with_forward_offset, obj_a.routing_surface, obj_b.position_with_forward_offset, obj_b.routing_surface, sim.routing_context)
            distance = sims4.math.MAX_FLOAT if distance is None else distance
            return distance

        self.estimate_connectivity_distance = estimate_connectivity_distance
        self.estimate_distance = estimate_distance = estimate_connectivity_distance

        @caches.BarebonesCache
        def get_preferred_object_cost(obj):
            return postures.posture_scoring.PostureScoring.get_preferred_object_cost((obj,), preferred_objects)

        self.get_preferred_object_cost = get_preferred_object_cost

        @caches.BarebonesCache
        def get_inventory_distance(inv_and_node_target):
            (inv, node_target) = inv_and_node_target
            min_dist = sims4.math.MAX_FLOAT
            for owner in inv.owning_objects_gen():
                distance = estimate_distance((sim, owner))
                if distance >= min_dist:
                    pass
                distance += get_preferred_object_cost(owner)
                if distance >= min_dist:
                    pass
                if node_target is not None:
                    distance += estimate_distance((owner, node_target))
                while distance < min_dist:
                    min_dist = distance
            return min_dist

        self.get_inventory_distance = get_inventory_distance

        @caches.BarebonesCache
        def estimate_object_distance(node_target):
            if isinstance(node_target, PostureSpecVariable):
                logger.warn('Attempt to estimate distance to a PostureSpecVariable: {} for {}', node_target, interaction)
                node_target = None
            if interaction.target is None:
                return estimate_distance((sim, node_target))
            carry_target = interaction.carry_target
            if carry_target is None and interaction.target is not None and interaction.target.carryable_component is not None:
                carry_target = interaction.target
            if carry_target is None:
                return estimate_distance((sim, node_target))
            inv = interaction.target.get_inventory()
            if inv is None:
                if interaction.target.is_same_object_or_part(node_target):
                    return estimate_distance((sim, interaction.target))
                return estimate_distance((sim, interaction.target)) + estimate_distance((interaction.target, node_target))
            if inv.owner.is_sim:
                if inv.owner is not sim:
                    return NON_OPTIMAL_PATH_DESTINATION
                return estimate_distance((sim, node_target))
            return get_inventory_distance((inv, node_target))

        self.estimate_object_distance = estimate_object_distance

        def estimate_goal_cost(node):
            return estimate_object_distance(node.body_target or node.surface_target) + posture_service._goal_costs.get(node, 0.0)

        self.estimate_goal_cost = estimate_goal_cost

class PathType(enum.Int, export=False):
    __qualname__ = 'PathType'
    LEFT = 0
    MIDDLE = 1
    RIGHT = 2

class SegmentedPath:
    __qualname__ = 'SegmentedPath'

    def __init__(self, posture_graph, sim, source, destination_specs, var_map, constraint, valid_edge_test, interaction, is_complete=True, distance_estimator=None):
        self.posture_graph = posture_graph
        self.sim = sim
        self.interaction = interaction
        self.source = source
        if not destination_specs:
            raise ValueError('Segmented paths need destinations.')
        self.destinations = destination_specs.keys()
        self.valid_edge_test = valid_edge_test
        self.var_map = var_map
        self._var_map_resolved = None
        self.constraint = constraint
        self.destination_specs = destination_specs
        self.is_complete = is_complete
        if distance_estimator is None:
            distance_estimator = DistanceEstimator(self.posture_graph, self.sim, self.interaction, constraint)
        self._distance_estimator = distance_estimator

    @property
    def var_map_resolved(self):
        if self._var_map_resolved is None:
            return self.var_map
        return self._var_map_resolved

    @var_map_resolved.setter
    def var_map_resolved(self, value):
        self._var_map_resolved = value

    def check_validity(self, sim):
        source_spec = sim.posture_state.get_posture_spec(self.var_map)
        return source_spec == self.source

    def generate_left_paths(self):
        left_path_gen = self.posture_graph._left_path_gen(self.sim, self.source, self.destinations, self.interaction, self.constraint, self.var_map, self.valid_edge_test, is_complete=self.is_complete)
        for path_left in left_path_gen:
            path_left.segmented_path = self
            yield path_left

    def generate_right_paths(self, path_left):
        if path_left[-1] in self.destinations and len(self.destinations) == 1:
            cost = self.posture_graph._get_goal_cost(self.sim, self.interaction, self.constraint, self.var_map, path_left[-1])
            path_right = algos.Path([path_left[-1]], cost)
            path_right.segmented_path = self
            yield path_right
            return
        if self.is_complete:
            left_destinations = (path_left[-1],)
        else:
            carry = self.var_map.get(PostureSpecVariable.CARRY_TARGET)
            if carry is not None and path_left[-1].carry_target is None:
                for constraint in self.constraint:
                    while constraint.posture_state_spec is not None and constraint.posture_state_spec.references_object(carry):
                        break
                carry = None
            if carry is None or isinstance(carry, Definition):
                left_destinations = (STAND_AT_NONE,)
            elif carry.get_inventory() is None and carry.parent not in (None, self.sim):
                left_destinations = STAND_AT_NONE_NODES
            else:
                left_destinations = (STAND_AT_NONE_CARRY,)
        self.left_destinations = left_destinations
        paths_right = self.posture_graph._right_path_gen(self.sim, self.interaction, self._distance_estimator, left_destinations, self.destinations, self.var_map, self.constraint, self.valid_edge_test)
        for path_right in paths_right:
            path_right.segmented_path = self
            yield path_right

    def generate_middle_paths(self, path_left, path_right):
        if self.is_complete:
            yield None
            return
        middle_paths = self.posture_graph._middle_path_gen(path_left, path_right, self.sim, self.interaction, self._distance_estimator, self.var_map)
        for path_middle in middle_paths:
            if path_middle is not None:
                path_middle.segmented_path = self
            yield path_middle

    @property
    def _path(self):
        return algos.Path(list(getattr(self, '_path_left', ['...?'])) + list(getattr(self, '_path_middle', ['...', '...?']) or [])[1:] + list(getattr(self, '_path_right', ['...', '...?']))[1:])

    def __repr__(self):
        if self.is_complete:
            return 'CompleteSegmentedPath(...)'
        return 'SegmentedPath(...)'

class Connectivity:
    __qualname__ = 'Connectivity'

    def __init__(self, best_complete_path, source_destination_sets, source_middle_sets, middle_destination_sets):
        self.best_complete_path = best_complete_path
        self.source_destination_sets = source_destination_sets
        self.source_middle_sets = source_middle_sets
        self.middle_destination_sets = middle_destination_sets

    def __repr__(self):
        return 'Connectivity%r' % (tuple(self),)

    def __bool__(self):
        return any(self)

    def __iter__(self):
        return iter((self.best_complete_path, self.source_destination_sets, self.source_middle_sets, self.middle_destination_sets))

    def __getitem__(self, i):
        return (self.best_complete_path, self.source_destination_sets, self.source_middle_sets, self.middle_destination_sets)[i]

class TransitionSequenceStage(enum.Int, export=False):
    __qualname__ = 'TransitionSequenceStage'
    EMPTY = Ellipsis
    TEMPLATES = Ellipsis
    PATHS = Ellipsis
    CONNECTIVITY = Ellipsis
    ROUTES = Ellipsis
    ACTOR_TARGET_SYNC = Ellipsis
    COMPLETE = Ellipsis

class SequenceId(enum.Int, export=False):
    __qualname__ = 'SequenceId'
    DEFAULT = 0
    PICKUP = 1
    PUTDOWN = 2

_MobileNode = namedtuple('_MobileNode', ('graph_node', 'prev'))

def _shortest_path_gen(sources, destinations, *args, **kwargs):

    def is_destination(node):
        if isinstance(node, _MobileNode):
            node = node.graph_node
        return node in destinations

    fake_paths = algos.shortest_path_gen(sources, is_destination, *args, **kwargs)
    for fake_path in fake_paths:
        path = algos.Path([node.graph_node if isinstance(node, _MobileNode) else node for node in fake_path], fake_path.cost)
        yield path

def set_transition_failure_reason(sim, reason, target_id=None, transition_controller=None):
    if transition_controller is None:
        transition_controller = sim.transition_controller
    if transition_controller is not None:
        transition_controller.set_failure_target(sim, reason, target_id=target_id)

def _cache_global_sim_default_values():
    global SIM_DEFAULT_POSTURE_TYPE, STAND_AT_NONE, STAND_AT_NONE_CARRY, STAND_AT_NONE_NODES, SIM_DEFAULT_AOP, SIM_DEFAULT_OPERATION
    SIM_DEFAULT_POSTURE_TYPE = PostureGraphService.SIM_DEFAULT_AFFORDANCE.provided_posture_type
    STAND_AT_NONE = get_origin_spec(SIM_DEFAULT_POSTURE_TYPE)
    STAND_AT_NONE_CARRY = get_origin_spec_carry(SIM_DEFAULT_POSTURE_TYPE)
    STAND_AT_NONE_NODES = (STAND_AT_NONE, STAND_AT_NONE_CARRY)
    SIM_DEFAULT_AOP = AffordanceObjectPair(PostureGraphService.SIM_DEFAULT_AFFORDANCE, None, PostureGraphService.SIM_DEFAULT_AFFORDANCE, None, force_inertial=True)
    SIM_DEFAULT_OPERATION = PostureOperation.BodyTransition(SIM_DEFAULT_POSTURE_TYPE, SIM_DEFAULT_AOP)

@contextmanager
def supress_posture_graph_build(rebuild=True):
    posture_graph_service = services.current_zone().posture_graph_service
    posture_graph_service.disable_graph_building()
    try:
        yield None
    finally:
        posture_graph_service.enable_graph_building()
        if rebuild:
            posture_graph_service.rebuild()

class TransitionSpec:
    __qualname__ = 'TransitionSpec'
    DISTANCE_TO_FADE_SIM_OUT = Tunable(description='\n        Distance at which a Sim will start fading out if tuned as such.\n        ', tunable_type=float, default=5.0)

    def __init__(self, path_spec, posture_spec, var_map, sequence_id=SequenceId.DEFAULT, portal=None):
        self.posture_spec = posture_spec
        self._path_spec = path_spec
        self.var_map = var_map
        self.path = None
        self.final_constraint = None
        self._transition_interactions = {}
        self.sequence_id = sequence_id
        self.locked_params = frozendict()
        self._additional_reservation_handlers = []
        self.handle_slot_reservations = False
        self._portal_ref = weakref.ref(portal) if portal is not None else None
        self.created_posture_state = None

    @property
    def mobile(self):
        return self.posture_spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile

    @property
    def is_failure_path(self):
        return self._path_spec.is_failure_path

    @property
    def final_si(self):
        return self._path_spec._final_si

    @property
    def is_carry(self):
        return self.posture_spec[CARRY_INDEX][CARRY_TARGET_INDEX] is not None

    @property
    def targets_empty_slot(self):
        surface_spec = self.posture_spec[SURFACE_INDEX]
        if surface_spec[SURFACE_SLOT_TYPE_INDEX] is not None and surface_spec[SURFACE_SLOT_TARGET_INDEX] is None:
            return True
        return False

    @property
    def portal(self):
        if self._portal_ref is not None:
            return self._portal_ref()

    @portal.setter
    def portal(self, value):
        self._portal_ref = weakref.ref(value) if value is not None else None

    def transition_interactions(self, sim):
        if sim in self._transition_interactions:
            return self._transition_interactions[sim]
        return []

    def test_transition_interactions(self, sim, interaction):
        if sim in self._transition_interactions:
            for (si, _) in self._transition_interactions[sim]:
                if si is interaction:
                    pass
                while si is not None and not si.aop.test(si.context):
                    return False
        return True

    def get_multi_target_interaction(self, sim):
        final_si = self._path_spec._final_si
        for (si, _) in self._transition_interactions[sim]:
            while si is not final_si:
                return si

    def set_path(self, path, final_constraint):
        self.path = path
        if final_constraint is not None and final_constraint.tentative:
            logger.warn("TransitionSpec's final constraint is tentative, this will not work correctly so the constraint will be ignored. This may interfere with slot reservation.", owner='jpollak')
        else:
            self.final_constraint = final_constraint

    def transfer_route_to(self, other_spec):
        other_spec.path = self.path
        self.path = None

    def add_transition_interaction(self, sim, interaction, var_map):
        if interaction is not None and not interaction.get_participant_type(sim) == ParticipantType.Actor:
            return
        if sim not in self._transition_interactions:
            self._transition_interactions[sim] = []
        self._transition_interactions[sim].append((interaction, var_map))

    def set_locked_params(self, locked_params):
        self.locked_params = locked_params

    def __repr__(self):
        args = [self.posture_spec]
        kwargs = {}
        if self.path is not None:
            args.append(suppress_quotes('has_route'))
        if self.locked_params:
            kwargs['locked_params'] = self.locked_params
        if self.final_constraint is not None:
            kwargs['final_constraint'] = self.final_constraint
        return standard_angle_repr(self, *args, **kwargs)

    def release_additional_reservation_handlers(self):
        for handler in self._additional_reservation_handlers:
            handler.end()
        self._additional_reservation_handlers.clear()

    def remove_props_created_to_reserve_slots(self, sim):
        for (reservation_si, _) in self._transition_interactions.get(sim, []):
            while reservation_si is not None:
                reservation_si.animation_context.clear_reserved_slots()

    def do_reservation(self, sim, is_failure_path=False):

        def cancel_reservations():
            for handler in reserve_object_handlers:
                handler.end()

        def add_reservation(handler, test_only=False):
            reserve_result = handler.may_reserve()
            if not reserve_result:
                blocking_obj = None
                for obj in handler.get_targets():
                    while blocking_obj is None:
                        while True:
                            for user in obj.get_users(include_multi=handler.is_multi):
                                if user is sim:
                                    pass
                                blocking_obj = user
                                break
                if blocking_obj is None:
                    for blocking_obj in handler.get_targets():
                        break
                logger.info('Transition Reservation Failure, Obj: {}, Handler: {}', blocking_obj, handler)
                set_transition_failure_reason(sim, TransitionFailureReasons.RESERVATION, target_id=blocking_obj.id)
                if not test_only:
                    cancel_reservations()
                return reserve_result
            if not test_only:
                handler.reserve()
                reserve_object_handlers.add(handler)
            return reserve_result

        try:
            reserve_object_handlers = set()
            reservations_sis = []
            reservation_spec = self
            while reservation_spec is not None:
                if sim in reservation_spec._transition_interactions:
                    reservations_sis.extend(reservation_spec._transition_interactions[sim])
                reservation_spec = self._path_spec.get_next_transition_spec(reservation_spec)
                while reservation_spec is not None and reservation_spec.path is not None:
                    break
                    continue
            if is_failure_path and not reservations_sis:
                return False
            for (si, _) in reservations_sis:
                if si is None:
                    pass
                if si.get_liability(RESERVATION_LIABILITY) is not None:
                    pass
                basic_reserve = si.basic_reserve_object
                handler = None
                if is_failure_path and basic_reserve is None:
                    pass
                if basic_reserve is not None:
                    handlers = []
                    handler = basic_reserve(sim, si)
                    if is_failure_path:
                        reserve_result = add_reservation(handler, test_only=True)
                    else:
                        reserve_result = add_reservation(handler)
                    if not reserve_result:
                        if si.source == InteractionSource.BODY_CANCEL_AOP or si.source == InteractionSource.CARRY_CANCEL_AOP:
                            logger.warn('{} failed to pass reservation tests as a cancel AOP. Result: {}', si, reserve_result, owner='cgast')
                        if si.priority == Priority.Low:
                            return False
                        need_to_cancel = []
                        blocking_sims = set()
                        for obj in handler.get_targets():
                            obj_users = obj.get_users()
                            if not obj_users and obj.is_part:
                                obj = obj.part_owner
                                obj_users = obj.get_users()
                            for blocking_sim in obj_users:
                                if blocking_sim is sim:
                                    pass
                                if not blocking_sim.is_sim:
                                    return False
                                for blocking_si in blocking_sim.si_state:
                                    if not obj.is_same_object_or_part(blocking_si.target):
                                        pass
                                    if not blocking_si.can_shoo or blocking_si.priority >= si.priority:
                                        return False
                                    need_to_cancel.append(blocking_si)
                                    blocking_sims.add(blocking_sim)
                        if need_to_cancel:
                            for blocking_si in need_to_cancel:
                                blocking_si.cancel_user('Sim was kicked out by another Sim with a higher priority interaction.')
                            for blocking_sim in blocking_sims:
                                push_route_away(blocking_sim)
                            sim.queue.transition_controller.add_blocked_si(si)
                            sim.queue.transition_controller.derail(DerailReason.WAIT_FOR_BLOCKING_SIMS, sim)
                        return False
                    if is_failure_path:
                        return False
                    handlers.append(handler)
                    liability = ReservationLiability(handlers)
                    si.add_liability(RESERVATION_LIABILITY, liability)
                next_spec = self._path_spec.get_next_transition_spec(self)
                while next_spec is not None:
                    target_set = set()
                    target_set.add(next_spec.posture_spec.body_target)
                    target_set.add(next_spec.posture_spec.surface_target)
                    while True:
                        for target in target_set:
                            while not target is None:
                                if handler is not None and target in handler.get_targets():
                                    pass
                                target_handler = MultiReserveObjectHandler(sim, target, si)
                                while add_reservation(target_handler):
                                    self._additional_reservation_handlers.append(target_handler)
            if is_failure_path:
                return False
            if self.handle_slot_reservations:
                object_to_ignore = []
                for (transition_si, _) in self._transition_interactions[sim]:
                    while hasattr(transition_si, 'process'):
                        if transition_si.process is not None:
                            if transition_si.process.previous_ico is not None:
                                object_to_ignore.append(transition_si.process.previous_ico)
                            if transition_si.process.current_ico is not None:
                                object_to_ignore.append(transition_si.process.current_ico)
                cur_spec = self
                slot_manifest_entries = []
                while cur_spec is not None:
                    if cur_spec is not self and cur_spec.path is not None:
                        break
                    if cur_spec.handle_slot_reservations:
                        if PostureSpecVariable.SLOT in cur_spec.var_map:
                            slot_entry = cur_spec.var_map[PostureSpecVariable.SLOT]
                            slot_manifest_entries.append(slot_entry)
                            cur_spec.handle_slot_reservations = False
                        else:
                            logger.error('Trying to reserve a surface with no PostureSpecVariable.SLOT in the var_map.\n    Sim: {}\n    Spec: {}\n    Var_map: {}\n    Transition: {}', sim, cur_spec, cur_spec.var_map, cur_spec._path_spec.path)
                    cur_spec = self._path_spec.get_next_transition_spec(cur_spec)
                if slot_manifest_entries:
                    final_animation_context = self.final_si.animation_context
                    while True:
                        for slot_manifest_entry in slot_manifest_entries:
                            slot_result = final_animation_context.update_reserved_slots(slot_manifest_entry, sim, objects_to_ignore=object_to_ignore)
                            while not slot_result:
                                set_transition_failure_reason(sim, TransitionFailureReasons.RESERVATION, target_id=slot_result.obj.id if slot_result.obj is not None else None)
                                cancel_reservations()
                                return TestResult(False, 'Slot Reservation Failed for {}'.format(self.final_si))
            return TestResult.TRUE
        except:
            cancel_reservations()
            logger.exception('Exception reserving for transition: {}', self)
            raise

    def get_transition_route(self, sim, fade_out, dest_posture):
        if self.path is None:
            return
        fade_sim_out = fade_out or sim.is_hidden()
        reserve = True
        fire_service = services.get_fire_service()

        def route_callback(distance_left):
            nonlocal reserve, fade_sim_out
            if not self.is_failure_path and distance_left < FollowPath.DISTANCE_TO_RECHECK_STAND_RESERVATION and sim.on_slot is not None:
                transition_controller = sim.queue.transition_controller
                excluded_sims = transition_controller.get_transitioning_sims() if transition_controller is not None else ()
                violators = sim.get_stand_slot_reservation_violators(excluded_sims=excluded_sims)
                if violators:
                    if transition_controller is not None:
                        transition_controller.derail(DerailReason.WAIT_FOR_BLOCKING_SIMS, sim)
                    return FollowPath.Action.CANCEL
            if reserve and distance_left < FollowPath.DISTANCE_TO_RECHECK_INUSE:
                reserve = False
                if not self.do_reservation(sim, is_failure_path=self.is_failure_path):
                    return FollowPath.Action.CANCEL
            if not self.is_failure_path and fade_sim_out and distance_left < TransitionSpec.DISTANCE_TO_FADE_SIM_OUT:
                fade_sim_out = False
                dest_posture.sim.fade_out()
            time_now = services.time_service().sim_now
            if time_now > sim.next_passive_balloon_unlock_time:
                PassiveBalloons.request_passive_balloon(sim, time_now)
            if fire_service.check_for_catching_on_fire(sim):
                if sim.queue.running is not None:
                    sim.queue.running.route_fail_on_transition_fail = False
                return FollowPath.Action.CANCEL
            return FollowPath.Action.CONTINUE

        def should_fade_in():
            if not fade_sim_out:
                return self.path.length() > 0
            return False

        return build_element((maybe(should_fade_in, build_element(lambda _: dest_posture.sim.fade_in())), get_route_element_for_path(sim, self.path, callback_fn=route_callback, handle_failure=True)))

class PathSpec:
    __qualname__ = 'PathSpec'

    def __init__(self, path, path_cost, var_map, destination_spec, final_constraint, spec_constraint, path_as_posture_specs=True, is_failure_path=False, final_routing_transform=None, allow_tentative=False):
        if path is not None and path_as_posture_specs:
            self._path = []
            for posture_spec in path:
                self._path.append(TransitionSpec(self, posture_spec, var_map))
        else:
            self._path = path
            if self._path is not None:
                for transition_spec in self._path:
                    transition_spec._path_spec = self
        self.cost = path_cost
        self.destination_spec = destination_spec
        self.completed_path = False
        self._path_progress = 0
        self._is_failure_path = is_failure_path
        if not allow_tentative and final_constraint is not None and final_constraint.tentative:
            logger.warn("PathSpec's final constraint is tentative, this will not work correctly so the constraint will be ignored. This may interfere with slot reservation.", owner='jpollak')
            self._final_constraint = None
        else:
            self._final_constraint = final_constraint
        self._spec_constraint = spec_constraint
        self._final_si = None
        self.final_routing_transform = final_routing_transform

    def __repr__(self):
        if self._path:
            posture_specs = ['({})'.format(path.posture_spec) for path in self._path]
            return 'PathSpec[{}]'.format('->'.join(posture_specs))
        return 'PathSpec[Empty]'

    def __bool__(self):
        return bool(self._path)

    @property
    def path(self):
        if self._path is not None:
            return [transition_spec.posture_spec for transition_spec in self._path]
        return []

    @property
    def transition_specs(self):
        return self._path

    @property
    def path_progress(self):
        return self._path_progress

    @property
    def total_cost(self):
        routing_cost = 0
        if self._path is not None:
            for trans_spec in self._path:
                while trans_spec.path is not None:
                    routing_cost += trans_spec.path.length()
        return self.cost + routing_cost

    @property
    def var_map(self):
        if self._path is not None:
            return self._path[self._path_progress].var_map
        return [{}]

    @property
    def remaining_path(self):
        if self._path is not None and not self.completed_path:
            return [transition_spec.posture_spec for transition_spec in self._path[self._path_progress:]]
        return []

    @property
    def is_failure_path(self):
        return self._is_failure_path

    def set_as_failure_path(self):
        self._is_failure_path = True

    def remaining_original_transition_specs(self):
        original_transition_specs = []
        if self._path is not None and not self.completed_path:
            for spec in self._path[self._path_progress:]:
                while spec.sequence_id == SequenceId.DEFAULT:
                    original_transition_specs.append(spec)
        return original_transition_specs

    @property
    def previous_posture_spec(self):
        previous_progress = self._path_progress - 1
        if previous_progress < 0 or previous_progress >= len(self._path):
            return
        return self._path[previous_progress].posture_spec

    @property
    def num_remaining_transitions(self):
        return len(self._path) - self._path_progress

    @property
    def final_constraint(self):
        if self._final_constraint is not None:
            return self._final_constraint
        if self._path is None:
            return
        for transition_spec in reversed(self._path):
            while transition_spec.final_constraint is not None:
                return transition_spec.final_constraint

    @property
    def spec_constraint(self):
        return self._spec_constraint

    def advance_path(self):
        new_progress = self._path_progress + 1
        if new_progress < len(self._path):
            self._path_progress = new_progress
        else:
            self.completed_path = True

    def get_spec(self):
        return self._path[self._path_progress].posture_spec

    def get_transition_spec(self):
        return self._path[self._path_progress]

    def get_transition_should_reserve(self):
        for (i, transition_spec) in enumerate_reversed(self._path):
            while transition_spec.path is not None:
                return self._path_progress >= i
        return True

    def get_next_transition_spec(self, transition_spec):
        if self._path is None:
            return
        for (index, cur_transition_spec) in enumerate(self._path):
            while cur_transition_spec is transition_spec:
                next_index = index + 1
                if next_index < len(self._path):
                    return self._path[next_index]

    def insert_transition_specs_at_index(self, i, new_specs):
        self._path[i:i] = new_specs

    def combine(self, *path_specs):
        full_path = self._path
        cost = self.cost
        final_constraint = self.final_constraint
        spec_constraint = self.spec_constraint
        final_routing_transform = self.final_routing_transform
        is_failure_path = False
        for path_spec in path_specs:
            if not path_spec._path:
                raise AssertionError('Trying to combine two paths when one of them is None!')
            if full_path[-1].posture_spec != path_spec._path[0].posture_spec:
                raise AssertionError("Trying to combine two paths that don't have a common node on the ends {} != {}.\nThis may be caused by handles being generated for complete paths.".format(self.path[-1], path_spec.path[0]))
            if full_path[-1].mobile and path_spec._path[0].path is not None:
                full_path = list(itertools.chain(full_path, path_spec._path))
            else:
                if full_path[-1].locked_params:
                    path_spec._path[0].locked_params = full_path[-1].locked_params
                full_path = list(itertools.chain(full_path[:-1], path_spec._path))
            cost = cost + path_spec.cost
            final_constraint = path_spec.final_constraint
            spec_constraint = path_spec.spec_constraint
            final_routing_transform = path_spec.final_routing_transform
            is_failure_path = is_failure_path or path_spec.is_failure_path
        return PathSpec(full_path, cost, None, path_spec.destination_spec, final_constraint, spec_constraint, path_as_posture_specs=False, final_routing_transform=final_routing_transform, is_failure_path=is_failure_path)

    def edge_exists(self, spec_a_type, spec_b_type):
        for (cur_spec, next_spec) in zip(self.path, self.path[1:]):
            cur_spec_type = cur_spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX]
            next_spec_type = next_spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX]
            while cur_spec_type == spec_a_type and next_spec_type == spec_b_type:
                return True
        return False

    def get_failure_reason_and_object_id(self):
        if self._path is not None:
            for trans_spec in self._path:
                while trans_spec.path is not None and trans_spec.path.is_route_fail():
                    return (trans_spec.path.nodes.plan_failure_path_type, trans_spec.path.nodes.plan_failure_object_id)
        return (None, None)

    def create_route_node(self, path, final_constraint, portal=None):
        final_node = self._path[-1]
        if final_node.mobile:
            new_transition_spec = TransitionSpec(self, final_node.posture_spec, final_node.var_map, portal=portal)
            self._path.append(new_transition_spec)
            new_transition_spec.set_path(path, final_constraint)
        else:
            raise RuntimeError('PathSpec: Trying to turn a non-mobile node into a route: {}'.format(self._path))

    def attach_route_and_params(self, path, locked_params, final_constraint, reverse=False):
        if reverse:
            sequence = reversed(self._path)
        else:
            sequence = self._path
        previous_spec = None
        route_spec = None
        locked_param_spec = None
        for transition_spec in sequence:
            if not transition_spec.posture_spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].unconstrained:
                if route_spec is None:
                    route_spec = previous_spec if previous_spec is not None else transition_spec
                if reverse and previous_spec is not None:
                    locked_param_spec = previous_spec
                else:
                    locked_param_spec = transition_spec
                break
            if route_spec is None:
                if not reverse and transition_spec.posture_spec[BODY_INDEX][BODY_TARGET_INDEX] is not None:
                    route_spec = previous_spec if previous_spec is not None else transition_spec
                elif previous_spec is not None and previous_spec.posture_spec[CARRY_INDEX][CARRY_TARGET_INDEX] is not None != transition_spec.posture_spec[CARRY_INDEX][CARRY_TARGET_INDEX] is not None:
                    route_spec = previous_spec
            previous_spec = transition_spec
        if locked_param_spec is None:
            locked_param_spec = transition_spec
        if route_spec is None:
            route_spec = transition_spec
        route_spec.set_path(path, final_constraint)
        locked_param_spec.set_locked_params(locked_params)

    def adjust_route_for_sim_inventory(self):
        spec_to_destination = None
        spec_for_pick_up_route = None
        for transition_spec in reversed(self._path):
            while transition_spec.path is not None:
                if spec_to_destination is None:
                    spec_to_destination = transition_spec
                else:
                    spec_for_pick_up_route = transition_spec
                    break
        if spec_to_destination is not None and spec_for_pick_up_route is not None:
            spec_to_destination.transfer_route_to(spec_for_pick_up_route)

    def finalize(self, sim):
        if self.path is not None and len(self.path) > 0:
            final_destination = self.path[-1]
            final_var_map = self._path[-1].var_map
            interaction_target = final_var_map[PostureSpecVariable.INTERACTION_TARGET]
            if interaction_target is not None:
                for path_node in self._path:
                    if PostureSpecVariable.INTERACTION_TARGET not in path_node.var_map:
                        pass
                    for obj in final_destination.get_core_objects():
                        if obj.id != interaction_target.id:
                            pass
                        new_interaction_target = interaction_target.resolve_retarget(obj)
            carry_target = final_var_map[PostureSpecVariable.CARRY_TARGET]
            if carry_target is not None and carry_target.is_in_sim_inventory():
                self.adjust_route_for_sim_inventory()
            body_posture_target = sim.posture.target
            if body_posture_target is not None and sim.posture.mobile and self.path[0][BODY_INDEX][BODY_TARGET_INDEX] != body_posture_target:
                start_spec = sim.posture_state.get_posture_spec(self.var_map)
                self._path.insert(0, TransitionSpec(self, start_spec, self.var_map))

    def clean_path(self):
        start_spec = self._path[0].posture_spec if len(self._path) > 0 else None
        self.process_transitions(start_spec, self.remove_non_surface_to_surface_transitions)
        self.process_transitions(start_spec, self.remove_extra_mobile_transitions)
        if self._path[0].posture_spec == start_spec:
            self.process_transitions(start_spec, self.remove_origin_node)

    def process_transitions(self, start_spec, get_new_sequence_fn):
        new_transitions = []
        transitions_len = len(self._path)
        prev_transition = None
        for (i, transition) in enumerate(self._path):
            k = i + 1
            next_transition = None
            if k < transitions_len:
                next_transition = self._path[k]
            new_sequence = get_new_sequence_fn(i, prev_transition, transition, next_transition)
            if self.validate_new_sequence(prev_transition, new_sequence, next_transition, get_new_sequence_fn, start_spec):
                new_transitions.extend(new_sequence)
            else:
                new_transitions.append(transition)
            while len(new_transitions) >= 1:
                prev_transition = new_transitions[-1]
        self._path = new_transitions

    def validate_new_sequence(self, prev_transition, new_sequence, next_transition, get_new_sequence_fn, start_spec):
        validate = services.current_zone().posture_graph_service._can_transition_between_nodes
        if new_sequence:
            if prev_transition is None:
                if not validate(start_spec, new_sequence[0].posture_spec):
                    self.handle_validate_error_msg(start_spec, new_sequence[0].posture_spec, get_new_sequence_fn, start_spec)
                    return False
            elif not validate(prev_transition.posture_spec, new_sequence[0].posture_spec):
                self.handle_validate_error_msg(prev_transition.posture_spec, new_sequence[0].posture_spec, get_new_sequence_fn, start_spec)
                return False
            if len(new_sequence) > 1:
                for (curr_trans, next_trans) in zip(new_sequence[0:], new_sequence[1:]):
                    while not validate(curr_trans.posture_spec, next_trans.posture_spec):
                        self.handle_validate_error_msg(curr_trans.posture_spec, next_trans.posture_spec, get_new_sequence_fn, start_spec)
                        return False
            if next_transition and not validate(new_sequence[-1].posture_spec, next_transition.posture_spec):
                self.handle_validate_error_msg(new_sequence[-1].posture_spec or prev_transition.posture_spec, next_transition.posture_spec, get_new_sequence_fn, start_spec)
                return False
        else:
            if not (prev_transition is None and next_transition and validate(start_spec, next_transition.posture_spec)):
                self.handle_validate_error_msg(start_spec, next_transition.posture_spec, get_new_sequence_fn, start_spec)
                return False
            if prev_transition and next_transition and not validate(prev_transition.posture_spec, next_transition.posture_spec):
                self.handle_validate_error_msg(prev_transition.posture_spec, next_transition.posture_spec, get_new_sequence_fn, start_spec)
                return False
        return True

    def handle_validate_error_msg(self, posture_spec_a, posture_spec_b, mod_function, start_spec):
        logger.error('--- FAIL: validate_new_sequence({}) ---', mod_function.__name__)
        logger.error('Start Spec: {}', start_spec)
        logger.error('Full Path:')
        for (index, posture_spec) in enumerate(self.path):
            logger.error('    {}: {}', index, posture_spec)
        logger.error('Failure:', posture_spec_a, posture_spec_b)
        logger.error('    posture_spec_a: {}', posture_spec_a)
        logger.error('    posture_spec_b: {}', posture_spec_b)

    @staticmethod
    def remove_non_surface_to_surface_transitions(i, prev_transition_spec, transition_spec, next_transition_spec):
        prev_transition = prev_transition_spec.posture_spec if prev_transition_spec is not None else None
        transition = transition_spec.posture_spec
        next_transition = next_transition_spec.posture_spec if next_transition_spec is not None else None
        if next_transition is not None and ((prev_transition is None or prev_transition[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile) and (transition[SURFACE_INDEX][SURFACE_TARGET_INDEX] is None and next_transition[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile)) and next_transition[SURFACE_INDEX][SURFACE_TARGET_INDEX] is not None:
            if prev_transition is None or prev_transition[CARRY_INDEX] == next_transition[CARRY_INDEX] or next_transition is None:
                return ()
        return (transition_spec,)

    @staticmethod
    def remove_extra_mobile_transitions(i, prev_transition_spec, transition_spec, next_transition_spec):
        prev_transition = prev_transition_spec.posture_spec if prev_transition_spec is not None else None
        transition = transition_spec.posture_spec
        next_transition = next_transition_spec.posture_spec if next_transition_spec is not None else None
        if prev_transition is None or next_transition is None:
            return (transition_spec,)
        if prev_transition[CARRY_INDEX] == next_transition[CARRY_INDEX] and (prev_transition[SURFACE_INDEX] == next_transition[SURFACE_INDEX] and prev_transition[BODY_INDEX][BODY_TARGET_INDEX] == next_transition[BODY_INDEX][BODY_TARGET_INDEX]) and transition[BODY_INDEX][BODY_POSTURE_TYPE_INDEX] == next_transition[BODY_INDEX][BODY_POSTURE_TYPE_INDEX]:
            return ()
        if prev_transition[SURFACE_INDEX][SURFACE_TARGET_INDEX] != transition[SURFACE_INDEX][SURFACE_TARGET_INDEX] or transition[SURFACE_INDEX][SURFACE_TARGET_INDEX] != next_transition[SURFACE_INDEX][SURFACE_TARGET_INDEX]:
            return (transition_spec,)
        if prev_transition[CARRY_INDEX][CARRY_TARGET_INDEX] != transition[CARRY_INDEX][CARRY_TARGET_INDEX] or transition[CARRY_INDEX][CARRY_TARGET_INDEX] != next_transition[CARRY_INDEX][CARRY_TARGET_INDEX]:
            return (transition_spec,)
        if not prev_transition[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile and next_transition_spec.path is not None:
            return (transition_spec,)
        if prev_transition[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile and (transition[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile and next_transition[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile) and services.current_zone().posture_graph_service._can_transition_between_nodes(prev_transition, next_transition):
            return ()
        return (transition_spec,)

    @staticmethod
    def remove_origin_node(i, prev_transition_spec, transition_spec, next_transition_spec):
        transition = transition_spec.posture_spec
        next_transition = next_transition_spec.posture_spec if next_transition_spec is not None else None
        if i == 0 and next_transition is not None and not transition[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile:
            return ()
        return (transition_spec,)

    def flag_slot_reservations(self):
        for (prev_transition_spec, cur_transition_spec) in zip(self._path, self._path[1:]):
            if prev_transition_spec.sequence_id != cur_transition_spec.sequence_id:
                pass
            if not cur_transition_spec.posture_spec[SURFACE_INDEX][SURFACE_TARGET_INDEX]:
                pass
            if prev_transition_spec.is_carry and not cur_transition_spec.is_carry:
                prev_transition_spec.handle_slot_reservations = True
            else:
                while not prev_transition_spec.targets_empty_slot and cur_transition_spec.targets_empty_slot:
                    prev_transition_spec.handle_slot_reservations = True

    def generate_transition_interactions(self, sim, final_si, transition_success):
        if self._path is None:
            return True
        self._final_si = final_si
        transition_aops = OrderedDict()
        context = InteractionContext(sim, InteractionContext.SOURCE_POSTURE_GRAPH, final_si.priority, run_priority=final_si.run_priority, insert_strategy=QueueInsertStrategy.NEXT, must_run_next=True)
        preload_outfit_set = set()
        exit_change = sim.posture_state.body.saved_exit_clothing_change
        if exit_change is not None:
            preload_outfit_set.add(exit_change)
        for (i, cur_transition_spec) in enumerate(self._path[1:], start=1):
            cur_posture_spec = cur_transition_spec.posture_spec
            outfit_change = cur_transition_spec.posture_spec.body.posture_type.outfit_change
            if outfit_change:
                entry_change = outfit_change.get_on_entry_outfit(final_si)
                preload_outfit_set.add(entry_change)
            for prev_transition_spec in reversed(self._path[:i]):
                while prev_transition_spec.sequence_id == cur_transition_spec.sequence_id:
                    prev_posture_spec = prev_transition_spec.posture_spec
                    break
            prev_posture_spec = None
            aop_list = []
            var_map = cur_transition_spec.var_map
            edge_info = services.current_zone().posture_graph_service.get_edge(prev_posture_spec, cur_posture_spec, return_none_on_failure=True)
            aop = None
            if edge_info is not None:
                for operation in edge_info.operations:
                    op_aop = operation.associated_aop(sim, var_map)
                    while op_aop is not None:
                        aop = op_aop
            si = None
            if aop is not None:
                aop_list.append((aop, var_map))
            transition_aops[i] = aop_list
        added_final_si = False
        for (i, aops) in reversed(list(transition_aops.items())):
            for (aop, var_map) in aops:
                final_valid_combinables = final_si.get_combinable_interactions_with_safe_carryables()
                existing_si_set = {final_si} if not final_valid_combinables else set(itertools.chain((final_si,), final_valid_combinables))
                for existing_si in existing_si_set:
                    while not added_final_si and aop.is_equivalent_to_interaction(existing_si):
                        si = existing_si
                        if existing_si is final_si:
                            added_final_si = True
                        break
                execute_result = aop.interaction_factory(context)
                if not execute_result:
                    return False
                si = execute_result.interaction
                self._path[i].add_transition_interaction(sim, si, var_map)
                si.add_preload_outfit_changes(preload_outfit_set)
            while not aops:
                self._path[i].add_transition_interaction(sim, None, self._path[i].var_map)
        if not added_final_si and transition_success:
            self._path[-1].add_transition_interaction(sim, final_si, self._path[-1].var_map)
            final_si.add_preload_outfit_changes(preload_outfit_set)
        if not preload_outfit_set:
            current_position_on_active_lot = services.active_lot().is_position_on_lot(sim.position)
            if current_position_on_active_lot and not sim.is_outside:
                level = sim.routing_surface.secondary_id
                if not sim.intended_position_on_active_lot or build_buy.is_location_outside(sim.zone_id, sim.intended_position, level):
                    sim.preload_inappropriate_streetwear_change(final_si, preload_outfit_set)
        sim.preload_outfit_list = list(preload_outfit_set)
        return True

with reload.protected(globals()):
    EMPTY_PATH_SPEC = PathSpec(None, 0, {}, None, None, None)

class NodeData(namedtuple('NodeData', ('canonical_node', 'predecessors', 'successors'))):
    __qualname__ = 'NodeData'
    __slots__ = ()

    def __new__(cls, canonical_node, predecessors=(), successors=()):
        return super().__new__(cls, canonical_node, set(predecessors), set(successors))

class PostureGraph(dict):
    __qualname__ = 'PostureGraph'

    def __init__(self):
        self._subsets = defaultdict(set)
        self._quadtrees = defaultdict(sims4.geometry.QuadTree)

    @property
    def nodes(self):
        return self.keys()

    def get_canonical_node(self, node):
        node_data = self.get(node)
        if node_data is None:
            return node
        return node_data.canonical_node

    def remove_node(self, node):
        target = node.body_target or node.surface_target
        if target is not None and target != PostureSpecVariable.ANYTHING and target.routing_surface is not None:
            floor = target.routing_surface.secondary_id
            self._quadtrees[floor].remove(node)
        for key in self._get_subset_keys(node):
            self._subsets[key].remove(node)
            while not self._subsets[key]:
                del self._subsets[key]
        node_data = self[node]
        for successor in node_data.successors:
            self[successor].predecessors.remove(node)
        for predecessor in node_data.predecessors:
            self[predecessor].successors.remove(node)
        del self[node]

    def __missing__(self, node):
        self[node] = node_data = NodeData(node)
        target = node.body_target or node.surface_target
        if target is not None and target != PostureSpecVariable.ANYTHING and target.routing_surface is not None:
            self.add_to_quadtree(target, (node,))
        for key in self._get_subset_keys(node):
            self._subsets[key].add(node)
        return node_data

    def remove_from_quadtree(self, obj, nodes=None):
        if nodes is None:
            nodes = self.nodes_for_object_gen(obj)
        floor = obj.routing_surface.secondary_id
        quadtree = self._quadtrees[floor]
        for node in nodes:
            quadtree.remove(node)

    def add_to_quadtree(self, obj, nodes=None):
        if nodes is None:
            nodes = self.nodes_for_object_gen(obj)
        (lower_bound, upper_bound) = obj.footprint_polygon.bounds()
        bounding_box = sims4.geometry.QtRect(sims4.math.Vector2(lower_bound.x, lower_bound.z), sims4.math.Vector2(upper_bound.x, upper_bound.z))
        floor = obj.routing_surface.secondary_id
        quadtree = self._quadtrees[floor]
        for node in nodes:
            quadtree.insert(node, bounding_box)

    def add_successor(self, node, successor):
        node = self.get_canonical_node(node)
        successor = self.get_canonical_node(successor)
        self[node].successors.add(successor)
        self[successor].predecessors.add(node)

    def get_successors(self, node, default=DEFAULT):
        node_data = self.get(node)
        if node_data is not None:
            return node_data.successors
        if default is DEFAULT:
            raise KeyError('Node {} not in posture graph.'.format(node))
        return default

    def get_predecessors(self, node, default=DEFAULT):
        node_data = self.get(node)
        if node_data is not None:
            return node_data.predecessors
        if default is DEFAULT:
            raise KeyError('Node {} not in posture graph.'.format(node))
        return default

    @staticmethod
    def _get_subset_keys(node_or_spec):
        keys = set()
        posture_type = node_or_spec.body and node_or_spec.body.posture_type
        if posture_type is not None:
            keys.add(('posture_type', posture_type))
        carry_target = node_or_spec.carry_target
        keys.add(('carry_target', carry_target))
        body_target = node_or_spec.body_target
        body_target = getattr(body_target, 'part_owner', None) or body_target
        if node_or_spec.surface is not None:
            original_surface_target = node_or_spec.surface_target
            surface_target = getattr(original_surface_target, 'part_owner', None) or original_surface_target
            keys.add(('slot_target', node_or_spec.slot_target))
            slot_type = node_or_spec.slot_type
            if slot_type is not None and slot_type != PostureSpecVariable.SLOT:
                keys.add(('slot_type', slot_type))
            if surface_target == PostureSpecVariable.CONTAINER_TARGET:
                surface_target = node_or_spec.body_target
            if surface_target is None:
                if body_target is not None and not isinstance(body_target, PostureSpecVariable) and body_target.is_surface():
                    keys.add(('surface_target', body_target))
                    keys.add(('has_a_surface', True))
                else:
                    keys.add(('has_a_surface', False))
            elif surface_target not in (PostureSpecVariable.ANYTHING, PostureSpecVariable.SURFACE_TARGET):
                keys.add(('surface_target', surface_target))
                keys.add(('has_a_surface', True))
            elif surface_target == PostureSpecVariable.SURFACE_TARGET:
                keys.add(('has_a_surface', True))
            while True:
                for slot_type in original_surface_target.get_provided_slot_types():
                    keys.add(('slot_type', slot_type))
        else:
            surface_target = None
        if node_or_spec.body is not None:
            if body_target != PostureSpecVariable.ANYTHING:
                keys.add(('body_target', body_target))
            elif surface_target is None and posture_type.mobile:
                keys.add(('body_target', None))
        if ('body_target', None) in keys and ('slot_target', None) in keys:
            keys.add(('body_target and slot_target', None))
        return keys

    def nodes_matching_constraint_geometry(self, constraint):
        if any(sub_constraint.routing_surface is None or sub_constraint.geometry is None for sub_constraint in constraint):
            return
        nodes = set()
        for sub_constraint in constraint:
            floor = sub_constraint.routing_surface.secondary_id
            quadtree = self._quadtrees[floor]
            for polygon in sub_constraint.geometry.polygon:
                (lower_bound, upper_bound) = polygon.bounds()
                bounding_box = sims4.geometry.QtRect(sims4.math.Vector2(lower_bound.x, lower_bound.z), sims4.math.Vector2(upper_bound.x, upper_bound.z))
                nodes.update(quadtree.query(bounding_box))
        nodes |= self._subsets[('body_target and slot_target', None)]
        return nodes

    def nodes_for_object_gen(self, obj):
        if obj.is_part:
            owner = obj.part_owner
            nodes = self._subsets.get(('body_target', owner), set()) | self._subsets.get(('surface_target', owner), set())
            for node in nodes:
                while node.body_target is obj or node.surface_target is obj:
                    yield node
        else:
            nodes = self._subsets.get(('body_target', obj), set()) | self._subsets.get(('surface_target', obj), set())
            yield nodes

    def get_matching_nodes_iter(self, specs, slot_types, constraint=None):
        nodes = set()
        for spec in specs:
            if slot_types:
                spec_nodes = set()
                for slot_type in slot_types:
                    surface = PostureAspectSurface((spec.surface.target, slot_type, spec.surface.slot_target))
                    slot_type_spec = spec.clone(surface=surface)
                    keys = self._get_subset_keys(slot_type_spec)
                    if not keys:
                        raise AssertionError('No keys returned for a specific slot type!')
                    subsets = {key: self._subsets[key] for key in keys}
                    intersection = functools.reduce(operator.and_, sorted(subsets.values(), key=len))
                    spec_nodes.update(intersection)
            else:
                keys = self._get_subset_keys(spec)
                if not keys:
                    return iter(self.nodes)
                subsets = {key: self._subsets[key] for key in keys}
                spec_nodes = set(functools.reduce(operator.and_, sorted(subsets.values(), key=len)))
            target = spec.body_target or spec.surface_target
            if target in (None, PostureSpecVariable.ANYTHING) and constraint:
                quadtree_subset = self.nodes_matching_constraint_geometry(constraint)
                if quadtree_subset is not None:
                    spec_nodes &= quadtree_subset
            nodes.update(spec_nodes)
        return iter(nodes)

    def clear(self):
        super().clear()
        self._subsets.clear()
        self._quadtrees.clear()

    def __bool__(self):
        if self.nodes:
            return True
        return False

    def _check_graph(self):
        for node in self:
            for successor in self.get_successors(node):
                while node not in self.get_predecessors(successor):
                    raise AssertionError('Edge {} -> {} not stored consistently.'.format(node, successor))
            for predecessor in self.get_predecessors(node):
                while node not in self.get_successors(predecessor):
                    raise AssertionError('Edge {} -> {} not stored consistently.'.format(predecessor, node))
        d = defaultdict(set)

        def mark_instance(node):
            d[node].add(id(node))

        for node in self:
            mark_instance(node)
            mark_instance(self.get_canonical_node(node))
            for successor in self.get_successors(node):
                mark_instance(successor)
            for predecessor in self.get_predecessors(node):
                mark_instance(predecessor)
        for (node, ids) in d.items():
            while len(ids) > 1:
                raise AssertionError('Node {} has multiple instances stored in the graph.'.format(node))

class EdgeInfo(namedtuple('_EdgeInfo', ['operations', 'validate', 'cost'])):
    __qualname__ = 'EdgeInfo'
    __slots__ = ()

class PostureGraphService(Service):
    __qualname__ = 'PostureGraphService'
    SIM_DEFAULT_AFFORDANCE = TunableReference(description='\n        The default interaction to push onto the Sim when it is starting up.\n        ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION))
    POSTURE_PROVIDING_AFFORDANCES = TunableList(description='\n        Additional posture providing interactions that are not tuned on any\n        object. This allows us to add additional postures for sims to use.\n        Example: Kneel on floor.\n        ', tunable=TunableReference(description='\n            Interaction that provides a posture.\n            ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)))
    INCREMENTAL_REBUILD_THRESHOLD = Tunable(description='\n        The posture graph will do a full rebuild when exiting build/buy if\n        there have been more than this number of modifications to the posture\n        graph. Otherwise, an incremental rebuild will be done, which is much\n        faster for small numbers of operations, but slower for large numbers.\n        Talk to a gameplay engineer before changing this value.\n        ', tunable_type=int, default=10)
    WALL_OBJECT_FORWARD_MOD = 0.1

    def __init__(self):
        self._graph = PostureGraph()
        self._edge_info = {}
        self._goal_costs = {}
        self._zone_loaded = False
        self._disable_graph_update_count = 0
        self._incremental_update_count = None

    def _clear(self):
        self._graph.clear()
        self._edge_info.clear()

    def rebuild(self):
        if self._disable_graph_update_count == 0:
            self._clear()
            self.build()

    def disable_graph_building(self):
        pass

    def enable_graph_building(self):
        pass

    def remove_from_quadtree(self, obj):
        self._graph.remove_from_quadtree(obj)

    def add_to_quadtree(self, obj):
        self._graph.add_to_quadtree(obj)

    def on_enter_buildbuy(self):
        self._incremental_update_count = 0

    def on_exit_buildbuy(self):
        if self._incremental_update_count is None:
            logger.warn('Posture graph incremental update count is None when exiting build/buy. This can only happen if there is a mismatch between calls to on_enter_buildbuy() and on_exit_buildbuy(). The posture graph will be rebuilt just to be cautious.', owner='bhill')
            self.rebuild()
        elif self._incremental_update_count > self.INCREMENTAL_REBUILD_THRESHOLD:
            self.rebuild()
        self._incremental_update_count = None

    def start(self):
        self._clear()
        if SIM_DEFAULT_AOP is None:
            _cache_global_sim_default_values()
        self.build()

    @contextmanager
    def __reload_context__(oldobj, newobj):
        try:
            yield None
        finally:
            if isinstance(oldobj, PostureGraphService):
                _cache_global_sim_default_values()

    def stop(self):
        if not self._zone_loaded:
            return
        object_manager = services.object_manager()
        object_manager.unregister_callback(CallbackTypes.ON_OBJECT_ADD, self._on_object_added)
        object_manager.unregister_callback(CallbackTypes.ON_OBJECT_REMOVE, self._on_object_deleted)

    def build_during_zone_spin_up(self):
        self._zone_loaded = True
        self.rebuild()
        object_manager = services.object_manager()
        object_manager.register_callback(CallbackTypes.ON_OBJECT_ADD, self._on_object_added)
        object_manager.register_callback(CallbackTypes.ON_OBJECT_REMOVE, self._on_object_deleted)

    @staticmethod
    def _process_node_operations(node, operations):
        validate = CallableTestList()
        cost = 0
        next_node = node
        for operation in operations:
            validate.append(functools.partial(operation.validate, next_node))
            cost += operation.cost(next_node)
            next_node = operation.apply(next_node)
            while next_node is None:
                return (None, None)
        if not PostureGraphService._validate_node_for_graph(next_node):
            return (None, None)
        edge_info = EdgeInfo(operations, validate, cost)
        return (next_node, edge_info)

    def add_node(self, node, operations):
        (next_node, edge_info) = self._process_node_operations(node, operations)
        if next_node is None or next_node in self._graph.get_successors(node, ()):
            return
        self._graph.add_successor(node, next_node)
        self._edge_info[(node, next_node)] = edge_info
        return next_node

    @with_caches
    def _on_object_added(self, new_obj):
        if not new_obj.is_valid_posture_graph_object or self._disable_graph_update_count:
            return
        if new_obj.is_part:
            return
        if self._incremental_update_count is not None:
            if self._incremental_update_count > self.INCREMENTAL_REBUILD_THRESHOLD:
                return
        objects = set()

        def add_object_to_build(obj_to_add):
            if obj_to_add.parts:
                objects.update(obj_to_add.parts)
            else:
                objects.add(obj_to_add)

        add_object_to_build(new_obj)
        for child in new_obj.children:
            while child.is_valid_posture_graph_object:
                add_object_to_build(child)
        open_set = set()
        closed_set = set(self._graph.nodes)
        all_ancestors = set().union(*(obj.ancestry_gen() for obj in objects))
        for ancestor in all_ancestors:
            while not ancestor.parts:
                open_set.update(self._graph.nodes_for_object_gen(ancestor))
        closed_set -= open_set
        for (node, obj) in itertools.product(STAND_AT_NONE_NODES, objects):
            for operations in self._expand_node_object(node, obj):
                new_node = self.add_node(node, operations)
                while new_node is not None and new_node not in closed_set:
                    open_set.add(new_node)
        self._build(open_set, closed_set)

    @with_caches
    def _on_object_deleted(self, obj):
        if not obj.is_valid_posture_graph_object or self._disable_graph_update_count:
            return
        if self._incremental_update_count is not None:
            if self._incremental_update_count > self.INCREMENTAL_REBUILD_THRESHOLD:
                return
        for node in self._graph.nodes_for_object_gen(obj):
            self._graph.remove_node(node)

    @contextmanager
    @with_caches
    def object_moving(self, obj):
        if not self._zone_loaded:
            yield None
            return
        if not obj.is_valid_posture_graph_object:
            yield None
            return
        self._on_object_deleted(obj)
        try:
            yield None
        finally:
            self._on_object_added(obj)

    def _expand_node(self, node):
        for obj in node.get_relevant_objects():
            if not obj.is_valid_posture_graph_object:
                pass
            yield self._expand_node_object(node, obj)
        yield (SIM_DEFAULT_OPERATION,)
        if node[SURFACE_INDEX] is not None:
            yield (PostureOperation.FORGET_SURFACE_OP, SIM_DEFAULT_OPERATION)
            if node[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile:
                yield (PostureOperation.FORGET_SURFACE_OP,)
        if node[BODY_INDEX][BODY_POSTURE_TYPE_INDEX]._supports_carry:
            yield (PostureOperation.STANDARD_PICK_UP_OP,)

    @caches.cached_generator(maxsize=None)
    def _expand_object_surface(self, obj, surface):
        if surface is not None:
            put_down = PostureOperation.PutDownObjectOnSurface(PostureSpecVariable.POSTURE_TYPE_CARRY_NOTHING, surface, PostureSpecVariable.SLOT, PostureSpecVariable.CARRY_TARGET)
            yield (put_down,)
            surface_ops = tuple(self._expand_surface(surface))
            yield surface_ops
        posture_aops = obj.posture_interaction_gen()
        if obj.is_part:
            posture_aops = filter(obj.part_definition.supported_affordance, posture_aops)
        for aop in posture_aops:
            body_operation = aop.get_provided_posture_change()
            if body_operation is None:
                pass
            while not obj.parts or body_operation.posture_type.unconstrained:
                yield (body_operation,)
                if surface is not None:
                    yield ((body_operation,) + ops for ops in surface_ops)
        if obj.inventory_component is not None:
            at_surface = PostureOperation.TargetAlreadyInSlot(None, obj, None)
            yield (at_surface,)

    def _expand_node_object(self, node, obj):
        if obj.is_surface():
            surface = obj
        elif obj.parent is not None and obj.parent.is_surface():
            surface = obj.parent
        else:
            surface = None
        yield self._expand_object_surface(obj, surface)
        if surface is not obj:
            return
        if node.body_target not in (None, obj):
            return
        if obj.is_part and not obj.supports_posture_type(SIM_DEFAULT_POSTURE_TYPE):
            return
        body_operation = PostureOperation.BodyTransition(SIM_DEFAULT_POSTURE_TYPE, AffordanceObjectPair(self.SIM_DEFAULT_AFFORDANCE, obj, self.SIM_DEFAULT_AFFORDANCE, None))
        yield (body_operation,)

    def _expand_surface(self, surface):
        existing_slotted_target = PostureOperation.TargetAlreadyInSlot(PostureSpecVariable.CARRY_TARGET, surface, PostureSpecVariable.SLOT)
        yield (existing_slotted_target,)
        empty_surface = PostureOperation.TargetAlreadyInSlot(None, surface, PostureSpecVariable.SLOT)
        yield (empty_surface,)
        at_surface = PostureOperation.TargetAlreadyInSlot(None, surface, None)
        yield (at_surface,)

    @staticmethod
    def _validate_node_for_graph(node):
        surface = node[SURFACE_INDEX]
        target = node[BODY_INDEX][BODY_TARGET_INDEX]
        if not ((surface is None or surface[SURFACE_TARGET_INDEX] is None) and target is not None and node[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile):
            if target.parent is not None and not target.is_set_as_head:
                return False
        return True

    def _build(self, open_set, closed_set):
        while open_set:
            node = open_set.pop()
            closed_set.add(node)
            for operations in self._expand_node(node):
                new_node = self.add_node(node, operations)
                while new_node is not None and new_node not in closed_set:
                    open_set.add(new_node)
        caches.clear_all_caches()

    @with_caches
    def build(self):
        open_set = set(STAND_AT_NONE_NODES)
        closed_set = set()
        self._edge_info[(STAND_AT_NONE, STAND_AT_NONE)] = EdgeInfo((SIM_DEFAULT_OPERATION,), lambda *_, **__: True, 0)
        for affordance in self.POSTURE_PROVIDING_AFFORDANCES:
            aop = AffordanceObjectPair(affordance, None, affordance, None)
            body_operation = aop.get_provided_posture_change()
            open_set.add(self.add_node(STAND_AT_NONE, (body_operation,)))
            open_set.add(self.add_node(STAND_AT_NONE_CARRY, (body_operation,)))
        self._build(open_set, closed_set)

    def contains_node(self, node):
        return node in self._graph.nodes

    def nodes_matching_constraint_geometry(self, constraint):
        return self._graph.nodes_matching_constraint_geometry(constraint)

    def distance_fn(self, sim, var_map, curr_node, next_node):
        if isinstance(curr_node, _MobileNode):
            curr_node = curr_node.graph_node
        if isinstance(next_node, _MobileNode):
            next_node = next_node.graph_node
        if curr_node == next_node:
            return 0
        cost = 0
        next_body = next_node[BODY_INDEX]
        next_body_target = next_body[BODY_TARGET_INDEX]
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            cost_str_list = []
        if next_body_target is not None and not next_body_target.may_reserve(sim):
            cost += PostureScoring.OBJECT_RESERVED_PENALTY
            if gsi_handlers.posture_graph_handlers.archiver.enabled:
                cost_str_list.append('NO_CONNECTION_PENALTY: {}'.format(PostureScoring.OBJECT_RESERVED_PENALTY))
        edge_info = self._edge_info[(curr_node, next_node)]
        cost += edge_info.cost
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            for operation in edge_info.operations:
                cost_str_list.append('OpCost({}): {}'.format(type(operation).__name__, edge_info.cost))
                operation_cost_str_list = operation.debug_cost_str_list
                while operation_cost_str_list is not None:
                    while True:
                        for operation_cost_str in operation_cost_str_list:
                            cost_str_list.append('\t' + operation_cost_str)
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            cost_str_list.insert(0, 'Score: {}'.format(cost))
            logger.debug('Score: {}, curr_node: {}, next_node: {}', cost, curr_node, next_node)
            gsi_handlers.posture_graph_handlers.log_path_cost(sim, curr_node, next_node, cost_str_list)
        return cost

    def _adjacent_nodes_gen(self, sim, get_successors_fn, valid_edge_test, var_map, node, *, allow_pickups, allow_putdowns, reverse_path):
        if isinstance(node, _MobileNode):
            node = node.graph_node
        if node in STAND_AT_NONE_NODES:
            return
        for successor in get_successors_fn(node):
            forward_nodes = (successor, node) if reverse_path else (node, successor)
            (first, second) = forward_nodes
            if allow_pickups or first.carry_target is None and second.carry_target is not None:
                pass
            if allow_putdowns or first.carry_target is not None and second.carry_target is None:
                pass
            if not (valid_edge_test is not None and valid_edge_test(*forward_nodes)):
                pass
            edge_info = self._edge_info[forward_nodes]
            if not edge_info.validate(sim, var_map):
                pass
            if successor in STAND_AT_NONE_NODES:
                yield _MobileNode(successor, node)
            else:
                yield successor

    def _left_path_gen(self, sim, source, destinations, interaction, constraint, var_map, valid_edge_test, is_complete):
        if is_complete:
            if source[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile and source[SURFACE_INDEX][SURFACE_TARGET_INDEX] is None:
                return
            search_destinations = set(destinations) - set(STAND_AT_NONE_NODES)
            return
        else:
            search_destinations = STAND_AT_NONE_NODES
        distance_fn = functools.partial(self.distance_fn, sim, var_map)
        allow_pickups = False
        if is_complete:
            carry_target = var_map.get(PostureSpecVariable.CARRY_TARGET)
            if carry_target is not None and carry_target.definition is not carry_target:
                if carry_target.is_in_sim_inventory(sim=sim):
                    allow_pickups = True
                elif carry_target.parent is not None and (carry_target.parent.is_same_object_or_part(sim.posture_state.surface_target) or carry_target.parent.is_same_object_or_part(sim)):
                    allow_pickups = True
                elif carry_target.routing_surface is not None:
                    sim_constraint = interactions.constraints.Transform(sim.intended_transform, routing_surface=sim.intended_routing_surface)
                    carry_constraint = CarryingObject.get_carry_transition_position_constraint(carry_target.position, carry_target.routing_surface, mobile=False)
                    if sim_constraint.intersect(carry_constraint).valid and sim.los_constraint.geometry.contains_point(carry_target.position):
                        allow_pickups = True
        allow_putdowns = allow_pickups
        adjacent_nodes_gen = functools.partial(self._adjacent_nodes_gen, sim, self._graph.get_successors, valid_edge_test, var_map, reverse_path=False, allow_pickups=allow_pickups, allow_putdowns=allow_putdowns)

        def left_distance_fn(curr_node, next_node):
            if isinstance(curr_node, _MobileNode):
                curr_node = curr_node.graph_node
            if isinstance(next_node, _MobileNode):
                next_node = next_node.graph_node
            if next_node is None:
                if curr_node in destinations:
                    return self._get_goal_cost(sim, interaction, constraint, var_map, curr_node)
                return 0.0
            return distance_fn(curr_node, next_node)

        paths = _shortest_path_gen((source,), search_destinations, adjacent_nodes_gen, left_distance_fn)
        for path in paths:
            path = algos.Path(list(path), path.cost - left_distance_fn(path[-1], None))
            yield path

    def clear_goal_costs(self):
        self._get_goal_cost.cache.clear()

    @caches.cached
    def _get_goal_cost(self, sim, interaction, constraint, var_map, dest):
        cost = self._goal_costs.get(dest, 0.0)
        node_target = dest.body_target
        if node_target is not None:
            cost += constraint.get_routing_cost(node_target.position, node_target.orientation)
        if not any(c.cost for c in constraint):
            return cost
        participant_type = interaction.get_participant_type(sim)
        animation_resolver_fn = interaction.get_constraint_resolver(None)
        (_, routing_data) = self.get_locations_from_posture(sim, dest, var_map, interaction=interaction, participant_type=participant_type, animation_resolver_fn=animation_resolver_fn, final_constraint=constraint)
        final_constraint = routing_data[0]
        if final_constraint is None:
            final_constraint = constraint
        if not final_constraint.valid:
            return sims4.math.MAX_FLOAT
        cost += final_constraint.cost
        return cost

    def _right_path_gen(self, sim, interaction, distance_estimator, left_destinations, destinations, var_map, constraint, valid_edge_test):
        adjacent_nodes_gen = functools.partial(self._adjacent_nodes_gen, sim, self._graph.get_predecessors, valid_edge_test, var_map, reverse_path=True, allow_pickups=False, allow_putdowns=True)

        def reversed_distance_fn(curr_node, next_node):
            if next_node is None:
                return 0.0
            return self.distance_fn(sim, var_map, next_node, curr_node)

        weighted_sources = {dest: self._get_goal_cost(sim, interaction, constraint, var_map, dest) for dest in destinations}

        def heuristic_fn(node):
            if isinstance(node, _MobileNode):
                node = node.prev
            distances = []
            if node.body_target is not None:
                distances.append(distance_estimator.estimate_object_distance(node.body_target))
            if node.surface_target is not None:
                distances.append(distance_estimator.estimate_object_distance(node.surface_target))
            if not distances:
                for sub_constraint in constraint:
                    while sub_constraint.average_position is not None and sub_constraint.routing_surface is not None:
                        avg_position = sub_constraint.average_position
                        distance = primitives.routing_utils.estimate_distance_between_points(sim.position, sim.routing_surface, avg_position, sub_constraint.routing_surface, sim.routing_context)
                        if distance is not None:
                            area = sub_constraint.geometry.polygon.area()
                            radius = sims4.math.sqrt(area/sims4.math.PI)
                            distance -= radius
                            distance = max(0, distance)
                        distance = sims4.math.MAX_FLOAT if distance is None else distance
                        distances.append(distance)
            if not distances:
                distances.append(distance_estimator.estimate_object_distance(None))
            if distances:
                return min(distances)
            return 0.0

        paths_reversed = _shortest_path_gen(weighted_sources, set(left_destinations), adjacent_nodes_gen, reversed_distance_fn, heuristic_fn)
        for path in paths_reversed:
            path = algos.Path(reversed(path), path.cost)
            yield path

    def _middle_path_gen(self, path_left, path_right, sim, interaction, distance_estimator, var_map):
        left_destinations = {path_left[-1]}
        right_sources = {path_right[0]}
        pickup_cost = PostureOperation.PickUpObject.get_pickup_cost(path_left[-1])
        middleless_left_dests = left_destinations - right_sources
        if not middleless_left_dests:
            yield None
            return
        carry_target = var_map[PostureSpecVariable.CARRY_TARGET]
        if carry_target is None:
            raise ValueError('Interaction requires a carried object in its animation but has no carry_target: {} {}', interaction, var_map)
        if isinstance(carry_target, Definition):
            return
        parent_slot = carry_target.parent_slot
        if parent_slot is not None and parent_slot.owner != sim:
            if parent_slot.owner.is_sim:
                return []
            surface_target = parent_slot.owner
            if not surface_target.is_surface():
                raise ValueError('Cannot pick up an object: {} from an invalid surface: {}'.format(carry_target, surface_target))
            pickup_path = self.get_pickup_path(surface_target, interaction)
            yield pickup_path
            return
        carry_target_inventory = carry_target.get_inventory()
        if carry_target_inventory is None or carry_target.is_in_sim_inventory():
            yield algos.Path([STAND_AT_NONE, STAND_AT_NONE_CARRY], pickup_cost)
            return
        if interaction is not None:
            obj_with_inventory = interaction.object_with_inventory
            if obj_with_inventory is not None:
                pickup_path = self.get_pickup_path(obj_with_inventory, interaction)
                yield pickup_path
                return
        inv_objects = list(carry_target_inventory.owning_objects_gen())
        if not inv_objects:
            logger.warn('Attempt to plan a middle path for an inventory with no owning objects: {} on interaction: {}', carry_target_inventory, interaction, owner='bhill')
            yield None
            return
        for node in path_right:
            while node.body_target or node.surface_target:
                right_target = node.body_target or node.surface_target
                break
        right_target = None

        def inv_owner_dist(owner):
            dist = distance_estimator.estimate_distance((sim, owner))
            dist += distance_estimator.get_preferred_object_cost(owner)
            if right_target:
                dist += distance_estimator.estimate_distance((owner, right_target))
            return dist

        inv_objects.sort(key=inv_owner_dist)
        for inv_object in inv_objects:
            pickup_path = self.get_pickup_path(inv_object, interaction)
            yield pickup_path

    def _get_all_paths(self, sim, source, destinations, var_map, constraint, valid_edge_test, interaction=None, allow_complete=True):
        distance_estimator = DistanceEstimator(self, sim, interaction, constraint)
        incomplete = SegmentedPath(self, sim, source, destinations, var_map, constraint, valid_edge_test, interaction, is_complete=False, distance_estimator=distance_estimator)
        if allow_complete:
            complete = SegmentedPath(self, sim, source, destinations, var_map, constraint, valid_edge_test, interaction, is_complete=True, distance_estimator=distance_estimator)
        else:
            complete = None
        return (incomplete, complete)

    def get_pickup_path(self, surface_target, interaction):
        cost_pickup = 0
        path_pickup = [STAND_AT_NONE]
        sequence_pickup = get_pick_up_spec_sequence(STAND_AT_NONE, surface_target)
        path_pickup.extend(sequence_pickup)
        path_pickup.append(STAND_AT_NONE_CARRY)
        if interaction is not None:
            preferred_objects = interaction.preferred_objects
            cost_pickup += postures.posture_scoring.PostureScoring.get_preferred_object_cost((surface_target,), preferred_objects)
        return algos.Path(path_pickup, cost_pickup)

    def any_template_passes_destination_test(self, templates, si, sim, node):
        for (dest_spec, var_map, _) in [(ds, vm, c) for (c, value) in templates.items() for (ds, vm) in value]:
            while postures.posture_specs.destination_test(sim, node, (dest_spec,), var_map, None, si.affordance):
                return True
        return False

    def get_segmented_paths(self, sim, posture_dest_list, additional_template_list, interaction, participant_type, valid_destination_test, valid_edge_test, preferences, final_constraint, included_sis):
        possible_destinations = []
        all_segmented_paths = []
        self._goal_costs.clear()
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            gsi_templates = [(ds, vm, c) for (c, value) in posture_dest_list.items() for (ds, vm) in value]
            gsi_handlers.posture_graph_handlers.add_templates_to_gsi(sim, gsi_templates)
        guaranteed_sis = list(sim.si_state.all_guaranteed_si_gen(interaction.priority, interaction.group_id))
        interaction_sims = set(interaction.get_participants(ParticipantType.AllSims))
        interaction_sims.discard(interaction.sim)
        relationship_bonuses = PostureScoring.build_relationship_bonuses(sim, interaction.sim_affinity_posture_scoring_data, sims_to_consider=interaction_sims)
        main_group = sim.get_main_group()
        if main_group is not None and main_group.constraint_initialized and not main_group.is_solo:
            group_constraint = main_group.get_constraint(sim)
        else:
            group_constraint = None
        found_destination_node = False
        for (constraint, templates) in posture_dest_list.items():
            destination_nodes = {}
            var_map_all = DEFAULT
            destination_specs = set()
            slot_types = set()
            for (destination_spec, var_map) in templates:
                destination_specs.add(destination_spec)
                slot = var_map.get(PostureSpecVariable.SLOT)
                if slot is not None:
                    slot_types.update(slot.slot_types)
                if var_map_all is DEFAULT:
                    var_map_all = var_map
                while gsi_handlers.posture_graph_handlers.archiver.enabled:
                    possible_destinations.append(destination_spec)
            slot_all = var_map_all.get(PostureSpecVariable.SLOT)
            if slot_all is not None:
                new_slot_manifest = slot_all.with_overrides(slot=frozenset(slot_types))
                var_map_all = frozendict(var_map_all, {PostureSpecVariable.SLOT: new_slot_manifest})
            source_spec = sim.posture_state.get_posture_spec(var_map_all)
            if source_spec is None:
                pass
            if source_spec.body_posture.mobile and source_spec.body_target is not None:
                new_body = PostureAspectBody((source_spec.body_posture, None))
                new_surface = PostureAspectSurface((None, None, None))
                source_spec = source_spec.clone(body=new_body, surface=new_surface)
            possible_source_nodes = self._graph.get_matching_nodes_iter((source_spec,), None)
            for node in possible_source_nodes:
                if not node_matches_spec(node, source_spec, var_map_all, False):
                    pass
                if gsi_handlers.posture_graph_handlers.archiver.enabled:
                    gsi_handlers.posture_graph_handlers.add_source_or_dest(sim, destination_spec, var_map_all, 'source', node)
                source_node = node
                break
            raise AssertionError('No source node found for source_spec: {}'.format(source_spec))
            for node in self._graph.get_matching_nodes_iter(destination_specs, slot_types, constraint=final_constraint):
                excluded_objects = interaction.excluded_posture_destination_objects()
                if node.body_target is not None and node.body_target in excluded_objects:
                    pass
                if not destination_test(sim, node, destination_specs, var_map_all, valid_destination_test, interaction.affordance):
                    pass
                if additional_template_list and not interaction.is_putdown:
                    compatible = True
                    for (carry_si, additional_templates) in additional_template_list.items():
                        if carry_si not in guaranteed_sis:
                            pass
                        compatible = self.any_template_passes_destination_test(additional_templates, carry_si, sim, node)
                        while compatible:
                            break
                    if not compatible:
                        pass
                if gsi_handlers.posture_graph_handlers.archiver.enabled:
                    gsi_handlers.posture_graph_handlers.add_source_or_dest(sim, destination_spec, var_map_all, 'destination', node)
                destination_nodes[node] = destination_specs
            if destination_nodes:
                found_destination_node = True
            else:
                logger.debug('No destination_nodes found for destination_specs: {}', destination_specs)
            PostureScoring.build_destination_costs(self._goal_costs, destination_nodes, sim, interaction, var_map_all, preferences, included_sis, additional_template_list, relationship_bonuses, constraint, group_constraint)
            allow_complete = True
            interaction_outfit_changes = interaction.get_tuned_outfit_changes(include_exit_changes=False)
            if interaction_outfit_changes:
                for outfit_change_reason in interaction_outfit_changes:
                    while not sim.sim_info.sim_outfits.is_wearing_outfit(outfit_change_reason):
                        allow_complete = False
            if allow_complete:
                for dest_node in destination_nodes:
                    outfit_change = dest_node.body.posture_type.outfit_change
                    while outfit_change:
                        entry_change_outfit = outfit_change.get_on_entry_outfit(interaction, sim=sim)
                        if entry_change_outfit is not None and not sim.sim_info.sim_outfits.is_wearing_outfit(entry_change_outfit):
                            allow_complete = False
                            break
            (incomplete, complete) = self._get_all_paths(sim, source_node, destination_nodes, var_map_all, constraint, valid_edge_test, interaction=interaction, allow_complete=allow_complete)
            if incomplete is not None:
                all_segmented_paths.append(incomplete)
            while complete is not None:
                all_segmented_paths.append(complete)
        if self._goal_costs:
            lowest_goal_cost = min(self._goal_costs.values())
            for (goal_node, cost) in self._goal_costs.items():
                self._goal_costs[goal_node] = cost - lowest_goal_cost
        if not all_segmented_paths:
            if not found_destination_node:
                set_transition_failure_reason(sim, TransitionFailureReasons.NO_DESTINATION_NODE, transition_controller=interaction.transition)
            else:
                set_transition_failure_reason(sim, TransitionFailureReasons.NO_PATH_FOUND, transition_controller=interaction.transition)
        return all_segmented_paths

    def handle_additional_pickups_and_putdowns(self, best_path_spec, additional_template_list, sim):
        included_sis = set()
        if not best_path_spec.transition_specs or not additional_template_list:
            return included_sis
        best_transition_specs = best_path_spec.transition_specs
        final_transition_spec = best_transition_specs[-1]
        final_node = final_transition_spec.posture_spec
        final_var_map = final_transition_spec.var_map
        final_hand = final_var_map[PostureSpecVariable.HAND]
        final_spec_constraint = best_path_spec.spec_constraint
        final_carry_target = final_var_map[PostureSpecVariable.CARRY_TARGET]
        slot_manifest_entry = final_var_map.get(PostureSpecVariable.SLOT)
        additional_template_added = False
        for (carry_si, additional_templates) in additional_template_list.items():
            carry_si_carryable = carry_si.carry_target
            if carry_si_carryable is None and carry_si.target is not None and carry_si.target.carryable_component is not None:
                carry_si_carryable = carry_si.target
            if carry_si_carryable is final_carry_target:
                included_sis.add(carry_si)
                additional_template_added = True
            valid_additional_intersection = False
            while True:
                for (destination_spec_additional, var_map_additional, constraint_additional) in [(ds, vm, c) for (c, value) in additional_templates.items() for (ds, vm) in value]:
                    additional_hand = var_map_additional[PostureSpecVariable.HAND]
                    if final_hand == additional_hand:
                        pass
                    if additional_template_added:
                        pass
                    valid_destination = destination_test(sim, final_node, (destination_spec_additional,), var_map_additional, None, carry_si.affordance)
                    valid_intersection = constraint_additional.intersect(final_spec_constraint).valid
                    if not valid_intersection:
                        pass
                    valid_additional_intersection = True
                    if not valid_destination:
                        pass
                    carry_target = var_map_additional[PostureSpecVariable.CARRY_TARGET]
                    container = carry_target.parent
                    if final_node[SURFACE_INDEX][SURFACE_TARGET_INDEX] is container:
                        included_sis.add(carry_si)
                    additional_slot_manifest_entry = var_map_additional.get(PostureSpecVariable.SLOT)
                    if additional_slot_manifest_entry is not None and slot_manifest_entry is not None and slot_manifest_entry.slot_types.intersection(additional_slot_manifest_entry.slot_types):
                        pass
                    if container is not sim:
                        insertion_index = 0
                        fallback_insertion_index_and_spec = None
                        original_spec = best_transition_specs[0].posture_spec
                        if original_spec[SURFACE_INDEX][SURFACE_TARGET_INDEX] is container:
                            fallback_insertion_index_and_spec = InsertionIndexAndSpec(insertion_index, original_spec)
                        while True:
                            for (prev_transition_spec, transition_spec) in zip(best_transition_specs, best_transition_specs[1:]):
                                insertion_index += 1
                                if transition_spec.sequence_id != prev_transition_spec.sequence_id:
                                    pass
                                spec = transition_spec.posture_spec
                                if fallback_insertion_index_and_spec is None and spec[SURFACE_INDEX][SURFACE_TARGET_INDEX] is container:
                                    fallback_insertion_index_and_spec = InsertionIndexAndSpec(insertion_index, spec)
                                while prev_transition_spec.posture_spec[CARRY_INDEX][CARRY_TARGET_INDEX] is None and spec[CARRY_INDEX][CARRY_TARGET_INDEX] is not None:
                                    if spec[SURFACE_INDEX][SURFACE_TARGET_INDEX] is not container:
                                        pass
                                    break
                            while fallback_insertion_index_and_spec is not None:
                                insertion_index = fallback_insertion_index_and_spec.index
                                spec = fallback_insertion_index_and_spec.spec
                                pick_up_sequence = get_pick_up_spec_sequence(spec, container, body_target=spec[BODY_INDEX][BODY_TARGET_INDEX])
                                slot_var_map = {PostureSpecVariable.SLOT: SlotManifestEntry(carry_target, container, carry_target.parent_slot)}
                                var_map_additional_updated = frozendict(var_map_additional, slot_var_map)
                                new_specs = []
                                for pick_up_spec in pick_up_sequence:
                                    new_specs.append(TransitionSpec(best_path_spec, pick_up_spec, var_map_additional_updated, sequence_id=SequenceId.PICKUP))
                                best_path_spec.insert_transition_specs_at_index(insertion_index, new_specs)
                                final_surface_target = final_node.surface.target if final_node.surface is not None else None
                                if final_surface_target is not None:
                                    _slot_manifest_entry = var_map_additional[PostureSpecVariable.SLOT]
                                    overrides = {}
                                    if isinstance(_slot_manifest_entry.target, PostureSpecVariable):
                                        overrides['target'] = final_surface_target
                                    interaction_target = final_var_map[PostureSpecVariable.INTERACTION_TARGET]
                                    if interaction_target is not None:
                                        relative_position = interaction_target.position
                                    else:
                                        relative_position = final_surface_target.position
                                    chosen_slot = self._get_best_slot(final_surface_target, _slot_manifest_entry.slot_types, carry_target, relative_position)
                                    if chosen_slot is None:
                                        pass
                                    overrides['slot'] = chosen_slot
                                    _slot_manifest_entry = _slot_manifest_entry.with_overrides(**overrides)
                                    slot_var_map = {PostureSpecVariable.SLOT: _slot_manifest_entry}
                                    var_map_additional = frozendict(var_map_additional, slot_var_map)
                                if additional_slot_manifest_entry is not None:
                                    insertion_index = 0
                                    fallback_insertion_index_and_spec = None
                                    original_spec = best_transition_specs[0].posture_spec
                                    if original_spec[SURFACE_INDEX][SURFACE_TARGET_INDEX] is slot_manifest_entry.actor.parent:
                                        fallback_insertion_index_and_spec = InsertionIndexAndSpec(insertion_index, original_spec)
                                    while True:
                                        for (prev_transition_spec, transition_spec) in zip(best_transition_specs, best_transition_specs[1:]):
                                            insertion_index += 1
                                            if transition_spec.sequence_id != prev_transition_spec.sequence_id:
                                                pass
                                            spec = transition_spec.posture_spec
                                            if fallback_insertion_index_and_spec is None and spec[SURFACE_INDEX][SURFACE_TARGET_INDEX] is slot_manifest_entry.actor.parent:
                                                fallback_insertion_index_and_spec = InsertionIndexAndSpec(insertion_index, spec)
                                            while prev_transition_spec.posture_spec[CARRY_INDEX][CARRY_TARGET_INDEX] is not None and spec[CARRY_INDEX][CARRY_TARGET_INDEX] is None:
                                                break
                                        while fallback_insertion_index_and_spec is not None:
                                            insertion_index = fallback_insertion_index_and_spec.index
                                            spec = fallback_insertion_index_and_spec.spec
                                            put_down_sequence = get_put_down_spec_sequence(spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX], spec[SURFACE_INDEX][SURFACE_TARGET_INDEX], body_target=spec[BODY_INDEX][BODY_TARGET_INDEX])
                                            new_specs = []
                                            for put_down_spec in put_down_sequence:
                                                new_specs.append(TransitionSpec(best_path_spec, put_down_spec, var_map_additional, sequence_id=SequenceId.PUTDOWN))
                                            best_path_spec.insert_transition_specs_at_index(insertion_index + 1, new_specs)
                                            included_sis.add(carry_si)
                                            additional_template_added = True
                                            break
                                    put_down_sequence = get_put_down_spec_sequence(spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX], spec[SURFACE_INDEX][SURFACE_TARGET_INDEX], body_target=spec[BODY_INDEX][BODY_TARGET_INDEX])
                                    new_specs = []
                                    for put_down_spec in put_down_sequence:
                                        new_specs.append(TransitionSpec(best_path_spec, put_down_spec, var_map_additional, sequence_id=SequenceId.PUTDOWN))
                                    best_path_spec.insert_transition_specs_at_index(insertion_index + 1, new_specs)
                                included_sis.add(carry_si)
                                additional_template_added = True
                                break
                        pick_up_sequence = get_pick_up_spec_sequence(spec, container, body_target=spec[BODY_INDEX][BODY_TARGET_INDEX])
                        slot_var_map = {PostureSpecVariable.SLOT: SlotManifestEntry(carry_target, container, carry_target.parent_slot)}
                        var_map_additional_updated = frozendict(var_map_additional, slot_var_map)
                        new_specs = []
                        for pick_up_spec in pick_up_sequence:
                            new_specs.append(TransitionSpec(best_path_spec, pick_up_spec, var_map_additional_updated, sequence_id=SequenceId.PICKUP))
                        best_path_spec.insert_transition_specs_at_index(insertion_index, new_specs)
                    final_surface_target = final_node.surface.target if final_node.surface is not None else None
                    if final_surface_target is not None:
                        _slot_manifest_entry = var_map_additional[PostureSpecVariable.SLOT]
                        overrides = {}
                        if isinstance(_slot_manifest_entry.target, PostureSpecVariable):
                            overrides['target'] = final_surface_target
                        interaction_target = final_var_map[PostureSpecVariable.INTERACTION_TARGET]
                        if interaction_target is not None:
                            relative_position = interaction_target.position
                        else:
                            relative_position = final_surface_target.position
                        chosen_slot = self._get_best_slot(final_surface_target, _slot_manifest_entry.slot_types, carry_target, relative_position)
                        if chosen_slot is None:
                            pass
                        overrides['slot'] = chosen_slot
                        _slot_manifest_entry = _slot_manifest_entry.with_overrides(**overrides)
                        slot_var_map = {PostureSpecVariable.SLOT: _slot_manifest_entry}
                        var_map_additional = frozendict(var_map_additional, slot_var_map)
                    if additional_slot_manifest_entry is not None:
                        insertion_index = 0
                        fallback_insertion_index_and_spec = None
                        original_spec = best_transition_specs[0].posture_spec
                        if original_spec[SURFACE_INDEX][SURFACE_TARGET_INDEX] is slot_manifest_entry.actor.parent:
                            fallback_insertion_index_and_spec = InsertionIndexAndSpec(insertion_index, original_spec)
                        while True:
                            for (prev_transition_spec, transition_spec) in zip(best_transition_specs, best_transition_specs[1:]):
                                insertion_index += 1
                                if transition_spec.sequence_id != prev_transition_spec.sequence_id:
                                    pass
                                spec = transition_spec.posture_spec
                                if fallback_insertion_index_and_spec is None and spec[SURFACE_INDEX][SURFACE_TARGET_INDEX] is slot_manifest_entry.actor.parent:
                                    fallback_insertion_index_and_spec = InsertionIndexAndSpec(insertion_index, spec)
                                while prev_transition_spec.posture_spec[CARRY_INDEX][CARRY_TARGET_INDEX] is not None and spec[CARRY_INDEX][CARRY_TARGET_INDEX] is None:
                                    break
                            while fallback_insertion_index_and_spec is not None:
                                insertion_index = fallback_insertion_index_and_spec.index
                                spec = fallback_insertion_index_and_spec.spec
                                put_down_sequence = get_put_down_spec_sequence(spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX], spec[SURFACE_INDEX][SURFACE_TARGET_INDEX], body_target=spec[BODY_INDEX][BODY_TARGET_INDEX])
                                new_specs = []
                                for put_down_spec in put_down_sequence:
                                    new_specs.append(TransitionSpec(best_path_spec, put_down_spec, var_map_additional, sequence_id=SequenceId.PUTDOWN))
                                best_path_spec.insert_transition_specs_at_index(insertion_index + 1, new_specs)
                                included_sis.add(carry_si)
                                additional_template_added = True
                                break
                        put_down_sequence = get_put_down_spec_sequence(spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX], spec[SURFACE_INDEX][SURFACE_TARGET_INDEX], body_target=spec[BODY_INDEX][BODY_TARGET_INDEX])
                        new_specs = []
                        for put_down_spec in put_down_sequence:
                            new_specs.append(TransitionSpec(best_path_spec, put_down_spec, var_map_additional, sequence_id=SequenceId.PUTDOWN))
                        best_path_spec.insert_transition_specs_at_index(insertion_index + 1, new_specs)
                    included_sis.add(carry_si)
                    additional_template_added = True
                    break
                while not valid_additional_intersection:
                    carry_si.cancel(FinishingType.TRANSITION_FAILURE, cancel_reason_msg='Posture Graph. No valid intersections for additional constraint.')
        return included_sis

    @staticmethod
    def is_valid_complete_path(sim, path, interaction):
        for posture_spec in path:
            target = posture_spec[BODY_INDEX][BODY_TARGET_INDEX]
            while target is not None:
                if target is interaction.target:
                    basic_reserve = interaction.basic_reserve_object
                    if basic_reserve is not None:
                        handler = basic_reserve(sim, interaction)
                        if handler.may_reserve():
                            pass
                elif target.may_reserve(sim):
                    pass
                if target.usable_by_transition_controller(sim.queue.transition_controller):
                    pass
                return False
        return True

    @staticmethod
    def get_sim_position_routing_data(sim):
        sim_position_constraint = interactions.constraints.Transform(sim.intended_transform, routing_surface=sim.intended_routing_surface, debug_name='SimCurrentPosition')
        return (sim_position_constraint, None, None)

    @staticmethod
    def append_handles(sim, handle_dict, invalid_handle_dict, invalid_los_dict, routing_data, target_path, var_map, dest_spec, cur_path_id, final_constraint, entry=True, path_type=PathType.LEFT):
        (routing_constraint, locked_params, target) = routing_data
        if routing_constraint is None:
            return
        routing_surface = target.routing_surface if target is not None else None
        reference_pt = None
        if target is not None and not target.is_in_inventory() and not target.disable_los_reference_point:
            reference_pt = target.position
            top_level_parent = target
            while top_level_parent.parent is not None:
                top_level_parent = top_level_parent.parent
            if top_level_parent.wall_or_fence_placement:
                reference_pt += top_level_parent.forward*PostureGraphService.WALL_OBJECT_FORWARD_MOD
        weight_route_factor = max(constraint._weight_route_factor for constraint in itertools.chain(routing_constraint, final_constraint))
        blocking_obj_id = None
        for sub_constraint in routing_constraint:
            if not sub_constraint.valid:
                pass
            connectivity_handles = sub_constraint.get_connectivity_handles(sim=sim, routing_surface_override=routing_surface, locked_params=locked_params, los_reference_point=reference_pt, entry=entry, target=target, weight_route_factor=weight_route_factor)
            for connectivity_handle in connectivity_handles:
                connectivity_handle.path = target_path
                connectivity_handle.var_map = var_map
                existing_data = handle_dict.get(connectivity_handle)
                if existing_data is not None and target_path.cost >= existing_data[1]:
                    pass
                if connectivity_handle.los_reference_point is None or test_point_in_compound_polygon(connectivity_handle.los_reference_point, connectivity_handle.geometry.polygon):
                    single_goal_only = True
                else:
                    single_goal_only = False
                for_carryable = path_type == PathType.MIDDLE
                routing_goals = connectivity_handle.get_goals(relative_object=target, single_goal_only=single_goal_only, for_carryable=for_carryable)
                if not routing_goals:
                    while gsi_handlers.posture_graph_handlers.archiver.enabled:
                        gsi_handlers.posture_graph_handlers.log_transition_handle(sim, connectivity_handle, connectivity_handle.polygons, target_path, 'no goals generated', path_type)
                        yield_to_irq()
                        valid_goals = []
                        invalid_goals = []
                        invalid_los_goals = []
                        for goal in routing_goals:
                            if not single_goal_only and (goal.requires_los_check and target is not None) and not target.is_sim:
                                (result, blocking_obj_id) = target.check_line_of_sight(goal.location.transform, verbose=True)
                                if result == routing.RAYCAST_HIT_TYPE_IMPASSABLE:
                                    invalid_goals.append(goal)
                                elif result == routing.RAYCAST_HIT_TYPE_LOS_IMPASSABLE:
                                    invalid_los_goals.append(goal)
                            goal.path_id = cur_path_id
                            valid_goals.append(goal)
                        if gsi_handlers.posture_graph_handlers.archiver.enabled and (invalid_goals or invalid_los_goals):
                            gsi_handlers.posture_graph_handlers.log_transition_handle(sim, connectivity_handle, connectivity_handle.polygons, target_path, 'LOS Failure', path_type)
                        if invalid_goals:
                            invalid_handle_dict[connectivity_handle] = (target_path, target_path.cost, var_map, dest_spec, invalid_goals, routing_constraint, final_constraint)
                        if invalid_los_goals:
                            invalid_los_dict[connectivity_handle] = (target_path, target_path.cost, var_map, dest_spec, invalid_los_goals, routing_constraint, final_constraint)
                        if not valid_goals:
                            pass
                        if gsi_handlers.posture_graph_handlers.archiver.enabled:
                            gsi_handlers.posture_graph_handlers.log_transition_handle(sim, connectivity_handle, connectivity_handle.polygons, target_path, True, path_type)
                        handle_dict[connectivity_handle] = (target_path, target_path.cost, var_map, dest_spec, valid_goals, routing_constraint, final_constraint)
                yield_to_irq()
                valid_goals = []
                invalid_goals = []
                invalid_los_goals = []
                for goal in routing_goals:
                    if not single_goal_only and (goal.requires_los_check and target is not None) and not target.is_sim:
                        (result, blocking_obj_id) = target.check_line_of_sight(goal.location.transform, verbose=True)
                        if result == routing.RAYCAST_HIT_TYPE_IMPASSABLE:
                            invalid_goals.append(goal)
                        elif result == routing.RAYCAST_HIT_TYPE_LOS_IMPASSABLE:
                            invalid_los_goals.append(goal)
                    goal.path_id = cur_path_id
                    valid_goals.append(goal)
                if gsi_handlers.posture_graph_handlers.archiver.enabled and (invalid_goals or invalid_los_goals):
                    gsi_handlers.posture_graph_handlers.log_transition_handle(sim, connectivity_handle, connectivity_handle.polygons, target_path, 'LOS Failure', path_type)
                if invalid_goals:
                    invalid_handle_dict[connectivity_handle] = (target_path, target_path.cost, var_map, dest_spec, invalid_goals, routing_constraint, final_constraint)
                if invalid_los_goals:
                    invalid_los_dict[connectivity_handle] = (target_path, target_path.cost, var_map, dest_spec, invalid_los_goals, routing_constraint, final_constraint)
                if not valid_goals:
                    pass
                if gsi_handlers.posture_graph_handlers.archiver.enabled:
                    gsi_handlers.posture_graph_handlers.log_transition_handle(sim, connectivity_handle, connectivity_handle.polygons, target_path, True, path_type)
                handle_dict[connectivity_handle] = (target_path, target_path.cost, var_map, dest_spec, valid_goals, routing_constraint, final_constraint)
            while gsi_handlers.posture_graph_handlers.archiver.enabled and not connectivity_handles and sub_constraint.geometry is not None:
                gsi_handlers.posture_graph_handlers.log_transition_handle(sim, None, sub_constraint.geometry, target_path, True, path_type)
        return blocking_obj_id or None

    @staticmethod
    def copy_handles(sim, destination_handles, path, var_map):
        existing_data = destination_handles.get(DEFAULT)
        if existing_data is not None:
            existing_cost = existing_data[1]
            if path.cost >= existing_cost:
                return
        destination_spec = path.segmented_path.destination_specs.get(path[-1])
        destination_handles[DEFAULT] = (path, path.cost, var_map, destination_spec, [], Anywhere(), Anywhere())

    def _get_resolved_var_map(self, path, var_map):
        final_spec = path[-1]
        target = final_spec[BODY_INDEX][BODY_TARGET_INDEX]
        surface_target = final_spec[SURFACE_INDEX][SURFACE_TARGET_INDEX]
        updates = {}
        if target is not None:
            original_target = var_map.get(PostureSpecVariable.INTERACTION_TARGET)
            if original_target is not None and original_target.id == target.id:
                updates[PostureSpecVariable.INTERACTION_TARGET] = target
            original_carry_target = var_map.get(PostureSpecVariable.CARRY_TARGET)
            if original_carry_target is not None and original_carry_target.id == target.id:
                updates[PostureSpecVariable.CARRY_TARGET] = target
        if surface_target is not None:
            slot_manifest_entry = var_map.get(PostureSpecVariable.SLOT)
            if slot_manifest_entry is not None and slot_manifest_entry.target is not None:
                if isinstance(slot_manifest_entry.target, PostureSpecVariable) or slot_manifest_entry.target.id == surface_target.id:
                    slot_manifest_entry = SlotManifestEntry(slot_manifest_entry.actor, surface_target, slot_manifest_entry.slot)
                    updates[PostureSpecVariable.SLOT] = slot_manifest_entry
                    slot_types = slot_manifest_entry.slot_types
                    if slot_types:
                        slot_cost_modifier = min(surface_target.slot_cost_modifiers.get(slot_type, 0) for slot_type in slot_types)
                        path.cost = max(slot_cost_modifier + path.cost, 0)
        return frozendict(var_map, updates)

    def _generate_left_handles(self, sim, interaction, participant_type, left_path, var_map, destination_spec, final_constraint, unique_id, sim_position_routing_data):
        left_handles = {}
        invalid = {}
        invalid_los = {}
        blocking_obj_ids = []
        if left_path[0][BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile:
            blocking_obj_id = self.append_handles(sim, left_handles, invalid, invalid_los, sim_position_routing_data, left_path, var_map, destination_spec, unique_id, final_constraint, path_type=PathType.LEFT)
            if blocking_obj_id is not None:
                blocking_obj_ids.append(blocking_obj_id)
        else:
            (exit_spec, _, _) = self.find_exit_posture_spec(sim, left_path, var_map)
            if exit_spec == left_path[0] and sim.posture.is_puppet:
                with create_puppet_postures(sim):
                    (use_previous_position, routing_data) = self.get_locations_from_posture(sim, exit_spec, var_map, participant_type=participant_type)
            else:
                (use_previous_position, routing_data) = self.get_locations_from_posture(sim, exit_spec, var_map, participant_type=participant_type)
            if use_previous_position:
                routing_data = sim_position_routing_data
            blocking_obj_id = self.append_handles(sim, left_handles, invalid, invalid_los, routing_data, left_path, var_map, destination_spec, unique_id, final_constraint, entry=False, path_type=PathType.LEFT)
            if blocking_obj_id is not None:
                blocking_obj_ids.append(blocking_obj_id)
        return (left_handles, invalid, invalid_los, blocking_obj_ids)

    def _generate_right_handles(self, sim, interaction, participant_type, right_path, var_map, destination_spec, final_constraint, unique_id, animation_resolver_fn):
        right_handles = {}
        invalid = {}
        invalid_los = {}
        blocking_obj_ids = []
        first_spec = right_path[0]
        if first_spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile and first_spec[BODY_INDEX][BODY_TARGET_INDEX] is None:
            (entry_spec, constrained_edge, _) = self.find_entry_posture_spec(sim, right_path, var_map)
            final_spec = right_path[-1]
            relevant_interaction = interaction if entry_spec is final_spec else None
            right_var_map = self._get_resolved_var_map(right_path, right_path.segmented_path.var_map)
            right_path.segmented_path.var_map_resolved = right_var_map
            (use_previous_pos, routing_data) = self.get_locations_from_posture(sim, entry_spec, right_var_map, interaction=relevant_interaction, participant_type=participant_type, constrained_edge=constrained_edge, animation_resolver_fn=animation_resolver_fn, final_constraint=final_constraint)
            if use_previous_pos:
                self.copy_handles(sim, right_handles, right_path, right_var_map)
            elif routing_data[0].valid:
                blocking_obj_id = self.append_handles(sim, right_handles, invalid, invalid_los, routing_data, right_path, right_var_map, destination_spec, unique_id, final_constraint, path_type=PathType.RIGHT)
                if blocking_obj_id is not None:
                    blocking_obj_ids.append(blocking_obj_id)
        return (right_handles, invalid, invalid_los, blocking_obj_ids)

    def _generate_middle_handles(self, sim, interaction, participant_type, middle_path, var_map, destination_spec, final_constraint, unique_id, animation_resolver_fn):
        middle_handles = {}
        invalid = {}
        invalid_los = {}
        blocking_obj_ids = []
        (entry_spec, constrained_edge, carry_spec) = self.find_entry_posture_spec(sim, middle_path, var_map)
        if constrained_edge is None:
            carry_target = var_map[PostureSpecVariable.CARRY_TARGET]
            if carry_target is not None and carry_target.is_in_sim_inventory():
                self.copy_handles(sim, middle_handles, middle_path, var_map)
            else:
                raise RuntimeError('Have a middle path to pick up an object that is not in the inventory and we cannot generate a constrained_edge; object: {}'.format(carry_target))
        else:
            carry_transition_constraint = constrained_edge.get_constraint(sim, carry_spec, var_map)
            target_posture_state = postures.posture_state.PostureState(sim, None, carry_spec, var_map, invalid_expected=True)
            interaction.transition.add_relevant_object(target_posture_state.body_target)
            carry_transition_constraint = carry_transition_constraint.apply_posture_state(target_posture_state, animation_resolver_fn)
            if carry_transition_constraint is not None:
                carry_spec_surface_spec = carry_spec[SURFACE_INDEX]
                if carry_spec_surface_spec is not None:
                    relative_object = carry_spec_surface_spec[SURFACE_TARGET_INDEX]
                else:
                    relative_object = None
                if relative_object is None:
                    relative_object = carry_spec[BODY_INDEX][BODY_TARGET_INDEX]
                if relative_object is None:
                    relative_object = entry_spec[CARRY_INDEX][CARRY_TARGET_INDEX]
                    if isinstance(relative_object, PostureSpecVariable):
                        relative_object = var_map.get(relative_object)
                if any(constraint.geometry is not None for constraint in carry_transition_constraint):
                    blocking_obj_id = self.append_handles(sim, middle_handles, invalid, invalid_los, (carry_transition_constraint, None, relative_object), middle_path, var_map, destination_spec, unique_id, final_constraint, path_type=PathType.MIDDLE)
                    blocking_obj_ids.append(blocking_obj_id)
                else:
                    self.copy_handles(sim, middle_handles, middle_path, var_map)
        return (middle_handles, invalid, invalid_los, blocking_obj_ids)

    def _get_segmented_path_connectivity_handles(self, sim, segmented_path, interaction, participant_type, animation_resolver_fn, sim_position_routing_data):
        blocking_obj_ids = []
        searched = {PathType.LEFT: set(), PathType.RIGHT: set()}
        (middle_handles, invalid_middles) = ({}, {})
        invalid_los_middles = {}
        (destination_handles, invalid_destinations) = ({}, {})
        invalid_los_destinations = {}
        (source_handles, invalid_sources) = ({}, {})
        invalid_los_sources = {}
        for path_left in segmented_path.generate_left_paths():
            if path_left[-1] in searched[PathType.LEFT]:
                pass
            (source_handles, invalid_sources, invalid_los_sources, blockers) = self._generate_left_handles(sim, interaction, participant_type, path_left, segmented_path.var_map, None, segmented_path.constraint, id(segmented_path), sim_position_routing_data)
            blocking_obj_ids += blockers
            if not source_handles:
                pass
            searched[PathType.LEFT].add(path_left[-1])
            for path_right in segmented_path.generate_right_paths(path_left):
                (entry_node, _, _) = self.find_entry_posture_spec(sim, path_right, segmented_path.var_map)
                if entry_node is not None and entry_node.body_target in searched[PathType.RIGHT]:
                    pass
                destination_spec = segmented_path.destination_specs[path_right[-1]]
                (destination_handles, invalid_destinations, invalid_los_destinations, blockers) = self._generate_right_handles(sim, interaction, participant_type, path_right, segmented_path.var_map, destination_spec, segmented_path.constraint, id(segmented_path), animation_resolver_fn)
                blocking_obj_ids += blockers
                if not destination_handles:
                    pass
                final_body_target = path_right[-1].body_target
                if final_body_target is not None:
                    posture = postures.create_posture(path_right[-1].body_posture, sim, final_body_target)
                    slot_constraint = posture.slot_constraint_simple
                    if slot_constraint is not None:
                        geometry_constraint = segmented_path.constraint.generate_geometry_only_constraint()
                        if not slot_constraint.intersect(geometry_constraint).valid:
                            pass
                if entry_node is not None:
                    searched[PathType.RIGHT].add(entry_node.body_target)
                for path_middle in segmented_path.generate_middle_paths(path_left, path_right):
                    if path_middle is None:
                        if path_left[-1] != path_right[0]:
                            pass
                        return (source_handles, {}, destination_handles, invalid_sources, {}, invalid_destinations, invalid_los_sources, {}, invalid_los_destinations, blocking_obj_ids)
                    (middle_handles, invalid_middles, invalid_los_middles, blockers) = self._generate_middle_handles(sim, interaction, participant_type, path_middle, segmented_path.var_map_resolved, destination_spec, segmented_path.constraint, id(segmented_path), animation_resolver_fn)
                    blocking_obj_ids += blockers
                    while middle_handles:
                        return (source_handles, middle_handles, destination_handles, invalid_sources, invalid_middles, invalid_destinations, invalid_los_sources, invalid_los_middles, invalid_los_destinations, blocking_obj_ids)
                while all(dest in searched[PathType.RIGHT] for dest in segmented_path.left_destinations) or len(searched[PathType.RIGHT]) >= MAX_RIGHT_PATHS:
                    break
        return (source_handles, {}, {}, invalid_sources, invalid_middles, invalid_destinations, invalid_los_sources, invalid_los_middles, invalid_los_destinations, blocking_obj_ids)

    def generate_connectivity_handles(self, sim, segmented_paths, interaction, participant_type, animation_resolver_fn):
        if len(segmented_paths) == 0:
            return Connectivity(None, None, None, None)
        source_destination_sets = collections.OrderedDict()
        source_middle_sets = collections.OrderedDict()
        middle_destination_sets = collections.OrderedDict()
        sim_position_routing_data = self.get_sim_position_routing_data(sim)
        best_complete_path = EMPTY_PATH_SPEC
        for segmented_path in segmented_paths:
            if not segmented_path.is_complete:
                pass
            for left_path in segmented_path.generate_left_paths():
                for right_path in segmented_path.generate_right_paths(left_path):
                    complete_path = left_path + right_path
                    if not self.is_valid_complete_path(sim, complete_path, interaction):
                        pass
                    if best_complete_path is not EMPTY_PATH_SPEC and best_complete_path.cost <= complete_path.cost:
                        break
                    final_node = complete_path[-1]
                    if interaction.privacy is not None and len(complete_path) == 1:
                        complete_path.append(final_node)
                    destination_spec = segmented_path.destination_specs[final_node]
                    var_map = self._get_resolved_var_map(complete_path, segmented_path.var_map)
                    constraint = segmented_path.constraint
                    if len(complete_path) == 1:
                        transform_constraint = None
                        if not sim.posture.mobile:
                            transform_constraint = sim.posture.slot_constraint
                        if transform_constraint is None:
                            transform_constraint = interactions.constraints.Transform(sim.transform, routing_surface=sim.routing_surface)
                        final_constraint = constraint.intersect(transform_constraint)
                    else:
                        (_, routing_data) = self.get_locations_from_posture(sim, complete_path[-1], var_map, interaction=interaction, participant_type=participant_type, animation_resolver_fn=animation_resolver_fn, final_constraint=constraint)
                        final_constraint = routing_data[0]
                    if final_constraint is not None and not final_constraint.valid:
                        pass
                    if final_constraint is None:
                        final_constraint = constraint
                    best_complete_path = PathSpec(complete_path, complete_path.cost, var_map, destination_spec, final_constraint, constraint, allow_tentative=True)
                    self._generate_surface_and_slot_targets(best_complete_path, None, sim.routing_location, objects_to_ignore=DEFAULT)
                    break
                while best_complete_path is not EMPTY_PATH_SPEC:
                    break
        blocking_obj_ids = []
        for segmented_path in segmented_paths:
            if segmented_path.is_complete:
                pass
            handles = self._get_segmented_path_connectivity_handles(sim, segmented_path, interaction, participant_type, animation_resolver_fn, sim_position_routing_data)
            (source_handles, middle_handles, destination_handles, invalid_sources, invalid_middles, invalid_destinations, invalid_los_sources, invalid_los_middles, invalid_los_destinations, blockers) = handles
            blocking_obj_ids += blockers
            if middle_handles:
                value = (source_handles, middle_handles, {}, {}, invalid_middles, invalid_los_middles)
                source_middle_sets[segmented_path] = value
                value = [None, destination_handles, invalid_middles, invalid_los_middles, invalid_destinations, invalid_los_destinations]
                middle_destination_sets[segmented_path] = value
            else:
                if DEFAULT in destination_handles:
                    default_values = {source_handle.clone(): destination_handles[DEFAULT] for source_handle in source_handles}
                    for (dest_handle, (dest_path, _, _, _, _, _, _)) in default_values.items():
                        dest_handle.path = dest_path
                    del destination_handles[DEFAULT]
                    destination_handles.update(default_values)
                value = (source_handles, destination_handles, {}, {}, invalid_destinations, invalid_los_destinations)
                source_destination_sets[segmented_path] = value
        if best_complete_path is EMPTY_PATH_SPEC and not (source_destination_sets or source_middle_sets and middle_destination_sets):
            if blocking_obj_ids:
                set_transition_failure_reason(sim, TransitionFailureReasons.BLOCKING_OBJECT, target_id=blocking_obj_ids[0], transition_controller=interaction.transition)
            else:
                set_transition_failure_reason(sim, TransitionFailureReasons.NO_VALID_INTERSECTION, transition_controller=interaction.transition)
        return Connectivity(best_complete_path, source_destination_sets, source_middle_sets, middle_destination_sets)

    def find_best_path_pair(self, interaction, sim, connectivity, timeline):
        (best_complete_path, source_destination_sets, source_middle_sets, middle_destination_sets) = connectivity
        (success, best_non_complete_path) = yield self._find_best_path_pair(interaction, sim, source_destination_sets, source_middle_sets, middle_destination_sets, timeline)
        if best_complete_path is EMPTY_PATH_SPEC and success == False:
            return (success, best_non_complete_path)
        if best_complete_path is EMPTY_PATH_SPEC:
            return (success, best_non_complete_path)
        if best_non_complete_path is EMPTY_PATH_SPEC:
            return (True, best_complete_path)
        if not success or best_complete_path.cost <= best_non_complete_path.total_cost:
            return (True, best_complete_path)
        return (success, best_non_complete_path)

    def _find_best_path_pair(self, interaction, sim, source_destination_sets, source_middle_sets, middle_destination_sets, timeline):
        source_dest_success = False
        source_dest_path_spec = EMPTY_PATH_SPEC
        source_dest_cost = sims4.math.MAX_FLOAT
        middle_success = False
        middle_path_spec = EMPTY_PATH_SPEC
        middle_cost = sims4.math.MAX_FLOAT
        if source_destination_sets:
            (source_dest_success, source_dest_path_spec, _) = yield self.get_best_path_between_handles(interaction, sim, source_destination_sets, timeline)
            source_dest_cost = source_dest_path_spec.total_cost
        if middle_destination_sets:
            (middle_success, middle_path_spec, selected_goal) = yield self.get_best_path_between_handles(interaction, sim, source_middle_sets, timeline, path_type=PathType.MIDDLE)
            if middle_success:
                geometry = create_transform_geometry(selected_goal.location.transform)
                middle_handle = selected_goal.connectivity_handle.clone(routing_surface_override=selected_goal.routing_surface_id, geometry=geometry)
                middle_handle.path = middle_path = algos.Path(middle_path_spec.path[-1:])
                middle_path.segmented_path = selected_goal.connectivity_handle.path.segmented_path
                middle_handle.var_map = middle_path.segmented_path.var_map_resolved
                selected_goal.connectivity_handle = middle_handle
                middle_handle_set = {middle_handle: (middle_path, 0, middle_path_spec.var_map, None, [selected_goal], None, None)}
                for middle_dest_set in middle_destination_sets.values():
                    middle_dest_set[0] = middle_handle_set
                (middle_success, best_right_path_spec, _) = yield self.get_best_path_between_handles(interaction, sim, middle_destination_sets, timeline)
                if middle_success:
                    middle_path_spec = middle_path_spec.combine(best_right_path_spec)
                    middle_cost = middle_path_spec.total_cost
        if source_dest_success == middle_success:
            if source_dest_cost <= middle_cost:
                (result_success, result_path_spec) = (source_dest_success, source_dest_path_spec)
            else:
                (result_success, result_path_spec) = (middle_success, middle_path_spec)
        elif source_dest_success:
            (result_success, result_path_spec) = (source_dest_success, source_dest_path_spec)
        else:
            (result_success, result_path_spec) = (middle_success, middle_path_spec)
        return (result_success, result_path_spec)

    def _get_best_slot(self, slot_target, slot_types, obj, location, objects_to_ignore=DEFAULT):
        runtime_slots = tuple(slot_target.get_runtime_slots_gen(slot_types=slot_types))
        if not runtime_slots:
            return
        chosen_slot = None
        closest_distance = None
        for runtime_slot in runtime_slots:
            while runtime_slot.is_valid_for_placement(obj=obj, objects_to_ignore=objects_to_ignore):
                transform = runtime_slot.transform
                slot_routing_location = routing.Location(transform.translation, transform.orientation, runtime_slot.routing_surface)
                distance = (location - slot_routing_location.position).magnitude_2d_squared()
                if closest_distance is None or distance < closest_distance:
                    chosen_slot = runtime_slot
                    closest_distance = distance
        return chosen_slot

    def _generate_surface_and_slot_targets(self, path_spec_right, path_spec_left, final_sim_routing_location, objects_to_ignore):
        slot_var = path_spec_right.var_map.get(PostureSpecVariable.SLOT)
        if slot_var is None:
            return True
        slot_target = slot_var.target
        if isinstance(slot_target, PostureSpecVariable):
            return False
        chosen_slot = self._get_best_slot(slot_target, slot_var.slot_types, slot_var.actor, final_sim_routing_location.position, objects_to_ignore)
        if chosen_slot is None:
            return False
        path_spec_right._final_constraint = path_spec_right.final_constraint.generate_constraint_with_slot_info(slot_var.actor, slot_target, chosen_slot)
        path_spec_right._spec_constraint = path_spec_right.spec_constraint.generate_constraint_with_slot_info(slot_var.actor, slot_target, chosen_slot)

        def get_frozen_manifest_entry():
            for constraint in path_spec_right.spec_constraint:
                while constraint.posture_state_spec is not None:
                    while True:
                        for manifest_entry in constraint.posture_state_spec.slot_manifest:
                            pass
            raise AssertionError('Spec constraint with no manifest entries: {}'.format(path_spec_right.spec_constraint))

        frozen_manifest_entry = get_frozen_manifest_entry()

        def replace_var_map_for_path_spec(path_spec):
            for spec in path_spec.transition_specs:
                while PostureSpecVariable.SLOT in spec.var_map:
                    new_var_map = {}
                    new_var_map[PostureSpecVariable.SLOT] = frozen_manifest_entry
                    spec.var_map = frozendict(spec.var_map, new_var_map)

        replace_var_map_for_path_spec(path_spec_right)
        if path_spec_left is not None:
            replace_var_map_for_path_spec(path_spec_left)
        return True

    @staticmethod
    def estimate_distance_for_connectivity(sim, connectivity):
        (best_complete_path, source_destination_sets, source_middle_sets, _) = connectivity
        if best_complete_path:
            return (0, False)
        if not source_destination_sets and not source_middle_sets:
            return (None, False)
        min_distance = sims4.math.MAX_FLOAT
        routing_sets = source_destination_sets or source_middle_sets
        for (source_handles, destination_handles, _, _, _, _) in routing_sets.values():
            left_handles = set(source_handles.keys())
            right_handles = set(destination_handles.keys())
            while not not left_handles:
                if not right_handles:
                    pass
                yield_to_irq()
                if DEFAULT in right_handles:
                    min_distance = 0.0
                distances = routing.estimate_path_batch(left_handles, right_handles, routing_context=sim.routing_context)
                if not distances:
                    pass
                for (left_handle, right_handle, distance) in distances:
                    while distance is not None and distance < min_distance:
                        min_distance = distance + left_handle.path.cost + right_handle.path.cost
        if min_distance == sims4.math.MAX_FLOAT:
            return (None, False)
        return (min_distance, True)

    def _prepare_goals_for_router(self, sim, handle_dict, goal_list, data_list, highest_cost, debug_type_str):
        for source_data in handle_dict.values():
            (_, path_cost, _, _, left_goals, _, _) = source_data
            for (_, goal) in enumerate(left_goals):
                goal.cost = max(highest_cost - goal.cost, 0) + path_cost
                goal_list.append(goal)
            data_list.append(source_data)

    def get_best_path_between_handles(self, interaction, sim, source_destination_sets, timeline, path_type=None):
        non_suppressed_source_goals = []
        non_suppressed_goals = []
        suppressed_source_goals = []
        suppressed_goals = []
        postures.posture_scoring.set_transition_destinations(sim, source_destination_sets, preserve=True, draw_both_sets=True)
        for (source_handles, _, _, _, _, _) in source_destination_sets.values():
            for source_handle in source_handles:
                if source_handle is DEFAULT:
                    raise AssertionError
                path_cost = source_handles[source_handle][1]
                for_carryable = path_type == PathType.MIDDLE
                source_goals = source_handle.get_goals(relative_object=source_handle.target, for_carryable=for_carryable)
                for source_goal in source_goals:
                    if source_goal.cost >= 0 and (source_goal.requires_los_check and source_handle.target is not None) and not source_handle.target.is_sim:
                        (result, _) = source_handle.target.check_line_of_sight(source_goal.location.transform, verbose=True)
                        if result != routing.RAYCAST_HIT_TYPE_NONE:
                            if source_goal.cost == 0:
                                source_goal.cost = -0.01
                    source_goal.path_cost = path_cost
                non_suppressed_source_goals += [goal for goal in source_goals if goal.cost >= NON_SUPPRESSED_FAILURE_GOAL_SCORE]
                suppressed_source_goals += [goal for goal in source_goals if goal.cost < NON_SUPPRESSED_FAILURE_GOAL_SCORE]
        default_goals = set()
        for (_, destination_handles, _, _, _, _) in source_destination_sets.values():
            for dest_handle in destination_handles:
                if dest_handle is DEFAULT:
                    is_default = True
                    (right_path, path_cost) = destination_handles[DEFAULT][:2]
                    additional_dest_handles = []
                    for (source_handles, *_) in source_destination_sets.values():
                        for source_handle in source_handles:
                            dest_handle = source_handle.clone()
                            dest_handle.path = right_path
                            additional_dest_handles.append(dest_handle)
                else:
                    is_default = False
                    path_cost = destination_handles[dest_handle][1]
                    additional_dest_handles = [dest_handle]
                for dest_handle in additional_dest_handles:
                    for_carryable = path_type == PathType.MIDDLE
                    dest_goals = dest_handle.get_goals(relative_object=dest_handle.target, for_carryable=for_carryable)
                    for dest_goal in dest_goals:
                        dest_goal.path_cost = path_cost
                        if is_default:
                            default_goals.add(dest_goal)
                        if dest_goal.cost < 0 and sims4.math.vector3_almost_equal_2d(dest_goal.position, sim.position):
                            dest_goal.cost = 0
                        while dest_goal.cost >= 0 and (dest_goal.requires_los_check and dest_handle.target is not None) and not dest_handle.target.is_sim:
                            (result, _) = dest_handle.target.check_line_of_sight(dest_goal.location.transform, verbose=True)
                            if result != routing.RAYCAST_HIT_TYPE_NONE:
                                if dest_goal.cost == 0:
                                    dest_goal.cost = -0.01
                    non_suppressed_goals += [goal for goal in dest_goals if goal.cost >= NON_SUPPRESSED_FAILURE_GOAL_SCORE]
                    suppressed_goals += [goal for goal in dest_goals if goal.cost < NON_SUPPRESSED_FAILURE_GOAL_SCORE]
        all_source_goals = non_suppressed_source_goals or suppressed_source_goals
        all_dest_goals = non_suppressed_goals or suppressed_goals
        if not all_source_goals or not all_dest_goals:
            failure_path = yield self._get_failure_path_spec_gen(timeline, sim, source_destination_sets)
            return (False, failure_path, None)
        highest_score = max(abs(goal.cost) for goal in itertools.chain(all_source_goals, all_dest_goals))
        for goal in itertools.chain(all_source_goals, all_dest_goals):
            goal.cost = highest_score - abs(goal.cost)
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            for source_goal in all_source_goals:
                gsi_handlers.posture_graph_handlers.log_possible_goal(sim, source_goal.connectivity_handle.path, source_goal, source_goal.cost, 'Source', id(source_destination_sets))
            for dest_goal in all_dest_goals:
                gsi_handlers.posture_graph_handlers.log_possible_goal(sim, dest_goal.connectivity_handle.path, dest_goal, dest_goal.cost, 'Dest', id(source_destination_sets))
        self.normalize_goal_costs(all_source_goals)
        self.normalize_goal_costs(all_dest_goals)
        route = routing.Route(all_source_goals[0].location, all_dest_goals, additional_origins=all_source_goals, routing_context=sim.routing_context)
        is_failure_path = all_dest_goals is suppressed_goals
        plan_primitive = interactions.utils.routing.PlanRoute(route, sim, is_failure_route=is_failure_path)
        result = yield element_utils.run_child(timeline, elements.MustRunElement(plan_primitive))
        if not result:
            raise RuntimeError('Unknown error when trying to run PlanRoute.run()')
        if is_failure_path and plan_primitive.path.nodes and plan_primitive.path.nodes.plan_failure_object_id:
            failure_obj_id = plan_primitive.path.nodes.plan_failure_object_id
            set_transition_failure_reason(sim, TransitionFailureReasons.BLOCKING_OBJECT, target_id=failure_obj_id)
        if not is_failure_path and not plan_primitive.path.nodes.plan_success or not plan_primitive.path.nodes:
            failure_path = yield self._get_failure_path_spec_gen(timeline, sim, source_destination_sets)
            return (False, failure_path, None)
        origin = plan_primitive.path.selected_start
        origin_path = origin.connectivity_handle.path
        dest = plan_primitive.path.selected_goal
        dest_path = dest.connectivity_handle.path
        destination_spec = origin_path.segmented_path.destination_specs.get(dest_path[-1])
        left_path_spec = PathSpec(origin_path, origin.path_cost, origin.connectivity_handle.var_map, None, origin.connectivity_handle.constraint, origin_path.segmented_path.constraint, is_failure_path=is_failure_path)
        o_locked_params = origin.slot_params if origin.has_slot_params else frozendict()
        left_path_spec.attach_route_and_params(None, o_locked_params, None, reverse=True)
        selected_dest_transform = sims4.math.Transform(sims4.math.Vector3(*dest.location.position), sims4.math.Quaternion(*dest.location.orientation))
        if isinstance(dest, SlotGoal) and not dest_path[-1][BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile:
            selected_dest_containment_transform = dest.containment_transform
        else:
            selected_dest_containment_transform = selected_dest_transform
        selected_dest_constraint = interactions.constraints.Transform(selected_dest_containment_transform, routing_surface=dest.routing_surface_id)
        constraint = dest.connectivity_handle.constraint
        d_route_constraint = constraint.apply(selected_dest_constraint)
        if not d_route_constraint.valid:
            d_route_constraint = constraint
        right_path_spec = PathSpec(dest_path, dest.path_cost, dest_path.segmented_path.var_map_resolved, destination_spec, d_route_constraint, dest_path.segmented_path.constraint, final_routing_transform=selected_dest_transform, is_failure_path=is_failure_path)
        if interaction.carry_target is not None:
            objects_to_ignore = (interaction.carry_target,)
        else:
            objects_to_ignore = DEFAULT
        if not (dest_path.segmented_path.constraint is not None and self._generate_surface_and_slot_targets(right_path_spec, left_path_spec, dest.location, objects_to_ignore)):
            return (False, EMPTY_PATH_SPEC, None)
        d_locked_params = dest.slot_params if dest.has_slot_params else frozendict()
        cur_path = plan_primitive.path
        while cur_path.next_path is not None:
            left_path_spec.create_route_node(cur_path, None)
            left_path_spec.create_route_node(None, None, portal=cur_path.portal)
            cur_path = cur_path.next_path
        right_path_spec.attach_route_and_params(cur_path, d_locked_params, d_route_constraint)
        path_spec = left_path_spec.combine(right_path_spec)
        return (True, path_spec, dest)

    def normalize_goal_costs(self, all_goals):
        min_weight = sims4.math.MAX_UINT16
        for goal in all_goals:
            while goal.weight < min_weight:
                min_weight = goal.weight
                if min_weight == 0:
                    return
        for goal in all_goals:
            pass

    def _get_failure_path_spec_gen(self, timeline, sim, source_destination_sets):
        all_sources = {}
        all_destinations = {}
        all_invalid_sources = {}
        all_invalid_los_sources = {}
        all_invalid_destinations = {}
        all_invalid_los_destinations = {}
        for (source_handles, destination_handles, invalid_sources, invalid_los_sources, invalid_destinations, invalid_los_destinations) in source_destination_sets.values():
            all_sources.update(source_handles)
            all_destinations.update(destination_handles)
            all_invalid_sources.update(invalid_sources)
            all_invalid_los_sources.update(invalid_los_sources)
            all_invalid_destinations.update(invalid_destinations)
            all_invalid_los_destinations.update(invalid_los_destinations)
        set_transition_failure_reason(sim, TransitionFailureReasons.PATH_PLAN_FAILED)
        failure_sources = all_sources or (all_invalid_sources or all_invalid_los_sources)
        if not failure_sources:
            return EMPTY_PATH_SPEC
        best_left_data = None
        best_left_cost = sims4.math.MAX_UINT32
        for (source_handle, (_, path_cost, _, _, _, _, _)) in failure_sources.items():
            while path_cost < best_left_cost:
                best_left_cost = path_cost
                best_left_data = failure_sources[source_handle]
                best_left_goal = best_left_data[4][0]
        fail_left_path_spec = PathSpec(best_left_data[0], best_left_data[1], best_left_data[2], best_left_data[3], best_left_data[5], best_left_data[6], is_failure_path=True)
        if best_left_goal is not None and best_left_goal.has_slot_params and best_left_goal.slot_params:
            fail_left_path_spec.attach_route_and_params(None, best_left_goal.slot_params, None, reverse=True)
        failure_destinations = all_destinations or (all_invalid_destinations or all_invalid_los_destinations)
        if not failure_destinations:
            return EMPTY_PATH_SPEC
        all_destination_goals = []
        for (_, _, _, _, dest_goals, _, _) in failure_destinations.values():
            all_destination_goals.extend(dest_goals)
        if all_destination_goals:
            route = routing.Route(best_left_goal.location, all_destination_goals, routing_context=sim.routing_context)
            plan_element = interactions.utils.routing.PlanRoute(route, sim)
            result = yield element_utils.run_child(timeline, plan_element)
            if not result:
                raise RuntimeError('Failed to generate a failure path.')
            if plan_element.path.nodes:
                fail_left_path_spec.create_route_node(plan_element.path, None)
                return fail_left_path_spec
        return EMPTY_PATH_SPEC

    def handle_teleporting_path(self, segmented_paths):
        best_left_path = None
        best_cost = None
        for segmented_path in segmented_paths:
            for left_path in segmented_path.generate_left_paths():
                if best_left_path is None or left_path.cost < best_cost:
                    best_left_path = left_path
                    best_cost = left_path.cost
                    if left_path[-1] in segmented_path.destination_specs:
                        dest_spec = segmented_path.destination_specs[left_path[-1]]
                    else:
                        dest_spec = left_path[-1]
                    var_map = segmented_path.var_map_resolved
                else:
                    break
        if best_left_path is None:
            raise ValueError('No left paths found for teleporting path.')
        return PathSpec(best_left_path, best_left_path.cost, var_map, dest_spec, None, None, path_as_posture_specs=True)

    def _find_first_constrained_edge(self, sim, path, var_map, reverse=False):
        if not path:
            return (None, None, None)
        if reverse:
            sequence = reversed(path)
        else:
            sequence = path
        for posture_spec in sequence:
            while not posture_spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].unconstrained:
                return (posture_spec, None, None)
        if len(path) > 1:
            sequence = zip(path, path[1:])
            if reverse:
                sequence = reversed(list(sequence))
            for (spec_a, spec_b) in sequence:
                edge_info = self.get_edge(spec_a, spec_b)
                while edge_info is not None:
                    while True:
                        for op in edge_info.operations:
                            constraint = op.get_constraint(sim, spec_a, var_map)
                            while constraint is not None and constraint is not ANYWHERE:
                                return (posture_spec, op, spec_a)
        return (posture_spec, None, None)

    def find_entry_posture_spec(self, sim, path, var_map):
        return self._find_first_constrained_edge(sim, path, var_map)

    def find_exit_posture_spec(self, sim, path, var_map):
        return self._find_first_constrained_edge(sim, path, var_map, reverse=True)

    def get_locations_from_posture(self, sim, posture_spec, var_map, interaction=None, participant_type=None, constrained_edge=None, animation_resolver_fn=None, final_constraint=None):
        body_target = posture_spec[BODY_INDEX][BODY_TARGET_INDEX]
        body_posture_type = posture_spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX]
        body_unconstrained = body_posture_type.unconstrained
        if interaction is not None and interaction.transition is not None:
            interaction.transition.add_relevant_object(body_target)
            interaction.transition.add_relevant_object(interaction.target)
        if not body_unconstrained:
            body_posture = postures.create_posture(body_posture_type, sim, body_target)
            constraint_intersection = body_posture.slot_constraint
            if constraint_intersection is None:
                logger.error('Non-mobile posture with no slot_constraint! This is unexpected and currently unsupported. {}', body_posture)
                return (True, (None, None, body_target))
            constraint_geometry_only = final_constraint.generate_geometry_only_constraint()
            constraint_intersection = constraint_intersection.intersect(constraint_geometry_only)
        else:
            if interaction is None:
                return (True, (None, None, body_target))
            target_posture_state = postures.posture_state.PostureState(sim, None, posture_spec, var_map, invalid_expected=True, body_state_spec_only=True)
            with interaction.override_var_map(sim, var_map):
                interaction_constraint = interaction.apply_posture_state_and_interaction_to_constraint(target_posture_state, final_constraint, sim=sim, target=interaction.target, participant_type=participant_type)
                target_posture_state.add_constraint(self, interaction_constraint)
            constraint_intersection = target_posture_state.constraint_intersection
        if body_unconstrained and (animation_resolver_fn is not None and constrained_edge is not None) and constraint_intersection.valid:
            edge_constraint = constrained_edge.get_constraint(sim, posture_spec, var_map)
            edge_constraint_resolved = edge_constraint.apply_posture_state(target_posture_state, animation_resolver_fn)
            edge_constraint_resolved_geometry_only = edge_constraint_resolved.generate_geometry_only_constraint()
            constraint_intersection = constraint_intersection.intersect(edge_constraint_resolved_geometry_only)
        if not constraint_intersection.valid:
            return (False, (constraint_intersection, None, body_target))
        for constraint in constraint_intersection:
            while constraint.geometry is not None:
                break
        return (True, (None, None, body_target))
        locked_params = frozendict()
        if body_target is not None:
            target_name = posture_spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].target_name
            if target_name is not None:
                anim_overrides = body_target.get_anim_overrides(target_name)
                if anim_overrides is not None:
                    locked_params += anim_overrides.params
        if not body_unconstrained:
            locked_params += body_posture.get_slot_offset_locked_params()
        routing_target = None
        if body_target is not None:
            routing_target = body_target
        elif interaction.target is not None:
            if not posture_spec.requires_carry_target_in_hand and not posture_spec.requires_carry_target_in_slot:
                routing_target = interaction.target
            elif interaction.target.parent is not sim:
                routing_target = interaction.target
        if interaction is not None and interaction.transition is not None:
            interaction.transition.add_relevant_object(routing_target)
        return (False, (constraint_intersection, locked_params, routing_target))

    def _can_transition_between_nodes(self, source_spec, destination_spec):
        if self.get_edge(source_spec, destination_spec, return_none_on_failure=True) is None:
            return False
        return True

    def get_edge(self, spec_a, spec_b, return_none_on_failure=False):
        try:
            key = (spec_a, spec_b)
            edge_info = self._edge_info.get(key)
            if edge_info is None:
                if spec_a[BODY_INDEX][BODY_POSTURE_TYPE_INDEX] != spec_b[BODY_INDEX][BODY_POSTURE_TYPE_INDEX] or spec_a[CARRY_INDEX] != spec_b[CARRY_INDEX]:
                    if not return_none_on_failure:
                        raise KeyError('Edge not found in posture graph: [{:s}] -> [{:s}]'.format(spec_a, spec_b))
                    return
                return EdgeInfo((), None, 0)
            return edge_info
        except:
            pass

    def export(self, filename='posture_graph'):
        graph = self._graph
        edge_info = self._edge_info
        attribute_indexes = {}
        w = xml.etree.ElementTree.TreeBuilder()
        w.start('gexf', {'xmlns': 'http://www.gexf.net/1.2draft', 'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance', 'xsi:schemaLocation': 'http://www.gexf.net/1.2draft/gexf.xsd', 'version': '1.2'})
        w.start('meta', {})
        w.start('creator', {})
        w.data('Electronic Arts')
        w.end('creator')
        w.start('description', {})
        w.data('Tuning topology')
        w.end('description')
        w.end('meta')
        w.start('graph', {'defaultedgetype': 'directed', 'mode': 'static'})
        TYPE_MAPPING = {str: 'string', int: 'float', float: 'float'}
        w.start('attributes', {'class': 'node'})
        attribute_index = 0
        for (attribute_name, attribute_type) in PostureSpec._attribute_definitions:
            attribute_indexes[attribute_name] = str(attribute_index)
            w.start('attribute', {'id': str(attribute_index), 'title': attribute_name.strip('_').title().replace('_', ' '), 'type': TYPE_MAPPING[attribute_type]})
            w.end('attribute')
            attribute_index += 1
        w.end('attributes')
        nodes = set()
        edge_nodes = set()
        w.start('nodes', {})
        for node in sorted(graph.nodes, key=repr):
            nodes.add(hash(node))
            w.start('node', {'id': str(hash(node)), 'label': str(node)})
            w.start('attvalues', {})
            for (attribute_name, attribute_type) in PostureSpec._attribute_definitions:
                attr_value = getattr(node, attribute_name)
                w.start('attvalue', {'for': attribute_indexes[attribute_name], 'value': str(attr_value)})
                w.end('attvalue')
            w.end('attvalues')
            w.end('node')
        w.end('nodes')
        w.start('edges', {})
        edge_id = 0
        for node in sorted(graph.nodes, key=repr):
            for connected_node in sorted(graph.get_successors(node), key=repr):
                edge_nodes.add(hash(node))
                edge_nodes.add(hash(connected_node))
                w.start('edge', {'id': str(edge_id), 'label': ', '.join(str(operation) for operation in edge_info[(node, connected_node)].operations), 'source': str(hash(node)), 'target': str(hash(connected_node))})
                w.end('edge')
                edge_id += 1
        w.end('edges')
        w.end('graph')
        w.end('gexf')
        tree = w.close()

        def indent(elem, level=0):
            i = '\n' + level*'  '
            if len(elem):
                if not elem.text or not elem.text.strip():
                    elem.text = i + '  '
                if not elem.tail or not elem.tail.strip():
                    elem.tail = i
                for elem in elem:
                    indent(elem, level + 1)
                if not elem.tail or not elem.tail.strip():
                    elem.tail = i
            elif level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

        indent(tree)
        file = open('c:\\{}.gexf'.format(filename), 'wb')
        file.write(xml.etree.ElementTree.tostring(tree))
        file.close()
        print('DONE!')

