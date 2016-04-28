from _pyio import StringIO
from contextlib import contextmanager
import _pythonutils
import imp
import linecache
import marshal
import operator
import os.path
import sys
import types
from sims4.utils import flexproperty, flexmethod, classproperty
import enum
import sims4.log
set_function_closure = _pythonutils.set_function_closure
logger = sims4.log.Logger('Reload', default_owner='bhill')
SUPPORTED_BUILTIN_MODULES = ('builtins', 'collections', 'operator')
SUPPORTED_BUILTIN_TYPES = (int, float, complex, str, list, tuple, bytearray, set, frozenset, dict, operator.itemgetter, operator.attrgetter, operator.methodcaller)
SUPPORTED_CUSTOM_METACLASSES = (enum.Metaclass,)
SUPPORTED_CUSTOM_TYPES = (sims4.log.Logger,)
IMMUTABLE_CLASS_ATTRIBUTES = ('__dict__', '__doc__', '__slots__', '__weakref__', '__mro__', '__reload_as__')

def _make_hooks_dict(hooks, module_dict):
    if not isinstance(hooks, (dict, tuple, set, list)):
        raise TypeError('__reload_hooks__ must be a list of global variable names or a dict of names to reload hooks')
    if not isinstance(hooks, dict):
        hooks = {name: module_dict['__reload_{0}'.format(name)] for name in hooks}
    return hooks

@contextmanager
def protected(globals):
    old_names = set(globals.keys())
    try:
        yield None
    finally:
        new_names = set(globals.keys()) - old_names
        if new_names:
            hooks = globals.get('__reload_hooks__', {})
            hooks = _make_hooks_dict(hooks, globals)
            for name in new_names:
                hooks[name] = None
            globals['__reload_hooks__'] = hooks

with protected(globals()):
    _reload_serial_number = 0
    currently_reloading = 0
_reload_object_stack = []

def reload_module(module):
    modname = module.__name__
    i = modname.rfind('.')
    if i >= 0:
        (pkgname, modname) = (modname[:i], modname[i + 1:])
    else:
        pkgname = None
    if pkgname:
        pkg = sys.modules[pkgname]
        path = pkg.__path__
    else:
        pkg = None
        path = None
    (stream, filename, (_, _, kind)) = imp.find_module(modname, path)
    return _reload(module, filename, stream, kind)

def reload_module_from_file(module, filename):
    kind = imp.PY_SOURCE if filename.endswith('.py') else imp.PY_COMPILED
    stream = open(filename)
    module = _reload(module, filename, stream, kind)
    if module is not None:
        module = filename
    return module

def reload_module_from_string(module, source):
    stream = StringIO(source)
    filename = module.__dict__['__file__']
    kind = imp.PY_SOURCE
    return _reload(module, filename, stream, kind)

def get_module_for_filename(filename):
    module = None
    for _module in sys.modules.values():
        _filename = _module.__dict__.get('__file__')
        while _filename is not None and os.path.normcase(_filename) == os.path.normcase(filename):
            module = _module
            break
    return module

def reload_file(filename):
    import sims4.tuning.serialization
    module = get_module_for_filename(filename)
    if module is None:
        logger.error('{0} is not currently loaded as a module.', filename)
        return
    kind = imp.PY_SOURCE if filename.endswith('.py') else imp.PY_COMPILED
    stream = open(filename)
    reloaded_module = _reload(module, filename, stream, kind)
    try:
        sims4.tuning.serialization.process_tuning(module)
    except:
        logger.exception('Exception while reloading module tuning for {0}', filename)
    linecache.checkcache(filename)
    return reloaded_module

def _reload(module, filename, stream, kind):
    global currently_reloading, _reload_serial_number
    currently_reloading += 1
    _reload_serial_number += 1
    try:
        modns = module.__dict__
        try:
            if kind not in (imp.PY_COMPILED, imp.PY_SOURCE):
                raise NotImplementedError('Reloading non-source or byte code files is currently unimplemented.')
            if kind == imp.PY_SOURCE:
                source = stream.read()
                code = compile(source, filename, 'exec')
            else:
                code = marshal.load(stream)
        finally:
            if stream:
                stream.close()
        tmpns = modns.copy()
        modns.clear()
        modns['__name__'] = tmpns['__name__']
        modns['__file__'] = tmpns['__file__']
        exec(code, modns)
        update_module_dict(tmpns, modns)
        return module
    finally:
        currently_reloading -= 1

