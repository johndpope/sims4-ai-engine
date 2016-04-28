from broadcasters.broadcaster import Broadcaster
from broadcasters.broadcaster_effect import _BroadcasterEffect

class BroadcasterEffectEnvironmentScore(_BroadcasterEffect):
    __qualname__ = 'BroadcasterEffectEnvironmentScore'

    def apply_broadcaster_effect(self, broadcaster, affected_object):
        if affected_object.is_sim:
            affected_object.add_environment_score_broadcaster(broadcaster)

    def remove_broadcaster_effect(self, broadcaster, affected_object):
        if affected_object.is_sim:
            affected_object.remove_environment_score_broadcaster(broadcaster)

class BroadcasterEnvironmentScore(Broadcaster):
    __qualname__ = 'BroadcasterEnvironmentScore'
    REMOVE_INSTANCE_TUNABLES = ('effects',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.effects = (BroadcasterEffectEnvironmentScore(),)

