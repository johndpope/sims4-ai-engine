from protocolbuffers import UI_pb2, FileSerialization_pb2 as serialization
from protocolbuffers.DistributorOps_pb2 import Operation
import weakref
from animation.posture_manifest import AnimationParticipant
from animation.posture_manifest_constants import STAND_OR_SIT_CONSTRAINT
from build_buy import ObjectOriginLocation
from distributor.ops import GenericProtocolBufferOp
from distributor.shared_messages import build_icon_info_msg
from distributor.system import Distributor
from event_testing.test_events import TestEvent
from event_testing.tests import TunableTestSet
from interactions import ParticipantType
from interactions.constraints import create_constraint_set
from interactions.utils.interaction_elements import XevtTriggeredElement
from objects.components import Component, types, ComponentContainer, componentmethod, componentmethod_with_fallback
from objects.components.get_put_component_mixin import GetPutComponentMixin
from objects.components.inventory_enums import InventoryType, InventoryTypeTuning
from objects.components.inventory_item import ItemLocation
from objects.components.state import ObjectStateValue
from objects.object_enums import ResetReason
from objects.system import create_object
from postures.posture_specs import PostureSpecVariable
from server.live_drag_tuning import LiveDragState
from services.reset_and_delete_service import ResetRecord
from sims4.tuning.tunable import TunableEnumEntry, Tunable, TunableList, TunableReference, TunableMapping, AutoFactoryInit, HasTunableFactory, TunableVariant, OptionalTunable, TunableTuple
from singletons import DEFAULT
from statistics.statistic import Statistic
import build_buy
import enum
import event_testing
import objects.system
import services
import sims4.log
import telemetry_helper
logger = sims4.log.Logger(types.INVENTORY_COMPONENT.class_attr)
TELEMETRY_GROUP_INVENTORY = 'INVT'
TELEMETRY_HOOK_ADD_TO_INV = 'IADD'
TELEMETRY_HOOK_REMOVE_FROM_INV = 'IREM'
TELEMETRY_HOOK_TOGGLE_LOCK = 'LOCK'
TELEMETRY_FIELD_ID = 'guid'
TELEMETRY_FIELD_INV_TYPE = 'type'
TELEMETRY_FIELD_IS_LOCKED = 'ison'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_INVENTORY)

