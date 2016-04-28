import native.animation
from sims4.sim_irq_service import yield_zone_id
from sims4.tuning.tunable import Tunable, TunableReference
from sims4.utils import exception_protected, c_api_can_fail
from telemetry_helper import TelemetryTuning
import clock
import paths
import server.account
import services
import sims.sim_spawner
import sims4.core_services
import sims4.geometry
import sims4.gsi.http_service
import sims4.log
import sims4.zone_utils
import telemetry_helper
logger = sims4.log.Logger('AreaServer')
status = sims4.log.Logger('Status')
SYSTEM_HOUSEHOLD_ID = 1
WORLDBUILDER_ZONE_ID = 1
SUCCESS_CODE = 0
EXCEPTION_ERROR_CODE = -1
TIMEOUT_ERROR_CODE = -2
NO_ACCOUNT_ERROR_CODE = -3
NO_CLIENT_ERROR_CODE = -4
NO_HOUSEHOLD_ERROR_CODE = -5
LOADSIMS_FAILED_ERROR_CODE = -6
SIM_NOT_FOUND_ERROR_CODE = -7
CLIENT_DISCONNECTED_ERROR_CODE = -8
TELEMETRY_GROUP_AREA = 'AREA'
TELEMETRY_HOOK_ZONE_EXIT = 'EXIT'
TELEMETRY_FIELD_NPC_COUNT = 'npcc'
TELEMETRY_FIELD_PLAYER_COUNT = 'plyc'
area_telemetry_writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_AREA)

class Settings:
    __qualname__ = 'Settings'
    MAX_ZONE_SIMS = Tunable(int, 10, description='Number of Sims the Area Server will try to create on startup.')
    GRIEF_STATISTIC = TunableReference(manager=services.get_instance_manager(sims4.resources.Types.STATISTIC), description='The affordance to push when the C API grief command is being run.')

class synchronous(object):
    __qualname__ = 'synchronous'
    __slots__ = ('callback_index', 'zone_id_index', 'session_id_index')

    def __init__(self, callback_index=None, zone_id_index=None, session_id_index=None):
        self.callback_index = callback_index
        self.zone_id_index = zone_id_index
        self.session_id_index = session_id_index

    def __call__(self, fn):

        def wrapped(*args, **kwargs):

            def run_callback(ret):
                if self.callback_index is not None:
                    finally_fn = args[self.callback_index]
                    if self.zone_id_index is not None:
                        if self.session_id_index is not None:
                            finally_fn(args[self.zone_id_index], args[self.session_id_index], ret)
                        else:
                            finally_fn(args[self.zone_id_index], ret)
                            finally_fn(ret)
                    else:
                        finally_fn(ret)

            def finally_wrap(*args, **kwargs):
                ret = EXCEPTION_ERROR_CODE
                try:
                    ret = fn(*args, **kwargs)
                finally:
                    run_callback(ret)

            finally_wrap(*args, **kwargs)
            return SUCCESS_CODE

        return wrapped

@exception_protected(None, log_invoke=True)
def c_api_server_init(initial_ticks):
    services.start_services(initial_ticks)
    native.animation.enable_native_reaction_event_handling(False)
    sims4.geometry.PolygonFootprint.set_global_enabled(True)
    status.info('c_api_server_init: Server initialized')
    return SUCCESS_CODE

@exception_protected(None)
def c_api_server_init_tick():
    return sims4.core_services.start_service_tick()

@exception_protected(None)
def c_api_server_tick(absolute_ticks):
    sims4.core_services.on_tick()
    clock_service = services.server_clock_service()
    previous_ticks = clock_service.ticks()
    if absolute_ticks < previous_ticks:
        absolute_ticks = previous_ticks
    clock_service.tick_server_clock(absolute_ticks)
    if services._zone_manager is not None:
        for zone in services._zone_manager.objects:
            while zone.is_instantiated:
                with sims4.zone_utils.global_zone_lock(zone.id):
                    persistence_service = services.get_persistence_service()
                    if persistence_service is not None and persistence_service.save_timeline:
                        persistence_service.save_timeline.simulate(services.time_service().sim_now)
                        return SUCCESS_CODE
                    zone.update(absolute_ticks)
    services.get_distributor_service().on_tick()
    return SUCCESS_CODE

@exception_protected(None)
def c_api_set_game_time(game_time_in_seconds):
    pass

@exception_protected(EXCEPTION_ERROR_CODE)
def c_api_server_ready():
    if paths.DEBUG_AVAILABLE:
        try:
            import pydevd
            pydevd.on_break_point_hook = clock.on_break_point_hook
        except ImportError:
            logger.exception('Unable to initialize gameplay components of the PyDev debugger due to exception.')
    return SUCCESS_CODE

