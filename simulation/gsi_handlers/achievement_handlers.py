from gsi_handlers.gameplay_archiver import GameplayArchiver
from sims4.gsi.dispatcher import GsiHandler
from sims4.gsi.schema import GsiGridSchema
import gsi_handlers
import services
import sims4.resources
achievement_schema = GsiGridSchema(label='Achievements', sim_specific=True)
achievement_schema.add_field('achievement_uid', label='UId', unique_field=True)
achievement_schema.add_field('achievement', label='Achievement', width=3)
achievement_schema.add_field('category', label='Category', width=2)
achievement_schema.add_field('points', label='Points')
achievement_schema.add_field('achievement_complete', label='Done')
achievement_schema.add_field('display_name', label='DisplayStr', hidden=True)
achievement_schema.add_field('description', label='DescStr', hidden=True)
achievement_schema.add_field('simId', label='SimId', hidden=True)
with achievement_schema.add_view_cheat('achievements.complete_achievement', label='Complete') as cheat:
    cheat.add_token_param('achievement_uid')
    cheat.add_token_param('simId')
with achievement_schema.add_has_many('objectives', GsiGridSchema, label='Objectives') as sub_schema:
    sub_schema.add_field('objective', label='Objective')
    sub_schema.add_field('objective_complete', label='Done')

@GsiHandler('achievement_view', achievement_schema)
def generate_achievement_view_data(sim_id:int=None):
    sim_info = services.sim_info_manager().get(sim_id)
    achievement_manager = services.get_instance_manager(sims4.resources.Types.ACHIEVEMENT)
    all_achievements = []
    for achievement_id in achievement_manager.types:
        achievement = achievement_manager.get(achievement_id)
        achievement_data = {}
        achievement_data['achievement'] = str(achievement)
        achievement_data['achievement_uid'] = int(achievement.guid64)
        achievement_data['category'] = str(achievement.category)
        achievement_data['points'] = int(achievement.point_value)
        achievement_data['display_name'] = str(hex(achievement.display_name.hash))
        achievement_data['description'] = str(hex(achievement.descriptive_text.hash))
        achievement_data['achievement_complete'] = False
        achievement_data['objectives'] = []
        achievement_data['simId'] = str(sim_id)
        if not sim_info.account.achievement_tracker.milestone_completed(achievement.guid64):
            for objective in achievement.objectives:
                objective_data = {}
                objective_data['objective'] = str(objective)
                if sim_info.account.achievement_tracker.objective_completed(objective.guid64):
                    objective_data['objective_complete'] = True
                else:
                    objective_data['objective_complete'] = False
                achievement_data['objectives'].append(objective_data)
        else:
            achievement_data['achievement_complete'] = True
            for objective in achievement.objectives:
                objective_data = {}
                objective_data['objective'] = str(objective)
                objective_data['objective_complete'] = True
                achievement_data['objectives'].append(objective_data)
        all_achievements.append(achievement_data)
    return all_achievements

achievement_event_schema = GsiGridSchema(label='Achievement Events')
achievement_event_schema.add_field('sim', label='Sim', width=2)
achievement_event_schema.add_field('event', label='Event', width=2)
with achievement_event_schema.add_has_many('Objectives Processed', GsiGridSchema) as sub_schema:
    sub_schema.add_field('achievement', label='Achievement', width=2)
    sub_schema.add_field('completed', label='Completed')
    sub_schema.add_field('test_type', label='Test', width=2)
    sub_schema.add_field('test_result', label='Result', width=3)
archiver = GameplayArchiver('achievement_events', achievement_event_schema)

def archive_achievement_event_set(event_data):
    archiver.archive(data=event_data)

