import enum

class DataType(enum.Int, export=False):
    __qualname__ = 'DataType'
    RelationshipData = 1
    SimoleanData = 2
    TimeData = 3
    BuffData = 4
    TravelData = 5
    ObjectiveCount = 6
    CareerData = 7
    TagData = 8
    RelativeStartingData = 9

class InteractionData(enum.Int, export=False):
    __qualname__ = 'InteractionData'
    InteractionsFailed = 0
    InteractionsSucceeded = 1

class RelationshipData(enum.Int, export=False):
    __qualname__ = 'RelationshipData'
    CurrentRelationships = 0
    TotalRelationships = 1

class SimoleonData(enum.Int):
    __qualname__ = 'SimoleonData'
    MoneyFromEvents = 0
    TotalMoneyEarned = 1

class TimeData(enum.Int, export=False):
    __qualname__ = 'TimeData'
    SimTime = 0
    ServerTime = 1

class BuffData(enum.Int, export=False):
    __qualname__ = 'BuffData'
    TotalBuffTimeElapsed = 0
    LastTimeBuffStarted = 1

class TagData(enum.Int, export=False):
    __qualname__ = 'TagData'
    SimoleonsEarned = 0
    TimeElapsed = 1

class EventData(enum.Int, export=False):
    __qualname__ = 'EventData'
    EventsAttended = 0
    EventsHosted = 1
    EventsWon = 2