def update_module_dict(tmpns, modns):
    oldnames = set(tmpns)
    newnames = set(modns)
    update_names = oldnames & newnames
    delete_names = oldnames - newnames
    hooked_names = ()
    hooks = modns.get('__reload_hooks__')
    if hooks is not None:
        hooks = _make_hooks_dict(hooks, modns)
        hooked_names = hooks.keys() & update_names
        update_names = update_names - hooked_names
    for name in update_names:
        modns[name] = _update(tmpns[name], modns[name])
    for name in delete_names:
        oldobj = tmpns[name]
        while isinstance(oldobj, types.ModuleType):
            logger.warn('Preserving old sub-module: {} ({})', name, oldobj)
            modns[name] = oldobj
    for name in hooked_names:
        hook = hooks[name]
        if hook is not None:
            modns[name] = hook(tmpns[name], modns[name], _update)
        else:
            modns[name] = tmpns[name]

def _getattr_exact(obj, name, default=None):
    try:
        vars_obj = vars(obj)
    except TypeError:
        return default
    return vars_obj.get(name, default)

def _log_reload_position(obj):
    lines = str(obj).splitlines()
    for line in lines:
        line = line.strip()
        while line:
            break
    if len(lines) > 1:
        line += '...'
    logger.warn('{}{}', '  '*len(_reload_object_stack), line)

def _update_reload_mark(oldobj, newobj):
    if _reload_serial_number == 0:
        return
    old_mark = _getattr_exact(oldobj, '__reload_mark__', 0)
    new_mark = _getattr_exact(newobj, '__reload_mark__', 0)
    if old_mark == _reload_serial_number:
        logger.warn('Updating an object of type {0} multiple times. (Value: {1})', type(oldobj), oldobj)
    elif new_mark == _reload_serial_number:
        logger.error('Visiting an object of type {0} multiple times before it has finished updating. (Value: {1})', type(newobj), newobj)
    try:
        setattr(newobj, '__reload_mark__', _reload_serial_number)
    except AttributeError:
        pass

def _update(oldobj, newobj):
    try:
        _reload_object_stack.append(newobj)
        if oldobj is newobj:
            return newobj
        reload_as = _getattr_exact(newobj, '__reload_as__')
        if reload_as is not None:
            return reload_as
        _update_reload_mark(oldobj, newobj)
        if isinstance(newobj, type):
            if hasattr(newobj, '__reload_update_class__'):
                return newobj.__reload_update_class__(oldobj, newobj, _update)
            if hasattr(oldobj, '__reload_update_class__'):
                return oldobj.__reload_update_class__(oldobj, newobj, _update)
        else:
            if hasattr(newobj, '__reload_update__'):
                return newobj.__reload_update__(oldobj, newobj, _update)
            if hasattr(oldobj, '__reload_update__'):
                return oldobj.__reload_update__(oldobj, newobj, _update)
        reload_context = _getattr_exact(newobj, '__reload_context__')
        if reload_context is None:
            reload_context = _getattr_exact(oldobj, '__reload_context__')
        if reload_context is not None:
            with reload_context(oldobj, newobj):
                return __update(oldobj, newobj)
        return __update(oldobj, newobj)
    finally:
        _reload_object_stack.pop()

def _is_supported_as_literal_value(newobj):
    if type(newobj).__module__ in SUPPORTED_BUILTIN_MODULES and isinstance(newobj, SUPPORTED_BUILTIN_TYPES):
        return True
    if isinstance(newobj, SUPPORTED_CUSTOM_TYPES):
        return True
    if isinstance(type(newobj), SUPPORTED_CUSTOM_METACLASSES):
        return True
    return False

def _check_unupdated_newobj(newobj, what):
    if _is_supported_as_literal_value(newobj):
        logger.debug('Reloading {2} of type {0}. (New value: {1})', type(newobj), newobj, what)
    else:
        logger.warn('Leaking new {0} into old module while reloading {2}.  As long as this type is equivalent to a literal value, this is probably ok. (Value: {1})', type(newobj), newobj, what)

