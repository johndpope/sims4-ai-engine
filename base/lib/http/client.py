import email.parser
import email.message
import io
import os
import socket
import collections
from urllib.parse import urlsplit
import warnings
__all__ = ['HTTPResponse', 'HTTPConnection', 'HTTPException', 'NotConnected', 'UnknownProtocol', 'UnknownTransferEncoding', 'UnimplementedFileMode', 'IncompleteRead', 'InvalidURL', 'ImproperConnectionState', 'CannotSendRequest', 'CannotSendHeader', 'ResponseNotReady', 'BadStatusLine', 'error', 'responses']
HTTP_PORT = 80
HTTPS_PORT = 443
_UNKNOWN = 'UNKNOWN'
_CS_IDLE = 'Idle'
_CS_REQ_STARTED = 'Request-started'
_CS_REQ_SENT = 'Request-sent'
CONTINUE = 100
SWITCHING_PROTOCOLS = 101
PROCESSING = 102
OK = 200
CREATED = 201
ACCEPTED = 202
NON_AUTHORITATIVE_INFORMATION = 203
NO_CONTENT = 204
RESET_CONTENT = 205
PARTIAL_CONTENT = 206
MULTI_STATUS = 207
IM_USED = 226
MULTIPLE_CHOICES = 300
MOVED_PERMANENTLY = 301
FOUND = 302
SEE_OTHER = 303
NOT_MODIFIED = 304
USE_PROXY = 305
TEMPORARY_REDIRECT = 307
BAD_REQUEST = 400
UNAUTHORIZED = 401
PAYMENT_REQUIRED = 402
FORBIDDEN = 403
NOT_FOUND = 404
METHOD_NOT_ALLOWED = 405
NOT_ACCEPTABLE = 406
PROXY_AUTHENTICATION_REQUIRED = 407
REQUEST_TIMEOUT = 408
CONFLICT = 409
GONE = 410
LENGTH_REQUIRED = 411
PRECONDITION_FAILED = 412
REQUEST_ENTITY_TOO_LARGE = 413
REQUEST_URI_TOO_LONG = 414
UNSUPPORTED_MEDIA_TYPE = 415
REQUESTED_RANGE_NOT_SATISFIABLE = 416
EXPECTATION_FAILED = 417
UNPROCESSABLE_ENTITY = 422
LOCKED = 423
FAILED_DEPENDENCY = 424
UPGRADE_REQUIRED = 426
PRECONDITION_REQUIRED = 428
TOO_MANY_REQUESTS = 429
REQUEST_HEADER_FIELDS_TOO_LARGE = 431
INTERNAL_SERVER_ERROR = 500
NOT_IMPLEMENTED = 501
BAD_GATEWAY = 502
SERVICE_UNAVAILABLE = 503
GATEWAY_TIMEOUT = 504
HTTP_VERSION_NOT_SUPPORTED = 505
INSUFFICIENT_STORAGE = 507
NOT_EXTENDED = 510
NETWORK_AUTHENTICATION_REQUIRED = 511
responses = {100: 'Continue', 101: 'Switching Protocols', 200: 'OK', 201: 'Created', 202: 'Accepted', 203: 'Non-Authoritative Information', 204: 'No Content', 205: 'Reset Content', 206: 'Partial Content', 300: 'Multiple Choices', 301: 'Moved Permanently', 302: 'Found', 303: 'See Other', 304: 'Not Modified', 305: 'Use Proxy', 306: '(Unused)', 307: 'Temporary Redirect', 400: 'Bad Request', 401: 'Unauthorized', 402: 'Payment Required', 403: 'Forbidden', 404: 'Not Found', 405: 'Method Not Allowed', 406: 'Not Acceptable', 407: 'Proxy Authentication Required', 408: 'Request Timeout', 409: 'Conflict', 410: 'Gone', 411: 'Length Required', 412: 'Precondition Failed', 413: 'Request Entity Too Large', 414: 'Request-URI Too Long', 415: 'Unsupported Media Type', 416: 'Requested Range Not Satisfiable', 417: 'Expectation Failed', 428: 'Precondition Required', 429: 'Too Many Requests', 431: 'Request Header Fields Too Large', 500: 'Internal Server Error', 501: 'Not Implemented', 502: 'Bad Gateway', 503: 'Service Unavailable', 504: 'Gateway Timeout', 505: 'HTTP Version Not Supported', 511: 'Network Authentication Required'}
MAXAMOUNT = 1048576
_MAXLINE = 65536
_MAXHEADERS = 100

