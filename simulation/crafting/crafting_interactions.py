from collections import namedtuple
from protocolbuffers import Consts_pb2
from animation.posture_manifest import AnimationParticipant, SlotManifest, SlotManifestEntry
from animation.posture_manifest_constants import SIT_POSTURE_MANIFEST
from carry import enter_carry_while_holding, exit_carry_while_holding, SCRIPT_EVENT_ID_STOP_CARRY, SCRIPT_EVENT_ID_START_CARRY, PARAM_CARRY_TRACK
from carry.carry_interactions import PickUpObjectSuperInteraction
from carry.carry_postures import CarryingObject
from crafting.crafting_ingredients import Ingredient, IngredientTuning
from crafting.crafting_process import CraftingProcess, CRAFTING_QUALITY_LIABILITY
from crafting.crafting_tunable import CraftingTuning
from crafting.recipe import CraftingObjectType, Recipe, PhaseName, Phase
from distributor.shared_messages import IconInfoData
from distributor.system import Distributor
from element_utils import build_critical_section_with_finally, build_critical_section, unless, build_element
from event_testing.resolver import SingleSimResolver
from event_testing.results import TestResult, EnqueueResult, ExecuteResult
from interactions import ParticipantType, liability
from interactions.aop import AffordanceObjectPair
from interactions.base.basic import TunableBasicContentSet
from interactions.base.immediate_interaction import ImmediateSuperInteraction
from interactions.base.interaction import CancelInteractionsOnExitLiability, CANCEL_INTERACTION_ON_EXIT_LIABILITY, Interaction
from interactions.base.mixer_interaction import MixerInteraction
from interactions.base.picker_interaction import PickerSuperInteraction, AutonomousPickerSuperInteraction
from interactions.base.picker_strategy import RecipePickerEnumerationStrategy
from interactions.base.super_interaction import SuperInteraction
from interactions.constraints import Anywhere, Constraint, create_constraint_set
from interactions.interaction_finisher import FinishingType
from interactions.liability import Liability
from interactions.utils.animation import flush_all_animations
from interactions.utils.animation_reference import TunableAnimationReference
from interactions.utils.interaction_elements import ParentObjectElement
from interactions.utils.loot import create_loot_list
from interactions.utils.reserve import TunableReserveObject
from objects.components import types
from objects.components.state import state_change, TunableStateValueReference
from objects.components.types import CRAFTING_COMPONENT
from objects.helpers.create_object_helper import CreateObjectHelper
from objects.slots import SlotTypeReferences, get_surface_height_parameter_for_object
from objects.system import create_object
from postures.posture_specs import PostureSpecVariable
from postures.posture_state_spec import PostureStateSpec
from sims4.localization import TunableLocalizedStringFactory, LocalizationHelperTuning
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import TunableReference, TunableList, OptionalTunable, TunableEnumEntry, Tunable
from sims4.tuning.tunable_base import GroupNames
from sims4.utils import flexmethod, flexproperty, classproperty
from singletons import DEFAULT
from statistics.statistic_conditions import TunableStatisticCondition
from ui.ui_dialog_element import UiDialogElement
from ui.ui_dialog_generic import UiDialogTextInputOkCancel
from ui.ui_dialog_picker import RecipePickerRow, TunablePickerDialogVariant
import build_buy
import element_utils
import services
import sims4.log
import sims4.telemetry
import telemetry_helper
logger = sims4.log.Logger('Interactions')
TELEMETRY_GROUP_CRAFTING = 'CRFT'
TELEMETRY_HOOK_NEW_OBJECT = 'NOBJ'
TELEMETRY_FIELD_OBJECT_TYPE = 'obtp'
TELEMETRY_FIELD_OBJECT_QUALITY = 'qual'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_CRAFTING)

class StartCraftingMixin:
    __qualname__ = 'StartCraftingMixin'

    def __init__(self):
        self.orderer_ids = []

    def _set_orderers(self, sim):
        if self.is_party_crafting:
            main_group = sim.get_visible_group()
            if main_group:
                self.orderer_ids.extend(main_group.member_sim_ids_gen())
            else:
                self.orderer_ids.append(sim.id)
        else:
            self.orderer_ids.append(sim.id)

    def _handle_begin_crafting(self, recipe, crafter, ordering_sim=None, crafting_target=None, orderer_ids=DEFAULT, ingredients=()):
        if orderer_ids is DEFAULT:
            orderer_ids = []
        if recipe.use_ingredients and ingredients is not None:
            ingredients_required = len(recipe.use_ingredients.ingredient_list)
            ingredient_modifier = (ingredients_required - len(ingredients))/ingredients_required
        else:
            ingredient_modifier = 1
        if ordering_sim is not None and crafter is not ordering_sim:
            reserved_funds = ordering_sim.family_funds.try_remove(recipe.get_price(True, ingredient_modifier=ingredient_modifier)*len(orderer_ids), Consts_pb2.TELEMETRY_INTERACTION_COST, ordering_sim)
        else:
            reserved_funds = crafter.family_funds.try_remove(recipe.get_price(False, ingredient_modifier=ingredient_modifier)*len(orderer_ids), Consts_pb2.TELEMETRY_INTERACTION_COST, crafter)
        if reserved_funds is None:
            return
        if ingredients:
            ingredients_to_consume = self._get_ingredients_to_consume(ingredients)
            avg_quality_bonus = sum(ingredients_to_consume.values())/len(recipe.use_ingredients.ingredient_list)
            for ingredient_object in ingredients_to_consume.keys():
                inventory = ingredient_object.get_inventory()
                if inventory is not None:
                    inventory.try_remove_object_by_id(ingredient_object.id)
                    ingredient_object.destroy(source=crafter, cause='Consuming ingredients required to start crafting')
                else:
                    logger.error('Trying to consume ingredient {} thats not on an inventory.', ingredient_object, owner='camilogarcia')
        else:
            avg_quality_bonus = 0
        original_target = None
        if self.context.pick is not None:
            original_target = self.context.pick.target
        else:
            original_target = self.target
        self.crafting_process = CraftingProcess(self.context.sim, crafter, recipe, reserved_funds, orderer_ids=orderer_ids, original_target=original_target, ingredient_quality_bonus=avg_quality_bonus)
        result = self.crafting_process.push_si_for_first_phase(self, crafting_target)
        if not result:
            reserved_funds.cancel()
        return result

    def _get_ingredients_to_consume(self, ingredients):
        ingredients_to_consume = {}
        for ingredient_type in ingredients:
            obj_list = []
            for inventory in ingredient_type._inventory_locations:
                obj_list = inventory.get_list_object_by_definition(ingredient_type._definition)
            quality_level = -1000
            best_ingredient = None
            for ingredient in obj_list:
                ingredient_quality_bonus = IngredientTuning.get_quality_bonus(ingredient)
                while ingredient_quality_bonus >= quality_level:
                    quality_level = ingredient_quality_bonus
                    best_ingredient = ingredient
            while best_ingredient is not None:
                ingredients_to_consume[best_ingredient] = quality_level
        return ingredients_to_consume

IngredientDisplayData = namedtuple('IngredientDisplayData', ['ingredient_name', 'is_in_inventory'])

