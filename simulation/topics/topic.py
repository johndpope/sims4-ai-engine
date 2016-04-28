from sims4.tuning.instances import TunedInstanceMetaclass
from sims4.tuning.tunable import Tunable, OptionalTunable, TunableTuple, TunableLiteralOrRandomValue
import services
import clock

class Topic(metaclass=TunedInstanceMetaclass, manager=services.topic_manager()):
    __qualname__ = 'Topic'
    INSTANCE_TUNABLES = {'score_bonus': Tunable(description='\n            Score bonus for matching topic tag.\n            ', tunable_type=int, default=0), 'guaranteed_content': OptionalTunable(TunableTuple(description='\n            If enabled, will force content set generation to add options for\n            this topic.\n            ', count=Tunable(description='\n                The number of options to force into the content set.\n                ', tunable_type=int, default=1), priority=Tunable(description='\n                The priority of this Topic vs. other Topics. Ties are randomized.\n                ', tunable_type=int, default=0))), 'relevancy_value': TunableLiteralOrRandomValue(description='\n            Initial Decay value once value has reached zero topic will be\n            removed.  If is_timeout is set, this will the number of minutes\n            before topic will timeout.\n            ', tunable_type=int, default=1), 'is_timed_relevancy': Tunable(description='\n            If set, relevancy value is treated as number of minutes until topic\n            is removed.\n            ', tunable_type=bool, default=False)}

    @classmethod
    def topic_exist_in_sim(cls, sim, target=None):
        return sim.has_topic(cls, target=target)

    @classmethod
    def score_for_sim(cls, sim, target=None):
        if cls.topic_exist_in_sim(sim, target):
            return cls.score_bonus
        return 0

    def __init__(self, target):

        def on_target_deleted(ref):
            self.is_valid = False

        self._target_ref = target.ref(on_target_deleted) if target is not None else None
        self.reset_relevancy()
        self.is_valid = True

    def reset_relevancy(self):
        relevancy = self.relevancy_value.random_int()
        if self.is_timed_relevancy:
            self.current_relevancy = services.time_service().sim_now + clock.interval_in_sim_minutes(relevancy)
        else:
            self.current_relevancy = relevancy

    def decay_topic(self, time):
        if not self.is_valid:
            return True
        if self.is_timed_relevancy:
            return time >= self.current_relevancy
        return self.current_relevancy <= 0

    def target_matches(self, target):
        return self.is_valid and target is self.target

    @property
    def target(self):
        if self._target_ref is not None:
            return self._target_ref()

