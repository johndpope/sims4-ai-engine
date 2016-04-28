__author__ = 'petar@google.com (Petar Petrov)'
import operator
import _net_proto2___python
from google.protobuf import message
_LABEL_REPEATED = _net_proto2___python.LABEL_REPEATED
_LABEL_OPTIONAL = _net_proto2___python.LABEL_OPTIONAL
_CPPTYPE_MESSAGE = _net_proto2___python.CPPTYPE_MESSAGE
_TYPE_MESSAGE = _net_proto2___python.TYPE_MESSAGE

def cmp(a, b):
    return (a > b) - (a < b)

def cmp_to_key(mycmp):

    class K(object):
        __qualname__ = 'cmp_to_key.<locals>.K'

        def __init__(self, obj, *args):
            self.obj = obj

        def __lt__(self, other):
            return mycmp(self.obj, other.obj) < 0

        def __gt__(self, other):
            return mycmp(self.obj, other.obj) > 0

        def __eq__(self, other):
            return mycmp(self.obj, other.obj) == 0

        def __le__(self, other):
            return mycmp(self.obj, other.obj) <= 0

        def __ge__(self, other):
            return mycmp(self.obj, other.obj) >= 0

        def __ne__(self, other):
            return mycmp(self.obj, other.obj) != 0

    return K

def GetDescriptorPool():
    return _net_proto2___python.NewCDescriptorPool()

_pool = GetDescriptorPool()

def GetFieldDescriptor(full_field_name):
    return _pool.FindFieldByName(full_field_name)

def BuildFile(content):
    _net_proto2___python.BuildFile(content.encode('latin-1'))

def GetExtensionDescriptor(full_extension_name):
    return _pool.FindExtensionByName(full_extension_name)

def NewCMessage(full_message_name):
    return _net_proto2___python.NewCMessage(full_message_name)

def ScalarProperty(cdescriptor):

    def Getter(self):
        return self._cmsg.GetScalar(cdescriptor)

    def Setter(self, value):
        self._cmsg.SetScalar(cdescriptor, value)

    return property(Getter, Setter)

def CompositeProperty(cdescriptor, message_type):

    def Getter(self):
        sub_message = self._composite_fields.get(cdescriptor.name, None)
        if sub_message is None or not self._cmsg.HasFieldByDescriptor(cdescriptor):
            cmessage = self._cmsg.NewSubMessage(cdescriptor)
            sub_message = message_type._concrete_class(__cmessage=cmessage)
            self._composite_fields[cdescriptor.name] = sub_message
        return sub_message

    def Setter(self, value):
        sub_message = Getter(self)
        if type(sub_message) != type(value):
            raise TypeError('value has type {}, but expected {}'.format(type(value).__name__, type(sub_message).__name__))
        return sub_message.CopyFrom(value)

    return property(Getter, Setter)

class RepeatedScalarContainer(object):
    __qualname__ = 'RepeatedScalarContainer'
    __slots__ = ['_message', '_cfield_descriptor', '_cmsg']

    def __init__(self, msg, cfield_descriptor):
        self._message = msg
        self._cmsg = msg._cmsg
        self._cfield_descriptor = cfield_descriptor

    def append(self, value):
        self._cmsg.AddRepeatedScalar(self._cfield_descriptor, value)

    def extend(self, sequence):
        for element in sequence:
            self.append(element)

    def insert(self, key, value):
        values = self[slice(None, None, None)]
        values.insert(key, value)
        self._cmsg.AssignRepeatedScalar(self._cfield_descriptor, values)

    def remove(self, value):
        values = self[slice(None, None, None)]
        values.remove(value)
        self._cmsg.AssignRepeatedScalar(self._cfield_descriptor, values)

    def __setitem__(self, key, value):
        values = self[slice(None, None, None)]
        values[key] = value
        self._cmsg.AssignRepeatedScalar(self._cfield_descriptor, values)

    def __getitem__(self, key):
        return self._cmsg.GetRepeatedScalar(self._cfield_descriptor, key)

    def __delitem__(self, key):
        self._cmsg.DeleteRepeatedField(self._cfield_descriptor, key)

    def __len__(self):
        return len(self[slice(None, None, None)])

    def __eq__(self, other):
        if self is other:
            return True
        if not operator.isSequenceType(other):
            raise TypeError('Can only compare repeated scalar fields against sequences.')
        return other == self[slice(None, None, None)]

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        raise TypeError('unhashable object')

    def sort(self, *args, **kwargs):
        if 'sort_function' in kwargs:
            kwargs['cmp'] = kwargs.pop('sort_function')
        self._cmsg.AssignRepeatedScalar(self._cfield_descriptor, sorted(self, *args, **kwargs))

