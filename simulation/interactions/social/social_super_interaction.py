from animation.posture_manifest_constants import STAND_OR_SIT_CONSTRAINT
from event_testing import test_events
from event_testing.results import TestResult
from interactions import ParticipantType, TargetType, PipelineProgress, ParticipantTypeActorTargetSim
from interactions.base.basic import StagingContent, FlexibleLengthContent
from interactions.base.interaction import CancelInteractionsOnExitLiability, CANCEL_INTERACTION_ON_EXIT_LIABILITY, InteractionQueuePreparationStatus
from interactions.base.super_interaction import SuperInteraction
from interactions.constraints import Anywhere, Constraint, Nowhere
from interactions.context import QueueInsertStrategy, InteractionContext
from interactions.interaction_finisher import FinishingType
from interactions.liability import Liability
from interactions.si_state import can_priority_displace
from interactions.social import SocialInteractionMixin
from interactions.utils.animation import flush_all_animations
from interactions.utils.outcome import TunableOutcome
from interactions.utils.satisfy_constraint_interaction import SatisfyConstraintSuperInteraction
from interactions.utils.sim_focus import TunableFocusElement
from objects.base_interactions import JoinInteraction, ProxyInteraction
from postures import DerailReason
from primitives.routing_utils import estimate_distance_between_points
from sims.sim import LOSAndSocialConstraintTuning
from sims4.tuning.tunable import TunableTuple, TunableMapping, TunableEnumEntry, Tunable, OptionalTunable
from sims4.utils import flexmethod, classproperty
from socials.group import get_fallback_social_constraint_position
import alarms
import assertions
import autonomy.autonomy_modes
import autonomy.content_sets
import clock
import interactions.aop
import interactions.context
import interactions.utils.animation_reference
import interactions.utils.tunable_icon
import services
import sims.sim
import sims4.localization
import sims4.log
import sims4.tuning.tunable
import sims4.tuning.tunable_base
import situations
import socials
logger = sims4.log.Logger('Socials')

class SocialCompatibilityMixin:
    __qualname__ = 'SocialCompatibilityMixin'

    def test_constraint_compatibility(self):
        incompatible_sims = set()
        included_sis = set()
        for required_sim in self.required_sims():
            participant_type = self.get_participant_type(required_sim)
            if participant_type == ParticipantType.TargetSim and self.target_type == TargetType.OBJECT:
                pass
            for si in required_sim.si_state.all_guaranteed_si_gen(self.priority, self.group_id):
                if self.super_affordance_klobberers is not None and self.super_affordance_klobberers(si.affordance):
                    pass
                if not required_sim.si_state.are_sis_compatible(self, si, participant_type_a=participant_type, participant_type_b=si.get_participant_type(required_sim), for_sim=required_sim):
                    incompatible_sims.add(required_sim)
                else:
                    while required_sim is self.sim:
                        included_sis.add(si)
        for si in self.sim.si_state:
            if si in included_sis:
                pass
            while self.sim.si_state.are_sis_compatible(self, si, participant_type_b=si.get_participant_type(self.sim)):
                included_sis.add(si)
        if incompatible_sims:
            return (False, incompatible_sims, included_sis)
        return (True, None, included_sis)

    def estimate_distance(self):
        constraint = self.constraint_intersection()
        target_sim = self.get_participant(ParticipantType.TargetSim)
        posture_change = False
        si_constraint_sim = self.sim.posture_state.constraint_intersection
        posture_constraint_sim = self.sim.posture_state.posture_constraint
        constraint_sim = si_constraint_sim.intersect(posture_constraint_sim)
        if not constraint.intersect(constraint_sim).valid:
            posture_change = True
        if target_sim is not None and not posture_change:
            si_constraint_target = target_sim.posture_state.constraint_intersection
            posture_constraint_target = target_sim.posture_state.posture_constraint
            constraint_target = si_constraint_target.intersect(posture_constraint_target)
            if not constraint.intersect(constraint_target).valid:
                posture_change = True
        (compatible, _, included_sis) = self.test_constraint_compatibility()
        estimate = 0 if compatible else None
        return (estimate, posture_change, included_sis)

    def get_sims_with_invalid_paths(self):
        (valid, incompatible_sims, _) = self.test_constraint_compatibility()
        if not valid:
            return incompatible_sims
        target_sim = self.get_participant(ParticipantType.TargetSim)
        if target_sim is None:
            return set()
        (position, _) = get_fallback_social_constraint_position(self.sim, target_sim, self)
        if position is not None:
            return set()
        return {self.sim}

INTENDED_POSITION_LIABILITY = 'IntendedPositionLiability'

class IntendedPositionLiability(Liability):
    __qualname__ = 'IntendedPositionLiability'

    def __init__(self, interaction, sim):
        super().__init__()
        self._interaction = interaction
        self._sim_ref = sim.ref()
        sim.on_intended_location_changed.append(self._on_intended_location_changed)

    @property
    def _sim(self):
        return self._sim_ref()

    def _on_intended_location_changed(self, *args, **kwargs):
        if self._sim is not None and self._on_intended_location_changed in self._sim.on_intended_location_changed:
            self._sim.on_intended_location_changed.remove(self._on_intended_location_changed)
        self._interaction.cancel(FinishingType.CONDITIONAL_EXIT, 'TargetSim intended position changed.')

    def release(self):
        super().release()
        if self._sim is not None and self._on_intended_location_changed in self._sim.on_intended_location_changed:
            self._sim.on_intended_location_changed.remove(self._on_intended_location_changed)

