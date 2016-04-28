from interactions.context import InteractionContext
from interactions.priority import Priority

class PostureContext:
    __qualname__ = 'PostureContext'
    __slots__ = ('source', 'priority', 'pick')

    def __init__(self, source=InteractionContext.SOURCE_SCRIPT, priority=Priority.Low, pick=None):
        self.source = source
        self.priority = priority
        self.pick = pick

    def __repr__(self):
        return '{0}.{1}({2}, {3})'.format(self.__module__, self.__class__.__name__, self.source, repr(self.priority))

