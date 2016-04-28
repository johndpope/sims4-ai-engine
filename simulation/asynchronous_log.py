import alarms
import clock
import sims4.log

class AsynchronousLogger(sims4.log.LoggerClass):
    __qualname__ = 'AsynchronousLogger'
    __slots__ = ('_logqueue', '_auto_flush_time', '__weakref__')

    def __init__(self, group, auto_flush_time=None):
        super().__init__(group)
        self._logqueue = []
        self._auto_flush_time = auto_flush_time

    def _log(self, level, message, frame=sims4.log.DEFAULT):
        if not self._logqueue and self._auto_flush_time is not None:
            alarms.add_alarm_real_time(self, clock.interval_in_real_seconds(self._auto_flush_time), self.flush)
        self._logqueue.append((level, message, frame))

    def flush(self, handle=None):
        for (level, message, frame) in self._logqueue:
            super()._log(level, message, frame)
        del self._logqueue[:]

