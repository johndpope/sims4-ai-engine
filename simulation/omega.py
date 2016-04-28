try:
    import _omega
except ImportError:

    class _omega:
        __qualname__ = '_omega'

        @staticmethod
        def send(session_id, msg_id, data):
            return True

_send = _omega.send

def send(session_id, msg_id, data):
    if not _send(session_id, msg_id, data):
        raise KeyError('Failed to find ZoneSessionContext for [ZoneSessionId: 0x{:016x}]'.format(session_id))