class _InventoryComponent(Component):
    __qualname__ = '_InventoryComponent'
    INVENTORY_TRANSFORM = sims4.math.Transform(sims4.math.Vector3.ZERO(), sims4.math.Quaternion.IDENTITY())

    def __init__(self, owner, inventory_type, max_size=sims4.math.MAX_UINT32, max_overflow_size=0):
        super().__init__(owner)
        self._inventory_type = inventory_type
        self._max_size = max_size
        self._max_overflow_size = max_overflow_size
        if max_size:
            self._inventory_items = {}
        if max_overflow_size:
            self._overflow_items = []
        self.inventory_manager = services.current_zone().inventory_manager
        self._inventory_state_triggers = []

    @property
    def inventory_value(self):
        return sum(obj.current_value*obj.stack_count() for obj in self)

    @property
    def should_score_contained_objects_for_autonomy(self):
        return True

    def __len__(self):
        ret = 0
        if self.max_size:
            ret = len(self._inventory_items)
        if self.max_overflow_size:
            ret += len(self._overflow_items)
        return ret

    def __iter__(self):
        if self.max_size:
            for obj in self._inventory_items.values():
                yield obj
        if self.max_overflow_size:
            for obj in self._overflow_items:
                yield obj

    @property
    def max_size(self):
        return self._max_size

    @property
    def max_overflow_size(self):
        return self._max_overflow_size

    @property
    def max_total_size(self):
        return self.max_size + self.max_overflow_size

    @property
    def gameplay_effects(self):
        return InventoryTypeTuning.GAMEPLAY_MODIFIERS.get(self._inventory_type)

    @property
    def inventory_type(self):
        return self._inventory_type

    def _get_id(self, obj_or_id):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        if hasattr('id', obj_or_id):
            return obj_or_id.id
        return obj_or_id

    def _common_test(self, obj, error_on_failure=True):
        if not obj.inventoryitem_component:
            if error_on_failure:
                logger.error('Attempt to add an object: {0} to inventory {1} with no InventoryItem Component.', obj, self, owner='mduke')
            return False
        if not obj.can_go_in_inventory_type(self._inventory_type):
            if error_on_failure:
                logger.error('Attempt to add an object: {0} to inventory of type {1} is not valid. You may need to update your InventoryItem Component.', obj, self._inventory_type, owner='mduke')
            return False
        if len(self) >= self.max_total_size:
            return False
        return True

    def can_add(self, obj):
        return self._common_test(obj, error_on_failure=False)

    def _added(self, obj, send_ui=True, object_with_inventory=None):
        obj.inventoryitem_component.set_inventory_type(self._inventory_type, object_with_inventory)
        if obj.id in services.object_manager():
            services.object_manager().move_to_inventory(obj, self.inventory_manager)
            obj.clear_parent(self.INVENTORY_TRANSFORM, None)
            for state_trigger in self._inventory_state_triggers:
                state_trigger.on_object_added(obj)
        if send_ui:
            self._added_ui_update(obj)

    def _removed(self, obj, send_ui=True, on_manager_remove=False):
        obj.inventoryitem_component.set_inventory_type(None, None)
        if not on_manager_remove:
            self.inventory_manager.move_to_world(obj, services.object_manager())
            for state_trigger in self._inventory_state_triggers:
                state_trigger.on_obj_removed(obj)
        if send_ui:
            self._removed_ui_update(obj)

    def _on_update(self):
        pass

    def add_state_trigger(self, state_trigger):
        for exist_state_trigger in self._inventory_state_triggers:
            while exist_state_trigger.compare(state_trigger):
                return
        self._inventory_state_triggers.append(state_trigger)

    def object_state_update_callback(self, old_state, new_state):
        for state_trigger in self._inventory_state_triggers:
            state_trigger.obj_state_changed(old_state, new_state)

    def set_owner_object_state(self, state_value):
        pass

    def player_try_add_object(self, obj, **insert_item_kwargs):
        if self._common_test(obj, error_on_failure=False) and self._insert_item(obj, use_overflow=False, call_add=True, **insert_item_kwargs):
            return True
        return False

    def system_add_object(self, obj, object_with_inventory):
        if not self._common_test(obj):
            logger.error('Attempt to add object ({}) which failed the common test.', obj, owner='mduke')
            obj.destroy(source=self.owner, cause='Attempt to add object which failed the common test.')
            return
        if not self._insert_item(obj, use_overflow=True, call_add=True, object_with_inventory=object_with_inventory):
            logger.error('Attempt to use system_add_object on an inventory with no overflow space.', owner='mduke')

    def _insert_item(self, obj, use_overflow=False, call_add=False, object_with_inventory=None, try_find_matching_item=True):
        if try_find_matching_item:
            matching_obj = self._find_matching_item(obj, object_with_inventory)
            if matching_obj is not None:
                self._stack_addition(matching_obj, obj)
                if call_add:
                    self._added(obj, send_ui=False, object_with_inventory=object_with_inventory)
                return True
        if self.max_size and len(self._inventory_items) < self.max_size:
            self._inventory_items[obj.id] = obj
            obj.item_location = self._get_default_item_location()
            if call_add:
                self._added(obj, object_with_inventory=object_with_inventory)
            return True
        if use_overflow and self.max_overflow_size:
            if len(self._overflow_items) == self.max_overflow_size:
                obj_to_destroy = self._overflow_items.pop(0)
                logger.warn('Overflow inventory item being destroyed: {0}', obj_to_destroy)
                obj_to_destroy.destroy(source=self.owner, cause='Overflow inventory item being destroyed.')
            self._overflow_items.append(obj)
            if call_add:
                self._added(obj, object_with_inventory=object_with_inventory)
            return True
        return False

    def _find_matching_item(self, obj_to_match, object_with_inventory):
        def_id = obj_to_match.definition.id
        save_data = None
        for obj in self:
            while obj.definition.id == def_id:
                if not save_data:
                    obj_to_match.inventoryitem_component.set_inventory_type(self._inventory_type, object_with_inventory)
                    save_data = obj_to_match.get_attribute_save_data()
                    obj_to_match.inventoryitem_component.set_inventory_type(None, None)
                obj_count = obj.stack_count()
                obj.set_stack_count(obj_to_match.stack_count())
                obj_save_data = obj.get_attribute_save_data()
                obj.set_stack_count(obj_count)
                if save_data == obj_save_data:
                    return obj

    def try_remove_object_by_id(self, obj_id, on_manager_remove=False, force_remove_stack=False):
        if self.max_size:
            obj = self._inventory_items.get(obj_id)
            if obj is not None:
                in_stack = obj.stack_count() > 1
                self._inventory_items.pop(obj_id)
                obj.item_location = ItemLocation.ON_LOT
                if not force_remove_stack and in_stack and not on_manager_remove:
                    self._try_stack_removal(obj)
                send_ui = not in_stack or force_remove_stack
                self._removed(obj, send_ui=send_ui, on_manager_remove=on_manager_remove)
                if (force_remove_stack or not in_stack) and self.max_overflow_size and self._overflow_items:
                    obj = self._overflow_items.pop(0)
                    self._inventory_items[obj.id] = obj
                return True
        if self.max_overflow_size:
            for obj in self._overflow_items:
                while obj.id == obj_id:
                    if not force_remove_stack and self._try_stack_removal(obj):
                        return True
                    self._overflow_items.remove(obj)
                    self._removed(obj, on_manager_remove=on_manager_remove)
                    return True
        return False

    def _stack_addition(self, obj, new_obj):
        obj.update_stack_count(new_obj.stack_count())
        new_count = obj.stack_count()
        new_obj.set_stack_count(new_count)
        old_obj_id = obj.id
        obj.destroy(source=self.owner, cause='Object being added to a stack')
        self._obj_stacked(new_obj, old_obj_id)
        self._inventory_items[new_obj.id] = new_obj

    def _try_stack_removal(self, obj):
        if obj.stack_count() > 1:
            clone = obj.clone(loc_type=self._get_default_item_location())
            clone.update_stack_count(-1)
            obj.set_stack_count(1)
            self._obj_stacked(clone, obj.id)
            self._inventory_items[clone.id] = clone
            return True
        return False

    def purge_inventory(self, send_ui_message=True):
        all_objs = list(self)
        for obj in all_objs:
            if send_ui_message:
                self._removed_ui_update(obj)
            obj.destroy(source=self.owner, cause='Purging inventory')

    def try_destroy_object_by_definition(self, obj_def, source=None, cause=None):
        for obj in self:
            while obj.definition == obj_def:
                if self.try_remove_object_by_id(obj.id):
                    obj.destroy(source=source, cause=cause)
                    return True
                return False
        return False

    def try_destroy_object(self, obj, force_remove_stack=False, source=None, cause=None):
        if self.try_remove_object_by_id(obj.id, force_remove_stack=force_remove_stack):
            obj.destroy(source=source, cause=cause)
            return True
        return False

    def get_object_by_id(self, obj_id):
        if self.max_size:
            obj = self._inventory_items.get(obj_id)
            if obj is not None:
                return obj
        if self.max_overflow_size:
            for obj in self._overflow_items:
                while obj.id == obj_id:
                    return obj

    def get_items_with_definition_gen(self, obj_def):
        yield (obj for obj in self if obj.definition is obj_def)

    def get_item_with_definition(self, obj_def):
        for obj in self.get_items_with_definition_gen(obj_def):
            pass

    def has_item_with_definition(self, obj_def):
        return any(obj.definition is obj_def for obj in self)

    def get_count(self, obj_def):
        return sum(obj.stack_count() for obj in self if obj.definition is obj_def)

    def get_item_quantity_by_definition(self, obj_def):
        return sum(obj.stack_count() for obj in self._inventory_items.values() if obj.definition is obj_def)

    def _get_default_item_location(self):
        return ItemLocation.OBJECT_INVENTORY

    def get_list_object_by_definition(self, obj_def):
        return list(self.get_items_with_definition_gen(obj_def))

    def get_stack_items(self, stack_id):
        items = []
        for obj in self:
            obj_stack_id = obj.inventoryitem_component.get_stack_id()
            while obj_stack_id == stack_id:
                items.append(obj)
        items.sort(key=lambda item: item.get_stack_sort_order())
        return items

    def is_object_hidden(self, obj):
        return False

    def _get_inventory_id(self):
        raise NotImplementedError

    def _get_inventory_ui_type(self):
        raise NotImplementedError

    def _get_add_to_client_msg(self, obj):
        msg = UI_pb2.InventoryItemUpdate()
        msg.type = UI_pb2.InventoryItemUpdate.TYPE_ADD
        msg.inventory_id = self._get_inventory_id()
        msg.inventory_type = self._get_inventory_ui_type()
        msg.stack_id = obj.inventoryitem_component.get_stack_id()
        msg.object_id = obj.id
        add_data = UI_pb2.InventoryItemData()
        add_data.definition_id = obj.definition.id
        dynamic_data = UI_pb2.DynamicInventoryItemData()
        dynamic_data.value = obj.current_value
        dynamic_data.locked = False
        dynamic_data.in_use = False
        dynamic_data.count = obj.stack_count()
        dynamic_data.is_new = obj.new_in_inventory
        dynamic_data.sort_order = obj.get_stack_sort_order()
        icon_info = obj.get_icon_info_data()
        build_icon_info_msg(icon_info, None, dynamic_data.icon_info)
        add_data.dynamic_data = dynamic_data
        msg.add_data = add_data
        return msg

    def _added_ui_update(self, obj):
        distributor = Distributor.instance()
        distributor.add_op(obj, GenericProtocolBufferOp(Operation.INVENTORY_ITEM_UPDATE, self._get_add_to_client_msg(obj)))

    def _removed_ui_update(self, obj):
        msg = UI_pb2.InventoryItemUpdate()
        msg.type = UI_pb2.InventoryItemUpdate.TYPE_REMOVE
        msg.inventory_id = self._get_inventory_id()
        msg.inventory_type = self._get_inventory_ui_type()
        msg.object_id = obj.id
        msg.stack_id = obj.inventoryitem_component.get_stack_id()
        distributor = Distributor.instance()
        distributor.add_op(obj, GenericProtocolBufferOp(Operation.INVENTORY_ITEM_UPDATE, msg))

    def _updated_ui_update(self, obj, old_obj_id, update_data):
        msg = UI_pb2.InventoryItemUpdate()
        msg.type = UI_pb2.InventoryItemUpdate.TYPE_UPDATE
        msg.inventory_id = self._get_inventory_id()
        msg.inventory_type = self._get_inventory_ui_type()
        msg.object_id = old_obj_id
        msg.update_data = update_data
        msg.stack_id = obj.inventoryitem_component.get_stack_id()
        distributor = Distributor.instance()
        distributor.add_op(obj, GenericProtocolBufferOp(Operation.INVENTORY_ITEM_UPDATE, msg))

    def _obj_stacked(self, new_object, old_obj_id):
        update_data = UI_pb2.DynamicInventoryItemData()
        update_data.count = new_object.stack_count()
        update_data.sort_order = new_object.get_stack_sort_order()
        update_data.new_object_id = new_object.id
        update_data.is_new = new_object.new_in_inventory
        icon_info = new_object.get_icon_info_data()
        build_icon_info_msg(icon_info, None, update_data.icon_info)
        self._updated_ui_update(new_object, old_obj_id, update_data)

    def push_inventory_item_update_msg(self, object_updated):
        update_data = UI_pb2.DynamicInventoryItemData()
        update_data.count = object_updated.stack_count()
        update_data.sort_order = object_updated.get_stack_sort_order()
        update_data.new_object_id = object_updated.id
        update_data.is_new = object_updated.new_in_inventory
        icon_info = object_updated.get_icon_info_data()
        build_icon_info_msg(icon_info, None, update_data.icon_info)
        self._updated_ui_update(object_updated, object_updated.id, update_data)

    @componentmethod
    def inventory_view_update(self):
        for obj in list(self._inventory_items.values()):
            while obj.new_in_inventory:
                obj.new_in_inventory = False
                self.push_inventory_item_update_msg(obj)

    def _open_ui_panel_for_object(self, owner):
        msg = UI_pb2.OpenInventory()
        msg.object_id = owner.id
        msg.inventory_id = self._get_inventory_id()
        msg.inventory_type = self._get_inventory_ui_type()
        distributor = Distributor.instance()
        distributor.add_op_with_no_owner(GenericProtocolBufferOp(Operation.OPEN_INVENTORY, msg))

