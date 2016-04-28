import base64
import bisect
import email
import hashlib
import http.client
import io
import os
import posixpath
import re
import socket
import sys
import time
import collections
import tempfile
import contextlib
import warnings
from urllib.error import URLError, HTTPError, ContentTooShortError
from urllib.parse import urlparse, urlsplit, urljoin, unwrap, quote, unquote, splittype, splithost, splitport, splituser, splitpasswd, splitattr, splitquery, splitvalue, splittag, to_bytes, urlunparse
from urllib.response import addinfourl, addclosehook
try:
    import ssl
except ImportError:
    _have_ssl = False
_have_ssl = True
__all__ = ['Request', 'OpenerDirector', 'BaseHandler', 'HTTPDefaultErrorHandler', 'HTTPRedirectHandler', 'HTTPCookieProcessor', 'ProxyHandler', 'HTTPPasswordMgr', 'HTTPPasswordMgrWithDefaultRealm', 'AbstractBasicAuthHandler', 'HTTPBasicAuthHandler', 'ProxyBasicAuthHandler', 'AbstractDigestAuthHandler', 'HTTPDigestAuthHandler', 'ProxyDigestAuthHandler', 'HTTPHandler', 'FileHandler', 'FTPHandler', 'CacheFTPHandler', 'UnknownHandler', 'HTTPErrorProcessor', 'urlopen', 'install_opener', 'build_opener', 'pathname2url', 'url2pathname', 'getproxies', 'urlretrieve', 'urlcleanup', 'URLopener', 'FancyURLopener']
__version__ = sys.version[:3]
_opener = None

def urlopen(url, data=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, *, cafile=None, capath=None, cadefault=False):
    global _opener
    if cafile or capath or cadefault:
        if not _have_ssl:
            raise ValueError('SSL support not available')
        context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        context.verify_mode = ssl.CERT_REQUIRED
        if cafile or capath:
            context.load_verify_locations(cafile, capath)
        else:
            context.set_default_verify_paths()
        https_handler = HTTPSHandler(context=context, check_hostname=True)
        opener = build_opener(https_handler)
    elif _opener is None:
        _opener = opener = build_opener()
    else:
        opener = _opener
    return opener.open(url, data, timeout)

def install_opener(opener):
    global _opener
    _opener = opener

_url_tempfiles = []

def urlretrieve(url, filename=None, reporthook=None, data=None):
    (url_type, path) = splittype(url)
    with contextlib.closing(urlopen(url, data)) as fp:
        headers = fp.info()
        if url_type == 'file' and not filename:
            return (os.path.normpath(path), headers)
        if filename:
            tfp = open(filename, 'wb')
        else:
            tfp = tempfile.NamedTemporaryFile(delete=False)
            filename = tfp.name
            _url_tempfiles.append(filename)
        with tfp:
            result = (filename, headers)
            bs = 8192
            size = -1
            read = 0
            blocknum = 0
            if 'content-length' in headers:
                size = int(headers['Content-Length'])
            if reporthook:
                reporthook(blocknum, bs, size)
            while True:
                block = fp.read(bs)
                if not block:
                    break
                read += len(block)
                tfp.write(block)
                blocknum += 1
                if reporthook:
                    reporthook(blocknum, bs, size)
    if size >= 0 and read < size:
        raise ContentTooShortError('retrieval incomplete: got only %i out of %i bytes' % (read, size), result)
    return result

def urlcleanup():
    global _opener
    for temp_file in _url_tempfiles:
        try:
            os.unlink(temp_file)
        except EnvironmentError:
            pass
    del _url_tempfiles[:]
    if _opener:
        _opener = None

_cut_port_re = re.compile(':\\d+$', re.ASCII)

def request_host(request):
    url = request.full_url
    host = urlparse(url)[1]
    if host == '':
        host = request.get_header('Host', '')
    host = _cut_port_re.sub('', host, 1)
    return host.lower()

class Request:
    __qualname__ = 'Request'

    def __init__(self, url, data=None, headers={}, origin_req_host=None, unverifiable=False, method=None):
        self.full_url = unwrap(url)
        (self.full_url, self.fragment) = splittag(self.full_url)
        self.data = data
        self.headers = {}
        self._tunnel_host = None
        for (key, value) in headers.items():
            self.add_header(key, value)
        self.unredirected_hdrs = {}
        if origin_req_host is None:
            origin_req_host = request_host(self)
        self.origin_req_host = origin_req_host
        self.unverifiable = unverifiable
        self.method = method
        self._parse()

    def _parse(self):
        (self.type, rest) = splittype(self.full_url)
        if self.type is None:
            raise ValueError('unknown url type: %r' % self.full_url)
        (self.host, self.selector) = splithost(rest)
        if self.host:
            self.host = unquote(self.host)

    def get_method(self):
        if self.method is not None:
            return self.method
        if self.data is not None:
            return 'POST'
        return 'GET'

    def get_full_url(self):
        if self.fragment:
            return '%s#%s' % (self.full_url, self.fragment)
        return self.full_url

    def add_data(self, data):
        msg = 'Request.add_data method is deprecated.'
        warnings.warn(msg, DeprecationWarning, stacklevel=1)
        self.data = data

    def has_data(self):
        msg = 'Request.has_data method is deprecated.'
        warnings.warn(msg, DeprecationWarning, stacklevel=1)
        return self.data is not None

    def get_data(self):
        msg = 'Request.get_data method is deprecated.'
        warnings.warn(msg, DeprecationWarning, stacklevel=1)
        return self.data

    def get_type(self):
        msg = 'Request.get_type method is deprecated.'
        warnings.warn(msg, DeprecationWarning, stacklevel=1)
        return self.type

    def get_host(self):
        msg = 'Request.get_host method is deprecated.'
        warnings.warn(msg, DeprecationWarning, stacklevel=1)
        return self.host

    def get_selector(self):
        msg = 'Request.get_selector method is deprecated.'
        warnings.warn(msg, DeprecationWarning, stacklevel=1)
        return self.selector

    def is_unverifiable(self):
        msg = 'Request.is_unverifiable method is deprecated.'
        warnings.warn(msg, DeprecationWarning, stacklevel=1)
        return self.unverifiable

    def get_origin_req_host(self):
        msg = 'Request.get_origin_req_host method is deprecated.'
        warnings.warn(msg, DeprecationWarning, stacklevel=1)
        return self.origin_req_host

    def set_proxy(self, host, type):
        if self.type == 'https' and not self._tunnel_host:
            self._tunnel_host = self.host
        else:
            self.type = type
            self.selector = self.full_url
        self.host = host

    def has_proxy(self):
        return self.selector == self.full_url

    def add_header(self, key, val):
        self.headers[key.capitalize()] = val

    def add_unredirected_header(self, key, val):
        self.unredirected_hdrs[key.capitalize()] = val

    def has_header(self, header_name):
        return header_name in self.headers or header_name in self.unredirected_hdrs

    def get_header(self, header_name, default=None):
        return self.headers.get(header_name, self.unredirected_hdrs.get(header_name, default))

    def header_items(self):
        hdrs = self.unredirected_hdrs.copy()
        hdrs.update(self.headers)
        return list(hdrs.items())

