import event_testing.test_variants
import services
from sims4.tuning.tunable_base import GroupNames
import situations.situation_goal
import situations.situation_goal_actor

class SituationGoalCraftObject(situations.situation_goal.SituationGoal):
    __qualname__ = 'SituationGoalCraftObject'
    INSTANCE_TUNABLES = {'crafted_item_test': event_testing.test_variants.TunableCraftedItemTest(description='\n                A test to run to determine if the player can have this goal. If crafted_tagged_item \n                is set, the player may craft any item that has the specified tag.', tuning_group=GroupNames.TESTS), '_post_tests': situations.situation_goal_actor.TunableSituationGoalActorPostTestSet(description='\n                A set of tests that must all pass when the player satisfies the crafted_item_test \n                for the goal to be consider completed.\nThese test can only consider the actor and \n                the environment. \ne.g. Make a Scotch and Soda while drunk.', tuning_group=GroupNames.TESTS)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        services.get_event_manager().register(self, self.crafted_item_test.test_events)

    def decommision(self):
        services.get_event_manager().unregister(self, self.crafted_item_test.test_events)
        super().decommision()

    def _run_goal_completion_tests(self, sim_info, event, resolver):
        if not resolver(self.crafted_item_test):
            return False
        return super()._run_goal_completion_tests(sim_info, event, resolver)

