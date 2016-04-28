import functools
import itertools
import random
from animation.arb_accumulator import with_skippable_animation_time
from animation.posture_manifest import Hand
from autonomy import autonomy_modes
from broadcasters.environment_score.environment_score_mixin import EnvironmentScoreMixin
from buffs.tunable import TunableBuffReference
from caches import cached_generator
from carry import CarryPostureStaticTuning, get_carried_objects_gen
from date_and_time import DateAndTime
from distributor.ops import SetRelativeLotLocation
from distributor.system import Distributor
from element_utils import build_critical_section_with_finally, build_element, build_critical_section
from event_testing import test_events
from event_testing.test_variants import SocialContextTest
from interactions import priority, constraints
from interactions.aop import AffordanceObjectPair
from interactions.base.interaction import FITNESS_LIABILITY, FitnessLiability, Interaction, STAND_SLOT_LIABILITY, StandSlotReservationLiability
from interactions.base.super_interaction import SuperInteraction
from interactions.context import InteractionContext, QueueInsertStrategy, InteractionSource
from interactions.interaction_finisher import FinishingType
from interactions.priority import Priority
from interactions.si_state import SIState
from interactions.utils.animation import AnimationOverrides, flush_all_animations, AsmAutoExitInfo, ArbElement
from interactions.utils.animation_reference import TunableAnimationReference
from interactions.utils.routing import WalkStyleRequest, FollowPath
from objects import HiddenReasonFlag
from objects.base_interactions import JoinInteraction, AskToJoinInteraction
from objects.components.consumable_component import ConsumableComponent
from objects.game_object import GameObject
from objects.helpers.user_footprint_helper import UserFootprintHelper
from objects.mixins import LockoutMixin
from objects.object_enums import ResetReason
from objects.part import Part
from postures import ALL_POSTURES, PostureTrack, create_posture, posture_graph
from postures.posture_specs import PostureSpecVariable, get_origin_spec
from postures.posture_state import PostureState
from postures.transition_sequence import DerailReason
from services.reset_and_delete_service import ResetRecord
from sims.aging import AGING_LIABILITY, AgingLiability
from sims.master_controller import WorkRequest
from sims.self_interactions import AnimationInteraction
from sims.sim_outfits import ForcedOutfitChanges, OutfitChangeReason
from sims4.callback_utils import CallableList, consume_exceptions, RemovableCallableList
from sims4.geometry import test_point_in_polygon
from sims4.localization import TunableLocalizedString
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import Tunable, TunableRange, TunableList, TunableReference, TunableMapping, TunableThreshold
from sims4.utils import classproperty, flexmethod
from singletons import DEFAULT
from zone import Zone
import animation.arb
import autonomy.autonomy_request
import buffs.buff
import build_buy
import caches
import cas.cas
import clock
import date_and_time
import distributor.fields
import distributor.ops
import element_utils
import elements
import enum
import event_testing.resolver
import gsi_handlers.sim_timeline_handlers
import interactions.interaction_queue
import objects.components.topic_component
import objects.components.types
import placement
import reset
import routing
import services
import sims.multi_motive_buff_tracker
import sims.ui_manager
import sims4.log
import statistics.commodity
TELEMETRY_QUICKTIME_INTERACTION = 'QUIC'
writer_2 = sims4.telemetry.TelemetryWriter(TELEMETRY_QUICKTIME_INTERACTION)
try:
    import _zone
except ImportError:

    class _zone:
        __qualname__ = '_zone'

        @staticmethod
        def add_sim(_):
            pass

        @staticmethod
        def remove_sim(_):
            pass

logger = sims4.log.Logger('Sim')

def __reload__(old_module_vars):
    global GLOBAL_AUTONOMY
    GLOBAL_AUTONOMY = old_module_vars['GLOBAL_AUTONOMY']

class SimulationState(enum.Int, export=False):
    __qualname__ = 'SimulationState'
    INITIALIZING = 1
    RESETTING = 2
    SIMULATING = 3
    BEING_DESTROYED = 4

class LOSAndSocialConstraintTuning:
    __qualname__ = 'LOSAndSocialConstraintTuning'
    constraint_expansion_amount = Tunable(float, 5, description="\n    The amount, in meters, to expand the Sim's current constraint by when calculating fallback social constraints.\n    This number should be equal to the tuned radius for the standard social group constraint minus a nominal\n    amount, such as 1 meter to prevent extremely small intersections from being considered valid.")
    num_sides_for_circle_expansion_of_point_constraint = Tunable(int, 8, description='\n    The number of sides to use when creating a circle for expanding point constraints for the fallback social constraint.')
    incompatible_target_sim_maximum_time_to_wait = Tunable(float, 20, description='\n    The number of sim minutes to wait for the target Sim of a social interaction if they are in an\n    incompatible state (such as sleeping) before giving up and canceling the social.')
    incompatible_target_sim_route_nearby_frequency = Tunable(float, 5, description='\n    The number of sim minutes to delay in between routing nearby the target Sim of a social\n    interaction if they are in an incompatible state (such as sleeping).')
    maximum_intended_distance_to_route_nearby = Tunable(float, 20, description="\n    The maximum distance in meters from the target Sim's current position to their\n    intended position where a Sim will stop the target Sim instead of routing to their\n    intended position. Note: this only applies to Sims who are trying to socialize\n    with a target Sim at higher-priority than the interaction that Sim is running.")
    minimum_delay_between_route_nearby_attempts = Tunable(float, 5, description="\n    description = The minimum delay, in Sim minutes, between route nearby attempts when a\n    social is in the head of a Sim's queue. NOTE: This is performance-critical so please\n    don't change this unless you know what you are doing.")

