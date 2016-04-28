import time
import heapq
from collections import namedtuple
try:
    import threading
except ImportError:
    import dummy_threading as threading
try:
    from time import monotonic as _time
except ImportError:
    from time import time as _time
__all__ = ['scheduler']

class Event(namedtuple('Event', 'time, priority, action, argument, kwargs')):
    __qualname__ = 'Event'

    def __eq__(s, o):
        return (s.time, s.priority) == (o.time, o.priority)

    def __ne__(s, o):
        return (s.time, s.priority) != (o.time, o.priority)

    def __lt__(s, o):
        return (s.time, s.priority) < (o.time, o.priority)

    def __le__(s, o):
        return (s.time, s.priority) <= (o.time, o.priority)

    def __gt__(s, o):
        return (s.time, s.priority) > (o.time, o.priority)

    def __ge__(s, o):
        return (s.time, s.priority) >= (o.time, o.priority)

_sentinel = object()

class scheduler:
    __qualname__ = 'scheduler'

    def __init__(self, timefunc=_time, delayfunc=time.sleep):
        self._queue = []
        self._lock = threading.RLock()
        self.timefunc = timefunc
        self.delayfunc = delayfunc

    def enterabs(self, time, priority, action, argument=(), kwargs=_sentinel):
        if kwargs is _sentinel:
            kwargs = {}
        with self._lock:
            event = Event(time, priority, action, argument, kwargs)
            heapq.heappush(self._queue, event)
            return event

    def enter(self, delay, priority, action, argument=(), kwargs=_sentinel):
        with self._lock:
            time = self.timefunc() + delay
            return self.enterabs(time, priority, action, argument, kwargs)

    def cancel(self, event):
        with self._lock:
            self._queue.remove(event)
            heapq.heapify(self._queue)

    def empty(self):
        with self._lock:
            return not self._queue

    def run(self, blocking=True):
        lock = self._lock
        q = self._queue
        delayfunc = self.delayfunc
        timefunc = self.timefunc
        pop = heapq.heappop
        while True:
            with lock:
                if not q:
                    break
                (time, priority, action, argument, kwargs) = q[0]
                now = timefunc()
                if time > now:
                    delay = True
                else:
                    delay = False
                    pop(q)
            if delay:
                if not blocking:
                    return time - now
                delayfunc(time - now)
            else:
                action(*argument, **kwargs)
                delayfunc(0)

    @property
    def queue(self):
        with self._lock:
            events = self._queue[:]
            return list(map(heapq.heappop, [events]*len(events)))

