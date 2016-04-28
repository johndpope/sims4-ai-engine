from autonomy.autonomy_modifier import AutonomyModifier
from buffs import GameEffectType
from date_and_time import TimeSpan
from gsi_handlers.gameplay_archiver import GameplayArchiver
from objects import ALL_HIDDEN_REASONS
from server_commands.argument_helpers import get_tunable_instance
from sims4.gsi.dispatcher import GsiHandler, add_cheat_schema
from sims4.gsi.schema import GsiBarChartSchema, GsiFieldVisualizers, GsiGridSchema, GSIGlobalCheatSchema, GsiLineGraphSchema
from sims4.resources import Types
import alarms
import date_and_time
import services
import sims.aging
import sims4
import statistics.commodity
import statistics.statistic
global_sim_cheats_schema = GSIGlobalCheatSchema()
global_sim_cheats_schema.add_cheat('sims.fill_all_commodities', label='Make All Sims Happy')
global_sim_cheats_schema.add_cheat('sims.reset_all', label='Reset All Sims')
add_cheat_schema('global_sim_cheats', global_sim_cheats_schema)
logger = sims4.log.Logger('GSI')

def _get_sim_instance_by_id(sim_id):
    sim_info_manager = services.sim_info_manager()
    if sim_info_manager is not None:
        for sim_info in sim_info_manager.objects:
            while sim_id == sim_info.sim_id:
                return sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)

def _get_sim_info_by_id(sim_id):
    sim_info_manager = services.sim_info_manager()
    sim_info = None
    if sim_info_manager is not None:
        sim_info = sim_info_manager.get(sim_id)
    return sim_info

static_commodity = GsiGridSchema(label='Statistics/Static Commodities', sim_specific=True)
static_commodity.add_field('name', label='Name')

@GsiHandler('static_commodity_view', static_commodity)
def generate_sim_static_commodity_view_data(sim_id:int=None):
    stat_data = []
    cur_sim_info = _get_sim_info_by_id(sim_id)
    if cur_sim_info is not None:
        for stat in list(cur_sim_info.static_commodity_tracker):
            stat_data.append({'name': type(stat).__name__})
    return stat_data

def generate_all_commodities():
    return [cls.__name__ for cls in services.get_instance_manager(Types.STATISTIC).types.values() if issubclass(cls, statistics.commodity.Commodity)]

commodity_view_schema = GsiBarChartSchema(label='Statistics/Commodities', sim_specific=True)
commodity_view_schema.add_field('simId', hidden=True)
commodity_view_schema.add_field('commodityName', axis=GsiBarChartSchema.Axis.X)
commodity_view_schema.add_field('commodityValue', type=GsiFieldVisualizers.FLOAT)
commodity_view_schema.add_field('percentFull', axis=GsiBarChartSchema.Axis.Y, type=GsiFieldVisualizers.FLOAT, is_percent=True)
with commodity_view_schema.add_cheat('stats.set_commodity', label='Set {commodityName}') as cheat:
    cheat.add_token_param('commodityName')
    cheat.add_input_param(label='Value', default='100')
    cheat.add_token_param('simId')
with commodity_view_schema.add_cheat('stats.fill_all_sim_commodities_except', label='Fill all except {commodityName}') as cheat:
    cheat.add_token_param('commodityName')
    cheat.add_token_param('simId')
with commodity_view_schema.add_cheat('stats.set_commodity_percent', label='Set {commodityName} to max', dbl_click=True) as cheat:
    cheat.add_token_param('commodityName')
    cheat.add_static_param(1)
    cheat.add_token_param('simId')

def add_commodity_cheats(manager):
    with commodity_view_schema.add_view_cheat('stats.set_stat', label='Add Commodity') as cheat:
        cheat.add_token_param('commodity_string', dynamic_token_fn=generate_all_commodities)
        cheat.add_static_param('1')
        cheat.add_token_param('simId')

services.get_instance_manager(Types.STATISTIC).add_on_load_complete(add_commodity_cheats)

@GsiHandler('commodity_view', commodity_view_schema)
def generate_sim_commodity_view_data(sim_id:int=None):
    commodity_data = []
    cur_sim_info = _get_sim_info_by_id(sim_id)
    if cur_sim_info is not None:
        for statistic in list(cur_sim_info.commodity_tracker):
            if statistic.is_skill:
                pass
            commodity_data.append({'simId': str(sim_id), 'commodityName': type(statistic).__name__, 'commodityValue': statistic.get_value(), 'percentFull': statistic.get_value()/statistic.max_value*100 if statistic.max_value != 0 else 0})
    return sorted(commodity_data, key=lambda entry: entry['commodityName'])

def generate_all_stats():
    return [cls.__name__ for cls in services.get_instance_manager(Types.STATISTIC).types.values() if issubclass(cls, statistics.statistic.Statistic)]

statistic_schema = GsiBarChartSchema(label='Statistics/Statistic', sim_specific=True, x_min=0, x_max=100)
statistic_schema.add_field('simId', hidden=True)
statistic_schema.add_field('statName', axis=GsiBarChartSchema.Axis.X)
statistic_schema.add_field('statValue', type=GsiFieldVisualizers.FLOAT)
statistic_schema.add_field('percentFull', axis=GsiBarChartSchema.Axis.Y, type=GsiFieldVisualizers.FLOAT, is_percent=True)
with statistic_schema.add_cheat('stats.set_stat', label='Set {statName}') as cheat:
    cheat.add_token_param('statName')
    cheat.add_input_param(label='Value', default='100')
    cheat.add_token_param('simId')
with statistic_schema.add_cheat('stats.set_stat', label='Add Statistic') as cheat:
    cheat.add_input_param(label='Statistic')
    cheat.add_input_param(label='Value', default='100')
    cheat.add_token_param('simId')

def add_stat_cheats(manager):
    with statistic_schema.add_view_cheat('stats.set_stat', label='Add Statistic') as cheat:
        cheat.add_token_param('stat_string', dynamic_token_fn=generate_all_stats)
        cheat.add_static_param('1')
        cheat.add_token_param('simId')

