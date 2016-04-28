import sims4.commands
import sims4.profiler

@sims4.commands.Command('pyprofile.on')
def pyprofile_on(_connection=None):
    sims4.profiler.enable_profiler()
    return True

@sims4.commands.Command('pyprofile.off')
def pyprofile_off(_connection=None):
    sims4.profiler.disable_profiler()
    sims4.profiler.flush()
    return True

@sims4.commands.Command('pyprofile.flush')
def pyprofile_flush(_connection=None):
    sims4.profiler.flush()
    return True

