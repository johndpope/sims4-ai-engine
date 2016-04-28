import argparse
import collections
import itertools
from crafting.recipe import destroy_unentitled_craftables
from event_testing import test_events
from objects import ALL_HIDDEN_REASONS
from persistence_error_types import ErrorCodes, generate_exception_code
from world.lot_tuning import GlobalLotTuningAndCleanup
import caches
import enum
import pythonutils
import routing
import services
import sims4.command_script
import sims4.log
import sims4.service_manager
import telemetry_helper
TELEMETRY_GROUP_ZONE = 'ZONE'
TELEMETRY_HOOK_ZONE_LOAD = 'LOAD'
TELEMETRY_FIELD_NPC_COUNT = 'npcc'
TELEMETRY_FIELD_PLAYER_COUNT = 'plyc'
zone_telemetry_writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_ZONE)
logger = sims4.log.Logger('ZoneSpinUpService')

class ZoneSpinUpStatus(enum.Int, export=False):
    __qualname__ = 'ZoneSpinUpStatus'
    CREATED = 0
    INITIALIZED = 1
    SEQUENCED = 2
    RUNNING = 3
    COMPLETED = 4
    ERRORED = 5

class _ZoneSpinUpStateResult(enum.Int, export=False):
    __qualname__ = '_ZoneSpinUpStateResult'
    WAITING = 0
    DONE = 1

class _ZoneSpinUpState:
    __qualname__ = '_ZoneSpinUpState'

    def __init__(self):
        self._task = None

    def exception_error_code(self):
        return ErrorCodes.GENERIC_ERROR

    def on_enter(self):
        logger.debug('{}.on_enter at {}', self.__class__.__name__, services.time_service().sim_now)
        return _ZoneSpinUpStateResult.DONE

    def on_update(self):
        return _ZoneSpinUpStateResult.DONE

    def on_exit(self):
        logger.debug('{}.on_exit at {}', self.__class__.__name__, services.time_service().sim_now, services.game_clock_service()._loading_monotonic_ticks)

class _StopCaching(_ZoneSpinUpState):
    __qualname__ = '_StopCaching'

    def exception_error_code(self):
        return ErrorCodes.STOP_CACHING_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        caches.skip_cache = True
        return _ZoneSpinUpStateResult.DONE

class _StartCaching(_ZoneSpinUpState):
    __qualname__ = '_StartCaching'

    def exception_error_code(self):
        return ErrorCodes.START_CACHING_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        caches.skip_cache = False
        caches.clear_all_caches(force=True)
        return _ZoneSpinUpStateResult.DONE

class _InitializeFrontDoor(_ZoneSpinUpState):
    __qualname__ = '_InitializeFrontDoor'

    def exception_error_code(self):
        return ErrorCodes.INITIALIZED_FRONT_DOOR_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        current_zone = services.current_zone()
        current_zone.load_zone_front_door()
        return _ZoneSpinUpStateResult.DONE

class _LoadHouseholdsAndSimInfosState(_ZoneSpinUpState):
    __qualname__ = '_LoadHouseholdsAndSimInfosState'

    def exception_error_code(self):
        return ErrorCodes.LOAD_HOUSEHOLD_AND_SIM_INFO_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        services.household_manager().load_households()
        zone = services.current_zone()
        zone_spin_up_service = zone.zone_spin_up_service
        household_id = zone_spin_up_service._client_connect_data.household_id
        household = zone.household_manager.get(household_id)
        client = zone_spin_up_service._client_connect_data.client
        services.account_service().on_load_options(client)
        for sim_info in household.sim_info_gen():
            client.add_selectable_sim_info(sim_info, send_relationship_update=False)
        zone.on_households_and_sim_infos_loaded()
        zone.service_manager.on_all_households_and_sim_infos_loaded(client)
        services.ui_dialog_service().send_dialog_options_to_client()
        client.clean_and_send_remaining_relationship_info()
        services.current_zone().lot.send_lot_display_info()
        for obj in itertools.chain(services.object_manager().values(), services.inventory_manager().values()):
            while obj.live_drag_component is not None:
                obj.live_drag_component.set_active_household_live_drag_permission()
        return _ZoneSpinUpStateResult.DONE

