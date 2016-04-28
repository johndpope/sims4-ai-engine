__author__ = 'kenton@google.com (Kenton Varda)'
import struct
from google.protobuf.internal import wire_format
_POS_INF = inf
_NEG_INF = -_POS_INF

def _VarintSize(value):
    if value <= 127:
        return 1
    if value <= 16383:
        return 2
    if value <= 2097151:
        return 3
    if value <= 268435455:
        return 4
    if value <= 34359738367:
        return 5
    if value <= 4398046511103:
        return 6
    if value <= 562949953421311:
        return 7
    if value <= 72057594037927935:
        return 8
    if value <= 9223372036854775807:
        return 9
    return 10

def _SignedVarintSize(value):
    if value < 0:
        return 10
    if value <= 127:
        return 1
    if value <= 16383:
        return 2
    if value <= 2097151:
        return 3
    if value <= 268435455:
        return 4
    if value <= 34359738367:
        return 5
    if value <= 4398046511103:
        return 6
    if value <= 562949953421311:
        return 7
    if value <= 72057594037927935:
        return 8
    if value <= 9223372036854775807:
        return 9
    return 10

def _TagSize(field_number):
    return _VarintSize(wire_format.PackTag(field_number, 0))

def _SimpleSizer(compute_value_size):

    def SpecificSizer(field_number, is_repeated, is_packed):
        tag_size = _TagSize(field_number)
        if is_packed:
            local_VarintSize = _VarintSize

            def PackedFieldSize(value):
                result = 0
                for element in value:
                    result += compute_value_size(element)
                return result + local_VarintSize(result) + tag_size

            return PackedFieldSize
        if is_repeated:

            def RepeatedFieldSize(value):
                result = tag_size*len(value)
                for element in value:
                    result += compute_value_size(element)
                return result

            return RepeatedFieldSize

        def FieldSize(value):
            return tag_size + compute_value_size(value)

        return FieldSize

    return SpecificSizer

def _ModifiedSizer(compute_value_size, modify_value):

    def SpecificSizer(field_number, is_repeated, is_packed):
        tag_size = _TagSize(field_number)
        if is_packed:
            local_VarintSize = _VarintSize

            def PackedFieldSize(value):
                result = 0
                for element in value:
                    result += compute_value_size(modify_value(element))
                return result + local_VarintSize(result) + tag_size

            return PackedFieldSize
        if is_repeated:

            def RepeatedFieldSize(value):
                result = tag_size*len(value)
                for element in value:
                    result += compute_value_size(modify_value(element))
                return result

            return RepeatedFieldSize

        def FieldSize(value):
            return tag_size + compute_value_size(modify_value(value))

        return FieldSize

    return SpecificSizer

def _FixedSizer(value_size):

    def SpecificSizer(field_number, is_repeated, is_packed):
        tag_size = _TagSize(field_number)
        if is_packed:
            local_VarintSize = _VarintSize

            def PackedFieldSize(value):
                result = len(value)*value_size
                return result + local_VarintSize(result) + tag_size

            return PackedFieldSize
        if is_repeated:
            element_size = value_size + tag_size

            def RepeatedFieldSize(value):
                return len(value)*element_size

            return RepeatedFieldSize
        field_size = value_size + tag_size

        def FieldSize(value):
            return field_size

        return FieldSize

    return SpecificSizer

Int32Sizer = Int64Sizer = EnumSizer = _SimpleSizer(_SignedVarintSize)
UInt32Sizer = UInt64Sizer = _SimpleSizer(_VarintSize)
SInt32Sizer = SInt64Sizer = _ModifiedSizer(_SignedVarintSize, wire_format.ZigZagEncode)
Fixed32Sizer = SFixed32Sizer = FloatSizer = _FixedSizer(4)
Fixed64Sizer = SFixed64Sizer = DoubleSizer = _FixedSizer(8)
BoolSizer = _FixedSizer(1)

def StringSizer(field_number, is_repeated, is_packed):
    tag_size = _TagSize(field_number)
    local_VarintSize = _VarintSize
    local_len = len
    if is_repeated:

        def RepeatedFieldSize(value):
            result = tag_size*len(value)
            for element in value:
                l = local_len(element.encode('utf-8'))
                result += local_VarintSize(l) + l
            return result

        return RepeatedFieldSize

    def FieldSize(value):
        l = local_len(value.encode('utf-8'))
        return tag_size + local_VarintSize(l) + l

    return FieldSize

