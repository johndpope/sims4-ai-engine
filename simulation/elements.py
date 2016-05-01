class Element:
    __qualname__ = 'Element'
    __slots__ = ('_element_handle', '_parent_handle')

    @classmethod
    def shortname(cls):
        return cls.__name__

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._element_handle = None
        self._parent_handle = None

    @property
    def attached_to_timeline(self):
        return self._element_handle is not None

    def trigger_hard_stop(self):
        if self._element_handle is not None:
            timeline = self._element_handle.timeline
            timeline.hard_stop(self._element_handle)

    def trigger_soft_stop(self):
        if self._element_handle is not None:
            timeline = self._element_handle.timeline
            timeline.soft_stop(self._element_handle)

    def _run(self, timeline):
        return True

    def _hard_stop(self):
        pass

    def _soft_stop(self):
        return False

    def _teardown(self):
        self._parent_handle = None

    def _get_child_handles(self):
        return ()

    def set_parent_handle(self, handle):
        self._parent_handle = handle

    def _clear_parent_handle(self):
        self._parent_handle = None

    def _child_scheduled(self, timeline, child_handle):
        raise RuntimeError('Only ParentElement can schedule children.')

    def __repr__(self):
        return '<{}#{:#010x}>'.format(self.shortname(), id(self))

    def tracing_repr(self):
        return self.__repr__()


class ParentElement(Element):
    __qualname__ = 'ParentElement'
    __slots__ = '_child_handle'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._child_handle = None

    def _resume(self, timeline, child_result):
        return child_result

    def _hard_stop(self):
        if self._child_handle is not None:
            child = self._child_handle
            self._child_handle = None
            if child.element is not None:
                child.element._clear_parent_handle()

    def _get_child_handles(self):
        if self._child_handle is not None:
            return (self._child_handle, )
        return ()

    def _child_scheduled(self, timeline, child_handle):
        (e, handle) = timeline._active
        handle._set_scheduled(True)
        child_handle.element.set_parent_handle(handle)
        self._child_handle = child_handle

    def _child_returned(self, child):
        self._child_handle = None

    def _teardown(self):
        self._child_handle = None
        super()._teardown()


class RunChildElement(ParentElement):
    __qualname__ = 'RunChildElement'
    __slots__ = ('child_element', )

    @classmethod
    def shortname(cls):
        return 'RunChild'

    def __init__(self, child_element):
        super().__init__()
        self.child_element = child_element

    def _run(self, timeline):
        if self.child_element is not None:
            return timeline.run_child(self.child_element)

    def _teardown(self):
        super()._teardown()
        self.child_element = None


class MinimumTimeElement(RunChildElement):
    __qualname__ = 'MinimumTimeElement'
    __slots__ = ('_child_result', '_minimum_time_required', '_start_time',
                 '_slept')

    @classmethod
    def shortname(cls):
        return 'MinimumTime'

    def __init__(self, child_element, minimum_time_required):
        super().__init__(child_element)
        self._child_result = None
        self._minimum_time_required = minimum_time_required
        self._start_time = None
        self._slept = False

    def _run(self, timeline):
        self._start_time = timeline.now
        self._slept = False
        return super()._run(timeline)

    def _resume(self, timeline, child_result):
        if self._slept:
            return self._child_result
        current_time = timeline.now
        time_delta = current_time - self._start_time
        if time_delta > self._minimum_time_required:
            return child_result
        self._child_result = child_result
        time_to_sleep = self._minimum_time_required - time_delta
        self._slept = True
        return timeline.run_child(SleepElement(time_to_sleep))

    def _teardown(self):
        super()._teardown()
        self._child_result = None
        self._minimum_time_required = None
        self._start_time = None
        self._slept = False

    def __repr__(self):
        if self._slept:
            status = 'slept'
        else:
            status = 'not slept'
        return '<{}; {}; {}>'.format(self.shortname(), status,
                                     self._minimum_time_required)


