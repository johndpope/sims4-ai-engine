import _geometry
import bisect
import itertools
import random
from sims4.math import vector_cross_2d
from sims4.repr_utils import standard_repr
from sims4.utils import ImmutableType
import enum
import sims4.math
import sims4.random
ANIMATION_SLOT_EPSILON = 0.005
__all__ = ['Polygon']
get_intersection_points = _geometry.find_intersection_points
interval_from_facing_angle = _geometry.interval_from_facing_angle
angular_weighted_average = _geometry.angular_weighted_average

class ObjectQuadTreeQueryFlag(enum.IntFlags, export=False):
    __qualname__ = 'ObjectQuadTreeQueryFlag'
    NONE = 0
    IGNORE_BOUNDS = _geometry.OBJECT_QUAD_TREE_QUERY_FLAG_IGNORE_BOUNDS
    IGNORE_LEVEL = _geometry.OBJECT_QUAD_TREE_QUERY_FLAG_IGNORE_LEVEL
    ONLY_FULLY_CONTAINED = _geometry.OBJECT_QUAD_TREE_QUERY_FLAG_ONLY_FULLY_CONTAINED
    MUST_NOT_CONTAIN_QUERY_BOUNDS = _geometry.OBJECT_QUAD_TREE_QUERY_FLAG_MUST_NOT_CONTAIN_QUERY_BOUNDS
    STOP_AT_FIRST_RESULT = _geometry.OBJECT_QUAD_TREE_QUERY_FLAG_STOP_AT_FIRST_RESULT

ObjectQuadTree = _geometry.ObjectQuadTree
generate_circle_constraint = _geometry.generate_circle_constraint
generate_cone_constraint = _geometry.generate_cone_constraint
QuadTree = _geometry.QuadTree
QtCircle = _geometry.Circle
QtRect = _geometry.Rect
Polygon = _geometry.Polygon
CompoundPolygon = _geometry.CompoundPolygon
AngularInterval = _geometry.AngularInterval
AbsoluteOrientationRange = _geometry.AbsoluteOrientationRange
RelativeFacingRange = _geometry.RelativeFacingRange
RelativeFacingWithCircle = _geometry.RelativeFacingWithCircle
try:
    import _footprints
    PolygonFootprint = _footprints.PolygonFootprint
except ImportError:

    class _footprints:
        __qualname__ = '_footprints'

    class PolygonFootprint:
        __qualname__ = 'PolygonFootprint'

DEFAULT_EPSILON = 0.1

def make_perturb_gen(rand=None, scale=0.1):
    if rand is None:
        rand = random

    def perturb(v):
        dx = rand.uniform(-scale/2, scale/2)
        dz = rand.uniform(-scale/2, scale/2)
        return sims4.math.Vector3(v.x + dx, v.y, v.z + dz)

    perturb_gen = itertools.chain([lambda v: v], itertools.repeat(perturb))
    return perturb_gen

class SpatialQuery:
    __qualname__ = 'SpatialQuery'

    def __init__(self, bounds, quadtrees, types=None):
        self._bounds = bounds
        self._types = types
        self._quadtrees = quadtrees

    def run(self):
        qt_results = []
        results = []
        for qt in self._quadtrees:
            qt_results.extend(qt.query(self._bounds))
        for r in qt_results:
            while self._types is None or issubclass(type(r), self._types):
                results.append(r)
        return results

def build_rectangle_from_two_points_and_radius(p0, p1, r) -> Polygon:
    diff = p1 - p0
    if diff.magnitude_squared() != 0:
        forward = sims4.math.vector_normalize(p1 - p0)*r
    else:
        forward = sims4.math.Vector3(r, 0, 0)
    side = sims4.math.Vector3(-forward.z, forward.y, forward.x)
    vertices = []
    vertices.append(p0 - forward - side)
    vertices.append(p1 + forward - side)
    vertices.append(p1 + forward + side)
    vertices.append(p0 - forward + side)
    return Polygon(vertices)

def random_uniform_point_in_triangle(p, edge_a, edge_b, random=random, epsilon=sims4.math.EPSILON):
    a = random.uniform(epsilon, 1 - epsilon)
    b = random.uniform(epsilon, 1 - epsilon)
    if a + b > 1 - epsilon:
        a = 1 - a
        b = 1 - b
    result = p + edge_a*a + edge_b*b
    return result

def random_uniform_points_in_compound_polygon(compound_polygon, num=1, random=random):
    buckets = {}
    weights = []
    for poly in compound_polygon:
        weights.append((poly.area(), poly))
        buckets[poly] = 0
    for _ in range(num):
        choice = sims4.random.weighted_random_item(weights)
        buckets[choice] += 1
    points = []
    for (poly, poly_num) in buckets.items():
        points.extend(random_uniform_points_in_polygon(poly, poly_num, random=random))
    return points

