from objects import ALL_HIDDEN_REASONS
from sims4 import zone_utils
from sims4.log import Logger
import enum
import indexed_manager
import protocolbuffers.FileSerialization_pb2 as file_serialization
import pythonutils
import routing
import services
import sims4.utils


class ObjectOriginLocation(enum.Int, export=False):
    __qualname__ = 'ObjectOriginLocation'
    UNKNOWN = 0
    ON_LOT = 1
    SIM_INVENTORY = 2
    HOUSEHOLD_INVENTORY = 3
    OBJECT_INVENTORY = 4
    LANDING_STRIP = 5


class FloorFeatureType(enum.Int):
    __qualname__ = 'FloorFeatureType'
    BURNT = 0


try:
    import _buildbuy
except ImportError:

    class _buildbuy:
        __qualname__ = '_buildbuy'

        @staticmethod
        def get_wall_contours(*_, **__):
            return []

        @staticmethod
        def add_object_to_buildbuy_system(*_, **__):
            pass

        @staticmethod
        def remove_object_from_buildbuy_system(*_, **__):
            pass

        @staticmethod
        def invalidate_object_location(*_, **__):
            pass

        @staticmethod
        def get_stair_count(*_, **__):
            pass

        @staticmethod
        def update_object_attributes(*_, **__):
            pass

        @staticmethod
        def test_location_for_object(*_, **__):
            pass

        @staticmethod
        def has_floor_at_location(*_, **__):
            pass

        @staticmethod
        def is_location_outside(*_, **__):
            return True

        @staticmethod
        def is_location_natural_ground(*_, **__):
            return True

        @staticmethod
        def get_object_slotset(*_, **__):
            pass

        @staticmethod
        def get_object_placement_flags(*_, **__):
            pass

        @staticmethod
        def get_object_buy_category_flags(*_, **__):
            pass

        @staticmethod
        def get_block_id(*_, **__):
            pass

        @staticmethod
        def get_user_in_bb(*_, **__):
            pass

        @staticmethod
        def init_bb_force_exit(*_, **__):
            pass

        @staticmethod
        def bb_force_exit(*_, **__):
            pass

        @staticmethod
        def get_object_decosize(*_, **__):
            pass

        @staticmethod
        def can_create_object(*_, **__):
            pass

        @staticmethod
        def update_zone_object_count(*_, **__):
            pass

        @staticmethod
        def update_household_object_count(*_, **__):
            pass

        @staticmethod
        def get_object_catalog_name(*_, **__):
            pass

        @staticmethod
        def get_object_catalog_description(*_, **__):
            pass

        @staticmethod
        def get_object_is_deletable(*_, **__):
            pass

        @staticmethod
        def get_object_can_depreciate(*_, **__):
            pass

        @staticmethod
        def get_household_inventory_value(*_, **__):
            pass

        @staticmethod
        def get_object_has_tag(*_, **__):
            pass

        @staticmethod
        def get_object_all_tags(*_, **__):
            pass

        @staticmethod
        def get_current_venue(*_, **__):
            pass

        @staticmethod
        def update_gameplay_unlocked_products(*_, **__):
            pass

        @staticmethod
        def has_floor_feature(*_, **__):
            pass

        @staticmethod
        def get_floor_feature(*_, **__):
            pass

        @staticmethod
        def set_floor_feature(*_, **__):
            pass

        @staticmethod
        def begin_update_floor_features(*_, **__):
            pass

        @staticmethod
        def end_update_floor_features(*_, **__):
            pass

        @staticmethod
        def find_floor_feature(*_, **__):
            pass

        @staticmethod
        def list_floor_features(*_, **__):
            pass

        @staticmethod
        def scan_floor_features(*_, **__):
            pass

        @staticmethod
        def get_variant_group_id(*_, **__):
            pass


logger = Logger('BuildBuy')


def remove_object_from_buildbuy_system(obj_id, zone_id, persist=True):
    _buildbuy.remove_object_from_buildbuy_system(obj_id, zone_id, persist)


