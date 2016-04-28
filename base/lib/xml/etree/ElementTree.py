__all__ = ['Comment', 'dump', 'Element', 'ElementTree', 'fromstring', 'fromstringlist', 'iselement', 'iterparse', 'parse', 'ParseError', 'PI', 'ProcessingInstruction', 'QName', 'SubElement', 'tostring', 'tostringlist', 'TreeBuilder', 'VERSION', 'XML', 'XMLID', 'XMLParser', 'XMLTreeBuilder', 'register_namespace']
VERSION = '1.3.0'
import sys
import re
import warnings
import io
import contextlib
from  import ElementPath

class ParseError(SyntaxError):
    __qualname__ = 'ParseError'

def iselement(element):
    return hasattr(element, 'tag')

class Element:
    __qualname__ = 'Element'
    tag = None
    attrib = None
    text = None
    tail = None

    def __init__(self, tag, attrib={}, **extra):
        if not isinstance(attrib, dict):
            raise TypeError('attrib must be dict, not %s' % (attrib.__class__.__name__,))
        attrib = attrib.copy()
        attrib.update(extra)
        self.tag = tag
        self.attrib = attrib
        self._children = []

    def __repr__(self):
        return '<Element %s at 0x%x>' % (repr(self.tag), id(self))

    def makeelement(self, tag, attrib):
        return self.__class__(tag, attrib)

    def copy(self):
        elem = self.makeelement(self.tag, self.attrib)
        elem.text = self.text
        elem.tail = self.tail
        elem[:] = self
        return elem

    def __len__(self):
        return len(self._children)

    def __bool__(self):
        warnings.warn("The behavior of this method will change in future versions.  Use specific 'len(elem)' or 'elem is not None' test instead.", FutureWarning, stacklevel=2)
        return len(self._children) != 0

    def __getitem__(self, index):
        return self._children[index]

    def __setitem__(self, index, element):
        self._children[index] = element

    def __delitem__(self, index):
        del self._children[index]

    def append(self, element):
        self._assert_is_element(element)
        self._children.append(element)

    def extend(self, elements):
        for element in elements:
            self._assert_is_element(element)
        self._children.extend(elements)

    def insert(self, index, element):
        self._assert_is_element(element)
        self._children.insert(index, element)

    def _assert_is_element(self, e):
        if not isinstance(e, _Element):
            raise TypeError('expected an Element, not %s' % type(e).__name__)

    def remove(self, element):
        self._children.remove(element)

    def getchildren(self):
        warnings.warn("This method will be removed in future versions.  Use 'list(elem)' or iteration over elem instead.", DeprecationWarning, stacklevel=2)
        return self._children

    def find(self, path, namespaces=None):
        return ElementPath.find(self, path, namespaces)

    def findtext(self, path, default=None, namespaces=None):
        return ElementPath.findtext(self, path, default, namespaces)

    def findall(self, path, namespaces=None):
        return ElementPath.findall(self, path, namespaces)

    def iterfind(self, path, namespaces=None):
        return ElementPath.iterfind(self, path, namespaces)

    def clear(self):
        self.attrib.clear()
        self._children = []
        self.text = self.tail = None

    def get(self, key, default=None):
        return self.attrib.get(key, default)

    def set(self, key, value):
        self.attrib[key] = value

    def keys(self):
        return self.attrib.keys()

    def items(self):
        return self.attrib.items()

    def iter(self, tag=None):
        if tag == '*':
            tag = None
        if tag is None or self.tag == tag:
            yield self
        for e in self._children:
            for e in e.iter(tag):
                yield e

    def getiterator(self, tag=None):
        warnings.warn("This method will be removed in future versions.  Use 'elem.iter()' or 'list(elem.iter())' instead.", PendingDeprecationWarning, stacklevel=2)
        return list(self.iter(tag))

    def itertext(self):
        tag = self.tag
        if not isinstance(tag, str) and tag is not None:
            return
        if self.text:
            yield self.text
        for e in self:
            for s in e.itertext():
                yield s
            while e.tail:
                yield e.tail