def random_uniform_points_in_polygon(polygon, num=1, random=random):
    if num <= 0:
        return []
    vertices = list(polygon)
    num_vertices = len(vertices)
    if num_vertices == 0:
        return []
    if num_vertices == 1:
        return [vertices[0]]
    if num_vertices == 2:
        results = []
        for _ in range(num):
            a = random.random()
            results.append(vertices[0]*a + vertices[1]*(1 - a))
        return results
    results = []
    origin = vertices[0]
    if num_vertices == 3:
        edge_a = vertices[1] - origin
        edge_b = vertices[2] - origin
        for _ in range(num):
            results.append(random_uniform_point_in_triangle(origin, edge_a, edge_b, random=random))
        return results
    weights = []
    edges = []
    origin = vertices[0]
    prev = vertices[1] - origin
    total = 0.0
    for v in vertices[2:]:
        edge = v - origin
        area2 = sims4.math.vector_cross(edge, prev).y
        total = total + area2
        weights.append(total)
        edges.append((prev, edge))
        prev = edge
    if total < 0:
        return []
    if total < sims4.math.EPSILON:
        return [vertices[0]]
    results = []
    for _ in range(num):
        pick = random.uniform(0, total)
        index = bisect.bisect(weights, pick)
        (edge_a, edge_b) = edges[index]
        result = random_uniform_point_in_triangle(origin, edge_a, edge_b, random=random)
        results.append(result)
    return results

def test_point_in_compound_polygon(point, compound_polygon):
    single_point_poly = sims4.geometry.CompoundPolygon(sims4.geometry.Polygon([sims4.math.Vector3(point.x, 0, point.z)]))
    intersection = compound_polygon.intersect(single_point_poly)
    return len(intersection) >= 1

def test_point_in_polygon(point, polygon):
    return polygon.contains(point)

def is_concave(a, b, c, epsilon=0):
    (u, v) = (c - b, b - a)
    cross = vector_cross_2d(u, v)
    return cross < epsilon

def is_index_concave(i, points):
    length = len(points)
    a1 = points[(i - 1 + length) % length]
    a2 = points[i]
    a3 = points[(i + 1) % length]
    return is_concave(a1, a2, a3)

def is_polygon_concave(polygon):
    for i in range(len(polygon)):
        while is_index_concave(i, polygon):
            return True
    return False

def inflate_polygon(polygon, amount, centroid=None):
    if centroid is None:
        centroid = polygon.centroid()
    new_vertices = []
    for vertex in polygon:
        if not sims4.math.vector3_almost_equal_2d(vertex, centroid):
            expansion_vector = sims4.math.vector_normalize(vertex - centroid)
            vertex += expansion_vector*amount
        new_vertices.append(vertex)
    return sims4.geometry.Polygon(new_vertices)

def _evaluate_interval(point, restrictions):
    if not restrictions:
        return (True, None)
    interval = None
    for restriction in restrictions:
        restricted_range = restriction.range(point)
        interval = restricted_range if interval is None else interval.intersect(restricted_range)
        while not interval:
            return (False, None)
    return (True, interval)

def _evaluate_restrictions(point, restrictions):
    (compatible, _) = _evaluate_interval(point, restrictions)
    return compatible

def _find_valid_point(a, b, restrictions, epsilon):
    dist_sq = (a - b).magnitude_2d_squared()
    if dist_sq < epsilon*epsilon:
        return a
    c = (a + b)*0.5
    satisfies = _evaluate_restrictions(c, restrictions)
    if satisfies:
        return _find_valid_point(c, b, restrictions, epsilon)
    return _find_valid_point(a, c, restrictions, epsilon)

def _resolve_restrictions(polygon, restrictions, epsilon):
    if not polygon:
        return polygon
    status = []
    for point in polygon:
        status.append((point, _evaluate_restrictions(point, restrictions)))
    vertices = []
    (last, last_satisfies) = status[-1]
    for (p, satisfies) in status:
        if satisfies:
            if last_satisfies:
                vertices.append(p)
            else:
                mid = _find_valid_point(p, last, restrictions, epsilon)
                if not mid == p:
                    vertices.append(mid)
                vertices.append(p)
        elif last_satisfies:
            mid = _find_valid_point(last, p, restrictions, epsilon)
            if not mid == last:
                vertices.append(mid)
        last = p
        last_satisfies = satisfies
    return Polygon(vertices)

