from event_testing.resolver import DoubleObjectResolver
from objects.components import Component
from objects.components.inventory_enums import InventoryType
from objects.components.types import LIVE_DRAG_TARGET_COMPONENT
from server.live_drag_tuning import TunableLiveDragTestSet, LiveDragLootActions
from sims4.tuning.tunable import HasTunableFactory, AutoFactoryInit, TunableEnumEntry, TunableList, TunableTuple, Tunable
import sims4.log
logger = sims4.log.Logger('LiveDragTargetComponent', default_owner='rmccord')

class LiveDragTargetComponent(Component, HasTunableFactory, AutoFactoryInit, component_name=LIVE_DRAG_TARGET_COMPONENT):
    __qualname__ = 'LiveDragTargetComponent'
    FACTORY_TUNABLES = {'description': '\n            An object with this component can be a valid drop target for custom Live Drag operations.\n            ', 'drop_tests_and_actions': TunableList(description='\n            A list of TestSet/Loot Action pairs. The first test set that\n            passes will run the appropriate action when an object is\n            dropped onto this one. If no tests pass, then nothing will\n            happen and the system will act as though the user canceled Live\n            Drag. \n            \n            Note: To order the tests, renumber the guids to the left\n            of each entry in the order you want the tests to be run.\n            ', tunable=TunableTuple(description="\n                TestSet/Action pairs. The test sets will run in the order\n                they are loaded in. The first test set that passes will\n                stop testing and execute the associated action. Common\n                actions will be destroy the object, put the dragged object\n                in the dropped object's inventory, modify commodities, etc.\n                \n                Note: To change the order of the tests, renumber the guid\n                to the left, then refresh the page by looking at another\n                tuning file, then coming back to this one.\n                ", drop_type=TunableEnumEntry(description='\n                    Drop/Inventory Type that this object accepts. \n                    \n                    You must also set the Inventory Type on the Inventory Item \n                    Component of the object you expect to be dropped on this \n                    Object.\n                    ', tunable_type=InventoryType, default=InventoryType.UNDEFINED), test_set=TunableLiveDragTestSet(), actions=TunableList(description='\n                    A list of pre-defined loot operations that are run for the dragged/dropped object pairs.\n                    \n                    Typically these loot actions will delete the dragged\n                    object, put it in the inventory of the dropped object,\n                    etc.\n                    ', tunable=LiveDragLootActions.TunableReference()), destroy_live_drag_object=Tunable(description='\n                    If checked, the Live Drag Object dropped on this target\n                    will be destroyed, provided the tests pass.\n                    ', tunable_type=bool, default=False)))}

    def test_inventory_addition(self, live_drag_obj):
        if self.owner.inventory_component is not None:
            live_drag_household_id = live_drag_obj.get_household_owner_id()
            owner_household_id = self.owner.get_household_owner_id() if not self.owner.is_sim else self.owner.household_id
            if live_drag_household_id is not None and owner_household_id != live_drag_household_id:
                return False
            return self.owner.inventory_component.can_add(live_drag_obj)
        return False

    def test_live_drag(self, live_drag_obj):
        inventoryitem_component = live_drag_obj.inventoryitem_component
        if inventoryitem_component is None:
            return (False, None)
        resolver = DoubleObjectResolver(live_drag_obj, self.owner)
        can_add_to_inventory = self.test_inventory_addition(live_drag_obj)
        if not self.drop_tests_and_actions:
            return (can_add_to_inventory, None)
        for entry in self.drop_tests_and_actions:
            while inventoryitem_component.can_go_in_inventory_type(entry.drop_type):
                if entry.test_set.run_tests(resolver):
                    if entry.actions or entry.destroy_live_drag_object or can_add_to_inventory:
                        return (True, entry)
        return (False, None)

    def remove_drag_object_and_add(self, drag_object, remove_entire_stack=False):
        next_object_id = None
        previous_inventory = drag_object.inventoryitem_component.get_inventory()
        if previous_inventory is None:
            added_to_new_inventory = self.owner.inventory_component.player_try_add_object(drag_object, object_with_inventory=self.owner)
            return (added_to_new_inventory, next_object_id)
        stack_id = drag_object.inventoryitem_component.get_stack_id()
        removed = previous_inventory.try_remove_object_by_id(drag_object.id, force_remove_stack=remove_entire_stack)
        stack_items = previous_inventory.get_stack_items(stack_id)
        if stack_items:
            next_object_id = stack_items[0].id
        self._add_drag_object_to_inventory(drag_object, previous_inventory, removed)
        if remove_entire_stack:
            next_object_id = None
            for stack_item in stack_items:
                removed = previous_inventory.try_remove_object_by_id(stack_item.id, force_remove_stack=remove_entire_stack)
                self._add_drag_object_to_inventory(stack_item, previous_inventory, removed)
        return (removed, next_object_id)

    def _add_drag_object_to_inventory(self, item_to_be_added, inventory, removed_from_previous_inventory):
        if inventory is None or removed_from_previous_inventory:
            added_to_new_inventory = self.owner.inventory_component.player_try_add_object(item_to_be_added, object_with_inventory=self.owner)
            if removed_from_previous_inventory and not added_to_new_inventory:
                inventory.system_add_object(item_to_be_added, inventory.owner)

    def drop_live_drag_object(self, live_drag_obj, is_stack):
        success = False
        next_object_id = None
        (test_result, action_entry) = self.test_live_drag(live_drag_obj)
        if test_result:
            if action_entry.actions or action_entry.destroy_live_drag_object:
                (success, next_object_id) = self.apply_live_drag_actions(live_drag_obj, action_entry)
            elif self.owner.inventory_component is not None and live_drag_obj.inventoryitem_component is not None:
                (success, next_object_id) = self.remove_drag_object_and_add(live_drag_obj, remove_entire_stack=is_stack)
        return (success, next_object_id)

    def apply_live_drag_actions(self, live_drag_obj, action_entry=None):
        next_object_id = None
        if action_entry is None:
            (valid, entry) = self.test_live_drag(live_drag_obj)
        else:
            valid = True
            entry = action_entry
        if valid and entry is not None:
            resolver = DoubleObjectResolver(live_drag_obj, self.owner)
            for action in entry.actions:
                action.apply_to_resolver(resolver)
            if entry.destroy_live_drag_object:
                next_object_id = self._destroy_object(live_drag_obj)
        return (valid, next_object_id)

    def can_add(self, obj):
        (valid, _) = self.test_live_drag(obj)
        return valid

    def _destroy_object(self, obj_to_destroy):
        next_object_id = None
        if obj_to_destroy is None:
            return next_object_id
        if obj_to_destroy.is_in_inventory():
            inventory = obj_to_destroy.get_inventory()
            stack_id = obj_to_destroy.inventoryitem_component.get_stack_id()
            inventory.try_remove_object_by_id(obj_to_destroy.id)
            stack_items = inventory.get_stack_items(stack_id)
            next_object_id = stack_items[0].id
        else:
            obj_to_destroy.remove_from_client()
        obj_to_destroy.destroy(source=self, cause='Livedrag destroying object')
        return next_object_id

