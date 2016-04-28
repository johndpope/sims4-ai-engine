from autonomy.autonomy_modes import FullAutonomy
from autonomy.autonomy_request import AutonomyRequest, AutonomyDistanceEstimationBehavior
from interactions.context import InteractionContext, InteractionSource
from interactions.priority import Priority
from objects.components.autonomy import AutonomyComponent
from sims4.tuning.tunable import HasTunableFactory, TunableEnumEntry, AutoFactoryInit, Tunable
from sims4.tuning.tunable_base import FilterTag
from snippets import TunableAffordanceFilterSnippet
import services

class ServicePrerollAutonomy(HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'ServicePrerollAutonomy'
    FACTORY_TUNABLES = {'description': '\n        A tunable to specify tests/settings for how to post process a\n        manual autonomy request on a sim. EX: preroll autonomy for the maid\n        when she first gets onto the lot has an affordance link that\n        blacklists her from doing the serviceNpc_noMoreWork\n        interaction.', 'super_affordance_compatibility': TunableAffordanceFilterSnippet(), 'preroll_source': TunableEnumEntry(description='\n            The source of the context of the autonomy roll.\n            Whether you want the autonomy roll to pretend like it was autonomy\n            that did the tests for available interactions or have the interaction\n            be tested and run as if it was user directed.\n            ', tunable_type=InteractionSource, default=InteractionSource.AUTONOMY, tuning_filter=FilterTag.EXPERT_MODE), 'preroll_priority': TunableEnumEntry(description="\n            The priority of the context of the autonomy roll.\n            Use this if you want the preroll's priority to either be higher or\n            lower because the sim could be running another interaction at\n            the time preroll autonomy ping is run.\n            ", tunable_type=Priority, default=Priority.Low, tuning_filter=FilterTag.EXPERT_MODE), 'allow_unreachable_destinations': Tunable(description="\n            If checked, autonomy will allow interactions that WILL fail when\n            run because the objects are unreachable. If not checked, autonomy\n            won't even return interactions that have unreachable destinations.\n            Interactions with unreachable destinations will just score really\n            high instead of be tested out.\n            \n            This is checked to true for things like the mailman where we want\n            him to do a failure transition when delivering mail to an unreachable\n            mailbox so it's visible to the player that the mailbox is unroutable.\n            ", tunable_type=bool, default=False)}

    def run_preroll(self, sim):
        autonomy_service = services.autonomy_service()
        context = InteractionContext(sim, self.preroll_source, self.preroll_priority, client=None, pick=None)
        autonomy_distance_estimation_behavior = AutonomyDistanceEstimationBehavior.ALLOW_UNREACHABLE_LOCATIONS if self.allow_unreachable_destinations else AutonomyDistanceEstimationBehavior.FULL
        autonomy_request = AutonomyRequest(sim, autonomy_mode=FullAutonomy, skipped_static_commodities=AutonomyComponent.STANDARD_STATIC_COMMODITY_SKIP_SET, limited_autonomy_allowed=False, context=context, distance_estimation_behavior=autonomy_distance_estimation_behavior, autonomy_mode_label_override='NPCPrerollAutonomy')
        scored_interactions = autonomy_service.score_all_interactions(autonomy_request)
        compatible_scored_interactions = tuple([scored_interaction_data for scored_interaction_data in scored_interactions if self.super_affordance_compatibility(scored_interaction_data.interaction.affordance)])
        chosen_interaction = autonomy_service.choose_best_interaction(compatible_scored_interactions, autonomy_request)
        autonomy_request.invalidate_created_interactions(excluded_si=chosen_interaction)
        return chosen_interaction

