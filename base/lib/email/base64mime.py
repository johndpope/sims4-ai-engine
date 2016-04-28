__all__ = ['body_decode', 'body_encode', 'decode', 'decodestring', 'header_encode', 'header_length']
from base64 import b64encode
from binascii import b2a_base64, a2b_base64
CRLF = '\r\n'
NL = '\n'
EMPTYSTRING = ''
MISC_LEN = 7

def header_length(bytearray):
    (groups_of_3, leftover) = divmod(len(bytearray), 3)
    n = groups_of_3*4
    if leftover:
        n += 4
    return n

def header_encode(header_bytes, charset='iso-8859-1'):
    if not header_bytes:
        return ''
    if isinstance(header_bytes, str):
        header_bytes = header_bytes.encode(charset)
    encoded = b64encode(header_bytes).decode('ascii')
    return '=?%s?b?%s?=' % (charset, encoded)

def body_encode(s, maxlinelen=76, eol=NL):
    if not s:
        return s
    encvec = []
    max_unencoded = maxlinelen*3//4
    for i in range(0, len(s), max_unencoded):
        enc = b2a_base64(s[i:i + max_unencoded]).decode('ascii')
        if enc.endswith(NL) and eol != NL:
            enc = enc[:-1] + eol
        encvec.append(enc)
    return EMPTYSTRING.join(encvec)

def decode(string):
    if not string:
        return bytes()
    if isinstance(string, str):
        return a2b_base64(string.encode('raw-unicode-escape'))
    return a2b_base64(string)

body_decode = decode
decodestring = decode
