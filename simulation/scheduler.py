import collections
import random
from date_and_time import TimeSpan
from sims4.tuning.tunable import TunableList, Tunable, TunableFactory, TunableReference, TunableSingletonFactory, AutoFactoryInit
from tunable_time import Days, TunableTimeOfDay
import alarms
import date_and_time
import services
import sims4.resources
logger = sims4.log.Logger('Scheduler')
AlarmData = collections.namedtuple('AlarmData', ('start_time', 'end_time', 'entry', 'is_random'))

def convert_string_to_enum(**day_availability_mapping):
    day_availability_dict = {}
    for day in Days:
        name = '{} {}'.format(int(day), day.name)
        available = day_availability_mapping[name]
        day_availability_dict[day] = available
    return day_availability_dict

class TunableAvailableDays(TunableSingletonFactory):
    __qualname__ = 'TunableAvailableDays'
    FACTORY_TYPE = staticmethod(convert_string_to_enum)

def TunableDayAvailability():
    day_availability_mapping = {}
    for day in Days:
        name = '{} {}'.format(int(day), day.name)
        day_availability_mapping[name] = Tunable(bool, False)
    day_availability = TunableAvailableDays(description='Which days of the week to include', **day_availability_mapping)
    return day_availability

class ScheduleEntry(AutoFactoryInit):
    __qualname__ = 'ScheduleEntry'
    FACTORY_TUNABLES = {'description': '\n            A map of days of the week to start time and duration.\n            ', 'days_available': TunableDayAvailability(), 'start_time': TunableTimeOfDay(default_hour=9), 'duration': Tunable(description='Duration of this work session in hours.', tunable_type=float, default=1.0), 'random_start': Tunable(bool, False, description='\n            If True, This schedule will have a random start time in the tuned window\n            each time.\n            ', needs_tuning=True)}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._start_and_end_times = set()
        for (day, day_enabled) in self.days_available.items():
            while day_enabled:
                days_as_time_span = date_and_time.create_time_span(days=day)
                start_time = self.start_time + days_as_time_span
                end_time = start_time + date_and_time.create_time_span(hours=self.duration)
                self._start_and_end_times.add((start_time, end_time))

    def get_start_and_end_times(self):
        return self._start_and_end_times

TunableScheduleEntry = TunableSingletonFactory.create_auto_factory(ScheduleEntry)

