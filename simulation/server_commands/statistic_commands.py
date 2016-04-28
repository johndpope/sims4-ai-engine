import collections
import random
import weakref
from autonomy.autonomy_request import AutonomyPostureBehavior
from interactions import priority
from interactions.aop import AffordanceObjectPair
from interactions.context import InteractionContext, InteractionBucketType
from server_commands.argument_helpers import OptionalTargetParam, get_optional_target, TunableInstanceParam
from sims.sim_info import SimInfo
from statistics.commodity import Commodity
from statistics.continuous_statistic import ContinuousStatistic
from statistics.skill import Skill
from statistics.tunable import CommodityTuning
import autonomy.autonomy_modes
import autonomy.autonomy_modifier
import services
import sims4.commands
import statistics.skill
logger = sims4.log.Logger('SimStatistics')

@sims4.commands.Command('stats.show_stats')
def show_statistics(display_skill_only=False, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        for stat in sim.statistics_gen():
            while not display_skill_only or isinstance(stat, statistics.skill.Skill):
                s = 'Statistic: {}, Value: {},  Level: {}.'.format(stat.__class__.__name__, stat.get_value(), stat.get_user_value())
                sims4.commands.output(s, _connection)

@sims4.commands.Command('stats.show_commodities', command_type=sims4.commands.CommandType.Automation)
def show_commodities(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.commodity_tracker.debug_output_all(_connection)
        sim.statistic_tracker.debug_output_all(_connection)
    else:
        sims4.commands.output('No target for stats.show_commodities.', _connection)

@sims4.commands.Command('stats.show_static_commodities')
def show_static_commodities(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.static_commodity_tracker.debug_output_all(_connection)
    else:
        sims4.commands.output('No target for stats.show_static_commodities.', _connection)

@sims4.commands.Command('qa.stats.show_commodities', command_type=sims4.commands.CommandType.Automation)
def show_commodities_automation(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sim.commodity_tracker.debug_output_all_automation(_connection)
    sims4.commands.automation_output('CommodityInfo; Type:END', _connection)

@sims4.commands.Command('mood.show_active_mood_type')
def show_active_mood_type(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        mood_type = sim.get_mood()
        sims4.commands.output("{0}'s active mood type is {1}".format(sim, mood_type), _connection)
        return True
    sims4.commands.output('No target for mood.show_active_mood_type', _connection)
    return False

@sims4.commands.Command('stats.show_all_statistics')
def show_all_statistics(opt_sim:OptionalTargetParam=None, _connection=None):
    sim_or_obj = get_optional_target(opt_sim, _connection)
    if sim_or_obj is not None:
        show_commodities(opt_sim=opt_sim, _session_id=_connection)
        if sim_or_obj.is_sim:
            show_statistics(opt_sim=opt_sim, _session_id=_connection)

@sims4.commands.Command('stats.show_change')
def show_change(stat_type, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None and stat_type is not None:
        tracker = sim.get_tracker(stat_type)
        stat = tracker.get_statistic(stat_type)
        if stat is None:
            sims4.commands.output("Couldn't find stat on sim: {}".format(stat_type), _connection)
            return
        if not isinstance(stat, ContinuousStatistic):
            sims4.commands.output('{} is not a continuous statistic'.format(stat), _connection)
            return
        sims4.commands.output('\tDecay: {}\n\tChange: {}\n\tTotal Delta: {}'.format(stat.get_decay_rate(), stat._get_change_rate_without_decay(), stat.get_change_rate()), _connection)
    else:
        sims4.commands.output('No sim or stat type for stats.show_change.', _connection)

@sims4.commands.Command('stats.fill_commodities', command_type=sims4.commands.CommandType.Cheat)
def fill_commodities(opt_sim:OptionalTargetParam=None, visible_only:bool=True, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sims4.commands.output('Setting all motives on the current sim to full.', _connection)
        sim.commodity_tracker.set_all_commodities_to_max(visible_only=visible_only)

@sims4.commands.Command('stats.fill_commodities_household', command_type=sims4.commands.CommandType.Automation)
def fill_commodities_household(core_only:bool=True, _connection=None):
    tgt_client = services.client_manager().get(_connection)
    sims4.commands.output('Setting all motives on all household sims to full.', _connection)
    for sim_info in tgt_client.selectable_sims:
        sim_info.commodity_tracker.set_all_commodities_to_max(core_only=core_only)

@sims4.commands.Command('stats.tank_commodities')
def tank_commodities(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        sims4.commands.output('Setting all motives on the current sim to min.', _connection)
        sim.commodity_tracker.debug_set_all_to_min()

@sims4.commands.Command('stats.set_stat', 'stats.set_commodity', command_type=sims4.commands.CommandType.Automation)
def set_statisitic(stat_type, value:float=None, opt_target:OptionalTargetParam=None, _connection=None):
    target = get_optional_target(opt_target, _connection)
    if target is not None and stat_type is not None and value is not None:
        tracker = target.get_tracker(stat_type)
        tracker.set_value(stat_type, value)
    else:
        sims4.commands.output('No target for stats.set_stat.', _connection)

@sims4.commands.Command('fillmotive', command_type=sims4.commands.CommandType.Cheat)
def fill_motive(stat_type, _connection=None):
    if stat_type is not None:
        tgt_client = services.client_manager().get(_connection)
        tracker = tgt_client.active_sim.get_tracker(stat_type)
        tracker.set_value(stat_type, stat_type.max_value)
        return True
    return False

@sims4.commands.Command('stats.add_to_stat', 'stats.add_to_commodity')
def add_value_to_statistic(stat_type, value:float=None, opt_target:OptionalTargetParam=None, _connection=None):
    target = get_optional_target(opt_target, _connection)
    if target is not None and stat_type is not None and value is not None:
        tracker = target.get_tracker(stat_type)
        tracker.add_value(stat_type, value)
    else:
        sims4.commands.output('No target for stats.add_to_stat. Params: stat_name, value, optional target', _connection)

@sims4.commands.Command('stats.add_stat_to_tracker', 'stats.add_commodity_to_tracker')
def add_statistic_to_tracker(stat_type, opt_target:OptionalTargetParam=None, _connection=None):
    target = get_optional_target(opt_target, _connection)
    if target is not None and stat_type is not None:
        tracker = target.get_tracker(stat_type)
        tracker.add_statistic(stat_type)
    else:
        sims4.commands.output('No target for stats.add_stat_to_tracker. Params: stat_name, optional target', _connection)

@sims4.commands.Command('stats.remove_stat', 'stats.remove_commodity')
def remove_statistic(stat_type, opt_target:OptionalTargetParam=None, _connection=None):
    target = get_optional_target(opt_target, _connection)
    if target is not None and stat_type is not None:
        tracker = target.get_tracker(stat_type)
        tracker.remove_statistic(stat_type)
    else:
        sims4.commands.output('No target for stats.remove_stat. Params: stat_name, optional target', _connection)

@sims4.commands.Command('stats.add_static_commodity_to_tracker')
def add_static_commodity_to_tracker(static_commodity, opt_target:OptionalTargetParam=None, _connection=None):
    target = get_optional_target(opt_target, _connection)
    if target is not None:
        tracker = target.get_tracker(static_commodity)
        tracker.add_statistic(static_commodity)
    else:
        sims4.commands.output('No target for stats.add_static_commodity_to_tracker. Params: stat_name, optional target', _connection)

@sims4.commands.Command('stats.remove_static_commodity_from_tracker')
def remove_static_commodity_from_tracker(static_commodity, opt_target:OptionalTargetParam=None, _connection=None):
    target = get_optional_target(opt_target, _connection)
    if target is not None:
        tracker = target.get_tracker(static_commodity)
        tracker.remove_statistic(static_commodity)
    else:
        sims4.commands.output('No target for stats.remove_static_commodity_from_tracker. Params: stat_name, optional target', _connection)

@sims4.commands.Command('stats.set_modifier', command_type=sims4.commands.CommandType.Live)
def set_modifier(stat_type, level:float=None, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None or stat_type is None or level is None:
        sims4.commands.output('Unable to set modifier - invalid arguments.', _connection)
        return
    stat = sim.get_statistic(stat_type)
    if stat is None:
        stat = sim.add_statistic(stat_type)
    stat.add_statistic_modifier(level)
    if isinstance(stat, Skill):
        sim.sim_info.current_skill_guid = stat.guid64

@sims4.commands.Command('stats.remove_modifier', command_type=sims4.commands.CommandType.Live)
def remove_modifier(stat_type, level:float=None, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None or stat_type is None or level is None:
        sims4.commands.output('Unable to remove modifier - invalid arguments.', _connection)
        return
    stat = sim.get_statistic(stat_type)
    if stat is None:
        return
    stat.remove_statistic_modifier(level)
    if isinstance(stat, Skill) and stat._statistic_modifier <= 0 and sim.sim_info.current_skill_guid == stat.guid64:
        sim.sim_info.current_skill_guid = 0

def _set_skill_level(stat_type, level, sim, _connection):
    stat = sim.commodity_tracker.get_statistic(stat_type)
    if stat is None:
        stat = sim.commodity_tracker.add_statistic(stat_type)
        if stat is None:
            sims4.commands.output('Unable to add Skill due to entitlement restriction {}.'.format(stat_type), _connection)
            return
    if not isinstance(stat, statistics.skill.Skill):
        sims4.commands.output('Unable to set Skill level - statistic {} is a {}, not a skill.'.format(stat_type, type(stat)), _connection)
        return
    sims4.commands.output('Setting Skill {0} to level {1}'.format(stat_type, level), _connection)
    sim.commodity_tracker.set_user_value(stat_type, level)

@sims4.commands.Command('stats.set_skill_level', command_type=sims4.commands.CommandType.Automation)
def set_skill_level(stat_type, level:int=None, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None or stat_type is None or level is None:
        sims4.commands.output('Unable to set Skill level - invalid arguments.', _connection)
        return
    _set_skill_level(stat_type, level, sim, _connection)

@sims4.commands.Command('stats.clear_skill')
def clear_skill(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('Invalid Sim id: {}'.format(opt_sim), _connection)
        return
    tracker = sim.commodity_tracker
    statistics = list(tracker)
    stats_removed = []
    for stat in statistics:
        while stat.is_skill:
            stat_type = type(stat)
            stats_removed.append(stat_type)
            tracker.remove_statistic(stat_type)
    sims4.commands.output('Removed {} skills from {}'.format(len(stats_removed), sim), _connection)

@sims4.commands.Command('stats.solve_motive', command_type=sims4.commands.CommandType.Live)
def solve_motive(stat_type, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None or stat_type is None:
        sims4.commands.output('Unable to identify Sim or Motive - invalid arguments.', _connection)
        return
    stat = sim.commodity_tracker.get_statistic(stat_type)
    if stat is None:
        sims4.commands.output('Unable to motive {} on the Sim .'.format(stat_type), _connection)
        return
    if not sim.queue.can_queue_visible_interaction():
        sims4.commands.output('Interaction queue is full, cannot add anymore interactions.', _connection)
        return
    context = InteractionContext(sim, InteractionContext.SOURCE_AUTONOMY, priority.Priority.High, bucket=InteractionBucketType.DEFAULT)
    autonomy_request = autonomy.autonomy_request.AutonomyRequest(sim, autonomy_mode=autonomy.autonomy_modes.FullAutonomy, commodity_list=[stat], context=context, consider_scores_of_zero=True, posture_behavior=AutonomyPostureBehavior.IGNORE_SI_STATE, is_script_request=True, allow_opportunity_cost=False, autonomy_mode_label_override='AutoSolveMotive')
    selected_interaction = services.autonomy_service().find_best_action(autonomy_request)
    if selected_interaction is None:
        stat_str = '{}'.format(stat_type)
        commodity_interaction = CommodityTuning.BLADDER_SOLVING_FAILURE_INTERACTION
        if stat_str == "<class 'sims4.tuning.instances.motive_Energy'>":
            commodity_interaction = CommodityTuning.ENERGY_SOLVING_FAILURE_INTERACTION
        elif stat_str == "<class 'sims4.tuning.instances.motive_Fun'>":
            commodity_interaction = CommodityTuning.FUN_SOLVING_FAILURE_INTERACTION
        elif stat_str == "<class 'sims4.tuning.instances.motive_Hunger'>":
            commodity_interaction = CommodityTuning.HUNGER_SOLVING_FAILURE_INTERACTION
        elif stat_str == "<class 'sims4.tuning.instances.motive_Hygiene'>":
            commodity_interaction = CommodityTuning.HYGIENE_SOLVING_FAILURE_INTERACTION
        elif stat_str == "<class 'sims4.tuning.instances.motive_Social'>":
            commodity_interaction = CommodityTuning.SOCIAL_SOLVING_FAILURE_INTERACTION
        if not sim.queue.has_duplicate_super_affordance(commodity_interaction, sim, None):
            failure_aop = AffordanceObjectPair(commodity_interaction, None, commodity_interaction, None)
            failure_aop.test_and_execute(context)
        sims4.commands.output('Could not find a good interaction to solve {}.'.format(stat_type), _connection)
        return
    if sim.queue.has_duplicate_super_affordance(selected_interaction.affordance, sim, selected_interaction.target):
        sims4.commands.output('Duplicate Interaction in the queue.', _connection)
        return
    if not AffordanceObjectPair.execute_interaction(selected_interaction):
        sims4.commands.output('Failed to execute SI {}.'.format(selected_interaction), _connection)
        return
    sims4.commands.output('Successfully executed SI {}.'.format(selected_interaction), _connection)

def _randomize_motive(stat_type, sim, min_value, max_value):
    if min_value is None or min_value < stat_type.min_value:
        min_value = stat_type.min_value
    if max_value is None or max_value > stat_type.max_value:
        max_value = stat_type.max_value
    random_value = random.uniform(min_value, max_value)
    sim.set_stat_value(stat_type, random_value)

@sims4.commands.Command('stats.randomize_motives')
def randomize_motives(min_value:int=None, max_value:int=None, opt_sim:OptionalTargetParam=None, _connection=None):
    if opt_sim is not None:
        sim = get_optional_target(opt_sim, _connection)
        sims4.commands.output('Unable to identify Sim - invalid arguments.', _connection)
        return
        while True:
            for stat_type in SimInfo.INITIAL_COMMODITIES:
                _randomize_motive(stat_type, sim, min_value, max_value)
    else:
        for sim in services.sim_info_manager().instanced_sims_gen():
            for stat_type in SimInfo.INITIAL_COMMODITIES:
                _randomize_motive(stat_type, sim, min_value, max_value)

@sims4.commands.Command('stats.set_convergence')
def set_convergence(stat_type, convergence:float=None, opt_target:OptionalTargetParam=None, _connection=None):
    target = get_optional_target(opt_target, _connection)
    if target is not None and stat_type is not None and convergence is not None:
        tracker = target.get_tracker(stat_type)
        tracker.set_convergence(stat_type, convergence)
    else:
        sims4.commands.output('No target for stats.set_convergence.', _connection)

@sims4.commands.Command('stats.reset_convergence')
def reset_convergence(stat_type, opt_target:OptionalTargetParam=None, _connection=None):
    target = get_optional_target(opt_target, _connection)
    if target is not None and stat_type is not None:
        tracker = target.get_tracker(stat_type)
        tracker.reset_convergence(stat_type)
    else:
        sims4.commands.output('No target for stats.reset_convergence.', _connection)

def _set_stat_percent(stat, tracker, percent, _connection=0):
    stat_range = stat.max_value_tuning - stat.min_value_tuning
    stat_value = percent*stat_range + stat.min_value_tuning
    sims4.commands.output('Setting Statistic {0} to {1}'.format(stat.__name__, stat_value), _connection)
    tracker.set_value(stat, stat_value)

@sims4.commands.Command('stats.set_commodity_percent')
def set_commodity_percent(stat_type, value:float=None, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None and stat_type is not None and value is not None:
        _set_stat_percent(stat_type, sim.commodity_tracker, value, _connection=_connection)
    else:
        sims4.commands.output('Unable to set Commodity - invalid arguments.', _connection)

@sims4.commands.Command('stats.fill_all_sim_commodities_except')
def fill_all_sim_commodities_except(stat_type, opt_sim:OptionalTargetParam=None, _connection=None):
    if stat_type is not None:
        if opt_sim is not None:
            sim = get_optional_target(opt_sim, _connection)
            if sim is None:
                sims4.commands.output('No valid target for stats.enable_sim_commodities', _connection)
                return
            sim.commodity_tracker.debug_set_all_to_max_except(stat_type)
        else:
            for sim in services.sim_info_manager().instanced_sims_gen():
                sim.commodity_tracker.debug_set_all_to_max_except(stat_type)
    else:
        sims4.commands.output('Unable to set Commodity - commodity {} not found.'.format(stat_type.lower()), _connection)

with sims4.reload.protected(globals()):
    autonomy_handles = collections.defaultdict(weakref.WeakKeyDictionary)

@sims4.commands.Command('stats.enable_commodities', command_type=sims4.commands.CommandType.Cheat)
def enable_commodities(opt_sim:OptionalTargetParam=None, *stat_types, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('No valid target for stats.enable_sim_commodities', _connection)
        return
    for stat_type in stat_types:
        while sim in autonomy_handles[stat_type]:
            sim.remove_statistic_modifier(autonomy_handles[stat_type][sim])
            del autonomy_handles[stat_type][sim]

@sims4.commands.Command('stats.enable_all_commodities', command_type=sims4.commands.CommandType.Cheat)
def enable_all_commodities(opt_sim:OptionalTargetParam=None, _connection=None):
    if opt_sim is not None:
        sim = get_optional_target(opt_sim, _connection)
        if sim is None:
            sims4.commands.output('No valid target for stats.enable_sim_commodities', _connection)
            return
        for sim_handle_dictionary in autonomy_handles.values():
            while sim in sim_handle_dictionary:
                sim.remove_statistic_modifier(sim_handle_dictionary[sim])
                del sim_handle_dictionary[sim]
    else:
        for sim_handle_dictionary in autonomy_handles.values():
            for (sim, handle) in sim_handle_dictionary.items():
                sim.remove_statistic_modifier(handle)
            sim_handle_dictionary.clear()

def _disable_commodities(sim, commodities_to_lock=[]):
    for commodity in commodities_to_lock:
        if sim in autonomy_handles[commodity]:
            return
        modifier = autonomy.autonomy_modifier.AutonomyModifier(decay_modifiers={commodity: 0})
        handle = sim.add_statistic_modifier(modifier)
        autonomy_handles[commodity][sim] = handle

@sims4.commands.Command('stats.disable_commodities', command_type=sims4.commands.CommandType.Cheat)
def disable_commodities(opt_sim:OptionalTargetParam=None, *stat_types, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is None:
        sims4.commands.output('No valid target for stats.disable_commodities', _connection)
        return
    _disable_commodities(sim, stat_types)

@sims4.commands.Command('stats.disable_all_commodities', command_type=sims4.commands.CommandType.Cheat)
def disable_all_commodities(opt_sim:OptionalTargetParam=None, _connection=None):
    if opt_sim is not None:
        sim = get_optional_target(opt_sim, _connection)
        if sim is None:
            sims4.commands.output('No valid target for stats.disable_sim_commodities', _connection)
            return
        _disable_commodities(sim, SimInfo.INITIAL_COMMODITIES)
    else:
        for sim in services.sim_info_manager().instanced_sims_gen():
            _disable_commodities(sim, SimInfo.INITIAL_COMMODITIES)

@sims4.commands.Command('stats.enable_autosatisfy_curves', command_type=sims4.commands.CommandType.Cheat)
def enable_autosatisfy_curves(_connection=None):
    Commodity.use_autosatisfy_curve = True

@sims4.commands.Command('stats.disable_autosatisfy_curves', command_type=sims4.commands.CommandType.Cheat)
def disable_autosatisfy_curves(_connection=None):
    Commodity.use_autosatisfy_curve = False

