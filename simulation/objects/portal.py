from collections import namedtuple
import weakref
from objects.game_object import GameObject
from protocolbuffers import Routing_pb2 as routing_protocols
from sims4.tuning.tunable import TunableSet, TunableEnumWithFilter
import animation.arb
import enum
import routing
import services
import sims4.math
import sims4.utils
import tag
_PortalPair = namedtuple('_PortalPair', ['there', 'back'])

class Portal(GameObject):
    __qualname__ = 'Portal'
    INSTANCE_TUNABLES = {'portal_disallowance_tags': TunableSet(description="\n                A set of tags that define what the portal disallowance tags of\n                this portal are.  Sim's with role states that also include any\n                of these disallowance tags consider the portal to be locked\n                when routing.\n                ", tunable=TunableEnumWithFilter(description='\n                    A single portal disallowance tag.\n                    ', tunable_type=tag.Tag, default=tag.Tag.INVALID, filter_prefixes=tag.PORTAL_DISALLOWANCE_PREFIX))}

    class PortalType(enum.Int, export=False):
        __qualname__ = 'Portal.PortalType'
        PortalType_Wormhole = 0
        PortalType_Walk = 1
        PortalType_Animate = 2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._portals = []
        self._disallowed_sims = weakref.WeakKeyDictionary()

    @property
    def portals(self):
        return self._portals

    def on_location_changed(self, old_location):
        super().on_location_changed(old_location)
        self.portal_cleanup()
        self.portal_setup()

    def on_add(self):
        super().on_add()
        services.object_manager().add_portal_to_cache(self)

    def on_remove(self):
        super().on_remove()
        self.portal_cleanup()
        services.object_manager().remove_portal_from_cache(self)

    def add_disallowed_sim(self, sim, disallower):
        if sim not in self._disallowed_sims:
            self._disallowed_sims[sim] = set()
        self._disallowed_sims[sim].add(disallower)
        for portal_pair in self._portals:
            sim.routing_context.lock_portal(portal_pair.there)

    def remove_disallowed_sim(self, sim, disallower):
        disallowing_objects = self._disallowed_sims.get(sim)
        if disallowing_objects is None:
            return
        disallowing_objects.remove(disallower)
        if not disallowing_objects:
            for portal_pair in self._portals:
                sim.routing_context.unlock_portal(portal_pair.there)
            del self._disallowed_sims[sim]

    def portal_setup(self):
        if self.portals:
            raise ValueError('Portal: Portals Already Exist.')

    def create_portal(self, start_loc, end_loc, portal_type, portal_id, traversal_cost=0.0):
        return routing.add_portal(start_loc, end_loc, portal_type, portal_id, traversal_cost)

    def add_pair(self, there, back):
        self._portals.append(_PortalPair(there, back))
        for sim in self._disallowed_sims.keys():
            sim.routing_context.lock_portal(there)

    def portal_cleanup(self):
        while self.portals:
            portal_pair = self.portals.pop()
            if portal_pair.there is not None:
                routing.remove_portal(portal_pair.there)
            while portal_pair.back is not None:
                routing.remove_portal(portal_pair.back)
                continue

    def add_portal_events(self, portal, actor, time, route_pb):
        sims4.log.info('Routing', 'Actor:{0} using portal {1} in object {2}', actor, portal, self)

    @sims4.utils.exception_protected(0)
    def c_api_get_portal_duration(self, portal_id, walkstyle, age, gender):
        return 0.0

    def add_portal_data(self, portal, actor, walkstyle):
        pass

    def split_path_on_portal(self):
        return False

    def swap_there_and_back(self):
        old_portals = tuple(self._portals)
        self._portals.clear()
        for portal_pair in old_portals:
            new_portal_pair = _PortalPair(portal_pair.back, portal_pair.there)
            self._portals.append(new_portal_pair)
            for sim in self._disallowed_sims.keys():
                sim.routing_context.lock_portal(new_portal_pair.there)
                sim.routing_context.unlock_portal(new_portal_pair.back)

    def get_portal_element(self, sim):

        def do_portal_transition(e):
            current_surface = sim.routing_surface
            if current_surface == self.object_routing_surface:
                target_surface = self.routing_surface
            else:
                target_surface = self.object_routing_surface
            location = sim.location
            location.routing_surface = target_surface
            transform_vector = location.transform.transform_vector(sims4.math.Vector3(0, 0, 1))
            new_transform = sims4.math.Transform(sim.transform.translation + transform_vector, sim.transform.orientation)
            location.transform = new_transform
            sim.set_location(location)
            return True

        return do_portal_transition

PORTAL_POSITION_OFFSET = 1.5

def get_initial_portal_positions(transform):
    offset = transform.orientation.transform_vector(sims4.math.Vector3(0.0, 0.0, PORTAL_POSITION_OFFSET))
    p0 = transform.translation + offset
    p1 = transform.translation - offset
    return (p0, p1)

