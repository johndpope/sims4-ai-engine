import re
import weakref
from gsi_handlers.gameplay_archiver import GameplayArchiver
from sims4.gsi.schema import GsiGridSchema, GsiFieldVisualizers
from uid import UniqueIdGenerator
import algos
import postures
import sims4.log
from sims4.utils import setdefault_callable
logger = sims4.log.Logger('GSI')
with sims4.reload.protected(globals()):
    gsi_path_id = UniqueIdGenerator()
    posture_transition_logs = weakref.WeakKeyDictionary()
    current_transition_interactions = weakref.WeakKeyDictionary()

class PostureTransitionGSILog:
    __qualname__ = 'PostureTransitionGSILog'

    def __init__(self):
        self.clear_log()

    def clear_log(self):
        self.current_pass = 0
        self.path = None
        self.path_success = False
        self.path_cost = 0
        self.dest_spec = None
        self.all_goals = []
        self.path_progress = 0
        self.path_cost_log = []
        self.path_goal_costs = []
        self.possible_constraints = []
        self.possible_path_destinations = {}
        self.all_handles = []
        self.sources_and_destinations = []
        self.transition_templates = []
        self.cur_posture_interaction = None
        self.all_possible_paths = []
        self.all_goal_costs = []

trans_path_archive_schema = GsiGridSchema(label='Transition Log', sim_specific=True)
trans_path_archive_schema.add_field('id', label='ID', hidden=True)
trans_path_archive_schema.add_field('sim_name', label='Sim Name', width=150, hidden=True)
trans_path_archive_schema.add_field('interaction', label='Interaction', width=150)
trans_path_archive_schema.add_field('path_success', label='Success', width=65)
trans_path_archive_schema.add_field('path_progress', label='Progress', width=65)
trans_path_archive_schema.add_field('path', label='Chosen Path', width=450)
trans_path_archive_schema.add_field('destSpec', label='Dest Spec', width=350)
trans_path_archive_schema.add_field('pathCost', label='Cost')
trans_path_archive_schema.add_field('posture_state', label='Posture State', hidden=True)
with trans_path_archive_schema.add_has_many('all_constraints', GsiGridSchema) as sub_schema:
    sub_schema.add_field('build_pass', label='Pass', width=0.15)
    sub_schema.add_field('cur_constraint', label='Constraint')
    sub_schema.add_field('constraint_type', label='Type', width=0.15)
    sub_schema.add_field('constraint_geometry', label='Geometry')
with trans_path_archive_schema.add_has_many('templates', GsiGridSchema) as sub_schema:
    sub_schema.add_field('build_pass', label='Pass', width=0.15)
    sub_schema.add_field('spec', label='Spec')
    sub_schema.add_field('var_maps', label='Var Maps')
with trans_path_archive_schema.add_has_many('sources_and_dests', GsiGridSchema) as sub_schema:
    sub_schema.add_field('build_pass', label='Pass', width=0.15)
    sub_schema.add_field('dest_spec', label='Dest Spec')
    sub_schema.add_field('var_map', label='Var Map')
    sub_schema.add_field('type', label='Type', width=0.5)
    sub_schema.add_field('node', label='Node')
with trans_path_archive_schema.add_has_many('all_handles', GsiGridSchema) as sub_schema:
    sub_schema.add_field('build_pass', label='Pass', width=0.15)
    sub_schema.add_field('handle', label='Handle', width=4)
    sub_schema.add_field('polygons', label='Polygons', width=4)
    sub_schema.add_field('path', label='Path', width=4)
    sub_schema.add_field('type', label='Type')
    sub_schema.add_field('valid', label='Valid')
with trans_path_archive_schema.add_has_many('path_costs', GsiGridSchema) as sub_schema:
    sub_schema.add_field('build_pass', label='Pass', width=0.15)
    sub_schema.add_field('currNode', label='Current Node')
    sub_schema.add_field('nextNode', label='Next Node')
    sub_schema.add_field('transCost', label='Cost')
with trans_path_archive_schema.add_has_many('goal_costs', GsiGridSchema) as sub_schema:
    sub_schema.add_field('build_pass', label='Pass', width=0.15)
    sub_schema.add_field('currNode', label='Current Node', width=4)
    sub_schema.add_field('transCost', label='Cost', type=GsiFieldVisualizers.FLOAT)
    sub_schema.add_field('info', label='Cost Info', width=4)
with trans_path_archive_schema.add_has_many('all_possible_paths', GsiGridSchema) as sub_schema:
    sub_schema.add_field('build_pass', label='Pass', width=0.15)
    sub_schema.add_field('path', label='Path', width=10)
    sub_schema.add_field('type', label='Type')
    sub_schema.add_field('cost', label='Cost', type=GsiFieldVisualizers.FLOAT)
    sub_schema.add_field('constraint', label='Constraint')
