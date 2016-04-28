import collections
import contextlib
import math
from sims4.tuning.geometric import TunableCurve
from sims4.tuning.tunable import Tunable, TunableRange
import accumulator
import interactions.constraints
import interactions.utils.routing
import placement
import sims4.geometry
import sims4.log
import sims4.math
__all__ = ['SocialGeometry', 'make']
logger = sims4.log.Logger('SocialGeometry')

class SocialGeometry:
    __qualname__ = 'SocialGeometry'
    __slots__ = ('focus', 'field', '_area', 'transform')
    GROUP_DISTANCE_CURVE = TunableCurve(description='\n    A curve defining the score for standing a given distance away from other\n    Sims in the social group.\n    \n    Higher values (on the y-axis) encourage standing at that distance (on the\n    x-axis) away from other Sims.')
    NON_GROUP_DISTANCE_CURVE = TunableCurve(description='\n    A curve defining the score for standing a given distance away from other\n    Sims *not* in the social group.\n    \n    Higher values (on the y-axis) encourage standing at that distance (on the\n     x-axis) away from other Sims.')
    GROUP_ANGLE_CURVE = TunableCurve(description='\n    A curve defining the score for two Sims with this facing angle (in radians).\n    \n    An angle of zero (on the x-axis) means a Sims is facing another Sim, while\n    PI means a Sim is facing away.  Higher values (on the y-axis) encourage\n    that angular facing.')
    OVERLAP_SCORE_MULTIPLIER = Tunable(float, 1.0, description='p\n    Higher values raise the importance of the "personal space" component of the\n    social scoring function.')
    DEFAULT_SCORE_CUTOFF = TunableRange(float, 0.8, minimum=0, maximum=1.0, description='\n    Transforms scoring below cutoff * max_score are filtered out when joining / adjusting position')
    NON_OVERLAPPING_SCORE_MULTIPLIER = Tunable(float, 0.05, description='Minimum score multiplier for non-overlapping fields')
    SCORE_STRENGTH_MULTIPLIER = Tunable(float, 3, description='\n    Values > 1 will cause Sims to go further out of their way to be in perfect social arrangements.\n    This helps overcome distance attenuation for social adjustment since we want Sims to care more\n    about where they are positioned than how far they have to go to improve that position.')
    SCORE_OFFSET_FOR_CURRENT_POSITION = Tunable(float, 0.5, description="\n    An additional score to apply to points that are virtually identical to the\n    Sim's current position if the Sim already has an entry in the geometry.\n    \n    Larger numbers provide more friction that will prevent Sims from moving\n    away from their current position unless the score of the new point makes\n    moving worthwhile.")

    def __init__(self, focus, field, transform):
        self.focus = focus
        self.field = field
        self.transform = transform
        self._area = None

    def __repr__(self):
        return 'SocialGeometry[Focus:{}]'.format(self.focus)

    @property
    def area(self):
        if self._area is None:
            self._area = self.field.area()
        return self._area

class SocialGroupGeometry(collections.MutableMapping):
    __qualname__ = 'SocialGroupGeometry'

    def __init__(self):
        self.members = {}
        self.aggregate = None
        self._total_focus = None
        self._lockout = 0
        self._dirty = False

    def __repr__(self):
        return 'SocialGroupGeometry[focus:{}, Members:{}]'.format(self.focus, len(self.members))

    @property
    def focus(self):
        if self.aggregate is None:
            return
        return self.aggregate.focus

    @property
    def field(self):
        if self.aggregate is None:
            return
        return self.aggregate.field

    @property
    def area(self):
        if self.aggregate is None:
            return
        return self.aggregate.area

    def minimum_distance(self, p, sim_list, skip=None):
        sim_positions = [sim.intended_position for sim in sim_list if sim is not skip]
        if not sim_positions:
            return
        return sims4.math.minimum_distance(p, sim_positions)

    @contextlib.contextmanager
    def lock(self):
        try:
            self.aggregate = None
            self._total_focus = None
            yield self
        finally:
            if self._lockout == 0 and self._dirty:
                self._reconstruct()

    def score_placement(self, sim_list, group):
        scores = []
        for sim in sim_list:
            remainder = SocialGroupGeometry()
            with remainder.lock():
                for (other, other_geometry) in self.members.items():
                    if other is sim:
                        pass
                    remainder[other] = other_geometry
            (valid, _) = score_transforms([sim.transform], sim, group, remainder)
            if valid:
                scores.append((sim, valid[0][1]))
            else:
                scores.append((sim, 0))
        return scores

    def __len__(self):
        return len(self.members)

    def __iter__(self):
        return iter(self.members)

    def __bool__(self):
        return bool(self.members)

    def __getitem__(self, key):
        return self.members[key]

    def __setitem__(self, key, value):
        existed = key in self.members
        self.members[key] = value
        if existed:
            self._reconstruct()
        else:
            self._merge(value)

    def __delitem__(self, key):
        existed = key in self.members
        del self.members[key]
        if existed:
            self._reconstruct()

    def __contains__(self, key):
        return key in self.members

    def _reconstruct(self):
        if self._lockout:
            self._dirty = True
            return
        n = len(self.members)
        if n == 0:
            self._total_focus = None
            self.aggregate = None
            return
        total_focus = None
        field = None
        for geometry in self.members.values():
            if total_focus is None:
                total_focus = geometry.focus
                field = geometry.field
            else:
                total_focus = total_focus + geometry.focus
                field = field.intersect(geometry.field)
            while not field.convex:
                field = sims4.geometry.CompoundPolygon(sims4.geometry.Polygon())
        focus = total_focus*(1.0/n)
        self._total_focus = total_focus
        self.aggregate = SocialGeometry(focus, field, None)

    def _merge(self, geometry):
        if self._lockout:
            self._dirty = True
            return
        if self.aggregate is None:
            self._total_focus = geometry.focus
            self.aggregate = geometry
            return
        n = len(self.members)
        self._total_focus = self._total_focus + geometry.focus
        focus = self._total_focus*(1.0/n)
        field = self.aggregate.field.intersect(geometry.field)
        self.aggregate = SocialGeometry(focus, field, None)

