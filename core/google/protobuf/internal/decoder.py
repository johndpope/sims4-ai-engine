__author__ = 'kenton@google.com (Kenton Varda)'
import struct
from google.protobuf.internal import encoder
from google.protobuf.internal import wire_format
from google.protobuf import message
_POS_INF = inf
_NEG_INF = -_POS_INF
_NAN = _POS_INF*0
_DecodeError = message.DecodeError

def ord_py3(value):
    return value

def _VarintDecoder(mask):
    local_ord = ord_py3

    def DecodeVarint(buffer, pos):
        result = 0
        shift = 0
        while True:
            b = local_ord(buffer[pos])
            result |= (b & 127) << shift
            pos += 1
            if not b & 128:
                result &= mask
                return (result, pos)
            shift += 7
            if shift >= 64:
                raise _DecodeError('Too many bytes when decoding varint.')

    return DecodeVarint

def _SignedVarintDecoder(mask):
    local_ord = ord_py3

    def DecodeVarint(buffer, pos):
        result = 0
        shift = 0
        while True:
            b = local_ord(buffer[pos])
            result |= (b & 127) << shift
            pos += 1
            if not b & 128:
                if result > 9223372036854775807:
                    result -= 18446744073709551616
                    result |= ~mask
                else:
                    result &= mask
                return (result, pos)
            shift += 7
            if shift >= 64:
                raise _DecodeError('Too many bytes when decoding varint.')

    return DecodeVarint

_DecodeVarint = _VarintDecoder(18446744073709551615)
_DecodeSignedVarint = _SignedVarintDecoder(18446744073709551615)
_DecodeVarint32 = _VarintDecoder(4294967295)
_DecodeSignedVarint32 = _SignedVarintDecoder(4294967295)

def ReadTag(buffer, pos):
    start = pos
    while buffer[pos] & 128:
        pos += 1
    pos += 1
    return (buffer[start:pos], pos)

def _SimpleDecoder(wire_type, decode_value):

    def SpecificDecoder(field_number, is_repeated, is_packed, key, new_default):
        if is_packed:
            local_DecodeVarint = _DecodeVarint

            def DecodePackedField(buffer, pos, end, message, field_dict):
                value = field_dict.get(key)
                if value is None:
                    value = field_dict.setdefault(key, new_default(message))
                (endpoint, pos) = local_DecodeVarint(buffer, pos)
                endpoint += pos
                if endpoint > end:
                    raise _DecodeError('Truncated message.')
                while pos < endpoint:
                    (element, pos) = decode_value(buffer, pos)
                    value.append(element)
                if pos > endpoint:
                    del value[-1]
                    raise _DecodeError('Packed element was truncated.')
                return pos

            return DecodePackedField
        if is_repeated:
            tag_bytes = encoder.TagBytes(field_number, wire_type)
            tag_len = len(tag_bytes)

            def DecodeRepeatedField(buffer, pos, end, message, field_dict):
                value = field_dict.get(key)
                if value is None:
                    value = field_dict.setdefault(key, new_default(message))
                while True:
                    (element, new_pos) = decode_value(buffer, pos)
                    value.append(element)
                    pos = new_pos + tag_len
                    if buffer[new_pos:pos] != tag_bytes or new_pos >= end:
                        if new_pos > end:
                            raise _DecodeError('Truncated message.')
                        return new_pos

            return DecodeRepeatedField

        def DecodeField(buffer, pos, end, message, field_dict):
            (field_dict[key], pos) = decode_value(buffer, pos)
            if pos > end:
                del field_dict[key]
                raise _DecodeError('Truncated message.')
            return pos

        return DecodeField

    return SpecificDecoder

def _ModifiedDecoder(wire_type, decode_value, modify_value):

    def InnerDecode(buffer, pos):
        (result, new_pos) = decode_value(buffer, pos)
        return (modify_value(result), new_pos)

    return _SimpleDecoder(wire_type, InnerDecode)

def _StructPackDecoder(wire_type, format):
    value_size = struct.calcsize(format)
    local_unpack = struct.unpack

    def InnerDecode(buffer, pos):
        new_pos = pos + value_size
        result = local_unpack(format, buffer[pos:new_pos])[0]
        return (result, new_pos)

    return _SimpleDecoder(wire_type, InnerDecode)

