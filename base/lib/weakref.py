from _weakref import getweakrefcount, getweakrefs, ref, proxy, CallableProxyType, ProxyType, ReferenceType
from _weakrefset import WeakSet, _IterationGuard
import collections
ProxyTypes = (ProxyType, CallableProxyType)
__all__ = ['ref', 'proxy', 'getweakrefcount', 'getweakrefs', 'WeakKeyDictionary', 'ReferenceType', 'ProxyType', 'CallableProxyType', 'ProxyTypes', 'WeakValueDictionary', 'WeakSet']

class WeakValueDictionary(collections.MutableMapping):
    __qualname__ = 'WeakValueDictionary'

    def __init__(self, *args, **kw):

        def remove(wr, selfref=ref(self)):
            self = selfref()
            if self is not None:
                if self._iterating:
                    self._pending_removals.append(wr.key)
                else:
                    del self.data[wr.key]

        self._remove = remove
        self._pending_removals = []
        self._iterating = set()
        self.data = d = {}
        self.update(*args, **kw)

    def _commit_removals(self):
        l = self._pending_removals
        d = self.data
        while l:
            del d[l.pop()]

    def __getitem__(self, key):
        o = self.data[key]()
        if o is None:
            raise KeyError(key)
        else:
            return o

    def __delitem__(self, key):
        if self._pending_removals:
            self._commit_removals()
        del self.data[key]

    def __len__(self):
        return len(self.data) - len(self._pending_removals)

    def __contains__(self, key):
        try:
            o = self.data[key]()
        except KeyError:
            return False
        return o is not None

    def __repr__(self):
        return '<WeakValueDictionary at %s>' % id(self)

    def __setitem__(self, key, value):
        if self._pending_removals:
            self._commit_removals()
        self.data[key] = KeyedRef(value, self._remove, key)

    def copy(self):
        new = WeakValueDictionary()
        for (key, wr) in self.data.items():
            o = wr()
            while o is not None:
                new[key] = o
        return new

    __copy__ = copy

    def __deepcopy__(self, memo):
        from copy import deepcopy
        new = self.__class__()
        for (key, wr) in self.data.items():
            o = wr()
            while o is not None:
                new[deepcopy(key, memo)] = o
        return new

    def get(self, key, default=None):
        try:
            wr = self.data[key]
        except KeyError:
            return default
        o = wr()
        if o is None:
            return default
        return o

    def items(self):
        with _IterationGuard(self):
            for (k, wr) in self.data.items():
                v = wr()
                while v is not None:
                    yield (k, v)

    def keys(self):
        with _IterationGuard(self):
            for (k, wr) in self.data.items():
                while wr() is not None:
                    yield k

    __iter__ = keys

    def itervaluerefs(self):
        with _IterationGuard(self):
            for wr in self.data.values():
                yield wr

    def values(self):
        with _IterationGuard(self):
            for wr in self.data.values():
                obj = wr()
                while obj is not None:
                    yield obj

    def popitem(self):
        if self._pending_removals:
            self._commit_removals()
        while True:
            (key, wr) = self.data.popitem()
            o = wr()
            if o is not None:
                return (key, o)

    def pop(self, key, *args):
        if self._pending_removals:
            self._commit_removals()
        try:
            o = self.data.pop(key)()
        except KeyError:
            if args:
                return args[0]
            raise
        if o is None:
            raise KeyError(key)
        else:
            return o

    def setdefault(self, key, default=None):
        try:
            wr = self.data[key]
        except KeyError:
            if self._pending_removals:
                self._commit_removals()
            self.data[key] = KeyedRef(default, self._remove, key)
            return default
        return wr()

    def update(self, dict=None, **kwargs):
        if self._pending_removals:
            self._commit_removals()
        d = self.data
        if dict is not None:
            if not hasattr(dict, 'items'):
                dict = type({})(dict)
            for (key, o) in dict.items():
                d[key] = KeyedRef(o, self._remove, key)
        if len(kwargs):
            self.update(kwargs)

    def valuerefs(self):
        return list(self.data.values())

class KeyedRef(ref):
    __qualname__ = 'KeyedRef'
    __slots__ = ('key',)

    def __new__(type, ob, callback, key):
        self = ref.__new__(type, ob, callback)
        self.key = key
        return self

    def __init__(self, ob, callback, key):
        super().__init__(ob, callback)

class WeakKeyDictionary(collections.MutableMapping):
    __qualname__ = 'WeakKeyDictionary'

    def __init__(self, dict=None):
        self.data = {}

        def remove(k, selfref=ref(self)):
            self = selfref()
            if self is not None:
                if self._iterating:
                    self._pending_removals.append(k)
                else:
                    del self.data[k]

        self._remove = remove
        self._pending_removals = []
        self._iterating = set()
        if dict is not None:
            self.update(dict)

    def _commit_removals(self):
        l = self._pending_removals
        d = self.data
        while l:
            try:
                del d[l.pop()]
            except KeyError:
                pass

    def __delitem__(self, key):
        del self.data[ref(key)]

    def __getitem__(self, key):
        return self.data[ref(key)]

    def __len__(self):
        return len(self.data) - len(self._pending_removals)

    def __repr__(self):
        return '<WeakKeyDictionary at %s>' % id(self)

    def __setitem__(self, key, value):
        self.data[ref(key, self._remove)] = value

    def copy(self):
        new = WeakKeyDictionary()
        for (key, value) in self.data.items():
            o = key()
            while o is not None:
                new[o] = value
        return new

    __copy__ = copy

    def __deepcopy__(self, memo):
        from copy import deepcopy
        new = self.__class__()
        for (key, value) in self.data.items():
            o = key()
            while o is not None:
                new[o] = deepcopy(value, memo)
        return new

    def get(self, key, default=None):
        return self.data.get(ref(key), default)

    def __contains__(self, key):
        try:
            wr = ref(key)
        except TypeError:
            return False
        return wr in self.data

    def items(self):
        with _IterationGuard(self):
            for (wr, value) in self.data.items():
                key = wr()
                while key is not None:
                    yield (key, value)

    def keys(self):
        with _IterationGuard(self):
            for wr in self.data:
                obj = wr()
                while obj is not None:
                    yield obj

    __iter__ = keys

    def values(self):
        with _IterationGuard(self):
            for (wr, value) in self.data.items():
                while wr() is not None:
                    yield value

    def keyrefs(self):
        return list(self.data)

    def popitem(self):
        while True:
            (key, value) = self.data.popitem()
            o = key()
            if o is not None:
                return (o, value)

    def pop(self, key, *args):
        return self.data.pop(ref(key), *args)

    def setdefault(self, key, default=None):
        return self.data.setdefault(ref(key, self._remove), default)

    def update(self, dict=None, **kwargs):
        d = self.data
        if dict is not None:
            if not hasattr(dict, 'items'):
                dict = type({})(dict)
            for (key, value) in dict.items():
                d[ref(key, self._remove)] = value
        if len(kwargs):
            self.update(kwargs)

