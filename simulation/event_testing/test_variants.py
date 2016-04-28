import itertools
from aspirations.aspiration_types import AspriationType
from broadcasters.environment_score.environment_score_types import EnvironmentScoreType
from build_buy import FloorFeatureType
from event_testing import TargetIdTypes
from event_testing.results import TestResult, TestResultNumeric
from event_testing.test_events import TestEvent, cached_test
from interactions import ParticipantType, ParticipantTypeActorTargetSim, ParticipantTypeSingle, TargetType
from objects import ALL_HIDDEN_REASONS
from objects.slots import RuntimeSlot, SlotType
from server.pick_info import PickTerrainType, PICK_TRAVEL, PickType
from sims.unlock_tracker import TunableUnlockVariant
from sims4.math import Operator
from sims4.tuning.tunable import TunableFactory, TunableEnumEntry, TunableSingletonFactory, Tunable, OptionalTunable, TunableList, TunableTuple, TunableThreshold, TunableSet, TunableReference, TunableVariant, HasTunableSingletonFactory, AutoFactoryInit, TunableSimMinute, TunableInterval, TunableEnumFlags, TunableOperator, TunableEnumSet, TunableRange
from sims4.utils import flexproperty
from statistics.skill import Skill
from terrain import is_position_in_street
import algos
import build_buy
import caches
import clock
import date_and_time
import enum
import event_testing.event_data_const
import event_testing.test_base
import interactions.utils.death
import objects.collection_manager
import objects.components.inventory_enums
import objects.components.statistic_types
import relationships.relationship_bit
import scheduler
import server.config_service
import server.permissions
import services
import sims.bills_enums
import sims4.tuning.tunable
import singletons
import snippets
import statistics.mood
import statistics.statistic_categories
import tag
import tunable_time
logger = sims4.log.Logger('Tests')

class StateTest(event_testing.test_base.BaseTest):
    __qualname__ = 'StateTest'
    test_events = ()
    ALWAYS_PASS = 'always_pass'
    ALWAYS_FAIL = 'always_fail'
    FACTORY_TUNABLES = {'description': "\n        Gate availability by object state.  By default, the test will use the\n        state's linked stat as a fallback in case the target doesn't have the\n        state involved.\n        ", 'who': TunableEnumEntry(description='\n            Who or what to apply this test to.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'operator': TunableOperator(description='\n            The comparison to use.', default=Operator.EQUAL), 'value': TunableReference(description='\n            The value to compare to.', manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions='ObjectStateValue'), 'fallback_behavior': TunableVariant(description="\n            What to do if the given object doesn't have the state in question.\n            ", default=ALWAYS_FAIL, locked_args={ALWAYS_PASS: ALWAYS_PASS, ALWAYS_FAIL: ALWAYS_FAIL})}

    def __init__(self, who, operator, value, fallback_behavior=ALWAYS_FAIL, **kwargs):
        super().__init__(**kwargs)
        self.who = who
        self.operator = operator
        self.operator_enum = Operator.from_function(operator)
        self.value = value
        self.fallback_behavior = fallback_behavior

    def get_expected_args(self):
        return {'test_targets': self.who}

    @cached_test
    def __call__(self, test_targets):
        if not test_targets:
            return TestResult(False, 'failed state check: no target object found!')
        for target in test_targets:
            if target.is_sim:
                if target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                    return TestResult(False, '{} failed state check: It is not an instantiated sim.', target, tooltip=self.tooltip)
                target = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            if target.state_component and target.has_state(self.value.state):
                curr_value = target.get_state(self.value.state)
            else:
                while self.fallback_behavior == self.ALWAYS_FAIL:
                    return TestResult(False, '{} failed state check: {} does not have the {} state.', self.who.name, target.__class__.__name__, self.value.state, tooltip=self.tooltip)
                    if self.operator_enum.category == sims4.math.Operator.EQUAL:
                        if not self.operator(curr_value, self.value):
                            operator_symbol = self.operator_enum.symbol
                            return TestResult(False, '{} failed state check: {}.{} {} {} (current value: {})', self.who.name, target.__class__.__name__, self.value.state, operator_symbol, self.value, curr_value, tooltip=self.tooltip)
                            while not self.operator(curr_value.value, self.value.value):
                                operator_symbol = self.operator_enum.symbol
                                return TestResult(False, '{} failed state check: {}.{} {} {} (current value: {})', self.who.name, target.__class__.__name__, self.value.state, operator_symbol, self.value, curr_value, tooltip=self.tooltip)
                    else:
                        while not self.operator(curr_value.value, self.value.value):
                            operator_symbol = self.operator_enum.symbol
                            return TestResult(False, '{} failed state check: {}.{} {} {} (current value: {})', self.who.name, target.__class__.__name__, self.value.state, operator_symbol, self.value, curr_value, tooltip=self.tooltip)
            if self.operator_enum.category == sims4.math.Operator.EQUAL:
                if not self.operator(curr_value, self.value):
                    operator_symbol = self.operator_enum.symbol
                    return TestResult(False, '{} failed state check: {}.{} {} {} (current value: {})', self.who.name, target.__class__.__name__, self.value.state, operator_symbol, self.value, curr_value, tooltip=self.tooltip)
                    while not self.operator(curr_value.value, self.value.value):
                        operator_symbol = self.operator_enum.symbol
                        return TestResult(False, '{} failed state check: {}.{} {} {} (current value: {})', self.who.name, target.__class__.__name__, self.value.state, operator_symbol, self.value, curr_value, tooltip=self.tooltip)
            else:
                while not self.operator(curr_value.value, self.value.value):
                    operator_symbol = self.operator_enum.symbol
                    return TestResult(False, '{} failed state check: {}.{} {} {} (current value: {})', self.who.name, target.__class__.__name__, self.value.state, operator_symbol, self.value, curr_value, tooltip=self.tooltip)
        return TestResult.TRUE

    def _get_make_true_value(self):
        for value in algos.binary_walk_gen(self.value.state.values):
            while self.operator(value.value, self.value.value):
                return (TestResult.TRUE, value)
        operator_symbol = Operator.from_function(self.operator).symbol
        return (TestResult(False, 'Could not find value to satisfy operation: {} {} {}', self.value.state, operator_symbol, self.value), None)

    def _can_make_pass(self, test_targets):
        if self.fallback_behavior == self.ALWAYS_FAIL:
            for target in test_targets:
                if target.is_sim:
                    if target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                        return TestResult(False, 'Cannot add missing state to {} since it is not an instantiated sim.', target, tooltip=self.tooltip)
                    target = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
                if target.state_component and target.has_state(self.value.state):
                    pass
        (result, _) = self._get_make_true_value()
        return result

    def _make_pass(self, test_targets):
        (result, value) = self._get_make_true_value()
        if not result:
            return result
        operator_symbol = self.operator_enum.symbol
        for target in test_targets:
            if target.is_sim:
                if target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                    pass
                target = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            while target.state_component and target.has_state(self.value.state):
                target.set_state(value.state, value)
                self.log_make_pass_action('{}: set {}.{} to {} ({} {})'.format(self.who.name, target.__class__.__name__, self.value.state, value, operator_symbol, self.value))
        return TestResult.TRUE

TunableStateTest = TunableSingletonFactory.create_auto_factory(StateTest)

class MotiveThresholdTest(event_testing.test_base.BaseTest):
    __qualname__ = 'MotiveThresholdTest'
    test_events = (TestEvent.MotiveLevelChange,)

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'who': TunableEnumEntry(participant_type_enum, participant_type_default, description='Who or what to apply this test to')}

    FACTORY_TUNABLES = {'description': 'Tests for a provided level on one or many motives.', 'who': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), 'stats': TunableList(TunableReference(services.statistic_manager(), description='The stat we are operating on.')), 'threshold': TunableThreshold(description="The threshold to control availability based on the statistic's value")}

    def __init__(self, who, stats, threshold, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.who = who
        self.stats = stats
        self.threshold = threshold

    def get_expected_args(self):
        return {'test_targets': self.who}

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            if self.stats is None:
                return TestResult(False, 'Stat failed to load.')
            if target is None:
                logger.error('Trying to call MotiveThresholdTest on {} which is None', target)
                return TestResult(False, 'Target({}) does not exist', self.who)
            for stat in self.stats:
                tracker = target.get_tracker(stat)
                curr_value = tracker.get_user_value(stat)
                while not self.threshold.compare(curr_value):
                    operator_symbol = Operator.from_function(self.threshold.comparison).symbol
                    return TestResult(False, '{} failed stat check: {}.{} {} {} (current value: {})', self.who.name, target.__class__.__name__, stat.__name__, operator_symbol, self.threshold.value, curr_value, tooltip=self.tooltip)
        return TestResult.TRUE

    def tuning_is_valid(self):
        return len(self.stats) != 0

TunableMotiveThresholdTestTest = TunableSingletonFactory.create_auto_factory(MotiveThresholdTest)

class CollectionThresholdTest(event_testing.test_base.BaseTest):
    __qualname__ = 'CollectionThresholdTest'
    test_events = (TestEvent.CollectedSomething,)

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'who': TunableEnumEntry(participant_type_enum, participant_type_default, description='Who or what to apply this test to')}

    FACTORY_TUNABLES = {'description': 'Tests for a provided amount of a given collection type.', 'who': TunableEnumEntry(description='\n            Who or what to apply this test to\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'collection_type': TunableEnumEntry(description='\n            The collection we are checking on.  If collection type is\n            unidentified then we will look through all collections.\n            ', tunable_type=objects.collection_manager.CollectionIdentifier, default=objects.collection_manager.CollectionIdentifier.Unindentified), 'complete_collection': Tunable(description='\n            Setting this to True (checked) will override the threshold and\n            check for collection completed\n            ', tunable_type=bool, needs_tuning=True, default=False), 'threshold': TunableThreshold(description='\n            Threshold for which the Sim experiences motive failure\n            ', value=Tunable(description='\n                The value of the threshold that the collection is compared\n                against.\n                ', tunable_type=int, default=1), default=sims4.math.Threshold(1, sims4.math.Operator.GREATER_OR_EQUAL.function))}

    def __init__(self, who, collection_type, complete_collection, threshold, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.who = who
        self.collection_type = collection_type
        self.complete_collection = complete_collection
        self.threshold = threshold

    def get_expected_args(self):
        return {'test_targets': self.who}

    @cached_test
    def __call__(self, test_targets=None):
        if test_targets is None:
            return TestResult(False, 'Test Targets are None, valid during zone load.')
        curr_value = 0
        for target in test_targets:
            household = target.household
            if household is None:
                return TestResult(False, 'Household is None when running test, valid during zone load.')
            collection_tracker = household.collection_tracker
            if self.complete_collection:
                if self.collection_type == objects.collection_manager.CollectionIdentifier.Unindentified:
                    while True:
                        for collection_id in objects.collection_manager.CollectionIdentifier:
                            while collection_id != objects.collection_manager.CollectionIdentifier.Unindentified:
                                if collection_tracker.check_collection_complete_by_id(collection_id):
                                    curr_value += 1
                        curr_value += 1
                else:
                    curr_value += 1
                    if self.collection_type == objects.collection_manager.CollectionIdentifier.Unindentified:
                        for collection_id in objects.collection_manager.CollectionIdentifier:
                            while collection_id != objects.collection_manager.CollectionIdentifier.Unindentified:
                                curr_value += collection_tracker.get_collected_items_per_collection_id(collection_id)
                    else:
                        curr_value += collection_tracker.get_collected_items_per_collection_id(self.collection_type)
            elif self.collection_type == objects.collection_manager.CollectionIdentifier.Unindentified:
                for collection_id in objects.collection_manager.CollectionIdentifier:
                    while collection_id != objects.collection_manager.CollectionIdentifier.Unindentified:
                        curr_value += collection_tracker.get_collected_items_per_collection_id(collection_id)
            else:
                curr_value += collection_tracker.get_collected_items_per_collection_id(self.collection_type)
        if self.threshold.compare(curr_value):
            return TestResult.TRUE
        operator_symbol = Operator.from_function(self.threshold.comparison).symbol
        return TestResultNumeric(False, '{} failed collection check: {} {} {}', self.who.name, curr_value, operator_symbol, self.threshold.value, current_value=curr_value, goal_value=self.threshold.value, is_money=False, tooltip=self.tooltip)

    def goal_value(self):
        if self.complete_collection:
            return 1
        return self.threshold.value

TunableCollectionThresholdTest = TunableSingletonFactory.create_auto_factory(CollectionThresholdTest)

class TunableObjectStateValueThreshold(TunableThreshold):
    __qualname__ = 'TunableObjectStateValueThreshold'

    def __init__(self, **kwargs):

        def threshold_callback(instance_class, tunable_name, source, threshold):
            threshold_value = threshold.value
            if hasattr(threshold_value, 'value'):
                threshold.value = threshold_value.value

        super().__init__(value=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions='ObjectStateValue', **kwargs), callback=threshold_callback)

class StatThresholdTest(event_testing.test_base.BaseTest):
    __qualname__ = 'StatThresholdTest'
    test_events = (TestEvent.SkillLevelChange, TestEvent.StatValueUpdate)

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value.who == ParticipantType.Invalid or value.stat is None or value.threshold is None:
            logger.error('Missing or invalid argument at {}: {}', instance_class, tunable_name)
        if 'Types.INTERACTION' in str(source):
            stat = value.stat
            if stat.is_skill:
                threshold = value.threshold
                if threshold.value == 1.0 and threshold.comparison is sims4.math.Operator.GREATER_OR_EQUAL.function:
                    logger.error('StatThresholdTest for skill ({}) >= 1 is invalid in instance({}). Please remove the test.', stat, instance_class)

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'who': TunableEnumEntry(participant_type_enum, participant_type_default, description='Who or what to apply this test to')}

    FACTORY_TUNABLES = {'verify_tunable_callback': _verify_tunable_callback, 'description': 'Gate availability by a statistic on the actor or target.', 'who': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), 'stat': TunableReference(services.statistic_manager(), description='The stat we are operating on.'), 'threshold': TunableVariant(state_value_threshold=TunableObjectStateValueThreshold(description='The state threshold for this test.'), value_threshold=TunableThreshold(description="The threshold to control availability based on the statistic's value"), default='value_threshold', description='The value or state threshold to test against'), 'must_have_stat': Tunable(description='\n            Setting this to True (checked) will ensure that this test only passes if the tested Sim actually\n            has the statistic referenced. If left False (unchecked), this test will evaluate as if the Sim\n            had the statistic at the value of 0', tunable_type=bool, default=False)}

    def __init__(self, who, stat, threshold, must_have_stat, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.who = who
        self.stat = stat
        self.threshold = threshold
        self.must_have_stat = must_have_stat

    def get_expected_args(self):
        return {'test_targets': self.who, 'statistic': event_testing.test_events.FROM_EVENT_DATA}

    @cached_test
    def __call__(self, test_targets=None, statistic=None):
        if statistic is not None and self.stat is not statistic:
            return TestResult(False, 'Stat being looked for is not the stat that changed.')
        for target in test_targets:
            if self.stat is None:
                return TestResult(False, 'Stat failed to load.')
            if target is None:
                logger.error('Trying to call StatThresholdTest on {} which is None', target)
                return TestResult(False, 'Target({}) does not exist', self.who)
            tracker = target.get_tracker(self.stat)
            curr_value = 0
            stat_inst = tracker.get_statistic(self.stat)
            if not self.stat.is_skill or stat_inst is not None and not stat_inst.is_initial_value:
                curr_value = tracker.get_user_value(self.stat)
            if stat_inst is None and self.must_have_stat:
                return TestResultNumeric(False, '{} Does not have stat: {}.', self.who.name, self.stat.__name__, current_value=curr_value, goal_value=self.threshold.value, is_money=False, tooltip=self.tooltip)
            while not self.threshold.compare(curr_value):
                operator_symbol = Operator.from_function(self.threshold.comparison).symbol
                return TestResultNumeric(False, '{} failed stat check: {}.{} {} {} (current value: {})', self.who.name, target.__class__.__name__, self.stat.__name__, operator_symbol, self.threshold.value, curr_value, current_value=curr_value, goal_value=self.threshold.value, is_money=False, tooltip=self.tooltip)
        return TestResult.TRUE

    def __repr__(self):
        return 'Stat: {}, Threshold: {} on Subject {}'.format(self.stat, self.threshold, self.who)

    def _get_make_true_value(self):
        for value in algos.binary_walk_gen(list(range(int(self.stat.min_value), int(self.stat.max_value) + 1))):
            while self.threshold.compare(value):
                return (TestResult.TRUE, value)
        operator_symbol = Operator.from_function(self.threshold.comparison).symbol
        return (TestResult(False, 'Could not find value to satisfy operation: {} {} {}', self.value.state, operator_symbol, self.value), None)

    def _can_make_pass(self, **_):
        (result, _) = self._get_make_true_value()
        return result

    def _make_pass(self, test_targets=None):
        (result, value) = self._get_make_true_value()
        if not result:
            return result
        operator_symbol = Operator.from_function(self.threshold.comparison).symbol
        for target in test_targets:
            tracker = target.get_tracker(self.stat)
            tracker.set_value(self.stat, value)
            self.log_make_pass_action('{}: set {}.{} to {} ({} {})'.format(self.who.name, target.__class__.__name__, self.stat.__name__, value, operator_symbol, self.threshold.value))
        return TestResult.TRUE

    def tuning_is_valid(self):
        return self.stat.valid_for_stat_testing

    def goal_value(self):
        return self.threshold.value

TunableStatThresholdTest = TunableSingletonFactory.create_auto_factory(StatThresholdTest)

class StatInMotionTest(event_testing.test_base.BaseTest):
    __qualname__ = 'StatInMotionTest'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value.who == ParticipantType.Invalid or value.stat is None or value.threshold is None:
            logger.error('Missing or invalid argument at {}: {}', source, tunable_name)

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'who': TunableEnumEntry(description='\n            Who or what to apply this test to', tunable_type=participant_type_enum, default=participant_type_default)}

    FACTORY_TUNABLES = {'verify_tunable_callback': _verify_tunable_callback, 'description': 'Gate availability by the change rate of a continuous statistic on a participant.', 'who': TunableEnumEntry(description='\n            Who or what to apply this test to', tunable_type=ParticipantType, default=ParticipantType.Actor), 'stat': TunableReference(description='\n            "The stat we are operating on.', manager=services.statistic_manager()), 'threshold': TunableThreshold(description='\n            The threshold of loss or gain rate for this statistic in order to pass')}

    def __init__(self, who, stat, threshold, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.who = who
        self.stat = stat
        self.threshold = threshold

    def get_expected_args(self):
        return {'test_targets': self.who}

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            if self.stat is None:
                return TestResult(False, 'Stat failed to load.')
            if target is None:
                logger.error('Trying to call StatInMotionTest on {} which is None', target)
                return TestResult(False, 'Target({}) does not exist', self.who)
            curr_value = target.get_statistic(self.stat).get_change_rate_without_decay()
            while not self.threshold.compare(curr_value):
                return TestResult(False, 'Failed stat motion check')
        return TestResult.TRUE

TunableStatInMotionTest = TunableSingletonFactory.create_auto_factory(StatInMotionTest)

class StatOfCategoryTest(event_testing.test_base.BaseTest):
    __qualname__ = 'StatOfCategoryTest'

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'who': TunableEnumEntry(participant_type_enum, participant_type_default, description='Who or what to apply this test to')}

    FACTORY_TUNABLES = {'description': 'Gate availability by the existence of a category of statistics on the actor or target.', 'who': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), 'statistic_category': TunableEnumEntry(statistics.statistic_categories.StatisticCategory, statistics.statistic_categories.StatisticCategory.INVALID, description='The category to check for.'), 'check_for_existence': Tunable(bool, True, description='If checked, this test will succeed if any statistic of the category exists. If unchecked, this test will succeed only if no statistics of the category exist.')}

    def __init__(self, who, statistic_category, check_for_existence, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.who = who
        self.category = statistic_category
        self.check_exist = check_for_existence

    def get_expected_args(self):
        return {'test_targets': self.who}

    @cached_test
    def __call__(self, test_targets=None):
        category = self.category
        check_exist = self.check_exist
        for target in test_targets:
            found_category_on_sim = False
            for commodity in target.commodity_tracker.get_all_commodities():
                while category in commodity.get_categories():
                    if not commodity.is_at_convergence():
                        if check_exist:
                            found_category_on_sim = True
                        else:
                            return TestResult(False, 'Sim has a commodity disallowed by StatOfCategoryTest')
            while check_exist and not found_category_on_sim:
                TestResult(False, 'Sim does not have a commodity required by StatOfCategoryTest')
        return TestResult.TRUE

TunableStatOfCategoryTest = TunableSingletonFactory.create_auto_factory(StatOfCategoryTest)

class RelativeStatTest(event_testing.test_base.BaseTest):
    __qualname__ = 'RelativeStatTest'
    FACTORY_TUNABLES = {'description': 'Gate availability by a statistic on the actor or target.', 'source': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), 'target': TunableEnumEntry(ParticipantType, ParticipantType.TargetSim, description='Who or what to use for the comparison'), 'stat': TunableReference(services.statistic_manager(), description='The stat we are using for the comparison'), 'comparison': TunableOperator(sims4.math.Operator.GREATER_OR_EQUAL, description='The comparison to perform against the value. The test passes if (source_stat comparison target)')}

    def __init__(self, source, target, stat, comparison, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.source = source
        self.target = target
        self.stat = stat
        self.comparison = comparison

    def get_expected_args(self):
        return {'source_objects': self.source, 'target_objects': self.target}

    @cached_test
    def __call__(self, source_objects=None, target_objects=None):
        if self.stat is None:
            return TestResult(False, 'Stat failed to load.')
        for source_obj in source_objects:
            if source_obj is None:
                logger.error('Trying to call RelativeStatThresholdTest on {} which is None for {}', source_obj)
                return TestResult(False, 'Target({}) does not exist', self.source)
            source_tracker = source_obj.get_tracker(self.stat)
            source_curr_value = source_tracker.get_user_value(self.stat)
            for target_obj in target_objects:
                if target_obj is None:
                    logger.error('Trying to call RelativeStatThresholdTest on {} which is None for {}', target_obj)
                    return TestResult(False, 'Target({}) does not exist', self.target)
                target_tracker = target_obj.get_tracker(self.stat)
                target_curr_value = target_tracker.get_user_value(self.stat)
                threshold = sims4.math.Threshold(target_curr_value, self.comparison)
                while not threshold.compare(source_curr_value):
                    operator_symbol = Operator.from_function(self.comparison).symbol
                    return TestResult(False, '{} failed relative stat check: {}.{} {} {} (current value: {})', self.source.name, target_obj.__class__.__name__, self.stat.__name__, operator_symbol, target_curr_value, source_curr_value)
        return TestResult.TRUE

TunableRelativeStatTest = TunableSingletonFactory.create_auto_factory(RelativeStatTest)

class SkillTagThresholdTest(event_testing.test_base.BaseTest):
    __qualname__ = 'SkillTagThresholdTest'
    test_events = (TestEvent.SkillLevelChange,)

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'who': TunableEnumEntry(participant_type_enum, participant_type_default, description='Who or what to apply this test to')}

    FACTORY_TUNABLES = {'description': 'A tunable test method that checks the TAGS of ALL THE PARTICIPANTS SKILLS each against a threshold.', 'who': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), 'skill_tag': TunableEnumEntry(tag.Tag, tag.Tag.INVALID, description='What tag to test for'), 'skill_threshold': TunableThreshold(description='The threshold level to test of each skill'), 'skill_quantity': Tunable(int, 0, description='The minimum number of skills at or above this level required to pass')}

    def __init__(self, who, skill_tag, skill_threshold, skill_quantity, **kwargs):
        super().__init__(**kwargs)
        self.who = who
        self.tag = skill_tag
        self.threshold = skill_threshold
        self.quantity = skill_quantity

    def get_expected_args(self):
        return {'test_targets': self.who}

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            if self.tag is None:
                return TestResult(False, 'Tag not present or failed to load.')
            if target is None:
                logger.error('Trying to call SkillTagThresholdTest on {} which is None for {}', target)
                return TestResult(False, 'Target({}) does not exist', self.who)
            if self.tag is tag.Tag.INVALID:
                return TestResult(False, 'Tag test is set to INVALID, aborting test.')
            if self.threshold.value == 0 or self.quantity == 0:
                return TestResult(False, 'Threshold or Quantity not set, aborting test.')
            num_passed = 0
            highest_skill_value = 0
            for stat in target.all_skills():
                while self.tag in stat.tags:
                    curr_value = 0
                    if not stat.is_initial_value:
                        curr_value = stat.get_user_value()
                    if self.threshold.compare(curr_value):
                        num_passed += 1
                    elif curr_value > highest_skill_value:
                        highest_skill_value = curr_value
            while not num_passed >= self.quantity:
                if num_passed == 0 and self.quantity == 1:
                    return TestResultNumeric(False, 'The number of applicable skills: {} was not high enough to pass: {}.', num_passed, self.quantity, current_value=highest_skill_value, goal_value=self.threshold.value, is_money=False, tooltip=self.tooltip)
                return TestResultNumeric(False, 'The number of applicable skills: {} was not high enough to pass: {}.', num_passed, self.quantity, current_value=num_passed, goal_value=self.quantity, is_money=False, tooltip=self.tooltip)
        return TestResult.TRUE

    def tuning_is_valid(self):
        return self.tag is not tag.Tag.INVALID or (self.threshold.value != 0 or self.quantity != 0)

    def goal_value(self):
        if self.quantity > 1:
            return self.quantity
        return self.threshold.value

TunableSkillTagThresholdTest = TunableSingletonFactory.create_auto_factory(SkillTagThresholdTest)

