import re
__all__ = ['TextWrapper', 'wrap', 'fill', 'dedent', 'indent']
_whitespace = '\t\n\x0b\x0c\r '

class TextWrapper:
    __qualname__ = 'TextWrapper'
    unicode_whitespace_trans = {}
    uspace = ord(' ')
    for x in _whitespace:
        unicode_whitespace_trans[ord(x)] = uspace
    wordsep_re = re.compile('(\\s+|[^\\s\\w]*\\w+[^0-9\\W]-(?=\\w+[^0-9\\W])|(?<=[\\w\\!\\"\\\'\\&\\.\\,\\?])-{2,}(?=\\w))')
    wordsep_simple_re = re.compile('(\\s+)')
    sentence_end_re = re.compile('[a-z][\\.\\!\\?][\\"\\\']?\\Z')

    def __init__(self, width=70, initial_indent='', subsequent_indent='', expand_tabs=True, replace_whitespace=True, fix_sentence_endings=False, break_long_words=True, drop_whitespace=True, break_on_hyphens=True, tabsize=8):
        self.width = width
        self.initial_indent = initial_indent
        self.subsequent_indent = subsequent_indent
        self.expand_tabs = expand_tabs
        self.replace_whitespace = replace_whitespace
        self.fix_sentence_endings = fix_sentence_endings
        self.break_long_words = break_long_words
        self.drop_whitespace = drop_whitespace
        self.break_on_hyphens = break_on_hyphens
        self.tabsize = tabsize

    def _munge_whitespace(self, text):
        if self.expand_tabs:
            text = text.expandtabs(self.tabsize)
        if self.replace_whitespace:
            text = text.translate(self.unicode_whitespace_trans)
        return text

    def _split(self, text):
        if self.break_on_hyphens is True:
            chunks = self.wordsep_re.split(text)
        else:
            chunks = self.wordsep_simple_re.split(text)
        chunks = [c for c in chunks if c]
        return chunks

    def _fix_sentence_endings(self, chunks):
        i = 0
        patsearch = self.sentence_end_re.search
        while i < len(chunks) - 1:
            if chunks[i + 1] == ' ' and patsearch(chunks[i]):
                chunks[i + 1] = '  '
                i += 2
            else:
                i += 1

    def _handle_long_word(self, reversed_chunks, cur_line, cur_len, width):
        if width < 1:
            space_left = 1
        else:
            space_left = width - cur_len
        if self.break_long_words:
            cur_line.append(reversed_chunks[-1][:space_left])
            reversed_chunks[-1] = reversed_chunks[-1][space_left:]
        elif not cur_line:
            cur_line.append(reversed_chunks.pop())

    def _wrap_chunks(self, chunks):
        lines = []
        if self.width <= 0:
            raise ValueError('invalid width %r (must be > 0)' % self.width)
        chunks.reverse()
        while chunks:
            cur_line = []
            cur_len = 0
            if lines:
                indent = self.subsequent_indent
            else:
                indent = self.initial_indent
            width = self.width - len(indent)
            if self.drop_whitespace and chunks[-1].strip() == '' and lines:
                del chunks[-1]
            while chunks:
                l = len(chunks[-1])
                if cur_len + l <= width:
                    cur_line.append(chunks.pop())
                    cur_len += l
                else:
                    break
            if chunks and len(chunks[-1]) > width:
                self._handle_long_word(chunks, cur_line, cur_len, width)
            if self.drop_whitespace and cur_line and cur_line[-1].strip() == '':
                del cur_line[-1]
            while cur_line:
                lines.append(indent + ''.join(cur_line))
                continue
        return lines

    def wrap(self, text):
        text = self._munge_whitespace(text)
        chunks = self._split(text)
        if self.fix_sentence_endings:
            self._fix_sentence_endings(chunks)
        return self._wrap_chunks(chunks)

    def fill(self, text):
        return '\n'.join(self.wrap(text))

def wrap(text, width=70, **kwargs):
    w = TextWrapper(width=width, **kwargs)
    return w.wrap(text)

def fill(text, width=70, **kwargs):
    w = TextWrapper(width=width, **kwargs)
    return w.fill(text)

_whitespace_only_re = re.compile('^[ \t]+$', re.MULTILINE)
_leading_whitespace_re = re.compile('(^[ \t]*)(?:[^ \t\n])', re.MULTILINE)

def dedent(text):
    margin = None
    text = _whitespace_only_re.sub('', text)
    indents = _leading_whitespace_re.findall(text)
    for indent in indents:
        if margin is None:
            margin = indent
        elif indent.startswith(margin):
            pass
        elif margin.startswith(indent):
            margin = indent
        else:
            margin = ''
            break
    if 0 and margin:
        for line in text.split('\n'):
            pass
    if margin:
        text = re.sub('(?m)^' + margin, '', text)
    return text

def indent(text, prefix, predicate=None):
    if predicate is None:

        def predicate(line):
            return line.strip()

    def prefixed_lines():
        for line in text.splitlines(True):
            yield prefix + line if predicate(line) else line

    return ''.join(prefixed_lines())

if __name__ == '__main__':
    print(dedent('Hello there.\n  This is indented.'))
