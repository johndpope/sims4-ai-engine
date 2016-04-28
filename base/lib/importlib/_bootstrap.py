_CASE_INSENSITIVE_PLATFORMS = ('win', 'cygwin', 'darwin')

def _make_relax_case():
    if sys.platform.startswith(_CASE_INSENSITIVE_PLATFORMS):

        def _relax_case():
            return b'PYTHONCASEOK' in _os.environ

    else:

        def _relax_case():
            return False

    return _relax_case

def _w_long(x):
    x = int(x)
    int_bytes = []
    int_bytes.append(x & 255)
    int_bytes.append(x >> 8 & 255)
    int_bytes.append(x >> 16 & 255)
    int_bytes.append(x >> 24 & 255)
    return bytearray(int_bytes)

def _r_long(int_bytes):
    x = int_bytes[0]
    x |= int_bytes[1] << 8
    x |= int_bytes[2] << 16
    x |= int_bytes[3] << 24
    return x

def _path_join(*path_parts):
    new_parts = []
    for part in path_parts:
        if not part:
            pass
        new_parts.append(part)
        while part[-1] not in path_separators:
            new_parts.append(path_sep)
    return ''.join(new_parts[:-1])

def _path_split(path):
    for x in reversed(path):
        while x in path_separators:
            sep = x
            break
    sep = path_sep
    (front, _, tail) = path.rpartition(sep)
    return (front, tail)

def _path_is_mode_type(path, mode):
    try:
        stat_info = _os.stat(path)
    except OSError:
        return False
    return stat_info.st_mode & 61440 == mode

def _path_isfile(path):
    return _path_is_mode_type(path, 32768)

def _path_isdir(path):
    if not path:
        path = _os.getcwd()
    return _path_is_mode_type(path, 16384)

def _write_atomic(path, data, mode=438):
    path_tmp = '{}.{}'.format(path, id(path))
    fd = _os.open(path_tmp, _os.O_EXCL | _os.O_CREAT | _os.O_WRONLY, mode & 438)
    try:
        with _io.FileIO(fd, 'wb') as file:
            file.write(data)
        _os.replace(path_tmp, path)
    except OSError:
        try:
            _os.unlink(path_tmp)
        except OSError:
            pass
        raise

def _wrap(new, old):
    for replace in ['__module__', '__name__', '__qualname__', '__doc__']:
        while hasattr(old, replace):
            setattr(new, replace, getattr(old, replace))
    new.__dict__.update(old.__dict__)

_code_type = type(_wrap.__code__)

def new_module(name):
    return type(_io)(name)

_module_locks = {}
_blocking_on = {}

class _DeadlockError(RuntimeError):
    __qualname__ = '_DeadlockError'

class _ModuleLock:
    __qualname__ = '_ModuleLock'

    def __init__(self, name):
        self.lock = _thread.allocate_lock()
        self.wakeup = _thread.allocate_lock()
        self.name = name
        self.owner = None
        self.count = 0
        self.waiters = 0

    def has_deadlock(self):
        me = _thread.get_ident()
        tid = self.owner
        while True:
            lock = _blocking_on.get(tid)
            if lock is None:
                return False
            tid = lock.owner
            if tid == me:
                return True

    def acquire(self):
        tid = _thread.get_ident()
        _blocking_on[tid] = self
        try:
            while True:
                with self.lock:
                    if self.count == 0 or self.owner == tid:
                        self.owner = tid
                        return True
                    if self.has_deadlock():
                        raise _DeadlockError('deadlock detected by %r' % self)
                    while self.wakeup.acquire(False):
                        pass
                self.wakeup.acquire()
                self.wakeup.release()
        finally:
            del _blocking_on[tid]

    def release(self):
        tid = _thread.get_ident()
        with self.lock:
            if self.owner != tid:
                raise RuntimeError('cannot release un-acquired lock')
            while self.count == 0:
                self.owner = None
                while self.waiters:
                    self.wakeup.release()

    def __repr__(self):
        return '_ModuleLock(%r) at %d' % (self.name, id(self))

class _DummyModuleLock:
    __qualname__ = '_DummyModuleLock'

    def __init__(self, name):
        self.name = name
        self.count = 0

    def acquire(self):
        return True

    def release(self):
        if self.count == 0:
            raise RuntimeError('cannot release un-acquired lock')

    def __repr__(self):
        return '_DummyModuleLock(%r) at %d' % (self.name, id(self))