services.get_instance_manager(Types.STATISTIC).add_on_load_complete(add_stat_cheats)

@GsiHandler('statistic_view', statistic_schema)
def generate_sim_statistic_view_data(sim_id:int=None):
    statistic_data = []
    cur_sim_info = _get_sim_info_by_id(sim_id)
    if cur_sim_info is not None:
        for stat in list(cur_sim_info.statistic_tracker):
            statistic_data.append({'simId': str(sim_id), 'statName': type(stat).__name__, 'statValue': stat.get_value(), 'percentFull': (stat.get_value() - stat.min_value)/(stat.max_value - stat.min_value)*100})
        for stat in list(cur_sim_info.skills_gen()):
            statistic_data.append({'simId': str(sim_id), 'statName': type(stat).__name__, 'statValue': stat.get_value(), 'percentFull': stat.get_value()/stat.max_value*100})
    return sorted(statistic_data, key=lambda entry: entry['statName'])

skill_schema = GsiGridSchema(label='Statistics/Skill', sim_specific=True)
skill_schema.add_field('sim_id', label='Sim ID', hidden=True)
skill_schema.add_field('skill_guid', label='Skill ID', hidden=True, unique_field=True)
skill_schema.add_field('skill_name', label='Name')
skill_schema.add_field('skill_value', label='Value Points', type=GsiFieldVisualizers.INT)
skill_schema.add_field('skill_level', label='Level', type=GsiFieldVisualizers.INT)
skill_schema.add_field('skill_effective_level', label='Effective Level', type=GsiFieldVisualizers.INT)
with skill_schema.add_has_many('effective_modifiers', GsiGridSchema, label='Effective Level Modifier') as sub_schema:
    sub_schema.add_field('buff', label='Buff Name')
    sub_schema.add_field('modifier_value', label='Modifier Value', type=GsiFieldVisualizers.INT)

@GsiHandler('skill_view', skill_schema)
def generate_sim_skill_view_data(sim_id:int=None):
    skill_data = []
    cur_sim_info = _get_sim_info_by_id(sim_id)
    if cur_sim_info is not None:
        for stat in list(cur_sim_info.skills_gen()):
            skill_level = stat.get_user_value()
            effective_skill_level = cur_sim_info.get_effective_skill_level(stat)
            entry = {'simId': str(sim_id), 'skill_guid': str(stat.guid64), 'skill_name': type(stat).__name__, 'skill_value': stat.get_value(), 'skill_level': skill_level, 'skill_effective_level': effective_skill_level}
            entry['effective_modifiers'] = []
            if effective_skill_level != skill_level:
                for (buff_type, modifier) in cur_sim_info.effective_skill_modified_buff_gen(stat):
                    buff_entry = {'buff': buff_type.__class__.__name__, 'modifier_value': modifier}
                    entry['effective_modifiers'].append(buff_entry)
            skill_data.append(entry)
    return skill_data

commodity_data_schema = GsiGridSchema(label='Statistics/Commodity Data', sim_specific=True)
commodity_data_schema.add_field('stat_guid', label='Stat GUID', unique_field=True, width=0.5)
commodity_data_schema.add_field('stat_name', label='Name', width=2)
commodity_data_schema.add_field('stat_value', label='Value Points', type=GsiFieldVisualizers.FLOAT)
commodity_data_schema.add_field('decay_rate', label='Decay Rate', type=GsiFieldVisualizers.FLOAT, width=0.5)
commodity_data_schema.add_field('change_rate', label='Change Rate', type=GsiFieldVisualizers.FLOAT, width=0.5)
commodity_data_schema.add_field('decay_enabled', label='Decay Enabled', width=0.5)
commodity_data_schema.add_field('state_buff', label='Buff', width=2)
commodity_data_schema.add_field('distress_buff', label='Distress Buff', width=2)
commodity_data_schema.add_field('time_till_callback', label='Time')
commodity_data_schema.add_field('active_callback', label='Callback')
with commodity_data_schema.add_has_many('modifiers', GsiGridSchema, label='Modifiers') as sub_schema:
    sub_schema.add_field('modifier', label='Modifier')
    sub_schema.add_field('modifier_value', label='Modifier Value')

@GsiHandler('commodity_data_view', commodity_data_schema)
def generate_sim_commodity_data_view_data(sim_id:int=None):
    cur_sim_info = _get_sim_info_by_id(sim_id)
    if cur_sim_info is None:
        return []

    def add_modifier_entry(modifier_entries, modifier_name, modifier_value):
        modifier_entries.append({'modifier': modifier_name, 'modifier_value': modifier_value})

    stat_data = []
    for stat in list(cur_sim_info.commodity_tracker):
        if stat.is_skill:
            pass
        entry = {'stat_guid': str(stat.guid64), 'stat_name': stat.stat_type.__name__, 'stat_value': stat.get_value(), 'decay_rate': stat.get_decay_rate(), 'change_rate': stat.get_change_rate(), 'decay_enabled': 'x' if stat.decay_enabled else '', 'time_till_callback': str(stat._alarm_handle.get_remaining_time()) if stat._alarm_handle is not None else '', 'active_callback': str(stat._active_callback) if stat._active_callback is not None else ''}
        if stat._buff_handle is not None:
            buff_type = cur_sim_info.get_buff_type(stat._buff_handle)
            if buff_type is not None:
                entry['state_buff'] = buff_type.__name__
            else:
                stat_in_tracker = stat in cur_sim_info.commodity_tracker
                entry['state_buff'] = 'Buff Handle: {} and cannot find buff, Stat in Tracker: {}'.format(stat._buff_handle, stat_in_tracker)
        if stat._distress_buff_handle is not None:
            buff_type = cur_sim_info.get_buff_type(stat._distress_buff_handle)
            entry['distress_buff'] = buff_type.__name__
        modifier_entries = []
        add_modifier_entry(modifier_entries, 'persisted', 'x' if stat.persisted else '')
        add_modifier_entry(modifier_entries, 'remove_on_covergence', 'x' if stat.remove_on_convergence else '')
        add_modifier_entry(modifier_entries, 'min_value', stat.min_value)
        add_modifier_entry(modifier_entries, 'max_value', stat.max_value)
        add_modifier_entry(modifier_entries, 'statistic_modifier', stat._statistic_modifier)
        add_modifier_entry(modifier_entries, 'statistic_multiplier_increase', stat._statistic_multiplier_increase)
        add_modifier_entry(modifier_entries, 'statistic_multiplier_decrease', stat._statistic_multiplier_decrease)
        add_modifier_entry(modifier_entries, 'decay_rate_multiplier', stat._decay_rate_modifier)
        entry['modifiers'] = modifier_entries
        stat_data.append(entry)
    return stat_data