class FunctionElement(Element):
    __qualname__ = 'FunctionElement'
    __slots__ = ('callback', )

    @classmethod
    def shortname(cls):
        return 'Fn'

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def _run(self, timeline):
        result = self.callback(timeline)
        if result is None:
            return True
        return result

    def _teardown(self):
        self.callback = None
        super()._teardown()

    def __repr__(self):
        return '<{}; {}>'.format(self.shortname(),
                                 _format_callable(self.callback))


class GeneratorElementBase(ParentElement):
    __qualname__ = 'GeneratorElementBase'
    __slots__ = ('generator', )

    @classmethod
    def shortname(cls):
        return 'GenBase'

    def _get_generator(self):
        raise NotImplementedError()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.generator = None

    def _run(self, timeline):
        pending_generator = self._get_generator()
        self.generator = pending_generator(timeline)
        try:
            child = next(self.generator)
            if not _check_yield(child):
                raise AssertionError('Yielding non-Element handle: {}'.format(
                    child))
            return child
        except StopIteration as exc:
            return GeneratorElementBase._result_value(exc)

    def _resume(self, timeline, child_result):
        try:
            child = self.generator.send(child_result)
            if not _check_yield(child):
                raise AssertionError('Yielding non-Element handle: {}'.format(
                    child))
            return child
        except StopIteration as exc:
            return GeneratorElementBase._result_value(exc)

    @staticmethod
    def _result_value(exc):
        result = exc.value
        if result is None:
            return True
        return result

    def _hard_stop(self):
        super()._hard_stop()
        if self.generator is not None:
            self.generator.close()

    def _teardown(self):
        if self.generator is not None:
            self.generator.close()
        self.generator = None
        super()._teardown()

    def _get_default_gen_name(self):
        return 'None'

    def _repr_helper(self, tracing=False):
        if self.generator is None:
            status = 'not-started'
            name = self._get_default_gen_name()
        elif self.generator.gi_running:
            status = 'running'
            name = '{}@{}'.format(self.generator.gi_code.co_name,
                                  self.generator.gi_code.co_firstlineno)
        elif self.generator.gi_frame is not None:
            status = 'active'
            name = '{}@{}'.format(self.generator.gi_code.co_name,
                                  self.generator.gi_code.co_firstlineno)
            if self._child_handle is not None:
                child_element = self._child_handle.element
                if child_element is not None:
                    status += '; child: {}'.format(child_element)
        else:
            status = 'dead'
            name = self._get_default_gen_name()
        return '<{}; {}; {}>'.format(self.shortname(), name, status)

    def __repr__(self):
        return self._repr_helper(tracing=False)

    def tracing_repr(self):
        return self._repr_helper(tracing=True)


class GeneratorElement(GeneratorElementBase):
    __qualname__ = 'GeneratorElement'
    __slots__ = ('pending_generator', )

    @classmethod
    def shortname(cls):
        return 'Gen'

    def __init__(self, pending_generator):
        super().__init__()
        self.pending_generator = pending_generator

    def _get_generator(self):
        return self.pending_generator

    def _teardown(self):
        self.pending_generator = None
        super()._teardown()

    def _get_default_gen_name(self):
        if self.pending_generator is not None:
            return _format_callable(self.pending_generator)
        return super()._get_default_gen_name()


class SubclassableGeneratorElement(GeneratorElementBase):
    __qualname__ = 'SubclassableGeneratorElement'
    __slots__ = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @classmethod
    def shortname(cls):
        return 'SubclassableGen'

    def _get_generator(self):
        return self._run_gen

    def _run_gen(self, timeline):
        raise NotImplementedError()

    def _get_default_gen_name(self):
        return type(self).__name__


