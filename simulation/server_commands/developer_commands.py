import os.path
import pickle
from protocolbuffers.Area_pb2 import GSI_Open
from protocolbuffers.Consts_pb2 import MSG_GSI_OPEN
from algos import count_bits
from date_and_time import create_time_span
from relationships.relationship_bit import RelationshipBit
from server_commands.argument_helpers import get_optional_target, RequiredTargetParam, OptionalTargetParam, TunableInstanceParam
from server_commands.relationship_commands import RelationshipCommandTuning
from sims4.gsi import archive
from sims4.gsi.dispatcher import get_all_gsi_schema_names
from sims4.tuning.tunable import TunableList, TunableReference
import areaops
import date_and_time
import gsi_handlers.dump
import paths
import services
import sims.sim_info_types
import sims4.command_script
import sims4.commands
import sims4.gsi.archive
import sims4.gsi.http_service
import sims4.hash_util
import sims4.log
import story_progression
REQUIRED_TIME_BETWEEN_GSI_DUMPS = create_time_span(hours=2)
MAX_NUM_GSI_DUMPS_ON_ERROR_OR_EXCEPTION = 50
with sims4.reload.protected(globals()):
    _developer_mode_enabled = False
    _num_gsi_dumps_on_error_or_exception = 0

@sims4.commands.Command('debug.god_mode', 'debug.common_cheats')
def common_cheats(flags:str='', enable:bool=None, _connection=None):
    global _developer_mode_enabled
    commands = [('', True, 'rr.toggletime 12', None), ('b', True, 'bb.showwipobjects', None), ('r', True, 'routing.toggle_navmesh on', 'routing.toggle_navmesh off'), ('r', True, 'routing.toggle_visualization on', 'routing.toggle_visualization off'), ('', False, 'autonomy.ambient off', 'autonomy.ambient on'), ('', False, 'autonomy.household off', 'autonomy.household on'), ('', False, 'stats.fill_commodities_household', None), ('', False, 'stats.disable_all_commodities', 'stats.enable_all_commodities'), ('c', False, 'crafting.shorten_phases on', 'crafting.shorten_phases off'), ('', False, 'sims.reset_all', None), ('', False, 'death.toggle False', 'death.toggle True'), ('', False, 'fire.toggle_enabled off', 'fire.toggle_enabled on')]
    if flags == '*':
        flags = None
    if enable is None:
        enable = not _developer_mode_enabled
    output = sims4.commands.Output(_connection)
    output('{} developer mode:'.format('Enabling' if enable else 'Disabling'))
    for (cmd_flags, client_cmd, enable_cmd, disable_cmd) in commands:
        if not (flags is not None and cmd_flags and any(f in flags for f in cmd_flags)):
            pass
        command = enable_cmd if enable else disable_cmd
        if not command:
            pass
        if client_cmd:
            output('>' + command)
            sims4.commands.client_cheat(command, _connection)
        else:
            output('>|' + command)
            sims4.commands.execute(command, _connection)
    _developer_mode_enabled = enable
    output('Developer mode {}.'.format('enabled' if enable else 'disabled'))

@sims4.commands.Command('debug.ring_bell_on_exception')
def ring_bell_on_exception(enable:bool=None, _connection=None):
    output = sims4.commands.Output(_connection)
    if enable is None:
        enable = not sims4.log.ring_bell_on_exception
    sims4.log.ring_bell_on_exception = enable
    output('Ring bell on exception {}.'.format('enabled' if enable else 'disabled'))

@sims4.commands.Command('debug.regenerate_line_of_sight')
def regenerate_line_of_sight(_connection=None):
    import time
    logger = sims4.log.Logger('LineOfSightComponent')
    object_list = services.object_manager().valid_objects()
    first_time = time.clock()
    for obj in object_list:
        obj.on_location_changed(obj.position)
    second_time = time.clock()
    final_time = second_time - first_time
    logger.info('Time to regenerate Line of Sight constraints is {0}', final_time)

@sims4.commands.Command('debug.validate_spawn_points')
def debug_validate_spawn_points(_connection=None):
    zone = services.current_zone()
    if zone is not None:
        zone.validate_spawn_points()
        for spawn_point in zone.spawn_points_gen():
            sims4.commands.output('{} valid slots for SpawnPoint {}'.format(count_bits(spawn_point.valid_slots), str(spawn_point)), _connection)

