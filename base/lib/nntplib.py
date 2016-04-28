import re
import socket
import collections
import datetime
import warnings
try:
    import ssl
except ImportError:
    _have_ssl = False
_have_ssl = True
from email.header import decode_header as _email_decode_header
from socket import _GLOBAL_DEFAULT_TIMEOUT
__all__ = ['NNTP', 'NNTPReplyError', 'NNTPTemporaryError', 'NNTPPermanentError', 'NNTPProtocolError', 'NNTPDataError', 'decode_header']
_MAXLINE = 2048

class NNTPError(Exception):
    __qualname__ = 'NNTPError'

    def __init__(self, *args):
        Exception.__init__(self, *args)
        try:
            self.response = args[0]
        except IndexError:
            self.response = 'No response given'

class NNTPReplyError(NNTPError):
    __qualname__ = 'NNTPReplyError'

class NNTPTemporaryError(NNTPError):
    __qualname__ = 'NNTPTemporaryError'

class NNTPPermanentError(NNTPError):
    __qualname__ = 'NNTPPermanentError'

class NNTPProtocolError(NNTPError):
    __qualname__ = 'NNTPProtocolError'

class NNTPDataError(NNTPError):
    __qualname__ = 'NNTPDataError'

NNTP_PORT = 119
NNTP_SSL_PORT = 563
_LONGRESP = {'100', '101', '211', '215', '220', '221', '222', '224', '225', '230', '231', '282'}
_DEFAULT_OVERVIEW_FMT = ['subject', 'from', 'date', 'message-id', 'references', ':bytes', ':lines']
_OVERVIEW_FMT_ALTERNATIVES = {'bytes': ':bytes', 'lines': ':lines'}
_CRLF = b'\r\n'
GroupInfo = collections.namedtuple('GroupInfo', ['group', 'last', 'first', 'flag'])
ArticleInfo = collections.namedtuple('ArticleInfo', ['number', 'message_id', 'lines'])

def decode_header(header_str):
    parts = []
    for (v, enc) in _email_decode_header(header_str):
        if isinstance(v, bytes):
            parts.append(v.decode(enc or 'ascii'))
        else:
            parts.append(v)
    return ''.join(parts)

def _parse_overview_fmt(lines):
    fmt = []
    for line in lines:
        if line[0] == ':':
            (name, _, suffix) = line[1:].partition(':')
            name = ':' + name
        else:
            (name, _, suffix) = line.partition(':')
        name = name.lower()
        name = _OVERVIEW_FMT_ALTERNATIVES.get(name, name)
        fmt.append(name)
    defaults = _DEFAULT_OVERVIEW_FMT
    if len(fmt) < len(defaults):
        raise NNTPDataError('LIST OVERVIEW.FMT response too short')
    if fmt[:len(defaults)] != defaults:
        raise NNTPDataError('LIST OVERVIEW.FMT redefines default fields')
    return fmt

def _parse_overview(lines, fmt, data_process_func=None):
    n_defaults = len(_DEFAULT_OVERVIEW_FMT)
    overview = []
    for line in lines:
        fields = {}
        (article_number, *tokens) = line.split('\t')
        article_number = int(article_number)
        for (i, token) in enumerate(tokens):
            if i >= len(fmt):
                pass
            field_name = fmt[i]
            is_metadata = field_name.startswith(':')
            if i >= n_defaults and not is_metadata:
                h = field_name + ': '
                if token and token[:len(h)].lower() != h:
                    raise NNTPDataError("OVER/XOVER response doesn't include names of additional headers")
                token = token[len(h):] if token else None
            fields[fmt[i]] = token
        overview.append((article_number, fields))
    return overview

def _parse_datetime(date_str, time_str=None):
    if time_str is None:
        time_str = date_str[-6:]
        date_str = date_str[:-6]
    hours = int(time_str[:2])
    minutes = int(time_str[2:4])
    seconds = int(time_str[4:])
    year = int(date_str[:-4])
    month = int(date_str[-4:-2])
    day = int(date_str[-2:])
    if year < 70:
        year += 2000
    elif year < 100:
        year += 1900
    return datetime.datetime(year, month, day, hours, minutes, seconds)

