from gsi_handlers.gameplay_archiver import GameplayArchiver
from sims4.gsi.schema import GsiGridSchema
ambient_archive_schema = GsiGridSchema(label='Ambient Log')
ambient_archive_schema.add_field('sources', label='Sources')
archiver = GameplayArchiver('ambient', ambient_archive_schema)

def archive_ambient_data(description):
    entry = {}
    entry['sources'] = description
    archiver.archive(data=entry)

