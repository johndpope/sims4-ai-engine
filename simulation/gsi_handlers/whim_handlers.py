from sims4.gsi.dispatcher import GsiHandler
from sims4.gsi.schema import GsiGridSchema, GsiFieldVisualizers
import services
import sims4.resources
sim_whim_schema = GsiGridSchema(label='Whims/Whims Current', sim_specific=True)
sim_whim_schema.add_field('sim_id', label='Sim ID', hidden=True)
sim_whim_schema.add_field('whim', label='Whim', unique_field=True, width=3)
sim_whim_schema.add_field('instance', label='Instance', width=3)
sim_whim_schema.add_field('whimset', label='Whimset', width=3)
sim_whim_schema.add_field('target', label='Target', width=2)
sim_whim_schema.add_field('value', label='Value', width=1, type=GsiFieldVisualizers.INT)
with sim_whim_schema.add_view_cheat('sims.whims_complete_whim', label='Complete Whim', dbl_click=True) as cheat:
    cheat.add_token_param('whim')
    cheat.add_token_param('sim_id')

@GsiHandler('sim_whim_view', sim_whim_schema)
def generate_sim_whim_view_data(sim_id:int=None):
    whim_view_data = []
    sim_info_manager = services.sim_info_manager()
    if sim_info_manager is not None:
        for sim_info in sim_info_manager.objects:
            while sim_info.sim_id == sim_id:
                whim_tracker = sim_info._whim_tracker
                while True:
                    for whim in whim_tracker.get_goal_info():
                        source_whimset = whim_tracker.get_goal_set(whim)
                        whim_data = {'sim_id': str(sim_info.sim_id), 'whim': whim.get_gsi_name(), 'instance': whim.__class__.__name__, 'whimset': source_whimset.__name__, 'target': str(whim_tracker.get_whimset_target(source_whimset)), 'value': whim.score}
                        whim_view_data.append(whim_data)
    return whim_view_data

sim_activeset_schema = GsiGridSchema(label='Whims/Whimsets Active', sim_specific=True)
sim_activeset_schema.add_field('sim_id', label='Sim ID', hidden=True)
sim_activeset_schema.add_field('whimset', label='Whimset', unique_field=True, width=3)
sim_activeset_schema.add_field('time', label='Time Remaining', width=1, type=GsiFieldVisualizers.TIME)
sim_activeset_schema.add_field('priority', label='Priority', width=1, type=GsiFieldVisualizers.INT)
sim_activeset_schema.add_field('trigger', label='Triggered By', width=3)
sim_activeset_schema.add_field('target', label='Current Target', width=2)
with sim_activeset_schema.add_view_cheat('sims.whims_give_whim_from_set', label='Give from Whimset', dbl_click=True) as cheat:
    cheat.add_token_param('whimset')
    cheat.add_token_param('sim_id')
with sim_activeset_schema.add_has_many('potential_whims_view', GsiGridSchema, label='Potential Whims') as sub_schema:
    sub_schema.add_field('whim', label='Whim', width=3)
    sub_schema.add_field('status', label='Status', width=5)
    sub_schema.add_field('weight', label='Weight', width=1, type=GsiFieldVisualizers.FLOAT)

