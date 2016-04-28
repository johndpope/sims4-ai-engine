import itertools
from crafting.crafting_ingredients import TunableIngredientByDefFactory, TunableIngredientByTagFactory
from crafting.crafting_tunable import CraftingTuning
from crafting.genre import Genre
from event_testing.tests import TunableTestVariant
from interactions import ParticipantType
from interactions.base.picker_tunables import TunableBuffWeightMultipliers
from interactions.base.super_interaction import SuperInteraction
from interactions.utils.loot import LootActions
from interactions.utils.tunable import ContentSet
from objects.components.state import TunableStateValueReference
from postures import PostureTrack
from sims.bills_enums import Utilities
from sims4.localization import TunableLocalizedString, TunableLocalizedStringFactory, LocalizationHelperTuning
from sims4.tuning.dynamic_enum import DynamicEnum
from sims4.tuning.instances import TunedInstanceMetaclass, HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableList, Tunable, TunableReference, TunableMapping, TunableVariant, TunableTuple, TunableEnumEntry, OptionalTunable, TunableResourceKey, HasTunableReferenceFactory, HasTunableFactory, TunableInterval, TunableSet, TunableEntitlement, TunableThreshold
from sims4.tuning.tunable_base import GroupNames
from sims4.utils import classproperty
from singletons import DEFAULT
from statistics.skill import TunableSkillLootData
from tunable_multiplier import TunableStatisticModifierCurve
import event_testing.test_variants
import event_testing.tests
import mtx
import objects.components
import services
import sims4.log
import tag
logger = sims4.log.Logger('Recipe')
dump_logger = sims4.log.LoggerClass('Recipe')

class PhaseName(DynamicEnum):
    __qualname__ = 'PhaseName'
    INVALID = 0
    START_PHASE = 1

class TunableQualityInfo(TunableTuple):
    __qualname__ = 'TunableQualityInfo'

    def __init__(self, description='The quality adjustment info for final product.', **kwargs):
        super().__init__(base_quality=Tunable(description='\n                The base quality value for the final product.\n                ', tunable_type=float, default=0.0), skill_adjustment=Tunable(description='\n                The quality value adjustment based on the effective skill\n                level. If the skill level is higher than the recipe\n                requirement, the adjustment value will be a bonus, otherwise it\n                would apply to the final object quality negatively.\n                ', tunable_type=float, default=0.0), description=description, **kwargs)

