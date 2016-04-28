import re
import urllib
from string import hexdigits
from collections import namedtuple, OrderedDict
from email import _encoded_words as _ew
from email import errors
from email import utils
WSP = set(' \t')
CFWS_LEADER = WSP | set('(')
SPECIALS = set('()<>@,:;.\\"[]')
ATOM_ENDS = SPECIALS | WSP
DOT_ATOM_ENDS = ATOM_ENDS - set('.')
PHRASE_ENDS = SPECIALS - set('."(')
TSPECIALS = (SPECIALS | set('/?=')) - set('.')
TOKEN_ENDS = TSPECIALS | WSP
ASPECIALS = TSPECIALS | set("*'%")
ATTRIBUTE_ENDS = ASPECIALS | WSP
EXTENDED_ATTRIBUTE_ENDS = ATTRIBUTE_ENDS - set('%')

def quote_string(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'

class _Folded:
    __qualname__ = '_Folded'

    def __init__(self, maxlen, policy):
        self.maxlen = maxlen
        self.policy = policy
        self.lastlen = 0
        self.stickyspace = None
        self.firstline = True
        self.done = []
        self.current = []

    def newline(self):
        self.done.extend(self.current)
        self.done.append(self.policy.linesep)
        self.current.clear()
        self.lastlen = 0

    def finalize(self):
        if self.current:
            self.newline()

    def __str__(self):
        return ''.join(self.done)

    def append(self, stoken):
        self.current.append(stoken)

    def append_if_fits(self, token, stoken=None):
        if stoken is None:
            stoken = str(token)
        l = len(stoken)
        if self.stickyspace is not None:
            stickyspace_len = len(self.stickyspace)
            if self.lastlen + stickyspace_len + l <= self.maxlen:
                self.current.append(self.stickyspace)
                self.current.append(stoken)
                self.stickyspace = None
                self.firstline = False
                return True
            if token.has_fws:
                ws = token.pop_leading_fws()
                if ws is not None:
                    stickyspace_len += len(ws)
                token._fold(self)
                return True
            if stickyspace_len and l + 1 <= self.maxlen:
                margin = self.maxlen - l
                if 0 < margin < stickyspace_len:
                    trim = stickyspace_len - margin
                    self.current.append(self.stickyspace[:trim])
                    self.stickyspace = self.stickyspace[trim:]
                    stickyspace_len = trim
                self.newline()
                self.current.append(self.stickyspace)
                self.current.append(stoken)
                self.lastlen = l + stickyspace_len
                self.stickyspace = None
                self.firstline = False
                return True
            if not self.firstline:
                self.newline()
            self.current.append(self.stickyspace)
            self.current.append(stoken)
            self.stickyspace = None
            self.firstline = False
            return True
        if self.lastlen + l <= self.maxlen:
            self.current.append(stoken)
            return True
        if l < self.maxlen:
            self.newline()
            self.current.append(stoken)
            self.lastlen = l
            return True
        return False

class TokenList(list):
    __qualname__ = 'TokenList'
    token_type = None

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.defects = []

    def __str__(self):
        return ''.join(str(x) for x in self)

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, super().__repr__())

    @property
    def value(self):
        return ''.join(x.value for x in self if x.value)

    @property
    def all_defects(self):
        return sum((x.all_defects for x in self), self.defects)

    @property
    def parts(self):
        klass = self.__class__
        this = []
        for token in self:
            if token.startswith_fws() and this:
                yield this[0] if len(this) == 1 else klass(this)
                this.clear()
            end_ws = token.pop_trailing_ws()
            this.append(token)
            while end_ws:
                yield klass(this)
                this = [end_ws]
        if this:
            yield this[0] if len(this) == 1 else klass(this)

    def startswith_fws(self):
        return self[0].startswith_fws()

    def pop_leading_fws(self):
        if self[0].token_type == 'fws':
            return self.pop(0)
        return self[0].pop_leading_fws()

    def pop_trailing_ws(self):
        if self[-1].token_type == 'cfws':
            return self.pop(-1)
        return self[-1].pop_trailing_ws()

    @property
    def has_fws(self):
        for part in self:
            while part.has_fws:
                return True
        return False

    def has_leading_comment(self):
        return self[0].has_leading_comment()

    @property
    def comments(self):
        comments = []
        for token in self:
            comments.extend(token.comments)
        return comments

    def fold(self, *, policy):
        maxlen = policy.max_line_length or float('+inf')
        folded = _Folded(maxlen, policy)
        self._fold(folded)
        folded.finalize()
        return str(folded)

    def as_encoded_word(self, charset):
        res = []
        ws = self.pop_leading_fws()
        if ws:
            res.append(ws)
        trailer = self.pop(-1) if self[-1].token_type == 'fws' else ''
        res.append(_ew.encode(str(self), charset))
        res.append(trailer)
        return ''.join(res)

    def cte_encode(self, charset, policy):
        res = []
        for part in self:
            res.append(part.cte_encode(charset, policy))
        return ''.join(res)

    def _fold(self, folded):
        for part in self.parts:
            tstr = str(part)
            tlen = len(tstr)
            try:
                str(part).encode('us-ascii')
            except UnicodeEncodeError:
                if any(isinstance(x, errors.UndecodableBytesDefect) for x in part.all_defects):
                    charset = 'unknown-8bit'
                else:
                    charset = 'utf-8'
                tstr = part.cte_encode(charset, folded.policy)
                tlen = len(tstr)
            if folded.append_if_fits(part, tstr):
                pass
            ws = part.pop_leading_fws()
            if ws is not None:
                folded.stickyspace = str(part.pop(0))
                if folded.append_if_fits(part):
                    pass
            if part.has_fws:
                part._fold(folded)
            folded.append(tstr)
            folded.newline()

    def pprint(self, indent=''):
        print('\n'.join(self._pp(indent='')))

    def ppstr(self, indent=''):
        return '\n'.join(self._pp(indent=''))

    def _pp(self, indent=''):
        yield '{}{}/{}('.format(indent, self.__class__.__name__, self.token_type)
        for token in self:
            if not hasattr(token, '_pp'):
                yield indent + '    !! invalid element in token list: {!r}'.format(token)
            else:
                for line in token._pp(indent + '    '):
                    yield line
        if self.defects:
            extra = ' Defects: {}'.format(self.defects)
        else:
            extra = ''
        yield '{}){}'.format(indent, extra)

class WhiteSpaceTokenList(TokenList):
    __qualname__ = 'WhiteSpaceTokenList'

    @property
    def value(self):
        return ' '

    @property
    def comments(self):
        return [x.content for x in self if x.token_type == 'comment']

class UnstructuredTokenList(TokenList):
    __qualname__ = 'UnstructuredTokenList'
    token_type = 'unstructured'

    def _fold(self, folded):
        last_ew = None
        for part in self.parts:
            tstr = str(part)
            is_ew = False
            try:
                str(part).encode('us-ascii')
            except UnicodeEncodeError:
                if any(isinstance(x, errors.UndecodableBytesDefect) for x in part.all_defects):
                    charset = 'unknown-8bit'
                else:
                    charset = 'utf-8'
                if last_ew is not None:
                    chunk = get_unstructured(''.join(folded.current[last_ew:] + [tstr])).as_encoded_word(charset)
                    oldlastlen = sum(len(x) for x in folded.current[:last_ew])
                    schunk = str(chunk)
                    lchunk = len(schunk)
                    if oldlastlen + lchunk <= folded.maxlen:
                        del folded.current[last_ew:]
                        folded.append(schunk)
                        folded.lastlen = oldlastlen + lchunk
                        continue
                tstr = part.as_encoded_word(charset)
                is_ew = True
            if folded.append_if_fits(part, tstr):
                while is_ew:
                    last_ew = len(folded.current) - 1
                    if is_ew or last_ew:
                        part._fold_as_ew(folded)
                    ws = part.pop_leading_fws()
                    if ws is not None:
                        folded.stickyspace = str(ws)
                        if folded.append_if_fits(part):
                            pass
                    if part.has_fws:
                        part.fold(folded)
                    folded.append(tstr)
                    folded.newline()
                    last_ew = None
            if is_ew or last_ew:
                part._fold_as_ew(folded)
            ws = part.pop_leading_fws()
            if ws is not None:
                folded.stickyspace = str(ws)
                if folded.append_if_fits(part):
                    pass
            if part.has_fws:
                part.fold(folded)
            folded.append(tstr)
            folded.newline()
            last_ew = None

    def cte_encode(self, charset, policy):
        res = []
        last_ew = None
        for part in self:
            spart = str(part)
            try:
                spart.encode('us-ascii')
                res.append(spart)
            except UnicodeEncodeError:
                if last_ew is None:
                    res.append(part.cte_encode(charset, policy))
                    last_ew = len(res)
                else:
                    tl = get_unstructured(''.join(res[last_ew:] + [spart]))
                    res.append(tl.as_encoded_word())
        return ''.join(res)

