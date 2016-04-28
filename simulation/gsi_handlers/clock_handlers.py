from gsi_handlers.gameplay_archiver import GameplayArchiver
from sims4.gsi.schema import GsiGridSchema
speed_change_schema = GsiGridSchema(label='Speed Change Request Log')
speed_change_schema.add_field('sim', label='Sim')
speed_change_schema.add_field('interaction', label='Interaction', width=3)
speed_change_schema.add_field('request_type', label='Request Type')
speed_change_schema.add_field('requested_speed', label='Requested Speed')
speed_change_schema.add_field('is_request', label='Is Request')
speed_change_archiver = GameplayArchiver('speed_change_log', speed_change_schema)

def archive_speed_change(interaction, request_type, requested_speed, is_request):
    archive_data = {'sim': str(interaction.sim), 'interaction': str(interaction), 'request_type': str(request_type), 'requested_speed': str(requested_speed), 'is_request': is_request}
    speed_change_archiver.archive(data=archive_data)

