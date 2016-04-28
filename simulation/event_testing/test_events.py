from collections import Counter
import collections
from sims4.callback_utils import CallbackEvent
from sims4.service_manager import Service
from sims4.tuning.dynamic_enum import DynamicEnum
from sims4.utils import decorator
from singletons import SingletonType
import caches
import event_testing.resolver
import services
import sims4.log
logger = sims4.log.Logger('EventManager')

class TestEvent(DynamicEnum):
    __qualname__ = 'TestEvent'
    Invalid = 0
    SkillLevelChange = 1
    ObjectAdd = 2
    InteractionComplete = 3
    SituationEnded = 4
    ItemCrafted = 5
    InteractionAtEvent = 6
    SimoleonsEarned = 7
    UpdateAllEvent = 8
    TraitAddEvent = 9
    MotiveLevelChange = 10
    TestTotalTime = 11
    SimTravel = 12
    AddRelationshipBit = 13
    RemoveRelationshipBit = 14
    BuffBeganEvent = 15
    BuffEndedEvent = 16
    WorkdayComplete = 17
    MoodChange = 18
    HouseholdChanged = 19
    InteractionStart = 20
    AspirationTrackSelected = 21
    PrerelationshipChanged = 22
    RelationshipChanged = 23
    CollectedSomething = 24
    FamilyTrigger = 25
    InteractionStaged = 26
    InteractionExitedPipeline = 27
    UITraitsPanel = 28
    UICareerPanel = 29
    UIAspirationsPanel = 30
    UIRelationshipPanel = 31
    UISkillsPanel = 32
    UISimInventory = 33
    UIPhoneButton = 34
    UIAchievementPanel = 35
    UICameraButton = 36
    UIBuildButton = 37
    WhimCompleted = 38
    ObjectStateChange = 39
    OffspringCreated = 40
    CareerEvent = 41
    BuffUpdateEvent = 42
    InteractionUpdate = 43
    StatValueUpdate = 44
    LoadingScreenLifted = 45
    OnExitBuildBuy = 46
    OnBuildBuyReset = 47
    OnSimReset = 48
    UIMemoriesPanel = 49
    ReadyToAge = 50
    BillsDelivered = 51
    UnlockEvent = 52
    SimActiveLotStatusChanged = 53
    OnInventoryChanged = 54
    UpdateObjectiveData = 55
    ObjectDestroyed = 56

SIM_INSTANCE = 'sim_instance'
TARGET_SIM_ID = 'target_sim_id'
FROM_EVENT_DATA = 'from_event_data'
FROM_DATA_OBJECT = 'from_data_object'
OBJECTIVE_GUID64 = 'objective_guid64'

class DataStoreEventMap(SingletonType, dict):
    __qualname__ = 'DataStoreEventMap'

with sims4.reload.protected(globals()):
    data_store_event_test_event_callback_map = DataStoreEventMap()

class DataMapHandler:
    __qualname__ = 'DataMapHandler'

    def __init__(self, event_enum):
        self.event_enum = event_enum

    def __call__(self, func):
        callbacks = data_store_event_test_event_callback_map.get(self.event_enum)
        if callbacks is None:
            data_store_event_test_event_callback_map[self.event_enum] = [func.__name__]
        else:
            callbacks.append(func.__name__)
        return func

CONTENT_SET_GEN_PROCESS_HOUSEHOLD_EVENT_CACHE_GROUP = 'CONTENT_SET_GEN_PROCESS_HOUSEHOLD_EVENT_CACHE_GROUP'

@decorator
def cached_test(fn, **kwargs):
    return caches.cached(fn, **kwargs)