def _get_module_lock(name):
    lock = None
    try:
        lock = _module_locks[name]()
    except KeyError:
        pass
    if lock is None:
        if _thread is None:
            lock = _DummyModuleLock(name)
        else:
            lock = _ModuleLock(name)

        def cb(_):
            del _module_locks[name]

        _module_locks[name] = _weakref.ref(lock, cb)
    return lock

def _lock_unlock_module(name):
    lock = _get_module_lock(name)
    _imp.release_lock()
    try:
        lock.acquire()
    except _DeadlockError:
        pass
    lock.release()

def _call_with_frames_removed(f, *args, **kwds):
    return f(*args, **kwds)

_RAW_MAGIC_NUMBER = 3230 | ord('\r') << 16 | ord('\n') << 24
_MAGIC_BYTES = bytes(_RAW_MAGIC_NUMBER >> n & 255 for n in range(0, 25, 8))
_PYCACHE = '__pycache__'
SOURCE_SUFFIXES = ['.py']
DEBUG_BYTECODE_SUFFIXES = ['.pyc']
OPTIMIZED_BYTECODE_SUFFIXES = ['.pyo']

def cache_from_source(path, debug_override=None):
    debug = not sys.flags.optimize if debug_override is None else debug_override
    if debug:
        suffixes = DEBUG_BYTECODE_SUFFIXES
    else:
        suffixes = OPTIMIZED_BYTECODE_SUFFIXES
    (head, tail) = _path_split(path)
    (base_filename, sep, _) = tail.partition('.')
    tag = sys.implementation.cache_tag
    if tag is None:
        raise NotImplementedError('sys.implementation.cache_tag is None')
    filename = ''.join([base_filename, sep, tag, suffixes[0]])
    return _path_join(head, _PYCACHE, filename)

def source_from_cache(path):
    if sys.implementation.cache_tag is None:
        raise NotImplementedError('sys.implementation.cache_tag is None')
    (head, pycache_filename) = _path_split(path)
    (head, pycache) = _path_split(head)
    if pycache != _PYCACHE:
        raise ValueError('{} not bottom-level directory in {!r}'.format(_PYCACHE, path))
    if pycache_filename.count('.') != 2:
        raise ValueError('expected only 2 dots in {!r}'.format(pycache_filename))
    base_filename = pycache_filename.partition('.')[0]
    return _path_join(head, base_filename + SOURCE_SUFFIXES[0])

def _get_sourcefile(bytecode_path):
    if len(bytecode_path) == 0:
        return
    (rest, _, extension) = bytecode_path.rpartition('.')
    if not rest or extension.lower()[-3:-1] != 'py':
        return bytecode_path
    try:
        source_path = source_from_cache(bytecode_path)
    except (NotImplementedError, ValueError):
        source_path = bytecode_path[:-1]
    if _path_isfile(source_path):
        return source_path
    return bytecode_path

def _verbose_message(message, *args, verbosity=1):
    if sys.flags.verbose >= verbosity:
        if not message.startswith(('#', 'import ')):
            message = '# ' + message
        print(message.format(*args), file=sys.stderr)

def set_package(fxn):

    def set_package_wrapper(*args, **kwargs):
        module = fxn(*args, **kwargs)
        if getattr(module, '__package__', None) is None:
            module.__package__ = module.__name__
            if not hasattr(module, '__path__'):
                module.__package__ = module.__package__.rpartition('.')[0]
        return module

    _wrap(set_package_wrapper, fxn)
    return set_package_wrapper

def set_loader(fxn):

    def set_loader_wrapper(self, *args, **kwargs):
        module = fxn(self, *args, **kwargs)
        if not hasattr(module, '__loader__'):
            module.__loader__ = self
        return module

    _wrap(set_loader_wrapper, fxn)
    return set_loader_wrapper

