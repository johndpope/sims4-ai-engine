__author__ = 'robinson@google.com (Will Robinson)'

class MessageListener(object):
    __qualname__ = 'MessageListener'

    def Modified(self):
        raise NotImplementedError

class NullMessageListener(object):
    __qualname__ = 'NullMessageListener'

    def Modified(self):
        pass