class _SetObjectOwnershipState(_ZoneSpinUpState):
    __qualname__ = '_SetObjectOwnershipState'

    def exception_error_code(self):
        return ErrorCodes.SET_OBJECT_OWNERSHIP_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        current_zone = services.current_zone()
        current_zone.update_household_objects_ownership()
        return _ZoneSpinUpStateResult.DONE

class _CleanupLotState(_ZoneSpinUpState):
    __qualname__ = '_CleanupLotState'

    def on_enter(self):
        super().on_enter()
        zone = services.current_zone()
        client = zone.zone_spin_up_service._client_connect_data.client
        destroy_unentitled_craftables()
        GlobalLotTuningAndCleanup.cleanup_objects(lot=zone.lot)
        zone.service_manager.on_cleanup_zone_objects(client)
        services.current_zone().posture_graph_service.build_during_zone_spin_up()
        pythonutils.try_highwater_gc()
        return _ZoneSpinUpStateResult.DONE

    def exception_error_code(self):
        return ErrorCodes.CLEANUP_STATE_FAILED

class _SpawnSimsState(_ZoneSpinUpState):
    __qualname__ = '_SpawnSimsState'

    def exception_error_code(self):
        return ErrorCodes.SPAWN_SIM_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        services.get_zone_situation_manager().on_pre_spawning_sims()
        client = services.client_manager().get_first_client()
        services.sim_info_manager().on_spawn_sims_for_zone_spin_up(client)
        return _ZoneSpinUpStateResult.DONE

class _WaitForSimsReadyState(_ZoneSpinUpState):
    __qualname__ = '_WaitForSimsReadyState'

    def exception_error_code(self):
        return ErrorCodes.WAIT_FOR_SIM_READY_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        return _ZoneSpinUpStateResult.WAITING

    def on_update(self):
        for sim in services.sim_info_manager().instanced_sims_gen(allow_hidden_flags=ALL_HIDDEN_REASONS):
            while not sim.is_simulating:
                return _ZoneSpinUpStateResult.WAITING
        return _ZoneSpinUpStateResult.DONE

class _WaitForNavmeshState(_ZoneSpinUpState):
    __qualname__ = '_WaitForNavmeshState'

    def __init__(self):
        super().__init__()
        self._sent_fence_id = None

    def exception_error_code(self):
        return ErrorCodes.WAIT_FOR_NAVMESH_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        zone = services.current_zone()
        with sims4.zone_utils.global_zone_lock(zone.id):
            fence_id = zone.get_current_fence_id_and_increment()
            self._sent_fence_id = fence_id
            routing.flush_planner(False)
            routing.add_fence(fence_id)
        return _ZoneSpinUpStateResult.WAITING

    def on_update(self):
        last_fence_id = routing.get_last_fence()
        if last_fence_id < self._sent_fence_id:
            return _ZoneSpinUpStateResult.WAITING
        return _ZoneSpinUpStateResult.DONE

class _RestoreSIState(_ZoneSpinUpState):
    __qualname__ = '_RestoreSIState'

    def exception_error_code(self):
        return ErrorCodes.RESTORE_SI_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        zone = services.current_zone()
        if not zone.should_restore_sis():
            logger.debug('NOT restoring interactions in zone spin up', owner='sscholl')
            return _ZoneSpinUpStateResult.DONE
        logger.debug('Restoring interactions in zone spin up', owner='sscholl')
        services.sim_info_manager().restore_sim_si_state()
        return _ZoneSpinUpStateResult.DONE

class _RestoreCareerState(_ZoneSpinUpState):
    __qualname__ = '_RestoreCareerState'

    def exception_error_code(self):
        return ErrorCodes.RESTORE_CAREER_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        services.get_career_service().restore_career_state()
        return _ZoneSpinUpStateResult.DONE

