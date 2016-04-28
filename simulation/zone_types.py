import enum

class ZoneState(enum.Int, export=False):
    __qualname__ = 'ZoneState'
    ZONE_INIT = 0
    OBJECTS_LOADED = 1
    CLIENT_CONNECTED = 2
    HOUSEHOLDS_AND_SIM_INFOS_LOADED = 3
    HITTING_THEIR_MARKS = 4
    RUNNING = 5
    SHUTDOWN_STARTED = 6