def BytesSizer(field_number, is_repeated, is_packed):
    tag_size = _TagSize(field_number)
    local_VarintSize = _VarintSize
    local_len = len
    if is_repeated:

        def RepeatedFieldSize(value):
            result = tag_size*len(value)
            for element in value:
                l = local_len(element)
                result += local_VarintSize(l) + l
            return result

        return RepeatedFieldSize

    def FieldSize(value):
        l = local_len(value)
        return tag_size + local_VarintSize(l) + l

    return FieldSize

def GroupSizer(field_number, is_repeated, is_packed):
    tag_size = _TagSize(field_number)*2
    if is_repeated:

        def RepeatedFieldSize(value):
            result = tag_size*len(value)
            for element in value:
                result += element.ByteSize()
            return result

        return RepeatedFieldSize

    def FieldSize(value):
        return tag_size + value.ByteSize()

    return FieldSize

def MessageSizer(field_number, is_repeated, is_packed):
    tag_size = _TagSize(field_number)
    local_VarintSize = _VarintSize
    if is_repeated:

        def RepeatedFieldSize(value):
            result = tag_size*len(value)
            for element in value:
                l = element.ByteSize()
                result += local_VarintSize(l) + l
            return result

        return RepeatedFieldSize

    def FieldSize(value):
        l = value.ByteSize()
        return tag_size + local_VarintSize(l) + l

    return FieldSize

def MessageSetItemSizer(field_number):
    static_size = _TagSize(1)*2 + _TagSize(2) + _VarintSize(field_number) + _TagSize(3)
    local_VarintSize = _VarintSize

    def FieldSize(value):
        l = value.ByteSize()
        return static_size + local_VarintSize(l) + l

    return FieldSize

def _VarintEncoder():
    local_chr = chr

    def EncodeVarint(write, value):
        bits = value & 127
        value >>= 7
        while value:
            write(local_chr(128 | bits))
            bits = value & 127
            value >>= 7
        return write(local_chr(bits))

    return EncodeVarint

def _SignedVarintEncoder():
    local_chr = chr

    def EncodeSignedVarint(write, value):
        if value < 0:
            value += 18446744073709551616
        bits = value & 127
        value >>= 7
        while value:
            write(local_chr(128 | bits))
            bits = value & 127
            value >>= 7
        return write(local_chr(bits))

    return EncodeSignedVarint

_EncodeVarint = _VarintEncoder()
_EncodeSignedVarint = _SignedVarintEncoder()

def _VarintBytes(value):
    pieces = []
    _EncodeVarint(pieces.append, value)
    return ''.join(pieces)

def TagBytes(field_number, wire_type):
    return _VarintBytes(wire_format.PackTag(field_number, wire_type))

def _SimpleEncoder(wire_type, encode_value, compute_value_size):

    def SpecificEncoder(field_number, is_repeated, is_packed):
        if is_packed:
            tag_bytes = TagBytes(field_number, wire_format.WIRETYPE_LENGTH_DELIMITED)
            local_EncodeVarint = _EncodeVarint

            def EncodePackedField(write, value):
                write(tag_bytes)
                size = 0
                for element in value:
                    size += compute_value_size(element)
                local_EncodeVarint(write, size)
                for element in value:
                    encode_value(write, element)

            return EncodePackedField
        if is_repeated:
            tag_bytes = TagBytes(field_number, wire_type)

            def EncodeRepeatedField(write, value):
                for element in value:
                    write(tag_bytes)
                    encode_value(write, element)

            return EncodeRepeatedField
        tag_bytes = TagBytes(field_number, wire_type)

        def EncodeField(write, value):
            write(tag_bytes)
            return encode_value(write, value)

        return EncodeField

    return SpecificEncoder

def _ModifiedEncoder(wire_type, encode_value, compute_value_size, modify_value):

    def SpecificEncoder(field_number, is_repeated, is_packed):
        if is_packed:
            tag_bytes = TagBytes(field_number, wire_format.WIRETYPE_LENGTH_DELIMITED)
            local_EncodeVarint = _EncodeVarint

            def EncodePackedField(write, value):
                write(tag_bytes)
                size = 0
                for element in value:
                    size += compute_value_size(modify_value(element))
                local_EncodeVarint(write, size)
                for element in value:
                    encode_value(write, modify_value(element))

            return EncodePackedField
        if is_repeated:
            tag_bytes = TagBytes(field_number, wire_type)

            def EncodeRepeatedField(write, value):
                for element in value:
                    write(tag_bytes)
                    encode_value(write, modify_value(element))

            return EncodeRepeatedField
        tag_bytes = TagBytes(field_number, wire_type)

        def EncodeField(write, value):
            write(tag_bytes)
            return encode_value(write, modify_value(value))

        return EncodeField

    return SpecificEncoder

