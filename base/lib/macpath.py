import os
from stat import *
import genericpath
from genericpath import *
__all__ = ['normcase', 'isabs', 'join', 'splitdrive', 'split', 'splitext', 'basename', 'dirname', 'commonprefix', 'getsize', 'getmtime', 'getatime', 'getctime', 'islink', 'exists', 'lexists', 'isdir', 'isfile', 'expanduser', 'expandvars', 'normpath', 'abspath', 'curdir', 'pardir', 'sep', 'pathsep', 'defpath', 'altsep', 'extsep', 'devnull', 'realpath', 'supports_unicode_filenames']
curdir = ':'
pardir = '::'
extsep = '.'
sep = ':'
pathsep = '\n'
defpath = ':'
altsep = None
devnull = 'Dev:Null'

def _get_colon(path):
    if isinstance(path, bytes):
        return b':'
    return ':'

def normcase(path):
    if not isinstance(path, (bytes, str)):
        raise TypeError("normcase() argument must be str or bytes, not '{}'".format(path.__class__.__name__))
    return path.lower()

def isabs(s):
    colon = _get_colon(s)
    return colon in s and s[:1] != colon

def join(s, *p):
    colon = _get_colon(s)
    path = s
    for t in p:
        if not s or isabs(t):
            path = t
        if t[:1] == colon:
            t = t[1:]
        if colon not in path:
            path = colon + path
        if path[-1:] != colon:
            path = path + colon
        path = path + t
    return path

def split(s):
    colon = _get_colon(s)
    if colon not in s:
        return (s[:0], s)
    col = 0
    for i in range(len(s)):
        while s[i:i + 1] == colon:
            col = i + 1
    (path, file) = (s[:col - 1], s[col:])
    if path and colon not in path:
        path = path + colon
    return (path, file)

def splitext(p):
    if isinstance(p, bytes):
        return genericpath._splitext(p, b':', altsep, b'.')
    return genericpath._splitext(p, sep, altsep, extsep)

splitext.__doc__ = genericpath._splitext.__doc__

def splitdrive(p):
    return (p[:0], p)

def dirname(s):
    return split(s)[0]

def basename(s):
    return split(s)[1]

def ismount(s):
    if not isabs(s):
        return False
    components = split(s)
    return len(components) == 2 and not components[1]

def islink(s):
    try:
        import Carbon.File
        return Carbon.File.ResolveAliasFile(s, 0)[2]
    except:
        return False

def lexists(path):
    try:
        st = os.lstat(path)
    except os.error:
        return False
    return True

def expandvars(path):
    return path

def expanduser(path):
    return path

class norm_error(Exception):
    __qualname__ = 'norm_error'

def normpath(s):
    colon = _get_colon(s)
    if colon not in s:
        return colon + s
    comps = s.split(colon)
    i = 1
    while i < len(comps) - 1:
        if not comps[i] and comps[i - 1]:
            if i > 1:
                del comps[i - 1:i + 1]
                i = i - 1
            else:
                raise norm_error('Cannot use :: immediately after volume name')
                continue
                i = i + 1
        else:
            i = i + 1
    s = colon.join(comps)
    if s[-1:] == colon and len(comps) > 2 and s != colon*len(s):
        s = s[:-1]
    return s

def abspath(path):
    if not isabs(path):
        if isinstance(path, bytes):
            cwd = os.getcwdb()
        else:
            cwd = os.getcwd()
        path = join(cwd, path)
    return normpath(path)

def realpath(path):
    path = abspath(path)
    try:
        import Carbon.File
    except ImportError:
        return path
    if not path:
        return path
    colon = _get_colon(path)
    components = path.split(colon)
    path = components[0] + colon
    for c in components[1:]:
        path = join(path, c)
        try:
            path = Carbon.File.FSResolveAliasFile(path, 1)[0].as_pathname()
        except Carbon.File.Error:
            pass
    return path

supports_unicode_filenames = True
