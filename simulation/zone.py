import collections
import gc
import random
import weakref
from protocolbuffers import FileSerialization_pb2 as serialization
from protocolbuffers.Consts_pb2 import MGR_OBJECT, MGR_SIM_INFO, MGR_CLIENT, MGR_SITUATION, MGR_PARTY, MGR_HOUSEHOLD, MGR_SOCIAL_GROUP
from careers.career_service import CareerService
from clock import GameClock, ClockSpeedMode
from date_and_time import DateAndTime, TimeSpan
from event_testing import test_events
from interactions.constraints import create_constraint_set, Constraint
from sims.royalty_tracker import RoyaltyAlarmManager
from sims4 import protocol_buffer_utils
from sims4.callback_utils import CallableList, CallableListPreventingRecursion
from world.lot import Lot
from world.spawn_point import SpawnPointOption, SpawnPoint
import adaptive_clock_speed
import alarms
import areaserver
import build_buy
import caches
import camera
import clock
import distributor.system
import gsi_handlers.routing_handlers
import id_generator
import indexed_manager
import interactions.constraints
import interactions.utils
import persistence_error_types
import persistence_module
import placement
import routing
import services
import sims4.log
import sims4.random
import world.spawn_point
import zone_types
logger = sims4.log.Logger('Zone')
TickMetric = collections.namedtuple(
    'TickMetric', ['absolute_ticks', 'sim_now', 'clock_speed',
                   'clock_speed_multiplier', 'game_time', 'multiplier_type'])
ZONE_OBJECT_LEAK_DISABLE_REASON = 'Zone shutting down'


