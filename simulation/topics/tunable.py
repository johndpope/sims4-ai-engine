from interactions.utils.loot_basic_op import BaseTargetedLootOperation
from sims4.tuning.tunable import Tunable, TunableReference
from topics.topic import Topic
import interactions
import services
import sims4.log
logger = sims4.log.Logger('Topic')

class TopicUpdate(BaseTargetedLootOperation):
    __qualname__ = 'TopicUpdate'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        pass

    FACTORY_TUNABLES = {'topic': TunableReference(description='\n            The topic we are updating.', manager=services.get_instance_manager(sims4.resources.Types.TOPIC), class_restrictions=Topic), 'add': Tunable(description='\n            Topic will be added to recipient. if unchecked topic will be\n            removed from recipient.', tunable_type=bool, default=True), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, topic, add, **kwargs):
        super().__init__(**kwargs)
        self._topic_type = topic
        self._add = add

    def _apply_to_subject_and_target(self, subject, target, resolver):
        sim = self._get_object_from_recipient(subject)
        if sim is None:
            return
        if self._add:
            sim.add_topic(self._topic_type, target=target)
        else:
            sim.remove_topic(self._topic_type, target=target)

