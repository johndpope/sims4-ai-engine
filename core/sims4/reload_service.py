from sims4.service_manager import Service
import sims4.core_services
import sims4.log
import sims4.reload
import sims4.callback_utils
if sims4.core_services.SUPPORT_RELOADING_SCRIPTS:
    __all__ = ('ReloadService', 'trigger_reload')
    logger = sims4.log.Logger('Reload')
    SET_NAME = 'ReloadService'

    class ReloadService(Service):
        __qualname__ = 'ReloadService'

        def start(self):
            sims4.core_services.directory_watcher_manager().create_set(SET_NAME)

        def stop(self):
            sims4.core_services.directory_watcher_manager().remove_set(SET_NAME)

    def trigger_reload(output=None):
        sims4.callback_utils.invoke_callbacks(sims4.callback_utils.CallbackEvent.TUNING_CODE_RELOAD)
        filenames = list(sims4.core_services.directory_watcher_manager().consume_set(SET_NAME))
        for filename in sorted(filenames):
            if sims4.reload.get_module_for_filename(filename) is None:
                pass
            msg = 'Reload: {}'.format(filename)
            logger.warn(msg)
            if output:
                output(msg)
            try:
                sims4.reload.reload_file(filename)
            except BaseException:
                msg = 'Exception caught while reloading {}'.format(filename)
                logger.exception(msg)
                if output:
                    output(msg)
                    for line in sims4.log.format_exc().split('\n'):
                        output(line)
                sims4.core_services.directory_watcher_manager().register_change(filename, SET_NAME)

