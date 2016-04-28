import itertools
import re
from gsi_handlers.gameplay_archiver import GameplayArchiver
from objects.game_object import GameObject
from sims4.gsi.dispatcher import GsiHandler, add_cheat_schema
from sims4.gsi.schema import GsiGridSchema, GSIGlobalCheatSchema, GsiFieldVisualizers
import gsi_handlers.gsi_utils
import services
import sims4
global_object_cheats_schema = GSIGlobalCheatSchema()
global_object_cheats_schema.add_cheat('objects.clear_lot', label='Clear Lot')
add_cheat_schema('global_object_cheats', global_object_cheats_schema)
object_manager_schema = GsiGridSchema(label='Object Manager')
object_manager_schema.add_field('mgr', label='Manager', width=1, hidden=True)
object_manager_schema.add_field('objId', label='Object Id', width=3, unique_field=True)
object_manager_schema.add_field('classStr', label='Class', width=3)
object_manager_schema.add_field('modelStr', label='Model', width=3)
object_manager_schema.add_field('locX', label='X', width=1)
object_manager_schema.add_field('locY', label='Y', width=1)
object_manager_schema.add_field('locZ', label='Z', width=1)
object_manager_schema.add_field('on_active_lot', label='On Active Lot', width=1, hidden=True)
object_manager_schema.add_field('current_value', label='Value', width=1)
object_manager_schema.add_field('isSurface', label='Surface', width=1)
object_manager_schema.add_field('parent', label='Parent', width=2)
object_manager_schema.add_field('inUseBy', label='In Use By', width=2)
object_manager_schema.add_field('lockouts', label='Lockouts', width=2)
object_manager_schema.add_field('transient', label='Transient', width=1, hidden=True)
object_manager_schema.add_field('is_interactable', label='Interactable', width=1, hidden=True)
object_manager_schema.add_field('footprint', label='Footprint', width=1, hidden=True)
object_manager_schema.add_field('inventory_owner_id', label='inventory owner id', width=2, hidden=True)
object_manager_schema.add_filter('on_active_lot')
object_manager_schema.add_filter('game_objects')
object_manager_schema.add_filter('prototype_objects')
object_manager_schema.add_filter('all_objects')
with object_manager_schema.add_view_cheat('objects.destroy', label='Delete') as cheat:
    cheat.add_token_param('objId')
with object_manager_schema.add_view_cheat('objects.reset', label='Reset') as cheat:
    cheat.add_token_param('objId')
with object_manager_schema.add_view_cheat('objects.focus_camera_on_object', label='Focus On Selected Object') as cheat:
    cheat.add_token_param('objId')
with object_manager_schema.add_has_many('commodities', GsiGridSchema) as sub_schema:
    sub_schema.add_field('commodity', label='Commodity')
    sub_schema.add_field('value', label='value')
    sub_schema.add_field('convergence_value', label='convergence value')
    sub_schema.add_field('decay_rate', label='decay')
    sub_schema.add_field('change_rate', label='change rate')
with object_manager_schema.add_has_many('postures', GsiGridSchema) as sub_schema:
    sub_schema.add_field('interactionName', label='Interaction Name')
    sub_schema.add_field('providedPosture', label='Provided Posture')
with object_manager_schema.add_has_many('states', GsiGridSchema) as sub_schema:
    sub_schema.add_field('state_type', label='State')
    sub_schema.add_field('state_value', label='Value')
    sub_schema.add_field('state_severity', label='Severity')
with object_manager_schema.add_has_many('parts', GsiGridSchema) as sub_schema:
    sub_schema.add_field('part_group_index', label='Part Group Index', width=0.5)
    sub_schema.add_field('part_suffix', label='Part Suffix', width=0.5)
    sub_schema.add_field('subroot_index', label='SubRoot', width=0.5)
    sub_schema.add_field('using_sim', label='Using Sim')
with object_manager_schema.add_has_many('slots', GsiGridSchema) as sub_schema:
    sub_schema.add_field('slot', label='Slot')
    sub_schema.add_field('children', label='Children')
with object_manager_schema.add_has_many('inventory', GsiGridSchema) as sub_schema:
    sub_schema.add_field('objId', label='Object Id', width=2, unique_field=True)
    sub_schema.add_field('classStr', label='Class', width=2)
    sub_schema.add_field('stack_count', label='Stack Count', width=1, type=GsiFieldVisualizers.INT)
    sub_schema.add_field('stack_sort_order', label='Stack Sort Order', width=1, type=GsiFieldVisualizers.INT)
    sub_schema.add_field('hidden', label='In Hidden', width=1)
