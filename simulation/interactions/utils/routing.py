from protocolbuffers import DistributorOps_pb2 as protocols
import collections
from element_utils import build_critical_section_with_finally, soft_sleep_forever
from element_utils import build_element
from interactions.context import InteractionSource, QueueInsertStrategy
from interactions.priority import Priority
from interactions.utils.animation import flush_all_animations, TunableAnimationOverrides
from interactions.utils.animation_reference import TunableAnimationReference
from interactions.utils.balloon import TunableBalloon
from interactions.utils.reserve import ReserveObjectHandler
from interactions.utils.routing_constants import TransitionFailureReasons
from placement import FGLTuning
from sims4.tuning.dynamic_enum import DynamicEnum
from sims4.tuning.geometric import TunableDistanceSquared
from sims4.tuning.tunable import Tunable, TunableRange, TunableEnumEntry, TunableSingletonFactory, TunableMapping
from sims4.utils import Result
import autonomy
import build_buy
import clock
import date_and_time
import distributor.ops
import element_utils
import elements
import enum
import gsi_handlers.routing_handlers
import id_generator
import interactions.constraints
import interactions.context
import objects.system
import placement
import routing
import services
import sims4.log
import sims4.math
import sims4.telemetry
import telemetry_helper
logger = sims4.log.Logger('Routing')
TELEMETRY_GROUP_ROUTING = 'ROUT'
TELEMETRY_HOOK_ROUTE_FAILURE = 'RTFL'
TELEMETRY_FIELD_ID = 'idrt'
TELEMETRY_FIELD_POSX = 'posx'
TELEMETRY_FIELD_POSY = 'posy'
TELEMETRY_FIELD_POSZ = 'posz'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_ROUTING)
DEFAULT_WALKSTYLE_OVERRIDE_PRIORITY = 10

class WalkStyle(DynamicEnum, partitioned=True):
    __qualname__ = 'WalkStyle'
    INVALID = 0
    WALK = 1
    WALKSLOW = 2
    RUN = 3
    JOG = 4
    STAIRSUP = 5
    STAIRSDOWN = 6
    RUNSTAIRSUP = 7
    RUNSTAIRSDOWN = 8
    hash_cache = {}

    @classmethod
    def get_hash(cls, walkstyle):
        walkstyle_hash = cls.hash_cache.get(walkstyle)
        if walkstyle_hash is None:
            walkstyle_hash = sims4.hash_util.hash32(walkstyle.name)
            cls.hash_cache[walkstyle] = walkstyle_hash
        return walkstyle_hash

class WalkStyleTuning:
    __qualname__ = 'WalkStyleTuning'
    SHORT_WALK_DIST = Tunable(description='\n        The distance of a route, in meters, below which the Sim will use the\n        slow version of their walkstyle.\n        ', tunable_type=float, default=7.0)
    SHORT_WALK_DIST_OVERRIDE_MAP = TunableMapping(description='\n        Allow certain walkstyles to have a custom override defining the\n        threshold for using the slow walkstyle.\n        ', key_type=TunableEnumEntry(description='\n            The walkstyle that this distance override applies to.\n            ', tunable_type=WalkStyle, default=WalkStyle.INVALID, pack_safe=True), value_type=Tunable(description='\n            The distance of a route, in meters, below which the Sim will use the\n            slow version of their walkstyle.\n            ', tunable_type=float, default=7.0))
    SLOW_WALKSTYLE_MAP = TunableMapping(description='\n        Associate a specific slow version of a walkstyle to walkstyles.\n        ', key_type=TunableEnumEntry(description='\n            The walkstyle that this slow-version applies to. Walk->WalkSlow\n            would be the canonical example.\n            ', tunable_type=WalkStyle, default=WalkStyle.INVALID, pack_safe=True), value_type=TunableEnumEntry(description='\n            The slow version of this walkstyle.\n            ', tunable_type=WalkStyle, default=WalkStyle.WALKSLOW, pack_safe=True))

class RouteTargetType(enum.Int, export=False):
    __qualname__ = 'RouteTargetType'
    NONE = 1
    OBJECT = 2
    PARTS = 3

WalkStyleRequest = collections.namedtuple('WalkStyleRequest', ['priority', 'walkstyle'])

class TunableWalkstyle(TunableSingletonFactory):
    __qualname__ = 'TunableWalkstyle'

    def __init__(self, **kwargs):
        super().__init__(priority=Tunable(float, DEFAULT_WALKSTYLE_OVERRIDE_PRIORITY, description='The priority of the walkstyle. Higher priority walkstyles will take precedence over lower priority. Equal priority will favor recent requests.'), walkstyle=TunableEnumEntry(WalkStyle, WalkStyle.INVALID, description='The walkstyle, from the WalkStyle enumeration, to use for the Sim.'))

    @staticmethod
    def _factory(priority=None, walkstyle=None):
        if priority is None:
            priority = DEFAULT_WALKSTYLE_OVERRIDE_PRIORITY
        if walkstyle is None:
            walkstyle = WalkStyle.WALK
        return WalkStyleRequest(priority, walkstyle)

    FACTORY_TYPE = _factory

