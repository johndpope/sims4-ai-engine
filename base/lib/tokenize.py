__author__ = 'Ka-Ping Yee <ping@lfw.org>'
__credits__ = 'GvR, ESR, Tim Peters, Thomas Wouters, Fred Drake, Skip Montanaro, Raymond Hettinger, Trent Nelson, Michael Foord'
import builtins
from codecs import lookup, BOM_UTF8
import collections
from io import TextIOWrapper
from itertools import chain
import re
import sys
from token import *
cookie_re = re.compile('^[ \\t\\f]*#.*coding[:=][ \\t]*([-\\w.]+)', re.ASCII)
blank_re = re.compile(b'^[ \\t\\f]*(?:[#\\r\\n]|$)', re.ASCII)
import token
__all__ = token.__all__ + ['COMMENT', 'tokenize', 'detect_encoding', 'NL', 'untokenize', 'ENCODING', 'TokenInfo']
del token
COMMENT = N_TOKENS
tok_name[COMMENT] = 'COMMENT'
NL = N_TOKENS + 1
tok_name[NL] = 'NL'
ENCODING = N_TOKENS + 2
tok_name[ENCODING] = 'ENCODING'
N_TOKENS += 3
EXACT_TOKEN_TYPES = {'(': LPAR, ')': RPAR, '[': LSQB, ']': RSQB, ':': COLON, ',': COMMA, ';': SEMI, '+': PLUS, '-': MINUS, '*': STAR, '/': SLASH, '|': VBAR, '&': AMPER, '<': LESS, '>': GREATER, '=': EQUAL, '.': DOT, '%': PERCENT, '{': LBRACE, '}': RBRACE, '==': EQEQUAL, '!=': NOTEQUAL, '<=': LESSEQUAL, '>=': GREATEREQUAL, '~': TILDE, '^': CIRCUMFLEX, '<<': LEFTSHIFT, '>>': RIGHTSHIFT, '**': DOUBLESTAR, '+=': PLUSEQUAL, '-=': MINEQUAL, '*=': STAREQUAL, '/=': SLASHEQUAL, '%=': PERCENTEQUAL, '&=': AMPEREQUAL, '|=': VBAREQUAL, '^=': CIRCUMFLEXEQUAL, '<<=': LEFTSHIFTEQUAL, '>>=': RIGHTSHIFTEQUAL, '**=': DOUBLESTAREQUAL, '//': DOUBLESLASH, '//=': DOUBLESLASHEQUAL, '@': AT}

class TokenInfo(collections.namedtuple('TokenInfo', 'type string start end line')):
    __qualname__ = 'TokenInfo'

    def __repr__(self):
        annotated_type = '%d (%s)' % (self.type, tok_name[self.type])
        return 'TokenInfo(type=%s, string=%r, start=%r, end=%r, line=%r)' % self._replace(type=annotated_type)

    @property
    def exact_type(self):
        if self.type == OP and self.string in EXACT_TOKEN_TYPES:
            return EXACT_TOKEN_TYPES[self.string]
        return self.type

def group(*choices):
    return '(' + '|'.join(choices) + ')'

def any(*choices):
    return group(*choices) + '*'

def maybe(*choices):
    return group(*choices) + '?'

