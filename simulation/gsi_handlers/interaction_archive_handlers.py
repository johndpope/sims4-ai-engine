import collections
import sys
import traceback
import weakref
from gsi_handlers.gameplay_archiver import GameplayArchiver
from sims4.gsi.schema import GsiGridSchema
from sims4.log import generate_message_with_callstack
from sims4.utils import setdefault_callable
from uid import UniqueIdGenerator
import algos
import services
import sims4.log
logger = sims4.log.Logger('GSI')
with sims4.reload.protected(globals()):
    gsi_log_id = UniqueIdGenerator()
    interaction_archive = weakref.WeakKeyDictionary()

class InteractionArchiveGSILog:
    __qualname__ = 'InteractionArchiveGSILog'

    def __init__(self):
        self.clear_log()

    def clear_log(self):
        self.status = None
        self.exit_reason = None
        self.asms_and_actors = collections.defaultdict(dict)
        self.participants = []
        self.animation_data = []
        self.constraints = []
        self.exit_reasons = []
        self.cancel_callstack = []

interaction_archive_schema = GsiGridSchema(label='Interaction Archive (SI)', sim_specific=True)
interaction_archive_schema.add_field('game_time', label='GameTime', hidden=True)
interaction_archive_schema.add_field('id', label='ID', hidden=True)
interaction_archive_schema.add_field('interaction_id', label='interaction ID', hidden=True)
interaction_archive_schema.add_field('sim_name', label='Sim Name', width=150, hidden=True)
interaction_archive_schema.add_field('interaction', label='Interaction', width=75)
interaction_archive_schema.add_field('target', label='Target', width=30)
interaction_archive_schema.add_field('initiator', label='Initiator', width=30)
interaction_archive_schema.add_field('duration', label='Duration(Sim Game Time Minutes)', hidden=True)
interaction_archive_schema.add_field('status', label='Status', width=65)
with interaction_archive_schema.add_has_many('participants', GsiGridSchema) as sub_schema:
    sub_schema.add_field('ptype', label='PType')
    sub_schema.add_field('actor', label='Actor')
with interaction_archive_schema.add_has_many('asms_and_actors', GsiGridSchema) as sub_schema:
    sub_schema.add_field('asm', label='ASM')
    sub_schema.add_field('actor', label='Actor')
    sub_schema.add_field('actor_id', label='Actor ID')
    sub_schema.add_field('actor_name', label='Name')
with interaction_archive_schema.add_has_many('animation_data', GsiGridSchema) as sub_schema:
    sub_schema.add_field('asm', label='ASM')
    sub_schema.add_field('request', label='Request')
    sub_schema.add_field('data', label='Data')
with interaction_archive_schema.add_has_many('cancel_callstack', GsiGridSchema) as sub_schema:
    sub_schema.add_field('code', label='Code', width=6)
    sub_schema.add_field('file', label='File', width=2)
    sub_schema.add_field('full_file', label='Full File', hidden=True)
    sub_schema.add_field('line', label='Line')
with interaction_archive_schema.add_has_many('exit_reasons', GsiGridSchema) as sub_schema:
    sub_schema.add_field('event_type', label='Type')
    sub_schema.add_field('event_data', label='Reason', width=2)
with interaction_archive_schema.add_has_many('constraints', GsiGridSchema) as sub_schema:
    sub_schema.add_field('sim', label='Sim')
    sub_schema.add_field('constraint', label='Constraint')
archiver = GameplayArchiver('interaction_archive', interaction_archive_schema)
interaction_archive_schema_mixer = interaction_archive_schema.copy('Interaction Archive (Mixer)')
archiver_mixer = GameplayArchiver('interaction_archive_mixer', interaction_archive_schema_mixer)

def is_archive_enabled(interaction):
    if interaction.is_super:
        return archiver.enabled
    return archiver_mixer.enabled

def get_sim_interaction_log(interaction, clear=False):
    if interaction.sim is not None:
        all_interaction_logs = setdefault_callable(interaction_archive, interaction.sim, weakref.WeakKeyDictionary)
        interaction_log = setdefault_callable(all_interaction_logs, interaction, InteractionArchiveGSILog)
        if clear:
            del all_interaction_logs[interaction]
        return interaction_log

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

