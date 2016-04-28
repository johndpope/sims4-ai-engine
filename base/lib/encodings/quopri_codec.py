import codecs
import quopri
from io import BytesIO

def quopri_encode(input, errors='strict'):
    f = BytesIO(input)
    g = BytesIO()
    quopri.encode(f, g, 1)
    return (g.getvalue(), len(input))

def quopri_decode(input, errors='strict'):
    f = BytesIO(input)
    g = BytesIO()
    quopri.decode(f, g)
    return (g.getvalue(), len(input))

class Codec(codecs.Codec):
    __qualname__ = 'Codec'

    def encode(self, input, errors='strict'):
        return quopri_encode(input, errors)

    def decode(self, input, errors='strict'):
        return quopri_decode(input, errors)

class IncrementalEncoder(codecs.IncrementalEncoder):
    __qualname__ = 'IncrementalEncoder'

    def encode(self, input, final=False):
        return quopri_encode(input, self.errors)[0]

class IncrementalDecoder(codecs.IncrementalDecoder):
    __qualname__ = 'IncrementalDecoder'

    def decode(self, input, final=False):
        return quopri_decode(input, self.errors)[0]

class StreamWriter(Codec, codecs.StreamWriter):
    __qualname__ = 'StreamWriter'
    charbuffertype = bytes

class StreamReader(Codec, codecs.StreamReader):
    __qualname__ = 'StreamReader'
    charbuffertype = bytes

def getregentry():
    return codecs.CodecInfo(name='quopri', encode=quopri_encode, decode=quopri_decode, incrementalencoder=IncrementalEncoder, incrementaldecoder=IncrementalDecoder, streamwriter=StreamWriter, streamreader=StreamReader, _is_text_encoding=False)