class SleepElement(Element):
    __qualname__ = 'SleepElement'
    __slots__ = ('delay', 'sleep', 'soft_stopped')

    @classmethod
    def shortname(cls):
        return 'Sleep'

    def __init__(self, delay):
        super().__init__()
        self.delay = delay
        self.sleep = True
        self.soft_stopped = False

    def _run(self, timeline):
        if self.soft_stopped:
            return False
        if self.sleep:
            timeline.schedule(self, timeline.now + self.delay)
            self.sleep = False
            return
        self.sleep = True
        return True

    def _soft_stop(self):
        self.soft_stopped = True

    def __repr__(self):
        if self.sleep:
            status = 'ready to sleep'
        else:
            status = 'ready to wake'
        return '<{}; {}; {}; {}>'.format(
            self.shortname(), self.delay, status, 'soft-stopped'
            if self.soft_stopped else 'not-stopped')


class SoftSleepElement(SleepElement):
    __qualname__ = 'SoftSleepElement'
    __slots__ = ()

    def __init__(self, delay):
        super().__init__(delay)

    @classmethod
    def shortname(cls):
        return 'SoftSleep'

    def _run(self, timeline):
        if self.soft_stopped:
            return False
        return super()._run(timeline)

    def _soft_stop(self):
        timeline = self._element_handle.timeline
        if not self.soft_stopped:
            self.soft_stopped = True
            timeline.reschedule(self._element_handle, timeline.now)


class CallbackElement(ParentElement):
    __qualname__ = 'CallbackElement'
    __slots__ = ('_child_element', '_complete_callback', '_hard_stop_callback',
                 '_teardown_callback')

    def __init__(self, child_element, complete_callback, hard_stop_callback,
                 teardown_callback):
        super().__init__()
        self._child_element = child_element
        self._complete_callback = complete_callback
        self._hard_stop_callback = hard_stop_callback
        self._teardown_callback = teardown_callback

    def _run(self, timeline):
        return timeline.run_child(self._child_element)

    def _resume(self, timeline, child_result):
        self._call_callback(self._complete_callback)
        return child_result

    def _hard_stop(self):
        super()._hard_stop()
        self._call_callback(self._hard_stop_callback)

    def _teardown(self):
        super()._teardown()
        self._call_callback(self._teardown_callback)

    def _call_callback(self, callback):
        self._clear_callbacks()
        if callback is not None:
            callback()

    def _clear_callbacks(self):
        self._complete_callback = None
        self._hard_stop_callback = None
        self._teardown_callback = None


class BusyWaitElement(ParentElement):
    __qualname__ = 'BusyWaitElement'

    def __init__(self, child_element, test_callable):
        super().__init__()
        self._test_callable = test_callable
        self._child_element = child_element
        self._timeline = None
        self._sleep_handle = None

    @classmethod
    def shortname(cls):
        return 'BusyWait'

    def _run(self, timeline):
        if self._sleep_handle is not None and self._test_callable():
            return True
        self._timeline = timeline
        timeline.per_simulate_callbacks.append(self._try_to_wake)
        self._sleep_handle = timeline.run_child(self._child_element)
        return self._sleep_handle

    def _try_to_wake(self):
        if self._test_callable():
            self._timeline.per_simulate_callbacks.remove(self._try_to_wake)
            self._timeline.soft_stop(self._sleep_handle)

    def _hard_stop(self):
        self._clean_up_common()
        super()._hard_stop()

    def _teardown(self):
        self._clean_up_common()
        super()._teardown()

    def _clean_up_common(self):
        self._test_callable = None
        self._child_element = None
        if self._timeline is not None:
            if self._try_to_wake in self._timeline.per_simulate_callbacks:
                self._timeline.per_simulate_callbacks.remove(self._try_to_wake)
            self._timeline = None
            self._sleep_handle = None

    def __repr__(self):
        return '<{}; {}>'.format(self.shortname(),
                                 self._test_callable.__code__.co_name)


