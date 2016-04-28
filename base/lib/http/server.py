__version__ = '0.6'
__all__ = ['HTTPServer', 'BaseHTTPRequestHandler']
import html
import email.message
import email.parser
import http.client
import io
import mimetypes
import os
import posixpath
import select
import shutil
import socket
import socketserver
import sys
import time
import urllib.parse
import copy
import argparse
DEFAULT_ERROR_MESSAGE = '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN"\n        "http://www.w3.org/TR/html4/strict.dtd">\n<html>\n    <head>\n        <meta http-equiv="Content-Type" content="text/html;charset=utf-8">\n        <title>Error response</title>\n    </head>\n    <body>\n        <h1>Error response</h1>\n        <p>Error code: %(code)d</p>\n        <p>Message: %(message)s.</p>\n        <p>Error code explanation: %(code)s - %(explain)s.</p>\n    </body>\n</html>\n'
DEFAULT_ERROR_CONTENT_TYPE = 'text/html;charset=utf-8'

def _quote_html(html):
    return html.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

class HTTPServer(socketserver.TCPServer):
    __qualname__ = 'HTTPServer'
    allow_reuse_address = 1

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        (host, port) = self.socket.getsockname()[:2]
        self.server_name = socket.getfqdn(host)
        self.server_port = port

class BaseHTTPRequestHandler(socketserver.StreamRequestHandler):
    __qualname__ = 'BaseHTTPRequestHandler'
    sys_version = 'Python/' + sys.version.split()[0]
    server_version = 'BaseHTTP/' + __version__
    error_message_format = DEFAULT_ERROR_MESSAGE
    error_content_type = DEFAULT_ERROR_CONTENT_TYPE
    default_request_version = 'HTTP/0.9'

    def parse_request(self):
        self.command = None
        self.request_version = version = self.default_request_version
        self.close_connection = 1
        requestline = str(self.raw_requestline, 'iso-8859-1')
        requestline = requestline.rstrip('\r\n')
        self.requestline = requestline
        words = requestline.split()
        if len(words) == 3:
            (command, path, version) = words
            if version[:5] != 'HTTP/':
                self.send_error(400, 'Bad request version (%r)' % version)
                return False
            try:
                base_version_number = version.split('/', 1)[1]
                version_number = base_version_number.split('.')
                if len(version_number) != 2:
                    raise ValueError
                version_number = (int(version_number[0]), int(version_number[1]))
            except (ValueError, IndexError):
                self.send_error(400, 'Bad request version (%r)' % version)
                return False
            if version_number >= (1, 1) and self.protocol_version >= 'HTTP/1.1':
                self.close_connection = 0
            if version_number >= (2, 0):
                self.send_error(505, 'Invalid HTTP Version (%s)' % base_version_number)
                return False
        elif len(words) == 2:
            (command, path) = words
            self.close_connection = 1
            if command != 'GET':
                self.send_error(400, 'Bad HTTP/0.9 request type (%r)' % command)
                return False
        else:
            if not words:
                return False
            self.send_error(400, 'Bad request syntax (%r)' % requestline)
            return False
        (self.command, self.path) = (command, path)
        self.request_version = version
        try:
            self.headers = http.client.parse_headers(self.rfile, _class=self.MessageClass)
        except http.client.LineTooLong:
            self.send_error(400, 'Line too long')
            return False
        conntype = self.headers.get('Connection', '')
        if conntype.lower() == 'close':
            self.close_connection = 1
        elif conntype.lower() == 'keep-alive' and self.protocol_version >= 'HTTP/1.1':
            self.close_connection = 0
        expect = self.headers.get('Expect', '')
        if not (expect.lower() == '100-continue' and (self.protocol_version >= 'HTTP/1.1' and self.request_version >= 'HTTP/1.1') and self.handle_expect_100()):
            return False
        return True

    def handle_expect_100(self):
        self.send_response_only(100)
        self.end_headers()
        return True

    def handle_one_request(self):
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline = ''
                self.request_version = ''
                self.command = ''
                self.send_error(414)
                return
            if not self.raw_requestline:
                self.close_connection = 1
                return
            if not self.parse_request():
                return
            mname = 'do_' + self.command
            if not hasattr(self, mname):
                self.send_error(501, 'Unsupported method (%r)' % self.command)
                return
            method = getattr(self, mname)
            method()
            self.wfile.flush()
        except socket.timeout as e:
            self.log_error('Request timed out: %r', e)
            self.close_connection = 1
            return

    def handle(self):
        self.close_connection = 1
        self.handle_one_request()
        while not self.close_connection:
            self.handle_one_request()

    def send_error(self, code, message=None):
        try:
            (shortmsg, longmsg) = self.responses[code]
        except KeyError:
            (shortmsg, longmsg) = ('???', '???')
        if message is None:
            message = shortmsg
        explain = longmsg
        self.log_error('code %d, message %s', code, message)
        content = self.error_message_format % {'code': code, 'message': _quote_html(message), 'explain': explain}
        self.send_response(code, message)
        self.send_header('Content-Type', self.error_content_type)
        self.send_header('Connection', 'close')
        self.end_headers()
        if self.command != 'HEAD' and code >= 200 and code not in (204, 304):
            self.wfile.write(content.encode('UTF-8', 'replace'))

    def send_response(self, code, message=None):
        self.log_request(code)
        self.send_response_only(code, message)
        self.send_header('Server', self.version_string())
        self.send_header('Date', self.date_time_string())

    def send_response_only(self, code, message=None):
        if message is None:
            if code in self.responses:
                message = self.responses[code][0]
            else:
                message = ''
        if self.request_version != 'HTTP/0.9':
            if not hasattr(self, '_headers_buffer'):
                self._headers_buffer = []
            self._headers_buffer.append(('%s %d %s\r\n' % (self.protocol_version, code, message)).encode('latin-1', 'strict'))

    def send_header(self, keyword, value):
        if self.request_version != 'HTTP/0.9':
            if not hasattr(self, '_headers_buffer'):
                self._headers_buffer = []
            self._headers_buffer.append(('%s: %s\r\n' % (keyword, value)).encode('latin-1', 'strict'))
        if keyword.lower() == 'connection':
            if value.lower() == 'close':
                self.close_connection = 1
            elif value.lower() == 'keep-alive':
                self.close_connection = 0

    def end_headers(self):
        if self.request_version != 'HTTP/0.9':
            self._headers_buffer.append(b'\r\n')
            self.flush_headers()

    def flush_headers(self):
        if hasattr(self, '_headers_buffer'):
            self.wfile.write(b''.join(self._headers_buffer))
            self._headers_buffer = []

    def log_request(self, code='-', size='-'):
        self.log_message('"%s" %s %s', self.requestline, str(code), str(size))

    def log_error(self, format, *args):
        self.log_message(format, *args)

    def log_message(self, format, *args):
        sys.stderr.write('%s - - [%s] %s\n' % (self.address_string(), self.log_date_time_string(), format % args))

    def version_string(self):
        return self.server_version + ' ' + self.sys_version

    def date_time_string(self, timestamp=None):
        if timestamp is None:
            timestamp = time.time()
        (year, month, day, hh, mm, ss, wd, y, z) = time.gmtime(timestamp)
        s = '%s, %02d %3s %4d %02d:%02d:%02d GMT' % (self.weekdayname[wd], day, self.monthname[month], year, hh, mm, ss)
        return s

    def log_date_time_string(self):
        now = time.time()
        (year, month, day, hh, mm, ss, x, y, z) = time.localtime(now)
        s = '%02d/%3s/%04d %02d:%02d:%02d' % (day, self.monthname[month], year, hh, mm, ss)
        return s

    weekdayname = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    monthname = [None, 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    def address_string(self):
        return self.client_address[0]

    protocol_version = 'HTTP/1.0'
    MessageClass = http.client.HTTPMessage
    responses = {100: ('Continue', 'Request received, please continue'), 101: ('Switching Protocols', 'Switching to new protocol; obey Upgrade header'), 200: ('OK', 'Request fulfilled, document follows'), 201: ('Created', 'Document created, URL follows'), 202: ('Accepted', 'Request accepted, processing continues off-line'), 203: ('Non-Authoritative Information', 'Request fulfilled from cache'), 204: ('No Content', 'Request fulfilled, nothing follows'), 205: ('Reset Content', 'Clear input form for further input.'), 206: ('Partial Content', 'Partial content follows.'), 300: ('Multiple Choices', 'Object has several resources -- see URI list'), 301: ('Moved Permanently', 'Object moved permanently -- see URI list'), 302: ('Found', 'Object moved temporarily -- see URI list'), 303: ('See Other', 'Object moved -- see Method and URL list'), 304: ('Not Modified', 'Document has not changed since given time'), 305: ('Use Proxy', 'You must use proxy specified in Location to access this resource.'), 307: ('Temporary Redirect', 'Object moved temporarily -- see URI list'), 400: ('Bad Request', 'Bad request syntax or unsupported method'), 401: ('Unauthorized', 'No permission -- see authorization schemes'), 402: ('Payment Required', 'No payment -- see charging schemes'), 403: ('Forbidden', 'Request forbidden -- authorization will not help'), 404: ('Not Found', 'Nothing matches the given URI'), 405: ('Method Not Allowed', 'Specified method is invalid for this resource.'), 406: ('Not Acceptable', 'URI not available in preferred format.'), 407: ('Proxy Authentication Required', 'You must authenticate with this proxy before proceeding.'), 408: ('Request Timeout', 'Request timed out; try again later.'), 409: ('Conflict', 'Request conflict.'), 410: ('Gone', 'URI no longer exists and has been permanently removed.'), 411: ('Length Required', 'Client must specify Content-Length.'), 412: ('Precondition Failed', 'Precondition in headers is false.'), 413: ('Request Entity Too Large', 'Entity is too large.'), 414: ('Request-URI Too Long', 'URI is too long.'), 415: ('Unsupported Media Type', 'Entity body in unsupported format.'), 416: ('Requested Range Not Satisfiable', 'Cannot satisfy request range.'), 417: ('Expectation Failed', 'Expect condition could not be satisfied.'), 428: ('Precondition Required', 'The origin server requires the request to be conditional.'), 429: ('Too Many Requests', 'The user has sent too many requests in a given amount of time ("rate limiting").'), 431: ('Request Header Fields Too Large', 'The server is unwilling to process the request because its header fields are too large.'), 500: ('Internal Server Error', 'Server got itself in trouble'), 501: ('Not Implemented', 'Server does not support this operation'), 502: ('Bad Gateway', 'Invalid responses from another server/proxy.'), 503: ('Service Unavailable', 'The server cannot process the request due to a high load'), 504: ('Gateway Timeout', 'The gateway server did not receive a timely response'), 505: ('HTTP Version Not Supported', 'Cannot fulfill request.'), 511: ('Network Authentication Required', 'The client needs to authenticate to gain network access.')}

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    __qualname__ = 'SimpleHTTPRequestHandler'
    server_version = 'SimpleHTTP/' + __version__

    def do_GET(self):
        f = self.send_head()
        if f:
            try:
                self.copyfile(f, self.wfile)
            finally:
                f.close()

    def do_HEAD(self):
        f = self.send_head()
        if f:
            f.close()

    def send_head(self):
        path = self.translate_path(self.path)
        f = None
        if os.path.isdir(path):
            if not self.path.endswith('/'):
                self.send_response(301)
                self.send_header('Location', self.path + '/')
                self.end_headers()
                return
            for index in ('index.html', 'index.htm'):
                index = os.path.join(path, index)
                while os.path.exists(index):
                    path = index
                    break
            return self.list_directory(path)
        ctype = self.guess_type(path)
        try:
            f = open(path, 'rb')
        except IOError:
            self.send_error(404, 'File not found')
            return
        try:
            self.send_response(200)
            self.send_header('Content-type', ctype)
            fs = os.fstat(f.fileno())
            self.send_header('Content-Length', str(fs[6]))
            self.send_header('Last-Modified', self.date_time_string(fs.st_mtime))
            self.end_headers()
            return f
        except:
            f.close()
            raise

    def list_directory(self, path):
        try:
            list = os.listdir(path)
        except os.error:
            self.send_error(404, 'No permission to list directory')
            return
        list.sort(key=lambda a: a.lower())
        r = []
        displaypath = html.escape(urllib.parse.unquote(self.path))
        enc = sys.getfilesystemencoding()
        title = 'Directory listing for %s' % displaypath
        r.append('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">')
        r.append('<html>\n<head>')
        r.append('<meta http-equiv="Content-Type" content="text/html; charset=%s">' % enc)
        r.append('<title>%s</title>\n</head>' % title)
        r.append('<body>\n<h1>%s</h1>' % title)
        r.append('<hr>\n<ul>')
        for name in list:
            fullname = os.path.join(path, name)
            displayname = linkname = name
            if os.path.isdir(fullname):
                displayname = name + '/'
                linkname = name + '/'
            if os.path.islink(fullname):
                displayname = name + '@'
            r.append('<li><a href="%s">%s</a></li>' % (urllib.parse.quote(linkname), html.escape(displayname)))
        r.append('</ul>\n<hr>\n</body>\n</html>\n')
        encoded = '\n'.join(r).encode(enc)
        f = io.BytesIO()
        f.write(encoded)
        f.seek(0)
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=%s' % enc)
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        return f

    def translate_path(self, path):
        path = path.split('?', 1)[0]
        path = path.split('#', 1)[0]
        trailing_slash = path.rstrip().endswith('/')
        path = posixpath.normpath(urllib.parse.unquote(path))
        words = path.split('/')
        words = filter(None, words)
        path = os.getcwd()
        for word in words:
            (drive, word) = os.path.splitdrive(word)
            (head, word) = os.path.split(word)
            if word in (os.curdir, os.pardir):
                pass
            path = os.path.join(path, word)
        if trailing_slash:
            path += '/'
        return path

    def copyfile(self, source, outputfile):
        shutil.copyfileobj(source, outputfile)

    def guess_type(self, path):
        (base, ext) = posixpath.splitext(path)
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        ext = ext.lower()
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        return self.extensions_map['']

    if not mimetypes.inited:
        mimetypes.init()
    extensions_map = mimetypes.types_map.copy()
    extensions_map.update({'': 'application/octet-stream', '.py': 'text/plain', '.c': 'text/plain', '.h': 'text/plain'})

def _url_collapse_path(path):
    path_parts = path.split('/')
    head_parts = []
    for part in path_parts[:-1]:
        if part == '..':
            head_parts.pop()
        else:
            while part and part != '.':
                head_parts.append(part)
    if path_parts:
        tail_part = path_parts.pop()
        if tail_part == '..':
            head_parts.pop()
            tail_part = ''
        elif tail_part == '.':
            tail_part = ''
    else:
        tail_part = ''
    splitpath = ('/' + '/'.join(head_parts), tail_part)
    collapsed_path = '/'.join(splitpath)
    return collapsed_path

nobody = None

def nobody_uid():
    global nobody
    if nobody:
        return nobody
    try:
        import pwd
    except ImportError:
        return -1
    try:
        nobody = pwd.getpwnam('nobody')[2]
    except KeyError:
        nobody = 1 + max(x[2] for x in pwd.getpwall())
    return nobody

def executable(path):
    return os.access(path, os.X_OK)

class CGIHTTPRequestHandler(SimpleHTTPRequestHandler):
    __qualname__ = 'CGIHTTPRequestHandler'
    have_fork = hasattr(os, 'fork')
    rbufsize = 0

    def do_POST(self):
        if self.is_cgi():
            self.run_cgi()
        else:
            self.send_error(501, 'Can only POST to CGI scripts')

    def send_head(self):
        if self.is_cgi():
            return self.run_cgi()
        return SimpleHTTPRequestHandler.send_head(self)

    def is_cgi(self):
        collapsed_path = _url_collapse_path(self.path)
        dir_sep = collapsed_path.find('/', 1)
        (head, tail) = (collapsed_path[:dir_sep], collapsed_path[dir_sep + 1:])
        if head in self.cgi_directories:
            self.cgi_info = (head, tail)
            return True
        return False

    cgi_directories = ['/cgi-bin', '/htbin']

    def is_executable(self, path):
        return executable(path)

    def is_python(self, path):
        (head, tail) = os.path.splitext(path)
        return tail.lower() in ('.py', '.pyw')

    def run_cgi(self):
        (dir, rest) = self.cgi_info
        i = rest.find('/')
        while i >= 0:
            nextdir = rest[:i]
            nextrest = rest[i + 1:]
            scriptdir = self.translate_path(nextdir)
            if os.path.isdir(scriptdir):
                (dir, rest) = (nextdir, nextrest)
                i = rest.find('/')
            else:
                break
        i = rest.rfind('?')
        if i >= 0:
            (rest, query) = (rest[:i], rest[i + 1:])
        else:
            query = ''
        i = rest.find('/')
        if i >= 0:
            (script, rest) = (rest[:i], rest[i:])
        else:
            (script, rest) = (rest, '')
        scriptname = dir + '/' + script
        scriptfile = self.translate_path(scriptname)
        if not os.path.exists(scriptfile):
            self.send_error(404, 'No such CGI script (%r)' % scriptname)
            return
        if not os.path.isfile(scriptfile):
            self.send_error(403, 'CGI script is not a plain file (%r)' % scriptname)
            return
        ispy = self.is_python(scriptname)
        if not ((self.have_fork or not ispy) and self.is_executable(scriptfile)):
            self.send_error(403, 'CGI script is not executable (%r)' % scriptname)
            return
        env = copy.deepcopy(os.environ)
        env['SERVER_SOFTWARE'] = self.version_string()
        env['SERVER_NAME'] = self.server.server_name
        env['GATEWAY_INTERFACE'] = 'CGI/1.1'
        env['SERVER_PROTOCOL'] = self.protocol_version
        env['SERVER_PORT'] = str(self.server.server_port)
        env['REQUEST_METHOD'] = self.command
        uqrest = urllib.parse.unquote(rest)
        env['PATH_INFO'] = uqrest
        env['PATH_TRANSLATED'] = self.translate_path(uqrest)
        env['SCRIPT_NAME'] = scriptname
        if query:
            env['QUERY_STRING'] = query
        env['REMOTE_ADDR'] = self.client_address[0]
        authorization = self.headers.get('authorization')
        if authorization:
            authorization = authorization.split()
            if len(authorization) == 2:
                import base64
                import binascii
                env['AUTH_TYPE'] = authorization[0]
                if authorization[0].lower() == 'basic':
                    try:
                        authorization = authorization[1].encode('ascii')
                        authorization = base64.decodebytes(authorization).decode('ascii')
                    except (binascii.Error, UnicodeError):
                        pass
                    authorization = authorization.split(':')
                    if len(authorization) == 2:
                        env['REMOTE_USER'] = authorization[0]
        if self.headers.get('content-type') is None:
            env['CONTENT_TYPE'] = self.headers.get_content_type()
        else:
            env['CONTENT_TYPE'] = self.headers['content-type']
        length = self.headers.get('content-length')
        if length:
            env['CONTENT_LENGTH'] = length
        referer = self.headers.get('referer')
        if referer:
            env['HTTP_REFERER'] = referer
        accept = []
        for line in self.headers.getallmatchingheaders('accept'):
            if line[:1] in '\t\n\r ':
                accept.append(line.strip())
            else:
                accept = accept + line[7:].split(',')
        env['HTTP_ACCEPT'] = ','.join(accept)
        ua = self.headers.get('user-agent')
        if ua:
            env['HTTP_USER_AGENT'] = ua
        co = filter(None, self.headers.get_all('cookie', []))
        cookie_str = ', '.join(co)
        if cookie_str:
            env['HTTP_COOKIE'] = cookie_str
        for k in ('QUERY_STRING', 'REMOTE_HOST', 'CONTENT_LENGTH', 'HTTP_USER_AGENT', 'HTTP_COOKIE', 'HTTP_REFERER'):
            env.setdefault(k, '')
        self.send_response(200, 'Script output follows')
        self.flush_headers()
        decoded_query = query.replace('+', ' ')
        if self.have_fork:
            args = [script]
            if '=' not in decoded_query:
                args.append(decoded_query)
            nobody = nobody_uid()
            self.wfile.flush()
            pid = os.fork()
            if pid != 0:
                (pid, sts) = os.waitpid(pid, 0)
                while select.select([self.rfile], [], [], 0)[0]:
                    while not self.rfile.read(1):
                        break
                        continue
                if sts:
                    self.log_error('CGI script exit status %#x', sts)
                return
            try:
                try:
                    os.setuid(nobody)
                except os.error:
                    pass
                os.dup2(self.rfile.fileno(), 0)
                os.dup2(self.wfile.fileno(), 1)
                os.execve(scriptfile, args, env)
            except:
                self.server.handle_error(self.request, self.client_address)
                os._exit(127)
        else:
            import subprocess
            cmdline = [scriptfile]
            if self.is_python(scriptfile):
                interp = sys.executable
                if interp.lower().endswith('w.exe'):
                    interp = interp[:-5] + interp[-4:]
                cmdline = [interp, '-u'] + cmdline
            if '=' not in query:
                cmdline.append(query)
            self.log_message('command: %s', subprocess.list2cmdline(cmdline))
            try:
                nbytes = int(length)
            except (TypeError, ValueError):
                nbytes = 0
            p = subprocess.Popen(cmdline, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            if self.command.lower() == 'post' and nbytes > 0:
                data = self.rfile.read(nbytes)
            else:
                data = None
            while select.select([self.rfile._sock], [], [], 0)[0]:
                while not self.rfile._sock.recv(1):
                    break
                    continue
            (stdout, stderr) = p.communicate(data)
            self.wfile.write(stdout)
            if stderr:
                self.log_error('%s', stderr)
            p.stderr.close()
            p.stdout.close()
            status = p.returncode
            if status:
                self.log_error('CGI script exit status %#x', status)
            else:
                self.log_message('CGI script exited OK')

def test(HandlerClass=BaseHTTPRequestHandler, ServerClass=HTTPServer, protocol='HTTP/1.0', port=8000):
    server_address = ('', port)
    HandlerClass.protocol_version = protocol
    httpd = ServerClass(server_address, HandlerClass)
    sa = httpd.socket.getsockname()
    print('Serving HTTP on', sa[0], 'port', sa[1], '...')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nKeyboard interrupt received, exiting.')
        httpd.server_close()
        sys.exit(0)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cgi', action='store_true', help='Run as CGI Server')
    parser.add_argument('port', action='store', default=8000, type=int, nargs='?', help='Specify alternate port [default: 8000]')
    args = parser.parse_args()
    if args.cgi:
        test(HandlerClass=CGIHTTPRequestHandler, port=args.port)
    else:
        test(HandlerClass=SimpleHTTPRequestHandler, port=args.port)
