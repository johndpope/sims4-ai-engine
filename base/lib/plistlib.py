__all__ = ['readPlist', 'writePlist', 'readPlistFromBytes', 'writePlistToBytes', 'Plist', 'Data', 'Dict']
import binascii
import datetime
from io import BytesIO
import re

def readPlist(pathOrFile):
    didOpen = False
    try:
        if isinstance(pathOrFile, str):
            pathOrFile = open(pathOrFile, 'rb')
            didOpen = True
        p = PlistParser()
        rootObject = p.parse(pathOrFile)
    finally:
        if didOpen:
            pathOrFile.close()
    return rootObject

def writePlist(rootObject, pathOrFile):
    didOpen = False
    try:
        if isinstance(pathOrFile, str):
            pathOrFile = open(pathOrFile, 'wb')
            didOpen = True
        writer = PlistWriter(pathOrFile)
        writer.writeln('<plist version="1.0">')
        writer.writeValue(rootObject)
        writer.writeln('</plist>')
    finally:
        if didOpen:
            pathOrFile.close()

def readPlistFromBytes(data):
    return readPlist(BytesIO(data))

def writePlistToBytes(rootObject):
    f = BytesIO()
    writePlist(rootObject, f)
    return f.getvalue()

class DumbXMLWriter:
    __qualname__ = 'DumbXMLWriter'

    def __init__(self, file, indentLevel=0, indent='\t'):
        self.file = file
        self.stack = []
        self.indentLevel = indentLevel
        self.indent = indent

    def beginElement(self, element):
        self.stack.append(element)
        self.writeln('<%s>' % element)

    def endElement(self, element):
        self.writeln('</%s>' % element)

    def simpleElement(self, element, value=None):
        if value is not None:
            value = _escape(value)
            self.writeln('<%s>%s</%s>' % (element, value, element))
        else:
            self.writeln('<%s/>' % element)

    def writeln(self, line):
        if line:
            if isinstance(line, str):
                line = line.encode('utf-8')
            self.file.write(self.indentLevel*self.indent)
            self.file.write(line)
        self.file.write(b'\n')

_dateParser = re.compile('(?P<year>\\d\\d\\d\\d)(?:-(?P<month>\\d\\d)(?:-(?P<day>\\d\\d)(?:T(?P<hour>\\d\\d)(?::(?P<minute>\\d\\d)(?::(?P<second>\\d\\d))?)?)?)?)?Z', re.ASCII)

def _dateFromString(s):
    order = ('year', 'month', 'day', 'hour', 'minute', 'second')
    gd = _dateParser.match(s).groupdict()
    lst = []
    for key in order:
        val = gd[key]
        if val is None:
            break
        lst.append(int(val))
    return datetime.datetime(*lst)

def _dateToString(d):
    return '%04d-%02d-%02dT%02d:%02d:%02dZ' % (d.year, d.month, d.day, d.hour, d.minute, d.second)

_controlCharPat = re.compile('[\\x00\\x01\\x02\\x03\\x04\\x05\\x06\\x07\\x08\\x0b\\x0c\\x0e\\x0f\\x10\\x11\\x12\\x13\\x14\\x15\\x16\\x17\\x18\\x19\\x1a\\x1b\\x1c\\x1d\\x1e\\x1f]')

def _escape(text):
    m = _controlCharPat.search(text)
    if m is not None:
        raise ValueError("strings can't contains control characters; use plistlib.Data instead")
    text = text.replace('\r\n', '\n')
    text = text.replace('\r', '\n')
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text

PLISTHEADER = b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'

class PlistWriter(DumbXMLWriter):
    __qualname__ = 'PlistWriter'

    def __init__(self, file, indentLevel=0, indent=b'\t', writeHeader=1):
        if writeHeader:
            file.write(PLISTHEADER)
        DumbXMLWriter.__init__(self, file, indentLevel, indent)

    def writeValue(self, value):
        if isinstance(value, str):
            self.simpleElement('string', value)
        elif isinstance(value, bool):
            if value:
                self.simpleElement('true')
            else:
                self.simpleElement('false')
        elif isinstance(value, int):
            self.simpleElement('integer', '%d' % value)
        elif isinstance(value, float):
            self.simpleElement('real', repr(value))
        elif isinstance(value, dict):
            self.writeDict(value)
        elif isinstance(value, Data):
            self.writeData(value)
        elif isinstance(value, datetime.datetime):
            self.simpleElement('date', _dateToString(value))
        elif isinstance(value, (tuple, list)):
            self.writeArray(value)
        else:
            raise TypeError('unsupported type: %s' % type(value))

    def writeData(self, data):
        self.beginElement('data')
        maxlinelength = max(16, 76 - len(self.indent.replace(b'\t', b'        ')*self.indentLevel))
        for line in data.asBase64(maxlinelength).split(b'\n'):
            while line:
                self.writeln(line)
        self.endElement('data')

    def writeDict(self, d):
        if d:
            self.beginElement('dict')
            items = sorted(d.items())
            for (key, value) in items:
                if not isinstance(key, str):
                    raise TypeError('keys must be strings')
                self.simpleElement('key', key)
                self.writeValue(value)
            self.endElement('dict')
        else:
            self.simpleElement('dict')

    def writeArray(self, array):
        if array:
            self.beginElement('array')
            for value in array:
                self.writeValue(value)
            self.endElement('array')
        else:
            self.simpleElement('array')

