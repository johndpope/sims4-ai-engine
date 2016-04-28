import random
from objects.definition_manager import TunableDefinitionList
from sims4.tuning.dynamic_enum import DynamicEnum
from sims4.tuning.tunable import TunableTuple, TunableMapping, TunableEnumEntry
import enum
import objects.system

class PuddleSize(enum.Int):
    __qualname__ = 'PuddleSize'
    NoPuddle = 0
    SmallPuddle = 1
    MediumPuddle = 2
    LargePuddle = 3

class PuddleLiquid(DynamicEnum, partitioned=True):
    __qualname__ = 'PuddleLiquid'
    WATER = 0

class PuddleChoices:
    __qualname__ = 'PuddleChoices'
    reverse_lookup = None
    PUDDLE_DEFINITIONS = TunableMapping(description='\n        A mapping that defines the various puddle objects for the given sizes\n        and liquids.\n        ', key_type=TunableEnumEntry(description='\n            The liquid that the puddle is made of.\n            ', tunable_type=PuddleLiquid, default=PuddleLiquid.WATER), value_type=TunableMapping(description='\n            A mapping that defines the various puddle objects for the given\n            size.\n            ', key_type=TunableEnumEntry(description='\n                The size of the puddle.\n                ', tunable_type=PuddleSize, default=PuddleSize.SmallPuddle), value_type=TunableDefinitionList(description='\n                A list of object definitions. A random one will be chosen to\n                create a puddle of the corresponding liquid and size.\n                ')))

def create_puddle(puddle_size, puddle_liquid=PuddleLiquid.WATER):
    available_sizes = PuddleChoices.PUDDLE_DEFINITIONS.get(puddle_liquid)
    if not available_sizes:
        return
    available_definitions = available_sizes.get(puddle_size)
    if not available_definitions:
        return

    def init(obj):
        obj._puddle_size = puddle_size
        obj._puddle_liquid = puddle_liquid
        obj.opacity = 0

    return objects.system.create_object(random.choice(available_definitions), init=init)