def RepeatedScalarProperty(cdescriptor):

    def Getter(self):
        container = self._composite_fields.get(cdescriptor.name, None)
        if container is None:
            container = RepeatedScalarContainer(self, cdescriptor)
            self._composite_fields[cdescriptor.name] = container
        return container

    def Setter(self, new_value):
        raise AttributeError('Assignment not allowed to repeated field "%s" in protocol message object.' % cdescriptor.name)

    doc = 'Magic attribute generated for "%s" proto field.' % cdescriptor.name
    return property(Getter, Setter, doc=doc)

class RepeatedCompositeContainer(object):
    __qualname__ = 'RepeatedCompositeContainer'
    __slots__ = ['_message', '_subclass', '_cfield_descriptor', '_cmsg']

    def __init__(self, msg, cfield_descriptor, subclass):
        self._message = msg
        self._cmsg = msg._cmsg
        self._subclass = subclass
        self._cfield_descriptor = cfield_descriptor

    def add(self, **kwargs):
        cmessage = self._cmsg.AddMessage(self._cfield_descriptor)
        return self._subclass(__cmessage=cmessage, __owner=self._message, **kwargs)

    def append(self, value):
        sub_message = self.add()
        if type(sub_message) != type(value):
            raise TypeError('value has type {}, but expected {}'.format(type(value).__name__, type(sub_message).__name__))
        return sub_message.CopyFrom(value)

    def extend(self, elem_seq):
        for message in elem_seq:
            self.add().MergeFrom(message)

    def remove(self, value):
        self.__delitem__(self[slice(None, None, None)].index(value))

    def MergeFrom(self, other):
        for message in other[:]:
            self.add().MergeFrom(message)

    def __getitem__(self, key):
        cmessages = self._cmsg.GetRepeatedMessage(self._cfield_descriptor, key)
        subclass = self._subclass
        if not isinstance(cmessages, list):
            return subclass(__cmessage=cmessages, __owner=self._message)
        return [subclass(__cmessage=m, __owner=self._message) for m in cmessages]

    def __delitem__(self, key):
        self._cmsg.DeleteRepeatedField(self._cfield_descriptor, key)

    def __len__(self):
        return self._cmsg.FieldLength(self._cfield_descriptor)

    def __eq__(self, other):
        if self is other:
            return True
        if not isinstance(other, self.__class__):
            raise TypeError('Can only compare repeated composite fields against other repeated composite fields.')
        messages = self[slice(None, None, None)]
        other_messages = other[slice(None, None, None)]
        return messages == other_messages

    def __hash__(self):
        raise TypeError('unhashable object')

    def sort(self, cmp=None, key=None, reverse=False, **kwargs):
        if cmp is None and 'sort_function' in kwargs:
            cmp = kwargs.pop('sort_function')
        if key is None:
            index_key = self.__getitem__
        else:
            index_key = lambda i: key(self[i])
        indexes = range(len(self))
        indexes.sort(cmp=cmp, key=index_key, reverse=reverse)
        for (dest, src) in enumerate(indexes):
            if dest == src:
                pass
            self._cmsg.SwapRepeatedFieldElements(self._cfield_descriptor, dest, src)
            indexes[src] = src

