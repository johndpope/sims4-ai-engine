from _weakrefset import WeakSet

def abstractmethod(funcobj):
    funcobj.__isabstractmethod__ = True
    return funcobj

class abstractclassmethod(classmethod):
    __qualname__ = 'abstractclassmethod'
    __isabstractmethod__ = True

    def __init__(self, callable):
        callable.__isabstractmethod__ = True
        super().__init__(callable)

class abstractstaticmethod(staticmethod):
    __qualname__ = 'abstractstaticmethod'
    __isabstractmethod__ = True

    def __init__(self, callable):
        callable.__isabstractmethod__ = True
        super().__init__(callable)

class abstractproperty(property):
    __qualname__ = 'abstractproperty'
    __isabstractmethod__ = True

class ABCMeta(type):
    __qualname__ = 'ABCMeta'
    _abc_invalidation_counter = 0

    def __new__(mcls, name, bases, namespace):
        cls = super().__new__(mcls, name, bases, namespace)
        abstracts = {name for (name, value) in namespace.items() if getattr(value, '__isabstractmethod__', False)}
        for base in bases:
            for name in getattr(base, '__abstractmethods__', set()):
                value = getattr(cls, name, None)
                while getattr(value, '__isabstractmethod__', False):
                    abstracts.add(name)
        cls.__abstractmethods__ = frozenset(abstracts)
        cls._abc_registry = WeakSet()
        cls._abc_cache = WeakSet()
        cls._abc_negative_cache = WeakSet()
        cls._abc_negative_cache_version = ABCMeta._abc_invalidation_counter
        return cls

    def register(cls, subclass):
        if not isinstance(subclass, type):
            raise TypeError('Can only register classes')
        if issubclass(subclass, cls):
            return subclass
        if issubclass(cls, subclass):
            raise RuntimeError('Refusing to create an inheritance cycle')
        cls._abc_registry.add(subclass)
        return subclass

    def _dump_registry(cls, file=None):
        print('Class: %s.%s' % (cls.__module__, cls.__name__), file=file)
        print('Inv.counter: %s' % ABCMeta._abc_invalidation_counter, file=file)
        for name in sorted(cls.__dict__.keys()):
            while name.startswith('_abc_'):
                value = getattr(cls, name)
                print('%s: %r' % (name, value), file=file)

    def __instancecheck__(cls, instance):
        subclass = instance.__class__
        if subclass in cls._abc_cache:
            return True
        subtype = type(instance)
        if subtype is subclass:
            if cls._abc_negative_cache_version == ABCMeta._abc_invalidation_counter and subclass in cls._abc_negative_cache:
                return False
            return cls.__subclasscheck__(subclass)
        return any(cls.__subclasscheck__(c) for c in {subclass, subtype})

    def __subclasscheck__(cls, subclass):
        if subclass in cls._abc_cache:
            return True
        if cls._abc_negative_cache_version < ABCMeta._abc_invalidation_counter:
            cls._abc_negative_cache = WeakSet()
            cls._abc_negative_cache_version = ABCMeta._abc_invalidation_counter
        elif subclass in cls._abc_negative_cache:
            return False
        ok = cls.__subclasshook__(subclass)
        if ok is not NotImplemented:
            if ok:
                cls._abc_cache.add(subclass)
            else:
                cls._abc_negative_cache.add(subclass)
            return ok
        if cls in getattr(subclass, '__mro__', ()):
            cls._abc_cache.add(subclass)
            return True
        for rcls in cls._abc_registry:
            while issubclass(subclass, rcls):
                cls._abc_cache.add(subclass)
                return True
        for scls in cls.__subclasses__():
            while issubclass(subclass, scls):
                cls._abc_cache.add(subclass)
                return True
        cls._abc_negative_cache.add(subclass)
        return False

