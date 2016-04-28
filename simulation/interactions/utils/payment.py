from protocolbuffers import Consts_pb2
from event_testing.resolver import SingleSimResolver
from interactions.interaction_finisher import FinishingType
from interactions.liability import Liability
from interactions.utils.interaction_elements import XevtTriggeredElement
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.tunable import TunableVariant, Tunable, HasTunableFactory
from singletons import DEFAULT
from tunable_multiplier import TunableMultiplier
import sims4.log
logger = sims4.log.Logger('Payment')

class PaymentLiability(Liability, HasTunableFactory):
    __qualname__ = 'PaymentLiability'
    LIABILITY_TOKEN = 'PaymentLiability'
    FACTORY_TUNABLES = {'description': '\n            A liability cost to run this interaction.  This cost is reserved at\n            the beginning of the interaction and is eventually applied at the\n            end of the last interaction in the line of continuations.\n            \n            To reserve payment and trigger it at the end of one specific\n            interaction or on an xevt use a payment basic extra instead.\n            ', 'cost': Tunable(description='\n                The amount of money it costs to run this interaction.\n                ', tunable_type=int, default=0)}

    def __init__(self, interaction, cost, init_on_add=False, **kwargs):
        self.interaction = interaction
        self.reserved_funds = None
        self.cost = cost
        self._init_on_add = init_on_add

    @classmethod
    def on_affordance_loaded_callback(cls, affordance, liability_tuning):

        def get_simoleon_delta(interaction, target=DEFAULT, context=DEFAULT):
            return -liability_tuning.cost

        affordance.register_simoleon_delta_callback(get_simoleon_delta)

    def on_run(self):
        if not self._init_on_add:
            self._initialize()

    def on_add(self, *args, **kwargs):
        if self._init_on_add:
            self._initialize()

    def _initialize(self):
        if self.reserved_funds is not None:
            return
        amount_to_reserve = self.interaction.get_simoleon_cost()
        if amount_to_reserve <= 0:
            return
        sim = self.interaction.sim
        self.reserved_funds = sim.family_funds.try_remove(amount_to_reserve, Consts_pb2.TELEMETRY_INTERACTION_COST, sim)
        if self.reserved_funds is None:
            self.interaction.cancel(FinishingType.FAILED_TESTS, cancel_reason_msg="Sim's household does not have enough money to perform this interaction.")

    @property
    def should_transfer(self):
        if not self.interaction.is_finishing:
            return True
        return self.interaction.is_finishing_naturally

    def transfer(self, interaction):
        self.interaction = interaction

    def process_bills_payment(self):
        payment_owed = self.interaction.sim.sim_info.household.bills_manager.current_payment_owed
        if payment_owed != self.reserved_funds.amount:
            self.reserved_funds.cancel()
        else:
            self.interaction.sim.sim_info.household.bills_manager.pay_bill()
            self.reserved_funds.apply()
        self.reserved_funds = None

    def release(self, *args, **kwargs):
        if self.reserved_funds is None:
            return
        if self.interaction.is_finishing_naturally:
            if self.cost == PaymentElement.PAY_BILLS:
                self.process_bills_payment()
                return
            self.reserved_funds.apply()
        else:
            self.reserved_funds.cancel()
        self.reserved_funds = None

class PaymentElement(XevtTriggeredElement):
    __qualname__ = 'PaymentElement'
    CANNOT_AFFORD_TOOLTIP = TunableLocalizedStringFactory(description='Tooltip to display when the player cannot afford to run an interaction.')
    PAY_BILLS = -1
    CATALOG_VALUE = -2
    FACTORY_TUNABLES = {'description': '\n            Remove any funds this interaction has reserved, either when an\n            appropriate xevt has been triggered, or on interaction complete.\n        \n            To reserve payment and trigger it at the end of all the continuations\n            of an interaction instead use a payment liability.\n            ', 'cost': TunableVariant(description='Type of payment this element processes.', cost=Tunable(int, 0, description='The amount of money it costs to run this interaction.'), locked_args={'pay_bills': PAY_BILLS, 'target_catalog_value': CATALOG_VALUE}, default='cost'), 'display_only': Tunable(description="\n            A PaymentElement marked as display_only will affect an affordance's\n            display name (by appending the Simoleon cost in parentheses), but\n            will not deduct funds when run.\n            ", tunable_type=bool, default=False), 'cost_modifiers': TunableMultiplier.TunableFactory(description='\n            A tunable list of test sets and associated multipliers to apply to the total cost of this payment.\n            ')}

    def __init__(self, interaction, **kwargs):
        super().__init__(interaction, **kwargs)
        if not self.display_only:
            self.liability = PaymentLiability(interaction, self.cost, init_on_add=True)
            interaction.add_liability(self.liability.LIABILITY_TOKEN, self.liability)

    @classmethod
    def on_affordance_loaded_callback(cls, affordance, payment_element):

        def get_simoleon_delta(interaction, target=DEFAULT, context=DEFAULT):
            payment_owed = 0
            if payment_element.cost == PaymentElement.PAY_BILLS:
                context = interaction.context if context is DEFAULT else context
                payment_owed = context.sim.household.bills_manager.current_payment_owed
                if payment_owed is not None:
                    payment_owed = -payment_owed
            elif payment_element.cost == PaymentElement.CATALOG_VALUE:
                if target is DEFAULT:
                    target = interaction.target
                payment_owed = -target.definition.price
            else:
                payment_owed = -payment_element.cost
            if payment_owed == 0:
                return payment_owed
            context = interaction.context if context is DEFAULT else context
            return payment_owed*payment_element.cost_modifiers.get_multiplier(SingleSimResolver(context.sim.sim_info))

        affordance.register_simoleon_delta_callback(get_simoleon_delta)

    def _do_behavior(self):
        if self.display_only:
            return
        if self.liability.reserved_funds is not None:
            if self.cost == PaymentElement.PAY_BILLS:
                self.liability.process_bills_payment()
            else:
                self.liability.reserved_funds.apply()
                self.liability.reserved_funds = None

