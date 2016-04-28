import time as _time
import math as _math

def _cmp(x, y):
    if x == y:
        return 0
    if x > y:
        return 1
    return -1

MINYEAR = 1
MAXYEAR = 9999
_MAXORDINAL = 3652059
_DAYS_IN_MONTH = [None, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
_DAYS_BEFORE_MONTH = [None]
dbm = 0
for dim in _DAYS_IN_MONTH[1:]:
    _DAYS_BEFORE_MONTH.append(dbm)
    dbm += dim
del dbm
del dim

def _is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)

def _days_before_year(year):
    y = year - 1
    return y*365 + y//4 - y//100 + y//400

def _days_in_month(year, month):
    if month == 2 and _is_leap(year):
        return 29
    return _DAYS_IN_MONTH[month]

def _days_before_month(year, month):
    return _DAYS_BEFORE_MONTH[month] + (month > 2 and _is_leap(year))

def _ymd2ord(year, month, day):
    dim = _days_in_month(year, month)
    return _days_before_year(year) + _days_before_month(year, month) + day

_DI400Y = _days_before_year(401)
_DI100Y = _days_before_year(101)
_DI4Y = _days_before_year(5)

def _ord2ymd(n):
    n -= 1
    (n400, n) = divmod(n, _DI400Y)
    year = n400*400 + 1
    (n100, n) = divmod(n, _DI100Y)
    (n4, n) = divmod(n, _DI4Y)
    (n1, n) = divmod(n, 365)
    year += n100*100 + n4*4 + n1
    if n1 == 4 or n100 == 4:
        return (year - 1, 12, 31)
    leapyear = n1 == 3 and (n4 != 24 or n100 == 3)
    month = n + 50 >> 5
    preceding = _DAYS_BEFORE_MONTH[month] + (month > 2 and leapyear)
    if preceding > n:
        month -= 1
        preceding -= _DAYS_IN_MONTH[month] + (month == 2 and leapyear)
    n -= preceding
    return (year, month, n + 1)

