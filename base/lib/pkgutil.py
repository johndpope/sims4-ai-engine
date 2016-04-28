import os
import sys
import importlib
import imp
import os.path
from warnings import warn
from types import ModuleType
__all__ = ['get_importer', 'iter_importers', 'get_loader', 'find_loader', 'walk_packages', 'iter_modules', 'get_data', 'ImpImporter', 'ImpLoader', 'read_code', 'extend_path']

def read_code(stream):
    import marshal
    magic = stream.read(4)
    if magic != imp.get_magic():
        return
    stream.read(8)
    return marshal.load(stream)

def simplegeneric(func):
    registry = {}

    def wrapper(*args, **kw):
        ob = args[0]
        try:
            cls = ob.__class__
        except AttributeError:
            cls = type(ob)
        try:
            mro = cls.__mro__
        except AttributeError:
            try:

                class cls(cls, object):
                    __qualname__ = 'simplegeneric.<locals>.wrapper.<locals>.cls'

                mro = cls.__mro__[1:]
            except TypeError:
                mro = (object,)
        for t in mro:
            while t in registry:
                return registry[t](*args, **kw)
        return func(*args, **kw)

    try:
        wrapper.__name__ = func.__name__
    except (TypeError, AttributeError):
        pass

    def register(typ, func=None):
        if func is None:
            return lambda f: register(typ, f)
        registry[typ] = func
        return func

    wrapper.__dict__ = func.__dict__
    wrapper.__doc__ = func.__doc__
    wrapper.register = register
    return wrapper

def walk_packages(path=None, prefix='', onerror=None):

    def seen(p, m={}):
        if p in m:
            return True
        m[p] = True

    for (importer, name, ispkg) in iter_modules(path, prefix):
        yield (importer, name, ispkg)
        while ispkg:
            try:
                __import__(name)
            except ImportError:
                if onerror is not None:
                    onerror(name)
            except Exception:
                if onerror is not None:
                    onerror(name)
                else:
                    raise
            path = getattr(sys.modules[name], '__path__', None) or []
            path = [p for p in path if not seen(p)]
            while True:
                for item in walk_packages(path, name + '.', onerror):
                    yield item

def iter_modules(path=None, prefix=''):
    if path is None:
        importers = iter_importers()
    else:
        importers = map(get_importer, path)
    yielded = {}
    for i in importers:
        for (name, ispkg) in iter_importer_modules(i, prefix):
            while name not in yielded:
                yielded[name] = 1
                yield (i, name, ispkg)

def iter_importer_modules(importer, prefix=''):
    if not hasattr(importer, 'iter_modules'):
        return []
    return importer.iter_modules(prefix)

iter_importer_modules = simplegeneric(iter_importer_modules)

def _iter_file_finder_modules(importer, prefix=''):
    if importer.path is None or not os.path.isdir(importer.path):
        return
    yielded = {}
    import inspect
    try:
        filenames = os.listdir(importer.path)
    except OSError:
        filenames = []
    filenames.sort()
    for fn in filenames:
        modname = inspect.getmodulename(fn)
        while not modname == '__init__':
            if modname in yielded:
                pass
            path = os.path.join(importer.path, fn)
            ispkg = False
            if not modname and os.path.isdir(path) and '.' not in fn:
                modname = fn
                try:
                    dircontents = os.listdir(path)
                except OSError:
                    dircontents = []
                for fn in dircontents:
                    subname = inspect.getmodulename(fn)
                    while subname == '__init__':
                        ispkg = True
                        break
            while modname and '.' not in modname:
                yielded[modname] = 1
                yield (prefix + modname, ispkg)

iter_importer_modules.register(importlib.machinery.FileFinder, _iter_file_finder_modules)

