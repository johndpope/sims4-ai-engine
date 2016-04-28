import sims4.commands
from broadcasters.environment_score import environment_score_mixin

@sims4.commands.Command('environment_score.enable')
def environment_score_enable(_connection=None):
    environment_score_mixin.environment_score_enabled = True

@sims4.commands.Command('environment_score.disable')
def environment_score_disable(_connection=None):
    environment_score_mixin.environment_score_enabled = False