class SkillThreshold(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'SkillThreshold'
    FACTORY_TUNABLES = {'description': 'A TunableThreshold that is specifically used in Skill Range Tests to determine if a skill meets the required skill level.', 'skill_threshold': TunableThreshold(description='\n            The Threshold for the skill level to be valid.\n            ')}

    @property
    def skill_range_max(self):
        comparison_operator = sims4.math.Operator.from_function(self.skill_threshold.comparison)
        if comparison_operator == sims4.math.Operator.LESS_OR_EQUAL or comparison_operator == sims4.math.Operator.LESS or comparison_operator == sims4.math.Operator.EQUAL:
            return self.skill_threshold.value
        logger.error('Tuned Threshold has no maximum for skill range', owner='rmccord')
        return sims4.math.MAX_FLOAT

    @property
    def skill_range_min(self):
        comparison_operator = sims4.math.Operator.from_function(self.skill_threshold.comparison)
        if comparison_operator == sims4.math.Operator.GREATER_OR_EQUAL or comparison_operator == sims4.math.Operator.GREATER or comparison_operator == sims4.math.Operator.EQUAL:
            return self.skill_threshold.value
        logger.error('Tuned Threshold has no minimum for skill range', owner='rmccord')
        return 0

    @cached_test
    def __call__(self, curr_value):
        if not self.skill_threshold.compare(curr_value):
            return TestResult(False, 'Skill failed threshold test.')
        return TestResult.TRUE

class SkillInterval(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'SkillInterval'
    FACTORY_TUNABLES = {'description': 'A TunableThreshold that is specifically used in Skill Range Tests to determine if a skill meets the required skill level.', 'skill_interval': TunableInterval(description='\n            The range (inclusive) a skill level must be in to pass this test.\n            ', tunable_type=int, default_lower=1, default_upper=10, minimum=0, maximum=20)}

    @property
    def skill_range_min(self):
        return self.skill_interval.lower_bound

    @property
    def skill_range_max(self):
        return self.skill_interval.upper_bound

    @cached_test
    def __call__(self, curr_value):
        if curr_value < self.skill_interval.lower_bound or curr_value > self.skill_interval.upper_bound:
            return TestResult(False, 'skill level not in desired range.')
        return TestResult.TRUE

class SkillRangeTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'SkillRangeTest'
    FACTORY_TUNABLES = {'description': 'Gate availability by a skill level range.', 'subject': TunableEnumEntry(description='\n            The subject of this test.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'skill': Skill.TunableReference(description='\n            What skill to test for.\n            '), 'skill_range': TunableVariant(description='\n            A skill range defined by either an interval or a threshold.\n            ', interval=SkillInterval.TunableFactory(), threshold=SkillThreshold.TunableFactory(), default='interval'), 'use_effective_skill_level': Tunable(description='\n            The range (inclusive) a skill level must be in to pass this test.\n            ', tunable_type=bool, needs_tuning=True, default=False)}

    def get_expected_args(self):
        return {'test_targets': self.subject}

    @property
    def skill_range_min(self):
        return self.skill_range.skill_range_min

    @property
    def skill_range_max(self):
        return self.skill_range.skill_range_max

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            if self.skill is None:
                return TestResult(False, 'skill not present or failed to load.')
            if target is None:
                logger.error('Trying to call SkillRangeTest when no actor was found.')
                return TestResult(False, 'ParticipantType.Actor not found.')
            stat = target.get_statistic(self.skill)
            while stat is not None:
                if self.use_effective_skill_level and target.is_instanced():
                    curr_value = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS).get_effective_skill_level(stat)
                else:
                    curr_value = stat.get_user_value()
                if not self.skill_range(curr_value):
                    return TestResult(False, 'skill level not in desired range.', tooltip=self.tooltip)
                return TestResult.TRUE
        return TestResult(False, 'Sim does not have required skill.', tooltip=self.tooltip)

class SkillInUseTest(event_testing.test_base.BaseTest):
    __qualname__ = 'SkillInUseTest'

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'who': TunableEnumEntry(description='\n            Who or what to apply this test to', tunable_type=participant_type_enum, default=participant_type_default)}

    FACTORY_TUNABLES = {'description': 'Gate availability by the a skill being actively in use by a participant.', 'who': TunableEnumEntry(description='\n            Who or what to apply this test to', tunable_type=ParticipantType, default=ParticipantType.Actor), 'skill': TunableReference(description='\n            "The skill we are operating on.', manager=services.statistic_manager(), class_restrictions='Skill')}

    def __init__(self, who, skill, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.who = who
        self.skill = skill

    def get_expected_args(self):
        return {'test_targets': self.who}

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            if target is None:
                logger.error('Trying to call SkillInUseTest on {} which is None', target)
                return TestResult(False, 'Target({}) does not exist', self.who)
            if self.skill is None:
                if target.current_skill_guid != 0:
                    return TestResult.TRUE
                    while target.current_skill_guid == self.skill.guid64:
                        return TestResult.TRUE
            else:
                while target.current_skill_guid == self.skill.guid64:
                    return TestResult.TRUE
        return TestResult(False, 'Failed SkillInUseTest')

TunableSkillInUseTest = TunableSingletonFactory.create_auto_factory(SkillInUseTest)

class MoodTest(event_testing.test_base.BaseTest):
    __qualname__ = 'MoodTest'
    test_events = (TestEvent.MoodChange, TestEvent.LoadingScreenLifted)

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'who': TunableEnumEntry(participant_type_enum, participant_type_default, description='Who or what to apply this test to')}

    FACTORY_TUNABLES = {'description': 'Test for a mood being active on a Sim.', 'who': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), 'mood': TunableReference(services.mood_manager(), description='The mood that must be active (or must not be active, if disallow is True).'), 'disallow': Tunable(bool, False, description="If True, this test will pass if the Sim's mood does NOT match the tuned mood reference.")}

    def __init__(self, who, mood, disallow, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.who = who
        self.mood = mood
        self.disallow = disallow

    def get_expected_args(self):
        return {'test_targets': self.who}

    @cached_test
    def __call__(self, test_targets=None):
        influence_by_active_mood = False
        for target in test_targets:
            if target is None:
                logger.error('Trying to call MoodTest with a None value in the sims iterable.')
            if target.is_sim:
                if target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                    return TestResult(False, '{} failed mood check: It is not an instantiated sim.', target, tooltip=self.tooltip)
                target = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            sim_mood = target.get_mood()
            if self.disallow:
                return TestResult(False, '{} failed mood check for disallowed {}. Current mood: {}', target, self.mood.__name__, sim_mood.__name__ if sim_mood is not None else None, tooltip=self.tooltip)
            else:
                if self.mood is not sim_mood:
                    return TestResult(False, '{} failed mood check for {}. Current mood: {}', target, self.mood.__name__, sim_mood.__name__ if sim_mood is not None else None, tooltip=self.tooltip)
                while self.who == ParticipantType.Actor:
                    influence_by_active_mood = True
        return TestResult(True, influence_by_active_mood=influence_by_active_mood)

TunableMoodTest = TunableSingletonFactory.create_auto_factory(MoodTest)

class SelectedAspirationTrackTest(event_testing.test_base.BaseTest):
    __qualname__ = 'SelectedAspirationTrackTest'
    test_events = (TestEvent.AspirationTrackSelected,)

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'who': TunableEnumEntry(description='\n                    Who or what to apply this test to', tunable_type=participant_type_enum, default=participant_type_default)}

    FACTORY_TUNABLES = {'description': 'Test the Sim for ability to age up.', 'who': TunableEnumEntry(description='\n            Who or what to apply this test to', tunable_type=ParticipantType, default=ParticipantType.Actor), 'aspiration_track': TunableReference(description='\n            The mood that must be active (or must not be active, if disallow is True).', manager=services.get_instance_manager(sims4.resources.Types.ASPIRATION_TRACK))}

    def __init__(self, who, aspiration_track, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.who = who
        self.aspiration_track = aspiration_track

    def get_expected_args(self):
        return {'test_targets': self.who}

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            if target is None:
                logger.error('Trying to call SelectedAspirationTrackTest with a None value in the sims iterable.')
            while target._primary_aspiration != self.aspiration_track.guid64:
                return TestResult(False, '{} failed SelectedAspirationTrackTest check. Track guids: {} is not {}', target, target._primary_aspiration, self.aspiration_track.guid64, tooltip=self.tooltip)
        return TestResult.TRUE

TunableSelectedAspirationTrackTest = TunableSingletonFactory.create_auto_factory(SelectedAspirationTrackTest)

class AgeUpTest(event_testing.test_base.BaseTest):
    __qualname__ = 'AgeUpTest'
    test_events = ()

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'who': TunableEnumEntry(participant_type_enum, participant_type_default, description='Who or what to apply this test to')}

    FACTORY_TUNABLES = {'description': 'Test the Sim for ability to age up.', 'who': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to')}

    def __init__(self, who, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.who = who

    def get_expected_args(self):
        return {'test_targets': self.who}

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            if target is None:
                logger.error('Trying to call AgeUpTest with a None value in the sims iterable.')
            if not target.is_sim:
                logger.error('Trying to call AgeUpTest on {} which is not a sim.', target)
            if target.is_npc:
                return TestResult.TRUE
            while target.can_age_up():
                return TestResult.TRUE
        return TestResult(False, '{} failed AgeUp check. Current age: {}', target, target._age_progress.get_value(), tooltip=self.tooltip)

TunableAgeUpTest = TunableSingletonFactory.create_auto_factory(AgeUpTest)

class SimInfoTest(event_testing.test_base.BaseTest):
    __qualname__ = 'SimInfoTest'
    test_events = ()
    REQUIRE_ALIVE = -1
    REQUIRE_DEAD = -2

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'who': TunableEnumEntry(participant_type_enum, participant_type_default, description='Who or what to apply this test to')}

    FACTORY_TUNABLES = {'description': 'Gate availability by an attribute of the actor or target Sim.', 'who': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), 'gender': OptionalTunable(TunableEnumEntry(sims.sim_info_types.Gender, None, description='Required gender.'), disabled_name='unspecified', enabled_name='specified'), 'ages': OptionalTunable(TunableEnumSet(sims.sim_info_types.Age, enum_default=sims.sim_info_types.Age.ADULT, default_enum_list=[sims.sim_info_types.Age.TEEN, sims.sim_info_types.Age.YOUNGADULT, sims.sim_info_types.Age.ADULT, sims.sim_info_types.Age.ELDER], description='All valid ages.'), description='Allowed ages.', disabled_name='unspecified', enabled_name='specified'), 'can_age_up': OptionalTunable(Tunable(bool, None, description='Whether the Sim is eligible to advance to the next age.'), description='Whether the Sim is eligible to advance to the next age.', disabled_name='unspecified', enabled_name='specified'), 'death': TunableVariant(description='\n            Determines the required death conditions of the Sim. The\n            test can check for a specific death type or a specific\n            condition related to death.\n            ', death_type=TunableEnumEntry(description="\n                Require the Sim's death type to match the specified death type.\n                ", tunable_type=interactions.utils.death.DeathType, default=interactions.utils.death.DeathType.NONE), locked_args={'dead': REQUIRE_DEAD, 'alive': REQUIRE_ALIVE}, default='alive'), 'npc': OptionalTunable(Tunable(description='\n                Whether the Sim must be an NPC or Playable Sim.\n                If enabled and true, the sim must be an NPC for this test to pass.\n                If enabled and false, the sim must be playable, non-NPC sim for this test to pass.\n                If disabled, this portion of the Sim Info test will be ignored.\n                ', tunable_type=bool, default=False)), 'is_active_sim': OptionalTunable(Tunable(description='\n                Whether the Sim must be the active selected Sim.\n                If enabled and true, the sim must active for this test to pass.\n                If enabled and false, the sim must not be active for this test to pass.\n                If disabled, this portion of the Sim Info test will be ignored.\n                ', tunable_type=bool, default=True))}

    def __init__(self, who, gender, ages, can_age_up, death, npc, is_active_sim, **kwargs):
        super().__init__(**kwargs)
        self.who = who
        self.gender = gender
        self.ages = ages
        self.can_age_up = can_age_up
        self.death = death
        self.npc = npc
        self.is_active_sim = is_active_sim

    def get_expected_args(self):
        return {'test_targets': self.who}

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            result = self.test_sim_info(target)
            while not result:
                return result
        return TestResult.TRUE

    def test_sim_info(self, sim_info):
        if sim_info is None:
            return TestResult(False, 'Sim Info is None!')
        if self.gender is not None and sim_info.gender != self.gender:
            return TestResult(False, "{}'s gender is {}, must be {}", self.who.name, sim_info.gender, self.gender, tooltip=self.tooltip)
        if self.ages is not None and sim_info.age not in self.ages:
            return TestResult(False, "{}'s age is {}, must be one of the following: {}", self.who.name, sim_info.age, ', '.join(str(age) for age in self.ages), tooltip=self.tooltip)
        if self.can_age_up is not None and self.can_age_up != sim_info.can_age_up():
            return TestResult(False, '{} {} be able to advance to the next age.', self.who.name, 'must' if self.can_age_up else 'must not', tooltip=self.tooltip)
        if self.death == self.REQUIRE_ALIVE:
            if sim_info.is_dead:
                return TestResult(False, '{} is dead.', sim_info.full_name, tooltip=self.tooltip)
        elif self.death == self.REQUIRE_DEAD:
            if not sim_info.is_dead:
                return TestResult(False, '{} is not dead.', sim_info.full_name, tooltip=self.tooltip)
        elif self.death != sim_info.death_type:
            return TestResult(False, '{} died of {}, not of {}', sim_info.full_name, sim_info.death_type, self.death, tooltip=self.tooltip)
        if self.npc is not None and sim_info.is_npc != self.npc:
            return TestResult(False, '{} does not meet the npc requirement.', sim_info.full_name, tooltip=self.tooltip)
        if self.is_active_sim is not None:
            clients = [client for client in services.client_manager().values()]
            if not clients:
                return TestResult(False, 'SimInfoTest: No clients found when trying to get the active sim.', tooltip=self.tooltip)
            client = clients[0]
            if client.active_sim is None:
                return TestResult(False, 'SimInfoTest: Client returned active Sim as None.', tooltip=self.tooltip)
            if self.is_active_sim:
                if client.active_sim.sim_info is not sim_info:
                    return TestResult(False, '{} does not meet the active sim requirement.', sim_info.full_name, tooltip=self.tooltip)
                    if client.active_sim.sim_info is sim_info:
                        return TestResult(False, '{} does not meet the active sim requirement.', sim_info.full_name, tooltip=self.tooltip)
            elif client.active_sim.sim_info is sim_info:
                return TestResult(False, '{} does not meet the active sim requirement.', sim_info.full_name, tooltip=self.tooltip)
        return TestResult.TRUE

TunableSimInfoTest = TunableSingletonFactory.create_auto_factory(SimInfoTest)

class TraitTest(event_testing.test_base.BaseTest):
    __qualname__ = 'TraitTest'
    test_events = (TestEvent.TraitAddEvent, TestEvent.LoadingScreenLifted)

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'subject': TunableEnumEntry(participant_type_enum, participant_type_default, description='Who or what to apply this test to')}

    FACTORY_TUNABLES = {'description': 'Gate traits of the actor or target Sim.', 'subject': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), 'whitelist_traits': TunableList(TunableReference(services.trait_manager()), description='The Sim must have any trait in this list to pass this test.'), 'blacklist_traits': TunableList(TunableReference(services.trait_manager()), description='The Sim cannot have any trait contained in this list to pass this test.'), 'num_whitelist_required': Tunable(int, 1, description='Number of whitelist traits required to pass.'), 'num_blacklist_allowed': Tunable(int, 0, description='Number of blacklist traits allowed before failing.')}

    def __init__(self, subject, whitelist_traits, blacklist_traits, num_whitelist_required, num_blacklist_allowed, **kwargs):
        super().__init__(**kwargs)
        self.subject = subject
        self.whitelist_traits = whitelist_traits
        self.blacklist_traits = blacklist_traits
        self.num_whitelist_required = num_whitelist_required
        self.num_blacklist_allowed = num_blacklist_allowed

    def get_expected_args(self):
        return {'test_targets': self.subject}

    @cached_test
    def __call__(self, test_targets=None):
        trait_pie_menu_icon = None
        for target in test_targets:
            trait_tracker = target.trait_tracker
            if self.whitelist_traits:
                white_count = 0
                pass_white = False
                for trait in self.whitelist_traits:
                    while trait_tracker.has_trait(trait):
                        white_count += 1
                        if self.subject == ParticipantType.Actor:
                            trait_pie_menu_icon = trait.pie_menu_icon
                        if white_count >= self.num_whitelist_required:
                            pass_white = True
                            break
                if not pass_white:
                    return TestResult(False, "{} doesn't have any or enough traits in white list", self.subject.name, tooltip=self.tooltip)
                    if self.blacklist_traits:
                        black_count = 0
                        for trait in self.blacklist_traits:
                            while trait_tracker.has_trait(trait):
                                black_count += 1
                                if black_count >= self.num_blacklist_allowed:
                                    return TestResult(False, '{} has trait {} in black list', self.subject.name, trait, tooltip=self.tooltip)
                    else:
                        trait_count = len(trait_tracker)
                        while trait_count < self.num_whitelist_required:
                            return TestResult(False, "{} doesn't have enough traits.", self.subject.name, tooltip=self.tooltip)
            elif self.blacklist_traits:
                black_count = 0
                for trait in self.blacklist_traits:
                    while trait_tracker.has_trait(trait):
                        black_count += 1
                        if black_count >= self.num_blacklist_allowed:
                            return TestResult(False, '{} has trait {} in black list', self.subject.name, trait, tooltip=self.tooltip)
            else:
                trait_count = len(trait_tracker)
                while trait_count < self.num_whitelist_required:
                    return TestResult(False, "{} doesn't have enough traits.", self.subject.name, tooltip=self.tooltip)
        return TestResult(True, icon=trait_pie_menu_icon)

    def tuning_is_valid(self):
        return len(self.whitelist_traits) != 0 or (len(self.blacklist_traits) != 0 or self.num_whitelist_required > 1)

TunableTraitTest = TunableSingletonFactory.create_auto_factory(TraitTest)

class BuffTest(event_testing.test_base.BaseTest):
    __qualname__ = 'BuffTest'
    test_events = (TestEvent.BuffBeganEvent,)

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'subject': TunableEnumEntry(participant_type_enum, participant_type_default, description='Who or what to apply this test to')}

    FACTORY_TUNABLES = {'description': 'Gate buffs of the actor or target Sim.', 'subject': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), 'whitelist': TunableList(TunableReference(services.buff_manager()), description='The Sim must have any buff in this list to pass this test.'), 'blacklist': TunableList(TunableReference(services.buff_manager()), description='The Sim cannot have any buff contained in this list to pass this test.')}

    def __init__(self, subject, whitelist, blacklist, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.subject = subject
        self.whitelist = whitelist
        self.blacklist = blacklist

    def get_expected_args(self):
        return {'test_targets': self.subject}

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            if target is None:
                return TestResult(False, '{} Sim is not instanced from Sim Info.', self.subject.name, tooltip=self.tooltip)
            if target.is_sim:
                target_instance = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
                if target_instance is None:
                    return TestResult(False, '{} failed buff check: It is not an instantiated sim.', target, tooltip=self.tooltip)
                target = target_instance
            if self.blacklist:
                for buff_type in self.blacklist:
                    while target.has_buff(buff_type):
                        return TestResult(False, '{} has buff {} in buff list', self.subject.name, buff_type, tooltip=self.tooltip)
            while self.whitelist:
                for buff_type in self.whitelist:
                    while target.has_buff(buff_type):
                        return TestResult.TRUE
                return TestResult(False, "{} doesn't have any buff in white list", self.subject.name, tooltip=self.tooltip)
        return TestResult.TRUE

    def tuning_is_valid(self):
        return len(self.whitelist) != 0 or len(self.blacklist) != 0

TunableBuffTest = TunableSingletonFactory.create_auto_factory(BuffTest)

class BuffAddedTest(event_testing.test_base.BaseTest):
    __qualname__ = 'BuffAddedTest'
    test_events = (TestEvent.BuffBeganEvent,)
    USES_EVENT_DATA = True
    FACTORY_TUNABLES = {'description': 'Determine if a sim receives the specified buff(s).', 'acceptable_buffs': TunableList(TunableReference(services.buff_manager()), description='Buffs that will pass the test.'), 'check_visibility': Tunable(description='\n                If checked then we will check to make sure that the buff is\n                visible.\n                ', tunable_type=bool, default=False)}

    def __init__(self, acceptable_buffs, check_visibility, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.acceptable_buffs = acceptable_buffs
        self.check_visibility = check_visibility

    def get_expected_args(self):
        return {'buff': event_testing.test_events.FROM_EVENT_DATA}

    @cached_test
    def __call__(self, buff=None):
        if buff is None:
            return TestResult(False, 'Buff provided is None, valid during zone load.')
        if self.acceptable_buffs and buff not in self.acceptable_buffs:
            return TestResult(False, "{} isn't in acceptable buff list.", buff, tooltip=self.tooltip)
        if self.check_visibility and not buff.visible:
            return TestResult(False, '{} is not visible when we are checking for visibility.', buff, tooltip=self.tooltip)
        return TestResult.TRUE

    def tuning_is_valid(self):
        return self.check_visibility or len(self.acceptable_buffs) != 0

TunableBuffAddedTest = TunableSingletonFactory.create_auto_factory(BuffAddedTest)

class SlotTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'SlotTest'
    TEST_EMPTY_SLOT = 1
    TEST_USED_SLOT = 2

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value.child_slot is None:
            logger.error('SlotTest: There are no slots to check at {}: {}', source, tunable_name, owner='nbaker')
        if value.slot_test_type is None:
            logger.error('SlotTest: There is not slot_test_type selected {}: {}', source, tunable_name, owner='camilogarcia')

    FACTORY_TUNABLES = {'description': 'Verify slot status.  This test will only apply for single entity participants', 'verify_tunable_callback': _verify_tunable_callback, 'participant': TunableEnumEntry(description='\n            The subject of this situation data test.', tunable_type=ParticipantType, default=ParticipantType.Object), 'child_slot': TunableVariant(description=' \n            The slot on the participant to be tested. \n            ', by_name=Tunable(description=' \n                The exact name of a slot on the participant to be tested.\n                ', tunable_type=str, default='_ctnm_'), by_reference=SlotType.TunableReference(description=' \n                A particular slot type to be tested.\n                ')), 'slot_test_type': TunableVariant(description='\n            Type of slot test to run on target subject.\n            ', has_empty_slot=TunableTuple(description="\n                Verify the slot exists on the participant and it's unoccupied\n                ", check_all_slots=Tunable(description='\n                    Check this if you want to check that all the slots of the \n                    subject are empty.\n                    ', tunable_type=bool, default=False), locked_args={'test_type': TEST_EMPTY_SLOT}), has_used_slot=TunableTuple(description='\n                Verify if any slot of the child slot type is currently occupied\n                ', check_all_slots=Tunable(description='\n                    Check this if you want to check that all the slots of the \n                    subject are used.\n                    ', tunable_type=bool, default=False), locked_args={'test_type': TEST_USED_SLOT})), 'slot_count_required': Tunable(description='\n            Minimum number of slots that must pass test \n            only valid for reference slots And not if all are required to pass\n            ', tunable_type=int, default=1), 'check_part_owner': Tunable(description='\n            If enabled and target of tests is a part, the test will be run\n            on the part owner instead.\n            ', tunable_type=bool, default=False)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_expected_args(self):
        return {'test_targets': self.participant}

    @cached_test
    def __call__(self, test_targets=None):
        if test_targets is None:
            return TestResult(False, 'SlotTest: There are no test targets')
        if self.child_slot is None:
            return TestResult(False, 'SlotTest: There are no slots')
        for target in test_targets:
            if self.check_part_owner and target.is_part:
                target = target.part_owner
            valid_count = 0
            if self.slot_test_type.test_type == self.TEST_EMPTY_SLOT:
                if isinstance(self.child_slot, str):
                    runtime_slot = RuntimeSlot(target, sims4.hash_util.hash32(self.child_slot), singletons.EMPTY_SET)
                    return TestResult.TRUE
                elif self.slot_test_type.check_all_slots:
                    return TestResult.TRUE
                else:
                    while True:
                        for runtime_slot in target.get_runtime_slots_gen(slot_types={self.child_slot}, bone_name_hash=None):
                            while runtime_slot.empty:
                                valid_count += 1
                                if valid_count >= self.slot_count_required:
                                    return TestResult.TRUE
                        while self.slot_test_type.test_type == self.TEST_USED_SLOT:
                            if isinstance(self.child_slot, str):
                                runtime_slot = RuntimeSlot(target, sims4.hash_util.hash32(self.child_slot), singletons.EMPTY_SET)
                                return TestResult.TRUE
                            elif self.slot_test_type.check_all_slots:
                                return TestResult.TRUE
                            else:
                                while True:
                                    for runtime_slot in target.get_runtime_slots_gen(slot_types={self.child_slot}, bone_name_hash=None):
                                        while not runtime_slot.empty:
                                            valid_count += 1
                                            if valid_count >= self.slot_count_required:
                                                return TestResult.TRUE
            else:
                while self.slot_test_type.test_type == self.TEST_USED_SLOT:
                    if isinstance(self.child_slot, str):
                        runtime_slot = RuntimeSlot(target, sims4.hash_util.hash32(self.child_slot), singletons.EMPTY_SET)
                        return TestResult.TRUE
                    elif self.slot_test_type.check_all_slots:
                        return TestResult.TRUE
                    else:
                        while True:
                            for runtime_slot in target.get_runtime_slots_gen(slot_types={self.child_slot}, bone_name_hash=None):
                                while not runtime_slot.empty:
                                    valid_count += 1
                                    if valid_count >= self.slot_count_required:
                                        return TestResult.TRUE
        return TestResult(False, "SlotTest: participant doesn't meet slot availability requirements", tooltip=self.tooltip)

TunableSlotTest = TunableSingletonFactory.create_auto_factory(SlotTest)

class TopicTest(event_testing.test_base.BaseTest):
    __qualname__ = 'TopicTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': 'Gate topics of the actor or target Sim.', 'subject': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), 'target_sim': TunableEnumEntry(ParticipantType, ParticipantType.Invalid, description='Set if topic needs a specfic target.  If no target, keep as Invalid.'), 'whitelist_topics': TunableList(TunableReference(services.topic_manager()), description='The Sim must have any topic in this list to pass this test.'), 'blacklist_topics': TunableList(TunableReference(services.topic_manager()), description='The Sim cannot have any topic contained in this list to pass this test.')}

    def __init__(self, subject, target_sim, whitelist_topics, blacklist_topics, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.subject = subject
        self.target_sim = target_sim
        self.whitelist_topics = whitelist_topics
        self.blacklist_topics = blacklist_topics

    def get_expected_args(self):
        if self.target_sim == ParticipantType.Invalid:
            return {'subjects': self.subject}
        return {'subjects': self.subject, 'targets_to_match': self.target_sim}

    def _topic_exists(self, sim, target):
        if self.whitelist_topics:
            if any(t.topic_exist_in_sim(sim, target=target) for t in self.whitelist_topics):
                return TestResult.TRUE
            return TestResult(False, "{} doesn't have any topic in white list", sim.name, tooltip=self.tooltip)
        if self.blacklist_topics and any(t.topic_exist_in_sim(sim, target=target) for t in self.blacklist_topics):
            return TestResult(False, '{} has topic in black list', sim.name, tooltip=self.tooltip)
        return TestResult.TRUE

    @cached_test
    def __call__(self, subjects=None, targets_to_match=None):
        for subject in subjects:
            if subject.is_sim:
                if subject.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                    return TestResult(False, '{} failed topic check: It is not an instantiated sim.', subject, tooltip=self.tooltip)
                subject = subject.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            if targets_to_match is not None:
                for target_to_match in targets_to_match:
                    result = self._topic_exists(subject, target_to_match)
                    while not result:
                        return result
            else:
                result = self._topic_exists(subject, None)
                while not result:
                    return result
        return TestResult.TRUE

TunableTopicTest = TunableSingletonFactory.create_auto_factory(TopicTest)

class UseDefaultOfflotToleranceFactory(TunableSingletonFactory):
    __qualname__ = 'UseDefaultOfflotToleranceFactory'

    @staticmethod
    def factory():
        return objects.components.statistic_types.StatisticComponentGlobalTuning.DEFAULT_OFF_LOT_TOLERANCE

    FACTORY_TYPE = factory

class LocationTest(event_testing.test_base.BaseTest):
    __qualname__ = 'LocationTest'
    test_events = (TestEvent.SimTravel,)
    FACTORY_TUNABLES = {'description': "Test the existing subject's position for location type flags like being placed outside or on natural ground.", 'subject': TunableEnumEntry(description='Who or what to apply this \n            test to', tunable_type=ParticipantType, default=ParticipantType.Actor), 'location_tests': TunableTuple(is_outside=OptionalTunable(description='\n                If checked, will verify if the subject of the test is outside \n                (no roof over its head) \n                If unchecked, will verify the subject of the test is not \n                outside.\n                ', disabled_name="Don't_Test", tunable=Tunable(bool, True)), is_natural_ground=OptionalTunable(description='\n                If checked, will verify the subject of the test is on natural \n                ground (no floor tiles are under him).\n                Otherwise, will verify the subject of the test is not on \n                natural ground.\n                ', disabled_name="Don't_Test", tunable=Tunable(bool, True)), is_in_slot=OptionalTunable(description='\n                If enabled will test if the object is attacked/deattached to\n                any of possible tuned slots.\n                If you tune a slot type set the test will test if the object \n                is slotted or not slotted into into any of those types. \n                ', disabled_name="Don't_Test", tunable=TunableTuple(description='\n                    Test if an object is current slotted in any of a possible\n                    list of slot types.\n                    Empty slot type set is allowed for testing for slotted or\n                    not slotted only.\n                    ', require_slotted=Tunable(description='\n                        If checked, will verify the subject of the test is  \n                        currently attached to a slot of any of the slots found \n                        in slot_type, if slot_type is empty it will only check \n                        for the object being in any slot.\n                        If unchecked, will verify the subject of the test is \n                        not attached to a slot tuned on slot type.  If slot \n                        type is empty, it will only checked if its at all in\n                        a slot.\n                        ', tunable_type=bool, default=True), slot_type=TunableReference(description='\n                        Possible slot types to object may be attached to.\n                        ', manager=services.slot_type_set_manager()))), is_venue_type=OptionalTunable(description='\n                If checked, will verify if the subject is at a venue of the\n                specified type.\n                ', disabled_name="Don't_Test", tunable=TunableTuple(description='\n                    Venue type required for this test to pass.\n                    ', venue_type=TunableReference(description='\n                        Venue type to test against.\n                        ', manager=services.get_instance_manager(sims4.resources.Types.VENUE)), negate=Tunable(description='\n                        If enabled, the test will return true if the subject\n                        IS NOT at a venue of the specified type.\n                        ', tunable_type=bool, default=False))), is_on_active_lot=OptionalTunable(description='\n                If disabled the test will not be used.\n                If enabled and checked, the test will pass if the subject is\n                on the active lot. (their center is within the lot bounds)\n                If enabled and not checked, the test will pass if the subject is \n                outside of the active lot.\n                \n                For example, Ask To Leave is tuned with this enabled and checked\n                for the TargetSim. You can only ask someone to leave if they\n                are actually on the active lot, but not if they are wandering\n                around in the open streets.\n                ', disabled_name="Don't_Test", enabled_name='Is_or_is_not_on_active_lot', tunable=TunableTuple(is_or_is_not_on_active_lot=Tunable(description='\n                        If checked then the test will pass if the subject is on\n                        the active lot.\n                        ', tunable_type=bool, default=True), tolerance=TunableVariant(explicit=Tunable(description='\n                            The tolerance from the edge of the lot that the\n                            location test will use in order to determine if the\n                            test target is considered on lot or not.\n                            ', tunable_type=int, default=0), use_default_tolerance=UseDefaultOfflotToleranceFactory(description='\n                            Use the default tuned global offlot tolerance tuned\n                            in objects.components.statistic_component.Default Off Lot.\n                            '), default='explicit'))))}

    def __init__(self, subject, location_tests, **kwargs):
        super().__init__(**kwargs)
        self.subject = subject
        self.location_tests = location_tests

    def get_expected_args(self):
        return {'test_target': self.subject}

    @cached_test
    def __call__(self, test_target=None):
        slot_test_tuning = self.location_tests.is_in_slot
        required_venue_type = None if self.location_tests.is_venue_type is None else self.location_tests.is_venue_type.venue_type
        for target in test_target:
            if isinstance(target, sims.sim_info.SimInfo):
                target = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
                if target is None:
                    return TestResult(False, 'Object in None', tooltip=self.tooltip)
            if self.location_tests.is_outside is not None:
                is_outside = not target.is_hidden() and target.is_outside
                if self.location_tests.is_outside != is_outside:
                    return TestResult(False, 'Object failed outside location test', tooltip=self.tooltip)
            if self.location_tests.is_natural_ground is not None and self.location_tests.is_natural_ground != target.is_on_natural_ground():
                return TestResult(False, 'Object failed natural ground location test.', tooltip=self.tooltip)
            if slot_test_tuning is not None:
                if slot_test_tuning.require_slotted:
                    if target.parent_slot is None:
                        return TestResult(False, 'Object failed slotted location test.  Slotted test failed, target is not parented.', tooltip=self.tooltip)
                    if slot_test_tuning.slot_type is not None:
                        if not any(slot in slot_test_tuning.slot_type.slot_types for slot in target.parent_slot.slot_types):
                            return TestResult(False, 'Object failed slotted location test.  Slotted test failed.  Parent slot mismatch', tooltip=self.tooltip)
                        elif slot_test_tuning.slot_type is None:
                            if target.parent_slot is not None:
                                return TestResult(False, 'Object failed slotted location test. Not slotted test failed', tooltip=self.tooltip)
                                if target.parent_slot is not None:
                                    if any(slot in slot_test_tuning.slot_type.slot_types for slot in target.parent_slot.slot_types):
                                        return TestResult(False, 'Object failed slotted location test.  Not slotted for custom slot test failed.  Object is slotted', tooltip=self.tooltip)
                        elif target.parent_slot is not None:
                            if any(slot in slot_test_tuning.slot_type.slot_types for slot in target.parent_slot.slot_types):
                                return TestResult(False, 'Object failed slotted location test.  Not slotted for custom slot test failed.  Object is slotted', tooltip=self.tooltip)
                elif slot_test_tuning.slot_type is None:
                    if target.parent_slot is not None:
                        return TestResult(False, 'Object failed slotted location test. Not slotted test failed', tooltip=self.tooltip)
                        if target.parent_slot is not None:
                            if any(slot in slot_test_tuning.slot_type.slot_types for slot in target.parent_slot.slot_types):
                                return TestResult(False, 'Object failed slotted location test.  Not slotted for custom slot test failed.  Object is slotted', tooltip=self.tooltip)
                elif target.parent_slot is not None:
                    if any(slot in slot_test_tuning.slot_type.slot_types for slot in target.parent_slot.slot_types):
                        return TestResult(False, 'Object failed slotted location test.  Not slotted for custom slot test failed.  Object is slotted', tooltip=self.tooltip)
            if required_venue_type is not None:
                venue = services.get_zone(target.zone_id).venue_service.venue
                if self.location_tests.is_venue_type.negate:
                    if isinstance(venue, required_venue_type):
                        return TestResult(False, 'Object failed venue type test.', tooltip=self.tooltip)
                        if not isinstance(venue, required_venue_type):
                            return TestResult(False, 'Object failed venue type test.', tooltip=self.tooltip)
                elif not isinstance(venue, required_venue_type):
                    return TestResult(False, 'Object failed venue type test.', tooltip=self.tooltip)
            while self.location_tests.is_on_active_lot is not None:
                if self.location_tests.is_on_active_lot.is_or_is_not_on_active_lot != services.current_zone().lot.is_position_on_lot(target.position, self.location_tests.is_on_active_lot.tolerance):
                    return TestResult(False, 'Object on active lot test', tooltip=self.tooltip)
        return TestResult.TRUE

TunableLocationTest = TunableSingletonFactory.create_auto_factory(LocationTest)

class LotOwnerTest(event_testing.test_base.BaseTest):
    __qualname__ = 'LotOwnerTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': 'Gate availability by whether a sim owns the lot the object is on or not.', 'subject': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), 'owns_lot': Tunable(bool, True, description='Check if testing if subject owns lot. Uncheck if testing subject does not own lot.')}

    def __init__(self, subject, owns_lot, **kwargs):
        super().__init__(**kwargs)
        self.subject = subject
        self.owns_lot = owns_lot

    def get_expected_args(self):
        return {'test_targets': self.subject}

    @cached_test
    def __call__(self, test_targets=None):
        lot = services.active_lot()
        if lot:
            for target in test_targets:
                household = target.household
                if self.owns_lot:
                    if not household:
                        return TestResult(False, 'Sim has no household, cannot own an object on a lot.', tooltip=self.tooltip)
                    if household.id != lot.owner_household_id:
                        return TestResult(False, 'Only Sims who own the lot can check ownership of the object.', tooltip=self.tooltip)
                        while household is not None and household.id == lot.owner_household_id:
                            return TestResult(False, 'Sim owns lot.', tooltip=self.tooltip)
                else:
                    while household is not None and household.id == lot.owner_household_id:
                        return TestResult(False, 'Sim owns lot.', tooltip=self.tooltip)
        return TestResult.TRUE

