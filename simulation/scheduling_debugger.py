try:
    import ctypes
    HAS_CTYPES = True
except ImportError:
    HAS_CTYPES = False
import traceback
import weakref
try:
    from pydevd_comm import GetGlobalDebugger, CMD_SET_BREAK
except ImportError:
    pass
import framewrapper
try:
    import pydevd
except ImportError:
    pass
import sims4.log
import enum
logger = sims4.log.Logger('Timeline')


class BreakpointEvent(enum.Int, export=False):
    __qualname__ = 'BreakpointEvent'
    ON_SOFT_STOP = Ellipsis
    ON_HARD_STOP = Ellipsis
    ON_RUN = Ellipsis
    ON_RESUME = Ellipsis
    ON_RETURN = Ellipsis


class _Breakpoint:
    __qualname__ = '_Breakpoint'

    def __init__(self):
        self.enabled = True
        self.conditional = None


class _ElementDebugData:
    __qualname__ = '_ElementDebugData'

    def __init__(self, element):
        self.breakpoints = {}
        self.element = element

    def should_break(self, event):
        breakpoint = self.breakpoints.get(event, None)
        if breakpoint is None:
            return False
        if not breakpoint.enabled:
            return False
        if breakpoint.conditional is not None:
            return breakpoint.conditional(self.element)
        return True

    def enable_breakpoint(self, event, conditional=None):
        breakpoint = self.breakpoints.setdefault(event, _Breakpoint())
        breakpoint.enabled = True
        breakpoint.conditional = conditional

    def disable_breakpoint(self, event):
        breakpoint = self.breakpoints.get(event, None)
        if breakpoint is not None:
            breakpoint.enabled = False


class TimelineDebugger:
    __qualname__ = 'TimelineDebugger'

    def __init__(self):
        self._element_to_debug_data = weakref.WeakKeyDictionary()
        self._enable_call_logging = False
        self._timeline = None

    def set_timeline(self, timeline):
        self._timeline = timeline

    def on_run_element(self, element):
        self._logging(element, 'Run', None)
        self.break_on_element_event(element, BreakpointEvent.ON_RUN)

    def on_resume_element(self, element, result):
        self._logging(element, 'Res', result)
        self.break_on_element_event(element, BreakpointEvent.ON_RESUME)

    def on_return_element(self, element, result):
        self._logging(element, 'Ret', result)
        self.break_on_element_event(element, BreakpointEvent.ON_RETURN)

    def on_soft_stop_element(self, element):
        self.break_on_element_event(element, BreakpointEvent.ON_SOFT_STOP)

    def on_hard_stop_element(self, element):
        self._logging(element, 'Hard')
        self.break_on_element_event(element, BreakpointEvent.ON_HARD_STOP)

    def set_break_on_soft_stop(self, element, break_on=True, conditional=None):
        self.set_break_on_event(element, BreakpointEvent.ON_SOFT_STOP,
                                break_on, conditional)

    def set_break_on_event(
            self, element,
            event, break_on=True,
            conditional=None):
        debug_data = self._element_to_debug_data.setdefault(
            element, _ElementDebugData(element))
        if break_on:
            debug_data.enable_breakpoint(event, conditional)
        else:
            debug_data.disable_breakpoint(event)

    def break_on_element_event(self, element, event):
        debug_data = self._element_to_debug_data.get(element, None)
        if debug_data is None:
            return
        if not debug_data.should_break(event):
            return
        self._debugger_break()
        self._stop_here()

    def _debugger_break(self):
        t = pydevd.threadingCurrentThread()
        debugger = GetGlobalDebugger()
        debugger.setSuspend(t, CMD_SET_BREAK)

    def _stop_here(self):
        pass

    def _logging(self, e, what, result=None):
        if not self._enable_call_logging:
            return
        import alarms
        if isinstance(e, alarms.AlarmElement):
            return
        indent = 0
        top_element = e
        parent_handle = e._parent_handle
        while parent_handle is not None:
            indent += 1
            parent_element = parent_handle.element
            if parent_element is None:
                break
            top_element = parent_element
            parent_handle = parent_element._parent_handle
        if result is self._timeline._child:
            print_result = 'child'
        else:
            print_result = result
        indent_string = ' ' * indent
        logger.debug('{}{} {}:{} -> {}', indent_string,
                     top_element.tracing_repr(), what, e.tracing_repr(),
                     print_result)
        if getattr(
                e, 'generator',
                None) and e.generator.gi_code is not None and result is self._timeline._child:
            frames = get_generator_frames(e.generator)
            for frame in frames:
                for (module, line_num, func_name,
                     _) in traceback.extract_stack(frame):
                    logger.debug('{}{}.{}:{}', indent_string, module,
                                 func_name, line_num)


def get_generator_frames(gen):
    frames = []
    if HAS_CTYPES:
        while gen is not None and gen.gi_frame is not None:
            frames.append(gen.gi_frame)
            if gen.gi_code.co_code[gen.gi_frame.f_lasti + 1] != 72:
                break
            frame_pointer = ctypes.c_void_p(id(gen.gi_frame))
            frame_wrapper = ctypes.cast(
                frame_pointer, ctypes.POINTER(framewrapper.FrameWrapper))
            sub_gen_id = frame_wrapper[0].f_stacktop[-1]
            gen = ctypes.cast(sub_gen_id, ctypes.py_object).value
    return frames


def get_element_chain(element):
    element_names = []
    child_name = None
    while element is not None:
        name = str(element)
        if child_name is None:
            display_name = name
        else:
            display_name = name.replace(child_name, '$child')
        element_names.append(display_name)
        if element._parent_handle is None:
            break
        element = element._parent_handle.element
        child_name = name
    return element_names


def print_element_chain(element):
    for elem in get_element_chain(childmost(element)):
        print(elem)


def childmost(element):
    while hasattr(element, '_child_handle'):
        while element._child_handle is not None and element._child_handle.element is not None:
            element = element._child_handle.element
    return element


def parentmost(element):
    while element._parent_handle is not None:
        while element._parent_handle.element is not None:
            element = element._parent_handle.element
    return element