def create_from_transform(base_transform, base_focus, base_field, focal_dist):
    offset = sims4.math.Transform(sims4.math.Vector3(0, 0, focal_dist), sims4.math.Quaternion.IDENTITY())
    transform = sims4.math.Transform.concatenate(offset, base_transform)
    transform.translation = sims4.math.vector_flatten(transform.translation)
    focus = transform.transform_point(base_focus)
    vertices = [transform.transform_point(v) for v in base_field]
    field = sims4.geometry.CompoundPolygon(sims4.geometry.Polygon(vertices))
    return SocialGeometry(focus, field, base_transform)

def _get_social_geometry_for_sim(sim):
    tuning = sim.posture.social_geometry
    if tuning is None:
        return (None, None)
    base_focus = tuning.focal_point
    base_field = tuning.social_space
    if base_field is None:
        return (None, None)
    (social_space_override, focal_point_override) = sim.si_state.get_social_geometry_override()
    if social_space_override is not None and focal_point_override is not None:
        base_focus = focal_point_override
        base_field = social_space_override
    return (base_focus, base_field)

def create(sim, group, transform_override=None):
    (base_focus, base_field) = _get_social_geometry_for_sim(sim)
    if base_focus is None or base_field is None:
        return
    r = group.group_radius
    transform = transform_override or sim.intended_transform
    return create_from_transform(transform, base_focus, base_field, r)

def score_transforms(transforms, sim, group, group_geometry, cutoff=None, modifier=None):
    (base_focus, base_field) = _get_social_geometry_for_sim(sim)
    if base_focus is None or base_field is None or not group_geometry:
        return ([], [])
    r = group.group_radius
    scored = []
    results = []
    rejected = []
    max_score = None
    for transform in transforms:
        score = score_transform(transform, sim, group_geometry, r, base_focus, base_field)
        if score > 0 and modifier is not None:
            score = modifier(score, transform, sim)
        if score > 0:
            scored.append((transform, score))
            max_score = max(score, max_score) if max_score is not None else score
        else:
            rejected.append((transform, score))
    if cutoff is None:
        cutoff = SocialGeometry.DEFAULT_SCORE_CUTOFF
    if max_score is not None:
        cutoff_score = max_score*cutoff
        for score_data in scored:
            if score_data[1] >= cutoff_score:
                results.append(score_data)
            else:
                rejected.append(score_data)
    return (results, rejected)

def score_transform(transform, sim, group_geometry, r, base_focus, base_field):
    accum = accumulator.HarmonicMeanAccumulator()
    dist = group_geometry.minimum_distance(transform.translation, group_geometry.members, skip=sim)
    in_group_dist_score = SocialGeometry.GROUP_DISTANCE_CURVE.get(dist)
    accum.add(in_group_dist_score)
    if accum.fault():
        return 0
    candidate_geometry = create_from_transform(transform, base_focus, base_field, r)
    candidate_area = candidate_geometry.field.area()
    if candidate_area <= sims4.math.EPSILON:
        return 0
    candidate_facing = sims4.math.yaw_quaternion_to_angle(transform.orientation)
    for (other_sim, geometry) in group_geometry.members.items():
        if other_sim is sim:
            pass
        other_facing = sims4.math.yaw_quaternion_to_angle(geometry.transform.orientation)
        delta = geometry.transform.translation - transform.translation
        score_facing(accum, candidate_facing, other_facing, delta)
        intersection = geometry.field.intersect(candidate_geometry.field)
        fraction = intersection.area()/candidate_area
        fraction = SocialGeometry.OVERLAP_SCORE_MULTIPLIER*max(fraction, SocialGeometry.NON_OVERLAPPING_SCORE_MULTIPLIER)
        accum.add(fraction)
        while accum.fault():
            return 0
    nearby_non_members = placement.get_nearby_sims(transform.translation, sim.routing_surface.secondary_id, exclude=group_geometry)
    if sim in nearby_non_members:
        nearby_non_members.remove(sim)
    if nearby_non_members:
        nearest = group_geometry.minimum_distance(transform.translation, nearby_non_members)
        not_in_group_score = SocialGeometry.NON_GROUP_DISTANCE_CURVE.get(nearest)
        accum.add(not_in_group_score)
    return accum.value()

def score_facing(accum, sim_facing, other_facing, delta):
    facing_angle = sims4.math.vector3_angle(delta)
    angle = sims4.math.angle_abs_difference(sim_facing, facing_angle)
    score = SocialGeometry.GROUP_ANGLE_CURVE.get(angle)
    accum.add(score)
    angle = sims4.math.angle_abs_difference(other_facing, facing_angle + sims4.math.PI)
    score = SocialGeometry.GROUP_ANGLE_CURVE.get(angle)
    accum.add(score)

