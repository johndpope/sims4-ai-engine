from collections import defaultdict
from weakref import WeakSet
import random
from event_testing.resolver import SingleObjectResolver, InteractionResolver
from event_testing.results import TestResult
from event_testing.test_variants import ObjectTypeFactory, ObjectTagFactory
from event_testing.tests import TunableTestSet
from filters.tunable import TunableSimFilter
from interactions import ParticipantType
from interactions.aop import AffordanceObjectPair
from interactions.base.immediate_interaction import ImmediateSuperInteraction
from interactions.base.interaction import InteractionQueueVisualType
from interactions.base.mixer_interaction import MixerInteraction
from interactions.base.picker_strategy import SimPickerEnumerationStrategy, LotPickerEnumerationStrategy, ObjectPickerEnumerationStrategy
from interactions.base.super_interaction import SuperInteraction
from interactions.base.tuningless_interaction import create_tuningless_interaction
from interactions.context import InteractionContext, QueueInsertStrategy
from interactions.utils.outcome import InteractionOutcome
from interactions.utils.tunable import TunableContinuation
from objects.components.inventory_enums import InventoryType
from objects.terrain import get_venue_instance_from_pick_location, get_zone_id_from_pick_location
from sims4.localization import TunableLocalizedStringFactory, LocalizationHelperTuning
from sims4.tuning.geometric import TunableDistanceSquared
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import TunableEnumEntry, OptionalTunable, TunableVariant, Tunable, TunableTuple, TunableReference, TunableSet, TunableList, TunableFactory
from sims4.tuning.tunable_base import GroupNames
from sims4.utils import flexmethod
from singletons import DEFAULT
from snippets import TunableVenueListReference
from ui.ui_dialog import PhoneRingType
from ui.ui_dialog_notification import TunableUiDialogNotificationSnippet
from ui.ui_dialog_picker import logger, TunablePickerDialogVariant, SimPickerRow, ObjectPickerRow, ObjectPickerTuningFlags, PurchasePickerRow, LotPickerRow
import build_buy
import enum
import event_testing.results
import services
import sims
import sims4.localization
import tag

class PickerMixerInteraction(MixerInteraction):
    __qualname__ = 'PickerMixerInteraction'
    INSTANCE_SUBCLASSES_ONLY = True

    def __init__(self, *args, row_data=None, pie_menu_name=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.row_data = row_data
        self.pie_menu_name = pie_menu_name

    @flexmethod
    def get_pie_menu_category(cls, inst, pie_menu_category=None, **interaction_parameters):
        if inst is not None:
            return inst.pie_menu_category
        return pie_menu_category

    @flexmethod
    def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, row_data=None, pie_menu_name=None, **interaction_parameters):
        inst_or_cls = inst if inst is not None else cls
        context = inst_or_cls.context if context is DEFAULT else context
        target = inst_or_cls.target if target is DEFAULT else target
        row_data = inst.row_data if inst is not None else row_data
        pie_menu_name = inst.pie_menu_name if inst is not None else pie_menu_name
        if row_data is not None:
            display_name = inst_or_cls.create_localized_string(pie_menu_name, row_data.name, target=target, context=context, **interaction_parameters)
            price = getattr(row_data, 'price', 0)
            if price > 0:
                display_name = inst_or_cls.SIMOLEON_COST_NAME_FACTORY(display_name, price)
            return display_name
        return super(MixerInteraction, inst_or_cls)._get_name(target=target, context=context, **interaction_parameters)

    @flexmethod
    def get_icon_info(cls, inst, *args, **kwargs):
        if inst is not None:
            si = inst.super_interaction
            if si is not None:
                return si.get_icon_info(*args, **kwargs)
            sa = inst.super_affordance
            if sa is not None:
                return sa.get_icon_info(target=inst.target, context=inst.context)
        inst_or_cls = inst if inst is not None else cls
        return super(MixerInteraction, inst_or_cls).get_icon_info(*args, **kwargs)

    def perform_gen(self, timeline):
        (result, failure_reason) = yield super().perform_gen(timeline)
        if result:
            si = self.super_interaction
            if si is not None:
                si.on_choice_selected(self.row_data.tag, ingredient_data=self._kwargs.get('recipe_ingredients_map'))
        return (result, failure_reason)

def create_picker_mixer_affordance(affordance):
    create_tuningless_interaction(affordance)
    lock_instance_tunables(affordance, visible=True, visual_type_override=InteractionQueueVisualType.SIMPLE, allow_user_directed=True, allow_from_sim_inventory=True)

create_picker_mixer_affordance(PickerMixerInteraction)

