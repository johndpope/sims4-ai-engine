from sims4.tuning.tunable import HasTunableFactory, TunableList, TunableVariant
from statistics.statistic_conditions import TunableStatisticCondition, TunableTimeRangeCondition
from statistics.statistic_ops import DynamicSkillLootOp, GAIN_TYPE_RATE, StatisticAddRelationship, StatisticChangeOp, StatisticOperation, RelationshipOperation, ChangeStatisticByCategory
import alarms
import clock

class TunableAwayActionCondition(TunableVariant):
    __qualname__ = 'TunableAwayActionCondition'

    def __init__(self, *args, **kwargs):
        super().__init__(stat_based=TunableStatisticCondition(description='\n                A condition based on the status of a statistic.\n                '), time_based=TunableTimeRangeCondition(description='\n                The minimum and maximum amount of time required to satisfy this\n                condition.\n                '), default='stat_based', *args, **kwargs)

class PeriodicStatisticChange(HasTunableFactory):
    __qualname__ = 'PeriodicStatisticChange'
    FACTORY_TUNABLES = {'operations': TunableList(description='\n            A list of statistic operations that occur at each interval.\n            ', tunable=TunableVariant(dynamic_skill=DynamicSkillLootOp.TunableFactory(locked_args={'chance': 1, 'exclusive_to_owning_si': False, 'tests': []}), relationship_change=StatisticAddRelationship.TunableFactory(description='\n                    Adds to the relationship score statistic for this Super\n                    Interaction\n                    ', amount=GAIN_TYPE_RATE, locked_args={'chance': 1, 'tests': []}, **RelationshipOperation.DEFAULT_PARTICIPANT_ARGUMENTS), statistic_change=StatisticChangeOp.TunableFactory(description='\n                    Modify the value of a statistic.\n                    ', amount=GAIN_TYPE_RATE, locked_args={'chance': 1, 'exclusive_to_owning_si': False, 'advertise': False, 'tests': []}, **StatisticOperation.DEFAULT_PARTICIPANT_ARGUMENTS), statistic_change_by_category=ChangeStatisticByCategory.TunableFactory(description='\n                    Change value of  all statistics of a specific category.\n                    ', locked_args={'chance': 1, 'tests': []})))}

    def __init__(self, away_action, operations):
        self._away_action = away_action
        self._operations = operations
        self._alarm_handle = None

    def _do_statistic_gain(self, _):
        resolver = self._away_action.get_resolver()
        for operation in self._operations:
            operation.apply_to_resolver(resolver)

    def run(self):
        if self._operations and self._alarm_handle is None:
            time_span = clock.interval_in_sim_minutes(StatisticOperation.STATIC_CHANGE_INTERVAL)
            self._alarm_handle = alarms.add_alarm(self, time_span, self._do_statistic_gain, repeating=True)

    def stop(self):
        if self._alarm_handle is not None:
            alarms.cancel_alarm(self._alarm_handle)

