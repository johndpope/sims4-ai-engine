import services
import sims4.tuning.tunable
import snippets
logger = sims4.log.Logger('Fishing', default_owner='TrevorLindsey')

class FishingData(sims4.tuning.tunable.HasTunableSingletonFactory, sims4.tuning.tunable.AutoFactoryInit):
    __qualname__ = 'FishingData'
    FACTORY_TUNABLES = {'weight_fish': sims4.tuning.tunable.Tunable(description='\n            The weight used to determine if the Sim will catch a fish instead of treasure or junk..\n            This will be used in conjunction with the Weight Junk and Weight Treasure.\n            ', tunable_type=float, default=1.0), 'weight_junk': sims4.tuning.tunable.Tunable(description='\n            The weight used to determine if the Sim will catch junk instead of a fish or treasure.\n            This will be used in conjunction with the Weight Fish and Weight Treasure.\n            ', tunable_type=float, default=1.0), 'weight_treasure': sims4.tuning.tunable.Tunable(description='\n            The weight used to determine if the Sim will catch a treasure instead of fish or junk.\n            This will be used in conjunction with the Weight Fish and Weight Junk.\n            ', tunable_type=float, default=1.0), 'possible_treasures': sims4.tuning.tunable.TunableList(description="\n            If the Sim catches a treasure, we'll pick one of these based on their weights.\n            Higher weighted treasures have a higher chance of being caught.\n            ", tunable=sims4.tuning.tunable.TunableTuple(treasure=sims4.tuning.tunable.TunableReference(manager=services.definition_manager()), weight=sims4.tuning.tunable.Tunable(tunable_type=float, default=1.0))), 'possible_fish': sims4.tuning.tunable.TunableList(description="\n            If the Sim catches a fish, we'll pick one of these based on their weights.\n            Higher weighted fish have a higher chance of being caught.\n            ", tunable=sims4.tuning.tunable.TunableTuple(fish=sims4.tuning.tunable.TunableReference(manager=services.definition_manager()), weight=sims4.tuning.tunable.Tunable(tunable_type=float, default=1.0)))}

    def _verify_tuning_callback(self):
        import fishing.fish_object
        if not self.possible_fish:
            logger.error("FishingData has an empty list of Possible Fish. This isn't much of a fishing location if there aren't any fish.\n{}", self)
        else:
            for fish in self.possible_fish:
                while fish.fish is None or not issubclass(fish.fish.cls, fishing.fish_object.Fish):
                    logger.error("Possible Fish on Fishing Data has been tuned but there either isn't a definition tuned for the fish, or the definition currently tuned is not a Fish.\n{}", self)

    def get_possible_fish_gen(self):
        yield self.possible_fish

    def choose_fish(self, resolver):
        weighted_fish = [(f.weight, f.fish) for f in self.possible_fish if f.fish.cls.can_catch(resolver, require_bait=True)]
        if weighted_fish:
            return sims4.random.weighted_random_item(weighted_fish)

    def choose_treasure(self):
        weighted_treasures = [(t.weight, t.treasure) for t in self.possible_treasures]
        if weighted_treasures:
            return sims4.random.weighted_random_item(weighted_treasures)

(_, TunableFishingDataSnippet) = snippets.define_snippet('fishing_data', FishingData.TunableFactory())
