import unittest
from unittest.mock import sentinel, DEFAULT

class SentinelTest(unittest.TestCase):
    __qualname__ = 'SentinelTest'

    def testSentinels(self):
        self.assertEqual(sentinel.whatever, sentinel.whatever, 'sentinel not stored')
        self.assertNotEqual(sentinel.whatever, sentinel.whateverelse, 'sentinel should be unique')

    def testSentinelName(self):
        self.assertEqual(str(sentinel.whatever), 'sentinel.whatever', 'sentinel name incorrect')

    def testDEFAULT(self):
        self.assertIs(DEFAULT, sentinel.DEFAULT)

    def testBases(self):
        self.assertRaises(AttributeError, lambda : sentinel.__bases__)

if __name__ == '__main__':
    unittest.main()
