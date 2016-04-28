from sims4.gsi.dispatcher import GsiHandler
from sims4.gsi.schema import GsiGridSchema
import services
test_event_schema = GsiGridSchema(label='Event Testing')
test_event_schema.add_field('event_enum', label='Enum', unique_field=True, width=1)
test_event_schema.add_field('event_name', label='Event Name', width=12)
test_event_schema.add_field('custom_key', label='Custom Key', width=15)
test_event_schema.add_field('register_count', label='Registered', width=2)
test_event_schema.add_field('called_count', label='Called', width=2)
test_event_schema.add_field('cost', label='Cost', width=2)
test_event_schema.add_field('handlers', label='Handlers', width=20)
with test_event_schema.add_has_many('handles', GsiGridSchema, label='Objectives') as sub_schema:
    sub_schema.add_field('handle', label='Handle')

@GsiHandler('test_event_view', test_event_schema)
def generate_test_event_view_data(*args, zone_id:int=None, **kwargs):
    event_mgr = services.get_event_manager()
    all_events = []
    for (key, handlers) in event_mgr._test_event_callback_map.items():
        (event_enum, custom_key) = key
        event_data = {}
        registered = len(handlers)
        called = '?'
        cost = '?'
        event_data['event_enum'] = int(event_enum)
        event_data['event_name'] = str(event_enum)
        event_data['custom_key'] = str(custom_key)
        event_data['register_count'] = registered
        event_data['called_count'] = called
        event_data['cost'] = cost
        event_data['handlers'] = str(handlers)
        sub_data = []
        for handle in handlers:
            handlers_data = {}
            handlers_data['handle'] = str(handle)
            sub_data.append(handlers_data)
        event_data['handles'] = sub_data
        all_events.append(event_data)
    return all_events

