from server_commands.argument_helpers import OptionalTargetParam, get_optional_target
import services
import sims4.commands

@sims4.commands.Command('topic.add_topic')
def add_topic(name:str=None, opt_sim:OptionalTargetParam=None, topic_target_id:int=0, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None or name is None:
        return False
    topic_type = services.topic_manager().get(name)
    if topic_type is None:
        sims4.commands.output('({0}) is not a valid topic'.format(name), _connection)
        return False
    target = None
    if topic_target_id:
        target = services.object_manager().get(topic_target_id)
        if target is None:
            sims4.commands.output('({0}) is not a valid target for topic'.format(topic_target_id), _connection)
            return False
    sim.add_topic(topic_type, target=target)
    sims4.commands.output('({0}) has been added'.format(name), _connection)
    return True

@sims4.commands.Command('topic.remove_topic')
def remove_topic(name:str=None, opt_sim:OptionalTargetParam=None, topic_target_id:int=0, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None or name is None:
        return False
    topic_type = services.topic_manager().get(name)
    if topic_type is None:
        sims4.commands.output('({0}) is not a valid topic'.format(name), _connection)
        return False
    target = None
    if topic_target_id:
        target = services.object_manager().get(topic_target_id)
        if target is None:
            sims4.commands.output('({0}) is not a valid target for topic'.format(topic_target_id), _connection)
            return False
    sim.remove_topic(topic_type, target=target)
    return True

@sims4.commands.Command('topic.remove_all_topics')
def remove_all_topic_of_type(name:str=None, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None or name is None:
        return False
    topic_type = services.topic_manager().get(name)
    if topic_type is None:
        sims4.commands.output('({0}) is not a valid topic'.format(name), _connection)
        return False
    sim.remove_all_topic_of_type(topic_type)
    return True

