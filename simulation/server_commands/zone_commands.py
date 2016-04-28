from event_testing.test_events import TestEvent
from server_commands.argument_helpers import OptionalTargetParam, get_optional_target
from sims4.utils import create_csv
import services
import sims4.commands

@sims4.commands.Command('zone.loading_screen_animation_finished', command_type=sims4.commands.CommandType.Live)
def loading_screen_animation_finished(_connection=None):
    services.current_zone().on_loading_screen_animation_finished()

@sims4.commands.Command('zone.trigger_test_event', command_type=sims4.commands.CommandType.Live)
def trigger_test_event(event:int=0, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    sim_info = sim.sim_info if sim is not None else None
    test_event = TestEvent(event)
    services.get_event_manager().process_event(test_event, sim_info=sim_info)

@sims4.commands.Command('zone.gather_tick_metrics.start', command_type=sims4.commands.CommandType.Automation)
def gather_tick_metrics_start(_connection=None):
    services.current_zone().start_gathering_tick_metrics()

@sims4.commands.Command('zone.gather_tick_metrics.stop', command_type=sims4.commands.CommandType.Automation)
def gather_tick_metrics_stop(_connection=None):

    def callback(file):
        zone = services.current_zone()
        tick_data = zone.tick_data
        zone.stop_gathering_tick_metrics()
        file.write('ABSOLUTE TICKS,SIM NOW READABLE, SIM NOW TICKS,CLOCK SPEED ENUM,CLOCK SPEED MULTIPLIER,GAME TIME READABLE,GAME TIME TICKS,MULTIPLIER TYPE\n')
        for data in tick_data:
            file.write('{},{},{},{},{},{},{},{}\n'.format(data.absolute_ticks, data.sim_now, data.sim_now.absolute_ticks(), data.clock_speed, data.clock_speed_multiplier, data.game_time, data.game_time.absolute_ticks(), data.multiplier_type))

    create_csv('tick_metrics', callback=callback, connection=_connection)

