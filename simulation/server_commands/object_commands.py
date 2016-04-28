import collections
import itertools
import random
from crafting.crafting_interactions import DebugCreateCraftableInteraction
from crafting.crafting_tunable import CraftingTuning
from distributor.ops import GenericProtocolBufferOp
from distributor.rollback import ProtocolBufferRollback
from distributor.system import Distributor
from objects import VisibilityState, MaterialState, PaintingState
from objects.components import types, Component, consumable_component
from objects.components.censor_grid_component import CensorState
from objects.prop_object import PropObject
from postures.posture_graph import supress_posture_graph_build
from protocolbuffers.UI_pb2 import InventoryCountUpdate
from server_commands.argument_helpers import OptionalTargetParam, get_optional_target, RequiredTargetParam, TunableInstanceParam
from sims4.commands import NoneIntegerOrString
import camera
import objects.components
import objects.system
import placement
import postures.posture_graph
import routing
import services
import sims4.commands
import sims4.math
import sims4.zone_utils
import weakref

@sims4.commands.Command('objects.list', command_type=sims4.commands.CommandType.Automation)
def list_objects(filter_name=None, _connection=None):
    manager = services.object_manager()
    if filter_name is None:
        object_types = {}
        total = 0
        for obj in manager.get_all():
            total += 1
            t = type(obj).__name__
            object_types[t] = object_types.get(t, 0) + 1
        for (object_type, count) in object_types.items():
            sims4.commands.output('{}: {}'.format(object_type, count), _connection)
        sims4.commands.output('Total: {}'.format(total), _connection)
    elif filter_name == 'all':
        total = 0
        for obj in manager.get_all():
            sims4.commands.output('{}: {} (obj_id={:#018x}, addr={:#010x})'.format(type(obj).__name__, obj, obj.id, id(obj)), _connection)
            total += 1
        sims4.commands.output('Total: {}'.format(total), _connection)
    elif filter_name == 'definitions':
        all_definitions = collections.Counter()
        for obj in manager.get_all():
            all_definitions[obj.definition] += 1
        for (definition, count) in sorted(all_definitions.items(), key=lambda x: x[0].id):
            sims4.commands.output('{},{:#010x},{}'.format(definition.name, definition.id, count), _connection)
    else:
        total = 0
        for obj in manager.get_all():
            t = type(obj).__name__
            while filter_name in t:
                sims4.commands.output('{}: {} (obj_id={:#018x}, addr={:#010x})'.format(type(obj).__name__, obj, obj.id, id(obj)), _connection)
                total += 1
        sims4.commands.output('Total: {}'.format(total), _connection)

