from broadcasters.broadcaster import Broadcaster
from element_utils import build_critical_section_with_finally
from sims4.tuning.tunable import AutoFactoryInit, HasTunableFactory, TunableList
import elements
import services

class BroadcasterRequest(elements.ParentElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'BroadcasterRequest'
    FACTORY_TUNABLES = {'broadcaster_types': TunableList(Broadcaster.TunableReference(description='\n                The broadcasters to request.\n                '))}

    def __init__(self, owner, *args, sequence=(), **kwargs):
        super().__init__(*args, **kwargs)
        self._sequence = sequence
        if hasattr(owner, 'target'):
            self._interaction = owner
            self._target = self._interaction.sim
        else:
            self._interaction = None
            self._target = owner
        self._broadcasters = []

    @classmethod
    def on_affordance_loaded_callback(cls, affordance, broadcaster_request):
        for broadcaster_type in broadcaster_request.broadcaster_types:
            broadcaster_type.register_static_callbacks(affordance)

    def start(self, *_, **__):
        if self._target.is_prop:
            return
        broadcaster_service = services.current_zone().broadcaster_service
        if broadcaster_service is not None:
            for broadcaster_type in self.broadcaster_types:
                broadcaster = broadcaster_type(broadcasting_object=self._target, interaction=self._interaction)
                self._broadcasters.append(broadcaster)
                broadcaster_service.add_broadcaster(broadcaster)

    def stop(self, *_, **__):
        broadcaster_service = services.current_zone().broadcaster_service
        if broadcaster_service is not None:
            for broadcaster in self._broadcasters:
                broadcaster_service.remove_broadcaster(broadcaster)
        self._broadcasters = []

    def _run(self, timeline):
        sequence = build_critical_section_with_finally(self.start, self._sequence, self.stop)
        return timeline.run_child(sequence)

