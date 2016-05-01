try:
    import _pythonutils
except ImportError:

    class _pythonutils:
        __qualname__ = '_pythonutils'

        @staticmethod
        def try_highwater_gc():
            return False


try_highwater_gc = _pythonutils.try_highwater_gc
