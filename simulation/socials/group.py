#ERROR: jaddr is None
from _weakrefset import WeakSet
from weakref import WeakKeyDictionary
import collections
import itertools
import math
import random
from animation.posture_manifest_constants import STAND_OR_SIT_CONSTRAINT_OUTER_PENALTY, STAND_CONSTRAINT_OUTER_PENALTY, STAND_OR_SIT_CONSTRAINT
from element_utils import build_critical_section_with_finally, unless, build_element
from interactions import priority, ParticipantTypeObject, ParticipantTypeActorTargetSim, ParticipantType
from interactions.constraints import Circle, Anywhere, TunableFacing, Nowhere, Facing, create_constraint_set
from interactions.context import InteractionSource
from interactions.interaction_finisher import FinishingType
from interactions.utils.sim_focus import SimFocus
from objects.components import forward_to_components
from objects.components.state import TunableStateComponent
from objects.components.statistic_component import HasStatisticComponent
from sims.sim import LOSAndSocialConstraintTuning
from sims4 import resources
from sims4.callback_utils import CallableList
from sims4.geometry import CompoundPolygon, RestrictedPolygon
from sims4.sim_irq_service import yield_to_irq
from sims4.tuning.geometric import TunableDistanceSquared
from sims4.tuning.tunable import Tunable, TunableRange, TunableTuple, TunableReference, TunableEnumEntry, TunableRealSecond, OptionalTunable, TunableSimMinute, TunableAngle
from sims4.tuning.tunable_base import GroupNames
from sims4.utils import setdefault_callable
from socials.social_focus_manager import SocialFocusManager
from socials.social_scoring import SocialGroupScoringFunction
import alarms
import build_buy
import clock
import date_and_time
import distributor.ops
import interactions.constraints
import objects.components.line_of_sight_component
import placement
import routing
import services
import sims4.log
import sims4.math
import sims4.tuning.instances
import socials.geometry
import terrain
logger = sims4.log.Logger('Social Group')

def create_social_circle_constraint_around_sim(sim):
    new_polygon = sims4.geometry.generate_circle_constraint(LOSAndSocialConstraintTuning.num_sides_for_circle_expansion_of_point_constraint, sim.position, LOSAndSocialConstraintTuning.constraint_expansion_amount)
    new_compound_polygon = sims4.geometry.CompoundPolygon((new_polygon,))
    new_restricted_polygon = sims4.geometry.RestrictedPolygon(new_compound_polygon, [])
    constraint = interactions.constraints.Constraint(geometry=new_restricted_polygon, routing_surface=sim.routing_surface)
    constraint = constraint.intersect(sim.los_constraint)
    return constraint

def get_fallback_social_constraint_position(sim, target, si, priority=None):
    if priority is None and si is not None:
        priority = si.priority
    sim_constraint = sim.si_state.get_total_constraint(priority=priority, to_exclude=si, existing_si=si)
    for constraint in sim_constraint:
        while constraint.geometry is None:
            return (target.position, target.routing_surface)
    target_constraint = target.si_state.get_total_constraint(priority=priority, to_exclude=si, existing_si=si)
    for constraint in target_constraint:
        while constraint.geometry is None:
            return (sim.position, sim.routing_surface)
    sim_circle = create_social_circle_constraint_around_sim(sim)
    target_circle = create_social_circle_constraint_around_sim(target)
    intersection = sim_circle.intersect(target_circle)
    if not intersection.valid:
        return (None, None)
    return (intersection.average_position, intersection.routing_surface)

SocialGroupLocation = collections.namedtuple('SocialGroupLocation', ('position', 'forward', 'routing_surface'))
SocialGroupMember = collections.namedtuple('SocialGroupMember', ('sim_id', 'social_context_bit'))

