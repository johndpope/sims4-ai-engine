from server_commands.argument_helpers import OptionalTargetParam, get_optional_target, TunableInstanceParam
from sims4.tuning.tunable import TunableReference, Tunable
from filters.tunable import TunableSimFilter
from sims.sim_spawner import SimSpawner
import relationships.relationship_track
import services
import sims4.commands
import sims4.log
logger = sims4.log.Logger('Relationship', default_owner='rez')

class RelationshipCommandTuning:
    __qualname__ = 'RelationshipCommandTuning'
    INTRODUCE_BIT = TunableReference(services.get_instance_manager(sims4.resources.Types.RELATIONSHIP_BIT), description='Relationship bit to add to all Sims when running the introduce command.')
    INTRODUCE_TRACK = TunableReference(services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions=relationships.relationship_track.RelationshipTrack, description='Relationship track for friendship used for the ')
    INTRODUCE_VALUE = Tunable(int, 0, description='The value to add to the relationship to introduce the sims.')
    CREATE_FRIENDS_COMMAND_QUANTITY = Tunable(description='\n        The number of friendly sims to generate \n        using command |relationships.create_friends_for_sim.\n        ', tunable_type=int, default=1)
    CREATE_FRIENDS_COMMAND_FILTER = TunableSimFilter.TunableReference(description='\n        The sim-filter for generating friendly sims.\n        ')

@sims4.commands.Command('relationship.create')
def create_relationship(source_sim_id, *sim_id_list, _connection=None):
    if not source_sim_id:
        return False
    source_sim_info = services.sim_info_manager().get(source_sim_id)
    if source_sim_info is None:
        return False
    sim_id_list = _get_sim_ids_from_string_list(sim_id_list, _connection)
    if sim_id_list is None:
        return False
    sim_info_set = {services.sim_info_manager().get(sim_id) for sim_id in sim_id_list}
    for sim_info in sim_info_set:
        source_sim_info.relationship_tracker.create_relationship(sim_info.sim_id)
        sim_info.relationship_tracker.create_relationship(source_sim_info.sim_id)
    return True

@sims4.commands.Command('relationship.destroy', command_type=sims4.commands.CommandType.Automation)
def destroy_relationship(source_sim_id, *sim_id_list, _connection=None):
    if not source_sim_id:
        sims4.commands.automation_output('DestroyRelationshipResponse; Success:False', _connection)
        return False
    source_sim_info = services.sim_info_manager().get(source_sim_id)
    if source_sim_info is None:
        sims4.commands.automation_output('DestroyRelationshipResponse; Success:False', _connection)
        return False
    sim_id_list = _get_sim_ids_from_string_list(sim_id_list, _connection)
    if sim_id_list is None:
        sims4.commands.automation_output('DestroyRelationshipResponse; Success:False', _connection)
        return False
    sim_info_set = {services.sim_info_manager().get(sim_id) for sim_id in sim_id_list}
    for sim_info in sim_info_set:
        source_sim_info.relationship_tracker.destroy_relationship(sim_info.sim_id)
        sim_info.relationship_tracker.destroy_relationship(source_sim_info.sim_id)
    sims4.commands.automation_output('DestroyRelationshipResponse; Success:True', _connection)
    return True

@sims4.commands.Command('relationship.introduce_all_sims')
def introduce_all_sims_command():
    introduce_all_sims()

def introduce_all_sims():
    all_sims = [sim_info for sim_info in services.sim_info_manager().objects]
    num_sims = len(all_sims)
    bit = RelationshipCommandTuning.INTRODUCE_BIT
    for sim_a_index in range(num_sims - 1):
        for sim_b_index in range(sim_a_index + 1, num_sims):
            sim_info_a = all_sims[sim_a_index]
            sim_info_b = all_sims[sim_b_index]
            if sim_info_a.relationship_tracker.has_bit(sim_info_b.sim_id, bit):
                pass
            sim_info_a.relationship_tracker.add_relationship_score(sim_info_b.sim_id, RelationshipCommandTuning.INTRODUCE_VALUE, RelationshipCommandTuning.INTRODUCE_TRACK)
            sim_info_b.relationship_tracker.add_relationship_score(sim_info_a.sim_id, RelationshipCommandTuning.INTRODUCE_VALUE, RelationshipCommandTuning.INTRODUCE_TRACK)
            sim_info_a.relationship_tracker.add_relationship_bit(sim_info_b.sim_id, bit)
            sim_info_b.relationship_tracker.add_relationship_bit(sim_info_a.sim_id, bit)