class PathNodeAction(enum.Int, export=False):
    __qualname__ = 'PathNodeAction'
    PATH_NODE_WALK_ACTION = 0
    PATH_NODE_PORTAL_WARP_ACTION = 1
    PATH_NODE_PORTAL_WALK_ACTION = 2
    PATH_NODE_PORTAL_ANIMATE_ACTION = 3
    PATH_NODE_UNDEFINED_ACTION = 4294967295

class SlotGoal(routing.Goal):
    __qualname__ = 'SlotGoal'
    __slots__ = ('slot_params', 'containment_transform')

    def __init__(self, *args, containment_transform, slot_params=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.slot_params = slot_params
        self.containment_transform = containment_transform

    def __repr__(self):
        return '<SlotGoal, loc({}), containment({}), orientation({}), weight({}), params({})'.format(self.location.position, self.containment_transform, self.location.orientation, self.weight, self.slot_params)

    def clone(self):
        new_goal = type(self)(self.location, self.containment_transform)
        self._copy_data(new_goal)
        return new_goal

    def _copy_data(self, new_goal):
        super()._copy_data(new_goal)
        new_goal.slot_params = self.slot_params
        new_goal.containment_transform = self.containment_transform
        new_goal.path_id = self.path_id

    @property
    def has_slot_params(self):
        return True

class FollowPath(distributor.ops.ElementDistributionOpMixin, elements.SubclassableGeneratorElement):
    __qualname__ = 'FollowPath'
    ROUTE_GATE_REQUEST = 2
    ROUTE_MINIMUM_TIME_REMAINING_FOR_CANCELLATION = 0.5
    ROUTE_SIM_POSITION_UPDATE_FREQUENCY = 1
    ROUTE_COMPARE_EPSILON = 0.001
    ROUTE_CANCELLATION_APPROX_STOP_ACTION_TIME = 0.5
    DISTANCE_TO_RECHECK_INUSE = Tunable(float, 5.0, description="Distance at which a Sim will start checking their LoS and in use on the object they're routing to and cancel if it's taken.")
    DISTANCE_TO_RECHECK_STAND_RESERVATION = Tunable(float, 3.0, description='Distance at which a Sim will stop if there are still other Sims standing in the way.')
    MIN_TOTAL_ROUTE_DISTANCE_TO_RUN = Tunable(float, 60, description='\n        The minimum distance, in meters, of a total route beyond which a Sim will run when outside.')
    MIN_ROUTE_SEGMENT_DISTANCE_TO_RUN = Tunable(float, 10, description='\n        The minimum distance, in meters, of a segment of a route that is outside beyond which a \n        Sim will run through that route segment. This only matters if the total route is longer\n        than MIN_ROUTE_DISTANCE_TO_RUN.')

    class Action(enum.Int, export=False):
        __qualname__ = 'FollowPath.Action'
        CONTINUE = 0
        CANCEL = 1

    @staticmethod
    def should_follow_path(sim, path):
        final_path_node = path.nodes[-1]
        final_position = sims4.math.Vector3(*final_path_node.position)
        final_orientation = sims4.math.Quaternion(*final_path_node.orientation)
        if sims4.math.vector3_almost_equal_2d(final_position, sim.position, epsilon=FollowPath.ROUTE_COMPARE_EPSILON) and sims4.math.quaternion_almost_equal(final_orientation, sim.orientation, epsilon=FollowPath.ROUTE_COMPARE_EPSILON) and final_path_node.routing_surface_id == sim.routing_surface:
            return False
        return True

    def __init__(self, actor, path, track_override=None, callback_fn=None):
        super().__init__()
        self.actor = actor
        self._transition_controller = actor.transition_controller
        self.path = path
        self.id = id_generator.generate_object_id()
        self.start_time = None
        self.update_walkstyle = False
        self.track_override = track_override
        self._callback_fn = callback_fn
        self._time_to_shave = 0
        self.wait_time = 0
        self.finished = False
        self._time_offset = 0.0
        self._running_nodes = None
        self.canceled = False
        self._sleep_element = None

    @staticmethod
    def _get_block_id_for_node(node):
        zone_id = services.current_zone().id
        block_id = build_buy.get_block_id(zone_id, sims4.math.Vector3(*node.position), node.routing_surface_id.secondary_id)
        return block_id

    @staticmethod
    def _determine_running_nodes(path):
        running_nodes = []
        distance_outside = 0
        outside_nodes = []
        nodes_list = list(path.nodes)
        for (prev, curr) in zip(nodes_list, nodes_list[1:]):
            outside_prev = FollowPath._get_block_id_for_node(prev) == 0 and prev.portal_id == 0
            if outside_prev:
                outside_nodes.append(prev)
                delta = (sims4.math.Vector3(*curr.position) - sims4.math.Vector3(*prev.position)).magnitude_2d()
                distance_outside += delta
            else:
                while outside_nodes:
                    if distance_outside > FollowPath.MIN_ROUTE_SEGMENT_DISTANCE_TO_RUN:
                        running_nodes.extend(outside_nodes)
                    del outside_nodes[:]
                    distance_outside = 0
        if distance_outside > FollowPath.MIN_ROUTE_SEGMENT_DISTANCE_TO_RUN:
            running_nodes.extend(outside_nodes)
        distance_total = path.length()
        if distance_total > FollowPath.MIN_TOTAL_ROUTE_DISTANCE_TO_RUN:
            return running_nodes
        return ()

    def _current_time(self):
        return (services.time_service().sim_now - self.start_time).in_real_world_seconds()

    def _time_left(self, current_time):
        return clock.interval_in_real_seconds(self.path.nodes[-1].time - current_time - self._time_to_shave)

    def _next_update_interval(self, current_time):
        update_interval = clock.interval_in_real_seconds(self.ROUTE_SIM_POSITION_UPDATE_FREQUENCY)
        return update_interval

    def attach(self, *args, **kwargs):
        if hasattr(self.actor, 'on_follow_path'):
            self.actor.on_follow_path(self, True)
        super().attach(*args, **kwargs)

    def detach(self, *args, **kwargs):
        if hasattr(self.actor, 'on_follow_path'):
            self.actor.on_follow_path(self, False)
        super().detach(*args, **kwargs)
        self.canceled = True

    def _get_walkstyle(self, actor, path):
        walkstyle = self.actor.walkstyle
        short_walk_distance = WalkStyleTuning.SHORT_WALK_DIST_OVERRIDE_MAP.get(walkstyle, WalkStyleTuning.SHORT_WALK_DIST)
        if path.length() < short_walk_distance:
            slow_style = WalkStyleTuning.SLOW_WALKSTYLE_MAP.get(walkstyle, WalkStyle.WALKSLOW)
            walkstyle = slow_style
        return walkstyle

    def _apply_rules_to_node(self, node, walkstyle, actor):
        if node.routing_surface_id.type == routing.SURFACETYPE_OBJECT:
            obj = objects.system.find_object(node.routing_surface_id.primary_id)
            if obj is not None:
                walkstyle = obj.get_surface_walkstyle()
        elif (node.position, node.orientation) in [(running_node.position, running_node.orientation) for running_node in self._running_nodes]:
            walkstyle = WalkStyle.JOG
        node.walkstyle = WalkStyle.get_hash(walkstyle)

    def _apply_walkstyle(self, path, actor):
        walkstyle = self._get_walkstyle(actor, path)
        origin_q = (float(actor.orientation.x), float(actor.orientation.y), float(actor.orientation.z), float(actor.orientation.w))
        origin_t = (float(actor.position.x), float(actor.position.y), float(actor.position.z))
        age = actor.age
        gender = actor.gender
        if actor.allow_running_for_long_distance_routes:
            self._running_nodes = self._determine_running_nodes(path)
        else:
            self._running_nodes = []
        for n in path.nodes:
            self._apply_rules_to_node(n, walkstyle, actor)
        current_ticks = int(services.time_service().sim_now)
        path.nodes.apply_initial_timing(origin_q, origin_t, walkstyle, age, gender, current_ticks, services.current_zone_id())

    def _update_walkstyle(self, path, actor, time_offset):
        walkstyle = self._get_walkstyle(actor, path)
        age = actor.age
        gender = actor.gender
        for n in path.nodes:
            while n.time >= time_offset:
                self._apply_rules_to_node(n, walkstyle, actor)
        path.nodes.update_timing(walkstyle, age, gender, time_offset, services.current_zone_id())

    def is_traversing_portal(self):
        current_time = self._current_time()
        index = self.actor.current_path.node_at_time(current_time).index - 1
        if index < 0:
            return False
        return self.actor.current_path.nodes[index].portal_object_id != 0

    def get_next_non_portal_node(self):
        current_time = self._current_time()
        index = self.actor.current_path.node_at_time(current_time).index - 1
        if index < 0:
            return
        if self.actor.current_path.nodes[index].portal_object_id == 0:
            return
        while index < len(self.actor.current_path.nodes) - 1:
            index += 1
            node = self.actor.current_path.nodes[index]
            while node.portal_object_id == 0:
                return node

    def is_traversing_invalid_portal(self):
        current_time = self._current_time()
        index = self.actor.current_path.node_at_time(current_time).index - 1
        if index < 0:
            return False
        node = self.actor.current_path.nodes[index]
        portal_object_id = node.portal_object_id
        if not portal_object_id:
            return False
        portal_object = objects.system.find_object(portal_object_id)
        if portal_object is not None:
            portal_id = node.portal_id
            if any(portal_id in portal_pair for portal_pair in portal_object.portals):
                return False
        return True

    def get_remaining_distance(self, seconds_left):
        path_nodes = self.path.nodes
        total_distance_left = 0
        if seconds_left <= 0:
            return 0
        for index in range(len(path_nodes) - 1, 0, -1):
            cur_node = path_nodes[index]
            prev_node = path_nodes[index - 1]
            segment_time = cur_node.time - prev_node.time
            position_diff = sims4.math.Vector2(cur_node.position[0] - prev_node.position[0], cur_node.position[2] - prev_node.position[2])
            segment_distance = position_diff.magnitude()
            if seconds_left > segment_time:
                total_distance_left += segment_distance
                seconds_left -= segment_time
            else:
                finished_segment_time = segment_time - seconds_left
                if finished_segment_time > 0:
                    ratio = seconds_left/segment_time
                    total_distance_left += segment_distance*ratio
                else:
                    total_distance_left += segment_distance
                return total_distance_left
        return total_distance_left

    def _hide_held_props(self):
        for si in self.actor.si_state:
            si.animation_context.set_all_prop_visibility(False, held_only=True)

    def _run_gen(self, timeline):
        self._hide_held_props()
        if self.actor.should_route_instantly:
            final_path_node = self.path.nodes[-1]
            final_position = sims4.math.Vector3(*final_path_node.position)
            final_orientation = sims4.math.Quaternion(*final_path_node.orientation)
            routing_surface = final_path_node.routing_surface_id
            final_position.y = services.terrain_service.terrain_object().get_routing_surface_height_at(final_position.x, final_position.z, routing_surface)
            self.actor.location = sims4.math.Location(sims4.math.Transform(final_position, final_orientation), routing_surface)
            return True
        accumulator = services.current_zone().arb_accumulator_service
        if accumulator.MAXIMUM_TIME_DEBT > 0:
            time_debt = accumulator.get_time_debt((self.actor,))
            self._time_to_shave = accumulator.get_shave_time_given_duration_and_debt(self.path.duration(), time_debt)
            self.wait_time = time_debt
            new_time_debt = time_debt + self._time_to_shave
        else:
            time_debt = 0
            self._time_to_shave = 0
            self.wait_time = 0
            new_time_debt = 0
        try:
            if self.canceled:
                return False
            if self.path and self.path.nodes:
                try:
                    final_path_node = self.path.nodes[-1]
                    final_position = sims4.math.Vector3(*final_path_node.position)
                    final_orientation = sims4.math.Quaternion(*final_path_node.orientation)
                    self.actor.current_path = self.path
                    self._apply_walkstyle(self.path, self.actor)
                    accumulator = services.current_zone().arb_accumulator_service
                    self.start_time = services.time_service().sim_now + clock.interval_in_real_seconds(time_debt)
                    if self.actor.primitives:
                        for primitive in tuple(self.actor.primitives):
                            while isinstance(primitive, FollowPath):
                                primitive.detach(self.actor)
                    self.attach(self.actor)
                    self._sleep_element = elements.SoftSleepElement(self._next_update_interval(self._current_time()))
                    yield element_utils.run_child(timeline, self._sleep_element)
                    self._sleep_element = None
                    while True:
                        current_time = self._current_time()
                        if self._callback_fn is not None:
                            time_left = self._time_left(current_time).in_real_world_seconds()
                            distance_left = self.get_remaining_distance(time_left)
                            route_action = self._callback_fn(distance_left)
                            if route_action == FollowPath.Action.CANCEL:
                                self.canceled = True
                        if self.canceled or self.finished:
                            break
                        elif self.update_walkstyle:
                            time_offset = current_time + 0.5
                            self._update_walkstyle(self.path, self.actor, time_offset)
                            self.send_updated_msg()
                            self.update_walkstyle = False
                        else:
                            self.update_routing_location(current_time)
                        if current_time > self.path.nodes[-1].time*2.0 + 5.0:
                            break
                        next_interval = self._next_update_interval(current_time)
                        self._sleep_element = elements.SoftSleepElement(next_interval)
                        yield element_utils.run_child(timeline, self._sleep_element)
                        self._sleep_element = None
                    if self.canceled:
                        cancellation_info = self.choose_cancellation_time()
                        if cancellation_info:
                            self.send_canceled_msg(cancellation_info[0])
                            location = self.actor.location
                            location.routing_surface = self.path.node_at_time(cancellation_info[0]).routing_surface_id
                            translation = sims4.math.Vector3(*self.path.position_at_time(cancellation_info[0]))
                            translation.y = services.terrain_service.terrain_object().get_routing_surface_height_at(translation.x, translation.z, location.routing_surface)
                            orientation = sims4.math.Quaternion(*self.path.orientation_at_time(cancellation_info[0]))
                            location.transform = sims4.math.Transform(translation, orientation)
                            self.path.add_location_to_quad_tree(location)
                            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_ROUTE_FAILURE, sim=self.actor) as hook:
                                hook.write_int(TELEMETRY_FIELD_ID, self.id)
                                hook.write_float(TELEMETRY_FIELD_POSX, translation.x)
                                hook.write_float(TELEMETRY_FIELD_POSY, translation.y)
                                hook.write_float(TELEMETRY_FIELD_POSZ, translation.z)
                            self.actor.location = location
                            while True:
                                if self.finished:
                                    break
                                current_time = self._current_time()
                                if current_time > self.path.nodes[-1].time*2.0 + 5.0:
                                    break
                                next_interval = self._next_update_interval(current_time)
                                self._sleep_element = elements.SoftSleepElement(next_interval)
                                yield element_utils.run_child(timeline, self._sleep_element)
                                self._sleep_element = None
                            return False
                        with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_ROUTE_FAILURE) as hook:
                            hook.write_int(TELEMETRY_FIELD_ID, self.id)
                    location = self.actor.location
                    location.routing_surface = final_path_node.routing_surface_id
                    final_position.y = services.terrain_service.terrain_object().get_routing_surface_height_at(final_position.x, final_position.z, location.routing_surface)
                    location.transform = sims4.math.Transform(final_position, final_orientation)
                    self.actor.location = location
                finally:
                    self.detach(self.actor)
                    self.actor.current_path = None
                    self._sleep_element = None
            return True
        finally:
            if accumulator.MAXIMUM_TIME_DEBT > 0:
                accumulator.set_time_debt((self.actor,), new_time_debt)

    def _soft_stop(self):
        self.canceled = True
        if self._sleep_element is not None:
            self._sleep_element.trigger_soft_stop()
        return True

    def update_routing_location(self, current_time=None):
        if current_time is None:
            current_time = self._current_time()
        location = self.actor.location
        location.routing_surface = self.path.node_at_time(current_time).routing_surface_id
        translation = sims4.math.Vector3(*self.path.position_at_time(current_time))
        translation.y = services.terrain_service.terrain_object().get_routing_surface_height_at(location.transform.translation.x, location.transform.translation.z, location.routing_surface)
        orientation = sims4.math.Quaternion(*self.path.orientation_at_time(current_time))
        location.transform = sims4.math.Transform(translation, orientation)
        self.actor.set_location_without_distribution(location)

    def choose_cancellation_time(self):
        path_duration = self.path.duration()
        if path_duration > 0:
            server_delay = (services.time_service().sim_timeline.future - services.time_service().sim_now).in_real_world_seconds()
            min_time = self.ROUTE_MINIMUM_TIME_REMAINING_FOR_CANCELLATION + server_delay
            current_time = (services.time_service().sim_now - self.start_time).in_real_world_seconds() - self._time_offset
            while path_duration - current_time > min_time:
                cancellation_time = current_time + min_time
                cancel_node = self.path.node_at_time(cancellation_time)
                if cancel_node is None:
                    return
                if cancel_node.index > 0:
                    cancel_node = self.path.nodes[cancel_node.index - 1]
                while cancel_node.action != PathNodeAction.PATH_NODE_WALK_ACTION:
                    cancel_node = self.path.nodes[cancel_node.index + 1]
                    cancellation_time = cancel_node.time
                routing_surface_id = cancel_node.routing_surface_id
                position = sims4.math.Vector3(*self.path.position_at_time(cancellation_time))
                nearby = placement.get_nearby_sims(position, routing_surface_id.secondary_id, radius=routing.get_default_agent_radius(), exclude=[self.actor], stop_at_first_result=True, only_sim_position=False, only_sim_intended_position=False)
                if len(nearby) == 0 and routing.test_point_placement_in_navmesh(routing_surface_id, position):
                    return (cancellation_time, self.ROUTE_CANCELLATION_APPROX_STOP_ACTION_TIME + (cancellation_time - current_time))
                current_time = cancellation_time

    def write(self, msg):
        if self.actor.should_route_instantly:
            return
        try:
            msg_src = distributor.ops.create_route_msg_src(self.id, self.actor, self.path, self.start_time, self.wait_time, track_override=self.track_override)
            msg.type = protocols.Operation.FOLLOW_ROUTE
            msg.data = msg_src.SerializeToString()
        except Exception as e:
            logger.error('_FollowPath.write: {0}', e)

    def send_canceled_msg(self, time):
        cancel_op = distributor.ops.RouteCancel(self.id, time)
        distributor.ops.record(self.actor, cancel_op)

    def send_updated_msg(self):
        op = distributor.ops.RouteUpdate(self.id, self.actor, self.path, self.start_time, self.wait_time, track_override=self.track_override)
        distributor.ops.record(self.actor, op)

    def request_walkstyle_update(self):
        self.update_walkstyle = True
        if self._sleep_element is not None:
            self._sleep_element.trigger_soft_stop()

    def route_finished(self, path_id):
        if self.id == path_id:
            self.finished = True
            self._sleep_element.trigger_soft_stop()
        else:
            logger.debug("Routing: route_finished current path id doesn't match, ignoring. This can happen when the client is running way behind the server or the route was cancelled")

    def route_time_update(self, path_id, current_client_time):
        if self.id == path_id:
            self._time_offset = self._current_time() - current_client_time
        else:
            logger.debug("Routing: route_time_update current path id doesn't match, ignoring.")

