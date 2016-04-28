from server_commands.argument_helpers import OptionalTargetParam, get_optional_target
import sims4.commands

@sims4.commands.Command('royalty.give_royalties')
def give_royalties(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('Target Sim could not be found.', _connection)
        return False
    royalty_tracker = sim.sim_info.royalty_tracker
    if royalty_tracker is None:
        sims4.commands.output('Royalty Tracker not found for Sim.', _connection)
        return False
    royalty_tracker.update_royalties_and_get_paid()
    return True

