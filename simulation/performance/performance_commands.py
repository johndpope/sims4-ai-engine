from collections import Counter
from clock import ClockSpeedMultiplierType, ClockSpeedMode
from gsi_handlers.performance_handlers import generate_statistics
from server_commands.autonomy_commands import show_queue
from server_commands.cache_commands import cache_status
from sims4.commands import CommandType
from sims4.profiler_utils import create_custom_named_profiler_function
from sims4.utils import create_csv
import enum
import event_testing
import services
import sims4.commands
from adaptive_clock_speed import AdaptiveClockSpeed

@sims4.commands.Command('performance.log_alarms')
def log_alarms(enabled:bool=True, check_cooldown:bool=True, _connection=None):
    services.current_zone().alarm_service._log = enabled
    return True

@sims4.commands.Command('performance.log_object_statistics', command_type=CommandType.Automation)
def log_object_statistics(_connection=None):
    from numbers import Number
    result = generate_statistics()
    automationOutput = sims4.commands.AutomationOutput(_connection)
    automationOutput('PerfLogObjStats; Status:Begin')
    for (name, value) in result:
        sims4.commands.output('{:40} : {:5}'.format(name, value), _connection)
        eval_value = eval(value)
        if isinstance(eval_value, Number):
            automationOutput('PerfLogObjStats; Status:Data, Name:{}, Value:{}'.format(name, value))
        else:
            while isinstance(eval_value, (list, tuple)):
                automationOutput('PerfLogObjStats; Status:ListBegin, Name:{}'.format(name))
                for obj_freq in eval_value:
                    object_name = obj_freq.get('object_name')
                    frequency = obj_freq.get('frequency')
                    automationOutput('PerfLogObjStats; Status:ListData, Name:{}, Frequency:{}'.format(object_name, frequency))
                automationOutput('PerfLogObjStats; Status:ListEnd, Name:{}'.format(name))
    automationOutput('PerfLogObjStats; Status:End')

@sims4.commands.Command('performance.add_automation_profiling_marker', command_type=CommandType.Automation)
def add_automation_profiling_marker(message:str='Unspecified', _connection=None):
    name_f = create_custom_named_profiler_function(message)
    return name_f(lambda : None)

class SortStyle(enum.Int, export=False):
    __qualname__ = 'SortStyle'
    AVERAGE_TIME = 0
    TOTAL_TIME = 1
    COUNT = 2

@sims4.commands.Command('performance.test_profile.dump', command_type=CommandType.Automation)
def dump_tests_profile(sort:SortStyle=SortStyle.AVERAGE_TIME, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    if event_testing.resolver.test_profile is None:
        output('Test profiling is currently disabled. Use |performance.test_profile.enable')
        return
    if len(event_testing.resolver.test_profile) == 0:
        output('Test profiling is currently enabled but has no records.')
        return

    def sort_style(metric):
        if sort == SortStyle.AVERAGE_TIME:
            return metric.average_time
        if sort == SortStyle.TOTAL_TIME:
            return metric.total_time
        return metric.count

    def callback(file):
        TIME_MULTIPLIER = 1000
        file.write('Test,Count,AverageTime(ms),TotalTime(ms),Resolver,Key,Count,AverageTime(ms),TotalTime(ms)\n')
        for (test_name, test_metrics) in sorted(event_testing.resolver.test_profile.items(), key=lambda t: sort_style(t[1].metrics), reverse=True):
            file.write('{},{},{},{},,,,,\n'.format(test_name, test_metrics.metrics.count, test_metrics.metrics.average_time*TIME_MULTIPLIER, test_metrics.metrics.total_time*TIME_MULTIPLIER))
            for resolver in sorted(test_metrics.resolvers.keys()):
                data = test_metrics.resolvers[resolver]
                for (key, metrics) in sorted(data.items(), key=lambda t: sort_style(t[1]), reverse=True):
                    while metrics.average_time > 0:
                        file.write(',,,,{},{},{},{},{}\n'.format(resolver, key, metrics.count, metrics.average_time*TIME_MULTIPLIER, metrics.total_time*TIME_MULTIPLIER))

    create_csv('test_profile', callback=callback, connection=_connection)

@sims4.commands.Command('performance.test_profile.enable', command_type=CommandType.Automation)
def enable_test_profile(_connection=None):
    event_testing.resolver.test_profile = dict()
    output = sims4.commands.CheatOutput(_connection)
    output('Test profiling enabled. Dump the profile any time using performance.test_profile.dump')

@sims4.commands.Command('performance.test_profile.disable', command_type=CommandType.Automation)
def disable_test_profile(_connection=None):
    event_testing.resolver.test_profile = None
    output = sims4.commands.CheatOutput(_connection)
    output('Test profiling disabled.')

@sims4.commands.Command('performance.test_profile.clear', command_type=CommandType.Automation)
def clear_tests_profile(_connection=None):
    if event_testing.resolver.test_profile is not None:
        event_testing.resolver.test_profile.clear()
    output = sims4.commands.CheatOutput(_connection)
    output('Test profile metrics have been cleared.')

@sims4.commands.Command('performance.print_sim_info_creation_sources', command_type=CommandType.Automation)
def print_sim_info_creation_sources(enable:bool=True, _connection=None):
    counter = Counter()
    for sim_info in services.sim_info_manager().values():
        counter[sim_info.creation_source] += 1
    output = sims4.commands.CheatOutput(_connection)
    output('Total sim_infos: {}'.format(sum(counter.values())))
    output('--------------------')
    for (source, count) in counter.most_common():
        if source == '':
            source = 'Unknown'
        output('{:50} : {}'.format(source, count))

@sims4.commands.Command('performance.clock_status', command_type=CommandType.Automation)
def clock_status(_connection=None):
    stats = []
    game_clock = services.game_clock_service()
    ss3_service = services.get_super_speed_three_service()
    clock_speed = None
    if ss3_service.in_super_speed_three_mode():
        clock_speed = 'Super Speed 3'
    else:
        clock_speed = ClockSpeedMode(game_clock.clock_speed())
    (deviance, threshold, current_duration, duration) = AdaptiveClockSpeed.get_debugging_metrics()
    output = sims4.commands.CheatOutput(_connection)
    stats.append(('Clock Speed', clock_speed, '(Current player-facing clock speed)'))
    stats.append(('Speed Multiplier Type', ClockSpeedMultiplierType(game_clock.clock_speed_multiplier_type), '(Decides the speed 2/3/SS3 multipliers for adaptive speed)'))
    stats.append(('Clock Speed Multiplier', game_clock.current_clock_speed_scale(), '(Current Speed scaled with appropriate speed settings)'))
    stats.append(('Simulation Deviance', '{:>7} / {:<7}'.format(deviance, threshold), '(Simulation clock deviance from time service clock / Tuning Threshold [units: ticks])'))
    stats.append(('Deviance Duration', '{:>7} / {:<7}'.format(current_duration, duration), '(Current duration in multiplier phase / Tuning Duration [units: ticks])'))
    for (name, value, description) in stats:
        output('{:25} {!s:40} {}'.format(name, value, description))

@sims4.commands.Command('performance.status', command_type=CommandType.Automation)
def status(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    output('==Clock==')
    clock_status(_connection=_connection)
    output('==AutonomyQueue==')
    show_queue(_connection=_connection)
    output('==ACC&BCC==')
    cache_status(_connection=_connection)

