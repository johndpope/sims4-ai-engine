from audio.primitive import TunablePlayAudio, play_tunable_audio
from clock import interval_in_sim_weeks
from date_and_time import TimeSpan, create_date_and_time, DateAndTime
from distributor.rollback import ProtocolBufferRollback
from event_testing.resolver import SingleSimResolver
from event_testing.results import TestResult
from interactions.interaction_finisher import FinishingType
from sims.bills_enums import Utilities
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.tunable import Tunable, TunableList, TunableTuple, TunablePercent, TunableInterval, TunableMapping, TunableReference
from tunable_multiplier import TunableMultiplier
from tunable_time import Days, TunableTimeOfWeek
from ui.ui_dialog_notification import UiDialogNotification
import alarms
import clock
import objects.components.types
import services
import sims4.log
logger = sims4.log.Logger('Bills')

class Bills:
    __qualname__ = 'Bills'
    BILL_ARRIVAL_NOTIFICATION = UiDialogNotification.TunableFactory(description='\n        A notification which pops up when bills are delivered.\n        ')
    UTILITY_INFO = TunableMapping(key_type=Utilities, value_type=TunableTuple(warning_notification=UiDialogNotification.TunableFactory(description='\n                A notification which appears when the player will be losing this\n                utility soon due to delinquency.\n                '), shutoff_notification=UiDialogNotification.TunableFactory(description='\n                A notification which appears when the player loses this utility\n                due to delinquency.\n                '), shutoff_tooltip=TunableLocalizedStringFactory(description='\n                A tooltip to show when an interaction cannot be run due to this\n                utility being shutoff.\n                ')))
    BILL_COST_MODIFIERS = TunableMultiplier.TunableFactory(description='\n        A tunable list of test sets and associated multipliers to apply to the total bill cost per payment.\n        ')
    BILL_OBJECT = TunableReference(description="\n        The object that will be delivered to the lot's mailbox once bills have\n        been scheduled.\n        ", manager=services.definition_manager())
    DELINQUENCY_FREQUENCY = Tunable(description='\n        Tunable representing the number of Sim hours between utility shut offs.\n        ', tunable_type=int, default=24)
    DELINQUENCY_WARNING_OFFSET_TIME = Tunable(description='\n        Tunable representing the number of Sim hours before a delinquency state\n        kicks in that a warning notification pops up.\n        ', tunable_type=int, default=2)
    BILL_BRACKETS = TunableList(description="\n        A list of brackets that determine the percentages that each portion of\n        a household's value is taxed at.\n        \n        ex: The first $2000 of a household's value is taxed at 10%, and\n        everything after that is taxed at 15%.\n        ", tunable=TunableTuple(description='\n            A value range and tax percentage that define a bill bracket.\n            ', value_range=TunableInterval(description="\n                A tunable range of integers that specifies a portion of a\n                household's total value.\n                ", tunable_type=int, default_lower=0, default_upper=None), tax_percentage=TunablePercent(description="\n                A tunable percentage value that defines what percent of a\n                household's value within this value_range the player is billed\n                for.\n                ", default=10)))
    TIME_TO_PLACE_BILL_IN_HIDDEN_INVENTORY = TunableTimeOfWeek(description="\n        The time of the week that we will attempt to place a bill in this\n        household's hidden inventory so it can be delivered.  This time should\n        be before the mailman shows up for that day or the bill will not be\n        delivered until the following day.\n        ", default_day=Days.MONDAY, default_hour=8, default_minute=0)
    AUDIO = TunableTuple(description='\n        Tuning for all the audio stings that will play as a part of bills.\n        ', delinquency_warning_sfx=TunablePlayAudio(description='\n            The sound to play when a delinquency warning is displayed.\n            '), delinquency_activation_sfx=TunablePlayAudio(description='\n            The sound to play when delinquency is activated.\n            '), delinquency_removed_sfx=TunablePlayAudio(description='\n            The sound to play when delinquency is removed.\n            '), bills_paid_sfx=TunablePlayAudio(description='\n            The sound to play when bills are paid.  If there are any delinquent\n            utilities, the delinquency_removed_sfx will play in place of this.\n            '))

    def __init__(self, household):
        self._household = household
        self._utility_delinquency = {utility: False for utility in Utilities}
        self._can_deliver_bill = False
        self._current_payment_owed = None
        self._bill_timer_handle = None
        self._shutoff_handle = None
        self._warning_handle = None
        self._set_up_bill_timer()
        self._additional_bill_costs = {}
        self.bill_notifications_enabled = True
        self.autopay_bills = False
        self._bill_timer = None
        self._shutoff_timer = None
        self._warning_timer = None
        self._put_bill_in_hidden_inventory = False

    @property
    def can_deliver_bill(self):
        return self._can_deliver_bill

    @property
    def current_payment_owed(self):
        return self._current_payment_owed

    def _get_lot(self):
        home_zone = services.get_zone(self._household.home_zone_id)
        if home_zone is not None:
            return home_zone.lot

    def _set_up_bill_timer(self):
        day = self.TIME_TO_PLACE_BILL_IN_HIDDEN_INVENTORY.day
        hour = self.TIME_TO_PLACE_BILL_IN_HIDDEN_INVENTORY.hour
        minute = self.TIME_TO_PLACE_BILL_IN_HIDDEN_INVENTORY.minute
        time = create_date_and_time(days=day, hours=hour, minutes=minute)
        time_until_bill_delivery = services.time_service().sim_now.time_to_week_time(time)
        bill_delivery_time = services.time_service().sim_now + time_until_bill_delivery
        end_of_first_week = DateAndTime(0) + interval_in_sim_weeks(1)
        if bill_delivery_time < end_of_first_week:
            time_until_bill_delivery += interval_in_sim_weeks(1)
        if time_until_bill_delivery.in_ticks() <= 0:
            time_until_bill_delivery = TimeSpan(1)
        self._bill_timer_handle = alarms.add_alarm(self, time_until_bill_delivery, lambda _: self.allow_bill_delivery())

    def _set_up_timers(self):
        if self._bill_timer is None and self._shutoff_timer is None and self._warning_timer is None:
            return
        next_delinquent_utility = None
        for utility in self._utility_delinquency:
            if self._utility_delinquency[utility]:
                pass
            next_delinquent_utility = utility
            break
        if next_delinquent_utility is None:
            return

        def set_up_alarm(timer_data, handle, callback):
            if timer_data <= 0:
                return
            if handle is not None:
                alarms.cancel_alarm(handle)
            return alarms.add_alarm(self, clock.TimeSpan(timer_data), callback, use_sleep_time=False)

        warning_notification = self.UTILITY_INFO[next_delinquent_utility].warning_notification
        if self._bill_timer > 0 and self._current_payment_owed is not None:
            self._bill_timer_handle = set_up_alarm(self._bill_timer, self._bill_timer_handle, lambda _: self.allow_bill_delivery())
        self._shutoff_handle = set_up_alarm(self._shutoff_timer, self._shutoff_handle, lambda _: self._shut_off_utility(next_delinquent_utility))
        self._warning_handle = set_up_alarm(self._warning_timer, self._warning_handle, lambda _: self._send_notification(warning_notification))
        self._bill_timer = None
        self._shutoff_timer = None
        self._warning_timer = None

    def _destroy_timers(self):
        if self._bill_timer_handle is None and self._shutoff_handle is None and self._warning_handle is None:
            return
        current_time = services.time_service().sim_now
        if self._bill_timer_handle is not None:
            time = max((self._bill_timer_handle.finishing_time - current_time).in_ticks(), 0)
            self._bill_timer = time
            alarms.cancel_alarm(self._bill_timer_handle)
            self._bill_timer_handle = None
        if self._shutoff_handle is not None:
            time = max((self._shutoff_handle.finishing_time - current_time).in_ticks(), 0)
            self._shutoff_timer = time
            alarms.cancel_alarm(self._shutoff_handle)
            self._shutoff_handle = None
        if self._warning_handle is not None:
            time = max((self._warning_handle.finishing_time - current_time).in_ticks(), 0)
            self._warning_timer = time
            alarms.cancel_alarm(self._warning_handle)
            self._warning_handle = None

    def on_all_households_and_sim_infos_loaded(self):
        active_household_id = services.active_household_id()
        if active_household_id is not None and self._household.id == active_household_id:
            self._set_up_timers()

    def on_client_disconnect(self):
        self._destroy_timers()

    def is_utility_delinquent(self, utility):
        if self._utility_delinquency[utility]:
            if self._current_payment_owed is None:
                self._clear_delinquency_status()
                logger.error('Household {} has delinquent utilities without actually owing any money. Resetting delinquency status.', self._household, owner='tastle')
                return False
            return True
        return False

    def is_any_utility_delinquent(self):
        for delinquency_status in self._utility_delinquency.values():
            while delinquency_status:
                return True
        return False

    def mailman_has_delivered_bills(self):
        if self.current_payment_owed is not None and (self._shutoff_handle is not None or self.is_any_utility_delinquent()):
            return True
        return False

    def is_additional_bill_source_delinquent(self, additional_bill_source):
        cost = self._additional_bill_costs.get(additional_bill_source, 0)
        if cost > 0 and any(self._utility_delinquency.values()):
            return True
        return False

    def test_utility_info(self, utility_info):
        if utility_info is None:
            return TestResult.TRUE
        for utility in utility_info:
            while utility in utility_info and self.is_utility_delinquent(utility):
                return TestResult(False, 'Bills: Interaction requires a utility that is shut off.', tooltip=self.UTILITY_INFO[utility].shutoff_tooltip)
        return TestResult.TRUE

    def get_bill_amount(self):
        bill_amount = 0
        billable_household_value = self._household.household_net_worth(billable=True)
        for bracket in Bills.BILL_BRACKETS:
            lower_bound = bracket.value_range.lower_bound
            while billable_household_value >= lower_bound:
                upper_bound = bracket.value_range.upper_bound
                if upper_bound is None:
                    upper_bound = billable_household_value
                bound_difference = upper_bound - lower_bound
                value_difference = billable_household_value - lower_bound
                if value_difference > bound_difference:
                    value_difference = bound_difference
                value_difference *= bracket.tax_percentage
                bill_amount += value_difference
        for additional_cost in self._additional_bill_costs.values():
            bill_amount += additional_cost
        multiplier = 1
        for sim_info in self._household._sim_infos:
            multiplier *= Bills.BILL_COST_MODIFIERS.get_multiplier(SingleSimResolver(sim_info))
        bill_amount *= multiplier
        if bill_amount <= 0 and not self._household.is_npc_household:
            logger.error('Player household {} has been determined to owe {} simoleons. Player households are always expected to owe at least some amount of money for bills.', self._household, bill_amount, owner='tastle')
        return int(bill_amount)

    def allow_bill_delivery(self):
        self._place_bill_in_hidden_inventory()

    def _place_bill_in_hidden_inventory(self):
        self._current_payment_owed = self.get_bill_amount()
        if self._current_payment_owed <= 0:
            self.pay_bill()
            return
        lot = self._get_lot()
        if lot is not None:
            lot.create_object_in_hidden_inventory(self.BILL_OBJECT)
            self._put_bill_in_hidden_inventory = False
            self._can_deliver_bill = True
            return
        self._put_bill_in_hidden_inventory = True
        self.trigger_bill_notifications_from_delivery()

    def _place_bill_in_mailbox(self):
        lot = self._get_lot()
        if lot is None:
            return
        lot.create_object_in_mailbox(self.BILL_OBJECT)
        self._put_bill_in_hidden_inventory = False

    def trigger_bill_notifications_from_delivery(self):
        if self.mailman_has_delivered_bills():
            return
        self._can_deliver_bill = False
        if self.autopay_bills or self._current_payment_owed == 0 or not self._household:
            self.pay_bill()
            return
        self._set_next_delinquency_timers()
        self._send_notification(self.BILL_ARRIVAL_NOTIFICATION)

    def pay_bill(self):
        if self._current_payment_owed:
            for status in self._utility_delinquency.values():
                while status:
                    play_tunable_audio(self.AUDIO.delinquency_removed_sfx)
                    break
            play_tunable_audio(self.AUDIO.bills_paid_sfx)
        self._current_payment_owed = None
        self._clear_delinquency_status()
        self._set_up_bill_timer()

        def remove_from_inventory(inventory):
            for obj in [obj for obj in inventory if obj.definition is self.BILL_OBJECT]:
                obj.destroy(source=inventory, cause='Paying bills.')

        lot = self._get_lot()
        if lot is not None:
            for (_, inventory) in lot.get_all_object_inventories_gen():
                remove_from_inventory(inventory)
        for sim_info in self._household:
            sim = sim_info.get_sim_instance()
            while sim is not None:
                remove_from_inventory(sim.inventory_component)
        self._put_bill_in_hidden_inventory = False

    def _clear_delinquency_status(self):
        for utility in self._utility_delinquency:
            if utility == Utilities.POWER:
                self._start_all_power_utilities()
            self._utility_delinquency[utility] = False
        self._additional_bill_costs = {}
        if self._shutoff_handle is not None:
            alarms.cancel_alarm(self._shutoff_handle)
            self._shutoff_handle = None
        if self._warning_handle is not None:
            alarms.cancel_alarm(self._warning_handle)
            self._warning_handle = None
        for obj in services.object_manager().valid_objects():
            if obj.state_component is None:
                pass
            states_before_delinquency = obj.state_component.states_before_delinquency
            if not states_before_delinquency:
                pass
            for old_state in states_before_delinquency:
                obj.set_state(old_state.state, old_state)
            obj.state_component.states_before_delinquency = []

    def _set_next_delinquency_timers(self):
        for utility in self._utility_delinquency:
            if self._utility_delinquency[utility]:
                pass
            warning_notification = self.UTILITY_INFO[utility].warning_notification
            self._warning_handle = alarms.add_alarm(self, clock.interval_in_sim_hours(self.DELINQUENCY_FREQUENCY - self.DELINQUENCY_WARNING_OFFSET_TIME), lambda _: self._send_notification(warning_notification))
            self._shutoff_handle = alarms.add_alarm(self, clock.interval_in_sim_hours(self.DELINQUENCY_FREQUENCY), lambda _: self._shut_off_utility(utility))
            break

    def _shut_off_utility(self, utility):
        if self._current_payment_owed == None:
            self._clear_delinquency_status()
            logger.error('Household {} is getting a utility shut off without actually owing any money. Resetting delinquency status.', self._household, owner='tastle')
            return
        shutoff_notification = self.UTILITY_INFO[utility].shutoff_notification
        self._send_notification(shutoff_notification)
        if self._shutoff_handle is not None:
            alarms.cancel_alarm(self._shutoff_handle)
            self._shutoff_handle = None
        self._utility_delinquency[utility] = True
        self._set_next_delinquency_timers()
        self._cancel_delinquent_interactions(utility)
        if utility == Utilities.POWER:
            self._stop_all_power_utilities()
        play_tunable_audio(self.AUDIO.delinquency_activation_sfx)

    def _cancel_delinquent_interactions(self, delinquent_utility):
        for sim in services.sim_info_manager().instanced_sims_gen():
            for interaction in sim.si_state:
                utility_info = interaction.utility_info
                if utility_info is None:
                    pass
                while delinquent_utility in utility_info:
                    interaction.cancel(FinishingType.FAILED_TESTS, 'Bills. Interaction violates current delinquency state of household.')
        for obj in services.object_manager().valid_objects():
            if obj.state_component is None:
                pass
            delinquency_state_changes = obj.state_component.delinquency_state_changes
            while delinquency_state_changes is not None and delinquent_utility in delinquency_state_changes:
                new_states = delinquency_state_changes[delinquent_utility]
                if not new_states:
                    pass
                while True:
                    for new_state in new_states:
                        if obj.state_value_active(new_state):
                            pass
                        obj.state_component.states_before_delinquency.append(obj.state_component.get_state(new_state.state))
                        obj.set_state(new_state.state, new_state)

    def _start_all_power_utilities(self):
        object_manager = services.object_manager()
        for light_obj in object_manager.get_all_objects_with_component_gen(objects.components.types.LIGHTING_COMPONENT):
            while light_obj.get_household_owner_id() == self._household.id:
                light_obj.lighting_component.on_power_on()

    def _stop_all_power_utilities(self):
        object_manager = services.object_manager()
        for light_obj in object_manager.get_all_objects_with_component_gen(objects.components.types.LIGHTING_COMPONENT):
            while light_obj.get_household_owner_id() == self._household.id:
                light_obj.lighting_component.on_power_off()

    def _send_notification(self, notification):
        if not self.bill_notifications_enabled:
            return
        client = services.client_manager().get_client_by_household(self._household)
        if client is not None:
            active_sim = client.active_sim
            if active_sim is not None:
                remaining_time = max(int(self._shutoff_handle.get_remaining_time().in_hours()), 0)
                dialog = notification(active_sim, None)
                dialog.show_dialog(additional_tokens=(remaining_time, self._current_payment_owed))
        current_time = services.time_service().sim_now
        if self._warning_handle is not None and self._warning_handle.finishing_time <= current_time:
            alarms.cancel_alarm(self._warning_handle)
            self._warning_handle = None
            play_tunable_audio(self.AUDIO.delinquency_warning_sfx)

    def add_additional_bill_cost(self, additional_bill_source, cost):
        current_cost = self._additional_bill_costs.get(additional_bill_source, 0)
        self._additional_bill_costs[additional_bill_source] = current_cost + cost

    def load_data(self, householdProto):
        for utility in householdProto.gameplay_data.delinquent_utilities:
            self._utility_delinquency[utility] = True
            while utility == Utilities.POWER:
                self._stop_all_power_utilities()
        for additional_bill_cost in householdProto.gameplay_data.additional_bill_costs:
            self.add_additional_bill_cost(additional_bill_cost.bill_source, additional_bill_cost.cost)
        self._can_deliver_bill = householdProto.gameplay_data.can_deliver_bill
        self._put_bill_in_hidden_inventory = householdProto.gameplay_data.put_bill_in_hidden_inventory
        if self._put_bill_in_hidden_inventory:
            self._place_bill_in_mailbox()
        self._current_payment_owed = householdProto.gameplay_data.current_payment_owed
        if self._current_payment_owed == 0:
            self._current_payment_owed = None
        self._bill_timer = householdProto.gameplay_data.bill_timer
        self._shutoff_timer = householdProto.gameplay_data.shutoff_timer
        self._warning_timer = householdProto.gameplay_data.warning_timer
        active_household_id = services.active_household_id()
        if active_household_id is not None and self._household.id == active_household_id:
            self._set_up_timers()
        elif self._bill_timer_handle is not None:
            alarms.cancel_alarm(self._bill_timer_handle)
            self._bill_timer_handle = None

    def save_data(self, household_msg):
        for utility in Utilities:
            while self.is_utility_delinquent(utility):
                household_msg.gameplay_data.delinquent_utilities.append(utility)
        for (bill_source, cost) in self._additional_bill_costs.items():
            with ProtocolBufferRollback(household_msg.gameplay_data.additional_bill_costs) as additional_bill_cost:
                additional_bill_cost.bill_source = bill_source
                additional_bill_cost.cost = cost
        household_msg.gameplay_data.can_deliver_bill = self._can_deliver_bill
        household_msg.gameplay_data.put_bill_in_hidden_inventory = self._put_bill_in_hidden_inventory
        if self.current_payment_owed is not None:
            household_msg.gameplay_data.current_payment_owed = self.current_payment_owed
        current_time = services.time_service().sim_now
        if self._bill_timer_handle is not None:
            time = max((self._bill_timer_handle.finishing_time - current_time).in_ticks(), 0)
            household_msg.gameplay_data.bill_timer = time
        elif self._bill_timer is not None:
            household_msg.gameplay_data.bill_timer = self._bill_timer
        if self._shutoff_handle is not None:
            time = max((self._shutoff_handle.finishing_time - current_time).in_ticks(), 0)
            household_msg.gameplay_data.shutoff_timer = time
        elif self._shutoff_timer is not None:
            household_msg.gameplay_data.shutoff_timer = self._shutoff_timer
        if self._warning_handle is not None:
            time = max((self._warning_handle.finishing_time - current_time).in_ticks(), 0)
            household_msg.gameplay_data.warning_timer = time
        elif self._warning_timer is not None:
            household_msg.gameplay_data.warning_timer = self._warning_timer

