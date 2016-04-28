from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableEnumEntry, TunableList, TunableTuple, TunableReference, Tunable, TunableSet, HasTunableReference
from situations.situation_goal import TunableWeightedSituationGoalReference
from tag import Tag
import services
import sims4.resources

class TunableWeightedSituationGoalSetReference(TunableTuple):
    __qualname__ = 'TunableWeightedSituationGoalSetReference'

    def __init__(self, **kwargs):
        super().__init__(weight=Tunable(float, 1.0, description='Higher number means higher chance of being selected.'), goal_set=TunableReference(services.get_instance_manager(sims4.resources.Types.SITUATION_GOAL_SET), description='A goal set.'))

class SituationGoalSet(HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.SITUATION_GOAL_SET)):
    __qualname__ = 'SituationGoalSet'
    INSTANCE_TUNABLES = {'goals': TunableList(TunableWeightedSituationGoalReference(), description='List of weighted goals.'), 'chained_goal_sets': TunableList(TunableReference(services.get_instance_manager(sims4.resources.Types.SITUATION_GOAL_SET)), description='List of chained goal sets in priority order.'), 'role_tags': TunableSet(TunableEnumEntry(Tag, Tag.INVALID), description='Goals from this set will only be given to Sims in SituationJobs or Role States marked with one of these tags.')}