class TunableRecipeObjectInfo(TunableTuple):
    __qualname__ = 'TunableRecipeObjectInfo'

    def __init__(self, optional_create=True, description='An object definition and states to apply.', class_restrictions=(), **kwargs):
        definition = TunableReference(description='\n            An object to create.', manager=services.definition_manager(), class_restrictions=class_restrictions)
        if optional_create:
            definition = OptionalTunable(definition)
        super().__init__(definition=definition, carry_track=OptionalTunable(description='\n                Which hand to carry the object in.', tunable=TunableEnumEntry(PostureTrack, default=PostureTrack.RIGHT)), initial_states=TunableList(description='\n                A list of states to apply to the finished object as soon as it is created.\n                ', tunable=TunableStateValueReference()), apply_states=TunableList(description='\n                A list of states to apply to the finished object.\n                ', tunable=TunableStateValueReference()), apply_tags=TunableSet(description='\n                A list of category tags to apply to the finished product.\n                ', tunable=TunableEnumEntry(tag.Tag, tag.Tag.INVALID, description='What tag to test for')), conditional_apply_states=TunableList(description='\n                A list of states to apply to the finished object based on if the associated test passes.\n                ', tunable=TunableTuple(description='\n                    The test to pass for the given state to be applied.', test=TunableTestVariant(), state=TunableStateValueReference())), super_affordances=TunableList(description='\n                Affordances available on the finished product.\n                ', tunable=SuperInteraction.TunableReference()), loot_list=TunableList(description='\n                A list of pre-defined loot operations to apply after crafting object creation.\n                ', tunable=LootActions.TunableReference()), quality_adjustment=TunableQualityInfo(), simoleon_value_modifiers_map=TunableMapping(description='\n                    The mapping of state values to Simolean value modifiers.\n                    The final value of a craftable is decided based on its\n                    retail value multiplied by the sum of all modifiers for\n                    states that apply to the final product. All modifiers are\n                    added together first, then the sum will be multiplied by\n                    the retail price.\n                    ', key_type=TunableStateValueReference(description='\n                        The quality state values. If this item has this state,\n                        then a random modifier between min_value and max_value\n                        will be multiplied to the retail price.'), value_type=TunableInterval(description='\n                        The maximum modifier multiplied to the retail price based on the provided state value\n                        ', tunable_type=float, default_lower=1, default_upper=1)), simoleon_value_skill_curve=TunableStatisticModifierCurve.TunableFactory(description="\n                Allows you to adjust the final value of the object based on the Sim's\n                level of a given skill.\n                ", axis_name_overrides=('Skill Level', 'Simoleon Multiplier'), locked_args={'subject': ParticipantType.Actor}), masterworks=OptionalTunable(TunableTuple(description='\n                    If the result of this recipe can be a masterwork (i.e. a\n                    masterpiece for paintings), this should be enabled.\n                    ', base_test=event_testing.tests.TunableTestSet(description="\n                        This is the initial gate for a recipe to result in a masterwork.\n                        If this test doesn't pass, we don't even attempt to be a masterwork.\n                        "), base_chance=Tunable(description='\n                        Once the Base Test passes, this will be the base chance\n                        that this recipe will result in a masterwork.\n                        0.0 is 0% chance\n                        1.0 is 100% chance\n                        ', tunable_type=float, default=0.25), multiplier_tests=TunableList(TunableTuple(description='\n                        When deciding if this recipe will result in a masterwork, we run through each test in this list. IF the test passes, its multiplier will be applied to the Base Chance.\n                        ', multiplier=Tunable(description='\n                            This is the multiplier that will be applied to the Base Chance if these tests pass.\n                            ', tunable_type=float, default=1), tests=event_testing.tests.TunableTestSet())), skill_adjustment=Tunable(description="\n                        The masterwork chance adjustment based on the effective skill\n                        level. For each level higher than the requires skill of the recipe,\n                        the masterwork chance will be increased by this.\n                        There is no penalty if, somehow, the required skill is greater\n                        than the effective skill of the Sim.\n                        Example:\n                        Assume you're level 10 writing skill and you're crafting a\n                        book that requires level 4 writing skill. Also assume skill_adjustment\n                        is tuned to 0.05 and the base_chance is set to 0.25.\n                        The differences in skill is 10 (your skill) - 4 (required skill) = 6 \n                        Then, take this difference, 6 * 0.05 (skill_adjustment) = 0.3\n                        The base chance, 0.25 + 0.3 = 0.55. 55% chance of this being a masterwork.\n                        ", tunable_type=float, default=0.0), simoleon_value_multiplier=TunableInterval(description='\n                        The amount by which the final simoleon value of the object will be multiplied if it is a masterwork.\n                        The multiplier is a random number between the lower and upper bounds, inclusively.\n                        ', tunable_type=float, default_lower=1, default_upper=1))), thumbnail_geo_state=OptionalTunable(description='\n                The geo state name override for recipe picker thumbnail generation.\n                ', disabled_name='UseCatalog', enabled_name='CustomValue', tunable=Tunable(description='Geo State name', tunable_type=str, default='')), thumbnail_material_state=OptionalTunable(description='\n                The material state name override for recipe picker thumbnail generation.\n                ', disabled_name='UseCatalog', enabled_name='CustomValue', tunable=Tunable(description='Material State name', tunable_type=str, default='')), description=description, **kwargs)

