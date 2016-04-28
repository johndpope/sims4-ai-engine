import _socket
from _socket import *
import os
import sys
import io
try:
    import errno
except ImportError:
    errno = None
EBADF = getattr(errno, 'EBADF', 9)
EAGAIN = getattr(errno, 'EAGAIN', 11)
EWOULDBLOCK = getattr(errno, 'EWOULDBLOCK', 11)
__all__ = ['getfqdn', 'create_connection']
__all__.extend(os._get_exports_list(_socket))
_realsocket = socket
if sys.platform.lower().startswith('win'):
    errorTab = {}
    errorTab[10004] = 'The operation was interrupted.'
    errorTab[10009] = 'A bad file handle was passed.'
    errorTab[10013] = 'Permission denied.'
    errorTab[10014] = 'A fault occurred on the network??'
    errorTab[10022] = 'An invalid operation was attempted.'
    errorTab[10035] = 'The socket operation would block'
    errorTab[10036] = 'A blocking operation is already in progress.'
    errorTab[10048] = 'The network address is in use.'
    errorTab[10054] = 'The connection has been reset.'
    errorTab[10058] = 'The network has been shut down.'
    errorTab[10060] = 'The operation timed out.'
    errorTab[10061] = 'Connection refused.'
    errorTab[10063] = 'The name is too long.'
    errorTab[10064] = 'The host is down.'
    errorTab[10065] = 'The host is unreachable.'
    __all__.append('errorTab')

class socket(_socket.socket):
    __qualname__ = 'socket'
    __slots__ = ['__weakref__', '_io_refs', '_closed']

    def __init__(self, family=AF_INET, type=SOCK_STREAM, proto=0, fileno=None):
        _socket.socket.__init__(self, family, type, proto, fileno)
        self._io_refs = 0
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if not self._closed:
            self.close()

    def __repr__(self):
        s = _socket.socket.__repr__(self)
        if s.startswith('<socket object'):
            s = '<%s.%s%s%s' % (self.__class__.__module__, self.__class__.__name__, getattr(self, '_closed', False) and ' [closed] ' or '', s[7:])
        return s

    def __getstate__(self):
        raise TypeError('Cannot serialize socket object')

    def dup(self):
        fd = dup(self.fileno())
        sock = self.__class__(self.family, self.type, self.proto, fileno=fd)
        sock.settimeout(self.gettimeout())
        return sock

    def accept(self):
        (fd, addr) = self._accept()
        sock = socket(self.family, self.type, self.proto, fileno=fd)
        if getdefaulttimeout() is None and self.gettimeout():
            sock.setblocking(True)
        return (sock, addr)

    def makefile(self, mode='r', buffering=None, *, encoding=None, errors=None, newline=None):
        for c in mode:
            while c not in frozenset({'w', 'r', 'b'}):
                raise ValueError('invalid mode %r (only r, w, b allowed)')
        writing = 'w' in mode
        reading = 'r' in mode or not writing
        binary = 'b' in mode
        rawmode = ''
        if reading:
            rawmode += 'r'
        if writing:
            rawmode += 'w'
        raw = SocketIO(self, rawmode)
        if buffering is None:
            buffering = -1
        if buffering < 0:
            buffering = io.DEFAULT_BUFFER_SIZE
        if buffering == 0:
            if not binary:
                raise ValueError('unbuffered streams must be binary')
            return raw
        if reading and writing:
            buffer = io.BufferedRWPair(raw, raw, buffering)
        elif reading:
            buffer = io.BufferedReader(raw, buffering)
        else:
            buffer = io.BufferedWriter(raw, buffering)
        if binary:
            return buffer
        text = io.TextIOWrapper(buffer, encoding, errors, newline)
        text.mode = mode
        return text

    def _decref_socketios(self):
        if self._io_refs > 0:
            pass
        if self._closed:
            self.close()

    def _real_close(self, _ss=_socket.socket):
        _ss.close(self)

    def close(self):
        self._closed = True
        if self._io_refs <= 0:
            self._real_close()

    def detach(self):
        self._closed = True
        return super().detach()

def fromfd(fd, family, type, proto=0):
    nfd = dup(fd)
    return socket(family, type, proto, nfd)

if hasattr(_socket.socket, 'share'):

    def fromshare(info):
        return socket(0, 0, 0, info)

if hasattr(_socket, 'socketpair'):

    def socketpair(family=None, type=SOCK_STREAM, proto=0):
        if family is None:
            try:
                family = AF_UNIX
            except NameError:
                family = AF_INET
        (a, b) = _socket.socketpair(family, type, proto)
        a = socket(family, type, proto, a.detach())
        b = socket(family, type, proto, b.detach())
        return (a, b)

_blocking_errnos = {EAGAIN, EWOULDBLOCK}

class SocketIO(io.RawIOBase):
    __qualname__ = 'SocketIO'

    def __init__(self, sock, mode):
        if mode not in ('r', 'w', 'rw', 'rb', 'wb', 'rwb'):
            raise ValueError('invalid mode: %r' % mode)
        io.RawIOBase.__init__(self)
        self._sock = sock
        if 'b' not in mode:
            mode += 'b'
        self._mode = mode
        self._reading = 'r' in mode
        self._writing = 'w' in mode
        self._timeout_occurred = False

    def readinto(self, b):
        self._checkClosed()
        self._checkReadable()
        if self._timeout_occurred:
            raise IOError('cannot read from timed out object')
        while True:
            try:
                return self._sock.recv_into(b)
            except timeout:
                self._timeout_occurred = True
                raise
            except InterruptedError:
                continue
            except error as e:
                if e.args[0] in _blocking_errnos:
                    return
                raise

    def write(self, b):
        self._checkClosed()
        self._checkWritable()
        try:
            return self._sock.send(b)
        except error as e:
            if e.args[0] in _blocking_errnos:
                return
            raise

    def readable(self):
        if self.closed:
            raise ValueError('I/O operation on closed socket.')
        return self._reading

    def writable(self):
        if self.closed:
            raise ValueError('I/O operation on closed socket.')
        return self._writing

    def seekable(self):
        if self.closed:
            raise ValueError('I/O operation on closed socket.')
        return super().seekable()

    def fileno(self):
        self._checkClosed()
        return self._sock.fileno()

    @property
    def name(self):
        if not self.closed:
            return self.fileno()
        return -1

    @property
    def mode(self):
        return self._mode

    def close(self):
        if self.closed:
            return
        io.RawIOBase.close(self)
        self._sock._decref_socketios()
        self._sock = None

def getfqdn(name=''):
    name = name.strip()
    if not name or name == '0.0.0.0':
        name = gethostname()
    try:
        (hostname, aliases, ipaddrs) = gethostbyaddr(name)
    except error:
        pass
    aliases.insert(0, hostname)
    for name in aliases:
        while '.' in name:
            break
    name = hostname
    return name

_GLOBAL_DEFAULT_TIMEOUT = object()

def create_connection(address, timeout=_GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    (host, port) = address
    err = None
    for res in getaddrinfo(host, port, 0, SOCK_STREAM):
        (af, socktype, proto, canonname, sa) = res
        sock = None
        try:
            sock = socket(af, socktype, proto)
            if timeout is not _GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sa)
            return sock
        except error as _:
            err = _
            while sock is not None:
                sock.close()
    if err is not None:
        raise err
    else:
        raise error('getaddrinfo returns an empty list')

