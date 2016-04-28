from interactions import ParticipantType
from interactions.utils.interaction_elements import XevtTriggeredElement
from sims4.tuning.tunable import AutoFactoryInit, HasTunableFactory, TunableVariant, TunableTuple, TunableEnumEntry
import distributor
import services

class InviteSimElement(XevtTriggeredElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'InviteSimElement'
    INVITE_TYPE_STORED_SIM = 0
    FACTORY_TUNABLES = {'description': '\n            An element that spawns a specified Sim using the filter system.\n            ', 'invite_data': TunableVariant(description='\n            Define a method to retrieve the ID of the Sim to invite.\n            ', use_stored_sim=TunableTuple(locked_args={'invite_type': INVITE_TYPE_STORED_SIM}, participant=TunableEnumEntry(description='\n                    The participant of this interaction with the Stored Sim we\n                    want to invite.\n                    ', tunable_type=ParticipantType, default=ParticipantType.Object)))}

    def _get_invited_sim_id(self):
        invite_data = self.invite_data
        if invite_data.invite_type == self.INVITE_TYPE_STORED_SIM:
            participant = self.interaction.get_participant(self.invite_data.participant)
            if participant is None:
                return
            return participant.get_stored_sim_id()

    def _do_behavior(self):
        invited_sim_id = self._get_invited_sim_id()
        if invited_sim_id:
            op = distributor.ops.TravelBringToZone([invited_sim_id, 0, services.current_zone().id, 0])
            distributor.system.Distributor.instance().add_op(self.interaction.sim, op)
            return True
        return False

