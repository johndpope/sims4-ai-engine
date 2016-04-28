from sims4.gsi.dispatcher import GsiHandler
from sims4.gsi.schema import GsiGridSchema, GsiFieldVisualizers
import date_and_time
import services
situation_sim_schema = GsiGridSchema(label='Situation Manager')
situation_sim_schema.add_field('situation_id', label='Situation Id', width=1, unique_field=True)
situation_sim_schema.add_field('situation', label='Situation Name', width=3)
situation_sim_schema.add_field('state', label='State', width=1.5)
situation_sim_schema.add_field('time_left', label='Time Left')
situation_sim_schema.add_field('sim_count', label='Number of Sims', type=GsiFieldVisualizers.INT, width=0.5)
situation_sim_schema.add_field('score', label='Score', type=GsiFieldVisualizers.FLOAT, width=0.5)
situation_sim_schema.add_field('level', label='Level', width=1)
with situation_sim_schema.add_has_many('Sims', GsiGridSchema) as sub_schema:
    sub_schema.add_field('sim_name', label='Sim')
    sub_schema.add_field('sim_score', label='Score', type=GsiFieldVisualizers.FLOAT)
    sub_schema.add_field('sim_job', label='Job')
    sub_schema.add_field('sim_role', label='Role')
    sub_schema.add_field('sim_emotion', label='Emotion')
    sub_schema.add_field('sim_on_active_lot', label='On Active Lot')
with situation_sim_schema.add_has_many('Goals', GsiGridSchema) as sub_schema:
    sub_schema.add_field('goal', label='Goal')
    sub_schema.add_field('goal_set', label='Goal Set')
    sub_schema.add_field('time_created', label='Time Created')
    sub_schema.add_field('time_completed', label='Time Completed')
    sub_schema.add_field('score', label='Score', type=GsiFieldVisualizers.INT, width=1)
with situation_sim_schema.add_has_many('Churn', GsiGridSchema) as sub_schema:
    sub_schema.add_field('sim_job', label='Job')
    sub_schema.add_field('min', label='Min', type=GsiFieldVisualizers.INT, width=1)
    sub_schema.add_field('max', label='Max', type=GsiFieldVisualizers.INT, width=1)
    sub_schema.add_field('here', label='Sims Here', type=GsiFieldVisualizers.INT, width=1)
    sub_schema.add_field('coming', label='Sims Coming', type=GsiFieldVisualizers.INT, width=1)
    sub_schema.add_field('time_left', label='Time Until Churn')
with situation_sim_schema.add_has_many('Shifts', GsiGridSchema) as sub_schema:
    sub_schema.add_field('sim_job', label='Job')
    sub_schema.add_field('num', label='Tuned Staffing', type=GsiFieldVisualizers.INT, width=1)
    sub_schema.add_field('here', label='Sims Here', type=GsiFieldVisualizers.INT, width=1)
    sub_schema.add_field('coming', label='Sims Coming', type=GsiFieldVisualizers.INT, width=1)
    sub_schema.add_field('change_time_left', label='Time Until Shift Change')
    sub_schema.add_field('churn_time_left', label='Time Until Churn')
with situation_sim_schema.add_has_many('Global', GsiGridSchema) as sub_schema:
    sub_schema.add_field('npc', label='NPC')
    sub_schema.add_field('npc_time_on_lot', label='On Lot Time')
    sub_schema.add_field('npc_blacklist_time', label='Blacklist Time')

