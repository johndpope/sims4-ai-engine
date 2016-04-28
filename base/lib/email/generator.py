__all__ = ['Generator', 'DecodedGenerator', 'BytesGenerator']
import re
import sys
import time
import random
import warnings
from copy import deepcopy
from io import StringIO, BytesIO
from email._policybase import compat32
from email.header import Header
from email.utils import _has_surrogates
import email.charset as _charset
UNDERSCORE = '_'
NL = '\n'
fcre = re.compile('^From ', re.MULTILINE)

class Generator:
    __qualname__ = 'Generator'

    def __init__(self, outfp, mangle_from_=True, maxheaderlen=None, *, policy=None):
        self._fp = outfp
        self._mangle_from_ = mangle_from_
        self.maxheaderlen = maxheaderlen
        self.policy = policy

    def write(self, s):
        self._fp.write(s)

    def flatten(self, msg, unixfrom=False, linesep=None):
        policy = msg.policy if self.policy is None else self.policy
        if linesep is not None:
            policy = policy.clone(linesep=linesep)
        if self.maxheaderlen is not None:
            policy = policy.clone(max_line_length=self.maxheaderlen)
        self._NL = policy.linesep
        self._encoded_NL = self._encode(self._NL)
        self._EMPTY = ''
        self._encoded_EMTPY = self._encode('')
        old_gen_policy = self.policy
        old_msg_policy = msg.policy
        try:
            self.policy = policy
            msg.policy = policy
            if unixfrom:
                ufrom = msg.get_unixfrom()
                if not ufrom:
                    ufrom = 'From nobody ' + time.ctime(time.time())
                self.write(ufrom + self._NL)
            self._write(msg)
        finally:
            self.policy = old_gen_policy
            msg.policy = old_msg_policy

    def clone(self, fp):
        return self.__class__(fp, self._mangle_from_, None, policy=self.policy)

    _encoded_EMPTY = ''

    def _new_buffer(self):
        return StringIO()

    def _encode(self, s):
        return s

    def _write_lines(self, lines):
        if not lines:
            return
        lines = lines.splitlines(True)
        for line in lines[:-1]:
            self.write(line.rstrip('\r\n'))
            self.write(self._NL)
        laststripped = lines[-1].rstrip('\r\n')
        self.write(laststripped)
        if len(lines[-1]) != len(laststripped):
            self.write(self._NL)

    def _write(self, msg):
        oldfp = self._fp
        try:
            self._munge_cte = None
            self._fp = sfp = self._new_buffer()
            self._dispatch(msg)
        finally:
            self._fp = oldfp
            munge_cte = self._munge_cte
            del self._munge_cte
        if munge_cte:
            msg = deepcopy(msg)
            msg.replace_header('content-transfer-encoding', munge_cte[0])
            msg.replace_header('content-type', munge_cte[1])
        meth = getattr(msg, '_write_headers', None)
        if meth is None:
            self._write_headers(msg)
        else:
            meth(self)
        self._fp.write(sfp.getvalue())

    def _dispatch(self, msg):
        main = msg.get_content_maintype()
        sub = msg.get_content_subtype()
        specific = UNDERSCORE.join((main, sub)).replace('-', '_')
        meth = getattr(self, '_handle_' + specific, None)
        if meth is None:
            generic = main.replace('-', '_')
            meth = getattr(self, '_handle_' + generic, None)
            if meth is None:
                meth = self._writeBody
        meth(msg)

    def _write_headers(self, msg):
        for (h, v) in msg.raw_items():
            self.write(self.policy.fold(h, v))
        self.write(self._NL)

    def _handle_text(self, msg):
        payload = msg.get_payload()
        if payload is None:
            return
        if not isinstance(payload, str):
            raise TypeError('string payload expected: %s' % type(payload))
        if _has_surrogates(msg._payload):
            charset = msg.get_param('charset')
            if charset is not None:
                msg = deepcopy(msg)
                del msg['content-transfer-encoding']
                msg.set_payload(payload, charset)
                payload = msg.get_payload()
                self._munge_cte = (msg['content-transfer-encoding'], msg['content-type'])
        if self._mangle_from_:
            payload = fcre.sub('>From ', payload)
        self._write_lines(payload)

    _writeBody = _handle_text

    def _handle_multipart(self, msg):
        msgtexts = []
        subparts = msg.get_payload()
        if subparts is None:
            subparts = []
        else:
            if isinstance(subparts, str):
                self.write(subparts)
                return
            if not isinstance(subparts, list):
                subparts = [subparts]
        for part in subparts:
            s = self._new_buffer()
            g = self.clone(s)
            g.flatten(part, unixfrom=False, linesep=self._NL)
            msgtexts.append(s.getvalue())
        boundary = msg.get_boundary()
        if not boundary:
            alltext = self._encoded_NL.join(msgtexts)
            boundary = self._make_boundary(alltext)
            msg.set_boundary(boundary)
        if msg.preamble is not None:
            if self._mangle_from_:
                preamble = fcre.sub('>From ', msg.preamble)
            else:
                preamble = msg.preamble
            self._write_lines(preamble)
            self.write(self._NL)
        self.write('--' + boundary + self._NL)
        if msgtexts:
            self._fp.write(msgtexts.pop(0))
        for body_part in msgtexts:
            self.write(self._NL + '--' + boundary + self._NL)
            self._fp.write(body_part)
        self.write(self._NL + '--' + boundary + '--' + self._NL)
        if msg.epilogue is not None:
            if self._mangle_from_:
                epilogue = fcre.sub('>From ', msg.epilogue)
            else:
                epilogue = msg.epilogue
            self._write_lines(epilogue)

    def _handle_multipart_signed(self, msg):
        p = self.policy
        self.policy = p.clone(max_line_length=0)
        try:
            self._handle_multipart(msg)
        finally:
            self.policy = p

    def _handle_message_delivery_status(self, msg):
        blocks = []
        for part in msg.get_payload():
            s = self._new_buffer()
            g = self.clone(s)
            g.flatten(part, unixfrom=False, linesep=self._NL)
            text = s.getvalue()
            lines = text.split(self._encoded_NL)
            if lines and lines[-1] == self._encoded_EMPTY:
                blocks.append(self._encoded_NL.join(lines[:-1]))
            else:
                blocks.append(text)
        self._fp.write(self._encoded_NL.join(blocks))

    def _handle_message(self, msg):
        s = self._new_buffer()
        g = self.clone(s)
        payload = msg._payload
        if isinstance(payload, list):
            g.flatten(msg.get_payload(0), unixfrom=False, linesep=self._NL)
            payload = s.getvalue()
        else:
            payload = self._encode(payload)
        self._fp.write(payload)

    @classmethod
    def _make_boundary(cls, text=None):
        token = random.randrange(sys.maxsize)
        boundary = '===============' + _fmt % token + '=='
        if text is None:
            return boundary
        b = boundary
        counter = 0
        while True:
            cre = cls._compile_re('^--' + re.escape(b) + '(--)?$', re.MULTILINE)
            if not cre.search(text):
                break
            b = boundary + '.' + str(counter)
            counter += 1
        return b

    @classmethod
    def _compile_re(cls, s, flags):
        return re.compile(s, flags)