class PlanRoute(elements.SubclassableGeneratorElement):
    __qualname__ = 'PlanRoute'

    def __init__(self, route, sim, reserve_final_location=True, is_failure_route=False):
        super().__init__()
        self.route = route
        self.path = routing.Path(sim, route)
        self.sim = sim
        self.reserve_final_location = reserve_final_location
        self._is_failure_route = is_failure_route

    @classmethod
    def shortname(cls):
        return 'PlanRoute'

    def _run_gen(self, timeline):
        if self.path.status == routing.Path.PLANSTATUS_NONE:
            yield self.generate_path(timeline)
        self.route.context.path_goals_id = 0
        if self.path.status == routing.Path.PLANSTATUS_READY:
            if self.reserve_final_location:
                self.path.add_destination_to_quad_tree()
            return True
        return False

    def generate_path(self, timeline):
        start_time = services.time_service().sim_now
        ticks = 0
        try:
            self.path.status = routing.Path.PLANSTATUS_PLANNING
            self.path.nodes.clear_route_data()
            if not self.route.goals:
                self.path.status = routing.Path.PLANSTATUS_FAILED
            else:
                for goal in self.route.goals:
                    self.path.add_goal(goal)
                for origin in self.route.origins:
                    self.path.add_start(origin)
                self.sim.on_plan_path(self.route.goals, True)
                if self.path.nodes.make_path() is True:

                    def is_planning_done():
                        nonlocal ticks
                        ticks += 1
                        return not self.path.nodes.plan_in_progress

                    yield element_utils.run_child(timeline, elements.BusyWaitElement(soft_sleep_forever(), is_planning_done))
                    self.path.nodes.finalize(self._is_failure_route)
                else:
                    self.path.status = routing.Path.PLANSTATUS_FAILED
                new_route = routing.Route(self.route.origin, self.route.goals, additional_origins=self.route.origins, routing_context=self.route.context)
                new_route.path.copy(self.route.path)
                new_path = routing.Path(self.path.sim, new_route)
                new_path.status = self.path.status
                new_path._start_ids = self.path._start_ids
                new_path._goal_ids = self.path._goal_ids
                result_path = new_path
                if len(new_path.nodes) > 0:
                    start_index = 0
                    current_index = 0
                    for n in self.path.nodes:
                        if n.portal_object_id != 0:
                            portal_object = services.object_manager(services.current_zone_id()).get(n.portal_object_id)
                            if portal_object is not None and portal_object.split_path_on_portal():
                                new_path.nodes.clip_nodes(start_index, current_index)
                                new_route = routing.Route(self.route.origin, self.route.goals, additional_origins=self.route.origins, routing_context=self.route.context)
                                new_route.path.copy(self.route.path)
                                next_path = routing.Path(self.path.sim, new_route)
                                next_path.status = self.path.status
                                next_path._start_ids = self.path._start_ids
                                next_path._goal_ids = self.path._goal_ids
                                new_path.next_path = next_path
                                new_path.portal = portal_object
                                new_path = next_path
                                start_index = current_index + 1
                        current_index = current_index + 1
                    new_path.nodes.clip_nodes(start_index, current_index - 1)
                self.route = result_path.route
                self.path = result_path
                self.sim.on_plan_path(self.route.goals, False)
        except Exception:
            logger.exception('Exception in generate_path')
            self.path.status = routing.Path.PLANSTATUS_FAILED
            self.sim.on_plan_path(self.route.goals, False)
        if self.path.status == routing.Path.PLANSTATUS_PLANNING:
            self.path.set_status(routing.Path.PLANSTATUS_READY)
        else:
            self.path.set_status(routing.Path.PLANSTATUS_FAILED)
        if gsi_handlers.routing_handlers.archiver.enabled:
            gsi_handlers.routing_handlers.archive_plan(self.sim, self.path, ticks, (services.time_service().sim_now - start_time).in_real_world_seconds())

