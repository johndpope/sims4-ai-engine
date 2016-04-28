from debugvis import Context
import services
import sims4.color

class ConnectivityHandlesVisualizer:
    __qualname__ = 'ConnectivityHandlesVisualizer'

    def __init__(self, sim, layer):
        self.layer = layer
        self.start()

    def start(self):
        services.current_zone().navmesh_change_callbacks.append(self.refresh)
        self.refresh()

    def stop(self):
        services.current_zone().navmesh_change_callbacks.remove(self.refresh)

    def refresh(self):
        pre_slot_color = sims4.color.from_rgba(0.8, 0.8, 0, 0.9)
        post_slot_color = sims4.color.from_rgba(0.9, 0.7, 0, 0.25)
        with Context(self.layer, altitude=0.1) as context:
            for obj in services.object_manager().valid_objects():
                pass

