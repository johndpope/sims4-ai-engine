import codecs

class Codec(codecs.Codec):
    __qualname__ = 'Codec'
    encode = codecs.unicode_internal_encode
    decode = codecs.unicode_internal_decode

class IncrementalEncoder(codecs.IncrementalEncoder):
    __qualname__ = 'IncrementalEncoder'

    def encode(self, input, final=False):
        return codecs.unicode_internal_encode(input, self.errors)[0]

class IncrementalDecoder(codecs.IncrementalDecoder):
    __qualname__ = 'IncrementalDecoder'

    def decode(self, input, final=False):
        return codecs.unicode_internal_decode(input, self.errors)[0]

class StreamWriter(Codec, codecs.StreamWriter):
    __qualname__ = 'StreamWriter'

class StreamReader(Codec, codecs.StreamReader):
    __qualname__ = 'StreamReader'

def getregentry():
    return codecs.CodecInfo(name='unicode-internal', encode=Codec.encode, decode=Codec.decode, incrementalencoder=IncrementalEncoder, incrementaldecoder=IncrementalDecoder, streamwriter=StreamWriter, streamreader=StreamReader)