class OpenerDirector:
    __qualname__ = 'OpenerDirector'

    def __init__(self):
        client_version = 'Python-urllib/%s' % __version__
        self.addheaders = [('User-agent', client_version)]
        self.handlers = []
        self.handle_open = {}
        self.handle_error = {}
        self.process_response = {}
        self.process_request = {}

    def add_handler(self, handler):
        if not hasattr(handler, 'add_parent'):
            raise TypeError('expected BaseHandler instance, got %r' % type(handler))
        added = False
        for meth in dir(handler):
            if meth in ('redirect_request', 'do_open', 'proxy_open'):
                pass
            i = meth.find('_')
            protocol = meth[:i]
            condition = meth[i + 1:]
            if condition.startswith('error'):
                j = condition.find('_') + i + 1
                kind = meth[j + 1:]
                try:
                    kind = int(kind)
                except ValueError:
                    pass
                lookup = self.handle_error.get(protocol, {})
                self.handle_error[protocol] = lookup
            elif condition == 'open':
                kind = protocol
                lookup = self.handle_open
            elif condition == 'response':
                kind = protocol
                lookup = self.process_response
            else:
                while condition == 'request':
                    kind = protocol
                    lookup = self.process_request
                    handlers = lookup.setdefault(kind, [])
                    if handlers:
                        bisect.insort(handlers, handler)
                    else:
                        handlers.append(handler)
                    added = True
            handlers = lookup.setdefault(kind, [])
            if handlers:
                bisect.insort(handlers, handler)
            else:
                handlers.append(handler)
            added = True
        if added:
            bisect.insort(self.handlers, handler)
            handler.add_parent(self)

    def close(self):
        pass

    def _call_chain(self, chain, kind, meth_name, *args):
        handlers = chain.get(kind, ())
        for handler in handlers:
            func = getattr(handler, meth_name)
            result = func(*args)
            while result is not None:
                return result

    def open(self, fullurl, data=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT):
        if isinstance(fullurl, str):
            req = Request(fullurl, data)
        else:
            req = fullurl
            if data is not None:
                req.data = data
        req.timeout = timeout
        protocol = req.type
        meth_name = protocol + '_request'
        for processor in self.process_request.get(protocol, []):
            meth = getattr(processor, meth_name)
            req = meth(req)
        response = self._open(req, data)
        meth_name = protocol + '_response'
        for processor in self.process_response.get(protocol, []):
            meth = getattr(processor, meth_name)
            response = meth(req, response)
        return response

    def _open(self, req, data=None):
        result = self._call_chain(self.handle_open, 'default', 'default_open', req)
        if result:
            return result
        protocol = req.type
        result = self._call_chain(self.handle_open, protocol, protocol + '_open', req)
        if result:
            return result
        return self._call_chain(self.handle_open, 'unknown', 'unknown_open', req)

    def error(self, proto, *args):
        if proto in ('http', 'https'):
            dict = self.handle_error['http']
            proto = args[2]
            meth_name = 'http_error_%s' % proto
            http_err = 1
            orig_args = args
        else:
            dict = self.handle_error
            meth_name = proto + '_error'
            http_err = 0
        args = (dict, proto, meth_name) + args
        result = self._call_chain(*args)
        if result:
            return result
        if http_err:
            args = (dict, 'default', 'http_error_default') + orig_args
            return self._call_chain(*args)

def build_opener(*handlers):

    def isclass(obj):
        return isinstance(obj, type) or hasattr(obj, '__bases__')

    opener = OpenerDirector()
    default_classes = [ProxyHandler, UnknownHandler, HTTPHandler, HTTPDefaultErrorHandler, HTTPRedirectHandler, FTPHandler, FileHandler, HTTPErrorProcessor]
    if hasattr(http.client, 'HTTPSConnection'):
        default_classes.append(HTTPSHandler)
    skip = set()
    for klass in default_classes:
        for check in handlers:
            if isclass(check):
                if issubclass(check, klass):
                    skip.add(klass)
                    while isinstance(check, klass):
                        skip.add(klass)
            else:
                while isinstance(check, klass):
                    skip.add(klass)
    for klass in skip:
        default_classes.remove(klass)
    for klass in default_classes:
        opener.add_handler(klass())
    for h in handlers:
        if isclass(h):
            h = h()
        opener.add_handler(h)
    return opener

class BaseHandler:
    __qualname__ = 'BaseHandler'
    handler_order = 500

    def add_parent(self, parent):
        self.parent = parent

    def close(self):
        pass

    def __lt__(self, other):
        if not hasattr(other, 'handler_order'):
            return True
        return self.handler_order < other.handler_order

class HTTPErrorProcessor(BaseHandler):
    __qualname__ = 'HTTPErrorProcessor'
    handler_order = 1000

    def http_response(self, request, response):
        (code, msg) = (response.code, response.msg)
        hdrs = response.info()
        if not 200 <= code < 300:
            response = self.parent.error('http', request, response, code, msg, hdrs)
        return response

    https_response = http_response

class HTTPDefaultErrorHandler(BaseHandler):
    __qualname__ = 'HTTPDefaultErrorHandler'

    def http_error_default(self, req, fp, code, msg, hdrs):
        raise HTTPError(req.full_url, code, msg, hdrs, fp)

class HTTPRedirectHandler(BaseHandler):
    __qualname__ = 'HTTPRedirectHandler'
    max_repeats = 4
    max_redirections = 10

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        m = req.get_method()
        if not (code in (301, 302, 303, 307) and m in ('GET', 'HEAD') or code in (301, 302, 303) and m == 'POST'):
            raise HTTPError(req.full_url, code, msg, headers, fp)
        newurl = newurl.replace(' ', '%20')
        CONTENT_HEADERS = ('content-length', 'content-type')
        newheaders = dict((k, v) for (k, v) in req.headers.items() if k.lower() not in CONTENT_HEADERS)
        return Request(newurl, headers=newheaders, origin_req_host=req.origin_req_host, unverifiable=True)

    def http_error_302(self, req, fp, code, msg, headers):
        if 'location' in headers:
            newurl = headers['location']
        elif 'uri' in headers:
            newurl = headers['uri']
        else:
            return
        urlparts = urlparse(newurl)
        if urlparts.scheme not in ('http', 'https', 'ftp', ''):
            raise HTTPError(newurl, code, "%s - Redirection to url '%s' is not allowed" % (msg, newurl), headers, fp)
        if not urlparts.path:
            urlparts = list(urlparts)
            urlparts[2] = '/'
        newurl = urlunparse(urlparts)
        newurl = urljoin(req.full_url, newurl)
        new = self.redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return
        if hasattr(req, 'redirect_dict'):
            visited = new.redirect_dict = req.redirect_dict
            raise HTTPError(req.full_url, code, self.inf_msg + msg, headers, fp)
        else:
            visited = new.redirect_dict = req.redirect_dict = {}
        visited[newurl] = visited.get(newurl, 0) + 1
        fp.read()
        fp.close()
        return self.parent.open(new, timeout=req.timeout)

    http_error_301 = http_error_303 = http_error_307 = http_error_302
    inf_msg = 'The HTTP server returned a redirect error that would lead to an infinite loop.\nThe last 30x error message was:\n'

def _parse_proxy(proxy):
    (scheme, r_scheme) = splittype(proxy)
    if not r_scheme.startswith('/'):
        scheme = None
        authority = proxy
    else:
        if not r_scheme.startswith('//'):
            raise ValueError('proxy URL with no authority: %r' % proxy)
        end = r_scheme.find('/', 2)
        if end == -1:
            end = None
        authority = r_scheme[2:end]
    (userinfo, hostport) = splituser(authority)
    if userinfo is not None:
        (user, password) = splitpasswd(userinfo)
    else:
        user = password = None
    return (scheme, user, password, hostport)

