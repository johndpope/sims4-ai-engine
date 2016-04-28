import sys
mswindows = sys.platform == 'win32'
import io
import os
import time
import traceback
import gc
import signal
import builtins
import warnings
import errno
try:
    from time import monotonic as _time
except ImportError:
    from time import time as _time

class SubprocessError(Exception):
    __qualname__ = 'SubprocessError'

class CalledProcessError(SubprocessError):
    __qualname__ = 'CalledProcessError'

    def __init__(self, returncode, cmd, output=None):
        self.returncode = returncode
        self.cmd = cmd
        self.output = output

    def __str__(self):
        return "Command '%s' returned non-zero exit status %d" % (self.cmd, self.returncode)

class TimeoutExpired(SubprocessError):
    __qualname__ = 'TimeoutExpired'

    def __init__(self, cmd, timeout, output=None):
        self.cmd = cmd
        self.timeout = timeout
        self.output = output

    def __str__(self):
        return "Command '%s' timed out after %s seconds" % (self.cmd, self.timeout)

if mswindows:
    import threading
    import msvcrt
    import _winapi

    class STARTUPINFO:
        __qualname__ = 'STARTUPINFO'
        dwFlags = 0
        hStdInput = None
        hStdOutput = None
        hStdError = None
        wShowWindow = 0

    class pywintypes:
        __qualname__ = 'pywintypes'
        error = IOError

else:
    import select
    _has_poll = hasattr(select, 'poll')
    import _posixsubprocess
    _create_pipe = _posixsubprocess.cloexec_pipe
    _PIPE_BUF = getattr(select, 'PIPE_BUF', 512)
__all__ = ['Popen', 'PIPE', 'STDOUT', 'call', 'check_call', 'getstatusoutput', 'getoutput', 'check_output', 'CalledProcessError', 'DEVNULL']
if mswindows:
    from _winapi import CREATE_NEW_CONSOLE, CREATE_NEW_PROCESS_GROUP, STD_INPUT_HANDLE, STD_OUTPUT_HANDLE, STD_ERROR_HANDLE, SW_HIDE, STARTF_USESTDHANDLES, STARTF_USESHOWWINDOW
    __all__.extend(['CREATE_NEW_CONSOLE', 'CREATE_NEW_PROCESS_GROUP', 'STD_INPUT_HANDLE', 'STD_OUTPUT_HANDLE', 'STD_ERROR_HANDLE', 'SW_HIDE', 'STARTF_USESTDHANDLES', 'STARTF_USESHOWWINDOW'])

    class Handle(int):
        __qualname__ = 'Handle'
        closed = False

        def Close(self, CloseHandle=_winapi.CloseHandle):
            if not self.closed:
                self.closed = True
                CloseHandle(self)

        def Detach(self):
            if not self.closed:
                self.closed = True
                return int(self)
            raise ValueError('already closed')

        def __repr__(self):
            return 'Handle(%d)' % int(self)

        __del__ = Close
        __str__ = __repr__

try:
    MAXFD = os.sysconf('SC_OPEN_MAX')
except:
    MAXFD = 256
_active = []

def _cleanup():
    for inst in _active[:]:
        res = inst._internal_poll(_deadstate=sys.maxsize)
        while res is not None:
            try:
                _active.remove(inst)
            except ValueError:
                pass

PIPE = -1
STDOUT = -2
DEVNULL = -3

def _eintr_retry_call(func, *args):
    while True:
        try:
            return func(*args)
        except InterruptedError:
            continue

def _args_from_interpreter_flags():
    flag_opt_map = {'debug': 'd', 'optimize': 'O', 'dont_write_bytecode': 'B', 'no_user_site': 's', 'no_site': 'S', 'ignore_environment': 'E', 'verbose': 'v', 'bytes_warning': 'b', 'quiet': 'q', 'hash_randomization': 'R'}
    args = []
    for (flag, opt) in flag_opt_map.items():
        v = getattr(sys.flags, flag)
        while v > 0:
            args.append('-' + opt*v)
    for opt in sys.warnoptions:
        args.append('-W' + opt)
    return args

def call(*popenargs, timeout=None, **kwargs):
    with Popen(*popenargs, **kwargs) as p:
        try:
            return p.wait(timeout=timeout)
        except:
            p.kill()
            p.wait()
            raise