class _SituationCommonState(_ZoneSpinUpState):
    __qualname__ = '_SituationCommonState'

    def exception_error_code(self):
        return ErrorCodes.SITUATION_COMMON_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        situation_manager = services.get_zone_situation_manager()
        situation_manager.create_situations_during_zone_spin_up()
        services.current_zone().venue_service.initialize_venue_background_schedule()
        situation_manager.on_all_situations_created_during_zone_spin_up()
        return _ZoneSpinUpStateResult.DONE

class _WaitForBouncer(_ZoneSpinUpState):
    __qualname__ = '_WaitForBouncer'

    def exception_error_code(self):
        return ErrorCodes.WAIT_FOR_BOUNCER_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        situation_manager = services.get_zone_situation_manager()
        situation_manager.bouncer.lock_high_frequency_spawn()
        situation_manager.bouncer.unlock_high_frequency_spawn()
        return _ZoneSpinUpStateResult.WAITING

    def on_update(self):
        super().on_update()
        if services.get_zone_situation_manager().bouncer.high_frequency_spawn:
            return _ZoneSpinUpStateResult.WAITING
        return _ZoneSpinUpStateResult.DONE

class _PrerollAutonomyState(_ZoneSpinUpState):
    __qualname__ = '_PrerollAutonomyState'

    def exception_error_code(self):
        return ErrorCodes.PREROLL_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        caches.skip_cache = False
        first_visit_to_zone = services.current_zone().is_first_visit_to_zone
        if services.game_clock_service().time_has_passed_in_world_since_zone_save() or first_visit_to_zone:
            services.sim_info_manager().run_preroll_autonomy(first_time_load_zone=first_visit_to_zone)
        return _ZoneSpinUpStateResult.DONE

    def on_exit(self):
        super().on_exit()
        caches.skip_cache = True

class _AwayActionsState(_ZoneSpinUpState):
    __qualname__ = '_AwayActionsState'

    def exception_error_code(self):
        return ErrorCodes.AWAY_ACTION_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        client = services.client_manager().get_first_client()
        home_zone_id = client.household.home_zone_id
        if home_zone_id == 0:
            return _ZoneSpinUpStateResult.DONE
        zone_manager = services.get_zone_manager()
        loaded_zones = set()
        loaded_zones.add(services.current_zone_id())
        for sim_info in services.sim_info_manager().values():
            if sim_info.is_selectable:
                if sim_info.zone_id not in loaded_zones:
                    zone_manager.load_uninstantiated_zone_data(sim_info.zone_id)
                    loaded_zones.add(sim_info.zone_id)
                sim_info.away_action_tracker.start()
            else:
                sim_info.away_action_tracker.stop()
        home_zone_id = client.household.home_zone_id
        if home_zone_id not in loaded_zones:
            zone_manager.load_uninstantiated_zone_data(home_zone_id)
        return _ZoneSpinUpStateResult.DONE

class _PushSimsToGoHomeState(_ZoneSpinUpState):
    __qualname__ = '_PushSimsToGoHomeState'

    def exception_error_code(self):
        return ErrorCodes.PUSH_SIMS_GO_HOME_STATE_FAILED

    def on_enter(self):
        sim_info_manager = services.sim_info_manager()
        if sim_info_manager:
            sim_info_manager.push_sims_to_go_home()
        return _ZoneSpinUpStateResult.DONE

class _FinalizeObjectsState(_ZoneSpinUpState):
    __qualname__ = '_FinalizeObjectsState'

    def exception_error_code(self):
        return ErrorCodes.FINALIZE_OBJECT_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        services.current_zone().lot.publish_shared_inventory_items()
        active_household_id = services.active_household_id()
        for script_object in services.object_manager().get_all():
            script_object.finalize(active_household_id=active_household_id)
        return _ZoneSpinUpStateResult.DONE

