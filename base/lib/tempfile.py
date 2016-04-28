__all__ = ['NamedTemporaryFile', 'TemporaryFile', 'SpooledTemporaryFile', 'TemporaryDirectory', 'mkstemp', 'mkdtemp', 'mktemp', 'TMP_MAX', 'gettempprefix', 'tempdir', 'gettempdir']
import atexit as _atexit
import functools as _functools
import warnings as _warnings
import io as _io
import os as _os
import shutil as _shutil
import errno as _errno
from random import Random as _Random
try:
    import fcntl as _fcntl
except ImportError:

    def _set_cloexec(fd):
        pass

def _set_cloexec(fd):
    try:
        flags = _fcntl.fcntl(fd, _fcntl.F_GETFD, 0)
    except OSError:
        pass
    flags |= _fcntl.FD_CLOEXEC
    _fcntl.fcntl(fd, _fcntl.F_SETFD, flags)

try:
    import _thread
except ImportError:
    import _dummy_thread as _thread
_allocate_lock = _thread.allocate_lock
_text_openflags = _os.O_RDWR | _os.O_CREAT | _os.O_EXCL
if hasattr(_os, 'O_NOINHERIT'):
    _text_openflags |= _os.O_NOINHERIT
if hasattr(_os, 'O_NOFOLLOW'):
    _text_openflags |= _os.O_NOFOLLOW
_bin_openflags = _text_openflags
if hasattr(_os, 'O_BINARY'):
    _bin_openflags |= _os.O_BINARY
if hasattr(_os, 'TMP_MAX'):
    TMP_MAX = _os.TMP_MAX
else:
    TMP_MAX = 10000
template = 'tmp'
_once_lock = _allocate_lock()
if hasattr(_os, 'lstat'):
    _stat = _os.lstat
elif hasattr(_os, 'stat'):
    _stat = _os.stat
else:

    def _stat(fn):
        f = open(fn)
        f.close()

def _exists(fn):
    try:
        _stat(fn)
    except OSError:
        return False
    return True

class _RandomNameSequence:
    __qualname__ = '_RandomNameSequence'
    characters = 'abcdefghijklmnopqrstuvwxyz0123456789_'

    @property
    def rng(self):
        cur_pid = _os.getpid()
        if cur_pid != getattr(self, '_rng_pid', None):
            self._rng = _Random()
            self._rng_pid = cur_pid
        return self._rng

    def __iter__(self):
        return self

    def __next__(self):
        c = self.characters
        choose = self.rng.choice
        letters = [choose(c) for dummy in '123456']
        return ''.join(letters)

def _candidate_tempdir_list():
    dirlist = []
    for envname in ('TMPDIR', 'TEMP', 'TMP'):
        dirname = _os.getenv(envname)
        while dirname:
            dirlist.append(dirname)
    if _os.name == 'nt':
        dirlist.extend(['c:\\temp', 'c:\\tmp', '\\temp', '\\tmp'])
    else:
        dirlist.extend(['/tmp', '/var/tmp', '/usr/tmp'])
    try:
        dirlist.append(_os.getcwd())
    except (AttributeError, OSError):
        dirlist.append(_os.curdir)
    return dirlist

def _get_default_tempdir():
    namer = _RandomNameSequence()
    dirlist = _candidate_tempdir_list()
    for dir in dirlist:
        if dir != _os.curdir:
            dir = _os.path.normcase(_os.path.abspath(dir))
        for seq in range(100):
            name = next(namer)
            filename = _os.path.join(dir, name)
            try:
                fd = _os.open(filename, _bin_openflags, 384)
                try:
                    try:
                        with _io.open(fd, 'wb', closefd=False) as fp:
                            fp.write(b'blat')
                    finally:
                        _os.close(fd)
                finally:
                    _os.unlink(filename)
                return dir
            except FileExistsError:
                pass
            except OSError:
                break
    raise FileNotFoundError(_errno.ENOENT, 'No usable temporary directory found in %s' % dirlist)

_name_sequence = None

def _get_candidate_names():
    global _name_sequence
    if _name_sequence is None:
        _once_lock.acquire()
        try:
            while _name_sequence is None:
                _name_sequence = _RandomNameSequence()
        finally:
            _once_lock.release()
    return _name_sequence