def _StructPackEncoder(wire_type, format):
    value_size = struct.calcsize(format)

    def SpecificEncoder(field_number, is_repeated, is_packed):
        local_struct_pack = struct.pack
        if is_packed:
            tag_bytes = TagBytes(field_number, wire_format.WIRETYPE_LENGTH_DELIMITED)
            local_EncodeVarint = _EncodeVarint

            def EncodePackedField(write, value):
                write(tag_bytes)
                local_EncodeVarint(write, len(value)*value_size)
                for element in value:
                    write(local_struct_pack(format, element))

            return EncodePackedField
        if is_repeated:
            tag_bytes = TagBytes(field_number, wire_type)

            def EncodeRepeatedField(write, value):
                for element in value:
                    write(tag_bytes)
                    write(local_struct_pack(format, element))

            return EncodeRepeatedField
        tag_bytes = TagBytes(field_number, wire_type)

        def EncodeField(write, value):
            write(tag_bytes)
            return write(local_struct_pack(format, value))

        return EncodeField

    return SpecificEncoder

def _FloatingPointEncoder(wire_type, format):
    value_size = struct.calcsize(format)
    if value_size == 4:

        def EncodeNonFiniteOrRaise(write, value):
            if value == _POS_INF:
                write('\x00\x00\x80\x7f')
            elif value == _NEG_INF:
                write('\x00\x00\x80ÿ')
            elif value != value:
                write('\x00\x00À\x7f')
            else:
                raise

    elif value_size == 8:

        def EncodeNonFiniteOrRaise(write, value):
            if value == _POS_INF:
                write('\x00\x00\x00\x00\x00\x00ð\x7f')
            elif value == _NEG_INF:
                write('\x00\x00\x00\x00\x00\x00ðÿ')
            elif value != value:
                write('\x00\x00\x00\x00\x00\x00ø\x7f')
            else:
                raise

    else:
        raise ValueError("Can't encode floating-point values that are %d bytes long (only 4 or 8)" % value_size)

    def SpecificEncoder(field_number, is_repeated, is_packed):
        local_struct_pack = struct.pack
        if is_packed:
            tag_bytes = TagBytes(field_number, wire_format.WIRETYPE_LENGTH_DELIMITED)
            local_EncodeVarint = _EncodeVarint

            def EncodePackedField(write, value):
                write(tag_bytes)
                local_EncodeVarint(write, len(value)*value_size)
                for element in value:
                    try:
                        write(local_struct_pack(format, element).decode('latin-1'))
                    except SystemError:
                        EncodeNonFiniteOrRaise(write, element)

            return EncodePackedField
        if is_repeated:
            tag_bytes = TagBytes(field_number, wire_type)

            def EncodeRepeatedField(write, value):
                for element in value:
                    write(tag_bytes)
                    try:
                        write(local_struct_pack(format, element).decode('latin-1'))
                    except SystemError:
                        EncodeNonFiniteOrRaise(write, element)

            return EncodeRepeatedField
        tag_bytes = TagBytes(field_number, wire_type)

        def EncodeField(write, value):
            write(tag_bytes)
            try:
                write(local_struct_pack(format, value).decode('latin-1'))
            except SystemError:
                EncodeNonFiniteOrRaise(write, value)

        return EncodeField

    return SpecificEncoder

Int32Encoder = Int64Encoder = EnumEncoder = _SimpleEncoder(wire_format.WIRETYPE_VARINT, _EncodeSignedVarint, _SignedVarintSize)
UInt32Encoder = UInt64Encoder = _SimpleEncoder(wire_format.WIRETYPE_VARINT, _EncodeVarint, _VarintSize)
SInt32Encoder = SInt64Encoder = _ModifiedEncoder(wire_format.WIRETYPE_VARINT, _EncodeVarint, _VarintSize, wire_format.ZigZagEncode)
Fixed32Encoder = _StructPackEncoder(wire_format.WIRETYPE_FIXED32, '<I')
Fixed64Encoder = _StructPackEncoder(wire_format.WIRETYPE_FIXED64, '<Q')
SFixed32Encoder = _StructPackEncoder(wire_format.WIRETYPE_FIXED32, '<i')
SFixed64Encoder = _StructPackEncoder(wire_format.WIRETYPE_FIXED64, '<q')
FloatEncoder = _FloatingPointEncoder(wire_format.WIRETYPE_FIXED32, '<f')
DoubleEncoder = _FloatingPointEncoder(wire_format.WIRETYPE_FIXED64, '<d')

