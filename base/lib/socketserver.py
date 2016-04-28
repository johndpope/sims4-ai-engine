__version__ = '0.4'
import socket
import select
import sys
import os
import errno
try:
    import threading
except ImportError:
    import dummy_threading as threading
__all__ = ['TCPServer', 'UDPServer', 'ForkingUDPServer', 'ForkingTCPServer', 'ThreadingUDPServer', 'ThreadingTCPServer', 'BaseRequestHandler', 'StreamRequestHandler', 'DatagramRequestHandler', 'ThreadingMixIn', 'ForkingMixIn']
if hasattr(socket, 'AF_UNIX'):
    __all__.extend(['UnixStreamServer', 'UnixDatagramServer', 'ThreadingUnixStreamServer', 'ThreadingUnixDatagramServer'])

def _eintr_retry(func, *args):
    while True:
        try:
            return func(*args)
        except OSError as e:
            while e.errno != errno.EINTR:
                raise

class BaseServer:
    __qualname__ = 'BaseServer'
    timeout = None

    def __init__(self, server_address, RequestHandlerClass):
        self.server_address = server_address
        self.RequestHandlerClass = RequestHandlerClass
        self._BaseServer__is_shut_down = threading.Event()
        self._BaseServer__shutdown_request = False

    def server_activate(self):
        pass

    def serve_forever(self, poll_interval=0.5):
        self._BaseServer__is_shut_down.clear()
        try:
            while not self._BaseServer__shutdown_request:
                (r, w, e) = _eintr_retry(select.select, [self], [], [], poll_interval)
                if self in r:
                    self._handle_request_noblock()
                self.service_actions()
        finally:
            self._BaseServer__shutdown_request = False
            self._BaseServer__is_shut_down.set()

    def shutdown(self):
        self._BaseServer__shutdown_request = True
        self._BaseServer__is_shut_down.wait()

    def service_actions(self):
        pass

    def handle_request(self):
        timeout = self.socket.gettimeout()
        if timeout is None:
            timeout = self.timeout
        elif self.timeout is not None:
            timeout = min(timeout, self.timeout)
        fd_sets = _eintr_retry(select.select, [self], [], [], timeout)
        if not fd_sets[0]:
            self.handle_timeout()
            return
        self._handle_request_noblock()

    def _handle_request_noblock(self):
        try:
            (request, client_address) = self.get_request()
        except socket.error:
            return
        if self.verify_request(request, client_address):
            try:
                self.process_request(request, client_address)
            except:
                self.handle_error(request, client_address)
                self.shutdown_request(request)

    def handle_timeout(self):
        pass

    def verify_request(self, request, client_address):
        return True

    def process_request(self, request, client_address):
        self.finish_request(request, client_address)
        self.shutdown_request(request)

    def server_close(self):
        pass

    def finish_request(self, request, client_address):
        self.RequestHandlerClass(request, client_address, self)

    def shutdown_request(self, request):
        self.close_request(request)

    def close_request(self, request):
        pass

    def handle_error(self, request, client_address):
        print('-'*40)
        print('Exception happened during processing of request from', end=' ')
        print(client_address)
        import traceback
        traceback.print_exc()
        print('-'*40)

class TCPServer(BaseServer):
    __qualname__ = 'TCPServer'
    address_family = socket.AF_INET
    socket_type = socket.SOCK_STREAM
    request_queue_size = 5
    allow_reuse_address = False

    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):
        BaseServer.__init__(self, server_address, RequestHandlerClass)
        self.socket = socket.socket(self.address_family, self.socket_type)
        if bind_and_activate:
            self.server_bind()
            self.server_activate()

    def server_bind(self):
        if self.allow_reuse_address:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()

    def server_activate(self):
        self.socket.listen(self.request_queue_size)

    def server_close(self):
        self.socket.close()

    def fileno(self):
        return self.socket.fileno()

    def get_request(self):
        return self.socket.accept()

    def shutdown_request(self, request):
        try:
            request.shutdown(socket.SHUT_WR)
        except socket.error:
            pass
        self.close_request(request)

    def close_request(self, request):
        request.close()

class UDPServer(TCPServer):
    __qualname__ = 'UDPServer'
    allow_reuse_address = False
    socket_type = socket.SOCK_DGRAM
    max_packet_size = 8192

    def get_request(self):
        (data, client_addr) = self.socket.recvfrom(self.max_packet_size)
        return ((data, self.socket), client_addr)

    def server_activate(self):
        pass

    def shutdown_request(self, request):
        self.close_request(request)

    def close_request(self, request):
        pass

