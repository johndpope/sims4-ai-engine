import enum
from sims4.tuning.dynamic_enum import DynamicEnum

class BouncerRequestStatus(enum.Int, export=False):
    __qualname__ = 'BouncerRequestStatus'
    INITIALIZED = 0
    SUBMITTED = 1
    SPAWN_REQUESTED = 2
    FULFILLED = 3
    DESTROYED = 4

class BouncerRequestPriority(enum.Int, export=False):
    __qualname__ = 'BouncerRequestPriority'
    GAME_BREAKER = 0
    VIP_PLUS = 1
    VIP = 2
    HOSTING = 3
    AUTO_FILL_PLUS = 4
    AUTO_FILL = 5
    DEFAULT_JOB = 6
    LEAVE = 7
    COUNT = 8

class RequestSpawningOption(enum.Int, export=False):
    __qualname__ = 'RequestSpawningOption'
    MUST_SPAWN = 1
    CANNOT_SPAWN = 2
    DONT_CARE = 3

class BouncerExclusivityCategory(enum.IntFlags):
    __qualname__ = 'BouncerExclusivityCategory'
    LEAVE = 2
    NORMAL = 4
    WALKBY = 8
    SERVICE = 16
    VISIT = 32
    LEAVE_NOW = 64
    UNGREETED = 128
    PRE_VISIT = 256
    WORKER = 512

class BouncerExclusivityOption(enum.Int):
    __qualname__ = 'BouncerExclusivityOption'
    NONE = 0
    EXPECTATION_PREFERENCE = 1
    ERROR = 2
    ALREADY_ASSIGNED = 3