def BoolEncoder(field_number, is_repeated, is_packed):
    false_byte = chr(0)
    true_byte = chr(1)
    if is_packed:
        tag_bytes = TagBytes(field_number, wire_format.WIRETYPE_LENGTH_DELIMITED)
        local_EncodeVarint = _EncodeVarint

        def EncodePackedField(write, value):
            write(tag_bytes)
            local_EncodeVarint(write, len(value))
            for element in value:
                if element:
                    write(true_byte)
                else:
                    write(false_byte)

        return EncodePackedField
    if is_repeated:
        tag_bytes = TagBytes(field_number, wire_format.WIRETYPE_VARINT)

        def EncodeRepeatedField(write, value):
            for element in value:
                write(tag_bytes)
                if element:
                    write(true_byte)
                else:
                    write(false_byte)

        return EncodeRepeatedField
    tag_bytes = TagBytes(field_number, wire_format.WIRETYPE_VARINT)

    def EncodeField(write, value):
        write(tag_bytes)
        if value:
            return write(true_byte)
        return write(false_byte)

    return EncodeField

def StringEncoder(field_number, is_repeated, is_packed):
    tag = TagBytes(field_number, wire_format.WIRETYPE_LENGTH_DELIMITED)
    local_EncodeVarint = _EncodeVarint
    local_len = len
    if is_repeated:

        def EncodeRepeatedField(write, value):
            for element in value:
                encoded = value
                write(tag)
                local_EncodeVarint(write, local_len(encoded))
                write(encoded)

        return EncodeRepeatedField

    def EncodeField(write, value):
        encoded = value
        write(tag)
        local_EncodeVarint(write, local_len(encoded))
        return write(encoded)

    return EncodeField

def BytesEncoder(field_number, is_repeated, is_packed):
    tag = TagBytes(field_number, wire_format.WIRETYPE_LENGTH_DELIMITED)
    local_EncodeVarint = _EncodeVarint
    local_len = len
    if is_repeated:

        def EncodeRepeatedField(write, value):
            for element in value:
                write(tag)
                local_EncodeVarint(write, local_len(element))
                write(element.decode('latin-1'))

        return EncodeRepeatedField

    def EncodeField(write, value):
        write(tag)
        local_EncodeVarint(write, local_len(value))
        return write(value.decode('latin-1'))

    return EncodeField

def GroupEncoder(field_number, is_repeated, is_packed):
    start_tag = TagBytes(field_number, wire_format.WIRETYPE_START_GROUP)
    end_tag = TagBytes(field_number, wire_format.WIRETYPE_END_GROUP)
    if is_repeated:

        def EncodeRepeatedField(write, value):
            for element in value:
                write(start_tag)
                element._InternalSerialize(write)
                write(end_tag)

        return EncodeRepeatedField

    def EncodeField(write, value):
        write(start_tag)
        value._InternalSerialize(write)
        return write(end_tag)

    return EncodeField

def MessageEncoder(field_number, is_repeated, is_packed):
    tag = TagBytes(field_number, wire_format.WIRETYPE_LENGTH_DELIMITED)
    local_EncodeVarint = _EncodeVarint
    if is_repeated:

        def EncodeRepeatedField(write, value):
            for element in value:
                write(tag)
                local_EncodeVarint(write, element.ByteSize())
                element._InternalSerialize(write)

        return EncodeRepeatedField

    def EncodeField(write, value):
        write(tag)
        local_EncodeVarint(write, value.ByteSize())
        return value._InternalSerialize(write)

    return EncodeField

def MessageSetItemEncoder(field_number):
    start_bytes = ''.join([TagBytes(1, wire_format.WIRETYPE_START_GROUP), TagBytes(2, wire_format.WIRETYPE_VARINT), _VarintBytes(field_number), TagBytes(3, wire_format.WIRETYPE_LENGTH_DELIMITED)])
    end_bytes = TagBytes(1, wire_format.WIRETYPE_END_GROUP)
    local_EncodeVarint = _EncodeVarint

    def EncodeField(write, value):
        write(start_bytes)
        local_EncodeVarint(write, value.ByteSize())
        value._InternalSerialize(write)
        return write(end_bytes)

    return EncodeField

