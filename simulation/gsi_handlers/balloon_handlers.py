from gsi_handlers.gameplay_archiver import GameplayArchiver
from sims4.gsi.schema import GsiGridSchema, GsiFieldVisualizers
balloon_archive_schema = GsiGridSchema(label='Balloons', sim_specific=True)
balloon_archive_schema.add_field('sim', label='Sim', width=2)
balloon_archive_schema.add_field('interaction', label='Interaction', width=2)
balloon_archive_schema.add_field('balloon_type', label='Type', width=2)
balloon_archive_schema.add_field('icon', label='Icon', width=2)
balloon_archive_schema.add_field('balloon_category', label='Category', width=2)
balloon_archive_schema.add_field('weight', label='Weight', type=GsiFieldVisualizers.INT, width=1)
balloon_archive_schema.add_field('total_weight', label='Total Weight', type=GsiFieldVisualizers.INT, width=1)
with balloon_archive_schema.add_has_many('Considered', GsiGridSchema) as sub_schema:
    sub_schema.add_field('test_result', label='Test Result', width=2)
    sub_schema.add_field('balloon_type', label='Type', width=2)
    sub_schema.add_field('icon', label='Icon', width=2)
    sub_schema.add_field('weight', label='Weight', type=GsiFieldVisualizers.INT, width=1)
    sub_schema.add_field('balloon_category', label='Category', width=2)
archiver = GameplayArchiver('balloon', balloon_archive_schema)

def archive_balloon_data(sim, interaction, result, icon, entries):
    if result is not None:
        weight = result.weight
        balloon_type = str(result.balloon_type)
        gsi_category = result.gsi_category
    else:
        weight = 0
        balloon_type = 'None'
        gsi_category = 'None'
    entry = {}
    entry['sim'] = str(sim)
    entry['interaction'] = str(interaction)
    entry['weight'] = weight
    entry['balloon_type'] = balloon_type
    entry['icon'] = str(icon)
    entry['balloon_category'] = gsi_category
    entry['total_weight'] = sum(entry['weight'] for entry in entries)
    entry['Considered'] = entries
    archiver.archive(data=entry, object_id=sim.id)

