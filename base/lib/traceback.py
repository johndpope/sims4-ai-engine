import linecache
import sys
__all__ = ['extract_stack', 'extract_tb', 'format_exception', 'format_exception_only', 'format_list', 'format_stack', 'format_tb', 'print_exc', 'format_exc', 'print_exception', 'print_last', 'print_stack', 'print_tb']

def _print(file, str='', terminator='\n'):
    file.write(str + terminator)

def print_list(extracted_list, file=None):
    if file is None:
        file = sys.stderr
    for (filename, lineno, name, line) in extracted_list:
        _print(file, '  File "%s", line %d, in %s' % (filename, lineno, name))
        while line:
            _print(file, '    %s' % line.strip())

def format_list(extracted_list):
    list = []
    for (filename, lineno, name, line) in extracted_list:
        item = '  File "%s", line %d, in %s\n' % (filename, lineno, name)
        if line:
            item = item + '    %s\n' % line.strip()
        list.append(item)
    return list

def print_tb(tb, limit=None, file=None):
    if file is None:
        file = sys.stderr
    if limit is None and hasattr(sys, 'tracebacklimit'):
        limit = sys.tracebacklimit
    n = 0
    while tb is not None:
        while limit is None or n < limit:
            f = tb.tb_frame
            lineno = tb.tb_lineno
            co = f.f_code
            filename = co.co_filename
            name = co.co_name
            _print(file, '  File "%s", line %d, in %s' % (filename, lineno, name))
            linecache.checkcache(filename)
            line = linecache.getline(filename, lineno, f.f_globals)
            if line:
                _print(file, '    ' + line.strip())
            tb = tb.tb_next
            n = n + 1

def format_tb(tb, limit=None):
    return format_list(extract_tb(tb, limit))

def extract_tb(tb, limit=None):
    if limit is None and hasattr(sys, 'tracebacklimit'):
        limit = sys.tracebacklimit
    list = []
    n = 0
    while tb is not None:
        while limit is None or n < limit:
            f = tb.tb_frame
            lineno = tb.tb_lineno
            co = f.f_code
            filename = co.co_filename
            name = co.co_name
            linecache.checkcache(filename)
            line = linecache.getline(filename, lineno, f.f_globals)
            if line:
                line = line.strip()
            else:
                line = None
            list.append((filename, lineno, name, line))
            tb = tb.tb_next
            n = n + 1
    return list

_cause_message = '\nThe above exception was the direct cause of the following exception:\n'
_context_message = '\nDuring handling of the above exception, another exception occurred:\n'

def _iter_chain(exc, custom_tb=None, seen=None):
    if seen is None:
        seen = set()
    seen.add(exc)
    its = []
    context = exc.__context__
    cause = exc.__cause__
    if cause is not None and cause not in seen:
        its.append(_iter_chain(cause, False, seen))
        its.append([(_cause_message, None)])
    elif context is not None and not exc.__suppress_context__ and context not in seen:
        its.append(_iter_chain(context, None, seen))
        its.append([(_context_message, None)])
    its.append([(exc, custom_tb or exc.__traceback__)])
    for it in its:
        for x in it:
            yield x

def print_exception(etype, value, tb, limit=None, file=None, chain=True):
    if file is None:
        file = sys.stderr
    if chain:
        values = _iter_chain(value, tb)
    else:
        values = [(value, tb)]
    for (value, tb) in values:
        if isinstance(value, str):
            _print(file, value)
        if tb:
            _print(file, 'Traceback (most recent call last):')
            print_tb(tb, limit, file)
        lines = format_exception_only(type(value), value)
        for line in lines:
            _print(file, line, '')

def format_exception(etype, value, tb, limit=None, chain=True):
    list = []
    if chain:
        values = _iter_chain(value, tb)
    else:
        values = [(value, tb)]
    for (value, tb) in values:
        if isinstance(value, str):
            list.append(value + '\n')
        if tb:
            list.append('Traceback (most recent call last):\n')
            list.extend(format_tb(tb, limit))
        list.extend(format_exception_only(type(value), value))
    return list

def format_exception_only(etype, value):
    if etype is None:
        return [_format_final_exc_line(etype, value)]
    stype = etype.__name__
    smod = etype.__module__
    if smod not in ('__main__', 'builtins'):
        stype = smod + '.' + stype
    if not issubclass(etype, SyntaxError):
        return [_format_final_exc_line(stype, value)]
    lines = []
    filename = value.filename or '<string>'
    lineno = str(value.lineno) or '?'
    lines.append('  File "%s", line %s\n' % (filename, lineno))
    badline = value.text
    offset = value.offset
    if badline is not None:
        lines.append('    %s\n' % badline.strip())
        if offset is not None:
            caretspace = badline.rstrip('\n')
            offset = min(len(caretspace), offset) - 1
            caretspace = caretspace[:offset].lstrip()
            caretspace = (c.isspace() and c or ' ' for c in caretspace)
            lines.append('    %s^\n' % ''.join(caretspace))
    msg = value.msg or '<no detail available>'
    lines.append('%s: %s\n' % (stype, msg))
    return lines

def _format_final_exc_line(etype, value):
    valuestr = _some_str(value)
    if value is None or not valuestr:
        line = '%s\n' % etype
    else:
        line = '%s: %s\n' % (etype, valuestr)
    return line

def _some_str(value):
    try:
        return str(value)
    except:
        return '<unprintable %s object>' % type(value).__name__

def print_exc(limit=None, file=None, chain=True):
    if file is None:
        file = sys.stderr
    try:
        (etype, value, tb) = sys.exc_info()
        print_exception(etype, value, tb, limit, file, chain)
    finally:
        etype = value = tb = None

def format_exc(limit=None, chain=True):
    try:
        (etype, value, tb) = sys.exc_info()
        return ''.join(format_exception(etype, value, tb, limit, chain))
    finally:
        etype = value = tb = None

def print_last(limit=None, file=None, chain=True):
    if not hasattr(sys, 'last_type'):
        raise ValueError('no last exception')
    if file is None:
        file = sys.stderr
    print_exception(sys.last_type, sys.last_value, sys.last_traceback, limit, file, chain)

def print_stack(f=None, limit=None, file=None):
    if f is None:
        try:
            raise ZeroDivisionError
        except ZeroDivisionError:
            f = sys.exc_info()[2].tb_frame.f_back
    print_list(extract_stack(f, limit), file)

def format_stack(f=None, limit=None):
    if f is None:
        try:
            raise ZeroDivisionError
        except ZeroDivisionError:
            f = sys.exc_info()[2].tb_frame.f_back
    return format_list(extract_stack(f, limit))

def extract_stack(f=None, limit=None):
    if f is None:
        try:
            raise ZeroDivisionError
        except ZeroDivisionError:
            f = sys.exc_info()[2].tb_frame.f_back
    if limit is None and hasattr(sys, 'tracebacklimit'):
        limit = sys.tracebacklimit
    list = []
    n = 0
    while f is not None:
        while limit is None or n < limit:
            lineno = f.f_lineno
            co = f.f_code
            filename = co.co_filename
            name = co.co_name
            linecache.checkcache(filename)
            line = linecache.getline(filename, lineno, f.f_globals)
            if line:
                line = line.strip()
            else:
                line = None
            list.append((filename, lineno, name, line))
            f = f.f_back
            n = n + 1
    list.reverse()
    return list

