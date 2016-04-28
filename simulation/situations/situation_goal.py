from clock import interval_in_sim_minutes
from event_testing.resolver import Resolver, SingleSimResolver
from event_testing.results import TestResult
from interactions import ParticipantType, ParticipantTypeActorTargetSim
from interactions.money_payout import MoneyChange
from sims4.callback_utils import CallableList
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.instances import HashedTunedInstanceMetaclass, TunedInstanceMetaclass
from sims4.tuning.tunable import Tunable, TunableEnumEntry, TunableList, TunableReference, TunableSet, TunableTuple, TunableVariant, TunableResourceKey, TunableSimMinute, HasTunableReference, OptionalTunable
from sims4.tuning.tunable_base import GroupNames
from statistics.statistic_ops import TunableStatisticChange
from tag import Tag
from ui.ui_dialog import UiDialogOk
from ui.ui_dialog_notification import UiDialogNotification
import buffs.buff_ops
import event_testing.test_variants
import event_testing.tests
import services
import sims4.resources
import situations

class TunableWeightedSituationGoalReference(TunableTuple):
    __qualname__ = 'TunableWeightedSituationGoalReference'

    def __init__(self, **kwargs):
        super().__init__(weight=Tunable(float, 1.0, description='Higher number means higher chance of being selected.'), goal=TunableReference(services.get_instance_manager(sims4.resources.Types.SITUATION_GOAL), description='A goal in the set.'))

class TunableSituationGoalPreTestVariant(TunableVariant):
    __qualname__ = 'TunableSituationGoalPreTestVariant'

    def __init__(self, description='A single tunable test.', **kwargs):
        super().__init__(statistic=event_testing.test_variants.TunableStatThresholdTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), skill_tag=event_testing.test_variants.TunableSkillTagThresholdTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), mood=event_testing.test_variants.TunableMoodTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), sim_info=event_testing.test_variants.TunableSimInfoTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), location=event_testing.test_variants.TunableLocationTest(locked_args={'subject': ParticipantType.Actor, 'tooltip': None}), lot_owner=event_testing.test_variants.TunableLotOwnerTest(locked_args={'subject': ParticipantType.Actor, 'tooltip': None}), sim_filter=event_testing.test_variants.TunableFilterTest(locked_args={'filter_target': ParticipantType.Actor, 'tooltip': None}), trait=event_testing.test_variants.TunableTraitTest(locked_args={'subject': ParticipantType.Actor, 'tooltip': None}), buff=event_testing.test_variants.TunableBuffTest(locked_args={'subject': ParticipantType.Actor, 'tooltip': None}), motive=event_testing.test_variants.TunableMotiveThresholdTestTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), skill_test=event_testing.test_variants.SkillRangeTest.TunableFactory(locked_args={'tooltip': None}), career=event_testing.test_variants.TunableCareerTest.TunableFactory(locked_args={'tooltip': None}), object_criteria=event_testing.test_variants.ObjectCriteriaTest.TunableFactory(locked_args={'tooltip': None}), collection=event_testing.test_variants.TunableCollectionThresholdTest(locked_args={'who': ParticipantType.Actor, 'tooltip': None}), relationship=event_testing.test_variants.TunableRelationshipTest(locked_args={'subject': ParticipantType.Actor, 'test_event': 0, 'tooltip': None}), inventory=event_testing.test_variants.InventoryTest.TunableFactory(locked_args={'tooltip': None}), description=description, **kwargs)

class TunableSituationGoalPreTestSet(event_testing.tests.TestListLoadingMixin):
    __qualname__ = 'TunableSituationGoalPreTestSet'
    DEFAULT_LIST = event_testing.tests.TestList()

    def __init__(self, description=None, **kwargs):
        if description is None:
            description = 'A list of tests.  All tests must succeed to pass the TestSet.'
        super().__init__(description=description, tunable=TunableSituationGoalPreTestVariant(), **kwargs)