def generate_all_rel_bits():
    return [cls.__name__ for cls in services.get_instance_manager(Types.RELATIONSHIP_BIT).types.values()]

relationship_schema = GsiGridSchema(label='Relationships', sim_specific=True)
relationship_schema.add_field('relationship_id', label='Rel ID', hidden=True, unique_field=True)
relationship_schema.add_field('sim_name', label='Sim Name')
relationship_schema.add_field('depth', label='Depth', type=GsiFieldVisualizers.FLOAT)
relationship_schema.add_field('prevailing_stc', label='Prevailing STC')
relationship_schema.add_field('sim_id', label='Sim Id', hidden=True)
relationship_schema.add_field('target_id', label='Target Id', hidden=True)

def add_rel_bit_cheats(manager):
    with relationship_schema.add_view_cheat('relationship.add_bit', label='Add Bit') as cheat:
        cheat.add_token_param('sim_id')
        cheat.add_token_param('target_id')
        cheat.add_token_param('bit_string', dynamic_token_fn=generate_all_rel_bits)

services.get_instance_manager(Types.RELATIONSHIP_BIT).add_on_load_complete(add_rel_bit_cheats)
with relationship_schema.add_has_many('tracks', GsiGridSchema, label='Tracks') as sub_schema:
    sub_schema.add_field('type', label='Track')
    sub_schema.add_field('score', label='Score', type=GsiFieldVisualizers.FLOAT)
    sub_schema.add_field('decay', label='Decay', type=GsiFieldVisualizers.FLOAT)
    sub_schema.add_field('bits', label='Bit')
with relationship_schema.add_has_many('all_bits', GsiGridSchema, label='All Bits') as sub_schema:
    sub_schema.add_field('raw_bit', label='Bit')

@GsiHandler('relationship_view', relationship_schema)
def generate_relationship_view_data(sim_id:int=None):
    rel_data = []
    sim_info_manager = services.sim_info_manager()
    if sim_info_manager is None:
        return rel_data
    sim_info = sim_info_manager.get(sim_id)
    for rel in sim_info.relationship_tracker:
        target_sim_info = _get_sim_info_by_id(rel.relationship_id)
        entry = {'relationship_id': str(rel.relationship_id), 'depth': rel.depth, 'prevailing_stc': str(rel.get_prevailing_short_term_context_track()), 'sim_id': str(sim_info.sim_id)}
        if target_sim_info is not None:
            entry['target_id'] = str(target_sim_info.id)
            entry['sim_name'] = target_sim_info.full_name
        entry['tracks'] = []
        for track in rel.bit_track_tracker:
            track_entry = {'type': type(track).__name__, 'score': track.get_user_value(), 'decay': track.get_decay_rate()}
            active_bit = track.get_active_bit()
            if active_bit is not None:
                track_entry['bits'] = active_bit.__name__
            entry['tracks'].append(track_entry)
        entry['all_bits'] = []
        for bit in rel._bits:
            entry['all_bits'].append({'raw_bit': bit.__name__})
        rel_data.append(entry)
    return rel_data

autonomy_timer_schema = GsiGridSchema(label='Autonomy Timers', sim_specific=True)
autonomy_timer_schema.add_field('timer_name', label='Timer')
autonomy_timer_schema.add_field('timer_value', label='value')

@GsiHandler('autonomy_timer_view', autonomy_timer_schema)
def generate_autonomy_timer_view_data(sim_id:int=None):
    autonomy_timer_data = []
    sim = None
    sim_info_manager = services.sim_info_manager()
    if sim_info_manager is None:
        return autonomy_timer_data
    for sim_info in services.sim_info_manager().objects:
        while sim_id == sim_info.sim_id:
            sim = sim_info.get_sim_instance()
            break
    if sim is not None:
        for timer in sim.debug_get_autonomy_timers_gen():
            entry = {'timer_name': timer[0], 'timer_value': timer[1]}
            autonomy_timer_data.append(entry)
    return autonomy_timer_data

sim_info_schema = GsiGridSchema(label='Sim Info')
sim_info_schema.add_field('simId', label='Sim ID', width=1, unique_field=True)
sim_info_schema.add_field('householdId', label='Household ID', width=1)
sim_info_schema.add_field('firstName', label='First Name', width=1)
sim_info_schema.add_field('lastName', label='Last Name', width=1)
sim_info_schema.add_field('fullName', label='Full Name', hidden=True)
sim_info_schema.add_field('gender', label='Gender', width=1)
sim_info_schema.add_field('age', label='Age', width=1)
sim_info_schema.add_field('ageProgress', label='Age Progress', width=1)
sim_info_schema.add_field('ageTimers', label='Age Timers', width=2)
sim_info_schema.add_field('householdFunds', label='Household Funds', width=1)
sim_info_schema.add_field('personalFunds', label='Personal Funds', width=1)
sim_info_schema.add_field('active_mood', label='Active Mood', width=1)
sim_info_schema.add_field('on_active_lot', label='On Active Lot', width=1)
sim_info_schema.add_field('away_action', label='Away Action', width=1)
sim_info_schema.add_field('creation_source', label='Creation Source', width=1)
with sim_info_schema.add_view_cheat('sims.focus_camera_on_sim', label='Focus Camera', dbl_click=True) as cheat:
    cheat.add_token_param('simId')