@sims4.commands.Command('debug.set_audio_effect')
def set_audio_effect(target_id:int=None, key_id=None, effect_id=None, _connection=None):
    if target_id is None:
        sims4.commands.output('format "debug.set_audio_effect target_id effect_key effect_id", target_id is None', _connection)
        return False
    if key_id is None:
        sims4.commands.output('format "debug.set_audio_effect target_id effect_key effect_id", key_id is None', _connection)
        return False
    if effect_id is None:
        sims4.commands.output('format "debug.set_audio_effect target_id effect_key effect_id", effect_id is None', _connection)
        return False
    obj = services.object_manager().get(target_id)
    if obj is not None:
        obj.append_audio_effect(key_id, effect_id)
        return True
    sims4.commands.output('debug.set_audio_effect could not find target object', _connection)
    return False

@sims4.commands.Command('http_debug_server.start')
def http_debug_server_start(_connection=None):

    def _on_started(server):
        output = sims4.commands.Output(_connection)
        server_info = server.socket.getsockname()
        output('Debug HTTP Server: http://{}:{}'.format(server_info[0], server_info[1]))

    sims4.gsi.http_service.start_http_server(_on_started)

@sims4.commands.Command('http_debug_server.stop')
def http_debug_server_stop(_connection=None):
    sims4.gsi.http_service.stop_http_server()

@sims4.commands.Command('gsi.list_schemas')
def gsi_list_schemas(*args, _connection=None):
    output = sims4.commands.Output(_connection)
    output('---- All GSI Schema Names ----')
    for (index, schema_name) in enumerate(sorted(get_all_gsi_schema_names())):
        output('{}'.format(schema_name))
    output('---- {} GSI Views printed. ----'.format(index))

@sims4.commands.Command('gsi.start')
def gsi_start(*args, _connection=None):
    output = sims4.commands.Output(_connection)
    tgt_client = services.client_manager().get(_connection)
    if tgt_client is None:
        output('Unable to find client')
        return
    additional_params = []
    number_of_instances = 1
    if args:
        all_gsi_schema_names = get_all_gsi_schema_names()
        valid_args = []
        found_invalid_arg = False
        singleSimMode = False
        for arg in args:
            try:
                number_of_instances = int(arg)
                continue
            except:
                pass
            if arg in all_gsi_schema_names:
                valid_args.append(arg)
            elif arg == 'single_sim':
                singleSimMode = True
            elif isinstance(arg, int):
                number_of_instances = int(arg)
            else:
                found_invalid_arg = True
                output('No GSI View registered for {}'.format(arg))
        if found_invalid_arg:
            output('See |gsi.list_schemas for a list of all registered GSI Schemas.')
        if valid_args:
            additional_params.append('views={}'.format(','.join(valid_args)))
        if singleSimMode:
            additional_params.append('singleSimMode=true')
    additional_params_str = '&'.join(additional_params) if additional_params else ''

    def _on_started(server):
        if server is not None:
            server_info = server.socket.getsockname()
            output('Opening HTTP Server at: http://{}:{}'.format(server_info[0], server_info[1]))
            for _ in range(number_of_instances):
                msg = GSI_Open(ip=server_info[0], port=int(server_info[1]), zone_id=int(tgt_client.zone_id), additional_params=additional_params_str)
                tgt_client.send_message(MSG_GSI_OPEN, msg)
        else:
            logger = sims4.log.Logger('GSI')
            logger.warn('GSI _on_started called but server is None.')

    sims4.gsi.http_service.start_http_server(_on_started)

@sims4.commands.Command('gsi.display_archive_records')
def gsi_print_archive_records(_connection=None):
    archive.print_num_archive_records()

@sims4.commands.Command('gsi.enable_all_logging', command_type=sims4.commands.CommandType.Automation)
def gsi_enable_all_logging(_connection=None):
    sims4.gsi.archive.set_max_archive_records(500)
    sims4.gsi.archive.set_all_archivers_enabled()

@sims4.commands.Command('gsi.disable_all_logging')
def gsi_disable_all_logging(_connection=None):
    sims4.gsi.archive.set_max_archive_records_default()
    sims4.gsi.archive.set_all_archivers_enabled(enable=False)

@sims4.commands.Command('gsi.enable_archivers')
def gsi_enable_archivers(*args, _connection=None):
    for archive_type in args:
        sims4.gsi.archive.set_archive_enabled(archive_type)

@sims4.commands.Command('gsi.set_max_gsi_log_entries', command_type=sims4.commands.CommandType.Automation)
def gsi_set_logging_size(num_entries:int=None, _connection=None):
    sims4.gsi.archive.set_max_archive_records(num_entries)

