import collections
import contextlib
import enum
import sims4.log
import sims4.reload
import sims4.repr_utils

class CallbackEvent(enum.IntFlags, export=True):
    __qualname__ = 'CallbackEvent'
    TUNING_CODE_RELOAD = 1
    AUTONOMY_PING_ENTER = 2
    AUTONOMY_PING_EXIT = 4
    POSTURE_GRAPH_BUILD_ENTER = 8
    POSTURE_GRAPH_BUILD_EXIT = 16
    CONTENT_SET_GENERATE_ENTER = 32
    CONTENT_SET_GENERATE_EXIT = 64
    PROCESS_EVENTS_FOR_HOUSEHOLD_ENTER = 128
    PROCESS_EVENTS_FOR_HOUSEHOLD_EXIT = 256
    TRANSITION_SEQUENCE_ENTER = 512
    TRANSITION_SEQUENCE_EXIT = 1024
    ENTER_CONTENT_SET_GEN_OR_PROCESS_HOUSEHOLD_EVENTS = CONTENT_SET_GENERATE_ENTER | PROCESS_EVENTS_FOR_HOUSEHOLD_ENTER
    EXIT_CONTENT_SET_GEN_OR_PROCESS_HOUSEHOLD_EVENTS = CONTENT_SET_GENERATE_EXIT | PROCESS_EVENTS_FOR_HOUSEHOLD_EXIT

with sims4.reload.protected(globals()):
    _callbacks = collections.defaultdict(list)

def add_callbacks(events, *callbacks):
    if sims4.reload.currently_reloading:
        return
    for event in events:
        sims4.log.assert_raise('Callback_Utils', isinstance(event, CallbackEvent), '{} is an instance of {}', event, type(event), owner='bhill')
        for callback in callbacks:
            sims4.log.assert_raise('Callback_Utils', callback not in _callbacks[event], '{} is a duplicate callback being added for event {}', callback, event, owner='bhill')
            _callbacks[event].append(callback)

def invoke_callbacks(events, *args, **kwargs):
    for event in events:
        sims4.log.assert_raise('Callback_Utils', isinstance(event, CallbackEvent), '{} is an instance of {}', event, type(event), owner='bhill')
        for fn in _callbacks[event]:
            with consume_exceptions():
                fn(*args, **kwargs)

@contextlib.contextmanager
def invoke_enter_exit_callbacks(enter_event, exit_event, *args, **kwargs):
    invoke_callbacks(enter_event, *args, **kwargs)
    try:
        yield None
    finally:
        invoke_callbacks(exit_event, *args, **kwargs)

class consume_exceptions:
    __qualname__ = 'consume_exceptions'
    __slots__ = ('group', 'message')

    def __init__(self, group='Callback', message='Exception during a callback:'):
        self.group = group
        self.message = message

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_value is None:
            return
        if not isinstance(exc_value, Exception):
            return False
        sims4.log.exception(self.group, self.message() if callable(self.message) else self.message)
        return True

class protected_callback:
    __qualname__ = 'protected_callback'
    __slots__ = ('_callback',)

    def __new__(cls, callback):
        if callback is None:
            return
        return super().__new__(cls)

    def __init__(self, callback):
        self._callback = callback

    def __call__(self, *args, **kwargs):
        with consume_exceptions():
            self._callback(*args, **kwargs)

    def __repr__(self):
        return sims4.repr_utils.standard_repr(self, self._callback)

class CallableList(list):
    __qualname__ = 'CallableList'
    __slots__ = ()

    def __call__(self, *args, **kwargs):
        for fn in self[:]:
            fn(*args, **kwargs)

class RemovableCallableList(list):
    __qualname__ = 'RemovableCallableList'
    __slots__ = ()

    def __call__(self, *args, **kwargs):
        self[:] = [fn for fn in self if not fn(*args, **kwargs)]
        return not self

class CallableListConsumingExceptions(list):
    __qualname__ = 'CallableListConsumingExceptions'
    __slots__ = ()

    def __call__(self, *args, **kwargs):
        for fn in self[:]:
            with consume_exceptions('Utils', 'Exception throw calling: {}'.format(fn)):
                fn(*args, **kwargs)

class CallableListPreventingRecursion(CallableList):
    __qualname__ = 'CallableListPreventingRecursion'
    __slots__ = ('_callback_in_progress',)

    def __init__(self, *args):
        super().__init__(*args)
        self._callback_in_progress = False

    def __call__(self, *args, **kwargs):
        if self._callback_in_progress:
            return
        self._callback_in_progress = True
        try:
            super().__call__(*args, **kwargs)
        finally:
            self._callback_in_progress = False

class CallableTestList(list):
    __qualname__ = 'CallableTestList'
    __slots__ = ()

    def __call__(self, *args, **kwargs):
        return all(fn(*args, **kwargs) for fn in self[:])

