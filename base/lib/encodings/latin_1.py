import codecs

class Codec(codecs.Codec):
    __qualname__ = 'Codec'
    encode = codecs.latin_1_encode
    decode = codecs.latin_1_decode

class IncrementalEncoder(codecs.IncrementalEncoder):
    __qualname__ = 'IncrementalEncoder'

    def encode(self, input, final=False):
        return codecs.latin_1_encode(input, self.errors)[0]

class IncrementalDecoder(codecs.IncrementalDecoder):
    __qualname__ = 'IncrementalDecoder'

    def decode(self, input, final=False):
        return codecs.latin_1_decode(input, self.errors)[0]

class StreamWriter(Codec, codecs.StreamWriter):
    __qualname__ = 'StreamWriter'

class StreamReader(Codec, codecs.StreamReader):
    __qualname__ = 'StreamReader'

class StreamConverter(StreamWriter, StreamReader):
    __qualname__ = 'StreamConverter'
    encode = codecs.latin_1_decode
    decode = codecs.latin_1_encode

def getregentry():
    return codecs.CodecInfo(name='iso8859-1', encode=Codec.encode, decode=Codec.decode, incrementalencoder=IncrementalEncoder, incrementaldecoder=IncrementalDecoder, streamreader=StreamReader, streamwriter=StreamWriter)