class UniqueObjectInventoryComponent(_InventoryComponent, component_name=types.INVENTORY_COMPONENT):
    __qualname__ = 'UniqueObjectInventoryComponent'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._hidden_inventory_items = {}

    def __len__(self):
        ret = super().__len__()
        ret += len(self._hidden_inventory_items)
        return ret

    def __iter__(self):
        for obj in super().__iter__():
            yield obj
        for obj in self._hidden_inventory_items.values():
            yield obj

    def _get_inventory_id(self):
        return self.owner.id

    def _get_inventory_ui_type(self):
        return UI_pb2.InventoryItemUpdate.TYPE_OBJECT

    @property
    def is_empty(self):
        return not self._inventory_items and not self._overflow_items

    def should_load(self, obj_data):
        return True

    @componentmethod
    def get_inventory_access_constraint(self, sim, is_put, carry_target, use_owner_as_target_for_resolver=False):
        return STAND_OR_SIT_CONSTRAINT

    @componentmethod
    def get_inventory_access_animation(self, *args, **kwargs):
        pass

    @componentmethod_with_fallback(lambda _: None)
    def save_unique_inventory_objects(self, save_data):
        if save_data is not None:
            save_data.unique_inventory = self.save_items()

    @componentmethod_with_fallback(lambda _: None)
    def load_unique_inventory_objects(self, object_data):
        self.load_items(object_data.unique_inventory)

    def get_items_with_definition_gen(self, obj_def, ignore_hidden=False):
        if ignore_hidden:
            yield (obj for obj in self._inventory_items.values() if obj.definition is obj_def)
        else:
            yield super().get_items_with_definition_gen(obj_def)

    def get_item_with_definition(self, obj_def, ignore_hidden=False):
        for obj in self.get_items_with_definition_gen(obj_def, ignore_hidden):
            pass

    def _insert_item(self, obj, use_overflow=False, call_add=False, object_with_inventory=None, try_find_matching_item=True, force_add_to_hidden_inventory=False):
        if force_add_to_hidden_inventory or obj.inventoryitem_component is not None and not obj.inventoryitem_component.visible:
            self._hidden_inventory_items[obj.id] = obj
            self._added(obj, send_ui=False, object_with_inventory=object_with_inventory)
            return True
        return super()._insert_item(obj, use_overflow, call_add, object_with_inventory, try_find_matching_item=try_find_matching_item)

    def player_try_add_object(self, obj, mark_as_new_object=False, object_with_inventory=None):
        return super().player_try_add_object(obj, object_with_inventory=self.owner)

    def _added(self, obj, object_with_inventory=None, **kwargs):
        super()._added(obj, object_with_inventory=self.owner, **kwargs)

    def try_remove_object_by_id(self, obj_id, on_manager_remove=False, force_remove_stack=False):
        if super().try_remove_object_by_id(obj_id, on_manager_remove=on_manager_remove, force_remove_stack=force_remove_stack):
            return True
        item = self._hidden_inventory_items.pop(obj_id, None)
        if item is not None:
            return True
        return False

    def try_move_object_to_hidden_inventory(self, obj):
        if not self.try_remove_object_by_id(obj.id):
            logger.warn("Tried moving item, {}, to hidden inventory, but item was not found in the Sim's, {}, inventory.", obj, self.owner, owner='TrevorLindsey')
            return False
        if not self._insert_item(obj, force_add_to_hidden_inventory=True):
            logger.warn("Tried moving item, {}, to hidden inventory but failed. Going to try putting it back into the Sim's inventory. No warning will show if the re-add fails.", obj, owner='TrevorLindsey')
            self._insert_item(obj)
            return False
        return True

    def is_object_hidden(self, obj):
        return obj in self._hidden_inventory_items

    def save_items(self):
        inventory_msg = serialization.ObjectList()
        for obj in self:
            obj.save_object(inventory_msg.objects, ItemLocation.SIM_INVENTORY, self.owner.id)
        return inventory_msg

    def load_items(self, save_data):
        if not save_data.objects:
            return
        for obj_data in save_data.objects:

            def post_create_inventory_object(obj):
                obj.load_object(obj_data)
                obj.on_added_to_inventory()
                if not self._insert_item(obj, use_overflow=True, call_add=True, object_with_inventory=self.owner, try_find_matching_item=False):
                    logger.error('Failure to load back a persisted sim inventory item. Item {} will be destroyed.  Tuning has likely changed.', obj, owner='mduke')
                    obj.destroy(source=self.owner, cause='Failed to load a persisted sim inventory item.  Tuning has likely changed')

            if not self.should_load(obj_data):
                pass
            objects.system.create_object(obj_data.guid or obj_data.type, obj_id=obj_data.object_id, loc_type=obj_data.loc_type, post_add=post_create_inventory_object)

    def on_remove(self):
        self.purge_inventory(send_ui_message=False)

    def _get_default_item_location(self):
        return ItemLocation.SIM_INVENTORY

    def push_items_to_household_inventory(self):
        client = services.client_manager().get_first_client()
        for obj in list(self._inventory_items.values()):
            if obj in client.live_drag_objects:
                client.cancel_live_drag(obj)
            while not obj.consumable_component is not None:
                if obj.has_servings_statistic():
                    pass
                try:
                    while self.try_remove_object_by_id(obj.id, force_remove_stack=True):
                        build_buy.move_object_to_household_inventory(obj, object_location_type=ObjectOriginLocation.SIM_INVENTORY)
                except Exception:
                    logger.exception('{} failed to push object from inventory to household inventory', obj)

    def open_ui_panel(self):
        super()._open_ui_panel_for_object(self.owner)

    def on_reset_component_get_interdependent_reset_records(self, reset_reason, reset_records):
        if reset_reason == ResetReason.BEING_DESTROYED:
            for obj in self:
                obj.inventoryitem_component.set_inventory_type(None, None)
                reset_records.append(ResetRecord(obj, reset_reason, self, 'In inventory'))
            self._hidden_inventory_items.clear()
            if self.max_size:
                self._inventory_items.clear()
            if self.max_overflow_size:
                self._overflow_items.clear()

