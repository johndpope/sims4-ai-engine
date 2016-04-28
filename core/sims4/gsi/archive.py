import json
import time
import zlib
from sims4.gsi.schema import GsiSchema
from uid import UniqueIdGenerator
import sims4.gsi.dispatcher
import sims4.log
import sims4.reload
import sims4.zone_utils
logger = sims4.log.Logger('GSI')
with sims4.reload.protected(globals()):
    archive_data = {}
    archive_schemas = {}
    all_archivers = {}
    archive_id = UniqueIdGenerator()
ARCHIVE_DEFAULT_RECORDS = 50
ARCHIVE_MAX_RECORDS = ARCHIVE_DEFAULT_RECORDS

def set_max_archive_records(max_records):
    global ARCHIVE_MAX_RECORDS
    ARCHIVE_MAX_RECORDS = max_records

def set_max_archive_records_default():
    set_max_archive_records(ARCHIVE_DEFAULT_RECORDS)

def set_archive_enabled(archive_type, enable=True):
    if archive_type in all_archivers:
        all_archivers[archive_type].archive_enable_fn(enableLog=enable)
    else:
        logger.error('Tried to enable {} which is not a valid archive name'.format(archive_type))

def set_all_archivers_enabled(enable=True):
    for archiver in all_archivers.values():
        while archiver._enable_on_all_enable:
            archiver.archive_enable_fn(enableLog=enable)

class Archiver:
    __qualname__ = 'Archiver'
    __slots__ = ('_type_name', '_flatten_data', '_sim_specific', '_max_records', '_custom_enable_fn', '_archive_enabled', '__weakref__')

    def __init__(self, type_name=None, schema=None, max_records=None, enable_archive_by_default=False, add_to_archive_enable_functions=True, custom_enable_fn=None):
        self._type_name = type_name
        self._flatten_data = schema.is_graph_schema
        self._sim_specific = schema.is_sim_specific
        self._max_records = max_records
        self._custom_enable_fn = custom_enable_fn
        self._enable_on_all_enable = add_to_archive_enable_functions
        self._archive_enabled = False
        sims4.gsi.dispatcher.add_handler('{}{}'.format(type_name, sims4.gsi.dispatcher.ARCHIVE_TOGGLE_SUFFIX), None, lambda *args, **kwargs: self.archive_enable_fn(*args, **kwargs))
        all_archivers[type_name] = self
        register_archive_type(type_name, schema, flatten_data=schema.is_graph_schema, partition_by_obj=self._sim_specific)

    @property
    def enabled(self):
        return self._archive_enabled

    def archive_enable_fn(self, *args, enableLog=False, **kwargs):
        self._archive_enabled = enableLog
        if self._custom_enable_fn is not None:
            self._custom_enable_fn(enableLog=enableLog, *args, **kwargs)

    def archive(self, data=None, object_id=None, zone_override=None):
        if zone_override is not None:
            zone_id = zone_override
        else:
            zone_id = sims4.zone_utils.get_zone_id(True)
            if not zone_id:
                logger.error('Archiving data to zone 0. This data will be inaccessible to the GSI.')
                zone_id = 0
        now = int(time.time())
        record = ArchiveRecord(zone_id=zone_id, object_id=object_id, timestamp=now, data=data, flatten_data=self._flatten_data)
        if self._sim_specific:
            if object_id is None:
                logger.error('Archiving data to a sim_specific archive with no object ID. This data will be inaccessible to the GSI.')
            archive_list = archive_data[self._type_name].get(object_id)
            archive_list = []
            archive_data[self._type_name][object_id] = archive_list
        else:
            archive_list = archive_data[self._type_name]
        archive_list.append(record)
        num_max_records = ARCHIVE_MAX_RECORDS
        if self._max_records is not None and num_max_records < self._max_records:
            num_max_records = self._max_records
        num_records = len(archive_list)
        if num_records > num_max_records:
            diff = num_records - num_max_records
            archive_list = archive_list[diff:]
            if self._sim_specific:
                archive_data[self._type_name][object_id] = archive_list
            else:
                archive_data[self._type_name] = archive_list

class ArchiveRecord:
    __qualname__ = 'ArchiveRecord'
    __slots__ = ('zone_id', 'object_id', 'timestamp', 'uid', 'compressed_json')

    def __init__(self, zone_id=None, object_id=None, timestamp=None, data=None, flatten_data=False):
        self.zone_id = zone_id
        self.object_id = object_id
        self.timestamp = timestamp
        full_dict = {'zone_id': hex(zone_id), 'object_id': hex(object_id) if object_id is not None else 'None', 'timestamp': timestamp, 'uid': archive_id(), 'data': data}
        if flatten_data:
            uncompressed_json = json.dumps(self.flatten_archive(full_dict))
        else:
            uncompressed_json = json.dumps(full_dict)
        self.compressed_json = zlib.compress(uncompressed_json.encode())

    def flatten_archive(self, full_dict):
        data_fields = full_dict['data']
        for (key, field) in data_fields.items():
            full_dict[key] = field
        return full_dict

def register_archive_type(type_name, schema, flatten_data=False, partition_by_obj=False):
    if isinstance(schema, GsiSchema):
        schema = schema.output
    if type_name in archive_schemas:
        logger.error('Replacing archive type for {}.', type_name)
        del archive_schemas[type_name]
    path = type_name.strip('/')
    new_archive = archive_data.get(type_name)
    if new_archive is None:
        if partition_by_obj:
            new_archive = {}
        else:
            new_archive = []
        archive_data[type_name] = new_archive
    actual_schema = {'archive': True, 'perf_toggle': True, 'unique_field': 'uid', 'definition': [{'name': 'zone_id', 'type': 'string', 'label': 'Zone', 'hidden': True}, {'name': 'object_id', 'type': 'string', 'label': 'Object ID', 'hidden': True}, {'name': 'timestamp', 'type': 'int', 'label': 'Time', 'is_time': True, 'axis': 'xField'}, {'name': 'uid', 'type': 'int', 'label': 'UId', 'hidden': True}]}
    if flatten_data:
        for (key, entry) in schema.items():
            if key == 'definition':
                for definition_entry in entry:
                    actual_schema['definition'].append(definition_entry)
            else:
                actual_schema[key] = entry
    else:
        actual_schema['associations'] = [{'name': 'data', 'type': 'hasOne', 'schema': schema}]
    for (key, value) in schema.items():
        if key not in ('definition', 'associations'):
            actual_schema[key] = value
    archive_schemas[type_name] = actual_schema

    def archive_handler(zone_id:int=None, object_id:int=None, sim_id:int=None, timestamp:int=None):
        if object_id is None and sim_id is not None:
            object_id = sim_id
        if partition_by_obj:
            archive_data_list = archive_data[type_name].get(object_id)
            return '[]'
        else:
            archive_data_list = archive_data[type_name]
        try:
            first_entry = True
            json_output = '['
            for record in archive_data_list:
                if zone_id is not None and zone_id != record.zone_id:
                    pass
                if object_id is not None and object_id != record.object_id:
                    pass
                if timestamp is not None and timestamp >= record.timestamp:
                    pass
                if first_entry:
                    first_entry = False
                else:
                    json_output += ','
                uncompressed_json = zlib.decompress(record.compressed_json).decode('utf-8')
                json_output += uncompressed_json
            json_output += ']'
        except MemoryError:
            logger.error('Archive Data[{}] has too many entries: {}', type_name, len(archive_data_list))
            json_output = '[]'
        return json_output

    sims4.gsi.dispatcher.GsiHandler(path, actual_schema, suppress_json=True)(archive_handler)