class SocialSuperInteraction(SocialInteractionMixin, SocialCompatibilityMixin, SuperInteraction):
    __qualname__ = 'SocialSuperInteraction'
    INSTANCE_TUNABLES = {'affordance_to_push_on_target': sims4.tuning.tunable.TunableVariant(description='\n            Affordance to push on the target sim.\n            ', push_self_or_none=sims4.tuning.tunable.Tunable(description='\n                If true will push this affordance on the target sim, else push None\n                ', tunable_type=bool, default=True), push_affordance=sims4.tuning.tunable.TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), default='push_self_or_none'), 'additional_social_to_run_on_both': sims4.tuning.tunable.OptionalTunable(sims4.tuning.tunable.TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), description="\n                     Another SocialSuperInteraction to run on both Sims as part of entering\n                     this social. All touching socials should reference a non-touching social\n                     to run that is responsible for handling exit conditions so the Sims aren't\n                     locked into a touching formation at all times."), '_social_group_type': sims4.tuning.tunable.TunableReference(description='\n            The type of social group to use for this interaction and related\n            interactions.\n            ', manager=services.get_instance_manager(sims4.resources.Types.SOCIAL_GROUP)), '_social_group_participant_slot_overrides': OptionalTunable(description='\n            Overrides for the slot index mapping on the jig keyed by participant type.\n            Note: This only works with Jig Social Groups.\n            ', tunable=TunableMapping(description='\n                Overrides for the slot index mapping on the jig keyed by\n                participant type. Note: This only works with Jig Social Groups.\n                ', key_type=TunableEnumEntry(ParticipantType, ParticipantType.Actor), value_type=Tunable(description='The slot index for the participant type', tunable_type=int, default=0))), '_social_group_leader_override': OptionalTunable(description='\n            If enabled, you can override the sim participant who will be the leader\n            of the social group.  If the leader leaves the group the group\n            will be shutdown.', tunable=TunableEnumEntry(description='\n                The leader of the social group.\n                ', tunable_type=ParticipantTypeActorTargetSim, default=ParticipantTypeActorTargetSim.Actor)), 'listen_animation': interactions.utils.animation_reference.TunableAnimationReference(description='\n            The animation for a Sim to play while running this\n            SocialSuperInteraction and waiting to play a reactionlet.\n            '), 'social_start_animation': TunableTuple(description='\n            The Animation and focus information for a Sim to use when first arriving within\n            sight of the target Sim.\n            ', greet_animation=interactions.utils.animation_reference.TunableAnimationReference(description='\n            The animation for a Sim to play when they first start socializing with a Sim.\n            '), focus=TunableFocusElement()), 'multi_sim_override_data': sims4.tuning.tunable.OptionalTunable(sims4.tuning.tunable.TunableTuple(description='\n            Override data that gets applied to interaction if social group size\n            meets threshold.\n            ', threshold=sims4.tuning.tunable.TunableRange(description='\n                Size of group before display name and icon for interaction queue\n                will be replaced.  If the group size is larger than threshold\n                then icon and/or text will be replaced.\n                ', tunable_type=int, default=2, minimum=1), display_text=sims4.localization.TunableLocalizedStringFactory(description="\n                Display text of target of mixer interaction.  Example: Sim A\n                queues 'Tell Joke', Sim B will see in their queue 'Be Told Joke'\n                ", default=None), icon=interactions.utils.tunable_icon.TunableIcon(description='\n                Icon to display if social group becomes larger than threshold.\n                ')), tuning_group=sims4.tuning.tunable_base.GroupNames.UI), 'invite_in_after_interaction': sims4.tuning.tunable.Tunable(description='\n        Checking this box will automatically invite the targeted Sim into your\n        home as long as you are on your lot and they are not.', tunable_type=bool, default=True), 'outcome': TunableOutcome(allow_social_animation=True)}

    def __init__(self, *args, initiated=True, social_group=None, picked_object=None, source_social_si=None, set_work_timestamp=False, **kwargs):
        SuperInteraction.__init__(self, initiated=initiated, set_work_timestamp=set_work_timestamp, *args, **kwargs)
        SocialInteractionMixin.__init__(self, initiated=initiated, *args, **kwargs)
        self._initiated = initiated
        self._target_si = None
        self._target_si_test_result = True
        self._picked_object_ref = picked_object.ref() if picked_object is not None else None
        self._social_group = social_group
        self._source_social_si = source_social_si
        self._waiting_start_time = None
        self._waiting_alarm = None
        self._go_nearby_interaction = None
        self._last_go_nearby_time = None
        self._trying_to_go_nearby_target = False
        self._target_was_going_far_away = False
        self._waved_hi = False

    @property
    def target_sim(self):
        return self.get_participant(ParticipantType.TargetSim)

    @property
    def social_group_leader_override(self):
        return self._social_group_leader_override

    def _get_close_to_target(self, force=False):
        now = services.time_service().sim_now
        if self._last_go_nearby_time is not None:
            minimum_delay_between_attempts = LOSAndSocialConstraintTuning.minimum_delay_between_route_nearby_attempts
            if now - self._last_go_nearby_time < clock.interval_in_sim_minutes(minimum_delay_between_attempts):
                return False
        self._last_go_nearby_time = now
        if self._trying_to_go_nearby_target:
            return False
        if self._target_was_going_far_away:
            return False
        if self._go_nearby_interaction is not None and not self._go_nearby_interaction.is_finishing:
            return False
        social_group = self._get_social_group_for_this_interaction()
        if social_group is not None and self.sim in social_group:
            return False
        self._trying_to_go_nearby_target = True
        try:
            target_sim = self.target_sim
            if target_sim is None:
                return False
            if self._go_nearby_interaction is not None:
                transition_failed = self._go_nearby_interaction.transition_failed
                self._interactions.discard(self._go_nearby_interaction)
                self._go_nearby_interaction = None
                if transition_failed:
                    self.sim.add_lockout(target_sim, autonomy.autonomy_modes.AutonomyMode.LOCKOUT_TIME)
                    self.cancel(FinishingType.TRANSITION_FAILURE, 'SocialSuperInteraction: Failed to _get_close_to_target.')
                    return False
            if target_sim.intended_location is not None:
                distance_to_intended = estimate_distance_between_points(target_sim.position, target_sim.routing_surface, target_sim.intended_location.transform.translation, target_sim.intended_location.routing_surface)
                if distance_to_intended is not None and distance_to_intended > LOSAndSocialConstraintTuning.maximum_intended_distance_to_route_nearby:
                    target_running = target_sim.queue.running
                    if target_running is None or can_priority_displace(self.priority, target_running.priority):
                        self._target_was_going_far_away = True
                        return False
                target_sim_position = target_sim.intended_location.transform.translation
                target_sim_routing_surface = target_sim.intended_location.routing_surface
            else:
                target_sim_position = target_sim.position
                target_sim_routing_surface = target_sim.routing_surface
            if not force:
                distance = (self.sim.position - target_sim_position).magnitude()
                if distance < LOSAndSocialConstraintTuning.constraint_expansion_amount and target_sim.can_see(self.sim):
                    return False
            ideal_radius = socials.group.SocialGroup.IDEAL_JOIN_RADIUS_MULTIPLIER*self._social_group_type.radius_scale
            constraint_circle = interactions.constraints.Circle(target_sim_position, LOSAndSocialConstraintTuning.constraint_expansion_amount, target_sim_routing_surface, ideal_radius=ideal_radius)
            constraint_facing = interactions.constraints.Facing(target_sim, target_position=target_sim_position, facing_range=sims4.math.PI*2)
            constraint_los = target_sim.los_constraint
            total_constraint = constraint_circle.intersect(constraint_facing).intersect(constraint_los)
            total_constraint = total_constraint.intersect(STAND_OR_SIT_CONSTRAINT)
            if not total_constraint.valid:
                return False
            context = InteractionContext(self.sim, InteractionContext.SOURCE_SCRIPT, self.priority, insert_strategy=QueueInsertStrategy.FIRST, cancel_if_incompatible_in_queue=True, must_run_next=True)
            wave_hi_animation = None
            if not self._waved_hi:
                if self.social_start_animation.greet_animation is not None:
                    wave_hi_animation = (self.social_start_animation.greet_animation(self), flush_all_animations)
                    if self.social_start_animation.focus is not None:
                        wave_hi_animation = self.social_start_animation.focus(self, sequence=wave_hi_animation)
                self._waved_hi = True
            result = self.sim.push_super_affordance(SatisfyConstraintSuperInteraction, None, context, constraint_to_satisfy=total_constraint, allow_posture_changes=True, run_element=wave_hi_animation, set_work_timestamp=False, name_override='WaitNearby')
            interaction = result.interaction
            if interaction is None or interaction.is_finishing:
                return False
            intended_position_liability = IntendedPositionLiability(interaction, target_sim)
            interaction.add_liability(INTENDED_POSITION_LIABILITY, intended_position_liability)
            self._go_nearby_interaction = interaction
            self._interactions.add(interaction)
            return True
        finally:
            self._trying_to_go_nearby_target = False

    def _cancel_waiting_alarm(self):
        self._waiting_start_time = None
        if self._waiting_alarm is not None:
            alarms.cancel_alarm(self._waiting_alarm)
            self._waiting_alarm = None
        if self._go_nearby_interaction is not None:
            self._go_nearby_interaction.cancel(FinishingType.SOCIALS, 'Canceled')
            self._interactions.discard(self._go_nearby_interaction)
            self._go_nearby_interaction = None

    def _check_target_status(self, *args, **kwargs):
        if self.pipeline_progress > PipelineProgress.QUEUED:
            self._cancel_waiting_alarm()
            return
        now = services.time_service().sim_now
        maximum_wait_time = LOSAndSocialConstraintTuning.incompatible_target_sim_maximum_time_to_wait
        if now - self._waiting_start_time > clock.interval_in_sim_minutes(maximum_wait_time):
            self.cancel(FinishingType.INTERACTION_INCOMPATIBILITY, 'Timeout due to incompatibility.')
            self._cancel_waiting_alarm()
        self._get_close_to_target()

    def _create_route_nearby_check_alarm(self):
        if self._waiting_alarm is None:
            self._waiting_start_time = services.time_service().sim_now
            route_nearby_frequency = LOSAndSocialConstraintTuning.incompatible_target_sim_route_nearby_frequency
            self._waiting_alarm = alarms.add_alarm(self, clock.interval_in_sim_minutes(route_nearby_frequency), self._check_target_status, repeating=True)
            self._get_close_to_target(force=self.sim.posture.mobile)

    def on_incompatible_in_queue(self):
        super().on_incompatible_in_queue()
        if self.sim in self.get_sims_with_invalid_paths():
            return
        self._create_route_nearby_check_alarm()

    @classmethod
    def _get_social_group_for_sim(cls, sim):
        for social_group in sim.get_groups_for_sim_gen():
            while type(social_group) is cls._social_group_type:
                if social_group.has_been_shutdown:
                    pass
                return social_group

    @classmethod
    def _verify_tuning_callback(cls):
        super()._verify_tuning_callback()
        if cls._social_group_type is None:
            logger.error('Tuning: Social interaction has no Social Group Type tuned: {}', cls.__name__)

    @flexmethod
    def _test(cls, inst, target, context, initiated=True, join=False, **kwargs):
        if target is context.sim:
            return TestResult(False, 'Cannot run a social as a self interaction.')
        if target is None:
            return TestResult(False, 'Cannot run a social with no target.')
        sim = inst.sim if inst is not None else context.sim
        social_group = cls._get_social_group_for_sim(sim)
        if context.source == context.SOURCE_AUTONOMY and social_group is not None and target in social_group:
            attached_si = social_group.get_si_registered_for_sim(sim, affordance=cls)
            if attached_si is not None:
                if inst is not None:
                    if attached_si is not inst:
                        return TestResult(False, 'Cannot run social since sim already has an interaction that is registered to group.')
                        return TestResult(False, 'Sim {} is already running matching affordance:{} ', sim, cls)
                else:
                    return TestResult(False, 'Sim {} is already running matching affordance:{} ', sim, cls)
        inst_or_cls = inst if inst is not None else cls
        return super(SuperInteraction, inst_or_cls)._test(target, context, initiated=initiated, **kwargs)

    @classmethod
    def visual_targets_gen(cls, target, context, **kwargs):
        if cls.target_type & TargetType.ACTOR:
            yield context.sim
        elif cls.target_type & TargetType.TARGET and isinstance(target, sims.sim.Sim):
            yield target
        else:
            for group in context.sim.get_groups_for_sim_gen():
                for sim in group:
                    yield sim

    @classproperty
    def requires_target_support(cls):
        return False

    @flexmethod
    def is_linked_to(cls, inst, super_affordance):
        if inst is not None:
            target_sim = inst.target_sim
            if target_sim is not None:
                target_social_group = inst._get_social_group_for_sim(target_sim)
                if target_social_group is not None:
                    social_group = inst._get_social_group_for_sim(inst.sim)
                    if social_group is not None and target_social_group is not social_group:
                        return False
        inst_or_cls = inst if inst is not None else cls
        return super(SocialSuperInteraction, inst_or_cls).is_linked_to(super_affordance)

    @flexmethod
    @assertions.not_recursive_gen
    def _constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        inst_or_cls = inst if inst is not None else cls
        if participant_type == ParticipantType.Actor and cls.relocate_main_group and (inst is None or inst.pipeline_progress < PipelineProgress.RUNNING):
            for constraint in super(SuperInteraction, inst_or_cls)._constraint_gen(sim, target, participant_type=participant_type):
                yield constraint
            return
        if inst is None or inst.social_group is None or not inst.social_group.constraint_initialized:
            for constraint in super(SuperInteraction, inst_or_cls)._constraint_gen(sim, target, participant_type=participant_type):
                yield constraint
            if inst is not None and inst.is_finishing:
                return
            actor = None
            if inst is not None:
                actor = inst.sim
                target = inst.target_sim
            if participant_type == ParticipantType.Actor:
                actor = sim
            if sim is not None and participant_type == ParticipantType.TargetSim:
                target = sim
            if target is None or not target.is_sim:
                return
            if actor is not None and actor is not target:
                (fallback_position, fallback_routing_surface) = get_fallback_social_constraint_position(actor, target, inst)
            else:
                fallback_position = None
            if fallback_position is None:
                if inst is not None:
                    yield Constraint(allow_geometry_intersections=False)
                return
            if inst is not None:
                picked_object = inst.picked_object
            else:
                picked_object = None
            fallback_constraint = cls._social_group_type.make_constraint_default(actor, target, fallback_position, fallback_routing_surface, participant_type=participant_type, picked_object=picked_object, participant_slot_overrides=inst_or_cls._social_group_participant_slot_overrides)
            priority = inst.priority if inst is not None else None
            if sim.si_state.is_compatible_constraint(fallback_constraint, priority=priority, to_exclude=inst) and target.is_sim and target.si_state.is_compatible_constraint(fallback_constraint, priority=priority, to_exclude=inst):
                yield fallback_constraint
            else:
                yield Constraint(allow_geometry_intersections=False)
            return
        if participant_type == ParticipantType.TargetSim:
            if not cls.acquire_targets_as_resource:
                yield Anywhere()
                return
            if inst is not None:
                (target_si, test_result) = inst.get_target_si()
                if not test_result:
                    yield Nowhere()
                    return
                if target_si is not None:
                    target_si_target = target_si.get_participant(ParticipantType.TargetSim)
                    for constraint in target_si.constraint_gen(sim, target_si_target, participant_type=ParticipantType.Actor):
                        yield constraint
                    return
            for constraint in super(SuperInteraction, cls)._constraint_gen(sim, target, participant_type=participant_type):
                yield constraint
            if inst is not None:
                if inst.social_group is not None:
                    yield inst.social_group.get_constraint(sim)
                else:
                    logger.error('Attempt to get constraint from Social interaction and no constraint exists: {}', inst, owner='maxr')
                    yield Anywhere()
                    return
        elif participant_type == ParticipantType.Actor:
            for constraint in super(SuperInteraction, inst_or_cls)._constraint_gen(sim, target, participant_type=participant_type):
                yield constraint
            if inst is not None:
                if inst.social_group is not None and participant_type == ParticipantType.Actor:
                    yield inst.social_group.get_constraint(sim)

    @flexmethod
    def apply_posture_state_and_interaction_to_constraint(cls, inst, posture_state, intersection, participant_type=ParticipantType.Actor, **kwargs):
        if inst is None:
            return intersection.apply_posture_state(posture_state, cls.get_constraint_resolver(posture_state, participant_type=participant_type, **kwargs))
        if participant_type == ParticipantType.TargetSim:
            (target_si, test_result) = inst.get_target_si()
            if not test_result:
                return Nowhere()
            if target_si is not None and (posture_state is None or posture_state.sim is target_si.sim):
                return target_si.apply_posture_state_and_interaction_to_constraint(posture_state, intersection, participant_type=ParticipantType.Actor, **kwargs)
        inst_or_cls = inst if inst is not None else cls
        return super(SuperInteraction, inst_or_cls).apply_posture_state_and_interaction_to_constraint(posture_state, intersection, participant_type=participant_type, **kwargs)

    @classmethod
    def has_pie_menu_sub_interactions(cls, target, context, **kwargs):
        return autonomy.content_sets.any_content_set_available(context.sim, cls, None, context, potential_targets=(target,), include_failed_aops_with_tooltip=True)

    @classmethod
    def potential_pie_menu_sub_interactions_gen(cls, target, context, **aop_kwargs):
        content_set = autonomy.content_sets.generate_content_set(context.sim, cls, None, context, potential_targets=(target,), include_failed_aops_with_tooltip=True, push_super_on_prepare=True, check_posture_compatibility=True, aop_kwargs=aop_kwargs)
        for (_, aop, test_result) in content_set:
            yield (aop, test_result)

    def apply_posture_state(self, posture_state, participant_type=ParticipantType.Actor, **kwargs):
        if participant_type == ParticipantType.TargetSim:
            (target_si, test_result) = self.get_target_si()
            if target_si is not None and not test_result and posture_state is not None:
                posture_state.add_constraint(target_si, Nowhere())
            if target_si is not None:
                return target_si.apply_posture_state(posture_state, participant_type=ParticipantType.Actor, **kwargs)
        return super().apply_posture_state(posture_state, participant_type=participant_type, **kwargs)

    @classmethod
    def supports_posture_type(cls, *args, **kwargs):
        return True

    def should_visualize_interaction_for_sim(self, participant_type):
        return participant_type == ParticipantType.Actor

    def notify_queue_head(self):
        super().notify_queue_head()
        if self.sim in self.get_sims_with_invalid_paths():
            return
        target_sim = self.target_sim
        if target_sim is not None and target_sim.queue.running is not None and can_priority_displace(self.priority, target_sim.queue.running.priority):
            target_sim.queue.running.displace(self, cancel_reason_msg='Target of higher priority social')
        self._get_close_to_target()

    def _get_social_group_for_this_interaction(self):
        social_group = None
        target_sim = self.get_participant(ParticipantType.TargetSim)
        if target_sim is None:
            target_sim = self.get_participant(ParticipantType.JoinTarget)
        if target_sim is not None:
            social_group = self._get_social_group_for_sim(target_sim)
        if social_group is None:
            social_group = self._get_social_group_for_sim(self.sim)
            if social_group is None:
                if target_sim is None:
                    while True:
                        for participant in self.get_participants(ParticipantType.OtherSimsInteractingWithTarget):
                            social_group = self._get_social_group_for_sim(participant)
                            while social_group is not None:
                                break
        target_object = self.get_participant(ParticipantType.Object)
        if social_group is None and target_object is not None:
            for existing_social_group in services.social_group_manager().objects:
                while type(existing_social_group) is self._social_group_type:
                    if target_object is existing_social_group.anchor:
                        social_group = existing_social_group
        if social_group is not None and (not social_group.has_room_in_group(self.sim) or target_sim is not None and not social_group.has_room_in_group(target_sim)):
            social_group = None
        return social_group

    def _derail_on_target_sim_posture_change(self, *args, **kwargs):
        target_sim = self.target_sim
        if target_sim is None:
            return
        if self.transition is None:
            return
        if target_sim in self.transition.get_transitioning_sims() != self._is_target_sim_location_and_posture_valid():
            return
        if target_sim not in self.transition.get_transitioning_sims() and self._is_target_sim_location_and_posture_valid():
            return
        if self.transition is not None:
            self.transition.derail(DerailReason.PREEMPTED, self.sim)
            self.transition.derail(DerailReason.PREEMPTED, self.target_sim)

    def _register_derail_on_target_sim_posture_change(self):
        target_sim = self.target_sim
        if target_sim is None:
            return
        if self._derail_on_target_sim_posture_change not in target_sim.on_posture_event:
            target_sim.on_posture_event.append(self._derail_on_target_sim_posture_change)
        if self._derail_on_target_sim_posture_change not in target_sim.on_intended_location_changed:
            target_sim.on_intended_location_changed.append(self._derail_on_target_sim_posture_change)

    def _unregister_derail_on_target_sim_posture_change(self):
        target_sim = self.target_sim
        if target_sim is None:
            return
        if self._derail_on_target_sim_posture_change in target_sim.on_posture_event:
            target_sim.on_posture_event.remove(self._derail_on_target_sim_posture_change)
        if self._derail_on_target_sim_posture_change in target_sim.on_intended_location_changed:
            target_sim.on_intended_location_changed.remove(self._derail_on_target_sim_posture_change)

    def _is_target_sim_location_and_posture_valid(self):
        target_sim = self.target_sim
        if target_sim.is_moving:
            return False
        interaction_constraint = self.constraint_intersection(target_sim, posture_state=None, participant_type=ParticipantType.TargetSim)
        target_sim_transform = interactions.constraints.Transform(target_sim.transform, routing_surface=target_sim.routing_surface)
        target_sim_posture_constraint = target_sim.posture_state.posture_constraint_strict
        intersection = interaction_constraint.intersect(target_sim_transform).intersect(target_sim_posture_constraint)
        return intersection.valid

    def _get_required_sims(self, for_threading=False):
        required_sims = super()._get_required_sims()
        if not self.initiated or not self.basic_content.staging or not for_threading:
            return required_sims
        target_sim = self.target_sim
        if target_sim is None:
            return required_sims
        current_constraint = target_sim.posture_state.constraint_intersection
        if not any(constraint.geometry is not None for constraint in current_constraint):
            return required_sims
        if self._is_target_sim_location_and_posture_valid():
            required_sims = set(required_sims)
            required_sims.discard(target_sim)
            required_sims = frozenset(required_sims)
        self._register_derail_on_target_sim_posture_change()
        return required_sims

    def get_idle_behavior(self):
        if self.social_group is None:
            return
        for sim in self.social_group:
            if sim is self.sim:
                pass
            while sim.queue.running is not None and sim.queue.running.is_social:
                break
        return
        return super().get_idle_behavior()

    def _choose_social_group(self):
        social_group = self.social_group
        if social_group is None:
            social_group = self._get_social_group_for_this_interaction()
            if social_group is None:
                target_sim = self.get_participant(ParticipantType.TargetSim)
                social_group = self._social_group_type(si=self, target_sim=target_sim, participant_slot_overrides=self._social_group_participant_slot_overrides)
            self._social_group = social_group
            self.refresh_constraints()
        self.social_group.on_constraint_changed.append(self.refresh_constraints)
        self.social_group.attach(self)

    def prepare_gen(self, timeline, *args, **kwargs):
        result = yield super().prepare_gen(timeline, *args, **kwargs)
        if result != InteractionQueuePreparationStatus.SUCCESS:
            return result
        self._choose_social_group()
        (target_si, target_si_test_result) = self.get_target_si()
        if target_si is not None:
            if not target_si_test_result:
                return False
            if target_si._social_group is not None and target_si._social_group is not self.social_group:
                logger.error('Social group mismatch between Sim and TargetSim in social_super_interaction.prepare')
            target_si._social_group = self.social_group
            result = yield target_si.prepare_gen(timeline, *args, **kwargs)
        return result

    def _pre_perform(self):
        result = super()._pre_perform()
        self._unregister_derail_on_target_sim_posture_change()
        social_group = self.social_group
        if social_group is None:
            logger.error('SocialSuperInteraction is trying to run without a social group: {}', self, owner='maxr')
            return False
        if self.multi_sim_override_data is not None and (self.multi_sim_override_data.icon is not None or self.multi_sim_override_data.display_text is not None):
            self._on_social_group_changed(social_group)
        social_group.on_group_changed.append(self._on_social_group_changed)
        return result

    def get_multi_sim_icon_and_name(self):
        icon_info = None
        display_text = None
        if self.multi_sim_override_data.icon is not None:
            icon_info = (self.multi_sim_override_data.icon, None)
        if self.multi_sim_override_data.display_text is not None:
            sim_names = []
            actor = self.sim
            for sim in self.social_group:
                if sim is actor:
                    pass
                sim_names.append(sims4.localization.LocalizationHelperTuning.get_sim_name(sim))
            sim_names_loc = sims4.localization.LocalizationHelperTuning.get_comma_separated_list(*sim_names)
            display_text = self.multi_sim_override_data.display_text(sim_names_loc)
        return (icon_info, display_text)

    def _run_interaction_gen(self, timeline):
        if not self.is_finishing:
            if self.social_group is not None:
                self.social_group.on_social_super_interaction_run()
            else:
                logger.error('{} is running and has no social group. This should never happen!', self, owner='maxr')
                self.cancel(FinishingType.SOCIALS, 'Social Group is None in _run_interaction_gen')
        yield super()._run_interaction_gen(timeline)

    def _retarget_social_interaction(self, social_group):
        actor = self.sim
        target_is_sim = self.target is not None and self.target.is_sim
        if target_is_sim and self.target not in social_group:
            for target in social_group:
                if actor is target:
                    pass
                self.set_target(target)
                break

    def _on_social_group_changed(self, social_group):
        if social_group is None:
            return
        actor = self.sim
        actor.invalidate_mixer_interaction_cache(None)
        self._retarget_social_interaction(social_group)
        if self.multi_sim_override_data is not None and len(social_group) > self.multi_sim_override_data.threshold:
            (icon_info, display_name) = self.get_multi_sim_icon_and_name()
            actor.ui_manager.set_interaction_icon_and_name(self.id, icon_info, display_name)
        else:
            (_, visual_type_data) = self.get_interaction_queue_visual_type()
            if visual_type_data.icon is not None:
                icon_info = (visual_type_data.icon, None)
            else:
                icon_info = self.get_icon_info()
            if visual_type_data.tooltip_text is not None:
                display_name = self.create_localized_string(visual_type_data.tooltip_text)
            else:
                display_name = self.get_name()
            actor.ui_manager.set_interaction_icon_and_name(self.id, icon_info, display_name)

    @property
    def initiated(self):
        return self._initiated

    @classproperty
    def is_social(cls):
        return True

    @property
    def social_group(self):
        return self._social_group

    @property
    def picked_object(self):
        if self._picked_object_ref is not None:
            return self._picked_object_ref()

    def get_potential_mixer_targets(self):
        potential_targets = set()
        if self.social_group is not None:
            group_leader = self.social_group.group_leader_sim
            if group_leader is None or self.sim is group_leader:
                while True:
                    for sim in self.social_group:
                        si = self.social_group.get_si_registered_for_sim(sim)
                        while si is not None and not si.is_finishing:
                            potential_targets.add(sim)
        if self.target is not None:
            if not self.target.is_sim:
                potential_targets.add(self.target)
            elif self.pipeline_progress < PipelineProgress.STAGED:
                potential_targets.add(self.target)
        return potential_targets

    @classproperty
    def linked_interaction_type(cls):
        linked_interaction_type = cls.affordance_to_push_on_target
        if isinstance(linked_interaction_type, bool):
            if linked_interaction_type and not issubclass(cls, JoinInteraction):
                linked_interaction_type = cls
            else:
                return
        basic_content = cls.basic_content
        if not basic_content.staging and basic_content.sleeping and linked_interaction_type is not None:
            linked_interaction_type = SocialPlaceholderSuperInteraction.generate(linked_interaction_type)
        return linked_interaction_type

    @property
    def canceling_incurs_opportunity_cost(self):
        return True

    def get_target_si(self):
        if self._target_si is None:
            (aop, context) = self._get_target_aop_and_context()
            if aop is not None and context is not None:
                (_, self._target_si, _) = aop.interaction_factory(context)
                self._target_si_test_result = aop.test(context, skip_safe_tests=True)
            else:
                (self._target_si, self._target_si_test_result) = super().get_target_si()
        elif self.social_group is not None:
            target_sim = self._target_si.sim
            if target_sim is not None and self.social_group.is_sim_active_in_social_group(target_sim):
                self._target_si.invalidate()
                self._target_si = None
                self._target_si_test_result = True
        return (self._target_si, self._target_si_test_result)

    def _get_target_aop_and_context(self):
        target_affordance = self.linked_interaction_type
        target_sim = self.get_participant(ParticipantType.TargetSim)
        if not self.initiated or target_affordance is None or target_sim is None:
            return (None, None)
        if self.social_group is not None and self.social_group.is_sim_active_in_social_group(target_sim):
            return (None, None)
        target_context = interactions.context.InteractionContext(target_sim, self.context.source, self.priority, group_id=self.group_id, insert_strategy=QueueInsertStrategy.NEXT)
        target_aop = interactions.aop.AffordanceObjectPair(target_affordance, self.sim, target_affordance, None, social_group=self.social_group, initiated=False, source_social_si=self, picked_object=self.picked_object, disable_saving=True)
        return (target_aop, target_context)

    def run_additional_social_affordance_gen(self, timeline):
        affordance = self.additional_social_to_run_on_both
        if affordance is None:
            return
        target_sim = self.get_participant(ParticipantType.TargetSim)
        sim_context = self.context.clone_for_sim(self.sim)
        sim_aop = interactions.aop.AffordanceObjectPair(affordance, target_sim, affordance, None, initiated=True)
        sim_execute_result = sim_aop.interaction_factory(sim_context)
        if sim_execute_result:
            sim_si = sim_execute_result.interaction
            (target_si, target_test_result) = sim_si.get_target_si()
            if target_test_result and target_si is not None:
                yield sim_si.run_direct_gen(timeline, source_interaction=self)
                yield target_si.run_direct_gen(timeline, source_interaction=self)
                return True
        return False

    def _entered_pipeline(self):
        if self._social_group is not None:
            self._social_group.attach(self)
        return super()._entered_pipeline()

    def _exited_pipeline(self):
        super()._exited_pipeline()
        self._detach_from_group()
        if self._target_si is not None and self._target_si.pipeline_progress == PipelineProgress.NONE:
            self._target_si.on_removed_from_queue()
            self._target_si = None
        self._cancel_waiting_alarm()
        self._unregister_derail_on_target_sim_posture_change()

    def _cancel(self, finishing_type, *args, propagate_cancelation_to_socials=True, **kwargs):
        if super()._cancel(finishing_type, *args, **kwargs):
            self._detach_from_group()
            if finishing_type == FinishingType.USER_CANCEL and self._source_social_si is not None:
                self._source_social_si.sim.add_lockout(self.sim, autonomy.autonomy_modes.AutonomyMode.LOCKOUT_TIME)
                self.sim.add_lockout(self._source_social_si.sim, autonomy.autonomy_modes.AutonomyMode.LOCKOUT_TIME)
        elif propagate_cancelation_to_socials and self._social_group is not None:
            group_count = len(self._social_group) - 1
            if group_count < self._social_group.minimum_sim_count:
                while True:
                    for interaction in list(self._social_group.get_all_interactions_gen()):
                        while interaction is not self:
                            interaction.cancel(finishing_type, propagate_cancelation_to_socials=False, cancel_reason_msg='Propagating social cancelation pending deferred cancel from running')

    def _trigger_interaction_start_event(self):
        super()._trigger_interaction_start_event()
        if self.linked_interaction_type is None:
            sim = self.get_participant(ParticipantType.TargetSim)
            if sim is not None:
                services.get_event_manager().process_event(test_events.TestEvent.InteractionStart, sim_info=sim.sim_info, interaction=self, custom_keys=self.get_keys_to_process_events())
                self._register_target_event_auto_update()

    def _detach_from_group(self):
        if self.social_group is not None:
            if self.refresh_constraints in self.social_group.on_constraint_changed:
                self.social_group.on_constraint_changed.remove(self.refresh_constraints)
            if self._on_social_group_changed in self.social_group.on_group_changed:
                self.social_group.on_group_changed.remove(self._on_social_group_changed)
            self.social_group.detach(self)
            self._social_group = None

    def _get_similar_interaction(self):
        for interaction in self.sim.running_interactions_gen(self.get_interaction_type()):
            while interaction is not self:
                return interaction
                break
        return self

    def get_attention_cost(self):
        attention_cost = super().get_attention_cost()
        social_context_bit = self.sim.get_social_context()
        if social_context_bit is not None:
            attention_cost += social_context_bit.attention_cost
        return attention_cost

    def _build_pre_elements(self):

        def cancel_if_running_similar_interaction(_):
            similar_interaction = self._get_similar_interaction()
            if similar_interaction is not self:
                similar_interaction.cancel(FinishingType.SOCIALS, cancel_reason_msg='Similar Social SI: {} already running'.format(similar_interaction))

        return cancel_if_running_similar_interaction

    def run_pre_transition_behavior(self):
        result = super().run_pre_transition_behavior()
        if self.invite_in_after_interaction is False:
            return result
        if result:
            target_sim = self.get_participant(ParticipantType.TargetSim)
            if target_sim is not None and (self.is_user_directed and (target_sim.is_npc and (not target_sim.sim_info.lives_here and (self.sim.sim_info.lives_here or services.get_zone_situation_manager().is_player_greeted())))) and self.sim.is_on_active_lot():
                has_full_permissions = True
                for role in target_sim.autonomy_component.active_roles():
                    while not role.has_full_permissions:
                        has_full_permissions = False
                        break
                if not has_full_permissions:
                    self.add_liability(situations.situation_liabilities.AUTO_INVITE_LIABILTIY, situations.situation_liabilities.AutoInviteLiability())
        return result

class TakeObjectFromHandInteraction(SocialSuperInteraction):
    __qualname__ = 'TakeObjectFromHandInteraction'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        liability = CancelInteractionsOnExitLiability()
        self.add_liability(CANCEL_INTERACTION_ON_EXIT_LIABILITY, liability)
        liability.add_cancel_entry(self.depended_on_si.context.sim, self.depended_on_si)

    @property
    def carry_target(self):
        return self.depended_on_si.target

class SocialPlaceholderSuperInteraction(ProxyInteraction):
    __qualname__ = 'SocialPlaceholderSuperInteraction'
    INSTANCE_SUBCLASSES_ONLY = True

    @classmethod
    def generate(cls, proxied_affordance):
        result = super().generate(proxied_affordance)
        basic_content = proxied_affordance.basic_content
        basic_content_kwargs = {key: getattr(basic_content, key) for key in basic_content.AUTO_INIT_KWARGS}
        basic_content_kwargs['content'] = StagingContent.EMPTY
        result.basic_content = FlexibleLengthContent(**basic_content_kwargs)
        return result

