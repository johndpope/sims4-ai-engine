from debugvis import Context
from sims4.color import from_rgba, pseudo_random_color
from visualization.constraint_visualizer import _draw_constraint

class ShortestTransitionPathVisualizer:
    __qualname__ = 'ShortestTransitionPathVisualizer'

    def __init__(self, layer):
        self.layer = layer
        self._start()

    def _start(self):
        import postures.posture_scoring
        postures.posture_scoring.on_transition_destinations_changed.append(self._on_transition_destinations_changed)

    def stop(self):
        import postures.posture_scoring
        postures.posture_scoring.on_transition_destinations_changed.remove(self._on_transition_destinations_changed)

    def _on_transition_destinations_changed(self, sim, transition_destinations, possible_sources, max_weight, preserve=False):
        POSSIBLE_SOURCE = from_rgba(50, 50, 50, 0.5)
        with Context(self.layer, preserve=preserve) as layer:
            for (path_id, constraint, weight) in transition_destinations:
                alpha = 1.0
                if max_weight > 0:
                    alpha = weight/max_weight
                color = pseudo_random_color(path_id, a=alpha)
                _draw_constraint(layer, constraint, color)
            for constraint in possible_sources:
                _draw_constraint(layer, constraint, POSSIBLE_SOURCE, altitude_modifier=0.5)

class SimShortestTransitionPathVisualizer(ShortestTransitionPathVisualizer):
    __qualname__ = 'SimShortestTransitionPathVisualizer'

    def __init__(self, sim, layer):
        self.sim = sim
        super().__init__(layer)

    def _on_transition_destinations_changed(self, sim, *args, **kwargs):
        if self.sim is not None and sim is not self.sim:
            return
        super()._on_transition_destinations_changed(sim, *args, **kwargs)

