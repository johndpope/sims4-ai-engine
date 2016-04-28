import itertools
import math
import random
from sims4.sim_irq_service import yield_to_irq
from sims4.tuning.tunable import Tunable, TunableAngle
import enum
import objects.system
import routing
import services
import sims4.geometry
import sims4.log
import sims4.math
import sims4.zone_utils
try:
    import _placement
    get_sim_quadtree_for_zone = _placement.get_sim_quadtree_for_zone
    get_placement_footprint_polygon = _placement.get_placement_footprint_polygon
    get_accurate_placement_footprint_polygon = _placement.get_accurate_placement_footprint_polygon
    get_routing_footprint_polygon = _placement.get_routing_footprint_polygon
    validate_sim_location = _placement.validate_sim_location
    validate_los_source_location = _placement.validate_los_source_location
    FGLSearch = _placement.FGLSearch
    FGLResult = _placement.FGLResult
    FGLResultStrategyDefault = _placement.FGLResultStrategyDefault
    FGLSearchStrategyRouting = _placement.FGLSearchStrategyRouting
    FGLSearchStrategyRoutingGoals = _placement.FGLSearchStrategyRoutingGoals
    ScoringFunctionLinear = _placement.ScoringFunctionLinear
    ScoringFunctionRadial = _placement.ScoringFunctionRadial
    ScoringFunctionAngular = _placement.ScoringFunctionAngular
    ScoringFunctionPolygon = _placement.ScoringFunctionPolygon
    NON_SUPPRESSED_FAILURE_GOAL_SCORE = _placement.NON_SUPPRESSED_FAILURE_GOAL_SCORE

    class ItemType(enum.Int, export=False):
        __qualname__ = 'ItemType'
        UNKNOWN = _placement.ITEMTYPE_UNKNOWN
        SIM_POSITION = _placement.ITEMTYPE_SIM_POSITION
        SIM_INTENDED_POSITION = _placement.ITEMTYPE_SIM_INTENDED_POSITION
        ROUTE_GOAL_SUPPRESSOR = _placement.ITEMTYPE_ROUTE_GOAL_SUPPRESSOR
        ROUTE_GOAL_PENALIZER = _placement.ITEMTYPE_ROUTE_GOAL_PENALIZER
        SIM_ROUTING_CONTEXT = _placement.ITEMTYPE_SIM_ROUTING_CONTEXT
        GOAL = _placement.ITEMTYPE_GOAL
        GOAL_SLOT = _placement.ITEMTYPE_GOAL_SLOT

    class FGLSearchType(enum.Int, export=False):
        __qualname__ = 'FGLSearchType'
        NONE = _placement.FGL_SEARCH_TYPE_NONE
        ROUTING = _placement.FGL_SEARCH_TYPE_ROUTING
        ROUTING_GOALS = _placement.FGL_SEARCH_TYPE_ROUTING_GOALS

    class FGLSearchDataType(enum.Int, export=False):
        __qualname__ = 'FGLSearchDataType'
        UNKNOWN = _placement.FGL_SEARCH_DATA_TYPE_UNKNOWN
        START_LOCATION = _placement.FGL_SEARCH_DATA_TYPE_START_LOCATION
        POLYGON = _placement.FGL_SEARCH_DATA_TYPE_POLYGON
        SCORING_FUNCTION = _placement.FGL_SEARCH_DATA_TYPE_SCORING_FUNCTION
        POLYGON_CONSTRAINT = _placement.FGL_SEARCH_DATA_TYPE_POLYGON_CONSTRAINT
        RESTRICTION = _placement.FGL_SEARCH_DATA_TYPE_RESTRICTION
        ROUTING_CONTEXT = _placement.FGL_SEARCH_DATA_TYPE_ROUTING_CONTEXT
        FLAG_CONTAINS_NOWHERE_CONSTRAINT = _placement.FGL_SEARCH_DATA_TYPE_FLAG_CONTAINS_NOWHERE_CONSTRAINT
        FLAG_CONTAINS_ANYWHERE_CONSTRAINT = _placement.FGL_SEARCH_DATA_TYPE_FLAG_CONTAINS_ANYWHERE_CONSTRAINT

    class FGLSearchResult(enum.Int, export=False):
        __qualname__ = 'FGLSearchResult'
        SUCCESS = _placement.FGL_SEARCH_RESULT_SUCCESS
        NOT_INITIALIZED = _placement.FGL_SEARCH_RESULT_NOT_INITIALIZED
        IN_PROGRESS = _placement.FGL_SEARCH_RESULT_IN_PROGRESS
        FAIL_PATHPLANNER_NOT_INITIALIZED = _placement.FGL_SEARCH_RESULT_FAIL_PATHPLANNER_NOT_INITIALIZED
        FAIL_CANNOT_LOCK_PATHPLANNER = _placement.FGL_SEARCH_RESULT_FAIL_CANNOT_LOCK_PATHPLANNER
        FAIL_BUILDBUY_SYSTEM_UNAVAILABLE = _placement.FGL_SEARCH_RESULT_FAIL_BUILDBUY_SYSTEM_UNAVAILABLE
        FAIL_LOT_UNAVAILABLE = _placement.FGL_SEARCH_RESULT_FAIL_LOT_UNAVAILABLE
        FAIL_INVALID_INPUT = _placement.FGL_SEARCH_RESULT_FAIL_INVALID_INPUT
        FAIL_INVALID_INPUT_START_LOCATION = _placement.FGL_SEARCH_RESULT_FAIL_INVALID_INPUT_START_LOCATION
        FAIL_INVALID_INPUT_POLYGON = _placement.FGL_SEARCH_RESULT_FAIL_INVALID_INPUT_POLYGON
        FAIL_INVALID_INPUT_OBJECT_ID = _placement.FGL_SEARCH_RESULT_FAIL_INVALID_INPUT_OBJECT_ID
        FAIL_INCOMPATIBLE_SEARCH_STRATEGY = _placement.FGL_SEARCH_RESULT_FAIL_INCOMPATIBLE_SEARCH_STRATEGY
        FAIL_INCOMPATIBLE_RESULT_STRATEGY = _placement.FGL_SEARCH_RESULT_FAIL_INCOMPATIBLE_RESULT_STRATEGY
        FAIL_NO_RESULTS = _placement.FGL_SEARCH_RESULT_FAIL_NO_RESULTS
        FAIL_UNKNOWN = _placement.FGL_SEARCH_RESULT_FAIL_UNKNOWN