def with_walkstyle(sim, walkstyle, uid, sequence=None, priority=DEFAULT_WALKSTYLE_OVERRIDE_PRIORITY):

    def request_walkstyle(element):
        sim.request_walkstyle(WalkStyleRequest(priority, walkstyle), uid)

    def unrequest_walkstyle(element):
        sim.remove_walkstyle(uid)

    return build_critical_section_with_finally(request_walkstyle, sequence, unrequest_walkstyle)

class FollowSim:
    __qualname__ = 'FollowSim'
    RETRIES = Tunable(int, 3, description='The maximum number of route attempts the following sim will make.')
    MIN_DISTANCE_SQ = TunableDistanceSquared(5, description='The minimum distance between the two sims to consider the route a success.')
    TARGET_DISTANCE = TunableRange(float, 1.0, minimum=0, description='The distance to which we attempt to route when following another Sim.')

    @staticmethod
    def sim_within_range_of_target(sim, target):
        distance_sq = (target.position - sim.position).magnitude_squared()
        if distance_sq < FollowSim.MIN_DISTANCE_SQ:
            return True
        return False

class ShooTunables:
    __qualname__ = 'ShooTunables'
    shoo_animation = TunableAnimationReference(description='Shoo Animation', callback=None)

def shoo(interaction):
    return (ShooTunables.shoo_animation(interaction, sequence=()), flush_all_animations)