with trans_path_archive_schema.add_has_many('all_goal_costs', GsiGridSchema) as sub_schema:
    sub_schema.add_field('build_pass', label='Pass', width=0.15)
    sub_schema.add_field('path', label='Path', width=10)
    sub_schema.add_field('location', label='Loc', width=6)
    sub_schema.add_field('type', label='Type')
    sub_schema.add_field('cost', label='Cost', type=GsiFieldVisualizers.FLOAT)
    sub_schema.add_field('source_dest_id', label='Set Id', type=GsiFieldVisualizers.INT)
archiver = GameplayArchiver('transition_path', trans_path_archive_schema)

def get_sim_transition_log(sim, interaction=None):
    all_transition_logs = setdefault_callable(posture_transition_logs, sim, weakref.WeakKeyDictionary)
    if interaction is None:
        interaction_ref = current_transition_interactions.get(sim, None)
        if interaction_ref is None:
            return
        interaction = interaction_ref()
        if interaction is None:
            del current_transition_interactions[sim]
            return
    posture_log = setdefault_callable(all_transition_logs, interaction, PostureTransitionGSILog)
    return posture_log

def increment_build_pass(sim, interaction):
    transition_log = get_sim_transition_log(sim, interaction=interaction)
    if transition_log is None:
        return

def format_interaction_for_transition_log(interaction):
    return '{} (id:{})'.format(type(interaction).__name__, interaction.id)

def format_path_string(path_spec):
    if path_spec is None:
        return ''
    if isinstance(path_spec, algos.Path):
        return ' -> '.join(str(node) for node in path_spec)
    if path_spec.path:
        return ' -> '.join(str(node.posture_spec) + (' (Route)' if node.path else '') for node in path_spec._path)
    return ''

def add_possible_constraints(sim, constraints, type_str):
    transition_log = get_sim_transition_log(sim)
    if transition_log is None:
        return
    geometry = [str(constraint.geometry) for constraint in constraints]
    for constraint in constraints:
        transition_log.possible_constraints.append({'build_pass': transition_log.current_pass, 'cur_constraint': str(constraint), 'constraint_type': type_str, 'constraint_geometry': ','.join(geometry)})

def add_source_or_dest(sim, dest_spec, var_map, node_type, node):
    transition_log = get_sim_transition_log(sim)
    if transition_log is None:
        return
    transition_log.sources_and_destinations.append({'build_pass': transition_log.current_pass, 'dest_spec': str(dest_spec), 'var_map': str(var_map), 'type': node_type, 'node': str(node)})

def add_templates_to_gsi(sim, templates):
    transition_log = get_sim_transition_log(sim)
    if transition_log is None:
        return
    for (spec, spec_vars, _) in templates:
        spec_var_strs = []
        for var_map in spec_vars:
            spec_var_strs.append(str(var_map))
        transition_log.transition_templates.append({'build_pass': transition_log.current_pass, 'spec': str(spec), 'var_maps': '\n'.join(spec_var_strs)})

def set_current_posture_interaction(sim, interaction):
    current_transition_interactions[sim] = weakref.ref(interaction)
    transition_log = get_sim_transition_log(sim)
    transition_log.cur_posture_interaction = format_interaction_for_transition_log(interaction)

def log_path_cost(sim, curr_node, next_node, cost_str_list):
    transition_log = get_sim_transition_log(sim)
    if transition_log is None:
        return
    transition_log.path_cost_log.append({'build_pass': transition_log.current_pass, 'currNode': str(curr_node), 'nextNode': str(next_node), 'transCost': ', '.join(cost_str_list)})

def log_goal_cost(sim, curr_node, cost, cost_str_list):
    transition_log = get_sim_transition_log(sim)
    if transition_log is None:
        return
    transition_log.path_goal_costs.append({'build_pass': transition_log.current_pass, 'currNode': str(curr_node), 'transCost': cost, 'info': ', '.join(cost_str_list)})

def mark_selected_destination(sim, path_index, goal_index):
    transition_log = get_sim_transition_log(sim)
    if transition_log is None:
        return
    transition_log.possible_path_destinations[path_index][goal_index]['handle'] += ' (Selected)'

def log_transition_handle(sim, handle, geometry, path, valid, type_str):
    transition_log = get_sim_transition_log(sim)
    if transition_log is None:
        return
    entry = {'build_pass': transition_log.current_pass, 'handle': str(handle), 'polygons': str(geometry), 'path': str(path), 'type': str(type_str).replace('PathType.', ''), 'valid': valid}
    transition_log.all_handles.append(entry)

def log_possible_segmented_paths(sim, all_possible_segmented_paths):
    transition_log = get_sim_transition_log(sim)
    if transition_log is None:
        return
    all_scored_paths = transition_log.all_possible_paths

    def add_path_to_log(path, constraint, path_type):
        if path:
            all_scored_paths.append({'build_pass': transition_log.current_pass, 'path': ' -> '.join(map(str, path)), 'type': path_type, 'cost': path.cost, 'constraint': str(constraint)})

    for segmented_path in all_possible_segmented_paths:
        while segmented_path:
            add_path_to_log(getattr(segmented_path, '_path_left', None), segmented_path.constraint, 'Left')
            add_path_to_log(getattr(segmented_path, '_path_middle', None), segmented_path.constraint, 'Middle')
            add_path_to_log(getattr(segmented_path, '_path_right', None), segmented_path.constraint, 'Right')

