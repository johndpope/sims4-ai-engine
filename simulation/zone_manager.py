from indexed_manager import IndexedManager
from uninstantiated_zone import UninstantiatedZone
import sims4.gsi.dispatcher
import sims4.zone_utils
import zone


class ZoneManager(IndexedManager):
    __qualname__ = 'ZoneManager'

    def get(self, zone_id, allow_uninstantiated_zones=False):
        zone = super().get(zone_id)
        if zone is not None and not zone.is_instantiated and not allow_uninstantiated_zones:
            return
        return zone

    def create_zone(self, zone_id, gameplay_zone_data, save_slot_data):
        if sims4.zone_utils._global_zone_id is not None:
            raise RuntimeError('_global_zone_id is already set to {}'.format(
                sims4.zone_utils._global_zone_id))
        sims4.zone_utils._global_zone_id = zone_id
        if save_slot_data is not None:
            save_slot_data_id = save_slot_data.slot_id
        else:
            save_slot_data_id = None
        new_zone = zone.Zone(zone_id, save_slot_data_id)
        self.add(new_zone)
        new_zone.start_services(gameplay_zone_data, save_slot_data)
        return new_zone

    def remove_id(self, obj_id):
        super().remove_id(obj_id)
        if sims4.zone_utils._global_zone_id == obj_id:
            sims4.zone_utils._global_zone_id = None

    def shutdown(self):
        key_list = list(self._objects.keys())
        for k in key_list:
            self.remove_id(k)

    def get_current_zone(self):
        return self.get(sims4.zone_utils.get_zone_id())

    def start(self):
        super().start()
        sims4.gsi.dispatcher.register_zone_manager(self)

    def stop(self):
        super().stop()
        sims4.gsi.dispatcher.register_zone_manager(None)

    def save(self, save_slot_data=None):
        for zone in self.values():
            zone.save_zone(save_slot_data=save_slot_data)

    def load_uninstantiated_zone_data(self, zone_id):
        if zone_id in self:
            return
        new_uninstantiated_zone = UninstantiatedZone(zone_id)
        self.add(new_uninstantiated_zone)
        new_uninstantiated_zone.load()

    def cleanup_uninstantiated_zones(self):
        for (zone_id, zone) in tuple(self.items()):
            while not zone.is_instantiated:
                self.remove_id(zone_id)
