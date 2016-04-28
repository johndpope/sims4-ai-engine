import os
import sys
import stat
import genericpath
from genericpath import *
__all__ = ['normcase', 'isabs', 'join', 'splitdrive', 'split', 'splitext', 'basename', 'dirname', 'commonprefix', 'getsize', 'getmtime', 'getatime', 'getctime', 'islink', 'exists', 'lexists', 'isdir', 'isfile', 'ismount', 'expanduser', 'expandvars', 'normpath', 'abspath', 'splitunc', 'curdir', 'pardir', 'sep', 'pathsep', 'defpath', 'altsep', 'extsep', 'devnull', 'realpath', 'supports_unicode_filenames', 'relpath', 'samefile', 'sameopenfile']
curdir = '.'
pardir = '..'
extsep = '.'
sep = '\\'
pathsep = ';'
altsep = '/'
defpath = '.;C:\\bin'
if 'ce' in sys.builtin_module_names:
    defpath = '\\Windows'
elif 'os2' in sys.builtin_module_names:
    altsep = '/'
devnull = 'nul'

def _get_empty(path):
    if isinstance(path, bytes):
        return b''
    return ''

def _get_sep(path):
    if isinstance(path, bytes):
        return b'\\'
    return '\\'

def _get_altsep(path):
    if isinstance(path, bytes):
        return b'/'
    return '/'

def _get_bothseps(path):
    if isinstance(path, bytes):
        return b'\\/'
    return '\\/'

def _get_dot(path):
    if isinstance(path, bytes):
        return b'.'
    return '.'

def _get_colon(path):
    if isinstance(path, bytes):
        return b':'
    return ':'

def _get_special(path):
    if isinstance(path, bytes):
        return (b'\\\\.\\', b'\\\\?\\')
    return ('\\\\.\\', '\\\\?\\')

def normcase(s):
    if not isinstance(s, (bytes, str)):
        raise TypeError("normcase() argument must be str or bytes, not '{}'".format(s.__class__.__name__))
    return s.replace(_get_altsep(s), _get_sep(s)).lower()

def isabs(s):
    s = splitdrive(s)[1]
    return len(s) > 0 and s[:1] in _get_bothseps(s)

def join(path, *paths):
    sep = _get_sep(path)
    seps = _get_bothseps(path)
    colon = _get_colon(path)
    (result_drive, result_path) = splitdrive(path)
    for p in paths:
        (p_drive, p_path) = splitdrive(p)
        if p_path and p_path[0] in seps:
            if p_drive or not result_drive:
                result_drive = p_drive
            result_path = p_path
        elif p_drive and p_drive != result_drive:
            if p_drive.lower() != result_drive.lower():
                result_drive = p_drive
                result_path = p_path
            result_drive = p_drive
        if result_path and result_path[-1] not in seps:
            result_path = result_path + sep
        result_path = result_path + p_path
    if result_path and (result_path[0] not in seps and result_drive) and result_drive[-1:] != colon:
        return result_drive + sep + result_path
    return result_drive + result_path

def splitdrive(p):
    empty = _get_empty(p)
    if len(p) > 1:
        sep = _get_sep(p)
        normp = p.replace(_get_altsep(p), sep)
        if normp[0:2] == sep*2 and normp[2:3] != sep:
            index = normp.find(sep, 2)
            if index == -1:
                return (empty, p)
            index2 = normp.find(sep, index + 1)
            if index2 == index + 1:
                return (empty, p)
            if index2 == -1:
                index2 = len(p)
            return (p[:index2], p[index2:])
        if normp[1:2] == _get_colon(p):
            return (p[:2], p[2:])
    return (empty, p)

def splitunc(p):
    import warnings
    warnings.warn('ntpath.splitunc is deprecated, use ntpath.splitdrive instead', DeprecationWarning, 2)
    (drive, path) = splitdrive(p)
    if len(drive) == 2:
        return (p[:0], p)
    return (drive, path)

