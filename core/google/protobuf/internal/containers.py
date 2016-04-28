__author__ = 'petar@google.com (Petar Petrov)'

def cmp(a, b):
    return (a > b) - (a < b)

def cmp_to_key(mycmp):

    class K(object):
        __qualname__ = 'cmp_to_key.<locals>.K'

        def __init__(self, obj, *args):
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

    return K

class BaseContainer(object):
    __qualname__ = 'BaseContainer'
    __slots__ = ['_message_listener', '_values']

    def __init__(self, message_listener):
        self._message_listener = message_listener
        self._values = []

    def __getitem__(self, key):
        return self._values[key]

    def __len__(self):
        return len(self._values)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        raise TypeError('unhashable object')

    def __repr__(self):
        return repr(self._values)

    def sort(self, *args, **kwargs):
        if 'sort_function' in kwargs:
            kwargs['cmp'] = kwargs.pop('sort_function')
        self._values.sort(*args, **kwargs)

class RepeatedScalarFieldContainer(BaseContainer):
    __qualname__ = 'RepeatedScalarFieldContainer'
    __slots__ = ['_type_checker']

    def __init__(self, message_listener, type_checker):
        super(RepeatedScalarFieldContainer, self).__init__(message_listener)
        self._type_checker = type_checker

    def append(self, value):
        self._type_checker.CheckValue(value)
        self._values.append(value)
        if not self._message_listener.dirty:
            self._message_listener.Modified()

    def insert(self, key, value):
        self._type_checker.CheckValue(value)
        self._values.insert(key, value)
        if not self._message_listener.dirty:
            self._message_listener.Modified()

    def extend(self, elem_seq):
        if not elem_seq:
            return
        new_values = []
        for elem in elem_seq:
            self._type_checker.CheckValue(elem)
            new_values.append(elem)
        self._values.extend(new_values)
        self._message_listener.Modified()

    def MergeFrom(self, other):
        self._values.extend(other._values)
        self._message_listener.Modified()

    def remove(self, elem):
        self._values.remove(elem)
        self._message_listener.Modified()

    def __setitem__(self, key, value):
        self._type_checker.CheckValue(value)
        self._values[key] = value
        self._message_listener.Modified()

    def __getslice__(self, start, stop):
        return self._values[start:stop]

    def __setslice__(self, start, stop, values):
        new_values = []
        for value in values:
            self._type_checker.CheckValue(value)
            new_values.append(value)
        self._values[start:stop] = new_values
        self._message_listener.Modified()

    def __delitem__(self, key):
        del self._values[key]
        self._message_listener.Modified()

    def __delslice__(self, start, stop):
        del self._values[start:stop]
        self._message_listener.Modified()

    def __eq__(self, other):
        if self is other:
            return True
        if isinstance(other, self.__class__):
            return other._values == self._values
        return other == self._values

class RepeatedCompositeFieldContainer(BaseContainer):
    __qualname__ = 'RepeatedCompositeFieldContainer'
    __slots__ = ['_message_descriptor']

    def __init__(self, message_listener, message_descriptor):
        super(RepeatedCompositeFieldContainer, self).__init__(message_listener)
        self._message_descriptor = message_descriptor

    def add(self, **kwargs):
        new_element = self._message_descriptor._concrete_class(**kwargs)
        new_element._SetListener(self._message_listener)
        self._values.append(new_element)
        if not self._message_listener.dirty:
            self._message_listener.Modified()
        return new_element

    def extend(self, elem_seq):
        message_class = self._message_descriptor._concrete_class
        listener = self._message_listener
        values = self._values
        for message in elem_seq:
            new_element = message_class()
            new_element._SetListener(listener)
            new_element.MergeFrom(message)
            values.append(new_element)
        listener.Modified()

    def MergeFrom(self, other):
        self.extend(other._values)

    def remove(self, elem):
        self._values.remove(elem)
        self._message_listener.Modified()

    def __getslice__(self, start, stop):
        return self._values[start:stop]

    def __delitem__(self, key):
        del self._values[key]
        self._message_listener.Modified()

    def __delslice__(self, start, stop):
        del self._values[start:stop]
        self._message_listener.Modified()

    def __eq__(self, other):
        if self is other:
            return True
        if not isinstance(other, self.__class__):
            raise TypeError('Can only compare repeated composite fields against other repeated composite fields.')
        return self._values == other._values

