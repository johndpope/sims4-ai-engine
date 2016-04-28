from interactions import ParticipantType
from interactions.liability import Liability
import services
AUTO_INVITE_LIABILTIY = 'AutoInviteLiability'

class AutoInviteLiability(Liability):
    __qualname__ = 'AutoInviteLiability'

    def __init__(self):
        self._target_sim = None
        self._situation_id = None
        self._interaction = None

    def on_add(self, interaction):
        self._interaction = interaction
        self._target_sim = interaction.get_participant(ParticipantType.TargetSim)
        situation_manager = services.get_zone_situation_manager()
        self._situation_id = situation_manager.create_visit_situation(self._target_sim)
        situation_manager.bouncer._assign_instanced_sims_to_unfulfilled_requests()

    def release(self):
        if not self._target_sim.is_on_active_lot():
            situation_manager = services.get_zone_situation_manager()
            situation_manager.destroy_situation_by_id(self._situation_id)

    @property
    def should_transfer(self):
        return False

