import math
import sys
import weakref
from protocolbuffers import SimObjectAttributes_pb2 as protocols, DistributorOps_pb2, FileSerialization_pb2 as serialization, GameplaySaveData_pb2 as gameplay_serialization
from protocolbuffers.Consts_pb2 import MSG_SIM_SKILL_UPDATE
from protocolbuffers.DistributorOps_pb2 import SetWhimBucks
from protocolbuffers.Localization_pb2 import LocalizedStringToken
from protocolbuffers.ResourceKey_pb2 import ResourceKeyList
from away_actions.away_action_tracker import AwayActionTracker
from away_actions.away_actions import AwayAction
from away_actions.away_actions_interactions import ApplyDefaultAwayActionInteraction
from careers.career_tracker import CareerTracker
from careers.career_tuning import CareerCategory
from cas.cas import BaseSimInfo
from clock import interval_in_sim_days
from date_and_time import DateAndTime, TimeSpan
from distributor.rollback import ProtocolBufferRollback
from distributor.shared_messages import add_object_message, IconInfoData
from distributor.system import Distributor
from event_testing import test_events
from interactions.aop import AffordanceObjectPair
from interactions.utils.adventure import AdventureTracker
from interactions.utils.death import DeathTracker
from interactions.utils.pregnancy import PregnancyTracker, PregnancyClientMixin
from interactions.utils.routing import WalkStyleRequest, WalkStyle
from objects import ALL_HIDDEN_REASONS, ALL_HIDDEN_REASONS_EXCEPT_UNINITIALIZED
from objects.components import ComponentContainer, forward_to_components_gen, forward_to_components
from objects.components.consumable_component import ConsumableComponent
from objects.components.inventory_enums import InventoryType
from objects.components.inventory_item import ItemLocation
from objects.components.statistic_component import HasStatisticComponent
from objects.system import create_object
from relationships.relationship import Relationship
from relationships.relationship_tracker import RelationshipTracker
from services.persistence_service import PersistenceTuning
from sims.aging import AgingMixin
from sims.baby import Baby, on_sim_removed_baby_handle
from sims.genealogy_tracker import GenealogyTracker, FamilyRelationshipIndex
from sims.global_gender_preference_tuning import GlobalGenderPreferenceTuning
from sims.sim_info_types import SimInfoSpawnerTags, Age
from sims.sim_outfits import OutfitCategory, SimOutfits
from sims.unlock_tracker import UnlockTracker
from sims4.callback_utils import CallableList, protected_callback
from sims4.protocol_buffer_utils import persist_fields_for_new_game
from sims4.resources import Types
from sims4.tuning.tunable import TunableResourceKey, Tunable, TunableList, TunableReference, TunableTuple, TunableMapping
from sims4.utils import RegistryHandle
from singletons import DEFAULT
from statistics.commodity import Commodity
from traits.trait_tracker import TraitTrackerSimInfo
from world.spawn_point import SpawnPointOption, SpawnPoint
import aspirations.aspirations
import caches
import date_and_time
import distributor.fields
import distributor.ops
import enum
import id_generator
import interactions.utils.routing
import itertools
import objects.components
import objects.system
import placement
import routing
import server.permissions
import services
import sims.sim_info_types as types
import sims.sim_outfits
import sims4.log
import sims4.resources
import statistics.commodity
import tag
import telemetry_helper
import whims
logger = sims4.log.Logger('SimInfo')
TELEMETRY_CHANGE_ASPI = 'ASPI'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_CHANGE_ASPI)
with sims4.reload.protected(globals()):
    SAVE_ACTIVE_HOUSEHOLD_COMMAND = False