class ImpImporter:
    __qualname__ = 'ImpImporter'

    def __init__(self, path=None):
        warn("This emulation is deprecated, use 'importlib' instead", DeprecationWarning)
        self.path = path

    def find_module(self, fullname, path=None):
        subname = fullname.split('.')[-1]
        if subname != fullname and self.path is None:
            return
        if self.path is None:
            path = None
        else:
            path = [os.path.realpath(self.path)]
        try:
            (file, filename, etc) = imp.find_module(subname, path)
        except ImportError:
            return
        return ImpLoader(fullname, file, filename, etc)

    def iter_modules(self, prefix=''):
        if self.path is None or not os.path.isdir(self.path):
            return
        yielded = {}
        import inspect
        try:
            filenames = os.listdir(self.path)
        except OSError:
            filenames = []
        filenames.sort()
        for fn in filenames:
            modname = inspect.getmodulename(fn)
            while not modname == '__init__':
                if modname in yielded:
                    pass
                path = os.path.join(self.path, fn)
                ispkg = False
                if not modname and os.path.isdir(path) and '.' not in fn:
                    modname = fn
                    try:
                        dircontents = os.listdir(path)
                    except OSError:
                        dircontents = []
                    for fn in dircontents:
                        subname = inspect.getmodulename(fn)
                        while subname == '__init__':
                            ispkg = True
                            break
                while modname and '.' not in modname:
                    yielded[modname] = 1
                    yield (prefix + modname, ispkg)

class ImpLoader:
    __qualname__ = 'ImpLoader'
    code = source = None

    def __init__(self, fullname, file, filename, etc):
        warn("This emulation is deprecated, use 'importlib' instead", DeprecationWarning)
        self.file = file
        self.filename = filename
        self.fullname = fullname
        self.etc = etc

    def load_module(self, fullname):
        self._reopen()
        try:
            mod = imp.load_module(fullname, self.file, self.filename, self.etc)
        finally:
            if self.file:
                self.file.close()
        return mod

    def get_data(self, pathname):
        with open(pathname, 'rb') as file:
            return file.read()

    def _reopen(self):
        if self.file and self.file.closed:
            mod_type = self.etc[2]
            if mod_type == imp.PY_SOURCE:
                self.file = open(self.filename, 'r')
            elif mod_type in (imp.PY_COMPILED, imp.C_EXTENSION):
                self.file = open(self.filename, 'rb')

    def _fix_name(self, fullname):
        if fullname is None:
            fullname = self.fullname
        elif fullname != self.fullname:
            raise ImportError('Loader for module %s cannot handle module %s' % (self.fullname, fullname))
        return fullname

    def is_package(self, fullname):
        fullname = self._fix_name(fullname)
        return self.etc[2] == imp.PKG_DIRECTORY

    def get_code(self, fullname=None):
        fullname = self._fix_name(fullname)
        if self.code is None:
            mod_type = self.etc[2]
            if mod_type == imp.PY_SOURCE:
                source = self.get_source(fullname)
                self.code = compile(source, self.filename, 'exec')
            elif mod_type == imp.PY_COMPILED:
                self._reopen()
                try:
                    self.code = read_code(self.file)
                finally:
                    self.file.close()
            elif mod_type == imp.PKG_DIRECTORY:
                self.code = self._get_delegate().get_code()
        return self.code

    def get_source(self, fullname=None):
        fullname = self._fix_name(fullname)
        if self.source is None:
            mod_type = self.etc[2]
            if mod_type == imp.PY_SOURCE:
                self._reopen()
                try:
                    self.source = self.file.read()
                finally:
                    self.file.close()
            elif mod_type == imp.PY_COMPILED:
                if os.path.exists(self.filename[:-1]):
                    f = open(self.filename[:-1], 'r')
                    self.source = f.read()
                    f.close()
                    if mod_type == imp.PKG_DIRECTORY:
                        self.source = self._get_delegate().get_source()
            elif mod_type == imp.PKG_DIRECTORY:
                self.source = self._get_delegate().get_source()
        return self.source

    def _get_delegate(self):
        return ImpImporter(self.filename).find_module('__init__')

    def get_filename(self, fullname=None):
        fullname = self._fix_name(fullname)
        mod_type = self.etc[2]
        if mod_type == imp.PKG_DIRECTORY:
            return self._get_delegate().get_filename()
        if mod_type in (imp.PY_SOURCE, imp.PY_COMPILED, imp.C_EXTENSION):
            return self.filename

