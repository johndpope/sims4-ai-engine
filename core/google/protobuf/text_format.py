__author__ = 'kenton@google.com (Kenton Varda)'
import io
import re
from collections import deque
from google.protobuf.internal import type_checkers
from google.protobuf import descriptor
__all__ = ['MessageToString', 'PrintMessage', 'PrintField', 'PrintFieldValue', 'Merge']
_INTEGER_CHECKERS = (type_checkers.Uint32ValueChecker(), type_checkers.Int32ValueChecker(), type_checkers.Uint64ValueChecker(), type_checkers.Int64ValueChecker())
_FLOAT_INFINITY = re.compile('-?inf(?:inity)?f?', re.IGNORECASE)
_FLOAT_NAN = re.compile('nanf?', re.IGNORECASE)

class ParseError(Exception):
    __qualname__ = 'ParseError'

def MessageToString(message, as_utf8=False, as_one_line=False):
    out = io.StringIO()
    PrintMessage(message, out, as_utf8=as_utf8, as_one_line=as_one_line)
    result = out.getvalue()
    out.close()
    if as_one_line:
        return result.rstrip()
    return result

def PrintMessage(message, out, indent=0, as_utf8=False, as_one_line=False):
    for (field, value) in message.ListFields():
        if field.label == descriptor.FieldDescriptor.LABEL_REPEATED:
            for element in value:
                PrintField(field, element, out, indent, as_utf8, as_one_line)
        else:
            PrintField(field, value, out, indent, as_utf8, as_one_line)

def PrintField(field, value, out, indent=0, as_utf8=False, as_one_line=False):
    out.write(' '*indent)
    if field.is_extension:
        out.write('[')
        if field.containing_type.GetOptions().message_set_wire_format and (field.type == descriptor.FieldDescriptor.TYPE_MESSAGE and field.message_type == field.extension_scope) and field.label == descriptor.FieldDescriptor.LABEL_OPTIONAL:
            out.write(field.message_type.full_name)
        else:
            out.write(field.full_name)
        out.write(']')
    elif field.type == descriptor.FieldDescriptor.TYPE_GROUP:
        out.write(field.message_type.name)
    else:
        out.write(field.name)
    if field.cpp_type != descriptor.FieldDescriptor.CPPTYPE_MESSAGE:
        out.write(': ')
    PrintFieldValue(field, value, out, indent, as_utf8, as_one_line)
    if as_one_line:
        out.write(' ')
    else:
        out.write('\n')

def PrintFieldValue(field, value, out, indent=0, as_utf8=False, as_one_line=False):
    if field.cpp_type == descriptor.FieldDescriptor.CPPTYPE_MESSAGE:
        if as_one_line:
            out.write(' { ')
            PrintMessage(value, out, indent, as_utf8, as_one_line)
            out.write('}')
        else:
            out.write(' {\n')
            PrintMessage(value, out, indent + 2, as_utf8, as_one_line)
            out.write(' '*indent + '}')
    elif field.cpp_type == descriptor.FieldDescriptor.CPPTYPE_ENUM:
        enum_value = field.enum_type.values_by_number.get(value, None)
        if enum_value is not None:
            out.write(enum_value.name)
        else:
            out.write(str(value))
    elif field.cpp_type == descriptor.FieldDescriptor.CPPTYPE_STRING:
        out.write('"')
        if type(value) is str:
            out.write(_CEscape(value.encode('utf-8'), as_utf8))
        else:
            out.write(_CEscape(value, as_utf8))
        out.write('"')
    elif field.cpp_type == descriptor.FieldDescriptor.CPPTYPE_BOOL:
        if value:
            out.write('true')
        else:
            out.write('false')
    else:
        out.write(str(value))

def Merge(text, message):
    tokenizer = _Tokenizer(text)
    while not tokenizer.AtEnd():
        _MergeField(tokenizer, message)

