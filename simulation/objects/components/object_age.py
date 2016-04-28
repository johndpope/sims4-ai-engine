from objects.components import Component, componentmethod, types, componentmethod_with_fallback
from protocolbuffers import SimObjectAttributes_pb2 as persistence_protocols
from sims4.tuning.tunable import TunableFactory
import services

class ObjectAgeComponent(Component, component_name=types.OBJECT_AGE_COMPONENT, persistence_key=persistence_protocols.PersistenceMaster.PersistableData.ObjectAgeComponent):
    __qualname__ = 'ObjectAgeComponent'

    def __init__(self, owner):
        super().__init__(owner)
        self._object_age = 0
        self._loaded_tick = services.time_service().sim_now.absolute_ticks()
        self._last_used = self._loaded_tick

    def save(self, persistence_master_message):
        persistable_data = persistence_protocols.PersistenceMaster.PersistableData()
        persistable_data.type = persistence_protocols.PersistenceMaster.PersistableData.ObjectAgeComponent
        obj_age_data = persistable_data.Extensions[persistence_protocols.PersistableObjectAgeComponent.persistable_data]
        obj_age_data.age = self.get_current_age()
        obj_age_data.saved_tick = services.time_service().sim_now.absolute_ticks()
        persistence_master_message.data.extend([persistable_data])

    def load(self, state_component_message):
        obj_age_data = state_component_message.Extensions[persistence_protocols.PersistableObjectAgeComponent.persistable_data]
        saved_tick = obj_age_data.saved_tick
        self._loaded_tick = saved_tick
        current_tick = services.time_service().sim_now.absolute_ticks()
        self._object_age = obj_age_data.age + current_tick - saved_tick

    @componentmethod_with_fallback(lambda : False)
    def is_disposable(self):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return True

    @componentmethod
    def get_current_age(self):
        current_tick = services.time_service().sim_now.absolute_ticks()
        return self._object_age + current_tick - self._loaded_tick

    @componentmethod
    def get_last_used(self):
        return self._last_used

    @componentmethod
    def update_last_used(self):
        self._last_used = services.time_service().sim_now.absolute_ticks()

class TunableObjectAgeComponent(TunableFactory):
    __qualname__ = 'TunableObjectAgeComponent'
    FACTORY_TYPE = ObjectAgeComponent

    def __init__(self, callback=None, **kwargs):
        super().__init__(description='Record the age of the object.', **kwargs)