class Sim(GameObject, LockoutMixin, EnvironmentScoreMixin, reset.ResettableObjectMixin):
    __qualname__ = 'Sim'
    INSTANCE_TUNABLES = {'max_interactions': TunableRange(int, 8, minimum=0, maximum=10, description='Max interactions in queue, including running interaction. If this value is greater than 10, the interaction queue .swf must be updated.'), 'initial_buff': TunableBuffReference(description='A buff that will be permanently added to the Sim on creation. Used to affect the neutral state of a Sim.'), '_quadtree_radius': Tunable(float, 0.123, description="Size of the Sim's quadtree footprint used for spatial queries"), '_phone_affordances': TunableList(TunableReference(services.affordance_manager(), description='An affordance that can be run as a solo interaction.'), description="A list of affordances generated when the player wants to use the Sim's cell phone."), '_relation_panel_affordances': TunableList(description='\n                A list of affordances that are shown when the player clicks on\n                a Sim in the relationship panel. These affordances must be able\n                to run as solo interactions, meaning they cannot have a target\n                object or Sim.\n\n                When the selected interaction runs, the Subject type \n                "PickedItemId" will be set to the clicked Sim\'s id. For example,\n                a relationship change loot op with Subject as Actor and\n                Target Subject as PickedItemId will change the relationship\n                between the Active Sim and the Sim selected in the Relationship\n                Panel.\n                ', tunable=TunableReference(description='\n                An affordance shown when the player clicks on a relation in the relationship panel.', manager=services.affordance_manager()))}
    REMOVE_INSTANCE_TUNABLES = ('_should_search_forwarded_sim_aop', '_should_search_forwarded_child_aop')
    _pathplan_context = None
    _reaction_triggers = {}
    FACIAL_OVERLAY_ANIMATION = TunableAnimationReference(description='Facial Overlay Animation for Mood.')
    FOREIGN_ZONE_BUFF = buffs.buff.Buff.TunableReference(description='\n        This buff is applied to any sim that is not in their home zone.  It is\n        used by autonomy for NPCs to score the GoHome interaction.\n        ')
    BUFF_CLOTHING_REASON = TunableLocalizedString(description='\n        The localized string used to give reason why clothing buff was added.\n        Does not support any tokens.\n        ')
    MULTI_MOTIVE_BUFF_MOTIVES = TunableMapping(description='\n        Buffs, Motives and the threshold needed for that motive to count towards\n        the multi motive buff\n        ', key_type=buffs.buff.Buff.TunableReference(description='\n            Buff that is added when all the motives are above their threshold\n            '), value_type=TunableMapping(description='\n            Motives and the threshold needed for that motive to count towards\n            the multi motive buff\n            ', key_type=statistics.commodity.Commodity.TunableReference(description='\n                    Motive needed above threshold to get the buff\n                    '), value_type=TunableThreshold(description='\n                    Threshold at which this motive counts for the buff\n                    ')))

    def __init__(self, *args, **kwargs):
        GameObject.__init__(self, *args, **kwargs)
        LockoutMixin.__init__(self)
        self.remove_component(objects.components.types.FOOTPRINT_COMPONENT.instance_attr)
        self.add_component(objects.components.topic_component.TopicComponent(self))
        self.add_component(objects.components.inventory.SimInventoryComponent(self))
        self.queue = None
        self._is_removed = False
        self._scheduled_elements = set()
        self._starting_up = False
        self._persistence_group = objects.persistence_groups.PersistenceGroups.SIM
        self._simulation_state = SimulationState.INITIALIZING
        self._route_fail_disable_count = 0
        self.waiting_dialog_response = None
        self._posture_state = None
        self.target_posture = None
        self._si_state = SIState(self)
        self._obj_manager = None
        self._pathplan_context = routing.PathPlanContext()
        self._pathplan_context.footprint_key = self.definition.get_footprint(0)
        self._pathplan_context.agent_id = self.id
        self._pathplan_context.agent_radius = routing.get_default_agent_radius()
        self._pathplan_context.set_key_mask(routing.FOOTPRINT_KEY_ON_LOT | routing.FOOTPRINT_KEY_OFF_LOT)
        self._lot_routing_restriction_ref_count = 0
        goal_finder_result_strategy = placement.FGLResultStrategyDefault()
        goal_finder_result_strategy.max_results = 20
        goal_finder_result_strategy.done_on_max_results = True
        self._goal_finder_search_strategy = placement.FGLSearchStrategyRouting(routing_context=self._pathplan_context)
        self._goal_finder_search_strategy.use_sim_footprint = True
        self._goal_finder = placement.FGLSearch(self._goal_finder_search_strategy, goal_finder_result_strategy)
        self.on_social_group_changed = CallableList()
        self._social_groups = []
        self.on_social_geometry_changed = CallableList()
        self.on_posture_event = CallableList()
        self.on_follow_path = CallableList()
        self.on_plan_path = CallableList()
        self.on_intended_location_changed = CallableList()
        self.on_intended_location_changed.append(self.refresh_los_constraint)
        self.on_intended_location_changed.append(self._update_social_geometry_on_location_changed)
        self.on_intended_location_changed.append(lambda *_, **__: self.two_person_social_transforms.clear())
        self.on_intended_location_changed.append(self._update_intended_position_on_active_lot)
        self._ui_manager = sims.ui_manager.UIManager(self)
        self._posture_compatibility_filter = []
        self._sim_info = None
        self._mixers_locked_out = {}
        self._mixer_front_page_cooldown = {}
        self.current_path = None
        self._start_animation_interaction()
        self._preload_outfit_list = []
        self.needs_fitness_update = False
        self.asm_auto_exit = AsmAutoExitInfo()
        self.on_slot = None
        self.last_affordance = None
        self._sleeping = False
        self._buff_handles = []
        self.interaction_logging = False
        self.transition_path_logging = False
        self._multi_motive_buff_trackers = []
        self._los_constraint = None
        self._social_group_constraint = None
        self.on_start_up = RemovableCallableList()
        self.object_ids_to_ignore = set()
        self._posture_target_refs = []
        self.next_passive_balloon_unlock_time = DateAndTime(0)
        self.two_person_social_transforms = {}
        self._intended_position_on_active_lot = False
        self.active_transition = None
        self._allow_route_instantly_when_hitting_marks = False
        self.current_object_set_as_head = None
        self._handedness = None

    def __repr__(self):
        if self.sim_info is None:
            return "sim 'Destroyed Sim - Unknown Name' {0:#x}".format(self.id)
        return "<sim '{0} {1} {2}' {3:#x}>".format(self.first_name, self.last_name, self.persona, self.id)

    def __str__(self):
        if self.sim_info is None:
            return 'Destroyed Sim - Unknown Name ID: {0:#x}'.format(self.id)
        return self.full_name

    @classproperty
    def reaction_triggers(cls):
        return cls._reaction_triggers

    @classproperty
    def is_sim(cls):
        return True

    @property
    def is_npc(self):
        return self.sim_info.is_npc

    @property
    def _anim_overrides_internal(self):
        return AnimationOverrides(overrides=super()._anim_overrides_internal, params={'sex': self.gender.name.lower(), 'age': self.age.animation_age_param, 'mood': self.get_mood_animation_param_name()})

    @property
    def name(self):
        return (self.first_name, self.last_name, self.persona)

    @name.setter
    def name(self, value):
        self.sim_info.first_name(value[0])
        self.sim_info.last_name(value[1])
        self.sim_info.persona(value[2])

    @property
    def voice_pitch(self):
        return self.sim_info.voice_pitch

    @voice_pitch.setter
    def voice_pitch(self, value):
        self.sim_info.voice_pitch = value

    @property
    def voice_actor(self):
        return self.sim_info.voice_actor

    @voice_actor.setter
    def voice_actor(self, value):
        self.sim_info.voice_actor = value

    @property
    def pregnancy_progress(self):
        return self.sim_info.pregnancy_progress

    @pregnancy_progress.setter
    def pregnancy_progress(self, value):
        self.sim_info.pregnancy_progress = value

    @distributor.fields.Field(op=distributor.ops.SetThumbnail)
    def thumbnail(self):
        return self.sim_info.thumbnail

    @thumbnail.setter
    def thumbnail(self, value):
        self.sim_info.thumbnail = value

    @property
    def gender(self):
        return self.sim_info.gender

    @property
    def age(self):
        return self.sim_info.age

    @property
    def sim_info(self):
        return self._sim_info

    @property
    def spouse_sim_id(self):
        return self._sim_info.spouse_sim_id

    def get_spouse_sim_info(self):
        return self._sim_info.get_spouse_sim_info()

    def get_significant_other_sim_info(self):
        return self._sim_info.get_significant_other_sim_info()

    @sim_info.setter
    def sim_info(self, value):
        self._sim_info = value
        if self._sim_info is not None:
            self._pathplan_context.agent_id = self._sim_info.sim_id

    @property
    def sim_id(self):
        return self._sim_info.sim_id

    @property
    def first_name(self):
        return self.sim_info.first_name

    @first_name.setter
    def first_name(self, value):
        self.sim_info.first_name = value

    @property
    def last_name(self):
        return self.sim_info.last_name

    @last_name.setter
    def last_name(self, value):
        self.sim_info.last_name = value

    @property
    def full_name(self):
        return self.sim_info.full_name

    @property
    def persona(self):
        return self.sim_info.persona

    @property
    def zone_id(self):
        if self.sim_info is not None:
            return self.sim_info.zone_id

    @property
    def world_id(self):
        return self.sim_info.world_id

    @property
    def is_selectable(self):
        return self.sim_info.is_selectable

    @property
    def is_selected(self):
        client = services.client_manager().get_client_by_household(self.household)
        if client is not None:
            return self is client.active_sim
        return False

    @property
    def transition_controller(self):
        return self.queue.transition_controller

    @world_id.setter
    def world_id(self, value):
        self.sim_info.world_id = value

    def _create_routing_context(self):
        pass

    def get_or_create_routing_context(self):
        return self._pathplan_context

    @property
    def routing_context(self):
        return self._pathplan_context

    @property
    def object_radius(self):
        return self._pathplan_context.agent_radius

    @object_radius.setter
    def object_radius(self, value):
        self._pathplan_context.agent_radius = value

    @property
    def goal_finder_search_strategy(self):
        return self._goal_finder_search_strategy

    @property
    def goal_finder(self):
        return self._goal_finder

    @property
    def account_id(self):
        return self.sim_info.account_id

    @property
    def account(self):
        return self.sim_info.account

    @property
    def has_client(self):
        return self.client is not None

    @property
    def client(self):
        if self.account is not None:
            return self.account.get_client(self.zone_id)

    @property
    def household(self):
        return self.sim_info.household

    @property
    def household_id(self):
        return self.sim_info.household.id

    @property
    def si_state(self):
        return self._si_state

    @property
    def is_valid_posture_graph_object(self):
        return False

    @property
    def icon_info(self):
        return self.sim_info.icon_info

    def get_icon_info_data(self):
        return self.sim_info.get_icon_info_data()

    @property
    def manager_id(self):
        return self.sim_info.manager.id

    @property
    def should_route_fail(self):
        return self._route_fail_disable_count == 0

    @property
    def should_route_instantly(self):
        zone = services.current_zone()
        if Zone.force_route_instantly:
            return True
        return zone.are_sims_hitting_their_marks and self._allow_route_instantly_when_hitting_marks

    def set_allow_route_instantly_when_hitting_marks(self, allow):
        self._allow_route_instantly_when_hitting_marks = allow

    @property
    def account_connection(self):
        return self.sim_info.account_connection

    @property
    def family_funds(self):
        return self.household.funds

    @property
    def is_simulating(self):
        return self._simulation_state == SimulationState.SIMULATING

    @property
    def is_being_destroyed(self):
        return self._simulation_state == SimulationState.RESETTING and self.reset_reason() == ResetReason.BEING_DESTROYED

    @property
    def handedness(self):
        if self._handedness is None:
            self._handedness = Hand.RIGHT if self.sim_id % 4 else Hand.LEFT
        return self._handedness

    @handedness.setter
    def handedness(self, value):
        self._handedness = value

    @property
    def on_home_lot(self):
        current_zone = services.current_zone()
        if self.household.home_zone_id == current_zone.id:
            active_lot = current_zone.lot
            if active_lot.is_position_on_lot(self.position):
                return True
        return False

    def set_location_without_distribution(self, value):
        if self._location.transform.translation != sims4.math.Vector3.ZERO() and value._parent_ref is None and value.transform.translation == sims4.math.Vector3.ZERO():
            logger.callstack('Attempting to move an unparented object {} to position Zero'.format(self), level=sims4.log.LEVEL_ERROR)
        super().set_location_without_distribution(value)

    def _update_intended_position_on_active_lot(self, *_, update_ui=False, **__):
        arrival_spawn_point = services.current_zone().active_lot_arrival_spawn_point
        if services.active_lot().is_position_on_lot(self.intended_position) or arrival_spawn_point is not None and test_point_in_polygon(self.intended_position, arrival_spawn_point.get_footprint_polygon()):
            new_intended_position_on_active_lot = True
        else:
            new_intended_position_on_active_lot = False
        on_off_lot_update = self._intended_position_on_active_lot != new_intended_position_on_active_lot
        if on_off_lot_update or update_ui:
            self._intended_position_on_active_lot = new_intended_position_on_active_lot
            msg = SetRelativeLotLocation(self.id, self.intended_position_on_active_lot, self.sim_info.is_at_home)
            distributor = Distributor.instance()
            distributor.add_op(self, msg)
            services.get_event_manager().process_event(test_events.TestEvent.SimActiveLotStatusChanged, sim_info=self.sim_info, on_active_lot=new_intended_position_on_active_lot)

    def preload_inappropriate_streetwear_change(self, final_si, preload_outfit_set):
        if self.sim_info._current_outfit[0] in ForcedOutfitChanges.INAPPROPRIATE_STREETWEAR:
            if self.transition_controller is None:
                return
            outfit_category_and_index = self.sim_info.sim_outfits.get_outfit_for_clothing_change(final_si, OutfitChangeReason.DefaultOutfit)
            self.transition_controller.inappropriate_streetwear_change = outfit_category_and_index
            preload_outfit_set.add(outfit_category_and_index)

    @distributor.fields.Field(op=distributor.ops.SetSimSleepState)
    def sleeping(self):
        return self._sleeping

    @sleeping.setter
    def sleeping(self, value):
        self._sleeping = value

    @distributor.fields.Field(op=distributor.ops.PreloadSimOutfit)
    def preload_outfit_list(self):
        return self._preload_outfit_list

    @preload_outfit_list.setter
    def preload_outfit_list(self, value):
        self._preload_outfit_list = value

    def save_object(self, object_list, item_location, container_id):
        pass

    def get_create_after_objs(self):
        super_objs = super().get_create_after_objs()
        return (self.sim_info,) + super_objs

    def set_build_buy_lockout_state(self, lockout_state, lockout_timer=None):
        raise AssertionError('Trying to illegally set a Sim as locked out: {}'.format(self))

    def without_route_failure(self, sequence=None):

        def disable_route_fail(_):
            pass

        def enable_route_fail(_):
            pass

        return build_critical_section_with_finally(disable_route_fail, sequence, enable_route_fail)

    @property
    def rig(self):
        return self._rig

    def inc_lot_routing_restriction_ref_count(self):
        if not self.is_npc or self.sim_info.lives_here:
            return
        if services.current_zone().lot.is_position_on_lot(self.position):
            return
        if self._pathplan_context.get_key_mask() & routing.FOOTPRINT_KEY_ON_LOT:
            self._pathplan_context.set_key_mask(self._pathplan_context.get_key_mask() & ~routing.FOOTPRINT_KEY_ON_LOT)

    def dec_lot_routing_restriction_ref_count(self):
        if not self.is_npc or self.sim_info.lives_here:
            return
        if self._lot_routing_restriction_ref_count > 0:
            if self._lot_routing_restriction_ref_count == 0:
                self._pathplan_context.set_key_mask(self._pathplan_context.get_key_mask() | routing.FOOTPRINT_KEY_ON_LOT)

    def clear_lot_routing_restrictions_ref_count(self):
        self._lot_routing_restriction_ref_count = 0
        self._pathplan_context.set_key_mask(self._pathplan_context.get_key_mask() | routing.FOOTPRINT_KEY_ON_LOT)

    def execute_adjustment_interaction(self, affordance, constraint, int_priority, group_id=None, **kwargs):
        aop = AffordanceObjectPair(affordance, None, affordance, None, constraint_to_satisfy=constraint, route_fail_on_transition_fail=False, is_adjustment_interaction=True, **kwargs)
        context = InteractionContext(self, InteractionContext.SOURCE_SOCIAL_ADJUSTMENT, int_priority, insert_strategy=QueueInsertStrategy.NEXT, group_id=group_id, must_run_next=True, cancel_if_incompatible_in_queue=True)
        return aop.test_and_execute(context)

    @property
    def ui_manager(self):
        return self._ui_manager

    def get_tracker(self, stat):
        from relationships.relationship_track import RelationshipTrack
        if isinstance(stat, RelationshipTrack):
            return stat.tracker
        return self.sim_info.get_tracker(stat)

    def _update_social_geometry_on_location_changed(self, *args, **kwargs):
        social_group = self.get_main_group()
        if social_group is not None:
            social_group.refresh_social_geometry(sim=self)

    def notify_social_group_changed(self, group):
        if self in group:
            if group not in self._social_groups:
                self._social_groups.append(group)
        elif group in self._social_groups:
            self._social_groups.remove(group)
        self.on_social_group_changed(self, group)

    def filter_supported_postures(self, supported_postures):
        filtered_postures = supported_postures
        if filtered_postures is ALL_POSTURES:
            return ALL_POSTURES
        for filter_func in self._posture_compatibility_filter:
            filtered_postures = filter_func(filtered_postures)
        return filtered_postures

    def may_reserve(self, *args, **kwargs):
        return False

    def reserve(self, *args, **kwargs):
        logger.error('Attempting to reserve Sim {}. Violation of human rights.', self, owner='tastle')

    def schedule_element(self, timeline, element):
        resettable_element = reset.ResettableElement(element, self)
        resettable_element.on_scheduled(timeline)
        timeline.schedule(resettable_element)
        return resettable_element

    def register_reset_element(self, element):
        self._scheduled_elements.add(element)

    def unregister_reset_element(self, element):
        self._scheduled_elements.discard(element)

    def on_reset_element_hard_stop(self):
        self.reset(reset_reason=ResetReason.RESET_EXPECTED)

    def on_reset_notification(self, reset_reason):
        super().on_reset_notification(reset_reason)
        self._simulation_state = SimulationState.RESETTING
        self.queue.lock()

    def on_reset_get_elements_to_hard_stop(self, reset_reason):
        elements_to_reset = super().on_reset_get_elements_to_hard_stop(reset_reason)
        scheduled_elements = list(self._scheduled_elements)
        self._scheduled_elements.clear()
        for element in scheduled_elements:
            elements_to_reset.append(element)
            element.unregister()
        return elements_to_reset

    def on_reset_get_interdependent_reset_records(self, reset_reason, reset_records):
        super().on_reset_get_interdependent_reset_records(reset_reason, reset_records)
        master_controller = services.get_master_controller()
        master_controller.add_interdependent_reset_records(self, reset_records)
        for other_sim in master_controller.added_sims():
            while other_sim is not self:
                if other_sim.has_sim_in_any_queued_interactions_required_sim_cache(self):
                    reset_records.append(ResetRecord(other_sim, ResetReason.RESET_EXPECTED, self, 'In required sims of queued interaction.'))
        for social_group in self.get_groups_for_sim_gen():
            for other_sim in social_group:
                while other_sim is not self:
                    reset_records.append(ResetRecord(other_sim, ResetReason.RESET_EXPECTED, self, 'In social group'))
        for interaction in self.get_all_running_and_queued_interactions():
            while interaction.prepared:
                while True:
                    for other_sim in interaction.required_sims():
                        while other_sim is not self:
                            reset_records.append(ResetRecord(other_sim, ResetReason.RESET_EXPECTED, self, 'required sim in {}'.format(interaction)))
        if self.posture_state is not None:
            for aspect in self.posture_state.aspects:
                target = aspect.target
                while target is not None:
                    if target.is_part:
                        target = target.part_owner
                    reset_records.append(ResetRecord(target, ResetReason.RESET_EXPECTED, self, 'Posture state aspect:{} target:{}'.format(aspect, target)))

    def on_reset_restart(self):
        self._start_animation_interaction()
        return False

    def on_state_changed(self, state, old_value, new_value):
        if not self.is_simulating:
            return
        affordances = self.sim_info.PHYSIQUE_CHANGE_AFFORDANCES
        reaction_affordance = None
        if old_value != new_value and (state == ConsumableComponent.FAT_STATE or state == ConsumableComponent.FIT_STATE):
            self.needs_fitness_update = True
            if state == ConsumableComponent.FAT_STATE:
                reaction_affordance = affordances.FAT_CHANGE_NEUTRAL_AFFORDANCE
                fat_commodity = ConsumableComponent.FAT_COMMODITY
                old_fat = self.sim_info.fat
                new_fat = self.commodity_tracker.get_value(fat_commodity)
                midrange_fat = (fat_commodity.max_value + fat_commodity.min_value)/2
                self.sim_info.fat = new_fat
                if new_fat > midrange_fat:
                    if old_fat < new_fat:
                        if new_fat == fat_commodity.max_value:
                            reaction_affordance = affordances.FAT_CHANGE_MAX_NEGATIVE_AFFORDANCE
                        else:
                            reaction_affordance = affordances.FAT_CHANGE_NEGATIVE_AFFORDANCE
                            if old_fat > new_fat:
                                reaction_affordance = affordances.FAT_CHANGE_POSITIVE_AFFORDANCE
                                reaction_affordance = affordances.FAT_CHANGE_MAX_POSITIVE_AFFORDANCE
                    elif old_fat > new_fat:
                        reaction_affordance = affordances.FAT_CHANGE_POSITIVE_AFFORDANCE
                        reaction_affordance = affordances.FAT_CHANGE_MAX_POSITIVE_AFFORDANCE
                else:
                    reaction_affordance = affordances.FAT_CHANGE_MAX_POSITIVE_AFFORDANCE
            else:
                reaction_affordance = affordances.FIT_CHANGE_NEUTRAL_AFFORDANCE
                old_fit = self.sim_info.fit
                new_fit = self.commodity_tracker.get_value(ConsumableComponent.FIT_COMMODITY)
                self.sim_info.fit = new_fit
                if old_fit < new_fit:
                    reaction_affordance = affordances.FIT_CHANGE_POSITIVE_AFFORDANCE
                else:
                    reaction_affordance = affordances.FIT_CHANGE_NEGATIVE_AFFORDANCE
            if reaction_affordance is not None:
                context = InteractionContext(self, InteractionContext.SOURCE_SCRIPT, Priority.Low, client=None, pick=None)
                result = self.push_super_affordance(reaction_affordance, None, context)
                if result:
                    result.interaction.add_liability(FITNESS_LIABILITY, FitnessLiability(self))
                    return
            self.sim_info.update_fitness_state()

    def _on_navmesh_updated(self):
        self.validate_current_location_or_fgl()
        if self.queue.transition_controller is not None and self.current_path is not None and self.current_path.nodes.needs_replan():
            if any(sim_primitive.is_traversing_portal() for sim_primitive in self.primitives if isinstance(sim_primitive, FollowPath)):
                self.reset(ResetReason.RESET_EXPECTED, None, 'Navmesh update while traversing a portal.')
            else:
                self.queue.transition_controller.derail(DerailReason.NAVMESH_UPDATED, self)
        self.two_person_social_transforms.clear()

    def validate_location(self, location):
        routing_location = routing.Location(location.transform.translation, location.transform.orientation, location.routing_surface)
        contexts = set()
        for interaction in itertools.chain((self.queue.running,), self.si_state):
            while not interaction is None:
                if interaction.target is None:
                    pass
                contexts.add(interaction.target.raycast_context())
                while interaction.target.parent is not None:
                    contexts.add(interaction.target.parent.raycast_context())
        if not contexts:
            contexts.add(self.routing_context)
        for context in contexts:
            while placement.validate_sim_location(routing_location, routing.get_default_agent_radius(), context):
                return True
        return False

    def validate_current_location_or_fgl(self, from_reset=False):
        zone = services.current_zone()
        if not zone.is_in_build_buy and not from_reset:
            return
        if from_reset and zone.is_in_build_buy:
            services.get_event_manager().process_event(test_events.TestEvent.OnBuildBuyReset, sim_info=self.sim_info)
        if self.current_path is not None:
            if from_reset:
                return
            if any(sim_primitive.is_traversing_invalid_portal() for sim_primitive in self.primitives if isinstance(sim_primitive, FollowPath)):
                self.reset(ResetReason.RESET_EXPECTED, self, 'Traversing invalid portal.')
            return
        (location, on_surface) = self.get_location_on_nearest_surface_below()
        if self.validate_location(location):
            if not on_surface:
                if not from_reset:
                    self.reset(ResetReason.RESET_EXPECTED, self, 'Failed to validate location.')
                self.location = location
            return
        ignored_object_ids = {self.sim_id}
        ignored_object_ids.update(child.id for child in self.children_recursive_gen())
        parent_object = self.parent_object
        while parent_object is not None:
            ignored_object_ids.add(parent_object.id)
            parent_object = self.parent_object
        (trans, orient) = placement.find_good_location(placement.FindGoodLocationContext(starting_location=location, ignored_object_ids=ignored_object_ids, additional_avoid_sim_radius=routing.get_sim_extra_clearance_distance(), search_flags=placement.FGLSearchFlagsDefault | placement.FGLSearchFlag.USE_SIM_FOOTPRINT | placement.FGLSearchFlag.STAY_IN_CURRENT_BLOCK, routing_context=self.routing_context))
        if trans is None or orient is None:
            if not from_reset:
                self.reset(ResetReason.RESET_EXPECTED, self, 'Failed to find location.')
                return
            self.fgl_reset_to_landing_strip()
            return
        if not from_reset:
            self.reset(ResetReason.RESET_EXPECTED, self, 'Failed to find location.')
        new_transform = sims4.math.Transform(trans, orient)
        location.transform = new_transform
        self.location = location

    def fgl_reset_to_landing_strip(self):
        self.reset(ResetReason.RESET_EXPECTED, self, 'Reset to landing strip.')
        zone = services.current_zone()
        spawn_point = zone.active_lot_arrival_spawn_point
        if spawn_point is None:
            self.move_to_landing_strip()
            return
        (spawn_trans, _) = spawn_point.next_spawn_spot()
        location = routing.Location(spawn_trans, routing_surface=spawn_point.routing_surface)
        success = False
        if self._pathplan_context.get_key_mask() & routing.FOOTPRINT_KEY_ON_LOT:
            self._pathplan_context.set_key_mask(self._pathplan_context.get_key_mask() & ~routing.FOOTPRINT_KEY_ON_LOT)
            should_have_permission = True
        else:
            should_have_permission = False
        try:
            (trans, orient) = placement.find_good_location(placement.FindGoodLocationContext(starting_location=location, ignored_object_ids={self.sim_id}, additional_avoid_sim_radius=routing.get_default_agent_radius(), routing_context=self.routing_context, search_flags=placement.FGLSearchFlagsDefault | placement.FGLSearchFlag.USE_SIM_FOOTPRINT))
            while trans is not None and orient is not None:
                new_location = self.location
                new_location.transform.translation = trans
                new_location.transform.orientation = orient
                if spawn_point is not None:
                    new_location.routing_surface = spawn_point.routing_surface
                self.location = new_location
                success = True
        finally:
            if should_have_permission:
                self._pathplan_context.set_key_mask(self._pathplan_context.get_key_mask() | routing.FOOTPRINT_KEY_ON_LOT)
        return success

    def _highest_valid_level(self):
        position = sims4.math.Vector3(self.position.x, self.position.y, self.position.z)
        for i in range(self.routing_surface.secondary_id, 0, -1):
            while build_buy.has_floor_at_location(self.zone_id, position, i):
                return i
        return 0

    def get_location_on_nearest_surface_below(self):
        if self.posture_state.valid and (not self.posture.unconstrained or self.active_transition is not None and not self.active_transition.source.unconstrained):
            return (self.location, True)
        location = self.location
        level = self._highest_valid_level()
        if level != location.routing_surface.secondary_id:
            location.routing_surface = routing.SurfaceIdentifier(location.routing_surface.primary_id, level, location.routing_surface.type)
        on_surface = False
        snapped_y = services.terrain_service.terrain_object().get_routing_surface_height_at(location.transform.translation.x, location.transform.translation.z, location.routing_surface)
        LEVEL_SNAP_TOLERANCE = 0.001
        if level == self.routing_surface.secondary_id and sims4.math.almost_equal(snapped_y, location.transform.translation.y, epsilon=LEVEL_SNAP_TOLERANCE):
            on_surface = True
        location.transform.translation = sims4.math.Vector3(location.transform.translation.x, snapped_y, location.transform.translation.z)
        return (location, on_surface)

    def move_to_landing_strip(self):
        zone = services.current_zone()
        spawn_point = zone.get_spawn_point()
        if spawn_point is not None:
            (trans, _) = spawn_point.next_spawn_spot()
            new_location = self.location
            new_location.transform.translation = trans
            new_location.routing_surface = spawn_point.routing_surface
            self.location = new_location
            self.fade_in()
            return
        logger.warn('No landing strip exists in zone {}', zone)

    def _start_animation_interaction(self):
        animation_aop = AffordanceObjectPair(AnimationInteraction, None, AnimationInteraction, None, hide_unrelated_held_props=False)
        facial_overlay_interaction_context = InteractionContext(self, InteractionContext.SOURCE_SCRIPT, priority.Priority.High)
        self._update_facial_overlay_interaction = animation_aop.interaction_factory(facial_overlay_interaction_context).interaction
        animation_interaction_context = InteractionContext(self, InteractionContext.SOURCE_SCRIPT, priority.Priority.High)
        animation_aop = AffordanceObjectPair(AnimationInteraction, None, AnimationInteraction, None)
        self.animation_interaction = animation_aop.interaction_factory(animation_interaction_context).interaction

    def _stop_animation_interaction(self):
        if self._update_facial_overlay_interaction is not None:
            self._update_facial_overlay_interaction.cancel(FinishingType.RESET, 'Sim is being reset.')
            self._update_facial_overlay_interaction.on_removed_from_queue()
            self._update_facial_overlay_interaction = None
        if self.animation_interaction is not None:
            self.animation_interaction.cancel(FinishingType.RESET, 'Sim is being reset.')
            self.animation_interaction.on_removed_from_queue()
            self.animation_interaction = None

    def on_reset_internal_state(self, reset_reason):
        being_destroyed = reset_reason == ResetReason.BEING_DESTROYED
        try:
            if not being_destroyed:
                self.set_last_user_directed_action_time()
            services.get_master_controller().on_reset_sim(self, reset_reason)
            self.hide(HiddenReasonFlag.NOT_INITIALIZED)
            self.queue.on_reset()
            self.si_state.on_reset()
            if self.posture_state is not None:
                self.posture_state.on_reset(ResetReason.RESET_EXPECTED)
            if not being_destroyed:
                self.sim_info.refresh_current_outfit()
            self._posture_target_refs.clear()
            self._stop_environment_score()
            if self._update_facial_overlay in self.Buffs.on_mood_changed:
                self.Buffs.on_mood_changed.remove(self._update_facial_overlay)
            self._stop_animation_interaction()
            self.ui_manager.remove_all_interactions()
            self.on_sim_reset(being_destroyed)
            self.clear_all_autonomy_skip_sis()
            if being_destroyed:
                self._remove_multi_motive_buff_trackers()
            self.asm_auto_exit.clear()
            self.last_affordance = None
            if not being_destroyed and not self._is_removed:
                try:
                    self.validate_current_location_or_fgl(from_reset=True)
                    self.refresh_los_constraint()
                except Exception:
                    logger.exception('Exception thrown while finding good location for Sim on reset:')
            services.get_event_manager().process_event(test_events.TestEvent.OnSimReset, sim_info=self.sim_info)
            self.two_person_social_transforms.clear()
        except:
            logger.exception('TODO: Exception thrown during Sim reset, possibly we should be kicking the Sim out of the game.')
            raise
        finally:
            super().on_reset_internal_state(reset_reason)

    def _reset_reference_arb(self):
        self._reference_arb = None

    def _create_motives(self):
        if self.initial_buff.buff_type is not None:
            self.add_buff(self.initial_buff.buff_type, self.initial_buff.buff_reason)

    def running_interactions_gen(self, *interactions):
        if self.si_state is not None:
            for si in self.si_state.sis_actor_gen():
                for interaction in interactions:
                    interaction_type = interaction.get_interaction_type()
                    if issubclass(si.get_interaction_type(), interaction_type):
                        yield si
                    else:
                        linked_interaction_type = si.get_linked_interaction_type()
                        while linked_interaction_type is not None:
                            if issubclass(linked_interaction_type, interaction_type):
                                yield si

    def get_all_running_and_queued_interactions(self):
        interactions = [si for si in self.si_state.sis_actor_gen()]
        for si in self.queue:
            interactions.append(si)
        return interactions

    def get_running_and_queued_interactions_by_tag(self, tags):
        interaction_set = set()
        for si in self.si_state.sis_actor_gen():
            while tags & si.affordance.interaction_category_tags:
                interaction_set.add(si)
        for si in self.queue:
            while tags & si.affordance.interaction_category_tags:
                interaction_set.add(si)
        return interaction_set

    def has_sim_in_any_queued_interactions_required_sim_cache(self, sim_in_question):
        return any(interaction.has_sim_in_required_sim_cache(sim_in_question) for interaction in self.queue)

    def get_running_interactions_by_tags(self, tags):
        interaction_set = set()
        for si in self.si_state.sis_actor_gen():
            while tags & si.affordance.interaction_category_tags:
                interaction_set.add(si)
        return interaction_set

    def is_running_interaction(self, interaction, target):
        for interaction in self.running_interactions_gen(interaction):
            if interaction.is_finishing:
                pass
            if target is interaction.target:
                return True
            potential_targets = interaction.get_potential_mixer_targets()
            while potential_targets and target in potential_targets:
                return True
        return False

    def are_running_equivalent_interaction(self, sim, *interactions):
        sis_a = list(self.running_interactions_gen(*interactions))
        sis_b = list(sim.running_interactions_gen(*interactions))
        for si_a in sis_a:
            for si_b in sis_b:
                while si_a.target is si_b.target:
                    return True
        return False

    def _provided_interactions_gen(self, context, **kwargs):
        _generated_affordance = set()
        for interaction in self.si_state:
            if interaction.is_finishing:
                pass
            for affordance in interaction.affordance.provided_affordances:
                if affordance in _generated_affordance:
                    pass
                if context.sim.is_running_interaction(affordance, self):
                    pass
                if self.are_running_equivalent_interaction(context.sim, affordance):
                    pass
                aop = AffordanceObjectPair(affordance, self, affordance, None, depended_on_si=interaction, **kwargs)
                while aop.test(context):
                    _generated_affordance.add(affordance)
                    yield aop
        if context.sim is not None:
            for (_, _, carried_object) in get_carried_objects_gen(context.sim):
                for affordance in carried_object.get_provided_affordances_gen():
                    aop = AffordanceObjectPair(affordance, self, affordance, None, **kwargs)
                    while aop.test(context):
                        yield aop

    def _potential_joinable_interactions_gen(self, context, **kwargs):

        def get_target(interaction, join_participant):
            join_target = interaction.get_participant(join_participant)
            if join_target and isinstance(join_target, Part):
                join_target = join_target.part_owner
            return join_target

        def get_join_affordance(default, join_info, joining_sim, target):
            if join_info.join_affordance.is_affordance:
                join_affordance = join_info.join_affordance.value
                if join_affordance is None:
                    join_affordance = default
                if target is not None:
                    for interaction in joining_sim.si_state:
                        while interaction.get_interaction_type() is join_affordance:
                            interaction_join_target = get_target(interaction, join_info.join_target)
                            if interaction_join_target is target:
                                return (None, target)
                return (join_affordance, target)
            if context.source == InteractionSource.AUTONOMY:
                return (None, target)
            commodity_search = join_info.join_affordance.value
            for interaction in joining_sim.si_state:
                while commodity_search.commodity in interaction.commodity_flags:
                    return (None, target)
            join_context = InteractionContext(joining_sim, InteractionContext.SOURCE_AUTONOMY, Priority.High, client=None, pick=None, always_check_in_use=True)
            constraint = constraints.Circle(target.position, commodity_search.radius, target.routing_surface)
            autonomy_request = autonomy.autonomy_request.AutonomyRequest(joining_sim, autonomy_modes.FullAutonomy, static_commodity_list=(commodity_search.commodity,), context=join_context, constraint=constraint, limited_autonomy_allowed=True, consider_scores_of_zero=True, allow_forwarding=False, autonomy_mode_label_override='Joinable')
            best_action = services.autonomy_service().find_best_action(autonomy_request)
            if best_action:
                return (best_action, best_action.target)
            return (None, target)

        def get_join_aops_gen(interaction, join_sim, joining_sim, join_factory):
            interaction_type = interaction.get_interaction_type()
            join_target_ref = join_sim.ref()
            for joinable_info in interaction.joinable:
                if join_sim is self and not joinable_info.join_available:
                    pass
                if join_sim is context.sim and not joinable_info.invite_available:
                    pass
                join_target = get_target(interaction, joinable_info.join_target)
                if join_target is None and interaction.sim is not self:
                    pass
                (joinable_interaction, join_target) = get_join_affordance(interaction_type, joinable_info, joining_sim, join_target)
                if joinable_interaction is None:
                    pass
                join_interaction = join_factory(joinable_interaction.affordance, joining_sim, interaction, joinable_info)
                for aop in join_interaction.potential_interactions(join_target, context, join_target_ref=join_target_ref, **kwargs):
                    result = aop.test(context)
                    while result or result.tooltip:
                        yield aop

        def create_join_si(affordance, joining_sim, join_interaction, joinable_info):
            return JoinInteraction.generate(affordance, join_interaction, joinable_info)

        def create_invite_to_join_si(affordance, joining_sim, join_interaction, joinable_info):
            return AskToJoinInteraction.generate(affordance, joining_sim, join_interaction, joinable_info)

        for interaction in self.si_state.sis_actor_gen():
            while interaction.joinable and not interaction.is_finishing:
                while True:
                    for aop in get_join_aops_gen(interaction, self, context.sim, create_join_si):
                        yield aop
        if context.sim is not None:
            for interaction in context.sim.si_state.sis_actor_gen():
                while interaction.joinable and not interaction.is_finishing:
                    while True:
                        for aop in get_join_aops_gen(interaction, context.sim, self, create_invite_to_join_si):
                            yield aop

    def _potential_role_state_affordances_gen(self, context, **kwargs):

        def _can_show_affordance(shift_held, affordance):
            if shift_held:
                if affordance.cheat:
                    return True
                if affordance.debug and __debug__:
                    return True
            elif not affordance.debug and not affordance.cheat:
                return True
            return False

        shift_held = False
        if context is not None:
            shift_held = context.shift_held
        if self.active_roles() is not None:
            for active_role in self.active_roles():
                for affordance in active_role.role_affordances:
                    while _can_show_affordance(shift_held, affordance):
                        yield affordance

    @cached_generator
    def potential_interactions(self, context, get_interaction_parameters=None, **kwargs):
        if context.sim is not self:
            for aop in self._potential_joinable_interactions_gen(context, **kwargs):
                yield aop
        else:
            for si in self.si_state.sis_actor_gen():
                for affordance in si.all_affordances_gen():
                    for aop in affordance.potential_interactions(si.target, si.affordance, si, **kwargs):
                        while aop.affordance.allow_forward:
                            yield aop
        for affordance in self.super_affordances(context):
            if context.sim.is_running_interaction(affordance, self):
                pass
            if context.sim is not None and self.are_running_equivalent_interaction(context.sim, affordance):
                pass
            if get_interaction_parameters is not None:
                interaction_parameters = get_interaction_parameters(affordance, kwargs)
            else:
                interaction_parameters = kwargs
            for aop in affordance.potential_interactions(self, context, **interaction_parameters):
                yield aop
        if context.sim is not self:
            for aop in self._provided_interactions_gen(context, **kwargs):
                yield aop

    def potential_phone_interactions(self, context, **kwargs):
        for affordance in self._phone_affordances:
            for aop in affordance.potential_interactions(self, context, **kwargs):
                yield aop

    def potential_relation_panel_interactions(self, context, **kwargs):
        for affordance in self._relation_panel_affordances:
            for aop in affordance.potential_interactions(self, context, **kwargs):
                yield aop

    def locked_from_obj_by_privacy(self, obj):
        for privacy in services.privacy_service().privacy_instances:
            if self in privacy.allowed_sims:
                pass
            if self not in privacy.disallowed_sims and privacy.evaluate_sim(self):
                pass
            while privacy.intersects_with_object(obj):
                return True
        return False

    @flexmethod
    def super_affordances(cls, inst, context=None):
        inst_or_cls = inst if inst is not None else cls
        for affordance in super(GameObject, inst_or_cls).super_affordances(context):
            yield affordance
        if inst is not None:
            for affordance in inst._potential_role_state_affordances_gen(context):
                yield affordance

    @property
    def commodity_flags(self):
        dynamic_commodity_flags = set()
        return super().commodity_flags | dynamic_commodity_flags

    @staticmethod
    def _get_mixer_key(target, affordance, sim_specific):
        if sim_specific and target is not None and target.is_sim:
            return (affordance, target.id)
        return affordance

    def set_sub_action_lockout(self, mixer_interaction, target=None, lock_other_affordance=False, initial_lockout=False):
        now = services.time_service().sim_now
        if initial_lockout:
            lockout_time = mixer_interaction.lock_out_time_initial.random_float()
            sim_specific = False
        else:
            lockout_time = mixer_interaction.lock_out_time.interval.random_float()
            sim_specific = mixer_interaction.lock_out_time.target_based_lock_out
        lockout_time_span = clock.interval_in_sim_minutes(lockout_time)
        lock_out_time = now + lockout_time_span
        mixer_lockout_key = self._get_mixer_key(mixer_interaction.target, mixer_interaction.affordance, sim_specific)
        self._mixers_locked_out[mixer_lockout_key] = lock_out_time
        if not initial_lockout and lock_other_affordance and mixer_interaction.lock_out_affordances is not None:
            while True:
                for affordance in mixer_interaction.lock_out_affordances:
                    sim_specific = affordance.lock_out_time.target_based_lock_out if affordance.lock_out_time is not None else False
                    mixer_lockout_key = self._get_mixer_key(mixer_interaction.target, affordance, sim_specific)
                    self._mixers_locked_out[mixer_lockout_key] = lock_out_time

    def update_last_used_mixer(self, mixer_interaction):
        if mixer_interaction.lock_out_time is not None:
            self.set_sub_action_lockout(mixer_interaction, lock_other_affordance=True)
        if mixer_interaction.front_page_cooldown is not None:
            cooldown_time = mixer_interaction.front_page_cooldown.interval.random_float()
            now = services.time_service().sim_now
            cooldown_time_span = clock.interval_in_sim_minutes(cooldown_time)
            cooldown_finish_time = now + cooldown_time_span
            affordance = mixer_interaction.affordance
            cur_penalty = self.get_front_page_penalty(affordance)
            penalty = mixer_interaction.front_page_cooldown.penalty + cur_penalty
            self._mixer_front_page_cooldown[affordance] = (cooldown_finish_time, penalty)

    def get_front_page_penalty(self, affordance):
        if affordance in self._mixer_front_page_cooldown:
            (cooldown_finish_time, penalty) = self._mixer_front_page_cooldown[affordance]
            now = services.time_service().sim_now
            if now >= cooldown_finish_time:
                del self._mixer_front_page_cooldown[affordance]
            else:
                return penalty
        return 0

    def is_sub_action_locked_out(self, affordance, target=None):
        if affordance is None:
            return False
        targeted_lockout_key = self._get_mixer_key(target, affordance, True)
        global_lockout_key = self._get_mixer_key(target, affordance, False)
        targeted_unlock_time = self._mixers_locked_out.get(targeted_lockout_key, None)
        global_unlock_time = self._mixers_locked_out.get(global_lockout_key, None)
        if targeted_unlock_time is None and global_unlock_time is None:
            return False
        now = services.time_service().sim_now
        locked_out = False
        if targeted_unlock_time is not None:
            if now >= targeted_unlock_time:
                del self._mixers_locked_out[targeted_lockout_key]
            else:
                locked_out = True
        if global_unlock_time is not None:
            if now >= global_unlock_time:
                del self._mixers_locked_out[global_lockout_key]
            else:
                locked_out = True
        return locked_out

    def create_default_si(self):
        context = InteractionContext(self, InteractionContext.SOURCE_SCRIPT, priority.Priority.Low)
        result = posture_graph.SIM_DEFAULT_AOP.interaction_factory(context)
        if not result:
            logger.error('Error creating default si: {}', result.reason)
        return result.interaction

    def create_default_posture(self, track=PostureTrack.BODY):
        if PostureTrack.is_body(track):
            return create_posture(posture_graph.SIM_DEFAULT_POSTURE_TYPE, self, None)
        if PostureTrack.is_carry(track):
            return create_posture(CarryPostureStaticTuning.POSTURE_CARRY_NOTHING, self, None, track)

    def pre_add(self, manager):
        super().pre_add(manager)
        self.queue = interactions.interaction_queue.InteractionQueue(self)
        self._obj_manager = manager
        self.hide(HiddenReasonFlag.NOT_INITIALIZED)

    @property
    def persistence_group(self):
        return self._persistence_group

    @persistence_group.setter
    def persistence_group(self, value):
        logger.callstack('Trying to override the persistence group of sim: {}.', self, owner='msantander')

    def on_add(self):
        super().on_add()
        zone_id = sims4.zone_utils.get_zone_id()
        _zone.add_sim(self.sim_id, zone_id)
        self._update_quadtree_location()
        with consume_exceptions('SimInfo', 'Error during motive creation'):
            self._create_motives()
        with consume_exceptions('SimInfo', 'Error during buff addition'):
            while zone_id != self.household.home_zone_id:
                self.add_buff(self.FOREIGN_ZONE_BUFF)
        with consume_exceptions('SimInfo', 'Error clearing death type'):
            self.sim_info.death_tracker.clear_death_type()
        with consume_exceptions('SimInfo', 'Error during inventory load'):
            self.inventory_component.load_items(self.sim_info.inventory_data)
        with consume_exceptions('SimInfo', 'Error during aspiration initialization'):
            self.aspiration_tracker.load(self.sim_info.aspirations_blob)
        with consume_exceptions('SimInfo', 'Error during pregnancy initialization'):
            self.sim_info.pregnancy_tracker.enable_pregnancy()
        with consume_exceptions('SimInfo', 'Error during spawn condition trigger'):
            self.manager.trigger_sim_spawn_condition(self.sim_id)
        services.get_master_controller().add_sim(self)

    def _update_face_and_posture_gen(self, timeline):
        origin_posture_spec = get_origin_spec(posture_graph.SIM_DEFAULT_POSTURE_TYPE)
        self._posture_state = PostureState(self, None, origin_posture_spec, {PostureSpecVariable.HAND: (Hand.LEFT,)})
        yield self.posture_state.kickstart_gen(timeline)
        self.Buffs.on_mood_changed.append(self._update_facial_overlay)
        self._update_facial_overlay()

    def _update_multi_motive_buff_trackers(self):
        for multi_motive_buff_tracker in self._multi_motive_buff_trackers:
            multi_motive_buff_tracker.setup_callbacks()

    def _remove_multi_motive_buff_trackers(self):
        for multi_motive_buff_tracker in self._multi_motive_buff_trackers:
            multi_motive_buff_tracker.cleanup_callbacks()
        self._multi_motive_buff_trackers.clear()

    def add_callbacks(self):
        with consume_exceptions('SimInfo', 'Error during routing initialization'):
            self.register_on_location_changed(self._update_quadtree_location)
            self.register_on_location_changed(self._check_violations)
            self.on_plan_path.append(self._on_update_goals)
        with consume_exceptions('SimInfo', 'Error during navmesh initialization'):
            zone = services.get_zone(self.zone_id)
            zone.navmesh_change_callbacks.append(self._on_navmesh_updated)
            zone.wall_contour_update_callbacks.append(self._on_navmesh_updated)
            zone.foundation_and_level_height_update_callbacks.append(self.validate_current_location_or_fgl)
        with consume_exceptions('SimInfo', 'Error during outfit initialization'):
            self.sim_info.on_outfit_changed.append(self.on_outfit_changed)

    def remove_callbacks(self):
        zone = services.current_zone()
        if self._on_update_goals in self.on_plan_path:
            self.on_plan_path.remove(self._on_update_goals)
        if self._on_location_changed_callbacks is not None and self._check_violations in self._on_location_changed_callbacks:
            self.unregister_on_location_changed(self._check_violations)
        if self._on_location_changed_callbacks is not None and self._update_quadtree_location in self._on_location_changed_callbacks:
            self.unregister_on_location_changed(self._update_quadtree_location)
        if self._on_navmesh_updated in zone.navmesh_change_callbacks:
            zone.navmesh_change_callbacks.remove(self._on_navmesh_updated)
        if self._on_navmesh_updated in zone.wall_contour_update_callbacks:
            zone.wall_contour_update_callbacks.remove(self._on_navmesh_updated)
        if self.validate_current_location_or_fgl in zone.foundation_and_level_height_update_callbacks:
            zone.foundation_and_level_height_update_callbacks.remove(self.validate_current_location_or_fgl)
        if self.on_outfit_changed in self.sim_info.on_outfit_changed:
            self.sim_info.on_outfit_changed.remove(self.on_outfit_changed)

    def _startup_sim_gen(self, timeline):
        if self._starting_up:
            logger.error('Attempting to run _startup_sim while it is already running on another thread.')
            return
        self._starting_up = True
        try:
            yield self._update_face_and_posture_gen(timeline)
            self.queue.unlock()
            self.show(HiddenReasonFlag.NOT_INITIALIZED)
            if self._simulation_state == SimulationState.INITIALIZING:
                self.sim_info.verify_school(from_age_up=False)
                for commodity in tuple(self.commodity_tracker):
                    while not commodity.is_skill:
                        commodity.fixup_on_sim_instantiated()
                owning_household_of_active_lot = services.owning_household_of_active_lot()
                if owning_household_of_active_lot is not None:
                    for target_sim_info in owning_household_of_active_lot:
                        self.relationship_tracker.add_relationship_appropriateness_buffs(target_sim_info.id)
                self.autonomy_component.start_autonomy_alarm()
                services.get_zone_situation_manager().on_sim_creation(self)
                self.commodity_tracker.start_regular_simulation()
                for (buff, multi_motive_buff_motives) in self.MULTI_MOTIVE_BUFF_MOTIVES.items():
                    self._multi_motive_buff_trackers.append(sims.multi_motive_buff_tracker.MultiMotiveBuffTracker(self, multi_motive_buff_motives, buff))
                self.sim_info.buffs_component.on_sim_ready_to_simulate()
                self.sim_info.career_tracker.on_sim_startup()
                self.sim_info.whim_tracker.load_whims_info_from_proto()
                self.sim_info.whim_tracker.refresh_goals()
                self.update_sleep_schedule()
                if services.current_zone().is_zone_running:
                    self.sim_info.away_action_tracker.refresh()
                    if self.is_selectable:
                        self.sim_info.aspiration_tracker.initialize_aspiration()
                        self.sim_info.career_tracker.activate_career_aspirations()
                if self.is_selected:
                    self.client.notify_active_sim_changed(None, self)
            elif self._simulation_state == SimulationState.RESETTING:
                self.remove_callbacks()
            self.on_outfit_changed(self._sim_info.get_current_outfit())
            self.refresh_los_constraint()
            self._simulation_state = SimulationState.SIMULATING
            self.add_callbacks()
            self.on_start_up(self)
            self._start_environment_score()
            self._update_intended_position_on_active_lot(update_ui=True)
            self._update_walkstyle()
        finally:
            self._starting_up = False

    def on_remove(self):
        self.sim_info.buffs_component.on_sim_removed()
        self._stop_environment_score()
        if self._update_facial_overlay in self.Buffs.on_mood_changed:
            self.Buffs.on_mood_changed.remove(self._update_facial_overlay)
        self.commodity_tracker.remove_non_persisted_commodities()
        self.commodity_tracker.stop_regular_simulation()
        self.sim_info.time_sim_was_saved = services.time_service().sim_now
        if self.is_selectable:
            self.commodity_tracker.start_low_level_simulation()
        self.asm_auto_exit.clear()
        zone = services.current_zone()
        if zone.master_controller is not None:
            zone.master_controller.remove_sim(self)
        self.on_posture_event.clear()
        self.on_slot = None
        _zone.remove_sim(self.sim_id, zone.id)
        self._is_removed = True
        self._stop_animation_interaction()
        super().on_remove()
        self._posture_state = None
        self.on_start_up.clear()
        self.remove_callbacks()
        self.on_intended_location_changed.clear()
        zone.sim_quadtree.remove(self.sim_id, placement.ItemType.SIM_POSITION, 0)
        zone.sim_quadtree.remove(self.sim_id, placement.ItemType.SIM_INTENDED_POSITION, 0)
        if self.refresh_los_constraint in zone.wall_contour_update_callbacks:
            zone.wall_contour_update_callbacks.remove(self.refresh_los_constraint)
        self._remove_multi_motive_buff_trackers()
        self.object_ids_to_ignore.clear()
        self._si_state = None
        self._mixers_locked_out.clear()
        self._mixer_front_page_cooldown.clear()

    def post_remove(self):
        super().post_remove()
        self._buff_handles.clear()
        self.queue = None

    @property
    def allow_running_for_long_distance_routes(self):
        for buff in self.Buffs:
            while not buff.allow_running_for_long_distance_routes:
                return False
        return True

    def _update_facial_overlay(self, *_, **__):

        def restart_overlay_asm(asm):
            asm.set_current_state('entry')

        if self._update_facial_overlay_interaction is None:
            return
        overlay_animation = self.FACIAL_OVERLAY_ANIMATION(self._update_facial_overlay_interaction, setup_asm_additional=restart_overlay_asm, enable_auto_exit=False)
        asm = overlay_animation.get_asm()
        if asm is None:
            logger.warn('Sim: {} - overlay_animation.get_asm() returned None instead of a valid ASM in sim._update_facial_overlay()', self)
            return
        arb = animation.arb.Arb()
        overlay_animation.append_to_arb(asm, arb)
        arb_element = ArbElement(arb)
        arb_element.distribute()

    def _update_quadtree_location(self, *_, **__):
        pos = self.position
        pos = sims4.math.Vector2(pos.x, pos.z)
        geo = sims4.geometry.QtCircle(pos, self._quadtree_radius)
        services.sim_quadtree().insert(self, self.sim_id, placement.ItemType.SIM_POSITION, geo, self.routing_surface.secondary_id, False, 0)

    def add_stand_slot_reservation(self, interaction, position, routing_surface, excluded_sims):
        interaction.add_liability(STAND_SLOT_LIABILITY, StandSlotReservationLiability(self, interaction))
        excluded_sims.add(self)
        self._stand_slot_reservation = position
        pos_2d = sims4.math.Vector2(position.x, position.z)
        geo = sims4.geometry.QtCircle(pos_2d, self._quadtree_radius)
        services.sim_quadtree().insert(self, self.sim_id, placement.ItemType.ROUTE_GOAL_SUPPRESSOR, geo, routing_surface.secondary_id, False, 0)
        reservation_radius = self._quadtree_radius*2
        polygon = sims4.geometry.generate_circle_constraint(6, position, reservation_radius)
        self.on_slot = (position, polygon, routing_surface)
        UserFootprintHelper.force_move_sims_in_polygon(polygon, routing_surface, exclude=excluded_sims)

    def remove_stand_slot_reservation(self, interaction):
        services.sim_quadtree().remove(self.sim_id, placement.ItemType.ROUTE_GOAL_SUPPRESSOR, 0)
        self.on_slot = None

    def get_stand_slot_reservation_violators(self, excluded_sims=()):
        if not self.on_slot:
            return
        (_, polygon, routing_surface) = self.on_slot
        violators = []
        excluded_sims = {sim for sim in itertools.chain((self,), excluded_sims)}
        for sim_nearby in placement.get_nearby_sims(polygon.centroid(), routing_surface.secondary_id, radius=polygon.radius(), exclude=excluded_sims):
            while sims4.geometry.test_point_in_polygon(sim_nearby.position, polygon):
                violators.append(sim_nearby)
        return violators

    def _check_violations(self, *_, **__):
        if services.privacy_service().check_for_late_violators(self):
            return
        for reaction_trigger in self.reaction_triggers.values():
            reaction_trigger.intersect_and_execute(self)

    @property
    def quadtree_radius(self):
        return self._quadtree_radius

    @property
    def intended_location(self):
        if self.queue is not None and self.queue.transition_controller is not None:
            return self.queue.transition_controller.intended_location(self)
        return self.location

    @property
    def intended_transform(self):
        return self.intended_location.transform

    @property
    def intended_routing_surface(self):
        return self.intended_location.routing_surface

    @property
    def intended_position_on_active_lot(self):
        return self._intended_position_on_active_lot

    def get_intended_location_excluding_transition(self, exclude_transition):
        if self.queue.transition_controller is None or self.queue.transition_controller is exclude_transition:
            return self.location
        return self.intended_location

    @property
    def is_moving(self):
        return not sims4.math.transform_almost_equal_2d(self.intended_transform, self.transform) or self.intended_routing_surface != self.routing_surface

    def _on_update_goals(self, goal_list, starting):
        NUM_GOALS_TO_RESERVE = 2
        if starting:
            for (index, goal) in enumerate(goal_list):
                if index >= NUM_GOALS_TO_RESERVE:
                    break
                pos = sims4.math.Vector2(goal.position.x, goal.position.z)
                geo = sims4.geometry.QtCircle(pos, self._quadtree_radius)
                services.sim_quadtree().insert(self, self.sim_id, placement.ItemType.SIM_INTENDED_POSITION, geo, goal.routing_surface_id.secondary_id, False, index + 1)
        else:
            for (index, goal) in enumerate(goal_list):
                if index >= NUM_GOALS_TO_RESERVE:
                    break
                services.sim_quadtree().remove(self.sim_id, placement.ItemType.SIM_INTENDED_POSITION, index + 1)

    def _should_invalidate_location(self):
        return False

    @property
    def career_tracker(self):
        return self.sim_info.career_tracker

    @property
    def trait_tracker(self):
        return self.sim_info.trait_tracker

    def has_trait(self, trait):
        return self.sim_info.trait_tracker.has_trait(trait)

    @property
    def statistic_tracker(self):
        return self.sim_info.statistic_tracker

    @property
    def commodity_tracker(self):
        return self.sim_info.commodity_tracker

    @property
    def static_commodity_tracker(self):
        return self.sim_info.static_commodity_tracker

    @property
    def Buffs(self):
        return self.sim_info.buffs_component

    def add_buff_from_op(self, *args, **kwargs):
        return self.sim_info.add_buff_from_op(*args, **kwargs)

    def add_buff(self, *args, **kwargs):
        return self.sim_info.add_buff(*args, **kwargs)

    def remove_buff(self, *args, **kwargs):
        return self.sim_info.remove_buff(*args, **kwargs)

    def has_buff(self, *args, **kwargs):
        return self.sim_info.has_buff(*args, **kwargs)

    def get_active_buff_types(self, *args, **kwargs):
        return self.sim_info.get_active_buff_types(*args, **kwargs)

    def debug_add_buff_by_type(self, *args, **kwargs):
        return self.sim_info.debug_add_buff_by_type(*args, **kwargs)

    def remove_buff_by_type(self, *args, **kwargs):
        return self.sim_info.remove_buff_by_type(*args, **kwargs)

    def remove_buff_entry(self, *args, **kwargs):
        return self.sim_info.remove_buff_entry(*args, **kwargs)

    def set_buff_reason(self, *args, **kwargs):
        return self.sim_info.set_buff_reason(*args, **kwargs)

    def buff_commodity_changed(self, *args, **kwargs):
        return self.sim_info.buff_commodity_changed(*args, **kwargs)

    def get_success_chance_modifier(self, *args, **kwargs):
        return self.sim_info.get_success_chance_modifier(*args, **kwargs)

    def get_actor_scoring_modifier(self, *args, **kwargs):
        return self.sim_info.get_actor_scoring_modifier(*args, **kwargs)

    def get_actor_success_modifier(self, *args, **kwargs):
        return self.sim_info.get_actor_success_modifier(*args, **kwargs)

    def get_mood(self, *args, **kwargs):
        return self.sim_info.get_mood(*args, **kwargs)

    def get_mood_intensity(self, *args, **kwargs):
        return self.sim_info.get_mood_intensity(*args, **kwargs)

    def get_mood_animation_param_name(self, *args, **kwargs):
        return self.sim_info.get_mood_animation_param_name(*args, **kwargs)

    def get_effective_skill_level(self, *args, **kwargs):
        return self.sim_info.get_effective_skill_level(*args, **kwargs)

    def effective_skill_modified_buff_gen(self, *args, **kwargs):
        return self.sim_info.effective_skill_modified_buff_gen(*args, **kwargs)

    def get_all_stats_gen(self):
        return self.sim_info.get_all_stats_gen()

    def create_statistic_tracker(self):
        self.sim_info.create_statistic_tracker()

    def get_stat_instance(self, stat_type, **kwargs):
        return self.sim_info.get_stat_instance(stat_type, **kwargs)

    def get_stat_value(self, stat_type):
        return self.sim_info.get_stat_value(stat_type)

    def set_stat_value(self, stat_type, *args, **kwargs):
        self.sim_info.set_stat_value(stat_type, *args, **kwargs)

    def add_statistic_modifier(self, modifier, interaction_modifier=False):
        handle = self.sim_info.add_statistic_modifier(modifier, interaction_modifier)
        return handle

    def remove_statistic_modifier(self, handle):
        return self.sim_info.remove_statistic_modifier(handle)

    def get_score_multiplier(self, stat_type):
        return self.sim_info.get_score_multiplier(stat_type)

    def get_stat_multiplier(self, stat_type, participant_type):
        return self.sim_info.get_stat_multiplier(stat_type, participant_type)

    def update_all_commodities(self):
        return self.sim_info.update_all_commodities()

    def check_affordance_for_suppression(self, sim, aop, user_directed):
        return self.sim_info.check_affordance_for_suppression(sim, aop, user_directed)

    def is_locked(self, stat):
        return self.sim_info.is_locked(stat)

    def is_scorable(self, stat_type):
        return self.sim_info.is_scorable(stat_type)

    def is_in_distress(self):
        return self.sim_info.is_in_distress()

    def enter_distress(self, commodity):
        self.sim_info.enter_distress(commodity)

    def exit_distress(self, commodity):
        self.sim_info.exit_distress(commodity)

    def test_interaction_for_distress_compatability(self, interaction):
        return self.sim_info.test_interaction_for_distress_compatability(interaction)

    def test_for_distress_compatibility_and_run_replacement(self, interaction, sim):
        return self.sim_info.test_for_distress_compatibility_and_run_replacement(interaction, sim)

    def add_modifiers_for_interaction(self, interaction, sequence):
        return self.sim_info.add_modifiers_for_interaction(interaction, sequence)

    def get_commodity(self, commodity_id):
        return self.commodity_tracker.get_statistic(commodity_id)

    def inspect_commodity(self, commodity_id):
        return self.commodity_tracker.get_value(commodity_id)

    def commodities_gen(self):
        for stat in self.commodity_tracker:
            yield stat

    def static_commodities_gen(self):
        for stat in self.static_commodity_tracker:
            yield stat

    def get_statistic(self, stat, add=True):
        return self.sim_info.get_statistic(stat, add=add)

    def statistics_gen(self):
        for stat in self.statistic_tracker:
            yield stat

    def get_off_lot_autonomy_rule_type(self):
        return self.sim_info.get_off_lot_autonomy_rule_type()

    def get_off_lot_autonomy_tolerance(self):
        return self.sim_info.get_off_lot_autonomy_tolerance()

    def get_off_lot_autonomy_radius(self):
        return self.sim_info.get_off_lot_autonomy_radius()

    def skills_gen(self):
        for stat in self.commodities_gen():
            while stat.is_skill:
                yield stat

    def all_skills(self):
        return self.sim_info.all_skills()

    def scored_stats_gen(self):
        for stat in self.statistics_gen():
            while stat.is_scored and self.is_scorable(stat.stat_type):
                yield stat
        for commodity in self.commodities_gen():
            while commodity.is_scored and self.is_scorable(commodity.stat_type):
                yield commodity
        for static_commodity in self.static_commodities_gen():
            while static_commodity.is_scored and self.is_scorable(static_commodity.stat_type):
                yield static_commodity

    def get_permission(self, permission_type):
        return self.sim_info.get_permission(permission_type)

    @property
    def aspiration_tracker(self):
        return self.sim_info.aspiration_tracker

    @property
    def relationship_tracker(self):
        return self.sim_info.relationship_tracker

    @property
    def singed(self):
        return self.sim_info.singed

    @singed.setter
    def singed(self, value):
        self.sim_info.singed = value

    @property
    def on_fire(self):
        return self.sim_info.on_fire

    @property
    def walkstyle(self):
        return self.sim_info._walkstyle_requests[0].walkstyle

    @property
    def default_walkstyle(self):
        return self.sim_info._walkstyle_requests[-1].walkstyle

    @default_walkstyle.setter
    def default_walkstyle(self, walkstyle):
        self.sim_info._walkstyle_requests[-1] = WalkStyleRequest(-1, walkstyle)
        self._update_walkstyle()

    def request_walkstyle(self, walkstyle_request, uid):
        self.sim_info.request_walkstyle(walkstyle_request, uid)

    def remove_walkstyle(self, uid):
        self.sim_info.remove_walkstyle(uid)

    def _update_walkstyle(self):
        for primitive in self.primitives:
            try:
                primitive.request_walkstyle_update()
            except AttributeError:
                pass

    def route_finished(self, path_id):
        for primitive in self.primitives:
            while hasattr(primitive, 'route_finished'):
                primitive.route_finished(path_id)

    def route_time_update(self, path_id, current_time):
        for primitive in self.primitives:
            while hasattr(primitive, 'route_time_update'):
                primitive.route_time_update(path_id, current_time)

    def force_update_routing_location(self):
        for primitive in self.primitives:
            while hasattr(primitive, 'update_routing_location'):
                primitive.update_routing_location()

    def populate_localization_token(self, *args, **kwargs):
        self.sim_info.populate_localization_token(*args, **kwargs)

    def create_posture_interaction_context(self):
        return InteractionContext(self, InteractionContext.SOURCE_POSTURE_GRAPH, Priority.High)

    @property
    def posture(self):
        return self.posture_state.body

    @property
    def posture_state(self):
        return self._posture_state

    @posture_state.setter
    def posture_state(self, value):
        self._posture_state = value
        self._posture_target_refs.clear()
        for aspect in self._posture_state.aspects:
            while aspect.target is not None:
                self._posture_target_refs.append(aspect.target.ref(lambda _: self.reset(ResetReason.RESET_EXPECTED, self, 'Posture target went away.')))
        if self.posture_state is not None:
            connectivity_handles = self.posture_state.connectivity_handles
            if connectivity_handles is not None:
                self._pathplan_context.connectivity_handles = connectivity_handles

    @property
    def connectivity_handles(self):
        return self._pathplan_context.connectivity_handles

    def is_surface(self, *args, **kwargs):
        return False

    def ignore_group_socials(self, excluded_group=None):
        for si in self.si_state:
            if excluded_group is not None and si.social_group is excluded_group:
                pass
            while si.ignore_group_socials:
                return True
        next_interaction = self.queue.peek_head()
        if next_interaction is not None and (next_interaction.is_super and next_interaction.ignore_group_socials) and (excluded_group is None or next_interaction.social_group is not excluded_group):
            return True
        return False

    @property
    def ignore_autonomous_targeted_socials(self):
        return any(si.ignore_autonomous_targeted_socials for si in self.si_state)

    def get_groups_for_sim_gen(self):
        for group in self._social_groups:
            while self in group:
                yield group

    def get_main_group(self):
        for group in self.get_groups_for_sim_gen():
            while not group.is_side_group:
                return group

    def get_visible_group(self):
        visible_group = None
        for group in self.get_groups_for_sim_gen():
            while group.is_visible:
                if not group.is_side_group:
                    return group
                visible_group = group
        return visible_group

    def is_in_side_group(self):
        return any(self in g and g.is_side_group for g in self.get_groups_for_sim_gen())

    def is_in_group_with(self, target_sim):
        return any(target_sim in group for group in self.get_groups_for_sim_gen())

    @caches.cached
    def get_social_context(self):
        sims = set(itertools.chain(*self.get_groups_for_sim_gen()))
        social_context_bit = SocialContextTest.get_overall_short_term_context_bit(*sims)
        if social_context_bit is not None:
            size_limit = social_context_bit.size_limit
            if size_limit is not None:
                if len(sims) > size_limit.size:
                    social_context_bit = size_limit.transformation
        return social_context_bit

    def on_social_context_changed(self):
        SocialContextTest.get_overall_short_term_context_bit.cache.clear()
        self.get_social_context.cache.clear()
        for group in self.get_groups_for_sim_gen():
            group.on_social_context_changed()

    def without_social_focus(self, sequence):
        new_sequence = sequence
        for group in self.get_groups_for_sim_gen():
            new_sequence = group.without_social_focus(self, self, new_sequence)
        return new_sequence

    def set_mood_asm_parameter(self, asm, actor_name):
        mood_asm_name = self.get_mood_animation_param_name()
        if mood_asm_name is not None:
            asm.set_actor_parameter(actor_name, self, 'mood', mood_asm_name.lower())

    def set_trait_asm_parameters(self, asm, actor_name):
        sim_traits = self.sim_info.trait_tracker.equipped_traits
        asm_param_dict = {}
        for trait in sim_traits:
            while trait.asm_param_name is not None:
                asm_param_dict[(trait.asm_param_name, actor_name)] = True
        asm.update_locked_params(asm_param_dict)

    def evaluate_si_state_and_cancel_incompatible(self, finishing_type, cancel_reason_msg):
        sim_transform_constraint = interactions.constraints.Transform(self.transform, routing_surface=self.routing_surface)
        sim_posture_constraint = self.posture_state.posture_constraint_strict
        sim_constraint = sim_transform_constraint.intersect(sim_posture_constraint)
        (_, included_sis) = self.si_state.get_combined_constraint(sim_constraint, None, None, None, True, True)
        for si in self.si_state:
            while si not in included_sis and si.basic_content is not None and si.basic_content.staging:
                si.cancel(finishing_type, cancel_reason_msg)

    def refresh_los_constraint(self, *args, target_position=DEFAULT, **kwargs):
        if target_position is DEFAULT:
            target_position = self.intended_position
            target_forward = self.intended_forward
            target_routing_surface = self.intended_routing_surface
        else:
            target_forward = self.forward
            target_routing_surface = self.routing_surface
        if target_routing_surface == self.lineofsight_component.routing_surface and sims4.math.vector3_almost_equal_2d(target_position, self.lineofsight_component.position):
            return
        target_position = target_position + target_forward*self.lineofsight_component.facing_offset
        self.lineofsight_component.generate(position=target_position, routing_surface=target_routing_surface, lock=True, build_convex=True)
        self._los_constraint = self.lineofsight_component.constraint
        zone = services.current_zone()
        if self.refresh_los_constraint not in zone.wall_contour_update_callbacks:
            zone.wall_contour_update_callbacks.append(self.refresh_los_constraint)
        self._social_group_constraint = None

    @property
    def los_constraint(self):
        return self._los_constraint

    def can_see(self, obj):
        if obj.intended_position is not None:
            obj_position = obj.intended_position
        else:
            obj_position = obj.position
        return self.los_constraint.geometry.contains_point(obj_position)

    def get_social_group_constraint(self, si):
        if self._social_group_constraint is None:
            si_constraint = self.si_state.get_total_constraint(priority=si.priority if si is not None else None, include_inertial_sis=True, to_exclude=si)
            for base_constraint in si_constraint:
                while base_constraint.geometry is not None:
                    break
            if self.queue.running is not None and self.queue.running.is_super:
                base_constraint = interactions.constraints.Transform(self.transform, routing_surface=self.routing_surface)
            if base_constraint.geometry is not None and base_constraint.geometry.polygon:
                los_constraint = self.los_constraint
                base_geometry = base_constraint.geometry
                expanded_polygons = []
                for sub_polygon in base_geometry.polygon:
                    if len(sub_polygon) == 1:
                        new_polygon = sims4.geometry.generate_circle_constraint(LOSAndSocialConstraintTuning.num_sides_for_circle_expansion_of_point_constraint, sub_polygon[0], LOSAndSocialConstraintTuning.constraint_expansion_amount)
                    else:
                        while len(sub_polygon) > 1:
                            center = sum(sub_polygon, sims4.math.Vector3.ZERO())/len(sub_polygon)
                            new_polygon = sims4.geometry.inflate_polygon(sub_polygon, LOSAndSocialConstraintTuning.constraint_expansion_amount, centroid=center)
                            expanded_polygons.append(new_polygon)
                    expanded_polygons.append(new_polygon)
                new_compound_polygon = sims4.geometry.CompoundPolygon(expanded_polygons)
                new_restricted_polygon = sims4.geometry.RestrictedPolygon(new_compound_polygon, [])
                base_constraint = interactions.constraints.Constraint(geometry=new_restricted_polygon, routing_surface=los_constraint.routing_surface)
                intersection = base_constraint.intersect(los_constraint)
                self._social_group_constraint = intersection
            else:
                self._social_group_constraint = interactions.constraints.Anywhere()
        return self._social_group_constraint

    def get_next_work_priority(self):
        if not self.is_simulating:
            return Priority.Critical
        next_interaction = self.queue.get_head()
        if next_interaction is not None:
            return next_interaction.priority
        return Priority.Low

    def get_next_work(self):
        if self.is_being_destroyed:
            logger.error('sim.get_next_work() called for Sim {} when they were in the process of being destroyed.', self, owner='tastle/sscholl')
            return WorkRequest()
        if not self.is_simulating:
            if self._starting_up:
                return WorkRequest()
            return WorkRequest(work_element=elements.GeneratorElement(self._startup_sim_gen), required_sims=(self,))
        _ = self.queue._get_head()
        next_interaction = self.queue.get_head()
        if next_interaction is None and services.current_zone().is_zone_running:
            if any(not i.is_super for i in self.queue._autonomy):
                for i in tuple(self.queue._autonomy):
                    i.cancel(FinishingType.INTERACTION_QUEUE, 'Blocked interaction in autonomy bucket, canceling all interactions in the autonomy bucket to fix.')
            else:
                self.run_subaction_autonomy()
                next_interaction = self.queue.get_head()
        if next_interaction is not None:
            next_interaction.refresh_and_lock_required_sims()
            required_sims = next_interaction.required_sims(for_threading=True)
            element = elements.GeneratorElement(functools.partial(self._process_interaction_gen, interaction=next_interaction))
            return WorkRequest(work_element=element, required_sims=required_sims, additional_resources=next_interaction.required_resources(), set_work_timestamp=next_interaction.set_work_timestamp, debug_name=str(next_interaction))
        return WorkRequest()

    def get_idle_element(self, duration=10):
        if self.is_being_destroyed:
            logger.error('sim.get_idle_element() called for Sim {} when they were in the process of being destroyed.', self, owner='tastle/sscholl')
        if not self.is_simulating:
            return (None, None)
        possible_idle_behaviors = []
        for si in self.si_state:
            idle_behavior = si.get_idle_behavior()
            while idle_behavior is not None:
                possible_idle_behaviors.append((si, idle_behavior))
        if possible_idle_behaviors:
            (_, idle_behavior) = random.choice(possible_idle_behaviors)
        else:
            idle_behavior = self.posture.get_idle_behavior()
        sleep_behavior = build_element((elements.SoftSleepElement(date_and_time.create_time_span(minutes=duration)), self.si_state.process_gen))
        idle_sequence = build_element([build_critical_section(idle_behavior, flush_all_animations), sleep_behavior])
        idle_sequence = with_skippable_animation_time((self,), sequence=idle_sequence)
        for group in self.get_groups_for_sim_gen():
            idle_sequence = group.with_listener_focus(self, self, idle_sequence)

        def do_idle_behavior(timeline):
            nonlocal idle_sequence
            with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self, 'Sim', 'Process Idle Interaction'):
                try:
                    self.queue._apply_next_pressure()
                    result = yield element_utils.run_child(timeline, idle_sequence)
                    return result
                finally:
                    idle_sequence = None

        def cancel_idle_behavior():
            nonlocal idle_sequence
            if idle_sequence is not None:
                idle_sequence.trigger_soft_stop()
                idle_sequence = None

        return (elements.GeneratorElement(do_idle_behavior), cancel_idle_behavior)

    def _process_interaction_gen(self, timeline, interaction=None):
        with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self, 'Sim', 'Process Interaction', interaction):
            try:
                if self.queue.get_head() is not interaction:
                    logger.info('Interaction has changed from {} to {} after work was scheduled. Bailing.', interaction, self.queue.get_head())
                    return
                yield self.queue.process_one_interaction_gen(timeline)
            finally:
                interaction.unlock_required_sims()

    def _can_skip_turn_rules(self, interaction):
        if interaction.continuation_id is not None:
            return True
        participants = interaction.required_sims()
        if len(participants) == 1 and interaction.sim in participants:
            return True
        return False

    def get_resolver(self):
        return event_testing.resolver.SingleSimResolver(self.sim_info)

    def push_super_affordance(self, super_affordance, target, context, **kwargs):
        if isinstance(super_affordance, str):
            super_affordance = services.get_instance_manager(sims4.resources.Types.INTERACTION).get(super_affordance)
            if not super_affordance:
                raise ValueError('{0} is not a super affordance'.format(super_affordance))
        aop = interactions.aop.AffordanceObjectPair(super_affordance, target, super_affordance, None, **kwargs)
        res = aop.test_and_execute(context)
        return res

    def test_super_affordance(self, super_affordance, target, context, **kwargs):
        if isinstance(super_affordance, str):
            super_affordance = services.get_instance_manager(sims4.resources.Types.INTERACTION).get(super_affordance)
            if not super_affordance:
                raise ValueError('{0} is not a super affordance'.format(super_affordance))
        aop = interactions.aop.AffordanceObjectPair(super_affordance, target, super_affordance, None, **kwargs)
        res = aop.test(context)
        return res

    def si_state_is_empty(self):
        for si in self.si_state:
            while si.affordance is not posture_graph.PostureGraphService.SIM_DEFAULT_AFFORDANCE:
                return False
        return True

    def find_interaction_by_id(self, id_to_find):
        id_to_find = self.ui_manager.get_routing_owner_id(id_to_find)
        interaction = None
        if self.queue is not None:
            interaction = self.queue.find_interaction_by_id(id_to_find)
            if interaction is None:
                transition_controller = self.queue.transition_controller
                if transition_controller is not None:
                    (target_si, _) = transition_controller.interaction.get_target_si()
                    if target_si is not None and target_si.id == id_to_find:
                        return target_si
        if interaction is None and self.si_state is not None:
            interaction = self.si_state.find_interaction_by_id(id_to_find)
        return interaction

    def find_continuation_by_id(self, source_id):
        interaction = None
        if self.queue is not None:
            interaction = self.queue.find_continuation_by_id(source_id)
        if interaction is None and self.si_state is not None:
            interaction = self.si_state.find_continuation_by_id(source_id)
        return interaction

    def find_sub_interaction_by_aop_id(self, super_id, aop_id):
        interaction = None
        if self.queue is not None:
            interaction = self.queue.find_sub_interaction(super_id, aop_id)
        return interaction

    def owns_this_lot(self, lot):
        return self.sim_info.household_id == lot.owner_household_id

    def set_autonomy_preference(self, preference, obj):
        if preference.is_scoring:
            self.sim_info.autonomy_scoring_preferences[preference.tag] = obj.id
        else:
            self.sim_info.autonomy_use_preferences[preference.tag] = obj.id

    def is_object_scoring_preferred(self, preference_tag, obj):
        return self._check_preference(preference_tag, obj, self.sim_info.autonomy_scoring_preferences)

    def is_object_use_preferred(self, preference_tag, obj):
        return self._check_preference(preference_tag, obj, self.sim_info.autonomy_use_preferences)

    @property
    def autonomy_settings(self):
        return self.get_autonomy_settings()

    def _check_preference(self, preference_tag, obj, preference_map):
        obj_id = preference_map.get(preference_tag, None)
        return obj.id == obj_id

    def on_outfit_changed(self, category_and_index):
        for (buff_type, buff_handle) in self._buff_handles:
            if buff_handle is not None:
                self.remove_buff(buff_handle)
            stat = self.get_stat_instance(buff_type.commodity)
            while stat is not None:
                stat.decay_enabled = True
        self._buff_handles.clear()
        part_ids = self.sim_info.get_part_ids_for_current_outfit()
        if part_ids:
            buff_guids = cas.cas.get_buff_from_part_ids(part_ids)
            for buff_guid in buff_guids:
                buff_type = services.get_instance_manager(sims4.resources.Types.BUFF).get(buff_guid)
                if buff_type is None:
                    logger.error('Error one of the parts in current outfit does not have a valid buff')
                buff_handle = None
                if buff_type.can_add(self):
                    buff_handle = self.add_buff(buff_type, buff_reason=self.BUFF_CLOTHING_REASON)
                else:
                    if buff_type.commodity is None:
                        pass
                    stat = self.get_stat_instance(buff_type.commodity)
                    if stat is not None:
                        stat.decay_enabled = True
                self._buff_handles.append((buff_type, buff_handle))

    def load_staged_interactions(self):
        return self.si_state.load_staged_interactions(self.sim_info.si_state)

    def load_transitioning_interaction(self):
        return self.si_state.load_transitioning_interaction(self.sim_info.si_state)

    def load_queued_interactions(self):
        self.si_state.load_queued_interactions(self.sim_info.si_state)

    def update_related_objects(self, triggering_sim, forced_interaction=None):
        if not triggering_sim.valid_for_distribution:
            return
        PARTICIPANT_TYPE_MASK = interactions.ParticipantType.Actor | interactions.ParticipantType.Object | interactions.ParticipantType.Listeners | interactions.ParticipantType.CarriedObject | interactions.ParticipantType.CraftingObject | interactions.ParticipantType.ActorSurface
        relevant_obj_ids = set()
        relevant_obj_ids.add(self.id)
        if forced_interaction is not None:
            objs = forced_interaction.get_participants(PARTICIPANT_TYPE_MASK)
            for obj in objs:
                relevant_obj_ids.add(obj.id)
        for i in self.running_interactions_gen(Interaction):
            objs = i.get_participants(PARTICIPANT_TYPE_MASK)
            for obj in objs:
                relevant_obj_ids.add(obj.id)
        if self.queue.running is not None:
            objs = self.queue.running.get_participants(PARTICIPANT_TYPE_MASK)
            for obj in objs:
                relevant_obj_ids.add(obj.id)
        op = distributor.ops.SetRelatedObjects(relevant_obj_ids, self.id)
        dist = Distributor.instance()
        dist.add_op(triggering_sim, op)

    def is_on_active_lot(self, tolerance=0):
        lot = services.current_zone().lot
        if not lot.is_position_on_lot(self.position, tolerance):
            return False
        if self.intended_position != self.position and not lot.is_position_on_lot(self.intended_position, tolerance):
            return False
        return True

    def log_sim_info(self, *args, **kwargs):
        self.sim_info.log_sim_info(*args, **kwargs)

lock_instance_tunables(Sim, _persists=False, _world_file_object_persists=False)

class AgeUpSuperInteraction(SuperInteraction):
    __qualname__ = 'AgeUpSuperInteraction'

    def _setup_gen(self, timeline):
        result = yield super()._setup_gen(timeline)
        if result:
            self.animation_context.register_event_handler(self._age_up_event_handler, handler_id=100)
            return True
        return False

    def _pre_perform(self, *args, **kwargs):
        self.add_liability(AGING_LIABILITY, AgingLiability(self.sim.sim_info, self.sim.sim_info.age))
        return super()._pre_perform(*args, **kwargs)

    def _age_up_event_handler(self, *args, **kwargs):
        self.sim.sim_info.advance_age()

