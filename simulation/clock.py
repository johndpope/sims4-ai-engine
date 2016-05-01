import math
from date_and_time import TimeSpan, DateAndTime
from objects import ALL_HIDDEN_REASONS
from services.persistence_service import PersistenceTuning
from sims4.service_manager import Service
from tunable_time import TunableTimeOfWeek
import date_and_time
import distributor.ops
import distributor.system
import enum
import services
import sims4.telemetry
import sims4.tuning.dynamic_enum
import sims4.tuning.tunable
import telemetry_helper
logger = sims4.log.Logger('Clock', default_owner='trevor')
TELEMETRY_GROUP_CLOCK = 'CLCK'
TELEMETRY_HOOK_CHANGE_SPEED_REPORT = 'CHSR'
TELEMETRY_FIELD_CLOCK_SPEED = 'clsp'
TELEMETRY_FIELD_TIME_SPENT_IN_SPEED = 'tmsp'
TELEMETRY_FIELD_PERCENTAGE_TIME_SPENT_IN_SPEED = 'pcsp'
clock_telemetry_writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_CLOCK)


class ClockSpeedMode(enum.Int):
    __qualname__ = 'ClockSpeedMode'
    PAUSED = 0
    NORMAL = 1
    SPEED2 = 2
    SPEED3 = 3
    INTERACTION_STARTUP_SPEED = 4


class GameSpeedChangeSource(enum.Int, export=False):
    __qualname__ = 'GameSpeedChangeSource'
    USER = 0
    GAMEPLAY = 1
    STARTUP = 2


def interval_in_real_time(duration, time_unit):
    if time_unit is date_and_time.TimeUnit.SECONDS:
        return interval_in_real_seconds(duration)
    if time_unit is date_and_time.TimeUnit.MINUTES:
        return interval_in_real_minutes(duration)
    if time_unit is date_and_time.TimeUnit.HOURS:
        return interval_in_real_hours(duration)
    if time_unit is date_and_time.TimeUnit.DAYS:
        return interval_in_real_days(duration)
    if time_unit is date_and_time.TimeUnit.WEEKS:
        return interval_in_real_weeks(duration)


def interval_in_real_seconds(seconds):
    return TimeSpan(seconds * date_and_time.TICKS_PER_REAL_WORLD_SECOND)


def interval_in_real_minutes(minutes):
    return TimeSpan(minutes * date_and_time.TICKS_PER_REAL_WORLD_SECOND *
                    date_and_time.SECONDS_PER_MINUTE)


def interval_in_real_hours(hours):
    return TimeSpan(hours * date_and_time.TICKS_PER_REAL_WORLD_SECOND *
                    date_and_time.SECONDS_PER_HOUR)


def interval_in_real_days(days):
    return TimeSpan(days * date_and_time.TICKS_PER_REAL_WORLD_SECOND *
                    date_and_time.SECONDS_PER_DAY)


def interval_in_real_weeks(weeks):
    return TimeSpan(weeks * date_and_time.TICKS_PER_REAL_WORLD_SECOND *
                    date_and_time.SECONDS_PER_WEEK)


def interval_in_sim_time(duration, time_unit):
    if time_unit is date_and_time.TimeUnit.SECONDS:
        return interval_in_sim_seconds(duration)
    if time_unit is date_and_time.TimeUnit.MINUTES:
        return interval_in_sim_minutes(duration)
    if time_unit is date_and_time.TimeUnit.HOURS:
        return interval_in_sim_hours(duration)
    if time_unit is date_and_time.TimeUnit.DAYS:
        return interval_in_sim_days(duration)
    if time_unit is date_and_time.TimeUnit.WEEKS:
        return interval_in_sim_weeks(duration)


def interval_in_sim_seconds(seconds):
    return TimeSpan(seconds *
                    date_and_time.get_real_milliseconds_per_sim_second())


def interval_in_sim_minutes(minutes):
    return TimeSpan(date_and_time.SECONDS_PER_MINUTE * minutes *
                    date_and_time.get_real_milliseconds_per_sim_second())


