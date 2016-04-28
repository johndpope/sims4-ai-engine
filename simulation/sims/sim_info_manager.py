import argparse
import itertools
from audio.primitive import play_tunable_audio
from clock import ClockSpeedMode
from date_and_time import DateAndTime
from filters.tunable import FilterResult
from interactions.si_restore import SuperInteractionRestorer
from interactions.utils.death import DeathTracker
from objects import ALL_HIDDEN_REASONS, HiddenReasonFlag
from objects.object_enums import ResetReason
from objects.object_manager import DistributableObjectManager
from sims.genealogy_tracker import genealogy_caching
from sims.sim_outfits import OutfitCategory
from sims4.callback_utils import CallableList
from singletons import DEFAULT
from situations.situation_types import GreetedStatus
from world.travel_tuning import TravelTuning
import alarms
import caches
import interactions.utils.routing
import objects
import services
import sims.baby
import sims.sim_info
import sims.sim_info_types
import sims.sim_outfits
import sims.sim_spawner
import sims4.log
logger = sims4.log.Logger('SimInfoManager')
relationship_setup_logger = sims4.log.Logger('DefaultRelSetup', default_owner='manus')

class ShouldSpawnResult:
    __qualname__ = 'ShouldSpawnResult'
    CURRENT_POSITION = 0
    SPAWNER_POSITION = 1

    def __init__(self, should_spawn, position_hint=CURRENT_POSITION):
        self.should_spawn = should_spawn
        self.position_hint = position_hint

    @property
    def startup_location(self):
        if self.position_hint == ShouldSpawnResult.CURRENT_POSITION:
            return DEFAULT

    def __bool__(self):
        return self.should_spawn

    def __repr__(self):
        return '<ShouldSpawnResult: {} {}>'.format(self.should_spawn, self.position_hint)