class RouteFailureTunables:
    __qualname__ = 'RouteFailureTunables'
    route_fail_animation = TunableAnimationReference(description='\n                               Route Failure Animation                     \n                               Note: Route Failure Balloons are handled specially and not tuned here. See: route_fail_overrides_object, route_fail_overrides_build\n                               ', callback=None)
    route_fail_overrides_object = TunableAnimationOverrides()
    route_fail_overrides_reservation = TunableAnimationOverrides()
    route_fail_overrides_build = TunableAnimationOverrides()
    route_fail_overrides_no_dest_node = TunableAnimationOverrides()
    route_fail_overrides_no_path_found = TunableAnimationOverrides()
    route_fail_overrides_no_valid_intersection = TunableAnimationOverrides()
    route_fail_overrides_no_goals_generated = TunableAnimationOverrides()
    route_fail_overrides_no_connectivity = TunableAnimationOverrides()
    route_fail_overrides_path_plan_fail = TunableAnimationOverrides()

ROUTE_FAILURE_OVERRIDE_MAP = None

def route_failure(sim, interaction, failure_reason, failure_object_id):
    global ROUTE_FAILURE_OVERRIDE_MAP
    if not sim.should_route_fail:
        return
    overrides = None
    if ROUTE_FAILURE_OVERRIDE_MAP is None:
        ROUTE_FAILURE_OVERRIDE_MAP = {TransitionFailureReasons.BLOCKING_OBJECT: RouteFailureTunables.route_fail_overrides_object, TransitionFailureReasons.RESERVATION: RouteFailureTunables.route_fail_overrides_reservation, TransitionFailureReasons.BUILD_BUY: RouteFailureTunables.route_fail_overrides_build, TransitionFailureReasons.NO_DESTINATION_NODE: RouteFailureTunables.route_fail_overrides_no_dest_node, TransitionFailureReasons.NO_PATH_FOUND: RouteFailureTunables.route_fail_overrides_no_path_found, TransitionFailureReasons.NO_VALID_INTERSECTION: RouteFailureTunables.route_fail_overrides_no_valid_intersection, TransitionFailureReasons.NO_GOALS_GENERATED: RouteFailureTunables.route_fail_overrides_no_goals_generated, TransitionFailureReasons.NO_CONNECTIVITY_TO_GOALS: RouteFailureTunables.route_fail_overrides_no_connectivity, TransitionFailureReasons.PATH_PLAN_FAILED: RouteFailureTunables.route_fail_overrides_path_plan_fail}
    if failure_reason is not None and failure_reason in ROUTE_FAILURE_OVERRIDE_MAP:
        overrides = ROUTE_FAILURE_OVERRIDE_MAP[failure_reason]()
        if failure_object_id is not None:
            fail_obj = services.object_manager().get(failure_object_id)
            if fail_obj is not None:
                overrides.balloon_target_override = fail_obj
    route_fail_anim = RouteFailureTunables.route_fail_animation(sim.posture.source_interaction, overrides=overrides, sequence=())
    supported_postures = route_fail_anim.get_supported_postures()
    if supported_postures:
        return build_element((route_fail_anim, flush_all_animations))
    balloon_requests = TunableBalloon.get_balloon_requests(interaction, route_fail_anim.overrides)
    return balloon_requests

