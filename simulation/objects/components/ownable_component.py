from interactions import ParticipantType
from interactions.utils.loot_basic_op import BaseLootOperation
from objects.components import Component, types, componentmethod_with_fallback
from protocolbuffers import SimObjectAttributes_pb2 as protocols
from sims4.tuning.tunable import HasTunableFactory, TunableEnumEntry, Tunable, TunableList, TunableReference
import services
import sims4.resources
import zone_types

class TransferOwnershipLootOp(BaseLootOperation):
    __qualname__ = 'TransferOwnershipLootOp'
    FACTORY_TUNABLES = {'description': "\n            This loot will give ownership of the tuned object to the tuned sim\n            or to the tuned sim's household.\n            ", 'target': TunableEnumEntry(description='\n            The participant of the interaction whom the ownership will be \n            tested on.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'give_sim_ownership': Tunable(description="\n            If True, the sim will be the owner of this object, and the sim's \n            household will be the owning household. If False, the sim's \n            household will own the object and the sim owner will be cleared if\n            the household_id assigned is new.\n            ", tunable_type=bool, default=False)}

    def __init__(self, target, give_sim_ownership, **kwargs):
        super().__init__(target_participant_type=target, **kwargs)
        self._give_sim_ownership = give_sim_ownership

    def _apply_to_subject_and_target(self, subject, target, resolver):
        subject_obj = self._get_object_from_recipient(subject)
        target_obj = self._get_object_from_recipient(target)
        if subject_obj is not None and target_obj is not None:
            target_obj.update_ownership(subject_obj, make_sim_owner=self._give_sim_ownership)

class OwnableComponent(Component, HasTunableFactory, component_name=types.OWNABLE_COMPONENT, persistence_key=protocols.PersistenceMaster.PersistableData.OwnableComponent):
    __qualname__ = 'OwnableComponent'
    DEFAULT_OWNABLE_COMPONENT_AFFORDANCES = TunableList(TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), description='Affordances that all ownable component owners have.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sim_owner_id = None

    def update_sim_ownership(self, new_sim_id):
        self._sim_owner_id = new_sim_id

    @componentmethod_with_fallback(lambda : None)
    def get_sim_owner_id(self):
        return self._sim_owner_id

    def save(self, persistence_master_message):
        if self._sim_owner_id is None:
            return
        persistable_data = protocols.PersistenceMaster.PersistableData()
        persistable_data.type = protocols.PersistenceMaster.PersistableData.OwnableComponent
        ownable_component_data = persistable_data.Extensions[protocols.PersistableOwnableComponent.persistable_data]
        if self._sim_owner_id is not None:
            ownable_component_data.sim_owner_id = self._sim_owner_id
        persistence_master_message.data.extend([persistable_data])

    def _owning_sim_in_owning_household(self, sim_id):
        owner_household_id = self.owner.get_household_owner_id()
        if sim_id is None or owner_household_id is None:
            return False
        household = services.household_manager().get(owner_household_id)
        if household is None:
            return False
        return household.sim_in_household(sim_id)

    def _on_households_loaded_verify(self):
        if not self._owning_sim_in_owning_household(self._sim_owner_id):
            self._sim_owner_id = None
        else:
            self.owner.update_object_tooltip()

    def load(self, persistable_data):
        ownable_component_data = persistable_data.Extensions[protocols.PersistableOwnableComponent.persistable_data]
        if ownable_component_data.HasField('sim_owner_id'):
            self._sim_owner_id = ownable_component_data.sim_owner_id
            services.current_zone().register_callback(zone_types.ZoneState.HOUSEHOLDS_AND_SIM_INFOS_LOADED, self._on_households_loaded_verify)

    def component_super_affordances_gen(self, **kwargs):
        for affordance in self.DEFAULT_OWNABLE_COMPONENT_AFFORDANCES:
            yield affordance

