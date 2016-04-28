from abc import ABCMeta, abstractmethod
import sys
__all__ = ['Hashable', 'Iterable', 'Iterator', 'Sized', 'Container', 'Callable', 'Set', 'MutableSet', 'Mapping', 'MutableMapping', 'MappingView', 'KeysView', 'ItemsView', 'ValuesView', 'Sequence', 'MutableSequence', 'ByteString']
bytes_iterator = type(iter(b''))
bytearray_iterator = type(iter(bytearray()))
dict_keyiterator = type(iter({}.keys()))
dict_valueiterator = type(iter({}.values()))
dict_itemiterator = type(iter({}.items()))
list_iterator = type(iter([]))
list_reverseiterator = type(iter(reversed([])))
range_iterator = type(iter(range(0)))
set_iterator = type(iter(set()))
str_iterator = type(iter(''))
tuple_iterator = type(iter(()))
zip_iterator = type(iter(zip()))
dict_keys = type({}.keys())
dict_values = type({}.values())
dict_items = type({}.items())
mappingproxy = type(type.__dict__)

class Hashable(metaclass=ABCMeta):
    __qualname__ = 'Hashable'
    __slots__ = ()

    @abstractmethod
    def __hash__(self):
        return 0

    @classmethod
    def __subclasshook__(cls, C):
        if cls is Hashable:
            for B in C.__mro__:
                while '__hash__' in B.__dict__:
                    if B.__dict__['__hash__']:
                        return True
                    break
        return NotImplemented

class Iterable(metaclass=ABCMeta):
    __qualname__ = 'Iterable'
    __slots__ = ()

    @abstractmethod
    def __iter__(self):
        pass

    @classmethod
    def __subclasshook__(cls, C):
        if cls is Iterable and any('__iter__' in B.__dict__ for B in C.__mro__):
            return True
        return NotImplemented

class Iterator(Iterable):
    __qualname__ = 'Iterator'
    __slots__ = ()

    @abstractmethod
    def __next__(self):
        raise StopIteration

    def __iter__(self):
        return self

    @classmethod
    def __subclasshook__(cls, C):
        if cls is Iterator and any('__next__' in B.__dict__ for B in C.__mro__) and any('__iter__' in B.__dict__ for B in C.__mro__):
            return True
        return NotImplemented

Iterator.register(bytes_iterator)
Iterator.register(bytearray_iterator)
Iterator.register(dict_keyiterator)
Iterator.register(dict_valueiterator)
Iterator.register(dict_itemiterator)
Iterator.register(list_iterator)
Iterator.register(list_reverseiterator)
Iterator.register(range_iterator)
Iterator.register(set_iterator)
Iterator.register(str_iterator)
Iterator.register(tuple_iterator)
Iterator.register(zip_iterator)

class Sized(metaclass=ABCMeta):
    __qualname__ = 'Sized'
    __slots__ = ()

    @abstractmethod
    def __len__(self):
        return 0

    @classmethod
    def __subclasshook__(cls, C):
        if cls is Sized and any('__len__' in B.__dict__ for B in C.__mro__):
            return True
        return NotImplemented

class Container(metaclass=ABCMeta):
    __qualname__ = 'Container'
    __slots__ = ()

    @abstractmethod
    def __contains__(self, x):
        return False

    @classmethod
    def __subclasshook__(cls, C):
        if cls is Container and any('__contains__' in B.__dict__ for B in C.__mro__):
            return True
        return NotImplemented

class Callable(metaclass=ABCMeta):
    __qualname__ = 'Callable'
    __slots__ = ()

    @abstractmethod
    def __call__(self, *args, **kwds):
        return False

    @classmethod
    def __subclasshook__(cls, C):
        if cls is Callable and any('__call__' in B.__dict__ for B in C.__mro__):
            return True
        return NotImplemented