def _FloatDecoder():
    local_unpack = struct.unpack

    def InnerDecode(buffer, pos):
        new_pos = pos + 4
        float_bytes = buffer[pos:new_pos]
        if float_bytes[3] in '\x7fÿ' and float_bytes[2] >= '\x80':
            if float_bytes[0:3] != '\x00\x00\x80':
                return (_NAN, new_pos)
            if float_bytes[3] == 'ÿ':
                return (_NEG_INF, new_pos)
            return (_POS_INF, new_pos)
        result = local_unpack('<f', float_bytes)[0]
        return (result, new_pos)

    return _SimpleDecoder(wire_format.WIRETYPE_FIXED32, InnerDecode)

def _DoubleDecoder():
    local_unpack = struct.unpack

    def InnerDecode(buffer, pos):
        new_pos = pos + 8
        double_bytes = buffer[pos:new_pos]
        if double_bytes[7] in '\x7fÿ' and double_bytes[6] >= 'ð' and double_bytes[0:7] != '\x00\x00\x00\x00\x00\x00ð':
            return (_NAN, new_pos)
        result = local_unpack('<d', double_bytes)[0]
        return (result, new_pos)

    return _SimpleDecoder(wire_format.WIRETYPE_FIXED64, InnerDecode)

Int32Decoder = EnumDecoder = _SimpleDecoder(wire_format.WIRETYPE_VARINT, _DecodeSignedVarint32)
Int64Decoder = _SimpleDecoder(wire_format.WIRETYPE_VARINT, _DecodeSignedVarint)
UInt32Decoder = _SimpleDecoder(wire_format.WIRETYPE_VARINT, _DecodeVarint32)
UInt64Decoder = _SimpleDecoder(wire_format.WIRETYPE_VARINT, _DecodeVarint)
SInt32Decoder = _ModifiedDecoder(wire_format.WIRETYPE_VARINT, _DecodeVarint32, wire_format.ZigZagDecode)
SInt64Decoder = _ModifiedDecoder(wire_format.WIRETYPE_VARINT, _DecodeVarint, wire_format.ZigZagDecode)
Fixed32Decoder = _StructPackDecoder(wire_format.WIRETYPE_FIXED32, '<I')
Fixed64Decoder = _StructPackDecoder(wire_format.WIRETYPE_FIXED64, '<Q')
SFixed32Decoder = _StructPackDecoder(wire_format.WIRETYPE_FIXED32, '<i')
SFixed64Decoder = _StructPackDecoder(wire_format.WIRETYPE_FIXED64, '<q')
FloatDecoder = _FloatDecoder()
DoubleDecoder = _DoubleDecoder()
BoolDecoder = _ModifiedDecoder(wire_format.WIRETYPE_VARINT, _DecodeVarint, bool)

def StringDecoder(field_number, is_repeated, is_packed, key, new_default):
    local_DecodeVarint = _DecodeVarint
    local_unicode = str
    if is_repeated:
        tag_bytes = encoder.TagBytes(field_number, wire_format.WIRETYPE_LENGTH_DELIMITED)
        tag_len = len(tag_bytes)

        def DecodeRepeatedField(buffer, pos, end, message, field_dict):
            value = field_dict.get(key)
            if value is None:
                value = field_dict.setdefault(key, new_default(message))
            while True:
                (size, pos) = local_DecodeVarint(buffer, pos)
                new_pos = pos + size
                if new_pos > end:
                    raise _DecodeError('Truncated string.')
                value.append(local_unicode(buffer[pos:new_pos], 'utf-8'))
                pos = new_pos + tag_len
                if buffer[new_pos:pos] != tag_bytes or new_pos == end:
                    return new_pos

        return DecodeRepeatedField

    def DecodeField(buffer, pos, end, message, field_dict):
        (size, pos) = local_DecodeVarint(buffer, pos)
        new_pos = pos + size
        if new_pos > end:
            raise _DecodeError('Truncated string.')
        field_dict[key] = local_unicode(buffer[pos:new_pos], 'utf-8')
        return new_pos

    return DecodeField

