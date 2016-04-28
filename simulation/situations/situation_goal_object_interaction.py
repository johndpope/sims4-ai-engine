from event_testing.results import TestResult
from event_testing.tests_with_data import TunableParticipantRanInteractionTest
from interactions import ParticipantType
from sims4.tuning.tunable import TunableVariant
from sims4.tuning.tunable_base import GroupNames
from situations.situation_goal import SituationGoal
import event_testing.test_variants
import services

class TunableSituationGoalActorObjectPostTestVariant(TunableVariant):
    __qualname__ = 'TunableSituationGoalActorObjectPostTestVariant'

    def __init__(self, description='A single tunable test.', **kwargs):
        super().__init__(state=event_testing.test_variants.TunableStateTest(locked_args={'who': ParticipantType.Object, 'tooltip': None}), statistic=event_testing.test_variants.TunableStatThresholdTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), skill_tag=event_testing.test_variants.TunableSkillTagThresholdTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), mood=event_testing.test_variants.TunableMoodTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), location=event_testing.test_variants.TunableLocationTest(locked_args={'subject': ParticipantType.Actor, 'tooltip': None}), sim_info=event_testing.test_variants.TunableSimInfoTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), trait=event_testing.test_variants.TunableTraitTest(locked_args={'subject': ParticipantType.Actor, 'tooltip': None}), topic=event_testing.test_variants.TunableTopicTest(locked_args={'subject': ParticipantType.Actor, 'target_sim': ParticipantType.TargetSim, 'tooltip': None}), buff=event_testing.test_variants.TunableBuffTest(locked_args={'subject': ParticipantType.Actor, 'tooltip': None}), motive=event_testing.test_variants.TunableMotiveThresholdTestTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), situation_job=event_testing.test_variants.TunableSituationJobTest(locked_args={'participant': ParticipantType.Actor, 'tooltip': None}), description=description, **kwargs)

class TunableSituationGoalActorObjectPostTestSet(event_testing.tests.TestListLoadingMixin):
    __qualname__ = 'TunableSituationGoalActorObjectPostTestSet'
    DEFAULT_LIST = event_testing.tests.TestList()

    def __init__(self, description=None, **kwargs):
        if description is None:
            description = 'A list of tests.  All tests must succeed to pass the TestSet.'
        super().__init__(description=description, tunable=TunableSituationGoalActorObjectPostTestVariant(), **kwargs)

class SituationGoalObjectInteraction(SituationGoal):
    __qualname__ = 'SituationGoalObjectInteraction'
    INSTANCE_TUNABLES = {'_goal_test': TunableParticipantRanInteractionTest(locked_args={'participant': ParticipantType.Actor, 'tooltip': None}, tuning_group=GroupNames.TESTS), '_post_tests': TunableSituationGoalActorObjectPostTestSet(description='\n                A set of tests that must all pass when the player satisfies the goal_test \n                for the goal to be consider completed.', tuning_group=GroupNames.TESTS)}

    @classmethod
    def can_be_given_as_goal(cls, actor, situation, **kwargs):
        result = super(SituationGoalObjectInteraction, cls).can_be_given_as_goal(actor, situation)
        if not result:
            return result
        return TestResult.TRUE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        services.get_event_manager().register(self, self._goal_test.test_events)

    def decommision(self):
        services.get_event_manager().unregister(self, self._goal_test.test_events)
        super().decommision()

    def _run_goal_completion_tests(self, sim_info, event, resolver):
        if not resolver(self._goal_test):
            return False
        return super()._run_goal_completion_tests(sim_info, event, resolver)

