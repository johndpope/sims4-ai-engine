try:
    import _guid
except ImportError:
    _object_count = 0

    class _guid:
        __qualname__ = '_guid'

        @staticmethod
        def generate_s4guid():
            global _object_count
            _object_count += 1
            return _object_count


def __reload__(old_module_vars):
    pass


def generate_object_id():
    return _guid.generate_s4guid()
