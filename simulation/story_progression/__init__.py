import enum

class StoryProgressionFlags(enum.IntFlags, export=False):
    __qualname__ = 'StoryProgressionFlags'
    DISABLED = 0
    ALLOW_POPULATION_ACTION = 1
    ALLOW_INITIAL_POPULATION = 2

