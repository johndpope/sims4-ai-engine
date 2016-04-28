from _weakrefset import WeakSet
import weakref
from event_testing.tests import TunableTestSet
from interactions import ParticipantType
from interactions.context import InteractionContext, QueueInsertStrategy
from interactions.interaction_finisher import FinishingType
from interactions.liability import Liability
from interactions.priority import Priority
from interactions.utils.routing import FollowPath
from objects.components.line_of_sight_component import LineOfSight
from sims4.geometry import PolygonFootprint
from sims4.localization import TunableLocalizedStringFactory
from sims4.service_manager import Service
from sims4.tuning.tunable import TunableFactory, Tunable, TunableReference
import placement
import routing
import services
import sims4.geometry
import sims4.log
import snippets
logger = sims4.log.Logger('Privacy')

class PrivacyService(Service):
    __qualname__ = 'PrivacyService'

    def __init__(self):
        self._privacy_instances = weakref.WeakSet()

    @property
    def privacy_instances(self):
        return self._privacy_instances

    def check_for_late_violators(self, sim):
        for privacy in self.privacy_instances:
            if not sim in privacy.violators:
                if sim in privacy.late_violators:
                    pass
                if sim not in privacy.find_violating_sims():
                    pass
                privacy.handle_late_violator(sim)
                return True
        return False

    def add_instance(self, instance):
        self._privacy_instances.add(instance)

    def remove_instance(self, instance):
        self.privacy_instances.remove(instance)

    def stop(self):
        while self.privacy_instances:
            instance = self.privacy_instances.pop()
            instance.cleanup_privacy_instance()