TunableLotOwnerTest = TunableSingletonFactory.create_auto_factory(LotOwnerTest)

class HasLotOwnerTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'HasLotOwnerTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': '\n            Test to check if the lot has an owner or not.\n            ', 'has_owner': Tunable(description='\n                If checked then the test will return true if the lot has an\n                owner.\n                If unchecked then the test will return true if the lot does not\n                have an owner.\n                ', tunable_type=bool, default=True)}

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self):
        lot = services.active_lot()
        if not lot:
            return TestResult(False, 'HasLotOwnerTest: No active lot found.', tooltip=self.tooltip)
        if self.has_owner and lot.owner_household_id == 0:
            return TestResult(False, 'HasLotOwnerTest: Trying to check if the lot has an owner, but the lot does not have an owner.', tooltip=self.tooltip)
        if not self.has_owner and lot.owner_household_id != 0:
            return TestResult(False, 'HasLotOwnerTest: Trying to check if the lot does not have an owner, but the lot has an owner.', tooltip=self.tooltip)
        return TestResult.TRUE

class DuringWorkHoursTest(event_testing.test_base.BaseTest):
    __qualname__ = 'DuringWorkHoursTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': 'Returns True if run during a time that the subject Sim should be at work.', 'subject': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), 'is_during_work': Tunable(bool, True, description='Check to return True if during work hours.')}

    def __init__(self, subject, is_during_work, **kwargs):
        super().__init__(**kwargs)
        self.subject = subject
        self.is_during_work = is_during_work

    def get_expected_args(self):
        return {'test_targets': self.subject}

    @cached_test
    def __call__(self, test_targets=None):
        is_work_time = False
        for target in test_targets:
            while target.career_tracker.currently_during_work_hours:
                is_work_time = True
                break
        if is_work_time:
            if self.is_during_work:
                return TestResult.TRUE
            return TestResult(False, 'Current time is not within any active career work hours.', tooltip=self.tooltip)
        if self.is_during_work:
            return TestResult(False, 'Current time is within any active career work hours.', tooltip=self.tooltip)
        return TestResult.TRUE

TunableDuringWorkHoursTest = TunableSingletonFactory.create_auto_factory(DuringWorkHoursTest)

class AtWorkTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'AtWorkTest'
    test_events = ()
    FACTORY_TUNABLES = {'subject': TunableEnumEntry(description='\n            Who or what to apply this test to.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'is_at_work': Tunable(description='\n            Check to return True if any of the subjects are at work.\n            ', tunable_type=bool, default=True)}

    def get_expected_args(self):
        return {'subjects': self.subject}

    @cached_test
    def __call__(self, subjects=()):
        currently_at_work = any(subject.career_tracker.currently_at_work for subject in subjects)
        if self.is_at_work != currently_at_work:
            return TestResult(False, 'Sim does not match required at_work status {}'.format(self.is_at_work), tooltip=self.tooltip)
        return TestResult.TRUE

class TagTestType(enum.Int):
    __qualname__ = 'TagTestType'
    CONTAINS_ANY_TAG_IN_SET = 1
    CONTAINS_ALL_TAGS_IN_SET = 2
    CONTAINS_NO_TAGS_IN_SET = 3

class StateTestType(enum.Int):
    __qualname__ = 'StateTestType'
    CONTAINS_ANY_STATE_IN_SET = 1
    CONTAINS_ALL_STATES_IN_SET = 2
    CONTAINS_NO_STATE_IN_SET = 3

class NumberTaggedObjectsOwnedFactory(TunableFactory):
    __qualname__ = 'NumberTaggedObjectsOwnedFactory'

    @staticmethod
    def factory(tag_set, test_type, desired_state, required_household_owner_id=None):
        items = []
        for obj in services.object_manager().values():
            if required_household_owner_id is not None and obj.get_household_owner_id() != required_household_owner_id:
                pass
            if not obj.has_state(desired_state.state):
                pass
            if desired_state is not None and obj.get_state(desired_state.state) is not desired_state:
                pass
            object_tags = set(obj.get_tags())
            if test_type == TagTestType.CONTAINS_ANY_TAG_IN_SET and object_tags & tag_set:
                items.append(obj)
            if test_type == TagTestType.CONTAINS_ALL_TAGS_IN_SET and object_tags & tag_set == tag_set:
                items.append(obj)
            while test_type == TagTestType.CONTAINS_NO_TAGS_IN_SET:
                if not object_tags & tag_set:
                    items.append(obj)
        return items

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(tag_set=sims4.tuning.tunable.TunableSet(TunableEnumEntry(tag.Tag, tag.Tag.INVALID, description='What tag to test for'), description='The tags of objects we want to test ownership of'), test_type=TunableEnumEntry(TagTestType, TagTestType.CONTAINS_ANY_TAG_IN_SET, description='How to test the tags in the tag set against the objects on the lot.'), desired_state=OptionalTunable(TunableReference(description='\n                             A state value that must exist on the object to be counted. Example: Masterwork', manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions='ObjectStateValue')), **kwargs)

class ObjectTypeFactory(TunableFactory):
    __qualname__ = 'ObjectTypeFactory'

    @staticmethod
    def factory(obj, actual_object):
        if actual_object is None:
            return True
        return obj.definition.id == actual_object.id

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(actual_object=sims4.tuning.tunable.TunableReference(manager=services.definition_manager(), description='The object we want to test ownership of'))

class ObjectTagFactory(TunableFactory):
    __qualname__ = 'ObjectTagFactory'

    @staticmethod
    def factory(obj, tag_set, test_type):
        object_tags = set(obj.get_tags())
        if test_type == TagTestType.CONTAINS_ANY_TAG_IN_SET:
            if object_tags & tag_set:
                return True
            return False
        elif test_type == TagTestType.CONTAINS_ALL_TAGS_IN_SET:
            if object_tags & tag_set == tag_set:
                return True
            return False
        elif test_type == TagTestType.CONTAINS_NO_TAGS_IN_SET:
            if not object_tags & tag_set:
                return True
            return False
        logger.error('ObjectTagFactory recieved unrecognized TagTestType {}, defaulting to False', test_type, owner='tingyul')
        return False

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(tag_set=sims4.tuning.tunable.TunableSet(TunableEnumEntry(tag.Tag, tag.Tag.INVALID, description='What tag to test for'), description='The tags of objects we want to test ownership of'), test_type=TunableEnumEntry(TagTestType, TagTestType.CONTAINS_ANY_TAG_IN_SET, description='How to test the tags in the tag set against the objects on the lot.'))

class ObjectPurchasedTest(event_testing.test_base.BaseTest):
    __qualname__ = 'ObjectPurchasedTest'
    test_events = (TestEvent.ObjectAdd,)
    FACTORY_TUNABLES = {'description': 'Test the objects purchased against the ones that are tuned.', 'test_type': TunableVariant(default='object', object=ObjectTypeFactory(), tag_set=ObjectTagFactory(), description='The object we want to test for. An object test type left un-tuned is considered any object.'), 'value_threshold': TunableThreshold(description='Amounts in Simoleans required to pass'), 'use_depreciated_value': Tunable(description='\n            If checked, the value consideration for purchased object will at its depreciated amount.\n            ', tunable_type=bool, default=False)}

    def __init__(self, test_type, value_threshold, use_depreciated_value, **kwargs):
        super().__init__(**kwargs)
        self._test_type = test_type
        self._value_threshold = value_threshold
        self.use_depreciated_value = use_depreciated_value

    @property
    def value(self):
        return self._value_threshold.value

    def get_expected_args(self):
        return {'obj': event_testing.test_events.FROM_EVENT_DATA}

    @cached_test
    def __call__(self, obj=None):
        if obj is None:
            return TestResultNumeric(False, 'ObjectPurchasedTest: Object is None, normal during zone load.', current_value=0, goal_value=self._value_threshold.value, is_money=True)
        obj_value = obj.depreciated_value if self.use_depreciated_value else obj.catalog_value
        if self._test_type(obj) and self._value_threshold.compare(obj_value):
            return TestResult.TRUE
        return TestResultNumeric(False, 'ObjectPurchasedTest: Incorrect or invalid value object purchased for test: {}, value: {}', obj, obj_value, current_value=obj_value, goal_value=self._value_threshold.value, is_money=True)

TunableObjectPurchasedTest = TunableSingletonFactory.create_auto_factory(ObjectPurchasedTest)

class ValueContext(enum.Int):
    __qualname__ = 'ValueContext'
    NET_WORTH = 1
    PROPERTY_ONLY = 2
    TOTAL_CASH = 3
    CURRENT_VALUE = 4

class SimoleonsTestEvents(enum.Int):
    __qualname__ = 'SimoleonsTestEvents'
    AllSimoloenEvents = 0
    OnExitBuildBuy = TestEvent.OnExitBuildBuy
    SimoleonsEarned = TestEvent.SimoleonsEarned

class SimoleonsTest(event_testing.test_base.BaseTest):
    __qualname__ = 'SimoleonsTest'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value.context == ValueContext.CURRENT_VALUE and value.subject != ParticipantType.Object and value.subject != ParticipantType.CarriedObject:
            logger.error('{} uses a CURRENT_VALUE for an invalid subject. Only Object and CarriedObject are supported.', instance_class, owner='manus')

    FACTORY_TUNABLES = {'description': 'Tests a Simolean value against a threshold.', 'subject': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who to examine for Simoleon values.'), 'context': TunableEnumEntry(ValueContext, ValueContext.NET_WORTH, description='Value context to test.'), 'value_threshold': TunableThreshold(description='Amounts in Simoleans required to pass'), 'test_event': TunableEnumEntry(description='\n            The event that we want to trigger this instance of the tuned test on. NOTE: OnClientConnect is\n            still used as a trigger regardless of this choice in order to update the UI.\n            ', tunable_type=SimoleonsTestEvents, default=SimoleonsTestEvents.AllSimoloenEvents), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, subject, context, value_threshold, test_event, **kwargs):
        super().__init__(**kwargs)
        self.subject = subject
        self.context = context
        self.value_threshold = value_threshold
        if test_event == SimoleonsTestEvents.AllSimoloenEvents:
            self.test_events = (TestEvent.SimoleonsEarned, TestEvent.OnExitBuildBuy)
        else:
            self.test_events = (test_event,)

    def get_expected_args(self):
        return {'subjects': self.subject}

    def _current_value(self, obj):
        return getattr(obj, 'current_value', 0)

    def _property_value(self, household):
        value = 0
        lot = services.active_lot()
        if lot is not None:
            if household.id != lot.owner_household_id:
                return value
            value = household.household_net_worth() - household.funds.money
        return value

    @cached_test
    def __call__(self, subjects):
        value = 0
        households = set()
        for subject in subjects:
            if self.context == ValueContext.NET_WORTH:
                household = services.household_manager().get_by_sim_id(subject.sim_id)
                if household not in households:
                    households.add(household)
                    value += household.funds.money
                    value += self._property_value(household)
                    if self.context == ValueContext.PROPERTY_ONLY:
                        household = services.household_manager().get_by_sim_id(subject.sim_id)
                        if household not in households:
                            households.add(household)
                            value += self._property_value(household)
                            if self.context == ValueContext.TOTAL_CASH:
                                household = services.household_manager().get_by_sim_id(subject.sim_id)
                                if household not in households:
                                    households.add(household)
                                    value += household.funds.money
                                    while self.context == ValueContext.CURRENT_VALUE:
                                        value += self._current_value(subject)
                            else:
                                while self.context == ValueContext.CURRENT_VALUE:
                                    value += self._current_value(subject)
                    elif self.context == ValueContext.TOTAL_CASH:
                        household = services.household_manager().get_by_sim_id(subject.sim_id)
                        if household not in households:
                            households.add(household)
                            value += household.funds.money
                            while self.context == ValueContext.CURRENT_VALUE:
                                value += self._current_value(subject)
                    else:
                        while self.context == ValueContext.CURRENT_VALUE:
                            value += self._current_value(subject)
            elif self.context == ValueContext.PROPERTY_ONLY:
                household = services.household_manager().get_by_sim_id(subject.sim_id)
                if household not in households:
                    households.add(household)
                    value += self._property_value(household)
                    if self.context == ValueContext.TOTAL_CASH:
                        household = services.household_manager().get_by_sim_id(subject.sim_id)
                        if household not in households:
                            households.add(household)
                            value += household.funds.money
                            while self.context == ValueContext.CURRENT_VALUE:
                                value += self._current_value(subject)
                    else:
                        while self.context == ValueContext.CURRENT_VALUE:
                            value += self._current_value(subject)
            elif self.context == ValueContext.TOTAL_CASH:
                household = services.household_manager().get_by_sim_id(subject.sim_id)
                if household not in households:
                    households.add(household)
                    value += household.funds.money
                    while self.context == ValueContext.CURRENT_VALUE:
                        value += self._current_value(subject)
            else:
                while self.context == ValueContext.CURRENT_VALUE:
                    value += self._current_value(subject)
        if not self.value_threshold.compare(value):
            operator_symbol = Operator.from_function(self.value_threshold.comparison).symbol
            return TestResultNumeric(False, '{} failed value check: {} {} {} (current value: {})', subjects, self.context, operator_symbol, self.value_threshold.value, value, current_value=value, goal_value=self.value_threshold.value, is_money=True, tooltip=self.tooltip)
        return TestResultNumeric(True, current_value=value, goal_value=self.value_threshold.value, is_money=True)

    def tuning_is_valid(self):
        return True

    def goal_value(self):
        return self.value_threshold.value

    @property
    def is_goal_value_money(self):
        return True

TunableSimoleonsTest = TunableSingletonFactory.create_auto_factory(SimoleonsTest)

class ObjectOwnershipTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'ObjectOwnershipTest'
    test_events = (TestEvent.ObjectAdd,)
    FACTORY_TUNABLES = {'description': "Tests if the sim or the sim's household owns the object.", 'sim': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Presumed Owner.'), 'test_object': TunableEnumEntry(ParticipantType, ParticipantType.Object, description='\n            Object to test ownership of.\n            '), 'is_owner': Tunable(bool, True, description='\n            If True, the test succeeds if the tuned sim is the owner of the \n            tuned object.  If False, the test succeeds if the tuned sim is not\n            the owner of the tuned object.\n            '), 'is_creator': Tunable(bool, False, description='\n            If True, the test succeeds if the tuned sim is the original creator of the \n            tuned object. If False, creator test is disregarded. Test for household owner\n            also reneders this test null.\n            '), 'test_household_owner': Tunable(bool, True, description="\n            If True, we only compare the sim's household_id against the owning \n            household of the tuned object. If False, we compare the sim_id\n            against the owning sim of this object.\n            "), 'must_be_owned': Tunable(bool, True, description='\n            If True, the test will only pass if someone owns this object.\n            If False, the test will only pass if nobody owns this object.\n            This tunable is ignored if "is_owner" is set to True.\n            ')}

    def get_expected_args(self):
        return {'test_targets': self.sim, 'objs': self.test_object}

    @cached_test
    def __call__(self, test_targets, objs):
        for obj in objs:
            target_obj = obj
            for target in test_targets:
                target_sim = target
                if self.test_household_owner:
                    owner_id = target_obj.get_household_owner_id()
                    sim_id = target_sim.household.id
                else:
                    owner_id = target_obj.get_sim_owner_id()
                    sim_id = target_sim.sim_id
                    if self.is_creator and sim_id != target_obj.crafter_sim_id:
                        return TestResult(False, 'Sim did not craft this object.', tooltip=self.tooltip)
                if self.is_owner:
                    if sim_id != owner_id:
                        return TestResult(False, "Sim's household does not own this object.", tooltip=self.tooltip)
                        if self.must_be_owned:
                            if owner_id is None:
                                return TestResult(False, 'This object is not owned.', tooltip=self.tooltip)
                                while owner_id is not None:
                                    return TestResult(False, 'This object already has an owner.', tooltip=self.tooltip)
                        else:
                            while owner_id is not None:
                                return TestResult(False, 'This object already has an owner.', tooltip=self.tooltip)
                elif self.must_be_owned:
                    if owner_id is None:
                        return TestResult(False, 'This object is not owned.', tooltip=self.tooltip)
                        while owner_id is not None:
                            return TestResult(False, 'This object already has an owner.', tooltip=self.tooltip)
                else:
                    while owner_id is not None:
                        return TestResult(False, 'This object already has an owner.', tooltip=self.tooltip)
        return TestResult.TRUE

class PickTerrainTest(event_testing.test_base.BaseTest):
    __qualname__ = 'PickTerrainTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': 'Test a Pick Terrain location.', 'terrain_location': TunableEnumEntry(PickTerrainType, default=PickTerrainType.ANYWHERE), 'terrain_feature': OptionalTunable(description='\n            Tune this if you want to require a floor feature to be present', tunable=TunableEnumEntry(FloorFeatureType, default=FloorFeatureType.BURNT)), 'terrain_feature_radius': Tunable(float, 2.0, description='The radius to look for the floor feature, if one is tuned in terrain_feature')}

    def __init__(self, terrain_location, terrain_feature, terrain_feature_radius, **kwargs):
        super().__init__(**kwargs)
        self._terrain_location = terrain_location
        self._terrain_feature = terrain_feature
        self._terrain_feature_radius = terrain_feature_radius

    @cached_test
    def __call__(self, context=None):
        if context is None:
            return TestResult(False, 'Interaction Context is None. Make sure this test is Tuned on an Interaction.')
        pick_info = context.pick
        if pick_info is None:
            return TestResult(False, 'PickTerrainTest cannot run without a valid pick info from the Interaction Context.')
        if pick_info.pick_type not in PICK_TRAVEL:
            return TestResult(False, 'Attempting to run a PickTerrainTest with a pick that has an invalid type.')
        if self._terrain_feature is not None:
            zone_id = sims4.zone_utils.get_zone_id()
            if not build_buy.find_floor_feature(zone_id, self._terrain_feature, pick_info.location, pick_info.routing_surface.secondary_id, self._terrain_feature_radius):
                return TestResult(False, 'Location does not have the required floor feature.')
        if self._terrain_location == PickTerrainType.ANYWHERE:
            return TestResult.TRUE
        on_lot = services.current_zone().lot.is_position_on_lot(pick_info.location)
        if self._terrain_location == PickTerrainType.ON_LOT:
            if on_lot:
                return TestResult.TRUE
            return TestResult(False, 'Pick Terrain is not ON_LOT as expected.')
        if self._terrain_location == PickTerrainType.OFF_LOT:
            if not on_lot:
                return TestResult.TRUE
            return TestResult(False, 'Pick Terrain is not OFF_LOT as expected.')
        pick_lot_id = pick_info.lot_id
        current_zone_id = services.current_zone().id
        other_zone_id = services.get_persistence_service().resolve_lot_id_into_zone_id(pick_lot_id)
        if self._terrain_location == PickTerrainType.ON_OTHER_LOT:
            if not on_lot and other_zone_id is not None and other_zone_id != current_zone_id:
                return TestResult.TRUE
            return TestResult(False, 'Pick Terrain is not ON_OTHER_LOT as expected.')
        if self._terrain_location == PickTerrainType.NO_LOT:
            if other_zone_id is None:
                return TestResult.TRUE
            return TestResult(False, 'Pick Terrain is is on a valid lot, but not expected.')
        in_street = is_position_in_street(pick_info.location)
        if self._terrain_location == PickTerrainType.IN_STREET:
            if in_street:
                return TestResult.TRUE
            return TestResult(False, 'Pick Terrain is not IN_STREET as expected.')
        if self._terrain_location == PickTerrainType.OFF_STREET:
            if not in_street:
                return TestResult.TRUE
            return TestResult(False, 'Pick Terrain is in the street, but not expected.')
        return TestResult.TRUE

TunablePickTerrainTest = TunableSingletonFactory.create_auto_factory(PickTerrainTest)

class PickTypeTest(AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'PickTypeTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': '\n            Test a Pick Type.  A Pick Type is what got clicked on.\n            Example: Stairs, Walls, Sim, Object, Terrain, etc.\n            ', 'whitelist': TunableSet(description='\n                A set of pick types that will pass the test if the pick type\n                matches any of them.\n                ', tunable=TunableEnumEntry(description='\n                    A pick type.\n                    ', tunable_type=PickType, default=PickType.PICK_NONE)), 'blacklist': TunableSet(description='\n                A set of pick types that will fail the test if the pick type\n                matches any of them.\n                ', tunable=TunableEnumEntry(description='\n                    A pick type.\n                    ', tunable_type=PickType, default=PickType.PICK_NONE))}

    @cached_test
    def __call__(self, context=None):
        if context is None:
            return TestResult(False, 'Interaction Context is None. Make sure this test is Tuned on an Interaction.')
        pick_info = context.pick
        if pick_info is None:
            return TestResult(False, 'PickTerrainTest cannot run without a valid pick info from the Interaction Context.')
        pick_type = pick_info.pick_type
        if self.whitelist and pick_type not in self.whitelist:
            return TestResult(False, 'Pick type () not in whitelist {}'.format(pick_type, self.whitelist))
        if pick_type in self.blacklist:
            return TestResult(False, 'Pick type () in blacklist {}'.format(pick_type, self.blacklist))
        return TestResult.TRUE

TunablePickTypeTest = TunableSingletonFactory.create_auto_factory(PickTypeTest)

class PickInfoTest(event_testing.test_base.BaseTest):
    __qualname__ = 'PickInfoTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': 'Require a particular Pick and info about that Pick.', 'pick_type_test': TunableVariant(pick_terrain=TunablePickTerrainTest(), pick_type=TunablePickTypeTest(), default='pick_terrain')}

    def __init__(self, pick_type_test, **kwargs):
        super().__init__(**kwargs)
        self._pick_type_test = pick_type_test

    def get_expected_args(self):
        return {'context': ParticipantType.InteractionContext}

    @cached_test
    def __call__(self, *args, **kwargs):
        return self._pick_type_test(*args, **kwargs)

TunablePickInfoTest = TunableSingletonFactory.create_auto_factory(PickInfoTest)

class PartySizeTest(event_testing.test_base.BaseTest):
    __qualname__ = 'PartySizeTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': 'Require the party size of the subject sim to match a threshold.', 'subject': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='The subject of this party size test.'), 'threshold': TunableThreshold(description='The party size threshold for this test.')}

    def __init__(self, subject, threshold, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.subject = subject
        self.threshold = threshold

    def get_expected_args(self):
        return {'test_targets': self.subject}

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            if target is None:
                return TestResult(False, 'Party Size test failed because subject is not set.', tooltip=self.tooltip)
            if target.is_sim:
                if target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                    return TestResult(False, '{} failed topic check: It is not an instantiated sim.', target, tooltip=self.tooltip)
                target = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            main_group = target.get_main_group()
            if main_group is None:
                return TestResult(False, 'Party Size test failed because subject has no party attribute.', tooltip=self.tooltip)
            group_size = len(main_group)
            while not self.threshold.compare(group_size):
                return TestResult(False, 'Party Size Failed.', tooltip=self.tooltip)
        return TestResult.TRUE

TunablePartySizeTest = TunableSingletonFactory.create_auto_factory(PartySizeTest)

class PartyAgeTest(event_testing.test_base.BaseTest):
    __qualname__ = 'PartyAgeTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': 'Require all sims in the party meet with the age requirement.', 'subject': TunableEnumEntry(description='\n            The subject of this party age test.', tunable_type=ParticipantType, default=ParticipantType.Actor), 'ages_allowed': TunableEnumSet(description='\n            All valid ages.', enum_type=sims.sim_info_types.Age, enum_default=sims.sim_info_types.Age.ADULT, default_enum_list=[sims.sim_info_types.Age.TEEN, sims.sim_info_types.Age.YOUNGADULT, sims.sim_info_types.Age.ADULT, sims.sim_info_types.Age.ELDER])}

    def __init__(self, subject, ages_allowed, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.subject = subject
        self.ages_allowed = ages_allowed

    def get_expected_args(self):
        return {'test_targets': self.subject}

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            if target is None:
                return TestResult(False, 'Party Age test failed because subject is not set.', tooltip=self.tooltip)
            if target.is_sim:
                if target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                    return TestResult(False, '{} failed topic check: It is not an instantiated sim.', target, tooltip=self.tooltip)
                target = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            main_group = target.get_main_group()
            if main_group is None:
                return TestResult(False, 'Party Age test failed because subject has no party attribute.', tooltip=self.tooltip)
            while not all(sim.age in self.ages_allowed for sim in main_group):
                return TestResult(False, "Party has members that age doesn't meet with the requirement", tooltip=self.tooltip)
        return TestResult.TRUE

TunablePartyAgeTest = TunableSingletonFactory.create_auto_factory(PartyAgeTest)

class TotalSimoleonsEarnedTest(event_testing.test_base.BaseTest):
    __qualname__ = 'TotalSimoleonsEarnedTest'
    test_events = (TestEvent.SimoleonsEarned,)
    USES_DATA_OBJECT = True
    FACTORY_TUNABLES = {'description': 'This test is specifically for account based Achievements, upon         event/situation completion testing if the players account has earned enough Simoleons         from event rewards to pass a threshold.', 'threshold': TunableThreshold(description='The simoleons threshold for this test.'), 'earned_source': TunableEnumEntry(event_testing.event_data_const.SimoleonData, event_testing.event_data_const.SimoleonData.TotalMoneyEarned, description='The individual source that we want to track the simoleons from.')}

    def __init__(self, threshold, earned_source, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.threshold = threshold
        self.earned_source = earned_source

    def get_expected_args(self):
        return {'data_object': event_testing.test_events.FROM_DATA_OBJECT, 'objective_guid64': event_testing.test_events.OBJECTIVE_GUID64}

    @cached_test
    def __call__(self, data_object=None, objective_guid64=None):
        simoleons_earned = data_object.get_simoleons_earned(self.earned_source)
        if simoleons_earned is None:
            simoleons_earned = 0
        relative_start_value = data_object.get_starting_values(objective_guid64)
        if relative_start_value is not None:
            simoleons = 0
            simoleons_earned -= relative_start_value[simoleons]
        if not self.threshold.compare(simoleons_earned):
            return TestResultNumeric(False, 'TotalEventsSimoleonsEarnedTest: not enough Simoleons.', current_value=simoleons_earned, goal_value=self.threshold.value, is_money=True)
        return TestResult.TRUE

    def save_relative_start_values(self, objective_guid64, data_object):
        data_object.set_starting_values(objective_guid64, [data_object.get_simoleons_earned(self.earned_source)])

    def tuning_is_valid(self):
        return self.threshold != 0

    def goal_value(self):
        return self.threshold.value

    @property
    def is_goal_value_money(self):
        return True

TunableTotalSimoleonsEarnedTest = TunableSingletonFactory.create_auto_factory(TotalSimoleonsEarnedTest)

class TotalTimePlayedTest(event_testing.test_base.BaseTest):
    __qualname__ = 'TotalTimePlayedTest'
    test_events = (TestEvent.TestTotalTime,)
    USES_DATA_OBJECT = True
    FACTORY_TUNABLES = {'description': 'This test is specifically for account based Achievements, upon         client connect testing if the players account has played the game long enough         in either sim time or server time to pass a threshold of sim or server minutes, respectively.        NOTE: The smallest ', 'use_sim_time': Tunable(bool, False, description='Whether to use sim time, or server time.'), 'threshold': TunableThreshold(description='The amount of time played to pass, measured         in the specified unit of time.'), 'time_unit': TunableEnumEntry(date_and_time.TimeUnit, date_and_time.TimeUnit.MINUTES, description='The unit of time         used for testing')}

    def __init__(self, use_sim_time, threshold, time_unit, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.use_sim_time = use_sim_time
        self.threshold = threshold
        self.treshold_value_in_time_units = threshold.value
        self.time_unit = time_unit
        if use_sim_time:
            threshold_value = clock.interval_in_sim_time(threshold.value, time_unit)
        else:
            threshold_value = clock.interval_in_real_time(threshold.value, time_unit)
            self.threshold.value = threshold_value.in_ticks()

    def get_expected_args(self):
        return {'data': event_testing.test_events.FROM_DATA_OBJECT, 'objective_guid64': event_testing.test_events.OBJECTIVE_GUID64}

    @cached_test
    def __call__(self, data=None, objective_guid64=None):
        if data is None:
            return TestResult(False, 'Data object is None, valid during zone load.')
        if self.use_sim_time:
            value_to_test = data.get_time_data(event_testing.event_data_const.TimeData.SimTime)
        else:
            value_to_test = data.get_time_data(event_testing.event_data_const.TimeData.ServerTime)
        relative_start_value = data.get_starting_values(objective_guid64)
        if relative_start_value is not None:
            time = 0
            value_to_test -= relative_start_value[time]
        if not self.threshold.compare(value_to_test):
            value_in_time_units = date_and_time.ticks_to_time_unit(value_to_test, self.time_unit, self.use_sim_time)
            return TestResultNumeric(False, 'TotalTimePlayedTest: not enough time played.', current_value=int(value_in_time_units), goal_value=self.treshold_value_in_time_units, is_money=False)
        return TestResult.TRUE

    def save_relative_start_values(self, objective_guid64, data_object):
        if self.use_sim_time:
            value_to_test = data_object.get_time_data(event_testing.event_data_const.TimeData.SimTime)
        else:
            value_to_test = data_object.get_time_data(event_testing.event_data_const.TimeData.ServerTime)
        data_object.set_starting_values(objective_guid64, [value_to_test])

    def tuning_is_valid(self):
        return True

TunableTotalTimePlayedTest = TunableSingletonFactory.create_auto_factory(TotalTimePlayedTest)

class RelationshipTestEvents(enum.Int):
    __qualname__ = 'RelationshipTestEvents'
    AllRelationshipEvents = 0
    RelationshipChanged = TestEvent.RelationshipChanged
    AddRelationshipBit = TestEvent.AddRelationshipBit
    RemoveRelationshipBit = TestEvent.RemoveRelationshipBit

class RelationshipTest(event_testing.test_base.BaseTest):
    __qualname__ = 'RelationshipTest'
    UNIQUE_TARGET_TRACKING_AVAILABLE = True
    MIN_RELATIONSHIP_VALUE = -100.0
    MAX_RELATIONSHIP_VALUE = 100.0
    FACTORY_TUNABLES = {'description': 'Gate availability by a relationship status.', 'subject': TunableEnumFlags(description='\n            Owner(s) of the relationship(s)\n            ', enum_type=ParticipantType, default=ParticipantType.Actor), 'target_sim': TunableEnumFlags(description='\n            Target(s) of the relationship(s)\n            ', enum_type=ParticipantType, default=ParticipantType.TargetSim), 'required_relationship_bits': TunableTuple(match_any=TunableSet(description='\n                Any of these relationship bits will pass the test\n                ', tunable=TunableReference(services.relationship_bit_manager())), match_all=TunableSet(description='\n                All of these relationship bits must be present to pass the test\n                ', tunable=TunableReference(services.relationship_bit_manager()))), 'prohibited_relationship_bits': TunableTuple(match_any=TunableSet(description='\n                If any of these relationship bits match the test will fail\n                ', tunable=TunableReference(services.relationship_bit_manager())), match_all=TunableSet(description='\n                All of these relationship bits must match to fail the test\n                ', tunable=TunableReference(services.relationship_bit_manager()))), 'track': TunableReference(description='\n            The track to be manipulated\n            ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions='RelationshipTrack'), 'relationship_score_interval': TunableInterval(description='\n            The range that the relationship score must be within in order for this test to pass.\n            ', tunable_type=float, default_lower=MIN_RELATIONSHIP_VALUE, default_upper=MAX_RELATIONSHIP_VALUE, minimum=MIN_RELATIONSHIP_VALUE, maximum=MAX_RELATIONSHIP_VALUE), 'num_relations': Tunable(description='\n            Number of Sims with specified relationships required to pass,\n            default(0) is all known relations.\n            \n            If value set to 1 or greater, then test is looking at least that\n            number of relationship to match the criteria.\n            \n            If value is set to 0, then test will pass if relationships being\n            tested must match all criteria of the test to succeed.  For\n            example, if interaction should not appear if any relationship\n            contains a relationship bit, this value should be 0.\n            ', tunable_type=int, default=0), 'test_event': TunableEnumEntry(description='\n            The event that we want to trigger this instance of the tuned test on.\n            ', tunable_type=RelationshipTestEvents, default=RelationshipTestEvents.AllRelationshipEvents)}

    def __init__(self, subject, target_sim, required_relationship_bits, prohibited_relationship_bits, track, relationship_score_interval, num_relations, test_event, initiated=True, **kwargs):
        super().__init__(**kwargs)
        if test_event == RelationshipTestEvents.AllRelationshipEvents:
            self.test_events = (TestEvent.RelationshipChanged, TestEvent.AddRelationshipBit, TestEvent.RemoveRelationshipBit)
        else:
            self.test_events = (test_event,)
        self.subject = subject
        self.target_sim = target_sim
        self.required_relationship_bits = required_relationship_bits
        self.prohibited_relationship_bits = prohibited_relationship_bits
        self.track = track
        self.relationship_score_interval = relationship_score_interval
        self.num_relations = num_relations
        self.initiated = initiated
        overlapping_bits = (required_relationship_bits.match_any | required_relationship_bits.match_all) & (prohibited_relationship_bits.match_any | prohibited_relationship_bits.match_all)
        if overlapping_bits:
            raise ValueError('Cannot have overlapping required and prohibited relationship bits: {}'.format(overlapping_bits))

    def get_expected_args(self):
        return {'source_sims': self.subject, 'target_sims': self.target_sim}

    def get_target_id(self, source_sims=None, target_sims=None, id_type=None):
        if source_sims is None or target_sims is None:
            return
        for target_sim in target_sims:
            while target_sim and target_sim.is_sim:
                if id_type == TargetIdTypes.HOUSEHOLD:
                    return target_sim.household.id
                return target_sim.id

    def __call__(self, source_sims=None, target_sims=None):
        if self.num_relations:
            use_threshold = True
            threshold_count = 0
            count_it = True
        else:
            use_threshold = False
        if not self.initiated:
            return TestResult.TRUE
        if self.track is None:
            self.track = singletons.DEFAULT
        if self.target_sim == ParticipantType.AllRelationships:
            targets_id_gen = self.all_related_sims_and_id_gen
        else:
            targets_id_gen = self.all_specified_sims_and_id_gen
        for sim_a in source_sims:
            rel_tracker = sim_a.relationship_tracker
            if target_sims is None:
                return TestResult(False, 'Currently Actor-only relationship tests are unsupported, valid on zone load.')
            for (sim_b, sim_b_id) in targets_id_gen(sim_a, target_sims):
                if sim_b is None:
                    pass
                if self.relationship_score_interval is not None:
                    rel_score = rel_tracker.get_relationship_score(sim_b_id, self.track)
                    if rel_score < self.relationship_score_interval.lower_bound or rel_score > self.relationship_score_interval.upper_bound:
                        if not use_threshold:
                            return TestResult(False, 'Inadequate relationship level ({} not within [{},{}]) between {} and {} ', rel_score, self.relationship_score_interval.lower_bound, self.relationship_score_interval.upper_bound, sim_a, sim_b, tooltip=self.tooltip)
                        count_it = False
                if self.required_relationship_bits.match_any:
                    match_found = False
                    for bit in self.required_relationship_bits.match_any:
                        while rel_tracker.has_bit(sim_b_id, bit):
                            match_found = True
                            break
                    if not match_found:
                        if not use_threshold:
                            return TestResult(False, 'Missing all of the match_any required relationship bits between {} and {}', sim_a, sim_b, tooltip=self.tooltip)
                        count_it = False
                for bit in self.required_relationship_bits.match_all:
                    while not rel_tracker.has_bit(sim_b_id, bit):
                        if not use_threshold:
                            return TestResult(False, 'Missing relationship bit ({}) between {} and {} ', bit, sim_a, sim_b, tooltip=self.tooltip)
                        count_it = False
                        break
                if self.prohibited_relationship_bits.match_any:
                    for bit in self.prohibited_relationship_bits.match_any:
                        while rel_tracker.has_bit(sim_b_id, bit):
                            if not use_threshold:
                                return TestResult(False, 'Prohibited Relationship ({}) between {} and {}', bit, sim_a, sim_b, tooltip=self.tooltip)
                            count_it = False
                            break
                missing_bit = False
                if self.prohibited_relationship_bits.match_all:
                    for bit in self.prohibited_relationship_bits.match_all:
                        while not rel_tracker.has_bit(sim_b_id, bit):
                            missing_bit = True
                            break
                    if not missing_bit:
                        if not use_threshold:
                            return TestResult(False, '{} has all  the match_all prohibited bits with {}', sim_a, sim_b, tooltip=self.tooltip)
                        count_it = False
                while use_threshold:
                    if count_it:
                        threshold_count += 1
                    count_it = True
        if not use_threshold:
            if target_sims == ParticipantType.AllRelationships or len(target_sims) > 0:
                return TestResult.TRUE
            return TestResult(False, 'Nothing compared against, target_sims list is empty.')
        if not threshold_count >= self.num_relations:
            return TestResultNumeric(False, 'Number of relations required not met', current_value=threshold_count, goal_value=self.num_relations, is_money=False, tooltip=self.tooltip)
        return TestResult.TRUE

    def all_related_sims_and_id_gen(self, source_sim, target_sims):
        for sim_b_id in source_sim.relationship_tracker.target_sim_gen():
            sim_b = services.sim_info_manager().get(sim_b_id)
            yield (sim_b, sim_b_id)

    def all_specified_sims_and_id_gen(self, source_sims, target_sims):
        for sim in target_sims:
            if sim is None:
                yield (None, None)
            else:
                yield (sim, sim.sim_id)

    def goal_value(self):
        if self.num_relations:
            return self.num_relations
        return 1

TunableRelationshipTest = TunableSingletonFactory.create_auto_factory(RelationshipTest)

class UndirectedStatThresholdTest(event_testing.test_base.BaseTest):
    __qualname__ = 'UndirectedStatThresholdTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': 'Tune a Skill Threshold for use in tests', 'skill': TunableReference(services.statistic_manager(), description='The Skill the threshold applies to.'), 'threshold': TunableThreshold(description='The threshold used for comparisons.'), 'tooltip': sims4.localization.TunableLocalizedStringFactory(default=1821907359, description="Grayed-out tooltip message when sim doesn't match skill test.")}

    def __init__(self, skill, threshold, **kwargs):
        super().__init__(**kwargs)
        self.skill = skill
        self.threshold = threshold

    def get_expected_args(self):
        return {'sims_to_test': interactions.ParticipantType.CustomSim}

    @cached_test
    def __call__(self, sims_to_test=None):
        for sim_to_test in sims_to_test:
            tracker = sim_to_test.get_tracker(self.skill)
            curr_value = tracker.get_user_value(self.skill)
            while not self.threshold.compare(curr_value):
                operator_symbol = sims4.math.Operator.from_function(self.threshold.comparison).symbol
                return TestResult(False, '{} failed stat check: {}.{} {} {} (current value: {})', sim_to_test.name, sim_to_test.__class__.__name__, self.skill.__name__, operator_symbol, self.threshold.value, curr_value, tooltip=self.tooltip(sim_to_test))
        return TestResult.TRUE

TunableUndirectedStatThresholdTest = TunableSingletonFactory.create_auto_factory(UndirectedStatThresholdTest)

class ContentModeTest(event_testing.test_base.BaseTest):
    __qualname__ = 'ContentModeTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': 'Require the game to be set to a specific content mode.', 'mode': TunableEnumEntry(server.config_service.ContentModes, default=server.config_service.ContentModes.PRODUCTION, description='Required mode.')}

    def __init__(self, mode, **kwargs):
        super().__init__(**kwargs)
        self.mode = mode

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self):
        current_mode = services.config_service().content_mode
        if current_mode != self.mode:
            return TestResult(False, 'Current content mode in the ConfigService does not allow this interaction.', tooltip=self.tooltip)
        return TestResult.TRUE

TunableContentModeTest = TunableSingletonFactory.create_auto_factory(ContentModeTest)

class ObjectScoringPreferenceTest(event_testing.test_base.BaseTest):
    __qualname__ = 'ObjectScoringPreferenceTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': "Require the Sim to either prefer or not prefer the test's target.", 'require': Tunable(bool, True, description="The Sim's preference is required to be True or required to be False.")}

    def __init__(self, require, **kwargs):
        super().__init__(**kwargs)
        self.require = require

    def get_expected_args(self):
        return {'affordance': ParticipantType.Affordance, 'targets': ParticipantType.Object, 'context': ParticipantType.InteractionContext}

    @cached_test
    def __call__(self, affordance=None, targets=None, context=None):
        preference = affordance.autonomy_preference.preference or affordance.super_affordance.autonomy_preference.preference
        if preference is not None:
            for target in targets:
                is_object_scoring_preferred = context.sim.is_object_use_preferred(preference.tag, target)
                while is_object_scoring_preferred != self.require:
                    return TestResult(False, 'Object preference disallows this interaction.', tooltip=self.tooltip)
            return TestResult.TRUE
        logger.error('A preference tunable test is set on {}, but preference tuning is unset of the affordance.', affordance)
        return TestResult.TRUE

TunableObjectScoringPreferenceTest = TunableSingletonFactory.create_auto_factory(ObjectScoringPreferenceTest)

class ObjectEnvironmentScoreTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'ObjectEnvironmentScoreTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': "\n            Test the object's environment score for a particular mood againts a threshold.\n            ", 'sim_participant': OptionalTunable(description='\n            An Optional Sim to test Environment Score against. If disabled, the\n            Environment Score will not take into acount any Trait modifiers\n            relative to the Sim. If enabled, Trait modifiers will be taken into\n            account.\n            ', tunable=TunableEnumEntry(tunable_type=ParticipantTypeActorTargetSim, default=ParticipantTypeActorTargetSim.TargetSim)), 'object_to_test': TunableEnumEntry(description='\n            The object particiant we want to check the environment score of.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'environment_score_type': TunableVariant(description='\n            The type of environment score to test against. This can be mood\n            based, positive scoring, or negative scoring.\n            ', mood_scoring=TunableTuple(description="\n                Test for a particular mood's environment score on the object.\n                ", mood_to_check=statistics.mood.Mood.TunableReference(description="\n                    The mood to check the participant's environment scoring.\n                    "), threshold=TunableThreshold(description="\n                    The threshold for this mood's scoring to pass.\n                    "), locked_args={'scoring_type': EnvironmentScoreType.MOOD_SCORING}), positive_scoring=TunableTuple(description="\n                Test for the object's positive environment scoring.\n                ", threshold=TunableThreshold(description='\n                    The threshold for negative scoring to pass.\n                    '), locked_args={'scoring_type': EnvironmentScoreType.POSITIVE_SCORING}), negative_scoring=TunableTuple(description="\n                Test for the object's negative environment scoring.\n                ", threshold=TunableThreshold(description='\n                    The threshold for positive scoring to pass.\n                    '), locked_args={'scoring_type': EnvironmentScoreType.NEGATIVE_SCORING}), default='mood_scoring'), 'ignore_emotional_aura': Tunable(description='\n            Whether or not this test cares if Emotional Aura is\n            Enabled/Disabled. If this is checked and the emotional aura is\n            disabled (EmotionEnvironment_Disabled is on the object), then\n            there will be no mood scoring and the test will fail if\n            checking moods. If unchecked, any mood scoring will always\n            affect this test.\n            ', tunable_type=bool, default=False)}

    def get_expected_args(self):
        expected_args = {'objects_to_test': self.object_to_test}
        if self.sim_participant is not None:
            expected_args['sim'] = self.sim_participant
        return expected_args

    @cached_test
    def __call__(self, objects_to_test=None, sim=None):
        if objects_to_test is None:
            return TestResult(False, 'No Object for this affordance.', tooltip=self.tooltip)
        for target in objects_to_test:
            (mood_scores, negative_score, positive_score, _) = target.get_environment_score(sim, ignore_disabled_state=self.ignore_emotional_aura)
            if self.environment_score_type.scoring_type == EnvironmentScoreType.MOOD_SCORING:
                mood_score = mood_scores.get(self.environment_score_type.mood_to_check)
                if not self.environment_score_type.threshold.compare(mood_score):
                    return TestResult(False, 'Object does not meet environment score requirements for mood {}.'.format(self.environment_score_type.mood_to_check), tooltip=self.tooltip)
                    if self.environment_score_type.scoring_type == EnvironmentScoreType.POSITIVE_SCORING:
                        if not self.environment_score_type.threshold.compare(positive_score):
                            return TestResult(False, 'Object does not meet positive environment score requirements.', tooltip=self.tooltip)
                            while self.environment_score_type.scoring_type == EnvironmentScoreType.NEGATIVE_SCORING:
                                if not self.environment_score_type.threshold.compare(negative_score):
                                    return TestResult(False, 'Object does not meet negative environment score requirements.', tooltip=self.tooltip)
                    else:
                        while self.environment_score_type.scoring_type == EnvironmentScoreType.NEGATIVE_SCORING:
                            if not self.environment_score_type.threshold.compare(negative_score):
                                return TestResult(False, 'Object does not meet negative environment score requirements.', tooltip=self.tooltip)
            elif self.environment_score_type.scoring_type == EnvironmentScoreType.POSITIVE_SCORING:
                if not self.environment_score_type.threshold.compare(positive_score):
                    return TestResult(False, 'Object does not meet positive environment score requirements.', tooltip=self.tooltip)
                    while self.environment_score_type.scoring_type == EnvironmentScoreType.NEGATIVE_SCORING:
                        if not self.environment_score_type.threshold.compare(negative_score):
                            return TestResult(False, 'Object does not meet negative environment score requirements.', tooltip=self.tooltip)
            else:
                while self.environment_score_type.scoring_type == EnvironmentScoreType.NEGATIVE_SCORING:
                    if not self.environment_score_type.threshold.compare(negative_score):
                        return TestResult(False, 'Object does not meet negative environment score requirements.', tooltip=self.tooltip)
        return TestResult.TRUE

class DistanceTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'DistanceTest'
    test_events = ()
    FACTORY_TUNABLES = {'threshold': TunableThreshold(description='\n            The distance threshold for this test. The distance between the\n            subject and the target must satisfy this condition in order of the\n            test to pass.\n            '), 'level_modifier': TunableVariant(description='\n            Determine how difference in levels affects distance. A modifier of\n            10, for example, would mean that the distance between two objects is\n            increased by 10 meters for every floor between them.\n            ', specific=TunableRange(description='\n                A meter modifier to add to the distance multiplied by the number\n                of floors between subject and target.\n                ', tunable_type=float, minimum=0, default=8), locked_args={'no_modifier': 0, 'infinite': None}, default='no_modifier'), 'subject': TunableEnumEntry(description='\n            The subject of the test.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'target': TunableEnumEntry(description='\n            The target of the test.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object)}

    def get_expected_args(self):
        return {'subjects': self.subject, 'targets': self.target}

    @cached_test
    def __call__(self, subjects=(), targets=()):
        for subject in subjects:
            if subject.is_sim:
                subject = subject.get_sim_instance()
            for target in targets:
                if target.is_sim:
                    target = target.get_sim_instance()
                if subject is None or target is None:
                    distance = sims4.math.MAX_INT32
                else:
                    distance = (target.position - subject.position).magnitude()
                    level_difference = abs(subject.routing_surface.secondary_id - target.routing_surface.secondary_id)
                    if level_difference:
                        if self.level_modifier is None:
                            distance = sims4.math.MAX_INT32
                        else:
                            distance += level_difference*self.level_modifier
                while not self.threshold.compare(distance):
                    return TestResult(False, 'Distance test failed.', tooltip=self.tooltip)
        return TestResult.TRUE

    def tuning_is_valid(self):
        return self.threshold.value != 0

class RoutabilityTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'RoutabilityTest'
    test_events = ()
    FACTORY_TUNABLES = {'subject': TunableEnumEntry(description='\n            The subject of the test.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'target': TunableEnumEntry(description='\n            The target of the test.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'negate': Tunable(description='\n            If checked, passes the test if the sim does NOT have permissions\n            ', tunable_type=bool, default=False)}

    def get_expected_args(self):
        return {'subjects': self.subject, 'targets': self.target}

    def __call__(self, subjects=(), targets=()):
        for subject in subjects:
            if not subject.is_sim:
                return TestResult(False, "subject of routability test isn't sim.", tooltip=self.tooltip)
            for target in targets:
                if target.is_sim:
                    target = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
                if not target:
                    if self.negate:
                        return TestResult(True)
                    return TestResult(False, "target of routability test isn't instantiated", tooltip=self.tooltip)
                while target.is_on_active_lot():
                    if subject.household.home_zone_id != target.zone_id:
                        subject = subject.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
                        if self.negate:
                            return TestResult(True)
                        return TestResult(False, "subject of routability test isn't instantiated, and not their home lot, and target not in open streets", tooltip=self.tooltip)
                        while True:
                            for role in subject.autonomy_component.active_roles():
                                while not role.has_full_permissions:
                                    if self.negate:
                                        return TestResult(True)
                                    return TestResult(False, "subject of routability test's roll doesn't have full permissions.", tooltip=self.tooltip)
        if self.negate:
            return TestResult(False, 'subject has permission to route to target', tooltip=self.tooltip)
        return TestResult(True)

class PostureTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'PostureTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': '\n            Require the participants of this interaction to pass certain posture\n            tests.\n            ', 'subject': TunableEnumEntry(description='\n            The subject of this posture test.\n            ', tunable_type=ParticipantTypeActorTargetSim, default=ParticipantType.Actor), 'required_postures': TunableList(description='\n            If any posture is specified, the test will fail if the subject is\n            not in one of these postures.\n            ', tunable=TunableReference(manager=services.posture_manager())), 'prohibited_postures': TunableList(description='\n            The test will fail if the subject is in any of these postures.\n            ', tunable=TunableReference(manager=services.posture_manager())), 'container_supports': OptionalTunable(description="\n            Test whether or not the subject's current posture's container\n            supports the specified posture.\n            ", tunable=TunableReference(description="\n                The posture that the container of the subject's current posture\n                must support.\n                ", manager=services.posture_manager()))}

    def __init__(self, *args, **kwargs):
        super().__init__(safe_to_skip=True, *args, **kwargs)

    def get_expected_args(self):
        return {'actors': ParticipantTypeActorTargetSim.Actor, 'targets': ParticipantTypeActorTargetSim.TargetSim}

    @cached_test
    def __call__(self, actors, targets):
        if self.subject == ParticipantTypeActorTargetSim.Actor:
            subject_sim = next(iter(actors), None)
            target_sim = next(iter(targets), None)
        else:
            subject_sim = next(iter(targets), None)
            target_sim = next(iter(actors), None)
        if subject_sim is None:
            return TestResult(False, 'Posture test failed because the actor is None.')
        subject_sim = subject_sim.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if subject_sim is None:
            return TestResult(False, 'Posture test failed because the actor is non-instantiated.', tooltip=self.tooltip)
        if target_sim is not None:
            target_sim = target_sim.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if self.required_postures:
            for posture_aspect in subject_sim.posture_state.aspects:
                while not any(posture_aspect.posture_type is required_posture and (not required_posture.multi_sim or posture_aspect.linked_sim is target_sim) for required_posture in self.required_postures):
                    return TestResult(False, '{} is not in one of the required postures ({})', subject_sim, posture_aspect, tooltip=self.tooltip)
        if self.prohibited_postures:
            for posture_aspect in subject_sim.posture_state.aspects:
                while any(posture_aspect.posture_type is prohibited_posture for prohibited_posture in self.prohibited_postures):
                    return TestResult(False, '{} is in a prohibited posture ({})', subject_sim, posture_aspect, tooltip=self.tooltip)
        if self.container_supports is not None:
            container = subject_sim.posture.target
            if container is None or not container.is_part:
                return TestResult(False, 'Posture container for {} is None or not a part', subject_sim.posture, tooltip=self.tooltip)
            if not container.supports_posture_type(self.container_supports):
                return TestResult(False, 'Posture container {} does not support {}', container, self.container_supports, tooltip=self.tooltip)
            if self.container_supports.multi_sim:
                if target_sim is None:
                    return TestResult(False, 'Posture test failed because the target is None')
                if target_sim is None:
                    return TestResult(False, 'Posture test failed because the target is non-instantiated.')
                if not container.has_adjacent_part(target_sim):
                    return TestResult(False, 'Posture container {} requires an adjacent part for {} since {} is multi-Sim', container, target_sim, self.container_supports, tooltip=self.tooltip)
        return TestResult.TRUE

class IdentityTest(AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'IdentityTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': '\n            Require the specified participants to be the same, or,\n            alternatively, require them to be different.\n            ', 'subject_a': TunableEnumEntry(description='\n            The participant to be compared to subject_b.\n            ', tunable_type=ParticipantTypeSingle, default=ParticipantTypeSingle.Actor), 'subject_b': TunableEnumEntry(description='\n            The participant to be compared to subject_a.\n            ', tunable_type=ParticipantTypeSingle, default=ParticipantTypeSingle.Object), 'subjects_match': Tunable(description='\n            If True, subject_a must match subject_b. If False, they must not.\n            ', tunable_type=bool, default=False)}

    def get_expected_args(self):
        return {'subject_a': self.subject_a, 'subject_b': self.subject_b, 'affordance': ParticipantType.Affordance, 'context': ParticipantType.InteractionContext}

    @cached_test
    def __call__(self, subject_a=None, subject_b=None, affordance=None, context=None):
        subject_a = next(iter(subject_a), None)
        subject_b = next(iter(subject_b), None)
        if subject_a is None and (self.subject_a == ParticipantType.TargetSim or self.subject_a == ParticipantType.Object):
            subject_a = context.sim.sim_info
        if affordance is not None and (affordance.target_type == TargetType.ACTOR and subject_b is None) and (self.subject_b == ParticipantType.TargetSim or self.subject_b == ParticipantType.Object):
            subject_b = context.sim.sim_info
        if self.subjects_match:
            if subject_a is not subject_b:
                return TestResult(False, '{} must match {}, but {} is not {}', self.subject_a, self.subject_b, subject_a, subject_b, tooltip=self.tooltip)
        elif subject_a is subject_b:
            return TestResult(False, '{} must not match {}, but {} is {}', self.subject_a, self.subject_b, subject_a, subject_b, tooltip=self.tooltip)
        return TestResult.TRUE

TunableIdentityTest = TunableSingletonFactory.create_auto_factory(IdentityTest)

class SituationRunningTest(event_testing.test_base.BaseTest):
    __qualname__ = 'SituationRunningTest'
    test_events = (TestEvent.SituationEnded,)
    FACTORY_TUNABLES = {'description': '\n            A test to see if the participant is part of any situations that are\n            running that satisfy the conditions of the test.\n            ', 'participant': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='\n                The subject of this situation test.\n                '), 'situation_whitelist': TunableSet(TunableReference(services.situation_manager()), description='\n            A Set of situations that are tested to see if the participant\n            is part of any of them.\n            \n            If no situations are tuned then all situations match.\n            '), 'situation_blacklist': TunableSet(TunableReference(services.situation_manager()), description='\n            A Set of situations that will fail the test if the participant\n            is part of any of them.\n            '), 'level': TunableThreshold(description='\n                A check for the level of the situation we are checking.\n                '), 'check_for_initiating_sim': Tunable(bool, False, description='\n                If checked then this will check to make sure that the sim that\n                is being checked is the sim that initiated the situation.\n                ')}

    def __init__(self, participant, situation_whitelist, situation_blacklist, level, check_for_initiating_sim, **kwargs):
        super().__init__(**kwargs)
        self.participant = participant
        self.situation_whitelist = situation_whitelist
        self.situation_blacklist = situation_blacklist
        self.level = level
        self.check_for_initiating_sim = check_for_initiating_sim

    def get_expected_args(self):
        return {'test_targets': self.participant, 'situation': event_testing.test_events.FROM_EVENT_DATA}

    def _check_situation(self, situation, target):
        if situation is None:
            return TestResult(False, 'SituationTest: Situtaion is None, normal during zone load.')
        if self.situation_whitelist and type(situation) not in self.situation_whitelist:
            return TestResult(False, 'SituationTest: Situtaion not in situation whitelist.', tooltip=self.tooltip)
        if self.situation_blacklist and type(situation) in self.situation_blacklist:
            return TestResult(False, 'SituationTest: Situation is in situation blacklist.', tooltip=self.tooltip)
        level = situation.get_level()
        if level is None or not self.level.compare(level):
            return TestResult(False, 'SituationTest: Situation not of proper level.', tooltip=self.tooltip)
        if self.check_for_initiating_sim and situation.initiating_sim_info is not target:
            return TestResult(False, 'SituationTest: Sim is not initiating sim of the situation.', tooltip=self.tooltip)
        return TestResult.TRUE

    @cached_test
    def __call__(self, test_targets=None, situation=None):
        for target in test_targets:
            if not target.is_sim:
                return TestResult(False, 'SituationTest: Target {} is not a sim.', target, tooltip=self.tooltip)
            if situation is not None:
                return self._check_situation(situation, target)
            if target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                return TestResult(False, 'SituationTest: uninstantiated sim {} cannot be in any situations.', target, tooltip=self.tooltip)
            target_sim = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            situations = services.get_zone_situation_manager().get_situations_sim_is_in(target_sim)
            if situations:
                for situation in situations:
                    result = self._check_situation(situation, target)
                    while result:
                        return result
            elif not self.situation_whitelist and self.situation_blacklist:
                return TestResult.TRUE

TunableSituationRunningTest = TunableSingletonFactory.create_auto_factory(SituationRunningTest)

class UserFacingSituationRunningTest(event_testing.test_base.BaseTest):
    __qualname__ = 'UserFacingSituationRunningTest'
    FACTORY_TUNABLES = {'description': '\n            Test to see if there is a user facing situation running or not.\n            ', 'is_running': Tunable(bool, False, description='\n                If checked then this test will return true if a user facing\n                situation is running in the current zone.  If not checked then\n                this test will return false if a user facing situation is\n                running in this zone.\n                ')}

    def __init__(self, is_running, **kwargs):
        super().__init__(**kwargs)
        self.is_running = is_running

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self):
        is_user_facing_situation_running = services.get_zone_situation_manager().is_user_facing_situation_running()
        if self.is_running:
            if is_user_facing_situation_running:
                return TestResult.TRUE
            return TestResult(False, 'UserFacingSituationRunningTest: A user facing situation is not running.', tooltip=self.tooltip)
        else:
            if is_user_facing_situation_running:
                return TestResult(False, 'UserFacingSituationRunningTest: A user facing situation is running.', tooltip=self.tooltip)
            return TestResult.TRUE