class ProxyHandler(BaseHandler):
    __qualname__ = 'ProxyHandler'
    handler_order = 100

    def __init__(self, proxies=None):
        if proxies is None:
            proxies = getproxies()
        self.proxies = proxies
        for (type, url) in proxies.items():
            setattr(self, '%s_open' % type, lambda r, proxy=url, type=type, meth=self.proxy_open: meth(r, proxy, type))

    def proxy_open(self, req, proxy, type):
        orig_type = req.type
        (proxy_type, user, password, hostport) = _parse_proxy(proxy)
        if proxy_type is None:
            proxy_type = orig_type
        if req.host and proxy_bypass(req.host):
            return
        if user and password:
            user_pass = '%s:%s' % (unquote(user), unquote(password))
            creds = base64.b64encode(user_pass.encode()).decode('ascii')
            req.add_header('Proxy-authorization', 'Basic ' + creds)
        hostport = unquote(hostport)
        req.set_proxy(hostport, proxy_type)
        if orig_type == proxy_type or orig_type == 'https':
            return
        return self.parent.open(req, timeout=req.timeout)

class HTTPPasswordMgr:
    __qualname__ = 'HTTPPasswordMgr'

    def __init__(self):
        self.passwd = {}

    def add_password(self, realm, uri, user, passwd):
        if isinstance(uri, str):
            uri = [uri]
        if realm not in self.passwd:
            self.passwd[realm] = {}
        for default_port in (True, False):
            reduced_uri = tuple([self.reduce_uri(u, default_port) for u in uri])
            self.passwd[realm][reduced_uri] = (user, passwd)

    def find_user_password(self, realm, authuri):
        domains = self.passwd.get(realm, {})
        for default_port in (True, False):
            reduced_authuri = self.reduce_uri(authuri, default_port)
            for (uris, authinfo) in domains.items():
                for uri in uris:
                    while self.is_suburi(uri, reduced_authuri):
                        return authinfo
        return (None, None)

    def reduce_uri(self, uri, default_port=True):
        parts = urlsplit(uri)
        if parts[1]:
            scheme = parts[0]
            authority = parts[1]
            path = parts[2] or '/'
        else:
            scheme = None
            authority = uri
            path = '/'
        (host, port) = splitport(authority)
        if default_port and port is None and scheme is not None:
            dport = {'http': 80, 'https': 443}.get(scheme)
            if dport is not None:
                authority = '%s:%d' % (host, dport)
        return (authority, path)

    def is_suburi(self, base, test):
        if base == test:
            return True
        if base[0] != test[0]:
            return False
        common = posixpath.commonprefix((base[1], test[1]))
        if len(common) == len(base[1]):
            return True
        return False

class HTTPPasswordMgrWithDefaultRealm(HTTPPasswordMgr):
    __qualname__ = 'HTTPPasswordMgrWithDefaultRealm'

    def find_user_password(self, realm, authuri):
        (user, password) = HTTPPasswordMgr.find_user_password(self, realm, authuri)
        if user is not None:
            return (user, password)
        return HTTPPasswordMgr.find_user_password(self, None, authuri)

class AbstractBasicAuthHandler:
    __qualname__ = 'AbstractBasicAuthHandler'
    rx = re.compile('(?:.*,)*[ \t]*([^ \t]+)[ \t]+realm=(["\']?)([^"\']*)\\2', re.I)

    def __init__(self, password_mgr=None):
        if password_mgr is None:
            password_mgr = HTTPPasswordMgr()
        self.passwd = password_mgr
        self.add_password = self.passwd.add_password
        self.retried = 0

    def reset_retry_count(self):
        self.retried = 0

    def http_error_auth_reqed(self, authreq, host, req, headers):
        authreq = headers.get(authreq, None)
        if self.retried > 5:
            raise HTTPError(req.get_full_url(), 401, 'basic auth failed', headers, None)
        if authreq:
            scheme = authreq.split()[0]
            if scheme.lower() != 'basic':
                raise ValueError("AbstractBasicAuthHandler does not support the following scheme: '%s'" % scheme)
            else:
                mo = AbstractBasicAuthHandler.rx.search(authreq)
                if mo:
                    (scheme, quote, realm) = mo.groups()
                    if quote not in ('"', "'"):
                        warnings.warn('Basic Auth Realm was unquoted', UserWarning, 2)
                    if scheme.lower() == 'basic':
                        response = self.retry_http_basic_auth(host, req, realm)
                        if response and response.code != 401:
                            self.retried = 0
                        return response

    def retry_http_basic_auth(self, host, req, realm):
        (user, pw) = self.passwd.find_user_password(realm, host)
        if pw is not None:
            raw = '%s:%s' % (user, pw)
            auth = 'Basic ' + base64.b64encode(raw.encode()).decode('ascii')
            if req.headers.get(self.auth_header, None) == auth:
                return
            req.add_unredirected_header(self.auth_header, auth)
            return self.parent.open(req, timeout=req.timeout)
        return

class HTTPBasicAuthHandler(AbstractBasicAuthHandler, BaseHandler):
    __qualname__ = 'HTTPBasicAuthHandler'
    auth_header = 'Authorization'

    def http_error_401(self, req, fp, code, msg, headers):
        url = req.full_url
        response = self.http_error_auth_reqed('www-authenticate', url, req, headers)
        self.reset_retry_count()
        return response

class ProxyBasicAuthHandler(AbstractBasicAuthHandler, BaseHandler):
    __qualname__ = 'ProxyBasicAuthHandler'
    auth_header = 'Proxy-authorization'

    def http_error_407(self, req, fp, code, msg, headers):
        authority = req.host
        response = self.http_error_auth_reqed('proxy-authenticate', authority, req, headers)
        self.reset_retry_count()
        return response

_randombytes = os.urandom

