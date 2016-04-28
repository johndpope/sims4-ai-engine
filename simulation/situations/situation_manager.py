#ERROR: jaddr is None
from protocolbuffers import Consts_pb2
import protocolbuffers
from buffs.tunable import TunableBuffReference
from objects.object_manager import DistributableObjectManager
from sims4.tuning.tunable import TunableSet, TunableEnumWithFilter
from sims4.tuning.tunable_base import FilterTag
from situations.bouncer.bouncer import Bouncer
from situations.bouncer.bouncer_types import RequestSpawningOption, BouncerRequestPriority
from situations.situation import Situation
from situations.situation_guest_list import SituationGuestList
from situations.situation_serialization import SituationSeed, SeedPurpose
from situations.situation_types import SituationStage, GreetedStatus, SituationSerializationOption
from uid import UniqueIdGenerator
from venues.venue_constants import NPCSummoningPurpose
import date_and_time
import distributor.system
import id_generator
import services
import sims
import sims4.log
import sims4.tuning.tunable
import situations.complex.single_sim_leave_situation
import situations.complex.leave_situation
import tag
import telemetry_helper
import venues
logger = sims4.log.Logger('Situations')
TELEMETRY_GROUP_SITUATIONS = 'SITU'
TELEMETRY_HOOK_CREATE_SITUATION = 'SITU'
TELEMETRY_HOOK_GUEST = 'GUES'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_SITUATIONS)

class _CallbackRegistration:
    __qualname__ = '_CallbackRegistration'

    def __init__(self, situation_callback_option, callback_fn):
        self.situation_callback_option = situation_callback_option
        self.callback_fn = callback_fn

class _SituationManagerSimData:
    __qualname__ = '_SituationManagerSimData'
    BLACKLISTED_MAX_SPAN = date_and_time.create_time_span(hours=8)

    def __init__(self, sim_id):
        self._sim_id = sim_id
        self._created_time = None
        self._blacklist_until = date_and_time.DATE_AND_TIME_ZERO

    def set_created_time(self, created_time):
        self._created_time = created_time

    @property
    def created_time(self):
        return self._created_time

    def blacklist(self, blacklist_until=None):
        if blacklist_until is None:
            self._blacklist_until = services.time_service().sim_now + self.BLACKLISTED_MAX_SPAN
        else:
            self._blacklist_until = blacklist_until

    @property
    def is_blacklisted(self):
        return services.time_service().sim_now < self._blacklist_until

    def get_remaining_blacklisted_time_span(self):
        if self.is_blacklisted == False:
            return date_and_time.TimeSpan.ZERO
        return self._blacklist_until - services.time_service().sim_now

class DelayedSituationDestruction:
    __qualname__ = 'DelayedSituationDestruction'

    def __enter__(self):
        situation_manager = services.get_zone_situation_manager()

    def __exit__(self, exc_type, exc_value, traceback):
        situation_manager = services.get_zone_situation_manager()
        if situation_manager._delay_situation_destruction_ref_count == 0:
            for situation in situation_manager._situations_for_delayed_destruction:
                situation._self_destruct()
            situation_manager._situations_for_delayed_destruction.clear()

