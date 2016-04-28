import sims4.log
from contextlib import contextmanager
logger = sims4.log.Logger('Profiler')
if __profile__:
    import _profiler
    begin_scope = _profiler.begin_scope
    end_scope = _profiler.end_scope
    enable_profiler = _profiler.begin
    disable_profiler = _profiler.end
    flush = _profiler.flush
else:

    def enable_profiler(*args, **kwargs):
        logger.error('__profile__ is not set. Did you forget to pass in the command line argument?')

    def disable_profiler(*args, **kwargs):
        pass

    def begin_scope(*args, **kwargs):
        logger.error('__profile__ is not set. Did you forget to pass in the command line argument?')

    def begin_scope(*args, **kwargs):
        logger.error('__profile__ is not set. Did you forget to pass in the command line argument?')

@contextmanager
def scope(name):
    if __profile__:
        sims4.profiler.begin_scope(name)
    try:
        yield None
    finally:
        if __profile__:
            sims4.profiler.end_scope()

