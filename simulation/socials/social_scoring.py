import weakref
from interactions.constraints import ScoringFunctionBase
import sims4.math
import socials.geometry
import accumulator

class SocialJoinScoringFunction(ScoringFunctionBase):
    __qualname__ = 'SocialJoinScoringFunction'

    def __init__(self, target_sim):
        self._target_sim_ref = target_sim.ref()

    def get_score(self, position, orientation, routing_surface):
        target_sim = self._target_sim_ref() if self._target_sim_ref is not None else None
        if target_sim is None:
            return 1
        accum = accumulator.HarmonicMeanAccumulator()
        candidate_facing = sims4.math.yaw_quaternion_to_angle(orientation)
        other_facing = sims4.math.yaw_quaternion_to_angle(target_sim.intended_transform.orientation)
        delta = target_sim.intended_transform.translation - position
        socials.geometry.score_facing(accum, candidate_facing, other_facing, delta)
        return accum.value()

class SocialGroupScoringFunction(ScoringFunctionBase):
    __qualname__ = 'SocialGroupScoringFunction'

    def __init__(self, group, sim):
        self._group_ref = weakref.ref(group)
        self._sim = sim

    def get_score(self, position, orientation, routing_surface):
        raise NotImplementedError('SocialGroupScoringFunction only supports get_combined_score')

    def get_combined_score(self, position, orientation, routing_surface):
        group = self._group_ref()
        if group is None:
            return (1.0, 0.0)
        geometry = group.geometry
        if not geometry or len(geometry) == 1 and self._sim in geometry:
            ideal_position = group.position
            effective_distance = (position - ideal_position).magnitude_2d()*2.0
            score = socials.geometry.SocialGeometry.GROUP_DISTANCE_CURVE.get(effective_distance)
            return (score, 0.0)
        (base_focus, base_field) = socials.geometry._get_social_geometry_for_sim(self._sim)
        transform = sims4.math.Transform(position, orientation)
        multiplier = socials.geometry.score_transform(transform, self._sim, geometry, group.group_radius, base_focus, base_field)
        offset = multiplier*socials.geometry.SocialGeometry.SCORE_STRENGTH_MULTIPLIER
        if self._sim in geometry and sims4.math.vector3_almost_equal_2d(position, self._sim.position, epsilon=0.01):
            offset += socials.geometry.SocialGeometry.SCORE_OFFSET_FOR_CURRENT_POSITION
        return (multiplier, offset)

    def get_posture_cost_attenuation(self, body_target):
        (multiplier, _) = self.get_combined_score(body_target.position, body_target.orientation, body_target.routing_surface)
        return multiplier

