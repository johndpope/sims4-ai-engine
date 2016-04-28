from _math import Quaternion
import weakref
import build_buy
import enum
import placement
import services
import sims4.reload
try:
    import _pathing
except ImportError:

    def get_default_traversal_cost(*_, **__):
        return 1.0

    def get_default_discouragement_cost(*_, **__):
        return 100.0

    def get_default_obstacle_cost(*_, **__):
        return 10000.0

    def get_min_agent_radius(*_, **__):
        return 0.123

    def get_default_agent_radius(*_, **__):
        return 0.123

    def get_default_agent_extra_clearance_multiplier(*_, **__):
        return 2.0

    def set_default_agent_extra_clearance_multiplier(*_, **__):
        pass

    def get_world_size(*_, **__):
        pass

    def get_world_bounds(*_, **__):
        pass

    def is_position_in_world_bounds(*_, **__):
        return False

    def is_position_in_surface_bounds(*_, **__):
        return False

    def get_world_center(*_, **__):
        pass

    def invalidate_navmesh(*_, **__):
        pass

    def add_footprint(*_, **__):
        pass

    def remove_footprint(*_, **__):
        pass

    def invalidate_footprint(*_, **__):
        pass

    def get_footprint_polys(*_, **__):
        pass

    def add_portal(*_, **__):
        pass

    def remove_portal(*_, **__):
        pass

    def get_stair_portals(*_, **__):
        pass

    def test_connectivity_batch(*_, **__):
        pass

    def estimate_path_batch(*_, **__):
        pass

    def test_connectivity_permissions_for_handle(*_, **__):
        return False

    def test_point_placement_in_navmesh(*_, **__):
        return False

    def test_polygon_placement_in_navmesh(*_, **__):
        return False

    def get_portals_in_connectivity_path(*_, **__):
        pass

    def estimate_path_portals(*_, **__):
        return (-1, 0)

    def estimate_path_distance(*_, **__):
        return (-1.0, 0)

    def ray_test(*_, **__):
        return False

    RAYCAST_HIT_TYPE_NONE = 0
    RAYCAST_HIT_TYPE_IMPASSABLE = 1
    RAYCAST_HIT_TYPE_LOS_IMPASSABLE = 2

    def ray_test_verbose(*_, **__):
        return RAYCAST_HIT_TYPE_NONE

    def planner_build_id(*_, **__):
        return 0

    def add_fence(*_, **__):
        pass

    def get_last_fence(*_, **__):
        return 0

    def flush_planner(*_, **__):
        pass

    class LocationBase:
        __qualname__ = 'LocationBase'

        def __init__(self, position, orientation=None, routing_surface=None):
            pass

    class SurfaceIdentifier:
        __qualname__ = 'SurfaceIdentifier'

        def __init__(self, primary_id, secondary_id=None, surface_type=None):
            pass

        @property
        def primary_id(self):
            return 0

        @property
        def secondary_id(self):
            return 0

        @property
        def type(self):
            return 0

    class Destination:
        __qualname__ = 'Destination'

        def __init__(self, loc, weight=1.0, tag=0):
            self._loc = loc
            self._weight = weight
            self._tag = tag

        @property
        def location(self):
            return self._loc

        @property
        def weight(self):
            return self._weight

        @property
        def tag(self):
            return self._tag

        @property
        def has_slot_params(self):
            return False

    SURFACETYPE_UNKNOWN = 0
    SURFACETYPE_WORLD = 1
    SURFACETYPE_OBJECT = 2

    class RoutingContext:
        __qualname__ = 'RoutingContext'

        def __init__(self):
            pass

        @property
        def object_id(self):
            return 0

        @object_id.setter
        def object_id(self, value):
            pass

    class PathPlanContext:
        __qualname__ = 'PathPlanContext'

        def __init__(self):
            pass

        @property
        def agent_id(self):
            return 0

        @agent_id.setter
        def agent_id(self, value):
            pass

    PATH_RESULT_UNKNOWN = 0
    PATH_RESULT_SUCCESS_TRIVIAL = 1
    PATH_RESULT_SUCCESS_LOCAL = 2
    PATH_RESULT_SUCCESS_GLOBAL = 3
    PATH_RESULT_FAIL_NO_GOALS = 4
    PATH_RESULT_FAIL_INVALID_START_SURFACE = 5
    PATH_RESULT_FAIL_INVALID_START_POINT = 6
    PATH_RESULT_FAIL_START_POINT_IN_IMPASSABLE_REGION = 7
    PATH_RESULT_FAIL_TOO_MANY_CYCLES = 8
    PATH_RESULT_FAIL_PARTIAL_PATH = 9
    PATH_RESULT_FAIL_NO_PATH = 10
    FAIL_PATH_TYPE_UNKNOWN = 0
    FAIL_PATH_TYPE_OBJECT_BLOCKING = 1
    FAIL_PATH_TYPE_BUILD_BLOCKING = 2
    FAIL_PATH_TYPE_UNKNOWN_BLOCKING = 3
    GOAL_STATUS_PENDING = 0
    GOAL_STATUS_INVALID_SURFACE = 1
    GOAL_STATUS_INVALID_POINT = 2
    GOAL_STATUS_DUPLICATE_GOAL = 4
    GOAL_STATUS_CONNECTIVITY_GROUP_UNREACHABLE = 8
    GOAL_STATUS_COMPONENT_DIFFERENT = 16
    GOAL_STATUS_NOTEVALUATED = 32
    GOAL_STATUS_LOWER_SCORE = 64
    GOAL_STATUS_IMPASSABLE = 128
    GOAL_STATUS_BLOCKED = 256
    GOAL_STATUS_REJECTED_UNKNOWN = 512
    GOAL_STATUS_SUCCESS = 1024
    GOAL_STATUS_SUCCESS_TRIVIAL = 2048
    GOAL_STATUS_SUCCESS_LOCAL = 4096
    FOOTPRINT_KEY_ON_LOT = 1
    FOOTPRINT_KEY_OFF_LOT = 2

    class EstimatePathFlag(enum.IntFlags, export=False):
        __qualname__ = 'EstimatePathFlag'
        NONE = 0
        RETURN_DISTANCE_ON_FAIL = 1
        IGNORE_CONNECTIVITY_HANDLES = 2
        RETURN_DISTANCE_FROM_FIRST_CONNECTION_FOUND = 4
        ALWAYS_RETURN_MINIMUM_DISTANCE = 8
        ZERO_DISTANCE_IS_OPTIMAL = 16
        NO_NEAREST_VALID_POINT_SEARCH = 32

    class EstimatePathResults(enum.IntFlags, export=False):
        __qualname__ = 'EstimatePathResults'
        NONE = 0
        SUCCESS = 1
        PATHPLANNER_NOT_INITIALIZED = 2
        START_SURFACE_INVALID = 4
        START_LOCATION_INVALID = 8
        START_LOCATION_BLOCKED = 16
        ALL_START_HANDLES_BLOCKED = 32
        GOAL_SURFACE_INVALID = 64
        GOAL_LOCATION_INVALID = 128
        GOAL_LOCATION_BLOCKED = 256
        ALL_GOAL_HANDLES_BLOCKED = 512
        NO_CONNECTIVITY = 1024
        UNKNOWN_ERROR = 2048

