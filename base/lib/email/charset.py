__all__ = ['Charset', 'add_alias', 'add_charset', 'add_codec']
from functools import partial
import email.base64mime
import email.quoprimime
from email import errors
from email.encoders import encode_7or8bit
QP = 1
BASE64 = 2
SHORTEST = 3
RFC2047_CHROME_LEN = 7
DEFAULT_CHARSET = 'us-ascii'
UNKNOWN8BIT = 'unknown-8bit'
EMPTYSTRING = ''
CHARSETS = {'iso-8859-1': (QP, QP, None), 'iso-8859-2': (QP, QP, None), 'iso-8859-3': (QP, QP, None), 'iso-8859-4': (QP, QP, None), 'iso-8859-9': (QP, QP, None), 'iso-8859-10': (QP, QP, None), 'iso-8859-13': (QP, QP, None), 'iso-8859-14': (QP, QP, None), 'iso-8859-15': (QP, QP, None), 'iso-8859-16': (QP, QP, None), 'windows-1252': (QP, QP, None), 'viscii': (QP, QP, None), 'us-ascii': (None, None, None), 'big5': (BASE64, BASE64, None), 'gb2312': (BASE64, BASE64, None), 'euc-jp': (BASE64, None, 'iso-2022-jp'), 'shift_jis': (BASE64, None, 'iso-2022-jp'), 'iso-2022-jp': (BASE64, None, None), 'koi8-r': (BASE64, BASE64, None), 'utf-8': (SHORTEST, BASE64, 'utf-8')}
ALIASES = {'latin_1': 'iso-8859-1', 'latin-1': 'iso-8859-1', 'latin_2': 'iso-8859-2', 'latin-2': 'iso-8859-2', 'latin_3': 'iso-8859-3', 'latin-3': 'iso-8859-3', 'latin_4': 'iso-8859-4', 'latin-4': 'iso-8859-4', 'latin_5': 'iso-8859-9', 'latin-5': 'iso-8859-9', 'latin_6': 'iso-8859-10', 'latin-6': 'iso-8859-10', 'latin_7': 'iso-8859-13', 'latin-7': 'iso-8859-13', 'latin_8': 'iso-8859-14', 'latin-8': 'iso-8859-14', 'latin_9': 'iso-8859-15', 'latin-9': 'iso-8859-15', 'latin_10': 'iso-8859-16', 'latin-10': 'iso-8859-16', 'cp949': 'ks_c_5601-1987', 'euc_jp': 'euc-jp', 'euc_kr': 'euc-kr', 'ascii': 'us-ascii'}
CODEC_MAP = {'gb2312': 'eucgb2312_cn', 'big5': 'big5_tw', 'us-ascii': None}

def add_charset(charset, header_enc=None, body_enc=None, output_charset=None):
    if body_enc == SHORTEST:
        raise ValueError('SHORTEST not allowed for body_enc')
    CHARSETS[charset] = (header_enc, body_enc, output_charset)

def add_alias(alias, canonical):
    ALIASES[alias] = canonical

def add_codec(charset, codecname):
    CODEC_MAP[charset] = codecname

def _encode(string, codec):
    if codec == UNKNOWN8BIT:
        return string.encode('ascii', 'surrogateescape')
    return string.encode(codec)

class Charset:
    __qualname__ = 'Charset'

    def __init__(self, input_charset=DEFAULT_CHARSET):
        try:
            if isinstance(input_charset, str):
                input_charset.encode('ascii')
            else:
                input_charset = str(input_charset, 'ascii')
        except UnicodeError:
            raise errors.CharsetError(input_charset)
        input_charset = input_charset.lower()
        self.input_charset = ALIASES.get(input_charset, input_charset)
        (henc, benc, conv) = CHARSETS.get(self.input_charset, (SHORTEST, BASE64, None))
        if not conv:
            conv = self.input_charset
        self.header_encoding = henc
        self.body_encoding = benc
        self.output_charset = ALIASES.get(conv, conv)
        self.input_codec = CODEC_MAP.get(self.input_charset, self.input_charset)
        self.output_codec = CODEC_MAP.get(self.output_charset, self.output_charset)

    def __str__(self):
        return self.input_charset.lower()

    __repr__ = __str__

    def __eq__(self, other):
        return str(self) == str(other).lower()

    def __ne__(self, other):
        return not self.__eq__(other)

    def get_body_encoding(self):
        if self.body_encoding == QP:
            return 'quoted-printable'
        if self.body_encoding == BASE64:
            return 'base64'
        return encode_7or8bit

    def get_output_charset(self):
        return self.output_charset or self.input_charset

    def header_encode(self, string):
        codec = self.output_codec or 'us-ascii'
        header_bytes = _encode(string, codec)
        encoder_module = self._get_encoder(header_bytes)
        if encoder_module is None:
            return string
        return encoder_module.header_encode(header_bytes, codec)

    def header_encode_lines(self, string, maxlengths):
        codec = self.output_codec or 'us-ascii'
        header_bytes = _encode(string, codec)
        encoder_module = self._get_encoder(header_bytes)
        encoder = partial(encoder_module.header_encode, charset=codec)
        charset = self.get_output_charset()
        extra = len(charset) + RFC2047_CHROME_LEN
        lines = []
        current_line = []
        maxlen = next(maxlengths) - extra
        for character in string:
            current_line.append(character)
            this_line = EMPTYSTRING.join(current_line)
            length = encoder_module.header_length(_encode(this_line, charset))
            while length > maxlen:
                current_line.pop()
                if not lines and not current_line:
                    lines.append(None)
                else:
                    separator = ' ' if lines else ''
                    joined_line = EMPTYSTRING.join(current_line)
                    header_bytes = _encode(joined_line, codec)
                    lines.append(encoder(header_bytes))
                current_line = [character]
                maxlen = next(maxlengths) - extra
        joined_line = EMPTYSTRING.join(current_line)
        header_bytes = _encode(joined_line, codec)
        lines.append(encoder(header_bytes))
        return lines

    def _get_encoder(self, header_bytes):
        if self.header_encoding == BASE64:
            return email.base64mime
        if self.header_encoding == QP:
            return email.quoprimime
        if self.header_encoding == SHORTEST:
            len64 = email.base64mime.header_length(header_bytes)
            lenqp = email.quoprimime.header_length(header_bytes)
            if len64 < lenqp:
                return email.base64mime
            return email.quoprimime
        else:
            return

    def body_encode(self, string):
        if not string:
            return string
        if self.body_encoding is BASE64:
            if isinstance(string, str):
                string = string.encode(self.output_charset)
            return email.base64mime.body_encode(string)
        if self.body_encoding is QP:
            if isinstance(string, str):
                string = string.encode(self.output_charset)
            string = string.decode('latin1')
            return email.quoprimime.body_encode(string)
        if isinstance(string, str):
            string = string.encode(self.output_charset).decode('ascii')
        return string

