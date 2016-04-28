from collections import namedtuple
from distributor.rollback import ProtocolBufferRollback
from protocolbuffers import SimObjectAttributes_pb2 as protocols
from sims4.tuning.tunable import TunableVariant, TunableReference
import services
import sims4
Unlock = namedtuple('Unlock', ('tuning_class', 'name'))
logger = sims4.log.Logger('UnlockTracker')

class TunableUnlockVariant(TunableVariant):
    __qualname__ = 'TunableUnlockVariant'

    def __init__(self, **kwargs):
        super().__init__(unlock_recipe=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.RECIPE)), **kwargs)

class UnlockTracker:
    __qualname__ = 'UnlockTracker'

    def __init__(self, sim_info):
        self._sim_info = sim_info
        self._unlocks = []

    def add_unlock(self, tuning_class, name):
        self._unlocks.append(Unlock(tuning_class, name))

    def get_unlocks(self, tuning_class):
        return [unlock for unlock in self._unlocks if issubclass(unlock.tuning_class, tuning_class)]

    def get_unlocks_by_type(self, resource_type):
        return [unlock for unlock in self._unlocks if unlock.tuning_class.tuning_manager.TYPE == resource_type]

    def is_unlocked(self, tuning_class):
        return any(unlock.tuning_class is tuning_class for unlock in self._unlocks)

    def save_unlock(self):
        unlock_tracker_data = protocols.PersistableUnlockTracker()
        for unlock in self._unlocks:
            with ProtocolBufferRollback(unlock_tracker_data.unlock_data_list) as unlock_data:
                unlock_data.unlock_instance_id = unlock.tuning_class.guid64
                unlock_data.unlock_instance_type = unlock.tuning_class.tuning_manager.TYPE
                while unlock.name is not None:
                    unlock_data.custom_name = unlock.name
        return unlock_tracker_data

    def load_unlock(self, unlock_proto_msg):
        for unlock_data in unlock_proto_msg.unlock_data_list:
            instance_id = unlock_data.unlock_instance_id
            instance_type = unlock_data.unlock_instance_type
            manager = services.get_instance_manager(instance_type)
            if manager is None:
                logger.error('Loading: Sim {} fail to get instance manager for unlock item {}, type {}', self.owner, instance_id, instance_type, owner='cjiang')
            tuning_class = manager.get(instance_id)
            if tuning_class is None:
                logger.error('Loading: Sim {} fail to get class for unlock item {}, type {}', self.owner, instance_id, instance_type, owner='cjiang')
            self._unlocks.append(Unlock(tuning_class, unlock_data.custom_name))