class AbstractDigestAuthHandler:
    __qualname__ = 'AbstractDigestAuthHandler'

    def __init__(self, passwd=None):
        if passwd is None:
            passwd = HTTPPasswordMgr()
        self.passwd = passwd
        self.add_password = self.passwd.add_password
        self.retried = 0
        self.nonce_count = 0
        self.last_nonce = None

    def reset_retry_count(self):
        self.retried = 0

    def http_error_auth_reqed(self, auth_header, host, req, headers):
        authreq = headers.get(auth_header, None)
        if self.retried > 5:
            raise HTTPError(req.full_url, 401, 'digest auth failed', headers, None)
        if authreq:
            scheme = authreq.split()[0]
            if scheme.lower() == 'digest':
                return self.retry_http_digest_auth(req, authreq)
            if scheme.lower() != 'basic':
                raise ValueError("AbstractDigestAuthHandler does not support the following scheme: '%s'" % scheme)

    def retry_http_digest_auth(self, req, auth):
        (token, challenge) = auth.split(' ', 1)
        chal = parse_keqv_list(filter(None, parse_http_list(challenge)))
        auth = self.get_authorization(req, chal)
        if auth:
            auth_val = 'Digest %s' % auth
            if req.headers.get(self.auth_header, None) == auth_val:
                return
            req.add_unredirected_header(self.auth_header, auth_val)
            resp = self.parent.open(req, timeout=req.timeout)
            return resp

    def get_cnonce(self, nonce):
        s = '%s:%s:%s:' % (self.nonce_count, nonce, time.ctime())
        b = s.encode('ascii') + _randombytes(8)
        dig = hashlib.sha1(b).hexdigest()
        return dig[:16]

    def get_authorization(self, req, chal):
        try:
            realm = chal['realm']
            nonce = chal['nonce']
            qop = chal.get('qop')
            algorithm = chal.get('algorithm', 'MD5')
            opaque = chal.get('opaque', None)
        except KeyError:
            return
        (H, KD) = self.get_algorithm_impls(algorithm)
        if H is None:
            return
        (user, pw) = self.passwd.find_user_password(realm, req.full_url)
        if user is None:
            return
        if req.data is not None:
            entdig = self.get_entity_digest(req.data, chal)
        else:
            entdig = None
        A1 = '%s:%s:%s' % (user, realm, pw)
        A2 = '%s:%s' % (req.get_method(), req.selector)
        if qop == 'auth':
            if nonce == self.last_nonce:
                pass
            else:
                self.nonce_count = 1
                self.last_nonce = nonce
            ncvalue = '%08x' % self.nonce_count
            cnonce = self.get_cnonce(nonce)
            noncebit = '%s:%s:%s:%s:%s' % (nonce, ncvalue, cnonce, qop, H(A2))
            respdig = KD(H(A1), noncebit)
        elif qop is None:
            respdig = KD(H(A1), '%s:%s' % (nonce, H(A2)))
        else:
            raise URLError("qop '%s' is not supported." % qop)
        base = 'username="%s", realm="%s", nonce="%s", uri="%s", response="%s"' % (user, realm, nonce, req.selector, respdig)
        if opaque:
            base += ', opaque="%s"' % opaque
        if entdig:
            base += ', digest="%s"' % entdig
        base += ', algorithm="%s"' % algorithm
        if qop:
            base += ', qop=auth, nc=%s, cnonce="%s"' % (ncvalue, cnonce)
        return base

    def get_algorithm_impls(self, algorithm):
        if algorithm == 'MD5':
            H = lambda x: hashlib.md5(x.encode('ascii')).hexdigest()
        elif algorithm == 'SHA':
            H = lambda x: hashlib.sha1(x.encode('ascii')).hexdigest()
        KD = lambda s, d: H('%s:%s' % (s, d))
        return (H, KD)

    def get_entity_digest(self, data, chal):
        pass

class HTTPDigestAuthHandler(BaseHandler, AbstractDigestAuthHandler):
    __qualname__ = 'HTTPDigestAuthHandler'
    auth_header = 'Authorization'
    handler_order = 490

    def http_error_401(self, req, fp, code, msg, headers):
        host = urlparse(req.full_url)[1]
        retry = self.http_error_auth_reqed('www-authenticate', host, req, headers)
        self.reset_retry_count()
        return retry

class ProxyDigestAuthHandler(BaseHandler, AbstractDigestAuthHandler):
    __qualname__ = 'ProxyDigestAuthHandler'
    auth_header = 'Proxy-Authorization'
    handler_order = 490

    def http_error_407(self, req, fp, code, msg, headers):
        host = req.host
        retry = self.http_error_auth_reqed('proxy-authenticate', host, req, headers)
        self.reset_retry_count()
        return retry

class AbstractHTTPHandler(BaseHandler):
    __qualname__ = 'AbstractHTTPHandler'

    def __init__(self, debuglevel=0):
        self._debuglevel = debuglevel

    def set_http_debuglevel(self, level):
        self._debuglevel = level

    def do_request_(self, request):
        host = request.host
        if not host:
            raise URLError('no host given')
        if request.data is not None:
            data = request.data
            if isinstance(data, str):
                msg = 'POST data should be bytes or an iterable of bytes. It cannot be of type str.'
                raise TypeError(msg)
            if not request.has_header('Content-type'):
                request.add_unredirected_header('Content-type', 'application/x-www-form-urlencoded')
            if not request.has_header('Content-length'):
                try:
                    mv = memoryview(data)
                except TypeError:
                    if isinstance(data, collections.Iterable):
                        raise ValueError('Content-Length should be specified for iterable data of type %r %r' % (type(data), data))
                request.add_unredirected_header('Content-length', '%d' % (len(mv)*mv.itemsize))
        sel_host = host
        if request.has_proxy():
            (scheme, sel) = splittype(request.selector)
            (sel_host, sel_path) = splithost(sel)
        if not request.has_header('Host'):
            request.add_unredirected_header('Host', sel_host)
        for (name, value) in self.parent.addheaders:
            name = name.capitalize()
            while not request.has_header(name):
                request.add_unredirected_header(name, value)
        return request

    def do_open(self, http_class, req, **http_conn_args):
        host = req.host
        if not host:
            raise URLError('no host given')
        h = http_class(host, timeout=req.timeout, **http_conn_args)
        headers = dict(req.unredirected_hdrs)
        headers.update(dict((k, v) for (k, v) in req.headers.items() if k not in headers))
        headers['Connection'] = 'close'
        headers = dict((name.title(), val) for (name, val) in headers.items())
        if req._tunnel_host:
            tunnel_headers = {}
            proxy_auth_hdr = 'Proxy-Authorization'
            if proxy_auth_hdr in headers:
                tunnel_headers[proxy_auth_hdr] = headers[proxy_auth_hdr]
                del headers[proxy_auth_hdr]
            h.set_tunnel(req._tunnel_host, headers=tunnel_headers)
        try:
            h.request(req.get_method(), req.selector, req.data, headers)
        except socket.error as err:
            h.close()
            raise URLError(err)
        r = h.getresponse()
        if h.sock:
            h.sock.close()
            h.sock = None
        r.url = req.get_full_url()
        r.msg = r.reason
        return r

class HTTPHandler(AbstractHTTPHandler):
    __qualname__ = 'HTTPHandler'

    def http_open(self, req):
        return self.do_open(http.client.HTTPConnection, req)

    http_request = AbstractHTTPHandler.do_request_

if hasattr(http.client, 'HTTPSConnection'):

    class HTTPSHandler(AbstractHTTPHandler):
        __qualname__ = 'HTTPSHandler'

        def __init__(self, debuglevel=0, context=None, check_hostname=None):
            AbstractHTTPHandler.__init__(self, debuglevel)
            self._context = context
            self._check_hostname = check_hostname

        def https_open(self, req):
            return self.do_open(http.client.HTTPSConnection, req, context=self._context, check_hostname=self._check_hostname)

        https_request = AbstractHTTPHandler.do_request_

    __all__.append('HTTPSHandler')

class HTTPCookieProcessor(BaseHandler):
    __qualname__ = 'HTTPCookieProcessor'

    def __init__(self, cookiejar=None):
        import http.cookiejar
        if cookiejar is None:
            cookiejar = http.cookiejar.CookieJar()
        self.cookiejar = cookiejar

    def http_request(self, request):
        self.cookiejar.add_cookie_header(request)
        return request

    def http_response(self, request, response):
        self.cookiejar.extract_cookies(response, request)
        return response

    https_request = http_request
    https_response = http_response

class UnknownHandler(BaseHandler):
    __qualname__ = 'UnknownHandler'

    def unknown_open(self, req):
        type = req.type
        raise URLError('unknown url type: %s' % type)

def parse_keqv_list(l):
    parsed = {}
    for elt in l:
        (k, v) = elt.split('=', 1)
        if v[0] == '"' and v[-1] == '"':
            v = v[1:-1]
        parsed[k] = v
    return parsed

def parse_http_list(s):
    res = []
    part = ''
    escape = quote = False
    for cur in s:
        if escape:
            part += cur
            escape = False
        if quote:
            if cur == '\\':
                escape = True
            elif cur == '"':
                quote = False
            part += cur
        if cur == ',':
            res.append(part)
            part = ''
        if cur == '"':
            quote = True
        part += cur
    if part:
        res.append(part)
    return [part.strip() for part in res]

