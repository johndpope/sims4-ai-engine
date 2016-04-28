import sys

def _f():
    pass

FunctionType = type(_f)
LambdaType = type(lambda : None)
CodeType = type(_f.__code__)
MappingProxyType = type(type.__dict__)
SimpleNamespace = type(sys.implementation)

def _g():
    yield 1

GeneratorType = type(_g())

class _C:
    __qualname__ = '_C'

    def _m(self):
        pass

MethodType = type(_C()._m)
BuiltinFunctionType = type(len)
BuiltinMethodType = type([].append)
ModuleType = type(sys)
try:
    raise TypeError
except TypeError:
    tb = sys.exc_info()[2]
    TracebackType = type(tb)
    FrameType = type(tb.tb_frame)
    tb = None
    del tb
GetSetDescriptorType = type(FunctionType.__code__)
MemberDescriptorType = type(FunctionType.__globals__)
del sys
del _f
del _g
del _C

def new_class(name, bases=(), kwds=None, exec_body=None):
    (meta, ns, kwds) = prepare_class(name, bases, kwds)
    if exec_body is not None:
        exec_body(ns)
    return meta(name, bases, ns, **kwds)

def prepare_class(name, bases=(), kwds=None):
    if kwds is None:
        kwds = {}
    else:
        kwds = dict(kwds)
    if 'metaclass' in kwds:
        meta = kwds.pop('metaclass')
    elif bases:
        meta = type(bases[0])
    else:
        meta = type
    if isinstance(meta, type):
        meta = _calculate_meta(meta, bases)
    if hasattr(meta, '__prepare__'):
        ns = meta.__prepare__(name, bases, **kwds)
    else:
        ns = {}
    return (meta, ns, kwds)

def _calculate_meta(meta, bases):
    winner = meta
    for base in bases:
        base_meta = type(base)
        if issubclass(winner, base_meta):
            pass
        if issubclass(base_meta, winner):
            winner = base_meta
        raise TypeError('metaclass conflict: the metaclass of a derived class must be a (non-strict) subclass of the metaclasses of all its bases')
    return winner

