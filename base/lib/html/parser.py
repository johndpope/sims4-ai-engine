import _markupbase
import re
import warnings
interesting_normal = re.compile('[&<]')
incomplete = re.compile('&[a-zA-Z#]')
entityref = re.compile('&([a-zA-Z][-.a-zA-Z0-9]*)[^a-zA-Z0-9]')
charref = re.compile('&#(?:[0-9]+|[xX][0-9a-fA-F]+)[^0-9a-fA-F]')
starttagopen = re.compile('<[a-zA-Z]')
piclose = re.compile('>')
commentclose = re.compile('--\\s*>')
tagfind = re.compile('([a-zA-Z][-.a-zA-Z0-9:_]*)(?:\\s|/(?!>))*')
tagfind_tolerant = re.compile('([a-zA-Z][^\t\n\r\x0c />\x00]*)(?:\\s|/(?!>))*')
attrfind = re.compile('\\s*([a-zA-Z_][-.:a-zA-Z_0-9]*)(\\s*=\\s*(\\\'[^\\\']*\\\'|"[^"]*"|[^\\s"\\\'=<>`]*))?')
attrfind_tolerant = re.compile('((?<=[\\\'"\\s/])[^\\s/>][^\\s/=>]*)(\\s*=+\\s*(\\\'[^\\\']*\\\'|"[^"]*"|(?![\\\'"])[^>\\s]*))?(?:\\s|/(?!>))*')
locatestarttagend = re.compile('\n  <[a-zA-Z][-.a-zA-Z0-9:_]*          # tag name\n  (?:\\s+                             # whitespace before attribute name\n    (?:[a-zA-Z_][-.:a-zA-Z0-9_]*     # attribute name\n      (?:\\s*=\\s*                     # value indicator\n        (?:\'[^\']*\'                   # LITA-enclosed value\n          |\\"[^\\"]*\\"                # LIT-enclosed value\n          |[^\'\\">\\s]+                # bare value\n         )\n       )?\n     )\n   )*\n  \\s*                                # trailing whitespace\n', re.VERBOSE)
locatestarttagend_tolerant = re.compile('\n  <[a-zA-Z][^\\t\\n\\r\\f />\\x00]*       # tag name\n  (?:[\\s/]*                          # optional whitespace before attribute name\n    (?:(?<=[\'"\\s/])[^\\s/>][^\\s/=>]*  # attribute name\n      (?:\\s*=+\\s*                    # value indicator\n        (?:\'[^\']*\'                   # LITA-enclosed value\n          |"[^"]*"                   # LIT-enclosed value\n          |(?![\'"])[^>\\s]*           # bare value\n         )\n         (?:\\s*,)*                   # possibly followed by a comma\n       )?(?:\\s|/(?!>))*\n     )*\n   )?\n  \\s*                                # trailing whitespace\n', re.VERBOSE)
endendtag = re.compile('>')
endtagfind = re.compile('</\\s*([a-zA-Z][-.a-zA-Z0-9:_]*)\\s*>')

class HTMLParseError(Exception):
    __qualname__ = 'HTMLParseError'

    def __init__(self, msg, position=(None, None)):
        self.msg = msg
        self.lineno = position[0]
        self.offset = position[1]

    def __str__(self):
        result = self.msg
        if self.lineno is not None:
            result = result + ', at line %d' % self.lineno
        if self.offset is not None:
            result = result + ', column %d' % (self.offset + 1)
        return result

