import _codecs_iso2022
import codecs
import _multibytecodec as mbc
codec = _codecs_iso2022.getcodec('iso2022_jp_ext')

class Codec(codecs.Codec):
    __qualname__ = 'Codec'
    encode = codec.encode
    decode = codec.decode

class IncrementalEncoder(mbc.MultibyteIncrementalEncoder, codecs.IncrementalEncoder):
    __qualname__ = 'IncrementalEncoder'
    codec = codec

class IncrementalDecoder(mbc.MultibyteIncrementalDecoder, codecs.IncrementalDecoder):
    __qualname__ = 'IncrementalDecoder'
    codec = codec

class StreamReader(Codec, mbc.MultibyteStreamReader, codecs.StreamReader):
    __qualname__ = 'StreamReader'
    codec = codec

class StreamWriter(Codec, mbc.MultibyteStreamWriter, codecs.StreamWriter):
    __qualname__ = 'StreamWriter'
    codec = codec

def getregentry():
    return codecs.CodecInfo(name='iso2022_jp_ext', encode=Codec().encode, decode=Codec().decode, incrementalencoder=IncrementalEncoder, incrementaldecoder=IncrementalDecoder, streamreader=StreamReader, streamwriter=StreamWriter)

