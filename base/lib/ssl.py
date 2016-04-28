import textwrap
import re
import _ssl
from _ssl import OPENSSL_VERSION_NUMBER, OPENSSL_VERSION_INFO, OPENSSL_VERSION
from _ssl import _SSLContext
from _ssl import SSLError, SSLZeroReturnError, SSLWantReadError, SSLWantWriteError, SSLSyscallError, SSLEOFError
from _ssl import CERT_NONE, CERT_OPTIONAL, CERT_REQUIRED
from _ssl import OP_ALL, OP_NO_SSLv2, OP_NO_SSLv3, OP_NO_TLSv1, OP_CIPHER_SERVER_PREFERENCE, OP_SINGLE_DH_USE
try:
    from _ssl import OP_NO_COMPRESSION
except ImportError:
    pass
try:
    from _ssl import OP_SINGLE_ECDH_USE
except ImportError:
    pass
from _ssl import RAND_status, RAND_egd, RAND_add, RAND_bytes, RAND_pseudo_bytes
from _ssl import SSL_ERROR_ZERO_RETURN, SSL_ERROR_WANT_READ, SSL_ERROR_WANT_WRITE, SSL_ERROR_WANT_X509_LOOKUP, SSL_ERROR_SYSCALL, SSL_ERROR_SSL, SSL_ERROR_WANT_CONNECT, SSL_ERROR_EOF, SSL_ERROR_INVALID_ERROR_CODE
from _ssl import HAS_SNI, HAS_ECDH, HAS_NPN
from _ssl import PROTOCOL_SSLv3, PROTOCOL_SSLv23, PROTOCOL_TLSv1
from _ssl import _OPENSSL_API_VERSION
_PROTOCOL_NAMES = {PROTOCOL_TLSv1: 'TLSv1', PROTOCOL_SSLv23: 'SSLv23', PROTOCOL_SSLv3: 'SSLv3'}
try:
    from _ssl import PROTOCOL_SSLv2
    _SSLv2_IF_EXISTS = PROTOCOL_SSLv2
except ImportError:
    _SSLv2_IF_EXISTS = None
_PROTOCOL_NAMES[PROTOCOL_SSLv2] = 'SSLv2'
from socket import getnameinfo as _getnameinfo
from socket import error as socket_error
from socket import socket, AF_INET, SOCK_STREAM, create_connection
from socket import SOL_SOCKET, SO_TYPE
import base64
import traceback
import errno
if _ssl.HAS_TLS_UNIQUE:
    CHANNEL_BINDING_TYPES = ['tls-unique']
else:
    CHANNEL_BINDING_TYPES = []
_DEFAULT_CIPHERS = 'DEFAULT:!aNULL:!eNULL:!LOW:!EXPORT:!SSLv2'

class CertificateError(ValueError):
    __qualname__ = 'CertificateError'

def _dnsname_match(dn, hostname, max_wildcards=1):
    pats = []
    if not dn:
        return False
    (leftmost, *remainder) = dn.split('.')
    wildcards = leftmost.count('*')
    if wildcards > max_wildcards:
        raise CertificateError('too many wildcards in certificate DNS name: ' + repr(dn))
    if not wildcards:
        return dn.lower() == hostname.lower()
    if leftmost == '*':
        pats.append('[^.]+')
    elif leftmost.startswith('xn--') or hostname.startswith('xn--'):
        pats.append(re.escape(leftmost))
    else:
        pats.append(re.escape(leftmost).replace('\\*', '[^.]*'))
    for frag in remainder:
        pats.append(re.escape(frag))
    pat = re.compile('\\A' + '\\.'.join(pats) + '\\Z', re.IGNORECASE)
    return pat.match(hostname)

def match_hostname(cert, hostname):
    if not cert:
        raise ValueError('empty or no certificate')
    dnsnames = []
    san = cert.get('subjectAltName', ())
    for (key, value) in san:
        while key == 'DNS':
            if _dnsname_match(value, hostname):
                return
            dnsnames.append(value)
    if not dnsnames:
        for sub in cert.get('subject', ()):
            for (key, value) in sub:
                while key == 'commonName':
                    if _dnsname_match(value, hostname):
                        return
                    dnsnames.append(value)
    if len(dnsnames) > 1:
        raise CertificateError("hostname %r doesn't match either of %s" % (hostname, ', '.join(map(repr, dnsnames))))
    elif len(dnsnames) == 1:
        raise CertificateError("hostname %r doesn't match %r" % (hostname, dnsnames[0]))
    else:
        raise CertificateError('no appropriate commonName or subjectAltName fields were found')