@sims4.commands.Command('gsi.dump', command_type=sims4.commands.CommandType.Automation)
def gsi_dump(compress:bool=True, location=None, error_str='From Command: |gsi.dump', _connection=None):
    output = sims4.commands.Output(_connection)
    if not location:
        location = paths.APP_ROOT
    if not os.path.isdir(location):
        output('Output location specified ({}) does not exist. Please try a different location.')
        return False
    full_path = gsi_handlers.dump.save_dump_to_location(location, console_output=output, compress_file=compress, error_str=error_str)
    try:
        output('Dump successfully written to {}'.format(full_path))
    except:
        pass
    return True

def force_gsi_dump_on_error_or_exception(_connection=None):
    if sims4.log.callback_on_error_or_exception is not None:
        gsi_dump(_connection, error_str='force_gsi_dump_on_error_or_exception')

@sims4.commands.Command('gsi.gsi_dump_on_error_or_exception', command_type=sims4.commands.CommandType.Automation)
def gsi_dump_on_error_or_exception(_connection=None):
    if sims4.log.callback_on_error_or_exception is None:

        def create_gsi_dump(error_str):
            global _num_gsi_dumps_on_error_or_exception
            _num_gsi_dumps_on_error_or_exception += 1
            if _num_gsi_dumps_on_error_or_exception >= MAX_NUM_GSI_DUMPS_ON_ERROR_OR_EXCEPTION:
                sims4.log.callback_on_error_or_exception = None
            gsi_dump(_connection=_connection, error_str=error_str)

        sims4.log.callback_on_error_or_exception = create_gsi_dump

@sims4.commands.Command('gsi.test')
def gsi_test(location=None, _connection=None):
    output = sims4.commands.Output(_connection)
    data = {}
    schemas = {}
    try:
        gsi_handlers.dump.get_dump(data, schemas, output)
    except:
        sims4.log.exception('GSI', 'Exception while writing a GSI dump:')
        return
    output('Dump finished successfully.')
    output('    {} schemas and {} data entries were built.'.format(len(schemas), len(data)))

@sims4.commands.Command('gsi.save')
def gsi_save(_connection=None):
    output = sims4.commands.Output(_connection)
    data = {}
    schemas = {}
    gsi_handlers.dump.get_dump(data, schemas, output)
    gsi_data = {'data': data, 'schemas': schemas}
    gsistring = pickle.dumps(gsi_data)
    areaops.save_gsi(0, gsistring)
    output('GSI data successfully saved')
    return True

@sims4.commands.Command('gsi.load')
def gsi_load(_connection=None):
    areaops.load_gsi(_connection)
    return True

@sims4.commands.Command('services.list')
def services_list(_connection=None):
    import sims4.service_manager
    output = sims4.commands.Output(_connection)
    svcs = []
    for (name, obj) in vars(services).items():
        while isinstance(obj, sims4.service_manager.Service):
            svcs.append((name, obj))
    svcs.sort(key=lambda t: t[0].strip('_'))
    for (name, _) in svcs:
        output('    {}'.format(name))

@sims4.commands.Command('services.restart')
def services_restart(service_name, _connection=None):
    import sims4.service_manager
    output = sims4.commands.Output(_connection)
    svc = vars(services).get(service_name)
    if isinstance(svc, sims4.service_manager.Service):
        svc.stop()
        svc.setup()
        svc.start()
    else:
        output('Service not found: {}'.format(service_name))

@sims4.commands.Command('commands.runfile')
def commands_runfile(filename, _connection=None):
    sims4.command_script.run_script(filename, _connection=_connection)

@sims4.commands.Command('debug.line_break')
def create_line(num_dashes:int=80, num_lines:int=1, _connection=None):
    logger = sims4.log.Logger('Line Breaker')
    for _ in range(num_lines):
        logger.error('-'*num_dashes)

@sims4.commands.Command('debug.force_c_api_failure')
def force_c_api_failure(percent, _connection=None):
    sims4.utils.c_api_failure_chance = max(min(1, percent), 0)

class CheatWoohooTuning:
    __qualname__ = 'CheatWoohooTuning'
    CHEAT_WOOHOO_BITS = TunableList(TunableReference(manager=services.relationship_bit_manager()))
    CHEAT_WOOHOO_TRACK = TunableReference(manager=services.statistic_manager(), class_restrictions=('RelationshipTrack',))
    CHEAT_WOOHOO_COMMODITY = TunableReference(manager=services.statistic_manager(), class_restrictions=('Commodity',))
    CHEAT_WOOHOO_BUFF = TunableReference(manager=services.buff_manager())
    CHEAT_WOOHOO_SOCIALCONTEXT = TunableReference(manager=services.statistic_manager(), class_restrictions='RelationshipTrack')

