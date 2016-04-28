from protocolbuffers import Social_pb2, Consts_pb2
from protocolbuffers.Localization_pb2 import LocalizedStringToken
from sims4.localization import TunableLocalizedString
import enum
try:
    import _social_module
except ImportError:

    class _social_module:
        __qualname__ = '_social_module'

        @staticmethod
        def post_wall(*args):
            pass

class SocialTuning:
    __qualname__ = 'SocialTuning'
    SKILLUP = TunableLocalizedString(default=2747889317, description="Whenever a Sim's skill reaches a new level, notification is posted on the owner's wall")
    SKILLMASTERED = TunableLocalizedString(description="Whenever a Sim's skill reaches the max level, notification is posted on the owner's wall")
    TRAVEL = TunableLocalizedString(default=3331072641, description='Travel message displayed on the social wall when a Sim travels from one zone to another')
    SITUATION_START = TunableLocalizedString(default=978256876, description='When a situation has started in the zone, this message is posted to the wall')
    SITUATION_FINISHED = TunableLocalizedString(default=1714955919, description='When a situation has ended in the zone, this message is posted to the wall')
    ALMOST_AGE_MSG = TunableLocalizedString(description='Message sent to the feed when a Sim is almost ready to age up.')
    TIME_TO_AGE_MSG = TunableLocalizedString(description='Message sent to the feed when a Sim is ready to age up.')
    TRAIT_ADDED = TunableLocalizedString(description="Whenever a Sim adds a trait notification is posted on the owner's wall")
    TRAIT_REMOVED = TunableLocalizedString(description="Whenever a Sim removes a trait notification is posted on the owner's wall")
    REL_BIT_ADDED = TunableLocalizedString(description="Whenever a Sim adds a relationship bit notification is posted on both Sim's walls")
    REL_BIT_REMOVED = TunableLocalizedString(description="Whenever a Sim removes a relationship bit notification is posted on both Sim's walls")

class SocialEnums(enum.Int, export=False):
    __qualname__ = 'SocialEnums'
    SITUATION_START = 0
    SITUATION_FINISHED = 1

def _post_wall(whose_wall_id, poster_id, message):
    pass

def post_travel_message(sim_info, destination_zone_id):
    pass

def post_aging_message(sim_info, ready_to_age=True):
    pass

def post_skill_message(sim_info, skill, old_level, new_level):
    pass

def post_situation_message(personas, situation_id, situation_type, zone_id, starting):
    pass

def post_trait_message(sim_info, trait, added=None):
    pass

def post_relationship_message(sim_info, bit, target_sim_id, added=None):
    pass

def post_career_message(sim_info, career, msg_type):
    pass