class SSLContext(_SSLContext):
    __qualname__ = 'SSLContext'
    __slots__ = ('protocol',)

    def __new__(cls, protocol, *args, **kwargs):
        self = _SSLContext.__new__(cls, protocol)
        if protocol != _SSLv2_IF_EXISTS:
            self.set_ciphers(_DEFAULT_CIPHERS)
        return self

    def __init__(self, protocol):
        self.protocol = protocol

    def wrap_socket(self, sock, server_side=False, do_handshake_on_connect=True, suppress_ragged_eofs=True, server_hostname=None):
        return SSLSocket(sock=sock, server_side=server_side, do_handshake_on_connect=do_handshake_on_connect, suppress_ragged_eofs=suppress_ragged_eofs, server_hostname=server_hostname, _context=self)

    def set_npn_protocols(self, npn_protocols):
        protos = bytearray()
        for protocol in npn_protocols:
            b = bytes(protocol, 'ascii')
            if len(b) == 0 or len(b) > 255:
                raise SSLError('NPN protocols must be 1 to 255 in length')
            protos.append(len(b))
            protos.extend(b)
        self._set_npn_protocols(protos)

class SSLSocket(socket):
    __qualname__ = 'SSLSocket'

    def __init__(self, sock=None, keyfile=None, certfile=None, server_side=False, cert_reqs=CERT_NONE, ssl_version=PROTOCOL_SSLv23, ca_certs=None, do_handshake_on_connect=True, family=AF_INET, type=SOCK_STREAM, proto=0, fileno=None, suppress_ragged_eofs=True, npn_protocols=None, ciphers=None, server_hostname=None, _context=None):
        if _context:
            self.context = _context
        else:
            if server_side and not certfile:
                raise ValueError('certfile must be specified for server-side operations')
            if keyfile and not certfile:
                raise ValueError('certfile must be specified')
            if certfile and not keyfile:
                keyfile = certfile
            self.context = SSLContext(ssl_version)
            self.context.verify_mode = cert_reqs
            if ca_certs:
                self.context.load_verify_locations(ca_certs)
            if certfile:
                self.context.load_cert_chain(certfile, keyfile)
            if npn_protocols:
                self.context.set_npn_protocols(npn_protocols)
            if ciphers:
                self.context.set_ciphers(ciphers)
            self.keyfile = keyfile
            self.certfile = certfile
            self.cert_reqs = cert_reqs
            self.ssl_version = ssl_version
            self.ca_certs = ca_certs
            self.ciphers = ciphers
        if sock.getsockopt(SOL_SOCKET, SO_TYPE) != SOCK_STREAM:
            raise NotImplementedError('only stream sockets are supported')
        if server_side and server_hostname:
            raise ValueError('server_hostname can only be specified in client mode')
        self.server_side = server_side
        self.server_hostname = server_hostname
        self.do_handshake_on_connect = do_handshake_on_connect
        self.suppress_ragged_eofs = suppress_ragged_eofs
        connected = False
        if sock is not None:
            socket.__init__(self, family=sock.family, type=sock.type, proto=sock.proto, fileno=sock.fileno())
            self.settimeout(sock.gettimeout())
            try:
                sock.getpeername()
            except socket_error as e:
                while e.errno != errno.ENOTCONN:
                    raise
            connected = True
            sock.detach()
        elif fileno is not None:
            socket.__init__(self, fileno=fileno)
        else:
            socket.__init__(self, family=family, type=type, proto=proto)
        self._closed = False
        self._sslobj = None
        self._connected = connected
        if connected:
            try:
                self._sslobj = self.context._wrap_socket(self, server_side, server_hostname)
                while do_handshake_on_connect:
                    timeout = self.gettimeout()
                    if timeout == 0.0:
                        raise ValueError('do_handshake_on_connect should not be specified for non-blocking sockets')
                    self.do_handshake()
            except socket_error as x:
                self.close()
                raise x

    def dup(self):
        raise NotImplemented("Can't dup() %s instances" % self.__class__.__name__)

    def _checkClosed(self, msg=None):
        pass

    def read(self, len=0, buffer=None):
        self._checkClosed()
        try:
            if buffer is not None:
                v = self._sslobj.read(len, buffer)
            else:
                v = self._sslobj.read(len or 1024)
            return v
        except SSLError as x:
            if buffer is not None:
                return 0
            return b''

    def write(self, data):
        self._checkClosed()
        return self._sslobj.write(data)

    def getpeercert(self, binary_form=False):
        self._checkClosed()
        return self._sslobj.peer_certificate(binary_form)

    def selected_npn_protocol(self):
        self._checkClosed()
        if not self._sslobj or not _ssl.HAS_NPN:
            return
        return self._sslobj.selected_npn_protocol()

    def cipher(self):
        self._checkClosed()
        if not self._sslobj:
            return
        return self._sslobj.cipher()

    def compression(self):
        self._checkClosed()
        if not self._sslobj:
            return
        return self._sslobj.compression()

    def send(self, data, flags=0):
        self._checkClosed()
        if self._sslobj:
            if flags != 0:
                raise ValueError('non-zero flags not allowed in calls to send() on %s' % self.__class__)
            try:
                v = self._sslobj.write(data)
            except SSLError as x:
                if x.args[0] == SSL_ERROR_WANT_READ:
                    return 0
                if x.args[0] == SSL_ERROR_WANT_WRITE:
                    return 0
                raise
            return v
            continue
        else:
            return socket.send(self, data, flags)

    def sendto(self, data, flags_or_addr, addr=None):
        self._checkClosed()
        if self._sslobj:
            raise ValueError('sendto not allowed on instances of %s' % self.__class__)
        else:
            if addr is None:
                return socket.sendto(self, data, flags_or_addr)
            return socket.sendto(self, data, flags_or_addr, addr)

    def sendmsg(self, *args, **kwargs):
        raise NotImplementedError('sendmsg not allowed on instances of %s' % self.__class__)

    def sendall(self, data, flags=0):
        self._checkClosed()
        if self._sslobj:
            if flags != 0:
                raise ValueError('non-zero flags not allowed in calls to sendall() on %s' % self.__class__)
            amount = len(data)
            count = 0
            while count < amount:
                v = self.send(data[count:])
                count += v
            return amount
        return socket.sendall(self, data, flags)

    def recv(self, buflen=1024, flags=0):
        self._checkClosed()
        if self._sslobj:
            if flags != 0:
                raise ValueError('non-zero flags not allowed in calls to recv() on %s' % self.__class__)
            return self.read(buflen)
        return socket.recv(self, buflen, flags)

    def recv_into(self, buffer, nbytes=None, flags=0):
        self._checkClosed()
        if buffer and nbytes is None:
            nbytes = len(buffer)
        elif nbytes is None:
            nbytes = 1024
        if self._sslobj:
            if flags != 0:
                raise ValueError('non-zero flags not allowed in calls to recv_into() on %s' % self.__class__)
            return self.read(nbytes, buffer)
        return socket.recv_into(self, buffer, nbytes, flags)

    def recvfrom(self, buflen=1024, flags=0):
        self._checkClosed()
        if self._sslobj:
            raise ValueError('recvfrom not allowed on instances of %s' % self.__class__)
        else:
            return socket.recvfrom(self, buflen, flags)

    def recvfrom_into(self, buffer, nbytes=None, flags=0):
        self._checkClosed()
        if self._sslobj:
            raise ValueError('recvfrom_into not allowed on instances of %s' % self.__class__)
        else:
            return socket.recvfrom_into(self, buffer, nbytes, flags)

    def recvmsg(self, *args, **kwargs):
        raise NotImplementedError('recvmsg not allowed on instances of %s' % self.__class__)

    def recvmsg_into(self, *args, **kwargs):
        raise NotImplementedError('recvmsg_into not allowed on instances of %s' % self.__class__)

    def pending(self):
        self._checkClosed()
        if self._sslobj:
            return self._sslobj.pending()
        return 0

    def shutdown(self, how):
        self._checkClosed()
        self._sslobj = None
        socket.shutdown(self, how)

    def unwrap(self):
        if self._sslobj:
            s = self._sslobj.shutdown()
            self._sslobj = None
            return s
        raise ValueError('No SSL wrapper around ' + str(self))

    def _real_close(self):
        self._sslobj = None
        socket._real_close(self)

    def do_handshake(self, block=False):
        timeout = self.gettimeout()
        try:
            if timeout == 0.0 and block:
                self.settimeout(None)
            self._sslobj.do_handshake()
        finally:
            self.settimeout(timeout)

    def _real_connect(self, addr, connect_ex):
        if self.server_side:
            raise ValueError("can't connect in server-side mode")
        if self._connected:
            raise ValueError('attempt to connect already-connected SSLSocket!')
        self._sslobj = self.context._wrap_socket(self, False, self.server_hostname)
        try:
            if connect_ex:
                rc = socket.connect_ex(self, addr)
            else:
                rc = None
                socket.connect(self, addr)
            if not rc:
                if self.do_handshake_on_connect:
                    self.do_handshake()
                self._connected = True
            return rc
        except socket_error:
            self._sslobj = None
            raise

    def connect(self, addr):
        self._real_connect(addr, False)

    def connect_ex(self, addr):
        return self._real_connect(addr, True)

    def accept(self):
        (newsock, addr) = socket.accept(self)
        newsock = self.context.wrap_socket(newsock, do_handshake_on_connect=self.do_handshake_on_connect, suppress_ragged_eofs=self.suppress_ragged_eofs, server_side=True)
        return (newsock, addr)

    def get_channel_binding(self, cb_type='tls-unique'):
        if cb_type not in CHANNEL_BINDING_TYPES:
            raise ValueError('Unsupported channel binding type')
        if cb_type != 'tls-unique':
            raise NotImplementedError('{0} channel binding type not implemented'.format(cb_type))
        if self._sslobj is None:
            return
        return self._sslobj.tls_unique_cb()