def interval_in_sim_hours(hours):
    return TimeSpan(date_and_time.SECONDS_PER_HOUR * hours *
                    date_and_time.get_real_milliseconds_per_sim_second())


def interval_in_sim_days(days):
    return TimeSpan(date_and_time.SECONDS_PER_DAY * days *
                    date_and_time.get_real_milliseconds_per_sim_second())


def interval_in_sim_weeks(weeks):
    return TimeSpan(date_and_time.SECONDS_PER_WEEK * weeks *
                    date_and_time.get_real_milliseconds_per_sim_second())

with sims4.reload.protected(globals()):
    break_point_triggered = False


def on_break_point_hook():
    global break_point_triggered
    break_point_triggered = True


class Clock:
    __qualname__ = 'Clock'
    __slots__ = '_ticks'

    def __init__(self, initial_ticks):
        self._ticks = int(initial_ticks)

    def set_ticks(self, ticks):
        self._ticks = ticks

    def _unit_test_advance_minutes(self, delta):
        pass


class GameClock(Service):
    __qualname__ = 'GameClock'
    NEW_GAME_START_TIME = TunableTimeOfWeek(
        description=
        'The time the game starts at when a player starts a new game.')
    MAX_GAME_CLOCK_TICK_STEP = 5000
    SECONDS_BETWEEN_CLOCK_BROADCAST = 30
    PAUSED_SPEED_MULTIPLIER = 0
    NORMAL_SPEED_MULTIPLIER = 1
    ignore_game_speed_requests = False

    def __init__(self, *args, ticks=None, **kwargs):
        super().__init__()
        date_and_time.send_clock_tuning()
        if ticks is None:
            ticks = services.server_clock_service().ticks()
        self._initial_server_ticks = ticks
        new_game_start_time = GameClock.NEW_GAME_START_TIME()
        self._initial_ticks = new_game_start_time.absolute_ticks()
        self._time_of_last_save = None
        self._client_connect_world_time = None
        self._previous_absolute_ticks = ticks
        self._game_clock = Clock(0)
        self._clock_speed = ClockSpeedMode.PAUSED
        self._previous_non_pause_speed = ClockSpeedMode.NORMAL
        self._tick_to_next_message = 0
        self._error_accumulation = 0
        self._sim_game_speed_requests = {}
        self._last_speed_change_server_time = self._initial_server_ticks
        self._server_ticks_spent_in_speed = [0 for _ in ClockSpeedMode]
        self._client_connect_speed = None
        self._pause_requests = []
        self._zone_init_world_game_time = None
        self._interaction_loading = False
        self._loading_monotonic_ticks = 0
        self.clock_speed_multiplier_type = ClockSpeedMultiplierType.DEFAULT

    def start(self):
        return True

    def stop(self):
        self._game_clock = None
        self._sim_game_speed_requests = None

    @property
    def client_connect_world_time(self):
        return self._client_connect_world_time

    def tick_game_clock(self, absolute_ticks):
        global break_point_triggered
        if self.clock_speed() is not ClockSpeedMode.PAUSED:
            scale = self.current_clock_speed_scale()
            diff = absolute_ticks - self._previous_absolute_ticks
            if diff < 0:
                logger.error(
                    'game clock ticking backwards. absolute ticks: {}, previous absolute ticks: {}',
                    absolute_ticks, self._previous_absolute_ticks)
                return
            if break_point_triggered:
                diff = 1
                self._tick_to_next_message = 0
                break_point_triggered = False
            if diff > GameClock.MAX_GAME_CLOCK_TICK_STEP:
                logger.warn(
                    'Gameplay clock experienced large server tick step: {}. Ignoring large time step and using {} as tick increment.',
                    diff, GameClock.MAX_GAME_CLOCK_TICK_STEP)
                diff = GameClock.MAX_GAME_CLOCK_TICK_STEP
                self._tick_to_next_message = 0
            ideal_tick_increment = diff * scale + self._error_accumulation
            rounded = math.floor(ideal_tick_increment + 0.5)
            error = ideal_tick_increment - rounded
            self._error_accumulation = self._error_accumulation + sims4.math.clamp(
                -1, error, 1)
            self._game_clock.set_ticks(rounded + self._game_clock._ticks)
        self._previous_absolute_ticks = absolute_ticks
        if absolute_ticks > self._tick_to_next_message:
            self._tick_to_next_message = absolute_ticks + self.SECONDS_BETWEEN_CLOCK_BROADCAST * date_and_time.MILLISECONDS_PER_SECOND
            self._sync_clock_and_broadcast_gameclock()

    def enter_zone_spin_up(self):
        self._interaction_loading = True
        self._loading_monotonic_ticks = 0
        self._sync_clock_and_broadcast_gameclock()

    def advance_for_hitting_their_marks(self):
        loading_clock_speed = self._clock_speed_to_scale(
            ClockSpeedMode.INTERACTION_STARTUP_SPEED)
        increment = math.floor(33 * loading_clock_speed)
        self._sync_clock_and_broadcast_gameclock()

    def exit_zone_spin_up(self):
        self._interaction_loading = False
        self._sync_clock_and_broadcast_gameclock()

    def monotonic_time(self):
        return DateAndTime(self._game_clock._ticks +
                           self._loading_monotonic_ticks)

    def send_update(self):
        self._sync_clock_and_broadcast_gameclock()

    def _sync_clock_and_broadcast_gameclock(self):
        (server_time, monotonic_time, game_time, game_speed, clock_speed,
         super_speed) = self._get_game_clock_sync_variables()
        self._broadcast_gameplay_clock_message(
            server_time, monotonic_time, game_time, game_speed, clock_speed,
            super_speed)

    def _broadcast_gameplay_clock_message(self, server_time, monotonic_time,
                                          game_time, game_speed, clock_speed,
                                          super_speed):
        op = distributor.ops.SetGameTime(server_time, monotonic_time,
                                         game_time, game_speed, clock_speed,
                                         self._initial_ticks, super_speed)
        distributor.system.Distributor.instance().add_op_with_no_owner(op)

    def now(self):
        return DateAndTime(self._game_clock._ticks + self._initial_ticks)

    def request_pause(self, pause_source_name):
        self._pause_requests.append(pause_source_name)
        self._sync_clock_and_broadcast_gameclock()

    def unrequest_pause(self, pause_source_name):
        self._pause_requests.remove(pause_source_name)
        self._sync_clock_and_broadcast_gameclock()

    def set_clock_speed(self,
                        speed,
                        change_source=GameSpeedChangeSource.GAMEPLAY) -> bool:
        if speed is None or speed < 0 or speed > ClockSpeedMode.INTERACTION_STARTUP_SPEED:
            logger.error(
                'Attempting to set clock speed to something invalid: {}',
                speed)
            return False
        logger.debug(
            'set_clock_speed CALLED ...\n    speed: {}, change_source: {}',
            speed, change_source)
        if self._pause_requests:
            return False
        if change_source == GameSpeedChangeSource.USER and not services.current_zone(
        ).is_zone_running:
            logger.debug("set_clock_speed FAILED\n    zone isn't running")
            return False
        if change_source == GameSpeedChangeSource.GAMEPLAY and self._clock_speed == ClockSpeedMode.PAUSED and speed != ClockSpeedMode.PAUSED:
            if self._previous_non_pause_speed > speed:
                self._previous_non_pause_speed = speed
            logger.debug(
                'set_clock_speed SUCCEEDED\n    gameplay request to bring game out of PAUSED. caching for the unpause.')
            return True
        if speed != self._clock_speed:
            if self._clock_speed != ClockSpeedMode.INTERACTION_STARTUP_SPEED and self._clock_speed != ClockSpeedMode.PAUSED:
                self._previous_non_pause_speed = self._clock_speed
            self._update_time_spent_in_speed(self._clock_speed)
        if speed == ClockSpeedMode.NORMAL:
            self._set_clock_speed_multiplier_type(
                ClockSpeedMultiplierType.DEFAULT)
        (server_time, monotonic_time, game_time, _, _,
         _) = self._get_game_clock_sync_variables()
        self._clock_speed = speed
        ss3_service = services.get_super_speed_three_service()
        ss3_service.update()
        in_ss3 = ss3_service.in_super_speed_three_mode()
        game_speed = self.current_clock_speed_scale()
        self._broadcast_gameplay_clock_message(server_time, monotonic_time,
                                               game_time, game_speed,
                                               self._clock_speed, in_ss3)
        logger.debug('set_clock_speed SUCCEEDED. speed: {}, change_source: {}',
                     speed, change_source)
        return True

    def previous_non_pause_speed(self):
        return self._previous_non_pause_speed

    def clock_speed(self):
        if self._pause_requests:
            return ClockSpeedMode.PAUSED
        return self._clock_speed

    def current_clock_speed_scale(self):
        return self._clock_speed_to_scale(self.clock_speed())

    def _clock_speed_to_scale(self, clock_speed):
        if clock_speed == ClockSpeedMode.PAUSED:
            return self.PAUSED_SPEED_MULTIPLIER
        if clock_speed == ClockSpeedMode.NORMAL:
            return self.NORMAL_SPEED_MULTIPLIER
        if clock_speed == ClockSpeedMode.SPEED2:
            return ClockSpeedMultipliers.speed_two_multiplier(
                self.clock_speed_multiplier_type)
        if clock_speed == ClockSpeedMode.SPEED3:
            if services.get_super_speed_three_service(
            ).super_speed_three_active:
                return ClockSpeedMultipliers.super_speed_three_multiplier(
                    self.clock_speed_multiplier_type)
            return ClockSpeedMultipliers.speed_three_multiplier(
                self.clock_speed_multiplier_type)
        if clock_speed == ClockSpeedMode.INTERACTION_STARTUP_SPEED:
            return ClockSpeedMultipliers.get_interaction_startup_speed_multiplier(
            )

    def _get_game_clock_sync_variables(self):
        server_time = services.server_clock_service().ticks()
        if self._interaction_loading:
            game_time = self._loading_monotonic_ticks
            monotonic_time = self._loading_monotonic_ticks
            game_speed = self._clock_speed_to_scale(
                ClockSpeedMode.INTERACTION_STARTUP_SPEED)
            clock_speed = ClockSpeedMode.INTERACTION_STARTUP_SPEED
            super_speed = False
        else:
            game_time = self._game_clock._ticks
            monotonic_time = game_time + self._loading_monotonic_ticks
            game_speed = self.current_clock_speed_scale()
            clock_speed = self.clock_speed()
            super_speed = services.get_super_speed_three_service(
            ).in_super_speed_three_mode()
        return (server_time, monotonic_time, game_time, game_speed,
                clock_speed, super_speed)

    def on_client_connect(self, client):
        if client.account.save_slot_id is not None:
            save_slot_data_msg = services.get_persistence_service(
            ).get_save_slot_proto_buff()
            if save_slot_data_msg.HasField('gameplay_data'):
                world_game_time = save_slot_data_msg.gameplay_data.world_game_time
                current_ticks = self.now().absolute_ticks()
                difference = world_game_time - current_ticks
                self._add_to_game_time_and_send_update(difference)
                self._client_connect_world_time = self.now()
                logger.debug('Clock.on_client_connect {}', self.now())

    def _should_restore_saved_client_connect_speed(self):
        if services.current_zone().is_first_visit_to_zone:
            return False
        if self._client_connect_speed is None:
            return False
        if self.time_has_passed_in_world_since_zone_save():
            return False
        return True

    def restore_saved_clock_speed(self):
        if self._should_restore_saved_client_connect_speed():
            self.set_clock_speed(self._client_connect_speed,
                                 change_source=GameSpeedChangeSource.STARTUP)
            self._client_connect_speed = None
        else:
            self.set_clock_speed(ClockSpeedMode.NORMAL,
                                 change_source=GameSpeedChangeSource.STARTUP)
        self._sync_clock_and_broadcast_gameclock()

    def on_client_disconnect(self, client):
        self._update_time_spent_in_speed(self.clock_speed())
        total_time_spent = services.server_clock_service().ticks(
        ) - self._initial_server_ticks
        for speed in ClockSpeedMode:
            time_spent_in_speed = self._server_ticks_spent_in_speed[speed]
            precentage_time_in_speed = time_spent_in_speed / float(
                total_time_spent) * 100
            time_spent_in_speed = time_spent_in_speed / date_and_time.TICKS_PER_REAL_WORLD_SECOND
            with telemetry_helper.begin_hook(
                    clock_telemetry_writer,
                    TELEMETRY_HOOK_CHANGE_SPEED_REPORT,
                    household=client.household) as hook:
                hook.write_int(TELEMETRY_FIELD_CLOCK_SPEED, speed)
                hook.write_int(TELEMETRY_FIELD_TIME_SPENT_IN_SPEED,
                               time_spent_in_speed)
                hook.write_float(
                    TELEMETRY_FIELD_PERCENTAGE_TIME_SPENT_IN_SPEED,
                    precentage_time_in_speed)
        if GameClock._is_single_player():
            self.set_clock_speed(ClockSpeedMode.PAUSED)
            self._time_of_last_save = self.now()

    @staticmethod
    def _is_single_player():
        return len(services.current_zone().client_manager.values()) < 2

    def set_game_time(self, hours, minutes, seconds):
        current_date_and_time = self.now()
        days = int(current_date_and_time.absolute_days())
        current_time_minus_days = current_date_and_time - DateAndTime(
            interval_in_sim_days(days).in_ticks())
        requested_time = interval_in_sim_hours(
            hours) + interval_in_sim_minutes(
                minutes) + interval_in_sim_seconds(seconds)
        time_difference = requested_time - current_time_minus_days
        if time_difference.in_hours() < 0:
            time_difference = time_difference + interval_in_sim_hours(24)
        self._add_to_game_time_and_send_update(time_difference.in_ticks())

    def advance_game_time(self, hours=0, minutes=0, seconds=0):
        requested_increment = interval_in_sim_hours(
            hours) + interval_in_sim_minutes(
                minutes) + interval_in_sim_seconds(seconds)
        self._add_to_game_time_and_send_update(requested_increment.in_ticks())

    def _add_to_game_time_and_send_update(self, time_difference_in_ticks):
        self._sync_clock_and_broadcast_gameclock()

    def get_game_speed_request_for_sim_id(self, sim_id):
        return self._sim_game_speed_requests.get(sim_id)

    def register_game_speed_change_request(self, sim, game_speed_params):
        (game_speed, _) = game_speed_params
        if not sim.sim_info.is_npc:
            self._sim_game_speed_requests[sim.id] = game_speed_params
            lowest_requested_speed = game_speed
            for sim_in_household in sim.household.instanced_sims_gen(
                    allow_hidden_flags=ALL_HIDDEN_REASONS):
                speed_params = self._sim_game_speed_requests.get(
                    sim_in_household.id)
                if speed_params is not None:
                    (speed, _) = speed_params
                    if speed < lowest_requested_speed:
                        lowest_requested_speed = speed
                        return
                else:
                    return
            services.get_super_speed_three_service().update()
            self.set_clock_speed(lowest_requested_speed)

    def stop_super_speed_three(self):
        for (sim_id,
             (speed,
              ss3_requested)) in tuple(self._sim_game_speed_requests.items()):
            while ss3_requested:
                self._sim_game_speed_requests[sim_id] = (speed, False)
        services.get_super_speed_three_service().update()

    def unregister_game_speed_change_request(self, sim_id):
        if sim_id in self._sim_game_speed_requests:
            sim_info = services.sim_info_manager().get(sim_id)
            if sim_info is not None:
                for sim_in_household in sim_info.household.instanced_sims_gen(
                        allow_hidden_flags=ALL_HIDDEN_REASONS):
                    while sim_in_household.id not in self._sim_game_speed_requests:
                        break
                if self.clock_speed() > ClockSpeedMode.NORMAL:
                    self.set_clock_speed(ClockSpeedMode.NORMAL)
            del self._sim_game_speed_requests[sim_id]
            services.get_super_speed_three_service().update()

    def game_speed_requests_gen(self):
        yield self._sim_game_speed_requests.items()

    def _update_time_spent_in_speed(self, current_speed):
        server_time = services.server_clock_service().ticks()
        server_ticks_spent_in_current_speed = server_time - self._last_speed_change_server_time
        self._server_ticks_spent_in_speed[
            current_speed] += server_ticks_spent_in_current_speed
        self._last_speed_change_server_time = server_time

    def time_until_hour_of_day(self, hour_of_day):
        cur_hour = self.now().hour()
        if cur_hour <= hour_of_day:
            hours_from_now = hour_of_day - cur_hour
        else:
            hours_from_now = 24 - cur_hour + hour_of_day
        return date_and_time.create_time_span(hours=hours_from_now)

    def precise_time_until_hour_of_day(self, hour_of_day):
        cur_hour = self.now().hour()
        cur_day = int(self.now().absolute_days())
        if cur_hour < hour_of_day:
            future = date_and_time.create_date_and_time(days=cur_day,
                                                        hours=hour_of_day)
        else:
            future = date_and_time.create_date_and_time(days=cur_day + 1,
                                                        hours=hour_of_day)
        return future - self.now()

    def save(self, zone_data=None, save_slot_data=None, **kwargs):
        now_ticks = self.now().absolute_ticks()
        if zone_data is not None:
            zone_data.gameplay_zone_data.game_time = now_ticks
            if self.clock_speed() == ClockSpeedMode.PAUSED:
                zone_data.gameplay_zone_data.clock_speed_mode = ClockSpeedMode.PAUSED
            else:
                zone_data.gameplay_zone_data.clock_speed_mode = ClockSpeedMode.NORMAL
        if save_slot_data is not None:
            save_slot_data.gameplay_data.world_game_time = now_ticks

    def setup(self, gameplay_zone_data=None, save_slot_data=None):
        if gameplay_zone_data is None:
            return
        world_game_time = self._initial_ticks
        if save_slot_data is not None and save_slot_data.HasField(
                'gameplay_data'):
            world_game_time = save_slot_data.gameplay_data.world_game_time
            self._zone_init_world_game_time = DateAndTime(world_game_time)
        initial_time = world_game_time
        if gameplay_zone_data.HasField('game_time'):
            saved_ticks = gameplay_zone_data.game_time
            tick_diff = world_game_time - saved_ticks
            time_diff = TimeSpan(tick_diff)
            self._time_of_last_save = DateAndTime(saved_ticks)
            if time_diff.in_minutes(
            ) < PersistenceTuning.MAX_LOT_SIMULATE_ELAPSED_TIME:
                initial_time = saved_ticks
            else:
                max_minutes = date_and_time.create_date_and_time(
                    minutes=PersistenceTuning.MAX_LOT_SIMULATE_ELAPSED_TIME)
                initial_time = world_game_time - max_minutes.absolute_ticks()
        self._initial_ticks = initial_time
        if gameplay_zone_data.HasField('clock_speed_mode'):
            self._client_connect_speed = ClockSpeedMode(
                gameplay_zone_data.clock_speed_mode)
        else:
            self._client_connect_speed = ClockSpeedMode.NORMAL

    def time_of_last_save(self):
        if self._time_of_last_save is None:
            return GameClock.NEW_GAME_START_TIME()
        return self._time_of_last_save

    def has_time_of_last_save(self):
        return self._time_of_last_save is not None

    def zone_init_world_game_time(self):
        if self._zone_init_world_game_time is None:
            return DateAndTime(self._initial_ticks)
        return self._zone_init_world_game_time

    def time_elapsed_since_last_save(self):
        if self._client_connect_world_time is None:
            return TimeSpan.ZERO
        time_elapsed = self._client_connect_world_time - self.time_of_last_save(
        )
        return time_elapsed

    def time_has_passed_in_world_since_zone_save(self):
        if services.current_zone().is_first_visit_to_zone:
            return False
        time_elapsed = self.time_elapsed_since_last_save()
        if time_elapsed > TimeSpan.ZERO:
            return True
        return False

    def _set_clock_speed_multiplier_type(self, clock_speed_multiplier_type):
        if self.clock_speed_multiplier_type != clock_speed_multiplier_type:
            self.clock_speed_multiplier_type = clock_speed_multiplier_type
            self._update_game_speed_after_multiplier_change()
            return True
        return False

    def _update_game_speed_after_multiplier_change(self):
        clock_speed = self.clock_speed()
        if clock_speed == ClockSpeedMode.SPEED2 or clock_speed == ClockSpeedMode.SPEED3:
            self.set_clock_speed(clock_speed)


