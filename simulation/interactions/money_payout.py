import collections
from interactions.liability import Liability
from interactions.utils.loot_basic_op import BaseLootOperation
from protocolbuffers import Consts_pb2
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.tunable import Tunable, TunableList, TunableLiteralOrRandomValue
from singletons import DEFAULT
from tunable_multiplier import TunableStatisticModifierCurve
import interactions.utils
import sims4
logger = sims4.log.Logger('MoneyPayout')

class MoneyLiability(Liability):
    __qualname__ = 'MoneyLiability'
    LIABILITY_TOKEN = 'MoneyLiability'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.amounts = collections.defaultdict(lambda : 0)

class MoneyChange(BaseLootOperation):
    __qualname__ = 'MoneyChange'
    DISPLAY_TEXT = TunableLocalizedStringFactory(description='\n        A string displaying the Simoleon amount that this loot operation awards.\n        It will be provided one token: the amount of Simoleons awarded.\n        ')

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value._subject == interactions.ParticipantType.Invalid:
            logger.error("{} doesn't have a valid participant type tuned", source)

    FACTORY_TUNABLES = {'amount': TunableLiteralOrRandomValue(description='\n        The amount of Simoleons awarded. The value will be rounded to the\n        closest integer. When two integers are equally close, rounding is done\n        towards the even one (e.g. 0.5 -> 0, 1.5 -> 2).\n        ', tunable_type=float, minimum=0), 'statistic_multipliers': TunableList(description='\n        Tunables for adding statistic based multipliers to the payout in the\n        format:\n        \n        amount *= statistic.value\n        ', tunable=TunableStatisticModifierCurve.TunableFactory()), 'display_to_user': Tunable(description='\n        If true, the amount will be displayed in the interaction name.\n        ', tunable_type=bool, needs_tuning=True, default=True), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, amount, statistic_multipliers, display_to_user, **kwargs):
        super().__init__(**kwargs)
        self._amount = amount
        self._statistic_multipliers = statistic_multipliers
        self._display_to_user = display_to_user
        self._random_amount = None

    @property
    def loot_type(self):
        return interactions.utils.LootType.SIMOLEONS

    def get_simoleon_delta(self, interaction, target=DEFAULT, context=DEFAULT):
        if not self._display_to_user:
            return 0
        if not self._tests.run_tests(interaction.get_resolver(target=target, context=context)):
            return 0
        sim = context.sim if context is not DEFAULT else DEFAULT
        recipients = interaction.get_participants(participant_type=self.subject, sim=sim, target=target)
        skill_multiplier = 1 if context is DEFAULT else interaction.get_skill_multiplier(interaction.monetary_payout_multipliers, context.sim)
        return self.amount*len(recipients)*skill_multiplier

    def _apply_to_subject_and_target(self, subject, target, resolver):
        interaction = resolver.interaction
        if interaction is not None:
            money_liability = interaction.get_liability(MoneyLiability.LIABILITY_TOKEN)
            if money_liability is None:
                money_liability = MoneyLiability()
                interaction.add_liability(MoneyLiability.LIABILITY_TOKEN, money_liability)
            skill_multiplier = interaction.get_skill_multiplier(interaction.monetary_payout_multipliers, interaction.sim)
        else:
            money_liability = None
            skill_multiplier = 1
        subject_obj = self._get_object_from_recipient(subject)
        amount_multiplier = self._get_multiplier(resolver, subject_obj)*skill_multiplier
        amount = round(self.amount*amount_multiplier)
        if amount:
            if money_liability is not None:
                money_liability.amounts[self.subject] += amount
            if interaction is not None:
                interaction_category_tags = interaction.interaction_category_tags
            else:
                interaction_category_tags = None
            subject.household.funds.add(amount, Consts_pb2.TELEMETRY_INTERACTION_REWARD, subject_obj, tags=interaction_category_tags)

    def _on_apply_completed(self):
        self._random_amount = None

    def _get_display_text(self):
        return self.DISPLAY_TEXT(*self._get_display_text_tokens())

    def _get_display_text_tokens(self):
        return (self.amount,)

    def _get_multiplier(self, resolver, sim):
        amount_multiplier = 1
        if self._statistic_multipliers:
            for statistic_multiplier in self._statistic_multipliers:
                amount_multiplier *= statistic_multiplier.get_multiplier(resolver, sim)
        return amount_multiplier

    @property
    def amount(self):
        if self._random_amount is None:
            self._random_amount = self._amount.random_float()
        return self._random_amount

