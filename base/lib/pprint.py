import sys as _sys
from collections import OrderedDict as _OrderedDict
from io import StringIO as _StringIO
__all__ = ['pprint', 'pformat', 'isreadable', 'isrecursive', 'saferepr', 'PrettyPrinter']
_commajoin = ', '.join
_id = id
_len = len
_type = type

def pprint(object, stream=None, indent=1, width=80, depth=None):
    printer = PrettyPrinter(stream=stream, indent=indent, width=width, depth=depth)
    printer.pprint(object)

def pformat(object, indent=1, width=80, depth=None):
    return PrettyPrinter(indent=indent, width=width, depth=depth).pformat(object)

def saferepr(object):
    return _safe_repr(object, {}, None, 0)[0]

def isreadable(object):
    return _safe_repr(object, {}, None, 0)[1]

def isrecursive(object):
    return _safe_repr(object, {}, None, 0)[2]

class _safe_key:
    __qualname__ = '_safe_key'
    __slots__ = ['obj']

    def __init__(self, obj):
        self.obj = obj

    def __lt__(self, other):
        try:
            rv = self.obj.__lt__(other.obj)
        except TypeError:
            rv = NotImplemented
        if rv is NotImplemented:
            rv = (str(type(self.obj)), id(self.obj)) < (str(type(other.obj)), id(other.obj))
        return rv

def _safe_tuple(t):
    return (_safe_key(t[0]), _safe_key(t[1]))

class PrettyPrinter:
    __qualname__ = 'PrettyPrinter'

    def __init__(self, indent=1, width=80, depth=None, stream=None):
        indent = int(indent)
        width = int(width)
        self._depth = depth
        self._indent_per_level = indent
        self._width = width
        if stream is not None:
            self._stream = stream
        else:
            self._stream = _sys.stdout

    def pprint(self, object):
        self._format(object, self._stream, 0, 0, {}, 0)
        self._stream.write('\n')

    def pformat(self, object):
        sio = _StringIO()
        self._format(object, sio, 0, 0, {}, 0)
        return sio.getvalue()

    def isrecursive(self, object):
        return self.format(object, {}, 0, 0)[2]

    def isreadable(self, object):
        (s, readable, recursive) = self.format(object, {}, 0, 0)
        return readable and not recursive

    def _format(self, object, stream, indent, allowance, context, level):
        level = level + 1
        objid = _id(object)
        if objid in context:
            stream.write(_recursion(object))
            self._recursive = True
            self._readable = False
            return
        rep = self._repr(object, context, level - 1)
        typ = _type(object)
        sepLines = _len(rep) > self._width - 1 - indent - allowance
        write = stream.write
        if self._depth and level > self._depth:
            write(rep)
            return
        if sepLines:
            r = getattr(typ, '__repr__', None)
            if issubclass(typ, dict):
                write('{')
                if self._indent_per_level > 1:
                    write((self._indent_per_level - 1)*' ')
                length = _len(object)
                if length:
                    context[objid] = 1
                    indent = indent + self._indent_per_level
                    if issubclass(typ, _OrderedDict):
                        items = list(object.items())
                    else:
                        items = sorted(object.items(), key=_safe_tuple)
                    (key, ent) = items[0]
                    rep = self._repr(key, context, level)
                    write(rep)
                    write(': ')
                    self._format(ent, stream, indent + _len(rep) + 2, allowance + 1, context, level)
                    if length > 1:
                        for (key, ent) in items[1:]:
                            rep = self._repr(key, context, level)
                            write(',\n%s%s: ' % (' '*indent, rep))
                            self._format(ent, stream, indent + _len(rep) + 2, allowance + 1, context, level)
                    indent = indent - self._indent_per_level
                    del context[objid]
                write('}')
                return
            if issubclass(typ, list) and r is list.__repr__ or (issubclass(typ, tuple) and r is tuple.__repr__ or issubclass(typ, set) and r is set.__repr__) or issubclass(typ, frozenset) and r is frozenset.__repr__:
                length = _len(object)
                if issubclass(typ, list):
                    write('[')
                    endchar = ']'
                elif issubclass(typ, tuple):
                    write('(')
                    endchar = ')'
                else:
                    if not length:
                        write(rep)
                        return
                    if typ is set:
                        write('{')
                        endchar = '}'
                    else:
                        write(typ.__name__)
                        write('({')
                        endchar = '})'
                        indent += len(typ.__name__) + 1
                    object = sorted(object, key=_safe_key)
                if self._indent_per_level > 1:
                    write((self._indent_per_level - 1)*' ')
                if length:
                    context[objid] = 1
                    indent = indent + self._indent_per_level
                    self._format(object[0], stream, indent, allowance + 1, context, level)
                    if length > 1:
                        for ent in object[1:]:
                            write(',\n' + ' '*indent)
                            self._format(ent, stream, indent, allowance + 1, context, level)
                    indent = indent - self._indent_per_level
                    del context[objid]
                if issubclass(typ, tuple) and length == 1:
                    write(',')
                write(endchar)
                return
        write(rep)

    def _repr(self, object, context, level):
        (repr, readable, recursive) = self.format(object, context.copy(), self._depth, level)
        if not readable:
            self._readable = False
        if recursive:
            self._recursive = True
        return repr

    def format(self, object, context, maxlevels, level):
        return _safe_repr(object, context, maxlevels, level)

