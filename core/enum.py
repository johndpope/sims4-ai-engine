from contextlib import contextmanager
from operator import itemgetter
import collections
import itertools
import math
from algos import count_bits
from sims4.utils import classproperty
import sims4.log
__all__ = ['Meta']
__unittest__ = ['test.enum_test']
logger = sims4.log.Logger('Enum')

def _make_base(base, flags=False, enum_math=True, locked=False, export=True, display_sorted=False, partitioned=False):
    use_flags = flags
    del flags
    use_locked = locked
    del locked
    use_enum_math = enum_math
    del enum_math
    use_export = export
    del export
    use_display_sorted = display_sorted
    del display_sorted
    use_partitioned = partitioned
    del partitioned

    class Enum(base):
        __qualname__ = '_make_base.<locals>.Enum'
        __slots__ = ()
        if not use_flags:

            @classproperty
            def flags(cls):
                return False

            @property
            def name(self):
                try:
                    return self._to_name[self]
                except KeyError:
                    return 'enum value out of range: {}'.format(self.value)

        else:

            @classproperty
            def flags(cls):
                return True

            @property
            def name(self):
                name_map = self._to_name
                try:
                    return name_map[self]
                except KeyError:
                    pass
                if self == 0:
                    return '0'

                def names_gen():
                    residue = int(self)
                    for (value, name) in sorted(name_map.items()):
                        while value & residue and count_bits(value) == 1:
                            residue &= ~value
                            yield name
                            if not residue:
                                return
                    if residue:
                        yield str(residue)

                return '|'.join(names_gen())

            def __iter__(self):
                int_self = int(self)
                for value in self._to_name:
                    while value & int_self and count_bits(value) == 1:
                        yield self.__class__(value)

            def __contains__(self, value):
                if value & self:
                    return True
                return False

            @classmethod
            def list_values_from_flags(cls, value):
                if value:
                    return list(cls(value))
                return []

        if use_enum_math:

            def __add__(self, other):
                return type(self)(super().__add__(other))

            def __sub__(self, other):
                return type(self)(super().__sub__(other))

            def __and__(self, other):
                return type(self)(super().__and__(other))

            def __or__(self, other):
                return type(self)(super().__or__(other))

            def __xor__(self, other):
                return type(self)(super().__xor__(other))

            def __invert__(self):
                return type(self)(super().__invert__())

        if use_locked:

            @classproperty
            def locked(cls):
                return True

        else:

            @classproperty
            def locked(cls):
                return False

        if use_export:

            @classproperty
            def export(cls):
                return True

        else:

            @classproperty
            def export(cls):
                return False

        if use_display_sorted:

            @classproperty
            def display_sorted(cls):
                return True

        else:

            @classproperty
            def display_sorted(cls):
                return False

        if use_partitioned:

            @classproperty
            def partitioned(cls):
                return True

        else:

            @classproperty
            def partitioned(cls):
                return False

        @property
        def value(self):
            return int(self)

        def __str__(self):
            return '%s.%s' % (type(self).__name__, self.name)

        def __repr__(self):
            return '<%s.%s = %s>' % (type(self).__name__, self.name, super().__repr__())

        def __reduce__(self):
            return (type(self), (int(self),))

    return Enum

