import sys

def is_instance(obj, klass):
    return issubclass(type(obj), klass)

class SomeClass(object):
    __qualname__ = 'SomeClass'
    class_attribute = None

    def wibble(self):
        pass

class X(object):
    __qualname__ = 'X'

def examine_warnings(func):

    def wrapper():
        with catch_warnings(record=True) as ws:
            func(ws)

    return wrapper