class PickerSuperInteractionMixin:
    __qualname__ = 'PickerSuperInteractionMixin'
    INSTANCE_TUNABLES = {'picker_dialog': TunablePickerDialogVariant(description='\n            The object picker dialog.\n            ', dialog_locked_args={'title': None}, tuning_group=GroupNames.PICKERTUNING), 'pie_menu_option': OptionalTunable(description='\n            Whether use Pie Menu to show choices other than picker dialog.', tunable=TunableTuple(show_disabled_item=Tunable(description='\n                    If set true, the disabled item will show as disabled in the\n                    Pie Menu with a greyed-out tooltip. Otherwise the disabled\n                    item will not show up in the pie menu.\n                    ', tunable_type=bool, needs_tuning=True, default=False), pie_menu_category=TunableReference(description='\n                    Pie menu category for pie menu mixers.\n                    ', manager=services.get_instance_manager(sims4.resources.Types.PIE_MENU_CATEGORY), tuning_group=GroupNames.UI), pie_menu_name=TunableLocalizedStringFactory(description="\n                    The localized name for the pie menu item. The content\n                    should always have {2.String} to wrap picker row data's\n                    name.\n                    ")), disabled_name='use_picker', enabled_name='use_pie_menu', tuning_group=GroupNames.PICKERTUNING), 'pie_menu_test_tooltip': OptionalTunable(description='\n            If enabled, then a greyed-out tooltip will be displayed if there\n            are no valid choices. When disabled, the test to check for valid\n            choices will run first and if it fail any other tuned test in the\n            interaction will not get run. When enabled, the tooltip will be the\n            last fallback tooltip, and if other tuned interaction tests have\n            tooltip, those tooltip will show first. [cjiang/scottd]\n            ', tunable=TunableLocalizedStringFactory(description='\n                The tooltip text to show in the greyed-out tooltip when no valid\n                choices exist.\n                '), tuning_group=GroupNames.PICKERTUNING)}

    @classmethod
    def _test(cls, *args, **kwargs):
        result = super()._test(*args, **kwargs)
        if not result:
            return result
        if not cls.has_valid_choice(*args, **kwargs):
            return event_testing.results.TestResult(False, 'This picker SI has no valid choices.', tooltip=cls.pie_menu_test_tooltip)
        return event_testing.results.TestResult.TRUE

    @flexmethod
    def _get_name(cls, inst, *args, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        text = super(__class__, inst_or_cls)._get_name(*args, **kwargs)
        if inst_or_cls._use_ellipsized_name():
            text = LocalizationHelperTuning.get_ellipsized_text(text)
        return text

    @flexmethod
    def _use_ellipsized_name(cls, inst):
        return True

    @classmethod
    def has_valid_choice(cls, target, context, **kwargs):
        return True

    @classmethod
    def use_pie_menu(cls):
        if cls.pie_menu_option is not None:
            return True
        return False

    def _show_picker_dialog(self, owner, **kwargs):
        if self.use_pie_menu():
            return
        dialog = self._create_dialog(owner, **kwargs)
        dialog.show_dialog()

    def _create_dialog(self, owner, target_sim=None, target=None, **kwargs):
        dialog = self.picker_dialog(owner, title=lambda *_, **__: self.get_name(apply_name_modifiers=False), resolver=self.get_resolver())
        self._setup_dialog(dialog, **kwargs)
        dialog.set_target_sim(target_sim)
        dialog.set_target(target)
        dialog.add_listener(self._on_picker_selected)
        return dialog

    @classmethod
    def has_pie_menu_sub_interactions(cls, target, context, **kwargs):
        if not cls.use_pie_menu():
            return False
        show_disabled_item = cls.pie_menu_option.show_disabled_item
        for row_data in cls.picker_rows_gen(target, context, **kwargs):
            if not row_data.available_as_pie_menu:
                pass
            if row_data.is_enable:
                return True
            while show_disabled_item:
                return True
        return False

    @classmethod
    def potential_pie_menu_sub_interactions_gen(cls, target, context, **kwargs):
        if cls.use_pie_menu():
            affordance = PickerMixerInteraction
            affordance.guid64 = sims4.hash_util.hash64(affordance.__name__)
            affordance.display_name_text_tokens = cls.display_name_text_tokens
            show_disabled_item = cls.pie_menu_option.show_disabled_item
            affordance_pie_menu_category = cls.pie_menu_option.pie_menu_category
            pie_menu_name = cls.pie_menu_option.pie_menu_name
            recipe_ingredients_map = {}
            for row_data in cls.picker_rows_gen(target, context, recipe_ingredients_map=recipe_ingredients_map, **kwargs):
                if not row_data.available_as_pie_menu:
                    pass
                test_result = None
                if row_data.is_enable:
                    test_result = TestResult(result=True, influence_by_active_mood=row_data.pie_menu_influence_by_active_mood)
                else:
                    tooltip = row_data.row_tooltip if show_disabled_item else None
                    test_result = TestResult(False, 'Picker row is not enabled', tooltip=tooltip)
                pie_menu_category = row_data.pie_menu_category or affordance_pie_menu_category
                for aop in affordance.potential_interactions(target, cls, None, row_data=row_data, push_super_on_prepare=True, pie_menu_category=pie_menu_category, pie_menu_name=pie_menu_name, recipe_ingredients_map=recipe_ingredients_map):
                    yield (aop, test_result)

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        raise NotImplementedError

    def _setup_dialog(self, dialog, **kwargs):
        for row in self.picker_rows_gen(self.target, self.context, **kwargs):
            dialog.add_row(row)

    def _on_picker_selected(self, dialog):
        tag_obj = dialog.get_single_result_tag()
        self.on_choice_selected(tag_obj, ingredient_check=dialog.ingredient_check)

    def on_choice_selected(self, picked_choice, **kwargs):
        raise NotImplementedError

class PickerSuperInteraction(PickerSuperInteractionMixin, ImmediateSuperInteraction):
    __qualname__ = 'PickerSuperInteraction'
    INSTANCE_SUBCLASSES_ONLY = True

    def __init__(self, *args, choice_enumeration_strategy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._choice_enumeration_strategy = choice_enumeration_strategy
        if self.allow_autonomous and self._choice_enumeration_strategy is None:
            logger.error('{} is a new PickerSuperInteraction that was added without also adding an appropriate ChoiceEnumerationStrategy.  The owner of this SI should set up a new strategy or use an existing one.  See me if you have any questions.'.format(self), owner='rez')

lock_instance_tunables(PickerSuperInteraction, outcome=InteractionOutcome())

class PickerSingleChoiceSuperInteraction(PickerSuperInteraction):
    __qualname__ = 'PickerSingleChoiceSuperInteraction'
    INSTANCE_SUBCLASSES_ONLY = True
    INSTANCE_TUNABLES = {'single_choice_display_name': OptionalTunable(tunable=TunableLocalizedStringFactory(description="\n                The name of the interaction if only one option is available. There\n                should be a single token for the item that's used. The token will\n                be replaced with the name of a Sim in Sim Pickers, or an object\n                for recipes, etc.\n                 \n                Picked Sim/Picked Object participants can be used as display\n                name tokens.\n                ", default=None), tuning_group=GroupNames.UI)}

    @classmethod
    def potential_interactions(cls, target, context, **kwargs):
        single_row = None
        if cls.single_choice_display_name is not None:
            (_, single_row) = cls.get_single_choice_and_row(context=context, target=target, **kwargs)
        picked_item_ids = () if single_row is None else (single_row.tag,)
        yield AffordanceObjectPair(cls, target, cls, None, picked_item_ids=picked_item_ids, picked_row=single_row, **kwargs)

    @flexmethod
    def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, picked_row=None, **interaction_parameters):
        inst_or_cls = inst if inst is not None else cls
        context = inst_or_cls.context if context is DEFAULT else context
        target = inst_or_cls.target if target is DEFAULT else target
        if inst_or_cls.single_choice_display_name is not None and picked_row is not None:
            return inst_or_cls.create_localized_string(inst_or_cls.single_choice_display_name, picked_row.name, target=target, context=context, **interaction_parameters)
        return super(PickerSingleChoiceSuperInteraction, inst_or_cls)._get_name(target=target, context=context, **interaction_parameters)

    @flexmethod
    def get_single_choice_and_row(cls, inst, context=None, target=None, **kwargs):
        return (None, None)

    def _show_picker_dialog(self, owner, target_sim=None, target=None, **kwargs):
        if self.use_pie_menu():
            return
        picked_item_ids = self.interaction_parameters.get('picked_item_ids')
        if picked_item_ids:
            self.on_choice_selected(picked_item_ids)
        else:
            dialog = self._create_dialog(owner, target_sim=None, target=target, **kwargs)
            dialog.show_dialog()

class AutonomousPickerSuperInteraction(SuperInteraction):
    __qualname__ = 'AutonomousPickerSuperInteraction'

    def __init__(self, *args, choice_enumeration_strategy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._choice_enumeration_strategy = choice_enumeration_strategy

lock_instance_tunables(AutonomousPickerSuperInteraction, allow_user_directed=False, basic_reserve_object=None, disable_transitions=True)

class SimPickerLinkContinuation(enum.Int):
    __qualname__ = 'SimPickerLinkContinuation'
    NEITHER = 0
    ACTOR = 1
    PICKED = 2
    ALL = 3

class SimPickerMixin:
    __qualname__ = 'SimPickerMixin'
    INSTANCE_TUNABLES = {'actor_continuation': TunableContinuation(description='\n            If specified, a continuation to push on the actor when a picker \n            selection has been made.', locked_args={'actor': ParticipantType.Actor}, tuning_group=GroupNames.PICKERTUNING), 'picked_continuation': TunableContinuation(description='\n            If specified, a continuation to push on each sim selected in the \n            picker.', locked_args={'actor': ParticipantType.Actor}, tuning_group=GroupNames.PICKERTUNING), 'link_continuation': TunableEnumEntry(description='\n            Which, if any, continuation should cancel if the other interaction\n            is canceled.\n            \n            e.g. if "ACTOR" is selected, then if any of the picked continuation\n            is canceled the actor continuation will also be canceled.\n            ', tunable_type=SimPickerLinkContinuation, default=SimPickerLinkContinuation.NEITHER, tuning_group=GroupNames.PICKERTUNING), 'sim_filter': OptionalTunable(description='\n            Optional Sim Filter to run Sims through. Otherwise we will just get all Sims that pass the tests.', tunable=TunableSimFilter.TunableReference(description='Sim Filter to run all Sims through before tests.'), disabled_name='no_filter', enabled_name='sim_filter_selected', needs_tuning=True, tuning_group=GroupNames.PICKERTUNING), 'sim_tests': event_testing.tests.TunableTestSet(description='\n            A set of tests that are run against the prospective sims. At\n            least one test must pass in order for the prospective sim to show.\n            All sims will pass if there are no tests.\n            Picked_sim is the participant type for the prospective sim.\n            ', tuning_group=GroupNames.PICKERTUNING), 'include_uninstantiated_sims': Tunable(description='\n            If unchecked, uninstantiated sims will never be available in the picker.\n            if checked, they must still pass the filters and tests\n            This is an optimization tunable.\n            ', tunable_type=bool, default=True, tuning_group=GroupNames.PICKERTUNING)}

    @flexmethod
    def _get_requesting_sim_info_for_picker(cls, inst, context, **kwargs):
        return context.sim.sim_info

    @flexmethod
    def _get_valid_sim_choices(cls, inst, target, context, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        sim_constraints = []
        blacklist_sim_ids = set()
        requesting_sim_info = inst_or_cls._get_requesting_sim_info_for_picker(context, **kwargs)
        blacklist_sim_ids.add(requesting_sim_info.id)
        if not inst_or_cls.include_uninstantiated_sims:
            sim_constraints = [sim_info.id for sim_info in services.sim_info_manager().instanced_sims_gen()]
        filtered_sims = services.sim_filter_service().submit_filter(inst_or_cls.sim_filter, None, sim_constraints=sim_constraints if sim_constraints else None, requesting_sim_info=requesting_sim_info, blacklist_sim_ids=blacklist_sim_ids, allow_yielding=False)
        if not inst_or_cls.sim_tests:
            return filtered_sims
        results = []
        interaction_parameters = {}
        if inst:
            interaction_parameters = inst.interaction_parameters.copy()
        for choice in filtered_sims:
            interaction_parameters['picked_item_ids'] = {choice.sim_info.id}
            resolver = InteractionResolver(cls, inst, target=target, context=context, **interaction_parameters)
            while inst_or_cls.sim_tests.run_tests(resolver):
                results.append(choice)
        return results

    def _push_continuations(self, sim_ids, zone_datas=None):
        if not self.picked_continuation:
            insert_strategy = QueueInsertStrategy.LAST
        else:
            insert_strategy = QueueInsertStrategy.NEXT
        picked_zone_set = None
        if zone_datas is not None:
            try:
                picked_zone_set = {zone_data.zone_id for zone_data in zone_datas if zone_data is not None}
            except TypeError:
                picked_zone_set = {zone_datas.zone_id}
            self.interaction_parameters['picked_zone_ids'] = frozenset(picked_zone_set)
        actor_continuation = None
        picked_continuations = []
        if self.actor_continuation:
            picked_item_set = {target_sim_id for target_sim_id in sim_ids if target_sim_id is not None}
            self.interaction_parameters['picked_item_ids'] = frozenset(picked_item_set)
            self.push_tunable_continuation(self.actor_continuation, insert_strategy=insert_strategy, picked_item_ids=picked_item_set, picked_zone_ids=picked_zone_set)
            new_continuation = self.sim.queue.find_pushed_interaction_by_id(self.group_id)
            while new_continuation is not None:
                actor_continuation = new_continuation
                new_continuation = self.sim.queue.find_continuation_by_id(actor_continuation.id)
        if self.picked_continuation:
            for target_sim_id in sim_ids:
                if target_sim_id is None:
                    pass
                logger.info('SimPicker: picked Sim_id: {}', target_sim_id, owner='jjacobson')
                target_sim = services.object_manager().get(target_sim_id)
                if target_sim is None:
                    logger.error("You must pick on lot sims for a tuned 'picked continuation' to function.", owner='jjacobson')
                self.interaction_parameters['picked_item_ids'] = frozenset((target_sim_id,))
                self.push_tunable_continuation(self.picked_continuation, insert_strategy=insert_strategy, actor=target_sim, picked_zone_ids=picked_zone_set)
                picked_continuation = target_sim.queue.find_pushed_interaction_by_id(self.group_id)
                while picked_continuation is not None:
                    new_continuation = target_sim.queue.find_continuation_by_id(picked_continuation.id)
                    while new_continuation is not None:
                        picked_continuation = new_continuation
                        new_continuation = target_sim.queue.find_continuation_by_id(picked_continuation.id)
                    picked_continuations.append(picked_continuation)
        if self.link_continuation != SimPickerLinkContinuation.NEITHER and actor_continuation is not None:
            while True:
                for interaction in picked_continuations:
                    if self.link_continuation == SimPickerLinkContinuation.ACTOR or self.link_continuation == SimPickerLinkContinuation.ALL:
                        interaction.attach_interaction(actor_continuation)
                    while self.link_continuation == SimPickerLinkContinuation.PICKED or self.link_continuation == SimPickerLinkContinuation.ALL:
                        actor_continuation.attach_interaction(interaction)

class SimPickerInteraction(SimPickerMixin, PickerSingleChoiceSuperInteraction):
    __qualname__ = 'SimPickerInteraction'
    INSTANCE_TUNABLES = {'picker_dialog': TunablePickerDialogVariant(description='The object picker dialog.', available_picker_flags=ObjectPickerTuningFlags.SIM, tuning_group=GroupNames.PICKERTUNING)}

    def __init__(self, *args, **kwargs):
        super().__init__(choice_enumeration_strategy=SimPickerEnumerationStrategy(), *args, **kwargs)

    def _run_interaction_gen(self, timeline):
        self._show_picker_dialog(self.sim, target_sim=self.sim, target=self.target)
        return True

    @flexmethod
    def create_row(cls, inst, tag):
        return SimPickerRow(sim_id=tag, tag=tag)

    @flexmethod
    def get_single_choice_and_row(cls, inst, context=None, target=None, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        if context is not None:
            choices = inst_or_cls._get_valid_sim_choices(target, context, **kwargs)
            if len(choices) == 1:
                sim_id = choices[0].sim_info.id
                return (choices[0].sim_info, inst_or_cls.create_row(sim_id))
        return (None, None)

    @classmethod
    def has_valid_choice(cls, target, context, **kwargs):
        if cls._get_valid_sim_choices(target, context, **kwargs):
            return True
        return False

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        for filter_result in inst_or_cls._get_valid_sim_choices(target, context, **kwargs):
            sim_id = filter_result.sim_info.id
            logger.info('SimPicker: add sim_id:{}', sim_id)
            row = inst_or_cls.create_row(sim_id)
            yield row

    def _on_picker_selected(self, dialog):
        if dialog.accepted:
            results = dialog.get_result_tags()
            if len(results) >= dialog.min_selectable:
                self._push_continuations(results)

    def on_choice_selected(self, choice_tag, **kwargs):
        sim = choice_tag
        if sim is not None:
            self._push_continuations(sim)

class PickerTravelHereSuperInteraction(SimPickerInteraction):
    __qualname__ = 'PickerTravelHereSuperInteraction'

    @flexmethod
    def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, **interaction_parameters):
        inst_or_cls = inst if inst is not None else cls
        target = inst_or_cls.target if target is DEFAULT else target
        context = inst_or_cls.context if context is DEFAULT else context
        venue_instance = get_venue_instance_from_pick_location(context.pick)
        zone_id = get_zone_id_from_pick_location(context.pick)
        if inst is not None:
            inst.interaction_parameters['picked_zone_ids'] = frozenset({zone_id})
        if venue_instance is not None:
            return venue_instance.travel_with_interaction_name(target, context)
        return super(__class__, inst_or_cls)._get_name(target=target, context=context, **interaction_parameters)

    @flexmethod
    def _get_valid_sim_choices(cls, inst, target, context, **kwargs):
        filter_results = super()._get_valid_sim_choices(target, context, **kwargs)
        zone_id = get_zone_id_from_pick_location(context.pick)
        not_at_destination_results = []
        for filter_result in filter_results:
            while not filter_result.sim_info.zone_id == zone_id:
                not_at_destination_results.append(filter_result)
        return not_at_destination_results

    @flexmethod
    def get_single_choice_and_row(cls, inst, context=None, target=None, **kwargs):
        return (None, None)

    def _on_picker_selected(self, dialog):
        results = dialog.get_result_tags()
        if results:
            zone_ids = self.interaction_parameters['picked_zone_ids']
            zone_datas = []
            for zone_id in zone_ids:
                zone_data = services.get_persistence_service().get_zone_proto_buff(zone_id)
                while zone_data is not None:
                    zone_datas.append(zone_data)
            self._push_continuations(results, zone_datas=zone_datas)

lock_instance_tunables(PickerTravelHereSuperInteraction, single_choice_display_name=None)

class AutonomousSimPickerSuperInteraction(SimPickerMixin, AutonomousPickerSuperInteraction):
    __qualname__ = 'AutonomousSimPickerSuperInteraction'

    def __init__(self, *args, **kwargs):
        super().__init__(choice_enumeration_strategy=SimPickerEnumerationStrategy(), *args, **kwargs)

    @classmethod
    def _test(cls, target, context, **interaction_parameters):
        if not cls.has_valid_choice(target, context, **interaction_parameters):
            return event_testing.results.TestResult(False, 'This picker SI has no valid choices.')
        return super()._test(target, context, **interaction_parameters)

    def _run_interaction_gen(self, timeline):
        self._choice_enumeration_strategy.build_choice_list(self, self.sim)
        chosen_sim = (self._choice_enumeration_strategy.find_best_choice(self),)
        self._push_continuations(chosen_sim)
        return True

    @classmethod
    def has_valid_choice(cls, target, context, **kwargs):
        if cls._get_valid_sim_choices(target, context, **kwargs):
            return True
        return False

class LotPickerMixin:
    __qualname__ = 'LotPickerMixin'
    INSTANCE_TUNABLES = {'default_inclusion': TunableVariant(description='\n            This defines which venue types are valid for this picker.\n            ', include_all=TunableTuple(description='\n                This will allow all venue types to be valid, except those blacklisted.\n                ', include_all_by_default=Tunable(bool, True), exclude_venues=TunableList(tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.VENUE), tuning_group=GroupNames.VENUES), display_name='Blacklist Items'), exclude_lists=TunableList(TunableVenueListReference(), display_name='Blacklist Lists'), locked_args={'include_all_by_default': True}), exclude_all=TunableTuple(description='\n                This will prevent all venue types from being valid, except those whitelisted.\n                ', include_all_by_default=Tunable(bool, False), include_venues=TunableList(tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.VENUE), tuning_group=GroupNames.VENUES), display_name='Whitelist Items'), include_lists=TunableList(TunableVenueListReference(), display_name='Whitelist Lists'), locked_args={'include_all_by_default': False}), default='include_all', tuning_group=GroupNames.PICKERTUNING), 'include_actor_home_lot': Tunable(description='\n            If checked, the actors home lot will always be included regardless\n            of venue tuning.  If unchecked, it will NEVER be included.\n            ', tunable_type=bool, default=False, tuning_group=GroupNames.PICKERTUNING), 'include_target_home_lot': Tunable(description='\n            If checked, the target(s) home lot will always be included regardless\n            of venue tuning.  If unchecked, it will NEVER be included.\n            ', tunable_type=bool, default=False, tuning_group=GroupNames.PICKERTUNING), 'include_active_lot': Tunable(description='\n            If checked, the active lot may or may not appear based on \n            venue/situation tuning. If not checked, the active lot will always \n            be excluded.\n            ', tunable_type=bool, default=False, tuning_group=GroupNames.PICKERTUNING)}

    @flexmethod
    def _get_valid_lot_choices(cls, inst, target, context, target_list=None):
        inst_or_cls = inst if inst is not None else cls
        actor = context.sim
        target_zone_ids = []
        actor_zone_id = actor.household.home_zone_id
        results = []
        if target_list is None:
            target_zone_ids.append(target.household.home_zone_id)
        else:
            sim_info_manager = services.sim_info_manager()
            for target_sim_id in target_list:
                target_sim_info = sim_info_manager.get(target_sim_id)
                while target_sim_info is not None and target_sim_info.household is not None:
                    target_zone_ids.append(target_sim_info.household.home_zone_id)
        venue_manager = services.get_instance_manager(sims4.resources.Types.VENUE)
        active_zone_id = services.current_zone().id
        for zone_data in services.get_persistence_service().zone_proto_buffs_gen():
            zone_id = zone_data.zone_id
            if not inst_or_cls.include_active_lot and zone_id == active_zone_id:
                pass
            if zone_id == actor_zone_id:
                while inst_or_cls.include_actor_home_lot:
                    results.append(zone_data)
                    if zone_id in target_zone_ids:
                        while inst_or_cls.include_target_home_lot:
                            results.append(zone_data)
                            venue_type_id = build_buy.get_current_venue(zone_id)
                            if venue_type_id is None:
                                pass
                            venue_type = venue_manager.get(venue_type_id)
                            if venue_type is None:
                                pass
                            default_inclusion = inst_or_cls.default_inclusion
                            if inst_or_cls.default_inclusion.include_all_by_default:
                                if venue_type in default_inclusion.exclude_venues:
                                    pass
                                if any(venue_type in venue_list for venue_list in default_inclusion.exclude_lists):
                                    pass
                                results.append(zone_data)
                            elif venue_type in default_inclusion.include_venues:
                                results.append(zone_data)
                            else:
                                while any(venue_type in venue_list for venue_list in default_inclusion.include_lists):
                                    results.append(zone_data)
                    venue_type_id = build_buy.get_current_venue(zone_id)
                    if venue_type_id is None:
                        pass
                    venue_type = venue_manager.get(venue_type_id)
                    if venue_type is None:
                        pass
                    default_inclusion = inst_or_cls.default_inclusion
                    if inst_or_cls.default_inclusion.include_all_by_default:
                        if venue_type in default_inclusion.exclude_venues:
                            pass
                        if any(venue_type in venue_list for venue_list in default_inclusion.exclude_lists):
                            pass
                        results.append(zone_data)
                    elif venue_type in default_inclusion.include_venues:
                        results.append(zone_data)
                    else:
                        while any(venue_type in venue_list for venue_list in default_inclusion.include_lists):
                            results.append(zone_data)
            if zone_id in target_zone_ids:
                while inst_or_cls.include_target_home_lot:
                    results.append(zone_data)
                    venue_type_id = build_buy.get_current_venue(zone_id)
                    if venue_type_id is None:
                        pass
                    venue_type = venue_manager.get(venue_type_id)
                    if venue_type is None:
                        pass
                    default_inclusion = inst_or_cls.default_inclusion
                    if inst_or_cls.default_inclusion.include_all_by_default:
                        if venue_type in default_inclusion.exclude_venues:
                            pass
                        if any(venue_type in venue_list for venue_list in default_inclusion.exclude_lists):
                            pass
                        results.append(zone_data)
                    elif venue_type in default_inclusion.include_venues:
                        results.append(zone_data)
                    else:
                        while any(venue_type in venue_list for venue_list in default_inclusion.include_lists):
                            results.append(zone_data)
            venue_type_id = build_buy.get_current_venue(zone_id)
            if venue_type_id is None:
                pass
            venue_type = venue_manager.get(venue_type_id)
            if venue_type is None:
                pass
            default_inclusion = inst_or_cls.default_inclusion
            if inst_or_cls.default_inclusion.include_all_by_default:
                if venue_type in default_inclusion.exclude_venues:
                    pass
                if any(venue_type in venue_list for venue_list in default_inclusion.exclude_lists):
                    pass
                results.append(zone_data)
            elif venue_type in default_inclusion.include_venues:
                results.append(zone_data)
            else:
                while any(venue_type in venue_list for venue_list in default_inclusion.include_lists):
                    results.append(zone_data)
        return results

