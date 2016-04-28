import random
from weakref import WeakKeyDictionary
from alarms import add_alarm, cancel_alarm
import clock
from distributor.rollback import ProtocolBufferRollback
from event_testing.tests import TunableTestVariant
from interactions.item_consume import ItemCost
from interactions.utils.interaction_elements import XevtTriggeredElement
from interactions.utils.loot import LootActions
from interactions.utils.tunable import TunableContinuation
from element_utils import build_critical_section_with_finally
from protocolbuffers import Consts_pb2, SimObjectAttributes_pb2 as protocols
from sims4.localization import TunableLocalizedStringFactoryVariant, TunableLocalizedStringFactory
from sims4.random import weighted_random_item
import sims4.reload
from sims4.tuning.dynamic_enum import DynamicEnumLocked
from sims4.tuning.tunable import AutoFactoryInit, HasTunableFactory, TunableMapping, TunableTuple, TunableList, TunableEnumEntry, Tunable, TunableVariant, TunableRange, TunableInterval, OptionalTunable
from snippets import define_snippet
from tunable_multiplier import TunableMultiplier
from ui.ui_dialog import UiDialog, UiDialogResponse
from ui.ui_dialog_notification import TunableUiDialogNotificationSnippet
with sims4.reload.protected(globals()):
    _initial_adventure_moment_key_overrides = WeakKeyDictionary()

def set_initial_adventure_moment_key_override(sim, initial_adventure_moment_key):
    _initial_adventure_moment_key_overrides[sim] = initial_adventure_moment_key

class AdventureTracker:
    __qualname__ = 'AdventureTracker'

    def __init__(self):
        self._adventure_mappings = dict()

    def set_adventure_moment(self, interaction, adventure_moment_id):
        self._adventure_mappings[interaction.guid64] = adventure_moment_id

    def remove_adventure_moment(self, interaction):
        if interaction.guid64 in self._adventure_mappings:
            del self._adventure_mappings[interaction.guid64]

    def get_adventure_moment(self, interaction):
        return self._adventure_mappings.get(interaction.guid64)

    def save(self):
        data = protocols.PersistableAdventureTracker()
        for (adventure_id, adventure_moment_id) in self._adventure_mappings.items():
            with ProtocolBufferRollback(data.adventures) as adventure_pair:
                adventure_pair.adventure_id = adventure_id
                adventure_pair.adventure_moment_id = adventure_moment_id
        return data

    def load(self, data):
        for adventure_pair in data.adventures:
            self._adventure_mappings[adventure_pair.adventure_id] = adventure_pair.adventure_moment_id

class AdventureMomentKey(DynamicEnumLocked):
    __qualname__ = 'AdventureMomentKey'
    INVALID = 0