except ImportError:

    class _placement:
        __qualname__ = '_placement'

        @staticmethod
        def test_object_placement(pos, ori, resource_key):
            return False

        @staticmethod
        def test_footprint_intersection():
            return False

    class ScoringFunctionLinear:
        __qualname__ = 'ScoringFunctionLinear'

        def __init__(self, *args, **kwargs):
            pass

    class ScoringFunctionRadial:
        __qualname__ = 'ScoringFunctionRadial'

        def __init__(self, *args, **kwargs):
            pass

    class ScoringFunctionAngular:
        __qualname__ = 'ScoringFunctionAngular'

        def __init__(self, *args, **kwargs):
            pass

    class ScoringFunctionPolygon:
        __qualname__ = 'ScoringFunctionPolygon'

        def __init__(self, *args, **kwargs):
            pass

    @staticmethod
    def get_sim_quadtree_for_zone(*_, **__):
        pass

    @staticmethod
    def get_placement_footprint_polygon(*_, **__):
        pass

    @staticmethod
    def get_accurate_placement_footprint_polygon(*_, **__):
        pass

    @staticmethod
    def get_routing_footprint_polygon(*_, **__):
        pass

    class ItemType(enum.Int):
        __qualname__ = 'ItemType'
        UNKNOWN = 0
        SIM_POSITION = 5
        SIM_INTENDED_POSITION = 6
        GOAL = 7
        GOAL_SLOT = 8
        ROUTE_GOAL_SUPPRESSOR = 30
        ROUTE_GOAL_PENALIZER = 50

    class FGLSearch:
        __qualname__ = 'FGLSearch'

        def __init__(self, *args, **kwargs):
            pass

    class FGLResultStrategyDefault:
        __qualname__ = 'FGLResultStrategyDefault'

        def __init__(self, *args, **kwargs):
            pass

    class FGLSearchStrategyRoutingGoals:
        __qualname__ = 'FGLSearchStrategyRoutingGoals'

        def __init__(self, *args, **kwargs):
            pass

    class FGLSearchType(enum.Int, export=False):
        __qualname__ = 'FGLSearchType'
        UNKNOWN = 0

    class FGLSearchDataType(enum.Int, export=False):
        __qualname__ = 'FGLSearchDataType'
        UNKNOWN = 0

    class FGLSearchResult(enum.Int, export=False):
        __qualname__ = 'FGLSearchResult'
        FAIL_UNKNOWN = 11

    NON_SUPPRESSED_FAILURE_GOAL_SCORE = 0

