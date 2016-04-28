from alarms import add_alarm, cancel_alarm
from sims4.service_manager import Service
from situations.service_npcs.modify_lot_items_tuning import ModifyAllLotItems
import date_and_time
import services
import tunable_time

class CleanupService(Service):
    __qualname__ = 'CleanupService'
    OPEN_STREET_CLEANUP_ACTIONS = ModifyAllLotItems.TunableFactory()
    OPEN_STREET_CLEANUP_TIME = tunable_time.TunableTimeOfDay(description='\n        What time of day the open street cleanup will occur.\n        ', default_hour=4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._alarm_handle = None

    def start(self):
        current_time = services.time_service().sim_now
        initial_time_span = current_time.time_till_next_day_time(self.OPEN_STREET_CLEANUP_TIME)
        repeating_time_span = date_and_time.create_time_span(days=1)
        self._alarm_handle = add_alarm(self, initial_time_span, self._on_update, repeating=True, repeating_time_span=repeating_time_span)

    def stop(self):
        if self._alarm_handle is not None:
            cancel_alarm(self._alarm_handle)
            self._alarm_handle = None

    def _on_update(self, _):
        cleanup = CleanupService.OPEN_STREET_CLEANUP_ACTIONS()
        cleanup.modify_objects_on_active_lot(modify_open_streets=True)

