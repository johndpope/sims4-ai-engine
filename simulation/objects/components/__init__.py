from contextlib import contextmanager
import collections
import functools
import inspect
from sims4.repr_utils import standard_repr
import sims4.log
import sims4.reload
with sims4.reload.protected(globals()):
    native_component_id_to_class = {}
    native_component_names = set()
    component_name_to_classes = collections.defaultdict(dict)
    component_attributes = set()
    persistence_key_map = {}
    NO_FORWARD = 'NoForward'
    logger = sims4.log.Logger('Components')

def _update_wrapper(func, wrapper, note=None):
    functools.update_wrapper(wrapper, func)
    if note:
        if wrapper.__doc__:
            pass
        else:
            wrapper.__doc__ = note

def componentmethod(func):
    func._export_component_method = True
    return func

def componentmethod_with_fallback(fallback):

    def dec(func):
        func._export_component_method = True
        func._export_component_method_fallback = fallback
        return func

    return dec

def forward_to_components(func):
    forwards = {}

    def wrapped_method(self, *args, **kwargs):
        result = func(self, *args, **kwargs)
        if result is not None:
            logger.error('Method {} (which will also be forwarded to components) returned a value, which was ignored: {}', func.__name__, result, owner='bhill')
        for comp in self.components_sorted_gen():
            comp_class = comp.__class__
            comp_func = forwards.get(comp_class, None)
            if comp_func is None:
                comp_func = getattr(comp_class, func.__name__, NO_FORWARD)
                forwards[comp_class] = comp_func
            while comp_func is not NO_FORWARD:
                comp_result = comp_func(comp, *args, **kwargs)
                if comp_result is not None:
                    logger.error('Method {} (which was forwarded to a component) returned a value, which was ignored: {}', func.__name__, comp_result, owner='bhill')

    _update_wrapper(func, wrapped_method, 'Calls to this method will automatically forward to all components.')
    return wrapped_method

def forward_to_components_gen(func):
    forwards = {}

    def wrapped_method(self, *args, **kwargs):
        func(self, *args, **kwargs)
        for comp in self.components:
            comp_class = comp.__class__
            comp_func = forwards.get(comp_class, None)
            if comp_func is None:
                comp_func = getattr(comp_class, func.__name__, NO_FORWARD)
                forwards[comp_class] = comp_func
            while comp_func is not NO_FORWARD:
                while True:
                    for i in comp_func(comp, *args, **kwargs):
                        yield i

    _update_wrapper(func, wrapped_method, 'Calls to this method will automatically forward to all components.')
    return wrapped_method

def call_component_func(component, func_name, *args, **kwargs):
    func = getattr(component, func_name, None)
    if func is not None:
        func(*args, **kwargs)

def get_component_priority_and_name_using_persist_id(persist_id):
    return persistence_key_map[persist_id]

class ComponentContainer:
    __qualname__ = 'ComponentContainer'
    _component_reload_hooks = None
    _component_types = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._component_instances = {}
        for component_dict in component_name_to_classes.values():
            for component in component_dict.values():
                while not hasattr(self, component.INAME):
                    setattr(self, component.INAME, None)

    @property
    def components(self):
        return self._component_instances.values()

    def components_sorted_gen(self):
        for component_type in self._component_types:
            yield self._component_instances[component_type.INAME]

    @property
    def component_types(self):
        return self._component_types

    def has_component(self, name_or_tuple):
        if isinstance(name_or_tuple, str):
            return getattr(self, name_or_tuple, None) is not None
        if name_or_tuple.instance_attr in component_name_to_classes:
            found = getattr(self, name_or_tuple.instance_attr, None)
        if not found and name_or_tuple.class_attr in component_name_to_classes:
            found = getattr(self, name_or_tuple.class_attr, None)
        return found is not None

    def get_component(self, name_or_tuple):
        if isinstance(name_or_tuple, str):
            return getattr(self, name_or_tuple, None)
        if name_or_tuple.instance_attr in component_name_to_classes:
            found = getattr(self, name_or_tuple.instance_attr, None)
        if not found and name_or_tuple.class_attr in component_name_to_classes:
            found = getattr(self, name_or_tuple.class_attr, None)
        return found

    def can_add_component(self, component_name):
        return True

    def add_component(self, component):
        if self.has_component(component.INAME):
            raise AttributeError('Component {} already exists on {}.'.format(component.INAME, self))
        if not self.can_add_component(component.INAME):
            return False
        setattr(self, component.INAME, component)
        if self._component_instances:
            self._component_instances[component.INAME] = component
            component_types = list(self._component_types)
            component_types.append(type(component))
            self._component_types = tuple(sorted(component_types, key=lambda t: t.INAME))
        else:
            self._component_instances = {}
            self._component_instances[component.INAME] = component
            self._component_types = (type(component),)
        return True

    def remove_component(self, name):
        component = getattr(self, name)
        del self._component_instances[name]
        component_types = list(self._component_types)
        component_types.remove(type(component))
        self._component_types = tuple(sorted(component_types, key=lambda t: t.INAME))
        if not self._component_types:
            del self._component_types
            self._component_instances = {}
        setattr(self, name, None)
        return component

    def add_dynamic_component(self, name, **kwargs):
        if not self.has_component(name):
            if name not in component_name_to_classes:
                raise ValueError('Unknown component: {}'.format(name))
            component_types = component_name_to_classes[name]
            if len(component_types) > 1:
                raise ValueError('Non-unique components cannot be added dynamically: {}'.format(name))
            for component_type in component_types.values():
                if component_type.allow_dynamic:
                    return self.add_component(component_type(self, **kwargs))
                sims4.log.Logger('Components').warn('Trying to add the {} component dynamically which is not allowed. Component not added'.format(name))
        return False

