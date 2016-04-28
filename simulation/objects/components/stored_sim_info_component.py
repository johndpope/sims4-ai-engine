from protocolbuffers import SimObjectAttributes_pb2 as protocols
from interactions import ParticipantType
from interactions.utils.interaction_elements import XevtTriggeredElement
from objects.components import Component, types, componentmethod_with_fallback
from sims4.tuning.tunable import AutoFactoryInit, HasTunableFactory, TunableEnumEntry, OptionalTunable
import services
import zone_types

class StoreSimElement(XevtTriggeredElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'StoreSimElement'
    FACTORY_TUNABLES = {'description': '\n            An element that retrieves an interaction participant and attaches\n            its information to another interaction participant using a dynamic\n            StoredSimInfoComponent.\n            ', 'source_participant': OptionalTunable(description='\n            Specify what participant to store on the destination participant.\n            ', tunable=TunableEnumEntry(description='\n                The participant of this interaction whose Sim Info is retrieved\n                to be stored as a component.\n                ', tunable_type=ParticipantType, default=ParticipantType.PickedObject), enabled_name='specific_participant', disabled_name='no_participant'), 'destination_participant': TunableEnumEntry(description='\n            The participant of this interaction to which a\n            StoredSimInfoComponent is added, with the Sim Info of\n            source_participant.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object)}

    def _do_behavior(self):
        source = self.interaction.get_participant(participant_type=self.source_participant) if self.source_participant is not None else None
        destination = self.interaction.get_participant(participant_type=self.destination_participant)
        if destination.has_component(types.STORED_SIM_INFO_COMPONENT.instance_attr):
            destination.remove_component(types.STORED_SIM_INFO_COMPONENT.instance_attr)
        if source is not None:
            destination.add_dynamic_component(types.STORED_SIM_INFO_COMPONENT.instance_attr, sim_id=source.id)

class StoredSimInfoComponent(Component, component_name=types.STORED_SIM_INFO_COMPONENT, allow_dynamic=True, persistence_key=protocols.PersistenceMaster.PersistableData.StoredSimInfoComponent):
    __qualname__ = 'StoredSimInfoComponent'

    def __init__(self, *args, sim_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._sim_id = sim_id

    def save(self, persistence_master_message):
        persistable_data = protocols.PersistenceMaster.PersistableData()
        persistable_data.type = protocols.PersistenceMaster.PersistableData.StoredSimInfoComponent
        stored_sim_info_component_data = persistable_data.Extensions[protocols.PersistableStoredSimInfoComponent.persistable_data]
        stored_sim_info_component_data.sim_id = self._sim_id
        persistence_master_message.data.extend([persistable_data])

    def load(self, persistable_data):
        stored_sim_info_component_data = persistable_data.Extensions[protocols.PersistableStoredSimInfoComponent.persistable_data]
        self._sim_id = stored_sim_info_component_data.sim_id
        services.current_zone().register_callback(zone_types.ZoneState.HOUSEHOLDS_AND_SIM_INFOS_LOADED, self._on_households_loaded_update)

    def _on_households_loaded_update(self):
        self.owner.update_object_tooltip()

    @componentmethod_with_fallback(lambda : None)
    def get_stored_sim_id(self):
        return self._sim_id

    @componentmethod_with_fallback(lambda : None)
    def get_stored_sim_info(self):
        return services.sim_info_manager().get(self._sim_id)

    def component_interactable_gen(self):
        yield self