class StartCraftingSuperInteraction(PickerSuperInteraction, StartCraftingMixin):
    __qualname__ = 'StartCraftingSuperInteraction'
    INSTANCE_TUNABLES = {'recipes': TunableList(description='The recipes a Sim can craft.', tunable=TunableReference(description='Recipe to craft.', manager=services.recipe_manager(), reload_dependent=True)), 'is_party_crafting': Tunable(bool, False, description='Whether this crafting will create consumables for party'), 'create_unavailable_recipe_description': TunableLocalizedStringFactory(default=4228422038, tuning_group=GroupNames.UI), 'basic_reserve_object': TunableReserveObject(), 'use_ingredients_default_value': Tunable(description='\n            Default value if the interaction should use ingredients. \n            If this interaction is not using the recipe picker but the \n            interaction picker, this is the way to tune if a cooking \n            interaction will use ingredients or not.\n            ', tunable_type=bool, default=False, tuning_group=GroupNames.PICKERTUNING)}

    @classmethod
    def _tuning_loaded_callback(cls):
        super()._tuning_loaded_callback()
        for recipe in cls.recipes:
            recipe.validate_for_start_crafting()

    def __init__(self, *args, recipe_ingredients_map=None, **kwargs):
        choice_enumeration_strategy = RecipePickerEnumerationStrategy()
        PickerSuperInteraction.__init__(self, choice_enumeration_strategy=choice_enumeration_strategy, *args, **kwargs)
        self._recipe_ingredients_map = recipe_ingredients_map
        StartCraftingMixin.__init__(self)

    def _run_interaction_gen(self, timeline):
        self._set_orderers(self.sim)
        self._show_picker_dialog(self.sim, target_sim=self.sim, order_count=len(self.orderer_ids), crafter=self.sim)
        return True

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, crafter=DEFAULT, order_count=1, recipe_ingredients_map=None, **kwargs):
        if crafter is DEFAULT:
            crafter = context.sim
        fridge_inventory = services.active_lot().get_object_inventory(CraftingTuning.SHARED_FRIDGE_INVENTORY_TYPE)
        if crafter:
            sim_inventory = crafter.inventory_component
        else:
            sim_inventory = context.sim.inventory_component
        fridge_ingredients = {}
        sim_ingredients = {}
        if fridge_inventory is not None:
            for obj in fridge_inventory:
                while obj.definition.has_build_buy_tag(IngredientTuning.INGREDIENT_TAG):
                    fridge_ingredients[obj.definition] = fridge_inventory
        for obj in sim_inventory:
            while obj.definition.has_build_buy_tag(IngredientTuning.INGREDIENT_TAG):
                sim_ingredients[obj.definition] = sim_inventory
        recipe_list = []
        if inst is not None:
            inst._choice_enumeration_strategy.build_choice_list(inst)
            recipe_list = inst._choice_enumeration_strategy.choices
        else:
            recipe_list = cls.recipes
        if recipe_ingredients_map is None:
            recipe_ingredients_map = {}
        for recipe in recipe_list:
            adjusted_ingredient_price = 0
            ingredients_found_list = []
            ingredient_display_list = []
            if recipe.use_ingredients is not None:
                recipe_ingredients_map[recipe] = ingredients_found_list
                for tuned_ingredient_factory in recipe.use_ingredients.ingredient_list:
                    ingredient_instance = None
                    (fridge_ingredient_list, tag, ingredient_name) = tuned_ingredient_factory(fridge_ingredients)
                    for ingredient in fridge_ingredient_list:
                        if ingredient_instance is not None:
                            ingredient_instance.add_inventory_location(fridge_inventory)
                        else:
                            ingredient_instance = Ingredient(ingredient, inventory_location=fridge_inventory, catalog_tag=tag)
                            ingredient_display_list.append(IngredientDisplayData(ingredient_instance.get_diplay_name(), True))
                    (inventory_ingredient_list, tag, ingredient_name) = tuned_ingredient_factory(sim_ingredients)
                    for ingredient in inventory_ingredient_list:
                        if ingredient_instance is not None:
                            ingredient_instance.add_inventory_location(sim_inventory)
                        else:
                            ingredient_instance = Ingredient(ingredient, inventory_location=sim_inventory, catalog_tag=tag)
                            ingredient_display_list.append(IngredientDisplayData(ingredient_instance.get_diplay_name(), True))
                    if ingredient_instance:
                        recipe_ingredients_map[recipe].append(ingredient_instance)
                    elif tag is None:
                        ingredient_display_list.append(IngredientDisplayData(ingredient_name, False))
                    else:
                        ingredient_display_list.append(IngredientDisplayData(IngredientTuning.get_ingredient_string_for_tag(tag), False))
                ingredients_required = len(recipe.use_ingredients.ingredient_list)
                ingredients_found = len(ingredients_found_list)
                if recipe.use_ingredients.all_ingredients_required and ingredients_found < ingredients_required:
                    pass
                adjusted_ingredient_price = (ingredients_required - ingredients_found)/ingredients_required
            is_order_interaction = issubclass(cls, StartCraftingOrderSuperInteraction)
            price = recipe.get_price(is_order_interaction)
            price = price*order_count
            price_with_ingredients = recipe.get_price(is_order_interaction, adjusted_ingredient_price)*order_count
            if cls.use_ingredients_default_value:
                price = price_with_ingredients
            recipe_test_result = CraftingProcess.recipe_test(target, context, recipe, crafter, price)
            while recipe_test_result.visible:
                if recipe_test_result.errors:
                    if len(recipe_test_result.errors) > 1:
                        localized_error_string = LocalizationHelperTuning.get_bulleted_list(None, *recipe_test_result.errors)
                    else:
                        localized_error_string = recipe_test_result.errors[0]
                    description = cls.create_unavailable_recipe_description(localized_error_string)
                    tooltip = lambda *_, **__: cls.create_unavailable_recipe_description(localized_error_string)
                else:
                    description = recipe.recipe_description(crafter)
                    tooltip = lambda *_, **__: recipe.recipe_description(crafter)
                if recipe.has_final_product_definition:
                    recipe_icon = IconInfoData(icon_resource=recipe.icon_override, obj_def_id=recipe.final_product_definition_id, obj_geo_hash=recipe.final_product_geo_hash, obj_material_hash=recipe.final_product_material_hash)
                else:
                    recipe_icon = IconInfoData(recipe.icon_override)
                row = RecipePickerRow(name=recipe.get_recipe_name(crafter), price=price, icon=recipe.icon_override, row_description=description, row_tooltip=tooltip, skill_level=recipe.required_skill_level, is_enable=recipe_test_result.enabled, linked_recipe=recipe.base_recipe, display_name=recipe.get_recipe_picker_name(crafter), icon_info=recipe_icon, tag=recipe, ingredients=ingredient_display_list, price_with_ingredients=price_with_ingredients, pie_menu_influence_by_active_mood=recipe_test_result.influence_by_active_mood, mtx_id=recipe.entitlement)
                yield row
        if inst is not None:
            inst._recipe_ingredients_map = recipe_ingredients_map

    def _setup_dialog(self, dialog, crafter=DEFAULT, order_count=1, **kwargs):
        crafter = self.sim if crafter is DEFAULT else crafter
        dialog.set_target_sim(crafter)
        for row in self.picker_rows_gen(self.target, self.context, crafter=crafter, order_count=order_count, **kwargs):
            dialog.add_row(row)

    def on_choice_selected(self, choice_tag, ingredient_data=None, ingredient_check=None, **kwargs):
        recipe = choice_tag
        if recipe is not None:
            ingredients = None
            if ingredient_check or self.use_ingredients_default_value:
                if self._recipe_ingredients_map:
                    ingredients = self._recipe_ingredients_map.get(recipe)
                else:
                    ingredients = ingredient_data.get(recipe)
            return self._handle_begin_crafting(recipe, self.sim, orderer_ids=self.orderer_ids, ingredients=ingredients)
        return EnqueueResult.NONE