get_default_traversal_cost = _pathing.get_default_traversal_cost
get_default_discouragement_cost = _pathing.get_default_discouragement_cost
get_default_obstacle_cost = _pathing.get_default_obstacle_cost
get_min_agent_radius = _pathing.get_min_agent_radius
get_default_agent_radius = _pathing.get_default_agent_radius
get_default_agent_extra_clearance_multiplier = _pathing.get_default_agent_extra_clearance_multiplier
set_default_agent_extra_clearance_multiplier = _pathing.set_default_agent_extra_clearance_multiplier
get_world_size = _pathing.get_world_size
get_world_bounds = _pathing.get_world_bounds
is_position_in_world_bounds = _pathing.is_position_in_world_bounds
is_position_in_surface_bounds = _pathing.is_position_in_surface_bounds
get_world_center = _pathing.get_world_center
invalidate_navmesh = _pathing.invalidate_navmesh
add_footprint = _pathing.add_footprint
remove_footprint = _pathing.remove_footprint
invalidate_footprint = _pathing.invalidate_footprint
get_footprint_polys = _pathing.get_footprint_polys
add_portal = _pathing.add_portal
remove_portal = _pathing.remove_portal
get_stair_portals = _pathing.get_stair_portals
test_connectivity_pt_pt = _pathing.test_connectivity_pt_pt
test_point_placement_in_navmesh = _pathing.test_point_placement_in_navmesh
test_polygon_placement_in_navmesh = _pathing.test_polygon_placement_in_navmesh
ray_test = _pathing.ray_test
get_portals_in_connectivity_path = _pathing.get_portals_in_connectivity_path
RAYCAST_HIT_TYPE_NONE = _pathing.RAYCAST_HIT_TYPE_NONE
RAYCAST_HIT_TYPE_IMPASSABLE = _pathing.RAYCAST_HIT_TYPE_IMPASSABLE
RAYCAST_HIT_TYPE_LOS_IMPASSABLE = _pathing.RAYCAST_HIT_TYPE_LOS_IMPASSABLE
ray_test_verbose = _pathing.ray_test_verbose
get_walkstyle_info = _pathing.get_walkstyle_info
planner_build_id = _pathing.planner_build_id
planner_build_record = _pathing.planner_build_record
flush_planner = _pathing.flush_planner
add_fence = _pathing.add_fence
get_last_fence = _pathing.get_last_fence
LocationBase = _pathing.Location
SurfaceIdentifier = _pathing.SurfaceIdentifier
SURFACETYPE_UNKNOWN = _pathing.SURFACETYPE_UNKNOWN
SURFACETYPE_WORLD = _pathing.SURFACETYPE_WORLD
SURFACETYPE_OBJECT = _pathing.SURFACETYPE_OBJECT
path_wrapper = _pathing.PathNodeList
Destination = _pathing.Destination
RoutingContext = _pathing.RoutingContext
PathPlanContext = _pathing.PathPlanContext