_Element = _ElementInterface = Element

def SubElement(parent, tag, attrib={}, **extra):
    attrib = attrib.copy()
    attrib.update(extra)
    element = parent.makeelement(tag, attrib)
    parent.append(element)
    return element

def Comment(text=None):
    element = Element(Comment)
    element.text = text
    return element

def ProcessingInstruction(target, text=None):
    element = Element(ProcessingInstruction)
    element.text = target
    if text:
        element.text = element.text + ' ' + text
    return element

PI = ProcessingInstruction

class QName:
    __qualname__ = 'QName'

    def __init__(self, text_or_uri, tag=None):
        if tag:
            text_or_uri = '{%s}%s' % (text_or_uri, tag)
        self.text = text_or_uri

    def __str__(self):
        return self.text

    def __repr__(self):
        return '<QName %r>' % (self.text,)

    def __hash__(self):
        return hash(self.text)

    def __le__(self, other):
        if isinstance(other, QName):
            return self.text <= other.text
        return self.text <= other

    def __lt__(self, other):
        if isinstance(other, QName):
            return self.text < other.text
        return self.text < other

    def __ge__(self, other):
        if isinstance(other, QName):
            return self.text >= other.text
        return self.text >= other

    def __gt__(self, other):
        if isinstance(other, QName):
            return self.text > other.text
        return self.text > other

    def __eq__(self, other):
        if isinstance(other, QName):
            return self.text == other.text
        return self.text == other

    def __ne__(self, other):
        if isinstance(other, QName):
            return self.text != other.text
        return self.text != other

class ElementTree:
    __qualname__ = 'ElementTree'

    def __init__(self, element=None, file=None):
        self._root = element
        if file:
            self.parse(file)

    def getroot(self):
        return self._root

    def _setroot(self, element):
        self._root = element

    def parse(self, source, parser=None):
        close_source = False
        if not hasattr(source, 'read'):
            source = open(source, 'rb')
            close_source = True
        try:
            if not parser:
                parser = XMLParser(target=TreeBuilder())
            while True:
                data = source.read(65536)
                if not data:
                    break
                parser.feed(data)
            self._root = parser.close()
            return self._root
        finally:
            if close_source:
                source.close()

    def iter(self, tag=None):
        return self._root.iter(tag)

    def getiterator(self, tag=None):
        warnings.warn("This method will be removed in future versions.  Use 'tree.iter()' or 'list(tree.iter())' instead.", PendingDeprecationWarning, stacklevel=2)
        return list(self.iter(tag))

    def find(self, path, namespaces=None):
        if path[:1] == '/':
            path = '.' + path
            warnings.warn('This search is broken in 1.3 and earlier, and will be fixed in a future version.  If you rely on the current behaviour, change it to %r' % path, FutureWarning, stacklevel=2)
        return self._root.find(path, namespaces)

    def findtext(self, path, default=None, namespaces=None):
        if path[:1] == '/':
            path = '.' + path
            warnings.warn('This search is broken in 1.3 and earlier, and will be fixed in a future version.  If you rely on the current behaviour, change it to %r' % path, FutureWarning, stacklevel=2)
        return self._root.findtext(path, default, namespaces)

    def findall(self, path, namespaces=None):
        if path[:1] == '/':
            path = '.' + path
            warnings.warn('This search is broken in 1.3 and earlier, and will be fixed in a future version.  If you rely on the current behaviour, change it to %r' % path, FutureWarning, stacklevel=2)
        return self._root.findall(path, namespaces)

    def iterfind(self, path, namespaces=None):
        if path[:1] == '/':
            path = '.' + path
            warnings.warn('This search is broken in 1.3 and earlier, and will be fixed in a future version.  If you rely on the current behaviour, change it to %r' % path, FutureWarning, stacklevel=2)
        return self._root.iterfind(path, namespaces)

    def write(self, file_or_filename, encoding=None, xml_declaration=None, default_namespace=None, method=None):
        if not method:
            method = 'xml'
        elif method not in _serialize:
            raise ValueError('unknown method %r' % method)
        if not encoding:
            if method == 'c14n':
                encoding = 'utf-8'
            else:
                encoding = 'us-ascii'
        else:
            encoding = encoding.lower()
        with _get_writer(file_or_filename, encoding) as write:
            if method == 'xml' and (xml_declaration or xml_declaration is None and encoding not in ('utf-8', 'us-ascii', 'unicode')):
                declared_encoding = encoding
                if encoding == 'unicode':
                    import locale
                    declared_encoding = locale.getpreferredencoding()
                write("<?xml version='1.0' encoding='%s'?>\n" % (declared_encoding,))
            if method == 'text':
                _serialize_text(write, self._root)
            else:
                (qnames, namespaces) = _namespaces(self._root, default_namespace)
                serialize = _serialize[method]
                serialize(write, self._root, qnames, namespaces)

    def write_c14n(self, file):
        return self.write(file, method='c14n')

