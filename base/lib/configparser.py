from collections.abc import MutableMapping
from collections import OrderedDict as _default_dict, ChainMap as _ChainMap
import functools
import io
import itertools
import re
import sys
import warnings
__all__ = ['NoSectionError', 'DuplicateOptionError', 'DuplicateSectionError', 'NoOptionError', 'InterpolationError', 'InterpolationDepthError', 'InterpolationSyntaxError', 'ParsingError', 'MissingSectionHeaderError', 'ConfigParser', 'SafeConfigParser', 'RawConfigParser', 'DEFAULTSECT', 'MAX_INTERPOLATION_DEPTH']
DEFAULTSECT = 'DEFAULT'
MAX_INTERPOLATION_DEPTH = 10

class Error(Exception):
    __qualname__ = 'Error'

    def __init__(self, msg=''):
        self.message = msg
        Exception.__init__(self, msg)

    def __repr__(self):
        return self.message

    __str__ = __repr__

class NoSectionError(Error):
    __qualname__ = 'NoSectionError'

    def __init__(self, section):
        Error.__init__(self, 'No section: %r' % (section,))
        self.section = section
        self.args = (section,)

class DuplicateSectionError(Error):
    __qualname__ = 'DuplicateSectionError'

    def __init__(self, section, source=None, lineno=None):
        msg = [repr(section), ' already exists']
        if source is not None:
            message = ['While reading from ', repr(source)]
            if lineno is not None:
                message.append(' [line {0:2d}]'.format(lineno))
            message.append(': section ')
            message.extend(msg)
            msg = message
        else:
            msg.insert(0, 'Section ')
        Error.__init__(self, ''.join(msg))
        self.section = section
        self.source = source
        self.lineno = lineno
        self.args = (section, source, lineno)

class DuplicateOptionError(Error):
    __qualname__ = 'DuplicateOptionError'

    def __init__(self, section, option, source=None, lineno=None):
        msg = [repr(option), ' in section ', repr(section), ' already exists']
        if source is not None:
            message = ['While reading from ', repr(source)]
            if lineno is not None:
                message.append(' [line {0:2d}]'.format(lineno))
            message.append(': option ')
            message.extend(msg)
            msg = message
        else:
            msg.insert(0, 'Option ')
        Error.__init__(self, ''.join(msg))
        self.section = section
        self.option = option
        self.source = source
        self.lineno = lineno
        self.args = (section, option, source, lineno)

class NoOptionError(Error):
    __qualname__ = 'NoOptionError'

    def __init__(self, option, section):
        Error.__init__(self, 'No option %r in section: %r' % (option, section))
        self.option = option
        self.section = section
        self.args = (option, section)

class InterpolationError(Error):
    __qualname__ = 'InterpolationError'

    def __init__(self, option, section, msg):
        Error.__init__(self, msg)
        self.option = option
        self.section = section
        self.args = (option, section, msg)

class InterpolationMissingOptionError(InterpolationError):
    __qualname__ = 'InterpolationMissingOptionError'

    def __init__(self, option, section, rawval, reference):
        msg = 'Bad value substitution:\n\tsection: [%s]\n\toption : %s\n\tkey    : %s\n\trawval : %s\n' % (section, option, reference, rawval)
        InterpolationError.__init__(self, option, section, msg)
        self.reference = reference
        self.args = (option, section, rawval, reference)

class InterpolationSyntaxError(InterpolationError):
    __qualname__ = 'InterpolationSyntaxError'

class InterpolationDepthError(InterpolationError):
    __qualname__ = 'InterpolationDepthError'

    def __init__(self, option, section, rawval):
        msg = 'Value interpolation too deeply recursive:\n\tsection: [%s]\n\toption : %s\n\trawval : %s\n' % (section, option, rawval)
        InterpolationError.__init__(self, option, section, msg)
        self.args = (option, section, rawval)

