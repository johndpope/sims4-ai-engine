import os
import re
import fnmatch
__all__ = ['glob', 'iglob']

def glob(pathname):
    return list(iglob(pathname))

def iglob(pathname):
    if not has_magic(pathname):
        if os.path.lexists(pathname):
            yield pathname
        return
    (dirname, basename) = os.path.split(pathname)
    if not dirname:
        for name in glob1(None, basename):
            yield name
        return
    if dirname != pathname and has_magic(dirname):
        dirs = iglob(dirname)
    else:
        dirs = [dirname]
    if has_magic(basename):
        glob_in_dir = glob1
    else:
        glob_in_dir = glob0
    for dirname in dirs:
        for name in glob_in_dir(dirname, basename):
            yield os.path.join(dirname, name)

def glob1(dirname, pattern):
    if not dirname:
        if isinstance(pattern, bytes):
            dirname = bytes(os.curdir, 'ASCII')
        else:
            dirname = os.curdir
    try:
        names = os.listdir(dirname)
    except os.error:
        return []
    if not _ishidden(pattern):
        names = [x for x in names if not _ishidden(x)]
    return fnmatch.filter(names, pattern)

def glob0(dirname, basename):
    if not basename:
        if os.path.isdir(dirname):
            return [basename]
    elif os.path.lexists(os.path.join(dirname, basename)):
        return [basename]
    return []

magic_check = re.compile('[*?[]')
magic_check_bytes = re.compile(b'[*?[]')

def has_magic(s):
    if isinstance(s, bytes):
        match = magic_check_bytes.search(s)
    else:
        match = magic_check.search(s)
    return match is not None

def _ishidden(path):
    return path[0] in ('.', 46)

