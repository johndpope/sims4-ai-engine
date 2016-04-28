from collections import namedtuple
from contextlib import contextmanager
import itertools
import operator
import random
import weakref
from protocolbuffers import Consts_pb2, DistributorOps_pb2
from protocolbuffers.Dialog_pb2 import UiCareerNotificationArgs
from protocolbuffers.DistributorOps_pb2 import Operation
import protocolbuffers
from audio.primitive import play_tunable_audio
from careers.retirement import Retirement
from date_and_time import create_time_span, DateAndTime, TimeSpan, DATE_AND_TIME_ZERO, MINUTES_PER_HOUR
from distributor.ops import GenericProtocolBufferOp
from distributor.rollback import ProtocolBufferRollback
from distributor.system import Distributor
from event_testing import test_events
from event_testing.resolver import SingleSimResolver
from event_testing.results import EnqueueResult
from interactions.aop import AffordanceObjectPair
from interactions.context import QueueInsertStrategy
from objects import ALL_HIDDEN_REASONS
from sims.sim_outfits import OutfitChangeReason
from sims4 import math
from sims4.localization import LocalizationHelperTuning
from sims4.math import Threshold
from situations.situation_guest_list import SituationGuestInfo, SituationInvitationPurpose, SituationGuestList
from situations.situation_types import SituationCallbackOption
import alarms
import clock
import date_and_time
import distributor.shared_messages
import interactions.context
import services
import sims4.log
import telemetry_helper
TELEMETRY_GROUP_CAREERS = 'CARE'
TELEMETRY_HOOK_CAREER_START = 'CAST'
TELEMETRY_HOOK_CAREER_END = 'CAEN'
TELEMETRY_HOOK_CAREER_PROMOTION = 'CAUP'
TELEMETRY_HOOK_CAREER_DEMOTION = 'CADW'
TELEMETRY_HOOK_CAREER_DAILY_END = 'CADA'
TELEMETRY_CAREER_ID = 'caid'
TELEMETRY_CAREER_LEVEL = 'leve'
TELEMETRY_CAREER_DAILY_PERFORMANCE = 'poin'
TELEMETRY_TRACK_ID = 'trid'
TELEMETRY_TRACK_LEVEL = 'trlv'
career_telemetry_writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_CAREERS)
logger = sims4.log.Logger('Careers')
NO_TIME_DIFFERENCE = date_and_time.TimeSpan.ZERO
PERCENT_FLOAT_CONVERSION = 0.01
CareerHistory = namedtuple('CareerHistory', ['career_level', 'user_level', 'time_left', 'track_uid', 'highest_level'])

