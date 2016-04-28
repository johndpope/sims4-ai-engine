from sims4.gsi.dispatcher import GsiHandler
from sims4.gsi.schema import GsiGridSchema, GsiFieldVisualizers
import services
broadcaster_schema = GsiGridSchema(label='Broadcasters')
broadcaster_schema.add_field('broadcaster_id', label='ID', type=GsiFieldVisualizers.INT, width=0.5, unique_field=True)
broadcaster_schema.add_field('broadcaster_type', label='Type', width=1)
broadcaster_schema.add_field('broadcasting_object', label='Object', width=1)
broadcaster_schema.add_field('broadcasting_object_id', label='Object ID', type=GsiFieldVisualizers.INT, hidden=True)
broadcaster_schema.add_field('broadcaster_status', label='Status', width=1)
broadcaster_schema.add_view_cheat('debugvis.broadcasters.start', label='Start Visualization')
broadcaster_schema.add_view_cheat('debugvis.broadcasters.stop', label='Stop Visualization')
with broadcaster_schema.add_cheat('objects.focus_camera_on_object', label='Focus', dbl_click=True) as cheat:
    cheat.add_token_param('broadcasting_object_id')
with broadcaster_schema.add_has_many('affected_objects', GsiGridSchema, label='Affected Objects') as sub_schema:
    sub_schema.add_field('object_name', label='Object', width=1)
    sub_schema.add_field('last_reaction_time', label='Reaction Time', width=1)
    sub_schema.add_field('in_area', label='In Area', width=1)

@GsiHandler('broadcasters', broadcaster_schema)
def generate_broadcaster_data():

    def _get_broadcasters_gen():
        try:
            broadcaster_service = services.current_zone().broadcaster_service
            while broadcaster_service is not None:
                for broadcaster in broadcaster_service.get_broadcasters_gen(inspect_only=True):
                    yield ('Active', broadcaster)
                    linked_broadcasters = list(broadcaster.get_linked_broadcasters_gen())
                    for linked_broadcaster in linked_broadcasters:
                        yield ('Linked/{}'.format(broadcaster.broadcaster_id), linked_broadcaster)
                for broadcaster in broadcaster_service.get_pending_broadcasters_gen():
                    yield ('Pending', broadcaster)
        except RuntimeError:
            pass

    broadcaster_data = []
    for (status, broadcaster) in _get_broadcasters_gen():
        entry = {'broadcaster_id': str(broadcaster.broadcaster_id), 'broadcaster_type': str(type(broadcaster)), 'broadcasting_object': str(broadcaster.broadcasting_object), 'broadcasting_object_id': broadcaster.broadcasting_object.id if broadcaster.broadcasting_object is not None else 0, 'broadcaster_status': status}
        affected_object_info = []
        entry['affected_objects'] = affected_object_info
        for (obj, data) in broadcaster._affected_objects.items():
            affect_object_entry = {'object_name': str(obj), 'last_reaction_time': str(data[0]), 'in_area': str(data[1])}
            affected_object_info.append(affect_object_entry)
        broadcaster_data.append(entry)
    return broadcaster_data

