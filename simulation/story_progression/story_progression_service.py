from sims4.service_manager import Service
from sims4.tuning.tunable import TunableList, TunableRealSecond
from story_progression import StoryProgressionFlags
from story_progression.actions import TunableStoryProgressionActionVariant
import alarms
import clock
import services
import sims4.log
import zone_types
import sims
logger = sims4.log.Logger('StoryProgression')

class StoryProgressionService(Service):
    __qualname__ = 'StoryProgressionService'
    INTERVAL = TunableRealSecond(description='\n        The time between Story Progression actions. A lower number will\n        impact performance.\n        ', default=5)
    ACTIONS = TunableList(description='\n        A list of actions that are available to Story Progression.\n        ', tunable=TunableStoryProgressionActionVariant())

    def __init__(self):
        self._sleep_handle = None
        self._processor = None
        self._alarm_handle = None
        self._next_action_index = 0
        self._story_progression_flags = StoryProgressionFlags.DISABLED

    def load_options(self, options_proto):
        if options_proto is None:
            return
        if options_proto.npc_population_enabled:
            pass

    def setup(self, save_slot_data=None, **kwargs):
        if save_slot_data is not None:
            sims.global_gender_preference_tuning.GlobalGenderPreferenceTuning.enable_autogeneration_same_sex_preference = save_slot_data.gameplay_data.enable_autogeneration_same_sex_preference

    def save(self, save_slot_data=None, **kwargs):
        if save_slot_data is not None:
            save_slot_data.gameplay_data.enable_autogeneration_same_sex_preference = sims.global_gender_preference_tuning.GlobalGenderPreferenceTuning.enable_autogeneration_same_sex_preference

    def enable_story_progression_flag(self, story_progression_flag):
        pass

    def disable_story_progression_flag(self, story_progression_flag):
        pass

    def is_story_progression_flag_enabled(self, story_progression_flag):
        return self._story_progression_flags & story_progression_flag

    def on_client_connect(self, client):
        current_zone = services.current_zone()
        current_zone.register_callback(zone_types.ZoneState.RUNNING, self._initialize_alarm)
        current_zone.register_callback(zone_types.ZoneState.SHUTDOWN_STARTED, self._on_zone_shutdown)

    def _on_zone_shutdown(self):
        current_zone = services.current_zone()
        if self._alarm_handle is not None:
            alarms.cancel_alarm(self._alarm_handle)
        current_zone.unregister_callback(zone_types.ZoneState.SHUTDOWN_STARTED, self._on_zone_shutdown)

    def _initialize_alarm(self):
        current_zone = services.current_zone()
        current_zone.unregister_callback(zone_types.ZoneState.RUNNING, self._initialize_alarm)
        time_span = clock.interval_in_sim_minutes(self.INTERVAL)
        self._alarm_handle = alarms.add_alarm(self, time_span, self._process_next_action, repeating=True)

    def _process_next_action(self, _):
        action = self.ACTIONS[self._next_action_index]
        logger.info('Attempt to Process - {}', action)
        if action.should_process(self._story_progression_flags):
            logger.info('Processing: {}', action)
            action.process_action(self._story_progression_flags)
            logger.info('Processing - Completed')
        else:
            logger.info('Attempt to Process - Skipped')
        if self._next_action_index >= len(self.ACTIONS):
            self._next_action_index = 0

