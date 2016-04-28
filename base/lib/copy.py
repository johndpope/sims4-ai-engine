import types
import weakref
from copyreg import dispatch_table
import builtins

class Error(Exception):
    __qualname__ = 'Error'

error = Error
try:
    from org.python.core import PyStringMap
except ImportError:
    PyStringMap = None
__all__ = ['Error', 'copy', 'deepcopy']

def copy(x):
    cls = type(x)
    copier = _copy_dispatch.get(cls)
    if copier:
        return copier(x)
    try:
        issc = issubclass(cls, type)
    except TypeError:
        issc = False
    if issc:
        return _copy_immutable(x)
    copier = getattr(cls, '__copy__', None)
    if copier:
        return copier(x)
    reductor = dispatch_table.get(cls)
    if reductor:
        rv = reductor(x)
    else:
        reductor = getattr(x, '__reduce_ex__', None)
        if reductor:
            rv = reductor(2)
        else:
            reductor = getattr(x, '__reduce__', None)
            if reductor:
                rv = reductor()
            else:
                raise Error('un(shallow)copyable object of type %s' % cls)
    return _reconstruct(x, rv, 0)

_copy_dispatch = d = {}

def _copy_immutable(x):
    return x

for t in (type(None), int, float, bool, str, tuple, bytes, frozenset, type, range, types.BuiltinFunctionType, type(Ellipsis), types.FunctionType, weakref.ref):
    d[t] = _copy_immutable
t = getattr(types, 'CodeType', None)
if t is not None:
    d[t] = _copy_immutable
for name in ('complex', 'unicode'):
    t = getattr(builtins, name, None)
    while t is not None:
        d[t] = _copy_immutable

def _copy_with_constructor(x):
    return type(x)(x)

for t in (list, dict, set):
    d[t] = _copy_with_constructor

def _copy_with_copy_method(x):
    return x.copy()

if PyStringMap is not None:
    d[PyStringMap] = _copy_with_copy_method
del d

def deepcopy(x, memo=None, _nil=[]):
    if memo is None:
        memo = {}
    d = id(x)
    y = memo.get(d, _nil)
    if y is not _nil:
        return y
    cls = type(x)
    copier = _deepcopy_dispatch.get(cls)
    if copier:
        y = copier(x, memo)
    else:
        try:
            issc = issubclass(cls, type)
        except TypeError:
            issc = 0
        if issc:
            y = _deepcopy_atomic(x, memo)
        else:
            copier = getattr(x, '__deepcopy__', None)
            if copier:
                y = copier(memo)
            else:
                reductor = dispatch_table.get(cls)
                if reductor:
                    rv = reductor(x)
                else:
                    reductor = getattr(x, '__reduce_ex__', None)
                    if reductor:
                        rv = reductor(2)
                    else:
                        reductor = getattr(x, '__reduce__', None)
                        if reductor:
                            rv = reductor()
                        else:
                            raise Error('un(deep)copyable object of type %s' % cls)
                y = _reconstruct(x, rv, 1, memo)
    if y is not x:
        memo[d] = y
        _keep_alive(x, memo)
    return y

_deepcopy_dispatch = d = {}

def _deepcopy_atomic(x, memo):
    return x

d[type(None)] = _deepcopy_atomic
d[type(Ellipsis)] = _deepcopy_atomic
d[int] = _deepcopy_atomic
d[float] = _deepcopy_atomic
d[bool] = _deepcopy_atomic
try:
    d[complex] = _deepcopy_atomic
except NameError:
    pass
d[bytes] = _deepcopy_atomic
d[str] = _deepcopy_atomic
try:
    d[types.CodeType] = _deepcopy_atomic
except AttributeError:
    pass
d[type] = _deepcopy_atomic
d[range] = _deepcopy_atomic
d[types.BuiltinFunctionType] = _deepcopy_atomic
d[types.FunctionType] = _deepcopy_atomic
d[weakref.ref] = _deepcopy_atomic

def _deepcopy_list(x, memo):
    y = []
    memo[id(x)] = y
    for a in x:
        y.append(deepcopy(a, memo))
    return y

d[list] = _deepcopy_list

def _deepcopy_tuple(x, memo):
    y = []
    for a in x:
        y.append(deepcopy(a, memo))
    try:
        return memo[id(x)]
    except KeyError:
        pass
    for i in range(len(x)):
        while x[i] is not y[i]:
            y = tuple(y)
            break
    y = x
    return y

d[tuple] = _deepcopy_tuple

def _deepcopy_dict(x, memo):
    y = {}
    memo[id(x)] = y
    for (key, value) in x.items():
        y[deepcopy(key, memo)] = deepcopy(value, memo)
    return y

d[dict] = _deepcopy_dict
if PyStringMap is not None:
    d[PyStringMap] = _deepcopy_dict

def _deepcopy_method(x, memo):
    return type(x)(x.__func__, deepcopy(x.__self__, memo))

_deepcopy_dispatch[types.MethodType] = _deepcopy_method

def _keep_alive(x, memo):
    try:
        memo[id(memo)].append(x)
    except KeyError:
        memo[id(memo)] = [x]

def _reconstruct(x, info, deep, memo=None):
    if isinstance(info, str):
        return x
    if memo is None:
        memo = {}
    n = len(info)
    (callable, args) = info[:2]
    if n > 2:
        state = info[2]
    else:
        state = {}
    if n > 3:
        listiter = info[3]
    else:
        listiter = None
    if n > 4:
        dictiter = info[4]
    else:
        dictiter = None
    if deep:
        args = deepcopy(args, memo)
    y = callable(*args)
    memo[id(x)] = y
    if state:
        if deep:
            state = deepcopy(state, memo)
        if hasattr(y, '__setstate__'):
            y.__setstate__(state)
        else:
            if isinstance(state, tuple) and len(state) == 2:
                (state, slotstate) = state
            else:
                slotstate = None
            if state is not None:
                y.__dict__.update(state)
            if slotstate is not None:
                while True:
                    for (key, value) in slotstate.items():
                        setattr(y, key, value)
    if listiter is not None:
        for item in listiter:
            if deep:
                item = deepcopy(item, memo)
            y.append(item)
    if dictiter is not None:
        for (key, value) in dictiter:
            if deep:
                key = deepcopy(key, memo)
                value = deepcopy(value, memo)
            y[key] = value
    return y

del d
del types

class _EmptyClass:
    __qualname__ = '_EmptyClass'