class SequenceElement(ParentElement):
    __qualname__ = 'SequenceElement'
    __slots__ = ('queue', 'index', 'soft_stopped', 'failed')

    @classmethod
    def shortname(cls):
        return 'Seq'

    def __init__(self, queue):
        super().__init__()
        self.queue = list(queue)
        self.index = 0
        self.soft_stopped = False
        self.failed = False

    def _run(self, timeline):
        self.index = 0
        self.soft_stopped = False
        self.failed = False
        child_handle = self._run_next(timeline)
        if child_handle is not None:
            return child_handle
        return not self.soft_stopped

    def _resume(self, timeline, child_result):
        if not child_result:
            self.failed = True
        child_handle = self._run_next(timeline)
        if child_handle is not None:
            return child_handle
        return child_result and (not self.soft_stopped and not self.failed)

    def _run_next(self, timeline):
        cancelled = self.soft_stopped or self.failed
        while self.index < len(self.queue):
            child_element = self.queue[self.index]
            if cancelled and not isinstance(child_element, MustRunElement):
                continue
            child_handle = timeline.run_child(child_element)
            return child_handle

    def _teardown(self):
        self.queue = None
        super()._teardown()

    def _soft_stop(self):
        self.soft_stopped = True

    def __repr__(self):
        return '<{}; [{}]; index {}>'.format(
            self.shortname(), ', '.join(str(e) for e in self.queue)
            if self.queue is not None else 'None', self.index)

    def tracing_repr(self):
        active_element_str = self.queue[self.index].tracing_repr(
        ) if self.index < len(self.queue) else 'Done'
        return '<{};{}  [{}]; index {}>'.format(
            self.shortname(), active_element_str, ', '.join(
                str(e) for e in self.queue)
            if self.queue is not None else 'None', self.index)


class RememberSoftStopElement(ParentElement):
    __qualname__ = 'RememberSoftStopElement'
    __slots__ = ('_child_element', 'soft_stopped')

    @classmethod
    def shortname(cls):
        return 'RememberSoftStop'

    def __init__(self, child_element):
        super().__init__()
        self._child_element = child_element
        self.soft_stopped = False

    def _run(self, timeline):
        if self._child_element is not None:
            return timeline.run_child(self._child_element)

    def _resume(self, timeline, child_result):
        if self.soft_stopped:
            return False
        return child_result

    def _soft_stop(self):
        self.soft_stopped = True

    def _teardown(self):
        self._child_element = None
        super()._teardown()

    def __repr__(self):
        return '<{}; {}; {}>'.format(self.shortname(), self._child_element,
                                     'stop-pending'
                                     if self.soft_stopped else 'running')

    def tracing_repr(self):
        return '<{}; {}; {}>'.format(
            self.shortname(), self._child_element.tracing_repr(),
            'stop-pending' if self.soft_stopped else 'running')


class RepeatElement(RememberSoftStopElement):
    __qualname__ = 'RepeatElement'
    __slots__ = ()

    @classmethod
    def shortname(cls):
        return 'Repeat'

    def __init__(self, child_element):
        super().__init__(child_element)

    def _resume(self, timeline, child_result):
        if self.soft_stopped:
            return False
        if child_result:
            return timeline.run_child(self._child_element)
        return child_result

    def __repr__(self):
        return '<{}; {}; {}>'.format(self.shortname(), self._child_element,
                                     'stop-pending'
                                     if self.soft_stopped else 'looping')

    def tracing_repr(self):
        return '<{}; {}; {}>'.format(
            self.shortname(), self._child_element.tracing_repr(),
            'stop-pending' if self.soft_stopped else 'looping')