def RepeatedCompositeProperty(cdescriptor, message_type):

    def Getter(self):
        container = self._composite_fields.get(cdescriptor.name, None)
        if container is None:
            container = RepeatedCompositeContainer(self, cdescriptor, message_type._concrete_class)
            self._composite_fields[cdescriptor.name] = container
        return container

    def Setter(self, new_value):
        raise AttributeError('Assignment not allowed to repeated field "%s" in protocol message object.' % cdescriptor.name)

    doc = 'Magic attribute generated for "%s" proto field.' % cdescriptor.name
    return property(Getter, Setter, doc=doc)

class ExtensionDict(object):
    __qualname__ = 'ExtensionDict'

    def __init__(self, msg):
        self._message = msg
        self._cmsg = msg._cmsg
        self._values = {}

    def __setitem__(self, extension, value):
        from google.protobuf import descriptor
        if not isinstance(extension, descriptor.FieldDescriptor):
            raise KeyError('Bad extension %r.' % (extension,))
        cdescriptor = extension._cdescriptor
        if cdescriptor.label != _LABEL_OPTIONAL or cdescriptor.cpp_type == _CPPTYPE_MESSAGE:
            raise TypeError('Extension %r is repeated and/or a composite type.' % (extension.full_name,))
        self._cmsg.SetScalar(cdescriptor, value)
        self._values[extension] = value

    def __getitem__(self, extension):
        from google.protobuf import descriptor
        if not isinstance(extension, descriptor.FieldDescriptor):
            raise KeyError('Bad extension %r.' % (extension,))
        cdescriptor = extension._cdescriptor
        if cdescriptor.label != _LABEL_REPEATED and cdescriptor.cpp_type != _CPPTYPE_MESSAGE:
            return self._cmsg.GetScalar(cdescriptor)
        ext = self._values.get(extension, None)
        if ext is not None:
            return ext
        ext = self._CreateNewHandle(extension)
        self._values[extension] = ext
        return ext

    def ClearExtension(self, extension):
        from google.protobuf import descriptor
        if not isinstance(extension, descriptor.FieldDescriptor):
            raise KeyError('Bad extension %r.' % (extension,))
        self._cmsg.ClearFieldByDescriptor(extension._cdescriptor)
        if extension in self._values:
            del self._values[extension]

    def HasExtension(self, extension):
        from google.protobuf import descriptor
        if not isinstance(extension, descriptor.FieldDescriptor):
            raise KeyError('Bad extension %r.' % (extension,))
        return self._cmsg.HasFieldByDescriptor(extension._cdescriptor)

    def _FindExtensionByName(self, name):
        return self._message._extensions_by_name.get(name, None)

    def _CreateNewHandle(self, extension):
        cdescriptor = extension._cdescriptor
        if cdescriptor.label != _LABEL_REPEATED and cdescriptor.cpp_type == _CPPTYPE_MESSAGE:
            cmessage = self._cmsg.NewSubMessage(cdescriptor)
            return extension.message_type._concrete_class(__cmessage=cmessage)
        if cdescriptor.label == _LABEL_REPEATED:
            if cdescriptor.cpp_type == _CPPTYPE_MESSAGE:
                return RepeatedCompositeContainer(self._message, cdescriptor, extension.message_type._concrete_class)
            return RepeatedScalarContainer(self._message, cdescriptor)

def NewMessage(bases, message_descriptor, dictionary):
    _AddClassAttributesForNestedExtensions(message_descriptor, dictionary)
    _AddEnumValues(message_descriptor, dictionary)
    _AddDescriptors(message_descriptor, dictionary)
    return bases

def InitMessage(message_descriptor, cls):
    cls._extensions_by_name = {}
    _AddInitMethod(message_descriptor, cls)
    _AddMessageMethods(message_descriptor, cls)
    _AddPropertiesForExtensions(message_descriptor, cls)

def _AddDescriptors(message_descriptor, dictionary):
    dictionary['__descriptors'] = {}
    for field in message_descriptor.fields:
        dictionary['__descriptors'][field.name] = GetFieldDescriptor(field.full_name)
    dictionary['__slots__'] = list(dictionary['__descriptors'].keys()) + ['_cmsg', '_owner', '_composite_fields', 'Extensions', '_HACK_REFCOUNTS']

