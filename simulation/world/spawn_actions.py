from interactions.context import InteractionContext, InteractionSource
from interactions.priority import Priority
from sims4.tuning.tunable import AutoFactoryInit, HasTunableSingletonFactory, TunableVariant, TunableReference
import services

class SpawnActionFadeIn:
    __qualname__ = 'SpawnActionFadeIn'

    def __call__(self, sim):
        sim.fade_in()
        return True

class SpawnActionAffordance(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'SpawnActionAffordance'
    FACTORY_TUNABLES = {'spawn_affordance': TunableReference(description='\n            The affordance that is pushed on the Sim as soon as they are spawned\n            on the lot.\n            ', manager=services.affordance_manager(), class_restrictions=('SuperInteraction',))}

    def __call__(self, sim):
        context = InteractionContext(sim, InteractionSource.SCRIPT, Priority.Critical)
        return sim.push_super_affordance(self.spawn_affordance, None, context)

class TunableSpawnActionVariant(TunableVariant):
    __qualname__ = 'TunableSpawnActionVariant'

    def __init__(self, **kwargs):
        super().__init__(affordance=SpawnActionAffordance.TunableFactory(), locked_args={'fade_in': SpawnActionFadeIn()}, default='fade_in', **kwargs)

