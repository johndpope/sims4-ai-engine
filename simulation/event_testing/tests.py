import itertools
import event_testing.resolver
import event_testing.results
import event_testing.test_based_score_threshold
import event_testing.test_variants
import services
import sims4.log
import sims4.repr_utils
import sims4.tuning.tunable
import sims4.utils
logger = sims4.log.Logger('Tests')

def _get_debug_loaded_tuning_callbak(tuning_loaded_callback, callback):
    return callback

def _verify_tooltip_tuning(instance_class, tunable_name, source, value):
    test_with_tooltip = None
    for test in value:
        if test.has_tooltip():
            test_with_tooltip = test
        else:
            while test_with_tooltip is not None:
                test_name = getattr(test_with_tooltip, '__name__', type(test_with_tooltip).__name__)
                if hasattr(test_with_tooltip, 'tooltip'):
                    tooltip_id = test_with_tooltip.tooltip._string_id
                else:
                    tooltip_id = 0
                logger.error('TestSet in {} has a test ({}) which specifies a tooltip (0x{:x}) which precedes tests without tooltips.', instance_class.__name__, test_name, tooltip_id)
                break

class TunableTestVariant(sims4.tuning.tunable.TunableVariant):
    __qualname__ = 'TunableTestVariant'

    def __init__(self, description='A single tunable test.', test_excluded=(), test_locked_args={}, **kwargs):
        test_map = {'age_up_test': event_testing.test_variants.TunableAgeUpTest, 'appropriateness': event_testing.test_variants.TunableAppropriatenessTest, 'autonomy_scoring_preference': event_testing.test_variants.TunableObjectScoringPreferenceTest, 'bills': event_testing.test_variants.TunableBillsTest, 'buff': event_testing.test_variants.TunableBuffTest, 'can_create_object': event_testing.test_variants.TunableCreateObjectTest, 'can_see_object': event_testing.test_variants.TunableCanSeeObjectTest, 'career_test': event_testing.test_variants.TunableCareerTest.TunableFactory, 'collection_test': event_testing.test_variants.TunableCollectionThresholdTest, 'commodity_advertised': event_testing.test_variants.CommodityAdvertisedTest.TunableFactory, 'commodity_desired_by_other_sims': event_testing.test_variants.CommodityDesiredByOtherSims.TunableFactory, 'consumable_test': event_testing.test_variants.ConsumableTest.TunableFactory, 'content_mode': event_testing.test_variants.TunableContentModeTest, 'crafted_item': event_testing.test_variants.TunableCraftedItemTest, 'custom_name': event_testing.test_variants.CustomNameTest.TunableFactory, 'day_and_time': event_testing.test_variants.TunableDayTimeTest, 'distance': event_testing.test_variants.DistanceTest.TunableFactory, 'during_work_hours': event_testing.test_variants.TunableDuringWorkHoursTest, 'at_work': event_testing.test_variants.AtWorkTest.TunableFactory, 'existence': event_testing.test_variants.ExistenceTest.TunableFactory, 'filter_test': event_testing.test_variants.TunableFilterTest, 'fire': event_testing.test_variants.FireTest.TunableFactory, 'game_component': event_testing.test_variants.GameTest.TunableFactory, 'gender_preference': event_testing.test_variants.TunableGenderPreferencetTest, 'genealogy': event_testing.test_variants.GenealogyTest.TunableFactory, 'greeted': event_testing.test_variants.GreetedTest.TunableFactory, 'has_free_part': event_testing.test_variants.HasFreePartTest.TunableFactory, 'has_in_use_part': event_testing.test_variants.HasInUsePartTest.TunableFactory, 'has_lot_owner': event_testing.test_variants.HasLotOwnerTest.TunableFactory, 'has_parent_object': event_testing.test_variants.HasParentObjectTest.TunableFactory, 'household_size': event_testing.test_variants.HouseholdSizeTest.TunableFactory, 'identity': event_testing.test_variants.TunableIdentityTest, 'in_inventory': event_testing.test_variants.InInventoryTest.TunableFactory, 'in_use': event_testing.test_variants.InUseTest.TunableFactory, 'inappropriateness': event_testing.test_variants.TunableInappropriatenessTest, 'interaction_restored_from_load': event_testing.test_variants.InteractionRestoredFromLoadTest.TunableFactory, 'inventory': event_testing.test_variants.InventoryTest.TunableFactory, 'is_carrying_object': event_testing.test_variants.TunableIsCarryingObjectTest, 'knowledge': event_testing.test_variants.KnowledgeTest.TunableFactory, 'location': event_testing.test_variants.TunableLocationTest, 'lot_has_floor_feature': event_testing.test_variants.LotHasFloorFeatureTest.TunableFactory, 'lot_has_front_door': event_testing.test_variants.FrontDoorTest.TunableFactory, 'lot_owner': event_testing.test_variants.TunableLotOwnerTest, 'mood': event_testing.test_variants.TunableMoodTest, 'motive': event_testing.test_variants.TunableMotiveThresholdTestTest, 'object_criteria': event_testing.test_variants.ObjectCriteriaTest.TunableFactory, 'object_environment_score': event_testing.test_variants.ObjectEnvironmentScoreTest.TunableFactory, 'object_ownership': event_testing.test_variants.ObjectOwnershipTest.TunableFactory, 'object_relationship': event_testing.test_variants.TunableObjectRelationshipTest, 'party_age': event_testing.test_variants.TunablePartyAgeTest, 'party_size': event_testing.test_variants.TunablePartySizeTest, 'permission_test': event_testing.test_variants.TunableSimPermissionTest, 'phone_silenced_test': event_testing.test_variants.PhoneSilencedTest.TunableFactory, 'pick_info_test': event_testing.test_variants.TunablePickInfoTest, 'posture': event_testing.test_variants.PostureTest.TunableFactory, 'relationship': event_testing.test_variants.TunableRelationshipTest, 'relative_statistic': event_testing.test_variants.TunableRelativeStatTest, 'routability': event_testing.test_variants.RoutabilityTest.TunableFactory, 'selected_aspiration_track_test': event_testing.test_variants.TunableSelectedAspirationTrackTest, 'service_npc_hired_test': event_testing.test_variants.TunableServiceNpcHiredTest, 'sim_info': event_testing.test_variants.TunableSimInfoTest, 'simoleon_value': event_testing.test_variants.TunableSimoleonsTest, 'situation_availability': event_testing.test_variants.TunableSituationAvailabilityTest, 'situation_job_test': event_testing.test_variants.TunableSituationJobTest, 'situation_running_test': event_testing.test_variants.TunableSituationRunningTest, 'skill_tag': event_testing.test_variants.TunableSkillTagThresholdTest, 'skill_test': event_testing.test_variants.SkillRangeTest.TunableFactory, 'skill_in_use': event_testing.test_variants.TunableSkillInUseTest, 'slot_test': event_testing.test_variants.TunableSlotTest, 'social_boredom': event_testing.test_variants.SocialBoredomTest.TunableFactory, 'social_context': event_testing.test_variants.SocialContextTest.TunableFactory, 'social_group': event_testing.test_variants.SocialGroupTest.TunableFactory, 'state': event_testing.test_variants.TunableStateTest, 'statistic': event_testing.test_variants.TunableStatThresholdTest, 'statistic_in_category': event_testing.test_variants.TunableStatOfCategoryTest, 'statistic_in_motion': event_testing.test_variants.TunableStatInMotionTest, 'test_based_score_threshold': event_testing.test_based_score_threshold.TunableTestBasedScoreThresholdTest, 'test_set_reference': lambda **__: sims4.tuning.tunable.TunableReference(manager=services.get_instance_manager(sims4.resources.Types.SNIPPET), class_restrictions=('TestSetInstance',)), 'topic': event_testing.test_variants.TunableTopicTest, 'total_event_simoleons_earned': event_testing.test_variants.TunableTotalSimoleonsEarnedTest, 'total_time_played': event_testing.test_variants.TunableTotalTimePlayedTest, 'trait': event_testing.test_variants.TunableTraitTest, 'unlock_earned': event_testing.test_variants.TunableUnlockedTest, 'unlock_tracker': event_testing.test_variants.UnlockTrackerTest.TunableFactory, 'user_facing_situation_running_test': event_testing.test_variants.TunableUserFacingSituationRunningTest, 'user_running_interaction': event_testing.test_variants.UserRunningInteractionTest.TunableFactory, 'visitation_rights': event_testing.test_variants.RequiresVisitationRightsTest.TunableFactory}
        for key in test_excluded:
            del test_map[key]
        kwargs.update({test_name: test_factory(locked_args=test_locked_args) for (test_name, test_factory) in test_map.items()})
        super().__init__(description=description, **kwargs)

