from distributor import shared_messages
from distributor.system import Distributor
from objects import HiddenReasonFlag, ALL_HIDDEN_REASONS
from protocolbuffers import Consts_pb2, UI_pb2
from server_commands.argument_helpers import OptionalTargetParam, get_optional_target
from sims.bills_enums import AdditionalBillSource, Utilities
import services
import sims4.commands
import sims4.log
import zone
logger = sims4.log.Logger('Commands')

@sims4.commands.Command('households.list')
def list_households(household_id:int=None, _connection=None):
    household_manager = services.household_manager()
    output = sims4.commands.Output(_connection)
    output('Household report:')
    if household_id is not None:
        households = (household_manager.get(household_id),)
    else:
        households = household_manager.get_all()
    for household in households:
        output('{}, {} Sims'.format(str(household), len(household)))
        for sim_info in household.sim_info_gen():
            if sim_info.is_instanced(allow_hidden_flags=0):
                output(' Instanced: {}'.format(sim_info))
            elif sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS):
                output(' Hidden: {}'.format(sim_info))
            else:
                output(' Off lot: {}'.format(sim_info))

@sims4.commands.Command('households.modify_funds', command_type=sims4.commands.CommandType.Automation)
def modify_household_funds(amount, household_id:int=0, reason=None, _connection=None):
    if reason is None:
        reason = Consts_pb2.TELEMETRY_MONEY_CHEAT
    if household_id == 0:
        tgt_client = services.client_manager().get(_connection)
        household = tgt_client.household
    else:
        household = services.household_manager().get(household_id)
    if household is not None:
        if amount > 0:
            household.funds.add(amount, reason, None)
        else:
            household.funds.remove(-amount, reason, None)
    else:
        sims4.commands.output('Invalid Household id: {}'.format(household_id), _connection)

@sims4.commands.Command('households.get_value', command_type=sims4.commands.CommandType.DebugOnly)
def get_value(household_id, billable:bool=False, _connection=None):
    household = services.household_manager().get(household_id)
    if household is not None:
        value = household.household_net_worth(billable=billable)
        sims4.commands.output('Simoleon value of household {} is {}.'.format(household, value), _connection)
    else:
        sims4.commands.output('Invalid Household id: {}'.format(household_id), _connection)

@sims4.commands.Command('households.toggle_bill_notifications', 'households.toggle_bill_dialogs', command_type=sims4.commands.CommandType.Automation)
def toggle_bill_notifications(enable:bool=None, _connection=None):
    households = services.household_manager().get_all()
    for household in households:
        bills_manager = household.bills_manager
        enable_notifications = enable if enable is not None else not bills_manager.bill_notifications_enabled
        if enable_notifications:
            bills_manager.bill_notifications_enabled = True
            sims4.commands.output('Bill notifications for household {} enabled.'.format(household), _connection)
        else:
            bills_manager.bill_notifications_enabled = False
            sims4.commands.output('Bill notifications for household {} disabled.'.format(household), _connection)

@sims4.commands.Command('households.make_bill_source_delinquent', command_type=sims4.commands.CommandType.DebugOnly)
def make_bill_source_delinquent(additional_bill_source_name='Miscellaneous', _connection=None):
    try:
        additional_bill_source = AdditionalBillSource(additional_bill_source_name)
    except:
        sims4.commands.output('{0} is not a valid AdditionalBillSource.'.format(additional_bill_source_name), _connection)
        return False
    if additional_bill_source is not None:
        households = services.household_manager().get_all()
        for household in households:
            bills_manager = household.bills_manager
            bills_manager.add_additional_bill_cost(additional_bill_source, 1)
            if bills_manager.current_payment_owed is None:
                bills_manager._current_payment_owed = bills_manager.get_bill_amount()
            previous_send_notification = bills_manager.bill_notifications_enabled
            bills_manager.bill_notifications_enabled = False
            bills_manager._shut_off_utility(Utilities.POWER)
            bills_manager.bill_notifications_enabled = previous_send_notification

@sims4.commands.Command('households.make_bills_delinquent', command_type=sims4.commands.CommandType.DebugOnly)
def make_bills_delinquent(_connection=None):
    households = services.household_manager().get_all()
    for household in households:
        bills_manager = household.bills_manager
        previous_send_notification = bills_manager.bill_notifications_enabled
        bills_manager.bill_notifications_enabled = False
        if bills_manager.current_payment_owed is None:
            bills_manager._current_payment_owed = bills_manager.get_bill_amount()
        for utility in Utilities:
            bills_manager._shut_off_utility(utility)
        bills_manager.bill_notifications_enabled = previous_send_notification

@sims4.commands.Command('households.pay_bills', command_type=sims4.commands.CommandType.DebugOnly)
def pay_bills(_connection=None):
    households = services.household_manager().get_all()
    for household in households:
        bills_manager = household.bills_manager
        bills_manager.pay_bill()

@sims4.commands.Command('households.force_bills_due', command_type=sims4.commands.CommandType.Automation)
def force_bills_due(_connection=None):
    tgt_client = services.client_manager().get(_connection)
    if tgt_client is None:
        return False
    if tgt_client.household is None:
        return False
    tgt_client.household.bills_manager.allow_bill_delivery()
    tgt_client.household.bills_manager.trigger_bill_notifications_from_delivery()
    return True

