__author__ = 'petar@google.com (Petar Petrov)'
import os
_implementation_type = os.getenv('PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION', 'python')
_implementation_type = 'cpp'
if _implementation_type != 'python':
    _implementation_type = 'cpp'
    try:
        from google.protobuf.internal import cpp_message
        _implementation_type = 'cpp'
    except ImportError as e:
        _implementation_type = 'python'
_implementation_version_str = os.getenv('PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION_VERSION', '1')
if _implementation_version_str not in ('1', '2'):
    raise ValueError("unsupported PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION_VERSION: '" + _implementation_version_str + "' (supported versions: 1, 2)")
_implementation_version = int(_implementation_version_str)

def Type():
    return _implementation_type

def Version():
    return _implementation_version

