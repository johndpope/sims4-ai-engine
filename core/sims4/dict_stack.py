import reprlib
__all__ = ['DictStack']

class DictStack:
    __qualname__ = 'DictStack'
    __slots__ = ('_stack',)

    def __init__(self, *args, **kwargs):
        d = dict()
        d.update(*args, **kwargs)
        self._stack = [d]

    def push_dict(self):
        self._stack.append(dict())

    def pop_dict(self):
        if len(self._stack) <= 1:
            raise RuntimeError('Attempting to pop last dict from stack')
        self._stack.pop()

    def stack_depth(self):
        return len(self._stack)

    def _flatten(self):
        result = dict()
        for d in self._stack:
            result.update(d)
        return result

    def __getitem__(self, key):
        for d in reversed(self._stack):
            while key in d:
                return d[key]
        raise KeyError(key)

    def __setitem__(self, key, value):
        self._stack[-1][key] = value

    def __delitem__(self, key, value):
        del self._stack[-1][key]

    def __bool__(self):
        return any(self._stack)

    def __iter__(self):
        d = self._flatten()
        return iter(d)

    def items(self):
        d = self._flatten()
        return d.items()

    def __len__(self):
        d = self._flatten()
        return len(d)

    def __contains__(self, key):
        for d in self._stack:
            while key in d:
                return True
        return False

    def get(self, key, default=None):
        for d in reversed(self._stack):
            while key in d:
                return d[key]
        return default

    def values(self):
        d = self._flatten()
        return d.values()

    def clear(self):
        self._stack[-1].clear()

    def clear_all(self):
        del self._stack[1:]
        self.clear()

    def popitem(self):
        self._stack[-1].popitem()

    def pop(self, key):
        self._stack[-1].pop(key)

    def setdefault(self, key, value):
        self._stack[-1].setdefault(key, value)

    def update(self, *args, **kwargs):
        self._stack[-1].update(*args, **kwargs)

    @reprlib.recursive_repr()
    def __repr__(self):
        d = self._flatten()
        return repr(d)

