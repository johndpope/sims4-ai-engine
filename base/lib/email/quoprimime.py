__all__ = ['body_decode', 'body_encode', 'body_length', 'decode', 'decodestring', 'header_decode', 'header_encode', 'header_length', 'quote', 'unquote']
import re
import io
from string import ascii_letters, digits, hexdigits
CRLF = '\r\n'
NL = '\n'
EMPTYSTRING = ''
_QUOPRI_MAP = ['=%02X' % c for c in range(256)]
_QUOPRI_HEADER_MAP = _QUOPRI_MAP[:]
_QUOPRI_BODY_MAP = _QUOPRI_MAP[:]
for c in b'-!*+/' + ascii_letters.encode('ascii') + digits.encode('ascii'):
    _QUOPRI_HEADER_MAP[c] = chr(c)
_QUOPRI_HEADER_MAP[ord(' ')] = '_'
for c in b' !"#$%&\'()*+,-./0123456789:;<>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~\t':
    _QUOPRI_BODY_MAP[c] = chr(c)

def header_check(octet):
    return chr(octet) != _QUOPRI_HEADER_MAP[octet]

def body_check(octet):
    return chr(octet) != _QUOPRI_BODY_MAP[octet]

def header_length(bytearray):
    return sum(len(_QUOPRI_HEADER_MAP[octet]) for octet in bytearray)

def body_length(bytearray):
    return sum(len(_QUOPRI_BODY_MAP[octet]) for octet in bytearray)

def _max_append(L, s, maxlen, extra=''):
    if not isinstance(s, str):
        s = chr(s)
    if not L:
        L.append(s.lstrip())
    elif len(L[-1]) + len(s) <= maxlen:
        L[-1] += extra + s
    else:
        L.append(s.lstrip())

def unquote(s):
    return chr(int(s[1:3], 16))

def quote(c):
    return _QUOPRI_MAP[ord(c)]

def header_encode(header_bytes, charset='iso-8859-1'):
    if not header_bytes:
        return ''
    encoded = header_bytes.decode('latin1').translate(_QUOPRI_HEADER_MAP)
    return '=?%s?q?%s?=' % (charset, encoded)

_QUOPRI_BODY_ENCODE_MAP = _QUOPRI_BODY_MAP[:]
for c in b'\r\n':
    _QUOPRI_BODY_ENCODE_MAP[c] = chr(c)

def body_encode(body, maxlinelen=76, eol=NL):
    if maxlinelen < 4:
        raise ValueError('maxlinelen must be at least 4')
    if not body:
        return body
    body = body.translate(_QUOPRI_BODY_ENCODE_MAP)
    soft_break = '=' + eol
    maxlinelen1 = maxlinelen - 1
    encoded_body = []
    append = encoded_body.append
    for line in body.splitlines():
        start = 0
        laststart = len(line) - 1 - maxlinelen
        while start <= laststart:
            stop = start + maxlinelen1
            if line[stop - 2] == '=':
                append(line[start:stop - 1])
                start = stop - 2
            elif line[stop - 1] == '=':
                append(line[start:stop])
                start = stop - 1
            else:
                append(line[start:stop] + '=')
                start = stop
        if line and line[-1] in ' \t':
            room = start - laststart
            if room >= 3:
                q = quote(line[-1])
            elif room == 2:
                q = line[-1] + soft_break
            else:
                q = soft_break + quote(line[-1])
            append(line[start:-1] + q)
        else:
            append(line[start:])
    if body[-1] in CRLF:
        append('')
    return eol.join(encoded_body)

def decode(encoded, eol=NL):
    if not encoded:
        return encoded
    decoded = ''
    for line in encoded.splitlines():
        line = line.rstrip()
        if not line:
            decoded += eol
        i = 0
        n = len(line)
        while i < n:
            c = line[i]
            if c != '=':
                decoded += c
                i += 1
            elif i + 1 == n:
                i += 1
                continue
            elif i + 2 < n and line[i + 1] in hexdigits and line[i + 2] in hexdigits:
                decoded += unquote(line[i:i + 3])
                i += 3
            else:
                decoded += c
                i += 1
            while i == n:
                decoded += eol
                continue
    if encoded[-1] not in '\r\n' and decoded.endswith(eol):
        decoded = decoded[:-1]
    return decoded

body_decode = decode
decodestring = decode

def _unquote_match(match):
    s = match.group(0)
    return unquote(s)

def header_decode(s):
    s = s.replace('_', ' ')
    return re.sub('=[a-fA-F0-9]{2}', _unquote_match, s, flags=re.ASCII)