class TunableSituationGoalPostTestVariant(TunableVariant):
    __qualname__ = 'TunableSituationGoalPostTestVariant'

    def __init__(self, description='A single tunable test.', **kwargs):
        super().__init__(state=event_testing.test_variants.TunableStateTest(locked_args={'who': ParticipantType.Object, 'tooltip': None}), statistic=event_testing.test_variants.TunableStatThresholdTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor), locked_args={'tooltip': None}), relative_statistic=event_testing.test_variants.TunableRelativeStatTest(locked_args={'source': ParticipantType.Actor, 'target': ParticipantType.TargetSim}), skill_tag=event_testing.test_variants.TunableSkillTagThresholdTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor), locked_args={'tooltip': None}), mood=event_testing.test_variants.TunableMoodTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor), locked_args={'tooltip': None}), sim_info=event_testing.test_variants.TunableSimInfoTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor), locked_args={'tooltip': None}), location=event_testing.test_variants.TunableLocationTest(locked_args={'tooltip': None}), lot_owner=event_testing.test_variants.TunableLotOwnerTest(locked_args={'tooltip': None}), sim_filter=event_testing.test_variants.TunableFilterTest(locked_args={'tooltip': None}), trait=event_testing.test_variants.TunableTraitTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor), locked_args={'tooltip': None}), topic=event_testing.test_variants.TunableTopicTest(locked_args={'subject': ParticipantType.Actor, 'target_sim': ParticipantType.TargetSim, 'tooltip': None}), buff=event_testing.test_variants.TunableBuffTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor), locked_args={'tooltip': None}), motive=event_testing.test_variants.TunableMotiveThresholdTestTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor), locked_args={'tooltip': None}), situation_job=event_testing.test_variants.TunableSituationJobTest(locked_args={'participant': ParticipantType.Actor, 'tooltip': None}), career=event_testing.test_variants.TunableCareerTest.TunableFactory(locked_args={'tooltip': None}), description=description, **kwargs)

class TunableSituationGoalPostTestSet(event_testing.tests.TestListLoadingMixin):
    __qualname__ = 'TunableSituationGoalPostTestSet'
    DEFAULT_LIST = event_testing.tests.TestList()

    def __init__(self, description=None, **kwargs):
        if description is None:
            description = 'A list of tests.  All tests must succeed to pass the TestSet.'
        super().__init__(description=description, tunable=TunableSituationGoalPostTestVariant(), **kwargs)

class TunableSituationGoalEnvironmentPreTestVariant(TunableVariant):
    __qualname__ = 'TunableSituationGoalEnvironmentPreTestVariant'

    def __init__(self, description='A single tunable test.', **kwargs):
        super().__init__(object_criteria=event_testing.test_variants.ObjectCriteriaTest.TunableFactory(locked_args={'tooltip': None}), description=description, **kwargs)

class TunableSituationGoalEnvironmentPreTestSet(event_testing.tests.TestListLoadingMixin):
    __qualname__ = 'TunableSituationGoalEnvironmentPreTestSet'
    DEFAULT_LIST = event_testing.tests.TestList()

    def __init__(self, description=None, **kwargs):
        if description is None:
            description = 'A list of tests.  All tests must succeed to pass the TestSet.'
        super().__init__(description=description, tunable=TunableSituationGoalEnvironmentPreTestVariant(), **kwargs)

class SituationGoalLootActions(HasTunableReference, metaclass=TunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.ACTION)):
    __qualname__ = 'SituationGoalLootActions'
    INSTANCE_TUNABLES = {'goal_loot_actions': TunableList(TunableVariant(statistics=TunableStatisticChange(locked_args={'subject': ParticipantType.Actor, 'advertise': False, 'chance': 1, 'tests': None}), money_loot=MoneyChange.TunableFactory(locked_args={'subject': ParticipantType.Actor, 'chance': 1, 'tests': None, 'display_to_user': None, 'statistic_multipliers': None}), buff=buffs.buff_ops.BuffOp.TunableFactory(locked_args={'subject': ParticipantType.Actor, 'chance': 1, 'tests': None})))}

    def __iter__(self):
        return iter(self.goal_loot_actions)

