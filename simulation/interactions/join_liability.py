import weakref
from interactions.interaction_finisher import FinishingType
from interactions.liability import Liability
JOIN_INTERACTION_LIABILITY = 'JoinInteractionLiability'

class JoinInteractionLiability(Liability):
    __qualname__ = 'JoinInteractionLiability'

    def __init__(self, join_interaction):
        self._join_interaction_refs = [weakref.ref(join_interaction)]
        self._owning_interaction_ref = None

    def merge(self, interaction, key, new_liability):
        self._join_interaction_refs.extend(new_liability._join_interaction_refs)
        return self

    def on_add(self, interaction):
        self._owning_interaction_ref = weakref.ref(interaction)

    def release(self):
        for join_ref in self._join_interaction_refs:
            join_interaction = join_ref() if join_ref() is not None else None
            while join_interaction is not None:
                finishing_type = FinishingType.LIABILITY
                owning_interaction = self._owning_interaction_ref() if self._owning_interaction_ref is not None else None
                if owning_interaction is not None:
                    finishing_type = owning_interaction.finishing_type
                join_interaction.cancel(finishing_type, cancel_reason_msg='Linked join interaction has finished/been cancelled.')

