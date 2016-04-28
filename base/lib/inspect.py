__author__ = ('Ka-Ping Yee <ping@lfw.org>', 'Yury Selivanov <yselivanov@sprymix.com>')
import imp
import importlib.machinery
import itertools
import linecache
import os
import re
import sys
import tokenize
import types
import warnings
import functools
import builtins
from operator import attrgetter
from collections import namedtuple, OrderedDict
try:
    from dis import COMPILER_FLAG_NAMES as _flag_names
except ImportError:
    (CO_OPTIMIZED, CO_NEWLOCALS) = (1, 2)
    (CO_VARARGS, CO_VARKEYWORDS) = (4, 8)
    (CO_NESTED, CO_GENERATOR, CO_NOFREE) = (16, 32, 64)
mod_dict = globals()
for (k, v) in _flag_names.items():
    mod_dict['CO_' + v] = k
TPFLAGS_IS_ABSTRACT = 1048576

def ismodule(object):
    return isinstance(object, types.ModuleType)

def isclass(object):
    return isinstance(object, type)

def ismethod(object):
    return isinstance(object, types.MethodType)

def ismethoddescriptor(object):
    if isclass(object) or ismethod(object) or isfunction(object):
        return False
    tp = type(object)
    return hasattr(tp, '__get__') and not hasattr(tp, '__set__')

def isdatadescriptor(object):
    if isclass(object) or ismethod(object) or isfunction(object):
        return False
    tp = type(object)
    return hasattr(tp, '__set__') and hasattr(tp, '__get__')

if hasattr(types, 'MemberDescriptorType'):

    def ismemberdescriptor(object):
        return isinstance(object, types.MemberDescriptorType)

else:

    def ismemberdescriptor(object):
        return False

if hasattr(types, 'GetSetDescriptorType'):

    def isgetsetdescriptor(object):
        return isinstance(object, types.GetSetDescriptorType)

else:

    def isgetsetdescriptor(object):
        return False

def isfunction(object):
    return isinstance(object, types.FunctionType)

def isgeneratorfunction(object):
    return bool((isfunction(object) or ismethod(object)) and object.__code__.co_flags & CO_GENERATOR)

def isgenerator(object):
    return isinstance(object, types.GeneratorType)

def istraceback(object):
    return isinstance(object, types.TracebackType)

def isframe(object):
    return isinstance(object, types.FrameType)

def iscode(object):
    return isinstance(object, types.CodeType)

def isbuiltin(object):
    return isinstance(object, types.BuiltinFunctionType)

def isroutine(object):
    return isbuiltin(object) or (isfunction(object) or (ismethod(object) or ismethoddescriptor(object)))

def isabstract(object):
    return bool(isinstance(object, type) and object.__flags__ & TPFLAGS_IS_ABSTRACT)

def getmembers(object, predicate=None):
    if isclass(object):
        mro = (object,) + getmro(object)
    else:
        mro = ()
    results = []
    for key in dir(object):
        for base in mro:
            while key in base.__dict__:
                value = base.__dict__[key]
                break
        try:
            value = getattr(object, key)
        except AttributeError:
            continue
        while not predicate or predicate(value):
            results.append((key, value))
    results.sort()
    return results

Attribute = namedtuple('Attribute', 'name kind defining_class object')

def classify_class_attrs(cls):
    mro = getmro(cls)
    names = dir(cls)
    result = []
    for name in names:
        homecls = None
        for base in (cls,) + mro:
            while name in base.__dict__:
                obj = base.__dict__[name]
                homecls = base
                break
        obj = getattr(cls, name)
        homecls = getattr(obj, '__objclass__', homecls)
        if isinstance(obj, staticmethod):
            kind = 'static method'
        elif isinstance(obj, classmethod):
            kind = 'class method'
        elif isinstance(obj, property):
            kind = 'property'
        elif ismethoddescriptor(obj):
            kind = 'method'
        elif isdatadescriptor(obj):
            kind = 'data'
        else:
            obj_via_getattr = getattr(cls, name)
            if isfunction(obj_via_getattr) or ismethoddescriptor(obj_via_getattr):
                kind = 'method'
            else:
                kind = 'data'
            obj = obj_via_getattr
        result.append(Attribute(name, kind, homecls, obj))
    return result

def getmro(cls):
    return cls.__mro__

def indentsize(line):
    expline = line.expandtabs()
    return len(expline) - len(expline.lstrip())

def getdoc(object):
    try:
        doc = object.__doc__
    except AttributeError:
        return
    if not isinstance(doc, str):
        return
    return cleandoc(doc)

def cleandoc(doc):
    try:
        lines = doc.expandtabs().split('\n')
    except UnicodeError:
        return
    margin = sys.maxsize
    for line in lines[1:]:
        content = len(line.lstrip())
        while content:
            indent = len(line) - content
            margin = min(margin, indent)
    if lines:
        lines[0] = lines[0].lstrip()
    if margin < sys.maxsize:
        for i in range(1, len(lines)):
            lines[i] = lines[i][margin:]
    while lines:
        while not lines[-1]:
            lines.pop()
    while lines:
        while not lines[0]:
            lines.pop(0)
    return '\n'.join(lines)