class FGLTuning:
    __qualname__ = 'FGLTuning'
    MAX_FGL_DISTANCE = Tunable(description='\n        The maximum distance searched by the Find Good Location code.\n        ', tunable_type=float, default=100.0)
    SOCIAL_FGL_HEIGHT_TOLERANCE = Tunable(description='\n        Maximum height tolerance on the terrain we will use for the placement \n        of social jigs.\n        If this value needs to be retuned a GPE, an Animator and Motech should\n        be involved.\n        ', tunable_type=float, default=0.1)

logger = sims4.log.Logger('Placement')

def generate_routing_goals_for_polygon(sim, polygon, polygon_surface, scoring_functions=None, orientation_restrictions=None, object_ids_to_ignore=None, flush_planner=False, sim_location_score_offset=0.0, add_sim_location_as_goal=True, los_reference_pt=None, score_density=2.5, max_points=100, min_score_to_ignore_outer_penalty=2, target_object=2, target_object_id=0, even_coverage_step=3, single_goal_only=False, los_routing_context=None, all_blocking_edges_block_los=False):
    yield_to_irq()
    if los_routing_context is None:
        los_routing_context = sim.routing_context
    return _placement.generate_routing_goals_for_polygon(sim.routing_location, polygon, polygon_surface, scoring_functions, orientation_restrictions, object_ids_to_ignore, sim.routing_context, flush_planner, sim_location_score_offset, add_sim_location_as_goal, los_reference_pt, score_density, max_points, min_score_to_ignore_outer_penalty, target_object_id, even_coverage_step, single_goal_only, los_routing_context, all_blocking_edges_block_los)

class FGLSearchFlag(enum.IntFlags):
    __qualname__ = 'FGLSearchFlag'
    NONE = 0
    USE_RANDOM_WEIGHTING = 1
    USE_RANDOM_ORIENTATION = 2
    ALLOW_TOO_CLOSE_TO_OBSTACLE = 4
    ALLOW_GOALS_IN_SIM_POSITIONS = 8
    ALLOW_GOALS_IN_SIM_INTENDED_POSITIONS = 16
    STAY_IN_SAME_CONNECTIVITY_GROUP = 32
    STAY_IN_CONNECTED_CONNECTIVITY_GROUP = 64
    SHOULD_TEST_BUILDBUY = 128
    SHOULD_TEST_ROUTING = 256
    CALCULATE_RESULT_TERRAIN_HEIGHTS = 512
    DONE_ON_MAX_RESULTS = 1024
    USE_SIM_FOOTPRINT = 2048
    STAY_IN_CURRENT_BLOCK = 4096

FGLSearchFlagsDefault = FGLSearchFlag.STAY_IN_CONNECTED_CONNECTIVITY_GROUP | FGLSearchFlag.SHOULD_TEST_ROUTING | FGLSearchFlag.CALCULATE_RESULT_TERRAIN_HEIGHTS | FGLSearchFlag.DONE_ON_MAX_RESULTS