def log_possible_goal(sim, path_spec, goal, cost, type_str, source_dest_id):
    transition_log = get_sim_transition_log(sim)
    if transition_log is None:
        return
    entry = {'build_pass': transition_log.current_pass, 'path': format_path_string(path_spec), 'location': str(goal.location.position), 'type': type_str, 'cost': cost, 'source_dest_id': source_dest_id}
    transition_log.all_goal_costs.append(entry)

def archive_path(sim, best_path_spec, path_success, path_progress, interaction=None):
    transition_log = get_sim_transition_log(sim, interaction=interaction)
    if transition_log is None:
        return
    if best_path_spec is not None:
        transition_log.path = format_path_string(best_path_spec)
        transition_log.path_cost = best_path_spec.cost
        transition_log.dest_spec = best_path_spec.destination_spec
    elif path_progress < postures.posture_graph.TransitionSequenceStage.COMPLETE:
        transition_log.path = '---'
        transition_log.dest_spec = '---'
    else:
        transition_log.path = 'EMPTY_PATH_SPEC'
    transition_log.path_success = path_success
    for goal_list in transition_log.possible_path_destinations.values():
        transition_log.all_goals.extend(goal_list)
    transition_log.path_progress = path_progress
    log_path_data_to_gsi(sim)

def archive_current_spec_valid(sim, interaction):
    transition_log = get_sim_transition_log(sim, interaction=interaction)
    if transition_log is None:
        return
    transition_log.path = 'Current Spec Valid'
    transition_log.path_success = True
    log_path_data_to_gsi(sim, interaction=interaction)

def log_path_data_to_gsi(sim, interaction=None):
    transition_log = get_sim_transition_log(sim, interaction=interaction)
    if transition_log is None:
        return
    archive_data = {'id': gsi_path_id(), 'sim_name': sim.full_name, 'interaction': transition_log.cur_posture_interaction, 'path': transition_log.path, 'path_success': transition_log.path_success, 'path_progress': int(transition_log.path_progress), 'pathCost': transition_log.path_cost, 'destSpec': str(transition_log.dest_spec), 'path_costs': transition_log.path_cost_log, 'goal_costs': transition_log.path_goal_costs, 'all_handles': transition_log.all_handles, 'all_possible_paths': transition_log.all_possible_paths, 'connected_destinations': transition_log.all_goals, 'all_constraints': transition_log.possible_constraints, 'sources_and_dests': transition_log.sources_and_destinations, 'templates': transition_log.transition_templates, 'posture_state': str(sim.posture_state), 'all_goal_costs': transition_log.all_goal_costs}
    archiver.archive(data=archive_data, object_id=sim.id)
    if sim.transition_path_logging:
        log_transition_path_automation(sim, archive_data)

def archive_canceled_transition(sim, interaction, finishing_type, test_result):
    transition_log = get_sim_transition_log(sim, interaction=interaction)
    if transition_log is None:
        return
    transition_log.path = 'CANCELED: Finishing Type: {}, Result: {}'.format(finishing_type, test_result)
    transition_log.path_success = False
    transition_log.path_progress = int(postures.posture_graph.TransitionSequenceStage.COMPLETE) + 1
    transition_log.cur_posture_interaction = format_interaction_for_transition_log(interaction)
    log_path_data_to_gsi(sim, interaction=interaction)

def archive_derailed_transition(sim, interaction, reason, test_result):
    transition_log = get_sim_transition_log(sim, interaction=interaction)
    if transition_log is None:
        return
    transition_log.path = 'DERAILED: {} Result: {}'.format(reason, test_result)
    transition_log.path_progress = int(postures.posture_graph.TransitionSequenceStage.COMPLETE) + 1
    transition_log.cur_posture_interaction = format_interaction_for_transition_log(interaction)
    log_path_data_to_gsi(sim, interaction=interaction)

def log_transition_path_automation(sim=None, data=None):
    if sim is None or (sim.client is None or data is None) or data['interaction'] is None:
        return False
    pathStr = re.split(':0x....,|:0x......]', data['path'])
    pathStr = ''.join(pathStr)
    pathStr = re.split(':0x....$|:0x......]$', pathStr)
    pathStr = ''.join(pathStr)
    destStr = re.split(':0x....,|:0x......]', data['destSpec'])
    destStr = ''.join(destStr)
    destStr = re.split(':0x....$|:0x......]$', destStr)
    destStr = ''.join(destStr)
    output = sims4.commands.AutomationOutput(sim.client.id)
    output('[AreaInstanceTransitionPath] SimTransPathData;         Interaction:%s,         Path:%s,         PathCost:%s,         DestSpec:%s' % (data['interaction'].split()[0], pathStr, data['pathCost'], destStr.replace(',', '')))

