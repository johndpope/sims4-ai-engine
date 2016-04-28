import socket
import threading
import time
import sims4.gsi.dispatcher
import sims4.log
try:
    import urllib.parse
except:
    pass
logger = sims4.log.Logger('GSI')
try:
    import http.server
except ImportError:

    class http:
        __qualname__ = 'http'

        class server:
            __qualname__ = 'http.server'

            class BaseHTTPRequestHandler:
                __qualname__ = 'http.server.BaseHTTPRequestHandler'

                def __init__(self):
                    pass

            class HTTPServer:
                __qualname__ = 'http.server.HTTPServer'

                def __init__(self):
                    pass

with sims4.reload.protected(globals()):
    server_thread = None
    server_lock = threading.Lock()
    http_server = None
JSONP_CALLBACK = 'callback'

class GameHttpHandler(http.server.BaseHTTPRequestHandler):
    __qualname__ = 'GameHttpHandler'

    def log_message(self, log_format, *args):
        pass

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'content-type')
        self.send_header('Content-Length', '0')
        self.send_header('Content-Type', 'text/html')
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        clean_path = parsed_url.path.strip('/')
        try:
            if parsed_url.query:
                params = urllib.parse.parse_qs(parsed_url.query)
                for (key, value) in params.items():
                    if value[0] == 'true':
                        params[key] = True
                    elif value[0] == 'false':
                        params[key] = False
                    else:
                        params[key] = value[0]
            else:
                params = None
        except Exception:
            logger.exception('Unable to parse kwargs from query string:\n{}', parsed_url.query)
            params = None
        if params is None:
            callback_string = None
            response = sims4.gsi.dispatcher.handle_request(clean_path, params)
        else:
            callback_string = params.pop(JSONP_CALLBACK, None)
            response = sims4.gsi.dispatcher.handle_request(clean_path, params)
        if response is None:
            self.send_response(404)
            return
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        if callback_string:
            response = callback_string + '(' + response + ')'
        self.write_string(response)

    def write_string(self, string):
        self.wfile.write(bytes(string, 'UTF-8'))

def http_server_loop(callback=None, server_class=http.server.HTTPServer, handler_class=GameHttpHandler):
    global http_server
    host_address = socket.gethostbyname(socket.gethostname())
    port = 0
    if http_server is None:
        with server_lock:
            http_server = server_class((host_address, port), handler_class)
            http_server.timeout = 0.001
    if callback is not None:
        callback(http_server)
    while http_server is not None:
        with server_lock:
            http_server.handle_request()
        time.sleep(0.1)

def start_http_server(callback):
    global server_thread
    if server_thread is None:
        server_thread = threading.Thread(target=http_server_loop, args=(callback,), name='HTTP Server')
        server_thread.start()
    else:
        callback(http_server)

def stop_http_server():
    global http_server, server_thread
    if server_thread is not None:
        with server_lock:
            if http_server is not None:
                http_server.socket.close()
                http_server = None
            server_thread = None