def check_call(*popenargs, **kwargs):
    retcode = call(*popenargs, **kwargs)
    if retcode:
        cmd = kwargs.get('args')
        if cmd is None:
            cmd = popenargs[0]
        raise CalledProcessError(retcode, cmd)
    return 0

def check_output(*popenargs, timeout=None, **kwargs):
    if 'stdout' in kwargs:
        raise ValueError('stdout argument not allowed, it will be overridden.')
    with Popen(stdout=PIPE, *popenargs, **kwargs) as process:
        try:
            (output, unused_err) = process.communicate(timeout=timeout)
        except TimeoutExpired:
            process.kill()
            (output, unused_err) = process.communicate()
            raise TimeoutExpired(process.args, timeout, output=output)
        except:
            process.kill()
            process.wait()
            raise
        retcode = process.poll()
        while retcode:
            raise CalledProcessError(retcode, process.args, output=output)
    return output

def list2cmdline(seq):
    result = []
    needquote = False
    for arg in seq:
        bs_buf = []
        if result:
            result.append(' ')
        needquote = ' ' in arg or ('\t' in arg or not arg)
        if needquote:
            result.append('"')
        for c in arg:
            if c == '\\':
                bs_buf.append(c)
            elif c == '"':
                result.append('\\'*len(bs_buf)*2)
                bs_buf = []
                result.append('\\"')
            else:
                if bs_buf:
                    result.extend(bs_buf)
                    bs_buf = []
                result.append(c)
        if bs_buf:
            result.extend(bs_buf)
        while needquote:
            result.extend(bs_buf)
            result.append('"')
    return ''.join(result)

def getstatusoutput(cmd):
    try:
        data = check_output(cmd, shell=True, universal_newlines=True, stderr=STDOUT)
        status = 0
    except CalledProcessError as ex:
        data = ex.output
        status = ex.returncode
    if data[-1:] == '\n':
        data = data[:-1]
    return (status, data)

def getoutput(cmd):
    return getstatusoutput(cmd)[1]

_PLATFORM_DEFAULT_CLOSE_FDS = object()

