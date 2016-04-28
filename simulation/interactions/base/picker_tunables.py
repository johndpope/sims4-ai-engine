from sims4.tuning.tunable import TunableMapping, TunableReference, Tunable
import services
import sims4.resources

class TunableBuffWeightMultipliers(TunableMapping):
    __qualname__ = 'TunableBuffWeightMultipliers'

    def __init__(self, **kwargs):
        super().__init__(description='\n            A mapping of buffs to weight multipliers.  These multiplier will be applied \n            to the autonomy_weight whenever the Sim has that buff.\n            ', key_type=TunableReference(services.get_instance_manager(sims4.resources.Types.BUFF), description='\n                The buff the Sim must have to apply this multiplier.\n                '), value_type=Tunable(description='\n                Float value to apply to the recipe weight.  The final recipe score \n                will be autonomy_weight times the product of all applicable buff \n                weight multipliers.\n                ', tunable_type=float, default=1.0), **kwargs)

