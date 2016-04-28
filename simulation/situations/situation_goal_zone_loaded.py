from event_testing import test_events
import services
from sims4.tuning.tunable_base import GroupNames
from situations.situation_goal import SituationGoal
from situations.situation_goal_actor import TunableSituationGoalActorPostTestSet

class SituationGoalZoneLoaded(SituationGoal):
    __qualname__ = 'SituationGoalZoneLoaded'
    INSTANCE_TUNABLES = {'_post_tests': TunableSituationGoalActorPostTestSet(description='\n                A set of tests that must all pass when zone has finished loading.\n                ', tuning_group=GroupNames.TESTS)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._test_events = set()
        self._test_events.add(test_events.TestEvent.LoadingScreenLifted)
        services.get_event_manager().register(self, self._test_events)

    def decommision(self):
        services.get_event_manager().unregister(self, self._test_events)
        super().decommision()

