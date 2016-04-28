import sims4.commands

@sims4.commands.Command('diagnostic.stack_overflow')
def diagnostic_stack_overflow(_connection=None):

    def recursive_fn():
        recursive_fn()

    recursive_fn()

@sims4.commands.Command('diagnostic.stack_overflow_property')
def diagnostic_stack_overflow_property(_connection=None):

    class Rec:
        __qualname__ = 'diagnostic_stack_overflow_property.<locals>.Rec'

        @property
        def recursive_property(self):
            return self.recursive_property

    Rec().recursive_property

@sims4.commands.Command('diagnostic.infinite_loop')
def diagnostic_infinite_loop(_connection=None):
    while True:
        pass

