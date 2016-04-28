from element_utils import build_critical_section, maybe, build_critical_section_with_finally
from interactions.aop import AffordanceObjectPair
from interactions.interaction_finisher import FinishingType
from interactions.utils.animation_reference import TunableAnimationReference
from interactions.utils.state import conditional_animation
from objects.game_object import GameObject
from sims4.geometry import build_rectangle_from_two_points_and_radius
from sims4.tuning.tunable import Tunable
import element_utils
import interactions.base.super_interaction
import interactions.constraints
import objects.components.state
import placement
import services
import sims4.log
import sims4.math
logger = sims4.log.Logger('Television')

class WatchSuperInteraction(interactions.base.super_interaction.SuperInteraction):
    __qualname__ = 'WatchSuperInteraction'
    INSTANCE_TUNABLES = {'required_channel': objects.components.state.TunableStateValueReference(description='The channel that this affordance watches.'), 'remote_animation': TunableAnimationReference(description='The animation for using the TV remote.'), 'sim_view_discourage_area_width': Tunable(float, 0.4, description='The width of the discouragement region placed from a viewing Sim to the TV.')}
    CHANGE_CHANNEL_XEVT_ID = 101

    @classmethod
    def _verify_tuning_callback(cls):
        super()._verify_tuning_callback()
        if cls.required_channel is None:
            logger.error('Tuning: {} is missing a Required Channel.', cls.__name__)
        if cls.remote_animation is None:
            logger.error('Tuning: {} is missing a Remote Animation.', cls.__name__)

    def _add_route_goal_suppression_region_to_quadtree(self, *args, **kwargs):
        object_point = self.target.location.transform.translation
        sim_point = self.sim.intended_location.transform.translation
        geo = build_rectangle_from_two_points_and_radius(object_point, sim_point, self.sim_view_discourage_area_width)
        services.sim_quadtree().insert(self.sim, self.id, placement.ItemType.ROUTE_GOAL_PENALIZER, geo, self.sim.routing_surface.secondary_id, False, 0)

    def _remove_route_goal_suppression_region_from_quadtree(self):
        services.sim_quadtree().remove(self.id, placement.ItemType.ROUTE_GOAL_PENALIZER, 0)

    def _refresh_watching_discouragement_stand_region(self, *args, **kwargs):
        self._remove_route_goal_suppression_region_from_quadtree()
        self._add_route_goal_suppression_region_to_quadtree()

    def _start_route_goal_suppression(self, _):
        self.sim.on_intended_location_changed.append(self._refresh_watching_discouragement_stand_region)
        self._add_route_goal_suppression_region_to_quadtree()

    def _stop_route_goal_suppression(self, _):
        self._remove_route_goal_suppression_region_from_quadtree()
        self.sim.on_intended_location_changed.remove(self._refresh_watching_discouragement_stand_region)

    def ensure_state(self, desired_channel):
        return conditional_animation(self, desired_channel, self.CHANGE_CHANNEL_XEVT_ID, self.affordance.remote_animation)

    def _changed_state_callback(self, target, state, old_value, new_value):
        if new_value != Television.TV_OFF_STATE:
            context = self.context.clone_for_continuation(self)
            affordance = self.generate_continuation_affordance(new_value.affordance)
            aop = AffordanceObjectPair(affordance, self.target, affordance, None)
            aop.test_and_execute(context)
        self.cancel(FinishingType.OBJECT_CHANGED, cancel_reason_msg='state: interaction canceled on state change ({} != {})'.format(new_value.value, self.required_channel.value))

    def _run_interaction_gen(self, timeline):
        result = yield element_utils.run_child(timeline, build_critical_section_with_finally(self._start_route_goal_suppression, build_critical_section(build_critical_section(self.ensure_state(self.affordance.required_channel), objects.components.state.with_on_state_changed(self.target, self.affordance.required_channel.state, self._changed_state_callback, super()._run_interaction_gen)), maybe(lambda : len(self.target.get_users(sims_only=True)) == 1, self.ensure_state(Television.TV_OFF_STATE))), self._stop_route_goal_suppression))
        return result

class Television(GameObject):
    __qualname__ = 'Television'
    DISCOURAGE_AREA = interactions.constraints.TunableCone(0, 1.25, sims4.math.PI/3, description='Area in front of a TV Sims will be discouraged from routing through if the TV is on.')
    DISCOURAGE_AREA_COST = Tunable(float, 25, description='The cost of routing in front of a TV that is on.')
    TV_OFF_STATE = objects.components.state.TunableStateValueReference(description='The TV channel off state value')