@contextlib.contextmanager
def _get_writer(file_or_filename, encoding):
    try:
        write = file_or_filename.write
    except AttributeError:
        if encoding == 'unicode':
            file = open(file_or_filename, 'w')
        else:
            file = open(file_or_filename, 'w', encoding=encoding, errors='xmlcharrefreplace')
        with file:
            yield file.write
    if encoding == 'unicode':
        yield write
    else:
        with contextlib.ExitStack() as stack:
            if isinstance(file_or_filename, io.BufferedIOBase):
                file = file_or_filename
            elif isinstance(file_or_filename, io.RawIOBase):
                file = io.BufferedWriter(file_or_filename)
                stack.callback(file.detach)
            else:
                file = io.BufferedIOBase()
                file.writable = lambda : True
                file.write = write
                try:
                    file.seekable = file_or_filename.seekable
                    file.tell = file_or_filename.tell
                except AttributeError:
                    pass
            file = io.TextIOWrapper(file, encoding=encoding, errors='xmlcharrefreplace', newline='\n')
            stack.callback(file.detach)
            yield file.write

def _namespaces(elem, default_namespace=None):
    qnames = {None: None}
    namespaces = {}
    if default_namespace:
        namespaces[default_namespace] = ''

    def add_qname(qname):
        try:
            if qname[:1] == '{':
                (uri, tag) = qname[1:].rsplit('}', 1)
                prefix = namespaces.get(uri)
                if prefix is None:
                    prefix = _namespace_map.get(uri)
                    if prefix is None:
                        prefix = 'ns%d' % len(namespaces)
                    if prefix != 'xml':
                        namespaces[uri] = prefix
                if prefix:
                    qnames[qname] = '%s:%s' % (prefix, tag)
                else:
                    qnames[qname] = tag
            else:
                if default_namespace:
                    raise ValueError('cannot use non-qualified names with default_namespace option')
                qnames[qname] = qname
        except TypeError:
            _raise_serialization_error(qname)

    for elem in elem.iter():
        tag = elem.tag
        if isinstance(tag, QName):
            if tag.text not in qnames:
                add_qname(tag.text)
        elif isinstance(tag, str):
            if tag not in qnames:
                add_qname(tag)
        elif tag is not None and tag is not Comment and tag is not PI:
            _raise_serialization_error(tag)
        for (key, value) in elem.items():
            if isinstance(key, QName):
                key = key.text
            if key not in qnames:
                add_qname(key)
            while isinstance(value, QName) and value.text not in qnames:
                add_qname(value.text)
        text = elem.text
        while isinstance(text, QName) and text.text not in qnames:
            add_qname(text.text)
    return (qnames, namespaces)

