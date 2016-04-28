import functools
import inspect
import itertools
import date_and_time
import elements
import enum

class CleanupType(enum.Int):
    __qualname__ = 'CleanupType'
    NotCritical = 0
    OnCancel = 1
    OnCancelOrException = 2
    RunAll = 3

def run_child(timeline, sequence):
    element = build_element(sequence)
    if element is None:
        return
    result = yield timeline.run_child(element)
    return result

def build_element(sequence, critical=CleanupType.NotCritical):
    if critical == CleanupType.NotCritical:
        elem = _build_element(sequence)
    elif critical == CleanupType.OnCancel:
        elem = _build_critical_section(sequence)
    elif critical == CleanupType.OnCancelOrException:
        elem = _build_with_finally(sequence)
    elif critical == CleanupType.RunAll:
        elem = _build_element(sequence, sequence_wrapper=return_true_wrapper)
    else:
        raise ValueError('Unknown critical value: {}'.format(critical))
    return elem

def build_critical_section(*args):
    return build_element(args, critical=CleanupType.OnCancel)

def build_critical_section_with_finally(*args):
    return build_element(args, critical=CleanupType.OnCancelOrException)

def _split_sequence(sequence):
    if isinstance(sequence, (tuple, list)):
        if not sequence:
            return ([], None)
        (prefix, final) = (sequence[:-1], sequence[-1])
        return (prefix, final)
    return ([], sequence)

def _build_element(elem, sequence_wrapper=None):
    if isinstance(elem, functools.partial):
        canonical = elem.func
    else:
        canonical = elem
    if elem is None:
        return
    if isinstance(elem, elements.Element):
        return elem
    if isinstance(elem, (tuple, list)):
        return _build_from_iterable(elem, sequence_wrapper=sequence_wrapper)
    if inspect.isgeneratorfunction(canonical):
        return elements.GeneratorElement(elem)
    if inspect.isroutine(canonical):
        return elements.FunctionElement(elem)
    raise ValueError('Unknown element in _build_element: {}'.format(elem))

def _build_from_iterable(elem_iterable, sequence_wrapper=None):
    processed_list = [_build_element(e) for e in elem_iterable]
    if sequence_wrapper is None:
        filtered_list = [e for e in processed_list if e is not None]
    else:
        filtered_list = [sequence_wrapper(e) for e in processed_list if e is not None]
    if not filtered_list:
        return
    if len(filtered_list) == 1:
        return filtered_list[0]
    return elements.SequenceElement(filtered_list)

def _build_with_finally(sequence):
    (prefix, final) = _split_sequence(sequence)
    if final is not None and (inspect.isgeneratorfunction(final) or not inspect.isroutine(final)):
        raise ValueError('{} not a function in _build_element'.format(final))
    child = _build_from_iterable(prefix)
    if final is None:
        return child
    return elements.WithFinallyElement(child, final)

def _build_critical_section(sequence):
    (prefix, final) = _split_sequence(sequence)
    final_elem = _build_element(final)
    child = _build_from_iterable(prefix)
    if final is None:
        return child
    return elements.CriticalSectionElement(child, final_elem)

def return_true_wrapper(elem):
    return elements.OverrideResultElement(elem, True)

def soft_sleep_forever():
    return return_true_wrapper(elements.RepeatElement(elements.SoftSleepElement(date_and_time.create_time_span(days=28))))

def sleep_until_next_tick_element():
    return elements.BusyWaitElement(soft_sleep_forever(), lambda : True)

def maybe(predicate, sequence):
    return elements.ConditionalElement(predicate, sequence, None)

def unless(predicate, sequence):
    return elements.ConditionalElement(predicate, None, sequence)

def with_callback(target_list, callback, sequence=None):

    def add_callback(_):
        target_list.append(callback)

    def remove_callback(_):
        if callback in target_list:
            target_list.remove(callback)

    return build_critical_section_with_finally(add_callback, sequence, remove_callback)

def do_all(*parallel_elements, thread_element_map=None):
    if not thread_element_map:
        all_elements = parallel_elements
    elif not parallel_elements:
        all_elements = tuple(build_element(sequence) for sequence in thread_element_map.values())
    else:
        all_elements = itertools.chain(parallel_elements, tuple(build_element(sequence) for sequence in thread_element_map.values()))
    all_elements = tuple(element for element in all_elements if element is not None)
    if len(all_elements) == 1:
        return build_element(all_elements[0])
    return elements.AllElement(all_elements)

def must_run(sequence):
    return elements.MustRunElement(build_element(sequence))

