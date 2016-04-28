import server_commands.argument_helpers
import services
import sims4.commands
logger = sims4.log.Logger('Rewards')

@sims4.commands.Command('rewards.give_reward')
def give_reward(reward_name, opt_sim:server_commands.argument_helpers.OptionalTargetParam=None, _connection=None):
    output = sims4.commands.Output(_connection)
    reward_instance = services.get_instance_manager(sims4.resources.Types.REWARD).get(reward_name)
    if reward_instance is None:
        output('Failed to find the specified reward instance.')
        return False
    sim = server_commands.argument_helpers.get_optional_target(opt_sim, _connection)
    reward_instance.give_reward(sim.sim_info)
    output('Successfully gave the reward.')

