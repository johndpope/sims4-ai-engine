from debugvis import Context, KEEP_ALTITUDE
from sims4.color import from_rgba, to_rgba
import routing
import sims4.math
import terrain

class PathGoalVisualizer:
    __qualname__ = 'PathGoalVisualizer'

    def __init__(self, sim, layer):
        self._sim = sim.ref()
        self.layer = layer
        self.start()

    @property
    def sim(self):
        if self._sim is not None:
            return self._sim()

    def start(self):
        self.sim.on_follow_path.append(self._on_path_follow)

    def stop(self):
        self.sim.on_follow_path.remove(self._on_path_follow)

    def _draw_goal(self, context, goal, goal_color, weight_height, weight_color):
        if goal is None:
            return
        (_, _, _, goal_color_alpha) = to_rgba(goal_color)
        goal_color_alpha = weight_height*goal_color_alpha
        goal_weight_color = from_rgba(0, 255, 0, goal_color_alpha)
        context.routing_surface = goal.routing_surface_id
        if goal.location.orientation != sims4.math.Quaternion.ZERO():
            angle = sims4.math.yaw_quaternion_to_angle(goal.location.orientation)
            context.add_arrow(goal.location.position, angle, length=0.05, color=goal_color)
            context.add_arrow(goal.location.position, angle, length=0.1, color=goal_weight_color)
        else:
            context.add_circle(goal.location.position, 0.02, color=goal_color)
            context.add_circle(goal.location.position, 0.07, color=goal_weight_color)
        if weight_height > 0:
            ground_height = terrain.get_terrain_height(goal.location.position.x, goal.location.position.z, routing_surface=context.routing_surface)
            bottom = sims4.math.Vector3(goal.location.position.x, ground_height, goal.location.position.z)
            top = sims4.math.Vector3(bottom.x, bottom.y + weight_height, bottom.z)
            context.add_segment(bottom, top, color=weight_color, altitude=KEEP_ALTITUDE)

    def _draw_goal_with_score(self, context, goal, goal_color, score_height, score_color, weight_height, weight_color):
        if goal is None:
            return
        self._draw_goal(context, goal, goal_color, weight_height, weight_color)
        ground_height = terrain.get_terrain_height(goal.location.position.x, goal.location.position.z, routing_surface=goal.routing_surface_id)
        bottom = sims4.math.Vector3(goal.location.position.x, ground_height, goal.location.position.z)
        top = sims4.math.Vector3(goal.location.position.x, ground_height + score_height, goal.location.position.z)
        context.add_segment(bottom, top, color=score_color, altitude=KEEP_ALTITUDE)

    def _on_path_follow(self, follow_path, starting):
        if not starting:
            return
        path = follow_path.path
        if not path.route.goals:
            return
        goal_results = path.nodes.goal_results()
        if goal_results is None:
            return
        goal_list = path.route.goals
        goal_mask_success = routing.GOAL_STATUS_SUCCESS | routing.GOAL_STATUS_SUCCESS_TRIVIAL | routing.GOAL_STATUS_SUCCESS_LOCAL
        goal_mask_input_error = routing.GOAL_STATUS_INVALID_SURFACE | routing.GOAL_STATUS_INVALID_POINT
        goal_mask_unreachable = routing.GOAL_STATUS_CONNECTIVITY_GROUP_UNREACHABLE | routing.GOAL_STATUS_COMPONENT_DIFFERENT | routing.GOAL_STATUS_IMPASSABLE | routing.GOAL_STATUS_BLOCKED
        min_score = sims4.math.POS_INFINITY
        max_score = sims4.math.NEG_INFINITY
        for result in goal_results:
            while result[1] & (routing.GOAL_STATUS_LOWER_SCORE | goal_mask_success) > 0:
                if result[2] < min_score:
                    min_score = result[2]
                if result[2] > max_score:
                    max_score = result[2]
        score_range = max_score - min_score
        normalized_scores = []
        if score_range != 0:
            for result in goal_results:
                normalized_scores.append(1.0 - (result[2] - min_score)/score_range)
        else:
            for result in goal_results:
                normalized_scores.append(1.0)
        min_weight = sims4.math.POS_INFINITY
        max_weight = sims4.math.NEG_INFINITY
        for goal in goal_list:
            if goal.weight < min_weight:
                min_weight = goal.weight
            while goal.weight > max_weight:
                max_weight = goal.weight
        weight_range = max_weight - min_weight
        normalized_weights = []
        if weight_range != 0:
            for goal in goal_list:
                normalized_weights.append(1.0 - (goal.weight - min_weight)/weight_range)
        else:
            for goal in goal_list:
                normalized_weights.append(0.0)
        selected_tag = path.nodes.selected_tag
        min_success_score_color = sims4.color.from_rgba(0.0, 0.4, 0.0)
        max_success_score_color = sims4.color.from_rgba(0.0, 1.0, 0.0)
        selected_goal_color = sims4.color.from_rgba(0.0, 1.0, 0.0)
        min_weight_color = sims4.color.from_rgba(0.0, 0.0, 0.4)
        max_weight_color = sims4.color.from_rgba(0.0, 0.0, 1.0)
        min_discarded_score_color = sims4.color.from_rgba(0.4, 0.4, 0.0)
        max_discarded_score_color = sims4.color.from_rgba(1.0, 1.0, 0.0)
        not_evaluated_color = sims4.color.from_rgba(0, 1.0, 1.0)
        error_color = sims4.color.Color.WHITE
        unreachable_color = sims4.color.Color.RED
        input_error_color = sims4.color.from_rgba(1.0, 0, 1.0)
        with Context(self.layer) as context:
            for i in range(len(goal_results)):
                result = goal_results[i]
                goal = goal_list[i]
                status = result[1]
                weight_color = sims4.color.interpolate(max_weight_color, min_weight_color, normalized_weights[i])
                if status & goal_mask_input_error > 0:
                    self._draw_goal(context, goal, input_error_color, normalized_weights[i], weight_color)
                elif status & goal_mask_unreachable > 0:
                    if status & goal_mask_success > 0 and i == selected_tag:
                        score_color = sims4.color.interpolate(max_discarded_score_color, min_discarded_score_color, normalized_scores[i])
                        self._draw_goal_with_score(context, goal, unreachable_color, normalized_scores[i], score_color, normalized_weights[i], weight_color)
                    else:
                        self._draw_goal(context, goal, unreachable_color, normalized_weights[i], weight_color)
                        if status & routing.GOAL_STATUS_LOWER_SCORE > 0:
                            score_color = sims4.color.interpolate(max_discarded_score_color, min_discarded_score_color, normalized_scores[i])
                            self._draw_goal_with_score(context, goal, max_discarded_score_color, normalized_scores[i], score_color, normalized_weights[i], weight_color)
                        elif status & goal_mask_success > 0:
                            if i == selected_tag:
                                score_color = sims4.color.interpolate(max_success_score_color, min_success_score_color, normalized_scores[i])
                            else:
                                score_color = sims4.color.interpolate(max_discarded_score_color, min_discarded_score_color, normalized_scores[i])
                            self._draw_goal_with_score(context, goal, selected_goal_color, normalized_scores[i], score_color, normalized_weights[i], weight_color)
                        elif status & routing.GOAL_STATUS_NOTEVALUATED > 0:
                            self._draw_goal(context, goal, not_evaluated_color, normalized_weights[i], weight_color)
                        else:
                            self._draw_goal(context, goal, error_color, normalized_weights[i], weight_color)
                elif status & routing.GOAL_STATUS_LOWER_SCORE > 0:
                    score_color = sims4.color.interpolate(max_discarded_score_color, min_discarded_score_color, normalized_scores[i])
                    self._draw_goal_with_score(context, goal, max_discarded_score_color, normalized_scores[i], score_color, normalized_weights[i], weight_color)
                elif status & goal_mask_success > 0:
                    if i == selected_tag:
                        score_color = sims4.color.interpolate(max_success_score_color, min_success_score_color, normalized_scores[i])
                    else:
                        score_color = sims4.color.interpolate(max_discarded_score_color, min_discarded_score_color, normalized_scores[i])
                    self._draw_goal_with_score(context, goal, selected_goal_color, normalized_scores[i], score_color, normalized_weights[i], weight_color)
                elif status & routing.GOAL_STATUS_NOTEVALUATED > 0:
                    self._draw_goal(context, goal, not_evaluated_color, normalized_weights[i], weight_color)
                else:
                    self._draw_goal(context, goal, error_color, normalized_weights[i], weight_color)