class SituationManager(DistributableObjectManager):
    __qualname__ = 'SituationManager'
    DEFAULT_LEAVE_SITUATION = sims4.tuning.tunable.TunableReference(description='\n                                            The situation type for the background leave situation.\n                                            It collects sims who are not in other situations and\n                                            asks them to leave periodically.\n                                            ', manager=services.get_instance_manager(sims4.resources.Types.SITUATION), class_restrictions=situations.complex.leave_situation.LeaveSituation)
    DEFAULT_LEAVE_NOW_MUST_RUN_SITUATION = sims4.tuning.tunable.TunableReference(description='\n                                            The situation type that drives the sim off the lot pronto.\n                                            ', manager=services.get_instance_manager(sims4.resources.Types.SITUATION), class_restrictions=situations.complex.single_sim_leave_situation.SingleSimLeaveSituation)
    DEFAULT_VISIT_SITUATION = sims4.tuning.tunable.TunableReference(description='\n                                            The default visit situation used when you ask someone to \n                                            hang out or invite them in.\n                                            ', manager=services.get_instance_manager(sims4.resources.Types.SITUATION))
    DEFAULT_TRAVEL_SITUATION = Situation.TunableReference(description=' \n                                            The default situation for when you \n                                            are simply traveling with a group \n                                            of Sims.\n                                            ')
    NPC_SOFT_CAP = sims4.tuning.tunable.Tunable(description='\n                The base value for calculating the soft cap on the maximum \n                number of NPCs instantiated.\n                \n                The actual value of the NPC soft cap will be\n                this tuning value minus the number of sims in the active household.\n                \n                There is no hard cap because certain types of NPCs must always\n                spawn or the game will be broken. The prime example of a \n                game breaker is the Grim Reaper.\n                \n                If the number of NPCs is:\n                \n                1) At or above the soft cap only game breaker NPCs will be spawned.\n                \n                2) Above the soft cap then low priority NPCs will be driven from the lot.\n                \n                3) Equal to the soft cap and there are pending requests for higher priority\n                NPCs, then lower priority NPCs will be driven from the lot.\n                                \n                ', tunable_type=int, default=20, tuning_filter=sims4.tuning.tunable_base.FilterTag.EXPERT_MODE)
    LEAVE_INTERACTION_TAGS = TunableSet(description='\n                The tags indicating leave lot interactions, but not \n                leave lot must run interactions.\n                These are used to determine if a leave lot interaction is running\n                or cancel one if it is.\n                ', tunable=TunableEnumWithFilter(tunable_type=tag.Tag, default=tag.Tag.INVALID, tuning_filter=FilterTag.EXPERT_MODE, filter_prefixes=tag.INTERACTION_PREFIX))
    SUPER_SPEED_THREE_REQUEST_BUFF = TunableBuffReference(description="\n        The buff to apply to the Sim when we're trying to make them run the\n        leave situation from a super speed three request.\n        ", deferred=True)
    _npc_soft_cap_override = None
    _perf_test_cheat_enabled = False

    def __init__(self, manager_id=0):
        super().__init__(manager_id=manager_id)
        self._get_next_session_id = UniqueIdGenerator(1)
        self._added_to_distributor = set()
        self._callbacks = {}
        self._departing_situation_seed = None
        self._arriving_situation_seed = None
        self._zone_seeds_for_zone_spinup = []
        self._open_street_seeds_for_zone_spinup = []
        self._debug_sims = set()
        self._leave_situation_id = 0
        self._player_greeted_situation_id = 0
        self._player_waiting_to_be_greeted_situation_id = 0
        self._sim_being_created = None
        self._sim_data = {}
        self._delay_situation_destruction_ref_count = 0
        self._situations_for_delayed_destruction = set()
        self._bouncer = None
        self._zone_spin_up_greeted_complete = False
        self._pre_bouncer_update = []

    def start(self):
        self._bouncer = Bouncer()

    def destroy_situations_on_teardown(self):
        self.destroy_all_situations(include_system=True)
        self._sim_data.clear()
        self._bouncer.destroy()
        self._bouncer = None

    def reset(self, create_system_situations=True):
        self.destroy_all_situations(include_system=True)
        self._added_to_distributor.clear()
        self._callbacks.clear()
        self._bouncer.reset()
        if create_system_situations:
            self._create_system_situations()

    def add_pre_bouncer_update(self, situation):
        self._pre_bouncer_update.append(situation)

    def update(self):
        if self._bouncer is not None:
            try:
                situations = tuple(self._pre_bouncer_update)
                if situations:
                    self._pre_bouncer_update = []
                    for situation in situations:
                        situation.on_pre_bouncer_update()
                self._bouncer._update()
            except Exception:
                logger.exception('Exception while updating the Bouncer.')

    @property
    def npc_soft_cap(self):
        cap = self.NPC_SOFT_CAP if self._npc_soft_cap_override is None else self._npc_soft_cap_override
        if services.active_household() is None:
            return 0
        return cap - services.active_household().size_of_household

    def set_npc_soft_cap_override(self, override):
        self._npc_soft_cap_override = override

    def enable_perf_cheat(self, enable=True):
        self._perf_test_cheat_enabled = enable
        self._bouncer.spawning_freeze(enable)
        self._bouncer.cap_cheat(enable)

    def get_all(self):
        return [obj for obj in self._objects.values() if obj._stage == SituationStage.RUNNING]

    def get_new_situation_creation_session(self):
        return self._get_next_session_id()

    @property
    def bouncer(self):
        return self._bouncer

    @property
    def sim_being_created(self):
        return self._sim_being_created

    def add_debug_sim_id(self, sim_id):
        self._debug_sims.add(sim_id)

    def _determine_player_greeted_status_during_zone_spin_up(self):
        if not services.current_zone().venue_service.venue.requires_visitation_rights:
            return GreetedStatus.NOT_APPLICABLE
        active_household = services.active_household()
        if active_household is None:
            return GreetedStatus.NOT_APPLICABLE
        if active_household.home_zone_id == services.current_zone().id:
            return GreetedStatus.NOT_APPLICABLE
        cur_status = GreetedStatus.WAITING_TO_BE_GREETED
        lot_seeds = list(self._zone_seeds_for_zone_spinup)
        if self._arriving_situation_seed is not None:
            lot_seeds.append(self._arriving_situation_seed)
        for seed in lot_seeds:
            status = seed.get_player_greeted_status()
            logger.debug('Player:{} :{}', status, seed.situation_type, owner='sscholl')
            while status == GreetedStatus.GREETED:
                cur_status = status
                break
        return cur_status

    def get_npc_greeted_status_during_zone_fixup(self, sim_info):
        if not services.current_zone().venue_service.venue.requires_visitation_rights:
            return GreetedStatus.NOT_APPLICABLE
        if sim_info.lives_here:
            return GreetedStatus.NOT_APPLICABLE
        cur_status = GreetedStatus.NOT_APPLICABLE
        for seed in self._zone_seeds_for_zone_spinup:
            status = seed.get_npc_greeted_status(sim_info)
            logger.debug('NPC:{} :{} :{}', sim_info, status, seed.situation_type, owner='sscholl')
            if status == GreetedStatus.GREETED:
                cur_status = status
                break
            while status == GreetedStatus.WAITING_TO_BE_GREETED:
                cur_status = status
        return cur_status

    def is_player_greeted(self):
        return self._player_greeted_situation_id != 0

    def is_player_waiting_to_be_greeted(self):
        return self._player_waiting_to_be_greeted_situation_id != 0 and self._player_greeted_situation_id == 0

    @property
    def is_zone_spin_up_greeted_complete(self):
        return self._zone_spin_up_greeted_complete

    def create_situation(self, situation_type, guest_list=None, user_facing=True, duration_override=None, custom_init_writer=None, zone_id=0, scoring_enabled=True, spawn_sims_during_zone_spin_up=False):
        if guest_list is None:
            guest_list = SituationGuestList()
        hire_cost = guest_list.get_hire_cost()
        reserved_funds = None
        if guest_list.host_sim is not None:
            reserved_funds = guest_list.host_sim.family_funds.try_remove(situation_type.cost() + hire_cost, Consts_pb2.TELEMETRY_EVENT_COST, guest_list.host_sim)
            if reserved_funds is None:
                return
            reserved_funds.apply()
        situation_id = id_generator.generate_object_id()
        self._send_create_situation_telemetry(situation_type, situation_id, guest_list, hire_cost, zone_id)
        if zone_id != 0 and services.current_zone().id != zone_id:
            return self._create_departing_seed_and_travel(situation_type, situation_id, guest_list, user_facing, duration_override, custom_init_writer, zone_id, scoring_enabled=scoring_enabled)
        situation_seed = SituationSeed(situation_type, SeedPurpose.NORMAL, situation_id, guest_list, user_facing=user_facing, duration_override=duration_override, scoring_enabled=scoring_enabled, spawn_sims_during_zone_spin_up=spawn_sims_during_zone_spin_up)
        if custom_init_writer is not None:
            situation_seed.setup_for_custom_init_params(custom_init_writer)
        return self.create_situation_from_seed(situation_seed)

    def create_visit_situation_for_unexpected(self, sim):
        duration_override = None
        if self._perf_test_cheat_enabled:
            duration_override = 0
        self.create_visit_situation(sim, duration_override=duration_override)

    def create_visit_situation(self, sim, duration_override=None, visit_type_override=None):
        situation_id = None
        visit_type = visit_type_override if visit_type_override is not None else self.DEFAULT_VISIT_SITUATION
        if visit_type is not None:
            guest_list = situations.situation_guest_list.SituationGuestList(invite_only=True)
            guest_info = situations.situation_guest_list.SituationGuestInfo.construct_from_purpose(sim.id, visit_type.default_job(), situations.situation_guest_list.SituationInvitationPurpose.INVITED)
            guest_list.add_guest_info(guest_info)
            situation_id = self.create_situation(visit_type, guest_list=guest_list, user_facing=False, duration_override=duration_override)
        if situation_id is None:
            logger.error('Failed to create visit situation for sim: {}', sim)
            self.make_sim_leave(sim)
        return situation_id

    def create_situation_from_seed(self, seed):
        if not seed.allow_creation:
            return
        if seed.user_facing:
            situation = self.get_user_facing_situation()
            if situation is not None:
                self.destroy_situation_by_id(situation.id)
        if seed.situation_type.is_unique_situation:
            for situation in self.running_situations():
                while type(situation) is seed.situation_type:
                    return
        situation = seed.situation_type(seed)
        try:
            if seed.is_loadable:
                situation._destroy()
                return
            else:
                situation.start_situation()
        except Exception:
            logger.exception('Exception thrown while starting situation')
            situation._destroy()
            return
        self.add(situation)
        if situation.is_user_facing or situation.distribution_override:
            distributor.system.Distributor.instance().add_object(situation)
            self._added_to_distributor.add(situation)
            situation.on_added_to_distributor()
        return situation.id

    def _create_departing_seed_and_travel(self, situation_type, situation_id, guest_list=None, user_facing=True, duration_override=None, custom_init_writer=None, zone_id=0, scoring_enabled=True):
        traveling_sim = guest_list.get_traveler()
        if traveling_sim is None:
            logger.error('No traveling sim available for creating departing seed for situation: {}.', situation_type)
            return
        if traveling_sim.client is None:
            logger.error('No client on traveling sim: {} for for situation: {}.', traveling_sim, situation_type)
            return
        if traveling_sim.household is None:
            logger.error('No household on traveling sim for for situation: {}.', situation_type)
            return
        situation_seed = SituationSeed(situation_type, SeedPurpose.TRAVEL, situation_id, guest_list, user_facing, duration_override, zone_id, scoring_enabled=scoring_enabled)
        if situation_seed is None:
            logger.error('Failed to create departing seed.for situation: {}.', situation_type)
            return
        if custom_init_writer is not None:
            situation_seed.setup_for_custom_init_params(custom_init_writer)
        self._departing_situation_seed = situation_seed
        travel_info = protocolbuffers.InteractionOps_pb2.TravelSimsToZone()
        travel_info.zone_id = zone_id
        travel_info.sim_ids.append(traveling_sim.id)
        traveling_sim_ids = guest_list.get_other_travelers(traveling_sim)
        travel_info.sim_ids.extend(traveling_sim_ids)
        distributor.system.Distributor.instance().add_event(protocolbuffers.Consts_pb2.MSG_TRAVEL_SIMS_TO_ZONE, travel_info)
        services.game_clock_service().request_pause('Situation Travel')
        logger.debug('Travel seed creation time {}', services.time_service().sim_now)
        logger.debug('Travel seed future time {}', services.time_service().sim_future)
        return situation_id

    def _create_system_situations(self):
        self._leave_situation_id = 0
        for situation in self.running_situations():
            while type(situation) is self.DEFAULT_LEAVE_SITUATION:
                self._leave_situation_id = situation.id
                break
        if self._leave_situation_id == 0:
            self._leave_situation_id = self.create_situation(self.DEFAULT_LEAVE_SITUATION, user_facing=False, duration_override=0)

    @property
    def auto_manage_distributor(self):
        return False

    def call_on_remove(self, situation):
        super().call_on_remove(situation)
        self._callbacks.pop(situation.id, None)
        if situation in self._added_to_distributor:
            dist = distributor.system.Distributor.instance()
            dist.remove_object(situation)
            self._added_to_distributor.remove(situation)
            situation.on_removed_from_distributor()

    def is_distributed(self, situation):
        return situation in self._added_to_distributor

    def _request_destruction(self, situation):
        if self._delay_situation_destruction_ref_count == 0:
            return True
        self._situations_for_delayed_destruction.add(situation)
        return False

    def destroy_situation_by_id(self, situation_id):
        if situation_id in self:
            if situation_id == self._leave_situation_id:
                self._leave_situation_id = 0
            if situation_id == self._player_greeted_situation_id:
                self._player_greeted_situation_id = 0
            if situation_id == self._player_waiting_to_be_greeted_situation_id:
                self._player_waiting_to_be_greeted_situation_id = 0
            self.remove_id(situation_id)

    def destroy_all_situations(self, include_system=False):
        all_situations = tuple(self.values())
        for situation in all_situations:
            if include_system == False and situation.id == self._leave_situation_id:
                pass
            try:
                self.destroy_situation_by_id(situation.id)
            except Exception:
                logger.error('Error when destroying situation {}. You are probably screwed.', situation)

    def register_for_callback(self, situation_id, situation_callback_option, callback_fn):
        registrant = _CallbackRegistration(situation_callback_option, callback_fn)
        registrant_list = self._callbacks.setdefault(situation_id, [])
        registrant_list.append(registrant)

    def create_greeted_npc_visiting_npc_situation(self, npc_sim_info):
        services.current_zone().venue_service.venue.summon_npcs((npc_sim_info,), venues.venue_constants.NPCSummoningPurpose.PLAYER_BECOMES_GREETED)

    def create_greeted_player_visiting_npc_situation(self, sim=None):
        if sim is None:
            guest_list = situations.situation_guest_list.SituationGuestList()
        else:
            guest_list = situations.situation_guest_list.SituationGuestList(host_sim_id=sim.id)
        greeted_situation_type = services.current_zone().venue_service.venue.player_greeted_situation_type
        if greeted_situation_type is None:
            return
        self._player_greeted_situation_id = self.create_situation(greeted_situation_type, user_facing=False, guest_list=guest_list)

    def create_player_waiting_to_be_greeted_situation(self):
        self._player_waiting_to_be_greeted_situation_id = self.create_situation(services.current_zone().venue_service.venue.player_ungreeted_situation_type, user_facing=False)

    def _handle_player_greeting_situations_during_zone_spin_up(self):
        if self._zone_spin_up_player_greeted_status == GreetedStatus.NOT_APPLICABLE:
            return
        if self._zone_spin_up_player_greeted_status == GreetedStatus.GREETED:
            greeted_situation_type = services.current_zone().venue_service.venue.player_greeted_situation_type
            for situation in self.running_situations():
                while type(situation) is greeted_situation_type:
                    break
            self.create_greeted_player_visiting_npc_situation()
            return
        waiting_situation_type = services.current_zone().venue_service.venue.player_ungreeted_situation_type
        for situation in self.running_situations():
            while type(situation) is waiting_situation_type:
                break
        self.create_player_waiting_to_be_greeted_situation()

    def handle_npcs_during_zone_fixup(self):
        if services.game_clock_service().time_has_passed_in_world_since_zone_save() or services.current_zone().active_household_changed_between_save_and_load():
            sim_infos_to_fix_up = []
            for sim_info in services.sim_info_manager().get_sim_infos_saved_in_zone():
                while sim_info.is_npc and not sim_info.lives_here and sim_info.get_sim_instance() is not None:
                    sim_infos_to_fix_up.append(sim_info)
            if sim_infos_to_fix_up:
                logger.debug('Fixing up {} npcs during zone fixup', len(sim_infos_to_fix_up), owner='sscholl')
                services.current_zone().venue_service.venue.zone_fixup(sim_infos_to_fix_up)

    def make_waiting_player_greeted(self, door_bell_ringing_sim=None):
        for situation in self.running_situations():
            situation._on_make_waiting_player_greeted(door_bell_ringing_sim)
        if self._player_greeted_situation_id == 0:
            self.create_greeted_player_visiting_npc_situation(door_bell_ringing_sim)

    def save(self, zone_data=None, open_street_data=None, save_slot_data=None, **kwargs):
        if zone_data is None:
            return
        SituationSeed.serialize_travel_seed_to_slot(save_slot_data, self._departing_situation_seed)
        zone_seeds = []
        street_seeds = []
        for situation in self.running_situations():
            seed = situation.save_situation()
            while seed is not None:
                if situation.situation_serialization_option == SituationSerializationOption.OPEN_STREETS:
                    street_seeds.append(seed)
                else:
                    zone_seeds.append(seed)
        SituationSeed.serialize_seeds_to_zone(zone_seeds, zone_data)
        SituationSeed.serialize_seeds_to_open_street(street_seeds, open_street_data)

    def on_pre_spawning_sims(self):
        zone = services.current_zone()
        save_slot_proto = services.get_persistence_service().get_save_slot_proto_buff()
        seed = SituationSeed.deserialize_travel_seed_from_slot(save_slot_proto)
        if seed is not None:
            if zone.id != seed.zone_id:
                logger.debug('Travel situation :{} not loaded. Expected zone :{} but is on zone:{}', seed.situation_type, seed.zone_id, services.current_zone().id)
                seed.allow_creation = False
            else:
                time_since_travel_seed_created = services.time_service().sim_now - seed.create_time
                if time_since_travel_seed_created > date_and_time.TimeSpan.ZERO:
                    logger.debug('Not loading traveled situation :{} because time has passed {}', seed.situation_type, time_since_travel_seed_created)
                    seed.allow_creation = False
        self._arriving_situation_seed = seed
        zone_proto = services.get_persistence_service().get_zone_proto_buff(zone.id)
        if zone_proto is not None:
            self._zone_seeds_for_zone_spinup = SituationSeed.deserialize_seeds_from_zone(zone_proto)
        for seed in self._zone_seeds_for_zone_spinup:
            while not seed.situation_type._should_seed_be_loaded(seed):
                seed.allow_creation = False
        open_street_proto = services.get_persistence_service().get_open_street_proto_buff(zone.open_street_id)
        if open_street_proto is not None:
            self._open_street_seeds_for_zone_spinup = SituationSeed.deserialize_seeds_from_open_street(open_street_proto)
        for seed in self._open_street_seeds_for_zone_spinup:
            while not seed.situation_type._should_seed_be_loaded(seed):
                seed.allow_creation = False
        self._zone_spin_up_player_greeted_status = self._determine_player_greeted_status_during_zone_spin_up()

    def create_situations_during_zone_spin_up(self):
        for seed in self._zone_seeds_for_zone_spinup:
            self.create_situation_from_seed(seed)
        for seed in self._open_street_seeds_for_zone_spinup:
            self.create_situation_from_seed(seed)
        self._create_system_situations()
        if self._arriving_situation_seed is not None:
            self.create_situation_from_seed(self._arriving_situation_seed)
        self._handle_player_greeting_situations_during_zone_spin_up()
        self.handle_npcs_during_zone_fixup()

    def on_all_situations_created_during_zone_spin_up(self):
        self._bouncer.start()

    def get_sim_serialization_option(self, sim):
        result = sims.sim_info_types.SimSerializationOption.UNDECLARED
        for situation in self.get_situations_sim_is_in(sim):
            option = situation.situation_serialization_option
            if option == situations.situation_types.SituationSerializationOption.LOT:
                result = sims.sim_info_types.SimSerializationOption.LOT
                break
            else:
                while option == situations.situation_types.SituationSerializationOption.OPEN_STREETS:
                    result = sims.sim_info_types.SimSerializationOption.OPEN_STREETS
        return result

    def remove_sim_from_situation(self, sim, situation_id):
        situation = self.get(situation_id)
        if situation is None:
            return
        self._bouncer.remove_sim_from_situation(sim, situation)

    def on_reset(self, sim_ref):
        pass

    def on_sim_creation(self, sim):
        sim_data = self._sim_data.setdefault(sim.id, _SituationManagerSimData(sim.id))
        sim_data.set_created_time(services.time_service().sim_now)
        self._prune_sim_data()
        self._sim_being_created = sim
        if sim.id in self._debug_sims:
            self._debug_sims.discard(sim.id)
            if self._perf_test_cheat_enabled:
                self.create_visit_situation_for_unexpected(sim)
            else:
                services.current_zone().venue_service.venue.summon_npcs((sim.sim_info,), NPCSummoningPurpose.DEFAULT)
        self._bouncer.on_sim_creation(sim)
        self._sim_being_created = None

    def get_situations_sim_is_in(self, sim):
        return [situation for situation in self.values() if situation._stage == SituationStage.RUNNING]

    def is_user_facing_situation_running(self):
        for situation in self.values():
            while situation.is_user_facing:
                return True
        return False

    def get_user_facing_situation(self):
        for situation in self.values():
            while situation.is_user_facing:
                return situation

    def running_situations(self):
        return [obj for obj in self._objects.values() if obj._stage == SituationStage.RUNNING]

    def is_situation_with_tags_running(self, tags):
        for situation in self.values():
            while situation._stage == SituationStage.RUNNING and situation.tags & tags:
                return True
        return False

    def user_ask_sim_to_leave_now_must_run(self, sim):
        if not sim.sim_info.is_npc or sim.sim_info.lives_here:
            return
        ask_to_leave = True
        for situation in self.get_situations_sim_is_in(sim):
            while not situation.on_ask_sim_to_leave(sim):
                ask_to_leave = False
                break
        if ask_to_leave:
            self.make_sim_leave_now_must_run(sim)

    def make_sim_leave_now_must_run(self, sim, super_speed_three_request=False):
        if services.current_zone().is_zone_shutting_down:
            return
        for situation in self.get_situations_sim_is_in(sim):
            while type(situation) is self.DEFAULT_LEAVE_NOW_MUST_RUN_SITUATION:
                return
        if super_speed_three_request:
            sim.add_buff(buff_type=self.SUPER_SPEED_THREE_REQUEST_BUFF.buff_type, buff_reason=self.SUPER_SPEED_THREE_REQUEST_BUFF.buff_reason)
        leave_now_type = self.DEFAULT_LEAVE_NOW_MUST_RUN_SITUATION
        guest_list = situations.situation_guest_list.SituationGuestList(invite_only=True)
        guest_info = situations.situation_guest_list.SituationGuestInfo(sim.id, leave_now_type.default_job(), RequestSpawningOption.CANNOT_SPAWN, BouncerRequestPriority.VIP, expectation_preference=True)
        guest_list.add_guest_info(guest_info)
        self.create_situation(leave_now_type, guest_list=guest_list, user_facing=False)

    def make_sim_leave(self, sim):
        leave_situation = self.get(self._leave_situation_id)
        if leave_situation is None:
            logger.error('The leave situation is missing. Making the sim leave now must run.')
            self.make_sim_leave_now_must_run(sim)
            return
        leave_situation.invite_sim_to_leave(sim)

    def expedite_leaving(self):
        leave_situation = self.get(self._leave_situation_id)
        if leave_situation is None:
            return
        for sim in leave_situation.all_sims_in_situation_gen():
            self.make_sim_leave_now_must_run(sim)

    def get_time_span_sim_has_been_on_lot(self, sim):
        sim_data = self._sim_data.get(sim.id)
        if sim_data is None:
            return
        if sim_data.created_time is None:
            return
        return services.time_service().sim_now - sim_data.created_time

    def get_remaining_blacklist_time_span(self, sim_id):
        sim_data = self._sim_data.get(sim_id)
        if sim_data is None:
            return date_and_time.TimeSpan.ZERO
        return sim_data.get_remaining_blacklisted_time_span()

    def get_auto_fill_blacklist(self):
        blacklist = set()
        for (sim_id, sim_data) in tuple(self._sim_data.items()):
            while sim_data.is_blacklisted:
                blacklist.add(sim_id)
        return blacklist

    def add_sim_to_auto_fill_blacklist(self, sim_id, blacklist_until=None):
        sim_data = self._sim_data.setdefault(sim_id, _SituationManagerSimData(sim_id))
        sim_data.blacklist(blacklist_until=blacklist_until)
        self._prune_sim_data()

    def _prune_sim_data(self):
        to_remove_ids = []
        for (sim_id, sim_data) in self._sim_data.items():
            while services.object_manager().get(sim_id) is None and sim_data.is_blacklisted == False:
                to_remove_ids.append(sim_id)
        for sim_id in to_remove_ids:
            del self._sim_data[sim_id]

    def _get_callback_registrants(self, situation_id):
        return list(self._callbacks.get(situation_id, []))

    def _send_create_situation_telemetry(self, situation_type, situation_id, guest_list, hire_cost, zone_id):
        if hasattr(situation_type, 'guid64'):
            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_CREATE_SITUATION) as hook:
                hook.write_int('situ', situation_id)
                hook.write_int('host', guest_list.host_sim_id)
                hook.write_guid('type', situation_type.guid64)
                hook.write_bool('invi', guest_list.invite_only)
                hook.write_bool('hire', hire_cost)
                hook.write_bool('nzon', zone_id != 0 and services.current_zone().id != zone_id)
            sim_info_manager = services.sim_info_manager()
            if sim_info_manager is not None:
                while True:
                    for guest_infos in guest_list._job_type_to_guest_infos.values():
                        for guest_info in guest_infos:
                            if guest_info.sim_id == 0:
                                pass
                            guest_sim = sim_info_manager.get(guest_info.sim_id)
                            if guest_sim is None:
                                pass
                            client = services.client_manager().get_client_by_household_id(guest_sim.household_id)
                            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_GUEST) as hook:
                                hook.write_int('situ', situation_id)
                                if client is None:
                                    hook.write_int('npcg', guest_info.sim_id)
                                else:
                                    hook.write_int('pcgu', guest_info.sim_id)
                                    hook.write_guid('jobb', guest_info.job_type.guid64)