def _AddEnumValues(message_descriptor, dictionary):
    for enum_type in message_descriptor.enum_types:
        for enum_value in enum_type.values:
            dictionary[enum_value.name] = enum_value.number

def _AddClassAttributesForNestedExtensions(message_descriptor, dictionary):
    extension_dict = message_descriptor.extensions_by_name
    for (extension_name, extension_field) in extension_dict.items():
        dictionary[extension_name] = extension_field

def _AddInitMethod(message_descriptor, cls):
    for field in message_descriptor.fields:
        field_cdescriptor = cls.__descriptors[field.name]
        if field.label == _LABEL_REPEATED:
            if field.cpp_type == _CPPTYPE_MESSAGE:
                value = RepeatedCompositeProperty(field_cdescriptor, field.message_type)
            else:
                value = RepeatedScalarProperty(field_cdescriptor)
        elif field.cpp_type == _CPPTYPE_MESSAGE:
            value = CompositeProperty(field_cdescriptor, field.message_type)
        else:
            value = ScalarProperty(field_cdescriptor)
        setattr(cls, field.name, value)
        constant_name = field.name.upper() + '_FIELD_NUMBER'
        setattr(cls, constant_name, field.number)

    def Init(self, **kwargs):
        cmessage = kwargs.pop('__cmessage', None)
        if cmessage is None:
            self._cmsg = NewCMessage(message_descriptor.full_name)
        else:
            self._cmsg = cmessage
        owner = kwargs.pop('__owner', None)
        if owner is not None:
            self._owner = owner
        if message_descriptor.is_extendable:
            self.Extensions = ExtensionDict(self)
        else:
            self._HACK_REFCOUNTS = self
        self._composite_fields = {}
        for (field_name, field_value) in kwargs.items():
            field_cdescriptor = self.__descriptors.get(field_name, None)
            if field_cdescriptor is None:
                raise ValueError('Protocol message has no "%s" field.' % field_name)
            if field_cdescriptor.label == _LABEL_REPEATED:
                if field_cdescriptor.cpp_type == _CPPTYPE_MESSAGE:
                    field_name = getattr(self, field_name)
                    for val in field_value:
                        field_name.add().MergeFrom(val)
                else:
                    getattr(self, field_name).extend(field_value)
                    if field_cdescriptor.cpp_type == _CPPTYPE_MESSAGE:
                        getattr(self, field_name).MergeFrom(field_value)
                    else:
                        setattr(self, field_name, field_value)
            elif field_cdescriptor.cpp_type == _CPPTYPE_MESSAGE:
                getattr(self, field_name).MergeFrom(field_value)
            else:
                setattr(self, field_name, field_value)

    Init.__module__ = None
    Init.__doc__ = None
    cls.__init__ = Init

def _IsMessageSetExtension(field):
    return field.is_extension and (field.containing_type.has_options and (field.containing_type.GetOptions().message_set_wire_format and (field.type == _TYPE_MESSAGE and (field.message_type == field.extension_scope and field.label == _LABEL_OPTIONAL))))

