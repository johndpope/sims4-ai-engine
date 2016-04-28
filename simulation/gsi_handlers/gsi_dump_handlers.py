from gsi_handlers.gameplay_archiver import GameplayArchiver
from sims4.gsi.schema import GsiGridSchema
from sims4.log import generate_message_with_callstack
import services
gsi_dump_schema = GsiGridSchema(label='GSI Dump Log')
gsi_dump_schema.add_field('game_time', label='Game Time')
gsi_dump_schema.add_field('gsi_filename', label='Filename')
gsi_dump_schema.add_field('error_log_or_exception', label='Error', width=4)
gsi_dump_schema.add_field('callstack', label='Callstack', width=4)
gsi_dump_archiver = GameplayArchiver('gsi_dump_log', gsi_dump_schema)

def archive_gsi_dump(filename_str, error_str):
    callstack = generate_message_with_callstack('GSI Dump')
    archive_data = {'game_time': str(services.game_clock_service().now()), 'gsi_filename': filename_str, 'error_log_or_exception': error_str, 'callstack': callstack}
    gsi_dump_archiver.archive(data=archive_data)

