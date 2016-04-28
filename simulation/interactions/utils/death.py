from protocolbuffers import SimObjectAttributes_pb2 as protocols
from sims4.tuning.dynamic_enum import DynamicEnumLocked
import services
import sims4.reload
with sims4.reload.protected(globals()):
    _is_death_enabled = True

def toggle_death(enabled=None):
    global _is_death_enabled
    if enabled is None:
        _is_death_enabled = not _is_death_enabled
    else:
        _is_death_enabled = enabled

def is_death_enabled():
    return _is_death_enabled

class DeathType(DynamicEnumLocked):
    __qualname__ = 'DeathType'
    NONE = 0

class DeathTracker:
    __qualname__ = 'DeathTracker'
    DEATH_ZONE_ID = 0

    def __init__(self, sim_info):
        self._sim_info = sim_info
        self._death_type = None
        self._death_time = None

    @property
    def death_type(self):
        return self._death_type

    @property
    def death_time(self):
        return self._death_time

    @property
    def is_dead(self):
        if not self._death_type:
            return False
        return True

    def set_death_type(self, death_type):
        self._sim_info.inject_into_inactive_zone(self.DEATH_ZONE_ID)
        self._sim_info.household.remove_sim_info(self._sim_info, destroy_if_empty_gameplay_household=True)
        household = services.household_manager().create_household(self._sim_info.account)
        household.hidden = True
        household.add_sim_info(self._sim_info)
        self._sim_info.assign_to_household(household)
        self._death_type = death_type
        self._death_time = services.time_service().sim_now.absolute_ticks()
        self._sim_info.resend_death_type()

    def clear_death_type(self):
        self._death_type = None
        self._death_time = None
        self._sim_info.resend_death_type()

    def save(self):
        if self._death_type is not None:
            data = protocols.PersistableDeathTracker()
            data.death_type = self._death_type
            data.death_time = self._death_time
            return data

    def load(self, data):
        self._death_type = data.death_type
        self._death_time = data.death_time

