import sims4

class DefaultPropertyStreamReader:
    __qualname__ = 'DefaultPropertyStreamReader'

    def __init__(self, data):
        self._reader = sims4.PropertyStreamReader(data)

    def read_bool(self, key, default):
        try:
            value = self._reader.read_bool(key)
        except KeyError:
            value = default
        return value

    def read_int8(self, key, default):
        try:
            value = self._reader.read_int8(key)
        except KeyError:
            value = default
        return value

    def read_int16(self, key, default):
        try:
            value = self._reader.read_int16(key)
        except KeyError:
            value = default
        return value

    def read_int32(self, key, default):
        try:
            value = self._reader.read_int32(key)
        except KeyError:
            value = default
        return value

    def read_int64(self, key, default):
        try:
            value = self._reader.read_int64(key)
        except KeyError:
            value = default
        return value

    def read_uint8(self, key, default):
        try:
            value = self._reader.read_uint8(key)
        except KeyError:
            value = default
        return value

    def read_uint16(self, key, default):
        try:
            value = self._reader.read_uint16(key)
        except KeyError:
            value = default
        return value

    def read_uint32(self, key, default):
        try:
            value = self._reader.read_uint32(key)
        except KeyError:
            value = default
        return value

    def read_uint64(self, key, default):
        try:
            value = self._reader.read_uint64(key)
        except KeyError:
            value = default
        return value

    def read_float(self, key, default):
        try:
            value = self._reader.read_float(key)
        except KeyError:
            value = default
        return value

    def read_string8(self, key, default):
        try:
            value = self._reader.read_string8(key)
        except KeyError:
            value = default
        return value

    def read_string16(self, key, default):
        try:
            value = self._reader.read_string16(key)
        except KeyError:
            value = default
        return value

    def read_int8s(self, key, default):
        try:
            value = self._reader.read_int8s(key)
        except KeyError:
            value = default
        return value

    def read_int16s(self, key, default):
        try:
            value = self._reader.read_int16s(key)
        except KeyError:
            value = default
        return value

    def read_int32s(self, key, default):
        try:
            value = self._reader.read_int32s(key)
        except KeyError:
            value = default
        return value

    def read_int64s(self, key, default):
        try:
            value = self._reader.read_int64s(key)
        except KeyError:
            value = default
        return value

    def read_uint8s(self, key, default):
        try:
            value = self._reader.read_uint8s(key)
        except KeyError:
            value = default
        return value

    def read_uint16s(self, key, default):
        try:
            value = self._reader.read_uint16s(key)
        except KeyError:
            value = default
        return value

    def read_uint32s(self, key, default):
        try:
            value = self._reader.read_uint32s(key)
        except KeyError:
            value = default
        return value

    def read_uint64s(self, key, default):
        try:
            value = self._reader.read_uint64s(key)
        except KeyError:
            value = default
        return value

    def read_floats(self, key, default):
        try:
            value = self._reader.read_floats(key)
        except KeyError:
            value = default
        return value

