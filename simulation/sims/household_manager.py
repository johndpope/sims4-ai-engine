import collections
import random
from protocolbuffers import Consts_pb2, InteractionOps_pb2
from clock import ClockSpeedMode, interval_in_sim_minutes, interval_in_sim_days
from date_and_time import TimeSpan
from event_testing.resolver import SingleSimResolver, DoubleSimResolver
from event_testing.results import TestResult
from event_testing.tests import TunableTestSet
from filters.sim_filter_service import SimFilterGlobalBlacklistReason
from relationships import global_relationship_tuning
from sims4.random import pop_weighted
from sims4.tuning.tunable import HasTunableFactory, Tunable, TunableReference, TunableEnumEntry, TunableTuple, TunableSimMinute
from tunable_time import TunableTimeOfDay
from ui.ui_dialog import UiDialogOkCancel
import alarms
import autonomy.settings
import build_buy
import distributor
import element_utils
import elements
import interactions.context
import interactions.priority
import objects.object_manager
import server.account
import services
import sims.household
import sims4.log
import situations.npc_hosted_situations
import venues
logger = sims4.log.Logger('HouseholdManager')

class PhoneCall(HasTunableFactory):
    __qualname__ = 'PhoneCall'
    FACTORY_TUNABLES = {'weight': Tunable(description='\n                The weight that this phone call type will be chosen.\n                ', tunable_type=float, default=1.0), 'dialog': UiDialogOkCancel.TunableFactory(description='\n                The message that will be displayed when the phone is picked up.\n                '), 'sim_filter': TunableReference(description='\n                The filter that determines the NPC target of the phone call.\n                ', manager=services.get_instance_manager(sims4.resources.Types.SIM_FILTER)), 'tests': TunableTestSet(description='\n                Tests that will be run on the sim when testing to see if this\n                phone call should be allowed.\n                ')}

    def __init__(self, sim, weight=None, dialog=None, sim_filter=None, tests=None):
        self._sim = sim
        self._weight = weight
        self._dialog = dialog
        self._sim_filter = sim_filter
        self._target = None
        self._tests = tests

    @property
    def weight(self):
        return self._weight

    def try_and_setup(self):
        if not self._test():
            return False
        self._generate_target()
        if self._target is None:
            return False
        return True

    def _on_dialog_accepted(self):
        raise NotImplementedError

    def _dialog_callback(self, dialog):
        services.sim_filter_service().remove_sim_id_from_global_blacklist(self._target.id, SimFilterGlobalBlacklistReason.PHONE_CALL)
        if not dialog.accepted:
            return
        self._on_dialog_accepted()

    def execute(self):
        services.sim_filter_service().add_sim_id_to_global_blacklist(self._target.id, SimFilterGlobalBlacklistReason.PHONE_CALL)
        dialog = self._dialog(self._sim, DoubleSimResolver(self._sim.sim_info, self._target))
        dialog.show_dialog(on_response=self._dialog_callback)

    def _test(self):
        resolver = SingleSimResolver(self._sim.sim_info)
        return self._tests.run_tests(resolver)

    def _generate_target(self):
        blacklist_sim_ids = [sim.id for sim in services.sim_info_manager().instanced_sims_gen()]
        filter_results = services.sim_filter_service().submit_filter(self._sim_filter, None, requesting_sim_info=self._sim.sim_info, blacklist_sim_ids=blacklist_sim_ids, allow_yielding=False)
        if filter_results:
            self._target = sims4.random.weighted_random_item([(result.score, result.sim_info) for result in filter_results])

