import builtins
import sys
try:
    from _codecs import *
except ImportError as why:
    raise SystemError('Failed to load the builtin codecs: %s' % why)
__all__ = ['register', 'lookup', 'open', 'EncodedFile', 'BOM', 'BOM_BE', 'BOM_LE', 'BOM32_BE', 'BOM32_LE', 'BOM64_BE', 'BOM64_LE', 'BOM_UTF8', 'BOM_UTF16', 'BOM_UTF16_LE', 'BOM_UTF16_BE', 'BOM_UTF32', 'BOM_UTF32_LE', 'BOM_UTF32_BE', 'strict_errors', 'ignore_errors', 'replace_errors', 'xmlcharrefreplace_errors', 'register_error', 'lookup_error']
BOM_UTF8 = b'\xef\xbb\xbf'
BOM_LE = BOM_UTF16_LE = b'\xff\xfe'
BOM_BE = BOM_UTF16_BE = b'\xfe\xff'
BOM_UTF32_LE = b'\xff\xfe\x00\x00'
BOM_UTF32_BE = b'\x00\x00\xfe\xff'
if sys.byteorder == 'little':
    BOM = BOM_UTF16 = BOM_UTF16_LE
    BOM_UTF32 = BOM_UTF32_LE
else:
    BOM = BOM_UTF16 = BOM_UTF16_BE
    BOM_UTF32 = BOM_UTF32_BE
BOM32_LE = BOM_UTF16_LE
BOM32_BE = BOM_UTF16_BE
BOM64_LE = BOM_UTF32_LE
BOM64_BE = BOM_UTF32_BE

class CodecInfo(tuple):
    __qualname__ = 'CodecInfo'
    _is_text_encoding = True

    def __new__(cls, encode, decode, streamreader=None, streamwriter=None, incrementalencoder=None, incrementaldecoder=None, name=None, *, _is_text_encoding=None):
        self = tuple.__new__(cls, (encode, decode, streamreader, streamwriter))
        self.name = name
        self.encode = encode
        self.decode = decode
        self.incrementalencoder = incrementalencoder
        self.incrementaldecoder = incrementaldecoder
        self.streamwriter = streamwriter
        self.streamreader = streamreader
        if _is_text_encoding is not None:
            self._is_text_encoding = _is_text_encoding
        return self

    def __repr__(self):
        return '<%s.%s object for encoding %s at 0x%x>' % (self.__class__.__module__, self.__class__.__name__, self.name, id(self))

class Codec:
    __qualname__ = 'Codec'

    def encode(self, input, errors='strict'):
        raise NotImplementedError

    def decode(self, input, errors='strict'):
        raise NotImplementedError

class IncrementalEncoder(object):
    __qualname__ = 'IncrementalEncoder'

    def __init__(self, errors='strict'):
        self.errors = errors
        self.buffer = ''

    def encode(self, input, final=False):
        raise NotImplementedError

    def reset(self):
        pass

    def getstate(self):
        return 0

    def setstate(self, state):
        pass

class BufferedIncrementalEncoder(IncrementalEncoder):
    __qualname__ = 'BufferedIncrementalEncoder'

    def __init__(self, errors='strict'):
        IncrementalEncoder.__init__(self, errors)
        self.buffer = ''

    def _buffer_encode(self, input, errors, final):
        raise NotImplementedError

    def encode(self, input, final=False):
        data = self.buffer + input
        (result, consumed) = self._buffer_encode(data, self.errors, final)
        self.buffer = data[consumed:]
        return result

    def reset(self):
        IncrementalEncoder.reset(self)
        self.buffer = ''

    def getstate(self):
        return self.buffer or 0

    def setstate(self, state):
        self.buffer = state or ''

class IncrementalDecoder(object):
    __qualname__ = 'IncrementalDecoder'

    def __init__(self, errors='strict'):
        self.errors = errors

    def decode(self, input, final=False):
        raise NotImplementedError

    def reset(self):
        pass

    def getstate(self):
        return (b'', 0)

    def setstate(self, state):
        pass

class BufferedIncrementalDecoder(IncrementalDecoder):
    __qualname__ = 'BufferedIncrementalDecoder'

    def __init__(self, errors='strict'):
        IncrementalDecoder.__init__(self, errors)
        self.buffer = b''

    def _buffer_decode(self, input, errors, final):
        raise NotImplementedError

    def decode(self, input, final=False):
        data = self.buffer + input
        (result, consumed) = self._buffer_decode(data, self.errors, final)
        self.buffer = data[consumed:]
        return result

    def reset(self):
        IncrementalDecoder.reset(self)
        self.buffer = b''

    def getstate(self):
        return (self.buffer, 0)

    def setstate(self, state):
        self.buffer = state[0]

