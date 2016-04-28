from interactions import ParticipantType
from interactions.utils.loot import LootActions
from objects.components import Component, types
from objects.components.state import TunableStateTypeReference
from sims4.tuning.tunable import Tunable, TunableTuple, TunableList, TunableReference, TunableRange, TunableEnumEntry, TunableVariant, HasTunableFactory
from statistics.statistic_ops import StatisticChangeOp, StatisticAddRelationship, StatisticOperation, RelationshipOperation
import enum
import services
import sims4.log
logger = sims4.log.Logger('ConsumableComponent')

class ConsumptionEffects(enum.Int):
    __qualname__ = 'ConsumptionEffects'
    NO_EFFECT = 0
    CALORIE_LOSS = 1
    CALORIE_GAIN = 2

debug_consumables_are_infinite = False

class ConsumableComponent(Component, HasTunableFactory, component_name=types.CONSUMABLE_COMPONENT):
    __qualname__ = 'ConsumableComponent'
    manager = services.get_instance_manager(sims4.resources.Types.STATISTIC)
    CALORIES_PER_POUND = Tunable(int, 3500, description='Number of calories in 1 pound of fat.')
    SIM_WEIGHT_RANGE = Tunable(int, 100, description='The difference in pounds between Sims with empty and full fat commodities.')
    FAT_COMMODITY = TunableReference(manager, description="A reference to the Sim's fat commodity.")
    FIT_COMMODITY = TunableReference(manager, description="A reference to the Sim's fit commodity.")
    CONSUMABLE_COMMODITY = TunableReference(manager, description="A reference to the Object's consumable commodity.")
    FAT_STATE = TunableStateTypeReference(description='The fatness state type.')
    FIT_STATE = TunableStateTypeReference(description='The fit state type.')

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, consume_affordance=None, **tuned_values):
        if consume_affordance is None:
            logger.error('{} has consumable component but has no consume affordance tuned', instance_class)

    FACTORY_TUNABLES = {'description': 'Manage statistic changes for consumable objects.', 'consumption_turns': TunableRange(description='\n            An integer value specifying the number of turns it\n            would take a Sim to completely consume this\n            object.\n            ', tunable_type=int, default=10, minimum=1), 'consumption_statistics': TunableList(description="\n            Statistic changes whose values represent the values that the\n            complete consumption of this object would provide.  \n            \n            e.g. A statistic change of 50 for the hunger commodity will\n            fill a Sim's hunger commodity by 25 if they consume half of\n            this object, and by 50 if they consume all of it.\n            \n            The following commodities will have statistic changes\n            automatically generated based on other information and do not\n            need to be added explicitly:\n            \n             * Fat commodity\n             * Fit commodity\n             * Consumable commodity\n            ", tunable=TunableVariant(statistic_change=StatisticChangeOp.TunableFactory(**StatisticOperation.DEFAULT_PARTICIPANT_ARGUMENTS), relationship_change=StatisticAddRelationship.TunableFactory(**RelationshipOperation.DEFAULT_PARTICIPANT_ARGUMENTS))), 'fitness_info': TunableTuple(description='\n            A list of tunables that affect Sim fitness.\n            ', calories=Tunable(description='\n                The number of calories contained in this consumable.  \n                \n                If this object is marked as having a consumption effect,\n                this value will be used to generate appropriate fat gains\n                or losses for the Sim consuming this object.\n                ', tunable_type=int, default=500), consumption_effect=TunableEnumEntry(description='\n                The effect that consuming this object will have on the Sim.\n                ', tunable_type=ConsumptionEffects, needs_tuning=True, default=ConsumptionEffects.NO_EFFECT)), 'consume_affordance': TunableReference(description="\n            The affordance that interfaces with this component and consumes the\n            owning object.  This affordance will be dynamically added to the\n            owning object's super affordance list at runtime.\n            ", manager=services.affordance_manager(), class_restrictions=('SuperInteraction',)), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, owner, consumption_turns, consumption_statistics, fitness_info, consume_affordance, **kwargs):
        super().__init__(owner)
        self.owner = owner
        self.consumption_turns = consumption_turns
        self.consumption_statistics = list(consumption_statistics)
        self.fitness_info = fitness_info
        self.consume_affordance = consume_affordance
        self.commodity_range = self.FAT_COMMODITY.max_value_tuning - self.FAT_COMMODITY.min_value_tuning
        self.calorie_modifier = self.CALORIES_PER_POUND*self.SIM_WEIGHT_RANGE/self.commodity_range
        self._loot_list = None

    @property
    def loot_list(self):
        if self._loot_list is None:
            self._derive_consumption_operations()
        return self._loot_list

    def component_super_affordances_gen(self, **kwargs):
        if self.consume_affordance is not None:
            yield self.consume_affordance

    def _derive_consumption_operations(self):
        new_statistics = []
        for stat in self.consumption_statistics:
            amount = stat._amount/self.consumption_turns
            stat_change = StatisticChangeOp(amount=amount, stat=stat._stat, subject=stat._subject, tests=stat._tests)
            new_statistics.append(stat_change)
        if self.fitness_info.consumption_effect != ConsumptionEffects.NO_EFFECT:
            if self.fitness_info.consumption_effect == ConsumptionEffects.CALORIE_GAIN:
                amount = self.fitness_info.calories
            else:
                amount = -self.fitness_info.calories
            amount = amount/self.calorie_modifier
            amount /= self.consumption_turns
            stat_change = StatisticChangeOp(amount=amount, stat=self.FAT_COMMODITY, subject=ParticipantType.Actor)
            new_statistics.append(stat_change)
        if not debug_consumables_are_infinite:
            commodity_range = self.CONSUMABLE_COMMODITY.max_value_tuning - self.CONSUMABLE_COMMODITY.min_value_tuning
            amount = commodity_range/self.consumption_turns
            stat_change = StatisticChangeOp(amount=-amount, stat=self.CONSUMABLE_COMMODITY, subject=ParticipantType.Object)
            new_statistics.append(stat_change)
        loot_actions = LootActions(run_test_first=False, loot_actions=new_statistics)
        self._loot_list = [loot_actions]

    def bites_left(self):
        commodity_range = self.CONSUMABLE_COMMODITY.max_value_tuning - self.CONSUMABLE_COMMODITY.min_value_tuning
        amount_per_turn = commodity_range/self.consumption_turns
        current_value = self.owner.commodity_tracker.get_value(self.CONSUMABLE_COMMODITY)
        bites_left = current_value/amount_per_turn
        return bites_left

