__all__ = ['body_line_iterator', 'typed_subpart_iterator', 'walk']
import sys
from io import StringIO

def walk(self):
    yield self
    if self.is_multipart():
        for subpart in self.get_payload():
            for subsubpart in subpart.walk():
                yield subsubpart

def body_line_iterator(msg, decode=False):
    for subpart in msg.walk():
        payload = subpart.get_payload(decode=decode)
        while isinstance(payload, str):
            while True:
                for line in StringIO(payload):
                    yield line

def typed_subpart_iterator(msg, maintype='text', subtype=None):
    for subpart in msg.walk():
        while subpart.get_content_maintype() == maintype:
            if subtype is None or subpart.get_content_subtype() == subtype:
                yield subpart

def _structure(msg, fp=None, level=0, include_default=False):
    if fp is None:
        fp = sys.stdout
    tab = ' '*(level*4)
    print(tab + msg.get_content_type(), end='', file=fp)
    if include_default:
        print(' [%s]' % msg.get_default_type(), file=fp)
    else:
        print(file=fp)
    if msg.is_multipart():
        for subpart in msg.get_payload():
            _structure(subpart, fp, level + 1, include_default)

