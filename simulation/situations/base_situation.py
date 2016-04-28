import random
from protocolbuffers import Situations_pb2, Loot_pb2
from clock import interval_in_sim_minutes
from distributor.rollback import ProtocolBufferRollback
from distributor.shared_messages import build_icon_info_msg
from distributor.system import Distributor
from event_testing import test_events
from event_testing.resolver import SingleSimResolver
from event_testing.test_events import TestEvent
from interactions.context import QueueInsertStrategy, InteractionContext
from interactions.interaction_finisher import FinishingType
from interactions.utils.tunable import SetGoodbyeNotificationElement
from services.social_service import SocialEnums
from sims.sim_outfits import OutfitCategory, OutfitChangeReason
from sims4.localization import LocalizationHelperTuning
from sims4.tuning.geometric import TunableCurve
from sims4.tuning.tunable import TunableList, TunableReference
from sims4.utils import classproperty
from singletons import DEFAULT
from situations.bouncer.bouncer_client import IBouncerClient
from situations.bouncer.bouncer_request import BouncerRequest, BouncerFallbackRequestFactory, BouncerHostRequestFactory, RequestSpawningOption
from situations.bouncer.bouncer_types import BouncerRequestPriority
from situations.situation_guest_list import SituationGuestList, SituationInvitationPurpose, SituationGuestInfo
from situations.situation_job_data import SituationJobData
from situations.situation_serialization import SituationSeed, SeedPurpose
from situations.situation_sim import SituationSim
from situations.situation_types import JobHolderNoShowAction, JobHolderDiedOrLeftAction, SituationStage, SituationCallbackOption, ScoringCallbackData, SituationMedal, GreetedStatus, SituationSerializationOption, SituationCommonBlacklistCategory
from ui.screen_slam import ScreenSlam
import distributor.ops
import id_generator
import interactions.context
import services
import sims4.log
import telemetry_helper
logger = sims4.log.Logger('Situations')
TELEMETRY_GROUP_SITUATIONS = 'SITU'
TELEMETRY_HOOK_START_SITUATION = 'STOS'
TELEMETRY_HOOK_STOP_SITUATION = 'STAS'
TELEMETRY_HOOK_SCORE_CHANGE = 'CHSC'
TELEMETRY_HOOK_GOAL = 'GOAL'
TELEMETRY_FIELD_SITUATION_ID = 'stid'
TELEMETRY_FIELD_SITUATION_SCORE = 'stsc'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_SITUATIONS)

class _RequestUserData:
    __qualname__ = '_RequestUserData'

    def __init__(self, role_state_type=None):
        self.role_state_type = role_state_type