class Popen(object):
    __qualname__ = 'Popen'
    _child_created = False

    def __init__(self, args, bufsize=-1, executable=None, stdin=None, stdout=None, stderr=None, preexec_fn=None, close_fds=_PLATFORM_DEFAULT_CLOSE_FDS, shell=False, cwd=None, env=None, universal_newlines=False, startupinfo=None, creationflags=0, restore_signals=True, start_new_session=False, pass_fds=()):
        _cleanup()
        self._input = None
        self._communication_started = False
        if bufsize is None:
            bufsize = -1
        if not isinstance(bufsize, int):
            raise TypeError('bufsize must be an integer')
        if mswindows:
            if preexec_fn is not None:
                raise ValueError('preexec_fn is not supported on Windows platforms')
            any_stdio_set = stdin is not None or (stdout is not None or stderr is not None)
            if close_fds is _PLATFORM_DEFAULT_CLOSE_FDS:
                if any_stdio_set:
                    close_fds = False
                else:
                    close_fds = True
                    if close_fds and any_stdio_set:
                        raise ValueError('close_fds is not supported on Windows platforms if you redirect stdin/stdout/stderr')
            elif close_fds and any_stdio_set:
                raise ValueError('close_fds is not supported on Windows platforms if you redirect stdin/stdout/stderr')
        else:
            if close_fds is _PLATFORM_DEFAULT_CLOSE_FDS:
                close_fds = True
            if pass_fds and not close_fds:
                warnings.warn('pass_fds overriding close_fds.', RuntimeWarning)
                close_fds = True
            if startupinfo is not None:
                raise ValueError('startupinfo is only supported on Windows platforms')
            if creationflags != 0:
                raise ValueError('creationflags is only supported on Windows platforms')
        self.args = args
        self.stdin = None
        self.stdout = None
        self.stderr = None
        self.pid = None
        self.returncode = None
        self.universal_newlines = universal_newlines
        (p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite) = self._get_handles(stdin, stdout, stderr)
        if p2cwrite != -1:
            p2cwrite = msvcrt.open_osfhandle(p2cwrite.Detach(), 0)
        if c2pread != -1:
            c2pread = msvcrt.open_osfhandle(c2pread.Detach(), 0)
        if mswindows and errread != -1:
            errread = msvcrt.open_osfhandle(errread.Detach(), 0)
        if p2cwrite != -1:
            self.stdin = io.open(p2cwrite, 'wb', bufsize)
            if universal_newlines:
                self.stdin = io.TextIOWrapper(self.stdin, write_through=True)
        if c2pread != -1:
            self.stdout = io.open(c2pread, 'rb', bufsize)
            if universal_newlines:
                self.stdout = io.TextIOWrapper(self.stdout)
        if errread != -1:
            self.stderr = io.open(errread, 'rb', bufsize)
            if universal_newlines:
                self.stderr = io.TextIOWrapper(self.stderr)
        self._closed_child_pipe_fds = False
        try:
            self._execute_child(args, executable, preexec_fn, close_fds, pass_fds, cwd, env, startupinfo, creationflags, shell, p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite, restore_signals, start_new_session)
        except:
            for f in filter(None, (self.stdin, self.stdout, self.stderr)):
                try:
                    f.close()
                except EnvironmentError:
                    pass
            if not self._closed_child_pipe_fds:
                to_close = []
                if stdin == PIPE:
                    to_close.append(p2cread)
                if stdout == PIPE:
                    to_close.append(c2pwrite)
                if stderr == PIPE:
                    to_close.append(errwrite)
                if hasattr(self, '_devnull'):
                    to_close.append(self._devnull)
                for fd in to_close:
                    try:
                        os.close(fd)
                    except EnvironmentError:
                        pass
            raise

    def _translate_newlines(self, data, encoding):
        data = data.decode(encoding)
        return data.replace('\r\n', '\n').replace('\r', '\n')

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        if self.stdout:
            self.stdout.close()
        if self.stderr:
            self.stderr.close()
        if self.stdin:
            self.stdin.close()
        self.wait()

    def __del__(self, _maxsize=sys.maxsize):
        if not self._child_created:
            return
        self._internal_poll(_deadstate=_maxsize)
        if self.returncode is None and _active is not None:
            _active.append(self)

    def _get_devnull(self):
        if not hasattr(self, '_devnull'):
            self._devnull = os.open(os.devnull, os.O_RDWR)
        return self._devnull

    def communicate(self, input=None, timeout=None):
        if self._communication_started and input:
            raise ValueError('Cannot send input after starting communication')
        if timeout is None and not self._communication_started and [self.stdin, self.stdout, self.stderr].count(None) >= 2:
            stdout = None
            stderr = None
            if self.stdin:
                if input:
                    try:
                        self.stdin.write(input)
                    except IOError as e:
                        while e.errno != errno.EPIPE and e.errno != errno.EINVAL:
                            raise
                self.stdin.close()
            elif self.stdout:
                stdout = _eintr_retry_call(self.stdout.read)
                self.stdout.close()
            elif self.stderr:
                stderr = _eintr_retry_call(self.stderr.read)
                self.stderr.close()
            self.wait()
        else:
            if timeout is not None:
                endtime = _time() + timeout
            else:
                endtime = None
            try:
                (stdout, stderr) = self._communicate(input, endtime, timeout)
            finally:
                self._communication_started = True
            sts = self.wait(timeout=self._remaining_time(endtime))
        return (stdout, stderr)

    def poll(self):
        return self._internal_poll()

    def _remaining_time(self, endtime):
        if endtime is None:
            return
        return endtime - _time()

    def _check_timeout(self, endtime, orig_timeout):
        if endtime is None:
            return
        if _time() > endtime:
            raise TimeoutExpired(self.args, orig_timeout)

    if mswindows:

        def _get_handles(self, stdin, stdout, stderr):
            if stdin is None and stdout is None and stderr is None:
                return (-1, -1, -1, -1, -1, -1)
            (p2cread, p2cwrite) = (-1, -1)
            (c2pread, c2pwrite) = (-1, -1)
            (errread, errwrite) = (-1, -1)
            if stdin is None:
                p2cread = _winapi.GetStdHandle(_winapi.STD_INPUT_HANDLE)
                (p2cread, _) = _winapi.CreatePipe(None, 0)
                p2cread = Handle(p2cread)
                _winapi.CloseHandle(_)
            elif stdin == PIPE:
                (p2cread, p2cwrite) = _winapi.CreatePipe(None, 0)
                (p2cread, p2cwrite) = (Handle(p2cread), Handle(p2cwrite))
            elif stdin == DEVNULL:
                p2cread = msvcrt.get_osfhandle(self._get_devnull())
            elif isinstance(stdin, int):
                p2cread = msvcrt.get_osfhandle(stdin)
            else:
                p2cread = msvcrt.get_osfhandle(stdin.fileno())
            p2cread = self._make_inheritable(p2cread)
            if stdout is None:
                c2pwrite = _winapi.GetStdHandle(_winapi.STD_OUTPUT_HANDLE)
                (_, c2pwrite) = _winapi.CreatePipe(None, 0)
                c2pwrite = Handle(c2pwrite)
                _winapi.CloseHandle(_)
            elif stdout == PIPE:
                (c2pread, c2pwrite) = _winapi.CreatePipe(None, 0)
                (c2pread, c2pwrite) = (Handle(c2pread), Handle(c2pwrite))
            elif stdout == DEVNULL:
                c2pwrite = msvcrt.get_osfhandle(self._get_devnull())
            elif isinstance(stdout, int):
                c2pwrite = msvcrt.get_osfhandle(stdout)
            else:
                c2pwrite = msvcrt.get_osfhandle(stdout.fileno())
            c2pwrite = self._make_inheritable(c2pwrite)
            if stderr is None:
                errwrite = _winapi.GetStdHandle(_winapi.STD_ERROR_HANDLE)
                (_, errwrite) = _winapi.CreatePipe(None, 0)
                errwrite = Handle(errwrite)
                _winapi.CloseHandle(_)
            elif stderr == PIPE:
                (errread, errwrite) = _winapi.CreatePipe(None, 0)
                (errread, errwrite) = (Handle(errread), Handle(errwrite))
            elif stderr == STDOUT:
                errwrite = c2pwrite
            elif stderr == DEVNULL:
                errwrite = msvcrt.get_osfhandle(self._get_devnull())
            elif isinstance(stderr, int):
                errwrite = msvcrt.get_osfhandle(stderr)
            else:
                errwrite = msvcrt.get_osfhandle(stderr.fileno())
            errwrite = self._make_inheritable(errwrite)
            return (p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite)

        def _make_inheritable(self, handle):
            h = _winapi.DuplicateHandle(_winapi.GetCurrentProcess(), handle, _winapi.GetCurrentProcess(), 0, 1, _winapi.DUPLICATE_SAME_ACCESS)
            return Handle(h)

        def _find_w9xpopen(self):
            w9xpopen = os.path.join(os.path.dirname(_winapi.GetModuleFileName(0)), 'w9xpopen.exe')
            if not os.path.exists(w9xpopen):
                w9xpopen = os.path.join(os.path.dirname(sys.base_exec_prefix), 'w9xpopen.exe')
                if not os.path.exists(w9xpopen):
                    raise RuntimeError('Cannot locate w9xpopen.exe, which is needed for Popen to work with your shell or platform.')
            return w9xpopen

        def _execute_child(self, args, executable, preexec_fn, close_fds, pass_fds, cwd, env, startupinfo, creationflags, shell, p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite, unused_restore_signals, unused_start_new_session):
            if not isinstance(args, str):
                args = list2cmdline(args)
            if startupinfo is None:
                startupinfo = STARTUPINFO()
            if -1 not in (p2cread, c2pwrite, errwrite):
                startupinfo.hStdInput = p2cread
                startupinfo.hStdOutput = c2pwrite
                startupinfo.hStdError = errwrite
            if shell:
                startupinfo.wShowWindow = _winapi.SW_HIDE
                comspec = os.environ.get('COMSPEC', 'cmd.exe')
                args = '{} /c "{}"'.format(comspec, args)
                if _winapi.GetVersion() >= 2147483648 or os.path.basename(comspec).lower() == 'command.com':
                    w9xpopen = self._find_w9xpopen()
                    args = '"%s" %s' % (w9xpopen, args)
                    creationflags |= _winapi.CREATE_NEW_CONSOLE
            try:
                (hp, ht, pid, tid) = _winapi.CreateProcess(executable, args, None, None, int(not close_fds), creationflags, env, cwd, startupinfo)
            except pywintypes.error as e:
                raise WindowsError(*e.args)
            finally:
                if p2cread != -1:
                    p2cread.Close()
                if c2pwrite != -1:
                    c2pwrite.Close()
                if errwrite != -1:
                    errwrite.Close()
                if hasattr(self, '_devnull'):
                    os.close(self._devnull)
            self._child_created = True
            self._handle = Handle(hp)
            self.pid = pid
            _winapi.CloseHandle(ht)

        def _internal_poll(self, _deadstate=None, _WaitForSingleObject=_winapi.WaitForSingleObject, _WAIT_OBJECT_0=_winapi.WAIT_OBJECT_0, _GetExitCodeProcess=_winapi.GetExitCodeProcess):
            if self.returncode is None and _WaitForSingleObject(self._handle, 0) == _WAIT_OBJECT_0:
                self.returncode = _GetExitCodeProcess(self._handle)
            return self.returncode

        def wait(self, timeout=None, endtime=None):
            if endtime is not None:
                timeout = self._remaining_time(endtime)
            if timeout is None:
                timeout_millis = _winapi.INFINITE
            else:
                timeout_millis = int(timeout*1000)
            if self.returncode is None:
                result = _winapi.WaitForSingleObject(self._handle, timeout_millis)
                if result == _winapi.WAIT_TIMEOUT:
                    raise TimeoutExpired(self.args, timeout)
                self.returncode = _winapi.GetExitCodeProcess(self._handle)
            return self.returncode

        def _readerthread(self, fh, buffer):
            buffer.append(fh.read())
            fh.close()

        def _communicate(self, input, endtime, orig_timeout):
            if self.stdout and not hasattr(self, '_stdout_buff'):
                self._stdout_buff = []
                self.stdout_thread = threading.Thread(target=self._readerthread, args=(self.stdout, self._stdout_buff))
                self.stdout_thread.daemon = True
                self.stdout_thread.start()
            if self.stderr and not hasattr(self, '_stderr_buff'):
                self._stderr_buff = []
                self.stderr_thread = threading.Thread(target=self._readerthread, args=(self.stderr, self._stderr_buff))
                self.stderr_thread.daemon = True
                self.stderr_thread.start()
            if self.stdin:
                if input is not None:
                    try:
                        self.stdin.write(input)
                    except IOError as e:
                        if e.errno == errno.EPIPE:
                            pass
                        elif e.errno == errno.EINVAL and self.poll() is not None:
                            pass
                        else:
                            raise
                self.stdin.close()
            if self.stdout is not None:
                self.stdout_thread.join(self._remaining_time(endtime))
                if self.stdout_thread.is_alive():
                    raise TimeoutExpired(self.args, orig_timeout)
            if self.stderr is not None:
                self.stderr_thread.join(self._remaining_time(endtime))
                if self.stderr_thread.is_alive():
                    raise TimeoutExpired(self.args, orig_timeout)
            stdout = None
            stderr = None
            if self.stdout:
                stdout = self._stdout_buff
                self.stdout.close()
            if self.stderr:
                stderr = self._stderr_buff
                self.stderr.close()
            if stdout is not None:
                stdout = stdout[0]
            if stderr is not None:
                stderr = stderr[0]
            return (stdout, stderr)

        def send_signal(self, sig):
            if sig == signal.SIGTERM:
                self.terminate()
            elif sig == signal.CTRL_C_EVENT:
                os.kill(self.pid, signal.CTRL_C_EVENT)
            elif sig == signal.CTRL_BREAK_EVENT:
                os.kill(self.pid, signal.CTRL_BREAK_EVENT)
            else:
                raise ValueError('Unsupported signal: {}'.format(sig))

        def terminate(self):
            try:
                _winapi.TerminateProcess(self._handle, 1)
            except PermissionError:
                rc = _winapi.GetExitCodeProcess(self._handle)
                if rc == _winapi.STILL_ACTIVE:
                    raise
                self.returncode = rc

        kill = terminate
    else:

        def _get_handles(self, stdin, stdout, stderr):
            (p2cread, p2cwrite) = (-1, -1)
            (c2pread, c2pwrite) = (-1, -1)
            (errread, errwrite) = (-1, -1)
            if stdin is None:
                pass
            elif stdin == PIPE:
                (p2cread, p2cwrite) = _create_pipe()
            elif stdin == DEVNULL:
                p2cread = self._get_devnull()
            elif isinstance(stdin, int):
                p2cread = stdin
            else:
                p2cread = stdin.fileno()
            if stdout is None:
                pass
            elif stdout == PIPE:
                (c2pread, c2pwrite) = _create_pipe()
            elif stdout == DEVNULL:
                c2pwrite = self._get_devnull()
            elif isinstance(stdout, int):
                c2pwrite = stdout
            else:
                c2pwrite = stdout.fileno()
            if stderr is None:
                pass
            elif stderr == PIPE:
                (errread, errwrite) = _create_pipe()
            elif stderr == STDOUT:
                errwrite = c2pwrite
            elif stderr == DEVNULL:
                errwrite = self._get_devnull()
            elif isinstance(stderr, int):
                errwrite = stderr
            else:
                errwrite = stderr.fileno()
            return (p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite)

        def _close_fds(self, fds_to_keep):
            start_fd = 3
            for fd in sorted(fds_to_keep):
                while fd >= start_fd:
                    os.closerange(start_fd, fd)
                    start_fd = fd + 1
            if start_fd <= MAXFD:
                os.closerange(start_fd, MAXFD)

        def _execute_child(self, args, executable, preexec_fn, close_fds, pass_fds, cwd, env, startupinfo, creationflags, shell, p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite, restore_signals, start_new_session):
            if isinstance(args, (str, bytes)):
                args = [args]
            else:
                args = list(args)
            if shell:
                args = ['/bin/sh', '-c'] + args
                if executable:
                    args[0] = executable
            if executable is None:
                executable = args[0]
            orig_executable = executable
            (errpipe_read, errpipe_write) = _create_pipe()
            try:
                try:
                    if env is not None:
                        env_list = [os.fsencode(k) + b'=' + os.fsencode(v) for (k, v) in env.items()]
                    else:
                        env_list = None
                    executable = os.fsencode(executable)
                    if os.path.dirname(executable):
                        executable_list = (executable,)
                    else:
                        executable_list = tuple(os.path.join(os.fsencode(dir), executable) for dir in os.get_exec_path(env))
                    fds_to_keep = set(pass_fds)
                    fds_to_keep.add(errpipe_write)
                    self.pid = _posixsubprocess.fork_exec(args, executable_list, close_fds, sorted(fds_to_keep), cwd, env_list, p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite, errpipe_read, errpipe_write, restore_signals, start_new_session, preexec_fn)
                    self._child_created = True
                finally:
                    os.close(errpipe_write)
                devnull_fd = getattr(self, '_devnull', None)
                if p2cread != -1 and p2cwrite != -1 and p2cread != devnull_fd:
                    os.close(p2cread)
                if c2pwrite != -1 and c2pread != -1 and c2pwrite != devnull_fd:
                    os.close(c2pwrite)
                if errwrite != -1 and errread != -1 and errwrite != devnull_fd:
                    os.close(errwrite)
                if devnull_fd is not None:
                    os.close(devnull_fd)
                self._closed_child_pipe_fds = True
                errpipe_data = bytearray()
                while True:
                    part = _eintr_retry_call(os.read, errpipe_read, 50000)
                    errpipe_data += part
                    if not part or len(errpipe_data) > 50000:
                        break
            finally:
                os.close(errpipe_read)
            if errpipe_data:
                try:
                    _eintr_retry_call(os.waitpid, self.pid, 0)
                except OSError as e:
                    while e.errno != errno.ECHILD:
                        raise
                try:
                    (exception_name, hex_errno, err_msg) = errpipe_data.split(b':', 2)
                except ValueError:
                    exception_name = b'RuntimeError'
                    hex_errno = b'0'
                    err_msg = b'Bad exception data from child: ' + repr(errpipe_data)
                child_exception_type = getattr(builtins, exception_name.decode('ascii'), RuntimeError)
                err_msg = err_msg.decode(errors='surrogatepass')
                if issubclass(child_exception_type, OSError) and hex_errno:
                    errno_num = int(hex_errno, 16)
                    child_exec_never_called = err_msg == 'noexec'
                    if child_exec_never_called:
                        err_msg = ''
                    if errno_num != 0:
                        err_msg = os.strerror(errno_num)
                        if errno_num == errno.ENOENT:
                            if child_exec_never_called:
                                err_msg += ': ' + repr(cwd)
                            else:
                                err_msg += ': ' + repr(orig_executable)
                    raise child_exception_type(errno_num, err_msg)
                raise child_exception_type(err_msg)

        def _handle_exitstatus(self, sts, _WIFSIGNALED=os.WIFSIGNALED, _WTERMSIG=os.WTERMSIG, _WIFEXITED=os.WIFEXITED, _WEXITSTATUS=os.WEXITSTATUS):
            if _WIFSIGNALED(sts):
                self.returncode = -_WTERMSIG(sts)
            elif _WIFEXITED(sts):
                self.returncode = _WEXITSTATUS(sts)
            else:
                raise RuntimeError('Unknown child exit status!')

        def _internal_poll(self, _deadstate=None, _waitpid=os.waitpid, _WNOHANG=os.WNOHANG, _os_error=os.error, _ECHILD=errno.ECHILD):
            if self.returncode is None:
                try:
                    (pid, sts) = _waitpid(self.pid, _WNOHANG)
                    while pid == self.pid:
                        self._handle_exitstatus(sts)
                except _os_error as e:
                    if _deadstate is not None:
                        self.returncode = _deadstate
                    else:
                        while e.errno == _ECHILD:
                            self.returncode = 0
            return self.returncode

        def _try_wait(self, wait_flags):
            try:
                (pid, sts) = _eintr_retry_call(os.waitpid, self.pid, wait_flags)
            except OSError as e:
                if e.errno != errno.ECHILD:
                    raise
                pid = self.pid
                sts = 0
            return (pid, sts)

        def wait(self, timeout=None, endtime=None):
            if self.returncode is not None:
                return self.returncode
            if endtime is not None or timeout is not None:
                if endtime is None:
                    endtime = _time() + timeout
                elif timeout is None:
                    timeout = self._remaining_time(endtime)
            if endtime is not None:
                delay = 0.0005
                while pid == self.pid:
                    self._handle_exitstatus(sts)
                    break
                    remaining = self._remaining_time(endtime)
                    if remaining <= 0:
                        raise TimeoutExpired(self.args, timeout)
                    delay = min(delay*2, remaining, 0.05)
                    time.sleep(delay)
                    continue
            else:
                while self.returncode is None:
                    (pid, sts) = self._try_wait(0)
                    while pid == self.pid:
                        self._handle_exitstatus(sts)
                        continue
            return self.returncode

        def _communicate(self, input, endtime, orig_timeout):
            if self.stdin and not self._communication_started:
                self.stdin.flush()
                if not input:
                    self.stdin.close()
            if _has_poll:
                (stdout, stderr) = self._communicate_with_poll(input, endtime, orig_timeout)
            else:
                (stdout, stderr) = self._communicate_with_select(input, endtime, orig_timeout)
            self.wait(timeout=self._remaining_time(endtime))
            if stdout is not None:
                stdout = b''.join(stdout)
            if stderr is not None:
                stderr = b''.join(stderr)
            if stdout is not None:
                stdout = self._translate_newlines(stdout, self.stdout.encoding)
            if self.universal_newlines and stderr is not None:
                stderr = self._translate_newlines(stderr, self.stderr.encoding)
            return (stdout, stderr)

        def _save_input(self, input):
            if self.stdin and self._input is None:
                self._input_offset = 0
                self._input = input
                if self.universal_newlines and input is not None:
                    self._input = self._input.encode(self.stdin.encoding)

        def _communicate_with_poll(self, input, endtime, orig_timeout):
            stdout = None
            stderr = None
            if not self._communication_started:
                self._fd2file = {}
            poller = select.poll()

            def register_and_append(file_obj, eventmask):
                poller.register(file_obj.fileno(), eventmask)
                self._fd2file[file_obj.fileno()] = file_obj

            def close_unregister_and_remove(fd):
                poller.unregister(fd)
                self._fd2file[fd].close()
                self._fd2file.pop(fd)

            if self.stdin and input:
                register_and_append(self.stdin, select.POLLOUT)
            if not self._communication_started:
                self._fd2output = {}
                if self.stdout:
                    self._fd2output[self.stdout.fileno()] = []
                if self.stderr:
                    self._fd2output[self.stderr.fileno()] = []
            select_POLLIN_POLLPRI = select.POLLIN | select.POLLPRI
            if self.stdout:
                register_and_append(self.stdout, select_POLLIN_POLLPRI)
                stdout = self._fd2output[self.stdout.fileno()]
            if self.stderr:
                register_and_append(self.stderr, select_POLLIN_POLLPRI)
                stderr = self._fd2output[self.stderr.fileno()]
            self._save_input(input)
            if self._input:
                input_view = memoryview(self._input)
            while self._fd2file:
                timeout = self._remaining_time(endtime)
                if timeout is not None and timeout < 0:
                    raise TimeoutExpired(self.args, orig_timeout)
                try:
                    ready = poller.poll(timeout)
                except select.error as e:
                    if e.args[0] == errno.EINTR:
                        continue
                    raise
                self._check_timeout(endtime, orig_timeout)
                for (fd, mode) in ready:
                    if mode & select.POLLOUT:
                        chunk = input_view[self._input_offset:self._input_offset + _PIPE_BUF]
                        try:
                            pass
                        except OSError as e:
                            if e.errno == errno.EPIPE:
                                close_unregister_and_remove(fd)
                            else:
                                raise
                        close_unregister_and_remove(fd)
                    elif mode & select_POLLIN_POLLPRI:
                        data = os.read(fd, 32768)
                        if not data:
                            close_unregister_and_remove(fd)
                        self._fd2output[fd].append(data)
                    else:
                        close_unregister_and_remove(fd)
            return (stdout, stderr)

        def _communicate_with_select(self, input, endtime, orig_timeout):
            if not self._communication_started:
                self._read_set = []
                self._write_set = []
                if self.stdin and input:
                    self._write_set.append(self.stdin)
                if self.stdout:
                    self._read_set.append(self.stdout)
                if self.stderr:
                    self._read_set.append(self.stderr)
            self._save_input(input)
            stdout = None
            stderr = None
            if self.stdout:
                if not self._communication_started:
                    self._stdout_buff = []
                stdout = self._stdout_buff
            if not self._communication_started:
                self._stderr_buff = []
            stderr = self._stderr_buff
            while not self._read_set:
                while self._write_set:
                    timeout = self._remaining_time(endtime)
                    if timeout is not None and timeout < 0:
                        raise TimeoutExpired(self.args, orig_timeout)
                    try:
                        (rlist, wlist, xlist) = select.select(self._read_set, self._write_set, [], timeout)
                    except select.error as e:
                        if e.args[0] == errno.EINTR:
                            continue
                        raise
                    if not (rlist or (wlist or xlist)):
                        raise TimeoutExpired(self.args, orig_timeout)
                    self._check_timeout(endtime, orig_timeout)
                    if self.stdin in wlist:
                        chunk = self._input[self._input_offset:self._input_offset + _PIPE_BUF]
                        try:
                            bytes_written = os.write(self.stdin.fileno(), chunk)
                        except OSError as e:
                            if e.errno == errno.EPIPE:
                                self.stdin.close()
                                self._write_set.remove(self.stdin)
                            else:
                                raise
                        if self._input_offset >= len(self._input):
                            self.stdin.close()
                            self._write_set.remove(self.stdin)
                    if self.stdout in rlist:
                        data = os.read(self.stdout.fileno(), 1024)
                        if not data:
                            self.stdout.close()
                            self._read_set.remove(self.stdout)
                        stdout.append(data)
                    while self.stderr in rlist:
                        data = os.read(self.stderr.fileno(), 1024)
                        if not data:
                            self.stderr.close()
                            self._read_set.remove(self.stderr)
                        stderr.append(data)
                        continue
            return (stdout, stderr)

        def send_signal(self, sig):
            os.kill(self.pid, sig)

        def terminate(self):
            self.send_signal(signal.SIGTERM)

        def kill(self):
            self.send_signal(signal.SIGKILL)

