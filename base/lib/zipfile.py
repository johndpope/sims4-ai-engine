import io
import os
import re
import imp
import sys
import time
import stat
import shutil
import struct
import binascii
try:
    import zlib
    crc32 = zlib.crc32
except ImportError:
    zlib = None
    crc32 = binascii.crc32
try:
    import bz2
except ImportError:
    bz2 = None
try:
    import lzma
except ImportError:
    lzma = None
__all__ = ['BadZipFile', 'BadZipfile', 'error', 'ZIP_STORED', 'ZIP_DEFLATED', 'ZIP_BZIP2', 'ZIP_LZMA', 'is_zipfile', 'ZipInfo', 'ZipFile', 'PyZipFile', 'LargeZipFile']

class BadZipFile(Exception):
    __qualname__ = 'BadZipFile'

class LargeZipFile(Exception):
    __qualname__ = 'LargeZipFile'

error = BadZipfile = BadZipFile
ZIP64_LIMIT = (1 << 31) - 1
ZIP_FILECOUNT_LIMIT = 1 << 16
ZIP_MAX_COMMENT = (1 << 16) - 1
ZIP_STORED = 0
ZIP_DEFLATED = 8
ZIP_BZIP2 = 12
ZIP_LZMA = 14
DEFAULT_VERSION = 20
ZIP64_VERSION = 45
BZIP2_VERSION = 46
LZMA_VERSION = 63
MAX_EXTRACT_VERSION = 63
structEndArchive = b'<4s4H2LH'
stringEndArchive = b'PK\x05\x06'
sizeEndCentDir = struct.calcsize(structEndArchive)
_ECD_SIGNATURE = 0
_ECD_DISK_NUMBER = 1
_ECD_DISK_START = 2
_ECD_ENTRIES_THIS_DISK = 3
_ECD_ENTRIES_TOTAL = 4
_ECD_SIZE = 5
_ECD_OFFSET = 6
_ECD_COMMENT_SIZE = 7
_ECD_COMMENT = 8
_ECD_LOCATION = 9
structCentralDir = '<4s4B4HL2L5H2L'
stringCentralDir = b'PK\x01\x02'
sizeCentralDir = struct.calcsize(structCentralDir)
_CD_SIGNATURE = 0
_CD_CREATE_VERSION = 1
_CD_CREATE_SYSTEM = 2
_CD_EXTRACT_VERSION = 3
_CD_EXTRACT_SYSTEM = 4
_CD_FLAG_BITS = 5
_CD_COMPRESS_TYPE = 6
_CD_TIME = 7
_CD_DATE = 8
_CD_CRC = 9
_CD_COMPRESSED_SIZE = 10
_CD_UNCOMPRESSED_SIZE = 11
_CD_FILENAME_LENGTH = 12
_CD_EXTRA_FIELD_LENGTH = 13
_CD_COMMENT_LENGTH = 14
_CD_DISK_NUMBER_START = 15
_CD_INTERNAL_FILE_ATTRIBUTES = 16
_CD_EXTERNAL_FILE_ATTRIBUTES = 17
_CD_LOCAL_HEADER_OFFSET = 18
structFileHeader = '<4s2B4HL2L2H'
stringFileHeader = b'PK\x03\x04'
sizeFileHeader = struct.calcsize(structFileHeader)
_FH_SIGNATURE = 0
_FH_EXTRACT_VERSION = 1
_FH_EXTRACT_SYSTEM = 2
_FH_GENERAL_PURPOSE_FLAG_BITS = 3
_FH_COMPRESSION_METHOD = 4
_FH_LAST_MOD_TIME = 5
_FH_LAST_MOD_DATE = 6
_FH_CRC = 7
_FH_COMPRESSED_SIZE = 8
_FH_UNCOMPRESSED_SIZE = 9
_FH_FILENAME_LENGTH = 10
_FH_EXTRA_FIELD_LENGTH = 11
structEndArchive64Locator = '<4sLQL'
stringEndArchive64Locator = b'PK\x06\x07'
sizeEndCentDir64Locator = struct.calcsize(structEndArchive64Locator)
structEndArchive64 = '<4sQ2H2L4Q'
stringEndArchive64 = b'PK\x06\x06'
sizeEndCentDir64 = struct.calcsize(structEndArchive64)
_CD64_SIGNATURE = 0
_CD64_DIRECTORY_RECSIZE = 1
_CD64_CREATE_VERSION = 2
_CD64_EXTRACT_VERSION = 3
_CD64_DISK_NUMBER = 4
_CD64_DISK_NUMBER_START = 5
_CD64_NUMBER_ENTRIES_THIS_DISK = 6
_CD64_NUMBER_ENTRIES_TOTAL = 7
_CD64_DIRECTORY_SIZE = 8
_CD64_OFFSET_START_CENTDIR = 9

def _check_zipfile(fp):
    try:
        if _EndRecData(fp):
            return True
    except IOError:
        pass
    return False

def is_zipfile(filename):
    result = False
    try:
        if hasattr(filename, 'read'):
            result = _check_zipfile(fp=filename)
        else:
            with open(filename, 'rb') as fp:
                result = _check_zipfile(fp)
    except IOError:
        pass
    return result

def _EndRecData64(fpin, offset, endrec):
    try:
        fpin.seek(offset - sizeEndCentDir64Locator, 2)
    except IOError:
        return endrec
    data = fpin.read(sizeEndCentDir64Locator)
    if len(data) != sizeEndCentDir64Locator:
        return endrec
    (sig, diskno, reloff, disks) = struct.unpack(structEndArchive64Locator, data)
    if sig != stringEndArchive64Locator:
        return endrec
    if diskno != 0 or disks != 1:
        raise BadZipFile('zipfiles that span multiple disks are not supported')
    fpin.seek(offset - sizeEndCentDir64Locator - sizeEndCentDir64, 2)
    data = fpin.read(sizeEndCentDir64)
    if len(data) != sizeEndCentDir64:
        return endrec
    (sig, sz, create_version, read_version, disk_num, disk_dir, dircount, dircount2, dirsize, diroffset) = struct.unpack(structEndArchive64, data)
    if sig != stringEndArchive64:
        return endrec
    endrec[_ECD_SIGNATURE] = sig
    endrec[_ECD_DISK_NUMBER] = disk_num
    endrec[_ECD_DISK_START] = disk_dir
    endrec[_ECD_ENTRIES_THIS_DISK] = dircount
    endrec[_ECD_ENTRIES_TOTAL] = dircount2
    endrec[_ECD_SIZE] = dirsize
    endrec[_ECD_OFFSET] = diroffset
    return endrec

