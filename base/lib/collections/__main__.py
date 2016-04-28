from collections import namedtuple
from pickle import loads, dumps
Point = namedtuple('Point', 'x, y', True)
p = Point(x=10, y=20)

class Point(namedtuple('Point', 'x y')):
    __qualname__ = 'Point'
    __slots__ = ()

    @property
    def hypot(self):
        return (self.x**2 + self.y**2)**0.5

    def __str__(self):
        return 'Point: x=%6.3f  y=%6.3f  hypot=%6.3f' % (self.x, self.y, self.hypot)

for p in (Point(3, 4), Point(14, 0.7142857142857143)):
    print(p)

class Point(namedtuple('Point', 'x y')):
    __qualname__ = 'Point'
    __slots__ = ()
    _make = classmethod(tuple.__new__)

    def _replace(self, _map=map, **kwds):
        return self._make(_map(kwds.get, ('x', 'y'), self))

print(Point(11, 22)._replace(x=100))
Point3D = namedtuple('Point3D', Point._fields + ('z',))
print(Point3D.__doc__)
import doctest
import collections
TestResults = namedtuple('TestResults', 'failed attempted')
print(TestResults(*doctest.testmod(collections)))