class CriticalSectionElement(ParentElement):
    __qualname__ = 'CriticalSectionElement'
    __slots__ = ('work', 'cleanup', 'result', 'state')
    STATE_INIT = 0
    STATE_WORK = 1
    STATE_CLEANUP = 2

    @classmethod
    def shortname(cls):
        return 'Critical'

    def __init__(self, work, cleanup):
        super().__init__()
        self.work = work
        self.cleanup = cleanup
        self.result = None
        self.state = CriticalSectionElement.STATE_INIT

    def _run(self, timeline):
        self.result = None
        if self.work is not None:
            self.state = CriticalSectionElement.STATE_WORK
            return timeline.run_child(self.work)
        if self.cleanup is not None:
            self.state = CriticalSectionElement.STATE_CLEANUP
            return timeline.run_child(self.cleanup)

    def _resume(self, timeline, child_result):
        if self.state == CriticalSectionElement.STATE_WORK:
            self.state = CriticalSectionElement.STATE_CLEANUP
            self.result = child_result
            if self.cleanup is not None:
                return timeline.run_child(self.cleanup)
        if self.result is None:
            return child_result
        return self.result and child_result

    def _teardown(self):
        self.work = None
        self.cleanup = None
        self.result = None
        super()._teardown()

    def __repr__(self):
        return '<{}; {}; {}; {}; {}>'.format(
            self.shortname(), ['init', 'work', 'cleanup'][self.state],
            self.work, self.cleanup, self.result)

    def tracing_repr(self):
        return '<{}; {}; {}; {}; {}>'.format(
            self.shortname(), ['init', 'work', 'cleanup'][self.state],
            self.work.tracing_repr(), self.cleanup.tracing_repr(), self.result)


class AllElement(Element):
    __qualname__ = 'AllElement'
    __slots__ = ('active', 'inactive', 'result')

    @classmethod
    def shortname(cls):
        return 'All'

    def __init__(self, children):
        super().__init__()
        self.inactive = list(children)
        self.active = {}
        for child in self.inactive:
            while not isinstance(child, Element):
                raise TypeError(
                    'Children of All element must be elements, not {}'.format(
                        child))
        self.result = None

    def add_work(self, timeline, child):
        if child in self.active:
            raise AssertionError('Double scheduling of child in add_work.')
        (element, handle) = timeline._active
        while handle is not None:
            while element is not self:
                handle = element._parent_handle
                element = handle.element
        if handle is None:
            raise AssertionError(
                'Work can only be added to an All element when it in the running chain.')
        self.active[child] = child_handle = timeline.schedule_asap(child)
        child_handle.element.set_parent_handle(handle)

    def _run(self, timeline):
        self.result = True
        children = {}
        pending = self.inactive
        self.inactive = []
        for child in pending:
            if child in children:
                raise AssertionError('Double scheduling of a child in All')
            children[child] = timeline.schedule_child(child, timeline.now)
        self.active = children
        return self._work(timeline)

    def _resume(self, timeline, child_result):
        if child_result is not None:
            self.result = self.result and child_result
        return self._work(timeline)

    def _work(self, timeline):
        if self.active:
            timeline._mark_scheduled(self)
            return
        return self.result

    def _child_scheduled(self, timeline, child_handle):
        (e, handle) = timeline._active
        child_handle.element.set_parent_handle(handle)

    def _child_returned(self, child):
        del self.active[child]
        self.inactive.append(child)

    def _get_child_handles(self):
        return self.active.values()

    def _teardown(self):
        self.active.clear()
        self.inactive.chear()
        self.result = None
        super()._teardown()

    def __repr__(self):
        return '<{}; active: [{}]; inactive: [{}]>'.format(
            self.shortname(), ', '.join(str(child) for child in self.active),
            ', '.join(str(child) for child in self.inactive))


class ConditionalElement(ParentElement):
    __qualname__ = 'ConditionalElement'
    __slots__ = ('_callable_test', '_true_element', '_false_element')

    @classmethod
    def shortname(cls):
        return 'Conditional'

    def __init__(self, callable_test, true_element, false_element):
        super().__init__()
        self._callable_test = callable_test
        self._true_element = true_element
        self._false_element = false_element

    def _run(self, timeline):
        if self._callable_test():
            if self._true_element is not None:
                return timeline.run_child(self._true_element)
        elif self._false_element is not None:
            return timeline.run_child(self._false_element)
        return True

    def _teardown(self):
        self._callable_test = None
        self._true_element = None
        self._false_element = None
        super()._teardown()

    def __repr__(self):
        return '<{}; test:{}; true:{}; false:{}>'.format(
            self.shortname(), self._callable_test, self._true_element,
            self._false_element)


