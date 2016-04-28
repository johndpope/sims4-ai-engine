from sims4.localization import TunableLocalizedString
from sims4.tuning.dynamic_enum import DynamicEnumLocked
from sims4.tuning.tunable import TunableMapping, TunableTuple, TunableEnumEntry, TunableReference
from sims4.tuning.tunable_base import ExportModes
import services
import sims4

class MemoryUid(DynamicEnumLocked, display_sorted=True):
    __qualname__ = 'MemoryUid'
    Invalid = 0

class TunableMemoryTuple(TunableTuple):
    __qualname__ = 'TunableMemoryTuple'

    def __init__(self, **kwargs):
        super().__init__(name=TunableLocalizedString(export_modes=ExportModes.All, description='Localization String for the kind of memory.'), reminisce_affordance=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION), class_restrictions='SuperInteraction', description='The interaction that is pushed on the Sim when they Reminisce about this Memory. Should most often be from the Reminisce Prototype.'), **kwargs)

class Memory:
    __qualname__ = 'Memory'
    MEMORIES = TunableMapping(key_type=TunableEnumEntry(MemoryUid, export_modes=ExportModes.All, default=MemoryUid.Invalid, description='The Type of Memory. Should be unique. Defined in MemoryUid.'), value_type=TunableMemoryTuple(), export_modes=ExportModes.All)