with object_manager_schema.add_has_many('additional_data', GsiGridSchema) as sub_schema:
    sub_schema.add_field('dataId', label='Data', unique_field=True)
    sub_schema.add_field('dataValue', label='Value')

def _get_model_name(cur_obj):
    model_name = 'Unexpected Repr'
    model = getattr(cur_obj, 'model', None)
    if model is not None:
        split_model_name = re.split('[\\(\\)]', str(cur_obj.model))
        if len(split_model_name) > 1:
            model_name = split_model_name[1]
    return model_name

@GsiHandler('object_manager', object_manager_schema)
def generate_object_manager_data(*args, zone_id:int=None, filter=None, **kwargs):
    lockout_data = {}
    zone = services.get_zone(zone_id)
    for sim_info in list(zone.sim_info_manager.objects):
        sim = sim_info.get_sim_instance()
        while sim is not None:
            while True:
                for (obj, time) in sim.get_lockouts_gen():
                    lockouts = lockout_data.setdefault(obj, [])
                    lockouts.append((sim, time))
    all_object_data = []
    for cur_obj in list(itertools.chain(zone.object_manager.objects, zone.prop_manager.objects, zone.inventory_manager.objects)):
        class_str = gsi_handlers.gsi_utils.format_object_name(cur_obj)
        on_active_lot = cur_obj.is_on_active_lot() if hasattr(cur_obj, 'is_on_active_lot') else False
        while (filter is None or filter == 'all_objects' or filter == 'prototype_objects') and (class_str == 'prototype' or filter == 'game_objects') and (class_str != 'prototype' or filter == 'on_active_lot') and on_active_lot:
            obj_loc = cur_obj.position
            model_name = _get_model_name(cur_obj)
            ret_dict = {'mgr': str(cur_obj.manager).replace('_manager', ''), 'objId': hex(cur_obj.id), 'classStr': class_str, 'modelStr': model_name, 'locX': round(obj_loc.x, 3), 'locY': round(obj_loc.y, 3), 'locZ': round(obj_loc.z, 3), 'on_active_lot': str(on_active_lot), 'current_value': cur_obj.current_value, 'is_interactable': 'x' if getattr(cur_obj, 'interactable', False) else '', 'footprint': str(cur_obj.footprint_polygon) if getattr(cur_obj, 'footprint_polygon', None) else ''}
            ret_dict['additional_data'] = []
            parent = cur_obj.parent
            if parent is not None:
                ret_dict['parent'] = gsi_handlers.gsi_utils.format_object_name(parent)
                ret_dict['additional_data'].append({'dataId': 'Parent Id', 'dataValue': hex(parent.id)})
                ret_dict['additional_data'].append({'dataId': 'Parent Slot', 'dataValue': cur_obj.parent_slot.slot_name_or_hash})
            if cur_obj.state_component:
                value = cur_obj.get_most_severe_state_value()
                if value is not None:
                    ret_dict['additional_data'].append({'dataId': 'Severity', 'dataValue': value.__name__})
            ret_dict['isSurface'] = cur_obj.is_surface()
            if cur_obj in lockout_data:
                lockouts = ('{} ({})'.format(*lockout) for lockout in lockouts)
                ret_dict['lockouts'] = ', '.join(lockouts)
            ret_dict['states'] = []
            if cur_obj.state_component:
                for (state_type, state_value) in cur_obj.state_component.items():
                    state_entry = {'state_type': str(state_type), 'state_value': str(state_value), 'state_severity': str(state_value.severity)}
                    ret_dict['states'].append(state_entry)
            if cur_obj.in_use:
                users = cur_obj.get_users()
                ret_dict['inUseBy'] = gsi_handlers.gsi_utils.format_object_list_names(users)
            ret_dict['transient'] = cur_obj.transient
            ret_dict['additional_data'].append({'dataId': 'Category Tags', 'dataValue': gsi_handlers.gsi_utils.format_object_list_names(cur_obj.get_tags())})
            name = 'None'
            house_id = cur_obj.get_household_owner_id()
            ret_dict['additional_data'].append({'dataId': 'Household Owner Id', 'dataValue': house_id})
            if house_id is not None:
                household = zone.household_manager.get(house_id)
                if household is not None:
                    name = household.name
            ret_dict['additional_data'].append({'dataId': 'Household Owner', 'dataValue': name})
            sim_name = 'None'
            sim_id = cur_obj.get_sim_owner_id()
            if sim_id is not None:
                sim_info = zone.sim_info_manager.get(sim_id)
                sim_name = sim_info.full_name
            ret_dict['additional_data'].append({'dataId': 'Sim Owner', 'dataValue': sim_name})
            if cur_obj.is_in_inventory() and cur_obj.inventoryitem_component._last_inventory_owner is not None:
                ret_dict['inventory_owner_id'] = hex(cur_obj.inventoryitem_component._last_inventory_owner.id)
            ret_dict['commodities'] = []
            for commodity in list(cur_obj.get_all_stats_gen()):
                com_entry = {'commodity': type(commodity).__name__, 'value': commodity.get_value()}
                if commodity.continuous:
                    com_entry['convergence_value'] = (commodity.convergence_value,)
                    com_entry['decay_rate'] = (commodity.base_decay_rate,)
                    com_entry['change_rate'] = (commodity.get_change_rate,)
                ret_dict['commodities'].append(com_entry)
            ret_dict['postures'] = []
            for affordance in list(cur_obj.super_affordances()):
                while affordance.provided_posture_type is not None:
                    posture_entry = {'interactionName': affordance.__name__, 'providedPosture': affordance.provided_posture_type.__name__}
                    ret_dict['postures'].append(posture_entry)
            ret_dict['parts'] = []
            if cur_obj.parts is not None:
                for part in cur_obj.parts:
                    part_entry = {'part_group_index': part.part_group_index, 'part_suffix': part.part_suffix, 'subroot_index': part.subroot_index}
                    if part.using_sim is not None:
                        ret_dict['inUseBy'] = 'In Use(See Parts Tab)'
                        part_entry['using_sim'] = part.using_sim.full_name
                    ret_dict['parts'].append(part_entry)
            ret_dict['slots'] = []
            for runtime_slot in cur_obj.get_runtime_slots_gen():
                slot_entry = {'slot': str(runtime_slot), 'children': ', '.join(gsi_handlers.gsi_utils.format_object_name(child) for child in runtime_slot.children)}
                ret_dict['slots'].append(slot_entry)
            ret_dict['inventory'] = []
            inventory = cur_obj.inventory_component
            if isinstance(cur_obj, GameObject) and inventory is not None:
                while True:
                    for obj in inventory:
                        inv_entry = {}
                        inv_entry['objId'] = hex(obj.id)
                        inv_entry['classStr'] = gsi_handlers.gsi_utils.format_object_name(obj)
                        inv_entry['stack_count'] = obj.stack_count()
                        inv_entry['stack_sort_order'] = obj.get_stack_sort_order(inspect_only=True)
                        inv_entry['hidden'] = inventory.is_object_hidden(obj)
                        ret_dict['inventory'].append(inv_entry)
            all_object_data.append(ret_dict)
    return all_object_data