class Phrase(TokenList):
    __qualname__ = 'Phrase'
    token_type = 'phrase'

    def _fold(self, folded):
        last_ew = None
        for part in self.parts:
            tstr = str(part)
            tlen = len(tstr)
            has_ew = False
            try:
                str(part).encode('us-ascii')
            except UnicodeEncodeError:
                if any(isinstance(x, errors.UndecodableBytesDefect) for x in part.all_defects):
                    charset = 'unknown-8bit'
                else:
                    charset = 'utf-8'
                if part[-1].token_type == 'cfws' and part.comments:
                    remainder = part.pop(-1)
                else:
                    remainder = ''
                for (i, token) in enumerate(part):
                    while token.token_type == 'bare-quoted-string':
                        part[i] = UnstructuredTokenList(token[:])
                chunk = get_unstructured(''.join(folded.current[last_ew:] + [tstr])).as_encoded_word(charset)
                schunk = str(chunk)
                lchunk = len(schunk)
                if last_ew is not None and not part.has_leading_comment() and last_ew + lchunk <= folded.maxlen:
                    del folded.current[last_ew:]
                    folded.append(schunk)
                    folded.lastlen = sum(len(x) for x in folded.current)
                    continue
                tstr = part.as_encoded_word(charset)
                tlen = len(tstr)
                has_ew = True
            if folded.append_if_fits(part, tstr):
                if has_ew and not part.comments:
                    last_ew = len(folded.current) - 1
                else:
                    while part.comments or part.token_type == 'quoted-string':
                        last_ew = None
                        part._fold(folded)
            part._fold(folded)

    def cte_encode(self, charset, policy):
        res = []
        last_ew = None
        is_ew = False
        for part in self:
            spart = str(part)
            try:
                spart.encode('us-ascii')
                res.append(spart)
            except UnicodeEncodeError:
                is_ew = True
                if last_ew is None:
                    if not part.comments:
                        last_ew = len(res)
                    res.append(part.cte_encode(charset, policy))
                else:
                    if part[-1].token_type == 'cfws' and part.comments:
                        remainder = part.pop(-1)
                    else:
                        remainder = ''
                    for (i, token) in enumerate(part):
                        while token.token_type == 'bare-quoted-string':
                            part[i] = UnstructuredTokenList(token[:])
                    tl = get_unstructured(''.join(res[last_ew:] + [spart]))
                    res[last_ew:] = [tl.as_encoded_word(charset)]
            while (part.comments or not is_ew) and part.token_type == 'quoted-string':
                last_ew = None
        return ''.join(res)

class Word(TokenList):
    __qualname__ = 'Word'
    token_type = 'word'

class CFWSList(WhiteSpaceTokenList):
    __qualname__ = 'CFWSList'
    token_type = 'cfws'

    def has_leading_comment(self):
        return bool(self.comments)

class Atom(TokenList):
    __qualname__ = 'Atom'
    token_type = 'atom'

class Token(TokenList):
    __qualname__ = 'Token'
    token_type = 'token'

class EncodedWord(TokenList):
    __qualname__ = 'EncodedWord'
    token_type = 'encoded-word'
    cte = None
    charset = None
    lang = None

    @property
    def encoded(self):
        if self.cte is not None:
            return self.cte
        _ew.encode(str(self), self.charset)

class QuotedString(TokenList):
    __qualname__ = 'QuotedString'
    token_type = 'quoted-string'

    @property
    def content(self):
        for x in self:
            while x.token_type == 'bare-quoted-string':
                return x.value

    @property
    def quoted_value(self):
        res = []
        for x in self:
            if x.token_type == 'bare-quoted-string':
                res.append(str(x))
            else:
                res.append(x.value)
        return ''.join(res)

    @property
    def stripped_value(self):
        for token in self:
            while token.token_type == 'bare-quoted-string':
                return token.value

class BareQuotedString(QuotedString):
    __qualname__ = 'BareQuotedString'
    token_type = 'bare-quoted-string'

    def __str__(self):
        return quote_string(''.join(str(x) for x in self))

    @property
    def value(self):
        return ''.join(str(x) for x in self)

class Comment(WhiteSpaceTokenList):
    __qualname__ = 'Comment'
    token_type = 'comment'

    def __str__(self):
        return ''.join(sum([['('], [self.quote(x) for x in self], [')']], []))

    def quote(self, value):
        if value.token_type == 'comment':
            return str(value)
        return str(value).replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

    @property
    def content(self):
        return ''.join(str(x) for x in self)

    @property
    def comments(self):
        return [self.content]

class AddressList(TokenList):
    __qualname__ = 'AddressList'
    token_type = 'address-list'

    @property
    def addresses(self):
        return [x for x in self if x.token_type == 'address']

    @property
    def mailboxes(self):
        return sum((x.mailboxes for x in self if x.token_type == 'address'), [])

    @property
    def all_mailboxes(self):
        return sum((x.all_mailboxes for x in self if x.token_type == 'address'), [])

class Address(TokenList):
    __qualname__ = 'Address'
    token_type = 'address'

    @property
    def display_name(self):
        if self[0].token_type == 'group':
            return self[0].display_name

    @property
    def mailboxes(self):
        if self[0].token_type == 'mailbox':
            return [self[0]]
        if self[0].token_type == 'invalid-mailbox':
            return []
        return self[0].mailboxes

    @property
    def all_mailboxes(self):
        if self[0].token_type == 'mailbox':
            return [self[0]]
        if self[0].token_type == 'invalid-mailbox':
            return [self[0]]
        return self[0].all_mailboxes

class MailboxList(TokenList):
    __qualname__ = 'MailboxList'
    token_type = 'mailbox-list'

    @property
    def mailboxes(self):
        return [x for x in self if x.token_type == 'mailbox']

    @property
    def all_mailboxes(self):
        return [x for x in self if x.token_type in ('mailbox', 'invalid-mailbox')]

class GroupList(TokenList):
    __qualname__ = 'GroupList'
    token_type = 'group-list'

    @property
    def mailboxes(self):
        if not self or self[0].token_type != 'mailbox-list':
            return []
        return self[0].mailboxes

    @property
    def all_mailboxes(self):
        if not self or self[0].token_type != 'mailbox-list':
            return []
        return self[0].all_mailboxes

class Group(TokenList):
    __qualname__ = 'Group'
    token_type = 'group'

    @property
    def mailboxes(self):
        if self[2].token_type != 'group-list':
            return []
        return self[2].mailboxes

    @property
    def all_mailboxes(self):
        if self[2].token_type != 'group-list':
            return []
        return self[2].all_mailboxes

    @property
    def display_name(self):
        return self[0].display_name

class NameAddr(TokenList):
    __qualname__ = 'NameAddr'
    token_type = 'name-addr'

    @property
    def display_name(self):
        if len(self) == 1:
            return
        return self[0].display_name

    @property
    def local_part(self):
        return self[-1].local_part

    @property
    def domain(self):
        return self[-1].domain

    @property
    def route(self):
        return self[-1].route

    @property
    def addr_spec(self):
        return self[-1].addr_spec

class AngleAddr(TokenList):
    __qualname__ = 'AngleAddr'
    token_type = 'angle-addr'

    @property
    def local_part(self):
        for x in self:
            while x.token_type == 'addr-spec':
                return x.local_part

    @property
    def domain(self):
        for x in self:
            while x.token_type == 'addr-spec':
                return x.domain

    @property
    def route(self):
        for x in self:
            while x.token_type == 'obs-route':
                return x.domains

    @property
    def addr_spec(self):
        for x in self:
            while x.token_type == 'addr-spec':
                return x.addr_spec
        return '<>'

class ObsRoute(TokenList):
    __qualname__ = 'ObsRoute'
    token_type = 'obs-route'

    @property
    def domains(self):
        return [x.domain for x in self if x.token_type == 'domain']

