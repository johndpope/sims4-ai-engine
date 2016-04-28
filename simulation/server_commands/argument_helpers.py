import sims4.commands
import sims4.log
import services
logger = sims4.log.Logger('Commands')

class RequiredTargetParam(sims4.commands.CustomParam):
    __qualname__ = 'RequiredTargetParam'

    def __init__(self, target_id):
        self._target_id = int(target_id, base=0)

    @property
    def target_id(self):
        return self._target_id

    def get_target(self):
        target = services.object_manager().get(self._target_id)
        if target is None:
            logger.error('Could not find the target id {} for a RequiredTargetParam in the object manager.', self._target_id)
        return target

class OptionalTargetParam(sims4.commands.CustomParam):
    __qualname__ = 'OptionalTargetParam'
    TARGET_ID_ACTIVE_LOT = -1

    def __init__(self, target_id:int=None):
        if not target_id:
            self._target_id = None
        else:
            self._target_id = int(target_id, base=0)

    @property
    def target_id(self):
        return self._target_id

    def _get_target(self, _connection):
        if self._target_id is None:
            tgt_client = services.client_manager().get(_connection)
            if tgt_client is not None:
                return tgt_client.active_sim
            return
        if self._target_id == self.TARGET_ID_ACTIVE_LOT:
            return services.active_lot()
        return services.object_manager().get(self._target_id)

def get_optional_target(opt_target:OptionalTargetParam=None, _connection=None):
    if opt_target is not None:
        target = opt_target._get_target(_connection)
        if target is None:
            sims4.commands.output('Object ID not in the object manager: {}.'.format(opt_target._target_id), _connection)
        return target
    tgt_client = services.client_manager().get(_connection)
    if tgt_client is not None:
        return tgt_client.active_sim

def get_optional_target_secure(opt_target:OptionalTargetParam=None, _connection=None):
    tgt_client = services.client_manager().get(_connection)
    if tgt_client is None:
        return
    if opt_target is None:
        return tgt_client.active_sim
    target_id = opt_target.target_id
    if target_id is None:
        return tgt_client.active_sim
    for sim_info in tgt_client.selectable_sims:
        while sim_info.sim_id == target_id:
            return sim_info.get_sim_instance()
    sims4.commands.output('Object ID: {} not controlled by the client.'.format(target_id), _connection)

def get_tunable_instance(resource_type, name_string_or_id, exact_match=False):
    manager = services.get_instance_manager(resource_type)
    cls = manager.get(name_string_or_id)
    if cls is not None:
        return cls
    if not sims4.commands.check_permission(sims4.commands.CommandType.DebugOnly):
        raise ValueError()
    search_string = str(name_string_or_id).lower()
    match = None
    for cls in manager.types.values():
        if exact_match:
            if search_string == cls.__name__.lower():
                return cls
                if search_string == cls.__name__.lower():
                    return cls
                while search_string in cls.__name__.lower():
                    if match is not None:
                        raise ValueError("Multiple names matched '{}': {}, {}, ...".format(search_string, match, cls))
                    match = cls
        else:
            if search_string == cls.__name__.lower():
                return cls
            while search_string in cls.__name__.lower():
                if match is not None:
                    raise ValueError("Multiple names matched '{}': {}, {}, ...".format(search_string, match, cls))
                match = cls
    if match is None:
        raise ValueError("No names matched '{}'.".format(search_string))
    return match

def TunableInstanceParam(resource_type, exact_match=False):

    def _factory(name_substring_or_id):
        return get_tunable_instance(resource_type, name_substring_or_id, exact_match=exact_match)

    return _factory