@synchronous(callback_index=0)
@exception_protected(None, log_invoke=True)
def c_api_server_shutdown(callback):
    sims4.gsi.http_service.stop_http_server()
    services.stop_services()
    status.info('c_api_server_shutdown: Server shutdown')
    return SUCCESS_CODE

@c_api_can_fail()
@exception_protected(EXCEPTION_ERROR_CODE, log_invoke=True)
def c_api_zone_init(zone_id, world_id, world_file, gameplay_zone_data_bytes=None, save_slot_data_bytes=None):
    zone_data_proto = services.get_persistence_service().get_zone_proto_buff(zone_id)
    if zone_data_proto is not None:
        gameplay_zone_data = zone_data_proto.gameplay_zone_data
    save_slot_data = services.get_persistence_service().get_save_slot_proto_buff()
    zone = services._zone_manager.create_zone(zone_id, gameplay_zone_data, save_slot_data)
    zone.world_id = world_id
    zone_number = sims4.zone_utils.zone_numbers[zone_id]
    status.info('Zone {:#08x} (Zone #{}) initialized'.format(zone_id, zone_number))
    zone = services._zone_manager.get(zone_id)
    return SUCCESS_CODE

@synchronous(callback_index=1, zone_id_index=0)
@c_api_can_fail(error_return_values=(EXCEPTION_ERROR_CODE, TIMEOUT_ERROR_CODE, LOADSIMS_FAILED_ERROR_CODE))
@exception_protected(EXCEPTION_ERROR_CODE, log_invoke=True)
def c_api_zone_loaded(zone_id, callback):
    zone = services._zone_manager.get(zone_id)
    zone.on_objects_loaded()
    zone.load_zone()
    zone.zone_spin_up_service.process_zone_loaded()
    status.info('Zone {:#08x} loaded'.format(zone_id))
    return SUCCESS_CODE

@synchronous(callback_index=1, zone_id_index=0)
@c_api_can_fail(error_return_values=(EXCEPTION_ERROR_CODE, TIMEOUT_ERROR_CODE))
@exception_protected(EXCEPTION_ERROR_CODE, log_invoke=True)
def c_api_zone_shutdown(zone_id, callback):
    try:
        services._zone_manager.cleanup_uninstantiated_zones()
        services._zone_manager.remove_id(zone_id)
    finally:
        status.info('Zone {:#08x} shutdown'.format(zone_id))
    return SUCCESS_CODE

@synchronous(callback_index=5, zone_id_index=4, session_id_index=0)
@c_api_can_fail(error_return_values=(EXCEPTION_ERROR_CODE, TIMEOUT_ERROR_CODE, NO_HOUSEHOLD_ERROR_CODE, SIM_NOT_FOUND_ERROR_CODE))
@exception_protected(EXCEPTION_ERROR_CODE, log_invoke=True)
def c_api_client_connect(session_id, account_id, household_id, persona_name, zone_id, callback, active_sim_id, locale='none', edit_lot_mode=False):
    account = services.account_service().get_account_by_id(account_id, try_load_account=True)
    if account is None:
        account = server.account.Account(account_id, persona_name)
    account.locale = locale
    TelemetryTuning.filter_tunable_hooks()
    zone = services.current_zone()
    client = zone.client_manager.create_client(session_id, account, household_id)
    zone.on_client_connect(client)
    services.on_client_connect(client)
    yield_zone_id(services.current_zone_id())
    if client.household_id == SYSTEM_HOUSEHOLD_ID:
        zone.game_clock.restore_saved_clock_speed()
        return NO_HOUSEHOLD_ERROR_CODE
    status.info('Client {:#08x} ({}) connected to zone {:#08x}'.format(session_id, persona_name, zone_id))
    if edit_lot_mode:
        result = zone.do_build_mode_zone_spin_up(household_id)
    else:
        result = zone.do_zone_spin_up(household_id, active_sim_id)
    if not result:
        return EXCEPTION_ERROR_CODE
    return SUCCESS_CODE

@synchronous(callback_index=2, zone_id_index=1, session_id_index=0)
@c_api_can_fail(error_return_values=(EXCEPTION_ERROR_CODE, TIMEOUT_ERROR_CODE))
@exception_protected(EXCEPTION_ERROR_CODE, log_invoke=True)
def c_api_client_disconnect(session_id, zone_id, callback):
    logger.info('Client {0} disconnected in zone {1}', session_id, zone_id)
    status.info('Client {:#08x} disconnected from zone {:#08x}'.format(session_id, zone_id))
    return SUCCESS_CODE

