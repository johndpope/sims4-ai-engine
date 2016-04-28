__all__ = ['help']
__author__ = 'Ka-Ping Yee <ping@lfw.org>'
__date__ = '26 February 2001'
__credits__ = 'Guido van Rossum, for an excellent programming language.\nTommy Burnette, the original creator of manpy.\nPaul Prescod, for all his work on onlinehelp.\nRichard Chamberlain, for the first implementation of textdoc.\n'
import builtins
import imp
import importlib.machinery
import inspect
import io
import os
import pkgutil
import platform
import re
import sys
import time
import tokenize
import warnings
from collections import deque
from reprlib import Repr
from traceback import extract_tb, format_exception_only

def pathdirs():
    dirs = []
    normdirs = []
    for dir in sys.path:
        dir = os.path.abspath(dir or '.')
        normdir = os.path.normcase(dir)
        while normdir not in normdirs and os.path.isdir(dir):
            dirs.append(dir)
            normdirs.append(normdir)
    return dirs

def getdoc(object):
    result = inspect.getdoc(object) or inspect.getcomments(object)
    return result and re.sub('^ *\n', '', result.rstrip()) or ''

def splitdoc(doc):
    lines = doc.strip().split('\n')
    if len(lines) == 1:
        return (lines[0], '')
    if len(lines) >= 2 and not lines[1].rstrip():
        return (lines[0], '\n'.join(lines[2:]))
    return ('', '\n'.join(lines))

def classname(object, modname):
    name = object.__name__
    if object.__module__ != modname:
        name = object.__module__ + '.' + name
    return name

def isdata(object):
    return not (inspect.ismodule(object) or (inspect.isclass(object) or (inspect.isroutine(object) or (inspect.isframe(object) or (inspect.istraceback(object) or inspect.iscode(object))))))

def replace(text, *pairs):
    while pairs:
        text = pairs[1].join(text.split(pairs[0]))
        pairs = pairs[2:]
    return text