class HTTPMessage(email.message.Message):
    __qualname__ = 'HTTPMessage'

    def getallmatchingheaders(self, name):
        name = name.lower() + ':'
        n = len(name)
        lst = []
        hit = 0
        for line in self.keys():
            if line[:n].lower() == name:
                hit = 1
            elif not line[:1].isspace():
                hit = 0
            while hit:
                lst.append(line)
        return lst

def parse_headers(fp, _class=HTTPMessage):
    headers = []
    while True:
        line = fp.readline(_MAXLINE + 1)
        if len(line) > _MAXLINE:
            raise LineTooLong('header line')
        headers.append(line)
        if len(headers) > _MAXHEADERS:
            raise HTTPException('got more than %d headers' % _MAXHEADERS)
        if line in (b'\r\n', b'\n', b''):
            break
    hstring = b''.join(headers).decode('iso-8859-1')
    return email.parser.Parser(_class=_class).parsestr(hstring)

_strict_sentinel = object()

class HTTPResponse(io.RawIOBase):
    __qualname__ = 'HTTPResponse'

    def __init__(self, sock, debuglevel=0, strict=_strict_sentinel, method=None, url=None):
        self.fp = sock.makefile('rb')
        self.debuglevel = debuglevel
        if strict is not _strict_sentinel:
            warnings.warn("the 'strict' argument isn't supported anymore; http.client now always assumes HTTP/1.x compliant servers.", DeprecationWarning, 2)
        self._method = method
        self.headers = self.msg = None
        self.version = _UNKNOWN
        self.status = _UNKNOWN
        self.reason = _UNKNOWN
        self.chunked = _UNKNOWN
        self.chunk_left = _UNKNOWN
        self.length = _UNKNOWN
        self.will_close = _UNKNOWN

    def _read_status(self):
        line = str(self.fp.readline(_MAXLINE + 1), 'iso-8859-1')
        if len(line) > _MAXLINE:
            raise LineTooLong('status line')
        if self.debuglevel > 0:
            print('reply:', repr(line))
        if not line:
            raise BadStatusLine(line)
        try:
            (version, status, reason) = line.split(None, 2)
        except ValueError:
            try:
                (version, status) = line.split(None, 1)
                reason = ''
            except ValueError:
                version = ''
        if not version.startswith('HTTP/'):
            self._close_conn()
            raise BadStatusLine(line)
        try:
            status = int(status)
            while status < 100 or status > 999:
                raise BadStatusLine(line)
        except ValueError:
            raise BadStatusLine(line)
        return (version, status, reason)

    def begin(self):
        if self.headers is not None:
            return
        while True:
            (version, status, reason) = self._read_status()
            if status != CONTINUE:
                break
            while True:
                skip = self.fp.readline(_MAXLINE + 1)
                if len(skip) > _MAXLINE:
                    raise LineTooLong('header line')
                skip = skip.strip()
                if not skip:
                    break
                if self.debuglevel > 0:
                    print('header:', skip)
        self.code = self.status = status
        self.reason = reason.strip()
        if version in ('HTTP/1.0', 'HTTP/0.9'):
            self.version = 10
        elif version.startswith('HTTP/1.'):
            self.version = 11
        else:
            raise UnknownProtocol(version)
        self.headers = self.msg = parse_headers(self.fp)
        if self.debuglevel > 0:
            for hdr in self.headers:
                print('header:', hdr, end=' ')
        tr_enc = self.headers.get('transfer-encoding')
        if tr_enc and tr_enc.lower() == 'chunked':
            self.chunked = True
            self.chunk_left = None
        else:
            self.chunked = False
        self.will_close = self._check_close()
        self.length = None
        length = self.headers.get('content-length')
        tr_enc = self.headers.get('transfer-encoding')
        if length and not self.chunked:
            try:
                self.length = int(length)
            except ValueError:
                self.length = None
            self.length = None
        else:
            self.length = None
        if status == NO_CONTENT or (status == NOT_MODIFIED or 100 <= status < 200) or self._method == 'HEAD':
            self.length = 0
        if not self.will_close and not self.chunked and self.length is None:
            self.will_close = True

    def _check_close(self):
        conn = self.headers.get('connection')
        if self.version == 11:
            conn = self.headers.get('connection')
            if conn and 'close' in conn.lower():
                return True
            return False
        if self.headers.get('keep-alive'):
            return False
        if conn and 'keep-alive' in conn.lower():
            return False
        pconn = self.headers.get('proxy-connection')
        if pconn and 'keep-alive' in pconn.lower():
            return False
        return True

    def _close_conn(self):
        fp = self.fp
        self.fp = None
        fp.close()

    def close(self):
        super().close()
        if self.fp:
            self._close_conn()

    def flush(self):
        super().flush()
        if self.fp:
            self.fp.flush()

    def readable(self):
        return True

    def isclosed(self):
        return self.fp is None

    def read(self, amt=None):
        if self.fp is None:
            return b''
        if self._method == 'HEAD':
            self._close_conn()
            return b''
        if amt is not None:
            return super(HTTPResponse, self).read(amt)
        if self.chunked:
            return self._readall_chunked()
        if self.length is None:
            s = self.fp.read()
        else:
            try:
                s = self._safe_read(self.length)
            except IncompleteRead:
                self._close_conn()
                raise
            self.length = 0
        self._close_conn()
        return s

    def readinto(self, b):
        if self.fp is None:
            return 0
        if self._method == 'HEAD':
            self._close_conn()
            return 0
        if self.chunked:
            return self._readinto_chunked(b)
        if self.length is not None and len(b) > self.length:
            b = memoryview(b)[0:self.length]
        n = self.fp.readinto(b)
        if not n and b:
            self._close_conn()
        elif self.length is not None:
            if not self.length:
                self._close_conn()
        return n

    def _read_next_chunk_size(self):
        line = self.fp.readline(_MAXLINE + 1)
        if len(line) > _MAXLINE:
            raise LineTooLong('chunk size')
        i = line.find(b';')
        if i >= 0:
            line = line[:i]
        try:
            return int(line, 16)
        except ValueError:
            self._close_conn()
            raise

    def _read_and_discard_trailer(self):
        while True:
            line = self.fp.readline(_MAXLINE + 1)
            if len(line) > _MAXLINE:
                raise LineTooLong('trailer line')
            if not line:
                break
            if line in (b'\r\n', b'\n', b''):
                break

    def _readall_chunked(self):
        chunk_left = self.chunk_left
        value = []
        while True:
            if chunk_left is None:
                try:
                    chunk_left = self._read_next_chunk_size()
                    while chunk_left == 0:
                        break
                except ValueError:
                    raise IncompleteRead(b''.join(value))
            value.append(self._safe_read(chunk_left))
            self._safe_read(2)
            chunk_left = None
        self._read_and_discard_trailer()
        self._close_conn()
        return b''.join(value)

    def _readinto_chunked(self, b):
        chunk_left = self.chunk_left
        total_bytes = 0
        mvb = memoryview(b)
        while True:
            if chunk_left is None:
                try:
                    chunk_left = self._read_next_chunk_size()
                    while chunk_left == 0:
                        break
                except ValueError:
                    raise IncompleteRead(bytes(b[0:total_bytes]))
            if len(mvb) < chunk_left:
                n = self._safe_readinto(mvb)
                self.chunk_left = chunk_left - n
                return total_bytes + n
            if len(mvb) == chunk_left:
                n = self._safe_readinto(mvb)
                self._safe_read(2)
                self.chunk_left = None
                return total_bytes + n
            temp_mvb = mvb[0:chunk_left]
            n = self._safe_readinto(temp_mvb)
            mvb = mvb[n:]
            total_bytes += n
            self._safe_read(2)
            chunk_left = None
        self._read_and_discard_trailer()
        self._close_conn()
        return total_bytes

    def _safe_read(self, amt):
        s = []
        while amt > 0:
            chunk = self.fp.read(min(amt, MAXAMOUNT))
            if not chunk:
                raise IncompleteRead(b''.join(s), amt)
            s.append(chunk)
            amt -= len(chunk)
        return b''.join(s)

    def _safe_readinto(self, b):
        total_bytes = 0
        mvb = memoryview(b)
        while total_bytes < len(b):
            if MAXAMOUNT < len(mvb):
                temp_mvb = mvb[0:MAXAMOUNT]
                n = self.fp.readinto(temp_mvb)
            else:
                n = self.fp.readinto(mvb)
            if not n:
                raise IncompleteRead(bytes(mvb[0:total_bytes]), len(b))
            mvb = mvb[n:]
            total_bytes += n
        return total_bytes

    def fileno(self):
        return self.fp.fileno()

    def getheader(self, name, default=None):
        if self.headers is None:
            raise ResponseNotReady()
        headers = self.headers.get_all(name) or default
        if isinstance(headers, str) or not hasattr(headers, '__iter__'):
            return headers
        return ', '.join(headers)

    def getheaders(self):
        if self.headers is None:
            raise ResponseNotReady()
        return list(self.headers.items())

    def __iter__(self):
        return self

    def info(self):
        return self.headers

    def geturl(self):
        return self.url

    def getcode(self):
        return self.status