@GsiHandler('sim_activeset_view', sim_activeset_schema)
def generate_sim_activeset_view_data(sim_id:int=None):
    activeset_view_data = []
    sim_info_manager = services.sim_info_manager()
    if sim_info_manager is not None:
        for sim_info in sim_info_manager.objects:
            while sim_info.sim_id == sim_id:
                whim_tracker = sim_info._whim_tracker
                active_sets = []
                active_sets.extend(whim_tracker.active_sets)
                active_sets.extend(whim_tracker.active_chained_sets)
                while True:
                    for whimset in active_sets:
                        time_left = ''
                        if whimset in whim_tracker.alarm_handles:
                            time_left = str(whim_tracker.alarm_handles[whimset].get_remaining_time())
                        trigger = 'Cheat'
                        if whimset in whim_tracker._whimset_objective_map:
                            trigger_obj = whim_tracker._whimset_objective_map[whimset]
                            if hasattr(trigger_obj, '__name__'):
                                trigger = trigger_obj.__name__
                            else:
                                trigger = trigger_obj.__class__.__name__
                        set_data = {'sim_id': str(sim_info.sim_id), 'whimset': whimset.__name__, 'time': time_left, 'priority': whim_tracker.get_priority(whimset), 'trigger': trigger, 'target': str(whim_tracker.get_whimset_target(whimset))}
                        sub_data = []
                        for whim in whimset.whims:
                            test_result = 'Not Chosen'
                            if whim.goal in whim_tracker._test_results_map:
                                if whim_tracker._test_results_map[whim.goal]:
                                    test_result = 'Active'
                                else:
                                    result = whim_tracker._test_results_map[whim.goal]
                                    if result is False and hasattr(result, 'reason'):
                                        result = result.reason
                                    test_result = str(whim_tracker._test_results_map[whim.goal])
                            whim_data = {'whim': whim.goal.__name__, 'status': test_result, 'weight': whim.weight}
                            sub_data.append(whim_data)
                        set_data['potential_whims_view'] = sub_data
                        activeset_view_data.append(set_data)
    return activeset_view_data

sim_whimset_schema = GsiGridSchema(label='Whims/Whimsets All', sim_specific=True)
sim_whimset_schema.add_field('simId', label='Sim ID', hidden=True)
sim_whimset_schema.add_field('whimset', label='WhimSet', unique_field=True, width=3)
sim_whimset_schema.add_field('priority', label='Priority', width=1, type=GsiFieldVisualizers.INT)
sim_whimset_schema.add_field('target', label='Target', width=2)
sim_whimset_schema.add_field('base_priority', label='Base', width=1, type=GsiFieldVisualizers.INT)
sim_whimset_schema.add_field('active_priority', label='Activated', width=1, type=GsiFieldVisualizers.INT)
sim_whimset_schema.add_field('chained_priority', label='Chained', width=1, type=GsiFieldVisualizers.INT)
sim_whimset_schema.add_field('time_left', label='Time Left', width=2, type=GsiFieldVisualizers.TIME)
sim_whimset_schema.add_field('whims_in_set', label='Whims In Set', width=3)
with sim_whimset_schema.add_view_cheat('sims.whims_activate_set', label='Activate Whimset', dbl_click=True) as cheat:
    cheat.add_token_param('whimset')
    cheat.add_token_param('simId')

@GsiHandler('sim_whimset_view', sim_whimset_schema)
def generate_sim_whimset_view_data(sim_id:int=None):
    whimset_view_data = []
    sim_info_manager = services.sim_info_manager()
    if sim_info_manager is not None:
        for sim_info in sim_info_manager.objects:
            while sim_info.sim_id == sim_id:
                whim_tracker = sim_info._whim_tracker
                whim_set_list = []
                for whim_set in services.get_instance_manager(sims4.resources.Types.ASPIRATION).all_whim_sets:
                    priority = whim_tracker.get_priority(whim_set)
                    whim_set_list.append((priority, whim_set))
                    whim_set_list = sorted(whim_set_list, key=lambda whim_set: whim_set[0])
                    whim_set_list.reverse()
                if whim_set_list is not None:
                    for whim_set_data in whim_set_list:
                        whim_set = whim_set_data[1]
                        whims_in_set_str = ', '.join(whim.goal.__name__ for whim in whim_set.whims)
                        time_left = ''
                        if whim_set in whim_tracker.alarm_handles:
                            time_left = str(whim_tracker.alarm_handles[whim_set].get_remaining_time())
                        whim_set_entry = {'simId': sim_id, 'whimset': whim_set.__name__, 'priority': whim_tracker.get_priority(whim_set), 'target': str(whim_tracker.get_whimset_target(whim_set)), 'base_priority': whim_set.base_priority, 'active_priority': whim_set.activated_priority, 'chained_priority': whim_set.chained_priority, 'time_left': time_left, 'whims_in_set': whims_in_set_str}
                        whimset_view_data.append(whim_set_entry)
                return whimset_view_data