def _EndRecData(fpin):
    fpin.seek(0, 2)
    filesize = fpin.tell()
    try:
        fpin.seek(-sizeEndCentDir, 2)
    except IOError:
        return
    data = fpin.read()
    if len(data) == sizeEndCentDir and data[0:4] == stringEndArchive and data[-2:] == b'\x00\x00':
        endrec = struct.unpack(structEndArchive, data)
        endrec = list(endrec)
        endrec.append(b'')
        endrec.append(filesize - sizeEndCentDir)
        return _EndRecData64(fpin, -sizeEndCentDir, endrec)
    maxCommentStart = max(filesize - 65536 - sizeEndCentDir, 0)
    fpin.seek(maxCommentStart, 0)
    data = fpin.read()
    start = data.rfind(stringEndArchive)
    if start >= 0:
        recData = data[start:start + sizeEndCentDir]
        if len(recData) != sizeEndCentDir:
            return
        endrec = list(struct.unpack(structEndArchive, recData))
        commentSize = endrec[_ECD_COMMENT_SIZE]
        comment = data[start + sizeEndCentDir:start + sizeEndCentDir + commentSize]
        endrec.append(comment)
        endrec.append(maxCommentStart + start)
        return _EndRecData64(fpin, maxCommentStart + start - filesize, endrec)

class ZipInfo(object):
    __qualname__ = 'ZipInfo'
    __slots__ = ('orig_filename', 'filename', 'date_time', 'compress_type', 'comment', 'extra', 'create_system', 'create_version', 'extract_version', 'reserved', 'flag_bits', 'volume', 'internal_attr', 'external_attr', 'header_offset', 'CRC', 'compress_size', 'file_size', '_raw_time')

    def __init__(self, filename='NoName', date_time=(1980, 1, 1, 0, 0, 0)):
        self.orig_filename = filename
        null_byte = filename.find(chr(0))
        if null_byte >= 0:
            filename = filename[0:null_byte]
        if os.sep != '/' and os.sep in filename:
            filename = filename.replace(os.sep, '/')
        self.filename = filename
        self.date_time = date_time
        if date_time[0] < 1980:
            raise ValueError('ZIP does not support timestamps before 1980')
        self.compress_type = ZIP_STORED
        self.comment = b''
        self.extra = b''
        if sys.platform == 'win32':
            self.create_system = 0
        else:
            self.create_system = 3
        self.create_version = DEFAULT_VERSION
        self.extract_version = DEFAULT_VERSION
        self.reserved = 0
        self.flag_bits = 0
        self.volume = 0
        self.internal_attr = 0
        self.external_attr = 0

    def FileHeader(self, zip64=None):
        dt = self.date_time
        dosdate = dt[0] - 1980 << 9 | dt[1] << 5 | dt[2]
        dostime = dt[3] << 11 | dt[4] << 5 | dt[5]//2
        if self.flag_bits & 8:
            CRC = compress_size = file_size = 0
        else:
            CRC = self.CRC
            compress_size = self.compress_size
            file_size = self.file_size
        extra = self.extra
        min_version = 0
        if zip64 is None:
            zip64 = file_size > ZIP64_LIMIT or compress_size > ZIP64_LIMIT
        if zip64:
            fmt = '<HHQQ'
            extra = extra + struct.pack(fmt, 1, struct.calcsize(fmt) - 4, file_size, compress_size)
        if file_size > ZIP64_LIMIT or compress_size > ZIP64_LIMIT:
            if not zip64:
                raise LargeZipFile('Filesize would require ZIP64 extensions')
            file_size = 4294967295
            compress_size = 4294967295
            min_version = ZIP64_VERSION
        if self.compress_type == ZIP_BZIP2:
            min_version = max(BZIP2_VERSION, min_version)
        elif self.compress_type == ZIP_LZMA:
            min_version = max(LZMA_VERSION, min_version)
        self.extract_version = max(min_version, self.extract_version)
        self.create_version = max(min_version, self.create_version)
        (filename, flag_bits) = self._encodeFilenameFlags()
        header = struct.pack(structFileHeader, stringFileHeader, self.extract_version, self.reserved, flag_bits, self.compress_type, dostime, dosdate, CRC, compress_size, file_size, len(filename), len(extra))
        return header + filename + extra

    def _encodeFilenameFlags(self):
        try:
            return (self.filename.encode('ascii'), self.flag_bits)
        except UnicodeEncodeError:
            return (self.filename.encode('utf-8'), self.flag_bits | 2048)

    def _decodeExtra(self):
        extra = self.extra
        unpack = struct.unpack
        while extra:
            (tp, ln) = unpack('<HH', extra[:4])
            if ln >= 24:
                counts = unpack('<QQQ', extra[4:28])
            elif ln == 16:
                counts = unpack('<QQ', extra[4:20])
            elif ln == 8:
                counts = unpack('<Q', extra[4:12])
            elif ln == 0:
                counts = ()
            else:
                raise RuntimeError('Corrupt extra field %s' % (ln,))
            idx = 0
            if self.file_size in (18446744073709551615, 4294967295):
                self.file_size = counts[idx]
                idx += 1
            if self.compress_size == 4294967295:
                self.compress_size = counts[idx]
                idx += 1
            if tp == 1 and self.header_offset == 4294967295:
                old = self.header_offset
                self.header_offset = counts[idx]
                idx += 1
            extra = extra[ln + 4:]

