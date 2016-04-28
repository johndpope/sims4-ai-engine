from protocolbuffers import DistributorOps_pb2
import protocolbuffers
from careers.career_base import CareerHistory
from careers.career_tuning import Career
from careers.retirement import Retirement
from date_and_time import DateAndTime, TimeSpan, DATE_AND_TIME_ZERO
from distributor.rollback import ProtocolBufferRollback
import distributor
import services
import sims4.resources

class CareerTracker:
    __qualname__ = 'CareerTracker'

    def __init__(self, sim_info):
        self._sim_info = sim_info
        self._careers = {}
        self._career_history = {}
        self._retirement = None

    @property
    def careers(self):
        return self._careers

    def resend_career_data(self):
        if self._sim_info.is_npc:
            return
        if services.current_zone().is_zone_shutting_down:
            return
        op = distributor.ops.SetCareers(self._careers)
        distributor.system.Distributor.instance().add_op(self._sim_info, op)

    def _at_work_infos(self):
        at_work_infos = []
        for career in self._careers.values():
            at_work_info = DistributorOps_pb2.SetAtWorkInfo()
            at_work_info.career_uid = career.guid64
            at_work_info.work_state = career.get_work_state()
            at_work_infos.append(at_work_info)
        return at_work_infos

    def resend_at_work_infos(self):
        if self._sim_info.is_npc:
            return
        op = distributor.ops.SetAtWorkInfos(self._at_work_infos())
        distributor.system.Distributor.instance().add_op(self._sim_info, op)

    @property
    def has_career(self):
        return bool(self._careers)

    def has_career_outfit(self):
        return any(career.has_outfit() for career in self._careers.values())

    def _on_confirmation_dialog_response(self, dialog, new_career):
        if dialog.accepted:
            if new_career.can_quit:
                quittable_careers = self.quittable_careers()
                for career_uid in quittable_careers:
                    self.remove_career(career_uid)
            self.add_career(new_career)

    def add_career(self, new_career, show_confirmation_dialog=False):
        if self._retirement is not None:
            self._retirement.send_dialog(Career.UNRETIRE_DIALOG, new_career.start_track.career_name(self._sim_info), on_response=lambda dialog: self._on_confirmation_dialog_response(dialog, new_career))
            return
        if show_confirmation_dialog and new_career.can_quit:
            quittable_careers = self.quittable_careers()
            if quittable_careers:
                career = next(iter(quittable_careers.values()))
                career.send_career_message(Career.SWITCH_JOBS_DIALOG, new_career.start_track.career_name(self._sim_info), on_response=lambda dialog: self._on_confirmation_dialog_response(dialog, new_career))
                return
        self.end_retirement()
        self._careers[new_career.guid64] = new_career
        new_career.join_career(career_history=self._career_history)
        self.resend_career_data()

    def remove_career(self, career_uid, post_quit_msg=True):
        if career_uid in self._careers:
            career = self._careers[career_uid]
            career.career_stop()
            career.quit_career(post_quit_msg=post_quit_msg)

    def get_career_by_uid(self, career_uid):
        if career_uid in self._careers:
            return self._careers[career_uid]

    def quittable_careers(self):
        quittable_careers = dict(self._careers)
        for (career_uid, career_instance) in self._careers.items():
            while not career_instance.can_quit:
                del quittable_careers[career_uid]
        return quittable_careers

    def conflicting_with_careers(self, other_career):
        for (_, career_instance) in self._careers.items():
            while career_instance.master_scheduler().check_for_conflict(other_career.master_scheduler()):
                return True
        return False

    def get_at_work_career(self):
        for career in self._careers.values():
            while career.currently_at_work:
                return career

    @property
    def currently_at_work(self):
        for career in self._careers.values():
            while career.currently_at_work:
                return True
        return False

    @property
    def currently_during_work_hours(self):
        for career in self._careers.values():
            while career.is_work_time:
                return True
        return False

    @property
    def career_currently_within_hours(self):
        for career in self._careers.values():
            while career.is_work_time:
                return career

    def get_currently_at_work_career(self):
        for career in self._careers.values():
            while career.currently_at_work:
                return career

    def career_leave(self, career):
        self.update_history(career, from_leave=True)
        del self._careers[career.guid64]

    def get_busy_times(self):
        busy_times = list(career.get_busy_time_periods() for career in self._careers.values())
        return busy_times

    @property
    def career_history(self):
        return self._career_history

    def update_history(self, career, from_leave=False):
        level = self.get_highest_level_reached(career.guid64)
        if career.user_level > level:
            level = career.user_level
        time_left = services.time_service().sim_now if from_leave else DATE_AND_TIME_ZERO
        self._career_history[career.guid64] = CareerHistory(career.level, career.user_level, time_left, career.current_track_tuning.guid64, level)

    def get_highest_level_reached(self, career_uid):
        entry = self._career_history.get(career_uid)
        if entry is not None:
            return entry.highest_level
        return 0

    def retire_career(self, career_uid):
        for uid in list(self._careers):
            self.remove_career(uid, post_quit_msg=False)
        self._retirement = Retirement(self._sim_info, career_uid)
        self._retirement.start(send_retirement_notification=True)

    def end_retirement(self):
        if self._retirement is not None:
            self._retirement.stop()
            self._retirement = None

    @property
    def retired_career_uid(self):
        if self._retirement is not None:
            return self._retirement.career_uid
        return 0

    def start_retirement(self):
        if self._retirement is not None:
            self._retirement.start()

    def on_sim_added_to_skewer(self):
        self.resend_career_data()
        self.resend_at_work_infos()

    def on_loading_screen_animation_finished(self):
        for career in self._careers.values():
            career.on_loading_screen_animation_finished()

    def on_sim_startup(self):
        for career in self._careers.values():
            career.startup_career()

    def on_death(self):
        for uid in list(self._careers):
            self.remove_career(uid, post_quit_msg=False)
        self.end_retirement()

    def clean_up(self):
        for career in self._careers.values():
            career.career_stop()
        self._careers.clear()
        self.end_retirement()

    def on_situation_request(self, situation):
        career = self.get_at_work_career()
        if career is not None:
            career.leave_work_early()

    def save(self):
        save_data = protocolbuffers.SimObjectAttributes_pb2.PersistableSimCareers()
        for career in self._careers.values():
            with ProtocolBufferRollback(save_data.careers) as careers_proto:
                careers_proto.career_uid = career.guid64
                careers_proto.track_uid = career.current_track_tuning.guid64
                careers_proto.track_level = career.level
                careers_proto.user_display_level = career.user_level
                careers_proto.attended_work = career.attended_work
                careers_proto.called_in_sick = career.called_in_sick
                careers_proto.pending_promotion = career._pending_promotion
                careers_proto.company_name_hash = career._company_name
                careers_proto.active_situation_id = career._career_situation_id
                if career._career_situation is not None:
                    careers_proto.career_situation_guid = career._career_situation.guid64
                if career._current_work_start is not None:
                    careers_proto.current_work_start = career._current_work_start.absolute_ticks()
                    careers_proto.current_work_end = career._current_work_end.absolute_ticks()
                    careers_proto.current_work_duration = career._current_work_duration.in_ticks()
                while career._join_time is not None:
                    careers_proto.join_time = career._join_time.absolute_ticks()
        for (career_uid, history) in self._career_history.items():
            with ProtocolBufferRollback(save_data.career_history) as career_history_proto:
                career_history_proto.career_uid = career_uid
                career_history_proto.track_uid = history.track_uid
                career_history_proto.track_level = history.career_level
                career_history_proto.user_display_level = history.user_level
                career_history_proto.time_left = history.time_left.absolute_ticks()
                career_history_proto.highest_level = history.highest_level
        if self._retirement is not None:
            save_data.retirement_career_uid = self._retirement.career_uid
        return save_data

    def activate_career_aspirations(self):
        for career in self._careers.values():
            career_aspiration = career._current_track.career_levels[career._level].get_aspiration()
            while career_aspiration is not None:
                career_aspiration.register_callbacks()
                self._sim_info.aspiration_tracker.process_test_events_for_aspiration(career_aspiration)

    def load(self, save_data, skip_load=False):
        self._careers.clear()
        for career_save_data in save_data.careers:
            career_uid = career_save_data.career_uid
            career = services.get_instance_manager(sims4.resources.Types.CAREER).get(career_uid)
            while career is not None:
                career_inst = career(self._sim_info)
                career_inst._current_track = services.get_instance_manager(sims4.resources.Types.CAREER_TRACK).get(career_save_data.track_uid)
                career_inst._level = career_save_data.track_level
                career_inst._user_level = career_save_data.user_display_level
                career_inst._company_name = career_save_data.company_name_hash
                if skip_load:
                    career_inst._join_time = services.time_service().sim_now
                else:
                    career_inst._join_time = DateAndTime(career_save_data.join_time)
                    career_inst._attended_work = career_save_data.attended_work
                    career_inst._called_in_sick = career_save_data.called_in_sick
                    career_inst._pending_promotion = career_save_data.pending_promotion
                    career_inst._career_situation_id = career_save_data.active_situation_id
                    if career_save_data.career_situation_guid != 0:
                        career_inst._career_situation = services.get_instance_manager(sims4.resources.Types.CAREER_SITUATION).get(career_save_data.career_situation_guid)
                    if career_save_data.HasField('current_work_start'):
                        career_inst._current_work_start = DateAndTime(career_save_data.current_work_start)
                        career_inst._current_work_end = DateAndTime(career_save_data.current_work_end)
                        career_inst._current_work_duration = TimeSpan(career_save_data.current_work_duration)
                career_inst.career_start(is_load=True)
                self._careers[career_uid] = career_inst
        self._career_history.clear()
        for history_entry in save_data.career_history:
            if skip_load and history_entry.career_uid not in self._careers:
                pass
            self._career_history[history_entry.career_uid] = CareerHistory(history_entry.track_level, history_entry.user_display_level, DateAndTime(history_entry.time_left), history_entry.track_uid, history_entry.highest_level)
        self._retirement = None
        if save_data.HasField('retirement_career_uid'):
            retired_career = save_data.retirement_career_uid
            self._retirement = Retirement(self._sim_info, retired_career)

