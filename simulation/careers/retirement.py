from distributor.ops import GenericProtocolBufferOp
from distributor.rollback import ProtocolBufferRollback
from distributor.system import Distributor
from objects import ALL_HIDDEN_REASONS
from protocolbuffers.DistributorOps_pb2 import Operation
from singletons import DEFAULT
from tunable_multiplier import TunableMultiplier
from tunable_time import TunableTimeOfDay
from ui.ui_dialog_notification import UiDialogNotification
import alarms
import date_and_time
import event_testing
import protocolbuffers
import services
import sims4.resources

def _get_notification_tunable_factory(**kwargs):
    return UiDialogNotification.TunableFactory(locked_args={'text_tokens': DEFAULT, 'icon': None, 'secondary_icon': None}, **kwargs)

class Retirement:
    __qualname__ = 'Retirement'
    DAILY_PAY_TIME = TunableTimeOfDay(description='\n        The time of day the retirement payout will be given.\n        ', default_hour=7)
    DAILY_PAY_MULTIPLIER = TunableMultiplier.TunableFactory(description='\n        Multiplier on the average daily pay of the retired career the Sim will\n        get every day.\n        ')
    DAILY_PAY_NOTIFICATION = _get_notification_tunable_factory(description='\n        Message when a Sim receives a retirement payout.\n        ')
    RETIREMENT_NOTIFICATION = _get_notification_tunable_factory(description='\n        Message when a Sim retires.\n        ')
    __slots__ = ('_sim_info', '_career_uid', '_alarm_handle')

    def __init__(self, sim_info, retired_career_uid):
        self._sim_info = sim_info
        self._career_uid = retired_career_uid
        self._alarm_handle = None

    @property
    def career_uid(self):
        return self._career_uid

    def start(self, send_retirement_notification=False):
        self._add_alarm()
        self._distribute()
        if send_retirement_notification:
            self.send_dialog(Retirement.RETIREMENT_NOTIFICATION)

    def stop(self):
        self._clear_alarm()

    def _add_alarm(self):
        now = services.time_service().sim_now
        time_span = now.time_till_next_day_time(Retirement.DAILY_PAY_TIME)
        self._alarm_handle = alarms.add_alarm(self._sim_info, time_span, self._alarm_callback, repeating=False, use_sleep_time=False)

    def _clear_alarm(self):
        if self._alarm_handle is not None:
            alarms.cancel_alarm(self._alarm_handle)
            self._alarm_handle = None

    def _alarm_callback(self, alarm_handle):
        self._add_alarm()
        pay = self._get_daily_pay()
        self._sim_info.household.funds.add(pay, protocolbuffers.Consts_pb2.TELEMETRY_MONEY_CAREER, self._sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS))
        self.send_dialog(Retirement.DAILY_PAY_NOTIFICATION, pay)

    def _get_career_history(self):
        return self._sim_info.career_tracker.career_history[self._career_uid]

    def _get_career_track_tuning(self):
        history = self._get_career_history()
        career_track_manager = services.get_instance_manager(sims4.resources.Types.CAREER_TRACK)
        track = career_track_manager.get(history.track_uid)
        return track

    def _get_career_level_tuning(self):
        history = self._get_career_history()
        track = self._get_career_track_tuning()
        level = track.career_levels[history.career_level]
        return level

    def _get_daily_pay(self):
        level = self._get_career_level_tuning()
        ticks = 0
        for (start_ticks, end_ticks) in level.work_schedule(init_only=True).get_schedule_times():
            ticks += end_ticks - start_ticks
        hours = date_and_time.ticks_to_time_unit(ticks, date_and_time.TimeUnit.HOURS, True)
        pay_rate = level.simoleons_per_hour
        for trait_bonus in level.simolean_trait_bonus:
            while self._sim_info.trait_tracker.has_trait(trait_bonus.trait):
                pay_rate += pay_rate*(trait_bonus.bonus*0.01)
        pay_rate = int(pay_rate)
        week_pay = hours*pay_rate
        day_pay = week_pay/7
        resolver = event_testing.resolver.SingleSimResolver(self._sim_info)
        multiplier = Retirement.DAILY_PAY_MULTIPLIER.get_multiplier(resolver)
        adjusted_pay = int(day_pay*multiplier)
        return adjusted_pay

    def send_dialog(self, notification, *additional_tokens, on_response=None):
        if self._sim_info.is_npc:
            return
        resolver = event_testing.resolver.SingleSimResolver(self._sim_info)
        dialog = notification(self._sim_info, resolver=resolver)
        if dialog is not None:
            track = self._get_career_track_tuning()
            level = self._get_career_level_tuning()
            job = level.title(self._sim_info)
            career = track.career_name(self._sim_info)
            tokens = (job, career) + additional_tokens
            dialog.show_dialog(additional_tokens=tokens, icon_override=(track.icon, None), secondary_icon_override=(None, self._sim_info), on_response=on_response)

    def _distribute(self):
        op = protocolbuffers.DistributorOps_pb2.SetCareers()
        with ProtocolBufferRollback(op.careers) as career_op:
            history = self._get_career_history()
            career_op.career_uid = self._career_uid
            career_op.career_level = history.career_level
            career_op.career_track = history.track_uid
            career_op.user_career_level = history.user_level
            career_op.is_retired = True
        distributor = Distributor.instance()
        if distributor is not None:
            distributor.add_op(self._sim_info, GenericProtocolBufferOp(Operation.SET_CAREER, career_op))

