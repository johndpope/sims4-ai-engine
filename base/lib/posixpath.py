import os
import sys
import stat
import genericpath
from genericpath import *
__all__ = ['normcase', 'isabs', 'join', 'splitdrive', 'split', 'splitext', 'basename', 'dirname', 'commonprefix', 'getsize', 'getmtime', 'getatime', 'getctime', 'islink', 'exists', 'lexists', 'isdir', 'isfile', 'ismount', 'expanduser', 'expandvars', 'normpath', 'abspath', 'samefile', 'sameopenfile', 'samestat', 'curdir', 'pardir', 'sep', 'pathsep', 'defpath', 'altsep', 'extsep', 'devnull', 'realpath', 'supports_unicode_filenames', 'relpath']
curdir = '.'
pardir = '..'
extsep = '.'
sep = '/'
pathsep = ':'
defpath = ':/bin:/usr/bin'
altsep = None
devnull = '/dev/null'

def _get_sep(path):
    if isinstance(path, bytes):
        return b'/'
    return '/'

def normcase(s):
    if not isinstance(s, (bytes, str)):
        raise TypeError("normcase() argument must be str or bytes, not '{}'".format(s.__class__.__name__))
    return s

def isabs(s):
    sep = _get_sep(s)
    return s.startswith(sep)

def join(a, *p):
    sep = _get_sep(a)
    path = a
    try:
        for b in p:
            if b.startswith(sep):
                path = b
            elif not path or path.endswith(sep):
                path += b
            else:
                path += sep + b
    except TypeError:
        valid_types = all(isinstance(s, (str, bytes, bytearray)) for s in (a,) + p)
        if valid_types:
            raise TypeError("Can't mix strings and bytes in path components.") from None
        raise
    return path

def split(p):
    sep = _get_sep(p)
    i = p.rfind(sep) + 1
    (head, tail) = (p[:i], p[i:])
    if head and head != sep*len(head):
        head = head.rstrip(sep)
    return (head, tail)

def splitext(p):
    if isinstance(p, bytes):
        sep = b'/'
        extsep = b'.'
    else:
        sep = '/'
        extsep = '.'
    return genericpath._splitext(p, sep, None, extsep)

splitext.__doc__ = genericpath._splitext.__doc__

def splitdrive(p):
    return (p[:0], p)

def basename(p):
    sep = _get_sep(p)
    i = p.rfind(sep) + 1
    return p[i:]

def dirname(p):
    sep = _get_sep(p)
    i = p.rfind(sep) + 1
    head = p[:i]
    if head and head != sep*len(head):
        head = head.rstrip(sep)
    return head

def islink(path):
    try:
        st = os.lstat(path)
    except (os.error, AttributeError):
        return False
    return stat.S_ISLNK(st.st_mode)

def lexists(path):
    try:
        os.lstat(path)
    except os.error:
        return False
    return True

def samefile(f1, f2):
    s1 = os.stat(f1)
    s2 = os.stat(f2)
    return samestat(s1, s2)

def sameopenfile(fp1, fp2):
    s1 = os.fstat(fp1)
    s2 = os.fstat(fp2)
    return samestat(s1, s2)

def samestat(s1, s2):
    return s1.st_ino == s2.st_ino and s1.st_dev == s2.st_dev

def ismount(path):
    if islink(path):
        return False
    try:
        s1 = os.lstat(path)
        if isinstance(path, bytes):
            parent = join(path, b'..')
        else:
            parent = join(path, '..')
        s2 = os.lstat(parent)
    except os.error:
        return False
    dev1 = s1.st_dev
    dev2 = s2.st_dev
    if dev1 != dev2:
        return True
    ino1 = s1.st_ino
    ino2 = s2.st_ino
    if ino1 == ino2:
        return True
    return False

def expanduser(path):
    if isinstance(path, bytes):
        tilde = b'~'
    else:
        tilde = '~'
    if not path.startswith(tilde):
        return path
    sep = _get_sep(path)
    i = path.find(sep, 1)
    if i < 0:
        i = len(path)
    if i == 1:
        if 'HOME' not in os.environ:
            import pwd
            userhome = pwd.getpwuid(os.getuid()).pw_dir
        else:
            userhome = os.environ['HOME']
    else:
        import pwd
        name = path[1:i]
        if isinstance(name, bytes):
            name = str(name, 'ASCII')
        try:
            pwent = pwd.getpwnam(name)
        except KeyError:
            return path
        userhome = pwent.pw_dir
    if isinstance(path, bytes):
        userhome = os.fsencode(userhome)
        root = b'/'
    else:
        root = '/'
    userhome = userhome.rstrip(root)
    return userhome + path[i:] or root

