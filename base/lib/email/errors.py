
class MessageError(Exception):
    __qualname__ = 'MessageError'

class MessageParseError(MessageError):
    __qualname__ = 'MessageParseError'

class HeaderParseError(MessageParseError):
    __qualname__ = 'HeaderParseError'

class BoundaryError(MessageParseError):
    __qualname__ = 'BoundaryError'

class MultipartConversionError(MessageError, TypeError):
    __qualname__ = 'MultipartConversionError'

class CharsetError(MessageError):
    __qualname__ = 'CharsetError'

class MessageDefect(ValueError):
    __qualname__ = 'MessageDefect'

    def __init__(self, line=None):
        if line is not None:
            super().__init__(line)
        self.line = line

class NoBoundaryInMultipartDefect(MessageDefect):
    __qualname__ = 'NoBoundaryInMultipartDefect'

class StartBoundaryNotFoundDefect(MessageDefect):
    __qualname__ = 'StartBoundaryNotFoundDefect'

class CloseBoundaryNotFoundDefect(MessageDefect):
    __qualname__ = 'CloseBoundaryNotFoundDefect'

class FirstHeaderLineIsContinuationDefect(MessageDefect):
    __qualname__ = 'FirstHeaderLineIsContinuationDefect'

class MisplacedEnvelopeHeaderDefect(MessageDefect):
    __qualname__ = 'MisplacedEnvelopeHeaderDefect'

class MissingHeaderBodySeparatorDefect(MessageDefect):
    __qualname__ = 'MissingHeaderBodySeparatorDefect'

MalformedHeaderDefect = MissingHeaderBodySeparatorDefect

class MultipartInvariantViolationDefect(MessageDefect):
    __qualname__ = 'MultipartInvariantViolationDefect'

class InvalidMultipartContentTransferEncodingDefect(MessageDefect):
    __qualname__ = 'InvalidMultipartContentTransferEncodingDefect'

class UndecodableBytesDefect(MessageDefect):
    __qualname__ = 'UndecodableBytesDefect'

class InvalidBase64PaddingDefect(MessageDefect):
    __qualname__ = 'InvalidBase64PaddingDefect'

class InvalidBase64CharactersDefect(MessageDefect):
    __qualname__ = 'InvalidBase64CharactersDefect'

class HeaderDefect(MessageDefect):
    __qualname__ = 'HeaderDefect'

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)

class InvalidHeaderDefect(HeaderDefect):
    __qualname__ = 'InvalidHeaderDefect'

class HeaderMissingRequiredValue(HeaderDefect):
    __qualname__ = 'HeaderMissingRequiredValue'

class NonPrintableDefect(HeaderDefect):
    __qualname__ = 'NonPrintableDefect'

    def __init__(self, non_printables):
        super().__init__(non_printables)
        self.non_printables = non_printables

    def __str__(self):
        return 'the following ASCII non-printables found in header: {}'.format(self.non_printables)

class ObsoleteHeaderDefect(HeaderDefect):
    __qualname__ = 'ObsoleteHeaderDefect'

class NonASCIILocalPartDefect(HeaderDefect):
    __qualname__ = 'NonASCIILocalPartDefect'

