import sys as _sys
import _thread
from time import sleep as _sleep
try:
    from time import monotonic as _time
except ImportError:
    from time import time as _time
from traceback import format_exc as _format_exc
from _weakrefset import WeakSet
__all__ = ['active_count', 'Condition', 'current_thread', 'enumerate', 'Event', 'Lock', 'RLock', 'Semaphore', 'BoundedSemaphore', 'Thread', 'Barrier', 'Timer', 'ThreadError', 'setprofile', 'settrace', 'local', 'stack_size']
_start_new_thread = _thread.start_new_thread
_allocate_lock = _thread.allocate_lock
get_ident = _thread.get_ident
ThreadError = _thread.error
try:
    _CRLock = _thread.RLock
except AttributeError:
    _CRLock = None
TIMEOUT_MAX = _thread.TIMEOUT_MAX
del _thread
_profile_hook = None
_trace_hook = None

def setprofile(func):
    global _profile_hook
    _profile_hook = func

def settrace(func):
    global _trace_hook
    _trace_hook = func

Lock = _allocate_lock

def RLock(*args, **kwargs):
    if _CRLock is None:
        return _PyRLock(*args, **kwargs)
    return _CRLock(*args, **kwargs)

class _RLock:
    __qualname__ = '_RLock'

    def __init__(self):
        self._block = _allocate_lock()
        self._owner = None
        self._count = 0

    def __repr__(self):
        owner = self._owner
        try:
            owner = _active[owner].name
        except KeyError:
            pass
        return '<%s owner=%r count=%d>' % (self.__class__.__name__, owner, self._count)

    def acquire(self, blocking=True, timeout=-1):
        me = get_ident()
        if self._owner == me:
            self._count = self._count + 1
            return 1
        rc = self._block.acquire(blocking, timeout)
        if rc:
            self._owner = me
            self._count = 1
        return rc

    __enter__ = acquire

    def release(self):
        if self._owner != get_ident():
            raise RuntimeError('cannot release un-acquired lock')
        self._count = count = self._count - 1
        if not count:
            self._owner = None
            self._block.release()

    def __exit__(self, t, v, tb):
        self.release()

    def _acquire_restore(self, state):
        self._block.acquire()
        (self._count, self._owner) = state

    def _release_save(self):
        if self._count == 0:
            raise RuntimeError('cannot release un-acquired lock')
        count = self._count
        self._count = 0
        owner = self._owner
        self._owner = None
        self._block.release()
        return (count, owner)

    def _is_owned(self):
        return self._owner == get_ident()

_PyRLock = _RLock

class Condition:
    __qualname__ = 'Condition'

    def __init__(self, lock=None):
        if lock is None:
            lock = RLock()
        self._lock = lock
        self.acquire = lock.acquire
        self.release = lock.release
        try:
            self._release_save = lock._release_save
        except AttributeError:
            pass
        try:
            self._acquire_restore = lock._acquire_restore
        except AttributeError:
            pass
        try:
            self._is_owned = lock._is_owned
        except AttributeError:
            pass
        self._waiters = []

    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, *args):
        return self._lock.__exit__(*args)

    def __repr__(self):
        return '<Condition(%s, %d)>' % (self._lock, len(self._waiters))

    def _release_save(self):
        self._lock.release()

    def _acquire_restore(self, x):
        self._lock.acquire()

    def _is_owned(self):
        if self._lock.acquire(0):
            self._lock.release()
            return False
        return True

    def wait(self, timeout=None):
        if not self._is_owned():
            raise RuntimeError('cannot wait on un-acquired lock')
        waiter = _allocate_lock()
        waiter.acquire()
        self._waiters.append(waiter)
        saved_state = self._release_save()
        try:
            if timeout is None:
                waiter.acquire()
                gotit = True
            else:
                if timeout > 0:
                    gotit = waiter.acquire(True, timeout)
                else:
                    gotit = waiter.acquire(False)
                if not gotit:
                    try:
                        self._waiters.remove(waiter)
                    except ValueError:
                        pass
            return gotit
        finally:
            self._acquire_restore(saved_state)

    def wait_for(self, predicate, timeout=None):
        endtime = None
        waittime = timeout
        result = predicate()
        while not result:
            if waittime is not None:
                if endtime is None:
                    endtime = _time() + waittime
                else:
                    waittime = endtime - _time()
                    if waittime <= 0:
                        break
            self.wait(waittime)
            result = predicate()
        return result

    def notify(self, n=1):
        if not self._is_owned():
            raise RuntimeError('cannot notify on un-acquired lock')
        _Condition__waiters = self._waiters
        waiters = _Condition__waiters[:n]
        if not waiters:
            return
        for waiter in waiters:
            waiter.release()
            try:
                _Condition__waiters.remove(waiter)
            except ValueError:
                pass

    def notify_all(self):
        self.notify(len(self._waiters))

    notifyAll = notify_all