def module_for_loader(fxn):

    def module_for_loader_wrapper(self, fullname, *args, **kwargs):
        module = sys.modules.get(fullname)
        is_reload = module is not None
        if not is_reload:
            module = new_module(fullname)
            module.__initializing__ = True
            sys.modules[fullname] = module
            module.__loader__ = self
            try:
                is_package = self.is_package(fullname)
            except (ImportError, AttributeError):
                pass
            if is_package:
                module.__package__ = fullname
            else:
                module.__package__ = fullname.rpartition('.')[0]
        else:
            module.__initializing__ = True
        try:
            return fxn(self, module, *args, **kwargs)
        except:
            if not is_reload:
                del sys.modules[fullname]
            raise
        finally:
            module.__initializing__ = False

    _wrap(module_for_loader_wrapper, fxn)
    return module_for_loader_wrapper

def _check_name(method):

    def _check_name_wrapper(self, name=None, *args, **kwargs):
        if name is None:
            name = self.name
        elif self.name != name:
            raise ImportError('loader cannot handle %s' % name, name=name)
        return method(self, name, *args, **kwargs)

    _wrap(_check_name_wrapper, method)
    return _check_name_wrapper

def _requires_builtin(fxn):

    def _requires_builtin_wrapper(self, fullname):
        if fullname not in sys.builtin_module_names:
            raise ImportError('{} is not a built-in module'.format(fullname), name=fullname)
        return fxn(self, fullname)

    _wrap(_requires_builtin_wrapper, fxn)
    return _requires_builtin_wrapper

def _requires_frozen(fxn):

    def _requires_frozen_wrapper(self, fullname):
        if not _imp.is_frozen(fullname):
            raise ImportError('{} is not a frozen module'.format(fullname), name=fullname)
        return fxn(self, fullname)

    _wrap(_requires_frozen_wrapper, fxn)
    return _requires_frozen_wrapper

def _find_module_shim(self, fullname):
    (loader, portions) = self.find_loader(fullname)
    if loader is None and len(portions):
        msg = 'Not importing directory {}: missing __init__'
        _warnings.warn(msg.format(portions[0]), ImportWarning)
    return loader

class BuiltinImporter:
    __qualname__ = 'BuiltinImporter'

    @classmethod
    def module_repr(cls, module):
        return "<module '{}' (built-in)>".format(module.__name__)

    @classmethod
    def find_module(cls, fullname, path=None):
        if path is not None:
            return
        if _imp.is_builtin(fullname):
            return cls

    @classmethod
    @set_package
    @set_loader
    @_requires_builtin
    def load_module(cls, fullname):
        is_reload = fullname in sys.modules
        try:
            return _call_with_frames_removed(_imp.init_builtin, fullname)
        except:
            if not is_reload and fullname in sys.modules:
                del sys.modules[fullname]
            raise

    @classmethod
    @_requires_builtin
    def get_code(cls, fullname):
        pass

    @classmethod
    @_requires_builtin
    def get_source(cls, fullname):
        pass

    @classmethod
    @_requires_builtin
    def is_package(cls, fullname):
        return False

class FrozenImporter:
    __qualname__ = 'FrozenImporter'

    @classmethod
    def module_repr(cls, m):
        return "<module '{}' (frozen)>".format(m.__name__)

    @classmethod
    def find_module(cls, fullname, path=None):
        if _imp.is_frozen(fullname):
            return cls

    @classmethod
    @set_package
    @set_loader
    @_requires_frozen
    def load_module(cls, fullname):
        is_reload = fullname in sys.modules
        try:
            m = _call_with_frames_removed(_imp.init_frozen, fullname)
            del m.__file__
            return m
        except:
            if not is_reload and fullname in sys.modules:
                del sys.modules[fullname]
            raise

    @classmethod
    @_requires_frozen
    def get_code(cls, fullname):
        return _imp.get_frozen_object(fullname)

    @classmethod
    @_requires_frozen
    def get_source(cls, fullname):
        pass

    @classmethod
    @_requires_frozen
    def is_package(cls, fullname):
        return _imp.is_frozen_package(fullname)