class SituationGoal(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.SITUATION_GOAL)):
    __qualname__ = 'SituationGoal'
    INSTANCE_SUBCLASSES_ONLY = True
    IS_TARGETED = False
    INSTANCE_TUNABLES = {'_display_name': TunableLocalizedStringFactory(description='\n                Display name for the Situation Goal. It takes one token, the\n                target (0) of this situation goal.\n                ', tuning_group=GroupNames.UI), '_icon': TunableResourceKey('PNG:missing_image', description='\n                Icon to be displayed for the Situation Goal.\n                ', needs_tuning=True, resource_types=sims4.resources.CompoundTypes.IMAGE), '_pre_tests': TunableSituationGoalPreTestSet(description='\n                A set of tests on the player sim and environment that all must\n                pass for the goal to be given to the player. e.g. Player Sim\n                has cooking skill level 7.\n                ', tuning_group=GroupNames.TESTS), '_post_tests': TunableSituationGoalPostTestSet(description='\n                A set of tests that must all pass when the player satisfies the\n                goal_test for the goal to be consider completed. e.g. Player\n                has Drunk Buff when Kissing another sim at Night.\n                ', tuning_group=GroupNames.TESTS), '_environment_pre_tests': TunableSituationGoalEnvironmentPreTestSet(description='\n                A set of sim independent pre tests.\n                e.g. There are five desks.\n                ', tuning_group=GroupNames.TESTS), 'role_tags': TunableSet(TunableEnumEntry(Tag, Tag.INVALID), description='\n                This goal will only be given to Sims in SituationJobs or Role\n                States marked with one of these tags.\n                '), '_cooldown': TunableSimMinute(description='\n                The cooldown of this situation goal.  Goals that have been\n                completed will not be chosen again for the amount of time that\n                is tuned.\n                ', default=600, minimum=0), '_iterations': Tunable(description='\n                     Number of times the player must perform the action to complete the goal\n                     ', tunable_type=int, default=1), '_score': Tunable(description='\n                    The number of points received for completing the goal.\n                    ', tunable_type=int, default=10), '_goal_loot_list': TunableList(description='\n            A list of pre-defined loot actions that will applied to every\n            sim in the situation when this situation goal is completed.\n             \n            Do not use this loot list in an attempt to undo changes made by\n            the RoleStates to the sim. For example, do not attempt\n            to remove buffs or commodities added by the RoleState.\n            ', tunable=SituationGoalLootActions.TunableReference()), '_tooltip': TunableLocalizedStringFactory(description='\n            Tooltip for this situation goal. It takes one token, the\n            actor (0) of this situation goal.'), 'noncancelable': Tunable(description='\n            Checking this box will prevent the player from canceling this goal in the whim system.', tunable_type=bool, needs_tuning=True, default=False), 'time_limit': Tunable(description='\n            Timeout (in Sim minutes) for Sim to complete this goal. The default state of 0 means\n            time is unlimited. If the goal is not completed in time, any tuned penalty loot is applied.', tunable_type=int, default=0), 'penalty_loot_list': TunableList(description='\n            A list of pre-defined loot actions that will applied to the Sim who fails\n            to complete this goal within the tuned time limit.\n            ', tunable=SituationGoalLootActions.TunableReference()), 'goal_completion_notification': OptionalTunable(tunable=UiDialogNotification.TunableFactory(description='\n                A TNS that will fire when this situation goal is completed.\n                ')), 'audio_sting_on_complete': TunableResourceKey(description='\n            The sound to play when this goal is completed.\n            ', default=None, resource_types=(sims4.resources.Types.PROPX,), tuning_group=GroupNames.AUDIO), 'goal_completion_modal_dialog': OptionalTunable(tunable=UiDialogOk.TunableFactory(description='\n                A modal dialog that will fire when this situation goal is\n                completed.\n                '))}

    @classmethod
    def can_be_given_as_goal(cls, actor, situation, **kwargs):
        if actor is not None:
            resolver = event_testing.resolver.DataResolver(actor.sim_info, None)
            result = cls._pre_tests.run_tests(resolver)
            if not result:
                return result
        environment_test_result = cls._environment_pre_tests.run_tests(Resolver())
        if not environment_test_result:
            return environment_test_result
        return TestResult.TRUE

    def __init__(self, sim_info=None, situation=None, goal_id=0, count=0, **kwargs):
        self._sim_info = sim_info
        self._situation = situation
        self.id = goal_id
        self._on_goal_completed_callbacks = CallableList()
        self._completed_time = None
        self._count = count

    def destroy(self):
        self.decommision()
        self._sim_info = None
        self._situation = None

    def decommision(self):
        self._on_goal_completed_callbacks.clear()

    def create_seedling(self):
        actor_id = 0 if self._sim_info is None else self._sim_info.sim_id
        seedling = situations.situation_serialization.GoalSeedling(type(self), actor_id, self._count)
        return seedling

    def register_for_on_goal_completed_callback(self, listener):
        self._on_goal_completed_callbacks.append(listener)

    def unregister_for_on_goal_completed_callback(self, listener):
        self._on_goal_completed_callbacks.remove(listener)

    def get_gsi_name(self):
        if self._iterations <= 1:
            return self.__class__.__name__
        return '{} {}/{}'.format(self.__class__.__name__, self._count, self._iterations)

    def _on_goal_completed(self):
        self._completed_time = services.time_service().sim_now
        for loots in self._goal_loot_list:
            for loot in loots.goal_loot_actions:
                for sim in self._situation.all_sims_in_situation_gen():
                    loot.apply_to_resolver(sim.get_resolver())
        client = services.client_manager().get_first_client()
        if client is not None:
            active_sim = client.active_sim
            resolver = SingleSimResolver(active_sim)
            if self.goal_completion_notification is not None:
                notification = self.goal_completion_notification(active_sim, resolver=resolver)
                notification.show_dialog()
            if self.goal_completion_modal_dialog is not None:
                dialog = self.goal_completion_modal_dialog(active_sim, resolver=resolver)
                dialog.show_dialog()
        self._on_goal_completed_callbacks(self, True)

    def _on_iteration_completed(self):
        self._on_goal_completed_callbacks(self, False)

    def debug_force_complete(self, target_sim):
        self._count = self._iterations
        self._on_goal_completed()

    def handle_event(self, sim_info, event, resolver):
        if self._sim_info is not None and self._sim_info is not sim_info:
            return
        if self._run_goal_completion_tests(sim_info, event, resolver):
            if self._count >= self._iterations:
                self._on_goal_completed()
            else:
                self._on_iteration_completed()

    def _run_goal_completion_tests(self, sim_info, event, resolver):
        return self._post_tests.run_tests(resolver)

    def _get_actual_target_sim_info(self):
        pass

    def get_required_target_sim_info(self):
        pass

    @property
    def created_time(self):
        pass

    @property
    def completed_time(self):
        return self._completed_time

    def is_on_cooldown(self):
        if self._completed_time is None:
            return False
        time_since_last_completion = services.time_service().sim_now - self._completed_time
        return time_since_last_completion < interval_in_sim_minutes(self._cooldown)

    def get_localization_tokens(self):
        if self._sim_info is None:
            return (self._numerical_token,)
        required_tgt_sim = self.get_required_target_sim_info()
        if required_tgt_sim is None:
            return (self._numerical_token, self._sim_info)
        return (self._numerical_token, self._sim_info, required_tgt_sim)

    @property
    def display_name(self):
        return self._display_name(*self.get_localization_tokens())

    @property
    def tooltip(self):
        return self._tooltip(*self.get_localization_tokens())

    @property
    def score(self):
        return self._score

    @property
    def completed_iterations(self):
        return self._count

    @property
    def max_iterations(self):
        return self._iterations

    @property
    def _numerical_token(self):
        return self.max_iterations

