import sims4.core_services
import sims4.service_manager
import sims4.directory_watcher_handler
if sims4.core_services.SUPPORT_RELOADING_SCRIPTS:
    __all__ = ['DirectoryWatcherService']

    class DirectoryWatcherService(sims4.service_manager.Service):
        __qualname__ = 'DirectoryWatcherService'

        class DirectoryWatcherChangeHandler(sims4.directory_watcher_handler.DirectoryWatcherHandler):
            __qualname__ = 'DirectoryWatcherService.DirectoryWatcherChangeHandler'

            def __init__(self):
                super().__init__()
                self._path = None

            def _paths(self):
                return [self._path]

            def set_paths(self, paths):
                self._path = paths

            def _handle(self, filename):
                sims4.core_services.directory_watcher_manager().register_change(filename)

        def __init__(self):
            self.directory_watcher_handler = self.DirectoryWatcherChangeHandler()
            self.change_sets = {}

        def set_paths(self, paths):
            was_running = self.directory_watcher_handler._watcher is not None
            self.directory_watcher_handler.stop()
            self.directory_watcher_handler.set_paths(paths)
            self.create_set(paths, True)
            if was_running:
                self.directory_watcher_handler.start()

        def stop(self):
            self.directory_watcher_handler.stop()

        def on_tick(self):
            self.directory_watcher_handler.on_tick()

        def create_set(self, name, allow_existing=False):
            if name in self.change_sets:
                if allow_existing:
                    return
                raise KeyError("A change set with the name '{}' already exists.".format(name))
            if not self.change_sets:
                self.directory_watcher_handler.start()
            self.change_sets[name] = set()

        def register_change(self, filename, setname=None):
            if setname is not None:
                self.change_sets[setname].add(filename)
            else:
                for change_set in self.change_sets.values():
                    change_set.add(filename)

        def get_changes(self, name):
            return set(self.change_sets[name])

        def get_change_sets(self):
            return {name: set(change_set) for (name, change_set) in self.change_sets.items()}

        def consume_set(self, name):
            change_set = self.change_sets[name]
            self.change_sets[name] = set()
            return change_set

        def remove_set(self, name):
            del self.change_sets[name]
            if not self.change_sets:
                self.directory_watcher_handler.stop()

