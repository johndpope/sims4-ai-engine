from server.live_drag_tuning import LiveDragLocation
import gsi_handlers
import services
import sims4.commands
import sims4.log
import sims4.utils
logger = sims4.log.Logger('LiveDragCommands', default_owner='rmccord')

@sims4.commands.Command('live_drag.start', command_type=sims4.commands.CommandType.Live)
def live_drag_start(live_drag_object_id, start_system, is_stack:bool=False, _connection=None):
    current_zone = services.current_zone()
    live_drag_object = current_zone.find_object(live_drag_object_id)
    if gsi_handlers.live_drag_handlers.live_drag_archiver.enabled:
        gsi_handlers.live_drag_handlers.archive_live_drag('Start', 'Command', start_system, LiveDragLocation.GAMEPLAY_SCRIPT, live_drag_object=live_drag_object, live_drag_object_id=live_drag_object_id, live_drag_target=None)
    if live_drag_object is None:
        logger.error('Attempting to Live Drag an object that does not exist. object_id: {}'.format(live_drag_object_id), owner='rmccord')
        sims4.commands.output('Live Drag object with id: {} does not exist.'.format(live_drag_object_id), _connection)
        return
    client = services.client_manager().get_first_client()
    if client is None:
        logger.error('Client is not connected', owner='rmccord')
        sims4.commands.output('Client is not connected.', _connection)
        return
    client.start_live_drag(live_drag_object, start_system, is_stack)

@sims4.commands.Command('live_drag.end', command_type=sims4.commands.CommandType.Live)
def live_drag_end(object_source_id, object_target_id, end_system, _connection=None):
    current_zone = services.current_zone()
    source_object = current_zone.find_object(object_source_id)
    target_object = None
    if object_target_id:
        target_object = current_zone.find_object(object_target_id)
    if gsi_handlers.live_drag_handlers.live_drag_archiver.enabled:
        gsi_handlers.live_drag_handlers.archive_live_drag('End', 'Command', end_system, LiveDragLocation.GAMEPLAY_SCRIPT, live_drag_object=source_object, live_drag_object_id=object_source_id, live_drag_target=target_object)
    if source_object is None:
        logger.error('Ending Live Drag with an object that does not exist. object_id: {}'.format(object_source_id), owner='rmccord')
        sims4.commands.output('Live Drag object with id: {} does not exist.'.format(object_source_id), _connection)
        return
    if target_object is None and object_target_id:
        logger.error('Ending Live Drag with a drop target that does not exist. object_id: {}'.format(object_target_id), owner='rmccord')
        sims4.commands.output('Live Drag target object with id: {} does not exist.'.format(object_target_id), _connection)
        return
    client = services.client_manager().get_first_client()
    if client is None:
        logger.error('Client is not connected', owner='rmccord')
        sims4.commands.output('Client is not connected.', _connection)
        return
    client.end_live_drag(source_object, target_object, end_system)

@sims4.utils.exception_protected(-1)
def c_api_live_drag_end(zone_id, obj_id, routing_surface, transform, parent_id, joint_name_or_hash, slot_hash):
    with sims4.zone_utils.global_zone_lock(zone_id):
        current_zone = services.current_zone()
        obj = current_zone.find_object(obj_id)
        client = services.client_manager().get_first_client()
        if client is None:
            logger.error('Client is not connected', owner='rmccord')
            return
        if obj is None:
            sims4.log.error('BuildBuy', 'Trying to place an invalid object id: {}', obj_id, owner='rmccord')
            return
        if parent_id:
            parent_obj = current_zone.find_object(parent_id)
            if parent_obj is None:
                sims4.log.error('BuildBuy', 'Trying to parent an object to an invalid object id: {}', obj_id, owner='rmccord')
                client.cancel_live_drag(obj, LiveDragLocation.BUILD_BUY)
                return
            location = sims4.math.Location(transform, routing_surface, parent_obj, joint_name_or_hash, slot_hash)
        else:
            location = sims4.math.Location(transform, routing_surface)
        if gsi_handlers.live_drag_handlers.live_drag_archiver.enabled:
            gsi_handlers.live_drag_handlers.archive_live_drag('End (C_API)', 'Command', LiveDragLocation.BUILD_BUY, LiveDragLocation.GAMEPLAY_SCRIPT, live_drag_object=obj, live_drag_object_id=obj_id, live_drag_target=None)
        client.end_live_drag(obj, target_object=None, end_system=LiveDragLocation.BUILD_BUY, location=location)
        return obj

@sims4.commands.Command('live_drag.canceled', command_type=sims4.commands.CommandType.Live)
def live_drag_canceled(live_drag_object_id, end_system:LiveDragLocation=LiveDragLocation.INVALID, _connection=None):
    current_zone = services.current_zone()
    live_drag_object = current_zone.find_object(live_drag_object_id)
    if gsi_handlers.live_drag_handlers.live_drag_archiver.enabled:
        gsi_handlers.live_drag_handlers.archive_live_drag('Cancel', 'Command', end_system, LiveDragLocation.GAMEPLAY_SCRIPT, live_drag_object=live_drag_object, live_drag_object_id=live_drag_object_id)
    if live_drag_object is None:
        logger.warn('Canceling Live Drag on an object that does not exist. object_id: {}'.format(live_drag_object_id), owner='rmccord')
        sims4.commands.output('Live Drag object with id: {} does not exist.'.format(live_drag_object_id), _connection)
        return
    client = services.client_manager().get_first_client()
    if client is None:
        logger.error('Client is not connected', owner='rmccord')
        sims4.commands.output('Client is not connected.', _connection)
        return
    client.cancel_live_drag(live_drag_object, end_system)

@sims4.commands.Command('live_drag.sell', command_type=sims4.commands.CommandType.Live)
def live_drag_sell(live_drag_object_id, end_system:LiveDragLocation=LiveDragLocation.GAMEPLAY_UI, _connection=None):
    current_zone = services.current_zone()
    live_drag_object = current_zone.find_object(live_drag_object_id)
    if gsi_handlers.live_drag_handlers.live_drag_archiver.enabled:
        gsi_handlers.live_drag_handlers.archive_live_drag('Sell', 'Command', end_system, LiveDragLocation.GAMEPLAY_SCRIPT, live_drag_object=live_drag_object, live_drag_object_id=live_drag_object_id)
    if live_drag_object is None:
        logger.error('Attempting to Sell an object that does not exist. object_id: {}'.format(live_drag_object_id), owner='rmccord')
        sims4.commands.output('Live Drag object with id: {} does not exist.'.format(live_drag_object_id), _connection)
        return
    client = services.client_manager().get_first_client()
    if client is None:
        logger.error('Client is not connected', owner='rmccord')
        sims4.commands.output('Client is not connected.', _connection)
        return
    client.sell_live_drag_object(live_drag_object, end_system)