class FileHandler(BaseHandler):
    __qualname__ = 'FileHandler'

    def file_open(self, req):
        url = req.selector
        if url[:2] == '//' and (url[2:3] != '/' and req.host) and req.host != 'localhost':
            if req.host is not self.get_names():
                raise URLError('file:// scheme is supported only on localhost')
        else:
            return self.open_local_file(req)

    names = None

    def get_names(self):
        if FileHandler.names is None:
            try:
                FileHandler.names = tuple(socket.gethostbyname_ex('localhost')[2] + socket.gethostbyname_ex(socket.gethostname())[2])
            except socket.gaierror:
                FileHandler.names = (socket.gethostbyname('localhost'),)
        return FileHandler.names

    def open_local_file(self, req):
        import email.utils
        import mimetypes
        host = req.host
        filename = req.selector
        localfile = url2pathname(filename)
        try:
            stats = os.stat(localfile)
            size = stats.st_size
            modified = email.utils.formatdate(stats.st_mtime, usegmt=True)
            mtype = mimetypes.guess_type(filename)[0]
            headers = email.message_from_string('Content-type: %s\nContent-length: %d\nLast-modified: %s\n' % (mtype or 'text/plain', size, modified))
            if host:
                (host, port) = splitport(host)
            if host:
                origurl = 'file://' + host + filename
            else:
                origurl = 'file://' + filename
            return addinfourl(open(localfile, 'rb'), headers, origurl)
        except OSError as exp:
            raise URLError(exp)
        raise URLError('file not on local host')

def _safe_gethostbyname(host):
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return

class FTPHandler(BaseHandler):
    __qualname__ = 'FTPHandler'

    def ftp_open(self, req):
        import ftplib
        import mimetypes
        host = req.host
        if not host:
            raise URLError('ftp error: no host given')
        (host, port) = splitport(host)
        if port is None:
            port = ftplib.FTP_PORT
        else:
            port = int(port)
        (user, host) = splituser(host)
        if user:
            (user, passwd) = splitpasswd(user)
        else:
            passwd = None
        host = unquote(host)
        user = user or ''
        passwd = passwd or ''
        try:
            host = socket.gethostbyname(host)
        except socket.error as msg:
            raise URLError(msg)
        (path, attrs) = splitattr(req.selector)
        dirs = path.split('/')
        dirs = list(map(unquote, dirs))
        (dirs, file) = (dirs[:-1], dirs[-1])
        if dirs and not dirs[0]:
            dirs = dirs[1:]
        try:
            fw = self.connect_ftp(user, passwd, host, port, dirs, req.timeout)
            type = file and 'I' or 'D'
            for attr in attrs:
                (attr, value) = splitvalue(attr)
                while attr.lower() == 'type' and value in ('a', 'A', 'i', 'I', 'd', 'D'):
                    type = value.upper()
            (fp, retrlen) = fw.retrfile(file, type)
            headers = ''
            mtype = mimetypes.guess_type(req.full_url)[0]
            if mtype:
                headers += 'Content-type: %s\n' % mtype
            if retrlen is not None and retrlen >= 0:
                headers += 'Content-length: %d\n' % retrlen
            headers = email.message_from_string(headers)
            return addinfourl(fp, headers, req.full_url)
        except ftplib.all_errors as exp:
            exc = URLError('ftp error: %r' % exp)
            raise exc.with_traceback(sys.exc_info()[2])

    def connect_ftp(self, user, passwd, host, port, dirs, timeout):
        return ftpwrapper(user, passwd, host, port, dirs, timeout, persistent=False)

class CacheFTPHandler(FTPHandler):
    __qualname__ = 'CacheFTPHandler'

    def __init__(self):
        self.cache = {}
        self.timeout = {}
        self.soonest = 0
        self.delay = 60
        self.max_conns = 16

    def setTimeout(self, t):
        self.delay = t

    def setMaxConns(self, m):
        self.max_conns = m

    def connect_ftp(self, user, passwd, host, port, dirs, timeout):
        key = (user, host, port, '/'.join(dirs), timeout)
        if key in self.cache:
            self.timeout[key] = time.time() + self.delay
        else:
            self.cache[key] = ftpwrapper(user, passwd, host, port, dirs, timeout)
            self.timeout[key] = time.time() + self.delay
        self.check_cache()
        return self.cache[key]

    def check_cache(self):
        t = time.time()
        if self.soonest <= t:
            for (k, v) in list(self.timeout.items()):
                while v < t:
                    self.cache[k].close()
                    del self.cache[k]
                    del self.timeout[k]
        self.soonest = min(list(self.timeout.values()))
        if len(self.cache) == self.max_conns:
            for (k, v) in list(self.timeout.items()):
                while v == self.soonest:
                    del self.cache[k]
                    del self.timeout[k]
                    break
            self.soonest = min(list(self.timeout.values()))

    def clear_cache(self):
        for conn in self.cache.values():
            conn.close()
        self.cache.clear()
        self.timeout.clear()

MAXFTPCACHE = 10
if os.name == 'nt':
    from nturl2path import url2pathname, pathname2url
else:

    def url2pathname(pathname):
        return unquote(pathname)

    def pathname2url(pathname):
        return quote(pathname)

ftpcache = {}

