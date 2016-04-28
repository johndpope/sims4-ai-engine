from objects import PaintingState
from objects.components import Component, componentmethod_with_fallback
from protocolbuffers import SimObjectAttributes_pb2 as persistence_protocols
from sims4.tuning.dynamic_enum import DynamicEnumFlags
from sims4.tuning.tunable import HasTunableFactory, TunableEnumFlags
import distributor.fields
import distributor.ops
import objects.components.types

class CanvasType(DynamicEnumFlags):
    __qualname__ = 'CanvasType'
    NONE = 0

class CanvasComponent(Component, HasTunableFactory, component_name=objects.components.types.CANVAS_COMPONENT, persistence_key=persistence_protocols.PersistenceMaster.PersistableData.CanvasComponent):
    __qualname__ = 'CanvasComponent'
    FACTORY_TUNABLES = {'canvas_types': TunableEnumFlags(CanvasType, CanvasType.NONE, description="\n            A painting texture must support at least one of these canvas types\n            to be applied to this object's painting area.\n            ")}

    def __init__(self, owner, *, canvas_types):
        super().__init__(owner)
        self.canvas_types = canvas_types
        self._painting_state = None

    def save(self, persistence_master_message):
        persistable_data = persistence_protocols.PersistenceMaster.PersistableData()
        persistable_data.type = persistence_protocols.PersistenceMaster.PersistableData.CanvasComponent
        canvas_data = persistable_data.Extensions[persistence_protocols.PersistableCanvasComponent.persistable_data]
        canvas_data.texture_id = self.painting_state.texture_id
        canvas_data.reveal_level = self.painting_state.reveal_level
        persistence_master_message.data.extend([persistable_data])

    def load(self, persistable_data):
        canvas_data = persistable_data.Extensions[persistence_protocols.PersistableCanvasComponent.persistable_data]
        self.painting_state = PaintingState(canvas_data.texture_id, canvas_data.reveal_level)

    @distributor.fields.ComponentField(op=distributor.ops.SetPaintingState, default=None)
    def painting_state(self) -> PaintingState:
        return self._painting_state

    @painting_state.setter
    def painting_state(self, value):
        self._painting_state = value

    @property
    def painting_reveal_level(self) -> int:
        if self.painting_state is not None:
            return self.painting_state.reveal_level

    @painting_reveal_level.setter
    def painting_reveal_level(self, reveal_level):
        if self.painting_state is not None:
            self.painting_state = self.painting_state.get_at_level(reveal_level)

    @componentmethod_with_fallback(lambda msg: None)
    def populate_icon_canvas_texture_info(self, msg):
        if self.painting_state is not None and msg is not None:
            msg.texture_id = self.painting_state.texture_id

