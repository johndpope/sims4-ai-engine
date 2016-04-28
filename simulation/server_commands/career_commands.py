from careers.career_ops import CareerOps
from careers.career_tuning import Career
from interactions.context import QueueInsertStrategy
from server_commands.argument_helpers import OptionalTargetParam, get_optional_target, TunableInstanceParam, RequiredTargetParam
from situations.situation_guest_list import SituationGuestInfo, SituationInvitationPurpose, SituationGuestList
import interactions
import services
import sims4.commands
import sims4.log
logger = sims4.log.Logger('CareerCommand')

@sims4.commands.Command('careers.select', command_type=sims4.commands.CommandType.Live)
def select_career(sim_id:int=None, career_instance_id:int=None, track_id:int=None, level:int=None, company_name_hash:int=None, reason:int=CareerOps.JOIN_CAREER, _connection=None):
    if sim_id is None or (career_instance_id is None or track_id is None) or level is None:
        logger.error('Not all of the data needed for the careers.select command was passed.')
        return False
    career_manager = services.get_instance_manager(sims4.resources.Types.CAREER)
    career_type = career_manager.get(career_instance_id)
    if career_type is None:
        logger.error('invalid career Id sent to careers.select')
        return False
    sim = services.object_manager().get(sim_id)
    if sim_id is None:
        logger.error('invalid sim Id passed to careers.select')
        return False
    career_track_manager = services.get_instance_manager(sims4.resources.Types.CAREER_TRACK)
    career_track = career_track_manager.get(track_id)
    if career_track is None:
        logger.error('invalid career track Id passed to careers.select')
        return False
    if reason is None:
        logger.error('invalid career selection reason passed to careers.select')
        return False
    career_tracker = sim.sim_info.career_tracker
    if reason == CareerOps.JOIN_CAREER:
        current_career = career_tracker.get_career_by_uid(career_instance_id)
        if current_career is not None:
            current_career.set_new_career_track(track_id)
        else:
            career_tracker.add_career(career_type(sim.sim_info, company_name=company_name_hash), show_confirmation_dialog=True)
    if reason == CareerOps.QUIT_CAREER:
        career_tracker.remove_career(career_instance_id)

@sims4.commands.Command('careers.start_event', command_type=sims4.commands.CommandType.Live)
def start_career_event(sim_id:int=None, career_uid:int=None, _connection=None):
    if sim_id is None:
        logger.error('careers.start_event got no Sim to start the event for.')
        return False
    sim = services.object_manager().get(sim_id)
    if sim_id is None:
        logger.error('invalid sim Id passed to careers.start_event')
        return False
    career = sim.sim_info.career_tracker.get_career_by_uid(career_uid)
    career.set_career_situation_available(False)
    career.start_career_situation()

