import codecs

class Codec(codecs.Codec):
    __qualname__ = 'Codec'
    encode = codecs.ascii_encode
    decode = codecs.ascii_decode

class IncrementalEncoder(codecs.IncrementalEncoder):
    __qualname__ = 'IncrementalEncoder'

    def encode(self, input, final=False):
        return codecs.ascii_encode(input, self.errors)[0]

class IncrementalDecoder(codecs.IncrementalDecoder):
    __qualname__ = 'IncrementalDecoder'

    def decode(self, input, final=False):
        return codecs.ascii_decode(input, self.errors)[0]

class StreamWriter(Codec, codecs.StreamWriter):
    __qualname__ = 'StreamWriter'

class StreamReader(Codec, codecs.StreamReader):
    __qualname__ = 'StreamReader'

class StreamConverter(StreamWriter, StreamReader):
    __qualname__ = 'StreamConverter'
    encode = codecs.ascii_decode
    decode = codecs.ascii_encode

def getregentry():
    return codecs.CodecInfo(name='ascii', encode=Codec.encode, decode=Codec.decode, incrementalencoder=IncrementalEncoder, incrementaldecoder=IncrementalDecoder, streamwriter=StreamWriter, streamreader=StreamReader)