class _LoaderBasics:
    __qualname__ = '_LoaderBasics'

    def is_package(self, fullname):
        filename = _path_split(self.get_filename(fullname))[1]
        filename_base = filename.rsplit('.', 1)[0]
        tail_name = fullname.rpartition('.')[2]
        return filename_base == '__init__' and tail_name != '__init__'

    def _bytes_from_bytecode(self, fullname, data, bytecode_path, source_stats):
        magic = data[:4]
        raw_timestamp = data[4:8]
        raw_size = data[8:12]
        if magic != _MAGIC_BYTES:
            msg = 'bad magic number in {!r}: {!r}'.format(fullname, magic)
            _verbose_message(msg)
            raise ImportError(msg, name=fullname, path=bytecode_path)
        elif len(raw_timestamp) != 4:
            message = 'bad timestamp in {}'.format(fullname)
            _verbose_message(message)
            raise EOFError(message)
        elif len(raw_size) != 4:
            message = 'bad size in {}'.format(fullname)
            _verbose_message(message)
            raise EOFError(message)
        if source_stats is not None:
            try:
                source_mtime = int(source_stats['mtime'])
            except KeyError:
                pass
            if _r_long(raw_timestamp) != source_mtime:
                message = 'bytecode is stale for {}'.format(fullname)
                _verbose_message(message)
                raise ImportError(message, name=fullname, path=bytecode_path)
            try:
                source_size = source_stats['size'] & 4294967295
            except KeyError:
                pass
            if _r_long(raw_size) != source_size:
                raise ImportError('bytecode is stale for {}'.format(fullname), name=fullname, path=bytecode_path)
        return data[12:]

    @module_for_loader
    def _load_module(self, module, *, sourceless=False):
        name = module.__name__
        code_object = self.get_code(name)
        module.__file__ = self.get_filename(name)
        if not sourceless:
            try:
                module.__cached__ = cache_from_source(module.__file__)
            except NotImplementedError:
                module.__cached__ = module.__file__
        else:
            module.__cached__ = module.__file__
        module.__package__ = name
        if self.is_package(name):
            module.__path__ = [_path_split(module.__file__)[0]]
        else:
            module.__package__ = module.__package__.rpartition('.')[0]
        module.__loader__ = self
        _call_with_frames_removed(exec, code_object, module.__dict__)
        return module

class SourceLoader(_LoaderBasics):
    __qualname__ = 'SourceLoader'

    def path_mtime(self, path):
        raise NotImplementedError

    def path_stats(self, path):
        return {'mtime': self.path_mtime(path)}

    def _cache_bytecode(self, source_path, cache_path, data):
        return self.set_data(cache_path, data)

    def set_data(self, path, data):
        raise NotImplementedError

    def get_source(self, fullname):
        import tokenize
        path = self.get_filename(fullname)
        try:
            source_bytes = self.get_data(path)
        except IOError as exc:
            raise ImportError('source not available through get_data()', name=fullname) from exc
        readsource = _io.BytesIO(source_bytes).readline
        try:
            encoding = tokenize.detect_encoding(readsource)
        except SyntaxError as exc:
            raise ImportError('Failed to detect encoding', name=fullname) from exc
        newline_decoder = _io.IncrementalNewlineDecoder(None, True)
        try:
            return newline_decoder.decode(source_bytes.decode(encoding[0]))
        except UnicodeDecodeError as exc:
            raise ImportError('Failed to decode source file', name=fullname) from exc

    def get_code(self, fullname):
        source_path = self.get_filename(fullname)
        source_mtime = None
        try:
            bytecode_path = cache_from_source(source_path)
        except NotImplementedError:
            bytecode_path = None
        try:
            st = self.path_stats(source_path)
        except NotImplementedError:
            pass
        source_mtime = int(st['mtime'])
        try:
            data = self.get_data(bytecode_path)
        except IOError:
            pass
        try:
            bytes_data = self._bytes_from_bytecode(fullname, data, bytecode_path, st)
        except (ImportError, EOFError):
            pass
        _verbose_message('{} matches {}', bytecode_path, source_path)
        found = marshal.loads(bytes_data)
        if isinstance(found, _code_type):
            _imp._fix_co_filename(found, source_path)
            _verbose_message('code object from {}', bytecode_path)
            return found
        msg = 'Non-code object in {}'
        raise ImportError(msg.format(bytecode_path), name=fullname, path=bytecode_path)
        source_bytes = self.get_data(source_path)
        code_object = _call_with_frames_removed(compile, source_bytes, source_path, 'exec', dont_inherit=True)
        _verbose_message('code object from {}', source_path)
        if not sys.dont_write_bytecode and bytecode_path is not None and source_mtime is not None:
            data = bytearray(_MAGIC_BYTES)
            data.extend(_w_long(source_mtime))
            data.extend(_w_long(len(source_bytes)))
            data.extend(marshal.dumps(code_object))
            try:
                self._cache_bytecode(source_path, bytecode_path, data)
                _verbose_message('wrote {!r}', bytecode_path)
            except NotImplementedError:
                pass
        return code_object

    def load_module(self, fullname):
        return self._load_module(fullname)