class StreamWriter(Codec):
    __qualname__ = 'StreamWriter'

    def __init__(self, stream, errors='strict'):
        self.stream = stream
        self.errors = errors

    def write(self, object):
        (data, consumed) = self.encode(object, self.errors)
        self.stream.write(data)

    def writelines(self, list):
        self.write(''.join(list))

    def reset(self):
        pass

    def seek(self, offset, whence=0):
        self.stream.seek(offset, whence)
        if whence == 0 and offset == 0:
            self.reset()

    def __getattr__(self, name, getattr=getattr):
        return getattr(self.stream, name)

    def __enter__(self):
        return self

    def __exit__(self, type, value, tb):
        self.stream.close()

class StreamReader(Codec):
    __qualname__ = 'StreamReader'
    charbuffertype = str

    def __init__(self, stream, errors='strict'):
        self.stream = stream
        self.errors = errors
        self.bytebuffer = b''
        self._empty_charbuffer = self.charbuffertype()
        self.charbuffer = self._empty_charbuffer
        self.linebuffer = None

    def decode(self, input, errors='strict'):
        raise NotImplementedError

    def read(self, size=-1, chars=-1, firstline=False):
        if self.linebuffer:
            self.charbuffer = self._empty_charbuffer.join(self.linebuffer)
            self.linebuffer = None
        while True:
            if chars >= 0:
                if len(self.charbuffer) >= chars:
                    break
            elif size >= 0 and len(self.charbuffer) >= size:
                break
            if size < 0:
                newdata = self.stream.read()
            else:
                newdata = self.stream.read(size)
            data = self.bytebuffer + newdata
            if not data:
                break
            try:
                (newchars, decodedbytes) = self.decode(data, self.errors)
            except UnicodeDecodeError as exc:
                if firstline:
                    (newchars, decodedbytes) = self.decode(data[:exc.start], self.errors)
                    lines = newchars.splitlines(keepends=True)
                    if len(lines) <= 1:
                        raise
                else:
                    raise
            self.bytebuffer = data[decodedbytes:]
            if not newdata:
                break
        if chars < 0:
            result = self.charbuffer
            self.charbuffer = self._empty_charbuffer
        else:
            result = self.charbuffer[:chars]
            self.charbuffer = self.charbuffer[chars:]
        return result

    def readline(self, size=None, keepends=True):
        if self.linebuffer:
            line = self.linebuffer[0]
            del self.linebuffer[0]
            if len(self.linebuffer) == 1:
                self.charbuffer = self.linebuffer[0]
                self.linebuffer = None
            if not keepends:
                line = line.splitlines(keepends=False)[0]
            return line
        readsize = size or 72
        line = self._empty_charbuffer
        while True:
            data = self.read(readsize, firstline=True)
            if data and (isinstance(data, str) and data.endswith('\r') or isinstance(data, bytes) and data.endswith(b'\r')):
                data += self.read(size=1, chars=1)
            line += data
            lines = line.splitlines(keepends=True)
            if len(lines) > 1:
                line = lines[0]
                del lines[0]
                if len(lines) > 1:
                    lines[-1] += self.charbuffer
                    self.linebuffer = lines
                    self.charbuffer = None
                else:
                    self.charbuffer = lines[0] + self.charbuffer
                if not keepends:
                    line = line.splitlines(keepends=False)[0]
                break
            line0withend = lines[0]
            line0withoutend = lines[0].splitlines(keepends=False)[0]
            if lines and line0withend != line0withoutend:
                self.charbuffer = self._empty_charbuffer.join(lines[1:]) + self.charbuffer
                if keepends:
                    line = line0withend
                else:
                    line = line0withoutend
                break
            if not data or size is not None:
                if line and not keepends:
                    line = line.splitlines(keepends=False)[0]
                break
            if readsize < 8000:
                readsize *= 2
        return line

    def readlines(self, sizehint=None, keepends=True):
        data = self.read()
        return data.splitlines(keepends)

    def reset(self):
        self.bytebuffer = b''
        self.charbuffer = self._empty_charbuffer
        self.linebuffer = None

    def seek(self, offset, whence=0):
        self.stream.seek(offset, whence)
        self.reset()

    def __next__(self):
        line = self.readline()
        if line:
            return line
        raise StopIteration

    def __iter__(self):
        return self

    def __getattr__(self, name, getattr=getattr):
        return getattr(self.stream, name)

    def __enter__(self):
        return self

    def __exit__(self, type, value, tb):
        self.stream.close()

class StreamReaderWriter:
    __qualname__ = 'StreamReaderWriter'
    encoding = 'unknown'

    def __init__(self, stream, Reader, Writer, errors='strict'):
        self.stream = stream
        self.reader = Reader(stream, errors)
        self.writer = Writer(stream, errors)
        self.errors = errors

    def read(self, size=-1):
        return self.reader.read(size)

    def readline(self, size=None):
        return self.reader.readline(size)

    def readlines(self, sizehint=None):
        return self.reader.readlines(sizehint)

    def __next__(self):
        return next(self.reader)

    def __iter__(self):
        return self

    def write(self, data):
        return self.writer.write(data)

    def writelines(self, list):
        return self.writer.writelines(list)

    def reset(self):
        self.reader.reset()
        self.writer.reset()

    def seek(self, offset, whence=0):
        self.stream.seek(offset, whence)
        self.reader.reset()
        if whence == 0 and offset == 0:
            self.writer.reset()

    def __getattr__(self, name, getattr=getattr):
        return getattr(self.stream, name)

    def __enter__(self):
        return self

    def __exit__(self, type, value, tb):
        self.stream.close()