class ServerClock(Service):
    __qualname__ = 'ServerClock'

    def __init__(self, *args, ticks=0, **kwargs):
        super().__init__()
        self._server_clock = Clock(ticks)

    def tick_server_clock(self, absolute_ticks):
        self._server_clock.set_ticks(absolute_ticks)

    def start(self):
        return True

    def stop(self):
        self._server_clock = None

    def now(self):
        return DateAndTime(self._server_clock._ticks)

    def ticks(self):
        return self._server_clock._ticks


class ClockSpeedMultiplierType(sims4.tuning.dynamic_enum.DynamicEnumLocked):
    __qualname__ = 'ClockSpeedMultiplierType'
    DEFAULT = 0
    LOW_PERFORMANCE = 1


class TunableClockSpeedMultipliers(sims4.tuning.tunable.TunableTuple):
    __qualname__ = 'TunableClockSpeedMultipliers'

    def __init__(self, **kwargs):
        super().__init__(
            speed_two_multiplier=sims4.tuning.tunable.Tunable(
                description=
                '\n                How much faster speed two goes than normal speed. The game clock will\n                have its speed multiplied by this number.\n                ',
                tunable_type=float,
                default=3.0),
            speed_three_multiplier=sims4.tuning.tunable.Tunable(
                description=
                '\n                How much faster speed three goes than normal speed. The game clock will\n                have its speed multiplied by this number.\n                ',
                tunable_type=float,
                default=7.0),
            super_speed_three_multiplier=sims4.tuning.tunable.Tunable(
                description=
                '\n                How much faster super speed three goes than normal speed. The\n                game clock will have its speed multiplied by this number.\n                ',
                tunable_type=float,
                default=36.0),
            **kwargs)


