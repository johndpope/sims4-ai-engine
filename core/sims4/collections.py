from _sims4_collections import frozendict
from sims4.utils import raiser

class ListSet(list):
    __qualname__ = 'ListSet'
    __slots__ = ()

    def __init__(self, iterable=()):
        super().__init__(())
        self.update(iterable)

    def add(self, value):
        if value not in self:
            super().append(value)

    def update(self, iterable):
        for value in iterable:
            self.add(value)

    def discard(self, value):
        if value in self:
            self.remove(value)

    def __eq__(self, other_set):
        if len(self) != len(other_set):
            return False
        return all(i in self for i in other_set)

    def __ne__(self, other):
        return not self.__eq__(other)

    __getitem__ = raiser(TypeError('ListSet object does not support indexing.'))
    __setitem__ = raiser(TypeError('ListSet object does not support item assignment.'))
    __delitem__ = raiser(TypeError('ListSet object does not support item deletion.'))
    append = extend = __add__ = raiser(AttributeError)

class AttributeDict(dict):
    __qualname__ = 'AttributeDict'
    __slots__ = ()
    __dict__ = property(lambda self: self)
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError("Key '{}' not found in {}".format(name, self))

    def __repr__(self):
        return '{}({})'.format(type(self).__name__, dict.__repr__(self))

    def copy(self):
        return self.__class__(self.items())

class FrozenAttributeDict(AttributeDict, frozendict):
    __qualname__ = 'FrozenAttributeDict'
    __slots__ = ()
    __setattr__ = frozendict.__setitem__
    __delattr__ = frozendict.__delitem__

