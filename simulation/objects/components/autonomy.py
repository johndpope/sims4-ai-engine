import random
from animation.posture_manifest_constants import STAND_OR_SIT_CONSTRAINT
from autonomy.autonomy_modes import AutonomyMode, FullAutonomy, SubActionAutonomy
from autonomy.autonomy_request import AutonomyRequest, AutonomyDistanceEstimationBehavior
from autonomy.settings import AutonomyRandomization
from date_and_time import DateAndTime, TimeSpan
from event_testing.results import EnqueueResult
from interactions.aop import AffordanceObjectPair
from interactions.context import InteractionContext, InteractionSource, QueueInsertStrategy
from interactions.priority import Priority
from objects.components import Component, componentmethod, types
from role.role_tracker import RoleStateTracker
from sims4.resources import Types
from sims4.tuning.tunable import TunableFactory, TunableTuple, TunableSet, TunableReference, TunableList, Tunable, TunableSimMinute, TunableRange, OptionalTunable, TunableEnumEntry
from singletons import UNSET
from tunable_time import TunableTimeOfDay
import alarms
import autonomy.settings
import buffs.tunable
import caches
import clock
import date_and_time
import elements
import gsi_handlers
import interactions.utils
import services
import sims4.log
logger = sims4.log.Logger('AutonomyComponent', default_owner='rez')