class Phase(HasTunableReferenceFactory, HasTunableFactory, metaclass=TunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.RECIPE)):
    __qualname__ = 'Phase'
    debug_name = 'uninitialized'
    TURN_BASED = 'turn_based'
    PROGRESS_BASED = 'progress_based'
    INSTANCE_SUBCLASSES_ONLY = True
    INSTANCE_TUNABLES = {'super_affordance': SuperInteraction.TunableReference(description='\n            Super-affordance that manages this phase of the recipe.\n            '), 'phase_interaction_name_override': OptionalTunable(description="\n            The localized name that will display in the UI instead of the\n            recipe's Phase Interaction Name property.\n            ", tunable=sims4.localization.TunableLocalizedStringFactory()), 'target_ico': Tunable(description="\n            This phase targets the last object created by the recipe, so don't\n            run autonomy to find it.\n            ", tunable_type=bool, default=False), '_object_info': TunableVariant(description='\n            If this phase creates an object, use this definition.\n            ', locked_args={'none': None, 'use_final_product': DEFAULT}, literal=TunableRecipeObjectInfo(description='\n                If this phase creates an object, use this definition.\n                '), default='none'), '_cancel_phase_name': TunableEnumEntry(description='\n            The name of the phase to run if the crafting process is canceled\n            during this phase.  May be None.\n            ', tunable_type=PhaseName, default=None), 'loop_by_orders': Tunable(description='\n            Should loop in the phase if multiple orders?\n            ', tunable_type=bool, default=False), 'point_of_no_return': Tunable(description='\n            When crafting get to this phase, the final product will be created\n            no matter cancel SI or not\n            ', tunable_type=bool, default=False), 'phase_display_name': TunableLocalizedString(description='\n            Localized name of this phase for the crafting quality UI\n            '), 'is_visible': Tunable(description='\n            If this phase will show on crafting quality UI\n            ', tunable_type=bool, default=False), 'completion': TunableVariant(description="\n            Controls how the phase completes, either when turns have elapsed or\n            based on the crafting progress statistic maxing out.  If the super\n            interaction for the phase isn't looping or staging, this value is\n            ignored.\n            ", locked_args={TURN_BASED: TURN_BASED, PROGRESS_BASED: PROGRESS_BASED}, default=TURN_BASED)}
    FACTORY_TUNABLES = {'next_phases': TunableList(description='\n            The names of the phases that can come next.  If empty, this will be the\n            final phase.\n            ', tunable=TunableEnumEntry(PhaseName, None))}
    FACTORY_TUNABLES.update(INSTANCE_TUNABLES)

    def __init__(self, *, recipe, phase_id, **kwargs):
        super().__init__(**kwargs)
        self.recipe = recipe
        self.id = phase_id

    def recipe_tuning_loaded(self):
        recipe = self.recipe
        next_phases = []
        for name in self.next_phases:
            if name in recipe.phases:
                next_phases.append(recipe.phases[name])
            else:
                logger.error("Unknown phase '{}' specified in next_phase_names for phase '{}' in '{}'.", name, self.id, recipe)
        self.next_phases = next_phases
        if self._cancel_phase_name is None:
            self.cancel_phase = None
        elif self._cancel_phase_name in recipe.phases:
            self.cancel_phase = recipe.phases[self._cancel_phase_name]
        else:
            self.cancel_phase = None
            logger.error("Unknown phase '{}' specified for cancel_phase_name for phase '{}' in '{}'.", self._cancel_phase_name, self.id, recipe)

    @property
    def interaction_name(self):
        if self.phase_interaction_name_override is not None:
            return self.phase_interaction_name_override
        return self.recipe.phase_interaction_name

    @property
    def object_info(self):
        object_info = self._object_info
        if object_info is None:
            return
        if object_info is DEFAULT:
            return self.recipe.final_product
        return object_info

    @property
    def object_info_is_final_product(self):
        return self._object_info is DEFAULT

    @property
    def num_turns(self):
        return self._num_turns

    @property
    def one_shot(self):
        return self.super_affordance.one_shot

    @property
    def turn_based(self):
        if self.one_shot:
            return False
        return self.completion == self.TURN_BASED

    @property
    def progress_based(self):
        if self.one_shot:
            return False
        return self.completion == self.PROGRESS_BASED

    def __repr__(self):
        return '<{} {}>'.format(type(self).__name__, self.id)

    @property
    def allows_multiple_orders(self):
        return False

    def accepting_more_orders(self, turns):
        return True

    @property
    def repeat_on_resume(self):
        from crafting.crafting_interactions import CraftingPhaseSuperInteractionMixin
        if issubclass(self.super_affordance, CraftingPhaseSuperInteractionMixin) and self.super_affordance.advance_phase_on_resume:
            return False
        return True

