from gsi_handlers import gsi_utils
from gsi_handlers.gameplay_archiver import GameplayArchiver
from sims4.gsi.schema import GsiGridSchema, GsiFieldVisualizers
from uid import UniqueIdGenerator
import services
import sims4.reload
live_drag_schema = GsiGridSchema(label='Live Drag')
live_drag_schema.add_field('live_drag_id', label='ID', type=GsiFieldVisualizers.INT, width=0.5)
live_drag_schema.add_field('live_drag_operation', label='Operation', width=1)
live_drag_schema.add_field('live_drag_message_type', label='Message Type', width=1)
live_drag_schema.add_field('live_drag_from_where', label='From', width=2)
live_drag_schema.add_field('live_drag_to_where', label='To', width=2)
live_drag_schema.add_field('live_drag_object', label='Object', width=2)
live_drag_schema.add_field('live_drag_object_id', label='Object ID', type=GsiFieldVisualizers.INT, hidden=True)
live_drag_schema.add_field('live_drag_definition_id', label='Definition ID', type=GsiFieldVisualizers.INT, hidden=True)
live_drag_schema.add_field('live_drag_status', label='Can Live Drag', type=GsiFieldVisualizers.STRING, width=1)
live_drag_schema.add_field('live_drag_target', label='Drop Target', width=1)
live_drag_schema.add_field('live_drag_stack_id', label='Stack ID', type=GsiFieldVisualizers.INT, width=1, hidden=True)
live_drag_schema.add_field('live_drag_stack_count', label='Stack Count', type=GsiFieldVisualizers.INT, width=1)
live_drag_schema.add_field('live_drag_object_inventory', label='Inventory', width=1)
live_drag_archiver = GameplayArchiver('live_drag', live_drag_schema)
with sims4.reload.protected(globals()):
    _live_drag_index = UniqueIdGenerator()

def archive_live_drag(op_or_command, message_type, location_from, location_to, live_drag_object=None, live_drag_object_id:int=0, live_drag_target=None):
    definition_id = 0
    stack_id = 0
    stack_count = 1
    can_live_drag = False
    current_inventory = None
    if live_drag_object is None:
        live_drag_object = services.current_zone().find_object(live_drag_object_id)
    if live_drag_object is not None:
        definition_id = live_drag_object.definition.id
        live_drag_component = live_drag_object.live_drag_component
        can_live_drag = live_drag_component.can_live_drag
        inventoryitem_component = live_drag_object.inventoryitem_component
        stack_count = live_drag_object.stack_count()
        if inventoryitem_component is not None:
            stack_id = inventoryitem_component.get_stack_id()
            current_inventory = inventoryitem_component.get_inventory()
    entry = {'live_drag_id': _live_drag_index(), 'live_drag_operation': str(op_or_command), 'live_drag_message_type': message_type, 'live_drag_from_where': str(location_from), 'live_drag_to_where': str(location_to), 'live_drag_object': gsi_utils.format_object_name(live_drag_object), 'live_drag_object_id': live_drag_object_id, 'live_drag_definition_id': definition_id, 'live_drag_target': gsi_utils.format_object_name(live_drag_target), 'live_drag_status': str(can_live_drag), 'live_drag_object_inventory': str(current_inventory), 'live_drag_stack_id': stack_id, 'live_drag_stack_count': stack_count}
    live_drag_archiver.archive(data=entry)

