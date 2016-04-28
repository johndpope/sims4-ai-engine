from event_testing.tests import TunableTestSet
from interactions import ParticipantType
from sims4.tuning.geometric import TunableCurve
from sims4.tuning.tunable import AutoFactoryInit, HasTunableSingletonFactory, TunableList, TunableTuple, TunableRange, Tunable, TunableFactory, TunableVariant, TunableReference, TunableEnumEntry
import services
import sims4

class TestedSum(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'TestedSum'
    FACTORY_TUNABLES = {'base_value': Tunable(description='\n            The basic value to return if no modifiers are applied.\n            ', default=0, tunable_type=float), 'modifiers': TunableList(description='\n            A list of modifiers to add to Base Value.\n            ', tunable=TunableTuple(modifier=Tunable(description='\n                    The value to apply add to Base Value if the associated\n                    tests pass. Can be negative\n                    ', tunable_type=float, default=0), tests=TunableTestSet(description='\n                    A series of tests that must pass in order for the modifier\n                    to be applied.\n                    ')))}

    def get_sum(self, participant_resolver):
        return sum((mod.modifier for mod in self.modifiers if mod.tests.run_tests(participant_resolver)), self.base_value)

    def get_max_modifier(self, participant_resolver):
        max_value = 0
        for mod in self.modifiers:
            while mod.tests.run_tests(participant_resolver):
                max_value = max(max_value, mod.modifier)
        return self.base_value + max_value

class TunableMultiplier(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'TunableMultiplier'
    FACTORY_TUNABLES = {'base_value': Tunable(description='\n            The basic value to return if no modifications are applied.\n            ', default=1, tunable_type=float), 'multipliers': TunableList(description='\n            A list of multipliers to apply to base_value.\n            ', tunable=TunableTuple(multiplier=TunableRange(description='\n                    The multiplier to apply to base_value if the associated\n                    tests pass.\n                    ', tunable_type=float, default=1, minimum=0), tests=TunableTestSet(description='\n                    A series of tests that must pass in order for multiplier to\n                    be applied.\n                    ')))}

    def get_multiplier(self, participant_resolver):
        multiplier = self.base_value
        for multiplier_data in self.multipliers:
            while multiplier_data.tests.run_tests(participant_resolver):
                multiplier *= multiplier_data.multiplier
        return multiplier

class TunableStatisticModifierCurve(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'TunableStatisticModifierCurve'

    @TunableFactory.factory_option
    def axis_name_overrides(x_axis_name=None, y_axis_name=None):
        return {'multiplier': TunableVariant(description='\n                Define how the multiplier will be applied.\n                ', value_curve=TunableCurve(description='\n                    The multiplier will be determined by interpolating against a\n                    curve. The user-value is used. This means that a curve for\n                    skills should have levels as its x-axis.\n                    ', x_axis_name=x_axis_name, y_axis_name=y_axis_name), locked_args={'raw_value': None}, default='raw_value')}

    FACTORY_TUNABLES = {'statistic': TunableReference(description="\n            The payout amount will be multiplied by this statistic's value.\n            ", manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)), 'subject': TunableEnumEntry(description='\n            The participant to look for the specified statistic on.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'multiplier': TunableVariant(description='\n            Define how the multiplier will be applied.\n            ', value_curve=TunableCurve(description='\n                The multiplier will be determined by interpolating against a\n                curve. The user-value is used. This means that a curve for\n                skills should have levels as its x-axis.\n                '), locked_args={'raw_value': None}, default='raw_value')}

    def get_multiplier(self, resolver, sim):
        subject = resolver.get_participant(participant_type=self.subject, sim=sim)
        if subject is not None:
            stat = subject.get_stat_instance(self.statistic)
            if stat is not None:
                value = stat.convert_to_user_value(stat.get_value())
                if self.multiplier is not None:
                    return self.multiplier.get(value)
                return value
        return 1.0

