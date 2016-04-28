from codecs import mbcs_encode, mbcs_decode
import codecs
encode = mbcs_encode

def decode(input, errors='strict'):
    return mbcs_decode(input, errors, True)

class IncrementalEncoder(codecs.IncrementalEncoder):
    __qualname__ = 'IncrementalEncoder'

    def encode(self, input, final=False):
        return mbcs_encode(input, self.errors)[0]

class IncrementalDecoder(codecs.BufferedIncrementalDecoder):
    __qualname__ = 'IncrementalDecoder'
    _buffer_decode = mbcs_decode

class StreamWriter(codecs.StreamWriter):
    __qualname__ = 'StreamWriter'
    encode = mbcs_encode

class StreamReader(codecs.StreamReader):
    __qualname__ = 'StreamReader'
    decode = mbcs_decode

def getregentry():
    return codecs.CodecInfo(name='mbcs', encode=encode, decode=decode, incrementalencoder=IncrementalEncoder, incrementaldecoder=IncrementalDecoder, streamreader=StreamReader, streamwriter=StreamWriter)