class SimInventoryComponent(UniqueObjectInventoryComponent):
    __qualname__ = 'SimInventoryComponent'
    SIM_INVENTORY_OVERFLOW_SIZE = Tunable(int, 8, description='Number of overflow spots before items start getting deleted from a sim inventory.')
    SIM_INVENTORY_STARTING_SIZE = Tunable(int, 10000, description='Number of spots in sim inventory.')

    def __init__(self, owner):
        super().__init__(owner=owner, inventory_type=InventoryType.SIM, max_size=self.SIM_INVENTORY_STARTING_SIZE, max_overflow_size=self.SIM_INVENTORY_OVERFLOW_SIZE)

    def should_load(self, obj_data):
        if self.owner.household.id != obj_data.owner_id:
            zone = services.current_zone()
            if zone.is_zone_running:
                return False
            if not zone.should_restore_sis():
                return False
            sim_info = self.owner.sim_info
            if sim_info not in services.sim_info_manager().get_sim_infos_saved_in_zone() and sim_info not in services.sim_info_manager().get_sim_infos_saved_in_open_streets():
                return False
        return True

class FishBowlInventoryComponent(UniqueObjectInventoryComponent):
    __qualname__ = 'FishBowlInventoryComponent'

    def __init__(self, owner):
        super().__init__(owner=owner, inventory_type=InventoryType.FISHBOWL, max_size=1, max_overflow_size=0)

    def get_items_for_autonomy_gen(self, motives=DEFAULT):
        return ()

    @property
    def is_empty(self):
        return not self._inventory_items

    def _added(self, obj, object_with_inventory=None, **kwargs):
        super()._added(obj, object_with_inventory, **kwargs)
        self.owner.fish_added(obj)

    def _removed(self, *args, **kwargs):
        super()._removed(*args, **kwargs)
        self.owner.fish_removed()