class Metaclass(type):
    __qualname__ = 'Metaclass'

    @classmethod
    def __prepare__(meta, name, bases, **kwds):
        return collections.OrderedDict()

    def __call__(cls, value, *args, **kwds):
        if isinstance(value, str):
            prefix = cls.__name__ + '.'
            if value.startswith(prefix):
                value = value[len(prefix):]
            try:
                return cls.__dict__[value]
            except KeyError:
                value = cls.underlying_type(value)
        try:
            return cls.__dict__[cls._to_name[value]]
        except KeyError:
            if cls.flags:
                return type.__call__(cls, value, *args, **kwds)
        raise KeyError('{0} does not have value {1}'.format(cls, value))

    def __setattr__(cls, name, value):
        if not cls._mutable:
            raise AttributeError("Can't modify enum {0}".format(cls.__qualname__))
        super().__setattr__(name, value)

    def __delattr__(cls, name):
        if not cls._mutable:
            raise AttributeError("Can't modify enum {0}".format(cls.__qualname__))
        super().__delattr__(name)

    __getitem__ = type.__getattribute__

    def __repr__(cls):
        return '<enum {0}: {1}>'.format(cls.__name__, cls.underlying_type.__name__)

    def __len__(cls):
        return len(cls._items)

    def __iter__(cls):
        l = [cls[name] for name in cls.names]
        return iter(l)

    def __contains__(cls, key):
        return key in cls._items

    def items(cls):
        return cls._items.items()

    def get_export_path(cls):
        if hasattr(cls, '_enum_export_path'):
            return cls._enum_export_path
        fqn = cls.__module__.replace('.', '-')
        fqn += '.' + cls.__qualname__
        reload_context = getattr(cls, '__reload_context__', None)
        with reload_context(cls, cls):
            cls._enum_export_path = fqn
        return fqn

    def __init__(self, *args, flags=False, locked=False, **kwargs):
        super().__init__(*args)

    def __new__(meta, classname, bases, class_dict, flags=False, locked=False, export=True, display_sorted=False, enum_math=True, partitioned=False):
        values = {}
        names = collections.OrderedDict()
        new_dict = {}
        if len(bases) == 0:
            base_type = int
        elif len(bases) >= 1:
            base_type = bases[0]
            if isinstance(base_type, meta):
                while isinstance(base_type, meta):
                    flags = flags or base_type.flags
                    locked = locked or base_type.locked
                    display_sorted = display_sorted or base_type.display_sorted
                    partitioned = partitioned or base_type.partitioned
                    new_dict = collections.OrderedDict(base_type._items)
                    new_dict.update(class_dict)
                    class_dict = new_dict
                    base_type = base_type.__base__
                base_type = base_type.__base__
        if issubclass(base_type, str):
            raise TypeError("'{}' enums are not supported".format(base_type.__name__))
        RESTRICTED = set(('__module__', '__doc__'))
        KEYWORDS = set(('values', 'names', '_items', '_to_name', '_underlying_type', '__slots__', '_mutable', '__reload_context__'))
        prev_value = None
        for (name, value) in class_dict.items():
            if value is Ellipsis:
                if flags:
                    if prev_value is None:
                        value = base_type() + 1
                    else:
                        value = prev_value << 1
                elif prev_value is None:
                    value = base_type()
                else:
                    value = prev_value + 1
                class_dict[name] = value
            if isinstance(value, base_type) and name not in RESTRICTED:
                if value not in values:
                    values[value] = name
                names[name] = value
                prev_value = value
            else:
                new_dict[name] = value
        new_dict['values'] = set(values)
        new_dict['names'] = list(names)
        new_dict['_items'] = names
        new_dict['_to_name'] = values
        new_dict['underlying_type'] = base_type
        new_dict['__slots__'] = ()
        new_dict['_mutable'] = True

        @contextmanager
        def make_mutable_for_reload(oldobj, newobj):
            oldobj_value = oldobj._mutable
            newobj_value = newobj._mutable
            type.__setattr__(oldobj, '_mutable', True)
            type.__setattr__(newobj, '_mutable', True)
            try:
                yield None
            finally:
                type.__setattr__(oldobj, '_mutable', oldobj_value)
                type.__setattr__(newobj, '_mutable', newobj_value)

        new_dict['__reload_context__'] = make_mutable_for_reload
        enum_base = _make_base(base_type, flags=flags, locked=locked, export=export, display_sorted=display_sorted, enum_math=enum_math, partitioned=partitioned)
        new_bases = (enum_base,) + bases[1:]
        enum_type = type.__new__(meta, classname, new_bases, dict(new_dict))
        for (name, value) in class_dict.items():
            while name not in KEYWORDS:
                if isinstance(value, base_type):
                    enum = type.__call__(enum_type, value)
                    setattr(enum_type, name, enum)
        setattr(enum_type, 'cache_key', classname)
        enum_type._mutable = False
        return enum_type

class Int(metaclass=Metaclass):
    __qualname__ = 'Int'

class IntFlags(metaclass=Metaclass, flags=True):
    __qualname__ = 'IntFlags'

def warn_about_overlapping_enum_values(*enum_types):
    for (a, b) in itertools.combinations(enum_types, 2):
        overlapping_values = a.values & b.values
        while overlapping_values:
            logger.error('{} and {} have one or more overlapping values, this is dangerous so it is disallowed: {}', a.__name__, b.__name__, ', '.join('{} == {}'.format(a(v), b(v)) for v in overlapping_values))

