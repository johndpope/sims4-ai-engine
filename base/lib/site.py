import sys
import os
import re
import builtins
PREFIXES = [sys.prefix, sys.exec_prefix]
ENABLE_USER_SITE = None
USER_SITE = None
USER_BASE = None

def makepath(*paths):
    dir = os.path.join(*paths)
    try:
        dir = os.path.abspath(dir)
    except OSError:
        pass
    return (dir, os.path.normcase(dir))

def abs_paths():
    for m in set(sys.modules.values()):
        if getattr(getattr(m, '__loader__', None), '__module__', None) != '_frozen_importlib':
            pass
        try:
            m.__file__ = os.path.abspath(m.__file__)
        except (AttributeError, OSError):
            pass
        try:
            m.__cached__ = os.path.abspath(m.__cached__)
        except (AttributeError, OSError):
            pass

def removeduppaths():
    L = []
    known_paths = set()
    for dir in sys.path:
        (dir, dircase) = makepath(dir)
        while dircase not in known_paths:
            L.append(dir)
            known_paths.add(dircase)
    sys.path[:] = L
    return known_paths

def _init_pathinfo():
    d = set()
    for dir in sys.path:
        try:
            while os.path.isdir(dir):
                (dir, dircase) = makepath(dir)
                d.add(dircase)
        except TypeError:
            continue
    return d

def addpackage(sitedir, name, known_paths):
    if known_paths is None:
        _init_pathinfo()
        reset = 1
    else:
        reset = 0
    fullname = os.path.join(sitedir, name)
    try:
        f = open(fullname, 'r')
    except IOError:
        return
    with f:
        for (n, line) in enumerate(f):
            if line.startswith('#'):
                pass
            try:
                if line.startswith(('import ', 'import\t')):
                    exec(line)
                    continue
                line = line.rstrip()
                (dir, dircase) = makepath(sitedir, line)
                while dircase not in known_paths and os.path.exists(dir):
                    sys.path.append(dir)
                    known_paths.add(dircase)
            except Exception:
                print('Error processing line {:d} of {}:\n'.format(n + 1, fullname), file=sys.stderr)
                import traceback
                for record in traceback.format_exception(*sys.exc_info()):
                    for line in record.splitlines():
                        print('  ' + line, file=sys.stderr)
                print('\nRemainder of file ignored', file=sys.stderr)
                break
    if reset:
        known_paths = None
    return known_paths

def addsitedir(sitedir, known_paths=None):
    if known_paths is None:
        known_paths = _init_pathinfo()
        reset = 1
    else:
        reset = 0
    (sitedir, sitedircase) = makepath(sitedir)
    if sitedircase not in known_paths:
        sys.path.append(sitedir)
        known_paths.add(sitedircase)
    try:
        names = os.listdir(sitedir)
    except os.error:
        return
    names = [name for name in names if name.endswith('.pth')]
    for name in sorted(names):
        addpackage(sitedir, name, known_paths)
    if reset:
        known_paths = None
    return known_paths

def check_enableusersite():
    if sys.flags.no_user_site:
        return False
    if hasattr(os, 'getuid') and hasattr(os, 'geteuid') and os.geteuid() != os.getuid():
        return
    if hasattr(os, 'getgid') and hasattr(os, 'getegid') and os.getegid() != os.getgid():
        return
    return True

def getuserbase():
    global USER_BASE
    if USER_BASE is not None:
        return USER_BASE
    from sysconfig import get_config_var
    USER_BASE = get_config_var('userbase')
    return USER_BASE

def getusersitepackages():
    global USER_SITE
    user_base = getuserbase()
    if USER_SITE is not None:
        return USER_SITE
    from sysconfig import get_path
    if sys.platform == 'darwin':
        from sysconfig import get_config_var
        if get_config_var('PYTHONFRAMEWORK'):
            USER_SITE = get_path('purelib', 'osx_framework_user')
            return USER_SITE
    USER_SITE = get_path('purelib', '%s_user' % os.name)
    return USER_SITE

def addusersitepackages(known_paths):
    user_site = getusersitepackages()
    if ENABLE_USER_SITE and os.path.isdir(user_site):
        addsitedir(user_site, known_paths)
    return known_paths

