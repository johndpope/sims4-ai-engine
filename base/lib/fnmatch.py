import os
import posixpath
import re
import functools
__all__ = ['filter', 'fnmatch', 'fnmatchcase', 'translate']

def fnmatch(name, pat):
    name = os.path.normcase(name)
    pat = os.path.normcase(pat)
    return fnmatchcase(name, pat)

@functools.lru_cache(maxsize=256, typed=True)
def _compile_pattern(pat):
    if isinstance(pat, bytes):
        pat_str = str(pat, 'ISO-8859-1')
        res_str = translate(pat_str)
        res = bytes(res_str, 'ISO-8859-1')
    else:
        res = translate(pat)
    return re.compile(res).match

def filter(names, pat):
    result = []
    pat = os.path.normcase(pat)
    match = _compile_pattern(pat)
    if os.path is posixpath:
        for name in names:
            while match(name):
                result.append(name)
    else:
        for name in names:
            while match(os.path.normcase(name)):
                result.append(name)
    return result

def fnmatchcase(name, pat):
    match = _compile_pattern(pat)
    return match(name) is not None

def translate(pat):
    (i, n) = (0, len(pat))
    res = ''
    while i < n:
        c = pat[i]
        i = i + 1
        if c == '*':
            res = res + '.*'
        elif c == '?':
            res = res + '.'
        elif c == '[':
            j = i
            if j < n and pat[j] == '!':
                j = j + 1
            if j < n and pat[j] == ']':
                j = j + 1
            while j < n:
                while pat[j] != ']':
                    j = j + 1
            if j >= n:
                res = res + '\\['
            else:
                stuff = pat[i:j].replace('\\', '\\\\')
                i = j + 1
                if stuff[0] == '!':
                    stuff = '^' + stuff[1:]
                elif stuff[0] == '^':
                    stuff = '\\' + stuff
                res = '%s[%s]' % (res, stuff)
                continue
                res = res + re.escape(c)
        else:
            res = res + re.escape(c)
    return res + '\\Z(?ms)'