class AutonomyComponent(Component, component_name=types.AUTONOMY_COMPONENT):
    __qualname__ = 'AutonomyComponent'
    STANDARD_STATIC_COMMODITY_SKIP_SET = TunableSet(TunableReference(manager=services.get_instance_manager(Types.STATIC_COMMODITY), description='A static commodity.'), description='A set of static commodities. Any affordances that provide these commodities will be skipped in a standard autonomy run.')
    DELAY_UNTIL_RUNNING_AUTONOMY_THE_FIRST_TIME = TunableSimMinute(5, description='The amount of time to wait before running autonomy the first time, in Sim minutes.')
    PREROLL_AUTONOMY_AFFORDANCE_SKIP_SET = TunableSet(TunableReference(manager=services.get_instance_manager(Types.INTERACTION), description='The affordances to skip trying to solve on preroll autonomy.'), description='A set of affordances that will be skipped when preroll autonomy is run.')
    SLEEP_SCHEDULE = TunableTuple(schedule=TunableList(TunableTuple(time_from_work_start=Tunable(float, 0, description='The time relative to the start work time that the buff should be added.  For example, if you want the Sim to gain this static commodity 10 hours before work, set this value to 10'), buff=buffs.tunable.TunableBuffReference(description='Buff that gets added to the sim.'))), default_work_time=TunableTimeOfDay(default_hour=9, description="The default time that the Sim assumes he needs to be at work if he doesn't have a career.  This is only used for sleep."))
    MIXERS_TO_CACHE = TunableRange(description='\n                         Number of mixers to cache during a subaction request\n                         ', tunable_type=int, default=3, minimum=1)
    _STORE_AUTONOMY_REQUEST_HISTORY = False

    def __init__(self, owner):
        super().__init__(owner)
        self._last_user_directed_action_time = DateAndTime(0)
        self._last_autonomous_action_time = DateAndTime(0)
        self._last_no_result_time = None
        self._autonomy_skip_sis = set()
        self._autonomy_enabled = False
        self._full_autonomy_alarm_handle = None
        self._multitasking_roll = UNSET
        self._role_tracker = RoleStateTracker(owner)
        self._full_autonomy_request = None
        self._full_autonomy_element_handle = None
        self._sleep_buff_handle = None
        self._sleep_buff_alarms = {}
        self._sleep_buff_reset = None
        self._autonomy_settings = autonomy.settings.AutonomySettings()
        self._cached_mixer_interactions = []

    def on_add(self):
        self.owner.si_state.on_changed.append(self.reset_multitasking_roll)
        self.owner.si_state.on_changed.append(self.invalidate_mixer_interaction_cache)

    def on_remove(self):
        for alarm_handle in self._sleep_buff_alarms.keys():
            alarms.cancel_alarm(alarm_handle)
        if self._full_autonomy_request is not None:
            self._full_autonomy_request.valid = False
            self._full_autonomy_request = None
        if self._sleep_buff_reset is not None:
            alarms.cancel_alarm(self._sleep_buff_reset)
        self.owner.si_state.on_changed.remove(self.invalidate_mixer_interaction_cache)
        self.owner.si_state.on_changed.remove(self.reset_multitasking_roll)
        self.on_sim_reset(True)
        self._role_tracker.shutdown()

    def _on_run_full_autonomy_callback(self, handle):
        if self._full_autonomy_element_handle is not None:
            return
        timeline = services.time_service().sim_timeline
        self._full_autonomy_element_handle = timeline.schedule(elements.GeneratorElement(self._run_full_autonomy_callback_gen))

    def _run_full_autonomy_callback_gen(self, timeline):
        try:
            self.set_last_autonomous_action_time(False)
            autonomy_pushed_interaction = yield self._attempt_full_autonomy_gen(timeline)
            self._last_autonomy_result_was_none = not autonomy_pushed_interaction
        except Exception:
            logger.exception('Exception hit while processing FullAutonomy for {}:', self.owner, owner='rez')
        finally:
            self._full_autonomy_element_handle = None
            self._schedule_next_full_autonomy_update()

    def _attempt_full_autonomy_gen(self, timeline):
        if self._full_autonomy_request is not None and self._full_autonomy_request.valid:
            logger.debug('Ignoring full autonomy request for {} due to pending request in the queue.', self.owner)
            return False
        if self.to_skip_autonomy():
            if gsi_handlers.autonomy_handlers.archiver.enabled:
                gsi_handlers.autonomy_handlers.archive_autonomy_data(self.owner, 'None - Running SIs are preventing autonomy from running: {}'.format(self._autonomy_skip_sis), 'FullAutonomy', None)
            return False
        if not self._test_full_autonomy():
            return False
        try:
            selected_interaction = None
            try:
                self._full_autonomy_request = self._create_autonomy_request()
                selected_interaction = yield services.autonomy_service().find_best_action_gen(timeline, self._full_autonomy_request, archive_if_enabled=False)
            finally:
                self._full_autonomy_request.valid = False
            if not self._autonomy_enabled:
                if gsi_handlers.autonomy_handlers.archiver.enabled:
                    gsi_handlers.autonomy_handlers.archive_autonomy_data(self.owner, 'None - Autonomy Disabled', 'FullAutonomy', None)
                return False
            if not self._test_full_autonomy():
                if selected_interaction:
                    selected_interaction.invalidate()
                return False
            chose_get_comfortable = False
            if selected_interaction is None:
                selected_interaction = self.get_comfortable_interaction()
                chose_get_comfortable = True
                if gsi_handlers.autonomy_handlers.archiver.enabled:
                    gsi_handlers.autonomy_handlers.archive_autonomy_data(self._full_autonomy_request.sim, selected_interaction, self._full_autonomy_request.autonomy_mode_label, self._full_autonomy_request.gsi_data)
            if selected_interaction is not None:
                result = self._push_interaction(selected_interaction)
                if not result and gsi_handlers.autonomy_handlers.archiver.enabled:
                    gsi_handlers.autonomy_handlers.archive_autonomy_data(self.owner, 'Failed - interaction failed to be pushed {}.'.format(selected_interaction), 'FullAutonomy', None)
                if result:
                    if gsi_handlers.autonomy_handlers.archiver.enabled:
                        gsi_handlers.autonomy_handlers.archive_autonomy_data(self._full_autonomy_request.sim, selected_interaction, self._full_autonomy_request.autonomy_mode_label, self._full_autonomy_request.gsi_data)
                    if chose_get_comfortable:
                        return False
                    return True
            return False
        finally:
            if selected_interaction is not None:
                selected_interaction.invalidate()

    def _test_full_autonomy(self):
        result = FullAutonomy.test(self.owner)
        if not result:
            if gsi_handlers.autonomy_handlers.archiver.enabled:
                gsi_handlers.autonomy_handlers.archive_autonomy_data(self.owner, result.reason, 'FullAutonomy', None)
            return False
        return True

    @componentmethod
    def run_test_autonomy_ping(self):
        autonomy_request = self._create_autonomy_request()
        selected_interaction = services.autonomy_service().find_best_action(autonomy_request)
        return selected_interaction

    @componentmethod
    def cancel_actively_running_full_autonomy_request(self):
        if self._full_autonomy_element_handle is not None:
            self._full_autonomy_element_handle.trigger_hard_stop()
            self._full_autonomy_element_handle = None

    @caches.cached
    def is_object_autonomously_available(self, obj):
        autonomy_rule = self.owner.get_off_lot_autonomy_rule_type()
        off_lot_radius = self.owner.get_off_lot_autonomy_radius()
        sim_is_on_active_lot = self.owner.is_on_active_lot(tolerance=self.owner.get_off_lot_autonomy_tolerance())
        return self.get_autonomous_availability_of_object(obj, autonomy_rule, off_lot_radius, sim_is_on_active_lot)

    def get_autonomous_availability_of_object(self, obj, autonomy_rule, off_lot_radius, sim_is_on_active_lot, reference_object=None):
        reference_object = self.owner if reference_object is None else reference_object
        if obj is self.owner:
            return True
        object_is_on_active_lot = obj.is_on_active_lot()
        if object_is_on_active_lot:
            if autonomy_rule == autonomy.autonomy_modifier.OffLotAutonomyRules.DEFAULT and not sim_is_on_active_lot:
                return False
            if autonomy_rule == autonomy.autonomy_modifier.OffLotAutonomyRules.OFF_LOT_ONLY:
                return False
        else:
            if autonomy_rule == autonomy.autonomy_modifier.OffLotAutonomyRules.ON_LOT_ONLY:
                return False
            if off_lot_radius == 0:
                return False
            if off_lot_radius > 0:
                delta = obj.position - reference_object.position
                if delta.magnitude() > off_lot_radius:
                    return False
        if autonomy_rule != autonomy.autonomy_modifier.OffLotAutonomyRules.UNLIMITED and obj.is_sim and not object_is_on_active_lot:
            if self.owner.is_on_active_lot(tolerance=self.owner.get_off_lot_autonomy_tolerance()):
                return False
            autonomy_service = services.autonomy_service()
            target_delta = obj.intended_position - obj.position
            if target_delta.magnitude_squared() > autonomy_service.MAX_OPEN_STREET_ROUTE_DISTANCE_FOR_SOCIAL_TARGET_SQUARED:
                return False
            distance_from_me = obj.intended_position - self.owner.intended_position
            if distance_from_me.magnitude_squared() > autonomy_service.MAX_OPEN_STREET_ROUTE_DISTANCE_FOR_INITIATING_SOCIAL_SQUARED:
                return False
        if self.owner.locked_from_obj_by_privacy(obj):
            return False
        return True

    def get_comfortable_interaction(self):
        sim = self.owner
        if not sim.posture.unconstrained:
            return
        if sim.get_main_group():
            return
        affordance = interactions.utils.satisfy_constraint_interaction.SatisfyConstraintSuperInteraction
        aop = AffordanceObjectPair(affordance, None, affordance, None, constraint_to_satisfy=STAND_OR_SIT_CONSTRAINT, route_fail_on_transition_fail=False, name_override='Satisfy[GetComfortable]', allow_posture_changes=True)
        context = InteractionContext(sim, InteractionContext.SOURCE_GET_COMFORTABLE, Priority.Low, insert_strategy=QueueInsertStrategy.NEXT, must_run_next=True, cancel_if_incompatible_in_queue=True)
        execute_result = aop.interaction_factory(context)
        return execute_result.interaction

    def _create_autonomy_request(self):
        autonomy_request = AutonomyRequest(self.owner, autonomy_mode=FullAutonomy, skipped_static_commodities=self.STANDARD_STATIC_COMMODITY_SKIP_SET, limited_autonomy_allowed=False)
        return autonomy_request

    def _push_interaction(self, selected_interaction):
        should_log = services.autonomy_service().should_log(self.owner)
        if AffordanceObjectPair.execute_interaction(selected_interaction):
            return True
        if should_log:
            logger.debug('Autonomy failed to push {}', selected_interaction.affordance)
        if selected_interaction.target:
            self.owner.add_lockout(selected_interaction.target, AutonomyMode.LOCKOUT_TIME)
        return False

    def _schedule_next_full_autonomy_update(self, delay_in_sim_minutes=None):
        if not self._autonomy_enabled:
            return
        try:
            if delay_in_sim_minutes is None:
                delay_in_sim_minutes = self.get_time_until_next_update()
            logger.assert_log(isinstance(delay_in_sim_minutes, TimeSpan), 'delay_in_sim_minutes is not a TimeSpan object in _schedule_next_full_autonomy_update()', owner='rez')
            logger.debug('Scheduling next autonomy update for {} for {}', self.owner, delay_in_sim_minutes)
            self._create_full_autonomy_alarm(delay_in_sim_minutes)
        except Exception:
            logger.exception('Exception hit while attempting to schedule FullAutonomy for {}:', self.owner)

    def start_autonomy_alarm(self):
        self._autonomy_enabled = True
        self._schedule_next_full_autonomy_update(clock.interval_in_sim_minutes(self.DELAY_UNTIL_RUNNING_AUTONOMY_THE_FIRST_TIME))

    def _create_full_autonomy_alarm(self, time_until_trigger):
        if self._full_autonomy_alarm_handle is not None:
            self._destroy_full_autonomy_alarm()
        if time_until_trigger.in_ticks() <= 0:
            time_until_trigger = TimeSpan(1)
        self._full_autonomy_alarm_handle = alarms.add_alarm(self, time_until_trigger, self._on_run_full_autonomy_callback, use_sleep_time=False)

    def _destroy_full_autonomy_alarm(self):
        if self._full_autonomy_alarm_handle is not None:
            alarms.cancel_alarm(self._full_autonomy_alarm_handle)
            self._full_autonomy_alarm_handle = None

    @componentmethod
    def get_multitasking_roll(self):
        if self._multitasking_roll is UNSET:
            self._multitasking_roll = random.random()
        return self._multitasking_roll

    @componentmethod
    def reset_multitasking_roll(self, interaction=None):
        if interaction is None or (interaction.source is InteractionSource.PIE_MENU or interaction.source is InteractionSource.AUTONOMY) or interaction.source is InteractionSource.SCRIPT:
            self._multitasking_roll = UNSET

    @componentmethod
    def on_sim_reset(self, is_kill):
        self.invalidate_mixer_interaction_cache(None)
        if self._full_autonomy_request is not None:
            self._full_autonomy_request.valid = False
        if is_kill:
            self._autonomy_enabled = False
            self._destroy_full_autonomy_alarm()
        if self._full_autonomy_element_handle is not None:
            self._full_autonomy_element_handle.trigger_hard_stop()
            self._full_autonomy_element_handle = None

    @componentmethod
    def run_full_autonomy_next_ping(self):
        self._last_user_directed_action_time = None
        self._schedule_next_full_autonomy_update(TimeSpan(1))

    @componentmethod
    def set_last_user_directed_action_time(self, to_reschedule_autonomy=True):
        now = services.time_service().sim_now
        logger.debug('Setting user-directed action time for {} to {}', self.owner, now)
        self._last_user_directed_action_time = now
        self._last_autonomy_result_was_none = False
        if to_reschedule_autonomy:
            self._schedule_next_full_autonomy_update()

    @componentmethod
    def set_last_autonomous_action_time(self, to_reschedule_autonomy=True):
        now = services.time_service().sim_now
        logger.debug('Setting last autonomous action time for {} to {}', self.owner, now)
        self._last_autonomous_action_time = now
        self._last_autonomy_result_was_none = False
        if to_reschedule_autonomy:
            self._schedule_next_full_autonomy_update()

    @componentmethod
    def set_last_no_result_time(self, to_reschedule_autonomy=True):
        now = services.time_service().sim_now
        logger.debug('Setting last no-result time for {} to {}', self.owner, now)
        self._last_no_result_time = now
        if to_reschedule_autonomy:
            self._schedule_next_full_autonomy_update()

    @componentmethod
    def skip_autonomy(self, si, to_skip):
        if si.source == InteractionSource.BODY_CANCEL_AOP or si.source == InteractionSource.CARRY_CANCEL_AOP or si.source == InteractionSource.SOCIAL_ADJUSTMENT:
            return
        if to_skip:
            logger.debug('Skipping autonomy for {} due to {}', self.owner, si)
            self._autonomy_skip_sis.add(si)
        else:
            if si in self._autonomy_skip_sis:
                self._autonomy_skip_sis.remove(si)
            logger.debug('Unskipping autonomy for {} due to {}; {} is left.', self.owner, si, self._autonomy_skip_sis)

    def _get_last_user_directed_action_time(self):
        return self._last_user_directed_action_time

    def _get_last_autonomous_action_time(self):
        return self._last_autonomous_action_time

    def _get_last_no_result_time(self):
        return self._last_no_result_time

    @property
    def _last_autonomy_result_was_none(self):
        return self._last_no_result_time is not None

    @_last_autonomy_result_was_none.setter
    def _last_autonomy_result_was_none(self, value):
        if value == True:
            self.set_last_no_result_time(to_reschedule_autonomy=False)
        else:
            self._last_no_result_time = None

    @componentmethod
    def to_skip_autonomy(self):
        return bool(self._autonomy_skip_sis)

    @componentmethod
    def clear_all_autonomy_skip_sis(self):
        self._autonomy_skip_sis.clear()

    @componentmethod
    def is_player_active(self):
        if self._get_last_user_directed_action_time() is None:
            return False
        delta = services.time_service().sim_now - self._get_last_user_directed_action_time()
        if delta >= AutonomyMode.get_autonomy_delay_after_user_interaction():
            return False
        return True

    @componentmethod
    def get_time_until_next_update(self, mode=FullAutonomy):
        time_to_run_autonomy = None
        if self.is_player_active():
            time_to_run_autonomy = self._get_last_user_directed_action_time() + mode.get_autonomy_delay_after_user_interaction()
        elif self._last_autonomy_result_was_none:
            time_to_run_autonomy = self._get_last_no_result_time() + mode.get_no_result_delay_time()
        elif self.owner.si_state.has_visible_si(ignore_pending_complete=True) or self.owner.transition_controller is not None and self.owner.transition_controller.interaction.visible and not self.owner.transition_controller.interaction.is_finishing or self.owner.queue.visible_len() > 0:
            time_to_run_autonomy = self._get_last_autonomous_action_time() + mode.get_autonomous_delay_time()
        else:
            time_to_run_autonomy = self._get_last_autonomous_action_time() + mode.get_autonomous_update_delay_with_no_primary_sis()
        delta_time = time_to_run_autonomy - services.time_service().sim_now
        if delta_time.in_ticks() <= 0:
            delta_time = TimeSpan(1)
        return delta_time

    @componentmethod
    def run_preroll_autonomy(self, ignored_objects):
        sim = self.owner
        sim_info = sim.sim_info
        current_away_action = sim_info.current_away_action
        if current_away_action is not None:
            commodity_list = current_away_action.get_commodity_preroll_list()
            static_commodity_list = current_away_action.get_static_commodity_preroll_list()
        else:
            commodity_list = None
            static_commodity_list = None
        autonomy_request = AutonomyRequest(self.owner, autonomy_mode=FullAutonomy, commodity_list=commodity_list, static_commodity_list=static_commodity_list, skipped_affordance_list=self.PREROLL_AUTONOMY_AFFORDANCE_SKIP_SET, distance_estimation_behavior=AutonomyDistanceEstimationBehavior.IGNORE_DISTANCE, ignored_object_list=ignored_objects, limited_autonomy_allowed=False, autonomy_mode_label_override='PrerollAutonomy')
        selected_interaction = services.autonomy_service().find_best_action(autonomy_request)
        if selected_interaction is None:
            return (None, None)
        if self._push_interaction(selected_interaction):
            return (selected_interaction.affordance, selected_interaction.target)
        return (None, None)

    @componentmethod
    def invalidate_mixer_interaction_cache(self, _):
        for interaction in self._cached_mixer_interactions:
            interaction.invalidate()
        self._cached_mixer_interactions.clear()

    def _should_run_cached_interaction(self, interaction_to_run):
        if interaction_to_run is None:
            return False
        super_interaction = interaction_to_run.super_interaction
        if super_interaction is None or super_interaction.is_finishing:
            return False
        if super_interaction.phase_index is not None and interaction_to_run.affordance not in super_interaction.all_affordances_gen(phase_index=super_interaction.phase_index):
            return False
        if interaction_to_run.is_finishing:
            return False
        if self.owner.is_sub_action_locked_out(interaction_to_run.affordance, interaction_to_run.target):
            return False
        return interaction_to_run.test()

    @componentmethod
    def run_subaction_autonomy(self):
        if not SubActionAutonomy.test(self.owner):
            if gsi_handlers.autonomy_handlers.archiver.enabled:
                gsi_handlers.autonomy_handlers.archive_autonomy_data(self.owner, 'None - Autonomy Disabled', 'SubActionAutonomy', gsi_handlers.autonomy_handlers.EMPTY_ARCHIVE)
            return EnqueueResult.NONE
        attempt_to_use_cache = False
        if gsi_handlers.autonomy_handlers.archiver.enabled:
            caching_info = []
        else:
            caching_info = None
        while self._cached_mixer_interactions:
            attempt_to_use_cache = True
            interaction_to_run = self._cached_mixer_interactions.pop(0)
            if self._should_run_cached_interaction(interaction_to_run):
                enqueue_result = AffordanceObjectPair.execute_interaction(interaction_to_run)
                if enqueue_result:
                    if gsi_handlers.autonomy_handlers.archiver.enabled:
                        gsi_handlers.autonomy_handlers.archive_autonomy_data(self.owner, 'Using Cache: {}'.format(interaction_to_run), 'SubActionAutonomy', gsi_handlers.autonomy_handlers.EMPTY_ARCHIVE)
                    return enqueue_result
            if interaction_to_run:
                interaction_to_run.invalidate()
            while caching_info is not None:
                caching_info.append('Failed to use cache interaction: {}'.format(interaction_to_run))
                continue
        if caching_info is not None and attempt_to_use_cache:
            caching_info.append('Cache invalid:Regenerating')
        self.invalidate_mixer_interaction_cache(None)
        context = InteractionContext(self.owner, InteractionSource.AUTONOMY, Priority.Low)
        autonomy_request = AutonomyRequest(self.owner, context=context, consider_scores_of_zero=True, autonomy_mode=SubActionAutonomy)
        if caching_info is not None:
            caching_info.append('Caching: Mixers - START')
        initial_probability_result = None
        while len(self._cached_mixer_interactions) < self.MIXERS_TO_CACHE:
            interaction = services.autonomy_service().find_best_action(autonomy_request, consider_all_options=True, archive_if_enabled=False)
            if interaction is None:
                break
            if caching_info is not None:
                caching_info.append('caching interaction: {}'.format(interaction))
                if initial_probability_result is None:
                    initial_probability_result = list(autonomy_request.gsi_data['Probability'])
            self._cached_mixer_interactions.append(interaction)
        if caching_info is not None:
            caching_info.append('Caching: Mixers - DONE')
        if self._cached_mixer_interactions:
            interaction = self._cached_mixer_interactions.pop(0)
            if caching_info is not None:
                caching_info.append('Executing mixer: {}'.format(interaction))
            enqueue_result = AffordanceObjectPair.execute_interaction(interaction)
            if caching_info is not None:
                autonomy_request.gsi_data['caching_info'] = caching_info
                autonomy_request.gsi_data['Probability'] = initial_probability_result
                if enqueue_result:
                    result_info = str(interaction)
                else:
                    result_info = 'None - failed to execute: {}'.format(interaction)
                gsi_handlers.autonomy_handlers.archive_autonomy_data(autonomy_request.sim, result_info, autonomy_request.autonomy_mode_label, autonomy_request.gsi_data)
            return enqueue_result
        return EnqueueResult.NONE

    @componentmethod
    def add_role(self, role_state_type, role_affordance_target=None):
        for role_state in self._role_tracker:
            while isinstance(role_state, role_state_type):
                logger.error('Trying to add duplicate role:{}. Returning current instantiated role.', role_state_type)
                return role_state
        role_state = role_state_type(self.owner)
        self._role_tracker.add_role(role_state, role_affordance_target=role_affordance_target)
        return role_state

    @componentmethod
    def remove_role(self, role_state):
        return self._role_tracker.remove_role(role_state)

    @componentmethod
    def remove_role_of_type(self, role_state_type):
        for role_state_priority in self._role_tracker:
            for role_state in role_state_priority:
                while isinstance(role_state, role_state_type):
                    self.remove_role(role_state)
                    return True
        return False

    @componentmethod
    def active_roles(self):
        return self._role_tracker.active_role_states

    @componentmethod
    def reset_role_tracker(self):
        self._role_tracker.reset()

    @componentmethod
    def update_sleep_schedule(self):
        self._remove_sleep_schedule_buff()
        for alarm_handle in self._sleep_buff_alarms.keys():
            alarms.cancel_alarm(alarm_handle)
        self._sleep_buff_alarms.clear()
        time_span_until_wakeup = self.get_time_until_next_wakeup()
        most_appropriate_buff = None
        for sleep_schedule_entry in sorted(self.SLEEP_SCHEDULE.schedule, key=lambda entry: entry.time_from_work_start, reverse=True):
            if time_span_until_wakeup.in_hours() <= sleep_schedule_entry.time_from_work_start:
                most_appropriate_buff = sleep_schedule_entry.buff
            else:
                time_until_buff_alarm = time_span_until_wakeup - date_and_time.create_time_span(hours=sleep_schedule_entry.time_from_work_start)
                alarm_handle = alarms.add_alarm(self, time_until_buff_alarm, self._add_buff_callback, True, date_and_time.create_time_span(hours=date_and_time.HOURS_PER_DAY))
                self._sleep_buff_alarms[alarm_handle] = sleep_schedule_entry.buff
        if most_appropriate_buff and most_appropriate_buff.buff_type:
            self._sleep_buff_handle = self.owner.add_buff(most_appropriate_buff.buff_type)
        if self._sleep_buff_reset:
            alarms.cancel_alarm(self._sleep_buff_reset)
        self._sleep_buff_reset = alarms.add_alarm(self, time_span_until_wakeup, self._reset_alarms_callback)

    @componentmethod
    def get_time_until_next_wakeup(self, offset_time:TimeSpan=None):
        now = services.time_service().sim_now
        time_span_until_wakeup = None
        sim_careers = self.owner.sim_info.career_tracker.careers
        if sim_careers:
            earliest_time = None
            for career in sim_careers.values():
                wakeup_time = career.get_next_wakeup_time()
                while earliest_time is None or wakeup_time < earliest_time:
                    earliest_time = wakeup_time
            if earliest_time is not None:
                time_span_until_wakeup = now.time_till_next_day_time(earliest_time)
        if time_span_until_wakeup is None:
            start_time = self._get_default_sleep_schedule_work_time(offset_time)
            time_span_until_wakeup = start_time - now
        if time_span_until_wakeup.in_ticks() <= 0:
            time_span_until_wakeup += TimeSpan(date_and_time.sim_ticks_per_day())
            logger.assert_log(time_span_until_wakeup.in_ticks() > 0, 'time_span_until_wakeup occurs in the past.')
        return time_span_until_wakeup

    def _add_buff_callback(self, alarm_handle):
        buff = self._sleep_buff_alarms.get(alarm_handle)
        if not buff:
            logger.error("Couldn't find alarm handle in _sleep_buff_alarms dict for sim:{}.", self.owner, owner='rez')
            return
        self._remove_sleep_schedule_buff()
        if buff and buff.buff_type:
            self._sleep_buff_handle = self.owner.add_buff(buff.buff_type)

    def _reset_alarms_callback(self, _):
        self.update_sleep_schedule()

    def _remove_sleep_schedule_buff(self):
        if self._sleep_buff_handle is not None:
            self.owner.remove_buff(self._sleep_buff_handle)
            self._sleep_buff_handle = None

    def _get_default_sleep_schedule_work_time(self, offset_time):
        now = services.time_service().sim_now
        if offset_time is not None:
            now += offset_time
        work_time = date_and_time.create_date_and_time(days=int(now.absolute_days()), hours=self.SLEEP_SCHEDULE.default_work_time.hour(), minutes=self.SLEEP_SCHEDULE.default_work_time.minute())
        if work_time < now:
            work_time += date_and_time.create_time_span(days=1)
        return work_time

    @componentmethod
    def get_autonomy_state_setting(self) -> autonomy.settings.AutonomyState:
        return self._get_appropriate_autonomy_setting(autonomy.settings.AutonomyState)

    @componentmethod
    def get_autonomy_randomization_setting(self) -> autonomy.settings.AutonomyRandomization:
        return self._get_appropriate_autonomy_setting(autonomy.settings.AutonomyRandomization)

    @componentmethod
    def get_autonomy_settings(self):
        return self._autonomy_settings

    def _get_appropriate_autonomy_setting(self, setting_class):
        autonomy_service = services.autonomy_service()
        setting = autonomy_service.global_autonomy_settings.get_setting(setting_class)
        if setting != setting_class.UNDEFINED:
            return setting
        if self._role_tracker is not None:
            setting = self._role_tracker.get_autonomy_state()
            if setting != setting_class.UNDEFINED:
                return setting
        setting = self._autonomy_settings.get_setting(setting_class)
        if setting != setting_class.UNDEFINED:
            return setting
        household = self.owner.household
        if household:
            setting = household.autonomy_settings.get_setting(setting_class)
            if setting != setting_class.UNDEFINED:
                return setting
        setting = autonomy_service.default_autonomy_settings.get_setting(setting_class)
        if setting == setting_class.UNDEFINED:
            logger.error('Sim {} has an UNDEFINED autonomy setting!', self.owner, owner='rez')
        return setting

    def save(self, persistence_master_message):
        pass

    def load(self, state_component_message):
        pass

    @componentmethod
    def debug_reset_autonomy_alarm(self):
        self._schedule_next_full_autonomy_update()

    @componentmethod
    def debug_output_autonomy_timers(self, _connection):
        now = services.time_service().sim_now
        if self._last_user_directed_action_time is not None:
            sims4.commands.output('Last User-Directed Action: {} ({} ago)'.format(self._last_user_directed_action_time, now - self._last_user_directed_action_time), _connection)
        else:
            sims4.commands.output('Last User-Directed Action: None', _connection)
        if self._last_autonomous_action_time is not None:
            sims4.commands.output('Last Autonomous Action: {} ({} ago)'.format(self._last_autonomous_action_time, now - self._last_autonomous_action_time), _connection)
        else:
            sims4.commands.output('Last Autonomous Action: None', _connection)
        if self._full_autonomy_alarm_handle is not None:
            sims4.commands.output('Full Autonomy: {} from now'.format(self._full_autonomy_alarm_handle.get_remaining_time()), _connection)
        else:
            sims4.commands.output('Full Autonomy: None)', _connection)
        if len(self._autonomy_skip_sis) > 0:
            sims4.commands.output("Skipping autonomy due to the follow SI's:", _connection)
            for si in self._autonomy_skip_sis:
                sims4.commands.output('\t{}'.format(si), _connection)
        else:
            sims4.commands.output('Not skipping autonomy', _connection)

    @componentmethod
    def debug_get_autonomy_timers_gen(self):
        now = services.time_service().sim_now
        if self._full_autonomy_alarm_handle is not None:
            yield ('Full Autonomy', '{}'.format(self._full_autonomy_alarm_handle.get_remaining_time()))
        else:
            yield ('Full Autonomy', 'None')
        if self._last_user_directed_action_time is not None:
            yield ('Last User-Directed Action', '{} ({} ago)'.format(self._last_user_directed_action_time, now - self._last_user_directed_action_time))
        if self._last_autonomous_action_time:
            yield ('Last Autonomous Action', '{} ({} ago)'.format(self._last_autonomous_action_time, now - self._last_autonomous_action_time))
        if len(self._autonomy_skip_sis) > 0:
            yield ('Skipping Autonomy?', 'True')
        else:
            yield ('Skipping Autonomy?', 'False')

    @componentmethod
    def debug_update_autonomy_timer(self, mode):
        self._schedule_next_full_autonomy_update()

