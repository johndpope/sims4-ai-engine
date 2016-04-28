import services
from sims4.resources import Types
from sims4.tuning.tunable import TunableMapping, Tunable, TunableInterval, TunableReference, AutoFactoryInit, HasTunableSingletonFactory
from sims4.tuning.tunable_base import SourceQueries

class TunableStatAsmParam(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'TunableStatAsmParam'
    FACTORY_TUNABLES = {'description': '\n            A tunable factory use the stat_value to decide tuple(asm_param_name, \n            asm_param_value) to set on the asm.\n            ', 'level_ranges': TunableMapping(description='\n            The value mapping of the stat range to stat value or user value. \n            If use_user_value is True, the range should be user value, \n            otherwise stat value.\n            ', key_type=Tunable(description="The asm parameter for Sim's \n                 stat level.\n                 ", tunable_type=str, default=None, source_query=SourceQueries.SwingEnumNamePattern.format('statLevel')), value_type=TunableInterval(description='\n                Stat value fall into the range (inclusive).\n                ', tunable_type=float, default_lower=1, default_upper=1)), 'asm_param_name': Tunable(description='\n            The asm param name.\n            ', tunable_type=str, default='statLevel'), 'use_user_value': Tunable(description='\n            Whether use the user value or stat value to decide the asm_param.\n            ', tunable_type=bool, default=True), 'use_effective_skill_level': Tunable(description='\n            If true, the effective skill level of the Sim will be used for \n            the asm_param.\n            ', tunable_type=bool, default=True)}

    def get_asm_param(self, stat):
        stat_value = stat.get_user_value() if self.use_user_value else self.stat.get_value()
        if stat.is_skill and self.use_effective_skill_level:
            stat_value = stat.tracker.owner.get_effective_skill_level(stat)
        asm_param_value = None
        for (range_key, stat_range) in self.level_ranges.items():
            while stat_value >= stat_range.lower_bound and stat_value <= stat_range.upper_bound:
                asm_param_value = range_key
                break
        return (self.asm_param_name, asm_param_value)

class CommodityDecayModifierMapping(TunableMapping):
    __qualname__ = 'CommodityDecayModifierMapping'

    def __init__(self, description=''):
        import statistics.commodity
        (super().__init__(description=description, key_type=TunableReference(services.statistic_manager(), class_restrictions=(statistics.commodity.Commodity,), description='\n                    The stat the modifier will apply to.\n                    '), value_type=Tunable(float, 0, description='Multiply statistic decay by this value.')),)

    @property
    def export_class(self):
        return 'TunableMapping'

class CommodityTuning:
    __qualname__ = 'CommodityTuning'
    BLADDER_SOLVING_FAILURE_INTERACTION = TunableReference(manager=services.get_instance_manager(Types.INTERACTION), class_restrictions='SuperInteraction', description='\n                     Interaction run to notify the player that the bladder motive cannot be autonomously solved.\n                     ')
    HUNGER_SOLVING_FAILURE_INTERACTION = TunableReference(manager=services.get_instance_manager(Types.INTERACTION), class_restrictions='SuperInteraction', description='\n                     Interaction run to notify the player that the hunger motive cannot be autonomously solved.\n                     ')
    ENERGY_SOLVING_FAILURE_INTERACTION = TunableReference(manager=services.get_instance_manager(Types.INTERACTION), class_restrictions='SuperInteraction', description='\n                     Interaction run to notify the player that the energy motive cannot be autonomously solved.\n                     ')
    FUN_SOLVING_FAILURE_INTERACTION = TunableReference(manager=services.get_instance_manager(Types.INTERACTION), class_restrictions='SuperInteraction', description='\n                     Interaction run to notify the player that the fun motive cannot be autonomously solved.\n                     ')
    SOCIAL_SOLVING_FAILURE_INTERACTION = TunableReference(manager=services.get_instance_manager(Types.INTERACTION), class_restrictions='SuperInteraction', description='\n                     Interaction run to notify the player that the social motive cannot be autonomously solved.\n                     ')
    HYGIENE_SOLVING_FAILURE_INTERACTION = TunableReference(manager=services.get_instance_manager(Types.INTERACTION), class_restrictions='SuperInteraction', description='\n                     Interaction run to notify the player that the hygiene motive cannot be autonomously solved.\n                     ')