class ObjectsInObjectInventoryComponent(_InventoryComponent, component_name=types.INVENTORY_COMPONENT):
    __qualname__ = 'ObjectsInObjectInventoryComponent'

    def __init__(self, owner, inventory_type):
        super().__init__(owner, inventory_type)
        self._objects = weakref.WeakSet()

    def register_object(self, obj):
        self._objects.add(obj)

    def _added(self, *args, **kwargs):
        super()._added(*args, **kwargs)
        self.update_inventory_count()

    def _removed(self, *args, **kwargs):
        super()._removed(*args, **kwargs)
        self.update_inventory_count()

    @componentmethod
    def update_inventory_count(self):
        for obj in self.owning_objects_gen():
            obj.inventory_component._on_update()

    def _get_inventory_id(self):
        return int(self._inventory_type)

    def _get_inventory_ui_type(self):
        return UI_pb2.InventoryItemUpdate.TYPE_SHARED

    @property
    def has_owning_object(self):
        for _ in self.owning_objects_gen():
            pass
        return False

    def owning_objects_gen(self):
        for obj in self._objects:
            if obj.is_in_inventory():
                pass
            yield obj

    def set_owner_object_state(self, state_value):
        for obj in self.owning_objects_gen():
            while obj.state_component is not None:
                obj.set_state(state_value.state, state_value)

    @componentmethod
    def get_inventory_access_constraint(self, sim, is_put, carry_target, use_owner_as_target_for_resolver=False):
        constraint_list = []
        for obj in self.owning_objects_gen():
            constraint_list.append(obj.get_inventory_access_constraint(sim, is_put, carry_target, use_owner_as_target_for_resolver=use_owner_as_target_for_resolver))
        return create_constraint_set(constraint_list, debug_name='Object Inventory Constraints')

    @componentmethod
    def get_inventory_access_animation(self, is_put):
        for obj in self.owning_objects_gen():
            pass

    @componentmethod
    def get_item_update_ops_gen(self):
        for obj in self._inventory_items.values():
            yield (obj, GenericProtocolBufferOp(Operation.INVENTORY_ITEM_UPDATE, self._get_add_to_client_msg(obj)))
        if self.max_overflow_size:
            for obj in self._overflow_items:
                yield (obj, GenericProtocolBufferOp(Operation.INVENTORY_ITEM_UPDATE, self._get_add_to_client_msg(obj)))

class ObjectInventoryObject(ComponentContainer):
    __qualname__ = 'ObjectInventoryObject'

    def __init__(self, inventory_type):
        super().__init__()
        self.add_component(ObjectsInObjectInventoryComponent(self, inventory_type))
        self.id = 1

    @property
    def is_sim(self):
        return False

    def ref(self, callback=None):
        return weakref.ref(self, callback)

class InventoryItemStateTriggerOp(enum.Int):
    __qualname__ = 'InventoryItemStateTriggerOp'
    NONE = 0
    ANY = 1
    ALL = 2