class StartCraftingOrderHandler:
    __qualname__ = 'StartCraftingOrderHandler'

    def __init__(self, orderer, crafter, start_crafting_si):
        self._orderer = orderer
        self._crafter = crafter
        self._process = None
        self._start_crafting_si = start_crafting_si

    def clear(self):
        self._orderer = None
        self._crafter = None
        self._process = None
        self._start_crafting_si = None

    def get_existing_order(self):

        def is_crafting_interaction(interaction):
            if isinstance(interaction, CraftingPhaseSuperInteractionMixin) and interaction.phase.allows_multiple_orders:
                return True
            return False

        for interaction in self._crafter.si_state:
            while is_crafting_interaction(interaction):
                return interaction
        for interaction in self._crafter.queue:
            while is_crafting_interaction(interaction):
                return interaction

    def push_wait_for_order(self, crafting_si):

        def exit_wait_for_order():
            if self._process is not None:
                self._process.remove_order(self._orderer)
            self.clear()

        if self._start_crafting_si.immediate:
            context = self._start_crafting_si.context.clone_from_immediate_context(self._start_crafting_si)
        else:
            context = self._start_crafting_si.context.clone_for_continuation(self._start_crafting_si)
        result = self._orderer.push_super_affordance(self._start_crafting_si.order_wait_affordance, self._crafter, context, exit_functions=(exit_wait_for_order,), depended_on_si=self._start_crafting_si.depended_on_si)
        if result:
            liability = crafting_si.get_liability(CANCEL_INTERACTION_ON_EXIT_LIABILITY)
            if liability is None:
                liability = CancelInteractionsOnExitLiability()
                crafting_si.add_liability(CANCEL_INTERACTION_ON_EXIT_LIABILITY, liability)
            liability.add_cancel_entry(self._orderer, self._start_crafting_si.order_wait_affordance)
        else:
            self.clear()
            logger.error('Failed to push wait for drink: {}', result)
        return result

    def start_order_affordance(self, recipe):

        def place_order():
            depended_on_si = self._start_crafting_si.depended_on_si
            if depended_on_si is None or not depended_on_si.has_been_canceled:
                self.place_order_for_recipe(recipe)

        result = self._orderer.push_super_affordance(self._start_crafting_si.order_craft_affordance, self._crafter, self._start_crafting_si.context, depended_on_si=self._start_crafting_si.depended_on_si, exit_functions=(place_order,))
        if not result:
            self.clear()

    def place_order_for_recipe(self, recipe):
        if self._crafter is None:
            return EnqueueResult(TestResult.NONE, ExecuteResult.NONE)
        if not self._crafter.is_simulating:
            return EnqueueResult(TestResult.NONE, ExecuteResult.NONE)
        crafting_si = self.get_existing_order()
        result = False
        if crafting_si is not None:
            for sim_id in self._start_crafting_si.orderer_ids:
                crafting_si.process.add_order(sim_id, recipe)
            self._process = crafting_si.process
            result = self.push_wait_for_order(crafting_si)
        elif self._start_crafting_si._handle_begin_crafting(recipe, self._crafter, ordering_sim=self._orderer, orderer_ids=self._start_crafting_si.orderer_ids):
            crafting_si = self.get_existing_order()
            self._process = crafting_si.process
            result = self.push_wait_for_order(crafting_si)
        if not result:
            self.clear()
        return result

class StartCraftingOrderSuperInteraction(StartCraftingSuperInteraction):
    __qualname__ = 'StartCraftingOrderSuperInteraction'
    INSTANCE_TUNABLES = {'crafter': TunableEnumEntry(ParticipantType, ParticipantType.Object, description='Who or what to apply this test to'), 'order_craft_affordance': TunableReference(services.affordance_manager(), description='The affordance used to order the chosen craft'), 'order_wait_affordance': TunableReference(services.affordance_manager(), description='The affordance used to wait for an ordered craft'), 'tooltip_crafting_almost_done': TunableLocalizedStringFactory(default=1860708663, description="Grayed-out tooltip message when another order can't be added because the crafter is almost done.")}

    @classmethod
    def _test(cls, target, context, **kwargs):
        test_result = StartCraftingSuperInteraction._test(target, context, **kwargs)
        if not test_result:
            return test_result
        who = cls.get_participant(participant_type=cls.crafter, sim=context.sim, target=target)
        for interaction in who.si_state:
            while isinstance(interaction, CraftingPhaseSuperInteractionMixin):
                if not interaction.phase.allows_multiple_orders:
                    return TestResult(False, "The crafter is in a phase doesn't allow multiple orders.")
                if interaction.process.is_last_phase:
                    return TestResult(False, 'The crafter is almost done.', tooltip=cls.tooltip_crafting_almost_done)
        return TestResult.TRUE

    def _run_interaction_gen(self, timeline):
        self._set_orderers(self.sim)
        crafter = self.get_participant(self.crafter, target=self.target)
        self._show_picker_dialog(self.sim, target_sim=crafter, order_count=len(self.orderer_ids), crafter=crafter)
        return True

    def on_choice_selected(self, choice_tag, **kwargs):
        recipe = choice_tag
        if recipe is None:
            return
        crafter = self.get_participant(self.crafter, target=self.target)
        start_crafting_handler = StartCraftingOrderHandler(self.sim, crafter, self)
        start_crafting_handler.start_order_affordance(recipe)

lock_instance_tunables(StartCraftingOrderSuperInteraction, basic_reserve_object=None)

class StartCraftingAutonomouslySuperInteraction(AutonomousPickerSuperInteraction, StartCraftingMixin):
    __qualname__ = 'StartCraftingAutonomouslySuperInteraction'
    INSTANCE_TUNABLES = {'recipes': TunableList(description='The recipes a Sim can craft.', tunable=TunableReference(description='Recipe to craft.', manager=services.recipe_manager(), reload_dependent=True)), 'is_party_crafting': Tunable(bool, False, description='Whether this crafting will create consumables for party')}

    @classmethod
    def _tuning_loaded_callback(cls):
        super()._tuning_loaded_callback()
        for recipe in cls.recipes:
            recipe.validate_for_start_crafting()

    @classmethod
    def _test(cls, target, context, **kwargs):
        if target is not None:
            targets = (target,) if not target.parts else [part for part in target.parts if part.supports_affordance(cls)]
            for target in targets:
                while target.may_reserve(context.sim):
                    break
            return TestResult(False, 'Object {} is in use, cannot autonomously used by sim {}', target, context.sim)
        return cls._autonomous_test(target, context, context.sim)

    @classmethod
    def _autonomous_test(cls, target, context, who):
        for recipe in cls.recipes:
            result = CraftingProcess.recipe_test(target, context, recipe, who, 0, False, from_autonomy=True)
            while result:
                return TestResult.TRUE
        return TestResult(False, 'There are no autonomously completable recipies.')

    @classmethod
    def get_situation_score(cls, sim):
        (situation, score) = super().get_situation_score(sim)
        if situation is not None:
            return (situation, score)
        for recipe in cls.recipes:
            while recipe.final_product.definition is not None:
                (situation, score) = services.get_zone_situation_manager().get_situation_score_for_action(sim, object_def=recipe.final_product.definition)
                if situation is not None:
                    return (situation, score)
        return (None, None)

    def __init__(self, *args, **kwargs):
        choice_enumeration_strategy = RecipePickerEnumerationStrategy()
        AutonomousPickerSuperInteraction.__init__(self, choice_enumeration_strategy=choice_enumeration_strategy, *args, **kwargs)
        StartCraftingMixin.__init__(self)

    @property
    def create_target(self):
        if self.recipes:
            first_phases = self.recipes[0].first_phases
            if first_phases:
                first_phase = first_phases[0]
                if hasattr(first_phase, 'factory'):
                    object_info = first_phase.factory._object_info
                object_info = first_phase.object_info
                if object_info is not None:
                    return object_info.definition
        return super().create_target

    def _run_interaction_gen(self, timeline):
        self._set_orderers(self.sim)
        self._choice_enumeration_strategy.build_choice_list(self)
        recipe = self._choice_enumeration_strategy.find_best_choice(self)
        if recipe is None:
            return False
        return self._handle_begin_crafting(recipe, self.sim, orderer_ids=self.orderer_ids)

class StartCraftingOrderAutonomouslySuperInteraction(StartCraftingAutonomouslySuperInteraction):
    __qualname__ = 'StartCraftingOrderAutonomouslySuperInteraction'
    INSTANCE_TUNABLES = {'crafter': TunableEnumEntry(ParticipantType, ParticipantType.Object, description='Who or what to apply this test to'), 'order_craft_affordance': TunableReference(services.affordance_manager(), description='The affordance used to order the chosen craft'), 'order_wait_affordance': TunableReference(services.affordance_manager(), description='The affordance used to wait for an ordered craft'), 'tooltip_crafting_almost_done': TunableLocalizedStringFactory(default=1860708663, description="Grayed-out tooltip message when another order can't be added because the crafter is almost done.")}

    @classmethod
    def _test(cls, target, context, **kwargs):
        test_result = StartCraftingSuperInteraction._test(target, context, **kwargs)
        if not test_result:
            return test_result
        crafter = cls.get_participant(participant_type=cls.crafter, sim=context.sim, target=target)
        test_result = cls._autonomous_test(target, context, crafter)
        if not test_result:
            return test_result
        for interaction in crafter.si_state:
            while isinstance(interaction, CraftingPhaseSuperInteractionMixin) and interaction.phase.allows_multiple_orders:
                tooltip = cls.create_localized_string(cls.tooltip_crafting_almost_done, target=target, context=context)
                return TestResult(False, 'The crafter is almost done.', tooltip=tooltip)
        return TestResult.TRUE

    def _run_interaction_gen(self, timeline):
        self._set_orderers(self.sim)
        self._choice_enumeration_strategy.build_choice_list(self)
        recipe = self._choice_enumeration_strategy.find_best_choice(self)
        if recipe is None:
            return False
        crafter = self.get_participant(self.crafter, target=self.target)
        start_crafting_handler = StartCraftingOrderHandler(self.sim, crafter, self)
        start_crafting_handler.start_order_affordance(recipe)
        return True

