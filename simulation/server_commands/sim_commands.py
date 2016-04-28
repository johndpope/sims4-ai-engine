import gc
import math
import random
import sys
import time
from protocolbuffers import InteractionOps_pb2 as interaction_protocol, Consts_pb2
from protocolbuffers import InteractionOps_pb2 as interaction_protocol, Sims_pb2 as protocols, Consts_pb2
from protocolbuffers.Consts_pb2 import OPC_DELETE_COMPLETE
from server.permissions import SimPermissions
from protocolbuffers.DistributorOps_pb2 import Operation, SetWhimBucks
from animation.posture_manifest import Hand
from distributor.ops import GenericProtocolBufferOp
from distributor.system import Distributor
from interactions import priority
from interactions.aop import AffordanceObjectPair
from interactions.context import InteractionContext
from interactions.priority import Priority
from interactions.utils.adventure import AdventureMomentKey, set_initial_adventure_moment_key_override
from interactions.utils.routing import WalkStyleRequest, WalkStyle
from interactions.utils.satisfy_constraint_interaction import SatisfyConstraintSuperInteraction
from objects import ALL_HIDDEN_REASONS
from objects.object_enums import ResetReason
from objects.terrain import TravelSuperInteraction
from server.pick_info import PickInfo, PickType
from server_commands.argument_helpers import OptionalTargetParam, get_optional_target, RequiredTargetParam, TunableInstanceParam
from sims.genealogy_tracker import FamilyRelationshipIndex
from sims.sim_outfits import OutfitCategory
from sims.sim_spawner import SimSpawner, SimCreator
from sims4.geometry import PolygonFootprint, build_rectangle_from_two_points_and_radius
from sims4.tuning.tunable import TunableReference
from zone import Zone
import alarms
import buffs.memory
import camera
import cas.cas
import clock
import distributor.ops
import interactions.priority
import interactions.utils.sim_focus
import objects
import objects.system
import placement
import routing
import server_commands
import services
import sims.sim_info_types as sim_info_types
import sims.sim_spawner
import sims4.commands
import sims4.hash_util
import sims4.log as log
import sims4.math
import sims4.resources
import sims4.zone_utils
import story_progression
import zone_types
with sims4.reload.protected(globals()):
    _reset_alarm_handles = {}

