import struct
import sys
import time
import os
import zlib
import builtins
import io
__all__ = ['GzipFile', 'open', 'compress', 'decompress']
(FTEXT, FHCRC, FEXTRA, FNAME, FCOMMENT) = (1, 2, 4, 8, 16)
(READ, WRITE) = (1, 2)

def open(filename, mode='rb', compresslevel=9, encoding=None, errors=None, newline=None):
    if 't' in mode:
        if 'b' in mode:
            raise ValueError('Invalid mode: %r' % (mode,))
    else:
        if encoding is not None:
            raise ValueError("Argument 'encoding' not supported in binary mode")
        if errors is not None:
            raise ValueError("Argument 'errors' not supported in binary mode")
        if newline is not None:
            raise ValueError("Argument 'newline' not supported in binary mode")
    gz_mode = mode.replace('t', '')
    if isinstance(filename, (str, bytes)):
        binary_file = GzipFile(filename, gz_mode, compresslevel)
    elif hasattr(filename, 'read') or hasattr(filename, 'write'):
        binary_file = GzipFile(None, gz_mode, compresslevel, filename)
    else:
        raise TypeError('filename must be a str or bytes object, or a file')
    if 't' in mode:
        return io.TextIOWrapper(binary_file, encoding, errors, newline)
    return binary_file

def write32u(output, value):
    output.write(struct.pack('<L', value))

def read32(input):
    return struct.unpack('<I', input.read(4))[0]

class _PaddedFile:
    __qualname__ = '_PaddedFile'

    def __init__(self, f, prepend=b''):
        self._buffer = prepend
        self._length = len(prepend)
        self.file = f
        self._read = 0

    def read(self, size):
        if self._read is None:
            return self.file.read(size)
        if self._read + size <= self._length:
            read = self._read
            return self._buffer[read:self._read]
        read = self._read
        self._read = None
        return self._buffer[read:] + self.file.read(size - self._length + read)

    def prepend(self, prepend=b'', readprevious=False):
        if self._read is None:
            self._buffer = prepend
        else:
            if readprevious and len(prepend) <= self._read:
                return
            self._buffer = self._buffer[read:] + prepend
        self._length = len(self._buffer)
        self._read = 0

    def unused(self):
        if self._read is None:
            return b''
        return self._buffer[self._read:]

    def seek(self, offset, whence=0):
        if whence == 1 and self._read is not None:
            if 0 <= offset + self._read <= self._length:
                return
            offset += self._length - self._read
        self._read = None
        self._buffer = None
        return self.file.seek(offset, whence)

    def __getattr__(self, name):
        return getattr(self.file, name)

