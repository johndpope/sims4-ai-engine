import contextlib
import math
import operator
from date_and_time import create_time_span
from sims4.repr_utils import standard_repr
from sims4.tuning.tunable import TunableRange
from sims4.utils import classproperty, flexmethod
from singletons import UNSET
from statistics.base_statistic import BaseStatistic
import alarms
import clock
import date_and_time
import services
import sims4.log
import sims4.math
__unittest__ = 'test.statistics.continuous_statistic_tests'
logger = sims4.log.Logger('SimStatistics')

class _ContinuousStatisticCallbackData:
    __qualname__ = '_ContinuousStatisticCallbackData'

    def __init__(self, stat, callback, threshold, repeating, interval, on_callback_alarm_reset=None):
        self._stat = stat
        self._callback = callback
        self._threshold = threshold
        self._trigger_time = UNSET
        self._repeating = repeating
        self._interval = interval
        self._on_callback_alarm_reset = on_callback_alarm_reset

    def __repr__(self):
        return standard_repr(self, stat=self.stat.stat_type.__name__, threshold=self.threshold)

    def reset_trigger_time(self, new_trigger_interval):
        old_trigger_time = self._trigger_time
        now = services.time_service().sim_now
        if new_trigger_interval is not None and new_trigger_interval > 0:
            self._trigger_time = now + clock.interval_in_sim_minutes(new_trigger_interval)
        else:
            self._trigger_time = None
        logger.debug('Resetting trigger time for stat {} at threshold {}; old time: {}, new time: {}', self._stat, self._threshold, old_trigger_time, self._trigger_time)
        if self._trigger_time is None:
            return
        if self._on_callback_alarm_reset is not None:
            self._on_callback_alarm_reset(self._stat, self._trigger_time)

    def destroy(self):
        self._trigger_time = UNSET

    def check_for_threshold(self, old_value, new_value):
        if not self._threshold.compare(old_value) and self._threshold.compare(new_value):
            return True
        return False

    def trigger_callback(self):
        logger.debug('Triggering callback for stat {} at threshold {}; value = {}', self._stat, self._threshold, self._stat.get_value())
        self._callback(self._stat)

    def is_valid(self):
        return self._trigger_time is not UNSET

    def will_be_called_at_the_same_time_as(self, other):
        if self.trigger_time is UNSET or (self.trigger_time is None or other.trigger_time is UNSET) or other.trigger_time is None:
            return False
        if self.trigger_time.absolute_ticks() == other.trigger_time.absolute_ticks():
            return True

    def calculate_interval(self):
        if self._trigger_time is UNSET:
            logger.warn('Attempting to calculate the interval on a callback that was never inserted into the _callbacks list: {}'.format(self))
            return
        if self._trigger_time == None:
            return
        now = services.time_service().sim_now
        delta = self._trigger_time - now
        return delta

    @property
    def stat(self):
        return self._stat

    @property
    def threshold(self):
        return self._threshold

    @threshold.setter
    def threshold(self, value):
        self._threshold = value

    @property
    def interval(self):
        return self._interval

    @property
    def trigger_time(self):
        return self._trigger_time

    @property
    def trigger_value(self):
        return self._threshold.value

    @property
    def repeating(self):
        return self._repeating

    def __lt__(self, other):
        logger.assert_log(self._trigger_time is not UNSET and other._trigger_time is not UNSET, '_trigger_time in _ContinuousStatisticCallbackData was never set.')
        if self._trigger_time is None and other._trigger_time is None:
            return False
        if other._trigger_time is None:
            return True
        if self._trigger_time is None:
            return False
        return self._trigger_time < other._trigger_time

    def __gt__(self, other):
        logger.assert_log(self._trigger_time is not UNSET and other._trigger_time is not UNSET, '_trigger_time in _ContinuousStatisticCallbackData was never set.')
        if self._trigger_time is None and other._trigger_time is None:
            return False
        if other._trigger_time is None:
            return False
        if self._trigger_time is None:
            return True
        return self._trigger_time > other._trigger_time