class CompoundTestList(list):
    __qualname__ = 'CompoundTestList'
    __slots__ = ()

    def __repr__(self):
        result = super().__repr__()
        return sims4.repr_utils.standard_repr(self, result)

    def _run_method_over_tests(self, resolver, skip_safe_tests, search_for_tooltip):
        group_result = event_testing.results.TestResult.TRUE
        for test_group in self:
            result = event_testing.results.TestResult(True)
            failed_result = None
            if not test_group:
                logger.error('Tuning Error: An empty test list was detected in a tunable test for {}', resolver)
            for test in test_group:
                if test is None:
                    logger.error('Tuning Error: A None value was detected in a tunable test for {}', resolver)
                if skip_safe_tests and test.safe_to_skip:
                    pass
                result &= resolver(test)
                if result:
                    pass
                if group_result:
                    group_result = result
                if not search_for_tooltip:
                    break
                if result.tooltip is not None:
                    failed_result = result
                else:
                    failed_result = None
                    break
            if failed_result is not None:
                group_result = failed_result
            while result:
                return result
        return group_result

    def run_tests(self, resolver, skip_safe_tests=False, search_for_tooltip=False):
        return self._run_method_over_tests(resolver, skip_safe_tests, search_for_tooltip)

    def can_make_pass(self, resolver, skip_safe_tests=False, search_for_tooltip=False):
        return self._run_method_over_tests(resolver.can_make_pass, skip_safe_tests, False)

    def make_pass(self, resolver, skip_safe_tests=False, search_for_tooltip=False):
        return self._run_method_over_tests(resolver.make_pass, skip_safe_tests, False)