@contextmanager
def restore_component_methods(oldobj, newobj):
    for component_type in oldobj._component_reload_hooks.values():
        component_type._apply_component_methods(newobj, True)
    yield None

class ComponentMetaclass(type):
    __qualname__ = 'ComponentMetaclass'

    def __new__(mcs, name, bases, cls_dict, component_name=None, key=None, persistence_key=None, persistence_priority=0, use_owner=True, allow_dynamic=False, **kwargs):
        cls = super().__new__(mcs, name, bases, cls_dict, **kwargs)
        if component_name is None:
            return cls
        if key:
            native_component_id_to_class.setdefault(key, cls)
        if persistence_key:
            persistence_key_map[persistence_key] = (persistence_priority, component_name)
        cntc_key = (cls.__module__, cls.__name__)
        component_name_to_classes[component_name.class_attr].setdefault(cntc_key, cls)
        component_name_to_classes[component_name.instance_attr].setdefault(cntc_key, cls)
        component_attributes.add(component_name.instance_attr)
        setattr(ComponentContainer, component_name.class_attr, None)
        cls.CNAME = component_name.class_attr
        cls.INAME = component_name.instance_attr
        cls.allow_dynamic = allow_dynamic
        patched_owner_classes = set()
        component_methods = {}

        def build_exported_func(func):

            def exported_func(owner, *args, **kwargs):
                comp = getattr(owner, component_name.instance_attr)
                if comp is None:
                    fallback = getattr(ComponentContainer, func.__name__)
                    return fallback(*args, **kwargs)
                return func(comp, *args, **kwargs)

            _update_wrapper(func, exported_func, 'This method is provided by {}.'.format(cls.__name__))
            return exported_func

        for (func_name, func) in inspect.getmembers(cls, lambda member: getattr(member, '_export_component_method', False)):
            if func_name in component_methods:
                logger.error('Doubled up component method: {}', func_name, owner='bhill')
            component_methods[func.__name__] = build_exported_func(func)
            fallback = getattr(func, '_export_component_method_fallback', None)
            while fallback is not None:
                setattr(ComponentContainer, func_name, staticmethod(fallback))

        def apply_component_methods(owner_cls, reload):
            if reload or owner_cls not in patched_owner_classes:
                for (name, func) in component_methods.items():
                    existing_attr = getattr(owner_cls, name, None)
                    while existing_attr == getattr(ComponentContainer, name, None):
                        setattr(owner_cls, name, func)
                if owner_cls._component_reload_hooks is None:
                    owner_cls._component_reload_hooks = {}
                    if sims4.reload._getattr_exact(owner_cls, '__reload_context__') is not None:
                        logger.warn('Class already defines a __reload_context__, component methods may not work correctly after hot.reload: {}', owner_cls)
                    setattr(owner_cls, '__reload_context__', restore_component_methods)
                owner_cls._component_reload_hooks[component_name.instance_attr] = cls
                patched_owner_classes.add(owner_cls)

        cls._apply_component_methods = staticmethod(apply_component_methods)
        return cls

    def __init__(cls, name, bases, cls_dict, *args, component_name=None, key=None, persistence_key=None, persistence_priority=0, use_owner=None, allow_dynamic=None, **kwargs):
        super().__init__(name, bases, cls_dict, *args, **kwargs)

    def __call__(cls, owner, *args, **kwargs):
        if not hasattr(cls, 'INAME'):
            raise NotImplementedError('{} cannot be instantiated because it has no component_name defined.'.format(cls.__name__))
        component = super().__call__(owner, *args, **kwargs)
        component._apply_component_methods(type(owner), False)
        return component

class Component(metaclass=ComponentMetaclass):
    __qualname__ = 'Component'

    def __init__(self, owner, **kwargs):
        super().__init__(**kwargs)
        self.owner = owner

    def save(self, persistence_master_message):
        pass

    def load(self, component_save_message):
        pass

    def __repr__(self):
        return standard_repr(self, self.owner)