def _MergeField(tokenizer, message):
    message_descriptor = message.DESCRIPTOR
    if tokenizer.TryConsume('['):
        name = [tokenizer.ConsumeIdentifier()]
        while tokenizer.TryConsume('.'):
            name.append(tokenizer.ConsumeIdentifier())
        name = '.'.join(name)
        if not message_descriptor.is_extendable:
            raise tokenizer.ParseErrorPreviousToken('Message type "%s" does not have extensions.' % message_descriptor.full_name)
        field = message.Extensions._FindExtensionByName(name)
        if not field:
            raise tokenizer.ParseErrorPreviousToken('Extension "%s" not registered.' % name)
        elif message_descriptor != field.containing_type:
            raise tokenizer.ParseErrorPreviousToken('Extension "%s" does not extend message type "%s".' % (name, message_descriptor.full_name))
        tokenizer.Consume(']')
    else:
        name = tokenizer.ConsumeIdentifier()
        field = message_descriptor.fields_by_name.get(name, None)
        if not field:
            field = message_descriptor.fields_by_name.get(name.lower(), None)
            if field and field.type != descriptor.FieldDescriptor.TYPE_GROUP:
                field = None
        if field and field.type == descriptor.FieldDescriptor.TYPE_GROUP and field.message_type.name != name:
            field = None
        if not field:
            raise tokenizer.ParseErrorPreviousToken('Message type "%s" has no field named "%s".' % (message_descriptor.full_name, name))
    if field.cpp_type == descriptor.FieldDescriptor.CPPTYPE_MESSAGE:
        tokenizer.TryConsume(':')
        if tokenizer.TryConsume('<'):
            end_token = '>'
        else:
            tokenizer.Consume('{')
            end_token = '}'
        if field.label == descriptor.FieldDescriptor.LABEL_REPEATED:
            if field.is_extension:
                sub_message = message.Extensions[field].add()
            else:
                sub_message = getattr(message, field.name).add()
        else:
            if field.is_extension:
                sub_message = message.Extensions[field]
            else:
                sub_message = getattr(message, field.name)
            sub_message.SetInParent()
        if tokenizer.AtEnd():
            raise tokenizer.ParseErrorPreviousToken('Expected "%s".' % end_token)
        _MergeField(tokenizer, sub_message)
        continue
    else:
        _MergeScalarField(tokenizer, message, field)

def _MergeScalarField(tokenizer, message, field):
    tokenizer.Consume(':')
    value = None
    if field.type in (descriptor.FieldDescriptor.TYPE_INT32, descriptor.FieldDescriptor.TYPE_SINT32, descriptor.FieldDescriptor.TYPE_SFIXED32):
        value = tokenizer.ConsumeInt32()
    elif field.type in (descriptor.FieldDescriptor.TYPE_INT64, descriptor.FieldDescriptor.TYPE_SINT64, descriptor.FieldDescriptor.TYPE_SFIXED64):
        value = tokenizer.ConsumeInt64()
    elif field.type in (descriptor.FieldDescriptor.TYPE_UINT32, descriptor.FieldDescriptor.TYPE_FIXED32):
        value = tokenizer.ConsumeUint32()
    elif field.type in (descriptor.FieldDescriptor.TYPE_UINT64, descriptor.FieldDescriptor.TYPE_FIXED64):
        value = tokenizer.ConsumeUint64()
    elif field.type in (descriptor.FieldDescriptor.TYPE_FLOAT, descriptor.FieldDescriptor.TYPE_DOUBLE):
        value = tokenizer.ConsumeFloat()
    elif field.type == descriptor.FieldDescriptor.TYPE_BOOL:
        value = tokenizer.ConsumeBool()
    elif field.type == descriptor.FieldDescriptor.TYPE_STRING:
        value = tokenizer.ConsumeString()
    elif field.type == descriptor.FieldDescriptor.TYPE_BYTES:
        value = tokenizer.ConsumeByteString()
    elif field.type == descriptor.FieldDescriptor.TYPE_ENUM:
        value = tokenizer.ConsumeEnum(field)
    else:
        raise RuntimeError('Unknown field type %d' % field.type)
    if field.label == descriptor.FieldDescriptor.LABEL_REPEATED:
        if field.is_extension:
            message.Extensions[field].append(value)
        else:
            getattr(message, field.name).append(value)
    elif field.is_extension:
        message.Extensions[field] = value
    else:
        setattr(message, field.name, value)

