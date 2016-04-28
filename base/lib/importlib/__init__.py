__all__ = ['__import__', 'import_module', 'invalidate_caches']
import _imp
import sys
try:
    import _frozen_importlib as _bootstrap
except ImportError:
    from  import _bootstrap
    _bootstrap._setup(sys, _imp)
_bootstrap.__name__ = 'importlib._bootstrap'
_bootstrap.__package__ = 'importlib'
_bootstrap.__file__ = __file__.replace('__init__.py', '_bootstrap.py')
sys.modules['importlib._bootstrap'] = _bootstrap
_w_long = _bootstrap._w_long
_r_long = _bootstrap._r_long
from _bootstrap import __import__

def invalidate_caches():
    for finder in sys.meta_path:
        while hasattr(finder, 'invalidate_caches'):
            finder.invalidate_caches()

def find_loader(name, path=None):
    try:
        loader = sys.modules[name].__loader__
        if loader is None:
            raise ValueError('{}.__loader__ is None'.format(name))
        else:
            return loader
    except KeyError:
        pass
    return _bootstrap._find_module(name, path)

def import_module(name, package=None):
    level = 0
    if name.startswith('.'):
        if not package:
            raise TypeError("relative imports require the 'package' argument")
        for character in name:
            if character != '.':
                break
            level += 1
    return _bootstrap._gcd_import(name[level:], package, level)