class SocialGroup(objects.components.ComponentContainer, HasStatisticComponent, metaclass=sims4.tuning.instances.TunedInstanceMetaclass, manager=services.get_instance_manager(resources.Types.SOCIAL_GROUP)):
    __qualname__ = 'SocialGroup'
    INSTANCE_TUNABLES = {'maximum_sim_count': TunableRange(description='\n            The maximum number of Sims in this social group.', tunable_type=int, default=8, minimum=0), 'minimum_sim_count': TunableRange(description='\n            The minimum number of Sims in this social group; if fewer Sims are\n            in the group it will be destroyed.', tunable_type=int, default=1, minimum=1), 'facing_restriction': TunableFacing(description='\n            Controls how a Sim must face the center of a social group.\n            \n            If the range is less than 360, a Sim will be prohibited from\n            socializing if they face away from the center.  Because mobile\n            Sims can change their facing, this will mostly affect Sims who\n            are socializing while in objects.'), 'adjust_sim_positions_dynamically': Tunable(description='\n            Whether this group should attempt to shift Sims around to maximize\n            placement quality.', tunable_type=bool, default=True), 'max_radius': TunableRange(description='\n            The maximum radius of this social group', tunable_type=float, default=3.0, minimum=1.0), 'radius_scale': TunableRange(description='\n            Determines the baseline radius of the social group.\n            \n            The ideal social group radius increases as the number of Sims\n            increases, based on the formula: radius_scale * sqrt(num_sims / 2).\n            \n            So if there are two Sims, the ideal group will be exactly this size,\n            and if there are four Sims, it will be 1.4142 * radius_scale. \n            ', tunable_type=float, default=0.7, minimum=0), 'line_of_sight': objects.components.line_of_sight_component.TunableLineOfSightComponent(description='\n            A line_of_sight constraint represents an area viewable from a\n            point, so it adapts itself to respect the wall graph. Sims\n            attempting to interact with a group will need to be within this\n            constraint in order to do so.\n            \n            Example: The television has line_of_sight tuned on it. When Sims\n            try to use the television, they will try to route to within the\n            line_of_sight constraint to watch it.  This ensures that Sims\n            cannot watch the television from too far away or through walls.\n            '), 'is_side_group': Tunable(description='\n            If checked, this group represents the sub-set of the sims inside\n            the main social group. It will bring some different social\n            adjustment behavior for sims in the side group.\n            ', tunable_type=bool, default=False), 'is_visible': Tunable(description='\n        If set, then Sims in this group will have a visible representation in\n        the UI, i.e. a Relationship Inspector will be available and Groupobobs\n        will appear.\n        ', tunable_type=bool, default=False), '_components': TunableTuple(tuning_group=GroupNames.COMPONENTS, description='\n            The components that instances of this object should have.",\n            ', state=OptionalTunable(TunableStateComponent())), 'social_anchor_object': OptionalTunable(description='\n            If enabled, you can tune a participant to be the anchor the social \n            group is constructed around. Game groups tune the anchor to the \n            object the game targets. If disabled, the group_leader, if tuned,\n            will be the anchor.\n            ', tunable=TunableEnumEntry(description='\n                The anchor the social group forms around.\n                ', tunable_type=ParticipantTypeObject, default=ParticipantTypeObject.Object)), 'group_leader': OptionalTunable(description='\n            If enabled, you can tune the sim participant who will be the leader\n            of this social group.  If the leader leaves the group the group\n            will be shutdown.', tunable=TunableEnumEntry(description='\n                The leader of the social group.\n                ', tunable_type=ParticipantTypeActorTargetSim, default=ParticipantTypeActorTargetSim.Actor)), 'time_until_posture_changes': TunableSimMinute(15, description='\n        The length of time a Sim must be in the social group before they will\n        consider changing postures.\n        '), 'max_distance_to_snap_to_cluster_sq': TunableDistanceSquared(description='\n        The maximum distance (in meters) a group constraint will move to snap\n        to a cluster.\n        ', default=1.5)}
    MOVE_CONSTRAINT_EPSILON_SQ = TunableDistanceSquared(description='\n        When the focal point of the group moves by more than this epsilon,\n        attempt to re-center the social constraint.', default=1.0)
    MAXIMUM_NUMBER_OF_NON_ADJUSTABLE_SIMS = TunableRange(description='\n        The maximum number of entries in the list of non-adjustable Sims. Sims\n        are placed in the list when they complete mobile posture transitions,\n        and can be in the list more than once, thus occupying multiple\n        spots.', tunable_type=int, default=1, minimum=0)
    MOVEMENT_COST_BASE = TunableRange(description='\n        Cost for moving at all when incrementally adjusting the position of a\n        Sim', tunable_type=float, default=0.1, minimum=0.0)
    MOVEMENT_COST_MULTIPLIER = TunableRange(description='\n        Multiplier on the cost of moving a given distance when adjusting the\n        position of a Sim', tunable_type=float, default=0.1, minimum=0.0)
    MINIMUM_JIG_MOVE_EPSILON = TunableRange(description='\n        A Sim will not adjust their position if the distance is smaller than\n        this', tunable_type=float, default=0.01, minimum=sims4.math.EPSILON)
    MINIMUM_JIG_TURN_EPSILON = TunableRange(description='\n        A Sim will not adjust their position if the turning distance (arc in\n        radians) is smaller than this', tunable_type=float, default=0.01, minimum=sims4.math.EPSILON)
    FOCUS_SPEAKER_SCORE = TunableRange(description='\n        Focus score assigned to the speaker in a social group.\n        \n        Higher numbers make Sims more likely to look at the speaker.', tunable_type=int, default=50, minimum=0)
    FOCUS_LISTENER_SCORE = TunableRange(description='\n        Focus score assigned to the listeners in a social group.\n        \n        Higher numbers make Sims more likely to look at listeners.', tunable_type=int, default=10, minimum=0)
    SOCIAL_ADJUSTMENT_DELAY = TunableTuple(description='\n        Amount of time, in seconds, to delay before the next social adjustment\n        attempt.', lower_bound=TunableRealSecond(description='\n            Minimum amount of time, in seconds, to delay adjustment.', default=2), upper_bound=TunableRealSecond(description='\n            Maximum amount of time, in seconds, to delay adjustment', default=16))
    SETTLED_SOCIAL_ADJUSTMENT_DELAY = TunableTuple(description='\n        Once a group has become stagnant, the amount of time in seconds to delay\n        before performing a social adjustment attempt.', lower_bound=TunableRealSecond(description='\n            Minimum amount of time, in seconds, to delay adjustment (when stagnant).', default=20), upper_bound=TunableRealSecond(description='\n            Maximum amount of time, in seconds, to delay adjustment (when stagnant)', default=30))
    WORST_PLACED_SIM_RANDOMNESS = Tunable(description='\n        A floating point value that determines the randomness of the\n        selection of the worst placed Sim.  The worst placed Sim is given a\n        chance to change position by social adjustment. \n        \n        Larger values are more random.  A value of 0 means that there is no\n        randomness, while a value of 1000 means the selection is almost\n        completely random.\n        ', tunable_type=float, default=1.0)
    CENTER_PLACEMENT_JIG_OBJECT_DEF = TunableReference(description='\n        Temporary object (jig) to be placed when computing position of a sim joining a social group.', manager=services.definition_manager())
    BOREDOM_QUEUE_SIZE = TunableRange(description="\n        The number of different interactions that are memorized to calculate\n        boredom. The larger the number, the easier it will be for Sims to be\n        bored even if different affordance are used.\n        \n        e.g. If this number is 1, then boredom will apply to the last run\n        interaction only. If the Sim runs X X X Y X, then X's boredom count is\n        1.\n        \n        e.g. If this number is 3, then boredom will apply to the last three run\n        interactions. If the Sim runs X X Y Z Z X, the X's boredom count is 3,\n        Y's i 1, and Z's is 2.\n        ", tunable_type=int, minimum=0, default=1)
    SOCIAL_ADJUSTMENT_AFFORDANCE = TunableReference(services.affordance_manager(), description='\n                        The affordance to push when doing social adjustment.')
    FACING_AWAY_PENALTY = Tunable(float, 10, description='\n        The number of meters to penalize destinations that involve facing away from\n        the social group. This will be applied to destinations that violate the\n        tuning for FACING_RANGE_IDEAL.')
    FACING_RANGE_IDEAL = TunableAngle(sims4.math.PI/2, description='\n        The facing angle restriction on the ideal constraint for this group. A\n        constraint with this facing restriction will be added to a constraint\n        set where the constraint without this restriction gets the facing away\n        penalty.')
    IDEAL_JOIN_RADIUS_MULTIPLIER = Tunable(float, 2.9, description='\n        A Multiplier on top of the group radius that determines the ideal spacing\n        between Sims when "routing nearby" to form the initial social group.\n         \n        Note: ideal radius is set to be slightly larger than the standard\n        social distance so that when the group starts, the Sims don\'t need to\n        move much.')
    SOCIAL_GROUP_STAGNATION_TIME = TunableSimMinute(description='\n        After a social adjustment occurs we keep track of the time. We will not\n        clear out the list of Sims that cannot move in the group until\n        SOCIAL_GROUP_STAGNATION_TIME Sim minutes have elapsed.\n        ', default=30, minimum=0)
    SOCIAL_GROUP_ARRANGEMENT_SETTLING_TIME = TunableSimMinute(description='\n        After the social geometry changes, we keep track of the time.  Once\n        SOCIAL_GROUP_ARRANGEMENT_SETTLING_TIME has elapsed, we attempt\n        social adjustment less frequently (using SETTLED_SOCIAL_ADJUSTMENT_DELAY).\n        ', default=10, minimum=0)

    def __init__(self, *args, si=None, target_sim=None, **kwargs):
        super().__init__()
        self._component_types = ()
        self._component_instances = {}
        self._user_footprint_helper = None
        for component_factory in self._components.values():
            while component_factory is not None:
                self.add_component(component_factory(self))
        self.add_component(self.line_of_sight(self))
        self._contained_sims = WeakKeyDictionary()
        self._si_registry = WeakKeyDictionary()
        self._boredom_registry = WeakKeyDictionary()
        self._anchor_object = si.get_participant(self.social_anchor_object) if self.social_anchor_object is not None else None
        if self._anchor_object is not None and self._anchor_object.is_in_inventory():
            self._anchor_object = None
        self._group_leader = si.get_participant(self.group_leader) if self.group_leader is not None else None
        group_leader_override = si.social_group_leader_override
        if group_leader_override is not None:
            self._group_leader = si.get_participant(group_leader_override)
        self._has_been_shutdown = False
        self._has_played_social_animation = False
        self.on_group_changed = CallableList()
        self.geometry = socials.geometry.SocialGroupGeometry()
        self.radius = None
        self._constraint = None
        self.on_constraint_changed = CallableList()
        self._focus = None
        self._los_dirty = False
        self._sim_focus_ids = []
        self._focus_group = SocialFocusManager(self)
        self._adjustment_alarm = None
        self._non_adjustable_sims = collections.deque(maxlen=self.MAXIMUM_NUMBER_OF_NON_ADJUSTABLE_SIMS)
        self._has_adjusted = set()
        self._adjustment_interactions = WeakSet()
        self._time_when_second_sim_joined = None
        self._last_interaction_time = services.time_service().sim_now
        self._initiating_sim_ref = si.sim.ref()
        self._target_sim_ref = target_sim.ref() if target_sim is not None else None
        self.manager = None
        self.primitives = ()
        self._social_group_id = None
        services.social_group_manager().add(self)
        self.adjust_attempt_time = None
        self.geometry_change_time = services.time_service().sim_now
        self._moving_constraint = False

    def __iter__(self):
        return iter(tuple(self._contained_sims))

    def __len__(self):
        return len(self._contained_sims)

    def __repr__(self):
        return 'SocialGroup[{}] with anchor ({}), and leader ({})'.format(self.__class__.__name__, self._anchor_object, self._group_leader)

    @property
    def is_solo(self):
        return len(self) == 1

    def get_active_sim_count(self):
        return sum(1 for sim in self if self.is_sim_active_in_social_group(sim))

    @property
    def id(self):
        return self._social_group_id

    @id.setter
    def id(self, value):
        self._social_group_id = value

    def member_sim_ids_gen(self):
        for member in self:
            yield member.sim_id

    def get_create_op(self, *args, **kwargs):
        if self.is_visible:
            return distributor.ops.SocialGroupCreate(self, *args, **kwargs)

    def get_create_after_objs(self):
        return list(self)

    def get_delete_op(self):
        return distributor.ops.SocialGroupDelete()

    @property
    def valid_for_distribution(self):
        return True

    @distributor.fields.Field(op=distributor.ops.SocialGroupUpdate)
    def social_group_members(self):
        return [SocialGroupMember(sim.id, sim.get_social_context()) for sim in self]

    _resend_members = social_group_members.get_resend()

    @forward_to_components
    def on_state_changed(self, state, old_value, new_value):
        pass

    def on_social_context_changed(self):
        if not (self.is_visible and self.has_been_shutdown):
            self._resend_members()

    def on_social_super_interaction_run(self):
        self.on_group_changed(self)

    @property
    def anchor(self):
        return self._anchor_object

    @property
    def group_leader_sim(self):
        return self._group_leader

    @property
    def zone_id(self):
        if self.anchor is not None and self.anchor.is_sim:
            return self.anchor.zone_id
        if self._group_leader is not None and self._group_leader.is_sim:
            return self._group_leader.zone_id
        for sim_in_group in self._contained_sims:
            pass
        return services.current_zone().id

    @property
    def constraint_initialized(self):
        return self._constraint is not None

    @property
    def forward(self):
        return self._focus.forward

    @property
    def group_radius(self):
        num = max(len(self), 2)
        return self.radius_scale*math.sqrt(num/2)

    @property
    def has_been_shutdown(self):
        return self._has_been_shutdown

    @property
    def is_sim(self):
        return False

    @property
    def parent(self):
        pass

    @property
    def position(self):
        return self._focus.position

    @position.setter
    def position(self, value):
        self._set_focus(value, self.forward, self.routing_surface)

    @property
    def routing_location(self):
        return routing.Location(self._focus.position, orientation=self._focus.forward, routing_surface=self._focus.routing_surface)

    @property
    def routing_surface(self):
        if self._focus is None:
            return
        return self._focus.routing_surface

    @property
    def intended_position(self):
        return self.position

    @property
    def intended_forward(self):
        return self.forward

    @property
    def intended_routing_surface(self):
        return self.routing_surface

    @property
    def _initiating_sim(self):
        if self._initiating_sim_ref is not None:
            return self._initiating_sim_ref()

    @property
    def _los_constraint(self):
        if not self.lineofsight_component:
            return Anywhere()
        if self._los_dirty:
            self._los_dirty = False
            self.lineofsight_component.on_location_changed(self.position)
        return self.lineofsight_component.constraint_convex

    @property
    def _target_sim(self):
        if self._target_sim_ref is not None:
            return self._target_sim_ref()

    @property
    def is_outside(self):
        level = 0 if self.routing_surface is None else self.routing_surface.secondary_id
        return build_buy.is_location_outside(self.zone_id, self.position, level)

    def is_on_natural_ground(self):
        level = 0 if self.routing_surface is None else self.routing_surface.secondary_id
        return build_buy.is_location_natural_ground(self.zone_id, self.position, level)

    def has_room_in_group(self, sim):
        if sim in self:
            return True
        return len(self) < self.maximum_sim_count

    def attach(self, interaction):
        sis = self._si_registry.setdefault(interaction.sim, set())
        should_add = not sis
        sis.add(interaction)
        if should_add:
            self._add(interaction.sim, interaction)
        self._refresh_all_attached_si_conditional_actions()

    def detach(self, interaction):
        interactions = self._si_registry.get(interaction.sim, set())
        interactions.discard(interaction)
        if not interactions:
            finishing_type = interaction.finishing_type
            self._remove(interaction.sim, finishing_type=finishing_type)

    def _add(self, sim, attaching_si):
        if self.has_been_shutdown:
            logger.error('sim: {}, trying to attach to group that has already been cleaned up.', sim)
        (focus_object, sim_to_adjust) = self._get_focus_and_adjust_sim_while_join(sim)
        now = services.time_service().sim_now
        current_sims = len(self)
        if current_sims == 0:
            if self._constraint is None:
                if focus_object is None:
                    logger.error('focus_object for {} on {} is None. Did you forget to specify a social anchor object?', attaching_si, self)
                else:
                    used_object = self._relocate_group_around_focus(focus_object, joining_sim=sim_to_adjust, priority=attaching_si.priority)
                    if used_object is not None and used_object.is_sim:
                        self._create_social_geometry(used_object)
                    self.on_constraint_changed()
        elif current_sims == 1:
            self._time_when_second_sim_joined = now
        for target_sim in self:
            while target_sim is not None:
                sim.sim_info.relationship_tracker.on_added_to_social_group(target_sim.id)
        try:
            self._contained_sims[sim] = now
            DEFAULT_SCORE = 1
            self._focus_group.add_sim(sim, sim, DEFAULT_SCORE, SimFocus.LAYER_SUPER_INTERACTION)
            sim.notify_social_group_changed(self)
            for group_sim in self:
                group_sim.on_social_context_changed()
            self.on_group_changed(self)
            if len(self) == 1:
                self.on_constraint_changed()
                self._create_adjustment_alarm()
            else:
                self._try_adjusting_constraint()
            social_group_leader_override = attaching_si.social_group_leader_override
            while social_group_leader_override is not None and attaching_si.get_participant(social_group_leader_override) is not self._group_leader:
                logger.warn("Social Group Leader Override for SI: {} doesn't match existing group leader {}", attaching_si, self._group_leader)
        except:
            self._remove(sim)
            raise

    def remove(self, sim, finishing_type=None):
        finishing_type = FinishingType.SOCIALS if finishing_type is None else finishing_type
        if finishing_type != FinishingType.RESET and sim in self._si_registry:
            while True:
                for interaction in list(self._si_registry[sim]):
                    interaction.cancel(finishing_type, cancel_reason_msg='Remove Sim from the social group.')

    def get_all_interactions_gen(self):
        for sim in self:
            yield self._si_registry[sim]

    def get_users(self, **kwargs):
        return set(self)

    def _remove(self, sim, finishing_type=None):
        self._has_adjusted.discard(sim)
        self._clear_social_geometry(sim)
        self._focus_group.remove_sim(sim, sim)
        if sim in self._si_registry:
            del self._si_registry[sim]
        if sim in self._contained_sims:
            del self._contained_sims[sim]
        for target_sim in self:
            while target_sim is not None:
                sim.sim_info.relationship_tracker.on_removed_from_social_group(target_sim.id)
        if finishing_type != FinishingType.RESET:
            for adjustment_interaction in list(self._adjustment_interactions):
                while adjustment_interaction.sim is sim:
                    adjustment_interaction.cancel(FinishingType.SOCIALS, cancel_reason_msg='Sim was removed from the social group.')
                    if adjustment_interaction in self._adjustment_interactions:
                        self._adjustment_interactions.remove(adjustment_interaction)
            for contained_sim in tuple(self._contained_sims):
                for si in contained_sim.queue:
                    while si.target is sim and si.social_group is self:
                        si.cancel(FinishingType.SOCIALS, cancel_reason_msg='Target Sim was removed from the social group.')
        else:
            self._adjustment_interactions.clear()
        while sim in self._non_adjustable_sims:
            self._non_adjustable_sims.remove(sim)
        sim.notify_social_group_changed(self)
        for group_sim in itertools.chain((sim,), self):
            group_sim.on_social_context_changed()
        self.on_group_changed(self)
        sim.on_social_geometry_changed()
        sims_in_group = len(self)
        if sims_in_group <= min(1, self.minimum_sim_count):
            self._constraint = None
            self.on_constraint_changed()
            if sims_in_group < self.minimum_sim_count:
                self.shutdown(finishing_type=finishing_type)
        if sim is self._group_leader:
            self.shutdown(finishing_type=finishing_type)

    def shutdown(self, finishing_type):
        if not self.has_been_shutdown:
            self._has_been_shutdown = True
            sims = list(self)
            for sim in sims:
                self.remove(sim, finishing_type)
            if self.lineofsight_component is not None:
                self.lineofsight_component.on_remove()
                self.remove_component('lineofsight_component')
                self.lineofsight_component = None
            self._destroy_adjustment_alarm()
            self._focus_group.shutdown(self._group_leader)
            self.manager.remove(self)
            self._user_footprint_helper = None
            if finishing_type != FinishingType.RESET:
                for interaction in self._adjustment_interactions:
                    interaction.cancel(FinishingType.SOCIALS, cancel_reason_msg='Social group was shutdown')
            self._adjustment_interactions.clear()

    def try_relocate_around_focus(self, focus_object, priority=None):
        if self.anchor is not None:
            return False
        for interaction in tuple(self._adjustment_interactions):
            interaction.cancel(FinishingType.SOCIALS, cancel_reason_msg='Social group was relocated')
        self._adjustment_interactions.clear()
        used_object = self._relocate_group_around_focus(focus_object, notify=False, priority=priority)
        for member in self:
            self._clear_social_geometry(member, call_on_changed=False)
        if used_object is not None and used_object.is_sim:
            self._create_social_geometry(used_object)
        self._group_geometry_changed()
        self.on_constraint_changed()
        self._non_adjustable_sims.clear()
        return True

    def _relocate_group_around_focus(self, focus_object, joining_sim=None, notify=True, constraint=None, priority=None):
        if self._anchor_object is not None:
            target_position = self._anchor_object.position
            target_forward = self._anchor_object.forward
            target_routing_surface = self._anchor_object.routing_surface
            used_object = self._anchor_object
            self._anchor_object = None
        else:
            used_object = None
            if constraint is not None:
                target_position = constraint.average_position if constraint is not None else None
                target_forward = sims4.math.Vector3.Z_AXIS()
                target_routing_surface = constraint.routing_surface
            else:
                found = False
                if joining_sim is not None and (joining_sim.posture.mobile and (focus_object is not None and (focus_object.is_sim and (focus_object.posture.mobile and constraint is None)))) and (joining_sim.intended_position - focus_object.intended_position).magnitude() < 4.0*self.radius_scale:
                    target_position = self._get_ideal_midpoint(joining_sim, focus_object)
                    if self._check_focus_position(target_position, focus_object.intended_routing_surface):
                        found = True
                if not found:
                    target_position = focus_object.intended_position + focus_object.intended_forward*self.radius_scale
                    if self._check_focus_position(target_position, focus_object.intended_routing_surface):
                        found = True
                        used_object = focus_object
                if not found:
                    target_position = focus_object.intended_position + focus_object.intended_forward*(focus_object.object_radius*0.5)
                    used_object = focus_object
                target_forward = focus_object.intended_forward
                target_routing_surface = focus_object.intended_routing_surface
        initial_sims = [obj for obj in (joining_sim, focus_object) if obj.is_sim]
        self._set_focus(target_position, target_forward, target_routing_surface)
        self._initialize_constraint(notify=notify, priority=priority, initial_sims=initial_sims)
        return used_object

    @classmethod
    def _check_focus_position(cls, position, routing_surface):
        footprint = cls.CENTER_PLACEMENT_JIG_OBJECT_DEF.get_footprint()
        return placement._placement.test_object_placement(position, sims4.math.Quaternion.IDENTITY(), routing_surface, footprint)

    def _get_ideal_midpoint(self, sim1, sim2):
        delta = sim1.intended_position - sim2.intended_position
        delta.y = 0
        m = delta.magnitude()
        if m == 0:
            return sim2.position + sim2.forward*self.radius_scale
        normalized_delta = delta/m
        positions = []
        total_weight = 0
        for sim in (sim1, sim2):
            weight = 1
            total_constraint = sim.si_state.get_total_constraint()
            for constraint in total_constraint:
                if constraint.geometry is not None:
                    weight += len(constraint.geometry.restrictions)
                cross = sims4.math.vector_cross_2d(normalized_delta, sim.forward)
                point = sim.position + abs(cross)*sim.forward*self.radius_scale
                positions.append(point*weight)
                total_weight += weight
                break
        return sum(positions, sims4.math.Vector3Immutable.ZERO())/total_weight

    def _set_focus(self, position, forward, routing_surface):
        if position is None:
            raise RuntimeError('Attempt to set the position of a social group to None!')
        y = terrain.get_terrain_height(position.x, position.z, routing_surface=routing_surface)
        self._focus = SocialGroupLocation(sims4.math.Vector3(position.x, y, position.z), forward, routing_surface)
        self._los_dirty = True
        self.refresh_social_geometry()

    def queued_mixers_gen(self, sim):
        for sim in self:
            sis = self._si_registry.get(sim)
            if not sis:
                pass
            for interaction in sim.queue:
                if interaction.is_super:
                    pass
                while interaction.super_interaction in sis:
                    yield interaction

    @classmethod
    def make_constraint_default(cls, sim, target, position, routing_surface, participant_type=ParticipantType.Actor, **kwargs):
        circle = Circle(position, cls.max_radius, routing_surface, ideal_radius=cls.radius_scale, debug_name='SocialConstraint')
        ideal = circle.intersect(Facing(target_position=position, facing_range=sims4.math.TWO_PI))
        return ideal

    def _make_constraint(self, position, priority=None, from_init=True):
        if self._focus is None:
            logger.error('Attempt to _make_constraint for a group that has not had position initialized. {}', self)
            return Anywhere()
        if not from_init:
            routing_location = routing.Location(self._focus.position, sims4.math.Quaternion.IDENTITY(), self._focus.routing_surface)
            if not placement.validate_los_source_location(routing_location):
                return Nowhere()
        constraint = self.make_constraint_default(self._initiating_sim, self._target_sim, position, self.routing_surface)
        constraint = constraint.intersect(self._los_constraint)
        sims = (self._initiating_sim, self._target_sim)
        for sim in sims:
            if sim is None:
                pass
            registered_si = self.get_si_registered_for_sim(sim)
            while not sim.si_state.is_compatible_constraint(constraint, priority=priority, to_exclude=registered_si):
                (fallback_position, fallback_routing_surface) = get_fallback_social_constraint_position(self._initiating_sim, self._target_sim, registered_si, priority=priority)
                if fallback_position is None:
                    return Nowhere()
                self._set_focus(fallback_position, sims4.math.Vector3(1, 0, 0), fallback_routing_surface)
                constraint = self.make_constraint_default(self._initiating_sim, self._target_sim, fallback_position, self.routing_surface)
                constraint = constraint.intersect(self._los_constraint)
                for sim in sims:
                    while not sim.si_state.is_compatible_constraint(constraint, priority=priority, to_exclude=registered_si):
                        return Nowhere()
                break
        cluster = services.social_group_cluster_service().get_closest_valid_cluster(constraint)
        if cluster is not None:
            new_constraints = []
            for sub_constraint in constraint:
                if sub_constraint.geometry is not None:
                    polygon = CompoundPolygon(list(itertools.chain(sub_constraint.geometry.polygon, cluster.constraint.geometry.polygon)))
                    new_geometry = RestrictedPolygon(polygon, sub_constraint.geometry.restrictions)
                else:
                    polygon = cluster.constraint.geometry.polygon
                    new_geometry = RestrictedPolygon(polygon, [])
                new_sub_constraint = sub_constraint.generate_alternate_geometry_constraint(new_geometry)
                new_constraints.append(new_sub_constraint)
            constraint = create_constraint_set(new_constraints, debug_name='SocialConstraint + Cluster')
        return constraint

    def regenerate_constraint_and_validate_members(self):
        self._constraint = self._make_constraint(self.position, from_init=False)
        self.on_constraint_changed()

    def _initialize_constraint(self, notify=True, priority=None, initial_sims=()):
        self._constraint = self._make_constraint(self.position, priority=priority)
        if notify:
            self.on_constraint_changed()

    def _get_constraint(self, sim):
        if self._focus is None:
            logger.error('Attempt to get a constraint for a Sim before the group constraint is initialized: {} for {}', self, sim, owner='maxr')
            return Anywhere()
        geometric_constraint = self._constraint
        if geometric_constraint is None:
            raise RuntimeError('Attempt to get the constraint from a Social group before it has been initialized.')
        scoring_constraint = self.facing_restriction.create_constraint(sim, self, scoring_functions=(SocialGroupScoringFunction(self, sim),))
        intersection = geometric_constraint.intersect(scoring_constraint)
        return intersection

    def get_constraint(self, sim):
        return self._get_constraint(sim)

    def time_since_active(self):
        if self._time_when_second_sim_joined is not None:
            now = services.time_service().sim_now
            return now - self._time_when_second_sim_joined
        return date_and_time.TimeSpan.ZERO

    def time_in_group(self, sim):
        join_time = self._contained_sims.get(sim)
        if join_time is not None:
            now = services.time_service().sim_now
            return now - join_time
        return date_and_time.TimeSpan.ZERO

    def time_since_interaction(self):
        now = services.time_service().sim_now
        return now - self._last_interaction_time

    def _on_interaction_start(self, interaction):
        now = services.time_service().sim_now
        self._last_interaction_time = now
        self._add_boredom(interaction)

    def can_change_posture_during_adjustment(self, sim):
        time_in_group = self.time_in_group(sim)
        return time_in_group >= clock.interval_in_sim_minutes(self.time_until_posture_changes)

    def _refresh_all_attached_si_conditional_actions(self):
        for sis in tuple(self._si_registry.values()):
            for si in tuple(sis):
                si.refresh_conditional_actions()

    def _adjustment_alarm_callback(self, _):
        try:
            self._consider_adjusting_sim()
        finally:
            if self._adjustment_alarm is not None:
                self._adjustment_alarm = None
                self._create_adjustment_alarm()

    def _create_adjustment_alarm(self):
        if self._adjustment_alarm is not None:
            alarms.cancel_alarm(self._adjustment_alarm)
        if self._recent_geometry_change():
            delay_interval = self.SOCIAL_ADJUSTMENT_DELAY
        else:
            delay_interval = self.SETTLED_SOCIAL_ADJUSTMENT_DELAY
        alarm_delay = random.uniform(delay_interval.lower_bound, delay_interval.upper_bound)
        self._adjustment_alarm = alarms.add_alarm(self, clock.interval_in_sim_minutes(alarm_delay), self._adjustment_alarm_callback)

    def _destroy_adjustment_alarm(self):
        if self._adjustment_alarm is not None:
            alarms.cancel_alarm(self._adjustment_alarm)
            self._adjustment_alarm = None

    def _get_focus_and_adjust_sim_while_join(self, joining_sim):
        if self._anchor_object:
            return (self._anchor_object, joining_sim)
        if self._group_leader:
            return (self._group_leader, joining_sim)
        return (self._target_sim, joining_sim)

    def get_sis_registered_for_sim(self, sim):
        return self._si_registry.get(sim)

    def get_si_registered_for_sim(self, sim, affordance=None):
        sis = self.get_sis_registered_for_sim(sim)
        if sis:
            for si in sis:
                if affordance is None:
                    return si
                while si.affordance is affordance:
                    return si

    def is_sim_active_in_social_group(self, sim):
        si = self.get_si_registered_for_sim(sim)
        if si is None:
            return False
        return si.running and not si.is_finishing

    def _could_sim_route(self, sim):
        allow_posture_changes = self.can_change_posture_during_adjustment(sim)
        if not sim.posture.mobile:
            if not allow_posture_changes:
                return False
            if sim.posture.owning_interactions:
                interactions_to_test = sim.posture.owning_interactions
            else:
                interactions_to_test = [sim.posture.source_interaction]
            for interaction in interactions_to_test:
                while interaction is not None and not interaction.satisfied:
                    return False
        constraint_intersection = sim.si_state.get_total_constraint(priority=interactions.priority.Priority.Low, include_inertial_sis=True, force_inertial_sis=True, allow_posture_providers=not allow_posture_changes)
        test_posture_intersection = constraint_intersection.intersect(STAND_OR_SIT_CONSTRAINT)
        if not test_posture_intersection.valid:
            return False
        geometry_intersection = None
        for constraint in constraint_intersection:
            geometry = constraint.geometry
            while geometry is not None:
                geometry_intersection = geometry if geometry_intersection is None else geometry_intersection.intersect(geometry)
                if geometry_intersection.polygon.area() == 0:
                    return False
        if geometry_intersection is None or geometry_intersection.polygon.area() > 0:
            return True
        return False

    def _can_sim_be_adjusted(self, sim, initial=False):
        if sim in self._non_adjustable_sims:
            return False
        if sim in self.geometry.members and len(self.geometry.members) == 1:
            return False
        if sim.last_affordance is self.SOCIAL_ADJUSTMENT_AFFORDANCE:
            return False
        if sim.queue.has_adjustment_interaction():
            return False
        head = sim.queue.get_head()
        if head is not None and head.is_super:
            return False
        if not initial and (sim.queue.transition_in_progress or sim.is_moving):
            return False
        if sim.is_in_side_group():
            return False
        if not self._could_sim_route(sim):
            return False
        return True

    def _adjustable_sims_gen(self):
        for sim in self:
            while self._can_sim_be_adjusted(sim):
                yield sim

    def _recent_adjustment_attempt(self):
        if self.adjust_attempt_time is None:
            return False
        time_delta = services.time_service().sim_now - self.adjust_attempt_time
        if time_delta > date_and_time.create_time_span(minutes=SocialGroup.SOCIAL_GROUP_STAGNATION_TIME):
            return False
        return True

    def _recent_geometry_change(self):
        time_delta = services.time_service().sim_now - self.geometry_change_time
        if time_delta > date_and_time.create_time_span(minutes=SocialGroup.SOCIAL_GROUP_ARRANGEMENT_SETTLING_TIME):
            return False
        return True

    def _pick_worst_placed_sim(self):
        if self.geometry:
            if not self._recent_geometry_change():
                self._non_adjustable_sims.clear()
            available_sims = list(self._adjustable_sims_gen())
            if not available_sims:
                return
            scores = self.geometry.score_placement(available_sims, self)
            worst = None
            minimum = None
            for (sim, score) in scores:
                if SocialGroup.WORST_PLACED_SIM_RANDOMNESS != 0:
                    score += random.expovariate(1.0/SocialGroup.WORST_PLACED_SIM_RANDOMNESS)
                if minimum is None or score < minimum:
                    worst = sim
                    minimum = score
                else:
                    while score < minimum:
                        worst = sim
            return worst

    def try_initial_adjustment(self, sim):
        if sim not in self._has_adjusted:
            return self._consider_adjusting_sim(sim=sim, initial=True)
        return False

    def execute_adjustment_interaction(self, sim_to_adjust, force_allow_posture_changes=False):
        allow_posture_changes = force_allow_posture_changes or self.can_change_posture_during_adjustment(sim_to_adjust)
        if allow_posture_changes or not sim_to_adjust.posture.mobile:
            constraint_to_satisfy = STAND_OR_SIT_CONSTRAINT_OUTER_PENALTY
        else:
            constraint_to_satisfy = STAND_CONSTRAINT_OUTER_PENALTY
        adjustment_prioriry = priority.Priority.High
        result = sim_to_adjust.execute_adjustment_interaction(self.SOCIAL_ADJUSTMENT_AFFORDANCE, constraint_to_satisfy, adjustment_prioriry, name_override='Satisfy[social_adjust]', allow_posture_changes=allow_posture_changes, set_work_timestamp=False, cancel_incompatible_with_posture_on_transition_shutdown=False)
        return result

    def _consider_adjusting_sim(self, sim=None, initial=False):
        if sim is not None and sim.queue.has_adjustment_interaction():
            return False
        self._try_adjusting_constraint()
        if not self.geometry or len(self.geometry) < 2:
            return False
        if sim is None and not self.adjust_sim_positions_dynamically:
            return False
        if sim not in self:
            logger.error('[Adjustment] Attempting to adjust Sim {} not in group.', sim)
            return False
        if not (sim is not None and self._can_sim_be_adjusted(sim, initial=initial)):
            return False
        sim_to_adjust = sim or self._pick_worst_placed_sim()
        if sim_to_adjust is not None and self.geometry:
            logger.debug('[Adjustment] Worst placed Sim is {} at {}', sim_to_adjust, sim_to_adjust.position)
            si = self.get_si_registered_for_sim(sim_to_adjust)
            if si is not None and not si.is_finishing:
                self.adjust_attempt_time = services.time_service().sim_now
                self._has_adjusted.add(sim_to_adjust)
                result = self.execute_adjustment_interaction(sim_to_adjust)
                if result:
                    adjustment_interaction = result.execute_result.interaction
                    self._adjustment_interactions.add(adjustment_interaction)
                    return True
                self.adjust_attempt_time = None
        return False

    def _try_adjusting_constraint(self):
        if self._anchor_object is not None or len(self) == 0 or self._focus is None:
            return False
        if self._constraint is not None and self.position is not None and self.geometry:
            focus_position = self.geometry.focus
            min_sim_dist_sq = min((sim.intended_position - focus_position).magnitude_2d_squared() for sim in self)
            dist_sq = (self.position - self.geometry.focus).magnitude_2d_squared()
            if dist_sq > min_sim_dist_sq or dist_sq > SocialGroup.MOVE_CONSTRAINT_EPSILON_SQ:
                target_position = focus_position
                target_routing_surface = self.routing_surface
                if self._try_adjusting_constraint_to_location(target_position, target_routing_surface):
                    return True
        return False

    def _try_adjusting_constraint_to_location(self, position, routing_surface):
        try:
            self._moving_constraint = True
            original_constraint = self._constraint
            original_position = self.position
            original_geometry_change_time = self.geometry_change_time
            position_constraint = interactions.constraints.Position(position, routing_surface=routing_surface)
            if not position_constraint.intersect(original_constraint).valid:
                return False
            self.position = position
            candidate_constraint = self._make_constraint(position)
            candidate_constraint = candidate_constraint.intersect(self._los_constraint)
            self._constraint = candidate_constraint
            self.on_constraint_changed()
            intersection_valid = True
            for sim in self:
                si_state_intersection = sim.si_state.get_total_constraint(include_inertial_sis=True, force_inertial_sis=True)
                si_state_intersection = si_state_intersection.intersect(interactions.constraints.Transform(sim.transform, routing_surface=self.routing_surface))
                while not si_state_intersection.valid:
                    intersection_valid = False
                    break
            while not intersection_valid:
                self._constraint = original_constraint
                self.position = original_position
                self.geometry_change_time = original_geometry_change_time
        finally:
            self._moving_constraint = False
        self.on_constraint_changed()
        return intersection_valid

    def remove_non_adjustable_sim(self, sim):
        if sim in self._non_adjustable_sims:
            self._non_adjustable_sims.remove(sim)

    def add_non_adjustable_sim(self, sim):
        self._non_adjustable_sims.append(sim)

    def has_social_geometry(self, sim):
        if sim in self.geometry:
            return True
        return False

    def refresh_social_geometry(self, sim=None):
        sims = (sim,) if sim is not None else self
        for sim in sims:
            self._clear_social_geometry(sim, call_on_changed=False)
        for sim in sims:
            self._create_social_geometry(sim, call_on_changed=False)
        self._group_geometry_changed()

    def _create_social_geometry(self, sim, call_on_changed=True, transform_override=None):
        if sim not in self.geometry:
            yield_to_irq()
            social_geometry = socials.geometry.create(sim, self, transform_override=transform_override)
            if social_geometry is not None:
                self.geometry[sim] = social_geometry
            if call_on_changed:
                self._group_geometry_changed()

    def _clear_social_geometry(self, sim, call_on_changed=True):
        del self.geometry[sim]
        if sim in self.geometry and call_on_changed:
            self._group_geometry_changed()

    def _group_geometry_changed(self):
        self.radius = None
        if self.geometry:
            ideal_radius = self.group_radius
            radii = [ideal_radius]
            for sim in self:
                while sim in self.geometry:
                    delta = sim.intended_position - self.geometry.focus
                    radii.append(delta.magnitude_2d())
            avg_radius = sum(radii)/len(radii)
            self.radius = avg_radius
        for sim in self:
            sim.on_social_geometry_changed()
        if not self._moving_constraint:
            recent_geometry_change = self._recent_geometry_change()
            self.geometry_change_time = services.time_service().sim_now
            if not recent_geometry_change:
                self._create_adjustment_alarm()

    def with_social_focus(self, owner_sim, speaker, required_sims, *args):
        active_list = []
        if speaker is not None:
            multiplier = len(self) - 1
            active_list.append((speaker, self.FOCUS_SPEAKER_SCORE*multiplier))
        for sim in self:
            while sim is not speaker and sim in required_sims:
                active_list.append((sim, self.FOCUS_LISTENER_SCORE))
        focus_group = self._focus_group
        return build_critical_section_with_finally(lambda _: focus_group.active_focus_begin(owner_sim, active_list), args, lambda _: focus_group.active_focus_end(owner_sim, active_list))

    def without_social_focus(self, owner_sim, sim, *args):
        sim_focus_entry = self._focus_group.get_focus_entry_for_sim(owner_sim, sim, SimFocus.LAYER_SUPER_INTERACTION)
        if sim_focus_entry is None:
            return args
        focus_group = self._focus_group
        return build_critical_section_with_finally(lambda _: focus_group.remove_focus_entry_for_sim(owner_sim, sim, SimFocus.LAYER_SUPER_INTERACTION), args, lambda _: focus_group.add_focus_entry_for_sim(owner_sim, sim, SimFocus.LAYER_SUPER_INTERACTION, sim_focus_entry))

    def with_target_focus(self, owner_sim, speaker, target, *args):
        multiplier = len(self) - 1
        active_list = [(speaker, self.FOCUS_SPEAKER_SCORE*multiplier), (target, self.FOCUS_SPEAKER_SCORE*multiplier)]
        focus_group = self._focus_group
        return build_critical_section_with_finally(lambda _: focus_group.active_focus_begin(owner_sim, active_list, immediate=True), args, lambda _: focus_group.active_focus_end(owner_sim, active_list))

    def with_listener_focus(self, owner_sim, listener, *args):
        active_list = [(listener, self.FOCUS_LISTENER_SCORE)]
        focus_group = self._focus_group
        return build_critical_section_with_finally(lambda _: focus_group.active_focus_begin(owner_sim, active_list, immediate=False), args, lambda _: focus_group.active_focus_end(owner_sim, active_list))

    def _add_boredom(self, interaction):
        if interaction.is_super or not interaction.visible or interaction.source != InteractionSource.PIE_MENU:
            return
        sim = interaction.sim
        setdefault_callable(self._boredom_registry, sim, WeakKeyDictionary)
        for target_sim in interaction.get_participants(ParticipantType.TargetSim | ParticipantType.Listeners):
            setdefault_callable(self._boredom_registry[sim], target_sim, lambda : collections.deque(maxlen=self.BOREDOM_QUEUE_SIZE))
            for (index, (affordance, count)) in enumerate(self._boredom_registry[sim][target_sim]):
                while interaction.affordance is affordance:
                    self._boredom_registry[sim][target_sim][index] = (affordance, count + 1)
                    break
            self._boredom_registry[sim][target_sim].append((interaction.affordance, 1))

    def get_boredom(self, sim, target_sim, affordance):
        target_mapping = self._boredom_registry.get(sim)
        if target_mapping is not None:
            affordance_mapping = target_mapping.get(target_sim)
            if affordance_mapping is not None:
                while True:
                    for (affordance_key, count) in affordance_mapping:
                        while affordance is affordance_key:
                            return count
        return 0

    def get_social_animation_element(self, social_animation_ref):

        def set_has_played_social_animation(_):
            self._has_played_social_animation = True

        return unless(lambda : self._has_played_social_animation, build_element((set_has_played_social_animation, social_animation_ref)))

