from server_commands.argument_helpers import get_optional_target, OptionalTargetParam
from sims4.commands import CommandType
import services
import sims4.commands

@sims4.commands.Command('fire.kill')
def kill(_connection=None):
    fire_service = services.get_fire_service()
    fire_service.kill()

@sims4.commands.Command('fire.toggle_enabled', command_type=CommandType.Automation)
def toggle_fire_enabled(enabled:bool=None, _connection=None):
    if enabled is None:
        services.fire_service.fire_enabled = not services.fire_service.fire_enabled
    else:
        services.fire_service.fire_enabled = enabled
    sims4.commands.output('Fire enabled = {}'.format(services.fire_service.fire_enabled), _connection)

@sims4.commands.Command('fire.alert_all_sims')
def alert_all_sims(_connection=None):
    fire_service = services.get_fire_service()
    fire_service.alert_all_sims()

@sims4.commands.Command('fire.singe_sim')
def singe_sim(opt_target:OptionalTargetParam=None, set_singed:bool=None, _connection=None):
    sim = get_optional_target(opt_target, _connection)
    if sim is None:
        return False
    sim_info = sim.sim_info
    if set_singed is None:
        sim_info.singed = not sim_info.singed
    else:
        sim_info.singed = set_singed

