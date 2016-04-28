from _weakrefset import WeakSet
from protocolbuffers import FileSerialization_pb2 as file_serialization, GameplaySaveData_pb2 as gameplay_serialization
import collections
from indexed_manager import IndexedManager, CallbackTypes
from objects.components.inventory_enums import InventoryType, StackScheme
from objects.components.inventory_item import ItemLocation
from objects.object_enums import ResetReason
from objects.system import get_child_objects
from sims4.callback_utils import CallableList
from sims4.tuning.tunable import Tunable, TunableTuple, TunableSet, TunableEnumWithFilter
from sims4.utils import classproperty
from sims4.zone_utils import get_zone_id
from singletons import DEFAULT
import build_buy
import distributor.system
import objects.persistence_groups
import services
import sims4.log
import tag
logger = sims4.log.Logger('Object Manager')

class CraftingObjectCache:
    __qualname__ = 'CraftingObjectCache'

    def __init__(self):
        self._user_directed_cache = {}
        self._autonomy_cache = {}

    def add_type(self, crafting_type, user_directed=True, autonomy=True):
        if user_directed:
            self._add_type_to_cache(crafting_type, self._user_directed_cache)
        if autonomy:
            self._add_type_to_cache(crafting_type, self._autonomy_cache)

    def _add_type_to_cache(self, crafting_type, cache):
        if crafting_type in cache:
            cache[crafting_type] += 1
        else:
            cache[crafting_type] = 1

    def remove_type(self, crafting_type, user_directed=True, autonomy=True):
        if user_directed:
            self._remove_type_from_cache(crafting_type, self._user_directed_cache)
        if autonomy:
            self._remove_type_from_cache(crafting_type, self._autonomy_cache)

    def _remove_type_from_cache(self, crafting_type, cache):
        ref_count = cache.get(crafting_type)
        if ref_count is not None:
            if ref_count <= 0:
                logger.error("Crafting cache has a ref count of {} for {}, which shoudn't be possible", ref_count, crafting_type, owner='rez')
                del cache[crafting_type]
            elif ref_count == 1:
                del cache[crafting_type]
            else:
                cache[crafting_type] -= 1
        else:
            logger.error('Attempting to remove object {} from cache that has never been added to it', crafting_type, owner='rez')

    def get_ref_count(self, crafting_type, from_autonomy=False):
        if from_autonomy:
            return self._autonomy_cache.get(crafting_type, 0)
        return self._user_directed_cache.get(crafting_type, 0)

    def __iter__(self):
        return self._user_directed_cache.items().__iter__()

    def clear(self):
        self._user_directed_cache.clear()
        self._autonomy_cache.clear()

class DistributableObjectManager(IndexedManager):
    __qualname__ = 'DistributableObjectManager'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.zone_id = get_zone_id()

    def setup(self, **kwargs):
        super().setup()
        services.get_zone(self.zone_id).client_object_managers.add(self)

    def call_on_add(self, obj):
        if self.auto_manage_distributor:
            distributor.system.Distributor.instance().add_object(obj)
        super().call_on_add(obj)

    @property
    def auto_manage_distributor(self):
        return True

    def remove_from_client(self, obj):
        if obj.id not in self:
            logger.error('Object was not found in object manager: {}', obj)
            return
        if not obj.visible_to_client:
            return
        child_objects = get_child_objects(obj)
        for child_object in child_objects:
            child_object.remove_from_client()
        if self.auto_manage_distributor:
            distributor.system.Distributor.instance().remove_object(obj)

    def remove(self, obj):
        if self.is_removing_object(obj):
            return
        if obj.id not in self:
            logger.warn('Object was not found in object manager: {}', obj)
            return
        if self.supports_parenting:
            obj.remove_reference_from_parent()
        child_objects = get_child_objects(obj)
        for child_object in child_objects:
            child_object.destroy(source=obj, cause='Removing parent from object manager.')
        if obj.visible_to_client:
            self.remove_from_client(obj)
        super().remove(obj)

    @classproperty
    def supports_parenting(self):
        return False

    def on_location_changed(self, obj):
        pass

