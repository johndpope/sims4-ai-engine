from sims4.tuning.dynamic_enum import DynamicEnumLocked
from sims4.tuning.tunable_base import ExportModes
PORTAL_DISALLOWANCE_PREFIX = ('PortalDisallowance',)
INTERACTION_PREFIX = ('interaction',)
SPAWN_PREFIX = ('Spawn',)

class Tag(DynamicEnumLocked, export_modes=(ExportModes.ClientBinary, ExportModes.ServerXML), display_sorted=True, partitioned=True):
    __qualname__ = 'Tag'
    INVALID = 0

class TagCategory(DynamicEnumLocked, export_modes=(ExportModes.ClientBinary, ExportModes.ServerXML)):
    __qualname__ = 'TagCategory'
    INVALID = 0

