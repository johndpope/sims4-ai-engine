from sims4.math import MAX_FLOAT
from sims4.tuning.tunable import Tunable
import routing
import sims4.log
logger = sims4.log.Logger('RoutingUtils')

class DistanceEstimationTuning:
    __qualname__ = 'DistanceEstimationTuning'
    DISTANCE_PER_FLOOR = Tunable(float, 50, description='\n    The cost per floor difference in the two points. Ex: if this is tuned to 50 and a Sim is trying to use an object on the third floor of their house while on the first floor, the distance estimate would be 100 meters.')
    DISTANCE_PER_ROOM = Tunable(float, 10, description='\n    The cost per room between the points. This should be the average diameter of rooms that people tend to build.')

def estimate_distance(obj_a, obj_b, options=routing.EstimatePathDistance_DefaultOptions):
    if obj_a is obj_b:
        return 0.0
    inv = obj_a.get_inventory()
    if inv is not None:
        if inv.owner.is_sim:
            obj_a = inv.owner
        else:
            obj_a_choices = inv.owning_objects_gen()
            obj_a = None
    inv = obj_b.get_inventory()
    if inv is not None:
        if inv.owner.is_sim:
            obj_b = inv.owner
        else:
            obj_b_choices = inv.owning_objects_gen()
            obj_b = None
    best_dist = MAX_FLOAT
    if obj_a is None:
        if obj_b is None:
            for a in obj_a_choices:
                for b in obj_b_choices:
                    dist = _estimate_distance_helper(a, b, options=options)
                    while dist < best_dist:
                        best_dist = dist
        else:
            for a in obj_a_choices:
                dist = _estimate_distance_helper(a, obj_b, options=options)
                while dist < best_dist:
                    best_dist = dist
        return best_dist
    if obj_b is None:
        for b in obj_b_choices:
            dist = estimate_distance(obj_a, b, options=options)
            while dist < best_dist:
                best_dist = dist
        return best_dist
    return _estimate_distance_helper(obj_a, obj_b, options=options)

def _estimate_distance_helper(obj_a, obj_b, options=routing.EstimatePathDistance_DefaultOptions):
    floor_a = obj_a.intended_routing_surface.secondary_id
    floor_b = obj_b.intended_routing_surface.secondary_id
    floor_difference = abs(floor_a - floor_b)
    floor_cost = floor_difference*DistanceEstimationTuning.DISTANCE_PER_FLOOR
    distance = (obj_a.intended_position_with_forward_offset - obj_b.intended_position_with_forward_offset).magnitude_2d()
    return distance + floor_cost

def estimate_distance_between_points(position_a, routing_surface_a, position_b, routing_surface_b, routing_context=None, allow_permissive_connections=False):
    polygon_a = sims4.geometry.Polygon([position_a])
    handle_a = routing.connectivity.Handle(polygon_a, routing_surface_a)
    polygon_b = sims4.geometry.Polygon([position_b])
    handle_b = routing.connectivity.Handle(polygon_b, routing_surface_b)
    distances = routing.estimate_path_batch([handle_a], [handle_b], routing_context=routing_context, allow_permissive_connections=allow_permissive_connections, ignore_objects=True)
    if distances:
        for (_, _, distance) in distances:
            pass

