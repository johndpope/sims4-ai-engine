import itertools
from sims4.gsi.dispatcher import GsiHandler
from sims4.gsi.schema import GsiGridSchema, GsiFieldVisualizers
import services
group_schema = GsiGridSchema(label='Social Groups')
group_schema.add_field('type', label='Group Type', width=1, unique_field=True)
group_schema.add_field('count', label='Count', type=GsiFieldVisualizers.INT, width=0.5)
group_schema.add_field('anchor', label='Anchor', width=1)
group_schema.add_field('shutting_down', label='Shutting Down', width=0.4)
with group_schema.add_has_many('states', GsiGridSchema, label='States') as sub_schema:
    sub_schema.add_field('state', label='State', width=1)
    sub_schema.add_field('value', label='Value', width=1)
with group_schema.add_has_many('group_members', GsiGridSchema, label='Members') as sub_schema:
    sub_schema.add_field('sim_id', label='Sim ID', width=0.35)
    sub_schema.add_field('sim_name', label='Sim Name', width=0.4)
    sub_schema.add_field('registered_si', label='Registered SIs')
    sub_schema.add_field('social_context', label='Social Context')

@GsiHandler('social_groups', group_schema)
def generate_group_data():
    group_data = []
    for group in services.social_group_manager().values():
        entry = {'type': repr(group), 'count': len(group), 'shutting_down': 'x' if group.has_been_shutdown else '', 'anchor': str(getattr(group, '_anchor', None))}
        state_info = []
        entry['states'] = state_info
        if group.State is not None:
            for (state, value) in group.State.items():
                state_entry = {'state': str(state), 'value': str(value)}
                state_info.append(state_entry)
        members_info = []
        entry['group_members'] = members_info
        for sim in group:
            interactions = group._si_registry.get(sim)
            group_members_entry = {'sim_id': str(sim.id), 'sim_name': sim.full_name, 'registered_si': str(interactions), 'social_context': str(sim.get_social_context())}
            members_info.append(group_members_entry)
        group_data.append(entry)
    return group_data

