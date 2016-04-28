import heapq
from protocolbuffers import FileSerialization_pb2 as serialization, Consts_pb2, ResourceKey_pb2
from date_and_time import create_time_span
from distributor.rollback import ProtocolBufferRollback
from event_testing import test_events
from objects import HiddenReasonFlag, ALL_HIDDEN_REASONS
from objects.collection_manager import CollectionTracker
from protocolbuffers.Consts_pb2 import TELEMETRY_HOUSEHOLD_TRANSFER_GAIN
from sims import bills, sim_info
from sims.aging import AgingTuning
from sims.genealogy_tracker import genealogy_caching
from sims.sim_outfits import OutfitCategory
from sims4.resources import Types
from sims4.tuning.tunable import Tunable, TunableRange
from situations.service_npcs.service_npc_record import ServiceNpcRecord
from telemetry_helper import HouseholdTelemetryTracker
import alarms
import autonomy.settings
import build_buy
import distributor.ops
import distributor.system
import enum
import services
import sims.baby
import sims.funds
import sims.sim_info
import sims.sim_spawner
import sims4.log
import sims4.tuning.tunable
import singletons
logger = sims4.log.Logger('HouseholdManager')

class HouseholdType(enum.Int, export=False):
    __qualname__ = 'HouseholdType'
    UNKNOWN = 0
    USER_CREATED_PLAYABLE = 1
    USER_CREATED_NPC = 2
    GAME_CREATED = 3

