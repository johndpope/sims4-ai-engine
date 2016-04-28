import bisect
import enum
import sims4.collections
import sims4.log
import sims4.reload
try:
    import _telemetry
except ImportError:

    class _telemetry:
        __qualname__ = '_telemetry'

        @staticmethod
        def log_event(session_id, module_key, group_key, hook_key, attributes):
            pass

__all__ = ['TelemetryWriter']
with sims4.reload.protected(globals()):
    _archiver_map = {}
    _filters = []
logger = sims4.log.Logger('Telemetry')
DEFAULT_MODULE_TAG = 'GAME'
RESERVED_FIELDS = {'hip_'}

class RuleAction(enum.Int):
    __qualname__ = 'RuleAction'
    DROP = 0
    COLLECT = 1

def add_filter_rule(priority, module_tag, group_tag, hook_tag, fields, action):
    fields = sims4.collections.frozendict(fields)
    key = _get_key(module_tag, group_tag, hook_tag)
    record = (priority, key, fields, action)
    bisect.insort(_filters, record)

def remove_filter_rule(priority, module_tag, group_tag, hook_tag, fields, action):
    fields = sims4.collections.frozendict(fields)
    key = _get_key(module_tag, group_tag, hook_tag)
    record = (priority, key, fields, action)
    index = bisect.bisect_left(_filters, record)
    if index != len(_filters) and _filters[index] == record:
        del _filters[index]
        return True
    return False

class TelemetryWriter:
    __qualname__ = 'TelemetryWriter'

    def __init__(self, group_tag, module_tag=DEFAULT_MODULE_TAG):
        self.module_tag = module_tag
        self.group_tag = group_tag

    def begin_hook(self, hook_tag, valid_for_npc=False):
        return _TelemetryHookWriter(self, hook_tag, valid_for_npc)

def check_telemetry_tag(tag):
    pass

class _TelemetryHookWriter:
    __qualname__ = '_TelemetryHookWriter'

    def __init__(self, writer, hook_tag, valid_for_npc):
        self.session_id = 0
        self.disabled_hook = False
        self.module_tag = writer.module_tag
        self.group_tag = writer.group_tag
        self.hook_tag = hook_tag
        self.valid_for_npc = valid_for_npc
        self.data = []

    def write_bool(self, tag, value):
        output = '1' if value else '0'
        self.data.append((tag, output))

    def write_int(self, tag, value):
        output = str(int(value))
        self.data.append((tag, output))

    def write_localized_string(self, tag, localized_string):
        output = '{0:#x}'.format(localized_string.hash)
        self.data.append((tag, output))

    def write_enum(self, tag, value):
        output = str(value)
        self.data.append((tag, output))

    def write_guid(self, tag, value):
        output = '_' + str(int(value))
        self.data.append((tag, output))

    def write_float(self, tag, value, precision=2):
        output = '{0:.{1}f}'.format(value, precision)
        self.data.append((tag, output))

    def write_string(self, tag, value):
        self.data.append((tag, value))

    def _commit(self):
        if self.disabled_hook:
            return
        if not _check_filter(self.module_tag, self.group_tag, self.hook_tag, self.data):
            return
        _telemetry.log_event(self.session_id, self.module_tag, self.group_tag, self.hook_tag, self.data)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_value is None:
            self._commit()
            return
        if not isinstance(exc_value, Exception):
            return False
        sims4.log.exception('Telemetry', 'Exception while processing telemetry hooks!')
        return True

def _get_key(module_tag, group_tag, hook_tag):
    key = []
    if module_tag is not None:
        key.append(module_tag)
        if group_tag is not None:
            key.append(group_tag)
            if hook_tag is not None:
                key.append(hook_tag)
    return tuple(key)

def _check_filter(module_tag, group_tag, hook_tag, data):
    for (_, tags, fields, action) in _filters:
        l = len(tags)
        match = False
        if l == 3:
            match = tags[2] == hook_tag and (tags[1] == group_tag and tags[0] == module_tag)
        elif l == 2:
            match = tags[1] == group_tag and tags[0] == module_tag
        elif l == 1:
            match = tags[0] == module_tag
        elif l == 0:
            match = True
        while match and (not fields or _check_fields(fields, data)):
            return action == RuleAction.COLLECT
    return True

def _check_fields(fields, data):
    expected = len(fields)
    if not expected:
        return True
    matches = 0
    for (key, value) in data:
        while key in fields:
            if fields[key] != value:
                return False
            matches += 1
            if matches == expected:
                return True
    return False

FIELD_ACCOUNT_ID = 'acct'
FIELD_SIM_ID = 'simi'
FIELD_SIM_CLASS = 'clss'
FIELD_HOUSEHOLD_ID = 'hous'
FIELD_ZONE_ID = 'zone'
FIELD_TIME = 'time'
FIELD_SIM_MOOD = 'mood'

def _write_common_data(hook, sim_id=0, household_id=0, session_id=0, sim_time=0, sim_mood=0, sim_class=0):
    hook.session_id = session_id
    zone_id = sims4.zone_utils.get_zone_id(can_be_none=True)
    if zone_id is not None:
        hook.write_int(FIELD_ZONE_ID, zone_id)
    hook.write_int(FIELD_SIM_ID, sim_id)
    hook.write_guid(FIELD_SIM_CLASS, sim_class)
    hook.write_int(FIELD_HOUSEHOLD_ID, household_id)
    hook.write_int(FIELD_TIME, sim_time)
    hook.write_guid(FIELD_SIM_MOOD, sim_mood)

def begin_hook(writer, hook_tag, **kwargs):
    hook = writer.begin_hook(hook_tag)
    _write_common_data(hook, **kwargs)
    return hook