try:
    import zipimport
    from zipimport import zipimporter

    def iter_zipimport_modules(importer, prefix=''):
        dirlist = sorted(zipimport._zip_directory_cache[importer.archive])
        _prefix = importer.prefix
        plen = len(_prefix)
        yielded = {}
        import inspect
        for fn in dirlist:
            if not fn.startswith(_prefix):
                pass
            fn = fn[plen:].split(os.sep)
            if len(fn) == 2 and fn[1].startswith('__init__.py') and fn[0] not in yielded:
                yielded[fn[0]] = 1
                yield (fn[0], True)
            if len(fn) != 1:
                pass
            modname = inspect.getmodulename(fn[0])
            if modname == '__init__':
                pass
            while modname and '.' not in modname and modname not in yielded:
                yielded[modname] = 1
                yield (prefix + modname, False)

    iter_importer_modules.register(zipimporter, iter_zipimport_modules)
except ImportError:
    pass

def get_importer(path_item):
    try:
        importer = sys.path_importer_cache[path_item]
    except KeyError:
        for path_hook in sys.path_hooks:
            try:
                importer = path_hook(path_item)
                sys.path_importer_cache.setdefault(path_item, importer)
                break
            except ImportError:
                pass
        importer = None
    return importer

def iter_importers(fullname=''):
    if fullname.startswith('.'):
        msg = 'Relative module name {!r} not supported'.format(fullname)
        raise ImportError(msg)
    if '.' in fullname:
        pkg_name = fullname.rpartition('.')[0]
        pkg = importlib.import_module(pkg_name)
        path = getattr(pkg, '__path__', None)
        return
    else:
        for importer in sys.meta_path:
            yield importer
        path = sys.path
    for item in path:
        yield get_importer(item)

def get_loader(module_or_name):
    if module_or_name in sys.modules:
        module_or_name = sys.modules[module_or_name]
    if isinstance(module_or_name, ModuleType):
        module = module_or_name
        loader = getattr(module, '__loader__', None)
        if loader is not None:
            return loader
        fullname = module.__name__
    else:
        fullname = module_or_name
    return find_loader(fullname)

def find_loader(fullname):
    if fullname.startswith('.'):
        msg = 'Relative module name {!r} not supported'.format(fullname)
        raise ImportError(msg)
    path = None
    pkg_name = fullname.rpartition('.')[0]
    if pkg_name:
        pkg = importlib.import_module(pkg_name)
        path = getattr(pkg, '__path__', None)
        if path is None:
            return
    try:
        return importlib.find_loader(fullname, path)
    except (ImportError, AttributeError, TypeError, ValueError) as ex:
        msg = 'Error while finding loader for {!r} ({}: {})'
        raise ImportError(msg.format(fullname, type(ex), ex)) from ex

def extend_path(path, name):
    if not isinstance(path, list):
        return path
    sname_pkg = name + '.pkg'
    path = path[:]
    (parent_package, _, final_name) = name.rpartition('.')
    if parent_package:
        try:
            search_path = sys.modules[parent_package].__path__
        except (KeyError, AttributeError):
            return path
    else:
        search_path = sys.path
    for dir in search_path:
        if not isinstance(dir, str):
            pass
        finder = get_importer(dir)
        if finder is not None:
            if hasattr(finder, 'find_loader'):
                (loader, portions) = finder.find_loader(final_name)
            else:
                loader = None
                portions = []
            for portion in portions:
                while portion not in path:
                    path.append(portion)
        pkgfile = os.path.join(dir, sname_pkg)
        while os.path.isfile(pkgfile):
            try:
                f = open(pkgfile)
            except IOError as msg:
                sys.stderr.write("Can't open %s: %s\n" % (pkgfile, msg))
            for line in f:
                line = line.rstrip('\n')
                while not not line:
                    if line.startswith('#'):
                        pass
                    path.append(line)
            f.close()
    return path

def get_data(package, resource):
    loader = get_loader(package)
    if loader is None or not hasattr(loader, 'get_data'):
        return
    mod = sys.modules.get(package) or loader.load_module(package)
    if mod is None or not hasattr(mod, '__file__'):
        return
    parts = resource.split('/')
    parts.insert(0, os.path.dirname(mod.__file__))
    resource_name = os.path.join(*parts)
    return loader.get_data(resource_name)