_MONTHNAMES = [None, 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
_DAYNAMES = [None, 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

def _build_struct_time(y, m, d, hh, mm, ss, dstflag):
    wday = (_ymd2ord(y, m, d) + 6) % 7
    dnum = _days_before_month(y, m) + d
    return _time.struct_time((y, m, d, hh, mm, ss, wday, dnum, dstflag))

def _format_time(hh, mm, ss, us):
    result = '%02d:%02d:%02d' % (hh, mm, ss)
    if us:
        result += '.%06d' % us
    return result

def _wrap_strftime(object, format, timetuple):
    freplace = None
    zreplace = None
    Zreplace = None
    newformat = []
    push = newformat.append
    (i, n) = (0, len(format))
    while i < n:
        ch = format[i]
        i += 1
        if ch == '%':
            if i < n:
                ch = format[i]
                i += 1
                if ch == 'f':
                    if freplace is None:
                        freplace = '%06d' % getattr(object, 'microsecond', 0)
                    newformat.append(freplace)
                elif ch == 'z':
                    if zreplace is None:
                        zreplace = ''
                        if hasattr(object, 'utcoffset'):
                            offset = object.utcoffset()
                            if offset is not None:
                                sign = '+'
                                if offset.days < 0:
                                    offset = -offset
                                    sign = '-'
                                (h, m) = divmod(offset, timedelta(hours=1))
                                m //= timedelta(minutes=1)
                                zreplace = '%c%02d%02d' % (sign, h, m)
                    newformat.append(zreplace)
                elif ch == 'Z':
                    if Zreplace is None:
                        Zreplace = ''
                        if hasattr(object, 'tzname'):
                            s = object.tzname()
                            if s is not None:
                                Zreplace = s.replace('%', '%%')
                    newformat.append(Zreplace)
                else:
                    push('%')
                    push(ch)
                    push('%')
            else:
                push('%')
                continue
                push(ch)
        else:
            push(ch)
    newformat = ''.join(newformat)
    return _time.strftime(newformat, timetuple)

def _call_tzinfo_method(tzinfo, methname, tzinfoarg):
    if tzinfo is None:
        return
    return getattr(tzinfo, methname)(tzinfoarg)

def _check_tzname(name):
    if name is not None and not isinstance(name, str):
        raise TypeError("tzinfo.tzname() must return None or string, not '%s'" % type(name))

def _check_utc_offset(name, offset):
    if offset is None:
        return
    if not isinstance(offset, timedelta):
        raise TypeError("tzinfo.%s() must return None or timedelta, not '%s'" % (name, type(offset)))
    if offset % timedelta(minutes=1) or offset.microseconds:
        raise ValueError('tzinfo.%s() must return a whole number of minutes, got %s' % (name, offset))
    if not -timedelta(1) < offset < timedelta(1):
        raise ValueError('%s()=%s, must be must be strictly between -timedelta(hours=24) and timedelta(hours=24)' % (name, offset))

def _check_date_fields(year, month, day):
    if not isinstance(year, int):
        raise TypeError('int expected')
    if not MINYEAR <= year <= MAXYEAR:
        raise ValueError('year must be in %d..%d' % (MINYEAR, MAXYEAR), year)
    if not 1 <= month <= 12:
        raise ValueError('month must be in 1..12', month)
    dim = _days_in_month(year, month)
    if not 1 <= day <= dim:
        raise ValueError('day must be in 1..%d' % dim, day)

def _check_time_fields(hour, minute, second, microsecond):
    if not isinstance(hour, int):
        raise TypeError('int expected')
    if not 0 <= hour <= 23:
        raise ValueError('hour must be in 0..23', hour)
    if not 0 <= minute <= 59:
        raise ValueError('minute must be in 0..59', minute)
    if not 0 <= second <= 59:
        raise ValueError('second must be in 0..59', second)
    if not 0 <= microsecond <= 999999:
        raise ValueError('microsecond must be in 0..999999', microsecond)

def _check_tzinfo_arg(tz):
    if tz is not None and not isinstance(tz, tzinfo):
        raise TypeError('tzinfo argument must be None or of a tzinfo subclass')

def _cmperror(x, y):
    raise TypeError("can't compare '%s' to '%s'" % (type(x).__name__, type(y).__name__))

class timedelta:
    __qualname__ = 'timedelta'
    __slots__ = ('_days', '_seconds', '_microseconds')

    def __new__(cls, days=0, seconds=0, microseconds=0, milliseconds=0, minutes=0, hours=0, weeks=0):
        d = s = us = 0
        days += weeks*7
        seconds += minutes*60 + hours*3600
        microseconds += milliseconds*1000
        if isinstance(days, float):
            (dayfrac, days) = _math.modf(days)
            (daysecondsfrac, daysecondswhole) = _math.modf(dayfrac*86400.0)
            s = int(daysecondswhole)
            d = int(days)
        else:
            daysecondsfrac = 0.0
            d = days
        if isinstance(seconds, float):
            (secondsfrac, seconds) = _math.modf(seconds)
            seconds = int(seconds)
            secondsfrac += daysecondsfrac
        else:
            secondsfrac = daysecondsfrac
        (days, seconds) = divmod(seconds, 86400)
        d += days
        s += int(seconds)
        usdouble = secondsfrac*1000000.0
        if isinstance(microseconds, float):
            microseconds += usdouble
            microseconds = round(microseconds, 0)
            (seconds, microseconds) = divmod(microseconds, 1000000.0)
            (days, seconds) = divmod(seconds, 86400.0)
            d += int(days)
            s += int(seconds)
        else:
            (seconds, microseconds) = divmod(microseconds, 1000000)
            (days, seconds) = divmod(seconds, 86400)
            d += days
            s += int(seconds)
            microseconds = float(microseconds)
            microseconds += usdouble
            microseconds = round(microseconds, 0)
        us = int(microseconds)
        (seconds, us) = divmod(us, 1000000)
        s += seconds
        (days, s) = divmod(s, 86400)
        d += days
        self = object.__new__(cls)
        self._days = d
        self._seconds = s
        self._microseconds = us
        if abs(d) > 999999999:
            raise OverflowError('timedelta # of days is too large: %d' % d)
        return self

    def __repr__(self):
        if self._microseconds:
            return '%s(%d, %d, %d)' % ('datetime.' + self.__class__.__name__, self._days, self._seconds, self._microseconds)
        if self._seconds:
            return '%s(%d, %d)' % ('datetime.' + self.__class__.__name__, self._days, self._seconds)
        return '%s(%d)' % ('datetime.' + self.__class__.__name__, self._days)

    def __str__(self):
        (mm, ss) = divmod(self._seconds, 60)
        (hh, mm) = divmod(mm, 60)
        s = '%d:%02d:%02d' % (hh, mm, ss)
        if self._days:

            def plural(n):
                return (n, abs(n) != 1 and 's' or '')

            s = '%d day%s, ' % plural(self._days) + s
        if self._microseconds:
            s = s + '.%06d' % self._microseconds
        return s

    def total_seconds(self):
        return ((self.days*86400 + self.seconds)*1000000 + self.microseconds)/1000000

    @property
    def days(self):
        return self._days

    @property
    def seconds(self):
        return self._seconds

    @property
    def microseconds(self):
        return self._microseconds

    def __add__(self, other):
        if isinstance(other, timedelta):
            return timedelta(self._days + other._days, self._seconds + other._seconds, self._microseconds + other._microseconds)
        return NotImplemented

    __radd__ = __add__

    def __sub__(self, other):
        if isinstance(other, timedelta):
            return timedelta(self._days - other._days, self._seconds - other._seconds, self._microseconds - other._microseconds)
        return NotImplemented

    def __rsub__(self, other):
        if isinstance(other, timedelta):
            return -self + other
        return NotImplemented

    def __neg__(self):
        return timedelta(-self._days, -self._seconds, -self._microseconds)

    def __pos__(self):
        return self

    def __abs__(self):
        if self._days < 0:
            return -self
        return self

    def __mul__(self, other):
        if isinstance(other, int):
            return timedelta(self._days*other, self._seconds*other, self._microseconds*other)
        if isinstance(other, float):
            (a, b) = other.as_integer_ratio()
            return self*a/b
        return NotImplemented

    __rmul__ = __mul__

    def _to_microseconds(self):
        return (self._days*86400 + self._seconds)*1000000 + self._microseconds

    def __floordiv__(self, other):
        if not isinstance(other, (int, timedelta)):
            return NotImplemented
        usec = self._to_microseconds()
        if isinstance(other, timedelta):
            return usec//other._to_microseconds()
        if isinstance(other, int):
            return timedelta(0, 0, usec//other)

    def __truediv__(self, other):
        if not isinstance(other, (int, float, timedelta)):
            return NotImplemented
        usec = self._to_microseconds()
        if isinstance(other, timedelta):
            return usec/other._to_microseconds()
        if isinstance(other, int):
            return timedelta(0, 0, usec/other)
        if isinstance(other, float):
            (a, b) = other.as_integer_ratio()
            return timedelta(0, 0, b*usec/a)

    def __mod__(self, other):
        if isinstance(other, timedelta):
            r = self._to_microseconds() % other._to_microseconds()
            return timedelta(0, 0, r)
        return NotImplemented

    def __divmod__(self, other):
        if isinstance(other, timedelta):
            (q, r) = divmod(self._to_microseconds(), other._to_microseconds())
            return (q, timedelta(0, 0, r))
        return NotImplemented

    def __eq__(self, other):
        if isinstance(other, timedelta):
            return self._cmp(other) == 0
        return False

    def __ne__(self, other):
        if isinstance(other, timedelta):
            return self._cmp(other) != 0
        return True

    def __le__(self, other):
        if isinstance(other, timedelta):
            return self._cmp(other) <= 0
        _cmperror(self, other)

    def __lt__(self, other):
        if isinstance(other, timedelta):
            return self._cmp(other) < 0
        _cmperror(self, other)

    def __ge__(self, other):
        if isinstance(other, timedelta):
            return self._cmp(other) >= 0
        _cmperror(self, other)

    def __gt__(self, other):
        if isinstance(other, timedelta):
            return self._cmp(other) > 0
        _cmperror(self, other)

    def _cmp(self, other):
        return _cmp(self._getstate(), other._getstate())

    def __hash__(self):
        return hash(self._getstate())

    def __bool__(self):
        return self._days != 0 or (self._seconds != 0 or self._microseconds != 0)

    def _getstate(self):
        return (self._days, self._seconds, self._microseconds)

    def __reduce__(self):
        return (self.__class__, self._getstate())

timedelta.min = timedelta(-999999999)
timedelta.max = timedelta(days=999999999, hours=23, minutes=59, seconds=59, microseconds=999999)
timedelta.resolution = timedelta(microseconds=1)

class date:
    __qualname__ = 'date'
    __slots__ = ('_year', '_month', '_day')

    def __new__(cls, year, month=None, day=None):
        if isinstance(year, bytes) and len(year) == 4:
            if 1 <= year[2] <= 12 and month is None:
                self = object.__new__(cls)
                self._date__setstate(year)
                return self
        _check_date_fields(year, month, day)
        self = object.__new__(cls)
        self._year = year
        self._month = month
        self._day = day
        return self

    @classmethod
    def fromtimestamp(cls, t):
        (y, m, d, hh, mm, ss, weekday, jday, dst) = _time.localtime(t)
        return cls(y, m, d)

    @classmethod
    def today(cls):
        t = _time.time()
        return cls.fromtimestamp(t)

    @classmethod
    def fromordinal(cls, n):
        (y, m, d) = _ord2ymd(n)
        return cls(y, m, d)

    def __repr__(self):
        return '%s(%d, %d, %d)' % ('datetime.' + self.__class__.__name__, self._year, self._month, self._day)

    def ctime(self):
        weekday = self.toordinal() % 7 or 7
        return '%s %s %2d 00:00:00 %04d' % (_DAYNAMES[weekday], _MONTHNAMES[self._month], self._day, self._year)

    def strftime(self, fmt):
        return _wrap_strftime(self, fmt, self.timetuple())

    def __format__(self, fmt):
        if len(fmt) != 0:
            return self.strftime(fmt)
        return str(self)

    def isoformat(self):
        return '%04d-%02d-%02d' % (self._year, self._month, self._day)

    __str__ = isoformat

    @property
    def year(self):
        return self._year

    @property
    def month(self):
        return self._month

    @property
    def day(self):
        return self._day

    def timetuple(self):
        return _build_struct_time(self._year, self._month, self._day, 0, 0, 0, -1)

    def toordinal(self):
        return _ymd2ord(self._year, self._month, self._day)

    def replace(self, year=None, month=None, day=None):
        if year is None:
            year = self._year
        if month is None:
            month = self._month
        if day is None:
            day = self._day
        _check_date_fields(year, month, day)
        return date(year, month, day)

    def __eq__(self, other):
        if isinstance(other, date):
            return self._cmp(other) == 0
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, date):
            return self._cmp(other) != 0
        return NotImplemented

    def __le__(self, other):
        if isinstance(other, date):
            return self._cmp(other) <= 0
        return NotImplemented

    def __lt__(self, other):
        if isinstance(other, date):
            return self._cmp(other) < 0
        return NotImplemented

    def __ge__(self, other):
        if isinstance(other, date):
            return self._cmp(other) >= 0
        return NotImplemented

    def __gt__(self, other):
        if isinstance(other, date):
            return self._cmp(other) > 0
        return NotImplemented

    def _cmp(self, other):
        (y, m) = (self._year, self._month)
        d = self._day
        (y2, m2) = (other._year, other._month)
        d2 = other._day
        return _cmp((y, m, d), (y2, m2, d2))

    def __hash__(self):
        return hash(self._getstate())

    def __add__(self, other):
        if isinstance(other, timedelta):
            o = self.toordinal() + other.days
            if 0 < o <= _MAXORDINAL:
                return date.fromordinal(o)
            raise OverflowError('result out of range')
        return NotImplemented

    __radd__ = __add__

    def __sub__(self, other):
        if isinstance(other, timedelta):
            return self + timedelta(-other.days)
        if isinstance(other, date):
            days1 = self.toordinal()
            days2 = other.toordinal()
            return timedelta(days1 - days2)
        return NotImplemented

    def weekday(self):
        return (self.toordinal() + 6) % 7

    def isoweekday(self):
        return self.toordinal() % 7 or 7

    def isocalendar(self):
        year = self._year
        week1monday = _isoweek1monday(year)
        today = _ymd2ord(self._year, self._month, self._day)
        (week, day) = divmod(today - week1monday, 7)
        if week < 0:
            year -= 1
            week1monday = _isoweek1monday(year)
            (week, day) = divmod(today - week1monday, 7)
        elif week >= 52 and today >= _isoweek1monday(year + 1):
            year += 1
            week = 0
        return (year, week + 1, day + 1)

    def _getstate(self):
        (yhi, ylo) = divmod(self._year, 256)
        return (bytes([yhi, ylo, self._month, self._day]),)

    def __setstate(self, string):
        if len(string) != 4 or not 1 <= string[2] <= 12:
            raise TypeError('not enough arguments')
        (yhi, ylo, self._month, self._day) = string
        self._year = yhi*256 + ylo

    def __reduce__(self):
        return (self.__class__, self._getstate())

_date_class = date
date.min = date(1, 1, 1)
date.max = date(9999, 12, 31)
date.resolution = timedelta(days=1)

class tzinfo:
    __qualname__ = 'tzinfo'
    __slots__ = ()

    def tzname(self, dt):
        raise NotImplementedError('tzinfo subclass must override tzname()')

    def utcoffset(self, dt):
        raise NotImplementedError('tzinfo subclass must override utcoffset()')

    def dst(self, dt):
        raise NotImplementedError('tzinfo subclass must override dst()')

    def fromutc(self, dt):
        if not isinstance(dt, datetime):
            raise TypeError('fromutc() requires a datetime argument')
        if dt.tzinfo is not self:
            raise ValueError('dt.tzinfo is not self')
        dtoff = dt.utcoffset()
        if dtoff is None:
            raise ValueError('fromutc() requires a non-None utcoffset() result')
        dtdst = dt.dst()
        if dtdst is None:
            raise ValueError('fromutc() requires a non-None dst() result')
        delta = dtoff - dtdst
        if delta:
            dt += delta
            dtdst = dt.dst()
            if dtdst is None:
                raise ValueError('fromutc(): dt.dst gave inconsistent results; cannot convert')
        return dt + dtdst

    def __reduce__(self):
        getinitargs = getattr(self, '__getinitargs__', None)
        if getinitargs:
            args = getinitargs()
        else:
            args = ()
        getstate = getattr(self, '__getstate__', None)
        if getstate:
            state = getstate()
        else:
            state = getattr(self, '__dict__', None) or None
        if state is None:
            return (self.__class__, args)
        return (self.__class__, args, state)

_tzinfo_class = tzinfo

class time:
    __qualname__ = 'time'

    def __new__(cls, hour=0, minute=0, second=0, microsecond=0, tzinfo=None):
        self = object.__new__(cls)
        if isinstance(hour, bytes) and len(hour) == 6:
            self._time__setstate(hour, minute or None)
            return self
        _check_tzinfo_arg(tzinfo)
        _check_time_fields(hour, minute, second, microsecond)
        self._hour = hour
        self._minute = minute
        self._second = second
        self._microsecond = microsecond
        self._tzinfo = tzinfo
        return self

    @property
    def hour(self):
        return self._hour

    @property
    def minute(self):
        return self._minute

    @property
    def second(self):
        return self._second

    @property
    def microsecond(self):
        return self._microsecond

    @property
    def tzinfo(self):
        return self._tzinfo

    def __eq__(self, other):
        if isinstance(other, time):
            return self._cmp(other, allow_mixed=True) == 0
        return False

    def __ne__(self, other):
        if isinstance(other, time):
            return self._cmp(other, allow_mixed=True) != 0
        return True

    def __le__(self, other):
        if isinstance(other, time):
            return self._cmp(other) <= 0
        _cmperror(self, other)

    def __lt__(self, other):
        if isinstance(other, time):
            return self._cmp(other) < 0
        _cmperror(self, other)

    def __ge__(self, other):
        if isinstance(other, time):
            return self._cmp(other) >= 0
        _cmperror(self, other)

    def __gt__(self, other):
        if isinstance(other, time):
            return self._cmp(other) > 0
        _cmperror(self, other)

    def _cmp(self, other, allow_mixed=False):
        mytz = self._tzinfo
        ottz = other._tzinfo
        myoff = otoff = None
        if mytz is ottz:
            base_compare = True
        else:
            myoff = self.utcoffset()
            otoff = other.utcoffset()
            base_compare = myoff == otoff
        if base_compare:
            return _cmp((self._hour, self._minute, self._second, self._microsecond), (other._hour, other._minute, other._second, other._microsecond))
        if myoff is None or otoff is None:
            if allow_mixed:
                return 2
            raise TypeError('cannot compare naive and aware times')
        myhhmm = self._hour*60 + self._minute - myoff//timedelta(minutes=1)
        othhmm = other._hour*60 + other._minute - otoff//timedelta(minutes=1)
        return _cmp((myhhmm, self._second, self._microsecond), (othhmm, other._second, other._microsecond))

    def __hash__(self):
        tzoff = self.utcoffset()
        if not tzoff:
            return hash(self._getstate()[0])
        (h, m) = divmod(timedelta(hours=self.hour, minutes=self.minute) - tzoff, timedelta(hours=1))
        m //= timedelta(minutes=1)
        if 0 <= h < 24:
            return hash(time(h, m, self.second, self.microsecond))
        return hash((h, m, self.second, self.microsecond))

    def _tzstr(self, sep=':'):
        off = self.utcoffset()
        if off is not None:
            if off.days < 0:
                sign = '-'
                off = -off
            else:
                sign = '+'
            (hh, mm) = divmod(off, timedelta(hours=1))
            mm //= timedelta(minutes=1)
            off = '%s%02d%s%02d' % (sign, hh, sep, mm)
        return off

    def __repr__(self):
        if self._microsecond != 0:
            s = ', %d, %d' % (self._second, self._microsecond)
        elif self._second != 0:
            s = ', %d' % self._second
        else:
            s = ''
        s = '%s(%d, %d%s)' % ('datetime.' + self.__class__.__name__, self._hour, self._minute, s)
        if self._tzinfo is not None:
            s = s[:-1] + ', tzinfo=%r' % self._tzinfo + ')'
        return s

    def isoformat(self):
        s = _format_time(self._hour, self._minute, self._second, self._microsecond)
        tz = self._tzstr()
        if tz:
            s += tz
        return s

    __str__ = isoformat

    def strftime(self, fmt):
        timetuple = (1900, 1, 1, self._hour, self._minute, self._second, 0, 1, -1)
        return _wrap_strftime(self, fmt, timetuple)

    def __format__(self, fmt):
        if len(fmt) != 0:
            return self.strftime(fmt)
        return str(self)

    def utcoffset(self):
        if self._tzinfo is None:
            return
        offset = self._tzinfo.utcoffset(None)
        _check_utc_offset('utcoffset', offset)
        return offset

    def tzname(self):
        if self._tzinfo is None:
            return
        name = self._tzinfo.tzname(None)
        _check_tzname(name)
        return name

    def dst(self):
        if self._tzinfo is None:
            return
        offset = self._tzinfo.dst(None)
        _check_utc_offset('dst', offset)
        return offset

    def replace(self, hour=None, minute=None, second=None, microsecond=None, tzinfo=True):
        if hour is None:
            hour = self.hour
        if minute is None:
            minute = self.minute
        if second is None:
            second = self.second
        if microsecond is None:
            microsecond = self.microsecond
        if tzinfo is True:
            tzinfo = self.tzinfo
        _check_time_fields(hour, minute, second, microsecond)
        _check_tzinfo_arg(tzinfo)
        return time(hour, minute, second, microsecond, tzinfo)

    def __bool__(self):
        if self.second or self.microsecond:
            return True
        offset = self.utcoffset() or timedelta(0)
        return timedelta(hours=self.hour, minutes=self.minute) != offset

    def _getstate(self):
        (us2, us3) = divmod(self._microsecond, 256)
        (us1, us2) = divmod(us2, 256)
        basestate = bytes([self._hour, self._minute, self._second, us1, us2, us3])
        if self._tzinfo is None:
            return (basestate,)
        return (basestate, self._tzinfo)

    def __setstate(self, string, tzinfo):
        if len(string) != 6 or string[0] >= 24:
            raise TypeError('an integer is required')
        (self._hour, self._minute, self._second, us1, us2, us3) = string
        self._microsecond = (us1 << 8 | us2) << 8 | us3
        if tzinfo is None or isinstance(tzinfo, _tzinfo_class):
            self._tzinfo = tzinfo
        else:
            raise TypeError('bad tzinfo state arg %r' % tzinfo)

    def __reduce__(self):
        return (time, self._getstate())

_time_class = time
time.min = time(0, 0, 0)
time.max = time(23, 59, 59, 999999)
time.resolution = timedelta(microseconds=1)

class datetime(date):
    __qualname__ = 'datetime'
    __slots__ = date.__slots__ + ('_hour', '_minute', '_second', '_microsecond', '_tzinfo')

    def __new__(cls, year, month=None, day=None, hour=0, minute=0, second=0, microsecond=0, tzinfo=None):
        if isinstance(year, bytes) and len(year) == 10:
            self = date.__new__(cls, year[:4])
            self._datetime__setstate(year, month)
            return self
        _check_tzinfo_arg(tzinfo)
        _check_time_fields(hour, minute, second, microsecond)
        self = date.__new__(cls, year, month, day)
        self._hour = hour
        self._minute = minute
        self._second = second
        self._microsecond = microsecond
        self._tzinfo = tzinfo
        return self

    @property
    def hour(self):
        return self._hour

    @property
    def minute(self):
        return self._minute

    @property
    def second(self):
        return self._second

    @property
    def microsecond(self):
        return self._microsecond

    @property
    def tzinfo(self):
        return self._tzinfo

    @classmethod
    def fromtimestamp(cls, t, tz=None):
        _check_tzinfo_arg(tz)
        converter = _time.localtime if tz is None else _time.gmtime
        (t, frac) = divmod(t, 1.0)
        us = int(frac*1000000.0)
        if us == 1000000:
            t += 1
            us = 0
        (y, m, d, hh, mm, ss, weekday, jday, dst) = converter(t)
        ss = min(ss, 59)
        result = cls(y, m, d, hh, mm, ss, us, tz)
        if tz is not None:
            result = tz.fromutc(result)
        return result

    @classmethod
    def utcfromtimestamp(cls, t):
        (t, frac) = divmod(t, 1.0)
        us = int(frac*1000000.0)
        if us == 1000000:
            t += 1
            us = 0
        (y, m, d, hh, mm, ss, weekday, jday, dst) = _time.gmtime(t)
        ss = min(ss, 59)
        return cls(y, m, d, hh, mm, ss, us)

    @classmethod
    def now(cls, tz=None):
        t = _time.time()
        return cls.fromtimestamp(t, tz)

    @classmethod
    def utcnow(cls):
        t = _time.time()
        return cls.utcfromtimestamp(t)

    @classmethod
    def combine(cls, date, time):
        if not isinstance(date, _date_class):
            raise TypeError('date argument must be a date instance')
        if not isinstance(time, _time_class):
            raise TypeError('time argument must be a time instance')
        return cls(date.year, date.month, date.day, time.hour, time.minute, time.second, time.microsecond, time.tzinfo)

    def timetuple(self):
        dst = self.dst()
        if dst is None:
            dst = -1
        elif dst:
            dst = 1
        else:
            dst = 0
        return _build_struct_time(self.year, self.month, self.day, self.hour, self.minute, self.second, dst)

    def timestamp(self):
        if self._tzinfo is None:
            return _time.mktime((self.year, self.month, self.day, self.hour, self.minute, self.second, -1, -1, -1)) + self.microsecond/1000000.0
        return (self - _EPOCH).total_seconds()

    def utctimetuple(self):
        offset = self.utcoffset()
        if offset:
            self -= offset
        (y, m) = (self.year, self.month)
        d = self.day
        (hh, mm) = (self.hour, self.minute)
        ss = self.second
        return _build_struct_time(y, m, d, hh, mm, ss, 0)

    def date(self):
        return date(self._year, self._month, self._day)

    def time(self):
        return time(self.hour, self.minute, self.second, self.microsecond)

    def timetz(self):
        return time(self.hour, self.minute, self.second, self.microsecond, self._tzinfo)

    def replace(self, year=None, month=None, day=None, hour=None, minute=None, second=None, microsecond=None, tzinfo=True):
        if year is None:
            year = self.year
        if month is None:
            month = self.month
        if day is None:
            day = self.day
        if hour is None:
            hour = self.hour
        if minute is None:
            minute = self.minute
        if second is None:
            second = self.second
        if microsecond is None:
            microsecond = self.microsecond
        if tzinfo is True:
            tzinfo = self.tzinfo
        _check_date_fields(year, month, day)
        _check_time_fields(hour, minute, second, microsecond)
        _check_tzinfo_arg(tzinfo)
        return datetime(year, month, day, hour, minute, second, microsecond, tzinfo)

    def astimezone(self, tz=None):
        if tz is None:
            if self.tzinfo is None:
                raise ValueError('astimezone() requires an aware datetime')
            ts = (self - _EPOCH)//timedelta(seconds=1)
            localtm = _time.localtime(ts)
            local = datetime(*localtm[:6])
            try:
                gmtoff = localtm.tm_gmtoff
                zone = localtm.tm_zone
            except AttributeError:
                delta = local - datetime(*_time.gmtime(ts)[:6])
                dst = _time.daylight and localtm.tm_isdst > 0
                gmtoff = -(_time.altzone if dst else _time.timezone)
                if delta == timedelta(seconds=gmtoff):
                    tz = timezone(delta, _time.tzname[dst])
                else:
                    tz = timezone(delta)
            tz = timezone(timedelta(seconds=gmtoff), zone)
        elif not isinstance(tz, tzinfo):
            raise TypeError('tz argument must be an instance of tzinfo')
        mytz = self.tzinfo
        if mytz is None:
            raise ValueError('astimezone() requires an aware datetime')
        if tz is mytz:
            return self
        myoffset = self.utcoffset()
        if myoffset is None:
            raise ValueError('astimezone() requires an aware datetime')
        utc = (self - myoffset).replace(tzinfo=tz)
        return tz.fromutc(utc)

    def ctime(self):
        weekday = self.toordinal() % 7 or 7
        return '%s %s %2d %02d:%02d:%02d %04d' % (_DAYNAMES[weekday], _MONTHNAMES[self._month], self._day, self._hour, self._minute, self._second, self._year)

    def isoformat(self, sep='T'):
        s = '%04d-%02d-%02d%c' % (self._year, self._month, self._day, sep) + _format_time(self._hour, self._minute, self._second, self._microsecond)
        off = self.utcoffset()
        if off is not None:
            if off.days < 0:
                sign = '-'
                off = -off
            else:
                sign = '+'
            (hh, mm) = divmod(off, timedelta(hours=1))
            mm //= timedelta(minutes=1)
            s += '%s%02d:%02d' % (sign, hh, mm)
        return s

    def __repr__(self):
        L = [self._year, self._month, self._day, self._hour, self._minute, self._second, self._microsecond]
        if L[-1] == 0:
            del L[-1]
        if L[-1] == 0:
            del L[-1]
        s = ', '.join(map(str, L))
        s = '%s(%s)' % ('datetime.' + self.__class__.__name__, s)
        if self._tzinfo is not None:
            s = s[:-1] + ', tzinfo=%r' % self._tzinfo + ')'
        return s

    def __str__(self):
        return self.isoformat(sep=' ')

    @classmethod
    def strptime(cls, date_string, format):
        import _strptime
        return _strptime._strptime_datetime(cls, date_string, format)

    def utcoffset(self):
        if self._tzinfo is None:
            return
        offset = self._tzinfo.utcoffset(self)
        _check_utc_offset('utcoffset', offset)
        return offset

    def tzname(self):
        name = _call_tzinfo_method(self._tzinfo, 'tzname', self)
        _check_tzname(name)
        return name

    def dst(self):
        if self._tzinfo is None:
            return
        offset = self._tzinfo.dst(self)
        _check_utc_offset('dst', offset)
        return offset

    def __eq__(self, other):
        if isinstance(other, datetime):
            return self._cmp(other, allow_mixed=True) == 0
        if not isinstance(other, date):
            return NotImplemented
        return False

    def __ne__(self, other):
        if isinstance(other, datetime):
            return self._cmp(other, allow_mixed=True) != 0
        if not isinstance(other, date):
            return NotImplemented
        return True

    def __le__(self, other):
        if isinstance(other, datetime):
            return self._cmp(other) <= 0
        if not isinstance(other, date):
            return NotImplemented
        _cmperror(self, other)

    def __lt__(self, other):
        if isinstance(other, datetime):
            return self._cmp(other) < 0
        if not isinstance(other, date):
            return NotImplemented
        _cmperror(self, other)

    def __ge__(self, other):
        if isinstance(other, datetime):
            return self._cmp(other) >= 0
        if not isinstance(other, date):
            return NotImplemented
        _cmperror(self, other)

    def __gt__(self, other):
        if isinstance(other, datetime):
            return self._cmp(other) > 0
        if not isinstance(other, date):
            return NotImplemented
        _cmperror(self, other)

    def _cmp(self, other, allow_mixed=False):
        mytz = self._tzinfo
        ottz = other._tzinfo
        myoff = otoff = None
        if mytz is ottz:
            base_compare = True
        else:
            myoff = self.utcoffset()
            otoff = other.utcoffset()
            base_compare = myoff == otoff
        if base_compare:
            return _cmp((self._year, self._month, self._day, self._hour, self._minute, self._second, self._microsecond), (other._year, other._month, other._day, other._hour, other._minute, other._second, other._microsecond))
        if myoff is None or otoff is None:
            if allow_mixed:
                return 2
            raise TypeError('cannot compare naive and aware datetimes')
        diff = self - other
        if diff.days < 0:
            return -1
        return diff and 1 or 0

    def __add__(self, other):
        if not isinstance(other, timedelta):
            return NotImplemented
        delta = timedelta(self.toordinal(), hours=self._hour, minutes=self._minute, seconds=self._second, microseconds=self._microsecond)
        delta += other
        (hour, rem) = divmod(delta.seconds, 3600)
        (minute, second) = divmod(rem, 60)
        if 0 < delta.days <= _MAXORDINAL:
            return datetime.combine(date.fromordinal(delta.days), time(hour, minute, second, delta.microseconds, tzinfo=self._tzinfo))
        raise OverflowError('result out of range')

    __radd__ = __add__

    def __sub__(self, other):
        if not isinstance(other, datetime):
            if isinstance(other, timedelta):
                return self + -other
            return NotImplemented
        days1 = self.toordinal()
        days2 = other.toordinal()
        secs1 = self._second + self._minute*60 + self._hour*3600
        secs2 = other._second + other._minute*60 + other._hour*3600
        base = timedelta(days1 - days2, secs1 - secs2, self._microsecond - other._microsecond)
        if self._tzinfo is other._tzinfo:
            return base
        myoff = self.utcoffset()
        otoff = other.utcoffset()
        if myoff == otoff:
            return base
        if myoff is None or otoff is None:
            raise TypeError('cannot mix naive and timezone-aware time')
        return base + otoff - myoff

    def __hash__(self):
        tzoff = self.utcoffset()
        if tzoff is None:
            return hash(self._getstate()[0])
        days = _ymd2ord(self.year, self.month, self.day)
        seconds = self.hour*3600 + self.minute*60 + self.second
        return hash(timedelta(days, seconds, self.microsecond) - tzoff)

    def _getstate(self):
        (yhi, ylo) = divmod(self._year, 256)
        (us2, us3) = divmod(self._microsecond, 256)
        (us1, us2) = divmod(us2, 256)
        basestate = bytes([yhi, ylo, self._month, self._day, self._hour, self._minute, self._second, us1, us2, us3])
        if self._tzinfo is None:
            return (basestate,)
        return (basestate, self._tzinfo)

    def __setstate(self, string, tzinfo):
        (yhi, ylo, self._month, self._day, self._hour, self._minute, self._second, us1, us2, us3) = string
        self._year = yhi*256 + ylo
        self._microsecond = (us1 << 8 | us2) << 8 | us3
        if tzinfo is None or isinstance(tzinfo, _tzinfo_class):
            self._tzinfo = tzinfo
        else:
            raise TypeError('bad tzinfo state arg %r' % tzinfo)

    def __reduce__(self):
        return (self.__class__, self._getstate())

datetime.min = datetime(1, 1, 1)
datetime.max = datetime(9999, 12, 31, 23, 59, 59, 999999)
datetime.resolution = timedelta(microseconds=1)

def _isoweek1monday(year):
    THURSDAY = 3
    firstday = _ymd2ord(year, 1, 1)
    firstweekday = (firstday + 6) % 7
    week1monday = firstday - firstweekday
    if firstweekday > THURSDAY:
        week1monday += 7
    return week1monday

class timezone(tzinfo):
    __qualname__ = 'timezone'
    __slots__ = ('_offset', '_name')
    _Omitted = object()

    def __new__(cls, offset, name=_Omitted):
        if not isinstance(offset, timedelta):
            raise TypeError('offset must be a timedelta')
        if name is cls._Omitted:
            if not offset:
                return cls.utc
            name = None
        elif not isinstance(name, str):
            raise TypeError('name must be a string')
        if not cls._minoffset <= offset <= cls._maxoffset:
            raise ValueError('offset must be a timedelta strictly between -timedelta(hours=24) and timedelta(hours=24).')
        if offset.microseconds != 0 or offset.seconds % 60 != 0:
            raise ValueError('offset must be a timedelta representing a whole number of minutes')
        return cls._create(offset, name)

    @classmethod
    def _create(cls, offset, name=None):
        self = tzinfo.__new__(cls)
        self._offset = offset
        self._name = name
        return self

    def __getinitargs__(self):
        if self._name is None:
            return (self._offset,)
        return (self._offset, self._name)

    def __eq__(self, other):
        if type(other) != timezone:
            return False
        return self._offset == other._offset

    def __hash__(self):
        return hash(self._offset)

    def __repr__(self):
        if self is self.utc:
            return 'datetime.timezone.utc'
        if self._name is None:
            return '%s(%r)' % ('datetime.' + self.__class__.__name__, self._offset)
        return '%s(%r, %r)' % ('datetime.' + self.__class__.__name__, self._offset, self._name)

    def __str__(self):
        return self.tzname(None)

    def utcoffset(self, dt):
        if isinstance(dt, datetime) or dt is None:
            return self._offset
        raise TypeError('utcoffset() argument must be a datetime instance or None')

    def tzname(self, dt):
        if isinstance(dt, datetime) or dt is None:
            if self._name is None:
                return self._name_from_offset(self._offset)
            return self._name
        raise TypeError('tzname() argument must be a datetime instance or None')

    def dst(self, dt):
        if isinstance(dt, datetime) or dt is None:
            return
        raise TypeError('dst() argument must be a datetime instance or None')

    def fromutc(self, dt):
        if isinstance(dt, datetime):
            if dt.tzinfo is not self:
                raise ValueError('fromutc: dt.tzinfo is not self')
            return dt + self._offset
        raise TypeError('fromutc() argument must be a datetime instance or None')

    _maxoffset = timedelta(hours=23, minutes=59)
    _minoffset = -_maxoffset

    @staticmethod
    def _name_from_offset(delta):
        if delta < timedelta(0):
            sign = '-'
            delta = -delta
        else:
            sign = '+'
        (hours, rest) = divmod(delta, timedelta(hours=1))
        minutes = rest//timedelta(minutes=1)
        return 'UTC{}{:02d}:{:02d}'.format(sign, hours, minutes)

timezone.utc = timezone._create(timedelta(0))
timezone.min = timezone._create(timezone._minoffset)
timezone.max = timezone._create(timezone._maxoffset)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
try:
    from _datetime import *
except ImportError:
    pass
del _DAYNAMES
del _DAYS_BEFORE_MONTH
del _DAYS_IN_MONTH
del _DI100Y
del _DI400Y
del _DI4Y
del _MAXORDINAL
del _MONTHNAMES
del _build_struct_time
del _call_tzinfo_method
del _check_date_fields
del _check_time_fields
del _check_tzinfo_arg
del _check_tzname
del _check_utc_offset
del _cmp
del _cmperror
del _date_class
del _days_before_month
del _days_before_year
del _days_in_month
del _format_time
del _is_leap
del _isoweek1monday
del _math
del _ord2ymd
del _time
del _time_class
del _tzinfo_class
del _wrap_strftime
del _ymd2ord
from _datetime import __doc__