class ClockSpeedMultipliers:
    __qualname__ = 'ClockSpeedMultipliers'
    TUNABLE_INTERACTION_STARTUP_SPEED_MULTIPLIER = sims4.tuning.tunable.Tunable(
        description=
        '\n        How much faster preroll autonomy speed goes than normal speed.\n        ',
        tunable_type=float,
        default=5.0)
    CLOCK_SPEED_TYPE_MULTIPLIER_MAP = sims4.tuning.tunable.TunableMapping(
        description=
        '\n        A mapping of ClockSpeedMultiplierTypes to clock speed multipliers.\n        ',
        key_type=sims4.tuning.tunable.TunableEnumEntry(
            description=
            '\n            The ClockSpeedMultiplier to which we apply the multipliers.\n            ',
            tunable_type=ClockSpeedMultiplierType,
            default=ClockSpeedMultiplierType.DEFAULT),
        key_name='Clock Speed Multiplier Type',
        value_type=TunableClockSpeedMultipliers(),
        value_name='Clock Speed Multipliers')

    @classmethod
    def get_interaction_startup_speed_multiplier(cls):
        return cls.TUNABLE_INTERACTION_STARTUP_SPEED_MULTIPLIER

    @classmethod
    def speed_two_multiplier(cls, clock_speed_multiplier_type):
        return cls.CLOCK_SPEED_TYPE_MULTIPLIER_MAP.get(
            clock_speed_multiplier_type).speed_two_multiplier

    @classmethod
    def speed_three_multiplier(cls, clock_speed_multiplier_type):
        return cls.CLOCK_SPEED_TYPE_MULTIPLIER_MAP.get(
            clock_speed_multiplier_type).speed_three_multiplier

    @classmethod
    def super_speed_three_multiplier(cls, clock_speed_multiplier_type):
        return cls.CLOCK_SPEED_TYPE_MULTIPLIER_MAP.get(
            clock_speed_multiplier_type).super_speed_three_multiplier
