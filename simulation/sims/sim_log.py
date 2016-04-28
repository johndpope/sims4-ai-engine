from gsi_handlers.gameplay_archiver import GameplayArchiver
from sims4.gsi.schema import GsiGridSchema, GsiFieldVisualizers
from sims4.repr_utils import standard_brief_id_repr
import interactions
import sims4.log
import sims4.telemetry
import telemetry_helper
logger = sims4.log.Logger('InteractionLog')
TELEMETRY_GROUP_INTERACTION = 'INTR'
TELEMETRY_HOOK_SI_BEGIN = 'SIBE'
TELEMETRY_HOOK_SI_END = 'SIEN'
TELEMETRY_HOOK_MIXER_BEGIN = 'MIBE'
TELEMETRY_HOOK_MIXER_END = 'MIEN'
TELEMETRY_FIELD_INTERACTION_ID = 'idix'
TELEMETRY_FIELD_TARGET_ID = 'idtx'
TELEMETRY_FIELD_TARGET_TYPE = 'tptx'
TELEMETRY_FIELD_SOURCE = 'sorc'
TELEMETRY_FIELD_OUTCOME = 'outc'
TELEMETRY_FIELD_GROUP_ID = 'idgr'
TELEMETRY_HOOK_MAPPING = {('Process_SI', True): TELEMETRY_HOOK_SI_BEGIN, ('Running', False): TELEMETRY_HOOK_MIXER_BEGIN, ('Remove_SI', True): TELEMETRY_HOOK_SI_END, ('Done', False): TELEMETRY_HOOK_MIXER_END}
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_INTERACTION)
interactions_archive_schema = GsiGridSchema(label='Interaction Log', sim_specific=True)
interactions_archive_schema.add_field('affordance', label='Affordance')
interactions_archive_schema.add_field('phase', label='Phase')
interactions_archive_schema.add_field('target', label='Target')
interactions_archive_schema.add_field('context', label='Context')
interactions_archive_schema.add_field('progress', label='Progress')
interactions_archive_schema.add_field('message', label='Message')
archiver = GameplayArchiver('interactions', interactions_archive_schema, enable_archive_by_default=True, max_records=200)
_INTERACTION_LOG_FORMAT = '{sim:>24}, {phase:>16}, {name:>32}, {target:>32}, {progress:>8}, {context}, {msg}'
_POSTURE_LOG_FORMAT = '{sim:>24}, {phase:>16}, {name:>32}, {target:>32},         , {msg}'

def _get_csv_friendly_string(s):
    if s is not None:
        s = s.replace('"', "'")
        if ',' in s:
            s = '"{}"'.format(s)
        return s

def _get_sim_name(sim):
    if sim is not None:
        s = '{}[{}]'.format(sim.full_name, standard_brief_id_repr(sim.id))
        s = _get_csv_friendly_string(s)
        return s

def _get_object_name(obj):
    if obj is not None:
        return _get_csv_friendly_string('{}'.format(obj))

def log_affordance(phase, affordance, context, msg=None):
    logger.info(_INTERACTION_LOG_FORMAT.format(phase=phase, name='{}'.format(affordance.__name__), sim=_get_sim_name(context.sim), target='', progress='', context='', msg=_get_csv_friendly_string(msg) or ''))
    archive_data = {'affordance': affordance.__name__, 'phase': phase}
    if msg:
        archive_data['message'] = msg
    archiver.archive(data=archive_data, object_id=context.sim.id)