class SimplePhase(Phase):
    __qualname__ = 'SimplePhase'
    content_set = None
    _num_turns = 0
    INSTANCE_TUNABLES = {'multiple_order_tuning': Tunable(description='\n            Sets whether a stage is compatible with multiple orders\n            ', tunable_type=bool, default=False)}
    FACTORY_TUNABLES = {}
    FACTORY_TUNABLES.update(INSTANCE_TUNABLES)

    @property
    def allows_multiple_orders(self):
        return self.multiple_order_tuning

class MultiStagePhase(Phase):
    __qualname__ = 'MultiStagePhase'
    INSTANCE_TUNABLES = {'multiple_order_tuning': OptionalTunable(TunableTuple(min_turns_required=Tunable(description='\n            Minimum pips needed for adding more orders.\n            ', tunable_type=int, default=0)))}
    FACTORY_TUNABLES = {'content_set': ContentSet.TunableFactory(description='\n        A list of interactions available to the player as recipe actions,\n        boosters, and flourishes.\n        ', locked_args={'phase_tuning': None}), '_num_turns': Tunable(description='\n        Number of turns (number of mixer interactions that must be performed) for this phase.\n        ', tunable_type=int, default=3)}
    FACTORY_TUNABLES.update(INSTANCE_TUNABLES)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.content_set = self.content_set()
        num_phases = self.content_set.num_phases
        if num_phases > 0:
            self._num_turns = num_phases

    @property
    def turns(self):
        pass

    @property
    def allows_multiple_orders(self):
        return self.multiple_order_tuning is not None

    def accepting_more_orders(self, turns):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return True

class TunablePhaseVariant(TunableVariant):
    __qualname__ = 'TunablePhaseVariant'

    def __init__(self, description='The information for a single phase of a recipe.', **kwargs):
        super().__init__(description=description, simple_phase=SimplePhase.TunableFactory(), simple_phase_ref=SimplePhase.TunableReferenceFactory(reload_dependent=True), multi_stage_phase=MultiStagePhase.TunableFactory(), multi_stage_phase_ref=MultiStagePhase.TunableReferenceFactory(reload_dependent=True), **kwargs)

