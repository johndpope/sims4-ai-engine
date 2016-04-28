from interactions import ParticipantType, ParticipantTypeSingle
from interactions.base.interaction import InteractionQueuePreparationStatus
from interactions.base.super_interaction import SuperInteraction
from interactions.constraints import Anywhere, TunableConstraintVariant
from objects.helpers.user_footprint_helper import UserFootprintHelper
from sims4.tuning.tunable import TunableList, TunableEnumEntry
import sims4.geometry

class ClearSpaceSuperInteraction(SuperInteraction):
    __qualname__ = 'ClearSpaceSuperInteraction'
    INSTANCE_TUNABLES = {'clear_constraints': TunableList(description='\n            A list of constraints from which sims will be pushed\n            ', tunable=TunableConstraintVariant(description='\n                A constraint from which sims will be pushed.\n                ')), 'clear_constraints_actor': TunableEnumEntry(ParticipantTypeSingle, ParticipantType.Object, description='\n            The Actor used to generate constraints relative to.\n            ')}

    def prepare_gen(self, timeline, *args, **kwargs):
        result = yield super().prepare_gen(timeline, *args, **kwargs)
        if result != InteractionQueuePreparationStatus.SUCCESS:
            return result
        constraint_target = self.get_participant(participant_type=self.clear_constraints_actor)
        sim = self.get_participant(ParticipantType.Actor, target=constraint_target)
        if sim is None:
            return result
        if constraint_target is None:
            return result
        intersection = Anywhere()
        for tuned_constraint in self.clear_constraints:
            constraint = tuned_constraint.create_constraint(sim, constraint_target)
            constraint = constraint.create_concrete_version(self)
            intersection = constraint.intersect(intersection)
            while not intersection.valid:
                return result
        for constraint_polygon in constraint.polygons:
            if isinstance(constraint_polygon, sims4.geometry.CompoundPolygon):
                for polygon in constraint_polygon:
                    UserFootprintHelper.force_move_sims_in_polygon(polygon, constraint_target.routing_surface, exclude=[sim])
            else:
                UserFootprintHelper.force_move_sims_in_polygon(constraint_polygon, constraint_target.routing_surface, exclude=[sim])
        return result