class Semaphore:
    __qualname__ = 'Semaphore'

    def __init__(self, value=1):
        if value < 0:
            raise ValueError('semaphore initial value must be >= 0')
        self._cond = Condition(Lock())
        self._value = value

    def acquire(self, blocking=True, timeout=None):
        if not blocking and timeout is not None:
            raise ValueError("can't specify timeout for non-blocking acquire")
        rc = False
        endtime = None
        with self._cond:
            if not blocking:
                break
            if timeout is not None:
                if endtime is None:
                    endtime = _time() + timeout
                else:
                    timeout = endtime - _time()
                    if timeout <= 0:
                        break
            self._cond.wait(timeout)
            self._value = self._value - 1
            rc = True
        return rc

    __enter__ = acquire

    def release(self):
        with self._cond:
            self._value = self._value + 1
            self._cond.notify()

    def __exit__(self, t, v, tb):
        self.release()

class BoundedSemaphore(Semaphore):
    __qualname__ = 'BoundedSemaphore'

    def __init__(self, value=1):
        Semaphore.__init__(self, value)
        self._initial_value = value

    def release(self):
        with self._cond:
            if self._value >= self._initial_value:
                raise ValueError('Semaphore released too many times')
            self._cond.notify()

class Event:
    __qualname__ = 'Event'

    def __init__(self):
        self._cond = Condition(Lock())
        self._flag = False

    def _reset_internal_locks(self):
        self._cond.__init__()

    def is_set(self):
        return self._flag

    isSet = is_set

    def set(self):
        self._cond.acquire()
        try:
            self._flag = True
            self._cond.notify_all()
        finally:
            self._cond.release()

    def clear(self):
        self._cond.acquire()
        try:
            self._flag = False
        finally:
            self._cond.release()

    def wait(self, timeout=None):
        self._cond.acquire()
        try:
            signaled = self._flag
            if not signaled:
                signaled = self._cond.wait(timeout)
            return signaled
        finally:
            self._cond.release()

class Barrier:
    __qualname__ = 'Barrier'

    def __init__(self, parties, action=None, timeout=None):
        self._cond = Condition(Lock())
        self._action = action
        self._timeout = timeout
        self._parties = parties
        self._state = 0
        self._count = 0

    def wait(self, timeout=None):
        if timeout is None:
            timeout = self._timeout
        with self._cond:
            self._enter()
            index = self._count
            try:
                if index + 1 == self._parties:
                    self._release()
                else:
                    self._wait(timeout)
                return index
            finally:
                self._exit()

    def _enter(self):
        while self._state in (-1, 1):
            self._cond.wait()
        if self._state < 0:
            raise BrokenBarrierError

    def _release(self):
        try:
            if self._action:
                self._action()
            self._state = 1
            self._cond.notify_all()
        except:
            self._break()
            raise

    def _wait(self, timeout):
        if not self._cond.wait_for(lambda : self._state != 0, timeout):
            self._break()
            raise BrokenBarrierError
        if self._state < 0:
            raise BrokenBarrierError

    def _exit(self):
        if self._count == 0 and self._state in (-1, 1):
            self._state = 0
            self._cond.notify_all()

    def reset(self):
        with self._cond:
            if self._count > 0:
                if self._state == 0:
                    self._state = -1
                else:
                    self._state = -1
            else:
                self._state = 0
            self._cond.notify_all()

    def abort(self):
        with self._cond:
            self._break()

    def _break(self):
        self._state = -2
        self._cond.notify_all()

    @property
    def parties(self):
        return self._parties

    @property
    def n_waiting(self):
        if self._state == 0:
            return self._count
        return 0

    @property
    def broken(self):
        return self._state == -2