class _SetActiveSimState(_ZoneSpinUpState):
    __qualname__ = '_SetActiveSimState'

    def exception_error_code(self):
        return ErrorCodes.SET_ACTIVE_SIM_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        zone = services.current_zone()
        zone_spin_up_service = zone.zone_spin_up_service
        active_sim_id = zone_spin_up_service._client_connect_data.active_sim_id
        client = zone_spin_up_service._client_connect_data.client
        if (not active_sim_id or not client.set_active_sim_by_id(active_sim_id)) and client.active_sim is None:
            client.set_next_sim()
        client.resend_active_sim_info()
        return _ZoneSpinUpStateResult.DONE

class _StartupCommandsState(_ZoneSpinUpState):
    __qualname__ = '_StartupCommandsState'

    def exception_error_code(self):
        return ErrorCodes.START_UP_COMMANDS_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        parser = argparse.ArgumentParser()
        parser.add_argument('--on_startup_commands')
        (args, unused_args) = parser.parse_known_args()
        args_dict = vars(args)
        startup_commands_file = args_dict.get('on_startup_commands')
        if not startup_commands_file:
            return
        clients = list(client for client in services.client_manager().values())
        if not clients:
            client_id = 0
        else:
            client_id = clients[0].id
        sims4.command_script.run_script(startup_commands_file, client_id)
        return _ZoneSpinUpStateResult.DONE

class _EditModeSequenceCompleteState(_ZoneSpinUpState):
    __qualname__ = '_EditModeSequenceCompleteState'

    def exception_error_code(self):
        return ErrorCodes.EDIT_MODE_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        zone = services.current_zone()
        zone_spin_up_service = zone.zone_spin_up_service
        household_id = zone_spin_up_service._client_connect_data.household_id
        zone.household_manager.load_household(household_id)
        zone.on_households_and_sim_infos_loaded()
        zone.game_clock.restore_saved_clock_speed()
        return _ZoneSpinUpStateResult.DONE

class _FinalPlayableState(_ZoneSpinUpState):
    __qualname__ = '_FinalPlayableState'

    def exception_error_code(self):
        return ErrorCodes.FINAL_PLAYABLE_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        zone = services.current_zone()
        zone_spin_up_service = zone.zone_spin_up_service
        zone.venue_service.setup_special_event_alarm()
        zone.ambient_service.begin_walkbys()
        client = zone_spin_up_service._client_connect_data.client
        if client is not None:
            with telemetry_helper.begin_hook(zone_telemetry_writer, TELEMETRY_HOOK_ZONE_LOAD, household=client.household) as hook:
                (player_sims, npc_sims) = services.sim_info_manager().get_player_npc_sim_count()
                hook.write_int(TELEMETRY_FIELD_PLAYER_COUNT, player_sims)
                hook.write_int(TELEMETRY_FIELD_NPC_COUNT, npc_sims)
            from event_testing import test_events
            for sim_info in client.selectable_sims:
                services.get_event_manager().process_event(test_events.TestEvent.LoadingScreenLifted, sim_info=sim_info)
        client.household.telemetry_tracker.initialize_alarms()
        return _ZoneSpinUpStateResult.DONE

class _HittingTheirMarksState(_ZoneSpinUpState):
    __qualname__ = '_HittingTheirMarksState'

    def __init__(self):
        super().__init__()
        self._countdown = 30

    def exception_error_code(self):
        return ErrorCodes.HITTING_THEIR_MARKS_STATE_FAILED

    def on_enter(self):
        super().on_enter()
        services.game_clock_service().advance_for_hitting_their_marks()
        return _ZoneSpinUpStateResult.WAITING

    def on_update(self):
        super().on_update()
        if self._countdown <= 0:
            services.current_zone().on_hit_their_marks()
            return _ZoneSpinUpStateResult.DONE
        services.game_clock_service().advance_for_hitting_their_marks()
        return _ZoneSpinUpStateResult.WAITING

ClientConnectData = collections.namedtuple('ClientConnectData', ['household_id', 'client', 'active_sim_id'])

