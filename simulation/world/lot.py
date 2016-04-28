from protocolbuffers import Consts_pb2, UI_pb2
from distributor.system import Distributor
from objects.components import ComponentContainer
from objects.components.inventory import ObjectInventoryObject
from objects.components.inventory_enums import InventoryType
from objects.components.inventory_item import ItemLocation
from objects.components.statistic_component import HasStatisticComponent
from objects.system import create_object
from sims4.math import vector_normalize
from world.lot_tuning import GlobalLotTuningAndCleanup
import distributor
import services
import sims4.log
try:
    import _lot
except ImportError:

    class _lot:
        __qualname__ = '_lot'

        @staticmethod
        def get_lot_id_from_instance_id(*_, **__):
            return 0

        class Lot:
            __qualname__ = '_lot.Lot'

get_lot_id_from_instance_id = _lot.get_lot_id_from_instance_id
logger = sims4.log.Logger('Lot')

class Lot(ComponentContainer, HasStatisticComponent, _lot.Lot):
    __qualname__ = 'Lot'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inv_objs = {}
        self._front_door_id = None

    @property
    def center(self):
        return self.position

    @property
    def front_door_id(self):
        return self._front_door_id

    @front_door_id.setter
    def front_door_id(self, value):
        self._front_door_id = value

    def get_front_door(self):
        if self._front_door_id:
            return services.object_manager().get(self._front_door_id)

    def get_default_position(self, position=None):
        front_door = self.get_front_door()
        if front_door is not None:
            default_position = front_door.position
        elif position is not None:
            default_position = min(self.corners, key=lambda p: (p - position).magnitude_squared())
        else:
            default_position = self.corners[0]
        return default_position + vector_normalize(self.position - default_position)

    def get_hidden_inventory(self):
        inventory = self._get_object_inventory(InventoryType.HIDDEN)
        if inventory is None:
            inventory = self.create_object_inventory(InventoryType.HIDDEN)
        return inventory

    def create_object_in_hidden_inventory(self, definition_id):
        inventory = self.get_hidden_inventory()
        obj = create_object(definition_id, loc_type=ItemLocation.OBJECT_INVENTORY)
        try:
            inventory.system_add_object(obj, None)
            return obj
        except:
            obj.destroy(source=self, cause='Failed to place object in hidden inventory.')

    def get_mailbox_inventory(self):
        inventory = self._get_object_inventory(InventoryType.MAILBOX)
        if inventory is None:
            inventory = self.create_object_inventory(InventoryType.MAILBOX)
        return inventory

    def create_object_in_mailbox(self, definition_id):
        inventory = self.get_mailbox_inventory()
        if inventory is None:
            return
        obj = create_object(definition_id, loc_type=ItemLocation.OBJECT_INVENTORY)
        try:
            inventory.system_add_object(obj, None)
            return obj
        except:
            obj.destroy(source=self, cause='Failed to place object in mailbox.')

    def create_object_inventory(self, inv_type):
        obj = ObjectInventoryObject(inv_type)
        self.inv_objs[inv_type] = obj
        return obj.inventory_component

    def _get_object_inventory(self, inv_type):
        if inv_type in self.inv_objs:
            return self.inv_objs[inv_type].inventory_component

    def get_object_inventory(self, inv_type):
        if inv_type == InventoryType.HIDDEN:
            return self.get_hidden_inventory()
        return self._get_object_inventory(inv_type)

    def get_all_object_inventories_gen(self):
        for (inventory_type, inventory_object) in self.inv_objs.items():
            yield (inventory_type, inventory_object.inventory_component)

    def publish_shared_inventory_items(self):
        distributor = Distributor.instance()
        for (inventory_type, inventory_object) in self.inv_objs.items():
            if inventory_type == InventoryType.HIDDEN:
                pass
            for (obj, message_op) in inventory_object.get_item_update_ops_gen():
                distributor.add_op(obj, message_op)
            inventory_object.update_inventory_count()

    def send_lot_display_info(self):
        persistence = services.get_persistence_service()
        lot_owner_data = persistence.get_lot_proto_buff(self.lot_id)
        lot_name = None
        if lot_owner_data is not None:
            zone_data = persistence.get_zone_proto_buff(lot_owner_data.zone_instance_id)
            if zone_data is not None:
                lot_name = zone_data.name
        household = self.get_household()
        if household is not None:
            owner_household_name = household.name
        else:
            owner_household_name = None
        msg = UI_pb2.LotDisplayInfo()
        if lot_name is not None:
            msg.lot_name = lot_name
        if owner_household_name is not None:
            msg.household_name = owner_household_name
        op = distributor.shared_messages.create_message_op(msg, Consts_pb2.MSG_UI_LOT_DISPLAY_INFO)
        Distributor.instance().add_op_with_no_owner(op)

    def get_household(self):
        return services.household_manager().get(self.owner_household_id)

    def save(self, gameplay_zone_data, is_instantiated=True):
        gameplay_zone_data.ClearField('commodity_tracker')
        gameplay_zone_data.ClearField('statistics_tracker')
        gameplay_zone_data.ClearField('skill_tracker')
        if is_instantiated:
            GlobalLotTuningAndCleanup.calculate_object_quantity_statistic_values(self)
        self.update_all_commodities()
        (commodites, skill_statistics) = self.commodity_tracker.save()
        gameplay_zone_data.commodity_tracker.commodities.extend(commodites)
        regular_statistics = self.statistic_tracker.save()
        gameplay_zone_data.statistics_tracker.statistics.extend(regular_statistics)
        gameplay_zone_data.skill_tracker.skills.extend(skill_statistics)

    def load(self, gameplay_zone_data):
        self.commodity_tracker.load(gameplay_zone_data.commodity_tracker.commodities)
        self.statistic_tracker.load(gameplay_zone_data.statistics_tracker.statistics)
        self.commodity_tracker.load(gameplay_zone_data.skill_tracker.skills)