class ParsingError(Error):
    __qualname__ = 'ParsingError'

    def __init__(self, source=None, filename=None):
        if filename and source:
            raise ValueError("Cannot specify both `filename' and `source'. Use `source'.")
        elif not filename and not source:
            raise ValueError("Required argument `source' not given.")
        elif filename:
            source = filename
        Error.__init__(self, 'Source contains parsing errors: %r' % source)
        self.source = source
        self.errors = []
        self.args = (source,)

    @property
    def filename(self):
        warnings.warn("The 'filename' attribute will be removed in future versions.  Use 'source' instead.", DeprecationWarning, stacklevel=2)
        return self.source

    @filename.setter
    def filename(self, value):
        warnings.warn("The 'filename' attribute will be removed in future versions.  Use 'source' instead.", DeprecationWarning, stacklevel=2)
        self.source = value

    def append(self, lineno, line):
        self.errors.append((lineno, line))

class MissingSectionHeaderError(ParsingError):
    __qualname__ = 'MissingSectionHeaderError'

    def __init__(self, filename, lineno, line):
        Error.__init__(self, 'File contains no section headers.\nfile: %r, line: %d\n%r' % (filename, lineno, line))
        self.source = filename
        self.lineno = lineno
        self.line = line
        self.args = (filename, lineno, line)

_UNSET = object()

class Interpolation:
    __qualname__ = 'Interpolation'

    def before_get(self, parser, section, option, value, defaults):
        return value

    def before_set(self, parser, section, option, value):
        return value

    def before_read(self, parser, section, option, value):
        return value

    def before_write(self, parser, section, option, value):
        return value

class BasicInterpolation(Interpolation):
    __qualname__ = 'BasicInterpolation'
    _KEYCRE = re.compile('%\\(([^)]+)\\)s')

    def before_get(self, parser, section, option, value, defaults):
        L = []
        self._interpolate_some(parser, option, L, value, section, defaults, 1)
        return ''.join(L)

    def before_set(self, parser, section, option, value):
        tmp_value = value.replace('%%', '')
        tmp_value = self._KEYCRE.sub('', tmp_value)
        if '%' in tmp_value:
            raise ValueError('invalid interpolation syntax in %r at position %d' % (value, tmp_value.find('%')))
        return value

    def _interpolate_some(self, parser, option, accum, rest, section, map, depth):
        if depth > MAX_INTERPOLATION_DEPTH:
            raise InterpolationDepthError(option, section, rest)
        while rest:
            p = rest.find('%')
            if p < 0:
                accum.append(rest)
                return
            if p > 0:
                accum.append(rest[:p])
                rest = rest[p:]
            c = rest[1:2]
            if c == '%':
                accum.append('%')
                rest = rest[2:]
            elif c == '(':
                m = self._KEYCRE.match(rest)
                if m is None:
                    raise InterpolationSyntaxError(option, section, 'bad interpolation variable reference %r' % rest)
                var = parser.optionxform(m.group(1))
                rest = rest[m.end():]
                try:
                    v = map[var]
                except KeyError:
                    raise InterpolationMissingOptionError(option, section, rest, var)
                if '%' in v:
                    self._interpolate_some(parser, option, accum, v, section, map, depth + 1)
                else:
                    accum.append(v)
                    continue
                    raise InterpolationSyntaxError(option, section, "'%%' must be followed by '%%' or '(', found: %r" % (rest,))
            else:
                raise InterpolationSyntaxError(option, section, "'%%' must be followed by '%%' or '(', found: %r" % (rest,))

