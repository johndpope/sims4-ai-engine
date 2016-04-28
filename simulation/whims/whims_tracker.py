from protocolbuffers import DistributorOps_pb2, Sims_pb2
from protocolbuffers.DistributorOps_pb2 import Operation, SetWhimBucks
from date_and_time import create_time_span
from distributor.ops import distributor, GenericProtocolBufferOp
from distributor.rollback import ProtocolBufferRollback
from distributor.system import Distributor
from event_testing import test_events
from event_testing.results import TestResult
from objects import ALL_HIDDEN_REASONS_EXCEPT_UNINITIALIZED
from sims.sim import Sim
from sims.sim_info import SimInfo
from sims4.tuning.tunable import TunableReference, TunableTuple, Tunable, TunableEnumEntry
from situations.situation_goal_targeted_sim import SituationGoalSimTargetingOptions
from situations.situation_serialization import GoalSeedling
import alarms
import date_and_time
import enum
import event_testing
import rewards
import services
import sims4.log
import sims4.random
import sims4.tuning
import telemetry_helper
import uid
TELEMETRY_GROUP_WHIMS = 'WHIM'
TELEMETRY_HOOK_WHIM_EVENT = 'WEVT'
TELEMETRY_WHIM_EVENT_TYPE = 'wtyp'
TELEMETRY_WHIM_GUID = 'wgui'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_WHIMS)
logger = sims4.log.Logger('Whims')

class TelemetryWhimEvents(enum.Int, export=False):
    __qualname__ = 'TelemetryWhimEvents'
    CANCELED = 0
    NO_LONGER_AVAILABLE = 1
    COMPLETED = 2
    ADDED = 4

