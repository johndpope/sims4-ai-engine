from server_commands.argument_helpers import OptionalTargetParam, get_optional_target, TunableInstanceParam, get_tunable_instance
import services
import sims4.commands
logger = sims4.log.Logger('AspirationCommand')

@sims4.commands.Command('ui.aspirations.set_primary', command_type=sims4.commands.CommandType.Live)
def set_primary_track(aspiration_track, sim_id:int=0, _connection=None):
    sim_info = services.sim_info_manager().get(sim_id)
    if sim_info is None:
        logger.error('Sim Info not found')
        return False
    sim_info.primary_aspiration = aspiration_track.guid64
    return True

@sims4.commands.Command('aspirations.reset_data')
def reset_aspirations(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.sim_info.aspiration_tracker.reset_data()
        sims4.commands.output('Aspirations reset complete', _connection)
    else:
        sims4.commands.output('Sim not found, please check: |aspirations.reset_data <sim id from desired account>', _connection)

@sims4.commands.Command('aspirations.list_all_aspirations')
def list_all_aspirations(_connection=None):
    aspiration_manager = services.get_instance_manager(sims4.resources.Types.ASPIRATION)
    for aspiration_id in aspiration_manager.types:
        aspiration = aspiration_manager.get(aspiration_id)
        sims4.commands.output('{}: {}'.format(aspiration, int(aspiration.guid64)), _connection)

@sims4.commands.Command('aspirations.complete_aspiration', command_type=sims4.commands.CommandType.Automation)
def complete_aspiration(aspiration_type, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        for objective_type in aspiration_type.objectives:
            while not sim.sim_info.aspiration_tracker.objective_completed(objective_type.guid64):
                sim.sim_info.aspiration_tracker.complete_objective(objective_type)
        sim.sim_info.aspiration_tracker.complete_milestone(aspiration_type, sim.sim_info)
        sims4.commands.output('Complete {} on {}'.format(aspiration_type, sim), _connection)
        sim.sim_info.aspiration_tracker.send_if_dirty()

@sims4.commands.Command('aspirations.complete_current_milestone', command_type=sims4.commands.CommandType.Automation)
def complete_current_milestone(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        track_id = sim.sim_info.primary_aspiration
        if track_id == 0:
            sims4.commands.output("{} doesn't have a primary aspiration.".format(sim), _connection)
            return
        track = get_tunable_instance(sims4.resources.Types.ASPIRATION_TRACK, track_id)
        for (_, track_aspriation) in track.get_aspirations():
            while not sim.sim_info.aspiration_tracker.milestone_completed(track_aspriation.guid64):
                for objective_type in track_aspriation.objectives:
                    while not sim.sim_info.aspiration_tracker.objective_completed(objective_type.guid64):
                        sim.sim_info.aspiration_tracker.complete_objective(objective_type)
                sim.sim_info.aspiration_tracker.complete_milestone(track_aspriation, sim.sim_info)
                sims4.commands.output('Complete {} on {}'.format(track_aspriation, sim), _connection)
                sim.sim_info.aspiration_tracker.send_if_dirty()
                return
        sims4.commands.output('{} has completed all milestones in {}.'.format(sim, track), _connection)

@sims4.commands.Command('aspirations.complete_objective', command_type=sims4.commands.CommandType.Automation)
def complete_objective(objective_type, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None and objective_type is not None:
        sim.sim_info.aspiration_tracker.complete_objective(objective_type)
        track_id = sim.sim_info.primary_aspiration
        if track_id != 0:
            track = get_tunable_instance(sims4.resources.Types.ASPIRATION_TRACK, track_id)
            for (_, track_aspriation) in track.get_aspirations():
                while objective_type in track_aspriation.objectives:
                    count_completed = 0
                    for obj in track_aspriation.objectives:
                        while sim.sim_info.aspiration_tracker.objective_completed(obj.guid64):
                            count_completed += 1
                    if count_completed == len(track_aspriation.objectives):
                        sim.sim_info.aspiration_tracker.complete_milestone(track_aspriation, sim.sim_info)
                    break
        sim.sim_info.aspiration_tracker.send_if_dirty()
        sims4.commands.output('Complete {} on {}'.format(objective_type, sim), _connection)