@sims4.commands.Command('objects.dump')
def dump_object(obj_id, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('DUMP_OBJECT: Object ID not in the object manager.', _connection)
    if obj is not None:
        sims4.commands.output('Object {} ({})'.format(obj_id, obj.__class__.__name__), _connection)
        for (key, value) in vars(obj).items():
            sims4.commands.output('\t{} = {}'.format(key, value), _connection)
            while isinstance(value, Component):
                while True:
                    for (key, value) in vars(value).items():
                        sims4.commands.output('\t\t{} = {}'.format(key, value), _connection)

@sims4.commands.Command('objects.dump_def')
def dump_definition(guid, _connection=None):
    manager = services.definition_manager()
    obj_def = manager.get(guid)
    if not obj_def:
        sims4.commands.output('DUMP_DEFINITION: Unknown object definition GUID {}.'.format(guid), _connection)
    else:
        sims4.commands.output('Definition {}'.format(guid), _connection)
        for (key, value) in vars(obj_def).items():
            sims4.commands.output('    {} = {}'.format(key, value), _connection)

@sims4.commands.Command('objects.in_use')
def show_in_use(obj_id, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('in_use: Object ID not in the object manager.', _connection)
        return
    if getattr(obj, 'in_use'):
        sims4.commands.output('[{}] {} in_use = '.format(obj_id, obj.__class__.__name__, obj.in_use), _connection)
    else:
        sims4.commands.output('[{}] {} does not have the in_use property.'.format(obj_id, obj.__class__.__name__), _connection)

@sims4.commands.Command('objects.create', command_type=sims4.commands.CommandType.Automation)
def create_object(def_id, x:float=0.0, y:float=0.0, z:float=0.0, level:int=0, _connection=None):
    obj = objects.system.create_object(def_id)
    if obj is not None:
        routing_surface = routing.SurfaceIdentifier(sims4.zone_utils.get_zone_id(), level, routing.SURFACETYPE_WORLD)
        obj.move_to(translation=sims4.math.Vector3(x, y, z), routing_surface=routing_surface)
    return obj

@sims4.commands.Command('objects.create_multiple_objects', 'objects.make_it_rain')
def create_multiple_objects(number, *obj_ids, _connection=None):
    manager = services.object_manager()
    sim = get_optional_target(None, _connection)
    search_flags = placement.FGLSearchFlagsDefault | placement.FGLSearchFlag.SHOULD_TEST_BUILDBUY
    if sim is not None:
        starting_position = sim.position
        routing_surface = sim.routing_surface
    else:
        lot = services.active_lot()
        starting_position = lot.position
        routing_surface = routing.SurfaceIdentifier(services.current_zone().id, 0, routing.SURFACETYPE_WORLD)
    with postures.posture_graph.supress_posture_graph_build():
        for obj_id in obj_ids:
            obj_id = int(obj_id)
            original_obj = None
            if obj_id in manager:
                original_obj = manager.get(obj_id)
            if original_obj is None:
                return
            obj_definition_id = original_obj.definition.id
            created_obj_count = number
            while created_obj_count > 0:
                if original_obj.crafting_component is not None:
                    obj = DebugCreateCraftableInteraction.create_craftable(original_obj.crafting_component._crafting_process.recipe, sim)
                else:
                    obj = objects.system.create_object(obj_definition_id)
                if obj is not None:
                    fgl_context = placement.FindGoodLocationContext(starting_position=starting_position, object_id=obj.id, search_flags=search_flags, object_footprints=(obj.get_footprint(),))
                    (position, orientation) = placement.find_good_location(fgl_context)
                    if position is not None and orientation is not None:
                        obj.move_to(translation=position, orientation=orientation, routing_surface=routing_surface)
                    else:
                        obj.destroy(source=obj, cause='Failed to find good location for create_multiple_objects')
                created_obj_count -= 1

@sims4.commands.Command('objects.create_multiple_objects_from_definition')
def create_multiple_objects_from_definition(number, *obj_defs, _connection=None):
    created_objs = []
    obj_ids = []
    try:
        for obj_def in obj_defs:
            obj = objects.system.create_object(obj_def)
            while obj is not None:
                created_objs.append(obj)
                obj_ids.append(obj.id)
        create_multiple_objects(number, _connection=_connection, *obj_ids)
    finally:
        for obj in created_objs:
            obj.destroy(source=obj, cause='Destroying original objects in create_multiple_objects_from_definition')

@sims4.commands.Command('objects.create_all_carryables')
def create_all_carryables(_connection=None):
    carryable_component_name = 'carryable'
    done = False
    created_objs = []
    obj_ids = []
    try:
        definition_manager = services.definition_manager()
        for obj_def in definition_manager.loaded_definitions:
            obj_tuning = obj_def.cls
            carryable_component = obj_tuning._components.get(carryable_component_name)
            if carryable_component is None:
                pass
            try:
                obj = objects.system.create_object(obj_def)
            except:
                obj = None
            if obj is not None:
                created_objs.append(obj)
                obj_ids.append(obj.id)
            while done:
                break
        create_multiple_objects(1, _connection=_connection, *obj_ids)
    finally:
        for obj in created_objs:
            obj.destroy(source=obj, cause='Destroying original objects in create_all_carryables.')

@sims4.commands.Command('objects.set_as_head', command_type=sims4.commands.CommandType.Cheat)
def set_as_head(obj_id:RequiredTargetParam=None, scale:float=None, forward_rot:float=None, up_rot:float=None, _connection=None):
    sim = get_optional_target(None, _connection)
    if sim is None:
        return
    original_obj = obj_id.get_target()
    if original_obj is None:
        return
    if original_obj.is_sim:
        sims4.commands.output('Cannot set a Sim as your head.', _connection)
        return
    obj_definition_id = original_obj.definition.id
    if original_obj.crafting_component is not None:
        obj = DebugCreateCraftableInteraction.create_craftable(original_obj.crafting_component._crafting_process.recipe, sim)
    else:
        obj = objects.system.create_object(obj_definition_id)
    if obj is None:
        return
    if scale is None:
        head_width = 0.75
        default_object_width = head_width/4
        polygon = obj.footprint_polygon
        if len(polygon) > 1:
            polygon2 = list(polygon)[1:]
            polygon2.append(polygon[-1])
            object_width_x = max([abs(x - y).x for (x, y) in zip(polygon2, polygon)])
            object_width_z = max([abs(x - y).z for (x, y) in zip(polygon2, polygon)])
            object_width = min((object_width_x, object_width_z))
        else:
            object_width = default_object_width
        new_scale = head_width/object_width
        obj.scale = new_scale
    else:
        obj.scale = scale
    forward_rot = 4*sims4.math.PI/3 if forward_rot is None else forward_rot
    up_rot = 3*sims4.math.PI/2 if up_rot is None else up_rot
    forward_orientation = sims4.math.Quaternion.from_axis_angle(forward_rot, sims4.math.FORWARD_AXIS)
    up_orientation = sims4.math.Quaternion.from_axis_angle(up_rot, sims4.math.UP_AXIS)
    orientation = sims4.math.Quaternion.concatenate(forward_orientation, up_orientation)
    new_transform = sims4.math.Transform.IDENTITY()
    new_transform.orientation = orientation
    neck_hash = sims4.hash_util.hash32('b__neck__')
    if sim.current_object_set_as_head is not None and sim.current_object_set_as_head() is not None:
        sim.current_object_set_as_head().destroy(source=sim, cause='Destroying existing object set as head when setting new one.')
    sim.current_object_set_as_head = weakref.ref(obj)
    obj.set_parent(sim, transform=new_transform, joint_name_or_hash=neck_hash)

@sims4.commands.Command('objects.remove_object_set_as_head', command_type=sims4.commands.CommandType.Cheat)
def remove_object_set_as_head(_connection=None):
    sim = get_optional_target(None, _connection)
    if sim is None:
        return
    if sim.current_object_set_as_head is not None and sim.current_object_set_as_head() is not None:
        sim.current_object_set_as_head().destroy(source=sim, cause='Removing object set as head')
    sim.current_object_set_as_head = None

@sims4.commands.Command('objects.teleport')
def teleport_object(obj_id:int=None, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    if obj is None:
        return
    ot = obj.get_component(types.OBJECT_TELEPORTATION_COMPONENT)
    if ot is not None:
        ot.teleport(None)

@sims4.commands.Command('objects.reset', command_type=sims4.commands.CommandType.Automation)
def reset(obj_id:int=None, expected:bool=True, _connection=None):
    return objects.system.reset_object(obj_id, expected=expected, cause='Command')

@sims4.commands.Command('objects.destroy', command_type=sims4.commands.CommandType.Automation)
def destroy_objects(*obj_ids, _connection=None):
    result = True
    for obj_id in obj_ids:
        obj_id = int(obj_id, 0)
        obj = objects.system.find_object(obj_id, include_props=True)
        if obj is None:
            result = False
        obj.destroy(source=obj, cause='Destroyed requested objects in destroy_objects command.')
        while obj.is_sim:
            obj.client.selectable_sims.notify_dirty()
    return result

@sims4.commands.Command('objects.destroy_children')
def destroy_object_children(obj_id:int=None, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    if obj is None:
        return
    for child in list(obj.children):
        child.destroy(source=obj, cause='Destroy children requested by destroy_object_children command')

@sims4.commands.Command('objects.gsi_create_obj', command_type=sims4.commands.CommandType.Automation)
def gsi_create_object(def_id, x_pos:float=None, y_pos:float=None, z_pos:float=None, _connection=None):
    obj = objects.system.create_object(def_id)
    if x_pos is None or y_pos is None or z_pos is None:
        start_pos = services.current_zone().lot.center
    else:
        start_pos = sims4.math.Vector3(x_pos, y_pos, z_pos)
    if obj is not None:
        search_flags = placement.FGLSearchFlagsDefault
        fgl_context = placement.FindGoodLocationContext(starting_position=start_pos, object_id=obj.id, max_distance=100, search_flags=search_flags, object_footprints=(obj.get_footprint(),))
        (position, orientation) = placement.find_good_location(fgl_context)
        obj.transform = sims4.math.Transform(position, orientation)
        return True
    return False

@sims4.commands.Command('objects.fade_and_destroy', command_type=sims4.commands.CommandType.Live)
def fade_and_destroy_object(obj_id, _connection=None):
    obj_id = int(obj_id, 0)
    obj = objects.system.find_object(obj_id)
    if obj is not None:
        obj.fade_and_destroy()
        return True
    return False

@sims4.commands.Command('objects.clear_lot', 'objects.destroy_all')
def destroy_all_objects(_connection=None):
    with supress_posture_graph_build():
        all_objects = list(itertools.chain(services.object_manager().objects, services.prop_manager().objects))
        for obj in all_objects:
            while obj.persistence_group != objects.persistence_groups.PersistenceGroups.SIM:
                obj.destroy(source=obj, cause='destroy_all_objects command')
        return True

@sims4.commands.Command('objects.clear_minor')
def destroy_all_objects_with_less_area_than(max_area=0.25, _connection=None):
    with supress_posture_graph_build():
        all_objects = list(itertools.chain(services.object_manager().objects, services.prop_manager().objects))
        for obj in all_objects:
            if isinstance(obj, PropObject):
                obj.destroy(source=obj, cause='Prop in destroy_all_objects_with_less_area_than command')
            else:
                while obj.persistence_group != objects.persistence_groups.PersistenceGroups.SIM:
                    poly = obj.footprint_polygon
                    if poly:
                        if poly.area() < max_area:
                            obj.destroy(source=obj, cause='Too small in destroy_all_objects_with_less_area_than command')
    return True

@sims4.commands.Command('objects.destroy_random', command_type=sims4.commands.CommandType.Automation)
def destroy_random_objects(count:int=1, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    with supress_posture_graph_build():
        all_objects = list(itertools.chain(services.object_manager().objects, services.prop_manager().objects))
        non_sim_objects = list(obj for obj in all_objects if obj.persistence_group != objects.persistence_groups.PersistenceGroups.SIM)
        count = min(count, len(non_sim_objects))
        to_kill = random.sample(non_sim_objects, count)
        for obj in to_kill:
            obj.destroy(source=obj, cause='destroy_random_objects command')
        output('{}/{} objects destroyed!'.format(len(to_kill), len(non_sim_objects)))
    return True

@sims4.commands.Command('objects.set_build_buy_lockout_state')
def set_build_buy_lockout_state(opt_obj:OptionalTargetParam=None, lockout_state:bool=None, lockout_timer:int=None, _connection=None):
    obj = get_optional_target(opt_obj, _connection)
    if obj is None:
        return False
    if lockout_state is None:
        lockout_state = not obj.build_buy_lockout
    obj.set_build_buy_lockout_state(lockout_state, lockout_timer)

@sims4.commands.Command('objects.set_position', command_type=sims4.commands.CommandType.Automation)
def set_position(obj_id, x:float=0, y:float=0, z:float=0, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('set_position: Object ID not in the object manager.', _connection)
    if obj is not None:
        location = obj.location.clone(translation=sims4.math.Vector3(x, y, z))
        obj.location = location

@sims4.commands.Command('objects.set_tint')
def set_tint(obj_id, r:float=1.0, g:float=1.0, b:float=1.0, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('SET_TINT: Object ID not in the object manager.', _connection)
    if obj is not None:
        tint = sims4.color.from_rgba(r, g, b)
        obj.tint = tint

@sims4.commands.Command('objects.set_opacity')
def set_opacity(obj_id, a:float=1.0, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('SET_OPACITY: Object ID not in the object manager.', _connection)
    if obj is not None:
        obj.opacity = a

@sims4.commands.Command('objects.fade_opacity')
def fade_opacity(obj_id, opacity:float=1.0, duration:float=0.0, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('FADE_OPACITY: Object ID not in the object manager.', _connection)
    if obj is not None:
        obj.fade_opacity(opacity, duration)

@sims4.commands.Command('objects.set_painting_state')
def set_painting_state(obj_id, texture_name_or_hash, reveal_level:int=0, use_overlay:bool=False, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('SET_PAINTING_STATE: Object ID not in the object manager.', _connection)
    if obj is not None and obj.canvas_component is not None:
        if texture_name_or_hash is None:
            painting_state = None
        elif type(texture_name_or_hash) is str:
            painting_state = PaintingState.from_name(texture_name_or_hash, reveal_level, use_overlay)
        else:
            painting_state = PaintingState(texture_name_or_hash, reveal_level, use_overlay)
        obj.canvas_component.painting_state = painting_state

@sims4.commands.Command('objects.set_light_dimmer')
def set_light_dimmer(obj_id, a:float=1.0, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('SET_LIGHT_DIMMER: Object ID not in the object manager.', _connection)
        return False
    if not obj.lighting_component:
        sims4.commands.output("SET_LIGHT_DIMMER: Object doesn't have a lighting component so the light dimmer can't be set.", _connection)
        return False
    obj.set_light_dimmer_value(a)

@sims4.commands.Command('objects.add_censor')
def add_censor(obj_id, mode:str=None, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('ADD_CENSOR: Object ID not in the object manager.', _connection)
    if obj is not None:
        mode = mode.upper()
        if mode.startswith('CENSOR_'):
            mode = mode[7:]
        if mode in CensorState:
            handle = obj.censorgrid_component.add_censor(CensorState[mode])
            sims4.commands.output('Censor created with handle: {}'.format(handle), _connection)
        else:
            sims4.commands.output('Unknown censor mode name: ' + mode, _connection)

@sims4.commands.Command('objects.remove_censor')
def remove_censor(obj_id, handle:int=None, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('REMOVE_CENSOR: Object ID not in the object manager.', _connection)
    if obj is not None:
        obj.censorgrid_component.remove_censor(handle)

@sims4.commands.Command('objects.set_geometry_state')
def set_geometry_state(obj_id, state_name='', _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('SET_GEOMETRY_STATE: Object ID not in the object manager.', _connection)
    if obj is not None:
        obj.geometry_state = state_name

@sims4.commands.Command('objects.set_visibility')
def set_visibility(obj_id, visibility:bool=True, inherits:bool=False, enable_drop_shadow:bool=False, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('SET_VISIBILITY: Object ID not in the object manager.', _connection)
    if obj is not None:
        obj.visibility = VisibilityState(visibility, inherits, enable_drop_shadow)

@sims4.commands.Command('objects.set_material_state')
def set_material_state(obj_id, state_name='', a:float=1.0, t:float=0.0, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('SET_MATERIAL_STATE: Object ID not in the object manager.', _connection)
    if obj is not None:
        obj.material_state = MaterialState(state_name, a, t)

@sims4.commands.Command('objects.set_material_variant')
def set_material_variant(obj_id, state_name='', _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('SET_MATERIAL_VARIANT: Object ID not in the object manager.', _connection)
    if obj is not None:
        obj.material_variant = state_name

@sims4.commands.Command('objects.set_object_definition')
def set_object_definition(obj_id, definition_id, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('SET_OBJECT_DEFINITION: Object ID not in the object manager.', _connection)
    if not (obj is not None and obj.set_definition(definition_id)):
        sims4.commands.output("SET_OBJECT_DEFINITION: requested new definition isn't similar to current", _connection)

@sims4.commands.Command('objects.show_crafting_cache')
def show_crafting_cache(_connection=None):
    manager = services.object_manager()
    for (crafting_type, ref_count) in manager.crafting_cache:
        sims4.commands.output('{} -> {}'.format(crafting_type, ref_count), _connection)

@sims4.commands.Command('objects.show_lockouts')
def show_lockouts(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sims4.commands.output('Standard Lockouts:', _connection)
        for (obj, end_time) in sim._lockouts.items():
            sims4.commands.output('  {} -> {}'.format(obj, end_time), _connection)
        sims4.commands.output('Crafting Lockouts:', _connection)
        for (obj, crafting_lockout_data) in sim._crafting_lockouts.items():
            sims4.commands.output('  {}:'.format(obj), _connection)
            for (crafting_type, ref_count) in crafting_lockout_data._crafting_lockout_ref_counts.items():
                sims4.commands.output('    {} -> {}'.format(crafting_type, ref_count), _connection)
    else:
        sims4.commands.output('No target for objects.show_lockouts.', _connection)

@sims4.commands.Command('objects.clear_lockouts')
def clear_lockouts(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.clear_all_lockouts()
    else:
        sims4.commands.output('No target for objects.clear_lockouts.', _connection)

@sims4.commands.Command('objects.clear_crafting_autonomoy_cache')
def clear_autonomous_crafting_cache(_connection=None):
    services.object_manager().crafting_cache.clear()

@sims4.commands.Command('discouragement_regions.enable')
def discouragement_regions_enable(_connection=None):
    import sims4.geometry
    sims4.geometry.PolygonFootprint.set_global_enabled(True)
    return True

@sims4.commands.Command('discouragement_regions.disable')
def discouragement_regions_disable(_connection=None):
    import sims4.geometry
    sims4.geometry.PolygonFootprint.set_global_enabled(False)
    return True

@sims4.commands.Command('objects.toggle_lockout_visualization')
def toggle_lockout_visualization(_connection=None):
    objects.base.lockout_visualization = not objects.script_object.lockout_visualization
    sims4.commands.output('Lockout visualization: {}'.format(objects.script_object.lockout_visualization), _connection)
    return True

@sims4.commands.Command('objects.current_value')
def object_current_value(obj_id, new_value:int=None, _connection=None):
    output = sims4.commands.Output(_connection)
    obj = services.object_manager()[obj_id]
    output('Current value: {}'.format(obj.current_value))
    if new_value is not None:
        obj.current_value = new_value
        output('New value: {}'.format(obj.current_value))
    return True

@sims4.commands.Command('objects.focus_camera_on_object')
def focus_camera_on_object(obj_id, _connection=None):
    manager = services.object_manager()
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('Object ID not in the object manager.', _connection)
        return
    if obj is not None:
        client = services.client_manager().get(_connection)
        camera.focus_on_position(obj.position, client)

@sims4.commands.Command('objects.add_stored_sim')
def object_add_stored_sim_info(obj:RequiredTargetParam=None, sim_id:OptionalTargetParam=None, _connection=None):
    obj = obj.get_target()
    sim = get_optional_target(sim_id, _connection)
    if obj is not None and sim is not None:
        obj.add_dynamic_component(types.STORED_SIM_INFO_COMPONENT.instance_attr, sim_id=sim.id)
        return True
    return False

@sims4.commands.Command('objects.get_inventory_counts', command_type=sims4.commands.CommandType.Live)
def get_inventory_counts(_connection=None):
    zone = services.current_zone()
    if zone is None:
        return False
    if zone.lot is None:
        return False
    inventory_counts_msg = InventoryCountUpdate()
    for (inventory_type, inventory) in zone.lot.get_all_object_inventories_gen():
        with ProtocolBufferRollback(inventory_counts_msg.inventory_counts) as inventory_count_msg:
            inventory_count_msg.inventory_type = inventory_type
            inventory_count_msg.count = len(inventory)
    distributor = Distributor.instance()
    distributor.add_op_with_no_owner(GenericProtocolBufferOp(Operation.INVENTORY_COUNT_UPDATE, inventory_counts_msg))
    return True

@sims4.commands.Command('objects.test_save_load')
def test_save_load(obj:RequiredTargetParam=None, _connection=None):
    obj = obj.get_target()
    clone = obj.clone()
    clone.location = obj.location
    obj.destroy(source=clone, cause='test_save_load command')
    return True

@sims4.commands.Command('objects.set_state_value')
def set_state_value(state_value, obj_id:int=None, _connection=None):
    state = state_value.state
    object_manager = services.object_manager()
    if obj_id is not None:
        obj = object_manager.get(obj_id)
        if obj.has_state(state):
            obj.set_state(state, state_value)
            return True
        sims4.commands.output('State Value {} from State {} is invalid for object {} '.format(state_value_name, state, obj), _connection)
        return False
    for obj in object_manager.values():
        while obj.state_component is not None and obj.has_state(state):
            obj.set_state(state, state_value)
    return True

@sims4.commands.Command('objects.set_household_owner', command_type=sims4.commands.CommandType.Automation)
def set_household_owner(obj_id:int=None, household_id:int=None, _connection=None):
    if obj_id is None:
        sims4.commands.output('Usage: objects.set_household_owner <obj_id> optional:<household_id>: No obj_id provided', _connection)
        return False
    selected_obj = services.object_manager().get(obj_id)
    if selected_obj is None:
        sims4.commands.output('Usage: objects.set_household_owner <obj_id> optional:<household_id>: obj_id is not in the object manager', _connection)
        return False
    current_zone = services.current_zone()
    if household_id is None:
        household_id = current_zone.lot.owner_household_id
    household = current_zone.household_manager.get(household_id)
    if household is None:
        sims4.commands.output('Usage: objects.set_household_owner <obj_id> optional:<household_id>: Could not find household({})'.format(household_id), _connection)
        return False
    selected_obj.set_household_owner_id(household_id)
    return True

@sims4.commands.Command('objects.get_users', command_type=sims4.commands.CommandType.Automation)
def get_object_use_list(obj_id:int=None, _connection=None):
    if obj_id is None:
        sims4.commands.output('Usage: objects.get_users <obj_id>: No obj_id provided', _connection)
        return False
    current_zone = services.current_zone()
    selected_obj = current_zone.find_object(obj_id)
    if selected_obj is None:
        sims4.commands.output('Usage: objects.get_users <obj_id>: obj_id is not in the object manager or inventory manager.', _connection)
        return False
    object_users = selected_obj.get_users(sims_only=True)
    user_strs = []
    for (index, reserver) in enumerate(object_users):
        user_strs.append('SimId{}:{}'.format(index, reserver.id))
    use_list_str = 'ObjectUserList; ObjectId:{}, NumUsers:{}, {}'.format(obj_id, len(object_users), ', '.join(user_strs))
    sims4.commands.automation_output(use_list_str, _connection)
    sims4.commands.output(use_list_str, _connection)

@sims4.commands.Command('objects.print_transform', command_type=sims4.commands.CommandType.Cheat)
def print_object_transform(obj_id:int=None, _connection=None):
    if obj_id is None:
        sims4.commands.output('Usage: objects.print_object_transform <obj_id>: No obj_id provided', _connection)
        return False
    current_zone = services.current_zone()
    selected_obj = current_zone.find_object(obj_id)
    if selected_obj is None:
        sims4.commands.output('Usage: objects.get_users <obj_id>: obj_id is not in the object manager or inventory manager.', _connection)
        return False
    sims4.commands.output(str(selected_obj.transform), _connection)
    if not selected_obj.parts:
        return
    for part in selected_obj.parts:
        sims4.commands.output('Part[{}]: {}'.format(part.part_suffix, part.transform), _connection)

@sims4.commands.Command('objects.consumables_infinite_toggle', command_type=sims4.commands.CommandType.Cheat)
def make_consumables_infinite(_connection=None):
    consumable_component.debug_consumables_are_infinite = not consumable_component.debug_consumables_are_infinite
    if consumable_component.debug_consumables_are_infinite:
        message = 'All consumables have infinite contents!'
    else:
        message = 'All consumables are again ordinary and thus boring.'
    sims4.commands.output(message, _connection)

@sims4.commands.Command('objects.consumable_make_spoiled', command_type=sims4.commands.CommandType.Automation)
def make_consumable_spoiled(obj_id, _connection=None):
    current_zone = services.current_zone()
    selected_obj = current_zone.find_object(obj_id)
    if selected_obj is None:
        sims4.commands.output('Usage: objects.consumable_make_spoiled <obj_id>: obj_id is not in the object manager or inventory manager.', _connection)
        return False
    selected_obj.set_state(CraftingTuning.FRESHNESS_STATE, CraftingTuning.SPOILED_STATE_VALUE)

