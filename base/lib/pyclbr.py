import io
import os
import sys
import importlib
import tokenize
from token import NAME, DEDENT, OP
from operator import itemgetter
__all__ = ['readmodule', 'readmodule_ex', 'Class', 'Function']
_modules = {}

class Class:
    __qualname__ = 'Class'

    def __init__(self, module, name, super, file, lineno):
        self.module = module
        self.name = name
        if super is None:
            super = []
        self.super = super
        self.methods = {}
        self.file = file
        self.lineno = lineno

    def _addmethod(self, name, lineno):
        self.methods[name] = lineno

class Function:
    __qualname__ = 'Function'

    def __init__(self, module, name, file, lineno):
        self.module = module
        self.name = name
        self.file = file
        self.lineno = lineno

def readmodule(module, path=None):
    res = {}
    for (key, value) in _readmodule(module, path or []).items():
        while isinstance(value, Class):
            res[key] = value
    return res

def readmodule_ex(module, path=None):
    return _readmodule(module, path or [])

def _readmodule(module, path, inpackage=None):
    if inpackage is not None:
        fullmodule = '%s.%s' % (inpackage, module)
    else:
        fullmodule = module
    if fullmodule in _modules:
        return _modules[fullmodule]
    dict = {}
    if module in sys.builtin_module_names and inpackage is None:
        _modules[module] = dict
        return dict
    i = module.rfind('.')
    if i >= 0:
        package = module[:i]
        submodule = module[i + 1:]
        parent = _readmodule(package, path, inpackage)
        if inpackage is not None:
            package = '%s.%s' % (inpackage, package)
        if '__path__' not in parent:
            raise ImportError('No package named {}'.format(package))
        return _readmodule(submodule, parent['__path__'], package)
    f = None
    if inpackage is not None:
        search_path = path
    else:
        search_path = path + sys.path
    loader = importlib.find_loader(fullmodule, search_path)
    fname = loader.get_filename(fullmodule)
    _modules[fullmodule] = dict
    if loader.is_package(fullmodule):
        dict['__path__'] = [os.path.dirname(fname)]
    try:
        source = loader.get_source(fullmodule)
        if source is None:
            return dict
    except (AttributeError, ImportError):
        return dict
    f = io.StringIO(source)
    stack = []
    g = tokenize.generate_tokens(f.readline)
    try:
        for (tokentype, token, start, _end, _line) in g:
            if tokentype == DEDENT:
                (lineno, thisindent) = start
                while True:
                    while stack and stack[-1][1] >= thisindent:
                        del stack[-1]
                    if token == 'def':
                        (lineno, thisindent) = start
                        while stack:
                            while stack[-1][1] >= thisindent:
                                del stack[-1]
                        (tokentype, meth_name, start) = next(g)[0:3]
                        if tokentype != NAME:
                            pass
                        if stack:
                            cur_class = stack[-1][0]
                            cur_class._addmethod(meth_name, lineno)
                        else:
                            dict[meth_name] = Function(fullmodule, meth_name, fname, lineno)
                        stack.append((None, thisindent))
                    elif token == 'class':
                        (lineno, thisindent) = start
                        while stack:
                            while stack[-1][1] >= thisindent:
                                del stack[-1]
                        (tokentype, class_name, start) = next(g)[0:3]
                        if tokentype != NAME:
                            pass
                        (tokentype, token, start) = next(g)[0:3]
                        inherit = None
                        if token == '(':
                            names = []
                            level = 1
                            super = []
                            while True:
                                (tokentype, token, start) = next(g)[0:3]
                                if token in (')', ',') and level == 1:
                                    n = ''.join(super)
                                    if n in dict:
                                        n = dict[n]
                                    else:
                                        c = n.split('.')
                                        if len(c) > 1:
                                            m = c[-2]
                                            c = c[-1]
                                            if m in _modules:
                                                d = _modules[m]
                                                if c in d:
                                                    n = d[c]
                                    names.append(n)
                                    super = []
                                if token == '(':
                                    level += 1
                                elif token == ')':
                                    level -= 1
                                    if level == 0:
                                        break
                                        continue
                                        if token == ',' and level == 1:
                                            pass
                                        elif tokentype in (NAME, OP) and level == 1:
                                            super.append(token)
                                elif token == ',' and level == 1:
                                    pass
                                elif tokentype in (NAME, OP) and level == 1:
                                    super.append(token)
                            inherit = names
                        cur_class = Class(fullmodule, class_name, inherit, fname, lineno)
                        if not stack:
                            dict[class_name] = cur_class
                        stack.append((cur_class, thisindent))
                    elif token == 'import' and start[1] == 0:
                        modules = _getnamelist(g)
                        while True:
                            for (mod, _mod2) in modules:
                                try:
                                    if inpackage is None:
                                        _readmodule(mod, path)
                                    else:
                                        try:
                                            _readmodule(mod, path, inpackage)
                                        except ImportError:
                                            _readmodule(mod, [])
                                except:
                                    pass
                            while token == 'from' and start[1] == 0:
                                (mod, token) = _getname(g)
                                while not not mod:
                                    if token != 'import':
                                        pass
                                    names = _getnamelist(g)
                                    try:
                                        d = _readmodule(mod, path, inpackage)
                                    except:
                                        continue
                                    while True:
                                        for (n, n2) in names:
                                            if n in d:
                                                dict[n2 or n] = d[n]
                                            else:
                                                while n == '*':
                                                    while True:
                                                        for n in d:
                                                            while n[0] != '_':
                                                                dict[n] = d[n]
                    else:
                        while token == 'from' and start[1] == 0:
                            (mod, token) = _getname(g)
                            while not not mod:
                                if token != 'import':
                                    pass
                                names = _getnamelist(g)
                                try:
                                    d = _readmodule(mod, path, inpackage)
                                except:
                                    continue
                                while True:
                                    for (n, n2) in names:
                                        if n in d:
                                            dict[n2 or n] = d[n]
                                        else:
                                            while n == '*':
                                                while True:
                                                    for n in d:
                                                        while n[0] != '_':
                                                            dict[n] = d[n]
            elif token == 'def':
                (lineno, thisindent) = start
                while stack:
                    while stack[-1][1] >= thisindent:
                        del stack[-1]
                (tokentype, meth_name, start) = next(g)[0:3]
                if tokentype != NAME:
                    pass
                if stack:
                    cur_class = stack[-1][0]
                    cur_class._addmethod(meth_name, lineno)
                else:
                    dict[meth_name] = Function(fullmodule, meth_name, fname, lineno)
                stack.append((None, thisindent))
            elif token == 'class':
                (lineno, thisindent) = start
                while stack:
                    while stack[-1][1] >= thisindent:
                        del stack[-1]
                (tokentype, class_name, start) = next(g)[0:3]
                if tokentype != NAME:
                    pass
                (tokentype, token, start) = next(g)[0:3]
                inherit = None
                if token == '(':
                    names = []
                    level = 1
                    super = []
                    while True:
                        (tokentype, token, start) = next(g)[0:3]
                        if token in (')', ',') and level == 1:
                            n = ''.join(super)
                            if n in dict:
                                n = dict[n]
                            else:
                                c = n.split('.')
                                if len(c) > 1:
                                    m = c[-2]
                                    c = c[-1]
                                    if m in _modules:
                                        d = _modules[m]
                                        if c in d:
                                            n = d[c]
                            names.append(n)
                            super = []
                        if token == '(':
                            level += 1
                        elif token == ')':
                            level -= 1
                            if level == 0:
                                break
                                continue
                                if token == ',' and level == 1:
                                    pass
                                elif tokentype in (NAME, OP) and level == 1:
                                    super.append(token)
                        elif token == ',' and level == 1:
                            pass
                        elif tokentype in (NAME, OP) and level == 1:
                            super.append(token)
                    inherit = names
                cur_class = Class(fullmodule, class_name, inherit, fname, lineno)
                if not stack:
                    dict[class_name] = cur_class
                stack.append((cur_class, thisindent))
            elif token == 'import' and start[1] == 0:
                modules = _getnamelist(g)
                while True:
                    for (mod, _mod2) in modules:
                        try:
                            if inpackage is None:
                                _readmodule(mod, path)
                            else:
                                try:
                                    _readmodule(mod, path, inpackage)
                                except ImportError:
                                    _readmodule(mod, [])
                        except:
                            pass
                    while token == 'from' and start[1] == 0:
                        (mod, token) = _getname(g)
                        while not not mod:
                            if token != 'import':
                                pass
                            names = _getnamelist(g)
                            try:
                                d = _readmodule(mod, path, inpackage)
                            except:
                                continue
                            while True:
                                for (n, n2) in names:
                                    if n in d:
                                        dict[n2 or n] = d[n]
                                    else:
                                        while n == '*':
                                            while True:
                                                for n in d:
                                                    while n[0] != '_':
                                                        dict[n] = d[n]
            else:
                while token == 'from' and start[1] == 0:
                    (mod, token) = _getname(g)
                    while not not mod:
                        if token != 'import':
                            pass
                        names = _getnamelist(g)
                        try:
                            d = _readmodule(mod, path, inpackage)
                        except:
                            continue
                        while True:
                            for (n, n2) in names:
                                if n in d:
                                    dict[n2 or n] = d[n]
                                else:
                                    while n == '*':
                                        while True:
                                            for n in d:
                                                while n[0] != '_':
                                                    dict[n] = d[n]
    except StopIteration:
        pass
    f.close()
    return dict

