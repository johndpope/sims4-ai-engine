from collections import OrderedDict
from protocolbuffers import GameplaySaveData_pb2 as gameplay_serialization
import operator
from animation.posture_manifest import Hand
from date_and_time import DateAndTime
from distributor.rollback import ProtocolBufferRollback
from event_testing.results import TestResult, ExecuteResult
from interactions import ParticipantType, PipelineProgress
from interactions.constraints import Anywhere, Nowhere, ANYWHERE
from interactions.context import InteractionSource
from interactions.interaction_finisher import FinishingType
from interactions.priority import Priority
from sims4.callback_utils import consume_exceptions, CallableList
from singletons import DEFAULT
import caches
import carry
import elements
import interactions.base.interaction
import postures
import role
import scheduling
import services
import sims4.log
__all__ = ['SIState']
logger = sims4.log.Logger('SIState')

def can_priority_displace(priority_new, priority_existing, allow_clobbering=False):
    if priority_new is None:
        return False
    if allow_clobbering:
        return priority_new >= priority_existing
    return priority_new > priority_existing

class SIState:
    __qualname__ = 'SIState'

    @staticmethod
    def _are_dissimilar_and_linked(si_a, si_b):
        if si_a.affordance == si_b.affordance or not si_a.super_affordance_can_share_target and not si_b.super_affordance_can_share_target:
            target_a = si_a.target
            target_b = si_b.target
            if target_a == target_b:
                return False
            if target_a is not None and target_a.is_same_object_or_part(target_b):
                return False
        if not si_a.affordance.is_linked_to(si_b.affordance):
            return False
        return True

    @staticmethod
    def test_non_constraint_compatibility(si_a, si_b):
        if not SIState._are_dissimilar_and_linked(si_a, si_b):
            return False
        return True

    @staticmethod
    def _get_constraint_intersection_for_sis(si_a, si_b, participant_type_a=ParticipantType.Actor, participant_type_b=ParticipantType.Actor, existing_intersection=DEFAULT, for_sim=DEFAULT):
        if existing_intersection is DEFAULT:
            existing_intersection = si_a.constraint_intersection(sim=for_sim, participant_type=participant_type_a, posture_state=None)
        constraint_resolver_b = si_b.get_constraint_resolver(None, participant_type=participant_type_b)
        existing_intersection = existing_intersection.apply_posture_state(None, constraint_resolver_b)
        si_b_constraint = si_b.constraint_intersection(sim=for_sim, participant_type=participant_type_b, posture_state=None)
        if si_a is not None:
            constraint_resolver_a = si_a.get_constraint_resolver(None, participant_type=participant_type_a)
            si_b_constraint = si_b_constraint.apply_posture_state(None, constraint_resolver_a)
        intersection = existing_intersection.intersect(si_b_constraint)
        return intersection

    @staticmethod
    def _test_constraint_intersection(si_a, si_b, participant_type_a=ParticipantType.Actor, participant_type_b=ParticipantType.Actor, existing_intersection=DEFAULT, for_sim=DEFAULT):
        intersection = SIState._get_constraint_intersection_for_sis(si_a, si_b, participant_type_a=participant_type_a, participant_type_b=participant_type_b, existing_intersection=existing_intersection, for_sim=for_sim)
        return bool(intersection.valid)

    @staticmethod
    def are_sis_compatible(si_a, si_b, participant_type_a=ParticipantType.Actor, participant_type_b=ParticipantType.Actor, ignore_geometry=False, for_sim=DEFAULT):
        if not SIState.test_non_constraint_compatibility(si_a, si_b):
            return False
        cancel_aop_liability_a = si_a.get_liability(interactions.base.interaction.CANCEL_AOP_LIABILITY)
        if cancel_aop_liability_a is not None and cancel_aop_liability_a.interaction_to_cancel is si_b:
            return False
        cancel_aop_liability_b = si_b.get_liability(interactions.base.interaction.CANCEL_AOP_LIABILITY)
        if cancel_aop_liability_b is not None and cancel_aop_liability_b.interaction_to_cancel is si_a:
            return False
        if ignore_geometry:
            return True
        return SIState._test_constraint_intersection(si_a, si_b, participant_type_a=participant_type_a, participant_type_b=participant_type_b, for_sim=for_sim)

    @staticmethod
    def _get_actor_and_target_sim_from_si(si, sim=DEFAULT):
        sim = sim if sim is not DEFAULT else si.sim
        from interactions.base.super_interaction import SuperInteraction
        if isinstance(si, SuperInteraction):
            actor = si.get_participant(ParticipantType.Actor, sim=sim)
            target = si.get_participant(ParticipantType.TargetSim, sim=sim)
        else:
            actor = sim
            from sims.sim import Sim
            target = si.target if isinstance(si.target, Sim) else None
        if actor is target:
            target = None
        if target not in si.required_sims():
            target = None
        return (actor, target)

    @staticmethod
    def test_compatibility(si, **kwargs):
        (actor, target) = SIState._get_actor_and_target_sim_from_si(si)
        return SIState._test_compatibility(si, actor, target, si.priority, si.group_id, si.context, **kwargs)

    @staticmethod
    def _test_compatibility(si_or_aop, actor, target, priority, group_id, context, **kwargs):
        test_result = actor.si_state.is_compatible(si_or_aop, priority, group_id, context, **kwargs)
        if not test_result:
            return test_result
        if target is not None:
            test_result = target.si_state.is_compatible(si_or_aop, priority, group_id, context, participant_type=ParticipantType.TargetSim, **kwargs)
            return test_result
        return TestResult.TRUE

    @staticmethod
    def potential_canceled_interaction_ids(interaction):
        sim = interaction.sim
        posture = sim.posture_state.get_posture_for_si(interaction)
        if posture is None:
            return set()
        cancel_constraints = set()
        if posture is sim.posture_state.body:
            participant_type = interaction.get_participant_type(sim)
            for (cancel_aop, _, _) in posture.source_interaction._get_cancel_replacement_aops_contexts_postures():
                cancel_constraints.add(cancel_aop.constraint_intersection(sim=sim, participant_type=participant_type, posture_state=None))
        else:
            hand = Hand.LEFT if posture is sim.posture_state.left else Hand.RIGHT
            cancel_constraints.add(carry.create_carry_nothing_constraint(hand))
        if not cancel_constraints:
            return cancel_constraints
        to_be_canceled_si_ids = set()
        for si in sim.si_state:
            if si is interaction:
                pass
            participant_type = si.get_participant_type(sim)
            si_constraint = si.constraint_intersection(participant_type=participant_type, posture_state=None)
            for cancel_constraint in cancel_constraints:
                while not cancel_constraint.intersect(si_constraint).valid:
                    to_be_canceled_si_ids.add(si.id)
        return to_be_canceled_si_ids

    @staticmethod
    def resolve(si, must_add=False, pairwise_intersection=False):
        if must_add or SIState.test_compatibility(si, pairwise_intersection=pairwise_intersection):
            (actor, target) = SIState._get_actor_and_target_sim_from_si(si)
            actor.si_state._resolve(si, pairwise_intersection=pairwise_intersection)
            if target is not None:
                target.si_state._resolve(si, participant_type=ParticipantType.TargetSim)
            return True
        return False

    @staticmethod
    def add(si, **kwargs):
        if SIState.resolve(si, **kwargs):
            (actor, target) = SIState._get_actor_and_target_sim_from_si(si)
            actor.si_state._add(si)
            if target is not None and target is not actor and si.should_visualize_interaction_for_sim(ParticipantType.TargetSim):
                target.si_state._add(si, participant_type=ParticipantType.TargetSim)
            return True
        return False

    @staticmethod
    def remove_immediate(si):
        (actor, _) = SIState._get_actor_and_target_sim_from_si(si)

        def _remove_gen(timeline):
            result = yield actor.si_state._remove_gen(timeline, si, allow_yield=False)
            return result

        reset_timeline = scheduling.Timeline(services.time_service().sim_timeline.now)
        reset_timeline.schedule(elements.GeneratorElement(_remove_gen))
        reset_timeline.simulate(reset_timeline.now)
        if reset_timeline.heap:
            logger.error('On reset, remove_immediate timeline is not empty')

    @staticmethod
    def remove_gen(timeline, si):
        (actor, _) = SIState._get_actor_and_target_sim_from_si(si)
        yield actor.si_state._remove_gen(timeline, si, allow_yield=True)

    @staticmethod
    def on_interaction_canceled(si):
        (actor, target) = SIState._get_actor_and_target_sim_from_si(si)
        actor.si_state._on_interaction_canceled(si)
        if target is not None:
            target.si_state._on_interaction_canceled(si)

    def __init__(self, sim):
        self._super_interactions = set()
        self._removing_interactions = set()
        self._resetting = False
        self._sim = sim.ref() if sim else None
        self._watchers = {}
        self._constraints = {}
        self.on_changed = CallableList()

    @property
    def sim(self):
        if self._sim:
            return self._sim()

    def __contains__(self, key):
        return key in self._super_interactions

    def __len__(self):
        return len(self._super_interactions)

    def __iter__(self):
        return self._super_interactions.__iter__()

    def sis_actor_gen(self):
        return self.sis_for_role_gen(ParticipantType.Actor)

    def sis_for_role_gen(self, participant_type):
        if participant_type is None:
            for si in self:
                yield si
        else:
            for si in self:
                si_ptype = si.get_participant_type(self.sim)
                while participant_type & si_ptype:
                    yield si

    def _si_sort_key(self, si):
        is_active_si = not self.sim.posture_state.is_source_interaction(si)
        return (si.is_guaranteed(), si.priority, is_active_si, si.id)

    def _sis_sorted(self, sis):
        if not sis:
            return sis
        return sorted(sis, key=self._si_sort_key, reverse=True)

    def all_guaranteed_si_gen(self, *args, **kwargs):
        for si in self.all_si_gen(*args, **kwargs):
            while si.is_guaranteed():
                yield si

    def all_si_gen(self, priority=None, group_id=None):
        for si in self._super_interactions:
            if group_id is not None and si.group_id == group_id:
                pass
            while priority is None or not can_priority_displace(priority, si.priority):
                yield si

    def is_running_affordance(self, affordance, target=DEFAULT):
        return any(si.affordance is affordance and (target is DEFAULT or si.target == target) for si in self)

    def get_si_by_affordance(self, affordance):
        for si in self:
            while si.affordance is affordance:
                return si

    def _build_incompatible_constraint_sis(self, si, to_consider, participant_type=ParticipantType.Actor, force_concrete=False, context=DEFAULT, pairwise_intersection=False, constraint=None):
        incompatible_sis = set()
        if constraint is None:
            constraint = si.constraint_intersection(sim=self.sim, target=si.target, participant_type=participant_type, posture_state=None)
            if si.can_holster_incompatible_carries:
                constraint = constraint.get_holster_version()
        if constraint is ANYWHERE:
            return incompatible_sis
        if force_concrete:
            constraint = constraint.apply_posture_state(self.sim.posture_state, si.get_constraint_resolver(self.sim.posture_state, sim=self.sim, participant_type=participant_type), invalid_expected=True)
            if constraint.tentative or not constraint.valid:
                return set(to_consider)
        intersection = constraint
        for existing_si in self._sis_sorted(to_consider):
            if existing_si is si:
                pass
            if existing_si.disable_cancel_by_posture_change:
                pass
            role = existing_si.get_participant_type(self.sim)
            test_intersection = self._get_constraint_intersection_for_sis(si, existing_si, participant_type_a=participant_type, participant_type_b=role, existing_intersection=intersection)
            if test_intersection.valid:
                intersection = test_intersection
            else:
                incompatible_sis.add(existing_si)
        return incompatible_sis

    def is_compatible(self, si, priority, group_id, context, participant_type=ParticipantType.Actor, force_concrete=False, pairwise_intersection=False, force_inertial_sis=False):
        if not si.affordance.is_super:
            return TestResult(si.super_interaction in self, "Mixer's superinteraction is not in the si state.")
        if not force_inertial_sis:
            if context.continuation_id is not None and any(existing_si.id == context.continuation_id for existing_si in self):
                return TestResult.TRUE
            to_consider = []
            for existing_si in self.all_guaranteed_si_gen(priority, group_id=group_id):
                if si.super_affordance_klobberers and si.super_affordance_klobberers(existing_si.affordance):
                    pass
                to_consider.append(existing_si)
            return TestResult.TRUE
        else:
            to_consider = self._super_interactions
        for existing_si in to_consider:
            if existing_si is si:
                pass
            while not SIState.test_non_constraint_compatibility(si, existing_si):
                return TestResult(False, 'Failed test_non_constraint_compatibility check with {}', existing_si)
        if not si.affordance.immediate:
            incompatible_constraint_sis = self._build_incompatible_constraint_sis(si, to_consider, participant_type=participant_type, force_concrete=force_concrete, context=context, pairwise_intersection=pairwise_intersection)
            if incompatible_constraint_sis:
                return TestResult(False, 'incompatible constraint sis: {}', incompatible_constraint_sis)
        return TestResult.TRUE

    @caches.cached(maxsize=None)
    def is_compatible_constraint(self, constraint, priority=None, to_exclude=None):
        to_consider = []
        for existing_si in self.all_guaranteed_si_gen(priority):
            if existing_si is to_exclude:
                pass
            to_consider.append(existing_si)
        for si in to_consider:
            owned_posture = self.sim.posture_state.get_source_or_owned_posture_for_si(si)
            while owned_posture is not None and owned_posture.source_interaction and owned_posture.source_interaction not in to_consider:
                to_consider.append(owned_posture.source_interaction)
        incompatible_constraint_sis = self._build_incompatible_constraint_sis(None, to_consider, constraint=constraint)
        if incompatible_constraint_sis:
            return False
        return True

    def _get_incompatible(self, si_or_aop, sis, participant_type=ParticipantType.Actor, force_concrete=False, pairwise_intersection=False):
        if si_or_aop.affordance.immediate:
            return []
        incompatible = set()
        to_consider = []
        for existing_si in sis:
            while not existing_si is si_or_aop:
                if existing_si.is_finishing:
                    pass
                my_role = existing_si.get_participant_type(self.sim)
                if participant_type != ParticipantType.Actor or my_role != ParticipantType.Actor or self.test_non_constraint_compatibility(si_or_aop, existing_si):
                    to_consider.append(existing_si)
                else:
                    incompatible.add(existing_si)
        if to_consider:
            incompatible_constraint_sis = self._build_incompatible_constraint_sis(si_or_aop, to_consider, participant_type=participant_type, force_concrete=force_concrete, pairwise_intersection=pairwise_intersection)
            incompatible.update(incompatible_constraint_sis)
        return incompatible

    def get_incompatible(self, si_or_aop, participant_type=ParticipantType.Actor, pairwise_intersection=False):
        return self._get_incompatible(si_or_aop, self.sis_for_role_gen(participant_type), participant_type=participant_type, pairwise_intersection=pairwise_intersection)

    def _all_inertial_or_displaceble_sis_gen(self, priority):
        for existing_si in self._sis_sorted(self._super_interactions):
            if not existing_si.is_guaranteed():
                yield existing_si
            else:
                while can_priority_displace(priority, existing_si.priority):
                    yield existing_si

    def get_incompatible_nonguaranteed_sis(self, si, force_concrete):
        return self._get_incompatible(si, self._all_inertial_or_displaceble_sis_gen(si.priority), force_concrete=force_concrete)

    def _common_included_si_tests(self, si):
        if si.basic_content is None or not si.basic_content.staging:
            return False
        if si.is_finishing or si.has_active_cancel_replacement:
            return False
        return True

    def _get_must_include_sis(self, priority, group_id, existing_si=None):
        return set(si_mi for si_mi in self.all_guaranteed_si_gen(priority, group_id=group_id) if self._common_included_si_tests(si_mi) and (existing_si is None or existing_si.super_affordance_klobberers is None or not existing_si.super_affordance_klobberers(si_mi.affordance)))

    def get_combined_constraint(self, existing_constraint=None, priority=None, group_id=None, to_exclude=None, include_inertial_sis=False, force_inertial_sis=False, existing_si=None, posture_state=DEFAULT, allow_posture_providers=True, include_existing_constraint=True, participant_type=ParticipantType.Actor):
        included_sis = set()
        if include_inertial_sis:
            if existing_si is not None and any(si.id == existing_si.continuation_id for si in self):
                sis_must_include = set()
            else:
                sis_must_include = self._get_must_include_sis(priority, group_id, existing_si=existing_si)
            if force_inertial_sis:
                for si in self._super_interactions:
                    if si in sis_must_include:
                        pass
                    if not allow_posture_providers and self.sim.posture_state.is_source_interaction(si):
                        pass
                    if not self._common_included_si_tests(si):
                        pass
                    sis_must_include.add(si)
            to_consider = set()
            for non_guaranteed_si in self._super_interactions:
                if non_guaranteed_si in sis_must_include:
                    pass
                if not allow_posture_providers and self.sim.posture_state.is_source_interaction(non_guaranteed_si):
                    pass
                to_consider.add(non_guaranteed_si)
        else:
            sis_must_include = self._get_must_include_sis(priority, group_id, existing_si=existing_si)
            to_consider = set()
        if allow_posture_providers:
            additional_posture_sis = set()
            for si in sis_must_include:
                owned_posture = self.sim.posture_state.get_source_or_owned_posture_for_si(si)
                if owned_posture is None:
                    pass
                if owned_posture.track != postures.PostureTrack.BODY:
                    pass
                if owned_posture.source_interaction.is_finishing:
                    pass
                additional_posture_sis.add(owned_posture.source_interaction)
            sis_must_include.update(additional_posture_sis)
            additional_posture_sis.clear()
        total_constraint = Anywhere()
        included_carryables = set()
        for si_must_include in sis_must_include:
            if si_must_include.is_finishing:
                pass
            while not si_must_include is to_exclude:
                if si_must_include is existing_si:
                    pass
                if existing_si is not None and existing_si.group_id == si_must_include.group_id:
                    pass
                my_role = si_must_include.get_participant_type(self.sim)
                if existing_si is not None:
                    existing_participant_type = existing_si.get_participant_type(self.sim)
                    if not self.are_sis_compatible(si_must_include, existing_si, my_role, existing_participant_type, ignore_geometry=True):
                        return (Nowhere(), sis_must_include)
                si_constraint = si_must_include.constraint_intersection(participant_type=my_role, posture_state=posture_state)
                if existing_si is not None:
                    if (existing_si.should_rally or existing_si.relocate_main_group) and (si_must_include.is_social and si_must_include.social_group is not None) and si_must_include.social_group is si_must_include.sim.get_main_group():
                        si_constraint = si_constraint.generate_posture_only_constraint()
                    si_constraint = si_constraint.apply_posture_state(None, existing_si.get_constraint_resolver(None, participant_type=participant_type))
                if existing_constraint is not None:
                    si_constraint = si_constraint.apply(existing_constraint)
                test_constraint = total_constraint.intersect(si_constraint)
                if not test_constraint.valid:
                    break
                carry_target = si_must_include.targeted_carryable
                if carry_target is not None:
                    if len(included_carryables) == 2 and carry_target not in included_carryables:
                        pass
                    included_carryables.add(carry_target)
                total_constraint = test_constraint
                included_sis.add(si_must_include)
        if len(included_carryables) == 2 and existing_si is not None:
            existing_carry_target = existing_si.carry_target or existing_si.target
            if existing_carry_target is not None and existing_carry_target.carryable_component is not None:
                if existing_carry_target not in included_carryables:
                    total_constraint = Nowhere()
        if included_sis != sis_must_include:
            total_constraint = Nowhere()
        if not total_constraint.valid:
            return (total_constraint, included_sis)
        if total_constraint.tentative or existing_constraint is not None and existing_constraint.tentative:
            return (total_constraint, included_sis)
        if to_consider:
            for si in self._sis_sorted(to_consider):
                if si is to_exclude:
                    pass
                if existing_si is not None and existing_si.group_id == si.group_id:
                    pass
                if not self._common_included_si_tests(si):
                    pass
                my_role = si.get_participant_type(self.sim)
                if existing_si is not None:
                    existing_participant_type = existing_si.get_participant_type(self.sim)
                    if not self.are_sis_compatible(si, existing_si, my_role, existing_participant_type, ignore_geometry=True):
                        pass
                si_constraint = si.constraint_intersection(participant_type=my_role, posture_state=posture_state)
                if existing_si is not None:
                    si_constraint = si_constraint.apply_posture_state(None, existing_si.get_constraint_resolver(None, participant_type=participant_type))
                if si_constraint.tentative:
                    si_constraint = si.constraint_intersection(participant_type=my_role, posture_state=DEFAULT)
                test_constraint = total_constraint.intersect(si_constraint)
                if existing_constraint is not None:
                    test_constraint_plus_existing = test_constraint.intersect(existing_constraint)
                    while not not test_constraint_plus_existing.valid:
                        if test_constraint_plus_existing.tentative:
                            pass
                        test_constraint = test_constraint.apply(existing_constraint)
                        if test_constraint.valid:
                            total_constraint = test_constraint
                            included_sis.add(si)
                        while total_constraint.tentative:
                            break
                if test_constraint.valid:
                    total_constraint = test_constraint
                    included_sis.add(si)
                while total_constraint.tentative:
                    break
        if allow_posture_providers:
            additional_posture_sis = set()
            for si in included_sis:
                owned_posture = self.sim.posture_state.get_source_or_owned_posture_for_si(si)
                while owned_posture is not None and owned_posture.source_interaction not in included_sis and owned_posture.track == postures.PostureTrack.BODY:
                    additional_posture_sis.add(owned_posture.source_interaction)
            included_sis.update(additional_posture_sis)
        if include_existing_constraint and existing_constraint is not None:
            total_constraint = total_constraint.intersect(existing_constraint)
        return (total_constraint, included_sis)

    def get_total_constraint(self, **kwargs):
        (total_constraint, _) = self.get_combined_constraint(**kwargs)
        return total_constraint

    def get_best_constraint_and_sources(self, existing_constraint, existing_si, force_inertial_sis, ignore_inertial=False, participant_type=ParticipantType.Actor):
        (total_constraint, included_sis) = self.get_combined_constraint(existing_constraint, existing_si.priority, existing_si.group_id, None, not ignore_inertial, force_inertial_sis, existing_si=existing_si, posture_state=None, allow_posture_providers=False, include_existing_constraint=False, participant_type=participant_type)
        return (total_constraint, included_sis)

    def compatible_with(self, constraint):
        (total_constraint, _) = self.get_combined_constraint(constraint, None, None, None, True, True)
        return total_constraint.valid

    def has_finishing_super_interactions(self):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        for si in self._super_interactions:
            while si.is_finishing:
                return True
        return False

    def has_visible_si(self, ignore_pending_complete=False):
        for si in self.sis_actor_gen():
            if ignore_pending_complete and si.pending_complete:
                pass
            while si.visible:
                return True
        return False

    def process_gen(self, timeline):
        sis = tuple(self._super_interactions)
        for si in sis:
            si.process_events()
        for si in sis:
            while si.is_finishing:
                yield SIState.remove_gen(timeline, si)

    def _resolve(self, si, must_add=True, participant_type=ParticipantType.Actor, pairwise_intersection=False):
        incompatible = self._get_incompatible(si, self._super_interactions, participant_type=participant_type, pairwise_intersection=pairwise_intersection, force_concrete=True)
        for incompatible_si in incompatible:
            incompatible_si.displace(si)
        return True

    def _add(self, si, participant_type=ParticipantType.Actor):
        if si in self._super_interactions:
            logger.error('Double add of interaction to SIState: {0}', si)
            return False
        self._super_interactions.add(si)
        si.on_transferred_to_si_state(participant_type=participant_type)
        self.sim._social_group_constraint = None
        self.notify_dirty()
        self.on_changed(si)
        for interaction in self.sim.queue:
            while interaction.transition is not None and not interaction.transition.running:
                interaction.transition.reset_all_progress()
        return True

    def pre_resolve_posture_change(self, posture_state):
        incompatible = {}
        for si in self._super_interactions:
            if posture_state.sim.posture_state.is_source_or_owning_interaction(si):
                pass
            if si.disable_cancel_by_posture_change:
                pass
            my_role = si.get_participant_type(self.sim)
            while not si.performing and not si.is_finishing:
                result = si.supports_posture_state(posture_state, participant_type=my_role)
                if not result:
                    incompatible[si] = result
        for (interaction, result) in incompatible.items():
            interaction.cancel(FinishingType.INTERACTION_INCOMPATIBILITY, cancel_reason_msg='SI State incompatible with new posture. {}'.format(result))

    @staticmethod
    def _should_cancel_previous_posture_interaction(old_posture_interaction, new_posture_interaction):
        if old_posture_interaction is not None and old_posture_interaction is not new_posture_interaction:
            return True
        return False

    def notify_posture_change_and_remove_incompatible_gen(self, timeline, prev_posture_state, posture_state):
        incompatible = OrderedDict()
        for (aspect_old, aspect_new) in zip(prev_posture_state.aspects, posture_state.aspects):
            while aspect_old != aspect_new:
                if aspect_old is not None:
                    old_source_interaction = aspect_old.source_interaction
                    new_source_interaction = aspect_new.source_interaction
                    if self._should_cancel_previous_posture_interaction(old_source_interaction, new_source_interaction):
                        incompatible[old_source_interaction] = TestResult(False, 'Must cancel previous source interaction for {}', aspect_old)
                    while True:
                        for old_owning_interaction in aspect_old.owning_interactions:
                            while old_owning_interaction is not None and not old_owning_interaction.disable_cancel_by_posture_change:
                                if aspect_new.owning_interactions:
                                    for new_owning_interaction in aspect_new.owning_interactions:
                                        while self._should_cancel_previous_posture_interaction(old_owning_interaction, new_owning_interaction):
                                            incompatible[old_owning_interaction] = TestResult(False, 'Must cancel previous owning interaction for {}', aspect_old)
                                else:
                                    incompatible[old_owning_interaction] = TestResult(False, 'Must cancel previous owning interaction for {}', aspect_old)
        for si in self._super_interactions:
            my_role = si.get_participant_type(self.sim)
            while si not in incompatible and (not si.performing and (not si.is_finishing and not si.has_active_cancel_replacement)) and not si.disable_cancel_by_posture_change:
                result = si.supports_posture_state(posture_state, participant_type=my_role)
                if not result:
                    incompatible[si] = result
        for (si, result) in incompatible.items():
            if self.sim.queue.running is si:
                pass
            si.cancel(FinishingType.INTERACTION_INCOMPATIBILITY, immediate=True, cancel_reason_msg='SI State incompatible with new posture. {}'.format(result))
        yield self.process_gen(timeline)

    def on_reset(self):
        if self._resetting:
            return
        try:
            self._resetting = True
            super_interactions = list(self._super_interactions)
            for interaction in super_interactions:
                with consume_exceptions('SIState', 'Exception raised while clearing SIState:'):
                    interaction.on_reset()
            while self._super_interactions:
                logger.error('Super Interactions {} should be empty after a reset. List will be cleared.', self._super_interactions, owner='mduke')
                self._super_interactions.clear()
        finally:
            self._resetting = False

    def _remove_gen(self, timeline, si, participant_type=ParticipantType.Actor, allow_yield=True):
        if si.performing:
            si.log_info('SIState:Remove', msg='Failed to Remove: SIIsPerforming')
            return True
        if si in self._removing_interactions:
            si.log_info('SIState:Remove', msg='Failed to Remove: AlreadyRemoving')
            return True
        si_in_super_interactions = si in self._super_interactions
        if si_in_super_interactions:
            try:
                while participant_type & ParticipantType.Actor:
                    self._removing_interactions.add(si)
                    yield si._exit(timeline, allow_yield)
                    while si.started and not si.stopped:
                        if allow_yield:
                            logger.error('Super Interaction primitive ({0}) failed to fully exit. Hard stop!', si)
                        si.trigger_hard_stop()
            finally:
                self._removing_interactions.discard(si)
                self._super_interactions.discard(si)
                self.sim._social_group_constraint = None
                self.notify_dirty()
                self.on_changed(si)
                si.log_info('SIState:Remove', msg='Success')
                si.on_removed_from_si_state(participant_type=participant_type)
            return True
        si.log_info('SIState:Remove', msg='Failed')
        return False

    def find_interaction_by_id(self, super_interaction_id):
        for test_si in self:
            while super_interaction_id == test_si.id:
                return test_si

    def find_continuation_by_id(self, source_id):
        for test_si in self:
            while test_si.is_continuation_by_id(source_id):
                return test_si

    def _on_interaction_canceled(self, interaction):
        if not self.find_interaction_by_id(interaction.id):
            return False
        self.notify_dirty()
        return True

    def has_guaranteed_si(self, ignored_group=None):
        for si in self._super_interactions:
            if ignored_group is not None and si.group_id == ignored_group:
                pass
            while si.is_guaranteed():
                return True
        return False

    def has_user_directed_si(self):
        for si in self._super_interactions:
            while si.source == interactions.context.InteractionSource.PIE_MENU:
                return True
        return False

    def is_affordance_active_for_actor(self, super_affordance):
        super_affordance_type = super_affordance.get_interaction_type()
        return any(si.super_affordance.get_interaction_type() is super_affordance_type for si in self.sis_actor_gen())

    def get_highest_priority(self):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        priority = None
        for si in self._super_interactions:
            while not priority or si.priority > priority:
                priority = si.priority
        return priority

    def get_social_geometry_override(self):
        try:
            si = max((si for si in self if si.social_geometry_override), key=operator.attrgetter('priority'))
            return (si.social_geometry_override.social_space, si.social_geometry_override.focal_point)
        except:
            return (None, None)

    def add_watcher(self, handle, f):
        self._watchers[handle] = f
        return handle

    def remove_watcher(self, handle):
        return self._watchers.pop(handle)

    def notify_dirty(self):
        for watcher in self._watchers.values():
            watcher(self)

    def save_interactions(self):
        interaction_save_state = gameplay_serialization.SuperInteractionSaveState()
        sorted_sis = sorted(self._super_interactions, key=lambda si: return 0 if self.sim.posture_state.is_source_interaction(si) else 1)
        for si in sorted_sis:
            if not si.saveable:
                pass
            with ProtocolBufferRollback(interaction_save_state.interactions) as si_save_data:
                si.fill_save_data(si_save_data)
        sim_queue = self.sim.queue
        transition_controller = sim_queue.transition_controller
        interaction = None if transition_controller is None else transition_controller.interaction
        if interaction is not None:
            is_transitioning = interaction.transition is not None and (interaction.transition.running and interaction.pipeline_progress < PipelineProgress.RUNNING)
            if is_transitioning and interaction.saveable:
                transitioning_interaction = interaction_save_state.transitioning_interaction
                interaction.fill_save_data(transitioning_interaction.base_interaction_data)
                current_sim_posture = self.sim.posture_state
                if current_sim_posture is not None:
                    transitioning_interaction.posture_aspect_body = current_sim_posture.body.guid64
                    transitioning_interaction.posture_carry_left = current_sim_posture.left.guid64
                    transitioning_interaction.posture_carry_right = current_sim_posture.right.guid64
        for si in sim_queue.queued_super_interactions_gen():
            if not si.is_super:
                pass
            if not si.saveable:
                pass
            if si is interaction:
                pass
            with ProtocolBufferRollback(interaction_save_state.queued_interactions) as si_save_data:
                si.fill_save_data(si_save_data)
        return interaction_save_state

    def load_staged_interactions(self, interaction_save_state):
        for interaction_data in interaction_save_state.interactions:
            enqueue_result = self._load_and_push_interaction(interaction_data)
            while enqueue_result:
                interaction = enqueue_result.execute_result.interaction
                logger.debug('load_staged_interactions :{} on sim:{}', interaction, self.sim, owner='sscholl')

    def load_transitioning_interaction(self, interaction_save_state):
        if interaction_save_state.HasField('transitioning_interaction'):
            transitioning_interaction = interaction_save_state.transitioning_interaction
            transition_enqueue_result = self._load_and_push_interaction(transitioning_interaction.base_interaction_data)
            if transition_enqueue_result:
                interaction = transition_enqueue_result.execute_result.interaction
                logger.debug('load_transitioning_interaction :{} on sim:{}', interaction, self.sim, owner='sscholl')

    def load_queued_interactions(self, interaction_save_state):
        for queued_interaction in interaction_save_state.queued_interactions:
            self._load_and_push_interaction(queued_interaction)

    def _load_and_push_interaction(self, interaction_data):
        interaction = services.get_instance_manager(sims4.resources.Types.INTERACTION).get(interaction_data.interaction)
        if interaction is None:
            return ExecuteResult.NONE
        logger.debug('_load_and_push_interaction :{} on sim:{}', interaction, self.sim, owner='sscholl')
        target = services.object_manager().get(interaction_data.target_id)
        if target is None:
            target = services.current_zone().inventory_manager.get(interaction_data.target_id)
        if target is not None and interaction_data.HasField('target_part_group_index'):
            target = target.parts[interaction_data.target_part_group_index]
        source = InteractionSource(interaction_data.source)
        priority = Priority(interaction_data.priority)
        context = interactions.context.InteractionContext(self.sim, source, priority, restored_from_load=True)
        load_data = InteractionLoadData()
        if interaction_data.HasField('start_time'):
            load_data.start_time = DateAndTime(interaction_data.start_time)
        execute_result = self.sim.push_super_affordance(interaction, target, context, skip_safe_tests=True, skip_test_on_execute=True, load_data=load_data)
        return execute_result

    def log_si_state(self, logger_func, additional_msg=None, **kwargs):
        si_state_strings = []
        if additional_msg is not None:
            si_state_strings.append(additional_msg)
        si_state_strings.append('SI State info for {}'.format(self.sim))
        for si in self:
            si_state_strings.append('    {}'.format(si))
        logger_func('\n'.join(si_state_strings), **kwargs)

class InteractionLoadData:
    __qualname__ = 'InteractionLoadData'

    def __init__(self):
        self.start_time = None

def check_visibility(item):
    return item.visible