def _get_random_spiral_vector():
    switch_val = random.randint(0, 3)
    if switch_val == 0:
        return sims4.math.Vector3.X_AXIS()
    if switch_val == 1:
        return sims4.math.Vector3.Z_AXIS()
    if switch_val == 2:
        return -sims4.math.Vector3.X_AXIS()
    return -sims4.math.Vector3.Z_AXIS()

def _get_next_spiral_vector(current_vector):
    if current_vector.x > 0.0:
        return sims4.math.Vector3.Z_AXIS()
    if current_vector.z > 0.0:
        return -sims4.math.Vector3.X_AXIS()
    if current_vector.x < 0.0:
        return -sims4.math.Vector3.Z_AXIS()
    return sims4.math.Vector3.X_AXIS()

class PlacementConstants:
    __qualname__ = 'PlacementConstants'
    rotation_increment = TunableAngle(sims4.math.PI/8, description='The size of the angle-range that sims should use when determining facing constraints.')
    default_random_weight_range = Tunable(float, 0.1, description='Range to adjust goal point final weighting score.  Only used for searches that set the use_random_weighting flag to true and do not pass in a value for the range.')
    polygon_search_density = Tunable(float, 1, description='The number of points per unit of polygon area to test.')
    avoid_sims_radius = Tunable(float, 1, description='How far from Sims (in meters) we try to place objects.')
    max_points_per_search = Tunable(int, 150, description='This is how many individual positions will be checked when trying to find a good location for an object')
    default_spiral_delta = Tunable(float, 0.75, description='This is the distance between points when finding a good location')

def _get_nearby_items(position, level, radius=None, exclude=None, flags=sims4.geometry.ObjectQuadTreeQueryFlag.NONE, query_filter=ItemType.UNKNOWN):
    if radius is None:
        radius = routing.get_default_agent_radius()
    position_2d = sims4.math.Vector2(position.x, position.z)
    bounds = sims4.geometry.QtCircle(position_2d, radius)
    exclude_ids = []
    if exclude:
        for sim in exclude:
            exclude_ids.append(sim.sim_id)
    nearby_items = []
    query = services.sim_quadtree().query(bounds, level, filter=query_filter, flags=flags, exclude=exclude_ids)
    for q in query:
        obj = q[0]
        if exclude and obj in exclude:
            pass
        nearby_items.append(q[0])
    return nearby_items

def get_nearby_sims(position, level, radius=None, exclude=None, stop_at_first_result=False, only_sim_position=False, only_sim_intended_position=False):
    query_filter = (ItemType.SIM_POSITION, ItemType.SIM_INTENDED_POSITION)
    if only_sim_position:
        query_filter = ItemType.SIM_POSITION
    elif only_sim_intended_position:
        query_filter = ItemType.SIM_INTENDED_POSITION
    flags = sims4.geometry.ObjectQuadTreeQueryFlag.NONE
    if stop_at_first_result:
        flags |= sims4.geometry.ObjectQuadTreeQueryFlag.STOP_AT_FIRST_RESULT
    return _get_nearby_items(position=position, level=level, radius=radius, exclude=exclude, flags=flags, query_filter=query_filter)

def get_nearby_route_goal_suppressors(position, level, radius=None, stop_at_first_result=False):
    query_filter = ItemType.ROUTE_GOAL_SUPPRESSOR
    flags = sims4.geometry.ObjectQuadTreeQueryFlag.NONE
    if stop_at_first_result:
        flags |= sims4.geometry.ObjectQuadTreeQueryFlag.STOP_AT_FIRST_RESULT
    return _get_nearby_items(position=position, level=level, radius=radius, exclude=[], flags=flags, query_filter=query_filter)