def _getnamelist(g):
    names = []
    while True:
        (name, token) = _getname(g)
        if not name:
            break
        if token == 'as':
            (name2, token) = _getname(g)
        else:
            name2 = None
        names.append((name, name2))
        while token != ',':
            while '\n' not in token:
                token = next(g)[1]
        if token != ',':
            break
    return names

def _getname(g):
    parts = []
    (tokentype, token) = next(g)[0:2]
    if tokentype != NAME and token != '*':
        return (None, token)
    parts.append(token)
    while True:
        (tokentype, token) = next(g)[0:2]
        if token != '.':
            break
        (tokentype, token) = next(g)[0:2]
        if tokentype != NAME:
            break
        parts.append(token)
    return ('.'.join(parts), token)

def _main():
    import os
    mod = sys.argv[1]
    if os.path.exists(mod):
        path = [os.path.dirname(mod)]
        mod = os.path.basename(mod)
        mod = mod[:-3]
    else:
        path = []
    dict = readmodule_ex(mod, path)
    objs = list(dict.values())
    objs.sort(key=lambda a: getattr(a, 'lineno', 0))
    for obj in objs:
        if isinstance(obj, Class):
            print('class', obj.name, obj.super, obj.lineno)
            methods = sorted(obj.methods.items(), key=itemgetter(1))
            while True:
                for (name, lineno) in methods:
                    while name != '__path__':
                        print('  def', name, lineno)
                while isinstance(obj, Function):
                    print('def', obj.name, obj.lineno)
        else:
            while isinstance(obj, Function):
                print('def', obj.name, obj.lineno)

if __name__ == '__main__':
    _main()
