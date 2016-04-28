import inspect
import re
import enum
import sims4.common
import sims4.log
import sims4.reload
import sims4.telemetry
import sims4.zone_utils
__enable_native_commands = True
try:
    import _commands
except:
    __enable_native_commands = False
try:
    import _mdz
except ImportError:

    class _mdz:
        __qualname__ = '_mdz'

        @staticmethod
        def get_zone_by_account(account_id):
            return 0

class CommandType(enum.Int, export=False):
    __qualname__ = 'CommandType'
    DebugOnly = 1
    Automation = 2
    Cheat = 4
    Live = 5

with sims4.reload.protected(globals()):
    permissions_provider = None
logger = sims4.log.Logger('Commands')
TELEMETRY_GROUP_CHEATS = 'CHTS'
TELEMETRY_HOOK_INTERACTION = 'NTRC'
TELEMETRY_HOOK_COMMAND = 'CMND'
TELEMETRY_FIELD_NAME = 'name'
TELEMETRY_FIELD_TARGET = 'trgt'
TELEMETRY_FIELD_ARGS = 'args'
cheats_writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_CHEATS)
BOOL_TRUE = {'t', 'true', 'on', '1', 'yes', 'y', 'enable'}
BOOL_FALSE = {'f', 'false', 'off', '0', 'no', 'n', 'disable'}
with sims4.reload.protected(globals()):
    _current_check_permission = []

def check_permission(command_type, silent_fail=False):
    if command_type != CommandType.Live and _current_check_permission:
        (_session_id, output, permissions_provider) = _current_check_permission[-1]
        if not permissions_provider(_session_id, command_type):
            if not silent_fail:
                err_str = 'Attempt to invoke command of type: {}. This is not allowed.-Mike Duke'.format(command_type)
                logger.error(err_str)
                output(err_str, _session_id)
            return False
    return True

def register(name, handler, description, usage):
    if __enable_native_commands:
        _commands.register(name, description, usage, handler)

def unregister(name):
    if __enable_native_commands:
        _commands.unregister(name)

def execute(command_line, _connection):
    if __enable_native_commands:
        if _connection is None:
            _connection = 0
        _commands.execute(command_line, _connection)

def describe(search_string=None):
    if __enable_native_commands:
        return _commands.describe(search_string)
    return []

def output(s, context):
    pass

def cheat_output(s, context):
    if __enable_native_commands:
        _commands.output(s, context)

def automation_output(s, context=0):
    if __enable_native_commands:
        _commands.automation_output(s, context)

def client_cheat(s, context):
    if __enable_native_commands:
        _commands.client_cheat(s, context)

REMOVE_ACCOUNT_ARG = re.compile('(, ?)?_account=None', flags=re.IGNORECASE)

def prettify_usage(usage_string):
    usage_string = re.sub(REMOVE_ACCOUNT_ARG, '', usage_string)
    return usage_string

class CustomParam:
    __qualname__ = 'CustomParam'

def parse_args(spec, args, account):
    args = list(args)
    for (name, index) in zip(spec.args, range(len(args))):
        arg_type = spec.annotations.get(name)
        while arg_type is not None:
            arg_value = args[index]
            _parse_arg(spec, args, arg_type, arg_value, name, index, account)
    index = 0
    for (name, index) in zip(spec.args, range(len(spec.args))):
        arg_type = spec.annotations.get(name)
        while index < len(args):
            if isinstance(arg_type, type) and issubclass(arg_type, CustomParam):
                arg_value = args[index]
                if not isinstance(arg_value, arg_type):
                    args[index] = arg_type(arg_value)
    if spec.varargs is not None:
        arg_type = spec.annotations.get(spec.varargs)
        if arg_type is not None:
            index += 1
            vararg_list = args[index:]
            name = spec.varargs
            while True:
                for arg_value in vararg_list:
                    _parse_arg(spec, args, arg_type, arg_value, name, index, account)
                    index += 1
    return args

