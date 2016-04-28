import io
import sys
import textwrap
from test import support
import traceback
import unittest

class Test_TestResult(unittest.TestCase):
    __qualname__ = 'Test_TestResult'

    def test_init(self):
        result = unittest.TestResult()
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.failures), 0)
        self.assertEqual(result.testsRun, 0)
        self.assertEqual(result.shouldStop, False)
        self.assertIsNone(result._stdout_buffer)
        self.assertIsNone(result._stderr_buffer)

    def test_stop(self):
        result = unittest.TestResult()
        result.stop()
        self.assertEqual(result.shouldStop, True)

    def test_startTest(self):

        class Foo(unittest.TestCase):
            __qualname__ = 'Test_TestResult.test_startTest.<locals>.Foo'

            def test_1(self):
                pass

        test = Foo('test_1')
        result = unittest.TestResult()
        result.startTest(test)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.failures), 0)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.shouldStop, False)
        result.stopTest(test)

    def test_stopTest(self):

        class Foo(unittest.TestCase):
            __qualname__ = 'Test_TestResult.test_stopTest.<locals>.Foo'

            def test_1(self):
                pass

        test = Foo('test_1')
        result = unittest.TestResult()
        result.startTest(test)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.failures), 0)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.shouldStop, False)
        result.stopTest(test)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.failures), 0)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.shouldStop, False)

    def test_startTestRun_stopTestRun(self):
        result = unittest.TestResult()
        result.startTestRun()
        result.stopTestRun()

    def test_addSuccess(self):

        class Foo(unittest.TestCase):
            __qualname__ = 'Test_TestResult.test_addSuccess.<locals>.Foo'

            def test_1(self):
                pass

        test = Foo('test_1')
        result = unittest.TestResult()
        result.startTest(test)
        result.addSuccess(test)
        result.stopTest(test)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.failures), 0)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.shouldStop, False)

    def test_addFailure(self):

        class Foo(unittest.TestCase):
            __qualname__ = 'Test_TestResult.test_addFailure.<locals>.Foo'

            def test_1(self):
                pass

        test = Foo('test_1')
        try:
            test.fail('foo')
        except:
            exc_info_tuple = sys.exc_info()
        result = unittest.TestResult()
        result.startTest(test)
        result.addFailure(test, exc_info_tuple)
        result.stopTest(test)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.shouldStop, False)
        (test_case, formatted_exc) = result.failures[0]
        self.assertIs(test_case, test)
        self.assertIsInstance(formatted_exc, str)

    def test_addError(self):

        class Foo(unittest.TestCase):
            __qualname__ = 'Test_TestResult.test_addError.<locals>.Foo'

            def test_1(self):
                pass

        test = Foo('test_1')
        try:
            raise TypeError()
        except:
            exc_info_tuple = sys.exc_info()
        result = unittest.TestResult()
        result.startTest(test)
        result.addError(test, exc_info_tuple)
        result.stopTest(test)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(result.failures), 0)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.shouldStop, False)
        (test_case, formatted_exc) = result.errors[0]
        self.assertIs(test_case, test)
        self.assertIsInstance(formatted_exc, str)

    def testGetDescriptionWithoutDocstring(self):
        result = unittest.TextTestResult(None, True, 1)
        self.assertEqual(result.getDescription(self), 'testGetDescriptionWithoutDocstring (' + __name__ + '.Test_TestResult)')

    @unittest.skipIf(sys.flags.optimize >= 2, 'Docstrings are omitted with -O2 and above')
    def testGetDescriptionWithOneLineDocstring(self):
        result = unittest.TextTestResult(None, True, 1)
        self.assertEqual(result.getDescription(self), 'testGetDescriptionWithOneLineDocstring (' + __name__ + '.Test_TestResult)\nTests getDescription() for a method with a docstring.')

    @unittest.skipIf(sys.flags.optimize >= 2, 'Docstrings are omitted with -O2 and above')
    def testGetDescriptionWithMultiLineDocstring(self):
        result = unittest.TextTestResult(None, True, 1)
        self.assertEqual(result.getDescription(self), 'testGetDescriptionWithMultiLineDocstring (' + __name__ + '.Test_TestResult)\nTests getDescription() for a method with a longer docstring.')

    def testStackFrameTrimming(self):

        class Frame(object):
            __qualname__ = 'Test_TestResult.testStackFrameTrimming.<locals>.Frame'

            class tb_frame(object):
                __qualname__ = 'Test_TestResult.testStackFrameTrimming.<locals>.Frame.tb_frame'
                f_globals = {}

        result = unittest.TestResult()
        self.assertFalse(result._is_relevant_tb_level(Frame))
        Frame.tb_frame.f_globals['__unittest'] = True
        self.assertTrue(result._is_relevant_tb_level(Frame))

    def testFailFast(self):
        result = unittest.TestResult()
        result._exc_info_to_string = lambda *_: ''
        result.failfast = True
        result.addError(None, None)
        self.assertTrue(result.shouldStop)
        result = unittest.TestResult()
        result._exc_info_to_string = lambda *_: ''
        result.failfast = True
        result.addFailure(None, None)
        self.assertTrue(result.shouldStop)
        result = unittest.TestResult()
        result._exc_info_to_string = lambda *_: ''
        result.failfast = True
        result.addUnexpectedSuccess(None)
        self.assertTrue(result.shouldStop)

    def testFailFastSetByRunner(self):
        runner = unittest.TextTestRunner(stream=io.StringIO(), failfast=True)

        def test(result):
            self.assertTrue(result.failfast)

        result = runner.run(test)

