from objects.object_enums import ResetReason
from objects.persistence_groups import PersistenceGroups
from sims4.tuning.tunable import Tunable
from sims4.utils import exception_protected
from sims4.zone_utils import global_zone_lock, get_zone_id
import build_buy
import services
import sims4
import sims4.log
LOG_CHANNEL = 'Objects'
logger = sims4.log.Logger(LOG_CHANNEL)
production_logger = sims4.log.ProductionLogger(LOG_CHANNEL)

class SystemTuning:
    __qualname__ = 'SystemTuning'
    build_buy_lockout_duration = Tunable(int, 5, description='Number of seconds an object should stay locked for after it is manipulated in Build/Buy.')

@exception_protected(None)
def c_api_get_object_definition(obj_id, zone_id):
    with global_zone_lock(zone_id):
        obj = find_object(obj_id)
    if obj is None:
        return
    return obj.definition.id

@exception_protected(None)
def c_api_get_object_def_state(obj_id, zone_id):
    with global_zone_lock(zone_id):
        obj = find_object(obj_id)
    if obj is None:
        return
    return obj.state_index

def create_script_object(definition_or_id, consume_exceptions=True, obj_state=0, **kwargs):
    from objects.definition import Definition
    if isinstance(definition_or_id, Definition):
        definition = definition_or_id
    else:
        try:
            definition = services.definition_manager().get(definition_or_id, obj_state=obj_state)
        except:
            logger.exception('Unable to create a script object for definition id: {0}', definition_or_id)
            if consume_exceptions:
                return
            raise
    zone_id = get_zone_id(can_be_none=True)
    if zone_id is not None and not build_buy.can_create_object(zone_id, 0, 1):
        logger.warn('Fire code said this object could not be created. -Mike Duke')
        return
    return definition.instantiate(obj_state=obj_state, **kwargs)

@exception_protected(None)
def c_api_create_object(zone_id, def_id, obj_id, obj_state, loc_type):
    with global_zone_lock(zone_id):
        return create_object(def_id, obj_id=obj_id, obj_state=obj_state, loc_type=loc_type, consume_exceptions=False)

@exception_protected(None)
def c_api_start_delaying_posture_graph_adds():
    pass

@exception_protected(None)
def c_api_stop_delaying_posture_graph_adds():
    pass

def create_object(definition_or_id, obj_id=0, init=None, post_add=None, loc_type=None, **kwargs):
    from objects.components.inventory_item import ItemLocation
    from objects.base_object import BaseObject
    added_to_object_manager = False
    obj = None
    if loc_type is None:
        loc_type = ItemLocation.ON_LOT
    try:
        obj = create_script_object(definition_or_id, **kwargs)
        if obj is None:
            return
        if not isinstance(obj, BaseObject):
            logger.error('Type {0} is not a valid managed object.  It is not a subclass of BaseObject.', type(obj))
            return
        if init is not None:
            init(obj)
        if loc_type == ItemLocation.FROM_WORLD_FILE:
            obj.persistence_group = PersistenceGroups.IN_OPEN_STREET
        obj.item_location = ItemLocation(loc_type) if loc_type is not None else ItemLocation.INVALID_LOCATION
        obj.id = obj_id
        if loc_type == ItemLocation.ON_LOT or loc_type == ItemLocation.FROM_WORLD_FILE or loc_type == ItemLocation.FROM_OPEN_STREET:
            obj.object_manager_for_create.add(obj)
        elif loc_type == ItemLocation.SIM_INVENTORY or loc_type == ItemLocation.OBJECT_INVENTORY:
            services.current_zone().inventory_manager.add(obj)
        else:
            logger.error('Unsupported loc_type passed to create_script_object.  We likely need to update this code path.', owner='mduke')
        added_to_object_manager = True
        if post_add is not None:
            post_add(obj)
        return obj
    finally:
        if not added_to_object_manager and obj is not None:
            import _weakrefutils
            _weakrefutils.clear_weak_refs(obj)

def _get_id_for_obj_or_id(obj_or_id):
    from objects.base_object import BaseObject
    if isinstance(obj_or_id, BaseObject):
        return obj_or_id.id
    return int(obj_or_id)

def _get_obj_for_obj_or_id(obj_or_id):
    from objects.base_object import BaseObject
    if not isinstance(obj_or_id, BaseObject):
        obj = services.object_manager().get(obj_or_id)
        if obj is None:
            logger.error('Could not find the target id {} for a RequiredTargetParam in the object manager.', obj_or_id)
        return obj
    return obj_or_id

