import event_testing.results
import sims4.localization
import sims4.tuning.tunable

class BaseTest:
    __qualname__ = 'BaseTest'
    test_events = ()
    USES_DATA_OBJECT = False
    UNIQUE_TARGET_TRACKING_AVAILABLE = False
    UNIQUE_POSTURE_TRACKING_AVAILABLE = False
    TAG_CHECKLIST_TRACKING_AVAILABLE = False
    USES_EVENT_DATA = False
    FACTORY_TUNABLES = {'tooltip': sims4.tuning.tunable.OptionalTunable(sims4.localization.TunableLocalizedStringFactory(description='Reason of failure.'))}

    def __init__(self, *args, safe_to_skip=False, tooltip=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tooltip is not None or not hasattr(self, 'tooltip'):
            self.tooltip = tooltip
        self._safe_to_skip = safe_to_skip

    def has_tooltip(self):
        return self.tooltip is not None

    @property
    def safe_to_skip(self):
        return self._safe_to_skip

    def can_make_pass(self, **kwargs):
        if not self(**kwargs):
            return self._can_make_pass(**kwargs)
        return event_testing.results.TestResult(True, 'Test already passes.')

    def make_pass(self, **kwargs):
        if not self(**kwargs):
            return self._make_pass(**kwargs)
        return event_testing.results.TestResult(True, 'Test already passes.')

    def log_make_pass_action(self, message):
        import interactions.choices
        interactions.choices.logger.info(message)

    def _can_make_pass(self, **kwargs):
        return event_testing.results.TestResult(False, '{} does not support make pass.', type(self).__name__)

    def _make_pass(self, **kwargs):
        return self._can_make_pass(**kwargs)

    def get_target_id(self, **kwargs):
        pass

    def get_posture_id(self, **kwargs):
        pass

    def get_tags(self, **kwargs):
        return ()

    def save_relative_start_values(self, objective_guid64, data_object):
        pass

    def tuning_is_valid(self):
        return True

    def goal_value(self):
        return 1

    @property
    def is_goal_value_money(self):
        return False

    def get_test_events_to_register(self):
        return self.test_events

    def get_custom_event_registration_keys(self):
        return ()