class Privacy(LineOfSight):
    __qualname__ = 'Privacy'
    _PRIVACY_FOOTPRINT_TYPE = 5
    _PRIVACY_DISCOURAGEMENT_COST = routing.get_default_discouragement_cost()
    _SHOO_CONSTRAINT_RADIUS = Tunable(description='\n        The radius of the constraint a Shooed Sim will attempt to route to.\n        ', tunable_type=float, default=2.5)
    _UNAVAILABLE_TOOLTIP = TunableLocalizedStringFactory(description='\n        Tooltip displayed when an object is not accessible due to being inside\n        a privacy region.\n        ')
    _EMBARRASSED_AFFORDANCE = TunableReference(description='\n        The affordance a Sim will play when getting embarrassed by walking in\n        on a privacy situation.\n        ', manager=services.affordance_manager())

    def __init__(self, interaction, tests, max_line_of_sight_radius, map_divisions, simplification_ratio, boundary_epsilon, facing_offset):
        super().__init__(max_line_of_sight_radius, map_divisions, simplification_ratio, boundary_epsilon)
        self._max_line_of_sight_radius = max_line_of_sight_radius
        self._interaction = interaction
        self._tests = tests
        self._privacy_constraints = []
        self._allowed_sims = WeakSet()
        self._disallowed_sims = WeakSet()
        self._violators = WeakSet()
        self._late_violators = WeakSet()
        self.is_active = False
        self.has_shooed = False
        self.central_object = None
        self._pushed_interactions = []
        services.privacy_service().add_instance(self)

    @property
    def unavailable_tooltip(self):
        return self._UNAVAILABLE_TOOLTIP

    @property
    def interaction(self):
        return self._interaction

    @property
    def is_active(self) -> bool:
        return self._is_active

    @is_active.setter
    def is_active(self, value):
        self._is_active = value

    def _is_sim_allowed(self, sim):
        if self._tests:
            resolver = self._interaction.get_resolver(target=sim)
            if self._tests and self._tests.run_tests(resolver):
                return True
        if self._interaction.can_sim_violate_privacy(sim):
            return True
        return False

    def evaluate_sim(self, sim):
        if self._is_sim_allowed(sim):
            self._allowed_sims.add(sim)
            return True
        self._disallowed_sims.add(sim)
        return False

    def build_privacy(self, target=None):
        self.is_active = True
        target_object = self._interaction.get_participant(ParticipantType.Object)
        target_object = None if target_object.is_sim else target_object
        self.central_object = target_object or (target or self._interaction.sim)
        self.generate(self.central_object.position, self.central_object.routing_surface)
        for poly in self.constraint.geometry.polygon:
            self._privacy_constraints.append(PolygonFootprint(poly, routing_surface=self._interaction.sim.routing_surface, cost=self._PRIVACY_DISCOURAGEMENT_COST, footprint_type=self._PRIVACY_FOOTPRINT_TYPE, enabled=True))
        self._allowed_sims.update(self._interaction.get_participants(ParticipantType.AllSims))
        for sim in services.sim_info_manager().instanced_sims_gen():
            while sim not in self._allowed_sims:
                self.evaluate_sim(sim)
        violating_sims = self.find_violating_sims()
        self._cancel_unavailable_interactions(violating_sims)
        self._add_overrides_and_constraints_if_needed(violating_sims)

    def cleanup_privacy_instance(self):
        if self.is_active:
            self.is_active = False
            for sim in self._allowed_sims:
                self.remove_override_for_sim(sim)
            for sim in self._late_violators:
                self.remove_override_for_sim(sim)
            del self._privacy_constraints[:]
            self._allowed_sims.clear()
            self._disallowed_sims.clear()
            self._violators.clear()
            self._late_violators.clear()
            self._cancel_pushed_interactions()

    def remove_privacy(self):
        self.cleanup_privacy_instance()
        services.privacy_service().remove_instance(self)

    def intersects_with_object(self, obj):
        if obj.routing_surface != self.central_object.routing_surface:
            return False
        delta = obj.position - self.central_object.position
        distance = delta.magnitude_2d_squared()
        if distance > self.max_line_of_sight_radius*self.max_line_of_sight_radius:
            return False
        object_footprint = obj.footprint_polygon
        if object_footprint is None:
            object_footprint = sims4.geometry.Polygon([obj.position])
        for poly in self.constraint.geometry.polygon:
            intersection = poly.intersect(object_footprint)
            while intersection is not None and intersection.has_enough_vertices:
                return True
        return False

    def find_violating_sims(self):
        if not self.is_active:
            return []
        nearby_sims = placement.get_nearby_sims(self.central_object.position, self.central_object.routing_surface.secondary_id, radius=self.max_line_of_sight_radius, exclude=self._allowed_sims, only_sim_position=True)
        violators = []
        for sim in nearby_sims:
            if any(sim_primitive.is_traversing_portal() for sim_primitive in sim.primitives if isinstance(sim_primitive, FollowPath)):
                pass
            if sim not in self._disallowed_sims and self.evaluate_sim(sim):
                pass
            while sims4.geometry.test_point_in_compound_polygon(sim.position, self.constraint.geometry.polygon):
                violators.append(sim)
        return violators

    def _add_overrides_and_constraints_if_needed(self, violating_sims):
        for sim in self._allowed_sims:
            self.add_override_for_sim(sim)
        for sim in violating_sims:
            self._violators.add(sim)
            liabilities = ((SHOO_LIABILITY, ShooLiability(self, sim)),)
            result = self._route_sim_away(sim, liabilities=liabilities)
            while result:
                self._pushed_interactions.append(result.interaction)

    def _cancel_unavailable_interactions(self, violating_sims):
        for sim in violating_sims:
            interactions_to_cancel = set()
            if sim.queue.running is not None:
                interactions_to_cancel.add(sim.queue.running)
            for interaction in sim.si_state:
                while interaction.is_super and interaction.target is not None and sim.locked_from_obj_by_privacy(interaction.target):
                    interactions_to_cancel.add(interaction)
            for interaction in sim.queue:
                if interaction.target is not None and sim.locked_from_obj_by_privacy(interaction.target):
                    interactions_to_cancel.add(interaction)
                else:
                    while interaction.target is not None:
                        break
            for interaction in interactions_to_cancel:
                interaction.cancel(FinishingType.INTERACTION_INCOMPATIBILITY, cancel_reason_msg='Canceled due to incompatibility with privacy instance.')

    def _route_sim_away(self, sim, liabilities=()):
        context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.High, insert_strategy=QueueInsertStrategy.NEXT)
        from interactions.utils.satisfy_constraint_interaction import BuildAndForceSatisfyShooConstraintInteraction
        result = sim.push_super_affordance(BuildAndForceSatisfyShooConstraintInteraction, None, context, liabilities=liabilities, privacy_inst=self, name_override='BuildShooFromPrivacy')
        if not result:
            logger.debug('Failed to push BuildAndForceSatisfyShooConstraintInteraction on Sim {} to route them out of a privacy area.  Result: {}', sim, result, owner='tastle')
            self.interaction.cancel(FinishingType.TRANSITION_FAILURE, cancel_reason_msg='Failed to shoo Sims away.')
        return result

    def _cancel_pushed_interactions(self):
        for interaction in self._pushed_interactions:
            interaction.cancel(FinishingType.AUTO_EXIT, cancel_reason_msg='Privacy finished and is cleaning up.')
        self._pushed_interactions.clear()

    def handle_late_violator(self, sim):
        self._cancel_unavailable_interactions((sim,))
        self.add_override_for_sim(sim)
        liabilities = ((LATE_SHOO_LIABILITY, LateShooLiability(self, sim)),)
        result = self._route_sim_away(sim, liabilities=liabilities)
        if not result:
            return
        if not self._violators:
            context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.High, insert_strategy=QueueInsertStrategy.NEXT)
            result = sim.push_super_affordance(self._EMBARRASSED_AFFORDANCE, self.interaction.get_participant(ParticipantType.Actor), context)
            if not result:
                logger.error('Failed to push the embarrassed affordance on Sim {}. Interaction {}. Result {}. Context {} ', sim, self.interaction, result, context, owner='tastle')
                return
        self._late_violators.add(sim)

    def add_override_for_sim(self, sim):
        for footprint in self._privacy_constraints:
            sim.routing_context.ignore_footprint_contour(footprint.footprint_id)

    def remove_override_for_sim(self, sim):
        for footprint in self._privacy_constraints:
            sim.routing_context.remove_footprint_contour_override(footprint.footprint_id)

    @property
    def allowed_sims(self):
        return self._allowed_sims

    @property
    def disallowed_sims(self):
        return self._disallowed_sims

    @property
    def violators(self):
        return self._violators

    def remove_violator(self, sim):
        self.remove_override_for_sim(sim)
        self._violators.discard(sim)

    @property
    def late_violators(self):
        return self._late_violators

    def remove_late_violator(self, sim):
        self.remove_override_for_sim(sim)
        self._late_violators.discard(sim)

