from clock import ClockSpeedMode, GameSpeedChangeSource
from sims4.commands import CommandType
import clock
import services
import sims4.commands
import telemetry_helper
TELEMETRY_GROUP_CLOCK = 'CLCK'
TELEMETRY_HOOK_CHANGE_SPEED_GAME = 'CHSG'
TELEMETRY_FIELD_CLOCK_SPEED = 'clsp'
clock_telemetry_writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_CLOCK)

@sims4.commands.Command('clock.pause', command_type=CommandType.Live)
def pause(speed_change_source='USER', _connection=None):
    speed_change_source = speed_change_source.upper()
    change_source = GameSpeedChangeSource(speed_change_source)
    if change_source is not None:
        services.game_clock_service().set_clock_speed(ClockSpeedMode.PAUSED, change_source=change_source)
        return True
    return False

@sims4.commands.Command('clock.unpause', command_type=CommandType.Live)
def unpause(speed_change_source='USER', _connection=None):
    speed_change_source = speed_change_source.upper()
    change_source = GameSpeedChangeSource(speed_change_source)
    if change_source is not None:
        previous_speed = services.game_clock_service().previous_non_pause_speed()
        if previous_speed is not None:
            services.game_clock_service().set_clock_speed(previous_speed, change_source=change_source)
            return True
    return False

@sims4.commands.Command('clock.request_pause', command_type=CommandType.Live)
def request_pause(pause_handle_name='Pause Handle From Command', _connection=None):
    services.game_clock_service().request_pause(pause_handle_name)
    return False

@sims4.commands.Command('clock.unrequest_pause', command_type=CommandType.Live)
def unrequest_pause(pause_handle_name='Pause Handle From Command', _connection=None):
    services.game_clock_service().unrequest_pause(pause_handle_name)
    return False

@sims4.commands.Command('clock.toggle_pause_unpause', command_type=CommandType.Live)
def toggle_pause_unpause(_connection=None):
    if services.game_clock_service().clock_speed() == ClockSpeedMode.PAUSED:
        speed = services.game_clock_service().previous_non_pause_speed()
    else:
        speed = ClockSpeedMode.PAUSED
    send_clock_telemetry_data(_connection, speed)
    services.game_clock_service().set_clock_speed(speed, change_source=GameSpeedChangeSource.USER)

@sims4.commands.Command('clock.setanimspeed')
def set_anim_speed(scale:float=1, _connection=None):
    output = sims4.commands.Output(_connection)
    if scale > 0.05:
        sims4.commands.execute('qa.broadcast animation.anim_speed {}'.format(scale), _connection)
        output('Setting scale to {}'.format(scale))
    else:
        output('Scale has to be more than 0.05')

@sims4.commands.Command('clock.setspeed', command_type=CommandType.Live)
def set_speed(speed='one', _connection=None):
    output = sims4.commands.Output(_connection)
    speed = speed.lower()
    if speed == 'one':
        speed = ClockSpeedMode.NORMAL
    elif speed == 'two':
        speed = ClockSpeedMode.SPEED2
    elif speed == 'three':
        speed = ClockSpeedMode.SPEED3
    send_clock_telemetry_data(_connection, speed)
    services.game_clock_service().set_clock_speed(speed, change_source=GameSpeedChangeSource.USER)

@sims4.commands.Command('clock.setgametime')
def set_game_time(hours:int=0, minutes:int=0, seconds:int=0, _connection=None):
    previous_time = services.time_service().sim_now
    services.game_clock_service().set_game_time(hours, minutes, seconds)
    new_time = services.time_service().sim_now
    services.sim_info_manager().auto_satisfy_sim_motives()
    output = sims4.commands.Output(_connection)
    output('previous time = {}'.format(previous_time))
    output('new time = {}'.format(new_time))

@sims4.commands.Command('clock.now')
def now(_connection=None):
    output = sims4.commands.Output(_connection)
    game_clock_ticks = services.time_service().sim_now.absolute_ticks()
    server_ticks = services.server_clock_service().ticks()
    output('Gameclock ticks: {} Server Ticks: {}'.format(game_clock_ticks, server_ticks))
    timeline_now = services.time_service().sim_now
    game_clock_now = services.game_clock_service().now()
    output('Sim timeline now: {}'.format(timeline_now))
    output('Game clock now: {}'.format(game_clock_now))

