import random
from interactions import ParticipantType
from sims4.tuning.tunable import TunableFactory, TunableResourceKey, TunableEnumFlags, TunableVariant
import sims4.resources

class TunableIcon(TunableResourceKey):
    __qualname__ = 'TunableIcon'

    def __init__(self, *, description='The icon image to be displayed.', **kwargs):
        super().__init__(None, resource_types=sims4.resources.CompoundTypes.IMAGE, **kwargs)

class TunableIconFactory(TunableFactory):
    __qualname__ = 'TunableIconFactory'

    @staticmethod
    def factory(_, key, balloon_target_override=None, **kwargs):
        if balloon_target_override is not None:
            return (None, balloon_target_override)
        return (key, None)

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(key=TunableResourceKey(None, resource_types=sims4.resources.CompoundTypes.IMAGE), description='The icon image to be displayed.', **kwargs)

class TunableParticipantTypeIconFactory(TunableFactory):
    __qualname__ = 'TunableParticipantTypeIconFactory'

    @staticmethod
    def factory(resolver, participant_type, balloon_target_override=None, **kwargs):
        if balloon_target_override is not None:
            return (None, balloon_target_override)
        icon_targets = resolver.get_participants(participant_type)
        if icon_targets:
            chosen_object = random.choice(icon_targets)
        else:
            chosen_object = None
        return (None, chosen_object)

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(participant_type=TunableEnumFlags(ParticipantType, ParticipantType.Actor), description="The Sim who's thumbnail will be used.", **kwargs)

class TunablePrivacyIconFactory(TunableFactory):
    __qualname__ = 'TunablePrivacyIconFactory'

    @staticmethod
    def factory(resolver, balloon_target_override=None, **kwargs):
        if balloon_target_override is not None:
            return (None, balloon_target_override)
        from interactions.base.interaction import PRIVACY_LIABILITY
        privacy_liability = resolver.get_liability(PRIVACY_LIABILITY)
        if privacy_liability:
            violators = privacy_liability.privacy.violators
            if violators:
                return (None, random.choice(list(violators)))
        return (None, None)

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(description="\n            Search an interaction's privacy liability to find violating Sims\n            and randomly select one to display an icon of.\n            ", **kwargs)

class TunableIconVariant(TunableVariant):
    __qualname__ = 'TunableIconVariant'

    def __init__(self, default='resource_key', **kwargs):
        super().__init__(resource_key=TunableIconFactory(), participant=TunableParticipantTypeIconFactory(), privacy=TunablePrivacyIconFactory(), default=default, **kwargs)

