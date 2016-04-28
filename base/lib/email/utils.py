__all__ = ['collapse_rfc2231_value', 'decode_params', 'decode_rfc2231', 'encode_rfc2231', 'formataddr', 'formatdate', 'format_datetime', 'getaddresses', 'make_msgid', 'mktime_tz', 'parseaddr', 'parsedate', 'parsedate_tz', 'parsedate_to_datetime', 'unquote']
import os
import re
import time
import base64
import random
import socket
import datetime
import urllib.parse
import warnings
from io import StringIO
from email._parseaddr import quote
from email._parseaddr import AddressList as _AddressList
from email._parseaddr import mktime_tz
from email._parseaddr import parsedate, parsedate_tz, _parsedate_tz
from quopri import decodestring as _qdecode
from email.encoders import _bencode, _qencode
from email.charset import Charset
COMMASPACE = ', '
EMPTYSTRING = ''
UEMPTYSTRING = ''
CRLF = '\r\n'
TICK = "'"
specialsre = re.compile('[][\\\\()<>@,:;".]')
escapesre = re.compile('[\\\\"]')
_has_surrogates = re.compile('([^\ud800-\udbff]|\\A)[\udc00-\udfff]([^\udc00-\udfff]|\\Z)').search

def _sanitize(string):
    original_bytes = string.encode('ascii', 'surrogateescape')
    return original_bytes.decode('ascii', 'replace')

def formataddr(pair, charset='utf-8'):
    (name, address) = pair
    address.encode('ascii')
    if name:
        try:
            name.encode('ascii')
        except UnicodeEncodeError:
            if isinstance(charset, str):
                charset = Charset(charset)
            encoded_name = charset.header_encode(name)
            return '%s <%s>' % (encoded_name, address)
        quotes = ''
        if specialsre.search(name):
            quotes = '"'
        name = escapesre.sub('\\\\\\g<0>', name)
        return '%s%s%s <%s>' % (quotes, name, quotes, address)
    return address

def getaddresses(fieldvalues):
    all = COMMASPACE.join(fieldvalues)
    a = _AddressList(all)
    return a.addresslist

ecre = re.compile('\n  =\\?                   # literal =?\n  (?P<charset>[^?]*?)   # non-greedy up to the next ? is the charset\n  \\?                    # literal ?\n  (?P<encoding>[qb])    # either a "q" or a "b", case insensitive\n  \\?                    # literal ?\n  (?P<atom>.*?)         # non-greedy up to the next ?= is the atom\n  \\?=                   # literal ?=\n  ', re.VERBOSE | re.IGNORECASE)

