
class addbase(object):
    __qualname__ = 'addbase'

    def __init__(self, fp):
        self.fp = fp
        self.read = self.fp.read
        self.readline = self.fp.readline
        if hasattr(self.fp, 'readlines'):
            self.readlines = self.fp.readlines
        if hasattr(self.fp, 'fileno'):
            self.fileno = self.fp.fileno
        else:
            self.fileno = lambda : None

    def __iter__(self):
        return iter(self.fp)

    def __repr__(self):
        return '<%s at %r whose fp = %r>' % (self.__class__.__name__, id(self), self.fp)

    def close(self):
        if self.fp:
            self.fp.close()
        self.fp = None
        self.read = None
        self.readline = None
        self.readlines = None
        self.fileno = None
        self.__iter__ = None
        self.__next__ = None

    def __enter__(self):
        if self.fp is None:
            raise ValueError('I/O operation on closed file')
        return self

    def __exit__(self, type, value, traceback):
        self.close()

class addclosehook(addbase):
    __qualname__ = 'addclosehook'

    def __init__(self, fp, closehook, *hookargs):
        addbase.__init__(self, fp)
        self.closehook = closehook
        self.hookargs = hookargs

    def close(self):
        if self.closehook:
            self.closehook(*self.hookargs)
            self.closehook = None
            self.hookargs = None
        addbase.close(self)

class addinfo(addbase):
    __qualname__ = 'addinfo'

    def __init__(self, fp, headers):
        addbase.__init__(self, fp)
        self.headers = headers

    def info(self):
        return self.headers

class addinfourl(addbase):
    __qualname__ = 'addinfourl'

    def __init__(self, fp, headers, url, code=None):
        addbase.__init__(self, fp)
        self.headers = headers
        self.url = url
        self.code = code

    def info(self):
        return self.headers

    def getcode(self):
        return self.code

    def geturl(self):
        return self.url

