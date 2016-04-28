from interactions.base.picker_interaction import PickerSuperInteraction
from sims4.localization import TunableLocalizedStringFactory, TunableLocalizedString
from sims4.tuning.tunable import TunableReference, TunableList, TunableTuple
from sims4.tuning.tunable_base import GroupNames
from sims4.utils import flexmethod
from situations.service_npcs.service_npc_tuning import ServiceNpcHireable
import services
import sims4.resources
import ui

class PickServiceNpcSuperInteraction(PickerSuperInteraction):
    __qualname__ = 'PickServiceNpcSuperInteraction'
    INSTANCE_TUNABLES = {'service_npcs': TunableList(description='\n            A list of the service npcs that will show up in the dialog picker\n            ', tunable=TunableTuple(description='\n                Tuple of service npcs data about those NPCs being pickable.\n                ', service_npc=TunableReference(description='\n                    The service npcs that will show up in the picker.\n                    ', manager=services.get_instance_manager(sims4.resources.Types.SERVICE_NPC), class_restrictions=(ServiceNpcHireable,)), already_hired_tooltip=TunableLocalizedStringFactory(description='\n                    Tooltip that displays if the service has already been\n                    hired.\n                    ')), tuning_group=GroupNames.PICKERTUNING), 'display_price_flat_rate': TunableLocalizedStringFactory(description='\n            Formatting for cost of the service if it has just a one time flat fee.\n            Parameters: 0 is flat rate cost of the service\n            ', tuning_group=GroupNames.PICKERTUNING), 'display_price_hourly_cost': TunableLocalizedStringFactory(description='\n            Formatting for cost of the service if it is purely hourly\n            Parameters: 0 is hourly cost of the service\n            ', tuning_group=GroupNames.PICKERTUNING), 'display_price_fee_and_hourly_cost': TunableLocalizedStringFactory(description='\n            Formatting for cost of the service if it has an upfront cost AND an\n            hourly cost\n            Parameters: 0 is upfront cost of service. 1 is hourly cost of service\n            ', tuning_group=GroupNames.PICKERTUNING), 'display_price_free': TunableLocalizedString(description='\n            Description text if the service has zero upfront cost and zero hourly cost.\n            ', tuning_group=GroupNames.PICKERTUNING)}

    def _run_interaction_gen(self, timeline):
        self._show_picker_dialog(self.sim, target_sim=self.sim)
        return True

    class _ServiceNpcRecurringPair:
        __qualname__ = 'PickServiceNpcSuperInteraction._ServiceNpcRecurringPair'

        def __init__(self, service_npc_type, recurring):
            self.service_npc_type = service_npc_type
            self.recurring = recurring
            self.__name__ = '{} recurring: {}'.format(self.service_npc_type, self.recurring)

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        inst_or_cls = cls if inst is None else inst
        service_npc_data_tuples = [service_npc_data for service_npc_data in inst_or_cls.service_npcs]
        for service_npc_data in service_npc_data_tuples:
            service_npc_type = service_npc_data.service_npc
            household = context.sim.household
            service_record = household.get_service_npc_record(service_npc_type.guid64, add_if_no_record=False)
            is_enabled = service_record is None or not service_record.hired
            if not is_enabled:
                tooltip = service_npc_data.already_hired_tooltip
            else:
                tooltip = None
            allows_recurring = service_npc_type._recurring is not None
            display_name = service_npc_type.display_name if not allows_recurring else service_npc_type._recurring.one_time_name
            tag = PickServiceNpcSuperInteraction._ServiceNpcRecurringPair(service_npc_type, recurring=False)
            if service_npc_type.cost_up_front > 0 and service_npc_type.cost_hourly > 0:
                display_description = inst_or_cls.display_price_fee_and_hourly_cost(service_npc_type.cost_up_front, service_npc_type.cost_hourly)
            elif service_npc_type.cost_up_front > 0:
                display_description = inst_or_cls.display_price_flat_rate(service_npc_type.cost_up_front)
            elif service_npc_type.cost_hourly > 0:
                display_description = inst_or_cls.display_price_hourly_cost(service_npc_type.cost_hourly)
            else:
                display_description = inst_or_cls.display_price_free()
            row = ui.ui_dialog_picker.ObjectPickerRow(is_enable=is_enabled, name=display_name, icon=service_npc_type.icon, row_description=display_description, tag=tag, row_tooltip=tooltip)
            yield row
            while allows_recurring:
                tag = PickServiceNpcSuperInteraction._ServiceNpcRecurringPair(service_npc_type, recurring=True)
                row = ui.ui_dialog_picker.ObjectPickerRow(is_enable=is_enabled, name=service_npc_type._recurring.recurring_name, icon=service_npc_type.icon, row_description=display_description, tag=tag)
                yield row

    def on_choice_selected(self, choice_tag, **kwargs):
        tag = choice_tag
        if tag is not None:
            tag.service_npc_type.on_chosen_from_service_picker(self, recurring=tag.recurring)