def get_route_element_for_path(sim, path, lockout_target=None, handle_failure=False, callback_fn=None):

    def route_gen(timeline):
        result = yield do_route(timeline, sim, path, lockout_target, handle_failure, callback_fn=callback_fn)
        return result

    return route_gen

def do_route(timeline, sim, path, lockout_target, handle_failure, callback_fn=None):

    def _route(timeline):
        origin_location = sim.routing_location
        if path.status == routing.Path.PLANSTATUS_READY:
            if not FollowPath.should_follow_path(sim, path):
                if callback_fn is not None:
                    result = callback_fn(0)
                    if result == FollowPath.Action.CANCEL:
                        return False
                return True
            distance_left = path.length()
            if callback_fn is not None and distance_left < FollowPath.DISTANCE_TO_RECHECK_INUSE:
                route_action = callback_fn(distance_left)
                if route_action == FollowPath.Action.CANCEL:
                    return False
            if sim.position != origin_location.position:
                logger.error("Route-to-position has outdated starting location. Sim's position ({}) is {:0.2f}m from the original starting position ({})", sim.position, (sim.position - origin_location.position).magnitude(), origin_location.position)
            follow_element = FollowPath(sim, path, callback_fn=callback_fn)
            if path.is_route_fail():
                if handle_failure:
                    yield element_utils.run_child(timeline, follow_element)
                if lockout_target is not None:
                    sim.add_lockout(lockout_target, ReserveObjectHandler.LOCKOUT_TIME)
                return Result.ROUTE_FAILED
            critical_element = elements.WithFinallyElement(follow_element, lambda _: path.remove_from_quad_tree())
            result = yield element_utils.run_child(timeline, critical_element)
            return result
        if lockout_target is not None:
            sim.add_lockout(lockout_target, ReserveObjectHandler.LOCKOUT_TIME)
        return Result.ROUTE_PLAN_FAILED

    result = yield _route(timeline)
    return result