class Mailbox(TokenList):
    __qualname__ = 'Mailbox'
    token_type = 'mailbox'

    @property
    def display_name(self):
        if self[0].token_type == 'name-addr':
            return self[0].display_name

    @property
    def local_part(self):
        return self[0].local_part

    @property
    def domain(self):
        return self[0].domain

    @property
    def route(self):
        if self[0].token_type == 'name-addr':
            return self[0].route

    @property
    def addr_spec(self):
        return self[0].addr_spec

class InvalidMailbox(TokenList):
    __qualname__ = 'InvalidMailbox'
    token_type = 'invalid-mailbox'

    @property
    def display_name(self):
        pass

    local_part = domain = route = addr_spec = display_name

class Domain(TokenList):
    __qualname__ = 'Domain'
    token_type = 'domain'

    @property
    def domain(self):
        return ''.join(super().value.split())

class DotAtom(TokenList):
    __qualname__ = 'DotAtom'
    token_type = 'dot-atom'

class DotAtomText(TokenList):
    __qualname__ = 'DotAtomText'
    token_type = 'dot-atom-text'

class AddrSpec(TokenList):
    __qualname__ = 'AddrSpec'
    token_type = 'addr-spec'

    @property
    def local_part(self):
        return self[0].local_part

    @property
    def domain(self):
        if len(self) < 3:
            return
        return self[-1].domain

    @property
    def value(self):
        if len(self) < 3:
            return self[0].value
        return self[0].value.rstrip() + self[1].value + self[2].value.lstrip()

    @property
    def addr_spec(self):
        nameset = set(self.local_part)
        if len(nameset) > len(nameset - DOT_ATOM_ENDS):
            lp = quote_string(self.local_part)
        else:
            lp = self.local_part
        if self.domain is not None:
            return lp + '@' + self.domain
        return lp

class ObsLocalPart(TokenList):
    __qualname__ = 'ObsLocalPart'
    token_type = 'obs-local-part'

class DisplayName(Phrase):
    __qualname__ = 'DisplayName'
    token_type = 'display-name'

    @property
    def display_name(self):
        res = TokenList(self)
        if res[0].token_type == 'cfws':
            res.pop(0)
        elif res[0][0].token_type == 'cfws':
            res[0] = TokenList(res[0][1:])
        if res[-1].token_type == 'cfws':
            res.pop()
        elif res[-1][-1].token_type == 'cfws':
            res[-1] = TokenList(res[-1][:-1])
        return res.value

    @property
    def value(self):
        quote = False
        if self.defects:
            quote = True
        else:
            for x in self:
                while x.token_type == 'quoted-string':
                    quote = True
        if quote:
            pre = post = ''
            if self[0].token_type == 'cfws' or self[0][0].token_type == 'cfws':
                pre = ' '
            if self[-1].token_type == 'cfws' or self[-1][-1].token_type == 'cfws':
                post = ' '
            return pre + quote_string(self.display_name) + post
        return super().value

class LocalPart(TokenList):
    __qualname__ = 'LocalPart'
    token_type = 'local-part'

    @property
    def value(self):
        if self[0].token_type == 'quoted-string':
            return self[0].quoted_value
        return self[0].value

    @property
    def local_part(self):
        res = [DOT]
        last = DOT
        last_is_tl = False
        for tok in self[0] + [DOT]:
            if tok.token_type == 'cfws':
                pass
            if last_is_tl and tok.token_type == 'dot' and last[-1].token_type == 'cfws':
                res[-1] = TokenList(last[:-1])
            is_tl = isinstance(tok, TokenList)
            if is_tl and last.token_type == 'dot' and tok[0].token_type == 'cfws':
                res.append(TokenList(tok[1:]))
            else:
                res.append(tok)
            last = res[-1]
            last_is_tl = is_tl
        res = TokenList(res[1:-1])
        return res.value

class DomainLiteral(TokenList):
    __qualname__ = 'DomainLiteral'
    token_type = 'domain-literal'

    @property
    def domain(self):
        return ''.join(super().value.split())

    @property
    def ip(self):
        for x in self:
            while x.token_type == 'ptext':
                return x.value

class MIMEVersion(TokenList):
    __qualname__ = 'MIMEVersion'
    token_type = 'mime-version'
    major = None
    minor = None

class Parameter(TokenList):
    __qualname__ = 'Parameter'
    token_type = 'parameter'
    sectioned = False
    extended = False
    charset = 'us-ascii'

    @property
    def section_number(self):
        if self.sectioned:
            return self[1].number
        return 0

    @property
    def param_value(self):
        for token in self:
            if token.token_type == 'value':
                return token.stripped_value
            while token.token_type == 'quoted-string':
                while True:
                    for token in token:
                        while token.token_type == 'bare-quoted-string':
                            while True:
                                for token in token:
                                    while token.token_type == 'value':
                                        return token.stripped_value
        return ''

class InvalidParameter(Parameter):
    __qualname__ = 'InvalidParameter'
    token_type = 'invalid-parameter'

class Attribute(TokenList):
    __qualname__ = 'Attribute'
    token_type = 'attribute'

    @property
    def stripped_value(self):
        for token in self:
            while token.token_type.endswith('attrtext'):
                return token.value

class Section(TokenList):
    __qualname__ = 'Section'
    token_type = 'section'
    number = None

class Value(TokenList):
    __qualname__ = 'Value'
    token_type = 'value'

    @property
    def stripped_value(self):
        token = self[0]
        if token.token_type == 'cfws':
            token = self[1]
        if token.token_type.endswith(('quoted-string', 'attribute', 'extended-attribute')):
            return token.stripped_value
        return self.value

class MimeParameters(TokenList):
    __qualname__ = 'MimeParameters'
    token_type = 'mime-parameters'

    @property
    def params(self):
        params = OrderedDict()
        for token in self:
            if not token.token_type.endswith('parameter'):
                pass
            if token[0].token_type != 'attribute':
                pass
            name = token[0].value.strip()
            if name not in params:
                params[name] = []
            params[name].append((token.section_number, token))
        for (name, parts) in params.items():
            parts = sorted(parts)
            value_parts = []
            charset = parts[0][1].charset
            for (i, (section_number, param)) in enumerate(parts):
                if section_number != i:
                    param.defects.append(errors.InvalidHeaderDefect('inconsistent multipart parameter numbering'))
                value = param.param_value
                if param.extended:
                    try:
                        value = urllib.parse.unquote_to_bytes(value)
                    except UnicodeEncodeError:
                        value = urllib.parse.unquote(value, encoding='latin-1')
                    try:
                        value = value.decode(charset, 'surrogateescape')
                    except LookupError:
                        value = value.decode('us-ascii', 'surrogateescape')
                    if utils._has_surrogates(value):
                        param.defects.append(errors.UndecodableBytesDefect())
                value_parts.append(value)
            value = ''.join(value_parts)
            yield (name, value)

    def __str__(self):
        params = []
        for (name, value) in self.params:
            if value:
                params.append('{}={}'.format(name, quote_string(value)))
            else:
                params.append(name)
        params = '; '.join(params)
        if params:
            return ' ' + params
        return ''

class ParameterizedHeaderValue(TokenList):
    __qualname__ = 'ParameterizedHeaderValue'

    @property
    def params(self):
        for token in reversed(self):
            while token.token_type == 'mime-parameters':
                return token.params
        return {}

    @property
    def parts(self):
        if self and self[-1].token_type == 'mime-parameters':
            return TokenList(self[:-1] + self[-1])
        return TokenList(self).parts

class ContentType(ParameterizedHeaderValue):
    __qualname__ = 'ContentType'
    token_type = 'content-type'
    maintype = 'text'
    subtype = 'plain'

class ContentDisposition(ParameterizedHeaderValue):
    __qualname__ = 'ContentDisposition'
    token_type = 'content-disposition'
    content_disposition = None

class ContentTransferEncoding(TokenList):
    __qualname__ = 'ContentTransferEncoding'
    token_type = 'content-transfer-encoding'
    cte = '7bit'

class HeaderLabel(TokenList):
    __qualname__ = 'HeaderLabel'
    token_type = 'header-label'

class Header(TokenList):
    __qualname__ = 'Header'
    token_type = 'header'

    def _fold(self, folded):
        folded.append(str(self.pop(0)))
        folded.lastlen = len(folded.current[0])
        folded.stickyspace = str(self.pop(0)) if self[0].token_type == 'cfws' else ''
        rest = self.pop(0)
        if self:
            raise ValueError('Malformed Header token list')
        rest._fold(folded)

