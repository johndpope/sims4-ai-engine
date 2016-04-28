import codecs
encode = codecs.utf_7_encode

def decode(input, errors='strict'):
    return codecs.utf_7_decode(input, errors, True)

class IncrementalEncoder(codecs.IncrementalEncoder):
    __qualname__ = 'IncrementalEncoder'

    def encode(self, input, final=False):
        return codecs.utf_7_encode(input, self.errors)[0]

class IncrementalDecoder(codecs.BufferedIncrementalDecoder):
    __qualname__ = 'IncrementalDecoder'
    _buffer_decode = codecs.utf_7_decode

class StreamWriter(codecs.StreamWriter):
    __qualname__ = 'StreamWriter'
    encode = codecs.utf_7_encode

class StreamReader(codecs.StreamReader):
    __qualname__ = 'StreamReader'
    decode = codecs.utf_7_decode

def getregentry():
    return codecs.CodecInfo(name='utf-7', encode=encode, decode=decode, incrementalencoder=IncrementalEncoder, incrementaldecoder=IncrementalDecoder, streamreader=StreamReader, streamwriter=StreamWriter)
