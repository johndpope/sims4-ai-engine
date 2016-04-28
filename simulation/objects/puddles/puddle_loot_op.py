from interactions.utils.loot_basic_op import BaseTargetedLootOperation
from objects.puddles import PuddleSize, create_puddle, PuddleLiquid
from sims4.tuning.tunable import TunableEnumEntry, TunableList, TunableTuple, TunableRange, TunableReference, Tunable
import services
import sims4.log
logger = sims4.log.Logger('Puddles')

class TunablePuddleFactory(TunableTuple):
    __qualname__ = 'TunablePuddleFactory'

    def __init__(self, **kwargs):
        super().__init__(none=TunableRange(int, 5, minimum=0, description='Relative chance of no puddle.'), small=TunableRange(int, 5, minimum=0, description='Relative chance of small puddle.'), medium=TunableRange(int, 0, minimum=0, description='Relative chance of medium puddle.'), large=TunableRange(int, 0, minimum=0, description='Relative chance of large puddle.'), liquid=TunableEnumEntry(description='\n                The liquid of the puddle that will be generated.\n                ', tunable_type=PuddleLiquid, default=PuddleLiquid.WATER), **kwargs)

class CreatePuddlesLootOp(BaseTargetedLootOperation):
    __qualname__ = 'CreatePuddlesLootOp'
    FACTORY_TUNABLES = {'description': '\n            This loot will create puddles based on a tuned set of chances.\n            ', 'trait_puddle_factory': TunableList(TunableTuple(trait=TunableReference(manager=services.trait_manager()), puddle_factory=TunablePuddleFactory(description='\n                The chance of creating a puddle of various sizes.\n                '))), 'default_puddle_factory': TunablePuddleFactory(description='\n            This set of chances will be used if the sim creating the puddle does\n            not match any of the traits in the trait_puddle_chances tuning list.\n            '), 'max_distance': Tunable(description='\n                Maximum distance from the source object a puddle can be spawned.\n                If no position is found within this distance no puddle will be \n                made.\n                ', tunable_type=float, default=2.5)}

    def __init__(self, trait_puddle_factory, default_puddle_factory, max_distance, **kwargs):
        super().__init__(**kwargs)
        self.trait_puddle_factory = trait_puddle_factory
        self.default_puddle_factory = default_puddle_factory
        self.max_distance = max_distance

    def _apply_to_subject_and_target(self, subject, target, resolver):
        puddle_factory = self.default_puddle_factory
        trait_tracker = subject.trait_tracker
        for item in self.trait_puddle_factory:
            while trait_tracker.has_trait(item.trait):
                puddle_factory = item.puddle_factory
                break
        puddle = self.create_puddle_from_factory(puddle_factory)
        if puddle is not None:
            target_obj = target.get_sim_instance() if target.is_sim else target
            puddle.place_puddle(target_obj, self.max_distance)

    def create_puddle_from_factory(self, puddle_factory):
        value = sims4.random.weighted_random_item([(puddle_factory.none, PuddleSize.NoPuddle), (puddle_factory.small, PuddleSize.SmallPuddle), (puddle_factory.medium, PuddleSize.MediumPuddle), (puddle_factory.large, PuddleSize.LargePuddle)])
        return create_puddle(value, puddle_factory.liquid)

