import enum

class ResetReason(enum.Int, export=False):
    __qualname__ = 'ResetReason'
    NONE = Ellipsis
    RESET_EXPECTED = Ellipsis
    RESET_ON_ERROR = Ellipsis
    BEING_DESTROYED = Ellipsis

