from event_testing.tests import TunableTestSet
from sims4.tuning.tunable import AutoFactoryInit, HasTunableSingletonFactory, TunablePercent, TunableList, TunableTuple, TunableRange

class SuccessChance(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'SuccessChance'
    FACTORY_TUNABLES = {'base_chance': TunablePercent(description='\n            The basic chance of success.\n            ', default=100), 'multipliers': TunableList(description='\n            A list of multipliers to apply to base_chance.\n            ', tunable=TunableTuple(multiplier=TunableRange(description='\n                    The multiplier to apply to base_chance if the associated\n                    tests pass.\n                    ', tunable_type=float, default=1, minimum=0), tests=TunableTestSet(description='\n                    A series of tests that must pass in order for multiplier to\n                    be applied.\n                    ')))}

    def get_chance(self, participant_resolver):
        chance = self.base_chance
        for multiplier_data in self.multipliers:
            while multiplier_data.tests.run_tests(participant_resolver):
                chance *= multiplier_data.multiplier
        return min(chance, 1)

