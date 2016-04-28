from distributor import logger

class ProtocolBufferRollback:
    __qualname__ = 'ProtocolBufferRollback'

    def __init__(self, repeated_field):
        self._repeated_field = repeated_field

    def __enter__(self):
        return self._repeated_field.add()

    def __exit__(self, exc_type, value, tb):
        if exc_type is not None:
            del self._repeated_field[len(self._repeated_field) - 1]
            logger.exception('Exception occurred while attempting to populate a repeated field:')
        return True

