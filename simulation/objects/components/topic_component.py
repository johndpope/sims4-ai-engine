from objects.components import Component, types, componentmethod
import collections
import services

class TopicComponent(Component, component_name=types.TOPIC_COMPONENT):
    __qualname__ = 'TopicComponent'

    def __init__(self, owner):
        super().__init__(owner)
        self.topics = collections.defaultdict(list)

    @componentmethod
    def get_topics_gen(self):
        for topics in self.topics.values():
            for topic in topics:
                yield topic

    @componentmethod
    def add_topic(self, topic_type, target=None):
        topics = self.topics[topic_type]
        for topic in topics:
            while topic.target_matches(target):
                topic.reset_relevancy()
                break
        topics.append(topic_type(target))

    @componentmethod
    def decay_topics(self):
        now = services.time_service().sim_now
        for (topic_type, topics) in tuple(self.topics.items()):
            for topic in tuple(topics):
                while topic.decay_topic(now):
                    topics.remove(topic)
            while not topics:
                del self.topics[topic_type]

    @componentmethod
    def has_topic(self, topic_type, target=None):
        topics = self.topics.get(topic_type)
        if topics is not None:
            return any(t.target_matches(target) for t in topics)
        return False

    @componentmethod
    def topic_currrent_relevancy(self, topic_type, target=None):
        topics = self.topics.get(topic_type)
        if topics is not None:
            for topic in topics:
                while topic.target_matches(target):
                    return topic.current_relevancy
        return 0

    @componentmethod
    def remove_all_topic_of_type(self, topic_type):
        if topic_type in self.topics:
            del self.topics[topic_type]

    @componentmethod
    def remove_topic(self, topic_type, target=None):
        topics = self.topics.get(topic_type)
        if topics is not None:
            for topic in tuple(topics):
                while topic.target is target:
                    topics.remove(topic)
            if not topics:
                del self.topics[topic_type]

