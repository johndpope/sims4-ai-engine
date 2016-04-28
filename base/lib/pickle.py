from types import FunctionType, BuiltinFunctionType
from copyreg import dispatch_table
from copyreg import _extension_registry, _inverted_registry, _extension_cache
import marshal
import sys
import struct
import re
import io
import codecs
import _compat_pickle
__all__ = ['PickleError', 'PicklingError', 'UnpicklingError', 'Pickler', 'Unpickler', 'dump', 'dumps', 'load', 'loads']
bytes_types = (bytes, bytearray)
format_version = '3.0'
compatible_formats = ['1.0', '1.1', '1.2', '1.3', '2.0', '3.0']
HIGHEST_PROTOCOL = 3
DEFAULT_PROTOCOL = 3
mloads = marshal.loads

class PickleError(Exception):
    __qualname__ = 'PickleError'

class PicklingError(PickleError):
    __qualname__ = 'PicklingError'

class UnpicklingError(PickleError):
    __qualname__ = 'UnpicklingError'

class _Stop(Exception):
    __qualname__ = '_Stop'

    def __init__(self, value):
        self.value = value

try:
    from org.python.core import PyStringMap
except ImportError:
    PyStringMap = None
MARK = b'('
STOP = b'.'
POP = b'0'
POP_MARK = b'1'
DUP = b'2'
FLOAT = b'F'
INT = b'I'
BININT = b'J'
BININT1 = b'K'
LONG = b'L'
BININT2 = b'M'
NONE = b'N'
PERSID = b'P'
BINPERSID = b'Q'
REDUCE = b'R'
STRING = b'S'
BINSTRING = b'T'
SHORT_BINSTRING = b'U'
UNICODE = b'V'
BINUNICODE = b'X'
APPEND = b'a'
BUILD = b'b'
GLOBAL = b'c'
DICT = b'd'
EMPTY_DICT = b'}'
APPENDS = b'e'
GET = b'g'
BINGET = b'h'
INST = b'i'
LONG_BINGET = b'j'
LIST = b'l'
EMPTY_LIST = b']'
OBJ = b'o'
PUT = b'p'
BINPUT = b'q'
LONG_BINPUT = b'r'
SETITEM = b's'
TUPLE = b't'
EMPTY_TUPLE = b')'
SETITEMS = b'u'
BINFLOAT = b'G'
TRUE = b'I01\n'
FALSE = b'I00\n'
PROTO = b'\x80'
NEWOBJ = b'\x81'
EXT1 = b'\x82'
EXT2 = b'\x83'
EXT4 = b'\x84'
TUPLE1 = b'\x85'
TUPLE2 = b'\x86'
TUPLE3 = b'\x87'
NEWTRUE = b'\x88'
NEWFALSE = b'\x89'
LONG1 = b'\x8a'
LONG4 = b'\x8b'
_tuplesize2code = [EMPTY_TUPLE, TUPLE1, TUPLE2, TUPLE3]
BINBYTES = b'B'
SHORT_BINBYTES = b'C'
__all__.extend([x for x in dir() if re.match('[A-Z][A-Z0-9_]+$', x)])