class CraftingResumeInteraction(SuperInteraction):
    __qualname__ = 'CraftingResumeInteraction'
    CRAFTING_RESUME_INTERACTION = TunableReference(description='\n        A Tunable Reference to the CraftingResumeInteraction for interaction\n        save/load to reference in order to resume crafting interactions.\n        ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION), class_restrictions='CraftingResumeInteraction')
    INSTANCE_TUNABLES = {'create_unavailable_recipe_description': TunableLocalizedStringFactory(default=4228422038, tuning_group=GroupNames.UI), 'resume_phase_name': TunableEnumEntry(PhaseName, None, description='The name of the phase to resume for this certain resume interaction. None means starts at current phase.')}

    def _run_interaction_gen(self, timeline):
        self.process.change_crafter(self.sim)
        if self.resume_phase_name is not None:
            resume_phase = self.process.get_phase_by_name(self.resume_phase_name)
            if resume_phase is None:
                logger.error("Try to resume phase {} which doesn't exist in recipe {}", self.resume_phase_name, self.process.recipe.__name__)
                return False
            self.process.send_process_update(self, increment_turn=False)
            return self.process.push_si_for_current_phase(self, next_phases=[resume_phase])
        curr_phase = self.process.phase
        if curr_phase is None:
            logger.error('Trying to resume a crafting interaction that is finished.')
            return False
        if curr_phase.super_affordance is None:
            logger.error("{} doesn't have a tuned super affordance in stage {}", self.process.recipe.__name__, type(curr_phase).__name__)
            return False
        self.process.send_process_update(self, increment_turn=False)
        return self.process.push_si_for_current_phase(self, from_resume=curr_phase.repeat_on_resume)

    @flexmethod
    def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, **interaction_parameters):
        inst_or_cls = inst if inst is not None else cls
        process = inst_or_cls.get_process(target=target)
        create_display_name = inst_or_cls.display_name
        return create_display_name(process.recipe.get_recipe_name(process.crafter))

    @flexmethod
    def get_process(cls, inst, target=DEFAULT):
        target = inst.target if target is DEFAULT else target
        if target is not None and target.has_component(CRAFTING_COMPONENT):
            return target.get_crafting_process()

    @property
    def process(self):
        return self.get_process()

    @classmethod
    def _test(cls, target, context, **kwargs):
        process = cls.get_process(target=target)
        if process is None:
            return TestResult(False, 'No crafting process on target.')
        if not process.recipe.resumable_by_different_sim and process.crafter is not context.sim:
            return TestResult(False, "This sim can't resume crafting this target")
        result = process.resume_test(target, context)
        if not result:
            return result
        result = CraftingProcess.recipe_test(target, context, process.recipe, context.sim, 0, first_phase=process.phase, from_resume=True)
        if result:
            return TestResult.TRUE
        error_tooltip = None
        if result.errors:
            if len(result.errors) > 1:
                localized_error_string = LocalizationHelperTuning.get_bulleted_list(None, *result.errors)
            else:
                localized_error_string = result.errors[0]
            error_tooltip = lambda *_, **__: cls.create_unavailable_recipe_description(localized_error_string)
        return TestResult(False, 'Recipe is not completable.', tooltip=error_tooltip)

class CraftingInteractionMixin:
    __qualname__ = 'CraftingInteractionMixin'
    handles_go_to_next_recipe_phase = True

    @flexmethod
    def get_participants(cls, inst, participant_type, sim=DEFAULT, target=DEFAULT, **interaction_parameters) -> set:
        result = super(CraftingInteractionMixin, inst if inst is not None else cls).get_participants(participant_type, sim=sim, target=target, **interaction_parameters)
        result = set(result)
        if participant_type & ParticipantType.CraftingProcess:
            if inst is not None:
                result.add(inst.process)
            else:
                process = interaction_parameters.get('crafting_process', None)
                if process is not None:
                    result.add(process)
        if participant_type & ParticipantType.All or participant_type & ParticipantType.CraftingObject:
            if inst is not None:
                if inst.process is not None and inst.process.current_ico is not None:
                    result.add(inst.process.current_ico)
                    process = interaction_parameters.get('crafting_process', None)
                    if process is not None and process.current_ico is not None:
                        result.add(process.current_ico)
            else:
                process = interaction_parameters.get('crafting_process', None)
                if process is not None and process.current_ico is not None:
                    result.add(process.current_ico)
        return tuple(result)

    @property
    def carry_target(self):
        carry_target = super().carry_target
        if carry_target is not None:
            return carry_target
        ico = self.process.current_ico
        if ico is not None and ico.set_ico_as_carry_target:
            return ico

    def send_progress_bar_message(self, **_):
        self.process.send_process_update(self, increment_turn=False)

class CraftingMixerInteractionMixin(CraftingInteractionMixin):
    __qualname__ = 'CraftingMixerInteractionMixin'

    @property
    def phase(self) -> Phase:
        return self.super_interaction.phase

    @property
    def process(self) -> CraftingProcess:
        return self.super_interaction.process

    @property
    def recipe(self) -> Recipe:
        return self.super_interaction.recipe

class CraftingStepInteraction(CraftingMixerInteractionMixin, MixerInteraction):
    __qualname__ = 'CraftingStepInteraction'
    INSTANCE_TUNABLES = {'skill_offset': Tunable(int, 0, description='Skill offset for procedural animations.  Used to determine which animations to pull from the recipe animation lists when procedural animations is selected.'), 'go_to_next_phase': Tunable(bool, False, description='Set to true if selecting this mixer interaction will push the next phase in the cooking process')}

    def _do_perform_gen(self, timeline):
        result = yield super()._do_perform_gen(timeline)
        if result:
            if self.go_to_next_phase or self.process.should_go_to_next_phase_on_mixer_completion:
                self.super_interaction._go_to_next_phase()
            crafting_liability = self.super_interaction.get_liability(CRAFTING_QUALITY_LIABILITY)
            if crafting_liability is not None and self.phase.progress_based:
                crafting_liability.send_quality_update()
            self.process.send_process_update(self.super_interaction)
        return result