def _get_source_and_target(source_sim_id, target_sim_id, output):
    source_sim_info = None
    target_sim_info = None
    if source_sim_id is None or target_sim_id is None:
        output('Please pick source and target sim.')
        return (source_sim_info, target_sim_info)
    source_sim_info = services.sim_info_manager().get(source_sim_id)
    if source_sim_info is None:
        output('Invalid source sim info.')
        return (source_sim_info, target_sim_info)
    target_sim_info = services.sim_info_manager().get(target_sim_id)
    if target_sim_info is None:
        output('Invalid target sim info.')
        return (source_sim_info, target_sim_info)
    return (source_sim_info, target_sim_info)

@sims4.commands.Command('debug.enable_woohoo', command_type=sims4.commands.CommandType.Automation)
def enable_woohoo(source_sim_id, target_sim_id, _connection=None):
    output = sims4.commands.Output(_connection)
    (source_sim_info, target_sim_info) = _get_source_and_target(source_sim_id, target_sim_id, output)
    if source_sim_info is None or target_sim_info is None:
        return False
    if source_sim_info.age <= sims.sim_info_types.Age.TEEN:
        output('Source sim is underage.')
        return False
    if target_sim_info.age <= sims.sim_info_types.Age.TEEN:
        output('Target sim is underage.')
        return False
    for bit in CheatWoohooTuning.CHEAT_WOOHOO_BITS:
        source_sim_info.relationship_tracker.add_relationship_bit(target_sim_id, bit)
        target_sim_info.relationship_tracker.add_relationship_bit(source_sim_id, bit)
    source_sim_info.relationship_tracker.add_relationship_score(target_sim_id, 100, CheatWoohooTuning.CHEAT_WOOHOO_TRACK)
    target_sim_info.relationship_tracker.add_relationship_score(source_sim_id, 100, CheatWoohooTuning.CHEAT_WOOHOO_TRACK)
    source_sim_info.relationship_tracker.add_relationship_score(target_sim_id, 100, CheatWoohooTuning.CHEAT_WOOHOO_SOCIALCONTEXT)
    target_sim_info.relationship_tracker.add_relationship_score(source_sim_id, 100, CheatWoohooTuning.CHEAT_WOOHOO_SOCIALCONTEXT)
    tracker = source_sim_info.get_tracker(CheatWoohooTuning.CHEAT_WOOHOO_COMMODITY)
    tracker.set_value(CheatWoohooTuning.CHEAT_WOOHOO_COMMODITY, 100)
    tracker = target_sim_info.get_tracker(CheatWoohooTuning.CHEAT_WOOHOO_COMMODITY)
    tracker.set_value(CheatWoohooTuning.CHEAT_WOOHOO_COMMODITY, 100)
    source_sim_info.debug_add_buff_by_type(CheatWoohooTuning.CHEAT_WOOHOO_BUFF)
    target_sim_info.debug_add_buff_by_type(CheatWoohooTuning.CHEAT_WOOHOO_BUFF)
    buff = TunableInstanceParam(sims4.resources.Types.BUFF)(12482)
    for sim in (source_sim_info, target_sim_info):
        while sim.has_buff(buff):
            sim.remove_buff_by_type(buff)

class CheatWeddingTuning:
    __qualname__ = 'CheatWeddingTuning'
    CHEAT_ENGAGED_RELATIONSHIP_BITS = TunableList(description='\n        Relationship bits added to the sims that are being cheated into engaged status.\n        ', tunable=RelationshipBit.TunableReference())

@sims4.commands.Command('debug.enable_wedding')
def enable_wedding(source_sim_id, target_sim_id, _connection=None):
    output = sims4.commands.Output(_connection)
    (source_sim_info, target_sim_info) = _get_source_and_target(source_sim_id, target_sim_id, output)
    if source_sim_info is None or target_sim_info is None:
        return False
    source_sim_info.relationship_tracker.add_relationship_score(target_sim_id, RelationshipCommandTuning.INTRODUCE_VALUE, RelationshipCommandTuning.INTRODUCE_TRACK)
    target_sim_info.relationship_tracker.add_relationship_score(source_sim_id, RelationshipCommandTuning.INTRODUCE_VALUE, RelationshipCommandTuning.INTRODUCE_TRACK)
    source_sim_info.relationship_tracker.add_relationship_bit(target_sim_id, RelationshipCommandTuning.INTRODUCE_BIT)
    target_sim_info.relationship_tracker.add_relationship_bit(source_sim_id, RelationshipCommandTuning.INTRODUCE_BIT)
    for bit in CheatWeddingTuning.CHEAT_ENGAGED_RELATIONSHIP_BITS:
        source_sim_info.relationship_tracker.add_relationship_bit(target_sim_id, bit)
        target_sim_info.relationship_tracker.add_relationship_bit(source_sim_id, bit)
    source_sim_info.relationship_tracker.send_relationship_info(target_sim_id)
    target_sim_info.relationship_tracker.send_relationship_info(source_sim_id)