def search_polygon(polygon, ideal_transform=None):
    raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
    up = sims4.math.UP_AXIS

    def try_rotations(point):
        rotation = 0
        while rotation < sims4.math.TWO_PI:
            orientation = sims4.math.Quaternion.from_axis_angle(rotation, up)
            yield (point, orientation)
            rotation += PlacementConstants.rotation_increment

    points = []
    if polygon is not None:
        for point in sims4.geometry.random_uniform_points_in_compound_polygon(polygon, num=int(PlacementConstants.polygon_search_density*polygon.area())):
            points.append(point)
    if ideal_transform is not None:

        def sort_key(g):
            return (g - ideal_transform.translation).magnitude_2d_squared()

        points.sort(key=sort_key)
    goals = []
    if ideal_transform is not None:
        goals.append((ideal_transform.translation, ideal_transform.orientation))
        for goal in try_rotations(ideal_transform.translation):
            goals.append(goal)
    for point in points:
        for goal in try_rotations(point):
            goals.append(goal)
    for goal in goals:
        yield goal

def search_spiral(position, max_points=None, spiral_delta=None):
    raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
    k_up_vector = sims4.math.UP_AXIS
    k_delta_radians = PlacementConstants.rotation_increment
    max_points = max_points if max_points is not None else PlacementConstants.max_points_per_search
    spiral_delta = spiral_delta if spiral_delta is not None else PlacementConstants.default_spiral_delta
    cur_spiral = sims4.math.Vector3.ZERO()
    next_spiral_arm = _get_random_spiral_vector()
    cur_position = position.translation
    cur_spiral_multiplier = 0.0
    point_count = 0
    while point_count <= max_points:
        num_increments_float = cur_spiral_multiplier/spiral_delta
        num_increments_int = math.ceil(num_increments_float)
        cur_spiral_increment = sims4.math.vector_flatten(cur_spiral)
        if num_increments_float > 0.0:
            cur_spiral_increment = cur_spiral_increment/num_increments_float
        else:
            num_increments_int = 1
        for _ in range(num_increments_int):
            point_count = point_count + 1
            cur_position = cur_position + cur_spiral_increment
            cur_rotation = 0.0
            while cur_rotation < sims4.math.TWO_PI:
                cur_orientation = sims4.math.Quaternion.from_axis_angle(cur_rotation, k_up_vector)
                yield (cur_position, cur_orientation)
                cur_rotation = cur_rotation + k_delta_radians
        next_spiral_arm = _get_next_spiral_vector(next_spiral_arm)
        if next_spiral_arm.x == 0.0:
            cur_spiral_multiplier = cur_spiral_multiplier + 1.0
        cur_spiral = next_spiral_arm*spiral_delta*cur_spiral_multiplier

