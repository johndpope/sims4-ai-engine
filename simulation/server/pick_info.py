from sims4.math import Vector3
import enum

class PickType(enum.Int):
    __qualname__ = 'PickType'
    PICK_NONE = 0
    PICK_UNKNOWN = 1
    PICK_OBJECT = 2
    PICK_SIM = 3
    PICK_WALL = 4
    PICK_FLOOR = 5
    PICK_TERRAIN = 6
    PICK_STAIRS = 7
    PICK_ROOF = 8
    PICK_MISC = 9
    PICK_PORTRAIT = 10
    PICK_SKEWER = 11
    PICK_FOUNDATION = 12
    PICK_WATER_TERRAIN = 13

PICK_TRAVEL = frozenset([PickType.PICK_TERRAIN, PickType.PICK_FLOOR, PickType.PICK_WATER_TERRAIN, PickType.PICK_UNKNOWN, PickType.PICK_STAIRS, PickType.PICK_FOUNDATION])
PICK_UNGREETED = frozenset([PickType.PICK_ROOF, PickType.PICK_WALL, PickType.PICK_FLOOR, PickType.PICK_STAIRS, PickType.PICK_FOUNDATION])
PICK_USE_TERRAIN_OBJECT = frozenset(PICK_TRAVEL | PICK_UNGREETED)

class PickTerrainType(enum.Int):
    __qualname__ = 'PickTerrainType'
    ANYWHERE = 0
    ON_LOT = 1
    OFF_LOT = 2
    NO_LOT = 3
    ON_OTHER_LOT = 4
    IN_STREET = 5
    OFF_STREET = 6

class PickInfo:
    __qualname__ = 'PickInfo'
    __slots__ = ('_location', '_lot_id', '_routing_surface', '_type', '_target', 'modifiers')

    class PickModifiers:
        __qualname__ = 'PickInfo.PickModifiers'
        __slots__ = ('_alt', '_control', '_shift')

        def __init__(self, alt=False, control=False, shift=False):
            self._alt = alt
            self._control = control
            self._shift = shift

        @property
        def alt(self):
            return self._alt

        @property
        def control(self):
            return self._control

        @property
        def shift(self):
            return self._shift

    def __init__(self, pick_type=PickType.PICK_UNKNOWN, target=None, location=None, routing_surface=None, lot_id=None, alt=False, control=False, shift=False):
        self._type = pick_type
        self._target = target.ref() if target is not None else None
        self._location = location or Vector3.ZERO()
        self._routing_surface = routing_surface
        self._lot_id = lot_id
        self.modifiers = PickInfo.PickModifiers(alt, control, shift)

    @property
    def location(self):
        return self._location

    @property
    def routing_surface(self):
        return self._routing_surface

    @property
    def lot_id(self):
        return self._lot_id

    @property
    def pick_type(self):
        return self._type

    @property
    def target(self):
        if self._target is not None:
            return self._target()

