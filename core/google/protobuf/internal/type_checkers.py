__author__ = 'robinson@google.com (Will Robinson)'
from google.protobuf.internal import decoder
from google.protobuf.internal import encoder
from google.protobuf.internal import wire_format
from google.protobuf import descriptor
_FieldDescriptor = descriptor.FieldDescriptor

def GetTypeChecker(cpp_type, field_type):
    if cpp_type == _FieldDescriptor.CPPTYPE_STRING and field_type == _FieldDescriptor.TYPE_STRING:
        return UnicodeValueChecker()
    return _VALUE_CHECKERS[cpp_type]

class TypeChecker(object):
    __qualname__ = 'TypeChecker'

    def __init__(self, *acceptable_types):
        self._acceptable_types = acceptable_types

    def CheckValue(self, proposed_value):
        if not isinstance(proposed_value, self._acceptable_types):
            message = '%.1024r has type %s, but expected one of: %s' % (proposed_value, type(proposed_value), self._acceptable_types)
            raise TypeError(message)

class IntValueChecker(object):
    __qualname__ = 'IntValueChecker'

    def CheckValue(self, proposed_value):
        if not isinstance(proposed_value, int):
            message = '%.1024r has type %s, but expected one of: %s' % (proposed_value, type(proposed_value), (int, int))
            raise TypeError(message)
        if not self._MIN <= proposed_value <= self._MAX:
            raise ValueError('Value out of range: %d' % proposed_value)

class UnicodeValueChecker(object):
    __qualname__ = 'UnicodeValueChecker'

    def CheckValue(self, proposed_value):
        if not isinstance(proposed_value, str):
            if isinstance(proposed_value, bytes):
                proposed_value = proposed_value.encode('latin-1')
            else:
                message = '%.1024r has type %s, but expected one of: %s' % (proposed_value, type(proposed_value), (str, str))
                raise TypeError(message)
        if isinstance(proposed_value, str):
            try:
                proposed_value.encode('latin-1')
            except UnicodeDecodeError:
                raise ValueError("%.1024r has type str, but isn't in 7-bit ASCII encoding. Non-ASCII strings must be converted to unicode objects before being added." % proposed_value)

class Int32ValueChecker(IntValueChecker):
    __qualname__ = 'Int32ValueChecker'
    _MIN = -2147483648
    _MAX = 2147483647

class Uint32ValueChecker(IntValueChecker):
    __qualname__ = 'Uint32ValueChecker'
    _MIN = 0
    _MAX = 4294967295

class Int64ValueChecker(IntValueChecker):
    __qualname__ = 'Int64ValueChecker'
    _MIN = -9223372036854775808
    _MAX = 9223372036854775807

class Uint64ValueChecker(IntValueChecker):
    __qualname__ = 'Uint64ValueChecker'
    _MIN = 0
    _MAX = 18446744073709551615

