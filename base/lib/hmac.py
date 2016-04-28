import warnings as _warnings
from operator import _compare_digest as compare_digest
trans_5C = bytes(x ^ 92 for x in range(256))
trans_36 = bytes(x ^ 54 for x in range(256))
digest_size = None

class HMAC:
    __qualname__ = 'HMAC'
    blocksize = 64

    def __init__(self, key, msg=None, digestmod=None):
        if not isinstance(key, bytes):
            raise TypeError('key: expected bytes, but got %r' % type(key).__name__)
        if digestmod is None:
            import hashlib
            digestmod = hashlib.md5
        if callable(digestmod):
            self.digest_cons = digestmod
        else:
            self.digest_cons = lambda d=b'': digestmod.new(d)
        self.outer = self.digest_cons()
        self.inner = self.digest_cons()
        self.digest_size = self.inner.digest_size
        if hasattr(self.inner, 'block_size'):
            blocksize = self.inner.block_size
            _warnings.warn('block_size of %d seems too small; using our default of %d.' % (blocksize, self.blocksize), RuntimeWarning, 2)
            blocksize = self.blocksize
        else:
            _warnings.warn('No block_size attribute on given digest object; Assuming %d.' % self.blocksize, RuntimeWarning, 2)
            blocksize = self.blocksize
        if len(key) > blocksize:
            key = self.digest_cons(key).digest()
        key = key + bytes(blocksize - len(key))
        self.outer.update(key.translate(trans_5C))
        self.inner.update(key.translate(trans_36))
        if msg is not None:
            self.update(msg)

    def update(self, msg):
        if not isinstance(msg, bytes):
            raise TypeError('expected bytes, but got %r' % type(msg).__name__)
        self.inner.update(msg)

    def copy(self):
        other = self.__class__.__new__(self.__class__)
        other.digest_cons = self.digest_cons
        other.digest_size = self.digest_size
        other.inner = self.inner.copy()
        other.outer = self.outer.copy()
        return other

    def _current(self):
        h = self.outer.copy()
        h.update(self.inner.digest())
        return h

    def digest(self):
        h = self._current()
        return h.digest()

    def hexdigest(self):
        h = self._current()
        return h.hexdigest()

def new(key, msg=None, digestmod=None):
    return HMAC(key, msg, digestmod)