class Recipe(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.RECIPE)):
    __qualname__ = 'Recipe'
    INSTANCE_TUNABLES = {'name': TunableLocalizedStringFactory(description='\n            The name of this recipe.\n            '), 'phase_interaction_name': TunableLocalizedStringFactory(description="\n            The name of each phase's interaction.\n            "), 'final_product': TunableRecipeObjectInfo(description='\n            The final product of the crafting process.\n            ', optional_create=False), '_first_phases': TunableList(description='\n            The names of the phases that can be done first.  This cannot be empty.\n            ', tunable=TunableEnumEntry(PhaseName, default=None)), '_phases': TunableMapping(description='\n            The phases that make up this recipe.\n            ', key_type=TunableEnumEntry(PhaseName, None), value_type=TunablePhaseVariant()), 'resume_affordance': OptionalTunable(description='\n            The interaction to use when resuming crafting this recipe.\n            ', tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION), class_restrictions=('CraftingResumeInteraction',))), 'skill_test': OptionalTunable(description='\n            The skill level required to use this recipe.\n            ', tunable=event_testing.test_variants.SkillRangeTest.TunableFactory()), 'additional_tests': event_testing.tests.TunableTestSetWithTooltip(), 'additional_tests_ignored_on_resume': Tunable(description='\n            If set, additional tests are ignored when testing to see if a recipe\n            can be resumed.\n            ', tunable_type=bool, default=False), 'utility_info': OptionalTunable(TunableList(description='\n            Tuning that specifies which utilities this recipe requires to\n            be made/cooked.\n            ', tunable=TunableEnumEntry(Utilities, None)), needs_tuning=True), '_retail_price': Tunable(description='\n            Retail price of the recipe. \n            This is not the total price of the recipe.  The total price of the \n            recipe will be _retail_price+delta_ingredient_price\n            ', tunable_type=int, default=0), 'crafting_cost': TunableVariant(description='\n            This determines the amount of money the Sim will have to pay in\n            order to craft this recipe.\n            \n            Crafting Discount is multiplied by the Retail Price to determine the\n            amount of money the Sim must pay to craft this.\n            \n            Flat Fee is just a flat fee the Sim must pay to craft this.\n            ', discount=Tunable(description='\n                This number is multiplied by the Retail Price to to determine\n                the amount of money the Sim will have to pay in order to craft this.\n                ', tunable_type=float, default=0.8), flat_fee=Tunable(description='\n                This is a flat amount of simoleons that the Sim will have to pay\n                in order to craft this.\n                ', tunable_type=int, default=0), default='discount'), 'delta_ingredient_price': Tunable(description='\n            Delta price of a recipe will be a delta value that will increase\n            or decrease depending on how many ingredients for the recipe the \n            sim has.\n            e.g  For a 3 ingredient recipe:\n            - If no ingredient is found,  price will be retail_price + delta\n            - If 1 ingredient is found,  price will be retail_price + 2/3 of \n            delta\n            - If 2 ingredient is found,  price will be retail_price + 1/3 of \n            delta\n            - If 3 ingredient is found,  price will be retail_price\n            ', tunable_type=int, default=0), '_no_initial_charge': Tunable(description='\n            If set, there is no initial charge for making this recipe\n            ', tunable_type=bool, needs_tuning=True, default=False), 'icon_override': TunableResourceKey(description="\n            This will override the default icon for this recipe. If left blank, the thumbnail of the recipe's final product will be used.\n            ", default=None, resource_types=sims4.resources.CompoundTypes.IMAGE), 'recipe_description': TunableLocalizedStringFactory(description='recipe description'), 'autonomy_weight': Tunable(description='\n            The relative weight for autonomy to choose to make or order this recipe\n            ', tunable_type=float, default=0), 'buff_weight_multipliers': TunableBuffWeightMultipliers(), 'base_recipe': OptionalTunable(description='\n            If set, the single serving counterpart for this recipe\n            ', tunable=TunableReference(services.recipe_manager())), 'visible_as_subrow': Tunable(description='\n            If this recipe has base recipe, this boolean will decide whether or\n            not this recipe will show up in the subrow entry of the base\n            recipe.\n            ', tunable_type=bool, default=True), 'base_recipe_category': OptionalTunable(description='\n            The pie menu category of the base recipe if the picker dialog to\n            choose recipes is tuned to use pie menu formation.\n            ', tunable=TunableReference(description='\n                Pie menu category for pie menu mixers.\n                ', manager=services.get_instance_manager(sims4.resources.Types.PIE_MENU_CATEGORY))), 'multi_serving_name': OptionalTunable(TunableLocalizedStringFactory(description='The name of multiple serving to show in the sub row of ObjectPicker.'), enabled_name='use_multi_serving_name', disabled_name='use_recipe_name', description="The string that shows up in the ObjectPicker when this recipe is a multi_serving. Please use 'use_recipe_name' when it's a single serving"), 'push_consume': Tunable(description='\n            Whether to push the consume after finish the recipe.\n            ', tunable_type=bool, needs_tuning=True, default=True), 'push_consume_threshold': OptionalTunable(description='\n            If Push Consume is checked and this threshold is enabled, the consume affordance will\n            only be pushed if the threshold is met.\n            ', tunable=TunableTuple(description='\n                The commodity/threshold pair.\n                ', commodity=TunableReference(description='\n                    The commodity to be tested.\n                    ', manager=services.statistic_manager(), class_restrictions='Commodity'), threshold=TunableThreshold(description='\n                    The threshold at which to remove this bit.\n                    '))), 'skill_loot_data': TunableSkillLootData(description='Loot Data for DynamicSkillLootOp. This will only be used if in the loot list of the outcome there is a dynamic loot op.'), 'masterwork_name': TunableLocalizedString(description='If this can be a masterwork, what should its masterwork state be called? Usually this is just Masterpiece.'), 'resumable': Tunable(description='\n            If set to False, this recipe is not resumable, for example drinks made at bar.\n            ', tunable_type=bool, default=True), 'resumable_by_different_sim': Tunable(description='\n            If set, this recipe can be resumed by a sim other than the one that started it\n            ', tunable_type=bool, needs_tuning=True, default=False), 'entitlement': TunableEntitlement(description='\n            Entitlement required to use this recipe.\n            '), 'hidden_until_unlock': Tunable(description="\n            If checked, this recipe will not show up in picker or piemenu if\n            it's not unlocked, either by skill up, or unlock outcome, or\n            entitlement.\n            ", tunable_type=bool, needs_tuning=True, default=True), 'use_ingredients': OptionalTunable(description='\n            If checked recipe will have the ability to use ingredients to \n            improve its quality when prepared.\n            ', tunable=TunableTuple(description='\n                Ingredient data for a recipe.\n                ', all_ingredients_required=Tunable(description='\n                    If checked recipe will not be available unless all \n                    ingredients are found on the sim inventory or the fridge\n                    inventory.\n                    ', tunable_type=bool, default=False), ingredient_list=TunableList(description='\n                    List of ingredients the recipe can use\n                    ', tunable=TunableVariant(description='\n                        Possible ingredient mapping by object definition of by \n                        catalog object Tag.\n                        ', ingredient_by_definition=TunableIngredientByDefFactory(), ingredient_by_tag=TunableIngredientByTagFactory())))), 'crafted_by_text': TunableLocalizedStringFactory(description="\n            Text that describes who made it, e.g. 'Made By: <Sim>'. Loc\n            parameter 0 is the Sim crafter.\n            "), 'value_text': TunableLocalizedStringFactory(description="\n            Text (if any) that describes the value in the tooltip.  \n            e.g. 'Value: $500'. Loc parameter 0 is the value.\n            "), 'mood_list': TunableList(description='\n            A list of possible moods this Recipe may associate with. Note that\n            this list is for coloring-purposes only. Interaction availability\n            testing is relegated to the individual mood tests on the\n            interaction. Future refactoring necessary.\n            ', tunable=TunableReference(manager=services.mood_manager()))}
    _tuning_loaded = False
    _referenced_by_start_crafting = False

    @classmethod
    def _tuning_loaded_callback(cls):
        cls._visible_phase_sequence = []
        cls.phases = {phase_id: phase(recipe=cls, phase_id=phase_id) for (phase_id, phase) in cls._phases.items()}
        first_phases = []
        for name in cls._first_phases:
            if name in cls.phases:
                first_phases.append(cls.phases[name])
            else:
                logger.error("Unknown phase '{}' specified in first_phases for recipe '{}'.", name, cls)
        cls.first_phases = first_phases
        for phase in cls.phases.values():
            phase.recipe_tuning_loaded()
        if cls.first_phases:
            cls._build_visible_phase_sequence(cls.first_phases[0])
        cls._tuning_loaded = True
        if cls._referenced_by_start_crafting:
            cls.validate_for_start_crafting()

    @classmethod
    def _verify_tuning_callback(cls):
        if cls.use_ingredients:
            for ingredient in cls.use_ingredients.ingredient_list:
                while ingredient is None:
                    logger.error('Recipe {} has unset ingredients', cls.__name__)
            if not cls.use_ingredients.ingredient_list:
                logger.error('Recipe {} has an empty ingredient list and its tuned to use ingredients.', cls.__name__)
        if not cls.name:
            logger.error('Recipe {} does not have a name set', cls.__name__)
        if not cls.phase_interaction_name:
            logger.error('Recipe {} does not have a phase interaction name set', cls.__name__)
        cls._validate_final_product()
        services.get_instance_manager(sims4.resources.Types.RECIPE).add_on_load_complete(cls.validate_base_recipe)

    @classmethod
    def _validate_final_product(cls):
        if cls.final_product_definition is None:
            return
        supported_states = objects.components.state.get_supported_state(cls.final_product.definition)
        unsupported_values = []
        for state_value in itertools.chain(cls.final_product.initial_states, cls.final_product.apply_states):
            while supported_states is None or state_value.state not in supported_states:
                unsupported_values.append(state_value)
        if supported_states is None:
            error = "\n    A recipe wants to set one or more state value on its final product, but that\n    object doesn't have a StateComponent.  The recipe shouldn't be trying to set\n    any state values, or the object's tuning should be updated to add these\n    states."
        else:
            error = "\n    A recipe wants to set a state value on its final product, but that object's\n    state component tuning doesn't have an entry for that state.  The recipe\n    shouldn't be trying to set these state values, or the object's tuning should\n    be updated to add these states."
        logger.warn('Recipe tuning error:{}\n        Recipe: {}\n        Missing States: {}\n        Final Product: {} ({})'.format(error, cls.__name__, ', '.join(sorted({e.state.__name__ for e in unsupported_values})), cls.final_product.definition.name, cls.final_product.definition.cls.__name__))
        for sa in cls.final_product.super_affordances:
            while sa.consumes_object() or sa.contains_stat(CraftingTuning.CONSUME_STATISTIC):
                logger.error('Recipe: Interaction {} on {} is consume affordance, should tune on ConsumableComponent of the object.', sa.__name__, cls.__name__, owner='tastle/cjiang')

    @classmethod
    def validate_for_start_crafting(cls):
        if not cls._tuning_loaded:
            cls._referenced_by_start_crafting = True
        elif not cls.first_phases:
            logger.error('Recipe is tuned to be craftable but has no first phases defined: {}', cls)

    @classmethod
    def validate_base_recipe(cls, manager):
        base_recipe = cls.base_recipe
        if base_recipe is not None and cls.hidden_until_unlock != base_recipe.hidden_until_unlock:
            logger.error("Recipe({})'s hidden_until_unlock({}) != base_recipe({})'s hidden_until_unlock({})", cls.__name__, cls.hidden_until_unlock, base_recipe.__name__, base_recipe.hidden_until_unlock)

    @classmethod
    def _build_visible_phase_sequence(cls, phase):
        if phase.is_visible:
            cls._visible_phase_sequence.append(phase)
        if phase.next_phases:
            next_phase = phase.next_phases[0]
            cls._build_visible_phase_sequence(next_phase)

    @classproperty
    def final_product_definition(cls):
        return cls.final_product.definition

    @classproperty
    def final_product_definition_id(cls):
        return cls.final_product.definition.id

    @classproperty
    def has_final_product_definition(cls):
        return cls.final_product.definition is not None

    @classproperty
    def final_product_geo_hash(cls):
        if cls.final_product.thumbnail_geo_state is not None:
            return sims4.hash_util.hash32(cls.final_product.thumbnail_geo_state)
        return cls.final_product_definition.thumbnail_geo_state_hash

    @classproperty
    def final_product_material_hash(cls):
        if cls.final_product.thumbnail_material_state is not None:
            return sims4.hash_util.hash32(cls.final_product.thumbnail_material_state)
        return 0

    @classproperty
    def final_product_type(cls):
        return cls.final_product.definition.cls

    @classproperty
    def apply_tags(cls):
        obj_info = cls.final_product
        if obj_info is not None:
            return obj_info.apply_tags
        return set()

    @classmethod
    def get_final_product_quality_adjustment(cls, effective_skill):
        quality_adjustment = cls.final_product.quality_adjustment
        skill_delta = effective_skill - cls.required_skill_level
        quality_value = quality_adjustment.base_quality + skill_delta*quality_adjustment.skill_adjustment
        return quality_value

    @classmethod
    def setup_crafted_object(cls, crafted_object, crafter, is_final_product):
        pass

    @classproperty
    def crafting_price(cls):
        if cls._no_initial_charge:
            return 0
        if isinstance(cls.crafting_cost, int):
            return cls.crafting_cost
        return int(cls._retail_price*cls.crafting_cost)

    @classproperty
    def retail_price(cls):
        return cls._retail_price

    @classproperty
    def simoleon_value_modifiers(cls):
        return cls.final_product.simoleon_value_modifiers_map

    @classproperty
    def simoleon_value_skill_curve(cls):
        return cls.final_product.simoleon_value_skill_curve

    @classproperty
    def masterworks_data(cls):
        return cls.final_product.masterworks

    @classproperty
    def required_skill_level(cls):
        if cls.skill_test is not None:
            return cls.skill_test.skill_range_min
        return 0

    @classproperty
    def required_skill(cls):
        if cls.skill_test is not None:
            return cls.skill_test.skill

    @classmethod
    def get_base_recipe(cls):
        return cls.base_recipe or cls

    @classmethod
    def get_recipe_picker_name(cls, *args):
        if cls.multi_serving_name is not None:
            return cls.multi_serving_name(*args)
        return cls.name(*args)

    @classmethod
    def get_recipe_name(cls, *args):
        return cls.name(*args)

    @classmethod
    def get_price(cls, is_retail=False, ingredient_modifier=1):
        if is_retail:
            if cls.retail_price != 0:
                return cls.retail_price
            return cls.crafting_price
        return cls.crafting_price + int(cls.delta_ingredient_price*ingredient_modifier)

    @classmethod
    def calculate_autonomy_weight(cls, sim):
        total_weight = cls.autonomy_weight
        for (buff, weight) in cls.buff_weight_multipliers.items():
            while sim.has_buff(buff):
                total_weight *= weight
        return total_weight

    @classproperty
    def total_visible_phases(cls):
        return len(cls._visible_phase_sequence)

    @classmethod
    def get_visible_phase_index(cls, phase):
        if phase in cls._visible_phase_sequence:
            return cls._visible_phase_sequence.index(phase) + 1
        return 0

    @classproperty
    def is_single_phase_recipe(cls):
        return len(cls._phases) == 1

    @classmethod
    def update_hovertip(cls, owner, crafter=None):
        description = cls.recipe_description(crafter)
        genre = Genre.get_genre_localized_string(owner)
        if genre is not None:
            description = LocalizationHelperTuning.get_new_line_separated_strings(description, genre)
        value_text = cls.value_text
        if value_text:
            localized_value = value_text(owner.current_value)
            description = LocalizationHelperTuning.get_new_line_separated_strings(description, localized_value)
        objects.components.crafting_component._set_recipe_decription(owner, description)

    @property
    def debug_name(self):
        return type(self).__name__

    @classmethod
    def debug_dump(cls, dump=dump_logger.warn):
        dump('Recipe Name: {}'.format(type(cls).__name__))
        dump('Phases: {}'.format(len(cls.phases)))
        for phase in cls.phases.values():
            dump('  Phase {}:'.format(phase.id))
            while phase.num_turns > 0:
                dump('    Turns: {}'.format(phase.turns))

class CraftingObjectType(metaclass=TunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.RECIPE)):
    __qualname__ = 'CraftingObjectType'
    INSTANCE_TUNABLES = {'unavailable_tooltip': TunableLocalizedStringFactory(description='Tooltip displayed when there are no objects of this type and one is required.')}

def destroy_unentitled_craftables():
    entitlement_map = {}
    objects_to_destroy = list()
    for obj in itertools.chain(services.object_manager().values(), services.inventory_manager().values()):
        crafting_component = obj.crafting_component
        while crafting_component is not None:
            recipe = crafting_component.get_recipe()
            if recipe is not None and recipe.entitlement:
                if recipe.entitlement in entitlement_map:
                    entitled = entitlement_map[recipe.entitlement]
                else:
                    entitled = mtx.has_entitlement(recipe.entitlement)
                    entitlement_map[recipe.entitlement] = entitled
                if not entitled:
                    objects_to_destroy.append(obj)
    for obj in objects_to_destroy:
        obj.destroy(source=obj, cause='Destroying unentitled craftables.')

