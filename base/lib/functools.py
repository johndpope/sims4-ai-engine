__all__ = ['update_wrapper', 'wraps', 'WRAPPER_ASSIGNMENTS', 'WRAPPER_UPDATES', 'total_ordering', 'cmp_to_key', 'lru_cache', 'reduce', 'partial']
from _functools import partial, reduce
from collections import namedtuple
try:
    from _thread import RLock
except:

    class RLock:
        __qualname__ = 'RLock'

        def __enter__(self):
            pass

        def __exit__(self, exctype, excinst, exctb):
            pass

WRAPPER_ASSIGNMENTS = ('__module__', '__name__', '__qualname__', '__doc__', '__annotations__')
WRAPPER_UPDATES = ('__dict__',)

def update_wrapper(wrapper, wrapped, assigned=WRAPPER_ASSIGNMENTS, updated=WRAPPER_UPDATES):
    wrapper.__wrapped__ = wrapped
    for attr in assigned:
        try:
            value = getattr(wrapped, attr)
        except AttributeError:
            pass
        setattr(wrapper, attr, value)
    for attr in updated:
        getattr(wrapper, attr).update(getattr(wrapped, attr, {}))
    return wrapper

def wraps(wrapped, assigned=WRAPPER_ASSIGNMENTS, updated=WRAPPER_UPDATES):
    return partial(update_wrapper, wrapped=wrapped, assigned=assigned, updated=updated)

def total_ordering(cls):
    convert = {'__lt__': [('__gt__', lambda self, other: not (self < other or self == other)), ('__le__', lambda self, other: self < other or self == other), ('__ge__', lambda self, other: not self < other)], '__le__': [('__ge__', lambda self, other: not self <= other or self == other), ('__lt__', lambda self, other: self <= other and not self == other), ('__gt__', lambda self, other: not self <= other)], '__gt__': [('__lt__', lambda self, other: not (self > other or self == other)), ('__ge__', lambda self, other: self > other or self == other), ('__le__', lambda self, other: not self > other)], '__ge__': [('__le__', lambda self, other: not self >= other or self == other), ('__gt__', lambda self, other: self >= other and not self == other), ('__lt__', lambda self, other: not self >= other)]}
    roots = [op for op in convert if getattr(cls, op, None) is not getattr(object, op, None)]
    if not roots:
        raise ValueError('must define at least one ordering operation: < > <= >=')
    root = max(roots)
    for (opname, opfunc) in convert[root]:
        while opname not in roots:
            opfunc.__name__ = opname
            opfunc.__doc__ = getattr(int, opname).__doc__
            setattr(cls, opname, opfunc)
    return cls

def cmp_to_key(mycmp):

    class K(object):
        __qualname__ = 'cmp_to_key.<locals>.K'
        __slots__ = ['obj']

        def __init__(self, obj):
            self.obj = obj

        def __lt__(self, other):
            return mycmp(self.obj, other.obj) < 0

        def __gt__(self, other):
            return mycmp(self.obj, other.obj) > 0

        def __eq__(self, other):
            return mycmp(self.obj, other.obj) == 0

        def __le__(self, other):
            return mycmp(self.obj, other.obj) <= 0

        def __ge__(self, other):
            return mycmp(self.obj, other.obj) >= 0

        def __ne__(self, other):
            return mycmp(self.obj, other.obj) != 0

        __hash__ = None

    return K

try:
    from _functools import cmp_to_key
except ImportError:
    pass
_CacheInfo = namedtuple('CacheInfo', ['hits', 'misses', 'maxsize', 'currsize'])

class _HashedSeq(list):
    __qualname__ = '_HashedSeq'
    __slots__ = 'hashvalue'

    def __init__(self, tup, hash=hash):
        self[:] = tup
        self.hashvalue = hash(tup)

    def __hash__(self):
        return self.hashvalue

def _make_key(args, kwds, typed, kwd_mark=(object(),), fasttypes={int, str, frozenset, type(None)}, sorted=sorted, tuple=tuple, type=type, len=len):
    key = args
    if kwds:
        sorted_items = sorted(kwds.items())
        key += kwd_mark
        for item in sorted_items:
            key += item
    if typed:
        key += tuple(type(v) for v in args)
        if kwds:
            key += tuple(type(v) for (k, v) in sorted_items)
    elif len(key) == 1 and type(key[0]) in fasttypes:
        return key[0]
    return _HashedSeq(key)

def lru_cache(maxsize=128, typed=False):
    sentinel = object()
    make_key = _make_key
    (PREV, NEXT, KEY, RESULT) = (0, 1, 2, 3)

    def decorating_function(user_function):
        cache = {}
        hits = misses = 0
        full = False
        cache_get = cache.get
        lock = RLock()
        root = []
        root[:] = [root, root, None, None]
        if maxsize == 0:

            def wrapper(*args, **kwds):
                nonlocal misses
                result = user_function(*args, **kwds)
                misses += 1
                return result

        elif maxsize is None:

            def wrapper(*args, **kwds):
                nonlocal hits, misses
                key = make_key(args, kwds, typed)
                result = cache_get(key, sentinel)
                if result is not sentinel:
                    hits += 1
                    return result
                result = user_function(*args, **kwds)
                cache[key] = result
                misses += 1
                return result

        else:

            def wrapper(*args, **kwds):
                nonlocal hits, root, full, misses
                key = make_key(args, kwds, typed)
                with lock:
                    link = cache_get(key)
                    if link is not None:
                        (link_prev, link_next, _key, result) = link
                        link_prev[NEXT] = link_next
                        link_next[PREV] = link_prev
                        last = root[PREV]
                        last[NEXT] = root[PREV] = link
                        link[PREV] = last
                        link[NEXT] = root
                        hits += 1
                        return result
                result = user_function(*args, **kwds)
                with lock:
                    if key in cache:
                        pass
                    elif full:
                        oldroot = root
                        oldroot[KEY] = key
                        oldroot[RESULT] = result
                        root = oldroot[NEXT]
                        oldkey = root[KEY]
                        oldresult = root[RESULT]
                        root[KEY] = root[RESULT] = None
                        del cache[oldkey]
                        cache[key] = oldroot
                    else:
                        last = root[PREV]
                        link = [last, root, key, result]
                        last[NEXT] = root[PREV] = cache[key] = link
                        full = len(cache) >= maxsize
                    misses += 1
                return result

        def cache_info():
            with lock:
                return _CacheInfo(hits, misses, maxsize, len(cache))

        def cache_clear():
            nonlocal hits, misses, full
            with lock:
                cache.clear()
                root[:] = [root, root, None, None]
                hits = misses = 0
                full = False

        wrapper.cache_info = cache_info
        wrapper.cache_clear = cache_clear
        return update_wrapper(wrapper, user_function)

    return decorating_function