def find_good_location_with_generator(search_generator, polygons=None, polygon_forwards=None, routing_surface=None, context=None):
    raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
    if routing_surface is None:
        if context is not None:
            routing_surface = context.search_strategy.start_routing_surface
        else:
            zone_id = sims4.zone_utils.get_zone_id()
            routing_surface = routing.SurfaceIdentifier(zone_id, 0, routing.SURFACETYPE_WORLD)
    if polygons is None:
        polygons = []
        polygon_forwards = []
        if context is not None:
            if context.search_strategy.object_id != 0:
                obj = objects.system.find_object(context.search_strategy.object_id)
                p = obj.footprint_polygon
                if p is not None:
                    polygons.append(p)
                    polygon_forwards.append(obj.orientation)
                elif context.search_strategy.object_footprints:
                    for fp in context.search_strategy.object_footprints:
                        p = _placement.get_placement_footprint_polygon(context.search_strategy.start_position, context.search_strategy.start_orientation, context.search_strategy.start_routing_surface, fp)
                        polygons.append(p)
                        polygon_forwards.append(context.search_strategy.start_orientation)
                else:
                    nNumPolygons = context.search_strategy.num_polygons
                    if nNumPolygons == 0:
                        return
                    q = sims4.math.angle_to_yaw_quaternion(0.0)
                    for i in range(nNumPolygons):
                        p = context.search_strategy.get_polygon(i)
                        polygons.append(p)
                        polygon_forwards.append(q)
                    return
            elif context.search_strategy.object_footprints:
                for fp in context.search_strategy.object_footprints:
                    p = _placement.get_placement_footprint_polygon(context.search_strategy.start_position, context.search_strategy.start_orientation, context.search_strategy.start_routing_surface, fp)
                    polygons.append(p)
                    polygon_forwards.append(context.search_strategy.start_orientation)
            else:
                nNumPolygons = context.search_strategy.num_polygons
                if nNumPolygons == 0:
                    return
                q = sims4.math.angle_to_yaw_quaternion(0.0)
                for i in range(nNumPolygons):
                    p = context.search_strategy.get_polygon(i)
                    polygons.append(p)
                    polygon_forwards.append(q)
                return
        else:
            return
    elif polygon_forwards is None:
        polygon_forwards = []
        for polygon in polygons:
            polygon_forwards.append(sims4.math.angle_to_yaw_quaternion(0.0))
    polygon_forward_angles = []
    for q in polygon_forwards:
        polygon_forward_angles.append(sims4.math.yaw_quaternion_to_angle(q))
    if context is not None:
        avoid_sims_radius = context.search_strategy.avoid_sim_radius
        zone = services.current_zone()
        quadtree = zone.sim_quadtree
        if context.search_strategy.allow_goals_in_sim_positions:
            query_filter = ItemType.SIM_INTENDED_POSITION
        elif context.search_strategy.allow_goals_in_sim_intended_positions:
            query_filter = ItemType.SIM_POSITION
        else:
            query_filter = (ItemType.SIM_POSITION, ItemType.SIM_INTENDED_POSITION)
    else:
        avoid_sims_radius = PlacementConstants.avoid_sims_radius
        zone = services.current_zone()
        quadtree = zone.sim_quadtree
        query_filter = ItemType.UNKNOWN
    rejected_position = None
    for (pos, ori) in search_generator:
        if pos == rejected_position:
            pass
        if not routing.test_point_placement_in_navmesh(routing_surface, pos):
            rejected_position = pos
        for (polygon, forward_offset_angle) in itertools.product(polygons, polygon_forward_angles):
            p = sims4.geometry.Polygon(polygon)
            cur_centroid = p.centroid()
            delta_t = pos - cur_centroid
            p.Translate(delta_t)
            new_angle = sims4.math.yaw_quaternion_to_angle(ori)
            delta_r = new_angle - forward_offset_angle
            p.Rotate(delta_r)
            if not routing.test_polygon_placement_in_navmesh(routing_surface, p):
                break
            while quadtree is not None:
                nearby_sims = quadtree.query(bounds=p, level=routing_surface.secondary_id, filter=query_filter, flags=sims4.geometry.ObjectQuadTreeQueryFlag.NONE, additional_radius=avoid_sims_radius)
                if nearby_sims:
                    break
        terrain_instance = services.terrain_service.terrain_object()
        pos.y = terrain_instance.get_routing_surface_height_at(pos.x, pos.z, routing_surface)
        return (pos, ori)

def find_good_location(context):
    if context is None:
        return (None, None)
    context.search.search()
    search_result = FGLSearchResult(context.search.search_result)
    if search_result == FGLSearchResult.SUCCESS:
        temp_list = context.search.get_results()
        fgl_loc = temp_list[0]
        fgl_pos = sims4.math.Vector3(fgl_loc.position.x, fgl_loc.position.y, fgl_loc.position.z)
        if not context.result_strategy.calculate_result_terrain_heights:
            terrain_instance = services.terrain_service.terrain_object()
            fgl_pos.y = terrain_instance.get_routing_surface_height_at(fgl_loc.position.x, fgl_loc.position.z, fgl_loc.routing_surface_id)
        return (fgl_pos, fgl_loc.orientation)
    elif search_result == FGLSearchResult.FAIL_NO_RESULTS:
        logger.debug('FGL search returned 0 results.')
    else:
        logger.warn('FGL search failed: {0}.', str(search_result))
    return (None, None)