class ChatPhoneCall(PhoneCall):
    __qualname__ = 'ChatPhoneCall'
    FACTORY_TUNABLES = {'affordance': TunableReference(description='\n                The affordance that will be pushed on the sim and the chosen\n                NPC target when the phone call is complete.\n                ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION))}

    def __init__(self, *args, affordance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._affordance = affordance

    def _on_dialog_accepted(self):
        context = interactions.context.InteractionContext(self._sim, interactions.context.InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT, interactions.priority.Priority.High, insert_strategy=interactions.context.QueueInsertStrategy.NEXT, bucket=interactions.context.InteractionBucketType.DEFAULT)
        self._sim.push_super_affordance(self._affordance, self._sim, context, picked_item_ids=(self._target.id,))

class InviteOverPhoneCall(PhoneCall):
    __qualname__ = 'InviteOverPhoneCall'

    def _test(self):
        if services.get_persistence_service().is_save_locked():
            return TestResult(False, 'InviteOverPhoneCall cannot trigger when save lock is active.')
        return super()._test()

    def _on_dialog_accepted(self):
        if services.get_persistence_service().is_save_locked():
            return
        travel_info = InteractionOps_pb2.TravelSimsToZone()
        travel_info.zone_id = self._target.household.home_zone_id
        travel_info.sim_ids.append(self._sim.id)
        distributor.system.Distributor.instance().add_event(Consts_pb2.MSG_TRAVEL_SIMS_TO_ZONE, travel_info)
        services.game_clock_service().set_clock_speed(ClockSpeedMode.PAUSED)

class AskToComeOverPhoneCall(PhoneCall):
    __qualname__ = 'AskToComeOverPhoneCall'
    FACTORY_TUNABLES = {'summoning_purpose': TunableEnumEntry(description='\n                The purpose that is used to summon the NPC to the lot.  Defined\n                in venue tuning.\n                ', tunable_type=venues.venue_constants.NPCSummoningPurpose, default=venues.venue_constants.NPCSummoningPurpose.DEFAULT)}

    def __init__(self, *args, summoning_purpose=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._summoning_purpose = summoning_purpose

    def _on_dialog_accepted(self):
        services.current_zone().venue_service.venue.summon_npcs((self._target,), self._summoning_purpose)

class HouseholdManager(objects.object_manager.DistributableObjectManager):
    __qualname__ = 'HouseholdManager'
    PHONE_CALL_INFO = TunableTuple(ask_to_come_over=AskToComeOverPhoneCall.TunableFactory(), chat=ChatPhoneCall.TunableFactory(), invite_over=InviteOverPhoneCall.TunableFactory(), minimum_time_between_calls=TunableSimMinute(description='\n            The minimum time between calls.  When scheduling the call alarm\n            A number between minimum and maximum will be chosen.\n            ', default=60, minimum=1), maximum_time_between_calls=TunableSimMinute(description='\n            The maximum time between calls.  When scheduling the call alarm\n            A number between minimum and maximum will be chosen.\n            ', default=120, minimum=1), availible_time_of_day=TunableTuple(start_time=TunableTimeOfDay(description='\n                The start time that the player can receive phone calls\n                '), end_time=TunableTimeOfDay(description='\n                The end time that the player can receive phone calls.\n                '), description='\n            The start and end times that determine the time that the player can\n            receive phone calls.\n            '), description='\n        Data related to sims calling up your sims.\n        ')
    NPC_HOSTED_EVENT_SCHEDULER = situations.npc_hosted_situations.TunableNPCHostedSituationSchedule()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._npc_hosted_situation_scheduler = None
        self._save_slot_data = None
        self._phone_call_alarm_handle = None
        self._phone_call_element = None
        self._pending_household_funds = collections.defaultdict(list)

    def create_household(self, account):
        new_household = sims.household.Household(account)
        self.add(new_household)
        return new_household

    def increment_household_object_count(self, household_id):
        if household_id is None:
            return
        house = self.get(household_id)
        if house is not None:
            build_buy.update_household_object_count(house.id, house.owned_object_count)

    def decrement_household_object_count(self, household_id):
        if household_id is None:
            return
        house = self.get(household_id)
        if house is not None:
            build_buy.update_household_object_count(house.id, house.owned_object_count)

    def load_households(self):
        for household_proto in services.get_persistence_service().all_household_proto_gen():
            household_id = household_proto.household_id
            household = self.get(household_id)
            while household is None:
                self._load_household_from_household_proto(household_proto)
        for household_id in self._pending_household_funds.keys():
            logger.error('Household {} has pending funds leftover from BB after all households were loaded.', household_id, owner='camilogarcia')
        self._pending_household_funds = None

    def load_household(self, household_id):
        return self._load_household(household_id)

    def _load_household(self, household_id):
        household = self.get(household_id)
        if household is not None:
            for sim_info in household.sim_info_gen():
                while sim_info.zone_id != sims4.zone_utils.get_zone_id(False):
                    householdProto = services.get_persistence_service().get_household_proto_buff(household_id)
                    if householdProto is None:
                        logger.error('unable to find household with household id {}'.household_id)
                        return
                    found_sim = False
                    if householdProto.sims.ids:
                        for sim_id in householdProto.sims.ids:
                            while sim_id == sim_info.sim_id:
                                found_sim = True
                                break
                    if found_sim:
                        sim_proto = services.get_persistence_service().get_sim_proto_buff(sim_id)
                        sim_info.load_sim_info(sim_proto)
            return household
        logger.info('Starting to load household id = {0}', household_id)
        household_proto = services.get_persistence_service().get_household_proto_buff(household_id)
        if household_proto is None:
            sims4.log.error('Persistence', 'Household proto could not be found id = {0}', household_id)
            return
        household = self._load_household_from_household_proto(household_proto)
        return household

    def _load_household_from_household_proto(self, household_proto):
        account = services.account_service().get_account_by_id(household_proto.account_id, try_load_account=True)
        if account is None:
            sims4.log.error('Persistence', "Household account doesn't exist in account ids. Creating temp account", owner='yshan')
            account = server.account.Account(household_proto.account_id, 'TempPersonaName')
        household = sims.household.Household(account)
        household.load_data(household_proto)
        logger.info('Household loaded. name:{:20} id:{:10} #sim_infos:{:2}', household.name, household.id, len(household))
        self.add(household)
        household.initialize_sim_infos()
        if household is services.client_manager().get_first_client().household:
            for sim_info in household.sim_info_gen():
                for other_info in household.sim_info_gen():
                    while sim_info is not other_info:
                        family_relationship = sim_info.relationship_tracker._find_relationship(other_info.id, create=False)
                        if family_relationship is not None and family_relationship.has_bit(global_relationship_tuning.RelationshipGlobalTuning.NEIGHBOR_RELATIONSHIP_BIT):
                            family_relationship.remove_bit(global_relationship_tuning.RelationshipGlobalTuning.NEIGHBOR_RELATIONSHIP_BIT)
        pending_funds_reasons = self._pending_household_funds.get(household.id)
        if pending_funds_reasons is not None:
            del self._pending_household_funds[household.id]
            for (fund, reason) in pending_funds_reasons:
                household.funds.add(fund, reason, None)
        return household

    def is_household_stored_in_any_neighborhood_proto(self, household_id):
        for neighborhood_proto in services.get_persistence_service().get_neighborhoods_proto_buf_gen():
            while any(household_id == household_account_proto.household_id for household_account_proto in neighborhood_proto.npc_households):
                return True
        return False

    def get_by_sim_id(self, sim_id):
        for house in self._objects.values():
            while house.sim_in_household(sim_id):
                return house

    def get_household_autonomy_mode(self, sim):
        household = sim.household
        if household is not None:
            return household.get_autonomy_mode()

    def get_household_autonomy_state(self, sim):
        household = sim.household
        if household is not None:
            household_setting = household.autonomy_setting
            if household_setting:
                if household_setting.state is not autonomy.settings.AutonomyState.UNDEFINED:
                    return household_setting.state

    def prune_household(self, household_id):
        household = self.get(household_id)
        if household is not None:
            if household.get_household_type() != sims.household.HouseholdType.GAME_CREATED:
                logger.warn('Trying to prune a non-game created household:{}', household.id, owner='msantander')
                return
            sim_info_manager = services.sim_info_manager()
            for sim_info in tuple(household):
                household.remove_sim_info(sim_info, destroy_if_empty_gameplay_household=True)
                sim_info_manager.remove_permanently(sim_info)
                services.get_persistence_service().del_sim_proto_buff(sim_info.id)

    def save(self, **kwargs):
        households = self.get_all()
        for household in households:
            household.save_data()

    def on_all_households_and_sim_infos_loaded(self, client):
        self._npc_hosted_situation_scheduler = HouseholdManager.NPC_HOSTED_EVENT_SCHEDULER()
        self._schedule_phone_call_alarm()
        for household in self.get_all():
            household.on_all_households_and_sim_infos_loaded()

    def on_client_disconnect(self, client):
        for household in self.get_all():
            household.on_client_disconnect()
        if self._phone_call_alarm_handle is not None:
            alarms.cancel_alarm(self._phone_call_alarm_handle)
            self._phone_call_alarm_handle = None
        if self._phone_call_element is not None:
            self._phone_call_element.trigger_hard_stop()

    def _schedule_phone_call_alarm(self):
        delay = random.randint(HouseholdManager.PHONE_CALL_INFO.minimum_time_between_calls, HouseholdManager.PHONE_CALL_INFO.maximum_time_between_calls)
        time_delay = interval_in_sim_minutes(delay)
        current_time = services.time_service().sim_now
        alarm_end_time = current_time + time_delay
        if alarm_end_time.time_between_day_times(HouseholdManager.PHONE_CALL_INFO.availible_time_of_day.start_time, HouseholdManager.PHONE_CALL_INFO.availible_time_of_day.end_time):
            time_till_alarm_end_time = alarm_end_time - current_time
            self._phone_call_alarm_handle = alarms.add_alarm(self, time_till_alarm_end_time, self._trigger_phone_call_callback)
            return
        if current_time.time_between_day_times(HouseholdManager.PHONE_CALL_INFO.availible_time_of_day.start_time, HouseholdManager.PHONE_CALL_INFO.availible_time_of_day.end_time):
            time_till_next_end_time = current_time.time_till_next_day_time(HouseholdManager.PHONE_CALL_INFO.availible_time_of_day.end_time)
        else:
            time_till_next_end_time = TimeSpan.ZERO
        time_delay -= time_till_next_end_time
        time_available_per_day = HouseholdManager.PHONE_CALL_INFO.availible_time_of_day.end_time - HouseholdManager.PHONE_CALL_INFO.availible_time_of_day.start_time
        cycles_left = time_delay.in_ticks()//time_available_per_day.in_ticks()
        time_till_next_start_time = current_time.time_till_next_day_time(HouseholdManager.PHONE_CALL_INFO.availible_time_of_day.start_time)
        time_till_alarm_end_time = time_till_next_start_time + interval_in_sim_days(cycles_left)
        time_delay -= time_available_per_day*cycles_left
        time_till_alarm_end_time += time_delay
        self._phone_call_alarm_handle = alarms.add_alarm(self, time_till_alarm_end_time, self._trigger_phone_call_callback)

    def _trigger_phone_call_callback(self, _):
        if self._phone_call_element is None:
            self._phone_call_element = elements.GeneratorElement(self._trigger_phone_call_gen)
            services.time_service().sim_timeline.schedule(self._phone_call_element)
        self._schedule_phone_call_alarm()

    def _trigger_phone_call_gen(self, timeline):
        client = services.client_manager().get_first_client()
        if client is None:
            return
        client_household = client.household
        if client_household is None:
            return
        sims_to_check = [sim for sim in client_household.instanced_sims_gen()]
        random.shuffle(sims_to_check)
        for sim in sims_to_check:
            call_types = []
            ask_to_come_over_phone_call = HouseholdManager.PHONE_CALL_INFO.ask_to_come_over(sim)
            call_types.append((ask_to_come_over_phone_call.weight, ask_to_come_over_phone_call))
            chat_phone_call = HouseholdManager.PHONE_CALL_INFO.chat(sim)
            call_types.append((chat_phone_call.weight, chat_phone_call))
            invite_over_phone_call = HouseholdManager.PHONE_CALL_INFO.invite_over(sim)
            call_types.append((invite_over_phone_call.weight, invite_over_phone_call))
            while call_types:
                call_type = pop_weighted(call_types)
                if call_type.try_and_setup():
                    call_type.execute()
                    self._phone_call_element = None
                    return
                yield element_utils.run_child(timeline, element_utils.sleep_until_next_tick_element())
        self._phone_call_element = None

    def debug_trigger_ask_to_come_over_phone_call(self, sim):
        phone_call = HouseholdManager.PHONE_CALL_INFO.ask_to_come_over(sim)
        if not phone_call.try_and_setup():
            return False
        phone_call.execute()
        return True

    def debug_trigger_chat_phone_call(self, sim):
        phone_call = HouseholdManager.PHONE_CALL_INFO.chat(sim)
        if not phone_call.try_and_setup():
            return False
        phone_call.execute()
        return True

    def debug_trigger_invite_over_phone_call(self, sim):
        phone_call = HouseholdManager.PHONE_CALL_INFO.invite_over(sim)
        if not phone_call.try_and_setup():
            return False
        phone_call.execute()
        return True

    @staticmethod
    def get_active_sim_home_zone_id():
        client = services.client_manager().get_first_client()
        if client is not None:
            active_sim = client.active_sim
            if active_sim is not None:
                household = active_sim.household
                if household is not None:
                    return household.home_zone_id

    def try_add_pending_household_funds(self, household_id, funds, reason):
        if self._pending_household_funds is None:
            return False
        self._pending_household_funds[household_id].append((funds, reason))
        return True