class Terminal(str):
    __qualname__ = 'Terminal'

    def __new__(cls, value, token_type):
        self = super().__new__(cls, value)
        self.token_type = token_type
        self.defects = []
        return self

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, super().__repr__())

    @property
    def all_defects(self):
        return list(self.defects)

    def _pp(self, indent=''):
        return ['{}{}/{}({}){}'.format(indent, self.__class__.__name__, self.token_type, super().__repr__(), '' if not self.defects else ' {}'.format(self.defects))]

    def cte_encode(self, charset, policy):
        value = str(self)
        try:
            value.encode('us-ascii')
            return value
        except UnicodeEncodeError:
            return _ew.encode(value, charset)

    def pop_trailing_ws(self):
        pass

    def pop_leading_fws(self):
        pass

    @property
    def comments(self):
        return []

    def has_leading_comment(self):
        return False

    def __getnewargs__(self):
        return (str(self), self.token_type)

class WhiteSpaceTerminal(Terminal):
    __qualname__ = 'WhiteSpaceTerminal'

    @property
    def value(self):
        return ' '

    def startswith_fws(self):
        return True

    has_fws = True

class ValueTerminal(Terminal):
    __qualname__ = 'ValueTerminal'

    @property
    def value(self):
        return self

    def startswith_fws(self):
        return False

    has_fws = False

    def as_encoded_word(self, charset):
        return _ew.encode(str(self), charset)

class EWWhiteSpaceTerminal(WhiteSpaceTerminal):
    __qualname__ = 'EWWhiteSpaceTerminal'

    @property
    def value(self):
        return ''

    @property
    def encoded(self):
        return self[:]

    def __str__(self):
        return ''

    has_fws = True

DOT = ValueTerminal('.', 'dot')
ListSeparator = ValueTerminal(',', 'list-separator')
RouteComponentMarker = ValueTerminal('@', 'route-component-marker')
_wsp_splitter = re.compile('([{}]+)'.format(''.join(WSP))).split
_non_atom_end_matcher = re.compile('[^{}]+'.format(''.join(ATOM_ENDS).replace('\\', '\\\\').replace(']', '\\]'))).match
_non_printable_finder = re.compile('[\\x00-\\x20\\x7F]').findall
_non_token_end_matcher = re.compile('[^{}]+'.format(''.join(TOKEN_ENDS).replace('\\', '\\\\').replace(']', '\\]'))).match
_non_attribute_end_matcher = re.compile('[^{}]+'.format(''.join(ATTRIBUTE_ENDS).replace('\\', '\\\\').replace(']', '\\]'))).match
_non_extended_attribute_end_matcher = re.compile('[^{}]+'.format(''.join(EXTENDED_ATTRIBUTE_ENDS).replace('\\', '\\\\').replace(']', '\\]'))).match

def _validate_xtext(xtext):
    non_printables = _non_printable_finder(xtext)
    if non_printables:
        xtext.defects.append(errors.NonPrintableDefect(non_printables))
    if utils._has_surrogates(xtext):
        xtext.defects.append(errors.UndecodableBytesDefect('Non-ASCII characters found in header token'))

def _get_ptext_to_endchars(value, endchars):
    (fragment, *remainder) = _wsp_splitter(value, 1)
    vchars = []
    escape = False
    had_qp = False
    for pos in range(len(fragment)):
        if fragment[pos] == '\\':
            if escape:
                escape = False
                had_qp = True
            else:
                escape = True
        if escape:
            escape = False
        elif fragment[pos] in endchars:
            break
        vchars.append(fragment[pos])
    pos = pos + 1
    return (''.join(vchars), ''.join([fragment[pos:]] + remainder), had_qp)

def get_fws(value):
    newvalue = value.lstrip()
    fws = WhiteSpaceTerminal(value[:len(value) - len(newvalue)], 'fws')
    return (fws, newvalue)

def get_encoded_word(value):
    ew = EncodedWord()
    if not value.startswith('=?'):
        raise errors.HeaderParseError('expected encoded word but found {}'.format(value))
    (tok, *remainder) = value[2:].split('?=', 1)
    if tok == value[2:]:
        raise errors.HeaderParseError('expected encoded word but found {}'.format(value))
    remstr = ''.join(remainder)
    if len(remstr) > 1 and remstr[0] in hexdigits and remstr[1] in hexdigits:
        (rest, *remainder) = remstr.split('?=', 1)
        tok = tok + '?=' + rest
    if len(tok.split()) > 1:
        ew.defects.append(errors.InvalidHeaderDefect('whitespace inside encoded word'))
    ew.cte = value
    value = ''.join(remainder)
    try:
        (text, charset, lang, defects) = _ew.decode('=?' + tok + '?=')
    except ValueError:
        raise errors.HeaderParseError("encoded word format invalid: '{}'".format(ew.cte))
    ew.charset = charset
    ew.lang = lang
    ew.defects.extend(defects)
    while text:
        if text[0] in WSP:
            (token, text) = get_fws(text)
            ew.append(token)
            continue
        (chars, *remainder) = _wsp_splitter(text, 1)
        vtext = ValueTerminal(chars, 'vtext')
        _validate_xtext(vtext)
        ew.append(vtext)
        text = ''.join(remainder)
    return (ew, value)

def get_unstructured(value):
    unstructured = UnstructuredTokenList()
    while value:
        if value[0] in WSP:
            (token, value) = get_fws(value)
            unstructured.append(token)
            continue
        if value.startswith('=?'):
            try:
                (token, value) = get_encoded_word(value)
            except errors.HeaderParseError:
                pass
            have_ws = True
            if len(unstructured) > 0 and unstructured[-1].token_type != 'fws':
                unstructured.defects.append(errors.InvalidHeaderDefect('missing whitespace before encoded word'))
                have_ws = False
            if have_ws and len(unstructured) > 1 and unstructured[-2].token_type == 'encoded-word':
                unstructured[-1] = EWWhiteSpaceTerminal(unstructured[-1], 'fws')
            unstructured.append(token)
            continue
        (tok, *remainder) = _wsp_splitter(value, 1)
        vtext = ValueTerminal(tok, 'vtext')
        _validate_xtext(vtext)
        unstructured.append(vtext)
        value = ''.join(remainder)
    return unstructured

def get_qp_ctext(value):
    (ptext, value, _) = _get_ptext_to_endchars(value, '()')
    ptext = WhiteSpaceTerminal(ptext, 'ptext')
    _validate_xtext(ptext)
    return (ptext, value)

def get_qcontent(value):
    (ptext, value, _) = _get_ptext_to_endchars(value, '"')
    ptext = ValueTerminal(ptext, 'ptext')
    _validate_xtext(ptext)
    return (ptext, value)

def get_atext(value):
    m = _non_atom_end_matcher(value)
    if not m:
        raise errors.HeaderParseError("expected atext but found '{}'".format(value))
    atext = m.group()
    value = value[len(atext):]
    atext = ValueTerminal(atext, 'atext')
    _validate_xtext(atext)
    return (atext, value)

def get_bare_quoted_string(value):
    if value[0] != '"':
        raise errors.HeaderParseError('expected \'"\' but found \'{}\''.format(value))
    bare_quoted_string = BareQuotedString()
    value = value[1:]
    while value:
        if value[0] in WSP:
            (token, value) = get_fws(value)
        elif value[:2] == '=?':
            try:
                (token, value) = get_encoded_word(value)
                bare_quoted_string.defects.append(errors.InvalidHeaderDefect('encoded word inside quoted string'))
            except errors.HeaderParseError:
                (token, value) = get_qcontent(value)
        else:
            (token, value) = get_qcontent(value)
        bare_quoted_string.append(token)
    if not value:
        bare_quoted_string.defects.append(errors.InvalidHeaderDefect('end of header inside quoted string'))
        return (bare_quoted_string, value)
    return (bare_quoted_string, value[1:])

def get_comment(value):
    if value and value[0] != '(':
        raise errors.HeaderParseError("expected '(' but found '{}'".format(value))
    comment = Comment()
    value = value[1:]
    while value:
        if value[0] in WSP:
            (token, value) = get_fws(value)
        elif value[0] == '(':
            (token, value) = get_comment(value)
        else:
            (token, value) = get_qp_ctext(value)
        comment.append(token)
    if not value:
        comment.defects.append(errors.InvalidHeaderDefect('end of header inside comment'))
        return (comment, value)
    return (comment, value[1:])

def get_cfws(value):
    cfws = CFWSList()
    while value:
        if value[0] in WSP:
            (token, value) = get_fws(value)
        else:
            (token, value) = get_comment(value)
        cfws.append(token)
    return (cfws, value)