class CompoundTestListLoadingMixin(sims4.tuning.tunable.TunableList):
    __qualname__ = 'CompoundTestListLoadingMixin'

    def load_etree_node(self, **kwargs):
        value = super().load_etree_node(**kwargs)
        if value is not None:
            return CompoundTestList(value)

class _TunableTestSetBase(CompoundTestListLoadingMixin):
    __qualname__ = '_TunableTestSetBase'
    DEFAULT_LIST = CompoundTestList()

    def __init__(self, description=None, callback=None, test_locked_args={}, **kwargs):
        if description is None:
            description = '\n                A list of tests groups.  At least one must pass all its sub-\n                tests to pass the TestSet.\n                '
        super().__init__(description=description, callback=_get_debug_loaded_tuning_callbak(self._on_tunable_loaded_callback, callback), tunable=sims4.tuning.tunable.TunableList(description='\n                             A list of tests.  All of these must pass for the\n                             group to pass.\n                             ', tunable=TunableTestVariant(test_locked_args=test_locked_args)), **kwargs)
        self.cache_key = '{}_{}'.format('TunableTestSet', self._template.cache_key)

    def _on_tunable_loaded_callback(self, instance_class, tunable_name, source, value):
        for test_set in value:
            _verify_tooltip_tuning(instance_class, tunable_name, source, test_set)

class TunableTestSet(_TunableTestSetBase, is_fragment=True):
    __qualname__ = 'TunableTestSet'

    def __init__(self, **kwargs):
        super().__init__(test_locked_args={'tooltip': None}, **kwargs)

class TunableTestSetWithTooltip(_TunableTestSetBase, is_fragment=True):
    __qualname__ = 'TunableTestSetWithTooltip'

    def __init__(self, **kwargs):
        super().__init__(test_locked_args={}, **kwargs)