@sims4.commands.Command('relationship.make_all_sims_friends', command_type=sims4.commands.CommandType.Cheat)
def make_all_sims_friends(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('No valid target for relationship.make_all_sims_friends', _connection)
        return
    friends = 0
    for target_sim in services.sim_info_manager().objects:
        while target_sim.id != sim.id:
            sim.relationship_tracker.set_default_tracks(target_sim, update_romance=False)
            target_sim.relationship_tracker.set_default_tracks(sim, update_romance=False)
            friends += 1
    sims4.commands.output('Set {} default friendships for {}'.format(friends, sim.full_name), _connection)

@sims4.commands.Command('relationships.create_friends_for_sim', command_type=sims4.commands.CommandType.Cheat)
def create_friends_for_sim(opt_sim:OptionalTargetParam=None, _connection=None):

    def callback_spawn_sims(filter_results, callback_data):
        for f_result in filter_results:
            services.get_zone_situation_manager().add_debug_sim_id(f_result.id)
            SimSpawner.spawn_sim(f_result)

    quantity = 1
    if RelationshipCommandTuning.CREATE_FRIENDS_COMMAND_QUANTITY is not None:
        quantity = RelationshipCommandTuning.CREATE_FRIENDS_COMMAND_QUANTITY
    friend_filter = RelationshipCommandTuning.CREATE_FRIENDS_COMMAND_FILTER
    active_sim_info = None
    tgt_client = services.client_manager().get(_connection)
    if tgt_client is not None:
        active_sim_info = services.client_manager().get(_connection).active_sim
    else:
        logger.error("tgt_client is None-- can't get active SimInfo")
    if active_sim_info is None:
        sims4.commands.output('error: A valid sim is needed to carry out this command.', _connection)
    sims4.commands.output('Generating friends for active sim...', _connection)
    services.sim_filter_service().submit_matching_filter(number_of_sim_to_find=quantity, sim_filter=friend_filter, callback=callback_spawn_sims, requesting_sim_info=active_sim_info, continue_if_constraints_fail=True)

@sims4.commands.Command('relationship.introduce_sim_to_all_others', command_type=sims4.commands.CommandType.Cheat)
def introduce_sim_to_all_others(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('No valid target for relationship.introduce_sim_to_all_others', _connection)
        return
    for target_sim in services.sim_info_manager().objects:
        if target_sim.id == sim.id:
            pass
        sim.relationship_tracker.add_relationship_score(target_sim.sim_id, RelationshipCommandTuning.INTRODUCE_VALUE, RelationshipCommandTuning.INTRODUCE_TRACK)
        target_sim.relationship_tracker.add_relationship_score(sim.sim_id, RelationshipCommandTuning.INTRODUCE_VALUE, RelationshipCommandTuning.INTRODUCE_TRACK)

@sims4.commands.Command('relationship.clear')
def clear_relationships(source_sim_id:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(source_sim_id, _connection)
    if sim is not None:
        source_sim_info = sim.sim_info
    else:
        if not source_sim_id:
            sims4.commands.output('No sim_info id specified for relationship.clear', _connection)
            return False
        source_sim_info = services.sim_info_manager().get(source_sim_id)
    if source_sim_info is None:
        sims4.commands.output('Invalid sim_info id: {}'.format(source_sim_id), _connection)
        return False
    tracker = source_sim_info.relationship_tracker
    if tracker:
        rel_list = list(tracker)
        for relationship in rel_list:
            tracker.destroy_relationship(relationship.relationship_id)
        sims4.commands.output('Removed {} relationships from {}'.format(len(rel_list), sim), _connection)
    else:
        logger.error("Sim {} doesn't have a RelationshipTracker", source_sim_info)
    return True

@sims4.commands.Command('relationship.add_score', command_type=sims4.commands.CommandType.Automation)
def add_score(source_sim_id, target_sim_id, score_delta, track_type, _connection=None):
    source_sim_info = services.sim_info_manager().get(source_sim_id)
    if source_sim_info is None:
        return False
    if score_delta != score_delta:
        logger.error('Sim {} trying to set {} to NaN', source_sim_info, track_type)
        return False
    source_sim_info.relationship_tracker.add_relationship_score(target_sim_id, score_delta, track_type)
    return True

@sims4.commands.Command('relationship.set_score')
def set_score(source_sim_id, target_sim_id, score, track_type, bidirectional:bool=True, _connection=None):
    source_sim_info = services.sim_info_manager().get(source_sim_id)
    if source_sim_info is None:
        sims4.commands.output("Source sim info doesn't exist in relationship.set_score", _connection)
        return False
    source_sim_info.relationship_tracker.set_relationship_score(target_sim_id, score, track_type)
    if bidirectional:
        target_sim_info = services.sim_info_manager().get(target_sim_id)
        if target_sim_info is None:
            sims4.commands.output("Target sim info doesn't exist in relationship.set_score", _connection)
            return False
        target_sim_info.relationship_tracker.set_relationship_score(source_sim_id, score, track_type)
    return True

@sims4.commands.Command('modifyrelationship', command_type=sims4.commands.CommandType.Cheat)
def modify_relationship(first_name1='', last_name1='', first_name2='', last_name2='', amount:float=0, track_type:TunableInstanceParam(sims4.resources.Types.STATISTIC)=None, _connection=None):
    info1 = services.sim_info_manager().get_sim_info_by_name(first_name1, last_name1)
    info2 = services.sim_info_manager().get_sim_info_by_name(first_name2, last_name2)
    if info1 is not None and info2 is not None:
        info1.relationship_tracker.add_relationship_score(info2.id, amount, track_type)
        return True
    return False

@sims4.commands.Command('relationship.print_score')
def print_relationship_score(source_sim_id, target_sim_id, track_name, _connection=None):
    source_sim_info = services.sim_info_manager().get(source_sim_id)
    if source_sim_info is None:
        return False
    track_type = services.get_instance_manager(sims4.resources.Types.STATISTIC).get(track_name)
    if track_type is None:
        sims4.commands.output('Invalid relationship track: {0}'.format(track_name), _connection)
        return False
    score = source_sim_info.relationship_tracker.get_relationship_score(target_sim_id, track_type)
    sims4.commands.output('Relationship Score: {0}'.format(score), _connection)
    return True

@sims4.commands.Command('relationship.add_bit', command_type=sims4.commands.CommandType.Automation)
def add_bit(source_sim_id, target_sim_id, rel_bit, _connection=None):
    source_sim_info = services.sim_info_manager().get(source_sim_id)
    if source_sim_info is None:
        return False
    source_sim_info.relationship_tracker.add_relationship_bit(target_sim_id, rel_bit, force_add=True)
    return True

@sims4.commands.Command('relationship.remove_bit')
def remove_bit(source_sim_id, target_sim_id, rel_bit, _connection=None):
    source_sim_info = services.sim_info_manager().get(source_sim_id)
    if source_sim_info is None:
        return False
    source_sim_info.relationship_tracker.remove_relationship_bit(target_sim_id, rel_bit)
    return True

@sims4.commands.Command('relationship.print_depth')
def print_relationship_depth(source_sim_id, target_sim_id, _connection=None):
    source_sim_info = services.sim_info_manager().get(source_sim_id)
    if source_sim_info is None:
        return False
    depth = source_sim_info.relationship_tracker.get_relationship_depth(target_sim_id)
    sims4.commands.output('Relationship Depth: {0}'.format(depth), _connection)
    return True

@sims4.commands.Command('relationship.print_info')
def print_relationship_info(source_sim_id, target_sim_id, _connection=None):
    source_sim_info = services.sim_info_manager().get(source_sim_id)
    if source_sim_info is None:
        return False
    source_sim_info.relationship_tracker.print_relationship_info(target_sim_id, _connection)

@sims4.commands.Command('qa.relationship.print_info', command_type=sims4.commands.CommandType.Automation)
def qa_print_relationship_info(source_sim_id, target_sim_id, _connection=None):
    source_sim_info = services.sim_info_manager().get(source_sim_id)
    if source_sim_info is None:
        sims4.commands.automation_output('SimRelationshipInfo; Error:COULD_NOT_FIND_SIM', _connection)
        return False
    relationship_tracker = source_sim_info.relationship_tracker
    out_str = 'SimRelationshipInfo; Sim1:{}, Sim2:{}, Depth:{}'.format(relationship_tracker._sim_info._sim_id, target_sim_id, relationship_tracker.get_relationship_depth(target_sim_id))
    relationship = relationship_tracker._find_relationship(target_sim_id)
    if not relationship:
        out_str += ', Exists:No, NumBits:0, NumTracks:0'
    else:
        out_str += ', Exists:Yes, NumBits:{}, NumTracks:{}'.format(len(relationship._bits), len(relationship._bit_track_tracker))
        for (idx, relationship_bit) in enumerate(relationship._bits):
            out_str += ', Bit{}:{}'.format(idx, relationship_bit.__name__)
        for (idx, relationship_track) in enumerate(relationship._bit_track_tracker):
            out_str += ', Track{}_Name:{}, Track{}_Value:{}'.format(idx, relationship_track.__class__.__name__, idx, relationship_track.get_value())
    sims4.commands.automation_output(out_str, _connection)

def _get_sim_ids_from_string_list(sim_id_list, _connection):
    if not sim_id_list:
        return
    output_list = {int(x) for x in sim_id_list}
    if not output_list:
        sims4.commands.output('No valid sim ids in _get_sim_ids_from_string_list() command.', _connection)
        return
    return output_list