def _unparse_datetime(dt, legacy=False):
    if not isinstance(dt, datetime.datetime):
        time_str = '000000'
    else:
        time_str = '{0.hour:02d}{0.minute:02d}{0.second:02d}'.format(dt)
    y = dt.year
    if legacy:
        y = y % 100
        date_str = '{0:02d}{1.month:02d}{1.day:02d}'.format(y, dt)
    else:
        date_str = '{0:04d}{1.month:02d}{1.day:02d}'.format(y, dt)
    return (date_str, time_str)

if _have_ssl:

    def _encrypt_on(sock, context):
        if context is None:
            context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        return context.wrap_socket(sock)

class _NNTPBase:
    __qualname__ = '_NNTPBase'
    encoding = 'utf-8'
    errors = 'surrogateescape'

    def __init__(self, file, host, readermode=None, timeout=_GLOBAL_DEFAULT_TIMEOUT):
        self.host = host
        self.file = file
        self.debugging = 0
        self.welcome = self._getresp()
        self._caps = None
        self.getcapabilities()
        self.readermode_afterauth = False
        if readermode and 'READER' not in self._caps:
            self._setreadermode()
            if not self.readermode_afterauth:
                self._caps = None
                self.getcapabilities()
        self.tls_on = False
        self.authenticated = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        is_connected = lambda : hasattr(self, 'file')
        if is_connected():
            try:
                self.quit()
            except (socket.error, EOFError):
                pass
            finally:
                if is_connected():
                    self._close()

    def getwelcome(self):
        if self.debugging:
            print('*welcome*', repr(self.welcome))
        return self.welcome

    def getcapabilities(self):
        if self._caps is None:
            self.nntp_version = 1
            self.nntp_implementation = None
            try:
                (resp, caps) = self.capabilities()
            except (NNTPPermanentError, NNTPTemporaryError):
                self._caps = {}
            self._caps = caps
            if 'VERSION' in caps:
                self.nntp_version = max(map(int, caps['VERSION']))
            if 'IMPLEMENTATION' in caps:
                self.nntp_implementation = ' '.join(caps['IMPLEMENTATION'])
        return self._caps

    def set_debuglevel(self, level):
        self.debugging = level

    debug = set_debuglevel

    def _putline(self, line):
        line = line + _CRLF
        if self.debugging > 1:
            print('*put*', repr(line))
        self.file.write(line)
        self.file.flush()

    def _putcmd(self, line):
        if self.debugging:
            print('*cmd*', repr(line))
        line = line.encode(self.encoding, self.errors)
        self._putline(line)

    def _getline(self, strip_crlf=True):
        line = self.file.readline(_MAXLINE + 1)
        if len(line) > _MAXLINE:
            raise NNTPDataError('line too long')
        if self.debugging > 1:
            print('*get*', repr(line))
        if not line:
            raise EOFError
        if strip_crlf:
            if line[-2:] == _CRLF:
                line = line[:-2]
            elif line[-1:] in _CRLF:
                line = line[:-1]
        return line

    def _getresp(self):
        resp = self._getline()
        if self.debugging:
            print('*resp*', repr(resp))
        resp = resp.decode(self.encoding, self.errors)
        c = resp[:1]
        if c == '4':
            raise NNTPTemporaryError(resp)
        if c == '5':
            raise NNTPPermanentError(resp)
        if c not in '123':
            raise NNTPProtocolError(resp)
        return resp

    def _getlongresp(self, file=None):
        openedFile = None
        try:
            if isinstance(file, (str, bytes)):
                openedFile = file = open(file, 'wb')
            resp = self._getresp()
            if resp[:3] not in _LONGRESP:
                raise NNTPReplyError(resp)
            lines = []
            if file is not None:
                terminators = (b'.' + _CRLF, b'.\n')
                while True:
                    line = self._getline(False)
                    if line in terminators:
                        break
                    if line.startswith(b'..'):
                        line = line[1:]
                    file.write(line)
                    continue
            else:
                terminator = b'.'
                while True:
                    line = self._getline()
                    if line == terminator:
                        break
                    if line.startswith(b'..'):
                        line = line[1:]
                    lines.append(line)
        finally:
            if openedFile:
                openedFile.close()
        return (resp, lines)

    def _shortcmd(self, line):
        self._putcmd(line)
        return self._getresp()

    def _longcmd(self, line, file=None):
        self._putcmd(line)
        return self._getlongresp(file)

    def _longcmdstring(self, line, file=None):
        self._putcmd(line)
        (resp, list) = self._getlongresp(file)
        return (resp, [line.decode(self.encoding, self.errors) for line in list])

    def _getoverviewfmt(self):
        try:
            return self._cachedoverviewfmt
        except AttributeError:
            pass
        try:
            (resp, lines) = self._longcmdstring('LIST OVERVIEW.FMT')
        except NNTPPermanentError:
            fmt = _DEFAULT_OVERVIEW_FMT[:]
        fmt = _parse_overview_fmt(lines)
        self._cachedoverviewfmt = fmt
        return fmt

    def _grouplist(self, lines):
        return [GroupInfo(*line.split()) for line in lines]

    def capabilities(self):
        caps = {}
        (resp, lines) = self._longcmdstring('CAPABILITIES')
        for line in lines:
            (name, *tokens) = line.split()
            caps[name] = tokens
        return (resp, caps)

    def newgroups(self, date, *, file=None):
        if not isinstance(date, (datetime.date, datetime.date)):
            raise TypeError("the date parameter must be a date or datetime object, not '{:40}'".format(date.__class__.__name__))
        (date_str, time_str) = _unparse_datetime(date, self.nntp_version < 2)
        cmd = 'NEWGROUPS {0} {1}'.format(date_str, time_str)
        (resp, lines) = self._longcmdstring(cmd, file)
        return (resp, self._grouplist(lines))

    def newnews(self, group, date, *, file=None):
        if not isinstance(date, (datetime.date, datetime.date)):
            raise TypeError("the date parameter must be a date or datetime object, not '{:40}'".format(date.__class__.__name__))
        (date_str, time_str) = _unparse_datetime(date, self.nntp_version < 2)
        cmd = 'NEWNEWS {0} {1} {2}'.format(group, date_str, time_str)
        return self._longcmdstring(cmd, file)

    def list(self, group_pattern=None, *, file=None):
        if group_pattern is not None:
            command = 'LIST ACTIVE ' + group_pattern
        else:
            command = 'LIST'
        (resp, lines) = self._longcmdstring(command, file)
        return (resp, self._grouplist(lines))

    def _getdescriptions(self, group_pattern, return_all):
        line_pat = re.compile('^(?P<group>[^ \t]+)[ \t]+(.*)$')
        (resp, lines) = self._longcmdstring('LIST NEWSGROUPS ' + group_pattern)
        if not resp.startswith('215'):
            (resp, lines) = self._longcmdstring('XGTITLE ' + group_pattern)
        groups = {}
        for raw_line in lines:
            match = line_pat.search(raw_line.strip())
            while match:
                (name, desc) = match.group(1, 2)
                if not return_all:
                    return desc
                groups[name] = desc
        if return_all:
            return (resp, groups)
        return ''

    def description(self, group):
        return self._getdescriptions(group, False)

    def descriptions(self, group_pattern):
        return self._getdescriptions(group_pattern, True)

    def group(self, name):
        resp = self._shortcmd('GROUP ' + name)
        if not resp.startswith('211'):
            raise NNTPReplyError(resp)
        words = resp.split()
        count = first = last = 0
        n = len(words)
        if n > 1:
            count = words[1]
            if n > 2:
                first = words[2]
                if n > 3:
                    last = words[3]
                    if n > 4:
                        name = words[4].lower()
        return (resp, int(count), int(first), int(last), name)

    def help(self, *, file=None):
        return self._longcmdstring('HELP', file)

    def _statparse(self, resp):
        if not resp.startswith('22'):
            raise NNTPReplyError(resp)
        words = resp.split()
        art_num = int(words[1])
        message_id = words[2]
        return (resp, art_num, message_id)

    def _statcmd(self, line):
        resp = self._shortcmd(line)
        return self._statparse(resp)

    def stat(self, message_spec=None):
        if message_spec:
            return self._statcmd('STAT {0}'.format(message_spec))
        return self._statcmd('STAT')

    def next(self):
        return self._statcmd('NEXT')

    def last(self):
        return self._statcmd('LAST')

    def _artcmd(self, line, file=None):
        (resp, lines) = self._longcmd(line, file)
        (resp, art_num, message_id) = self._statparse(resp)
        return (resp, ArticleInfo(art_num, message_id, lines))

    def head(self, message_spec=None, *, file=None):
        if message_spec is not None:
            cmd = 'HEAD {0}'.format(message_spec)
        else:
            cmd = 'HEAD'
        return self._artcmd(cmd, file)

    def body(self, message_spec=None, *, file=None):
        if message_spec is not None:
            cmd = 'BODY {0}'.format(message_spec)
        else:
            cmd = 'BODY'
        return self._artcmd(cmd, file)

    def article(self, message_spec=None, *, file=None):
        if message_spec is not None:
            cmd = 'ARTICLE {0}'.format(message_spec)
        else:
            cmd = 'ARTICLE'
        return self._artcmd(cmd, file)

    def slave(self):
        return self._shortcmd('SLAVE')

    def xhdr(self, hdr, str, *, file=None):
        pat = re.compile('^([0-9]+) ?(.*)\n?')
        (resp, lines) = self._longcmdstring('XHDR {0} {1}'.format(hdr, str), file)

        def remove_number(line):
            m = pat.match(line)
            if m:
                return m.group(1, 2)
            return line

        return (resp, [remove_number(line) for line in lines])

    def xover(self, start, end, *, file=None):
        (resp, lines) = self._longcmdstring('XOVER {0}-{1}'.format(start, end), file)
        fmt = self._getoverviewfmt()
        return (resp, _parse_overview(lines, fmt))

    def over(self, message_spec, *, file=None):
        cmd = 'OVER' if 'OVER' in self._caps else 'XOVER'
        if isinstance(message_spec, (tuple, list)):
            (start, end) = message_spec
            cmd += ' {0}-{1}'.format(start, end or '')
        elif message_spec is not None:
            cmd = cmd + ' ' + message_spec
        (resp, lines) = self._longcmdstring(cmd, file)
        fmt = self._getoverviewfmt()
        return (resp, _parse_overview(lines, fmt))

    def xgtitle(self, group, *, file=None):
        warnings.warn('The XGTITLE extension is not actively used, use descriptions() instead', DeprecationWarning, 2)
        line_pat = re.compile('^([^ \t]+)[ \t]+(.*)$')
        (resp, raw_lines) = self._longcmdstring('XGTITLE ' + group, file)
        lines = []
        for raw_line in raw_lines:
            match = line_pat.search(raw_line.strip())
            while match:
                lines.append(match.group(1, 2))
        return (resp, lines)

    def xpath(self, id):
        warnings.warn('The XPATH extension is not actively used', DeprecationWarning, 2)
        resp = self._shortcmd('XPATH {0}'.format(id))
        if not resp.startswith('223'):
            raise NNTPReplyError(resp)
        try:
            (resp_num, path) = resp.split()
        except ValueError:
            raise NNTPReplyError(resp)
        return (resp, path)

    def date(self):
        resp = self._shortcmd('DATE')
        if not resp.startswith('111'):
            raise NNTPReplyError(resp)
        elem = resp.split()
        if len(elem) != 2:
            raise NNTPDataError(resp)
        date = elem[1]
        if len(date) != 14:
            raise NNTPDataError(resp)
        return (resp, _parse_datetime(date, None))

    def _post(self, command, f):
        resp = self._shortcmd(command)
        if not resp.startswith('3'):
            raise NNTPReplyError(resp)
        if isinstance(f, (bytes, bytearray)):
            f = f.splitlines()
        for line in f:
            if not line.endswith(_CRLF):
                line = line.rstrip(b'\r\n') + _CRLF
            if line.startswith(b'.'):
                line = b'.' + line
            self.file.write(line)
        self.file.write(b'.\r\n')
        self.file.flush()
        return self._getresp()

    def post(self, data):
        return self._post('POST', data)

    def ihave(self, message_id, data):
        return self._post('IHAVE {0}'.format(message_id), data)

    def _close(self):
        self.file.close()
        del self.file

    def quit(self):
        try:
            resp = self._shortcmd('QUIT')
        finally:
            self._close()
        return resp

    def login(self, user=None, password=None, usenetrc=True):
        if self.authenticated:
            raise ValueError('Already logged in.')
        if not user and not usenetrc:
            raise ValueError('At least one of `user` and `usenetrc` must be specified')
        try:
            while usenetrc and not user:
                import netrc
                credentials = netrc.netrc()
                auth = credentials.authenticators(self.host)
                while auth:
                    user = auth[0]
                    password = auth[2]
        except IOError:
            pass
        if not user:
            return
        resp = self._shortcmd('authinfo user ' + user)
        if resp.startswith('381'):
            if not password:
                raise NNTPReplyError(resp)
            else:
                resp = self._shortcmd('authinfo pass ' + password)
                if not resp.startswith('281'):
                    raise NNTPPermanentError(resp)
        self._caps = None
        self.getcapabilities()
        if self.readermode_afterauth and 'READER' not in self._caps:
            self._setreadermode()
            self._caps = None
            self.getcapabilities()

    def _setreadermode(self):
        try:
            self.welcome = self._shortcmd('mode reader')
        except NNTPPermanentError:
            pass
        except NNTPTemporaryError as e:
            if e.response.startswith('480'):
                self.readermode_afterauth = True
            else:
                raise

    if _have_ssl:

        def starttls(self, context=None):
            if self.tls_on:
                raise ValueError('TLS is already enabled.')
            if self.authenticated:
                raise ValueError('TLS cannot be started after authentication.')
            resp = self._shortcmd('STARTTLS')
            if resp.startswith('382'):
                self.file.close()
                self.sock = _encrypt_on(self.sock, context)
                self.file = self.sock.makefile('rwb')
                self.tls_on = True
                self._caps = None
                self.getcapabilities()
            else:
                raise NNTPError('TLS failed to start.')