def get_quoted_string(value):
    quoted_string = QuotedString()
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        quoted_string.append(token)
    (token, value) = get_bare_quoted_string(value)
    quoted_string.append(token)
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        quoted_string.append(token)
    return (quoted_string, value)

def get_atom(value):
    atom = Atom()
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        atom.append(token)
    if value and value[0] in ATOM_ENDS:
        raise errors.HeaderParseError("expected atom but found '{}'".format(value))
    if value.startswith('=?'):
        try:
            (token, value) = get_encoded_word(value)
        except errors.HeaderParseError:
            (token, value) = get_atext(value)
    else:
        (token, value) = get_atext(value)
    atom.append(token)
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        atom.append(token)
    return (atom, value)

def get_dot_atom_text(value):
    dot_atom_text = DotAtomText()
    if not value or value[0] in ATOM_ENDS:
        raise errors.HeaderParseError("expected atom at a start of dot-atom-text but found '{}'".format(value))
    while value:
        while value[0] not in ATOM_ENDS:
            (token, value) = get_atext(value)
            dot_atom_text.append(token)
            while value and value[0] == '.':
                dot_atom_text.append(DOT)
                value = value[1:]
                continue
    if dot_atom_text[-1] is DOT:
        raise errors.HeaderParseError("expected atom at end of dot-atom-text but found '{}'".format('.' + value))
    return (dot_atom_text, value)

def get_dot_atom(value):
    dot_atom = DotAtom()
    if value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        dot_atom.append(token)
    if value.startswith('=?'):
        try:
            (token, value) = get_encoded_word(value)
        except errors.HeaderParseError:
            (token, value) = get_dot_atom_text(value)
    else:
        (token, value) = get_dot_atom_text(value)
    dot_atom.append(token)
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        dot_atom.append(token)
    return (dot_atom, value)

def get_word(value):
    if value[0] in CFWS_LEADER:
        (leader, value) = get_cfws(value)
    else:
        leader = None
    if value[0] == '"':
        (token, value) = get_quoted_string(value)
    elif value[0] in SPECIALS:
        raise errors.HeaderParseError("Expected 'atom' or 'quoted-string' but found '{}'".format(value))
    else:
        (token, value) = get_atom(value)
    if leader is not None:
        token[:0] = [leader]
    return (token, value)

def get_phrase(value):
    phrase = Phrase()
    try:
        (token, value) = get_word(value)
        phrase.append(token)
    except errors.HeaderParseError:
        phrase.defects.append(errors.InvalidHeaderDefect('phrase does not start with word'))
    while value:
        if value[0] == '.':
            phrase.append(DOT)
            phrase.defects.append(errors.ObsoleteHeaderDefect("period in 'phrase'"))
            value = value[1:]
        else:
            try:
                (token, value) = get_word(value)
            except errors.HeaderParseError:
                if value[0] in CFWS_LEADER:
                    (token, value) = get_cfws(value)
                    phrase.defects.append(errors.ObsoleteHeaderDefect('comment found without atom'))
                else:
                    raise
            phrase.append(token)
    return (phrase, value)

def get_local_part(value):
    local_part = LocalPart()
    leader = None
    if value[0] in CFWS_LEADER:
        (leader, value) = get_cfws(value)
    if not value:
        raise errors.HeaderParseError("expected local-part but found '{}'".format(value))
    try:
        (token, value) = get_dot_atom(value)
    except errors.HeaderParseError:
        try:
            (token, value) = get_word(value)
        except errors.HeaderParseError:
            if value[0] != '\\' and value[0] in PHRASE_ENDS:
                raise
            token = TokenList()
    if leader is not None:
        token[:0] = [leader]
    local_part.append(token)
    if value and (value[0] == '\\' or value[0] not in PHRASE_ENDS):
        (obs_local_part, value) = get_obs_local_part(str(local_part) + value)
        if obs_local_part.token_type == 'invalid-obs-local-part':
            local_part.defects.append(errors.InvalidHeaderDefect('local-part is not dot-atom, quoted-string, or obs-local-part'))
        else:
            local_part.defects.append(errors.ObsoleteHeaderDefect('local-part is not a dot-atom (contains CFWS)'))
        local_part[0] = obs_local_part
    try:
        local_part.value.encode('ascii')
    except UnicodeEncodeError:
        local_part.defects.append(errors.NonASCIILocalPartDefect('local-part contains non-ASCII characters)'))
    return (local_part, value)

def get_obs_local_part(value):
    obs_local_part = ObsLocalPart()
    last_non_ws_was_dot = False
    while value:
        if value[0] == '.':
            if last_non_ws_was_dot:
                obs_local_part.defects.append(errors.InvalidHeaderDefect("invalid repeated '.'"))
            obs_local_part.append(DOT)
            last_non_ws_was_dot = True
            value = value[1:]
            continue
        elif value[0] == '\\':
            obs_local_part.append(ValueTerminal(value[0], 'misplaced-special'))
            value = value[1:]
            obs_local_part.defects.append(errors.InvalidHeaderDefect("'\\' character outside of quoted-string/ccontent"))
            last_non_ws_was_dot = False
            continue
        if obs_local_part and obs_local_part[-1].token_type != 'dot':
            obs_local_part.defects.append(errors.InvalidHeaderDefect("missing '.' between words"))
        try:
            (token, value) = get_word(value)
            last_non_ws_was_dot = False
        except errors.HeaderParseError:
            if value[0] not in CFWS_LEADER:
                raise
            (token, value) = get_cfws(value)
        obs_local_part.append(token)
    if obs_local_part[0].token_type == 'dot' or obs_local_part[0].token_type == 'cfws' and obs_local_part[1].token_type == 'dot':
        obs_local_part.defects.append(errors.InvalidHeaderDefect("Invalid leading '.' in local part"))
    if obs_local_part[-1].token_type == 'dot' or obs_local_part[-1].token_type == 'cfws' and obs_local_part[-2].token_type == 'dot':
        obs_local_part.defects.append(errors.InvalidHeaderDefect("Invalid trailing '.' in local part"))
    if obs_local_part.defects:
        obs_local_part.token_type = 'invalid-obs-local-part'
    return (obs_local_part, value)

def get_dtext(value):
    (ptext, value, had_qp) = _get_ptext_to_endchars(value, '[]')
    ptext = ValueTerminal(ptext, 'ptext')
    if had_qp:
        ptext.defects.append(errors.ObsoleteHeaderDefect('quoted printable found in domain-literal'))
    _validate_xtext(ptext)
    return (ptext, value)

def _check_for_early_dl_end(value, domain_literal):
    if value:
        return False
    domain_literal.append(errors.InvalidHeaderDefect('end of input inside domain-literal'))
    domain_literal.append(ValueTerminal(']', 'domain-literal-end'))
    return True

def get_domain_literal(value):
    domain_literal = DomainLiteral()
    if value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        domain_literal.append(token)
    if not value:
        raise errors.HeaderParseError('expected domain-literal')
    if value[0] != '[':
        raise errors.HeaderParseError("expected '[' at start of domain-literal but found '{}'".format(value))
    value = value[1:]
    if _check_for_early_dl_end(value, domain_literal):
        return (domain_literal, value)
    domain_literal.append(ValueTerminal('[', 'domain-literal-start'))
    if value[0] in WSP:
        (token, value) = get_fws(value)
        domain_literal.append(token)
    (token, value) = get_dtext(value)
    domain_literal.append(token)
    if _check_for_early_dl_end(value, domain_literal):
        return (domain_literal, value)
    if value[0] in WSP:
        (token, value) = get_fws(value)
        domain_literal.append(token)
    if _check_for_early_dl_end(value, domain_literal):
        return (domain_literal, value)
    if value[0] != ']':
        raise errors.HeaderParseError("expected ']' at end of domain-literal but found '{}'".format(value))
    domain_literal.append(ValueTerminal(']', 'domain-literal-end'))
    value = value[1:]
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        domain_literal.append(token)
    return (domain_literal, value)