def wrap_socket(sock, keyfile=None, certfile=None, server_side=False, cert_reqs=CERT_NONE, ssl_version=PROTOCOL_SSLv23, ca_certs=None, do_handshake_on_connect=True, suppress_ragged_eofs=True, ciphers=None):
    return SSLSocket(sock=sock, keyfile=keyfile, certfile=certfile, server_side=server_side, cert_reqs=cert_reqs, ssl_version=ssl_version, ca_certs=ca_certs, do_handshake_on_connect=do_handshake_on_connect, suppress_ragged_eofs=suppress_ragged_eofs, ciphers=ciphers)

def cert_time_to_seconds(cert_time):
    import time
    return time.mktime(time.strptime(cert_time, '%b %d %H:%M:%S %Y GMT'))

PEM_HEADER = '-----BEGIN CERTIFICATE-----'
PEM_FOOTER = '-----END CERTIFICATE-----'

def DER_cert_to_PEM_cert(der_cert_bytes):
    f = str(base64.standard_b64encode(der_cert_bytes), 'ASCII', 'strict')
    return PEM_HEADER + '\n' + textwrap.fill(f, 64) + '\n' + PEM_FOOTER + '\n'

def PEM_cert_to_DER_cert(pem_cert_string):
    if not pem_cert_string.startswith(PEM_HEADER):
        raise ValueError('Invalid PEM encoding; must start with %s' % PEM_HEADER)
    if not pem_cert_string.strip().endswith(PEM_FOOTER):
        raise ValueError('Invalid PEM encoding; must end with %s' % PEM_FOOTER)
    d = pem_cert_string.strip()[len(PEM_HEADER):-len(PEM_FOOTER)]
    return base64.decodebytes(d.encode('ASCII', 'strict'))

def get_server_certificate(addr, ssl_version=PROTOCOL_SSLv3, ca_certs=None):
    (host, port) = addr
    if ca_certs is not None:
        cert_reqs = CERT_REQUIRED
    else:
        cert_reqs = CERT_NONE
    s = create_connection(addr)
    s = wrap_socket(s, ssl_version=ssl_version, cert_reqs=cert_reqs, ca_certs=ca_certs)
    dercert = s.getpeercert(True)
    s.close()
    return DER_cert_to_PEM_cert(dercert)

def get_protocol_name(protocol_code):
    return _PROTOCOL_NAMES.get(protocol_code, '<unknown>')