class _InternalDict(dict):
    __qualname__ = '_InternalDict'

    def __getattr__(self, attr):
        try:
            value = self[attr]
        except KeyError:
            raise AttributeError(attr)
        from warnings import warn
        warn('Attribute access from plist dicts is deprecated, use d[key] notation instead', DeprecationWarning, 2)
        return value

    def __setattr__(self, attr, value):
        from warnings import warn
        warn('Attribute access from plist dicts is deprecated, use d[key] notation instead', DeprecationWarning, 2)
        self[attr] = value

    def __delattr__(self, attr):
        try:
            del self[attr]
        except KeyError:
            raise AttributeError(attr)
        from warnings import warn
        warn('Attribute access from plist dicts is deprecated, use d[key] notation instead', DeprecationWarning, 2)

class Dict(_InternalDict):
    __qualname__ = 'Dict'

    def __init__(self, **kwargs):
        from warnings import warn
        warn('The plistlib.Dict class is deprecated, use builtin dict instead', DeprecationWarning, 2)
        super().__init__(**kwargs)

class Plist(_InternalDict):
    __qualname__ = 'Plist'

    def __init__(self, **kwargs):
        from warnings import warn
        warn('The Plist class is deprecated, use the readPlist() and writePlist() functions instead', DeprecationWarning, 2)
        super().__init__(**kwargs)

    def fromFile(cls, pathOrFile):
        rootObject = readPlist(pathOrFile)
        plist = cls()
        plist.update(rootObject)
        return plist

    fromFile = classmethod(fromFile)

    def write(self, pathOrFile):
        writePlist(self, pathOrFile)

def _encodeBase64(s, maxlinelength=76):
    maxbinsize = maxlinelength//4*3
    pieces = []
    for i in range(0, len(s), maxbinsize):
        chunk = s[i:i + maxbinsize]
        pieces.append(binascii.b2a_base64(chunk))
    return b''.join(pieces)

class Data:
    __qualname__ = 'Data'

    def __init__(self, data):
        if not isinstance(data, bytes):
            raise TypeError('data must be as bytes')
        self.data = data

    @classmethod
    def fromBase64(cls, data):
        return cls(binascii.a2b_base64(data))

    def asBase64(self, maxlinelength=76):
        return _encodeBase64(self.data, maxlinelength)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.data == other.data
        if isinstance(other, str):
            return self.data == other
        return id(self) == id(other)

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, repr(self.data))

class PlistParser:
    __qualname__ = 'PlistParser'

    def __init__(self):
        self.stack = []
        self.currentKey = None
        self.root = None

    def parse(self, fileobj):
        from xml.parsers.expat import ParserCreate
        self.parser = ParserCreate()
        self.parser.StartElementHandler = self.handleBeginElement
        self.parser.EndElementHandler = self.handleEndElement
        self.parser.CharacterDataHandler = self.handleData
        self.parser.ParseFile(fileobj)
        return self.root

    def handleBeginElement(self, element, attrs):
        self.data = []
        handler = getattr(self, 'begin_' + element, None)
        if handler is not None:
            handler(attrs)

    def handleEndElement(self, element):
        handler = getattr(self, 'end_' + element, None)
        if handler is not None:
            handler()

    def handleData(self, data):
        self.data.append(data)

    def addObject(self, value):
        if self.currentKey is not None:
            if not isinstance(self.stack[-1], type({})):
                raise ValueError('unexpected element at line %d' % self.parser.CurrentLineNumber)
            self.stack[-1][self.currentKey] = value
            self.currentKey = None
        elif not self.stack:
            self.root = value
        else:
            if not isinstance(self.stack[-1], type([])):
                raise ValueError('unexpected element at line %d' % self.parser.CurrentLineNumber)
            self.stack[-1].append(value)

    def getData(self):
        data = ''.join(self.data)
        self.data = []
        return data

    def begin_dict(self, attrs):
        d = _InternalDict()
        self.addObject(d)
        self.stack.append(d)

    def end_dict(self):
        if self.currentKey:
            raise ValueError("missing value for key '%s' at line %d" % (self.currentKey, self.parser.CurrentLineNumber))
        self.stack.pop()

    def end_key(self):
        if self.currentKey or not isinstance(self.stack[-1], type({})):
            raise ValueError('unexpected key at line %d' % self.parser.CurrentLineNumber)
        self.currentKey = self.getData()

    def begin_array(self, attrs):
        a = []
        self.addObject(a)
        self.stack.append(a)

    def end_array(self):
        self.stack.pop()

    def end_true(self):
        self.addObject(True)

    def end_false(self):
        self.addObject(False)

    def end_integer(self):
        self.addObject(int(self.getData()))

    def end_real(self):
        self.addObject(float(self.getData()))

    def end_string(self):
        self.addObject(self.getData())

    def end_data(self):
        self.addObject(Data.fromBase64(self.getData().encode('utf-8')))

    def end_date(self):
        self.addObject(_dateFromString(self.getData()))