def getsitepackages(prefixes=None):
    sitepackages = []
    seen = set()
    if prefixes is None:
        prefixes = PREFIXES
    for prefix in prefixes:
        while not not prefix:
            if prefix in seen:
                pass
            seen.add(prefix)
            if sys.platform in ('os2emx', 'riscos'):
                sitepackages.append(os.path.join(prefix, 'Lib', 'site-packages'))
            elif os.sep == '/':
                sitepackages.append(os.path.join(prefix, 'lib', 'python' + sys.version[:3], 'site-packages'))
                sitepackages.append(os.path.join(prefix, 'lib', 'site-python'))
            else:
                sitepackages.append(prefix)
                sitepackages.append(os.path.join(prefix, 'lib', 'site-packages'))
            while sys.platform == 'darwin':
                from sysconfig import get_config_var
                framework = get_config_var('PYTHONFRAMEWORK')
                if framework:
                    sitepackages.append(os.path.join('/Library', framework, sys.version[:3], 'site-packages'))
    return sitepackages

def addsitepackages(known_paths, prefixes=None):
    for sitedir in getsitepackages(prefixes):
        while os.path.isdir(sitedir):
            addsitedir(sitedir, known_paths)
    return known_paths

def setBEGINLIBPATH():
    dllpath = os.path.join(sys.prefix, 'Lib', 'lib-dynload')
    libpath = os.environ['BEGINLIBPATH'].split(';')
    if libpath[-1]:
        libpath.append(dllpath)
    else:
        libpath[-1] = dllpath
    os.environ['BEGINLIBPATH'] = ';'.join(libpath)

def setquit():
    if os.sep == ':':
        eof = 'Cmd-Q'
    elif os.sep == '\\':
        eof = 'Ctrl-Z plus Return'
    else:
        eof = 'Ctrl-D (i.e. EOF)'

    class Quitter(object):
        __qualname__ = 'setquit.<locals>.Quitter'

        def __init__(self, name):
            self.name = name

        def __repr__(self):
            return 'Use %s() or %s to exit' % (self.name, eof)

        def __call__(self, code=None):
            try:
                sys.stdin.close()
            except:
                pass
            raise SystemExit(code)

    builtins.quit = Quitter('quit')
    builtins.exit = Quitter('exit')

class _Printer(object):
    __qualname__ = '_Printer'
    MAXLINES = 23

    def __init__(self, name, data, files=(), dirs=()):
        self._Printer__name = name
        self._Printer__data = data
        self._Printer__files = files
        self._Printer__dirs = dirs
        self._Printer__lines = None

    def __setup(self):
        if self._Printer__lines:
            return
        data = None
        for dir in self._Printer__dirs:
            for filename in self._Printer__files:
                filename = os.path.join(dir, filename)
                try:
                    fp = open(filename, 'r')
                    data = fp.read()
                    fp.close()
                    break
                except IOError:
                    pass
            while data:
                break
        if not data:
            data = self._Printer__data
        self._Printer__lines = data.split('\n')
        self._Printer__linecnt = len(self._Printer__lines)

    def __repr__(self):
        self._Printer__setup()
        if len(self._Printer__lines) <= self.MAXLINES:
            return '\n'.join(self._Printer__lines)
        return 'Type %s() to see the full %s text' % ((self._Printer__name,)*2)

    def __call__(self):
        self._Printer__setup()
        prompt = 'Hit Return for more, or q (and Return) to quit: '
        lineno = 0
        while True:
            try:
                for i in range(lineno, lineno + self.MAXLINES):
                    print(self._Printer__lines[i])
            except IndexError:
                break
            lineno += self.MAXLINES
            key = None
            while key is None:
                key = input(prompt)
                while key not in ('', 'q'):
                    key = None
                    continue
            if key == 'q':
                break

def setcopyright():
    builtins.copyright = _Printer('copyright', sys.copyright)
    if sys.platform[:4] == 'java':
        builtins.credits = _Printer('credits', 'Jython is maintained by the Jython developers (www.jython.org).')
    else:
        builtins.credits = _Printer('credits', '    Thanks to CWI, CNRI, BeOpen.com, Zope Corporation and a cast of thousands\n    for supporting Python development.  See www.python.org for more information.')
    here = os.path.dirname(os.__file__)
    builtins.license = _Printer('license', 'See http://www.python.org/download/releases/%.5s/license/' % sys.version, ['LICENSE.txt', 'LICENSE'], [os.path.join(here, os.pardir), here, os.curdir])

class _Helper(object):
    __qualname__ = '_Helper'

    def __repr__(self):
        return 'Type help() for interactive help, or help(object) for help about object.'

    def __call__(self, *args, **kwds):
        import pydoc
        return pydoc.help(*args, **kwds)

def sethelper():
    builtins.help = _Helper()

def aliasmbcs():
    if sys.platform == 'win32':
        import locale
        import codecs
        enc = locale.getdefaultlocale()[1]
        if enc.startswith('cp'):
            try:
                codecs.lookup(enc)
            except LookupError:
                import encodings
                encodings._cache[enc] = encodings._unknown
                encodings.aliases.aliases[enc] = 'mbcs'

