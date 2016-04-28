import codecs

class Codec(codecs.Codec):
    __qualname__ = 'Codec'

    def encode(self, input, errors='strict'):
        raise UnicodeError('undefined encoding')

    def decode(self, input, errors='strict'):
        raise UnicodeError('undefined encoding')

class IncrementalEncoder(codecs.IncrementalEncoder):
    __qualname__ = 'IncrementalEncoder'

    def encode(self, input, final=False):
        raise UnicodeError('undefined encoding')

class IncrementalDecoder(codecs.IncrementalDecoder):
    __qualname__ = 'IncrementalDecoder'

    def decode(self, input, final=False):
        raise UnicodeError('undefined encoding')

class StreamWriter(Codec, codecs.StreamWriter):
    __qualname__ = 'StreamWriter'

class StreamReader(Codec, codecs.StreamReader):
    __qualname__ = 'StreamReader'

def getregentry():
    return codecs.CodecInfo(name='undefined', encode=Codec().encode, decode=Codec().decode, incrementalencoder=IncrementalEncoder, incrementaldecoder=IncrementalDecoder, streamwriter=StreamWriter, streamreader=StreamReader)