class WeeklySchedule:
    __qualname__ = 'WeeklySchedule'
    FACTORY_TUNABLES = {'description': '\n        A tunable to specify a weekly schedule.\n        ', 'schedule_entries': TunableList(description='\n            A list of event schedules. Each event is a mapping of days of\n            the week to a start_time and duration.\n            ', tunable=TunableScheduleEntry())}

    def __init__(self, schedule_entries, start_callback=None, schedule_immediate=True, min_alarm_time_span=None, min_duration_remaining=None, early_warning_callback=None, early_warning_time_span=None, extra_data=None, init_only=False):
        self._schedule_entires = set()
        for entry in schedule_entries:
            for (start_time, end_time) in entry.get_start_and_end_times():
                is_random = entry.random_start
                self._schedule_entires.add(AlarmData(start_time, end_time, entry, is_random))
        self._start_callback = start_callback
        self._alarm_handle = None
        self._random_alarm_handles = []
        self._alarm_data = {}
        self._min_alarm_time_span = min_alarm_time_span
        self.extra_data = extra_data
        self._early_warning_callback = early_warning_callback
        self._early_warning_time_span = early_warning_time_span
        self._early_warning_alarm_handle = None
        self._cooldown_time = None
        if not init_only:
            self._schedule_next_alarm(schedule_immediate=schedule_immediate, min_duration_remaining=min_duration_remaining)

    def _schedule_next_alarm(self, schedule_immediate=False, min_duration_remaining=None):
        now = services.time_service().sim_now
        (time_span, best_work_data) = self.time_until_next_scheduled_event(now, schedule_immediate=schedule_immediate, min_duration_remaining=min_duration_remaining)
        if self._min_alarm_time_span is not None and time_span < self._min_alarm_time_span:
            time_span = self._min_alarm_time_span
        if time_span == date_and_time.TimeSpan.ZERO and schedule_immediate:
            time_span = date_and_time.TimeSpan.ONE
        self._alarm_handle = alarms.add_alarm(self, time_span, self._alarm_callback)
        self._alarm_data[self._alarm_handle] = best_work_data
        if time_span is not None and (self._early_warning_callback is not None and self._early_warning_time_span is not None) and self._early_warning_time_span > date_and_time.TimeSpan.ZERO:
            warning_time_span = time_span - self._early_warning_time_span
            if warning_time_span > date_and_time.TimeSpan.ZERO:
                logger.assert_log(self._early_warning_alarm_handle is None, 'Scheduler is setting an early warning alarm when the previous one has not fired.', owner='tingyul')
                self._early_warning_alarm_handle = alarms.add_alarm(self, warning_time_span, self._early_warning_alarm_callback)

    def _random_alarm_callback(self, handle, alarm_data):
        self._random_alarm_handles.remove(handle)
        if not self.is_on_cooldown():
            self._start_callback(self, alarm_data, self.extra_data)

    def _early_warning_alarm_callback(self, handle, alarm_data=None):
        self._early_warning_alarm_handle = None
        self._early_warning_callback()

    def _alarm_callback(self, handle, alarm_datas=None):
        if alarm_datas is None:
            alarm_datas = self._alarm_data.pop(self._alarm_handle)
        if self._start_callback is not None:
            for alarm_data in alarm_datas:
                start_time = alarm_data.start_time
                end_time = alarm_data.end_time
                is_random = alarm_data.is_random
                if is_random:
                    cur_time_span = end_time - start_time
                    random_time_span = TimeSpan(random.randint(0, cur_time_span.in_ticks()))
                    random_callback = lambda handle: self._random_alarm_callback(handle, alarm_data)
                    cur_handle = alarms.add_alarm(self, random_time_span, random_callback)
                    self._random_alarm_handles.append(cur_handle)
                else:
                    self._start_callback(self, alarm_data, self.extra_data)
        self._schedule_next_alarm(schedule_immediate=False)

    def time_until_next_scheduled_event(self, current_date_and_time, schedule_immediate=False, min_duration_remaining=None):
        best_time = None
        best_work_data = []
        for alarm_data in self._schedule_entires:
            start_time = alarm_data.start_time
            end_time = alarm_data.end_time
            cur_time = current_date_and_time.time_till_timespan_of_week(start_time, optional_end_time=end_time if schedule_immediate else None, min_duration_remaining=min_duration_remaining)
            if best_time is None or cur_time < best_time:
                best_time = cur_time
                best_work_data = []
                best_work_data.append(alarm_data)
            else:
                while cur_time == best_time:
                    best_work_data.append(alarm_data)
        return (best_time, best_work_data)

    def add_cooldown(self, time_span):
        if self._cooldown_time is None:
            now = services.time_service().sim_now
            self._cooldown_time = now + time_span
        else:
            self._cooldown_time = self._cooldown_time + time_span

    def is_on_cooldown(self):
        if self._cooldown_time is None:
            return False
        now = services.time_service().sim_now
        if self._cooldown_time >= now:
            return True
        self._cooldown_time = None
        return False

    def get_schedule_times(self):
        busy_times = []
        for (start_time, end_time, _, _) in self._schedule_entires:
            busy_times.append((start_time.absolute_ticks(), end_time.absolute_ticks()))
        return busy_times

    def check_for_conflict(self, other_schedule):
        START = 0
        END = 1
        busy_times = self.get_schedule_times()
        other_busy_times = other_schedule.get_schedule_times()
        for this_time in busy_times:
            for other_time in other_busy_times:
                starting_time_delta = this_time[START] - other_time[START]
                if starting_time_delta >= 0:
                    earlier_career_duration = other_time[END] - other_time[START]
                else:
                    earlier_career_duration = this_time[END] - this_time[START]
                while earlier_career_duration >= abs(starting_time_delta):
                    return True
        return False

    def merge_schedule(self, other_schedule):
        pass

    def destroy(self):
        for alarm_handle in self._random_alarm_handles:
            alarms.cancel_alarm(alarm_handle)
        self._random_alarm_handles = []
        if self._alarm_handle is not None:
            alarms.cancel_alarm(self._alarm_handle)
            self._alarm_handle = None
        if self._early_warning_alarm_handle is not None:
            alarms.cancel_alarm(self._early_warning_alarm_handle)
            self._early_warning_alarm_handle = None
        self._alarm_data = {}

    def get_alarm_finishing_time(self):
        if self._alarm_handle is not None:
            return self._alarm_handle.finishing_time

TunableWeeklyScheduleFactory = TunableFactory.create_auto_factory(WeeklySchedule)

class SituationScheduleEntry(ScheduleEntry):
    __qualname__ = 'SituationScheduleEntry'
    FACTORY_TUNABLES = {'situation': TunableReference(description='\n            The situation to start according to the tuned schedule.', manager=services.get_instance_manager(sims4.resources.Types.SITUATION))}

TunableSituationScheduleEntry = TunableSingletonFactory.create_auto_factory(SituationScheduleEntry)

class SituationWeeklySchedule(WeeklySchedule):
    __qualname__ = 'SituationWeeklySchedule'
    FACTORY_TUNABLES = {'schedule_entries': TunableList(description='\n            A list of event schedules. Each event is a mapping of days of\n            the week to a start_time and duration.\n            ', tunable=TunableSituationScheduleEntry())}

TunableSituationWeeklyScheduleFactory = TunableFactory.create_auto_factory(SituationWeeklySchedule)
