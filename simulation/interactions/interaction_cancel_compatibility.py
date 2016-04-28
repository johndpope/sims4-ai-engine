from interactions.context import InteractionSource
from sims4.tuning.tunable import TunableMapping, TunableEnumEntry
from snippets import TunableAffordanceFilterSnippet
import enum
import sims4
logger = sims4.log.Logger('InteractionCancelCompatibility', default_owner='jjacobson')

class InteractionCancelReason(enum.Int):
    __qualname__ = 'InteractionCancelReason'
    DEATH = Ellipsis
    FIRE = Ellipsis
    WEDDING = Ellipsis

    @classmethod
    def get_next_reason(cls, reason):
        if reason == cls.DEATH:
            return
        val = reason - 1
        return InteractionCancelReason(val)

class InteractionCancelCompatibility:
    __qualname__ = 'InteractionCancelCompatibility'
    INTERACTION_CANCEL_COMPATIBILITY = TunableMapping(description='\n        A mapping between cancel reasons and affordance filters.  When a reason\n        is requested it runs the interaction though the affordance filter that\n        is requested along with all affordance filters in the hierarchy above\n        it.\n        \n        For example, the wedding will ensure the the interaction matches the\n        wedding, fire, and death reasons.\n        \n        The hierarchy of reasons is defined within python.  GPE support will be\n        needed to change or add new values to the hierarchy of reasons.\n        ', key_type=TunableEnumEntry(description='\n            An interaction canceling reason.\n            ', tunable_type=InteractionCancelReason, default=InteractionCancelReason.DEATH), value_type=TunableAffordanceFilterSnippet(description='\n            An affordance filter that defines which interactions are able to\n            be canceled.  If the interaction is not compatible with the\n            affordance filter then it will be canceled.\n            ', needs_tuning=True))

    @classmethod
    def can_cancel_interaction_for_reason(cls, interaction, reason):
        while reason is not None:
            interaction_compatibility_filter = cls.INTERACTION_CANCEL_COMPATIBILITY.get(reason)
            if interaction_compatibility_filter is None:
                logger.warn('InteractionCancelReason {} not found within the INTERACTION_CANCEL_HIARCHY tuning skipping to next reason.', reason)
            elif interaction_compatibility_filter(interaction):
                return False
            reason = InteractionCancelReason.get_next_reason(reason)
        return True

    @classmethod
    def cancel_interactions_for_reason(cls, sim, reason, finishing_type, cancel_reason_msg):
        sim_interactions = sim.get_all_running_and_queued_interactions()
        for interaction in sim_interactions:
            while cls.check_if_source_should_be_canceled(interaction.context) and cls.can_cancel_interaction_for_reason(interaction.affordance, reason):
                interaction.cancel(finishing_type, cancel_reason_msg=cancel_reason_msg)

    @classmethod
    def check_if_source_should_be_canceled(cls, context):
        if context.source is not InteractionSource.PIE_MENU and context.source is not InteractionSource.AUTONOMY and context.source is not InteractionSource.SCRIPT_WITH_USER_INTENT:
            return False
        return True

