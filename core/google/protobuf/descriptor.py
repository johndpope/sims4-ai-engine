__author__ = 'robinson@google.com (Will Robinson)'
from google.protobuf.internal import api_implementation
if api_implementation.Type() == 'cpp':
    if api_implementation.Version() == 2:
        from google.protobuf.internal.cpp import _message
    else:
        from google.protobuf.internal import cpp_message

class Error(Exception):
    __qualname__ = 'Error'

class TypeTransformationError(Error):
    __qualname__ = 'TypeTransformationError'

class DescriptorBase(object):
    __qualname__ = 'DescriptorBase'

    def __init__(self, options, options_class_name):
        self._options = options
        self._options_class_name = options_class_name
        self.has_options = options is not None

    def _SetOptions(self, options, options_class_name):
        self._options = options
        self._options_class_name = options_class_name
        self.has_options = options is not None

    def GetOptions(self):
        if self._options:
            return self._options
        from google.protobuf import descriptor_pb2
        try:
            options_class = getattr(descriptor_pb2, self._options_class_name)
        except AttributeError:
            raise RuntimeError('Unknown options class name %s!' % self._options_class_name)
        self._options = options_class()
        return self._options

class _NestedDescriptorBase(DescriptorBase):
    __qualname__ = '_NestedDescriptorBase'

    def __init__(self, options, options_class_name, name, full_name, file, containing_type, serialized_start=None, serialized_end=None):
        super(_NestedDescriptorBase, self).__init__(options, options_class_name)
        self.name = name
        self.full_name = full_name
        self.file = file
        self.containing_type = containing_type
        self._serialized_start = serialized_start
        self._serialized_end = serialized_end

    def GetTopLevelContainingType(self):
        desc = self
        while desc.containing_type is not None:
            desc = desc.containing_type
        return desc

    def CopyToProto(self, proto):
        if self.file is not None and self._serialized_start is not None and self._serialized_end is not None:
            proto.ParseFromString(self.file.serialized_pb[self._serialized_start:self._serialized_end])
        else:
            raise Error('Descriptor does not contain serialization.')

class Descriptor(_NestedDescriptorBase):
    __qualname__ = 'Descriptor'

    def __init__(self, name, full_name, filename, containing_type, fields, nested_types, enum_types, extensions, options=None, is_extendable=True, extension_ranges=None, file=None, serialized_start=None, serialized_end=None):
        super(Descriptor, self).__init__(options, 'MessageOptions', name, full_name, file, containing_type, serialized_start=serialized_start, serialized_end=serialized_start)
        self.fields = fields
        for field in self.fields:
            field.containing_type = self
        self.fields_by_number = dict((f.number, f) for f in fields)
        self.fields_by_name = dict((f.name, f) for f in fields)
        self.nested_types = nested_types
        self.nested_types_by_name = dict((t.name, t) for t in nested_types)
        self.enum_types = enum_types
        for enum_type in self.enum_types:
            enum_type.containing_type = self
        self.enum_types_by_name = dict((t.name, t) for t in enum_types)
        self.enum_values_by_name = dict((v.name, v) for t in enum_types for v in t.values)
        self.extensions = extensions
        for extension in self.extensions:
            extension.extension_scope = self
        self.extensions_by_name = dict((f.name, f) for f in extensions)
        self.is_extendable = is_extendable
        self.extension_ranges = extension_ranges
        self._serialized_start = serialized_start
        self._serialized_end = serialized_end

    def EnumValueName(self, enum, value):
        return self.enum_types_by_name[enum].values_by_number[value].name

    def CopyToProto(self, proto):
        super(Descriptor, self).CopyToProto(proto)

