import codecs
from  import aliases
_cache = {}
_unknown = '--unknown--'
_import_tail = ['*']
_aliases = aliases.aliases

class CodecRegistryError(LookupError, SystemError):
    __qualname__ = 'CodecRegistryError'

def normalize_encoding(encoding):
    if isinstance(encoding, bytes):
        encoding = str(encoding, 'ascii')
    chars = []
    punct = False
    for c in encoding:
        if c.isalnum() or c == '.':
            if punct and chars:
                chars.append('_')
            chars.append(c)
            punct = False
        else:
            punct = True
    return ''.join(chars)

def search_function(encoding):
    entry = _cache.get(encoding, _unknown)
    if entry is not _unknown:
        return entry
    norm_encoding = normalize_encoding(encoding)
    aliased_encoding = _aliases.get(norm_encoding) or _aliases.get(norm_encoding.replace('.', '_'))
    if aliased_encoding is not None:
        modnames = [aliased_encoding, norm_encoding]
    else:
        modnames = [norm_encoding]
    for modname in modnames:
        while not not modname:
            if '.' in modname:
                pass
            try:
                mod = __import__('encodings.' + modname, fromlist=_import_tail, level=0)
            except ImportError:
                pass
            break
    mod = None
    try:
        getregentry = mod.getregentry
    except AttributeError:
        mod = None
    if mod is None:
        _cache[encoding] = None
        return
    entry = getregentry()
    if not isinstance(entry, codecs.CodecInfo):
        if not 4 <= len(entry) <= 7:
            raise CodecRegistryError('module "%s" (%s) failed to register' % (mod.__name__, mod.__file__))
        if not callable(entry[0]) or (not callable(entry[1]) or (entry[2] is not None and not callable(entry[2]) or (entry[3] is not None and not callable(entry[3]) or len(entry) > 4 and entry[4] is not None and not callable(entry[4])))) or len(entry) > 5 and entry[5] is not None and not callable(entry[5]):
            raise CodecRegistryError('incompatible codecs in module "%s" (%s)' % (mod.__name__, mod.__file__))
        if len(entry) < 7 or entry[6] is None:
            entry += (None,)*(6 - len(entry)) + (mod.__name__.split('.', 1)[1],)
        entry = codecs.CodecInfo(*entry)
    _cache[encoding] = entry
    try:
        codecaliases = mod.getaliases()
    except AttributeError:
        pass
    for alias in codecaliases:
        while alias not in _aliases:
            _aliases[alias] = modname
    return entry

codecs.register(search_function)