_VALUE_CHECKERS = {_FieldDescriptor.CPPTYPE_INT32: Int32ValueChecker(), _FieldDescriptor.CPPTYPE_INT64: Int64ValueChecker(), _FieldDescriptor.CPPTYPE_UINT32: Uint32ValueChecker(), _FieldDescriptor.CPPTYPE_UINT64: Uint64ValueChecker(), _FieldDescriptor.CPPTYPE_DOUBLE: TypeChecker(float, int, int), _FieldDescriptor.CPPTYPE_FLOAT: TypeChecker(float, int, int), _FieldDescriptor.CPPTYPE_BOOL: TypeChecker(bool, int), _FieldDescriptor.CPPTYPE_ENUM: Int32ValueChecker(), _FieldDescriptor.CPPTYPE_STRING: TypeChecker(str, bytes)}
TYPE_TO_BYTE_SIZE_FN = {_FieldDescriptor.TYPE_DOUBLE: wire_format.DoubleByteSize, _FieldDescriptor.TYPE_FLOAT: wire_format.FloatByteSize, _FieldDescriptor.TYPE_INT64: wire_format.Int64ByteSize, _FieldDescriptor.TYPE_UINT64: wire_format.UInt64ByteSize, _FieldDescriptor.TYPE_INT32: wire_format.Int32ByteSize, _FieldDescriptor.TYPE_FIXED64: wire_format.Fixed64ByteSize, _FieldDescriptor.TYPE_FIXED32: wire_format.Fixed32ByteSize, _FieldDescriptor.TYPE_BOOL: wire_format.BoolByteSize, _FieldDescriptor.TYPE_STRING: wire_format.StringByteSize, _FieldDescriptor.TYPE_GROUP: wire_format.GroupByteSize, _FieldDescriptor.TYPE_MESSAGE: wire_format.MessageByteSize, _FieldDescriptor.TYPE_BYTES: wire_format.BytesByteSize, _FieldDescriptor.TYPE_UINT32: wire_format.UInt32ByteSize, _FieldDescriptor.TYPE_ENUM: wire_format.EnumByteSize, _FieldDescriptor.TYPE_SFIXED32: wire_format.SFixed32ByteSize, _FieldDescriptor.TYPE_SFIXED64: wire_format.SFixed64ByteSize, _FieldDescriptor.TYPE_SINT32: wire_format.SInt32ByteSize, _FieldDescriptor.TYPE_SINT64: wire_format.SInt64ByteSize}
TYPE_TO_ENCODER = {_FieldDescriptor.TYPE_DOUBLE: encoder.DoubleEncoder, _FieldDescriptor.TYPE_FLOAT: encoder.FloatEncoder, _FieldDescriptor.TYPE_INT64: encoder.Int64Encoder, _FieldDescriptor.TYPE_UINT64: encoder.UInt64Encoder, _FieldDescriptor.TYPE_INT32: encoder.Int32Encoder, _FieldDescriptor.TYPE_FIXED64: encoder.Fixed64Encoder, _FieldDescriptor.TYPE_FIXED32: encoder.Fixed32Encoder, _FieldDescriptor.TYPE_BOOL: encoder.BoolEncoder, _FieldDescriptor.TYPE_STRING: encoder.StringEncoder, _FieldDescriptor.TYPE_GROUP: encoder.GroupEncoder, _FieldDescriptor.TYPE_MESSAGE: encoder.MessageEncoder, _FieldDescriptor.TYPE_BYTES: encoder.BytesEncoder, _FieldDescriptor.TYPE_UINT32: encoder.UInt32Encoder, _FieldDescriptor.TYPE_ENUM: encoder.EnumEncoder, _FieldDescriptor.TYPE_SFIXED32: encoder.SFixed32Encoder, _FieldDescriptor.TYPE_SFIXED64: encoder.SFixed64Encoder, _FieldDescriptor.TYPE_SINT32: encoder.SInt32Encoder, _FieldDescriptor.TYPE_SINT64: encoder.SInt64Encoder}
TYPE_TO_SIZER = {_FieldDescriptor.TYPE_DOUBLE: encoder.DoubleSizer, _FieldDescriptor.TYPE_FLOAT: encoder.FloatSizer, _FieldDescriptor.TYPE_INT64: encoder.Int64Sizer, _FieldDescriptor.TYPE_UINT64: encoder.UInt64Sizer, _FieldDescriptor.TYPE_INT32: encoder.Int32Sizer, _FieldDescriptor.TYPE_FIXED64: encoder.Fixed64Sizer, _FieldDescriptor.TYPE_FIXED32: encoder.Fixed32Sizer, _FieldDescriptor.TYPE_BOOL: encoder.BoolSizer, _FieldDescriptor.TYPE_STRING: encoder.StringSizer, _FieldDescriptor.TYPE_GROUP: encoder.GroupSizer, _FieldDescriptor.TYPE_MESSAGE: encoder.MessageSizer, _FieldDescriptor.TYPE_BYTES: encoder.BytesSizer, _FieldDescriptor.TYPE_UINT32: encoder.UInt32Sizer, _FieldDescriptor.TYPE_ENUM: encoder.EnumSizer, _FieldDescriptor.TYPE_SFIXED32: encoder.SFixed32Sizer, _FieldDescriptor.TYPE_SFIXED64: encoder.SFixed64Sizer, _FieldDescriptor.TYPE_SINT32: encoder.SInt32Sizer, _FieldDescriptor.TYPE_SINT64: encoder.SInt64Sizer}
TYPE_TO_DECODER = {_FieldDescriptor.TYPE_DOUBLE: decoder.DoubleDecoder, _FieldDescriptor.TYPE_FLOAT: decoder.FloatDecoder, _FieldDescriptor.TYPE_INT64: decoder.Int64Decoder, _FieldDescriptor.TYPE_UINT64: decoder.UInt64Decoder, _FieldDescriptor.TYPE_INT32: decoder.Int32Decoder, _FieldDescriptor.TYPE_FIXED64: decoder.Fixed64Decoder, _FieldDescriptor.TYPE_FIXED32: decoder.Fixed32Decoder, _FieldDescriptor.TYPE_BOOL: decoder.BoolDecoder, _FieldDescriptor.TYPE_STRING: decoder.StringDecoder, _FieldDescriptor.TYPE_GROUP: decoder.GroupDecoder, _FieldDescriptor.TYPE_MESSAGE: decoder.MessageDecoder, _FieldDescriptor.TYPE_BYTES: decoder.BytesDecoder, _FieldDescriptor.TYPE_UINT32: decoder.UInt32Decoder, _FieldDescriptor.TYPE_ENUM: decoder.EnumDecoder, _FieldDescriptor.TYPE_SFIXED32: decoder.SFixed32Decoder, _FieldDescriptor.TYPE_SFIXED64: decoder.SFixed64Decoder, _FieldDescriptor.TYPE_SINT32: decoder.SInt32Decoder, _FieldDescriptor.TYPE_SINT64: decoder.SInt64Decoder}
FIELD_TYPE_TO_WIRE_TYPE = {_FieldDescriptor.TYPE_DOUBLE: wire_format.WIRETYPE_FIXED64, _FieldDescriptor.TYPE_FLOAT: wire_format.WIRETYPE_FIXED32, _FieldDescriptor.TYPE_INT64: wire_format.WIRETYPE_VARINT, _FieldDescriptor.TYPE_UINT64: wire_format.WIRETYPE_VARINT, _FieldDescriptor.TYPE_INT32: wire_format.WIRETYPE_VARINT, _FieldDescriptor.TYPE_FIXED64: wire_format.WIRETYPE_FIXED64, _FieldDescriptor.TYPE_FIXED32: wire_format.WIRETYPE_FIXED32, _FieldDescriptor.TYPE_BOOL: wire_format.WIRETYPE_VARINT, _FieldDescriptor.TYPE_STRING: wire_format.WIRETYPE_LENGTH_DELIMITED, _FieldDescriptor.TYPE_GROUP: wire_format.WIRETYPE_START_GROUP, _FieldDescriptor.TYPE_MESSAGE: wire_format.WIRETYPE_LENGTH_DELIMITED, _FieldDescriptor.TYPE_BYTES: wire_format.WIRETYPE_LENGTH_DELIMITED, _FieldDescriptor.TYPE_UINT32: wire_format.WIRETYPE_VARINT, _FieldDescriptor.TYPE_ENUM: wire_format.WIRETYPE_VARINT, _FieldDescriptor.TYPE_SFIXED32: wire_format.WIRETYPE_FIXED32, _FieldDescriptor.TYPE_SFIXED64: wire_format.WIRETYPE_FIXED64, _FieldDescriptor.TYPE_SINT32: wire_format.WIRETYPE_VARINT, _FieldDescriptor.TYPE_SINT64: wire_format.WIRETYPE_VARINT}