class ExtendedInterpolation(Interpolation):
    __qualname__ = 'ExtendedInterpolation'
    _KEYCRE = re.compile('\\$\\{([^}]+)\\}')

    def before_get(self, parser, section, option, value, defaults):
        L = []
        self._interpolate_some(parser, option, L, value, section, defaults, 1)
        return ''.join(L)

    def before_set(self, parser, section, option, value):
        tmp_value = value.replace('$$', '')
        tmp_value = self._KEYCRE.sub('', tmp_value)
        if '$' in tmp_value:
            raise ValueError('invalid interpolation syntax in %r at position %d' % (value, tmp_value.find('$')))
        return value

    def _interpolate_some(self, parser, option, accum, rest, section, map, depth):
        if depth > MAX_INTERPOLATION_DEPTH:
            raise InterpolationDepthError(option, section, rest)
        while rest:
            p = rest.find('$')
            if p < 0:
                accum.append(rest)
                return
            if p > 0:
                accum.append(rest[:p])
                rest = rest[p:]
            c = rest[1:2]
            if c == '$':
                accum.append('$')
                rest = rest[2:]
            elif c == '{':
                m = self._KEYCRE.match(rest)
                if m is None:
                    raise InterpolationSyntaxError(option, section, 'bad interpolation variable reference %r' % rest)
                path = m.group(1).split(':')
                rest = rest[m.end():]
                sect = section
                opt = option
                try:
                    if len(path) == 1:
                        opt = parser.optionxform(path[0])
                        v = map[opt]
                    elif len(path) == 2:
                        sect = path[0]
                        opt = parser.optionxform(path[1])
                        v = parser.get(sect, opt, raw=True)
                    else:
                        raise InterpolationSyntaxError(option, section, "More than one ':' found: %r" % (rest,))
                except (KeyError, NoSectionError, NoOptionError):
                    raise InterpolationMissingOptionError(option, section, rest, ':'.join(path))
                if '$' in v:
                    self._interpolate_some(parser, opt, accum, v, sect, dict(parser.items(sect, raw=True)), depth + 1)
                else:
                    accum.append(v)
                    continue
                    raise InterpolationSyntaxError(option, section, "'$' must be followed by '$' or '{', found: %r" % (rest,))
            else:
                raise InterpolationSyntaxError(option, section, "'$' must be followed by '$' or '{', found: %r" % (rest,))

class LegacyInterpolation(Interpolation):
    __qualname__ = 'LegacyInterpolation'
    _KEYCRE = re.compile('%\\(([^)]*)\\)s|.')

    def before_get(self, parser, section, option, value, vars):
        rawval = value
        depth = MAX_INTERPOLATION_DEPTH
        while depth:
            depth -= 1
            if value and '%(' in value:
                replace = functools.partial(self._interpolation_replace, parser=parser)
                value = self._KEYCRE.sub(replace, value)
                try:
                    value = value % vars
                except KeyError as e:
                    raise InterpolationMissingOptionError(option, section, rawval, e.args[0])
            else:
                break
        if value and '%(' in value:
            raise InterpolationDepthError(option, section, rawval)
        return value

    def before_set(self, parser, section, option, value):
        return value

    @staticmethod
    def _interpolation_replace(match, parser):
        s = match.group(1)
        if s is None:
            return match.group()
        return '%%(%s)s' % parser.optionxform(s)

