from crafting.crafting_tunable import CraftingTuning
from crafting.recipe import Recipe, logger
from event_testing.resolver import SingleSimResolver
from event_testing.tests import TunableTestSet
from objects import PaintingState
from objects.components import crafting_component
from objects.components.canvas_component import CanvasType
from sims4.localization import TunableLocalizedString
from sims4.tuning.instances import TunedInstanceMetaclass, lock_instance_tunables
from sims4.tuning.tunable import TunableResourceKey, TunableEnumFlags, TunableList, TunableTuple, TunableReference, TunableRange
from sims4.utils import classproperty
import services
import sims4.resources

class PaintingTexture(metaclass=TunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.RECIPE)):
    __qualname__ = 'PaintingTexture'
    INSTANCE_TUNABLES = {'texture': TunableResourceKey(None, resource_types=[sims4.resources.Types.TGA]), 'tests': TunableTestSet(), 'canvas_types': TunableEnumFlags(CanvasType, CanvasType.NONE, description='\n            The canvas types (generally, aspect ratios) with which this texture\n            may be used.\n            ')}

    @classmethod
    def _tuning_loaded_callback(cls):
        if cls.texture:
            cls._base_painting_state = PaintingState.from_key(cls.texture)
        else:
            cls._base_painting_state = None

    @classmethod
    def apply_to_object(cls, obj):
        obj.canvas_component.painting_state = cls._base_painting_state

class PaintingStyle(metaclass=TunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.RECIPE)):
    __qualname__ = 'PaintingStyle'
    INSTANCE_TUNABLES = {'_display_name': TunableLocalizedString(description='\n                The style name that will be displayed on the hovertip.\n                '), '_textures': TunableList(description='\n                A set of PaintingTextures from which one will be chosen for an\n                artwork created using this PaintingStyle.\n                ', tunable=TunableTuple(description='\n                    A particular painting texture and a weight indicating how\n                    often it will be picked from among available textures when\n                    this style is used.\n                    ', texture=TunableReference(description='\n                        A particular painting texture to use as part of this\n                        style.\n                        ', manager=services.get_instance_manager(sims4.resources.Types.RECIPE), class_restrictions=(PaintingTexture,)), weight=TunableRange(float, 1.0, minimum=0, description='\n                        The relative likelihood (among available textures) that\n                        this one will be chosen.\n                        ')))}

    @classproperty
    def display_name(cls):
        return cls._display_name

    @classmethod
    def pick_texture(cls, crafter, canvas_types) -> PaintingTexture:
        resolver = SingleSimResolver(crafter.sim_info)
        weights = []
        for weighted_texture in cls._textures:
            weight = weighted_texture.weight
            texture = weighted_texture.texture
            while canvas_types & texture.canvas_types:
                if texture.tests.run_tests(resolver):
                    weights.append((weight, texture))
        texture = sims4.random.pop_weighted(weights)
        if texture is None and cls._textures:
            for weighted_texture in cls._textures:
                weight = weighted_texture.weight
                texture = weighted_texture.texture
                while canvas_types & texture.canvas_types:
                    logger.error('Tuning Error: No texture of {0} passed tests for {1}, defaulting to {2}', cls._textures, crafter.sim_info, texture, owner='nbaker')
                    return texture
            texture = cls._textures[0].texture
            logger.error('Tuning Error: No texture of {0} was correct type for {1}, defaulting to {2}', cls._textures, crafter.sim_info, texture, owner='nbaker')
            return texture
        return texture

class PaintingRecipe(Recipe):
    __qualname__ = 'PaintingRecipe'
    INSTANCE_TUNABLES = {'painting_style': TunableReference(manager=services.get_instance_manager(sims4.resources.Types.RECIPE), class_restrictions=(PaintingStyle,))}

    @classmethod
    def _verify_tuning_callback(cls):
        super()._verify_tuning_callback()
        if cls.painting_style is None:
            logger.error('PaintingRecipe {} does not have a painting_style tuned.', cls.__name__)
        if cls.first_phases and cls.final_product_canvas_tuning is None:
            logger.error("PaintingRecipe {}'s final product does not have a CanvasComponent: {}", cls.__name__, cls.final_product_type)

    @classproperty
    def final_product_canvas_tuning(cls):
        return cls.final_product_type._components.canvas

    @classproperty
    def style_display_name(cls):
        return cls.painting_style.display_name

    @classmethod
    def pick_texture(cls, crafter) -> PaintingTexture:
        canvas_types = cls.final_product_canvas_tuning.canvas_types
        texture = cls.painting_style.pick_texture(crafter, canvas_types)
        return texture

    @classmethod
    def setup_crafted_object(cls, crafted_object, crafter, is_final_product):
        super().setup_crafted_object(crafted_object, crafter, is_final_product)
        if is_final_product:
            texture = cls.pick_texture(crafter)
            if texture is None:
                logger.error('Tuning Error: No texture found for {0}', crafted_object, owner='nbaker')
                return
            texture.apply_to_object(crafted_object)

    @classmethod
    def update_hovertip(cls, owner, crafter=None):
        crafting_component._set_simoleon_value(owner, owner.current_value)
        crafting_component._set_style_name(owner, cls.style_display_name)

lock_instance_tunables(PaintingRecipe, multi_serving_name=None, push_consume=False)