class TunablePrivacy(TunableFactory):
    __qualname__ = 'TunablePrivacy'
    FACTORY_TYPE = Privacy

    def __init__(self, description='Generate a privacy region for this object', callback=None, **kwargs):
        super().__init__(tests=TunableTestSet(description='Any Sim who passes these tests will be allowed to violate the privacy region.'), max_line_of_sight_radius=Tunable(float, 5, description='The maximum possible distance from this object than an interaction can reach.'), map_divisions=Tunable(int, 30, description='The number of points around the object to check collision from.  More points means higher accuracy.'), simplification_ratio=Tunable(float, 0.25, description='A factor determining how much to combine edges in the line of sight polygon.'), boundary_epsilon=Tunable(float, 0.01, description='The LOS origin is allowed to be outside of the boundary by this amount.'), facing_offset=Tunable(float, 0.1, description='The LOS origin is offset from the object origin by this amount (mainly to avoid intersecting walls).'), description=description, **kwargs)

(_, TunablePrivacySnippet) = snippets.define_snippet('Privacy', TunablePrivacy())
SHOO_LIABILITY = 'ShooLiability'

class ShooLiability(Liability):
    __qualname__ = 'ShooLiability'

    def __init__(self, privacy, sim):
        self._privacy = privacy
        self._sim = sim

    def release(self):
        if self._privacy.is_active:
            if self._sim in self._privacy.find_violating_sims():
                self._privacy.interaction.cancel(FinishingType.LIABILITY, cancel_reason_msg='Shoo. Failed to route away from privacy region.')
            else:
                self._privacy.remove_violator(self._sim)

LATE_SHOO_LIABILITY = 'LateShooLiability'

class LateShooLiability(Liability):
    __qualname__ = 'LateShooLiability'

    def __init__(self, privacy, sim):
        self._privacy = privacy
        self._sim = sim

    def release(self):
        if self._privacy.is_active:
            if self._sim in self._privacy.find_violating_sims():
                self._privacy.interaction.cancel(FinishingType.LIABILITY, cancel_reason_msg='Late Shoo. Failed to route away from privacy region.')
            else:
                self._privacy.remove_late_violator(self._sim)

    def on_reset(self):
        self.release()

    def transfer(self, interaction):
        if not self._privacy.is_active:
            interaction.cancel(FinishingType.LIABILITY, cancel_reason_msg='Late Shoo. Continuation canceled.')