class WhimsTracker:
    __qualname__ = 'WhimsTracker'
    MAX_GOALS = sims4.tuning.tunable.Tunable(description='\n        The maximum number of concurrent whims a Sim can have offered at once', tunable_type=int, default=2, export_modes=sims4.tuning.tunable_base.ExportModes.All)
    TICKS_PER_SIM_MINUTE = date_and_time.MILLISECONDS_PER_SECOND*date_and_time.SECONDS_PER_MINUTE

    class WhimAwardTypes(enum.Int):
        __qualname__ = 'WhimsTracker.WhimAwardTypes'
        MONEY = 0
        BUFF = 1
        OBJECT = 2
        TRAIT = 3
        CASPART = 4

    SATISFACTION_STORE_ITEMS = sims4.tuning.tunable.TunableMapping(description='\n        A list of Sim based Tunable Rewards offered from the Satisfaction Store.', key_type=TunableReference(description='The reward to offer .', manager=services.get_instance_manager(sims4.resources.Types.REWARD)), value_type=TunableTuple(description='A collection of data about this reward.', cost=Tunable(tunable_type=int, default=100), award_type=TunableEnumEntry(WhimAwardTypes, WhimAwardTypes.MONEY)))

    def __init__(self, sim_info):
        self._sim_info = sim_info
        self._goal_id_generator = uid.UniqueIdGenerator(1)
        self._whim_goal_proto = None
        self._active_whims = []
        for _ in range(WhimsTracker.MAX_GOALS + 1):
            self._active_whims.append(None)
        self._realized_goals = {}
        self._whimset_target_map = {}
        self._completed_goals = {}
        self._whimset_objective_map = {}
        self._test_results_map = {}
        self.active_sets = []
        self.active_chained_sets = []
        self.sets_on_cooldown = []
        self.alarm_handles = {}
        self.delay_alarm_handles = []
        self._goals_dirty = True

    def cache_whim_goal_proto(self, whim_tracker_proto, skip_load=False):
        if not skip_load:
            self._whim_goal_proto = whim_tracker_proto

    def load_whims_info_from_proto(self):
        if self._sim_info.is_npc:
            return
        if self._whim_goal_proto is None:
            return
        for goal in tuple(self._realized_goals.keys()):
            self.dismiss_whim(goal.guid64)
        active_whims_index = 0
        aspiration_mgr = services.get_instance_manager(sims4.resources.Types.ASPIRATION)
        whims_to_whimsets = {}
        for whim_whimset_pair in self._whim_goal_proto.whims_to_whimsets:
            whims_to_whimsets[whim_whimset_pair.whim_guid64] = whim_whimset_pair.whimset_guid64
        whims_to_targets = {}
        for whim_target_pair in self._whim_goal_proto.whims_to_targets:
            whims_to_targets[whim_target_pair.whim_guid64] = whim_target_pair.target_id
        if len(self._whim_goal_proto.whim_goals) > WhimsTracker.MAX_GOALS + 1:
            logger.error('More whims saved than the max number of goals allowed', owner='jjacobson')
        for goal_proto in self._whim_goal_proto.whim_goals:
            goal_seed = GoalSeedling.deserialize_from_proto(goal_proto)
            if goal_seed is None:
                pass
            goal_id = goal_seed.goal_type.guid64
            source_set = aspiration_mgr.get(whims_to_whimsets[goal_id])
            if source_set is None:
                logger.warn('Whimset for whim {} not found during whim tracker load.  Whim was probably saved with whimset that no longer exists.  Skipping whim.', goal_seed.goal_type, owner='jjacobson')
            goal_target_sim_info = None
            if goal_id in whims_to_targets:
                goal_target_sim_info = services.sim_info_manager().get(whims_to_targets[goal_id])
                if goal_target_sim_info is None:
                    pass
            goal = goal_seed.goal_type(sim_info=self._sim_info, goal_id=self._goal_id_generator(), inherited_target_sim_info=goal_target_sim_info, count=goal_seed.count, reader=goal_seed.reader)
            goal.register_for_on_goal_completed_callback(self._on_goal_completed)
            self._realized_goals[goal] = source_set
            if goal_target_sim_info is not None:
                self._whimset_target_map[source_set] = goal_target_sim_info
            if self.get_emotion_guid(source_set) != 0:
                self._active_whims[WhimsTracker.MAX_GOALS] = goal
            else:
                self._active_whims[active_whims_index] = goal
                active_whims_index += 1
            while active_whims_index > WhimsTracker.MAX_GOALS:
                break
        if active_whims_index > 0:
            self._goals_dirty = True
        self._whim_goal_proto = None

    def save_whims_info_to_proto(self, whim_tracker_proto):
        if self._sim_info.is_npc:
            return
        for (whim, whimset) in self._realized_goals.items():
            with ProtocolBufferRollback(whim_tracker_proto.whims_to_whimsets) as whim_whimset_pair:
                whim_whimset_pair.whim_guid64 = whim.guid64
                whim_whimset_pair.whimset_guid64 = whimset.guid64
        for (whimset, target) in self._whimset_target_map.items():
            while target is not None:
                with ProtocolBufferRollback(whim_tracker_proto.whims_to_targets) as whim_target_pair:
                    for (whim, source_set) in self._realized_goals.items():
                        while source_set.guid64 == whimset.guid64:
                            whim_target_pair.whim_guid64 = whim.guid64
                            break
                    while whim_target_pair.whim_guid64 != 0:
                        whim_target_pair.target_id = target.id
        if len(self._realized_goals) > self.MAX_GOALS + 1:
            logger.error('Trying to save too many whims. Current whims: {}', self._realized_goals.keys(), owner='jjacobson')
        for given_goal in self._realized_goals.keys():
            goal_seed = given_goal.create_seedling()
            goal_seed.finalize_creation_for_save()
            with ProtocolBufferRollback(whim_tracker_proto.whim_goals) as goal_proto:
                goal_seed.serialize_to_proto(goal_proto)

    @property
    def _sim(self):
        return self._sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS_EXCEPT_UNINITIALIZED)

    def clean_up(self):
        for goal in self._realized_goals.keys():
            while goal is not None:
                goal.destroy()
        self._realized_goals.clear()
        for goal in self._active_whims:
            while goal is not None:
                goal.destroy()
        self._active_whims.clear()
        for alarm_handle in self.alarm_handles.values():
            alarms.cancel_alarm(alarm_handle)
        self.alarm_handles.clear()
        for delay_alarm_handle in self.delay_alarm_handles:
            alarms.cancel_alarm(delay_alarm_handle)
        self.delay_alarm_handles.clear()
        self._whimset_objective_map.clear()
        self._test_results_map.clear()

    def remove_alarm_handle(self, whim_set):
        if whim_set in self.alarm_handles:
            alarms.cancel_alarm(self.alarm_handles[whim_set])
            del self.alarm_handles[whim_set]

    def purchase_whim_award(self, reward_guid64):
        reward_instance = services.get_instance_manager(sims4.resources.Types.REWARD).get(reward_guid64)
        award = reward_instance
        cost = self.SATISFACTION_STORE_ITEMS[reward_instance].cost
        if self._sim_info.get_whim_bucks() < cost:
            logger.debug('Attempting to purchase a whim award with insufficient funds: Cost: {}, Funds: {}', cost, self._sim_info.get_whim_bucks())
            return
        self._sim_info.add_whim_bucks(-cost, SetWhimBucks.PURCHASED_REWARD)
        award.give_reward(self._sim_info)

    def send_satisfaction_reward_list(self):
        msg = Sims_pb2.SatisfactionRewards()
        for (reward, data) in self.SATISFACTION_STORE_ITEMS.items():
            reward_msg = Sims_pb2.SatisfactionReward()
            reward_msg.reward_id = reward.guid64
            reward_msg.cost = data.cost
            reward_msg.affordable = True if data.cost <= self._sim_info.get_whim_bucks() else False
            reward_msg.available = reward.is_valid(self._sim_info)
            reward_msg.type = data.award_type
            msg.rewards.append(reward_msg)
        msg.sim_id = self._sim_info.id
        distributor = Distributor.instance()
        distributor.add_op_with_no_owner(GenericProtocolBufferOp(Operation.SIM_SATISFACTION_REWARDS, msg))

    def activate_set(self, whim_set, is_cheat=False):
        if whim_set in self.sets_on_cooldown:
            return
        if whim_set not in self.active_sets and whim_set not in self.active_chained_sets:
            if __debug__ and not is_cheat:
                self._whimset_objective_map[whim_set] = self._sim_info.aspiration_tracker.latest_objective
            self.active_sets.append(whim_set)
            self.remove_alarm_handle(whim_set)
            self.alarm_handles[whim_set] = alarms.add_alarm(self, create_time_span(minutes=whim_set.active_timer), lambda _, this_whim_set=whim_set: self.deactivate_set(this_whim_set), False)
        refresh_delay = whim_set.new_whim_delay.random_int()
        self.refresh_goals(request_single_goal=True, request_single_delay=refresh_delay)

    def activate_chained_set(self, last_whim_set, goal, inherited_target_sim_info):
        for whim_set in last_whim_set.connected_whim_sets:
            while whim_set not in self.active_chained_sets and whim_set not in self.sets_on_cooldown:
                self._whimset_target_map[whim_set] = inherited_target_sim_info
                self.active_chained_sets.append(whim_set)
                if whim_set in self.active_sets:
                    self.active_sets.remove(whim_set)
                self.remove_alarm_handle(whim_set)
                self.alarm_handles[whim_set] = alarms.add_alarm(self, create_time_span(minutes=whim_set.active_timer), lambda _, this_whim_set=whim_set: self.deactivate_set(this_whim_set), False)
        if goal in last_whim_set.connected_whims:
            whim_set = last_whim_set.connected_whims[goal]
            if whim_set not in self.active_chained_sets and whim_set not in self.sets_on_cooldown:
                self._whimset_target_map[whim_set] = inherited_target_sim_info
                self.active_chained_sets.append(whim_set)
                if whim_set in self.active_sets:
                    self.active_sets.remove(whim_set)
                self.remove_alarm_handle(whim_set)
                self.alarm_handles[whim_set] = alarms.add_alarm(self, create_time_span(minutes=whim_set.active_timer), lambda _, this_whim_set=whim_set: self.deactivate_set(this_whim_set), False)

    def deactivate_set(self, whim_set, from_cheat=False, from_cancel=False):
        if whim_set.timeout_retest is not None and not from_cancel:
            resolver = event_testing.resolver.SingleSimResolver(self._sim_info)
            if resolver(whim_set.timeout_retest.objective_test):
                self.remove_alarm_handle(whim_set)
                self.alarm_handles[whim_set] = alarms.add_alarm(self, create_time_span(minutes=whim_set.active_timer), lambda _, this_whim_set=whim_set: self.deactivate_set(this_whim_set), False)
                return
        if whim_set in self.active_sets:
            self.active_sets.remove(whim_set)
        elif whim_set in self.active_chained_sets:
            self.active_chained_sets.remove(whim_set)
        self.remove_alarm_handle(whim_set)
        if whim_set.cooldown_timer == 0:
            self._sim_info.aspiration_tracker.reset_milestone(whim_set.guid64)
        elif whim_set not in self.sets_on_cooldown and not from_cheat:
            self.sets_on_cooldown.append(whim_set)
            self.alarm_handles[whim_set] = alarms.add_alarm(self, create_time_span(minutes=whim_set.cooldown_timer), lambda _, this_whim_set=whim_set: self.finish_cooldown(this_whim_set), False)

    def finish_cooldown(self, whim_set):
        if whim_set in self.sets_on_cooldown:
            self.sets_on_cooldown.remove(whim_set)
            self._sim_info.aspiration_tracker.reset_milestone(whim_set.guid64)

    def get_priority(self, whim_set):
        if whim_set in self.active_chained_sets:
            return whim_set.chained_priority
        if whim_set in self.active_sets:
            return whim_set.activated_priority
        return whim_set.base_priority

    def get_whimset_target(self, whim_set):
        if whim_set not in self._whimset_target_map:
            return
        return self._whimset_target_map[whim_set]

    @property
    def whims_needed(self):
        normal_whim_count = 0
        for whimset in self._realized_goals.values():
            while whimset.whimset_emotion is None:
                normal_whim_count += 1
        return self.MAX_GOALS - normal_whim_count

    @property
    def emotion_whim_needed(self):
        for whimset in self._realized_goals.values():
            while whimset.whimset_emotion is not None:
                return False
        return True

    def _select_goals(self, prioritized_tuned_whim_sets, chosen_tuned_goals, debug_goal=None, debug_target=None, request_single_goal=None):
        sim = self._sim
        if request_single_goal:
            goals_needed = 1
        else:
            goals_needed = self.whims_needed if self.whims_needed > 0 else 1
        goals_found = 0
        while prioritized_tuned_whim_sets:
            tuned_whim_set = sims4.random.pop_weighted(prioritized_tuned_whim_sets)
            weighted_goal_refs = []
            if debug_goal is None:
                if tuned_whim_set in self.sets_on_cooldown:
                    continue
                for whim in tuned_whim_set.whims:
                    while whim not in self._realized_goals:
                        weighted_goal_refs.append((whim.weight, whim.goal))
            else:
                weighted_goal_refs.append((1, debug_goal))
            whimset_target = self._whimset_target_map.get(tuned_whim_set)
            while weighted_goal_refs:
                tuned_goal = sims4.random.pop_weighted(weighted_goal_refs)
                if tuned_goal in chosen_tuned_goals:
                    continue
                is_duplicate = False
                for (goal_instance, goal_set) in self._realized_goals.items():
                    if isinstance(goal_instance, tuned_goal):
                        is_duplicate = True
                    while goal_set is tuned_whim_set:
                        is_duplicate = True
                if is_duplicate:
                    continue
                old_goal_instance = self._completed_goals.get(tuned_goal)
                if old_goal_instance is not None and old_goal_instance[0].is_on_cooldown():
                    continue
                if debug_target is not None:
                    potential_target = debug_target
                    tuned_goal._target_option = SituationGoalSimTargetingOptions.DebugChoice
                else:
                    potential_target = whimset_target
                    if tuned_whim_set.force_target is not None:
                        potential_target = tuned_whim_set.force_target(self._sim_info)
                        if not potential_target:
                            continue
                if potential_target is not None and isinstance(potential_target, Sim):
                    potential_target = potential_target.sim_info
                pretest = tuned_goal.can_be_given_as_goal(sim, None, inherited_target_sim_info=potential_target)
                if pretest:
                    chosen_tuned_goals[tuned_goal] = tuned_whim_set
                    self._whimset_target_map[tuned_whim_set] = potential_target
                    self._goals_dirty = True
                    goals_found += 1
                    break
                else:
                    while debug_goal is not None:
                        logger.error('Whim Goal {} failed pre-tests during offering: {}', debug_goal, pretest.reason, owner='jjacobson')
                        continue
            while goals_found >= goals_needed:
                break
                continue

    def offer_goals(self, debug_goal=None, debug_target=None, request_single_goal=False, emotion_only=False):
        if not self.emotion_whim_needed and self.whims_needed == 0:
            return
        if self._sim_info.is_npc:
            return
        if self._sim is None:
            return
        chosen_tuned_goals = {}
        if self.whims_needed > 0:
            normal_whimset_list = services.get_instance_manager(sims4.resources.Types.ASPIRATION).normal_whim_sets
            prioritized_tuned_whim_sets = []
            for whim_set in normal_whimset_list:
                priority = self.get_priority(whim_set)
                while priority != 0:
                    prioritized_tuned_whim_sets.append((priority, whim_set))
            if not emotion_only:
                self._select_goals(prioritized_tuned_whim_sets, chosen_tuned_goals, debug_goal, debug_target, request_single_goal)
        if self.emotion_whim_needed:
            emotion_whimset_list = services.get_instance_manager(sims4.resources.Types.ASPIRATION).emotion_whim_sets
            prioritized_tuned_whim_sets = []
            for whim_set in emotion_whimset_list:
                priority = self.get_priority(whim_set)
                while priority != 0 and whim_set.whimset_emotion is self._sim_mood:
                    prioritized_tuned_whim_sets.append((priority, whim_set))
            self._select_goals(prioritized_tuned_whim_sets, chosen_tuned_goals, debug_goal, debug_target)
        if self._goals_dirty:
            index = 0
            for tuned_goal in chosen_tuned_goals:
                goal_added = False
                if chosen_tuned_goals[tuned_goal].whimset_emotion is not None:
                    goal = tuned_goal(sim_info=self._sim_info, goal_id=self._goal_id_generator(), inherited_target_sim_info=self._whimset_target_map[chosen_tuned_goals[tuned_goal]])
                    self._active_whims[WhimsTracker.MAX_GOALS] = goal
                    goal_added = True
                else:
                    while index < WhimsTracker.MAX_GOALS:
                        if self._active_whims[index] is None:
                            goal = tuned_goal(sim_info=self._sim_info, goal_id=self._goal_id_generator(), inherited_target_sim_info=self._whimset_target_map[chosen_tuned_goals[tuned_goal]])
                            self._active_whims[index] = goal
                            goal_added = True
                            break
                        index += 1
                if goal_added:
                    self._realized_goals[goal] = chosen_tuned_goals[tuned_goal]
                    goal.register_for_on_goal_completed_callback(self._on_goal_completed)
                    logger.debug('Added whim for {}: {}', self._sim_info, goal, owner='jjacobson')
                else:
                    logger.error('Trying to add a whim when the active whims are already full.', owner='jjacobson.')
                with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_WHIM_EVENT, sim=self._sim_info) as hook:
                    hook.write_int(TELEMETRY_WHIM_EVENT_TYPE, TelemetryWhimEvents.ADDED)
                    hook.write_guid(TELEMETRY_WHIM_GUID, goal.guid64)
        if len(self._realized_goals) > WhimsTracker.MAX_GOALS + 1:
            logger.error('Too many whims active.  Current Whims: {}', self._realized_goals.keys(), owner='jjacobson')

    def refresh_goals(self, completed_goal=None, debug_goal=None, debug_target=None, request_single_goal=False, request_single_delay=0, emotion_only=False):
        if completed_goal is not None:
            logger.debug('Whim completed for {}: {}', self._sim_info, completed_goal, owner='jjacobson')
            op = distributor.ops.SetWhimComplete(completed_goal.guid64)
            Distributor.instance().add_op(self._sim_info, op)
            if completed_goal.score > 0:
                self._sim_info.add_whim_bucks(completed_goal.score, SetWhimBucks.WHIM)
            self._remove_goal_from_current_order(completed_goal)
            completed_goal.unregister_for_on_goal_completed_callback(self._on_goal_completed)
            del self._realized_goals[completed_goal]
            completed_goal.decommision()
        if request_single_delay == 0 or debug_goal is not None:
            self.offer_goals(debug_goal=debug_goal, debug_target=debug_target, request_single_goal=request_single_goal, emotion_only=emotion_only)
        else:
            delay_alarm = alarms.add_alarm(self, create_time_span(minutes=request_single_delay), self._delayed_offer_goals, False)
            self.delay_alarm_handles.append(delay_alarm)
        self._send_goals_update()

    def _delayed_offer_goals(self, delay_alarm_handle):
        self.offer_goals(request_single_goal=True)
        self._send_goals_update()
        alarms.cancel_alarm(delay_alarm_handle)
        self.delay_alarm_handles.remove(delay_alarm_handle)

    def _verify_goals(self):
        desired_whims_amount = WhimsTracker.MAX_GOALS + 1
        emotion_whim_found = False
        for goal in list(self._active_whims):
            if goal is None:
                pass
            goal_whimset = self._realized_goals.get(goal, None)
            emotion_guid = self.get_emotion_guid(goal_whimset)
            while emotion_guid != 0:
                if emotion_guid != self._sim_mood.guid64 or emotion_whim_found:
                    self._remove_whim_goal(goal, goal_whimset)
                else:
                    emotion_whim_found = True
        if len(self._active_whims) > desired_whims_amount:
            for goal in list(self._active_whims):
                while goal is None:
                    self._active_whims.remove(goal)
        while len(self._active_whims) > desired_whims_amount:
            extra_goal = self._active_whims[desired_whims_amount + 1]
            if goal is None:
                self._active_whims.remove(goal)
                continue
            goal_whimset = self._realized_goals.get(goal, None)
            self._remove_whim_goal(extra_goal, goal_whimset)
        if len(self._active_whims) < desired_whims_amount:
            spots_to_fill = desired_whims_amount - len(self._active_whims)
            self._active_whims.extend([None]*spots_to_fill)
        if len(self._active_whims) != desired_whims_amount:
            logger.error('Whim Goal Verification failed to prepare whim goals message for distribution. Active Whims: {}', self._active_whims)
            return False
        return True

    def _send_goals_update(self):
        if not self._verify_goals():
            return
        logger.debug('Sending whims update for {}.  Current active whims: {}', self._sim_info, self._active_whims, owner='jjacobson')
        current_whims = []
        for goal in self._active_whims:
            if goal is None:
                whim_goal = DistributorOps_pb2.WhimGoal()
                current_whims.append(whim_goal)
            goal_target_id = 0
            goal_whimset = self._realized_goals[goal]
            goal_target = goal.get_required_target_sim_info()
            goal_target_id = goal_target.id if goal_target is not None else 0
            whim_goal = DistributorOps_pb2.WhimGoal()
            whim_goal.whim_guid64 = goal.guid64
            whim_goal.whim_name = goal.display_name
            whim_goal.whim_score = goal.score
            whim_goal.whim_noncancel = goal.noncancelable
            whim_goal.whim_icon_key.type = goal._icon.type
            whim_goal.whim_icon_key.group = goal._icon.group
            whim_goal.whim_icon_key.instance = goal._icon.instance
            whim_goal.whim_goal_count = goal.max_iterations
            whim_goal.whim_current_count = goal.completed_iterations
            whim_goal.whim_target_sim = goal_target_id
            whim_goal.whim_tooltip = goal.tooltip
            whim_goal.whim_mood_guid64 = self.get_emotion_guid(goal_whimset)
            whim_goal.whim_tooltip_reason = goal_whimset.whim_reason(*goal.get_localization_tokens())
            current_whims.append(whim_goal)
        if self._goals_dirty:
            self._sim_info.current_whims = current_whims
            self._goals_dirty = False

    def get_emotion_guid(self, whimset):
        if whimset is None or whimset.whimset_emotion is None:
            return 0
        return whimset.whimset_emotion.guid64

    def get_goal_info(self):
        if self._realized_goals is None:
            return
        return list(self._realized_goals.keys())

    def get_goal_set(self, goal):
        if goal in self._realized_goals:
            return self._realized_goals[goal]

    def get_completed_goal_info(self):
        return self._completed_goals.keys()

    @property
    def _sim_mood(self):
        return self._sim_info.get_component('buffs_component').get_mood()

    def _on_goal_completed(self, goal, goal_completed):
        if not goal_completed:
            self._goals_dirty = True
            self._send_goals_update()
            return
        services.get_event_manager().process_event(test_events.TestEvent.WhimCompleted, sim_info=self._sim_info, whim_completed=goal)
        with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_WHIM_EVENT, sim=self._sim_info) as hook:
            hook.write_int(TELEMETRY_WHIM_EVENT_TYPE, TelemetryWhimEvents.COMPLETED)
            hook.write_guid(TELEMETRY_WHIM_GUID, goal.guid64)
        prev_goal_set = self._realized_goals.get(goal, None)
        self._completed_goals[type(goal)] = (goal, prev_goal_set)
        inherited_target_sim_info = goal._get_actual_target_sim_info()
        refresh_delay = prev_goal_set.new_whim_delay.random_int()
        if prev_goal_set not in prev_goal_set.connected_whim_sets:
            self.deactivate_set(prev_goal_set)
        self.activate_chained_set(prev_goal_set, goal, inherited_target_sim_info)
        self._goals_dirty = True
        logger.debug('Goal completed: {}, from Whim Set: {}', goal.__class__.__name__, self._realized_goals[goal].__name__)
        self.refresh_goals(goal, request_single_goal=True, request_single_delay=refresh_delay)

    def dismiss_whim(self, whim_guid64):
        this_goal = None
        emotion_only = False
        for goal in self._realized_goals.keys():
            while goal.guid64 == whim_guid64:
                this_goal = goal
                break
        refresh_delay = 0
        if this_goal is not None:
            if this_goal is self._active_whims[WhimsTracker.MAX_GOALS]:
                emotion_only = True
            prev_goal_set = self._realized_goals.get(this_goal, None)
            refresh_delay = prev_goal_set.whim_cancel_refresh_delay.random_int()
            self._remove_whim_goal(this_goal, prev_goal_set)
            logger.debug('Removing whim {}: {}.', self._sim_info, this_goal, owner='jjacobson')
        self._goals_dirty = True
        self.refresh_goals(request_single_goal=True, request_single_delay=refresh_delay, emotion_only=emotion_only)

    def _remove_whim_goal(self, whim_goal, whim_goal_set):
        with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_WHIM_EVENT, sim=self._sim_info) as hook:
            hook.write_int(TELEMETRY_WHIM_EVENT_TYPE, TelemetryWhimEvents.CANCELED)
            hook.write_guid(TELEMETRY_WHIM_GUID, whim_goal.guid64)
        self.deactivate_set(whim_goal_set, from_cancel=True)
        whim_goal.unregister_for_on_goal_completed_callback(self._on_goal_completed)
        self._remove_goal_from_current_order(whim_goal)
        if __debug__ and whim_goal.__class__ in self._test_results_map:
            del self._test_results_map[whim_goal.__class__]
        if whim_goal in self._realized_goals:
            del self._realized_goals[whim_goal]
        whim_goal.decommision()

    def _dismiss_emotion_whim(self):
        if len(self._active_whims) != 0:
            emotion_whim = self._active_whims[WhimsTracker.MAX_GOALS]
            if emotion_whim is not None:
                whimset = self._realized_goals[emotion_whim]
                if whimset.whimset_emotion is not self._sim_mood:
                    emotion_guid64 = emotion_whim.guid64
                    with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_WHIM_EVENT, sim=self._sim_info) as hook:
                        hook.write_int(TELEMETRY_WHIM_EVENT_TYPE, TelemetryWhimEvents.NO_LONGER_AVAILABLE)
                        hook.write_guid(TELEMETRY_WHIM_GUID, emotion_guid64)
                    self.dismiss_whim(emotion_guid64)
                    return
            self._goals_dirty = True
            self._send_goals_update()

    def refresh_emotion_whim(self):
        self._dismiss_emotion_whim()
        self.offer_goals(emotion_only=True)

    def force_whim_complete(self, whim, target_sim=None):
        goals = list(self._realized_goals.keys())
        for goal in goals:
            while whim.guid64 is goal.guid64:
                goal.debug_force_complete(target_sim=target_sim)

    def force_whim(self, whim, target=None):
        for active_set in self.active_sets:
            self.deactivate_set(active_set, from_cheat=True)
        goals = list(self._realized_goals.keys())
        for goal in goals:
            goal.unregister_for_on_goal_completed_callback(self._on_goal_completed)
            self._remove_goal_from_current_order(goal)
            if goal.__class__ in self._test_results_map:
                del self._test_results_map[goal.__class__]
            del self._realized_goals[goal]
            goal.decommision()
        self.refresh_goals(completed_goal=None, debug_goal=whim, debug_target=target)

    def force_whimset(self, whimset):
        self.activate_set(whimset, is_cheat=True)

    def force_whim_from_whimset(self, whimset):
        for active_set in self.active_sets:
            self.deactivate_set(active_set, from_cheat=True)
        goals = list(self._realized_goals.keys())
        for goal in goals:
            goal.unregister_for_on_goal_completed_callback(self._on_goal_completed)
            self._remove_goal_from_current_order(goal)
            if goal.__class__ in self._test_results_map:
                del self._test_results_map[goal.__class__]
            del self._realized_goals[goal]
            goal.decommision()
        self.force_whimset(whimset)

    def _remove_goal_from_current_order(self, goal):
        index = 0
        while index <= WhimsTracker.MAX_GOALS:
            if self._active_whims[index] is goal:
                self._active_whims[index] = None
                break
            index += 1

    def validate_goals(self):
        sim = self._sim_info.get_sim_instance()
        if sim is None:
            return
        for whim in tuple(self._active_whims):
            if whim is None:
                pass
            required_sim_info = whim.get_required_target_sim_info()
            while not whim.can_be_given_as_goal(sim, None, inherited_target_sim_info=required_sim_info):
                self.dismiss_whim(whim.guid64)

