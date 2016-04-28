from broadcasters.environment_score.environment_score_broadcaster import BroadcasterEnvironmentScore
from objects.components.state import ObjectStateValue
from sims4.tuning.tunable import TunableMapping, TunableEnumEntry, TunableReference
from statistics.commodity import Commodity
from statistics.mood import Mood
import services
import tag

class EnvironmentScoreTuning:
    __qualname__ = 'EnvironmentScoreTuning'
    ENVIRONMENT_SCORE_BROADCASTER = BroadcasterEnvironmentScore.TunableReference(description='\n        The singleton broadcaster that groups all scoring objects. The\n        constraints on this broadcaster determine the constraint within which a\n        Sim is affected by environment score.\n        ')
    ENVIRONMENT_SCORE_MOODS = TunableMapping(description="\n        Tags on Objects correspond to a particular Mood.\n                \n        When an object is going to contribute to the environment score, put a\n        tag in it's catalog object, and make sure that tag points to a Mood\n        here.\n        ", key_type=TunableEnumEntry(description='\n            The Tag that corresponds to mood and environmental scoring data.\n            ', tunable_type=tag.Tag, default=tag.Tag.INVALID), value_type=Mood.TunableReference(description='\n            The mood that the Sim must be in for an object that emits this mood\n            to score. Corresponds to the mood_tag.\n            '), key_name='object_tag', value_name='mood')
    NEGATIVE_ENVIRONMENT_SCORING = Commodity.TunableReference(description='\n        Defines the ranges and corresponding buffs to apply for negative\n        environmental contribution.\n        \n        Be sure to tune min, max, and the different states. The convergence\n        value is what will remove the buff. Suggested to be 0.\n        ')
    POSITIVE_ENVIRONMENT_SCORING = Commodity.TunableReference(description='\n        Defines the ranges and corresponding buffs to apply for positive\n        environmental contribution.\n        \n        Be sure to tune min, max, and the different states. The convergence\n        value is what will remove the buff. Suggested to be 0.\n        ')
    ENABLE_AFFORDANCE = TunableReference(description='\n        The interaction that will turn on Environment Score for a particular\n        object. This interaction should set a state on the object that will\n        have multipliers of 1 and adders of 0 for all moods.\n        ', manager=services.affordance_manager())
    DISABLE_AFFORDANCE = TunableReference(description='\n        The interaction that will turn off Environment Score for a particular\n        object. This interaction should set a state on the object that will\n        have multipliers of 0 and adders of 0 for all moods.\n        ', manager=services.affordance_manager())
    ENABLED_STATE_VALUE = ObjectStateValue.TunableReference(description='\n        A state value that indicates the object should be contributing\n        Environment Score.\n        ')
    DISABLED_STATE_VALUE = ObjectStateValue.TunableReference(description='\n        A state value that indicates the object should not be contributing\n        Environment Score.\n        ')

