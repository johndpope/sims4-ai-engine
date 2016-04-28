from sims4.tuning.instances import TunedInstanceMetaclass
from sims4.tuning.tunable import TunableReference, TunableList
import services
import sims4.resources
import topics.topic

class TopicList(metaclass=TunedInstanceMetaclass, manager=services.topic_manager()):
    __qualname__ = 'TopicList'
    INSTANCE_TUNABLES = {'topic_list': TunableList(TunableReference(manager=services.get_instance_manager(sims4.resources.Types.TOPIC), class_restrictions=topics.topic.Topic), description='List of topics')}

    @classmethod
    def topic_exist_in_sim(cls, sim, target=None):
        return any(sim.has_topic(topic, target=target) for topic in cls.topic_list)

    @classmethod
    def score_for_sim(cls, sim, target=None):
        return sum(topic.score_for_sim(sim, target) for topic in cls.topic_list)