def get_domain(value):
    domain = Domain()
    leader = None
    if value[0] in CFWS_LEADER:
        (leader, value) = get_cfws(value)
    if not value:
        raise errors.HeaderParseError("expected domain but found '{}'".format(value))
    if value[0] == '[':
        (token, value) = get_domain_literal(value)
        if leader is not None:
            token[:0] = [leader]
        domain.append(token)
        return (domain, value)
    try:
        (token, value) = get_dot_atom(value)
    except errors.HeaderParseError:
        (token, value) = get_atom(value)
    if leader is not None:
        token[:0] = [leader]
    domain.append(token)
    if value and value[0] == '.':
        domain.defects.append(errors.ObsoleteHeaderDefect('domain is not a dot-atom (contains CFWS)'))
        if domain[0].token_type == 'dot-atom':
            domain[:] = domain[0]
        while value and value[0] == '.':
            domain.append(DOT)
            (token, value) = get_atom(value[1:])
            domain.append(token)
    return (domain, value)

def get_addr_spec(value):
    addr_spec = AddrSpec()
    (token, value) = get_local_part(value)
    addr_spec.append(token)
    if not value or value[0] != '@':
        addr_spec.defects.append(errors.InvalidHeaderDefect('add-spec local part with no domain'))
        return (addr_spec, value)
    addr_spec.append(ValueTerminal('@', 'address-at-symbol'))
    (token, value) = get_domain(value[1:])
    addr_spec.append(token)
    return (addr_spec, value)

def get_obs_route(value):
    obs_route = ObsRoute()
    while value:
        if value[0] in CFWS_LEADER:
            (token, value) = get_cfws(value)
            obs_route.append(token)
        else:
            while value[0] == ',':
                obs_route.append(ListSeparator)
                value = value[1:]
                continue
    if not value or value[0] != '@':
        raise errors.HeaderParseError("expected obs-route domain but found '{}'".format(value))
    obs_route.append(RouteComponentMarker)
    (token, value) = get_domain(value[1:])
    obs_route.append(token)
    while value:
        while value[0] == ',':
            obs_route.append(ListSeparator)
            value = value[1:]
            if not value:
                break
            if value[0] in CFWS_LEADER:
                (token, value) = get_cfws(value)
                obs_route.append(token)
            while value[0] == '@':
                obs_route.append(RouteComponentMarker)
                (token, value) = get_domain(value[1:])
                obs_route.append(token)
                continue
    if not value:
        raise errors.HeaderParseError('end of header while parsing obs-route')
    if value[0] != ':':
        raise errors.HeaderParseError("expected ':' marking end of obs-route but found '{}'".format(value))
    obs_route.append(ValueTerminal(':', 'end-of-obs-route-marker'))
    return (obs_route, value[1:])

def get_angle_addr(value):
    angle_addr = AngleAddr()
    if value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        angle_addr.append(token)
    if not value or value[0] != '<':
        raise errors.HeaderParseError("expected angle-addr but found '{}'".format(value))
    angle_addr.append(ValueTerminal('<', 'angle-addr-start'))
    value = value[1:]
    if value[0] == '>':
        angle_addr.append(ValueTerminal('>', 'angle-addr-end'))
        angle_addr.defects.append(errors.InvalidHeaderDefect('null addr-spec in angle-addr'))
        value = value[1:]
        return (angle_addr, value)
    try:
        (token, value) = get_addr_spec(value)
    except errors.HeaderParseError:
        try:
            (token, value) = get_obs_route(value)
            angle_addr.defects.append(errors.ObsoleteHeaderDefect('obsolete route specification in angle-addr'))
        except errors.HeaderParseError:
            raise errors.HeaderParseError("expected addr-spec or obs-route but found '{}'".format(value))
        angle_addr.append(token)
        (token, value) = get_addr_spec(value)
    angle_addr.append(token)
    if value and value[0] == '>':
        value = value[1:]
    else:
        angle_addr.defects.append(errors.InvalidHeaderDefect("missing trailing '>' on angle-addr"))
    angle_addr.append(ValueTerminal('>', 'angle-addr-end'))
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        angle_addr.append(token)
    return (angle_addr, value)

def get_display_name(value):
    display_name = DisplayName()
    (token, value) = get_phrase(value)
    display_name.extend(token[:])
    display_name.defects = token.defects[:]
    return (display_name, value)

def get_name_addr(value):
    name_addr = NameAddr()
    leader = None
    if value[0] in CFWS_LEADER:
        (leader, value) = get_cfws(value)
        if not value:
            raise errors.HeaderParseError("expected name-addr but found '{}'".format(leader))
    if value[0] != '<':
        if value[0] in PHRASE_ENDS:
            raise errors.HeaderParseError("expected name-addr but found '{}'".format(value))
        (token, value) = get_display_name(value)
        if not value:
            raise errors.HeaderParseError("expected name-addr but found '{}'".format(token))
        if leader is not None:
            token[0][:0] = [leader]
            leader = None
        name_addr.append(token)
    (token, value) = get_angle_addr(value)
    if leader is not None:
        token[:0] = [leader]
    name_addr.append(token)
    return (name_addr, value)

def get_mailbox(value):
    mailbox = Mailbox()
    try:
        (token, value) = get_name_addr(value)
    except errors.HeaderParseError:
        try:
            (token, value) = get_addr_spec(value)
        except errors.HeaderParseError:
            raise errors.HeaderParseError("expected mailbox but found '{}'".format(value))
    if any(isinstance(x, errors.InvalidHeaderDefect) for x in token.all_defects):
        mailbox.token_type = 'invalid-mailbox'
    mailbox.append(token)
    return (mailbox, value)

def get_invalid_mailbox(value, endchars):
    invalid_mailbox = InvalidMailbox()
    while value:
        if value[0] in PHRASE_ENDS:
            invalid_mailbox.append(ValueTerminal(value[0], 'misplaced-special'))
            value = value[1:]
        else:
            (token, value) = get_phrase(value)
            invalid_mailbox.append(token)
    return (invalid_mailbox, value)

def get_mailbox_list(value):
    mailbox_list = MailboxList()
    while value:
        while value[0] != ';':
            try:
                (token, value) = get_mailbox(value)
                mailbox_list.append(token)
            except errors.HeaderParseError:
                leader = None
                if value[0] in CFWS_LEADER:
                    (leader, value) = get_cfws(value)
                    if not value or value[0] in ',;':
                        mailbox_list.append(leader)
                        mailbox_list.defects.append(errors.ObsoleteHeaderDefect('empty element in mailbox-list'))
                    else:
                        (token, value) = get_invalid_mailbox(value, ',;')
                        if leader is not None:
                            token[:0] = [leader]
                        mailbox_list.append(token)
                        mailbox_list.defects.append(errors.InvalidHeaderDefect('invalid mailbox in mailbox-list'))
                elif value[0] == ',':
                    mailbox_list.defects.append(errors.ObsoleteHeaderDefect('empty element in mailbox-list'))
                else:
                    (token, value) = get_invalid_mailbox(value, ',;')
                    if leader is not None:
                        token[:0] = [leader]
                    mailbox_list.append(token)
                    mailbox_list.defects.append(errors.InvalidHeaderDefect('invalid mailbox in mailbox-list'))
            if value and value[0] not in ',;':
                mailbox = mailbox_list[-1]
                mailbox.token_type = 'invalid-mailbox'
                (token, value) = get_invalid_mailbox(value, ',;')
                mailbox.extend(token)
                mailbox_list.defects.append(errors.InvalidHeaderDefect('invalid mailbox in mailbox-list'))
            while value and value[0] == ',':
                mailbox_list.append(ListSeparator)
                value = value[1:]
                continue
    return (mailbox_list, value)

def get_group_list(value):
    group_list = GroupList()
    if not value:
        group_list.defects.append(errors.InvalidHeaderDefect('end of header before group-list'))
        return (group_list, value)
    leader = None
    if value and value[0] in CFWS_LEADER:
        (leader, value) = get_cfws(value)
        if not value:
            group_list.defects.append(errors.InvalidHeaderDefect('end of header in group-list'))
            group_list.append(leader)
            return (group_list, value)
        if value[0] == ';':
            group_list.append(leader)
            return (group_list, value)
    (token, value) = get_mailbox_list(value)
    if len(token.all_mailboxes) == 0:
        if leader is not None:
            group_list.append(leader)
        group_list.extend(token)
        group_list.defects.append(errors.ObsoleteHeaderDefect('group-list with empty entries'))
        return (group_list, value)
    if leader is not None:
        token[:0] = [leader]
    group_list.append(token)
    return (group_list, value)