Whitespace = '[ \\f\\t]*'
Comment = '#[^\\r\\n]*'
Ignore = Whitespace + any('\\\\\\r?\\n' + Whitespace) + maybe(Comment)
Name = '\\w+'
Hexnumber = '0[xX][0-9a-fA-F]+'
Binnumber = '0[bB][01]+'
Octnumber = '0[oO][0-7]+'
Decnumber = '(?:0+|[1-9][0-9]*)'
Intnumber = group(Hexnumber, Binnumber, Octnumber, Decnumber)
Exponent = '[eE][-+]?[0-9]+'
Pointfloat = group('[0-9]+\\.[0-9]*', '\\.[0-9]+') + maybe(Exponent)
Expfloat = '[0-9]+' + Exponent
Floatnumber = group(Pointfloat, Expfloat)
Imagnumber = group('[0-9]+[jJ]', Floatnumber + '[jJ]')
Number = group(Imagnumber, Floatnumber, Intnumber)
StringPrefix = '(?:[bB][rR]?|[rR][bB]?|[uU])?'
Single = "[^'\\\\]*(?:\\\\.[^'\\\\]*)*'"
Double = '[^"\\\\]*(?:\\\\.[^"\\\\]*)*"'
Single3 = "[^'\\\\]*(?:(?:\\\\.|'(?!''))[^'\\\\]*)*'''"
Double3 = '[^"\\\\]*(?:(?:\\\\.|"(?!""))[^"\\\\]*)*"""'
Triple = group(StringPrefix + "'''", StringPrefix + '"""')
String = group(StringPrefix + "'[^\\n'\\\\]*(?:\\\\.[^\\n'\\\\]*)*'", StringPrefix + '"[^\\n"\\\\]*(?:\\\\.[^\\n"\\\\]*)*"')
Operator = group('\\*\\*=?', '>>=?', '<<=?', '!=', '//=?', '->', '[+\\-*/%&|^=<>]=?', '~')
Bracket = '[][(){}]'
Special = group('\\r?\\n', '\\.\\.\\.', '[:;.,@]')
Funny = group(Operator, Bracket, Special)
PlainToken = group(Number, Funny, String, Name)
Token = Ignore + PlainToken
ContStr = group(StringPrefix + "'[^\\n'\\\\]*(?:\\\\.[^\\n'\\\\]*)*" + group("'", '\\\\\\r?\\n'), StringPrefix + '"[^\\n"\\\\]*(?:\\\\.[^\\n"\\\\]*)*' + group('"', '\\\\\\r?\\n'))
PseudoExtras = group('\\\\\\r?\\n|\\Z', Comment, Triple)
PseudoToken = Whitespace + group(PseudoExtras, Number, Funny, ContStr, Name)

def _compile(expr):
    return re.compile(expr, re.UNICODE)

endpats = {"'": Single, '"': Double, "'''": Single3, '"""': Double3, "r'''": Single3, 'r"""': Double3, "b'''": Single3, 'b"""': Double3, "R'''": Single3, 'R"""': Double3, "B'''": Single3, 'B"""': Double3, "br'''": Single3, 'br"""': Double3, "bR'''": Single3, 'bR"""': Double3, "Br'''": Single3, 'Br"""': Double3, "BR'''": Single3, 'BR"""': Double3, "rb'''": Single3, 'rb"""': Double3, "Rb'''": Single3, 'Rb"""': Double3, "rB'''": Single3, 'rB"""': Double3, "RB'''": Single3, 'RB"""': Double3, "u'''": Single3, 'u"""': Double3, "R'''": Single3, 'R"""': Double3, "U'''": Single3, 'U"""': Double3, 'r': None, 'R': None, 'b': None, 'B': None, 'u': None, 'U': None}
triple_quoted = {}
for t in ("'''", '"""', "r'''", 'r"""', "R'''", 'R"""', "b'''", 'b"""', "B'''", 'B"""', "br'''", 'br"""', "Br'''", 'Br"""', "bR'''", 'bR"""', "BR'''", 'BR"""', "rb'''", 'rb"""', "rB'''", 'rB"""', "Rb'''", 'Rb"""', "RB'''", 'RB"""', "u'''", 'u"""', "U'''", 'U"""'):
    triple_quoted[t] = t
single_quoted = {}
for t in ("'", '"', "r'", 'r"', "R'", 'R"', "b'", 'b"', "B'", 'B"', "br'", 'br"', "Br'", 'Br"', "bR'", 'bR"', "BR'", 'BR"', "rb'", 'rb"', "rB'", 'rB"', "Rb'", 'Rb"', "RB'", 'RB"', "u'", 'u"', "U'", 'U"'):
    single_quoted[t] = t
tabsize = 8

class TokenError(Exception):
    __qualname__ = 'TokenError'

class StopTokenizing(Exception):
    __qualname__ = 'StopTokenizing'