class BrokenBarrierError(RuntimeError):
    __qualname__ = 'BrokenBarrierError'

_counter = 0

def _newname(template='Thread-%d'):
    global _counter
    _counter = _counter + 1
    return template % _counter

_active_limbo_lock = _allocate_lock()
_active = {}
_limbo = {}
_dangling = WeakSet()

class Thread:
    __qualname__ = 'Thread'
    _Thread__initialized = False
    _Thread__exc_info = _sys.exc_info

    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None, *, daemon=None):
        if kwargs is None:
            kwargs = {}
        self._target = target
        self._name = str(name or _newname())
        self._args = args
        self._kwargs = kwargs
        if daemon is not None:
            self._daemonic = daemon
        else:
            self._daemonic = current_thread().daemon
        self._ident = None
        self._started = Event()
        self._stopped = False
        self._block = Condition(Lock())
        self._initialized = True
        self._stderr = _sys.stderr
        _dangling.add(self)

    def _reset_internal_locks(self):
        if hasattr(self, '_block'):
            self._block.__init__()
        self._started._reset_internal_locks()

    def __repr__(self):
        status = 'initial'
        if self._started.is_set():
            status = 'started'
        if self._stopped:
            status = 'stopped'
        if self._daemonic:
            status += ' daemon'
        if self._ident is not None:
            status += ' %s' % self._ident
        return '<%s(%s, %s)>' % (self.__class__.__name__, self._name, status)

    def start(self):
        if not self._initialized:
            raise RuntimeError('thread.__init__() not called')
        if self._started.is_set():
            raise RuntimeError('threads can only be started once')
        with _active_limbo_lock:
            _limbo[self] = self
        try:
            _start_new_thread(self._bootstrap, ())
        except Exception:
            with _active_limbo_lock:
                del _limbo[self]
            raise
        self._started.wait()

    def run(self):
        try:
            while self._target:
                self._target(*self._args, **self._kwargs)
        finally:
            del self._target
            del self._args
            del self._kwargs

    def _bootstrap(self):
        try:
            self._bootstrap_inner()
        except:
            if self._daemonic and _sys is None:
                return
            raise

    def _set_ident(self):
        self._ident = get_ident()

    def _bootstrap_inner(self):
        try:
            self._set_ident()
            self._started.set()
            with _active_limbo_lock:
                _active[self._ident] = self
                del _limbo[self]
            if _trace_hook:
                _sys.settrace(_trace_hook)
            if _profile_hook:
                _sys.setprofile(_profile_hook)
            try:
                self.run()
            except SystemExit:
                pass
            except:
                if _sys:
                    _sys.stderr.write('Exception in thread %s:\n%s\n' % (self.name, _format_exc()))
                else:
                    (exc_type, exc_value, exc_tb) = self._exc_info()
                    try:
                        print('Exception in thread ' + self.name + ' (most likely raised during interpreter shutdown):', file=self._stderr)
                        print('Traceback (most recent call last):', file=self._stderr)
                        while exc_tb:
                            print('  File "%s", line %s, in %s' % (exc_tb.tb_frame.f_code.co_filename, exc_tb.tb_lineno, exc_tb.tb_frame.f_code.co_name), file=self._stderr)
                            exc_tb = exc_tb.tb_next
                        print('%s: %s' % (exc_type, exc_value), file=self._stderr)
                    finally:
                        del exc_type
                        del exc_value
                        del exc_tb
            finally:
                pass
        finally:
            with _active_limbo_lock:
                self._stop()
                try:
                    del _active[get_ident()]
                except:
                    pass

    def _stop(self):
        self._block.acquire()
        self._stopped = True
        self._block.notify_all()
        self._block.release()

    def _delete(self):
        try:
            with _active_limbo_lock:
                del _active[get_ident()]
        except KeyError:
            if 'dummy_threading' not in _sys.modules:
                raise

    def join(self, timeout=None):
        if not self._initialized:
            raise RuntimeError('Thread.__init__() not called')
        if not self._started.is_set():
            raise RuntimeError('cannot join thread before it is started')
        if self is current_thread():
            raise RuntimeError('cannot join current thread')
        self._block.acquire()
        try:
            if timeout is None:
                while not self._stopped:
                    self._block.wait()
                    continue
            else:
                deadline = _time() + timeout
                while not self._stopped:
                    delay = deadline - _time()
                    if delay <= 0:
                        break
                    self._block.wait(delay)
        finally:
            self._block.release()

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, name):
        self._name = str(name)

    @property
    def ident(self):
        return self._ident

    def is_alive(self):
        return self._started.is_set() and not self._stopped

    isAlive = is_alive

    @property
    def daemon(self):
        return self._daemonic

    @daemon.setter
    def daemon(self, daemonic):
        if not self._initialized:
            raise RuntimeError('Thread.__init__() not called')
        if self._started.is_set():
            raise RuntimeError('cannot set daemon status of active thread')
        self._daemonic = daemonic

    def isDaemon(self):
        return self.daemon

    def setDaemon(self, daemonic):
        self.daemon = daemonic

    def getName(self):
        return self.name

    def setName(self, name):
        self.name = name