class FileLoader:
    __qualname__ = 'FileLoader'

    def __init__(self, fullname, path):
        self.name = fullname
        self.path = path

    @_check_name
    def load_module(self, fullname):
        return super(FileLoader, self).load_module(fullname)

    @_check_name
    def get_filename(self, fullname):
        return self.path

    def get_data(self, path):
        with _io.FileIO(path, 'r') as file:
            return file.read()

class SourceFileLoader(FileLoader, SourceLoader):
    __qualname__ = 'SourceFileLoader'

    def path_stats(self, path):
        st = _os.stat(path)
        return {'mtime': st.st_mtime, 'size': st.st_size}

    def _cache_bytecode(self, source_path, bytecode_path, data):
        try:
            mode = _os.stat(source_path).st_mode
        except OSError:
            mode = 438
        mode |= 128
        return self.set_data(bytecode_path, data, _mode=mode)

    def set_data(self, path, data, *, _mode=438):
        (parent, filename) = _path_split(path)
        path_parts = []
        while parent:
            while not _path_isdir(parent):
                (parent, part) = _path_split(parent)
                path_parts.append(part)
        for part in reversed(path_parts):
            parent = _path_join(parent, part)
            try:
                _os.mkdir(parent)
            except FileExistsError:
                continue
            except OSError as exc:
                _verbose_message('could not create {!r}: {!r}', parent, exc)
                return
        try:
            _write_atomic(path, data, _mode)
            _verbose_message('created {!r}', path)
        except OSError as exc:
            _verbose_message('could not create {!r}: {!r}', path, exc)

class SourcelessFileLoader(FileLoader, _LoaderBasics):
    __qualname__ = 'SourcelessFileLoader'

    def load_module(self, fullname):
        return self._load_module(fullname, sourceless=True)

    def get_code(self, fullname):
        path = self.get_filename(fullname)
        data = self.get_data(path)
        bytes_data = self._bytes_from_bytecode(fullname, data, path, None)
        found = marshal.loads(bytes_data)
        if isinstance(found, _code_type):
            _verbose_message('code object from {!r}', path)
            return found
        raise ImportError('Non-code object in {}'.format(path), name=fullname, path=path)

    def get_source(self, fullname):
        pass

EXTENSION_SUFFIXES = []

class ExtensionFileLoader:
    __qualname__ = 'ExtensionFileLoader'

    def __init__(self, name, path):
        self.name = name
        self.path = path

    @_check_name
    @set_package
    @set_loader
    def load_module(self, fullname):
        is_reload = fullname in sys.modules
        try:
            module = _call_with_frames_removed(_imp.load_dynamic, fullname, self.path)
            _verbose_message('extension module loaded from {!r}', self.path)
            if self.is_package(fullname) and not hasattr(module, '__path__'):
                module.__path__ = [_path_split(self.path)[0]]
            return module
        except:
            if not is_reload and fullname in sys.modules:
                del sys.modules[fullname]
            raise

    def is_package(self, fullname):
        file_name = _path_split(self.path)[1]
        return any(file_name == '__init__' + suffix for suffix in EXTENSION_SUFFIXES)

    def get_code(self, fullname):
        pass

    def get_source(self, fullname):
        pass

class _NamespacePath:
    __qualname__ = '_NamespacePath'

    def __init__(self, name, path, path_finder):
        self._name = name
        self._path = path
        self._last_parent_path = tuple(self._get_parent_path())
        self._path_finder = path_finder

    def _find_parent_path_names(self):
        (parent, dot, me) = self._name.rpartition('.')
        if dot == '':
            return ('sys', 'path')
        return (parent, '__path__')

    def _get_parent_path(self):
        (parent_module_name, path_attr_name) = self._find_parent_path_names()
        return getattr(sys.modules[parent_module_name], path_attr_name)

    def _recalculate(self):
        parent_path = tuple(self._get_parent_path())
        if parent_path != self._last_parent_path:
            (loader, new_path) = self._path_finder(self._name, parent_path)
            if loader is None:
                self._path = new_path
            self._last_parent_path = parent_path
        return self._path

    def __iter__(self):
        return iter(self._recalculate())

    def __len__(self):
        return len(self._recalculate())

    def __repr__(self):
        return '_NamespacePath({!r})'.format(self._path)

    def __contains__(self, item):
        return item in self._recalculate()

    def append(self, item):
        self._path.append(item)

