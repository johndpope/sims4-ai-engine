from sims4.commands import Command

class ConsoleOutput:
    __qualname__ = 'ConsoleOutput'
    try:

        def write(self, message):
            import sims4.log
            text = message.strip('\n')
            if text:
                sims4.log.info('Console', text)

    except:

        def write(self, message):
            text = message.strip('\n')
            print(text)

@Command('test.module')
def run_module_test(module, verbose:bool=False, _connection=None):
    import sims4.testing.unit
    sims4.testing.unit.test_module_by_name(module, set(), verbose=bool(verbose), file_=ConsoleOutput())

@Command('test.path')
def run_path_test(filename, verbose:bool=False, _connection=None):
    import sims4.testing.unit
    sims4.testing.unit.test_path(filename, set(), verbose=bool(verbose), file_=ConsoleOutput())

