import builtins
import doctest
import os
import sys
import traceback
import unittest
from sims4.console_colors import ConsoleColor
import sims4.log
test_filter_every_n = 1
test_filter_offset = 0

class TestResult:
    __qualname__ = 'TestResult'

    def __init__(self):
        self.failures = {}
        self.successes = {}
        self.warnings = {}
        self.modules_tested = set()

    @property
    def succeeded(self):
        return not self.failures

    def add_error(self, module_name, error):
        self.failures.setdefault(module_name, []).append(error)

    def add_success(self, module_name, test_name):
        self.successes.setdefault(module_name, []).append(test_name)

    def add_warning(self, module_name, warning):
        self.warnings.setdefault(module_name, []).append(warning)

    def concatenate(self, other):
        if other:
            for (k, v) in other.failures.items():
                module_failures = self.failures.setdefault(k, [])
                for failure in v:
                    module_failures.append(failure)
            for (k, v) in other.successes.items():
                module_successes = self.successes.setdefault(k, [])
                for success in v:
                    module_successes.append(success)
            for (k, v) in other.warnings.items():
                module_warnings = self.warnings.setdefault(k, [])
                for warning in v:
                    module_warnings.append(warning)
            self.modules_tested = self.modules_tested.union(other.modules_tested)

    def __add__(self, other):
        results = TestResult()
        results.concatenate(self)
        results.concatenate(other)
        return results

def test_path_list(paths, modules_to_ignore, file_=sys.stdout, verbose=False, recurse=True, failfast=False):
    result = TestResult()
    for path in paths:
        result += test_path(path, modules_to_ignore, file_, verbose, recurse, failfast)
        while not result.succeeded:
            if file_ is sys.stdout:
                ConsoleColor.change_color(ConsoleColor.RED)
            file_.write('ERROR in ' + path + '\n')
            if failfast == True:
                file_.write("Because of 'failfast', aborting remainder of tests\n")
                return result
    return result

def test_path(path, modules_to_ignore, file_=sys.stdout, verbose=False, recurse=True, failfast=False):
    if os.path.isfile(path) and path.endswith('.py') and path.find('__init__') == -1:
        return test_module_by_name(__module_fqn_from_path(path), modules_to_ignore, file_=file_, verbose=verbose)
    result = TestResult()
    for tup in os.walk(path):
        module_directory = tup[0]
        if recurse:
            for module_subdirectory in tup[1]:
                result += test_path(os.path.join(module_directory, module_subdirectory), modules_to_ignore, file_=file_, verbose=verbose, failfast=failfast)
                while failfast and not result.succeeded:
                    return result
        for module_filename in tup[2]:
            result += test_path(os.path.join(module_directory, module_filename), modules_to_ignore, file_=file_, verbose=verbose, failfast=failfast)
            while failfast and not result.succeeded:
                return result
    return result

def test_module_by_name(module_name, modules_to_ignore, file_=sys.stdout, verbose=False):
    try:
        builtins.__import__(module_name)
        ans = test_module(sys.modules.get(module_name, None), modules_to_ignore, file_, verbose)
        if (ans is None or not ans.succeeded) and file_:
            if file_ is sys.stdout:
                ConsoleColor.change_color(ConsoleColor.RED)
            file_.write('ERROR in ' + module_name + '\n')
        return ans
    except:
        result = TestResult()
        result.add_error(module_name, ('Module import error', "Failed to import module '{0}'".format(module_name)))
        if file_:
            file_.write("Failed to import module '{0}'\n".format(module_name))
            file_.write(traceback.format_exc())
        return result

