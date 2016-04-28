from event_testing import test_events
from event_testing.event_data_const import SimoleonData
from protocolbuffers import Consts_pb2
from sims.sim_info import AccountConnection
from sims4.tuning.tunable import TunableRange
import distributor.ops
import services
import sims4.log
import sims4.telemetry
import telemetry_helper
logger = sims4.log.Logger('Family Funds')
TELEMETRY_GROUP_FUNDS = 'FUND'
TELEMETRY_HOOK_POCKET = 'POKT'
TELEMETRY_HOOK_FUNDS_CHANGE = 'FMOD'
TELEMETRY_AMOUNT = 'amnt'
TELEMETRY_REASON = 'resn'
TELEMETRY_FUND_AMOUNT = 'fund'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_FUNDS)

class ReservedFunds:
    __qualname__ = 'ReservedFunds'
    __slots__ = ('_apply_function', '_cancel_function', '_amount')

    def __init__(self, apply_function, cancel_function, amount):
        self._apply_function = apply_function
        self._cancel_function = cancel_function
        self._amount = amount

    def apply(self):
        if self._apply_function:
            self._apply_function()
            self._cancel_function = None
            self._apply_function = None

    def cancel(self, from_gc=False):
        if self._cancel_function:
            if from_gc:
                logger.error('Refund being issued by garbage collection of a ReservedFunds object.', owner='mduke')
            self._cancel_function()
            self._cancel_function = None
            self._apply_function = None

    def __del__(self):
        self.cancel(True)

    @property
    def amount(self):
        return self._amount

class FamilyFunds:
    __qualname__ = 'FamilyFunds'
    __slots__ = ('_household', '_funds', '_reserved')
    MAX_FUNDS = TunableRange(int, 99999999, 0, sims4.math.MAX_INT32, description='Max Funds a household can have.')

    def __init__(self, household, startingAmount):
        self._household = household
        self._funds = startingAmount
        self._reserved = 0

    @property
    def money(self):
        return self._funds - self._reserved

    def send_money_update(self, vfx_amount, sim=None, reason=0):
        op = distributor.ops.SetMoney(self.money, vfx_amount, sim, reason)
        distributor.ops.record(self._household, op)

    def add(self, amount, reason, sim, tags=None, count_as_earnings=True):
        amount = round(amount)
        if amount < 0:
            logger.error('Attempt to add negative amount of money to Family Funds.', owner='mduke')
            return
        if sim is None:
            for client in services.client_manager().objects:
                while client.household_id == self._household.id:
                    self._update_money(amount, reason, client.account.id, tags=tags, count_as_earnings=count_as_earnings)
                    return
            logger.callstack('Attempt to raise household funds on a house with no client connected.', owner='nbaker', level=sims4.log.LEVEL_WARN)
        else:
            if sim.household != self._household:
                logger.error('Attempt to add funds to the wrong household.', owner='mduke')
                return
            status = sim.account_connection
            if status == AccountConnection.OFFLINE:
                return
            if status == AccountConnection.DIFFERENT_LOT:
                sim.sim_info.add_to_personal_funds(amount)
                with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_POCKET, sim=sim) as hook:
                    hook.write_int(TELEMETRY_AMOUNT, amount)
                    hook.write_int(TELEMETRY_REASON, reason)
            else:
                self._update_money(amount, reason, sim.account_id, sim, tags=tags, count_as_earnings=count_as_earnings)

    def try_remove(self, amount, reason, sim):
        amount = round(amount)
        if sim is None:
            raise ValueError('None Sim.')
        if self.money < amount:
            return
        if amount == 0:
            apply_removal = None
            cancel_removal = None
        elif amount < 0:

            def apply_removal():
                self.add(amount, reason, sim)

            cancel_removal = None
        else:
            self.send_money_update(vfx_amount=-amount, reason=reason)

            def apply_removal():
                self._update_money(-amount, reason, sim.account_id, sim, show_fx=False)

            def cancel_removal():
                self.send_money_update(vfx_amount=amount, reason=reason)

        return ReservedFunds(apply_removal, cancel_removal, amount)

    def remove(self, amount, reason, sim=None):
        amount = round(amount)
        if amount < 0:
            logger.error('Attempt to remove negative amount of money from Family Funds.', owner='mduke')
            return
        if sim is not None:
            self._update_money(-amount, reason, sim.account_id, sim)
        else:
            for client in services.client_manager().objects:
                while client.household_id == self._household.id:
                    self._update_money(-amount, reason, client.account.id)
                    return
            logger.error('Attempt to remove household funds on a house with no client connected.', owner='mduke')

    def empty_sim_personal_funds(self, sim):
        amount = sim.sim_info.empty_personal_funds()
        self._update_money(amount, Consts_pb2.TELEMETRY_SIM_WALLET_EMPTIED, sim.account_id, sim)

    def _update_money(self, amount, reason, account_id, sim=None, tags=None, count_as_earnings=True, show_fx=True):
        if amount == 0:
            return
        self._funds = min(self._funds + amount, self.MAX_FUNDS)
        if self._funds < 0:
            logger.error('Negative funds amount ({}) not supported', self._funds)
            self._funds = 0
        vfx_amount = amount
        if not show_fx:
            vfx_amount = 0
        self.send_money_update(vfx_amount=vfx_amount, sim=sim, reason=reason)
        with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_FUNDS_CHANGE, sim=sim) as hook:
            hook.write_int(TELEMETRY_AMOUNT, amount)
            hook.write_int(TELEMETRY_REASON, reason)
            hook.write_int(TELEMETRY_FUND_AMOUNT, self._funds)
        if count_as_earnings and amount > 0:
            if sim is None:
                services.get_event_manager().process_events_for_household(test_events.TestEvent.SimoleonsEarned, self._household, simoleon_data_type=SimoleonData.TotalMoneyEarned, amount=amount, skill_used=None, tags=tags)
            else:
                services.get_event_manager().process_event(test_events.TestEvent.SimoleonsEarned, sim_info=sim.sim_info, simoleon_data_type=SimoleonData.TotalMoneyEarned, amount=amount, skill_used=None, tags=tags)
                services.get_event_manager().process_events_for_household(test_events.TestEvent.SimoleonsEarned, self._household, simoleon_data_type=SimoleonData.TotalMoneyEarned, amount=0, skill_used=None, tags=frozenset(), exclude_sim=sim.sim_info)