class LotPickerInteraction(LotPickerMixin, PickerSuperInteraction):
    __qualname__ = 'LotPickerInteraction'
    INSTANCE_TUNABLES = {'picker_dialog': TunablePickerDialogVariant(description='The object picker dialog.', available_picker_flags=ObjectPickerTuningFlags.LOT, tuning_group=GroupNames.PICKERTUNING), 'actor_continuation': TunableContinuation(description='\n            If specified, a continuation to push on the actor when a picker \n            selection has been made.', locked_args={'actor': ParticipantType.Actor}, tuning_group=GroupNames.PICKERTUNING), 'target_continuation': TunableContinuation(description='\n            If specified, a continuation to push on the sim targetted', locked_args={'actor': ParticipantType.Actor}, tuning_group=GroupNames.PICKERTUNING)}

    def _push_continuations(self, zone_datas):
        if not self.target_continuation:
            insert_strategy = QueueInsertStrategy.LAST
        else:
            insert_strategy = QueueInsertStrategy.NEXT
        try:
            picked_zone_set = {zone_data.zone_id for zone_data in zone_datas if zone_data is not None}
        except TypeError:
            picked_zone_set = {zone_datas.zone_id}
        self.interaction_parameters['picked_zone_ids'] = frozenset(picked_zone_set)
        if self.actor_continuation:
            self.push_tunable_continuation(self.actor_continuation, insert_strategy=insert_strategy, picked_zone_ids=picked_zone_set)
        if self.target_continuation:
            self.push_tunable_continuation(self.target_continuation, insert_strategy=insert_strategy, actor=self.target, picked_zone_ids=picked_zone_set)

    def __init__(self, *args, **kwargs):
        super().__init__(choice_enumeration_strategy=LotPickerEnumerationStrategy(), *args, **kwargs)

    def _run_interaction_gen(self, timeline):
        self._show_picker_dialog(self.sim, target_sim=self.sim, target=self.target)
        return True

    @flexmethod
    def create_row(cls, inst, tag):
        return LotPickerRow(zone_data=tag, tag=tag)

    @classmethod
    def has_valid_choice(cls, target, context, **kwargs):
        if cls._get_valid_lot_choices(target, context):
            return True
        return False

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        for filter_result in inst_or_cls._get_valid_lot_choices(target, context):
            logger.info('LotPicker: add zone_data:{}', filter_result)
            yield LotPickerRow(zone_data=filter_result, tag=filter_result)

    def _on_picker_selected(self, dialog):
        results = dialog.get_result_tags()
        if results:
            self._push_continuations(results)

    def on_choice_selected(self, choice_tag, **kwargs):
        result = choice_tag
        if result is not None:
            self._push_continuations(result)

