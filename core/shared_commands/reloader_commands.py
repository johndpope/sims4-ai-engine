import sims4.commands
import sims4.core_services
import sims4.log
import sims4.reload_service
logger = sims4.log.Logger('Reloader Commands')

@sims4.commands.Command('hot.files.list')
def hot_files_list(_connection=None):
    output = sims4.commands.Output(_connection)
    for (name, change_set) in sims4.core_services.directory_watcher_manager().get_change_sets().items():
        output("Change Set '{}':".format(name))
        filenames = list(change_set)
        filenames.sort()
        for filename in filenames:
            output('  {}'.format(filename))

@sims4.commands.Command('hot.files.consume')
def hot_files_consume(name, _connection=None):
    output = sims4.commands.Output(_connection)
    output("Change Set '{}':".format(name))
    filenames = list(sims4.core_services.directory_watcher_manager().consume_set(name))
    for filename in sorted(filenames):
        output('  {}'.format(filename))

@sims4.commands.Command('hot.reload')
def hot_reload(_connection=None):
    sims4.reload_service.trigger_reload(sims4.commands.Output(_connection))