class _Tokenizer(object):
    __qualname__ = '_Tokenizer'
    _WHITESPACE = re.compile('(\\s|(#.*$))+', re.MULTILINE)
    _TOKEN = re.compile('[a-zA-Z_][0-9a-zA-Z_+-]*|[0-9+-][0-9a-zA-Z_.+-]*|"([^"\n\\\\]|\\\\.)*("|\\\\?$)|\'([^\'\n\\\\]|\\\\.)*(\'|\\\\?$)')
    _IDENTIFIER = re.compile('\\w+')

    def __init__(self, text_message):
        self._text_message = text_message
        self._position = 0
        self._line = -1
        self._column = 0
        self._token_start = None
        self.token = ''
        self._lines = deque(text_message.split('\n'))
        self._current_line = ''
        self._previous_line = 0
        self._previous_column = 0
        self._SkipWhitespace()
        self.NextToken()

    def AtEnd(self):
        return self.token == ''

    def _PopLine(self):
        while len(self._current_line) <= self._column:
            if not self._lines:
                self._current_line = ''
                return
            self._column = 0
            self._current_line = self._lines.popleft()

    def _SkipWhitespace(self):
        while True:
            self._PopLine()
            match = self._WHITESPACE.match(self._current_line, self._column)
            if not match:
                break
            length = len(match.group(0))

    def TryConsume(self, token):
        if self.token == token:
            self.NextToken()
            return True
        return False

    def Consume(self, token):
        if not self.TryConsume(token):
            raise self._ParseError('Expected "%s".' % token)

    def LookingAtInteger(self):
        if not self.token:
            return False
        c = self.token[0]
        return c >= '0' and c <= '9' or (c == '-' or c == '+')

    def ConsumeIdentifier(self):
        result = self.token
        if not self._IDENTIFIER.match(result):
            raise self._ParseError('Expected identifier.')
        self.NextToken()
        return result

    def ConsumeInt32(self):
        try:
            result = ParseInteger(self.token, is_signed=True, is_long=False)
        except ValueError as e:
            raise self._ParseError(str(e))
        self.NextToken()
        return result

    def ConsumeUint32(self):
        try:
            result = ParseInteger(self.token, is_signed=False, is_long=False)
        except ValueError as e:
            raise self._ParseError(str(e))
        self.NextToken()
        return result

    def ConsumeInt64(self):
        try:
            result = ParseInteger(self.token, is_signed=True, is_long=True)
        except ValueError as e:
            raise self._ParseError(str(e))
        self.NextToken()
        return result

    def ConsumeUint64(self):
        try:
            result = ParseInteger(self.token, is_signed=False, is_long=True)
        except ValueError as e:
            raise self._ParseError(str(e))
        self.NextToken()
        return result

    def ConsumeFloat(self):
        try:
            result = ParseFloat(self.token)
        except ValueError as e:
            raise self._ParseError(str(e))
        self.NextToken()
        return result

    def ConsumeBool(self):
        try:
            result = ParseBool(self.token)
        except ValueError as e:
            raise self._ParseError(str(e))
        self.NextToken()
        return result

    def ConsumeString(self):
        bytes = self.ConsumeByteString()
        try:
            return str(bytes, 'utf-8')
        except UnicodeDecodeError as e:
            raise self._StringParseError(e)

    def ConsumeByteString(self):
        list = [self._ConsumeSingleByteString()]
        while len(self.token) > 0:
            while self.token[0] in ("'", '"'):
                list.append(self._ConsumeSingleByteString())
        return ''.join(list)

    def _ConsumeSingleByteString(self):
        text = self.token
        if len(text) < 1 or text[0] not in ("'", '"'):
            raise self._ParseError('Expected string.')
        if len(text) < 2 or text[-1] != text[0]:
            raise self._ParseError('String missing ending quote.')
        try:
            result = _CUnescape(text[1:-1])
        except ValueError as e:
            raise self._ParseError(str(e))
        self.NextToken()
        return result

    def ConsumeEnum(self, field):
        try:
            result = ParseEnum(field, self.token)
        except ValueError as e:
            raise self._ParseError(str(e))
        self.NextToken()
        return result

    def ParseErrorPreviousToken(self, message):
        return ParseError('%d:%d : %s' % (self._previous_line + 1, self._previous_column + 1, message))

    def _ParseError(self, message):
        return ParseError('%d:%d : %s' % (self._line + 1, self._column + 1, message))

    def _StringParseError(self, e):
        return self._ParseError("Couldn't parse string: " + str(e))

    def NextToken(self):
        self._previous_line = self._line
        self._previous_column = self._column
        self._SkipWhitespace()
        if not self._lines and len(self._current_line) <= self._column:
            self.token = ''
            return
        match = self._TOKEN.match(self._current_line, self._column)
        if match:
            token = match.group(0)
            self.token = token
        else:
            self.token = self._current_line[self._column]