with sim_info_schema.add_has_many('walkstyles', GsiGridSchema, label='Walkstyles') as sub_schema:
    sub_schema.add_field('walkstyle_priority', label='Priority', type=GsiFieldVisualizers.INT, width=0.5)
    sub_schema.add_field('walkstyle_type', label='Style', width=1)
    sub_schema.add_field('walkstyle_is_current', label='Is Current', width=0.5)
    sub_schema.add_field('walkstyle_is_default', label='Is Default', width=0.5)
with sim_info_schema.add_has_many('pregnancy', GsiGridSchema, label='Pregnancy') as sub_schema:
    sub_schema.add_field('pregnancy_field_name', label='Property')
    sub_schema.add_field('pregnancy_field_value', label='Value')

@GsiHandler('sim_infos', sim_info_schema)
def generate_sim_info_data(*args, zone_id:int=None, **kwargs):
    sim_info_data = []
    sim_info_manager = services.sim_info_manager(zone_id=zone_id)
    if sim_info_manager is None:
        return sim_info_data
    for sim_info in list(sim_info_manager.objects):
        ageTimers = []
        if sim_info._almost_can_age_handle is not None:
            ageTimers.append(str(sim_info._almost_can_age_handle.get_remaining_time()))
        if sim_info._can_age_handle is not None:
            ageTimers.append(str(sim_info._can_age_handle.get_remaining_time()))
        if sim_info._auto_age_handle is not None:
            ageTimers.append(str(sim_info._auto_age_handle.get_remaining_time()))
        entry = {'simId': str(hex(sim_info.sim_id)), 'firstName': sim_info.first_name, 'lastName': sim_info.last_name, 'fullName': sim_info.full_name, 'gender': str(sim_info.gender), 'age': str(sim_info.age), 'ageProgress': '{}, {:.2%}'.format(sim_info.age_progress, sim_info.age_progress/sims.aging.AgeTransitions.get_duration(sim_info.age)), 'ageTimers': '; '.join(ageTimers), 'personalFunds': str(sim_info.personal_funds), 'selectable': sim_info.is_selectable}
        sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        walkstyle_info = []
        entry['walkstyles'] = walkstyle_info
        for walkstyle_request in sim_info._walkstyle_requests:
            walkstyle_entry = {'walkstyle_priority': walkstyle_request.priority, 'walkstyle_type': str(walkstyle_request.walkstyle), 'walkstyle_is_current': 'X' if sim is not None and sim.walkstyle is walkstyle_request.walkstyle else '', 'walkstyle_is_default': 'X' if sim is not None and sim.default_walkstyle is walkstyle_request.walkstyle else ''}
            walkstyle_info.append(walkstyle_entry)
        entry['pregnancy'] = []
        entry['pregnancy'].append({'pregnancy_field_name': 'Is Pregnant', 'pregnancy_field_value': str(sim_info.is_pregnant)})
        if sim_info.is_pregnant:
            pregnancy_tracker = sim_info.pregnancy_tracker
            pregnancy_commodity = sim_info.get_statistic(pregnancy_tracker.PREGNANCY_COMMODITY, add=False)
            entry['pregnancy'].append({'pregnancy_field_name': 'Progress', 'pregnancy_field_value': '<None>' if pregnancy_commodity is None else '{:.2%}'.format(pregnancy_commodity.get_value()/pregnancy_commodity.max_value)})
            entry['pregnancy'].append({'pregnancy_field_name': 'Parents', 'pregnancy_field_value': ', '.join('<None>' if p is None else p.full_name for p in pregnancy_tracker.get_parents())})
            entry['pregnancy'].append({'pregnancy_field_name': 'Last Off-lot Update', 'pregnancy_field_value': str(pregnancy_tracker._last_modified)})
            entry['pregnancy'].append({'pregnancy_field_name': 'Seed', 'pregnancy_field_value': str(pregnancy_tracker._seed)})
        household_id = sim_info.household_id
        if household_id is None:
            entry['householdId'] = 'None'
            entry['householdFunds'] = '0'
        else:
            entry['householdId'] = str(hex(household_id))
            if sim_info.household:
                entry['householdFunds'] = str(sim_info.household.funds.money)
            else:
                entry['householdFunds'] = 'Pending'
        sim = sim_info.get_sim_instance()
        if sim is not None:
            entry['active_mood'] = str(sim.get_mood().__name__)
            entry['on_active_lot'] = str(sim.is_on_active_lot())
        current_away_action = sim_info.away_action_tracker.current_away_action
        if current_away_action is not None:
            entry['away_action'] = str(current_away_action)
        entry['creation_source'] = sim_info.creation_source
        sim_info_data.append(entry)
    sort_key_fn = lambda data: (data['selectable'] != True, data['firstName'])
    sim_info_data = sorted(sim_info_data, key=sort_key_fn)
    return sim_info_data

interaction_state_view_schema = GsiGridSchema(label='Interaction State', sim_specific=True)
interaction_state_view_schema.add_field('interactionId', label='ID', type=GsiFieldVisualizers.INT, width=1, unique_field=True)
interaction_state_view_schema.add_field('interactionName', label='Name', width=6)
interaction_state_view_schema.add_field('target', label='Target', width=3)
interaction_state_view_schema.add_field('interactionPos', label='State', width=2)
interaction_state_view_schema.add_field('group_id', label='Group Id', width=1)
interaction_state_view_schema.add_field('running', label='Running', width=1)
interaction_state_view_schema.add_field('priority', label='Priority', width=1)
interaction_state_view_schema.add_field('isFinishing', label='Finishing', width=1)
interaction_state_view_schema.add_field('isSuper', label='Is Super', width=1)
interaction_state_view_schema.add_field('isExpressed', label='Is Expressed', width=1, hidden=True)
interaction_state_view_schema.add_field('allowAuto', label='Allow Auto', width=1, hidden=True)
interaction_state_view_schema.add_field('allowUser', label='Allow User', width=1, hidden=True)
interaction_state_view_schema.add_field('visible', label='Visible', width=1)
interaction_state_view_schema.add_field('is_guaranteed', label='Guaranteed', width=1)
with interaction_state_view_schema.add_has_many('liabilities', GsiGridSchema, label='Liabilities') as sub_schema:
    sub_schema.add_field('liabilityType', label='Liability Type')