@GsiHandler('situations', situation_sim_schema)
def generate_situation_data(zone_id:int=None):
    all_situations = []
    sit_man = services.get_zone_situation_manager(zone_id=zone_id)
    if sit_man is None:
        return all_situations
    global_data = []
    for sim_info in tuple(services.sim_info_manager().values()):
        sim = sim_info.get_sim_instance()
        if sim is not None:
            if not sim.sim_info.is_npc:
                pass
            on_lot_time = sit_man.get_time_span_sim_has_been_on_lot(sim)
            if on_lot_time is not None:
                on_lot_str = str(on_lot_time)
            else:
                on_lot_str = 'ERROR'
            blacklist_time = sit_man.get_remaining_blacklist_time_span(sim.id)
            if blacklist_time is not date_and_time.TimeSpan.ZERO:
                blacklist_str = str(blacklist_time)
            else:
                blacklist_str = ''
        else:
            on_lot_str = ''
            blacklist_time = sit_man.get_remaining_blacklist_time_span(sim_info.id)
            while blacklist_time is not date_and_time.TimeSpan.ZERO:
                blacklist_str = str(blacklist_time)
                global_data.append({'npc': sim_info.full_name, 'npc_time_on_lot': on_lot_str, 'npc_blacklist_time': blacklist_str})
        global_data.append({'npc': sim_info.full_name, 'npc_time_on_lot': on_lot_str, 'npc_blacklist_time': blacklist_str})
    situations = list(sit_man._objects.values())
    for sit in situations:
        sim_data = []
        for (sim, situation_sim) in tuple(sit._situation_sims.items()):
            while sim:
                sim_data.append({'sim_name': sim.full_name, 'sim_job': situation_sim.current_job_type.__name__ if situation_sim.current_job_type is not None else 'None', 'sim_role': situation_sim.current_role_state_type.__name__ if situation_sim.current_role_state_type is not None else 'None', 'sim_emotion': situation_sim.emotional_buff_name, 'sim_on_active_lot': sim.is_on_active_lot()})
        goal_data = []
        goals = sit.get_situation_goal_info()
        if goals is not None:
            for (goal, tuned_goal_set) in goals:
                goal_data.append({'goal': goal.get_gsi_name(), 'goal_set': tuned_goal_set.__name__ if tuned_goal_set is not None else 'None', 'time_created': str(goal.created_time), 'time_completed': str(goal.completed_time), 'score': goal.score})
            completed_goals = sit.get_situation_completed_goal_info()
            if completed_goals is not None:
                while True:
                    for (goal, tuned_goal_set) in completed_goals:
                        goal_data.append({'goal': goal.get_gsi_name(), 'goal_set': tuned_goal_set.__name__ if tuned_goal_set is not None else 'None', 'time_created': str(goal.created_time), 'time_completed': str(goal.completed_time), 'score': goal.score})
        churn_data = []
        for job_data in sit.gsi_all_jobs_data_gen():
            while job_data.gsi_has_churn():
                churn_data.append({'sim_job': job_data.gsi_get_job_name(), 'min': job_data.gsi_get_churn_min(), 'max': job_data.gsi_get_churn_max(), 'here': job_data.gsi_get_num_churn_sims_here(), 'coming': job_data.gsi_get_num_churn_sims_coming(), 'time_left': str(job_data.gsi_get_remaining_time_until_churn())})
        shift_data = []
        for job_data in sit.gsi_all_jobs_data_gen():
            while job_data.gsi_has_shifts():
                shift_data.append({'sim_job': job_data.gsi_get_job_name(), 'num': job_data.gsi_get_shifts_staffing(), 'here': job_data.gsi_get_num_churn_sims_here(), 'coming': job_data.gsi_get_num_churn_sims_coming(), 'change_time_left': str(job_data.gsi_get_remaining_time_until_shift_change()), 'churn_time_left': str(job_data.gsi_get_remaining_time_until_churn())})
        all_situations.append({'situation_id': str(sit.id), 'situation': str(sit), 'time_left': str(sit._get_remaining_time()) if sit._get_remaining_time() is not None else 'Forever', 'state': sit.get_phase_state_name_for_gsi(), 'sim_count': len(sit._situation_sims), 'score': sit.score, 'level': str(sit.get_level()), 'Sims': sim_data, 'Goals': goal_data, 'Churn': churn_data, 'Shifts': shift_data, 'Global': global_data})
    return all_situations

situation_bouncer_schema = GsiGridSchema(label='Situation Bouncer')
situation_bouncer_schema.add_field('situation', label='Situation')
situation_bouncer_schema.add_field('situation_id', label='Situation Id', type=GsiFieldVisualizers.INT, width=1)
situation_bouncer_schema.add_field('job', label='Job')
situation_bouncer_schema.add_field('filter', label='Filter')
situation_bouncer_schema.add_field('status', label='Status')
situation_bouncer_schema.add_field('klout', label='Klout', type=GsiFieldVisualizers.INT, width=1)
situation_bouncer_schema.add_field('priority', label='Priority')
situation_bouncer_schema.add_field('sim_name', label='Assigned Sim')
situation_bouncer_schema.add_field('spawning_option', label='Spawning Option')
situation_bouncer_schema.add_field('unique', label='unique', unique_field=True, hidden=True)
with situation_bouncer_schema.add_has_many('Global', GsiGridSchema) as sub_schema:
    sub_schema.add_field('npcs_here', label='NPCs Here', type=GsiFieldVisualizers.INT, width=1)
    sub_schema.add_field('npcs_leaving', label='NPCs Leaving', type=GsiFieldVisualizers.INT, width=1)
    sub_schema.add_field('npc_soft_cap', label='NPC Soft Cap', type=GsiFieldVisualizers.INT, width=1)

@GsiHandler('situation_bouncer', situation_bouncer_schema)
def generate_situation_bouncer_data(zone_id:int=None):
    all_requests = []
    situation_manager = services.get_zone_situation_manager(zone_id=zone_id)
    if situation_manager is None:
        return all_requests
    bouncer = situation_manager.bouncer
    global_data = []
    global_data.append({'npcs_here': bouncer._number_of_npcs_on_lot, 'npcs_leaving': bouncer._number_of_npcs_leaving, 'npc_soft_cap': situation_manager.npc_soft_cap})
    for request in bouncer._all_requests_gen():
        all_requests.append({'situation': str(request._situation), 'situation_id': str(request._situation.id), 'job': request._job_type.__name__, 'filter': request._sim_filter.__name__ if request._sim_filter is not None else 'None', 'status': request._status.name, 'klout': request._get_request_klout() if request._get_request_klout() is not None else 10000, 'priority': request._request_priority.name, 'sim_name': request.assigned_sim.full_name if request.assigned_sim is not None else 'None', 'spawning_option': request.spawning_option.name, 'unique': str(id(request)), 'Global': global_data})
    return all_requests

