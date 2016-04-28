__author__ = 'Brian Quinlan (brian@sweetapp.com)'
import collections
import logging
import threading
import time
FIRST_COMPLETED = 'FIRST_COMPLETED'
FIRST_EXCEPTION = 'FIRST_EXCEPTION'
ALL_COMPLETED = 'ALL_COMPLETED'
_AS_COMPLETED = '_AS_COMPLETED'
PENDING = 'PENDING'
RUNNING = 'RUNNING'
CANCELLED = 'CANCELLED'
CANCELLED_AND_NOTIFIED = 'CANCELLED_AND_NOTIFIED'
FINISHED = 'FINISHED'
_FUTURE_STATES = [PENDING, RUNNING, CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED]
_STATE_TO_DESCRIPTION_MAP = {PENDING: 'pending', RUNNING: 'running', CANCELLED: 'cancelled', CANCELLED_AND_NOTIFIED: 'cancelled', FINISHED: 'finished'}
LOGGER = logging.getLogger('concurrent.futures')

class Error(Exception):
    __qualname__ = 'Error'

class CancelledError(Error):
    __qualname__ = 'CancelledError'

class TimeoutError(Error):
    __qualname__ = 'TimeoutError'

class _Waiter(object):
    __qualname__ = '_Waiter'

    def __init__(self):
        self.event = threading.Event()
        self.finished_futures = []

    def add_result(self, future):
        self.finished_futures.append(future)

    def add_exception(self, future):
        self.finished_futures.append(future)

    def add_cancelled(self, future):
        self.finished_futures.append(future)

class _AsCompletedWaiter(_Waiter):
    __qualname__ = '_AsCompletedWaiter'

    def __init__(self):
        super(_AsCompletedWaiter, self).__init__()
        self.lock = threading.Lock()

    def add_result(self, future):
        with self.lock:
            super(_AsCompletedWaiter, self).add_result(future)
            self.event.set()

    def add_exception(self, future):
        with self.lock:
            super(_AsCompletedWaiter, self).add_exception(future)
            self.event.set()

    def add_cancelled(self, future):
        with self.lock:
            super(_AsCompletedWaiter, self).add_cancelled(future)
            self.event.set()

class _FirstCompletedWaiter(_Waiter):
    __qualname__ = '_FirstCompletedWaiter'

    def add_result(self, future):
        super().add_result(future)
        self.event.set()

    def add_exception(self, future):
        super().add_exception(future)
        self.event.set()

    def add_cancelled(self, future):
        super().add_cancelled(future)
        self.event.set()

class _AllCompletedWaiter(_Waiter):
    __qualname__ = '_AllCompletedWaiter'

    def __init__(self, num_pending_calls, stop_on_exception):
        self.num_pending_calls = num_pending_calls
        self.stop_on_exception = stop_on_exception
        self.lock = threading.Lock()
        super().__init__()

    def _decrement_pending_calls(self):
        with self.lock:
            while not self.num_pending_calls:
                self.event.set()

    def add_result(self, future):
        super().add_result(future)
        self._decrement_pending_calls()

    def add_exception(self, future):
        super().add_exception(future)
        if self.stop_on_exception:
            self.event.set()
        else:
            self._decrement_pending_calls()

    def add_cancelled(self, future):
        super().add_cancelled(future)
        self._decrement_pending_calls()

class _AcquireFutures(object):
    __qualname__ = '_AcquireFutures'

    def __init__(self, futures):
        self.futures = sorted(futures, key=id)

    def __enter__(self):
        for future in self.futures:
            future._condition.acquire()

    def __exit__(self, *args):
        for future in self.futures:
            future._condition.release()

def _create_and_install_waiters(fs, return_when):
    if return_when == _AS_COMPLETED:
        waiter = _AsCompletedWaiter()
    elif return_when == FIRST_COMPLETED:
        waiter = _FirstCompletedWaiter()
    else:
        pending_count = sum(f._state not in [CANCELLED_AND_NOTIFIED, FINISHED] for f in fs)
        if return_when == FIRST_EXCEPTION:
            waiter = _AllCompletedWaiter(pending_count, stop_on_exception=True)
        elif return_when == ALL_COMPLETED:
            waiter = _AllCompletedWaiter(pending_count, stop_on_exception=False)
        else:
            raise ValueError('Invalid return condition: %r' % return_when)
    for f in fs:
        f._waiters.append(waiter)
    return waiter

def as_completed(fs, timeout=None):
    if timeout is not None:
        end_time = timeout + time.time()
    fs = set(fs)
    with _AcquireFutures(fs):
        finished = set(f for f in fs if f._state in [CANCELLED_AND_NOTIFIED, FINISHED])
        pending = fs - finished
        waiter = _create_and_install_waiters(fs, _AS_COMPLETED)
    try:
        for future in finished:
            yield future
        while pending:
            if timeout is None:
                wait_timeout = None
            else:
                wait_timeout = end_time - time.time()
                if wait_timeout < 0:
                    raise TimeoutError('%d (of %d) futures unfinished' % (len(pending), len(fs)))
            waiter.event.wait(wait_timeout)
            with waiter.lock:
                finished = waiter.finished_futures
                waiter.finished_futures = []
                waiter.event.clear()
            for future in finished:
                yield future
                pending.remove(future)
    finally:
        for f in fs:
            f._waiters.remove(waiter)

