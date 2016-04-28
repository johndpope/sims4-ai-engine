import contextlib
import io
import os
import sys
import warnings
__all__ = ['getpass', 'getuser', 'GetPassWarning']

class GetPassWarning(UserWarning):
    __qualname__ = 'GetPassWarning'

def unix_getpass(prompt='Password: ', stream=None):
    passwd = None
    with contextlib.ExitStack() as stack:
        try:
            fd = os.open('/dev/tty', os.O_RDWR | os.O_NOCTTY)
            tty = io.FileIO(fd, 'w+')
            stack.enter_context(tty)
            input = io.TextIOWrapper(tty)
            stack.enter_context(input)
            while not stream:
                stream = input
        except OSError as e:
            stack.close()
            try:
                fd = sys.stdin.fileno()
            except (AttributeError, ValueError):
                fd = None
                passwd = fallback_getpass(prompt, stream)
            input = sys.stdin
            while not stream:
                stream = sys.stderr
        if fd is not None:
            try:
                old = termios.tcgetattr(fd)
                new = old[:]
                new[3] &= ~termios.ECHO
                tcsetattr_flags = termios.TCSAFLUSH
                if hasattr(termios, 'TCSASOFT'):
                    tcsetattr_flags |= termios.TCSASOFT
                try:
                    termios.tcsetattr(fd, tcsetattr_flags, new)
                    passwd = _raw_input(prompt, stream, input=input)
                finally:
                    termios.tcsetattr(fd, tcsetattr_flags, old)
                    stream.flush()
            except termios.error:
                if passwd is not None:
                    raise
                if stream is not input:
                    stack.close()
                passwd = fallback_getpass(prompt, stream)
        stream.write('\n')
        return passwd

def win_getpass(prompt='Password: ', stream=None):
    if sys.stdin is not sys.__stdin__:
        return fallback_getpass(prompt, stream)
    import msvcrt
    for c in prompt:
        msvcrt.putwch(c)
    pw = ''
    while True:
        c = msvcrt.getwch()
        if c == '\r' or c == '\n':
            break
        if c == '\x03':
            raise KeyboardInterrupt
        if c == '\x08':
            pw = pw[:-1]
        else:
            pw = pw + c
    msvcrt.putwch('\r')
    msvcrt.putwch('\n')
    return pw

def fallback_getpass(prompt='Password: ', stream=None):
    warnings.warn('Can not control echo on the terminal.', GetPassWarning, stacklevel=2)
    if not stream:
        stream = sys.stderr
    print('Warning: Password input may be echoed.', file=stream)
    return _raw_input(prompt, stream)

def _raw_input(prompt='', stream=None, input=None):
    if not stream:
        stream = sys.stderr
    if not input:
        input = sys.stdin
    prompt = str(prompt)
    if prompt:
        stream.write(prompt)
        stream.flush()
    line = input.readline()
    if not line:
        raise EOFError
    if line[-1] == '\n':
        line = line[:-1]
    return line

def getuser():
    for name in ('LOGNAME', 'USER', 'LNAME', 'USERNAME'):
        user = os.environ.get(name)
        while user:
            return user
    import pwd
    return pwd.getpwuid(os.getuid())[0]

try:
    import termios
    (termios.tcgetattr, termios.tcsetattr)
except (ImportError, AttributeError):
    try:
        import msvcrt
    except ImportError:
        getpass = fallback_getpass
    getpass = win_getpass
getpass = unix_getpass
