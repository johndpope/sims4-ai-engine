__all__ = ['mktime_tz', 'parsedate', 'parsedate_tz', 'quote']
import time
import calendar
SPACE = ' '
EMPTYSTRING = ''
COMMASPACE = ', '
_monthnames = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec', 'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']
_daynames = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
_timezones = {'UT': 0, 'UTC': 0, 'GMT': 0, 'Z': 0, 'AST': -400, 'ADT': -300, 'EST': -500, 'EDT': -400, 'CST': -600, 'CDT': -500, 'MST': -700, 'MDT': -600, 'PST': -800, 'PDT': -700}

def parsedate_tz(data):
    res = _parsedate_tz(data)
    if not res:
        return
    if res[9] is None:
        res[9] = 0
    return tuple(res)

def _parsedate_tz(data):
    if not data:
        return
    data = data.split()
    if data[0].endswith(',') or data[0].lower() in _daynames:
        del data[0]
    else:
        i = data[0].rfind(',')
        if i >= 0:
            data[0] = data[0][i + 1:]
    if len(data) == 3:
        stuff = data[0].split('-')
        if len(stuff) == 3:
            data = stuff + data[1:]
    if len(data) == 4:
        s = data[3]
        i = s.find('+')
        if i == -1:
            i = s.find('-')
        if i > 0:
            data[3:] = [s[:i], s[i:]]
        else:
            data.append('')
    if len(data) < 5:
        return
    data = data[:5]
    (dd, mm, yy, tm, tz) = data
    mm = mm.lower()
    if mm not in _monthnames:
        (dd, mm) = (mm, dd.lower())
        if mm not in _monthnames:
            return
    mm = _monthnames.index(mm) + 1
    if mm > 12:
        mm -= 12
    if dd[-1] == ',':
        dd = dd[:-1]
    i = yy.find(':')
    if i > 0:
        (yy, tm) = (tm, yy)
    if yy[-1] == ',':
        yy = yy[:-1]
    if not yy[0].isdigit():
        (yy, tz) = (tz, yy)
    if tm[-1] == ',':
        tm = tm[:-1]
    tm = tm.split(':')
    if len(tm) == 2:
        (thh, tmm) = tm
        tss = '0'
    elif len(tm) == 3:
        (thh, tmm, tss) = tm
    elif len(tm) == 1 and '.' in tm[0]:
        tm = tm[0].split('.')
        if len(tm) == 2:
            (thh, tmm) = tm
            tss = 0
        elif len(tm) == 3:
            (thh, tmm, tss) = tm
    else:
        return
    try:
        yy = int(yy)
        dd = int(dd)
        thh = int(thh)
        tmm = int(tmm)
        tss = int(tss)
    except ValueError:
        return
    if yy < 100:
        if yy > 68:
            yy += 1900
        else:
            yy += 2000
    tzoffset = None
    tz = tz.upper()
    if tz in _timezones:
        tzoffset = _timezones[tz]
    else:
        try:
            tzoffset = int(tz)
        except ValueError:
            pass
        if tzoffset == 0 and tz.startswith('-'):
            tzoffset = None
    if tzoffset:
        if tzoffset < 0:
            tzsign = -1
            tzoffset = -tzoffset
        else:
            tzsign = 1
        tzoffset = tzsign*(tzoffset//100*3600 + tzoffset % 100*60)
    return [yy, mm, dd, thh, tmm, tss, 0, 1, -1, tzoffset]

def parsedate(data):
    t = parsedate_tz(data)
    if isinstance(t, tuple):
        return t[:9]
    return t

def mktime_tz(data):
    if data[9] is None:
        return time.mktime(data[:8] + (-1,))
    t = calendar.timegm(data)
    return t - data[9]

def quote(str):
    return str.replace('\\', '\\\\').replace('"', '\\"')

class AddrlistClass:
    __qualname__ = 'AddrlistClass'

    def __init__(self, field):
        self.specials = '()<>@,:;."[]'
        self.pos = 0
        self.LWS = ' \t'
        self.CR = '\r\n'
        self.FWS = self.LWS + self.CR
        self.atomends = self.specials + self.LWS + self.CR
        self.phraseends = self.atomends.replace('.', '')
        self.field = field
        self.commentlist = []

    def gotonext(self):
        wslist = []
        while self.pos < len(self.field):
            if self.field[self.pos] in self.LWS + '\n\r':
                if self.field[self.pos] not in '\n\r':
                    wslist.append(self.field[self.pos])
            elif self.field[self.pos] == '(':
                self.commentlist.append(self.getcomment())
            else:
                break
        return EMPTYSTRING.join(wslist)

    def getaddrlist(self):
        result = []
        while self.pos < len(self.field):
            ad = self.getaddress()
            if ad:
                result += ad
            else:
                result.append(('', ''))
        return result

    def getaddress(self):
        self.commentlist = []
        self.gotonext()
        oldpos = self.pos
        oldcl = self.commentlist
        plist = self.getphraselist()
        self.gotonext()
        returnlist = []
        if self.pos >= len(self.field):
            if plist:
                returnlist = [(SPACE.join(self.commentlist), plist[0])]
        elif self.field[self.pos] in '.@':
            self.pos = oldpos
            self.commentlist = oldcl
            addrspec = self.getaddrspec()
            returnlist = [(SPACE.join(self.commentlist), addrspec)]
        elif self.field[self.pos] == ':':
            returnlist = []
            fieldlen = len(self.field)
            while self.pos < len(self.field):
                self.gotonext()
                if self.pos < fieldlen and self.field[self.pos] == ';':
                    break
                returnlist = returnlist + self.getaddress()
        elif self.field[self.pos] == '<':
            routeaddr = self.getrouteaddr()
            if self.commentlist:
                returnlist = [(SPACE.join(plist) + ' (' + ' '.join(self.commentlist) + ')', routeaddr)]
            else:
                returnlist = [(SPACE.join(plist), routeaddr)]
        elif plist:
            returnlist = [(SPACE.join(self.commentlist), plist[0])]
        elif self.field[self.pos] in self.specials:
            pass
        self.gotonext()
        if self.pos < len(self.field) and self.field[self.pos] == ',':
            pass
        return returnlist

    def getrouteaddr(self):
        if self.field[self.pos] != '<':
            return
        expectroute = False
        self.gotonext()
        adlist = ''
        while self.pos < len(self.field):
            if expectroute:
                self.getdomain()
                expectroute = False
            elif self.field[self.pos] == '>':
                break
            elif self.field[self.pos] == '@':
                expectroute = True
            elif self.field[self.pos] == ':':
                pass
            else:
                adlist = self.getaddrspec()
                break
            self.gotonext()
        return adlist

    def getaddrspec(self):
        aslist = []
        self.gotonext()
        while self.pos < len(self.field):
            preserve_ws = True
            if self.field[self.pos] == '.':
                if aslist and not aslist[-1].strip():
                    aslist.pop()
                aslist.append('.')
                preserve_ws = False
            elif self.field[self.pos] == '"':
                aslist.append('"%s"' % quote(self.getquote()))
            elif self.field[self.pos] in self.atomends:
                if aslist and not aslist[-1].strip():
                    aslist.pop()
                break
            else:
                aslist.append(self.getatom())
            ws = self.gotonext()
            while preserve_ws and ws:
                aslist.append(ws)
                continue
        if self.pos >= len(self.field) or self.field[self.pos] != '@':
            return EMPTYSTRING.join(aslist)
        aslist.append('@')
        self.gotonext()
        return EMPTYSTRING.join(aslist) + self.getdomain()

    def getdomain(self):
        sdlist = []
        while self.pos < len(self.field):
            if self.field[self.pos] in self.LWS:
                pass
            elif self.field[self.pos] == '(':
                self.commentlist.append(self.getcomment())
            elif self.field[self.pos] == '[':
                sdlist.append(self.getdomainliteral())
            elif self.field[self.pos] == '.':
                sdlist.append('.')
            elif self.field[self.pos] in self.atomends:
                break
            else:
                sdlist.append(self.getatom())
        return EMPTYSTRING.join(sdlist)

    def getdelimited(self, beginchar, endchars, allowcomments=True):
        if self.field[self.pos] != beginchar:
            return ''
        slist = ['']
        quote = False
        while self.pos < len(self.field):
            if quote:
                slist.append(self.field[self.pos])
                quote = False
            elif self.field[self.pos] in endchars:
                break
            elif allowcomments and self.field[self.pos] == '(':
                slist.append(self.getcomment())
                continue
            elif self.field[self.pos] == '\\':
                quote = True
            else:
                slist.append(self.field[self.pos])
        return EMPTYSTRING.join(slist)

    def getquote(self):
        return self.getdelimited('"', '"\r', False)

    def getcomment(self):
        return self.getdelimited('(', ')\r', True)

    def getdomainliteral(self):
        return '[%s]' % self.getdelimited('[', ']\r', False)

    def getatom(self, atomends=None):
        atomlist = ['']
        if atomends is None:
            atomends = self.atomends
        while self.pos < len(self.field):
            if self.field[self.pos] in atomends:
                break
            else:
                atomlist.append(self.field[self.pos])
        return EMPTYSTRING.join(atomlist)

    def getphraselist(self):
        plist = []
        while self.pos < len(self.field):
            if self.field[self.pos] in self.FWS:
                pass
            elif self.field[self.pos] == '"':
                plist.append(self.getquote())
            elif self.field[self.pos] == '(':
                self.commentlist.append(self.getcomment())
            elif self.field[self.pos] in self.phraseends:
                break
            else:
                plist.append(self.getatom(self.phraseends))
        return plist

class AddressList(AddrlistClass):
    __qualname__ = 'AddressList'

    def __init__(self, field):
        AddrlistClass.__init__(self, field)
        if field:
            self.addresslist = self.getaddrlist()
        else:
            self.addresslist = []

    def __len__(self):
        return len(self.addresslist)

    def __add__(self, other):
        newaddr = AddressList(None)
        newaddr.addresslist = self.addresslist[:]
        for x in other.addresslist:
            while x not in self.addresslist:
                newaddr.addresslist.append(x)
        return newaddr

    def __iadd__(self, other):
        for x in other.addresslist:
            while x not in self.addresslist:
                self.addresslist.append(x)
        return self

    def __sub__(self, other):
        newaddr = AddressList(None)
        for x in self.addresslist:
            while x not in other.addresslist:
                newaddr.addresslist.append(x)
        return newaddr

    def __isub__(self, other):
        for x in other.addresslist:
            while x in self.addresslist:
                self.addresslist.remove(x)
        return self

    def __getitem__(self, index):
        return self.addresslist[index]