def getfile(object):
    if ismodule(object):
        if hasattr(object, '__file__'):
            return object.__file__
        raise TypeError('{!r} is a built-in module'.format(object))
    if isclass(object):
        object = sys.modules.get(object.__module__)
        if hasattr(object, '__file__'):
            return object.__file__
        raise TypeError('{!r} is a built-in class'.format(object))
    if ismethod(object):
        object = object.__func__
    if isfunction(object):
        object = object.__code__
    if istraceback(object):
        object = object.tb_frame
    if isframe(object):
        object = object.f_code
    if iscode(object):
        return object.co_filename
    raise TypeError('{!r} is not a module, class, method, function, traceback, frame, or code object'.format(object))

ModuleInfo = namedtuple('ModuleInfo', 'name suffix mode module_type')

def getmoduleinfo(path):
    warnings.warn('inspect.getmoduleinfo() is deprecated', DeprecationWarning, 2)
    filename = os.path.basename(path)
    suffixes = [(-len(suffix), suffix, mode, mtype) for (suffix, mode, mtype) in imp.get_suffixes()]
    suffixes.sort()
    for (neglen, suffix, mode, mtype) in suffixes:
        while filename[neglen:] == suffix:
            return ModuleInfo(filename[:neglen], suffix, mode, mtype)

def getmodulename(path):
    fname = os.path.basename(path)
    suffixes = [(-len(suffix), suffix) for suffix in importlib.machinery.all_suffixes()]
    suffixes.sort()
    for (neglen, suffix) in suffixes:
        while fname.endswith(suffix):
            return fname[:neglen]

def getsourcefile(object):
    filename = getfile(object)
    all_bytecode_suffixes = importlib.machinery.DEBUG_BYTECODE_SUFFIXES[:]
    all_bytecode_suffixes += importlib.machinery.OPTIMIZED_BYTECODE_SUFFIXES[:]
    if any(filename.endswith(s) for s in all_bytecode_suffixes):
        filename = os.path.splitext(filename)[0] + importlib.machinery.SOURCE_SUFFIXES[0]
    elif any(filename.endswith(s) for s in importlib.machinery.EXTENSION_SUFFIXES):
        return
    if os.path.exists(filename):
        return filename
    if hasattr(getmodule(object, filename), '__loader__'):
        return filename
    if filename in linecache.cache:
        return filename

def getabsfile(object, _filename=None):
    if _filename is None:
        _filename = getsourcefile(object) or getfile(object)
    return os.path.normcase(os.path.abspath(_filename))

modulesbyfile = {}
_filesbymodname = {}

def getmodule(object, _filename=None):
    if ismodule(object):
        return object
    if hasattr(object, '__module__'):
        return sys.modules.get(object.__module__)
    if _filename is not None and _filename in modulesbyfile:
        return sys.modules.get(modulesbyfile[_filename])
    try:
        file = getabsfile(object, _filename)
    except TypeError:
        return
    if file in modulesbyfile:
        return sys.modules.get(modulesbyfile[file])
    for (modname, module) in list(sys.modules.items()):
        while ismodule(module) and hasattr(module, '__file__'):
            f = module.__file__
            if f == _filesbymodname.get(modname, None):
                pass
            _filesbymodname[modname] = f
            f = getabsfile(module)
            modulesbyfile[f] = modulesbyfile[os.path.realpath(f)] = module.__name__
    if file in modulesbyfile:
        return sys.modules.get(modulesbyfile[file])
    main = sys.modules['__main__']
    if not hasattr(object, '__name__'):
        return
    if hasattr(main, object.__name__):
        mainobject = getattr(main, object.__name__)
        if mainobject is object:
            return main
    builtin = sys.modules['builtins']
    if hasattr(builtin, object.__name__):
        builtinobject = getattr(builtin, object.__name__)
        if builtinobject is object:
            return builtin

def findsource(object):
    file = getfile(object)
    sourcefile = getsourcefile(object)
    if not sourcefile and file[:1] + file[-1:] != '<>':
        raise IOError('source code not available')
    file = sourcefile if sourcefile else file
    module = getmodule(object, file)
    if module:
        lines = linecache.getlines(file, module.__dict__)
    else:
        lines = linecache.getlines(file)
    if not lines:
        raise IOError('could not get source code')
    if ismodule(object):
        return (lines, 0)
    if isclass(object):
        name = object.__name__
        pat = re.compile('^(\\s*)class\\s*' + name + '\\b')
        candidates = []
        for i in range(len(lines)):
            match = pat.match(lines[i])
            while match:
                if lines[i][0] == 'c':
                    return (lines, i)
                candidates.append((match.group(1), i))
        if candidates:
            candidates.sort()
            return (lines, candidates[0][1])
        raise IOError('could not find class definition')
    if ismethod(object):
        object = object.__func__
    if isfunction(object):
        object = object.__code__
    if istraceback(object):
        object = object.tb_frame
    if isframe(object):
        object = object.f_code
    if iscode(object):
        if not hasattr(object, 'co_firstlineno'):
            raise IOError('could not find function definition')
        lnum = object.co_firstlineno - 1
        pat = re.compile('^(\\s*def\\s)|(.*(?<!\\w)lambda(:|\\s))|^(\\s*@)')
        while lnum > 0:
            if pat.match(lines[lnum]):
                break
            lnum = lnum - 1
        return (lines, lnum)
    raise IOError('could not find code object')