@exception_protected(None)
def c_api_destroy_object(zone_id, obj_or_id):
    with global_zone_lock(zone_id):
        obj = _get_obj_for_obj_or_id(obj_or_id)
        return obj.destroy(source=obj, cause='Destruction request from C.')

@exception_protected(None)
def c_api_reset_object(zone_id, obj_or_id):
    with global_zone_lock(zone_id):
        return reset_object(obj_or_id, expected=True, cause='Build/Buy')

def reset_object(obj_or_id, expected, cause=None):
    obj = _get_obj_for_obj_or_id(obj_or_id)
    if obj is not None:
        obj.reset(ResetReason.RESET_EXPECTED if expected else ResetReason.RESET_ON_ERROR, None, cause)
        return True
    return False

def remove_object_from_client(obj_or_id):
    obj = _get_obj_for_obj_or_id(obj_or_id)
    manager = obj.manager
    if obj.id in manager:
        manager.remove_from_client(obj)
        return True
    return False

def create_prop(definition_or_id, is_basic=False, **kwargs):
    from objects.prop_object import BasicPropObject, PropObject
    cls_override = BasicPropObject if is_basic else PropObject
    return create_object(definition_or_id, cls_override=cls_override, **kwargs)

def create_prop_with_footprint(definition_or_id, **kwargs):
    from objects.prop_object import PropObjectWithFootprint
    return create_object(definition_or_id, cls_override=PropObjectWithFootprint, **kwargs)

@exception_protected(None)
def c_api_find_object(obj_id, zone_id):
    with global_zone_lock(zone_id):
        return find_object(obj_id)

def find_object(obj_id, **kwargs):
    return services.current_zone().find_object(obj_id, **kwargs)

@exception_protected(None)
def c_api_get_objects(zone_id):
    with global_zone_lock(zone_id):
        return get_objects()

def get_objects():
    return services.object_manager().get_all()

@exception_protected(None)
def c_api_set_object_state_index(obj_id, state_index, zone_id):
    with global_zone_lock(zone_id):
        obj = find_object(obj_id)
        obj.set_object_def_state_index(state_index)

@exception_protected(False)
def c_api_set_build_buy_lockout(zone_id, obj_or_id, lockout_state, permanent_lock=False):
    with global_zone_lock(zone_id):
        obj = _get_obj_for_obj_or_id(obj_or_id)
        if obj is not None:
            obj.set_build_buy_lockout_state(False, None)
            return True
            if permanent_lock:
                obj.set_build_buy_lockout_state(lockout_state, None)
            else:
                obj.set_build_buy_lockout_state(lockout_state, SystemTuning.build_buy_lockout_duration)
            return True
        return False

@exception_protected(-1)
def c_api_set_parent_object(obj_id, parent_id, transform, joint_name, slot_hash, zone_id):
    with global_zone_lock(zone_id):
        set_parent_object(obj_id, parent_id, transform, joint_name, slot_hash)

def set_parent_object(obj_id, parent_id, transform=None, joint_name=None, slot_hash=0):
    obj = find_object(obj_id)
    parent_obj = find_object(parent_id)
    obj.set_parent(parent_obj, transform, joint_name, slot_hash)

@exception_protected(-1)
def c_api_clear_parent_object(obj_id, transform, zone_id, surface):
    with global_zone_lock(zone_id):
        obj = find_object(obj_id)
        obj.clear_parent(transform, surface)

@exception_protected(None)
def c_api_get_parent(obj_id, zone_id):
    with global_zone_lock(zone_id):
        obj = find_object(obj_id)
    if obj is not None:
        return obj.parent

@exception_protected(0)
def c_api_get_slot_hash(obj_id, zone_id):
    with global_zone_lock(zone_id):
        obj = find_object(obj_id)
    if obj is not None:
        return obj.bone_name_hash
    return 0

@exception_protected(0)
def c_api_set_slot_hash(obj_id, zone_id, slot_hash):
    with global_zone_lock(zone_id):
        obj = find_object(obj_id)
        while obj is not None:
            obj.slot_hash = slot_hash

@exception_protected([])
def c_api_get_child_objects(obj_id, zone_id):
    with global_zone_lock(zone_id):
        return get_child_objects_by_id(obj_id)

def get_child_objects_by_id(obj_id):
    obj = find_object(obj_id)
    if obj is None:
        return []
    return get_child_objects(obj)

def get_child_objects(obj):
    if hasattr(obj, 'children'):
        return list(obj.children)
    return []