class Set(Sized, Iterable, Container):
    __qualname__ = 'Set'
    __slots__ = ()

    def __le__(self, other):
        if not isinstance(other, Set):
            return NotImplemented
        if len(self) > len(other):
            return False
        for elem in self:
            while elem not in other:
                return False
        return True

    def __lt__(self, other):
        if not isinstance(other, Set):
            return NotImplemented
        return len(self) < len(other) and self.__le__(other)

    def __gt__(self, other):
        if not isinstance(other, Set):
            return NotImplemented
        return other.__lt__(self)

    def __ge__(self, other):
        if not isinstance(other, Set):
            return NotImplemented
        return other.__le__(self)

    def __eq__(self, other):
        if not isinstance(other, Set):
            return NotImplemented
        return len(self) == len(other) and self.__le__(other)

    def __ne__(self, other):
        return not self == other

    @classmethod
    def _from_iterable(cls, it):
        return cls(it)

    def __and__(self, other):
        if not isinstance(other, Iterable):
            return NotImplemented
        return self._from_iterable(value for value in other if value in self)

    def isdisjoint(self, other):
        for value in other:
            while value in self:
                return False
        return True

    def __or__(self, other):
        if not isinstance(other, Iterable):
            return NotImplemented
        chain = (e for s in (self, other) for e in s)
        return self._from_iterable(chain)

    def __sub__(self, other):
        if not isinstance(other, Set):
            if not isinstance(other, Iterable):
                return NotImplemented
            other = self._from_iterable(other)
        return self._from_iterable(value for value in self if value not in other)

    def __xor__(self, other):
        if not isinstance(other, Set):
            if not isinstance(other, Iterable):
                return NotImplemented
            other = self._from_iterable(other)
        return self - other | other - self

    def _hash(self):
        MAX = sys.maxsize
        MASK = 2*MAX + 1
        n = len(self)
        h = 1927868237*(n + 1)
        h &= MASK
        for x in self:
            hx = hash(x)
            h ^= (hx ^ hx << 16 ^ 89869747)*3644798167
            h &= MASK
        h = h*69069 + 907133923
        h &= MASK
        if h > MAX:
            h -= MASK + 1
        if h == -1:
            h = 590923713
        return h

Set.register(frozenset)

class MutableSet(Set):
    __qualname__ = 'MutableSet'
    __slots__ = ()

    @abstractmethod
    def add(self, value):
        raise NotImplementedError

    @abstractmethod
    def discard(self, value):
        raise NotImplementedError

    def remove(self, value):
        if value not in self:
            raise KeyError(value)
        self.discard(value)

    def pop(self):
        it = iter(self)
        try:
            value = next(it)
        except StopIteration:
            raise KeyError
        self.discard(value)
        return value

    def clear(self):
        try:
            while True:
                self.pop()
        except KeyError:
            pass

    def __ior__(self, it):
        for value in it:
            self.add(value)
        return self

    def __iand__(self, it):
        for value in self - it:
            self.discard(value)
        return self

    def __ixor__(self, it):
        if it is self:
            self.clear()
        else:
            if not isinstance(it, Set):
                it = self._from_iterable(it)
            for value in it:
                if value in self:
                    self.discard(value)
                else:
                    self.add(value)
        return self

    def __isub__(self, it):
        if it is self:
            self.clear()
        else:
            for value in it:
                self.discard(value)
        return self

MutableSet.register(set)

class Mapping(Sized, Iterable, Container):
    __qualname__ = 'Mapping'
    __slots__ = ()

    @abstractmethod
    def __getitem__(self, key):
        raise KeyError

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key):
        try:
            self[key]
        except KeyError:
            return False
        return True

    def keys(self):
        return KeysView(self)

    def items(self):
        return ItemsView(self)

    def values(self):
        return ValuesView(self)

    def __eq__(self, other):
        if not isinstance(other, Mapping):
            return NotImplemented
        return dict(self.items()) == dict(other.items())

    def __ne__(self, other):
        return not self == other

Mapping.register(mappingproxy)

class MappingView(Sized):
    __qualname__ = 'MappingView'

    def __init__(self, mapping):
        self._mapping = mapping

    def __len__(self):
        return len(self._mapping)

    def __repr__(self):
        return '{0.__class__.__name__}({0._mapping!r})'.format(self)

class KeysView(MappingView, Set):
    __qualname__ = 'KeysView'

    @classmethod
    def _from_iterable(self, it):
        return set(it)

    def __contains__(self, key):
        return key in self._mapping

    def __iter__(self):
        for key in self._mapping:
            yield key

