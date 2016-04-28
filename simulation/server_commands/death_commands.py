from interactions.utils import death
import sims4.commands

@sims4.commands.Command('death.toggle', command_type=sims4.commands.CommandType.Cheat)
def death_toggle(enabled:bool=None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    output('Toggling death')
    death.toggle_death(enabled=enabled)