class URLopener:
    __qualname__ = 'URLopener'
    _URLopener__tempfiles = None
    version = 'Python-urllib/%s' % __version__

    def __init__(self, proxies=None, **x509):
        msg = '%(class)s style of invoking requests is deprecated. Use newer urlopen functions/methods' % {'class': self.__class__.__name__}
        warnings.warn(msg, DeprecationWarning, stacklevel=3)
        if proxies is None:
            proxies = getproxies()
        self.proxies = proxies
        self.key_file = x509.get('key_file')
        self.cert_file = x509.get('cert_file')
        self.addheaders = [('User-Agent', self.version)]
        self._URLopener__tempfiles = []
        self._URLopener__unlink = os.unlink
        self.tempcache = None
        self.ftpcache = ftpcache

    def __del__(self):
        self.close()

    def close(self):
        self.cleanup()

    def cleanup(self):
        if self._URLopener__tempfiles:
            for file in self._URLopener__tempfiles:
                try:
                    self._URLopener__unlink(file)
                except OSError:
                    pass
            del self._URLopener__tempfiles[:]
        if self.tempcache:
            self.tempcache.clear()

    def addheader(self, *args):
        self.addheaders.append(args)

    def open(self, fullurl, data=None):
        fullurl = unwrap(to_bytes(fullurl))
        fullurl = quote(fullurl, safe="%/:=&?~#+!$,;'@()*[]|")
        if self.tempcache and fullurl in self.tempcache:
            (filename, headers) = self.tempcache[fullurl]
            fp = open(filename, 'rb')
            return addinfourl(fp, headers, fullurl)
        (urltype, url) = splittype(fullurl)
        if not urltype:
            urltype = 'file'
        if urltype in self.proxies:
            proxy = self.proxies[urltype]
            (urltype, proxyhost) = splittype(proxy)
            (host, selector) = splithost(proxyhost)
            url = (host, fullurl)
        else:
            proxy = None
        name = 'open_' + urltype
        self.type = urltype
        name = name.replace('-', '_')
        if proxy:
            return self.open_unknown_proxy(proxy, fullurl, data)
        return self.open_unknown(fullurl, data)
        try:
            if data is None:
                return getattr(self, name)(url)
            return getattr(self, name)(url, data)
        except HTTPError:
            raise
        except socket.error as msg:
            raise IOError('socket error', msg).with_traceback(sys.exc_info()[2])

    def open_unknown(self, fullurl, data=None):
        (type, url) = splittype(fullurl)
        raise IOError('url error', 'unknown url type', type)

    def open_unknown_proxy(self, proxy, fullurl, data=None):
        (type, url) = splittype(fullurl)
        raise IOError('url error', 'invalid proxy for %s' % type, proxy)

    def retrieve(self, url, filename=None, reporthook=None, data=None):
        url = unwrap(to_bytes(url))
        if self.tempcache and url in self.tempcache:
            return self.tempcache[url]
        (type, url1) = splittype(url)
        if filename is None and (not type or type == 'file'):
            try:
                fp = self.open_local_file(url1)
                hdrs = fp.info()
                fp.close()
                return (url2pathname(splithost(url1)[1]), hdrs)
            except IOError as msg:
                pass
        fp = self.open(url, data)
        try:
            headers = fp.info()
            if filename:
                tfp = open(filename, 'wb')
            else:
                import tempfile
                (garbage, path) = splittype(url)
                (garbage, path) = splithost(path or '')
                (path, garbage) = splitquery(path or '')
                (path, garbage) = splitattr(path or '')
                suffix = os.path.splitext(path)[1]
                (fd, filename) = tempfile.mkstemp(suffix)
                self._URLopener__tempfiles.append(filename)
                tfp = os.fdopen(fd, 'wb')
            try:
                result = (filename, headers)
                if self.tempcache is not None:
                    self.tempcache[url] = result
                bs = 8192
                size = -1
                read = 0
                blocknum = 0
                if 'content-length' in headers:
                    size = int(headers['Content-Length'])
                if reporthook:
                    reporthook(blocknum, bs, size)
                while True:
                    block = fp.read(bs)
                    if not block:
                        break
                    read += len(block)
                    tfp.write(block)
                    blocknum += 1
                    if reporthook:
                        reporthook(blocknum, bs, size)
            finally:
                tfp.close()
        finally:
            fp.close()
        if size >= 0 and read < size:
            raise ContentTooShortError('retrieval incomplete: got only %i out of %i bytes' % (read, size), result)
        return result

    def _open_generic_http(self, connection_factory, url, data):
        user_passwd = None
        proxy_passwd = None
        if isinstance(url, str):
            (host, selector) = splithost(url)
            if host:
                (user_passwd, host) = splituser(host)
                host = unquote(host)
            realhost = host
        else:
            (host, selector) = url
            (proxy_passwd, host) = splituser(host)
            (urltype, rest) = splittype(selector)
            url = rest
            user_passwd = None
            if urltype.lower() != 'http':
                realhost = None
            else:
                (realhost, rest) = splithost(rest)
                if realhost:
                    (user_passwd, realhost) = splituser(realhost)
                if user_passwd:
                    selector = '%s://%s%s' % (urltype, realhost, rest)
                if proxy_bypass(realhost):
                    host = realhost
        if not host:
            raise IOError('http error', 'no host given')
        if proxy_passwd:
            proxy_passwd = unquote(proxy_passwd)
            proxy_auth = base64.b64encode(proxy_passwd.encode()).decode('ascii')
        else:
            proxy_auth = None
        if user_passwd:
            user_passwd = unquote(user_passwd)
            auth = base64.b64encode(user_passwd.encode()).decode('ascii')
        else:
            auth = None
        http_conn = connection_factory(host)
        headers = {}
        if proxy_auth:
            headers['Proxy-Authorization'] = 'Basic %s' % proxy_auth
        if auth:
            headers['Authorization'] = 'Basic %s' % auth
        if realhost:
            headers['Host'] = realhost
        headers['Connection'] = 'close'
        for (header, value) in self.addheaders:
            headers[header] = value
        if data is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
            http_conn.request('POST', selector, data, headers)
        else:
            http_conn.request('GET', selector, headers=headers)
        try:
            response = http_conn.getresponse()
        except http.client.BadStatusLine:
            raise URLError('http protocol error: bad status line')
        if 200 <= response.status < 300:
            return addinfourl(response, response.msg, 'http:' + url, response.status)
        return self.http_error(url, response.fp, response.status, response.reason, response.msg, data)

    def open_http(self, url, data=None):
        return self._open_generic_http(http.client.HTTPConnection, url, data)

    def http_error(self, url, fp, errcode, errmsg, headers, data=None):
        name = 'http_error_%d' % errcode
        if hasattr(self, name):
            method = getattr(self, name)
            if data is None:
                result = method(url, fp, errcode, errmsg, headers)
            else:
                result = method(url, fp, errcode, errmsg, headers, data)
            if result:
                return result
        return self.http_error_default(url, fp, errcode, errmsg, headers)

    def http_error_default(self, url, fp, errcode, errmsg, headers):
        fp.close()
        raise HTTPError(url, errcode, errmsg, headers, None)

    if _have_ssl:

        def _https_connection(self, host):
            return http.client.HTTPSConnection(host, key_file=self.key_file, cert_file=self.cert_file)

        def open_https(self, url, data=None):
            return self._open_generic_http(self._https_connection, url, data)

    def open_file(self, url):
        if not isinstance(url, str):
            raise URLError('file error: proxy support for file protocol currently not implemented')
        if url[:2] == '//' and url[2:3] != '/' and url[2:12].lower() != 'localhost/':
            raise ValueError('file:// scheme is supported only on localhost')
        else:
            return self.open_local_file(url)

    def open_local_file(self, url):
        import email.utils
        import mimetypes
        (host, file) = splithost(url)
        localname = url2pathname(file)
        try:
            stats = os.stat(localname)
        except OSError as e:
            raise URLError(e.strerror, e.filename)
        size = stats.st_size
        modified = email.utils.formatdate(stats.st_mtime, usegmt=True)
        mtype = mimetypes.guess_type(url)[0]
        headers = email.message_from_string('Content-Type: %s\nContent-Length: %d\nLast-modified: %s\n' % (mtype or 'text/plain', size, modified))
        if not host:
            urlfile = file
            if file[:1] == '/':
                urlfile = 'file://' + file
            return addinfourl(open(localname, 'rb'), headers, urlfile)
        (host, port) = splitport(host)
        if not port and socket.gethostbyname(host) in (localhost(),) + thishost():
            urlfile = file
            if file[:1] == '/':
                urlfile = 'file://' + file
            elif file[:2] == './':
                raise ValueError('local file url may start with / or file:. Unknown url of type: %s' % url)
            return addinfourl(open(localname, 'rb'), headers, urlfile)
        raise URLError('local file error: not on local host')

    def open_ftp(self, url):
        if not isinstance(url, str):
            raise URLError('ftp error: proxy support for ftp protocol currently not implemented')
        import mimetypes
        (host, path) = splithost(url)
        if not host:
            raise URLError('ftp error: no host given')
        (host, port) = splitport(host)
        (user, host) = splituser(host)
        if user:
            (user, passwd) = splitpasswd(user)
        else:
            passwd = None
        host = unquote(host)
        user = unquote(user or '')
        passwd = unquote(passwd or '')
        host = socket.gethostbyname(host)
        if not port:
            import ftplib
            port = ftplib.FTP_PORT
        else:
            port = int(port)
        (path, attrs) = splitattr(path)
        path = unquote(path)
        dirs = path.split('/')
        (dirs, file) = (dirs[:-1], dirs[-1])
        if dirs and not dirs[0]:
            dirs = dirs[1:]
        if dirs and not dirs[0]:
            dirs[0] = '/'
        key = (user, host, port, '/'.join(dirs))
        if len(self.ftpcache) > MAXFTPCACHE:
            for k in self.ftpcache.keys():
                while k != key:
                    v = self.ftpcache[k]
                    del self.ftpcache[k]
                    v.close()
        try:
            if key not in self.ftpcache:
                self.ftpcache[key] = ftpwrapper(user, passwd, host, port, dirs)
            if not file:
                type = 'D'
            else:
                type = 'I'
            for attr in attrs:
                (attr, value) = splitvalue(attr)
                while attr.lower() == 'type' and value in ('a', 'A', 'i', 'I', 'd', 'D'):
                    type = value.upper()
            (fp, retrlen) = self.ftpcache[key].retrfile(file, type)
            mtype = mimetypes.guess_type('ftp:' + url)[0]
            headers = ''
            if mtype:
                headers += 'Content-Type: %s\n' % mtype
            if retrlen is not None and retrlen >= 0:
                headers += 'Content-Length: %d\n' % retrlen
            headers = email.message_from_string(headers)
            return addinfourl(fp, headers, 'ftp:' + url)
        except ftperrors() as exp:
            raise URLError('ftp error %r' % exp).with_traceback(sys.exc_info()[2])

    def open_data(self, url, data=None):
        if not isinstance(url, str):
            raise URLError('data error: proxy support for data protocol currently not implemented')
        try:
            (type, data) = url.split(',', 1)
        except ValueError:
            raise IOError('data error', 'bad data URL')
        if not type:
            type = 'text/plain;charset=US-ASCII'
        semi = type.rfind(';')
        if semi >= 0 and '=' not in type[semi:]:
            encoding = type[semi + 1:]
            type = type[:semi]
        else:
            encoding = ''
        msg = []
        msg.append('Date: %s' % time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(time.time())))
        msg.append('Content-type: %s' % type)
        if encoding == 'base64':
            data = base64.decodebytes(data.encode('ascii')).decode('latin-1')
        else:
            data = unquote(data)
        msg.append('Content-Length: %d' % len(data))
        msg.append('')
        msg.append(data)
        msg = '\n'.join(msg)
        headers = email.message_from_string(msg)
        f = io.StringIO(msg)
        return addinfourl(f, headers, url)