class TestList(list):
    __qualname__ = 'TestList'
    __slots__ = ()

    def __repr__(self):
        result = super().__repr__()
        return sims4.repr_utils.standard_repr(self, result)

    def _run_method_over_tests(self, resolver, skip_safe_tests, search_for_tooltip):
        result = event_testing.results.TestResult.TRUE
        failed_result = None
        for test in self:
            if test is None:
                logger.error('Tuning Error: A None value was detected in a tunable test for {}', resolver, test)
            if skip_safe_tests and test.safe_to_skip:
                pass
            result &= resolver(test)
            if result:
                pass
            if not search_for_tooltip:
                break
            if result.tooltip is not None:
                failed_result = result
            else:
                failed_result = None
                break
        if failed_result is not None:
            result = failed_result
        return result

    def run_tests(self, resolver, skip_safe_tests=False, search_for_tooltip=False):
        return self._run_method_over_tests(resolver, skip_safe_tests, search_for_tooltip)

    def can_make_pass(self, resolver, skip_safe_tests=False, search_for_tooltip=False):
        return self._run_method_over_tests(resolver.can_make_pass, skip_safe_tests, search_for_tooltip)

    def make_pass(self, resolver, skip_safe_tests=False, search_for_tooltip=False):
        return self._run_method_over_tests(resolver.make_pass, skip_safe_tests, search_for_tooltip)

    def get_test_events(self):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return {test_event for test in self for test_event in test.test_events}

class TestListLoadingMixin(sims4.tuning.tunable.TunableList):
    __qualname__ = 'TestListLoadingMixin'

    def load_etree_node(self, **kwargs):
        value = super().load_etree_node(**kwargs)
        if value is not None:
            return TestList(value)

class TunableGlobalTestSet(TestListLoadingMixin, is_fragment=True):
    __qualname__ = 'TunableGlobalTestSet'
    DEFAULT_LIST = TestList()

    def __init__(self, description=None, callback=None, **kwargs):
        if description is None:
            description = 'A list of tests.  All tests must succeed to pass the TestSet.'
        super().__init__(description=description, tunable=TunableTestVariant(), callback=_get_debug_loaded_tuning_callbak(self._on_tunable_loaded_callback, callback), **kwargs)
        self.cache_key = '{}_{}'.format('TunableGlobalTestSet', self._template.cache_key)

    def _on_tunable_loaded_callback(self, instance_class, tunable_name, source, value):
        test_with_tooltip = None
        for test in value:
            if not hasattr(test, 'tooltip'):
                for sub_test in itertools.chain.from_iterable(test.test):
                    sub_tooltip = getattr(sub_test, 'tooltip', None)
                    while sub_tooltip is not None:
                        tooltip = sub_tooltip
                        break
            else:
                tooltip = test.tooltip
            if tooltip is None:
                test_name = getattr(test_with_tooltip[0], '__name__', type(test_with_tooltip[0]).__name__)
                logger.error('TestSet in {} has a test ({}) which specifies a tooltip (0x{:x}) which precedes tests without tooltips.', instance_class.__name__, test_name, test_with_tooltip[1]._string_id)
                break
            else:
                test_with_tooltip = (test, tooltip)
        _verify_tooltip_tuning(instance_class, tunable_name, source, value)
        test_with_tooltip = None
        for test in value:
            if not hasattr(test, 'tooltip'):
                for sub_test in itertools.chain.from_iterable(test.test):
                    sub_tooltip = getattr(sub_test, 'tooltip', None)
                    while sub_tooltip is not None:
                        tooltip = sub_tooltip
                        break
            else:
                tooltip = test.tooltip
            if tooltip is None:
                test_name = getattr(test_with_tooltip[0], '__name__', type(test_with_tooltip[0]).__name__)
                logger.error('TestSet in {} has a test ({}) which specifies a tooltip (0x{:x}) which precedes tests without tooltips.', instance_class.__name__, test_name, test_with_tooltip[1]._string_id)
                break
            else:
                test_with_tooltip = (test, tooltip)

class TestSetInstance(metaclass=sims4.tuning.instances.HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.SNIPPET)):
    __qualname__ = 'TestSetInstance'
    INSTANCE_TUNABLES = {'test': TunableTestSetWithTooltip()}

    def __new__(cls, resolver, **kwargs):
        return cls.test.run_tests(resolver, resolver.skip_safe_tests, resolver.search_for_tooltip)

    @classmethod
    def has_tooltip(cls):
        return any(test.has_tooltip() for test in itertools.chain.from_iterable(cls.test))

    @sims4.utils.flexproperty
    def safe_to_skip(cls, inst):
        return False

    @sims4.utils.flexmethod
    def get_expected_args(cls, inst):
        return {'resolver': event_testing.resolver.RESOLVER_PARTICIPANT}