def get_group(value):
    group = Group()
    (token, value) = get_display_name(value)
    if not value or value[0] != ':':
        raise errors.HeaderParseError("expected ':' at end of group display name but found '{}'".format(value))
    group.append(token)
    group.append(ValueTerminal(':', 'group-display-name-terminator'))
    value = value[1:]
    if value and value[0] == ';':
        group.append(ValueTerminal(';', 'group-terminator'))
        return (group, value[1:])
    (token, value) = get_group_list(value)
    group.append(token)
    if not value:
        group.defects.append(errors.InvalidHeaderDefect('end of header in group'))
    if value[0] != ';':
        raise errors.HeaderParseError("expected ';' at end of group but found {}".format(value))
    group.append(ValueTerminal(';', 'group-terminator'))
    value = value[1:]
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        group.append(token)
    return (group, value)

def get_address(value):
    address = Address()
    try:
        (token, value) = get_group(value)
    except errors.HeaderParseError:
        try:
            (token, value) = get_mailbox(value)
        except errors.HeaderParseError:
            raise errors.HeaderParseError("expected address but found '{}'".format(value))
    address.append(token)
    return (address, value)

def get_address_list(value):
    address_list = AddressList()
    while value:
        try:
            (token, value) = get_address(value)
            address_list.append(token)
        except errors.HeaderParseError as err:
            leader = None
            if value[0] in CFWS_LEADER:
                (leader, value) = get_cfws(value)
                if not value or value[0] == ',':
                    address_list.append(leader)
                    address_list.defects.append(errors.ObsoleteHeaderDefect('address-list entry with no content'))
                else:
                    (token, value) = get_invalid_mailbox(value, ',')
                    if leader is not None:
                        token[:0] = [leader]
                    address_list.append(Address([token]))
                    address_list.defects.append(errors.InvalidHeaderDefect('invalid address in address-list'))
            elif value[0] == ',':
                address_list.defects.append(errors.ObsoleteHeaderDefect('empty element in address-list'))
            else:
                (token, value) = get_invalid_mailbox(value, ',')
                if leader is not None:
                    token[:0] = [leader]
                address_list.append(Address([token]))
                address_list.defects.append(errors.InvalidHeaderDefect('invalid address in address-list'))
        if value and value[0] != ',':
            mailbox = address_list[-1][0]
            mailbox.token_type = 'invalid-mailbox'
            (token, value) = get_invalid_mailbox(value, ',')
            mailbox.extend(token)
            address_list.defects.append(errors.InvalidHeaderDefect('invalid address in address-list'))
        while value:
            address_list.append(ValueTerminal(',', 'list-separator'))
            value = value[1:]
            continue
    return (address_list, value)

def parse_mime_version(value):
    mime_version = MIMEVersion()
    if not value:
        mime_version.defects.append(errors.HeaderMissingRequiredValue('Missing MIME version number (eg: 1.0)'))
        return mime_version
    if value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        mime_version.append(token)
        if not value:
            mime_version.defects.append(errors.HeaderMissingRequiredValue('Expected MIME version number but found only CFWS'))
    digits = ''
    while value:
        while value[0] != '.' and value[0] not in CFWS_LEADER:
            digits += value[0]
            value = value[1:]
    if not digits.isdigit():
        mime_version.defects.append(errors.InvalidHeaderDefect('Expected MIME major version number but found {!r}'.format(digits)))
        mime_version.append(ValueTerminal(digits, 'xtext'))
    else:
        mime_version.major = int(digits)
        mime_version.append(ValueTerminal(digits, 'digits'))
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        mime_version.append(token)
    if not value or value[0] != '.':
        if mime_version.major is not None:
            mime_version.defects.append(errors.InvalidHeaderDefect('Incomplete MIME version; found only major number'))
        if value:
            mime_version.append(ValueTerminal(value, 'xtext'))
        return mime_version
    mime_version.append(ValueTerminal('.', 'version-separator'))
    value = value[1:]
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        mime_version.append(token)
    if not value:
        if mime_version.major is not None:
            mime_version.defects.append(errors.InvalidHeaderDefect('Incomplete MIME version; found only major number'))
        return mime_version
    digits = ''
    while value:
        while value[0] not in CFWS_LEADER:
            digits += value[0]
            value = value[1:]
    if not digits.isdigit():
        mime_version.defects.append(errors.InvalidHeaderDefect('Expected MIME minor version number but found {!r}'.format(digits)))
        mime_version.append(ValueTerminal(digits, 'xtext'))
    else:
        mime_version.minor = int(digits)
        mime_version.append(ValueTerminal(digits, 'digits'))
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        mime_version.append(token)
    if value:
        mime_version.defects.append(errors.InvalidHeaderDefect('Excess non-CFWS text after MIME version'))
        mime_version.append(ValueTerminal(value, 'xtext'))
    return mime_version

def get_invalid_parameter(value):
    invalid_parameter = InvalidParameter()
    while value:
        if value[0] in PHRASE_ENDS:
            invalid_parameter.append(ValueTerminal(value[0], 'misplaced-special'))
            value = value[1:]
        else:
            (token, value) = get_phrase(value)
            invalid_parameter.append(token)
    return (invalid_parameter, value)

def get_ttext(value):
    m = _non_token_end_matcher(value)
    if not m:
        raise errors.HeaderParseError("expected ttext but found '{}'".format(value))
    ttext = m.group()
    value = value[len(ttext):]
    ttext = ValueTerminal(ttext, 'ttext')
    _validate_xtext(ttext)
    return (ttext, value)

def get_token(value):
    mtoken = Token()
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        mtoken.append(token)
    if value and value[0] in TOKEN_ENDS:
        raise errors.HeaderParseError("expected token but found '{}'".format(value))
    (token, value) = get_ttext(value)
    mtoken.append(token)
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        mtoken.append(token)
    return (mtoken, value)

def get_attrtext(value):
    m = _non_attribute_end_matcher(value)
    if not m:
        raise errors.HeaderParseError('expected attrtext but found {!r}'.format(value))
    attrtext = m.group()
    value = value[len(attrtext):]
    attrtext = ValueTerminal(attrtext, 'attrtext')
    _validate_xtext(attrtext)
    return (attrtext, value)

def get_attribute(value):
    attribute = Attribute()
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        attribute.append(token)
    if value and value[0] in ATTRIBUTE_ENDS:
        raise errors.HeaderParseError("expected token but found '{}'".format(value))
    (token, value) = get_attrtext(value)
    attribute.append(token)
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        attribute.append(token)
    return (attribute, value)

def get_extended_attrtext(value):
    m = _non_extended_attribute_end_matcher(value)
    if not m:
        raise errors.HeaderParseError('expected extended attrtext but found {!r}'.format(value))
    attrtext = m.group()
    value = value[len(attrtext):]
    attrtext = ValueTerminal(attrtext, 'extended-attrtext')
    _validate_xtext(attrtext)
    return (attrtext, value)

def get_extended_attribute(value):
    attribute = Attribute()
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        attribute.append(token)
    if value and value[0] in EXTENDED_ATTRIBUTE_ENDS:
        raise errors.HeaderParseError("expected token but found '{}'".format(value))
    (token, value) = get_extended_attrtext(value)
    attribute.append(token)
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        attribute.append(token)
    return (attribute, value)

def get_section(value):
    section = Section()
    if not value or value[0] != '*':
        raise errors.HeaderParseError('Expected section but found {}'.format(value))
    section.append(ValueTerminal('*', 'section-marker'))
    value = value[1:]
    if not value or not value[0].isdigit():
        raise errors.HeaderParseError('Expected section number but found {}'.format(value))
    digits = ''
    while value:
        while value[0].isdigit():
            digits += value[0]
            value = value[1:]
    if digits[0] == '0' and digits != '0':
        section.defects.append(errors.InvalidHeaderError('section numberhas an invalid leading 0'))
    section.number = int(digits)
    section.append(ValueTerminal(digits, 'digits'))
    return (section, value)

def get_value(value):
    v = Value()
    if not value:
        raise errors.HeaderParseError('Expected value but found end of string')
    leader = None
    if value[0] in CFWS_LEADER:
        (leader, value) = get_cfws(value)
    if not value:
        raise errors.HeaderParseError('Expected value but found only {}'.format(leader))
    if value[0] == '"':
        (token, value) = get_quoted_string(value)
    else:
        (token, value) = get_extended_attribute(value)
    if leader is not None:
        token[:0] = [leader]
    v.append(token)
    return (v, value)