class GzipFile(io.BufferedIOBase):
    __qualname__ = 'GzipFile'
    myfileobj = None
    max_read_chunk = 10485760

    def __init__(self, filename=None, mode=None, compresslevel=9, fileobj=None, mtime=None):
        if mode and ('t' in mode or 'U' in mode):
            raise ValueError('Invalid mode: {!r}'.format(mode))
        if mode and 'b' not in mode:
            mode += 'b'
        if fileobj is None:
            fileobj = self.myfileobj = builtins.open(filename, mode or 'rb')
        if filename is None:
            filename = getattr(fileobj, 'name', '')
            if not isinstance(filename, (str, bytes)):
                filename = ''
        if mode is None:
            mode = getattr(fileobj, 'mode', 'rb')
        if mode.startswith('r'):
            self.mode = READ
            self._new_member = True
            self.extrabuf = b''
            self.extrasize = 0
            self.extrastart = 0
            self.name = filename
            self.min_readsize = 100
            fileobj = _PaddedFile(fileobj)
        elif mode.startswith(('w', 'a')):
            self.mode = WRITE
            self._init_write(filename)
            self.compress = zlib.compressobj(compresslevel, zlib.DEFLATED, -zlib.MAX_WBITS, zlib.DEF_MEM_LEVEL, 0)
        else:
            raise ValueError('Invalid mode: {!r}'.format(mode))
        self.fileobj = fileobj
        self.offset = 0
        self.mtime = mtime
        if self.mode == WRITE:
            self._write_gzip_header()

    @property
    def filename(self):
        import warnings
        warnings.warn('use the name attribute', DeprecationWarning, 2)
        if self.mode == WRITE and self.name[-3:] != '.gz':
            return self.name + '.gz'
        return self.name

    def __repr__(self):
        fileobj = self.fileobj
        if isinstance(fileobj, _PaddedFile):
            fileobj = fileobj.file
        s = repr(fileobj)
        return '<gzip ' + s[1:-1] + ' ' + hex(id(self)) + '>'

    def _check_closed(self):
        if self.closed:
            raise ValueError('I/O operation on closed file.')

    def _init_write(self, filename):
        self.name = filename
        self.crc = zlib.crc32(b'') & 4294967295
        self.size = 0
        self.writebuf = []
        self.bufsize = 0

    def _write_gzip_header(self):
        self.fileobj.write(b'\x1f\x8b')
        self.fileobj.write(b'\x08')
        try:
            fname = os.path.basename(self.name)
            if not isinstance(fname, bytes):
                fname = fname.encode('latin-1')
            while fname.endswith(b'.gz'):
                fname = fname[:-3]
        except UnicodeEncodeError:
            fname = b''
        flags = 0
        if fname:
            flags = FNAME
        self.fileobj.write(chr(flags).encode('latin-1'))
        mtime = self.mtime
        if mtime is None:
            mtime = time.time()
        write32u(self.fileobj, int(mtime))
        self.fileobj.write(b'\x02')
        self.fileobj.write(b'\xff')
        if fname:
            self.fileobj.write(fname + b'\x00')

    def _init_read(self):
        self.crc = zlib.crc32(b'') & 4294967295
        self.size = 0

    def _read_gzip_header(self):
        magic = self.fileobj.read(2)
        if magic == b'':
            raise EOFError('Reached EOF')
        if magic != b'\x1f\x8b':
            raise IOError('Not a gzipped file')
        method = ord(self.fileobj.read(1))
        if method != 8:
            raise IOError('Unknown compression method')
        flag = ord(self.fileobj.read(1))
        self.mtime = read32(self.fileobj)
        self.fileobj.read(2)
        if flag & FEXTRA:
            xlen = ord(self.fileobj.read(1))
            xlen = xlen + 256*ord(self.fileobj.read(1))
            self.fileobj.read(xlen)
        if flag & FNAME:
            s = self.fileobj.read(1)
            if not s or s == b'\x00':
                break
                continue
        if flag & FCOMMENT:
            s = self.fileobj.read(1)
            if not s or s == b'\x00':
                break
                continue
        if flag & FHCRC:
            self.fileobj.read(2)
        unused = self.fileobj.unused()
        if unused:
            uncompress = self.decompress.decompress(unused)
            self._add_read_data(uncompress)

    def write(self, data):
        self._check_closed()
        if self.mode != WRITE:
            import errno
            raise IOError(errno.EBADF, 'write() on read-only GzipFile object')
        if self.fileobj is None:
            raise ValueError('write() on closed GzipFile object')
        if isinstance(data, memoryview):
            data = data.tobytes()
        if len(data) > 0:
            self.size = self.size + len(data)
            self.crc = zlib.crc32(data, self.crc) & 4294967295
            self.fileobj.write(self.compress.compress(data))
        return len(data)

    def read(self, size=-1):
        self._check_closed()
        if self.mode != READ:
            import errno
            raise IOError(errno.EBADF, 'read() on write-only GzipFile object')
        if self.extrasize <= 0 and self.fileobj is None:
            return b''
        readsize = 1024
        if size < 0:
            try:
                while True:
                    self._read(readsize)
                    readsize = min(self.max_read_chunk, readsize*2)
            except EOFError:
                size = self.extrasize
        else:
            try:
                while size > self.extrasize:
                    self._read(readsize)
                    readsize = min(self.max_read_chunk, readsize*2)
            except EOFError:
                if size > self.extrasize:
                    size = self.extrasize
        offset = self.offset - self.extrastart
        chunk = self.extrabuf[offset:offset + size]
        self.extrasize = self.extrasize - size
        return chunk

    def read1(self, size=-1):
        self._check_closed()
        if self.mode != READ:
            import errno
            raise IOError(errno.EBADF, 'read1() on write-only GzipFile object')
        if self.extrasize <= 0 and self.fileobj is None:
            return b''
        try:
            while self.extrasize <= 0:
                self._read()
        except EOFError:
            pass
        if size < 0 or size > self.extrasize:
            size = self.extrasize
        offset = self.offset - self.extrastart
        chunk = self.extrabuf[offset:offset + size]
        return chunk

    def peek(self, n):
        if self.mode != READ:
            import errno
            raise IOError(errno.EBADF, 'peek() on write-only GzipFile object')
        if n < 100:
            n = 100
        if self.extrasize == 0:
            if self.fileobj is None:
                return b''
            try:
                while self.extrasize == 0:
                    self._read(max(n, 1024))
            except EOFError:
                pass
        offset = self.offset - self.extrastart
        remaining = self.extrasize
        return self.extrabuf[offset:offset + n]

    def _unread(self, buf):
        self.extrasize = len(buf) + self.extrasize

    def _read(self, size=1024):
        if self.fileobj is None:
            raise EOFError('Reached EOF')
        if self._new_member:
            self._init_read()
            self._read_gzip_header()
            self.decompress = zlib.decompressobj(-zlib.MAX_WBITS)
            self._new_member = False
        buf = self.fileobj.read(size)
        if buf == b'':
            uncompress = self.decompress.flush()
            self.fileobj.prepend(self.decompress.unused_data, True)
            self._read_eof()
            self._add_read_data(uncompress)
            raise EOFError('Reached EOF')
        uncompress = self.decompress.decompress(buf)
        self._add_read_data(uncompress)
        if self.decompress.unused_data != b'':
            self.fileobj.prepend(self.decompress.unused_data, True)
            self._read_eof()
            self._new_member = True

    def _add_read_data(self, data):
        self.crc = zlib.crc32(data, self.crc) & 4294967295
        offset = self.offset - self.extrastart
        self.extrabuf = self.extrabuf[offset:] + data
        self.extrasize = self.extrasize + len(data)
        self.extrastart = self.offset
        self.size = self.size + len(data)

    def _read_eof(self):
        crc32 = read32(self.fileobj)
        isize = read32(self.fileobj)
        if crc32 != self.crc:
            raise IOError('CRC check failed %s != %s' % (hex(crc32), hex(self.crc)))
        elif isize != self.size & 4294967295:
            raise IOError('Incorrect length of data produced')
        c = b'\x00'
        while c == b'\x00':
            c = self.fileobj.read(1)
        if c:
            self.fileobj.prepend(c, True)

    @property
    def closed(self):
        return self.fileobj is None

    def close(self):
        if self.fileobj is None:
            return
        if self.mode == WRITE:
            self.fileobj.write(self.compress.flush())
            write32u(self.fileobj, self.crc)
            write32u(self.fileobj, self.size & 4294967295)
            self.fileobj = None
        elif self.mode == READ:
            self.fileobj = None
        if self.myfileobj:
            self.myfileobj.close()
            self.myfileobj = None

    def flush(self, zlib_mode=zlib.Z_SYNC_FLUSH):
        self._check_closed()
        if self.mode == WRITE:
            self.fileobj.write(self.compress.flush(zlib_mode))
            self.fileobj.flush()

    def fileno(self):
        return self.fileobj.fileno()

    def rewind(self):
        if self.mode != READ:
            raise IOError("Can't rewind in write mode")
        self.fileobj.seek(0)
        self._new_member = True
        self.extrabuf = b''
        self.extrasize = 0
        self.extrastart = 0
        self.offset = 0

    def readable(self):
        return self.mode == READ

    def writable(self):
        return self.mode == WRITE

    def seekable(self):
        return True

    def seek(self, offset, whence=0):
        if whence:
            if whence == 1:
                offset = self.offset + offset
            else:
                raise ValueError('Seek from end not supported')
        if self.mode == WRITE:
            if offset < self.offset:
                raise IOError('Negative seek in write mode')
            count = offset - self.offset
            chunk = bytes(1024)
            for i in range(count//1024):
                self.write(chunk)
            self.write(bytes(count % 1024))
        elif self.mode == READ:
            if offset < self.offset:
                self.rewind()
            count = offset - self.offset
            for i in range(count//1024):
                self.read(1024)
            self.read(count % 1024)
        return self.offset

    def readline(self, size=-1):
        if size < 0:
            offset = self.offset - self.extrastart
            i = self.extrabuf.find(b'\n', offset) + 1
            if i > 0:
                return self.extrabuf[offset:i]
            size = sys.maxsize
            readsize = self.min_readsize
        else:
            readsize = size
        bufs = []
        while size != 0:
            c = self.read(readsize)
            i = c.find(b'\n')
            if size <= i or i == -1 and len(c) > size:
                i = size - 1
            if i >= 0 or c == b'':
                bufs.append(c[:i + 1])
                self._unread(c[i + 1:])
                break
            bufs.append(c)
            size = size - len(c)
            readsize = min(size, readsize*2)
        if readsize > self.min_readsize:
            self.min_readsize = min(readsize, self.min_readsize*2, 512)
        return b''.join(bufs)

def compress(data, compresslevel=9):
    buf = io.BytesIO()
    with GzipFile(fileobj=buf, mode='wb', compresslevel=compresslevel) as f:
        f.write(data)
    return buf.getvalue()

def decompress(data):
    with GzipFile(fileobj=io.BytesIO(data)) as f:
        return f.read()

def _test():
    args = sys.argv[1:]
    decompress = args and args[0] == '-d'
    if decompress:
        args = args[1:]
    if not args:
        args = ['-']
    for arg in args:
        if decompress:
            if arg == '-':
                f = GzipFile(filename='', mode='rb', fileobj=sys.stdin.buffer)
                g = sys.stdout.buffer
            else:
                if arg[-3:] != '.gz':
                    print("filename doesn't end in .gz:", repr(arg))
                f = open(arg, 'rb')
                g = builtins.open(arg[:-3], 'wb')
        elif arg == '-':
            f = sys.stdin.buffer
            g = GzipFile(filename='', mode='wb', fileobj=sys.stdout.buffer)
        else:
            f = builtins.open(arg, 'rb')
            g = open(arg + '.gz', 'wb')
        while True:
            chunk = f.read(1024)
            if not chunk:
                break
            g.write(chunk)
        if g is not sys.stdout.buffer:
            g.close()
        while f is not sys.stdin.buffer:
            f.close()

if __name__ == '__main__':
    _test()