classDict = dict(unittest.TestResult.__dict__)
for m in ('addSkip', 'addExpectedFailure', 'addUnexpectedSuccess', '__init__'):
    del classDict[m]

def __init__(self, stream=None, descriptions=None, verbosity=None):
    self.failures = []
    self.errors = []
    self.testsRun = 0
    self.shouldStop = False
    self.buffer = False

classDict['__init__'] = __init__
OldResult = type('OldResult', (object,), classDict)

class Test_OldTestResult(unittest.TestCase):
    __qualname__ = 'Test_OldTestResult'

    def assertOldResultWarning(self, test, failures):
        with support.check_warnings(('TestResult has no add.+ method,', RuntimeWarning)):
            result = OldResult()
            test.run(result)
            self.assertEqual(len(result.failures), failures)

    def testOldTestResult(self):

        class Test(unittest.TestCase):
            __qualname__ = 'Test_OldTestResult.testOldTestResult.<locals>.Test'

            def testSkip(self):
                self.skipTest('foobar')

            @unittest.expectedFailure
            def testExpectedFail(self):
                raise TypeError

            @unittest.expectedFailure
            def testUnexpectedSuccess(self):
                pass

        for (test_name, should_pass) in (('testSkip', True), ('testExpectedFail', True), ('testUnexpectedSuccess', False)):
            test = Test(test_name)
            self.assertOldResultWarning(test, int(not should_pass))

    def testOldTestTesultSetup(self):

        class Test(unittest.TestCase):
            __qualname__ = 'Test_OldTestResult.testOldTestTesultSetup.<locals>.Test'

            def setUp(self):
                self.skipTest('no reason')

            def testFoo(self):
                pass

        self.assertOldResultWarning(Test('testFoo'), 0)

    def testOldTestResultClass(self):

        @unittest.skip('no reason')
        class Test(unittest.TestCase):
            __qualname__ = 'Test_OldTestResult.testOldTestResultClass.<locals>.Test'

            def testFoo(self):
                pass

        self.assertOldResultWarning(Test('testFoo'), 0)

    def testOldResultWithRunner(self):

        class Test(unittest.TestCase):
            __qualname__ = 'Test_OldTestResult.testOldResultWithRunner.<locals>.Test'

            def testFoo(self):
                pass

        runner = unittest.TextTestRunner(resultclass=OldResult, stream=io.StringIO())
        runner.run(Test('testFoo'))

class MockTraceback(object):
    __qualname__ = 'MockTraceback'

    @staticmethod
    def format_exception(*_):
        return ['A traceback']

def restore_traceback():
    unittest.result.traceback = traceback

