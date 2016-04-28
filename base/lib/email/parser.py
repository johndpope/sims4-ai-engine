__all__ = ['Parser', 'HeaderParser', 'BytesParser', 'BytesHeaderParser']
import warnings
from io import StringIO, TextIOWrapper
from email.feedparser import FeedParser, BytesFeedParser
from email.message import Message
from email._policybase import compat32

class Parser:
    __qualname__ = 'Parser'

    def __init__(self, _class=Message, *, policy=compat32):
        self._class = _class
        self.policy = policy

    def parse(self, fp, headersonly=False):
        feedparser = FeedParser(self._class, policy=self.policy)
        if headersonly:
            feedparser._set_headersonly()
        while True:
            data = fp.read(8192)
            if not data:
                break
            feedparser.feed(data)
        return feedparser.close()

    def parsestr(self, text, headersonly=False):
        return self.parse(StringIO(text), headersonly=headersonly)

class HeaderParser(Parser):
    __qualname__ = 'HeaderParser'

    def parse(self, fp, headersonly=True):
        return Parser.parse(self, fp, True)

    def parsestr(self, text, headersonly=True):
        return Parser.parsestr(self, text, True)

class BytesParser:
    __qualname__ = 'BytesParser'

    def __init__(self, *args, **kw):
        self.parser = Parser(*args, **kw)

    def parse(self, fp, headersonly=False):
        fp = TextIOWrapper(fp, encoding='ascii', errors='surrogateescape')
        with fp:
            return self.parser.parse(fp, headersonly)

    def parsebytes(self, text, headersonly=False):
        text = text.decode('ASCII', errors='surrogateescape')
        return self.parser.parsestr(text, headersonly)

class BytesHeaderParser(BytesParser):
    __qualname__ = 'BytesHeaderParser'

    def parse(self, fp, headersonly=True):
        return BytesParser.parse(self, fp, headersonly=True)

    def parsebytes(self, text, headersonly=True):
        return BytesParser.parsebytes(self, text, headersonly=True)