def log_interaction(phase, interaction, msg=None):
    if interaction.is_super:
        progress = str(interaction.pipeline_progress).split('.', 1)[-1]
    else:
        progress = ''
    source = str(interaction.context.source).split('.', 1)[-1]
    priority = str(interaction.priority).split('.', 1)[-1]
    sim_name = _get_sim_name(interaction.sim)
    interaction_name = getattr(interaction, 'name_override', interaction.affordance.__name__)
    interaction_name = '{}({})'.format(interaction_name, interaction.id)
    logger.info(_INTERACTION_LOG_FORMAT.format(phase=phase, name=interaction_name, sim=sim_name, target=_get_object_name(interaction.target), progress=progress, context='{}-{}'.format(source, priority), msg=_get_csv_friendly_string(msg) or ''))
    if archiver.enabled:
        archive_data = {'affordance': interaction_name, 'phase': phase, 'target': str(interaction.target), 'context': '{}, {}'.format(source, priority), 'progress': progress}
        if msg:
            archive_data['message'] = msg
        archiver.archive(data=archive_data, object_id=interaction.sim.id if interaction.sim is not None else 0)
    if interaction.sim is not None and interaction.sim.interaction_logging:
        log_queue_automation(interaction.sim)
    hook_tag = TELEMETRY_HOOK_MAPPING.get((phase, interaction.is_super))
    if hook_tag is not None and interaction.visible:
        with telemetry_helper.begin_hook(writer, hook_tag, sim=interaction.sim) as hook:
            hook.write_guid(TELEMETRY_FIELD_INTERACTION_ID, interaction.guid64)
            hook.write_int(TELEMETRY_FIELD_SOURCE, interaction.source)
            hook.write_int(TELEMETRY_FIELD_GROUP_ID, interaction.group_id)
            target = interaction.target
            if target is not None:
                hook.write_int(TELEMETRY_FIELD_TARGET_ID, target.id)
                hook.write_int(TELEMETRY_FIELD_TARGET_TYPE, target.definition.id)
            outcome_result = interaction.outcome_result
            while outcome_result is not None:
                hook.write_int(TELEMETRY_FIELD_OUTCOME, interaction.outcome_result)

def log_queue_automation(sim=None):
    if sim is None or sim.client is None:
        return False
    output = sims4.commands.AutomationOutput(sim.client.id)
    if sim.queue.running is None:
        output('[AreaInstanceInteraction] SimInteractionData; SimId:%d, SICount:%d, RunningId:None' % (sim.id, len(sim.si_state)))
    else:
        output('[AreaInstanceInteraction] SimInteractionData; SimId:%d, SICount:%d, RunningId:%d, RunningClass:%s' % (sim.id, len(sim.si_state), sim.queue.running.id, sim.queue.running.__class__.__name__))
    for si in sim.si_state.sis_actor_gen():
        output('[AreaInstanceInteraction] SimSuperInteractionData; Id:%d, Class:%s' % (si.id, si.__class__.__name__))

def log_posture(phase, posture, msg=None):
    logger.info(_POSTURE_LOG_FORMAT.format(phase=phase, name='{}({})'.format(posture.name, hex(posture.id)), sim=_get_sim_name(posture.sim), target=_get_object_name(posture.target), msg=_get_csv_friendly_string(msg) or ''))
    archive_data = {'affordance': posture.posture_type.__name__, 'phase': phase, 'target': str(posture.target)}
    if msg:
        archive_data['message'] = msg
    archiver.archive(data=archive_data, object_id=posture.sim.id)

interactions_outcome_archive_schema = GsiGridSchema(label='Interaction Outcome Log')
interactions_outcome_archive_schema.add_field('actor', label='Actor')
interactions_outcome_archive_schema.add_field('affordance', label='Affordance')
interactions_outcome_archive_schema.add_field('target', label='Target')
interactions_outcome_archive_schema.add_field('result', label='Result')
interactions_outcome_archive_schema.add_field('sim_buff_modifier', label='Actor Modifier')
interactions_outcome_archive_schema.add_field('chance_modification', label='Chance Modification')
interactions_outcome_archive_schema.add_field('success_chance', label='Success Chance')
interactions_outcome_archive_schema.add_field('outcome_type', label='Outcome Type')
interactions_outcome_archive_schema.add_field('message', label='Message')
outcome_archiver = GameplayArchiver('interactionOutcomes', interactions_outcome_archive_schema)

def log_interaction_outcome(interaction, outcome_type, success_chance=None, msg=None):
    try:
        sim = interaction.sim
        sim_name = _get_sim_name(sim)
        if interaction.target_type & interactions.TargetType.TARGET:
            target = interaction.target
        else:
            target = sim
        archive_data = {'actor': sim_name, 'affordance': type(interaction).__name__, 'target': _get_object_name(target), 'result': interaction.outcome_result.__str__(), 'skill_multiplier': interaction.get_skill_multiplier(interaction.success_chance_multipliers, sim), 'outcome_type': outcome_type}
        if success_chance is not None:
            archive_data['success_chance'] = success_chance
            archive_data['sim_buff_modifier'] = sim.get_actor_success_modifier(interaction.affordance) if sim is not None else 0
            archive_data['chance_modification'] = sim.get_success_chance_modifier() if sim is not None else 0
        if msg:
            archive_data['message'] = msg
        outcome_archiver.archive(data=archive_data, object_id=sim.id if sim is not None else 0)
    except:
        logger.exception('Exception while attempting to log an interaction outcome:')

