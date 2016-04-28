from event_testing.results import TestResult
from interactions.base.super_interaction import SuperInteraction
from objects.terrain import TerrainSuperInteraction
import routing
import services
import sims4

class TeleportHereInteraction(TerrainSuperInteraction):
    __qualname__ = 'TeleportHereInteraction'
    _teleporting = True
    _ignores_spawn_point_footprints = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dest_goals = None

    @classmethod
    def _test(cls, target, context, **kwargs):
        (position, surface) = cls._get_position_and_surface(target, context)
        if position is None or surface is None:
            return TestResult(False, 'Cannot go here without a pick or target.')
        location = routing.Location(position, sims4.math.Quaternion.IDENTITY(), surface)
        if not routing.test_connectivity_permissions_for_handle(routing.connectivity.Handle(location), context.sim.routing_context):
            return TestResult(False, 'Cannot TeleportHere! Unroutable area.')
        return TestResult.TRUE

    def _run_interaction_gen(self, timeline):
        sims4.log.info('SimInfo', 'Running teleport_here interaction')
        new_location = sims4.math.Location(self.target.transform, self.target.routing_surface)
        self.sim.set_location(new_location)
        self.sim.refresh_los_constraint()
        self.sim.on_slot = None
        return True

class TeleportInteraction(SuperInteraction):
    __qualname__ = 'TeleportInteraction'
    _teleporting = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dest_goals = []

    def _run_interaction_gen(self, timeline):
        for goal in self.dest_goals:
            goal_transform = sims4.math.Transform(goal.location.transform.translation, goal.location.transform.orientation)
            goal_surface = goal.routing_surface_id
            goal_location = sims4.math.Location(goal_transform, goal_surface)
            self.sim.set_location(goal_location)
            break
        result = yield super()._run_interaction_gen(timeline)
        return result