def _safe_repr(object, context, maxlevels, level):
    typ = _type(object)
    if typ is str:
        if 'locale' not in _sys.modules:
            return (repr(object), True, False)
        if "'" in object and '"' not in object:
            closure = '"'
            quotes = {'"': '\\"'}
        else:
            closure = "'"
            quotes = {"'": "\\'"}
        qget = quotes.get
        sio = _StringIO()
        write = sio.write
        for char in object:
            if char.isalpha():
                write(char)
            else:
                write(qget(char, repr(char)[1:-1]))
        return ('%s%s%s' % (closure, sio.getvalue(), closure), True, False)
    r = getattr(typ, '__repr__', None)
    if issubclass(typ, dict) and r is dict.__repr__:
        if not object:
            return ('{}', True, False)
        objid = _id(object)
        if maxlevels and level >= maxlevels:
            return ('{...}', False, objid in context)
        if objid in context:
            return (_recursion(object), False, True)
        context[objid] = 1
        readable = True
        recursive = False
        components = []
        append = components.append
        level += 1
        saferepr = _safe_repr
        items = sorted(object.items(), key=_safe_tuple)
        for (k, v) in items:
            (krepr, kreadable, krecur) = saferepr(k, context, maxlevels, level)
            (vrepr, vreadable, vrecur) = saferepr(v, context, maxlevels, level)
            append('%s: %s' % (krepr, vrepr))
            readable = readable and (kreadable and vreadable)
            while krecur or vrecur:
                recursive = True
        del context[objid]
        return ('{%s}' % _commajoin(components), readable, recursive)
    if issubclass(typ, list) and r is list.__repr__ or issubclass(typ, tuple) and r is tuple.__repr__:
        if issubclass(typ, list):
            if not object:
                return ('[]', True, False)
            format = '[%s]'
        elif _len(object) == 1:
            format = '(%s,)'
        else:
            if not object:
                return ('()', True, False)
            format = '(%s)'
        objid = _id(object)
        if maxlevels and level >= maxlevels:
            return (format % '...', False, objid in context)
        if objid in context:
            return (_recursion(object), False, True)
        context[objid] = 1
        readable = True
        recursive = False
        components = []
        append = components.append
        level += 1
        for o in object:
            (orepr, oreadable, orecur) = _safe_repr(o, context, maxlevels, level)
            append(orepr)
            if not oreadable:
                readable = False
            while orecur:
                recursive = True
        del context[objid]
        return (format % _commajoin(components), readable, recursive)
    rep = repr(object)
    return (rep, rep and not rep.startswith('<'), False)

def _recursion(object):
    return '<Recursion on %s with id=%s>' % (_type(object).__name__, _id(object))

def _perfcheck(object=None):
    import time
    if object is None:
        object = [('string', (1, 2), [3, 4], {5: 6, 7: 8})]*100000
    p = PrettyPrinter()
    t1 = time.time()
    _safe_repr(object, {}, None, 0)
    t2 = time.time()
    p.pformat(object)
    t3 = time.time()
    print('_safe_repr:', t2 - t1)
    print('pformat:', t3 - t2)

if __name__ == '__main__':
    _perfcheck()
