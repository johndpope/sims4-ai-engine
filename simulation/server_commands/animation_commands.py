from animation.arb_accumulator import ArbAccumulatorService
import animation.asm
import interactions.utils.animation
import services
import sims4.commands
from sims4.commands import CommandType

@sims4.commands.Command('animation.asm_describe')
def asm_describe(name, _connection=None):
    asm = animation.asm.Asm(name, None)
    sims4.commands.output('ASM is {0}'.format(str(asm.state_machine_name)), _connection)
    sims4.commands.output('  Public States:', _connection)
    public_states = asm.public_states
    if public_states is not None:
        for s in public_states:
            sims4.commands.output('     {0}'.format(s), _connection)
    else:
        sims4.commands.output('     (no public states)', _connection)
    sims4.commands.output('  Actors:', _connection)
    actors = asm.actors
    if actors is not None:
        for s in actors:
            sims4.commands.output('     {0}'.format(s), _connection)
            sims4.commands.output('       {0}'.format(asm.get_actor_definition(s)), _connection)
    else:
        sims4.commands.output('     (no actors)', _connection)
    sims4.commands.output('  Parameters:', _connection)
    parameters = asm.parameters
    if parameters is not None:
        for s in parameters:
            sims4.commands.output('     {0}'.format(s), _connection)
    else:
        sims4.commands.output('     (no parameters)', _connection)

@sims4.commands.Command('animation.set_parent')
def set_parent(parent_id, child_id, joint_name=None, use_offset:int=0, _connection=None):
    manager = services.object_manager()
    parent = None
    if parent_id != 0 and parent_id in manager:
        parent = manager.get(parent_id)
    child = None
    if child_id != 0:
        if child_id in manager:
            child = manager.get(child_id)
        else:
            sims4.commands.output('SET_PARENT: Child not in manager.', _connection)
    if child is None:
        sims4.commands.output('SET_PARENT: Invalid child.', _connection)
        return
    if parent is None:
        sims4.commands.output('SET_PARENT: No parent found.', _connection)
        return
    transform = None
    if use_offset == 1:
        transform = sims4.math.Transform(sims4.math.Vector3(1.0, 2.0, 3.0), sims4.math.Quaternion.IDENTITY())
    sims4.commands.output('SET_PARENT:Adding Parent', _connection)
    child.set_parent(parent, transform, joint_name)

@sims4.commands.Command('animation.arb_log.enable')
def enable_arb_log(_connection=None):
    interactions.utils.animation._log_arb_contents = True

@sims4.commands.Command('animation.arb_log.disable')
def disable_arb_log(_connection=None):
    interactions.utils.animation._log_arb_contents = False

@sims4.commands.Command('animation.boundary_condition.add_log')
def add_boundary_condition_log(pattern:str='', _connection=None):
    animation.asm.add_boundary_condition_logging(pattern)
    return True

@sims4.commands.Command('animation.boundary_condition.clear_log')
def clear_boundary_condition_log(_connection=None):
    animation.asm.clear_boundary_condition_logging()
    return True

@sims4.commands.Command('animation.list_parameter_sequences')
def list_asm_parameter_sequences(name, target_state, src_state='entry', _connection=None):
    asm = animation.asm.Asm(name, None)
    param_sequence_list = asm._get_param_sequences(0, target_state, src_state, None)
    for x in param_sequence_list:
        sims4.commands.output('{0}'.format(x), _connection)

@sims4.commands.Command('animation.set_shave_time')
def set_shave_time(shave_time, _connection=None):
    ArbAccumulatorService.SHAVE_TIME = shave_time

@sims4.commands.Command('animation.route_complete', command_type=CommandType.Live)
def route_complete(sim_id:int=None, path_id:int=None, _connection=None):
    if sim_id is None or path_id is None:
        return
    current_zone = services.current_zone()
    sim = current_zone.find_object(sim_id)
    if sim is None:
        return
    sim.route_finished(path_id)

@sims4.commands.Command('animation.route_time_update', command_type=CommandType.Live)
def route_time_update(sim_id:int=None, path_id:int=None, current_time:float=None, _connection=None):
    if sim_id is None or path_id is None or current_time is None:
        return
    current_zone = services.current_zone()
    sim = current_zone.find_object(sim_id)
    if sim is None:
        return
    sim.route_time_update(path_id, current_time)

