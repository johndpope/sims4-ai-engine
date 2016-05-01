import weakref
from date_and_time import TimeSpan
import date_and_time
import elements
import services
import sims4.reload
import sims4.log
logger = sims4.log.Logger('Alarms')
with sims4.reload.protected(globals()):
    _ALARM_ELEMENT_HANDLES = {}


def add_alarm(owner,
              time_span,
              callback,
              repeating=False,
              repeating_time_span=None,
              use_sleep_time=True):
    ts = services.time_service()
    if ts.sim_timeline is None:
        logger.error('Attempting to create alarm after TimeService shutdown.')
        return
    if use_sleep_time:
        initial_time = ts.sim_timeline.now
    else:
        initial_time = ts.sim_timeline.future
    return AlarmHandle(owner,
                       callback,
                       ts.sim_timeline,
                       initial_time + time_span,
                       repeating=repeating,
                       repeat_interval=repeating_time_span or time_span,
                       accurate_repeat=use_sleep_time)


def add_alarm_real_time(owner,
                        time_span,
                        callback,
                        repeating=False,
                        use_sleep_time=True):
    ts = services.time_service()
    return AlarmHandle(owner,
                       callback,
                       ts.wall_clock_timeline,
                       ts.wall_clock_timeline.now + time_span,
                       repeating=repeating,
                       repeat_interval=time_span,
                       accurate_repeat=use_sleep_time)


def cancel_alarm(handle):
    handle.cancel()


class AlarmHandle:
    __qualname__ = 'AlarmHandle'
    __slots__ = ('_element_handle', '_owner_ref', '__weakref__')

    def __init__(self,
                 owner,
                 callback,
                 t,
                 when,
                 repeating=False,
                 repeat_interval=None,
                 accurate_repeat=True):
        if owner is None:
            raise ValueError('Alarm created without owner')
        if not repeating:
            e = AlarmElement(callback)
        elif accurate_repeat:
            e = RepeatingAlarmElement(repeat_interval, callback)
        else:
            e = LossyRepeatingAlarmElement(repeat_interval, callback)
        self._element_handle = t.schedule(e, when)
        _register_auto_cleanup(self)
        self._owner_ref = weakref.ref(owner, self._owner_destroyed_callback)

    def _teardown(self):
        self._element_handle = None
        self._owner_ref = None

    @property
    def owner(self):
        if self._owner_ref is not None:
            return self._owner_ref()

    def _owner_destroyed_callback(self, _):
        if hasattr(self, '_element_handle'):
            self.cancel()

    def cancel(self):
        if self._element_handle is None:
            return
        _unregister_auto_cleanup(self._element_handle)
        timeline = self._element_handle.timeline
        if self._element_handle.is_active:
            self._element_handle._clear_element()
        else:
            timeline.hard_stop(self._element_handle)

    @property
    def timeline(self):
        return self._element_handle.timeline

    def get_remaining_time(self):
        timeline = self._element_handle.timeline
        when = self._element_handle.when
        if when is None:
            return TimeSpan.ZERO
        return when - timeline.now

    @property
    def finishing_time(self):
        when = self._element_handle.when
        if when is None:
            return date_and_time.DATE_AND_TIME_ZERO
        return when


class AlarmElement(elements.FunctionElement):
    __qualname__ = 'AlarmElement'
    __slots__ = ()

    @classmethod
    def shortname(cls):
        return 'Alarm'

    def __init__(self, callback):
        super().__init__(callback)

    def _run(self, t):
        result = self.callback(_lookup_alarm_handle(self._element_handle))
        _unregister_auto_cleanup(self._element_handle)
        return result

    def _teardown(self):
        alarm_handle = _lookup_alarm_handle(self._element_handle)
        if alarm_handle is not None:
            _unregister_auto_cleanup(self._element_handle)
            alarm_handle._teardown()
        super()._teardown()


class RepeatingAlarmElement(AlarmElement):
    __qualname__ = 'RepeatingAlarmElement'
    __slots__ = 'interval'

    @classmethod
    def shortname(cls):
        return 'RepeatingAlarm'

    def __init__(self, interval, callback):
        super().__init__(callback)
        self.interval = interval

    @staticmethod
    def timeline_now(t):
        return t.now

    def _run(self, t):
        element_handle = self._element_handle
        result = self.callback(_lookup_alarm_handle(element_handle))
        if not element_handle.canceled:
            when = self.timeline_now(t) + self.interval
            handle = t.schedule(self, when)
        return result

    def __str__(self):
        return '<{}; {}@{}; {}>'.format(
            self.shortname(), self.callback.__qualname__,
            self.callback.__code__.co_firstlineno, self.interval)


class LossyRepeatingAlarmElement(RepeatingAlarmElement):
    __qualname__ = 'LossyRepeatingAlarmElement'

    @staticmethod
    def timeline_now(t):
        return t.future


def _register_auto_cleanup(alarm_handle):
    element_handle = alarm_handle._element_handle

    def on_alarm_handle_collected(_):
        ehid = id(element_handle)
        if ehid in _ALARM_ELEMENT_HANDLES:
            del _ALARM_ELEMENT_HANDLES[ehid]
        timeline = element_handle.timeline
        timeline.hard_stop(element_handle)

    _ALARM_ELEMENT_HANDLES[id(element_handle)] = weakref.ref(
        alarm_handle, on_alarm_handle_collected)


def _unregister_auto_cleanup(element_handle):
    ehid = id(element_handle)
    if ehid in _ALARM_ELEMENT_HANDLES:
        del _ALARM_ELEMENT_HANDLES[ehid]


def _lookup_alarm_handle(element_handle):
    ehid = id(element_handle)
    return _ALARM_ELEMENT_HANDLES.get(ehid)()


def get_alarm_data_for_gsi():
    alarm_data = []
    for alarm_handle_ref in tuple(_ALARM_ELEMENT_HANDLES.values()):
        alarm_handle = alarm_handle_ref()
        if alarm_handle is None:
            pass
        element_handle = alarm_handle._element_handle
        element = element_handle.element
        if element is None:
            pass
        entry = {}
        entry['time'] = str(element_handle.when)
        entry['ticks'] = alarm_handle.get_remaining_time().in_ticks()
        entry['time_left'] = str(alarm_handle.get_remaining_time())
        owner = alarm_handle._owner_ref()
        if owner is None:
            owner_name = 'None Owner'
        else:
            owner_name = str(owner)
        entry['owner'] = owner_name
        entry['handle'] = id(alarm_handle)
        entry['callback'] = str(element.callback)
        alarm_data.append(entry)
    sort_key_fn = lambda data: data['ticks']
    alarm_data = sorted(alarm_data, key=sort_key_fn)
    return alarm_data
