from interactions.interaction_finisher import FinishingType
from interactions.liability import Liability
from objects import HiddenReasonFlag
from sims.baby import on_sim_removed_baby_handle, on_sim_spawned_baby_handle
import placement
import services
import sims4
logger = sims4.log.Logger('RabbitHoles')
RABBIT_HOLE_LIABILTIY = 'RabbitHoleLiability'

class RabbitHoleLiability(Liability):
    __qualname__ = 'RabbitHoleLiability'

    def __init__(self):
        self.interaction = None
        self.sim = None
        self._has_hidden = False

    @property
    def should_transfer(self):
        return False

    def on_add(self, interaction):
        self.interaction = interaction
        self.sim = interaction.sim

    def on_run(self):
        if not self.sim:
            return
        sim_info = self.sim.sim_info
        self.sim.fade_out()
        self.sim.hide(HiddenReasonFlag.RABBIT_HOLE)
        self.sim.client.selectable_sims.notify_dirty()
        self.sim.cancel_interactions_running_on_object(FinishingType.OBJECT_CHANGED, cancel_reason_msg='Target Sim went into rabbit hole')
        zone = services.current_zone()
        zone.sim_quadtree.remove(self.sim.id, placement.ItemType.SIM_POSITION, 0)
        zone.sim_quadtree.remove(self.sim.id, placement.ItemType.SIM_INTENDED_POSITION, 0)
        on_sim_removed_baby_handle(sim_info, sim_info.zone_id)
        self._has_hidden = True

    def release(self):
        if not self.sim:
            logger.error("Could not clean up Rabbit Hole Liabiltiy because the Sim doesn't exist for Interaction: {}", self.interaction)
            return
        if not self.sim.client:
            logger.warn('Could not clean up Rabbit Hole Liability because the Sim has no client. This is normal on zone shutdown.', owner='tingyul')
            return
        if not self._has_hidden:
            return
        sim_info = self.sim.sim_info
        self.sim.show(HiddenReasonFlag.RABBIT_HOLE)
        self.sim.client.selectable_sims.notify_dirty()
        pos = self.sim.position
        pos = sims4.math.Vector2(pos.x, pos.z)
        geo = sims4.geometry.QtCircle(pos, self.sim._quadtree_radius)
        services.sim_quadtree().insert(self.sim, self.sim.id, placement.ItemType.SIM_POSITION, geo, self.sim.routing_surface.secondary_id, False, 0)
        self.sim.fade_in()
        on_sim_spawned_baby_handle((sim_info,))
        self._has_hidden = False