class ItemStateTrigger(HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'ItemStateTrigger'
    FACTORY_TUNABLES = {'description': '\n            When Item inside the inventory has certain state value, it will trigger\n            corresponding state value on the inventory component owner.\n            ', 'item_state_value': ObjectStateValue.TunableReference(description='\n            The state value to monitor on the inventory item.\n            '), 'owner_state_value': ObjectStateValue.TunableReference(description='\n            The state value to apply on owner object if the condition satisfied.\n            '), 'trigger_condition': TunableEnumEntry(description='\n            NONE means if none of the object has the state value, the trigger will happen.\n            ANY means if any of the object has the state value, the trigger will happen.\n            ALL means all the objects inside has to have the value, the trigger will happen.\n            ', tunable_type=InventoryItemStateTriggerOp, default=InventoryItemStateTriggerOp.ANY)}

    def __init__(self, inventory, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._inventory = inventory
        self._total_obj_count = 0
        self._obj_with_state_count = 0

    def on_object_added(self, added_obj):
        state_component = added_obj.state_component
        if state_component is not None and state_component.state_value_active(self.item_state_value):
            pass
        self._check_trigger_state()

    def on_obj_removed(self, removed_obj):
        state_component = removed_obj.state_component
        if state_component is not None and state_component.state_value_active(self.item_state_value):
            pass
        self._check_trigger_state()

    def obj_state_changed(self, old_state, new_state):
        if old_state is self.item_state_value:
            pass
        if new_state is self.item_state_value:
            pass
        self._check_trigger_state()

    def _check_trigger_state(self):
        if self.trigger_condition == InventoryItemStateTriggerOp.NONE:
            if self._obj_with_state_count == 0:
                self._inventory.set_owner_object_state(self.owner_state_value)
        elif self.trigger_condition == InventoryItemStateTriggerOp.ANY:
            if self._obj_with_state_count > 0:
                self._inventory.set_owner_object_state(self.owner_state_value)
        elif self.trigger_condition == InventoryItemStateTriggerOp.ALL and self._obj_with_state_count == self._total_obj_count:
            self._inventory.set_owner_object_state(self.owner_state_value)

    def compare(self, other_state_trigger):
        if self.trigger_condition != other_state_trigger.trigger_condition:
            return False
        if self.item_state_value is not other_state_trigger.item_state_value:
            return False
        if self.owner_state_value is not other_state_trigger.owner_state_value:
            return False
        return True

class ObjectInventoryComponent(GetPutComponentMixin, Component, component_name=types.INVENTORY_COMPONENT):
    __qualname__ = 'ObjectInventoryComponent'
    DEFAULT_OBJECT_INVENTORY_AFFORDANCES = TunableList(TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), description='Affordances for all Object Inventories.')
    DEFAULT_INVENTORY_STATISTIC = Statistic.TunableReference(description='\n        A statistic whose value will be the number of objects\n        in this inventory. It will automatically be added\n        to the object owning this type of component.\n        ')
    TYPE_TO_AFFORDANCES_MAP = TunableMapping(key_type=TunableEnumEntry(InventoryType, InventoryType.UNDEFINED), value_type=TunableList(TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION))), description='Affordances for each type of object inventory.')

    @staticmethod
    def _verify_tunable_callback(cls, tunable_name, source, inventory_type, **kwargs):
        if inventory_type == InventoryType.UNDEFINED or inventory_type == InventoryType.SIM:
            logger.error('Object Inventory Type of {} will not work.', inventory_type, owner='mduke')

    FACTORY_TUNABLES = {'description': '\n            Generate an object inventory for this object\n            ', 'inventory_type': TunableEnumEntry(description='\n            Inventory Type must be set for the object type you add this for.\n            ', tunable_type=InventoryType, default=InventoryType.UNDEFINED), 'visible': Tunable(description='\n            If this inventory is visible to player.', tunable_type=bool, default=True), 'starting_objects': TunableList(description='\n            Objects in this list automatically populate the inventory when its\n            owner is created. Currently, to keep the game object count down, an\n            object will not be added if the object inventory already has\n            another object of the same type.', tunable=TunableReference(manager=services.definition_manager(), description='Objects to populate inventory with.')), 'purchasable_objects': OptionalTunable(description='\n            If this list is enabled, an interaction to buy the purchasable\n            objects through a dialog picker will show on the inventory object.\n            \n            Example usage: a list of books for the bookshelf inventory.\n            ', tunable=TunableTuple(show_description=Tunable(description='\n                    Toggles whether the object description should show in the \n                    purchase picker.\n                    ', tunable_type=bool, default=False), objects=TunableList(description='\n                    A list of object definitions that can be purchased.\n                    ', tunable=TunableReference(manager=services.definition_manager(), description='')))), 'score_contained_objects_for_autonomy': Tunable(description='\n            Whether or not to score for autonomy any objects contained in this object.', tunable_type=bool, default=True), 'item_state_triggers': TunableList(description="\n            The state triggers to modify inventory owner's state value based on\n            inventory items states.\n            ", tunable=ItemStateTrigger.TunableFactory()), 'allow_putdown_in_inventory': Tunable(description="\n            This inventory allows Sims to put objects away into it, such as books\n            or other carryables. Ex: mailbox has an inventory but we don't want\n            Sims putting away items in the inventory.", tunable_type=bool, default=True), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, owner, inventory_type, visible, starting_objects, purchasable_objects, score_contained_objects_for_autonomy, item_state_triggers, allow_putdown_in_inventory, **kwargs):
        super().__init__(owner, **kwargs)
        lot = services.current_zone().lot
        self._inventory = lot.get_object_inventory(inventory_type)
        self._visible = visible
        self._starting_objects = starting_objects
        self.purchasable_objects = purchasable_objects
        if self._inventory is None:
            self._inventory = lot.create_object_inventory(inventory_type)
        self._inventory.register_object(owner)
        self._score_contained_objects_for_autonomy = score_contained_objects_for_autonomy
        for state_trigger in item_state_triggers:
            self._inventory.add_state_trigger(state_trigger(self._inventory))
        self.allow_putdown_in_inventory = allow_putdown_in_inventory

    @property
    def should_score_contained_objects_for_autonomy(self):
        return self._score_contained_objects_for_autonomy

    @property
    def inventory_type(self):
        return self._inventory.inventory_type

    def on_post_bb_fixup(self):
        self._add_starting_objects()

    def _add_starting_objects(self):
        for definition in self._starting_objects:
            if self._inventory.has_item_with_definition(definition):
                pass
            new_object = create_object(definition)
            if not new_object:
                logger.error('Failed to create object {}', definition)
            if not self.player_try_add_object(new_object):
                logger.error('Failed to add object {} to inventory {}', new_object, self)
                new_object.destroy(source=self.owner, cause='Failed to add starting object to inventory.')
            new_object.set_household_owner_id(self.owner.get_household_owner_id())

    def _on_update(self):
        tracker = self.owner.get_tracker(self.DEFAULT_INVENTORY_STATISTIC)
        if tracker is not None:
            tracker.set_value(self.DEFAULT_INVENTORY_STATISTIC, len(self))

    @componentmethod
    def get_inventory_access_constraint(self, sim, is_put, carry_target, use_owner_as_target_for_resolver=False):
        if use_owner_as_target_for_resolver:

            def constraint_resolver(animation_participant, default=None):
                if animation_participant in (AnimationParticipant.SURFACE, PostureSpecVariable.SURFACE_TARGET, AnimationParticipant.TARGET, PostureSpecVariable.INTERACTION_TARGET):
                    return self.owner
                return default

        else:
            constraint_resolver = None
        return self._get_access_constraint(sim, is_put, carry_target, resolver=constraint_resolver)

    @componentmethod
    def get_inventory_access_animation(self, *args, **kwargs):
        return self._get_access_animation(*args, **kwargs)

    @property
    def inventory_value(self):
        return self._inventory.inventory_value

    def __len__(self):
        return self._inventory.__len__()

    def __iter__(self):
        return self._inventory.__iter__()

    def component_interactable_gen(self):
        yield self

    def component_super_affordances_gen(self, **kwargs):
        if self._visible:
            for affordance in self.DEFAULT_OBJECT_INVENTORY_AFFORDANCES:
                yield affordance
            inventory_type = self._inventory._inventory_type
            if inventory_type in self.TYPE_TO_AFFORDANCES_MAP:
                while True:
                    for affordance in self.TYPE_TO_AFFORDANCES_MAP[inventory_type]:
                        yield affordance

    def player_try_add_object(self, *args, **kwargs):
        return self._inventory.player_try_add_object(*args, **kwargs)

    def system_add_object(self, *args, **kwargs):
        return self._inventory.system_add_object(*args, **kwargs)

    def can_add(self, obj):
        return self._inventory.can_add(obj)

    def try_remove_object_by_id(self, *args, **kwargs):
        return self._inventory.try_remove_object_by_id(*args, **kwargs)

    def try_destroy_object(self, obj, force_remove_stack=False, source=None, cause=None):
        if self.try_remove_object_by_id(obj.id, force_remove_stack=force_remove_stack):
            obj.destroy(source=source, cause=cause)
            return True
        return False

    def object_state_update_callback(self, old_state, new_state):
        self._inventory.object_state_update_callback(old_state, new_state)

    def get_object_by_id(self, *args, **kwargs):
        return self._inventory.get_object_by_id(*args, **kwargs)

    def get_count(self, obj_def):
        return self._inventory.get_count(obj_def)

    def owning_objects_gen(self):
        for obj in self._inventory.owning_objects_gen():
            yield obj

    def get_stack_items(self, stack_id):
        return self._inventory.get_stack_items(stack_id)

    def get_items_for_autonomy_gen(self, motives=DEFAULT):
        for obj in list(self._inventory):
            while motives is DEFAULT or obj.commodity_flags & motives:
                yield obj

    def purge_inventory(self):
        self._inventory.purge_inventory()

    def is_object_hidden(self, obj):
        return self._inventory.is_object_hidden(obj)

    @property
    def gameplay_effects(self):
        return self._inventory.gameplay_effects

    def push_inventory_item_update_msg(self, object_updated):
        return self._inventory.push_inventory_item_update_msg(object_updated)

    @componentmethod
    def inventory_view_update(self):
        self._inventory.inventory_view_update()

    def open_ui_panel(self):
        self._inventory._open_ui_panel_for_object(self.owner)

