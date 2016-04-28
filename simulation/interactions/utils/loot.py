from buffs.buff_ops import DynamicBuffLootOp
from careers.career_ops import CareerLevelOp, CareerLootOp
from interactions import ParticipantType
from interactions.inventory_loot import InventoryLoot
from interactions.money_payout import MoneyChange
from interactions.object_rewards import ObjectRewardsOperation
from interactions.utils import LootType
from interactions.utils.loot_ops import LifeExtensionLootOp, StateChangeLootOp, AddTraitLootOp, RemoveTraitLootOp, HouseholdFundsInterestLootOp, FireLootOp, UnlockLootOp, NotificationLootOp, FireDeactivateSprinklerLootOp, FireCleanScorchLootOp, ExtinguishNearbyFireLootOp, AwardWhimBucksLootOp
from objects.components import game_component
from objects.components.object_relationship_component import ObjectRelationshipLootOp
from objects.components.ownable_component import TransferOwnershipLootOp
from objects.puddles.puddle_loot_op import CreatePuddlesLootOp
from relationships.relationship_bit_change import RelationshipBitChange, KnowOtherSimTraitOp
from sims4.sim_irq_service import yield_to_irq
from sims4.tuning.instances import TunedInstanceMetaclass, HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableList, Tunable, TunableVariant, HasTunableReference, HasTunableSingletonFactory, AutoFactoryInit, TunableTuple, TunableReference
from sims4.utils import classproperty, flexmethod
from statistics.statistic_ops import TunableStatisticChange, SkillEffectivenessLoot, DynamicSkillLootOp, NormalizeStatisticsOp
from topics.tunable import TopicUpdate
import assertions
import buffs.buff_ops
import services
import sims.gender_preference
import sims4.log
import sims4.resources
logger = sims4.log.Logger('Interactions')

class LootOperationList:
    __qualname__ = 'LootOperationList'
    DEFAULT_LOOT_OFFSET = Tunable(description='\n        The amount of time, in real seconds, from the start of the response\n        animation to wait before applying the loot operation. Negative values\n        will be offset from the end of the animation. If no response animation\n        exists, loot will fire immediately.\n        ', tunable_type=float, default=0)

    def __init__(self, interaction, loot_list):
        self._interaction = interaction
        self._loot_actions = tuple(loot_list)

    def apply_operations(self):
        resolver = self._interaction.get_resolver()
        for loot_action in self._loot_actions:
            yield_to_irq()
            loot_action.apply_to_resolver(resolver)

def create_loot_list(interaction, loot_list):
    loot_list = LootOperationList(interaction, loot_list)
    return loot_list