def _mkstemp_inner(dir, pre, suf, flags):
    names = _get_candidate_names()
    for seq in range(TMP_MAX):
        name = next(names)
        file = _os.path.join(dir, pre + name + suf)
        try:
            fd = _os.open(file, flags, 384)
            _set_cloexec(fd)
            return (fd, _os.path.abspath(file))
        except FileExistsError:
            continue
        except PermissionError:
            if _os.name == 'nt':
                continue
            else:
                raise
    raise FileExistsError(_errno.EEXIST, 'No usable temporary file name found')

def gettempprefix():
    return template

tempdir = None

def gettempdir():
    global tempdir
    if tempdir is None:
        _once_lock.acquire()
        try:
            while tempdir is None:
                tempdir = _get_default_tempdir()
        finally:
            _once_lock.release()
    return tempdir

def mkstemp(suffix='', prefix=template, dir=None, text=False):
    if dir is None:
        dir = gettempdir()
    if text:
        flags = _text_openflags
    else:
        flags = _bin_openflags
    return _mkstemp_inner(dir, prefix, suffix, flags)

def mkdtemp(suffix='', prefix=template, dir=None):
    if dir is None:
        dir = gettempdir()
    names = _get_candidate_names()
    for seq in range(TMP_MAX):
        name = next(names)
        file = _os.path.join(dir, prefix + name + suffix)
        try:
            _os.mkdir(file, 448)
            return file
        except FileExistsError:
            continue
    raise FileExistsError(_errno.EEXIST, 'No usable temporary directory name found')

def mktemp(suffix='', prefix=template, dir=None):
    if dir is None:
        dir = gettempdir()
    names = _get_candidate_names()
    for seq in range(TMP_MAX):
        name = next(names)
        file = _os.path.join(dir, prefix + name + suffix)
        while not _exists(file):
            return file
    raise FileExistsError(_errno.EEXIST, 'No usable temporary filename found')

class _TemporaryFileCloser:
    __qualname__ = '_TemporaryFileCloser'
    file = None
    close_called = False

    def __init__(self, file, name, delete=True):
        self.file = file
        self.name = name
        self.delete = delete

    if _os.name != 'nt':

        def close(self, unlink=_os.unlink):
            if not self.close_called and self.file is not None:
                self.close_called = True
                self.file.close()
                if self.delete:
                    unlink(self.name)

        def __del__(self):
            self.close()

    else:

        def close(self):
            if not self.close_called:
                self.close_called = True
                self.file.close()

class _TemporaryFileWrapper:
    __qualname__ = '_TemporaryFileWrapper'

    def __init__(self, file, name, delete=True):
        self.file = file
        self.name = name
        self.delete = delete
        self._closer = _TemporaryFileCloser(file, name, delete)

    def __getattr__(self, name):
        file = self.__dict__['file']
        a = getattr(file, name)
        if hasattr(a, '__call__'):
            func = a

            @_functools.wraps(func)
            def func_wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            func_wrapper._closer = self._closer
            a = func_wrapper
        if not isinstance(a, int):
            setattr(self, name, a)
        return a

    def __enter__(self):
        self.file.__enter__()
        return self

    def __exit__(self, exc, value, tb):
        result = self.file.__exit__(exc, value, tb)
        self.close()
        return result

    def close(self):
        self._closer.close()

    def __iter__(self):
        return iter(self.file)

def NamedTemporaryFile(mode='w+b', buffering=-1, encoding=None, newline=None, suffix='', prefix=template, dir=None, delete=True):
    if dir is None:
        dir = gettempdir()
    flags = _bin_openflags
    if _os.name == 'nt' and delete:
        flags |= _os.O_TEMPORARY
    (fd, name) = _mkstemp_inner(dir, prefix, suffix, flags)
    file = _io.open(fd, mode, buffering=buffering, newline=newline, encoding=encoding)
    return _TemporaryFileWrapper(file, name, delete)

if _os.name != 'posix' or _os.sys.platform == 'cygwin':
    TemporaryFile = NamedTemporaryFile
else:

    def TemporaryFile(mode='w+b', buffering=-1, encoding=None, newline=None, suffix='', prefix=template, dir=None):
        if dir is None:
            dir = gettempdir()
        flags = _bin_openflags
        (fd, name) = _mkstemp_inner(dir, prefix, suffix, flags)
        try:
            _os.unlink(name)
            return _io.open(fd, mode, buffering=buffering, newline=newline, encoding=encoding)
        except:
            _os.close(fd)
            raise