class RawConfigParser(MutableMapping):
    __qualname__ = 'RawConfigParser'
    _SECT_TMPL = '\n        \\[                                 # [\n        (?P<header>[^]]+)                  # very permissive!\n        \\]                                 # ]\n        '
    _OPT_TMPL = '\n        (?P<option>.*?)                    # very permissive!\n        \\s*(?P<vi>{delim})\\s*              # any number of space/tab,\n                                           # followed by any of the\n                                           # allowed delimiters,\n                                           # followed by any space/tab\n        (?P<value>.*)$                     # everything up to eol\n        '
    _OPT_NV_TMPL = '\n        (?P<option>.*?)                    # very permissive!\n        \\s*(?:                             # any number of space/tab,\n        (?P<vi>{delim})\\s*                 # optionally followed by\n                                           # any of the allowed\n                                           # delimiters, followed by any\n                                           # space/tab\n        (?P<value>.*))?$                   # everything up to eol\n        '
    _DEFAULT_INTERPOLATION = Interpolation()
    SECTCRE = re.compile(_SECT_TMPL, re.VERBOSE)
    OPTCRE = re.compile(_OPT_TMPL.format(delim='=|:'), re.VERBOSE)
    OPTCRE_NV = re.compile(_OPT_NV_TMPL.format(delim='=|:'), re.VERBOSE)
    NONSPACECRE = re.compile('\\S')
    BOOLEAN_STATES = {'1': True, 'yes': True, 'true': True, 'on': True, '0': False, 'no': False, 'false': False, 'off': False}

    def __init__(self, defaults=None, dict_type=_default_dict, allow_no_value=False, *, delimiters=('=', ':'), comment_prefixes=('#', ';'), inline_comment_prefixes=None, strict=True, empty_lines_in_values=True, default_section=DEFAULTSECT, interpolation=_UNSET):
        self._dict = dict_type
        self._sections = self._dict()
        self._defaults = self._dict()
        self._proxies = self._dict()
        self._proxies[default_section] = SectionProxy(self, default_section)
        if defaults:
            for (key, value) in defaults.items():
                self._defaults[self.optionxform(key)] = value
        self._delimiters = tuple(delimiters)
        if delimiters == ('=', ':'):
            self._optcre = self.OPTCRE_NV if allow_no_value else self.OPTCRE
        else:
            d = '|'.join(re.escape(d) for d in delimiters)
            if allow_no_value:
                self._optcre = re.compile(self._OPT_NV_TMPL.format(delim=d), re.VERBOSE)
            else:
                self._optcre = re.compile(self._OPT_TMPL.format(delim=d), re.VERBOSE)
        self._comment_prefixes = tuple(comment_prefixes or ())
        self._inline_comment_prefixes = tuple(inline_comment_prefixes or ())
        self._strict = strict
        self._allow_no_value = allow_no_value
        self._empty_lines_in_values = empty_lines_in_values
        self.default_section = default_section
        self._interpolation = interpolation
        if self._interpolation is _UNSET:
            self._interpolation = self._DEFAULT_INTERPOLATION
        if self._interpolation is None:
            self._interpolation = Interpolation()

    def defaults(self):
        return self._defaults

    def sections(self):
        return list(self._sections.keys())

    def add_section(self, section):
        if section == self.default_section:
            raise ValueError('Invalid section name: %r' % section)
        if section in self._sections:
            raise DuplicateSectionError(section)
        self._sections[section] = self._dict()
        self._proxies[section] = SectionProxy(self, section)

    def has_section(self, section):
        return section in self._sections

    def options(self, section):
        try:
            opts = self._sections[section].copy()
        except KeyError:
            raise NoSectionError(section)
        opts.update(self._defaults)
        return list(opts.keys())

    def read(self, filenames, encoding=None):
        if isinstance(filenames, str):
            filenames = [filenames]
        read_ok = []
        for filename in filenames:
            try:
                with open(filename, encoding=encoding) as fp:
                    self._read(fp, filename)
            except IOError:
                continue
            read_ok.append(filename)
        return read_ok

    def read_file(self, f, source=None):
        if source is None:
            try:
                source = f.name
            except AttributeError:
                source = '<???>'
        self._read(f, source)

    def read_string(self, string, source='<string>'):
        sfile = io.StringIO(string)
        self.read_file(sfile, source)

    def read_dict(self, dictionary, source='<dict>'):
        elements_added = set()
        for (section, keys) in dictionary.items():
            section = str(section)
            try:
                self.add_section(section)
            except (DuplicateSectionError, ValueError):
                if self._strict and section in elements_added:
                    raise
            elements_added.add(section)
            for (key, value) in keys.items():
                key = self.optionxform(str(key))
                if value is not None:
                    value = str(value)
                if self._strict and (section, key) in elements_added:
                    raise DuplicateOptionError(section, key, source)
                elements_added.add((section, key))
                self.set(section, key, value)

    def readfp(self, fp, filename=None):
        warnings.warn("This method will be removed in future versions.  Use 'parser.read_file()' instead.", DeprecationWarning, stacklevel=2)
        self.read_file(fp, source=filename)

    def get(self, section, option, *, raw=False, vars=None, fallback=_UNSET):
        try:
            d = self._unify_values(section, vars)
        except NoSectionError:
            if fallback is _UNSET:
                raise
            else:
                return fallback
        option = self.optionxform(option)
        try:
            value = d[option]
        except KeyError:
            if fallback is _UNSET:
                raise NoOptionError(option, section)
            else:
                return fallback
        if raw or value is None:
            return value
        return self._interpolation.before_get(self, section, option, value, d)

    def _get(self, section, conv, option, **kwargs):
        return conv(self.get(section, option, **kwargs))

    def getint(self, section, option, *, raw=False, vars=None, fallback=_UNSET):
        try:
            return self._get(section, int, option, raw=raw, vars=vars)
        except (NoSectionError, NoOptionError):
            if fallback is _UNSET:
                raise
            else:
                return fallback

    def getfloat(self, section, option, *, raw=False, vars=None, fallback=_UNSET):
        try:
            return self._get(section, float, option, raw=raw, vars=vars)
        except (NoSectionError, NoOptionError):
            if fallback is _UNSET:
                raise
            else:
                return fallback

    def getboolean(self, section, option, *, raw=False, vars=None, fallback=_UNSET):
        try:
            return self._get(section, self._convert_to_boolean, option, raw=raw, vars=vars)
        except (NoSectionError, NoOptionError):
            if fallback is _UNSET:
                raise
            else:
                return fallback

    def items(self, section=_UNSET, raw=False, vars=None):
        if section is _UNSET:
            return super().items()
        d = self._defaults.copy()
        try:
            d.update(self._sections[section])
        except KeyError:
            if section != self.default_section:
                raise NoSectionError(section)
        if vars:
            for (key, value) in vars.items():
                d[self.optionxform(key)] = value
        value_getter = lambda option: self._interpolation.before_get(self, section, option, d[option], d)
        if raw:
            value_getter = lambda option: d[option]
        return [(option, value_getter(option)) for option in d.keys()]

    def popitem(self):
        for key in self.sections():
            value = self[key]
            del self[key]
        raise KeyError

    def optionxform(self, optionstr):
        return optionstr.lower()

    def has_option(self, section, option):
        if not section or section == self.default_section:
            option = self.optionxform(option)
            return option in self._defaults
        if section not in self._sections:
            return False
        option = self.optionxform(option)
        return option in self._sections[section] or option in self._defaults

    def set(self, section, option, value=None):
        if value:
            value = self._interpolation.before_set(self, section, option, value)
        if not section or section == self.default_section:
            sectdict = self._defaults
        else:
            try:
                sectdict = self._sections[section]
            except KeyError:
                raise NoSectionError(section)
        sectdict[self.optionxform(option)] = value

    def write(self, fp, space_around_delimiters=True):
        if space_around_delimiters:
            d = ' {} '.format(self._delimiters[0])
        else:
            d = self._delimiters[0]
        if self._defaults:
            self._write_section(fp, self.default_section, self._defaults.items(), d)
        for section in self._sections:
            self._write_section(fp, section, self._sections[section].items(), d)

    def _write_section(self, fp, section_name, section_items, delimiter):
        fp.write('[{}]\n'.format(section_name))
        for (key, value) in section_items:
            value = self._interpolation.before_write(self, section_name, key, value)
            if value is not None or not self._allow_no_value:
                value = delimiter + str(value).replace('\n', '\n\t')
            else:
                value = ''
            fp.write('{}{}\n'.format(key, value))
        fp.write('\n')

    def remove_option(self, section, option):
        if not section or section == self.default_section:
            sectdict = self._defaults
        else:
            try:
                sectdict = self._sections[section]
            except KeyError:
                raise NoSectionError(section)
        option = self.optionxform(option)
        existed = option in sectdict
        if existed:
            del sectdict[option]
        return existed

    def remove_section(self, section):
        existed = section in self._sections
        if existed:
            del self._sections[section]
            del self._proxies[section]
        return existed

    def __getitem__(self, key):
        if key != self.default_section and not self.has_section(key):
            raise KeyError(key)
        return self._proxies[key]

    def __setitem__(self, key, value):
        if key == self.default_section:
            self._defaults.clear()
        elif key in self._sections:
            self._sections[key].clear()
        self.read_dict({key: value})

    def __delitem__(self, key):
        if key == self.default_section:
            raise ValueError('Cannot remove the default section.')
        if not self.has_section(key):
            raise KeyError(key)
        self.remove_section(key)

    def __contains__(self, key):
        return key == self.default_section or self.has_section(key)

    def __len__(self):
        return len(self._sections) + 1

    def __iter__(self):
        return itertools.chain((self.default_section,), self._sections.keys())

    def _read(self, fp, fpname):
        elements_added = set()
        cursect = None
        sectname = None
        optname = None
        lineno = 0
        indent_level = 0
        e = None
        for (lineno, line) in enumerate(fp, start=1):
            comment_start = sys.maxsize
            inline_prefixes = {p: -1 for p in self._inline_comment_prefixes}
            while comment_start == sys.maxsize:
                while inline_prefixes:
                    next_prefixes = {}
                    for (prefix, index) in inline_prefixes.items():
                        index = line.find(prefix, index + 1)
                        if index == -1:
                            pass
                        next_prefixes[prefix] = index
                        while (index == 0 or index > 0) and line[index - 1].isspace():
                            comment_start = min(comment_start, index)
                    inline_prefixes = next_prefixes
            for prefix in self._comment_prefixes:
                while line.strip().startswith(prefix):
                    comment_start = 0
                    break
            if comment_start == sys.maxsize:
                comment_start = None
            value = line[:comment_start].strip()
            if not value:
                if self._empty_lines_in_values:
                    cursect[optname].append('')
                else:
                    indent_level = sys.maxsize
                    first_nonspace = self.NONSPACECRE.search(line)
                    cur_indent_level = first_nonspace.start() if first_nonspace else 0
                    if cursect is not None and optname and cur_indent_level > indent_level:
                        cursect[optname].append(value)
                    else:
                        indent_level = cur_indent_level
                        mo = self.SECTCRE.match(value)
                        if mo:
                            sectname = mo.group('header')
                            if sectname in self._sections:
                                if self._strict and sectname in elements_added:
                                    raise DuplicateSectionError(sectname, fpname, lineno)
                                cursect = self._sections[sectname]
                                elements_added.add(sectname)
                            elif sectname == self.default_section:
                                cursect = self._defaults
                            else:
                                cursect = self._dict()
                                self._sections[sectname] = cursect
                                self._proxies[sectname] = SectionProxy(self, sectname)
                                elements_added.add(sectname)
                            optname = None
                        elif cursect is None:
                            raise MissingSectionHeaderError(fpname, lineno, line)
                        else:
                            mo = self._optcre.match(value)
                            if mo:
                                (optname, vi, optval) = mo.group('option', 'vi', 'value')
                                if not optname:
                                    e = self._handle_error(e, fpname, lineno, line)
                                optname = self.optionxform(optname.rstrip())
                                if self._strict and (sectname, optname) in elements_added:
                                    raise DuplicateOptionError(sectname, optname, fpname, lineno)
                                elements_added.add((sectname, optname))
                                if optval is not None:
                                    optval = optval.strip()
                                    cursect[optname] = [optval]
                                else:
                                    cursect[optname] = None
                                    e = self._handle_error(e, fpname, lineno, line)
                            else:
                                e = self._handle_error(e, fpname, lineno, line)
            first_nonspace = self.NONSPACECRE.search(line)
            cur_indent_level = first_nonspace.start() if first_nonspace else 0
            if cursect is not None and optname and cur_indent_level > indent_level:
                cursect[optname].append(value)
            else:
                indent_level = cur_indent_level
                mo = self.SECTCRE.match(value)
                if mo:
                    sectname = mo.group('header')
                    if sectname in self._sections:
                        if self._strict and sectname in elements_added:
                            raise DuplicateSectionError(sectname, fpname, lineno)
                        cursect = self._sections[sectname]
                        elements_added.add(sectname)
                    elif sectname == self.default_section:
                        cursect = self._defaults
                    else:
                        cursect = self._dict()
                        self._sections[sectname] = cursect
                        self._proxies[sectname] = SectionProxy(self, sectname)
                        elements_added.add(sectname)
                    optname = None
                elif cursect is None:
                    raise MissingSectionHeaderError(fpname, lineno, line)
                else:
                    mo = self._optcre.match(value)
                    if mo:
                        (optname, vi, optval) = mo.group('option', 'vi', 'value')
                        if not optname:
                            e = self._handle_error(e, fpname, lineno, line)
                        optname = self.optionxform(optname.rstrip())
                        if self._strict and (sectname, optname) in elements_added:
                            raise DuplicateOptionError(sectname, optname, fpname, lineno)
                        elements_added.add((sectname, optname))
                        if optval is not None:
                            optval = optval.strip()
                            cursect[optname] = [optval]
                        else:
                            cursect[optname] = None
                            e = self._handle_error(e, fpname, lineno, line)
                    else:
                        e = self._handle_error(e, fpname, lineno, line)
        if e:
            raise e
        self._join_multiline_values()

    def _join_multiline_values(self):
        defaults = (self.default_section, self._defaults)
        all_sections = itertools.chain((defaults,), self._sections.items())
        for (section, options) in all_sections:
            for (name, val) in options.items():
                if isinstance(val, list):
                    val = '\n'.join(val).rstrip()
                options[name] = self._interpolation.before_read(self, section, name, val)

    def _handle_error(self, exc, fpname, lineno, line):
        if not exc:
            exc = ParsingError(fpname)
        exc.append(lineno, repr(line))
        return exc

    def _unify_values(self, section, vars):
        sectiondict = {}
        try:
            sectiondict = self._sections[section]
        except KeyError:
            if section != self.default_section:
                raise NoSectionError(section)
        vardict = {}
        if vars:
            for (key, value) in vars.items():
                if value is not None:
                    value = str(value)
                vardict[self.optionxform(key)] = value
        return _ChainMap(vardict, sectiondict, self._defaults)

    def _convert_to_boolean(self, value):
        if value.lower() not in self.BOOLEAN_STATES:
            raise ValueError('Not a boolean: %s' % value)
        return self.BOOLEAN_STATES[value.lower()]

    def _validate_value_types(self, *, section='', option='', value=''):
        if not isinstance(section, str):
            raise TypeError('section names must be strings')
        if not isinstance(option, str):
            raise TypeError('option keys must be strings')
        if not ((not self._allow_no_value or value) and isinstance(value, str)):
            raise TypeError('option values must be strings')