with interaction_state_view_schema.add_has_many('conditional_actions', GsiGridSchema, label='Conditional Actions') as sub_schema:
    sub_schema.add_field('name', label='Name', width=3)
    sub_schema.add_field('action', label='Interaction Action', width=2)
    sub_schema.add_field('satisfied', label='Satisfied', width=1)
    sub_schema.add_field('satisfied_conditions', label='Satisfied Conditions', width=4)
    sub_schema.add_field('unsatisfied_conditions', label='Unsatisfied Conditions', width=4)
    sub_schema.add_field('loot', label='Loot', width=4)
with interaction_state_view_schema.add_has_many('running_elements', GsiGridSchema, label='Running Elements') as sub_schema:
    sub_schema.add_field('name', label='Name')
    sub_schema.add_field('result', label='Result')

@GsiHandler('interaction_state_view', interaction_state_view_schema)
def generate_interaction_view_data(sim_id:int=None):
    sim_interaction_info = []
    cur_sim = _get_sim_instance_by_id(sim_id)
    if cur_sim is not None:
        for bucket in list(cur_sim.queue._buckets):
            for interaction in bucket:
                sim_interaction_info.append(create_state_info_entry(interaction, type(bucket).__name__))
        for interaction in list(cur_sim.si_state):
            sim_interaction_info.append(create_state_info_entry(interaction, 'SI_State'))
    return sim_interaction_info

def create_state_info_entry(interaction, interaction_pos):

    def bool_to_str(value):
        if value:
            return 'X'
        return ''

    if hasattr(interaction, 'name_override'):
        interaction_name = interaction.name_override
    else:
        interaction_name = type(interaction).__name__
    entry = {'interactionId': interaction.id, 'interactionName': interaction_name, 'target': str(interaction.target), 'interactionPos': interaction_pos, 'group_id': interaction.group_id, 'running': bool_to_str(interaction.running), 'priority': interaction.priority.name, 'isSuper': bool_to_str(interaction.is_super), 'isFinishing': bool_to_str(interaction.is_finishing), 'allowAuto': bool_to_str(interaction.allow_autonomous), 'allowUser': bool_to_str(interaction.allow_user_directed), 'visible': bool_to_str(interaction.visible), 'is_guaranteed': bool_to_str(interaction.is_guaranteed())}
    if interaction.liabilities:
        entry['liabilities'] = []
        for liability in interaction.liabilities:
            entry['liabilities'].append({'liabilityType': type(liability).__name__})
    if interaction._conditional_action_manager is not None:
        entry['conditional_actions'] = []
        for group in interaction._conditional_action_manager:
            group_entry = {}
            group_entry['name'] = str(group.conditional_action)
            group_entry['loot'] = str(group.conditional_action.loot_actions)
            group_entry['action'] = str(group.conditional_action.interaction_action)
            group_entry['satisfied'] = group.satisfied
            group_entry['satisfied_conditions'] = ',\n'.join(str(c) for c in group if c.satisfied)
            group_entry['unsatisfied_conditions'] = ',\n'.join(str(c) for c in group if not c.satisfied)
            entry['conditional_actions'].append(group_entry)
    runner = None
    if runner is not None:
        entry['running_elements'] = []

        def append_element(element_result, depth=0):
            try:
                for sub_element in iter(element_result.element):
                    if hasattr(sub_element, '_debug_run_list'):
                        for sub_element_result in sub_element._debug_run_list:
                            append_element(sub_element_result, depth=depth + 1)
                    else:
                        name = '+'*depth + str(sub_element)
                        entry['running_elements'].append({'name': name, 'result': 'Pending'})
            except TypeError:
                name = '+'*depth + str(element_result.element)
                entry['running_elements'].append({'name': name, 'result': str(element_result.result)})

        if hasattr(runner, '_debug_run_list'):
            while True:
                for element_result in runner._debug_run_list:
                    append_element(element_result)
    return entry

posture_state_view_schema = GsiGridSchema(label='Posture State', sim_specific=True)
posture_state_view_schema.add_field('postureType', label='Type', width=2.5)
posture_state_view_schema.add_field('postureName', label='postureName', unique_field=True, width=2.5)
posture_state_view_schema.add_field('postureTarget', label='Target', width=3)
posture_state_view_schema.add_field('postureSpec', label='Spec', width=1.5)
posture_state_view_schema.add_field('sourceInteraction', label='Source Interaction', width=2)
posture_state_view_schema.add_field('owningInteraction', label='Owning Interaction', width=2)

@GsiHandler('posture_state_view', posture_state_view_schema)
def generate_sim_info_view_data(sim_id:int=None):
    sim_posture_info = []
    cur_sim = _get_sim_instance_by_id(sim_id)
    if cur_sim is not None:
        if cur_sim.posture_state is not None:
            for posture_aspect in cur_sim.posture_state.aspects:
                owning_interaction_strs = [str(owning_interaction) for owning_interaction in posture_aspect.owning_interactions]
                cur_posture_info = {'postureType': type(posture_aspect).name, 'postureName': str(posture_aspect), 'postureTarget': str(posture_aspect.target), 'postureSpec': str(cur_sim.posture_state.spec), 'sourceInteraction': str(posture_aspect.source_interaction), 'owningInteraction': ' '.join(owning_interaction_strs)}
                sim_posture_info.append(cur_posture_info)
        else:
            cur_posture_info = {'postureType': '---', 'postureName': 'Sim Posture State is None'}
            sim_posture_info.append(cur_posture_info)
    return sim_posture_info