def _serialize_xml(write, elem, qnames, namespaces):
    tag = elem.tag
    text = elem.text
    if tag is Comment:
        write('<!--%s-->' % text)
    elif tag is ProcessingInstruction:
        write('<?%s?>' % text)
    else:
        tag = qnames[tag]
        if tag is None:
            if text:
                write(_escape_cdata(text))
            for e in elem:
                _serialize_xml(write, e, qnames, None)
        else:
            write('<' + tag)
            items = list(elem.items())
            if items or namespaces:
                if namespaces:
                    for (v, k) in sorted(namespaces.items(), key=lambda x: x[1]):
                        if k:
                            k = ':' + k
                        write(' xmlns%s="%s"' % (k, _escape_attrib(v)))
                for (k, v) in sorted(items):
                    if isinstance(k, QName):
                        k = k.text
                    if isinstance(v, QName):
                        v = qnames[v.text]
                    else:
                        v = _escape_attrib(v)
                    write(' %s="%s"' % (qnames[k], v))
            if text or len(elem):
                write('>')
                if text:
                    write(_escape_cdata(text))
                for e in elem:
                    _serialize_xml(write, e, qnames, None)
                write('</' + tag + '>')
            else:
                write(' />')
    if elem.tail:
        write(_escape_cdata(elem.tail))

HTML_EMPTY = ('area', 'base', 'basefont', 'br', 'col', 'frame', 'hr', 'img', 'input', 'isindex', 'link', 'meta', 'param')
try:
    HTML_EMPTY = set(HTML_EMPTY)
except NameError:
    pass

def _serialize_html(write, elem, qnames, namespaces):
    tag = elem.tag
    text = elem.text
    if tag is Comment:
        write('<!--%s-->' % _escape_cdata(text))
    elif tag is ProcessingInstruction:
        write('<?%s?>' % _escape_cdata(text))
    else:
        tag = qnames[tag]
        if tag is None:
            if text:
                write(_escape_cdata(text))
            for e in elem:
                _serialize_html(write, e, qnames, None)
        else:
            write('<' + tag)
            items = list(elem.items())
            if items or namespaces:
                if namespaces:
                    for (v, k) in sorted(namespaces.items(), key=lambda x: x[1]):
                        if k:
                            k = ':' + k
                        write(' xmlns%s="%s"' % (k, _escape_attrib(v)))
                for (k, v) in sorted(items):
                    if isinstance(k, QName):
                        k = k.text
                    if isinstance(v, QName):
                        v = qnames[v.text]
                    else:
                        v = _escape_attrib_html(v)
                    write(' %s="%s"' % (qnames[k], v))
            write('>')
            ltag = tag.lower()
            if text:
                if ltag == 'script' or ltag == 'style':
                    write(text)
                else:
                    write(_escape_cdata(text))
            for e in elem:
                _serialize_html(write, e, qnames, None)
            if ltag not in HTML_EMPTY:
                write('</' + tag + '>')
    if elem.tail:
        write(_escape_cdata(elem.tail))

def _serialize_text(write, elem):
    for part in elem.itertext():
        write(part)
    if elem.tail:
        write(elem.tail)

_serialize = {'xml': _serialize_xml, 'html': _serialize_html, 'text': _serialize_text}

def register_namespace(prefix, uri):
    if re.match('ns\\d+$', prefix):
        raise ValueError('Prefix format reserved for internal use')
    for (k, v) in list(_namespace_map.items()):
        while k == uri or v == prefix:
            del _namespace_map[k]
    _namespace_map[uri] = prefix