class HTTPConnection:
    __qualname__ = 'HTTPConnection'
    _http_vsn = 11
    _http_vsn_str = 'HTTP/1.1'
    response_class = HTTPResponse
    default_port = HTTP_PORT
    auto_open = 1
    debuglevel = 0

    def __init__(self, host, port=None, strict=_strict_sentinel, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        if strict is not _strict_sentinel:
            warnings.warn("the 'strict' argument isn't supported anymore; http.client now always assumes HTTP/1.x compliant servers.", DeprecationWarning, 2)
        self.timeout = timeout
        self.source_address = source_address
        self.sock = None
        self._buffer = []
        self._HTTPConnection__response = None
        self._HTTPConnection__state = _CS_IDLE
        self._method = None
        self._tunnel_host = None
        self._tunnel_port = None
        self._tunnel_headers = {}
        self._set_hostport(host, port)

    def set_tunnel(self, host, port=None, headers=None):
        self._tunnel_host = host
        self._tunnel_port = port
        if headers:
            self._tunnel_headers = headers
        else:
            self._tunnel_headers.clear()

    def _set_hostport(self, host, port):
        if port is None:
            i = host.rfind(':')
            j = host.rfind(']')
            if i > j:
                try:
                    port = int(host[i + 1:])
                except ValueError:
                    if host[i + 1:] == '':
                        port = self.default_port
                    else:
                        raise InvalidURL("nonnumeric port: '%s'" % host[i + 1:])
                host = host[:i]
            else:
                port = self.default_port
            if host and host[0] == '[' and host[-1] == ']':
                host = host[1:-1]
        self.host = host
        self.port = port

    def set_debuglevel(self, level):
        self.debuglevel = level

    def _tunnel(self):
        self._set_hostport(self._tunnel_host, self._tunnel_port)
        connect_str = 'CONNECT %s:%d HTTP/1.0\r\n' % (self.host, self.port)
        connect_bytes = connect_str.encode('ascii')
        self.send(connect_bytes)
        for (header, value) in self._tunnel_headers.items():
            header_str = '%s: %s\r\n' % (header, value)
            header_bytes = header_str.encode('latin-1')
            self.send(header_bytes)
        self.send(b'\r\n')
        response = self.response_class(self.sock, method=self._method)
        (version, code, message) = response._read_status()
        if code != 200:
            self.close()
            raise socket.error('Tunnel connection failed: %d %s' % (code, message.strip()))
        while True:
            line = response.fp.readline(_MAXLINE + 1)
            if len(line) > _MAXLINE:
                raise LineTooLong('header line')
            if not line:
                break
            if line in (b'\r\n', b'\n', b''):
                break

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None
        if self._HTTPConnection__response:
            self._HTTPConnection__response.close()
            self._HTTPConnection__response = None
        self._HTTPConnection__state = _CS_IDLE

    def send(self, data):
        if self.sock is None:
            if self.auto_open:
                self.connect()
            else:
                raise NotConnected()
        if self.debuglevel > 0:
            print('send:', repr(data))
        blocksize = 8192
        if self.debuglevel > 0:
            print('sendIng a read()able')
        encode = False
        try:
            mode = data.mode
        except AttributeError:
            pass
        if 'b' not in mode:
            encode = True
            if self.debuglevel > 0:
                print('encoding file using iso-8859-1')
        while True:
            datablock = data.read(blocksize)
            if not datablock:
                break
            if encode:
                datablock = datablock.encode('iso-8859-1')
            self.sock.sendall(datablock)
        return
        try:
            self.sock.sendall(data)
        except TypeError:
            if isinstance(data, collections.Iterable):
                for d in data:
                    self.sock.sendall(d)
            else:
                raise TypeError('data should be a bytes-like object or an iterable, got %r' % type(data))

    def _output(self, s):
        self._buffer.append(s)

    def _send_output(self, message_body=None):
        self._buffer.extend((b'', b''))
        msg = b'\r\n'.join(self._buffer)
        del self._buffer[:]
        if isinstance(message_body, bytes):
            msg += message_body
            message_body = None
        self.send(msg)
        if message_body is not None:
            self.send(message_body)

    def putrequest(self, method, url, skip_host=0, skip_accept_encoding=0):
        if self._HTTPConnection__response and self._HTTPConnection__response.isclosed():
            self._HTTPConnection__response = None
        if self._HTTPConnection__state == _CS_IDLE:
            self._HTTPConnection__state = _CS_REQ_STARTED
        else:
            raise CannotSendRequest(self._HTTPConnection__state)
        self._method = method
        if not url:
            url = '/'
        request = '%s %s %s' % (method, url, self._http_vsn_str)
        self._output(request.encode('ascii'))
        if not skip_host:
            netloc = ''
            if url.startswith('http'):
                (nil, netloc, nil, nil, nil) = urlsplit(url)
            if netloc:
                try:
                    netloc_enc = netloc.encode('ascii')
                except UnicodeEncodeError:
                    netloc_enc = netloc.encode('idna')
                self.putheader('Host', netloc_enc)
            else:
                try:
                    host_enc = self.host.encode('ascii')
                except UnicodeEncodeError:
                    host_enc = self.host.encode('idna')
                if self.host.find(':') >= 0:
                    host_enc = b'[' + host_enc + b']'
                if self.port == self.default_port:
                    self.putheader('Host', host_enc)
                else:
                    host_enc = host_enc.decode('ascii')
                    self.putheader('Host', '%s:%s' % (host_enc, self.port))
        if not (self._http_vsn == 11 and skip_accept_encoding):
            self.putheader('Accept-Encoding', 'identity')

    def putheader(self, header, *values):
        if self._HTTPConnection__state != _CS_REQ_STARTED:
            raise CannotSendHeader()
        if hasattr(header, 'encode'):
            header = header.encode('ascii')
        values = list(values)
        for (i, one_value) in enumerate(values):
            if hasattr(one_value, 'encode'):
                values[i] = one_value.encode('latin-1')
            else:
                while isinstance(one_value, int):
                    values[i] = str(one_value).encode('ascii')
        value = b'\r\n\t'.join(values)
        header = header + b': ' + value
        self._output(header)

    def endheaders(self, message_body=None):
        if self._HTTPConnection__state == _CS_REQ_STARTED:
            self._HTTPConnection__state = _CS_REQ_SENT
        else:
            raise CannotSendHeader()
        self._send_output(message_body)

    def request(self, method, url, body=None, headers={}):
        self._send_request(method, url, body, headers)

    def _set_content_length(self, body):
        thelen = None
        try:
            thelen = str(len(body))
        except TypeError as te:
            try:
                thelen = str(os.fstat(body.fileno()).st_size)
            except (AttributeError, OSError):
                if self.debuglevel > 0:
                    print('Cannot stat!!')
        if thelen is not None:
            self.putheader('Content-Length', thelen)

    def _send_request(self, method, url, body, headers):
        header_names = dict.fromkeys([k.lower() for k in headers])
        skips = {}
        if 'host' in header_names:
            skips['skip_host'] = 1
        if 'accept-encoding' in header_names:
            skips['skip_accept_encoding'] = 1
        self.putrequest(method, url, **skips)
        if body is not None and 'content-length' not in header_names:
            self._set_content_length(body)
        for (hdr, value) in headers.items():
            self.putheader(hdr, value)
        if isinstance(body, str):
            body = body.encode('iso-8859-1')
        self.endheaders(body)

    def getresponse(self):
        if self._HTTPConnection__response and self._HTTPConnection__response.isclosed():
            self._HTTPConnection__response = None
        if self._HTTPConnection__state != _CS_REQ_SENT or self._HTTPConnection__response:
            raise ResponseNotReady(self._HTTPConnection__state)
        if self.debuglevel > 0:
            response = self.response_class(self.sock, self.debuglevel, method=self._method)
        else:
            response = self.response_class(self.sock, method=self._method)
        response.begin()
        self._HTTPConnection__state = _CS_IDLE
        if response.will_close:
            self.close()
        else:
            self._HTTPConnection__response = response
        return response

try:
    import ssl
except ImportError:
    pass

class HTTPSConnection(HTTPConnection):
    __qualname__ = 'HTTPSConnection'
    default_port = HTTPS_PORT

    def __init__(self, host, port=None, key_file=None, cert_file=None, strict=_strict_sentinel, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, *, context=None, check_hostname=None):
        super(HTTPSConnection, self).__init__(host, port, strict, timeout, source_address)
        self.key_file = key_file
        self.cert_file = cert_file
        if context is None:
            context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        will_verify = context.verify_mode != ssl.CERT_NONE
        if check_hostname is None:
            check_hostname = will_verify
        elif check_hostname and not will_verify:
            raise ValueError('check_hostname needs a SSL context with either CERT_OPTIONAL or CERT_REQUIRED')
        if key_file or cert_file:
            context.load_cert_chain(cert_file, key_file)
        self._context = context
        self._check_hostname = check_hostname

    def connect(self):
        sock = socket.create_connection((self.host, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
        server_hostname = self.host if ssl.HAS_SNI else None
        self.sock = self._context.wrap_socket(sock, server_hostname=server_hostname)
        try:
            while self._check_hostname:
                ssl.match_hostname(self.sock.getpeercert(), self.host)
        except Exception:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            raise

__all__.append('HTTPSConnection')

class HTTPException(Exception):
    __qualname__ = 'HTTPException'

class NotConnected(HTTPException):
    __qualname__ = 'NotConnected'

class InvalidURL(HTTPException):
    __qualname__ = 'InvalidURL'

class UnknownProtocol(HTTPException):
    __qualname__ = 'UnknownProtocol'

    def __init__(self, version):
        self.args = (version,)
        self.version = version

class UnknownTransferEncoding(HTTPException):
    __qualname__ = 'UnknownTransferEncoding'

class UnimplementedFileMode(HTTPException):
    __qualname__ = 'UnimplementedFileMode'

class IncompleteRead(HTTPException):
    __qualname__ = 'IncompleteRead'

    def __init__(self, partial, expected=None):
        self.args = (partial,)
        self.partial = partial
        self.expected = expected

    def __repr__(self):
        if self.expected is not None:
            e = ', %i more expected' % self.expected
        else:
            e = ''
        return 'IncompleteRead(%i bytes read%s)' % (len(self.partial), e)

    def __str__(self):
        return repr(self)

class ImproperConnectionState(HTTPException):
    __qualname__ = 'ImproperConnectionState'

class CannotSendRequest(ImproperConnectionState):
    __qualname__ = 'CannotSendRequest'

class CannotSendHeader(ImproperConnectionState):
    __qualname__ = 'CannotSendHeader'

class ResponseNotReady(ImproperConnectionState):
    __qualname__ = 'ResponseNotReady'

class BadStatusLine(HTTPException):
    __qualname__ = 'BadStatusLine'

    def __init__(self, line):
        if not line:
            line = repr(line)
        self.args = (line,)
        self.line = line

class LineTooLong(HTTPException):
    __qualname__ = 'LineTooLong'

    def __init__(self, line_type):
        HTTPException.__init__(self, 'got more than %d bytes when reading %s' % (_MAXLINE, line_type))

error = HTTPException
