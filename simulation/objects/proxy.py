import _weakrefutils
import weakref
from sims4.repr_utils import standard_repr
import sims4.log
logger = sims4.log.Logger('Proxy')

class ProxyObject:
    __qualname__ = 'ProxyObject'
    _unproxied_attributes = {'_proxied_obj_ref'}

    def __new__(cls, proxied_obj, *args, **kwargs):
        if hasattr(cls, '_class_proxy_cache'):
            cache = cls._class_proxy_cache
        else:
            cache = cls._class_proxy_cache = {}
        proxied_type = type(proxied_obj)
        if proxied_type in cache:
            return object.__new__(cache[proxied_type])
        class_dict = {'proxied_attributes': set(), 'shortcuts': cls._unproxied_attributes | {'__dict__', 'proxied_obj', 'get_proxied_obj'}, '__doc__': 'This is a class for proxying instances of {}.'.format(proxied_type) + ('\n\n' + cls.__doc__ if cls.__doc__ else '')}
        proxy_type = type('{}({})'.format(cls.__qualname__, proxied_type.__qualname__), (cls, proxied_type), class_dict)
        cache[proxied_type] = proxy_type
        return object.__new__(proxy_type)

    def __init__(self, proxied_obj):
        object.__setattr__(self, '_proxied_obj_ref', weakref.ref(proxied_obj, self.on_proxied_object_removed))

    def on_proxied_object_removed(self, proxied_obj_ref):
        _weakrefutils.clear_weak_refs(self)

    def get_proxied_obj(self):
        proxied_obj_ref = self._proxied_obj_ref
        if proxied_obj_ref is None:
            return
        return proxied_obj_ref()

    @property
    def proxied_obj(self):
        proxied_obj_ref = object.__getattribute__(self, '_proxied_obj_ref')
        if proxied_obj_ref is None:
            raise AttributeError('The proxied object reference is None on {} instance'.format(type(self)))
        proxied_obj = proxied_obj_ref()
        if proxied_obj is None:
            raise AttributeError('When called, the proxied object reference evaluates to None on {} instance'.format(type(self)))
        return proxied_obj

    def __getattr__(self, name):
        if name in self._unproxied_attributes:
            raise AttributeError('unproxied attribute not initialized: ' + name)
        proxied_obj = self.get_proxied_obj()
        if proxied_obj is None:
            raise AttributeError('Proxied Object is None so we cannot grab any of its attributes.')
        return getattr(proxied_obj, name)

    def __delattr__(self, name):
        cls = type(self)
        if name in cls.shortcuts:
            return object.__delattr__(self, name)
        property_test = getattr(type(self), name, None)
        if isinstance(property_test, property):
            cls.shortcuts.add(name)
            return property_test.fdel(self)
        cls.proxied_attributes.add(name)
        return delattr(self.proxied_obj, name)

    def __setattr__(self, name, value):
        cls = type(self)
        if name in cls.shortcuts:
            return object.__setattr__(self, name, value)
        property_test = getattr(type(self), name, None)
        if isinstance(property_test, property):
            cls.shortcuts.add(name)
            return property_test.fset(self, value)
        cls.proxied_attributes.add(name)
        return setattr(self.proxied_obj, name, value)

    def __repr__(self):
        return standard_repr(self, self.get_proxied_obj())

    class _WeakRef:
        __qualname__ = 'ProxyObject._WeakRef'

        def __init__(self, proxy, callback):
            self._proxy = proxy
            self._weakref = proxy.proxied_obj.ref(callback)

        def __call__(self):
            if self._proxy.get_proxied_obj() is not None:
                return self._proxy

    def ref(self, callback=None):
        if callback is None:
            return self.ref_callback
        return self._WeakRef(self, callback)

    def ref_callback(self):
        if self.get_proxied_obj() is not None:
            return self

    @property
    def client_objects_gen(self):
        proxied_obj = self.get_proxied_obj()
        if proxied_obj is not None:
            yield proxied_obj