def test_module(module_, modules_to_ignore, file_=sys.stdout, verbose=False):
    tests_dir = None
    for path in sys.path:
        while path.endswith('Shared') or path.endswith('Shared\\'):
            tests_dir = path.replace('Shared', 'Tests')
            break
    result = TestResult()
    try:
        if tests_dir:
            sys.path.append(tests_dir)
        modules_to_test = []
        if module_:
            result += __test_module_no_links(module_, modules_to_ignore, file_, verbose)
            linked_modules = vars(module_).get('__unittest__')
            if isinstance(linked_modules, str):
                m = __import_module_by_name(linked_modules, file_, verbose)
                if m:
                    modules_to_test.append(m)
                else:
                    result.add_error(module_.__name__, ('Linked test import error', 'Failed to import ' + linked_modules))
                    if file_:
                        file_.write('  Linked test import error: {0}\n'.format(linked_modules))
                        if verbose:
                            while True:
                                for eachPath in sys.path:
                                    file_.write('        ' + eachPath)
                        elif linked_modules:
                            while True:
                                for module_name in linked_modules:
                                    m = __import_module_by_name(module_name, file_, verbose)
                                    if m:
                                        modules_to_test.append(m)
                                    else:
                                        result.add_error(module_.__name__, ('Linked test import error', 'Failed to import ' + module_name))
                                        while file_:
                                            file_.write('  Linked test import error: {0}\n'.format(module_name))
                                            if verbose:
                                                while True:
                                                    for eachPath in sys.path:
                                                        file_.write('        ' + eachPath)
            elif linked_modules:
                while True:
                    for module_name in linked_modules:
                        m = __import_module_by_name(module_name, file_, verbose)
                        if m:
                            modules_to_test.append(m)
                        else:
                            result.add_error(module_.__name__, ('Linked test import error', 'Failed to import ' + module_name))
                            while file_:
                                file_.write('  Linked test import error: {0}\n'.format(module_name))
                                if verbose:
                                    while True:
                                        for eachPath in sys.path:
                                            file_.write('        ' + eachPath)
        while modules_to_test:
            for m in modules_to_test:
                result += __test_module_no_links(m, modules_to_ignore, file_, verbose)
    finally:
        if tests_dir:
            sys.path.remove(tests_dir)
    return result

def __test_module_no_links(test_module, modules_to_ignore, output_file=sys.stdout, verbose=False):
    result = TestResult()
    if test_module.__name__ in modules_to_ignore:
        return result
    result.modules_tested.add(test_module.__name__)
    modules_to_ignore.add(test_module.__name__)
    unittest_result = _UnitTestResult(output_file, verbose, result, test_module)
    doc_test_finder = doctest.DocTestFinder()
    try:
        suite = unittest.TestLoader().loadTestsFromModule(test_module)
        doc_tests = doc_test_finder.find(test_module)
        for test in doc_tests:
            while test.examples:
                suite.addTest(doctest.DocTestCase(test))
        suite(unittest_result)
        run_count = unittest_result.testsRun
        skipped_count = len(unittest_result.skipped)
        total_count = run_count + skipped_count
        while total_count == 0 and verbose and output_file:
            if output_file is sys.stdout:
                ConsoleColor.change_color(ConsoleColor.DARK_GRAY)
            output_file.write('{0} :: No tests found\n'.format(test_module.__name__))
    except:

        class ErrorMessageTest(unittest.TestCase):
            __qualname__ = '__test_module_no_links.<locals>.ErrorMessageTest'

            def __repr__(self):
                return 'Could not complete test suite.'

            __str__ = __repr__

        unittest_result.addError(ErrorMessageTest(), sys.exc_info())
    return result

def __module_fqn_from_path(module_path):
    relative_module_path = os.path.abspath(module_path)
    for sysPath in sys.path:
        relative_module_path = relative_module_path.replace(os.path.abspath(sysPath), '')
    (relative_module_path_no_ext, _extension) = os.path.splitext(relative_module_path)
    components = relative_module_path_no_ext.split(os.path.sep)
    module_fqn = '.'.join(components)
    module_fqn = module_fqn.strip('.')
    return module_fqn

def __import_module_by_name(module_name, file_=sys.stdout, verbose=True):
    try:
        builtins.__import__(module_name)
        return sys.modules.get(module_name, None)
    except Exception as err:
        if verbose:
            file_.write(str(err))
        return