def clone_path_plan_context(source_context):
    path_plan_context = PathPlanContext()
    path_plan_context.agent_extra_clearance_multiplier = source_context.agent_extra_clearance_multiplier
    path_plan_context.agent_id = source_context.agent_id
    path_plan_context.agent_name = source_context.agent_name
    path_plan_context.agent_radius = source_context.agent_radius
    path_plan_context.debug_trace = source_context.debug_trace
    path_plan_context.footprint_key = source_context.footprint_key
    path_plan_context.impassable_goals_auto_fail = source_context.impassable_goals_auto_fail
    path_plan_context.path_goals_id = source_context.path_goals_id
    return path_plan_context

def test_connectivity_batch(src, dst, routing_context=None, compute_cost=False, flush_planner=False, allow_permissive_connections=False, ignore_objects=False):
    return _pathing.test_connectivity_batch(src, dst, routing_context, compute_cost, flush_planner, allow_permissive_connections, ignore_objects)

def estimate_path_batch(src, dst, routing_context=None, flush_planner=False, allow_permissive_connections=False, ignore_objects=False):
    return _pathing.estimate_path_batch(src, dst, routing_context, flush_planner, allow_permissive_connections, ignore_objects)

def test_connectivity_permissions_for_handle(handle, routing_context=None, flush_planner=False):
    return _pathing.test_connectivity_permissions_for_handle(handle, routing_context, flush_planner)