class ContinuousStatistic(BaseStatistic):
    __qualname__ = 'ContinuousStatistic'
    SAVE_VALUE_MULTIPLE = TunableRange(description='\n        When saving the value of a continuous statistic, we force stats to the \n        nearest multiple of this tunable for save of inventory \n        items to increase the chance of stacking success.-Mike Duke\n        \n        EX: 95+ = 100, 85 to 94.9 = 90, ..., -5 to 5 = 0, ..., -95 to -100 = -100\n        ', tunable_type=int, minimum=1, default=10)
    decay_rate = 0
    _default_convergence_value = 0

    def __init__(self, tracker, initial_value):
        super().__init__(tracker, initial_value)
        self._decay_enabled = False
        self._decay_rate_override = UNSET
        self._callbacks = []
        self._suppress_update_active_callbacks = False
        self._alarm_handle = None
        self._active_callback = None
        if self.max_simulate_time_on_load is not None:
            now = services.time_service().sim_now
            if services.current_zone().is_zone_loading:
                world_game_time = services.game_clock_service().zone_init_world_game_time()
                neg_max_update_time = create_time_span(minutes=-self.max_simulate_time_on_load)
                diff = world_game_time + neg_max_update_time
                if diff > now:
                    update_time = diff
                else:
                    update_time = now
                self._last_update = update_time
            else:
                self._last_update = now
        else:
            self._last_update = services.time_service().sim_now
        self._decay_rate_modifier = 1
        self._decay_rate_modifiers = []
        self._convergence_value = self._default_convergence_value
        self._recalculate_modified_decay_rate()

    def on_initial_startup(self):
        pass

    def start_low_level_simulation(self):
        pass

    def stop_low_level_simulation(self):
        pass

    def stop_regular_simulation(self):
        pass

    @classproperty
    def default_value(cls):
        return cls._default_convergence_value

    @classproperty
    def continuous(self):
        return True

    @classproperty
    def max_simulate_time_on_load(cls):
        pass

    @flexmethod
    def get_value(cls, inst):
        if inst is not None:
            inst._update_value()
        return super(ContinuousStatistic, inst if inst is not None else cls).get_value()

    def set_value(self, value, **kwargs):
        self._update_value()
        old_value = self._value
        super().set_value(value, **kwargs)
        self._update_callbacks(old_value, self._value)

    def on_remove(self, on_destroy=False):
        super().on_remove(on_destroy=on_destroy)
        self._destroy_alarm()
        for callback_data in self._callbacks:
            callback_data.destroy()
        self._callbacks[:] = []
        self._active_callback = None

    def create_callback(self, threshold, callback, repeating=False, on_callback_alarm_reset=None):
        logger.debug('Adding callback for {} with threshold of {}', self, threshold)
        self._update_value()
        interval = None
        if repeating:
            interval = threshold.value
            threshold_value = self._find_nearest_threshold(interval, threshold.comparison)
            if threshold_value is None:
                return
            threshold = sims4.math.Threshold(threshold_value, threshold.comparison)
        callback_data = _ContinuousStatisticCallbackData(self, callback, threshold, repeating, interval, on_callback_alarm_reset=on_callback_alarm_reset)
        return callback_data

    def add_callback(self, threshold, callback, repeating=False, on_callback_alarm_reset=None):
        callback_data = self.create_callback(threshold, callback, repeating=repeating, on_callback_alarm_reset=on_callback_alarm_reset)
        self.add_callback_data(callback_data)
        return callback_data

    def add_callback_data(self, callback_data, update_active_callback=True) -> type(None):
        self._insert_callback_data(callback_data)
        if update_active_callback and callback_data is self._callback_queue_head:
            self._update_active_callback()

    def remove_callback(self, callback_data):
        if callback_data in self._callbacks:
            logger.debug('Removing callback for {} with threshold of {}', self, callback_data.threshold)
            self._callbacks.remove(callback_data)
            callback_data.destroy()
            if self._active_callback is callback_data:
                self._update_active_callback()
            return True
        logger.debug('Failed to remove callback from queue because it was already removed: {}'.format(callback_data))
        return False

    def fixup_callbacks_during_load(self):
        pass

    @property
    def has_callbacks(self):
        return len(self._callbacks) > 0

    @property
    def decay_enabled(self):
        return self._decay_enabled

    @decay_enabled.setter
    def decay_enabled(self, value):
        if self._decay_enabled != value:
            logger.debug('Setting decay for {} to {}', self, value)
            self._update_value()
            self._decay_enabled = value
            self._update_callbacks()
            if value:
                sleep_time_now = services.time_service().sim_now
                if self._last_update is None or self._last_update < sleep_time_now:
                    self._last_update = sleep_time_now

    def get_decay_rate(self, use_decay_modifier=True):
        if self.decay_enabled and self._get_change_rate_without_decay() == 0:
            start_value = self._value
            if use_decay_modifier:
                decay_rate = self.base_decay_rate*self._decay_rate_modifier
            else:
                decay_rate = self.base_decay_rate
            if start_value > self.convergence_value:
                decay_sign = -1
            elif start_value < self.convergence_value:
                decay_sign = 1
            else:
                decay_sign = 0
            return decay_rate*decay_sign
        return 0

    def add_decay_rate_modifier(self, value):
        if value < 0:
            logger.error('Attempting to add negative decay rate modifier of {} to {}', value, self)
            return
        logger.debug('Adding decay rate modifier of {} to {}', value, self)
        self._update_value()
        self._decay_rate_modifiers.append(value)
        self._recalculate_modified_decay_rate()

    def remove_decay_rate_modifier(self, value):
        if value in self._decay_rate_modifiers:
            logger.debug('Removing decay rate modifier of {} from {}', value, self)
            self._update_value()
            self._decay_rate_modifiers.remove(value)
            self._recalculate_modified_decay_rate()

    def get_decay_rate_modifier(self):
        return self._decay_rate_modifier

    @property
    def convergence_value(self):
        return self._convergence_value

    @convergence_value.setter
    def convergence_value(self, value):
        self._convergence_value = value
        self._update_callbacks()

    def reset_convergence_value(self):
        self._convergence_value = self._default_convergence_value
        self._update_callbacks()

    def is_at_convergence(self):
        if self.get_value() == self.convergence_value:
            return True
        return False

    def get_decay_time(self, threshold, use_decay_modifier=True):
        self._update_value()
        return self._calculate_minutes_until_value_is_reached_through_decay(threshold.value, threshold, use_decay_modifier=use_decay_modifier)

    def get_change_rate(self):
        change_rate = self._get_change_rate_without_decay()
        if change_rate != 0:
            return change_rate
        return self.get_decay_rate()

    def get_change_rate_without_decay(self):
        return self._get_change_rate_without_decay()

    @property
    def base_decay_rate(self):
        if self._decay_rate_override is not UNSET:
            return self._decay_rate_override
        return self.decay_rate

    def _get_change_rate_without_decay(self):
        if self._statistic_modifier > 0:
            return self._statistic_modifier*self._statistic_multiplier_increase
        return self._statistic_modifier*self._statistic_multiplier_decrease

    def _update_value(self):
        now = services.time_service().sim_now
        delta_time = now - self._last_update
        if delta_time <= date_and_time.TimeSpan.ZERO:
            return 0
        self._last_update = now
        local_time_delta = delta_time.in_minutes()
        start_value = self._value
        change_rate = self._get_change_rate_without_decay()
        decay_rate = self.get_decay_rate()
        new_value = None
        if change_rate == 0 and decay_rate != 0:
            time_to_convergence = self._calculate_minutes_until_value_is_reached_through_decay(self.convergence_value)
            if time_to_convergence is not None and local_time_delta > time_to_convergence:
                new_value = self.convergence_value
            delta_rate = decay_rate
        else:
            delta_rate = change_rate
        if new_value is None:
            new_value = start_value + local_time_delta*delta_rate
        self._value = new_value
        self._clamp()
        return local_time_delta

    @contextlib.contextmanager
    def _suppress_update_active_callbacks_context_manager(self):
        if self._suppress_update_active_callbacks:
            yield None
        else:
            self._suppress_update_active_callbacks = True
            try:
                yield None
            finally:
                self._suppress_update_active_callbacks = False

    def _update_callbacks(self, old_value=0, new_value=0, resort_list=True):
        self._update_value()
        callback_tuple = None
        if old_value <= new_value:
            callback_tuple = tuple(self._callbacks)
        else:
            callback_tuple = tuple(reversed(self._callbacks))
        for callback_data in callback_tuple:
            if old_value != new_value and callback_data.check_for_threshold(old_value, new_value):
                callback_data.trigger_callback()
                if callback_data.repeating:
                    comparison = callback_data.threshold.comparison
                    next_interval = self._find_nearest_threshold(callback_data.interval, comparison)
                    if next_interval is not None:
                        next_threshold = sims4.math.Threshold(next_interval, comparison)
                        callback_data.threshold = next_threshold
            trigger_interval = self._calculate_minutes_until_value_is_reached_through_decay(callback_data.threshold.value, callback_data.threshold)
            callback_data.reset_trigger_time(trigger_interval)
        if resort_list:
            self._callbacks.sort()
        self._update_active_callback()

    def _update_active_callback(self):
        if self._suppress_update_active_callbacks:
            return
        if not self._callbacks:
            if self._active_callback is not None or self._alarm_handle:
                logger.debug('_callback list is empty; destroying alarm & active callback.  Last active callback was {}'.format(self._active_callback))
                self._destroy_alarm()
                self._active_callback = None
            return
        self._destroy_alarm()
        while self._callbacks:
            callback_data = self._callback_queue_head
            interval = callback_data.calculate_interval()
            if interval is None:
                self._active_callback = None
                break
            if interval.in_ticks() <= 0:
                self._trigger_callback(callback_data)
                self._update_active_callback()
            else:
                if self._alarm_handle:
                    self._destroy_alarm()
                logger.debug('Creating alarm for callback: {}'.format(callback_data))
                self._alarm_handle = alarms.add_alarm(self, interval, self._alarm_callback)
                self._active_callback = callback_data
                break

    def _destroy_alarm(self):
        if self._alarm_handle is not None:
            alarms.cancel_alarm(self._alarm_handle)
            self._alarm_handle = None

    def _alarm_callback(self, handle):
        self._alarm_handle = None
        callbacks_to_call = [callback for callback in self._callbacks if self._active_callback.will_be_called_at_the_same_time_as(callback)]
        with self._suppress_update_active_callbacks_context_manager():
            for callback in callbacks_to_call:
                self._trigger_callback(callback)
        self._update_active_callback()

    def _trigger_callback(self, callback):
        if callback is None:
            logger.error('Attempting to trigger a None callback.')
            self._update_active_callback()
            return
        callback.trigger_callback()
        if self.remove_callback(callback):
            self.add_callback_data(callback, update_active_callback=False)

    @property
    def _callback_queue_head(self):
        if self._callbacks:
            return self._callbacks[0]

    def _insert_callback_data(self, callback_data):
        self._update_value()
        trigger_interval = self._calculate_minutes_until_value_is_reached_through_decay(callback_data.threshold.value, callback_data.threshold)
        callback_data.reset_trigger_time(trigger_interval)
        try:
            insertion_index = self._find_insertion_point(0, len(self._callbacks), callback_data)
        except Exception:
            if self.tracker and self.tracker.owner and self.tracker.owner.is_sim:
                self.tracker.owner.log_sim_info(logger.error, additional_msg='Failed to find insertion point for {}.'.format(self))
            else:
                logger.error('Failed to find insertion point for {}.', self)
            raise
        self._callbacks.insert(insertion_index, callback_data)

    def _find_insertion_point(self, start, end, callback_data):
        if start == end:
            return start
        index = int((start + end)/2)
        if index == len(self._callbacks):
            return index
        if callback_data > self._callbacks[index]:
            return self._find_insertion_point(index + 1, end, callback_data)
        if index == 0 or callback_data < self._callbacks[index] and callback_data < self._callbacks[index - 1]:
            return self._find_insertion_point(start, end - 1, callback_data)
        return index

    def _find_nearest_threshold(self, interval, comparison):
        num_intervals = (self.get_value() - self.min_value)/interval
        if comparison is operator.ge or comparison is operator.gt:
            next_interval = math.floor(num_intervals) + 1
        else:
            next_interval = math.ceil(num_intervals) - 1
        threshold = next_interval*interval + self.min_value
        if threshold >= self.min_value and threshold <= self.max_value:
            return threshold

    def _calculate_minutes_until_value_is_reached_through_decay(self, target_value, threshold=None, use_decay_modifier=True):
        if threshold is not None:
            if threshold.comparison is operator.gt:
                target_value = target_value + sims4.math.EPSILON
            elif threshold.comparison is operator.lt:
                target_value = target_value - sims4.math.EPSILON
        decay_rate = self.get_decay_rate(use_decay_modifier=use_decay_modifier)
        change_rate = self._get_change_rate_without_decay()
        current_value = self._value
        if threshold is not None and threshold.compare(current_value):
            return 0
        if current_value == target_value:
            return 0
        if change_rate != 0:
            if change_rate > 0 and target_value > current_value or change_rate < 0 and target_value < current_value:
                result = (target_value - current_value)/change_rate
                return abs(result)
            return
        else:
            if decay_rate != 0:
                if decay_rate < 0 and target_value > current_value or decay_rate > 0 and target_value < current_value:
                    return
                if current_value < self.convergence_value < target_value or current_value > self.convergence_value > target_value:
                    return
                result = (target_value - current_value)/decay_rate
                return abs(result)
            return

    def _recalculate_modified_decay_rate(self):
        old_decay_rate = self.get_decay_rate()
        self._decay_rate_modifier = 1
        for val in self._decay_rate_modifiers:
            pass
        if self.tracker is not None:
            multiplier = self.get_skill_based_statistic_multiplier([self.tracker.owner], -1)
        resort_callbacks = False
        if old_decay_rate == 0 and self.get_decay_rate() != 0:
            resort_callbacks = True
        self._update_callbacks(resort_list=resort_callbacks)

    def add_statistic_modifier(self, value):
        self._update_value()
        super().add_statistic_modifier(value)

    def remove_statistic_modifier(self, value):
        if value in self._statistic_modifiers:
            self._update_value()
            super().remove_statistic_modifier(value)
            self._update_value()

    def _on_statistic_modifier_changed(self, notify_watcher=True):
        self._update_value()
        super()._on_statistic_modifier_changed(notify_watcher=notify_watcher)
        self._update_callbacks()

    @flexmethod
    def get_saved_value(cls, inst):
        cls_or_inst = inst if inst is not None else cls
        value = cls_or_inst.get_value()
        if inst is not None:
            owner = inst._tracker.owner
            if owner is not None and owner.inventoryitem_component:
                value = round(value/cls.SAVE_VALUE_MULTIPLE)*cls.SAVE_VALUE_MULTIPLE
        return value