class EventManager(Service):
    __qualname__ = 'EventManager'

    def __init__(self):
        self._test_event_callback_map = collections.defaultdict(set)
        self._handlers_to_unregister_post_load = set()
        self._enabled = False

    def start(self):
        self._enabled = True
        for aspiration in services.get_instance_manager(sims4.resources.Types.ASPIRATION).types.values():
            while not aspiration.disabled:
                self.register_single_event(aspiration, TestEvent.UpdateObjectiveData)
                self._handlers_to_unregister_post_load.add(aspiration)
                if not aspiration.complete_only_in_sequence:
                    aspiration.register_callbacks()
        for achievement in services.get_instance_manager(sims4.resources.Types.ACHIEVEMENT).types.values():
            while not achievement.disabled:
                self.register_single_event(achievement, TestEvent.UpdateObjectiveData)
                self._handlers_to_unregister_post_load.add(achievement)
                achievement.register_callbacks()

    def disable_on_teardown(self):
        self._enabled = False

    def stop(self):
        self._test_event_callback_map = None
        self._handlers_to_unregister_post_load = None

    def _is_valid_handler(self, handler, event_types):
        if hasattr(handler, 'handle_event'):
            return True
        logger.error('Cannot register {} due to absence of expected callback method.  Registered event_types: {}.', handler, event_types, owner='manus')
        return False

    def register_tests(self, tuning_class_instance, tests):
        for test in tests:
            test_events = test.get_test_events_to_register()
            if test_events:
                self.register(tuning_class_instance, test_events)
            custom_keys = test.get_custom_event_registration_keys()
            for (test_event, custom_key) in custom_keys:
                self._register_with_custom_key(tuning_class_instance, test_event, custom_key)

    def unregister_tests(self, tuning_class_instance, tests):
        for test in tests:
            test_events = test.get_test_events_to_register()
            if test_events:
                self.unregister(tuning_class_instance, test_events)
            custom_keys = test.get_custom_event_registration_keys()
            for (test_event, custom_key) in custom_keys:
                self._unregister_with_custom_key(tuning_class_instance, test_event, custom_key)

    def register_single_event(self, handler, event_type):
        logger.assert_raise(self._enabled, 'Attempting to register event:{} \n            with handler:{} when the EventManager is disabled.', str(event_type), str(handler), owner='sscholl')
        self.register(handler, (event_type,))

    def register(self, handler, event_types):
        logger.assert_raise(self._enabled, 'Attempting to register events:{} \n            with handler:{} when the EventManager is disabled.', str(event_types), str(handler), owner='sscholl')
        if self._is_valid_handler(handler, event_types):
            for event in event_types:
                key = (event, None)
                self._test_event_callback_map[key].add(handler)

    def unregister_single_event(self, handler, event_type):
        self.unregister(handler, (event_type,))

    def unregister(self, handler, event_types):
        for event in event_types:
            key = (event, None)
            while handler in self._test_event_callback_map[key]:
                self._test_event_callback_map[key].remove(handler)

    def _register_with_custom_key(self, handler, event_type, custom_key):
        if self._is_valid_handler(handler, (event_type,)):
            key = (event_type, custom_key)
            self._test_event_callback_map[key].add(handler)

    def _unregister_with_custom_key(self, handler, event_type, custom_key):
        key = (event_type, custom_key)
        self._test_event_callback_map[key].remove(handler)

    def process_test_events_for_objective_updates(self, sim_info, init=True):
        if sim_info is None:
            return
        self._process_test_event(sim_info, TestEvent.UpdateObjectiveData, init=init)

    def unregister_unused_handlers(self):
        for handler in self._handlers_to_unregister_post_load:
            self.unregister_single_event(handler, TestEvent.UpdateObjectiveData)
        self._handlers_to_unregister_post_load = set()

    def process_event(self, event_type, sim_info=None, **kwargs):
        if not self._enabled:
            return
        caches.clear_all_caches()
        if sim_info is not None:
            callbacks = data_store_event_test_event_callback_map.get(event_type)
            if callbacks is not None:
                self._process_data_map_for_aspiration(sim_info, event_type, callbacks, **kwargs)
                self._process_data_map_for_achievement(sim_info, event_type, callbacks, **kwargs)
        self._process_test_event(sim_info, event_type, **kwargs)

    def process_events_for_household(self, event_type, household, exclude_sim=None, **kwargs):
        if not self._enabled:
            return
        if household is None:
            household = services.owning_household_of_active_lot()
        if household is None:
            return
        caches.clear_all_caches()
        with sims4.callback_utils.invoke_enter_exit_callbacks(CallbackEvent.ENTER_CONTENT_SET_GEN_OR_PROCESS_HOUSEHOLD_EVENTS, CallbackEvent.EXIT_CONTENT_SET_GEN_OR_PROCESS_HOUSEHOLD_EVENTS):
            callbacks = data_store_event_test_event_callback_map.get(event_type)
            has_not_triggered_achievment_data_object = True
            for sim_info in household._sim_infos:
                if sim_info == exclude_sim:
                    pass
                if callbacks is not None:
                    self._process_data_map_for_aspiration(sim_info, event_type, callbacks, **kwargs)
                if has_not_triggered_achievment_data_object:
                    if callbacks is not None:
                        self._process_data_map_for_achievement(sim_info, event_type, callbacks, **kwargs)
                    has_not_triggered_achievment_data_object = False
                self._process_test_event(sim_info, event_type, **kwargs)

    def _process_data_map_for_aspiration(self, sim_info, event_type, callbacks, **kwargs):
        data_object = sim_info.aspiration_tracker.data_object
        for function_name in callbacks:
            aspiration_function = getattr(data_object, function_name)
            aspiration_function(**kwargs)

    def _process_data_map_for_achievement(self, sim_info, event_type, callbacks, **kwargs):
        if not sim_info.is_selectable or sim_info.household.has_cheated:
            return
        data_object = sim_info.account.achievement_tracker.data_object
        for function_name in callbacks:
            achievement_function = getattr(data_object, function_name)
            achievement_function(**kwargs)

    def _update_call_counter(self, key):
        pass

    def _process_test_event(self, sim_info, event_type, custom_keys=tuple(), **kwargs):
        original_handlers = set()
        for custom_key in custom_keys:
            key = (event_type, custom_key)
            self._update_call_counter(key)
            handlers = self._test_event_callback_map.get(key)
            while handlers:
                original_handlers.update(handlers)
        key = (event_type, None)
        self._update_call_counter(key)
        handlers = self._test_event_callback_map.get(key)
        if handlers:
            original_handlers.update(handlers)
        if not original_handlers:
            return
        if sim_info is None:
            resolver = None
        else:
            resolver = event_testing.resolver.DataResolver(sim_info, event_kwargs=kwargs)
        tests_for_event = tuple(original_handlers)
        for test in tests_for_event:
            try:
                while test in original_handlers:
                    test.handle_event(sim_info, event_type, resolver)
            except Exception as e:
                logger.exception('Exception raised while trying to run a test event in test_events.py:', exc=e)