class _ZipDecrypter:
    __qualname__ = '_ZipDecrypter'

    def _GenerateCRCTable():
        poly = 3988292384
        table = [0]*256
        for i in range(256):
            crc = i
            for j in range(8):
                if crc & 1:
                    crc = crc >> 1 & 2147483647 ^ poly
                else:
                    crc = crc >> 1 & 2147483647
            table[i] = crc
        return table

    crctable = _GenerateCRCTable()

    def _crc32(self, ch, crc):
        return crc >> 8 & 16777215 ^ self.crctable[(crc ^ ch) & 255]

    def __init__(self, pwd):
        self.key0 = 305419896
        self.key1 = 591751049
        self.key2 = 878082192
        for p in pwd:
            self._UpdateKeys(p)

    def _UpdateKeys(self, c):
        self.key0 = self._crc32(c, self.key0)
        self.key1 = self.key1 + (self.key0 & 255) & 4294967295
        self.key1 = self.key1*134775813 + 1 & 4294967295
        self.key2 = self._crc32(self.key1 >> 24 & 255, self.key2)

    def __call__(self, c):
        k = self.key2 | 2
        c = c ^ k*(k ^ 1) >> 8 & 255
        self._UpdateKeys(c)
        return c

class LZMACompressor:
    __qualname__ = 'LZMACompressor'

    def __init__(self):
        self._comp = None

    def _init(self):
        props = lzma._encode_filter_properties({'id': lzma.FILTER_LZMA1})
        self._comp = lzma.LZMACompressor(lzma.FORMAT_RAW, filters=[lzma._decode_filter_properties(lzma.FILTER_LZMA1, props)])
        return struct.pack('<BBH', 9, 4, len(props)) + props

    def compress(self, data):
        if self._comp is None:
            return self._init() + self._comp.compress(data)
        return self._comp.compress(data)

    def flush(self):
        if self._comp is None:
            return self._init() + self._comp.flush()
        return self._comp.flush()

class LZMADecompressor:
    __qualname__ = 'LZMADecompressor'

    def __init__(self):
        self._decomp = None
        self._unconsumed = b''
        self.eof = False

    def decompress(self, data):
        if self._decomp is None:
            if len(self._unconsumed) <= 4:
                return b''
            (psize,) = struct.unpack('<H', self._unconsumed[2:4])
            if len(self._unconsumed) <= 4 + psize:
                return b''
            self._decomp = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[lzma._decode_filter_properties(lzma.FILTER_LZMA1, self._unconsumed[4:4 + psize])])
            data = self._unconsumed[4 + psize:]
            del self._unconsumed
        result = self._decomp.decompress(data)
        self.eof = self._decomp.eof
        return result

compressor_names = {0: 'store', 1: 'shrink', 2: 'reduce', 3: 'reduce', 4: 'reduce', 5: 'reduce', 6: 'implode', 7: 'tokenize', 8: 'deflate', 9: 'deflate64', 10: 'implode', 12: 'bzip2', 14: 'lzma', 18: 'terse', 19: 'lz77', 97: 'wavpack', 98: 'ppmd'}

def _check_compression(compression):
    if compression == ZIP_STORED:
        pass
    elif compression == ZIP_DEFLATED:
        if not zlib:
            raise RuntimeError('Compression requires the (missing) zlib module')
    elif compression == ZIP_BZIP2:
        if not bz2:
            raise RuntimeError('Compression requires the (missing) bz2 module')
    elif compression == ZIP_LZMA:
        if not lzma:
            raise RuntimeError('Compression requires the (missing) lzma module')
    else:
        raise RuntimeError('That compression method is not supported')

def _get_compressor(compress_type):
    if compress_type == ZIP_DEFLATED:
        return zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
    if compress_type == ZIP_BZIP2:
        return bz2.BZ2Compressor()
    if compress_type == ZIP_LZMA:
        return LZMACompressor()
    return

def _get_decompressor(compress_type):
    if compress_type == ZIP_STORED:
        return
    if compress_type == ZIP_DEFLATED:
        return zlib.decompressobj(-15)
    if compress_type == ZIP_BZIP2:
        return bz2.BZ2Decompressor()
    if compress_type == ZIP_LZMA:
        return LZMADecompressor()
    descr = compressor_names.get(compress_type)
    if descr:
        raise NotImplementedError('compression type %d (%s)' % (compress_type, descr))
    else:
        raise NotImplementedError('compression type %d' % (compress_type,))