def c_api_request_client_disconnect(session_id, zone_id, callback):

    def request_client_disconnect_gen(timeline):
        try:
            zone = services.current_zone()
            if zone is not None:
                client_manager = zone.client_manager
                client = client_manager.get(session_id)
                logger.info('Client {0} starting save of zone {1}', session_id, zone_id)
                yield services.get_persistence_service().save_to_scratch_slot_gen(timeline)
                logger.info('Client {0} save completed for {1}', session_id, zone_id)
                with telemetry_helper.begin_hook(area_telemetry_writer, TELEMETRY_HOOK_ZONE_EXIT, household=client.household) as hook:
                    (player_sims, npc_sims) = services.sim_info_manager().get_player_npc_sim_count()
                    hook.write_int(TELEMETRY_FIELD_PLAYER_COUNT, player_sims)
                    hook.write_int(TELEMETRY_FIELD_NPC_COUNT, npc_sims)
                zone.on_teardown(client)
                if client is None:
                    logger.error('Client {0} not in client manager from zone {1}', session_id, zone_id)
                    return callback(zone_id, session_id, NO_CLIENT_ERROR_CODE)
                client_manager.remove(client)
            return callback(zone_id, session_id, SUCCESS_CODE)
        except:
            logger.exception('Error disconnecting the client')
            return callback(zone_id, session_id, EXCEPTION_ERROR_CODE)

    logger.info('Client {0} requesting disconnect in zone {1}', session_id, zone_id)
    if zone_id == WORLDBUILDER_ZONE_ID:
        callback(zone_id, session_id, SUCCESS_CODE)
        return SUCCESS_CODE
    with sims4.zone_utils.global_zone_lock(zone_id):
        persistence_service = services.get_persistence_service()
        persistence_service.save_using(request_client_disconnect_gen)
    return SUCCESS_CODE

@synchronous(callback_index=3, zone_id_index=1, session_id_index=0)
@c_api_can_fail(error_return_values=(EXCEPTION_ERROR_CODE, TIMEOUT_ERROR_CODE, LOADSIMS_FAILED_ERROR_CODE))
@exception_protected(EXCEPTION_ERROR_CODE, log_invoke=True)
def c_api_add_sims(session_id, zone_id, sim_ids, callback, add_to_skewer):
    zone = services._zone_manager.get(zone_id)
    if zone is None:
        return LOADSIMS_FAILED_ERROR_CODE
    client = zone.client_manager.get(session_id)
    load_sims_on_client_connect = True
    if client is None and load_sims_on_client_connect:
        services.sim_info_manager().add_sims_to_zone(sim_ids)
    else:
        object_manager = services.object_manager()
        for sim_id in sim_ids:
            if sim_id in object_manager:
                logger.error('Attempt to add a sim who is already in the zone.  Native likely has a logic error.', owner='mduke')
            ret = sims.sim_spawner.SimSpawner.load_sim(sim_id)
            while not ret:
                logger.error('Sim failed to load while spinning up sim_id: {}.', sim_id, owner='mduke')
                return LOADSIMS_FAILED_ERROR_CODE
        if add_to_skewer:
            for sim_id in sim_ids:
                sim_info = services.sim_info_manager(zone_id).get(sim_id)
                while sim_info is not None:
                    if client.household_id == sim_info.household_id:
                        client.add_selectable_sim_info(sim_info)
    return SUCCESS_CODE

@exception_protected(None)
def c_api_setup_sim_spawner_data(zone_id, spawner_data):
    zone = services._zone_manager.get(zone_id)
    if zone is not None:
        zone.setup_spawner_data(spawner_data, zone_id)
    return SUCCESS_CODE

@exception_protected(None, log_invoke=True)
def c_api_remote_client_connect(zone_id, account_id):
    _set_remote_connected(zone_id, account_id, True)

@exception_protected(None, log_invoke=True)
def c_api_remote_client_disconnect(zone_id, account_id):
    _set_remote_connected(zone_id, account_id, False)

def _set_remote_connected(zone_id, account_id, value):
    account = services.account_service().get_account_by_id(account_id)
    household = account.get_household(zone_id)
    if household is not None:
        household.remote_connected = value

@c_api_can_fail()
@exception_protected(0)
def c_api_get_household_funds(zone_id, household_id):
    household = services.household_manager(zone_id).get(household_id)
    if household is not None:
        return household.funds.money
    return SUCCESS_CODE

@exception_protected(None)
def c_api_grief():
    pass