def _format_timetuple_and_zone(timetuple, zone):
    return '%s, %02d %s %04d %02d:%02d:%02d %s' % (['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][timetuple[6]], timetuple[2], ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][timetuple[1] - 1], timetuple[0], timetuple[3], timetuple[4], timetuple[5], zone)

def formatdate(timeval=None, localtime=False, usegmt=False):
    if timeval is None:
        timeval = time.time()
    if localtime:
        now = time.localtime(timeval)
        if time.daylight and now[-1]:
            offset = time.altzone
        else:
            offset = time.timezone
        (hours, minutes) = divmod(abs(offset), 3600)
        if offset > 0:
            sign = '-'
        else:
            sign = '+'
        zone = '%s%02d%02d' % (sign, hours, minutes//60)
    else:
        now = time.gmtime(timeval)
        if usegmt:
            zone = 'GMT'
        else:
            zone = '-0000'
    return _format_timetuple_and_zone(now, zone)

def format_datetime(dt, usegmt=False):
    now = dt.timetuple()
    if usegmt:
        if dt.tzinfo is None or dt.tzinfo != datetime.timezone.utc:
            raise ValueError('usegmt option requires a UTC datetime')
        zone = 'GMT'
    elif dt.tzinfo is None:
        zone = '-0000'
    else:
        zone = dt.strftime('%z')
    return _format_timetuple_and_zone(now, zone)

def make_msgid(idstring=None, domain=None):
    timeval = time.time()
    utcdate = time.strftime('%Y%m%d%H%M%S', time.gmtime(timeval))
    pid = os.getpid()
    randint = random.randrange(100000)
    if idstring is None:
        idstring = ''
    else:
        idstring = '.' + idstring
    if domain is None:
        domain = socket.getfqdn()
    msgid = '<%s.%s.%s%s@%s>' % (utcdate, pid, randint, idstring, domain)
    return msgid

def parsedate_to_datetime(data):
    (*dtuple, tz) = _parsedate_tz(data)
    if tz is None:
        return datetime.datetime(*dtuple[:6])
    return datetime.datetime(tzinfo=datetime.timezone(datetime.timedelta(seconds=tz)), *dtuple[:6])

def parseaddr(addr):
    addrs = _AddressList(addr).addresslist
    if not addrs:
        return ('', '')
    return addrs[0]

def unquote(str):
    if str.startswith('"') and str.endswith('"'):
        return str[1:-1].replace('\\\\', '\\').replace('\\"', '"')
    if len(str) > 1 and str.startswith('<') and str.endswith('>'):
        return str[1:-1]
    return str

def decode_rfc2231(s):
    parts = s.split(TICK, 2)
    if len(parts) <= 2:
        return (None, None, s)
    return parts

def encode_rfc2231(s, charset=None, language=None):
    s = urllib.parse.quote(s, safe='', encoding=charset or 'ascii')
    if charset is None and language is None:
        return s
    if language is None:
        language = ''
    return "%s'%s'%s" % (charset, language, s)

rfc2231_continuation = re.compile('^(?P<name>\\w+)\\*((?P<num>[0-9]+)\\*?)?$', re.ASCII)

def decode_params(params):
    params = params[:]
    new_params = []
    rfc2231_params = {}
    (name, value) = params.pop(0)
    new_params.append((name, value))
    while params:
        (name, value) = params.pop(0)
        if name.endswith('*'):
            encoded = True
        else:
            encoded = False
        value = unquote(value)
        mo = rfc2231_continuation.match(name)
        if mo:
            (name, num) = mo.group('name', 'num')
            if num is not None:
                num = int(num)
            rfc2231_params.setdefault(name, []).append((num, value, encoded))
        else:
            new_params.append((name, '"%s"' % quote(value)))
    if rfc2231_params:
        for (name, continuations) in rfc2231_params.items():
            value = []
            extended = False
            continuations.sort()
            for (num, s, encoded) in continuations:
                if encoded:
                    s = urllib.parse.unquote(s, encoding='latin-1')
                    extended = True
                value.append(s)
            value = quote(EMPTYSTRING.join(value))
            if extended:
                (charset, language, value) = decode_rfc2231(value)
                new_params.append((name, (charset, language, '"%s"' % value)))
            else:
                new_params.append((name, '"%s"' % value))
    return new_params

def collapse_rfc2231_value(value, errors='replace', fallback_charset='us-ascii'):
    if not isinstance(value, tuple) or len(value) != 3:
        return unquote(value)
    (charset, language, text) = value
    if charset is None:
        charset = fallback_charset
    rawbytes = bytes(text, 'raw-unicode-escape')
    try:
        return str(rawbytes, charset, errors)
    except LookupError:
        return unquote(text)

def localtime(dt=None, isdst=-1):
    if dt is None:
        return datetime.datetime.now(datetime.timezone.utc).astimezone()
    if dt.tzinfo is not None:
        return dt.astimezone()
    tm = dt.timetuple()[:-1] + (isdst,)
    seconds = time.mktime(tm)
    localtm = time.localtime(seconds)
    try:
        delta = datetime.timedelta(seconds=localtm.tm_gmtoff)
        tz = datetime.timezone(delta, localtm.tm_zone)
    except AttributeError:
        delta = dt - datetime.datetime(*time.gmtime(seconds)[:6])
        dst = time.daylight and localtm.tm_isdst > 0
        gmtoff = -(time.altzone if dst else time.timezone)
        if delta == datetime.timedelta(seconds=gmtoff):
            tz = datetime.timezone(delta, time.tzname[dst])
        else:
            tz = datetime.timezone(delta)
    return dt.replace(tzinfo=tz)

