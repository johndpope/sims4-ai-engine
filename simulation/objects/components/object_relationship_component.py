from collections import defaultdict
from distributor.rollback import ProtocolBufferRollback
from distributor.shared_messages import send_relationship_op
from interactions.utils.loot_basic_op import BaseTargetedLootOperation
from objects.components import Component, types
from objects.components.state import TunableStateValueReference
from protocolbuffers import SimObjectAttributes_pb2 as protocols, Commodities_pb2 as commodity_protocol
from relationships.relationship_track import RelationshipTrack
from sims4.callback_utils import CallableList
from sims4.tuning.tunable import TunableRange, Tunable, HasTunableFactory, OptionalTunable, TunableTuple, TunableList, TunableThreshold
from statistics.statistic import Statistic
import services
import sims4.log
import zone_types
logger = sims4.log.Logger('ObjectRelationshipComponent')

class ObjectRelationshipComponent(Component, HasTunableFactory, component_name=types.OBJECT_RELATIONSHIP_COMPONENT, persistence_key=protocols.PersistenceMaster.PersistableData.ObjectRelationshipComponent):
    __qualname__ = 'ObjectRelationshipComponent'
    FACTORY_TUNABLES = {'number_of_allowed_relationships': OptionalTunable(description='\n            Number of Sims who can have a relationship with this object at one\n            time.  If not specified, an infinite number of Sims can have a \n            relationship with the object.\n            ', tunable=TunableRange(tunable_type=int, default=1, minimum=1)), 'relationship_stat': Statistic.TunableReference(description="\n            The statistic which will be created for each of this object's\n            relationships.\n            "), 'relationship_track_visual': OptionalTunable(RelationshipTrack.TunableReference(description='\n                The relationship that this track will visually try and imitate in\n                regards to static track tack data.  If this is None then this\n                relationship will not be sent down to the client.\n                ')), 'relationship_based_state_change_tuning': OptionalTunable(TunableTuple(description='\n            A list of value ranges and associated states.  If the active Sim\n            has a relationship with this object  that falls within one of the\n            value ranges specified here, the object will change state to match\n            the specified state.\n            \n            These state changes exist on a per Sim basis, so this tuning will\n            effectively make the same object appear different depending on\n            which Sim is currently active.\n            ', state_changes=TunableList(tunable=TunableTuple(value_threshold=TunableThreshold(description="\n                        The range that the active Sim's relationship with this\n                        object must fall within in order for this state change to\n                        take place.\n                        "), state=TunableStateValueReference(description="\n                        The state this object will change to if it's relationship\n                        with the active Sim falls within the specified range.\n                        "))), default_state=TunableStateValueReference(description='\n                The state this object will change to if there is no other tuned\n                relationship based state change for the currently active Sim.\n                ')))}

    def __init__(self, owner, number_of_allowed_relationships, relationship_stat, relationship_track_visual, relationship_based_state_change_tuning):
        super().__init__(owner)
        self._number_of_allowed_relationships = number_of_allowed_relationships
        self._relationship_stat = relationship_stat
        self._relationship_track_visual = relationship_track_visual
        self._relationship_based_state_change_tuning = relationship_based_state_change_tuning
        self._state_changes = None
        self._default_state = None
        self._relationships = {}
        self._relationship_changed_callbacks = defaultdict(CallableList)

    def _on_active_sim_change(self, _, new_sim):
        if new_sim is None:
            return
        relationship = self._get_relationship(new_sim.id)
        self._update_state(relationship)

    def _update_state(self, relationship):
        if self._default_state is None:
            return
        if relationship is None:
            new_state = self._default_state
        elif self._state_changes is None:
            new_state = self._default_state
        else:
            for state_change in self._state_changes:
                while state_change.value_threshold.compare(relationship.get_value()):
                    new_state = state_change.state
                    break
            new_state = self._default_state
        self.owner.set_state(new_state.state, new_state)

    @property
    def _can_add_new_relationship(self):
        if self._number_of_allowed_relationships is not None and len(self._relationships) >= self._number_of_allowed_relationships:
            return False
        return True

    def on_add(self):
        if self._relationship_based_state_change_tuning is None:
            return
        self._state_changes = self._relationship_based_state_change_tuning.state_changes
        self._default_state = self._relationship_based_state_change_tuning.default_state
        services.current_zone().register_callback(zone_types.ZoneState.CLIENT_CONNECTED, self._register_active_sim_change)
        services.current_zone().register_callback(zone_types.ZoneState.HOUSEHOLDS_AND_SIM_INFOS_LOADED, self._publish_relationship_data)

    def on_remove(self):
        client = services.client_manager().get_first_client()
        if client is not None:
            client.unregister_active_sim_changed(self._on_active_sim_change)

    def _register_active_sim_change(self):
        client = services.client_manager().get_first_client()
        if client is not None:
            client.register_active_sim_changed(self._on_active_sim_change)

    def _publish_relationship_data(self):
        if not self._relationship_track_visual:
            return
        for sim_id in self._relationships.keys():
            self._send_relationship_data(sim_id)

    def add_relationship_changed_callback_for_sim_id(self, sim_id, callback):
        self._relationship_changed_callbacks[sim_id].append(callback)

    def remove_relationship_changed_callback_for_sim_id(self, sim_id, callback):
        if sim_id in self._relationship_changed_callbacks and callback in self._relationship_changed_callbacks[sim_id]:
            self._relationship_changed_callbacks[sim_id].remove(callback)

    def _trigger_relationship_changed_callbacks_for_sim_id(self, sim_id):
        callbacks = self._relationship_changed_callbacks[sim_id]
        if callbacks is not None:
            callbacks()

    def add_relationship(self, sim_id):
        if sim_id in self._relationships:
            return False
        if not self._can_add_new_relationship:
            return False
        stat = self._relationship_stat(None)
        self._relationships[sim_id] = stat
        stat.on_add()
        self._send_relationship_data(sim_id)
        self._trigger_relationship_changed_callbacks_for_sim_id(sim_id)
        return True

    def remove_relationship(self, sim_id):
        if sim_id not in self._relationships:
            return
        del self._relationships[sim_id]
        self._trigger_relationship_changed_callbacks_for_sim_id(sim_id)

    def modify_relationship(self, sim_id, value, add=True):
        if not add:
            return
        if not (sim_id not in self._relationships and self.add_relationship(sim_id)):
            return
        self._relationships[sim_id].add_value(value)
        self._send_relationship_data(sim_id)
        self._trigger_relationship_changed_callbacks_for_sim_id(sim_id)
        client = services.client_manager().get_first_client()
        if client is not None and client.active_sim is not None and client.active_sim.sim_id == sim_id:
            self._update_state(self._relationships[sim_id])

    def _get_relationship(self, sim_id):
        return self._relationships.get(sim_id)

    def has_relationship(self, sim_id):
        return sim_id in self._relationships

    def get_relationship_value(self, sim_id):
        relationship = self._get_relationship(sim_id)
        if relationship is not None:
            return relationship.get_value()
        return self._relationship_stat.initial_value

    def get_relationship_initial_value(self):
        return self._relationship_stat.initial_value

    def _send_relationship_data(self, sim_id):
        if self._relationship_track_visual is None:
            return
        relationship_to_send = self._get_relationship(sim_id)
        if not relationship_to_send:
            return
        sim_info = services.sim_info_manager().get(sim_id)
        if sim_info is None:
            return
        msg = commodity_protocol.RelationshipUpdate()
        msg.actor_sim_id = sim_id
        (msg.target_id.object_id, msg.target_id.manager_id) = self.owner.icon_info
        msg.target_instance_id = self.owner.id
        with ProtocolBufferRollback(msg.tracks) as relationship_track_update:
            relationship_value = relationship_to_send.get_value()
            relationship_track_update.track_score = relationship_value
            relationship_track_update.track_bit_id = self._relationship_track_visual.get_bit_at_relationship_value(relationship_value).guid64
            relationship_track_update.track_id = self._relationship_track_visual.guid64
            relationship_track_update.track_popup_priority = self._relationship_track_visual.display_popup_priority
        send_relationship_op(sim_info, msg)

    def save(self, persistence_master_message):
        if not self._relationships:
            return
        persistable_data = protocols.PersistenceMaster.PersistableData()
        persistable_data.type = protocols.PersistenceMaster.PersistableData.ObjectRelationshipComponent
        relationship_component_data = persistable_data.Extensions[protocols.PersistableObjectRelationshipComponent.persistable_data]
        for (key, value) in self._relationships.items():
            with ProtocolBufferRollback(relationship_component_data.relationships) as relationship_data:
                relationship_data.sim_id = key
                relationship_data.value = value.get_value()
        persistence_master_message.data.extend([persistable_data])

    def load(self, persistable_data):
        relationship_component_data = persistable_data.Extensions[protocols.PersistableObjectRelationshipComponent.persistable_data]
        for relationship in relationship_component_data.relationships:
            self.modify_relationship(relationship.sim_id, relationship.value)