def get_route_to_position_goals(position, routing_surface, orientation=None):
    goal_location = routing.Location(position, orientation, routing_surface)
    return [routing.Goal(goal_location)]

class Wander:
    __qualname__ = 'Wander'
    BACKOFF_DISCOURAGE_RADIUS = Tunable(float, 2, description="The distance from the sims's current position that we would like them to move beyond.")

def _create_backoff_constraint(sim, radius=None, center=None):
    import animation.posture_manifest_constants
    if radius is None:
        radius = Wander.BACKOFF_DISCOURAGE_RADIUS
    if center is None:
        center = sim.position
    circle_constraint = interactions.constraints.Circle(center, radius, sim.routing_surface, ideal_radius=radius, force_route=True)
    total_constraint = circle_constraint.intersect(animation.posture_manifest_constants.STAND_AT_NONE_CONSTRAINT)
    return total_constraint

def push_backoff(sim, source=InteractionSource.SCRIPT, radius=None, center=None):
    context = interactions.context.InteractionContext(sim, source, Priority.Low, insert_strategy=QueueInsertStrategy.NEXT)
    backoff_constraint = _create_backoff_constraint(sim, radius=radius, center=center)
    from interactions.utils.satisfy_constraint_interaction import SatisfyConstraintSuperInteraction
    sim.push_super_affordance(SatisfyConstraintSuperInteraction, None, context, constraint_to_satisfy=backoff_constraint, name_override='Satisfy[backoff]')