class FancyURLopener(URLopener):
    __qualname__ = 'FancyURLopener'

    def __init__(self, *args, **kwargs):
        URLopener.__init__(self, *args, **kwargs)
        self.auth_cache = {}
        self.tries = 0
        self.maxtries = 10

    def http_error_default(self, url, fp, errcode, errmsg, headers):
        return addinfourl(fp, headers, 'http:' + url, errcode)

    def http_error_302(self, url, fp, errcode, errmsg, headers, data=None):
        if self.maxtries and self.tries >= self.maxtries:
            if hasattr(self, 'http_error_500'):
                meth = self.http_error_500
            else:
                meth = self.http_error_default
            self.tries = 0
            return meth(url, fp, 500, 'Internal Server Error: Redirect Recursion', headers)
        result = self.redirect_internal(url, fp, errcode, errmsg, headers, data)
        self.tries = 0
        return result

    def redirect_internal(self, url, fp, errcode, errmsg, headers, data):
        if 'location' in headers:
            newurl = headers['location']
        elif 'uri' in headers:
            newurl = headers['uri']
        else:
            return
        fp.close()
        newurl = urljoin(self.type + ':' + url, newurl)
        urlparts = urlparse(newurl)
        if urlparts.scheme not in ('http', 'https', 'ftp', ''):
            raise HTTPError(newurl, errcode, errmsg + " Redirection to url '%s' is not allowed." % newurl, headers, fp)
        return self.open(newurl)

    def http_error_301(self, url, fp, errcode, errmsg, headers, data=None):
        return self.http_error_302(url, fp, errcode, errmsg, headers, data)

    def http_error_303(self, url, fp, errcode, errmsg, headers, data=None):
        return self.http_error_302(url, fp, errcode, errmsg, headers, data)

    def http_error_307(self, url, fp, errcode, errmsg, headers, data=None):
        if data is None:
            return self.http_error_302(url, fp, errcode, errmsg, headers, data)
        return self.http_error_default(url, fp, errcode, errmsg, headers)

    def http_error_401(self, url, fp, errcode, errmsg, headers, data=None, retry=False):
        if 'www-authenticate' not in headers:
            URLopener.http_error_default(self, url, fp, errcode, errmsg, headers)
        stuff = headers['www-authenticate']
        match = re.match('[ \t]*([^ \t]+)[ \t]+realm="([^"]*)"', stuff)
        if not match:
            URLopener.http_error_default(self, url, fp, errcode, errmsg, headers)
        (scheme, realm) = match.groups()
        if scheme.lower() != 'basic':
            URLopener.http_error_default(self, url, fp, errcode, errmsg, headers)
        if not retry:
            URLopener.http_error_default(self, url, fp, errcode, errmsg, headers)
        name = 'retry_' + self.type + '_basic_auth'
        if data is None:
            return getattr(self, name)(url, realm)
        return getattr(self, name)(url, realm, data)

    def http_error_407(self, url, fp, errcode, errmsg, headers, data=None, retry=False):
        if 'proxy-authenticate' not in headers:
            URLopener.http_error_default(self, url, fp, errcode, errmsg, headers)
        stuff = headers['proxy-authenticate']
        match = re.match('[ \t]*([^ \t]+)[ \t]+realm="([^"]*)"', stuff)
        if not match:
            URLopener.http_error_default(self, url, fp, errcode, errmsg, headers)
        (scheme, realm) = match.groups()
        if scheme.lower() != 'basic':
            URLopener.http_error_default(self, url, fp, errcode, errmsg, headers)
        if not retry:
            URLopener.http_error_default(self, url, fp, errcode, errmsg, headers)
        name = 'retry_proxy_' + self.type + '_basic_auth'
        if data is None:
            return getattr(self, name)(url, realm)
        return getattr(self, name)(url, realm, data)

    def retry_proxy_http_basic_auth(self, url, realm, data=None):
        (host, selector) = splithost(url)
        newurl = 'http://' + host + selector
        proxy = self.proxies['http']
        (urltype, proxyhost) = splittype(proxy)
        (proxyhost, proxyselector) = splithost(proxyhost)
        i = proxyhost.find('@') + 1
        proxyhost = proxyhost[i:]
        (user, passwd) = self.get_user_passwd(proxyhost, realm, i)
        if not (user or passwd):
            return
        proxyhost = '%s:%s@%s' % (quote(user, safe=''), quote(passwd, safe=''), proxyhost)
        self.proxies['http'] = 'http://' + proxyhost + proxyselector
        if data is None:
            return self.open(newurl)
        return self.open(newurl, data)

    def retry_proxy_https_basic_auth(self, url, realm, data=None):
        (host, selector) = splithost(url)
        newurl = 'https://' + host + selector
        proxy = self.proxies['https']
        (urltype, proxyhost) = splittype(proxy)
        (proxyhost, proxyselector) = splithost(proxyhost)
        i = proxyhost.find('@') + 1
        proxyhost = proxyhost[i:]
        (user, passwd) = self.get_user_passwd(proxyhost, realm, i)
        if not (user or passwd):
            return
        proxyhost = '%s:%s@%s' % (quote(user, safe=''), quote(passwd, safe=''), proxyhost)
        self.proxies['https'] = 'https://' + proxyhost + proxyselector
        if data is None:
            return self.open(newurl)
        return self.open(newurl, data)

    def retry_http_basic_auth(self, url, realm, data=None):
        (host, selector) = splithost(url)
        i = host.find('@') + 1
        host = host[i:]
        (user, passwd) = self.get_user_passwd(host, realm, i)
        if not (user or passwd):
            return
        host = '%s:%s@%s' % (quote(user, safe=''), quote(passwd, safe=''), host)
        newurl = 'http://' + host + selector
        if data is None:
            return self.open(newurl)
        return self.open(newurl, data)

    def retry_https_basic_auth(self, url, realm, data=None):
        (host, selector) = splithost(url)
        i = host.find('@') + 1
        host = host[i:]
        (user, passwd) = self.get_user_passwd(host, realm, i)
        if not (user or passwd):
            return
        host = '%s:%s@%s' % (quote(user, safe=''), quote(passwd, safe=''), host)
        newurl = 'https://' + host + selector
        if data is None:
            return self.open(newurl)
        return self.open(newurl, data)

    def get_user_passwd(self, host, realm, clear_cache=0):
        key = realm + '@' + host.lower()
        if key in self.auth_cache:
            if clear_cache:
                del self.auth_cache[key]
            else:
                return self.auth_cache[key]
        (user, passwd) = self.prompt_user_passwd(host, realm)
        if user or passwd:
            self.auth_cache[key] = (user, passwd)
        return (user, passwd)

    def prompt_user_passwd(self, host, realm):
        import getpass
        try:
            user = input('Enter username for %s at %s: ' % (realm, host))
            passwd = getpass.getpass('Enter password for %s in %s at %s: ' % (user, realm, host))
            return (user, passwd)
        except KeyboardInterrupt:
            print()
            return (None, None)

