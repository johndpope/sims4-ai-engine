import enum

class BuffPolarity(enum.Int):
    __qualname__ = 'BuffPolarity'
    NEUTRAL = 0
    NEGATIVE = 1
    POSITIVE = 2

class GameEffectType(enum.Int, export=False):
    __qualname__ = 'GameEffectType'
    AFFORDANCE_MODIFIER = 0
    EFFECTIVE_SKILL_MODIFIER = 1
    CONTINUOUS_STATISTIC_MODIFIER = 3
    RELATIONSHIP_TRACK_DECAY_LOCKER = 4

class Appropriateness(enum.Int, export=False):
    __qualname__ = 'Appropriateness'
    DONT_CARE = (0,)
    NOT_ALLOWED = (1,)
    ALLOWED = (2,)