class _Pickler:
    __qualname__ = '_Pickler'

    def __init__(self, file, protocol=None, *, fix_imports=True):
        if protocol is None:
            protocol = DEFAULT_PROTOCOL
        if protocol < 0:
            protocol = HIGHEST_PROTOCOL
        elif not 0 <= protocol <= HIGHEST_PROTOCOL:
            raise ValueError('pickle protocol must be <= %d' % HIGHEST_PROTOCOL)
        try:
            self.write = file.write
        except AttributeError:
            raise TypeError("file must have a 'write' attribute")
        self.memo = {}
        self.proto = int(protocol)
        self.bin = protocol >= 1
        self.fast = 0
        self.fix_imports = fix_imports and protocol < 3

    def clear_memo(self):
        self.memo.clear()

    def dump(self, obj):
        if not hasattr(self, 'write'):
            raise PicklingError('Pickler.__init__() was not called by %s.__init__()' % (self.__class__.__name__,))
        if self.proto >= 2:
            self.write(PROTO + bytes([self.proto]))
        self.save(obj)
        self.write(STOP)

    def memoize(self, obj):
        if self.fast:
            return
        memo_len = len(self.memo)
        self.write(self.put(memo_len))
        self.memo[id(obj)] = (memo_len, obj)

    def put(self, i, pack=struct.pack):
        if self.bin:
            if i < 256:
                return BINPUT + bytes([i])
            return LONG_BINPUT + pack('<I', i)
        return PUT + repr(i).encode('ascii') + b'\n'

    def get(self, i, pack=struct.pack):
        if self.bin:
            if i < 256:
                return BINGET + bytes([i])
            return LONG_BINGET + pack('<I', i)
        return GET + repr(i).encode('ascii') + b'\n'

    def save(self, obj, save_persistent_id=True):
        pid = self.persistent_id(obj)
        if pid is not None and save_persistent_id:
            self.save_pers(pid)
            return
        x = self.memo.get(id(obj))
        if x:
            self.write(self.get(x[0]))
            return
        t = type(obj)
        f = self.dispatch.get(t)
        if f:
            f(self, obj)
            return
        reduce = getattr(self, 'dispatch_table', dispatch_table).get(t)
        if reduce:
            rv = reduce(obj)
        else:
            try:
                issc = issubclass(t, type)
            except TypeError:
                issc = False
            if issc:
                self.save_global(obj)
                return
            reduce = getattr(obj, '__reduce_ex__', None)
            if reduce:
                rv = reduce(self.proto)
            else:
                reduce = getattr(obj, '__reduce__', None)
                if reduce:
                    rv = reduce()
                else:
                    raise PicklingError("Can't pickle %r object: %r" % (t.__name__, obj))
        if isinstance(rv, str):
            self.save_global(obj, rv)
            return
        if not isinstance(rv, tuple):
            raise PicklingError('%s must return string or tuple' % reduce)
        l = len(rv)
        if not 2 <= l <= 5:
            raise PicklingError('Tuple returned by %s must have two to five elements' % reduce)
        self.save_reduce(obj=obj, *rv)

    def persistent_id(self, obj):
        pass

    def save_pers(self, pid):
        if self.bin:
            self.save(pid, save_persistent_id=False)
            self.write(BINPERSID)
        else:
            self.write(PERSID + str(pid).encode('ascii') + b'\n')

    def save_reduce(self, func, args, state=None, listitems=None, dictitems=None, obj=None):
        if not isinstance(args, tuple):
            raise PicklingError('args from save_reduce() should be a tuple')
        if not callable(func):
            raise PicklingError('func from save_reduce() should be callable')
        save = self.save
        write = self.write
        if self.proto >= 2 and getattr(func, '__name__', '') == '__newobj__':
            cls = args[0]
            if not hasattr(cls, '__new__'):
                raise PicklingError('args[0] from __newobj__ args has no __new__')
            if obj is not None and cls is not obj.__class__:
                raise PicklingError('args[0] from __newobj__ args has the wrong class')
            args = args[1:]
            save(cls)
            save(args)
            write(NEWOBJ)
        else:
            save(func)
            save(args)
            write(REDUCE)
        if obj is not None:
            self.memoize(obj)
        if listitems is not None:
            self._batch_appends(listitems)
        if dictitems is not None:
            self._batch_setitems(dictitems)
        if state is not None:
            save(state)
            write(BUILD)

    dispatch = {}

    def save_none(self, obj):
        self.write(NONE)

    dispatch[type(None)] = save_none

    def save_ellipsis(self, obj):
        self.save_global(Ellipsis, 'Ellipsis')

    dispatch[type(Ellipsis)] = save_ellipsis

    def save_notimplemented(self, obj):
        self.save_global(NotImplemented, 'NotImplemented')

    dispatch[type(NotImplemented)] = save_notimplemented

    def save_bool(self, obj):
        if self.proto >= 2:
            self.write(obj and NEWTRUE or NEWFALSE)
        else:
            self.write(obj and TRUE or FALSE)

    dispatch[bool] = save_bool

    def save_long(self, obj, pack=struct.pack):
        if obj <= 255:
            self.write(BININT1 + bytes([obj]))
            return
        if obj >= 0 and obj <= 65535:
            self.write(BININT2 + bytes([obj & 255, obj >> 8]))
            return
        high_bits = obj >> 31
        if self.bin and (high_bits == 0 or high_bits == -1):
            self.write(BININT + pack('<i', obj))
            return
        if self.proto >= 2:
            encoded = encode_long(obj)
            n = len(encoded)
            if n < 256:
                self.write(LONG1 + bytes([n]) + encoded)
            else:
                self.write(LONG4 + pack('<i', n) + encoded)
            return
        self.write(LONG + repr(obj).encode('ascii') + b'L\n')

    dispatch[int] = save_long

    def save_float(self, obj, pack=struct.pack):
        if self.bin:
            self.write(BINFLOAT + pack('>d', obj))
        else:
            self.write(FLOAT + repr(obj).encode('ascii') + b'\n')

    dispatch[float] = save_float

    def save_bytes(self, obj, pack=struct.pack):
        if self.proto < 3:
            if len(obj) == 0:
                self.save_reduce(bytes, (), obj=obj)
            else:
                self.save_reduce(codecs.encode, (str(obj, 'latin1'), 'latin1'), obj=obj)
            return
        n = len(obj)
        if n < 256:
            self.write(SHORT_BINBYTES + bytes([n]) + bytes(obj))
        else:
            self.write(BINBYTES + pack('<I', n) + bytes(obj))
        self.memoize(obj)

    dispatch[bytes] = save_bytes

    def save_str(self, obj, pack=struct.pack):
        if self.bin:
            encoded = obj.encode('utf-8', 'surrogatepass')
            n = len(encoded)
            self.write(BINUNICODE + pack('<I', n) + encoded)
        else:
            obj = obj.replace('\\', '\\u005c')
            obj = obj.replace('\n', '\\u000a')
            self.write(UNICODE + bytes(obj.encode('raw-unicode-escape')) + b'\n')
        self.memoize(obj)

    dispatch[str] = save_str

    def save_tuple(self, obj):
        write = self.write
        proto = self.proto
        n = len(obj)
        if n == 0:
            if proto:
                write(EMPTY_TUPLE)
            else:
                write(MARK + TUPLE)
            return
        save = self.save
        memo = self.memo
        if n <= 3 and proto >= 2:
            for element in obj:
                save(element)
            if id(obj) in memo:
                get = self.get(memo[id(obj)][0])
                write(POP*n + get)
            else:
                write(_tuplesize2code[n])
                self.memoize(obj)
            return
        write(MARK)
        for element in obj:
            save(element)
        if id(obj) in memo:
            get = self.get(memo[id(obj)][0])
            if proto:
                write(POP_MARK + get)
            else:
                write(POP*(n + 1) + get)
            return
        self.write(TUPLE)
        self.memoize(obj)

    dispatch[tuple] = save_tuple

    def save_list(self, obj):
        write = self.write
        if self.bin:
            write(EMPTY_LIST)
        else:
            write(MARK + LIST)
        self.memoize(obj)
        self._batch_appends(obj)

    dispatch[list] = save_list
    _BATCHSIZE = 1000

    def _batch_appends(self, items):
        save = self.save
        write = self.write
        if not self.bin:
            for x in items:
                save(x)
                write(APPEND)
            return
        items = iter(items)
        r = range(self._BATCHSIZE)
        while items is not None:
            tmp = []
            for i in r:
                try:
                    x = next(items)
                    tmp.append(x)
                except StopIteration:
                    items = None
                    break
            n = len(tmp)
            if n > 1:
                write(MARK)
                for x in tmp:
                    save(x)
                write(APPENDS)
            else:
                while n:
                    save(tmp[0])
                    write(APPEND)
                    continue

    def save_dict(self, obj):
        write = self.write
        if self.bin:
            write(EMPTY_DICT)
        else:
            write(MARK + DICT)
        self.memoize(obj)
        self._batch_setitems(obj.items())

    dispatch[dict] = save_dict
    if PyStringMap is not None:
        dispatch[PyStringMap] = save_dict

    def _batch_setitems(self, items):
        save = self.save
        write = self.write
        if not self.bin:
            for (k, v) in items:
                save(k)
                save(v)
                write(SETITEM)
            return
        items = iter(items)
        r = range(self._BATCHSIZE)
        while items is not None:
            tmp = []
            for i in r:
                try:
                    tmp.append(next(items))
                except StopIteration:
                    items = None
                    break
            n = len(tmp)
            if n > 1:
                write(MARK)
                for (k, v) in tmp:
                    save(k)
                    save(v)
                write(SETITEMS)
            else:
                while n:
                    (k, v) = tmp[0]
                    save(k)
                    save(v)
                    write(SETITEM)
                    continue

    def save_global(self, obj, name=None, pack=struct.pack):
        write = self.write
        memo = self.memo
        if name is None:
            name = obj.__name__
        module = getattr(obj, '__module__', None)
        if module is None:
            module = whichmodule(obj, name)
        try:
            __import__(module, level=0)
            mod = sys.modules[module]
            klass = getattr(mod, name)
        except (ImportError, KeyError, AttributeError):
            raise PicklingError("Can't pickle %r: it's not found as %s.%s" % (obj, module, name))
        if klass is not obj:
            raise PicklingError("Can't pickle %r: it's not the same object as %s.%s" % (obj, module, name))
        if self.proto >= 2:
            code = _extension_registry.get((module, name))
            if code:
                if code <= 255:
                    write(EXT1 + bytes([code]))
                elif code <= 65535:
                    write(EXT2 + bytes([code & 255, code >> 8]))
                else:
                    write(EXT4 + pack('<i', code))
                return
        if self.proto >= 3:
            write(GLOBAL + bytes(module, 'utf-8') + b'\n' + bytes(name, 'utf-8') + b'\n')
        else:
            if (module, name) in _compat_pickle.REVERSE_NAME_MAPPING:
                (module, name) = _compat_pickle.REVERSE_NAME_MAPPING[(module, name)]
            if self.fix_imports and module in _compat_pickle.REVERSE_IMPORT_MAPPING:
                module = _compat_pickle.REVERSE_IMPORT_MAPPING[module]
            try:
                write(GLOBAL + bytes(module, 'ascii') + b'\n' + bytes(name, 'ascii') + b'\n')
            except UnicodeEncodeError:
                raise PicklingError("can't pickle global identifier '%s.%s' using pickle protocol %i" % (module, name, self.proto))
        self.memoize(obj)

    def save_type(self, obj):
        if obj is type(None):
            return self.save_reduce(type, (None,), obj=obj)
        if obj is type(NotImplemented):
            return self.save_reduce(type, (NotImplemented,), obj=obj)
        if obj is type(Ellipsis):
            return self.save_reduce(type, (Ellipsis,), obj=obj)
        return self.save_global(obj)

    dispatch[FunctionType] = save_global
    dispatch[BuiltinFunctionType] = save_global
    dispatch[type] = save_type