def transfer_entire_inventory(source, recipient):
    if source is None or recipient is None:
        raise ValueError('Attempt to transfer items from {} to {}.'.format(source, recipient))
    lot = services.active_lot()
    if isinstance(source, InventoryType):
        source_inventory = lot.get_object_inventory(source)
    else:
        source_inventory = source.inventory_component
    if source_inventory is None:
        raise ValueError('Failed to find inventory component for source of inventory transfer: {}'.format(source))
    recipient_is_inventory_type = isinstance(recipient, InventoryType)
    if recipient_is_inventory_type:
        recipient_inventory = lot.get_object_inventory(recipient)
    else:
        recipient_inventory = recipient.inventory_component
    if recipient_inventory is None:
        raise ValueError('Attempt to transfer items to an object that has no inventory component: {}'.format(recipient))
    for obj in list(source_inventory):
        if not source_inventory.try_remove_object_by_id(obj.id, force_remove_stack=True):
            logger.warn('Failed to remove object {} from {} inventory', obj, source)
        if recipient_inventory.can_add(obj):
            if not recipient_is_inventory_type and recipient.is_sim:
                obj.update_ownership(recipient)
            recipient_inventory.system_add_object(obj, None if recipient_is_inventory_type else recipient)
        else:
            obj.set_household_owner_id(services.active_household_id())
            build_buy.move_object_to_household_inventory(obj, object_location_type=ObjectOriginLocation.SIM_INVENTORY)