class AdventureMoment(HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'AdventureMoment'
    LOOT_NOTIFICATION_TEXT = TunableLocalizedStringFactory(description='\n        A string used to recursively build loot notification text. It will be\n        given two tokens: a loot display text string, if any, and the previously\n        built LOOT_NOTIFICATION_TEXT string.\n        ')
    NOTIFICATION_TEXT = TunableLocalizedStringFactory(description='\n        A string used to format notifications. It will be given two arguments:\n        the notification text and the built version of LOOT_NOTIFICATION_TEXT,\n        if not empty.\n        ')
    COST_TYPE_SIMOLEONS = 0
    COST_TYPE_ITEMS = 1
    FACTORY_TUNABLES = {'description': '\n            A phase of an adventure. Adventure moments may present\n            some information in a dialog form and for a choice to be\n            made regarding how the overall adventure will branch.\n            ', '_visibility': OptionalTunable(description='\n            Control whether or not this moment provides visual feedback to\n            the player (i.e., a modal dialog).\n            ', tunable=UiDialog.TunableFactory(), disabled_name='not_visible', enabled_name='show_dialog'), '_finish_actions': TunableList(description='\n            A list of choices that can be made by the player to determine\n            branching for the adventure. At most two finish actions can\n            be tuned. They will be displayed as buttons in the UI. If no\n            dialog is displayed, then the first finish action will be selected.\n            If this list is empty, the adventure ends.\n            ', tunable=TunableTuple(display_text=TunableLocalizedStringFactoryVariant(description="\n                   This finish action's title. This will be the button text in\n                   the UI.\n                   "), cost=TunableVariant(description='\n                    The cost associated with this finish action. Only one type\n                    of cost may be tuned. The player is informed of the cost\n                    before making the selection by modifying the display_text\n                    string to include this information.\n                    ', simoleon_cost=TunableTuple(description="The specified\n                        amount will be deducted from the Sim's funds.\n                        ", locked_args={'cost_type': COST_TYPE_SIMOLEONS}, amount=TunableRange(description='How many Simoleons to\n                            deduct.\n                            ', tunable_type=int, default=0, minimum=0)), item_cost=TunableTuple(description="The specified items will \n                        be removed from the Sim's inventory.\n                        ", locked_args={'cost_type': COST_TYPE_ITEMS}, item_cost=ItemCost.TunableFactory()), default=None), action_results=TunableList(description='\n                    A list of possible results that can occur if this finish\n                    action is selected. Action results can award loot, display\n                    notifications, and control the branching of the adventure by\n                    selecting the next adventure moment to run.\n                    ', tunable=TunableTuple(weight_modifiers=TunableList(description='\n                            A list of modifiers that affect the probability that\n                            this action result will be chosen. These are exposed\n                            in the form (test, multiplier). If the test passes,\n                            then the multiplier is applied to the running total.\n                            The default multiplier is 1. To increase the\n                            likelihood of this action result being chosen, tune\n                            multiplier greater than 1. To decrease the\n                            likelihood of this action result being chose, tune\n                            multipliers lower than 1. If you want to exclude\n                            this action result from consideration, tune a\n                            multiplier of 0.\n                            ', tunable=TunableTuple(description='\n                                A pair of test and weight multiplier. If the\n                                test passes, the associated weight multiplier is\n                                applied. If no test is specified, the multiplier\n                                is always applied.\n                                ', test=TunableTestVariant(description='\n                                    The test that has to pass for this weight\n                                    multiplier to be applied. The information\n                                    available to this test is the same\n                                    information available to the interaction\n                                    owning this adventure.\n                                    ', test_locked_args={'tooltip': None}), weight_multiplier=Tunable(description='\n                                    The weight multiplier to apply if the\n                                    associated test passes.\n                                    ', tunable_type=float, default=1))), notification=OptionalTunable(description='\n                            If set, this notification will be displayed.\n                            ', tunable=TunableUiDialogNotificationSnippet()), next_moments=TunableList(description='\n                            A list of adventure moment keys. One of these keys will\n                            be selected to determine which adventure moment is\n                            selected next. If the list is empty, the adventure ends\n                            here. Any of the keys tuned here will have to be tuned\n                            in the _adventure_moments tunable for the owning adventure.\n                            ', tunable=AdventureMomentKey), loot_actions=TunableList(description='\n                            List of Loot actions that are awarded if this action result is selected.\n                            ', tunable=LootActions.TunableReference()), continuation=TunableContinuation(description='\n                            A continuation to push when running finish actions.\n                            ')))), maxlength=2)}

    def __init__(self, parent_adventure, **kwargs):
        super().__init__(**kwargs)
        self._parent_adventure = parent_adventure

    @property
    def _interaction(self):
        return self._parent_adventure.interaction

    @property
    def _sim(self):
        return self._interaction.sim

    def run_adventure(self):
        if self._visibility is None:
            self._run_action_from_index(0)
        else:
            dialog = self._get_dialog()
            dialog.show_dialog()

    def _run_action_from_index(self, action_index):
        action = self._finish_actions[action_index]
        if self._apply_action_cost(action):
            self._run_finish_actions(action)

    def _get_action_result_weight(self, action_result):
        interaction_resolver = self._interaction.get_resolver()
        weight = 1
        for modifier in action_result.weight_modifiers:
            while modifier.test is None or interaction_resolver(modifier.test):
                weight *= modifier.weight_multiplier
        return weight

    def _apply_action_cost(self, action):
        if action.cost is not None:
            if action.cost.cost_type == self.COST_TYPE_SIMOLEONS:
                amount = action.cost.amount
                if amount > self._sim.family_funds.money:
                    return False
                self._sim.family_funds.remove(amount, Consts_pb2.TELEMETRY_INTERACTION_COST, sim=self._sim)
            elif action.cost.cost_type == self.COST_TYPE_ITEMS:
                item_cost = action.cost.item_cost
                return item_cost.consume_interaction_cost(self._interaction)()
        return True

    def _run_finish_actions(self, finish_action):
        weight_pairs = [(self._get_action_result_weight(action_result), action_result) for action_result in finish_action.action_results]
        action_result = weighted_random_item(weight_pairs)
        if action_result is not None:
            loot_display_text = None
            resolver = self._interaction.get_resolver()
            for actions in action_result.loot_actions:
                for (loot_op, test_ran) in actions.get_loot_ops_gen(resolver):
                    while loot_op.apply_to_resolver(resolver, skip_test=test_ran):
                        if action_result.notification is not None:
                            current_loot_display_text = loot_op.get_display_text()
                            if current_loot_display_text is not None:
                                if loot_display_text is None:
                                    loot_display_text = current_loot_display_text
                                else:
                                    loot_display_text = self.LOOT_NOTIFICATION_TEXT(loot_display_text, current_loot_display_text)
            if action_result.notification is not None:
                if loot_display_text is not None:
                    notification_text = lambda *tokens: self.NOTIFICATION_TEXT(action_result.notification.text(*tokens), loot_display_text)
                else:
                    notification_text = action_result.notification.text
                dialog = action_result.notification(self._sim, self._interaction.get_resolver())
                dialog.text = notification_text
                dialog.show_dialog()
            if action_result.next_moments:
                next_moment_key = random.choice(action_result.next_moments)
                self._parent_adventure.queue_adventure_moment(next_moment_key)
            if action_result.continuation:
                self._interaction.push_tunable_continuation(action_result.continuation)

    def _on_dialog_response(self, dialog):
        if dialog.response is not None:
            self._run_action_from_index(dialog.response)

    def _get_action_display_text(self, action):
        display_name = self._interaction.create_localized_string(action.display_text)
        if action.cost is not None:
            if action.cost.cost_type == self.COST_TYPE_SIMOLEONS:
                amount = action.cost.amount
                display_name = self._interaction.SIMOLEON_COST_NAME_FACTORY(display_name, amount)
            elif action.cost.cost_type == self.COST_TYPE_ITEMS:
                item_cost = action.cost.item_cost
                display_name = item_cost.get_interaction_name(self._interaction, display_name)
        return lambda *_, **__: display_name

    def _get_dialog(self):
        dialog = self._visibility(self._sim, self._interaction.get_resolver())
        dialog.set_responses(tuple(UiDialogResponse(dialog_response_id=i, text=self._get_action_display_text(action)) for (i, action) in enumerate(self._finish_actions)))
        dialog.add_listener(self._on_dialog_response)
        return dialog

(TunableAdventureMomentReference, TunableAdventureMomentSnippet) = define_snippet('Adventure_Moment', AdventureMoment.TunableFactory())

class Adventure(XevtTriggeredElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'Adventure'
    FACTORY_TUNABLES = {'description': '\n            A series of individual moments linked together in a game-like\n            fashion.\n            ', '_adventure_moments': TunableMapping(description='\n            The individual adventure moments for this adventure. Every moment\n            used in the adventure must be defined here. For instance, if there\n            is an adventure moment that triggers another adventure moment, the\n            latter must also be defined in this list.\n            ', key_type=AdventureMomentKey, value_type=TunableAdventureMomentSnippet()), '_initial_moments': TunableList(description='\n            A list of adventure moments that are valid as initiating moments for\n            this adventure.\n            ', tunable=TunableTuple(description='\n                A tuple of moment key and weight. The higher the weight, the\n                more likely it is this moment will be selected as the initial\n                moment.\n                ', adventure_moment_key=TunableEnumEntry(description='\n                    The key of the initial adventure moment.\n                    ', tunable_type=AdventureMomentKey, default=AdventureMomentKey.INVALID), weight=TunableMultiplier.TunableFactory(description='\n                    The weight of this potential initial moment relative\n                    to other items within this list.\n                    '))), '_trigger_interval': TunableInterval(description='\n            The interval, in Sim minutes, between the end of one adventure\n            moment and the beginning of the next one.\n            ', tunable_type=float, default_lower=8, default_upper=12, minimum=0), '_maximum_triggers': Tunable(description='\n            The maximum number of adventure moments that can be triggered by\n            this adventure. Any moment being generated from the adventure beyond\n            this limit will be discarded. Set to 0 to allow for an unlimited\n            number of adventure moments to be triggered.\n            ', tunable_type=int, default=0), '_resumable': Tunable(description='\n            A Sim who enters a resumable adventure will restart the same\n            adventure at the moment they left it at.\n            ', tunable_type=bool, needs_tuning=True, default=True)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._adventure_moment_count = 0
        self._alarm_handle = None
        self._canceled = False

    def _build_outer_elements(self, sequence):
        return build_critical_section_with_finally(sequence, self._end_adventure)

    def _end_adventure(self, *_, **__):
        if self._alarm_handle is not None:
            cancel_alarm(self._alarm_handle)
            self._alarm_handle = None

    def _soft_stop(self):
        self._canceled = True
        return super()._soft_stop()

    @property
    def tracker(self):
        return self.interaction.sim.sim_info.adventure_tracker

    def queue_adventure_moment(self, adventure_moment_key):
        if self._maximum_triggers and self._adventure_moment_count >= self._maximum_triggers:
            return
        time_span = clock.interval_in_sim_minutes(self._trigger_interval.random_float())

        def callback(alarm_handle):
            self._alarm_handle = None
            if not self._canceled:
                self.tracker.remove_adventure_moment(self.interaction)
                self._run_adventure_moment(adventure_moment_key)

        self.tracker.set_adventure_moment(self.interaction, adventure_moment_key)
        self._alarm_handle = add_alarm(self, time_span, callback)

    def _run_adventure_moment(self, adventure_moment_key):
        adventure_moment = self._adventure_moments.get(adventure_moment_key)
        if adventure_moment is not None:
            adventure_moment(self).run_adventure()

    def _get_initial_adventure_moment_key(self):
        initial_adventure_moment_key = _initial_adventure_moment_key_overrides.get(self.interaction.sim)
        if initial_adventure_moment_key is not None:
            return initial_adventure_moment_key
        if self._resumable:
            initial_adventure_moment_key = self.tracker.get_adventure_moment(self.interaction)
            if initial_adventure_moment_key is not None:
                return initial_adventure_moment_key
        participant_resolver = self.interaction.get_resolver()
        return weighted_random_item([(moment.weight.get_multiplier(participant_resolver), moment.adventure_moment_key) for moment in self._initial_moments])

    def _do_behavior(self):
        self._run_adventure_moment(self._get_initial_adventure_moment_key())