@sims4.commands.Command('debug.move_to_inventory')
def move_to_inventory(target, opt_target:OptionalTargetParam=None, _connection=None):
    get_optional_target(opt_target, _connection).inventory_component.player_try_add_object(target.get_target())

@sims4.commands.Command('designer.test_based_scores')
def dump_test_based_score_info(test_set, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        return False
    si = max(sim.si_state, key=lambda si: (si.is_social, si.priority, si.id))
    output = sims4.commands.Output(_connection)
    output('Generating test scores for {} using resolver {}'.format(sim, si))
    test_set.debug_dump(si.get_resolver(), dump=output)
    return True

@sims4.commands.Command('debug.unhash')
def debug_unhash(hash_value, unhash_db=None, _connection=None):
    FRIENDLY_MAP = {'all': None, 'resource': 1, 'tuning': 2, 'object': 3, 'swarm': 4}
    output = sims4.commands.Output(_connection)
    if unhash_db is None:
        unhash_db_id = unhash_db
        unhash_db = 'all'
    else:
        try:
            unhash_db_id = int(unhash_db, base=0)
        except ValueError:
            unhash_db_id = None
        if unhash_db not in FRIENDLY_MAP:
            output('Unknown db {}.  Options are: {}'.format(unhash_db, ', '.join(sorted(FRIENDLY_MAP))))
            return False
        unhash_db_id = FRIENDLY_MAP[unhash_db]
    try:
        unhashed_value = sims4.hash_util.unhash(hash_value, table_type=unhash_db_id)
    except KeyError:
        unhashed_value = '<not found>'
    output("Unhash of {} ({}) is '{}'".format(hash_value, unhash_db, unhashed_value))
    return True

@sims4.commands.Command('debug.force_neighbors_home')
def force_neighbors_home(_connection=None):
    client = services.client_manager().get_first_client()
    active_household = client.household
    if active_household is not None:
        active_household_home_zone_id = active_household.home_zone_id
        active_household_home_world_id = services.get_persistence_service().get_world_id_from_zone(active_household_home_zone_id)
        send_home = active_household_home_zone_id == services.current_zone().id
        blacklist_until = services.time_service().sim_now + date_and_time.create_time_span(days=7)
        for sim_info in services.sim_info_manager().values():
            if sim_info.is_selectable:
                pass
            sim_info_home_zone_id = sim_info.household.home_zone_id
            sim_info_home_world_id = services.get_persistence_service().get_world_id_from_zone(sim_info_home_zone_id)
            while sim_info_home_world_id == active_household_home_world_id:
                services.get_zone_situation_manager().add_sim_to_auto_fill_blacklist(sim_info.id, blacklist_until=blacklist_until)
                if send_home and sim_info.zone_id != active_household_home_zone_id and sim_info.zone_id != sim_info_home_zone_id:
                    sim_info.inject_into_inactive_zone(sim_info_home_zone_id)

@sims4.commands.Command('debug.toggle_initial_story_progression')
def toggle_initial_story_progression(enable:bool=None, _connection=None):
    current_zone = services.current_zone()
    if current_zone is None:
        return False
    story_progression_service = current_zone.story_progression_service
    if story_progression_service is None:
        return False
    if enable is None:
        enable = not story_progression_service.is_story_progression_flag_enabled(story_progression.StoryProgressionFlags.ALLOW_INITIAL_POPULATION)
    if enable:
        story_progression_service.enable_story_progression_flag(story_progression.StoryProgressionFlags.ALLOW_INITIAL_POPULATION)
        sims4.commands.output('Initial Population has been enabled', _connection)
    else:
        story_progression_service.disable_story_progression_flag(story_progression.StoryProgressionFlags.ALLOW_INITIAL_POPULATION)
        sims4.commands.output('Initial Population has been disabled', _connection)
    return True

@sims4.commands.Command('debug.get_hide_from_lot_picker')
def get_hide_from_lot_picker(_connection=None):
    current_zone = services.current_zone()
    world_desc_id = services.get_world_description_id(current_zone.world_id)
    lot = current_zone.lot
    b = services.get_hide_from_lot_picker(lot.lot_id, world_desc_id)
    output = sims4.commands.Output(_connection)
    output('c_api returned {} for lot {} and world {}'.format(b, lot.lot_id, current_zone.world_id))

