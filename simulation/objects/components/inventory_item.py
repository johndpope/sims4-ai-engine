from protocolbuffers import SimObjectAttributes_pb2 as protocols
from event_testing.test_events import TestEvent
from objects.components import Component, types, componentmethod_with_fallback
from objects.components.inventory_enums import InventoryType, InventoryTypeTuning, StackScheme, UNIQUE_OBJECT_INVENTORY_TYPES
from sims4.tuning.tunable import TunableEnumEntry, TunableList, TunableReference, Tunable, AutoFactoryInit, HasTunableFactory, TunableTuple, OptionalTunable
import enum
import services
import sims4.log
logger = sims4.log.Logger(types.INVENTORY_ITEM_COMPONENT.class_attr)

class ItemLocation(enum.Int, export=False):
    __qualname__ = 'ItemLocation'
    INVALID_LOCATION = 0
    ON_LOT = 1
    SIM_INVENTORY = 2
    HOUSEHOLD_INVENTORY = 3
    OBJECT_INVENTORY = 4
    FROM_WORLD_FILE = 5
    FROM_OPEN_STREET = 6

class InventoryItemComponent(Component, HasTunableFactory, AutoFactoryInit, component_name=types.INVENTORY_ITEM_COMPONENT, persistence_key=protocols.PersistenceMaster.PersistableData.InventoryItemComponent):
    __qualname__ = 'InventoryItemComponent'
    DEFAULT_ADD_TO_WORLD_AFFORDANCES = TunableList(description="\n        A list of default affordances to add objects in a Sim's inventory to\n        the world.\n        ", tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)))
    DEFAULT_ADD_TO_SIM_INVENTORY_AFFORDANCES = TunableList(description="\n        A list of default affordances to add objects to a Sim's inventory.\n        ", tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)))
    DEFAULT_NO_CARRY_ADD_TO_WORLD_AFFORDANCES = TunableList(description="\n        A list of default affordances to add objects in a Sim's inventory that\n        skip the carry pose to the world.\n        ", tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)))
    DEFAULT_NO_CARRY_ADD_TO_SIM_INVENTORY_AFFORDANCES = TunableList(description="\n        A list of default affordances to add objects that skip the carry pose\n        to a Sim's inventory.\n        ", tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)))
    PUT_AWAY_AFFORDANCE = TunableReference(description='\n        An affordance for putting an object away in an inventory.\n        ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION))
    STACK_SORT_ORDER_STATES = TunableList(description='\n        A list of states that dictate the order of an inventory stack. States\n        lower down in this list will cause the object to be further down in\n        the stack.\n        ', tunable=TunableTuple(description='\n            States to consider.\n            ', state=TunableReference(description='\n                State to sort on.\n                ', manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions='ObjectState'), is_value_order_inverted=Tunable(description='\n                Normally, higher state value is better. For example, an\n                IngredientQuality value of 0 is the worst and 10 is the best.\n\n                However, there are some state values where lower is better,\n                e.g. burnt state is tied to the burnt commodity where 0 is\n                unburnt and 100 is completely burnt. This option should be set\n                for these states.\n                ', tunable_type=bool, default=False)))

    @staticmethod
    def _verify_tunable_callback(cls, tunable_name, source, valid_inventory_types, skip_carry_pose, inventory_only, **kwargs):
        if InventoryType.UNDEFINED in valid_inventory_types:
            logger.error('Inventory Item is not valid for any inventories.  Please remove the component or update your tuning.', owner='mduke')
        if skip_carry_pose:
            for inv_type in valid_inventory_types:
                inv_data = InventoryTypeTuning.INVENTORY_TYPE_DATA.get(inv_type)
                while inv_data is not None and not inv_data.skip_carry_pose_allowed:
                    logger.error('You cannot tune your item to skip carry\n                    pose unless it is only valid for the sim, mailbox, and/or\n                    hidden inventories.  Any other inventory type will not\n                    properly support this option. -Mike Duke')

    FACTORY_TUNABLES = {'description': '\n            An object with this component can be placed in inventories.\n            ', 'valid_inventory_types': TunableList(description='\n            A list of Inventory Types this object can go into.\n            ', tunable=TunableEnumEntry(description='\n                Any inventory type tuned here is one in which the owner of this\n                component can be placed into.\n                ', tunable_type=InventoryType, default=InventoryType.UNDEFINED)), 'skip_carry_pose': Tunable(description='\n            If Checked, this object will not use the normal pick up or put down\n            SI which goes through the carry pose.  It will instead use a swipe\n            pick up which does a radial route and swipe.  Put down will run a\n            FGL and do a swipe then fade in the object in the world. You can\n            only use this for an object that is only valid for the sim, hidden\n            and/or mailbox inventory.  It will not work with other inventory\n            types.', tunable_type=bool, default=False), 'inventory_only': Tunable(description='\n            Denote the owner of this component as an "Inventory Only" object.\n            These objects are not meant to be placed in world, and will not\n            generate any of the default interactions normally generated for\n            inventory objects.\n            ', tunable_type=bool, default=False), 'visible': Tunable(description="\n            Whether the object is visible in the Sim's Inventory or not.\n            Objects that are invisible won't show up but can still be tested\n            for.\n            ", tunable_type=bool, default=True), 'put_away_affordance': OptionalTunable(description='\n            Whether to use the default put away interaction or an overriding\n            one. The default affordance is tuned at\n            objects.components.inventory_item -> InventoryItemComponent -> Put\n            Away Affordance.\n            ', tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), disabled_name='DEFAULT', enabled_name='OVERRIDE'), 'stack_scheme': TunableEnumEntry(description="\n            How object should stack in an inventory. If you're confused on\n            what definitions and variants are, consult a build/buy designer or\n            producer.\n            \n            NONE: Object will not stack.\n            \n            VARIANT_GROUP: This object will stack with objects with in the same\n            variant group. For example, orange guitars will stack with red\n            guitars.\n\n            DEFINITION: This object will stack with objects with the same\n            definition. For example, orange guitars will stack with other\n            orange guitars but not with red guitars.\n            ", tunable_type=StackScheme, default=StackScheme.VARIANT_GROUP), 'can_place_in_world': Tunable(description='\n            If checked, this object will generate affordances allowing it to be\n            placed in the world. If unchecked, it will not.\n            ', tunable_type=bool, default=True), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_inventory_type = None
        self._last_inventory_owner_ref = None
        self._stack_count = 1
        self._stack_id = None
        self._sort_order = None

    def on_state_changed(self, state, old_value, new_value):
        inventory = self.get_inventory()
        if inventory is not None and not inventory.owner.is_sim:
            inventory.object_state_update_callback(old_value, new_value)
        for state_info in InventoryItemComponent.STACK_SORT_ORDER_STATES:
            while state_info.state is state:
                self._sort_order = None
                if inventory is not None:
                    inventory.push_inventory_item_update_msg(self.owner)
                return

    def post_component_reset(self):
        inventory = self.get_inventory()
        if inventory is not None:
            inventory.push_inventory_item_update_msg(self.owner)

    @property
    def current_inventory_type(self):
        return self._current_inventory_type

    @property
    def _last_inventory_owner(self):
        if self._last_inventory_owner_ref is not None:
            return self._last_inventory_owner_ref()

    @_last_inventory_owner.setter
    def _last_inventory_owner(self, value):
        if value is None:
            self._last_inventory_owner_ref = None
        else:
            self._last_inventory_owner_ref = value.ref()

    @componentmethod_with_fallback(lambda : False)
    def is_in_inventory(self):
        return self._current_inventory_type is not None

    @componentmethod_with_fallback(lambda : 1)
    def stack_count(self):
        return self._stack_count

    @componentmethod_with_fallback(lambda count: None)
    def set_stack_count(self, count):
        self._stack_count = count

    @componentmethod_with_fallback(lambda num: None)
    def update_stack_count(self, num):
        pass

    @componentmethod_with_fallback(lambda sim=None: False)
    def is_in_sim_inventory(self, sim=None):
        if sim is not None:
            inventory = self.get_inventory()
            if inventory is not None:
                return inventory.owner is sim
            return False
        return self._current_inventory_type == InventoryType.SIM

    def on_added_to_inventory(self):
        inventory = self.get_inventory()
        if inventory is not None and inventory.owner.is_sim:
            services.get_event_manager().process_event(TestEvent.OnInventoryChanged, sim_info=inventory.owner.sim_info)

    def on_removed_from_inventory(self):
        owner = self._last_inventory_owner
        if owner.is_sim:
            services.get_event_manager().process_event(TestEvent.OnInventoryChanged, sim_info=owner.sim_info)
        inventory = owner.inventory_component
        if owner is not None and inventory is not None and inventory.inventory_type not in (InventoryType.MAILBOX, InventoryType.HIDDEN):
            self.owner.new_in_inventory = False

    @componentmethod_with_fallback(lambda : None)
    def get_inventory(self):
        if self.is_in_inventory():
            if self._last_inventory_owner is not None:
                return self._last_inventory_owner.inventory_component
            if self.is_in_sim_inventory():
                logger.error('Object exists but owning Sim does not!  This means we leaked the inventory item when the Sim was deleted.', owner='jpollak/mduke')
            return services.current_zone().lot.get_object_inventory(self._current_inventory_type)

    @componentmethod_with_fallback(lambda inventory_type: False)
    def can_go_in_inventory_type(self, inventory_type):
        if inventory_type == InventoryType.HIDDEN:
            if InventoryType.MAILBOX not in self.valid_inventory_types:
                logger.warn('Object can go in the hidden inventory, but not the mailbox: {}', self)
            return True
        return inventory_type in self.valid_inventory_types

    def get_stack_id(self):
        if self._stack_id is None:
            self._stack_id = services.inventory_manager().get_stack_id(self.owner, self.stack_scheme)
        return self._stack_id

    @componentmethod_with_fallback(lambda *args, **kwargs: 0)
    def get_stack_sort_order(self, inspect_only=False):
        if not inspect_only and self._sort_order is None:
            self._recalculate_sort_order()
        if self._sort_order is not None:
            return self._sort_order
        return 0

    def _recalculate_sort_order(self):
        sort_order = 0
        multiplier = 1
        for state_info in InventoryItemComponent.STACK_SORT_ORDER_STATES:
            state = state_info.state
            if state is None:
                pass
            invert_order = state_info.is_value_order_inverted
            num_values = len(state.values)
            if self.owner.has_state(state):
                state_value = self.owner.get_state(state)
                value = state.values.index(state_value)
                if not invert_order:
                    value = num_values - value - 1
                sort_order += multiplier*value
            multiplier *= num_values
        self._sort_order = sort_order

    def component_interactable_gen(self):
        if not self.inventory_only:
            yield self

    def component_super_affordances_gen(self, **kwargs):
        if self.owner.get_users():
            return
        if not self.inventory_only:
            lot = None
            obj_inventory_found = False
            for valid_type in self.valid_inventory_types:
                if valid_type == InventoryType.SIM:
                    if self.skip_carry_pose:
                        yield self.DEFAULT_NO_CARRY_ADD_TO_SIM_INVENTORY_AFFORDANCES
                        if self.can_place_in_world:
                            yield self.DEFAULT_NO_CARRY_ADD_TO_WORLD_AFFORDANCES
                            yield self.DEFAULT_ADD_TO_SIM_INVENTORY_AFFORDANCES
                            if self.can_place_in_world:
                                yield self.DEFAULT_ADD_TO_WORLD_AFFORDANCES
                                while not obj_inventory_found:
                                    if self.skip_carry_pose:
                                        pass
                                    if not lot:
                                        lot = services.current_zone().lot
                                    inventory = lot.get_object_inventory(valid_type)
                                    if inventory is not None and inventory.has_owning_object:
                                        inv_data = InventoryTypeTuning.INVENTORY_TYPE_DATA.get(valid_type)
                                        if inv_data is None or inv_data.put_away_allowed:
                                            obj_inventory_found = True
                                            if self.put_away_affordance is None:
                                                yield self.PUT_AWAY_AFFORDANCE
                                            else:
                                                yield self.put_away_affordance
                        else:
                            while not obj_inventory_found:
                                if self.skip_carry_pose:
                                    pass
                                if not lot:
                                    lot = services.current_zone().lot
                                inventory = lot.get_object_inventory(valid_type)
                                if inventory is not None and inventory.has_owning_object:
                                    inv_data = InventoryTypeTuning.INVENTORY_TYPE_DATA.get(valid_type)
                                    if inv_data is None or inv_data.put_away_allowed:
                                        obj_inventory_found = True
                                        if self.put_away_affordance is None:
                                            yield self.PUT_AWAY_AFFORDANCE
                                        else:
                                            yield self.put_away_affordance
                    else:
                        yield self.DEFAULT_ADD_TO_SIM_INVENTORY_AFFORDANCES
                        if self.can_place_in_world:
                            yield self.DEFAULT_ADD_TO_WORLD_AFFORDANCES
                            while not obj_inventory_found:
                                if self.skip_carry_pose:
                                    pass
                                if not lot:
                                    lot = services.current_zone().lot
                                inventory = lot.get_object_inventory(valid_type)
                                if inventory is not None and inventory.has_owning_object:
                                    inv_data = InventoryTypeTuning.INVENTORY_TYPE_DATA.get(valid_type)
                                    if inv_data is None or inv_data.put_away_allowed:
                                        obj_inventory_found = True
                                        if self.put_away_affordance is None:
                                            yield self.PUT_AWAY_AFFORDANCE
                                        else:
                                            yield self.put_away_affordance
                else:
                    while not obj_inventory_found:
                        if self.skip_carry_pose:
                            pass
                        if not lot:
                            lot = services.current_zone().lot
                        inventory = lot.get_object_inventory(valid_type)
                        if inventory is not None and inventory.has_owning_object:
                            inv_data = InventoryTypeTuning.INVENTORY_TYPE_DATA.get(valid_type)
                            if inv_data is None or inv_data.put_away_allowed:
                                obj_inventory_found = True
                                if self.put_away_affordance is None:
                                    yield self.PUT_AWAY_AFFORDANCE
                                else:
                                    yield self.put_away_affordance

    def valid_object_inventory_gen(self):
        lot = services.current_zone().lot
        for valid_type in self.valid_inventory_types:
            while valid_type != InventoryType.SIM:
                inventory = lot.get_object_inventory(valid_type)
                if inventory is not None:
                    while True:
                        for obj in inventory.owning_objects_gen():
                            yield obj

    def set_inventory_type(self, inventory_type, owner):
        if inventory_type == self._current_inventory_type and owner == self._last_inventory_owner:
            return
        if self._current_inventory_type != None:
            current_inventory = self.get_inventory()
            self._remove_inventory_effects(current_inventory)
        if inventory_type is None:
            self._current_inventory_type = None
        else:
            if inventory_type == InventoryType.SIM:
                pass
            self._current_inventory_type = inventory_type
            self._last_inventory_owner = owner
            current_inventory = self.get_inventory()
            self._apply_inventory_effects(current_inventory)

    @property
    def previous_inventory(self):
        if self._current_inventory_type is not None:
            return
        if self._last_inventory_owner is not None:
            return self._last_inventory_owner.inventory_component

    def clear_previous_inventory(self):
        self._last_inventory_owner = None

    def save(self, persistence_master_message):
        persistable_data = protocols.PersistenceMaster.PersistableData()
        persistable_data.type = protocols.PersistenceMaster.PersistableData.InventoryItemComponent
        inventory_item_save = persistable_data.Extensions[protocols.PersistableInventoryItemComponent.persistable_data]
        inventory_item_save.inventory_type = self._current_inventory_type if self._current_inventory_type is not None else 0
        inventory_item_save.owner_id = self._last_inventory_owner.id if self._last_inventory_owner is not None else 0
        inventory_item_save.stack_count = self._stack_count
        persistence_master_message.data.extend([persistable_data])

    def load(self, message):
        data = message.Extensions[protocols.PersistableInventoryItemComponent.persistable_data]
        if data.owner_id != 0:
            self._last_inventory_owner = services.object_manager().get(data.owner_id)
        else:
            self._last_inventory_owner = None
        if data.inventory_type == 0:
            return
        if data.inventory_type in InventoryType.values:
            self._current_inventory_type = InventoryType(data.inventory_type)
            if self._current_inventory_type in UNIQUE_OBJECT_INVENTORY_TYPES:
                inv = self._last_inventory_owner.inventory_component if self._last_inventory_owner is not None else None
                logger.assert_log(inv is not None, 'Loading object {} in a unique object inventory but missing inventory owner object.', self.owner, owner='tingyul')
            else:
                lot = services.current_zone().lot
                inv = lot.get_object_inventory(self._current_inventory_type)
                if inv is None:
                    inv = lot.create_object_inventory(self._current_inventory_type)
                inv._insert_item(self.owner, use_overflow=False, call_add=False, object_with_inventory=self._last_inventory_owner, try_find_matching_item=False)
            self._apply_inventory_effects(inv)
        self._stack_count = data.stack_count

    def _apply_inventory_effects(self, inventory):
        effects = inventory.gameplay_effects
        if effects:
            for (stat_type, decay_modifier) in effects.decay_modifiers.items():
                tracker = self.owner.get_tracker(stat_type)
                while tracker is not None:
                    stat = tracker.get_statistic(stat_type)
                    if stat is not None:
                        stat.add_decay_rate_modifier(decay_modifier)

    def _remove_inventory_effects(self, inventory):
        effects = inventory.gameplay_effects
        if effects:
            for (stat_type, decay_modifier) in effects.decay_modifiers.items():
                tracker = self.owner.get_tracker(stat_type)
                while tracker is not None:
                    stat = tracker.get_statistic(stat_type)
                    if stat is not None:
                        stat.remove_decay_rate_modifier(decay_modifier)