get_wall_contours = _buildbuy.get_wall_contours
add_object_to_buildbuy_system = _buildbuy.add_object_to_buildbuy_system
invalidate_object_location = _buildbuy.invalidate_object_location
get_stair_count = _buildbuy.get_stair_count
update_object_attributes = _buildbuy.update_object_attributes
test_location_for_object = _buildbuy.test_location_for_object
has_floor_at_location = _buildbuy.has_floor_at_location
is_location_outside = _buildbuy.is_location_outside
is_location_natural_ground = _buildbuy.is_location_natural_ground
get_object_slotset = _buildbuy.get_object_slotset
get_object_placement_flags = _buildbuy.get_object_placement_flags
get_object_buy_category_flags = _buildbuy.get_object_buy_category_flags
get_block_id = _buildbuy.get_block_id
get_user_in_build_buy = _buildbuy.get_user_in_bb
init_build_buy_force_exit = _buildbuy.init_bb_force_exit
build_buy_force_exit = _buildbuy.bb_force_exit
get_object_decosize = _buildbuy.get_object_decosize
can_create_object = _buildbuy.can_create_object
update_zone_object_count = _buildbuy.update_zone_object_count
update_household_object_count = _buildbuy.update_household_object_count
can_create_object = _buildbuy.can_create_object
get_object_catalog_name = _buildbuy.get_object_catalog_name
get_object_catalog_description = _buildbuy.get_object_catalog_description
get_object_is_deletable = _buildbuy.get_object_is_deletable
get_object_can_depreciate = _buildbuy.get_object_can_depreciate
get_household_inventory_value = _buildbuy.get_household_inventory_value
get_object_has_tag = _buildbuy.get_object_has_tag
get_object_all_tags = _buildbuy.get_object_all_tags
get_current_venue = _buildbuy.get_current_venue
update_gameplay_unlocked_products = _buildbuy.update_gameplay_unlocked_products
has_floor_feature = _buildbuy.has_floor_feature
get_floor_feature = _buildbuy.get_floor_feature
set_floor_feature = _buildbuy.set_floor_feature
begin_update_floor_features = _buildbuy.begin_update_floor_features
end_update_floor_features = _buildbuy.end_update_floor_features
find_floor_feature = _buildbuy.find_floor_feature
list_floor_features = _buildbuy.list_floor_features
scan_floor_features = _buildbuy.scan_floor_features
get_variant_group_id = _buildbuy.get_variant_group_id


def move_object_to_household_inventory(
        obj, object_location_type=ObjectOriginLocation.ON_LOT):
    household_id = obj.get_household_owner_id()
    if household_id is None:
        logger.error(
            'This object {} is not owned by any household. Request to move to household inventory will be ignored.',
            obj,
            owner='mduke')
        return
    household = services.household_manager().get(household_id)
    obj.new_in_inventory = True
    obj.remove_reference_from_parent()
    stack_count = obj.stack_count()
    obj.set_stack_count(1)
    _buildbuy.add_object_to_household_inventory(
        obj.id, household_id, zone_utils.get_zone_id(), household.account.id,
        object_location_type, stack_count)


def has_any_objects_in_household_inventory(object_list, household_id):
    household = services.household_manager().get(household_id)
    _buildbuy.has_any_objects_in_household_inventory(object_list, household_id,
                                                     zone_utils.get_zone_id(),
                                                     household.account.id)


def find_objects_in_household_inventory(object_list, household_id):
    household = services.household_manager().get(household_id)
    return _buildbuy.find_objects_in_household_inventory(
        object_list, household_id, zone_utils.get_zone_id(),
        household.account.id)


def object_exists_in_household_inventory(sim_id, household_id):
    return _buildbuy.object_exists_in_household_inventory(
        sim_id, household_id, zone_utils.get_zone_id())


def __reload__(old_module_vars):
    pass


class BuyCategory(enum.IntFlags):
    __qualname__ = 'BuyCategory'
    UNUSED = 1
    APPLIANCES = 2
    ELECTRONICS = 4
    ENTERTAINMENT = 8
    UNUSED_2 = 16
    LIGHTING = 32
    PLUMBING = 64
    DECOR = 128
    KIDS = 256
    STORAGE = 512
    COMFORT = 2048
    SURFACE = 4096
    VEHICLE = 8192
    DEFAULT = 2147483648


class PlacementFlags(enum.IntFlags, export=False):
    __qualname__ = 'PlacementFlags'
    CENTER_ON_WALL = 1
    EDGE_AGAINST_WALL = 2
    ADJUST_HEIGHT_ON_WALL = 4
    CEILING = 8
    IMMOVABLE_BY_USER = 16
    DIAGONAL = 32
    ROOF = 64
    REQUIRES_FENCE = 128
    SHOW_OBJ_IF_WALL_DOWN = 256
    SLOTTED_TO_FENCE = 512
    REQUIRES_SLOT = 1024
    ALLOWED_ON_SLOPE = 2048
    REPEAT_PLACEMENT = 4096
    NON_DELETEABLE = 8192
    NON_INVENTORYABLE = 16384
    REQUIRES_WALL = CENTER_ON_WALL | EDGE_AGAINST_WALL
    WALL_GRAPH_PLACEMENT = REQUIRES_WALL | REQUIRES_FENCE
    SNAP_TO_WALL = REQUIRES_WALL | ADJUST_HEIGHT_ON_WALL


BUILD_BUY_OBJECT_LEAK_DISABLED = 'in build buy'


def get_all_objects_with_flags_gen(objs, buy_category_flags):
    for obj in objs:
        if not get_object_buy_category_flags(
                obj.definition.id) & buy_category_flags:
            pass
        yield obj


@sims4.utils.exception_protected(None)
def c_api_wall_contour_update(zone_id, wall_type):
    with sims4.zone_utils.global_zone_lock(zone_id):
        while wall_type == 0 or wall_type == 2:
            services.get_zone(zone_id).wall_contour_update_callbacks()