class CraftingPhaseSuperInteractionMixin(CraftingInteractionMixin):
    __qualname__ = 'CraftingPhaseSuperInteractionMixin'
    INSTANCE_TUNABLES = {'crafting_type_requirement': TunableReference(services.recipe_manager(), class_restrictions=CraftingObjectType, description="This specifies the crafting object type that is required for this interaction to work.This allows the crafting system to know what type of object the SI was expecting when it can't find that SI.")}
    _object_info = None

    def __init__(self, *args, crafting_process, phase, **kwargs):
        super().__init__(crafting_process=crafting_process, phase=phase, *args, **kwargs)
        self._object_create_helper = None
        self.process = crafting_process
        self.phase = phase
        self._went_to_next_phase_or_finished_crafting = False
        self._pushed_cancel_replacement_aop = False
        self.add_exit_function(self._maybe_push_cancel_phase_exit_behavior)
        self._cancel_phase_ran = False

    def is_guaranteed(self):
        return not self.has_active_cancel_replacement

    @classmethod
    def _test(cls, target, context, *args, **kwargs):
        result = super()._test(target, context, *args, **kwargs)
        if not result:
            return result
        return TestResult.TRUE

    @property
    def recipe(self) -> Recipe:
        return self.process.recipe

    @flexmethod
    def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, **kwargs):
        target = inst.carry_target if target is DEFAULT else target
        return inst.create_localized_string(inst.phase.interaction_name, target=target, **kwargs)

    @property
    def object_info(self):
        if self._object_info is not None:
            return self._object_info
        return self.phase.object_info

    @property
    def create_target(self):
        if self.object_info is None:
            return
        return self.object_info.definition

    @property
    def auto_goto_next_phase(self):
        return True

    @flexproperty
    def advance_phase_on_resume(cls, inst):
        return False

    @property
    def created_target(self):
        if self._object_create_helper is not None:
            return self._object_create_helper.object

    def _maybe_push_cancel_phase_exit_behavior(self):
        self._maybe_push_cancel_phase()
        return True

    def _exited_pipeline(self):
        super()._exited_pipeline()
        self._object_create_helper = None

    def _maybe_push_cancel_phase(self):
        if self.sim.is_simulating and self.running and not self._went_to_next_phase_or_finished_crafting:
            if self.process.cancel_phase is not None:
                if self.process.cancel_crafting(self):
                    self._cancel_phase_ran = True
                    self._went_to_next_phase_or_finished_crafting = True
                    self._pushed_cancel_replacement_aop = True
        return self._pushed_cancel_replacement_aop

    def _try_exit_via_cancel_aop(self, carry_cancel_override=None):
        if self._maybe_push_cancel_phase():
            return False
        return super()._try_exit_via_cancel_aop(carry_cancel_override=carry_cancel_override)

    def _go_to_next_phase(self, completing_interaction=None):
        if self._cancel_phase_ran:
            return False
        if not self.will_exit:
            self.completed_by_mixer()
        if self.process.increment_phase(interaction=completing_interaction):
            if self.process.push_si_for_current_phase(self):
                self._went_to_next_phase_or_finished_crafting = True
                self.process.send_process_update(self)
                return True
            return False
        if self.created_target is not None:
            self.created_target.on_crafting_process_finished()
        elif self.process.current_ico is not None:
            self.process.current_ico.on_crafting_process_finished()
        self._went_to_next_phase_or_finished_crafting = True
        return True

    def should_push_consume(self, check_phase=True, from_exit=True):
        if self.consume_object is None:
            return False
        phase_complete = True
        if check_phase:
            last_phase_valid = self.process.is_last_phase and (self.process.is_single_phase_process or not from_exit)
            phase_complete = self.process.is_complete or last_phase_valid
        if self.recipe.push_consume and phase_complete and self.uncanceled:
            if self.recipe.push_consume_threshold is not None:
                commodity_value = self.sim.commodity_tracker.get_value(self.recipe.push_consume_threshold.commodity)
                if self.recipe.push_consume_threshold.threshold.compare(commodity_value):
                    return True
                    return True
            else:
                return True
        return False

    @property
    def consume_object(self):
        if self.created_target is not None:
            return self.created_target
        return self.process.current_ico

    def add_consume_exit_behavior(self):

        def maybe_push_consume():
            if self.should_push_consume():
                (aop, context) = self.get_consume_aop_and_context()
                if aop is not None:
                    return aop.test_and_execute(context)
            return True

        self.add_exit_function(maybe_push_consume)

    def get_consume_aop_and_context(self):
        affordance = self.consume_object.get_consume_affordance()
        if affordance is None:
            logger.warn('{}: object is missing consume affordance. It might not have been created as the final product of the recipe: {}', self, self.consume_object)
            return (None, None)
        affordance = self.generate_continuation_affordance(affordance)
        aop = AffordanceObjectPair(affordance, self.consume_object, affordance, None)
        context = self.context.clone_for_continuation(self, carry_target=None)
        return (aop, context)

    def _should_go_to_next_phase(self, result):
        return result

    def _do_perform_gen(self, timeline):
        result = yield super()._do_perform_gen(timeline)
        if self._should_go_to_next_phase(result) and self.auto_goto_next_phase:
            return self._go_to_next_phase()
        return result

lock_instance_tunables(CraftingPhaseSuperInteractionMixin, display_name=None, display_name_overrides=None, allow_user_directed=False, allow_autonomous=False)

class CraftingPhaseCreateObjectSuperInteraction(CraftingPhaseSuperInteractionMixin, SuperInteraction):
    __qualname__ = 'CraftingPhaseCreateObjectSuperInteraction'

    def _custom_claim_callback(self):
        for participant in self.get_participants(ParticipantType.CraftingProcess):
            multiplier = participant.get_stat_multiplier(CraftingTuning.QUALITY_STATISTIC, ParticipantType.CraftingProcess)
            self.process.add_interaction_quality_multiplier(multiplier)
        self.process.current_ico = self.created_target
        previous_ico = self.process.previous_ico
        if previous_ico is not None:
            self.process.previous_ico = None
            previous_ico.transient = True
            if previous_ico is self.target:
                self.set_target(self.created_target)
            if not previous_ico.in_use:
                self.add_exit_function(previous_ico.destroy)
        if self.phase.object_info_is_final_product:
            if self.process.recipe.final_product.conditional_apply_states:
                resolver = SingleSimResolver(self.sim.sim_info)
                for conditional_state in self.process.recipe.final_product.conditional_apply_states:
                    while resolver(conditional_state.test):
                        self.created_target.set_state(conditional_state.state.state, conditional_state.state)
            self.process.apply_quality_and_value(self.created_target)
            loot = create_loot_list(self, self.process.recipe.final_product.loot_list)
            loot.apply_operations()

    def _build_sequence_with_callback(self, callback=None, sequence=()):
        raise NotImplementedError()

    @property
    def _apply_state_xevt_id(self) -> int:
        raise NotImplementedError()

    @property
    def create_object_owner(self):
        return self.sim

    @property
    def should_reserve_created_object(self):
        return True

    @flexproperty
    def advance_phase_on_resume(cls, inst):
        return True

    def build_basic_content(self, sequence, **kwargs):
        super_build_basic_content = super().build_basic_content
        success = False

        def post_setup_crafted_object(crafted_object):
            self.process.setup_crafted_object(crafted_object, is_final_product=self.phase.object_info_is_final_product)

        def setup_crafted_object(crafted_object):
            for initial_state in reversed(self.object_info.initial_states):
                crafted_object.set_state(initial_state.state, initial_state, from_init=True)

        reserver = self if self.should_reserve_created_object else None
        self._object_create_helper = CreateObjectHelper(self.create_object_owner, self.object_info.definition.id, reserver, init=setup_crafted_object, tag='crafted object for recipe', post_add=post_setup_crafted_object)

        def callback(*_, **__):
            nonlocal success
            self._object_create_helper.claim()
            self._custom_claim_callback()
            self.process.pay_for_item()
            self._log_telemetry()
            success = True

        def crafting_sequence(timeline):
            nonlocal sequence
            sequence = super_build_basic_content(sequence, **kwargs)
            sequence = build_critical_section(sequence, flush_all_animations)
            sequence = self._build_sequence_with_callback(callback, sequence)
            for apply_state in reversed(self.object_info.apply_states):
                sequence = state_change(target=self.created_target, new_value_ending=apply_state, xevt_id=self._apply_state_xevt_id, animation_context=self.animation_context, sequence=sequence)
            result = yield element_utils.run_child(timeline, sequence)
            return result

        return (self._object_create_helper.create(crafting_sequence), lambda _: success)

    def _exited_pipeline(self):
        super()._exited_pipeline()
        if self.process is not None:
            self.process.refund_payment()

    def _log_telemetry(self):
        if self.phase.object_info_is_final_product:
            obj = self.process.current_ico
            if obj is None:
                logger.error('Crafting process telemetry not having a crafted object for phase {} with recipe {}', self.phase, self.recipe, owner='camilogarcia')
                return
            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_NEW_OBJECT, sim=self.sim) as hook:
                quality = obj.ui_metadata.quality
                hook.write_guid(TELEMETRY_FIELD_OBJECT_TYPE, obj.definition.id)
                hook.write_int(TELEMETRY_FIELD_OBJECT_QUALITY, quality)