class SimInfoManager(DistributableObjectManager):
    __qualname__ = 'SimInfoManager'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sim_infos_saved_in_zone = []
        self._sim_infos_saved_in_open_street = []
        self._sims_traveled_to_zone = []
        self._sim_ids_to_push_go_home = []
        self._sim_infos_excluded_from_preroll = set()
        self._startup_sims_set = set()
        self._startup_time = None
        self._return_sim_to_home_lot_alarm_handles = set()
        self._sim_ids_at_work = set()
        self._bring_sims_home = self._should_run_bring_home_behavior()

    def _should_run_bring_home_behavior(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--no_bring_home', action='store_true')
        (args, unused_args) = parser.parse_known_args()
        args_dict = vars(args)
        no_bring_home = args_dict.get('no_bring_home')
        return not no_bring_home

    def flush_to_client_on_teardown(self):
        for sim_info in self.objects:
            sim_info.flush_to_client_on_teardown()

    def on_client_disconnect(self, client):
        self._clear_return_sim_to_home_lot_alarm_handles()
        return super().on_client_disconnect(client)

    def _clear_return_sim_to_home_lot_alarm_handles(self):
        for alarm_handle in self._return_sim_to_home_lot_alarm_handles:
            alarms.cancel_alarm(alarm_handle)
        self._return_sim_to_home_lot_alarm_handles.clear()

    def add_sim_info_if_not_in_manager(self, sim_info):
        if sim_info.id in self._objects:
            pass
        else:
            self.add(sim_info)

    def _calculate_sim_filter_score(self, sim_info, filter_terms, start_time=None, end_time=None, **kwargs):
        total_result = FilterResult(sim_info=sim_info)
        start_time_ticks = start_time.absolute_ticks() if start_time is not None else None
        end_time_ticks = end_time.absolute_ticks() if end_time is not None else None
        for filter_term in filter_terms:
            result = filter_term.calculate_score(sim_info, start_time_ticks=start_time_ticks, end_time_ticks=end_time_ticks, **kwargs)
            total_result.combine_with_other_filter_result(result)
            while total_result.score == 0:
                break
        return total_result

    def find_sims_matching_filter(self, filter_terms, constrained_sim_ids=None, **kwargs):
        results = []
        sim_ids = constrained_sim_ids if constrained_sim_ids is not None else self.keys()
        for sim_id in sim_ids:
            sim_info = self.get(sim_id)
            if sim_info is None:
                pass
            result = self._calculate_sim_filter_score(sim_info, filter_terms, **kwargs)
            while result.score > 0:
                results.append(result)
        return results

    def save(self, zone_data=None, open_street_data=None, **kwargs):
        owning_household = services.current_zone().get_active_lot_owner_household()
        situation_manager = services.get_zone_situation_manager()
        for sim_info in self.get_all():
            while sim_info.account_id is not None:
                sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
                if sim is not None:
                    if sim.is_selectable or owning_household is not None and sim_info in owning_household:
                        if sim.is_on_active_lot() or sim.has_hidden_flags(HiddenReasonFlag.RABBIT_HOLE):
                            sim_info._serialization_option = sims.sim_info_types.SimSerializationOption.LOT
                        else:
                            sim_info._serialization_option = sims.sim_info_types.SimSerializationOption.OPEN_STREETS
                            sim_info._serialization_option = situation_manager.get_sim_serialization_option(sim)
                    else:
                        sim_info._serialization_option = situation_manager.get_sim_serialization_option(sim)
                sim_info.save_sim()

    def on_all_households_and_sim_infos_loaded(self, client):
        for sim_info in self.values():
            sim_info.on_all_households_and_sim_infos_loaded()
            zone = services.current_zone()
            if sim_info.zone_id == zone.id and (sim_info.serialization_option == sims.sim_info_types.SimSerializationOption.LOT or sim_info.serialization_option == sims.sim_info_types.SimSerializationOption.UNDECLARED):
                self._sim_infos_saved_in_zone.append(sim_info)
            else:
                while sim_info.world_id == zone.open_street_id and sim_info.serialization_option == sims.sim_info_types.SimSerializationOption.OPEN_STREETS:
                    self._sim_infos_saved_in_open_street.append(sim_info)

    def add_sims_to_zone(self, sim_list):
        self._sims_traveled_to_zone.extend(sim_list)

    def exclude_sim_info_from_preroll(self, sim_info):
        self._sim_infos_excluded_from_preroll.add(sim_info)

    def on_spawn_sims_for_zone_spin_up(self, client):
        current_zone = services.current_zone()
        for sim_id in tuple(self._sims_traveled_to_zone):
            if sim_id == 0:
                self._sims_traveled_to_zone.remove(sim_id)
            sim_info = self.get(sim_id)
            if sim_info is None:
                logger.error('sim id {} for traveling did not spawn because sim info does not exist.', sim_id, owner='msantander')
            self._spawn_sim(sim_info, startup_location=None)
            while sim_info.get_current_outfit()[0] == OutfitCategory.SLEEP:
                random_everyday_outfit = sim_info.sim_outfits.get_random_outfit([OutfitCategory.EVERYDAY])
                sim_info.set_current_outfit(random_everyday_outfit)
        if self._sims_traveled_to_zone:
            play_tunable_audio(TravelTuning.TRAVEL_SUCCESS_AUDIO_STING)
        else:
            play_tunable_audio(TravelTuning.NEW_GAME_AUDIO_STING)
        current_zone_owner_household_id = current_zone.lot.owner_household_id
        if current_zone_owner_household_id != 0:
            zone_owner_household = services.household_manager().get(current_zone_owner_household_id)
            if zone_owner_household is not None:
                zone_household_is_active_household = client.household.id == zone_owner_household.id
                any_members_spawned = self._spawn_lot_owner_household(zone_owner_household, zone_household_is_active_household)
                if zone_household_is_active_household and not any_members_spawned:
                    self._clear_return_sim_to_home_lot_alarm_handles()
                    while True:
                        for sim_info in zone_owner_household.sim_info_gen():
                            while not sim_info.is_dead:
                                logger.debug('Force spawn household sim:{}', sim_info, owner='sscholl')
                                self._spawn_sim(sim_info, startup_location=None)
        for sim_info in self._sim_infos_saved_in_zone:
            result = self._should_spawn_zone_saved_sim(sim_info)
            logger.debug('Should spawn zone sim:{} {}', sim_info, bool(result), owner='sscholl')
            while result:
                self._spawn_sim(sim_info, startup_location=result.startup_location)
        for sim_info in self._sim_infos_saved_in_open_street:
            result = self._should_spawn_open_street_saved_sim(sim_info)
            logger.debug('Should spawn open street sim:{} {}', sim_info, bool(result), owner='sscholl')
            while result:
                self._spawn_sim(sim_info, startup_location=result.startup_location)
                if len(self._sims_traveled_to_zone) > 0 and (client.household is not None and client.household.get_sim_info_by_id(sim_info.sim_id)) and sim_info.sim_id not in self._sims_traveled_to_zone:
                    self._sim_ids_to_push_go_home.append(sim_info.sim_id)
        self._on_spawn_sim_for_zone_spin_up_completed(client)

    def _spawn_lot_owner_household(self, zone_owner_household, zone_household_is_active_household):
        current_time = services.time_service().sim_now
        any_household_members_spawned = False
        for sim_info in zone_owner_household.sim_info_gen():
            result = self._should_spawn_lot_owner_sim(sim_info, zone_household_is_active_household)
            logger.debug('Should spawn household sim:{} {}', sim_info, bool(result), owner='sscholl')
            if result:
                any_household_members_spawned |= self._spawn_sim(sim_info, startup_location=result.startup_location)
            elif sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS):
                any_household_members_spawned = True
            else:
                while not sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS) and (not sim_info.is_dead and sim_info.game_time_bring_home is not None) and self._bring_sims_home:
                    time_to_expire = DateAndTime(sim_info.game_time_bring_home)
                    if current_time < time_to_expire:
                        time_till_spawn = time_to_expire - current_time
                        self._return_sim_to_home_lot_alarm_handles.add(alarms.add_alarm(sim_info, time_till_spawn, self.return_sim_to_home_lot))
        return any_household_members_spawned

    def _spawn_sim(self, sim_info, startup_location=DEFAULT):
        if sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS):
            return True
        if sim_info.is_baby:
            spawn_result = sims.baby.on_sim_spawn(sim_info)
        else:
            if startup_location is DEFAULT:
                startup_location = sim_info.startup_sim_location
            spawn_result = sims.sim_spawner.SimSpawner.spawn_sim(sim_info, sim_location=startup_location, from_load=True)
        return spawn_result

    def _should_bring_home_to_current_lot(self, sim_info):
        if not self._bring_sims_home:
            return False
        if not sim_info.lives_here:
            return False
        current_zone = services.current_zone()
        if sim_info.zone_id == current_zone.id:
            return False
        if sim_info.is_dead:
            return False
        if sim_info.zone_id == 0:
            return True
        if sim_info.game_time_bring_home is not None:
            time_to_expire = DateAndTime(sim_info.game_time_bring_home)
            return services.time_service().sim_now >= time_to_expire
        return True

    def _handle_send_home_based_on_time(self, sim_info):
        if sim_info.lives_here:
            return False
        if sim_info.game_time_bring_home is None:
            return False
        time_to_expire = DateAndTime(sim_info.game_time_bring_home)
        if services.time_service().sim_now >= time_to_expire:
            sim_info.inject_into_inactive_zone(sim_info.household.home_zone_id)
            return True
        return False

    def _should_spawn_lot_owner_sim(self, sim_info, zone_household_is_active_household):
        if sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS):
            return ShouldSpawnResult(False)
        current_zone = services.current_zone()
        save_game_data = services.get_persistence_service().get_save_game_data_proto()
        if zone_household_is_active_household and (current_zone.is_first_visit_to_zone or save_game_data.save_slot.active_household_id != sim_info.household_id):
            return ShouldSpawnResult(True, ShouldSpawnResult.SPAWNER_POSITION)
        if current_zone.lot_owner_household_changed_between_save_and_load():
            return ShouldSpawnResult(True, ShouldSpawnResult.SPAWNER_POSITION)
        if self._should_bring_home_to_current_lot(sim_info):
            return ShouldSpawnResult(True, ShouldSpawnResult.SPAWNER_POSITION)
        if sim_info in self._sim_infos_saved_in_zone:
            hint = ShouldSpawnResult.CURRENT_POSITION
            if sim_info.serialization_option == sims.sim_info_types.SimSerializationOption.UNDECLARED:
                hint = ShouldSpawnResult.SPAWNER_POSITION
            return ShouldSpawnResult(True, hint)
        if sim_info in self._sim_infos_saved_in_open_street:
            if current_zone.time_has_passed_in_world_since_open_street_save():
                return ShouldSpawnResult(True, ShouldSpawnResult.SPAWNER_POSITION)
            return ShouldSpawnResult(True, ShouldSpawnResult.CURRENT_POSITION)
        return ShouldSpawnResult(False)

    def _should_spawn_zone_saved_sim(self, sim_info):
        if sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS):
            return ShouldSpawnResult(False)
        current_zone = services.current_zone()
        situation_manager = services.get_zone_situation_manager()
        if sim_info.lives_here:
            return ShouldSpawnResult(False)
        if self._handle_send_home_based_on_time(sim_info):
            return ShouldSpawnResult(False)
        if sim_info.is_selectable:
            return ShouldSpawnResult(True, ShouldSpawnResult.CURRENT_POSITION)
        if current_zone.lot_owner_household_changed_between_save_and_load() or current_zone.venue_type_changed_between_save_and_load():
            sim_info.inject_into_inactive_zone(sim_info.household.home_zone_id)
            return ShouldSpawnResult(False)
        if current_zone.active_household_changed_between_save_and_load() or current_zone.game_clock.time_has_passed_in_world_since_zone_save():
            if services.current_zone().venue_service.venue.requires_visitation_rights:
                if situation_manager.get_npc_greeted_status_during_zone_fixup(sim_info) != GreetedStatus.GREETED:
                    sim_info.inject_into_inactive_zone(sim_info.household.home_zone_id)
                    return ShouldSpawnResult(False)
                return ShouldSpawnResult(True, ShouldSpawnResult.CURRENT_POSITION)
            else:
                return ShouldSpawnResult(True, ShouldSpawnResult.CURRENT_POSITION)
        return ShouldSpawnResult(True, ShouldSpawnResult.CURRENT_POSITION)

    def _should_spawn_open_street_saved_sim(self, sim_info):
        if sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS):
            return ShouldSpawnResult(False)
        current_zone = services.current_zone()
        if sim_info.lives_here:
            return ShouldSpawnResult(False)
        if self._handle_send_home_based_on_time(sim_info):
            return ShouldSpawnResult(False)
        if sim_info.is_selectable:
            return ShouldSpawnResult(True, ShouldSpawnResult.CURRENT_POSITION)
        if current_zone.time_has_passed_in_world_since_open_street_save():
            sim_info.inject_into_inactive_zone(sim_info.household.home_zone_id)
            return ShouldSpawnResult(False)
        return ShouldSpawnResult(True, ShouldSpawnResult.CURRENT_POSITION)

    def _on_spawn_sim_for_zone_spin_up_completed(self, client):
        for sim_info in self.values():
            if sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS) or sim_info.is_selectable:
                sim_info.commodity_tracker.start_low_level_simulation()
            sim_info.set_default_data()
            while sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS) and not sim_info.is_npc:
                sim_info.aspiration_tracker.refresh_progress(sim_info)
        client.refresh_achievement_data()
        services.get_event_manager().unregister_unused_handlers()
        for sim_info in client.selectable_sims:
            while sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS):
                sim_info.aspiration_tracker.initialize_aspiration()
                sim_info.career_tracker.activate_career_aspirations()
        self._set_default_genealogy()
        for sim_info in self.values():
            sim_info.relationship_tracker.send_relationship_info()

    def _set_default_genealogy(self):

        def get_spouse(sim_info):
            spouse = None
            spouse_id = sim_info.spouse_sim_id
            if spouse_id is not None:
                spouse = self.get(spouse_id)
            return spouse

        depth = 3
        with genealogy_caching():
            for sim_info in self.values():
                extended_family = set()
                candidates = set([sim_info])
                spouse = get_spouse(sim_info)
                if spouse is not None:
                    candidates.add(spouse)
                    extended_family.add(spouse)
                for _ in range(depth):
                    new_candidates = set()
                    for _id in itertools.chain.from_iterable(x.genealogy.get_immediate_family_sim_ids_gen() for x in candidates):
                        family_member = self.get(_id)
                        while family_member is not None and family_member not in extended_family:
                            new_candidates.add(family_member)
                            spouse = get_spouse(family_member)
                            if spouse is not None and family_member not in extended_family:
                                new_candidates.add(spouse)
                    candidates = new_candidates
                    extended_family.update(candidates)
                extended_family -= set([sim_info])
                for family_member in extended_family:
                    sim_info.add_family_link(family_member)
                    family_member.add_family_link(sim_info)
        relationship_setup_logger.info('_set_default_genealogy updated genealogy links for {} sim_infos.', len(self.values()))

    def return_sim_to_home_lot(self, alarm_handle):
        self._return_sim_to_home_lot_alarm_handles.discard(alarm_handle)
        sim_info = alarm_handle.owner
        if sim_info is None or sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS) or sim_info.is_dead:
            return
        success = sims.sim_spawner.SimSpawner.spawn_sim(sim_info)
        if success:
            client = services.client_manager().get_client_by_household_id(sim_info.household_id)
            if client is not None:
                client.add_selectable_sim_info(sim_info)

    def get_traveled_to_zone_sim_infos(self):
        return [self.get(sim_id) for sim_id in self._sims_traveled_to_zone]

    def get_sim_infos_saved_in_zone(self):
        return list(self._sim_infos_saved_in_zone)

    def get_sim_infos_saved_in_open_streets(self):
        return list(self._sim_infos_saved_in_open_street)

    def instanced_sims_gen(self, allow_hidden_flags=0):
        for info in self.get_all():
            sim = info.get_sim_instance(allow_hidden_flags=allow_hidden_flags)
            while sim is not None:
                yield sim

    def instanced_sims_on_active_lot_gen(self, allow_hidden_flags=0):
        for sim in self.instanced_sims_gen(allow_hidden_flags=allow_hidden_flags):
            while sim.is_on_active_lot():
                yield sim

    def instanced_sim_info_including_baby_gen(self, allow_hidden_flags=0):
        object_manager = services.object_manager()
        for sim_info in self.get_all():
            if sim_info.is_baby:
                sim_or_baby = object_manager.get(sim_info.id)
            else:
                sim_or_baby = sim_info.get_sim_instance(allow_hidden_flags=allow_hidden_flags)
            while sim_or_baby is not None:
                yield sim_info

    def get_player_npc_sim_count(self):
        npc = 0
        player = 0
        for sim in self.instanced_sims_gen(allow_hidden_flags=ALL_HIDDEN_REASONS):
            if sim.is_selectable:
                player += 1
            else:
                while sim.sim_info.is_npc:
                    npc += 1
        return (player, npc)

    def are_npc_sims_in_open_streets(self):
        return any(s.is_npc and not s.is_on_active_lot() for s in self.instanced_sims_gen(allow_hidden_flags=ALL_HIDDEN_REASONS))

    def get_sim_info_by_name(self, first_name, last_name):
        first_name = first_name.lower()
        last_name = last_name.lower()
        for info in self.get_all():
            while info.first_name.lower() == first_name and info.last_name.lower() == last_name:
                return info

    def auto_satisfy_sim_motives(self):
        for sim in self.instanced_sims_gen():
            statistics = list(sim.commodities_gen())
            for statistic in statistics:
                if statistic.is_skill:
                    pass
                statistic.set_to_auto_satisfy_value()

    def handle_event(self, sim_info, event, resolver):
        self._sim_started_startup_interaction(sim_info, event, resolver)

    def _run_preroll_autonomy(self):
        used_target_list = []
        sim_list = list(self._startup_sims_set)
        for sim_id in sim_list:
            sim_info = self.get(sim_id)
            if sim_info is None:
                self._startup_sims_set.discard(sim_id)
            if sim_info in self._sim_infos_excluded_from_preroll:
                self._startup_sims_set.discard(sim_id)
            sim = sim_info.get_sim_instance()
            if sim is None:
                self._startup_sims_set.discard(sim_id)
            caches.clear_all_caches()
            sim.set_allow_route_instantly_when_hitting_marks(True)
            (interaction_started, interaction_target) = sim.run_preroll_autonomy(used_target_list)
            if interaction_started:
                logger.debug('sim: {} started interaction:{} as part of preroll autonomy.', sim, interaction_started)
                used_target_list.append(interaction_target)
            else:
                logger.debug('sim: {} failed to choose interaction as part of preroll autonomy.', sim)
                self._startup_sims_set.discard(sim_id)

    def _run_startup_interactions(self, create_startup_interactions_function):
        try:
            create_startup_interactions_function()
        except Exception as e:
            logger.exception('Exception raised while trying to startup interactions.', exc=e)

    def startup_sim_set_gen(self, first_time_load_zone=False):
        for sim in self.instanced_sims_gen():
            sim_id = sim.id
            if sim_id in self._sims_traveled_to_zone:
                pass
            if sim_id in list(self._sim_ids_to_push_go_home):
                while sim.is_on_active_lot(tolerance=sim.get_off_lot_autonomy_tolerance()):
                    self._sim_ids_to_push_go_home.remove(sim_id)
                    if sim_id in self._sim_ids_at_work:
                        pass
                    if first_time_load_zone and not sim.sim_info.is_npc:
                        pass
                    yield sim_id
            if sim_id in self._sim_ids_at_work:
                pass
            if first_time_load_zone and not sim.sim_info.is_npc:
                pass
            yield sim_id

    def restore_sim_si_state(self):
        super_interaction_restorer = SuperInteractionRestorer()
        super_interaction_restorer.restore_sim_si_state()

    def verify_travel_sims_outfits(self):
        for traveled_sim_id in self._sims_traveled_to_zone:
            sim_info = self.get(traveled_sim_id)
            while sim_info is not None:
                if sim_info.get_current_outfit()[0] == sims.sim_outfits.OutfitCategory.BATHING:
                    sim_info.set_current_outfit((sims.sim_outfits.OutfitCategory.EVERYDAY, 0))

    def run_preroll_autonomy(self, first_time_load_zone=False):
        self._startup_sims_set = set(self.startup_sim_set_gen(first_time_load_zone=first_time_load_zone))
        self._run_startup_interactions(self._run_preroll_autonomy)
        self.verify_travel_sims_outfits()

    def push_sims_to_go_home(self):
        go_home_affordance = sims.sim_info.SimInfo.GO_HOME_FROM_OPEN_STREET
        if go_home_affordance is None:
            return
        for sim_id in self._sim_ids_to_push_go_home:
            sim_info = self.get(sim_id)
            if sim_info is None:
                pass
            sim = sim_info.get_sim_instance()
            while sim is not None:
                context = interactions.context.InteractionContext(sim, interactions.context.InteractionContext.SOURCE_SCRIPT, interactions.priority.Priority.High)
                if not sim.push_super_affordance(go_home_affordance, None, context):
                    logger.warn('Failed to push sim to go home from open street: {}', sim_info, owner='msantander')

    def set_aging_enabled_on_all_sims(self, is_aging_enabled_for_sim_info_fn):
        for sim_info in self.objects:
            sim_info.set_aging_enabled(is_aging_enabled_for_sim_info_fn(sim_info))

    def set_aging_speed_on_all_sims(self, speed):
        for sim_info in self.objects:
            sim_info.set_aging_speed(speed)

    def set_sim_at_work(self, sim_info):
        self._sim_ids_at_work.add(sim_info.id)

    def on_loading_screen_animation_finished(self):
        for sim_info in self.objects:
            sim_info.on_loading_screen_animation_finished()
        travel_sim_infos = [self.get(sim_id) for sim_id in self._sims_traveled_to_zone]
        sims.baby.on_sim_spawned_baby_handle(travel_sim_infos)
        self._sims_traveled_to_zone.clear()
        self._sim_infos_saved_in_open_street.clear()
        self._sim_infos_saved_in_zone.clear()
        self._sim_ids_at_work.clear()

    def remove_permanently(self, sim_info):
        sim_info.relationship_tracker.destroy_all_relationships()
        self.remove(sim_info)