class ZipExtFile(io.BufferedIOBase):
    __qualname__ = 'ZipExtFile'
    MAX_N = 1073741824
    MIN_READ_SIZE = 4096
    PATTERN = re.compile(b'^(?P<chunk>[^\\r\\n]+)|(?P<newline>\\n|\\r\\n?)')

    def __init__(self, fileobj, mode, zipinfo, decrypter=None, close_fileobj=False):
        self._fileobj = fileobj
        self._decrypter = decrypter
        self._close_fileobj = close_fileobj
        self._compress_type = zipinfo.compress_type
        self._compress_left = zipinfo.compress_size
        self._left = zipinfo.file_size
        self._decompressor = _get_decompressor(self._compress_type)
        self._eof = False
        self._readbuffer = b''
        self._offset = 0
        self._universal = 'U' in mode
        self.newlines = None
        if self._decrypter is not None:
            pass
        self.mode = mode
        self.name = zipinfo.filename
        if hasattr(zipinfo, 'CRC'):
            self._expected_crc = zipinfo.CRC
            self._running_crc = crc32(b'') & 4294967295
        else:
            self._expected_crc = None

    def readline(self, limit=-1):
        if not self._universal and limit < 0:
            i = self._readbuffer.find(b'\n', self._offset) + 1
            if i > 0:
                line = self._readbuffer[self._offset:i]
                self._offset = i
                return line
        if not self._universal:
            return io.BufferedIOBase.readline(self, limit)
        line = b''
        while not limit < 0:
            while len(line) < limit:
                readahead = self.peek(2)
                if readahead == b'':
                    return line
                match = self.PATTERN.search(readahead)
                newline = match.group('newline')
                if newline is not None:
                    if self.newlines is None:
                        self.newlines = []
                    if newline not in self.newlines:
                        self.newlines.append(newline)
                    return line + b'\n'
                chunk = match.group('chunk')
                if limit >= 0:
                    chunk = chunk[:limit - len(line)]
                line += chunk
        return line

    def peek(self, n=1):
        if n > len(self._readbuffer) - self._offset:
            chunk = self.read(n)
            if len(chunk) > self._offset:
                self._readbuffer = chunk + self._readbuffer[self._offset:]
                self._offset = 0
        return self._readbuffer[self._offset:self._offset + 512]

    def readable(self):
        return True

    def read(self, n=-1):
        if n is None or n < 0:
            buf = self._readbuffer[self._offset:]
            self._readbuffer = b''
            self._offset = 0
            while not self._eof:
                buf += self._read1(self.MAX_N)
            return buf
        end = n + self._offset
        if end < len(self._readbuffer):
            buf = self._readbuffer[self._offset:end]
            self._offset = end
            return buf
        n = end - len(self._readbuffer)
        buf = self._readbuffer[self._offset:]
        self._readbuffer = b''
        self._offset = 0
        while n > 0:
            while not self._eof:
                data = self._read1(n)
                if n < len(data):
                    self._readbuffer = data
                    self._offset = n
                    buf += data[:n]
                    break
                buf += data
                n -= len(data)
        return buf

    def _update_crc(self, newdata):
        if self._expected_crc is None:
            return
        self._running_crc = crc32(newdata, self._running_crc) & 4294967295
        if self._eof and self._running_crc != self._expected_crc:
            raise BadZipFile('Bad CRC-32 for file %r' % self.name)

    def read1(self, n):
        if n is None or n < 0:
            buf = self._readbuffer[self._offset:]
            self._readbuffer = b''
            self._offset = 0
            while not self._eof:
                data = self._read1(self.MAX_N)
                while data:
                    buf += data
                    break
                    continue
            return buf
        end = n + self._offset
        if end < len(self._readbuffer):
            buf = self._readbuffer[self._offset:end]
            self._offset = end
            return buf
        n = end - len(self._readbuffer)
        buf = self._readbuffer[self._offset:]
        self._readbuffer = b''
        self._offset = 0
        if n > 0:
            while not self._eof:
                data = self._read1(n)
                if n < len(data):
                    self._readbuffer = data
                    self._offset = n
                    buf += data[:n]
                    break
                #ERROR: Unexpected statement:   372 POP_BLOCK  |   373 JUMP_FORWARD 

                if data:
                    buf += data
                    break
                    continue
                    continue
                continue
        return buf

    def _read1(self, n):
        if self._eof or n <= 0:
            return b''
        if self._compress_type == ZIP_DEFLATED:
            data = self._decompressor.unconsumed_tail
            data += self._read2(n - len(data))
        else:
            data = self._read2(n)
        if self._compress_type == ZIP_STORED:
            self._eof = self._compress_left <= 0
        elif self._compress_type == ZIP_DEFLATED:
            n = max(n, self.MIN_READ_SIZE)
            data = self._decompressor.decompress(data, n)
            self._eof = self._decompressor.eof or self._compress_left <= 0 and not self._decompressor.unconsumed_tail
            data += self._decompressor.flush()
        else:
            data = self._decompressor.decompress(data)
            self._eof = self._decompressor.eof or self._compress_left <= 0
        data = data[:self._left]
        if self._left <= 0:
            self._eof = True
        self._update_crc(data)
        return data

    def _read2(self, n):
        if self._compress_left <= 0:
            return b''
        n = max(n, self.MIN_READ_SIZE)
        n = min(n, self._compress_left)
        data = self._fileobj.read(n)
        if not data:
            raise EOFError
        if self._decrypter is not None:
            data = bytes(map(self._decrypter, data))
        return data

    def close(self):
        try:
            while self._close_fileobj:
                self._fileobj.close()
        finally:
            super().close()

