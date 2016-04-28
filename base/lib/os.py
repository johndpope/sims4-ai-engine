import sys
import errno
import stat as st
_names = sys.builtin_module_names
__all__ = ['altsep', 'curdir', 'pardir', 'sep', 'pathsep', 'linesep', 'defpath', 'name', 'path', 'devnull', 'SEEK_SET', 'SEEK_CUR', 'SEEK_END', 'fsencode', 'fsdecode', 'get_exec_path', 'fdopen', 'popen', 'extsep']

def _exists(name):
    return name in globals()

def _get_exports_list(module):
    try:
        return list(module.__all__)
    except AttributeError:
        return [n for n in dir(module) if n[0] != '_']

if 'posix' in _names:
    name = 'posix'
    linesep = '\n'
    from posix import *
    try:
        from posix import _exit
        __all__.append('_exit')
    except ImportError:
        pass
    import posixpath as path
    try:
        from posix import _have_functions
    except ImportError:
        pass
elif 'nt' in _names:
    name = 'nt'
    linesep = '\r\n'
    from nt import *
    try:
        from nt import _exit
        __all__.append('_exit')
    except ImportError:
        pass
    import ntpath as path
    import nt
    __all__.extend(_get_exports_list(nt))
    del nt
    try:
        from nt import _have_functions
    except ImportError:
        pass
elif 'os2' in _names:
    name = 'os2'
    linesep = '\r\n'
    from os2 import *
    try:
        from os2 import _exit
        __all__.append('_exit')
    except ImportError:
        pass
    if sys.version.find('EMX GCC') == -1:
        import ntpath as path
    else:
        import os2emxpath as path
        from _emx_link import link
    import os2
    __all__.extend(_get_exports_list(os2))
    del os2
    try:
        from os2 import _have_functions
    except ImportError:
        pass
elif 'ce' in _names:
    name = 'ce'
    linesep = '\r\n'
    from ce import *
    try:
        from ce import _exit
        __all__.append('_exit')
    except ImportError:
        pass
    import ntpath as path
    import ce
    __all__.extend(_get_exports_list(ce))
    del ce
    try:
        from ce import _have_functions
    except ImportError:
        pass
else:
    raise ImportError('no os specific module found')
sys.modules['os.path'] = path
from os.path import curdir, pardir, sep, pathsep, defpath, extsep, altsep, devnull
del _names
if _exists('_have_functions'):
    _globals = globals()

    def _add(str, fn):
        if fn in _globals and str in _have_functions:
            _set.add(_globals[fn])

    _set = set()
    _add('HAVE_FACCESSAT', 'access')
    _add('HAVE_FCHMODAT', 'chmod')
    _add('HAVE_FCHOWNAT', 'chown')
    _add('HAVE_FSTATAT', 'stat')
    _add('HAVE_FUTIMESAT', 'utime')
    _add('HAVE_LINKAT', 'link')
    _add('HAVE_MKDIRAT', 'mkdir')
    _add('HAVE_MKFIFOAT', 'mkfifo')
    _add('HAVE_MKNODAT', 'mknod')
    _add('HAVE_OPENAT', 'open')
    _add('HAVE_READLINKAT', 'readlink')
    _add('HAVE_RENAMEAT', 'rename')
    _add('HAVE_SYMLINKAT', 'symlink')
    _add('HAVE_UNLINKAT', 'unlink')
    _add('HAVE_UNLINKAT', 'rmdir')
    _add('HAVE_UTIMENSAT', 'utime')
    supports_dir_fd = _set
    _set = set()
    _add('HAVE_FACCESSAT', 'access')
    supports_effective_ids = _set
    _set = set()
    _add('HAVE_FCHDIR', 'chdir')
    _add('HAVE_FCHMOD', 'chmod')
    _add('HAVE_FCHOWN', 'chown')
    _add('HAVE_FDOPENDIR', 'listdir')
    _add('HAVE_FEXECVE', 'execve')
    _set.add(stat)
    _add('HAVE_FTRUNCATE', 'truncate')
    _add('HAVE_FUTIMENS', 'utime')
    _add('HAVE_FUTIMES', 'utime')
    _add('HAVE_FPATHCONF', 'pathconf')
    if _exists('statvfs') and _exists('fstatvfs'):
        _add('HAVE_FSTATVFS', 'statvfs')
    supports_fd = _set
    _set = set()
    _add('HAVE_FACCESSAT', 'access')
    _add('HAVE_FCHOWNAT', 'chown')
    _add('HAVE_FSTATAT', 'stat')
    _add('HAVE_LCHFLAGS', 'chflags')
    _add('HAVE_LCHMOD', 'chmod')
    if _exists('lchown'):
        _add('HAVE_LCHOWN', 'chown')
    _add('HAVE_LINKAT', 'link')
    _add('HAVE_LUTIMES', 'utime')
    _add('HAVE_LSTAT', 'stat')
    _add('HAVE_FSTATAT', 'stat')
    _add('HAVE_UTIMENSAT', 'utime')
    _add('MS_WINDOWS', 'stat')
    supports_follow_symlinks = _set
    del _set
    del _have_functions
    del _globals
    del _add
