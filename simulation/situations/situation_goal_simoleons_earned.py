import event_testing
from event_testing.results import TestResult
import services
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import AutoFactoryInit, TunableSingletonFactory, TunableRange, TunableSet, TunableEnumEntry
from sims4.tuning.tunable_base import GroupNames
from situations.situation_goal import SituationGoal
from tag import Tag

class EarningsOfInterest(AutoFactoryInit):
    __qualname__ = 'EarningsOfInterest'
    FACTORY_TUNABLES = {'tags': TunableSet(description='\n                A set of tags that will match an affordance instead of looking\n                for a specific one. If you leave this empty, all Simoleons earned will be counted.\n                ', tunable=TunableEnumEntry(Tag, Tag.INVALID)), 'amount_to_earn': TunableRange(description='\n                The amount of time in Simoleons earned from all relevant activities for this\n                goal to pass.\n                ', tunable_type=int, default=10, minimum=1)}

    def get_expected_args(self):
        return {'amount': event_testing.test_events.FROM_EVENT_DATA, 'tags': event_testing.test_events.FROM_EVENT_DATA}

    def __call__(self, amount=None, tags=None):
        if amount is None:
            return TestResult(False, 'Amount is None')
        if len(self.tags) == 0 or tags is not None and self.tags & tags:
            if amount > 0:
                return TestResult.TRUE
            return TestResult(False, 'No money earned')
        return TestResult(False, 'Failed relevant tags check: Earnings do not have any matching tags in {}.', self.tags)

TunableEarningsOfInterest = TunableSingletonFactory.create_auto_factory(EarningsOfInterest)

class SituationGoalSimoleonsEarned(SituationGoal):
    __qualname__ = 'SituationGoalSimoleonsEarned'
    SIMOLEONS_EARNED = 'simoleons_earned'
    REMOVE_INSTANCE_TUNABLES = ('_post_tests',)
    INSTANCE_TUNABLES = {'_goal_test': TunableEarningsOfInterest(description='\n                Interaction and Simoleon amount that this situation goal will use.\n                Example: Earn 1000 Simoleons from Bartending activities.\n                ', tuning_group=GroupNames.TESTS)}

    def __init__(self, *args, reader=None, **kwargs):
        super().__init__(reader=reader, *args, **kwargs)
        self._total_simoleons_earned = 0
        self._test_events = set()
        self._test_events.add(event_testing.test_events.TestEvent.SimoleonsEarned)
        services.get_event_manager().register(self, self._test_events)
        if reader is not None:
            simoleons_earned = reader.read_uint64(self.SIMOLEONS_EARNED, 0)
            self._total_simoleons_earned = simoleons_earned

    def create_seedling(self):
        seedling = super().create_seedling()
        writer = seedling.writer
        writer.write_uint64(self.SIMOLEONS_EARNED, self._total_simoleons_earned)
        return seedling

    def decommision(self):
        services.get_event_manager().unregister(self, self._test_events)
        super().decommision()

    def _run_goal_completion_tests(self, sim_info, event, resolver):
        if not resolver(self._goal_test):
            return False
        amount_to_add = resolver.get_resolved_arg('amount')
        if self._total_simoleons_earned >= self._goal_test.amount_to_earn:
            super()._on_goal_completed()
        else:
            self._on_iteration_completed()

    @property
    def completed_iterations(self):
        return self._total_simoleons_earned

    @property
    def max_iterations(self):
        return self._goal_test.amount_to_earn

lock_instance_tunables(SituationGoalSimoleonsEarned, _iterations=1)