def BytesDecoder(field_number, is_repeated, is_packed, key, new_default):
    local_DecodeVarint = _DecodeVarint
    if is_repeated:
        tag_bytes = encoder.TagBytes(field_number, wire_format.WIRETYPE_LENGTH_DELIMITED)
        tag_len = len(tag_bytes)

        def DecodeRepeatedField(buffer, pos, end, message, field_dict):
            value = field_dict.get(key)
            if value is None:
                value = field_dict.setdefault(key, new_default(message))
            while True:
                (size, pos) = local_DecodeVarint(buffer, pos)
                new_pos = pos + size
                if new_pos > end:
                    raise _DecodeError('Truncated string.')
                value.append(buffer[pos:new_pos])
                pos = new_pos + tag_len
                if buffer[new_pos:pos] != tag_bytes or new_pos == end:
                    return new_pos

        return DecodeRepeatedField

    def DecodeField(buffer, pos, end, message, field_dict):
        (size, pos) = local_DecodeVarint(buffer, pos)
        new_pos = pos + size
        if new_pos > end:
            raise _DecodeError('Truncated string.')
        field_dict[key] = buffer[pos:new_pos]
        return new_pos

    return DecodeField

def GroupDecoder(field_number, is_repeated, is_packed, key, new_default):
    end_tag_bytes = encoder.TagBytes(field_number, wire_format.WIRETYPE_END_GROUP)
    end_tag_len = len(end_tag_bytes)
    if is_repeated:
        tag_bytes = encoder.TagBytes(field_number, wire_format.WIRETYPE_START_GROUP)
        tag_len = len(tag_bytes)

        def DecodeRepeatedField(buffer, pos, end, message, field_dict):
            value = field_dict.get(key)
            if value is None:
                value = field_dict.setdefault(key, new_default(message))
            while True:
                value = field_dict.get(key)
                if value is None:
                    value = field_dict.setdefault(key, new_default(message))
                pos = value.add()._InternalParse(buffer, pos, end)
                new_pos = pos + end_tag_len
                if buffer[pos:new_pos] != end_tag_bytes or new_pos > end:
                    raise _DecodeError('Missing group end tag.')
                pos = new_pos + tag_len
                if buffer[new_pos:pos] != tag_bytes or new_pos == end:
                    return new_pos

        return DecodeRepeatedField

    def DecodeField(buffer, pos, end, message, field_dict):
        value = field_dict.get(key)
        if value is None:
            value = field_dict.setdefault(key, new_default(message))
        pos = value._InternalParse(buffer, pos, end)
        new_pos = pos + end_tag_len
        if buffer[pos:new_pos] != end_tag_bytes or new_pos > end:
            raise _DecodeError('Missing group end tag.')
        return new_pos

    return DecodeField

def MessageDecoder(field_number, is_repeated, is_packed, key, new_default):
    local_DecodeVarint = _DecodeVarint
    if is_repeated:
        tag_bytes = encoder.TagBytes(field_number, wire_format.WIRETYPE_LENGTH_DELIMITED)
        tag_len = len(tag_bytes)

        def DecodeRepeatedField(buffer, pos, end, message, field_dict):
            value = field_dict.get(key)
            if value is None:
                value = field_dict.setdefault(key, new_default(message))
            while True:
                value = field_dict.get(key)
                if value is None:
                    value = field_dict.setdefault(key, new_default(message))
                (size, pos) = local_DecodeVarint(buffer, pos)
                new_pos = pos + size
                if new_pos > end:
                    raise _DecodeError('Truncated message.')
                if value.add()._InternalParse(buffer, pos, new_pos) != new_pos:
                    raise _DecodeError('Unexpected end-group tag.')
                pos = new_pos + tag_len
                if buffer[new_pos:pos] != tag_bytes or new_pos == end:
                    return new_pos

        return DecodeRepeatedField

    def DecodeField(buffer, pos, end, message, field_dict):
        value = field_dict.get(key)
        if value is None:
            value = field_dict.setdefault(key, new_default(message))
        (size, pos) = local_DecodeVarint(buffer, pos)
        new_pos = pos + size
        if new_pos > end:
            raise _DecodeError('Truncated message.')
        if value._InternalParse(buffer, pos, new_pos) != new_pos:
            raise _DecodeError('Unexpected end-group tag.')
        return new_pos

    return DecodeField

