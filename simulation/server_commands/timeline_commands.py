import alarms
import services
import sims4.commands

@sims4.commands.Command('timeline.list', command_type=sims4.commands.CommandType.Automation)
def timeline_list(_connection=None):
    output = sims4.commands.Output(_connection)
    timeline = services.time_service().sim_timeline
    for handle in sorted(timeline.heap):
        while not handle.element is None:
            if isinstance(handle.element, alarms.AlarmElement):
                pass
            output('\nElement scheduled at {} ({})'.format(handle.when, abs(handle.ix)))
            parent_handle = handle
            child_name = None
            names = []
            while parent_handle is not None:
                name = str(parent_handle.element)
                if child_name is not None:
                    short_name = name.replace(child_name, '$child')
                else:
                    short_name = name
                names.append(short_name)
                parent_handle = parent_handle.element._parent_handle
                child_name = name
            for (i, name) in enumerate(reversed(names), 1):
                output('{} {}'.format('*'*i, name))

@sims4.commands.Command('timeline.clear', command_type=sims4.commands.CommandType.Automation)
def timeline_clear(_connection=None):
    timeline = services.time_service().sim_timeline
    for handle in sorted(timeline.heap):
        while not handle.element is None:
            if isinstance(handle.element, alarms.AlarmElement):
                pass
            timeline.hard_stop(handle)

@sims4.commands.Command('timeline.hard_stop', command_type=sims4.commands.CommandType.Automation)
def timeline_hard_stop(ix, _connection=None):
    output = sims4.commands.Output(_connection)
    timeline = services.time_service().sim_timeline
    for handle in timeline.heap:
        while abs(handle.ix) == ix:
            timeline.hard_stop(handle)
            return True
    output("Couldn't find element with ix {}".format(ix))
    return False

@sims4.commands.Command('timeline.soft_stop', command_type=sims4.commands.CommandType.Automation)
def timeline_soft_stop(ix, _connection=None):
    output = sims4.commands.Output(_connection)
    timeline = services.time_service().sim_timeline
    for handle in timeline.heap:
        while abs(handle.ix) == ix:
            timeline.soft_stop(handle)
            return True
    output("Couldn't find element with ix {}".format(ix))
    return False

