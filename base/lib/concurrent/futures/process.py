__author__ = 'Brian Quinlan (brian@sweetapp.com)'
import atexit
import os
from concurrent.futures import _base
import queue
import multiprocessing
from multiprocessing.queues import SimpleQueue, Full
from multiprocessing.connection import wait
import threading
import weakref
_threads_queues = weakref.WeakKeyDictionary()
_shutdown = False

def _python_exit():
    global _shutdown
    _shutdown = True
    items = list(_threads_queues.items())
    for (t, q) in items:
        q.put(None)
    for (t, q) in items:
        t.join()

EXTRA_QUEUED_CALLS = 1

class _WorkItem(object):
    __qualname__ = '_WorkItem'

    def __init__(self, future, fn, args, kwargs):
        self.future = future
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

class _ResultItem(object):
    __qualname__ = '_ResultItem'

    def __init__(self, work_id, exception=None, result=None):
        self.work_id = work_id
        self.exception = exception
        self.result = result

class _CallItem(object):
    __qualname__ = '_CallItem'

    def __init__(self, work_id, fn, args, kwargs):
        self.work_id = work_id
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

def _process_worker(call_queue, result_queue):
    while True:
        call_item = call_queue.get(block=True)
        if call_item is None:
            result_queue.put(os.getpid())
            return
        try:
            r = call_item.fn(*call_item.args, **call_item.kwargs)
        except BaseException as e:
            result_queue.put(_ResultItem(call_item.work_id, exception=e))
        result_queue.put(_ResultItem(call_item.work_id, result=r))

def _add_call_item_to_queue(pending_work_items, work_ids, call_queue):
    while True:
        if call_queue.full():
            return
        try:
            work_id = work_ids.get(block=False)
        except queue.Empty:
            return
        work_item = pending_work_items[work_id]
        if work_item.future.set_running_or_notify_cancel():
            call_queue.put(_CallItem(work_id, work_item.fn, work_item.args, work_item.kwargs), block=True)
        else:
            del pending_work_items[work_id]
            continue

def _queue_management_worker(executor_reference, processes, pending_work_items, work_ids_queue, call_queue, result_queue):
    executor = None

    def shutting_down():
        return _shutdown or (executor is None or executor._shutdown_thread)

    def shutdown_worker():
        nb_children_alive = sum(p.is_alive() for p in processes.values())
        for i in range(0, nb_children_alive):
            call_queue.put_nowait(None)
        call_queue.close()
        for p in processes.values():
            p.join()

    reader = result_queue._reader
    while True:
        _add_call_item_to_queue(pending_work_items, work_ids_queue, call_queue)
        sentinels = [p.sentinel for p in processes.values()]
        ready = wait([reader] + sentinels)
        if reader in ready:
            result_item = reader.recv()
        else:
            executor = executor_reference()
            if executor is not None:
                executor._broken = True
                executor._shutdown_thread = True
                executor = None
            for (work_id, work_item) in pending_work_items.items():
                work_item.future.set_exception(BrokenProcessPool('A process in the process pool was terminated abruptly while the future was running or pending.'))
            pending_work_items.clear()
            for p in processes.values():
                p.terminate()
            shutdown_worker()
            return
        if isinstance(result_item, int):
            p = processes.pop(result_item)
            p.join()
            if not processes:
                shutdown_worker()
                return
        elif result_item is not None:
            work_item = pending_work_items.pop(result_item.work_id, None)
            if work_item is not None:
                if result_item.exception:
                    work_item.future.set_exception(result_item.exception)
                else:
                    work_item.future.set_result(result_item.result)
        executor = executor_reference()
        if shutting_down():
            try:
                if not pending_work_items:
                    shutdown_worker()
                    return
            except Full:
                pass
        executor = None

_system_limits_checked = False
_system_limited = None

def _check_system_limits():
    global _system_limits_checked, _system_limited
    if _system_limits_checked and _system_limited:
        raise NotImplementedError(_system_limited)
    _system_limits_checked = True
    try:
        nsems_max = os.sysconf('SC_SEM_NSEMS_MAX')
    except (AttributeError, ValueError):
        return
    if nsems_max == -1:
        return
    if nsems_max >= 256:
        return
    _system_limited = 'system provides too few semaphores (%d available, 256 necessary)' % nsems_max
    raise NotImplementedError(_system_limited)

class BrokenProcessPool(RuntimeError):
    __qualname__ = 'BrokenProcessPool'

class ProcessPoolExecutor(_base.Executor):
    __qualname__ = 'ProcessPoolExecutor'

    def __init__(self, max_workers=None):
        _check_system_limits()
        if max_workers is None:
            self._max_workers = multiprocessing.cpu_count()
        else:
            self._max_workers = max_workers
        self._call_queue = multiprocessing.Queue(self._max_workers + EXTRA_QUEUED_CALLS)
        self._call_queue._ignore_epipe = True
        self._result_queue = SimpleQueue()
        self._work_ids = queue.Queue()
        self._queue_management_thread = None
        self._processes = {}
        self._shutdown_thread = False
        self._shutdown_lock = threading.Lock()
        self._broken = False
        self._queue_count = 0
        self._pending_work_items = {}

    def _start_queue_management_thread(self):

        def weakref_cb(_, q=self._result_queue):
            q.put(None)

        if self._queue_management_thread is None:
            self._adjust_process_count()
            self._queue_management_thread = threading.Thread(target=_queue_management_worker, args=(weakref.ref(self, weakref_cb), self._processes, self._pending_work_items, self._work_ids, self._call_queue, self._result_queue))
            self._queue_management_thread.daemon = True
            self._queue_management_thread.start()
            _threads_queues[self._queue_management_thread] = self._result_queue

    def _adjust_process_count(self):
        for _ in range(len(self._processes), self._max_workers):
            p = multiprocessing.Process(target=_process_worker, args=(self._call_queue, self._result_queue))
            p.start()
            self._processes[p.pid] = p

    def submit(self, fn, *args, **kwargs):
        with self._shutdown_lock:
            if self._broken:
                raise BrokenProcessPool('A child process terminated abruptly, the process pool is not usable anymore')
            if self._shutdown_thread:
                raise RuntimeError('cannot schedule new futures after shutdown')
            f = _base.Future()
            w = _WorkItem(f, fn, args, kwargs)
            self._pending_work_items[self._queue_count] = w
            self._work_ids.put(self._queue_count)
            self._result_queue.put(None)
            self._start_queue_management_thread()
            return f

    submit.__doc__ = _base.Executor.submit.__doc__

    def shutdown(self, wait=True):
        with self._shutdown_lock:
            self._shutdown_thread = True
        if self._queue_management_thread:
            self._result_queue.put(None)
            if wait:
                self._queue_management_thread.join()
        self._queue_management_thread = None
        self._call_queue = None
        self._result_queue = None
        self._processes = None

    shutdown.__doc__ = _base.Executor.shutdown.__doc__

atexit.register(_python_exit)