class HTMLParser(_markupbase.ParserBase):
    __qualname__ = 'HTMLParser'
    CDATA_CONTENT_ELEMENTS = ('script', 'style')

    def __init__(self, strict=False):
        if strict:
            warnings.warn('The strict mode is deprecated.', DeprecationWarning, stacklevel=2)
        self.strict = strict
        self.reset()

    def reset(self):
        self.rawdata = ''
        self.lasttag = '???'
        self.interesting = interesting_normal
        self.cdata_elem = None
        _markupbase.ParserBase.reset(self)

    def feed(self, data):
        self.rawdata = self.rawdata + data
        self.goahead(0)

    def close(self):
        self.goahead(1)

    def error(self, message):
        raise HTMLParseError(message, self.getpos())

    _HTMLParser__starttag_text = None

    def get_starttag_text(self):
        return self._HTMLParser__starttag_text

    def set_cdata_mode(self, elem):
        self.cdata_elem = elem.lower()
        self.interesting = re.compile('</\\s*%s\\s*>' % self.cdata_elem, re.I)

    def clear_cdata_mode(self):
        self.interesting = interesting_normal
        self.cdata_elem = None

    def goahead(self, end):
        rawdata = self.rawdata
        i = 0
        n = len(rawdata)
        while i < n:
            match = self.interesting.search(rawdata, i)
            if match:
                j = match.start()
            else:
                if self.cdata_elem:
                    break
                j = n
            if i < j:
                self.handle_data(rawdata[i:j])
            i = self.updatepos(i, j)
            if i == n:
                break
            startswith = rawdata.startswith
            if startswith('<', i):
                if starttagopen.match(rawdata, i):
                    k = self.parse_starttag(i)
                elif startswith('</', i):
                    k = self.parse_endtag(i)
                elif startswith('<!--', i):
                    k = self.parse_comment(i)
                elif startswith('<?', i):
                    k = self.parse_pi(i)
                elif startswith('<!', i):
                    if self.strict:
                        k = self.parse_declaration(i)
                    else:
                        k = self.parse_html_declaration(i)
                elif i + 1 < n:
                    self.handle_data('<')
                    k = i + 1
                else:
                    break
                if k < 0:
                    if not end:
                        break
                    if self.strict:
                        self.error('EOF in middle of construct')
                    k = rawdata.find('>', i + 1)
                    if k < 0:
                        k = rawdata.find('<', i + 1)
                        k = i + 1
                    else:
                        k += 1
                    self.handle_data(rawdata[i:k])
                i = self.updatepos(i, k)
            elif startswith('&#', i):
                match = charref.match(rawdata, i)
                if match:
                    name = match.group()[2:-1]
                    self.handle_charref(name)
                    k = match.end()
                    if not startswith(';', k - 1):
                        k = k - 1
                    i = self.updatepos(i, k)
                    continue
                else:
                    if ';' in rawdata[i:]:
                        self.handle_data(rawdata[i:i + 2])
                        i = self.updatepos(i, i + 2)
                    break
                    continue
                    while startswith('&', i):
                        match = entityref.match(rawdata, i)
                        if match:
                            name = match.group(1)
                            self.handle_entityref(name)
                            k = match.end()
                            if not startswith(';', k - 1):
                                k = k - 1
                            i = self.updatepos(i, k)
                            continue
                        match = incomplete.match(rawdata, i)
                        if match:
                            if end and match.group() == rawdata[i:]:
                                if self.strict:
                                    self.error('EOF in middle of entity or char ref')
                                else:
                                    k = match.end()
                                    if k <= i:
                                        k = n
                                    i = self.updatepos(i, i + 1)
                            break
                        elif i + 1 < n:
                            self.handle_data('&')
                            i = self.updatepos(i, i + 1)
                        else:
                            break
                            continue
            else:
                while startswith('&', i):
                    match = entityref.match(rawdata, i)
                    if match:
                        name = match.group(1)
                        self.handle_entityref(name)
                        k = match.end()
                        if not startswith(';', k - 1):
                            k = k - 1
                        i = self.updatepos(i, k)
                        continue
                    match = incomplete.match(rawdata, i)
                    if match:
                        if end and match.group() == rawdata[i:]:
                            if self.strict:
                                self.error('EOF in middle of entity or char ref')
                            else:
                                k = match.end()
                                if k <= i:
                                    k = n
                                i = self.updatepos(i, i + 1)
                        break
                    elif i + 1 < n:
                        self.handle_data('&')
                        i = self.updatepos(i, i + 1)
                    else:
                        break
                        continue
        if end and i < n and not self.cdata_elem:
            self.handle_data(rawdata[i:n])
            i = self.updatepos(i, n)
        self.rawdata = rawdata[i:]

    def parse_html_declaration(self, i):
        rawdata = self.rawdata
        if rawdata[i:i + 4] == '<!--':
            return self.parse_comment(i)
        if rawdata[i:i + 3] == '<![':
            return self.parse_marked_section(i)
        if rawdata[i:i + 9].lower() == '<!doctype':
            gtpos = rawdata.find('>', i + 9)
            if gtpos == -1:
                return -1
            self.handle_decl(rawdata[i + 2:gtpos])
            return gtpos + 1
        return self.parse_bogus_comment(i)

    def parse_bogus_comment(self, i, report=1):
        rawdata = self.rawdata
        pos = rawdata.find('>', i + 2)
        if pos == -1:
            return -1
        if report:
            self.handle_comment(rawdata[i + 2:pos])
        return pos + 1

    def parse_pi(self, i):
        rawdata = self.rawdata
        match = piclose.search(rawdata, i + 2)
        if not match:
            return -1
        j = match.start()
        self.handle_pi(rawdata[i + 2:j])
        j = match.end()
        return j

    def parse_starttag(self, i):
        self._HTMLParser__starttag_text = None
        endpos = self.check_for_whole_start_tag(i)
        if endpos < 0:
            return endpos
        rawdata = self.rawdata
        self._HTMLParser__starttag_text = rawdata[i:endpos]
        attrs = []
        if self.strict:
            match = tagfind.match(rawdata, i + 1)
        else:
            match = tagfind_tolerant.match(rawdata, i + 1)
        k = match.end()
        self.lasttag = tag = match.group(1).lower()
        while k < endpos:
            if self.strict:
                m = attrfind.match(rawdata, k)
            else:
                m = attrfind_tolerant.match(rawdata, k)
            if not m:
                break
            (attrname, rest, attrvalue) = m.group(1, 2, 3)
            if not rest:
                attrvalue = None
            elif attrvalue[:1] == "'" == attrvalue[-1:] or attrvalue[:1] == '"' == attrvalue[-1:]:
                attrvalue = attrvalue[1:-1]
            if attrvalue:
                attrvalue = self.unescape(attrvalue)
            attrs.append((attrname.lower(), attrvalue))
            k = m.end()
        end = rawdata[k:endpos].strip()
        if end not in ('>', '/>'):
            (lineno, offset) = self.getpos()
            if '\n' in self._HTMLParser__starttag_text:
                lineno = lineno + self._HTMLParser__starttag_text.count('\n')
                offset = len(self._HTMLParser__starttag_text) - self._HTMLParser__starttag_text.rfind('\n')
            else:
                offset = offset + len(self._HTMLParser__starttag_text)
            if self.strict:
                self.error('junk characters in start tag: %r' % (rawdata[k:endpos][:20],))
            self.handle_data(rawdata[i:endpos])
            return endpos
        if end.endswith('/>'):
            self.handle_startendtag(tag, attrs)
        else:
            self.handle_starttag(tag, attrs)
            if tag in self.CDATA_CONTENT_ELEMENTS:
                self.set_cdata_mode(tag)
        return endpos

    def check_for_whole_start_tag(self, i):
        rawdata = self.rawdata
        if self.strict:
            m = locatestarttagend.match(rawdata, i)
        else:
            m = locatestarttagend_tolerant.match(rawdata, i)
        if m:
            j = m.end()
            next = rawdata[j:j + 1]
            if next == '>':
                return j + 1
            if next == '/':
                if rawdata.startswith('/>', j):
                    return j + 2
                if rawdata.startswith('/', j):
                    return -1
                if self.strict:
                    self.updatepos(i, j + 1)
                    self.error('malformed empty start tag')
                if j > i:
                    return j
                return i + 1
            if next == '':
                return -1
            if next in 'abcdefghijklmnopqrstuvwxyz=/ABCDEFGHIJKLMNOPQRSTUVWXYZ':
                return -1
            if self.strict:
                self.updatepos(i, j)
                self.error('malformed start tag')
            if j > i:
                return j
            return i + 1
        raise AssertionError('we should not get here!')

    def parse_endtag(self, i):
        rawdata = self.rawdata
        match = endendtag.search(rawdata, i + 1)
        if not match:
            return -1
        gtpos = match.end()
        match = endtagfind.match(rawdata, i)
        if not match:
            if self.cdata_elem is not None:
                self.handle_data(rawdata[i:gtpos])
                return gtpos
            if self.strict:
                self.error('bad end tag: %r' % (rawdata[i:gtpos],))
            namematch = tagfind_tolerant.match(rawdata, i + 2)
            if not namematch:
                if rawdata[i:i + 3] == '</>':
                    return i + 3
                return self.parse_bogus_comment(i)
            tagname = namematch.group(1).lower()
            gtpos = rawdata.find('>', namematch.end())
            self.handle_endtag(tagname)
            return gtpos + 1
        elem = match.group(1).lower()
        if self.cdata_elem is not None and elem != self.cdata_elem:
            self.handle_data(rawdata[i:gtpos])
            return gtpos
        self.handle_endtag(elem.lower())
        self.clear_cdata_mode()
        return gtpos

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_starttag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        pass

    def handle_charref(self, name):
        pass

    def handle_entityref(self, name):
        pass

    def handle_data(self, data):
        pass

    def handle_comment(self, data):
        pass

    def handle_decl(self, decl):
        pass

    def handle_pi(self, data):
        pass

    def unknown_decl(self, data):
        if self.strict:
            self.error('unknown declaration: %r' % (data,))

    def unescape(self, s):
        if '&' not in s:
            return s

        def replaceEntities(s):
            s = s.groups()[0]
            try:
                if s[0] == '#':
                    s = s[1:]
                    if s[0] in ('x', 'X'):
                        c = int(s[1:].rstrip(';'), 16)
                    else:
                        c = int(s.rstrip(';'))
                    return chr(c)
            except ValueError:
                return '&#' + s
            from html.entities import html5
            if s in html5:
                return html5[s]
            if s.endswith(';'):
                return '&' + s
            for x in range(2, len(s)):
                while s[:x] in html5:
                    return html5[s[:x]] + s[x:]
            return '&' + s

        return re.sub('&(#?[xX]?(?:[0-9a-fA-F]+;|\\w{1,32};?))', replaceEntities, s, flags=re.ASCII)