def split(p):
    seps = _get_bothseps(p)
    (d, p) = splitdrive(p)
    i = len(p)
    while i:
        while p[i - 1] not in seps:
            i -= 1
    (head, tail) = (p[:i], p[i:])
    head2 = head
    while head2:
        while head2[-1:] in seps:
            head2 = head2[:-1]
    head = head2 or head
    return (d + head, tail)

def splitext(p):
    return genericpath._splitext(p, _get_sep(p), _get_altsep(p), _get_dot(p))

splitext.__doc__ = genericpath._splitext.__doc__

def basename(p):
    return split(p)[1]

def dirname(p):
    return split(p)[0]

def islink(path):
    try:
        st = os.lstat(path)
    except (os.error, AttributeError):
        return False
    return stat.S_ISLNK(st.st_mode)

def lexists(path):
    try:
        st = os.lstat(path)
    except (os.error, WindowsError):
        return False
    return True

def ismount(path):
    seps = _get_bothseps(path)
    (root, rest) = splitdrive(path)
    if root and root[0] in seps:
        return not rest or rest in seps
    return rest in seps

def expanduser(path):
    if isinstance(path, bytes):
        tilde = b'~'
    else:
        tilde = '~'
    if not path.startswith(tilde):
        return path
    (i, n) = (1, len(path))
    while i < n:
        while path[i] not in _get_bothseps(path):
            i += 1
    if 'HOME' in os.environ:
        userhome = os.environ['HOME']
    elif 'USERPROFILE' in os.environ:
        userhome = os.environ['USERPROFILE']
    else:
        if 'HOMEPATH' not in os.environ:
            return path
        try:
            drive = os.environ['HOMEDRIVE']
        except KeyError:
            drive = ''
        userhome = join(drive, os.environ['HOMEPATH'])
    if isinstance(path, bytes):
        userhome = userhome.encode(sys.getfilesystemencoding())
    if i != 1:
        userhome = join(dirname(userhome), path[1:i])
    return userhome + path[i:]

def expandvars(path):
    if isinstance(path, bytes):
        if ord('$') not in path and ord('%') not in path:
            return path
        import string
        varchars = bytes(string.ascii_letters + string.digits + '_-', 'ascii')
        quote = b"'"
        percent = b'%'
        brace = b'{'
        dollar = b'$'
        environ = getattr(os, 'environb', None)
    else:
        if '$' not in path and '%' not in path:
            return path
        import string
        varchars = string.ascii_letters + string.digits + '_-'
        quote = "'"
        percent = '%'
        brace = '{'
        dollar = '$'
        environ = os.environ
    res = path[:0]
    index = 0
    pathlen = len(path)
    while index < pathlen:
        c = path[index:index + 1]
        if c == quote:
            path = path[index + 1:]
            pathlen = len(path)
            try:
                index = path.index(c)
                res += c + path[:index + 1]
            except ValueError:
                res += path
                index = pathlen - 1
        elif c == percent:
            if path[index + 1:index + 2] == percent:
                res += c
                index += 1
            else:
                path = path[index + 1:]
                pathlen = len(path)
                try:
                    index = path.index(percent)
                except ValueError:
                    res += percent + path
                    index = pathlen - 1
                var = path[:index]
                try:
                    if environ is None:
                        value = os.fsencode(os.environ[os.fsdecode(var)])
                    else:
                        value = environ[var]
                except KeyError:
                    value = percent + var + percent
                res += value
        elif c == dollar:
            if path[index + 1:index + 2] == dollar:
                res += c
                index += 1
            elif path[index + 1:index + 2] == brace:
                path = path[index + 2:]
                pathlen = len(path)
                try:
                    if isinstance(path, bytes):
                        index = path.index(b'}')
                    else:
                        index = path.index('}')
                except ValueError:
                    if isinstance(path, bytes):
                        res += b'${' + path
                    else:
                        res += '${' + path
                    index = pathlen - 1
                var = path[:index]
                try:
                    if environ is None:
                        value = os.fsencode(os.environ[os.fsdecode(var)])
                    else:
                        value = environ[var]
                except KeyError:
                    if isinstance(path, bytes):
                        value = b'${' + var + b'}'
                    else:
                        value = '${' + var + '}'
                res += value
            else:
                var = path[:0]
                index += 1
                c = path[index:index + 1]
                while c:
                    while c in varchars:
                        var += c
                        index += 1
                        c = path[index:index + 1]
                try:
                    if environ is None:
                        value = os.fsencode(os.environ[os.fsdecode(var)])
                    else:
                        value = environ[var]
                except KeyError:
                    value = dollar + var
                res += value
                index -= 1
        else:
            res += c
        index += 1
    return res