PATH_RESULT_UNKNOWN = _pathing.PATH_RESULT_UNKNOWN
PATH_RESULT_SUCCESS_TRIVIAL = _pathing.PATH_RESULT_SUCCESS_TRIVIAL
PATH_RESULT_SUCCESS_LOCAL = _pathing.PATH_RESULT_SUCCESS_LOCAL
PATH_RESULT_SUCCESS_GLOBAL = _pathing.PATH_RESULT_SUCCESS_GLOBAL
PATH_RESULT_FAIL_NO_GOALS = _pathing.PATH_RESULT_FAIL_NO_GOALS
PATH_RESULT_FAIL_INVALID_START_SURFACE = _pathing.PATH_RESULT_FAIL_INVALID_START_SURFACE
PATH_RESULT_FAIL_INVALID_START_POINT = _pathing.PATH_RESULT_FAIL_INVALID_START_POINT
PATH_RESULT_FAIL_START_POINT_IN_IMPASSABLE_REGION = _pathing.PATH_RESULT_FAIL_START_POINT_IN_IMPASSABLE_REGION
PATH_RESULT_FAIL_TOO_MANY_CYCLES = _pathing.PATH_RESULT_FAIL_TOO_MANY_CYCLES
PATH_RESULT_FAIL_PARTIAL_PATH = _pathing.PATH_RESULT_FAIL_PARTIAL_PATH
PATH_RESULT_FAIL_NO_PATH = _pathing.PATH_RESULT_FAIL_NO_PATH
FAIL_PATH_TYPE_UNKNOWN = _pathing.FAIL_PATH_TYPE_UNKNOWN
FAIL_PATH_TYPE_OBJECT_BLOCKING = _pathing.FAIL_PATH_TYPE_OBJECT_BLOCKING
FAIL_PATH_TYPE_BUILD_BLOCKING = _pathing.FAIL_PATH_TYPE_BUILD_BLOCKING
FAIL_PATH_TYPE_UNKNOWN_BLOCKING = _pathing.FAIL_PATH_TYPE_UNKNOWN_BLOCKING
GOAL_STATUS_PENDING = _pathing.GOAL_STATUS_PENDING
GOAL_STATUS_INVALID_SURFACE = _pathing.GOAL_STATUS_INVALID_SURFACE
GOAL_STATUS_INVALID_POINT = _pathing.GOAL_STATUS_INVALID_POINT
GOAL_STATUS_DUPLICATE_GOAL = _pathing.GOAL_STATUS_DUPLICATE_GOAL
GOAL_STATUS_CONNECTIVITY_GROUP_UNREACHABLE = _pathing.GOAL_STATUS_CONNECTIVITY_GROUP_UNREACHABLE
GOAL_STATUS_COMPONENT_DIFFERENT = _pathing.GOAL_STATUS_COMPONENT_DIFFERENT
GOAL_STATUS_NOTEVALUATED = _pathing.GOAL_STATUS_NOTEVALUATED
GOAL_STATUS_LOWER_SCORE = _pathing.GOAL_STATUS_LOWER_SCORE
GOAL_STATUS_IMPASSABLE = _pathing.GOAL_STATUS_IMPASSABLE
GOAL_STATUS_BLOCKED = _pathing.GOAL_STATUS_BLOCKED
GOAL_STATUS_REJECTED_UNKNOWN = _pathing.GOAL_STATUS_REJECTED_UNKNOWN
GOAL_STATUS_SUCCESS = _pathing.GOAL_STATUS_SUCCESS
GOAL_STATUS_SUCCESS_TRIVIAL = _pathing.GOAL_STATUS_SUCCESS_TRIVIAL
GOAL_STATUS_SUCCESS_LOCAL = _pathing.GOAL_STATUS_SUCCESS_LOCAL
FOOTPRINT_KEY_ON_LOT = _pathing.FOOTPRINT_KEY_ON_LOT
FOOTPRINT_KEY_OFF_LOT = _pathing.FOOTPRINT_KEY_OFF_LOT

class EstimatePathFlag(enum.IntFlags, export=False):
    __qualname__ = 'EstimatePathFlag'
    NONE = 0
    RETURN_DISTANCE_ON_FAIL = _pathing.ESTIMATE_PATH_OPTION_RETURN_DISTANCE_ON_FAIL
    IGNORE_CONNECTIVITY_HANDLES = _pathing.ESTIMATE_PATH_OPTION_IGNORE_CONNECTIVITY_HANDLES
    RETURN_DISTANCE_FROM_FIRST_CONNECTION_FOUND = _pathing.ESTIMATE_PATH_OPTION_RETURN_DISTANCE_FROM_FIRST_CONNECTION_FOUND
    ALWAYS_RETURN_MINIMUM_DISTANCE = _pathing.ESTIMATE_PATH_OPTION_ALWAYS_RETURN_MINIMUM_DISTANCE
    ZERO_DISTANCE_IS_OPTIMAL = _pathing.ESTIMATE_PATH_OPTION_ZERO_DISTANCE_IS_OPTIMAL
    NO_NEAREST_VALID_POINT_SEARCH = _pathing.ESTIMATE_PATH_OPTION_NO_NEAREST_VALID_POINT_SEARCH