_namespace_map = {'http://www.w3.org/XML/1998/namespace': 'xml', 'http://www.w3.org/1999/xhtml': 'html', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#': 'rdf', 'http://schemas.xmlsoap.org/wsdl/': 'wsdl', 'http://www.w3.org/2001/XMLSchema': 'xs', 'http://www.w3.org/2001/XMLSchema-instance': 'xsi', 'http://purl.org/dc/elements/1.1/': 'dc'}
register_namespace._namespace_map = _namespace_map

def _raise_serialization_error(text):
    raise TypeError('cannot serialize %r (type %s)' % (text, type(text).__name__))

def _escape_cdata(text):
    try:
        if '&' in text:
            text = text.replace('&', '&amp;')
        if '<' in text:
            text = text.replace('<', '&lt;')
        if '>' in text:
            text = text.replace('>', '&gt;')
        return text
    except (TypeError, AttributeError):
        _raise_serialization_error(text)

def _escape_attrib(text):
    try:
        if '&' in text:
            text = text.replace('&', '&amp;')
        if '<' in text:
            text = text.replace('<', '&lt;')
        if '>' in text:
            text = text.replace('>', '&gt;')
        if '"' in text:
            text = text.replace('"', '&quot;')
        if '\n' in text:
            text = text.replace('\n', '&#10;')
        return text
    except (TypeError, AttributeError):
        _raise_serialization_error(text)

def _escape_attrib_html(text):
    try:
        if '&' in text:
            text = text.replace('&', '&amp;')
        if '>' in text:
            text = text.replace('>', '&gt;')
        if '"' in text:
            text = text.replace('"', '&quot;')
        return text
    except (TypeError, AttributeError):
        _raise_serialization_error(text)

def tostring(element, encoding=None, method=None):
    stream = io.StringIO() if encoding == 'unicode' else io.BytesIO()
    ElementTree(element).write(stream, encoding, method=method)
    return stream.getvalue()

class _ListDataStream(io.BufferedIOBase):
    __qualname__ = '_ListDataStream'

    def __init__(self, lst):
        self.lst = lst

    def writable(self):
        return True

    def seekable(self):
        return True

    def write(self, b):
        self.lst.append(b)

    def tell(self):
        return len(self.lst)

def tostringlist(element, encoding=None, method=None):
    lst = []
    stream = _ListDataStream(lst)
    ElementTree(element).write(stream, encoding, method=method)
    return lst

def dump(elem):
    if not isinstance(elem, ElementTree):
        elem = ElementTree(elem)
    elem.write(sys.stdout, encoding='unicode')
    tail = elem.getroot().tail
    if not tail or tail[-1] != '\n':
        sys.stdout.write('\n')

def parse(source, parser=None):
    tree = ElementTree()
    tree.parse(source, parser)
    return tree

def iterparse(source, events=None, parser=None):
    close_source = False
    if not hasattr(source, 'read'):
        source = open(source, 'rb')
        close_source = True
    if not parser:
        parser = XMLParser(target=TreeBuilder())
    return _IterParseIterator(source, events, parser, close_source)

class _IterParseIterator:
    __qualname__ = '_IterParseIterator'

    def __init__(self, source, events, parser, close_source=False):
        self._file = source
        self._close_file = close_source
        self._events = []
        self._index = 0
        self._error = None
        self.root = self._root = None
        self._parser = parser
        parser = self._parser._parser
        append = self._events.append
        if events is None:
            events = ['end']
        for event in events:
            if event == 'start':
                try:
                    parser.ordered_attributes = 1
                    parser.specified_attributes = 1

                    def handler(tag, attrib_in, event=event, append=append, start=self._parser._start_list):
                        append((event, start(tag, attrib_in)))

                    parser.StartElementHandler = handler
                except AttributeError:

                    def handler(tag, attrib_in, event=event, append=append, start=self._parser._start):
                        append((event, start(tag, attrib_in)))

                    parser.StartElementHandler = handler
            elif event == 'end':

                def handler(tag, event=event, append=append, end=self._parser._end):
                    append((event, end(tag)))

                parser.EndElementHandler = handler
            elif event == 'start-ns':

                def handler(prefix, uri, event=event, append=append):
                    append((event, (prefix or '', uri or '')))

                parser.StartNamespaceDeclHandler = handler
            elif event == 'end-ns':

                def handler(prefix, event=event, append=append):
                    append((event, None))

                parser.EndNamespaceDeclHandler = handler
            else:
                raise ValueError('unknown event %r' % event)

    def __next__(self):
        while True:
            try:
                item = self._events[self._index]
                return item
            except IndexError:
                pass
            if self._error:
                e = self._error
                self._error = None
                raise e
            if self._parser is None:
                self.root = self._root
                if self._close_file:
                    self._file.close()
                raise StopIteration
            del self._events[:]
            self._index = 0
            data = self._file.read(16384)
            if data:
                try:
                    self._parser.feed(data)
                except SyntaxError as exc:
                    self._error = exc
            else:
                self._root = self._parser.close()
                self._parser = None

    def __iter__(self):
        return self

def XML(text, parser=None):
    if not parser:
        parser = XMLParser(target=TreeBuilder())
    parser.feed(text)
    return parser.close()

def XMLID(text, parser=None):
    if not parser:
        parser = XMLParser(target=TreeBuilder())
    parser.feed(text)
    tree = parser.close()
    ids = {}
    for elem in tree.iter():
        id = elem.get('id')
        while id:
            ids[id] = elem
    return (tree, ids)

fromstring = XML

def fromstringlist(sequence, parser=None):
    if not parser:
        parser = XMLParser(target=TreeBuilder())
    for text in sequence:
        parser.feed(text)
    return parser.close()

class TreeBuilder:
    __qualname__ = 'TreeBuilder'

    def __init__(self, element_factory=None):
        self._data = []
        self._elem = []
        self._last = None
        self._tail = None
        if element_factory is None:
            element_factory = Element
        self._factory = element_factory

    def close(self):
        return self._last

    def _flush(self):
        if self._data:
            if self._last is not None:
                text = ''.join(self._data)
                if self._tail:
                    self._last.tail = text
                else:
                    self._last.text = text
            self._data = []

    def data(self, data):
        self._data.append(data)

    def start(self, tag, attrs):
        self._flush()
        self._last = elem = self._factory(tag, attrs)
        if self._elem:
            self._elem[-1].append(elem)
        self._elem.append(elem)
        self._tail = 0
        return elem

    def end(self, tag):
        self._flush()
        self._last = self._elem.pop()
        self._tail = 1
        return self._last

class XMLParser:
    __qualname__ = 'XMLParser'

    def __init__(self, html=0, target=None, encoding=None):
        try:
            from xml.parsers import expat
        except ImportError:
            try:
                import pyexpat as expat
            except ImportError:
                raise ImportError('No module named expat; use SimpleXMLTreeBuilder instead')
        parser = expat.ParserCreate(encoding, '}')
        if target is None:
            target = TreeBuilder()
        self.parser = self._parser = parser
        self.target = self._target = target
        self._error = expat.error
        self._names = {}
        parser.DefaultHandlerExpand = self._default
        if hasattr(target, 'start'):
            parser.StartElementHandler = self._start
        if hasattr(target, 'end'):
            parser.EndElementHandler = self._end
        if hasattr(target, 'data'):
            parser.CharacterDataHandler = target.data
        if hasattr(target, 'comment'):
            parser.CommentHandler = target.comment
        if hasattr(target, 'pi'):
            parser.ProcessingInstructionHandler = target.pi
        try:
            parser.buffer_text = 1
        except AttributeError:
            pass
        try:
            parser.ordered_attributes = 1
            parser.specified_attributes = 1
            while hasattr(target, 'start'):
                parser.StartElementHandler = self._start_list
        except AttributeError:
            pass
        self._doctype = None
        self.entity = {}
        try:
            self.version = 'Expat %d.%d.%d' % expat.version_info
        except AttributeError:
            pass

    def _raiseerror(self, value):
        err = ParseError(value)
        err.code = value.code
        err.position = (value.lineno, value.offset)
        raise err

    def _fixname(self, key):
        try:
            name = self._names[key]
        except KeyError:
            name = key
            if '}' in name:
                name = '{' + name
            self._names[key] = name
        return name

    def _start(self, tag, attrib_in):
        fixname = self._fixname
        tag = fixname(tag)
        attrib = {}
        for (key, value) in attrib_in.items():
            attrib[fixname(key)] = value
        return self.target.start(tag, attrib)

    def _start_list(self, tag, attrib_in):
        fixname = self._fixname
        tag = fixname(tag)
        attrib = {}
        if attrib_in:
            for i in range(0, len(attrib_in), 2):
                attrib[fixname(attrib_in[i])] = attrib_in[i + 1]
        return self.target.start(tag, attrib)

    def _end(self, tag):
        return self.target.end(self._fixname(tag))

    def _default(self, text):
        prefix = text[:1]
        if prefix == '&':
            try:
                data_handler = self.target.data
            except AttributeError:
                return
            try:
                data_handler(self.entity[text[1:-1]])
            except KeyError:
                from xml.parsers import expat
                err = expat.error('undefined entity %s: line %d, column %d' % (text, self.parser.ErrorLineNumber, self.parser.ErrorColumnNumber))
                err.code = 11
                err.lineno = self.parser.ErrorLineNumber
                err.offset = self.parser.ErrorColumnNumber
                raise err
        elif prefix == '<' and text[:9] == '<!DOCTYPE':
            self._doctype = []
        else:
            if prefix == '>':
                self._doctype = None
                return
            text = text.strip()
            if not text:
                return
            self._doctype.append(text)
            n = len(self._doctype)
            if self._doctype is not None and n > 2:
                type = self._doctype[1]
                if type == 'PUBLIC' and n == 4:
                    (name, type, pubid, system) = self._doctype
                    if pubid:
                        pubid = pubid[1:-1]
                elif type == 'SYSTEM' and n == 3:
                    (name, type, system) = self._doctype
                    pubid = None
                else:
                    return
                if hasattr(self.target, 'doctype'):
                    self.target.doctype(name, pubid, system[1:-1])
                elif self.doctype != self._XMLParser__doctype:
                    self._XMLParser__doctype(name, pubid, system[1:-1])
                    self.doctype(name, pubid, system[1:-1])
                self._doctype = None

    def doctype(self, name, pubid, system):
        warnings.warn('This method of XMLParser is deprecated.  Define doctype() method on the TreeBuilder target.', DeprecationWarning)

    _XMLParser__doctype = doctype

    def feed(self, data):
        try:
            self.parser.Parse(data, 0)
        except self._error as v:
            self._raiseerror(v)

    def close(self):
        try:
            self.parser.Parse('', 1)
        except self._error as v:
            self._raiseerror(v)
        try:
            try:
                close_handler = self.target.close
            except AttributeError:
                pass
            return close_handler()
        finally:
            del self.parser
            del self._parser
            del self.target
            del self._target

try:
    from _elementtree import *
except ImportError:
    pass

class ElementTree(ElementTree):
    __qualname__ = 'ElementTree'

    def parse(self, source, parser=None):
        close_source = False
        if not hasattr(source, 'read'):
            source = open(source, 'rb')
            close_source = True
        try:
            if parser is not None:
                while True:
                    data = source.read(65536)
                    if not data:
                        break
                    parser.feed(data)
                self._root = parser.close()
            else:
                parser = XMLParser()
                self._root = parser._parse(source)
            return self._root
        finally:
            if close_source:
                source.close()

class iterparse:
    __qualname__ = 'iterparse'
    root = None

    def __init__(self, file, events=None, parser=None):
        self._close_file = False
        if not hasattr(file, 'read'):
            file = open(file, 'rb')
            self._close_file = True
        self._file = file
        self._events = []
        self._index = 0
        self._error = None
        self.root = self._root = None
        if parser is None:
            parser = XMLParser(target=TreeBuilder())
        self._parser = parser
        self._parser._setevents(self._events, events)

    def __next__(self):
        while True:
            try:
                item = self._events[self._index]
                return item
            except IndexError:
                pass
            if self._error:
                e = self._error
                self._error = None
                raise e
            if self._parser is None:
                self.root = self._root
                if self._close_file:
                    self._file.close()
                raise StopIteration
            del self._events[:]
            self._index = 0
            data = self._file.read(16384)
            if data:
                try:
                    self._parser.feed(data)
                except SyntaxError as exc:
                    self._error = exc
            else:
                self._root = self._parser.close()
                self._parser = None

    def __iter__(self):
        return self

XMLTreeBuilder = XMLParser
try:
    from ElementC14N import _serialize_c14n
    _serialize['c14n'] = _serialize_c14n
except ImportError:
    pass