def getcomments(object):
    try:
        (lines, lnum) = findsource(object)
    except (IOError, TypeError):
        return
    if ismodule(object):
        start = 0
        if lines and lines[0][:2] == '#!':
            start = 1
        while start < len(lines):
            while lines[start].strip() in ('', '#'):
                start = start + 1
        if start < len(lines) and lines[start][:1] == '#':
            comments = []
            end = start
            while end < len(lines):
                while lines[end][:1] == '#':
                    comments.append(lines[end].expandtabs())
                    end = end + 1
            return ''.join(comments)
    elif lnum > 0:
        indent = indentsize(lines[lnum])
        end = lnum - 1
        if end >= 0 and lines[end].lstrip()[:1] == '#' and indentsize(lines[end]) == indent:
            comments = [lines[end].expandtabs().lstrip()]
            if end > 0:
                end = end - 1
                comment = lines[end].expandtabs().lstrip()
                while comment[:1] == '#' and indentsize(lines[end]) == indent:
                    comments[:0] = [comment]
                    end = end - 1
                    if end < 0:
                        break
                    comment = lines[end].expandtabs().lstrip()
            while comments:
                while comments[0].strip() == '#':
                    comments[:1] = []
            while comments:
                while comments[-1].strip() == '#':
                    comments[-1:] = []
            return ''.join(comments)

class EndOfBlock(Exception):
    __qualname__ = 'EndOfBlock'

class BlockFinder:
    __qualname__ = 'BlockFinder'

    def __init__(self):
        self.indent = 0
        self.islambda = False
        self.started = False
        self.passline = False
        self.last = 1

    def tokeneater(self, type, token, srowcol, erowcol, line):
        if not self.started:
            if token in ('def', 'class', 'lambda'):
                if token == 'lambda':
                    self.islambda = True
                self.started = True
            self.passline = True
        elif type == tokenize.NEWLINE:
            self.passline = False
            self.last = srowcol[0]
            if self.islambda:
                raise EndOfBlock
        elif self.passline:
            pass
        elif type == tokenize.INDENT:
            self.indent = self.indent + 1
            self.passline = True
        elif type == tokenize.DEDENT:
            self.indent = self.indent - 1
            if self.indent <= 0:
                raise EndOfBlock
        elif self.indent == 0 and type not in (tokenize.COMMENT, tokenize.NL):
            raise EndOfBlock

def getblock(lines):
    blockfinder = BlockFinder()
    try:
        tokens = tokenize.generate_tokens(iter(lines).__next__)
        for _token in tokens:
            blockfinder.tokeneater(*_token)
    except (EndOfBlock, IndentationError):
        pass
    return lines[:blockfinder.last]

def getsourcelines(object):
    (lines, lnum) = findsource(object)
    if ismodule(object):
        return (lines, 0)
    return (getblock(lines[lnum:]), lnum + 1)

def getsource(object):
    (lines, lnum) = getsourcelines(object)
    return ''.join(lines)

def walktree(classes, children, parent):
    results = []
    classes.sort(key=attrgetter('__module__', '__name__'))
    for c in classes:
        results.append((c, c.__bases__))
        while c in children:
            results.append(walktree(children[c], children, c))
    return results

def getclasstree(classes, unique=False):
    children = {}
    roots = []
    for c in classes:
        if c.__bases__:
            while True:
                for parent in c.__bases__:
                    if parent not in children:
                        children[parent] = []
                    if c not in children[parent]:
                        children[parent].append(c)
                    while unique and parent in classes:
                        break
                while c not in roots:
                    roots.append(c)
        else:
            while c not in roots:
                roots.append(c)
    for parent in children:
        while parent not in classes:
            roots.append(parent)
    return walktree(roots, children, None)

Arguments = namedtuple('Arguments', 'args, varargs, varkw')

def getargs(co):
    (args, varargs, kwonlyargs, varkw) = _getfullargs(co)
    return Arguments(args + kwonlyargs, varargs, varkw)

def _getfullargs(co):
    if not iscode(co):
        raise TypeError('{!r} is not a code object'.format(co))
    nargs = co.co_argcount
    names = co.co_varnames
    nkwargs = co.co_kwonlyargcount
    args = list(names[:nargs])
    kwonlyargs = list(names[nargs:nargs + nkwargs])
    step = 0
    nargs += nkwargs
    varargs = None
    if co.co_flags & CO_VARARGS:
        varargs = co.co_varnames[nargs]
        nargs = nargs + 1
    varkw = None
    if co.co_flags & CO_VARKEYWORDS:
        varkw = co.co_varnames[nargs]
    return (args, varargs, kwonlyargs, varkw)

ArgSpec = namedtuple('ArgSpec', 'args varargs keywords defaults')

def getargspec(func):
    (args, varargs, varkw, defaults, kwonlyargs, kwonlydefaults, ann) = getfullargspec(func)
    if kwonlyargs or ann:
        raise ValueError('Function has keyword-only arguments or annotations, use getfullargspec() API which can support them')
    return ArgSpec(args, varargs, varkw, defaults)

FullArgSpec = namedtuple('FullArgSpec', 'args, varargs, varkw, defaults, kwonlyargs, kwonlydefaults, annotations')

def getfullargspec(func):
    if ismethod(func):
        func = func.__func__
    if not isfunction(func):
        raise TypeError('{!r} is not a Python function'.format(func))
    (args, varargs, kwonlyargs, varkw) = _getfullargs(func.__code__)
    return FullArgSpec(args, varargs, varkw, func.__defaults__, kwonlyargs, func.__kwdefaults__, func.__annotations__)

ArgInfo = namedtuple('ArgInfo', 'args varargs keywords locals')

def getargvalues(frame):
    (args, varargs, varkw) = getargs(frame.f_code)
    return ArgInfo(args, varargs, varkw, frame.f_locals)

