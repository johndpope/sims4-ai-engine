from interactions import ParticipantType
from interactions.utils.interaction_elements import XevtTriggeredElement
from sims4.tuning.tunable import TunableEnumEntry
from vfx import PlayEffect

class PlayVisualEffectElement(XevtTriggeredElement):
    __qualname__ = 'PlayVisualEffectElement'
    FACTORY_TUNABLES = {'vfx': PlayEffect.TunableFactory(description='\n            The effect to play.\n            '), 'participant': TunableEnumEntry(description='\n            The participant to play the effect on.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._running_vfx = None

    def _do_behavior(self):
        self._start_vfx()

    def _start_vfx(self):
        if self._running_vfx is None:
            participant = self.interaction.get_participant(self.participant)
            if participant is not None:
                self._running_vfx = self.vfx(participant)
                self._running_vfx.start_one_shot()

