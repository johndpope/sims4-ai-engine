__author__ = 'robinson@google.com (Will Robinson)'

class Error(Exception):
    __qualname__ = 'Error'

class DecodeError(Error):
    __qualname__ = 'DecodeError'

class EncodeError(Error):
    __qualname__ = 'EncodeError'

class Message(object):
    __qualname__ = 'Message'
    __slots__ = []
    DESCRIPTOR = None

    def __deepcopy__(self, memo=None):
        clone = type(self)()
        clone.MergeFrom(self)
        return clone

    def __eq__(self, other_msg):
        raise NotImplementedError

    def __ne__(self, other_msg):
        return not self == other_msg

    def __hash__(self):
        raise TypeError('unhashable object')

    def __str__(self):
        raise NotImplementedError

    def __unicode__(self):
        raise NotImplementedError

    def MergeFrom(self, other_msg):
        raise NotImplementedError

    def CopyFrom(self, other_msg):
        if self is other_msg:
            return
        self.Clear()
        self.MergeFrom(other_msg)

    def Clear(self):
        raise NotImplementedError

    def SetInParent(self):
        raise NotImplementedError

    def IsInitialized(self):
        raise NotImplementedError

    def MergeFromString(self, serialized):
        raise NotImplementedError

    def ParseFromString(self, serialized):
        self.Clear()
        self.MergeFromString(serialized)

    def SerializeToString(self):
        raise NotImplementedError

    def SerializePartialToString(self):
        raise NotImplementedError

    def ListFields(self):
        raise NotImplementedError

    def HasField(self, field_name):
        raise NotImplementedError

    def ClearField(self, field_name):
        raise NotImplementedError

    def HasExtension(self, extension_handle):
        raise NotImplementedError

    def ClearExtension(self, extension_handle):
        raise NotImplementedError

    def ByteSize(self):
        raise NotImplementedError

    def _SetListener(self, message_listener):
        raise NotImplementedError