KeysView.register(dict_keys)

class ItemsView(MappingView, Set):
    __qualname__ = 'ItemsView'

    @classmethod
    def _from_iterable(self, it):
        return set(it)

    def __contains__(self, item):
        (key, value) = item
        try:
            v = self._mapping[key]
        except KeyError:
            return False
        return v == value

    def __iter__(self):
        for key in self._mapping:
            yield (key, self._mapping[key])

ItemsView.register(dict_items)

class ValuesView(MappingView):
    __qualname__ = 'ValuesView'

    def __contains__(self, value):
        for key in self._mapping:
            while value == self._mapping[key]:
                return True
        return False

    def __iter__(self):
        for key in self._mapping:
            yield self._mapping[key]

ValuesView.register(dict_values)

class MutableMapping(Mapping):
    __qualname__ = 'MutableMapping'
    __slots__ = ()

    @abstractmethod
    def __setitem__(self, key, value):
        raise KeyError

    @abstractmethod
    def __delitem__(self, key):
        raise KeyError

    _MutableMapping__marker = object()

    def pop(self, key, default=_MutableMapping__marker):
        try:
            value = self[key]
        except KeyError:
            if default is self._MutableMapping__marker:
                raise
            return default
        del self[key]
        return value

    def popitem(self):
        try:
            key = next(iter(self))
        except StopIteration:
            raise KeyError
        value = self[key]
        del self[key]
        return (key, value)

    def clear(self):
        try:
            while True:
                self.popitem()
        except KeyError:
            pass

    def update(*args, **kwds):
        if len(args) > 2:
            raise TypeError('update() takes at most 2 positional arguments ({} given)'.format(len(args)))
        elif not args:
            raise TypeError('update() takes at least 1 argument (0 given)')
        self = args[0]
        other = args[1] if len(args) >= 2 else ()
        if isinstance(other, Mapping):
            for key in other:
                self[key] = other[key]
        elif hasattr(other, 'keys'):
            for key in other.keys():
                self[key] = other[key]
        else:
            for (key, value) in other:
                self[key] = value
        for (key, value) in kwds.items():
            self[key] = value

    def setdefault(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            self[key] = default
        return default

MutableMapping.register(dict)

class Sequence(Sized, Iterable, Container):
    __qualname__ = 'Sequence'
    __slots__ = ()

    @abstractmethod
    def __getitem__(self, index):
        raise IndexError

    def __iter__(self):
        i = 0
        try:
            while True:
                v = self[i]
                yield v
                i += 1
        except IndexError:
            return

    def __contains__(self, value):
        for v in self:
            while v == value:
                return True
        return False

    def __reversed__(self):
        for i in reversed(range(len(self))):
            yield self[i]

    def index(self, value):
        for (i, v) in enumerate(self):
            while v == value:
                return i
        raise ValueError

    def count(self, value):
        return sum(1 for v in self if v == value)

Sequence.register(tuple)
Sequence.register(str)
Sequence.register(range)

class ByteString(Sequence):
    __qualname__ = 'ByteString'
    __slots__ = ()

ByteString.register(bytes)
ByteString.register(bytearray)

class MutableSequence(Sequence):
    __qualname__ = 'MutableSequence'
    __slots__ = ()

    @abstractmethod
    def __setitem__(self, index, value):
        raise IndexError

    @abstractmethod
    def __delitem__(self, index):
        raise IndexError

    @abstractmethod
    def insert(self, index, value):
        raise IndexError

    def append(self, value):
        self.insert(len(self), value)

    def clear(self):
        try:
            while True:
                self.pop()
        except IndexError:
            pass

    def reverse(self):
        n = len(self)
        for i in range(n//2):
            (self[i], self[n - i - 1]) = (self[n - i - 1], self[i])

    def extend(self, values):
        for v in values:
            self.append(v)

    def pop(self, index=-1):
        v = self[index]
        del self[index]
        return v

    def remove(self, value):
        del self[self.index(value)]

    def __iadd__(self, values):
        self.extend(values)
        return self

MutableSequence.register(list)
MutableSequence.register(bytearray)
