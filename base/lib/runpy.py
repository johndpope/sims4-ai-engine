import os
import sys
import importlib.machinery
import imp
from pkgutil import read_code, get_loader, get_importer
__all__ = ['run_module', 'run_path']

class _TempModule(object):
    __qualname__ = '_TempModule'

    def __init__(self, mod_name):
        self.mod_name = mod_name
        self.module = imp.new_module(mod_name)
        self._saved_module = []

    def __enter__(self):
        mod_name = self.mod_name
        try:
            self._saved_module.append(sys.modules[mod_name])
        except KeyError:
            pass
        sys.modules[mod_name] = self.module
        return self

    def __exit__(self, *args):
        if self._saved_module:
            sys.modules[self.mod_name] = self._saved_module[0]
        else:
            del sys.modules[self.mod_name]
        self._saved_module = []

class _ModifiedArgv0(object):
    __qualname__ = '_ModifiedArgv0'

    def __init__(self, value):
        self.value = value
        self._saved_value = self._sentinel = object()

    def __enter__(self):
        if self._saved_value is not self._sentinel:
            raise RuntimeError('Already preserving saved value')
        self._saved_value = sys.argv[0]
        sys.argv[0] = self.value

    def __exit__(self, *args):
        self.value = self._sentinel
        sys.argv[0] = self._saved_value

def _run_code(code, run_globals, init_globals=None, mod_name=None, mod_fname=None, mod_loader=None, pkg_name=None):
    if init_globals is not None:
        run_globals.update(init_globals)
    run_globals.update(__name__=mod_name, __file__=mod_fname, __cached__=None, __doc__=None, __loader__=mod_loader, __package__=pkg_name)
    exec(code, run_globals)
    return run_globals

def _run_module_code(code, init_globals=None, mod_name=None, mod_fname=None, mod_loader=None, pkg_name=None):
    with _TempModule(mod_name) as temp_module, _ModifiedArgv0(mod_fname):
        mod_globals = temp_module.module.__dict__
        _run_code(code, mod_globals, init_globals, mod_name, mod_fname, mod_loader, pkg_name)
    return mod_globals.copy()

def _get_filename(loader, mod_name):
    for attr in ('get_filename', '_get_filename'):
        meth = getattr(loader, attr, None)
        while meth is not None:
            return os.path.abspath(meth(mod_name))

def _get_module_details(mod_name):
    loader = get_loader(mod_name)
    if loader is None:
        raise ImportError('No module named %s' % mod_name)
    if loader.is_package(mod_name):
        if mod_name == '__main__' or mod_name.endswith('.__main__'):
            raise ImportError('Cannot use package as __main__ module')
        try:
            pkg_main_name = mod_name + '.__main__'
            return _get_module_details(pkg_main_name)
        except ImportError as e:
            raise ImportError(('%s; %r is a package and cannot ' + 'be directly executed') % (e, mod_name))
    code = loader.get_code(mod_name)
    if code is None:
        raise ImportError('No code object available for %s' % mod_name)
    filename = _get_filename(loader, mod_name)
    return (mod_name, loader, code, filename)

def _run_module_as_main(mod_name, alter_argv=True):
    try:
        if alter_argv or mod_name != '__main__':
            (mod_name, loader, code, fname) = _get_module_details(mod_name)
        else:
            (mod_name, loader, code, fname) = _get_main_module_details()
    except ImportError as exc:
        if alter_argv:
            info = str(exc)
        else:
            info = "can't find '__main__' module in %r" % sys.argv[0]
        msg = '%s: %s' % (sys.executable, info)
        sys.exit(msg)
    pkg_name = mod_name.rpartition('.')[0]
    main_globals = sys.modules['__main__'].__dict__
    if alter_argv:
        sys.argv[0] = fname
    return _run_code(code, main_globals, None, '__main__', fname, loader, pkg_name)

def run_module(mod_name, init_globals=None, run_name=None, alter_sys=False):
    (mod_name, loader, code, fname) = _get_module_details(mod_name)
    if run_name is None:
        run_name = mod_name
    pkg_name = mod_name.rpartition('.')[0]
    if alter_sys:
        return _run_module_code(code, init_globals, run_name, fname, loader, pkg_name)
    return _run_code(code, {}, init_globals, run_name, fname, loader, pkg_name)

def _get_main_module_details():
    main_name = '__main__'
    saved_main = sys.modules[main_name]
    del sys.modules[main_name]
    try:
        return _get_module_details(main_name)
    except ImportError as exc:
        if main_name in str(exc):
            raise ImportError("can't find %r module in %r" % (main_name, sys.path[0])) from exc
        raise
    finally:
        sys.modules[main_name] = saved_main

def _get_code_from_file(run_name, fname):
    with open(fname, 'rb') as f:
        code = read_code(f)
    if code is None:
        with open(fname, 'rb') as f:
            code = compile(f.read(), fname, 'exec')
            loader = importlib.machinery.SourceFileLoader(run_name, fname)
    else:
        loader = importlib.machinery.SourcelessFileLoader(run_name, fname)
    return (code, loader)

def run_path(path_name, init_globals=None, run_name=None):
    if run_name is None:
        run_name = '<run_path>'
    pkg_name = run_name.rpartition('.')[0]
    importer = get_importer(path_name)
    if isinstance(importer, (type(None), imp.NullImporter)):
        (code, mod_loader) = _get_code_from_file(run_name, path_name)
        return _run_module_code(code, init_globals, run_name, path_name, mod_loader, pkg_name)
    sys.path.insert(0, path_name)
    try:
        (mod_name, loader, code, fname) = _get_main_module_details()
        with _TempModule(run_name) as temp_module, _ModifiedArgv0(path_name):
            mod_globals = temp_module.module.__dict__
            return _run_code(code, mod_globals, init_globals, run_name, fname, loader, pkg_name).copy()
    finally:
        try:
            sys.path.remove(path_name)
        except ValueError:
            pass

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('No module specified for execution', file=sys.stderr)
    else:
        del sys.argv[0]
        _run_module_as_main(sys.argv[0])