class FindGoodLocationContext:
    __qualname__ = 'FindGoodLocationContext'

    def __init__(self, starting_position=None, starting_orientation=None, starting_transform=None, starting_routing_surface=None, starting_location=None, starting_routing_location=None, object_id=None, object_footprints=None, object_polygons=None, routing_context=None, ignored_object_ids=None, max_distance=None, rotation_increment=None, position_increment=None, additional_avoid_sim_radius=0, restrictions=None, scoring_functions=None, offset_distance=None, starting_offset_orientation=None, offset_restrictions=None, random_seed=None, random_range_weighting=None, random_range_orientation=None, max_results=0, max_steps=1, min_score_threshold=None, max_score_threshold=None, height_tolerance=None, search_flags=FGLSearchFlagsDefault):
        if starting_routing_location is None:
            if starting_location is None:
                if starting_routing_surface is None:
                    zone_id = sims4.zone_utils.get_zone_id()
                    starting_routing_surface = routing.SurfaceIdentifier(zone_id, 0, routing.SURFACETYPE_WORLD)
                if starting_transform is None:
                    if starting_orientation is None:
                        starting_orientation = sims4.math.angle_to_yaw_quaternion(0.0)
                    starting_routing_location = routing.Location(starting_position, starting_orientation, starting_routing_surface)
                else:
                    starting_routing_location = routing.Location(starting_transform.translation, starting_transform.orientation, starting_routing_surface)
                    starting_routing_location = routing.Location(starting_location.transform.translation, starting_location.transform.orientation, starting_location.routing_surface)
            else:
                starting_routing_location = routing.Location(starting_location.transform.translation, starting_location.transform.orientation, starting_location.routing_surface)
        self.search_strategy = _placement.FGLSearchStrategyRouting(start_location=starting_routing_location)
        self.result_strategy = _placement.FGLResultStrategyDefault()
        self.search = _placement.FGLSearch(self.search_strategy, self.result_strategy)
        if object_id is not None:
            self.search_strategy.object_id = object_id
        if object_polygons is not None:
            for polygon_wrapper in object_polygons:
                if isinstance(polygon_wrapper, sims4.geometry.Polygon):
                    self.search_strategy.add_polygon(polygon_wrapper, starting_routing_location.routing_surface)
                else:
                    p = polygon_wrapper[0]
                    p_routing_surface = polygon_wrapper[1]
                    if p_routing_surface is None:
                        p_routing_surface = starting_routing_location.routing_surface
                    self.search_strategy.add_polygon(p, p_routing_surface)
        self.object_footprints = object_footprints
        if object_footprints is not None:
            for footprint_wrapper in object_footprints:
                if footprint_wrapper is None:
                    logger.error('None footprint wrapper found during FGL: {}', self)
                if isinstance(footprint_wrapper, sims4.resources.Key):
                    p = _placement.get_placement_footprint_polygon(starting_routing_location.position, starting_routing_location.orientation, starting_routing_location.routing_surface, footprint_wrapper)
                    self.search_strategy.add_polygon(p, starting_routing_location.routing_surface)
                else:
                    fp_key = footprint_wrapper[0]
                    t = footprint_wrapper[1]
                    p_routing_surface = footprint_wrapper[2]
                    if p_routing_surface is None:
                        p_routing_surface = starting_routing_location.routing_surface
                    p = _placement.get_placement_footprint_polygon(t.translation, t.orientation, p_routing_surface, fp_key)
                    self.search_strategy.add_polygon(p, p_routing_surface)
        if routing_context is not None:
            self.search_strategy.routing_context = routing_context
        if ignored_object_ids is not None:
            for obj_id in ignored_object_ids:
                self.search_strategy.add_ignored_object_id(obj_id)
        self.search_strategy.max_distance = FGLTuning.MAX_FGL_DISTANCE if max_distance is None else max_distance
        if rotation_increment is None:
            rotation_increment = PlacementConstants.rotation_increment
        self.search_strategy.rotation_increment = rotation_increment
        if position_increment is None:
            position_increment = 0.3
        self.search_strategy.position_increment = position_increment
        if restrictions is not None:
            for r in restrictions:
                self.search_strategy.add_restriction(r)
        if scoring_functions is not None:
            for sf in scoring_functions:
                self.search_strategy.add_scoring_function(sf)
        if offset_distance is not None and offset_distance > 0:
            self.search_strategy.offset_distance = offset_distance
            if starting_offset_orientation is None:
                starting_offset_orientation = sims4.math.angle_to_yaw_quaternion(0.0)
            self.search_strategy.start_offset_orientation = starting_offset_orientation
            if offset_restrictions is not None:
                while True:
                    for r in offset_restrictions:
                        self.search_strategy.add_offset_restriction(r)
        if additional_avoid_sim_radius > 0:
            self.search_strategy.avoid_sim_radius = additional_avoid_sim_radius
        self.result_strategy.max_results = max_results
        self.search_strategy.max_steps = max_steps
        if height_tolerance is not None:
            self.search_strategy.height_tolerance = height_tolerance
        if min_score_threshold is not None:
            self.result_strategy.min_score_threshold = min_score_threshold
        if max_score_threshold is not None:
            self.result_strategy.max_score_threshold = max_score_threshold
        if search_flags is not None:
            if search_flags & FGLSearchFlag.USE_RANDOM_WEIGHTING:
                self.search_strategy.use_random_weighting = True
                if random_range_weighting is None:
                    random_range_weighting = PlacementConstants.default_random_weight_range
                self.search_strategy.random_range_weighting = random_range_weighting
            if search_flags & FGLSearchFlag.USE_RANDOM_ORIENTATION:
                self.search_strategy.use_random_orientation = True
                if random_range_orientation is None:
                    random_range_orientation = PlacementConstants.rotation_increment
                self.search_strategy.random_range_orientation = random_range_orientation
            if random_seed is not None and search_flags & (FGLSearchFlag.USE_RANDOM_WEIGHTING | FGLSearchFlag.USE_RANDOM_ORIENTATION):
                self.search_strategy.random_seed = random_seed
            self.search_strategy.allow_too_close_to_obstacle = search_flags & FGLSearchFlag.ALLOW_TOO_CLOSE_TO_OBSTACLE
            self.search_strategy.allow_goals_in_sim_positions = search_flags & FGLSearchFlag.ALLOW_GOALS_IN_SIM_POSITIONS
            self.search_strategy.allow_goals_in_sim_intended_positions = search_flags & FGLSearchFlag.ALLOW_GOALS_IN_SIM_INTENDED_POSITIONS
            self.search_strategy.stay_in_same_connectivity_group = search_flags & FGLSearchFlag.STAY_IN_SAME_CONNECTIVITY_GROUP
            self.search_strategy.stay_in_connected_connectivity_group = search_flags & FGLSearchFlag.STAY_IN_CONNECTED_CONNECTIVITY_GROUP
            self.search_strategy.should_test_buildbuy = search_flags & FGLSearchFlag.SHOULD_TEST_BUILDBUY
            self.search_strategy.should_test_routing = search_flags & FGLSearchFlag.SHOULD_TEST_ROUTING
            self.search_strategy.use_sim_footprint = search_flags & FGLSearchFlag.USE_SIM_FOOTPRINT
            self.result_strategy.calculate_result_terrain_heights = search_flags & FGLSearchFlag.CALCULATE_RESULT_TERRAIN_HEIGHTS
            self.result_strategy.done_on_max_results = search_flags & FGLSearchFlag.DONE_ON_MAX_RESULTS
            self.search_strategy.stay_in_current_block = search_flags & FGLSearchFlag.STAY_IN_CURRENT_BLOCK

def footprint_intersection_check(resource_key, offset, orientation, circles, routing_surface=None):
    raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
    if routing_surface is None:
        zone_id = sims4.zone_utils.get_zone_id()
        routing_surface = routing.SurfaceIdentifier(zone_id, 0, routing.SURFACETYPE_WORLD)
    return _placement.test_footprint_intersection(resource_key, offset, orientation, routing_surface, circles)

def add_placement_footprint(owner):
    _placement.add_placement_footprint(owner.id, owner.zone_id, owner.footprint, owner.position, owner.orientation, owner.scale)
    owner.clear_raycast_context()

def remove_placement_footprint(owner):
    _placement.remove_placement_footprint(owner.id, owner.zone_id)