object_definitions_schema = GsiGridSchema(label='Object Definitions', auto_refresh=False)
object_definitions_schema.add_field('obj_name', label='Name', width=2)
object_definitions_schema.add_field('instance_id', label='Inst ID', unique_field=True)
with object_definitions_schema.add_view_cheat('objects.gsi_create_obj', label='Create Obj', dbl_click=True) as cheat:
    cheat.add_token_param('instance_id')

@GsiHandler('object_definitions', object_definitions_schema)
def generate_object_instances_data(*args, zone_id:int=None, **kwargs):
    all_objects = []
    for key in sorted(sims4.resources.list(type=sims4.resources.Types.OBJECTDEFINITION)):
        all_objects.append({'obj_name': sims4.resources.get_debug_name(key, table_type=sims4.hash_util.KEYNAMEMAPTYPE_OBJECTINSTANCES), 'instance_id': str(key.instance)})
    return all_objects

object_removed_schema = GsiGridSchema(label='Object Removed Log')
object_removed_schema.add_field('mgr', label='Manager', width=1, hidden=True)
object_removed_schema.add_field('objId', label='Object Id', width=3, unique_field=True)
object_removed_schema.add_field('classStr', label='Class', width=3)
object_removed_schema.add_field('modelStr', label='Model', width=3)
object_removed_schema.add_field('parent', label='Parent', width=2)
object_removed_archiver = GameplayArchiver('ObjectRemoved', object_removed_schema)

def archive_object_removal(obj_removed):
    class_str = gsi_handlers.gsi_utils.format_object_name(obj_removed)
    model_name = _get_model_name(obj_removed)
    ret_dict = {'mgr': str(obj_removed.manager).replace('_manager', ''), 'objId': hex(obj_removed.id), 'classStr': class_str, 'modelStr': model_name}
    parent = getattr(obj_removed, 'parent', None)
    if parent is not None:
        ret_dict['parent'] = gsi_handlers.gsi_utils.format_object_name(parent)
    object_removed_archiver.archive(data=ret_dict)

