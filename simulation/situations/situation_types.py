from collections import namedtuple
from sims4.localization import TunableLocalizedString
from sims4.tuning.dynamic_enum import DynamicEnumLocked
from sims4.tuning.tunable import TunableEnumEntry, TunableMapping
from sims4.tuning.tunable_base import ExportModes
import enum

class SituationStage(enum.Int, export=False):
    __qualname__ = 'SituationStage'
    NEVER_RUN = 0
    SETUP = 1
    RUNNING = 2
    DYING = 4
    DEAD = 5

class SituationCreationUIOption(enum.Int):
    __qualname__ = 'SituationCreationUIOption'
    NOT_AVAILABLE = 0
    AVAILABLE = 1
    DEBUG_AVAILABLE = 2

class SituationMedal(enum.Int):
    __qualname__ = 'SituationMedal'
    TIN = 0
    BRONZE = 1
    SILVER = 2
    GOLD = 3

class SituationCategoryUid(DynamicEnumLocked, display_sorted=True):
    __qualname__ = 'SituationCategoryUid'
    DEFAULT = 0
    DEBUG = 1

class SituationCategory:
    __qualname__ = 'SituationCategory'
    CATEGORIES = TunableMapping(key_type=TunableEnumEntry(SituationCategoryUid, export_modes=ExportModes.All, default=SituationCategoryUid.DEFAULT, description='The Situation Category.'), value_type=TunableLocalizedString(description='The Category Name'), export_modes=ExportModes.All, description='Mapping from Uid to Name')

class SituationCallbackOption:
    __qualname__ = 'SituationCallbackOption'
    END_OF_SITUATION_SCORING = 0

class SimJobScore(namedtuple('SimJobScore', 'sim, job_type, score')):
    __qualname__ = 'SimJobScore'

    def __str__(self):
        return 'sim {}, job_type {}, score {}'.format(self.sim, self.job_type, self.score)

class ScoringCallbackData:
    __qualname__ = 'ScoringCallbackData'

    def __init__(self, situation_id, situation_score):
        self.situation_id = situation_id
        self.situation_score = situation_score
        self.sim_job_scores = []

    def add_sim_job_score(self, sim, job_type, score):
        self.sim_job_scores.append(SimJobScore(sim, job_type, score))

    def __str__(self):
        return 'situation id {}, situation score {} sims {}'.format(self.situation_id, self.situation_score, self.sim_job_scores)

class JobHolderNoShowAction(enum.Int):
    __qualname__ = 'JobHolderNoShowAction'
    END_SITUATION = 0
    REPLACE_THEM = 1
    DO_NOTHING = 2

class JobHolderDiedOrLeftAction(enum.Int):
    __qualname__ = 'JobHolderDiedOrLeftAction'
    END_SITUATION = 0
    REPLACE_THEM = 1
    DO_NOTHING = 2

class GreetedStatus(enum.Int, export=False):
    __qualname__ = 'GreetedStatus'
    GREETED = 0
    WAITING_TO_BE_GREETED = 1
    NOT_APPLICABLE = 3

class SituationSerializationOption(enum.Int, export=False):
    __qualname__ = 'SituationSerializationOption'
    DONT = 0
    LOT = 1
    OPEN_STREETS = 2

class SituationCommonBlacklistCategory(enum.IntFlags, export=False):
    __qualname__ = 'SituationCommonBlacklistCategory'
    ACTIVE_HOUSEHOLD = 1
    ACTIVE_LOT_HOUSEHOLD = 2

