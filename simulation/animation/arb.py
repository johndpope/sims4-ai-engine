from native.animation import arb
ClipEventType = arb.ClipEventType
set_tag_functions = arb.set_tag_functions

class Arb(arb.NativeArb):
    __qualname__ = 'Arb'

    def __init__(self):
        super().__init__()

    def add_request_info(self, animation_context, asm, state):
        pass

    def log_request_history(self, log_fn):
        pass