class ZipFile:
    __qualname__ = 'ZipFile'
    fp = None
    _windows_illegal_name_trans_table = None

    def __init__(self, file, mode='r', compression=ZIP_STORED, allowZip64=False):
        if mode not in ('r', 'w', 'a'):
            raise RuntimeError('ZipFile() requires mode "r", "w", or "a"')
        _check_compression(compression)
        self._allowZip64 = allowZip64
        self._didModify = False
        self.debug = 0
        self.NameToInfo = {}
        self.filelist = []
        self.compression = compression
        self.mode = key = mode.replace('b', '')[0]
        self.pwd = None
        self._comment = b''
        if isinstance(file, str):
            self._filePassed = 0
            self.filename = file
            modeDict = {'r': 'rb', 'w': 'wb', 'a': 'r+b'}
            try:
                self.fp = io.open(file, modeDict[mode])
            except IOError:
                if mode == 'a':
                    mode = key = 'w'
                    self.fp = io.open(file, modeDict[mode])
                else:
                    raise
        else:
            self._filePassed = 1
            self.fp = file
            self.filename = getattr(file, 'name', None)
        try:
            if key == 'r':
                self._RealGetContents()
            elif key == 'w':
                self._didModify = True
            elif key == 'a':
                try:
                    self._RealGetContents()
                    self.fp.seek(self.start_dir, 0)
                except BadZipFile:
                    self.fp.seek(0, 2)
                    self._didModify = True
            else:
                raise RuntimeError('Mode must be "r", "w" or "a"')
        except:
            fp = self.fp
            self.fp = None
            if not self._filePassed:
                fp.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    def _RealGetContents(self):
        fp = self.fp
        try:
            endrec = _EndRecData(fp)
        except IOError:
            raise BadZipFile('File is not a zip file')
        if not endrec:
            raise BadZipFile('File is not a zip file')
        if self.debug > 1:
            print(endrec)
        size_cd = endrec[_ECD_SIZE]
        offset_cd = endrec[_ECD_OFFSET]
        self._comment = endrec[_ECD_COMMENT]
        concat = endrec[_ECD_LOCATION] - size_cd - offset_cd
        if endrec[_ECD_SIGNATURE] == stringEndArchive64:
            concat -= sizeEndCentDir64 + sizeEndCentDir64Locator
        if self.debug > 2:
            inferred = concat + offset_cd
            print('given, inferred, offset', offset_cd, inferred, concat)
        self.start_dir = offset_cd + concat
        fp.seek(self.start_dir, 0)
        data = fp.read(size_cd)
        fp = io.BytesIO(data)
        total = 0
        while total < size_cd:
            centdir = fp.read(sizeCentralDir)
            if len(centdir) != sizeCentralDir:
                raise BadZipFile('Truncated central directory')
            centdir = struct.unpack(structCentralDir, centdir)
            if centdir[_CD_SIGNATURE] != stringCentralDir:
                raise BadZipFile('Bad magic number for central directory')
            if self.debug > 2:
                print(centdir)
            filename = fp.read(centdir[_CD_FILENAME_LENGTH])
            flags = centdir[5]
            if flags & 2048:
                filename = filename.decode('utf-8')
            else:
                filename = filename.decode('cp437')
            x = ZipInfo(filename)
            x.extra = fp.read(centdir[_CD_EXTRA_FIELD_LENGTH])
            x.comment = fp.read(centdir[_CD_COMMENT_LENGTH])
            x.header_offset = centdir[_CD_LOCAL_HEADER_OFFSET]
            (x.create_version, x.create_system, x.extract_version, x.reserved, x.flag_bits, x.compress_type, t, d, x.CRC, x.compress_size, x.file_size) = centdir[1:12]
            if x.extract_version > MAX_EXTRACT_VERSION:
                raise NotImplementedError('zip file version %.1f' % (x.extract_version/10))
            (x.volume, x.internal_attr, x.external_attr) = centdir[15:18]
            x._raw_time = t
            x.date_time = ((d >> 9) + 1980, d >> 5 & 15, d & 31, t >> 11, t >> 5 & 63, (t & 31)*2)
            x._decodeExtra()
            x.header_offset = x.header_offset + concat
            self.filelist.append(x)
            self.NameToInfo[x.filename] = x
            total = total + sizeCentralDir + centdir[_CD_FILENAME_LENGTH] + centdir[_CD_EXTRA_FIELD_LENGTH] + centdir[_CD_COMMENT_LENGTH]
            while self.debug > 2:
                print('total', total)
                continue

    def namelist(self):
        return [data.filename for data in self.filelist]

    def infolist(self):
        return self.filelist

    def printdir(self, file=None):
        print('%-46s %19s %12s' % ('File Name', 'Modified    ', 'Size'), file=file)
        for zinfo in self.filelist:
            date = '%d-%02d-%02d %02d:%02d:%02d' % zinfo.date_time[:6]
            print('%-46s %s %12d' % (zinfo.filename, date, zinfo.file_size), file=file)

    def testzip(self):
        chunk_size = 1048576
        for zinfo in self.filelist:
            try:
                with self.open(zinfo.filename, 'r') as f:
                    while f.read(chunk_size):
                        pass
            except BadZipFile:
                return zinfo.filename

    def getinfo(self, name):
        info = self.NameToInfo.get(name)
        if info is None:
            raise KeyError('There is no item named %r in the archive' % name)
        return info

    def setpassword(self, pwd):
        if pwd and not isinstance(pwd, bytes):
            raise TypeError('pwd: expected bytes, got %s' % type(pwd))
        if pwd:
            self.pwd = pwd
        else:
            self.pwd = None

    @property
    def comment(self):
        return self._comment

    @comment.setter
    def comment(self, comment):
        if not isinstance(comment, bytes):
            raise TypeError('comment: expected bytes, got %s' % type(comment))
        if len(comment) > ZIP_MAX_COMMENT:
            import warnings
            warnings.warn('Archive comment is too long; truncating to %d bytes' % ZIP_MAX_COMMENT, stacklevel=2)
            comment = comment[:ZIP_MAX_COMMENT]
        self._comment = comment
        self._didModify = True

    def read(self, name, pwd=None):
        with self.open(name, 'r', pwd) as fp:
            return fp.read()

    def open(self, name, mode='r', pwd=None):
        if mode not in ('r', 'U', 'rU'):
            raise RuntimeError('open() requires mode "r", "U", or "rU"')
        if pwd and not isinstance(pwd, bytes):
            raise TypeError('pwd: expected bytes, got %s' % type(pwd))
        if not self.fp:
            raise RuntimeError('Attempt to read ZIP archive that was already closed')
        if self._filePassed:
            zef_file = self.fp
        else:
            zef_file = io.open(self.filename, 'rb')
        try:
            if isinstance(name, ZipInfo):
                zinfo = name
            else:
                zinfo = self.getinfo(name)
            zef_file.seek(zinfo.header_offset, 0)
            fheader = zef_file.read(sizeFileHeader)
            if len(fheader) != sizeFileHeader:
                raise BadZipFile('Truncated file header')
            fheader = struct.unpack(structFileHeader, fheader)
            if fheader[_FH_SIGNATURE] != stringFileHeader:
                raise BadZipFile('Bad magic number for file header')
            fname = zef_file.read(fheader[_FH_FILENAME_LENGTH])
            if fheader[_FH_EXTRA_FIELD_LENGTH]:
                zef_file.read(fheader[_FH_EXTRA_FIELD_LENGTH])
            if zinfo.flag_bits & 32:
                raise NotImplementedError('compressed patched data (flag bit 5)')
            if zinfo.flag_bits & 64:
                raise NotImplementedError('strong encryption (flag bit 6)')
            if zinfo.flag_bits & 2048:
                fname_str = fname.decode('utf-8')
            else:
                fname_str = fname.decode('cp437')
            if fname_str != zinfo.orig_filename:
                raise BadZipFile('File name in directory %r and header %r differ.' % (zinfo.orig_filename, fname))
            is_encrypted = zinfo.flag_bits & 1
            zd = None
            if not pwd:
                pwd = self.pwd
            if not pwd:
                raise RuntimeError('File %s is encrypted, password required for extraction' % name)
            zd = _ZipDecrypter(pwd)
            header = zef_file.read(12)
            h = list(map(zd, header[0:12]))
            if zinfo.flag_bits & 8:
                check_byte = zinfo._raw_time >> 8 & 255
            else:
                check_byte = zinfo.CRC >> 24 & 255
            if is_encrypted and h[11] != check_byte:
                raise RuntimeError('Bad password for file', name)
            return ZipExtFile(zef_file, mode, zinfo, zd, close_fileobj=not self._filePassed)
        except:
            if not self._filePassed:
                zef_file.close()
            raise

    def extract(self, member, path=None, pwd=None):
        if not isinstance(member, ZipInfo):
            member = self.getinfo(member)
        if path is None:
            path = os.getcwd()
        return self._extract_member(member, path, pwd)

    def extractall(self, path=None, members=None, pwd=None):
        if members is None:
            members = self.namelist()
        for zipinfo in members:
            self.extract(zipinfo, path, pwd)

    @classmethod
    def _sanitize_windows_name(cls, arcname, pathsep):
        table = cls._windows_illegal_name_trans_table
        if not table:
            illegal = ':<>|"?*'
            table = str.maketrans(illegal, '_'*len(illegal))
            cls._windows_illegal_name_trans_table = table
        arcname = arcname.translate(table)
        arcname = (x.rstrip('.') for x in arcname.split(pathsep))
        arcname = pathsep.join(x for x in arcname if x)
        return arcname

    def _extract_member(self, member, targetpath, pwd):
        arcname = member.filename.replace('/', os.path.sep)
        if os.path.altsep:
            arcname = arcname.replace(os.path.altsep, os.path.sep)
        arcname = os.path.splitdrive(arcname)[1]
        invalid_path_parts = ('', os.path.curdir, os.path.pardir)
        arcname = os.path.sep.join(x for x in arcname.split(os.path.sep) if x not in invalid_path_parts)
        if os.path.sep == '\\':
            arcname = self._sanitize_windows_name(arcname, os.path.sep)
        targetpath = os.path.join(targetpath, arcname)
        targetpath = os.path.normpath(targetpath)
        upperdirs = os.path.dirname(targetpath)
        if upperdirs and not os.path.exists(upperdirs):
            os.makedirs(upperdirs)
        if member.filename[-1] == '/':
            if not os.path.isdir(targetpath):
                os.mkdir(targetpath)
            return targetpath
        with self.open(member, pwd=pwd) as source, open(targetpath, 'wb') as target:
            shutil.copyfileobj(source, target)
        return targetpath

    def _writecheck(self, zinfo):
        if zinfo.filename in self.NameToInfo:
            import warnings
            warnings.warn('Duplicate name: %r' % zinfo.filename, stacklevel=3)
        if self.mode not in ('w', 'a'):
            raise RuntimeError('write() requires mode "w" or "a"')
        if not self.fp:
            raise RuntimeError('Attempt to write ZIP archive that was already closed')
        _check_compression(zinfo.compress_type)
        if not (zinfo.file_size > ZIP64_LIMIT and self._allowZip64):
            raise LargeZipFile('Filesize would require ZIP64 extensions')
        if not (zinfo.header_offset > ZIP64_LIMIT and self._allowZip64):
            raise LargeZipFile('Zipfile size would require ZIP64 extensions')

    def write(self, filename, arcname=None, compress_type=None):
        if not self.fp:
            raise RuntimeError('Attempt to write to ZIP archive that was already closed')
        st = os.stat(filename)
        isdir = stat.S_ISDIR(st.st_mode)
        mtime = time.localtime(st.st_mtime)
        date_time = mtime[0:6]
        if arcname is None:
            arcname = filename
        arcname = os.path.normpath(os.path.splitdrive(arcname)[1])
        while arcname[0] in (os.sep, os.altsep):
            arcname = arcname[1:]
        if isdir:
            arcname += '/'
        zinfo = ZipInfo(arcname, date_time)
        zinfo.external_attr = (st[0] & 65535) << 16
        if compress_type is None:
            zinfo.compress_type = self.compression
        else:
            zinfo.compress_type = compress_type
        zinfo.file_size = st.st_size
        zinfo.flag_bits = 0
        zinfo.header_offset = self.fp.tell()
        if zinfo.compress_type == ZIP_LZMA:
            pass
        self._writecheck(zinfo)
        self._didModify = True
        if isdir:
            zinfo.file_size = 0
            zinfo.compress_size = 0
            zinfo.CRC = 0
            self.filelist.append(zinfo)
            self.NameToInfo[zinfo.filename] = zinfo
            self.fp.write(zinfo.FileHeader(False))
            return
        cmpr = _get_compressor(zinfo.compress_type)
        with open(filename, 'rb') as fp:
            zinfo.CRC = CRC = 0
            zinfo.compress_size = compress_size = 0
            zip64 = self._allowZip64 and zinfo.file_size*1.05 > ZIP64_LIMIT
            self.fp.write(zinfo.FileHeader(zip64))
            file_size = 0
            while True:
                buf = fp.read(8192)
                if not buf:
                    break
                file_size = file_size + len(buf)
                CRC = crc32(buf, CRC) & 4294967295
                if cmpr:
                    buf = cmpr.compress(buf)
                    compress_size = compress_size + len(buf)
                self.fp.write(buf)
        if cmpr:
            buf = cmpr.flush()
            compress_size = compress_size + len(buf)
            self.fp.write(buf)
            zinfo.compress_size = compress_size
        else:
            zinfo.compress_size = file_size
        zinfo.CRC = CRC
        zinfo.file_size = file_size
        if file_size > ZIP64_LIMIT:
            raise RuntimeError('File size has increased during compressing')
        if not zip64 and self._allowZip64 and compress_size > ZIP64_LIMIT:
            raise RuntimeError('Compressed size larger than uncompressed size')
        position = self.fp.tell()
        self.fp.seek(zinfo.header_offset, 0)
        self.fp.write(zinfo.FileHeader(zip64))
        self.fp.seek(position, 0)
        self.filelist.append(zinfo)
        self.NameToInfo[zinfo.filename] = zinfo

    def writestr(self, zinfo_or_arcname, data, compress_type=None):
        if isinstance(data, str):
            data = data.encode('utf-8')
        if not isinstance(zinfo_or_arcname, ZipInfo):
            zinfo = ZipInfo(filename=zinfo_or_arcname, date_time=time.localtime(time.time())[:6])
            zinfo.compress_type = self.compression
            zinfo.external_attr = 25165824
        else:
            zinfo = zinfo_or_arcname
        if not self.fp:
            raise RuntimeError('Attempt to write to ZIP archive that was already closed')
        zinfo.file_size = len(data)
        zinfo.header_offset = self.fp.tell()
        if compress_type is not None:
            zinfo.compress_type = compress_type
        if zinfo.compress_type == ZIP_LZMA:
            pass
        self._writecheck(zinfo)
        self._didModify = True
        zinfo.CRC = crc32(data) & 4294967295
        co = _get_compressor(zinfo.compress_type)
        if co:
            data = co.compress(data) + co.flush()
            zinfo.compress_size = len(data)
        else:
            zinfo.compress_size = zinfo.file_size
        zip64 = zinfo.file_size > ZIP64_LIMIT or zinfo.compress_size > ZIP64_LIMIT
        if zip64 and not self._allowZip64:
            raise LargeZipFile('Filesize would require ZIP64 extensions')
        self.fp.write(zinfo.FileHeader(zip64))
        self.fp.write(data)
        if zinfo.flag_bits & 8:
            fmt = '<LQQ' if zip64 else '<LLL'
            self.fp.write(struct.pack(fmt, zinfo.CRC, zinfo.compress_size, zinfo.file_size))
        self.fp.flush()
        self.filelist.append(zinfo)
        self.NameToInfo[zinfo.filename] = zinfo

    def __del__(self):
        self.close()

    def close(self):
        if self.fp is None:
            return
        try:
            while self.mode in ('w', 'a') and self._didModify:
                count = 0
                pos1 = self.fp.tell()
                for zinfo in self.filelist:
                    count = count + 1
                    dt = zinfo.date_time
                    dosdate = dt[0] - 1980 << 9 | dt[1] << 5 | dt[2]
                    dostime = dt[3] << 11 | dt[4] << 5 | dt[5]//2
                    extra = []
                    if zinfo.file_size > ZIP64_LIMIT or zinfo.compress_size > ZIP64_LIMIT:
                        extra.append(zinfo.file_size)
                        extra.append(zinfo.compress_size)
                        file_size = 4294967295
                        compress_size = 4294967295
                    else:
                        file_size = zinfo.file_size
                        compress_size = zinfo.compress_size
                    if zinfo.header_offset > ZIP64_LIMIT:
                        extra.append(zinfo.header_offset)
                        header_offset = 4294967295
                    else:
                        header_offset = zinfo.header_offset
                    extra_data = zinfo.extra
                    min_version = 0
                    if extra:
                        extra_data = struct.pack('<HH' + 'Q'*len(extra), 1, 8*len(extra), *extra) + extra_data
                        min_version = ZIP64_VERSION
                    if zinfo.compress_type == ZIP_BZIP2:
                        min_version = max(BZIP2_VERSION, min_version)
                    elif zinfo.compress_type == ZIP_LZMA:
                        min_version = max(LZMA_VERSION, min_version)
                    extract_version = max(min_version, zinfo.extract_version)
                    create_version = max(min_version, zinfo.create_version)
                    try:
                        (filename, flag_bits) = zinfo._encodeFilenameFlags()
                        centdir = struct.pack(structCentralDir, stringCentralDir, create_version, zinfo.create_system, extract_version, zinfo.reserved, flag_bits, zinfo.compress_type, dostime, dosdate, zinfo.CRC, compress_size, file_size, len(filename), len(extra_data), len(zinfo.comment), 0, zinfo.internal_attr, zinfo.external_attr, header_offset)
                    except DeprecationWarning:
                        print((structCentralDir, stringCentralDir, create_version, zinfo.create_system, extract_version, zinfo.reserved, zinfo.flag_bits, zinfo.compress_type, dostime, dosdate, zinfo.CRC, compress_size, file_size, len(zinfo.filename), len(extra_data), len(zinfo.comment), 0, zinfo.internal_attr, zinfo.external_attr, header_offset), file=sys.stderr)
                        raise
                    self.fp.write(centdir)
                    self.fp.write(filename)
                    self.fp.write(extra_data)
                    self.fp.write(zinfo.comment)
                pos2 = self.fp.tell()
                centDirCount = count
                centDirSize = pos2 - pos1
                centDirOffset = pos1
                if centDirCount >= ZIP_FILECOUNT_LIMIT or centDirOffset > ZIP64_LIMIT or centDirSize > ZIP64_LIMIT:
                    zip64endrec = struct.pack(structEndArchive64, stringEndArchive64, 44, 45, 45, 0, 0, centDirCount, centDirCount, centDirSize, centDirOffset)
                    self.fp.write(zip64endrec)
                    zip64locrec = struct.pack(structEndArchive64Locator, stringEndArchive64Locator, 0, pos2, 1)
                    self.fp.write(zip64locrec)
                    centDirCount = min(centDirCount, 65535)
                    centDirSize = min(centDirSize, 4294967295)
                    centDirOffset = min(centDirOffset, 4294967295)
                endrec = struct.pack(structEndArchive, stringEndArchive, 0, 0, centDirCount, centDirCount, centDirSize, centDirOffset, len(self._comment))
                self.fp.write(endrec)
                self.fp.write(self._comment)
                self.fp.flush()
        finally:
            fp = self.fp
            self.fp = None
            if not self._filePassed:
                fp.close()

