import sys
import unittest
import warnings

def warnfun():
    warnings.warn('rw', RuntimeWarning)

class TestWarnings(unittest.TestCase):
    __qualname__ = 'TestWarnings'

    def test_assert(self):
        self.assertEquals(4, 4)
        self.assertEquals(4, 4)
        self.assertEquals(4, 4)

    def test_fail(self):
        self.failUnless(1)
        self.failUnless(True)

    def test_other_unittest(self):
        self.assertAlmostEqual(4, 4)
        self.assertNotAlmostEqual(8, 2)

    def test_deprecation(self):
        warnings.warn('dw', DeprecationWarning)
        warnings.warn('dw', DeprecationWarning)
        warnings.warn('dw', DeprecationWarning)

    def test_import(self):
        warnings.warn('iw', ImportWarning)
        warnings.warn('iw', ImportWarning)
        warnings.warn('iw', ImportWarning)

    def test_warning(self):
        warnings.warn('uw')
        warnings.warn('uw')
        warnings.warn('uw')

    def test_function(self):
        warnfun()
        warnfun()
        warnfun()

if __name__ == '__main__':
    with warnings.catch_warnings(record=True) as ws:
        if len(sys.argv) == 2:
            unittest.main(exit=False, warnings=sys.argv.pop())
        else:
            unittest.main(exit=False)
    for w in ws:
        print(w.message)
