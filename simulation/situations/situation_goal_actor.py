from event_testing.results import TestResult
from interactions import ParticipantType
from sims4.tuning.tunable import TunableVariant, Tunable
from sims4.tuning.tunable_base import GroupNames
from situations.situation_goal import SituationGoal
import event_testing.test_variants
import services
import sims4.tuning.tunable

class TunableSituationGoalActorPostTestVariant(TunableVariant):
    __qualname__ = 'TunableSituationGoalActorPostTestVariant'

    def __init__(self, description='A single tunable test.', **kwargs):
        super().__init__(statistic=event_testing.test_variants.TunableStatThresholdTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), skill_tag=event_testing.test_variants.TunableSkillTagThresholdTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), mood=event_testing.test_variants.TunableMoodTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), sim_info=event_testing.test_variants.TunableSimInfoTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), location=event_testing.test_variants.TunableLocationTest(locked_args={'subject': ParticipantType.Actor, 'tooltip': None}), lot_owner=event_testing.test_variants.TunableLotOwnerTest(locked_args={'subject': ParticipantType.Actor, 'tooltip': None}), sim_filter=event_testing.test_variants.TunableFilterTest(locked_args={'filter_target': ParticipantType.Actor, 'tooltip': None}), trait=event_testing.test_variants.TunableTraitTest(locked_args={'subject': ParticipantType.Actor, 'tooltip': None}), buff=event_testing.test_variants.TunableBuffTest(locked_args={'subject': ParticipantType.Actor, 'tooltip': None}), motive=event_testing.test_variants.TunableMotiveThresholdTestTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), skill_test=event_testing.test_variants.SkillRangeTest.TunableFactory(locked_args={'tooltip': None}), situation_job=event_testing.test_variants.TunableSituationJobTest(locked_args={'participant': ParticipantType.Actor, 'tooltip': None}), career=event_testing.test_variants.TunableCareerTest.TunableFactory(locked_args={'subjects': ParticipantType.Actor, 'tooltip': None}), collection=event_testing.test_variants.TunableCollectionThresholdTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), description=description, **kwargs)

class TunableSituationGoalActorPostTestSet(event_testing.tests.TestListLoadingMixin):
    __qualname__ = 'TunableSituationGoalActorPostTestSet'
    DEFAULT_LIST = event_testing.tests.TestList()

    def __init__(self, description=None, **kwargs):
        if description is None:
            description = 'A list of tests.  All tests must succeed to pass the TestSet.'
        super().__init__(description=description, tunable=TunableSituationGoalActorPostTestVariant(), **kwargs)

class SituationGoalActor(SituationGoal):
    __qualname__ = 'SituationGoalActor'
    INSTANCE_TUNABLES = {'_goal_test': sims4.tuning.tunable.TunableVariant(buff=event_testing.test_variants.TunableBuffTest(locked_args={'subject': ParticipantType.Actor, 'blacklist': None, 'tooltip': None}), mood=event_testing.test_variants.TunableMoodTest(locked_args={'who': ParticipantType.Actor}, description='A test to run to determine if the player has attained a specific mood.'), skill_tag=event_testing.test_variants.TunableSkillTagThresholdTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), statistic=event_testing.test_variants.TunableStatThresholdTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), career=event_testing.test_variants.TunableCareerTest.TunableFactory(locked_args={'tooltip': None}), collection=event_testing.test_variants.TunableCollectionThresholdTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), inventory=event_testing.test_variants.InventoryTest.TunableFactory(locked_args={'tooltip': None}), default='buff', description='Primary test which triggers evaluation of goal completion.', tuning_group=GroupNames.TESTS), '_post_tests': TunableSituationGoalActorPostTestSet(description='\n               A set of tests that must all pass when the player satisfies the goal_test \n               for the goal to be consider completed.\nThese test can only consider the \n               actor and the environment. \ne.g. Practice in front of mirror while drunk.\n               ', tuning_group=GroupNames.TESTS), 'ignore_goal_precheck': Tunable(description='\n            Checking this box will skip the normal goal pre-check in the case that other tuning makes the goal\n            continue to be valid. For example, for a collection test, we may want to give the goal to collect\n            an additional object even though the test that we have collected this object before will already\n            pass. This allows us to tune a more specific pre-test to check for the amount we want to collect.', tunable_type=bool, default=False)}

    @classmethod
    def can_be_given_as_goal(cls, actor, situation, **kwargs):
        result = super(SituationGoalActor, cls).can_be_given_as_goal(actor, situation)
        if not result:
            return result
        if actor is not None and not cls.ignore_goal_precheck:
            resolver = event_testing.resolver.DataResolver(actor.sim_info)
            result = resolver(cls._goal_test)
            if result:
                return TestResult(False, 'Goal test already passes and so cannot be given as goal.')
        return TestResult.TRUE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        reader = kwargs.get('reader', None)
        if reader:
            value = reader.read_uint32('test_int', 27)
        services.get_event_manager().register(self, self._goal_test.test_events)

    def destroy(self):
        services.get_event_manager().unregister(self, self._goal_test.test_events)
        super().destroy()

    def create_seedling(self):
        seedling = super().create_seedling()
        writer = seedling.writer
        writer.write_uint32('test_int', 42)
        return seedling

    def _run_goal_completion_tests(self, sim_info, event, resolver):
        if not resolver(self._goal_test):
            return False
        return super()._run_goal_completion_tests(sim_info, event, resolver)

