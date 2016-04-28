from protocolbuffers import Consts_pb2
from event_testing.resolver import SingleSimResolver
from event_testing.tests import TunableTestSet
from interactions.utils.display_name import HasDisplayTextMixin
from objects import ALL_HIDDEN_REASONS
from objects.system import create_object
from sims4 import random
from sims4.localization import TunableLocalizedString, LocalizationHelperTuning
from sims4.resources import Types
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import HasTunableReference, TunableList, TunableVariant, TunableReference, Tunable, TunableTuple, HasTunableSingletonFactory, TunableResourceKey, TunableCasPart, OptionalTunable, TunableMagazineCollection
from sims4.tuning.tunable_base import ExportModes
from ui.ui_dialog_notification import TunableUiDialogNotificationSnippet
import build_buy
import services
import sims4.resources
logger = sims4.log.Logger('Rewards')

class TunableRewardBase(HasTunableSingletonFactory, HasDisplayTextMixin):
    __qualname__ = 'TunableRewardBase'

    def open_reward(self, sim_info, is_household):
        raise NotImplementedError

    def valid_reward(self, sim_info):
        return True

class TunableRewardObject(TunableRewardBase):
    __qualname__ = 'TunableRewardObject'
    FACTORY_TUNABLES = {'definition': TunableReference(description='\n            Give an object as a reward.\n            ', manager=services.definition_manager())}

    def __init__(self, *args, definition, **kwargs):
        super().__init__(*args, **kwargs)
        self._definition = definition

    def open_reward(self, sim_info, is_household):
        obj = create_object(self._definition)
        if obj is None:
            logger.error('Trying to give an object reward to a Sim, {}, and the object created was None. Definition: {}'.format(sim_info, self._definition), owner='trevorlindsey')
            return
        if not is_household:
            sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            if sim is None:
                logger.warn("Trying to give a sim an object, but the sim isn't instantiated. Adding object to household inventory instead", owner='trevorlindsey')
            elif sim.inventory_component.player_try_add_object(obj):
                obj.update_ownership(sim_info)
                return
        obj.update_ownership(sim_info, make_sim_owner=False)
        obj.set_post_bb_fixup_needed()
        build_buy.move_object_to_household_inventory(obj)

    def _get_display_text(self):
        return LocalizationHelperTuning.get_object_name(self._definition)

class TunableRewardCASPart(TunableRewardBase):
    __qualname__ = 'TunableRewardCASPart'
    FACTORY_TUNABLES = {'cas_part': TunableCasPart(description='\n            The cas part for this reward.\n            ')}

    def __init__(self, *args, cas_part, **kwargs):
        super().__init__(*args, **kwargs)
        self._cas_part = cas_part

    def open_reward(self, sim_info, _):
        household = sim_info.household
        household.add_cas_part_to_reward_inventory(self._cas_part)

    def valid_reward(self, sim_info):
        return not sim_info.household.part_in_reward_inventory(self._cas_part)

class TunableRewardMoney(TunableRewardBase):
    __qualname__ = 'TunableRewardMoney'
    FACTORY_TUNABLES = {'money': Tunable(description='\n            Give money to a sim/household.\n            ', tunable_type=int, default=10)}

    def __init__(self, *args, money, **kwargs):
        super().__init__(*args, **kwargs)
        self._money = money

    def open_reward(self, sim_info, _):
        household = services.household_manager().get(sim_info.household_id)
        if household is not None:
            household.funds.add(self._money, Consts_pb2.TELEMETRY_MONEY_ASPIRATION_REWARD, sim_info.get_sim_instance())

    def _get_display_text(self):
        return LocalizationHelperTuning.get_money(self._money)

class TunableRewardTrait(TunableRewardBase):
    __qualname__ = 'TunableRewardTrait'
    FACTORY_TUNABLES = {'trait': TunableReference(description='\n            Give a trait as a reward\n            ', manager=services.get_instance_manager(sims4.resources.Types.TRAIT))}

    def __init__(self, *args, trait, **kwargs):
        super().__init__(*args, **kwargs)
        self._trait = trait

    def open_reward(self, sim_info, is_household):
        if is_household:
            household = sim_info.household
            for sim in household.sim_info_gen():
                sim.trait_tracker.add_trait(self._trait)
        else:
            sim_info.trait_tracker.add_trait(self._trait)

    def valid_reward(self, sim_info):
        return not sim_info.trait_tracker.is_conflicting(self._trait) and (not sim_info.trait_tracker.has_trait(self._trait) and self._trait.test_sim_info(sim_info))

class TunableRewardBuildBuyUnlockBase(TunableRewardBase):
    __qualname__ = 'TunableRewardBuildBuyUnlockBase'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = None
        self.type = Types.INVALID

    def get_resource_key(self):
        return NotImplementedError

    def open_reward(self, sim_info, is_household):
        key = self.get_resource_key()
        if key is not None:
            sim_info.add_build_buy_unlock(key)
            sim_info.household.add_build_buy_unlock(key)
        else:
            logger.warn('Invalid Build Buy unlock tuned. No reward given.')

