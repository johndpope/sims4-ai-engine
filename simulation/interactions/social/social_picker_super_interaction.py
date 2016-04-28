from autonomy.autonomy_request import AutonomyRequest
from interactions import ParticipantType
from interactions.aop import AffordanceObjectPair
from interactions.context import InteractionBucketType
from interactions.social.social_super_interaction import SocialCompatibilityMixin
import autonomy
import event_testing.results
import interactions.base.super_interaction
import services
import sims4.log
import sims4.resources
import sims4.tuning
logger = sims4.log.Logger('Socials')

class SocialPickerSuperInteraction(SocialCompatibilityMixin, interactions.base.super_interaction.SuperInteraction):
    __qualname__ = 'SocialPickerSuperInteraction'
    SOCIAL_STATIC_COMMODITY = sims4.tuning.tunable.TunableReference(description="\n                                                                        All social SIs except for this one must be tagged with this static commodity or they \n                                                                        won't be seen or selected by autonomy.\n                                                                        \n                                                                        Example: sim_Chat and BeAffectionate should both have this static commodity.", manager=services.get_instance_manager(sims4.resources.Types.STATIC_COMMODITY))

    @classmethod
    def _test(cls, target, context, **kwargs):
        target_sim = cls.get_participant(interactions.ParticipantType.TargetSim, target=target, context=context, sim=context.sim)
        if target_sim is None:
            return event_testing.results.TestResult(False, None, 'target_sim is invalid in SocialPickerSuperInteraction')
        if target_sim is context.sim:
            return event_testing.results.TestResult(False, None, 'Cannot run a social targeting yourself.')
        if not context.sim.queue.can_queue_visible_interaction():
            return event_testing.results.TestResult(False, None, 'Interaction queue is full.')
        return super()._test(target, context, **kwargs)

    def estimate_distance(self):
        (compatible, _, included_sis) = self.test_constraint_compatibility()
        if not compatible:
            return (None, False, included_sis)
        target_sim = self.get_participant(ParticipantType.TargetSim)
        sim_constraint = self.sim.si_state.get_total_constraint(priority=self.priority)
        for constraint in sim_constraint:
            while constraint.geometry is not None:
                break
        return (0, False, included_sis)
        if not target_sim.can_see(self.sim):
            return (None, False, included_sis)
        return (0, False, included_sis)

    @property
    def canceling_incurs_opportunity_cost(self):
        return False

    def _run_interaction_gen(self, timeline):
        target_sim = self.get_participant(interactions.ParticipantType.TargetSim)
        logger.assert_log(target_sim is not None, 'target_sim is invalid in SocialPickerSuperInteraction._run_interaction_gen()', owner='rez')
        self.force_inertial = True
        context = self.context.clone_for_sim(self.sim, bucket=InteractionBucketType.BASED_ON_SOURCE)
        autonomy_request = AutonomyRequest(self.sim, autonomy_mode=autonomy.autonomy_modes.SocialAutonomy, static_commodity_list=[self.SOCIAL_STATIC_COMMODITY], object_list=[target_sim], context=context, push_super_on_prepare=True, consider_scores_of_zero=True)
        social_mixer = services.autonomy_service().find_best_action(autonomy_request)
        if social_mixer and not social_mixer.super_interaction.running:
            social_mixer.super_interaction = None
        for si in autonomy_request.interactions_to_invalidate:
            si.invalidate()
        autonomy_request.interactions_to_invalidate.clear()
        if social_mixer:
            return AffordanceObjectPair.execute_interaction(social_mixer)
        return event_testing.results.EnqueueResult.NONE

sims4.tuning.instances.lock_instance_tunables(SocialPickerSuperInteraction, allow_autonomous=True, allow_user_directed=False)
