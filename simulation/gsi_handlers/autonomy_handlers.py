from gsi_handlers.gameplay_archiver import GameplayArchiver
from sims4.gsi.dispatcher import GsiHandler
from sims4.gsi.schema import GsiFieldVisualizers, GsiGridSchema
import autonomy.autonomy_modes
import services
autonomy_archive_schema = GsiGridSchema(label='Autonomy Log', sim_specific=True)
autonomy_archive_schema.add_field('sim_name', label='Sim Name', width=2)
autonomy_archive_schema.add_field('result', label='Result', width=5)
autonomy_archive_schema.add_field('type', label='Type', width=2)
with autonomy_archive_schema.add_has_many('Affordances', GsiGridSchema) as sub_schema:
    sub_schema.add_field('affordance', label='Affordance', width=3)
    sub_schema.add_field('target', label='Target', width=2)
    sub_schema.add_field('affordance_status', label='Status', width=5)
    sub_schema.add_field('autonomy_stage', label='Stage', width=2)
    sub_schema.add_field('affordance_score', label='Score', type=GsiFieldVisualizers.FLOAT, width=1)
    sub_schema.add_field('multitask_percentage', label='Multitask %', type=GsiFieldVisualizers.FLOAT, width=1)
    sub_schema.add_field('scoring_priority', label='Scoring Priority', width=2)
    sub_schema.add_field('affordance_relevant_desires', label='Relevant Desires', width=4)
    sub_schema.add_field('affordance_details', label='Details', width=6)
with autonomy_archive_schema.add_has_many('Probability', GsiGridSchema) as sub_schema:
    sub_schema.add_field('affordance', label='Affordance', width=3)
    sub_schema.add_field('target', label='Target', width=2)
    sub_schema.add_field('affordance_score', label='Score', type=GsiFieldVisualizers.FLOAT, width=1)
    sub_schema.add_field('multitask_roll', label='Multitask Roll', type=GsiFieldVisualizers.FLOAT, width=1)
    sub_schema.add_field('probability', label='Probability', type=GsiFieldVisualizers.FLOAT, width=1)
    sub_schema.add_field('probability_type', label='Probability Type', width=4)
with autonomy_archive_schema.add_has_many('Objects', GsiGridSchema) as sub_schema:
    sub_schema.add_field('object', label='Object', width=2)
    sub_schema.add_field('object_relevant_desires', label='Relevant Desires', width=4)
    sub_schema.add_field('object_status', label='Status', width=5)
with autonomy_archive_schema.add_has_many('Commodities', GsiGridSchema) as sub_schema:
    sub_schema.add_field('commodity', label='Commodity', width=3)
    sub_schema.add_field('commodity_weight', label='Weight', type=GsiFieldVisualizers.FLOAT, width=1)
    sub_schema.add_field('commodity_value', label='Value', type=GsiFieldVisualizers.FLOAT, width=1)
    sub_schema.add_field('commodity_desire', label='Autonomous Desire', type=GsiFieldVisualizers.FLOAT, width=1)
    sub_schema.add_field('commodity_multiplier', label='Multiplier', type=GsiFieldVisualizers.FLOAT, width=1)
with autonomy_archive_schema.add_has_many('MixerProvider', GsiGridSchema) as sub_schema:
    sub_schema.add_field('buff_or_affordance', label='Mixer Provider', width=3)
    sub_schema.add_field('target', label='Target', width=2)
    sub_schema.add_field('selected', label='Selected', width=2)
    sub_schema.add_field('mixer_provider_score', label='Score', type=GsiFieldVisualizers.FLOAT, width=1)
    sub_schema.add_field('mixer_provider_details', label='Details', width=2)
with autonomy_archive_schema.add_has_many('Mixers', GsiGridSchema) as sub_schema:
    sub_schema.add_field('mixer_provider', 'Provider')
    sub_schema.add_field('affordance', label='Aop', width=3)
    sub_schema.add_field('target', label='Target', width=2)
    sub_schema.add_field('sub_weight', label='Score', type=GsiFieldVisualizers.FLOAT, width=1)
    sub_schema.add_field('sub_details', label='Details', width=2)
with autonomy_archive_schema.add_has_many('MixerCachingInfo', GsiGridSchema) as sub_schema:
    sub_schema.add_field('mixer_caching_details', 'Provider')
with autonomy_archive_schema.add_has_many('SIState', GsiGridSchema) as sub_schema:
    sub_schema.add_field('interactionId', label='ID', type=GsiFieldVisualizers.INT, width=1, unique_field=True)
    sub_schema.add_field('interactionName', label='Name', width=6)
    sub_schema.add_field('target', label='Target', width=3)
    sub_schema.add_field('bucket_name', label='State', width=2)
    sub_schema.add_field('group_id', label='Group Id', width=1)
    sub_schema.add_field('running', label='Running', width=1)
    sub_schema.add_field('priority', label='Priority', width=1)
    sub_schema.add_field('isFinishing', label='Finishing', width=1)
    sub_schema.add_field('isSuper', label='Is Super', width=1)
    sub_schema.add_field('isExpressed', label='Is Expressed', width=1, hidden=True)
    sub_schema.add_field('allowAuto', label='Allow Auto', width=1, hidden=True)
    sub_schema.add_field('allowUser', label='Allow User', width=1, hidden=True)
    sub_schema.add_field('visible', label='Visible', width=1)
    sub_schema.add_field('is_guaranteed', label='Guaranteed', width=1)
archiver = GameplayArchiver('autonomy', autonomy_archive_schema, custom_enable_fn=autonomy.autonomy_modes.enable_gsi_logging)