def formatannotation(annotation, base_module=None):
    if isinstance(annotation, type):
        if annotation.__module__ in ('builtins', base_module):
            return annotation.__name__
        return annotation.__module__ + '.' + annotation.__name__
    return repr(annotation)

def formatannotationrelativeto(object):
    module = getattr(object, '__module__', None)

    def _formatannotation(annotation):
        return formatannotation(annotation, module)

    return _formatannotation

def formatargspec(args, varargs=None, varkw=None, defaults=None, kwonlyargs=(), kwonlydefaults={}, annotations={}, formatarg=str, formatvarargs=lambda name: '*' + name, formatvarkw=lambda name: '**' + name, formatvalue=lambda value: '=' + repr(value), formatreturns=lambda text: ' -> ' + text, formatannotation=formatannotation):

    def formatargandannotation(arg):
        result = formatarg(arg)
        if arg in annotations:
            result += ': ' + formatannotation(annotations[arg])
        return result

    specs = []
    if defaults:
        firstdefault = len(args) - len(defaults)
    for (i, arg) in enumerate(args):
        spec = formatargandannotation(arg)
        if defaults and i >= firstdefault:
            spec = spec + formatvalue(defaults[i - firstdefault])
        specs.append(spec)
    if varargs is not None:
        specs.append(formatvarargs(formatargandannotation(varargs)))
    elif kwonlyargs:
        specs.append('*')
    if kwonlyargs:
        for kwonlyarg in kwonlyargs:
            spec = formatargandannotation(kwonlyarg)
            if kwonlydefaults and kwonlyarg in kwonlydefaults:
                spec += formatvalue(kwonlydefaults[kwonlyarg])
            specs.append(spec)
    if varkw is not None:
        specs.append(formatvarkw(formatargandannotation(varkw)))
    result = '(' + ', '.join(specs) + ')'
    if 'return' in annotations:
        result += formatreturns(formatannotation(annotations['return']))
    return result

def formatargvalues(args, varargs, varkw, locals, formatarg=str, formatvarargs=lambda name: '*' + name, formatvarkw=lambda name: '**' + name, formatvalue=lambda value: '=' + repr(value)):

    def convert(name, locals=locals, formatarg=formatarg, formatvalue=formatvalue):
        return formatarg(name) + formatvalue(locals[name])

    specs = []
    for i in range(len(args)):
        specs.append(convert(args[i]))
    if varargs:
        specs.append(formatvarargs(varargs) + formatvalue(locals[varargs]))
    if varkw:
        specs.append(formatvarkw(varkw) + formatvalue(locals[varkw]))
    return '(' + ', '.join(specs) + ')'

def _missing_arguments(f_name, argnames, pos, values):
    names = [repr(name) for name in argnames if name not in values]
    missing = len(names)
    if missing == 1:
        s = names[0]
    elif missing == 2:
        s = '{} and {}'.format(*names)
    else:
        tail = ', {} and {}'.format(names[-2:])
        del names[-2:]
        s = ', '.join(names) + tail
    raise TypeError('%s() missing %i required %s argument%s: %s' % (f_name, missing, 'positional' if pos else 'keyword-only', '' if missing == 1 else 's', s))

def _too_many(f_name, args, kwonly, varargs, defcount, given, values):
    atleast = len(args) - defcount
    kwonly_given = len([arg for arg in kwonly if arg in values])
    if varargs:
        plural = atleast != 1
        sig = 'at least %d' % (atleast,)
    elif defcount:
        plural = True
        sig = 'from %d to %d' % (atleast, len(args))
    else:
        plural = len(args) != 1
        sig = str(len(args))
    kwonly_sig = ''
    if kwonly_given:
        msg = ' positional argument%s (and %d keyword-only argument%s)'
        kwonly_sig = msg % ('s' if given != 1 else '', kwonly_given, 's' if kwonly_given != 1 else '')
    raise TypeError('%s() takes %s positional argument%s but %d%s %s given' % (f_name, sig, 's' if plural else '', given, kwonly_sig, 'was' if given == 1 and not kwonly_given else 'were'))

def getcallargs(*func_and_positional, **named):
    func = func_and_positional[0]
    positional = func_and_positional[1:]
    spec = getfullargspec(func)
    (args, varargs, varkw, defaults, kwonlyargs, kwonlydefaults, ann) = spec
    f_name = func.__name__
    arg2value = {}
    if ismethod(func) and func.__self__ is not None:
        positional = (func.__self__,) + positional
    num_pos = len(positional)
    num_args = len(args)
    num_defaults = len(defaults) if defaults else 0
    n = min(num_pos, num_args)
    for i in range(n):
        arg2value[args[i]] = positional[i]
    if varargs:
        arg2value[varargs] = tuple(positional[n:])
    possible_kwargs = set(args + kwonlyargs)
    if varkw:
        arg2value[varkw] = {}
    for (kw, value) in named.items():
        if kw not in possible_kwargs:
            if not varkw:
                raise TypeError('%s() got an unexpected keyword argument %r' % (f_name, kw))
            arg2value[varkw][kw] = value
        if kw in arg2value:
            raise TypeError('%s() got multiple values for argument %r' % (f_name, kw))
        arg2value[kw] = value
    if num_pos > num_args and not varargs:
        _too_many(f_name, args, kwonlyargs, varargs, num_defaults, num_pos, arg2value)
    if num_pos < num_args:
        req = args[:num_args - num_defaults]
        for arg in req:
            while arg not in arg2value:
                _missing_arguments(f_name, req, True, arg2value)
        for (i, arg) in enumerate(args[num_args - num_defaults:]):
            while arg not in arg2value:
                arg2value[arg] = defaults[i]
    missing = 0
    for kwarg in kwonlyargs:
        while kwarg not in arg2value:
            if kwarg in kwonlydefaults:
                arg2value[kwarg] = kwonlydefaults[kwarg]
            else:
                missing += 1
    if missing:
        _missing_arguments(f_name, kwonlyargs, False, arg2value)
    return arg2value