class TunableAutonomyComponent(TunableFactory):
    __qualname__ = 'TunableAutonomyComponent'
    FACTORY_TYPE = AutonomyComponent

    def __init__(self, callback=None, **kwargs):
        super().__init__(description='Autonomy state', **kwargs)

class TunableParameterizedAutonomy(TunableTuple, is_fragment=True):
    __qualname__ = 'TunableParameterizedAutonomy'

    def __init__(self):
        super().__init__(commodities=TunableSet(TunableReference(services.statistic_manager(), description='The type of commodity to search for.'), description='List of commodities to run parameterized autonomy against after running this interaction.'), static_commodities=TunableSet(TunableReference(services.static_commodity_manager(), description='The type of static commodity to search for.'), description='List of static commodities to run parameterized autonomy against after running this interaction.'), same_target_only=Tunable(bool, False, description='If checked, only interactions on the same target as this interaction will be considered.'), retain_priority=Tunable(bool, True, needs_tuning=True, description='If checked, this autonomy request is run at the same priority level as the interaction creating it.  If unchecked, the interaction chosen will run at low priority.'), consider_same_target=Tunable(bool, True, description='If checked, parameterized autonomy will consider interactions on the current Target.'), retain_carry_target=Tunable(bool, True, description="If checked, the interactions considered for autonomy will retain this interaction's carry target. It is useful to uncheck this if the desired autonomous interactions need not to consider carry, e.g. the Grim Reaper finding arbitrary interactions while in an interaction holding his scythe as a carry target."), randomization_override=OptionalTunable(description='\n                    If enabled then the parameterized autonomy will run with\n                    an overwritten autonomy randomization settings.\n                    ', tunable=TunableEnumEntry(description='\n                        The autonomy randomization setting that will be used.\n                        ', tunable_type=AutonomyRandomization, default=AutonomyRandomization.UNDEFINED)), radius_to_consider=Tunable(description='\n                    The radius around the sim that targets must be in to be valid for Parameterized \n                    Autonomy.  Anything outside this radius will be ignored.  A radius of 0 is considered\n                    infinite.\n                    ', tunable_type=float, default=0), consider_scores_of_zero=Tunable(description='\n                    The autonomy request will consider scores of zero.  This allows sims to to choose things they \n                    might not desire.\n                    ', tunable_type=bool, default=False), description='Commodities and StaticCommodities will be combined, so interactions must support at least one commodity from both lists.')