TunableUserFacingSituationRunningTest = TunableSingletonFactory.create_auto_factory(UserFacingSituationRunningTest)

class SituationJobTest(event_testing.test_base.BaseTest):
    __qualname__ = 'SituationJobTest'
    FACTORY_TUNABLES = {'description': '\n            Require the tuned participant to have a specific situation job.\n            If multiple participants, ALL participants must have the required\n            job to pass.\n            ', 'participant': TunableEnumEntry(description='\n                The subject of this situation job test.\n                ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'situation_jobs': TunableSet(description='\n                The participant must have this job in this list or a job that\n                matches the role_tags.\n                ', tunable=TunableReference(services.situation_job_manager())), 'role_tags': TunableSet(description='\n                The  participant must have a job that matches the role_tags or\n                have the situation_job.\n                ', tunable=TunableEnumEntry(tag.Tag, tag.Tag.INVALID)), 'negate': Tunable(description='\n                If checked then the test result will be reversed, so it will\n                test to see if they are not in a job or not in role state\n                that has matching tags.\n                ', tunable_type=bool, default=False)}

    def __init__(self, participant, situation_jobs, role_tags, negate, **kwargs):
        super().__init__(**kwargs)
        self.participant = participant
        self.situation_jobs = situation_jobs
        self.role_tags = role_tags
        self.negate = negate

    def get_expected_args(self):
        return {'test_targets': self.participant}

    @cached_test
    def __call__(self, test_targets=None):
        if not test_targets:
            return TestResult(False, 'SituationJobTest: No test targets to check.')
        for target in test_targets:
            if not target.is_sim:
                return TestResult(False, 'SituationJobTest: Test being run on target {} that is not a sim.', target, tooltip=self.tooltip)
            if target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                return TestResult(False, 'SituationJobTest: {} is not an instantiated sim.', target, tooltip=self.tooltip)
            target = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            sim_has_job = False
            for situation in services.get_zone_situation_manager().get_situations_sim_is_in(target):
                current_job_type = situation.get_current_job_for_sim(target)
                if current_job_type in self.situation_jobs:
                    sim_has_job = True
                    break
                else:
                    while self.role_tags & situation.get_role_tags_for_sim(target):
                        sim_has_job = True
                        break
            if self.negate:
                if sim_has_job:
                    return TestResult(False, "SituationJobTest: Sim has the required jobs when it shouldn't.")
                    while not sim_has_job:
                        return TestResult(False, 'SituationJobTest: Sim does not have required situation job.')
            else:
                while not sim_has_job:
                    return TestResult(False, 'SituationJobTest: Sim does not have required situation job.')
        return TestResult.TRUE

TunableSituationJobTest = TunableSingletonFactory.create_auto_factory(SituationJobTest)

class SituationAvailabilityTest(event_testing.test_base.BaseTest):
    __qualname__ = 'SituationAvailabilityTest'
    FACTORY_TUNABLES = {'description': "Test whether it's possible for this Sim to host a particular Situation.", 'situation': TunableReference(description='\n            The Situation to test against\n            ', manager=services.situation_manager())}

    def __init__(self, situation, **kwargs):
        super().__init__(**kwargs)
        self.situation = situation

    def get_expected_args(self):
        return {'hosts': ParticipantType.Actor, 'targets': ParticipantType.TargetSim}

    @cached_test
    def __call__(self, hosts, targets=None):
        for host in hosts:
            if self.situation.cost() > host.household.funds.money:
                return TestResult(False, 'Cannot afford this Situation.', tooltip=self.tooltip)
            for target in targets:
                target_sim_id = 0 if target is None else target.id
                while not self.situation.is_situation_available(host, target_sim_id):
                    return TestResult(False, 'Sim not allowed to host this Situation or Target not allowed to come.')
        return TestResult.TRUE

TunableSituationAvailabilityTest = TunableSingletonFactory.create_auto_factory(SituationAvailabilityTest)

class CraftedWithSkillFactory(TunableFactory):
    __qualname__ = 'CraftedWithSkillFactory'

    @staticmethod
    def factory(crafted_object, skill, skill_to_test):
        return skill is skill_to_test

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(skill_to_test=TunableReference(services.statistic_manager(), description='Skills needed to pass amount on.'), description='This option tests for an item craft with the selected skill', **kwargs)

class CraftActualItemFactory(TunableFactory):
    __qualname__ = 'CraftActualItemFactory'

    @staticmethod
    def factory(crafted_object, skill, items_to_check):
        item_ids = [definition.id for definition in items_to_check]
        return crafted_object.definition.id in item_ids

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(items_to_check=TunableList(TunableReference(services.definition_manager(), description='Object that qualifies for this check.')), description='This option tests crafted item against a list of possible items', **kwargs)

class CraftTaggedItemFactory(TunableFactory):
    __qualname__ = 'CraftTaggedItemFactory'

    @staticmethod
    def factory(crafted_object, skill, tag_set, test_type, **kwargs):
        object_tags = crafted_object.get_tags()
        if test_type == TagTestType.CONTAINS_ANY_TAG_IN_SET:
            return object_tags & tag_set
        if test_type == TagTestType.CONTAINS_ALL_TAGS_IN_SET:
            return object_tags & tag_set == tag_set
        if test_type == TagTestType.CONTAINS_NO_TAGS_IN_SET:
            return not object_tags & tag_set
        return False

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(tag_set=sims4.tuning.tunable.TunableSet(TunableEnumEntry(tag.Tag, tag.Tag.INVALID, description='What tag to test for'), description='The tag of objects we want to test ownership of'), test_type=TunableEnumEntry(TagTestType, TagTestType.CONTAINS_ANY_TAG_IN_SET, description='How to test the tags in the tag set against the objects on the lot.'), description="This option tests crafted item's tags against a list of possible tags", **kwargs)

class BasicStateCheckFactory(TunableFactory):
    __qualname__ = 'BasicStateCheckFactory'

    @staticmethod
    def factory(tested_object, state_set, test_type, **kwargs):
        if tested_object.state_component is None:
            return False
        object_states = set(tested_object.state_component.values())
        if test_type == StateTestType.CONTAINS_ANY_STATE_IN_SET:
            return object_states & state_set
        if test_type == StateTestType.CONTAINS_ALL_STATES_IN_SET:
            return object_states & state_set == state_set
        if test_type == StateTestType.CONTAINS_NO_STATE_IN_SET:
            return object_states & state_set == 0
        return False

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(description="\n            This option tests crafted item's tags against a list of possible\n            tags.", state_set=sims4.tuning.tunable.TunableSet(TunableReference(description='\n                What state to test for.', manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE))), test_type=TunableEnumEntry(description='\n                How to test the states in the state set against the objects in\n                the inventory.', tunable_type=StateTestType, default=StateTestType.CONTAINS_ANY_STATE_IN_SET), **kwargs)

class CraftedItemTest(event_testing.test_base.BaseTest):
    __qualname__ = 'CraftedItemTest'
    test_events = (TestEvent.ItemCrafted,)
    UNIQUE_TARGET_TRACKING_AVAILABLE = True
    TAG_CHECKLIST_TRACKING_AVAILABLE = True
    FACTORY_TUNABLES = {'description': 'Require the participant to have crafted a number of specific quality items.', 'skill_or_item': TunableVariant(crafted_with_skill=CraftedWithSkillFactory(), crafted_actual_item=CraftActualItemFactory(), crafted_tagged_item=CraftTaggedItemFactory(), default='crafted_with_skill', description='Whether to test for a specific item or use of a skill for the item.'), 'quality_threshold': TunableObjectStateValueThreshold(description='The quality threshold for this test.'), 'masterwork_threshold': TunableObjectStateValueThreshold(description='The masterwork threshold for this test.')}

    def __init__(self, skill_or_item, quality_threshold, masterwork_threshold, **kwargs):
        super().__init__(**kwargs)
        self.skill_or_item = skill_or_item
        self.quality_threshold = quality_threshold
        self.masterwork_threshold = masterwork_threshold

    def get_expected_args(self):
        return {'crafted_object': event_testing.test_events.FROM_EVENT_DATA, 'skill': event_testing.test_events.FROM_EVENT_DATA, 'quality': event_testing.test_events.FROM_EVENT_DATA, 'masterwork': event_testing.test_events.FROM_EVENT_DATA}

    @cached_test
    def __call__(self, crafted_object=None, skill=None, quality=None, masterwork=None):
        if crafted_object is None:
            return TestResult(False, 'CraftedItemTest: Object created is None, normal during zone load.')
        match = self.skill_or_item(crafted_object, skill)
        if not match:
            return TestResult(False, 'CraftedItemTest: Object created either with wrong skill or was not being checked.')
        if masterwork is None:
            return TestResult(False, 'CraftedItemTest: Looking for a masterwork and object masterwork state was None.')
        if not (self.masterwork_threshold.value is not None and self.masterwork_threshold.value != 0 and self.masterwork_threshold.compare(masterwork.value)):
            return TestResult(False, 'CraftedItemTest: Object does not match masterwork state level desired.')
        if quality is None:
            return TestResult(False, 'CraftedItemTest: Item quality is None.')
        if not (self.quality_threshold.value is not None and self.quality_threshold.value != 0 and self.quality_threshold.compare(quality.value)):
            return TestResult(False, 'CraftedItemTest: Item is not of desired quality.')
        return TestResult.TRUE

    def get_target_id(self, crafted_object=None, skill=None, quality=None, masterwork=None, id_type=None):
        if crafted_object is None:
            return
        if id_type == TargetIdTypes.DEFAULT or id_type == TargetIdTypes.DEFINITION:
            return crafted_object.definition.id
        if id_type == TargetIdTypes.INSTANCE:
            return crafted_object.id
        logger.error('Unique target ID type: {} is not supported for test: {}', id_type, self)

    def get_tags(self, crafted_object=None, skill=None, quality=None, masterwork=None):
        if crafted_object is None:
            return ()
        return crafted_object.get_tags()

TunableCraftedItemTest = TunableSingletonFactory.create_auto_factory(CraftedItemTest)

class GameTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'GameTest'
    FACTORY_TUNABLES = {'description': "\n            Require the participant's game component information to match the\n            specified conditions.\n            ", 'participant': TunableEnumEntry(description='\n            The subject of this game test.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'is_sim_turn': OptionalTunable(description="\n            Whether it must or must not be the participant's turn in this game.\n            ", tunable=Tunable(bool, True)), 'number_of_players': OptionalTunable(description='\n            The number of players required for this interaction to run.\n            ', tunable=TunableInterval(int, 0, 0, minimum=0)), 'is_winner': OptionalTunable(description='\n            Whether the participant must be the winner or loser of this game.\n            ', tunable=Tunable(bool, True)), 'can_join': OptionalTunable(description='\n            If enabled, require the current game to be either joinable or non-\n            joinable.  If disabled, ignore joinability.\n            ', tunable=Tunable(bool, True)), 'requires_setup': OptionalTunable(description='\n            If enabled, require the game to either be set up or not set up.  If\n            disabled, ignore this state.\n            ', tunable=Tunable(bool, True)), 'game_over': OptionalTunable(description='\n            If enabled, require the game to have either ended or not ended.  If\n            disabled, ignore this state. A game is considered to be over if\n            there is either no active game, or if a winning team has been\n            chosen.\n            ', tunable=Tunable(bool, True))}

    def get_expected_args(self):
        return {'participants': self.participant, 'actor': ParticipantType.Actor, 'target': ParticipantType.TargetSim, 'objects': ParticipantType.Object}

    @cached_test
    def __call__(self, participants, actor, target, objects):
        game = None
        for obj in objects:
            while obj.game_component is not None:
                game = obj.game_component
                target_object = obj
        if game is None:
            sim_infos = actor + target
            for sim_info in sim_infos:
                if sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                    return TestResult(False, 'GameTest: Cannot run game test on uninstantiated sim.', tooltip=self.tooltip)
                sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
                while True:
                    for si in sim.si_state:
                        target_group = si.get_participant(ParticipantType.SocialGroup)
                        target_object = target_group.anchor if target_group is not None else None
                        while target_object is not None and target_object.game_component is not None:
                            game = target_object.game_component
                            break
                break
        if game is None:
            return TestResult(False, 'GameTest: Not able to find a valid Game.', tooltip=self.tooltip)
        for participant in participants:
            if not participant.is_sim:
                return TestResult(False, 'GameTest: The participant is not a sim.', tooltip=self.tooltip)
            if participant.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                return TestResult(False, 'GameTest: The participant is not an instantiated sim.', tooltip=self.tooltip)
            sim = participant.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            if self.is_sim_turn is not None and game.is_sim_turn(sim) != self.is_sim_turn:
                return TestResult(False, 'GameTest: The participant does not fulfill the turn requirement.', tooltip=self.tooltip)
            if self.number_of_players is not None:
                player_num = game.number_of_players
                if not self.number_of_players.lower_bound <= player_num <= self.number_of_players.upper_bound:
                    return TestResult(False, 'GameTest: Number of players required to be withing {} and {}, but the actual number of players is {}.', self.number_of_players.lower_bound, self.number_of_players.upper_bound, player_num, tooltip=self.tooltip)
            if self.is_winner is not None:
                if game.winning_team is not None:
                    in_winning_team = sim in game.winning_team
                    if self.is_winner != in_winning_team:
                        return TestResult(False, "GameTest: Sim's win status is not correct.", tooltip=self.tooltip)
                        return TestResult(False, 'GameTest: Game is over and no win status specified for this test.', tooltip=self.tooltip)
                else:
                    return TestResult(False, 'GameTest: Game is over and no win status specified for this test.', tooltip=self.tooltip)
            if self.can_join is not None and game.is_joinable(sim) != self.can_join:
                return TestResult(False, "GameTest: Sim's join status is not correct.", tooltip=self.tooltip)
            if game.current_game is None:
                return TestResult(False, 'GameTest: Cannot test setup conditions because no game has been started.', tooltip=self.tooltip)
            if self.requires_setup is not None and game.requires_setup != self.requires_setup:
                return TestResult(False, "GameTest: Game's setup requirements do not match this interaction's setup requirements.", tooltip=self.tooltip)
            while self.game_over is not None:
                if game.game_has_ended != self.game_over:
                    return TestResult(False, "GameTest: Game's GameOver state does not match this interaction's GameOver state requirements.", tooltip=self.tooltip)
        return TestResult.TRUE

class BillsTest(event_testing.test_base.BaseTest):
    __qualname__ = 'BillsTest'
    FACTORY_TUNABLES = {'description': "Require the participant's bill status to match the specified conditions.", 'participant': TunableEnumEntry(description='\n            The subject whose household is the object of this delinquency test.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'delinquency_states': OptionalTunable(TunableList(TunableTuple(description='\n            Tuple containing a utility and its required delinquency state.\n            ', utility=TunableEnumEntry(sims.bills_enums.Utilities, None), is_delinquent=Tunable(description='\n                Whether this utility is required to be delinquent or not delinquent.\n                ', tunable_type=bool, default=True)))), 'additional_bills_delinquency_states': OptionalTunable(TunableList(TunableTuple(description='\n            Tuple containing an AdditionalBillSource and its required\n            delinquency state. EX: This interaction requires that the\n            Maid_Service bill source not be delinquent.\n            ', bill_source=TunableEnumEntry(sims.bills_enums.AdditionalBillSource, None), is_delinquent=Tunable(description='\n                Whether this AdditionalBillSource is required to be delinquent or not delinquent.\n                ', tunable_type=bool, default=True)))), 'payment_due': OptionalTunable(Tunable(description='\n            Whether or not the participant is required to have a bill payment due.\n            ', tunable_type=bool, default=True)), 'test_participant_owned_households': Tunable(description="\n            If checked, this test will check the delinquency states of all the\n            participant's households.  If unchecked, this test will check the\n            delinquency states of the owning household of the active lot.\n            ", tunable_type=bool, default=False)}

    def __init__(self, participant, delinquency_states, additional_bills_delinquency_states, payment_due, test_participant_owned_households, **kwargs):
        super().__init__(**kwargs)
        self.participant = participant
        self.delinquency_states = delinquency_states
        self.additional_bills_delinquency_states = additional_bills_delinquency_states
        self.payment_due = payment_due
        self.test_participant_owned_households = test_participant_owned_households

    def get_expected_args(self):
        return {'test_targets': self.participant}

    @cached_test
    def __call__(self, test_targets=None):
        if not self.test_participant_owned_households:
            target_households = [services.owning_household_of_active_lot()]
        else:
            target_households = []
            for target in test_targets:
                target_households.append(services.household_manager().get_by_sim_id(target.id))
        for household in target_households:
            if self.delinquency_states is not None:
                for state in self.delinquency_states:
                    if household is None:
                        if state.is_delinquent:
                            return TestResult(False, 'BillsTest: Required {} to be delinquent, but there is no active household.', state.utility, tooltip=self.tooltip)
                            while household.bills_manager.is_utility_delinquent(state.utility) != state.is_delinquent:
                                return TestResult(False, "BillsTest: Participant's delinquency status for the {} utility is not correct.", state.utility, tooltip=self.tooltip)
                    else:
                        while household.bills_manager.is_utility_delinquent(state.utility) != state.is_delinquent:
                            return TestResult(False, "BillsTest: Participant's delinquency status for the {} utility is not correct.", state.utility, tooltip=self.tooltip)
            if self.additional_bills_delinquency_states is not None:
                for state in self.additional_bills_delinquency_states:
                    if household is None:
                        if state.is_delinquent:
                            return TestResult(False, 'BillsTest: Required {} to be delinquent, but there is no active household.', state.bill_source, tooltip=self.tooltip)
                            while household.bills_manager.is_additional_bill_source_delinquent(state.bill_source) != state.is_delinquent:
                                return TestResult(False, "BillsTest: Participant's delinquency status for the {} additional bill source is not correct.", state.bill_source, tooltip=self.tooltip)
                    else:
                        while household.bills_manager.is_additional_bill_source_delinquent(state.bill_source) != state.is_delinquent:
                            return TestResult(False, "BillsTest: Participant's delinquency status for the {} additional bill source is not correct.", state.bill_source, tooltip=self.tooltip)
            while self.payment_due is not None:
                if household is not None:
                    household_payment_due = household.bills_manager.mailman_has_delivered_bills()
                else:
                    household_payment_due = False
                if household_payment_due != self.payment_due:
                    return TestResult(False, "BillsTest: Participant's active bill status does not match the specified active bill status.", tooltip=self.tooltip)
        return TestResult.TRUE

TunableBillsTest = TunableSingletonFactory.create_auto_factory(BillsTest)

class ExistenceTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'ExistenceTest'
    FACTORY_TUNABLES = {'description': '\n            A test to check whether the specified participant exists.\n            ', 'participant': TunableEnumEntry(description='\n            The participant for which to check existence.\n            ', tunable_type=ParticipantType, default=ParticipantType.TargetSim), 'exists': Tunable(description='\n            When checked, require the specified participant to exist. When\n            unchecked, require the specified participant to not exist.\n            ', tunable_type=bool, default=True)}

    def get_expected_args(self):
        return {'test_targets': self.participant}

    @staticmethod
    def _exists(obj):
        if obj.is_sim:
            return obj.get_sim_instance(allow_hidden_flags=0) is not None
        return not obj.is_hidden() and obj.id in services.object_manager()

    @cached_test
    def __call__(self, test_targets=()):
        if self.exists:
            if not test_targets or not all(self._exists(obj) for obj in test_targets):
                return TestResult(False, 'Participant {} does not exist', self.participant, tooltip=self.tooltip)
        elif any(self._exists(obj) for obj in test_targets):
            return TestResult(False, 'Participant {} exists', self.participant, tooltip=self.tooltip)
        return TestResult.TRUE

class InventoryTest(HasTunableSingletonFactory, event_testing.test_base.BaseTest):
    __qualname__ = 'InventoryTest'
    PARTICIPANT_INVENTORY = 0
    GLOBAL_OBJECT_INVENTORY = 1
    HIDDEN_INVENTORY = 2
    TAGGED_ITEM_TEST = 0
    ITEM_DEFINITION_TEST = 1
    PARTICIPANT_TYPE_TEST = 2
    ITEM_STATE_TEST = 3
    test_events = (TestEvent.OnInventoryChanged,)
    FACTORY_TUNABLES = {'description': '\n            A test to check on the contents of either a sim inventory or\n            an object inventory.\n            ', 'inventory_location': TunableVariant(description='\n            Who owns the inventory. Either look in the inventory of a \n            participant or specify an object inventory type directly.\n            \n            If participant returns multiple inventory owners, the test will \n            pass only if ALL of those owners pass the inventory content test.\n            ', participant_inventory=TunableTuple(inventory=TunableEnumEntry(description='\n                    The owner of the inventory\n                    ', tunable_type=ParticipantType, default=ParticipantType.Actor), locked_args={'location_type': PARTICIPANT_INVENTORY}), object_inventory_type=TunableTuple(inventory=TunableEnumEntry(description='\n                    Check the global Object inventory that has the specified type.\n                    EX: check in the global fridge inventory that exists for all\n                    fridges\n                    ', tunable_type=objects.components.inventory_enums.InventoryType, default=objects.components.inventory_enums.InventoryType.UNDEFINED), locked_args={'location_type': GLOBAL_OBJECT_INVENTORY}), hidden_inventory_objects=TunableTuple(inventory=TunableEnumEntry(description='\n                    Check in the hidden inventory for objects that can go into the\n                    specified inventory type. EX: check that there are mailbox\n                    objects in the hidden inventory\n                    ', tunable_type=objects.components.inventory_enums.InventoryType, default=objects.components.inventory_enums.InventoryType.UNDEFINED), locked_args={'location_type': HIDDEN_INVENTORY}), default='participant_inventory'), 'contents_check': TunableVariant(description='\n            Checks to run on each object of the specified inventory\n            ', has_object_with_tag=CraftTaggedItemFactory(locked_args={'content_check_type': TAGGED_ITEM_TEST}), has_object_with_def=TunableTuple(definition=TunableReference(description='\n                    The object definition to look for inside inventory.\n                    ', manager=services.definition_manager()), locked_args={'content_check_type': ITEM_DEFINITION_TEST}), has_object_of_participant_type=TunableTuple(description='\n                Participant type we want to test if its in the selected\n                inventory.\n                ', participant=TunableEnumEntry(description='\n                    Which participant of the interaction do we want to validate\n                    on the inventory. \n                    ', tunable_type=ParticipantType, default=ParticipantType.Object), locked_args={'content_check_type': PARTICIPANT_TYPE_TEST}), has_object_with_states=BasicStateCheckFactory(locked_args={'content_check_type': ITEM_STATE_TEST}), locked_args={'has_anything': None}, default='has_anything'), 'required_count': TunableThreshold(description='\n            The inventory must have a tunable threshold of objects that\n            pass the contents check test.\n            \n            EX: test is object definition of type pizza. required count is enabled\n            and has a threshold of >= 5. That means this test will pass if you\n            have 5 or more pizzas in your inventory. To check if any objects\n            exist, use required count >= 1\n            ', value=Tunable(int, 1, description='The value of a threshold.'), default=sims4.math.Threshold(1, sims4.math.Operator.GREATER_OR_EQUAL.function))}

    def __init__(self, inventory_location, contents_check, required_count, **kwargs):
        super().__init__(**kwargs)
        self.inventory_location = inventory_location
        self.contents_check = contents_check
        self.required_count = required_count

    def get_expected_args(self):
        arguments = {}
        if self.inventory_location.location_type == InventoryTest.PARTICIPANT_INVENTORY:
            arguments['inventory_owners'] = self.inventory_location.inventory
        if self.contents_check is not None and self.contents_check.content_check_type == self.PARTICIPANT_TYPE_TEST:
            arguments['content_check_participant'] = self.contents_check.participant
        return arguments

    @cached_test
    def __call__(self, inventory_owners=None, content_check_participant=None):
        inventories = []
        location_type = self.inventory_location.location_type
        if location_type == InventoryTest.GLOBAL_OBJECT_INVENTORY:
            inventory = services.active_lot().get_object_inventory(self.inventory_location.inventory)
        else:
            hidden_inventory = services.active_lot().get_object_inventory(objects.components.inventory_enums.InventoryType.HIDDEN)
            inventory = []
            if hidden_inventory is not None:
                for obj in hidden_inventory:
                    while obj.can_go_in_inventory_type(self.inventory_location.inventory):
                        inventory.append(obj)
        if not inventory:
            return TestResult(False, 'Inventory {} does not exist or has no items', self.inventory_location, tooltip=self.tooltip)
        inventories.append(inventory)
        for inv in inventories:
            count = 0
            contents_check = self.contents_check
            if contents_check is None:
                count = len(inv)
            else:
                content_check_type = contents_check.content_check_type
                for item in inv:
                    item_definition_id = item.definition.id
                    if content_check_type == self.ITEM_DEFINITION_TEST:
                        count += item.stack_count()
                    elif content_check_type == self.TAGGED_ITEM_TEST:
                        count += item.stack_count()
                    elif content_check_type == self.PARTICIPANT_TYPE_TEST:
                        for check_participant in content_check_participant:
                            while item_definition_id == check_participant.definition.id:
                                count += item.stack_count()
                    elif content_check_type == self.ITEM_STATE_TEST:
                        count += item.stack_count()
                    else:
                        logger.error('Unsupported content check type {} in Inventory Test', content_check_type, owner='yshan')
                        break
            while not self.required_count.compare(count):
                return TestResultNumeric(False, 'Inventory {} does not have required number of objects in it', inv, tooltip=self.tooltip, current_value=count, goal_value=self.required_count.value, is_money=False)
        return TestResultNumeric(True, current_value=count, goal_value=self.required_count.value, is_money=False)

    def goal_value(self):
        return self.required_count.value

class InInventoryTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'InInventoryTest'
    FACTORY_TUNABLES = {'description': 'Require that the specified participant is in, or not in, an inventory of a particular type.', 'participant': TunableEnumEntry(description='\n            The participant to test.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'inventory_type': TunableEnumEntry(description='\n            The inventory type to test.\n            ', tunable_type=objects.components.inventory_enums.InventoryType, default=objects.components.inventory_enums.InventoryType.UNDEFINED), 'negate': Tunable(description='\n            If enabled, we will check that the participant IS NOT in the specified inventory type.\n            If disabled, we will check that the participant IS in the specified inventory type.\n            ', tunable_type=bool, default=False)}

    def get_expected_args(self):
        return {'objs': self.participant}

    @cached_test
    def __call__(self, objs):
        for obj in objs:
            inventoryitem_component = obj.inventoryitem_component
            if inventoryitem_component is None:
                return TestResult(False, "Failed InInventory test because the participant doesn't have an InventoryItemComponent.", tooltip=self.tooltip)
            current_inventory_type = inventoryitem_component.current_inventory_type
            if current_inventory_type == self.inventory_type and not self.negate:
                return TestResult.TRUE
            while current_inventory_type != self.inventory_type and self.negate:
                return TestResult.TRUE
        return TestResult(False, 'Failed InInventory test.', tooltip=self.tooltip)

class HouseholdSizeTest(event_testing.test_base.BaseTest, HasTunableSingletonFactory):
    __qualname__ = 'HouseholdSizeTest'
    test_events = (TestEvent.HouseholdChanged,)
    COUNT_FROM_PARTICIPANT = 0
    COUNT_EXPLICIT = 1
    COUNT_ACTUAL_SIZE = 2
    FACTORY_TUNABLES = {'description': "\n            Require the specified participant's household to have a specified\n            number of free Sim slots.\n            ", 'participant': TunableEnumEntry(description='\n            The subject whose household is the object of this test.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'test_type': TunableVariant(description='\n            The type of test to \n            ', participant=TunableTuple(description="\n                Use this option when you're testing a specific Sim being added\n                to the household.\n                ", locked_args={'count_type': COUNT_FROM_PARTICIPANT}, participant=TunableEnumEntry(description='\n                    The participant whose required slot count we consider.\n                    ', tunable_type=ParticipantType, default=ParticipantType.TargetSim)), count=TunableTuple(description="\n                Use this option when you're testing for a specific number of\n                free slots in the household.\n                ", locked_args={'count_type': COUNT_EXPLICIT}, count=TunableThreshold(description='\n                    The number of required free slots for the specified\n                    household.\n                    ', value=Tunable(description='\n                        The value of a threshold.\n                        ', tunable_type=int, default=1), default=sims4.math.Threshold(1, sims4.math.Operator.GREATER_OR_EQUAL.function))), actual_size=TunableTuple(description="\n                Use this option when you're testing the actual number of sims\n                in a household.  This should not be used for testing if you\n                are able to add a sim to the household and should only be used\n                for functionality that depents on the actual household members\n                being there and not counting reserved slots.\n                ex. Achievement for having a household of 8 sims.\n                ", locked_args={'count_type': COUNT_ACTUAL_SIZE}, count=TunableThreshold(description='\n                    The number of household members.\n                    ', value=Tunable(description='\n                        The value of a threshold.\n                        ', tunable_type=int, default=1), default=sims4.math.Threshold(1, sims4.math.Operator.GREATER_OR_EQUAL.function))), default='count')}

    def __init__(self, participant, test_type, **kwargs):
        super().__init__(**kwargs)
        self.participant = participant
        self.count_type = test_type.count_type
        if self.count_type == self.COUNT_FROM_PARTICIPANT:
            self._expected_args = {'participants': self.participant, 'targets': test_type.participant}
        elif self.count_type == self.COUNT_EXPLICIT:
            self._expected_args = {'participants': self.participant}
            self._count = test_type.count
        elif self.count_type == self.COUNT_ACTUAL_SIZE:
            self._expected_args = {'participants': self.participant}
            self._count = test_type.count

    def get_expected_args(self):
        return self._expected_args

    @cached_test
    def __call__(self, participants={}, targets={}):
        for participant in participants:
            if not participant.is_sim:
                return TestResult(False, 'Participant {} is not a sim.', participant, tooltip=self.tooltip)
            if self.count_type == self.COUNT_FROM_PARTICIPANT:
                if not targets:
                    return TestResult(False, 'No targets found for HouseholdSizeTest when it requires them.', tooltip=self.tooltip)
                while True:
                    for target in targets:
                        if not target.is_sim:
                            return TestResult(False, 'Target {} is not a sim.', target, tooltip=self.tooltip)
                        while not participant.household.can_add_sim_info(target):
                            return TestResult(False, 'Cannot add {} to {}', target, participant.household, tooltip=self.tooltip)
                    if self.count_type == self.COUNT_EXPLICIT:
                        free_slot_count = participant.household.free_slot_count
                        if not self._count.compare(free_slot_count):
                            return TestResult(False, "Household doesn't meet free slot count requirement.", tooltip=self.tooltip)
                            while self.count_type == self.COUNT_ACTUAL_SIZE:
                                household_size = participant.household.household_size
                                if not self._count.compare(household_size):
                                    return TestResult(False, "Household doesn't meet size requirements.", tooltip=self.tooltip)
                    else:
                        while self.count_type == self.COUNT_ACTUAL_SIZE:
                            household_size = participant.household.household_size
                            if not self._count.compare(household_size):
                                return TestResult(False, "Household doesn't meet size requirements.", tooltip=self.tooltip)
            elif self.count_type == self.COUNT_EXPLICIT:
                free_slot_count = participant.household.free_slot_count
                if not self._count.compare(free_slot_count):
                    return TestResult(False, "Household doesn't meet free slot count requirement.", tooltip=self.tooltip)
                    while self.count_type == self.COUNT_ACTUAL_SIZE:
                        household_size = participant.household.household_size
                        if not self._count.compare(household_size):
                            return TestResult(False, "Household doesn't meet size requirements.", tooltip=self.tooltip)
            else:
                while self.count_type == self.COUNT_ACTUAL_SIZE:
                    household_size = participant.household.household_size
                    if not self._count.compare(household_size):
                        return TestResult(False, "Household doesn't meet size requirements.", tooltip=self.tooltip)
        return TestResult.TRUE

class GenealogyRelationType(enum.Int):
    __qualname__ = 'GenealogyRelationType'
    NONE = 0
    ALL = 1
    PARENTS = 2

class GenealogyTest(event_testing.test_base.BaseTest, HasTunableSingletonFactory):
    __qualname__ = 'GenealogyTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': '\n            Require the test participant has certain genealogy relationship to\n            the target participant.\n            ', 'subject': TunableEnumEntry(description='\n            The subject who requires to have the genealogy relationship with\n            the target participant. e.g, if PARENTS is selected, then the\n            subject_sim must be a parent of the target_sim.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'target_sim': TunableEnumEntry(description='\n            The target sim to test the relationship against.\n            ', tunable_type=ParticipantType, default=ParticipantType.TargetSim), 'required_relationship': TunableEnumEntry(description='\n            The genealogy relationship required from test_participant to\n            target_participant.\n            ', tunable_type=GenealogyRelationType, default=GenealogyRelationType.ALL)}

    def __init__(self, subject, target_sim, required_relationship, **kwargs):
        super().__init__(**kwargs)
        self.subject = subject
        self.target_sim = target_sim
        self.required_relationship = required_relationship

    def get_expected_args(self):
        return {'source_participants': self.subject, 'target_participants': self.target_sim}

    def _get_required_ids(self, sim_info):
        genealogy = sim_info.genealogy
        match_ids = []
        if self.required_relationship == GenealogyRelationType.ALL or self.required_relationship == GenealogyRelationType.NONE:
            match_ids = genealogy.get_family_sim_ids()
        elif self.required_relationship == GenealogyRelationType.PARENTS:
            match_ids = list(genealogy.get_parent_sim_ids_gen())
        return match_ids

    @cached_test
    def __call__(self, source_participants=(), target_participants=()):
        for source_participant in source_participants:
            if not source_participant.is_sim:
                return TestResult(False, 'Source Participant {} is not a sim.', source_participant, tooltip=self.tooltip)
            for target_participant in target_participants:
                target_participant_info = None
                if not target_participant.is_sim:
                    target_participant_info = getattr(target_participant, 'sim_info', None)
                    if target_participant_info is None:
                        return TestResult(False, 'Target Participant {} is not a sim.', target_participant, tooltip=self.tooltip)
                error_message = "Genealogy test fail, {} is not {}'s {}".format(source_participant, target_participant, self.required_relationship)
                match_ids = self._get_required_ids(target_participant_info or target_participant)
                if self.required_relationship == GenealogyRelationType.NONE:
                    if source_participant.sim_id in match_ids:
                        return TestResult(False, error_message, tooltip=self.tooltip)
                        while source_participant.sim_id not in match_ids:
                            return TestResult(False, error_message, tooltip=self.tooltip)
                else:
                    while source_participant.sim_id not in match_ids:
                        return TestResult(False, error_message, tooltip=self.tooltip)
        return TestResult.TRUE

class ObjectRelationshipTest(event_testing.test_base.BaseTest):
    __qualname__ = 'ObjectRelationshipTest'
    FACTORY_TUNABLES = {'description': '\n            Test relationships between a specific Sim and a specific object.\n            The target object(s) must have an ObjectRelationshipComponent attached\n            to them for this test to be valid.\n            ', 'sims': TunableEnumEntry(description='\n            The Sim(s) to test.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'targets': TunableEnumEntry(description='\n            The object(s) to test.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'relationship_status': TunableVariant(description="\n            Whether the object cannot have a relationship with the sim, or the\n            sim and object's relationship value is within a tuned range.\n            \n            For test on relationship range:\n            If a sim does not have a relationship with the object and\n            use_default_value_if_no_relationship is checked, the relationship \n            value used will be the initial value of the relationship statistic\n            used to track relationships on the object. If sim doesn't have a\n            relationship and use_default_value_if_no_relationship is NOT checked,\n            the test will fail (so you can use that to check if a relationship\n            exists).\n            ", relationship_range=TunableTuple(use_default_value_if_no_relationship=Tunable(description="\n                    If checked, the initial value of the relationship stat will\n                    be used if the sim and object do not already have a\n                    relationship. If unchecked, the test will fail if the sim\n                    and object don't have a relationship.\n                    ", tunable_type=bool, default=False), value_interval=TunableInterval(tunable_type=float, default_lower=-100, default_upper=100)), locked_args={'no_relationship_exists': None}, default='relationship_range'), 'can_add_relationship': OptionalTunable(Tunable(description='\n            If checked, this object must be able to add a new relationship.  If\n            unchecked, this object must not be able to add any more\n            relationships.\n            ', tunable_type=bool, default=True))}

    def __init__(self, sims, targets, can_add_relationship, relationship_status, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.sims = sims
        self.targets = targets
        self.can_add_relationship = can_add_relationship
        self.relationship_status = relationship_status

    def get_expected_args(self):
        return {'sims': self.sims, 'targets': self.targets}

    @cached_test
    def __call__(self, sims, targets):
        for sim in sims:
            for target in targets:
                relationship_component = target.objectrelationship_component
                if relationship_component is None:
                    return TestResult(False, 'Target {} has no object relationship component attached.', target)
                has_relationship = relationship_component.has_relationship(sim.id)
                if self.relationship_status is None:
                    if has_relationship:
                        return TestResult(False, 'Target {} has a relationship with Sim {} but is required not to.', target, sim)
                else:
                    if not self.relationship_status.use_default_value_if_no_relationship and not has_relationship:
                        return TestResult(False, 'Target {} does not have a relationship with Sim {} and test does not allow default values.', target, sim)
                    relationship_value = relationship_component.get_relationship_value(sim.id)
                    if relationship_value < self.relationship_status.value_interval.lower_bound or relationship_value > self.relationship_status.value_interval.upper_bound:
                        return TestResult(False, "Target {}'s relationship with Sim {} is {}, which is not within range [{}, {}]", target, sim, relationship_value, self.relationship_status.value_interval.upper_bound, self.relationship_status.value_interval.lower_bound)
                while self.can_add_relationship is not None and self.can_add_relationship != relationship_component._can_add_new_relationship:
                    return TestResult(False, "Target {}'s ability to add new relationships is {} but the requirement is {} .", target, relationship_component._can_add_new_relationship, self.can_add_relationship)
        return TestResult.TRUE

TunableObjectRelationshipTest = TunableSingletonFactory.create_auto_factory(ObjectRelationshipTest)

class CustomNameTest(event_testing.test_base.BaseTest, HasTunableSingletonFactory):
    __qualname__ = 'CustomNameTest'
    FACTORY_TUNABLES = {'description': 'Require or prohibit an object from having a custom name or description set.', 'participant': TunableEnumEntry(ParticipantType, ParticipantType.Object, description='The subject who is the object of this test.'), 'has_custom_name': OptionalTunable(Tunable(bool, True, description='If checked, the subject must have a custom name set. If unchecked, it cannot have a custom name set.'), description='Use to specify whether or not to require or prohibit a custom name.'), 'has_custom_description': OptionalTunable(Tunable(bool, True, description='If checked, the subject must have a custom description set. If unchecked, it cannot have a custom description set.'), description='Use to specify whether or not to required or prohibit a custom description')}

    def __init__(self, participant, has_custom_name, has_custom_description, **kwargs):
        super().__init__(**kwargs)
        self.participant = participant
        self.has_custom_name = has_custom_name
        self.has_custom_description = has_custom_description

    def get_expected_args(self):
        return {'targets': self.participant}

    @cached_test
    def __call__(self, targets=()):
        for target in targets:
            if target.is_sim:
                if target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                    return TestResult(False, 'Target is not an instanced sim {}.', target, tooltip=self.tooltip)
                target = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            if self.has_custom_name is not None and target.has_custom_name() != self.has_custom_name:
                return TestResult(False, "Target's custom name fails requirements.", tooltip=self.tooltip)
            while self.has_custom_description is not None:
                if target.has_custom_description() != self.has_custom_description:
                    return TestResult(False, "Target's custom description fails requirements.", tooltip=self.tooltip)
        return TestResult.TRUE

class GenderPreferenceTest(event_testing.test_base.BaseTest):
    __qualname__ = 'GenderPreferenceTest'
    GENDER_PREFERNCE_THRESHOLD = TunableThreshold(description='\n        The threshold in which this sim will consider having an appropriate\n        gender preference.\n        ')
    FACTORY_TUNABLES = {'description': '\n            Test to see if two sims have a compatible gender preference.\n            ', 'subject': TunableEnumFlags(ParticipantType, ParticipantType.Actor, description='The subject(s) checking this the gender preference.'), 'target_sim': TunableEnumFlags(ParticipantType, ParticipantType.TargetSim, description='Target(s) of the relationship(s)')}

    def __init__(self, subject, target_sim, ignore_reciprocal=False, **kwargs):
        super().__init__(**kwargs)
        self._subject = subject
        self._target_sim = target_sim
        self._ignore_reciprocal = ignore_reciprocal

    def get_expected_args(self):
        return {'subject_participants': self._subject, 'target_participants': self._target_sim}

    @cached_test
    def __call__(self, subject_participants=None, target_participants=None):
        for subject_participant in subject_participants:
            if not subject_participant.is_sim:
                return TestResult(False, 'GenderPreferenceTest: subject {} is not a sim.', subject_participant, tooltip=self.tooltip)
            for target_participant in target_participants:
                if not target_participant.is_sim:
                    return TestResult(False, 'GenderPreferenceTest: target {} is not a sim.', target_participant, tooltip=self.tooltip)
                if not GenderPreferenceTest.GENDER_PREFERNCE_THRESHOLD.compare(subject_participant.get_gender_preference(target_participant.gender).get_value()):
                    return TestResult(False, "GenderPreferenceTest: subject {} doesn't have proper gender preference to target {}", subject_participant, target_participant, tooltip=self.tooltip)
                if not (self._ignore_reciprocal or GenderPreferenceTest.GENDER_PREFERNCE_THRESHOLD.compare(target_participant.get_gender_preference(subject_participant.gender).get_value())):
                    return TestResult(False, "GenderPreferenceTest: target {} doesn't have proper gender preference to subject {}", target_participant, subject_participant, tooltip=self.tooltip)

TunableGenderPreferencetTest = TunableSingletonFactory.create_auto_factory(GenderPreferenceTest)

class InUseTest(AutoFactoryInit, HasTunableSingletonFactory, event_testing.test_base.BaseTest):
    __qualname__ = 'InUseTest'

    class Candidates(enum.Int):
        __qualname__ = 'InUseTest.Candidates'
        NON_ACTORS = 0
        NON_ACTOR_HOUSEHOLD_MEMBERS = 1
        NON_ACTOR_NON_HOUSEHOLD_MEMBERS = 2
        PICKED_SIM = 3

    FACTORY_TUNABLES = {'description': 'Test for whether any of the tuned targets are in use.', 'targets': TunableEnumFlags(description='\n            Targets to check whether in use.\n            ', enum_type=ParticipantType, default=ParticipantType.Object), 'negate': Tunable(description='\n            If unchecked, this test will pass when the object is in use.\n            If checked, this test will pass when the object is not in use.\n            ', tunable_type=bool, default=False), 'candidates': TunableEnumEntry(description='\n            Which sims will be considered users of the target.\n            ', tunable_type=Candidates, default=Candidates.NON_ACTORS)}

    def get_expected_args(self):
        return {'actors': ParticipantType.Actor, 'targets': self.targets, 'picked_sim': ParticipantType.PickedSim}

    @cached_test
    def __call__(self, actors=None, targets=None, picked_sim=None):
        for target in targets:
            if target.is_part:
                target = target.part_owner
            all_users = target.get_users()
            sim_users = target.get_users(sims_only=True)
            if self.candidates == self.Candidates.PICKED_SIM:
                has_users = any(sim.sim_info in picked_sim for sim in sim_users)
            elif len(all_users) > len(sim_users):
                has_users = True
            elif self.candidates == self.Candidates.NON_ACTORS:
                has_users = any(sim.sim_info not in actors for sim in sim_users)
            else:
                for sim in sim_users:
                    if sim.sim_info in actors:
                        pass
                    is_in_household = any(actor.household is sim.household for actor in actors)
                    should_be_in_household = self.candidates == self.Candidates.NON_ACTOR_HOUSEHOLD_MEMBERS
                    while is_in_household == should_be_in_household:
                        has_users = True
                        break
                has_users = False
            while has_users ^ self.negate:
                return TestResult.TRUE
        return TestResult(False, 'Failed in_use test because object {} in use', 'is' if self.negate else "isn't", tooltip=self.tooltip)

class HasFreePartTest(AutoFactoryInit, HasTunableSingletonFactory, event_testing.test_base.BaseTest):
    __qualname__ = 'HasFreePartTest'
    FACTORY_TUNABLES = {'description': '\n            Check that the there is a part free/in use of the particular\n            tuned definition\n            ', 'targets': TunableEnumEntry(description='\n            Who or what to apply this test to.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'part_definition': TunableReference(description='\n            The part definition to check against.\n            ', manager=services.object_part_manager())}

    def get_expected_args(self):
        return {'actor': ParticipantType.Actor, 'targets': self.targets}

    def _base_tests(self, target):
        test_result = TestResult.TRUE
        target_parts = None
        if target is None:
            logger.error('Trying to call HasPartFreeTest on {} which is None', target)
            test_result = TestResult(False, 'Target({}) does not exist', self.targets)
            return (test_result, target_parts)
        if target.is_part:
            target = target.part_owner
        target_parts = target.parts
        if target_parts is None:
            logger.warn('Trying to call HasPartFreeTest on {} which has no parts. This is a tuning error.', target)
            test_result = TestResult(False, 'Failed has_part_free test because object has no parts at all', tooltip=self.tooltip)
        return (test_result, target_parts)

    @cached_test
    def __call__(self, actor=None, targets=None):
        if actor is None:
            logger.error('Trying to call HasPartFreeTest with no actor.', actor)
            return TestResult(False, 'Actor does not exist for the HasPartFreeTest')
        sim_info = next(iter(actor), None)
        sim = sim_info.get_sim_instance()
        for target in targets:
            (test_result, target_parts) = self._base_tests(target)
            while test_result:
                if not any(part.may_reserve(sim) for part in target_parts if part.part_definition is self.part_definition):
                    return TestResult(False, 'Failed has_part_free test because object has no free parts of the tuned definition', tooltip=self.tooltip)
                return TestResult.TRUE
        return test_result

class HasParentObjectTest(AutoFactoryInit, HasTunableSingletonFactory, event_testing.test_base.BaseTest):
    __qualname__ = 'HasParentObjectTest'
    FACTORY_TUNABLES = {'description': '\n            Check that the if the target has a parent object\n            ', 'targets': TunableEnumEntry(description='\n            Who or what to apply this test to.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'negate': Tunable(description="\n            If set to True, the test will pass if targets DON'T have parent.\n            ", tunable_type=bool, default=False)}

    def get_expected_args(self):
        return {'targets': self.targets}

    @cached_test
    def __call__(self, targets=None):
        for target in targets:
            if self.negate:
                if target.parent is not None:
                    return TestResult(False, 'Parent test fail because object {} has parent'.format(target), tooltip=self.tooltip)
                    while target.parent is None:
                        return TestResult(False, "Parent test fail because object {} doesn't have parent".format(target), tooltip=self.tooltip)
            else:
                while target.parent is None:
                    return TestResult(False, "Parent test fail because object {} doesn't have parent".format(target), tooltip=self.tooltip)
        return TestResult.TRUE

class HasInUsePartTest(HasFreePartTest):
    __qualname__ = 'HasInUsePartTest'

    @cached_test
    def __call__(self, actor=None, targets=None):
        for target in targets:
            (test_result, target_parts) = self._base_tests(target)
            while test_result:
                if not any(part.in_use for part in target_parts if part.part_definition is self.part_definition):
                    test_result = TestResult(False, 'Failed has_part_in_use test because object has no parts in use of the tuned definition', tooltip=self.tooltip)
                else:
                    return TestResult.TRUE
        return test_result

class SimPermissionTest(event_testing.test_base.BaseTest):
    __qualname__ = 'SimPermissionTest'
    test_events = ()

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'who': TunableEnumEntry(participant_type_enum, participant_type_default, description='Who or what to apply this test to')}

    FACTORY_TUNABLES = {'description': "Gate availability from a Sim's permission settings.", 'who': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), 'permission': TunableEnumEntry(server.permissions.SimPermissions.Settings, server.permissions.SimPermissions.Settings.VisitationAllowed, description='The Sim Permission being tested'), 'require_enabled': Tunable(bool, True, description='If True, the chosen Sim Permission must be enabled for the test to pass.  If False, the Sim Permission must be disabled to pass.')}

    def __init__(self, who, permission, require_enabled, **kwargs):
        super().__init__(safe_to_skip=True, **kwargs)
        self.who = who
        self.permission = permission
        self.require_enabled = require_enabled

    def get_expected_args(self):
        return {'test_targets': self.who}

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            if target is None:
                logger.error('Trying to call SimPermissionTest on {} which is None', target)
                return TestResult(False, 'Target({}) does not exist', self.who)
            if target.sim_permissions.is_permission_enabled(self.permission) and not self.require_enabled:
                return TestResult(False, "Sim Permission Test: Sim doesn't not have specified permission disabled.", tooltip=self.tooltip)
            while not target.sim_permissions.is_permission_enabled(self.permission) and self.require_enabled:
                return TestResult(False, "Sim Permission Test: Sim doesn't not have specified permission enabled.", tooltip=self.tooltip)
        return TestResult.TRUE

TunableSimPermissionTest = TunableSingletonFactory.create_auto_factory(SimPermissionTest)

class IsCarryingObjectTest(event_testing.test_base.BaseTest):
    __qualname__ = 'IsCarryingObjectTest'
    FACTORY_TUNABLES = {'description': "Require the participant to be carrying the specified object.  For example, this is being used currently to /only allow a Sim to run the wash dishes interaction if they're currently carrying the dirty dish stack object.", 'participant': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='The subject of this test.'), 'object_type': TunableReference(services.definition_manager(), description='A type of object required to be carried.')}

    def __init__(self, participant, object_type, **kwargs):
        super().__init__(**kwargs)
        self.participant = participant
        self.object_type = object_type

    def get_expected_args(self):
        return {'test_targets': self.participant}

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            if target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                return TestResult(False, 'IsCarryingObjectTest: {} is not an instanced sim.', target, tooltip=self.tooltip)
            sim = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            while not sim.posture_state.is_carrying(self.object_type):
                return TestResult(False, 'IsCarryingObjectTest: {} is not carrying {}.', sim.full_name, self.object_type.cls.__name__, tooltip=self.tooltip)
        return TestResult.TRUE

TunableIsCarryingObjectTest = TunableSingletonFactory.create_auto_factory(IsCarryingObjectTest)

class ServiceNpcHiredTest(event_testing.test_base.BaseTest):
    __qualname__ = 'ServiceNpcHiredTest'
    FACTORY_TUNABLES = {'description': "Tests on the state of service npc requests of the participant's household. EX whether a maid was requested or has been cancelled", 'participant': TunableEnumEntry(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor, description="The subject of this test. We will use the subject's household to test if the household has requested a service"), 'service': TunableReference(services.service_npc_manager(), description='The service tuning to perform the test against'), 'hired': Tunable(bool, True, description="Whether to test if service is hired or not hired. EX: If True, we test that you have hired the tuned service. If False, we test that you don't have the service hired.")}

    def __init__(self, participant, service, hired, **kwargs):
        super().__init__(**kwargs)
        self.participant = participant
        self.service = service
        self.hired = hired

    def get_expected_args(self):
        return {'test_targets': self.participant}

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            if not target.is_sim:
                return TestResult(False, '{} is not a sim.', target, tooltip=self.tooltip)
            household = target.household
            service_record = household.get_service_npc_record(self.service.guid64, add_if_no_record=False)
            if self.hired:
                if service_record is None or not service_record.hired:
                    return TestResult(False, '{} has not hired service {}.', household, self.service, tooltip=self.tooltip)
                    while service_record is not None and service_record.hired:
                        return TestResult(False, '{} has already hired service {}.', household, self.service, tooltip=self.tooltip)
            else:
                while service_record is not None and service_record.hired:
                    return TestResult(False, '{} has already hired service {}.', household, self.service, tooltip=self.tooltip)
        return TestResult.TRUE

TunableServiceNpcHiredTest = TunableSingletonFactory.create_auto_factory(ServiceNpcHiredTest)

class CreateObjectTest(event_testing.test_base.BaseTest):
    __qualname__ = 'CreateObjectTest'
    FACTORY_TUNABLES = {'description': 'Enforce the firecode (object limit) for zone and household objects. This SHOULD be used on interactions that would create non-disposable objects (i.e. painting, buying objects, rewards, gifts)', 'participant': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='The subject of this situation data test.')}

    def __init__(self, participant, **kwargs):
        super().__init__(**kwargs)
        self.participant = participant

    def get_expected_args(self):
        return {'test_targets': self.participant}

    @cached_test
    def __call__(self, test_targets=None):
        if test_targets is None:
            return TestResult(False, 'CreateObjectTest: There are no test targets')
        for target in test_targets:
            if not target.is_sim:
                return TestResult(False, 'CreateObjectTest: {} is not a sim.', target, tooltip=self.tooltip)
            household_id = target.household_id
            zone_id = sims4.zone_utils.get_zone_id(can_be_none=True)
            if not build_buy.can_create_object(zone_id, household_id, 1):
                return TestResult(False, 'CreateObjectTest: Zone or Household object limit reached.', tooltip=self.tooltip)

TunableCreateObjectTest = TunableSingletonFactory.create_auto_factory(CreateObjectTest)

class FilterTest(event_testing.test_base.BaseTest):
    __qualname__ = 'FilterTest'
    FACTORY_TUNABLES = {'description': '\n            Test to see if a sim matches a tuned filter.\n            ', 'filter_target': OptionalTunable(tunable=TunableEnumEntry(description='\n                The sim that will have the filter checked against.\n                ', tunable_type=ParticipantType, default=ParticipantType.TargetSim), enabled_by_default=True), 'relative_sim': TunableEnumEntry(description='\n                The sim that will be the relative sim that the filter will\n                check against for relative checks such as relationships or\n                household ids.\n                ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'sim_filter': TunableReference(manager=services.get_instance_manager(sims4.resources.Types.SIM_FILTER)), 'duration_available': TunableSimMinute(description='\n                The duration from now that will be used for the start\n                and end time of the filter request.\n                ', default=120, minimum=0)}

    def __init__(self, filter_target, relative_sim, sim_filter, duration_available, **kwargs):
        super().__init__(**kwargs)
        self.filter_target = filter_target
        self.relative_sim = relative_sim
        self._sim_filter = sim_filter
        self._duration_available = clock.interval_in_sim_minutes(duration_available)

    def get_expected_args(self):
        expected_args = {}
        if self.filter_target is not None:
            expected_args['filter_targets'] = self.filter_target
        expected_args['relative_sims'] = self.relative_sim
        return expected_args

    @cached_test
    def __call__(self, filter_targets=None, relative_sims=None):
        if not relative_sims:
            clients = [client for client in services.client_manager().values()]
            if not clients:
                return TestResult(False, 'FilterTest: No clients found when trying to get the active sim.', tooltip=self.tooltip)
            client = clients[0]
            relative_sim = client.active_sim
            if not relative_sim:
                return TestResult(False, 'FilterTest: No active sim found.', tooltip=self.tooltip)
            relative_sims = {relative_sim.sim_info}
        if filter_targets is not None:
            for filter_target in filter_targets:
                for relative_sim_info in relative_sims:
                    while not services.sim_filter_service().does_sim_match_filter(filter_target.id, sim_filter=self._sim_filter, requesting_sim_info=relative_sim_info, household_id=relative_sim_info.household_id):
                        return TestResult(False, 'FilterTest: Sim {} (id {}) does not match filter {}.', filter_target.full_name, filter_target.id, self._sim_filter.__name__, tooltip=self.tooltip)
        else:
            for relative_sim_info in relative_sims:
                while not services.sim_filter_service().submit_filter(self._sim_filter, None, requesting_sim_info=relative_sim_info, allow_yielding=False, start_time=services.time_service().sim_now, end_time=services.time_service().sim_now + self._duration_available, household_id=relative_sim_info.household_id):
                    return TestResult(False, 'Sim Filter returned no results.', tooltip=self.tooltip)
        return TestResult.TRUE

TunableFilterTest = TunableSingletonFactory.create_auto_factory(FilterTest)

class _AppropriatenessTestBase(event_testing.test_base.BaseTest):
    __qualname__ = '_AppropriatenessTestBase'
    FACTORY_TUNABLES = {'description': "Test to see if a sim's set of role states allows them perform this interaction.", 'participant': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='The subject of this situation data test.')}

    def __init__(self, participant, is_appropriate, **kwargs):
        super().__init__(**kwargs)
        self._participant = participant
        self._is_appropriate = is_appropriate

    def get_expected_args(self):
        return {'test_targets': self._participant, 'affordance': ParticipantType.Affordance}

    @cached_test
    def __call__(self, test_targets=None, affordance=None):
        if not test_targets:
            return TestResult(False, 'AppropriatenessTest: There are no participants.', tooltip=self.tooltip)
        if not affordance:
            return TestResult(False, 'AppropriatenessTest: There is no affordance.', tooltip=self.tooltip)
        for target in test_targets:
            if target.is_sim:
                if target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                    return TestResult(False, 'AppropriatenessTest: {} is not an instantiated sim.', target, tooltip=self.tooltip)
                target = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            while target.Buffs.is_appropriate(affordance.appropriateness_tags) != self._is_appropriate:
                return TestResult(False, 'AppropriatenessTest: This interaction is not appropriate for Sim of id {}. appropriateness tags {}.', target.id, affordance.appropriateness_tags, tooltip=self.tooltip)
        return TestResult.TRUE

class AppropriatenessTest(_AppropriatenessTestBase):
    __qualname__ = 'AppropriatenessTest'

    def __init__(self, *args, **kwargs):
        super().__init__(is_appropriate=True, *args, **kwargs)

class InappropriatenessTest(_AppropriatenessTestBase):
    __qualname__ = 'InappropriatenessTest'

    def __init__(self, *args, **kwargs):
        super().__init__(is_appropriate=False, *args, **kwargs)

TunableAppropriatenessTest = TunableSingletonFactory.create_auto_factory(AppropriatenessTest)
TunableInappropriatenessTest = TunableSingletonFactory.create_auto_factory(InappropriatenessTest)

class UserRunningInteractionTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'UserRunningInteractionTest'
    FACTORY_TUNABLES = {'description': '\n            A test that verifies if any of the users of the selected participant are\n            running a specific interaction.\n            ', 'participant': TunableEnumEntry(description='\n            The participant of the interaction used to fetch the users against\n            which the test is run.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'affordances': TunableList(TunableReference(description='\n            If any of the participants are running any of these affordances,\n            this test will pass.\n            ', manager=services.affordance_manager(), class_restrictions='SuperInteraction')), 'affordance_lists': TunableList(description='\n            If any of the participants are running any of the affordances in\n            these lists, this test will pass.\n            ', tunable=snippets.TunableAffordanceListReference()), 'test_for_not_running': Tunable(description='\n            Changes this test to check for the opposite case, as in verifying that this interaction is not running.', tunable_type=bool, default=False)}

    def get_expected_args(self):
        return {'test_targets': self.participant}

    @cached_test
    def __call__(self, test_targets=()):
        all_affordances = set(self.affordances)
        for affordance_list in self.affordance_lists:
            all_affordances.update(affordance_list)
        interaction_is_running = False
        for target in test_targets:
            if target.is_sim:
                if target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                    return TestResult(False, '{} is not an instanced object', target, tooltip=self.tooltip)
                target = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
                for si in target.si_state:
                    while si.get_interaction_type() in all_affordances:
                        interaction_is_running = True
            if target.is_part:
                target = target.part_owner
            for user in target.get_users(sims_only=True):
                for si in user.si_state:
                    while si.get_interaction_type() in all_affordances:
                        interaction_is_running = True
        if self.test_for_not_running:
            if interaction_is_running:
                return TestResult(False, 'User is running one of {}', all_affordances, tooltip=self.tooltip)
            return TestResult.TRUE
        if interaction_is_running:
            return TestResult.TRUE
        return TestResult(False, 'No user found running one of {}', all_affordances, tooltip=self.tooltip)

class AchievementEarnedFactory(TunableFactory):
    __qualname__ = 'AchievementEarnedFactory'

    @staticmethod
    def factory(sim, tooltip, unlocked, achievement):
        if achievement is None:
            if hasattr(unlocked, 'aspiration_type'):
                return TestResult(False, 'UnlockedTest: non-achievement object {} passed to AspirationEarnedFactory.', unlocked, tooltip=tooltip)
            return TestResult.TRUE
        if sim.account.achievement_tracker.milestone_completed(achievement.guid64):
            return TestResult.TRUE
        return TestResult(False, 'UnlockedTest: Sim has not unlocked achievement {}.', achievement, tooltip=tooltip)

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(description='\n            This option tests for completion of a tuned Achievement.\n            ', achievement=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.ACHIEVEMENT)), **kwargs)

class AspirationEarnedFactory(TunableFactory):
    __qualname__ = 'AspirationEarnedFactory'

    @staticmethod
    def factory(sim_info, tooltip, unlocked, aspiration):
        if aspiration is None:
            aspiration_type_fn = getattr(unlocked, 'aspiration_type', None)
            if aspiration_type_fn is None:
                return TestResult(False, 'UnlockedTest: non-aspiration object {} passed to AspirationEarnedFactory.', unlocked, tooltip=tooltip)
            aspiration_type = aspiration_type_fn()
            if aspiration_type != AspriationType.FULL_ASPIRATION:
                return TestResult(False, "UnlockedTest: aspiration object {} passed in isn't of type FULL_ASPIRATION.", unlocked, tooltip=tooltip)
            return TestResult.TRUE
        if sim_info.aspiration_tracker.milestone_completed(aspiration.guid64):
            return TestResult.TRUE
        return TestResult(False, 'UnlockedTest: Sim has not unlocked aspiration {}.', aspiration, tooltip=tooltip)

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(description='\n            This option tests for completion of a tuned Aspiration.\n            ', aspiration=TunableReference(description='\n                If this aspiration is completed, the test will pass.\n                ', manager=services.get_instance_manager(sims4.resources.Types.ASPIRATION)), **kwargs)

class UnlockedTest(event_testing.test_base.BaseTest):
    __qualname__ = 'UnlockedTest'
    test_events = (TestEvent.UnlockEvent,)
    USES_EVENT_DATA = True

    @TunableFactory.factory_option
    def unlock_type_override(allow_achievment=True):
        kwargs = {}
        default = 'aspiration'
        kwargs['aspiration'] = AspirationEarnedFactory()
        if allow_achievment:
            default = 'achievement'
            kwargs['achievement'] = AchievementEarnedFactory()
        return {'unlock_to_test': TunableVariant(description='\n            The unlocked aspiration, career, or achievement want to test for.\n            ', default=default, **kwargs), 'participant': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='The subject of this test.')}

    def __init__(self, *, unlock_to_test, participant, **kwargs):
        super().__init__(**kwargs)
        self.unlock_to_test = unlock_to_test
        self.participant = participant

    def get_expected_args(self):
        return {'sims': self.participant, 'unlocked': event_testing.test_events.FROM_EVENT_DATA}

    @cached_test
    def __call__(self, sims=None, unlocked=None):
        for sim in sims:
            pass

TunableUnlockedTest = TunableSingletonFactory.create_auto_factory(UnlockedTest)

class CommodityAdvertisedTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'CommodityAdvertisedTest'
    REQUIRE_ANY = 0
    REQUIRE_ALL = 1
    REQUIRE_NONE = 2
    FACTORY_TUNABLES = {'description': '\n            Require the current lot to have some interaction advertising the\n            specified commodities.\n            \n            example: You might not want the interaction to clean dishes to show\n            up if there are no sinks around.  The "wash dishes" interaction on\n            sinks advertises a "Wash_Dishes" static commodity, so we can get\n            this behavior by having the "Clean Up" interaction on dishes test\n            out if that static commodity is not being advertised.\n            ', 'commodities': TunableSet(description='\n            A list of commodities that must be advertised by some interaction\n            on the current lot.\n            ', tunable=TunableReference(description='\n                The type of commodity to search for.\n                ', manager=services.statistic_manager())), 'static_commodities': TunableSet(description='\n            A list of static commodities that must be advertised by some\n            interaction on the current lot.\n            ', tunable=TunableReference(description='\n                The type of static commodity to search for.\n                ', manager=services.static_commodity_manager())), 'requirements': TunableVariant(description='\n            A variant specifying the terms of this test with regards to the\n            tuned commodities.\n            \n            * Require Any: The test will pass if any of the tuned commodities are\n            found.\n            * Require All: The test will only pass if all of the tuned\n            commodities are found.\n            * Require None: The test will only pass if none of the tuned\n            commodities are found.\n            ', locked_args={'require_any': REQUIRE_ANY, 'require_all': REQUIRE_ALL, 'require_none': REQUIRE_NONE}, default='require_any'), 'require_reservable_by_participant': OptionalTunable(description='\n            If enabled, the object that advertises the commodity must by reservable\n            by the specified participant type.\n            ', tunable=TunableEnumEntry(description='\n                The participant that must be able to reserve the object.\n                ', tunable_type=ParticipantType, default=ParticipantType.Actor)), 'test_aops': Tunable(description='\n            If checked, the obj that is advertising the tuned commodities must\n            also have the aops that grant that commodity be able to run.\n            \n            EX: check if any dishes on the lot can be eaten. Even if the\n            dishes advertise the eat static commodity, the individual dish themselves might\n            not be able to be eaten because they are spoiled, empty, etc.\n            ', tunable_type=bool, default=False)}

    def get_expected_args(self):
        expected_args = {'target_objects': ParticipantType.Object, 'context': ParticipantType.InteractionContext, 'actor_set': ParticipantType.Actor}
        if self.require_reservable_by_participant is not None:
            expected_args['reserve_participants'] = self.require_reservable_by_participant
        return expected_args

    def _has_aop_that_passes_test(self, obj, motives, context):
        for aop in obj.potential_interactions(context):
            while aop.affordance.commodity_flags & motives:
                test_result = aop.test(context)
                if test_result:
                    return True
        return False

    @cached_test
    def __call__(self, target_objects=None, reserve_participants=None, context=None, actor_set=None):
        found_motives = set()
        motives = self.static_commodities.union(self.commodities)
        actor_info = next(iter(actor_set))
        actor = actor_info.get_sim_instance()
        if actor is None:
            return TestResult(False, 'The actor Sim is not instantiated.')
        autonomy_rule = actor.get_off_lot_autonomy_rule_type()
        off_lot_radius = actor.get_off_lot_autonomy_radius()
        reference_object = actor
        if target_objects:
            for obj in target_objects:
                if obj.is_sim:
                    sim_instance = obj.get_sim_instance()
                    if sim_instance is None:
                        pass
                    reference_object = sim_instance
                    break
                while not obj.is_in_inventory():
                    reference_object = obj
                    break
        reference_object_on_active_lot = reference_object.is_on_active_lot(tolerance=actor.get_off_lot_autonomy_tolerance())
        for obj in services.object_manager().valid_objects():
            if obj in target_objects:
                pass
            if not obj.commodity_flags & motives:
                pass
            if not actor.autonomy_component.get_autonomous_availability_of_object(obj, autonomy_rule, off_lot_radius, reference_object_on_active_lot, reference_object=reference_object):
                pass
            if reserve_participants is not None:
                for sim in reserve_participants:
                    while obj.may_reserve(sim):
                        break
            if self.test_aops and not self._has_aop_that_passes_test(obj, motives, context):
                pass
            if self.requirements == self.REQUIRE_NONE:
                return TestResult(False, 'A specified commodity was found, but we are requiring that no specified commodities are found.', tooltip=self.tooltip)
            if self.requirements == self.REQUIRE_ANY:
                return TestResult.TRUE
            found_motives.update(obj.commodity_flags.intersection(motives))
        if self.requirements == self.REQUIRE_NONE:
            return TestResult.TRUE
        if self.requirements == self.REQUIRE_ALL:
            if found_motives.symmetric_difference(motives):
                return TestResult(False, 'Not all of the required commodities and static commodities were found.', tooltip=self.tooltip)
            return TestResult.TRUE
        if reserve_participants is not None:
            return TestResult(False, 'No required commodities or static commodities are advertising where the object is reservable by participant type {}.', self.require_reservable_by_participant, tooltip=self.tooltip)
        return TestResult(False, 'No required commodities or static commodities are advertising.', tooltip=self.tooltip)

class CommodityDesiredByOtherSims(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'CommodityDesiredByOtherSims'
    FACTORY_TUNABLES = {'description': '\n            Tests to see if another Sim on the lot desires the particular \n            commodity.  For example, you can use this to test to see if any\n            Sim is hungry.\n            ', 'commodity': TunableTuple(commodity=TunableReference(description='\n                The type of commodity to test.\n                ', manager=services.statistic_manager()), threshold=TunableThreshold(description='\n                The threashold to test for.\n                ')), 'only_other_sims': Tunable(description='\n            If checked, the sim running this test is not counted.', tunable_type=bool, default=True), 'only_household_sims': Tunable(description='\n            If checked, only sims in the same household as the testing sim \n            are considered.', tunable_type=bool, default=True), 'count': Tunable(description='\n            The number of sims that must desire the commodity for this test\n            to pass.', tunable_type=int, default=1), 'invert': Tunable(description='\n            If checked, the test will be inverted.  In other words, the test \n            will fail if any sim desires the tuned commodity.', tunable_type=bool, default=False)}

    def get_expected_args(self):
        expected_args = {'context': ParticipantType.InteractionContext}
        return expected_args

    @cached_test
    def __call__(self, context=None):
        logger.assert_log(context is not None, 'Context is None in CommodityDesiredByOtherSims test.', owner='rez')
        total_passed = 0
        for sim in services.sim_info_manager().instanced_sims_gen():
            if self.only_other_sims and context is not None and context.sim is sim:
                pass
            if self.only_household_sims and context is not None and context.sim.household_id != sim.household_id:
                pass
            commodity_inst = sim.get_stat_instance(self.commodity.commodity)
            while commodity_inst is not None and self.commodity.threshold.compare(commodity_inst.get_value()):
                total_passed += 1
                if total_passed >= self.count:
                    if not self.invert:
                        return TestResult.TRUE
                    return TestResult(False, 'Too many sims desire this commodity.', tooltip=self.tooltip)
        if not self.invert:
            return TestResult(False, 'Not enough sims desire this commodity.', tooltip=self.tooltip)
        return TestResult.TRUE

class SocialContextTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'SocialContextTest'
    FACTORY_TUNABLES = {'participant': TunableEnumEntry(description='\n            The participant against which to test social context.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'target_subject': TunableEnumEntry(description="\n            The participant that must be included in participant's social group\n            in order for this test to rely solely on the participant's current\n            STC. If target_subject is not in any of participant's social groups,\n            then the STC test will only consider the prevailing STC between\n            participant and target_subject.\n            ", tunable_type=ParticipantType, default=ParticipantType.TargetSim), 'required_set': TunableSet(description="\n            A set of contexts that are required. If any context is specified,\n            the test will fail if the participant's social context is not one of\n            these entries.\n            ", tunable=relationships.relationship_bit.RelationshipBit.TunableReference()), 'prohibited_set': TunableSet(description="\n            A set of contexts that are prohibited. The test will fail if the\n            participant's social context is one of these entries.\n            ", tunable=relationships.relationship_bit.RelationshipBit.TunableReference())}

    @staticmethod
    @caches.cached
    def get_overall_short_term_context_bit(*sims):
        positive_stc_tracks = []
        negative_stc_tracks = []
        for (sim_a, sim_b) in itertools.combinations(sims, 2):
            stc_track = sim_a.relationship_tracker.get_relationship_prevailing_short_term_context_track(sim_b.id)
            while stc_track is not None:
                if stc_track.get_value() >= 0:
                    positive_stc_tracks.append(stc_track)
                else:
                    negative_stc_tracks.append(stc_track)
        prevailing_stc_tracks = negative_stc_tracks if len(negative_stc_tracks) >= len(positive_stc_tracks) else positive_stc_tracks
        if prevailing_stc_tracks:
            prevailing_stc_track = None
            prevailing_stc_magnitude = None
            for (_, group) in itertools.groupby(sorted(prevailing_stc_tracks, key=lambda stc_track: stc_track.stat_type.type_id()), key=lambda stc_track: stc_track.stat_type.type_id()):
                group = list(group)
                stc_magnitude = sum(stc_track.get_value() for stc_track in group)/len(group)
                while prevailing_stc_track is None or abs(stc_magnitude) > abs(prevailing_stc_magnitude):
                    prevailing_stc_magnitude = stc_magnitude
                    prevailing_stc_track = group[0].stat_type
            return prevailing_stc_track.get_bit_at_relationship_value(prevailing_stc_magnitude)
        sim = next(iter(sims), None)
        if sim is not None:
            return sim.relationship_tracker.get_default_short_term_context_bit()

    def get_expected_args(self):
        return {'subject': self.participant, 'target': self.target_subject}

    @cached_test
    def __call__(self, subject=(), target=()):
        subject = next(iter(subject), None)
        target = next(iter(target), None)
        if subject is None:
            return TestResult(False, '{} is not a valid participant', self.participant)
        if target is None:
            return TestResult(False, '{} is not a valid participant', self.target_subject)
        sim = subject.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if sim is None:
            return TestResult(False, '{} is non-instantiated', subject)
        target_sim = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if target_sim is None:
            return TestResult(False, '{} is non-instantiated', target)
        if sim.is_in_group_with(target_sim):
            social_context = sim.get_social_context()
        else:
            social_context = self.get_overall_short_term_context_bit(sim, target_sim)
        if self.required_set and social_context not in self.required_set:
            return TestResult(False, '{} for {} does not match required contexts', social_context, sim, tooltip=self.tooltip)
        if social_context in self.prohibited_set:
            return TestResult(False, '{} for {} is a prohibited context', social_context, sim, tooltip=self.tooltip)
        return TestResult.TRUE

class DayTimeTest(event_testing.test_base.BaseTest):
    __qualname__ = 'DayTimeTest'
    FACTORY_TUNABLES = {'description': '\n            Test to see if the current time falls within the tuned range\n            and/or is on a valid day.\n            ', 'days_available': OptionalTunable(scheduler.TunableDayAvailability()), 'time_range': OptionalTunable(TunableTuple(description='\n            The time the test is valid.  If days_available is tuned and the\n            time range spans across two days with the second day tuned as\n            unavailable, the test will pass for that day until time range is\n            invalid.  Example: Time range 20:00 - 4:00, Monday is valid,\n            Tuesday is invalid.  Tuesday at 2:00 the test passes.  Tuesday at\n            4:01 the test fails.\n            ', begin_time=tunable_time.TunableTimeOfDay(default_hour=0), duration=tunable_time.TunableTimeOfDay(default_hour=1)))}

    def __init__(self, days_available, time_range, **kwargs):
        super().__init__(**kwargs)
        self.days_available = days_available
        self.time_range = time_range
        self.weekly_schedule = set()
        if days_available and time_range:
            for day in days_available:
                while days_available[day]:
                    days_as_time_span = date_and_time.create_time_span(days=day)
                    start_time = self.time_range.begin_time + days_as_time_span
                    end_time = start_time + date_and_time.create_time_span(hours=self.time_range.duration.hour(), minutes=self.time_range.duration.minute())
                    self.weekly_schedule.add((start_time, end_time))

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self):
        current_time = services.time_service().sim_now
        if self.weekly_schedule:
            for times in self.weekly_schedule:
                while current_time.time_between_week_times(times[0], times[1]):
                    return TestResult.TRUE
            return TestResult(False, 'Day and Time Test: Current time and/or day is invalid.', tooltip=self.tooltip)
        if self.days_available is not None:
            day = current_time.day()
            if self.days_available[day]:
                return TestResult.TRUE
            return TestResult(False, 'Day and Time Test: {} is not a valid day.', tunable_time.Days(day), tooltip=self.tooltip)
        if self.time_range is not None:
            begin = self.time_range.begin_time
            end = begin + date_and_time.create_time_span(hours=self.time_range.duration.hour(), minutes=self.time_range.duration.minute())
            if current_time.time_between_day_times(begin, end):
                return TestResult.TRUE
        return TestResult(False, 'Day and Time Test: Current time outside of tuned time range of {} - {}.', begin, end, tooltip=self.tooltip)

TunableDayTimeTest = TunableSingletonFactory.create_auto_factory(DayTimeTest)

class SocialGroupTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'SocialGroupTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': "Require a Sim to be part of a specified social group type, and optionally if that group's size is within a tunable threshold.", 'subject': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='The subject of this social group test.'), 'social_group_type': TunableReference(services.get_instance_manager(sims4.resources.Types.SOCIAL_GROUP), description='The required social group type.'), 'threshold': OptionalTunable(TunableThreshold(description='Optional social group size threshold test.'))}

    def get_expected_args(self):
        return {'test_targets': self.subject}

    @cached_test
    def __call__(self, test_targets=None):
        for target in test_targets:
            if target is None:
                pass
            if target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is None:
                return TestResult(False, 'Social Group test failed: {} is not an instantiated sim.', target, tooltip=self.tooltip)
            target = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            for group in target.get_groups_for_sim_gen():
                while type(group) is self.social_group_type:
                    if self.threshold is not None:
                        group_size = group.get_active_sim_count()
                        if not self.threshold.compare(group_size):
                            return TestResult(False, 'Social Group test failed: group size not within threshold.', tooltip=self.tooltip)
                    return TestResult.TRUE
        return TestResult(False, "Social Group test failed: subject not part of a '{}' social group.", self.social_group_type, tooltip=self.tooltip)

class InteractionRestoredFromLoadTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'InteractionRestoredFromLoadTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': 'Test whether an interaction was pushed from load or from normal gameplay.', 'from_load': Tunable(description='\n            If checked, this test will pass if the interaction was restored from\n            save load (restored interactions are pushed behind the loading screen).\n            If not checked, this test will only pass if the interaction was pushed\n            during normal gameplay.\n            ', tunable_type=bool, default=False)}

    def get_expected_args(self):
        return {'context': ParticipantType.InteractionContext}

    @cached_test
    def __call__(self, context=None):
        if context is not None and context.restored_from_load != self.from_load:
            return TestResult(False, 'InteractionRestoredFromLoadTest failed. We wanted interaction restored from load to be {}.', self.from_load, tooltip=self.tooltip)
        return TestResult.TRUE

class KnowledgeTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'KnowledgeTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': 'Test to determine knowledge about information between two Sims.', 'subject': TunableEnumEntry(description='\n            The subject of the test. This is the Sim that needs to know\n            information about the target.\n            ', tunable_type=ParticipantTypeActorTargetSim, default=ParticipantTypeActorTargetSim.Actor), 'target': TunableEnumEntry(description='\n            The target of the test. This is the Sim whose information needs to\n            be known by the subject.\n            ', tunable_type=ParticipantTypeActorTargetSim, default=ParticipantTypeActorTargetSim.TargetSim), 'required_traits': TunableList(description='\n            If there are any traits specified in this list, the test will fail\n            if none of the traits are known.\n            ', tunable=TunableReference(manager=services.trait_manager())), 'prohibited_traits': TunableList(description='\n            The test will fail if any of the traits specified in this list are\n            known.\n            ', tunable=TunableReference(manager=services.trait_manager()))}

    def get_expected_args(self):
        return {'subject': self.subject, 'target': self.target}

    @cached_test
    def __call__(self, subject=None, target=None):
        subject = next(iter(subject))
        target = next(iter(target))
        if subject is None:
            return TestResult(False, 'Participant {} is None', self.subject, tooltip=self.tooltip)
        if target is None:
            return TestResult(False, 'Participant {} is None', self.target, tooltip=self.tooltip)
        knowledge = subject.relationship_tracker.get_knowledge(target.id)
        known_traits = knowledge.known_traits if knowledge is not None else set()
        if not (self.required_traits and any(required_trait in known_traits for required_trait in self.required_traits)):
            return TestResult(False, '{} does not know {} has any of these traits: {}', subject, target, self.required_traits, tooltip=self.tooltip)
        if any(prohibited_trait in known_traits for prohibited_trait in self.prohibited_traits):
            return TestResult(False, '{} knows {} has one or more of these traits: {}', subject, target, self.prohibited_traits, tooltip=self.tooltip)
        return TestResult.TRUE

class SocialBoredomTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'SocialBoredomTest'
    FACTORY_TUNABLES = {'threshold': TunableThreshold(description="\n            The test will fail if the affordance's boredom does not satisfy this\n            threshold.\n            ")}

    def get_expected_args(self):
        return {'affordance': ParticipantType.Affordance, 'social_group': ParticipantType.SocialGroup, 'subject': ParticipantType.Actor, 'target': ParticipantType.TargetSim}

    @cached_test
    def __call__(self, affordance=None, social_group=None, subject=None, target=None):
        subject = next(iter(subject), None)
        target = next(iter(target), None)
        social_group = next(iter(social_group), None)
        if subject is not None:
            subject = subject.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if target is not None:
            target = target.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if subject is None or target is None:
            return TestResult(False, '{} does not target instantiated Sims', affordance)
        if social_group is None:
            return TestResult(False, 'There is no social group associated with {}', affordance)
        boredom = social_group.get_boredom(subject, target, affordance)
        if not self.threshold.compare(boredom):
            return TestResult(False, 'Failed threshold test {} {}', boredom, self.threshold, tooltip=self.tooltip)
        return TestResult.TRUE

class HasCareerTestFactory(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'HasCareerTestFactory'
    FACTORY_TUNABLES = {'has_career': Tunable(description='If true all subjects must have a \n            career for the test to pass. If False then none of the subjects \n            can have a career for the test to pass.\n            ', tunable_type=bool, default=True)}

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self, subjects, targets=None, tooltip=None):
        for subject in subjects:
            if self.has_career:
                if not subject.career_tracker.careers:
                    return TestResult(False, '{0} does not currently have a career.', subject, tooltip=tooltip)
                    while subject.career_tracker.careers:
                        return TestResult(False, '{0} currently has a career'.format(subject), tooltip=tooltip)
            else:
                while subject.career_tracker.careers:
                    return TestResult(False, '{0} currently has a career'.format(subject), tooltip=tooltip)
        return TestResult.TRUE

class MaxCareerTestFactory(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'MaxCareerTestFactory'
    FACTORY_TUNABLES = {'has_max_careers': Tunable(description='If True all of the subjects\n            have to have the maximum number of careers to pass. If False then \n            none of the subjects can have the max number of careers to pass.\n            ', tunable_type=bool, default=True)}

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self, subjects, targets=None, tooltip=None):
        for subject in subjects:
            if self.has_max_careers:
                if len(subject.career_tracker.careers) < subject.MAX_CAREERS:
                    return TestResult(False, '{0} does not have the maximum number of careers', subject, tooltip=tooltip)
                    while len(subject.career_tracker.careers) >= subject.MAX_CAREERS:
                        return TestResult(False, '{0} has the maximum number of careers', subject, tooltip=tooltip)
            else:
                while len(subject.career_tracker.careers) >= subject.MAX_CAREERS:
                    return TestResult(False, '{0} has the maximum number of careers', subject, tooltip=tooltip)
        return TestResult.TRUE

class QuittableCareerTestFactory(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'QuittableCareerTestFactory'
    FACTORY_TUNABLES = {'has_quittable_career': Tunable(description='\n            If True then all of the subjects must have a quittable career in \n            order for the test to pass. If False then none of the subjects \n            can have a quittable career in order to pass.\n            ', tunable_type=bool, default=True)}

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self, subjects, targets=None, tooltip=None):
        for subject in subjects:
            if self.has_quittable_career:
                if not any(c.can_quit for c in subject.career_tracker.careers.values()):
                    return TestResult(False, '{0} does not have any quittable careers', subject, tooltip=tooltip)
                    while any(c.can_quit for c in subject.career_tracker.careers.values()):
                        return TestResult(False, '{0} has at least one career that is quittable', subject, tooltip=tooltip)
            else:
                while any(c.can_quit for c in subject.career_tracker.careers.values()):
                    return TestResult(False, '{0} has at least one career that is quittable', subject, tooltip=tooltip)
        return TestResult.TRUE

class CareerReferenceTestFactory(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'CareerReferenceTestFactory'
    UNIQUE_TARGET_TRACKING_AVAILABLE = True

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value.career is None and value.user_level is None:
            logger.error('A CareerReferenceTestFactory has no tuning for career or user_level. This is invalid tuning. Please fix!', owner='rfleig')

    FACTORY_TUNABLES = {'career': TunableReference(description='\n            The career to test for on the Sim. When set by itself it will pass\n            if the subject simply has this career. When set with user level it\n            will only pass if the subjects user level passes the threshold\n            test.\n            ', manager=services.get_instance_manager(sims4.resources.Types.CAREER)), 'user_level': OptionalTunable(TunableInterval(description='\n           Threshold test for the current user value of a career. If user_level\n           is set without career then it will pass if any of their careers \n           pass the threshold test. If set along with career then it will only\n           pass if the specified career passes the threshold test for user \n           level.\n           ', tunable_type=int, default_lower=1, default_upper=11, minimum=0, maximum=11)), 'verify_tunable_callback': _verify_tunable_callback}

    def get_expected_args(self):
        return {'career': event_testing.test_events.FROM_EVENT_DATA}

    @cached_test
    def __call__(self, subjects, career=None, targets=None, tooltip=None):
        for subject in subjects:
            current_value = 0
            if not subject.career_tracker.careers.values():
                return TestResult(False, '{0} does not have any careers currently and a career is needed for this interaction: {1}:{2}', subject, self.career, self.user_level)
            for this_career in subject.career_tracker.careers.values():
                while self.career is None or isinstance(this_career, self.career):
                    if self.user_level and (not this_career.user_level >= self.user_level.lower_bound or not this_career.user_level <= self.user_level.upper_bound):
                        current_value = this_career.user_level
                    break
            if self.user_level:
                return TestResultNumeric(False, '{0} does not currently have the correct career/user level ({1},{2})required to pass this test', subject, self.career, self.user_level, current_value=current_value, goal_value=self.user_level.lower_bound, is_money=False, tooltip=tooltip)
            return TestResult(False, '{0} does not currently have the correct career/user level ({1},{2})required to pass this test', subject, self.career, self.user_level, tooltip=tooltip)
        return TestResult.TRUE

    def get_target_id(self, subjects, career=None, targets=None, tooltip=None, id_type=None):
        if career is None:
            return
        if id_type == TargetIdTypes.DEFAULT or id_type == TargetIdTypes.DEFINITION:
            return career.guid64
        if id_type == TargetIdTypes.INSTANCE:
            return career.id
        logger.error('Unique target ID type: {} is not supported for test: {}', id_type, self)

class CareerTrackTestFactory(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'CareerTrackTestFactory'
    UNIQUE_TARGET_TRACKING_AVAILABLE = False
    FACTORY_TUNABLES = {'career_track': TunableReference(description='\n            A reference to the career track that each subject must have in at\n            least one career in order for this test to pass.\n            ', manager=services.get_instance_manager(sims4.resources.Types.CAREER_TRACK)), 'user_level': OptionalTunable(TunableInterval(description='\n           Interval test for the current user value of a career. Career track\n           must also be specified for this check to work properly.\n           ', tunable_type=int, default_lower=1, default_upper=10, minimum=0, maximum=10))}

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self, subjects, targets=None, tooltip=None):
        for subject in subjects:
            for career in subject.career_tracker.careers.values():
                while not (career.current_track_tuning == self.career_track and self.user_level and not career.user_level >= self.user_level.lower_bound):
                    if not career.user_level <= self.user_level.upper_bound:
                        pass
                    break
            return TestResult(False, '{0} is not currently in career track {1} in any of their current careers', subject, self.career_track, tooltip=tooltip)
        return TestResult.TRUE

class CareerLevelTestFactory(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'CareerLevelTestFactory'
    UNIQUE_TARGET_TRACKING_AVAILABLE = False
    FACTORY_TUNABLES = {'career_level': TunableReference(description='\n            A reference to career level tuning that each subject must have in \n            at least one career in order for this test to pass.\n            ', manager=services.get_instance_manager(sims4.resources.Types.CAREER_LEVEL), needs_tuning=True)}

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self, subjects, targets=None, tooltip=None):
        for subject in subjects:
            for career in subject.career_tracker.careers.values():
                while career.current_level_tuning == self.career_level:
                    break
            return TestResult(False, '{0} is not currently in career level {1} in any of their current careers', subject, self.career_level, tooltip=tooltip)
        return TestResult.TRUE

class SameCareerAtUserLevelTestFactory(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'SameCareerAtUserLevelTestFactory'
    UNIQUE_TARGET_TRACKING_AVAILABLE = False
    FACTORY_TUNABLES = {'user_level': TunableThreshold(description='User level to test for.')}

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self, subjects, targets=None, tooltip=None):
        common_careers = None
        for subject in subjects:
            subject_careers = set((type(career), career.user_level) for career in subject.career_tracker.careers.values())
            if common_careers is None:
                common_careers = subject_careers
            else:
                common_careers &= subject_careers
        if not common_careers:
            return TestResult(False, '{} do not have any common careers at the same user level.', subjects, tooltip=tooltip)
        return TestResult.TRUE

class IsRetiredTestFactory(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'IsRetiredTestFactory'
    FACTORY_TUNABLES = {'career': TunableReference(description='\n            The retired career to test for on the subjects. If left unset, the\n            test will pass if the Sim is retired from any career.\n            ', manager=services.get_instance_manager(sims4.resources.Types.CAREER))}

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self, subjects, targets=None, tooltip=None):
        for subject in subjects:
            retired_career_uid = subject.career_tracker.retired_career_uid
            if not retired_career_uid:
                return TestResult(False, '{0} is not retired from a career.', subject, tooltip=tooltip)
            while self.career is not None and self.career.guid64 != retired_career_uid:
                return TestResult(False, '{0} is retired from {}, which is not {}', subject, self.career, tooltip=tooltip)
        return TestResult.TRUE

class HasCareerOutfit(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'HasCareerOutfit'

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self, subjects, targets=None, tooltip=None):
        for subject in subjects:
            while not subject.career_tracker.has_career_outfit():
                return TestResult(False, '{} does not have a career outfit', subject, tooltip=tooltip)
        return TestResult.TRUE

class TunableCommonCareerTestsVariant(TunableVariant):
    __qualname__ = 'TunableCommonCareerTestsVariant'
    UNIQUE_TARGET_TRACKING_AVAILABLE = False

    def __init__(self, **kwargs):
        super().__init__(career_reference=CareerReferenceTestFactory.TunableFactory(), career_track=CareerTrackTestFactory.TunableFactory(), career_level=CareerLevelTestFactory.TunableFactory(), same_career_at_user_level=SameCareerAtUserLevelTestFactory.TunableFactory(), default='career_reference')

class CareerCommonTestFactory(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'CareerCommonTestFactory'
    UNIQUE_TARGET_TRACKING_AVAILABLE = False
    FACTORY_TUNABLES = {'targets': TunableEnumFlags(description='\n            tuning for the targets to check for the same common career on.\n            ', enum_type=ParticipantType, default=ParticipantType.Listeners), 'test_type': TunableCommonCareerTestsVariant()}

    def get_expected_args(self):
        return {'targets': self.targets}

    @cached_test
    def __call__(self, subjects, targets=(), tooltip=None):
        all_sims = tuple(set(subjects) | set(targets))
        if not self.test_type(all_sims, tooltip=tooltip):
            return TestResult(False, '{} do not have any common careers', subjects, tooltip=tooltip)
        return TestResult.TRUE

class TunableCareerTestVariant(TunableVariant):
    __qualname__ = 'TunableCareerTestVariant'

    def __init__(self, test_excluded={}, **kwargs):
        tunables = {'has_career': HasCareerTestFactory.TunableFactory(), 'has_max_careers': MaxCareerTestFactory.TunableFactory(), 'has_quittable_career': QuittableCareerTestFactory.TunableFactory(), 'career_reference': CareerReferenceTestFactory.TunableFactory(), 'career_track': CareerTrackTestFactory.TunableFactory(), 'career_level': CareerLevelTestFactory.TunableFactory(), 'common_career': CareerCommonTestFactory.TunableFactory(), 'is_retired': IsRetiredTestFactory.TunableFactory(), 'has_career_outfit': HasCareerOutfit.TunableFactory(), 'default': 'career_reference'}
        for key in test_excluded:
            del tunables[key]
        kwargs.update(tunables)
        super().__init__(**kwargs)

class TunableCareerTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'TunableCareerTest'
    test_events = (TestEvent.CareerEvent,)

    @flexproperty
    def UNIQUE_TARGET_TRACKING_AVAILABLE(cls, inst):
        if inst != None:
            return inst.test_type.UNIQUE_TARGET_TRACKING_AVAILABLE
        return False

    FACTORY_TUNABLES = {'subjects': TunableEnumEntry(description='\n            The participant to run the career test on.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'test_type': TunableCareerTestVariant(), 'negate': Tunable(description='If this is true then it will negate \n        the result of the test type. For instance if this is true and the test\n        would return true for whether or not a sim has a particular career\n        False will be returned instead.\n        ', tunable_type=bool, default=False)}

    def get_expected_args(self):
        expected_args = {'subjects': self.subjects}
        if self.test_type:
            test_args = self.test_type.get_expected_args()
            expected_args.update(test_args)
        return expected_args

    @cached_test
    def __call__(self, *args, **kwargs):
        result = self.test_type(tooltip=self.tooltip, *args, **kwargs)
        if self.negate:
            if not result:
                return TestResult.TRUE
            return TestResult(False, 'Test passed but the result was negated.')
        return result

    def get_target_id(self, *args, **kwargs):
        if self.test_type and self.test_type.UNIQUE_TARGET_TRACKING_AVAILABLE:
            return self.test_type.get_target_id(tooltip=self.tooltip, *args, **kwargs)
        return super().get_target_id(*args, **kwargs)

class GreetedTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'GreetedTest'
    test_events = ()
    FACTORY_TUNABLES = {'test_for_greeted_status': Tunable(description="\n                If checked then this test will pass if the player is considered\n                greeted on the current lot.  If unchecked the test will pass\n                If the player is considered ungreeted on the current lot.\n                If the current lot doesn't require visitation rights the player\n                will never be considered greeted.\n                ", tunable_type=bool, default=True)}

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self):
        if services.get_zone_situation_manager().is_player_greeted() != self.test_for_greeted_status:
            if self.test_for_greeted_status:
                return TestResult(False, 'Player sim is ungreeted when we are looking for them being greeted.', tooltip=self.tooltip)
            return TestResult(False, 'Player sim is greeted when we are looking for them being ungreeted.', tooltip=self.tooltip)
        return TestResult.TRUE

class RequiresVisitationRightsTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'RequiresVisitationRightsTest'
    test_events = ()
    FACTORY_TUNABLES = {'test_for_visitation_rights': Tunable(description="\n                If checked then this test will pass if the the current lot's\n                venue type requires visitation rights.  If unchecked then the\n                test will pass if it does not require visitation rights.\n                ", tunable_type=bool, default=True)}

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self):
        if services.current_zone().venue_service.venue.requires_visitation_rights != self.test_for_visitation_rights:
            if self.test_for_visitation_rights:
                return TestResult(False, "The current lot's venue type doesn't require visitation rights.", tooltip=self.tooltip)
            return TestResult(False, "The current lot's venue type requires visitation rights.", tooltip=self.tooltip)
        return TestResult.TRUE

class ObjectCriteriaTestEvents(enum.Int):
    __qualname__ = 'ObjectCriteriaTestEvents'
    AllObjectEvents = 0
    OnExitBuildBuy = TestEvent.OnExitBuildBuy
    ObjectStateChange = TestEvent.ObjectStateChange
    ItemCrafted = TestEvent.ItemCrafted
    ObjectDestroyed = TestEvent.ObjectDestroyed
    OnInventoryChanged = TestEvent.OnInventoryChanged

class ObjectCriteriaTest(HasTunableSingletonFactory, event_testing.test_base.BaseTest):
    __qualname__ = 'ObjectCriteriaTest'
    TARGET_OBJECTS = 0
    ALL_OBJECTS = 1

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value.desired_state_threshold is not None:
            threshold_value = value.desired_state_threshold.value
            if threshold_value.state is None or not hasattr(threshold_value, 'value'):
                logger.error('invalid state value in desired state threshold for {}: {}', source, tunable_name)

    FACTORY_TUNABLES = {'verify_tunable_callback': _verify_tunable_callback, 'subject_specific_tests': TunableVariant(all_objects=TunableTuple(locked_args={'subject_type': ALL_OBJECTS}, quantity=TunableThreshold(description='\n                        The number of objects that meet the tuned critera needed to pass this\n                        test. quantity is run after a list of matching objects is created\n                        using the tuned criteria.\n                        ', default=sims4.math.Threshold(1, sims4.math.Operator.GREATER_OR_EQUAL.function), value=Tunable(float, 1, description='The value of a threshold.')), total_value=OptionalTunable(TunableThreshold(description='\n                        If set, the total monetary value of all the objects that meet the tuned \n                        criteria needed in order to pass this test. total_value is run after \n                        a list of matching objects is created using the tuned criteria.\n                        '))), single_object=TunableTuple(locked_args={'subject_type': TARGET_OBJECTS}, target=TunableEnumEntry(description='\n                        If set this test will loop through the specified participants and\n                        run the object identity and criteria tests on them instead of all\n                        of the objects on the lot.\n                        ', tunable_type=ParticipantType, default=ParticipantType.Object)), default='all_objects'), 'identity_test': TunableVariant(description='\n            Which test to run on the object in order to determine \n            if it matches or not.\n            ', default='definition_id', definition_id=ObjectTypeFactory(), tags=ObjectTagFactory()), 'owned': Tunable(description="\n            If checked will test if the object is owned by the active \n            household. If unchecked it doesn't matter who owns the object or\n            if it is owned at all.\n            ", tunable_type=bool, default=True), 'on_active_lot': Tunable(description="\n            If checked, test whether or not the object is on the active\n            lot. If unchecked the object can be either on the active lot or\n            in the open streets area, we don't really care.\n            ", tunable_type=bool, default=False), 'desired_state_threshold': OptionalTunable(TunableThreshold(description='\n            A state threshold that the object must satisfy for this test to pass', value=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions='ObjectStateValue'))), 'test_events': TunableList(description='\n            The list of events that trigger this instance of the tuned test on.\n            \n            If you pick ObjectStateChange, the test will be registered with\n            EventManager for every ObjectStateValue managed by ObjectState\n            controlling the desired_state_threshold. E.g. if the test cares\n            about BrokenState_Broken, we will register tolisten for events for\n            state changes of BrokenState_Broken, BrokenState_Unbroken,\n            BrokenState_Repairing, etc.\n            ', tunable=TunableEnumEntry(tunable_type=ObjectCriteriaTestEvents, default=ObjectCriteriaTestEvents.AllObjectEvents), set_default_as_first_entry=True), 'use_depreciated_values': Tunable(description='\n            If checked, the value consideration for each checked object will at its depreciated amount.\n            This affects the "All Objects" test type, changing the total value considered to be at the\n            non-depreciated amount.\n            ', tunable_type=bool, default=False), 'value': OptionalTunable(TunableThreshold(description='\n            A threshold test for the monetary value of a single object in order for it\n            to be considered.\n            ')), 'completed': Tunable(description='\n            If checked, any craftable object (such as a painting) must be finished\n            for it to be considered.\n            ', tunable_type=bool, default=False)}

    def __init__(self, subject_specific_tests, identity_test, owned, on_active_lot, desired_state_threshold, test_events, value, use_depreciated_values, completed, **kwargs):
        super().__init__(**kwargs)
        if test_events and test_events[0] == ObjectCriteriaTestEvents.AllObjectEvents:
            self.test_events = (TestEvent.OnExitBuildBuy, TestEvent.ObjectStateChange, TestEvent.ItemCrafted, TestEvent.ObjectDestroyed, TestEvent.OnInventoryChanged)
        else:
            self.test_events = test_events
        self.subject_specific_tests = subject_specific_tests
        self.identity_test = identity_test
        self.owned = owned
        self.on_active_lot = on_active_lot
        self.desired_state_threshold = desired_state_threshold
        self.value = value
        self.use_depreciated_values = use_depreciated_values
        self.completed = completed

    def get_test_events_to_register(self):
        events = (event for event in self.test_events if event is not TestEvent.ObjectStateChange)
        return events

    def get_custom_event_registration_keys(self):
        keys = []
        if self.desired_state_threshold is not None:
            for value in self.desired_state_threshold.value.state.values:
                keys.append((TestEvent.ObjectStateChange, value))
        return keys

    def get_expected_args(self):
        expected_args = {}
        if self.subject_specific_tests.subject_type == self.TARGET_OBJECTS:
            expected_args['target_object'] = self.subject_specific_tests.target
        return expected_args

    def object_meets_criteria(self, obj, active_household_id, current_zone):
        if self.owned and obj.get_household_owner_id() != active_household_id:
            return False
        if self.on_active_lot and not obj.is_on_active_lot():
            return False
        if self.completed and obj.crafting_component is not None:
            crafting_process = obj.get_crafting_process()
            if not crafting_process.is_complete:
                return False
        if self.desired_state_threshold is not None:
            desired_state = self.desired_state_threshold.value.state
            if not obj.has_state(desired_state):
                return False
            if not self.desired_state_threshold.compare_value(obj.get_state(desired_state)):
                return False
        obj_value = obj.depreciated_value if self.use_depreciated_values else obj.catalog_value
        if self.value is not None and not self.value.compare(obj_value):
            return False
        return True

    @cached_test
    def __call__(self, target_object=None):
        total_value = 0
        active_household_id = services.active_household_id()
        current_zone = services.current_zone()

        def objects_to_test_gen():
            if target_object is not None:
                for obj in target_object:
                    yield obj
            else:
                for obj in services.object_manager().values():
                    yield obj

        number_of_matches = 0
        for obj in objects_to_test_gen():
            while self.identity_test(obj):
                if self.object_meets_criteria(obj, active_household_id, current_zone):
                    number_of_matches += 1
                    total_value += obj.depreciated_value if self.use_depreciated_values else obj.catalog_value
        if self.subject_specific_tests.subject_type == self.ALL_OBJECTS:
            if not self.subject_specific_tests.quantity.compare(number_of_matches):
                return TestResultNumeric(False, 'There are {} matches when {} matches are needed for the object criteria tuning', number_of_matches, self.subject_specific_tests.quantity.value, current_value=number_of_matches, goal_value=self.subject_specific_tests.quantity.value, is_money=False)
            if self.subject_specific_tests.total_value is not None and not self.subject_specific_tests.total_value.compare(total_value):
                return TestResultNumeric(False, 'The total value is {} when it needs to be {} for the object criteria tuning', total_value, self.subject_specific_tests.total_value.value, current_value=total_value, goal_value=self.subject_specific_tests.total_value.value, is_money=True)
        elif target_object is None or number_of_matches != len(target_object):
            return TestResult(False, "All of the specified targets don't meet the object criteria tuning.")
        return TestResult.TRUE

    def goal_value(self):
        if self.subject_specific_tests.total_value is not None:
            return self.subject_specific_tests.total_value.value
        return self.subject_specific_tests.quantity.value

    @property
    def is_goal_value_money(self):
        return self.subject_specific_tests.total_value is not None

class UnlockTrackerTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'UnlockTrackerTest'

    @TunableFactory.factory_option
    def participant_type_override(participant_type_enum, participant_type_default):
        return {'subject': TunableEnumEntry(description='\n                    Who or what to apply this test to\n                    ', tunable_type=participant_type_enum, default=participant_type_default)}

    FACTORY_TUNABLES = {'subject': TunableEnumEntry(description='\n            Who or what to apply this test to\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'unlock_item': TunableUnlockVariant(description='\n            The unlock item that Sim has or not.\n            ')}

    def get_expected_args(self):
        return {'test_targets': self.subject}

    @cached_test
    def __call__(self, test_targets=()):
        for target in test_targets:
            if not target.is_sim:
                return TestResult(False, 'Cannot test unlock on none_sim object {} as subject {}.', target, self.subject, tooltip=self.tooltip)
            while not target.unlock_tracker.is_unlocked(self.unlock_item):
                return TestResult(False, "Sim {} hasn't unlock {}.", target, self.unlock_item, tooltip=self.tooltip)
        return TestResult.TRUE

class PhoneSilencedTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'PhoneSilencedTest'
    FACTORY_TUNABLES = {'is_silenced': Tunable(description='\n            If checked the test will return True if the phone is silenced.\n            ', tunable_type=bool, default=True)}

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self):
        is_phone_silenced = services.ui_dialog_service().is_phone_silenced
        if is_phone_silenced and not self.is_silenced:
            return TestResult(False, 'The phone is not silenced.', tooltip=self.tooltip)
        if not is_phone_silenced and self.is_silenced:
            return TestResult(False, 'The phone is silenced.', tooltip=self.tooltip)
        return TestResult.TRUE

class FireTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'FireTest'
    FACTORY_TUNABLES = {'lot_on_fire': OptionalTunable(Tunable(description='\n            Whether you are testing for fire being present on the lot or not\n            present.\n            ', tunable_type=bool, default=True)), 'sim_on_fire': OptionalTunable(TunableTuple(subject=TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='\n                Check the selected participant for whether or not they are on fire.\n                '), on_fire=Tunable(description='Whether the sim needs to be on fire or not', tunable_type=bool, default=True)))}

    def get_expected_args(self):
        args = {}
        if self.sim_on_fire is not None:
            args['subject'] = self.sim_on_fire.subject
        return args

    @cached_test
    def __call__(self, subject=[]):
        if self.lot_on_fire is not None:
            fire_service = services.get_fire_service()
            if not self.lot_on_fire == fire_service.fire_is_active:
                return TestResult(False, 'Testing for lot on fire failed. Lot on Fire={}, Wanted: {}', fire_service.fire_is_active, self.lot_on_fire, tooltip=self.tooltip)
        if self.sim_on_fire is not None:
            for sim in subject:
                while not sim.on_fire == self.sim_on_fire.on_fire:
                    return TestResult(False, 'Sim on fire test failed. Sim={}, On Fire={}', sim, self.sim_on_fire.on_fire, tooltip=self.tooltip)
        return TestResult.TRUE

class ConsumableTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'ConsumableTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': 'A test that checks information about consumables.', 'subject': TunableEnumEntry(description='\n            The subject of the test. This is the consumable object.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'is_consumable': Tunable(description='\n            If checked, the subject must be a consumable, if unchecked, the\n            subject must not be a consumable.\n            ', tunable_type=bool, default=True), 'bites_left': TunableTuple(description='\n            A check that tests against the number of bites left before the\n            subject is completely consumed.\n            ', value=Tunable(description='\n                The number of bites to test against.\n                ', tunable_type=int, default=1), operator=TunableOperator(description='\n                The operator to use for the comparison.\n                ', default=sims4.math.Operator.EQUAL))}

    def get_expected_args(self):
        return {'subject': self.subject}

    @cached_test
    def __call__(self, subject=None, target=None):
        subject = next(iter(subject))
        consumable_component = subject.consumable_component
        if consumable_component is None and self.is_consumable:
            return TestResult(False, 'Object {} is not a consumable but is expected to be.', subject, tooltip=self.tooltip)
        if consumable_component is not None and not self.is_consumable:
            return TestResult(False, 'Object {} is a consumable but is expected not to be.', subject, tooltip=self.tooltip)
        bites_left_in_subject = consumable_component.bites_left()
        threshold = sims4.math.Threshold(self.bites_left.value, self.bites_left.operator)
        if not threshold.compare(bites_left_in_subject):
            return TestResult(False, 'Object {} is expected to have {} {} bites left, but actually has {} bites left.', subject, self.bites_left.operator, self.bites_left.value, bites_left_in_subject, tooltip=self.tooltip)
        return TestResult.TRUE

class FrontDoorTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'FrontDoorTest'
    test_events = ()

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self):
        lot = services.active_lot()
        if lot is not None:
            if lot.front_door_id is not None:
                return TestResult.TRUE
            return TestResult(False, 'Active lot has no front door.', tooltip=self.tooltip)
        return TestResult(False, 'Active lot is None.', tooltip=self.tooltip)

class CanSeeObjectTest(event_testing.test_base.BaseTest):
    __qualname__ = 'CanSeeObjectTest'
    test_events = ()
    FACTORY_TUNABLES = {'description': 'Require the Sim to be able to see the object.'}

    def get_expected_args(self):
        return {'sim_info_list': ParticipantType.Actor, 'target_list': ParticipantType.Object}

    @cached_test
    def __call__(self, sim_info_list=None, target_list=None):
        if sim_info_list is None:
            return TestResult(False, 'There are no actors.', tooltip=self.tooltip)
        if target_list is None:
            return TestResult(False, "Target object doesn't exist.", tooltip=self.tooltip)
        for sim_info in sim_info_list:
            sim = sim_info.get_sim_instance()
            if sim is None:
                return TestResult(False, '{} is not instanced..'.format(sim_info), tooltip=self.tooltip)
            for obj in target_list:
                while not sim.can_see(obj):
                    return TestResult(False, "{} can't see {}.".format(sim, obj), tooltip=self.tooltip)
        return TestResult.TRUE

TunableCanSeeObjectTest = TunableSingletonFactory.create_auto_factory(CanSeeObjectTest)

class LotHasFloorFeatureTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'LotHasFloorFeatureTest'
    FACTORY_TUNABLES = {'terrain_feature': TunableEnumEntry(description='\n            Tune this to the floor feature type that needs to be present\n            ', tunable_type=FloorFeatureType, default=FloorFeatureType.BURNT)}
    test_events = ()

    def get_expected_args(self):
        return {}

    @cached_test
    def __call__(self):
        lot = services.active_lot()
        if lot is not None:
            if build_buy.list_floor_features(lot.zone_id, self.terrain_feature):
                return TestResult.TRUE
            return TestResult(False, 'Active lot does not have the tuned floor feature.', tooltip=self.tooltip)
        return TestResult(False, 'Active lot is None.', tooltip=self.tooltip)