ClosureVars = namedtuple('ClosureVars', 'nonlocals globals builtins unbound')

def getclosurevars(func):
    if ismethod(func):
        func = func.__func__
    if not isfunction(func):
        raise TypeError("'{!r}' is not a Python function".format(func))
    code = func.__code__
    if func.__closure__ is None:
        nonlocal_vars = {}
    else:
        nonlocal_vars = {var: cell.cell_contents for (var, cell) in zip(code.co_freevars, func.__closure__)}
    global_ns = func.__globals__
    builtin_ns = global_ns.get('__builtins__', builtins.__dict__)
    if ismodule(builtin_ns):
        builtin_ns = builtin_ns.__dict__
    global_vars = {}
    builtin_vars = {}
    unbound_names = set()
    for name in code.co_names:
        if name in ('None', 'True', 'False'):
            pass
        try:
            global_vars[name] = global_ns[name]
        except KeyError:
            try:
                builtin_vars[name] = builtin_ns[name]
            except KeyError:
                unbound_names.add(name)
    return ClosureVars(nonlocal_vars, global_vars, builtin_vars, unbound_names)

Traceback = namedtuple('Traceback', 'filename lineno function code_context index')

def getframeinfo(frame, context=1):
    if istraceback(frame):
        lineno = frame.tb_lineno
        frame = frame.tb_frame
    else:
        lineno = frame.f_lineno
    if not isframe(frame):
        raise TypeError('{!r} is not a frame or traceback object'.format(frame))
    filename = getsourcefile(frame) or getfile(frame)
    if context > 0:
        start = lineno - 1 - context//2
        try:
            (lines, lnum) = findsource(frame)
        except IOError:
            lines = index = None
        start = max(start, 1)
        start = max(0, min(start, len(lines) - context))
        lines = lines[start:start + context]
        index = lineno - 1 - start
    else:
        lines = index = None
    return Traceback(filename, lineno, frame.f_code.co_name, lines, index)

def getlineno(frame):
    return frame.f_lineno

def getouterframes(frame, context=1):
    framelist = []
    while frame:
        framelist.append((frame,) + getframeinfo(frame, context))
        frame = frame.f_back
    return framelist

def getinnerframes(tb, context=1):
    framelist = []
    while tb:
        framelist.append((tb.tb_frame,) + getframeinfo(tb, context))
        tb = tb.tb_next
    return framelist

def currentframe():
    if hasattr(sys, '_getframe'):
        return sys._getframe(1)

def stack(context=1):
    return getouterframes(sys._getframe(1), context)

def trace(context=1):
    return getinnerframes(sys.exc_info()[2], context)

_sentinel = object()

def _static_getmro(klass):
    return type.__dict__['__mro__'].__get__(klass)

def _check_instance(obj, attr):
    instance_dict = {}
    try:
        instance_dict = object.__getattribute__(obj, '__dict__')
    except AttributeError:
        pass
    return dict.get(instance_dict, attr, _sentinel)

def _check_class(klass, attr):
    for entry in _static_getmro(klass):
        while _shadowed_dict(type(entry)) is _sentinel:
            try:
                return entry.__dict__[attr]
            except KeyError:
                pass
    return _sentinel

def _is_type(obj):
    try:
        _static_getmro(obj)
    except TypeError:
        return False
    return True

def _shadowed_dict(klass):
    dict_attr = type.__dict__['__dict__']
    for entry in _static_getmro(klass):
        try:
            class_dict = dict_attr.__get__(entry)['__dict__']
        except KeyError:
            pass
        while not (type(class_dict) is types.GetSetDescriptorType and (class_dict.__name__ == '__dict__' and class_dict.__objclass__ is entry)):
            return class_dict
    return _sentinel

def getattr_static(obj, attr, default=_sentinel):
    instance_result = _sentinel
    if not _is_type(obj):
        klass = type(obj)
        dict_attr = _shadowed_dict(klass)
        instance_result = _check_instance(obj, attr)
    else:
        klass = obj
    klass_result = _check_class(klass, attr)
    if instance_result is not _sentinel and (klass_result is not _sentinel and _check_class(type(klass_result), '__get__') is not _sentinel) and _check_class(type(klass_result), '__set__') is not _sentinel:
        return klass_result
    if instance_result is not _sentinel:
        return instance_result
    if klass_result is not _sentinel:
        return klass_result
    if obj is klass:
        for entry in _static_getmro(type(klass)):
            while _shadowed_dict(type(entry)) is _sentinel:
                try:
                    return entry.__dict__[attr]
                except KeyError:
                    pass
    if default is not _sentinel:
        return default
    raise AttributeError(attr)

GEN_CREATED = 'GEN_CREATED'
GEN_RUNNING = 'GEN_RUNNING'
GEN_SUSPENDED = 'GEN_SUSPENDED'
GEN_CLOSED = 'GEN_CLOSED'

def getgeneratorstate(generator):
    if generator.gi_running:
        return GEN_RUNNING
    if generator.gi_frame is None:
        return GEN_CLOSED
    if generator.gi_frame.f_lasti == -1:
        return GEN_CREATED
    return GEN_SUSPENDED