class PyZipFile(ZipFile):
    __qualname__ = 'PyZipFile'

    def __init__(self, file, mode='r', compression=ZIP_STORED, allowZip64=False, optimize=-1):
        ZipFile.__init__(self, file, mode=mode, compression=compression, allowZip64=allowZip64)
        self._optimize = optimize

    def writepy(self, pathname, basename=''):
        (dir, name) = os.path.split(pathname)
        if os.path.isdir(pathname):
            initname = os.path.join(pathname, '__init__.py')
            if os.path.isfile(initname):
                if basename:
                    basename = '%s/%s' % (basename, name)
                else:
                    basename = name
                if self.debug:
                    print('Adding package in', pathname, 'as', basename)
                (fname, arcname) = self._get_codename(initname[0:-3], basename)
                if self.debug:
                    print('Adding', arcname)
                self.write(fname, arcname)
                dirlist = os.listdir(pathname)
                dirlist.remove('__init__.py')
                for filename in dirlist:
                    path = os.path.join(pathname, filename)
                    (root, ext) = os.path.splitext(filename)
                    if os.path.isdir(path):
                        if os.path.isfile(os.path.join(path, '__init__.py')):
                            self.writepy(path, basename)
                            while ext == '.py':
                                (fname, arcname) = self._get_codename(path[0:-3], basename)
                                if self.debug:
                                    print('Adding', arcname)
                                self.write(fname, arcname)
                    else:
                        while ext == '.py':
                            (fname, arcname) = self._get_codename(path[0:-3], basename)
                            if self.debug:
                                print('Adding', arcname)
                            self.write(fname, arcname)
            else:
                if self.debug:
                    print('Adding files from directory', pathname)
                for filename in os.listdir(pathname):
                    path = os.path.join(pathname, filename)
                    (root, ext) = os.path.splitext(filename)
                    while ext == '.py':
                        (fname, arcname) = self._get_codename(path[0:-3], basename)
                        if self.debug:
                            print('Adding', arcname)
                        self.write(fname, arcname)
        else:
            if pathname[-3:] != '.py':
                raise RuntimeError('Files added with writepy() must end with ".py"')
            (fname, arcname) = self._get_codename(pathname[0:-3], basename)
            if self.debug:
                print('Adding file', arcname)
            self.write(fname, arcname)

    def _get_codename(self, pathname, basename):

        def _compile(file, optimize=-1):
            import py_compile
            if self.debug:
                print('Compiling', file)
            try:
                py_compile.compile(file, doraise=True, optimize=optimize)
            except py_compile.PyCompileError as err:
                print(err.msg)
                return False
            return True

        file_py = pathname + '.py'
        file_pyc = pathname + '.pyc'
        file_pyo = pathname + '.pyo'
        pycache_pyc = imp.cache_from_source(file_py, True)
        pycache_pyo = imp.cache_from_source(file_py, False)
        if self._optimize == -1:
            if os.path.isfile(file_pyo) and os.stat(file_pyo).st_mtime >= os.stat(file_py).st_mtime:
                arcname = fname = file_pyo
            elif os.path.isfile(file_pyc) and os.stat(file_pyc).st_mtime >= os.stat(file_py).st_mtime:
                arcname = fname = file_pyc
            elif os.path.isfile(pycache_pyc) and os.stat(pycache_pyc).st_mtime >= os.stat(file_py).st_mtime:
                fname = pycache_pyc
                arcname = file_pyc
            elif os.path.isfile(pycache_pyo) and os.stat(pycache_pyo).st_mtime >= os.stat(file_py).st_mtime:
                fname = pycache_pyo
                arcname = file_pyo
            elif _compile(file_py):
                fname = pycache_pyc if __debug__ else pycache_pyo
                arcname = file_pyc if __debug__ else file_pyo
            else:
                fname = arcname = file_py
        else:
            if self._optimize == 0:
                fname = pycache_pyc
                arcname = file_pyc
            else:
                fname = pycache_pyo
                arcname = file_pyo
            if not (os.path.isfile(fname) and os.stat(fname).st_mtime >= os.stat(file_py).st_mtime or _compile(file_py, optimize=self._optimize)):
                fname = arcname = file_py
        archivename = os.path.split(arcname)[1]
        if basename:
            archivename = '%s/%s' % (basename, archivename)
        return (fname, archivename)

