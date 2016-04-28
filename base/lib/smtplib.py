import socket
import io
import re
import email.utils
import email.message
import email.generator
import base64
import hmac
import copy
from email.base64mime import body_encode as encode_base64
from sys import stderr
__all__ = ['SMTPException', 'SMTPServerDisconnected', 'SMTPResponseException', 'SMTPSenderRefused', 'SMTPRecipientsRefused', 'SMTPDataError', 'SMTPConnectError', 'SMTPHeloError', 'SMTPAuthenticationError', 'quoteaddr', 'quotedata', 'SMTP']
SMTP_PORT = 25
SMTP_SSL_PORT = 465
CRLF = '\r\n'
bCRLF = b'\r\n'
_MAXLINE = 8192
OLDSTYLE_AUTH = re.compile('auth=(.*)', re.I)

class SMTPException(Exception):
    __qualname__ = 'SMTPException'

class SMTPServerDisconnected(SMTPException):
    __qualname__ = 'SMTPServerDisconnected'

class SMTPResponseException(SMTPException):
    __qualname__ = 'SMTPResponseException'

    def __init__(self, code, msg):
        self.smtp_code = code
        self.smtp_error = msg
        self.args = (code, msg)

class SMTPSenderRefused(SMTPResponseException):
    __qualname__ = 'SMTPSenderRefused'

    def __init__(self, code, msg, sender):
        self.smtp_code = code
        self.smtp_error = msg
        self.sender = sender
        self.args = (code, msg, sender)

class SMTPRecipientsRefused(SMTPException):
    __qualname__ = 'SMTPRecipientsRefused'

    def __init__(self, recipients):
        self.recipients = recipients
        self.args = (recipients,)

class SMTPDataError(SMTPResponseException):
    __qualname__ = 'SMTPDataError'

class SMTPConnectError(SMTPResponseException):
    __qualname__ = 'SMTPConnectError'

class SMTPHeloError(SMTPResponseException):
    __qualname__ = 'SMTPHeloError'

class SMTPAuthenticationError(SMTPResponseException):
    __qualname__ = 'SMTPAuthenticationError'

def quoteaddr(addrstring):
    (displayname, addr) = email.utils.parseaddr(addrstring)
    if (displayname, addr) == ('', ''):
        if addrstring.strip().startswith('<'):
            return addrstring
        return '<%s>' % addrstring
    return '<%s>' % addr

def _addr_only(addrstring):
    (displayname, addr) = email.utils.parseaddr(addrstring)
    if (displayname, addr) == ('', ''):
        return addrstring
    return addr

def quotedata(data):
    return re.sub('(?m)^\\.', '..', re.sub('(?:\\r\\n|\\n|\\r(?!\\n))', CRLF, data))

def _quote_periods(bindata):
    return re.sub(b'(?m)^\\.', b'..', bindata)

def _fix_eols(data):
    return re.sub('(?:\\r\\n|\\n|\\r(?!\\n))', CRLF, data)

try:
    import ssl
except ImportError:
    _have_ssl = False
_have_ssl = True

