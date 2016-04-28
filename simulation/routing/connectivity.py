from interactions.utils.routing import SlotGoal
from native.routing.connectivity import Handle, HandleList
from sims4.collections import frozendict
import sims4.math
import placement
import routing

class RoutingHandle(Handle):
    __qualname__ = 'RoutingHandle'

    def __init__(self, sim, constraint, geometry, los_reference_point=None, routing_surface_override=None, locked_params=frozendict(), target=None, weight_route_factor=1.0):
        self.routing_surface = sim.routing_surface if constraint.routing_surface is None else constraint.routing_surface
        if routing_surface_override is not None:
            self.routing_surface = routing_surface_override
        self.routing_surface_override = routing_surface_override
        super().__init__(geometry.polygon, self.routing_surface)
        self.locked_params = locked_params
        self.sim = sim
        self.constraint = constraint
        self.geometry = geometry
        self.los_reference_point = los_reference_point
        self.target = target
        self.weight_route_factor = weight_route_factor

    def clone(self, **overrides):
        kwargs = dict(sim=self.sim, constraint=self.constraint, geometry=self.geometry, los_reference_point=self.los_reference_point, routing_surface_override=self.routing_surface_override, locked_params=self.locked_params, weight_route_factor=self.weight_route_factor)
        kwargs.update(overrides)
        clone = RoutingHandle(**kwargs)
        if hasattr(self, 'path'):
            clone.path = self.path
        if hasattr(self, 'var_map'):
            clone.var_map = self.var_map
        return clone

    def get_goals(self, max_goals=None, relative_object=None, single_goal_only=False, for_carryable=False):
        if self.constraint.routing_surface is not None:
            routing_surface = self.constraint.routing_surface
        else:
            routing_surface = self.sim.routing_surface
        if max_goals is None:
            max_goals = self.constraint.ROUTE_GOAL_COUNT_FOR_SCORING_FUNC
        if self.constraint.get_python_scoring_functions():
            native_scoring_functions = ()
            python_scoring_functions = self.constraint._scoring_functions
        else:
            native_scoring_functions = self.constraint.get_native_scoring_functions()
            python_scoring_functions = ()
        orientation_restrictions = self.geometry.restrictions
        objects_to_ignore = set(self.constraint._objects_to_ignore or ())
        if relative_object is not None and not relative_object.is_sim:
            objects_to_ignore.add(relative_object.id)
        if not self.constraint.force_route:
            objects_to_ignore.add(self.sim.id)
        if self.sim.posture.target is not None:
            objects_to_ignore.add(self.sim.posture.target.id)
        if isinstance(self, SlotRoutingHandle) and native_scoring_functions:
            python_scoring_functions = native_scoring_functions
            native_scoring_functions = ()
        c_native_scoring_functions = [w._c_scoring_function for w in native_scoring_functions] if native_scoring_functions else None
        generated_goals = placement.generate_routing_goals_for_polygon(self.sim, self.geometry.polygon, routing_surface, c_native_scoring_functions, orientation_restrictions, objects_to_ignore, flush_planner=self.constraint._flush_planner, los_reference_pt=self.los_reference_point, max_points=max_goals, score_density=self.constraint._weight_route_factor, min_score_to_ignore_outer_penalty=self.constraint._ignore_outer_penalty_threshold, single_goal_only=single_goal_only, los_routing_context=relative_object.raycast_context(for_carryable=for_carryable) if relative_object is not None else None, all_blocking_edges_block_los=self.los_reference_point is not None and single_goal_only)
        if not generated_goals:
            return []
        goal_list = []
        group_id = id(self.constraint)
        if len(self.geometry.polygon) == 1 and len(self.geometry.polygon[0]) == 1 and isinstance(self, SlotRoutingHandle):
            cost_override = 1
        else:
            cost_override = None
        for (tag, (location, cost, _)) in enumerate(generated_goals):
            if cost_override is not None and cost > sims4.math.EPSILON:
                cost = max(cost, cost_override)
            full_cost = self.get_location_score(location.position, location.orientation, location.routing_surface, cost, python_scoring_functions)
            goal = self.create_goal(location, full_cost, tag, group_id)
            goal_list.append(goal)
        return goal_list

    def create_goal(self, location, full_cost, tag, group_id):
        return routing.Goal(location, cost=full_cost, tag=tag, group=group_id, requires_los_check=self.los_reference_point is not None, connectivity_handle=self)

    def get_location_score(self, position, orientation, routing_surface, router_cost, scoring_functions):
        full_cost = router_cost
        if router_cost > 0:
            scores = [scoring_function.get_combined_score(position, orientation, routing_surface) for scoring_function in scoring_functions]
            for (multiplier, _) in scores:
                full_cost *= multiplier
            for (_, offset) in scores:
                full_cost += offset
            full_cost *= self.weight_route_factor
        return full_cost

class SlotRoutingHandle(RoutingHandle):
    __qualname__ = 'SlotRoutingHandle'

    def create_goal(self, location, full_cost, tag, group_id):
        return SlotGoal(location, containment_transform=self.constraint.containment_transform, cost=full_cost, tag=tag, group=group_id, requires_los_check=self.los_reference_point is not None, connectivity_handle=self, slot_params=self.locked_params)

    def get_location_score(self, position, orientation, routing_surface, router_cost, scoring_functions):
        transform = self.constraint.containment_transform
        return super().get_location_score(transform.translation, transform.orientation, routing_surface, router_cost, scoring_functions)