def add_participant(interaction, ptype, actor):
    interaction_log = get_sim_interaction_log(interaction)
    if interaction_log is not None:
        interaction_log.participants.append({'ptype': str(ptype), 'actor': str(actor)})

def add_animation_data(interaction, asm, prev_state, next_state, data):
    interaction_log = get_sim_interaction_log(interaction)
    if interaction_log is not None:
        interaction_log.animation_data.append({'asm': str(asm), 'request': prev_state + ' -> ' + next_state, 'data': str(data)})

def add_asm_actor_data(interaction, asm, actor_name, actor):
    interaction_log = get_sim_interaction_log(interaction)
    if interaction_log is not None:
        existing_asm_data = interaction_log.asms_and_actors[asm]
        existing_asm_data[actor_name] = actor

def add_constraint(interaction, sim, constraint):
    interaction_log = get_sim_interaction_log(interaction)
    if interaction_log is not None:
        for sub_constraint in constraint:
            sim_str = str(sim)
            constraint_str = str(sub_constraint)
            while constraint_str not in [existing['constraint'] for existing in interaction_log.constraints if existing['sim'] == sim_str]:
                interaction_log.constraints.append({'sim': str(sim), 'constraint': str(sub_constraint)})

def add_exit_reason(interaction, event_type, reason):
    if not interaction.is_super:
        return
    interaction_log = get_sim_interaction_log(interaction)
    if interaction_log is not None:
        interaction_log.exit_reasons.append({'event_type': str(event_type), 'event_data': str(reason)})

def add_cancel_callstack(interaction):
    if not interaction.is_super:
        return
    interaction_log = get_sim_interaction_log(interaction)
    if interaction_log is not None:
        if interaction_log.cancel_callstack:
            return
        frame = sys._getframe(1)
        callstack_info = traceback.extract_stack(frame, limit=500)
        top_of_stack = callstack_info[-2]
        add_exit_reason(interaction, 'Cancel', top_of_stack[3])
        gsi_stack_info = interaction_log.cancel_callstack
        for stack_level in reversed(callstack_info[:-1]):
            short_file = stack_level[0].split('\\')[-1]
            gsi_stack_info.append({'full_file': stack_level[0], 'file': short_file, 'line': stack_level[1], 'code': stack_level[3]})

def _process_asm_actor_data(interaction_log):
    asms_and_actors = []
    for (asm, data) in interaction_log.asms_and_actors.items():
        for (actor_name, actor) in data.items():
            asms_and_actors.append({'asm': str(asm), 'actor_name': actor_name, 'actor': str(actor), 'actor_id': str(actor.id) if actor is not None else 'None'})
    return asms_and_actors

def _should_log_interaction(interaction):
    interaction_str = str(interaction)
    if 'SatisfyConstraint' in interaction_str or 'sim-stand' in interaction_str:
        return False
    return True

def archive_interaction(sim, interaction, status):
    if not _should_log_interaction(interaction):
        return
    interaction.log_participants_to_gsi()
    interaction_log = get_sim_interaction_log(interaction, clear=True)
    if interaction_log is None:
        return
    asms_and_actors = _process_asm_actor_data(interaction_log)
    services_time_service = services.time_service()
    if services_time_service is not None and services_time_service.sim_timeline is not None:
        now = str(services_time_service.sim_timeline.now)
    else:
        now = 'Unavailable'
    duration = '' if interaction.is_super else interaction.duration
    archive_data = {'id': gsi_log_id(), 'sim_name': sim.full_name, 'interaction_id': interaction.id, 'interaction': str(interaction.affordance.__name__), 'target': str(interaction.target), 'initiator': str(interaction.sim), 'game_time': now, 'participants': interaction_log.participants, 'status': status, 'duration': str(duration), 'asms_and_actors': asms_and_actors, 'animation_data': interaction_log.animation_data, 'exit_reasons': interaction_log.exit_reasons, 'cancel_callstack': interaction_log.cancel_callstack}
    if interaction.is_super:
        archive_data['constraints'] = interaction_log.constraints
    if interaction.is_super:
        use_archiver = archiver
    else:
        use_archiver = archiver_mixer
    use_archiver.archive(data=archive_data, object_id=sim.id)

