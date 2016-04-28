__author__ = 'robinson@google.com (Will Robinson)'
from google.protobuf.internal import api_implementation
from google.protobuf import descriptor as descriptor_mod
from google.protobuf import message
_FieldDescriptor = descriptor_mod.FieldDescriptor
if api_implementation.Type() == 'cpp':
    if api_implementation.Version() == 2:
        from google.protobuf.internal.cpp import cpp_message
        _NewMessage = cpp_message.NewMessage
        _InitMessage = cpp_message.InitMessage
    else:
        from google.protobuf.internal import cpp_message
        _NewMessage = cpp_message.NewMessage
        _InitMessage = cpp_message.InitMessage
else:
    from google.protobuf.internal import python_message
    _NewMessage = python_message.NewMessage
    _InitMessage = python_message.InitMessage

class GeneratedProtocolMessageType(type):
    __qualname__ = 'GeneratedProtocolMessageType'
    _DESCRIPTOR_KEY = 'DESCRIPTOR'

    def __new__(cls, name, bases, dictionary):
        descriptor = dictionary[GeneratedProtocolMessageType._DESCRIPTOR_KEY]
        bases = _NewMessage(bases, descriptor, dictionary)
        superclass = super(GeneratedProtocolMessageType, cls)
        new_class = superclass.__new__(cls, name, bases, dictionary)
        setattr(descriptor, '_concrete_class', new_class)
        return new_class

    def __init__(cls, name, bases, dictionary):
        descriptor = dictionary[GeneratedProtocolMessageType._DESCRIPTOR_KEY]
        _InitMessage(descriptor, cls)
        superclass = super(GeneratedProtocolMessageType, cls)
        superclass.__init__(name, bases, dictionary)

