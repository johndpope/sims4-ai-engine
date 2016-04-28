from objects.components.welcome_component import FrontDoorTuning
from routing import SURFACETYPE_WORLD
from routing.connectivity import Handle
from sims.sim_info_types import SimInfoSpawnerTags
import build_buy
import objects.doors.door
import routing
import services
import sims4
logger = sims4.log.Logger('FrontDoor')

class DoorConnectivityHandle(Handle):
    __qualname__ = 'DoorConnectivityHandle'

    def __init__(self, owning_door, location, routing_surface, **kwargs):
        super().__init__(location, routing_surface, **kwargs)
        self._owner = owning_door

    @property
    def owner(self):
        return self._owner

def enable_front_door(door, valid_door):
    front_door_state = FrontDoorTuning.FRONT_DOOR_DISABLED_STATE.state
    if valid_door:
        door.set_state(front_door_state, FrontDoorTuning.FRONT_DOOR_ENABLED_STATE)
    else:
        door.set_state(front_door_state, FrontDoorTuning.FRONT_DOOR_DISABLED_STATE)

def remove_front_door(front_door_id):
    if front_door_id is None:
        return
    current_front_door = services.object_manager().get(front_door_id)
    current_front_door.unset_as_front_door()

def _find_and_set_front_door():
    zone = services.current_zone()
    if zone is None:
        return
    active_lot = zone.lot
    if active_lot is None:
        return
    venue_instance = zone.venue_service.venue
    if (venue_instance is None or not venue_instance.venue_requires_front_door) and active_lot.owner_household_id == 0:
        return
    source_point = None
    spawn_point = zone.active_lot_arrival_spawn_point
    if spawn_point is None:
        source_point = active_lot.corners[1]
        logger.warn('FindFrontDoor: There are no arrival spawn points on lot {}, will use lot corners as fallback, this will generate abnormal front door behavior', active_lot.lot_id, owner='camilogarcia')
    else:
        source_point = spawn_point.center
    source_handles = set()
    source_handle = Handle(source_point, routing.SurfaceIdentifier(zone.id, 0, SURFACETYPE_WORLD))
    source_handles.add(source_handle)
    routing_context = routing.PathPlanContext()
    lot_doors = set()
    for obj in services.object_manager().valid_objects():
        while isinstance(obj, objects.doors.door.Door) and obj.is_door_portal:
            lot_doors.add(obj)
            while True:
                for portal_handle in obj.portals:
                    routing_context.lock_portal(portal_handle.there)
                    routing_context.lock_portal(portal_handle.back)
    dest_handles = set()
    for obj in lot_doors:
        if obj.portals is None or len(obj.portals) == 0:
            enable_front_door(obj, False)
        if obj.front_pos is None:
            logger.error("Door '{}' has broken portals, ignoring as front door", obj)
        is_front_outside = False
        portals_p0 = routing.get_portals_in_connectivity_path(source_handle, Handle(obj.front_pos, obj.routing_surface), routing_context)
        if verify_outside_portal(zone, portals_p0):
            dest_handles.add(DoorConnectivityHandle(obj, obj.front_pos, obj.routing_surface))
            is_front_outside = True
        portals_p1 = routing.get_portals_in_connectivity_path(source_handle, Handle(obj.back_pos, obj.routing_surface), routing_context)
        if verify_outside_portal(zone, portals_p1):
            dest_handles.add(DoorConnectivityHandle(obj, obj.back_pos, obj.routing_surface))
            if not is_front_outside:
                obj.swap_there_and_back()
        enable_front_door(obj, False)
    if not source_handles or not dest_handles:
        remove_front_door(active_lot.front_door_id)
        return
    connections = routing.test_connectivity_batch(source_handles, dest_handles, compute_cost=True)
    min_cost = None
    candidate_doors = []
    if not connections:
        remove_front_door(active_lot.front_door_id)
        return
    for connection in connections:
        (_, dest_handle, cost) = connection
        if min_cost == None or min_cost > cost:
            min_cost = cost
            candidate_doors = [dest_handle.owner]
        elif min_cost == cost:
            candidate_doors.append(dest_handle.owner)
        enable_front_door(dest_handle.owner, True)
    if active_lot.front_door_id is not None:
        current_front_door = services.object_manager().get(active_lot.front_door_id)
        if current_front_door is not None and current_front_door in candidate_doors:
            return current_front_door
    selected_door = None
    if len(candidate_doors) == 1:
        selected_door = candidate_doors.pop()
    else:
        min_dist = None
        for door in candidate_doors:
            dist = (source_point - door.position).magnitude_squared()
            while min_dist == None or min_dist > dist:
                selected_door = door
                min_dist = dist
    selected_door.set_as_front_door()
    return selected_door

def find_and_set_front_door():
    new_front_door = _find_and_set_front_door()
    services.object_manager().on_front_door_candidates_changed()
    return new_front_door

def verify_outside_portal(zone, portals):
    if portals is None:
        return False
    result_handles = set()
    for portal_id in portals:
        portal_obj = zone.find_object(portal_id)
        while isinstance(portal_obj, objects.doors.door.Door) and portal_obj.is_door_portal:
            result_handles.add(portal_id)
    if not result_handles:
        return True
    return False

def load_front_door(front_door_id):
    front_door = services.object_manager().get(front_door_id)
    if front_door is not None:
        front_door.set_as_front_door()
    else:
        logger.warn('Front door object id saved was not found in manager, finding a new front door')
        find_and_set_front_door()

@sims4.commands.Command('front_door.recalculate_front_door')
def recalculate_front_door(_connection=None):
    door = find_and_set_front_door()
    if door is None:
        sims4.commands.output('No valid front door found', _connection)
    else:
        sims4.commands.output('Front door found.  Door {} on position {}'.format(str(door), door.position), _connection)

@sims4.commands.Command('front_door.set_front_door')
def set_front_door(obj_id, _connection=None):
    door = services.object_manager().get(obj_id)
    if door is not None and isinstance(door, objects.doors.door.Door) and door.is_door_portal:
        door.set_as_front_door()
        sims4.commands.output('Object {} set as front door'.format(str(door)), _connection)
    else:
        sims4.commands.output('Object {} is not a door, no door will be set'.format(str(door)), _connection)

@sims4.commands.Command('front_door.validate_front_door')
def validate_front_door(_connection=None):
    active_lot = lot = services.active_lot()
    if active_lot is None:
        return
    door_id = active_lot.front_door_id
    if door_id is None:
        sims4.commands.output('Lot has no front door set', _connection)
    else:
        door = services.object_manager().get(door_id)
        if door is None:
            sims4.commands.output('Lot has a front door with an id of an object that doesnt exist', _connection)
        else:
            sims4.commands.output('Front door found.  Door {} on position {}'.format(str(door), door.position), _connection)

