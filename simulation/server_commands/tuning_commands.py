import os
import re
import time
from sims4 import resources
from sims4.resources import INSTANCE_TUNING_DEFINITIONS
from sims4.tuning.merged_tuning_manager import get_manager
import date_and_time
import services
import sims4.commands
import sims4.log
logger = sims4.log.Logger('Tuning')

def get_managers():
    managers = {}
    for definition in INSTANCE_TUNING_DEFINITIONS:
        label = definition.TypeNames.lower()
        instance_type = definition.TYPE_ENUM_VALUE
        if instance_type == sims4.resources.Types.TUNING:
            label = 'module_tuning'
        managers[label] = services.get_instance_manager(instance_type)
    return managers

@sims4.commands.Command('tuning.import')
def tuning_import(instance_type=None, name=None, _connection=None):
    instance_manager = get_managers().get(instance_type, None)
    if instance_manager is None or name is None:
        sims4.commands.output('Usage: tuning.import instance_type instance_name', _connection)
    if instance_manager is None:
        sims4.commands.output('Valid instance types:', _connection)
        for name in sorted(get_managers()):
            sims4.commands.output('   {}'.format(name), _connection)
        return
    if name is None:
        sims4.commands.output('Valid {} instance names:'.format(instance_type), _connection)
        keys = resources.list(type=instance_manager.TYPE)
        names = [resources.get_name_from_key(key) for key in keys]
        names = [name.split('.')[0] for name in names]
        for name in sorted(names):
            sims4.commands.output('    {}'.format(name), _connection)
        return
    instance = instance_manager.get(name)
    sims4.commands.output(repr(instance), _connection)
    if hasattr(instance, 'debug_dump'):
        instance.debug_dump(dump=lambda s: sims4.commands.output(s, _connection))
    return True

@sims4.commands.Command('tuning.print_debug_statistics')
def print_debug_statistics(instance_type=None, _connection=None):
    instance_mgr = get_managers().get(instance_type)
    if instance_mgr is None:
        sims4.commands.output('Usage: tuning.print_debug_statistics instance_type', _connection)
        return
    for (name, value) in instance_mgr.get_debug_statistics():
        sims4.commands.output('{:30}{:20}'.format(name, value), _connection)

@sims4.commands.Command('tuning.reload')
def tuning_reload(_connection=None):
    sims4.callback_utils.invoke_callbacks(sims4.callback_utils.CallbackEvent.TUNING_CODE_RELOAD)
    done = set()
    dependents = set()
    for manager in get_managers().values():
        for changed in manager.get_changed_files():
            done.add(changed)
            new_dependents = manager.reload_by_key(changed)
            while new_dependents is not None:
                dependents.update(new_dependents)
    dependents.difference_update(done)
    while dependents:
        next_dependent = dependents.pop()
        done.add(next_dependent)
        next_type = next_dependent.type
        manager = services.get_instance_manager(next_type)
        new_dependents = manager.reload_by_key(next_dependent)
        while new_dependents is not None:
            new_dependents.difference_update(done)
            dependents.update(new_dependents)
            continue
    sims4.commands.output('Reloading definitions tags: Begin.', _connection)
    services.definition_manager().refresh_build_buy_tag_cache()
    sims4.commands.output('Reloading definitions tags: End.', _connection)
    sims4.commands.output('Reload done', _connection)
    return True

@sims4.commands.Command('tuning.resend_clock_tuning')
def tuning_resend_clock_tuning():
    date_and_time.send_clock_tuning()
    return True

NAME_PATTERN = re.compile('.*\\((.*?)\\)')

@sims4.commands.Command('tuning.dump_load_cache')
def dump_load_cache(_connection=None):
    mtg = get_manager()
    ref_dict = mtg.index_ref_record
    sorted_dict = sorted(ref_dict, key=lambda ref_entry: len(ref_dict[ref_entry]))
    file_path = os.path.join('C:\\', 'merged_tuning_log_{}.txt'.format(time.strftime('%y%m%d_%H_%M_%S')))
    fd = os.open(file_path, os.O_RDWR | os.O_CREAT)
    for cache_key in sorted_dict:
        (cache_id, key) = cache_key
        ref_list = ref_dict[cache_key]
        ref_str = 'ID: {}, Key: {}, Ref: {}: \n'.format(cache_id, key, len(ref_list))
        os.write(fd, bytes(ref_str, 'UTF-8'))
        _template_to_write = None
        _value_to_write = None
        for (source, tunable_template, tuned_value) in ref_list:
            if _template_to_write is None and _value_to_write is None:
                _template_to_write = tunable_template
                _value_to_write = tuned_value
                ref_str = 'Template: {}, Value: {} \n'.format(_template_to_write, _value_to_write)
                os.write(fd, bytes(ref_str, 'UTF-8'))
            substr = ''
            match = NAME_PATTERN.match(source)
            if match:
                substr = match.group(1)
            ref_str = '    File: {}, Template: {} \n'.format(substr, tunable_template)
            os.write(fd, bytes(ref_str, 'UTF-8'))
    sims4.commands.output('Dump done', _connection)
    return True