def get_fgl_context_for_jig_definition(jig_definition, sim, target_sim=None, ignore_sim=True, max_dist=None, height_tolerance=None):
    max_facing_angle_diff = sims4.math.PI*2
    if max_dist is None:
        max_dist = FGLTuning.MAX_FGL_DISTANCE
    if target_sim is None:
        relative_sim = sim
        if ignore_sim:
            ignored_object_ids = (sim.id,)
        else:
            ignored_object_ids = None
        reference_transform = sim.intended_transform
    else:
        relative_sim = target_sim
        ignored_object_ids = (sim.id, target_sim.id)
        reference_transform = target_sim.intended_transform
    additional_interaction_jig_fgl_distance = relative_sim.posture_state.body.additional_interaction_jig_fgl_distance
    starting_position = relative_sim.intended_position
    if additional_interaction_jig_fgl_distance != 0:
        starting_position += relative_sim.intended_forward*additional_interaction_jig_fgl_distance
    starting_location = routing.Location(starting_position, relative_sim.intended_transform.orientation, relative_sim.intended_routing_surface)
    facing_angle = sims4.math.yaw_quaternion_to_angle(reference_transform.orientation)
    fgl_context = placement.FindGoodLocationContext(starting_location=starting_location, routing_context=sim.routing_context, ignored_object_ids=ignored_object_ids, max_distance=max_dist, height_tolerance=height_tolerance, restrictions=(sims4.geometry.AbsoluteOrientationRange(min_angle=facing_angle - max_facing_angle_diff, max_angle=facing_angle + max_facing_angle_diff, ideal_angle=facing_angle, weight=1.0),), offset_restrictions=(sims4.geometry.RelativeFacingRange(reference_transform.translation, max_facing_angle_diff*2),), scoring_functions=(placement.ScoringFunctionRadial(reference_transform.translation, 0, 0, max_dist),), object_footprints=(jig_definition.get_footprint(0),), max_results=1, max_steps=10, search_flags=placement.FGLSearchFlag.STAY_IN_CONNECTED_CONNECTIVITY_GROUP | placement.FGLSearchFlag.SHOULD_TEST_ROUTING | placement.FGLSearchFlag.ALLOW_TOO_CLOSE_TO_OBSTACLE | placement.FGLSearchFlag.CALCULATE_RESULT_TERRAIN_HEIGHTS)
    return fgl_context

def get_two_person_transforms_for_jig(jig_definition, jig_transform, routing_surface, sim_index, target_index):
    object_slots = jig_definition.get_slots_resource(0)
    slot_transform_sim = object_slots.get_slot_transform_by_index(sims4.ObjectSlots.SLOT_ROUTING, sim_index)
    sim_transform = sims4.math.Transform.concatenate(slot_transform_sim, jig_transform)
    slot_transform_target = object_slots.get_slot_transform_by_index(sims4.ObjectSlots.SLOT_ROUTING, target_index)
    target_transform = sims4.math.Transform.concatenate(slot_transform_target, jig_transform)
    return (sim_transform, target_transform, routing_surface)

def fgl_and_get_two_person_transforms_for_jig(jig_definition, sim, sim_index, target_sim, target_index, constraint_polygon=None):
    if constraint_polygon is None:
        key = (sim.id, sim_index, target_sim.id, target_index)
        data = target_sim.two_person_social_transforms.get(key)
        return data
    else:
        key = None
    fgl_context = get_fgl_context_for_jig_definition(jig_definition, sim, target_sim, height_tolerance=FGLTuning.SOCIAL_FGL_HEIGHT_TOLERANCE)
    if constraint_polygon is not None:
        if isinstance(constraint_polygon, sims4.geometry.CompoundPolygon):
            for cp in constraint_polygon:
                fgl_context.search_strategy.add_scoring_function(placement.ScoringFunctionPolygon(cp))
        else:
            fgl_context.search_strategy.add_scoring_function(placement.ScoringFunctionPolygon(constraint_polygon))
    (position, orientation) = placement.find_good_location(fgl_context)
    if position is None or orientation is None:
        result = (None, None, None)
    else:
        jig_transform = sims4.math.Transform(position, orientation)
        result = get_two_person_transforms_for_jig(jig_definition, jig_transform, target_sim.routing_surface, sim_index, target_index)
    if key is not None:
        target_sim.two_person_social_transforms[key] = result
    return result

def handle_transition_failure(sim, source_interaction_target, transition_interaction, failure_reason=None, failure_object_id=None):
    if not transition_interaction.visible:
        return
    if not transition_interaction.route_fail_on_transition_fail:
        return
    if transition_interaction.is_adjustment_interaction():
        return

    def _do_transition_failure(timeline):
        if source_interaction_target is not None:
            sim.add_lockout(source_interaction_target, autonomy.autonomy_modes.AutonomyMode.LOCKOUT_TIME)
        if transition_interaction is None:
            return
        if transition_interaction.context.source == InteractionSource.AUTONOMY:
            return
        yield element_utils.run_child(timeline, route_failure(sim, transition_interaction, failure_reason, failure_object_id))

    return _do_transition_failure

