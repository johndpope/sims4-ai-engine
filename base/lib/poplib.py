import re
import socket
__all__ = ['POP3', 'error_proto']

class error_proto(Exception):
    __qualname__ = 'error_proto'

POP3_PORT = 110
POP3_SSL_PORT = 995
CR = b'\r'
LF = b'\n'
CRLF = CR + LF
_MAXLINE = 2048

class POP3:
    __qualname__ = 'POP3'
    encoding = 'UTF-8'

    def __init__(self, host, port=POP3_PORT, timeout=socket._GLOBAL_DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.sock = self._create_socket(timeout)
        self.file = self.sock.makefile('rb')
        self._debugging = 0
        self.welcome = self._getresp()

    def _create_socket(self, timeout):
        return socket.create_connection((self.host, self.port), timeout)

    def _putline(self, line):
        if self._debugging > 1:
            print('*put*', repr(line))
        self.sock.sendall(line + CRLF)

    def _putcmd(self, line):
        if self._debugging:
            print('*cmd*', repr(line))
        line = bytes(line, self.encoding)
        self._putline(line)

    def _getline(self):
        line = self.file.readline(_MAXLINE + 1)
        if len(line) > _MAXLINE:
            raise error_proto('line too long')
        if self._debugging > 1:
            print('*get*', repr(line))
        if not line:
            raise error_proto('-ERR EOF')
        octets = len(line)
        if line[-2:] == CRLF:
            return (line[:-2], octets)
        if line[0] == CR:
            return (line[1:-1], octets)
        return (line[:-1], octets)

    def _getresp(self):
        (resp, o) = self._getline()
        if self._debugging > 1:
            print('*resp*', repr(resp))
        if not resp.startswith(b'+'):
            raise error_proto(resp)
        return resp

    def _getlongresp(self):
        resp = self._getresp()
        list = []
        octets = 0
        (line, o) = self._getline()
        while line != b'.':
            if line.startswith(b'..'):
                o = o - 1
                line = line[1:]
            octets = octets + o
            list.append(line)
            (line, o) = self._getline()
        return (resp, list, octets)

    def _shortcmd(self, line):
        self._putcmd(line)
        return self._getresp()

    def _longcmd(self, line):
        self._putcmd(line)
        return self._getlongresp()

    def getwelcome(self):
        return self.welcome

    def set_debuglevel(self, level):
        self._debugging = level

    def user(self, user):
        return self._shortcmd('USER %s' % user)

    def pass_(self, pswd):
        return self._shortcmd('PASS %s' % pswd)

    def stat(self):
        retval = self._shortcmd('STAT')
        rets = retval.split()
        if self._debugging:
            print('*stat*', repr(rets))
        numMessages = int(rets[1])
        sizeMessages = int(rets[2])
        return (numMessages, sizeMessages)

    def list(self, which=None):
        if which is not None:
            return self._shortcmd('LIST %s' % which)
        return self._longcmd('LIST')

    def retr(self, which):
        return self._longcmd('RETR %s' % which)

    def dele(self, which):
        return self._shortcmd('DELE %s' % which)

    def noop(self):
        return self._shortcmd('NOOP')

    def rset(self):
        return self._shortcmd('RSET')

    def quit(self):
        resp = self._shortcmd('QUIT')
        self.close()
        return resp

    def close(self):
        if self.file is not None:
            self.file.close()
        if self.sock is not None:
            self.sock.close()
        self.file = self.sock = None

    def rpop(self, user):
        return self._shortcmd('RPOP %s' % user)

    timestamp = re.compile(b'\\+OK.*(<[^>]+>)')

    def apop(self, user, password):
        secret = bytes(password, self.encoding)
        m = self.timestamp.match(self.welcome)
        if not m:
            raise error_proto('-ERR APOP not supported by server')
        import hashlib
        digest = m.group(1) + secret
        digest = hashlib.md5(digest).hexdigest()
        return self._shortcmd('APOP %s %s' % (user, digest))

    def top(self, which, howmuch):
        return self._longcmd('TOP %s %s' % (which, howmuch))

    def uidl(self, which=None):
        if which is not None:
            return self._shortcmd('UIDL %s' % which)
        return self._longcmd('UIDL')

try:
    import ssl
except ImportError:
    pass

class POP3_SSL(POP3):
    __qualname__ = 'POP3_SSL'

    def __init__(self, host, port=POP3_SSL_PORT, keyfile=None, certfile=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, context=None):
        if context is not None and keyfile is not None:
            raise ValueError('context and keyfile arguments are mutually exclusive')
        if context is not None and certfile is not None:
            raise ValueError('context and certfile arguments are mutually exclusive')
        self.keyfile = keyfile
        self.certfile = certfile
        self.context = context
        POP3.__init__(self, host, port, timeout)

    def _create_socket(self, timeout):
        sock = POP3._create_socket(self, timeout)
        if self.context is not None:
            sock = self.context.wrap_socket(sock)
        else:
            sock = ssl.wrap_socket(sock, self.keyfile, self.certfile)
        return sock

__all__.append('POP3_SSL')
if __name__ == '__main__':
    import sys
    a = POP3(sys.argv[1])
    print(a.getwelcome())
    a.user(sys.argv[2])
    a.pass_(sys.argv[3])
    a.list()
    (numMsgs, totalSize) = a.stat()
    for i in range(1, numMsgs + 1):
        (header, msg, octets) = a.retr(i)
        print('Message %d:' % i)
        for line in msg:
            print('   ' + line)
        print('-----------------------')
    a.quit()
