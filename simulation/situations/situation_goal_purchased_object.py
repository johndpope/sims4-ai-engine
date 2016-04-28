import event_testing.test_variants
import services
import sims4.tuning.instances
from sims4.tuning.tunable_base import GroupNames
import situations.situation_goal

class SituationGoalPurchasedObject(situations.situation_goal.SituationGoal):
    __qualname__ = 'SituationGoalPurchasedObject'
    INSTANCE_TUNABLES = {'purchased_object_test': event_testing.test_variants.TunableObjectPurchasedTest(description='\n                A test to determine the items that the player purchases out\n                of build buy.\n                ', tuning_group=GroupNames.TESTS)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        services.get_event_manager().register(self, self.purchased_object_test.test_events)

    def decommision(self):
        services.get_event_manager().unregister(self, self.purchased_object_test.test_events)
        super().decommision()

    def _run_goal_completion_tests(self, sim_info, event, resolver):
        if not resolver(self.purchased_object_test):
            return False
        return super()._run_goal_completion_tests(sim_info, event, resolver)

    @property
    def _numerical_token(self):
        return int(self.purchased_object_test.value)

sims4.tuning.instances.lock_instance_tunables(SituationGoalPurchasedObject, _iterations=1, _post_tests=event_testing.tests.TestList())