def _AddMessageMethods(message_descriptor, cls):
    if message_descriptor.is_extendable:

        def ClearExtension(self, extension):
            self.Extensions.ClearExtension(extension)

        def HasExtension(self, extension):
            return self.Extensions.HasExtension(extension)

    def HasField(self, field_name):
        field_name_in_bytes = bytes(field_name, 'utf8')
        val = self._cmsg.HasField(field_name_in_bytes)
        return val

    def ClearField(self, field_name_in_char):
        field_name = bytes(field_name_in_char, 'utf8')
        child_cmessage = None
        if field_name in self._composite_fields:
            child_field = self._composite_fields[field_name]
            del self._composite_fields[field_name]
            child_cdescriptor = self.__descriptors[field_name]
            if child_cdescriptor.label != _LABEL_REPEATED and child_cdescriptor.cpp_type == _CPPTYPE_MESSAGE:
                child_field._owner = None
                child_cmessage = child_field._cmsg
        if child_cmessage is not None:
            self._cmsg.ClearField(field_name_in_char, child_cmessage)
        else:
            self._cmsg.ClearField(field_name_in_char)

    def Clear(self):
        cmessages_to_release = []
        for (field_name, child_field) in self._composite_fields.items():
            child_cdescriptor = self.__descriptors[field_name]
            while child_cdescriptor.label != _LABEL_REPEATED and child_cdescriptor.cpp_type == _CPPTYPE_MESSAGE:
                child_field._owner = None
                cmessages_to_release.append((child_cdescriptor, child_field._cmsg))
        self._composite_fields.clear()
        self._cmsg.Clear(cmessages_to_release)

    def IsInitialized(self, errors=None):
        if self._cmsg.IsInitialized():
            return True
        if errors is not None:
            errors.extend(self.FindInitializationErrors())
        return False

    def SerializeToString(self):
        if not self.IsInitialized():
            raise message.EncodeError('Message is missing required fields: ' + str(self.FindInitializationErrors()))
        return self._cmsg.SerializeToString()

    def SerializePartialToString(self):
        return self._cmsg.SerializePartialToString()

    def ParseFromString(self, serialized):
        self.Clear()
        self.MergeFromString(serialized)

    def MergeFromString(self, serialized):
        if isinstance(serialized, str):
            serialized = serialized.encode('latin-1')
        byte_size = self._cmsg.MergeFromString(serialized)
        if byte_size < 0:
            raise message.DecodeError('Unable to merge from string.')
        return byte_size

    def MergeFrom(self, msg):
        if not isinstance(msg, cls):
            raise TypeError('Parameter to MergeFrom() must be instance of same class.')
        self._cmsg.MergeFrom(msg._cmsg)

    def CopyFrom(self, msg):
        self._cmsg.CopyFrom(msg._cmsg)

    def ByteSize(self):
        return self._cmsg.ByteSize()

    def SetInParent(self):
        return self._cmsg.SetInParent()

    def ListFields(self):
        all_fields = []
        field_list = self._cmsg.ListFields()
        fields_by_name = cls.DESCRIPTOR.fields_by_name
        for (is_extension, field_name) in field_list:
            field_name = str(field_name, 'utf8')
            if is_extension:
                extension = cls._extensions_by_name[field_name]
                all_fields.append((extension, self.Extensions[extension]))
            else:
                field_descriptor = fields_by_name[field_name]
                all_fields.append((field_descriptor, getattr(self, field_name)))
        all_fields.sort(key=lambda item: item[0].number)
        return all_fields

    def FindInitializationErrors(self):
        return self._cmsg.FindInitializationErrors()

    def __str__(self):
        return self._cmsg.DebugString()

    def __eq__(self, other):
        if self is other:
            return True
        if not isinstance(other, self.__class__):
            return False
        return self.ListFields() == other.ListFields()

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        raise TypeError('unhashable object')

    def __unicode__(self):
        from google.protobuf import text_format
        return text_format.MessageToString(self, as_utf8=True).decode('utf-8')

    for (key, value) in locals().copy().items():
        while key not in ('key', 'value', '__builtins__', '__name__', '__doc__'):
            setattr(cls, key, value)

    def RegisterExtension(extension_handle):
        extension_handle.containing_type = cls.DESCRIPTOR
        cls._extensions_by_name[extension_handle.full_name] = extension_handle
        if _IsMessageSetExtension(extension_handle):
            cls._extensions_by_name[extension_handle.message_type.full_name] = extension_handle

    cls.RegisterExtension = staticmethod(RegisterExtension)

    def FromString(string):
        msg = cls()
        msg.MergeFromString(string)
        return msg

    cls.FromString = staticmethod(FromString)

def _AddPropertiesForExtensions(message_descriptor, cls):
    extension_dict = message_descriptor.extensions_by_name
    for (extension_name, extension_field) in extension_dict.items():
        constant_name = extension_name.upper() + '_FIELD_NUMBER'
        setattr(cls, constant_name, extension_field.number)

