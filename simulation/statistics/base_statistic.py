from collections import namedtuple
from interactions import ParticipantType
from sims4.utils import classproperty, flexmethod, flexproperty
import caches
import enum
import sims4.log
import sims4.math
__unittest__ = 'test.statistics.base_statistic_tests'
logger = sims4.log.Logger('SimStatistics')

class StatisticChangeDirection(enum.Int):
    __qualname__ = 'StatisticChangeDirection'
    INCREASE = 0
    DECREASE = 1
    BOTH = 2

class BaseStatistic:
    __qualname__ = 'BaseStatistic'
    decay_rate = 0.0
    _utility_curve = None
    SkillBasedMultiplier = namedtuple('SkillBasedMultiplier', ['curve', 'use_effective_skill'])
    _skill_based_statistic_multipliers_increase = {}
    _skill_based_statistic_multipliers_decrease = {}

    def __init__(self, tracker, initial_value):
        self._tracker = tracker
        self._value = initial_value
        self._locked = 0
        self._statistic_modifier = 0
        self._statistic_modifiers = []
        self._statistic_multiplier_increase = 1.0
        self._statistic_multiplier_decrease = 1.0
        self._statistic_multipliers = []

    def __repr__(self):
        statistic_type_name = type(self).__mro__[1].__name__
        statistic_instance_name = type(self).__name__
        return '{}({}@{})'.format(statistic_type_name, statistic_instance_name, self._value)

    @classproperty
    def max_value(cls):
        raise NotImplementedError

    @classproperty
    def min_value(cls):
        raise NotImplementedError

    @classproperty
    def persisted(cls):
        raise NotImplementedError

    @classproperty
    def stat_type(cls):
        return cls

    @classmethod
    def type_id(cls):
        return cls.guid64

    @classmethod
    def get_skill_based_statistic_multiplier(cls, targets, add_amount):
        multiplier = 1
        if add_amount < 0:
            if cls not in cls._skill_based_statistic_multipliers_decrease:
                return multiplier
            skill_map = cls._skill_based_statistic_multipliers_decrease.get(cls)
        else:
            if cls not in cls._skill_based_statistic_multipliers_increase:
                return multiplier
            skill_map = cls._skill_based_statistic_multipliers_increase.get(cls)
        for target in targets:
            for skill_type in skill_map:
                skill = target.get_stat_instance(skill_type)
                while skill is not None:
                    modifier = skill_map[skill_type]
                    if modifier.use_effective_skill:
                        value = target.Buffs.get_effective_skill_level(skill)
                    else:
                        value = skill.get_user_value()
                    multiplier *= modifier.curve.get(value)
        return multiplier

    @classmethod
    def add_skill_based_statistic_multiplier(cls, skill_type, curve, direction, use_effective_skill):
        increase_dict = cls._skill_based_statistic_multipliers_increase
        decrease_dict = cls._skill_based_statistic_multipliers_decrease
        if direction != StatisticChangeDirection.DECREASE:
            if cls not in increase_dict:
                increase_dict[cls] = {}
            increase_dict[cls][skill_type] = cls.SkillBasedMultiplier(curve, use_effective_skill)
        if direction != StatisticChangeDirection.INCREASE:
            if cls not in decrease_dict:
                decrease_dict[cls] = {}
            decrease_dict[cls][skill_type] = cls.SkillBasedMultiplier(curve, use_effective_skill)

    @classproperty
    def continuous(self):
        return False

    def get_statistic_multiplier_increase(self):
        return self._statistic_multiplier_increase

    def get_statistic_multiplier_decrease(self):
        return self._statistic_multiplier_decrease

    def on_add(self):
        pass

    def on_remove(self, on_destroy=False):
        owner = self._tracker.owner if self._tracker is not None else None
        if owner is not None and not owner.is_sim:
            self._tracker = None

    @property
    def tracker(self):
        return self._tracker

    def get_asm_param(self, *_):
        return (None, None)

    @flexmethod
    def get_value(cls, inst):
        if inst is not None:
            return inst._value
        return cls.default_value

    @flexmethod
    def get_saved_value(cls, inst):
        cls_or_inst = inst if inst is not None else cls
        value = cls_or_inst.get_value()
        return value

    def set_value(self, value, **kwargs):
        old_value = self._value
        self._value = value
        self._clamp()
        if old_value != self._value and self._tracker is not None:
            self._tracker.notify_watchers(self.stat_type, old_value, self._value)
        caches.clear_all_caches()

    def add_value(self, add_amount, interaction=None, min_value=None, max_value=None, **kwargs):
        if self.tracker is not None and self.tracker.owner is not None and self.tracker.owner.is_locked(self):
            return
        multiplier = 1
        if interaction is not None:
            sims = interaction.get_participants(ParticipantType.AllSims)
            multiplier = self.get_skill_based_statistic_multiplier(sims, add_amount)
        if add_amount < 0:
            multiplier *= self.get_statistic_multiplier_decrease()
        else:
            multiplier *= self.get_statistic_multiplier_increase()
        new_value = self.get_value() + add_amount*multiplier
        self.set_value(new_value, **kwargs)

    def get_user_value(self):
        return self.convert_to_user_value(self.get_value())

    def set_user_value(self, value):
        self.set_value(self.convert_from_user_value(value))

    def add_statistic_modifier(self, value):
        if value == 0:
            logger.warn('Attempting to add statistic modifier with value zero to {}', self)
            return
        logger.debug('Adding statistic modifier of {} to {}', value, self)
        self._statistic_modifiers.append(value)
        self._on_statistic_modifier_changed()

    def remove_statistic_modifier(self, value):
        if value in self._statistic_modifiers:
            logger.debug('Removing statistic modifier of {} from {}', value, self)
            self._statistic_modifiers.remove(value)
            if self._statistic_modifiers:
                pass
            else:
                self._statistic_modifier = 0
            self._on_statistic_modifier_changed()

    def _recalculate_statistic_multiplier(self, value):
        if value.apply_direction == StatisticChangeDirection.BOTH or value.apply_direction == StatisticChangeDirection.INCREASE:
            pass
        if value.apply_direction == StatisticChangeDirection.BOTH or value.apply_direction == StatisticChangeDirection.DECREASE:
            pass

    def add_statistic_multiplier(self, value):
        logger.debug('Adding statistic multiplier of {} to {}', value, self)
        self._statistic_multipliers.append(value)
        self._recalculate_statistic_multiplier(value)
        self._on_statistic_modifier_changed(notify_watcher=self._statistic_modifier != 0)

    def remove_statistic_multiplier(self, value):
        if value in self._statistic_multipliers:
            logger.debug('Removing statistic multiplier of {} from {}', value, self)
            self._statistic_multipliers.remove(value)
            if self._statistic_multipliers:
                if value.multiplier == 0:
                    self._statistic_multiplier_increase = 1.0
                    self._statistic_multiplier_decrease = 1.0
                    while True:
                        for statistic_multiplier in self._statistic_multipliers:
                            self._recalculate_statistic_multiplier(statistic_multiplier)
                        if value.apply_direction == StatisticChangeDirection.BOTH or value.apply_direction == StatisticChangeDirection.INCREASE:
                            pass
                elif value.apply_direction == StatisticChangeDirection.BOTH or value.apply_direction == StatisticChangeDirection.INCREASE:
                    pass
            else:
                self._statistic_multiplier_increase = 1.0
                self._statistic_multiplier_decrease = 1.0
            self._on_statistic_modifier_changed(notify_watcher=self._statistic_modifier != 0)

    def _on_statistic_modifier_changed(self, notify_watcher=True):
        if notify_watcher and self._tracker is not None:
            self._tracker.notify_watchers(self.stat_type, self._value, self._value)

    @classproperty
    def default_value(cls):
        return 0

    @classproperty
    def default_user_value(cls):
        return cls.default_value

    @classmethod
    def convert_to_user_value(cls, value):
        return value

    @classmethod
    def convert_from_user_value(cls, user_value):
        return user_value

    @property
    def core(self):
        return False

    @property
    def is_visible(self):
        return False

    @classproperty
    def is_scored(cls):
        if cls._utility_curve:
            return True
        return False

    @flexproperty
    def autonomous_desire(cls, inst):
        this = inst if inst is not None else cls
        if this._utility_curve:
            return this._utility_curve.get(this.get_value())
        return 0

    @classproperty
    def autonomy_weight(cls):
        return 1

    @classproperty
    def use_stat_value_on_initialization(cls):
        return True

    def lock(self):
        pass

    def unlock(self):
        if self._locked > 0:
            pass
        else:
            logger.warn('BaseStatistic._locked variable became out of sync.')

    @classmethod
    def clamp(cls, value):
        return sims4.math.clamp(cls.min_value, value, cls.max_value)

    def _clamp(self, value=None):
        if value is None:
            value = self._value
        self._value = sims4.math.clamp(self.min_value, value, self.max_value)

    @classmethod
    def _build_utility_curve_from_tuning_data(cls, data, weight=1):
        if data:
            point_list = [(point.x, point.y) for point in data]
            cls._utility_curve = sims4.math.WeightedUtilityCurve(point_list, max_y=1, weight=weight)

    @classmethod
    def can_add(cls, owner):
        return True

    @classproperty
    def is_skill(cls):
        return False

    @classproperty
    def add_if_not_in_tracker(cls):
        return True

    def create_callback(self, threshold, callback, repeating=False, on_callback_alarm_reset=None):
        pass

    @classmethod
    def get_categories(cls):
        return ()

    @classproperty
    def valid_for_stat_testing(cls):
        return False