class CommandTuning:
    __qualname__ = 'CommandTuning'
    TERRAIN_TELEPORT_AFFORDANCE = TunableReference(description='\n        The affordance used by the command sims.teleport to teleport the sim. This\n        command is used during GUI Smoke as well. \n        ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION))
    TERRAIN_GOHERE_AFFORDANCE = TunableReference(description='\n        The affordance used by the command sims.gohere to make the sim go to a\n        specific position.\n        ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION))

@sims4.commands.Command('sim_info.printrefs')
def print_sim_info_refs(_connection=None):
    output = sims4.commands.Output(_connection)
    output('Could not create a new household.')
    output('-------------------- Ref Counts --------------------')
    for sim_info in services.sim_info_manager().objects:
        referrers = gc.get_referrers(sim_info)
        output('SimId: {}, NumRefs: {} '.format(sim_info.sim_id, sys.getrefcount(sim_info)))
        for referrer in referrers:
            output('    SimInfo Ref Held by: {}'.format(referrer))

@sims4.commands.Command('sims.spawnsimple', command_type=sims4.commands.CommandType.Automation)
def spawn_client_sims_simple(num:int=1, x:float=0, y:float=0, z:float=0, chosen_age:str=None, chosen_gender:str=None, household_id=None, _connection=None):
    tgt_client = services.client_manager().get(_connection)
    if tgt_client is None:
        log.info('SimInfo', 'No client found for spawn_client_sim, bailing.')
        return False
    account = tgt_client.account
    if household_id is None or household_id.lower() == 'new':
        tgt_client = None
        household = services.household_manager().create_household(account)
        if household is None:
            sims4.commands.output('Could not create a new household.', _connection)
            return False
    elif household_id.lower() == 'active':
        household = tgt_client.household
    else:
        household_id = int(household_id)
        manager = services.household_manager()
        household = manager.get(household_id)
        if household is None:
            sims4.commands.output('Unable to find household with ID {0}.'.format(household_id), _connection)
            return False
    if chosen_gender is not None:
        chosen_gender = chosen_gender.lower()
        if chosen_gender in ('male', 'm'):
            chosen_gender = sim_info_types.Gender.MALE
        elif chosen_gender in ('female', 'f'):
            chosen_gender = sim_info_types.Gender.FEMALE
        else:
            sims4.commands.output('Invalid gender: {0}. Valid options: male, m, female, or f.'.format(chosen_gender), _connection)
            return False
    if chosen_age is None:
        chosen_age = sim_info_types.Age.ADULT
    else:
        chosen_age = chosen_age.upper()
        try:
            chosen_age = sim_info_types.Age[chosen_age]
        except AttributeError:
            sims4.commands.output('Invalid age: {}. Valid options: {}.'.format(chosen_age, ', '.join(sim_info_types.Age.names)), _connection)
            return False
    if chosen_age is sim_info_types.Age.ELDER:
        sims4.commands.output('There is no {} model for {} yet, sorry.'.format(str(chosen_age), str(chosen_gender)), _connection)
        return False
    position = sims4.math.Vector3(x, y, z) if x != 0 and y != 0 and z != 0 else None
    sim_creators = [SimCreator(gender=chosen_gender if chosen_gender is not None else random.choice(list(sim_info_types.Gender)), age=chosen_age) for _ in range(num)]
    SimSpawner.create_sims(sim_creators, household=household, tgt_client=tgt_client, generate_deterministic_sim=True, sim_position=position, account=account, is_debug=True, skip_offset=True, additional_fgl_search_flags=placement.FGLSearchFlag.STAY_IN_SAME_CONNECTIVITY_GROUP, creation_source='cheat: sims.spawnsimple')

@sims4.commands.Command('sims.spawn', command_type=sims4.commands.CommandType.Automation)
def spawn_client_sim(x:float=0, y:float=0, z:float=0, num:int=1, gender:str=None, age:str=None, generate_deterministic_sim:bool=False, household_id=None, _connection=None):
    tgt_client = services.client_manager().get(_connection)
    if tgt_client is None:
        log.info('SimInfo', 'No client found for spawn_client_sim, bailing.')
        return False
    account = tgt_client.account
    if household_id is None:
        household = tgt_client.household
    elif household_id.lower() == 'new':
        tgt_client = None
        household = services.household_manager().create_household(account)
        if household is None:
            sims4.commands.output('Could not create a new household.', _connection)
            return False
    else:
        household_id = int(household_id)
        manager = services.household_manager()
        household = manager.get(household_id)
        if household is None:
            sims4.commands.output('Unable to find household with ID {0}.'.format(household_id), _connection)
            return False
    if gender is None:
        gender = random.choice(list(sim_info_types.Gender))
    else:
        gender = gender.lower()
        if gender in ('male', 'm'):
            gender = sim_info_types.Gender.MALE
        elif gender in ('female', 'f'):
            gender = sim_info_types.Gender.FEMALE
        else:
            sims4.commands.output('Invalid gender: {0}. Valid options: male, m, female, or f.'.format(gender), _connection)
            return False
    if age is None:
        age = sim_info_types.Age.ADULT
    else:
        age = age.upper()
        try:
            age = sim_info_types.Age[age]
        except AttributeError:
            sims4.commands.output('Invalid age: {}. Valid options: {}.'.format(age, ', '.join(sim_info_types.Age.names)), _connection)
            return False
    if age is sim_info_types.Age.ELDER:
        sims4.commands.output('There is no {} model for {} yet, sorry.'.format(str(age), str(gender)), _connection)
        return False
    position = sims4.math.Vector3(x, y, z) if x != 0 and y != 0 and z != 0 else None
    sim_creators = [SimCreator(gender=gender, age=age) for _ in range(num)]
    SimSpawner.create_sims(sim_creators, household=household, tgt_client=tgt_client, generate_deterministic_sim=generate_deterministic_sim, sim_position=position, account=account, is_debug=True, creation_source='cheat: sims.spawn')
    return True

@sims4.commands.Command('sims.recreate')
def recreate_sims(opt_sim:OptionalTargetParam=None, _connection=None):
    sims_to_load = []
    if opt_sim is not None:
        sim = get_optional_target(opt_sim, _connection)
        if sim is None:
            sims4.commands.output('No valid target for stats.enable_sim_commodities', _connection)
            return
        sims_to_load.append(sim.id)
        services.object_manager().remove(sim)
    else:
        for sim_info in services.sim_info_manager().objects:
            sims_to_load.append(sim_info.id)
            services.object_manager().remove(sim_info.get_sim_instance())
    for sim_id in sims_to_load:
        SimSpawner.load_sim(sim_id)

@sims4.commands.Command('sims.add_to_family', command_type=sims4.commands.CommandType.Cheat)
def add_to_family(opt_sim:OptionalTargetParam=None, _connection=None):
    if opt_sim is None:
        sims4.commands.output('Active sim is in the active family.', _connection)
        return False
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('No valid target for sims.add_to_family.', _connection)
        return False
    tgt_client = services.client_manager().get(_connection)
    household = tgt_client.household
    if not household.can_add_sim_info(sim.sim_info):
        sims4.commands.output('There is not enough room for this Sim.', _connection)
        return False
    if sim.household is not household:
        sim.household.remove_sim_info(sim.sim_info, destroy_if_empty_gameplay_household=True)
        household.add_sim_to_household(sim)
        tgt_client.add_selectable_sim_info(sim.sim_info)
        sim.clear_lot_routing_restrictions_ref_count()
    return True

@sims4.commands.Command('sims.modify_in_cas', command_type=sims4.commands.CommandType.Live)
def modify_in_cas(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('No valid target for sims.modify_in_cas.', _connection)
        return
    sims4.commands.client_cheat('sims.exit2cas {} {}'.format(sim.id, sim.household_id), _connection)

@sims4.commands.Command('sims.modify_in_cas_with_householdId', command_type=sims4.commands.CommandType.Live)
def modify_in_cas_with_householdId(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('No valid target for sims.modify_in_cas_with_householdId.', _connection)
        return
    sims4.commands.client_cheat('sims.exit2caswithhouseholdid {} {}'.format(sim.id, sim.household_id), _connection)

@sims4.commands.Command('sims.set_name_keys', command_type=sims4.commands.CommandType.Live)
def set_name_keys(opt_sim:OptionalTargetParam=None, first_name_key:int=0, last_name_key:int=0, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    sim.sim_info.first_name_key = first_name_key
    sim.sim_info.last_name_key = last_name_key

@sims4.commands.Command('sims.set_next', command_type=sims4.commands.CommandType.Live)
def set_next_sim(_connection=None):
    if _connection is not None:
        tgt_client = services.client_manager().get(_connection)
        if tgt_client is not None:
            if tgt_client.set_next_sim():
                log.info('SimInfo', 'Setting next Sim: Success')
                return True
            log.info('SimInfo', 'Setting next Sim: No change')
            return False
        else:
            log.info('SimInfo', 'Setting next Sim: No client manager')
            return False

@sims4.commands.Command('sims.set_active', command_type=sims4.commands.CommandType.Live)
def set_active_sim(sim_id:int=None, _connection=None):
    if _connection is not None and sim_id is not None:
        tgt_client = services.client_manager().get(_connection)
        if tgt_client is not None and tgt_client.set_active_sim_by_id(sim_id):
            log.info('SimInfo', 'Setting active Sim to {0}: Success', sim_id)
            sims4.commands.automation_output('SetActiveSim; Status:Success', _connection)
            return True
        log.info('SimInfo', 'Setting active Sim: No change')
        sims4.commands.automation_output('SetActiveSim; Status:NoChange', _connection)
        return True
    log.info('SimInfo', 'Incorrect number of parameters to set_active_sim.')
    sims4.commands.automation_output('SetActiveSim; Status:ParamError', _connection)
    return False

@sims4.commands.Command('sims.remove_sims_selectable')
def remove_sims_selectable(*args, _connection=None):
    if not args:
        return False
    if len(args) == 0:
        log.info('SelectableSims', 'Incorrect number of parameters to remove_sims_selectable. Must pass in one or more Sim Ids.')
    tgt_client = services.client_manager().get(_connection)
    if tgt_client is not None:
        for sim_id in args:
            while not tgt_client.remove_selectable_sim_by_id(int(sim_id)):
                sims4.commands.output('Failed to remove sim from selectability. At least 1 Sim must be selectable...', _connection)
                return False
    else:
        log.info('SelectableSims', 'Failed to get client to remove sims from selectability.')
    return True

@sims4.commands.Command('sims.make_sims_selectable')
def make_sims_selectable(*args, _connection=None):
    if not args:
        return False
    if len(args) == 0:
        log.info('SelectableSims', 'Incorrect number of parameters to make_sims_selectable. Must pass in one or more Sim Ids.')
        return
    tgt_client = services.client_manager().get(_connection)
    if tgt_client is not None:
        for sim_id in args:
            tgt_client.add_selectable_sim_by_id(int(sim_id))
    else:
        log.info('SelectableSims', 'Failed to get client to make sims selectable')

@sims4.commands.Command('sims.clear_selectable_sims')
def clear_all_selectable(_connection=None):
    if _connection is not None:
        tgt_client = services.client_manager().get(_connection)
        tgt_client.clear_selectable_sims()

@sims4.commands.Command('sims.make_all_selectable')
def make_all_selectable(_connection=None):
    if _connection is not None:
        tgt_client = services.client_manager().get(_connection)
        tgt_client.make_all_sims_selectable()

@sims4.commands.Command('sims.get_travel_menu_info', command_type=sims4.commands.CommandType.Live)
def get_travel_menu_info(*args, _connection=None):
    zone = services.current_zone()
    client = zone.client_manager.get(_connection)
    if client is None:
        log.info('Travel', 'No client found for get_travel_menu_info, bailing.')
        return False
    if zone.travel_service.has_pending_travel(client.account):
        log.info('Travel', 'Client has a pending travel.')
        return False
    household = client.household
    travel_info = interaction_protocol.TravelMenuInfo()
    for sim in household.instanced_sims_gen():
        travel_info.sim_ids.append(sim.id)
    distributor = Distributor.instance()
    distributor.add_op_with_no_owner(GenericProtocolBufferOp(Operation.TRAVEL_MENU_INFO, travel_info))

_walk_style_handles = {}

@sims4.commands.Command('sims.set_walkstyle')
def set_walkstyle(walkstyle, priority:int=100, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    handle = _walk_style_handles.get(sim.id)
    if handle is not None:
        handle.release()
        del _walk_style_handles[sim.id]
    for style in WalkStyle:
        while style.name.lower() == walkstyle.lower():
            _walk_style_handles[sim.id] = sim.request_walkstyle(WalkStyleRequest(priority, style), 1)
            break
    sims4.commands.output('set_walkstyle: Walkstyle not found!', _connection)
    return False
    return True

@sims4.commands.Command('sims.clear_walkstyle')
def clear_walkstyle(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    handle = _walk_style_handles.get(sim.id)
    if handle is not None:
        handle.release()
        del _walk_style_handles[sim.id]

@sims4.commands.Command('sims.list_walkstyles')
def list_walkstyles(_connection=None):
    sims4.commands.output('Available walkstyles:', _connection)
    for style in WalkStyle:
        sims4.commands.output('    {}'.format(style.name.lower()), _connection)
    return True

@sims4.commands.Command('sims.set_focus')
def set_focus(record_id, targetID:int=0, x:float=0.0, y:float=0.0, z:float=0.0, layer:int=1, score:float=1.0, targetBoneName='', flags:int=0, blocking:int=0, opt_sim:OptionalTargetParam=None, _connection=None):
    if targetID == 0 and (x == 0 and y == 0) and z == 0:
        sims4.commands.output('SET_FOCUS: No focus to set.', _connection)
    sim = get_optional_target(opt_sim, _connection)
    target = 0
    if targetID != 0:
        manager = services.object_manager()
        if targetID in manager:
            target = targetID
        else:
            sims4.log.warn('SimInfo', 'SET_FOCUS: Ignoring invalid Object ID.')
    bone = 0
    if targetBoneName != '':
        if targetID == 0:
            sims4.log.warn('SimInfo', 'SET_FOCUS: Ignoring bone ID without valid Object ID.')
        else:
            bone = sims4.hash_util.hash32(targetBoneName)
    offset = sims4.math.Vector3(x, y, z)
    if record_id < 0:
        record_id = 0
    if layer < 0:
        layer = 0
    interactions.utils.sim_focus.FocusAdd(sim, record_id, layer, score, sim.id, target, bone, offset, blocking, None, None, flags)

@sims4.commands.Command('sims.delete_focus')
def delete_focus(record_id, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    interactions.utils.sim_focus.FocusDelete(sim, sim.id, record_id, False)

@sims4.commands.Command('sims.clear_focus')
def clear_focus(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    interactions.utils.sim_focus.FocusClear(sim, sim.id, False)

@sims4.commands.Command('sims.modify_focus_score')
def modify_focus_score(record_id, score, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    interactions.utils.sim_focus.FocusModifyScore(sim, sim.id, record_id, score, False)

@sims4.commands.Command('sims.disable_focus')
def disable_focus(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    interactions.utils.sim_focus.FocusDisable(sim, True, False)

@sims4.commands.Command('sims.enable_focus')
def enable_focus(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    interactions.utils.sim_focus.FocusDisable(sim, False, False)

@sims4.commands.Command('sims.force_focus_update')
def force_focus_update(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    interactions.utils.sim_focus.FocusForceUpdate(sim, sim.id, False)

@sims4.commands.Command('sims.print_focus')
def print_focus(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    interactions.utils.sim_focus.FocusPrint(sim, sim.id)

@sims4.commands.Command('sims.print_focus_server')
def print_focus_server(opt_sim:OptionalTargetParam=None, _connection=None):
    interactions.utils.sim_focus.FocusPrintAll(_connection)

@sims4.commands.Command('sims.log_focus_to_console_toggle')
def log_focus_to_console_toggle(opt_sim:OptionalTargetParam=None, _connection=None):
    interactions.utils.sim_focus.log_to_cheat_console(_connection)

@sims4.commands.Command('sims.test_focus')
def test_focus(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    pos1 = sim.position + sims4.math.Vector3(2.0, 2, 0)
    pos2 = sim.position + sims4.math.Vector3(-2.0, 2, 0)
    pos3 = sim.position + sims4.math.Vector3(0, 2, 2.0)
    pos4 = sim.position + sims4.math.Vector3(0, 2, -2.0)
    set_focus(record_id=1, targetID=0, x=pos1.x, y=pos1.y, z=pos1.z, sim_id=sim.id, _connection=_connection)
    set_focus(record_id=2, targetID=0, x=pos2.x, y=pos2.y, z=pos2.z, sim_id=sim.id, _connection=_connection)
    set_focus(record_id=3, targetID=0, x=pos3.x, y=pos3.y, z=pos3.z, sim_id=sim.id, _connection=_connection)
    set_focus(record_id=4, targetID=0, x=pos4.x, y=pos4.y, z=pos4.z, sim_id=sim.id, _connection=_connection)

@sims4.commands.Command('sims.set_focus_compatibility')
def set_focus_compatibility(level:int=0, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        op = distributor.ops.SetFocusCompatibility(level)
        distributor.ops.record(sim, op)

@sims4.commands.Command('sims.facial_overlay_refresh')
def facial_overlay_refresh(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('Invalid Sim id: {}'.format(opt_sim), _connection)
        return False
    sim._update_facial_overlay()

@sims4.commands.Command('sims.show_buffs', command_type=sims4.commands.CommandType.Automation)
def show_buffs(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('Invalid Sim id: {}'.format(opt_sim), _connection)
        return False
    sims4.commands.automation_output('BuffsInfo; Status:Begin', _connection)
    sims4.commands.output('Buffs: ', _connection)
    for buff_entry in sim.Buffs:
        s = ' {}'.format(buff_entry.__class__.__name__)
        sims4.commands.output(s, _connection)
        sims4.commands.automation_output('BuffsInfo; Status:Data, Value:{}'.format(buff_entry.__class__.__name__), _connection)
    sims4.commands.automation_output('BuffsInfo; Status:End', _connection)

@sims4.commands.Command('sims.add_buff', command_type=sims4.commands.CommandType.Automation)
def add_buff(buff_type, opt_target:OptionalTargetParam=None, _connection=None):
    target = get_optional_target(opt_target, _connection)
    if target is None:
        return False
    if target.debug_add_buff_by_type(buff_type):
        sims4.commands.output('({0}) has been added.'.format(buff_type), _connection)
        return True
    sims4.commands.output('({0}) has NOT been added.'.format(buff_type), _connection)
    return False

@sims4.commands.Command('sims.remove_buff', 'removeBuff', command_type=sims4.commands.CommandType.Cheat)
def remove_buff(buff_type, opt_target:OptionalTargetParam=None, _connection=None):
    target = get_optional_target(opt_target, _connection)
    if target is None:
        return False
    if target.has_buff(buff_type):
        target.remove_buff_by_type(buff_type)
        sims4.commands.output('({0}) has been removed.'.format(buff_type), _connection)
    else:
        sims4.commands.output('({0}) does not exist on sim.'.format(buff_type), _connection)

@sims4.commands.Command('sims.remove_buff_from_all')
def remove_buff_from_all(buff_type, _connection=None):
    output = sims4.commands.Output(_connection)
    for sim_info in services.sim_info_manager().values():
        sim = sim_info.get_sim_instance()
        while sim is not None:
            if sim.has_buff(buff_type):
                sim.remove_buff_by_type(buff_type)
                output('{} has been removed from {}.'.format(buff_type, sim.full_name))

@sims4.commands.Command('sims.remove_all_buffs', command_type=sims4.commands.CommandType.Automation)
def remove_all_buffs(opt_target:OptionalTargetParam=None, _connection=None):
    target = get_optional_target(opt_target, _connection)
    if target is None:
        return False
    for buff_type in services.buff_manager().types.values():
        while target.has_buff(buff_type):
            if buff_type.commodity is not None:
                tracker = target.get_tracker(buff_type.commodity)
                commodity_inst = tracker.get_statistic(buff_type.commodity)
                if commodity_inst.core:
                    pass
            target.remove_buff_by_type(buff_type)
            sims4.commands.output('({0}) has been removed.'.format(buff_type.__name__), _connection)

@sims4.commands.Command('sims.reminisce_about_memory', command_type=sims4.commands.CommandType.Live)
def reminisce_about_memory(memory_id:int=0, opt_sim:OptionalTargetParam=None, _connection=None):
    if opt_sim is None:
        sims4.commands.output('Invalid Sim id: {}'.format(opt_sim), _connection)
        return False
    opt_target = RequiredTargetParam(str(opt_sim.target_id))
    memory_uids = buffs.memory.MemoryUid
    if memory_id == memory_uids.Invalid:
        sims4.commands.output('Invalid Memory Uid: {}'.format(memory_id), _connection)
        return False
    reminisce_affordance_tuple = buffs.memory.Memory.MEMORIES.get(memory_id, None)
    if reminisce_affordance_tuple is not None:
        reminisce_affordance = reminisce_affordance_tuple.reminisce_affordance
    else:
        sims4.commands.output('Memory Uid not in Memories Tuning: {}'.format(memory_id), _connection)
        return False
    if reminisce_affordance is not None:
        return server_commands.interaction_commands.push_interaction(affordance=reminisce_affordance, opt_target=opt_target, opt_sim=opt_sim, _connection=_connection)

def push_travel_affordance(opt_sim:OptionalTargetParam=None, lot_id:int=0, world_id:int=0, lot_name:str='', friend_account:str='', _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('Invalid Sim id: {}'.format(opt_sim), _connection)
        return False
    client = services.client_manager().get(_connection)
    context = InteractionContext(sim, InteractionContext.SOURCE_PIE_MENU, Priority.High, client=client, pick=None)
    result = sim.push_super_affordance(super_affordance=TravelSuperInteraction, target=sim, context=context, to_zone_id=lot_id, world_id=world_id, lot_name=lot_name, friend_account=friend_account)
    if not result:
        output = sims4.commands.Output(_connection)
        output('Failed to push: {}'.format(result))
        return False
    return True

@sims4.commands.Command('sims.travel_to_specific_location', command_type=sims4.commands.CommandType.Live)
def travel_to_specific_location(opt_sim:OptionalTargetParam=None, lot_id:int=0, world_id:int=0, lot_name:str='', _connection=None):
    return push_travel_affordance(opt_sim=opt_sim, lot_id=lot_id, world_id=world_id, lot_name=lot_name, _connection=_connection)

@sims4.commands.Command('sims.travel_to_friend', command_type=sims4.commands.CommandType.Live)
def travel_to_friend_location(opt_sim:OptionalTargetParam=None, friend_account:str='', _connection=None):
    return push_travel_affordance(opt_sim=opt_sim, friend_account=friend_account, _connection=_connection)

@sims4.commands.Command('sims.visit_target_sim', command_type=sims4.commands.CommandType.Live)
def visit_target_sim(opt_target:RequiredTargetParam=None, opt_sim:OptionalTargetParam=None, _connection=None):
    sim_mgr = services.sim_info_manager()
    target_info = sim_mgr.get(opt_target.target_id)
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('Invalid Sim id: {}'.format(opt_sim), _connection)
        return False
    if target_info.zone_id == 0:
        sims4.commands.output('Invalid destination zone id: {}'.format(target_info.zone_id), _connection)
        return False
    op = distributor.ops.TravelSwitchToZone([sim.id, sim.household_id, target_info.zone_id, target_info.world_id])
    distributor.ops.record(sim, op)
    return True

@sims4.commands.Command('sims.travel_to_target_sim', command_type=sims4.commands.CommandType.Live)
def travel_to_target_sim(opt_target:RequiredTargetParam=None, opt_sim:OptionalTargetParam=None, _connection=None):
    sim_mgr = services.sim_info_manager()
    target_info = sim_mgr.get(opt_target.target_id)
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('Invalid Sim id: {}'.format(opt_sim), _connection)
        return False
    if target_info.zone_id == 0:
        sims4.commands.output('Invalid destination zone id: {}'.format(target_info.zone_id), _connection)
        return False
    op = distributor.ops.TravelSwitchToZone([target_info.sim_id, target_info.household_id, target_info.zone_id, target_info.world_id])
    distributor.ops.record(sim, op)
    return True

@sims4.commands.Command('sims.summon_sim_to_zone', command_type=sims4.commands.CommandType.Live)
def summon_sim_to_zone(opt_target:RequiredTargetParam=None, opt_sim:OptionalTargetParam=None, _connection=None):
    sim_mgr = services.sim_info_manager()
    target_info = sim_mgr.get(opt_target.target_id)
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('Invalid Sim id: {}'.format(opt_sim), _connection)
        return False
    if opt_target is not None:
        sims.sim_spawner.SimSpawner.load_sim(target_info.sim_id)
        return True

@sims4.commands.Command('sims.start_effect')
def start_effect(effect_name='thoughtBalloonThumbnailNeutralFx', bone_name='b__head__', height_offset:float=0.25, texture_override_index:int=2, texture_name='moon', opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        op = distributor.ops.StartEffect(effect_name, bone_name, sims4.math.Vector3(0, height_offset, 0), texture_override_index, sims4.resources.Key.hash64(texture_name, 11786151, 0))
        distributor.ops.record(sim, op)

@sims4.commands.Command('sims.stop_effect')
def stop_effect(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        op = distributor.ops.StopEffect()
        distributor.ops.record(sim, op)

@sims4.commands.Command('sims.teleport', command_type=sims4.commands.CommandType.Automation)
def teleport(x:float=0.0, y:float=0.0, z:float=0.0, level:int=0, opt_sim:OptionalTargetParam=None, rotation:float=0, _connection=None):
    if x == 0 and y == 0 and z == 0:
        sims4.commands.output('teleport: no destination set.', _connection)
        return False
    sim = get_optional_target(opt_sim, _connection)
    orientation = sims4.math.angle_to_yaw_quaternion(rotation)
    pos = sims4.math.Vector3(x, y, z)
    routing_surface = routing.SurfaceIdentifier(sims4.zone_utils.get_zone_id(), level, routing.SURFACETYPE_WORLD)
    location = sims4.math.Location(sims4.math.Transform(pos, orientation), routing_surface)
    target = objects.terrain.TerrainPoint(location)
    pick = PickInfo(PickType.PICK_TERRAIN, target, pos, routing_surface=routing_surface)
    context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT, interactions.priority.Priority.High, pick=pick)
    sim.push_super_affordance(CommandTuning.TERRAIN_TELEPORT_AFFORDANCE, target, context)

@sims4.commands.Command('sims.teleport_instantly', command_type=sims4.commands.CommandType.Automation)
def teleport_instantly(x:float=0.0, y:float=0.0, z:float=0.0, level:int=0, opt_sim:OptionalTargetParam=None, rotation:float=0, _connection=None):
    if x == 0 and y == 0 and z == 0:
        sims4.commands.output('teleport: no destination set.', _connection)
        return False
    sim = get_optional_target(opt_sim, _connection)
    orientation = sims4.math.angle_to_yaw_quaternion(rotation)
    pos = sims4.math.Vector3(x, y, z)
    routing_surface = routing.SurfaceIdentifier(sims4.zone_utils.get_zone_id(), level, routing.SURFACETYPE_WORLD)
    location = sims4.math.Location(sims4.math.Transform(pos, orientation), routing_surface)
    sim.location = location

@sims4.commands.Command('sims.route_instantly')
def route_instantly(value:bool=False, _connection=None):
    Zone.force_route_instantly = value

@sims4.commands.Command('sims.resatisfy_constraint')
def resatisfy_constraint(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        affordance = SatisfyConstraintSuperInteraction
        aop = AffordanceObjectPair(affordance, None, affordance, None)
        context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT, priority.Priority.High)
        aop.test_and_execute(context)

@sims4.commands.Command('sims.age_max_progress')
def age_max_progress(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.sim_info.advance_age_progress(sim.sim_info.time_until_age_up)
        return True
    return False

@sims4.commands.Command('sims.age_add_progress')
def add_age_progress(amount_to_add:float=1.0, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.sim_info.advance_age_progress(amount_to_add)
        return True
    return False

@sims4.commands.Command('sims.age_up')
def advance_to_next_age(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('Sim not found.', _connection)
        return False
    target = None
    affordance = 'AgeUpInteraction'
    client = services.client_manager().get(_connection)
    priority = Priority.High
    context = InteractionContext(sim, InteractionContext.SOURCE_PIE_MENU, priority, client=client, pick=None)
    result = sim.push_super_affordance(affordance, target, context)
    return result

@sims4.commands.Command('sims.phase_up')
def advance_to_next_phase(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('Sim not found.', _connection)
        return False
    if sim is not None:
        sim.sim_info.advance_age_phase()
    return True

@sims4.commands.Command('sims.set_age_speed_option', command_type=sims4.commands.CommandType.Live)
def set_age_speed_option(speed, _connection=None):
    if speed is None or speed < 0 or speed > 2:
        sims4.commands.output('Invalid speed setting, valid speeds are 0, 1, or 2.', _connection)
        return False
    sims4.commands.output('Speed setting changed to speed {}'.format(speed), _connection)
    services.get_age_service().set_aging_speed(speed)

@sims4.commands.Command('sims.request_age_progress_update', command_type=sims4.commands.CommandType.Live)
def request_age_progress_update(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.sim_info.resend_age_progress()
        return True
    return False

@sims4.commands.Command('sims.set_aging_enabled_option', command_type=sims4.commands.CommandType.Live)
def set_aging_enabled_option(enabled, _connection=None):
    sims4.commands.output('Auto aging for played household set to: {}'.format(enabled), _connection)
    services.get_age_service().set_aging_enabled(enabled)

@sims4.commands.Command('sims.set_npc_repopulation', command_type=sims4.commands.CommandType.Live)
def set_npc_repopulation(disabled, _connection=None):
    current_zone = services.current_zone()
    if current_zone is None:
        return False
    story_progression_service = current_zone.story_progression_service
    if story_progression_service is None:
        return False
    if disabled is None:
        disabled = not story_progression_service.is_story_progression_flag_enabled(story_progression.StoryProgressionFlags.ALLOW_POPULATION_ACTION)
    if not disabled:
        story_progression_service.enable_story_progression_flag(story_progression.StoryProgressionFlags.ALLOW_POPULATION_ACTION)
        sims4.commands.output('Population action has been enabled', _connection)
    else:
        story_progression_service.disable_story_progression_flag(story_progression.StoryProgressionFlags.ALLOW_POPULATION_ACTION)
        sims4.commands.output('Population action has been disabled', _connection)
    return True

@sims4.commands.Command('sims.set_aging_unplayed_sims', command_type=sims4.commands.CommandType.Live)
def set_aging_unplayed_sims(enabled, _connection=None):
    sims4.commands.output('Auto aging for unplayed household toggled to: {}'.format(enabled), _connection)
    services.get_age_service().set_unplayed_aging_enabled(enabled)

@sims4.commands.Command('sims.whims_award_prize', command_type=sims4.commands.CommandType.Live)
def whims_award_prize(prizeType:int=0, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.sim_info.whim_tracker.purchase_whim_award(prizeType)
        sim.sim_info.whim_tracker.send_satisfaction_reward_list()
        return True
    return False

@sims4.commands.Command('sims.request_satisfaction_reward_list', command_type=sims4.commands.CommandType.Live)
def request_satisfaction_reward_list(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.sim_info.whim_tracker.send_satisfaction_reward_list()
        return True
    return False

@sims4.commands.Command('sims.regenerate_whims', command_type=sims4.commands.CommandType.Live)
def regenerate_whims(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.sim_info.whim_tracker.refresh_goals()
        return True
    return False

@sims4.commands.Command('sims.whims_dismiss', command_type=sims4.commands.CommandType.Live)
def whims_dismiss(whim_guid64:int=0, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.sim_info.whim_tracker.dismiss_whim(whim_guid64)
        return True
    return False

@sims4.commands.Command('sims.whims_activate_set', command_type=sims4.commands.CommandType.Live)
def whims_activate_set(whimset, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.sim_info.whim_tracker.force_whimset(whimset)
        return True
    return False

@sims4.commands.Command('sims.whims_give_whim_from_set', command_type=sims4.commands.CommandType.Live)
def whims_give_from_whimset(whimset, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.sim_info.whim_tracker.force_whim_from_whimset(whimset)
        return True
    return False

@sims4.commands.Command('sims.whims_give_whim', command_type=sims4.commands.CommandType.Live)
def whims_give_whim(whim, target_simId:int=0, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    target_sim = None
    if target_simId > 0:
        target_sim_info = services.sim_info_manager().get(target_simId)
        target_sim = target_sim_info.get_sim_instance() if target_sim_info is not None else None
    if sim is not None:
        sim.sim_info.whim_tracker.force_whim(whim, target_sim)
        return True
    return False

@sims4.commands.Command('sims.whims_complete_whim', command_type=sims4.commands.CommandType.Live)
def whims_complete_whim(whim, opt_sim:OptionalTargetParam=None, target_simId:int=0, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    target_sim = None
    if target_simId > 0:
        target_sim_info = services.sim_info_manager().get(target_simId)
        target_sim = target_sim_info.get_sim_instance() if target_sim_info is not None else None
    if sim is not None:
        sim.sim_info.whim_tracker.force_whim_complete(whim, target_sim)
        return True
    return False

@sims4.commands.Command('sims.whims_give_bucks', command_type=sims4.commands.CommandType.DebugOnly)
def whims_give_bucks(whim_bucks:int=0, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.sim_info.add_whim_bucks(whim_bucks, SetWhimBucks.COMMAND)
        return True
    return False

@sims4.commands.Command('sims.reset', command_type=sims4.commands.CommandType.Automation)
def reset(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.reset(ResetReason.RESET_EXPECTED, None, 'Command')
        return True
    return False

@sims4.commands.Command('resetsim', command_type=sims4.commands.CommandType.Live)
def reset_sim(first_name='', last_name='', _connection=None):
    info = services.sim_info_manager().get_sim_info_by_name(first_name, last_name)
    if info is not None:
        sim = info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if sim is not None:
            sim.reset(ResetReason.RESET_EXPECTED, None, 'Command')
            return True
    output = sims4.commands.CheatOutput(_connection)
    output('Sim not found')
    return False

@sims4.commands.Command('sims.get_sim_id_by_name', command_type=sims4.commands.CommandType.Live)
def get_sim_id_by_name(first_name='', last_name='', _connection=None):
    info = services.sim_info_manager().get_sim_info_by_name(first_name, last_name)
    if info is not None:
        output = sims4.commands.CheatOutput(_connection)
        output('{} has sim id: {}'.format(info, info.id))
        return True
    output = sims4.commands.CheatOutput(_connection)
    output('Sim not found')
    return False

@sims4.commands.Command('sims.reset_multiple')
def reset_sims(*obj_ids, _connection=None):
    for obj_id in obj_ids:
        sim = services.object_manager().get(obj_id)
        while sim is not None:
            sim.reset(ResetReason.RESET_EXPECTED, None, 'Command')
    return True

@sims4.commands.Command('sims.reset_all')
def reset_all_sims(_connection=None):
    sims = services.sim_info_manager().instanced_sims_gen(allow_hidden_flags=ALL_HIDDEN_REASONS)
    services.get_reset_and_delete_service().trigger_batch_reset(sims)
    return True

@sims4.commands.Command('sims.delete_sim_info_by_full_name', command_type=sims4.commands.CommandType.DebugOnly)
def delete_sim_info_by_full_name(first_name='', last_name='', _connection=None):
    info = services.sim_info_manager().get_sim_info_by_name(first_name, last_name)
    output = sims4.commands.CheatOutput(_connection)
    if info is not None:
        services.sim_info_manager().remove_permanently(info)
        output('Sim {} has had its SimInfo permanently deleted.'.format(info.full_name))
        return True
    output('Sim {} {} could not be found in the sim_info_manager.'.format(first_name, last_name))
    return False

@sims4.commands.Command('sims.interrupt')
def interrupt(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.reset(ResetReason.RESET_EXPECTED, None, 'Command')
        return True
    return False

@sims4.commands.Command('sims.gohere')
def gohere(x:float=0.0, y:float=0.0, z:float=0.0, level:int=0, start_x:float=0.0, start_y:float=0.0, start_z:float=0.0, start_level:int=0, opt_sim:OptionalTargetParam=None, _connection=None):
    if x == 0 and y == 0 and z == 0:
        sims4.commands.output('gohere: no destination set.', _connection)
        return False
    sim = get_optional_target(opt_sim, _connection)
    if start_x != 0 and start_z != 0:
        teleport(start_x, start_y, start_z, start_level, opt_sim, _connection=_connection)
    pos = sims4.math.Vector3(x, y, z)
    routing_surface = routing.SurfaceIdentifier(sims4.zone_utils.get_zone_id(), level, routing.SURFACETYPE_WORLD)
    location = sims4.math.Location(sims4.math.Transform(pos), routing_surface)
    target = objects.terrain.TerrainPoint(location)
    target.create_for_position_and_orientation(pos, routing_surface)
    pick = PickInfo(PickType.PICK_TERRAIN, target, pos, routing_surface)
    context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT, interactions.priority.Priority.High, pick=pick, group_id=1)
    sim.push_super_affordance(CommandTuning.TERRAIN_GOHERE_AFFORDANCE, target, context)

@sims4.commands.Command('sims.allgohere')
def all_gohere(x:float=0.0, y:float=0.0, z:float=0.0, level:int=0, start_x:float=0.0, start_y:float=0.0, start_z:float=0.0, start_level:int=0, opt_sim:OptionalTargetParam=None, _connection=None):
    for sim_info in services.sim_info_manager().objects:
        sim = sim_info.get_sim_instance()
        while sim is not None:
            gohere(x=x, y=y, z=z, level=level, start_x=start_x, start_y=start_y, start_z=start_z, start_level=start_level, opt_sim=OptionalTargetParam(str(sim.id)), _connection=_connection)

@sims4.commands.Command('sims.test_avoidance')
def test_avoidance(x:float=0.0, y:float=0.0, z:float=0.0, radius:float=5.0, level=0, opt_sim:OptionalTargetParam=None, _connection=None):
    num_sims = 0
    for sim_info in services.sim_info_manager().objects:
        while sim_info.is_instanced():
            num_sims += 1
    i = 0
    for sim_info in services.sim_info_manager().objects:
        while sim_info.is_instanced():
            sim = sim_info.get_sim_instance()
            x_end = x - math.cos(i*2.0*math.pi/num_sims)*radius
            y_end = y
            z_end = z - math.sin(i*2.0*math.pi/num_sims)*radius
            gohere(x_end, y_end, z_end, level, 0.0, 0.0, 0.0, 0, OptionalTargetParam(str(sim.id)), _connection=_connection)
            i += 1

@sims4.commands.Command('sims.path_test')
def path_test(_connection=None):
    client = services.client_manager().get(_connection)
    sim = client.active_sim
    xform = sim.transform
    translate = xform.translation
    orientation = xform.orientation
    routing_surface = sim.routing_surface
    path = routing.path_wrapper()
    path.origin = routing.Location(translate, orientation, routing_surface)
    path.context.agent_id = sim.sim_id
    goal_pos = sims4.math.Vector3(0.0, 0.0, 0.0)
    goal_orientation = sims4.math.Quaternion(0.0, 0.0, 0.0, 1.0)
    path.add_goal(routing.Location(goal_pos, goal_orientation, routing_surface), 1.0, 0)
    goal_pos = sims4.math.Vector3(50000.0, 0.0, 0.0)
    path.add_goal(routing.Location(goal_pos, goal_orientation, routing_surface), 1.0, 1)
    goal_pos = sims4.math.Vector3(200.0, 100.0, 100.0)
    path.add_goal(routing.Location(goal_pos, goal_orientation, routing_surface), 1.0, 2)
    path.make_path()
    time.sleep(15)
    goal_results = path.goal_results()
    sims4.commands.output('Results:', _connection)
    for result in goal_results:
        sims4.commands.output('Found a goal: {0} :: {1} :: {2}'.format(result[0], result[1], result[2]), _connection)

@sims4.commands.Command('sims.set_thumbnail')
def set_thumbnail(thumbnail, sim_id:int=None, _connection=None):
    if sim_id is not None:
        sim = services.object_manager().get(sim_id)
    else:
        client = services.client_manager().get(_connection)
        sim = client.active_sim
    if sim is not None:
        key = sims4.resources.Key.hash64(thumbnail, sims4.resources.Types.PNG)
        sims4.commands.output('Thumbnail changed from {} to {}'.format(sim.thumbnail, key), _connection)
        sim.thumbnail = key
        return True
    sims4.commands.output('Unable to find Sim.', _connection)
    return False

@sims4.commands.Command('sims.clear_all_stats')
def clear_all_stats(opt_sim:OptionalTargetParam=None, _connection=None):
    from server_commands import statistic_commands, relationship_commands
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('Invalid Sim id: {}'.format(opt_sim), _connection)
        return False
    statistic_commands.clear_skill(opt_sim, _connection=_connection)
    relationship_commands.clear_relationships(opt_sim, _connection=_connection)
    sim.commodity_tracker.debug_set_all_to_default()
    sim.statistic_tracker.debug_set_all_to_default()
    return True

@sims4.commands.Command('sims.fill_all_commodities', command_type=sims4.commands.CommandType.Automation)
def fill_commodities(core_only:bool=True, _connection=None):
    for sim_info in services.sim_info_manager().objects:
        sim_info.commodity_tracker.set_all_commodities_to_max(core_only=core_only)

@sims4.commands.Command('rosebud', 'kaching', command_type=sims4.commands.CommandType.Live)
def rosebud(_connection=None):
    tgt_client = services.client_manager().get(_connection)
    modify_fund_helper(1000, Consts_pb2.TELEMETRY_MONEY_CHEAT, tgt_client.active_sim)

@sims4.commands.Command('motherlode', command_type=sims4.commands.CommandType.Live)
def motherlode(_connection=None):
    tgt_client = services.client_manager().get(_connection)
    modify_fund_helper(50000, Consts_pb2.TELEMETRY_MONEY_CHEAT, tgt_client.active_sim)

@sims4.commands.Command('money', command_type=sims4.commands.CommandType.Cheat)
def set_money(amount, sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(sim, _connection)
    if sim is not None:
        current_amount = sim.family_funds.money
        modify_fund_helper(amount - current_amount, Consts_pb2.TELEMETRY_MONEY_CHEAT, sim)
        return True
    return False

@sims4.commands.Command('sims.modify_funds', command_type=sims4.commands.CommandType.Automation)
def modify_funds(amount, reason=None, opt_sim:OptionalTargetParam=None, _connection=None):
    if reason is None:
        reason = Consts_pb2.TELEMETRY_MONEY_CHEAT
    sim = get_optional_target(opt_sim, _connection)
    modify_fund_helper(amount, reason, sim)

def modify_fund_helper(amount, reason, sim):
    if amount > 0:
        sim.family_funds.add(amount, reason, sim)
    else:
        sim.family_funds.remove(-amount, reason, sim)

@sims4.commands.Command('sims.hard_reset', command_type=sims4.commands.CommandType.Automation)
def hard_reset(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.reset(ResetReason.RESET_EXPECTED, None, 'Command')
        return True
    return False

@sims4.commands.Command('sims.test_ignore_footprint')
def test_ignore_footprint(footprint_cost:int=100000, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        poly = build_rectangle_from_two_points_and_radius(sims4.math.Vector3.Z_AXIS() + sim.location.transform.translation, sim.location.transform.translation, 1.0)
        sim.test_footprint = PolygonFootprint(poly, routing_surface=sim.routing_surface, cost=footprint_cost, footprint_type=6, enabled=True)
        sim.routing_context.ignore_footprint_contour(sim.test_footprint.footprint_id)
        return True
    return False

@sims4.commands.Command('sims.test_polygonal_connectivity_handle')
def test_polygonal_connectivity_handle(x:float=0.0, y:float=0.0, z:float=0.0, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        pt = sims4.math.Vector3(x, y, z)
        poly = build_rectangle_from_two_points_and_radius(sims4.math.Vector3.Z_AXIS()*2 + sims4.math.Vector3.X_AXIS()*2 + pt, pt, 2.0)
        routing_surface = routing.SurfaceIdentifier(sims4.zone_utils.get_zone_id(), 0, routing.SURFACETYPE_WORLD)
        handle = routing.connectivity.Handle(poly, routing_surface)
        if routing.test_connectivity_permissions_for_handle(handle, sim.routing_context):
            sims4.commands.output('Connectivity Group: {0} - ALLOWED'.format(handle.connectivity_groups), _connection)
        else:
            sims4.commands.output('Connectivity Group: {0} - NOT ALLOWED'.format(handle.connectivity_groups), _connection)
        return True
    return False

@sims4.commands.Command('sims.test_connectivity_permissions')
def test_connectivity_permissions(x:float=0.0, y:float=0.0, z:float=0.0, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        pt = sims4.math.Vector3(x, y, z)
        routing_surface = routing.SurfaceIdentifier(sims4.zone_utils.get_zone_id(), 0, routing.SURFACETYPE_WORLD)
        loc = routing.Location(pt, sims4.math.Quaternion.ZERO(), routing_surface)
        handle = routing.connectivity.Handle(loc)
        if routing.test_connectivity_permissions_for_handle(handle, sim.routing_context):
            sims4.commands.output('Connectivity Group: {0}/{1} - ALLOWED'.format(handle.connectivity_groups, handle.connectivity_groups_lite), _connection)
        else:
            sims4.commands.output('Connectivity Group: {0}/{1} - NOT ALLOWED'.format(handle.connectivity_groups, handle.connectivity_groups_lite), _connection)
        return True
    return False

@sims4.commands.Command('sims.test_connectivity_pt_pt')
def test_connectivity_pt_pt(a_x:float=0.0, a_y:float=0.0, a_z:float=0.0, b_x:float=0.0, b_y:float=0.0, b_z:float=0.0, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        a = sims4.math.Vector3(a_x, a_y, a_z)
        b = sims4.math.Vector3(b_x, b_y, b_z)
        routing_surface = routing.SurfaceIdentifier(sims4.zone_utils.get_zone_id(), 0, routing.SURFACETYPE_WORLD)
        locA = routing.Location(a, sims4.math.Quaternion.ZERO(), routing_surface)
        locB = routing.Location(b, sims4.math.Quaternion.ZERO(), routing_surface)
        if routing.test_connectivity_pt_pt(locA, locB, sim.routing_context):
            sims4.commands.output('Points are CONNECTED', _connection)
        else:
            sims4.commands.output('Points are DISCONNECTED', _connection)
        return True
    return False

@sims4.commands.Command('sims.test_raytest')
def test_raytest(x1:float=0.0, y1:float=0.0, z1:float=0.0, level1:int=0, x2:float=0.0, y2:float=0.0, z2:float=0.0, level2:int=0, ignore_id:int=None, opt_sim:OptionalTargetParam=None, _connection=None):
    pos1 = sims4.math.Vector3(x1, y1, z1)
    routing_surface1 = routing.SurfaceIdentifier(sims4.zone_utils.get_zone_id(), level1, routing.SURFACETYPE_WORLD)
    location1 = routing.Location(pos1, sims4.math.Quaternion.ZERO(), routing_surface1)
    pos2 = sims4.math.Vector3(x2, y2, z2)
    routing_surface2 = routing.SurfaceIdentifier(sims4.zone_utils.get_zone_id(), level2, routing.SURFACETYPE_WORLD)
    location2 = routing.Location(pos2, sims4.math.Quaternion.ZERO(), routing_surface2)
    sim = get_optional_target(opt_sim, _connection)
    obj = objects.system.find_object(ignore_id)
    if obj is not None and obj.routing_context is not None and obj.routing_context.object_footprint_id is not None:
        sim.routing_context.ignore_footprint_contour(obj.routing_context.object_footprint_id)
    sims4.commands.output('test_raytest: returned {0}.'.format(routing.ray_test(location1, location2, sim.routing_context)), _connection)
    if obj is not None and obj.routing_context is not None and obj.routing_context.object_footprint_id is not None:
        sim.routing_context.remove_footprint_contour_override(obj.routing_context.object_footprint_id)

@sims4.commands.Command('sims.planner_build_id')
def planner_id(opt_sim:OptionalTargetParam=None, _connection=None):
    sims4.commands.output('planner_id: returned {0}.'.format(routing.planner_build_id()), _connection)

def _remove_alarm_helper(*args):
    current_zone = services.current_zone()
    if current_zone in _reset_alarm_handles:
        alarms.cancel_alarm(_reset_alarm_handles[current_zone])
        del _reset_alarm_handles[current_zone]
        current_zone.unregister_callback(zone_types.ZoneState.SHUTDOWN_STARTED, _remove_alarm_helper)

@sims4.commands.Command('sims.reset_periodically')
def reset_periodically(enable:bool=True, interval:int=10, reset_type='reset', _connection=None):
    _remove_alarm_helper()
    if not enable:
        return

    def reset_helper(self):
        current_zone = services.current_zone()
        reset_reason = ResetReason.RESET_ON_ERROR
        if reset_type.lower() == 'interrupt':
            reset_reason = ResetReason.RESET_EXPECTED
        elif reset_type.lower() == 'random' and random.randint(0, 1) == 1:
            reset_reason = ResetReason.RESET_EXPECTED
        household_manager = services.household_manager()
        for household in household_manager.get_all():
            for sim in household.instanced_sims_gen():
                sim.reset(reset_reason)
        alarms.cancel_alarm(_reset_alarm_handles[current_zone])
        reset_time_span = clock.interval_in_sim_minutes(random.randint(1, interval))
        _reset_alarm_handles[current_zone] = alarms.add_alarm(reset_periodically, reset_time_span, reset_helper)

    reset_time_span = clock.interval_in_sim_minutes(random.randint(1, interval))
    current_zone = services.current_zone()
    _reset_alarm_handles[current_zone] = alarms.add_alarm(reset_periodically, reset_time_span, reset_helper)
    current_zone.register_callback(zone_types.ZoneState.SHUTDOWN_STARTED, _remove_alarm_helper)

@sims4.commands.Command('sims.reset_random_sim_periodically')
def reset_random_sim_periodically(enable:bool=True, min_interval:int=2, max_interval:int=10, reset_type='reset', _connection=None):
    _remove_alarm_helper()
    if not enable:
        return

    def reset_helper(self):
        current_zone = services.current_zone()
        reset_reason = ResetReason.RESET_ON_ERROR
        if reset_type.lower() == 'expected':
            reset_reason = ResetReason.RESET_EXPECTED
        elif reset_type.lower() == 'random' and random.randint(0, 1) == 1:
            reset_reason = ResetReason.RESET_EXPECTED
        sim_info_manager = services.sim_info_manager()
        all_sims = list(sim_info_manager.instanced_sims_gen())
        sim = all_sims[random.randint(0, len(all_sims) - 1)]
        sim.reset(reset_reason)
        alarms.cancel_alarm(_reset_alarm_handles[current_zone])
        reset_time_span = clock.interval_in_sim_minutes(random.randint(min_interval, max_interval))
        _reset_alarm_handles[current_zone] = alarms.add_alarm(reset_periodically, reset_time_span, reset_helper)

    reset_time_span = clock.interval_in_sim_minutes(random.randint(min_interval, max_interval))
    current_zone = services.current_zone()
    _reset_alarm_handles[current_zone] = alarms.add_alarm(reset_periodically, reset_time_span, reset_helper)
    current_zone.register_callback(zone_types.ZoneState.SHUTDOWN_STARTED, _remove_alarm_helper)

@sims4.commands.Command('sims.changeoutfit', command_type=sims4.commands.CommandType.DebugOnly)
def change_outfit(opt_sim:OptionalTargetParam=None, outfit_category_string='EVERYDAY', outfit_index:int=0, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        category = getattr(OutfitCategory, outfit_category_string.upper(), None)
        if category is not None:
            sim.sim_info.set_current_outfit((category, outfit_index))
        else:
            available_categories = ''
            for category in OutfitCategory:
                available_categories = available_categories + category.name + ', '
            sims4.commands.output('Unrecognized outfit category name. available categories = {}'.format(available_categories), _connection)
        return True
    return False

@sims4.commands.Command('sims.get_buffs_ids_for_outfit')
def get_buffs_ids_for_outfit(opt_sim:OptionalTargetParam=None, outfit_category_string='EVERYDAY', outfit_index:int=0, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        return False
    category = getattr(OutfitCategory, outfit_category_string.upper(), None)
    if category is not None:
        sim.sim_info.set_current_outfit((category, outfit_index))
        part_ids = sim.sim_info.get_part_ids_for_outfit(category, outfit_index)
        sims4.commands.output('parts: {}'.format(part_ids), _connection)
        buff_guids = cas.cas.get_buff_from_part_ids(part_ids)
        if buff_guids:
            for buff_guid in buff_guids:
                buff_type = services.buff_manager().get(buff_guid)
                sims4.commands.output('buff: {}'.format(buff_type), _connection)
        else:
            sims4.commands.output('category: {}, index: {}, has no buffs associated'.format(outfit_category_string, outfit_index), _connection)
    else:
        available_categories = ''
        for category in OutfitCategory:
            available_categories = available_categories + category.name + ', '
        sims4.commands.output('Unrecognized outfit category name. available categories = {}'.format(available_categories), _connection)
    return True

@sims4.commands.Command('sims.set_familial_relationship', command_type=sims4.commands.CommandType.DebugOnly)
def set_familial_relationship(sim_a_id:OptionalTargetParam=None, sim_b_id:int=None, relationship:str=None, _connection=None):
    sim_a = get_optional_target(sim_a_id, _connection)
    if sim_a is None:
        sims4.commands.output('Must specify a sim, or have a sim selected, to set a familial relationship with.', _connection)
        return False
    try:
        relationship = FamilyRelationshipIndex(relationship)
    except Exception:
        available_relations = ''
        for relation in FamilyRelationshipIndex:
            available_relations = available_relations + relation.name + ', '
        sims4.commands.output('Unrecognized genealogy relationship name. available relations = {}'.format(available_relations), _connection)
        return False
    sim_b_info = services.sim_info_manager().get(sim_b_id)
    if sim_b_info is not None:
        sim_a.sim_info.set_and_propagate_family_relation(relationship, sim_b_info)
    else:
        sim_a.sim_info._genealogy_tracker.set_family_relation(relationship, sim_b_id)
    return True

@sims4.commands.Command('sims.set_permission', command_type=sims4.commands.CommandType.DebugOnly)
def set_permission(permission:str=None, enabled:bool=None, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('Must specify a sim or have a sim selected to set a permission.', _connection)
        return False
    category = getattr(SimPermissions.Settings, permission, None)
    if category is None:
        valid_permissions = ''
        for perm in SimPermissions.Settings:
            valid_permissions = valid_permissions + '{}'.format(perm) + ', '
        sims4.commands.output('Unrecognized permission. Valid permissions = {}'.format(valid_permissions), _connection)
        return False
    sim.sim_info._sim_permissions.permissions[category] = enabled
    return True

@sims4.commands.Command('sims.send_gameplay_options_to_client', command_type=sims4.commands.CommandType.Live)
def send_gameplay_options_to_client(get_default:bool=False, _connection=None):
    client = services.client_manager().get(_connection)
    client.account.send_options_to_client(client, get_default)

@sims4.commands.Command('sims.toggle_random_spawning', command_type=sims4.commands.CommandType.DebugOnly)
def toggle_random_spawning(_connection=None):
    sims.sim_spawner.disable_spawning_non_selectable_sims = not sims.sim_spawner.disable_spawning_non_selectable_sims

@sims4.commands.Command('sims.focus_camera_on_sim')
def focus_camera_on_sim(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        return
    client = services.client_manager().get(_connection)
    camera.focus_on_sim(sim, follow=True, client=client)

@sims4.commands.Command('sims.inventory_view_update', command_type=sims4.commands.CommandType.Live)
def inventory_view_update(sim_id:int=0, opt_sim:OptionalTargetParam=None, _connection=None):
    if sim_id > 0:
        sim_info = services.sim_info_manager().get(sim_id)
        sim = sim_info.get_sim_instance()
        if sim is not None:
            sim.inventory_view_update()

@sims4.commands.Command('sims.is_on_current_lot')
def is_on_current_lot(tolerance:float=0, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('No valid sim.', _connection)
        return
    active_lot = services.active_lot()
    if active_lot.is_position_on_lot(sim.position, tolerance):
        sims4.commands.output('TRUE', _connection)
    else:
        sims4.commands.output('FALSE', _connection)

@sims4.commands.Command('sims.debug_apply_away_action')
def debug_apply_away_action(away_action, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('No valid sim.', _connection)
        return
    sim.sim_info.debug_apply_away_action(away_action)

@sims4.commands.Command('sims.debug_apply_default_away_action')
def debug_apply_default_away_action(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('No valid sim.', _connection)
        return
    sim.sim_info.debug_apply_default_away_action()

@sims4.commands.Command('sims.set_initial_adventure_moment_key_override')
def set_initial_adventure_moment_key(initial_adventure_moment_key_name, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        try:
            initial_adventure_moment_key = AdventureMomentKey(initial_adventure_moment_key_name)
            set_initial_adventure_moment_key_override(sim, initial_adventure_moment_key)
        except ValueError:
            sims4.commands.output('{} is not a valid AdventureMomentKey entry'.format(initial_adventure_moment_key_name), _connection)

@sims4.commands.Command('baby.set_enabled_state')
def set_baby_empty_state(is_enabled:bool=True, _connection=None):
    household = services.active_household()
    if household is None:
        return False
    object_manager = services.object_manager()
    for baby_info in household.baby_info_gen():
        bassinet = object_manager.get(baby_info.sim_id)
        while bassinet is not None:
            if is_enabled:
                bassinet.enable_baby_state()
            else:
                bassinet.empty_baby_state()
    return True

@sims4.commands.Command('sims.set_handedness')
def set_handedness(handedness, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        handedness = handedness.lower()
        if handedness.startswith('r'):
            sim.handedness = Hand.RIGHT
        elif handedness.startswith('l'):
            sim.handedness = Hand.LEFT
        else:
            sims4.commands.output("Invalid handedness '{}' specified. Use 'right' or 'left'".format(handedness), _connection)