DoneAndNotDoneFutures = collections.namedtuple('DoneAndNotDoneFutures', 'done not_done')

def wait(fs, timeout=None, return_when=ALL_COMPLETED):
    with _AcquireFutures(fs):
        done = set(f for f in fs if f._state in [CANCELLED_AND_NOTIFIED, FINISHED])
        not_done = set(fs) - done
        if return_when == FIRST_COMPLETED and done:
            return DoneAndNotDoneFutures(done, not_done)
        if return_when == FIRST_EXCEPTION and done and any(f for f in done if not f.cancelled() and f.exception() is not None):
            return DoneAndNotDoneFutures(done, not_done)
        if len(done) == len(fs):
            return DoneAndNotDoneFutures(done, not_done)
        waiter = _create_and_install_waiters(fs, return_when)
    waiter.event.wait(timeout)
    for f in fs:
        f._waiters.remove(waiter)
    done.update(waiter.finished_futures)
    return DoneAndNotDoneFutures(done, set(fs) - done)

class Future(object):
    __qualname__ = 'Future'

    def __init__(self):
        self._condition = threading.Condition()
        self._state = PENDING
        self._result = None
        self._exception = None
        self._waiters = []
        self._done_callbacks = []

    def _invoke_callbacks(self):
        for callback in self._done_callbacks:
            try:
                callback(self)
            except Exception:
                LOGGER.exception('exception calling callback for %r', self)

    def __repr__(self):
        with self._condition:
            if self._state == FINISHED:
                if self._exception:
                    return '<Future at %s state=%s raised %s>' % (hex(id(self)), _STATE_TO_DESCRIPTION_MAP[self._state], self._exception.__class__.__name__)
                return '<Future at %s state=%s returned %s>' % (hex(id(self)), _STATE_TO_DESCRIPTION_MAP[self._state], self._result.__class__.__name__)
            return '<Future at %s state=%s>' % (hex(id(self)), _STATE_TO_DESCRIPTION_MAP[self._state])

    def cancel(self):
        with self._condition:
            if self._state in [RUNNING, FINISHED]:
                return False
            if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                return True
            self._state = CANCELLED
            self._condition.notify_all()
        self._invoke_callbacks()
        return True

    def cancelled(self):
        with self._condition:
            return self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]

    def running(self):
        with self._condition:
            return self._state == RUNNING

    def done(self):
        with self._condition:
            return self._state in [CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED]

    def __get_result(self):
        if self._exception:
            raise self._exception
        else:
            return self._result

    def add_done_callback(self, fn):
        with self._condition:
            if self._state not in [CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED]:
                self._done_callbacks.append(fn)
                return
        fn(self)

    def result(self, timeout=None):
        with self._condition:
            if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                raise CancelledError()
            elif self._state == FINISHED:
                return self._Future__get_result()
            self._condition.wait(timeout)
            if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                raise CancelledError()
            else:
                if self._state == FINISHED:
                    return self._Future__get_result()
                raise TimeoutError()

    def exception(self, timeout=None):
        with self._condition:
            if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                raise CancelledError()
            elif self._state == FINISHED:
                return self._exception
            self._condition.wait(timeout)
            if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                raise CancelledError()
            else:
                if self._state == FINISHED:
                    return self._exception
                raise TimeoutError()

    def set_running_or_notify_cancel(self):
        with self._condition:
            if self._state == CANCELLED:
                self._state = CANCELLED_AND_NOTIFIED
                for waiter in self._waiters:
                    waiter.add_cancelled(self)
                return False
            if self._state == PENDING:
                self._state = RUNNING
                return True
            LOGGER.critical('Future %s in unexpected state: %s', id(self), self._state)
            raise RuntimeError('Future in unexpected state')

    def set_result(self, result):
        with self._condition:
            self._result = result
            self._state = FINISHED
            for waiter in self._waiters:
                waiter.add_result(self)
            self._condition.notify_all()
        self._invoke_callbacks()

    def set_exception(self, exception):
        with self._condition:
            self._exception = exception
            self._state = FINISHED
            for waiter in self._waiters:
                waiter.add_exception(self)
            self._condition.notify_all()
        self._invoke_callbacks()

class Executor(object):
    __qualname__ = 'Executor'

    def submit(self, fn, *args, **kwargs):
        raise NotImplementedError()

    def map(self, fn, *iterables, timeout=None):
        if timeout is not None:
            end_time = timeout + time.time()
        fs = [self.submit(fn, *args) for args in zip(*iterables)]

        def result_iterator():
            try:
                for future in fs:
                    if timeout is None:
                        yield future.result()
                    else:
                        yield future.result(end_time - time.time())
            finally:
                for future in fs:
                    future.cancel()

        return result_iterator()

    def shutdown(self, wait=True):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown(wait=True)
        return False