class CraftingPhaseCreateObjectInSlotSuperInteraction(CraftingPhaseCreateObjectSuperInteraction):
    __qualname__ = 'CraftingPhaseCreateObjectInSlotSuperInteraction'
    INSTANCE_TUNABLES = {'parenting_element': ParentObjectElement.TunableFactory(description='\n                Use this element to instruct the game where the newly-created\n                object should go.  The constraint to ensure the slot is empty\n                will be created automatically.\n                ', locked_args={'_child_object': None})}

    @property
    def _apply_state_xevt_id(self):
        return self.parenting_element.timing.xevt_id

    def disable_carry_interaction_mask(self):
        return True

    def _build_sequence_with_callback(self, callback=None, sequence=()):

        def get_child_object(*_, **__):
            return self.created_target

        return (build_critical_section_with_finally(self.parenting_element(self, get_child_object, sequence=sequence), lambda _: callback()),)

class CraftingPhaseCreateObjectInInventorySuperInteraction(CraftingPhaseCreateObjectSuperInteraction):
    __qualname__ = 'CraftingPhaseCreateObjectInInventorySuperInteraction'
    INSTANCE_TUNABLES = {'inventory_participant': TunableEnumEntry(description='\n                The participant type who has the inventory for the created\n                target to go into.\n                ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'use_family_inventory': Tunable(description='\n                If checked, this object will be added to the family inventory \n                of the tuned sim participant. If the participant is not a sim,\n                this tunable will be ignored.', tunable_type=bool, default=False)}

    @classmethod
    def _constraint_gen(cls, sim, target, participant_type=ParticipantType.Actor):
        for constraint in super(SuperInteraction, cls)._constraint_gen(sim, target, participant_type=participant_type):
            yield constraint

    @property
    def _apply_state_xevt_id(self):
        return SCRIPT_EVENT_ID_START_CARRY

    @property
    def should_reserve_created_object(self):
        return False

    @property
    def auto_goto_next_phase(self):
        return not self.use_family_inventory

    def add_object_to_inventory(self, *_, **__):
        result = False
        inventory_target = self.get_participant(participant_type=self.inventory_participant)
        created_target = self.created_target
        if inventory_target is not None:
            result = inventory_target.inventory_component.player_try_add_object(self.created_target)
        if not result:
            self.cancel(FinishingType.CRAFTING, cancel_reason_msg="Fail to add created object {} into {}'s inventory.".format(created_target, inventory_target))

    def add_object_to_household_inventory(self, *_, **__):
        self._go_to_next_phase()
        build_buy.move_object_to_household_inventory(self.created_target)

    def _build_sequence_with_callback(self, callback=None, sequence=()):
        if self.use_family_inventory:
            return build_element((sequence, lambda _: callback(), self.add_object_to_household_inventory))
        return build_element((self.add_object_to_inventory, sequence, lambda _: callback()))

    @property
    def allow_outcomes(self):
        if self._object_create_helper is None or self._object_create_helper.is_object_none:
            return False
        return super().allow_outcomes

UNCLAIMED_CRAFTABLE_LIABILITY = 'UnclaimedCraftableLiability'

class UnclaimedCraftableLiability(Liability):
    __qualname__ = 'UnclaimedCraftableLiability'

    def __init__(self, object_to_claim, recipe_cost, owning_sim):
        self._object_to_claim = object_to_claim
        self._original_object_location = object_to_claim.location
        self._recipe_cost = recipe_cost
        self._owning_sim = owning_sim

    def release(self):
        if self._object_to_claim.location == self._original_object_location:
            self._object_to_claim.schedule_destroy_asap(source=self._owning_sim, cause='Destroying unclaimed craftable')
            self._owning_sim.family_funds.add(self._recipe_cost, None, self._owning_sim)

    @property
    def should_transfer(self):
        return False

class CreateConsumableAndPushConsumeSuperInteraction(CraftingPhaseCreateObjectInInventorySuperInteraction):
    __qualname__ = 'CreateConsumableAndPushConsumeSuperInteraction'

    def _run_interaction_gen(self, timeline):
        result = yield super()._run_interaction_gen(timeline)
        if not result:
            return result
        (aop, context) = self.get_consume_aop_and_context()
        if aop is not None and context is not None:
            result = aop.interaction_factory(context)
            if result:
                result.interaction.add_liability(UNCLAIMED_CRAFTABLE_LIABILITY, UnclaimedCraftableLiability(self.consume_object, self.recipe.crafting_price, self.sim))
                aop.execute_interaction(result.interaction)
            return result
        return False

    def get_consume_aop_and_context(self):
        (aop, _) = super().get_consume_aop_and_context()
        if aop is None:
            return (None, None)
        context = self.context.clone_for_insert_next(carry_target=None)
        return (aop, context)

class CraftingPhaseCreateCarriedObjectSuperInteraction(CraftingPhaseCreateObjectSuperInteraction):
    __qualname__ = 'CraftingPhaseCreateCarriedObjectSuperInteraction'
    INSTANCE_TUNABLES = {'posture_type': TunableReference(services.posture_manager(), description='Posture to use to carry the object.')}

    @property
    def auto_goto_next_phase(self):
        return True

    @property
    def _apply_state_xevt_id(self):
        return SCRIPT_EVENT_ID_START_CARRY

    def _build_sequence_with_callback(self, callback=None, sequence=()):

        def set_carry_target(_):
            self.context.carry_target = self.created_target

        def create_si_fn():
            if self.should_push_consume(from_exit=False):
                return self.get_consume_aop_and_context()
            return (None, None)

        sequence = (set_carry_target, sequence)
        return enter_carry_while_holding(self, self.created_target, create_si_fn=create_si_fn, callback=callback, sequence=sequence)

class CraftingPhaseCreateObjectFromCarryingSuperInteraction(CraftingPhaseCreateObjectSuperInteraction):
    __qualname__ = 'CraftingPhaseCreateObjectFromCarryingSuperInteraction'
    INSTANCE_TUNABLES = {'apply_final_states_xevt_id': OptionalTunable(Tunable(int, 100, description='Event ID at which the new ICO will have its final state changes applied.'), disabled_name='use_stop_carry_event', enabled_name='use_custom_event_id')}

    def disable_carry_interaction_mask(self):
        return True

    def setup_asm_default(self, asm, actor_name, target_name, carry_target_name, create_target_name=None, **kwargs):
        if super().setup_asm_default(asm, actor_name, target_name, carry_target_name, **kwargs):
            if create_target_name is None:
                logger.error('Attempt to use CraftingPhaseCreateObjectFromCarryingSuperInteraction without a create_target name in the animaion tuning: {}', self)
            elif asm.get_actor_definition(create_target_name) is not None:
                return asm.add_potentially_virtual_actor(actor_name, self.sim, create_target_name, self.created_target, target_participant=AnimationParticipant.CREATE_TARGET)
            return True
        return False

    def _custom_claim_callback(self):
        super()._custom_claim_callback()
        self.carry_target.remove_from_client()
        self.add_consume_exit_behavior()

    @property
    def _apply_state_xevt_id(self):
        if self.apply_final_states_xevt_id is None:
            return SCRIPT_EVENT_ID_STOP_CARRY
        return self.apply_final_states_xevt_id

    def _build_sequence_with_callback(self, callback=None, sequence=()):
        return exit_carry_while_holding(self, sequence=sequence, callback=callback)

    @flexproperty
    def advance_phase_on_resume(cls, inst):
        return False

    def _should_go_to_next_phase(self, result):
        if not result:
            return self.transition.succeeded
        return result

class CraftingPhasePickUpObjectSuperInteraction(CraftingPhaseSuperInteractionMixin, PickUpObjectSuperInteraction):
    __qualname__ = 'CraftingPhasePickUpObjectSuperInteraction'

class CraftingPhaseAddInscriptionSuperInteraction(CraftingPhaseSuperInteractionMixin, SuperInteraction):
    __qualname__ = 'CraftingPhaseAddInscriptionSuperInteraction'
    TEXT_INPUT_INSCRIPTION = 'Inscription'
    INSTANCE_TUNABLES = {'input_dialog': UiDialogTextInputOkCancel.TunableFactory(description='\n        The rename dialog to show when running this interaction.\n        ', text_inputs=(TEXT_INPUT_INSCRIPTION,))}

    def _on_dialog_response(self, dialog):
        if not dialog.accepted:
            return False
        inscription = dialog.text_input_responses.get(self.TEXT_INPUT_INSCRIPTION)
        if inscription is not None:
            self.process.inscription = inscription
        return True

    def _should_go_to_next_phase(self, result):
        return True

    def build_basic_content(self, sequence, **kwargs):
        sequence = super().build_basic_content(sequence, **kwargs)
        return (UiDialogElement(self.sim, self.get_resolver(), dialog=self.input_dialog, on_response=self._on_dialog_response), sequence)

class CraftingPhaseStagingSuperInteraction(CraftingPhaseSuperInteractionMixin, SuperInteraction):
    __qualname__ = 'CraftingPhaseStagingSuperInteraction'
    _content_sets_cls = SuperInteraction._content_sets

    @flexproperty
    def _content_sets(cls, inst):
        if inst is not None and inst.phase.content_set is not None:
            if cls._content_sets_cls.has_affordances():
                logger.error("{}: this interaction has a content set tuned but is being used in a recipe phase ({}) which has its own content set.  The interaction's content set will be ignored.", cls.__name__, inst.phase)
            return inst.phase.content_set
        return cls._content_sets_cls

    @flexproperty
    def stat_from_skill_loot_data(cls, inst):
        if inst is None or cls.skill_loot_data.stat is not None:
            return cls.skill_loot_data.stat
        return inst.recipe.skill_loot_data.stat

    @flexproperty
    def skill_effectiveness_from_skill_loot_data(cls, inst):
        if inst is None or cls.skill_loot_data.effectiveness is not None:
            return cls.skill_loot_data.effectiveness
        return inst.recipe.skill_loot_data.effectiveness

    @flexproperty
    def level_range_from_skill_loot_data(cls, inst):
        if inst is None or cls.skill_loot_data.level_range is not None:
            return cls.skill_loot_data.level_range
        return inst.recipe.skill_loot_data.level_range

    @property
    def auto_goto_next_phase(self):
        return self.basic_content is None or not self.basic_content.staging

    @property
    def phase_index(self):
        return self.process.get_progress()

    def _run_interaction_gen(self, timeline):
        self.add_consume_exit_behavior()
        result = yield super()._run_interaction_gen(timeline)
        return result

class CraftingPhaseTransferCraftingComponentSuperInteraction(CraftingPhaseStagingSuperInteraction):
    __qualname__ = 'CraftingPhaseTransferCraftingComponentSuperInteraction'
    INSTANCE_TUNABLES = {'crafting_component_recipient': TunableEnumEntry(ParticipantType, ParticipantType.Object, description='The participant of this interaction to which the Crafting process is transferred.')}

    def build_basic_elements(self, sequence):
        super_basic_elements = super().build_basic_elements(sequence=sequence)

        def transfer_crafting_component(_):
            subject = self.get_participant(self.crafting_component_recipient)
            self.process.add_crafting_component_to_object(subject)
            self.process.increment_phase(interaction=self)
            self.process.pay_for_item()
            self.process.apply_quality_and_value(subject)

        return element_utils.build_element((transfer_crafting_component, super_basic_elements))

    def _exited_pipeline(self):
        super()._exited_pipeline()
        if self.process is not None and not self.process.is_complete:
            self.process.refund_payment()

class GrabServingSuperInteraction(SuperInteraction):
    __qualname__ = 'GrabServingSuperInteraction'
    GRAB_WHILE_STANDING_PENALTY = Tunable(description='\n        An additional penalty to apply to the constraint of grabbing a serving\n        of food while standing so Sims will prefer to sit before grabbing the\n        food if possible.\n        ', tunable_type=int, default=5)
    INSTANCE_TUNABLES = {'basic_content': TunableBasicContentSet(one_shot=True, no_content=True, default='no_content'), 'posture_type': TunableReference(description='\n            Posture to use to carry the object.\n            ', manager=services.posture_manager()), 'si_to_push': TunableReference(description='\n            SI to push after picking up the object. ATTENTION: Any ads\n            specified by the SI to push will bubble up and attach themselves to\n            the _Grab interaction!\n            ', manager=services.affordance_manager()), 'transferred_stats': TunableList(description='\n            A list of stats to be copied over to the grabbed object.\n            ', tunable=TunableReference(manager=services.statistic_manager())), 'default_grab_serving_animation': TunableAnimationReference(description='\n             The animation to play for this interaction in the case that the\n             object we are grabbing is not in an inventory.  If the object is\n             in an inventory, we will dynamically generate the animation we\n             need to grab it.\n             ')}

    @classmethod
    def _tuning_loaded_callback(cls):
        super()._tuning_loaded_callback()
        if not __debug__:
            return
        if cls.default_grab_serving_animation is None:
            logger.error("GrabServingInteraction {} does not have a 'default_grab_serving_animation' specified.", cls, owner='tastle')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._object_create_helper = None
        self._has_handled_mutation = False

    @classmethod
    def _false_advertisements_gen(cls):
        yield super()._false_advertisements_gen()
        if cls.si_to_push:
            yield cls.si_to_push._false_advertisements_gen()

    def is_guaranteed(self):
        return not self.has_active_cancel_replacement

    @classproperty
    def commodity_flags(cls):
        if cls.si_to_push:
            return cls._commodity_flags | cls.si_to_push.commodity_flags
        return cls._commodity_flags

    @classmethod
    def _statistic_operations_gen(cls):
        for op in super()._statistic_operations_gen():
            yield op
        if cls.si_to_push is not None:
            for op in cls.si_to_push._statistic_operations_gen():
                yield op

    @flexmethod
    def _constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        yielded_geometry = False
        if target is None:
            return
        if target.is_in_inventory():
            if inst is not None:
                inventory_owner = inst.object_with_inventory
            else:
                inventory_owner = None
            if inventory_owner is None:
                inventory_owner = target.get_inventory().owner
            constraint = inventory_owner.get_inventory_access_constraint(sim, is_put=False, carry_target=target, use_owner_as_target_for_resolver=True)
            yield constraint
        else:
            total_constraint = Anywhere()
            for constraint in super(SuperInteraction, cls)._constraint_gen(sim, target, participant_type=participant_type):
                for inner_constraint in constraint:
                    while inner_constraint.geometry or inner_constraint.tentative:
                        yielded_geometry = True
                total_constraint = total_constraint.intersect(constraint)
            if not yielded_geometry:
                total_constraint = total_constraint.intersect(CarryingObject.get_carry_transition_position_constraint(target.position, target.routing_surface))
            if target.parent is None or inst is None:
                yield total_constraint
                return
            surface = target.parent
            if surface.is_part:
                surface = surface.part_owner
            target_obj_def = inst.create_target
            if not inst.target.has_component(CRAFTING_COMPONENT) and inst.created_target is not None:
                target_obj_def = inst.created_target.definition
            if target_obj_def is None:
                return
            slot_manifest = SlotManifest()
            slot_manifest_entry = SlotManifestEntry(target_obj_def, surface, SlotTypeReferences.SIT_EAT_SLOT)
            slot_manifest.add(slot_manifest_entry)
            posture_manifest = SIT_POSTURE_MANIFEST
            posture_state_spec = PostureStateSpec(posture_manifest, slot_manifest, PostureSpecVariable.ANYTHING)
            slot_constraint = Constraint(posture_state_spec=posture_state_spec, debug_name='IdealGrabServingConstraint')
            ideal_constraint = slot_constraint.intersect(total_constraint)
            fallback_constraint = total_constraint.generate_constraint_with_cost(cls.GRAB_WHILE_STANDING_PENALTY)
            total_constraint_set = create_constraint_set((fallback_constraint, ideal_constraint))
            yield total_constraint_set

    @property
    def create_target(self):
        recipe = self.get_base_recipe()
        if recipe is None:
            return
        return recipe.final_product_definition

    @property
    def created_target(self):
        if self._object_create_helper is None:
            return
        return self._object_create_helper.object

    def on_added_to_queue(self, *args, **kwargs):
        mutated_listeners = self.target.crafting_component.object_mutated_listeners
        if self.on_mutated not in mutated_listeners:
            mutated_listeners.append(self.on_mutated)
        return super().on_added_to_queue(*args, **kwargs)

    def _exited_pipeline(self, *args, **kwargs):
        self._detach_mutated_listener()
        self._object_create_helper = None
        return super()._exited_pipeline(*args, **kwargs)

    def _detach_mutated_listener(self):
        if self.target is not None and self.target.crafting_component is not None:
            mutated_listeners = self.target.crafting_component.object_mutated_listeners
            if self.on_mutated in mutated_listeners:
                mutated_listeners.remove(self.on_mutated)

    def setup_crafted_object(self, crafted_object):
        crafting_process = self.target.get_crafting_process()
        crafting_process.setup_crafted_object(crafted_object, use_base_recipe=True, is_final_product=True, owning_household_id_override=self.target.get_household_owner_id())
        self.setup_transferred_stats(crafted_object)
        crafting_process.apply_simoleon_value(crafted_object, single_serving=True)
        if self.target.is_in_inventory():
            inventory_owner = self.target.get_inventory().owner
            inventory_owner.inventory_component.system_add_object(crafted_object, inventory_owner)
        recipe = self.get_base_recipe()
        for apply_state in reversed(recipe.final_product.apply_states):
            crafted_object.set_state(apply_state.state, apply_state)

    def setup_transferred_stats(self, crafted_object):
        for stat in self.transferred_stats:
            tracker = self.target.get_tracker(stat)
            value = tracker.get_value(stat)
            tracker = crafted_object.get_tracker(stat)
            tracker.set_value(stat, value)

    def on_mutated(self):
        if not self._has_handled_mutation:
            self.cancel(FinishingType.OBJECT_CHANGED, cancel_reason_msg='Crafting Target Object Mutated to Empty Platter')
        self._has_handled_mutation = True

    def get_base_recipe(self):
        if self.target is not None and self.target.has_component(CRAFTING_COMPONENT):
            recipe = self.target.get_recipe()
            return recipe.get_base_recipe()

    @classmethod
    def _define_supported_postures(cls):
        return cls.posture_type(None, None, None).asm.get_supported_postures_for_actor('x')

    def setup_asm_default(self, asm, *args, **kwargs):
        result = super().setup_asm_default(asm, *args, **kwargs)
        surface_height = get_surface_height_parameter_for_object(self.target)
        asm.set_parameter('surfaceHeight', surface_height)
        return result

    def build_basic_elements(self, sequence):
        super_build_basic_elements = super().build_basic_elements
        self._object_create_helper = CreateObjectHelper(self.sim, self.create_target, self, post_add=self.setup_crafted_object, tag='Grab a Serving')

        def on_enter_carry(*_, **__):
            self._object_create_helper.claim()
            self._detach_mutated_listener()
            servings = self.target.get_stat_instance(CraftingTuning.SERVINGS_STATISTIC)
            servings.tracker.add_value(CraftingTuning.SERVINGS_STATISTIC, -1)

        self.animation_context.register_event_handler(on_enter_carry, handler_id=SCRIPT_EVENT_ID_START_CARRY)

        def create_si():
            affordance = self.created_target.get_consume_affordance()
            affordance = self.generate_continuation_affordance(affordance)
            aop = AffordanceObjectPair(affordance, self.created_target, affordance, None)
            context = self.context.clone_for_continuation(self)
            return (aop, context)

        def grab_sequence(timeline):
            nonlocal sequence
            sequence = super_build_basic_elements(sequence=sequence)
            inventory_target = None
            if not (self.target.is_in_inventory() and self.target.is_in_sim_inventory()):
                inventory_target = self.sim.posture_state.surface_target
            if inventory_target is not None:
                custom_animation = inventory_target.inventory_component._get_put.get_access_animation_factory(is_put=False)

                def setup_asm(asm):
                    result = self.sim.posture.setup_asm_interaction(asm, self.sim, inventory_target, custom_animation.actor_name, custom_animation.target_name, carry_target=self.created_target, carry_target_name=custom_animation.carry_target_name, surface_target=inventory_target)
                    carry_track = self.sim.posture_state.get_free_carry_track(obj=self.created_target)
                    asm.set_actor_parameter(custom_animation.carry_target_name, self.created_target, PARAM_CARRY_TRACK, carry_track.name.lower())
                    return result

                sequence = custom_animation(self, sequence=sequence, setup_asm_override=setup_asm)
            else:
                sequence = self.default_grab_serving_animation(self, sequence=sequence)
            sequence = enter_carry_while_holding(self, self.created_target, create_si_fn=create_si, sequence=sequence)
            result = yield element_utils.run_child(timeline, sequence)
            return result

        return unless(lambda *_: self._has_handled_mutation, self._object_create_helper.create(grab_sequence))

class DebugCreateCraftableInteraction(ImmediateSuperInteraction):
    __qualname__ = 'DebugCreateCraftableInteraction'
    INSTANCE_TUNABLES = {'recipe_picker': TunablePickerDialogVariant(description='The object picker used to display the possible objects to create.'), 'quality': OptionalTunable(TunableStateValueReference(description='The quality of the cheated consumable'))}

    @staticmethod
    def create_craftable(chosen_recipe, crafter_sim, quality=None, owning_household_id_override=None, place_in_crafter_inventory=False):

        def setup_object(obj):
            crafting_process = CraftingProcess(crafter=crafter_sim, recipe=chosen_recipe)
            crafting_process.setup_crafted_object(obj, is_final_product=True, owning_household_id_override=owning_household_id_override)

        product = create_object(chosen_recipe.final_product.definition.id, init=setup_object)
        try:
            if product.inventoryitem_component is not None and product.inventoryitem_component.inventory_only:
                place_in_crafter_inventory = True
            if place_in_crafter_inventory:
                crafter_sim.inventory_component.system_add_object(product, crafter_sim)
            if chosen_recipe.final_product.apply_states:
                for apply_state in chosen_recipe.final_product.apply_states:
                    product.set_state(apply_state.state, apply_state)
            while quality is not None:
                product.set_state(quality.state, quality)
        except:
            product.destroy(source=crafter_sim, cause='Except during creation of craftable.')
            raise
        return product

    def _run_interaction_gen(self, timeline):
        recipe_manager = services.get_instance_manager(sims4.resources.Types.RECIPE)
        if recipe_manager is None:
            logger.warn('Attempting to run CreateCraftable cheat when there is no recipe manager')
            return
        dialog = self.recipe_picker(self.sim, self.get_resolver())
        recipes = recipe_manager.get_ordered_types(only_subclasses_of=Recipe)
        for (i, recipe) in enumerate(recipes):
            if recipe.final_product.definition is None:
                pass
            recipe_icon = IconInfoData(icon_resource=recipe.icon_override, obj_def_id=recipe.final_product_definition_id, obj_geo_hash=recipe.final_product_geo_hash, obj_material_hash=recipe.final_product_material_hash)
            row = RecipePickerRow(name=recipe.get_recipe_name(self.sim), icon=recipe.icon_override, row_description=recipe.recipe_description(self.sim), linked_recipe=recipe.base_recipe, display_name=recipe.get_recipe_picker_name(self.sim), icon_info=recipe_icon, tag=recipe, skill_level=i)
            dialog.add_row(row)

        def on_recipe_selected(dialog):
            chosen_recipe = dialog.get_single_result_tag()
            if chosen_recipe is not None:
                craftable = DebugCreateCraftableInteraction.create_craftable(chosen_recipe, self.sim, quality=self.quality)
                if not craftable.is_in_inventory():
                    CarryingObject.snap_to_good_location_on_floor(craftable, starting_transform=self.target.transform, starting_routing_surface=self.target.routing_surface)

        dialog.set_target_sim(self.context.sim)
        dialog.add_listener(on_recipe_selected)
        dialog.show_dialog()

