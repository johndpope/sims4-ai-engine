import time
import sims4.log
import functools
logger = sims4.log.Logger('Profile')
debug_stack_depth = 0
output_strings = []
all_profile_functions = []
sub_start_time = 0


def sub_time_start():
    global sub_start_time
    if debug_stack_depth > 0:
        sub_start_time = time.clock()


def sub_time_end(sub_time_id, precision=5):
    if debug_stack_depth > 0:
        output_strings.append(('Sub: {1}, Time: {2:.{3}f}', debug_stack_depth,
                               (sub_time_id, time.clock() - sub_start_time,
                                precision)))


def add_string(format_string, indent=0, *args):
    output_strings.append((format_string, indent, args))


class profile_function:
    __qualname__ = 'profile_function'

    def __init__(self,
                 indent=None,
                 show_enter=False,
                 id_str='',
                 only_in_stack=False,
                 threshold=None,
                 precision=5,
                 output_to_file=False):
        self.time = 0
        self.total_time = 0
        self.num_calls = 0
        self.func_name = None
        self.show_enter = show_enter
        self.id_str = id_str
        self.threshold = threshold
        self.precision = precision
        self.output_to_file = output_to_file
        if indent is None:
            self.stack_indent = True
        else:
            self.stack_indent = False
            self.indent = indent
        self.only_in_stack = only_in_stack
        all_profile_functions.append(self)

    def _aftercall(self, func_return, start_time, func_name):
        global debug_stack_depth
        end_time = time.clock()
        self.time = end_time - start_time
        warning_str = ''
        if self.threshold is not None and self.threshold < self.time:
            warning_str = '(WARNING)'
        debug_stack_depth -= 1
        if self.stack_indent:
            self.indent = debug_stack_depth
        output_strings.append((
            'Exit: {1}({2}), Num Calls: {3}, Time this Run: {4:.{7}f}{5}, Total Time: {6:.{7}f}',
            self.indent, (func_name, self.id_str, self.num_calls, self.time,
                          warning_str, self.total_time, self.precision)))
        if debug_stack_depth == 0:
            self.print_output_strings()

    def __call__(self, func):
        def wrapper(*args, **kwargs):
            global debug_stack_depth
            if not self.only_in_stack or debug_stack_depth > 0:
                if self.stack_indent:
                    self.indent = debug_stack_depth
                debug_stack_depth += 1
                start_time = time.clock()
                self.func_name = func.__name__
                if self.show_enter:
                    output_strings.append(('Enter: {1}', self.indent, (
                        func.__name__, )))
                function = func(*args, **kwargs)
                self._aftercall(function, start_time, func.__name__)
                return function
            return func(*args, **kwargs)

        return functools.update_wrapper(wrapper, func)

    def print_output_strings(self):
        try:
            if self.output_to_file:
                f = open('perf_test_results.txt', 'a')
            for debug_output in output_strings:
                string = debug_output[0]
                output_string = '{}{}'.format('{0}', string)
                indent = debug_output[1]
                indent_str = indent * '   '
                string_args = debug_output[2]
                if self.output_to_file:
                    f.write(output_string.format(indent_str, *string_args) +
                            '\n')
                else:
                    logger.error(output_string, indent_str, *string_args)
        finally:
            if self.output_to_file:
                f.close()
        del output_strings[:]