class ForkingMixIn:
    __qualname__ = 'ForkingMixIn'
    timeout = 300
    active_children = None
    max_children = 40

    def collect_children(self):
        if self.active_children is None:
            return
        while len(self.active_children) >= self.max_children:
            try:
                (pid, status) = os.waitpid(0, 0)
            except os.error:
                pid = None
            if pid not in self.active_children:
                continue
            self.active_children.remove(pid)
        for child in self.active_children:
            try:
                (pid, status) = os.waitpid(child, os.WNOHANG)
            except os.error:
                pid = None
            if not pid:
                pass
            try:
                self.active_children.remove(pid)
            except ValueError as e:
                raise ValueError('%s. x=%d and list=%r' % (e.message, pid, self.active_children))

    def handle_timeout(self):
        self.collect_children()

    def service_actions(self):
        self.collect_children()

    def process_request(self, request, client_address):
        pid = os.fork()
        if self.active_children is None:
            self.active_children = []
        self.active_children.append(pid)
        self.close_request(request)
        return
        try:
            self.finish_request(request, client_address)
            self.shutdown_request(request)
            os._exit(0)
        except:
            try:
                self.handle_error(request, client_address)
                self.shutdown_request(request)
            finally:
                os._exit(1)

class ThreadingMixIn:
    __qualname__ = 'ThreadingMixIn'
    daemon_threads = False

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
            self.shutdown_request(request)
        except:
            self.handle_error(request, client_address)
            self.shutdown_request(request)

    def process_request(self, request, client_address):
        t = threading.Thread(target=self.process_request_thread, args=(request, client_address))
        t.daemon = self.daemon_threads
        t.start()

class ForkingUDPServer(ForkingMixIn, UDPServer):
    __qualname__ = 'ForkingUDPServer'

class ForkingTCPServer(ForkingMixIn, TCPServer):
    __qualname__ = 'ForkingTCPServer'

class ThreadingUDPServer(ThreadingMixIn, UDPServer):
    __qualname__ = 'ThreadingUDPServer'

class ThreadingTCPServer(ThreadingMixIn, TCPServer):
    __qualname__ = 'ThreadingTCPServer'

if hasattr(socket, 'AF_UNIX'):

    class UnixStreamServer(TCPServer):
        __qualname__ = 'UnixStreamServer'
        address_family = socket.AF_UNIX

    class UnixDatagramServer(UDPServer):
        __qualname__ = 'UnixDatagramServer'
        address_family = socket.AF_UNIX

    class ThreadingUnixStreamServer(ThreadingMixIn, UnixStreamServer):
        __qualname__ = 'ThreadingUnixStreamServer'

    class ThreadingUnixDatagramServer(ThreadingMixIn, UnixDatagramServer):
        __qualname__ = 'ThreadingUnixDatagramServer'

class BaseRequestHandler:
    __qualname__ = 'BaseRequestHandler'

    def __init__(self, request, client_address, server):
        self.request = request
        self.client_address = client_address
        self.server = server
        self.setup()
        try:
            self.handle()
        finally:
            self.finish()

    def setup(self):
        pass

    def handle(self):
        pass

    def finish(self):
        pass

class StreamRequestHandler(BaseRequestHandler):
    __qualname__ = 'StreamRequestHandler'
    rbufsize = -1
    wbufsize = 0
    timeout = None
    disable_nagle_algorithm = False

    def setup(self):
        self.connection = self.request
        if self.timeout is not None:
            self.connection.settimeout(self.timeout)
        if self.disable_nagle_algorithm:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
        self.rfile = self.connection.makefile('rb', self.rbufsize)
        self.wfile = self.connection.makefile('wb', self.wbufsize)

    def finish(self):
        if not self.wfile.closed:
            try:
                self.wfile.flush()
            except socket.error:
                pass
        self.wfile.close()
        self.rfile.close()

class DatagramRequestHandler(BaseRequestHandler):
    __qualname__ = 'DatagramRequestHandler'

    def setup(self):
        from io import BytesIO
        (self.packet, self.socket) = self.request
        self.rfile = BytesIO(self.packet)
        self.wfile = BytesIO()

    def finish(self):
        self.socket.sendto(self.wfile.getvalue(), self.client_address)