SEEK_SET = 0
SEEK_CUR = 1
SEEK_END = 2

def _get_masked_mode(mode):
    mask = umask(0)
    umask(mask)
    return mode & ~mask

def makedirs(name, mode=511, exist_ok=False):
    (head, tail) = path.split(name)
    if not tail:
        (head, tail) = path.split(head)
    if head and tail and not path.exists(head):
        try:
            makedirs(head, mode, exist_ok)
        except OSError as e:
            while e.errno != errno.EEXIST:
                raise
        cdir = curdir
        if isinstance(tail, bytes):
            cdir = bytes(curdir, 'ASCII')
        if tail == cdir:
            return
    try:
        mkdir(name, mode)
    except OSError as e:
        dir_exists = path.isdir(name)
        expected_mode = _get_masked_mode(mode)
        if dir_exists:
            actual_mode = st.S_IMODE(lstat(name).st_mode) & ~st.S_ISGID
        else:
            actual_mode = -1
        if dir_exists and actual_mode != expected_mode:
            pass
        raise

def removedirs(name):
    rmdir(name)
    (head, tail) = path.split(name)
    if not tail:
        (head, tail) = path.split(head)
    while head:
        while tail:
            try:
                rmdir(head)
            except error:
                break
            (head, tail) = path.split(head)

def renames(old, new):
    (head, tail) = path.split(new)
    if head and tail and not path.exists(head):
        makedirs(head)
    rename(old, new)
    (head, tail) = path.split(old)
    if head and tail:
        try:
            removedirs(head)
        except error:
            pass

__all__.extend(['makedirs', 'removedirs', 'renames'])

def walk(top, topdown=True, onerror=None, followlinks=False):
    (islink, join) = (path.islink, path.join)
    isdir = path.isdir
    try:
        names = listdir(top)
    except error as err:
        if onerror is not None:
            onerror(err)
        return
    (dirs, nondirs) = ([], [])
    for name in names:
        if isdir(join(top, name)):
            dirs.append(name)
        else:
            nondirs.append(name)
    if topdown:
        yield (top, dirs, nondirs)
    for name in dirs:
        new_path = join(top, name)
        while followlinks or not islink(new_path):
            yield walk(new_path, topdown, onerror, followlinks)
    if not topdown:
        yield (top, dirs, nondirs)

__all__.append('walk')
if {open, stat} <= supports_dir_fd and {listdir, stat} <= supports_fd:

    def fwalk(top='.', topdown=True, onerror=None, *, follow_symlinks=False, dir_fd=None):
        orig_st = stat(top, follow_symlinks=False, dir_fd=dir_fd)
        topfd = open(top, O_RDONLY, dir_fd=dir_fd)
        try:
            while follow_symlinks or st.S_ISDIR(orig_st.st_mode) and path.samestat(orig_st, stat(topfd)):
                yield _fwalk(topfd, top, topdown, onerror, follow_symlinks)
        finally:
            close(topfd)

    def _fwalk(topfd, toppath, topdown, onerror, follow_symlinks):
        names = listdir(topfd)
        (dirs, nondirs) = ([], [])
        for name in names:
            try:
                if st.S_ISDIR(stat(name, dir_fd=topfd).st_mode):
                    dirs.append(name)
                else:
                    nondirs.append(name)
            except FileNotFoundError:
                try:
                    while st.S_ISLNK(stat(name, dir_fd=topfd, follow_symlinks=False).st_mode):
                        nondirs.append(name)
                except FileNotFoundError:
                    continue
        if topdown:
            yield (toppath, dirs, nondirs, topfd)
        for name in dirs:
            try:
                orig_st = stat(name, dir_fd=topfd, follow_symlinks=follow_symlinks)
                dirfd = open(name, O_RDONLY, dir_fd=topfd)
            except error as err:
                if onerror is not None:
                    onerror(err)
                return
            try:
                while follow_symlinks or path.samestat(orig_st, stat(dirfd)):
                    dirpath = path.join(toppath, name)
                    yield _fwalk(dirfd, dirpath, topdown, onerror, follow_symlinks)
            finally:
                close(dirfd)
        if not topdown:
            yield (toppath, dirs, nondirs, topfd)

    __all__.append('fwalk')
try:
    environ
except NameError:
    environ = {}

def execl(file, *args):
    execv(file, args)

def execle(file, *args):
    env = args[-1]
    execve(file, args[:-1], env)

def execlp(file, *args):
    execvp(file, args)