class BaseSituation(IBouncerClient):
    __qualname__ = 'BaseSituation'
    PLAYABLE_SIMS_SCORE_MULTIPLIER = TunableCurve(description='Score multiplier based on number of playable Sims in the Situation')
    AUTOMATIC_BRONZE_TRAITS = TunableList(description='\n        An optional collection of traits that, if possessed by the host, will automagically promote the situation to bronze on start.', tunable=TunableReference(description='\n            A trait that if possessed by the host will start a given situation at bronze.', manager=services.get_instance_manager(sims4.resources.Types.TRAIT)))

    @classproperty
    def distribution_override(cls):
        return False

    constrained_emotional_loot = None

    def __init__(self, seed):
        self.id = seed.situation_id
        self._seed = seed
        self._guest_list = seed.guest_list
        self.initiating_sim_info = services.sim_info_manager().get(self._guest_list.host_sim_id)
        self.requesting_sim_info = self._guest_list.get_filter_requesting_sim_info()
        self._is_invite_only = self._guest_list.invite_only
        self.primitives = ()
        self.manager = services.get_zone_situation_manager()
        self.visible_to_client = False
        self._guid = id_generator.generate_object_id()
        self._stage = SituationStage.NEVER_RUN
        self._jobs = {}
        self._situation_sims = {}
        self._score = seed.score
        self.end_time_stamp = None
        self.scoring_enabled = seed.scoring_enabled
        self._start_time = seed.start_time
        services.get_event_manager().register_single_event(self, TestEvent.InteractionComplete)
        services.get_event_manager().register_single_event(self, TestEvent.ItemCrafted)

    def __str__(self):
        return self.__class__.__name__

    def start_situation(self):
        logger.debug('Starting up situation: {}', self)
        if self.is_user_facing:
            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_START_SITUATION, sim=self._guest_list.host_sim) as hook:
                hook.write_int(TELEMETRY_FIELD_SITUATION_ID, self.id)
        self._stage = SituationStage.SETUP
        self._initialize_situation_jobs()
        self._expand_guest_list_based_on_tuning()
        if self.is_user_facing:
            self._verify_role_objects()
        self._issue_requests()
        self._notify_guests_of_request()
        if self._start_time is None:
            self._start_time = services.time_service().sim_now
        self._stage = SituationStage.RUNNING
        if self.AUTOMATIC_BRONZE_TRAITS:
            host_sim = services.object_manager().get(self._guest_list.host_sim_id)
            bronze_award = self.get_level_data(SituationMedal.BRONZE)
            if bronze_award is not None and host_sim is not None:
                while True:
                    for trait in self.AUTOMATIC_BRONZE_TRAITS:
                        while host_sim.has_trait(trait):
                            self.score_update(bronze_award.score_delta)
                            break

    def load_situation(self):
        logger.debug('Loading situation:{}', self)
        self._load_situation_issue_requests()
        all_assigned = self.manager.bouncer.on_situation_loaded(self)
        if not all_assigned:
            logger.debug('Situation:{} not loaded because all sims could not be assigned', self, owner='sscholl')
            return False
        self._load_situation_states_and_phases()
        self._stage = SituationStage.RUNNING
        return True

    @classmethod
    def _should_seed_be_loaded(cls, seed):
        if cls.situation_serialization_option == SituationSerializationOption.DONT:
            return False
        zone = services.current_zone()
        if cls.situation_serialization_option == SituationSerializationOption.LOT:
            if zone.venue_type_changed_between_save_and_load() or (zone.lot_owner_household_changed_between_save_and_load() or services.game_clock_service().time_has_passed_in_world_since_zone_save()) or zone.active_household_changed_between_save_and_load():
                logger.debug("Don't load lot situation:{} due to game state change", seed.situation_type, owner='sscholl')
                return False
            return True
        if zone.time_has_passed_in_world_since_open_street_save():
            logger.debug("Don't load open street situation:{},{} due to open street time passed", seed.situation_type, seed.situation_id, owner='sscholl')
            return False
        active_lot_household = services.current_zone().get_active_lot_owner_household()
        if active_lot_household is not None:
            for sim_info in seed.invited_sim_infos_gen():
                while sim_info.household is active_lot_household:
                    logger.debug("Don't load open street situation:{},{} due to lot owner sim", seed.situation_type, seed.situation_id, owner='sscholl')
                    return False
        active_household = services.active_household()
        if active_household is not None:
            for sim_info in seed.invited_sim_infos_gen():
                while sim_info.is_selectable:
                    logger.debug("Don't load open street situation:{},{} due to selectable sim", seed.situation_type, seed.situation_id, owner='sscholl')
                    return False
        return True

    def _load_situation_issue_requests(self):
        self._load_situation_jobs()
        self._issue_requests()
        self._notify_guests_of_request()

    def _load_situation_states_and_phases(self):
        pass

    def _destroy(self):
        logger.debug('Destroying situation: {}', self)
        services.get_event_manager().unregister_single_event(self, TestEvent.InteractionComplete)
        services.get_event_manager().unregister_single_event(self, TestEvent.ItemCrafted)
        self._stage = SituationStage.DEAD
        self.manager.bouncer.on_situation_destroy(self)
        for sim in tuple(self._situation_sims):
            self._on_remove_sim_from_situation(sim)
        for job_data in self._jobs.values():
            job_data.destroy()
        self._jobs.clear()
        self._situation_sims.clear()
        self._guest_list._destroy()

    def _self_destruct(self):
        if self._stage >= SituationStage.DYING:
            return
        if not self.manager._request_destruction(self):
            return
        self._stage = SituationStage.DYING
        self.manager.destroy_situation_by_id(self.id)

    def on_remove(self):
        logger.debug('on_remove situation: {}', self)
        self._stage = SituationStage.DYING
        if self.is_user_facing and self.scoring_enabled and services.current_zone().is_zone_shutting_down == False:
            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_STOP_SITUATION, sim=self._guest_list.host_sim) as hook:
                hook.write_int(TELEMETRY_FIELD_SITUATION_ID, self.id)
                hook.write_int(TELEMETRY_FIELD_SITUATION_SCORE, self._score)
            level = self.get_level()
            for (sim, situation_sim) in self._situation_sims.items():
                while sim.is_selectable and situation_sim.current_job_type.rewards:
                    rewards = situation_sim.current_job_type.rewards.get(level, None)
                    if rewards is not None:
                        rewards.apply(sim)
            personas = set()
            for sim in tuple(self._situation_sims):
                personas.add(sim.persona)
            self._situation_social_message(personas, SocialEnums.SITUATION_FINISHED)
            for sim in self.all_sims_in_situation_gen():
                services.get_event_manager().process_event(test_events.TestEvent.SituationEnded, sim_info=sim.sim_info, situation=self)
            for registrant in self.manager._get_callback_registrants(self.id):
                while registrant.situation_callback_option == SituationCallbackOption.END_OF_SITUATION_SCORING:
                    data = ScoringCallbackData(self.id, self._score)
                    for (sim, situation_sim) in self._situation_sims.items():
                        while sim.is_selectable:
                            data.add_sim_job_score(sim, situation_sim.current_job_type, situation_sim.get_int_total_score())
                    registrant.callback_fn(self.id, registrant.situation_callback_option, data)
            level_data = self.get_level_data(level)
            if level_data.medal == SituationMedal.BRONZE:
                slam = self.screen_slam_bronze
            elif level_data.medal == SituationMedal.SILVER:
                slam = self.screen_slam_silver
            elif level_data.medal == SituationMedal.GOLD:
                slam = self.screen_slam_gold
            else:
                slam = self.screen_slam_no_medal
            if slam is not None:
                slam.send_screen_slam_message(self.initiating_sim_info, self.display_name, level_data.level_description)

    def on_added_to_distributor(self):
        for sim in self._situation_sims.keys():
            self.add_situation_sim_joined_message(sim)

    def on_removed_from_distributor(self):
        pass

    def post_remove(self):
        self._destroy()

    @classproperty
    def situation_serialization_option(cls):
        return SituationSerializationOption.LOT

    @classproperty
    def supports_multiple_sims(cls):
        return True

    @classproperty
    def implies_greeted_status(cls):
        return False

    @classmethod
    def _get_greeted_status(cls):
        if cls._implies_greeted_status == False:
            return GreetedStatus.NOT_APPLICABLE
        return GreetedStatus.GREETED

    @classmethod
    def get_player_greeted_status_from_seed(cls, situation_seed):
        active_household = services.active_household()
        sim_info_manager = services.sim_info_manager()
        if situation_seed.purpose != SeedPurpose.TRAVEL:
            sim_infos_of_interest = [sim_info for sim_info in active_household.sim_info_gen() if sim_info not in sim_info_manager.get_traveled_to_zone_sim_infos()]
        else:
            sim_infos_of_interest = list(active_household.sim_info_gen())
        if any(sim_info in situation_seed.invited_sim_infos_gen() for sim_info in sim_infos_of_interest):
            return cls._get_greeted_status()
        return GreetedStatus.NOT_APPLICABLE

    @classmethod
    def get_npc_greeted_status_during_zone_fixup(cls, situation_seed, sim_info):
        if situation_seed.contains_sim(sim_info):
            return cls._get_greeted_status()
        return GreetedStatus.NOT_APPLICABLE

    def _on_make_waiting_player_greeted(self, door_bell_ringing_sim):
        pass

    @classproperty
    def is_unique_situation(cls):
        return False

    def save_situation(self):
        if self.situation_serialization_option == SituationSerializationOption.DONT:
            return
        seed = self._create_standard_save_seed()
        if seed is None:
            return
        try:
            self._save_custom(seed)
        except Exception:
            logger.exception('Failed to save situation: {}', self)
            raise
        finally:
            seed.finalize_creation_for_save()
        return seed

    def _create_standard_save_seed(self):
        guest_list = SituationGuestList(self._guest_list.invite_only, self._guest_list.host_sim_id)
        for request in self.manager.bouncer.situation_requests_gen(self):
            guest_info = self._create_guest_info_from_request(request)
            while guest_info is not None:
                guest_list.add_guest_info(guest_info)
        seed = SituationSeed(type(self), SeedPurpose.PERSISTENCE, self.id, guest_list, self.is_user_facing, duration_override=self._get_remaining_time_in_minutes(), zone_id=services.current_zone().id, start_time=self._start_time, scoring_enabled=self.scoring_enabled)
        for (job_type, situation_job_data) in self._jobs.items():
            seed.add_job_data(job_type, situation_job_data.default_role_state_type, situation_job_data.emotional_loot_actions)
        seed.score = self._score
        return seed

    def _save_custom(self, seed):
        pass

    def handle_event(self, sim_info, event, resolver):
        sim = sim_info.get_sim_instance()
        if self._situation_sims.get(sim) is None:
            return
        score = self.get_sim_score_for_action(sim, event, resolver)
        if score != 0:
            self.score_update(score)

    def _should_apply_job_emotions_and_commodity_changes(self, sim):
        sim_in_no_other_situations = len(self.manager.get_situations_sim_is_in(sim)) == 1
        return sim_in_no_other_situations and (self.manager.sim_being_created is sim and sim.sim_info.is_npc)

    def _get_relationship_bits_to_add_to_sims(self, sim, job_type):
        result = []
        for relationship_data in self.relationship_between_job_members:
            target_job = None
            if job_type == relationship_data.job_x:
                target_job = relationship_data.job_y
            elif job_type == relationship_data.job_y:
                target_job = relationship_data.job_x
            while target_job is not None:
                while True:
                    for target_sim in self.all_sims_in_job_gen(target_job):
                        while target_sim is not sim:
                            while True:
                                for bit in relationship_data.relationship_bits_to_add:
                                    result.append((target_sim, bit))
        return result

    def _add_relationship_amongst_job_members(self, sim, job_type):
        sim_id = sim.id
        sim_relationship_tracker = sim.relationship_tracker
        for (target_sim, bit) in self._get_relationship_bits_to_add_to_sims(sim, job_type):
            target_sim_id = target_sim.id
            if not sim_relationship_tracker.has_bit(target_sim_id, bit):
                sim_relationship_tracker.add_relationship_bit(target_sim_id, bit, force_add=True)
            target_relationship_tracker = target_sim.relationship_tracker
            while not target_relationship_tracker.has_bit(sim_id, bit):
                target_relationship_tracker.add_relationship_bit(sim_id, bit, force_add=True)

    def _remove_relationship_amongst_job_members(self, sim, job_type):
        sim_id = sim.id
        sim_relationship_tracker = sim.relationship_tracker
        for (target_sim, bit) in self._get_relationship_bits_to_add_to_sims(sim, job_type):
            sim_relationship_tracker.remove_relationship_bit(target_sim.id, bit)
            target_sim.relationship_tracker.remove_relationship_bit(sim_id, bit)

    def _on_add_sim_to_situation(self, sim, job_type, role_state_type_override=None):
        logger.debug('adding sim {0} to situation: {1}', sim, self)
        if sim in self._situation_sims:
            logger.error('Adding sim {} with job {} to situation{} but the sims is already in the situation.', sim, job_type, self)
            return
        self._situation_sims[sim] = SituationSim(sim)
        self._set_job_for_sim(sim, job_type, role_state_type_override)
        self._add_situation_buff_to_sim(sim)
        if self._should_apply_job_emotions_and_commodity_changes(sim):
            job_data = self._jobs[job_type]
            resolver = sim.get_resolver()
            loot_actions = job_data.emotional_loot_actions
            if loot_actions:
                loot = loot_actions.pick_loot_op()
                if loot is not None:
                    (_, buff_type) = loot.apply_to_resolver(resolver)
                    self._situation_sims[sim].set_emotional_buff_for_gsi(buff_type)
            if job_type.commodities:
                while True:
                    for commodity in job_type.commodities:
                        commodity.apply_to_resolver(resolver)
        self._add_relationship_amongst_job_members(sim, job_type)
        self.add_situation_sim_joined_message(sim)
        self._send_social_start(sim)

    def _on_remove_sim_from_situation(self, sim):
        logger.debug('removing sim {0} from situation: {1}', sim, self)
        situation_sim = self._situation_sims.pop(sim, None)
        if situation_sim is not None and services.current_zone().is_zone_shutting_down == False:
            if situation_sim.outfit_priority_handle is not None:
                sim.sim_info.sim_outfits.remove_default_outfit_priority(situation_sim.outfit_priority_handle)
            if self._stage != SituationStage.DEAD:
                self._on_sim_removed_from_situation_prematurely(sim)
                self.add_situation_sim_left_message(sim)
            self._remove_situation_buff_from_sim(sim, situation_sim)
            self._remove_relationship_amongst_job_members(sim, situation_sim.current_job_type)
            situation_sim.destroy()

    def _on_sim_removed_from_situation_prematurely(self, sim):
        if self._should_cancel_leave_interaction_on_premature_removal:
            self._cancel_leave_interaction(sim)

    @property
    def _should_cancel_leave_interaction_on_premature_removal(self):
        return False

    def _cancel_leave_interaction(self, sim):
        if sim.sim_info.get_sim_instance() is None:
            return
        interaction_set = sim.get_running_and_queued_interactions_by_tag(self.manager.LEAVE_INTERACTION_TAGS)
        for interaction in interaction_set:
            interaction.cancel(FinishingType.SITUATIONS, 'Keep Sim from leaving.')

    def _add_situation_buff_to_sim(self, sim):
        if sim is not None and self._buff.buff_type is not None:
            situation_sim = self._situation_sims[sim]
            situation_sim.buff_handle = sim.add_buff(self._buff.buff_type)

    def _remove_situation_buff_from_sim(self, sim, situation_sim):
        if sim is not None and situation_sim.buff_handle is not None:
            sim.remove_buff(situation_sim.buff_handle)

    def _send_social_start(self, sim):
        if self.is_user_facing:
            personas = set()
            personas.add(sim.persona)
            self._situation_social_message(personas, SocialEnums.SITUATION_START)

    def remove_sim_from_situation(self, sim):
        self.manager.remove_sim_from_situation(sim, self.id)

    def is_sim_in_situation(self, sim):
        if self._situation_sims is None:
            return False
        return sim in self._situation_sims

    def on_ask_sim_to_leave(self, sim):
        return True

    def on_first_assignment_pass_completed(self):
        self._offer_goals_first_time()

    def on_sim_assigned_to_request(self, sim, request):
        job_type = request.job_type
        role_state_type = request.callback_data.role_state_type
        self._on_add_sim_to_situation(sim, job_type, role_state_type)
        if sim.is_selectable and self.has_offered_goals():
            self.refresh_situation_goals()

    def on_sim_unassigned_from_request(self, sim, request):
        job_type = request.job_type
        if job_type.died_or_left_action == JobHolderDiedOrLeftAction.END_SITUATION:
            self._on_remove_sim_from_situation(sim)
            self._self_destruct()
        elif job_type.died_or_left_action == JobHolderDiedOrLeftAction.REPLACE_THEM:
            self._on_remove_sim_from_situation(sim)
            new_request = request.clone_for_replace()
            self.manager.bouncer.submit_request(new_request)
        else:
            self._on_remove_sim_from_situation(sim)

    def on_sim_replaced_in_request(self, old_sim, new_sim, request):
        job_type = request.job_type
        role_state_type = request.callback_data.role_state_type
        self._on_remove_sim_from_situation(old_sim)
        self._on_add_sim_to_situation(new_sim, job_type, role_state_type)

    def on_failed_to_spawn_sim_for_request(self, request):
        job_type = request.job_type
        if job_type.no_show_action == JobHolderNoShowAction.END_SITUATION:
            self._self_destruct()
        elif job_type.no_show_action == JobHolderNoShowAction.REPLACE_THEM:
            new_request = request.clone_for_replace(only_if_explicit=True)
            if new_request is not None:
                self.manager.bouncer.submit_request(new_request)

    def on_tardy_request(self, request):
        job_type = request.job_type
        if job_type.no_show_action == JobHolderNoShowAction.END_SITUATION:
            self._self_destruct()

    def get_situation_goal_info(self):
        tracker = self._get_goal_tracker()
        if tracker is None:
            return
        return tracker.get_goal_info()

    def get_situation_completed_goal_info(self):
        tracker = self._get_goal_tracker()
        if tracker is None:
            return
        return tracker.get_completed_goal_info()

    def _offer_goals_first_time(self):
        tracker = self._get_goal_tracker()
        if tracker is None:
            return
        if tracker.has_offered_goals():
            return
        if self._seed.goal_tracker_seedling is not None:
            tracker.load_from_seedling(self._seed.goal_tracker_seedling)
        else:
            tracker.refresh_goals()

    def refresh_situation_goals(self):
        tracker = self._get_goal_tracker()
        if tracker is None:
            return
        tracker.refresh_goals()

    def has_offered_goals(self):
        tracker = self._get_goal_tracker()
        if tracker is None:
            return False
        return tracker.has_offered_goals()

    def _send_goal_update_to_client(self, completed_goal=None):
        goal_tracker = self._get_goal_tracker()
        if goal_tracker is None:
            return
        self.add_situation_goal_update_message(goal_tracker.get_main_goal(), goal_tracker.get_main_goal_completed(), goal_tracker.get_minor_goals(), completed_goal)

    def debug_force_complete_named_goal(self, goal_name, target_sim=None):
        tracker = self._get_goal_tracker()
        if tracker is None:
            return False
        return tracker.debug_force_complete_named_goal(goal_name, target_sim)

    def _get_goal_tracker(self):
        raise NotImplementedError

    def on_goal_completed(self, goal):
        score = goal.score
        score = self.score_update(score)
        with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_GOAL) as hook:
            hook.write_int(TELEMETRY_FIELD_SITUATION_ID, self.id)
            hook.write_int('scor', score)
            hook.write_guid('goal', goal.guid64)

    def _on_goals_completed(self):
        pass

    @classmethod
    def default_job(cls):
        raise NotImplementedError

    @classmethod
    def resident_job(cls):
        raise NotImplementedError

    @classmethod
    def get_prepopulated_job_for_sims(cls, sim, target_sim_id=None):
        pass

    def churn_jobs(self):
        for job_data in self._jobs.values():
            job_data._churn()

    def shift_change_jobs(self):
        for job_data in self._jobs.values():
            job_data._shift_change()

    def _make_late_auto_fill_request(self, job_type):
        request_priority = BouncerRequestPriority.AUTO_FILL_PLUS if job_type.elevated_importance else BouncerRequestPriority.AUTO_FILL
        request = BouncerRequest(self, callback_data=_RequestUserData(), job_type=job_type, request_priority=request_priority, user_facing=self.is_user_facing, exclusivity=self.exclusivity, common_blacklist_categories=SituationCommonBlacklistCategory.ACTIVE_HOUSEHOLD | SituationCommonBlacklistCategory.ACTIVE_LOT_HOUSEHOLD, spawning_option=RequestSpawningOption.MUST_SPAWN)
        self.manager.bouncer.submit_request(request)

    def _initialize_situation_jobs(self):
        pass

    def _load_situation_jobs(self):
        for (job_type, job_data) in self._seed.get_job_data().items():
            self._add_job_type(job_type, job_data.role_state_type, job_data.emotional_loot_actions_type)

    def _add_job_type(self, job_type, default_role_state, emotional_loot_actions=None):
        self._jobs[job_type] = SituationJobData(job_type, default_role_state, self)
        if job_type.emotional_setup:
            job_data = self._jobs[job_type]
            if self.constrained_emotional_loot is not None:
                for loot in job_type.emotional_setup:
                    while loot.single_sim_loot_actions is self.constrained_emotional_loot:
                        emotional_loot_actions = self.constrained_emotional_loot
            if not (emotional_loot_actions is None and emotional_loot_actions):
                weighted_loots = [(loot.weight, loot.single_sim_loot_actions) for loot in job_type.emotional_setup]
                emotional_loot_actions = sims4.random.weighted_random_item(weighted_loots)
            job_data.emotional_loot_actions = emotional_loot_actions

    def _set_job_role_state(self, job_type, role_state_type, role_affordance_target=None):
        self._jobs[job_type].set_default_role_state_type(role_state_type)
        for (sim, situation_sim) in self._situation_sims.items():
            while situation_sim.current_job_type == job_type:
                self._set_sim_role_state(sim, role_state_type, role_affordance_target)

    def _set_sim_role_state(self, sim, role_state_type, role_affordance_target=None):
        situation_sim = self._situation_sims[sim]
        job_type = situation_sim.current_job_type
        (override_role_state_type, override_target) = self._get_role_state_overrides(sim, job_type, role_state_type, role_affordance_target)
        if override_role_state_type is not None:
            role_state_type = override_role_state_type
        if override_target is not None:
            role_affordance_target = override_target
        situation_sim.set_role_state_type(role_state_type, role_affordance_target)
        self._on_set_sim_role_state(sim, job_type, role_state_type, role_affordance_target)

    def _get_role_state_overrides(self, sim, job_type, role_state_type, role_affordance_target):
        return (None, None)

    def _on_set_sim_role_state(self, sim, job_type, role_state_type, role_affordance_target=None):
        pass

    def _validate_guest_list(self):
        if self._guest_list is None:
            return
        for job in self._guest_list.get_set_of_jobs():
            while self._jobs.get(job) is None:
                logger.warn('guest list job {} is not available in situation: {}', job, self)

    def _expand_guest_list_based_on_tuning(self):
        host_sim_id = self._guest_list.host_sim_id
        if self.resident_job() is not None and host_sim_id != 0 and self._guest_list.get_guest_info_for_sim_id(host_sim_id) is None:
            guest_info = SituationGuestInfo.construct_from_purpose(host_sim_id, self.resident_job(), SituationInvitationPurpose.HOSTING)
            self._guest_list.add_guest_info(guest_info)
        for job_type in self._jobs:
            num_to_auto_fill = job_type.get_auto_invite() - len(self._guest_list.get_guest_infos_for_job(job_type))
            for _ in range(num_to_auto_fill):
                guest_info = SituationGuestInfo.construct_from_purpose(0, job_type, SituationInvitationPurpose.AUTO_FILL)
                self._guest_list.add_guest_info(guest_info)

    def _create_request_from_guest_info(self, guest_info):
        request = BouncerRequest(self, callback_data=_RequestUserData(guest_info.persisted_role_state_type), job_type=guest_info.job_type, request_priority=guest_info.request_priority, user_facing=self.is_user_facing, exclusivity=self.exclusivity, requested_sim_id=guest_info.sim_id, accept_alternate_sim=guest_info.accept_alternate_sim, spawning_option=guest_info.spawning_option, requesting_sim_info=self.requesting_sim_info, expectation_preference=guest_info.expectation_preference, loaded=guest_info.persisted_role_state_type is not None, common_blacklist_categories=guest_info.common_blacklist_categories, spawn_during_zone_spin_up=guest_info.spawn_during_zone_spin_up)
        return request

    def _create_guest_info_from_request(self, request):
        guest_info = None
        sim = request.assigned_sim
        if sim is not None:
            guest_info = SituationGuestInfo(sim.id, request.job_type, request.spawning_option, request.request_priority, request.expectation_preference, request.accept_alternate_sim, request.common_blacklist_categories)
            guest_info._set_persisted_role_state_type(self.get_current_role_state_for_sim(sim))
        elif request.is_factory == False:
            guest_info = SituationGuestInfo(request.requested_sim_id, request.job_type, request.spawning_option, request.request_priority, request.expectation_preference, request.accept_alternate_sim, request.common_blacklist_categories)
        return guest_info

    def _notify_guests_of_request(self):
        if self._guest_list is None:
            return
        sim_info_manager = services.sim_info_manager()
        for guest_info in self._guest_list.guest_info_gen():
            sim_info = sim_info_manager.get(guest_info.sim_id)
            while sim_info is not None:
                sim_info.on_situation_request(self)

    def _issue_requests(self):
        for guest_info in self._guest_list.guest_info_gen():
            request = self._create_request_from_guest_info(guest_info)
            self.manager.bouncer.submit_request(request)
        host_sim = self._guest_list.host_sim
        if self.resident_job() is not None and host_sim is not None and host_sim.sim_info.lives_here:
            request = BouncerHostRequestFactory(self, callback_data=_RequestUserData(), job_type=self.resident_job(), user_facing=self.is_user_facing, exclusivity=self.exclusivity, requesting_sim_info=self.requesting_sim_info)
            self.manager.bouncer.submit_request(request)
        self._create_uninvited_request()

    def _create_uninvited_request(self):
        if not self._is_invite_only and self.default_job() is not None:
            request = BouncerFallbackRequestFactory(self, callback_data=_RequestUserData(), job_type=self.default_job(), user_facing=self.is_user_facing, exclusivity=self.exclusivity)
            self.manager.bouncer.submit_request(request)

    def invite_sim_to_default_job(self, sim):
        if self.default_job() is None:
            logger.error('Requesting invitation to default job on a situation ({}) that does not have one.', self, owner='manus')
            return
        guest_info = SituationGuestInfo(sim.id, self.default_job(), RequestSpawningOption.DONT_CARE, BouncerRequestPriority.VIP, expectation_preference=True)
        request = self._create_request_from_guest_info(guest_info)
        self.manager.bouncer.submit_request(request)

    def _set_job_for_sim(self, sim, job, role_state_type_override=None):
        logger.debug('set situation job {} for sim {} in situation: {}', job, sim, self)
        job_data = self._jobs.get(job)
        if job_data is None:
            logger.error('No record of job {} in the situation {}.', job, self, owner='manus')
            return
        if job_data.test_add_sim(sim, self.requesting_sim_info) == False:
            logger.warn("Adding sim {} to job {} for which they don't match the filter {} in situation {}", sim, job, job.filter, self)
        self._situation_sims[sim].current_job_type = job
        self._on_set_sim_job(sim, job)
        if role_state_type_override:
            role_state_type = role_state_type_override
        else:
            role_state_type = job_data.default_role_state_type
        self._set_sim_role_state(sim, role_state_type, None)
        if self._seed.is_loadable:
            return
        job_uniform = job.job_uniform
        if job_uniform is None or sim.is_selectable and not job_uniform.playable_sims_change_outfits:
            return
        outfit_generation_tags = job_uniform.situation_outfit_generation_tags
        if outfit_generation_tags:
            outfit_tags = random.choice(list(outfit_generation_tags))
            tag_list = list(outfit_tags)
            sim.sim_info.generate_outfit(OutfitCategory.SITUATION, 0, tag_list=tag_list)
        sim_outfits = sim.sim_info.sim_outfits
        outfit_priority_handle = sim_outfits.add_default_outfit_priority(None, job_uniform.outfit_change_reason, job_uniform.outfit_change_priority)
        self._situation_sims[sim].outfit_priority_handle = outfit_priority_handle
        if self.manager.sim_being_created is sim:
            resolver = SingleSimResolver(sim)
            new_outfit = sim_outfits.get_outfit_for_clothing_change(None, OutfitChangeReason.DefaultOutfit, resolver=resolver)
            sim.sim_info.set_current_outfit(new_outfit)
        else:
            context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, interactions.priority.Priority.High, insert_strategy=QueueInsertStrategy.NEXT, bucket=interactions.context.InteractionBucketType.DEFAULT)
            sim.push_super_affordance(job.CHANGE_OUTFIT_INTERACTION, None, context)

    def _on_set_sim_job(self, sim, job):
        if job.goodbye_notification is DEFAULT:
            return
        if sim.sim_info.goodbye_notification == SetGoodbyeNotificationElement.NEVER_USE_NOTIFICATION_NO_MATTER_WHAT:
            return
        sim.sim_info.goodbye_notification = job.goodbye_notification

    def get_current_job_for_sim(self, sim):
        if sim is None:
            return
        situation_sim = self._situation_sims.get(sim)
        if situation_sim is None:
            return
        return situation_sim.current_job_type

    def get_current_role_state_for_sim(self, sim):
        if sim is None:
            return
        situation_sim = self._situation_sims.get(sim)
        if situation_sim is None:
            return
        return situation_sim.current_role_state_type

    def get_role_tags_for_sim(self, sim):
        current_tag_set = set()
        current_job = self.get_current_job_for_sim(sim)
        if current_job is None:
            return current_tag_set
        current_tag_set.update(current_job.tags)
        current_role_state = self.get_current_role_state_for_sim(sim)
        if current_role_state is not None:
            current_tag_set.update(current_role_state.tags)
        return current_tag_set

    def sim_has_job(self, sim, job_type):
        return job_type == self.get_current_job_for_sim(sim)

    def all_jobs_gen(self):
        for job_type in self._jobs.keys():
            yield job_type

    def gsi_all_jobs_data_gen(self):
        for job_data in self._jobs.values():
            yield job_data

    def all_sims_in_situation_gen(self):
        for sim in self._situation_sims:
            yield sim

    def all_sims_in_job_gen(self, job_type):
        for (sim, situation_sim) in self._situation_sims.items():
            while situation_sim.current_job_type is job_type:
                yield sim

    def get_num_sims_in_job(self, job_type):
        count = 0
        for (_, situation_sim) in self._situation_sims.items():
            while situation_sim.current_job_type is job_type:
                count += 1
        return count

    def get_sims_in_job_for_churn(self, job_type):
        sims = []
        if not self._situation_sims:
            return sims
        for (sim, situation_sim) in tuple(self._situation_sims.items()):
            while situation_sim.current_job_type is job_type:
                if self is self.manager._bouncer.get_most_important_situation_for_sim(sim):
                    sims.append(sim)
        return sims

    def get_num_sims_in_job_for_churn(self, job_type):
        return len(self.get_sims_in_job_for_churn(job_type))

    def get_num_sims_in_role_state(self, role_state_type):
        count = 0
        for situation_sim in self._situation_sims.values():
            while situation_sim.current_role_state_type is role_state_type:
                count += 1
        return count

    def _verify_role_objects(self):
        if self._guest_list is None:
            return
        bullet_points = []
        for job in self._guest_list.get_set_of_jobs():
            for recommended_object_tuning in job.recommended_objects:
                object_test = recommended_object_tuning.object
                object_list = object_test()
                num_objects = len(object_list)
                while num_objects < recommended_object_tuning.number:
                    bullet_points.append(recommended_object_tuning.object_display_name)
        if bullet_points:
            return self._display_role_objects_notification(self._guest_list.host_sim, LocalizationHelperTuning.get_bulleted_list(None, *bullet_points))

    def _display_role_objects_notification(self, sim, bullets):
        raise NotImplementedError

    @property
    def display_name(self):
        raise NotImplementedError

    @property
    def description(self):
        raise NotImplementedError

    @property
    def icon(self):
        raise NotImplementedError

    @property
    def start_audio_sting(self):
        pass

    @property
    def end_audio_sting(self):
        pass

    @classproperty
    def relationship_between_job_members(cls):
        raise NotImplementedError

    @classproperty
    def jobs_to_put_in_party(cls):
        raise NotImplementedError

    @property
    def is_user_facing(self):
        return self._seed.user_facing

    @property
    def spawn_sims_during_zone_spin_up(self):
        return self._seed.spawn_sims_during_zone_spin_up

    @property
    def sim(self):
        return self

    @property
    def is_traveling_situation(self):
        return self._seed.purpose == SeedPurpose.TRAVEL

    def set_end_time(self, end_time_in_sim_minutes):
        time_now = services.time_service().sim_now
        self.end_time_stamp = time_now + interval_in_sim_minutes(end_time_in_sim_minutes)

    @property
    def is_running(self):
        return self._stage == SituationStage.RUNNING

    def get_phase_state_name_for_gsi(self):
        return 'get_phase_state_name_for_gsi not overridden by a GPE'

    def _get_duration(self):
        raise NotImplementedError

    def _get_remaining_time(self):
        raise NotImplementedError

    def _get_remaining_time_in_minutes(self):
        raise NotImplementedError

    @property
    def num_of_sims(self):
        return len(self._situation_sims)

    def _situation_social_message(self, personas, social_enum):
        if self.is_user_facing:
            zone_id = sims4.zone_utils.get_zone_id()
            services.social_service.post_situation_message(personas, self._guid, self._display_name, zone_id, social_enum)

    @classmethod
    def level_data_gen(cls):
        raise NotImplementedError

    @classmethod
    def get_level_data(cls, medal:SituationMedal=SituationMedal.TIN):
        raise NotImplementedError

    @classmethod
    def get_level_min_threshold(cls, medal:SituationMedal=SituationMedal.TIN):
        raise NotImplementedError

    @property
    def score(self):
        return self._score

    def debug_set_overall_score(self, value):
        self._score = value

    def get_level(self, score=None):
        if score is None:
            score = self._score
        for level in self.level_data_gen():
            if score < level.min_score_threshold:
                break
            last_level = level
        return last_level.level_data.medal

    def _get_reward(self, score=0):
        if not score:
            score = self._score
        medal = self.get_level(score)
        level_data = self.get_level_data(medal)
        if level_data is not None:
            return level_data.reward
        return

    def score_update(self, score_delta):
        if self.is_user_facing and self.scoring_enabled:
            self.add_situation_score_update_message(self.build_situation_score_update_message(0, None))
            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_SCORE_CHANGE) as hook:
                hook.write_int(TELEMETRY_FIELD_SITUATION_ID, self.id)
                hook.write_int(TELEMETRY_FIELD_SITUATION_SCORE, self._score)
        return score_delta

    def get_sim_total_score(self, sim):
        situation_sim = self._situation_sims.get(sim)
        if situation_sim:
            return situation_sim.get_total_score()
        return 0

    def get_sim_score_for_action(self, sim, event, resolver, **kwargs):
        sim_job = self.get_current_job_for_sim(sim)
        if sim_job:
            return sim_job.get_score(event=event, resolver=resolver, **kwargs)
        return 0

    def get_num_playable_sims(self):
        playable_sims = 0
        for sim in self._situation_sims:
            while sim.is_selectable:
                playable_sims += 1
        return playable_sims

    def get_playable_sim_score_multiplier(self):
        if self.PLAYABLE_SIMS_SCORE_MULTIPLIER is not None:
            return self.PLAYABLE_SIMS_SCORE_MULTIPLIER.get(self.get_num_playable_sims())
        logger.warn('Invalid Tuning for Playable Sims Score Multiplier: {}', self.PLAYABLE_SIMS_SCORE_MULTIPLIER)
        return 1

    def _get_value_for_loot_op(self, sim, loot_op):
        stat_to_update = loot_op.stat
        tracker = sim.get_tracker(stat_to_update)
        stat_val = tracker.get_value(stat_to_update)
        true_delta = stat_to_update.clamp(stat_val + loot_op.get_value()) - stat_val
        return int(true_delta)

    @classmethod
    def can_start_walkby(cls, lot_id):
        return False

    def get_sim_available_for_walkby_flavor(self):
        pass

    def build_situation_start_message(self):
        start_msg = Situations_pb2.SituationStart()
        start_msg.score = int(round(self._score))
        start_msg.scoring_enabled = self.scoring_enabled
        build_icon_info_msg((self.icon, None), self.display_name, start_msg.icon_info)
        start_msg.icon_info.desc = self.description
        if self.end_time_stamp:
            start_msg.end_time = self.end_time_stamp.absolute_ticks()
        start_msg.current_level = self.build_situation_level_update_message()
        for sim in self._situation_sims.keys():
            if not sim.is_selectable:
                pass
            sim_job = self.get_current_job_for_sim(sim)
            while sim_job is not None:
                with ProtocolBufferRollback(start_msg.sim_jobs) as job_msg:
                    job_msg.sim_id = sim.id
                    job_msg.name = sim_job.display_name
                    job_msg.desc = sim_job.job_description
        start_msg.start_time = self._start_time.absolute_ticks()
        start_audio_sting = self.start_audio_sting
        if start_audio_sting is not None:
            start_msg.start_audio_sting.type = start_audio_sting.type
            start_msg.start_audio_sting.group = start_audio_sting.group
            start_msg.start_audio_sting.instance = start_audio_sting.instance
        logger.debug('Sending SituationStart situation:{} ', self, owner='sscholl')
        return start_msg

    def build_situation_end_message(self):
        end_msg = Loot_pb2.SituationEnded()
        build_icon_info_msg((self.icon, None), self.display_name, end_msg.icon_info)
        if services.current_zone().is_zone_shutting_down == False:
            household = services.active_household()
            if household is not None:
                household.set_highest_medal_for_situation(type(self).guid64, self.get_level(self.score))
            level_reward = self._get_reward(self.score)
            if level_reward is not None:
                end_msg.icon_info.desc = level_reward.reward_description
                level_reward.give_reward(self.initiating_sim_info)
            for sim in self._situation_sims.keys():
                if not sim.is_selectable:
                    pass
                end_msg.sim_ids.append(sim.id)
            end_msg.final_score = int(round(self._score))
            end_msg.final_level = self.build_situation_level_update_message()
            end_audio_sting = self.end_audio_sting
            if end_audio_sting is not None:
                end_msg.audio_sting.type = end_audio_sting.type
                end_msg.audio_sting.group = end_audio_sting.group
                end_msg.audio_sting.instance = end_audio_sting.instance
        return end_msg

    def build_situation_score_update_message(self, delta, sim=None):
        msg = Situations_pb2.SituationScoreUpdate()
        msg.score = int(round(self._score + delta))
        if sim:
            msg.sim_id = sim.id
        else:
            msg.sim_id = 0
        msg.current_level = self.build_situation_level_update_message()
        return msg

    def build_situation_level_update_message(self):
        level_msg = Situations_pb2.SituationLevelUpdate()
        current_level = self.get_level(self._score)
        if current_level == SituationMedal.GOLD:
            new_lower_bound = self.get_level_min_threshold(current_level - 1)
            new_upper_bound = self.get_level_min_threshold(current_level)
        else:
            new_lower_bound = self.get_level_min_threshold(current_level)
            new_upper_bound = self.get_level_min_threshold(current_level + 1)
        level_msg.score_lower_bound = new_lower_bound
        level_msg.score_upper_bound = new_upper_bound
        level_msg.current_level = current_level
        return level_msg

    def get_create_op(self, *args, **kwargs):
        return distributor.ops.SituationStartOp(self, self.build_situation_start_message())

    def get_delete_op(self):
        return distributor.ops.SituationEndOp(self.build_situation_end_message())

    def get_create_after_objs(self):
        return ()

    def add_situation_score_update_message(self, msg):
        op = distributor.ops.SituationScoreUpdateOp(msg)
        Distributor.instance().add_op(self, op)

    def add_situation_sim_joined_message(self, sim):
        if self.is_user_facing and self.manager.is_distributed(self):
            msg = Situations_pb2.SituationSimJoined()
            msg.sim_id = sim.id
            sim_job = self.get_current_job_for_sim(sim)
            if sim_job is not None:
                msg.job_assignment = Situations_pb2.SituationJobAssignment()
                msg.job_assignment.sim_id = sim.id
                msg.job_assignment.name = sim_job.display_name
                msg.job_assignment.desc = sim_job.job_description
                msg.job_assignment.tooltip = sim_job.tooltip_name
                logger.debug('Sending SituationSimJoinedOp situation:{} sim:{} job:{}', self, sim, sim_job, owner='sscholl')
            op = distributor.ops.SituationSimJoinedOp(msg)
            Distributor.instance().add_op(self, op)

    def add_situation_sim_left_message(self, sim):
        if self.is_user_facing:
            msg = Situations_pb2.SituationSimLeft()
            msg.sim_id = sim.id
            op = distributor.ops.SituationSimLeftOp(msg)
            Distributor.instance().add_op(self, op)

    def add_situation_goal_update_message(self, main_goal, is_main_goal_completed, situation_goals, completed_goal=None):
        if self.is_user_facing and self.scoring_enabled and self.is_running:
            msg = Situations_pb2.SituationGoalsUpdate()
            msg.situation_id = self.id
            if main_goal is not None:
                msg.major_goal.goal_id = main_goal.id
                msg.major_goal.goal_name = main_goal.display_name
                msg.major_goal.max_iterations = main_goal.max_iterations
                msg.major_goal.current_iterations = main_goal.completed_iterations
                msg.major_goal.goal_tooltip = main_goal.tooltip
                if self.main_goal_audio_sting is not None:
                    msg.major_goal.audio_sting.type = self.main_goal_audio_sting.type
                    msg.major_goal.audio_sting.group = self.main_goal_audio_sting.group
                    msg.major_goal.audio_sting.instance = self.main_goal_audio_sting.instance
                build_icon_info_msg((main_goal._icon, None), main_goal.display_name, msg.major_goal.icon_info)
            for goal in situation_goals:
                with ProtocolBufferRollback(msg.goals) as goal_msg:
                    goal_msg.goal_id = goal.id
                    goal_msg.goal_name = goal.display_name
                    goal_msg.max_iterations = goal.max_iterations
                    goal_msg.current_iterations = goal.completed_iterations
                    goal_msg.goal_tooltip = goal.tooltip
                    if main_goal is not None and goal.id == main_goal.id and self.main_goal_audio_sting is not None:
                        goal_msg.audio_sting.type = self.main_goal_audio_sting.type
                        goal_msg.audio_sting.group = self.main_goal_audio_sting.group
                        goal_msg.audio_sting.instance = self.main_goal_audio_sting.instance
                    elif goal.audio_sting_on_complete is not None:
                        goal_msg.audio_sting.type = goal.audio_sting_on_complete.type
                        goal_msg.audio_sting.group = goal.audio_sting_on_complete.group
                        goal_msg.audio_sting.instance = goal.audio_sting_on_complete.instance
                    build_icon_info_msg((goal._icon, None), goal.display_name, goal_msg.icon_info)
            if completed_goal is not None:
                msg.completed_goal_id = completed_goal.id
            op = distributor.ops.SituationGoalUpdateOp(msg)
            Distributor.instance().add_op(self, op)