class ZoneSpinUpService(sims4.service_manager.Service):
    __qualname__ = 'ZoneSpinUpService'

    def __init__(self):
        self._current_state = None
        self._cur_state_index = -1
        self._client_connect_data = None
        self._status = ZoneSpinUpStatus.CREATED
        self._state_sequence = None

    @property
    def _edit_mode_state_sequence(self):
        return (_EditModeSequenceCompleteState,)

    @property
    def _playable_sequence(self):
        return (_StopCaching, _LoadHouseholdsAndSimInfosState, _SetObjectOwnershipState, _SpawnSimsState, _WaitForSimsReadyState, _CleanupLotState, _AwayActionsState, _RestoreSIState, _SituationCommonState, _WaitForBouncer, _WaitForSimsReadyState, _FinalizeObjectsState, _RestoreCareerState, _WaitForNavmeshState, _InitializeFrontDoor, _PrerollAutonomyState, _PushSimsToGoHomeState, _SetActiveSimState, _StartupCommandsState, _StartCaching, _FinalPlayableState)

    @property
    def _hitting_their_marks_state_sequence(self):
        return (_HittingTheirMarksState,)

    def set_household_id_and_client_and_active_sim_id(self, household_id, client, active_sim_id):
        logger.assert_raise(self._status == ZoneSpinUpStatus.CREATED, 'Attempting to initialize the zone_spin_up_process more than once.', owner='sscholl')
        self._client_connect_data = ClientConnectData(household_id, client, active_sim_id)
        self._status = ZoneSpinUpStatus.INITIALIZED

    def stop(self):
        self.do_clean_up()

    @property
    def is_finished(self):
        return self._status >= ZoneSpinUpStatus.COMPLETED

    @property
    def had_an_error(self):
        return self._status == ZoneSpinUpStatus.ERRORED

    def _start_sequence(self, sequence):
        logger.assert_raise(self._status >= ZoneSpinUpStatus.INITIALIZED, 'Attempting to start the zone_spin_up_process when not initialized.', owner='sscholl')
        self._current_state = None
        self._cur_state_index = -1
        self._status = ZoneSpinUpStatus.SEQUENCED
        self._state_sequence = sequence

    def start_playable_sequence(self):
        self._start_sequence(self._playable_sequence)

    def start_build_mode_sequence(self):
        self._start_sequence(self._edit_mode_state_sequence)

    def start_hitting_their_marks_sequence(self):
        self._start_sequence(self._hitting_their_marks_state_sequence)

    def update(self):
        logger.assert_raise(self._status != ZoneSpinUpStatus.CREATED and self._status != ZoneSpinUpStatus.INITIALIZED, 'Attempting to update the zone_spin_up_process that has not been initialized.', owner='sscholl')
        if self._status >= ZoneSpinUpStatus.COMPLETED:
            return
        if self._status == ZoneSpinUpStatus.SEQUENCED:
            self._status = ZoneSpinUpStatus.RUNNING
        try:
            if self._current_state is not None:
                state_result = self._current_state.on_update()
                self._current_state.on_exit()
            else:
                state_result = _ZoneSpinUpStateResult.DONE
            while state_result == _ZoneSpinUpStateResult.DONE:
                if self._cur_state_index >= len(self._state_sequence):
                    self._status = ZoneSpinUpStatus.COMPLETED
                    break
                else:
                    self._current_state = self._state_sequence[self._cur_state_index]()
                    state_result = self._current_state.on_enter()
                    while state_result == _ZoneSpinUpStateResult.DONE:
                        self._current_state.on_exit()
                        continue
        except Exception as e:
            self._status = ZoneSpinUpStatus.ERRORED
            dialog = services.persistence_service.PersistenceTuning.LOAD_ERROR_REQUEST_RESTART(services.current_zone())
            if dialog is not None:
                error_string = generate_exception_code(self._current_state.exception_error_code(), e)
                dialog.show_dialog(additional_tokens=(error_string,))
            logger.exception('Exception raised while processing zone spin up sequence: {}', e)

    def do_clean_up(self):
        self._current_state = None
        self._cur_state_index = -1
        self._client_connect_data = None

    def process_zone_loaded(self):
        services.lot_spawner_service_instance().setup_spawner()
        services.current_zone().supress_goals_for_spawn_points()

