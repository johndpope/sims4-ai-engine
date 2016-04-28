import os
import paths
import sims4.commands
import sims4.log
logger = sims4.log.Logger('Commands')

def run_script(filename, _connection=None):
    filename = os.path.join(paths.APP_ROOT, filename)
    if not os.path.isfile(filename):
        logger.error("Could not find file '{}'", filename)
        return False
    with open(filename) as fd:
        for line in fd:
            command = line.split('#', 1)[0].strip()
            if command.startswith('|'):
                command = command[1:]
                to_server = True
            else:
                to_server = False
            if not command:
                pass
            if to_server:
                sims4.commands.execute(command, _connection)
            elif _connection:
                sims4.commands.client_cheat(command, _connection)
            else:
                logger.error('Cannot send client command without a connection')
    return True

