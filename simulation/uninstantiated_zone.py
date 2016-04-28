from world.lot import Lot
import services

class UninstantiatedZone:
    __qualname__ = 'UninstantiatedZone'

    def __init__(self, zone_id):
        self.id = zone_id
        self.neighborhood_id = 0
        self.lot = Lot(zone_id)

    @property
    def is_instantiated(self):
        return False

    def _get_zone_proto(self):
        return services.get_persistence_service().get_zone_proto_buff(self.id)

    def save_zone(self, save_slot_data=None):
        zone_data_msg = self._get_zone_proto()
        self.lot.save(zone_data_msg.gameplay_zone_data, is_instantiated=False)

    def load(self):
        zone_data_msg = self._get_zone_proto()
        self.lot.load(zone_data_msg.gameplay_zone_data)

