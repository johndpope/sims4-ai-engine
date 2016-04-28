from objects.components import Component, types
from objects.components.state import TunableStateTypeReference, TunableStateValueReference
from sims4.tuning.tunable import HasTunableFactory, TunableRange, TunableTuple, TunableMapping, TunableList
import alarms
import date_and_time
import services

class TimeOfDayComponent(Component, HasTunableFactory, component_name=types.TIME_OF_DAY_COMPONENT):
    __qualname__ = 'TimeOfDayComponent'
    DAILY_REPEAT = date_and_time.create_time_span(hours=24)
    FACTORY_TUNABLES = {'state_changes': TunableMapping(description='\n            A mapping from state to times of the day when the state should be \n            set to a tuned value.\n            ', key_type=TunableStateTypeReference(description='The state to be set.'), value_type=TunableList(description='List of times to modify the state at.', tunable=TunableTuple(start_time=TunableRange(float, 0, description='The start time (24 hour clock time) for the Day_Time state.', minimum=0, maximum=24), value=TunableStateValueReference(description='New state value.'))))}

    def __init__(self, owner, *, state_changes):
        super().__init__(owner)
        self.state_changes = state_changes
        self.alarm_handles = []

    def _add_alarm(self, cur_state, game_clock, state, change):
        time_to_day = game_clock.time_until_hour_of_day(change.start_time)

        def change_state(_):
            self.owner.set_state(state, change.value)

        self.alarm_handles.append(alarms.add_alarm(self.owner, time_to_day, change_state, repeating=True, repeating_time_span=self.DAILY_REPEAT))
        if cur_state is None or time_to_day > cur_state[0]:
            return (time_to_day, change.value)
        return cur_state

    def on_add(self):
        game_clock_service = services.game_clock_service()
        for (state, changes) in self.state_changes.items():
            current_state = None
            for change in changes:
                current_state = self._add_alarm(current_state, game_clock_service, state, change)
            while current_state is not None:
                self.owner.set_state(state, current_state[1])

    def on_remove(self):
        for handle in self.alarm_handles:
            alarms.cancel_alarm(handle)