class Timer(Thread):
    __qualname__ = 'Timer'

    def __init__(self, interval, function, args=None, kwargs=None):
        Thread.__init__(self)
        self.interval = interval
        self.function = function
        self.args = args if args is not None else []
        self.kwargs = kwargs if kwargs is not None else {}
        self.finished = Event()

    def cancel(self):
        self.finished.set()

    def run(self):
        self.finished.wait(self.interval)
        if not self.finished.is_set():
            self.function(*self.args, **self.kwargs)
        self.finished.set()

class _MainThread(Thread):
    __qualname__ = '_MainThread'

    def __init__(self):
        Thread.__init__(self, name='MainThread', daemon=False)
        self._started.set()
        self._set_ident()
        with _active_limbo_lock:
            _active[self._ident] = self

    def _exitfunc(self):
        self._stop()
        t = _pickSomeNonDaemonThread()
        while t:
            t.join()
            t = _pickSomeNonDaemonThread()
        self._delete()

def _pickSomeNonDaemonThread():
    for t in enumerate():
        while not t.daemon and t.is_alive():
            return t

class _DummyThread(Thread):
    __qualname__ = '_DummyThread'

    def __init__(self):
        Thread.__init__(self, name=_newname('Dummy-%d'), daemon=True)
        del self._block
        self._started.set()
        self._set_ident()
        with _active_limbo_lock:
            _active[self._ident] = self

    def _stop(self):
        pass

    def join(self, timeout=None):
        pass

def current_thread():
    try:
        return _active[get_ident()]
    except KeyError:
        return _DummyThread()

currentThread = current_thread

def active_count():
    with _active_limbo_lock:
        return len(_active) + len(_limbo)

activeCount = active_count

def _enumerate():
    return list(_active.values()) + list(_limbo.values())

def enumerate():
    with _active_limbo_lock:
        return list(_active.values()) + list(_limbo.values())

from _thread import stack_size
_shutdown = _MainThread()._exitfunc
try:
    from _thread import _local as local
except ImportError:
    from _threading_local import local

def _after_fork():
    global _active_limbo_lock
    _active_limbo_lock = _allocate_lock()
    new_active = {}
    current = current_thread()
    with _active_limbo_lock:
        for thread in _enumerate():
            thread._reset_internal_locks()
            if thread is current:
                ident = get_ident()
                thread._ident = ident
                new_active[ident] = thread
            else:
                thread._stop()
        _limbo.clear()
        _active.clear()
        _active.update(new_active)

