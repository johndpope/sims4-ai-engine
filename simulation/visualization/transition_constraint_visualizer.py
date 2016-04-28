from debugvis import Context
from sims4.color import pseudo_random_color
from visualization.constraint_visualizer import _draw_constraint
import services

class TransitionConstraintVisualizer:
    __qualname__ = 'TransitionConstraintVisualizer'

    def __init__(self, layer):
        self.layer = layer
        self._start()

    def _start(self):
        zone = services.current_zone()
        zone.on_transition_constraint_history_changed.append(self._on_transition_constraints_changed)
        self._on_transition_constraints_changed(zone.transition_constraint_history)

    def stop(self):
        services.current_zone().on_transition_constraint_history_changed.remove(self._on_transition_constraints_changed)

    def _on_transition_constraints_changed(self, constraint_history):
        with Context(self.layer) as layer:
            for constraint in constraint_history:
                color = pseudo_random_color(id(constraint))
                _draw_constraint(layer, constraint, color)

