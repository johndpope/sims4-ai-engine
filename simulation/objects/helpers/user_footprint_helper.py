from interactions.context import InteractionContext, QueueInsertStrategy
from interactions.priority import Priority
from postures import PostureTrack, PostureEvent
from sims4.geometry import PolygonFootprint, build_rectangle_from_two_points_and_radius
from sims4.math import vector3_almost_equal
from sims4.sim_irq_service import yield_to_irq
from sims4.tuning.tunable import Tunable, TunableReference
import placement
import routing
import services
import sims4.log
logger = sims4.log.Logger('Television')
FP_REMOVED_BY_POSTURE = 1
FP_REMOVED_BY_ROUTING = 2

def get_object_translation(obj):
    return obj.location.transform.translation

class UserFootprintHelper:
    __qualname__ = 'UserFootprintHelper'
    DEFAULT_DISCOURAGE_AREA_WIDTH = Tunable(float, 0.3, description='The default width of discouragement regions placed from a Sim to an object.')
    DEFAULT_DISCOURAGE_AREA_COST = Tunable(float, 1, description='The cost of routing between a Sim and an object.')
    MOVE_SIM_AFFORDANCE = TunableReference(services.affordance_manager(), description='\n                                When a Sim A places a discouragement region and Sim B\n                                is already inside of that discouragement region, Sim B\n                                gets MOVE_SIM_AFFORDANCE pushed on them.\n                                ')

    def __init__(self, owner=None, width=None, cost=None, get_focus_fn=None, get_enabled_fn=None):
        self._owner = owner.ref() if hasattr(owner, 'ref') else owner
        if get_focus_fn is None and hasattr(owner, 'register_on_location_changed'):
            owner.register_on_location_changed(self.refresh)
        self._get_focus = get_focus_fn or (lambda : get_object_translation(owner))
        self._get_enabled = get_enabled_fn or (lambda : True)
        self._radius = (width or UserFootprintHelper.DEFAULT_DISCOURAGE_AREA_WIDTH)/2
        self._cost = max(cost or UserFootprintHelper.DEFAULT_DISCOURAGE_AREA_COST, routing.get_default_discouragement_cost())
        self._footprints = {}
        self._focus = None

    def __repr__(self):
        return 'UserFootprintHelper(owner={owner}, width={_radius} * 2, cost={_cost}, get_focus_fn={_get_focus}, get_enabled_fn={_get_enabled})'.format(owner=self.owner, **self.__dict__)

    @property
    def owner(self):
        if callable(self._owner):
            return self._owner()
        return self._owner

    def add_user(self, sim):
        if sim in self._footprints:
            raise RuntimeError('Multiple calls to add_user() without calling remove_user().')
        self._add_user_footprint(sim)
        sim.on_posture_event.append(self._on_sim_posture_event)
        sim.on_follow_path.append(self._on_sim_follow_path)

    def remove_user(self, sim):
        if sim not in self._footprints:
            return
        if isinstance(self._footprints[sim], PolygonFootprint):
            sim.routing_context.remove_footprint_contour_override(self._footprints[sim].footprint_id)
        del self._footprints[sim]
        sim.on_posture_event.remove(self._on_sim_posture_event)
        sim.on_follow_path.remove(self._on_sim_follow_path)

    def is_user(self, sim):
        return sim in self._footprints

    def refresh(self, *_, **__):
        new_focus = self._get_focus()
        if self._focus is not None and vector3_almost_equal(self._focus, new_focus):
            for fp in self._footprints.values():
                while isinstance(fp, PolygonFootprint):
                    fp.enabled = self._get_enabled()
        else:
            self._focus = new_focus
            for (sim, fp) in list(self._footprints.items()):
                while isinstance(fp, PolygonFootprint):
                    self._add_user_footprint(sim)

    def _add_user_footprint(self, sim):
        if self._focus is None:
            self._focus = self._get_focus()
        p = build_rectangle_from_two_points_and_radius(self._focus, get_object_translation(sim), self._radius)
        self._footprints[sim] = PolygonFootprint(p, routing_surface=sim.routing_surface, cost=self._cost, enabled=self._get_enabled())
        if self._get_enabled():
            self.force_move_sims_in_polygon(p, sim.routing_surface, exclude=[sim])
        sim.routing_context.ignore_footprint_contour(self._footprints[sim].footprint_id)

    @staticmethod
    def force_move_sims_in_polygon(polygon, routing_surface, exclude=[]):
        nearby_sims = placement.get_nearby_sims(polygon.centroid(), routing_surface.secondary_id, radius=polygon.radius(), exclude=exclude)
        for near_sim in nearby_sims:
            while sims4.geometry.test_point_in_polygon(near_sim.position, polygon):
                total_constraint = near_sim.si_state.get_total_constraint(include_inertial_sis=True, force_inertial_sis=True)
                (single_point, _) = total_constraint.single_point()
                if single_point is not None:
                    pass
                push_route_away(near_sim)

    def _on_sim_posture_event(self, change, dest_state, track, old_posture, new_posture):
        if not PostureTrack.is_body(track):
            return
        yield_to_irq()
        posture = new_posture or old_posture
        sim = posture.sim
        if change == PostureEvent.TRANSITION_START:
            if isinstance(self._footprints.get(sim), PolygonFootprint):
                sim.routing_context.remove_footprint_contour_override(self._footprints[sim].footprint_id)
                self._footprints[sim] = FP_REMOVED_BY_POSTURE
        elif change == PostureEvent.TRANSITION_COMPLETE and self._footprints.get(sim) == FP_REMOVED_BY_POSTURE:
            self._add_user_footprint(sim)

    def _on_sim_follow_path(self, follow_path, starting):
        sim = follow_path.actor
        if starting:
            if isinstance(self._footprints.get(sim), PolygonFootprint):
                sim.routing_context.remove_footprint_contour_override(self._footprints[sim].footprint_id)
                self._footprints[sim] = FP_REMOVED_BY_ROUTING
        elif self._footprints.get(sim) == FP_REMOVED_BY_ROUTING:
            self._add_user_footprint(sim)

def push_route_away(sim):
    context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.High, insert_strategy=QueueInsertStrategy.NEXT, must_run_next=True, cancel_if_incompatible_in_queue=True)
    sim.push_super_affordance(UserFootprintHelper.MOVE_SIM_AFFORDANCE, sim, context, name_override='MoveSimFromDiscouragementRegion')