class WithFinallyElement(ParentElement):
    __qualname__ = 'WithFinallyElement'
    __slots__ = ('_element', '_finally_callable', '_should_call_finally')

    @classmethod
    def shortname(cls):
        return 'WithFinally'

    def __init__(self, element, finally_callable):
        super().__init__()
        self._element = element
        self._finally_callable = finally_callable
        self._should_call_finally = False

    def _run(self, timeline):
        self._should_call_finally = True
        if self._element is not None:
            return timeline.run_child(self._element)
        self._call_finally(timeline)
        return True

    def _resume(self, timeline, child_result):
        self._call_finally(timeline)
        return child_result

    def _hard_stop(self):
        timeline = self._element_handle.timeline
        self._call_finally(timeline)

    def _call_finally(self, timeline):
        if self._finally_callable is not None and self._should_call_finally:
            self._should_call_finally = False
            self._finally_callable(timeline)

    def _teardown(self):
        self._element = None
        self._finally_callable = None
        self._should_call_finally = False
        super()._teardown()

    def __repr__(self):
        return '<{}; element:{}; finally:{}>'.format(
            self.shortname(), str(self._element),
            _format_callable(self._finally_callable))

    def tracing_repr(self):
        str_element = self._element.tracing_repr(
        ) if self._element is not None else 'None'
        return '<{}; element:{}; finally:{}>'.format(
            self.shortname(), str_element,
            _format_callable(self._finally_callable))


class MustRunElement(ParentElement):
    __qualname__ = 'MustRunElement'
    __slots__ = '_child_element'

    @classmethod
    def shortname(cls):
        return 'MustRun'

    def __init__(self, child_element):
        super().__init__()
        self._child_element = child_element

    def _run(self, timeline):
        if self._child_element is not None:
            return timeline.run_child(self._child_element)
        return True

    def _soft_stop(self):
        return True

    def __repr__(self):
        return '<{}; {}>'.format(self.shortname(), self._child_element)

    def tracing_repr(self):
        str_element = self._child_element.tracing_repr(
        ) if self._child_element is not None else 'None'
        return '<{}; {}>'.format(self.shortname(), str_element)


class ResultElement(ParentElement):
    __qualname__ = 'ResultElement'
    __slots__ = ('_child_element', 'result')

    @classmethod
    def shortname(cls):
        return 'Result'

    def __init__(self, child, default=None):
        super().__init__()
        self._child_element = child
        self.result = default

    def _run(self, timeline):
        return timeline.run_child(self._child_element)

    def _resume(self, timeline, child_result):
        self.result = child_result
        return child_result

    def _teardown(self):
        self._child_element = None
        self.result = None
        super()._teardown()

    def __repr__(self):
        return '<{}; result: {}; child: {}>'.format(
            self.shortname(), self.result, self._child_element)

    def tracing_repr(self):
        return '<{}; result: {}; child: {}>'.format(
            self.shortname(), self.result, self._child_element.tracing_repr())


class OverrideResultElement(ParentElement):
    __qualname__ = 'OverrideResultElement'
    __slots__ = ('_child_element', '_result')

    @classmethod
    def shortname(cls):
        return 'OverrideResult'

    def __init__(self, child_element, result):
        super().__init__()
        self._child_element = child_element
        self._result = result

    def _run(self, timeline):
        if self._child_element is not None:
            return timeline.run_child(self._child_element)
        return self._result

    def _resume(self, timeline, child_result):
        return self._result

    def __repr__(self):
        return '<{}; result: {}; {}>'.format(self.shortname(), self._result,
                                             self._child_element)

    def call_repr_(self):
        str_element = self._child_element.tracing_repr(
        ) if self._child_element is not None else 'None'
        return '<{}; result: {}; {}>'.format(self.shortname(), self._result,
                                             str_element)


def _check_yield(result):
    return hasattr(result, 'element') and isinstance(result.element, Element)


def _format_callable(fn):
    if fn is None:
        return 'None'
    if hasattr(fn, '__qualname__'):
        return '{}@{}'.format(fn.__qualname__, fn.__code__.co_firstlineno)
    return str(fn)
