import sims4.commands
import sims4.resources
from server_commands.argument_helpers import OptionalTargetParam, TunableInstanceParam, get_optional_target
import services

@sims4.commands.Command('broadcasters.add')
def broadcasters_add(broadcaster_type, broadcasting_object:OptionalTargetParam=None, _connection=None):
    broadcasting_object = get_optional_target(broadcasting_object, _connection)
    if broadcasting_object is None:
        return False
    broadcaster = broadcaster_type(broadcasting_object=broadcasting_object)
    services.current_zone().broadcaster_service.add_broadcaster(broadcaster)
    return True