ui_manager_schema = GsiGridSchema(label='UI Manager', sim_specific=True)
ui_manager_schema.add_field('interaction_id', label='ID', type=GsiFieldVisualizers.INT, width=0.5, unique_field=True)
ui_manager_schema.add_field('insert_after_id', label='insert after Id', type=GsiFieldVisualizers.INT, width=0.5)
ui_manager_schema.add_field('target', width=1.3, label='target')
ui_manager_schema.add_field('canceled', label='canceled', width=0.5)
ui_manager_schema.add_field('ui_state', label='ui_state', width=0.5)
ui_manager_schema.add_field('super_id', label='super Id', type=GsiFieldVisualizers.INT, width=0.5)
ui_manager_schema.add_field('to_be_canceled', label='Interaction Canceled')
ui_manager_schema.add_field('associated_skill', label='associated_skill')
ui_manager_schema.add_field('visual_type', label='Visual Type')
ui_manager_schema.add_field('priority', label='priority')
ui_manager_schema.add_field('interaction', label='interaction', width=2)

@GsiHandler('ui_manager_view', ui_manager_schema)
def generate_sim_ui_manager_view_data(sim_id:int=None):

    def _visual_type_to_string(visual_type):
        if visual_type == 0:
            return 'Simple'
        if visual_type == 1:
            return 'Parent'
        if visual_type == 2:
            return 'Mixer'
        if visual_type == 3:
            return 'Posture'
        return 'Undefined'

    ui_data = []
    cur_sim = _get_sim_instance_by_id(sim_id)
    if cur_sim is not None:
        for int_info in cur_sim.ui_manager.get_interactions_gen():
            entry = {'interaction_id': int_info.interaction_id, 'insert_after_id': int_info.insert_after_id, 'target': str(int_info.target), 'canceled': int_info.canceled, 'ui_state': str(int_info.ui_state), 'to_be_canceled': str(int_info.interactions_to_be_canceled), 'super_id': int_info.super_id, 'associated_skill': str(int_info.associated_skill), 'visual_type': _visual_type_to_string(int_info.ui_visual_type), 'priority': str(int_info.priority)}
            ui_data.append(entry)
    return ui_data

sim_topics_schema = GsiGridSchema(label='Topic', sim_specific=True)
sim_topics_schema.add_field('sim_id', label='Sim ID', hidden=True, unique_field=True)
sim_topics_schema.add_field('topic_type', label='Topic')
sim_topics_schema.add_field('current_relevancy', label='Relevancy')
sim_topics_schema.add_field('target', label='Target')
sim_topics_schema.add_field('is_valid', label='Valid')
sim_topics_schema.add_field('target_id', label='Target ID', hidden=True)
with sim_topics_schema.add_view_cheat('topic.remove_topic', label='Remove Topic') as cheat:
    cheat.add_token_param('topic_type')
    cheat.add_token_param('sim_id')
    cheat.add_token_param('target_id')
with sim_topics_schema.add_view_cheat('topic.remove_all_topics', label='Remove All Of Type') as cheat:
    cheat.add_token_param('topic_type')
    cheat.add_token_param('sim_id')

@GsiHandler('sim_social_group_view', sim_topics_schema)
def generate_sim_topics_view_data(sim_id:int=None):
    topics_view_data = []
    cur_sim = _get_sim_instance_by_id(sim_id)
    if cur_sim is not None:
        for topic in cur_sim.get_topics_gen():
            topic_target = topic.target
            target_id = topic_target.id if topic_target is not None else ''
            topics_view_data.append({'sim_id': str(sim_id), 'topic_type': topic.__class__.__name__, 'current_relevancy': str(topic.current_relevancy), 'target': str(topic_target), 'target_id': str(target_id), 'is_valid': topic.is_valid})
    return topics_view_data

multi_motive_view_schema = GsiGridSchema(label='Statistics/Multi Motive View', sim_specific=True)
multi_motive_view_schema.add_field('buff_to_add', label='Buff')
multi_motive_view_schema.add_field('buff_added', label='Has Buff')
multi_motive_view_schema.add_field('count', label='Motives: (PASS/REQUIRED)')
multi_motive_view_schema.add_field('watcher_add', label='Has Watcher', hidden=True)
with multi_motive_view_schema.add_has_many('statistics', GsiGridSchema, label='Statistics Callback') as sub_schema:
    sub_schema.add_field('statistic', label='Stat')
    sub_schema.add_field('tuned_threshold', label='Desired Threshold')
    sub_schema.add_field('callback_threshold', label='Callback Threshold')

@GsiHandler('mult_motive_view', multi_motive_view_schema)
def generate_multi_motive_view_data(sim_id:int=None):
    view_data = []
    cur_sim = _get_sim_instance_by_id(sim_id)
    if cur_sim is not None:
        for multi_motive_tracker in cur_sim._multi_motive_buff_trackers:
            buff_to_add = multi_motive_tracker._buff
            entry = {'buff_to_add': str(buff_to_add), 'buff_added': 'x' if cur_sim.has_buff(buff_to_add) else '', 'count': '{}/{}'.format(multi_motive_tracker._motive_count, len(multi_motive_tracker._multi_motive_buff_motives)), 'watcher_add': 'x' if multi_motive_tracker._watcher_handle is not None else '', 'statistics': []}
            for (stat_type, callback_data) in tuple(multi_motive_tracker._commodity_callback.items()):
                threshold = multi_motive_tracker._multi_motive_buff_motives.get(stat_type)
                stat_entry = {'statistic': str(stat_type), 'tuned_threshold': str(threshold), 'callback_threshold': str(callback_data.threshold) if callback_data is not None else 'Stat not available'}
                entry['statistics'].append(stat_entry)
            view_data.append(entry)
    return view_data

