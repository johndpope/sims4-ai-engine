import collections
from sims4.repr_utils import standard_repr
from sims4.tuning.tunable import Tunable, TunableRange, TunableSingletonFactory, OptionalTunable, TunableFactory, TunableResourceKey, TunableReference, TunableSimMinute, TunableTuple
from singletons import DEFAULT
import enum
import services
import sims4.hash_util
import sims4.math
import sims4.log
logger = sims4.log.Logger('Objects', default_owner='pingebretson')

class HiddenReasonFlag(enum.IntFlags, export=False):
    __qualname__ = 'HiddenReasonFlag'
    NOT_INITIALIZED = 1
    RABBIT_HOLE = 2
    REPLACEMENT = 4

ALL_HIDDEN_REASONS = HiddenReasonFlag.NOT_INITIALIZED | HiddenReasonFlag.RABBIT_HOLE | HiddenReasonFlag.REPLACEMENT
ALL_HIDDEN_REASONS_EXCEPT_UNINITIALIZED = ALL_HIDDEN_REASONS & ~HiddenReasonFlag.NOT_INITIALIZED

class VisibilityState:
    __qualname__ = 'VisibilityState'
    __slots__ = ('visibility', 'inherits', 'enable_drop_shadow')

    def __init__(self, visibility=True, inherits=None, enable_drop_shadow=False):
        self.visibility = visibility
        self.inherits = inherits
        self.enable_drop_shadow = enable_drop_shadow

    def __repr__(self):
        return standard_repr(self, self.visibility, inherits=self.inherits, enable_drop_shadow=self.enable_drop_shadow)

class MaterialState:
    __qualname__ = 'MaterialState'
    __slots__ = ('state_name_hash', 'opacity', 'transition', 'debug_state_name')

    def __init__(self, state_name, opacity=1.0, transition=0.0):
        if state_name is None:
            self.state_name_hash = 0
        else:
            self.state_name_hash = sims4.hash_util.hash32(state_name)
        self.opacity = sims4.math.clamp(0.0, opacity, 1.0)
        self.transition = transition
        self.debug_state_name = state_name

    def __repr__(self):
        return standard_repr(self, self.debug_state_name, hex(self.state_name_hash), opacity=self.opacity, transition=self.transition)

class PaintingState(collections.namedtuple('_PaintingState', ('texture_id', 'reveal_level', 'use_overlay'))):
    __qualname__ = 'PaintingState'
    REVEAL_LEVEL_MIN = 0
    REVEAL_LEVEL_MAX = 5

    @staticmethod
    def from_key(texture_key, *args, **kwargs):
        texture_id = texture_key.instance
        return PaintingState(texture_id, *args, **kwargs)

    @staticmethod
    def from_name(texture_name, *args, **kwargs):
        texture_id = sims4.hash_util.hash64(texture_name)
        return PaintingState(texture_id, *args, **kwargs)

    def __new__(cls, texture_id, reveal_level:int=0, use_overlay:bool=False):
        if reveal_level < cls.REVEAL_LEVEL_MIN or reveal_level > cls.REVEAL_LEVEL_MAX:
            raise ValueError('reveal_level ({}) is out of range [{} - {}].'.format(reveal_level, cls.REVEAL_LEVEL_MIN, cls.REVEAL_LEVEL_MAX))
        if not isinstance(texture_id, int):
            raise TypeError('texture_id must be an integer.')
        return super().__new__(cls, texture_id, reveal_level, use_overlay)

    @property
    def texture_name(self):
        pass

    @property
    def is_initial(self):
        return self.reveal_level == self.REVEAL_LEVEL_MIN

    @property
    def is_final(self):
        return self.reveal_level == self.REVEAL_LEVEL_MAX

    def get_previous(self):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        if self.is_initial:
            return
        return PaintingState(self.texture_id, self.reveal_level - 1, self.use_overlay)

    def get_next(self):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        if self.is_final:
            return
        return PaintingState(self.texture_id, self.reveal_level + 1, self.use_overlay)

    def get_at_level(self, reveal_level):
        return PaintingState(self.texture_id, reveal_level, self.use_overlay)

    def get_with_use_overlay(self, use_overlay):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        if self.is_final:
            return
        return PaintingState(self.texture_id, self.reveal_level, use_overlay)

    def __repr__(self):
        return standard_repr(self, self.texture_name or self.texture_id, self.reveal_level, self.use_overlay)

class TunableStringOrDefault(OptionalTunable):
    __qualname__ = 'TunableStringOrDefault'

    def __init__(self, default, **kwargs):
        super().__init__(disabled_name='set_to_default_value', enabled_name='set_to_custom_value', tunable=Tunable(str, default), **kwargs)

class TunableModelOrDefault(OptionalTunable):
    __qualname__ = 'TunableModelOrDefault'

    def __init__(self, **kwargs):
        super().__init__(disabled_name='set_to_default_model', enabled_name='set_to_custom_model', tunable=TunableModel(), **kwargs)

class TunableVisibilityState(TunableSingletonFactory):
    __qualname__ = 'TunableVisibilityState'
    FACTORY_TYPE = VisibilityState

    def __init__(self, description='A visibility state.', **kwargs):
        super().__init__(visibility=Tunable(bool, True, description='If True, the object may be visible. If False, the object will not be visible.'), inherits=Tunable(bool, True, description="If True, this object can only be visible if its parent is visible. If False, it may be visible regardless of its parent's visibility."), enable_drop_shadow=Tunable(bool, True, description="If True, this object's drop shadow may be visible.  If False, this object's drop shadow will not be visible."), description=description, **kwargs)

class TunableMaterialState(TunableSingletonFactory):
    __qualname__ = 'TunableMaterialState'
    FACTORY_TYPE = MaterialState

    def __init__(self, description='A material state.', **kwargs):
        super().__init__(state_name=TunableStringOrDefault('materialStateName', description='The name of the material state.'), opacity=TunableRange(float, 1, 0, 1, description='Opacity of the material from ( 0.0 == transparent ) to ( 1.0 == opaque ). Not yet supported on the client.'), transition=TunableSimMinute(0, description='Time to take when transitioning in sim minutes. Not yet supported on the client.'), description=description, **kwargs)

class TunableGeometryState(TunableStringOrDefault):
    __qualname__ = 'TunableGeometryState'

class TunableMaterialVariant(TunableStringOrDefault):
    __qualname__ = 'TunableMaterialVariant'

class TunableModel(TunableSingletonFactory):
    __qualname__ = 'TunableModel'

    @staticmethod
    def _factory(model, model_from_definition):
        if model is not None:
            return model
        defintion = model_from_definition.definition
        if defintion is not None:
            if model_from_definition.also_swap_definition:
                return defintion
            return defintion._model[0]

    FACTORY_TYPE = _factory

    def __init__(self, description='A model state.', **kwargs):

        def validate_definition_swap(instance_class, tunable_name, source, value):
            pass

        super().__init__(model=TunableResourceKey(description='\n                The model file resource key.\n                ', default=None, resource_types=(sims4.resources.Types.MODEL,)), model_from_definition=TunableTuple(definition=TunableReference(description='\n                    The model definition.\n                    ', manager=services.definition_manager()), also_swap_definition=Tunable(description='\n                    If True, the model swap operation will also swap the\n                    definition for the object. If false it will only change the\n                    model. We should only set this to True for sculpture\n                    objects.\n                    ', tunable_type=bool, default=False)), description=description, callback=validate_definition_swap, **kwargs)

