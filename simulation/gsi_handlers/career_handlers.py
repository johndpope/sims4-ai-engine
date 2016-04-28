from sims4.gsi.dispatcher import GsiHandler
from sims4.gsi.schema import GsiGridSchema, GsiFieldVisualizers
from sims4.resources import Types
import services

def generate_all_careers():
    return [cls.__name__ for cls in services.get_instance_manager(Types.CAREER).types.values()]

sim_career_schema = GsiGridSchema(label='Careers')
sim_career_schema.add_field('sim', label='Sim', width=2, unique_field=True)
sim_career_schema.add_field('sim_id', label='Sim ID', hidden=True)
sim_career_schema.add_field('career_uid', label='UID', hidden=True)
sim_career_schema.add_field('name', label='Name', width=2)
sim_career_schema.add_field('level', label='Level')
sim_career_schema.add_field('time_to_work', label='Time To Work')
sim_career_schema.add_field('current_work_time', label='Current Work')
sim_career_schema.add_field('next_work_time', label='Next Work')
sim_career_schema.add_field('is_work_time', label='Is Work Time')
sim_career_schema.add_field('currently_at_work', label='Currently At Work')
sim_career_schema.add_field('attended_work', label='Attended Work')
sim_career_schema.add_field('work_performance', label='Performance', type=GsiFieldVisualizers.INT)
sim_career_schema.add_field('active_situation_id', label='Situation ID', type=GsiFieldVisualizers.INT)
with sim_career_schema.add_has_many('career_levels', GsiGridSchema, label='Levels') as sub_schema:
    sub_schema.add_field('name', label='Name')
    sub_schema.add_field('simoleons', label='Simoleons/Hr')
    sub_schema.add_field('fired_lvl', label='Fire Lvl')
    sub_schema.add_field('demotion_lvl', label='Demotion Lvl')
    sub_schema.add_field('promote_lvl', label='Promote Lvl')
with sim_career_schema.add_has_many('objectives', GsiGridSchema, label='Current Objectives') as sub_schema:
    sub_schema.add_field('objective', label='Objective')
    sub_schema.add_field('is_complete', label='Complete?')
with sim_career_schema.add_view_cheat('careers.promote', label='Promote Sim') as cheat:
    cheat.add_token_param('career_uid')
    cheat.add_token_param('sim_id')
with sim_career_schema.add_view_cheat('careers.demote', label='Demote Sim') as cheat:
    cheat.add_token_param('career_uid')
    cheat.add_token_param('sim_id')
with sim_career_schema.add_view_cheat('careers.remove_career', label='Remove Career') as cheat:
    cheat.add_token_param('career_uid')
    cheat.add_token_param('sim_id')
with sim_career_schema.add_view_cheat('careers.trigger_optional_situation', label='Trigger Situation') as cheat:
    cheat.add_token_param('career_uid')
    cheat.add_token_param('sim_id')
with sim_career_schema.add_view_cheat('careers.add_performance', label='+50 Performance') as cheat:
    cheat.add_token_param('sim_id')
    cheat.add_static_param('50')
    cheat.add_token_param('career_uid')

def add_career_cheats(manager):
    with sim_career_schema.add_view_cheat('careers.add_career', label='Add Career') as cheat:
        cheat.add_token_param('career_string', dynamic_token_fn=generate_all_careers)
        cheat.add_token_param('sim_id')

services.get_instance_manager(Types.CAREER).add_on_load_complete(add_career_cheats)

def get_work_hours_str(start_time, end_time):
    return '{} - {}'.format(start_time, end_time)

def get_career_level_data(career, career_track, level_data):
    for level in career_track.career_levels:
        level_name = level.__name__
        if career.current_level_tuning is level:
            level_name = '** {} **'.format(level_name)
        career_level_info = {'name': level_name, 'simoleons': level.simoleons_per_hour, 'fired_lvl': level.fired_performance_level, 'demotion_lvl': level.demotion_performance_level, 'promote_lvl': level.promote_performance_level}
        level_data.append(career_level_info)
    for track in career_track.branches:
        get_career_level_data(career, track, level_data)

def get_all_career_level_data(career):
    career_level_data = []
    get_career_level_data(career, career.start_track, career_level_data)
    return career_level_data

@GsiHandler('sim_career_view', sim_career_schema)
def generate_sim_career_view_data(sim_id:int=None):
    career_view_data = []
    sim_info_manager = services.sim_info_manager()
    if sim_info_manager is not None:
        for sim_info in sim_info_manager.objects:
            if sim_info.career_tracker.careers:
                for career in sim_info.career_tracker.careers.values():
                    career_data = {'sim': '{}(uid: {})'.format(sim_info.full_name, int(career.guid64)), 'sim_id': str(sim_info.sim_id), 'career_uid': int(career.guid64)}
                    while career is not None:
                        career_data['name'] = type(career).__name__
                        cur_level = '{} ({})'.format(career.user_level, career.level)
                        career_data['level'] = cur_level
                        (time_to_work, next_start_time, next_end_time) = career.get_next_work_time()
                        career_data['time_to_work'] = str(time_to_work)
                        if career._current_work_start is not None:
                            career_data['current_work_time'] = get_work_hours_str(career._current_work_start, career._current_work_end)
                        if next_start_time is not None:
                            career_data['next_work_time'] = get_work_hours_str(next_start_time, next_end_time)
                        career_data['is_work_time'] = career.is_work_time
                        career_data['currently_at_work'] = career.currently_at_work
                        career_data['attended_work'] = career.attended_work
                        career_data['work_performance'] = career.work_performance
                        career_data['active_situation_id'] = career.active_situation_id
                        career_data['objectives'] = []
                        if career.current_level_tuning.aspiration is not None:
                            for objective in career.current_level_tuning.aspiration.objectives:
                                objective_data = {}
                                objective_data['objective'] = str(objective)
                                if sim_info.aspiration_tracker.objective_completed(objective.guid64):
                                    objective_data['is_complete'] = True
                                else:
                                    objective_data['is_complete'] = False
                                career_data['objectives'].append(objective_data)
                        career_level_data = get_all_career_level_data(career)
                        career_data['career_levels'] = career_level_data
                        career_view_data.append(career_data)
            else:
                career_data = {'sim': sim_info.full_name, 'sim_id': str(sim_info.sim_id)}
                career_data['name'] = 'No Career'
                career_data['career_levels'] = []
                career_view_data.append(career_data)
    return career_view_data