def cram(text, maxlen):
    if len(text) > maxlen:
        pre = max(0, (maxlen - 3)//2)
        post = max(0, maxlen - 3 - pre)
        return text[:pre] + '...' + text[len(text) - post:]
    return text

_re_stripid = re.compile(' at 0x[0-9a-f]{6,16}(>+)$', re.IGNORECASE)

def stripid(text):
    return _re_stripid.sub('\\1', text)

def _is_some_method(obj):
    return inspect.isfunction(obj) or (inspect.ismethod(obj) or (inspect.isbuiltin(obj) or inspect.ismethoddescriptor(obj)))

def allmethods(cl):
    methods = {}
    for (key, value) in inspect.getmembers(cl, _is_some_method):
        methods[key] = 1
    for base in cl.__bases__:
        methods.update(allmethods(base))
    for key in methods.keys():
        methods[key] = getattr(cl, key)
    return methods

def _split_list(s, predicate):
    yes = []
    no = []
    for x in s:
        if predicate(x):
            yes.append(x)
        else:
            no.append(x)
    return (yes, no)

def visiblename(name, all=None, obj=None):
    if name in frozenset({'__name__', '__path__', '__file__', '__credits__', '__doc__', '__date__', '__initializing__', '__slots__', '__module__', '__cached__', '__author__', '__version__', '__builtins__', '__qualname__', '__loader__', '__package__'}):
        return 0
    if name.startswith('__') and name.endswith('__'):
        return 1
    if name.startswith('_') and hasattr(obj, '_fields'):
        return True
    if all is not None:
        return name in all
    return not name.startswith('_')

def classify_class_attrs(object):
    results = []
    for (name, kind, cls, value) in inspect.classify_class_attrs(object):
        if inspect.isdatadescriptor(value):
            kind = 'data descriptor'
        results.append((name, kind, cls, value))
    return results

def ispackage(path):
    if os.path.isdir(path):
        for ext in ('.py', '.pyc', '.pyo'):
            while os.path.isfile(os.path.join(path, '__init__' + ext)):
                return True
    return False

def source_synopsis(file):
    line = file.readline()
    while not line[:1] == '#':
        while not line.strip():
            line = file.readline()
            while not line:
                break
                continue
    line = line.strip()
    if line[:4] == 'r"""':
        line = line[1:]
    if line[:3] == '"""':
        line = line[3:]
        if line[-1:] == '\\':
            line = line[:-1]
        while not line.strip():
            line = file.readline()
            while not line:
                break
                continue
        result = line.split('"""')[0].strip()
    else:
        result = None
    return result

def synopsis(filename, cache={}):
    mtime = os.stat(filename).st_mtime
    (lastupdate, result) = cache.get(filename, (None, None))
    if lastupdate is None or lastupdate < mtime:
        try:
            file = tokenize.open(filename)
        except IOError:
            return
        binary_suffixes = importlib.machinery.BYTECODE_SUFFIXES[:]
        binary_suffixes += importlib.machinery.EXTENSION_SUFFIXES[:]
        if any(filename.endswith(x) for x in binary_suffixes):
            file.close()
            if any(filename.endswith(x) for x in importlib.machinery.BYTECODE_SUFFIXES):
                loader = importlib.machinery.SourcelessFileLoader('__temp__', filename)
            else:
                loader = importlib.machinery.ExtensionFileLoader('__temp__', filename)
            try:
                module = loader.load_module('__temp__')
            except:
                return
            result = (module.__doc__ or '').splitlines()[0]
            del sys.modules['__temp__']
        else:
            result = source_synopsis(file)
            file.close()
        cache[filename] = (mtime, result)
    return result

class ErrorDuringImport(Exception):
    __qualname__ = 'ErrorDuringImport'

    def __init__(self, filename, exc_info):
        self.filename = filename
        (self.exc, self.value, self.tb) = exc_info

    def __str__(self):
        exc = self.exc.__name__
        return 'problem in %s - %s: %s' % (self.filename, exc, self.value)

def importfile(path):
    magic = imp.get_magic()
    with open(path, 'rb') as file:
        if file.read(len(magic)) == magic:
            kind = imp.PY_COMPILED
        else:
            kind = imp.PY_SOURCE
        file.seek(0)
        filename = os.path.basename(path)
        (name, ext) = os.path.splitext(filename)
        try:
            module = imp.load_module(name, file, path, (ext, 'r', kind))
        except:
            raise ErrorDuringImport(path, sys.exc_info())
    return module

def safeimport(path, forceload=0, cache={}):
    try:
        if forceload and path in sys.modules and path not in sys.builtin_module_names:
            subs = [m for m in sys.modules if m.startswith(path + '.')]
            while True:
                for key in [path] + subs:
                    cache[key] = sys.modules[key]
                    del sys.modules[key]
        module = __import__(path)
    except:
        (exc, value, tb) = info = sys.exc_info()
        if path in sys.modules:
            raise ErrorDuringImport(sys.modules[path].__file__, info)
        elif exc is SyntaxError:
            raise ErrorDuringImport(value.filename, info)
        else:
            if exc is ImportError and value.name == path:
                return
            raise ErrorDuringImport(path, sys.exc_info())
    for part in path.split('.')[1:]:
        try:
            module = getattr(module, part)
        except AttributeError:
            return
    return module

class Doc:
    __qualname__ = 'Doc'
    PYTHONDOCS = os.environ.get('PYTHONDOCS', 'http://docs.python.org/%d.%d/library' % sys.version_info[:2])

    def document(self, object, name=None, *args):
        args = (object, name) + args
        if inspect.isgetsetdescriptor(object):
            return self.docdata(*args)
        if inspect.ismemberdescriptor(object):
            return self.docdata(*args)
        try:
            if inspect.ismodule(object):
                return self.docmodule(*args)
            if inspect.isclass(object):
                return self.docclass(*args)
            if inspect.isroutine(object):
                return self.docroutine(*args)
        except AttributeError:
            pass
        if isinstance(object, property):
            return self.docproperty(*args)
        return self.docother(*args)

    def fail(self, object, name=None, *args):
        message = "don't know how to document object%s of type %s" % (name and ' ' + repr(name), type(object).__name__)
        raise TypeError(message)

    docmodule = docclass = docroutine = docother = docproperty = docdata = fail

    def getdocloc(self, object):
        try:
            file = inspect.getabsfile(object)
        except TypeError:
            file = '(built-in)'
        docloc = os.environ.get('PYTHONDOCS', self.PYTHONDOCS)
        basedir = os.path.join(sys.base_exec_prefix, 'lib', 'python%d.%d' % sys.version_info[:2])
        if isinstance(object, type(os)) and ((object.__name__ in ('errno', 'exceptions', 'gc', 'imp', 'marshal', 'posix', 'signal', 'sys', '_thread', 'zipimport') or file.startswith(basedir)) and not file.startswith(os.path.join(basedir, 'site-packages'))) and object.__name__ not in ('xml.etree', 'test.pydoc_mod'):
            if docloc.startswith('http://'):
                docloc = '%s/%s' % (docloc.rstrip('/'), object.__name__)
            else:
                docloc = os.path.join(docloc, object.__name__ + '.html')
        else:
            docloc = None
        return docloc

class HTMLRepr(Repr):
    __qualname__ = 'HTMLRepr'

    def __init__(self):
        Repr.__init__(self)
        self.maxlist = self.maxtuple = 20
        self.maxdict = 10
        self.maxstring = self.maxother = 100

    def escape(self, text):
        return replace(text, '&', '&amp;', '<', '&lt;', '>', '&gt;')

    def repr(self, object):
        return Repr.repr(self, object)

    def repr1(self, x, level):
        if hasattr(type(x), '__name__'):
            methodname = 'repr_' + '_'.join(type(x).__name__.split())
            if hasattr(self, methodname):
                return getattr(self, methodname)(x, level)
        return self.escape(cram(stripid(repr(x)), self.maxother))

    def repr_string(self, x, level):
        test = cram(x, self.maxstring)
        testrepr = repr(test)
        if '\\' in test and '\\' not in replace(testrepr, '\\\\', ''):
            return 'r' + testrepr[0] + self.escape(test) + testrepr[0]
        return re.sub('((\\\\[\\\\abfnrtv\\\'"]|\\\\[0-9]..|\\\\x..|\\\\u....)+)', '<font color="#c040c0">\\1</font>', self.escape(testrepr))

    repr_str = repr_string

    def repr_instance(self, x, level):
        try:
            return self.escape(cram(stripid(repr(x)), self.maxstring))
        except:
            return self.escape('<%s instance>' % x.__class__.__name__)

    repr_unicode = repr_string

class HTMLDoc(Doc):
    __qualname__ = 'HTMLDoc'
    _repr_instance = HTMLRepr()
    repr = _repr_instance.repr
    escape = _repr_instance.escape

    def page(self, title, contents):
        return '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">\n<html><head><title>Python: %s</title>\n<meta http-equiv="Content-Type" content="text/html; charset=utf-8">\n</head><body bgcolor="#f0f0f8">\n%s\n</body></html>' % (title, contents)

    def heading(self, title, fgcol, bgcol, extras=''):
        return '\n<table width="100%%" cellspacing=0 cellpadding=2 border=0 summary="heading">\n<tr bgcolor="%s">\n<td valign=bottom>&nbsp;<br>\n<font color="%s" face="helvetica, arial">&nbsp;<br>%s</font></td\n><td align=right valign=bottom\n><font color="%s" face="helvetica, arial">%s</font></td></tr></table>\n    ' % (bgcol, fgcol, title, fgcol, extras or '&nbsp;')

    def section(self, title, fgcol, bgcol, contents, width=6, prelude='', marginalia=None, gap='&nbsp;'):
        if marginalia is None:
            marginalia = '<tt>' + '&nbsp;'*width + '</tt>'
        result = '<p>\n<table width="100%%" cellspacing=0 cellpadding=2 border=0 summary="section">\n<tr bgcolor="%s">\n<td colspan=3 valign=bottom>&nbsp;<br>\n<font color="%s" face="helvetica, arial">%s</font></td></tr>\n    ' % (bgcol, fgcol, title)
        if prelude:
            result = result + '\n<tr bgcolor="%s"><td rowspan=2>%s</td>\n<td colspan=2>%s</td></tr>\n<tr><td>%s</td>' % (bgcol, marginalia, prelude, gap)
        else:
            result = result + '\n<tr><td bgcolor="%s">%s</td><td>%s</td>' % (bgcol, marginalia, gap)
        return result + '\n<td width="100%%">%s</td></tr></table>' % contents

    def bigsection(self, title, *args):
        title = '<big><strong>%s</strong></big>' % title
        return self.section(title, *args)

    def preformat(self, text):
        text = self.escape(text.expandtabs())
        return replace(text, '\n\n', '\n \n', '\n\n', '\n \n', ' ', '&nbsp;', '\n', '<br>\n')

    def multicolumn(self, list, format, cols=4):
        result = ''
        rows = (len(list) + cols - 1)//cols
        for col in range(cols):
            result = result + '<td width="%d%%" valign=top>' % (100//cols)
            for i in range(rows*col, rows*col + rows):
                while i < len(list):
                    result = result + format(list[i]) + '<br>\n'
            result = result + '</td>'
        return '<table width="100%%" summary="list"><tr>%s</tr></table>' % result

    def grey(self, text):
        return '<font color="#909090">%s</font>' % text

    def namelink(self, name, *dicts):
        for dict in dicts:
            while name in dict:
                return '<a href="%s">%s</a>' % (dict[name], name)
        return name

    def classlink(self, object, modname):
        (name, module) = (object.__name__, sys.modules.get(object.__module__))
        if hasattr(module, name) and getattr(module, name) is object:
            return '<a href="%s.html#%s">%s</a>' % (module.__name__, name, classname(object, modname))
        return classname(object, modname)

    def modulelink(self, object):
        return '<a href="%s.html">%s</a>' % (object.__name__, object.__name__)

    def modpkglink(self, modpkginfo):
        (name, path, ispackage, shadowed) = modpkginfo
        if shadowed:
            return self.grey(name)
        if path:
            url = '%s.%s.html' % (path, name)
        else:
            url = '%s.html' % name
        if ispackage:
            text = '<strong>%s</strong>&nbsp;(package)' % name
        else:
            text = name
        return '<a href="%s">%s</a>' % (url, text)

    def filelink(self, url, path):
        return '<a href="file:%s">%s</a>' % (url, path)

    def markup(self, text, escape=None, funcs={}, classes={}, methods={}):
        escape = escape or self.escape
        results = []
        here = 0
        pattern = re.compile('\\b((http|ftp)://\\S+[\\w/]|RFC[- ]?(\\d+)|PEP[- ]?(\\d+)|(self\\.)?(\\w+))')
        while True:
            match = pattern.search(text, here)
            if not match:
                break
            (start, end) = match.span()
            results.append(escape(text[here:start]))
            (all, scheme, rfc, pep, selfdot, name) = match.groups()
            if scheme:
                url = escape(all).replace('"', '&quot;')
                results.append('<a href="%s">%s</a>' % (url, url))
            elif rfc:
                url = 'http://www.rfc-editor.org/rfc/rfc%d.txt' % int(rfc)
                results.append('<a href="%s">%s</a>' % (url, escape(all)))
            elif pep:
                url = 'http://www.python.org/dev/peps/pep-%04d/' % int(pep)
                results.append('<a href="%s">%s</a>' % (url, escape(all)))
            elif text[end:end + 1] == '(':
                results.append(self.namelink(name, methods, funcs, classes))
            elif selfdot:
                results.append('self.<strong>%s</strong>' % name)
            else:
                results.append(self.namelink(name, classes))
            here = end
        results.append(escape(text[here:]))
        return ''.join(results)

    def formattree(self, tree, modname, parent=None):
        result = ''
        for entry in tree:
            if type(entry) is type(()):
                (c, bases) = entry
                result = result + '<dt><font face="helvetica, arial">'
                result = result + self.classlink(c, modname)
                if bases and bases != (parent,):
                    parents = []
                    for base in bases:
                        parents.append(self.classlink(base, modname))
                    result = result + '(' + ', '.join(parents) + ')'
                result = result + '\n</font></dt>'
            else:
                while type(entry) is type([]):
                    result = result + '<dd>\n%s</dd>\n' % self.formattree(entry, modname, c)
        return '<dl>\n%s</dl>\n' % result

    def docmodule(self, object, name=None, mod=None, *ignored):
        name = object.__name__
        try:
            all = object.__all__
        except AttributeError:
            all = None
        parts = name.split('.')
        links = []
        for i in range(len(parts) - 1):
            links.append('<a href="%s.html"><font color="#ffffff">%s</font></a>' % ('.'.join(parts[:i + 1]), parts[i]))
        linkedname = '.'.join(links + parts[-1:])
        head = '<big><big><strong>%s</strong></big></big>' % linkedname
        try:
            path = inspect.getabsfile(object)
            url = path
            if sys.platform == 'win32':
                import nturl2path
                url = nturl2path.pathname2url(path)
            filelink = self.filelink(url, path)
        except TypeError:
            filelink = '(built-in)'
        info = []
        if hasattr(object, '__version__'):
            version = str(object.__version__)
            if version[:11] == '$Revision: ' and version[-1:] == '$':
                version = version[11:-1].strip()
            info.append('version %s' % self.escape(version))
        if hasattr(object, '__date__'):
            info.append(self.escape(str(object.__date__)))
        if info:
            head = head + ' (%s)' % ', '.join(info)
        docloc = self.getdocloc(object)
        if docloc is not None:
            docloc = '<br><a href="%(docloc)s">Module Reference</a>' % locals()
        else:
            docloc = ''
        result = self.heading(head, '#ffffff', '#7799ee', '<a href=".">index</a><br>' + filelink + docloc)
        modules = inspect.getmembers(object, inspect.ismodule)
        (classes, cdict) = ([], {})
        for (key, value) in inspect.getmembers(object, inspect.isclass):
            while all is not None or inspect.getmodule(value) or object is object:
                if visiblename(key, all, object):
                    classes.append((key, value))
                    cdict[key] = cdict[value] = '#' + key
        for (key, value) in classes:
            for base in value.__bases__:
                (key, modname) = (base.__name__, base.__module__)
                module = sys.modules.get(modname)
                while modname != name and module and hasattr(module, key):
                    if getattr(module, key) is base:
                        if key not in cdict:
                            cdict[key] = cdict[base] = modname + '.html#' + key
        (funcs, fdict) = ([], {})
        for (key, value) in inspect.getmembers(object, inspect.isroutine):
            while all is not None or inspect.isbuiltin(value) or inspect.getmodule(value) is object:
                if visiblename(key, all, object):
                    funcs.append((key, value))
                    fdict[key] = '#-' + key
                    if inspect.isfunction(value):
                        fdict[value] = fdict[key]
        data = []
        for (key, value) in inspect.getmembers(object, isdata):
            while visiblename(key, all, object):
                data.append((key, value))
        doc = self.markup(getdoc(object), self.preformat, fdict, cdict)
        doc = doc and '<tt>%s</tt>' % doc
        result = result + '<p>%s</p>\n' % doc
        if hasattr(object, '__path__'):
            modpkgs = []
            for (importer, modname, ispkg) in pkgutil.iter_modules(object.__path__):
                modpkgs.append((modname, name, ispkg, 0))
            modpkgs.sort()
            contents = self.multicolumn(modpkgs, self.modpkglink)
            result = result + self.bigsection('Package Contents', '#ffffff', '#aa55cc', contents)
        elif modules:
            contents = self.multicolumn(modules, lambda t: self.modulelink(t[1]))
            result = result + self.bigsection('Modules', '#ffffff', '#aa55cc', contents)
        if classes:
            classlist = [value for (key, value) in classes]
            contents = [self.formattree(inspect.getclasstree(classlist, 1), name)]
            for (key, value) in classes:
                contents.append(self.document(value, key, name, fdict, cdict))
            result = result + self.bigsection('Classes', '#ffffff', '#ee77aa', ' '.join(contents))
        if funcs:
            contents = []
            for (key, value) in funcs:
                contents.append(self.document(value, key, name, fdict, cdict))
            result = result + self.bigsection('Functions', '#ffffff', '#eeaa77', ' '.join(contents))
        if data:
            contents = []
            for (key, value) in data:
                contents.append(self.document(value, key))
            result = result + self.bigsection('Data', '#ffffff', '#55aa55', '<br>\n'.join(contents))
        if hasattr(object, '__author__'):
            contents = self.markup(str(object.__author__), self.preformat)
            result = result + self.bigsection('Author', '#ffffff', '#7799ee', contents)
        if hasattr(object, '__credits__'):
            contents = self.markup(str(object.__credits__), self.preformat)
            result = result + self.bigsection('Credits', '#ffffff', '#7799ee', contents)
        return result

    def docclass(self, object, name=None, mod=None, funcs={}, classes={}, *ignored):
        realname = object.__name__
        name = name or realname
        bases = object.__bases__
        contents = []
        push = contents.append

        class HorizontalRule:
            __qualname__ = 'HTMLDoc.docclass.<locals>.HorizontalRule'

            def __init__(self):
                self.needone = 0

            def maybe(self):
                if self.needone:
                    push('<hr>\n')
                self.needone = 1

        hr = HorizontalRule()
        mro = deque(inspect.getmro(object))
        if len(mro) > 2:
            hr.maybe()
            push('<dl><dt>Method resolution order:</dt>\n')
            for base in mro:
                push('<dd>%s</dd>\n' % self.classlink(base, object.__module__))
            push('</dl>\n')

        def spill(msg, attrs, predicate):
            (ok, attrs) = _split_list(attrs, predicate)
            if ok:
                hr.maybe()
                push(msg)
                for (name, kind, homecls, value) in ok:
                    try:
                        value = getattr(object, name)
                    except Exception:
                        push(self._docdescriptor(name, value, mod))
                    push(self.document(value, name, mod, funcs, classes, mdict, object))
                    push('\n')
            return attrs

        def spilldescriptors(msg, attrs, predicate):
            (ok, attrs) = _split_list(attrs, predicate)
            if ok:
                hr.maybe()
                push(msg)
                for (name, kind, homecls, value) in ok:
                    push(self._docdescriptor(name, value, mod))
            return attrs

        def spilldata(msg, attrs, predicate):
            (ok, attrs) = _split_list(attrs, predicate)
            if ok:
                hr.maybe()
                push(msg)
                for (name, kind, homecls, value) in ok:
                    base = self.docother(getattr(object, name), name, mod)
                    if callable(value) or inspect.isdatadescriptor(value):
                        doc = getattr(value, '__doc__', None)
                    else:
                        doc = None
                    if doc is None:
                        push('<dl><dt>%s</dl>\n' % base)
                    else:
                        doc = self.markup(getdoc(value), self.preformat, funcs, classes, mdict)
                        doc = '<dd><tt>%s</tt>' % doc
                        push('<dl><dt>%s%s</dl>\n' % (base, doc))
                    push('\n')
            return attrs

        attrs = [(name, kind, cls, value) for (name, kind, cls, value) in classify_class_attrs(object) if visiblename(name, obj=object)]
        mdict = {}
        for (key, kind, homecls, value) in attrs:
            mdict[key] = anchor = '#' + name + '-' + key
            try:
                value = getattr(object, name)
            except Exception:
                pass
            try:
                mdict[value] = anchor
            except TypeError:
                pass
        while attrs:
            if mro:
                thisclass = mro.popleft()
            else:
                thisclass = attrs[0][2]
            (attrs, inherited) = _split_list(attrs, lambda t: t[2] is thisclass)
            if thisclass is builtins.object:
                attrs = inherited
                continue
            elif thisclass is object:
                tag = 'defined here'
            else:
                tag = 'inherited from %s' % self.classlink(thisclass, object.__module__)
            tag += ':<br>\n'
            attrs.sort(key=lambda t: t[0])
            attrs = spill('Methods %s' % tag, attrs, lambda t: t[1] == 'method')
            attrs = spill('Class methods %s' % tag, attrs, lambda t: t[1] == 'class method')
            attrs = spill('Static methods %s' % tag, attrs, lambda t: t[1] == 'static method')
            attrs = spilldescriptors('Data descriptors %s' % tag, attrs, lambda t: t[1] == 'data descriptor')
            attrs = spilldata('Data and other attributes %s' % tag, attrs, lambda t: t[1] == 'data')
            attrs = inherited
        contents = ''.join(contents)
        if name == realname:
            title = '<a name="%s">class <strong>%s</strong></a>' % (name, realname)
        else:
            title = '<strong>%s</strong> = <a name="%s">class %s</a>' % (name, name, realname)
        if bases:
            parents = []
            for base in bases:
                parents.append(self.classlink(base, object.__module__))
            title = title + '(%s)' % ', '.join(parents)
        doc = self.markup(getdoc(object), self.preformat, funcs, classes, mdict)
        doc = doc and '<tt>%s<br>&nbsp;</tt>' % doc
        return self.section(title, '#000000', '#ffc8d8', contents, 3, doc)

    def formatvalue(self, object):
        return self.grey('=' + self.repr(object))

    def docroutine(self, object, name=None, mod=None, funcs={}, classes={}, methods={}, cl=None):
        realname = object.__name__
        name = name or realname
        anchor = (cl and cl.__name__ or '') + '-' + name
        note = ''
        skipdocs = 0
        if inspect.ismethod(object):
            imclass = object.__self__.__class__
            if cl:
                note = ' from ' + self.classlink(imclass, mod)
            elif object.__self__ is not None:
                note = ' method of %s instance' % self.classlink(object.__self__.__class__, mod)
            else:
                note = ' unbound %s method' % self.classlink(imclass, mod)
            object = object.__func__
        if name == realname:
            title = '<a name="%s"><strong>%s</strong></a>' % (anchor, realname)
        else:
            if cl and realname in cl.__dict__ and cl.__dict__[realname] is object:
                reallink = '<a href="#%s">%s</a>' % (cl.__name__ + '-' + realname, realname)
                skipdocs = 1
            else:
                reallink = realname
            title = '<a name="%s"><strong>%s</strong></a> = %s' % (anchor, name, reallink)
        if inspect.isfunction(object):
            (args, varargs, kwonlyargs, kwdefaults, varkw, defaults, ann) = inspect.getfullargspec(object)
            argspec = inspect.formatargspec(args, varargs, kwonlyargs, kwdefaults, varkw, defaults, ann, formatvalue=self.formatvalue, formatannotation=inspect.formatannotationrelativeto(object))
            title = '<strong>%s</strong> <em>lambda</em> ' % name
            argspec = argspec[1:-1]
        else:
            argspec = '(...)'
        decl = title + argspec + (note and self.grey('<font face="helvetica, arial">%s</font>' % note))
        if skipdocs:
            return '<dl><dt>%s</dt></dl>\n' % decl
        doc = self.markup(getdoc(object), self.preformat, funcs, classes, methods)
        doc = doc and '<dd><tt>%s</tt></dd>' % doc
        return '<dl><dt>%s</dt>%s</dl>\n' % (decl, doc)

    def _docdescriptor(self, name, value, mod):
        results = []
        push = results.append
        if name:
            push('<dl><dt><strong>%s</strong></dt>\n' % name)
        if value.__doc__ is not None:
            doc = self.markup(getdoc(value), self.preformat)
            push('<dd><tt>%s</tt></dd>\n' % doc)
        push('</dl>\n')
        return ''.join(results)

    def docproperty(self, object, name=None, mod=None, cl=None):
        return self._docdescriptor(name, object, mod)

    def docother(self, object, name=None, mod=None, *ignored):
        lhs = name and '<strong>%s</strong> = ' % name or ''
        return lhs + self.repr(object)

    def docdata(self, object, name=None, mod=None, cl=None):
        return self._docdescriptor(name, object, mod)

    def index(self, dir, shadowed=None):
        modpkgs = []
        if shadowed is None:
            shadowed = {}
        for (importer, name, ispkg) in pkgutil.iter_modules([dir]):
            if any(55296 <= ord(ch) <= 57343 for ch in name):
                pass
            modpkgs.append((name, '', ispkg, name in shadowed))
            shadowed[name] = 1
        modpkgs.sort()
        contents = self.multicolumn(modpkgs, self.modpkglink)
        return self.bigsection(dir, '#ffffff', '#ee77aa', contents)

class TextRepr(Repr):
    __qualname__ = 'TextRepr'

    def __init__(self):
        Repr.__init__(self)
        self.maxlist = self.maxtuple = 20
        self.maxdict = 10
        self.maxstring = self.maxother = 100

    def repr1(self, x, level):
        if hasattr(type(x), '__name__'):
            methodname = 'repr_' + '_'.join(type(x).__name__.split())
            if hasattr(self, methodname):
                return getattr(self, methodname)(x, level)
        return cram(stripid(repr(x)), self.maxother)

    def repr_string(self, x, level):
        test = cram(x, self.maxstring)
        testrepr = repr(test)
        if '\\' in test and '\\' not in replace(testrepr, '\\\\', ''):
            return 'r' + testrepr[0] + test + testrepr[0]
        return testrepr

    repr_str = repr_string

    def repr_instance(self, x, level):
        try:
            return cram(stripid(repr(x)), self.maxstring)
        except:
            return '<%s instance>' % x.__class__.__name__

class TextDoc(Doc):
    __qualname__ = 'TextDoc'
    _repr_instance = TextRepr()
    repr = _repr_instance.repr

    def bold(self, text):
        return ''.join(ch + '\x08' + ch for ch in text)

    def indent(self, text, prefix='    '):
        if not text:
            return ''
        lines = [prefix + line for line in text.split('\n')]
        if lines:
            lines[-1] = lines[-1].rstrip()
        return '\n'.join(lines)

    def section(self, title, contents):
        clean_contents = self.indent(contents).rstrip()
        return self.bold(title) + '\n' + clean_contents + '\n\n'

    def formattree(self, tree, modname, parent=None, prefix=''):
        result = ''
        for entry in tree:
            if type(entry) is type(()):
                (c, bases) = entry
                result = result + prefix + classname(c, modname)
                if bases and bases != (parent,):
                    parents = (classname(c, modname) for c in bases)
                    result = result + '(%s)' % ', '.join(parents)
                result = result + '\n'
            else:
                while type(entry) is type([]):
                    result = result + self.formattree(entry, modname, c, prefix + '    ')
        return result

    def docmodule(self, object, name=None, mod=None):
        name = object.__name__
        (synop, desc) = splitdoc(getdoc(object))
        result = self.section('NAME', name + (synop and ' - ' + synop))
        all = getattr(object, '__all__', None)
        docloc = self.getdocloc(object)
        if docloc is not None:
            result = result + self.section('MODULE REFERENCE', docloc + '\n\nThe following documentation is automatically generated from the Python\nsource files.  It may be incomplete, incorrect or include features that\nare considered implementation detail and may vary between Python\nimplementations.  When in doubt, consult the module reference at the\nlocation listed above.\n')
        if desc:
            result = result + self.section('DESCRIPTION', desc)
        classes = []
        for (key, value) in inspect.getmembers(object, inspect.isclass):
            while all is not None or inspect.getmodule(value) or object is object:
                if visiblename(key, all, object):
                    classes.append((key, value))
        funcs = []
        for (key, value) in inspect.getmembers(object, inspect.isroutine):
            while all is not None or inspect.isbuiltin(value) or inspect.getmodule(value) is object:
                if visiblename(key, all, object):
                    funcs.append((key, value))
        data = []
        for (key, value) in inspect.getmembers(object, isdata):
            while visiblename(key, all, object):
                data.append((key, value))
        modpkgs = []
        modpkgs_names = set()
        if hasattr(object, '__path__'):
            for (importer, modname, ispkg) in pkgutil.iter_modules(object.__path__):
                modpkgs_names.add(modname)
                if ispkg:
                    modpkgs.append(modname + ' (package)')
                else:
                    modpkgs.append(modname)
            modpkgs.sort()
            result = result + self.section('PACKAGE CONTENTS', '\n'.join(modpkgs))
        submodules = []
        for (key, value) in inspect.getmembers(object, inspect.ismodule):
            while value.__name__.startswith(name + '.') and key not in modpkgs_names:
                submodules.append(key)
        if submodules:
            submodules.sort()
            result = result + self.section('SUBMODULES', '\n'.join(submodules))
        if classes:
            classlist = [value for (key, value) in classes]
            contents = [self.formattree(inspect.getclasstree(classlist, 1), name)]
            for (key, value) in classes:
                contents.append(self.document(value, key, name))
            result = result + self.section('CLASSES', '\n'.join(contents))
        if funcs:
            contents = []
            for (key, value) in funcs:
                contents.append(self.document(value, key, name))
            result = result + self.section('FUNCTIONS', '\n'.join(contents))
        if data:
            contents = []
            for (key, value) in data:
                contents.append(self.docother(value, key, name, maxlen=70))
            result = result + self.section('DATA', '\n'.join(contents))
        if hasattr(object, '__version__'):
            version = str(object.__version__)
            if version[:11] == '$Revision: ' and version[-1:] == '$':
                version = version[11:-1].strip()
            result = result + self.section('VERSION', version)
        if hasattr(object, '__date__'):
            result = result + self.section('DATE', str(object.__date__))
        if hasattr(object, '__author__'):
            result = result + self.section('AUTHOR', str(object.__author__))
        if hasattr(object, '__credits__'):
            result = result + self.section('CREDITS', str(object.__credits__))
        try:
            file = inspect.getabsfile(object)
        except TypeError:
            file = '(built-in)'
        result = result + self.section('FILE', file)
        return result

    def docclass(self, object, name=None, mod=None, *ignored):
        realname = object.__name__
        name = name or realname
        bases = object.__bases__

        def makename(c, m=object.__module__):
            return classname(c, m)

        if name == realname:
            title = 'class ' + self.bold(realname)
        else:
            title = self.bold(name) + ' = class ' + realname
        if bases:
            parents = map(makename, bases)
            title = title + '(%s)' % ', '.join(parents)
        doc = getdoc(object)
        contents = doc and [doc + '\n'] or []
        push = contents.append
        mro = deque(inspect.getmro(object))
        if len(mro) > 2:
            push('Method resolution order:')
            for base in mro:
                push('    ' + makename(base))
            push('')

        class HorizontalRule:
            __qualname__ = 'TextDoc.docclass.<locals>.HorizontalRule'

            def __init__(self):
                self.needone = 0

            def maybe(self):
                if self.needone:
                    push('-'*70)
                self.needone = 1

        hr = HorizontalRule()

        def spill(msg, attrs, predicate):
            (ok, attrs) = _split_list(attrs, predicate)
            if ok:
                hr.maybe()
                push(msg)
                for (name, kind, homecls, value) in ok:
                    try:
                        value = getattr(object, name)
                    except Exception:
                        push(self._docdescriptor(name, value, mod))
                    push(self.document(value, name, mod, object))
            return attrs

        def spilldescriptors(msg, attrs, predicate):
            (ok, attrs) = _split_list(attrs, predicate)
            if ok:
                hr.maybe()
                push(msg)
                for (name, kind, homecls, value) in ok:
                    push(self._docdescriptor(name, value, mod))
            return attrs

        def spilldata(msg, attrs, predicate):
            (ok, attrs) = _split_list(attrs, predicate)
            if ok:
                hr.maybe()
                push(msg)
                for (name, kind, homecls, value) in ok:
                    if callable(value) or inspect.isdatadescriptor(value):
                        doc = getdoc(value)
                    else:
                        doc = None
                    push(self.docother(getattr(object, name), name, mod, maxlen=70, doc=doc) + '\n')
            return attrs

        attrs = [(name, kind, cls, value) for (name, kind, cls, value) in classify_class_attrs(object) if visiblename(name, obj=object)]
        while attrs:
            if mro:
                thisclass = mro.popleft()
            else:
                thisclass = attrs[0][2]
            (attrs, inherited) = _split_list(attrs, lambda t: t[2] is thisclass)
            if thisclass is builtins.object:
                attrs = inherited
                continue
            elif thisclass is object:
                tag = 'defined here'
            else:
                tag = 'inherited from %s' % classname(thisclass, object.__module__)
            attrs.sort()
            attrs = spill('Methods %s:\n' % tag, attrs, lambda t: t[1] == 'method')
            attrs = spill('Class methods %s:\n' % tag, attrs, lambda t: t[1] == 'class method')
            attrs = spill('Static methods %s:\n' % tag, attrs, lambda t: t[1] == 'static method')
            attrs = spilldescriptors('Data descriptors %s:\n' % tag, attrs, lambda t: t[1] == 'data descriptor')
            attrs = spilldata('Data and other attributes %s:\n' % tag, attrs, lambda t: t[1] == 'data')
            attrs = inherited
        contents = '\n'.join(contents)
        if not contents:
            return title + '\n'
        return title + '\n' + self.indent(contents.rstrip(), ' |  ') + '\n'

    def formatvalue(self, object):
        return '=' + self.repr(object)

    def docroutine(self, object, name=None, mod=None, cl=None):
        realname = object.__name__
        name = name or realname
        note = ''
        skipdocs = 0
        if inspect.ismethod(object):
            imclass = object.__self__.__class__
            if cl:
                note = ' from ' + classname(imclass, mod)
            elif object.__self__ is not None:
                note = ' method of %s instance' % classname(object.__self__.__class__, mod)
            else:
                note = ' unbound %s method' % classname(imclass, mod)
            object = object.__func__
        if name == realname:
            title = self.bold(realname)
        else:
            if cl and realname in cl.__dict__ and cl.__dict__[realname] is object:
                skipdocs = 1
            title = self.bold(name) + ' = ' + realname
        if inspect.isfunction(object):
            (args, varargs, varkw, defaults, kwonlyargs, kwdefaults, ann) = inspect.getfullargspec(object)
            argspec = inspect.formatargspec(args, varargs, varkw, defaults, kwonlyargs, kwdefaults, ann, formatvalue=self.formatvalue, formatannotation=inspect.formatannotationrelativeto(object))
            title = self.bold(name) + ' lambda '
            argspec = argspec[1:-1]
        else:
            argspec = '(...)'
        decl = title + argspec + note
        if skipdocs:
            return decl + '\n'
        doc = getdoc(object) or ''
        return decl + '\n' + (doc and self.indent(doc).rstrip() + '\n')

    def _docdescriptor(self, name, value, mod):
        results = []
        push = results.append
        if name:
            push(self.bold(name))
            push('\n')
        doc = getdoc(value) or ''
        if doc:
            push(self.indent(doc))
            push('\n')
        return ''.join(results)

    def docproperty(self, object, name=None, mod=None, cl=None):
        return self._docdescriptor(name, object, mod)

    def docdata(self, object, name=None, mod=None, cl=None):
        return self._docdescriptor(name, object, mod)

    def docother(self, object, name=None, mod=None, parent=None, maxlen=None, doc=None):
        repr = self.repr(object)
        if maxlen:
            line = (name and name + ' = ' or '') + repr
            chop = maxlen - len(line)
            if chop < 0:
                repr = repr[:chop] + '...'
        line = (name and self.bold(name) + ' = ' or '') + repr
        if doc is not None:
            line += '\n' + self.indent(str(doc))
        return line

class _PlainTextDoc(TextDoc):
    __qualname__ = '_PlainTextDoc'

    def bold(self, text):
        return text

def pager(text):
    global pager
    pager = getpager()
    pager(text)

def getpager():
    if not hasattr(sys.stdout, 'isatty'):
        return plainpager
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return plainpager
    if 'PAGER' in os.environ:
        if sys.platform == 'win32':
            return lambda text: tempfilepager(plain(text), os.environ['PAGER'])
        if os.environ.get('TERM') in ('dumb', 'emacs'):
            return lambda text: pipepager(plain(text), os.environ['PAGER'])
        return lambda text: pipepager(text, os.environ['PAGER'])
    if os.environ.get('TERM') in ('dumb', 'emacs'):
        return plainpager
    if sys.platform == 'win32' or sys.platform.startswith('os2'):
        return lambda text: tempfilepager(plain(text), 'more <')
    if hasattr(os, 'system') and os.system('(less) 2>/dev/null') == 0:
        return lambda text: pipepager(text, 'less')
    import tempfile
    (fd, filename) = tempfile.mkstemp()
    os.close(fd)
    try:
        if hasattr(os, 'system') and os.system('more "%s"' % filename) == 0:
            return lambda text: pipepager(text, 'more')
        return ttypager
    finally:
        os.unlink(filename)

def plain(text):
    return re.sub('.\x08', '', text)

def pipepager(text, cmd):
    pipe = os.popen(cmd, 'w')
    try:
        pipe.write(text)
        pipe.close()
    except IOError:
        pass

def tempfilepager(text, cmd):
    import tempfile
    filename = tempfile.mktemp()
    file = open(filename, 'w')
    file.write(text)
    file.close()
    try:
        os.system(cmd + ' "' + filename + '"')
    finally:
        os.unlink(filename)

def ttypager(text):
    lines = plain(text).split('\n')
    try:
        import tty
        fd = sys.stdin.fileno()
        old = tty.tcgetattr(fd)
        tty.setcbreak(fd)
        getchar = lambda : sys.stdin.read(1)
    except (ImportError, AttributeError):
        tty = None
        getchar = lambda : sys.stdin.readline()[:-1][:1]
    try:
        r = inc = os.environ.get('LINES', 25) - 1
        sys.stdout.write('\n'.join(lines[:inc]) + '\n')
        while lines[r:]:
            sys.stdout.write('-- more --')
            sys.stdout.flush()
            c = getchar()
            if c in ('q', 'Q'):
                sys.stdout.write('\r          \r')
                break
            elif c in ('\r', '\n'):
                sys.stdout.write('\r          \r' + lines[r] + '\n')
                r = r + 1
                continue
            if c in ('b', 'B', '\x1b'):
                r = r - inc - inc
                if r < 0:
                    r = 0
            sys.stdout.write('\n' + '\n'.join(lines[r:r + inc]) + '\n')
            r = r + inc
    finally:
        if tty:
            tty.tcsetattr(fd, tty.TCSAFLUSH, old)

def plainpager(text):
    sys.stdout.write(plain(text))

def describe(thing):
    if inspect.ismodule(thing):
        if thing.__name__ in sys.builtin_module_names:
            return 'built-in module ' + thing.__name__
        if hasattr(thing, '__path__'):
            return 'package ' + thing.__name__
        return 'module ' + thing.__name__
    if inspect.isbuiltin(thing):
        return 'built-in function ' + thing.__name__
    if inspect.isgetsetdescriptor(thing):
        return 'getset descriptor %s.%s.%s' % (thing.__objclass__.__module__, thing.__objclass__.__name__, thing.__name__)
    if inspect.ismemberdescriptor(thing):
        return 'member descriptor %s.%s.%s' % (thing.__objclass__.__module__, thing.__objclass__.__name__, thing.__name__)
    if inspect.isclass(thing):
        return 'class ' + thing.__name__
    if inspect.isfunction(thing):
        return 'function ' + thing.__name__
    if inspect.ismethod(thing):
        return 'method ' + thing.__name__
    return type(thing).__name__

def locate(path, forceload=0):
    parts = [part for part in path.split('.') if part]
    (module, n) = (None, 0)
    while n < len(parts):
        nextmodule = safeimport('.'.join(parts[:n + 1]), forceload)
        if nextmodule:
            (module, n) = (nextmodule, n + 1)
        else:
            break
    if module:
        object = module
    else:
        object = builtins
    for part in parts[n:]:
        try:
            object = getattr(object, part)
        except AttributeError:
            return
    return object

text = TextDoc()
plaintext = _PlainTextDoc()
html = HTMLDoc()

def resolve(thing, forceload=0):
    if isinstance(thing, str):
        object = locate(thing, forceload)
        if not object:
            raise ImportError('no Python documentation found for %r' % thing)
        return (object, thing)
    name = getattr(thing, '__name__', None)
    return (thing, name if isinstance(name, str) else None)

def render_doc(thing, title='Python Library Documentation: %s', forceload=0, renderer=None):
    if renderer is None:
        renderer = text
    (object, name) = resolve(thing, forceload)
    desc = describe(object)
    module = inspect.getmodule(object)
    if name and '.' in name:
        desc += ' in ' + name[:name.rfind('.')]
    elif module and module is not object:
        desc += ' in module ' + module.__name__
    if not (inspect.ismodule(object) or (inspect.isclass(object) or (inspect.isroutine(object) or (inspect.isgetsetdescriptor(object) or (inspect.ismemberdescriptor(object) or isinstance(object, property)))))):
        object = type(object)
        desc += ' object'
    return title % desc + '\n\n' + renderer.document(object, name)

def doc(thing, title='Python Library Documentation: %s', forceload=0, output=None):
    try:
        if output is None:
            pager(render_doc(thing, title, forceload))
        else:
            output.write(render_doc(thing, title, forceload, plaintext))
    except (ImportError, ErrorDuringImport) as value:
        print(value)

def writedoc(thing, forceload=0):
    try:
        (object, name) = resolve(thing, forceload)
        page = html.page(describe(object), html.document(object, name))
        file = open(name + '.html', 'w', encoding='utf-8')
        file.write(page)
        file.close()
        print('wrote', name + '.html')
    except (ImportError, ErrorDuringImport) as value:
        print(value)

def writedocs(dir, pkgpath='', done=None):
    if done is None:
        done = {}
    for (importer, modname, ispkg) in pkgutil.walk_packages([dir], pkgpath):
        writedoc(modname)

class Helper:
    __qualname__ = 'Helper'
    keywords = {'False': '', 'None': '', 'True': '', 'and': 'BOOLEAN', 'as': 'with', 'assert': ('assert', ''), 'break': ('break', 'while for'), 'class': ('class', 'CLASSES SPECIALMETHODS'), 'continue': ('continue', 'while for'), 'def': ('function', ''), 'del': ('del', 'BASICMETHODS'), 'elif': 'if', 'else': ('else', 'while for'), 'except': 'try', 'finally': 'try', 'for': ('for', 'break continue while'), 'from': 'import', 'global': ('global', 'nonlocal NAMESPACES'), 'if': ('if', 'TRUTHVALUE'), 'import': ('import', 'MODULES'), 'in': ('in', 'SEQUENCEMETHODS'), 'is': 'COMPARISON', 'lambda': ('lambda', 'FUNCTIONS'), 'nonlocal': ('nonlocal', 'global NAMESPACES'), 'not': 'BOOLEAN', 'or': 'BOOLEAN', 'pass': ('pass', ''), 'raise': ('raise', 'EXCEPTIONS'), 'return': ('return', 'FUNCTIONS'), 'try': ('try', 'EXCEPTIONS'), 'while': ('while', 'break continue if TRUTHVALUE'), 'with': ('with', 'CONTEXTMANAGERS EXCEPTIONS yield'), 'yield': ('yield', '')}
    _symbols_inverse = {'STRINGS': ("'", "'''", "r'", "b'", '"""', '"', 'r"', 'b"'), 'OPERATORS': ('+', '-', '*', '**', '/', '//', '%', '<<', '>>', '&', '|', '^', '~', '<', '>', '<=', '>=', '==', '!=', '<>'), 'COMPARISON': ('<', '>', '<=', '>=', '==', '!=', '<>'), 'UNARY': ('-', '~'), 'AUGMENTEDASSIGNMENT': ('+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '<<=', '>>=', '**=', '//='), 'BITWISE': ('<<', '>>', '&', '|', '^', '~'), 'COMPLEX': ('j', 'J')}
    symbols = {'%': 'OPERATORS FORMATTING', '**': 'POWER', ',': 'TUPLES LISTS FUNCTIONS', '.': 'ATTRIBUTES FLOAT MODULES OBJECTS', '...': 'ELLIPSIS', ':': 'SLICINGS DICTIONARYLITERALS', '@': 'def class', '\\': 'STRINGS', '_': 'PRIVATENAMES', '__': 'PRIVATENAMES SPECIALMETHODS', '`': 'BACKQUOTES', '(': 'TUPLES FUNCTIONS CALLS', ')': 'TUPLES FUNCTIONS CALLS', '[': 'LISTS SUBSCRIPTS SLICINGS', ']': 'LISTS SUBSCRIPTS SLICINGS'}
    for (topic, symbols_) in _symbols_inverse.items():
        for symbol in symbols_:
            topics = symbols.get(symbol, topic)
            if topic not in topics:
                topics = topics + ' ' + topic
            symbols[symbol] = topics
    topics = {'TYPES': ('types', 'STRINGS UNICODE NUMBERS SEQUENCES MAPPINGS FUNCTIONS CLASSES MODULES FILES inspect'), 'STRINGS': ('strings', 'str UNICODE SEQUENCES STRINGMETHODS FORMATTING TYPES'), 'STRINGMETHODS': ('string-methods', 'STRINGS FORMATTING'), 'FORMATTING': ('formatstrings', 'OPERATORS'), 'UNICODE': ('strings', 'encodings unicode SEQUENCES STRINGMETHODS FORMATTING TYPES'), 'NUMBERS': ('numbers', 'INTEGER FLOAT COMPLEX TYPES'), 'INTEGER': ('integers', 'int range'), 'FLOAT': ('floating', 'float math'), 'COMPLEX': ('imaginary', 'complex cmath'), 'SEQUENCES': ('typesseq', 'STRINGMETHODS FORMATTING range LISTS'), 'MAPPINGS': 'DICTIONARIES', 'FUNCTIONS': ('typesfunctions', 'def TYPES'), 'METHODS': ('typesmethods', 'class def CLASSES TYPES'), 'CODEOBJECTS': ('bltin-code-objects', 'compile FUNCTIONS TYPES'), 'TYPEOBJECTS': ('bltin-type-objects', 'types TYPES'), 'FRAMEOBJECTS': 'TYPES', 'TRACEBACKS': 'TYPES', 'NONE': ('bltin-null-object', ''), 'ELLIPSIS': ('bltin-ellipsis-object', 'SLICINGS'), 'FILES': ('bltin-file-objects', ''), 'SPECIALATTRIBUTES': ('specialattrs', ''), 'CLASSES': ('types', 'class SPECIALMETHODS PRIVATENAMES'), 'MODULES': ('typesmodules', 'import'), 'PACKAGES': 'import', 'EXPRESSIONS': ('operator-summary', 'lambda or and not in is BOOLEAN COMPARISON BITWISE SHIFTING BINARY FORMATTING POWER UNARY ATTRIBUTES SUBSCRIPTS SLICINGS CALLS TUPLES LISTS DICTIONARIES'), 'OPERATORS': 'EXPRESSIONS', 'PRECEDENCE': 'EXPRESSIONS', 'OBJECTS': ('objects', 'TYPES'), 'SPECIALMETHODS': ('specialnames', 'BASICMETHODS ATTRIBUTEMETHODS CALLABLEMETHODS SEQUENCEMETHODS MAPPINGMETHODS NUMBERMETHODS CLASSES'), 'BASICMETHODS': ('customization', 'hash repr str SPECIALMETHODS'), 'ATTRIBUTEMETHODS': ('attribute-access', 'ATTRIBUTES SPECIALMETHODS'), 'CALLABLEMETHODS': ('callable-types', 'CALLS SPECIALMETHODS'), 'SEQUENCEMETHODS': ('sequence-types', 'SEQUENCES SEQUENCEMETHODS SPECIALMETHODS'), 'MAPPINGMETHODS': ('sequence-types', 'MAPPINGS SPECIALMETHODS'), 'NUMBERMETHODS': ('numeric-types', 'NUMBERS AUGMENTEDASSIGNMENT SPECIALMETHODS'), 'EXECUTION': ('execmodel', 'NAMESPACES DYNAMICFEATURES EXCEPTIONS'), 'NAMESPACES': ('naming', 'global nonlocal ASSIGNMENT DELETION DYNAMICFEATURES'), 'DYNAMICFEATURES': ('dynamic-features', ''), 'SCOPING': 'NAMESPACES', 'FRAMES': 'NAMESPACES', 'EXCEPTIONS': ('exceptions', 'try except finally raise'), 'CONVERSIONS': ('conversions', ''), 'IDENTIFIERS': ('identifiers', 'keywords SPECIALIDENTIFIERS'), 'SPECIALIDENTIFIERS': ('id-classes', ''), 'PRIVATENAMES': ('atom-identifiers', ''), 'LITERALS': ('atom-literals', 'STRINGS NUMBERS TUPLELITERALS LISTLITERALS DICTIONARYLITERALS'), 'TUPLES': 'SEQUENCES', 'TUPLELITERALS': ('exprlists', 'TUPLES LITERALS'), 'LISTS': ('typesseq-mutable', 'LISTLITERALS'), 'LISTLITERALS': ('lists', 'LISTS LITERALS'), 'DICTIONARIES': ('typesmapping', 'DICTIONARYLITERALS'), 'DICTIONARYLITERALS': ('dict', 'DICTIONARIES LITERALS'), 'ATTRIBUTES': ('attribute-references', 'getattr hasattr setattr ATTRIBUTEMETHODS'), 'SUBSCRIPTS': ('subscriptions', 'SEQUENCEMETHODS'), 'SLICINGS': ('slicings', 'SEQUENCEMETHODS'), 'CALLS': ('calls', 'EXPRESSIONS'), 'POWER': ('power', 'EXPRESSIONS'), 'UNARY': ('unary', 'EXPRESSIONS'), 'BINARY': ('binary', 'EXPRESSIONS'), 'SHIFTING': ('shifting', 'EXPRESSIONS'), 'BITWISE': ('bitwise', 'EXPRESSIONS'), 'COMPARISON': ('comparisons', 'EXPRESSIONS BASICMETHODS'), 'BOOLEAN': ('booleans', 'EXPRESSIONS TRUTHVALUE'), 'ASSERTION': 'assert', 'ASSIGNMENT': ('assignment', 'AUGMENTEDASSIGNMENT'), 'AUGMENTEDASSIGNMENT': ('augassign', 'NUMBERMETHODS'), 'DELETION': 'del', 'RETURNING': 'return', 'IMPORTING': 'import', 'CONDITIONAL': 'if', 'LOOPING': ('compound', 'for while break continue'), 'TRUTHVALUE': ('truth', 'if while and or not BASICMETHODS'), 'DEBUGGING': ('debugger', 'pdb'), 'CONTEXTMANAGERS': ('context-managers', 'with')}

    def __init__(self, input=None, output=None):
        self._input = input
        self._output = output

    input = property(lambda self: self._input or sys.stdin)
    output = property(lambda self: self._output or sys.stdout)

    def __repr__(self):
        if inspect.stack()[1][3] == '?':
            self()
            return ''
        return '<pydoc.Helper instance>'

    _GoInteractive = object()

    def __call__(self, request=_GoInteractive):
        if request is not self._GoInteractive:
            self.help(request)
        else:
            self.intro()
            self.interact()
            self.output.write('\nYou are now leaving help and returning to the Python interpreter.\nIf you want to ask for help on a particular object directly from the\ninterpreter, you can type "help(object)".  Executing "help(\'string\')"\nhas the same effect as typing a particular string at the help> prompt.\n')

    def interact(self):
        self.output.write('\n')
        while True:
            try:
                request = self.getline('help> ')
                while not request:
                    break
            except (KeyboardInterrupt, EOFError):
                break
            request = replace(request, '"', '', "'", '').strip()
            if request.lower() in ('q', 'quit'):
                break
            self.help(request)

    def getline(self, prompt):
        if self.input is sys.stdin:
            return input(prompt)
        self.output.write(prompt)
        self.output.flush()
        return self.input.readline()

    def help(self, request):
        if type(request) is type(''):
            request = request.strip()
            if request == 'help':
                self.intro()
            elif request == 'keywords':
                self.listkeywords()
            elif request == 'symbols':
                self.listsymbols()
            elif request == 'topics':
                self.listtopics()
            elif request == 'modules':
                self.listmodules()
            elif request[:8] == 'modules ':
                self.listmodules(request.split()[1])
            elif request in self.symbols:
                self.showsymbol(request)
            elif request in ('True', 'False', 'None'):
                doc(eval(request), 'Help on %s:')
            elif request in self.keywords:
                self.showtopic(request)
            elif request in self.topics:
                self.showtopic(request)
            else:
                doc(request, 'Help on %s:', output=self._output)
        elif isinstance(request, Helper):
            self()
        else:
            doc(request, 'Help on %s:', output=self._output)
        self.output.write('\n')

    def intro(self):
        self.output.write('\nWelcome to Python %s!  This is the interactive help utility.\n\nIf this is your first time using Python, you should definitely check out\nthe tutorial on the Internet at http://docs.python.org/%s/tutorial/.\n\nEnter the name of any module, keyword, or topic to get help on writing\nPython programs and using Python modules.  To quit this help utility and\nreturn to the interpreter, just type "quit".\n\nTo get a list of available modules, keywords, or topics, type "modules",\n"keywords", or "topics".  Each module also comes with a one-line summary\nof what it does; to list the modules whose summaries contain a given word\nsuch as "spam", type "modules spam".\n' % tuple([sys.version[:3]]*2))

    def list(self, items, columns=4, width=80):
        items = list(sorted(items))
        colw = width//columns
        rows = (len(items) + columns - 1)//columns
        for row in range(rows):
            for col in range(columns):
                i = col*rows + row
                while i < len(items):
                    self.output.write(items[i])
                    if col < columns - 1:
                        self.output.write(' ' + ' '*(colw - 1 - len(items[i])))
            self.output.write('\n')

    def listkeywords(self):
        self.output.write('\nHere is a list of the Python keywords.  Enter any keyword to get more help.\n\n')
        self.list(self.keywords.keys())

    def listsymbols(self):
        self.output.write('\nHere is a list of the punctuation symbols which Python assigns special meaning\nto. Enter any symbol to get more help.\n\n')
        self.list(self.symbols.keys())

    def listtopics(self):
        self.output.write('\nHere is a list of available topics.  Enter any topic name to get more help.\n\n')
        self.list(self.topics.keys())

    def showtopic(self, topic, more_xrefs=''):
        try:
            import pydoc_data.topics
        except ImportError:
            self.output.write('\nSorry, topic and keyword documentation is not available because the\nmodule "pydoc_data.topics" could not be found.\n')
            return
        target = self.topics.get(topic, self.keywords.get(topic))
        if not target:
            self.output.write('no documentation found for %s\n' % repr(topic))
            return
        if type(target) is type(''):
            return self.showtopic(target, more_xrefs)
        (label, xrefs) = target
        try:
            doc = pydoc_data.topics.topics[label]
        except KeyError:
            self.output.write('no documentation found for %s\n' % repr(topic))
            return
        pager(doc.strip() + '\n')
        if more_xrefs:
            xrefs = (xrefs or '') + ' ' + more_xrefs
        if xrefs:
            import formatter
            buffer = io.StringIO()
            formatter.DumbWriter(buffer).send_flowing_data('Related help topics: ' + ', '.join(xrefs.split()) + '\n')
            self.output.write('\n%s\n' % buffer.getvalue())

    def _gettopic(self, topic, more_xrefs=''):
        try:
            import pydoc_data.topics
        except ImportError:
            return ('\nSorry, topic and keyword documentation is not available because the\nmodule "pydoc_data.topics" could not be found.\n', '')
        target = self.topics.get(topic, self.keywords.get(topic))
        if not target:
            raise ValueError('could not find topic')
        if isinstance(target, str):
            return self._gettopic(target, more_xrefs)
        (label, xrefs) = target
        doc = pydoc_data.topics.topics[label]
        if more_xrefs:
            xrefs = (xrefs or '') + ' ' + more_xrefs
        return (doc, xrefs)

    def showsymbol(self, symbol):
        target = self.symbols[symbol]
        (topic, _, xrefs) = target.partition(' ')
        self.showtopic(topic, xrefs)

    def listmodules(self, key=''):
        if key:
            self.output.write('\nHere is a list of matching modules.  Enter any module name to get more help.\n\n')
            apropos(key)
        else:
            self.output.write('\nPlease wait a moment while I gather a list of all available modules...\n\n')
            modules = {}

            def callback(path, modname, desc, modules=modules):
                if modname and modname[-9:] == '.__init__':
                    modname = modname[:-9] + ' (package)'
                if modname.find('.') < 0:
                    modules[modname] = 1

            def onerror(modname):
                callback(None, modname, None)

            ModuleScanner().run(callback, onerror=onerror)
            self.list(modules.keys())
            self.output.write('\nEnter any module name to get more help.  Or, type "modules spam" to search\nfor modules whose descriptions contain the word "spam".\n')

help = Helper()

class Scanner:
    __qualname__ = 'Scanner'

    def __init__(self, roots, children, descendp):
        self.roots = roots[:]
        self.state = []
        self.children = children
        self.descendp = descendp

    def next(self):
        if not self.state:
            if not self.roots:
                return
            root = self.roots.pop(0)
            self.state = [(root, self.children(root))]
        (node, children) = self.state[-1]
        if not children:
            self.state.pop()
            return self.next()
        child = children.pop(0)
        if self.descendp(child):
            self.state.append((child, self.children(child)))
        return child

class ModuleScanner:
    __qualname__ = 'ModuleScanner'

    def run(self, callback, key=None, completer=None, onerror=None):
        if key:
            key = key.lower()
        self.quit = False
        seen = {}
        for modname in sys.builtin_module_names:
            while modname != '__main__':
                seen[modname] = 1
                if key is None:
                    callback(None, modname, '')
                else:
                    name = __import__(modname).__doc__ or ''
                    desc = name.split('\n')[0]
                    name = modname + ' - ' + desc
                    if name.lower().find(key) >= 0:
                        callback(None, modname, desc)
        for (importer, modname, ispkg) in pkgutil.walk_packages(onerror=onerror):
            if self.quit:
                break
            if key is None:
                callback(None, modname, '')
            else:
                try:
                    loader = importer.find_module(modname)
                except SyntaxError:
                    continue
                if hasattr(loader, 'get_source'):
                    try:
                        source = loader.get_source(modname)
                    except Exception:
                        if onerror:
                            onerror(modname)
                        continue
                    desc = source_synopsis(io.StringIO(source)) or ''
                    if hasattr(loader, 'get_filename'):
                        path = loader.get_filename(modname)
                    else:
                        path = None
                else:
                    try:
                        module = loader.load_module(modname)
                    except ImportError:
                        if onerror:
                            onerror(modname)
                        continue
                    desc = (module.__doc__ or '').splitlines()[0]
                    path = getattr(module, '__file__', None)
                name = modname + ' - ' + desc
                while name.lower().find(key) >= 0:
                    callback(path, modname, desc)
        if completer:
            completer()

def apropos(key):

    def callback(path, modname, desc):
        if modname[-9:] == '.__init__':
            modname = modname[:-9] + ' (package)'
        print(modname, desc and '- ' + desc)

    def onerror(modname):
        pass

    with warnings.catch_warnings():
        warnings.filterwarnings('ignore')
        ModuleScanner().run(callback, key, onerror=onerror)

def _start_server(urlhandler, port):
    import http.server
    import email.message
    import select
    import threading

    class DocHandler(http.server.BaseHTTPRequestHandler):
        __qualname__ = '_start_server.<locals>.DocHandler'

        def do_GET(self):
            if self.path.endswith('.css'):
                content_type = 'text/css'
            else:
                content_type = 'text/html'
            self.send_response(200)
            self.send_header('Content-Type', '%s; charset=UTF-8' % content_type)
            self.end_headers()
            self.wfile.write(self.urlhandler(self.path, content_type).encode('utf-8'))

        def log_message(self, *args):
            pass

    class DocServer(http.server.HTTPServer):
        __qualname__ = '_start_server.<locals>.DocServer'

        def __init__(self, port, callback):
            self.host = sys.platform == 'mac' and '127.0.0.1' or 'localhost'
            self.address = ('', port)
            self.callback = callback
            self.base.__init__(self, self.address, self.handler)
            self.quit = False

        def serve_until_quit(self):
            while not self.quit:
                (rd, wr, ex) = select.select([self.socket.fileno()], [], [], 1)
                while rd:
                    self.handle_request()
                    continue
            self.server_close()

        def server_activate(self):
            self.base.server_activate(self)
            if self.callback:
                self.callback(self)

    class ServerThread(threading.Thread):
        __qualname__ = '_start_server.<locals>.ServerThread'

        def __init__(self, urlhandler, port):
            self.urlhandler = urlhandler
            self.port = int(port)
            threading.Thread.__init__(self)
            self.serving = False
            self.error = None

        def run(self):
            try:
                DocServer.base = http.server.HTTPServer
                DocServer.handler = DocHandler
                DocHandler.MessageClass = email.message.Message
                DocHandler.urlhandler = staticmethod(self.urlhandler)
                docsvr = DocServer(self.port, self.ready)
                self.docserver = docsvr
                docsvr.serve_until_quit()
            except Exception as e:
                self.error = e

        def ready(self, server):
            self.serving = True
            self.host = server.host
            self.port = server.server_port
            self.url = 'http://%s:%d/' % (self.host, self.port)

        def stop(self):
            self.docserver.quit = True
            self.serving = False
            self.url = None

    thread = ServerThread(urlhandler, port)
    thread.start()
    while not thread.error:
        while not thread.serving:
            time.sleep(0.01)
    return thread

def _url_handler(url, content_type='text/html'):

    class _HTMLDoc(HTMLDoc):
        __qualname__ = '_url_handler.<locals>._HTMLDoc'

        def page(self, title, contents):
            css_path = 'pydoc_data/_pydoc.css'
            css_link = '<link rel="stylesheet" type="text/css" href="%s">' % css_path
            return '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">\n<html><head><title>Pydoc: %s</title>\n<meta http-equiv="Content-Type" content="text/html; charset=utf-8">\n%s</head><body bgcolor="#f0f0f8">%s<div style="clear:both;padding-top:.5em;">%s</div>\n</body></html>' % (title, css_link, html_navbar(), contents)

        def filelink(self, url, path):
            return '<a href="getfile?key=%s">%s</a>' % (url, path)

    html = _HTMLDoc()

    def html_navbar():
        version = html.escape('%s [%s, %s]' % (platform.python_version(), platform.python_build()[0], platform.python_compiler()))
        return '\n            <div style=\'float:left\'>\n                Python %s<br>%s\n            </div>\n            <div style=\'float:right\'>\n                <div style=\'text-align:center\'>\n                  <a href="index.html">Module Index</a>\n                  : <a href="topics.html">Topics</a>\n                  : <a href="keywords.html">Keywords</a>\n                </div>\n                <div>\n                    <form action="get" style=\'display:inline;\'>\n                      <input type=text name=key size=15>\n                      <input type=submit value="Get">\n                    </form>&nbsp;\n                    <form action="search" style=\'display:inline;\'>\n                      <input type=text name=key size=15>\n                      <input type=submit value="Search">\n                    </form>\n                </div>\n            </div>\n            ' % (version, html.escape(platform.platform(terse=True)))

    def html_index():

        def bltinlink(name):
            return '<a href="%s.html">%s</a>' % (name, name)

        heading = html.heading('<big><big><strong>Index of Modules</strong></big></big>', '#ffffff', '#7799ee')
        names = [name for name in sys.builtin_module_names if name != '__main__']
        contents = html.multicolumn(names, bltinlink)
        contents = [heading, '<p>' + html.bigsection('Built-in Modules', '#ffffff', '#ee77aa', contents)]
        seen = {}
        for dir in sys.path:
            contents.append(html.index(dir, seen))
        contents.append('<p align=right><font color="#909090" face="helvetica,arial"><strong>pydoc</strong> by Ka-Ping Yee&lt;ping@lfw.org&gt;</font>')
        return ('Index of Modules', ''.join(contents))

    def html_search(key):
        search_result = []

        def callback(path, modname, desc):
            if modname[-9:] == '.__init__':
                modname = modname[:-9] + ' (package)'
            search_result.append((modname, desc and '- ' + desc))

        with warnings.catch_warnings():
            warnings.filterwarnings('ignore')
            ModuleScanner().run(callback, key)

        def bltinlink(name):
            return '<a href="%s.html">%s</a>' % (name, name)

        results = []
        heading = html.heading('<big><big><strong>Search Results</strong></big></big>', '#ffffff', '#7799ee')
        for (name, desc) in search_result:
            results.append(bltinlink(name) + desc)
        contents = heading + html.bigsection('key = %s' % key, '#ffffff', '#ee77aa', '<br>'.join(results))
        return ('Search Results', contents)

    def html_getfile(path):
        path = path.replace('%20', ' ')
        with tokenize.open(path) as fp:
            lines = html.escape(fp.read())
        body = '<pre>%s</pre>' % lines
        heading = html.heading('<big><big><strong>File Listing</strong></big></big>', '#ffffff', '#7799ee')
        contents = heading + html.bigsection('File: %s' % path, '#ffffff', '#ee77aa', body)
        return ('getfile %s' % path, contents)

    def html_topics():

        def bltinlink(name):
            return '<a href="topic?key=%s">%s</a>' % (name, name)

        heading = html.heading('<big><big><strong>INDEX</strong></big></big>', '#ffffff', '#7799ee')
        names = sorted(Helper.topics.keys())
        contents = html.multicolumn(names, bltinlink)
        contents = heading + html.bigsection('Topics', '#ffffff', '#ee77aa', contents)
        return ('Topics', contents)

    def html_keywords():
        heading = html.heading('<big><big><strong>INDEX</strong></big></big>', '#ffffff', '#7799ee')
        names = sorted(Helper.keywords.keys())

        def bltinlink(name):
            return '<a href="topic?key=%s">%s</a>' % (name, name)

        contents = html.multicolumn(names, bltinlink)
        contents = heading + html.bigsection('Keywords', '#ffffff', '#ee77aa', contents)
        return ('Keywords', contents)

    def html_topicpage(topic):
        buf = io.StringIO()
        htmlhelp = Helper(buf, buf)
        (contents, xrefs) = htmlhelp._gettopic(topic)
        if topic in htmlhelp.keywords:
            title = 'KEYWORD'
        else:
            title = 'TOPIC'
        heading = html.heading('<big><big><strong>%s</strong></big></big>' % title, '#ffffff', '#7799ee')
        contents = '<pre>%s</pre>' % html.markup(contents)
        contents = html.bigsection(topic, '#ffffff', '#ee77aa', contents)
        if xrefs:
            xrefs = sorted(xrefs.split())

            def bltinlink(name):
                return '<a href="topic?key=%s">%s</a>' % (name, name)

            xrefs = html.multicolumn(xrefs, bltinlink)
            xrefs = html.section('Related help topics: ', '#ffffff', '#ee77aa', xrefs)
        return ('%s %s' % (title, topic), ''.join((heading, contents, xrefs)))

    def html_getobj(url):
        obj = locate(url, forceload=1)
        if obj is None and url != 'None':
            raise ValueError('could not find object')
        title = describe(obj)
        content = html.document(obj, url)
        return (title, content)

    def html_error(url, exc):
        heading = html.heading('<big><big><strong>Error</strong></big></big>', '#ffffff', '#7799ee')
        contents = '<br>'.join(html.escape(line) for line in format_exception_only(type(exc), exc))
        contents = heading + html.bigsection(url, '#ffffff', '#bb0000', contents)
        return ('Error - %s' % url, contents)

    def get_html_page(url):
        complete_url = url
        if url.endswith('.html'):
            url = url[:-5]
        try:
            if url in ('', 'index'):
                (title, content) = html_index()
            elif url == 'topics':
                (title, content) = html_topics()
            elif url == 'keywords':
                (title, content) = html_keywords()
            elif '=' in url:
                (op, _, url) = url.partition('=')
                if op == 'search?key':
                    (title, content) = html_search(url)
                elif op == 'getfile?key':
                    (title, content) = html_getfile(url)
                elif op == 'topic?key':
                    try:
                        (title, content) = html_topicpage(url)
                    except ValueError:
                        (title, content) = html_getobj(url)
                elif op == 'get?key':
                    if url in ('', 'index'):
                        (title, content) = html_index()
                    else:
                        try:
                            (title, content) = html_getobj(url)
                        except ValueError:
                            (title, content) = html_topicpage(url)
                        raise ValueError('bad pydoc url')
                else:
                    raise ValueError('bad pydoc url')
            else:
                (title, content) = html_getobj(url)
        except Exception as exc:
            (title, content) = html_error(complete_url, exc)
        return html.page(title, content)

    if url.startswith('/'):
        url = url[1:]
    if content_type == 'text/css':
        path_here = os.path.dirname(os.path.realpath(__file__))
        css_path = os.path.join(path_here, url)
        with open(css_path) as fp:
            return ''.join(fp.readlines())
    elif content_type == 'text/html':
        return get_html_page(url)
    raise TypeError('unknown content type %r for url %s' % (content_type, url))

def browse(port=0, *, open_browser=True):
    import webbrowser
    serverthread = _start_server(_url_handler, port)
    if serverthread.error:
        print(serverthread.error)
        return
    if serverthread.serving:
        server_help_msg = 'Server commands: [b]rowser, [q]uit'
        if open_browser:
            webbrowser.open(serverthread.url)
        try:
            print('Server ready at', serverthread.url)
            print(server_help_msg)
            while serverthread.serving:
                cmd = input('server> ')
                cmd = cmd.lower()
                if cmd == 'q':
                    break
                elif cmd == 'b':
                    webbrowser.open(serverthread.url)
                else:
                    print(server_help_msg)
        except (KeyboardInterrupt, EOFError):
            print()
        finally:
            if serverthread.serving:
                serverthread.stop()
                print('Server stopped')

def ispath(x):
    return isinstance(x, str) and x.find(os.sep) >= 0

def cli():
    import getopt

    class BadUsage(Exception):
        __qualname__ = 'cli.<locals>.BadUsage'

    if '' not in sys.path:
        scriptdir = os.path.dirname(sys.argv[0])
        if scriptdir in sys.path:
            sys.path.remove(scriptdir)
        sys.path.insert(0, '.')
    try:
        (opts, args) = getopt.getopt(sys.argv[1:], 'bk:p:w')
        writing = False
        start_server = False
        open_browser = False
        port = None
        for (opt, val) in opts:
            if opt == '-b':
                start_server = True
                open_browser = True
            if opt == '-k':
                apropos(val)
                return
            if opt == '-p':
                start_server = True
                port = val
            while opt == '-w':
                writing = True
        if start_server:
            if port is None:
                port = 0
            browse(port, open_browser=open_browser)
            return
        if not args:
            raise BadUsage
        for arg in args:
            if ispath(arg) and not os.path.exists(arg):
                print('file %r does not exist' % arg)
                break
            try:
                if ispath(arg) and os.path.isfile(arg):
                    arg = importfile(arg)
                if writing:
                    if ispath(arg) and os.path.isdir(arg):
                        writedocs(arg)
                    else:
                        writedoc(arg)
                else:
                    help.help(arg)
            except ErrorDuringImport as value:
                print(value)
    except (getopt.error, BadUsage):
        cmd = os.path.splitext(os.path.basename(sys.argv[0]))[0]
        print("pydoc - the Python documentation tool\n\n{cmd} <name> ...\n    Show text documentation on something.  <name> may be the name of a\n    Python keyword, topic, function, module, or package, or a dotted\n    reference to a class or function within a module or module in a\n    package.  If <name> contains a '{sep}', it is used as the path to a\n    Python source file to document. If name is 'keywords', 'topics',\n    or 'modules', a listing of these things is displayed.\n\n{cmd} -k <keyword>\n    Search for a keyword in the synopsis lines of all available modules.\n\n{cmd} -p <port>\n    Start an HTTP server on the given port on the local machine.  Port\n    number 0 can be used to get an arbitrary unused port.\n\n{cmd} -b\n    Start an HTTP server on an arbitrary unused port and open a Web browser\n    to interactively browse documentation.  The -p option can be used with\n    the -b option to explicitly specify the server port.\n\n{cmd} -w <name> ...\n    Write out the HTML documentation for a module to a file in the current\n    directory.  If <name> contains a '{sep}', it is treated as a filename; if\n    it names a directory, documentation is written for all the contents.\n".format(cmd=cmd, sep=os.sep))

if __name__ == '__main__':
    cli()
