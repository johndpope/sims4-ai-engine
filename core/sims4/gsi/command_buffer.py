import collections
import threading
import sims4.commands
import sims4.log
import sims4.service_manager
logger = sims4.log.Logger('GSI')
_Command = collections.namedtuple('_Command', ('command_string', 'callback', 'output_override', 'zone_id', 'connection_id'))

class CommandBufferService(sims4.service_manager.Service):
    __qualname__ = 'CommandBufferService'

    def __init__(self):
        self.pending_commands = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            self.pending_commands = []

    def stop(self):
        with self._lock:
            self.pending_commands = None

    def add_command(self, command_string, callback=None, output_override=None, zone_id=None, connection_id=None):
        with self._lock:
            while self.pending_commands is not None:
                command = _Command(command_string, callback, output_override, zone_id, connection_id)
                self.pending_commands.append(command)

    def on_tick(self):
        with self._lock:
            if not self.pending_commands:
                return
            local_pending_commands = list(self.pending_commands)
            del self.pending_commands[:]
        for command in local_pending_commands:
            real_output = sims4.commands.output
            sims4.commands.output = command.output_override
            result = False
            try:
                if command.zone_id is not None:
                    with sims4.zone_utils.global_zone_lock(command.zone_id):
                        sims4.commands.execute(command.command_string, command.connection_id)
                else:
                    sims4.commands.execute(command.command_string, None)
                result = True
            except Exception:
                result = False
                logger.exception('Error while executing game command for')
            finally:
                sims4.commands.output = real_output
                command.callback(result)