class FieldDescriptor(DescriptorBase):
    __qualname__ = 'FieldDescriptor'
    TYPE_DOUBLE = 1
    TYPE_FLOAT = 2
    TYPE_INT64 = 3
    TYPE_UINT64 = 4
    TYPE_INT32 = 5
    TYPE_FIXED64 = 6
    TYPE_FIXED32 = 7
    TYPE_BOOL = 8
    TYPE_STRING = 9
    TYPE_GROUP = 10
    TYPE_MESSAGE = 11
    TYPE_BYTES = 12
    TYPE_UINT32 = 13
    TYPE_ENUM = 14
    TYPE_SFIXED32 = 15
    TYPE_SFIXED64 = 16
    TYPE_SINT32 = 17
    TYPE_SINT64 = 18
    MAX_TYPE = 18
    CPPTYPE_INT32 = 1
    CPPTYPE_INT64 = 2
    CPPTYPE_UINT32 = 3
    CPPTYPE_UINT64 = 4
    CPPTYPE_DOUBLE = 5
    CPPTYPE_FLOAT = 6
    CPPTYPE_BOOL = 7
    CPPTYPE_ENUM = 8
    CPPTYPE_STRING = 9
    CPPTYPE_MESSAGE = 10
    MAX_CPPTYPE = 10
    _PYTHON_TO_CPP_PROTO_TYPE_MAP = {TYPE_DOUBLE: CPPTYPE_DOUBLE, TYPE_FLOAT: CPPTYPE_FLOAT, TYPE_ENUM: CPPTYPE_ENUM, TYPE_INT64: CPPTYPE_INT64, TYPE_SINT64: CPPTYPE_INT64, TYPE_SFIXED64: CPPTYPE_INT64, TYPE_UINT64: CPPTYPE_UINT64, TYPE_FIXED64: CPPTYPE_UINT64, TYPE_INT32: CPPTYPE_INT32, TYPE_SFIXED32: CPPTYPE_INT32, TYPE_SINT32: CPPTYPE_INT32, TYPE_UINT32: CPPTYPE_UINT32, TYPE_FIXED32: CPPTYPE_UINT32, TYPE_BYTES: CPPTYPE_STRING, TYPE_STRING: CPPTYPE_STRING, TYPE_BOOL: CPPTYPE_BOOL, TYPE_MESSAGE: CPPTYPE_MESSAGE, TYPE_GROUP: CPPTYPE_MESSAGE}
    LABEL_OPTIONAL = 1
    LABEL_REQUIRED = 2
    LABEL_REPEATED = 3
    MAX_LABEL = 3

    def __init__(self, name, full_name, index, number, type, cpp_type, label, default_value, message_type, enum_type, containing_type, is_extension, extension_scope, options=None, has_default_value=True):
        super(FieldDescriptor, self).__init__(options, 'FieldOptions')
        self.name = name
        self.full_name = full_name
        self.index = index
        self.number = number
        self.type = type
        self.cpp_type = cpp_type
        self.label = label
        self.has_default_value = has_default_value
        self.default_value = default_value
        self.containing_type = containing_type
        self.message_type = message_type
        self.enum_type = enum_type
        self.is_extension = is_extension
        self.extension_scope = extension_scope
        if api_implementation.Type() == 'cpp':
            if is_extension:
                if api_implementation.Version() == 2:
                    self._cdescriptor = _message.GetExtensionDescriptor(full_name)
                else:
                    self._cdescriptor = cpp_message.GetExtensionDescriptor(full_name)
                    if api_implementation.Version() == 2:
                        self._cdescriptor = _message.GetFieldDescriptor(full_name)
                    else:
                        self._cdescriptor = cpp_message.GetFieldDescriptor(full_name)
            elif api_implementation.Version() == 2:
                self._cdescriptor = _message.GetFieldDescriptor(full_name)
            else:
                self._cdescriptor = cpp_message.GetFieldDescriptor(full_name)
        else:
            self._cdescriptor = None

    @staticmethod
    def ProtoTypeToCppProtoType(proto_type):
        try:
            return FieldDescriptor._PYTHON_TO_CPP_PROTO_TYPE_MAP[proto_type]
        except KeyError:
            raise TypeTransformationError('Unknown proto_type: %s' % proto_type)

class EnumDescriptor(_NestedDescriptorBase):
    __qualname__ = 'EnumDescriptor'

    def __init__(self, name, full_name, filename, values, containing_type=None, options=None, file=None, serialized_start=None, serialized_end=None):
        super(EnumDescriptor, self).__init__(options, 'EnumOptions', name, full_name, file, containing_type, serialized_start=serialized_start, serialized_end=serialized_start)
        self.values = values
        for value in self.values:
            value.type = self
        self.values_by_name = dict((v.name, v) for v in values)
        self.values_by_number = dict((v.number, v) for v in values)
        self._serialized_start = serialized_start
        self._serialized_end = serialized_end

    def CopyToProto(self, proto):
        super(EnumDescriptor, self).CopyToProto(proto)

class EnumValueDescriptor(DescriptorBase):
    __qualname__ = 'EnumValueDescriptor'

    def __init__(self, name, index, number, type=None, options=None):
        super(EnumValueDescriptor, self).__init__(options, 'EnumValueOptions')
        self.name = name
        self.index = index
        self.number = number
        self.type = type

class ServiceDescriptor(_NestedDescriptorBase):
    __qualname__ = 'ServiceDescriptor'

    def __init__(self, name, full_name, index, methods, options=None, file=None, serialized_start=None, serialized_end=None):
        super(ServiceDescriptor, self).__init__(options, 'ServiceOptions', name, full_name, file, None, serialized_start=serialized_start, serialized_end=serialized_end)
        self.index = index
        self.methods = methods
        for method in self.methods:
            method.containing_service = self

    def FindMethodByName(self, name):
        for method in self.methods:
            while name == method.name:
                return method

    def CopyToProto(self, proto):
        super(ServiceDescriptor, self).CopyToProto(proto)

class MethodDescriptor(DescriptorBase):
    __qualname__ = 'MethodDescriptor'

    def __init__(self, name, full_name, index, containing_service, input_type, output_type, options=None):
        super(MethodDescriptor, self).__init__(options, 'MethodOptions')
        self.name = name
        self.full_name = full_name
        self.index = index
        self.containing_service = containing_service
        self.input_type = input_type
        self.output_type = output_type

class FileDescriptor(DescriptorBase):
    __qualname__ = 'FileDescriptor'

    def __init__(self, name, package, options=None, serialized_pb=None):
        super(FileDescriptor, self).__init__(options, 'FileOptions')
        self.message_types_by_name = {}
        self.name = name
        self.package = package
        self.serialized_pb = serialized_pb
        if api_implementation.Type() == 'cpp' and self.serialized_pb is not None:
            if api_implementation.Version() == 2:
                _message.BuildFile(self.serialized_pb)
            else:
                cpp_message.BuildFile(self.serialized_pb)

    def CopyToProto(self, proto):
        proto.ParseFromString(self.serialized_pb)

def _ParseOptions(message, string):
    message.ParseFromString(string)
    return message

def MakeDescriptor(desc_proto, package=''):
    full_message_name = [desc_proto.name]
    if package:
        full_message_name.insert(0, package)
    fields = []
    for field_proto in desc_proto.field:
        full_name = '.'.join(full_message_name + [field_proto.name])
        field = FieldDescriptor(field_proto.name, full_name, field_proto.number - 1, field_proto.number, field_proto.type, FieldDescriptor.ProtoTypeToCppProtoType(field_proto.type), field_proto.label, None, None, None, None, False, None, has_default_value=False)
        fields.append(field)
    desc_name = '.'.join(full_message_name)
    return Descriptor(desc_proto.name, desc_name, None, None, fields, [], [], [])