def getgeneratorlocals(generator):
    if not isgenerator(generator):
        raise TypeError("'{!r}' is not a Python generator".format(generator))
    frame = getattr(generator, 'gi_frame', None)
    if frame is not None:
        return generator.gi_frame.f_locals
    return {}

_WrapperDescriptor = type(type.__call__)
_MethodWrapper = type(all.__call__)
_NonUserDefinedCallables = (_WrapperDescriptor, _MethodWrapper, types.BuiltinFunctionType)

def _get_user_defined_method(cls, method_name):
    try:
        meth = getattr(cls, method_name)
    except AttributeError:
        return
    if not isinstance(meth, _NonUserDefinedCallables):
        return meth

def signature(obj):
    if not callable(obj):
        raise TypeError('{!r} is not a callable object'.format(obj))
    if isinstance(obj, types.MethodType):
        sig = signature(obj.__func__)
        return sig.replace(parameters=tuple(sig.parameters.values())[1:])
    try:
        sig = obj.__signature__
    except AttributeError:
        pass
    if sig is not None:
        return sig
    try:
        wrapped = obj.__wrapped__
    except AttributeError:
        pass
    return signature(wrapped)
    if isinstance(obj, types.FunctionType):
        return Signature.from_function(obj)
    if isinstance(obj, functools.partial):
        sig = signature(obj.func)
        new_params = OrderedDict(sig.parameters.items())
        partial_args = obj.args or ()
        partial_keywords = obj.keywords or {}
        try:
            ba = sig.bind_partial(*partial_args, **partial_keywords)
        except TypeError as ex:
            msg = 'partial object {!r} has incorrect arguments'.format(obj)
            raise ValueError(msg) from ex
        for (arg_name, arg_value) in ba.arguments.items():
            param = new_params[arg_name]
            if arg_name in partial_keywords:
                new_params[arg_name] = param.replace(default=arg_value, _partial_kwarg=True)
            else:
                while param.kind not in (_VAR_KEYWORD, _VAR_POSITIONAL) and not param._partial_kwarg:
                    new_params.pop(arg_name)
        return sig.replace(parameters=new_params.values())
    sig = None
    if isinstance(obj, type):
        call = _get_user_defined_method(type(obj), '__call__')
        if call is not None:
            sig = signature(call)
        else:
            new = _get_user_defined_method(obj, '__new__')
            if new is not None:
                sig = signature(new)
            else:
                init = _get_user_defined_method(obj, '__init__')
                if init is not None:
                    sig = signature(init)
    elif not isinstance(obj, _NonUserDefinedCallables):
        call = _get_user_defined_method(type(obj), '__call__')
        if call is not None:
            sig = signature(call)
    if sig is not None:
        return sig.replace(parameters=tuple(sig.parameters.values())[1:])
    if isinstance(obj, types.BuiltinFunctionType):
        msg = 'no signature found for builtin function {!r}'.format(obj)
        raise ValueError(msg)
    raise ValueError('callable {!r} is not supported by signature'.format(obj))

class _void:
    __qualname__ = '_void'

class _empty:
    __qualname__ = '_empty'

class _ParameterKind(int):
    __qualname__ = '_ParameterKind'

    def __new__(self, *args, name):
        obj = int.__new__(self, *args)
        obj._name = name
        return obj

    def __str__(self):
        return self._name

    def __repr__(self):
        return '<_ParameterKind: {!r}>'.format(self._name)

_POSITIONAL_ONLY = _ParameterKind(0, name='POSITIONAL_ONLY')
_POSITIONAL_OR_KEYWORD = _ParameterKind(1, name='POSITIONAL_OR_KEYWORD')
_VAR_POSITIONAL = _ParameterKind(2, name='VAR_POSITIONAL')
_KEYWORD_ONLY = _ParameterKind(3, name='KEYWORD_ONLY')
_VAR_KEYWORD = _ParameterKind(4, name='VAR_KEYWORD')

