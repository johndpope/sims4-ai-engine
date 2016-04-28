from server_commands.argument_helpers import TunableInstanceParam
import sims4

@sims4.commands.Command('tutorial.activate_tutorial_tip', command_type=sims4.commands.CommandType.Live)
def activate_tutorial_tip(tutorial_tip, _connection=None):
    tutorial_tip.activate()
    return True

@sims4.commands.Command('tutorial.deactivate_tutorial_tip', command_type=sims4.commands.CommandType.Live)
def deactivate_tutorial_tip(tutorial_tip, _connection=None):
    tutorial_tip.deactivate()
    return True