class Zone:
    __qualname__ = 'Zone'
    force_route_instantly = False

    def __init__(self, zone_id, save_slot_data_id):
        self.id = zone_id
        self.neighborhood_id = 0
        self.open_street_id = 0
        self.lot = Lot(zone_id)
        self.entitlement_unlock_handlers = {}
        self._spawner_data = {}
        self._dynamic_spawn_points = {}
        self._zone_state = zone_types.ZoneState.ZONE_INIT
        self._zone_state_callbacks = {}
        self.all_transition_controllers = weakref.WeakSet()
        self.navmesh_change_callbacks = CallableListPreventingRecursion()
        self.wall_contour_update_callbacks = CallableListPreventingRecursion()
        self.foundation_and_level_height_update_callbacks = CallableListPreventingRecursion(
        )
        self.navmesh_id = None
        self.object_count = 0
        self.is_in_build_buy = False
        self.objects_to_fixup_post_bb = None
        self._save_slot_data_id = save_slot_data_id
        self._royalty_alarm_manager = RoyaltyAlarmManager()
        self.current_navmesh_fence_id = 1
        self._first_visit_to_zone = None
        self._active_lot_arrival_spawn_point = None
        self._time_of_last_open_street_save = None
        for key in zone_types.ZoneState:
            while key != zone_types.ZoneState.ZONE_INIT:
                self._zone_state_callbacks[key] = CallableList()
        self._client = None
        self._tick_metrics = None

    def __repr__(self):
        return '<Zone ID: {0:#x}>'.format(self.id)

    def ref(self, callback=None):
        return weakref.ref(self, callback)

    @property
    def is_zone_loading(self):
        return self._zone_state == zone_types.ZoneState.ZONE_INIT

    @property
    def are_sims_hitting_their_marks(self):
        return self._zone_state == zone_types.ZoneState.HITTING_THEIR_MARKS

    @property
    def is_zone_running(self):
        return self._zone_state == zone_types.ZoneState.RUNNING

    @property
    def is_zone_shutting_down(self):
        return self._zone_state == zone_types.ZoneState.SHUTDOWN_STARTED

    @property
    def is_households_and_sim_infos_loaded(self):
        return self._zone_state == zone_types.ZoneState.HOUSEHOLDS_AND_SIM_INFOS_LOADED

    @property
    def animate_instantly(self):
        return self._zone_state != zone_types.ZoneState.RUNNING

    @property
    def route_instantly(self):
        return self._zone_state != zone_types.ZoneState.RUNNING or force_route_instantly

    @property
    def force_process_transitions(self):
        return self._zone_state != zone_types.ZoneState.RUNNING

    @property
    def is_instantiated(self):
        return True

    @property
    def active_lot_arrival_spawn_point(self):
        return self._active_lot_arrival_spawn_point

    def _get_zone_proto(self):
        return services.get_persistence_service().get_zone_proto_buff(self.id)

    def get_current_fence_id_and_increment(self):
        current_id = self.current_navmesh_fence_id
        self.current_navmesh_fence_id = current_id + 1
        return current_id

    @property
    def is_first_visit_to_zone(self):
        logger.assert_raise(
            self._first_visit_to_zone is not None,
            'You must wait until after load_zone() has been called before checking is_first_visit_to_zone.',
            owner='sscholl')
        return self._first_visit_to_zone

    def start_services(self, gameplay_zone_data, save_slot_data):
        _distributor = distributor.system.Distributor.instance()
        self.sim_quadtree = placement.get_sim_quadtree_for_zone(self.id)
        self.single_part_condition_list = weakref.WeakKeyDictionary()
        self.multi_part_condition_list = weakref.WeakKeyDictionary()
        from objects.object_manager import ObjectManager, PropManager, PartyManager, InventoryManager, SocialGroupManager
        from sims.sim_info_manager import SimInfoManager
        from server.clientmanager import ClientManager
        from sims.household_manager import HouseholdManager
        from autonomy.autonomy_service import AutonomyService
        from ui.ui_dialog_service import UiDialogService
        from server.config_service import ConfigService
        from event_testing.test_events import EventManager
        from situations.situation_manager import SituationManager
        from filters.sim_filter_service import SimFilterService
        from socials.clustering import ObjectClusterService, SocialGroupClusterService
        from postures.posture_graph import PostureGraphService
        from animation.arb_accumulator import ArbAccumulatorService
        from world.travel_service import TravelService
        from situations.service_npcs.service_npc_manager import ServiceNpcService
        from story_progression.story_progression_service import StoryProgressionService
        from sims.master_controller import MasterController
        from filters.neighborhood_population_service import NeighborhoodPopulationService
        from services.lot_spawner_service import LotSpawnerService
        from zone_spin_up_service import ZoneSpinUpService
        from interactions.privacy import PrivacyService
        from services.age_service import AgeService
        from situations.ambient.ambient_service import AmbientService
        from broadcasters.broadcaster_service import BroadcasterService
        from services.super_speed_three_service import SuperSpeedThreeService
        from services.fire_service import FireService
        from services.cleanup_service import CleanupService
        from time_service import TimeService
        from sims4.sim_irq_service import SimIrqService
        from venues.venue_service import VenueService
        from services.reset_and_delete_service import ResetAndDeleteService
        services = [
            GameClock(), TimeService(), ConfigService(), SimIrqService(),
            EventManager(), ClientManager(manager_id=MGR_CLIENT),
            HouseholdManager(manager_id=MGR_HOUSEHOLD),
            ResetAndDeleteService(), ObjectManager(manager_id=MGR_OBJECT),
            InventoryManager(manager_id=MGR_OBJECT), AgeService(),
            SimInfoManager(manager_id=MGR_SIM_INFO),
            PropManager(manager_id=MGR_OBJECT), PostureGraphService(),
            ArbAccumulatorService(None, None), AutonomyService(),
            SituationManager(manager_id=MGR_SITUATION), SimFilterService(),
            PartyManager(manager_id=MGR_PARTY),
            SocialGroupManager(manager_id=MGR_SOCIAL_GROUP), UiDialogService(),
            ObjectClusterService(), SocialGroupClusterService(),
            TravelService(), NeighborhoodPopulationService(),
            ServiceNpcService(), LotSpawnerService(), VenueService(),
            AmbientService(), StoryProgressionService(), ZoneSpinUpService(),
            PrivacyService(), FireService(), BroadcasterService(),
            CleanupService(), SuperSpeedThreeService(), CareerService(),
            MasterController()
        ]
        from sims4.service_manager import ServiceManager
        self.service_manager = ServiceManager()
        for service in services:
            self.service_manager.register_service(service)
        self.client_object_managers = set()
        self.service_manager.start_services(
            zone=self,
            gameplay_zone_data=gameplay_zone_data,
            save_slot_data=save_slot_data)
        self.navmesh_alarm_handle = alarms.add_alarm_real_time(
            self,
            clock.interval_in_real_seconds(1),
            self._check_navmesh_updated_alarm_callback,
            repeating=True,
            use_sleep_time=False)
        self._royalty_alarm_manager.start_schedule()

    def update(self, absolute_ticks):
        if self._zone_state == zone_types.ZoneState.CLIENT_CONNECTED:
            self.game_clock.tick_game_clock(absolute_ticks)
        elif self._zone_state == zone_types.ZoneState.HITTING_THEIR_MARKS:
            self.time_service.update(time_slice=False)
            self.sim_filter_service.update()
            self.situation_manager.update()
            self.broadcaster_service.update()
            self.zone_spin_up_service.update()
        elif self._zone_state == zone_types.ZoneState.RUNNING:
            self.game_clock.tick_game_clock(absolute_ticks)
            self.time_service.update()
            self.sim_filter_service.update()
            if self.game_clock.clock_speed() != ClockSpeedMode.PAUSED:
                self.situation_manager.update()
                self.broadcaster_service.update()
                adaptive_clock_speed.AdaptiveClockSpeed.update_adaptive_speed()
        self._gather_tick_metrics(absolute_ticks)

    def _gather_tick_metrics(self, absolute_ticks):
        if self._tick_metrics is not None:
            self._tick_metrics.append(TickMetric(
                absolute_ticks=absolute_ticks,
                sim_now=self.time_service.sim_now,
                clock_speed=int(self.game_clock.clock_speed()),
                clock_speed_multiplier=
                self.game_clock.current_clock_speed_scale(),
                game_time=self.game_clock.now(),
                multiplier_type=self.game_clock.clock_speed_multiplier_type))

    def start_gathering_tick_metrics(self):
        self._tick_metrics = []

    def stop_gathering_tick_metrics(self):
        self._tick_metrics = None

    @property
    def tick_data(self):
        return self._tick_metrics

    def do_zone_spin_up(self, household_id, active_sim_id):
        self.zone_spin_up_service.set_household_id_and_client_and_active_sim_id(
            household_id=household_id,
            client=self._client,
            active_sim_id=active_sim_id)
        self.game_clock.enter_zone_spin_up()
        self.zone_spin_up_service.start_playable_sequence()
        while not self.zone_spin_up_service.is_finished:
            self.time_service.update(time_slice=False)
            self.zone_spin_up_service.update()
            self.sim_filter_service.update()
            self.situation_manager.update()
        if self.zone_spin_up_service.had_an_error:
            return False
        self._set_zone_state(zone_types.ZoneState.HITTING_THEIR_MARKS)
        self.zone_spin_up_service.start_hitting_their_marks_sequence()
        return True

    def do_build_mode_zone_spin_up(self, household_id):
        self.zone_spin_up_service.set_household_id_and_client_and_active_sim_id(
            household_id=household_id,
            client=self._client,
            active_sim_id=None)
        self.zone_spin_up_service.start_build_mode_sequence()
        while not self.zone_spin_up_service.is_finished:
            self.zone_spin_up_service.update()
        if self.zone_spin_up_service.had_an_error:
            return False
        self._set_zone_state(zone_types.ZoneState.HITTING_THEIR_MARKS)
        self._set_zone_state(zone_types.ZoneState.RUNNING)
        self._set_initial_camera_focus()
        return True

    def on_hit_their_marks(self):
        self._set_zone_state(zone_types.ZoneState.RUNNING)
        self.game_clock.exit_zone_spin_up()
        self._set_initial_camera_focus()

    def _set_initial_camera_focus(self):
        client = self._client
        if camera.deserialize(client=client):
            return
        if client.active_sim is not None:
            camera.focus_on_sim(follow=True, client=client)
        else:
            camera.set_to_default()

    def on_soak_end(self):
        import argparse
        import sims4
        import services
        parser = argparse.ArgumentParser()
        parser.add_argument('--on_shutdown_commands')
        (args, unused_args) = parser.parse_known_args()
        args_dict = vars(args)
        shutdown_commands_file = args_dict.get('on_shutdown_commands')
        if shutdown_commands_file:
            clients = list(client
                           for client in services.client_manager().values())
            if not clients:
                client_id = 0
            else:
                client_id = clients[0].id
            sims4.command_script.run_script(shutdown_commands_file, client_id)

    def on_teardown(self, client):
        logger.debug('Zone teardown started')
        indexed_manager.IndexedManager.add_gc_collect_disable_reason(
            ZONE_OBJECT_LEAK_DISABLE_REASON)
        self.on_soak_end()
        self._set_zone_state(zone_types.ZoneState.SHUTDOWN_STARTED)
        logger.debug('Zone teardown: disable event manager')
        self.event_manager.disable_on_teardown()
        self.ui_dialog_service.disable_on_teardown()
        logger.debug('Zone teardown: destroy situations')
        self.situation_manager.destroy_situations_on_teardown()
        logger.debug('Zone teardown: flush sim_infos to client')
        self.sim_info_manager.flush_to_client_on_teardown()
        logger.debug('Zone teardown: remove Sims from master controller')
        self.master_controller.remove_all_sims_and_disable_on_teardown()
        logger.debug('Zone teardown: destroy objects and sims')
        all_objects = []
        all_objects.extend(self.prop_manager.values())
        all_objects.extend(self.inventory_manager.values())
        all_objects.extend(self.object_manager.values())
        services.get_reset_and_delete_service().trigger_batch_destroy(
            all_objects)
        logger.debug('Zone teardown: destroy sim infos')
        self.sim_info_manager.destroy_all_objects()
        logger.debug('Zone teardown:  services.on_client_disconnect')
        services.on_client_disconnect(client)
        logger.debug('Zone teardown:  time_service')
        self.time_service.on_teardown()
        logger.debug('Zone teardown:  complete')
        self.zone_spin_up_service.do_clean_up()
        self._client = None

    def ensure_callable_list_is_empty(self, callable_list):
        while callable_list:
            callback = callable_list.pop()
            logger.error(
                'Callback {} from CallableList {} was not unregistered before shutdown.',
                callback,
                callable_list,
                owner='tastle')

    def on_remove(self):
        logger.assert_log(
            self.is_zone_shutting_down,
            'Attempting to shutdown the zone when it is not ready:{}',
            self._zone_state,
            owner='sscholl')
        self.client_object_managers.clear()
        interactions.constraints.RequiredSlot.clear_required_slot_cache()
        self.service_manager.stop_services(self)
        self.ensure_callable_list_is_empty(self.navmesh_change_callbacks)
        self.ensure_callable_list_is_empty(self.wall_contour_update_callbacks)
        self.ensure_callable_list_is_empty(
            self.foundation_and_level_height_update_callbacks)
        self._zone_state_callbacks.clear()
        caches.clear_all_caches(force=True)
        gc.collect()
        if self.id != areaserver.WORLDBUILDER_ZONE_ID:
            indexed_manager.IndexedManager.remove_gc_collect_disable_reason(
                ZONE_OBJECT_LEAK_DISABLE_REASON)

    def on_objects_loaded(self):
        self._set_zone_state(zone_types.ZoneState.OBJECTS_LOADED)

    def on_client_connect(self, client):
        self._client = client
        self._set_zone_state(zone_types.ZoneState.CLIENT_CONNECTED)

    def on_households_and_sim_infos_loaded(self):
        self._set_zone_state(
            zone_types.ZoneState.HOUSEHOLDS_AND_SIM_INFOS_LOADED)

    def on_loading_screen_animation_finished(self):
        logger.debug('on_loading_screen_animation_finished')
        services.game_clock_service().restore_saved_clock_speed()
        services.sim_info_manager().on_loading_screen_animation_finished()
        services.get_event_manager().process_events_for_household(
            test_events.TestEvent.SimTravel,
            services.active_household(),
            zone_id=self.id)

    def _set_zone_state(self, state):
        logger.assert_raise(self._zone_state + 1 == state or
                            state == zone_types.ZoneState.SHUTDOWN_STARTED,
                            'Illegal zone state change: {} to {}',
                            self._zone_state,
                            state,
                            owner='sscholl')
        self._zone_state = state
        if state in self._zone_state_callbacks:
            self._zone_state_callbacks[state]()
            del self._zone_state_callbacks[state]

    def register_callback(self, callback_type, callback):
        logger.assert_raise(
            self._zone_state != zone_types.ZoneState.SHUTDOWN_STARTED,
            'Attempting to register callbacks after shutdown has started',
            owner='sscholl')
        if callback_type <= self._zone_state:
            callback()
            return
        self._zone_state_callbacks[callback_type].append(callback)

    def unregister_callback(self, callback_type, callback):
        if callback in self._zone_state_callbacks[callback_type]:
            self._zone_state_callbacks[callback_type].remove(callback)

    def find_object(self, obj_id, include_props=False):
        obj = self.object_manager.get(obj_id)
        if obj is None:
            obj = self.inventory_manager.get(obj_id)
        if obj is None and include_props:
            obj = self.prop_manager.get(obj_id)
        return obj

    def increment_object_count(self, obj):
        build_buy.update_zone_object_count(self.id, self.object_count)

    def decrement_object_count(self, obj):
        build_buy.update_zone_object_count(self.id, self.object_count)

    def spawn_points_gen(self):
        for spawn_point in self._spawner_data.values():
            yield spawn_point
        for spawn_point in self._dynamic_spawn_points.values():
            yield spawn_point

    def setup_spawner_data(self, spawner_data_array, zone_id):
        self._spawner_data = {}
        for (index, spawner_data) in enumerate(spawner_data_array):
            self._spawner_data[index] = world.spawn_point.WorldSpawnPoint(
                spawner_data, index, self.id)

    def add_dynamic_spawn_point(self, spawn_point):
        self._dynamic_spawn_points[spawn_point.spawn_point_id] = spawn_point

    def remove_dynamic_spawn_point(self, spawn_point):
        self._dynamic_spawn_points.pop(spawn_point.spawn_point_id)

    def supress_goals_for_spawn_points(self):
        if not self._spawner_data:
            return
        self.spawn_point_ids = frozenset(
            spawn_point.spawn_point_id
            for spawn_point in self._spawner_data.values())
        for spawn_point in self._spawner_data.values():
            spawn_point.add_goal_suppression_region_to_quadtree()

    def get_spawn_point_ignore_constraint(self):
        objects_to_ignore = set()
        for spawn_point in self._spawner_data.values():
            objects_to_ignore.add(spawn_point.spawn_point_id)
        return Constraint(objects_to_ignore=objects_to_ignore)

    def _get_spawn_points_with_lot_id_and_tags(self,
                                               lot_id=None,
                                               sim_spawner_tags=None,
                                               ignore_point_validation=False,
                                               except_lot_id=None):
        spawn_points = []
        if not sim_spawner_tags:
            return
        for tag in sim_spawner_tags:
            for spawn_point in self.spawn_points_gen():
                if lot_id is not None and spawn_point.lot_id != lot_id:
                    pass
                if ignore_point_validation or except_lot_id is not None and spawn_point.lot_id == except_lot_id:
                    pass
                tags = spawn_point.get_tags()
                while tag in tags:
                    spawn_points.append(spawn_point)
        return spawn_points

    def get_spawn_point(self,
                        lot_id=None,
                        sim_spawner_tags=None,
                        must_have_tags=False,
                        ignore_point_validation=False):
        spawn_points = list(self.spawn_points_gen())
        if not spawn_points:
            return
        spawn_points_with_tags = self._get_spawn_points_with_lot_id_and_tags(
            lot_id=lot_id,
            sim_spawner_tags=sim_spawner_tags,
            ignore_point_validation=ignore_point_validation)
        if spawn_points_with_tags:
            return random.choice(spawn_points_with_tags)
        if not must_have_tags:
            return random.choice(spawn_points)
        return

    def get_spawn_points_constraint(self,
                                    sim_info=None,
                                    lot_id=None,
                                    sim_spawner_tags=None,
                                    except_lot_id=None):
        spawn_point_option = SpawnPointOption.SPAWN_ANY_POINT_WITH_CONSTRAINT_TAGS
        search_tags = sim_spawner_tags
        spawn_point_id = None
        original_spawn_point = None
        spawn_point_option = sim_info.spawn_point_option if sim_info.spawn_point_option is not None else SpawnPointOption.SPAWN_SAME_POINT
        spawn_point_id = sim_info.spawn_point_id
        original_spawn_point = self._spawner_data[
            spawn_point_id] if spawn_point_id is not None and spawn_point_id in self._spawner_data.keys(
            ) else None
        if sim_info is not None and sim_spawner_tags is None and (
                spawn_point_option ==
                SpawnPointOption.SPAWN_ANY_POINT_WITH_SAVED_TAGS or
                spawn_point_option ==
                SpawnPointOption.SPAWN_DIFFERENT_POINT_WITH_SAVED_TAGS):
            search_tags = sim_info.spawner_tags
        points = []
        if search_tags is not None:
            spawn_points_with_tags = self._get_spawn_points_with_lot_id_and_tags(
                lot_id=lot_id,
                sim_spawner_tags=search_tags,
                except_lot_id=except_lot_id)
            if spawn_points_with_tags:
                for spawn_point in spawn_points_with_tags:
                    if spawn_point_option == SpawnPointOption.SPAWN_DIFFERENT_POINT_WITH_SAVED_TAGS and original_spawn_point and spawn_point.spawn_point_id == original_spawn_point.spawn_point_id:
                        pass
                    position_constraints = spawn_point.get_position_constraints(
                    )
                    while position_constraints:
                        points.extend(position_constraints)
                if spawn_point_option == SpawnPointOption.SPAWN_DIFFERENT_POINT_WITH_SAVED_TAGS and original_spawn_point and points:
                    comparable_spawn_point_center = sims4.math.Vector3(
                        original_spawn_point.center.x, 0.0,
                        original_spawn_point.center.z)
                    weighted_points = [(
                        (comparable_spawn_point_center -
                         point.single_point()[0]).magnitude(), point)
                                       for point in points]
                    selected_spawn_point = sims4.random.weighted_random_item(
                        weighted_points)
                    return interactions.constraints.create_constraint_set(set(
                        selected_spawn_point))
                if points:
                    return interactions.constraints.create_constraint_set(
                        points)
        if spawn_point_option == SpawnPointOption.SPAWN_SAME_POINT and original_spawn_point:
            points = original_spawn_point.get_position_constraints()
            if points:
                return interactions.constraints.create_constraint_set(points)
        for spawn_point in self.spawn_points_gen():
            position_constraints = spawn_point.get_position_constraints()
            while position_constraints:
                points.extend(position_constraints)
        if points:
            return interactions.constraints.create_constraint_set(points)
        logger.warn(
            'There are no spawn locations on this lot.  The corners of the lot are being used instead: {}',
            services.current_zone().lot,
            owner='rmccord')
        return self.get_lot_corners_constraint_set()

    def get_lot_corners_constraint_set(self):
        lot_center = self.lot.center
        lot_corners = services.current_zone().lot.corners
        routing_surface = routing.SurfaceIdentifier(
            services.current_zone().id, 0, routing.SURFACETYPE_WORLD)
        constraint_list = []
        for corner in lot_corners:
            diff = lot_center - corner
            if diff.magnitude_squared() != 0:
                towards_center_vec = sims4.math.vector_normalize(lot_center -
                                                                 corner) * 0.1
            else:
                towards_center_vec = sims4.math.Vector3.ZERO()
            new_corner = corner + towards_center_vec
            constraint_list.append(interactions.constraints.Position(
                new_corner, routing_surface=routing_surface))
        return create_constraint_set(constraint_list)

    def validate_spawn_points(self):
        if not self._spawner_data and not self._dynamic_spawn_points:
            return
        dest_handles = set()
        lot_center = self.lot.center
        lot_corners = self.lot.corners
        routing_surface = routing.SurfaceIdentifier(self.id, 0,
                                                    routing.SURFACETYPE_WORLD)
        for corner in lot_corners:
            diff = lot_center - corner
            if diff.magnitude_squared() != 0:
                towards_center_vec = sims4.math.vector_normalize(lot_center -
                                                                 corner) * 0.1
            else:
                towards_center_vec = sims4.math.Vector3.ZERO()
            new_corner = corner + towards_center_vec
            location = routing.Location(
                new_corner, sims4.math.Quaternion.IDENTITY(), routing_surface)
            dest_handles.add(routing.connectivity.Handle(location))
        for spawn_point in self.spawn_points_gen():
            spawn_point.reset_valid_slots()
            routing_context = routing.PathPlanContext()
            routing_context.set_key_mask(routing.FOOTPRINT_KEY_ON_LOT |
                                         routing.FOOTPRINT_KEY_OFF_LOT)
            if spawn_point.footprint_id is not None:
                routing_context.ignore_footprint_contour(
                    spawn_point.footprint_id)
            spawn_point.validate_slots(dest_handles, routing_context)

    def _check_navmesh_updated_alarm_callback(self, *_):
        new_navmesh_id = interactions.utils.routing.routing.planner_build_id()
        if self.navmesh_id != new_navmesh_id:
            self.navmesh_id = new_navmesh_id
            self.navmesh_change_callbacks()
            if gsi_handlers.routing_handlers.build_archiver.enabled:
                gsi_handlers.routing_handlers.archive_build(new_navmesh_id)

    def on_build_buy_enter(self):
        self.is_in_build_buy = True

    def on_build_buy_exit(self):
        self.is_in_build_buy = False
        self._add_expenditures_and_do_post_bb_fixup()
        services.get_event_manager().process_events_for_household(
            test_events.TestEvent.OnExitBuildBuy, None)

    def set_to_fixup_on_build_buy_exit(self, obj):
        if self.objects_to_fixup_post_bb is None:
            self.objects_to_fixup_post_bb = weakref.WeakSet()
        self.objects_to_fixup_post_bb.add(obj)

    def _add_expenditures_and_do_post_bb_fixup(self):
        if self.objects_to_fixup_post_bb is not None:
            household = self.lot.get_household()
            rebate_manager = household.rebate_manager if household is not None else None
            active_household_id = services.active_household_id()
            for obj in self.objects_to_fixup_post_bb:
                if rebate_manager is not None:
                    rebate_manager.add_rebate_for_object(obj)
                obj.try_post_bb_fixup(active_household_id=active_household_id)
            self.objects_to_fixup_post_bb = None

    @property
    def save_slot_data_id(self):
        return self._save_slot_data_id

    def save_zone(self, save_slot_data=None):
        zone_data_msg = self._get_zone_proto()
        zone_data_msg.ClearField('gameplay_zone_data')
        gameplay_zone_data = zone_data_msg.gameplay_zone_data
        gameplay_zone_data.lot_owner_household_id_on_save = self.lot.owner_household_id
        gameplay_zone_data.venue_type_id_on_save = self.venue_service.venue.guid64 if self.venue_service.venue is not None else 0
        gameplay_zone_data.active_household_id_on_save = services.active_household_id(
        )
        self.lot.save(gameplay_zone_data)
        if self.lot.front_door_id:
            zone_data_msg.front_door_id = self.lot.front_door_id
        num_spawn_points = len(self._spawner_data)
        spawn_point_ids = [0] * num_spawn_points
        for (spawn_point_id, spawn_point) in self._spawner_data.items():
            spawn_point_ids[spawn_point.spawn_point_index] = spawn_point_id
        zone_data_msg.ClearField('spawn_point_ids')
        zone_data_msg.spawn_point_ids.extend(spawn_point_ids)
        zone_objects_message = serialization.ZoneObjectData()
        object_list = serialization.ObjectList()
        zone_objects_message.zone_id = self.id
        persistence_service = services.get_persistence_service()
        open_street_data = persistence_service.get_open_street_proto_buff(
            self.open_street_id)
        if open_street_data is not None:
            open_street_data.Clear()
            add_proto_to_persistence = False
        else:
            open_street_data = serialization.OpenStreetsData()
            add_proto_to_persistence = True
        open_street_data.world_id = self.open_street_id
        open_street_data.nbh_id = self.neighborhood_id
        open_street_data.sim_time_on_save = services.time_service(
        ).sim_timeline.now.absolute_ticks()
        open_street_data.active_household_id_on_save = services.active_household_id(
        )
        open_street_data.active_zone_id_on_save = self.id
        self.service_manager.save_all_services(
            persistence_service,
            persistence_error_types.ErrorCodes.ZONE_SERVICES_SAVE_FAILED,
            object_list=object_list,
            zone_data=zone_data_msg,
            open_street_data=open_street_data,
            save_slot_data=save_slot_data)
        zone_objects_message.objects = object_list
        if add_proto_to_persistence:
            services.get_persistence_service().add_open_street_proto_buff(
                open_street_data)
        persistence_module.run_persistence_operation(
            persistence_module.PersistenceOpType.kPersistenceOpSaveZoneObjects,
            zone_objects_message, 0, None)

    def load_zone(self):
        zone_data_proto = self._get_zone_proto()
        self.neighborhood_id = zone_data_proto.neighborhood_id
        self.open_street_id = zone_data_proto.world_id
        self.service_manager.load_all_services(zone_data=zone_data_proto)
        self._first_visit_to_zone = not protocol_buffer_utils.has_field(
            zone_data_proto.gameplay_zone_data, 'venue_type_id_on_save')
        open_street_data = services.get_persistence_service(
        ).get_open_street_proto_buff(self.open_street_id)
        if open_street_data is not None:
            self._time_of_last_open_street_save = DateAndTime(
                open_street_data.sim_time_on_save)
        spawn_points = {}
        if zone_data_proto.spawn_point_ids:
            for (index,
                 spawn_point_id) in enumerate(zone_data_proto.spawn_point_ids):
                spawn_point = self._spawner_data[index]
                spawn_point.spawn_point_id = spawn_point_id
                spawn_points[spawn_point_id] = spawn_point
        else:
            for (index, spawn_point) in enumerate(self._spawner_data.values()):
                spawn_point_id = id_generator.generate_object_id()
                spawn_point.spawn_point_id = spawn_point_id
                spawn_points[spawn_point_id] = spawn_point
        self._spawner_data = spawn_points
        self.lot.load(zone_data_proto.gameplay_zone_data)
        for spawn_point in self._spawner_data.values():
            while spawn_point.has_tag(
                    SpawnPoint.
                    ARRIVAL_SPAWN_POINT_TAG) and spawn_point.lot_id == self.lot.lot_id:
                self._active_lot_arrival_spawn_point = spawn_point
        return True

    def load_zone_front_door(self):
        zone_data_proto = self._get_zone_proto()
        from objects.doors.front_door import load_front_door, find_and_set_front_door
        if zone_data_proto.HasField('front_door_id'):
            load_front_door(zone_data_proto.front_door_id)
        else:
            find_and_set_front_door()

    def lot_owner_household_changed_between_save_and_load(self):
        zone_data_proto = self._get_zone_proto()
        if zone_data_proto is None or self.lot is None:
            return False
        gameplay_zone_data = zone_data_proto.gameplay_zone_data
        if not protocol_buffer_utils.has_field(
                gameplay_zone_data, 'lot_owner_household_id_on_save'):
            return False
        return gameplay_zone_data.lot_owner_household_id_on_save != self.lot.owner_household_id

    def active_household_changed_between_save_and_load(self):
        zone_data_proto = self._get_zone_proto()
        if zone_data_proto is None:
            return False
        gameplay_zone_data = zone_data_proto.gameplay_zone_data
        if not protocol_buffer_utils.has_field(gameplay_zone_data,
                                               'active_household_id_on_save'):
            return False
        return gameplay_zone_data.active_household_id_on_save != services.active_household_id(
        )

    def update_household_objects_ownership(self):
        zone_data_proto = self._get_zone_proto()
        if zone_data_proto is None:
            return
        venue_instance = self.venue_service.venue
        if venue_instance is None or not venue_instance.venue_requires_front_door:
            return
        if self.lot.owner_household_id == 0:
            self._set_zone_objects_household_owner_id(None)
        elif self.lot.owner_household_id == services.active_household_id():
            gameplay_zone_data = zone_data_proto.gameplay_zone_data
            if not protocol_buffer_utils.has_field(
                    gameplay_zone_data,
                    'active_household_id_on_save') or gameplay_zone_data.lot_owner_household_id_on_save != services.active_household_id(
                    ):
                self._set_zone_objects_household_owner_id(
                    services.active_household_id())

    def _set_zone_objects_household_owner_id(self, household_id):
        for obj in services.object_manager(self.id).get_all():
            while obj.is_on_active_lot():
                obj.set_household_owner_id(household_id)
        for (_, inventory) in self.lot.get_all_object_inventories_gen():
            for inv_obj in inventory:
                inv_obj.set_household_owner_id(household_id)

    def venue_type_changed_between_save_and_load(self):
        zone_data_proto = self._get_zone_proto()
        if zone_data_proto is None or self.venue_service.venue is None:
            return False
        gameplay_zone_data = zone_data_proto.gameplay_zone_data
        if not protocol_buffer_utils.has_field(gameplay_zone_data,
                                               'venue_type_id_on_save'):
            return False
        return False

    def should_restore_sis(self):
        if services.game_clock_service(
        ).time_has_passed_in_world_since_zone_save() or (
                self.venue_type_changed_between_save_and_load() or
            (self.lot_owner_household_changed_between_save_and_load() or
             self.active_household_changed_between_save_and_load(
             ))) or self.is_first_visit_to_zone:
            return False
        return True

    def get_active_lot_owner_household(self):
        if self.lot is None:
            return
        return services.household_manager().get(self.lot.owner_household_id)

    def time_elapsed_since_last_open_street_save(self):
        client_connect_world_time = self.game_clock.client_connect_world_time
        if client_connect_world_time is None:
            return TimeSpan.ZERO
        if self._time_of_last_open_street_save is None:
            return TimeSpan.ZERO
        time_elapsed = client_connect_world_time - self._time_of_last_open_street_save
        return time_elapsed

    def time_has_passed_in_world_since_open_street_save(self):
        time_elapsed = self.time_elapsed_since_last_open_street_save()
        if time_elapsed > TimeSpan.ZERO:
            return True
        return False