class Parameter:
    __qualname__ = 'Parameter'
    __slots__ = ('_name', '_kind', '_default', '_annotation', '_partial_kwarg')
    POSITIONAL_ONLY = _POSITIONAL_ONLY
    POSITIONAL_OR_KEYWORD = _POSITIONAL_OR_KEYWORD
    VAR_POSITIONAL = _VAR_POSITIONAL
    KEYWORD_ONLY = _KEYWORD_ONLY
    VAR_KEYWORD = _VAR_KEYWORD
    empty = _empty

    def __init__(self, name, kind, *, default=_empty, annotation=_empty, _partial_kwarg=False):
        if kind not in (_POSITIONAL_ONLY, _POSITIONAL_OR_KEYWORD, _VAR_POSITIONAL, _KEYWORD_ONLY, _VAR_KEYWORD):
            raise ValueError("invalid value for 'Parameter.kind' attribute")
        self._kind = kind
        if default is not _empty and kind in (_VAR_POSITIONAL, _VAR_KEYWORD):
            msg = '{} parameters cannot have default values'.format(kind)
            raise ValueError(msg)
        self._default = default
        self._annotation = annotation
        if name is None:
            if kind != _POSITIONAL_ONLY:
                raise ValueError('None is not a valid name for a non-positional-only parameter')
            self._name = name
        else:
            name = str(name)
            if kind != _POSITIONAL_ONLY and not name.isidentifier():
                msg = '{!r} is not a valid parameter name'.format(name)
                raise ValueError(msg)
            self._name = name
        self._partial_kwarg = _partial_kwarg

    @property
    def name(self):
        return self._name

    @property
    def default(self):
        return self._default

    @property
    def annotation(self):
        return self._annotation

    @property
    def kind(self):
        return self._kind

    def replace(self, *, name=_void, kind=_void, annotation=_void, default=_void, _partial_kwarg=_void):
        if name is _void:
            name = self._name
        if kind is _void:
            kind = self._kind
        if annotation is _void:
            annotation = self._annotation
        if default is _void:
            default = self._default
        if _partial_kwarg is _void:
            _partial_kwarg = self._partial_kwarg
        return type(self)(name, kind, default=default, annotation=annotation, _partial_kwarg=_partial_kwarg)

    def __str__(self):
        kind = self.kind
        formatted = self._name
        if kind == _POSITIONAL_ONLY:
            if formatted is None:
                formatted = ''
            formatted = '<{}>'.format(formatted)
        if self._annotation is not _empty:
            formatted = '{}:{}'.format(formatted, formatannotation(self._annotation))
        if self._default is not _empty:
            formatted = '{}={}'.format(formatted, repr(self._default))
        if kind == _VAR_POSITIONAL:
            formatted = '*' + formatted
        elif kind == _VAR_KEYWORD:
            formatted = '**' + formatted
        return formatted

    def __repr__(self):
        return '<{} at {:#x} {!r}>'.format(self.__class__.__name__, id(self), self.name)

    def __eq__(self, other):
        return issubclass(other.__class__, Parameter) and (self._name == other._name and (self._kind == other._kind and (self._default == other._default and self._annotation == other._annotation)))

    def __ne__(self, other):
        return not self.__eq__(other)

class BoundArguments:
    __qualname__ = 'BoundArguments'

    def __init__(self, signature, arguments):
        self.arguments = arguments
        self._signature = signature

    @property
    def signature(self):
        return self._signature

    @property
    def args(self):
        args = []
        for (param_name, param) in self._signature.parameters.items():
            if param.kind in (_VAR_KEYWORD, _KEYWORD_ONLY) or param._partial_kwarg:
                break
            try:
                arg = self.arguments[param_name]
            except KeyError:
                break
            if param.kind == _VAR_POSITIONAL:
                args.extend(arg)
            else:
                args.append(arg)
        return tuple(args)

    @property
    def kwargs(self):
        kwargs = {}
        kwargs_started = False
        for (param_name, param) in self._signature.parameters.items():
            if not kwargs_started:
                if param.kind in (_VAR_KEYWORD, _KEYWORD_ONLY) or param._partial_kwarg:
                    kwargs_started = True
                elif param_name not in self.arguments:
                    kwargs_started = True
            if not kwargs_started:
                pass
            try:
                arg = self.arguments[param_name]
            except KeyError:
                pass
            if param.kind == _VAR_KEYWORD:
                kwargs.update(arg)
            else:
                kwargs[param_name] = arg
        return kwargs

    def __eq__(self, other):
        return issubclass(other.__class__, BoundArguments) and (self.signature == other.signature and self.arguments == other.arguments)

    def __ne__(self, other):
        return not self.__eq__(other)