def main(args=None):
    import textwrap
    USAGE = textwrap.dedent('        Usage:\n            zipfile.py -l zipfile.zip        # Show listing of a zipfile\n            zipfile.py -t zipfile.zip        # Test if a zipfile is valid\n            zipfile.py -e zipfile.zip target # Extract zipfile into target dir\n            zipfile.py -c zipfile.zip src ... # Create zipfile from sources\n        ')
    if args is None:
        args = sys.argv[1:]
    if not args or args[0] not in ('-l', '-c', '-e', '-t'):
        print(USAGE)
        sys.exit(1)
    if args[0] == '-l':
        if len(args) != 2:
            print(USAGE)
            sys.exit(1)
        with ZipFile(args[1], 'r') as zf:
            zf.printdir()
    elif args[0] == '-t':
        if len(args) != 2:
            print(USAGE)
            sys.exit(1)
        with ZipFile(args[1], 'r') as zf:
            badfile = zf.testzip()
        if badfile:
            print('The following enclosed file is corrupted: {!r}'.format(badfile))
        print('Done testing')
    elif args[0] == '-e':
        if len(args) != 3:
            print(USAGE)
            sys.exit(1)
        with ZipFile(args[1], 'r') as zf:
            out = args[2]
            for path in zf.namelist():
                if path.startswith('./'):
                    tgt = os.path.join(out, path[2:])
                else:
                    tgt = os.path.join(out, path)
                tgtdir = os.path.dirname(tgt)
                if not os.path.exists(tgtdir):
                    os.makedirs(tgtdir)
                with open(tgt, 'wb') as fp:
                    fp.write(zf.read(path))
    elif args[0] == '-c':
        if len(args) < 3:
            print(USAGE)
            sys.exit(1)

        def addToZip(zf, path, zippath):
            if os.path.isfile(path):
                zf.write(path, zippath, ZIP_DEFLATED)
            elif os.path.isdir(path):
                for nm in os.listdir(path):
                    addToZip(zf, os.path.join(path, nm), os.path.join(zippath, nm))

        with ZipFile(args[1], 'w', allowZip64=True) as zf:
            for src in args[2:]:
                addToZip(zf, src, os.path.basename(src))

if __name__ == '__main__':
    main()