class LootActions(HasTunableReference, HasTunableSingletonFactory, AutoFactoryInit, metaclass=TunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.ACTION)):
    __qualname__ = 'LootActions'
    INSTANCE_TUNABLES = {'run_test_first': Tunable(description='\n           If left unchecked, iterate over the actions and if its test succeeds\n           apply the action at that moment.\n           \n           If checked, run through all the loot actions and collect all actions\n           that passes their test.  Then apply all the actions that succeeded.\n           ', tunable_type=bool, default=False, needs_tuning=True), 'loot_actions': TunableList(tunable=TunableVariant(actions=TunableReference(description='\n                    Apply a set of loot operations.\n                    ', manager=services.get_instance_manager(sims4.resources.Types.ACTION), class_restrictions='LootActions'), statistics=TunableStatisticChange(), relationship_bits_loot=RelationshipBitChange.TunableFactory(description='A list of relationship bit operations to perform'), money_loot=MoneyChange.TunableFactory(), topic_loot=TopicUpdate.TunableFactory(target_participant_type_options={'optional': True}), buff=buffs.buff_ops.BuffOp.TunableFactory(), buff_removal=buffs.buff_ops.BuffRemovalOp.TunableFactory(), buff_transfer=buffs.buff_ops.BuffTransferOp.TunableFactory(target_participant_type_options={'description': '\n                        The Sim from which to transfer buffs from.\n                        ', 'default_participant': ParticipantType.Actor}), normalize_stat=NormalizeStatisticsOp.TunableFactory(target_participant_type_options={'description': '\n                        The Sim from which to transfer the listed stats from.\n                        ', 'default_participant': ParticipantType.Actor}), skill_effectiveness=SkillEffectivenessLoot.TunableFactory(), take_turn=game_component.TakeTurn.TunableFactory(), team_score=game_component.TeamScore.TunableFactory(), game_over=game_component.GameOver.TunableFactory(), reset_game=game_component.ResetGame.TunableFactory(), setup_game=game_component.SetupGame.TunableFactory(), dynamic_skill_loot=DynamicSkillLootOp.TunableFactory(locked_args={'exclusive_to_owning_si': False}), fix_gender_preference=sims.gender_preference.GenderPreferenceOp.TunableFactory(), inventory_loot=InventoryLoot.TunableFactory(subject_participant_type_options={'description': '\n                         The participant type who has the inventory that the\n                         object goes into during this loot.\n                         ', 'optional': True}, target_participant_type_options={'description': '\n                        The participant type of the object which would get to\n                        switch inventory in the loot\n                        ', 'default_participant': ParticipantType.CarriedObject}), dynamic_buff_loot=DynamicBuffLootOp.TunableFactory(), object_rewards=ObjectRewardsOperation.TunableFactory(), transfer_ownership=TransferOwnershipLootOp.TunableFactory(), create_puddles=CreatePuddlesLootOp.TunableFactory(target_participant_type_options={'description': '\n                        The participant of the interaction whom the puddle\n                        should be placed near.\n                        ', 'default_participant': ParticipantType.Object}), life_extension=LifeExtensionLootOp.TunableFactory(), notification=NotificationLootOp.TunableFactory(), state_change=StateChangeLootOp.TunableFactory(), trait_add=AddTraitLootOp.TunableFactory(), trait_remove=RemoveTraitLootOp.TunableFactory(), know_other_sims_trait=KnowOtherSimTraitOp.TunableFactory(target_participant_type_options={'description': '\n                        The Sim or Sims whose information the subject Sim is learning.\n                        ', 'default_participant': ParticipantType.TargetSim}), object_relationship=ObjectRelationshipLootOp.TunableFactory(target_participant_type_options={'description': '\n                        The object whose relationship to modify.\n                        ', 'default_participant': ParticipantType.Object}), interest_income=HouseholdFundsInterestLootOp.TunableFactory(), career_level=CareerLevelOp.TunableFactory(), career_loot=CareerLootOp.TunableFactory(), fire=FireLootOp.TunableFactory(), unlock_item=UnlockLootOp.TunableFactory(), fire_deactivate_sprinkler=FireDeactivateSprinklerLootOp.TunableFactory(), fire_clean_scorch=FireCleanScorchLootOp.TunableFactory(), extinguish_nearby_fire=ExtinguishNearbyFireLootOp.TunableFactory(), award_whim_bucks=AwardWhimBucksLootOp.TunableFactory()))}
    FACTORY_TUNABLES = INSTANCE_TUNABLES
    _simoleon_loot = None

    @classmethod
    def _tuning_loaded_callback(cls):
        cls._simoleon_loot = None
        for action in cls.loot_actions:
            while hasattr(action, 'get_simoleon_delta'):
                if cls._simoleon_loot is None:
                    cls._simoleon_loot = []
                cls._simoleon_loot.append(action)

    @classmethod
    def _verify_tuning_callback(cls):
        cls._validate_recursion()

    @classmethod
    @assertions.not_recursive
    def _validate_recursion(cls):
        for action in cls.loot_actions:
            while action.loot_type == LootType.ACTIONS:
                try:
                    action._validate_recursion()
                except:
                    logger.error('{} is an action in {} but that creates a circular dependency', action, cls, owner='epanero')

    @classproperty
    def loot_type(self):
        return LootType.ACTIONS

    @classmethod
    def get_simoleon_delta(cls, *args, **kwargs):
        if cls._simoleon_loot is not None:
            return sum(action.get_simoleon_delta(*args, **kwargs) for action in cls._simoleon_loot)
        return 0

    @flexmethod
    def get_loot_ops_gen(cls, inst, resolver=None):
        inst_or_cls = inst if inst is not None else cls
        if resolver is None or not inst_or_cls.run_test_first:
            for action in inst_or_cls.loot_actions:
                if action.loot_type == LootType.ACTIONS:
                    yield action.get_loot_ops_gen(resolver=resolver)
                else:
                    yield (action, False)
        else:
            actions_that_can_be_applied = []
            for action in inst_or_cls.loot_actions:
                while action.loot_type == LootType.ACTIONS or action.test_resolver(resolver):
                    actions_that_can_be_applied.append(action)
            for action in actions_that_can_be_applied:
                if action.loot_type == LootType.ACTIONS:
                    yield action.get_loot_ops_gen(resolver=resolver)
                else:
                    yield (action, True)

    @flexmethod
    def apply_to_resolver(cls, inst, resolver, skip_test=False):
        inst_or_cls = inst if inst is not None else cls
        for (action, test_ran) in inst_or_cls.get_loot_ops_gen(resolver):
            try:
                action.apply_to_resolver(resolver, skip_test=test_ran)
            except BaseException as ex:
                logger.error('Exception when applying action {} for loot {}', action, cls)
                raise ex

LootActions.TunableFactory(description='[rez] <Unused>')

class WeightedSingleSimLootActions(HasTunableReference, HasTunableSingletonFactory, AutoFactoryInit, metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.ACTION)):
    __qualname__ = 'WeightedSingleSimLootActions'
    INSTANCE_TUNABLES = {'loot_actions': TunableList(description='\n            A list of weighted Loot Actions that operate only on one Sim.\n            ', tunable=TunableTuple(buff_loot=DynamicBuffLootOp.TunableFactory(), weight=Tunable(description='\n                    Accompanying weight of the loot.\n                    ', tunable_type=int, default=1)))}

    def __iter__(self):
        return iter(self.loot_actions)

    @classmethod
    def pick_loot_op(cls):
        weighted_loots = [(loot.weight, loot.buff_loot) for loot in cls.loot_actions]
        loot_op = sims4.random.weighted_random_item(weighted_loots)
        return loot_op

