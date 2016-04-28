import collections
from singletons import DEFAULT
import services
import sims4.callback_utils
import sims4.log
import uid
logger = sims4.log.Logger('Statistic')

class _StatisticTrackerListenerEntry:
    __qualname__ = '_StatisticTrackerListenerEntry'
    __slots__ = ('threshold', 'callback', 'callback_handler')

    def __init__(self, threshold, callback, callback_handler):
        self.threshold = threshold
        self.callback = callback
        self.callback_handler = callback_handler

_StatisticTrackerListener = collections.namedtuple('_StatisticTrackerListener', ['stat_type', 'handle_id', 'entry'])

class BaseStatisticTracker:
    __qualname__ = 'BaseStatisticTracker'

    def __init__(self, owner=None):
        self._statistics = {}
        self._owner = owner
        self._listeners = {}
        self._watchers = {}
        self._on_remove_callbacks = sims4.callback_utils.CallableList()
        self._handle_id_gen_listeners = uid.UniqueIdGenerator(1)
        self._handle_id_gen_watchers = uid.UniqueIdGenerator(1)
        self.suppress_callback_setup_during_load = False

    def __iter__(self):
        return self._statistics.values().__iter__()

    def __len__(self):
        return len(self._statistics)

    @property
    def owner(self):
        return self._owner

    def _statistics_values_gen(self):
        for stat in self._statistics.values():
            yield stat

    def destroy(self):
        for stat in list(self):
            stat.on_remove(on_destroy=True)
        self._listeners.clear()
        self._watchers.clear()
        self._on_remove_callbacks.clear()

    def on_initial_startup(self):
        pass

    def create_listener(self, stat_type, threshold, callback, on_callback_alarm_reset=None) -> _StatisticTrackerListener:
        handle_id = self._handle_id_gen_listeners()
        stat = self.get_statistic(stat_type, add=stat_type.add_if_not_in_tracker)
        if stat is not None:
            callback_handler = stat.create_callback(threshold, callback, on_callback_alarm_reset=on_callback_alarm_reset)
            entry = _StatisticTrackerListenerEntry(threshold, callback, callback_handler)
            return _StatisticTrackerListener(stat_type, handle_id, entry)
        callback_handler = None
        return

    def activate_listener(self, listener) -> type(None):
        if listener.stat_type not in self._listeners:
            self._listeners[listener.stat_type] = {}
        stat = self.get_statistic(listener.stat_type)
        self._listeners[listener.stat_type][listener.handle_id] = listener
        if listener.entry.callback_handler is None:
            listener.entry.callback_handler = stat.create_callback(listener.entry.threshold, listener.entry.callback)
        if stat is not None and listener.entry.callback_handler is not None:
            stat.add_callback_data(listener.entry.callback_handler)

    def create_and_activate_listener(self, stat_type, threshold, callback, on_callback_alarm_reset=None) -> _StatisticTrackerListener:
        listener = self.create_listener(stat_type, threshold, callback, on_callback_alarm_reset=on_callback_alarm_reset)
        if listener is not None:
            self.activate_listener(listener)
        return listener

    def remove_listener(self, listener):
        if listener.stat_type not in self._listeners:
            return
        callback_handler = listener.entry.callback_handler
        if callback_handler is not None:
            stat = self.get_statistic(listener.stat_type)
            if stat is not None:
                stat.remove_callback(listener.entry.callback_handler)
                listener.entry.callback_handler = None
        stat_handle_map = self._listeners[listener.stat_type]
        listener.entry.callback = None
        stat_handle_map.pop(listener.handle_id, None)

    def has_listener(self, stat_type):
        return stat_type in self._listeners

    def add_watcher(self, callback):
        handle_id = self._handle_id_gen_watchers()
        self._watchers[handle_id] = callback
        return handle_id

    def has_watcher(self, handle):
        return handle in self._watchers

    def remove_watcher(self, handle):
        del self._watchers[handle]

    def _change_watcher(self, stat):

        def notify(old_value, new_value):
            stat_type = type(stat)
            self._notify_listeners(stat_type, old_value, new_value)

        return sims4.utils.EdgeWatcher(lambda : stat.get_value(), notify)

    def _notify_listeners(self, stat_type, old_value, new_value):
        if stat_type not in self._listeners:
            return
        for listener in tuple(self._listeners[stat_type].values()):
            listener_entry = listener.entry
            if listener_entry.callback_handler is not None:
                pass
            while listener_entry.threshold is None or listener_entry.threshold.compare(new_value):
                listener_entry.callback(stat_type)

    def notify_watchers(self, stat_type, old_value, new_value):
        for watcher in list(self._watchers.values()):
            watcher(stat_type, old_value, new_value)

    def add_on_remove_callback(self, callback):
        self._on_remove_callbacks.append(callback)

    def remove_on_remove_callback(self, callback):
        if callback in self._on_remove_callbacks:
            self._on_remove_callbacks.remove(callback)

    def add_statistic(self, stat_type, owner=None, **kwargs):
        stat = self._statistics.get(stat_type)
        if owner is None:
            owner = self._owner
        if stat is None and stat_type.can_add(owner, **kwargs):
            stat = stat_type(self)
            self._statistics[stat_type] = stat
            stat.on_add()
            value = stat.get_value()
            self._notify_listeners(stat_type, value, value)
            self.notify_watchers(stat_type, value, value)
        return stat

    def remove_statistic(self, stat_type, on_destroy=False):
        if self.has_statistic(stat_type):
            stat = self._statistics[stat_type]
            listeners = self._listeners.get(stat_type)
            if listeners is not None:
                for listener in listeners.values():
                    while listener.entry.callback_handler is not None:
                        stat.remove_callback(listener.entry.callback_handler)
            del self._statistics[stat_type]
            self._on_remove_callbacks(stat)
            stat.on_remove(on_destroy=on_destroy)

    def get_statistic(self, stat_type, add=False):
        stat = self._statistics.get(stat_type)
        if stat is None and add:
            stat = self.add_statistic(stat_type)
        return stat

    def has_statistic(self, stat_type):
        return stat_type in self._statistics

    def get_value(self, stat_type, add=False):
        stat = self.get_statistic(stat_type, add=add)
        if stat is not None:
            return stat.get_value()
        return stat_type.default_value

    def get_int_value(self, stat_type, scale:int=None):
        value = self.get_value(stat_type)
        if scale is not None:
            value = scale*value/stat_type.max_value
        return int(sims4.math.floor(value))

    def get_user_value(self, stat_type):
        stat = self.get_statistic(stat_type)
        if stat is not None:
            return stat.get_user_value()
        return stat_type.default_user_value

    def set_value(self, stat_type, value, add=DEFAULT, from_load=False, **kwargs):
        if add is DEFAULT:
            add = stat_type.add_if_not_in_tracker or from_load
        stat = self.get_statistic(stat_type, add=add)
        if stat is not None:
            with self._change_watcher(stat):
                stat.set_value(value, from_load=from_load)

    def set_user_value(self, stat_type, user_value):
        stat = self.get_statistic(stat_type, add=True)
        with self._change_watcher(stat):
            stat.set_user_value(user_value)

    def add_value(self, stat_type, amount, **kwargs):
        if amount == 0:
            logger.warn('Attempting to add 0 to stat {}', stat_type)
            return
        stat = self.get_statistic(stat_type, add=stat_type.add_if_not_in_tracker)
        if stat is not None:
            with self._change_watcher(stat):
                stat.add_value(amount, **kwargs)

    def set_max(self, stat_type):
        stat = self.get_statistic(stat_type, add=stat_type.add_if_not_in_tracker)
        if stat is not None:
            self.set_value(stat_type, stat.max_value)

    def set_min(self, stat_type):
        stat = self.get_statistic(stat_type, add=stat_type.add_if_not_in_tracker)
        if stat is not None:
            self.set_value(stat_type, stat.min_value)

    def get_decay_time(self, stat_type, threshold):
        pass

    def set_convergence(self, stat_type, convergence):
        raise TypeError("This stat type doesn't have a convergence value.")

    def reset_convergence(self, stat_type):
        raise TypeError("This stat type doesn't have a convergence value.")

    def set_all_commodities_to_max(self, visible_only=False, core_only=False):
        for stat_type in list(self._statistics):
            stat = self.get_statistic(stat_type)
            while stat is not None:
                if not visible_only and not core_only or visible_only and stat.is_visible or core_only and stat.core:
                    self.set_value(stat_type, stat_type.max_value)

    def save(self):
        save_list = []
        for stat in self._statistics.values():
            while stat.persisted:
                value = stat.get_saved_value()
                save_data = (type(stat).__name__, value)
                save_list.append(save_data)
        return save_list

    def load(self, load_list):
        try:
            for (stat_type_name, value) in load_list:
                stat_cls = services.get_instance_manager(sims4.resources.Types.STATISTIC).get(stat_type_name)
                while stat_cls is not None:
                    if stat_cls.persisted:
                        self.set_value(stat_cls, value)
                    else:
                        logger.warn('Object has a saved value for {}, which is not a persisted statistic. Discarding value.', stat_cls)
        except ValueError:
            logger.error('Attempting to load old data in BaseStatisticTracker.load()')

    def debug_output_all(self, _connection):
        for stat in self._statistics.values():
            sims4.commands.output('{:<24} Value: {:-6.2f}'.format(stat.__class__.__name__, stat.get_value()), _connection)

    def debug_set_all_to_max_except(self, stat_to_exclude, core=True):
        for stat_type in list(self._statistics):
            while not core or self.get_statistic(stat_type).core:
                if stat_type != stat_to_exclude:
                    self.set_value(stat_type, stat_type.max_value)

    def debug_set_all_to_min(self, core=True):
        for stat_type in list(self._statistics):
            while not core or self.get_statistic(stat_type).core:
                self.set_value(stat_type, stat_type.min_value)

    def debug_set_all_to_default(self, core=True):
        for stat_type in list(self._statistics):
            while not core or self.get_statistic(stat_type).core:
                self.set_value(stat_type, stat_type.initial_value)