def _keep_alive(x, memo):
    try:
        memo[id(memo)].append(x)
    except KeyError:
        memo[id(memo)] = [x]

classmap = {}

def whichmodule(func, funcname):
    mod = getattr(func, '__module__', None)
    if mod is not None:
        return mod
    if func in classmap:
        return classmap[func]
    for (name, module) in list(sys.modules.items()):
        if module is None:
            pass
        while name != '__main__' and getattr(module, funcname, None) is func:
            break
    name = '__main__'
    classmap[func] = name
    return name

class _Unpickler:
    __qualname__ = '_Unpickler'

    def __init__(self, file, *, fix_imports=True, encoding='ASCII', errors='strict'):
        self.readline = file.readline
        self.read = file.read
        self.memo = {}
        self.encoding = encoding
        self.errors = errors
        self.proto = 0
        self.fix_imports = fix_imports

    def load(self):
        if not hasattr(self, 'read'):
            raise UnpicklingError('Unpickler.__init__() was not called by %s.__init__()' % (self.__class__.__name__,))
        self.mark = object()
        self.stack = []
        self.append = self.stack.append
        read = self.read
        dispatch = self.dispatch
        try:
            while True:
                key = read(1)
                if not key:
                    raise EOFError
                dispatch[key[0]](self)
        except _Stop as stopinst:
            return stopinst.value

    def marker(self):
        stack = self.stack
        mark = self.mark
        k = len(stack) - 1
        while stack[k] is not mark:
            k = k - 1
        return k

    def persistent_load(self, pid):
        raise UnpicklingError('unsupported persistent id encountered')

    dispatch = {}

    def load_proto(self):
        proto = ord(self.read(1))
        if not 0 <= proto <= HIGHEST_PROTOCOL:
            raise ValueError('unsupported pickle protocol: %d' % proto)
        self.proto = proto

    dispatch[PROTO[0]] = load_proto

    def load_persid(self):
        pid = self.readline()[:-1].decode('ascii')
        self.append(self.persistent_load(pid))

    dispatch[PERSID[0]] = load_persid

    def load_binpersid(self):
        pid = self.stack.pop()
        self.append(self.persistent_load(pid))

    dispatch[BINPERSID[0]] = load_binpersid

    def load_none(self):
        self.append(None)

    dispatch[NONE[0]] = load_none

    def load_false(self):
        self.append(False)

    dispatch[NEWFALSE[0]] = load_false

    def load_true(self):
        self.append(True)

    dispatch[NEWTRUE[0]] = load_true

    def load_int(self):
        data = self.readline()
        if data == FALSE[1:]:
            val = False
        elif data == TRUE[1:]:
            val = True
        else:
            try:
                val = int(data, 0)
            except ValueError:
                val = int(data, 0)
        self.append(val)

    dispatch[INT[0]] = load_int

    def load_binint(self):
        self.append(mloads(b'i' + self.read(4)))

    dispatch[BININT[0]] = load_binint

    def load_binint1(self):
        self.append(ord(self.read(1)))

    dispatch[BININT1[0]] = load_binint1

    def load_binint2(self):
        self.append(mloads(b'i' + self.read(2) + b'\x00\x00'))

    dispatch[BININT2[0]] = load_binint2

    def load_long(self):
        val = self.readline()[:-1].decode('ascii')
        if val and val[-1] == 'L':
            val = val[:-1]
        self.append(int(val, 0))

    dispatch[LONG[0]] = load_long

    def load_long1(self):
        n = ord(self.read(1))
        data = self.read(n)
        self.append(decode_long(data))

    dispatch[LONG1[0]] = load_long1

    def load_long4(self):
        n = mloads(b'i' + self.read(4))
        if n < 0:
            raise UnpicklingError('LONG pickle has negative byte count')
        data = self.read(n)
        self.append(decode_long(data))

    dispatch[LONG4[0]] = load_long4

    def load_float(self):
        self.append(float(self.readline()[:-1]))

    dispatch[FLOAT[0]] = load_float

    def load_binfloat(self, unpack=struct.unpack):
        self.append(unpack('>d', self.read(8))[0])

    dispatch[BINFLOAT[0]] = load_binfloat

    def load_string(self):
        orig = self.readline()
        rep = orig[:-1]
        for q in (b'"', b"'"):
            while rep.startswith(q):
                if len(rep) < 2 or not rep.endswith(q):
                    raise ValueError('insecure string pickle')
                rep = rep[len(q):-len(q)]
                break
        raise ValueError('insecure string pickle: %r' % orig)
        self.append(codecs.escape_decode(rep)[0].decode(self.encoding, self.errors))

    dispatch[STRING[0]] = load_string

    def load_binstring(self):
        len = mloads(b'i' + self.read(4))
        if len < 0:
            raise UnpicklingError('BINSTRING pickle has negative byte count')
        data = self.read(len)
        value = str(data, self.encoding, self.errors)
        self.append(value)

    dispatch[BINSTRING[0]] = load_binstring

    def load_binbytes(self, unpack=struct.unpack, maxsize=sys.maxsize):
        (len,) = unpack('<I', self.read(4))
        if len > maxsize:
            raise UnpicklingError("BINBYTES exceeds system's maximum size of %d bytes" % maxsize)
        self.append(self.read(len))

    dispatch[BINBYTES[0]] = load_binbytes

    def load_unicode(self):
        self.append(str(self.readline()[:-1], 'raw-unicode-escape'))

    dispatch[UNICODE[0]] = load_unicode

    def load_binunicode(self, unpack=struct.unpack, maxsize=sys.maxsize):
        (len,) = unpack('<I', self.read(4))
        if len > maxsize:
            raise UnpicklingError("BINUNICODE exceeds system's maximum size of %d bytes" % maxsize)
        self.append(str(self.read(len), 'utf-8', 'surrogatepass'))

    dispatch[BINUNICODE[0]] = load_binunicode

    def load_short_binstring(self):
        len = ord(self.read(1))
        data = bytes(self.read(len))
        value = str(data, self.encoding, self.errors)
        self.append(value)

    dispatch[SHORT_BINSTRING[0]] = load_short_binstring

    def load_short_binbytes(self):
        len = ord(self.read(1))
        self.append(bytes(self.read(len)))

    dispatch[SHORT_BINBYTES[0]] = load_short_binbytes

    def load_tuple(self):
        k = self.marker()
        self.stack[k:] = [tuple(self.stack[k + 1:])]

    dispatch[TUPLE[0]] = load_tuple

    def load_empty_tuple(self):
        self.append(())

    dispatch[EMPTY_TUPLE[0]] = load_empty_tuple

    def load_tuple1(self):
        self.stack[-1] = (self.stack[-1],)

    dispatch[TUPLE1[0]] = load_tuple1

    def load_tuple2(self):
        self.stack[-2:] = [(self.stack[-2], self.stack[-1])]

    dispatch[TUPLE2[0]] = load_tuple2

    def load_tuple3(self):
        self.stack[-3:] = [(self.stack[-3], self.stack[-2], self.stack[-1])]

    dispatch[TUPLE3[0]] = load_tuple3

    def load_empty_list(self):
        self.append([])

    dispatch[EMPTY_LIST[0]] = load_empty_list

    def load_empty_dictionary(self):
        self.append({})

    dispatch[EMPTY_DICT[0]] = load_empty_dictionary

    def load_list(self):
        k = self.marker()
        self.stack[k:] = [self.stack[k + 1:]]

    dispatch[LIST[0]] = load_list

    def load_dict(self):
        k = self.marker()
        d = {}
        items = self.stack[k + 1:]
        for i in range(0, len(items), 2):
            key = items[i]
            value = items[i + 1]
            d[key] = value
        self.stack[k:] = [d]

    dispatch[DICT[0]] = load_dict

    def _instantiate(self, klass, k):
        args = tuple(self.stack[k + 1:])
        del self.stack[k:]
        if args or not isinstance(klass, type) or hasattr(klass, '__getinitargs__'):
            try:
                value = klass(*args)
            except TypeError as err:
                raise TypeError('in constructor for %s: %s' % (klass.__name__, str(err)), sys.exc_info()[2])
        else:
            value = klass.__new__(klass)
        self.append(value)

    def load_inst(self):
        module = self.readline()[:-1].decode('ascii')
        name = self.readline()[:-1].decode('ascii')
        klass = self.find_class(module, name)
        self._instantiate(klass, self.marker())

    dispatch[INST[0]] = load_inst

    def load_obj(self):
        k = self.marker()
        klass = self.stack.pop(k + 1)
        self._instantiate(klass, k)

    dispatch[OBJ[0]] = load_obj

    def load_newobj(self):
        args = self.stack.pop()
        cls = self.stack[-1]
        obj = cls.__new__(cls, *args)
        self.stack[-1] = obj

    dispatch[NEWOBJ[0]] = load_newobj

    def load_global(self):
        module = self.readline()[:-1].decode('utf-8')
        name = self.readline()[:-1].decode('utf-8')
        klass = self.find_class(module, name)
        self.append(klass)

    dispatch[GLOBAL[0]] = load_global

    def load_ext1(self):
        code = ord(self.read(1))
        self.get_extension(code)

    dispatch[EXT1[0]] = load_ext1

    def load_ext2(self):
        code = mloads(b'i' + self.read(2) + b'\x00\x00')
        self.get_extension(code)

    dispatch[EXT2[0]] = load_ext2

    def load_ext4(self):
        code = mloads(b'i' + self.read(4))
        self.get_extension(code)

    dispatch[EXT4[0]] = load_ext4

    def get_extension(self, code):
        nil = []
        obj = _extension_cache.get(code, nil)
        if obj is not nil:
            self.append(obj)
            return
        key = _inverted_registry.get(code)
        if not key:
            if code <= 0:
                raise UnpicklingError('EXT specifies code <= 0')
            raise ValueError('unregistered extension code %d' % code)
        obj = self.find_class(*key)
        _extension_cache[code] = obj
        self.append(obj)

    def find_class(self, module, name):
        if (module, name) in _compat_pickle.NAME_MAPPING:
            (module, name) = _compat_pickle.NAME_MAPPING[(module, name)]
        if self.proto < 3 and self.fix_imports and module in _compat_pickle.IMPORT_MAPPING:
            module = _compat_pickle.IMPORT_MAPPING[module]
        __import__(module, level=0)
        mod = sys.modules[module]
        klass = getattr(mod, name)
        return klass

    def load_reduce(self):
        stack = self.stack
        args = stack.pop()
        func = stack[-1]
        try:
            value = func(*args)
        except:
            print(sys.exc_info())
            print(func, args)
            raise
        stack[-1] = value

    dispatch[REDUCE[0]] = load_reduce

    def load_pop(self):
        del self.stack[-1]

    dispatch[POP[0]] = load_pop

    def load_pop_mark(self):
        k = self.marker()
        del self.stack[k:]

    dispatch[POP_MARK[0]] = load_pop_mark

    def load_dup(self):
        self.append(self.stack[-1])

    dispatch[DUP[0]] = load_dup

    def load_get(self):
        i = int(self.readline()[:-1])
        self.append(self.memo[i])

    dispatch[GET[0]] = load_get

    def load_binget(self):
        i = self.read(1)[0]
        self.append(self.memo[i])

    dispatch[BINGET[0]] = load_binget

    def load_long_binget(self, unpack=struct.unpack):
        (i,) = unpack('<I', self.read(4))
        self.append(self.memo[i])

    dispatch[LONG_BINGET[0]] = load_long_binget

    def load_put(self):
        i = int(self.readline()[:-1])
        if i < 0:
            raise ValueError('negative PUT argument')
        self.memo[i] = self.stack[-1]

    dispatch[PUT[0]] = load_put

    def load_binput(self):
        i = self.read(1)[0]
        if i < 0:
            raise ValueError('negative BINPUT argument')
        self.memo[i] = self.stack[-1]

    dispatch[BINPUT[0]] = load_binput

    def load_long_binput(self, unpack=struct.unpack, maxsize=sys.maxsize):
        (i,) = unpack('<I', self.read(4))
        if i > maxsize:
            raise ValueError('negative LONG_BINPUT argument')
        self.memo[i] = self.stack[-1]

    dispatch[LONG_BINPUT[0]] = load_long_binput

    def load_append(self):
        stack = self.stack
        value = stack.pop()
        list = stack[-1]
        list.append(value)

    dispatch[APPEND[0]] = load_append

    def load_appends(self):
        stack = self.stack
        mark = self.marker()
        list_obj = stack[mark - 1]
        items = stack[mark + 1:]
        if isinstance(list_obj, list):
            list_obj.extend(items)
        else:
            append = list_obj.append
            for item in items:
                append(item)
        del stack[mark:]

    dispatch[APPENDS[0]] = load_appends

    def load_setitem(self):
        stack = self.stack
        value = stack.pop()
        key = stack.pop()
        dict = stack[-1]
        dict[key] = value

    dispatch[SETITEM[0]] = load_setitem

    def load_setitems(self):
        stack = self.stack
        mark = self.marker()
        dict = stack[mark - 1]
        for i in range(mark + 1, len(stack), 2):
            dict[stack[i]] = stack[i + 1]
        del stack[mark:]

    dispatch[SETITEMS[0]] = load_setitems

    def load_build(self):
        stack = self.stack
        state = stack.pop()
        inst = stack[-1]
        setstate = getattr(inst, '__setstate__', None)
        if setstate:
            setstate(state)
            return
        slotstate = None
        if isinstance(state, tuple) and len(state) == 2:
            (state, slotstate) = state
        if state:
            inst_dict = inst.__dict__
            intern = sys.intern
            for (k, v) in state.items():
                if type(k) is str:
                    inst_dict[intern(k)] = v
                else:
                    inst_dict[k] = v
        if slotstate:
            for (k, v) in slotstate.items():
                setattr(inst, k, v)

    dispatch[BUILD[0]] = load_build

    def load_mark(self):
        self.append(self.mark)

    dispatch[MARK[0]] = load_mark

    def load_stop(self):
        value = self.stack.pop()
        raise _Stop(value)

    dispatch[STOP[0]] = load_stop