class TestOutputBuffering(unittest.TestCase):
    __qualname__ = 'TestOutputBuffering'

    def setUp(self):
        self._real_out = sys.stdout
        self._real_err = sys.stderr

    def tearDown(self):
        sys.stdout = self._real_out
        sys.stderr = self._real_err

    def testBufferOutputOff(self):
        real_out = self._real_out
        real_err = self._real_err
        result = unittest.TestResult()
        self.assertFalse(result.buffer)
        self.assertIs(real_out, sys.stdout)
        self.assertIs(real_err, sys.stderr)
        result.startTest(self)
        self.assertIs(real_out, sys.stdout)
        self.assertIs(real_err, sys.stderr)

    def testBufferOutputStartTestAddSuccess(self):
        real_out = self._real_out
        real_err = self._real_err
        result = unittest.TestResult()
        self.assertFalse(result.buffer)
        result.buffer = True
        self.assertIs(real_out, sys.stdout)
        self.assertIs(real_err, sys.stderr)
        result.startTest(self)
        self.assertIsNot(real_out, sys.stdout)
        self.assertIsNot(real_err, sys.stderr)
        self.assertIsInstance(sys.stdout, io.StringIO)
        self.assertIsInstance(sys.stderr, io.StringIO)
        self.assertIsNot(sys.stdout, sys.stderr)
        out_stream = sys.stdout
        err_stream = sys.stderr
        result._original_stdout = io.StringIO()
        result._original_stderr = io.StringIO()
        print('foo')
        print('bar', file=sys.stderr)
        self.assertEqual(out_stream.getvalue(), 'foo\n')
        self.assertEqual(err_stream.getvalue(), 'bar\n')
        self.assertEqual(result._original_stdout.getvalue(), '')
        self.assertEqual(result._original_stderr.getvalue(), '')
        result.addSuccess(self)
        result.stopTest(self)
        self.assertIs(sys.stdout, result._original_stdout)
        self.assertIs(sys.stderr, result._original_stderr)
        self.assertEqual(result._original_stdout.getvalue(), '')
        self.assertEqual(result._original_stderr.getvalue(), '')
        self.assertEqual(out_stream.getvalue(), '')
        self.assertEqual(err_stream.getvalue(), '')

    def getStartedResult(self):
        result = unittest.TestResult()
        result.buffer = True
        result.startTest(self)
        return result

    def testBufferOutputAddErrorOrFailure(self):
        unittest.result.traceback = MockTraceback
        self.addCleanup(restore_traceback)
        for (message_attr, add_attr, include_error) in [('errors', 'addError', True), ('failures', 'addFailure', False), ('errors', 'addError', True), ('failures', 'addFailure', False)]:
            result = self.getStartedResult()
            buffered_out = sys.stdout
            buffered_err = sys.stderr
            result._original_stdout = io.StringIO()
            result._original_stderr = io.StringIO()
            print('foo', file=sys.stdout)
            if include_error:
                print('bar', file=sys.stderr)
            addFunction = getattr(result, add_attr)
            addFunction(self, (None, None, None))
            result.stopTest(self)
            result_list = getattr(result, message_attr)
            self.assertEqual(len(result_list), 1)
            (test, message) = result_list[0]
            expectedOutMessage = textwrap.dedent('\n                Stdout:\n                foo\n            ')
            expectedErrMessage = ''
            if include_error:
                expectedErrMessage = textwrap.dedent('\n                Stderr:\n                bar\n            ')
            expectedFullMessage = 'A traceback%s%s' % (expectedOutMessage, expectedErrMessage)
            self.assertIs(test, self)
            self.assertEqual(result._original_stdout.getvalue(), expectedOutMessage)
            self.assertEqual(result._original_stderr.getvalue(), expectedErrMessage)
            self.assertMultiLineEqual(message, expectedFullMessage)

    def testBufferSetupClass(self):
        result = unittest.TestResult()
        result.buffer = True

        class Foo(unittest.TestCase):
            __qualname__ = 'TestOutputBuffering.testBufferSetupClass.<locals>.Foo'

            @classmethod
            def setUpClass(cls):
                1/0

            def test_foo(self):
                pass

        suite = unittest.TestSuite([Foo('test_foo')])
        suite(result)
        self.assertEqual(len(result.errors), 1)

    def testBufferTearDownClass(self):
        result = unittest.TestResult()
        result.buffer = True

        class Foo(unittest.TestCase):
            __qualname__ = 'TestOutputBuffering.testBufferTearDownClass.<locals>.Foo'

            @classmethod
            def tearDownClass(cls):
                1/0

            def test_foo(self):
                pass

        suite = unittest.TestSuite([Foo('test_foo')])
        suite(result)
        self.assertEqual(len(result.errors), 1)

    def testBufferSetUpModule(self):
        result = unittest.TestResult()
        result.buffer = True

        class Foo(unittest.TestCase):
            __qualname__ = 'TestOutputBuffering.testBufferSetUpModule.<locals>.Foo'

            def test_foo(self):
                pass

        class Module(object):
            __qualname__ = 'TestOutputBuffering.testBufferSetUpModule.<locals>.Module'

            @staticmethod
            def setUpModule():
                1/0

        Foo.__module__ = 'Module'
        sys.modules['Module'] = Module
        self.addCleanup(sys.modules.pop, 'Module')
        suite = unittest.TestSuite([Foo('test_foo')])
        suite(result)
        self.assertEqual(len(result.errors), 1)

    def testBufferTearDownModule(self):
        result = unittest.TestResult()
        result.buffer = True

        class Foo(unittest.TestCase):
            __qualname__ = 'TestOutputBuffering.testBufferTearDownModule.<locals>.Foo'

            def test_foo(self):
                pass

        class Module(object):
            __qualname__ = 'TestOutputBuffering.testBufferTearDownModule.<locals>.Module'

            @staticmethod
            def tearDownModule():
                1/0

        Foo.__module__ = 'Module'
        sys.modules['Module'] = Module
        self.addCleanup(sys.modules.pop, 'Module')
        suite = unittest.TestSuite([Foo('test_foo')])
        suite(result)
        self.assertEqual(len(result.errors), 1)

if __name__ == '__main__':
    unittest.main()
