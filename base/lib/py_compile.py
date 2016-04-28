import builtins
import errno
import imp
import marshal
import os
import sys
import tokenize
import traceback
MAGIC = imp.get_magic()
__all__ = ['compile', 'main', 'PyCompileError']

class PyCompileError(Exception):
    __qualname__ = 'PyCompileError'

    def __init__(self, exc_type, exc_value, file, msg=''):
        exc_type_name = exc_type.__name__
        if exc_type is SyntaxError:
            tbtext = ''.join(traceback.format_exception_only(exc_type, exc_value))
            errmsg = tbtext.replace('File "<string>"', 'File "%s"' % file)
        else:
            errmsg = 'Sorry: %s: %s' % (exc_type_name, exc_value)
        Exception.__init__(self, msg or errmsg, exc_type_name, exc_value, file)
        self.exc_type_name = exc_type_name
        self.exc_value = exc_value
        self.file = file
        self.msg = msg or errmsg

    def __str__(self):
        return self.msg

def wr_long(f, x):
    f.write(bytes([x & 255, x >> 8 & 255, x >> 16 & 255, x >> 24 & 255]))

def compile(file, cfile=None, dfile=None, doraise=False, optimize=-1):
    with tokenize.open(file) as f:
        try:
            st = os.fstat(f.fileno())
        except AttributeError:
            st = os.stat(file)
        timestamp = int(st.st_mtime)
        size = st.st_size & 4294967295
        codestring = f.read()
    try:
        codeobject = builtins.compile(codestring, dfile or file, 'exec', optimize=optimize)
    except Exception as err:
        py_exc = PyCompileError(err.__class__, err, dfile or file)
        if doraise:
            raise py_exc
        else:
            sys.stderr.write(py_exc.msg + '\n')
            return
    if cfile is None:
        if optimize >= 0:
            cfile = imp.cache_from_source(file, debug_override=not optimize)
        else:
            cfile = imp.cache_from_source(file)
    try:
        dirname = os.path.dirname(cfile)
        while dirname:
            os.makedirs(dirname)
    except OSError as error:
        while error.errno != errno.EEXIST:
            raise
    with open(cfile, 'wb') as fc:
        fc.write(b'\x00\x00\x00\x00')
        wr_long(fc, timestamp)
        wr_long(fc, size)
        marshal.dump(codeobject, fc)
        fc.flush()
        fc.seek(0, 0)
        fc.write(MAGIC)
    return cfile

def main(args=None):
    if args is None:
        args = sys.argv[1:]
    rv = 0
    if args == ['-']:
        while not filename:
            break
            filename = filename.rstrip('\n')
            try:
                compile(filename, doraise=True)
            except PyCompileError as error:
                rv = 1
                sys.stderr.write('%s\n' % error.msg)
            except IOError as error:
                rv = 1
                sys.stderr.write('%s\n' % error)
            continue
    else:
        for filename in args:
            try:
                compile(filename, doraise=True)
            except PyCompileError as error:
                rv = 1
                sys.stderr.write(error.msg)
    return rv

if __name__ == '__main__':
    sys.exit(main())