def archive_autonomy_data(sim, result, mode_name, gsi_data):
    archive_data = {'sim_name': sim.full_name, 'result': str(result), 'type': mode_name}
    if gsi_data is not None:
        archive_data['Affordances'] = [{'affordance': interaction_result.interaction.affordance.__name__, 'target': str(interaction_result.interaction.target), 'autonomy_stage': interaction_result.stage if not interaction_result else autonomy.autonomy_modes.AutonomyMode._AutonomyStageLabel.AFTER_SCORING, 'affordance_score': float(interaction_result.score) if interaction_result else None, 'multitask_percentage': float(interaction_result.multitask_percentage) if interaction_result else None, 'scoring_priority': str(interaction_result.interaction.affordance.scoring_priority)[str(interaction_result.interaction.affordance.scoring_priority).index('.') + 1:] if interaction_result and hasattr(interaction_result.interaction.affordance, 'scoring_priority') else None, 'affordance_relevant_desires': ', '.join([desire.__name__ for desire in interaction_result.relevant_desires]), 'affordance_status': 'Scored' if interaction_result else interaction_result.reason, 'affordance_details': interaction_result.score.details if interaction_result else ''} for interaction_result in gsi_data['Affordances']]
        archive_data['Probability'] = [{'affordance': '{} {}'.format(interaction_result.interaction_prefix, interaction_result.interaction.affordance.__name__), 'target': str(interaction_result.interaction.target), 'affordance_score': float(interaction_result.score) if interaction_result else None, 'multitask_roll': float(interaction_result.multitask_roll) if interaction_result else None, 'probability': float(interaction_result.probability) if interaction_result else None, 'probability_type': interaction_result.probability_type if interaction_result else None} for interaction_result in gsi_data['Probability']]
        archive_data['Objects'] = [{'object': str(object_result.obj), 'object_relevant_desires': ', '.join([desire.__name__ for desire in object_result.relevant_desires]), 'object_status': 'Scored' if object_result else object_result.reason} for object_result in gsi_data['Objects']]
        archive_data['Commodities'] = [{'commodity': commodity_score.stat_type.__name__, 'commodity_weight': float(commodity_score), 'commodity_value': commodity_score.stat_value, 'commodity_desire': commodity_score.autonomous_desire, 'commodity_multiplier': commodity_score.score_multiplier} for commodity_score in gsi_data['Commodities']]
        mixer_provider_entry = []
        selected_mixer_provider = gsi_data.get('selected_mixer_provider', '')
        for (mixer_provider_name, target_string, score, details) in gsi_data['MixerProvider']:
            entry = {'buff_or_affordance': mixer_provider_name, 'target': target_string, 'selected': 'x' if selected_mixer_provider == mixer_provider_name else '', 'mixer_provider_score': score, 'mixer_provider_details': details}
            mixer_provider_entry.append(entry)
        archive_data['MixerProvider'] = mixer_provider_entry
        archive_data['Mixers'] = [{'mixer_provider': mixer_provider, 'affordance': affordance_name, 'target': target_name, 'sub_weight': weight, 'sub_details': details} for (weight, mixer_provider, affordance_name, target_name, details) in gsi_data['Mixers']]
        caching_info = gsi_data.get('caching_info', None)
        caching_info_entry = []
        if caching_info:
            for info in caching_info:
                caching_info_entry.append({'mixer_caching_details': info})
        archive_data['MixerCachingInfo'] = caching_info_entry
        si_state_info = []
        if sim is not None:
            for bucket in list(sim.queue._buckets):
                for interaction in bucket:
                    si_state_info.append(_create_si_state_entry(interaction, type(bucket).__name__))
            for interaction in list(sim.si_state):
                si_state_info.append(_create_si_state_entry(interaction, 'SI_State'))
        archive_data['SIState'] = si_state_info
    archiver.archive(data=archive_data, object_id=sim.id)

def _create_si_state_entry(interaction, bucket_name):

    def bool_to_str(value):
        if value:
            return 'X'
        return ''

    if hasattr(interaction, 'name_override'):
        interaction_name = interaction.name_override
    else:
        interaction_name = type(interaction).__name__
    entry = {'interactionId': interaction.id, 'interactionName': interaction_name, 'target': str(interaction.target), 'bucket_name': bucket_name, 'group_id': interaction.group_id, 'running': bool_to_str(interaction.running), 'priority': interaction.priority.name, 'isSuper': bool_to_str(interaction.is_super), 'isFinishing': bool_to_str(interaction.is_finishing), 'allowAuto': bool_to_str(interaction.allow_autonomous), 'allowUser': bool_to_str(interaction.allow_user_directed), 'visible': bool_to_str(interaction.visible), 'is_guaranteed': bool_to_str(interaction.is_guaranteed())}
    return entry

EMPTY_ARCHIVE = {'Affordances': [], 'Probability': [], 'Objects': [], 'Commodities': [], 'MixerProvider': [], 'Mixers': [], 'caching_info': []}
autonomy_queue_schema = GsiGridSchema(label='Autonomy Queue')
autonomy_queue_schema.add_field('position', label='#')
autonomy_queue_schema.add_field('sim', label='Sim')

@GsiHandler('autonomy_queue_view', autonomy_queue_schema)
def generate_autonomy_queue_view_data(sim_id:int=None):
    autonomy_service = services.autonomy_service()
    autonomy_queue_data = []
    if autonomy_service._active_sim is not None:
        entry = {'position': '0', 'sim': str(autonomy_service._active_sim)}
        autonomy_queue_data.append(entry)
    for (index, autonomy_request) in enumerate(autonomy_service.queue):
        entry = {'position': str(index + 1), 'sim': str(autonomy_request.sim)}
        autonomy_queue_data.append(entry)
    return autonomy_queue_data

