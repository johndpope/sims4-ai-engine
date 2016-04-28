from build_buy import get_stair_count
from objects.portal import Portal
from protocolbuffers import Routing_pb2 as routing_protocols
from interactions.utils.routing import WalkStyle
import sims4.geometry
import sims4.utils
import routing

class Stairs(Portal):
    __qualname__ = 'Stairs'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._footprints = []
        self._cached_lanes = None

    def portal_cleanup(self):
        super().portal_cleanup()
        self._footprints = []
        self._cached_lanes = None

    def on_buildbuy_exit(self):
        super().on_buildbuy_exit()
        if self._has_changed():
            self.portal_cleanup()
            self.portal_setup()

    def _build_discouragement_footprint(self, start, end, surface, offset):
        fwd = start - end
        fwd.y = 0
        fwd = sims4.math.vector_normalize(fwd)
        cross = sims4.math.vector_cross(fwd, sims4.math.Vector3.Y_AXIS())
        width = 0.05
        length = 0.5
        pos = start - cross*0.25*offset
        vertices = []
        vertices.append(pos - width*cross)
        vertices.append(pos - width*cross + length*fwd)
        vertices.append(pos + width*cross + length*fwd)
        vertices.append(pos + width*cross)
        poly = sims4.geometry.Polygon(vertices)
        return sims4.geometry.PolygonFootprint(poly, routing_surface=surface, cost=routing.get_default_discouragement_cost(), footprint_type=6, enabled=True)

    def _has_changed(self):
        if self._cached_lanes is None:
            return True
        stair_lanes = routing.get_stair_portals(self.id, self.zone_id)
        if len(stair_lanes) != len(self._cached_lanes):
            return True
        for (lane1, lane2) in zip(stair_lanes, self._cached_lanes):
            for (end1, end2) in zip(lane1, lane2):
                while not sims4.math.vector3_almost_equal(end1[0][0], end2[0][0]) or not sims4.math.vector3_almost_equal(end1[1][0], end2[1][0]):
                    return True
        return False

    def portal_setup(self):
        super().portal_setup()
        stair_lanes = routing.get_stair_portals(self.id, self.zone_id)
        self._cached_lanes = stair_lanes
        for lane in stair_lanes:
            created_portals = []
            for end_set in lane:
                lane_start = end_set[0]
                lane_end = end_set[1]
                start_pos = lane_start[0]
                end_pos = lane_end[0]
                diff = start_pos - end_pos
                traversal_cost = diff.magnitude()*4.0
                created_portals.append(self.create_portal(routing.Location(start_pos, routing_surface=lane_start[1]), routing.Location(end_pos, routing_surface=lane_end[1]), Portal.PortalType.PortalType_Animate, self.id, traversal_cost))
            self.add_pair(*created_portals)

    def _traversing_up(self, portal_id):
        for p in self.portals:
            while portal_id == p.there:
                return True
        return False

    def _get_stairs_walkstyle(self, walkstyle, traversing_up):
        if walkstyle == WalkStyle.RUN or walkstyle == WalkStyle.JOG:
            if traversing_up:
                return WalkStyle.get_hash(WalkStyle.RUNSTAIRSUP)
            return WalkStyle.get_hash(WalkStyle.RUNSTAIRSDOWN)
        elif walkstyle == sims4.hash_util.hash32('walkreaper'):
            if traversing_up:
                return sims4.hash_util.hash32('reaperstairsup')
            return sims4.hash_util.hash32('reaperstairsdown')
        else:
            if traversing_up:
                return WalkStyle.get_hash(WalkStyle.STAIRSUP)
            return WalkStyle.get_hash(WalkStyle.STAIRSDOWN)

    @sims4.utils.exception_protected(1)
    def c_api_get_portal_duration(self, portal_id, walkstyle, age, gender):
        stairs_walkstyle = self._get_stairs_walkstyle(walkstyle, self._traversing_up(portal_id))
        (duration, _distance) = routing.get_walkstyle_info(stairs_walkstyle, age, gender)
        return duration*get_stair_count(self.id, self.zone_id)

    def add_portal_data(self, portal_id, actor, walkstyle):
        op = routing_protocols.RouteStairsData()
        op.traversing_up = self._traversing_up(portal_id)
        op.stair_count = get_stair_count(self.id, self.zone_id)
        op.walkstyle = self._get_stairs_walkstyle(walkstyle, op.traversing_up)
        op.stairs_per_cycle = 1
        node_data = routing_protocols.RouteNodeData()
        node_data.type = routing_protocols.RouteNodeData.DATA_STAIRS
        node_data.data = op.SerializeToString()
        return node_data