class TunableBuildBuyObjectDefinitionUnlock(TunableRewardBuildBuyUnlockBase):
    __qualname__ = 'TunableBuildBuyObjectDefinitionUnlock'
    FACTORY_TUNABLES = {'object_definition': TunableReference(description='\n            Unlock an object to purchase in build/buy.\n            ', manager=services.definition_manager())}

    def __init__(self, *args, object_definition, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = object_definition
        self.type = Types.OBJCATALOG

    def get_resource_key(self):
        if self.instance is not None:
            return sims4.resources.Key(self.type, self.instance.id)
        return

class TunableBuildBuyMagazineCollectionUnlock(TunableRewardBuildBuyUnlockBase):
    __qualname__ = 'TunableBuildBuyMagazineCollectionUnlock'
    FACTORY_TUNABLES = {'magazine_collection': TunableMagazineCollection(description='\n            Unlock a magazine room to purchase in build/buy.\n            ')}

    def __init__(self, *args, magazine_collection, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = magazine_collection
        self.type = Types.MAGAZINECOLLECTION

    def get_resource_key(self):
        if self.instance is not None:
            return sims4.resources.Key(self.type, self.instance)
        return

class TunableRewardDisplayText(TunableRewardBase):
    __qualname__ = 'TunableRewardDisplayText'

    def open_reward(self, sim_info, is_household):
        return True

class TunableSpecificReward(TunableVariant):
    __qualname__ = 'TunableSpecificReward'

    def __init__(self, description='A single specific reward.', **kwargs):
        super().__init__(money=TunableRewardMoney.TunableFactory(), object_definition=TunableRewardObject.TunableFactory(), trait=TunableRewardTrait.TunableFactory(), cas_part=TunableRewardCASPart.TunableFactory(), build_buy_object=TunableBuildBuyObjectDefinitionUnlock.TunableFactory(), build_buy_magazine_collection=TunableBuildBuyMagazineCollectionUnlock.TunableFactory(), display_text=TunableRewardDisplayText.TunableFactory(), description=description, **kwargs)

class TunableRandomReward(TunableTuple):
    __qualname__ = 'TunableRandomReward'

    def __init__(self, description='A list of specific rewards and a weight.', **kwargs):
        super().__init__(reward=TunableSpecificReward(), weight=Tunable(tunable_type=float, default=1), description=description)

class Reward(HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.REWARD)):
    __qualname__ = 'Reward'
    INSTANCE_SUBCLASSES_ONLY = True
    INSTANCE_TUNABLES = {'name': TunableLocalizedString(description='\n            The display name for this reward.\n            ', export_modes=ExportModes.All), 'reward_description': TunableLocalizedString(description='\n            Description for this reward.\n            ', export_modes=ExportModes.All), 'icon': TunableResourceKey(description='\n            The icon image for this reward.\n            ', default='PNG:missing_image', resource_types=sims4.resources.CompoundTypes.IMAGE, export_modes=ExportModes.All), 'tests': TunableTestSet(description='\n            A series of tests that must pass in order for reward to be available.\n            '), 'rewards': TunableList(TunableVariant(description='\n                The gifts that will be given for this reward. They can be either\n                a specific reward or a random reward, in the form of a list of\n                specific rewards.\n                ', specific_reward=TunableSpecificReward(), random_reward=TunableList(TunableRandomReward()))), 'notification': OptionalTunable(description='\n            If enabled, this notification will show when the sim/household receives this reward.\n            ', tunable=TunableUiDialogNotificationSnippet())}

    @classmethod
    def give_reward(cls, sim_info):
        raise NotImplementedError

    @classmethod
    def try_show_notification(cls, sim_info):
        if cls.notification is not None:
            dialog = cls.notification(sim_info, SingleSimResolver(sim_info))
            dialog.show_dialog()

    @classmethod
    def is_valid(cls, sim_info):
        if not cls.tests.run_tests(SingleSimResolver(sim_info)):
            return False
        for reward in cls.rewards:
            if not isinstance(reward, tuple):
                return reward.valid_reward(sim_info)
            for each_reward in reward:
                while not each_reward.reward.valid_reward(sim_info):
                    return False
            return True

class SimReward(Reward):
    __qualname__ = 'SimReward'

    @classmethod
    def give_reward(cls, sim_info):
        return _give_reward_payout(cls, sim_info, False)

class HouseholdReward(Reward):
    __qualname__ = 'HouseholdReward'

    @classmethod
    def give_reward(cls, sim_info):
        return _give_reward_payout(cls, sim_info, True)

def _give_reward_payout(reward_instance, sim_info, is_household_reward):
    payout = []
    chosen_reward = None
    for reward in reward_instance.rewards:
        if not isinstance(reward, TunableRewardBase):
            weighted_rewards = [(random_reward.weight, random_reward.reward) for random_reward in reward]
            chosen_reward = random.weighted_random_item(weighted_rewards)
        else:
            chosen_reward = reward
        chosen_reward.open_reward(sim_info, is_household_reward)
        payout.append(chosen_reward)
    if payout:
        reward_instance.try_show_notification(sim_info)
    return payout