class PartyManager(IndexedManager):
    __qualname__ = 'PartyManager'

class SocialGroupManager(DistributableObjectManager):
    __qualname__ = 'SocialGroupManager'

class PropManager(DistributableObjectManager):
    __qualname__ = 'PropManager'

class InventoryManager(DistributableObjectManager):
    __qualname__ = 'InventoryManager'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._variant_group_stack_id_map = {}
        self._definition_stack_id_map = {}
        self._last_stack_id = 0

    def on_client_connect(self, client):
        all_objects = list(self._objects.values())
        for game_object in all_objects:
            game_object.on_client_connect(client)

    def move_to_world(self, obj, object_manager):
        if hasattr(obj, 'on_removed_from_inventory'):
            obj.on_removed_from_inventory()
        del self._objects[obj.id]
        obj.manager = object_manager
        object_manager._objects[obj.id] = obj

    def add(self, obj, *args, **kwargs):
        super().add(obj, *args, **kwargs)
        if obj.objectage_component is None:
            services.current_zone().increment_object_count(obj)
            household_manager = services.household_manager()
            if household_manager is not None:
                household_manager.increment_household_object_count(obj.get_household_owner_id())

    def remove(self, obj, *args, **kwargs):
        object_id = obj.id
        inventory = obj.get_inventory()
        if inventory is not None:
            inventory.try_remove_object_by_id(object_id, on_manager_remove=True)
        if obj.objectage_component is None:
            current_zone = services.current_zone()
            current_zone.decrement_object_count(obj)
            current_zone.household_manager.decrement_household_object_count(obj.get_household_owner_id())
        super().remove(obj, *args, **kwargs)

    def get_stack_id(self, obj, stack_scheme):
        if stack_scheme == StackScheme.NONE:
            return self._get_new_stack_id()
        if stack_scheme == StackScheme.VARIANT_GROUP:
            variant_group_id = build_buy.get_variant_group_id(obj.definition.id)
            if variant_group_id not in self._variant_group_stack_id_map:
                self._variant_group_stack_id_map[variant_group_id] = self._get_new_stack_id()
            return self._variant_group_stack_id_map[variant_group_id]
        if stack_scheme == StackScheme.DEFINITION:
            definition_id = obj.definition.id
            if definition_id not in self._definition_stack_id_map:
                self._definition_stack_id_map[definition_id] = self._get_new_stack_id()
            return self._definition_stack_id_map[definition_id]
        logger.warn("Can't get stack id for unrecognized stack scheme {}", stack_scheme, owner='tingyul')
        return 0

    def _get_new_stack_id(self):
        if self._last_stack_id > sims4.math.MAX_UINT64:
            logger.warn('stack id reached MAX_UINT64. Rolling back to 0, which might cause stacking errors..', owner='tingyul')
            self._last_stack_id = 0
        return self._last_stack_id

    @classproperty
    def supports_parenting(self):
        return True

BED_PREFIX_FILTER = ('buycat', 'buycatee', 'buycatss', 'func')