class BytesGenerator(Generator):
    __qualname__ = 'BytesGenerator'
    _encoded_EMPTY = b''

    def write(self, s):
        self._fp.write(s.encode('ascii', 'surrogateescape'))

    def _new_buffer(self):
        return BytesIO()

    def _encode(self, s):
        return s.encode('ascii')

    def _write_headers(self, msg):
        for (h, v) in msg.raw_items():
            self._fp.write(self.policy.fold_binary(h, v))
        self.write(self._NL)

    def _handle_text(self, msg):
        if msg._payload is None:
            return
        if _has_surrogates(msg._payload) and not self.policy.cte_type == '7bit':
            if self._mangle_from_:
                msg._payload = fcre.sub('>From ', msg._payload)
            self._write_lines(msg._payload)
        else:
            super(BytesGenerator, self)._handle_text(msg)

    _writeBody = _handle_text

    @classmethod
    def _compile_re(cls, s, flags):
        return re.compile(s.encode('ascii'), flags)

_FMT = '[Non-text (%(type)s) part of message omitted, filename %(filename)s]'

class DecodedGenerator(Generator):
    __qualname__ = 'DecodedGenerator'

    def __init__(self, outfp, mangle_from_=True, maxheaderlen=78, fmt=None):
        Generator.__init__(self, outfp, mangle_from_, maxheaderlen)
        if fmt is None:
            self._fmt = _FMT
        else:
            self._fmt = fmt

    def _dispatch(self, msg):
        for part in msg.walk():
            maintype = part.get_content_maintype()
            if maintype == 'text':
                print(part.get_payload(decode=False), file=self)
            elif maintype == 'multipart':
                pass
            else:
                print(self._fmt % {'type': part.get_content_type(), 'maintype': part.get_content_maintype(), 'subtype': part.get_content_subtype(), 'filename': part.get_filename('[no filename]'), 'description': part.get('Content-Description', '[no description]'), 'encoding': part.get('Content-Transfer-Encoding', '[no encoding]')}, file=self)

_width = len(repr(sys.maxsize - 1))
_fmt = '%%0%dd' % _width
_make_boundary = Generator._make_boundary
