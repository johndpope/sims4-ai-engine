import functools
from sims4.collections import ListSet
from sims4.repr_utils import standard_repr
import sims4.log
logger = sims4.log.Logger('Assertions')
ENABLE_INTRUSIVE_ASSERTIONS = False

def not_recursive(func):
    open_calls = ListSet()
    func._not_recursive_tracker = open_calls

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        key = (args, kwargs)
        if key in open_calls:
            func_name = func.__name__
            invocation = standard_repr(func_name, *args, **kwargs)
            raise AssertionError('{}() does not support recursion.  Duplicated call: {}'.format(func_name, invocation))
        open_calls.add(key)
        try:
            return func(*args, **kwargs)
        finally:
            open_calls.remove(key)

    return wrapper

def not_recursive_gen(func):
    open_calls = ListSet()
    func._not_recursive_tracker = open_calls

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        key = (args, kwargs)
        if key in open_calls:
            func_name = func.__name__
            invocation = standard_repr(func_name, *args, **kwargs)
            raise AssertionError('{}() does not support recursion.  Duplicated call: {}'.format(func_name, invocation))
        open_calls.add(key)
        try:
            result = yield func(*args, **kwargs)
            return result
        finally:
            open_calls.remove(key)

    return wrapper

def hot_path(fn):
    return fn