def __update(oldobj, newobj):
    if type(oldobj) is not type(newobj):
        return newobj
    if isinstance(newobj, type):
        return _update_class(oldobj, newobj)
    if isinstance(newobj, types.FunctionType):
        return _update_function(oldobj, newobj)
    if isinstance(newobj, types.MethodType):
        return _update_method(oldobj, newobj)
    if isinstance(newobj, classmethod):
        return _update_classmethod(oldobj, newobj)
    if isinstance(newobj, staticmethod):
        return _update_staticmethod(oldobj, newobj)
    if isinstance(newobj, property):
        return _update_property(oldobj, newobj)
    if isinstance(newobj, flexmethod):
        return _update_flexmethod(oldobj, newobj)
    if isinstance(newobj, flexproperty):
        return _update_flexproperty(oldobj, newobj)
    if isinstance(newobj, classproperty):
        return _update_classproperty(oldobj, newobj)
    _check_unupdated_newobj(newobj, 'global/static member')
    return newobj

def _update_property(oldprop, newprop):
    _update(oldprop.fget, newprop.fget)
    _update(oldprop.fset, newprop.fset)
    _update(oldprop.fdel, newprop.fdel)
    return oldprop

def _update_flexproperty(oldprop, newprop):
    _update(oldprop.fget, newprop.fget)
    return oldprop

def _update_classproperty(oldprop, newprop):
    _update(oldprop.fget, newprop.fget)
    return oldprop

def _update_function(oldfunc, newfunc):
    newfunc.__reload_as__ = oldfunc
    olddict = oldfunc.__dict__
    newdict = newfunc.__dict__
    for name in newdict.keys() - olddict.keys() - {'__reload_as__'}:
        setattr(oldfunc, name, newdict[name])
    for name in olddict.keys() - newdict.keys() - {'__reload_as__'}:
        delattr(oldfunc, name)
    for name in (olddict.keys() & newdict.keys()) - {'__reload_as__'}:
        setattr(oldfunc, name, _update(olddict[name], newdict[name]))
    set_function_closure(oldfunc, newfunc)
    oldfunc.__code__ = newfunc.__code__
    oldfunc.__defaults__ = newfunc.__defaults__
    return oldfunc

def _update_method(oldmeth, newmeth):
    if hasattr(oldmeth, 'im_func'):
        _update(oldmeth.im_func, newmeth.im_func)
    elif hasattr(oldmeth, '__func__'):
        _update(oldmeth.__func__, newmeth.__func__)
    else:
        logger.error('Method {} has no im_func or __func__.', oldmeth)
    return oldmeth

def _get_slots_list_or_none(cls):
    if not hasattr(cls, '__slots__'):
        return
    slots = cls.__slots__
    if isinstance(slots, str):
        return [slots]
    return slots

def _mangle_attribute_name(cls, attr):
    if attr.startswith('__') and not attr.endswith('__'):
        classname = cls.__name__.lstrip('_')
        if classname:
            return '_{0}{1}'.format(classname, attr)
    return attr

def _update_class(oldclass, newclass):
    newclass.__reload_as__ = oldclass
    olddict = oldclass.__dict__
    newdict = newclass.__dict__
    immutables = set(IMMUTABLE_CLASS_ATTRIBUTES)
    oldslots = _get_slots_list_or_none(oldclass)
    newslots = _get_slots_list_or_none(newclass)
    if oldslots is not None:
        slots = {_mangle_attribute_name(oldclass, slot) for slot in oldslots}
        immutables |= slots
    oldnames = set(olddict) - immutables
    newnames = set(newdict) - immutables
    for name in newnames - oldnames:
        setattr(oldclass, name, newdict[name])
    for name in oldnames - newnames:
        delattr(oldclass, name)
    for name in oldnames & newnames:
        setattr(oldclass, name, _update(olddict[name], newdict[name]))
    return oldclass

def _update_classmethod(oldcm, newcm):
    _update(oldcm.__get__(0), newcm.__get__(0))
    return oldcm

def _update_staticmethod(oldsm, newsm):
    _update(oldsm.__get__(0), newsm.__get__(0))
    return oldsm

def _update_flexmethod(oldfm, newfm):
    oldfm.__wrapped__ = _update(oldfm.__wrapped__, newfm.__wrapped__)
    return oldfm