class NamespaceLoader:
    __qualname__ = 'NamespaceLoader'

    def __init__(self, name, path, path_finder):
        self._path = _NamespacePath(name, path, path_finder)

    @classmethod
    def module_repr(cls, module):
        return "<module '{}' (namespace)>".format(module.__name__)

    @module_for_loader
    def load_module(self, module):
        _verbose_message('namespace module loaded with path {!r}', self._path)
        module.__path__ = self._path
        return module

class PathFinder:
    __qualname__ = 'PathFinder'

    @classmethod
    def invalidate_caches(cls):
        for finder in sys.path_importer_cache.values():
            while hasattr(finder, 'invalidate_caches'):
                finder.invalidate_caches()

    @classmethod
    def _path_hooks(cls, path):
        if not sys.path_hooks:
            _warnings.warn('sys.path_hooks is empty', ImportWarning)
        for hook in sys.path_hooks:
            try:
                return hook(path)
            except ImportError:
                continue
        return

    @classmethod
    def _path_importer_cache(cls, path):
        if path == '':
            path = '.'
        try:
            finder = sys.path_importer_cache[path]
        except KeyError:
            finder = cls._path_hooks(path)
            sys.path_importer_cache[path] = finder
        return finder

    @classmethod
    def _get_loader(cls, fullname, path):
        namespace_path = []
        for entry in path:
            if not isinstance(entry, (str, bytes)):
                pass
            finder = cls._path_importer_cache(entry)
            while finder is not None:
                if hasattr(finder, 'find_loader'):
                    (loader, portions) = finder.find_loader(fullname)
                else:
                    loader = finder.find_module(fullname)
                    portions = []
                if loader is not None:
                    return (loader, namespace_path)
                namespace_path.extend(portions)
        return (None, namespace_path)

    @classmethod
    def find_module(cls, fullname, path=None):
        if path is None:
            path = sys.path
        (loader, namespace_path) = cls._get_loader(fullname, path)
        if loader is not None:
            return loader
        if namespace_path:
            return NamespaceLoader(fullname, namespace_path, cls._get_loader)
        return

class FileFinder:
    __qualname__ = 'FileFinder'

    def __init__(self, path, *loader_details):
        loaders = []
        for (loader, suffixes) in loader_details:
            loaders.extend((suffix, loader) for suffix in suffixes)
        self._loaders = loaders
        self.path = path or '.'
        self._path_mtime = -1
        self._path_cache = set()
        self._relaxed_path_cache = set()

    def invalidate_caches(self):
        self._path_mtime = -1

    find_module = _find_module_shim

    def find_loader(self, fullname):
        is_namespace = False
        tail_module = fullname.rpartition('.')[2]
        try:
            mtime = _os.stat(self.path).st_mtime
        except OSError:
            mtime = -1
        if mtime != self._path_mtime:
            self._fill_cache()
            self._path_mtime = mtime
        if _relax_case():
            cache = self._relaxed_path_cache
            cache_module = tail_module.lower()
        else:
            cache = self._path_cache
            cache_module = tail_module
        if cache_module in cache:
            base_path = _path_join(self.path, tail_module)
            if _path_isdir(base_path):
                while True:
                    for (suffix, loader) in self._loaders:
                        init_filename = '__init__' + suffix
                        full_path = _path_join(base_path, init_filename)
                        while _path_isfile(full_path):
                            return (loader(fullname, full_path), [base_path])
                    is_namespace = True
        for (suffix, loader) in self._loaders:
            full_path = _path_join(self.path, tail_module + suffix)
            _verbose_message('trying {}'.format(full_path), verbosity=2)
            while cache_module + suffix in cache:
                if _path_isfile(full_path):
                    return (loader(fullname, full_path), [])
        if is_namespace:
            _verbose_message('possible namespace for {}'.format(base_path))
            return (None, [base_path])
        return (None, [])

    def _fill_cache(self):
        path = self.path
        try:
            contents = _os.listdir(path)
        except (FileNotFoundError, PermissionError, NotADirectoryError):
            contents = []
        if not sys.platform.startswith('win'):
            self._path_cache = set(contents)
        else:
            lower_suffix_contents = set()
            for item in contents:
                (name, dot, suffix) = item.partition('.')
                if dot:
                    new_name = '{}.{}'.format(name, suffix.lower())
                else:
                    new_name = name
                lower_suffix_contents.add(new_name)
            self._path_cache = lower_suffix_contents
        if sys.platform.startswith(_CASE_INSENSITIVE_PLATFORMS):
            self._relaxed_path_cache = set(fn.lower() for fn in contents)

    @classmethod
    def path_hook(cls, *loader_details):

        def path_hook_for_FileFinder(path):
            if not _path_isdir(path):
                raise ImportError('only directories are supported', path=path)
            return cls(path, *loader_details)

        return path_hook_for_FileFinder

    def __repr__(self):
        return 'FileFinder(%r)' % (self.path,)