sim_buff_schema = GsiGridSchema(label='Buffs', sim_specific=True)
sim_buff_schema.add_field('sim_id', label='SimId', hidden=True)
sim_buff_schema.add_field('name', label='Name', unique_field=True)
sim_buff_schema.add_field('visible', label='Visible')
sim_buff_schema.add_field('commodity', label='Commodity')
sim_buff_schema.add_field('mood', label='Mood')
sim_buff_schema.add_field('mood_weight', label='Mood Weight', type=GsiFieldVisualizers.FLOAT)
sim_buff_schema.add_field('mood_override', label='Mood Override')
sim_buff_schema.add_field('timeout', label='Timeout Time and Rate')
sim_buff_schema.add_field('success_modifier', label='Success Modifier', type=GsiFieldVisualizers.FLOAT)
sim_buff_schema.add_field('exclusive_index', label='ExclusiveIndex')
with sim_buff_schema.add_has_many('autonomy_modifiers', GsiGridSchema, label='Autonomy Modifiers') as sub_schema:
    sub_schema.add_field('score_multipliers', label='Score Multiplier')
    sub_schema.add_field('locked_stats', label='Locked Stats')
    sub_schema.add_field('decay_modifiers', label='Decay Modifier')
    sub_schema.add_field('statistic_modifiers', label='Statistic Modifier')
    sub_schema.add_field('skill_tag_modifiers', label='Skill Tag Modifier')
with sim_buff_schema.add_has_many('reference_modifiers', GsiGridSchema, label='Reference Modifiers') as sub_schema:
    sub_schema.add_field('type', label='Type')
    sub_schema.add_field('reference', label='Reference')
    sub_schema.add_field('score_modifier', label='Score Modifier', type=GsiFieldVisualizers.FLOAT)
    sub_schema.add_field('success_modifier', label='Success Modifier', type=GsiFieldVisualizers.FLOAT)
with sim_buff_schema.add_has_many('interactions', GsiGridSchema, label='Idle Interactions') as sub_schema:
    sub_schema.add_field('affordance', label='Affordance')
    sub_schema.add_field('min_lockout_initial', label='Min Time Initial', type=GsiFieldVisualizers.FLOAT)
    sub_schema.add_field('max_lockout_initial', label='Max Time Initial', type=GsiFieldVisualizers.FLOAT)
    sub_schema.add_field('min_lockout', label='Min Time', type=GsiFieldVisualizers.FLOAT)
    sub_schema.add_field('max_lockout', label='Max Time', type=GsiFieldVisualizers.FLOAT)
    sub_schema.add_field('unlock_time', label='Time until unlock')
with sim_buff_schema.add_view_cheat('sims.remove_all_buffs', label='Remove All Buffs') as cheat:
    cheat.add_token_param('sim_id')
with sim_buff_schema.add_view_cheat('sims.remove_buff', label='Remove Selected Buff') as cheat:
    cheat.add_token_param('name')
    cheat.add_token_param('sim_id')

@GsiHandler('sim_buffs_view', sim_buff_schema)
def generate_sim_buffs_view_data(sim_id:int=None):
    buffs_view_data = []
    sim_info = _get_sim_info_by_id(sim_id)
    if sim_info is not None:
        sim = sim_info.get_sim_instance()
        now = services.time_service().sim_now
        for buff in sim_info.buffs_component:
            entry = {'sim_id': str(sim_id), 'name': buff.__class__.__name__, 'visible': str(buff.visible), 'success_modifier': buff.success_modifier, 'mood': buff.mood_type.__name__ if buff.mood_type is not None else 'None', 'mood_weight': buff.mood_weight, 'mood_override': buff.mood_override.__name__ if buff.mood_override is not None else 'None', 'exclusive_index': str(buff.exclusive_index)}
            if buff.commodity is not None:
                entry['commodity'] = buff.commodity.__name__
                (absolute_time, rate) = buff.get_timeout_time()
                entry['timeout'] = '{} : Rate({})'.format(str(date_and_time.DateAndTime(absolute_time)), rate)
            else:
                entry['commodity'] = ('None',)
                entry['timeout'] = ''
            entry['autonomy_modifiers'] = []
            entry['reference_modifiers'] = []
            entry['interactions'] = []
            if buff.interactions is not None:
                for mixer_affordance in buff.interactions.interaction_items:
                    if mixer_affordance.lock_out_time_initial is not None:
                        min_lockout_initial = mixer_affordance.lock_out_time_initial.lower_bound
                        max_lockout_initial = mixer_affordance.lock_out_time_initial.upper_bound
                    else:
                        min_lockout_initial = 0
                        max_lockout_initial = 0
                    if mixer_affordance.lock_out_time is not None:
                        min_lockout = mixer_affordance.lock_out_time.interval.lower_bound
                        max_lockout = mixer_affordance.lock_out_time.interval.upper_bound
                    else:
                        min_lockout = 0
                        max_lockout = 0
                    if sim is not None and (mixer_affordance.lock_out_time_initial is not None or mixer_affordance.lock_out_time is not None):
                        unlock_time = sim._mixers_locked_out.get(mixer_affordance, None)
                        if unlock_time is not None:
                            unlock_time = str(unlock_time - now)
                        else:
                            unlock_time = 'Currently Unlocked'
                    else:
                        unlock_time = 'Does Not Lock'
                    entry['interactions'].append({'affordance': mixer_affordance.__name__, 'min_lockout_initial': min_lockout_initial, 'max_lockout_initial': max_lockout_initial, 'min_lockout': min_lockout, 'max_lockout': max_lockout, 'unlock_time': unlock_time})
            for modifier in buff.game_effect_modifiers.game_effect_modifiers:
                if isinstance(modifier, AutonomyModifier):
                    buff_entry = {'score_multipliers': str(modifier._score_multipliers), 'locked_stats': str(modifier._locked_stats), 'decay_modifiers': str(modifier._decay_modifiers), 'statistic_modifiers': str(modifier._statistic_modifiers), 'skill_tag_modifiers': str(modifier._skill_tag_modifiers)}
                    entry['autonomy_modifiers'].append(buff_entry)
                else:
                    buff_entry = {'type': str(modifier.modifier_type)}
                    if modifier.modifier_type == GameEffectType.AFFORDANCE_MODIFIER:
                        buff_entry['reference'] = ('{}'.format([reference_name for reference_name in modifier.debug_affordances_gen()]),)
                        buff_entry['score_modifier'] = (modifier._score_bonus,)
                        buff_entry['success_modifier'] = (modifier._success_modifier,)
                    elif modifier.modifier_type == GameEffectType.EFFECTIVE_SKILL_MODIFIER:
                        buff_entry['reference'] = str(modifier.modifier_key)
                        buff_entry['score_modifier'] = (modifier.modifier_value,)
                    entry['reference_modifiers'].append(buff_entry)
            buffs_view_data.append(entry)
    return buffs_view_data