class Untokenizer:
    __qualname__ = 'Untokenizer'

    def __init__(self):
        self.tokens = []
        self.prev_row = 1
        self.prev_col = 0
        self.encoding = None

    def add_whitespace(self, start):
        (row, col) = start
        if row < self.prev_row or row == self.prev_row and col < self.prev_col:
            raise ValueError('start ({},{}) precedes previous end ({},{})'.format(row, col, self.prev_row, self.prev_col))
        row_offset = row - self.prev_row
        if row_offset:
            self.tokens.append('\\\n'*row_offset)
            self.prev_col = 0
        col_offset = col - self.prev_col
        if col_offset:
            self.tokens.append(' '*col_offset)

    def untokenize(self, iterable):
        it = iter(iterable)
        for t in it:
            if len(t) == 2:
                self.compat(t, it)
                break
            (tok_type, token, start, end, line) = t
            if tok_type == ENCODING:
                self.encoding = token
            if tok_type == ENDMARKER:
                break
            self.add_whitespace(start)
            self.tokens.append(token)
            (self.prev_row, self.prev_col) = end
            while tok_type in (NEWLINE, NL):
                self.prev_col = 0
        return ''.join(self.tokens)

    def compat(self, token, iterable):
        indents = []
        toks_append = self.tokens.append
        startline = token[0] in (NEWLINE, NL)
        prevstring = False
        for tok in chain([token], iterable):
            (toknum, tokval) = tok[:2]
            if toknum == ENCODING:
                self.encoding = tokval
            if toknum in (NAME, NUMBER):
                tokval += ' '
            if toknum == STRING:
                if prevstring:
                    tokval = ' ' + tokval
                prevstring = True
            else:
                prevstring = False
            if toknum == INDENT:
                indents.append(tokval)
            elif toknum == DEDENT:
                indents.pop()
            elif toknum in (NEWLINE, NL):
                startline = True
            elif startline and indents:
                toks_append(indents[-1])
                startline = False
            toks_append(tokval)

def untokenize(iterable):
    ut = Untokenizer()
    out = ut.untokenize(iterable)
    if ut.encoding is not None:
        out = out.encode(ut.encoding)
    return out

def _get_normal_name(orig_enc):
    enc = orig_enc[:12].lower().replace('_', '-')
    if enc == 'utf-8' or enc.startswith('utf-8-'):
        return 'utf-8'
    if enc in ('latin-1', 'iso-8859-1', 'iso-latin-1') or enc.startswith(('latin-1-', 'iso-8859-1-', 'iso-latin-1-')):
        return 'iso-8859-1'
    return orig_enc

def detect_encoding(readline):
    try:
        filename = readline.__self__.name
    except AttributeError:
        filename = None
    bom_found = False
    encoding = None
    default = 'utf-8'

    def read_or_stop():
        try:
            return readline()
        except StopIteration:
            return b''

    def find_cookie(line):
        try:
            line_string = line.decode('utf-8')
        except UnicodeDecodeError:
            msg = 'invalid or missing encoding declaration'
            if filename is not None:
                msg = '{} for {!r}'.format(msg, filename)
            raise SyntaxError(msg)
        match = cookie_re.match(line_string)
        if not match:
            return
        encoding = _get_normal_name(match.group(1))
        try:
            codec = lookup(encoding)
        except LookupError:
            if filename is None:
                msg = 'unknown encoding: ' + encoding
            else:
                msg = 'unknown encoding for {!r}: {}'.format(filename, encoding)
            raise SyntaxError(msg)
        if bom_found:
            if encoding != 'utf-8':
                if filename is None:
                    msg = 'encoding problem: utf-8'
                else:
                    msg = 'encoding problem for {!r}: utf-8'.format(filename)
                raise SyntaxError(msg)
            encoding += '-sig'
        return encoding

    first = read_or_stop()
    if first.startswith(BOM_UTF8):
        bom_found = True
        first = first[3:]
        default = 'utf-8-sig'
    if not first:
        return (default, [])
    encoding = find_cookie(first)
    if encoding:
        return (encoding, [first])
    if not blank_re.match(first):
        return (default, [first])
    second = read_or_stop()
    if not second:
        return (default, [first])
    encoding = find_cookie(second)
    if encoding:
        return (encoding, [first, second])
    return (default, [first, second])

def open(filename):
    buffer = builtins.open(filename, 'rb')
    (encoding, lines) = detect_encoding(buffer.readline)
    buffer.seek(0)
    text = TextIOWrapper(buffer, encoding, line_buffering=True)
    text.mode = 'r'
    return text

def tokenize(readline):
    from itertools import chain, repeat
    (encoding, consumed) = detect_encoding(readline)
    rl_gen = iter(readline, b'')
    empty = repeat(b'')
    return _tokenize(chain(consumed, rl_gen, empty).__next__, encoding)