class SpooledTemporaryFile:
    __qualname__ = 'SpooledTemporaryFile'
    _rolled = False

    def __init__(self, max_size=0, mode='w+b', buffering=-1, encoding=None, newline=None, suffix='', prefix=template, dir=None):
        if 'b' in mode:
            self._file = _io.BytesIO()
        else:
            self._file = _io.StringIO(newline='\n')
        self._max_size = max_size
        self._rolled = False
        self._TemporaryFileArgs = {'mode': mode, 'buffering': buffering, 'suffix': suffix, 'prefix': prefix, 'encoding': encoding, 'newline': newline, 'dir': dir}

    def _check(self, file):
        if self._rolled:
            return
        max_size = self._max_size
        if max_size and file.tell() > max_size:
            self.rollover()

    def rollover(self):
        if self._rolled:
            return
        file = self._file
        newfile = self._file = TemporaryFile(**self._TemporaryFileArgs)
        del self._TemporaryFileArgs
        newfile.write(file.getvalue())
        newfile.seek(file.tell(), 0)
        self._rolled = True

    def __enter__(self):
        if self._file.closed:
            raise ValueError('Cannot enter context with closed file')
        return self

    def __exit__(self, exc, value, tb):
        self._file.close()

    def __iter__(self):
        return self._file.__iter__()

    def close(self):
        self._file.close()

    @property
    def closed(self):
        return self._file.closed

    @property
    def encoding(self):
        try:
            return self._file.encoding
        except AttributeError:
            if 'b' in self._TemporaryFileArgs['mode']:
                raise
            return self._TemporaryFileArgs['encoding']

    def fileno(self):
        self.rollover()
        return self._file.fileno()

    def flush(self):
        self._file.flush()

    def isatty(self):
        return self._file.isatty()

    @property
    def mode(self):
        try:
            return self._file.mode
        except AttributeError:
            return self._TemporaryFileArgs['mode']

    @property
    def name(self):
        try:
            return self._file.name
        except AttributeError:
            return

    @property
    def newlines(self):
        try:
            return self._file.newlines
        except AttributeError:
            if 'b' in self._TemporaryFileArgs['mode']:
                raise
            return self._TemporaryFileArgs['newline']

    def read(self, *args):
        return self._file.read(*args)

    def readline(self, *args):
        return self._file.readline(*args)

    def readlines(self, *args):
        return self._file.readlines(*args)

    def seek(self, *args):
        self._file.seek(*args)

    @property
    def softspace(self):
        return self._file.softspace

    def tell(self):
        return self._file.tell()

    def truncate(self, size=None):
        if size is None:
            self._file.truncate()
        else:
            if size > self._max_size:
                self.rollover()
            self._file.truncate(size)

    def write(self, s):
        file = self._file
        rv = file.write(s)
        self._check(file)
        return rv

    def writelines(self, iterable):
        file = self._file
        rv = file.writelines(iterable)
        self._check(file)
        return rv

class TemporaryDirectory(object):
    __qualname__ = 'TemporaryDirectory'
    name = None
    _closed = False

    def __init__(self, suffix='', prefix=template, dir=None):
        self.name = mkdtemp(suffix, prefix, dir)

    def __repr__(self):
        return '<{} {!r}>'.format(self.__class__.__name__, self.name)

    def __enter__(self):
        return self.name

    def cleanup(self, _warn=False, _warnings=_warnings):
        if self.name and not self._closed:
            try:
                _shutil.rmtree(self.name)
            except (TypeError, AttributeError) as ex:
                if 'None' not in '%s' % (ex,):
                    raise
                self._rmtree(self.name)
            self._closed = True
            if _warn and _warnings.warn:
                try:
                    _warnings.warn('Implicitly cleaning up {!r}'.format(self), ResourceWarning)
                except:
                    if _is_running:
                        raise

    def __exit__(self, exc, value, tb):
        self.cleanup()

    def __del__(self):
        self.cleanup(_warn=True)

    def _rmtree(self, path, _OSError=OSError, _sep=_os.path.sep, _listdir=_os.listdir, _remove=_os.remove, _rmdir=_os.rmdir):
        if not isinstance(path, str):
            _sep = _sep.encode()
        try:
            for name in _listdir(path):
                fullname = path + _sep + name
                try:
                    _remove(fullname)
                except _OSError:
                    self._rmtree(fullname)
            _rmdir(path)
        except _OSError:
            pass

_is_running = True

def _on_shutdown():
    global _is_running
    _is_running = False

_atexit.register(_on_shutdown)
