from interactions.base.super_interaction import SuperInteraction
from sims4.tuning.tunable import TunableReference
import services

class StandSuperInteraction(SuperInteraction):
    __qualname__ = 'StandSuperInteraction'
    STAND_POSTURE_TYPE = TunableReference(services.posture_manager(), description='The Posture Type for the Stand posture.')

    @classmethod
    def _is_linked_to(cls, super_affordance):
        return cls is not super_affordance

    def _get_cancel_replacement_aops_contexts_postures(self, can_transfer_ownership=True, carry_cancel_override=None):
        if self.target is None:
            return []
        return super()._get_cancel_replacement_aops_contexts_postures(can_transfer_ownership=can_transfer_ownership, carry_cancel_override=carry_cancel_override)