def _tokenize(readline, encoding):
    lnum = parenlev = continued = 0
    numchars = '0123456789'
    (contstr, needcont) = ('', 0)
    contline = None
    indents = [0]
    if encoding == 'utf-8-sig':
        encoding = 'utf-8'
    yield TokenInfo(ENCODING, encoding, (0, 0), (0, 0), '')
    while True:
        try:
            line = readline()
        except StopIteration:
            line = b''
        if encoding is not None:
            line = line.decode(encoding)
        lnum += 1
        (pos, max) = (0, len(line))
        if contstr:
            if not line:
                raise TokenError('EOF in multi-line string', strstart)
            endmatch = endprog.match(line)
            if endmatch:
                pos = end = endmatch.end(0)
                yield TokenInfo(STRING, contstr + line[:end], strstart, (lnum, end), contline + line)
                (contstr, needcont) = ('', 0)
                contline = None
            elif needcont and line[-2:] != '\\\n' and line[-3:] != '\\\r\n':
                yield TokenInfo(ERRORTOKEN, contstr + line, strstart, (lnum, len(line)), contline)
                contstr = ''
                contline = None
                continue
            else:
                contstr = contstr + line
                contline = contline + line
                continue
        elif parenlev == 0 and not continued:
            if not line:
                break
            column = 0
            while pos < max:
                if line[pos] == ' ':
                    column += 1
                elif line[pos] == '\t':
                    column = (column//tabsize + 1)*tabsize
                elif line[pos] == '\x0c':
                    column = 0
                else:
                    break
                pos += 1
            if pos == max:
                break
            if line[pos] in '#\r\n':
                if line[pos] == '#':
                    comment_token = line[pos:].rstrip('\r\n')
                    nl_pos = pos + len(comment_token)
                    yield TokenInfo(COMMENT, comment_token, (lnum, pos), (lnum, pos + len(comment_token)), line)
                    yield TokenInfo(NL, line[nl_pos:], (lnum, nl_pos), (lnum, len(line)), line)
                else:
                    yield TokenInfo((NL, COMMENT)[line[pos] == '#'], line[pos:], (lnum, pos), (lnum, len(line)), line)
                    continue
                    if column > indents[-1]:
                        indents.append(column)
                        yield TokenInfo(INDENT, line[:pos], (lnum, 0), (lnum, pos), line)
                    if column not in indents:
                        raise IndentationError('unindent does not match any outer indentation level', ('<tokenize>', lnum, pos, line))
                    indents = indents[:-1]
                    yield TokenInfo(DEDENT, '', (lnum, pos), (lnum, pos), line)
                    continue
                    while pos < max:
                        pseudomatch = _compile(PseudoToken).match(line, pos)
                        if pseudomatch:
                            (start, end) = pseudomatch.span(1)
                            (spos, epos) = ((lnum, start), (lnum, end))
                            pos = end
                            if start == end:
                                continue
                            (token, initial) = (line[start:end], line[start])
                            if initial in numchars or initial == '.' and token != '.' and token != '...':
                                yield TokenInfo(NUMBER, token, spos, epos, line)
                            elif initial in '\r\n':
                                yield TokenInfo(NL if parenlev > 0 else NEWLINE, token, spos, epos, line)
                            elif initial == '#':
                                yield TokenInfo(COMMENT, token, spos, epos, line)
                            elif token in triple_quoted:
                                endprog = _compile(endpats[token])
                                endmatch = endprog.match(line, pos)
                                if endmatch:
                                    pos = endmatch.end(0)
                                    token = line[start:pos]
                                    yield TokenInfo(STRING, token, spos, (lnum, pos), line)
                                else:
                                    strstart = (lnum, start)
                                    contstr = line[start:]
                                    contline = line
                                    break
                                    if initial in single_quoted or token[:2] in single_quoted or token[:3] in single_quoted:
                                        if token[-1] == '\n':
                                            strstart = (lnum, start)
                                            endprog = _compile(endpats[initial] or (endpats[token[1]] or endpats[token[2]]))
                                            (contstr, needcont) = (line[start:], 1)
                                            contline = line
                                            break
                                        else:
                                            yield TokenInfo(STRING, token, spos, epos, line)
                                            if initial.isidentifier():
                                                yield TokenInfo(NAME, token, spos, epos, line)
                                            elif initial == '\\':
                                                continued = 1
                                            else:
                                                if initial in '([{':
                                                    parenlev += 1
                                                elif initial in ')]}':
                                                    parenlev -= 1
                                                yield TokenInfo(OP, token, spos, epos, line)
                                                continue
                                                yield TokenInfo(ERRORTOKEN, line[pos], (lnum, pos), (lnum, pos + 1), line)
                                                pos += 1
                                    elif initial.isidentifier():
                                        yield TokenInfo(NAME, token, spos, epos, line)
                                    elif initial == '\\':
                                        continued = 1
                                    else:
                                        if initial in '([{':
                                            parenlev += 1
                                        elif initial in ')]}':
                                            parenlev -= 1
                                        yield TokenInfo(OP, token, spos, epos, line)
                                        continue
                                        yield TokenInfo(ERRORTOKEN, line[pos], (lnum, pos), (lnum, pos + 1), line)
                                        pos += 1
                            elif initial in single_quoted or token[:2] in single_quoted or token[:3] in single_quoted:
                                if token[-1] == '\n':
                                    strstart = (lnum, start)
                                    endprog = _compile(endpats[initial] or (endpats[token[1]] or endpats[token[2]]))
                                    (contstr, needcont) = (line[start:], 1)
                                    contline = line
                                    break
                                else:
                                    yield TokenInfo(STRING, token, spos, epos, line)
                                    if initial.isidentifier():
                                        yield TokenInfo(NAME, token, spos, epos, line)
                                    elif initial == '\\':
                                        continued = 1
                                    else:
                                        if initial in '([{':
                                            parenlev += 1
                                        elif initial in ')]}':
                                            parenlev -= 1
                                        yield TokenInfo(OP, token, spos, epos, line)
                                        continue
                                        yield TokenInfo(ERRORTOKEN, line[pos], (lnum, pos), (lnum, pos + 1), line)
                                        pos += 1
                            elif initial.isidentifier():
                                yield TokenInfo(NAME, token, spos, epos, line)
                            elif initial == '\\':
                                continued = 1
                            else:
                                if initial in '([{':
                                    parenlev += 1
                                elif initial in ')]}':
                                    parenlev -= 1
                                yield TokenInfo(OP, token, spos, epos, line)
                                continue
                                yield TokenInfo(ERRORTOKEN, line[pos], (lnum, pos), (lnum, pos + 1), line)
                                pos += 1
                        else:
                            yield TokenInfo(ERRORTOKEN, line[pos], (lnum, pos), (lnum, pos + 1), line)
                            pos += 1
            if column > indents[-1]:
                indents.append(column)
                yield TokenInfo(INDENT, line[:pos], (lnum, 0), (lnum, pos), line)
            if column not in indents:
                raise IndentationError('unindent does not match any outer indentation level', ('<tokenize>', lnum, pos, line))
            indents = indents[:-1]
            yield TokenInfo(DEDENT, '', (lnum, pos), (lnum, pos), line)
            continue
        else:
            if not line:
                raise TokenError('EOF in multi-line statement', (lnum, 0))
            continued = 0
        while pos < max:
            pseudomatch = _compile(PseudoToken).match(line, pos)
            if pseudomatch:
                (start, end) = pseudomatch.span(1)
                (spos, epos) = ((lnum, start), (lnum, end))
                pos = end
                if start == end:
                    continue
                (token, initial) = (line[start:end], line[start])
                if initial in numchars or initial == '.' and token != '.' and token != '...':
                    yield TokenInfo(NUMBER, token, spos, epos, line)
                elif initial in '\r\n':
                    yield TokenInfo(NL if parenlev > 0 else NEWLINE, token, spos, epos, line)
                elif initial == '#':
                    yield TokenInfo(COMMENT, token, spos, epos, line)
                elif token in triple_quoted:
                    endprog = _compile(endpats[token])
                    endmatch = endprog.match(line, pos)
                    if endmatch:
                        pos = endmatch.end(0)
                        token = line[start:pos]
                        yield TokenInfo(STRING, token, spos, (lnum, pos), line)
                    else:
                        strstart = (lnum, start)
                        contstr = line[start:]
                        contline = line
                        break
                        if initial in single_quoted or token[:2] in single_quoted or token[:3] in single_quoted:
                            if token[-1] == '\n':
                                strstart = (lnum, start)
                                endprog = _compile(endpats[initial] or (endpats[token[1]] or endpats[token[2]]))
                                (contstr, needcont) = (line[start:], 1)
                                contline = line
                                break
                            else:
                                yield TokenInfo(STRING, token, spos, epos, line)
                                if initial.isidentifier():
                                    yield TokenInfo(NAME, token, spos, epos, line)
                                elif initial == '\\':
                                    continued = 1
                                else:
                                    if initial in '([{':
                                        parenlev += 1
                                    elif initial in ')]}':
                                        parenlev -= 1
                                    yield TokenInfo(OP, token, spos, epos, line)
                                    continue
                                    yield TokenInfo(ERRORTOKEN, line[pos], (lnum, pos), (lnum, pos + 1), line)
                                    pos += 1
                        elif initial.isidentifier():
                            yield TokenInfo(NAME, token, spos, epos, line)
                        elif initial == '\\':
                            continued = 1
                        else:
                            if initial in '([{':
                                parenlev += 1
                            elif initial in ')]}':
                                parenlev -= 1
                            yield TokenInfo(OP, token, spos, epos, line)
                            continue
                            yield TokenInfo(ERRORTOKEN, line[pos], (lnum, pos), (lnum, pos + 1), line)
                            pos += 1
                elif initial in single_quoted or token[:2] in single_quoted or token[:3] in single_quoted:
                    if token[-1] == '\n':
                        strstart = (lnum, start)
                        endprog = _compile(endpats[initial] or (endpats[token[1]] or endpats[token[2]]))
                        (contstr, needcont) = (line[start:], 1)
                        contline = line
                        break
                    else:
                        yield TokenInfo(STRING, token, spos, epos, line)
                        if initial.isidentifier():
                            yield TokenInfo(NAME, token, spos, epos, line)
                        elif initial == '\\':
                            continued = 1
                        else:
                            if initial in '([{':
                                parenlev += 1
                            elif initial in ')]}':
                                parenlev -= 1
                            yield TokenInfo(OP, token, spos, epos, line)
                            continue
                            yield TokenInfo(ERRORTOKEN, line[pos], (lnum, pos), (lnum, pos + 1), line)
                            pos += 1
                elif initial.isidentifier():
                    yield TokenInfo(NAME, token, spos, epos, line)
                elif initial == '\\':
                    continued = 1
                else:
                    if initial in '([{':
                        parenlev += 1
                    elif initial in ')]}':
                        parenlev -= 1
                    yield TokenInfo(OP, token, spos, epos, line)
                    continue
                    yield TokenInfo(ERRORTOKEN, line[pos], (lnum, pos), (lnum, pos + 1), line)
                    pos += 1
            else:
                yield TokenInfo(ERRORTOKEN, line[pos], (lnum, pos), (lnum, pos + 1), line)
                pos += 1
    for indent in indents[1:]:
        yield TokenInfo(DEDENT, '', (lnum, 0), (lnum, 0), '')
    yield TokenInfo(ENDMARKER, '', (lnum, 0), (lnum, 0), '')

def generate_tokens(readline):
    return _tokenize(readline, None)

def main():
    import argparse

    def perror(message):
        print(message, file=sys.stderr)

    def error(message, filename=None, location=None):
        if location:
            args = (filename,) + location + (message,)
            perror('%s:%d:%d: error: %s' % args)
        elif filename:
            perror('%s: error: %s' % (filename, message))
        else:
            perror('error: %s' % message)
        sys.exit(1)

    parser = argparse.ArgumentParser(prog='python -m tokenize')
    parser.add_argument(dest='filename', nargs='?', metavar='filename.py', help='the file to tokenize; defaults to stdin')
    parser.add_argument('-e', '--exact', dest='exact', action='store_true', help='display token names using the exact type')
    args = parser.parse_args()
    try:
        if args.filename:
            filename = args.filename
            with builtins.open(filename, 'rb') as f:
                tokens = list(tokenize(f.readline))
        else:
            filename = '<stdin>'
            tokens = _tokenize(sys.stdin.readline, None)
        for token in tokens:
            token_type = token.type
            if args.exact:
                token_type = token.exact_type
            token_range = '%d,%d-%d,%d:' % (token.start + token.end)
            print('%-20s%-15s%-15r' % (token_range, tok_name[token_type], token.string))
    except IndentationError as err:
        (line, column) = err.args[1][1:3]
        error(err.args[0], filename, (line, column))
    except TokenError as err:
        (line, column) = err.args[1]
        error(err.args[0], filename, (line, column))
    except SyntaxError as err:
        error(err, filename)
    except IOError as err:
        error(err)
    except KeyboardInterrupt:
        print('interrupted\n')
    except Exception as err:
        perror('unexpected error: %s' % err)
        raise

if __name__ == '__main__':
    main()
