#ERROR: jaddr is None
import weakref
from distributor.shared_messages import EMPTY_ICON_INFO_DATA, IconInfoData
from interactions.interaction_finisher import FinishingType
from objects.components import ComponentContainer, forward_to_components, call_component_func
from objects.components.types import CARRYABLE_COMPONENT
from objects.object_enums import ResetReason
from services.reset_and_delete_service import ResetRecord
from sims4.callback_utils import protected_callback
from sims4.collections import frozendict
from sims4.repr_utils import standard_repr, standard_brief_id_repr
from sims4.utils import classproperty
import build_buy
import caches
import elements
import event_testing
import objects.components
import objects.system
import services
import sims4.log
from element_utils import build_element
logger = sims4.log.Logger('Objects')
logger_reset = sims4.log.Logger('Reset')

class BaseObject(ComponentContainer):
    __qualname__ = 'BaseObject'

    def __init__(self, definition, tuned_native_components=frozendict(), **kwargs):
        super().__init__()
        self.id = 0
        self.manager = None
        self.definition = definition
        self.visible_to_client = False
        self.interaction_refs = set()
        if definition is not None:
            services.definition_manager().register_definition(definition.id, self)
            for component_id in definition.components:
                comp = objects.components.native_component_id_to_class[component_id]
                if not comp.has_server_component():
                    pass
                factory = tuned_native_components.get(comp.CNAME) or comp.create_component
                self.add_component(factory(self))

    def __repr__(self):
        guid = getattr(self, 'id', None)
        if guid is not None:
            return standard_repr(self, standard_brief_id_repr(guid))
        return standard_repr(self)

    def __str__(self):
        guid = getattr(self, 'id', None)
        if guid is not None:
            return '{}:{}'.format(self.__class__.__name__, standard_brief_id_repr(guid))
        return '{}'.format(self.__class__.__name__)

    @classmethod
    def get_class_for_obj_state(cls, obj_state):
        if cls._object_state_remaps and obj_state < len(cls._object_state_remaps):
            definition = cls._object_state_remaps[obj_state]
            if definition is not None:
                return definition.cls
        return cls

    @classproperty
    def is_sim(cls):
        return False

    @classproperty
    def is_prop(cls):
        return False

    @property
    def valid_for_distribution(self):
        return self.visible_to_client

    @property
    def zone_id(self):
        if self.manager is None:
            logger.error('Attempting to retrieve a zone id from an object: {} that is not in a manager.', self)
            return
        return self.manager.zone_id

    @property
    def object_manager_for_create(self):
        return services.object_manager()

    @property
    def wall_or_fence_placement(self):
        placement_flags = build_buy.get_object_placement_flags(self.definition.id)
        if placement_flags & build_buy.PlacementFlags.WALL_GRAPH_PLACEMENT:
            return True
        return False

    def ref(self, callback=None):
        return weakref.ref(self, protected_callback(callback))

    def resolve(self, type_or_tuple):
        if isinstance(self, type_or_tuple):
            return self

    def resolve_retarget(self, new_target):
        return new_target

    def reset_reason(self):
        return services.get_reset_and_delete_service().get_reset_reason(self)

    def reset(self, reset_reason, source=None, cause=None):
        services.get_reset_and_delete_service().trigger_reset(self, reset_reason, source, cause)

    def on_reset_notification(self, reset_reason):
        pass

    def on_reset_get_elements_to_hard_stop(self, reset_reason):
        return []

    def on_reset_get_interdependent_reset_records(self, reset_reason, reset_records):
        self.on_reset_component_get_interdependent_reset_records(reset_reason, reset_records)
        for interaction in list(self.interaction_refs):
            if reset_reason != ResetReason.BEING_DESTROYED:
                transition_controller = interaction.sim.queue.transition_controller
                if transition_controller is not None and transition_controller.will_derail_if_given_object_is_reset(self):
                    pass
            while interaction.should_reset_based_on_pipeline_progress:
                self.interaction_refs.remove(interaction)
                reset_records.append(ResetRecord(interaction.sim, ResetReason.RESET_EXPECTED, self, 'Actor in interaction targeting source. {}, {}'.format(interaction, interaction.pipeline_progress)))

    @forward_to_components
    def on_reset_component_get_interdependent_reset_records(self, reset_reason, reset_records):
        pass

    def on_reset_early_detachment(self, reset_reason):
        orig_list = list(self.interaction_refs)
        for interaction in list(orig_list):
            while not interaction.should_reset_based_on_pipeline_progress:
                self.interaction_refs.remove(interaction)
                interaction.cancel(FinishingType.OBJECT_CHANGED, cancel_reason_msg='object destroyed')

    def on_reset_send_op(self, reset_reason):
        pass

    def on_reset_internal_state(self, reset_reason):
        self.component_reset(reset_reason)

    def on_reset_destroy(self):
        self.manager.remove(self)

    def on_reset_restart(self):
        self.post_component_reset()
        return True

    @forward_to_components
    def component_reset(self, reset_reason):
        pass

    @forward_to_components
    def post_component_reset(self):
        pass

    def destroy(self, source=None, cause=None):
        services.get_reset_and_delete_service().trigger_destroy(self, source=source, cause=cause)

    def schedule_destroy_asap(self, post_delete_func=None, source=None, cause=None):

        def call_destroy(timeline):
            if services.reset_and_delete_service.can_be_destroyed(self):
                self.destroy(source=source, cause=cause)

        element = elements.CallbackElement(elements.FunctionElement(call_destroy), complete_callback=post_delete_func, hard_stop_callback=post_delete_func, teardown_callback=None)
        services.time_service().sim_timeline.schedule_asap(element)

    def schedule_reset_asap(self, reset_reason=ResetReason.RESET_EXPECTED, source=None, cause=None):

        def call_reset(timeline):
            self.reset(reset_reason, source=source, cause=cause)

        element = build_element(call_reset)
        services.time_service().sim_timeline.schedule_asap(element)

    def remove_from_client(self):
        return objects.system.remove_object_from_client(self)

    @property
    def is_valid_posture_graph_object(self):
        return not self.has_component(CARRYABLE_COMPONENT)

    @property
    def icon(self):
        if self.definition is not None:
            return self.definition.icon

    def get_icon_info_data(self):
        if self.manager is not None:
            return IconInfoData(obj_instance=self)
        return EMPTY_ICON_INFO_DATA

    @property
    def icon_info(self):
        if self.manager is not None:
            return (self.definition.id, self.manager.id)
        return (None, None)

    @property
    def manager_id(self):
        if self.manager is not None:
            return self.manager.id
        return 0

    @forward_to_components
    def pre_add(self, manager):
        pass

    @forward_to_components
    def on_add(self):
        pass

    @forward_to_components
    def on_client_connect(self, client):
        pass

    @forward_to_components
    def on_add_to_client(self):
        pass

    @forward_to_components
    def on_remove_from_client(self):
        pass

    @forward_to_components
    def on_added_to_inventory(self):
        pass

    @forward_to_components
    def on_removed_from_inventory(self):
        pass

    @forward_to_components
    def on_remove(self):
        pass

    @forward_to_components
    def post_remove(self):
        services.get_event_manager().process_event(event_testing.test_events.TestEvent.ObjectDestroyed, obj=self)

    def add_component(self, component):
        if super().add_component(component) and self.id:
            call_component_func(component, 'pre_add', self.object_manager_for_create)
            call_component_func(component, 'on_add')

    def remove_component(self, name):
        component = super().remove_component(name)
        if component is not None and self.id:
            call_component_func(component, 'on_remove_from_client')
            call_component_func(component, 'on_remove')
            call_component_func(component, 'post_remove')

    @property
    def parts(self):
        return getattr(self, '_parts', None)

    @property
    def is_part(self):
        return False

    @property
    def _anim_overrides_internal(self):
        pass

    @caches.cached
    def get_anim_overrides(self, actor_name):
        anim_overrides = self._anim_overrides_internal
        if anim_overrides is None:
            return
        if actor_name is not None and anim_overrides.params:
            return anim_overrides(params={(key, actor_name): value for (key, value) in anim_overrides.params.items()})
        return anim_overrides

    def get_param_overrides(self, actor_name, only_for_keys=None):
        anim_overrides = self._anim_overrides_internal
        if anim_overrides is None:
            return
        if actor_name is not None and anim_overrides.params:
            return {(key, actor_name): value for (key, value) in anim_overrides.params.items() if key in only_for_keys}
        return anim_overrides.params

    def children_recursive_gen(self, include_self=False):
        if include_self:
            yield self

    def parenting_hierarchy_gen(self):
        yield self

    def add_interaction_reference(self, interaction):
        self.interaction_refs.add(interaction)

    def remove_interaction_reference(self, interaction):
        if interaction in self.interaction_refs:
            self.interaction_refs.remove(interaction)

    def cancel_interactions_running_on_object(self, finishing_type, cancel_reason_msg):
        for interaction in tuple(self.interaction_refs):
            if interaction not in self.interaction_refs:
                pass
            interaction.cancel(finishing_type, cancel_reason_msg=cancel_reason_msg)

