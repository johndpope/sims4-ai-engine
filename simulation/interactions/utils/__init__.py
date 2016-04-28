import enum

class LootType(enum.Int, export=False):
    __qualname__ = 'LootType'
    SITUATION = 1
    RELATIONSHIP = 2
    SKILL = 3
    SIMOLEONS = 4
    GENERIC = 6
    RELATIONSHIP_BIT = 7
    TEAM_SCORE = 8
    GAME_OVER = 9
    GAME_SETUP = 10
    PARTY_AFFINITY = 11
    LIFE_EXTENSION = 12
    TAKE_TURN = 13
    ACTIONS = 14
    GAME_RESET = 15

