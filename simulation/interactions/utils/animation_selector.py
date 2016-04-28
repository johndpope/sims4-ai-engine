from interactions import ParticipantTypeAnimation
from animation import AnimationContext
from interactions import ParticipantType, ParticipantTypeReactionlet
from interactions.utils.animation_reference import TunableAnimationReference
from sims4.tuning.tunable import TunableFactory, TunableList, TunableTuple, TunableEnumFlags, TunableVariant
from singletons import DEFAULT

class TunableAnimationSelectorParticipant(TunableFactory):
    __qualname__ = 'TunableAnimationSelectorParticipant'

    @staticmethod
    def factory(interaction, groups, sequence=(), sim=DEFAULT, **kwargs):
        if sim is DEFAULT:
            sim = interaction.sim
        if groups:
            for g in groups:
                while sim in interaction.get_participants(g.group):
                    return g.animation_ref(interaction, sequence=sequence, **kwargs)

    FACTORY_TYPE = factory

    def __init__(self, locked_animation_args=DEFAULT, animation_callback=DEFAULT, interaction_asm_type=DEFAULT, override_animation_context=False, participant_enum_override=DEFAULT, description='There is an arbitrary number of possible animation selectors, based on participation in group.', **kwargs):
        if participant_enum_override is DEFAULT:
            participant_enum_type = ParticipantTypeAnimation
            participant_enum_default = ParticipantTypeAnimation.Invalid
        else:
            participant_enum_type = participant_enum_override[0]
            participant_enum_default = participant_enum_override[1]
        super().__init__(groups=TunableList(TunableTuple(group=TunableEnumFlags(participant_enum_type, participant_enum_default, description='The group the Sim must be a participant of'), animation_ref=TunableAnimationReference(allow_reactionlets=False, override_animation_context=override_animation_context, callback=animation_callback)), description='A list of difficulty to animation mappings.'), description=description, **kwargs)

class TunableAnimationSelector(TunableFactory):
    __qualname__ = 'TunableAnimationSelector'

    @staticmethod
    def factory(interaction, selector, sequence=(), **kwargs):
        if selector is None:
            return
        return selector(interaction, sequence=sequence, **kwargs)

    FACTORY_TYPE = factory

    def __init__(self, locked_animation_args=DEFAULT, animation_callback=DEFAULT, interaction_asm_type=DEFAULT, override_animation_context=False, participant_enum_override=DEFAULT, description='An animation to play based on the behavior of selector.', **kwargs):
        super().__init__(selector=TunableVariant(single_ref=TunableAnimationReference(allow_reactionlets=False, interaction_asm_type=interaction_asm_type, override_animation_context=override_animation_context, callback=animation_callback), participant=TunableAnimationSelectorParticipant(locked_animation_args=locked_animation_args, animation_callback=animation_callback, interaction_asm_type=interaction_asm_type, override_animation_context=override_animation_context, participant_enum_override=participant_enum_override), default='single_ref'), description=description, **kwargs)