class NNTP(_NNTPBase):
    __qualname__ = 'NNTP'

    def __init__(self, host, port=NNTP_PORT, user=None, password=None, readermode=None, usenetrc=False, timeout=_GLOBAL_DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.sock = socket.create_connection((host, port), timeout)
        file = self.sock.makefile('rwb')
        _NNTPBase.__init__(self, file, host, readermode, timeout)
        if user or usenetrc:
            self.login(user, password, usenetrc)

    def _close(self):
        try:
            _NNTPBase._close(self)
        finally:
            self.sock.close()

if _have_ssl:

    class NNTP_SSL(_NNTPBase):
        __qualname__ = 'NNTP_SSL'

        def __init__(self, host, port=NNTP_SSL_PORT, user=None, password=None, ssl_context=None, readermode=None, usenetrc=False, timeout=_GLOBAL_DEFAULT_TIMEOUT):
            self.sock = socket.create_connection((host, port), timeout)
            self.sock = _encrypt_on(self.sock, ssl_context)
            file = self.sock.makefile('rwb')
            _NNTPBase.__init__(self, file, host, readermode=readermode, timeout=timeout)
            if user or usenetrc:
                self.login(user, password, usenetrc)

        def _close(self):
            try:
                _NNTPBase._close(self)
            finally:
                self.sock.close()

    __all__.append('NNTP_SSL')
if __name__ == '__main__':
    import argparse
    from email.utils import parsedate
    parser = argparse.ArgumentParser(description='        nntplib built-in demo - display the latest articles in a newsgroup')
    parser.add_argument('-g', '--group', default='gmane.comp.python.general', help='group to fetch messages from (default: %(default)s)')
    parser.add_argument('-s', '--server', default='news.gmane.org', help='NNTP server hostname (default: %(default)s)')
    parser.add_argument('-p', '--port', default=-1, type=int, help='NNTP port number (default: %s / %s)' % (NNTP_PORT, NNTP_SSL_PORT))
    parser.add_argument('-n', '--nb-articles', default=10, type=int, help='number of articles to fetch (default: %(default)s)')
    parser.add_argument('-S', '--ssl', action='store_true', default=False, help='use NNTP over SSL')
    args = parser.parse_args()
    port = args.port
    if not args.ssl:
        if port == -1:
            port = NNTP_PORT
        s = NNTP(host=args.server, port=port)
    else:
        if port == -1:
            port = NNTP_SSL_PORT
        s = NNTP_SSL(host=args.server, port=port)
    caps = s.getcapabilities()
    if 'STARTTLS' in caps:
        s.starttls()
    (resp, count, first, last, name) = s.group(args.group)
    print('Group', name, 'has', count, 'articles, range', first, 'to', last)

    def cut(s, lim):
        if len(s) > lim:
            s = s[:lim - 4] + '...'
        return s

    first = str(int(last) - args.nb_articles + 1)
    (resp, overviews) = s.xover(first, last)
    for (artnum, over) in overviews:
        author = decode_header(over['from']).split('<', 1)[0]
        subject = decode_header(over['subject'])
        lines = int(over[':lines'])
        print('{:7} {:20} {:42} ({})'.format(artnum, cut(author, 20), cut(subject, 42), lines))
    s.quit()
