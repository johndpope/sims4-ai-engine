from build_buy import FloorFeatureType
from interactions.constraints import Anywhere, create_constraint_set, TunableCircle, TunableFacing
from interactions.utils.satisfy_constraint_interaction import SitOrStandSuperInteraction
from primitives.routing_utils import estimate_distance_between_points
from sims4.tuning.tunable import Tunable, TunableEnumEntry
import build_buy
import routing
import sims4.log
logger = sims4.log.Logger('FloorFeatureInteractions')

class GoToNearestFloorFeatureInteraction(SitOrStandSuperInteraction):
    __qualname__ = 'GoToNearestFloorFeatureInteraction'
    INSTANCE_TUNABLES = {'terrain_feature': TunableEnumEntry(description='\n            The type of floor feature the sim should route to\n            ', tunable_type=FloorFeatureType, default=FloorFeatureType.BURNT), 'routing_circle_constraint': TunableCircle(1.5, description='\n            Circle constraint around the floor feature\n            '), 'routing_facing_constraint': TunableFacing(description='\n                Controls how a Sim must face the terrain feature\n                '), 'indoors_only': Tunable(description='\n            Indoors Only\n            ', tunable_type=bool, default=False)}

    def __init__(self, aop, context, *args, **kwargs):
        constraint_to_satisfy = self._create_floor_feature_constraint_set(context)
        super().__init__(aop, context, constraint_to_satisfy=constraint_to_satisfy, *args, **kwargs)

    @classmethod
    def _create_floor_feature_constraint_set(cls, context):
        floor_feature_contraints = []
        floor_features_and_distances = []
        zone_id = sims4.zone_utils.get_zone_id()
        sim = context.sim
        sim_position = sim.position
        sim_routing_surface = sim.routing_surface
        floor_features = build_buy.list_floor_features(zone_id, cls.terrain_feature)
        for floor_feature in floor_features:
            if cls.indoors_only and build_buy.is_location_natural_ground(zone_id, floor_feature[0], floor_feature[1]):
                pass
            routing_surface = routing.SurfaceIdentifier(zone_id, floor_feature[1], routing.SURFACETYPE_WORLD)
            distance = estimate_distance_between_points(sim_position, sim_routing_surface, floor_feature[0], routing_surface)
            while distance is not None:
                floor_features_and_distances.append([[floor_feature[0], routing_surface], distance])
        if floor_features_and_distances:
            sorted(floor_features_and_distances, key=lambda feature: feature[1])
            for floor_feature_and_distance in floor_features_and_distances:
                floor_feature = floor_feature_and_distance[0]
                circle_constraint = cls.routing_circle_constraint.create_constraint(sim, None, target_position=floor_feature[0], routing_surface=floor_feature[1])
                facing_constraint = cls.routing_facing_constraint.create_constraint(sim, None, target_position=floor_feature[0], routing_surface=floor_feature[1])
                constraint = circle_constraint.intersect(facing_constraint)
                floor_feature_contraints.append(constraint)
        return create_constraint_set(floor_feature_contraints)