class SimAndLotPickerInteraction(LotPickerMixin, SimPickerInteraction):
    __qualname__ = 'SimAndLotPickerInteraction'
    INSTANCE_TUNABLES = {'lot_picker_dialog': TunablePickerDialogVariant(description='The object picker dialog.', available_picker_flags=ObjectPickerTuningFlags.LOT, tuning_group=GroupNames.PICKERTUNING)}

    @classmethod
    def has_valid_choice(cls, target, context, **kwargs):
        if not cls._get_valid_sim_choices(target, context, **kwargs):
            return False
        if cls.include_target_home_lot or cls._get_valid_lot_choices(target, context):
            return True
        return False

    def _on_picker_selected(self, dialog):
        self._sim_results = dialog.get_result_tags()
        if self._sim_results:
            self._show_lot_picker_dialog(self.sim, target_sim=self.sim, target=self.target)

    def on_choice_selected(self, choice_tag, **kwargs):
        self._sim_results = choice_tag
        if self._sim_results is not None:
            self._show_lot_picker_dialog(self.sim, target_sim=self.sim, target=self.target)

    def _show_lot_picker_dialog(self, owner, target_sim=None, target=None, **kwargs):
        dialog = self._create_lot_dialog(owner, target_sim=None, target=None, **kwargs)
        dialog.show_dialog()

    def _create_lot_dialog(self, owner, target_sim=None, target=None, **kwargs):
        dialog = self.lot_picker_dialog(owner, resolver=self.get_resolver())
        self._setup_lot_dialog(dialog, **kwargs)
        dialog.set_target_sim(target_sim)
        dialog.set_target(target)
        dialog.add_listener(self._on_lot_picker_selected)
        return dialog

    @flexmethod
    def lot_picker_rows_gen(cls, inst, target, context, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        target_list = None
        if inst is not None:
            target_list = inst._sim_results
        for filter_result in inst_or_cls._get_valid_lot_choices(target, context, target_list=target_list):
            logger.info('LotPicker: add zone_data:{}', filter_result)
            yield LotPickerRow(zone_data=filter_result, tag=filter_result)

    def _setup_lot_dialog(self, dialog, **kwargs):
        for row in self.lot_picker_rows_gen(self.target, self.context, **kwargs):
            dialog.add_row(row)

    def _on_lot_picker_selected(self, dialog):
        lot_results = dialog.get_result_tags()
        if lot_results:
            self._push_continuations(self._sim_results, lot_results)

class MapViewPickerInteraction(LotPickerMixin, PickerSuperInteraction):
    __qualname__ = 'MapViewPickerInteraction'
    INSTANCE_TUNABLES = {'picker_dialog': TunablePickerDialogVariant(description='\n            The object picker dialog.\n            ', available_picker_flags=ObjectPickerTuningFlags.MAP_VIEW, tuning_group=GroupNames.PICKERTUNING, dialog_locked_args={'text_cancel': None, 'text_ok': None, 'title': None, 'text': None, 'text_tokens': DEFAULT, 'icon': None, 'secondary_icon': None, 'phone_ring_type': PhoneRingType.NO_RING}), 'actor_continuation': TunableContinuation(description='\n            If specified, a continuation to push on the actor when a picker \n            selection has been made.\n            ', locked_args={'actor': ParticipantType.Actor}, tuning_group=GroupNames.PICKERTUNING), 'target_continuation': TunableContinuation(description='\n            If specified, a continuation to push on the sim targetted', tuning_group=GroupNames.PICKERTUNING)}

    def _push_continuations(self, zone_datas):
        if not self.target_continuation:
            insert_strategy = QueueInsertStrategy.LAST
        else:
            insert_strategy = QueueInsertStrategy.NEXT
        try:
            picked_zone_set = {zone_data.zone_id for zone_data in zone_datas if zone_data is not None}
        except TypeError:
            picked_zone_set = {zone_datas.zone_id}
        self.interaction_parameters['picked_zone_ids'] = frozenset(picked_zone_set)
        if self.actor_continuation:
            self.push_tunable_continuation(self.actor_continuation, insert_strategy=insert_strategy, picked_zone_ids=picked_zone_set)
        if self.target_continuation:
            self.push_tunable_continuation(self.target_continuation, insert_strategy=insert_strategy, actor=self.target, picked_zone_ids=picked_zone_set)

    def __init__(self, *args, **kwargs):
        super().__init__(choice_enumeration_strategy=LotPickerEnumerationStrategy(), *args, **kwargs)

    def _create_dialog(self, owner, target_sim=None, target=None, **kwargs):
        traveling_sims = []
        picked_sims = self.get_participants(ParticipantType.PickedSim)
        if picked_sims:
            traveling_sims = list(picked_sims)
        elif target is not None and target.is_sim and target is not self.sim:
            traveling_sims.append(target)
        dialog = self.picker_dialog(owner, title=lambda *_, **__: self.get_name(), resolver=self.get_resolver(), traveling_sims=traveling_sims)
        self._setup_dialog(dialog, **kwargs)
        dialog.set_target_sim(target_sim)
        dialog.set_target(target)
        dialog.add_listener(self._on_picker_selected)
        return dialog

    def _run_interaction_gen(self, timeline):
        self._show_picker_dialog(self.sim, target_sim=self.sim, target=self.target)
        return True

    @flexmethod
    def create_row(cls, inst, tag):
        return LotPickerRow(zone_data=tag, option_id=tag.zone_id, tag=tag)

    @classmethod
    def has_valid_choice(cls, target, context, **kwargs):
        if cls._get_valid_lot_choices(target, context):
            return True
        return False

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        for filter_result in inst_or_cls._get_valid_lot_choices(target, context):
            logger.info('LotPicker: add zone_data:{}', filter_result)
            yield LotPickerRow(zone_data=filter_result, option_id=filter_result.zone_id, tag=filter_result)

    def _on_picker_selected(self, dialog):
        results = dialog.get_result_tags()
        if results:
            self._push_continuations(results)

    def on_choice_selected(self, choice_tag, **kwargs):
        result = choice_tag
        if result is not None:
            self._push_continuations(result)

class ObjectPickerMixin:
    __qualname__ = 'ObjectPickerMixin'
    INSTANCE_TUNABLES = {'continuation': OptionalTunable(description='\n            If enabled, you can tune a continuation to be pushed.\n            PickedObject will be the object that was selected\n            ', tunable=TunableContinuation(description='\n                If specified, a continuation to push on the chosen object.'), tuning_group=GroupNames.PICKERTUNING), 'single_push_continuation': Tunable(description='\n            If enabled, only the first continuation that can be successfully\n            pushed will run. Otherwise, all continuations are pushed such that\n            they run in order.\n            ', tunable_type=bool, default=False, tuning_group=GroupNames.PICKERTUNING), 'auto_pick': Tunable(description='\n            If checked, this interaction will randomly pick one of the choices\n            available and push the continuation on it. It will be like the\n            interaction was run autonomously - no picker dialog will show up.\n            ', tunable_type=bool, default=False, tuning_group=GroupNames.PICKERTUNING)}

    @flexmethod
    def _use_ellipsized_name(cls, inst):
        inst_or_cls = inst if inst is not None else cls
        return not inst_or_cls.auto_pick

    @flexmethod
    def _get_objects_gen(cls, inst, target, context, **kwargs):
        raise NotImplementedError

    @classmethod
    def has_valid_choice(cls, target, context, **kwargs):
        for _ in cls._get_objects_gen(target, context):
            pass
        return False

    def _push_continuation(self, obj):
        if obj is not None and self.continuation is not None:
            picked_item_set = set()
            picked_item_set.add(obj.id)
            self.interaction_parameters['picked_item_ids'] = picked_item_set
            self.push_tunable_continuation(self.continuation, multi_push=not self.single_push_continuation, picked_item_ids=picked_item_set, insert_strategy=QueueInsertStrategy.LAST)

    @flexmethod
    def _test_continuation(cls, inst, row_data, context=DEFAULT, target=DEFAULT):
        inst_or_cls = inst if inst is not None else cls
        object_id = row_data.object_id
        if inst_or_cls.continuation is not None and object_id is not 0:
            picked_item_set = set()
            picked_item_set.add(object_id)
            result = event_testing.results.TestResult.TRUE
            resolver = inst_or_cls.get_resolver(target=target, context=context, picked_object=target, picked_item_ids=picked_item_set)
            for continuation in inst_or_cls.continuation:
                local_actors = resolver.get_participants(continuation.actor)
                for local_actor in local_actors:
                    if isinstance(local_actor, sims.sim_info.SimInfo):
                        local_actor = local_actor.get_sim_instance()
                        if local_actor is None:
                            result = event_testing.results.TestResult(False, "Actor isn't instantiated")
                    local_context = context.clone_for_sim(local_actor)
                    if continuation.carry_target is not None:
                        local_context.carry_target = resolver.get_participant(continuation.carry_target)
                    if continuation.target != ParticipantType.Invalid:
                        local_targets = resolver.get_participants(continuation.target)
                        local_target = next(iter(local_targets), None)
                    else:
                        local_target = None
                    if local_target is not None:
                        if local_target.is_sim:
                            if isinstance(local_target, sims.sim_info.SimInfo):
                                local_target = local_target.get_sim_instance()
                                if local_target.is_part:
                                    local_target = local_target.part_owner
                        elif local_target.is_part:
                            local_target = local_target.part_owner
                    affordance = continuation.affordance
                    if affordance.is_super:
                        result = local_actor.test_super_affordance(affordance, local_target, local_context, picked_object=target, picked_item_ids=picked_item_set)
                    else:
                        if continuation.si_affordance_override is not None:
                            super_affordance = continuation.si_affordance_override
                            super_interaction = None
                            push_super_on_prepare = True
                        else:
                            logger.error("Picker interaction doesn't have affordance override set for continuation", owner='nbaker')
                        aop = AffordanceObjectPair(affordance, local_target, super_affordance, super_interaction, picked_object=target, push_super_on_prepare=push_super_on_prepare, picked_item_ids=picked_item_set)
                        result = aop.test(local_context)
                    while result:
                        return result
            if not result:
                row_data.is_enable = False
                row_data.row_tooltip = result.tooltip

class ObjectPickerInteraction(ObjectPickerMixin, PickerSingleChoiceSuperInteraction):
    __qualname__ = 'ObjectPickerInteraction'
    INSTANCE_SUBCLASSES_ONLY = True
    INSTANCE_TUNABLES = {'picker_dialog': TunablePickerDialogVariant(description='\n            The object picker dialog.\n            ', available_picker_flags=ObjectPickerTuningFlags.OBJECT, tuning_group=GroupNames.PICKERTUNING)}

    @flexmethod
    def create_row(cls, inst, row_obj, context=DEFAULT, target=DEFAULT):
        name = None
        row_description = None
        icon = None
        if row_obj.has_custom_name():
            name = LocalizationHelperTuning.get_raw_text(row_obj.custom_name)
        elif row_obj.crafting_component is not None:
            crafting_process = row_obj.get_crafting_process()
            recipe = crafting_process.recipe
            name = recipe.get_recipe_name(crafting_process.crafter)
            row_description = recipe.recipe_description(crafting_process.crafter)
            icon = recipe.icon_override
        row = ObjectPickerRow(object_id=row_obj.id, name=name, row_description=row_description, icon=icon, def_id=row_obj.definition.id, count=row_obj.stack_count(), tag=row_obj)
        inst_or_cls = inst if inst is not None else cls
        inst_or_cls._test_continuation(row, context=context, target=target)
        return row

    @flexmethod
    def get_single_choice_and_row(cls, inst, context=DEFAULT, target=DEFAULT, **kwargs):
        if inst is not None:
            inst_or_cls = inst
        else:
            return (None, None)
        first_obj = None
        first_row = None
        for obj in inst_or_cls._get_objects_gen(target, context):
            if first_obj is not None and first_row is not None:
                return (None, None)
            row = inst_or_cls.create_row(obj, context=context, target=target)
            (first_obj, first_row) = (obj, row)
        return (first_obj, first_row)

    def _run_interaction_gen(self, timeline):
        if self.context.source != InteractionContext.SOURCE_PIE_MENU or self.auto_pick:
            choices = list(self._get_objects_gen(self.target, self.context))
            if choices:
                obj = random.choice(choices)
                self._push_continuation(obj)
                return True
            return False
        self._show_picker_dialog(self.sim, target_sim=self.sim)
        return True

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        for obj in inst_or_cls._get_objects_gen(target, context):
            row = inst_or_cls.create_row(obj, context=context, target=target)
            yield row

    def on_choice_selected(self, choice_tag, **kwargs):
        obj = choice_tag
        if obj is not None:
            self._push_continuation(obj)

class AutonomousObjectPickerInteraction(ObjectPickerMixin, AutonomousPickerSuperInteraction):
    __qualname__ = 'AutonomousObjectPickerInteraction'
    INSTANCE_SUBCLASSES_ONLY = True

    def __init__(self, *args, **kwargs):
        super().__init__(choice_enumeration_strategy=ObjectPickerEnumerationStrategy(), *args, **kwargs)

    @classmethod
    def _test(cls, target, context, **interaction_parameters):
        if not cls.has_valid_choice(target, context, **interaction_parameters):
            return event_testing.results.TestResult(False, 'This picker SI has no valid choices.')
        return super()._test(target, context, **interaction_parameters)

    def _run_interaction_gen(self, timeline):
        self._choice_enumeration_strategy.build_choice_list(self, self.sim)
        chosen_obj = self._choice_enumeration_strategy.find_best_choice(self)
        self._push_continuation(chosen_obj)
        return True

class ObjectInInventoryPickerMixin:
    __qualname__ = 'ObjectInInventoryPickerMixin'
    INSTANCE_TUNABLES = {'inventory_subject': TunableEnumEntry(description='\n            Subject on which the inventory exists.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor, tuning_group=GroupNames.PICKERTUNING), 'inventory_item_test': TunableVariant(default='object', tuning_group=GroupNames.PICKERTUNING, object=ObjectTypeFactory(), tag_set=ObjectTagFactory(), description='\n                A test to run on the objects in the inventory to determine\n                which objects will show up in the picker. An object test type\n                left un-tuned is considered any object.\n                '), 'additional_item_test': TunableTestSet(description='\n            A set of tests to run on each object in the inventory that passes the\n            inventory_item_test. Each object must pass first the inventory_item_test\n            and then the additional_item_test before it will be shown in the picker dialog.\n            Only tests with ParticipantType.Object will work\n            ', tuning_group=GroupNames.PICKERTUNING)}

    @flexmethod
    def _get_objects_gen(cls, inst, target, context, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        inventory_subject = inst_or_cls.get_participant(participant_type=inst_or_cls.inventory_subject, sim=context.sim, target=target, **kwargs)
        if inventory_subject is not None and inventory_subject.inventory_component is not None:
            for obj in inventory_subject.inventory_component:
                if not inst_or_cls.inventory_item_test(obj):
                    pass
                if inst_or_cls.additional_item_test:
                    resolver = SingleObjectResolver(obj)
                    if not inst_or_cls.additional_item_test.run_tests(resolver):
                        pass
                yield obj

class ObjectInInventoryPickerInteraction(ObjectInInventoryPickerMixin, ObjectPickerInteraction):
    __qualname__ = 'ObjectInInventoryPickerInteraction'

class AutonomousObjectInInventoryPickerInteraction(ObjectInInventoryPickerMixin, AutonomousObjectPickerInteraction):
    __qualname__ = 'AutonomousObjectInInventoryPickerInteraction'

    @classmethod
    def should_autonomy_forward_to_inventory(cls):
        return True

class PieMenuPickerInteraction(PickerSuperInteraction):
    __qualname__ = 'PieMenuPickerInteraction'

    @flexmethod
    def _get_objects_gen(cls, inst, target, context, **kwargs):
        raise NotImplementedError

    def _run_interaction_gen(self, timeline):
        if self.context.source != InteractionContext.SOURCE_PIE_MENU:
            logger.error('PieMenuPickerInteraction can only be user directed.', owner='mduke')
            return False
        self._show_picker_dialog(self.sim, target_sim=self.sim)
        return True

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        for obj in inst_or_cls._get_objects_gen(target, context):
            row = ObjectPickerRow(object_id=obj.id, def_id=obj.definition.id)
            yield row

    def on_choice_selected(self, choice_tag, **kwargs):
        pass

class OpenInventory(PieMenuPickerInteraction):
    __qualname__ = 'OpenInventory'
    INSTANCE_TUNABLES = {'greyed_out_tooltip': sims4.localization.TunableLocalizedStringFactory(description='Tooltip shown if the inventory is empty.', tuning_group=GroupNames.PICKERTUNING)}

    @classmethod
    def _test(cls, target, context, **kwargs):
        if target.inventory_component:
            return event_testing.results.TestResult.TRUE
        return event_testing.results.TestResult(False, 'The Inventory is empty.', tooltip=cls.greyed_out_tooltip)

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        for obj in inst_or_cls._get_objects_gen(target, context):
            row = ObjectPickerRow(object_id=obj.id, def_id=obj.definition.id, count=obj.stack_count())
            yield row

    def _setup_dialog(self, dialog, **kwargs):
        super()._setup_dialog(dialog, **kwargs)
        self.sim.client.set_interaction_parameters(object_with_inventory=self.target, preferred_objects=WeakSet((self.context.pick.target,)))

    @flexmethod
    def _get_objects_gen(cls, inst, target, context, **kwargs):
        return iter(target.inventory_component)

    def on_choice_selected(self, choice_tag, **kwargs):
        self.sim.client.set_interaction_parameters()

class AllItems(TunableFactory):
    __qualname__ = 'AllItems'

    @staticmethod
    def factory(_, **kwargs):
        return services.definition_manager().loaded_definitions

    FACTORY_TYPE = factory

class SpecificItems(TunableFactory):
    __qualname__ = 'SpecificItems'

    @staticmethod
    def factory(_, item_list=[], **kwargs):
        return item_list

    FACTORY_TYPE = factory

    def __init__(self, *args, **kwargs):
        super().__init__(item_list=TunableList(description='\n                A list of item ids that the user will be able to purchase.\n                ', tunable=TunableReference(services.definition_manager())), **kwargs)

class ParticipantsPurchasableInventory(TunableFactory):
    __qualname__ = 'ParticipantsPurchasableInventory'

    @staticmethod
    def factory(inst_or_cls, participant_type=ParticipantType.Object, **interaction_kwargs):
        participant = inst_or_cls.get_participant(participant_type=participant_type, **interaction_kwargs)
        inventory_component = participant.inventory_component
        if inventory_component is None:
            return
        return inventory_component.purchasable_objects.objects

    FACTORY_TYPE = factory

    def __init__(self, *args, **kwargs):
        super().__init__(participant_type=TunableEnumEntry(description="\n                The participant type who's inventory will be used to ask for\n                the purchasable objects.\n                ", tunable_type=ParticipantType, default=ParticipantType.Object), **kwargs)

class ParticipantInventoryCount(TunableFactory):
    __qualname__ = 'ParticipantInventoryCount'

    @staticmethod
    def factory(interaction, definition, participant_type=ParticipantType.Object):
        participant = interaction.get_participant(participant_type)
        inventory_component = participant.inventory_component
        if inventory_component is None:
            return 0
        return inventory_component.get_count(definition)

    FACTORY_TYPE = factory

    def __init__(self, *args, **kwargs):
        super().__init__(participant_type=TunableEnumEntry(description="\n                The participant type who's inventory will be used to count the\n                number of objects owned of a specific definition.\n                ", tunable_type=ParticipantType, default=ParticipantType.Object), **kwargs)

class InventoryTypeCount(TunableFactory):
    __qualname__ = 'InventoryTypeCount'

    @staticmethod
    def factory(_, definition, inventory_type=InventoryType.UNDEFINED):
        inventory = services.active_lot().get_object_inventory(inventory_type)
        if inventory is None:
            return 0
        return inventory.get_count(definition)

    FACTORY_TYPE = factory

    def __init__(self, *args, **kwargs):
        super().__init__(inventory_type=TunableEnumEntry(description='\n                The type of inventory that is used to count the number of\n                objects owned of a specific definition.\n                ', tunable_type=InventoryType, default=InventoryType.UNDEFINED), **kwargs)

class PurchaseToInventory(TunableFactory):
    __qualname__ = 'PurchaseToInventory'

    @staticmethod
    def factory(interaction, participant_type=ParticipantType.Object):
        participant = interaction.get_participant(participant_type)
        return (participant.id, False)

    FACTORY_TYPE = factory

    def __init__(self, *args, **kwargs):
        super().__init__(participant_type=TunableEnumEntry(description="\n                The participant who's inventory we will put the purchased items\n                into.\n                ", tunable_type=ParticipantType, default=ParticipantType.Object), **kwargs)

class MailmanDelivery(TunableFactory):
    __qualname__ = 'MailmanDelivery'

    @staticmethod
    def factory(_):
        return (0, True)

    FACTORY_TYPE = factory

class PurchasePickerInteraction(PickerSuperInteraction):
    __qualname__ = 'PurchasePickerInteraction'
    INSTANCE_TUNABLES = {'object_populate_filter': OptionalTunable(description='\n            An optional filter that if enabled will filter out the allowed items\n            based on the filter.\n            ', tunable=TunableSet(description='\n                A list of category tags to to search to build object picker\n                list.\n                ', tunable=TunableEnumEntry(description='\n                    What tag to test for\n                    ', tunable_type=tag.Tag, default=tag.Tag.INVALID)), disabled_name='no_filter', enabled_name='filter_tags', tuning_group=GroupNames.PICKERTUNING), 'purchase_list_option': TunableVariant(description='\n            The method that will be used to generate the list of objects that\n            will populate the picker.\n            ', all_items=AllItems(description='\n                Look through all the items that are possible to purchase.\n                \n                This should be accompanied with specific filtering tags in\n                Object Populate Filter to get a good result.\n                '), specific_items=SpecificItems(description='\n                A list of specific items that will be puchasable through this\n                dialog.\n                '), participants_purchasable_inventory=ParticipantsPurchasableInventory(description='\n                Looks at the purchasable objects that are on the inventory\n                component of the target of this interaction and uses those as\n                the items that can be purchased through this picker.\n                '), default='participants_purchasable_inventory', tuning_group=GroupNames.PICKERTUNING), 'purchase_notification': OptionalTunable(description='\n            If enabled, a notification is displayed should the purchase picker\n            dialog be accepted.\n            ', tunable=TunableUiDialogNotificationSnippet(description='\n                The notification to show when the purchase picker dialog is\n                accepted.\n                '), tuning_group=GroupNames.PICKERTUNING), 'object_count_option': OptionalTunable(description='\n            If enabled then we will display a count next to each item of the\n            number owned.\n            ', tunable=TunableList(description='\n                A list of methods to used to count the number of instances of\n                specific objects.\n                ', tunable=TunableVariant(description='\n                    The method that will be used to determine the object count\n                    that is displayed in the UI next to each item.\n                    ', participant_inventory_count=ParticipantInventoryCount(description="\n                        We will count through the number of objects that are in\n                        the target's inventory and display that as the number\n                        owned in the UI.\n                        "), inventory_type_count=InventoryTypeCount(description='\n                        We will count through the number of objects that are in\n                        a specific inventory type (for example fridges) and\n                        display that as the number owned in the UI.\n                        '), default='participant_inventory_count')), tuning_group=GroupNames.PICKERTUNING), 'delivery_method': TunableVariant(description='\n            Where the objects purchased will be delivered.\n            ', purchase_to_inventory=PurchaseToInventory(description="\n                Purchase the objects directly into a participant's inventory.\n                "), mailman_delivery=MailmanDelivery(description='\n                Deliver the objects by the mailman.\n                '), default='purchase_to_inventory', tuning_group=GroupNames.PICKERTUNING), 'show_descriptions': Tunable(description='\n            If True then we will show descriptions of the objects in the picker.\n            ', tunable_type=bool, default=True, tuning_group=GroupNames.PICKERTUNING)}

    def _run_interaction_gen(self, timeline):
        self._show_picker_dialog(self.sim)
        return True

    @classmethod
    def has_valid_choice(cls, target, context, **kwargs):
        items = cls.purchase_list_option(cls, target=target, context=context, sim=context.sim, **kwargs)
        if items:
            if not cls.object_populate_filter:
                return True
            for item in items:
                while item.build_buy_tags & cls.object_populate_filter:
                    return True
        return False

    def _setup_dialog(self, dialog, **kwargs):
        (inv_id, use_mailman) = self.delivery_method(self)
        dialog.object_id = inv_id
        dialog.mailman_purchase = use_mailman
        dialog.show_description = self.show_descriptions
        items = self.purchase_list_option(self)
        for item in items:
            tags = item.build_buy_tags
            if not (self.object_populate_filter and tags & self.object_populate_filter):
                pass
            if self.object_count_option is not None:
                count = sum(count_method(self, item) for count_method in self.object_count_option)
            else:
                count = 0
            row = PurchasePickerRow(def_id=item.id, num_owned=count, tags=tags)
            dialog.add_row(row)

    def _on_picker_selected(self, dialog):
        if dialog.accepted and self.purchase_notification is not None:
            notification_dialog = self.purchase_notification(self.sim, resolver=self.get_resolver())
            notification_dialog.show_dialog()