class InventoryTransfer(XevtTriggeredElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'InventoryTransfer'

    @staticmethod
    def _verify_tunable_callback(*args, **kwargs):
        if kwargs['source'] == InventoryType.UNDEFINED:
            logger.error('Inventory Transfer has an undefined inventory type as its source.', owner='bhill')
        if kwargs['recipient'] == InventoryType.UNDEFINED:
            logger.error('Inventory Transfer has an undefined inventory type as its recipient.', owner='bhill')

    FACTORY_TUNABLES = {'description': '\n            Transfer all objects with a specified inventory type from the\n            specified inventory to the inventory of a specified participant.\n            ', 'source': TunableVariant(description='\n            The source of the inventory objects being transferred.\n            ', lot_inventory_type=TunableEnumEntry(description='\n                The inventory from which the objects will be transferred.\n                ', tunable_type=InventoryType, default=InventoryType.UNDEFINED), participant=TunableEnumEntry(description='\n                The participant of the interaction whose inventory objects will\n                be transferred to the specified inventory.\n                ', tunable_type=ParticipantType, default=ParticipantType.Object)), 'recipient': TunableVariant(description='\n            The inventory that will receive the objects being transferred.\n            ', lot_inventory_type=TunableEnumEntry(description='\n                The inventory into which the objects will be transferred.\n                ', tunable_type=InventoryType, default=InventoryType.UNDEFINED), participant=TunableEnumEntry(description='\n                The participant of the interaction who will receive the objects \n                being transferred.\n                ', tunable_type=ParticipantType, default=ParticipantType.Object)), 'verify_tunable_callback': _verify_tunable_callback}

    def _do_behavior(self):
        if isinstance(self.source, ParticipantType):
            source = self.interaction.get_participant(self.source)
        else:
            source = self.source
        if isinstance(self.recipient, ParticipantType):
            recipient = self.interaction.get_participant(self.recipient)
        else:
            recipient = self.recipient
        transfer_entire_inventory(source, recipient)

class InventoryTransferFakePerform(HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'InventoryTransferFakePerform'
    FACTORY_TUNABLES = {'description': '\n            Transfer all objects with a specified inventory type from the\n            specified inventory to the inventory of a specified participant.\n            ', 'source': TunableEnumEntry(description='\n            The inventory from which the objects will be transferred.\n            ', tunable_type=InventoryType, default=InventoryType.UNDEFINED), 'recipient': TunableEnumEntry(description='\n            The inventory into which the objects will be transferred.\n            ', tunable_type=InventoryType, default=InventoryType.UNDEFINED)}

    def _do_behavior(self):
        transfer_entire_inventory(self.source, self.recipient)

class PutObjectInMail(XevtTriggeredElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'PutObjectInMail'
    FACTORY_TUNABLES = {'description': '\n            Create an object of the specified type and place it in the hidden\n            inventory of the active lot so that it will be delivered along with\n            the mail.\n            ', 'object_to_be_mailed': TunableReference(description='\n            A reference to the type of object which will be sent to the hidden\n            inventory to be mailed.\n            ', manager=services.definition_manager())}

    def _do_behavior(self):
        lot = services.active_lot()
        if lot is None:
            return
        lot.create_object_in_hidden_inventory(self.object_to_be_mailed.id)

class DeliverBill(XevtTriggeredElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'DeliverBill'
    FACTORY_TUNABLES = {'description': '\n            Let the bills manager know that a bill has been delivered and\n            trigger appropriate bill-specific functionality.\n            '}

    def _do_behavior(self):
        household = services.owning_household_of_active_lot()
        if household is None:
            return
        if not household.bills_manager.can_deliver_bill:
            return
        household.bills_manager.trigger_bill_notifications_from_delivery()
        services.get_event_manager().process_events_for_household(TestEvent.BillsDelivered, household)

class DeliverBillFakePerform(HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'DeliverBillFakePerform'
    FACTORY_TUNABLES = {'description': '\n            Let the bills manager know that a bill has been delivered and\n            trigger appropriate bill-specific functionality.\n            '}

    def _do_behavior(self):
        household = services.owning_household_of_active_lot()
        if household is None:
            return
        if not household.bills_manager.can_deliver_bill:
            return
        household.bills_manager.trigger_bill_notifications_from_delivery()
        services.get_event_manager().process_events_for_household(TestEvent.BillsDelivered, household)

class DestroySpecifiedObjectsFromTargetInventory(XevtTriggeredElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'DestroySpecifiedObjectsFromTargetInventory'
    FACTORY_TUNABLES = {'description': '\n            Destroy every object in the target inventory that passes the tuned\n            tests.\n            ', 'inventory_owner': TunableEnumEntry(description='\n            The participant of the interaction whose inventory will be checked\n            for objects to destroy.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'object_tests': TunableTestSet(description='\n            A list of tests to apply to all objects in the target inventory.\n            Every object that passes these tests will be destroyed.\n            ')}

    def _do_behavior(self):
        participant = self.interaction.get_participant(self.inventory_owner)
        inventory = participant.inventory_component
        if inventory is None:
            logger.error('Participant {} does not have an inventory to check for objects to destroy.', participant, owner='tastle')
            return
        objects_to_destroy = set()
        for obj in inventory:
            single_object_resolver = event_testing.resolver.SingleObjectResolver(obj)
            if not self.object_tests.run_tests(single_object_resolver):
                pass
            objects_to_destroy.add(obj)
        for obj in objects_to_destroy:
            while not inventory.try_destroy_object(obj, force_remove_stack=True, source=inventory, cause='Destroying specified objects from target inventory extra.'):
                logger.error('Error trying to destroy object {}.', obj, owner='tastle')
        objects_to_destroy.clear()