class EstimatePathResults(enum.IntFlags, export=False):
    __qualname__ = 'EstimatePathResults'
    NONE = 0
    SUCCESS = _pathing.ESTIMATE_PATH_RESULT_SUCCESS
    PATHPLANNER_NOT_INITIALIZED = _pathing.ESTIMATE_PATH_RESULT_PATHPLANNER_NOT_INITIALIZED
    START_SURFACE_INVALID = _pathing.ESTIMATE_PATH_RESULT_START_SURFACE_INVALID
    START_LOCATION_INVALID = _pathing.ESTIMATE_PATH_RESULT_START_LOCATION_INVALID
    START_LOCATION_BLOCKED = _pathing.ESTIMATE_PATH_RESULT_START_LOCATION_BLOCKED
    ALL_START_HANDLES_BLOCKED = _pathing.ESTIMATE_PATH_RESULT_ALL_START_HANDLES_BLOCKED
    GOAL_SURFACE_INVALID = _pathing.ESTIMATE_PATH_RESULT_GOAL_SURFACE_INVALID
    GOAL_LOCATION_INVALID = _pathing.ESTIMATE_PATH_RESULT_GOAL_LOCATION_INVALID
    GOAL_LOCATION_BLOCKED = _pathing.ESTIMATE_PATH_RESULT_GOAL_LOCATION_BLOCKED
    ALL_GOAL_HANDLES_BLOCKED = _pathing.ESTIMATE_PATH_RESULT_ALL_GOAL_HANDLES_BLOCKED
    NO_CONNECTIVITY = _pathing.ESTIMATE_PATH_RESULT_NO_CONNECTIVITY
    UNKNOWN_ERROR = _pathing.ESTIMATE_PATH_RESULT_UNKNOWN_ERROR

EstimatePathDistance_DefaultOptions = EstimatePathFlag.NONE

def get_sim_extra_clearance_distance():
    extra_clearance_mult = get_default_agent_extra_clearance_multiplier()
    if extra_clearance_mult > 0.0:
        agent_radius = get_default_agent_radius()
        return agent_radius*extra_clearance_mult
    return 0.0

class Location(LocationBase):
    __qualname__ = 'Location'

    def __init__(self, position, orientation=None, routing_surface=None):
        if orientation is None:
            orientation = Quaternion.ZERO()
        if routing_surface is None:
            import sims4.log
            sims4.log.callstack('Routing', 'Attempting to create a location without a routing_surface.', level=sims4.log.LEVEL_ERROR)
            routing_surface = SurfaceIdentifier(0, 0)
        super().__init__(position, orientation, routing_surface)

class Goal(Destination):
    __qualname__ = 'Goal'
    __slots__ = ('requires_los_check', 'path_id', 'connectivity_handle', 'path_cost')

    def __init__(self, location, cost=1.0, tag=0, group=0, requires_los_check=True, path_id=0, connectivity_handle=None):
        super().__init__(location, cost, tag, group)
        self.requires_los_check = requires_los_check
        self.path_id = path_id
        self.connectivity_handle = connectivity_handle
        self.path_cost = None

    def clone(self):
        new_goal = type(self)(self.location)
        self._copy_data(new_goal)
        return new_goal

    def _copy_data(self, new_goal):
        new_goal.location = self.location
        new_goal.connectivity_handle = self.connectivity_handle
        new_goal.cost = self.cost
        new_goal.tag = self.tag
        new_goal.group = self.group
        new_goal.requires_los_check = self.requires_los_check