@sims4.commands.Command('households.autopay_bills', command_type=sims4.commands.CommandType.Automation)
def autopay_bills(enable:bool=None, _connection=None):
    households = services.household_manager().get_all()
    for household in households:
        bills_manager = household.bills_manager
        autopay_bills = enable if enable is not None else not bills_manager.autopay_bills
        bills_manager.autopay_bills = autopay_bills
        sims4.commands.output('Autopay Bills for household {} set to {}.'.format(household, autopay_bills), _connection)

@sims4.commands.Command('households.get_household_display_info', command_type=sims4.commands.CommandType.Automation)
def get_household_display_info(lot_id, _connection=None):
    persistence_service = services.get_persistence_service()
    household_display_info = UI_pb2.HouseholdDisplayInfo()
    household_id = persistence_service.get_household_id_from_lot_id(lot_id)
    if household_id is None:
        household_id = 0
    household = services.household_manager().get(household_id)
    if household is None:
        household_id = 0
    else:
        household_display_info.at_home_sim_ids.extend(household.get_sims_at_home())
    household_display_info.household_id = household_id
    household_display_info.lot_id = lot_id
    op = shared_messages.create_message_op(household_display_info, Consts_pb2.MSG_UI_HOUSEHOLD_DISPLAY_INFO)
    Distributor.instance().add_op_with_no_owner(op)

@sims4.commands.Command('households.merge_with_active', command_type=sims4.commands.CommandType.Live)
def merge_with_active(household_id, _connection=None):
    client = services.client_manager().get(_connection)
    household = client.household
    household.merge(household_id)

@sims4.commands.Command('households.debug_trigger_ask_to_come_over_phone_call')
def trigger_ask_to_come_over_phone_call(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('No sim for households.debug_trigger_ask_to_come_over_phone_call.', _connection)
        return False
    if not services.household_manager().debug_trigger_ask_to_come_over_phone_call(sim):
        sims4.commands.output('households.debug_trigger_ask_to_come_over_phone_call failed to trigger phone call.', _connection)
        return False
    return True

@sims4.commands.Command('households.debug_trigger_chat_phone_call')
def trigger_chat_phone_call(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('No sim for households.debug_trigger_chat_phone_call.', _connection)
        return False
    if not services.household_manager().debug_trigger_chat_phone_call(sim):
        sims4.commands.output('households.debug_trigger_chat_phone_call failed to trigger phone call.', _connection)
        return False
    return True

@sims4.commands.Command('households.debug_trigger_invite_over_phone_call')
def trigger_invite_over_phone_call(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('No sim for households.debug_trigger_invite_over_phone_call.', _connection)
        return False
    if not services.household_manager().debug_trigger_invite_over_phone_call(sim):
        sims4.commands.output('households.debug_trigger_invite_over_phone_call failed to trigger phone call.', _connection)
        return False
    return True

@sims4.commands.Command('households.fill_visible_commodities_world', command_type=sims4.commands.CommandType.Cheat)
def fill_visible_commodities_world(opt_object:OptionalTargetParam=None, _connection=True):
    for sim_info in services.sim_info_manager().objects:
        sim_info.commodity_tracker.set_all_commodities_to_max(visible_only=True)

@sims4.commands.Command('households.fill_visible_commodities_household', command_type=sims4.commands.CommandType.Cheat)
def fill_visible_commodities_household(opt_object:OptionalTargetParam=None, _connection=None):
    active_sim_info = services.client_manager().get(_connection).active_sim
    household = active_sim_info.household
    for sim_info in household.sim_info_gen():
        sim_info.commodity_tracker.set_all_commodities_to_max(visible_only=True)

def _set_motive_decay(sim_infos, enable=True):
    for sim_info in sim_infos:
        for commodity in sim_info.commodity_tracker.get_all_commodities():
            while commodity.is_visible:
                current_decay_modifier = commodity.get_decay_rate_modifier()
                if enable:
                    if current_decay_modifier == 0:
                        commodity.remove_decay_rate_modifier(0)
                        commodity.send_commodity_progress_msg()
                        if not current_decay_modifier == 0:
                            commodity.add_decay_rate_modifier(0)
                            commodity.send_commodity_progress_msg()
                elif not current_decay_modifier == 0:
                    commodity.add_decay_rate_modifier(0)
                    commodity.send_commodity_progress_msg()

@sims4.commands.Command('households.enable_household_motive_decay', command_type=sims4.commands.CommandType.Cheat)
def enable_household_motive_decay(opt_object:OptionalTargetParam=None, _connection=None):
    active_sim_info = services.client_manager().get(_connection).active_sim
    household = active_sim_info.household
    _set_motive_decay(household.sim_info_gen(), True)

@sims4.commands.Command('households.disable_household_motive_decay', command_type=sims4.commands.CommandType.Cheat)
def disable_household_motive_decay(opt_object:OptionalTargetParam=None, _connection=None):
    active_sim_info = services.client_manager().get(_connection).active_sim
    household = active_sim_info.household
    _set_motive_decay(household.sim_info_gen(), False)

@sims4.commands.Command('households.enable_world_motive_decay', command_type=sims4.commands.CommandType.Cheat)
def enable_world_motive_decay(opt_object:OptionalTargetParam=None, _connection=True):
    _set_motive_decay(services.sim_info_manager().objects, True)

@sims4.commands.Command('households.disable_world_motive_decay', command_type=sims4.commands.CommandType.Cheat)
def disable_world_motive_decay(opt_object:OptionalTargetParam=None, _connection=True):
    _set_motive_decay(services.sim_info_manager().objects, False)