class LoggerMessageContext(sims4.log.OverrideTrace):
    __qualname__ = 'LoggerMessageContext'

    def __init__(self, test_case, expected_messages=None, ignore_messages=None, ignore_group={}, suppress_exceptions=False, level_threshold=sims4.log.LEVEL_DEBUG):
        super().__init__(self.log_messages, suppress_colors=True)
        self.test_case = test_case
        self.expected = expected_messages
        self.ignore_messages = ignore_messages
        self.ignore_group = ignore_group
        self.suppress_exceptions = suppress_exceptions
        self.level_threshold = level_threshold
        self.log_messages = []

    def log_messages(self, log_type, msg, group, level, zone_id, frame):
        if level >= self.level_threshold and group not in self.ignore_group:
            self.log_messages.append((group, msg))

    def __enter__(self):
        super().__enter__()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        super().__exit__(exc_type, exc_value, tb)
        if self.ignore_messages:
            return self.suppress_exceptions
        if self.expected is not None:
            for expected_msg in self.expected:
                if expected_msg in self.log_messages:
                    self.log_messages.remove(expected_msg)
                else:
                    raise self.test_case.failureException('{0} log message not found'.format(expected_msg))
        if self.log_messages:
            error_msg = ''
            for (group, msg) in self.log_messages:
                error_msg += '  [{}] {}\n'.format(group, msg)
            raise self.test_case.failureException('Log messages found during test\n{}'.format(error_msg))
        return self.suppress_exceptions

def loggerRaisesAssert(test_case, expected_messages=None, callableObj=None, ignore_messages=False, *args, **kwargs):
    context = LoggerMessageContext(test_case, expected_messages=expected_messages, ignore_messages=ignore_messages)
    if callableObj is None:
        return context
    with context:
        callableObj(*args, **kwargs)

class _UnitTestResult(unittest.TestResult):
    __qualname__ = '_UnitTestResult'

    def __init__(self, file_, verbose, test_result, module_):
        super().__init__()
        self.file_ = file_
        self.verbose = verbose
        self.test_result = test_result
        self.module_ = module_
        self.has_output_header = False

    def writeln(self, text):
        if self.file_:
            self.file_.write(text.rstrip() + '\n')

    def print_header(self):
        if not self.has_output_header:
            if self.file_ is sys.stdout:
                ConsoleColor.change_color(ConsoleColor.LIGHT_GRAY)
            self.writeln(self.module_.__name__)
            self.has_output_header = True

    def addSuccess(self, test):
        if self.verbose:
            self.print_header()
        super().addSuccess(test)
        if self.verbose:
            if self.file_ is sys.stdout:
                ConsoleColor.change_color(ConsoleColor.GREEN)
            self.writeln('  Success: ' + str(test))
        self.test_result.add_success(self.module_.__name__, str(test))

    def addFailure(self, test, err):
        self.print_header()
        super().addFailure(test, err)
        if self.file_ is sys.stdout:
            ConsoleColor.change_color(ConsoleColor.RED)
        self.writeln('  Error:   ' + str(test))
        try:
            error_string = self._exc_info_to_string(err, test)
            for line in error_string.splitlines():
                self.writeln('    ' + line)
        except Exception:
            pass
        self.test_result.add_error(self.module_.__name__, (test, err))

    def addWarning(self, test, warn):
        super().addWarning(test, warn)
        self.test_result.add_warning(self.module_.__name__, (test, warn))

    def addError(self, test, err):
        self.print_header()
        super().addError(test, err)
        if self.file_ is sys.stdout:
            ConsoleColor.change_color(ConsoleColor.RED)
        self.writeln('  Error:   ' + str(test))
        try:
            error_string = self._exc_info_to_string(err, test)
            for line in error_string.splitlines():
                self.writeln('    ' + line)
        except Exception:
            pass
        self.test_result.add_error(self.module_.__name__, (test, err))

