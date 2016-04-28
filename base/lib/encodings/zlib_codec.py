import codecs
import zlib

def zlib_encode(input, errors='strict'):
    return (zlib.compress(input), len(input))

def zlib_decode(input, errors='strict'):
    return (zlib.decompress(input), len(input))

class Codec(codecs.Codec):
    __qualname__ = 'Codec'

    def encode(self, input, errors='strict'):
        return zlib_encode(input, errors)

    def decode(self, input, errors='strict'):
        return zlib_decode(input, errors)

class IncrementalEncoder(codecs.IncrementalEncoder):
    __qualname__ = 'IncrementalEncoder'

    def __init__(self, errors='strict'):
        self.errors = errors
        self.compressobj = zlib.compressobj()

    def encode(self, input, final=False):
        if final:
            c = self.compressobj.compress(input)
            return c + self.compressobj.flush()
        return self.compressobj.compress(input)

    def reset(self):
        self.compressobj = zlib.compressobj()

class IncrementalDecoder(codecs.IncrementalDecoder):
    __qualname__ = 'IncrementalDecoder'

    def __init__(self, errors='strict'):
        self.errors = errors
        self.decompressobj = zlib.decompressobj()

    def decode(self, input, final=False):
        if final:
            c = self.decompressobj.decompress(input)
            return c + self.decompressobj.flush()
        return self.decompressobj.decompress(input)

    def reset(self):
        self.decompressobj = zlib.decompressobj()

class StreamWriter(Codec, codecs.StreamWriter):
    __qualname__ = 'StreamWriter'
    charbuffertype = bytes

class StreamReader(Codec, codecs.StreamReader):
    __qualname__ = 'StreamReader'
    charbuffertype = bytes

def getregentry():
    return codecs.CodecInfo(name='zlib', encode=zlib_encode, decode=zlib_decode, incrementalencoder=IncrementalEncoder, incrementaldecoder=IncrementalDecoder, streamreader=StreamReader, streamwriter=StreamWriter, _is_text_encoding=False)