def _parse_arg(spec, args, arg_type, arg_value, name, index, account):
    if isinstance(arg_value, str):
        if arg_type is bool:
            lower_arg_value = arg_value.lower()
            if lower_arg_value in BOOL_TRUE:
                args[index] = True
            elif lower_arg_value in BOOL_FALSE:
                args[index] = False
            else:
                output('Invalid entry specified for bool {}: {} (Expected one of {} for True, or one of {} for False.)'.format(name, arg_value, BOOL_TRUE, BOOL_FALSE), account)
                raise ValueError('invalid literal for boolean parameter')
                try:
                    if arg_type is int:
                        args[index] = int(arg_value, base=0)
                    else:
                        args[index] = arg_type(arg_value)
                except Exception as exc:
                    output("Invalid value for {}: '{}' ({})".format(name, arg_value, exc), account)
                    raise
        else:
            try:
                if arg_type is int:
                    args[index] = int(arg_value, base=0)
                else:
                    args[index] = arg_type(arg_value)
            except Exception as exc:
                output("Invalid value for {}: '{}' ({})".format(name, arg_value, exc), account)
                raise

def zone_id_from_args(spec, args):
    for (name, index) in zip(spec.args, range(len(args))):
        while name == 'zone_id':
            arg_value = args[index]
            return arg_value
    return 0

def Command(*aliases, command_type=CommandType.DebugOnly, pack=None):

    def is_valid_command():
        if not (command_type == CommandType.DebugOnly and __debug__):
            return False
        if not (pack and sims4.common.is_entitled_pack(pack)):
            return False
        return True

    def named_command(func):
        if not is_valid_command():
            return
        name = aliases[0]
        full_arg_spec = inspect.getfullargspec(func)

        def invoke_command(*args, _session_id=0, **kw):
            if '_account' in full_arg_spec.args or '_account' in full_arg_spec.kwonlyargs:
                kw['_account'] = _session_id
            if '_connection' in full_arg_spec.args or '_connection' in full_arg_spec.kwonlyargs:
                kw['_connection'] = _session_id
            if _session_id == 0:
                if 'zone_id' in full_arg_spec.args:
                    zone_id = zone_id_from_args(full_arg_spec, args)
                else:
                    zone_id = sims4.zone_utils.get_zone_id()
            else:
                zone_id = _mdz.get_zone_by_session_id(_session_id)
            args = parse_args(full_arg_spec, args, _session_id)
            with sims4.zone_utils.global_zone_lock(zone_id):
                pushed_check_permission = False
                if _session_id != 0 and permissions_provider is not None:
                    _current_check_permission.append((_session_id, output, permissions_provider))
                    pushed_check_permission = True
                try:
                    if not check_permission(command_type):
                        return
                    if command_type == CommandType.Cheat:
                        with sims4.telemetry.begin_hook(cheats_writer, TELEMETRY_HOOK_COMMAND) as hook:
                            hook.write_string(TELEMETRY_FIELD_NAME, name)
                            hook.write_string(TELEMETRY_FIELD_ARGS, str(args))
                    return func(*args, **kw)
                except BaseException as e:
                    output('Error: {}'.format(e), _session_id)
                    logger.warn('Error executing command')
                    raise
                finally:
                    if pushed_check_permission:
                        _current_check_permission.pop()

        invoke_command.__name__ = 'invoke_command ({})'.format(name)
        usage = prettify_usage(str.format(inspect.formatargspec(*full_arg_spec)))
        description = ''
        for alias in aliases:
            register(alias, invoke_command, description, usage)
        return func

    return named_command

class Output:
    __qualname__ = 'Output'
    __slots__ = ('_context',)

    def __init__(self, context):
        self._context = context

    def __call__(self, s):
        output(s, self._context)

class CheatOutput(Output):
    __qualname__ = 'CheatOutput'

    def __call__(self, s):
        cheat_output(s, self._context)

class AutomationOutput:
    __qualname__ = 'AutomationOutput'
    __slots__ = ('_context',)

    def __init__(self, context):
        self._context = context

    def __call__(self, s):
        automation_output(s, self._context)

class NoneIntegerOrString(CustomParam):
    __qualname__ = 'NoneIntegerOrString'

    def __new__(cls, value):
        if value == 'None':
            return
        try:
            return int(value, 0)
        except:
            pass
        return value

