import alarms
import clock
import date_and_time
import enum
import objects
import services
import sims4.service_manager
logger = sims4.log.Logger('Clock', default_owner='trevor')

class SuperSpeedThreeState(enum.Int, export=False):
    __qualname__ = 'SuperSpeedThreeState'
    SS3_STATE_INACTIVE = 0
    SS3_STATE_REQUESTED = 1
    SS3_STATE_ACTIVE = 2

class SuperSpeedThreeService(sims4.service_manager.Service):
    __qualname__ = 'SuperSpeedThreeService'
    TRY_ACTIVATE_SUPER_SPEED_THREE_PING_IN_SIM_MINUTES = 5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ss3_state = SuperSpeedThreeState.SS3_STATE_INACTIVE
        self._try_activate_super_speed_three_alarm = None
        self._sims_told_to_leave = set()

    @property
    def super_speed_three_active(self):
        return self._ss3_state == SuperSpeedThreeState.SS3_STATE_ACTIVE

    def in_or_has_requested_super_speed_three(self):
        return self._ss3_state == SuperSpeedThreeState.SS3_STATE_REQUESTED or self.in_super_speed_three_mode()

    def in_super_speed_three_mode(self):
        clock_service = services.game_clock_service()
        return clock_service.clock_speed() == clock.ClockSpeedMode.SPEED3 and self.super_speed_three_active

    def update(self):
        target_state = self._get_target_state()
        logger.debug('[SS3] update() CALLED\n    target_state: {}, current_state: {}', target_state, self._ss3_state)
        if target_state == SuperSpeedThreeState.SS3_STATE_INACTIVE:
            self._go_inactive()
            return
        if self._ss3_state == SuperSpeedThreeState.SS3_STATE_INACTIVE:
            self._request_super_speed_three(target_state)
        if self._ss3_state == SuperSpeedThreeState.SS3_STATE_REQUESTED:
            if target_state == SuperSpeedThreeState.SS3_STATE_ACTIVE:
                self._activate_super_speed_three(target_state)
            else:
                self._request_super_speed_three(target_state)
        logger.debug('[SS3] update() FINISHED\n    current_state: {}', self._ss3_state)

    def _get_target_state(self):
        if not self._have_all_sims_requested_ss3():
            return SuperSpeedThreeState.SS3_STATE_INACTIVE
        if services.sim_info_manager().are_npc_sims_in_open_streets():
            return SuperSpeedThreeState.SS3_STATE_REQUESTED
        return SuperSpeedThreeState.SS3_STATE_ACTIVE

    @staticmethod
    def _have_all_sims_requested_ss3():
        sim_info_manager = services.sim_info_manager()
        game_clock = services.game_clock_service()
        for instanced_sim in sim_info_manager.instanced_sims_gen(allow_hidden_flags=objects.ALL_HIDDEN_REASONS):
            while instanced_sim.is_selectable or instanced_sim.is_on_active_lot():
                speed_params = game_clock.get_game_speed_request_for_sim_id(instanced_sim.id)
                if speed_params is None:
                    return False
                (_, sim_allows_super_speed_three) = speed_params
                if not sim_allows_super_speed_three:
                    return False
        return True

    def _request_super_speed_three(self, target_state):
        self._ss3_state = SuperSpeedThreeState.SS3_STATE_REQUESTED
        if target_state != SuperSpeedThreeState.SS3_STATE_ACTIVE:
            self._push_open_street_sims_home()
            self._start_activate_super_speed_three_alarm()
        logger.debug('[SS3] _request_super_speed_three CALLED\n    ss3_state set to SS3_STATE_REQUESTED')

    def _push_open_street_sims_home(self):
        sim_info_manager = services.sim_info_manager()
        situation_manager = services.get_zone_situation_manager()
        for instanced_sim in sim_info_manager.instanced_sims_gen():
            while instanced_sim.id not in self._sims_told_to_leave and instanced_sim.is_npc and not instanced_sim.is_on_active_lot():
                situation_manager.make_sim_leave_now_must_run(instanced_sim, super_speed_three_request=True)
                self._sims_told_to_leave.add(instanced_sim.id)

    def _start_activate_super_speed_three_alarm(self):
        if self._try_activate_super_speed_three_alarm is None:
            logger.debug('[SS3] try_activate_super_speed_three_alarm STARTED')
            self._try_activate_super_speed_three_alarm = alarms.add_alarm(self, date_and_time.create_time_span(minutes=self.TRY_ACTIVATE_SUPER_SPEED_THREE_PING_IN_SIM_MINUTES), self._try_activate_super_speed_three_alarm_callback, repeating=True)

    def _stop_use_super_speed_three_alarm(self):
        if self._try_activate_super_speed_three_alarm is not None:
            logger.debug('[SS3] try_activate_super_speed_three_alarm STOPPED')
            alarms.cancel_alarm(self._try_activate_super_speed_three_alarm)
            self._try_activate_super_speed_three_alarm = None

    def _try_activate_super_speed_three_alarm_callback(self, handle):
        logger.debug('[SS3] try_activate_super_speed_three_alarm_callback CALLED')
        self.update()

    def _activate_super_speed_three(self, target_state):
        logger.debug('[SS3] _activate_super_speed_three CALLED ...')
        self._ss3_state = SuperSpeedThreeState.SS3_STATE_ACTIVE
        self._clear_requested_state()
        self._rerequest_speed_three()
        logger.debug('[SS3] _try_activate_super_speed_three SUCCEEDED\n    ss3_state set to SS3_STATE_ACTIVE')

    def _clear_requested_state(self):
        self._sims_told_to_leave.clear()
        self._stop_use_super_speed_three_alarm()

    def _go_inactive(self):
        logger.debug('[SS3] _go_inactive CALLED')
        old_state = self._ss3_state
        self._ss3_state = SuperSpeedThreeState.SS3_STATE_INACTIVE
        self._clear_requested_state()
        if old_state == SuperSpeedThreeState.SS3_STATE_ACTIVE:
            self._rerequest_speed_three()

    @staticmethod
    def _rerequest_speed_three():
        clock_service = services.game_clock_service()
        if clock_service.clock_speed() == clock.ClockSpeedMode.SPEED3:
            clock_service.set_clock_speed(clock.ClockSpeedMode.SPEED3)
            clock_service.send_update()

    def get_debug_information(self):
        return (self._ss3_state, 'Off' if self._try_activate_super_speed_three_alarm is None else 'On', services.sim_info_manager().are_npc_sims_in_open_streets(), self._get_target_state())

