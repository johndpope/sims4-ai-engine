from animation.posture_manifest_constants import STAND_AT_NONE_CONSTRAINT
from interactions import ParticipantType
from interactions.base.super_interaction import SuperInteraction
from interactions.constraints import Circle
from interactions.utils.routing import WalkStyle, with_walkstyle, PlanRoute, get_route_element_for_path
from sims.sim_info_types import SimInfoSpawnerTags
from sims4.random import pop_weighted
from sims4.tuning.tunable import Tunable
from sims4.utils import flexmethod
import element_utils
import routing
import services
import sims4.log
import sims4.math
logger = sims4.log.Logger('Jogging')

class GoJoggingInteraction(SuperInteraction):
    __qualname__ = 'GoJoggingInteraction'
    NUM_JOG_POINTS = Tunable(int, 2, description='\n            The number of waypoints to select, from spawn points in the zone, to visit for a Jog\n            prior to returning to the original location.')
    CONSTRAINT_RADIUS = Tunable(float, 6, description='\n            The radius in meters of the various jogging waypoint constraints that are generated.')
    WALKSTYLE_PRIORITY = Tunable(float, 15, description='\n            The walkstyle priority override of the jog interaction.')

    @classmethod
    def _is_linked_to(cls, super_affordance):
        return False

    @classmethod
    def get_jog_waypoint_constraints(cls, context):
        sim = context.sim
        if context.pick is not None:
            pick_position = context.pick.location
            pick_vector = pick_position - sim.position
            pick_vector /= pick_vector.magnitude()
        else:
            pick_vector = sim.forward
        zone = services.current_zone()
        active_lot = zone.lot
        lot_corners = active_lot.corners
        sim_poly = sims4.geometry.CompoundPolygon(sims4.geometry.Polygon([sim.position]))
        lot_poly = sims4.geometry.CompoundPolygon(sims4.geometry.Polygon([corner for corner in lot_corners]))
        intersection = lot_poly.intersect(sim_poly)
        sim_on_lot = len(intersection) >= 1
        if sim_on_lot:
            spawn_point = zone.get_spawn_point(lot_id=active_lot.lot_id, sim_spawner_tags=SimInfoSpawnerTags.SIM_SPAWNER_TAGS)
            origin_position = spawn_point.center
            routing_surface = routing.SurfaceIdentifier(zone.id, 0, routing.SURFACETYPE_WORLD)
            except_lot_id = active_lot.lot_id
        else:
            origin_position = sim.position
            routing_surface = sim.routing_surface
            except_lot_id = None
        interaction_constraint = Circle(origin_position, cls.CONSTRAINT_RADIUS, routing_surface=routing_surface, los_reference_point=None)
        jog_waypoint_constraints = []
        zone = services.current_zone()
        active_lot = zone.lot
        constraint_set = zone.get_spawn_points_constraint(except_lot_id=except_lot_id)
        constraints_weighted = []
        min_score = sims4.math.MAX_FLOAT
        for constraint in constraint_set:
            spawn_point_vector = constraint.average_position - sim.position
            score = sims4.math.vector_dot_2d(pick_vector, spawn_point_vector)
            if score < min_score:
                min_score = score
            constraints_weighted.append((score, constraint))
        constraints_weighted = [(score - min_score, constraint) for (score, constraint) in constraints_weighted]
        constraints_weighted = sorted(constraints_weighted, key=lambda i: i[0])
        first_constraint = constraints_weighted[-1][1]
        del constraints_weighted[-1]
        first_constraint_circle = Circle(first_constraint.average_position, cls.CONSTRAINT_RADIUS, routing_surface=first_constraint.routing_surface)
        jog_waypoint_constraints.append(first_constraint_circle)
        last_waypoint_position = first_constraint.average_position
        for _ in range(cls.NUM_JOG_POINTS - 1):
            constraints_weighted_next = []
            for (_, constraint) in constraints_weighted:
                average_position = constraint.average_position
                distance_last = (average_position - last_waypoint_position).magnitude_2d()
                distance_home = (average_position - origin_position).magnitude_2d()
                constraints_weighted_next.append((distance_last + distance_home, constraint))
            next_constraint = pop_weighted(constraints_weighted_next)
            next_constraint_circle = Circle(next_constraint.average_position, cls.CONSTRAINT_RADIUS, routing_surface=next_constraint.routing_surface)
            jog_waypoint_constraints.append(next_constraint_circle)
            constraints_weighted = constraints_weighted_next
            last_waypoint_position = next_constraint.average_position
        jog_waypoint_constraints.append(interaction_constraint)
        return (interaction_constraint, jog_waypoint_constraints)

    @classmethod
    def get_rallyable_aops_gen(cls, target, context, **kwargs):
        key = 'jog_info'
        if key not in kwargs:
            jog_waypoint_constraints = cls.get_jog_waypoint_constraints(context)
            kwargs[key] = jog_waypoint_constraints
        yield super().get_rallyable_aops_gen(target, context, rally_constraint=jog_waypoint_constraints[0], **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        jog_info = kwargs.get('jog_info')
        if jog_info is not None:
            (self._jog_start_constraint, self._jog_waypoint_constraints) = jog_info
        else:
            (self._jog_start_constraint, self._jog_waypoint_constraints) = self.get_jog_waypoint_constraints(self.context)

    @flexmethod
    def _constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        yield STAND_AT_NONE_CONSTRAINT
        if inst is not None:
            yield inst._jog_start_constraint

    def do_route_to_constraint(self, constraint, timeline):
        goals = []
        handles = constraint.get_connectivity_handles(self.sim)
        for handle in handles:
            goals.extend(handle.get_goals())
        route = routing.Route(self.sim.routing_location, goals, routing_context=self.sim.routing_context)
        plan_primitive = PlanRoute(route, self.sim)
        result = yield element_utils.run_child(timeline, plan_primitive)
        if not result:
            return False
        if not plan_primitive.path.nodes or not plan_primitive.path.nodes.plan_success:
            return False
        route = get_route_element_for_path(self.sim, plan_primitive.path)
        result = yield element_utils.run_child(timeline, with_walkstyle(self.sim, WalkStyle.JOG, self.id, sequence=route, priority=self.WALKSTYLE_PRIORITY))
        return result

    def _run_interaction_gen(self, timeline):
        for constraint in self._jog_waypoint_constraints:
            result = yield self.do_route_to_constraint(constraint, timeline)
            while not result:
                return False
        return True