class ConfigParser(RawConfigParser):
    __qualname__ = 'ConfigParser'
    _DEFAULT_INTERPOLATION = BasicInterpolation()

    def set(self, section, option, value=None):
        self._validate_value_types(option=option, value=value)
        super().set(section, option, value)

    def add_section(self, section):
        self._validate_value_types(section=section)
        super().add_section(section)

class SafeConfigParser(ConfigParser):
    __qualname__ = 'SafeConfigParser'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        warnings.warn('The SafeConfigParser class has been renamed to ConfigParser in Python 3.2. This alias will be removed in future versions. Use ConfigParser directly instead.', DeprecationWarning, stacklevel=2)

class SectionProxy(MutableMapping):
    __qualname__ = 'SectionProxy'

    def __init__(self, parser, name):
        self._parser = parser
        self._name = name

    def __repr__(self):
        return '<Section: {}>'.format(self._name)

    def __getitem__(self, key):
        if not self._parser.has_option(self._name, key):
            raise KeyError(key)
        return self._parser.get(self._name, key)

    def __setitem__(self, key, value):
        self._parser._validate_value_types(option=key, value=value)
        return self._parser.set(self._name, key, value)

    def __delitem__(self, key):
        if not (self._parser.has_option(self._name, key) and self._parser.remove_option(self._name, key)):
            raise KeyError(key)

    def __contains__(self, key):
        return self._parser.has_option(self._name, key)

    def __len__(self):
        return len(self._options())

    def __iter__(self):
        return self._options().__iter__()

    def _options(self):
        if self._name != self._parser.default_section:
            return self._parser.options(self._name)
        return self._parser.defaults()

    def get(self, option, fallback=None, *, raw=False, vars=None):
        return self._parser.get(self._name, option, raw=raw, vars=vars, fallback=fallback)

    def getint(self, option, fallback=None, *, raw=False, vars=None):
        return self._parser.getint(self._name, option, raw=raw, vars=vars, fallback=fallback)

    def getfloat(self, option, fallback=None, *, raw=False, vars=None):
        return self._parser.getfloat(self._name, option, raw=raw, vars=vars, fallback=fallback)

    def getboolean(self, option, fallback=None, *, raw=False, vars=None):
        return self._parser.getboolean(self._name, option, raw=raw, vars=vars, fallback=fallback)

    @property
    def parser(self):
        return self._parser

    @property
    def name(self):
        return self._name