@sims4.commands.Command('clock.advance_game_time')
def advance_game_time(hours:int=0, minutes:int=0, seconds:int=0, _connection=None):
    previous_time = services.time_service().sim_now
    services.game_clock_service().advance_game_time(hours=hours, minutes=minutes, seconds=seconds)
    new_time = services.time_service().sim_now
    services.sim_info_manager().auto_satisfy_sim_motives()
    output = sims4.commands.Output(_connection)
    output('previous time = {}'.format(previous_time))
    output('new time = {}'.format(new_time))

@sims4.commands.Command('clock.restore_saved_clock_speed', command_type=CommandType.Live)
def restore_saved_clock_speed(_connection=None):
    services.current_zone().on_loading_screen_animation_finished()

@sims4.commands.Command('clock.list_pause_requests', command_type=CommandType.DebugOnly)
def list_pause_requests(_connection=None):
    output = sims4.commands.Output(_connection)
    output('current pause requests:')
    index = 0
    for pause_request in services.game_clock_service()._pause_requests:
        output('{}) {}'.format(index, pause_request))
        index += 1
    return True

@sims4.commands.Command('clock.clear_pause_requests', command_type=CommandType.DebugOnly)
def clear_pause_requests(_connection=None):
    output = sims4.commands.Output(_connection)
    output('Clearing all pause requests:')
    game_clock_service = services.game_clock_service()
    if game_clock_service._pause_requests:
        game_clock_service._pause_requests = []
        game_clock_service._sync_clock_and_broadcast_gameclock()
    return True

def send_clock_telemetry_data(_connection, speed):
    if services.game_clock_service().clock_speed() != speed:
        client = services.client_manager().get(_connection)
        with telemetry_helper.begin_hook(clock_telemetry_writer, TELEMETRY_HOOK_CHANGE_SPEED_GAME, household=client.household) as hook:
            hook.write_int(TELEMETRY_FIELD_CLOCK_SPEED, speed)

ENTER_BUILDBUY_PAUSE_HANDLE = 'Entering Build Buy'

@sims4.commands.Command('clock.build_buy_pause_unpause', command_type=CommandType.Live)
def build_buy_pause_unpause(is_pause:bool=True, _connection=None):
    game_clock_service = services.game_clock_service()
    if is_pause:
        game_clock_service.request_pause(ENTER_BUILDBUY_PAUSE_HANDLE)
    else:
        game_clock_service.unrequest_pause(ENTER_BUILDBUY_PAUSE_HANDLE)
    return True

@sims4.commands.Command('clock.set_speed_multiplier_type', command_type=CommandType.Automation)
def set_speed_multipliers(speed_multiplier_type, _connection=None):
    try:
        multiplier_type = clock.ClockSpeedMultiplierType(speed_multiplier_type)
        services.game_clock_service()._set_clock_speed_multiplier_type(multiplier_type)
    except ValueError:
        sims4.commands.CheatOutput(_connection)('{} is not a valid ClockSpeedMultiplierType entry'.format(speed_multiplier_type))

@sims4.commands.Command('clock.show_ss3_info', command_type=CommandType.Automation)
def show_ss3_info(_connection=None):
    (ss3_state, alarm, sims_in_open_streets, target_state) = services.get_super_speed_three_service().get_debug_information()
    game_clock = services.game_clock_service()
    output = sims4.commands.Output(_connection)
    output('-=-=-=-=-=-=-=-=-\nSUPER SPEED THREE INFORMATION:')
    output('  State: {}\n  Alarm: {}\n  Sims in Open Streets: {}\n  Target State: {}'.format(ss3_state, alarm, sims_in_open_streets, target_state))
    output('  Game Speed: {}'.format(game_clock.clock_speed()))
    output('TIME REQUESTS:')
    for time_request in game_clock.game_speed_requests_gen():
        output('  {}\n'.format(time_request))
    output('-=-=-=-=-=-=-=-=-')

@sims4.commands.Command('clock.ignore_interaction_speed_change_requests', command_type=CommandType.Automation)
def ignore_interaction_speed_change_requests(value:bool=True, _connection=None):
    services.game_clock_service().ignore_game_speed_requests = value