def normpath(path):
    sep = _get_sep(path)
    dotdot = _get_dot(path)*2
    special_prefixes = _get_special(path)
    if path.startswith(special_prefixes):
        return path
    path = path.replace(_get_altsep(path), sep)
    (prefix, path) = splitdrive(path)
    if path.startswith(sep):
        prefix += sep
        path = path.lstrip(sep)
    comps = path.split(sep)
    i = 0
    while i < len(comps):
        if not comps[i] or comps[i] == _get_dot(path):
            del comps[i]
        elif comps[i] == dotdot:
            if i > 0 and comps[i - 1] != dotdot:
                del comps[i - 1:i + 1]
                i -= 1
            elif i == 0 and prefix.endswith(_get_sep(path)):
                del comps[i]
            else:
                i += 1
                continue
                i += 1
        else:
            i += 1
    if not prefix and not comps:
        comps.append(_get_dot(path))
    return prefix + sep.join(comps)

try:
    from nt import _getfullpathname
except ImportError:

    def abspath(path):
        if not isabs(path):
            if isinstance(path, bytes):
                cwd = os.getcwdb()
            else:
                cwd = os.getcwd()
            path = join(cwd, path)
        return normpath(path)

def abspath(path):
    if path:
        try:
            path = _getfullpathname(path)
        except WindowsError:
            pass
    elif isinstance(path, bytes):
        path = os.getcwdb()
    else:
        path = os.getcwd()
    return normpath(path)

realpath = abspath
supports_unicode_filenames = hasattr(sys, 'getwindowsversion') and sys.getwindowsversion()[3] >= 2

def relpath(path, start=curdir):
    sep = _get_sep(path)
    if start is curdir:
        start = _get_dot(path)
    if not path:
        raise ValueError('no path specified')
    start_abs = abspath(normpath(start))
    path_abs = abspath(normpath(path))
    (start_drive, start_rest) = splitdrive(start_abs)
    (path_drive, path_rest) = splitdrive(path_abs)
    if normcase(start_drive) != normcase(path_drive):
        error = "path is on mount '{0}', start on mount '{1}'".format(path_drive, start_drive)
        raise ValueError(error)
    start_list = [x for x in start_rest.split(sep) if x]
    path_list = [x for x in path_rest.split(sep) if x]
    i = 0
    for (e1, e2) in zip(start_list, path_list):
        if normcase(e1) != normcase(e2):
            break
        i += 1
    if isinstance(path, bytes):
        pardir = b'..'
    else:
        pardir = '..'
    rel_list = [pardir]*(len(start_list) - i) + path_list[i:]
    if not rel_list:
        return _get_dot(path)
    return join(*rel_list)

try:
    if sys.getwindowsversion()[:2] >= (6, 0):
        from nt import _getfinalpathname
    else:
        raise ImportError
except (AttributeError, ImportError):

    def _getfinalpathname(f):
        return normcase(abspath(f))

def samefile(f1, f2):
    return _getfinalpathname(f1) == _getfinalpathname(f2)

try:
    from nt import _getfileinformation
except ImportError:

    def _getfileinformation(fd):
        return fd

def sameopenfile(f1, f2):
    return _getfileinformation(f1) == _getfileinformation(f2)

try:
    from nt import _isdir as isdir
except ImportError:
    pass