class Path:
    __qualname__ = 'Path'
    PLANSTATUS_NONE = 0
    PLANSTATUS_PLANNING = 1
    PLANSTATUS_READY = 2
    PLANSTATUS_FAILED = 3

    def __init__(self, sim, route):
        if route is None:
            raise ValueError('Path has no route object')
        self.status = Path.PLANSTATUS_NONE
        self.route = route
        self.nodes = route.path
        self._start_ids = {}
        self._goal_ids = {}
        self._sim_ref = weakref.ref(sim)
        self.next_path = None
        self._portal_object_ref = None

    def __len__(self):
        return len(self.nodes)

    def __getitem__(self, key):
        return self.nodes[key]

    def __setitem__(self, value):
        raise RuntimeError('Only route generation should be trying to modify the nodes of a path.')

    def __delitem__(self, key):
        raise RuntimeError('Only route generation should be trying to modify the nodes of a path.')

    def __iter__(self):
        return iter(self.nodes)

    def __contains__(self, item):
        return item in self.nodes

    @property
    def sim(self):
        if self._sim_ref is not None:
            return self._sim_ref()

    @property
    def selected_start(self):
        (start_id, _) = self.nodes.selected_start_tag_tuple
        return self._start_ids[start_id]

    @property
    def selected_goal(self):
        (goal_id, _) = self.nodes.selected_tag_tuple
        return self._goal_ids[goal_id]

    @property
    def final_location(self):
        if not self.nodes:
            return
        final_path_node = self.nodes[-1]
        location = Location(sims4.math.Vector3(*final_path_node.position), sims4.math.Quaternion(*final_path_node.orientation), final_path_node.routing_surface_id)
        return location

    @property
    def portal(self):
        if self._portal_object_ref is not None:
            return self._portal_object_ref()

    @portal.setter
    def portal(self, value):
        self._portal_object_ref = weakref.ref(value) if value is not None else None

    def set_status(self, status):
        cur_path = self
        while cur_path is not None:
            cur_path.status = status
            cur_path = cur_path.next_path

    def add_start(self, start):
        self._start_ids[id(start)] = start
        self.nodes.add_start(start.location, start.cost, (id(start), 0))

    def add_goal(self, goal):
        self._goal_ids[id(goal)] = goal
        self.nodes.add_goal(goal.location, goal.cost, (id(goal), 0), goal.group)

    def duration(self):
        if self.status == self.PLANSTATUS_READY:
            return self.nodes.duration
        return -1

    def length(self):
        if self.status == self.PLANSTATUS_READY:
            return self.nodes.length
        return -1

    def position_at_time(self, time):
        if self.nodes:
            return self.nodes.position_at_time(time)

    def orientation_at_time(self, time):
        if self.nodes:
            return self.nodes.orientation_at_time(time)

    def node_at_time(self, time):
        if self.nodes:
            return self.nodes.node_at_time(time)

    def is_route_fail(self):
        if not self.nodes:
            return True
        if not self.nodes.plan_success:
            return True
        return False

    def add_destination_to_quad_tree(self):
        if not self.nodes:
            return
        final_location = self.final_location
        if final_location is not None:
            self.add_location_to_quad_tree(final_location)

    def add_location_to_quad_tree(self, location):
        if location is None:
            return
        sim = self.sim
        self.intended_location = location
        if location.routing_surface == sim.routing_surface and sims4.math.vector3_almost_equal_2d(sim.position, location.transform.translation) and sims4.math.quaternion_almost_equal(sim.orientation, location.transform.orientation):
            return
        pos_2d = sims4.math.Vector2(location.transform.translation.x, location.transform.translation.z)
        geo = sims4.geometry.QtCircle(pos_2d, sim.quadtree_radius)
        services.sim_quadtree().insert(sim, sim.sim_id, placement.ItemType.SIM_INTENDED_POSITION, geo, location.routing_surface.secondary_id, False, 0)

    def remove_from_quad_tree(self):
        sim = self.sim
        services.sim_quadtree().remove(sim.sim_id, placement.ItemType.SIM_INTENDED_POSITION, 0)

class Route:
    __qualname__ = 'Route'
    __slots__ = ('goals', 'options', 'path', 'origins')

    def __init__(self, origin, goals, additional_origins=(), routing_context=None, options=None):
        self.path = path_wrapper(routing_context)
        self.origin = origin
        self.origins = additional_origins
        self.goals = goals
        self.options = options

    @property
    def context(self):
        return self.path.context

    @context.setter
    def context(self, value):
        self.path.context = value

    @property
    def origin(self):
        return self.path.origin

    @origin.setter
    def origin(self, value):
        self.path.origin = value

def c_api_navmesh_updated_callback(navmesh_build_id):
    pass

def c_api_navmesh_fence_callback(fence_id):
    zone = services.current_zone()
    if zone.is_zone_running:
        build_buy.buildbuy_session_end(zone.id)
    from objects.components.spawner_component import SpawnerInitializerSingleton
    if SpawnerInitializerSingleton is not None:
        SpawnerInitializerSingleton.spawner_spawn_objects_post_nav_mesh_load(zone.id)

