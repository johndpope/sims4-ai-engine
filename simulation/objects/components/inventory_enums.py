from sims4.localization import TunableLocalizedString
from sims4.resources import CompoundTypes
from sims4.tuning.dynamic_enum import DynamicEnum
from sims4.tuning.tunable import TunableMapping, TunableTuple, TunableResourceKey, Tunable
from sims4.tuning.tunable_base import ExportModes
from statistics.tunable import CommodityDecayModifierMapping
import enum

class InventoryType(DynamicEnum):
    __qualname__ = 'InventoryType'
    UNDEFINED = 0
    SIM = 1
    HIDDEN = 2
    FISHBOWL = 3
    MAILBOX = 4

UNIQUE_OBJECT_INVENTORY_TYPES = frozenset([InventoryType.SIM, InventoryType.FISHBOWL])

class StackScheme(enum.Int):
    __qualname__ = 'StackScheme'
    NONE = Ellipsis
    VARIANT_GROUP = Ellipsis
    DEFINITION = Ellipsis

class InventoryTypeTuning:
    __qualname__ = 'InventoryTypeTuning'
    INVENTORY_TYPE_DATA = TunableMapping(description='\n        A mapping of Inventory Type to any static information required by the\n        client to display inventory data as well information about allowances\n        for each InventoryType.\n        ', key_type=InventoryType, value_type=TunableTuple(description='\n            Any information required by the client to display inventory data.\n            ', display_text=TunableLocalizedString(description='\n                The name associated with this inventory type.\n                '), icon=TunableResourceKey(description='\n                The icon associated with this inventory type.\n                ', default=None, resource_types=CompoundTypes.IMAGE), skip_carry_pose_allowed=Tunable(description='\n                If checked, an object tuned to be put away in this inventory\n                type will be allowed to skip the carry pose.  If unchecked, it\n                will not be allowed to skip the carry pose.\n                ', tunable_type=bool, default=False), put_away_allowed=Tunable(description='\n                If checked, objects can be manually "put away" in this\n                inventory type. If unchecked, objects cannot be manually "put\n                away" in this inventory type.\n                ', tunable_type=bool, default=True)))
    GAMEPLAY_MODIFIERS = TunableMapping(description="\n        A mapping of Inventory Type to the gameplay effects they provide. If an\n        inventory does not affect contained objects, it is fine to leave that\n        inventory's type out of this mapping.\n        ", key_type=InventoryType, value_type=TunableTuple(description='\n            Gameplay modifiers.\n            ', decay_modifiers=CommodityDecayModifierMapping(description='\n                Multiply the decay rate of specific commodities by a tunable\n                integer in order to speed up or slow down decay while the\n                object is contained within this inventory. This modifier will\n                be multiplied with other modifiers on the object, if it has\n                any.\n                ')))

