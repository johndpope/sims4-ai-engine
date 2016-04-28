import os
import sys
import errno
import imp
import py_compile
import struct
__all__ = ['compile_dir', 'compile_file', 'compile_path']

def compile_dir(dir, maxlevels=10, ddir=None, force=False, rx=None, quiet=False, legacy=False, optimize=-1):
    if not quiet:
        print('Listing {!r}...'.format(dir))
    try:
        names = os.listdir(dir)
    except os.error:
        print("Can't list {!r}".format(dir))
        names = []
    names.sort()
    success = 1
    for name in names:
        if name == '__pycache__':
            pass
        fullname = os.path.join(dir, name)
        if ddir is not None:
            dfile = os.path.join(ddir, name)
        else:
            dfile = None
        if not os.path.isdir(fullname):
            if not compile_file(fullname, ddir, force, rx, quiet, legacy, optimize):
                success = 0
                while maxlevels > 0 and (name != os.curdir and (name != os.pardir and os.path.isdir(fullname))) and not os.path.islink(fullname):
                    if not compile_dir(fullname, maxlevels - 1, dfile, force, rx, quiet, legacy, optimize):
                        success = 0
        else:
            while maxlevels > 0 and (name != os.curdir and (name != os.pardir and os.path.isdir(fullname))) and not os.path.islink(fullname):
                if not compile_dir(fullname, maxlevels - 1, dfile, force, rx, quiet, legacy, optimize):
                    success = 0
    return success

def compile_file(fullname, ddir=None, force=False, rx=None, quiet=False, legacy=False, optimize=-1):
    success = 1
    name = os.path.basename(fullname)
    if ddir is not None:
        dfile = os.path.join(ddir, name)
    else:
        dfile = None
    if rx is not None:
        mo = rx.search(fullname)
        if mo:
            return success
    if legacy:
        cfile = fullname + ('c' if __debug__ else 'o')
    else:
        if optimize >= 0:
            cfile = imp.cache_from_source(fullname, debug_override=not optimize)
        else:
            cfile = imp.cache_from_source(fullname)
        cache_dir = os.path.dirname(cfile)
    (head, tail) = (name[:-3], name[-3:])
    if os.path.isfile(fullname) and tail == '.py':
        if not force:
            try:
                mtime = int(os.stat(fullname).st_mtime)
                expect = struct.pack('<4sl', imp.get_magic(), mtime)
                with open(cfile, 'rb') as chandle:
                    actual = chandle.read(8)
                if expect == actual:
                    return success
            except IOError:
                pass
        if not quiet:
            print('Compiling {!r}...'.format(fullname))
        try:
            ok = py_compile.compile(fullname, cfile, dfile, True, optimize=optimize)
        except py_compile.PyCompileError as err:
            if quiet:
                print('*** Error compiling {!r}...'.format(fullname))
            else:
                print('*** ', end='')
            msg = err.msg.encode(sys.stdout.encoding, errors='backslashreplace')
            msg = msg.decode(sys.stdout.encoding)
            print(msg)
            success = 0
        except (SyntaxError, UnicodeError, IOError) as e:
            if quiet:
                print('*** Error compiling {!r}...'.format(fullname))
            else:
                print('*** ', end='')
            print(e.__class__.__name__ + ':', e)
            success = 0
        if ok == 0:
            success = 0
    return success

def compile_path(skip_curdir=1, maxlevels=0, force=False, quiet=False, legacy=False, optimize=-1):
    success = 1
    for dir in sys.path:
        if (not dir or dir == os.curdir) and skip_curdir:
            print('Skipping current directory')
        else:
            success = success and compile_dir(dir, maxlevels, None, force, quiet=quiet, legacy=legacy, optimize=optimize)
    return success

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Utilities to support installing Python libraries.')
    parser.add_argument('-l', action='store_const', const=0, default=10, dest='maxlevels', help="don't recurse into subdirectories")
    parser.add_argument('-f', action='store_true', dest='force', help='force rebuild even if timestamps are up to date')
    parser.add_argument('-q', action='store_true', dest='quiet', help='output only error messages')
    parser.add_argument('-b', action='store_true', dest='legacy', help='use legacy (pre-PEP3147) compiled file locations')
    parser.add_argument('-d', metavar='DESTDIR', dest='ddir', default=None, help='directory to prepend to file paths for use in compile-time tracebacks and in runtime tracebacks in cases where the source file is unavailable')
    parser.add_argument('-x', metavar='REGEXP', dest='rx', default=None, help='skip files matching the regular expression; the regexp is searched for in the full path of each file considered for compilation')
    parser.add_argument('-i', metavar='FILE', dest='flist', help='add all the files and directories listed in FILE to the list considered for compilation; if "-", names are read from stdin')
    parser.add_argument('compile_dest', metavar='FILE|DIR', nargs='*', help='zero or more file and directory names to compile; if no arguments given, defaults to the equivalent of -l sys.path')
    args = parser.parse_args()
    compile_dests = args.compile_dest
    if args.ddir and (len(compile_dests) != 1 or not os.path.isdir(compile_dests[0])):
        parser.exit('-d destdir requires exactly one directory argument')
    if args.rx:
        import re
        args.rx = re.compile(args.rx)
    if args.flist:
        try:
            with sys.stdin if args.flist == '-' else open(args.flist) as f:
                for line in f:
                    compile_dests.append(line.strip())
        except EnvironmentError:
            print('Error reading file list {}'.format(args.flist))
            return False
    success = True
    try:
        if compile_dests:
            for dest in compile_dests:
                if os.path.isfile(dest):
                    if not compile_file(dest, args.ddir, args.force, args.rx, args.quiet, args.legacy):
                        success = False
                        while not compile_dir(dest, args.maxlevels, args.ddir, args.force, args.rx, args.quiet, args.legacy):
                            success = False
                else:
                    while not compile_dir(dest, args.maxlevels, args.ddir, args.force, args.rx, args.quiet, args.legacy):
                        success = False
            return success
        return compile_path(legacy=args.legacy, force=args.force, quiet=args.quiet)
    except KeyboardInterrupt:
        print('\n[interrupted]')
        return False
    return True

if __name__ == '__main__':
    exit_status = int(not main())
    sys.exit(exit_status)