def get_parameter(value):
    param = Parameter()
    (token, value) = get_attribute(value)
    param.append(token)
    if not value or value[0] == ';':
        param.defects.append(errors.InvalidHeaderDefect('Parameter contains name ({}) but no value'.format(token)))
        return (param, value)
    if value[0] == '*':
        try:
            (token, value) = get_section(value)
            param.sectioned = True
            param.append(token)
        except errors.HeaderParseError:
            pass
        if not value:
            raise errors.HeaderParseError('Incomplete parameter')
        if value[0] == '*':
            param.append(ValueTerminal('*', 'extended-parameter-marker'))
            value = value[1:]
            param.extended = True
    if value[0] != '=':
        raise errors.HeaderParseError("Parameter not followed by '='")
    param.append(ValueTerminal('=', 'parameter-separator'))
    value = value[1:]
    leader = None
    if value and value[0] in CFWS_LEADER:
        (token, value) = get_cfws(value)
        param.append(token)
    remainder = None
    appendto = param
    if param.extended and value and value[0] == '"':
        (qstring, remainder) = get_quoted_string(value)
        inner_value = qstring.stripped_value
        semi_valid = False
        if inner_value and inner_value[0] == "'":
            semi_valid = True
        else:
            (token, rest) = get_attrtext(inner_value)
            if rest and rest[0] == "'":
                semi_valid = True
        if param.section_number == 0 and semi_valid:
            param.defects.append(errors.InvalidHeaderDefect('Quoted string value for extended parameter is invalid'))
            param.append(qstring)
            for t in qstring:
                while t.token_type == 'bare-quoted-string':
                    t[:] = []
                    appendto = t
                    break
            value = inner_value
        else:
            remainder = None
            param.defects.append(errors.InvalidHeaderDefect('Parameter marked as extended but appears to have a quoted string value that is non-encoded'))
    if value and value[0] == "'":
        token = None
    else:
        (token, value) = get_value(value)
    if not param.extended or param.section_number > 0:
        if not value or value[0] != "'":
            appendto.append(token)
            if remainder is not None:
                value = remainder
            return (param, value)
        param.defects.append(errors.InvalidHeaderDefect('Apparent initial-extended-value but attribute was not marked as extended or was not initial section'))
    if not value:
        param.defects.append(errors.InvalidHeaderDefect('Missing required charset/lang delimiters'))
        appendto.append(token)
        return (param, value)
    else:
        if token is not None:
            for t in token:
                while t.token_type == 'extended-attrtext':
                    break
            t.token_type == 'attrtext'
            appendto.append(t)
            param.charset = t.value
        if value[0] != "'":
            raise errors.HeaderParseError('Expected RFC2231 char/lang encoding delimiter, but found {!r}'.format(value))
        appendto.append(ValueTerminal("'", 'RFC2231 delimiter'))
        value = value[1:]
        if value and value[0] != "'":
            (token, value) = get_attrtext(value)
            appendto.append(token)
            param.lang = token.value
            if not value or value[0] != "'":
                raise errors.HeaderParseError('Expected RFC2231 char/lang encoding delimiter, but found {}'.format(value))
        appendto.append(ValueTerminal("'", 'RFC2231 delimiter'))
        value = value[1:]
    if remainder is not None:
        v = Value()
        while value:
            if value[0] in WSP:
                (token, value) = get_fws(value)
            else:
                (token, value) = get_qcontent(value)
            v.append(token)
        token = v
    else:
        (token, value) = get_value(value)
    appendto.append(token)
    if remainder is not None:
        value = remainder
    return (param, value)

def parse_mime_parameters(value):
    mime_parameters = MimeParameters()
    while value:
        try:
            (token, value) = get_parameter(value)
            mime_parameters.append(token)
        except errors.HeaderParseError as err:
            leader = None
            if value[0] in CFWS_LEADER:
                (leader, value) = get_cfws(value)
            if not value:
                mime_parameters.append(leader)
                return mime_parameters
            if value[0] == ';':
                if leader is not None:
                    mime_parameters.append(leader)
                mime_parameters.defects.append(errors.InvalidHeaderDefect('parameter entry with no content'))
            else:
                (token, value) = get_invalid_parameter(value)
                if leader:
                    token[:0] = [leader]
                mime_parameters.append(token)
                mime_parameters.defects.append(errors.InvalidHeaderDefect('invalid parameter {!r}'.format(token)))
        if value and value[0] != ';':
            param = mime_parameters[-1]
            param.token_type = 'invalid-parameter'
            (token, value) = get_invalid_parameter(value)
            param.extend(token)
            mime_parameters.defects.append(errors.InvalidHeaderDefect('parameter with invalid trailing text {!r}'.format(token)))
        while value:
            mime_parameters.append(ValueTerminal(';', 'parameter-separator'))
            value = value[1:]
            continue
    return mime_parameters

def _find_mime_parameters(tokenlist, value):
    while value:
        if value[0] in PHRASE_ENDS:
            tokenlist.append(ValueTerminal(value[0], 'misplaced-special'))
            value = value[1:]
        else:
            (token, value) = get_phrase(value)
            tokenlist.append(token)
    if not value:
        return
    tokenlist.append(ValueTerminal(';', 'parameter-separator'))
    tokenlist.append(parse_mime_parameters(value[1:]))

def parse_content_type_header(value):
    ctype = ContentType()
    recover = False
    if not value:
        ctype.defects.append(errors.HeaderMissingRequiredValue('Missing content type specification'))
        return ctype
    try:
        (token, value) = get_token(value)
    except errors.HeaderParseError:
        ctype.defects.append(errors.InvalidHeaderDefect('Expected content maintype but found {!r}'.format(value)))
        _find_mime_parameters(ctype, value)
        return ctype
    ctype.append(token)
    if not value or value[0] != '/':
        ctype.defects.append(errors.InvalidHeaderDefect('Invalid content type'))
        if value:
            _find_mime_parameters(ctype, value)
        return ctype
    ctype.maintype = token.value.strip().lower()
    ctype.append(ValueTerminal('/', 'content-type-separator'))
    value = value[1:]
    try:
        (token, value) = get_token(value)
    except errors.HeaderParseError:
        ctype.defects.append(errors.InvalidHeaderDefect('Expected content subtype but found {!r}'.format(value)))
        _find_mime_parameters(ctype, value)
        return ctype
    ctype.append(token)
    ctype.subtype = token.value.strip().lower()
    if not value:
        return ctype
    if value[0] != ';':
        ctype.defects.append(errors.InvalidHeaderDefect('Only parameters are valid after content type, but found {!r}'.format(value)))
        del ctype.maintype
        del ctype.subtype
        _find_mime_parameters(ctype, value)
        return ctype
    ctype.append(ValueTerminal(';', 'parameter-separator'))
    ctype.append(parse_mime_parameters(value[1:]))
    return ctype

def parse_content_disposition_header(value):
    disp_header = ContentDisposition()
    if not value:
        disp_header.defects.append(errors.HeaderMissingRequiredValue('Missing content disposition'))
        return disp_header
    try:
        (token, value) = get_token(value)
    except errors.HeaderParseError:
        ctype.defects.append(errors.InvalidHeaderDefect('Expected content disposition but found {!r}'.format(value)))
        _find_mime_parameters(disp_header, value)
        return disp_header
    disp_header.append(token)
    disp_header.content_disposition = token.value.strip().lower()
    if not value:
        return disp_header
    if value[0] != ';':
        disp_header.defects.append(errors.InvalidHeaderDefect('Only parameters are valid after content disposition, but found {!r}'.format(value)))
        _find_mime_parameters(disp_header, value)
        return disp_header
    disp_header.append(ValueTerminal(';', 'parameter-separator'))
    disp_header.append(parse_mime_parameters(value[1:]))
    return disp_header

def parse_content_transfer_encoding_header(value):
    cte_header = ContentTransferEncoding()
    if not value:
        cte_header.defects.append(errors.HeaderMissingRequiredValue('Missing content transfer encoding'))
        return cte_header
    try:
        (token, value) = get_token(value)
    except errors.HeaderParseError:
        ctype.defects.append(errors.InvalidHeaderDefect('Expected content trnasfer encoding but found {!r}'.format(value)))
    cte_header.append(token)
    cte_header.cte = token.value.strip().lower()
    if not value:
        return cte_header
    while value:
        cte_header.defects.append(errors.InvalidHeaderDefect('Extra text after content transfer encoding'))
        if value[0] in PHRASE_ENDS:
            cte_header.append(ValueTerminal(value[0], 'misplaced-special'))
            value = value[1:]
        else:
            (token, value) = get_phrase(value)
            cte_header.append(token)
    return cte_header

