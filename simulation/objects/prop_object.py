from objects.base_object import BaseObject
from objects.client_object_mixin import ClientObjectMixin
from objects.components import forward_to_components
from objects.components.footprint_component import HasFootprintComponent
from objects.components.statistic_component import HasStatisticComponent
from objects.components.types import FOOTPRINT_COMPONENT, STATE_COMPONENT, CENSOR_GRID_COMPONENT, STATISTIC_COMPONENT, VIDEO_COMPONENT
from objects.game_object import GameObject
from objects.mixins import UseListMixin
from sims4.repr_utils import standard_repr, standard_brief_id_repr
from sims4.utils import classproperty
import services

class BasicPropObject(ClientObjectMixin, UseListMixin, BaseObject):
    __qualname__ = 'BasicPropObject'
    VALID_COMPONENTS = ()
    VISIBLE_TO_AUTOMATION = False

    @classproperty
    def is_prop(cls):
        return True

    def __repr__(self):
        return standard_repr(self, self.definition.cls.__name__, self.definition.name or self.definition.id, standard_brief_id_repr(self.id))

    def __str__(self):
        return '[Prop]{}/{}:{}'.format(self.definition.cls.__name__, self.definition.name or self.definition.id, standard_brief_id_repr(self.id))

    @property
    def object_manager_for_create(self):
        return services.prop_manager()

    def can_add_component(self, component_name):
        return any(component_name == valid_component_name.instance_attr for valid_component_name in self.VALID_COMPONENTS)

    @property
    def _anim_overrides_internal(self):
        return self.definition.cls._anim_overrides_cls

    @property
    def is_valid_posture_graph_object(self):
        return False

    def supports_posture_type(self, posture_type):
        return False

    def potential_interactions(self, *_, **__):
        pass

    @property
    def persistence_group(self):
        pass

    @property
    def routing_context(self):
        pass

    def is_surface(self, *args, **kwargs):
        return False

    def get_household_owner_id(self):
        pass

    @property
    def transient(self):
        return False

    @forward_to_components
    def on_state_changed(self, state, old_value, new_value):
        pass

    @property
    def is_outside(self):
        pass

    def is_on_natural_ground(self):
        pass

class PropObject(BasicPropObject, HasStatisticComponent):
    __qualname__ = 'PropObject'
    VALID_COMPONENTS = (STATE_COMPONENT, CENSOR_GRID_COMPONENT, STATISTIC_COMPONENT, VIDEO_COMPONENT)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for component_factory in self.definition.cls._components.values():
            while component_factory is not None:
                self.add_component(component_factory(self))

class PropObjectWithFootprint(BasicPropObject, HasFootprintComponent):
    __qualname__ = 'PropObjectWithFootprint'
    VALID_COMPONENTS = (FOOTPRINT_COMPONENT,)

class PrototypeObject(GameObject):
    __qualname__ = 'PrototypeObject'

    @property
    def is_valid_posture_graph_object(self):
        return False

