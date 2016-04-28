import codecs
encode = codecs.utf_32_be_encode

def decode(input, errors='strict'):
    return codecs.utf_32_be_decode(input, errors, True)

class IncrementalEncoder(codecs.IncrementalEncoder):
    __qualname__ = 'IncrementalEncoder'

    def encode(self, input, final=False):
        return codecs.utf_32_be_encode(input, self.errors)[0]

class IncrementalDecoder(codecs.BufferedIncrementalDecoder):
    __qualname__ = 'IncrementalDecoder'
    _buffer_decode = codecs.utf_32_be_decode

class StreamWriter(codecs.StreamWriter):
    __qualname__ = 'StreamWriter'
    encode = codecs.utf_32_be_encode

class StreamReader(codecs.StreamReader):
    __qualname__ = 'StreamReader'
    decode = codecs.utf_32_be_decode

def getregentry():
    return codecs.CodecInfo(name='utf-32-be', encode=encode, decode=decode, incrementalencoder=IncrementalEncoder, incrementaldecoder=IncrementalDecoder, streamreader=StreamReader, streamwriter=StreamWriter)