sim_trait_schema = GsiGridSchema(label='Traits', sim_specific=True)
sim_trait_schema.add_field('sim_id', label='SimId', hidden=True)
sim_trait_schema.add_field('trait_name', label='Name', unique_field=True)
with sim_trait_schema.add_has_many('linked_buffs', GsiGridSchema, label='Linked Buffs') as sub_schema:
    sub_schema.add_field('name', label='Name')
    sub_schema.add_field('visible', label='Visible')
    sub_schema.add_field('mood', label='Mood')
    sub_schema.add_field('mood_weight', label='Mood Weight', type=GsiFieldVisualizers.INT)
with sim_trait_schema.add_has_many('conflict_traits', GsiGridSchema, label='Conflicted Traits') as sub_schema:
    sub_schema.add_field('name', label='Name')
with sim_trait_schema.add_view_cheat('traits.clear_traits', label='Remove All Traits') as cheat:
    cheat.add_token_param('sim_id')
with sim_trait_schema.add_view_cheat('traits.remove_trait', label='Remove Selected Trait') as cheat:
    cheat.add_token_param('trait_name')
    cheat.add_token_param('sim_id')

def generate_all_traits():
    return [cls.__name__ for cls in services.get_instance_manager(Types.TRAIT).types.values()]

def add_trait_cheats(manager):
    with sim_trait_schema.add_view_cheat('traits.equip_trait', label='Add Trait') as cheat:
        cheat.add_token_param('trait_name', dynamic_token_fn=generate_all_traits)
        cheat.add_token_param('sim_id')

services.get_instance_manager(Types.TRAIT).add_on_load_complete(add_trait_cheats)

@GsiHandler('sim_traits_view', sim_trait_schema)
def generate_sim_traits_view_data(sim_id:int=None):
    traits_view_data = []
    sim_info = _get_sim_info_by_id(sim_id)
    if sim_info is not None:
        for trait in sim_info.trait_tracker.equipped_traits:
            entry = {'sim_id': str(sim_id), 'trait_name': trait.__name__}
            entry['linked_buffs'] = []
            for buff in trait.buffs:
                buff_type = buff.buff_type
                buff_entry = {'name': buff_type.__name__, 'visible': str(buff_type.visible), 'commodity': buff_type.commodity.__name__ if buff_type.commodity is not None else 'None', 'mood': buff_type.mood_type.__name__ if buff_type.mood_type is not None else 'None', 'mood_weight': buff_type.mood_weight}
                entry['linked_buffs'].append(buff_entry)
            entry['conflict_traits'] = []
            for conflict_trait in trait.conflicting_traits:
                conflict_trait_entry = {'name': conflict_trait.__name__}
                entry['conflict_traits'].append(conflict_trait_entry)
            traits_view_data.append(entry)
    return traits_view_data

sim_motive_graph_alarm = None

def enable_sim_motive_graph_logging(*args, enableLog=False, **kwargs):
    global sim_motive_graph_alarm
    if enableLog and sim_motive_graph_alarm is None:
        sim_motive_graph_alarm = alarms.add_alarm(sim_motive_archiver, TimeSpan(5000), lambda _: archive_sim_motives(), repeating=True)
    else:
        alarms.cancel_alarm(sim_motive_graph_alarm)
        sim_motive_graph_alarm = None

sim_motives_graph_schema = GsiLineGraphSchema(label='Motives Graph', x_axis_label='X-Axis', y_axis_label='Y-Axis', sim_specific=True, y_min=-100, y_max=100)
sim_motives_graph_schema.add_field('motive_fun', axis=GsiLineGraphSchema.Axis.Y, type=GsiFieldVisualizers.FLOAT)
sim_motives_graph_schema.add_field('motive_social', axis=GsiLineGraphSchema.Axis.Y, type=GsiFieldVisualizers.FLOAT)
sim_motives_graph_schema.add_field('motive_hygiene', axis=GsiLineGraphSchema.Axis.Y, type=GsiFieldVisualizers.FLOAT)
sim_motives_graph_schema.add_field('motive_hunger', axis=GsiLineGraphSchema.Axis.Y, type=GsiFieldVisualizers.FLOAT)
sim_motives_graph_schema.add_field('motive_energy', axis=GsiLineGraphSchema.Axis.Y, type=GsiFieldVisualizers.FLOAT)
sim_motives_graph_schema.add_field('motive_bladder', axis=GsiLineGraphSchema.Axis.Y, type=GsiFieldVisualizers.FLOAT)
sim_motives_graph_schema.add_field('timestamp', axis=GsiLineGraphSchema.Axis.X, type=GsiFieldVisualizers.TIME)
sim_motive_archiver = GameplayArchiver('sim_motive_schema', sim_motives_graph_schema, custom_enable_fn=enable_sim_motive_graph_logging)

def archive_sim_motives():
    sim_info_manager = services.sim_info_manager()
    if sim_info_manager is None:
        logger.error('Archiving sim motives when the sim_info_manager is absent.')
        return
    all_motives = ['motive_fun', 'motive_social', 'motive_hygiene', 'motive_hunger', 'motive_energy', 'motive_bladder']
    sim_infos = list(sim_info_manager.values())
    for sim_info in sim_infos:
        sim = sim_info.get_sim_instance()
        while sim is not None:
            archive_data = {}
            for motive in all_motives:
                cur_stat = get_tunable_instance(sims4.resources.Types.STATISTIC, motive, exact_match=True)
                tracker = sim.get_tracker(cur_stat)
                cur_value = tracker.get_value(cur_stat)
                archive_data[motive] = cur_value
            archive_data['sim_id'] = str(sim.sim_id)
            sim_motive_archiver.archive(object_id=sim.id, data=archive_data)

