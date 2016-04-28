from objects.components.state import CommodityBasedObjectState, CommodityBasedObjectStateValue, ObjectStateValue
from sims4.localization import TunableLocalizedStringFactory, LocalizationHelperTuning
from sims4.tuning.tunable import TunableMapping, TunableTuple, Tunable, TunableList, TunableEnumEntry, TunableVariant, TunableReference, TunableFactory
from singletons import DEFAULT
import services
import tag

class IngredientTuning:
    __qualname__ = 'IngredientTuning'
    INGREDIENT_QUALITY_MAPPING = TunableMapping(description='\n        Mapping of all possible ingredient quality states to what possible\n        states will the ingredients have.\n        e.g. High quality ingredients need to be mapped to gardening high \n        quality, fish high quality or any state that will indicate what \n        high quality means on a different system.\n        ', key_type=ObjectStateValue.TunableReference(description='\n            The states that will define the ingredient quality.\n            '), value_type=TunableTuple(description='\n            Definition of the ingredient quality state.  This will define\n            the quality boost on the recipe and the possible states an \n            ingredient can have to have this state.\n            ', quality_boost=Tunable(description='\n                Value that will be added to the quality commodity whenever\n                this state is added.\n                ', tunable_type=int, default=1), state_value_list=TunableList(description='\n                List of ingredient states that will give this level of \n                ingredient quality.\n                ', tunable=ObjectStateValue.TunableReference(description='\n                    The states that will define the ingredient quality.\n                    '))))
    INGREDIENT_TAG_DISPLAY_MAPPING = TunableMapping(description='\n        Mapping of all object tags to their localized string that will display\n        on the ingredient list.\n        This will be used for displaying on the recipe\'s when an ingredient is \n        tuned by tag instead of object definition.\n        Example: Display objects of rag FISH as string "Any Fish"\n        ', key_type=TunableEnumEntry(description='\n            Tag corresponding at an ingredient type that can be used in a\n            recipe.\n            ', tunable_type=tag.Tag, default=tag.Tag.INVALID), value_type=TunableLocalizedStringFactory())
    INGREDIENT_TAG = TunableEnumEntry(description='\n        Tag to look for when iterating through objects to know if they are \n        ingredients.\n        All ingredients should be tuned with this tag.\n        ', tunable_type=tag.Tag, default=tag.Tag.INVALID)

    @classmethod
    def get_quality_bonus(cls, ingredient):
        for quality_details in IngredientTuning.INGREDIENT_QUALITY_MAPPING.values():
            for state_value in quality_details.state_value_list:
                while ingredient.state_value_active(state_value):
                    return quality_details.quality_boost
        return 0

    @classmethod
    def get_ingredient_quality_state(cls, quality_bonus):
        state_to_add = None
        bonus_selected = None
        for (quality_state_value, quality_details) in IngredientTuning.INGREDIENT_QUALITY_MAPPING.items():
            while (bonus_selected is None or quality_details.quality_boost <= bonus_selected) and bonus_selected >= quality_bonus:
                bonus_selected = quality_details.quality_boost
                state_to_add = quality_state_value
        return state_to_add

    @classmethod
    def get_ingredient_string_for_tag(cls, tag):
        string_factory = IngredientTuning.INGREDIENT_TAG_DISPLAY_MAPPING.get(tag)
        if string_factory:
            return string_factory()
        return

class Ingredient:
    __qualname__ = 'Ingredient'

    def __init__(self, definition, inventory_location=DEFAULT, catalog_tag=None):
        self._definition = definition
        if inventory_location is DEFAULT:
            self._inventory_locations = []
        else:
            self._inventory_locations = [inventory_location]
        self._catalog_tag = catalog_tag

    def add_inventory_location(self, inventory_location):
        self._inventory_locations.append(inventory_location)

    def get_diplay_name(self):
        return LocalizationHelperTuning.get_object_name(self._definition)

class TunableIngredientByDefFactory(TunableFactory):
    __qualname__ = 'TunableIngredientByDefFactory'

    @staticmethod
    def factory(candidate_ingredients, ingredient_ref):
        for ingredient in candidate_ingredients:
            while ingredient.id == ingredient_ref.id:
                return ([ingredient], None, LocalizationHelperTuning.get_object_name(ingredient_ref))
        return ([], None, LocalizationHelperTuning.get_object_name(ingredient_ref))

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(ingredient_ref=TunableReference(services.definition_manager(), description='Reference to ingredient object.'), description='This option uses an object definition as an individual ingredient.', **kwargs)

class TunableIngredientByTagFactory(TunableFactory):
    __qualname__ = 'TunableIngredientByTagFactory'

    @staticmethod
    def factory(candidate_ingredients, ingredient_tag):
        valid_ingredients = []
        for ingredient in candidate_ingredients:
            while ingredient.has_build_buy_tag(ingredient_tag):
                valid_ingredients.append(ingredient)
        return (valid_ingredients, ingredient_tag, None)

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(ingredient_tag=TunableEnumEntry(description='Tag that ingredient object should have.', tunable_type=tag.Tag, default=tag.Tag.INVALID), description='This option uses an object definition as an individual ingredient.', **kwargs)