def encode_long(x):
    if x == 0:
        return b''
    nbytes = (x.bit_length() >> 3) + 1
    result = x.to_bytes(nbytes, byteorder='little', signed=True)
    if x < 0 and (nbytes > 1 and result[-1] == 255) and result[-2] & 128 != 0:
        result = result[:-1]
    return result

def decode_long(data):
    return int.from_bytes(data, byteorder='little', signed=True)

def dump(obj, file, protocol=None, *, fix_imports=True):
    Pickler(file, protocol, fix_imports=fix_imports).dump(obj)

def dumps(obj, protocol=None, *, fix_imports=True):
    f = io.BytesIO()
    Pickler(f, protocol, fix_imports=fix_imports).dump(obj)
    res = f.getvalue()
    return res

def load(file, *, fix_imports=True, encoding='ASCII', errors='strict'):
    return Unpickler(file, fix_imports=fix_imports, encoding=encoding, errors=errors).load()

def loads(s, *, fix_imports=True, encoding='ASCII', errors='strict'):
    if isinstance(s, str):
        raise TypeError("Can't load pickle from unicode string")
    file = io.BytesIO(s)
    return Unpickler(file, fix_imports=fix_imports, encoding=encoding, errors=errors).load()

try:
    from _pickle import *
except ImportError:
    (Pickler, Unpickler) = (_Pickler, _Unpickler)

def _test():
    import doctest
    return doctest.testmod()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='display contents of the pickle files')
    parser.add_argument('pickle_file', type=argparse.FileType('br'), nargs='*', help='the pickle file')
    parser.add_argument('-t', '--test', action='store_true', help='run self-test suite')
    parser.add_argument('-v', action='store_true', help='run verbosely; only affects self-test run')
    args = parser.parse_args()
    if args.test:
        _test()
    elif not args.pickle_file:
        parser.print_help()
    else:
        import pprint
        for f in args.pickle_file:
            obj = load(f)
            pprint.pprint(obj)
