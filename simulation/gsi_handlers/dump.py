import datetime
import gzip
import os.path
import pickle
from gsi_handlers.gsi_dump_handlers import archive_gsi_dump
import services
import sims4.gsi.dispatcher
import sims4.log
logger = sims4.log.Logger('GSI')
GSI_DUMP_VERSION = 1

def save_dump_to_location(location, filename=None, console_output=None, compress_file=True, error_str='Default'):
    now = datetime.datetime.now()
    if filename is None:
        filename = '{}-{}-{}_{}h{}m{}s'.format(now.year, now.month, now.day, now.hour, now.minute, now.second)
    filename_w_ext = '{}.gsidump'.format(filename)
    filename_zip = '{}.gz'.format(filename_w_ext)
    full_path = os.path.join(location, filename_w_ext)
    full_zip_path = os.path.join(location, filename_zip)
    fail_count = 0
    while os.path.exists(full_path):
        fail_count += 1
        filename_w_ext = '{}_{}.gsidump'.format(filename, fail_count)
        full_path = os.path.join(location, filename_w_ext)
    archive_gsi_dump(filename, error_str)
    with open(full_path, mode='wb') as file:
        pickle.dump({'version': GSI_DUMP_VERSION}, file, protocol=3)
        for (entry, schema, entry_data) in get_dump_gen(console_output):
            pickle.dump({'entry': entry, 'data': entry_data, 'schema': schema}, file, protocol=3)
    if compress_file:
        with open(full_path, mode='rb') as file_in, gzip.open(full_zip_path, 'wb') as file_out:
            file_out.writelines(file_in)
        os.remove(full_path)
        return full_zip_path
    return full_path

def get_dump_gen(console_output):
    GsiSchema = sims4.gsi.schema.GsiSchema
    for zone_id in services._zone_manager:
        zone = services.get_zone(zone_id)
        if zone is None or not zone.is_instantiated:
            logger.warn("[cgast] Trying to dump GSI Data for zone {} but it's not instantiated.", zone_id)
        sim_info_manager = services.sim_info_manager(zone_id=zone_id)
        sim_ids = set()
        for sim_info in list(sim_info_manager.objects):
            sim_ids.add(sim_info.sim_id)
        for (entry, dispatch_data) in sims4.gsi.dispatcher.dispatch_table.items():
            schema = dispatch_data[1]
            if schema is None:
                pass
            if isinstance(schema, GsiSchema):
                schema = schema.output
            if 'is_global_cheat' in schema and schema['is_global_cheat']:
                pass
            if entry == 'command':
                pass
            entry_data = []
            if 'sim_specific' in schema and schema['sim_specific']:
                for sim_id in sim_ids:
                    new_entry = _build_dump_entry(entry, schema, {'sim_id': sim_id, 'zone_id': zone_id})
                    if new_entry is not None:
                        entry_data.append(new_entry)
                    else:
                        while console_output is not None:
                            try:
                                console_output('Failed to collect data for {} on Sim ID {}'.format(entry, sim_id))
                            except:
                                pass
            else:
                new_entry = _build_dump_entry(entry, schema, {'zone_id': zone_id})
                if new_entry is not None:
                    entry_data.append(new_entry)
                elif console_output is not None:
                    try:
                        console_output('Failed to collect data for {}'.format(entry))
                    except:
                        pass
            yield (entry, schema, entry_data)

def _build_dump_entry(entry, schema, params):
    string_params = {key: str(value) for (key, value) in params.items()}
    try:
        response = sims4.gsi.dispatcher.handle_request(entry, string_params)
    except:
        logger.exception('Exception in handler: {}', schema)
        response = None
    if response is not None:
        return {'params': params, 'response': response}
    return