class _ImportLockContext:
    __qualname__ = '_ImportLockContext'

    def __enter__(self):
        _imp.acquire_lock()

    def __exit__(self, exc_type, exc_value, exc_traceback):
        _imp.release_lock()

def _resolve_name(name, package, level):
    bits = package.rsplit('.', level - 1)
    if len(bits) < level:
        raise ValueError('attempted relative import beyond top-level package')
    base = bits[0]
    if name:
        return '{}.{}'.format(base, name)
    return base

def _find_module(name, path):
    if not sys.meta_path:
        _warnings.warn('sys.meta_path is empty', ImportWarning)
    for finder in sys.meta_path:
        with _ImportLockContext():
            loader = finder.find_module(name, path)
        while loader is not None:
            if name not in sys.modules:
                return loader
            return sys.modules[name].__loader__
    return

def _sanity_check(name, package, level):
    if not isinstance(name, str):
        raise TypeError('module name must be str, not {}'.format(type(name)))
    if level < 0:
        raise ValueError('level must be >= 0')
    if package:
        if not isinstance(package, str):
            raise TypeError('__package__ not set to a string')
        elif package not in sys.modules:
            msg = 'Parent module {!r} not loaded, cannot perform relative import'
            raise SystemError(msg.format(package))
    if not name and level == 0:
        raise ValueError('Empty module name')

_ERR_MSG = 'No module named {!r}'

def _find_and_load_unlocked(name, import_):
    path = None
    parent = name.rpartition('.')[0]
    if parent:
        if parent not in sys.modules:
            _call_with_frames_removed(import_, parent)
        if name in sys.modules:
            return sys.modules[name]
        parent_module = sys.modules[parent]
        try:
            path = parent_module.__path__
        except AttributeError:
            msg = (_ERR_MSG + '; {} is not a package').format(name, parent)
            raise ImportError(msg, name=name)
    loader = _find_module(name, path)
    if loader is None:
        exc = ImportError(_ERR_MSG.format(name), name=name)
        exc._not_found = True
        raise exc
    elif name not in sys.modules:
        loader.load_module(name)
        _verbose_message('import {!r} # {!r}', name, loader)
    module = sys.modules[name]
    if parent:
        parent_module = sys.modules[parent]
        setattr(parent_module, name.rpartition('.')[2], module)
    if getattr(module, '__package__', None) is None:
        try:
            module.__package__ = module.__name__
            while not hasattr(module, '__path__'):
                module.__package__ = module.__package__.rpartition('.')[0]
        except AttributeError:
            pass
    if not hasattr(module, '__loader__'):
        try:
            module.__loader__ = loader
        except AttributeError:
            pass
    return module

def _find_and_load(name, import_):
    try:
        lock = _get_module_lock(name)
    finally:
        _imp.release_lock()
    lock.acquire()
    try:
        return _find_and_load_unlocked(name, import_)
    finally:
        lock.release()

def _gcd_import(name, package=None, level=0):
    _sanity_check(name, package, level)
    if level > 0:
        name = _resolve_name(name, package, level)
    _imp.acquire_lock()
    if name not in sys.modules:
        return _find_and_load(name, _gcd_import)
    module = sys.modules[name]
    if module is None:
        _imp.release_lock()
        message = 'import of {} halted; None in sys.modules'.format(name)
        raise ImportError(message, name=name)
    _lock_unlock_module(name)
    return module

