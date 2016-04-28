from objects import ALL_HIDDEN_REASONS
from sims4.callback_utils import CallableList
import services
import sims4
logger = sims4.log.Logger('AwayActionTracker')

class AwayActionTracker:
    __qualname__ = 'AwayActionTracker'

    def __init__(self, sim_info):
        self._sim_info = sim_info
        self._current_away_action = None
        self._on_away_action_started = CallableList()
        self._on_away_action_ended = CallableList()
        self.add_on_away_action_started_callback(self._resend_away_action)
        self.add_on_away_action_ended_callback(self._resend_away_action)

    @property
    def sim_info(self):
        return self._sim_info

    @property
    def current_away_action(self):
        return self._current_away_action

    def _resend_away_action(self, _):
        self.sim_info.resend_current_away_action()

    def is_sim_info_valid_to_run_away_actions(self):
        if not self._sim_info.is_selectable:
            return False
        if self._sim_info.is_dead:
            return False
        if self._sim_info.is_baby:
            return False
        return True

    def _run_current_away_action(self):
        self._current_away_action.run(self._away_action_exit_condition_callback)
        self._on_away_action_started(self._current_away_action)

    def _find_away_action_from_load(self):
        away_actions_manager = services.get_instance_manager(sims4.resources.Types.AWAY_ACTION)
        for away_action_cls in away_actions_manager.types.values():
            while away_action_cls.should_run_on_load(self.sim_info):
                return away_action_cls

    def start(self, on_travel_away=False):
        if not self.is_sim_info_valid_to_run_away_actions():
            logger.error('Attempting to start away action tracker on invalid sim info {}.', self._sim_info, owner='jjacobson')
            return
        if self._sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS) and not on_travel_away:
            if self._current_away_action is not None:
                if not self._current_away_action.available_when_instanced:
                    self._current_away_action = None
                    return
                    return
            else:
                return
        if self._current_away_action is not None:
            self._run_current_away_action()
            return
        away_action_cls = self._find_away_action_from_load()
        if away_action_cls is not None:
            self.create_and_apply_away_action(away_action_cls)
            return
        self.reset_to_default_away_action(on_travel_away=on_travel_away)

    def stop(self):
        if self._current_away_action is not None:
            if self._current_away_action.is_running:
                self._current_away_action.stop()
                self._on_away_action_ended(self._current_away_action)
            self._current_away_action = None

    def clean_up(self):
        self.remove_on_away_action_started_callback(self._resend_away_action)
        self.remove_on_away_action_ended_callback(self._resend_away_action)
        self.stop()

    def refresh(self, on_travel_away=False):
        if not self.is_sim_info_valid_to_run_away_actions():
            return
        current_zone = services.current_zone()
        if not current_zone.is_zone_running and not current_zone.are_sims_hitting_their_marks:
            return
        if self._sim_info.zone_id == services.current_zone_id():
            self.stop()
            self._current_away_action = None
        else:
            self.start(on_travel_away=on_travel_away)

    def create_and_apply_away_action(self, away_action_cls, target=None):
        if not self.is_sim_info_valid_to_run_away_actions():
            logger.warn('Attempting to apply away action on invalid sim info {}.', self._sim_info, owner='jjacobson')
            return
        self.stop()
        self._current_away_action = away_action_cls(self, target=target)
        self._run_current_away_action()

    def _away_action_exit_condition_callback(self, _):
        self.reset_to_default_away_action()

    def reset_to_default_away_action(self, on_travel_away=False):
        default_away_action = self.sim_info.get_default_away_action(on_travel_away=on_travel_away)
        if default_away_action is None:
            self.stop()
            return
        self.create_and_apply_away_action(default_away_action)

    def save_away_action_info_to_proto(self, away_action_tracker_proto):
        if self._current_away_action is not None:
            away_action_tracker_proto.away_action.away_action_id = self._current_away_action.guid64
            target = self._current_away_action.target
            if target is not None:
                away_action_tracker_proto.away_action.target_sim_id = target.id

    def load_away_action_info_from_proto(self, away_action_tracker_proto):
        if away_action_tracker_proto.HasField('away_action'):
            away_action_cls = services.get_instance_manager(sims4.resources.Types.AWAY_ACTION).get(away_action_tracker_proto.away_action.away_action_id)
            if away_action_tracker_proto.away_action.HasField('target_sim_id'):
                target = services.sim_info_manager().get(away_action_tracker_proto.away_action.target_sim_id)
            else:
                target = None
            self._current_away_action = away_action_cls(self, target=target)

    def add_on_away_action_started_callback(self, callback):
        self._on_away_action_started.append(callback)

    def remove_on_away_action_started_callback(self, callback):
        self._on_away_action_started.remove(callback)

    def add_on_away_action_ended_callback(self, callback):
        self._on_away_action_ended.append(callback)

    def remove_on_away_action_ended_callback(self, callback):
        self._on_away_action_ended.remove(callback)

