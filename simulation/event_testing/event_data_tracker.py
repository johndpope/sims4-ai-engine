from collections import namedtuple
from date_and_time import TimeSpan, DateAndTime
from event_testing.event_data_const import TimeData
from event_testing.event_data_object import EventDataObject
from event_testing.resolver import DataResolver
from event_testing.results import TestResultNumeric
from gsi_handlers.achievement_handlers import archiver
import alarms
import services
import sims4.log
logger = sims4.log.Logger('Event Data Tracker')
ObjectiveUpdateInfo = namedtuple('ObjectiveUpdateInfo', ['current_value', 'objective_value', 'is_money', 'from_init'])

class EventDataTracker:
    __qualname__ = 'EventDataTracker'
    TIME_DATA_UPDATE_RATE = 60000

    def __init__(self):
        self._completed_milestones = set()
        self._completed_objectives = set()
        self._sent_milestones = set()
        self._sent_objectives = set()
        self._data_object = EventDataObject()
        self._tracker_dirty = False
        self._dirty_objective_state = {}
        self._last_objective_state = {}
        self.update_alarm_handle = None
        self.sim_time_on_connect = DateAndTime(0)
        self.server_time_on_connect = DateAndTime(0)
        self.sim_time_last_update = DateAndTime(0)
        self.server_time_last_update = DateAndTime(0)
        self.latest_objective = None

    @property
    def data_object(self):
        return self._data_object

    def _should_handle_event(self, milestone, event, resolver):
        return not resolver.sim_info.is_npc

    def _should_handle_objective(self, milestone, objective, resolver):
        return True

    def handle_event(self, milestone, event, resolver):
        if not self._should_handle_event(milestone, event, resolver):
            return
        log_enabled = archiver.enabled and not resolver.on_zone_load
        if log_enabled:
            milestone_event = self.gsi_event(event)
            milestone_process_data = []
        if not self.milestone_completed(milestone.guid64):
            objectives_completed = 0
            for objective in milestone.objectives:
                milestone_event_data = None
                if not self.objective_completed(objective.guid64):
                    if log_enabled:
                        milestone_event_data = self.gsi_event_data(milestone, objective, True, 'Objective Completed')
                    if self._should_handle_objective(milestone, objective, resolver):
                        test_result = objective.run_test(event, resolver, self._data_object)
                        if test_result:
                            self.complete_objective(objective)
                            objectives_completed += 1
                            goal_value = objective.goal_value()
                            self.update_objective(objective.guid64, goal_value, goal_value, objective.is_goal_value_money)
                        else:
                            if log_enabled:
                                milestone_event_data['test_result'] = test_result.reason
                                milestone_event_data['completed'] = False
                            if isinstance(test_result, TestResultNumeric):
                                self.update_objective(objective.guid64, test_result.current_value, test_result.goal_value, test_result.is_money, resolver.on_zone_load)
                else:
                    objectives_completed += 1
                    if resolver.on_zone_load:
                        goal_value = objective.goal_value()
                        self.update_objective(objective.guid64, goal_value, goal_value, objective.is_goal_value_money)
                while log_enabled and milestone_event_data is not None:
                    milestone_process_data.append(milestone_event_data)
            if objectives_completed >= self.required_completion_count(milestone):
                self.complete_milestone(milestone, resolver.sim_info)
        if log_enabled:
            milestone_event['Objectives Processed'] = milestone_process_data
            self.post_to_gsi(milestone_event)
        self.send_if_dirty()

    def gsi_event(self, event):
        return {'event': str(event)}

    def gsi_event_data(self, milestone, objective, completed, result):
        return {'milestone': milestone.__name__, 'completed': completed, 'test_type': objective.objective_test.__class__.__name__, 'test_result': result}

    def post_to_gsi(self, message):
        pass

    def send_if_dirty(self):
        if self._dirty_objective_state:
            self._send_objectives_update_to_client()
            self._dirty_objective_state = {}
        if self._tracker_dirty:
            self._send_tracker_to_client()
            self._tracker_dirty = False

    def _update_objectives_msg_for_client(self, msg):
        message_loaded = False
        for (objective_guid, value) in self._dirty_objective_state.items():
            while value.from_init or objective_guid not in self._last_objective_state or self._last_objective_state[objective_guid] != value.current_value:
                msg.goals_updated.append(int(objective_guid))
                msg.goal_values.append(int(value[0]))
                msg.goal_objectives.append(int(value[1]))
                msg.goals_that_are_money.append(bool(value[2]))
                self._last_objective_state[objective_guid] = value[0]
                message_loaded = True
        return message_loaded

    def clear_objective_updates_cache(self, milestone):
        for objective in milestone.objectives:
            while objective.guid64 in self._last_objective_state:
                del self._last_objective_state[objective.guid64]

    def _send_tracker_to_client(self, init=False):
        raise NotImplementedError

    def _send_objectives_update_to_client(self):
        raise NotImplementedError

    def required_completion_count(self, milestone):
        return len(milestone.objectives)

    def update_objective(self, objective_guid, current_value, objective_value, is_money, from_init=False):
        if objective_guid not in self._dirty_objective_state:
            self._dirty_objective_state[objective_guid] = ObjectiveUpdateInfo(current_value, objective_value, is_money, from_init)

    def complete_milestone(self, milestone, sim_info):
        self._completed_milestones.add(milestone.guid64)
        self._tracker_dirty = True

    def milestone_completed(self, milestone_guid):
        return milestone_guid in self._completed_milestones

    def milestone_sent(self, milestone_guid):
        return milestone_guid in self._sent_milestones

    def reset_milestone(self, milestone_guid):
        if milestone_guid in self._completed_milestones:
            self._completed_milestones.remove(milestone_guid)
            self._sent_milestones.remove(milestone_guid)

    def complete_objective(self, objective_instance):
        self.latest_objective = objective_instance
        self._completed_objectives.add(objective_instance.guid64)
        self._tracker_dirty = True

    def objective_completed(self, objective_instance_id):
        return objective_instance_id in self._completed_objectives

    def objective_sent(self, objective_instance_id):
        return objective_instance_id in self._sent_objectives

    def reset_objective(self, objective_instance_id):
        if objective_instance_id in self._completed_objectives:
            self._completed_objectives.remove(objective_instance_id)
            self._sent_objectives.remove(objective_instance_id)

    def update_timers(self):
        server_time_add = self.server_time_since_update()
        sim_time_add = self.sim_time_since_update()
        self._data_object.add_time_data(TimeData.SimTime, sim_time_add)
        self._data_object.add_time_data(TimeData.ServerTime, server_time_add)

    def set_update_alarm(self):
        self.sim_time_on_connect = services.time_service().sim_now
        self.server_time_on_connect = services.server_clock_service().now()
        self.sim_time_last_update = self.sim_time_on_connect
        self.server_time_last_update = self.server_time_on_connect
        self.update_alarm_handle = alarms.add_alarm(self, TimeSpan(self.TIME_DATA_UPDATE_RATE), self._update_timer_alarm, True)

    def clear_sent_milestones(self):
        self._sent_milestones.clear()

    def clear_update_alarm(self):
        if self.update_alarm_handle is not None:
            alarms.cancel_alarm(self.update_alarm_handle)
            self.update_alarm_handle = None
            self.update_timers()

    def _update_timer_alarm(self, _):
        raise NotImplementedError('Must override in subclass')

    def server_time_since_update(self):
        time_delta = services.server_clock_service().now() - self.server_time_last_update
        self.server_time_last_update = services.server_clock_service().now()
        return time_delta.in_ticks()

    def sim_time_since_update(self):
        time_delta = services.time_service().sim_now - self.sim_time_last_update
        self.sim_time_last_update = services.time_service().sim_now
        return time_delta.in_ticks()

    def save(self, blob=None):
        if blob is not None:
            self._data_object.save(blob)
            blob.milestones_completed.extend(self._completed_milestones)
            blob.objectives_completed.extend(self._completed_objectives)

    def load(self, blob=None):
        if blob is not None:
            self._completed_milestones = set(blob.milestones_completed)
            self._completed_objectives = set(blob.objectives_completed)
            self._data_object.load(blob)
        owner_sim_info = self.owner_sim_info
        if owner_sim_info is None or owner_sim_info.is_npc:
            return
        objectives_mgr = services.get_instance_manager(sims4.resources.Types.OBJECTIVE)
        objectives_in_progress = set()
        for (objective_id, objective_data) in self._data_object.get_objective_count_data().items():
            if objectives_mgr.get(objective_id) is None:
                logger.info('Trying to load unavailable OBJECTIVE resource: {}', objective_id)
            objective = objectives_mgr.get(objective_id)
            self.update_objective(objective_id, objective_data.get_count(), objective.goal_value(), objective.is_goal_value_money)
            objectives_in_progress.add(objective_id)
        for objective in objectives_mgr.types.values():
            while objective.guid64 not in objectives_in_progress:
                self.update_objective(objective.guid64, 0, objective.goal_value(), objective.is_goal_value_money)

    def post_load(self):
        owner_sim_info = self.owner_sim_info
        if owner_sim_info is None or owner_sim_info.is_npc:
            return
        self._send_objectives_update_to_client()
        self._send_tracker_to_client(init=True)

    def refresh_progress(self, sim_info=None):
        if sim_info is None:
            sim_info = self.owner_sim_info
        services.get_event_manager().process_test_events_for_objective_updates(sim_info)
        self._send_objectives_update_to_client()
        self._send_tracker_to_client(init=True)

    def reset_data(self):
        self._completed_milestones = set()
        self._completed_objectives = set()
        self._sent_milestones = set()
        self._sent_objectives = set()
        self._data_object = EventDataObject()
        self._tracker_dirty = False
        self._dirty_objective_state = {}
        self._last_objective_state = {}
        self.sim_time_on_connect = DateAndTime(0)
        self.server_time_on_connect = DateAndTime(0)
        self.sim_time_last_update = DateAndTime(0)
        self.server_time_last_update = DateAndTime(0)
        self.latest_objective = None