def _CEscape(text, as_utf8):

    def escape(c):
        o = ord(c)
        if o == 10:
            return '\\n'
        if o == 13:
            return '\\r'
        if o == 9:
            return '\\t'
        if o == 39:
            return "\\'"
        if o == 34:
            return '\\"'
        if o == 92:
            return '\\\\'
        if not as_utf8 and (o >= 127 or o < 32):
            return '\\%03o' % o
        return c

    return ''.join([escape(c) for c in text])

_CUNESCAPE_HEX = re.compile('(\\\\+)x([0-9a-fA-F])(?![0-9a-fA-F])')

def _CUnescape(text):

    def ReplaceHex(m):
        if len(m.group(1)) & 1:
            return m.group(1) + 'x0' + m.group(2)
        return m.group(0)

    result = _CUNESCAPE_HEX.sub(ReplaceHex, text)
    return result.decode('string_escape')

def ParseInteger(text, is_signed=False, is_long=False):
    try:
        result = int(text, 0)
    except ValueError:
        raise ValueError("Couldn't parse integer: %s" % text)
    checker = _INTEGER_CHECKERS[2*int(is_long) + int(is_signed)]
    checker.CheckValue(result)
    return result

def ParseFloat(text):
    try:
        return float(text)
    except ValueError:
        if _FLOAT_INFINITY.match(text):
            if text[0] == '-':
                return float('-inf')
            return float('inf')
        else:
            if _FLOAT_NAN.match(text):
                return float('nan')
            try:
                return float(text.rstrip('f'))
            except ValueError:
                raise ValueError("Couldn't parse float: %s" % text)

def ParseBool(text):
    if text in ('true', 't', '1'):
        return True
    if text in ('false', 'f', '0'):
        return False
    raise ValueError('Expected "true" or "false".')

def ParseEnum(field, value):
    enum_descriptor = field.enum_type
    try:
        number = int(value, 0)
    except ValueError:
        enum_value = enum_descriptor.values_by_name.get(value, None)
        if enum_value is None:
            raise ValueError('Enum type "%s" has no value named %s.' % (enum_descriptor.full_name, value))
    enum_value = enum_descriptor.values_by_number.get(number, None)
    if enum_value is None:
        raise ValueError('Enum type "%s" has no value with number %d.' % (enum_descriptor.full_name, number))
    return enum_value.number