@sims4.utils.exception_protected(None)
def c_api_foundation_and_level_height_update(zone_id):
    with sims4.zone_utils.global_zone_lock(zone_id):
        services.get_zone(
            zone_id).foundation_and_level_height_update_callbacks()


@sims4.utils.exception_protected(None)
def c_api_navmesh_update(zone_id):
    pass


@sims4.utils.exception_protected(None)
def c_api_modify_household_funds(amount, household_id, reason, zone_id):
    with sims4.zone_utils.global_zone_lock(zone_id):
        household_manager = services.household_manager()
        household = household_manager.get(household_id)
        if household is None:
            if household_manager.try_add_pending_household_funds(
                    household_id, amount, reason):
                return True
            logger.error(
                'Invalid Household id {} when attempting to modify household funds.',
                household_id)
            return False
        if amount > 0:
            household.funds.add(amount, reason, None, count_as_earnings=False)
        elif amount < 0:
            household.funds.remove(-amount, reason, None)
        return True


@sims4.utils.exception_protected(None)
def c_api_buildbuy_session_begin(zone_id, account_id):
    with sims4.zone_utils.global_zone_lock(zone_id):
        posture_graph_service = services.current_zone().posture_graph_service
        posture_graph_service.on_enter_buildbuy()
        services.current_zone().on_build_buy_enter()
        indexed_manager.IndexedManager.add_gc_collect_disable_reason(
            BUILD_BUY_OBJECT_LEAK_DISABLED)
        resource_keys = []
        current_zone = services.current_zone()
        household = current_zone.get_active_lot_owner_household()
        if household is not None:
            for unlock in household.build_buy_unlocks:
                resource_keys.append(unlock)
        update_gameplay_unlocked_products(resource_keys, zone_id, account_id)
    return True


@sims4.utils.exception_protected(None)
def buildbuy_session_end(zone_id):
    with sims4.zone_utils.global_zone_lock(zone_id):
        for obj in services.object_manager(zone_id).get_all():
            obj.on_buildbuy_exit()
        posture_graph_service = services.current_zone().posture_graph_service
        posture_graph_service.on_exit_buildbuy()
        pythonutils.try_highwater_gc()
        venue_type = get_current_venue(zone_id)
        logger.assert_raise(
            venue_type is not None,
            ' Venue Type is None in buildbuy session end for zone id:{}',
            zone_id,
            owner='sscholl')
        if venue_type is not None:
            venue_tuning = services.venue_manager().get(venue_type)
            services.current_zone(
            ).venue_service.set_venue_and_schedule_events(venue_tuning)
        services.current_zone().on_build_buy_exit()
        from objects.doors.front_door import find_and_set_front_door
        find_and_set_front_door()


@sims4.utils.exception_protected(None)
def c_api_buildbuy_session_end(zone_id,
                               account_id,
                               pending_navmesh_rebuild: bool=False):
    with sims4.zone_utils.global_zone_lock(zone_id):
        zone = services.get_zone(zone_id)
        fence_id = zone.get_current_fence_id_and_increment()
        routing.flush_planner(False)
        routing.add_fence(fence_id)
        indexed_manager.IndexedManager.remove_gc_collect_disable_reason(
            BUILD_BUY_OBJECT_LEAK_DISABLED)
    return True


@sims4.utils.exception_protected(None)
def c_api_buildbuy_get_save_object_data(zone_id, obj_id):
    with sims4.zone_utils.global_zone_lock(zone_id):
        obj = services.get_zone(zone_id).find_object(obj_id)
        if obj is None:
            return
        object_list = file_serialization.ObjectList()
        save_data = obj.save_object(object_list.objects)
    return save_data


@sims4.utils.exception_protected(None)
def c_api_house_inv_obj_added(zone_id, household_id, obj_id, obj_def_id):
    with sims4.zone_utils.global_zone_lock(zone_id):
        household = services.household_manager().get(household_id)
        if household is None:
            logger.error('Invalid Household id: {}', household_id)
            return
        collection_tracker = household.collection_tracker
        collection_tracker.check_add_collection_item(household, obj_id,
                                                     obj_def_id)


@sims4.utils.exception_protected(None)
def c_api_house_inv_obj_removed(zone_id, household_id, obj_id, obj_def_id):
    pass


@sims4.utils.exception_protected(None)
def c_api_set_object_location(zone_id, obj_id, routing_surface, transform):
    with sims4.zone_utils.global_zone_lock(zone_id):
        obj = services.object_manager().get(obj_id)
        if obj is None:
            logger.error('Trying to place an invalid object id: {}',
                         obj_id,
                         owner='camilogarcia')
            return
        obj.move_to(routing_surface=routing_surface, transform=transform)


@sims4.utils.exception_protected(None)
def c_api_on_apply_blueprint_lot(zone_id):
    with sims4.zone_utils.global_zone_lock(zone_id):
        for sim in services.sim_info_manager(
                zone_id).instanced_sims_on_active_lot_gen(
                    allow_hidden_flags=ALL_HIDDEN_REASONS):
            sim.fgl_reset_to_landing_strip()
