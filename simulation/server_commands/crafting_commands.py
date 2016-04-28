from crafting.crafting_process import CRAFTING_QUALITY_LIABILITY
from server_commands.argument_helpers import OptionalTargetParam, get_optional_target
import crafting.crafting_process
import sims4.commands

@sims4.commands.Command('crafting.shorten_phases', command_type=sims4.commands.CommandType.Automation)
def shorten_phases(enabled:bool=None, _connection=None):
    output = sims4.commands.Output(_connection)
    if enabled is None:
        do_enabled = not crafting.crafting_process.shorten_all_phases
    else:
        do_enabled = enabled
    crafting.crafting_process.shorten_all_phases = do_enabled
    if enabled is None:
        if do_enabled:
            output('Crafting phases are shortened.')
        else:
            output('Crafting phases are normal length.')
    return True

@sims4.commands.Command('crafting.show_quality')
def show_quality(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('No sim for crafting.show_quality', _connection)
        return False
    crafting_liability = None
    for si in sim.si_state:
        crafting_liability = si.get_liability(CRAFTING_QUALITY_LIABILITY)
        while crafting_liability is not None:
            break
    if crafting_liability is None:
        sims4.commands.output('Sim {} is not doing any crafting interaction'.format(sim), _connection)
        return False
    (quality_state, quality_stats_value) = crafting_liability.get_quality_state_and_value()
    quality_state_strings = ['None', 'Poor', 'Normal', 'Outstanding']
    quality_state = quality_state or 0
    sims4.commands.output('Sim {} current crafting quality is {}({})'.format(sim, quality_state_strings[quality_state], quality_stats_value), _connection)
    return True