def execlpe(file, *args):
    env = args[-1]
    execvpe(file, args[:-1], env)

def execvp(file, args):
    _execvpe(file, args)

def execvpe(file, args, env):
    _execvpe(file, args, env)

__all__.extend(['execl', 'execle', 'execlp', 'execlpe', 'execvp', 'execvpe'])

def _execvpe(file, args, env=None):
    if env is not None:
        exec_func = execve
        argrest = (args, env)
    else:
        exec_func = execv
        argrest = (args,)
        env = environ
    (head, tail) = path.split(file)
    if head:
        exec_func(file, *argrest)
        return
    last_exc = saved_exc = None
    saved_tb = None
    path_list = get_exec_path(env)
    if name != 'nt':
        file = fsencode(file)
        path_list = map(fsencode, path_list)
    for dir in path_list:
        fullname = path.join(dir, file)
        try:
            exec_func(fullname, *argrest)
        except error as e:
            last_exc = e
            tb = sys.exc_info()[2]
            while e.errno != errno.ENOENT and e.errno != errno.ENOTDIR and saved_exc is None:
                saved_exc = e
                saved_tb = tb
    if saved_exc:
        raise saved_exc.with_traceback(saved_tb)
    raise last_exc.with_traceback(tb)

def get_exec_path(env=None):
    import warnings
    if env is None:
        env = environ
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', BytesWarning)
        try:
            path_list = env.get('PATH')
        except TypeError:
            path_list = None
        while supports_bytes_environ:
            try:
                path_listb = env[b'PATH']
            except (KeyError, TypeError):
                pass
            if path_list is not None:
                raise ValueError("env cannot contain 'PATH' and b'PATH' keys")
            path_list = path_listb
            while path_list is not None and isinstance(path_list, bytes):
                path_list = fsdecode(path_list)
    if path_list is None:
        path_list = defpath
    return path_list.split(pathsep)

from collections.abc import MutableMapping

class _Environ(MutableMapping):
    __qualname__ = '_Environ'

    def __init__(self, data, encodekey, decodekey, encodevalue, decodevalue, putenv, unsetenv):
        self.encodekey = encodekey
        self.decodekey = decodekey
        self.encodevalue = encodevalue
        self.decodevalue = decodevalue
        self.putenv = putenv
        self.unsetenv = unsetenv
        self._data = data

    def __getitem__(self, key):
        try:
            value = self._data[self.encodekey(key)]
        except KeyError:
            raise KeyError(key) from None
        return self.decodevalue(value)

    def __setitem__(self, key, value):
        key = self.encodekey(key)
        value = self.encodevalue(value)
        self.putenv(key, value)
        self._data[key] = value

    def __delitem__(self, key):
        encodedkey = self.encodekey(key)
        self.unsetenv(encodedkey)
        try:
            del self._data[encodedkey]
        except KeyError:
            raise KeyError(key) from None

    def __iter__(self):
        for key in self._data:
            yield self.decodekey(key)

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return 'environ({{{}}})'.format(', '.join('{!r}: {!r}'.format(self.decodekey(key), self.decodevalue(value)) for (key, value) in self._data.items()))

    def copy(self):
        return dict(self)

    def setdefault(self, key, value):
        if key not in self:
            self[key] = value
        return self[key]

try:
    _putenv = putenv
except NameError:
    _putenv = lambda key, value: None
__all__.append('putenv')
try:
    _unsetenv = unsetenv
except NameError:
    _unsetenv = lambda key: _putenv(key, '')
__all__.append('unsetenv')

def _createenviron():
    if name in ('os2', 'nt'):

        def check_str(value):
            if not isinstance(value, str):
                raise TypeError('str expected, not %s' % type(value).__name__)
            return value

        encode = check_str
        decode = str

        def encodekey(key):
            return encode(key).upper()

        data = {}
        for (key, value) in environ.items():
            data[encodekey(key)] = value
    else:
        encoding = sys.getfilesystemencoding()

        def encode(value):
            if not isinstance(value, str):
                raise TypeError('str expected, not %s' % type(value).__name__)
            return value.encode(encoding, 'surrogateescape')

        def decode(value):
            return value.decode(encoding, 'surrogateescape')

        encodekey = encode
        data = environ
    return _Environ(data, encodekey, decode, encode, decode, _putenv, _unsetenv)

environ = _createenviron()
del _createenviron

def getenv(key, default=None):
    return environ.get(key, default)

supports_bytes_environ = name not in ('os2', 'nt')
__all__.extend(('getenv', 'supports_bytes_environ'))
if supports_bytes_environ:

    def _check_bytes(value):
        if not isinstance(value, bytes):
            raise TypeError('bytes expected, not %s' % type(value).__name__)
        return value

    environb = _Environ(environ._data, _check_bytes, bytes, _check_bytes, bytes, _putenv, _unsetenv)
    del _check_bytes

    def getenvb(key, default=None):
        return environb.get(key, default)

    __all__.extend(('environb', 'getenvb'))