@sims4.commands.Command('careers.force_event')
def force_career_event(career_situation_type, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if not sim:
        sims4.commands.output('Invalid Sim ID: {}'.format(opt_sim), _connection)
        return
    guest_info = SituationGuestInfo.construct_from_purpose(sim.id, career_situation_type.job, SituationInvitationPurpose.CAREER)
    guest_list = SituationGuestList()
    guest_list.add_guest_info(guest_info)
    situation_manager = services.get_zone_situation_manager()
    situation = career_situation_type.situation
    if not situation.has_venue_location():
        logger.error("Tried forcing a career event:{} and couldn't find a valid venue.", career_situation_type)
        return False
    zone_id = situation.get_venue_location()
    situation_manager.create_situation(situation, guest_list=guest_list, zone_id=zone_id)

@sims4.commands.Command('careers.send_to_work', command_type=sims4.commands.CommandType.Live)
def send_to_work(sim_id:int=None, career_uid:int=None, _connection=None):
    if sim_id is None:
        logger.error('careers.send_to_work got no Sim to start the event for.')
        return False
    sim = services.object_manager().get(sim_id)
    if sim is None:
        logger.error('invalid sim Id passed to careers.send_to_work')
        return False
    career = sim.sim_info.career_tracker.get_career_by_uid(career_uid)
    career.push_go_to_work_affordance()

@sims4.commands.Command('careers.leave_work', command_type=sims4.commands.CommandType.Live)
def leave_work(sim_id:int=None, career_uid:int=None, _connection=None):
    if sim_id is None:
        logger.error('careers.leave_work got no Sim to start the event for.')
        return False
    sim = services.object_manager().get(sim_id)
    if sim is None:
        logger.error('invalid Sim Id passed to careers.leave_work')
        return False
    career = sim.sim_info.career_tracker.get_career_by_uid(career_uid)
    if career is None:
        logger.error('invalid Career Id passed to careers.leave_work')
        return False
    career.leave_work_early()
    return True

@sims4.commands.Command('careers.list_careers')
def list_all_careers(_connection=None):
    career_manager = services.get_instance_manager(sims4.resources.Types.CAREER)
    current_time = services.time_service().sim_now
    sims4.commands.output('Current Time: {}'.format(current_time), _connection)
    for career_id in career_manager.types:
        career = career_manager.get(career_id)
        sims4.commands.output('{}: {}'.format(career, int(career.guid64)), _connection)
        cur_track = career.start_track
        sims4.commands.output('    {}: {}'.format(cur_track, int(cur_track.guid)), _connection)
        for career_level in cur_track.career_levels:
            sims4.commands.output('        {}'.format(career_level), _connection)

@sims4.commands.Command('qa.careers.info', command_type=sims4.commands.CommandType.Automation)
def qa_print_sim_career_info(opt_sim:OptionalTargetParam=None, _connection=None):
    output = sims4.commands.AutomationOutput(_connection)
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('Target sim could not be found', _connection)
        return
    careers = sim.sim_info.career_tracker.careers.values()
    results = 'CareerInfo; NumCareers:%d' % len(careers)
    for (idx, career) in enumerate(careers):
        results += ', Name%d:%s' % (idx, type(career).__name__) + ', Performance%d:%s' % (idx, career.work_performance) + ', Level%d:%s' % (idx, career.level) + ', Track%d:%s' % (idx, career.current_track_tuning.__name__) + ', Company%d:%s' % (idx, career.company_name)
    output(results)
    sims4.commands.output(results, _connection)

@sims4.commands.Command('careers.add_career', command_type=sims4.commands.CommandType.Automation)
def add_career_to_sim(career_type, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if career_type is None:
        career_names = []
        career_manager = services.get_instance_manager(sims4.resources.Types.CAREER)
        for career_id in career_manager.types:
            career_type = career_manager.get(career_id)
            career_names.append(career_type.__name__)
        all_careers_str = ' '.join(career_names)
        sims4.commands.output('Usage: careers.add_career <career_name> <opt_sim>)'.format(all_careers_str), _connection)
        sims4.commands.output('Please choose a valid career: {}'.format(all_careers_str), _connection)
        return
    if sim is not None:
        sim.sim_info.career_tracker.add_career(career_type(sim.sim_info))
        return True

@sims4.commands.Command('careers.remove_career', command_type=sims4.commands.CommandType.Automation)
def remove_career_from_sim(career_type, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.sim_info.career_tracker.remove_career(career_type.guid64)
        return True
    return False

@sims4.commands.Command('careers.promote', command_type=sims4.commands.CommandType.Automation)
def career_promote_sim(career_type, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        career = sim.sim_info.career_tracker.get_career_by_uid(career_type.guid64)
        if career is not None:
            career.promote()
            return True
    return False

@sims4.commands.Command('careers.demote', command_type=sims4.commands.CommandType.Automation)
def career_demote_sim(career_type, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        career = sim.sim_info.career_tracker.get_career_by_uid(career_type.guid64)
        if career is not None:
            career.demote()
            return True
    return False

@sims4.commands.Command('careers.trigger_optional_situation')
def trigger_career_situation(opt_sim:OptionalTargetParam=None, career_uid:int=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        career = sim.sim_info.career_tracker.get_career_by_uid(career_uid)
        if career is not None:
            career._career_situation_callback(None, None, None)

@sims4.commands.Command('careers.add_performance')
def add_career_performance(opt_sim:OptionalTargetParam=None, amount:int=None, career_uid:int=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('careers.add_performance Invalid Sim passed', _connection)
        sims4.commands.output('Usage: careers.add_performance <opt_sim> <amount>', _connection)
        return
    if amount is None:
        sims4.commands.output('careers.add_performance Invalid amount passed', _connection)
        sims4.commands.output('Usage: careers.add_performance <opt_sim> <amount>', _connection)
        return
    if len(sim.sim_info.career_tracker.careers) > 0:
        career = sim.sim_info.career_tracker.get_career_by_uid(career_uid)
        if career is not None:
            performance_stat = sim.statistic_tracker.get_statistic(career.current_level_tuning.performance_stat)
            performance_stat.add_value(amount)

@sims4.commands.Command('careers.find_career', command_type=sims4.commands.CommandType.Live)
def find_career(sim:RequiredTargetParam=None, _connection=None):
    sim = sim.get_target()
    if sim.queue.has_duplicate_super_affordance(Career.FIND_JOB_PHONE_INTERACTION, sim, None):
        return False
    context = interactions.context.InteractionContext(sim, interactions.context.InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT, interactions.priority.Priority.High, insert_strategy=QueueInsertStrategy.NEXT)
    enqueue_result = sim.push_super_affordance(Career.FIND_JOB_PHONE_INTERACTION, sim, context)
    if not enqueue_result:
        return False
    return True

@sims4.commands.Command('careers.show_parent_tracks', command_type=sims4.commands.CommandType.DebugOnly)
def show_parent_tracks(sim:RequiredTargetParam=None, _connection=None):
    for track in services.get_instance_manager(sims4.resources.Types.CAREER_TRACK).get_ordered_types():
        sims4.commands.output('{} -> {}'.format(str(track), str(track.parent_track)), _connection)