class ObjectRelationshipLootOp(BaseTargetedLootOperation):
    __qualname__ = 'ObjectRelationshipLootOp'
    FACTORY_TUNABLES = {'description': '\n            This loot will modify the relationship between an object and a Sim.\n            The target object must have an ObjectRelationshipComponent attached\n            to it for this loot operation to be valid.\n            ', 'amount_to_add': Tunable(description='\n            The amount tuned here will be added to the relationship between the\n            tuned object and Sim.\n            ', tunable_type=int, default=0), 'add_if_nonexistant': Tunable(description="\n            If checked, this relationship will be added if it doesn't currently\n            exist.  If unchecked, it will not be added if it doesn't currently\n            exist.\n            ", tunable_type=bool, default=True), 'remove_relationship': Tunable(description='\n            If checked, the relationship between the tuned object and Sim will\n            be remove if it currently exists.\n            ', tunable_type=bool, default=False)}

    def __init__(self, amount_to_add, add_if_nonexistant, remove_relationship, **kwargs):
        super().__init__(**kwargs)
        self.amount_to_add = amount_to_add
        self.add_if_nonexistant = add_if_nonexistant
        self.remove_relationship = remove_relationship

    def _apply_to_subject_and_target(self, subject, target, resolver):
        if subject is None or target is None:
            logger.error('Invalid subject or target specified for this loot operation. {}  Please fix in tuning.', self)
            return
        object_relationship = target.objectrelationship_component
        if object_relationship is None:
            logger.error('Target {} has no object relationship component.  Please fix in tuning.', target)
            return
        if self.remove_relationship:
            object_relationship.remove_relationship(subject.id)
            return
        object_relationship.modify_relationship(subject.id, self.amount_to_add, add=self.add_if_nonexistant)

