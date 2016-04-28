import sims4.commands
import sims4.telemetry

@sims4.commands.Command('telemetry.add_filter')
def add_filter(priority, action, module_tag, group_tag, hook_tag, _connection=None, **kwargs):
    output = sims4.commands.Output(_connection)
    if module_tag == '*':
        module_tag = None
    if group_tag == '*':
        group_tag = None
    if hook_tag == '*':
        hook_tag = None
    filter_action = sims4.telemetry.RuleAction(action)
    fields = kwargs
    sims4.telemetry.add_filter_rule(priority, module_tag, group_tag, hook_tag, fields, filter_action)
    output('Filter added')

@sims4.commands.Command('telemetry.remove_filter')
def remove_filter(priority, action, module_tag, group_tag, hook_tag, _connection=None, **kwargs):
    output = sims4.commands.Output(_connection)
    if module_tag == '*':
        module_tag = None
    if group_tag == '*':
        group_tag = None
    if hook_tag == '*':
        hook_tag = None
    filter_action = sims4.telemetry.RuleAction(action)
    fields = kwargs
    result = sims4.telemetry.remove_filter_rule(priority, module_tag, group_tag, hook_tag, fields, filter_action)
    if result:
        output('Filter removed')
    else:
        output('No matching filter')

@sims4.commands.Command('telemetry.clear_filters')
def clear_filters(_connection=None):
    del sims4.telemetry._filters[:]

@sims4.commands.Command('telemetry.list_filters')
def list_filters(_connection=None):
    output = sims4.commands.Output(_connection)
    for (priority, tags, fields, action) in sims4.telemetry._filters:
        module_tag = group_tag = hook_tag = '*'
        if len(tags) > 0:
            module_tag = tags[0]
        if len(tags) > 1:
            group_tag = tags[1]
        if len(tags) > 2:
            hook_tag = tags[2]
        output('{:4} {:8} {:4} {:4} {:4} {}'.format(priority, action.name, module_tag, group_tag, hook_tag, fields))