class StreamRecoder:
    __qualname__ = 'StreamRecoder'
    data_encoding = 'unknown'
    file_encoding = 'unknown'

    def __init__(self, stream, encode, decode, Reader, Writer, errors='strict'):
        self.stream = stream
        self.encode = encode
        self.decode = decode
        self.reader = Reader(stream, errors)
        self.writer = Writer(stream, errors)
        self.errors = errors

    def read(self, size=-1):
        data = self.reader.read(size)
        (data, bytesencoded) = self.encode(data, self.errors)
        return data

    def readline(self, size=None):
        if size is None:
            data = self.reader.readline()
        else:
            data = self.reader.readline(size)
        (data, bytesencoded) = self.encode(data, self.errors)
        return data

    def readlines(self, sizehint=None):
        data = self.reader.read()
        (data, bytesencoded) = self.encode(data, self.errors)
        return data.splitlines(keepends=True)

    def __next__(self):
        data = next(self.reader)
        (data, bytesencoded) = self.encode(data, self.errors)
        return data

    def __iter__(self):
        return self

    def write(self, data):
        (data, bytesdecoded) = self.decode(data, self.errors)
        return self.writer.write(data)

    def writelines(self, list):
        data = ''.join(list)
        (data, bytesdecoded) = self.decode(data, self.errors)
        return self.writer.write(data)

    def reset(self):
        self.reader.reset()
        self.writer.reset()

    def __getattr__(self, name, getattr=getattr):
        return getattr(self.stream, name)

    def __enter__(self):
        return self

    def __exit__(self, type, value, tb):
        self.stream.close()

def open(filename, mode='rb', encoding=None, errors='strict', buffering=1):
    if encoding is not None and 'b' not in mode:
        mode = mode + 'b'
    file = builtins.open(filename, mode, buffering)
    if encoding is None:
        return file
    info = lookup(encoding)
    srw = StreamReaderWriter(file, info.streamreader, info.streamwriter, errors)
    srw.encoding = encoding
    return srw

def EncodedFile(file, data_encoding, file_encoding=None, errors='strict'):
    if file_encoding is None:
        file_encoding = data_encoding
    data_info = lookup(data_encoding)
    file_info = lookup(file_encoding)
    sr = StreamRecoder(file, data_info.encode, data_info.decode, file_info.streamreader, file_info.streamwriter, errors)
    sr.data_encoding = data_encoding
    sr.file_encoding = file_encoding
    return sr

def getencoder(encoding):
    return lookup(encoding).encode

def getdecoder(encoding):
    return lookup(encoding).decode

def getincrementalencoder(encoding):
    encoder = lookup(encoding).incrementalencoder
    if encoder is None:
        raise LookupError(encoding)
    return encoder

def getincrementaldecoder(encoding):
    decoder = lookup(encoding).incrementaldecoder
    if decoder is None:
        raise LookupError(encoding)
    return decoder

def getreader(encoding):
    return lookup(encoding).streamreader

def getwriter(encoding):
    return lookup(encoding).streamwriter

def iterencode(iterator, encoding, errors='strict', **kwargs):
    encoder = getincrementalencoder(encoding)(errors, **kwargs)
    for input in iterator:
        output = encoder.encode(input)
        while output:
            yield output
    output = encoder.encode('', True)
    if output:
        yield output

def iterdecode(iterator, encoding, errors='strict', **kwargs):
    decoder = getincrementaldecoder(encoding)(errors, **kwargs)
    for input in iterator:
        output = decoder.decode(input)
        while output:
            yield output
    output = decoder.decode(b'', True)
    if output:
        yield output

def make_identity_dict(rng):
    return {i: i for i in rng}

def make_encoding_map(decoding_map):
    m = {}
    for (k, v) in decoding_map.items():
        if v not in m:
            m[v] = k
        else:
            m[v] = None
    return m

try:
    strict_errors = lookup_error('strict')
    ignore_errors = lookup_error('ignore')
    replace_errors = lookup_error('replace')
    xmlcharrefreplace_errors = lookup_error('xmlcharrefreplace')
    backslashreplace_errors = lookup_error('backslashreplace')
except LookupError:
    strict_errors = None
    ignore_errors = None
    replace_errors = None
    xmlcharrefreplace_errors = None
    backslashreplace_errors = None
_false = 0
if _false:
    import encodings
if __name__ == '__main__':
    sys.stdout = EncodedFile(sys.stdout, 'latin-1', 'utf-8')
    sys.stdin = EncodedFile(sys.stdin, 'utf-8', 'latin-1')
