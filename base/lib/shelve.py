from pickle import Pickler, Unpickler
from io import BytesIO
import collections
__all__ = ['Shelf', 'BsdDbShelf', 'DbfilenameShelf', 'open']

class _ClosedDict(collections.MutableMapping):
    __qualname__ = '_ClosedDict'

    def closed(self, *args):
        raise ValueError('invalid operation on closed shelf')

    __iter__ = __len__ = __getitem__ = __setitem__ = __delitem__ = keys = closed

    def __repr__(self):
        return '<Closed Dictionary>'

class Shelf(collections.MutableMapping):
    __qualname__ = 'Shelf'

    def __init__(self, dict, protocol=None, writeback=False, keyencoding='utf-8'):
        self.dict = dict
        if protocol is None:
            protocol = 3
        self._protocol = protocol
        self.writeback = writeback
        self.cache = {}
        self.keyencoding = keyencoding

    def __iter__(self):
        for k in self.dict.keys():
            yield k.decode(self.keyencoding)

    def __len__(self):
        return len(self.dict)

    def __contains__(self, key):
        return key.encode(self.keyencoding) in self.dict

    def get(self, key, default=None):
        if key.encode(self.keyencoding) in self.dict:
            return self[key]
        return default

    def __getitem__(self, key):
        try:
            value = self.cache[key]
        except KeyError:
            f = BytesIO(self.dict[key.encode(self.keyencoding)])
            value = Unpickler(f).load()
            if self.writeback:
                self.cache[key] = value
        return value

    def __setitem__(self, key, value):
        if self.writeback:
            self.cache[key] = value
        f = BytesIO()
        p = Pickler(f, self._protocol)
        p.dump(value)
        self.dict[key.encode(self.keyencoding)] = f.getvalue()

    def __delitem__(self, key):
        del self.dict[key.encode(self.keyencoding)]
        try:
            del self.cache[key]
        except KeyError:
            pass

    def close(self):
        self.sync()
        try:
            self.dict.close()
        except AttributeError:
            pass
        try:
            self.dict = _ClosedDict()
        except (NameError, TypeError):
            self.dict = None

    def __del__(self):
        if not hasattr(self, 'writeback'):
            return
        self.close()

    def sync(self):
        if self.writeback and self.cache:
            self.writeback = False
            for (key, entry) in self.cache.items():
                self[key] = entry
            self.writeback = True
            self.cache = {}
        if hasattr(self.dict, 'sync'):
            self.dict.sync()

class BsdDbShelf(Shelf):
    __qualname__ = 'BsdDbShelf'

    def __init__(self, dict, protocol=None, writeback=False, keyencoding='utf-8'):
        Shelf.__init__(self, dict, protocol, writeback, keyencoding)

    def set_location(self, key):
        (key, value) = self.dict.set_location(key)
        f = BytesIO(value)
        return (key.decode(self.keyencoding), Unpickler(f).load())

    def next(self):
        (key, value) = next(self.dict)
        f = BytesIO(value)
        return (key.decode(self.keyencoding), Unpickler(f).load())

    def previous(self):
        (key, value) = self.dict.previous()
        f = BytesIO(value)
        return (key.decode(self.keyencoding), Unpickler(f).load())

    def first(self):
        (key, value) = self.dict.first()
        f = BytesIO(value)
        return (key.decode(self.keyencoding), Unpickler(f).load())

    def last(self):
        (key, value) = self.dict.last()
        f = BytesIO(value)
        return (key.decode(self.keyencoding), Unpickler(f).load())

class DbfilenameShelf(Shelf):
    __qualname__ = 'DbfilenameShelf'

    def __init__(self, filename, flag='c', protocol=None, writeback=False):
        import dbm
        Shelf.__init__(self, dbm.open(filename, flag), protocol, writeback)

def open(filename, flag='c', protocol=None, writeback=False):
    return DbfilenameShelf(filename, flag, protocol, writeback)

