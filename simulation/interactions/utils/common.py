from element_utils import build_critical_section_with_finally
SCRIPT_EVENT_ID_PLUMBBOB_SHEEN = 601

class InteractionRetargetHandler:
    __qualname__ = 'InteractionRetargetHandler'

    def __init__(self, interaction, target):
        self._target = target
        self._old_target = interaction.target
        self._interaction = interaction

    def begin(self, _):
        self._interaction.set_target(self._target)

    def end(self, _):
        self._interaction.set_target(self._old_target)

def retarget_interaction(interaction, target, *args):
    if interaction is not None:
        interaction_retarget_handler = InteractionRetargetHandler(interaction, target)
        return build_critical_section_with_finally(interaction_retarget_handler.begin, args, interaction_retarget_handler.end)
    return args