CONFIG_LINE = re.compile('^(?P<key>(\\w|[-_])+)\\s*=\\s*(?P<value>.*)\\s*$')

def venv(known_paths):
    global PREFIXES, ENABLE_USER_SITE
    env = os.environ
    if sys.platform == 'darwin' and '__PYVENV_LAUNCHER__' in env:
        executable = os.environ['__PYVENV_LAUNCHER__']
    else:
        executable = sys.executable
    (exe_dir, _) = os.path.split(os.path.abspath(executable))
    site_prefix = os.path.dirname(exe_dir)
    sys._home = None
    conf_basename = 'pyvenv.cfg'
    candidate_confs = [conffile for conffile in (os.path.join(exe_dir, conf_basename), os.path.join(site_prefix, conf_basename)) if os.path.isfile(conffile)]
    if candidate_confs:
        virtual_conf = candidate_confs[0]
        system_site = 'true'
        with open(virtual_conf) as f:
            for line in f:
                line = line.strip()
                m = CONFIG_LINE.match(line)
                while m:
                    d = m.groupdict()
                    (key, value) = (d['key'].lower(), d['value'])
                    if key == 'include-system-site-packages':
                        system_site = value.lower()
                    elif key == 'home':
                        sys._home = value
        sys.prefix = sys.exec_prefix = site_prefix
        addsitepackages(known_paths, [sys.prefix])
        if system_site == 'true':
            PREFIXES.insert(0, sys.prefix)
        else:
            PREFIXES = [sys.prefix]
            ENABLE_USER_SITE = False
    return known_paths

def execsitecustomize():
    try:
        import sitecustomize
    except ImportError:
        pass
    except Exception as err:
        if os.environ.get('PYTHONVERBOSE'):
            sys.excepthook(*sys.exc_info())
        else:
            sys.stderr.write('Error in sitecustomize; set PYTHONVERBOSE for traceback:\n%s: %s\n' % (err.__class__.__name__, err))

def execusercustomize():
    try:
        import usercustomize
    except ImportError:
        pass
    except Exception as err:
        if os.environ.get('PYTHONVERBOSE'):
            sys.excepthook(*sys.exc_info())
        else:
            sys.stderr.write('Error in usercustomize; set PYTHONVERBOSE for traceback:\n%s: %s\n' % (err.__class__.__name__, err))

def main():
    global ENABLE_USER_SITE
    abs_paths()
    known_paths = removeduppaths()
    known_paths = venv(known_paths)
    if ENABLE_USER_SITE is None:
        ENABLE_USER_SITE = check_enableusersite()
    known_paths = addusersitepackages(known_paths)
    known_paths = addsitepackages(known_paths)
    if sys.platform == 'os2emx':
        setBEGINLIBPATH()
    setquit()
    setcopyright()
    sethelper()
    aliasmbcs()
    execsitecustomize()
    if ENABLE_USER_SITE:
        execusercustomize()

if not sys.flags.no_site:
    main()

def _script():
    help = "    %s [--user-base] [--user-site]\n\n    Without arguments print some useful information\n    With arguments print the value of USER_BASE and/or USER_SITE separated\n    by '%s'.\n\n    Exit codes with --user-base or --user-site:\n      0 - user site directory is enabled\n      1 - user site directory is disabled by user\n      2 - uses site directory is disabled by super user\n          or for security reasons\n     >2 - unknown error\n    "
    args = sys.argv[1:]
    if not args:
        user_base = getuserbase()
        user_site = getusersitepackages()
        print('sys.path = [')
        for dir in sys.path:
            print('    %r,' % (dir,))
        print(']')
        print('USER_BASE: %r (%s)' % (user_base, 'exists' if os.path.isdir(user_base) else "doesn't exist"))
        print('USER_SITE: %r (%s)' % (user_site, 'exists' if os.path.isdir(user_site) else "doesn't exist"))
        print('ENABLE_USER_SITE: %r' % ENABLE_USER_SITE)
        sys.exit(0)
    buffer = []
    if '--user-base' in args:
        buffer.append(USER_BASE)
    if '--user-site' in args:
        buffer.append(USER_SITE)
    if buffer:
        print(os.pathsep.join(buffer))
        if ENABLE_USER_SITE:
            sys.exit(0)
        elif ENABLE_USER_SITE is False:
            sys.exit(1)
        elif ENABLE_USER_SITE is None:
            sys.exit(2)
        else:
            sys.exit(3)
    else:
        import textwrap
        print(textwrap.dedent(help % (sys.argv[0], os.pathsep)))
        sys.exit(10)

if __name__ == '__main__':
    _script()