class Signature:
    __qualname__ = 'Signature'
    __slots__ = ('_return_annotation', '_parameters')
    _parameter_cls = Parameter
    _bound_arguments_cls = BoundArguments
    empty = _empty

    def __init__(self, parameters=None, *, return_annotation=_empty, __validate_parameters__=True):
        if parameters is None:
            params = OrderedDict()
        elif __validate_parameters__:
            params = OrderedDict()
            top_kind = _POSITIONAL_ONLY
            for (idx, param) in enumerate(parameters):
                kind = param.kind
                if kind < top_kind:
                    msg = 'wrong parameter order: {} before {}'
                    msg = msg.format(top_kind, param.kind)
                    raise ValueError(msg)
                else:
                    top_kind = kind
                name = param.name
                if name is None:
                    name = str(idx)
                    param = param.replace(name=name)
                if name in params:
                    msg = 'duplicate parameter name: {!r}'.format(name)
                    raise ValueError(msg)
                params[name] = param
        else:
            params = OrderedDict((param.name, param) for param in parameters)
        self._parameters = types.MappingProxyType(params)
        self._return_annotation = return_annotation

    @classmethod
    def from_function(cls, func):
        if not isinstance(func, types.FunctionType):
            raise TypeError('{!r} is not a Python function'.format(func))
        Parameter = cls._parameter_cls
        func_code = func.__code__
        pos_count = func_code.co_argcount
        arg_names = func_code.co_varnames
        positional = tuple(arg_names[:pos_count])
        keyword_only_count = func_code.co_kwonlyargcount
        keyword_only = arg_names[pos_count:pos_count + keyword_only_count]
        annotations = func.__annotations__
        defaults = func.__defaults__
        kwdefaults = func.__kwdefaults__
        if defaults:
            pos_default_count = len(defaults)
        else:
            pos_default_count = 0
        parameters = []
        non_default_count = pos_count - pos_default_count
        for name in positional[:non_default_count]:
            annotation = annotations.get(name, _empty)
            parameters.append(Parameter(name, annotation=annotation, kind=_POSITIONAL_OR_KEYWORD))
        for (offset, name) in enumerate(positional[non_default_count:]):
            annotation = annotations.get(name, _empty)
            parameters.append(Parameter(name, annotation=annotation, kind=_POSITIONAL_OR_KEYWORD, default=defaults[offset]))
        if func_code.co_flags & 4:
            name = arg_names[pos_count + keyword_only_count]
            annotation = annotations.get(name, _empty)
            parameters.append(Parameter(name, annotation=annotation, kind=_VAR_POSITIONAL))
        for name in keyword_only:
            default = _empty
            if kwdefaults is not None:
                default = kwdefaults.get(name, _empty)
            annotation = annotations.get(name, _empty)
            parameters.append(Parameter(name, annotation=annotation, kind=_KEYWORD_ONLY, default=default))
        if func_code.co_flags & 8:
            index = pos_count + keyword_only_count
            if func_code.co_flags & 4:
                index += 1
            name = arg_names[index]
            annotation = annotations.get(name, _empty)
            parameters.append(Parameter(name, annotation=annotation, kind=_VAR_KEYWORD))
        return cls(parameters, return_annotation=annotations.get('return', _empty), __validate_parameters__=False)

    @property
    def parameters(self):
        return self._parameters

    @property
    def return_annotation(self):
        return self._return_annotation

    def replace(self, *, parameters=_void, return_annotation=_void):
        if parameters is _void:
            parameters = self.parameters.values()
        if return_annotation is _void:
            return_annotation = self._return_annotation
        return type(self)(parameters, return_annotation=return_annotation)

    def __eq__(self, other):
        if not issubclass(type(other), Signature) or self.return_annotation != other.return_annotation or len(self.parameters) != len(other.parameters):
            return False
        other_positions = {param: idx for (idx, param) in enumerate(other.parameters.keys())}
        for (idx, (param_name, param)) in enumerate(self.parameters.items()):
            if param.kind == _KEYWORD_ONLY:
                try:
                    other_param = other.parameters[param_name]
                except KeyError:
                    return False
                if param != other_param:
                    return False
                    try:
                        other_idx = other_positions[param_name]
                    except KeyError:
                        return False
                    while idx != other_idx or param != other.parameters[param_name]:
                        return False
            else:
                try:
                    other_idx = other_positions[param_name]
                except KeyError:
                    return False
                while idx != other_idx or param != other.parameters[param_name]:
                    return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def _bind(self, args, kwargs, *, partial=False):
        arguments = OrderedDict()
        parameters = iter(self.parameters.values())
        parameters_ex = ()
        arg_vals = iter(args)
        if partial:
            for (param_name, param) in self.parameters.items():
                while param._partial_kwarg and param_name not in kwargs:
                    kwargs[param_name] = param.default
        while True:
            try:
                arg_val = next(arg_vals)
            except StopIteration:
                try:
                    param = next(parameters)
                except StopIteration:
                    break
                if param.kind == _VAR_POSITIONAL:
                    break
                elif param.name in kwargs:
                    if param.kind == _POSITIONAL_ONLY:
                        msg = '{arg!r} parameter is positional only, but was passed as a keyword'
                        msg = msg.format(arg=param.name)
                        raise TypeError(msg) from None
                    parameters_ex = (param,)
                    break
                elif param.kind == _VAR_KEYWORD or param.default is not _empty:
                    parameters_ex = (param,)
                    break
                elif partial:
                    parameters_ex = (param,)
                    break
                else:
                    msg = '{arg!r} parameter lacking default value'
                    msg = msg.format(arg=param.name)
                    raise TypeError(msg) from None
            try:
                param = next(parameters)
            except StopIteration:
                raise TypeError('too many positional arguments') from None
            if param.kind in (_VAR_KEYWORD, _KEYWORD_ONLY):
                raise TypeError('too many positional arguments')
            if param.kind == _VAR_POSITIONAL:
                values = [arg_val]
                values.extend(arg_vals)
                arguments[param.name] = tuple(values)
                break
            if param.name in kwargs:
                raise TypeError('multiple values for argument {arg!r}'.format(arg=param.name))
            arguments[param.name] = arg_val
        kwargs_param = None
        for param in itertools.chain(parameters_ex, parameters):
            if param.kind == _POSITIONAL_ONLY:
                raise TypeError('{arg!r} parameter is positional only, but was passed as a keyword'.format(arg=param.name))
            if param.kind == _VAR_KEYWORD:
                kwargs_param = param
            param_name = param.name
            try:
                arg_val = kwargs.pop(param_name)
            except KeyError:
                if not partial and param.kind != _VAR_POSITIONAL and param.default is _empty:
                    raise TypeError('{arg!r} parameter lacking default value'.format(arg=param_name)) from None
            arguments[param_name] = arg_val
        if kwargs:
            if kwargs_param is not None:
                arguments[kwargs_param.name] = kwargs
            else:
                raise TypeError('too many keyword arguments')
        return self._bound_arguments_cls(self, arguments)

    def bind(_Signature__bind_self, *args, **kwargs):
        return _Signature__bind_self._bind(args, kwargs)

    def bind_partial(_Signature__bind_self, *args, **kwargs):
        return _Signature__bind_self._bind(args, kwargs, partial=True)

    def __str__(self):
        result = []
        render_kw_only_separator = True
        for (idx, param) in enumerate(self.parameters.values()):
            formatted = str(param)
            kind = param.kind
            if kind == _VAR_POSITIONAL:
                render_kw_only_separator = False
            elif kind == _KEYWORD_ONLY and render_kw_only_separator:
                result.append('*')
                render_kw_only_separator = False
            result.append(formatted)
        rendered = '({})'.format(', '.join(result))
        if self.return_annotation is not _empty:
            anno = formatannotation(self.return_annotation)
            rendered += ' -> {}'.format(anno)
        return rendered