def _fscodec():
    encoding = sys.getfilesystemencoding()
    if encoding == 'mbcs':
        errors = 'strict'
    else:
        errors = 'surrogateescape'

    def fsencode(filename):
        if isinstance(filename, bytes):
            return filename
        if isinstance(filename, str):
            return filename.encode(encoding, errors)
        raise TypeError('expect bytes or str, not %s' % type(filename).__name__)

    def fsdecode(filename):
        if isinstance(filename, str):
            return filename
        if isinstance(filename, bytes):
            return filename.decode(encoding, errors)
        raise TypeError('expect bytes or str, not %s' % type(filename).__name__)

    return (fsencode, fsdecode)

(fsencode, fsdecode) = _fscodec()
del _fscodec
if _exists('fork') and not _exists('spawnv') and _exists('execv'):
    P_WAIT = 0
    P_NOWAIT = P_NOWAITO = 1
    __all__.extend(['P_WAIT', 'P_NOWAIT', 'P_NOWAITO'])

    def _spawnvef(mode, file, args, env, func):
        pid = fork()
        if not pid:
            try:
                if env is None:
                    func(file, args)
                else:
                    func(file, args, env)
            except:
                _exit(127)
        else:
            if mode == P_NOWAIT:
                return pid
            while True:
                (wpid, sts) = waitpid(pid, 0)
                if WIFSTOPPED(sts):
                    continue
                else:
                    if WIFSIGNALED(sts):
                        return -WTERMSIG(sts)
                    if WIFEXITED(sts):
                        return WEXITSTATUS(sts)
                    raise error('Not stopped, signaled or exited???')

    def spawnv(mode, file, args):
        return _spawnvef(mode, file, args, None, execv)

    def spawnve(mode, file, args, env):
        return _spawnvef(mode, file, args, env, execve)

    def spawnvp(mode, file, args):
        return _spawnvef(mode, file, args, None, execvp)

    def spawnvpe(mode, file, args, env):
        return _spawnvef(mode, file, args, env, execvpe)

if _exists('spawnv'):

    def spawnl(mode, file, *args):
        return spawnv(mode, file, args)

    def spawnle(mode, file, *args):
        env = args[-1]
        return spawnve(mode, file, args[:-1], env)

    __all__.extend(['spawnv', 'spawnve', 'spawnl', 'spawnle'])
if _exists('spawnvp'):

    def spawnlp(mode, file, *args):
        return spawnvp(mode, file, args)

    def spawnlpe(mode, file, *args):
        env = args[-1]
        return spawnvpe(mode, file, args[:-1], env)

    __all__.extend(['spawnvp', 'spawnvpe', 'spawnlp', 'spawnlpe'])
import copyreg as _copyreg

def _make_stat_result(tup, dict):
    return stat_result(tup, dict)

def _pickle_stat_result(sr):
    (type, args) = sr.__reduce__()
    return (_make_stat_result, args)

try:
    _copyreg.pickle(stat_result, _pickle_stat_result, _make_stat_result)
except NameError:
    pass

def _make_statvfs_result(tup, dict):
    return statvfs_result(tup, dict)

def _pickle_statvfs_result(sr):
    (type, args) = sr.__reduce__()
    return (_make_statvfs_result, args)

try:
    _copyreg.pickle(statvfs_result, _pickle_statvfs_result, _make_statvfs_result)
except NameError:
    pass

def popen(cmd, mode='r', buffering=-1):
    if not isinstance(cmd, str):
        raise TypeError('invalid cmd type (%s, expected string)' % type(cmd))
    if mode not in ('r', 'w'):
        raise ValueError('invalid mode %r' % mode)
    if buffering == 0 or buffering is None:
        raise ValueError('popen() does not support unbuffered streams')
    import subprocess
    import io
    if mode == 'r':
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, bufsize=buffering)
        return _wrap_close(io.TextIOWrapper(proc.stdout), proc)
    proc = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, bufsize=buffering)
    return _wrap_close(io.TextIOWrapper(proc.stdin), proc)

class _wrap_close:
    __qualname__ = '_wrap_close'

    def __init__(self, stream, proc):
        self._stream = stream
        self._proc = proc

    def close(self):
        self._stream.close()
        returncode = self._proc.wait()
        if returncode == 0:
            return
        if name == 'nt':
            return returncode
        return returncode << 8

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def __iter__(self):
        return iter(self._stream)

def fdopen(fd, *args, **kwargs):
    if not isinstance(fd, int):
        raise TypeError('invalid fd type (%s, expected integer)' % type(fd))
    import io
    return io.open(fd, *args, **kwargs)

