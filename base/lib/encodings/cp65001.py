import codecs
import functools
if not hasattr(codecs, 'code_page_encode'):
    raise LookupError('cp65001 encoding is only available on Windows')
encode = functools.partial(codecs.code_page_encode, 65001)
decode = functools.partial(codecs.code_page_decode, 65001)

class IncrementalEncoder(codecs.IncrementalEncoder):
    __qualname__ = 'IncrementalEncoder'

    def encode(self, input, final=False):
        return encode(input, self.errors)[0]

class IncrementalDecoder(codecs.BufferedIncrementalDecoder):
    __qualname__ = 'IncrementalDecoder'
    _buffer_decode = decode

class StreamWriter(codecs.StreamWriter):
    __qualname__ = 'StreamWriter'
    encode = encode

class StreamReader(codecs.StreamReader):
    __qualname__ = 'StreamReader'
    decode = decode

def getregentry():
    return codecs.CodecInfo(name='cp65001', encode=encode, decode=decode, incrementalencoder=IncrementalEncoder, incrementaldecoder=IncrementalDecoder, streamreader=StreamReader, streamwriter=StreamWriter)