class SimInfo(AgingMixin, PregnancyClientMixin, ComponentContainer, HasStatisticComponent):
    __qualname__ = 'SimInfo'

    class DirtyFlags(enum.Int, export=False):
        __qualname__ = 'SimInfo.DirtyFlags'
        GENDER = 0
        FIRSTNAME = 1
        LASTNAME = 2
        AREAID = 3
        AGE = 4
        AGE_PROGRESS = 5
        CURRENT_SKILL_ID = 6
        FULL_NAME = 7

    class BodyBlendTypes(enum.Int, export=False):
        __qualname__ = 'SimInfo.BodyBlendTypes'
        BODYBLENDTYPE_HEAVY = 0
        BODYBLENDTYPE_FIT = 1
        BODYBLENDTYPE_LEAN = 2
        BODYBLENDTYPE_BONY = 3
        BODYBLENDTYPE_PREGNANT = 4
        BODYBLENDTYPE_HIPS_WIDE = 5
        BODYBLENDTYPE_HIPS_NARROW = 6
        BODYBLENDTYPE_WAIST_WIDE = 7
        BODYBLENDTYPE_WAIST_NARROW = 8

    DEFAULT_THUMBNAIL = TunableResourceKey(None, resource_types=sims4.resources.CompoundTypes.IMAGE, description='Icon to be displayed for the Buff.')
    SIM_DEFINITION = TunableReference(description='\n        The definition used to instantiate Sims.', manager=services.definition_manager(), class_restrictions='Sim')
    CHILD_SKILLS = TunableList(TunableReference(services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions='Skill', description='The skills applied to children'))
    SCHOOL_CAREER = TunableReference(services.get_instance_manager(sims4.resources.Types.CAREER), description='The school career children can join')
    HIGH_SCHOOL_CAREER = TunableReference(services.get_instance_manager(sims4.resources.Types.CAREER), description='The school career teens can join')
    CHILD_HOMEWORK = TunableReference(manager=services.definition_manager(), description='The homework a child can use to increase school performance.')
    TEEN_HOMEWORK = TunableReference(manager=services.definition_manager(), description='The homework a teen can use to increase school performance.')
    MAX_CAREERS = Tunable(description='\n        This defines the maximum number of careers a sim can have simultaneously, also enabling\n        children and teens to have careers in addition to their school career.', tunable_type=int, default=1)
    PHYSIQUE_CHANGE_AFFORDANCES = TunableTuple(description="\n        Affordances to run when a Sim's physique changes.\n        ", FAT_CHANGE_POSITIVE_AFFORDANCE=TunableReference(description="\n            Affordance to run when a Sim's fat changes to positive effect.\n            ", manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), FAT_CHANGE_MAX_POSITIVE_AFFORDANCE=TunableReference(description="\n            Affordance to run when a Sim's fat changes to maximum positive effect.\n            ", manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), FAT_CHANGE_NEGATIVE_AFFORDANCE=TunableReference(description="\n            Affordance to run when a Sim's fat changes to negative effect.\n            ", manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), FAT_CHANGE_MAX_NEGATIVE_AFFORDANCE=TunableReference(description="\n            Affordance to run when a Sim's fat changes to maximum negative effect.\n            ", manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), FAT_CHANGE_NEUTRAL_AFFORDANCE=TunableReference(description="\n            Affordance to run when a Sim's fat changes to neutral effect.\n            ", manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), FIT_CHANGE_POSITIVE_AFFORDANCE=TunableReference(description="\n            Affordance to run when a Sim's fitness changes to positive effect.\n            ", manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), FIT_CHANGE_NEGATIVE_AFFORDANCE=TunableReference(description="\n            Affordance to run when a Sim's fitness changes to negative effect.\n            ", manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), FIT_CHANGE_NEUTRAL_AFFORDANCE=TunableReference(description="\n            Affordance to run when a Sim's fitness changes to neutral effect.\n            ", manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)))
    MAXIMUM_SAFE_FITNESS_VALUE = Tunable(description="\n        This is the value over which a Sim's fitness will always decay.  When a\n        Sim's fitness is set initially inside of CAS, it will not decay below\n        that value unless it is higher than this tunable. Sims with an initial\n        fitness value higher than this tunable will see their fitness commodity\n        decay towards this point.\n        \n        EXAMPLE: MAXIMUM_SAFE_FITNESS_VALUE is set to 90, and a Sim is created\n        in CAS with a fitness value of 100.  Their fitness commodity will decay\n        towards 90.  Another Sim is created with a fitness value of 80.  Their\n        fitness commodity will decay towards 80.\n        ", tunable_type=int, default=90)
    INITIAL_COMMODITIES = TunableList(description='\n        A list of commodities that are added every sim info on its creation.\n        ', tunable=TunableReference(description='\n            A commodity that will be added to each sim info on its creation.\n            ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions=statistics.commodity.Commodity))
    INITIAL_STATIC_COMMODITIES = TunableList(description='\n        A list of static commodities that are added to ever sim info on its\n        creation.\n        ', tunable=TunableReference(description='\n            A static commodity that is added to each sim info on its creation.\n            ', manager=services.get_instance_manager(sims4.resources.Types.STATIC_COMMODITY)))
    INITIAL_STATISTICS = TunableList(description='\n        A list of statistics that will be added to each sim info on its\n        creation.\n        ', tunable=TunableReference(description='\n            A statistic that will be added to each sim info on its creation.\n            ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)))
    AWAY_ACTIONS = TunableMapping(description='\n        A mapping between affordances and lists of away actions.  The\n        affordances are used to generate AoPs with each of the away actions.\n        ', key_type=TunableReference(description='\n            The interaction that will be used to create AoPs from the away list\n            of away actions that it is mapped to.\n            ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), value_type=TunableList(description='\n            A list of away actions that are available for the player to select\n            from and apply to the sim.\n            ', tunable=AwayAction.TunableReference()))
    DEFAULT_AWAY_ACTION = TunableMapping(description='\n        Map of commodities to away action.  When the default away action is\n        asked for we look at the ad data of each commodity and select the away\n        action linked to the commodity that is advertising the highest.\n        ', key_type=Commodity.TunableReference(description='\n            The commodity that we will look at the advertising value for.\n            '), value_type=AwayAction.TunableReference(description='\n            The away action that will applied if the key is the highest\n            advertising commodity of the ones listed.\n            '))
    APPLY_DEFAULT_AWAY_ACTION_INTERACTION = ApplyDefaultAwayActionInteraction.TunableReference(description='\n        Interaction that will be used to apply the default away action onto the\n        sim info.\n        ')
    SIM_SKEWER_AFFORDANCES = TunableList(description="\n        A list of affordances that will test and be available when the player\n        clicks on a Sim's interaction button in the Sim skewer.\n        ", tunable=TunableReference(description="\n            An affordance shown when the player clicks on a sim's\n            interaction button in the Sim skewer.\n            ", manager=services.affordance_manager()))
    GO_HOME_FROM_OPEN_STREET = TunableReference(description='\n        An affordance to push onto active household members left on the open\n        street but was not part of the traveling sims.\n        ', manager=services.affordance_manager())

    def __init__(self, sim_id:int=0, gender:types.Gender=types.Gender.MALE, age:types.Age=types.Age.ADULT, first_name:str='', last_name:str='', full_name_key=0, physique:str='', zone_id:int=0, zone_name='', world_id:int=0, account=None):
        super().__init__()
        self.primitives = distributor.ops.DistributionSet(self)
        self.manager = None
        self._revision = 0
        self.on_outfit_changed = CallableList()
        if sim_id:
            self._dirty_flags = 0
            self.sim_id = sim_id
        else:
            self._dirty_flags = sys.maxsize
            self.sim_id = id_generator.generate_object_id()
        self._base = BaseSimInfo(sim_id, first_name, last_name, full_name_key, age, gender, 1, physique)
        self.add_component(objects.components.buff_component.BuffComponent(self))
        self._base.voice_pitch = 0.0
        self._base.voice_actor = 0
        self._base.voice_effect = 0
        self._base.facial_attributes = ''
        self._outfits = sims.sim_outfits.SimOutfits(self)
        self._set_current_outfit_without_distribution((OutfitCategory.EVERYDAY, 0))
        self._previous_outfit = (OutfitCategory.EVERYDAY, 0)
        self._flags = 0
        self._zone_id = zone_id
        self.zone_name = zone_name
        self._world_id = world_id
        self._account = account
        self._sim_ref = None
        self._gameplay_fx = types.SimVFXOption.FILTER_NONE
        self._serialization_option = sims.sim_info_types.SimSerializationOption.UNDECLARED
        self._household_id = None
        self._relationship_tracker = RelationshipTracker(self)
        self._personal_funds = 0
        self._autonomy_scoring_preferences = {}
        self._autonomy_use_preferences = {}
        self._trait_tracker = TraitTrackerSimInfo(self)
        self._aspiration_tracker = aspirations.aspirations.AspirationTracker(self)
        self._aspirations_blob = None
        self._primary_aspiration = 0
        self._current_skill_guid = 0
        self._fat = 0
        self._fit = 0
        self._pregnancy_tracker = PregnancyTracker(self)
        self._death_tracker = DeathTracker(self)
        self._sim_permissions = server.permissions.SimPermissions()
        self._adventure_tracker = AdventureTracker()
        self._royalty_tracker = sims.royalty_tracker.RoyaltyTracker(self)
        self._career_tracker = CareerTracker(self)
        self._genealogy_tracker = GenealogyTracker(self.id)
        self.thumbnail = self.DEFAULT_THUMBNAIL
        self._whim_tracker = whims.whims_tracker.WhimsTracker(self)
        self._current_whims = []
        self._whim_bucks = 0
        self._sim_creation_path = None
        self._time_sim_was_saved = None
        self._additional_bonus_days = 0
        self.startup_sim_location = None
        self._si_state = None
        self._has_loaded_si_state = False
        self._cached_inventory_value = 0
        self.spawn_point_id = None
        self.spawner_tags = []
        self.spawn_point_option = SpawnPointOption.SPAWN_ANY_POINT_WITH_CONSTRAINT_TAGS
        self.game_time_bring_home = None
        self._initial_fitness_value = None
        self._build_buy_unlocks = set()
        self._unlock_tracker = UnlockTracker(self)
        self._away_action_tracker = AwayActionTracker(self)
        self._singed = False
        self._walkstyle_requests = [WalkStyleRequest(-1, WalkStyle.WALK)]
        self._walk_style_handles = {}
        self.goodbye_notification = None
        self.creation_source = 'Unknown'

    def ref(self, callback=None):
        return weakref.ref(self, protected_callback(callback))

    def on_loading_screen_animation_finished(self):
        self._career_tracker.on_loading_screen_animation_finished()

    def on_situation_request(self, situation):
        self._career_tracker.on_situation_request(situation)

    def update_fitness_state(self):
        sim = self._sim_ref()
        if not sim.needs_fitness_update:
            return
        sim.needs_fitness_update = False
        self._set_fit_fat()

    @property
    def household(self):
        return services.household_manager().get(self._household_id)

    def on_add(self):
        self.commodity_tracker.add_watcher(self._publish_commodity_update)
        self.statistic_tracker.add_watcher(self._publish_statistic_update)

    @forward_to_components
    def on_remove(self):
        with self.relationship_tracker.suppress_client_updates_context_manager():
            self.buffs_component.clean_up()
        self._whim_tracker.clean_up()
        self._current_whims.clear()
        self._away_action_tracker.clean_up()
        self._career_tracker.clean_up()
        if self.is_instanced():
            on_sim_removed_baby_handle(self, self.zone_id)
        if self.household is not None:
            if self.household.client is not None:
                self.household.client.set_next_sim_or_none(only_if_this_active_sim_info=self)
                self.household.client.selectable_sims.remove_selectable_sim_info(self)
            self.household.remove_sim_info(self)

    @property
    def is_enabled_in_skewer(self):
        if self.is_baby:
            return False
        return True

    def remove_child_only_features(self):
        for skill in self.CHILD_SKILLS:
            tracker = self.get_tracker(skill)
            tracker.remove_statistic(skill)

    def init_child_skills(self):
        if self.is_child:
            for skill in self.CHILD_SKILLS:
                tracker = self.get_tracker(skill)
                tracker.add_statistic(skill)

    def generate_career_outfit(self, tag_list=[]):
        self._base.generate_career_outfit(tag_list)
        getOutfitsPB = DistributorOps_pb2.SetSimOutfits()
        getOutfitsPB.ParseFromString(self._base.outfits)
        self._outfits.load_sim_outfits_from_cas_proto(getOutfitsPB)
        self.resend_outfits()

    def generate_outfit(self, outfit_category=OutfitCategory.EVERYDAY, outfit_index=0, tag_list=[]):
        self._base.generate_outfit(outfit_category, outfit_index, tag_list)
        getOutfitsPB = DistributorOps_pb2.SetSimOutfits()
        getOutfitsPB.ParseFromString(self._base.outfits)
        self._outfits.load_sim_outfits_from_cas_proto(getOutfitsPB)
        self.resend_outfits()

    def inventory_value(self):
        sim = self.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if sim is not None:
            self._cached_inventory_value = sim.inventory_component.inventory_value
        return self._cached_inventory_value

    def __repr__(self):
        return "<sim '{0} {1} {2}' {3:#x}>".format(self._base.first_name, self._base.last_name, self.persona, self.sim_id)

    def _generate_default_away_action_aop(self, context, **kwargs):
        return AffordanceObjectPair(SimInfo.APPLY_DEFAULT_AWAY_ACTION_INTERACTION, None, SimInfo.APPLY_DEFAULT_AWAY_ACTION_INTERACTION, None, away_action_sim_info=self, **kwargs)

    def _generate_away_action_affordances(self, context, **kwargs):
        for (affordance, away_action_list) in SimInfo.AWAY_ACTIONS.items():
            for away_action in away_action_list:
                yield AffordanceObjectPair(affordance, None, affordance, None, away_action=away_action, away_action_sim_info=self, **kwargs)

    def sim_skewer_affordance_gen(self, context, **kwargs):
        career = self._career_tracker.get_currently_at_work_career()
        if career is not None:
            yield career.sim_skewer_affordances_gen(context, **kwargs)
            return
        sim = self.get_sim_instance()
        for affordance in self.SIM_SKEWER_AFFORDANCES:
            if not affordance.simless and sim is None:
                pass
            for aop in affordance.potential_interactions(sim, context, sim_info=self, **kwargs):
                yield aop
        yield self._generate_default_away_action_aop(context, **kwargs)
        yield self._generate_away_action_affordances(context, **kwargs)

    @property
    def id(self):
        return self._sim_id

    @id.setter
    def id(self, value):
        pass

    @property
    def sim_id(self):
        return self._sim_id

    @sim_id.setter
    def sim_id(self, value):
        self._sim_id = value

    @distributor.fields.Field(op=distributor.ops.SetFirstName)
    def first_name(self):
        return self._base.first_name

    @first_name.setter
    def first_name(self, value):
        if self._base.first_name != value:
            self.set_field_dirty(SimInfo.DirtyFlags.FIRSTNAME)
            self._base.first_name = value

    @distributor.fields.Field(op=distributor.ops.SetLastName)
    def last_name(self):
        return self._base.last_name

    @last_name.setter
    def last_name(self, value):
        if self._base.last_name != value:
            self.set_field_dirty(SimInfo.DirtyFlags.LASTNAME)
            self._base.last_name = value

    @property
    def first_name_key(self):
        return self._base.first_name_key

    @first_name_key.setter
    def first_name_key(self, value):
        if self._base.first_name_key != value:
            self.set_field_dirty(SimInfo.DirtyFlags.FIRSTNAME)
            self._base.first_name_key = value

    @property
    def last_name_key(self):
        return self._base.last_name_key

    @last_name_key.setter
    def last_name_key(self, value):
        if self._base.last_name_key != value:
            self.set_field_dirty(SimInfo.DirtyFlags.LASTNAME)
            self._base.last_name_key = value

    @distributor.fields.Field(op=distributor.ops.SetFullNameKey)
    def full_name_key(self):
        return self._base.full_name_key

    @full_name_key.setter
    def full_name_key(self, value):
        if self._base.full_name_key != value:
            self.set_field_dirty(SimInfo.DirtyFlags.FULL_NAME)
            self._base.full_name_key = value

    @property
    def full_name(self):
        return ''

    @distributor.fields.Field(op=distributor.ops.SetAge)
    def age(self):
        return types.Age(self._base.age)

    @age.setter
    def age(self, value):
        self.set_field_dirty(SimInfo.DirtyFlags.AGE)
        self._base.age = value

    resend_age = age.get_resend()

    @property
    def age_progress(self):
        return self._age_progress.get_value()

    @age_progress.setter
    def age_progress(self, value):
        self.set_field_dirty(SimInfo.DirtyFlags.AGE_PROGRESS)
        self._age_progress.set_value(value)

    AGE_PROGRESS_BAR_FACTOR = 100

    @distributor.fields.Field(op=distributor.ops.SetAgeProgress)
    def age_progress_in_days(self):
        return int(self.age_progress/self._age_time*self.AGE_PROGRESS_BAR_FACTOR)

    resend_age_progress = age_progress_in_days.get_resend()

    @property
    def sim_creation_path(self):
        return self._sim_creation_path

    def send_age_progress_bar_update(self):
        self.resend_age_progress()
        days_until_ready_to_age = interval_in_sim_days(self._days_until_ready_to_age())
        current_time = services.time_service().sim_now
        ready_to_age_time = current_time + days_until_ready_to_age
        self.update_time_alive()
        op = distributor.ops.SetSimAgeProgressTooltipData(int(current_time.absolute_days()), int(ready_to_age_time.absolute_days()), int(self._time_alive.in_days()))
        Distributor.instance().add_op(self, op)

    @distributor.fields.Field(op=distributor.ops.SetGender)
    def gender(self):
        return types.Gender(self._base.gender)

    @gender.setter
    def gender(self, value):
        if types.Gender(self._base.gender) != value:
            self.set_field_dirty(SimInfo.DirtyFlags.GENDER)
            self._base.gender = types.Gender(value)

    @property
    def icon_info(self):
        return (self.id, self.manager.id)

    def get_icon_info_data(self):
        return IconInfoData(obj_instance=self)

    @distributor.fields.Field(op=distributor.ops.SetPrimaryAspiration)
    def primary_aspiration(self):
        return self._primary_aspiration

    resend_primary_aspiration = primary_aspiration.get_resend()

    @primary_aspiration.setter
    def primary_aspiration(self, value):
        self._primary_aspiration = value
        self.aspiration_tracker.initialize_aspiration()
        with telemetry_helper.begin_hook(writer, TELEMETRY_CHANGE_ASPI, sim=self.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)) as hook:
            hook.write_guid('aspi', value)

    @distributor.fields.Field(op=distributor.ops.SetCurrentWhims)
    def current_whims(self):
        return self._current_whims

    resend_current_whims = current_whims.get_resend()

    @current_whims.setter
    def current_whims(self, value):
        self._current_whims = value

    def send_whim_bucks_update(self, reason):
        if self.is_selectable:
            op = distributor.ops.SetWhimBucks(self._whim_bucks, reason)
            Distributor.instance().add_op(self, op)

    def set_whim_bucks(self, value, reason):
        self._whim_bucks = value
        self.send_whim_bucks_update(reason)

    def add_whim_bucks(self, amount, reason):
        self.set_whim_bucks(self._whim_bucks + amount, reason)

    def get_whim_bucks(self):
        return self._whim_bucks

    @distributor.fields.Field(op=distributor.ops.SetTraits, should_distribute_fn=lambda sim_info: sim_info.is_selectable)
    def trait_ids(self):
        return self._trait_tracker.trait_ids

    resend_trait_ids = trait_ids.get_resend()

    @distributor.fields.Field(op=distributor.ops.SetDeathType)
    def death_type(self):
        return self._death_tracker.death_type

    resend_death_type = death_type.get_resend()

    @property
    def is_dead(self):
        return self._death_tracker.is_dead

    @property
    def death_tracker(self):
        return self._death_tracker

    @property
    def pregnancy_tracker(self):
        return self._pregnancy_tracker

    @property
    def adventure_tracker(self):
        return self._adventure_tracker

    @property
    def royalty_tracker(self):
        return self._royalty_tracker

    @property
    def away_action_tracker(self):
        return self._away_action_tracker

    @distributor.fields.Field(op=distributor.ops.SetAwayAction)
    def current_away_action(self):
        return self._away_action_tracker.current_away_action

    resend_current_away_action = current_away_action.get_resend()

    def add_statistic(self, stat_type, value):
        tracker = self.get_tracker(stat_type)
        tracker.set_value(stat_type, value, add=True)

    def remove_statistic(self, stat_type):
        tracker = self.get_tracker(stat_type)
        tracker.remove_statistic(stat_type)

    @property
    def si_state(self):
        return self._si_state

    @property
    def has_loaded_si_state(self):
        return self._has_loaded_si_state

    @property
    def is_pregnant(self):
        return self._pregnancy_tracker.is_pregnant

    @property
    def sim_permissions(self):
        return self._sim_permissions

    @property
    def current_skill_guid(self):
        return self._current_skill_guid

    @current_skill_guid.setter
    def current_skill_guid(self, value):
        if self._current_skill_guid != value:
            self.set_field_dirty(SimInfo.DirtyFlags.CURRENT_SKILL_ID)
            self._current_skill_guid = value

    @property
    def zone_id(self):
        return self._zone_id

    def set_zone_on_spawn(self):
        logger.assert_raise(not self.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS), 'Attempting to set instanced sim into current zone.', owner='jjacobson')
        current_zone_id = services.current_zone_id()
        if self._zone_id != current_zone_id:
            self.set_field_dirty(SimInfo.DirtyFlags.AREAID)
            self._zone_id = current_zone_id
            self.world_id = services.get_persistence_service().get_world_id_from_zone(current_zone_id)

    def inject_into_inactive_zone(self, new_zone_id):
        if services.current_zone_id() == new_zone_id:
            logger.error('Attempting to put sim:{} into the active zone:{}', self, services.current_zone())
            return
        if self._zone_id == new_zone_id:
            return
        self.set_field_dirty(SimInfo.DirtyFlags.AREAID)
        self._zone_id = new_zone_id
        self.world_id = services.get_persistence_service().get_world_id_from_zone(new_zone_id)
        self.spawner_tags = []
        self.spawn_point_option = SpawnPointOption.SPAWN_ANY_POINT_WITH_CONSTRAINT_TAGS
        self.startup_sim_location = None
        self._serialization_option = sims.sim_info_types.SimSerializationOption.UNDECLARED
        if self._away_action_tracker is not None:
            self._away_action_tracker.refresh(on_travel_away=True)

    @property
    def world_id(self):
        return self._world_id

    @world_id.setter
    def world_id(self, value):
        if self._world_id != value:
            self.set_field_dirty(SimInfo.DirtyFlags.AREAID)
            self._world_id = value

    @property
    def serialization_option(self):
        return self._serialization_option

    @distributor.fields.Field(op=distributor.ops.SetSkinTone, priority=distributor.fields.Field.Priority.HIGH)
    def skin_tone(self):
        return self._base.skin_tone

    _resend_skin_tone = skin_tone.get_resend()

    def resend_skin_tone(self):
        self._resend_skin_tone()
        if self.is_baby:
            self.resend_baby_skin_tone()

    @skin_tone.setter
    def skin_tone(self, value):
        self._base.skin_tone = value
        if self.is_baby:
            self.resend_baby_skin_tone()

    @distributor.fields.Field(op=distributor.ops.SetBabySkinTone)
    def baby_skin_tone(self):
        return Baby.get_baby_skin_tone_enum(self)

    resend_baby_skin_tone = baby_skin_tone.get_resend()

    @distributor.fields.Field(op=distributor.ops.SetVoicePitch)
    def voice_pitch(self):
        return self._base.voice_pitch

    resend_voice_pitch = voice_pitch.get_resend()

    @voice_pitch.setter
    def voice_pitch(self, value):
        self._base.voice_pitch = value

    @distributor.fields.Field(op=distributor.ops.SetVoiceActor)
    def voice_actor(self):
        return self._base.voice_actor

    resend_voice_actor = voice_actor.get_resend()

    @voice_actor.setter
    def voice_actor(self, value):
        self._base.voice_actor = value

    @distributor.fields.Field(op=distributor.ops.SetVoiceEffect)
    def voice_effect(self):
        return self._base.voice_effect

    @voice_effect.setter
    def voice_effect(self, value):
        self._base.voice_effect = value

    resend_voice_effect = voice_effect.get_resend()

    @distributor.fields.Field(op=distributor.ops.SetPhysique)
    def physique(self):
        return self._base.physique

    resend_physique = physique.get_resend()

    @physique.setter
    def physique(self, value):
        self._base.physique = value

    @property
    def fat(self):
        return self._fat

    @fat.setter
    def fat(self, value):
        self._fat = value

    @property
    def fit(self):
        return self._fit

    @fit.setter
    def fit(self, value):
        self._fit = value

    @distributor.fields.Field(op=distributor.ops.SetSinged, default=False)
    def singed(self):
        return self._singed

    @singed.setter
    def singed(self, value):
        self._singed = value

    @property
    def on_fire(self):
        sim_instance = self.get_sim_instance()
        if not sim_instance:
            return False
        return services.get_fire_service().sim_is_on_fire(sim_instance)

    @property
    def thumbnail(self):
        return self._thumbnail

    @thumbnail.setter
    def thumbnail(self, value):
        if value is not None:
            self._thumbnail = value
        else:
            self._thumbnail = sims4.resources.Key(0, 0, 0)

    @distributor.fields.Field(op=distributor.ops.SetSimOutfits)
    def sim_outfits(self):
        return self._outfits

    resend_outfits = sim_outfits.get_resend()

    @sim_outfits.setter
    def sim_outfits(self, value):
        for outfit_data in value:
            self._outfits.add_outfit(sims.sim_outfits.OutfitCategory.EVERYDAY, outfit_data)

    @distributor.fields.Field(op=distributor.ops.ChangeSimOutfit, priority=distributor.fields.Field.Priority.LOW)
    def _current_outfit(self):
        return self._current_outfit_category_and_index

    @_current_outfit.setter
    def _current_outfit(self, value):
        self._set_current_outfit_without_distribution(value)

    def _set_current_outfit_without_distribution(self, value):
        self._current_outfit_category_and_index = value
        self.on_outfit_changed(value)

    def can_switch_to_outfit(self, outfit_category_and_index) -> bool:
        if outfit_category_and_index[0] == OutfitCategory.SITUATION:
            return True
        if self._current_outfit == outfit_category_and_index:
            return False
        return True

    def get_current_outfit(self):
        return self._current_outfit

    def get_part_ids_for_current_outfit(self):
        cur_outfit = self.get_current_outfit()
        return self.get_part_ids_for_outfit(cur_outfit[0], cur_outfit[1])

    def get_part_ids_for_outfit(self, outfit_category, outfit_index):
        return self._outfits.get_parts_ids_for_categry_and_index(outfit_category, outfit_index)

    def set_current_outfit(self, outfit_category_and_index) -> bool:
        if self._current_outfit == outfit_category_and_index and outfit_category_and_index[0] != OutfitCategory.SITUATION:
            return False
        self.set_previous_outfit()
        self._current_outfit = outfit_category_and_index
        logger.debug('{} {} Setting Current Outfit to: (Cat: {}, Index: {})', self.first_name, self.last_name, self._current_outfit[0], self._current_outfit[1])
        return True

    def refresh_current_outfit(self):
        self._current_outfit = self._current_outfit_category_and_index

    def set_previous_outfit(self):
        self._previous_outfit = self._current_outfit

    @property
    def autonomy_scoring_preferences(self):
        return self._autonomy_scoring_preferences

    @property
    def autonomy_use_preferences(self):
        return self._autonomy_use_preferences

    @distributor.fields.Field(op=distributor.ops.SetFacialAttributes)
    def facial_attributes(self):
        return self._base.facial_attributes

    resend_facial_attributes = facial_attributes.get_resend()

    @property
    def career_tracker(self):
        return self._career_tracker

    @distributor.fields.Field(op=distributor.ops.SetGeneticData)
    def genetic_data(self):
        return self._base.genetic_data

    resend_genetic_data = genetic_data.get_resend()

    @property
    def time_sim_was_saved(self):
        return self._time_sim_was_saved

    @time_sim_was_saved.setter
    def time_sim_was_saved(self, value):
        self._time_sim_was_saved = value

    def verify_school(self, from_age_up):
        if from_age_up or self._time_sim_was_saved is None:
            if self.is_child:
                self.create_homework(self.CHILD_HOMEWORK)
            elif self.is_teen:
                self.create_homework(self.TEEN_HOMEWORK)
        self.update_school_career()

    def update_school_career(self):
        self.ensure_age_based_career(Age.CHILD, SimInfo.SCHOOL_CAREER)
        self.ensure_age_based_career(Age.TEEN, SimInfo.HIGH_SCHOOL_CAREER)

    def ensure_age_based_career(self, age, career):
        has_career = career.guid64 in self._career_tracker.careers
        if self.age == age:
            if not has_career:
                self._career_tracker.add_career(career(self, init_track=True))
        elif has_career:
            self._career_tracker.remove_career(career.guid64, post_quit_msg=False)

    def remove_invalid_age_based_careers(self, previous_age):
        if previous_age == Age.TEEN:
            for career in tuple(self._career_tracker.careers.values()):
                while career.career_category == CareerCategory.TeenPartTime:
                    self._career_tracker.remove_career(career.guid64, post_quit_msg=False)

    def create_homework(self, homework_object):
        sim = self.get_sim_instance()
        if sim.inventory_component.has_item_with_definition(homework_object):
            return
        created_object = create_object(homework_object, init=None)
        if created_object is not None:
            created_object.update_ownership(sim)
            if sim.inventory_component.can_add(created_object):
                sim.inventory_component.player_try_add_object(created_object)
                return
            created_object.destroy(source=self, cause='Failed to add homework to sim inventory')

    def remove_homework(self, homework_object):
        sim = self.get_sim_instance()
        sim.inventory_component.try_destroy_object_by_definition(homework_object, source=sim, cause='Removing homework.')

    def get_create_op(self, *args, **kwargs):
        additional_ops = list(self.get_additional_create_ops_gen())
        return distributor.ops.SimInfoCreate(self, additional_ops=additional_ops, *args, **kwargs)

    @forward_to_components_gen
    def get_additional_create_ops_gen(self):
        pass

    def get_delete_op(self):
        return distributor.ops.SimInfoDelete()

    def get_create_after_objs(self):
        return ()

    @property
    def valid_for_distribution(self):
        return self.id is not None and self.manager is not None

    @property
    def relationship_tracker(self):
        return self._relationship_tracker

    @distributor.fields.Field(op=distributor.ops.SetAccountId)
    def account_id(self):
        if self._account is not None:
            return self._account.id

    @property
    def account(self):
        return self._account

    @property
    def account_connection(self):
        if self.account is not None:
            if self.household.remote_connected:
                return AccountConnection.DIFFERENT_LOT
            for client in self.account.clients:
                while self in client.selectable_sims:
                    return AccountConnection.SAME_LOT
        return AccountConnection.OFFLINE

    @distributor.fields.Field(op=distributor.ops.SetIsNpc)
    def is_npc(self):
        client = services.client_manager().get_client_by_household_id(self._household_id)
        return client is None

    @property
    def is_selectable(self):
        client = services.client_manager().get_client_by_household_id(self._household_id)
        if client is None:
            return False
        return self in client.selectable_sims

    @property
    def is_selected(self):
        sim = self.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if sim is not None:
            return sim.is_selected
        return False

    @is_npc.setter
    def is_npc(self, value):
        pass

    @distributor.fields.Field(op=distributor.ops.SetPersona)
    def persona(self):
        if self._account is not None:
            return self._account.persona_name
        return ''

    @property
    def is_male(self):
        return types.Gender(self._base.gender) == types.Gender.MALE

    @property
    def is_female(self):
        return types.Gender(self._base.gender) == types.Gender.FEMALE

    @property
    def is_sim(self):
        return True

    @property
    def Buffs(self):
        return self.buffs_component

    @property
    def trait_tracker(self):
        return self._trait_tracker

    @property
    def aspiration_tracker(self):
        return self._aspiration_tracker

    @property
    def whim_tracker(self):
        return self._whim_tracker

    @property
    def unlock_tracker(self):
        return self._unlock_tracker

    @property
    def personal_funds(self):
        return self._personal_funds

    @property
    def revision(self):
        return self._revision

    @personal_funds.setter
    def personal_funds(self, value):
        self._personal_funds = value

    def add_to_personal_funds(self, amount):
        if amount > 0:
            pass
        else:
            logger.error("Attempt to add non positive amount of funds to a Sim's personal_funds is not supported.", owner='mduke')

    def empty_personal_funds(self):
        ret = self._personal_funds
        self._personal_funds = 0
        return ret

    @property
    def inventory_data(self):
        return self._inventory_data

    @inventory_data.setter
    def inventory_data(self, new_data):
        self._inventory_data = new_data

    @property
    def build_buy_unlocks(self):
        return self._build_buy_unlocks

    def add_build_buy_unlock(self, unlock):
        self._build_buy_unlocks.add(unlock)

    @property
    def aspirations_blob(self):
        return self._aspirations_blob

    @property
    def is_simulating(self):
        sim_inst = self.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS_EXCEPT_UNINITIALIZED)
        if sim_inst is not None:
            return sim_inst.is_simulating
        if self.is_baby and self.is_selectable:
            return True
        return False

    def get_statistic(self, stat, add=True):
        tracker = self.get_tracker(stat)
        return tracker.get_statistic(stat, add=add)

    def skills_gen(self):
        for stat in self.commodity_tracker:
            while stat.is_skill:
                yield stat

    @caches.cached
    def all_skills(self):
        return [stat for stat in self.commodity_tracker if stat.is_skill]

    def get_sim_instance(self, *, allow_hidden_flags=0):
        if self._sim_ref:
            sim = self._sim_ref()
            if sim is not None:
                if not sim.is_hidden(allow_hidden_flags=allow_hidden_flags):
                    return sim

    def is_instanced(self, *, allow_hidden_flags=0):
        sim = self.get_sim_instance(allow_hidden_flags=allow_hidden_flags)
        return sim is not None

    def add_topic(self, *args, **kwargs):
        if not self._sim_ref or self._sim_ref() is None:
            return
        return self._sim_ref().add_topic(*args, **kwargs)

    def remove_topic(self, *args, **kwargs):
        if not self._sim_ref or self._sim_ref() is None:
            return
        return self._sim_ref().remove_topic(*args, **kwargs)

    def request_walkstyle(self, walkstyle_request, uid):
        self._walkstyle_requests.append(walkstyle_request)
        self._walkstyle_requests.sort(reverse=True)
        self._walk_style_handles[uid] = RegistryHandle(lambda : self._unrequest_walkstyle(walkstyle_request))
        if self._sim_ref and self._sim_ref() is not None:
            self._sim_ref()._update_walkstyle()

    def _unrequest_walkstyle(self, walkstyle_request):
        self._walkstyle_requests.remove(walkstyle_request)
        if self._sim_ref and self._sim_ref() is not None:
            self._sim_ref()._update_walkstyle()

    def remove_walkstyle(self, uid):
        if uid in self._walk_style_handles:
            self._walk_style_handles[uid].release()
            del self._walk_style_handles[uid]

    def set_sub_action_lockout(self, *args, **kwargs):
        if not self._sim_ref or self._sim_ref() is None:
            return
        return self._sim_ref().set_sub_action_lockout(*args, **kwargs)

    def create_sim_instance(self, position, sim_spawner_tags=None, spawn_action=None, sim_location=None, additional_fgl_search_flags=None, from_load=False):
        if self.household is None:
            logger.callstack('Creating a Sim instance with a None household. This will cause problems.\n   Sim: {}\n   Household id: {}\n   Creation Source: {}', self, self.household_id, self.creation_source, level=sims4.log.LEVEL_ERROR, owner='tingyul')
        sim_info = self

        def init(obj):
            trans = None
            orient = None
            start_routing_surface = None
            total_spawner_tags = []
            try:
                zone = services.current_zone()
                starting_position = position
                if sim_location is not None:
                    logger.info('Sim {} spawning with sim_location {}', sim_info, sim_location)
                    starting_position = sim_location.transform.translation
                    starting_orientation = sim_location.transform.orientation
                    start_routing_surface = sim_location.routing_surface
                    if sim_info.world_id != zone.open_street_id:
                        logger.warn("Sim {} spawning in zone {} but the sim's startup sim location had zone saved as {}. Setting sim location routing surface to use new zone.", sim_info, sim_info.zone_id, start_routing_surface.primary_id)
                    start_routing_surface = routing.SurfaceIdentifier(sim_info.zone_id, start_routing_surface.secondary_id, routing.SURFACETYPE_WORLD)
                else:
                    logger.info('Sim {} spawning with no sim_location'.format(sim_info))
                    starting_orientation = None
                    start_routing_surface = None
                if starting_position is not None:
                    logger.info('Sim {} spawning with starting_position {}', sim_info, starting_position)
                    fgl_search_flags = placement.FGLSearchFlagsDefault | placement.FGLSearchFlag.USE_SIM_FOOTPRINT
                    if additional_fgl_search_flags is not None:
                        fgl_search_flags = fgl_search_flags | additional_fgl_search_flags
                    additional_avoid_sim_radius = routing.get_default_agent_radius() if from_load else routing.get_sim_extra_clearance_distance()
                    (trans, orient) = placement.find_good_location(placement.FindGoodLocationContext(starting_position=starting_position, starting_orientation=starting_orientation, starting_routing_surface=start_routing_surface, additional_avoid_sim_radius=additional_avoid_sim_radius, search_flags=fgl_search_flags))
                    logger.info('Sim {} spawning FGL returned {}, {}', sim_info, trans, orient)
                else:
                    zone = services.current_zone()
                    default_tags = SimInfoSpawnerTags.SIM_SPAWNER_TAGS
                    lot_id = None
                    if not sim_spawner_tags:
                        total_spawner_tags = list(default_tags)
                        lot_id = zone.lot.lot_id
                    else:
                        total_spawner_tags = sim_spawner_tags
                        if SpawnPoint.ARRIVAL_SPAWN_POINT_TAG in total_spawner_tags or SpawnPoint.VISITOR_ARRIVAL_SPAWN_POINT_TAG in total_spawner_tags:
                            lot_id = zone.lot.lot_id
                    logger.info('Sim {} looking for spawn point relative to lot_id {} tags {}', sim_info, lot_id, total_spawner_tags)
                    spawn_point = zone.get_spawn_point(lot_id=lot_id, sim_spawner_tags=total_spawner_tags)
                    if spawn_point is not None:
                        (trans, orient) = spawn_point.next_spawn_spot()
                        start_routing_surface = spawn_point.routing_surface
                        sim_info.spawn_point_id = spawn_point.spawn_point_id
                        logger.info('Sim {} spawning from spawn point {} transform {}', sim_info, spawn_point.spawn_point_id, trans)
                    else:
                        (trans, orient) = self._find_place_on_lot_for_sim()
                        logger.info('Sim {} spawn point determined using FGL at {} {}', sim_info, trans, orient)
            except:
                logger.exception('Error in create_sim_instance/find_good_location:')
            if trans is None:
                logger.error('find_good_location Failed, Setting Sim Position to Default')
                translation = DEFAULT if position is None else position
            else:
                translation = trans
            orientation = DEFAULT if orient is None else orient
            routing_surface = DEFAULT if start_routing_surface is None else start_routing_surface
            obj.move_to(translation=translation, orientation=orientation, routing_surface=routing_surface)
            obj.sim_info = sim_info
            if not from_load or not sim_info.spawner_tags:
                sim_info.spawner_tags = total_spawner_tags

        import sims.baby
        sims.baby.on_sim_spawn(self)
        sim_inst = objects.system.create_object(self.SIM_DEFINITION, self.sim_id, init=init)
        sim_inst.opacity = 0
        sim_inst.on_start_up.append(lambda _: sim_inst.fade_in() if spawn_action is None else spawn_action)
        if sim_inst is not None:
            self._sim_ref = sim_inst.ref()
            return True
        logger.error('Failed to create sim:{}', self)
        return False

    def _find_place_on_lot_for_sim(self):
        zone = services.current_zone()
        center_pos = sims4.math.Vector3.ZERO()
        if zone.lot is not None:
            center_pos = zone.lot.center
        position = sims4.math.Vector3(center_pos.x, services.terrain_service.terrain_object().get_height_at(center_pos.x, center_pos.z), center_pos.z)
        return placement.find_good_location(placement.FindGoodLocationContext(starting_position=position, additional_avoid_sim_radius=routing.get_sim_extra_clearance_distance(), search_flags=placement.FGLSearchFlagsDefault | placement.FGLSearchFlag.USE_SIM_FOOTPRINT))

    def _teleport_sim(self, sim):
        (translation, orientation) = self._find_place_on_lot_for_sim()
        sim.move_to(translation=translation, orientation=orientation)
        sim.opacity = 1

    def _get_fit_fat(self):
        physique = [x for x in self.physique.split(',')]
        max_fat = ConsumableComponent.FAT_COMMODITY.max_value_tuning
        max_fit = ConsumableComponent.FIT_COMMODITY.max_value_tuning
        min_fat = ConsumableComponent.FAT_COMMODITY.min_value_tuning
        min_fit = ConsumableComponent.FIT_COMMODITY.min_value_tuning
        heavy = float(physique[SimInfo.BodyBlendTypes.BODYBLENDTYPE_HEAVY])
        lean = float(physique[SimInfo.BodyBlendTypes.BODYBLENDTYPE_LEAN])
        fit = float(physique[SimInfo.BodyBlendTypes.BODYBLENDTYPE_FIT])
        bony = float(physique[SimInfo.BodyBlendTypes.BODYBLENDTYPE_BONY])
        self.fat = (1 + heavy - lean)*max_fat + min_fat
        self.fit = (1 + fit - bony)*max_fit + min_fit

    def _set_fit_fat(self):
        sim = self.get_sim_instance()
        if sim is not None:
            self.fat = sim.commodity_tracker.get_value(ConsumableComponent.FAT_COMMODITY)
            self.fit = sim.commodity_tracker.get_value(ConsumableComponent.FIT_COMMODITY)
        physique = [x for x in self.physique.split(',')]
        max_fat = ConsumableComponent.FAT_COMMODITY.max_value_tuning
        max_fit = ConsumableComponent.FIT_COMMODITY.max_value_tuning
        min_fat = ConsumableComponent.FAT_COMMODITY.min_value_tuning
        min_fit = ConsumableComponent.FIT_COMMODITY.min_value_tuning
        fat_range = max_fat - min_fat
        fit_range = max_fit - min_fit
        fat_base = max_fat - fat_range/2
        fit_base = max_fit - fit_range/2
        heavy = 0.0 if self.fat <= fat_base else (self.fat - fat_base)/(max_fat - fat_base)
        lean = 0.0 if self.fat >= fat_base else (fat_base - self.fat)/(fat_base - min_fat)
        fit = 0.0 if self.fit <= fit_base else (self.fit - fit_base)/(max_fit - fit_base)
        bony = 0.0 if self.fit >= fit_base else (fit_base - self.fit)/(fit_base - min_fit)
        physique_range = 1000
        physique[SimInfo.BodyBlendTypes.BODYBLENDTYPE_HEAVY] = str(math.trunc(heavy*physique_range)/physique_range)
        physique[SimInfo.BodyBlendTypes.BODYBLENDTYPE_LEAN] = str(math.trunc(lean*physique_range)/physique_range)
        physique[SimInfo.BodyBlendTypes.BODYBLENDTYPE_FIT] = str(math.trunc(fit*physique_range)/physique_range)
        physique[SimInfo.BodyBlendTypes.BODYBLENDTYPE_BONY] = str(math.trunc(bony*physique_range)/physique_range)
        physique = ','.join([x for x in physique])
        self.physique = physique

    def _create_motives(self):
        for commodity_type in self.INITIAL_COMMODITIES:
            commodity_inst = self.commodity_tracker.add_statistic(commodity_type)
            commodity_inst.core = True
        for static_commodity_type in self.INITIAL_STATIC_COMMODITIES:
            self.static_commodity_tracker.add_statistic(static_commodity_type)
        for statistic in self.INITIAL_STATISTICS:
            tracker = self.get_tracker(statistic)
            tracker.add_statistic(statistic)

    def _init_skills(self):
        statistic_tracker = self.commodity_tracker
        for stat_type in services.statistic_manager().types.values():
            while issubclass(stat_type, statistics.skill.Skill):
                if stat_type.is_default and not statistic_tracker.has_statistic(stat_type):
                    statistic_tracker.add_statistic(stat_type)

    def _setup_fitness_commodities(self):
        self.commodity_tracker.set_value(ConsumableComponent.FAT_COMMODITY, self.fat)
        self.commodity_tracker.set_value(ConsumableComponent.FIT_COMMODITY, self.fit)
        fitness_commodity = self.commodity_tracker.get_statistic(ConsumableComponent.FIT_COMMODITY)
        if self._initial_fitness_value is None:
            self._initial_fitness_value = self.fit
        if self._initial_fitness_value > self.MAXIMUM_SAFE_FITNESS_VALUE:
            fitness_commodity.convergence_value = self.MAXIMUM_SAFE_FITNESS_VALUE
        else:
            fitness_commodity.convergence_value = self._initial_fitness_value

    def set_field_dirty(self, field):
        pass

    def is_dirty(self, field):
        return self._dirty_flags & 1 << field

    def print_dirty_flags(self):
        tmpStr = 'SimId: {0} - '.format(self.sim_id)
        for index in SimInfo.DirtyFlags:
            if self._dirty_flags & 1 << index:
                tmpStr += '1'
            else:
                tmpStr += '0'
        print(tmpStr)

    @property
    def household_id(self):
        return self._household_id

    def assign_to_household(self, household, assign_is_npc=True):
        self._household_id = household.id if household is not None else None
        if assign_is_npc:
            self.is_npc = household.is_npc_household
        sim = self.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if sim is not None:
            for inv_obj in sim.inventory_component:
                inv_obj_current_household_id = inv_obj.get_household_owner_id()
                while inv_obj_current_household_id is not None:
                    if inv_obj_current_household_id != self._household_id:
                        inv_obj.set_household_owner_id(self._household_id)
                    else:
                        logger.error('Sim: {} has inventory object: {} already set to household id: {} when assigning sim to household.', sim, inv_obj, self._household_id)

    @property
    def is_at_home(self):
        return self.household is not None and (self.household.home_zone_id != 0 and self.household.home_zone_id == self.zone_id)

    @property
    def lives_here(self):
        return self.household is not None and (self.household.home_zone_id != 0 and services.current_zone().id == self.household.home_zone_id)

    @property
    def genealogy(self):
        return self._genealogy_tracker

    def set_and_propagate_family_relation(self, relation, sim_info):
        self._genealogy_tracker.set_and_propagate_family_relation(relation, sim_info)

    def get_family_sim_ids(self, include_self=False):
        return self._genealogy_tracker.get_family_sim_ids(include_self=include_self)

    def get_relation(self, relation):
        return self._genealogy_tracker.get_relation(relation)

    def incest_prevention_test(self, sim_b):
        sim_a_fam_data = set(self.get_family_sim_ids(include_self=True))
        sim_b_fam_data = set(sim_b.sim_info.get_family_sim_ids(include_self=True))
        rel_union = sim_a_fam_data & sim_b_fam_data
        if None in rel_union:
            rel_union.remove(None)
        if rel_union:
            return False
        return True

    def save_sim(self):
        self._aspiration_tracker.update_timers()
        attributes_msg = self._save_sim_attributes()
        if attributes_msg is None:
            return False
        outfit_msg = self._outfits.save_sim_outfits()
        if outfit_msg is None:
            return False
        inventory_msg = self.inventory_data
        interactions_msg = None
        location_data = None
        sim = self.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if sim is not None:
            inventory_msg = sim.inventory_component.save_items()
            if inventory_msg is None:
                return False
            for parented_item in sim.children:
                while parented_item.can_go_in_inventory_type(InventoryType.SIM):
                    parented_item.save_object(inventory_msg.objects, ItemLocation.SIM_INVENTORY, self.id)
            self.inventory_data = inventory_msg
            interactions_msg = sim.si_state.save_interactions()
            if interactions_msg is None:
                return False
            if self._zone_id == services.current_zone_id():
                location_data = gameplay_serialization.WorldLocation()
                for sim_primitive in sim.primitives:
                    while isinstance(sim_primitive, interactions.utils.routing.FollowPath):
                        node = sim_primitive.get_next_non_portal_node()
                        if node is None:
                            pass
                        (location_data.x, location_data.y, location_data.z) = node.position
                        (location_data.rot_x, location_data.rot_y, location_data.rot_z, location_data.rot_w) = node.orientation
                        break
                transform = sim.transform
                location_data.x = transform.translation.x
                location_data.y = transform.translation.y
                location_data.z = transform.translation.z
                location_data.rot_x = transform.orientation.x
                location_data.rot_y = transform.orientation.y
                location_data.rot_z = transform.orientation.z
                location_data.rot_w = transform.orientation.w
                if sim.location.world_routing_surface is not None:
                    location_data.level = sim.location.level
                else:
                    location_data.location.level = 0
        self._save_sim_base(attributes_msg, outfit_msg, inventory_msg, interactions_msg, location_data)
        return True

    def _save_sim_base(self, attributes, outfits, inventory, interactions, location_data):
        self._set_fit_fat()
        sim_msg = services.get_persistence_service().get_sim_proto_buff(self._sim_id)
        if sim_msg is None:
            sim_msg = services.get_persistence_service().add_sim_proto_buff()
        sim_msg.Clear()
        sim_msg.sim_id = self._sim_id
        sim_msg.zone_id = self._zone_id
        sim_msg.world_id = self._world_id
        sim_msg.household_id = self._household_id
        sim_msg.first_name = self._base.first_name
        sim_msg.last_name = self._base.last_name
        if hasattr(self._base, 'first_name_key'):
            sim_msg.first_name_key = self._base.first_name_key
        if hasattr(self._base, 'last_name_key'):
            sim_msg.last_name_key = self._base.last_name_key
        sim_msg.full_name_key = self._base.full_name_key
        sim_msg.gender = types.Gender(self._base.gender)
        sim_msg.age = types.Age(self._base.age)
        sim_msg.skin_tone = self._base.skin_tone
        sim_msg.voice_pitch = self._base.voice_pitch
        sim_msg.voice_actor = self._base.voice_actor
        sim_msg.voice_effect = self._base.voice_effect
        sim_msg.physique = self._base.physique
        sim_msg.pregnancy_progress = self.pregnancy_progress
        sim_msg.flags = self._flags
        sim_msg.age_progress = self._age_progress.get_value()
        sim_msg.money = self._personal_funds
        sim_msg.fix_relationship = False
        sim_msg.attributes = attributes
        sim_msg.facial_attr = self._base.facial_attributes or bytes(0)
        sim_msg.created = services.time_service().sim_now.absolute_ticks()
        sim_msg.outfits = outfits
        sim_msg.inventory = inventory
        sim_msg.genetic_data.MergeFromString(self._base.genetic_data)
        sim_msg.household_name = self.household.name
        sim_msg.nucleus_id = self.account_id
        sim_msg.persona = self.persona
        sim_msg.primary_aspiration = self._primary_aspiration
        sim_msg.revision = self._revision
        (outfit_type, outfit_index) = self._current_outfit
        if outfit_type == OutfitCategory.BATHING:
            outfit_type = OutfitCategory.EVERYDAY
            outfit_index = 0
        outfit_category_tuning = SimOutfits.OUTFIT_CATEGORY_TUNING.get(outfit_type)
        if outfit_category_tuning.save_outfit_category is None:
            sim_msg.current_outfit_type = outfit_type
        else:
            sim_msg.current_outfit_type = outfit_category_tuning.save_outfit_category
        sim_msg.current_outfit_index = outfit_index
        sim_msg.gameplay_data.inventory_value = self.inventory_value()
        if interactions is not None:
            sim_msg.gameplay_data.interaction_state = interactions
        sim_msg.gameplay_data.additional_bonus_days = self._additional_bonus_days
        if self.spawn_point_id is not None:
            sim_msg.gameplay_data.spawn_point_id = self.spawn_point_id
        sim_msg.gameplay_data.spawn_point_option = self.spawn_point_option
        sim_msg.gameplay_data.spawner_tags.extend(self.spawner_tags)
        sim_msg.gameplay_data.build_buy_unlock_list = ResourceKeyList()
        for unlock in self.build_buy_unlocks:
            if isinstance(unlock, int):
                pass
            key_proto = sims4.resources.get_protobuff_for_key(unlock)
            sim_msg.gameplay_data.build_buy_unlock_list.resource_keys.append(key_proto)
        sim_msg.gameplay_data.serialization_option = self._serialization_option
        sim_msg.gameplay_data.creation_source = self.creation_source
        sim_msg.gameplay_data.old_household_id = self._household_id
        sim_msg.gameplay_data.whim_bucks = self._whim_bucks
        self._whim_tracker.save_whims_info_to_proto(sim_msg.gameplay_data.whim_tracker)
        self._away_action_tracker.save_away_action_info_to_proto(sim_msg.gameplay_data.away_action_tracker)
        if self.spouse_sim_id is not None:
            sim_msg.significant_other = self.spouse_sim_id
        now_time = services.time_service().sim_now
        sim_msg.gameplay_data.zone_time_stamp.time_sim_info_was_saved = now_time.absolute_ticks()
        if self.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS):
            sim_msg.gameplay_data.zone_time_stamp.time_sim_was_saved = now_time.absolute_ticks()
        elif self._time_sim_was_saved is not None:
            sim_msg.gameplay_data.zone_time_stamp.time_sim_was_saved = self._time_sim_was_saved.absolute_ticks()
        if self.household.home_zone_id != self._zone_id:
            if self.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS):
                random_minutes = PersistenceTuning.MINUTES_STAY_ON_LOT_BEFORE_GO_HOME.random_int()
                random_minutes_time_span = date_and_time.create_time_span(minutes=random_minutes)
                time_expire = now_time + random_minutes_time_span
                sim_msg.gameplay_data.zone_time_stamp.game_time_expire = time_expire.absolute_ticks()
            elif self.game_time_bring_home is not None:
                sim_msg.gameplay_data.zone_time_stamp.game_time_expire = self.game_time_bring_home
        if location_data is not None:
            sim_msg.gameplay_data.location = location_data
        current_mood = self.get_mood()
        current_mood_intensity = self.get_mood_intensity()
        sim_msg.current_mood = current_mood.guid64
        sim_msg.current_mood_intensity = current_mood_intensity
        if self._initial_fitness_value is not None:
            sim_msg.initial_fitness_value = self._initial_fitness_value
        self.update_time_alive()
        sim_msg.gameplay_data.time_alive = self._time_alive.in_ticks()
        self._dirty_flags = 0
        if SAVE_ACTIVE_HOUSEHOLD_COMMAND:
            sim_msg.sim_creation_path = serialization.SimData.SIMCREATION_PRE_MADE
            persist_fields_for_new_game(sim_msg)
        return True

    def _save_sim_attributes(self):
        attributes_save = protocols.PersistableSimInfoAttributes()
        attributes_save.pregnancy_tracker = self._pregnancy_tracker.save()
        attributes_save.adventure_tracker = self._adventure_tracker.save()
        attributes_save.royalty_tracker = self._royalty_tracker.save()
        death_save = self._death_tracker.save()
        if death_save is not None:
            attributes_save.death_tracker = self._death_tracker.save()
        attributes_save.sim_permissions = self._sim_permissions.save()
        attributes_save.sim_careers = self._career_tracker.save()
        attributes_save.relationship_tracker.relationships.extend(self._relationship_tracker.save())
        attributes_save.trait_tracker = self._trait_tracker.save()
        for (tag, obj_id) in self._autonomy_scoring_preferences.items():
            with ProtocolBufferRollback(attributes_save.object_preferences.preferences) as entry:
                entry.tag = tag
                entry.object_id = obj_id
        for (tag, obj_id) in self._autonomy_use_preferences.items():
            with ProtocolBufferRollback(attributes_save.object_ownership.owned_object) as entry:
                entry.tag = tag
                entry.object_id = obj_id
        (commodites, skill_statistics) = self.commodity_tracker.save()
        attributes_save.commodity_tracker.commodities.extend(commodites)
        regular_statistics = self.statistic_tracker.save()
        attributes_save.statistics_tracker.statistics.extend(regular_statistics)
        attributes_save.skill_tracker.skills.extend(skill_statistics)
        self._aspiration_tracker.save(attributes_save.event_data_tracker)
        attributes_save.genealogy_tracker = self._genealogy_tracker.save_genealogy()
        attributes_save.unlock_tracker = self._unlock_tracker.save_unlock()
        return attributes_save

    def load_sim_info(self, sim_proto):
        self._sim_creation_path = sim_proto.sim_creation_path
        skip_load = self._sim_creation_path != serialization.SimData.SIMCREATION_NONE
        self._sim_id = sim_proto.sim_id
        if sim_proto.gender == types.Gender.MALE or sim_proto.gender == types.Gender.FEMALE:
            self._base.gender = types.Gender(sim_proto.gender)
        self._base.age = types.Age(sim_proto.age)
        self._base.first_name = sim_proto.first_name
        self._base.last_name = sim_proto.last_name
        if hasattr(self._base, 'first_name_key'):
            self._base.first_name_key = sim_proto.first_name_key
        if hasattr(self._base, 'last_name_key'):
            self._base.last_name_key = sim_proto.last_name_key
        self._base.full_name_key = sim_proto.full_name_key
        self._zone_id = sim_proto.zone_id
        self.zone_name = sim_proto.zone_name
        self._world_id = sim_proto.world_id
        self._household_id = sim_proto.household_id
        self._serialization_option = sim_proto.gameplay_data.serialization_option
        self._base.skin_tone = sim_proto.skin_tone
        self._base.voice_pitch = sim_proto.voice_pitch
        self._base.voice_actor = sim_proto.voice_actor
        self._base.voice_effect = sim_proto.voice_effect
        self._base.physique = sim_proto.physique
        self._get_fit_fat()
        self._flags = sim_proto.flags
        self._age_progress.set_value(sim_proto.age_progress)
        self._personal_funds = sim_proto.money
        self._build_buy_unlocks = set()
        old_unlocks = set(list(sim_proto.gameplay_data.build_buy_unlocks))
        for unlock in old_unlocks:
            while isinstance(unlock, int):
                key = sims4.resources.Key(Types.OBJCATALOG, unlock, 0)
                self._build_buy_unlocks.add(key)
        if hasattr(sim_proto.gameplay_data, 'build_buy_unlock_list'):
            for key_proto in sim_proto.gameplay_data.build_buy_unlock_list.resource_keys:
                key = sims4.resources.Key(key_proto.type, key_proto.instance, key_proto.group)
                self._build_buy_unlocks.add(key)
        self._nucleus_id = sim_proto.nucleus_id
        self._primary_aspiration = sim_proto.primary_aspiration
        self._cached_inventory_value = sim_proto.gameplay_data.inventory_value
        if not skip_load:
            self._away_action_tracker.load_away_action_info_from_proto(sim_proto.gameplay_data.away_action_tracker)
        self.spawn_point_id = sim_proto.gameplay_data.spawn_point_id if sim_proto.gameplay_data.HasField('spawn_point_id') else None
        self.spawn_point_option = SpawnPointOption(sim_proto.gameplay_data.spawn_point_option) if sim_proto.gameplay_data.HasField('spawn_point_option') else SpawnPointOption.SPAWN_ANY_POINT_WITH_CONSTRAINT_TAGS
        self.spawner_tags = []
        if sim_proto.HasField('initial_fitness_value'):
            self._initial_fitness_value = sim_proto.initial_fitness_value
        if sim_proto.gameplay_data.HasField('time_alive'):
            time_alive = TimeSpan(sim_proto.gameplay_data.time_alive)
        else:
            time_alive = None
        self.load_time_alive(time_alive)
        for spawner_tag in sim_proto.gameplay_data.spawner_tags:
            self.spawner_tags.append(tag.Tag(spawner_tag))
        self._create_motives()
        self._init_skills()
        self.set_whim_bucks(sim_proto.gameplay_data.whim_bucks, SetWhimBucks.LOAD)
        self._whim_tracker.cache_whim_goal_proto(sim_proto.gameplay_data.whim_tracker, skip_load=skip_load)
        self._outfits.load_sim_outfits_from_persistence_proto(self.id, sim_proto.outfits)
        outfitPB = DistributorOps_pb2.SetSimOutfits()
        for outfits in self._outfits:
            outfit_message = outfitPB.outfits.add()
            outfit_message.outfit_id = outfits['outfit_id']
            outfit_message.sim_id = self.sim_id
            outfit_message.version = 0
            if hasattr(outfit_message, 'type'):
                outfit_message.type = outfits['type']
            outfit_message.part_ids.extend(outfits['parts'])
            outfit_message.body_types.extend(outfits['body_types'])
            outfit_message.match_hair_style = outfits['match_hair_style']
        self._base.outfits = outfitPB.SerializeToString()
        if sim_proto.HasField('current_outfit_type'):
            outfit_type = sim_proto.current_outfit_type
            outfit_index = sim_proto.current_outfit_index
            self._set_current_outfit_without_distribution((outfit_type, outfit_index))
        self._base.genetic_data = sim_proto.genetic_data.SerializeToString()
        self._base.flags = sim_proto.flags
        inventory_data = serialization.ObjectList()
        if not skip_load:
            inventory_data.MergeFrom(sim_proto.inventory)
        if sim_proto.gameplay_data.HasField('old_household_id'):
            old_household_id = sim_proto.gameplay_data.old_household_id
            if old_household_id != self._household_id:
                while True:
                    for inv_obj in inventory_data.objects:
                        while inv_obj.owner_id == old_household_id:
                            inv_obj.owner_id = self._household_id
        self._inventory_data = inventory_data
        self._revision = sim_proto.revision
        self._additional_bonus_days = sim_proto.gameplay_data.additional_bonus_days
        if sim_proto.significant_other != 0:
            self.update_spouse_sim_id(sim_proto.significant_other)
        try:
            self.buffs_component.load_in_progress = True
            if not skip_load and sim_proto.gameplay_data.zone_time_stamp.HasField('time_sim_was_saved'):
                self._time_sim_was_saved = DateAndTime(sim_proto.gameplay_data.zone_time_stamp.time_sim_was_saved)
            if sim_proto.gameplay_data.zone_time_stamp.game_time_expire != 0:
                self.game_time_bring_home = sim_proto.gameplay_data.zone_time_stamp.game_time_expire
            sim_attribute_data = sim_proto.attributes
            while sim_attribute_data:
                self.commodity_tracker.load(sim_attribute_data.commodity_tracker.commodities, skip_load=skip_load)
                for commodity in list(self.commodity_tracker):
                    while not commodity.is_skill:
                        commodity.set_to_auto_satisfy_value()
                self.statistic_tracker.load(sim_attribute_data.statistics_tracker.statistics)
                self.commodity_tracker.load(sim_attribute_data.skill_tracker.skills)
                skills_to_check_for_unlocks = [commodity for commodity in self.commodity_tracker.get_all_commodities() if commodity.is_skill]
                self._check_skills_for_unlock(skills_to_check_for_unlocks, sim_attribute_data.skill_tracker.skills)
                self.init_child_skills()
                self._aspirations_blob = protocols.PersistableEventDataTracker()
                self._aspirations_blob.MergeFrom(sim_attribute_data.event_data_tracker)
                self._relationship_tracker.load(sim_attribute_data.relationship_tracker.relationships)
                self._pregnancy_tracker.load(sim_attribute_data.pregnancy_tracker)
                self._death_tracker.load(sim_attribute_data.death_tracker)
                self._adventure_tracker.load(sim_attribute_data.adventure_tracker)
                self._sim_permissions.load(sim_attribute_data.sim_permissions)
                self._trait_tracker.load(sim_attribute_data.trait_tracker)
                self._career_tracker.load(sim_attribute_data.sim_careers, skip_load=skip_load)
                for entry in sim_attribute_data.object_preferences.preferences:
                    self._autonomy_scoring_preferences[entry.tag] = entry.object_id
                for entry in sim_attribute_data.object_ownership.owned_object:
                    self._autonomy_use_preferences[entry.tag] = entry.object_id
                self._genealogy_tracker.load_genealogy(sim_attribute_data.genealogy_tracker)
                while not skip_load:
                    self._royalty_tracker.load(sim_attribute_data.royalty_tracker)
                    self._unlock_tracker.load_unlock(sim_attribute_data.unlock_tracker)
        except:
            logger.exception('Failed to load attributes for sim {}.', self._base.first_name)
        finally:
            self.buffs_component.load_in_progress = False
        self._setup_fitness_commodities()
        if sim_proto.facial_attr:
            self._base.facial_attributes = sim_proto.facial_attr
        self._aspiration_tracker.load(self._aspirations_blob)
        self.creation_source = sim_proto.gameplay_data.creation_source
        if not skip_load:
            current_zone = services.current_zone()
            if (current_zone.id == self._zone_id or current_zone.open_street_id == self._world_id) and sim_proto.gameplay_data.HasField('location'):
                world_coord = sims4.math.Transform()
                location = sim_proto.gameplay_data.location
                world_coord.translation = sims4.math.Vector3(location.x, location.y, location.z)
                world_coord.orientation = sims4.math.Quaternion(location.rot_x, location.rot_y, location.rot_z, location.rot_w)
                routing_surface = routing.SurfaceIdentifier(self._zone_id, location.level, routing.SURFACETYPE_WORLD)
                self.startup_sim_location = sims4.math.Location(world_coord, routing_surface)
        self._si_state = gameplay_serialization.SuperInteractionSaveState()
        if sim_proto.gameplay_data.HasField('interaction_state'):
            self._has_loaded_si_state = True
            self._si_state.MergeFrom(sim_proto.gameplay_data.interaction_state)
        services.sim_info_manager().add_sim_info_if_not_in_manager(self)
        self._post_load()

    def _check_skills_for_unlock(self, skills, commodity_loading_data):
        open_set = set(skills)
        closed_set = set()
        while open_set:
            current_skill = open_set.pop()
            closed_set.add(current_skill)
            if not current_skill.reached_max_level:
                continue
            for skill_to_unlock in current_skill.skill_unlocks_on_max:
                while skill_to_unlock not in closed_set:
                    self.commodity_tracker.add_statistic(skill_to_unlock, force_add=True)
                    skill_data_object = [sdo for sdo in commodity_loading_data if sdo.name_hash == skill_to_unlock.guid64]
                    self.commodity_tracker.load(skill_data_object)
                    open_set.add(skill_to_unlock)

    def load_from_resource(self, resource_key):
        if not self._base.load_from_resource(resource_key):
            return
        outfit_data = DistributorOps_pb2.SetSimOutfits()
        outfit_data.MergeFromString(self._base.outfits)
        self._outfits.load_sim_outfits_from_cas_proto(outfit_data)
        self.resend_physical_attributes()

    def _post_load(self):
        self.refresh_age_settings()
        self.publish_all_commodities()
        self.aspiration_tracker.post_load()

    def refresh_age_settings(self):
        age_service = services.get_age_service()
        self._auto_aging_enabled = age_service.is_aging_enabled_for_sim_info(self)
        self._age_speed_setting = age_service.aging_speed
        self.update_age_callbacks()

    def on_all_households_and_sim_infos_loaded(self):
        self._relationship_tracker.add_neighbor_bit_if_necessary()
        self._career_tracker.start_retirement()

    def on_sim_added_to_skewer(self):
        for stat_inst in self.commodity_tracker:
            while stat_inst.is_skill:
                stat_value = stat_inst.get_value()
                stat_inst.refresh_level_up_callback()
                self._publish_commodity_update(type(stat_inst), stat_value, stat_value)

    def publish_all_commodities(self):
        if not self.is_npc:
            for stat_inst in self.commodity_tracker:
                stat_value = stat_inst.get_value()
                self._publish_commodity_update(type(stat_inst), stat_value, stat_value)

    def _publish_commodity_update(self, stat_type, old_value, new_value):
        if stat_type.is_skill and not self.is_npc:
            msg = stat_type.create_skill_update_msg(self.id, new_value)
            if msg is not None:
                add_object_message(self, MSG_SIM_SKILL_UPDATE, msg, False)
                stat_instance = self.get_statistic(stat_type.stat_type, add=False)
                if stat_instance and stat_instance.should_send_update:
                    change_rate = stat_instance.get_change_rate()
                    op = distributor.ops.SkillProgressUpdate(stat_type.guid64, change_rate, new_value)
                    distributor.ops.record(self, op)

    def _publish_statistic_update(self, stat_type, old_value, new_value):
        if not self.is_npc:
            services.get_event_manager().process_event(test_events.TestEvent.StatValueUpdate, sim_info=self, statistic=stat_type)

    def populate_localization_token(self, token):
        token.type = LocalizedStringToken.SIM
        token.first_name = self.first_name
        token.last_name = self.last_name
        token.full_name_key = self.full_name_key
        token.is_female = self.is_female

    def update_spouse_sim_id(self, spouse_sim_id):
        self._relationship_tracker.spouse_sim_id = spouse_sim_id

    def get_significant_other_sim_info(self):
        spouse_sim_info = self.get_spouse_sim_info()
        if spouse_sim_info is not None:
            return spouse_sim_info
        for rel in self._relationship_tracker:
            while rel.has_bit(Relationship.SIGNIFICANT_OTHER_RELATIONSHIP_BIT):
                return rel.find_target_sim_info()

    @property
    def spouse_sim_id(self):
        return self._relationship_tracker.spouse_sim_id

    def get_spouse_sim_info(self):
        signficant_other_id = self.spouse_sim_id
        if signficant_other_id:
            sim_info_manager = services.sim_info_manager()
            if sim_info_manager is not None:
                significant_other = sim_info_manager.get(signficant_other_id)
                if significant_other is not None:
                    return significant_other

    def get_gender_preference(self, gender):
        return self.get_statistic(GlobalGenderPreferenceTuning.GENDER_PREFERENCE[gender])

    def get_gender_preferences_gen(self):
        for (gender, gender_preference_statistic) in GlobalGenderPreferenceTuning.GENDER_PREFERENCE.items():
            yield (gender, self.get_statistic(gender_preference_statistic))

    def set_default_data(self):
        if self._sim_creation_path == serialization.SimData.SIMCREATION_NONE:
            return
        self.set_default_relationships(reciprocal=True)
        if self._sim_creation_path == serialization.SimData.SIMCREATION_INIT:
            self.creation_source = 'CAS: initial'
        elif self._sim_creation_path == serialization.SimData.SIMCREATION_REENTRY_ADDSIM:
            self.creation_source = 'CAS: re-entry'
        elif self._sim_creation_path == serialization.SimData.SIMCREATION_PRE_MADE:
            self.creation_source = 'pre-made'
        if self._sim_creation_path == serialization.SimData.SIMCREATION_GALLERY:
            self.creation_source = 'gallery'
            for commodity in list(self.commodity_tracker):
                if commodity.is_skill:
                    pass
                if not commodity.core:
                    pass
                while not commodity.set_to_auto_satisfy_value():
                    commodity.set_value(commodity.get_initial_value())
        self._sim_creation_path = serialization.SimData.SIMCREATION_NONE

    def set_default_relationships(self, reciprocal=False, update_romance=True):
        sim_id = self.id
        relationship_tracker = self.relationship_tracker

        def add_known_traits(sim_info, family_member):
            trait_tracker = family_member.trait_tracker
            personality_traits = trait_tracker.personality_traits
            num_traits = len(personality_traits)
            for house_member_trait in personality_traits:
                sim_info.relationship_tracker.add_known_trait(house_member_trait, family_member.id, num_traits=num_traits, notify_client=False)

        father_list = []
        father_sim_id = self._genealogy_tracker.get_relation(FamilyRelationshipIndex.FATHER)
        father_sim_info = services.sim_info_manager().get(father_sim_id)
        if father_sim_info is not None:
            father_list = [father_sim_info]
        for house_member in itertools.chain(self.household.sim_info_gen(), father_list):
            if house_member is self:
                pass
            house_member_id = house_member.id
            track = relationship_tracker.get_relationship_track(house_member_id, add=False)
            if track is not None:
                if reciprocal:
                    pass
                else:
                    return
            family_member = house_member.add_family_link(self)
            relationship_tracker.set_default_tracks(house_member, update_romance=update_romance, family_member=family_member)
            add_known_traits(self, house_member)
            relationship_tracker.send_relationship_info(house_member_id)
            while reciprocal:
                self.add_family_link(house_member)
                house_member.relationship_tracker.set_default_tracks(self, update_romance=update_romance, family_member=family_member)
                add_known_traits(house_member, self)
                house_member.relationship_tracker.send_relationship_info(sim_id)

    def add_family_link(self, target_sim_info):
        bit = self.genealogy.get_family_relationship_bit(target_sim_info.id)
        if bit is None:
            return False
        if target_sim_info.relationship_tracker.has_bit(self.id, bit):
            return True
        target_sim_info.relationship_tracker.add_relationship_bit(self.id, bit)
        return True

    def add_parent_relations(self, parent_a, parent_b):
        parent_a_relation = FamilyRelationshipIndex.MOTHER if parent_a.is_female else FamilyRelationshipIndex.FATHER
        self.set_and_propagate_family_relation(parent_a_relation, parent_a)
        if parent_b is not None and parent_a is not parent_b:
            parent_b_relation = FamilyRelationshipIndex.MOTHER if parent_a_relation == FamilyRelationshipIndex.FATHER else FamilyRelationshipIndex.FATHER
            self.set_and_propagate_family_relation(parent_b_relation, parent_b)

    def debug_apply_away_action(self, away_action):
        self._away_action_tracker.create_and_apply_away_action(away_action)

    def debug_apply_default_away_action(self):
        self._away_action_tracker.reset_to_default_away_action()

    def get_default_away_action(self, on_travel_away=False):
        is_instance = self.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS) and not on_travel_away
        highest_advertising_value = None
        highest_advertising_away_action = None
        for (commodity, away_action) in SimInfo.DEFAULT_AWAY_ACTION.items():
            if is_instance and not away_action.available_when_instanced:
                pass
            commodity_instance = self.get_statistic(commodity, add=False)
            if commodity_instance is None:
                pass
            advertising_value = commodity_instance.autonomous_desire
            while highest_advertising_value is None or highest_advertising_value < advertising_value:
                highest_advertising_value = advertising_value
                highest_advertising_away_action = away_action
        return highest_advertising_away_action

    def resend_physical_attributes(self):
        self.resend_skin_tone()
        self.resend_facial_attributes()
        self.resend_physique()
        self.resend_outfits()
        self.resend_voice_pitch()
        self.resend_voice_actor()
        self.resend_voice_effect()

    def flush_to_client_on_teardown(self):
        self.buffs_component.on_sim_removed(immediate=True)

    def log_sim_info(self, logger_func, additional_msg=None):
        sim_info_strings = []
        if additional_msg is not None:
            sim_info_strings.append(additional_msg)
        sim_info_strings.append('Sim info for {}'.format(self))
        sim = self.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if sim is not None:
            sim_info_strings.append('Simulation state: {}'.format(sim._simulation_state))
            sim_info_strings.append('Interaction queue:')
            for interaction in sim.queue:
                sim_info_strings.append('    {}'.format(interaction))
        else:
            sim_info_strings.append('Simulation state: UNINSTANTIATED')
        sim_info_strings.append('Traits:')
        for trait in self.trait_tracker:
            sim_info_strings.append('    {}'.format(trait))
        sim_info_strings.append('Buffs:')
        for buff in self.Buffs:
            sim_info_strings.append('    {}'.format(buff))
        sim_info_strings.append('Death Type = {}'.format(self.death_type))
        logger_func('\n'.join(sim_info_strings))

def save_active_household_command_start():
    global SAVE_ACTIVE_HOUSEHOLD_COMMAND
    SAVE_ACTIVE_HOUSEHOLD_COMMAND = True

def save_active_household_command_stop():
    global SAVE_ACTIVE_HOUSEHOLD_COMMAND
    SAVE_ACTIVE_HOUSEHOLD_COMMAND = False

class AccountConnection(enum.Int, export=False):
    __qualname__ = 'AccountConnection'
    SAME_LOT = 1
    DIFFERENT_LOT = 2
    OFFLINE = 3