class ObjectManager(DistributableObjectManager):
    __qualname__ = 'ObjectManager'
    FIREMETER_DISPOSABLE_OBJECT_CAP = Tunable(int, 5, description='Number of disposable objects a lot can have at any given moment.')
    BED_TAGS = TunableTuple(description='\n        Tags to check on an object to determine what type of bed an object is.\n        ', beds=TunableSet(description='\n            Tags that consider an object as a bed other than double beds.\n            ', tunable=TunableEnumWithFilter(tunable_type=tag.Tag, default=tag.Tag.INVALID, filter_prefixes=BED_PREFIX_FILTER)), double_beds=TunableSet(description='\n            Tags that consider an object as a double bed\n            ', tunable=TunableEnumWithFilter(tunable_type=tag.Tag, default=tag.Tag.INVALID, filter_prefixes=BED_PREFIX_FILTER)), kid_beds=TunableSet(description='\n            Tags that consider an object as a kid bed\n            ', tunable=TunableEnumWithFilter(tunable_type=tag.Tag, default=tag.Tag.INVALID, filter_prefixes=BED_PREFIX_FILTER)), other_sleeping_spots=TunableSet(description='\n            Tags that considered sleeping spots.\n            ', tunable=TunableEnumWithFilter(tunable_type=tag.Tag, default=tag.Tag.INVALID, filter_prefixes=BED_PREFIX_FILTER)))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._crafting_cache = CraftingObjectCache()
        self._sim_spawn_conditions = collections.defaultdict(set)
        self._client_connect_callbacks = CallableList()
        self._portal_cache = WeakSet()
        self._portal_added_callbacks = CallableList()
        self._portal_removed_callbacks = CallableList()
        self._front_door_candidates_changed_callback = CallableList()
        self._all_bed_tags = self.BED_TAGS.beds | self.BED_TAGS.double_beds | self.BED_TAGS.kid_beds | self.BED_TAGS.other_sleeping_spots

    @property
    def crafting_cache(self):
        return self._crafting_cache

    def portal_cache_gen(self):
        yield self._portal_cache

    def on_client_connect(self, client):
        all_objects = list(self._objects.values())
        for game_object in all_objects:
            game_object.on_client_connect(client)

    def move_to_inventory(self, obj, inventory_manager):
        del self._objects[obj.id]
        obj.manager = inventory_manager
        inventory_manager._objects[obj.id] = obj
        if hasattr(obj, 'on_added_to_inventory'):
            obj.on_added_to_inventory()

    def add(self, obj, *args, **kwargs):
        super().add(obj, *args, **kwargs)
        if obj.objectage_component is None:
            current_zone = services.current_zone()
            current_zone.increment_object_count(obj)
            current_zone.household_manager.increment_household_object_count(obj.get_household_owner_id())

    def remove(self, obj, *args, **kwargs):
        super().remove(obj, *args, **kwargs)
        if obj.objectage_component is None:
            current_zone = services.current_zone()
            current_zone.decrement_object_count(obj)
            current_zone.household_manager.decrement_household_object_count(obj.get_household_owner_id())

    def _should_save_object_on_lot(self, obj):
        parent = obj.parent
        if parent is not None and parent.is_sim:
            if obj.can_go_in_inventory_type(InventoryType.SIM):
                return False
        return True

    def pre_save(self):
        all_objects = list(self._objects.values())
        lot = services.current_zone().lot
        for (_, inventory) in lot.get_all_object_inventories_gen():
            for game_object in inventory:
                all_objects.append(game_object)
        for game_object in all_objects:
            game_object.update_all_commodities()

    def save(self, object_list=None, zone_data=None, open_street_data=None, **kwargs):
        if object_list is None:
            return
        open_street_objects = file_serialization.ObjectList()
        total_beds = 0
        double_bed_exist = False
        kid_bed_exist = False
        alternative_sleeping_spots = 0
        for game_object in self._objects.values():
            while self._should_save_object_on_lot(game_object):
                if game_object.persistence_group == objects.persistence_groups.PersistenceGroups.OBJECT:
                    save_result = game_object.save_object(object_list.objects, ItemLocation.ON_LOT, 0)
                else:
                    if game_object.item_location == ItemLocation.ON_LOT or game_object.item_location == ItemLocation.INVALID_LOCATION:
                        item_location = ItemLocation.FROM_OPEN_STREET
                    else:
                        item_location = game_object.item_location
                    save_result = game_object.save_object(open_street_objects.objects, item_location, 0)
                if not save_result:
                    pass
                if zone_data is None:
                    pass
                def_build_buy_tags = game_object.definition.build_buy_tags
                if not def_build_buy_tags & self._all_bed_tags:
                    pass
                if def_build_buy_tags & self.BED_TAGS.double_beds:
                    double_bed_exist = True
                    total_beds += 1
                elif def_build_buy_tags & self.BED_TAGS.kid_beds:
                    total_beds += 1
                    kid_bed_exist = True
                elif def_build_buy_tags & self.BED_TAGS.other_sleeping_spots:
                    alternative_sleeping_spots += 1
                elif def_build_buy_tags & self.BED_TAGS.beds:
                    total_beds += 1
        if open_street_data is not None:
            open_street_data.objects = open_street_objects
        if zone_data is not None:
            bed_info_data = gameplay_serialization.ZoneBedInfoData()
            bed_info_data.num_beds = total_beds
            bed_info_data.double_bed_exist = double_bed_exist
            bed_info_data.kid_bed_exist = kid_bed_exist
            bed_info_data.alternative_sleeping_spots = alternative_sleeping_spots
            zone_data.gameplay_zone_data.bed_info_data = bed_info_data
        lot = services.current_zone().lot
        for (inventory_type, inventory) in lot.get_all_object_inventories_gen():
            for game_object in inventory:
                game_object.save_object(object_list.objects, ItemLocation.OBJECT_INVENTORY, inventory_type)

    def valid_objects(self):
        return [obj for obj in self._objects.values() if not obj._hidden_flags]

    def get_objects_of_type_gen(self, *definitions):
        for obj in self._objects.values():
            while any(obj.definition is d for d in definitions):
                yield obj

    def get_objects_with_tag_gen(self, tag):
        for obj in self._objects.values():
            while build_buy.get_object_has_tag(obj.definition.id, tag):
                yield obj

    def add_sim_spawn_condition(self, sim_id, callback):
        for sim in services.sim_info_manager().instanced_sims_gen():
            while sim.id == sim_id:
                logger.error('Sim {} is already in the world, cannot add the spawn condition', sim)
                return
        self._sim_spawn_conditions[sim_id].add(callback)

    def remove_sim_spawn_condition(self, sim_id, callback):
        if callback not in self._sim_spawn_conditions.get(sim_id, ()):
            logger.error('Trying to remove sim spawn condition with invalid id-callback pair ({}-{}).', sim_id, callback)
            return
        self._sim_spawn_conditions[sim_id].remove(callback)

    def trigger_sim_spawn_condition(self, sim_id):
        if sim_id in self._sim_spawn_conditions:
            for callback in self._sim_spawn_conditions[sim_id]:
                callback()
            del self._sim_spawn_conditions[sim_id]

    def register_portal_added_callback(self, callback):
        if callback not in self._portal_added_callbacks:
            self._portal_added_callbacks.append(callback)

    def unregister_portal_added_callback(self, callback):
        if callback in self._portal_added_callbacks:
            self._portal_added_callbacks.remove(callback)

    def register_portal_removed_callback(self, callback):
        if callback not in self._portal_removed_callbacks:
            self._portal_removed_callbacks.append(callback)

    def unregister_portal_removed_callback(self, callback):
        if callback in self._portal_removed_callbacks:
            self._portal_removed_callbacks.remove(callback)

    def add_portal_to_cache(self, portal):
        self._portal_cache.add(portal)
        self._portal_added_callbacks(portal)

    def remove_portal_from_cache(self, portal):
        self._portal_cache.remove(portal)
        self._portal_removed_callbacks(portal)

    def register_front_door_candidates_changed_callback(self, callback):
        if callback not in self._front_door_candidates_changed_callback:
            self._front_door_candidates_changed_callback.append(callback)

    def unregister_front_door_candidates_changed_callback(self, callback):
        if callback in self._front_door_candidates_changed_callback:
            self._front_door_candidates_changed_callback.remove(callback)

    def on_front_door_candidates_changed(self):
        self._front_door_candidates_changed_callback()

    def advertising_objects_gen(self, motives:set=DEFAULT):
        if not motives:
            return
        if motives is DEFAULT:
            for obj in self.valid_objects():
                while obj.commodity_flags:
                    yield obj
            return
        for obj in self.valid_objects():
            while obj.commodity_flags & motives:
                yield obj

    def get_all_objects_with_component_gen(self, component):
        if component is None:
            return
        for obj in self.valid_objects():
            if obj.has_component(component.instance_attr):
                yield obj
            else:
                while obj.has_component(component.class_attr):
                    yield obj

    def on_location_changed(self, obj):
        self._registered_callbacks[CallbackTypes.ON_OBJECT_LOCATION_CHANGED](obj)

    @classproperty
    def supports_parenting(self):
        return True

