from event_testing.results import TestResult
from interactions.base.immediate_interaction import ImmediateSuperInteraction
from objects.components import types
from objects.components.welcome_component import WelcomeComponent
from objects.portal import Portal
from protocolbuffers import Routing_pb2 as routing_protocols
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.tunable import Tunable
import distributor.fields
import distributor.ops
import routing
import services
import sims4.math
import terrain

class Door(Portal):
    __qualname__ = 'Door'
    FRONT_DOOR_WELCOME_COMPONENT = WelcomeComponent.TunableFactory()
    MAX_DOOR_PORTAL_HEIGHT_VARIATION = 0.25
    INSTANCE_TUNABLES = {'is_door_portal': Tunable(description='\n            Is this a valid door.\n            Should be false for arches, gates and other non lockable door portals.\n            ', tunable_type=bool, default=False)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor_type = 2935391323
        self.statemachine = 'Door_OpenClose'
        self._footprints = []
        self.front_pos = None
        self.back_pos = None
        self._was_valid = False

    def portal_cleanup(self):
        super().portal_cleanup()
        self._footprints = []

    def on_remove(self):
        active_lot = services.active_lot()
        if active_lot.front_door_id == self.id:
            active_lot.front_door_id = None
        super().on_remove()

    @distributor.fields.Field(op=distributor.ops.SetActorType, priority=distributor.fields.Field.Priority.HIGH)
    def actor_type(self):
        return self._actor_type

    @actor_type.setter
    def actor_type(self, value):
        self._actor_type = value

    @distributor.fields.Field(op=distributor.ops.SetActorStateMachine)
    def statemachine(self):
        return self._statemachine

    @statemachine.setter
    def statemachine(self, value):
        self._statemachine = value

    def _build_discouragement_footprint(self, start, end, surface, offset):
        fwd = start - end
        fwd.y = 0
        fwd = sims4.math.vector_normalize(fwd)
        cross = sims4.math.vector_cross(fwd, sims4.math.Vector3.Y_AXIS())
        width = 0.05
        length = 0.5
        pos = start - cross*0.5*offset
        vertices = []
        vertices.append(pos - width*cross - length*fwd)
        vertices.append(pos - width*cross + length*fwd)
        vertices.append(pos + width*cross + length*fwd)
        vertices.append(pos + width*cross - length*fwd)
        poly = sims4.geometry.Polygon(vertices)
        return sims4.geometry.PolygonFootprint(poly, routing_surface=surface, cost=routing.get_default_discouragement_cost(), footprint_type=6, enabled=True)

    def _get_positions(self):
        pos = self.transform.translation
        orient = self.transform.orientation
        offset = orient.transform_vector(sims4.math.Vector3(0.0, 0.0, 0.3))
        cross = orient.transform_vector(sims4.math.Vector3(0.05, 0.0, 0.0))
        p0 = pos + offset
        p1 = pos - offset
        p0.y = terrain.get_lot_level_height(p0.x, p0.z, self.routing_surface.secondary_id, self.routing_surface.primary_id)
        p1.y = terrain.get_lot_level_height(p1.x, p1.z, self.routing_surface.secondary_id, self.routing_surface.primary_id)
        return (p0, p1, cross)

    def _is_valid(self):
        pos = self.transform.translation
        (p0, p1, cross) = self._get_positions()
        if abs(pos.y - p1.y) > Door.MAX_DOOR_PORTAL_HEIGHT_VARIATION or abs(pos.y - p0.y) > Door.MAX_DOOR_PORTAL_HEIGHT_VARIATION:
            return False
        return True

    def portal_setup(self):
        super().portal_setup()
        self.portal_cleanup()
        if not self._is_valid():
            self._was_valid = False
            return
        self._was_valid = True
        pos = self.transform.translation
        (p0, p1, cross) = self._get_positions()
        door_routing_surface = self.routing_surface
        self.front_pos = p0
        self.back_pos = p1
        there = self.create_portal(routing.Location(p0 + cross, routing_surface=door_routing_surface), routing.Location(p1 + cross, routing_surface=door_routing_surface), Portal.PortalType.PortalType_Walk, self.id)
        back = self.create_portal(routing.Location(p1 - cross, routing_surface=door_routing_surface), routing.Location(p0 - cross, routing_surface=door_routing_surface), Portal.PortalType.PortalType_Walk, self.id)
        self.add_pair(there, back)
        self._footprints.append(self._build_discouragement_footprint(pos, p1, door_routing_surface, 1.0))
        self._footprints.append(self._build_discouragement_footprint(pos, p1, door_routing_surface, -1.0))

    def add_portal_events(self, portal, actor, time, route_pb):
        op = routing_protocols.PortalEnterEvent()
        op.portal_object_id = self.id
        op.entering_front = portal == self.portals[0].there
        event = route_pb.events.add()
        event.time = time - 1.0
        event.type = routing_protocols.RouteEvent.PORTAL_ENTER
        event.data = op.SerializeToString()
        op = routing_protocols.PortalExitEvent()
        op.portal_object_id = self.id
        event = route_pb.events.add()
        event.time = time + 3.0
        event.type = routing_protocols.RouteEvent.PORTAL_EXIT
        event.data = op.SerializeToString()

    def on_buildbuy_exit(self):
        super().on_buildbuy_exit()
        is_valid = self._is_valid()
        if self._was_valid:
            if not is_valid:
                self.portal_cleanup()
        elif is_valid:
            self.portal_setup()
        self._was_valid = is_valid

    def set_as_front_door(self):
        active_lot = services.active_lot()
        current_door_id = active_lot.front_door_id
        if current_door_id == self.id:
            return
        if current_door_id is not None:
            door = services.object_manager().get(current_door_id)
            door.remove_component(types.WELCOME_COMPONENT.instance_attr)
        self.add_dynamic_component(types.WELCOME_COMPONENT.instance_attr)
        self.welcome_component.affordance_links = Door.FRONT_DOOR_WELCOME_COMPONENT.affordance_links
        for affordance in self.welcome_component.affordance_links:
            self.add_dynamic_commodity_flags(affordance, affordance.commodity_flags)
        active_lot.front_door_id = self.id

    def unset_as_front_door(self):
        self.remove_component(types.WELCOME_COMPONENT.instance_attr)
        active_lot = services.active_lot()
        active_lot.front_door_id = None

    def swap_there_and_back(self):
        front_pos = self.front_pos
        self.front_pos = self.back_pos
        self.back_pos = front_pos
        super().swap_there_and_back()

class SetFrontDoorImmediateInteraction(ImmediateSuperInteraction):
    __qualname__ = 'SetFrontDoorImmediateInteraction'
    INSTANCE_TUNABLES = {'already_front_door_tooltip': TunableLocalizedStringFactory(description='The greyed out tooltip if a player clicks on a door that is already their front door.')}

    @classmethod
    def _test(cls, target, context, **kwargs):
        if target.welcome_component:
            return TestResult(False, 'This door is already the front door.', tooltip=cls.already_front_door_tooltip)
        return TestResult.TRUE

    def _run_interaction_gen(self, timeline):
        self.target.set_as_front_door()