MESSAGE_SET_ITEM_TAG = encoder.TagBytes(1, wire_format.WIRETYPE_START_GROUP)

def MessageSetItemDecoder(extensions_by_number):
    type_id_tag_bytes = encoder.TagBytes(2, wire_format.WIRETYPE_VARINT)
    message_tag_bytes = encoder.TagBytes(3, wire_format.WIRETYPE_LENGTH_DELIMITED)
    item_end_tag_bytes = encoder.TagBytes(1, wire_format.WIRETYPE_END_GROUP)
    local_ReadTag = ReadTag
    local_DecodeVarint = _DecodeVarint
    local_SkipField = SkipField

    def DecodeItem(buffer, pos, end, message, field_dict):
        message_set_item_start = pos
        type_id = -1
        message_start = -1
        message_end = -1
        while True:
            (tag_bytes, pos) = local_ReadTag(buffer, pos)
            if tag_bytes == type_id_tag_bytes:
                (type_id, pos) = local_DecodeVarint(buffer, pos)
            elif tag_bytes == message_tag_bytes:
                (size, message_start) = local_DecodeVarint(buffer, pos)
                pos = message_end = message_start + size
            elif tag_bytes == item_end_tag_bytes:
                break
            else:
                pos = SkipField(buffer, pos, end, tag_bytes)
                if pos == -1:
                    raise _DecodeError('Missing group end tag.')
        if pos > end:
            raise _DecodeError('Truncated message.')
        if type_id == -1:
            raise _DecodeError('MessageSet item missing type_id.')
        if message_start == -1:
            raise _DecodeError('MessageSet item missing message.')
        extension = extensions_by_number.get(type_id)
        if extension is not None:
            value = field_dict.get(extension)
            if value is None:
                value = field_dict.setdefault(extension, extension.message_type._concrete_class())
            raise _DecodeError('Unexpected end-group tag.')
        else:
            if not message._unknown_fields:
                message._unknown_fields = []
            message._unknown_fields.append((MESSAGE_SET_ITEM_TAG, buffer[message_set_item_start:pos]))
        return pos

    return DecodeItem

def _SkipVarint(buffer, pos, end):
    while buffer[pos] & 128:
        pos += 1
    pos += 1
    if pos > end:
        raise _DecodeError('Truncated message.')
    return pos

def _SkipFixed64(buffer, pos, end):
    pos += 8
    if pos > end:
        raise _DecodeError('Truncated message.')
    return pos

def _SkipLengthDelimited(buffer, pos, end):
    (size, pos) = _DecodeVarint(buffer, pos)
    pos += size
    if pos > end:
        raise _DecodeError('Truncated message.')
    return pos

def _SkipGroup(buffer, pos, end):
    while True:
        (tag_bytes, pos) = ReadTag(buffer, pos)
        new_pos = SkipField(buffer, pos, end, tag_bytes)
        if new_pos == -1:
            return pos
        pos = new_pos

def _EndGroup(buffer, pos, end):
    return -1

def _SkipFixed32(buffer, pos, end):
    pos += 4
    if pos > end:
        raise _DecodeError('Truncated message.')
    return pos

def _RaiseInvalidWireType(buffer, pos, end):
    raise _DecodeError('Tag had invalid wire type.')

def _FieldSkipper():
    WIRETYPE_TO_SKIPPER = [_SkipVarint, _SkipFixed64, _SkipLengthDelimited, _SkipGroup, _EndGroup, _SkipFixed32, _RaiseInvalidWireType, _RaiseInvalidWireType]
    wiretype_mask = wire_format.TAG_TYPE_MASK
    local_ord = ord_py3

    def SkipField(buffer, pos, end, tag_bytes):
        wire_type = local_ord(tag_bytes[0]) & wiretype_mask
        return WIRETYPE_TO_SKIPPER[wire_type](buffer, pos, end)

    return SkipField

SkipField = _FieldSkipper()
