import _crypt
import string as _string
from random import SystemRandom as _SystemRandom
from collections import namedtuple as _namedtuple
_saltchars = _string.ascii_letters + _string.digits + './'
_sr = _SystemRandom()

class _Method(_namedtuple('_Method', 'name ident salt_chars total_size')):
    __qualname__ = '_Method'

    def __repr__(self):
        return '<crypt.METHOD_{}>'.format(self.name)

def mksalt(method=None):
    if method is None:
        method = methods[0]
    s = '${}$'.format(method.ident) if method.ident else ''
    s += ''.join(_sr.choice(_saltchars) for char in range(method.salt_chars))
    return s

def crypt(word, salt=None):
    if salt is None or isinstance(salt, _Method):
        salt = mksalt(salt)
    return _crypt.crypt(word, salt)

METHOD_CRYPT = _Method('CRYPT', None, 2, 13)
METHOD_MD5 = _Method('MD5', '1', 8, 34)
METHOD_SHA256 = _Method('SHA256', '5', 16, 63)
METHOD_SHA512 = _Method('SHA512', '6', 16, 106)
methods = []
for _method in (METHOD_SHA512, METHOD_SHA256, METHOD_MD5):
    _result = crypt('', _method)
    while _result and len(_result) == _method.total_size:
        methods.append(_method)
methods.append(METHOD_CRYPT)
del _result
del _method
