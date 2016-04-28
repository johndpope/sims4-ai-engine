from build_buy import get_object_slotset, test_location_for_object, get_object_buy_category_flags, BuyCategory
from carry import get_carried_objects_gen
from server_commands.argument_helpers import OptionalTargetParam, get_optional_target
from sims4.math import Location, Transform
import objects.system
import routing
import sims4.commands
import sims4.math
import sims4.zone_utils

@sims4.commands.Command('placement.in_navmesh')
def in_navmesh_cmd(obj_id, _connection=None):
    obj = objects.system.find_object(obj_id)
    if obj is not None:
        if obj.is_in_navmesh:
            sims4.commands.output('Object is in NavMesh', _connection)
        else:
            sims4.commands.output('Object is not in NavMesh', _connection)
    else:
        sims4.commands.output('ObjectID is not valid.', _connection)

@sims4.commands.Command('placement.output_slot_set')
def output_slot_set(obj_id, _connection=None):
    obj = objects.system.find_object(obj_id)
    if obj is None:
        sims4.commands.output('Invalid object id', _connection)
        return False
    key = get_object_slotset(obj.definition.id)
    if key is None:
        sims4.commands.output('Object does not have a slot set defined', _connection)
        return False
    sims4.commands.output('Slot set key: {}'.format(key), _connection)
    return True

@sims4.commands.Command('placement.category_flags')
def output_category_flags(obj_id, _connection=None):
    obj = objects.system.find_object(obj_id)
    if obj is None:
        sims4.commands.output('Invalid object id', _connection)
        return False
    buy_category_flags = get_object_buy_category_flags(obj.definition.id)
    sims4.commands.output('\tBuy category flags: {}\n'.format(BuyCategory(buy_category_flags)), _connection)
    return True

@sims4.commands.Command('placement.test_placement')
def test_placement(obj_id, x, y, z, rotation, level, parent_obj_id, parent_slot_hash, _connection=None):
    output = sims4.commands.Output(_connection)
    obj = objects.system.find_object(obj_id)
    if obj is None:
        output('Invalid object id')
        return False
    zone_id = sims4.zone_utils.get_zone_id()
    surface = routing.SurfaceIdentifier(zone_id, level, routing.SURFACETYPE_WORLD)
    position = sims4.math.Vector3(x, y, z)
    orientation = sims4.math.angle_to_yaw_quaternion(rotation)
    parent_obj = objects.system.find_object(parent_obj_id)
    transform = Transform(position, orientation)
    location = Location(transform, surface, parent_obj, parent_slot_hash, parent_slot_hash)
    (result, errors) = test_location_for_object(obj, location=location)
    if result:
        output('Placement is legal')
    else:
        output('Placement is NOT legal')
    if errors:
        for (code, msg) in errors:
            output('  {} ({})'.format(msg, code))
    return result

@sims4.commands.Command('placement.test_current_placement')
def test_current_placement(obj_id, _connection=None):
    output = sims4.commands.Output(_connection)
    obj = objects.system.find_object(obj_id)
    if obj is None:
        output('Invalid object id')
        return False
    args = (obj.id, obj.location.transform.translation.x, obj.location.transform.translation.y, obj.location.transform.translation.z, 0, obj.location.level, obj.parent.id if obj.parent is not None else 0, obj.location.joint_name_or_hash or obj.location.slot_hash)
    output('|placement.test_placement {} {} {} {} {} {} {} {}'.format(*args))
    (result, errors) = test_location_for_object(obj)
    if result:
        output('Placement is legal')
    else:
        output('Placement is NOT legal')
    if errors:
        for (code, msg) in errors:
            output('  {} ({})'.format(msg, code))
    return result

@sims4.commands.Command('placement.has_floor')
def has_floor(x, y, z, level, _connection=None):
    zone_id = sims4.zone_utils.get_zone_id()
    position = sims4.math.Vector3(x, y, z)
    from build_buy import has_floor_at_location
    if has_floor_at_location(zone_id, position, level):
        sims4.commands.output('Floor exists at location', _connection)
        return True
    sims4.commands.output('Floor does not exist at location', _connection)
    return False

@sims4.commands.Command('placement.get_slots')
def get_slots(obj_id, _connection=None):
    output = sims4.commands.Output(_connection)
    obj = objects.system.find_object(obj_id)
    if obj is not None:
        for slot in obj.get_runtime_slots_gen():
            output('{}: {}'.format(slot, slot.slot_height_and_parameter))
        output('Deco slotset:   {}'.format(obj.deco_slot_types or 'None'))
        output('Normal slotset: {}'.format(obj.slot_types or 'None'))
        output('Ideal slotset:  {}'.format(obj.ideal_slot_types or 'None'))
        return True
    return False

@sims4.commands.Command('carry.get_carried_objects')
def get_carried_objects(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('Invalid Sim id: {}'.format(opt_sim), _connection)
        return False
    for (hand, _, obj) in get_carried_objects_gen(sim):
        sims4.commands.output('\t{}: {}'.format(hand, obj), _connection)
    return True

