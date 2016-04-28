from debugvis import Context
from sims4.color import pseudo_random_color
from visualization.constraint_visualizer import _draw_constraint
import services
import sims4.color

class BroadcasterVisualizer:
    __qualname__ = 'BroadcasterVisualizer'

    def __init__(self, layer):
        self.layer = layer
        self._start()

    def _start(self):
        services.current_zone().broadcaster_service.register_callback(self._on_update)
        self._on_update()

    def stop(self):
        services.current_zone().broadcaster_service.unregister_callback(self._on_update)

    def _on_update(self):
        broadcaster_service = services.current_zone().broadcaster_service
        with Context(self.layer) as layer:
            for broadcaster in broadcaster_service.get_broadcasters_gen(inspect_only=True):
                constraint = broadcaster.get_constraint()
                if constraint is not None:
                    color = pseudo_random_color(broadcaster.guid)
                    _draw_constraint(layer, constraint, color)
                broadcasting_object = broadcaster.broadcasting_object
                if broadcasting_object is not None:
                    broadcaster_center = broadcasting_object.position
                    layer.add_circle(broadcaster_center, radius=0.3, color=color)
                for linked_broadcaster in broadcaster.get_linked_broadcasters_gen():
                    linked_broadcasting_object = linked_broadcaster.broadcasting_object
                    while linked_broadcasting_object is not None:
                        layer.add_point(linked_broadcasting_object.position, size=0.25, color=color)
                        layer.add_segment(broadcaster_center, linked_broadcasting_object.position, color=color)
            for broadcaster in broadcaster_service.get_pending_broadcasters_gen():
                color = pseudo_random_color(broadcaster.guid)
                (r, g, b, a) = sims4.color.to_rgba(color)
                color = sims4.color.from_rgba(r, g, b, a*0.5)
                broadcasting_object = broadcaster.broadcasting_object
                while broadcasting_object is not None:
                    layer.add_circle(broadcasting_object.position, color=color)

