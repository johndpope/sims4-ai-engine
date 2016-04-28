from collections import Counter
from protocolbuffers import Consts_pb2
from scheduler import TunableWeeklyScheduleFactory
from sims4.localization import LocalizationHelperTuning, TunableLocalizedStringFactory, TunableLocalizedString
from sims4.tuning.tunable import TunableMapping, TunableReference, TunableEnumEntry, TunableVariant, TunableTuple, TunablePercent, TunableSet
from ui.ui_dialog_notification import UiDialogNotification
import services
import tag

class RebateManager:
    __qualname__ = 'RebateManager'
    TRAIT_REBATE_MAP = TunableMapping(description='\n        A mapping of traits and the tags of objects which provide a rebate for\n        the given trait.\n        ', key_type=TunableReference(description='\n            If the Sim has this trait, any objects purchased with the given\n            tag(s) below will provide a rebate.\n            ', manager=services.trait_manager()), value_type=TunableTuple(description='\n            The information about the rebates the player should get for having\n            the mapped trait.\n            ', valid_objects=TunableVariant(description='\n                The items to which the rebate will be applied.\n                ', by_tag=TunableSet(description='\n                    The rebate will only be applied to objects purchased with the\n                    tags in this list.\n                    ', tunable=TunableEnumEntry(tag.Tag, tag.Tag.INVALID)), locked_args={'all_purchases': None}), rebate_percentage=TunablePercent(description='\n                The percentage of the catalog price that the player will get\n                back in the rebate.\n                ', default=10)))
    REBATE_PAYMENT_SCHEDULE = TunableWeeklyScheduleFactory(description='\n        The schedule when accrued rebates will be paid out.\n        ')
    REBATE_NOTIFICATION = UiDialogNotification.TunableFactory(description='\n        The notification that will show when the player receives their rebate money.\n        ', locked_args={'text': None})
    REBATE_NOTIFICATION_HEADER = TunableLocalizedString(description='\n        The header for the rebate notification that displays when the households\n        gets their rebate payout.\n        ')
    REBATE_NOTIFICATION_LINE_ITEM = TunableLocalizedStringFactory(description='\n        Each trait that gave rebates will generate a new line item on the notification.\n        {0.String} = trait name\n        {1.Money} = amount of rebate money received from the trait.\n        ')

    def __init__(self, household):
        self._household = household
        self._rebates = Counter()
        self._schedule = None

    def add_rebate_for_object(self, obj):
        for (trait, rebate_info) in self.TRAIT_REBATE_MAP.items():
            rebate_percentage = rebate_info.rebate_percentage
            valid_objects = rebate_info.valid_objects
            while self._sim_in_household_has_trait(trait):
                if valid_objects is None or self._object_has_required_tags(obj, valid_objects):
                    self._rebates[trait] += obj.catalog_value*rebate_percentage
        if self._rebates:
            self.start_rebate_schedule()

    def _sim_in_household_has_trait(self, trait):
        return any(s.trait_tracker.has_trait(trait) for s in self._household.sim_info_gen())

    @staticmethod
    def _object_has_required_tags(obj, valid_tags):
        return set(obj.tags) & set(valid_tags)

    def clear_rebates(self):
        self._rebates.clear()

    def start_rebate_schedule(self):
        if self._schedule is None:
            self._schedule = self.REBATE_PAYMENT_SCHEDULE(start_callback=self._payout_rebates, schedule_immediate=False)

    def _payout_rebates(self, *_):
        if not self._rebates:
            return
        active_sim = self._household.client.active_sim
        line_item_text = LocalizationHelperTuning.get_new_line_separated_strings(*(self.REBATE_NOTIFICATION_LINE_ITEM(t.display_name(active_sim), a) for (t, a) in self._rebates.items()))
        notification_text = LocalizationHelperTuning.get_new_line_separated_strings(self.REBATE_NOTIFICATION_HEADER, line_item_text)
        dialog = self.REBATE_NOTIFICATION(active_sim, text=lambda *_, **__: notification_text)
        dialog.show_dialog()
        total_rebate_amount = sum(self._rebates.values())
        self._household.funds.add(total_rebate_amount, reason=Consts_pb2.TELEMETRY_MONEY_ASPIRATION_REWARD, sim=active_sim)
        self.clear_rebates()

