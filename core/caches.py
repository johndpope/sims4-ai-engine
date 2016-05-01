from itertools import count
import collections
import functools
import sys
import weakref
from sims4.callback_utils import add_callbacks, CallbackEvent
from sims4.utils import decorator
import sims4.log
import sims4.reload
logger = sims4.log.Logger('Caches', default_owner='bhill')
MAX_CACHE_SIZE = 18446744073709551616
with sims4.reload.protected(globals()):
    _KEYWORD_MARKER = object()
    use_asm_cache = True
    use_boundary_condition_cache = True
    use_constraints_cache = True
    skip_cache = False
    all_cached_functions = weakref.WeakSet()
    global_cache_version = 0
CacheInfo = collections.namedtuple('CacheInfo',
                                   ('hits', 'misses', 'maxsize', 'currsize'))


def clear_all_caches(force=False):
    global global_cache_version
    global_cache_version += 1
    if force or global_cache_version % 1000 == 0:
        for fn in all_cached_functions:
            fn.cache.clear()


if not sims4.reload.currently_reloading:
    add_callbacks(CallbackEvent.TUNING_CODE_RELOAD,
                  lambda: clear_all_caches(force=True))


def _double_check_failure(cache_result, fn_result, fn, *args, **kwargs):
    exc = AssertionError('Stale Cache Hit')
    frame = sys._getframe(2)
    sims4.log.exception(
        'Caches',
        'cache result:{}, function result: {}, function:{} {} {}',
        cache_result,
        fn_result,
        fn,
        args,
        kwargs,
        exc=exc,
        frame=frame)


@decorator
def cached(fn, maxsize=100, key=None, debug_cache=False):
    key_fn = key
    del key

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if skip_cache:
            return fn(*args, **kwargs)
        cache = wrapper.cache
        if global_cache_version != wrapper.cache_version:
            cache.clear()
            wrapper.cache_version = global_cache_version
        try:
            if key_fn is None:
                key = (args, _KEYWORD_MARKER,
                       frozenset(kwargs.items())) if kwargs else args
            else:
                key = key_fn(*args, **kwargs)
            result = cache[key]
        except TypeError as exc:
            if len(exc.args) == 1 and exc.args[0].startswith(
                    'unhashable type'):
                logger.callstack(
                    'Cache failed on {} in function argument(s):\nargs={} kwargs={}\nTry one of the following: use hashable types as arguments to the function (e.g. tuple instead of list) or implement __hash__() on the unhashable object.',
                    exc.args[0],
                    args,
                    kwargs,
                    level=sims4.log.LEVEL_ERROR,
                    owner='bhill')
            raise exc
        except KeyError:
            cache[key] = result = fn(*args, **kwargs)
        if maxsize is not None and len(cache) > maxsize:
            cache.popitem(last=False)
        return result

    def cache_info():
        raise AttributeError(
            'Cache statistics not tracked in optimized Python.')

    wrapper.cache = {} if maxsize is None else collections.OrderedDict()
    wrapper.cache_version = global_cache_version
    wrapper.uncached_function = fn
    wrapper.cache_info = cache_info
    all_cached_functions.add(wrapper)
    return wrapper


@decorator
def cached_generator(fn, cache_decorator=cached, **cache_kwargs):
    @cache_decorator(**cache_kwargs)
    @functools.wraps(fn)
    def _wrapper(*args, **kwargs):
        return ([], fn(*args, **kwargs))

    @functools.wraps(_wrapper)
    def yielder(*args, **kwargs):
        (computed_values, gen) = _wrapper(*args, **kwargs)
        try:
            for i in count():
                if i >= len(computed_values):
                    computed_values.append(next(gen))
                yield computed_values[i]
        except StopIteration:
            pass

    return yielder


def uncached(wrapper):
    return wrapper.uncached_function


class BarebonesCache(dict):
    __qualname__ = 'BarebonesCache'
    __slots__ = ('uncached_function', )

    def __init__(self, uncached_function):
        self.uncached_function = uncached_function

    def __repr__(self):
        return '{}({})'.format(type(self).__qualname__, self.uncached_function)

    __call__ = dict.__getitem__

    def __missing__(self, key):
        self[key] = ret = self.uncached_function(key)
        return ret