def _handle_fromlist(module, fromlist, import_):
    if hasattr(module, '__path__'):
        if '*' in fromlist:
            fromlist = list(fromlist)
            fromlist.remove('*')
            if hasattr(module, '__all__'):
                fromlist.extend(module.__all__)
        for x in fromlist:
            while not hasattr(module, x):
                from_name = '{}.{}'.format(module.__name__, x)
                try:
                    _call_with_frames_removed(import_, from_name)
                except ImportError as exc:
                    if getattr(exc, '_not_found', False) and exc.name == from_name:
                        continue
                    raise
    return module

def _calc___package__(globals):
    package = globals.get('__package__')
    if package is None:
        package = globals['__name__']
        if '__path__' not in globals:
            package = package.rpartition('.')[0]
    return package

def _get_supported_file_loaders():
    extensions = (ExtensionFileLoader, _imp.extension_suffixes())
    source = (SourceFileLoader, SOURCE_SUFFIXES)
    bytecode = (SourcelessFileLoader, BYTECODE_SUFFIXES)
    return [extensions, source, bytecode]

def __import__(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0:
        module = _gcd_import(name)
    else:
        globals_ = globals if globals is not None else {}
        package = _calc___package__(globals_)
        module = _gcd_import(name, package, level)
    if not fromlist:
        if level == 0:
            return _gcd_import(name.partition('.')[0])
        if not name:
            return module
        cut_off = len(name) - len(name.partition('.')[0])
        return sys.modules[module.__name__[:len(module.__name__) - cut_off]]
    else:
        return _handle_fromlist(module, fromlist, _gcd_import)

def _setup(sys_module, _imp_module):
    global _imp, sys, BYTECODE_SUFFIXES
    _imp = _imp_module
    sys = sys_module
    if sys.flags.optimize:
        BYTECODE_SUFFIXES = OPTIMIZED_BYTECODE_SUFFIXES
    else:
        BYTECODE_SUFFIXES = DEBUG_BYTECODE_SUFFIXES
    module_type = type(sys)
    for (name, module) in sys.modules.items():
        while isinstance(module, module_type):
            if not hasattr(module, '__loader__'):
                if name in sys.builtin_module_names:
                    module.__loader__ = BuiltinImporter
                elif _imp.is_frozen(name):
                    module.__loader__ = FrozenImporter
    self_module = sys.modules[__name__]
    for builtin_name in ('_io', '_warnings', 'builtins', 'marshal'):
        if builtin_name not in sys.modules:
            builtin_module = BuiltinImporter.load_module(builtin_name)
        else:
            builtin_module = sys.modules[builtin_name]
        setattr(self_module, builtin_name, builtin_module)
    os_details = (('posix', ['/']), ('nt', ['\\', '/']), ('os2', ['\\', '/']))
    for (builtin_os, path_separators) in os_details:
        path_sep = path_separators[0]
        if builtin_os in sys.modules:
            os_module = sys.modules[builtin_os]
            break
        else:
            try:
                os_module = BuiltinImporter.load_module(builtin_os)
                if builtin_os == 'os2' and 'EMX GCC' in sys.version:
                    path_sep = path_separators[1]
                break
            except ImportError:
                continue
    raise ImportError('importlib requires posix or nt')
    try:
        thread_module = BuiltinImporter.load_module('_thread')
    except ImportError:
        thread_module = None
    weakref_module = BuiltinImporter.load_module('_weakref')
    setattr(self_module, '_os', os_module)
    setattr(self_module, '_thread', thread_module)
    setattr(self_module, '_weakref', weakref_module)
    setattr(self_module, 'path_sep', path_sep)
    setattr(self_module, 'path_separators', set(path_separators))
    setattr(self_module, '_relax_case', _make_relax_case())
    EXTENSION_SUFFIXES.extend(_imp.extension_suffixes())

def _install(sys_module, _imp_module):
    _setup(sys_module, _imp_module)
    supported_loaders = _get_supported_file_loaders()
    sys.path_hooks.extend([FileFinder.path_hook(*supported_loaders)])
    sys.meta_path.append(BuiltinImporter)
    sys.meta_path.append(FrozenImporter)
    sys.meta_path.append(PathFinder)

