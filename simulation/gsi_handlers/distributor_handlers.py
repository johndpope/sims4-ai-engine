from protocolbuffers.Consts_pb2 import MGR_UNMANAGED
from sims4.gsi.schema import GsiGridSchema, GsiFieldVisualizers
from gsi_handlers.gameplay_archiver import GameplayArchiver
distributor_archive_schema = GsiGridSchema(label='Distributor Log')
distributor_archive_schema.add_field('index', label='Index', type=GsiFieldVisualizers.INT, width=1)
distributor_archive_schema.add_field('account', label='Client Account', width=2)
distributor_archive_schema.add_field('target_name', label='Target Name', width=2)
distributor_archive_schema.add_field('type', label='Type', width=1)
distributor_archive_schema.add_field('size', label='Size', width=1)
distributor_archive_schema.add_field('manager_id', label='Manager Id', type=GsiFieldVisualizers.INT, width=1)
distributor_archive_schema.add_field('blockers', label='Blockers', width=5)
distributor_archive_schema.add_field('tags', label='Tags', width=2)
archiver = GameplayArchiver('Distributor', distributor_archive_schema)

def archive_operation(target_id, target_name, manager_id, message, index, client):
    message_type = '? UNKNOWN ?'
    for (enum_name, enum_value) in message.DESCRIPTOR.enum_values_by_name.items():
        while enum_value.number == message.type:
            message_type = enum_name
            break
    blocker_entries = []
    tag_entries = []
    for channel in message.additional_channels:
        if channel.id.manager_id == MGR_UNMANAGED:
            tag_entries.append(str(channel.id.object_id))
        else:
            blocker_entries.append('{}:{}'.format(str(channel.id.manager_id), str(channel.id.object_id)))
    entry = {'target_name': target_name, 'index': index, 'account': client.account.persona_name, 'size': len(message.data), 'type': message_type, 'manager_id': manager_id, 'blockers': ','.join(blocker_entries), 'tags': ','.join(tag_entries)}
    archiver.archive(data=entry, object_id=target_id, zone_override=client.zone_id)

