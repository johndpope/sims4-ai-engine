import objects.components.inventory_item
import objects.game_object
import objects.persistence_groups
import sims4.tuning.instances

class Jig(objects.game_object.GameObject):
    __qualname__ = 'Jig'

    @property
    def persistence_group(self):
        return objects.persistence_groups.PersistenceGroups.NONE

    def save_object(self, object_list, item_location=objects.components.inventory_item.ItemLocation.ON_LOT, container_id=0):
        pass

    @property
    def is_valid_posture_graph_object(self):
        return False

sims4.tuning.instances.lock_instance_tunables(Jig, _persists=False, _world_file_object_persists=False)
