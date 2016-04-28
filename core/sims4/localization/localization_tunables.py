from sims4.localization import TunableLocalizedStringFactoryVariant
from sims4.tuning.tunable import HasTunableSingletonFactory, AutoFactoryInit, OptionalTunable
import sims4.log
logger = sims4.log.Logger('Localization', default_owner='epanero')

class LocalizedStringHouseholdNameSelector(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'LocalizedStringHouseholdNameSelector'
    FACTORY_TUNABLES = {'empty_household': OptionalTunable(description='\n            When enabled, this string will be used if the provided household\n            does not have any members.\n            ', tunable=TunableLocalizedStringFactoryVariant(description='\n                The string to use if the provided household has no members. This\n                string is provided the same tokens as the original string.\n                ')), 'single_sim': OptionalTunable(description='\n            When enabled, this string will be used if the Sim is the only member\n            of the household. If disabled, this check will be ignored.\n            ', tunable=TunableLocalizedStringFactoryVariant(description='\n                The string to use if the Sim is the only member of the\n                household. The first token is the only Sim of the household. It\n                might differ from the original Sim if the provided household is\n                different. The original Sim is the last token.\n                ')), 'single_family': OptionalTunable(description='\n            When enabled, this string will be used if the Sim is part of a\n            household where all Sims share the same last name. If disabled, this\n            check will be ignored.\n            ', tunable=TunableLocalizedStringFactoryVariant(description='\n                The string to use if all Sims in the household share the same\n                last name. The first token is a string containing the household\n                name. The original Sim is the last token.\n                ')), 'fallback': TunableLocalizedStringFactoryVariant(description='\n            The string to use of no other rule applies. The first token is a\n            string containing the household name.\n            ')}

    def __call__(self, sim, *args, household=None, **kwargs):
        household = household if household is not None else sim.household
        if self.empty_household is not None and len(household) == 0:
            return self.empty_household(sim, *args, **kwargs)
        if self.single_sim is not None and len(household) == 1:
            return self.single_sim(next(iter(household)), *args + (sim,), **kwargs)
        if self.single_family is not None and all(sim_info.last_name == sim.last_name for sim_info in household) and sim.last_name == household.name:
            return self.single_family(sim.last_name, *args + (sim,), **kwargs)
        return self.fallback(household.name, *args + (sim,), **kwargs)

