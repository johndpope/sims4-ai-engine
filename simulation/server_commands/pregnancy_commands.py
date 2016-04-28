from server_commands.argument_helpers import get_optional_target, OptionalTargetParam
import sims4.commands

@sims4.commands.Command('pregnancy.clear')
def pregnancy_clear(sim_id:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(sim_id, _connection)
    if sim is not None:
        pregnancy_tracker = sim.sim_info.pregnancy_tracker
        pregnancy_tracker.clear_pregnancy()
        return True
    return False

@sims4.commands.Command('pregnancy.seed')
def pregnancy_seed(seed, sim_id:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(sim_id, _connection)
    if sim is not None:
        pregnancy_tracker = sim.sim_info.pregnancy_tracker
        if pregnancy_tracker.is_pregnant:
            pregnancy_tracker._seed = seed
            return True
    return False

@sims4.commands.Command('pregnancy.roll')
def pregnancy_roll(sim_id:OptionalTargetParam=None, *seeds, _connection=None):
    sim = get_optional_target(sim_id, _connection)
    if sim is not None:
        pregnancy_tracker = sim.sim_info.pregnancy_tracker
        if pregnancy_tracker.is_pregnant:
            output = sims4.commands.Output(_connection)
            if not seeds:
                seeds = (pregnancy_tracker._seed,)
            for seed in seeds:
                pregnancy_tracker._seed = seed
                pregnancy_tracker.create_offspring_data()
                output('Pregnancy seed: {}'.format(pregnancy_tracker._seed))
                for offspring_data in pregnancy_tracker.get_offspring_data_gen():
                    output('\tGender {}\n\tGenetics: {}\n\n'.format(offspring_data.gender, offspring_data.genetics))
            return True
    return False