class Household:
    __qualname__ = 'Household'
    SIM_SPAWN_RADIUS = sims4.tuning.tunable.Tunable(int, 2, description='Radius of the circle around which other family members will be spawned.')
    MAXIMUM_SIZE = Tunable(int, 8, description='Maximum number of Sims you can have in a household at a time.')
    ANCESTRY_PURGE_DEPTH = TunableRange(int, 3, minimum=1, description='The maximum number of links that living Sims can have with an ancestor before the ancestor is purged.')
    DEFAULT_STARTING_FUNDS = 500000

    def __init__(self, account, starting_funds=singletons.DEFAULT):
        self.account = account
        self.id = 0
        self.name = ''
        self.description = ''
        self.home_zone_id = 0
        self.last_modified_time = 0
        self._watchers = {}
        self._autonomy_settings = autonomy.settings.AutonomySettings()
        self._sim_infos = []
        if starting_funds is singletons.DEFAULT:
            starting_funds = self.DEFAULT_STARTING_FUNDS
        self._funds = sims.funds.FamilyFunds(self, starting_funds)
        self._remote_connected = False
        self.bills_manager = bills.Bills(self)
        self._cheats_enabled = False
        self._has_cheated = False
        self.owned_object_count = 0
        self._service_npc_record = None
        self._collection_tracker = CollectionTracker(self)
        self._telemetry_tracker = HouseholdTelemetryTracker(self)
        self._last_active_sim_id = 0
        self._reward_inventory = serialization.RewardPartList()
        self.is_persistent_npc = True
        self._cached_billable_household_value = 0
        self._highest_earned_situation_medals = {}
        self._situation_scoring_enabled = True
        self.hidden = False
        self.creator_id = 0
        self.creator_name = ''
        self.creator_uuid = None
        self.primitives = ()
        self._adopting_sim_ids = set()
        self._build_buy_unlocks = set()
        self._aging_update_alarm = None

    def __repr__(self):
        sim_strings = []
        for sim_info in self._sim_infos:
            sim_strings.append(str(sim_info))
        return 'Household {} ({}): {}'.format(self.name if self.name else '<Unnamed Household>', self.id, '; '.join(sim_strings))

    def __len__(self):
        return len(self._sim_infos)

    def __iter__(self):
        return iter(self._sim_infos)

    @property
    def valid_for_distribution(self):
        return True

    @property
    def funds(self):
        return self._funds

    @property
    def rebate_manager(self):
        return self._rebate_manager

    @property
    def situation_scoring_enabled(self):
        return self._situation_scoring_enabled

    def set_situation_scoring(self, scoring_enabled):
        self._situation_scoring_enabled = scoring_enabled

    @property
    def telemetry_tracker(self):
        return self._telemetry_tracker

    @property
    def collection_tracker(self):
        return self._collection_tracker

    def get_household_collections(self):
        return self.collection_tracker.collection_data

    def add_adopting_sim(self, sim_id):
        self._adopting_sim_ids.add(sim_id)

    def remove_adopting_sim(self, sim_id):
        if sim_id in self._adopting_sim_ids:
            self._adopting_sim_ids.remove(sim_id)

    @property
    def free_slot_count(self):

        def slot_count(sim_info):
            pregnancy_tracker = sim_info.pregnancy_tracker
            if pregnancy_tracker.is_pregnant:
                return 1 + pregnancy_tracker.offspring_count
            return 1

        used_slot_count = sum(slot_count(sim_info) for sim_info in self) + len(self._adopting_sim_ids)
        return self.MAXIMUM_SIZE - used_slot_count

    @property
    def household_size(self):
        return len(self._sim_infos)

    @property
    def cheats_enabled(self):
        return self._cheats_enabled

    @cheats_enabled.setter
    def cheats_enabled(self, value):
        self._cheats_enabled = value
        if value:
            self._has_cheated = True

    @property
    def has_cheated(self):
        return self._has_cheated

    @property
    def zone_id(self):
        if self._sim_infos:
            return self._sim_infos[0].zone_id
        return 0

    @property
    def is_npc_household(self):
        client = services.client_manager().get_client_by_household_id(self.id)
        is_npc = client is None
        return is_npc

    def get_highest_medal_for_situation(self, situation_id):
        highest_medal = self._highest_earned_situation_medals.get(situation_id)
        if highest_medal is None:
            return -1
        return highest_medal

    def set_highest_medal_for_situation(self, situation_id, medal_earned):
        if situation_id is not None:
            highest_medal = self._highest_earned_situation_medals.get(situation_id)
            if medal_earned is not None and (highest_medal is None or highest_medal < medal_earned):
                self._highest_earned_situation_medals[situation_id] = medal_earned

    def get_sims_at_home(self):
        at_home_sim_ids = set()
        for sim_info in self.sim_info_gen():
            while sim_info.zone_id == self.home_zone_id and not sim_info.is_instanced(allow_hidden_flags=HiddenReasonFlag.NOT_INITIALIZED) and not sim_info.career_tracker.currently_during_work_hours:
                at_home_sim_ids.add(sim_info.id)
        return at_home_sim_ids

    def household_net_worth(self, billable=False):
        household_inventory_value = build_buy.get_household_inventory_value(self.id)
        if household_inventory_value is None:
            household_inventory_value = 0
        sim_inventories_value = 0
        for sim_info in self.sim_info_gen():
            sim_inventories_value += sim_info.inventory_value()
        final_household_value = self._cached_billable_household_value + household_inventory_value + sim_inventories_value
        home_zone = services.get_zone(self.home_zone_id)
        if home_zone is None and billable:
            return final_household_value
        if not billable:
            household_funds = self._funds.money
            if home_zone is None:
                return final_household_value + household_funds
        billable_value = 0
        billable_value += home_zone.lot.unfurnished_lot_value
        for obj in services.object_manager().values():
            if obj.get_household_owner_id() != self.id:
                pass
            billable_value += obj.current_value
            obj_inventory = obj.inventory_component
            while obj_inventory is not None:
                billable_value += obj_inventory.inventory_value
        self._cached_billable_household_value = billable_value
        final_household_value = self._cached_billable_household_value + household_inventory_value + sim_inventories_value
        if billable:
            return final_household_value
        return final_household_value + household_funds

    def pay_what_you_can(self, cost, bill_source=None, sim=None):
        if self.remote_connected:
            return
        if sim is None:
            sim = self.instanced_sims_gen(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if cost > self.funds.money:
            unpaid_amount = cost - self.funds.money
            cost = self.funds.money
        else:
            unpaid_amount = 0
        reserved_funds = self.funds.try_remove(cost, reason=Consts_pb2.TELEMETRY_INTERACTION_COST, sim=sim)
        if reserved_funds is None:
            logger.error('Failed to reserve {} simoleons when we have {} simoleons.', cost, self.funds.money, owner='bhill')
            self.bills_manager.add_additional_bill_cost(bill_source, cost + unpaid_amount)
        else:
            reserved_funds.apply()
            if unpaid_amount > 0:
                self.bills_manager.add_additional_bill_cost(bill_source, unpaid_amount)

    @property
    def remote_connected(self):
        return self._remote_connected

    @remote_connected.setter
    def remote_connected(self, value):
        self._remote_connected = value

    @property
    def client(self):
        return services.client_manager().get_client_by_household_id(self.id)

    def on_all_households_and_sim_infos_loaded(self):
        self.bills_manager.on_all_households_and_sim_infos_loaded()

    def on_client_disconnect(self):
        self.bills_manager.on_client_disconnect()
        self.telemetry_tracker.on_client_disconnect()
        if self._aging_update_alarm is not None:
            alarms.cancel_alarm(self._aging_update_alarm)

    def instanced_sims_gen(self, allow_hidden_flags=0):
        for sim_info in self._sim_infos:
            while sim_info.is_instanced(allow_hidden_flags=allow_hidden_flags):
                yield sim_info.get_sim_instance(allow_hidden_flags=allow_hidden_flags)

    def sim_info_gen(self):
        for sim_info in self._sim_infos:
            yield sim_info

    def baby_info_gen(self):
        for sim_info in self._sim_infos:
            while sim_info.is_baby:
                yield sim_info

    def teen_or_older_info_gen(self):
        for sim_info in self._sim_infos:
            while sim_info.is_teen_or_older:
                yield sim_info

    @property
    def number_of_babies(self):
        baby_count = 0
        for sim_info in self._sim_infos:
            while sim_info.is_baby:
                baby_count += 1
        return baby_count

    def add_cas_part_to_reward_inventory(self, cas_part):
        reward_part_data = serialization.RewardPartData()
        reward_part_data.part_id = cas_part
        reward_part_data.is_new_reward = True
        self._reward_inventory.reward_parts.append(reward_part_data)

    def part_in_reward_inventory(self, cas_part):
        for reward_part_data in self._reward_inventory.reward_parts:
            while reward_part_data.part_id == cas_part:
                return True
        return False

    def get_create_op(self, *args, **kwargs):
        return distributor.ops.HouseholdCreate(self, *args, **kwargs)

    def get_delete_op(self):
        return distributor.ops.HouseholdDelete()

    def get_create_after_objs(self):
        return ()

    def on_add(self):
        if self.account:
            self.account.add_household(self)
        distributor_inst = distributor.system.Distributor.instance()
        distributor_inst.add_object(self)

    def on_remove(self):
        if self.account:
            self.account.remove_household(self)
        distributor_inst = distributor.system.Distributor.instance()
        distributor_inst.remove_object(self)

    def can_add_sim_info(self, sim_info):
        if sim_info in self:
            return False
        pregnancy_tracker = sim_info.pregnancy_tracker
        if pregnancy_tracker.is_pregnant:
            requested_slot_count = 1 + pregnancy_tracker.offspring_count
        else:
            requested_slot_count = 1
        return requested_slot_count <= self.free_slot_count

    def add_sim_info(self, sim_info, process_events=True):
        self._sim_infos.append(sim_info)
        if self.home_zone_id:
            for trait in tuple(t for t in sim_info.trait_tracker if t.is_npc_only):
                sim_info.trait_tracker.remove_trait(trait)
        if process_events:
            self._on_sim_added(sim_info)

    def _on_sim_added(self, sim_info):
        self.notify_dirty()
        services.get_event_manager().process_event(test_events.TestEvent.HouseholdChanged, sim_info=sim_info)
        for unlock in sim_info.build_buy_unlocks:
            self.add_build_buy_unlock(unlock)
        sim_info.refresh_age_settings()

    def remove_sim_info(self, sim_info, destroy_if_empty_gameplay_household=False):
        self._sim_infos.remove(sim_info)
        sim_info.assign_to_household(None, assign_is_npc=False)
        self.notify_dirty()
        services.get_event_manager().process_event(test_events.TestEvent.HouseholdChanged, sim_info=sim_info)
        if self._sim_infos or destroy_if_empty_gameplay_household and self.get_household_type() == HouseholdType.GAME_CREATED:
            services.get_persistence_service().del_household_proto_buff(self.id)
            services.household_manager().remove(self)

    def sim_in_household(self, sim_id):
        for sim_info in self._sim_infos:
            while sim_info.sim_id == sim_id:
                return True
        return False

    def all_sims_skip_load(self):
        return all(sim_info.sim_creation_path != serialization.SimData.SIMCREATION_NONE for sim_info in self._sim_infos)

    @property
    def size_of_household(self):
        return len(self._sim_infos)

    def add_sim_to_household(self, sim):
        self.add_sim_info_to_household(sim.sim_info)

    def add_sim_info_to_household(self, sim_info):
        sim_info.assign_to_household(self)
        self.add_sim_info(sim_info)
        sim_info.set_default_relationships(reciprocal=True, update_romance=False)

    @property
    def build_buy_unlocks(self):
        return self._build_buy_unlocks

    def add_build_buy_unlock(self, unlock):
        self._build_buy_unlocks.add(unlock)

    def get_sim_info_by_id(self, sim_id):
        for sim_info in self._sim_infos:
            while sim_info.sim_id == sim_id:
                return sim_info

    def get_by_id(self, sim_id):
        for sim_info in self._sim_infos:
            while sim_info.sim_id == sim_id:
                return sim_info.get_sim_instance()

    def add_watcher(self, handle, f):
        self._watchers[handle] = f
        return handle

    def remove_watcher(self, handle):
        return self._watchers.pop(handle)

    def notify_dirty(self):
        for watcher in self._watchers.values():
            watcher()

    def set_default_relationships(self):
        for sim_info in self:
            sim_info.set_default_relationships(reciprocal=True)

    def refresh_sim_data(self, sim_id, assign=False, spawn=False, selectable=False):
        try:
            sim_proto = services.get_persistence_service().get_sim_proto_buff(sim_id)
            sim_info = services.sim_info_manager().get(sim_id)
            if sim_info is not None:
                current_outfit = sim_info.get_current_outfit()
                sim_info.load_sim_info(sim_proto)
                sim_info.resend_outfits()
                if sim_info.sim_outfits.has_outfit(current_outfit):
                    sim_info._current_outfit = current_outfit
                else:
                    sim_info._current_outfit = (OutfitCategory.EVERYDAY, 0)
            else:
                sim_info = sims.sim_info.SimInfo(sim_id=sim_id, account=self.account)
                sim_info.load_sim_info(sim_proto)
            if not self.sim_in_household(sim_id):
                if assign:
                    sim_info.assign_to_household(self, assign_is_npc=False)
                    self.add_sim_info(sim_info)
                    sim_info.set_default_relationships(reciprocal=True, update_romance=False)
                else:
                    self.add_sim_info(sim_info)
            if sim_info.is_baby:
                sims.baby.on_sim_spawn(sim_info)
            else:
                sims.sim_spawner.SimSpawner.spawn_sim(sim_info, None)
            while (spawn or selectable) and selectable:
                client = services.client_manager().get_client_by_household_id(self.id)
                client.add_selectable_sim_info(sim_info)
        except Exception:
            logger.exception('Sim {} failed to load', sim_id)

    def refresh_data(self):
        if self.account is None:
            logger.error('Attempt to refresh_data on a household with no bound account. Household: {}', self)
            return
        household_proto = services.get_persistence_service().get_household_proto_buff(self.id)
        if not household_proto:
            logger.error('FAILED TO LOAD Household (returned None), {}', self)
            return
        for sim_id in household_proto.sims.ids:
            self.refresh_sim_data(sim_id)

    def load_data(self, householdProto):
        self.name = householdProto.name
        self.description = householdProto.description
        self.id = householdProto.household_id
        self.home_zone_id = householdProto.home_zone
        self.last_modified_time = householdProto.last_modified_time
        self._funds = sims.funds.FamilyFunds(self, householdProto.money)
        self._rebate_manager = sims.rebate_manager.RebateManager(self)
        self.is_persistent_npc = householdProto.is_npc
        self.hidden = householdProto.hidden
        self.creator_id = householdProto.creator_id
        self.creator_name = householdProto.creator_name
        self.creator_uuid = householdProto.creator_uuid
        if householdProto.sims.ids:
            for sim_id in householdProto.sims.ids:
                try:
                    sim_info = services.sim_info_manager().get(sim_id)
                    if sim_info is None:
                        sim_info = sims.sim_info.SimInfo(sim_id=sim_id, account=self.account)
                    sim_proto = services.get_persistence_service().get_sim_proto_buff(sim_id)
                    sim_info.load_sim_info(sim_proto)
                    while not self.sim_in_household(sim_id):
                        self.add_sim_info(sim_info, process_events=False)
                except Exception:
                    logger.exception('Sim {} failed to load', sim_id)
        self.bills_manager.load_data(householdProto)
        self.collection_tracker.load_data(householdProto)
        for record_msg in householdProto.gameplay_data.service_npc_records:
            record = self.get_service_npc_record(record_msg.service_type, add_if_no_record=True)
            record.load_npc_record(record_msg)
        for situation_medal in householdProto.gameplay_data.highest_earned_situation_medals:
            self._highest_earned_situation_medals[situation_medal.situation_id] = situation_medal.medal
        self._last_active_sim_id = householdProto.last_played
        self._reward_inventory = serialization.RewardPartList()
        self._reward_inventory.CopyFrom(householdProto.reward_inventory)
        old_unlocks = set(list(householdProto.gameplay_data.build_buy_unlocks))
        self._build_buy_unlocks = set()
        for unlock in old_unlocks:
            key = sims4.resources.Key(Types.OBJCATALOG, unlock, 0)
            self._build_buy_unlocks.add(key)
        if hasattr(householdProto.gameplay_data, 'build_buy_unlock_list'):
            for key_proto in householdProto.gameplay_data.build_buy_unlock_list.resource_keys:
                key = sims4.resources.Key(key_proto.type, key_proto.instance, key_proto.group)
                self._build_buy_unlocks.add(key)
        if hasattr(householdProto.gameplay_data, 'situation_scoring_enabled'):
            self._situation_scoring_enabled = householdProto.gameplay_data.situation_scoring_enabled
        self._cached_billable_household_value = householdProto.gameplay_data.billable_household_value

    def save_data(self):
        household_msg = services.get_persistence_service().get_household_proto_buff(self.id)
        if household_msg is None:
            household_msg = services.get_persistence_service().add_household_proto_buff()
        inventory = serialization.ObjectList()
        inventory.CopyFrom(household_msg.inventory)
        household_msg.Clear()
        household_msg.account_id = self.account.id
        household_msg.household_id = self.id
        household_msg.name = self.name
        household_msg.description = self.description
        household_msg.home_zone = self.home_zone_id
        household_msg.last_modified_time = self.last_modified_time
        household_msg.money = self.funds.money
        household_msg.hidden = self.hidden
        household_msg.creator_id = self.creator_id
        household_msg.creator_name = self.creator_name
        if self.creator_uuid is not None:
            household_msg.creator_uuid = self.creator_uuid
        household_msg.inventory = inventory
        household_msg.reward_inventory = self._reward_inventory
        household_msg.gameplay_data.build_buy_unlock_list = ResourceKey_pb2.ResourceKeyList()
        for unlock in self.build_buy_unlocks:
            if isinstance(unlock, int):
                unlock = sims4.resources.Key(Types.OBJCATALOG, unlock, 0)
            key_proto = sims4.resources.get_protobuff_for_key(unlock)
            household_msg.gameplay_data.build_buy_unlock_list.resource_keys.append(key_proto)
        household_msg.gameplay_data.situation_scoring_enabled = self._situation_scoring_enabled
        if self.sim_in_household(self._last_active_sim_id):
            household_msg.last_played = self._last_active_sim_id
        household_msg.is_npc = self.is_persistent_npc
        household_msg.gameplay_data.billable_household_value = self.household_net_worth(billable=True)
        household_msg.gameplay_data.ClearField('highest_earned_situation_medals')
        for (situation_id, medal) in self._highest_earned_situation_medals.items():
            with ProtocolBufferRollback(household_msg.gameplay_data.highest_earned_situation_medals) as situation_medal:
                situation_medal.situation_id = situation_id
                situation_medal.medal = medal
        self.bills_manager.save_data(household_msg)
        self.collection_tracker.save_data(household_msg)
        if self._service_npc_record is not None:
            for service_record in self._service_npc_record.values():
                with ProtocolBufferRollback(household_msg.gameplay_data.service_npc_records) as record_msg:
                    service_record.save_npc_record(record_msg)
        id_list = serialization.IdList()
        for sim_info in self:
            id_list.ids.append(sim_info.id)
        household_msg.sims = id_list
        return True

    def get_service_npc_record(self, service_guid64, add_if_no_record=True):
        if self._service_npc_record is None:
            if add_if_no_record:
                self._service_npc_record = {}
            else:
                return
        record = self._service_npc_record.get(service_guid64)
        if record is None and add_if_no_record:
            record = ServiceNpcRecord(service_guid64, self)
            self._service_npc_record[service_guid64] = record
        return record

    def get_all_hired_service_npcs(self):
        all_hired = []
        if self._service_npc_record is None:
            return all_hired
        for (service_guid64, record) in self._service_npc_record.items():
            while record.hired:
                all_hired.append(service_guid64)
        return all_hired

    def prune_distant_relatives(self):
        with genealogy_caching():
            open_list = []
            closed_list = set()
            prune_list = set()
            active_household_id = services.active_household_id()
            for sim_info in self:
                while not sim_info.is_dead:
                    heapq.heappush(open_list, (-self.ANCESTRY_PURGE_DEPTH, sim_info.id))

            def visit(sim_info, depth):
                if sim_info not in closed_list:
                    closed_list.add(sim_info)
                    heapq.heappush(open_list, (depth, sim_info.id))
                    if depth > 0:
                        if sim_info.household_id != active_household_id and not sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS):
                            prune_list.add(sim_info)

            sim_info_manager = services.sim_info_manager()
            while open_list:
                (depth, sim_info_id) = heapq.heappop(open_list)
                sim_info = sim_info_manager.get(sim_info_id)
                while sim_info is not None:
                    while True:
                        for relative_id in sim_info.genealogy.get_immediate_family_sim_ids_gen():
                            relative = sim_info_manager.get(relative_id)
                            while relative is not None:
                                visit(relative, depth + 1)
        for sim_info in prune_list:
            sim_info.household.remove_sim_info(sim_info)
            sim_info_manager.remove_permanently(sim_info)
            services.get_persistence_service().del_sim_proto_buff(sim_info.id)

    def on_active_sim_changed(self, new_sim):
        self._last_active_sim_id = new_sim.id

    def get_household_type(self):
        household_id = self.id
        if household_id in services.household_manager():
            if not self.is_persistent_npc:
                return HouseholdType.USER_CREATED_PLAYABLE
            account = self.account
            if account is not None:
                household_id = self.id
                if services.household_manager().is_household_stored_in_any_neighborhood_proto(household_id):
                    return HouseholdType.USER_CREATED_NPC
            return HouseholdType.GAME_CREATED
        logger.error("Tried to get the household type of a household that isn't in the household manager. household name: {} household id: {}", self.name, household_id, owner='yshan')
        return HouseholdType.UNKNOWN

    def merge(self, merge_with_id):
        otherhouse = services.get_persistence_service().get_household_proto_buff(merge_with_id)
        self._funds.add(otherhouse.money, TELEMETRY_HOUSEHOLD_TRANSFER_GAIN, None)
        self._reward_inventory.reward_parts.extend(otherhouse.reward_inventory.reward_parts)
        for sim_id in otherhouse.sims.ids:
            self.refresh_sim_data(sim_id, assign=True, spawn=True, selectable=True)
        services.get_persistence_service().del_household_proto_buff(merge_with_id)

    @property
    def autonomy_settings(self):
        return self._autonomy_settings

    def initialize_sim_infos(self):
        for sim_info in self._sim_infos:
            self._on_sim_added(sim_info)
            sim_info.update_school_career()

    def _send_household_aging_update(self, _):
        for sim_info in self._sim_infos:
            sim_info.send_age_progress_bar_update()

    def refresh_aging_updates(self, sim_info):
        sim_info.send_age_progress_bar_update()
        if self._aging_update_alarm is None:
            self._age_update_handle = alarms.add_alarm(self, create_time_span(days=AgingTuning.AGE_PROGRESS_UPDATE_TIME), self._send_household_aging_update, True)

    def clear_household_lot_ownership(self, zone_id):
        zone_data_proto = services.get_persistence_service().get_zone_proto_buff(zone_id)
        zone_data_proto.household_id = 0
        neighborhood_id = zone_data_proto.neighborhood_id
        neighborhood_proto = services.get_persistence_service().get_neighborhood_proto_buff(neighborhood_id)
        for lot_owner_info in neighborhood_proto.lots:
            while lot_owner_info.zone_instance_id == zone_id:
                lot_owner_info.ClearField('lot_owner')
                break