_varprog = None
_varprogb = None

def expandvars(path):
    global _varprogb, _varprog
    if isinstance(path, bytes):
        if b'$' not in path:
            return path
        if not _varprogb:
            import re
            _varprogb = re.compile(b'\\$(\\w+|\\{[^}]*\\})', re.ASCII)
        search = _varprogb.search
        start = b'{'
        end = b'}'
        environ = getattr(os, 'environb', None)
    else:
        if '$' not in path:
            return path
        if not _varprog:
            import re
            _varprog = re.compile('\\$(\\w+|\\{[^}]*\\})', re.ASCII)
        search = _varprog.search
        start = '{'
        end = '}'
        environ = os.environ
    i = 0
    while True:
        m = search(path, i)
        if not m:
            break
        (i, j) = m.span(0)
        name = m.group(1)
        if name.startswith(start) and name.endswith(end):
            name = name[1:-1]
        try:
            if environ is None:
                value = os.fsencode(os.environ[os.fsdecode(name)])
            else:
                value = environ[name]
        except KeyError:
            i = j
        tail = path[j:]
        path = path[:i] + value
        i = len(path)
        path += tail
    return path

def normpath(path):
    if isinstance(path, bytes):
        sep = b'/'
        empty = b''
        dot = b'.'
        dotdot = b'..'
    else:
        sep = '/'
        empty = ''
        dot = '.'
        dotdot = '..'
    if path == empty:
        return dot
    initial_slashes = path.startswith(sep)
    if initial_slashes and path.startswith(sep*2) and not path.startswith(sep*3):
        initial_slashes = 2
    comps = path.split(sep)
    new_comps = []
    for comp in comps:
        if comp in (empty, dot):
            pass
        if comp != dotdot or not initial_slashes and not new_comps or new_comps and new_comps[-1] == dotdot:
            new_comps.append(comp)
        else:
            while new_comps:
                new_comps.pop()
    comps = new_comps
    path = sep.join(comps)
    if initial_slashes:
        path = sep*initial_slashes + path
    return path or dot

def abspath(path):
    if not isabs(path):
        if isinstance(path, bytes):
            cwd = os.getcwdb()
        else:
            cwd = os.getcwd()
        path = join(cwd, path)
    return normpath(path)

def realpath(filename):
    (path, ok) = _joinrealpath(filename[:0], filename, {})
    return abspath(path)

def _joinrealpath(path, rest, seen):
    if isinstance(path, bytes):
        sep = b'/'
        curdir = b'.'
        pardir = b'..'
    else:
        sep = '/'
        curdir = '.'
        pardir = '..'
    if isabs(rest):
        rest = rest[1:]
        path = sep
    while rest:
        (name, _, rest) = rest.partition(sep)
        while not not name:
            if name == curdir:
                continue
            if name == pardir:
                if path:
                    (path, name) = split(path)
                    path = join(path, pardir, pardir)
                else:
                    path = pardir
                    continue
                    newpath = join(path, name)
                    if not islink(newpath):
                        path = newpath
                        continue
                    if newpath in seen:
                        path = seen[newpath]
                        if path is not None:
                            continue
                        return (join(newpath, rest), False)
                    seen[newpath] = None
                    (path, ok) = _joinrealpath(path, os.readlink(newpath), seen)
                    if not ok:
                        return (join(path, rest), False)
                    seen[newpath] = path
            newpath = join(path, name)
            if not islink(newpath):
                path = newpath
                continue
            if newpath in seen:
                path = seen[newpath]
                if path is not None:
                    continue
                return (join(newpath, rest), False)
            seen[newpath] = None
            (path, ok) = _joinrealpath(path, os.readlink(newpath), seen)
            if not ok:
                return (join(path, rest), False)
            seen[newpath] = path
    return (path, True)

supports_unicode_filenames = sys.platform == 'darwin'

def relpath(path, start=None):
    if not path:
        raise ValueError('no path specified')
    if isinstance(path, bytes):
        curdir = b'.'
        sep = b'/'
        pardir = b'..'
    else:
        curdir = '.'
        sep = '/'
        pardir = '..'
    if start is None:
        start = curdir
    start_list = [x for x in abspath(start).split(sep) if x]
    path_list = [x for x in abspath(path).split(sep) if x]
    i = len(commonprefix([start_list, path_list]))
    rel_list = [pardir]*(len(start_list) - i) + path_list[i:]
    if not rel_list:
        return curdir
    return join(*rel_list)