class SMTP:
    __qualname__ = 'SMTP'
    debuglevel = 0
    file = None
    helo_resp = None
    ehlo_msg = 'ehlo'
    ehlo_resp = None
    does_esmtp = 0
    default_port = SMTP_PORT

    def __init__(self, host='', port=0, local_hostname=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        self.timeout = timeout
        self.esmtp_features = {}
        self.source_address = source_address
        if host:
            (code, msg) = self.connect(host, port)
            if code != 220:
                raise SMTPConnectError(code, msg)
        if local_hostname is not None:
            self.local_hostname = local_hostname
        else:
            fqdn = socket.getfqdn()
            if '.' in fqdn:
                self.local_hostname = fqdn
            else:
                addr = '127.0.0.1'
                try:
                    addr = socket.gethostbyname(socket.gethostname())
                except socket.gaierror:
                    pass
                self.local_hostname = '[%s]' % addr

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            (code, message) = self.docmd('QUIT')
            while code != 221:
                raise SMTPResponseException(code, message)
        except SMTPServerDisconnected:
            pass
        finally:
            self.close()

    def set_debuglevel(self, debuglevel):
        self.debuglevel = debuglevel

    def _get_socket(self, host, port, timeout):
        if self.debuglevel > 0:
            print('connect: to', (host, port), self.source_address, file=stderr)
        return socket.create_connection((host, port), timeout, self.source_address)

    def connect(self, host='localhost', port=0, source_address=None):
        if source_address:
            self.source_address = source_address
        if not port and host.find(':') == host.rfind(':'):
            i = host.rfind(':')
            if i >= 0:
                (host, port) = (host[:i], host[i + 1:])
                try:
                    port = int(port)
                except ValueError:
                    raise socket.error('nonnumeric port')
        if not port:
            port = self.default_port
        if self.debuglevel > 0:
            print('connect:', (host, port), file=stderr)
        self.sock = self._get_socket(host, port, self.timeout)
        self.file = None
        (code, msg) = self.getreply()
        if self.debuglevel > 0:
            print('connect:', msg, file=stderr)
        return (code, msg)

    def send(self, s):
        if self.debuglevel > 0:
            print('send:', repr(s), file=stderr)
        if hasattr(self, 'sock') and self.sock:
            if isinstance(s, str):
                s = s.encode('ascii')
            try:
                self.sock.sendall(s)
            except socket.error:
                self.close()
                raise SMTPServerDisconnected('Server not connected')
        else:
            raise SMTPServerDisconnected('please run connect() first')

    def putcmd(self, cmd, args=''):
        if args == '':
            str = '%s%s' % (cmd, CRLF)
        else:
            str = '%s %s%s' % (cmd, args, CRLF)
        self.send(str)

    def getreply(self):
        resp = []
        if self.file is None:
            self.file = self.sock.makefile('rb')
        while True:
            try:
                line = self.file.readline(_MAXLINE + 1)
            except socket.error as e:
                self.close()
                raise SMTPServerDisconnected('Connection unexpectedly closed: ' + str(e))
            if not line:
                self.close()
                raise SMTPServerDisconnected('Connection unexpectedly closed')
            if self.debuglevel > 0:
                print('reply:', repr(line), file=stderr)
            if len(line) > _MAXLINE:
                raise SMTPResponseException(500, 'Line too long.')
            resp.append(line[4:].strip(b' \t\r\n'))
            code = line[:3]
            try:
                errcode = int(code)
            except ValueError:
                errcode = -1
                break
            if line[3:4] != b'-':
                break
        errmsg = b'\n'.join(resp)
        if self.debuglevel > 0:
            print('reply: retcode (%s); Msg: %s' % (errcode, errmsg), file=stderr)
        return (errcode, errmsg)

    def docmd(self, cmd, args=''):
        self.putcmd(cmd, args)
        return self.getreply()

    def helo(self, name=''):
        self.putcmd('helo', name or self.local_hostname)
        (code, msg) = self.getreply()
        self.helo_resp = msg
        return (code, msg)

    def ehlo(self, name=''):
        self.esmtp_features = {}
        self.putcmd(self.ehlo_msg, name or self.local_hostname)
        (code, msg) = self.getreply()
        if code == -1 and len(msg) == 0:
            self.close()
            raise SMTPServerDisconnected('Server not connected')
        self.ehlo_resp = msg
        if code != 250:
            return (code, msg)
        self.does_esmtp = 1
        resp = self.ehlo_resp.decode('latin-1').split('\n')
        del resp[0]
        for each in resp:
            auth_match = OLDSTYLE_AUTH.match(each)
            if auth_match:
                self.esmtp_features['auth'] = self.esmtp_features.get('auth', '') + ' ' + auth_match.groups(0)[0]
            m = re.match('(?P<feature>[A-Za-z0-9][A-Za-z0-9\\-]*) ?', each)
            while m:
                feature = m.group('feature').lower()
                params = m.string[m.end('feature'):].strip()
                if feature == 'auth':
                    self.esmtp_features[feature] = self.esmtp_features.get(feature, '') + ' ' + params
                else:
                    self.esmtp_features[feature] = params
        return (code, msg)

    def has_extn(self, opt):
        return opt.lower() in self.esmtp_features

    def help(self, args=''):
        self.putcmd('help', args)
        return self.getreply()[1]

    def rset(self):
        return self.docmd('rset')

    def noop(self):
        return self.docmd('noop')

    def mail(self, sender, options=[]):
        optionlist = ''
        if options and self.does_esmtp:
            optionlist = ' ' + ' '.join(options)
        self.putcmd('mail', 'FROM:%s%s' % (quoteaddr(sender), optionlist))
        return self.getreply()

    def rcpt(self, recip, options=[]):
        optionlist = ''
        if options and self.does_esmtp:
            optionlist = ' ' + ' '.join(options)
        self.putcmd('rcpt', 'TO:%s%s' % (quoteaddr(recip), optionlist))
        return self.getreply()

    def data(self, msg):
        self.putcmd('data')
        (code, repl) = self.getreply()
        if self.debuglevel > 0:
            print('data:', (code, repl), file=stderr)
        if code != 354:
            raise SMTPDataError(code, repl)
        else:
            if isinstance(msg, str):
                msg = _fix_eols(msg).encode('ascii')
            q = _quote_periods(msg)
            if q[-2:] != bCRLF:
                q = q + bCRLF
            q = q + b'.' + bCRLF
            self.send(q)
            (code, msg) = self.getreply()
            if self.debuglevel > 0:
                print('data:', (code, msg), file=stderr)
            return (code, msg)

    def verify(self, address):
        self.putcmd('vrfy', _addr_only(address))
        return self.getreply()

    vrfy = verify

    def expn(self, address):
        self.putcmd('expn', _addr_only(address))
        return self.getreply()

    def ehlo_or_helo_if_needed(self):
        if self.helo_resp is None and self.ehlo_resp is None:
            if not 200 <= self.ehlo()[0] <= 299:
                (code, resp) = self.helo()
                if not 200 <= code <= 299:
                    raise SMTPHeloError(code, resp)

    def login(self, user, password):

        def encode_cram_md5(challenge, user, password):
            challenge = base64.decodebytes(challenge)
            response = user + ' ' + hmac.HMAC(password.encode('ascii'), challenge).hexdigest()
            return encode_base64(response.encode('ascii'), eol='')

        def encode_plain(user, password):
            s = '\x00%s\x00%s' % (user, password)
            return encode_base64(s.encode('ascii'), eol='')

        AUTH_PLAIN = 'PLAIN'
        AUTH_CRAM_MD5 = 'CRAM-MD5'
        AUTH_LOGIN = 'LOGIN'
        self.ehlo_or_helo_if_needed()
        if not self.has_extn('auth'):
            raise SMTPException('SMTP AUTH extension not supported by server.')
        advertised_authlist = self.esmtp_features['auth'].split()
        preferred_auths = [AUTH_CRAM_MD5, AUTH_PLAIN, AUTH_LOGIN]
        authlist = [auth for auth in preferred_auths if auth in advertised_authlist]
        if not authlist:
            raise SMTPException('No suitable authentication method found.')
        for authmethod in authlist:
            if authmethod == AUTH_CRAM_MD5:
                (code, resp) = self.docmd('AUTH', AUTH_CRAM_MD5)
                if code == 334:
                    (code, resp) = self.docmd(encode_cram_md5(resp, user, password))
            elif authmethod == AUTH_PLAIN:
                (code, resp) = self.docmd('AUTH', AUTH_PLAIN + ' ' + encode_plain(user, password))
            elif authmethod == AUTH_LOGIN:
                (code, resp) = self.docmd('AUTH', '%s %s' % (AUTH_LOGIN, encode_base64(user.encode('ascii'), eol='')))
                if code == 334:
                    (code, resp) = self.docmd(encode_base64(password.encode('ascii'), eol=''))
            while code in (235, 503):
                return (code, resp)
        raise SMTPAuthenticationError(code, resp)

    def starttls(self, keyfile=None, certfile=None, context=None):
        self.ehlo_or_helo_if_needed()
        if not self.has_extn('starttls'):
            raise SMTPException('STARTTLS extension not supported by server.')
        (resp, reply) = self.docmd('STARTTLS')
        if resp == 220:
            if not _have_ssl:
                raise RuntimeError('No SSL support included in this Python')
            if context is not None and keyfile is not None:
                raise ValueError('context and keyfile arguments are mutually exclusive')
            if context is not None and certfile is not None:
                raise ValueError('context and certfile arguments are mutually exclusive')
            if context is not None:
                self.sock = context.wrap_socket(self.sock)
            else:
                self.sock = ssl.wrap_socket(self.sock, keyfile, certfile)
            self.file = None
            self.helo_resp = None
            self.ehlo_resp = None
            self.esmtp_features = {}
            self.does_esmtp = 0
        return (resp, reply)

    def sendmail(self, from_addr, to_addrs, msg, mail_options=[], rcpt_options=[]):
        self.ehlo_or_helo_if_needed()
        esmtp_opts = []
        if isinstance(msg, str):
            msg = _fix_eols(msg).encode('ascii')
        if self.does_esmtp:
            if self.has_extn('size'):
                esmtp_opts.append('size=%d' % len(msg))
            for option in mail_options:
                esmtp_opts.append(option)
        (code, resp) = self.mail(from_addr, esmtp_opts)
        if code != 250:
            if code == 421:
                self.close()
            else:
                self.rset()
            raise SMTPSenderRefused(code, resp, from_addr)
        senderrs = {}
        if isinstance(to_addrs, str):
            to_addrs = [to_addrs]
        for each in to_addrs:
            (code, resp) = self.rcpt(each, rcpt_options)
            if code != 250 and code != 251:
                senderrs[each] = (code, resp)
            while code == 421:
                self.close()
                raise SMTPRecipientsRefused(senderrs)
        if len(senderrs) == len(to_addrs):
            self.rset()
            raise SMTPRecipientsRefused(senderrs)
        (code, resp) = self.data(msg)
        if code != 250:
            if code == 421:
                self.close()
            else:
                self.rset()
            raise SMTPDataError(code, resp)
        return senderrs

    def send_message(self, msg, from_addr=None, to_addrs=None, mail_options=[], rcpt_options={}):
        resent = msg.get_all('Resent-Date')
        if resent is None:
            header_prefix = ''
        elif len(resent) == 1:
            header_prefix = 'Resent-'
        else:
            raise ValueError("message has more than one 'Resent-' header block")
        if from_addr is None:
            from_addr = msg[header_prefix + 'Sender'] if header_prefix + 'Sender' in msg else msg[header_prefix + 'From']
        if to_addrs is None:
            addr_fields = [f for f in (msg[header_prefix + 'To'], msg[header_prefix + 'Bcc'], msg[header_prefix + 'Cc']) if f is not None]
            to_addrs = [a[1] for a in email.utils.getaddresses(addr_fields)]
        msg_copy = copy.copy(msg)
        del msg_copy['Bcc']
        del msg_copy['Resent-Bcc']
        with io.BytesIO() as bytesmsg:
            g = email.generator.BytesGenerator(bytesmsg)
            g.flatten(msg_copy, linesep='\r\n')
            flatmsg = bytesmsg.getvalue()
        return self.sendmail(from_addr, to_addrs, flatmsg, mail_options, rcpt_options)

    def close(self):
        if self.file:
            self.file.close()
        self.file = None
        if self.sock:
            self.sock.close()
        self.sock = None

    def quit(self):
        res = self.docmd('quit')
        self.close()
        return res

if _have_ssl:

    class SMTP_SSL(SMTP):
        __qualname__ = 'SMTP_SSL'
        default_port = SMTP_SSL_PORT

        def __init__(self, host='', port=0, local_hostname=None, keyfile=None, certfile=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, context=None):
            if context is not None and keyfile is not None:
                raise ValueError('context and keyfile arguments are mutually exclusive')
            if context is not None and certfile is not None:
                raise ValueError('context and certfile arguments are mutually exclusive')
            self.keyfile = keyfile
            self.certfile = certfile
            self.context = context
            SMTP.__init__(self, host, port, local_hostname, timeout, source_address)

        def _get_socket(self, host, port, timeout):
            if self.debuglevel > 0:
                print('connect:', (host, port), file=stderr)
            new_socket = socket.create_connection((host, port), timeout, self.source_address)
            if self.context is not None:
                new_socket = self.context.wrap_socket(new_socket)
            else:
                new_socket = ssl.wrap_socket(new_socket, self.keyfile, self.certfile)
            return new_socket

    __all__.append('SMTP_SSL')
LMTP_PORT = 2003

class LMTP(SMTP):
    __qualname__ = 'LMTP'
    ehlo_msg = 'lhlo'

    def __init__(self, host='', port=LMTP_PORT, local_hostname=None, source_address=None):
        SMTP.__init__(self, host, port, local_hostname=local_hostname, source_address=source_address)

    def connect(self, host='localhost', port=0, source_address=None):
        if host[0] != '/':
            return SMTP.connect(self, host, port, source_address=source_address)
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.file = None
            self.sock.connect(host)
        except socket.error:
            if self.debuglevel > 0:
                print('connect fail:', host, file=stderr)
            if self.sock:
                self.sock.close()
            self.sock = None
            raise
        (code, msg) = self.getreply()
        if self.debuglevel > 0:
            print('connect:', msg, file=stderr)
        return (code, msg)

if __name__ == '__main__':
    import sys

    def prompt(prompt):
        sys.stdout.write(prompt + ': ')
        sys.stdout.flush()
        return sys.stdin.readline().strip()

    fromaddr = prompt('From')
    toaddrs = prompt('To').split(',')
    print('Enter message, end with ^D:')
    msg = ''
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        msg = msg + line
    print('Message length is %d' % len(msg))
    server = SMTP('localhost')
    server.set_debuglevel(1)
    server.sendmail(fromaddr, toaddrs, msg)
    server.quit()
