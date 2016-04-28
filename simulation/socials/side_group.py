from interactions import ParticipantTypeObject
from interactions.constraints import Anywhere
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import TunableEnumEntry
from socials.group import SocialGroup

class SideGroup(SocialGroup):
    __qualname__ = 'SideGroup'
    INSTANCE_SUBCLASSES_ONLY = True

    def _create_social_geometry(self, sim, call_on_changed=True):
        pass

    def _clear_social_geometry(self, sim, call_on_changed=True):
        pass

    def _group_geometry_changed(self):
        pass

    def _create_adjustment_alarm(self):
        pass

    def try_relocate_around_focus(self, *args, **kwargs):
        return True

lock_instance_tunables(SideGroup, adjust_sim_positions_dynamically=True, is_side_group=True)

class GameGroup(SideGroup):
    __qualname__ = 'GameGroup'
    INSTANCE_TUNABLES = {'social_anchor_object': TunableEnumEntry(description='\n            The participant type used to find an object with the game component.\n            This object will also be used as the social anchor for your social\n            group to ensure the players of the game are around the object.\n            ', tunable_type=ParticipantTypeObject, default=ParticipantTypeObject.ActorSurface)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.geometry = None

    @classmethod
    def make_constraint_default(cls, *args, **kwargs):
        return Anywhere()

    @property
    def _los_constraint(self):
        return Anywhere()

    def get_constraint(self, sim):
        return Anywhere()

    def _remove(self, sim, **kwargs):
        if self._anchor_object is not None:
            game = self._anchor_object.game_component
            if game is not None:
                game.remove_player(sim)
        super()._remove(sim, **kwargs)

class InObjectGroup(SideGroup):
    __qualname__ = 'InObjectGroup'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.geometry = None

    @classmethod
    def make_constraint_default(cls, *args, **kwargs):
        return Anywhere()

    def get_constraint(self, sim):
        return Anywhere()