_localhost = None

def localhost():
    global _localhost
    if _localhost is None:
        _localhost = socket.gethostbyname('localhost')
    return _localhost

_thishost = None

def thishost():
    global _thishost
    if _thishost is None:
        try:
            _thishost = tuple(socket.gethostbyname_ex(socket.gethostname())[2])
        except socket.gaierror:
            _thishost = tuple(socket.gethostbyname_ex('localhost')[2])
    return _thishost

_ftperrors = None

def ftperrors():
    global _ftperrors
    if _ftperrors is None:
        import ftplib
        _ftperrors = ftplib.all_errors
    return _ftperrors

_noheaders = None

def noheaders():
    global _noheaders
    if _noheaders is None:
        _noheaders = email.message_from_string('')
    return _noheaders

class ftpwrapper:
    __qualname__ = 'ftpwrapper'

    def __init__(self, user, passwd, host, port, dirs, timeout=None, persistent=True):
        self.user = user
        self.passwd = passwd
        self.host = host
        self.port = port
        self.dirs = dirs
        self.timeout = timeout
        self.refcount = 0
        self.keepalive = persistent
        self.init()

    def init(self):
        import ftplib
        self.busy = 0
        self.ftp = ftplib.FTP()
        self.ftp.connect(self.host, self.port, self.timeout)
        self.ftp.login(self.user, self.passwd)
        _target = '/'.join(self.dirs)
        self.ftp.cwd(_target)

    def retrfile(self, file, type):
        import ftplib
        self.endtransfer()
        if type in ('d', 'D'):
            cmd = 'TYPE A'
            isdir = 1
        else:
            cmd = 'TYPE ' + type
            isdir = 0
        try:
            self.ftp.voidcmd(cmd)
        except ftplib.all_errors:
            self.init()
            self.ftp.voidcmd(cmd)
        conn = None
        if file and not isdir:
            try:
                cmd = 'RETR ' + file
                (conn, retrlen) = self.ftp.ntransfercmd(cmd)
            except ftplib.error_perm as reason:
                while str(reason)[:3] != '550':
                    raise URLError('ftp error: %r' % reason).with_traceback(sys.exc_info()[2])
        if not conn:
            self.ftp.voidcmd('TYPE A')
            if file:
                pwd = self.ftp.pwd()
                try:
                    self.ftp.cwd(file)
                except ftplib.error_perm as reason:
                    raise URLError('ftp error: %r' % reason) from reason
                finally:
                    self.ftp.cwd(pwd)
                cmd = 'LIST ' + file
            else:
                cmd = 'LIST'
            (conn, retrlen) = self.ftp.ntransfercmd(cmd)
        self.busy = 1
        ftpobj = addclosehook(conn.makefile('rb'), self.file_close)
        conn.close()
        return (ftpobj, retrlen)

    def endtransfer(self):
        self.busy = 0

    def close(self):
        self.keepalive = False
        if self.refcount <= 0:
            self.real_close()

    def file_close(self):
        self.endtransfer()
        if self.refcount <= 0 and not self.keepalive:
            self.real_close()

    def real_close(self):
        self.endtransfer()
        try:
            self.ftp.close()
        except ftperrors():
            pass

def getproxies_environment():
    proxies = {}
    for (name, value) in os.environ.items():
        name = name.lower()
        while value and name[-6:] == '_proxy':
            proxies[name[:-6]] = value
    return proxies

def proxy_bypass_environment(host):
    no_proxy = os.environ.get('no_proxy', '') or os.environ.get('NO_PROXY', '')
    if no_proxy == '*':
        return 1
    (hostonly, port) = splitport(host)
    no_proxy_list = [proxy.strip() for proxy in no_proxy.split(',')]
    for name in no_proxy_list:
        while name and (hostonly.endswith(name) or host.endswith(name)):
            return 1
    return 0

def _proxy_bypass_macosx_sysconf(host, proxy_settings):
    from fnmatch import fnmatch
    (hostonly, port) = splitport(host)

    def ip2num(ipAddr):
        parts = ipAddr.split('.')
        parts = list(map(int, parts))
        if len(parts) != 4:
            parts = (parts + [0, 0, 0, 0])[:4]
        return parts[0] << 24 | parts[1] << 16 | parts[2] << 8 | parts[3]

    if '.' not in host and proxy_settings['exclude_simple']:
        return True
    hostIP = None
    for value in proxy_settings.get('exceptions', ()):
        if not value:
            pass
        m = re.match('(\\d+(?:\\.\\d+)*)(/\\d+)?', value)
        if m is not None:
            if hostIP is None:
                try:
                    hostIP = socket.gethostbyname(hostonly)
                    hostIP = ip2num(hostIP)
                except socket.error:
                    continue
            base = ip2num(m.group(1))
            mask = m.group(2)
            if mask is None:
                mask = 8*(m.group(1).count('.') + 1)
            else:
                mask = int(mask[1:])
            mask = 32 - mask
            if hostIP >> mask == base >> mask:
                return True
                while fnmatch(host, value):
                    return True
        else:
            while fnmatch(host, value):
                return True
    return False

if sys.platform == 'darwin':
    from _scproxy import _get_proxy_settings, _get_proxies

    def proxy_bypass_macosx_sysconf(host):
        proxy_settings = _get_proxy_settings()
        return _proxy_bypass_macosx_sysconf(host, proxy_settings)

    def getproxies_macosx_sysconf():
        return _get_proxies()

    def proxy_bypass(host):
        if getproxies_environment():
            return proxy_bypass_environment(host)
        return proxy_bypass_macosx_sysconf(host)

    def getproxies():
        return getproxies_environment() or getproxies_macosx_sysconf()

else:
    getproxies = getproxies_environment
    proxy_bypass = proxy_bypass_environment