class CareerBase:
    __qualname__ = 'CareerBase'
    TONE_STAT_MOD = 1

    def __init__(self, sim_info, company_name=None, init_track=False):
        self._sim_info_ref = weakref.ref(sim_info)
        self._level = 0
        self._user_level = 1
        self._join_time = None
        self._current_work_start = None
        self._current_work_end = None
        self._current_work_duration = None
        self._attended_work = False
        self._called_in_sick = False
        self._current_track = None
        if init_track:
            self._current_track = self.start_track
        self._company_name = company_name
        self._auto_work = False
        self._pending_promotion = False
        self._work_scheduler = None
        self._situation_scheduler = None
        self._career_situation_id = 0
        self._career_situation = None
        self._career_situation_alarm = None
        self._end_work_handle = None
        self._late_for_work_handle = None
        self._interaction = None
        self._statistic_down_listeners = {}
        self._statistic_up_listeners = {}

    def _get_sim(self):
        return self._sim_info_ref().get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)

    @property
    def _sim_info(self):
        return self._sim_info_ref()

    @property
    def current_level_tuning(self):
        return self._current_track.career_levels[self._level]

    @property
    def current_track_tuning(self):
        return self._current_track

    @property
    def level(self):
        return self._level

    @property
    def user_level(self):
        return self._user_level

    @property
    def work_performance(self):
        performance_stat = self._sim_info.statistic_tracker.get_statistic(self.current_level_tuning.performance_stat)
        if performance_stat is not None:
            return performance_stat.get_value()
        return 0

    @property
    def work_performance_stat(self):
        performance_stat = self._sim_info.statistic_tracker.get_statistic(self.current_level_tuning.performance_stat)
        if performance_stat is not None:
            return performance_stat
        logger.error('Career: Missing work performance stat. Sim:{} Career: {}', self._sim_info, self, owner='tingyul')

    @property
    def attended_work(self):
        return self._attended_work

    @property
    def called_in_sick(self):
        return self._called_in_sick

    @property
    def currently_at_work(self):
        return self._attended_work

    @property
    def is_late(self):
        if not self.is_work_time or self.attended_work:
            return False
        late_time = self.get_late_time()
        if late_time is None:
            return False
        now = services.time_service().sim_now
        if now < late_time:
            return False
        return True

    @property
    def is_work_time(self):
        if self._current_work_start is None:
            return False
        current_time = services.time_service().sim_now
        if current_time.time_between_week_times(self._current_work_start, self._current_work_end):
            return True
        return False

    def get_late_time(self):
        if not self.is_work_time:
            return
        time_before_late = self._current_work_duration*(1 - self.current_level_tuning.performance_metrics.full_work_day_percent*PERCENT_FLOAT_CONVERSION)
        late_time = self._current_work_start + time_before_late
        return late_time

    def get_work_state(self):
        if self.is_work_time:
            if self.currently_at_work:
                return DistributorOps_pb2.SetAtWorkInfo.WORKDAY_ATTENDING
            if self.is_late:
                return DistributorOps_pb2.SetAtWorkInfo.WORKDAY_LATE
            return DistributorOps_pb2.SetAtWorkInfo.WORKDAY_AVAILABLE
        return DistributorOps_pb2.SetAtWorkInfo.WORKDAY_OVER

    @property
    def company_name(self):
        return self._company_name

    @property
    def auto_work(self):
        return self._auto_work

    @property
    def active_situation_id(self):
        return self._career_situation_id

    def call_in_sick(self):
        self._called_in_sick = True
        self.resend_career_data()

    def resend_career_data(self):
        self._sim_info.career_tracker.resend_career_data()

    def resend_at_work_info(self):
        self._sim_info.career_tracker.resend_at_work_infos()
        client = services.client_manager().get_client_by_household_id(self._sim_info._household_id)
        if client is not None:
            client.selectable_sims.notify_dirty()

    def get_career_entry_level(self, career_history=None, resolver=None):
        if career_history is None or self.guid64 not in career_history:
            level = int(self.start_level_modifiers.get_max_modifier(resolver))
            max_level = len(self.start_track.career_levels)
            level = sims4.math.clamp(0, level, max_level - 1)
            return (level, level + 1, None)
        history = career_history[self.guid64]
        new_level = history.career_level
        new_user_level = history.user_level
        time_left = history.time_left
        current_track_uid = history.track_uid
        current_track = services.get_instance_manager(sims4.resources.Types.CAREER_TRACK).get(current_track_uid)
        new_level -= self.levels_lost_on_leave
        new_user_level -= self.levels_lost_on_leave
        current_time = services.time_service().sim_now
        time_gone_from_career = current_time - time_left
        days_gone_from_career = time_gone_from_career.in_days()
        if self.days_to_level_loss > 0:
            levels_to_lose = int(days_gone_from_career/self.days_to_level_loss)
            new_level -= levels_to_lose
            new_user_level -= levels_to_lose
        if new_level < 0:
            new_level = 0
        if new_user_level < 1:
            new_user_level = 1
        return (new_level, new_user_level, current_track)

    def get_next_wakeup_time(self) -> date_and_time.DateAndTime:
        return self.current_level_tuning.wakeup_time

    def get_next_work_time(self, offset_time=None, check_if_can_go_now=False, consider_job_start_delay=True):
        now = services.time_service().sim_now
        if offset_time:
            now += offset_time
        if self._work_scheduler is None:
            return (None, None, None)
        (best_time, work_data_list) = self._work_scheduler.time_until_next_scheduled_event(now, schedule_immediate=check_if_can_go_now)
        work_data = work_data_list[0]
        start_time = now + best_time
        if consider_job_start_delay:
            valid_start_time = self.get_valid_first_work_day_time()
            if start_time < valid_start_time:
                (best_time, work_data_list) = self._work_scheduler.time_until_next_scheduled_event(valid_start_time, schedule_immediate=False)
                best_time += valid_start_time - now
                work_data = work_data_list[0]
                start_time = now + best_time
        end_time = now.time_of_next_week_time(work_data.end_time)
        return (best_time, start_time, end_time)

    def get_valid_first_work_day_time(self):
        if self._join_time is None:
            return DATE_AND_TIME_ZERO
        return self._join_time + clock.interval_in_sim_minutes(self.JOB_START_DELAY)

    def should_skip_next_shift(self, check_if_can_go_now=False):
        if self._called_in_sick:
            return True
        (_, start, _) = self.get_next_work_time(check_if_can_go_now=check_if_can_go_now, consider_job_start_delay=False)
        if start is None:
            return False
        if start > self.get_valid_first_work_day_time():
            return False
        return True

    def get_is_school(self):
        return isinstance(self, self._sim_info.SCHOOL_CAREER) or isinstance(self, self._sim_info.HIGH_SCHOOL_CAREER)

    def _give_rewards_for_skipped_levels(self):
        level_of_last_reward = self._sim_info.career_tracker.get_highest_level_reached(self.guid64)
        track = self.current_track_tuning
        level = self.level
        user_level = self.user_level
        while user_level > level_of_last_reward:
            reward = track.career_levels[level].promotion_reward
            if reward is not None:
                reward.give_reward(self._sim_info)
            user_level -= 1
            level -= 1
            while level < 0:
                if track.parent_track is None:
                    break
                track = track.parent
                level = len(track.career_levels) - 1
                continue

    def join_career(self, career_history=None):
        resolver = SingleSimResolver(self._sim_info)
        (new_level, new_user_level, current_track) = self.get_career_entry_level(career_history=career_history, resolver=resolver)
        self._level = new_level
        self._user_level = new_user_level
        if self._company_name is None:
            self._company_name = self.get_random_company_name_hash()
        if current_track is None:
            self._current_track = self.start_track
        else:
            self._current_track = current_track
        self._join_time = services.time_service().sim_now
        self._reset_career_objectives(self._current_track, new_level)
        self.career_start()
        loot = self.current_level_tuning.loot_on_join
        if loot is not None:
            resolver = SingleSimResolver(self._sim_info)
            loot.apply_to_resolver(resolver)
        self._give_rewards_for_skipped_levels()
        with telemetry_helper.begin_hook(career_telemetry_writer, TELEMETRY_HOOK_CAREER_START, sim=self._sim_info) as hook:
            hook.write_int(TELEMETRY_CAREER_ID, self.guid64)
            hook.write_int(TELEMETRY_CAREER_LEVEL, self._user_level)
            hook.write_guid(TELEMETRY_TRACK_ID, self._current_track.guid64)
            hook.write_int(TELEMETRY_TRACK_LEVEL, new_level)
        if not self.get_is_school():
            (_, first_work_time, _) = self.get_next_work_time()
            self.send_career_message(self.career_messages.join_career_notification, first_work_time)

    def career_start(self, is_load=False):
        if self.current_level_tuning.situation_schedule is not None:
            self._situation_scheduler = self.current_level_tuning.situation_schedule(start_callback=self._career_situation_callback, schedule_immediate=False)
        if self.current_level_tuning.work_schedule is not None:
            if self.career_messages.career_early_warning_time is not None:
                early_warning_time_span = date_and_time.create_time_span(hours=self.career_messages.career_early_warning_time)
            else:
                early_warning_time_span = None
            self._work_scheduler = self.current_level_tuning.work_schedule(start_callback=self._start_work_callback, schedule_immediate=False, early_warning_callback=self._early_warning_callback, early_warning_time_span=early_warning_time_span)
        self._add_performance_statistics()
        if is_load:
            self.restore_career_session()
            self.restore_tones()
        else:
            if self.current_level_tuning.work_outfit.outfit_tags:
                self._sim_info.generate_career_outfit(tag_list=list(self.current_level_tuning.work_outfit.outfit_tags))
            sim = self._get_sim()
            if sim is not None:
                sim.update_sleep_schedule()
            services.get_event_manager().process_event(test_events.TestEvent.CareerEvent, sim_info=self._sim_info, career=self)
        self._add_statistic_metric_listeners()

    def career_stop(self):
        if self._situation_scheduler is not None:
            self._situation_scheduler.destroy()
            self._situation_scheduler = None
        if self._work_scheduler is not None:
            self._work_scheduler.destroy()
            self._work_scheduler = None
        self._career_situation_id = 0
        self._career_situation = None
        if self._career_situation_alarm is not None:
            alarms.cancel_alarm(self._career_situation_alarm)
            self._career_situation_alarm = None
        if self._end_work_handle is not None:
            alarms.cancel_alarm(self._end_work_handle)
            self._end_work_handle = None
        if self._late_for_work_handle is not None:
            alarms.cancel_alarm(self._late_for_work_handle)
            self._late_for_work_handle = None
        self._remove_performance_statistics()
        self._remove_statistic_metric_listeners()

    def _add_performance_statistics(self):
        tuning = self.current_level_tuning
        sim_info = self._sim_info
        tracker = sim_info.get_tracker(tuning.performance_stat)
        tracker.add_statistic(tuning.performance_stat)
        for metric in tuning.performance_metrics.statistic_metrics:
            tracker = sim_info.get_tracker(metric.statistic)
            tracker.add_statistic(metric.statistic)

    def _remove_performance_statistics(self):
        tuning = self.current_level_tuning
        sim_info = self._sim_info
        sim_info.remove_statistic(tuning.performance_stat)
        for metric in tuning.performance_metrics.statistic_metrics:
            sim_info.remove_statistic(metric.statistic)

    def _reset_performance_statistics(self):
        tuning = self.current_level_tuning
        sim_info = self._sim_info
        sim_info.remove_statistic(self.WORK_SESSION_PERFORMANCE_CHANGE)
        for metric in tuning.performance_metrics.statistic_metrics:
            while metric.reset_at_end_of_work:
                tracker = sim_info.get_tracker(metric.statistic)
                tracker.set_value(metric.statistic, metric.statistic.initial_value)

    def _on_statistic_metric_changed(self, stat_type):
        self.resend_career_data()
        self._refresh_statistic_metric_listeners()

    def _add_statistic_metric_listeners(self):
        metrics = self.current_level_tuning.performance_metrics
        for metric in metrics.statistic_metrics:
            tracker = self._sim_info.get_tracker(metric.statistic)
            value = tracker.get_value(metric.statistic)
            (lower_threshold, upper_threshold) = self._get_statistic_progress_thresholds(metric.statistic, value)
            if lower_threshold:
                threshold = Threshold(lower_threshold.threshold, operator.lt)
                handle = tracker.create_and_activate_listener(metric.statistic, threshold, self._on_statistic_metric_changed)
                self._statistic_down_listeners[metric.statistic] = handle
            while upper_threshold:
                threshold = Threshold(upper_threshold.threshold, operator.ge)
                handle = tracker.create_and_activate_listener(metric.statistic, threshold, self._on_statistic_metric_changed)
                self._statistic_up_listeners[metric.statistic] = handle

    def _remove_statistic_metric_listeners(self):
        for (stat_type, handle) in itertools.chain(self._statistic_down_listeners.items(), self._statistic_up_listeners.items()):
            tracker = self._sim_info.get_tracker(stat_type)
            tracker.remove_listener(handle)
        self._statistic_down_listeners = {}
        self._statistic_up_listeners = {}

    def _refresh_statistic_metric_listeners(self):
        self._remove_statistic_metric_listeners()
        self._add_statistic_metric_listeners()

    def _get_performance_tooltip(self):
        loc_strings = []
        metrics = self.current_level_tuning.performance_metrics
        if metrics.performance_tooltip is not None:
            loc_strings.append(metrics.performance_tooltip)
        for metric in metrics.statistic_metrics:
            text = metric.tooltip_text
            while text is not None:
                if text.general_description:
                    lower_threshold = None
                    stat = self._sim_info.get_statistic(metric.statistic)
                    if stat is not None:
                        (lower_threshold, _) = self._get_statistic_progress_thresholds(stat.stat_type, stat.get_value())
                    if lower_threshold:
                        description = text.general_description(lower_threshold.text)
                    else:
                        description = text.general_description()
                    loc_strings.append(description)
        if loc_strings:
            return LocalizationHelperTuning.get_new_line_separated_strings(*loc_strings)

    def _get_statistic_progress_thresholds(self, stat_type, value):
        metrics = self.current_level_tuning.performance_metrics
        for metric in metrics.statistic_metrics:
            while metric.statistic is stat_type:
                text = metric.tooltip_text
                if text is not None:
                    lower_threshold = None
                    upper_threshold = None
                    for threshold in text.thresholded_descriptions:
                        if value >= threshold.threshold and (lower_threshold is None or threshold.threshold > lower_threshold.threshold):
                            lower_threshold = threshold
                        while value < threshold.threshold and (upper_threshold is None or threshold.threshold < upper_threshold.threshold):
                            upper_threshold = threshold
                    return (lower_threshold, upper_threshold)
                break
        return (None, None)

    def apply_performance_change(self, time_elapsed, tone_multiplier):
        metrics = self.current_level_tuning.performance_metrics
        gain = 0
        loss = 0

        def add_metric(value):
            nonlocal gain, loss
            if value >= 0:
                gain += value
            else:
                loss -= value

        add_metric(metrics.base_performance)
        for commodity_metric in metrics.commodity_metrics:
            tracker = self._sim_info.get_tracker(commodity_metric.commodity)
            curr_value = tracker.get_user_value(commodity_metric.commodity)
            while curr_value is not None and commodity_metric.threshold.compare(curr_value):
                add_metric(commodity_metric.performance_mod)
        for mood_metric in metrics.mood_metrics:
            while self._sim_info.get_mood() is mood_metric.mood:
                add_metric(mood_metric.performance_mod)
                break
        for metric in metrics.statistic_metrics:
            while metric.performance_curve is not None:
                stat = self._sim_info.get_statistic(metric.statistic, add=False)
                if stat is not None:
                    stat_value = stat.get_value()
                    performance_mod = metric.performance_curve.get(stat_value)
                    add_metric(performance_mod)
        if metrics.tested_metrics:
            resolver = SingleSimResolver(self._sim_info)
            for metric in metrics.tested_metrics:
                while metric.tests.run_tests(resolver):
                    add_metric(metric.performance_mod)
        completed_objectives = 0
        promotion_milestone = self.current_level_tuning.aspiration
        if promotion_milestone is not None:
            for objective in promotion_milestone.objectives:
                while self._sim_info.aspiration_tracker.objective_completed(objective.guid64):
                    completed_objectives += 1
        objective_mod = completed_objectives*metrics.performance_per_completed_goal
        add_metric(objective_mod)
        total = gain*tone_multiplier - loss
        delta = total*time_elapsed.in_ticks()/self._current_work_duration.in_ticks()
        self.work_performance_stat.add_value(delta)
        session_stat = self._sim_info.statistic_tracker.get_statistic(self.WORK_SESSION_PERFORMANCE_CHANGE)
        session_stat.add_value(delta)

    def get_busy_time_periods(self):
        busy_times = []
        busy_times.extend(self._work_scheduler.get_schedule_times())
        for time_period in self.current_level_tuning.additional_unavailable_times:
            start_time = time_period.start_time()
            end_time = start_time + clock.interval_in_sim_hours(time_period.period_duration)
            busy_times.append((start_time.absolute_ticks(), end_time.absolute_ticks()))
        return busy_times

    def _early_warning_callback(self):
        if self.should_skip_next_shift():
            return
        if self._sim_info.is_selectable and self.career_messages.career_early_warning_notification is not None:
            self.send_career_message(self.career_messages.career_early_warning_notification)

    def _career_missing_work_response(self, dialog):
        if not dialog.accepted:
            return
        sim = self._sim_info.get_sim_instance()
        if sim is None:
            return
        context = interactions.context.InteractionContext(sim, interactions.context.InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT, interactions.priority.Priority.High, insert_strategy=interactions.context.QueueInsertStrategy.NEXT, bucket=interactions.context.InteractionBucketType.DEFAULT)
        sim.push_super_affordance(self.career_messages.career_missing_work.affordance, sim, context)

    def _late_for_work_callback(self, _):
        self.resend_at_work_info()
        sim = self._sim_info.get_sim_instance()
        if sim is not None:
            affordance = self.get_work_affordance()
            if sim.queue.has_duplicate_super_affordance(affordance, sim, sim):
                return
        self.send_career_message(self.career_messages.career_missing_work.dialog, on_response=self._career_missing_work_response)

    def _start_work_callback(self, scheduler, alarm_data, extra_data):
        logger.debug('My Work Time just triggered!!, Current Time:{}', services.time_service().sim_now)
        is_npc = self._sim_info.is_npc
        if self.should_skip_next_shift(check_if_can_go_now=True):
            self._called_in_sick = False
            self.resend_career_data()
            return
        if is_npc:
            sim = self._get_sim()
            services.get_zone_situation_manager().make_sim_leave_now_must_run(sim)
        else:
            now = services.time_service().sim_now
            work_duration = alarm_data.start_time.time_to_week_time(alarm_data.end_time)
            self.start_new_career_session(now, now + work_duration)
            sim = self._get_sim()
            if sim is not None:
                self.push_go_to_work_affordance()
            else:
                self.attend_work()

    def _end_work_callback(self, _):
        if self._interaction is not None and self._interaction() is not None:
            return
        if self.attended_work:
            self.leave_work()
        else:
            time_at_work = self._current_work_duration.in_hours() if self._called_in_sick else 0
            if not self._sim_info.is_npc:
                self.handle_career_loot(time_at_work)
            self.end_career_session()

    def _create_work_session_alarms(self):
        self._end_work_handle = alarms.add_alarm(self, self.time_until_end_of_work() + TimeSpan.ONE, self._end_work_callback)
        if not self.attended_work:
            now = services.time_service().sim_now
            late_time = self.get_late_time()
            if now < late_time:
                self._late_for_work_handle = alarms.add_alarm(self, late_time - now + TimeSpan.ONE, self._late_for_work_callback)

    def start_new_career_session(self, start_time, end_time):
        self.set_career_situation_available(False)
        self._current_work_start = start_time
        self._current_work_end = end_time
        self._current_work_duration = self._current_work_end - self._current_work_start
        self._attended_work = False
        self._create_work_session_alarms()
        self.resend_at_work_info()
        self._sim_info.add_statistic(self.WORK_SESSION_PERFORMANCE_CHANGE, self.WORK_SESSION_PERFORMANCE_CHANGE.initial_value)

    def restore_career_session(self):
        if self.is_work_time:
            self._create_work_session_alarms()

    def end_career_session(self):
        if self._end_work_handle is not None:
            alarms.cancel_alarm(self._end_work_handle)
            self._end_work_handle = None
        if self._late_for_work_handle is not None:
            alarms.cancel_alarm(self._late_for_work_handle)
            self._late_for_work_handle = None
        self._interaction = None
        self._reset_performance_statistics()
        self.set_career_situation_available(True)
        self._current_work_start = None
        self._current_work_end = None
        self._current_work_duration = None
        self._attended_work = False
        self.resend_at_work_info()

    def get_work_affordance(self):
        if self._sim_info.household.home_zone_id == services.current_zone_id():
            return self.career_affordance
        return self.go_home_to_work_affordance

    def push_go_to_work_affordance(self):
        sim = self._get_sim()
        if sim is None:
            return EnqueueResult.NONE
        affordance = self.get_work_affordance()
        context = interactions.context.InteractionContext(sim, interactions.context.InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT, interactions.priority.Priority.High, insert_strategy=QueueInsertStrategy.LAST)
        result = sim.push_super_affordance(affordance, sim, context, career_uid=self.guid64)
        if not result:
            logger.callstack('Failed to push career affordance on Sim {} IsNpc: {} Time: {} Career {}: {}', sim, sim.is_npc, services.time_service().sim_now, self, result, owner='tingyul', level=sims4.log.LEVEL_ERROR)
        return result

    def leave_work_early(self):
        interaction = self._interaction() if self._interaction is not None else None
        if interaction is not None:
            interaction.cancel_user(cancel_reason_msg='User canceled work interaction through UI panel.')
        else:
            self.leave_work()

    def _career_situation_callback(self, scheduler, alarm_data, extra_data):
        if not self._sim_info.is_instanced() or self._sim_info.is_npc:
            return
        num_situations = len(self.current_level_tuning.situation_list)
        if num_situations > 0 and not self.currently_at_work:
            self._career_situation = self.current_level_tuning.situation_list[random.randint(0, num_situations - 1)]
            self.send_career_message(self.career_messages.career_situation_start_notification, self._career_situation)
            self.set_career_situation_available(True)
            self._career_situation_alarm = alarms.add_alarm(self, create_time_span(hours=self._career_situation.available_time), lambda _: self.set_career_situation_available(False))
        self._situation_scheduler.add_cooldown(create_time_span(days=self.current_level_tuning.situation_cooldown))

    def _end_of_situation_scoring(self, situation_id, callback_option, data):
        individual_score = 0
        for sim_job_score in data.sim_job_scores:
            while sim_job_score.sim.sim_id == self._sim_info.sim_id:
                individual_score = sim_job_score.score
                break
        situation_performance = self._career_situation.base_work_performance + self._career_situation.event_modifier*data.situation_score + self._career_situation.individual_modifier*individual_score
        performance_stat = self._sim_info.statistic_tracker.get_statistic(self.current_level_tuning.performance_stat)
        performance_stat.add_value(situation_performance)
        self.evaluate_career_performance()

    def start_career_situation(self):
        if self._career_situation is not None:
            guest_info = SituationGuestInfo.construct_from_purpose(self._sim_info.sim_id, self._career_situation.job, SituationInvitationPurpose.CAREER)
            guest_list = SituationGuestList()
            guest_list.add_guest_info(guest_info)
            situation_manager = services.get_zone_situation_manager()
            situation = self._career_situation.situation
            if not situation.has_venue_location():
                logger.error("Tried starting a career event, career:{}  level:{}, and couldn't find a valid venue. There should ALWAYS be a Maxis Lot tuned for every venue type. - trevorlindsey", self, self.level)
                return False
            zone_id = situation.get_venue_location()
            self._career_situation_id = situation_manager.create_situation(self._career_situation.situation, guest_list=guest_list, zone_id=zone_id)

    def on_joining_active_career_situation(self, situation_id):
        self._career_situation_id = situation_id
        situation_manager = services.get_zone_situation_manager()
        situation_manager.register_for_callback(situation_id, SituationCallbackOption.END_OF_SITUATION_SCORING, self._end_of_situation_scoring)

    def attend_work(self, interaction=None):
        if interaction is not None:
            self._interaction = weakref.ref(interaction)
        if self._attended_work:
            return
        self._attended_work = True
        if self._late_for_work_handle is not None:
            alarms.cancel_alarm(self._late_for_work_handle)
            self._late_for_work_handle = None
        self.send_career_message(self.career_messages.career_daily_start_notification)
        self.resend_at_work_info()
        self.start_tones()

    def leave_work(self, interaction=None):
        if not self._sim_info.is_npc:
            hours_worked = self.get_hours_worked()
            self.handle_career_loot(hours_worked)
        self.end_tones()
        self.end_career_session()

    def time_until_end_of_work(self):
        current_time = services.time_service().sim_now
        time_to_work_end = current_time.time_to_week_time(self._current_work_end)
        return time_to_work_end

    def promote(self):
        with self._handle_promotion():
            while self._change_level(1) and self.promotion_buff is not None:
                self._sim_info.add_buff_from_op(self.promotion_buff.buff_type, buff_reason=self.promotion_buff.buff_reason)

    def demote(self, auto_fire=False):
        if random.random() < self.demotion_chance_modifiers.get_multiplier(SingleSimResolver(self._sim_info)):
            demote_fired = False
            if self.can_be_fired and (auto_fire or self._level - 1 < 0):
                demote_fired = True
                self.send_career_message(self.career_messages.fire_career_notification)
                self._sim_info.career_tracker.remove_career(self.guid64, post_quit_msg=False)
            elif self._change_level(-1):
                self.send_career_message(self.career_messages.demote_career_notification)
            if demote_fired:
                if self.fired_buff is not None:
                    self._sim_info.add_buff_from_op(self.fired_buff.buff_type, buff_reason=self.fired_buff.buff_reason)
            elif self.demotion_buff is not None:
                self._sim_info.add_buff_from_op(self.demotion_buff.buff_type, buff_reason=self.demotion_buff.buff_reason)
            curr_level = -1 if demote_fired else self._level
            with telemetry_helper.begin_hook(career_telemetry_writer, TELEMETRY_HOOK_CAREER_DEMOTION, sim=self._sim_info) as hook:
                hook.write_int(TELEMETRY_CAREER_ID, self.guid64)
                hook.write_int(TELEMETRY_CAREER_LEVEL, self._user_level)
                hook.write_guid(TELEMETRY_TRACK_ID, self._current_track.guid64)
                hook.write_int(TELEMETRY_TRACK_LEVEL, curr_level)

    def quit_career(self, post_quit_msg=True):
        with telemetry_helper.begin_hook(career_telemetry_writer, TELEMETRY_HOOK_CAREER_END, sim=self._sim_info) as hook:
            hook.write_int(TELEMETRY_CAREER_ID, self.guid64)
            hook.write_int(TELEMETRY_CAREER_LEVEL, self._user_level)
            hook.write_guid(TELEMETRY_TRACK_ID, self._current_track.guid64)
            hook.write_int(TELEMETRY_TRACK_LEVEL, self._level)
        loot = self.current_level_tuning.loot_on_quit
        if loot is not None:
            resolver = SingleSimResolver(self._sim_info)
            loot.apply_to_resolver(resolver)
        self._sim_info.career_tracker.career_leave(self)
        if post_quit_msg:
            self.send_career_message(self.career_messages.quit_career_notification)
        self.resend_career_data()
        self.resend_at_work_info()

    def can_change_level(self, demote=False):
        delta = 1 if not demote else -1
        new_level = self._level + delta
        num_career_levels = len(self._current_track.career_levels)
        if new_level < 0:
            return False
        if new_level >= num_career_levels and len(self.current_track_tuning.branches) == 0:
            return False
        return True

    def _change_level(self, delta):
        new_level = self._level + delta
        num_career_levels = len(self._current_track.career_levels)
        if new_level < 0:
            return False
        if new_level >= num_career_levels:
            if self.current_track_tuning.branches:
                sim_info = self._sim_info
                if sim_info.is_selectable and sim_info.valid_for_distribution:
                    if services.current_zone().ui_dialog_service.auto_respond:
                        self.set_new_career_track(self.current_track_tuning.branches[0].guid64)
                        return False
                    msg = self.get_select_career_track_pb(sim_info, self, self.current_track_tuning.branches)
                    Distributor.instance().add_op(sim_info, GenericProtocolBufferOp(Operation.SELECT_CAREER_UI, msg))
            return False
        self.career_stop()
        self._level = new_level
        self._sim_info.career_tracker.update_history(self)
        self._reset_career_objectives(self._current_track, new_level)
        self.career_start()
        self.resend_career_data()
        self.resend_at_work_info()
        return True

    def set_new_career_track(self, track_guid):
        with self._handle_promotion():
            for career_track in self.current_track_tuning.branches:
                while career_track.guid64 == track_guid:
                    self.career_stop()
                    self._current_track = career_track
                    self._level = 0
                    self._reset_career_objectives(career_track, 0)
                    self._sim_info.career_tracker.update_history(self)
                    self.career_start()
                    self.resend_career_data()
                    self.resend_at_work_info()
                    return
            logger.error('Tried to select an invalid track for career: {}, {}', self, track_guid)

    def _reset_career_objectives(self, track, level):
        career_aspiration = track.career_levels[level].get_aspiration()
        if career_aspiration is not None:
            self._sim_info.aspiration_tracker.reset_milestone(career_aspiration.guid64)
            career_aspiration.register_callbacks()
            self._sim_info.aspiration_tracker.process_test_events_for_aspiration(career_aspiration)

    def evaluate_career_performance(self):
        current_level_tuning = self.current_level_tuning
        performance_stat = self._sim_info.statistic_tracker.get_statistic(current_level_tuning.performance_stat)
        current_performance = performance_stat.get_value()
        auto_fire = current_performance <= current_level_tuning.fired_performance_level
        demotion = current_performance <= current_level_tuning.demotion_performance_level
        if auto_fire or demotion:
            resolver = SingleSimResolver(self._sim_info)
            if random.random() < self.demotion_chance_modifiers.get_multiplier(resolver):
                self.demote(auto_fire=auto_fire)
            return True
        promotion_aspiration = current_level_tuning.aspiration
        if promotion_aspiration is None or self._sim_info.aspiration_tracker.milestone_completed(promotion_aspiration.guid64):
            performance_threshold = current_level_tuning.promote_performance_level
            resolver = SingleSimResolver(self._sim_info)
            if random.random() < self.early_promotion_chance.get_multiplier(resolver):
                multiplier = self.early_promotion_modifiers.get_multiplier(resolver)
                current_performance += performance_threshold*multiplier
            if current_performance >= performance_threshold:
                self.promote()
                return True
        self.resend_career_data()
        return False

    def handle_career_loot(self, hours_worked):
        reward = self.collect_rewards(hours_worked)
        span_worked = create_time_span(hours=hours_worked)
        services.get_event_manager().process_event(test_events.TestEvent.WorkdayComplete, sim_info=self._sim_info, career=self, time_worked=span_worked.in_ticks(), money_made=reward)

    def _career_performance_warning_response(self, dialog):
        if not dialog.accepted:
            return
        sim = self._sim_info.get_sim_instance()
        if sim is None:
            return
        context = interactions.context.InteractionContext(sim, interactions.context.InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT, interactions.priority.Priority.High, insert_strategy=interactions.context.QueueInsertStrategy.NEXT, bucket=interactions.context.InteractionBucketType.DEFAULT)
        sim.push_super_affordance(self.career_messages.career_performance_warning.affordance, sim, context)

    def get_hourly_pay(self, career_level=None):
        if career_level is None:
            career_level = self._level
        level_tuning = self._current_track.career_levels[career_level]
        hourly_pay = level_tuning.simoleons_per_hour
        for trait_bonus in level_tuning.simolean_trait_bonus:
            while self._sim_info.trait_tracker.has_trait(trait_bonus.trait):
                hourly_pay += hourly_pay*(trait_bonus.bonus*0.01)
        hourly_pay = int(hourly_pay)
        return hourly_pay

    def collect_rewards(self, time_at_work):
        current_level_tuning = self.current_level_tuning
        performance_metrics = current_level_tuning.performance_metrics
        work_duration = self._current_work_duration.in_hours()
        percent_at_work = time_at_work/work_duration
        work_time_multiplier = 1
        if percent_at_work*100 < performance_metrics.full_work_day_percent:
            self.work_performance_stat.add_value(-performance_metrics.missed_work_penalty)
            work_time_multiplier = percent_at_work/(performance_metrics.full_work_day_percent/100)
        work_money = math.ceil(self.get_hourly_pay()*work_duration*work_time_multiplier)
        self._sim_info.household.funds.add(work_money, Consts_pb2.TELEMETRY_MONEY_CAREER, self._get_sim())
        with telemetry_helper.begin_hook(career_telemetry_writer, TELEMETRY_HOOK_CAREER_DAILY_END, sim=self._sim_info) as hook:
            hook.write_int(TELEMETRY_CAREER_ID, self.guid64)
            hook.write_int(TELEMETRY_CAREER_LEVEL, self._user_level)
            hook.write_guid(TELEMETRY_TRACK_ID, self._current_track.guid64)
            hook.write_int(TELEMETRY_TRACK_LEVEL, self._level)
        if self.attended_work:
            self.send_career_message(self.career_messages.career_daily_end_notification, work_money)
        if self.evaluate_career_performance() or self.career_messages.career_performance_warning.threshold.compare(self.work_performance):
            self.send_career_message(self.career_messages.career_performance_warning.dialog, on_response=self._career_performance_warning_response)
        return work_money

    def set_career_situation_available(self, available):
        if self._career_situation is None:
            return
        msg = protocolbuffers.Sims_pb2.CareerSituationEnable()
        msg.sim_id = self._sim_info.sim_id
        msg.career_situation_id = self._career_situation.guid64
        msg.career_uid = self.guid64
        msg.enable = available
        distributor.shared_messages.add_message_if_selectable(self._sim_info, protocolbuffers.Consts_pb2.MSG_CAREER_SITUATION_ENABLE, msg, False)

    def _get_message_tokens(self):
        job = self.current_level_tuning.title(self._sim_info)
        career = self._current_track.career_name(self._sim_info)
        company = self.get_company_name_from_hash(self._company_name)
        return (job, career, company)

    @contextmanager
    def _handle_promotion(self):
        self._pending_promotion = True
        previous_level_tuning = self.current_level_tuning
        previous_salary = self.get_hourly_pay()
        previous_highest_level = self._sim_info.career_tracker.get_highest_level_reached(self.guid64)
        try:
            yield None
        finally:
            if self.current_level_tuning is not previous_level_tuning:
                self._pending_promotion = False
                if self.user_level > previous_highest_level and self.current_level_tuning.promotion_reward is not None:
                    reward_payout = self.current_level_tuning.promotion_reward.give_reward(self._sim_info)
                    reward_text = LocalizationHelperTuning.get_bulleted_list(None, *(reward.get_display_text() for reward in reward_payout))
                else:
                    reward_text = None
                (_, next_work_time, _) = self.get_next_work_time()
                salary = self.get_hourly_pay()
                salary_increase = salary - previous_salary
                level_text = self.current_level_tuning.promotion_notification_text(self._sim_info)
                is_not_school = not self.get_is_school()
                if reward_text is None:
                    self.send_career_message(self.career_messages.promote_career_rewardless_notification, next_work_time, salary, salary_increase, level_text, display_career_info=is_not_school)
                else:
                    self.send_career_message(self.career_messages.promote_career_notification, next_work_time, salary, salary_increase, level_text, reward_text, display_career_info=is_not_school)
                promotion_sting = self.current_level_tuning.promotion_audio_sting
                if promotion_sting is not None:
                    play_tunable_audio(promotion_sting)
                if self.current_level_tuning.screen_slam is not None:
                    self.current_level_tuning.screen_slam.send_screen_slam_message(self._sim_info, self._sim_info, self.current_level_tuning.title(self._sim_info), self.user_level, self.current_track_tuning.career_name(self._sim_info))
                if self.has_outfit():
                    self._sim_info.refresh_current_outfit()
                else:
                    new_outfit = self._sim_info._outfits.get_outfit_for_clothing_change(None, OutfitChangeReason.DefaultOutfit, resolver=SingleSimResolver(self._sim_info))
                    self._sim_info.set_current_outfit(new_outfit)
                with telemetry_helper.begin_hook(career_telemetry_writer, TELEMETRY_HOOK_CAREER_PROMOTION, sim=self._sim_info) as hook:
                    hook.write_int(TELEMETRY_CAREER_ID, self.guid64)
                    hook.write_int(TELEMETRY_CAREER_LEVEL, self._user_level)
                    hook.write_guid(TELEMETRY_TRACK_ID, self._current_track.guid64)
                    hook.write_int(TELEMETRY_TRACK_LEVEL, self._level)

    def send_career_message(self, dialog_factory, *additional_tokens, on_response=None, display_career_info=False):
        if self._sim_info.is_npc:
            return
        dialog = dialog_factory(self._sim_info, resolver=SingleSimResolver(self._sim_info))
        if dialog is not None:
            if display_career_info:
                career_args = UiCareerNotificationArgs()
                career_args.career_uid = self.guid64
                career_args.career_level = self.level
                career_args.career_track = self._current_track.guid64
                career_args.user_career_level = self.user_level
                career_args.sim_id = self._sim_info.id
            else:
                career_args = None
            dialog.show_dialog(additional_tokens=self._get_message_tokens() + additional_tokens, icon_override=(self._current_track.icon, None), secondary_icon_override=(None, self._sim_info), on_response=on_response, career_args=career_args)

    def populate_set_career_op(self, career_op):
        career_op.career_uid = self.guid64
        career_op.career_level = self.level
        career_op.performance = int(self.work_performance)
        career_op.company.hash = self.company_name
        career_op.auto_work = self.auto_work
        career_op.career_track = self._current_track.guid64
        career_op.user_career_level = self.user_level
        career_op.performance_complete = self.work_performance >= self.current_level_tuning.promote_performance_level
        career_op.skip_next_shift = self.should_skip_next_shift()
        tooltip = self._get_performance_tooltip()
        if tooltip:
            career_op.performance_tooltip = tooltip
        career_op.is_retired = False

    def sim_skewer_affordances_gen(self, context, **kwargs):
        for tone in self.get_available_tones_gen():
            yield AffordanceObjectPair(self.CAREER_TONE_INTERACTION, None, self.CAREER_TONE_INTERACTION, None, away_action=tone, away_action_sim_info=self._sim_info, **kwargs)
        affordance = self.current_level_tuning.tones.leave_work_early
        if affordance is not None:
            for aop in affordance.potential_interactions(self._get_sim(), context, sim_info=self._sim_info, **kwargs):
                yield aop

    def get_available_tones_gen(self):
        tones = self.current_level_tuning.tones
        yield tones.default_action
        yield tones.optional_actions

    def start_tones(self):
        tones = self.current_level_tuning.tones
        tracker = self._sim_info.away_action_tracker
        tracker.add_on_away_action_started_callback(self._on_tone_started)
        tracker.add_on_away_action_ended_callback(self._on_tone_ended)
        tracker.create_and_apply_away_action(tones.default_action)

    def restore_tones(self):
        if self.attended_work:
            tracker = self._sim_info.away_action_tracker
            tracker.add_on_away_action_started_callback(self._on_tone_started)
            tracker.add_on_away_action_ended_callback(self._on_tone_ended)

    def end_tones(self):
        tracker = self._sim_info.away_action_tracker
        tracker.reset_to_default_away_action()
        tracker.remove_on_away_action_started_callback(self._on_tone_started)
        tracker.remove_on_away_action_ended_callback(self._on_tone_ended)
        dominant_tone = None
        dominant_value = 0
        for tone in self.get_available_tones_gen():
            stat = self._sim_info.get_statistic(tone.runtime_commodity, add=False)
            while stat is not None:
                value = stat.get_value()
                if dominant_tone is None or value > dominant_value:
                    dominant_tone = tone
                    dominant_value = value
        if dominant_tone is not None:
            tone = dominant_tone(tracker)
            tone.apply_dominant_tone_loot()
        self._remove_tone_commodities()

    def get_hours_worked(self):
        minutes = 0
        for tone in self.get_available_tones_gen():
            stat = self._sim_info.get_statistic(tone.runtime_commodity, add=False)
            while stat is not None:
                value = stat.get_value()
                minutes += value
        hours = minutes/MINUTES_PER_HOUR
        return hours

    def _on_tone_started(self, tone):
        if self._is_valid_tone(tone):
            stat = self._sim_info.get_statistic(tone.runtime_commodity)
            stat.add_statistic_modifier(CareerBase.TONE_STAT_MOD)

    def _on_tone_ended(self, tone):
        if self._is_valid_tone(tone):
            stat = self._sim_info.get_statistic(tone.runtime_commodity)
            stat.remove_statistic_modifier(CareerBase.TONE_STAT_MOD)

    def _remove_tone_commodities(self):
        for tone in self.get_available_tones_gen():
            self._sim_info.remove_statistic(tone.runtime_commodity)

    def _is_valid_tone(self, tone):
        for other_tone in self.get_available_tones_gen():
            while tone.guid64 == other_tone.guid64:
                return True
        return False

    def has_outfit(self):
        return bool(self.current_level_tuning.work_outfit.outfit_tags)

    def startup_career(self):
        self.set_career_situation_available(True)

    def on_loading_screen_animation_finished(self):
        if self._pending_promotion:
            self.promote()

