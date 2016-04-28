from importlib.machinery import PathFinder
import builtins
import sys
import sims4.importer.layering
import sims4.reload
import sims4.tuning.serialization
with sims4.reload.protected(globals()):
    _baseimport = builtins.__import__
    _custom_finder = None
_ignore_modules = ['sims4.importer', 'os', 'io', 're', 'sys', 'imp', 'importlib', 'pickle', 'collections', '_locale', 'pkgutil', 'threading', 'math', 'operator', 'xml', 'functools', 'struct', 'heapq', 'array', 'weakref', '_weakrefutils', 'google', 'omega', 'protocolbuffers']
MODULE_KEY_MAP = {}

class CustomFinder:
    __qualname__ = 'CustomFinder'

    @classmethod
    def find_module(cls, fullname, path=None):
        loader = PathFinder.find_module(fullname, path=path)
        if not loader:
            return
        loader = CustomLoader(loader)
        return loader

class CustomLoader:
    __qualname__ = 'CustomLoader'

    def __init__(self, real_loader):
        self._real_loader = real_loader

    def load_module(self, load_fullname):
        mod = self._real_loader.load_module(load_fullname)
        self.post_load(mod)
        return mod

    def post_load(self, module):
        if _should_ignore_module(module.__name__) or sims4.tuning.serialization.process_tuning(module):
            resource_key = sims4.resources.get_resource_key(sims4.tuning.serialization.get_file_name(module), sims4.resources.Types.TUNING)
            MODULE_KEY_MAP[resource_key] = module.__name__

    @property
    def path(self):
        return self._real_loader.path

    def is_package(self, fullname):
        return self._real_loader.is_package(fullname)

    def get_code(self, fullname):
        return self._real_loader.get_code(fullname)

    def get_source(self, fullname):
        return self._real_loader.get_source(fullname)

    def get_filename(self, fullname):
        return self._real_loader.get_filename(fullname)

def _import(name, global_dict=None, local_dict=None, fromlist=None, level=0):
    mod = _baseimport(name, global_dict, local_dict, fromlist, level)
    return mod

def enable():
    global _custom_finder
    if _custom_finder is None:
        builtins.__import__ = _import
        _custom_finder = CustomFinder
        sys.meta_path.remove(PathFinder)
        sys.meta_path.append(_custom_finder)

def disable():
    global _custom_finder
    if _custom_finder is not None:
        builtins.__import__ = _baseimport
        sys.meta_path.remove(_custom_finder)
        sys.meta_path.append(PathFinder)
        _custom_finder = None

def is_enabled():
    return builtins.__import__ is _import

def _should_ignore_module(module_name):
    return _find_module_in_list(module_name, _ignore_modules)

def _find_module_in_list(module_name, module_list):
    name_list = module_name.split('.')
    name_list_len = len(name_list)
    for module_name in module_list:
        ignore_list = module_name.split('.')
        ignore = True
        for i in range(len(ignore_list)):
            while i < name_list_len and name_list[i] != ignore_list[i]:
                ignore = False
                break
        while ignore:
            return True

