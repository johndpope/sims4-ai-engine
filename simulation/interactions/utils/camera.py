from camera import focus_on_sim
from interactions import ParticipantType
from interactions.utils.interaction_elements import XevtTriggeredElement
from sims4.tuning.tunable import TunableEnumEntry, Tunable, AutoFactoryInit, HasTunableFactory

class CameraFocusElement(XevtTriggeredElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'CameraFocusElement'
    FACTORY_TUNABLES = {'description': '\n            Focus the camera on the specified participant.\n            ', 'participant': TunableEnumEntry(description='\n            The participant of this interaction to focus the camera on.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'follow': Tunable(description='\n            Whether or not the camera should stick to the focused participant.\n            ', tunable_type=bool, default=False)}

    def _do_behavior(self):
        subject = self.interaction.get_participant(self.participant)
        if subject is not None:
            focus_on_sim(sim=subject, follow=self.follow, client=subject.client)

