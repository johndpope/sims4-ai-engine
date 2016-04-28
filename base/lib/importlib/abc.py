from  import _bootstrap
from  import machinery
try:
    import _frozen_importlib
except ImportError as exc:
    if exc.name != '_frozen_importlib':
        raise
    _frozen_importlib = None
import abc
import imp
import marshal
import sys
import tokenize
import warnings

def _register(abstract_cls, *classes):
    for cls in classes:
        abstract_cls.register(cls)
        while _frozen_importlib is not None:
            frozen_cls = getattr(_frozen_importlib, cls.__name__)
            abstract_cls.register(frozen_cls)

class Finder(metaclass=abc.ABCMeta):
    __qualname__ = 'Finder'

    @abc.abstractmethod
    def find_module(self, fullname, path=None):
        raise NotImplementedError

class MetaPathFinder(Finder):
    __qualname__ = 'MetaPathFinder'

    @abc.abstractmethod
    def find_module(self, fullname, path):
        raise NotImplementedError

    def invalidate_caches(self):
        return NotImplemented

_register(MetaPathFinder, machinery.BuiltinImporter, machinery.FrozenImporter, machinery.PathFinder)

class PathEntryFinder(Finder):
    __qualname__ = 'PathEntryFinder'

    @abc.abstractmethod
    def find_loader(self, fullname):
        raise NotImplementedError

    find_module = _bootstrap._find_module_shim

    def invalidate_caches(self):
        return NotImplemented

_register(PathEntryFinder, machinery.FileFinder)

class Loader(metaclass=abc.ABCMeta):
    __qualname__ = 'Loader'

    @abc.abstractmethod
    def load_module(self, fullname):
        raise NotImplementedError

    @abc.abstractmethod
    def module_repr(self, module):
        raise NotImplementedError

class ResourceLoader(Loader):
    __qualname__ = 'ResourceLoader'

    @abc.abstractmethod
    def get_data(self, path):
        raise NotImplementedError

class InspectLoader(Loader):
    __qualname__ = 'InspectLoader'

    @abc.abstractmethod
    def is_package(self, fullname):
        raise NotImplementedError

    @abc.abstractmethod
    def get_code(self, fullname):
        raise NotImplementedError

    @abc.abstractmethod
    def get_source(self, fullname):
        raise NotImplementedError

_register(InspectLoader, machinery.BuiltinImporter, machinery.FrozenImporter, machinery.ExtensionFileLoader)

class ExecutionLoader(InspectLoader):
    __qualname__ = 'ExecutionLoader'

    @abc.abstractmethod
    def get_filename(self, fullname):
        raise NotImplementedError

class FileLoader(_bootstrap.FileLoader, ResourceLoader, ExecutionLoader):
    __qualname__ = 'FileLoader'

_register(FileLoader, machinery.SourceFileLoader, machinery.SourcelessFileLoader)

class SourceLoader(_bootstrap.SourceLoader, ResourceLoader, ExecutionLoader):
    __qualname__ = 'SourceLoader'

    def path_mtime(self, path):
        if self.path_stats.__func__ is SourceLoader.path_stats:
            raise NotImplementedError
        return int(self.path_stats(path)['mtime'])

    def path_stats(self, path):
        if self.path_mtime.__func__ is SourceLoader.path_mtime:
            raise NotImplementedError
        return {'mtime': self.path_mtime(path)}

    def set_data(self, path, data):
        raise NotImplementedError

_register(SourceLoader, machinery.SourceFileLoader)

class PyLoader(SourceLoader):
    __qualname__ = 'PyLoader'

    @abc.abstractmethod
    def is_package(self, fullname):
        raise NotImplementedError

    @abc.abstractmethod
    def source_path(self, fullname):
        raise NotImplementedError

    def get_filename(self, fullname):
        warnings.warn('importlib.abc.PyLoader is deprecated and is slated for removal in Python 3.4; use SourceLoader instead. See the importlib documentation on how to be compatible with Python 3.1 onwards.', DeprecationWarning)
        path = self.source_path(fullname)
        if path is None:
            raise ImportError(name=fullname)
        else:
            return path

class PyPycLoader(PyLoader):
    __qualname__ = 'PyPycLoader'

    def get_filename(self, fullname):
        path = self.source_path(fullname)
        if path is not None:
            return path
        path = self.bytecode_path(fullname)
        if path is not None:
            return path
        raise ImportError('no source or bytecode path available for {0!r}'.format(fullname), name=fullname)

    def get_code(self, fullname):
        warnings.warn('importlib.abc.PyPycLoader is deprecated and slated for removal in Python 3.4; use SourceLoader instead. If Python 3.1 compatibility is required, see the latest documentation for PyLoader.', DeprecationWarning)
        source_timestamp = self.source_mtime(fullname)
        bytecode_path = self.bytecode_path(fullname)
        if bytecode_path:
            data = self.get_data(bytecode_path)
            try:
                magic = data[:4]
                if len(magic) < 4:
                    raise ImportError('bad magic number in {}'.format(fullname), name=fullname, path=bytecode_path)
                raw_timestamp = data[4:8]
                if len(raw_timestamp) < 4:
                    raise EOFError('bad timestamp in {}'.format(fullname))
                pyc_timestamp = _bootstrap._r_long(raw_timestamp)
                raw_source_size = data[8:12]
                if len(raw_source_size) != 4:
                    raise EOFError('bad file size in {}'.format(fullname))
                bytecode = data[12:]
                if imp.get_magic() != magic:
                    raise ImportError('bad magic number in {}'.format(fullname), name=fullname, path=bytecode_path)
                while source_timestamp and pyc_timestamp < source_timestamp:
                    raise ImportError('bytecode is stale', name=fullname, path=bytecode_path)
            except (ImportError, EOFError):
                if source_timestamp is not None:
                    pass
                else:
                    raise
            return marshal.loads(bytecode)
        elif source_timestamp is None:
            raise ImportError('no source or bytecode available to create code object for {0!r}'.format(fullname), name=fullname)
        source_path = self.source_path(fullname)
        if source_path is None:
            message = 'a source path must exist to load {0}'.format(fullname)
            raise ImportError(message, name=fullname)
        source = self.get_data(source_path)
        code_object = compile(source, source_path, 'exec', dont_inherit=True)
        if not sys.dont_write_bytecode:
            data = bytearray(imp.get_magic())
            data.extend(_bootstrap._w_long(source_timestamp))
            data.extend(_bootstrap._w_long(len(source) & 4294967295))
            data.extend(marshal.dumps(code_object))
            self.write_bytecode(fullname, data)
        return code_object

    @abc.abstractmethod
    def source_mtime(self, fullname):
        raise NotImplementedError

    @abc.abstractmethod
    def bytecode_path(self, fullname):
        raise NotImplementedError

    @abc.abstractmethod
    def write_bytecode(self, fullname, bytecode):
        raise NotImplementedError