class RestrictedPolygon(ImmutableType):
    __qualname__ = 'RestrictedPolygon'

    def __init__(self, polygon, restrictions, epsilon=DEFAULT_EPSILON):
        if polygon is not None:
            sub_polygons = polygon if isinstance(polygon, CompoundPolygon) else (polygon,)
            new_sub_polygons = []
            for sub_polygon in sub_polygons:
                sub_polygon.normalize()
                sub_polygon = _resolve_restrictions(sub_polygon, restrictions, epsilon)
                while sub_polygon:
                    new_sub_polygons.append(sub_polygon)
            self.polygon = CompoundPolygon(new_sub_polygons)
        else:
            self.polygon = None
        self.restrictions = frozenset(restrictions)

    def __repr__(self):
        return standard_repr(self, self.polygon, self.restrictions)

    def __bool__(self):
        if self.polygon is not None:
            if self.polygon:
                return True
            return False
        if self.restrictions:
            return True
        return False

    def intersect(self, other):
        if not isinstance(other, RestrictedPolygon):
            raise AssertionError('Attempting to merge with a non-restricted polygon: {}'.format(other))
        if self.polygon is not None and other.polygon is not None:
            merged_polygon = None
            if len(self.polygon) == 1 and len(other.polygon) == 1:
                poly_mine = self.polygon[0]
                poly_other = other.polygon[0]
                if len(poly_mine) == 1 and len(poly_other) == 1:
                    if sims4.math.vector3_almost_equal_2d(poly_mine[0], poly_other[0], epsilon=ANIMATION_SLOT_EPSILON):
                        merged_polygon = self.polygon
            merged_polygon = self.polygon.intersect(other.polygon)
        else:
            merged_polygon = self.polygon if other.polygon is None else other.polygon
        merged_restrictions = []
        absolute_interval = None
        for restriction in itertools.chain(self.restrictions, other.restrictions):
            if isinstance(restriction, AbsoluteOrientationRange):
                if absolute_interval is None:
                    absolute_interval = restriction.interval
                else:
                    absolute_interval = absolute_interval.intersect(restriction.interval)
                    merged_restrictions.append(restriction)
            else:
                merged_restrictions.append(restriction)
        if absolute_interval is not None:
            if absolute_interval:
                merged_restrictions.insert(0, AbsoluteOrientationRange(absolute_interval))
            else:
                merged_polygon = CompoundPolygon()
                merged_restrictions = []
        return RestrictedPolygon(merged_polygon, merged_restrictions)

    def get_orientation_range(self, point):
        (compatible, interval) = _evaluate_interval(point, self.restrictions)
        if not compatible:
            return (False, None)
        if interval is None:
            return (True, None)
        return (True, interval)

    def get_orientation(self, point, randomness=0):
        (valid, interval) = self.get_orientation_range(point)
        if interval is None:
            return (valid, interval)
        if randomness == 0:
            facing = interval.ideal
        else:
            a = sims4.math.interpolate(interval.ideal, interval.a, randomness)
            b = sims4.math.interpolate(interval.ideal, interval.b, randomness)
            facing = random.uniform(a, b)
        return (True, sims4.math.angle_to_yaw_quaternion(facing))

    def sample(self, num=None, density=None):
        if self.polygon is None:
            return []
        points = []
        for sub_polygon in self.polygon:
            if density is not None:
                num_vertices = len(sub_polygon)
                if num_vertices <= 1:
                    target_num = 1
                elif num_vertices == 2:
                    length = (sub_polygon[0] - sub_polygon[1]).magnitude()
                    target_num = max(1, sims4.math.ceil(length*density))
                else:
                    area = self.polygon.area()
                    target_num = max(1, sims4.math.ceil(area*density))
                num = min(num, target_num) if num else target_num
            elif not num:
                num = 1
            points.extend(random_uniform_points_in_polygon(sub_polygon, num=num))
        results = []
        for p in points:
            (valid, orientation) = self.get_orientation(p, randomness=0.1)
            while valid:
                results.append((p, orientation))
        return results

    def contains_point(self, p):
        return self.polygon is None or test_point_in_compound_polygon(p, self.polygon)

    def test_transform(self, transform):
        return self.test_position_and_orientation(transform.translation, transform.orientation)

    def test_position_and_orientation(self, position, orientation):
        (compatible, interval) = _evaluate_interval(position, self.restrictions)
        if not compatible:
            return False
        if interval is None or interval.angle >= sims4.math.TWO_PI:
            angle_valid = True
        else:
            angle = sims4.math.yaw_quaternion_to_angle(orientation)
            angle_valid = angle in interval
        if angle_valid:
            contains = self.contains_point(position)
            return contains
        return False

