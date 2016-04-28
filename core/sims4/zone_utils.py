import collections
import itertools
import sims4.reload
import sims4.log
with sims4.reload.protected(globals()):
    _global_zone_id = None
zone_id_counter = itertools.count(1)
zone_numbers = collections.defaultdict(lambda : next(zone_id_counter), {0: 0})

class global_zone_lock:
    __qualname__ = 'global_zone_lock'
    __slots__ = ('zone_id', 'previous_zone_id')

    def __init__(self, zone_id):
        self.zone_id = zone_id
        self.previous_zone_id = None

    def __enter__(self):
        global _global_zone_id
        self.previous_zone_id = _global_zone_id
        _global_zone_id = self.zone_id

    def __exit__(self, exc_type, exc_value, traceback):
        global _global_zone_id
        _global_zone_id = self.previous_zone_id

    def c_api_enter(self):
        self.__enter__()

    def c_api_exit(self):
        self.__exit__(None, None, None)

def get_zone_id(can_be_none=False):
    if _global_zone_id is not None or can_be_none:
        return _global_zone_id
    sims4.log.callstack('MDZ', 'Attempt to get a zone from a tasklet that is not a job, and there is no global zone value active.', level=sims4.log.LEVEL_ERROR, owner='pingebretson')
    return 0

