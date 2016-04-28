from debugvis import Context
from sims4.color import pseudo_random_color
import routing
import sims4.math

class SimPositionVisualizer:
    __qualname__ = 'SimPositionVisualizer'

    def __init__(self, sim, layer):
        self.sim = sim
        self.layer = layer
        self.start()

    def start(self):
        self.sim.register_on_location_changed(self._on_position_changed)
        self.sim.on_follow_path.append(self._on_intended_position_changed)

    def stop(self):
        if self._on_position_changed in self.sim.on_follow_path:
            self.sim.on_follow_path.remove(self._on_position_changed)
        if self.sim._on_location_changed_callbacks is not None and self._on_intended_position_changed in self.sim._on_location_changed_callbacks:
            self.sim.unregister_on_location_changed(self._on_intended_position_changed)

    def redraw(self, sim):
        with Context(self.layer, altitude=0.1, routing_surface=sim.routing_surface) as layer:
            position_color = pseudo_random_color(sim.id)
            position = sim.position
            orientation = sim.orientation
            layer.add_circle(position, routing.get_default_agent_radius(), color=position_color)
            if orientation != sims4.math.Quaternion.ZERO():
                angle = sims4.math.yaw_quaternion_to_angle(orientation)
                layer.add_arrow(position, angle, color=position_color)
            while sim.intended_location is not None:
                intended_position_color = pseudo_random_color(sim.id + 1)
                intended_position = sim.intended_location.position
                intended_orientation = sim.intended_location.orientation
                layer.add_circle(intended_position, routing.get_default_agent_radius(), color=intended_position_color)
                while intended_orientation != sims4.math.Quaternion.ZERO():
                    angle = sims4.math.yaw_quaternion_to_angle(intended_orientation)
                    layer.add_arrow(intended_position, angle, color=intended_position_color)

    def _on_position_changed(self, *_, **__):
        self.redraw(self.sim)

    def _on_intended_position_changed(self, follow_path, starting):
        self.redraw(self.sim)

