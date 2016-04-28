from contextlib import contextmanager
import collections
import functools
import itertools
from animation.posture_manifest import Hand, PostureManifest, AnimationParticipant, SlotManifest, MATCH_ANY
from carry import create_carry_constraint
from element_utils import build_critical_section_with_finally, build_critical_section, soft_sleep_forever
from element_utils import build_element, do_all, must_run
from interactions import ParticipantType
from interactions.aop import AffordanceObjectPair
from interactions.base.interaction import PRIVACY_LIABILITY, PrivacyLiability, CANCEL_AOP_LIABILITY, STAND_SLOT_LIABILITY
from interactions.base.super_interaction import SuperInteraction
from interactions.constraints import Constraint, ANYWHERE, create_constraint_set
from interactions.context import InteractionContext, QueueInsertStrategy, InteractionSource
from interactions.interaction_finisher import FinishingType
from interactions.priority import Priority
from interactions.utils import routing as interaction_routing
from interactions.utils.animation import flush_all_animations
from interactions.utils.routing import handle_transition_failure
from interactions.utils.routing_constants import TransitionFailureReasons
from objects.components.types import CARRYABLE_COMPONENT
from objects.object_enums import ResetReason
from postures import DerailReason
from postures.base_postures import create_puppet_postures
from postures.context import PostureContext
from postures.posture_graph import TransitionSequenceStage, EMPTY_PATH_SPEC
from postures.posture_specs import PostureSpecVariable, BODY_INDEX, BODY_TARGET_INDEX, BODY_POSTURE_TYPE_INDEX, PostureAspectBody
from postures.posture_state import PostureState
from postures.posture_state_spec import PostureStateSpec
from postures.transition import PostureStateTransition
from services.reset_and_delete_service import ResetRecord
from sims4 import callback_utils
from sims4.callback_utils import CallableList
from sims4.collections import frozendict
from sims4.math import transform_almost_equal
from sims4.profiler_utils import create_custom_named_profiler_function
from sims4.sim_irq_service import yield_to_irq
from sims4.tuning.tunable import TunableSimMinute, TunableRealSecond
import caches
import clock
import date_and_time
import element_utils
import elements
import gsi_handlers
import interactions
import macros
import postures.posture_graph
import postures.posture_scoring
import routing
import services
import sims4.collections
import sims4.log
logger = sims4.log.Logger('TransitionSequence')
with sims4.reload.protected(globals()):
    global_plan_lock = None
    inject_interaction_name_in_callstack = False

def path_plan_allowed():
    if global_plan_lock is None:
        return True
    sim_with_lock = global_plan_lock()
    return sim_with_lock is None

def final_destinations_gen():
    for transition_controller in services.current_zone().all_transition_controllers:
        while transition_controller.is_transition_active():
            while True:
                for final_dest in transition_controller.final_destinations_gen():
                    yield final_dest

postures.posture_scoring.set_final_destinations_gen(final_destinations_gen)

class PosturePreferencesData:
    __qualname__ = 'PosturePreferencesData'

    def __init__(self, apply_penalties, find_best_posture, prefer_surface, require_current_constraint, posture_cost_overrides):
        self.apply_penalties = apply_penalties
        self.find_best_posture = find_best_posture
        self.prefer_surface = prefer_surface
        self.require_current_constraint = require_current_constraint
        self.posture_cost_overrides = posture_cost_overrides.copy()

class TransitionSequenceData:
    __qualname__ = 'TransitionSequenceData'

    def __init__(self):
        self.intended_location = None
        self.constraint = (None, None)
        self.templates = (None, None, None)
        self.valid_dest_nodes = set()
        self.segmented_paths = None
        self.connectivity = (None, None, None, None)
        self.path_spec = None
        self.final_destination = None
        self.final_included_sis = None
        self.progress = TransitionSequenceStage.EMPTY
        self.progress_max = TransitionSequenceStage.COMPLETE

class TransitionSequenceController:
    __qualname__ = 'TransitionSequenceController'
    PRIVACY_ENGAGE = 0
    PRIVACY_SHOO = 1
    PRIVACY_BLOCK = 2
    SIM_MINUTES_TO_WAIT_FOR_VIOLATORS = TunableSimMinute(description='\n        How many Sim minutes a Sim will wait for violating Sims to route away\n        before giving up on the interaction he was trying to run.  Used\n        currently for privacy and for slot reservations.\n        ', default=15, minimum=0)
    SLEEP_TIME_FOR_IDLE_WAITING = TunableRealSecond(1, description='\n        Time in real seconds idle behavior will sleep for before trying to find next work again.')

    def __init__(self, interaction, ignore_all_other_sis=False):
        self._interaction = interaction
        self._target_interaction = None
        self._expected_sim_count = 0
        self._success = False
        self._canceled = False
        self._running_transition_interactions = set()
        self._transition_canceled = False
        self._current_transitions = {}
        self._derailed = {}
        self._has_tried_bring_group_along = False
        self._original_interaction_target = None
        self._original_interaction_target_changed = False
        self._shortest_path_success = collections.defaultdict(lambda : True)
        self._failure_target_and_reason = {}
        self._blocked_sis = []
        self._sim_jobs = set()
        self._sim_idles = set()
        self._worker_all_element = None
        self._exited_due_to_exception = False
        self._sim_data = {}
        self._tried_destinations = collections.defaultdict(set)
        self._running = False
        self._privacy_initiation_time = None
        self._processed_on_route_change = False
        self.inappropriate_streetwear_change = None
        self.deferred_si_cancels = {}
        self._relevant_objects = set()
        self.ignore_all_other_sis = ignore_all_other_sis

    def __str__(self):
        if self.interaction.sim is not None:
            return 'TransitionSequence for {} {} on {}'.format(self.interaction.affordance.__name__, self.interaction.id, self.interaction.sim.full_name)
        return 'TransitionSequence for {} {} on Sim who is None'.format(self.interaction.affordance.__name__, self.interaction.id)

    @property
    def running(self):
        return self._running

    def with_current_transition(self, sim, posture_transition, sequence=()):

        def set_current_transition(_):
            if sim in self._current_transitions and self._current_transitions[sim] is not None:
                raise RuntimeError('Attempting to do two posture transitions at the same time. {}, {}'.format(self._current_transitions[sim], posture_transition))
            self._current_transitions[sim] = posture_transition

        def clear_current_transition(_):
            if self._current_transitions[sim] == posture_transition:
                self._current_transitions[sim] = None

        return build_critical_section_with_finally(set_current_transition, sequence, clear_current_transition)

    @property
    def succeeded(self):
        return self._success

    @property
    def canceled(self):
        return self._canceled

    @property
    def interaction(self):
        return self._interaction

    @property
    def sim(self):
        return self.interaction.sim

    @staticmethod
    @caches.cached
    def _get_intended_location_from_spec(sim, path_spec):
        final_transition_spec = path_spec._path[-1]
        final_posture_spec = final_transition_spec.posture_spec
        posture_type = final_posture_spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX]
        if not posture_type.mobile and not posture_type.unconstrained:
            final_posture_target = final_posture_spec[BODY_INDEX][BODY_TARGET_INDEX]
            posture = posture_type(sim, final_posture_target, postures.PostureTrack.BODY)
            slot_constraint = posture.slot_constraint_simple
            if slot_constraint is not None:
                while True:
                    for sub_slot_constraint in slot_constraint:
                        final_transform = sub_slot_constraint.containment_transform
                        routing_surface = sub_slot_constraint.routing_surface
                        location = routing.Location(final_transform.translation, final_transform.orientation, routing_surface)
        for transition_spec in path_spec._path[path_spec.path_progress:]:
            while transition_spec.path is not None:
                return transition_spec.path.final_location

    def intended_location(self, sim):
        if self.running and (not self.canceled and not self.interaction.is_finishing) and not self.is_derailed(sim):
            path_spec = self._get_path_spec(sim)
            if path_spec is not None and path_spec._path is not None:
                intended_location = self._get_intended_location_from_spec(sim, path_spec)
                if intended_location is not None:
                    return intended_location
        return sim.location

    def _clear_target_interaction(self):
        if self._target_interaction is not None:
            self._target_interaction.transition = None
            self._target_interaction.on_removed_from_queue()
            self._target_interaction = None

    def on_reset(self):
        self.end_transition()
        self.shutdown()

    def on_reset_early_detachment(self, obj, reset_reason):
        if reset_reason != ResetReason.BEING_DESTROYED and self.sim is not None:
            self.derail(DerailReason.NAVMESH_UPDATED, self.sim)

    def on_reset_add_interdependent_reset_records(self, obj, reset_reason, reset_records):
        if not self.interaction.should_reset_based_on_pipeline_progress:
            return
        if reset_reason == ResetReason.BEING_DESTROYED:
            for sim in self._sim_data:
                reset_records.append(ResetRecord(sim, ResetReason.RESET_EXPECTED, self, 'Relevant object for Transition.'))

    def _cleanup_path_spec(self, sim, path_spec):
        transition_specs = path_spec.transition_specs
        if transition_specs is None:
            return
        for transition_spec in transition_specs:
            if transition_spec.created_posture_state is not None:
                for aspect in transition_spec.created_posture_state.aspects:
                    while aspect not in sim.posture_state.aspects:
                        aspect.reset()
                transition_spec.created_posture_state = None
            if transition_spec.path is not None:
                transition_spec.path.remove_from_quad_tree()
            for (interaction, _) in transition_spec.transition_interactions(sim):
                while interaction is not None and interaction not in sim.queue and interaction not in sim.si_state:
                    interaction.release_liabilities()

    def derail(self, reason, sim, test_result=None):
        if self._success:
            return
        if self.interaction is sim.posture.source_interaction:
            return
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            gsi_handlers.posture_graph_handlers.archive_derailed_transition(self.interaction.sim, self.interaction, reason, test_result)
        self._derailed[sim] = reason
        if sim in self._current_transitions and self._current_transitions[sim] is not None:
            self._current_transitions[sim].trigger_soft_stop()

    def release_stand_slot_reservations(self, sims):
        for sim in sims:
            interaction = self.get_interaction_for_sim(sim)
            while interaction is not None:
                interaction.release_liabilities(liabilities_to_release=(STAND_SLOT_LIABILITY,))

    def get_interaction_for_sim(self, sim):
        participant_type = self.interaction.get_participant_type(sim)
        if participant_type == ParticipantType.Actor:
            return self.interaction
        if participant_type == ParticipantType.TargetSim:
            return self.interaction.get_target_si()[0]
        return

    @contextmanager
    def deferred_derailment(self):
        derail = self.derail
        derailed = dict(self._derailed)

        def deferred_derail(reason, sim):
            derailed[sim] = reason

        self.derail = deferred_derail
        try:
            yield None
        finally:
            self.derail = derail
            self._derailed = derailed

    @macros.macro
    def _get_path_spec(self, sim):
        if sim in self._sim_data:
            return self._sim_data[sim].path_spec

    def get_transitions_gen(self):
        for (sim, sim_data) in self._sim_data.items():
            while sim_data.progress >= TransitionSequenceStage.ROUTES:
                yield (sim, sim_data.path_spec.remaining_path)

    def has_reference_to_si_in_planned_paths(self, si):
        for sim_data in self._sim_data.values():
            while sim_data.constraint and si in sim_data.constraint[1]:
                return True
        return False

    def get_transitioning_sims(self):
        sims = set(self._sim_data.keys())
        sims.update(self.interaction.required_sims(for_threading=True))
        return sims

    def get_remaining_transitions(self, sim):
        path_spec = self._get_path_spec(sim)
        if path_spec is None:
            return []
        return path_spec.remaining_path

    def get_previous_spec(self, sim):
        path_spec = self._get_path_spec(sim)
        if path_spec is None:
            return []
        return path_spec.previous_posture_spec

    def advance_path(self, sim, prime_path=False):
        path_spec = self._get_path_spec(sim)
        if path_spec is postures.posture_graph.EMPTY_PATH_SPEC:
            return
        if path_spec is not None and (not prime_path or path_spec.path_progress == 0):
            path_spec.advance_path()

    def get_transition_spec(self, sim):
        path_spec = self._get_path_spec(sim)
        if path_spec is not None:
            return path_spec.get_transition_spec()

    def get_transition_should_reserve(self, sim):
        path_spec = self._get_path_spec(sim)
        if path_spec is not None:
            return path_spec.get_transition_should_reserve()
        return False

    def get_destination_constraint(self, sim):
        path_spec = self._get_path_spec(sim)
        if path_spec is not None:
            return path_spec.final_constraint

    def get_destination(self, sim):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return self._sim_data[sim].final_destination

    def get_destination_transition_spec(self, sim):
        path_spec = self._get_path_spec(sim)
        if path_spec is not None and path_spec._path:
            return path_spec._path[-1]

    def get_var_map(self, sim):
        var_map = self._get_path_spec(sim).var_map
        return var_map

    def is_derailed(self, sim):
        if sim in self._derailed:
            return self._derailed[sim] != DerailReason.NOT_DERAILED
        return False

    @property
    def any_derailed(self):
        return any(v != DerailReason.NOT_DERAILED for v in self._derailed.values())

    def is_transition_active(self):
        if not self._success and not self.canceled:
            return True
        return False

    def get_failure_reason_and_target(self, sim):
        (failure_reason, failure_object_id) = (None, None)
        path_spec = self._get_path_spec(sim)
        if path_spec is not None:
            (failure_reason, failure_object_id) = path_spec.get_failure_reason_and_object_id()
            if failure_reason is not None:
                if failure_reason == routing.FAIL_PATH_TYPE_OBJECT_BLOCKING:
                    failure_reason = TransitionFailureReasons.BLOCKING_OBJECT
                elif failure_reason == routing.FAIL_PATH_TYPE_BUILD_BLOCKING or failure_reason == routing.FAIL_PATH_TYPE_UNKNOWN or failure_reason == routing.FAIL_PATH_TYPE_UNKNOWN_BLOCKING:
                    failure_reason = TransitionFailureReasons.BUILD_BUY
        if failure_reason is None and sim in self._failure_target_and_reason:
            (failure_reason, failure_object_id) = self._failure_target_and_reason[sim]
        return (failure_reason, failure_object_id)

    def set_failure_target(self, sim, reason, target_id=None):
        if sim in self._failure_target_and_reason:
            return
        self._failure_target_and_reason[sim] = (reason, target_id)

    def add_stand_slot_reservation(self, sim, interaction, position, routing_surface):
        sim.add_stand_slot_reservation(interaction, position, routing_surface, self.get_transitioning_sims())

    def _do(self, timeline, sim, *args):
        element = build_element(args)
        if element is None:
            return
        result = yield element_utils.run_child(timeline, element)
        return result

    def _do_must(self, timeline, sim, *args):
        element = build_element(args)
        if element is None:
            return
        element = must_run(element)
        result = yield element_utils.run_child(timeline, element)
        return result

    def on_owned_interaction_canceled(self, interaction):
        if interaction.is_social and self.interaction.is_social and interaction.social_group is self.interaction.social_group:
            return
        self.derail(DerailReason.PREEMPTED, interaction.sim)

    def cancel(self, finishing_type=None, cancel_reason_msg=None, test_result=None, si_to_cancel=None):
        if finishing_type == FinishingType.NATURAL:
            return True
        if finishing_type is not None and finishing_type == FinishingType.USER_CANCEL:
            self.interaction.route_fail_on_transition_fail = False
        self._transition_canceled = True
        main_group = self.sim.get_main_group()
        if main_group is not None:
            main_group.remove_non_adjustable_sim(self.sim)
        defer_cancel = False
        for transition in self._current_transitions.values():
            if transition is None:
                pass
            if transition.is_routing:
                transition.trigger_soft_stop()
            else:
                defer_cancel = True
        if self.interaction.is_cancel_aop and self.interaction.running:
            defer_cancel = True
        if not defer_cancel:
            self.cancel_sequence(finishing_type=finishing_type, test_result=test_result)
        elif si_to_cancel is not None and si_to_cancel not in self.deferred_si_cancels:
            self.deferred_si_cancels[si_to_cancel] = (finishing_type, cancel_reason_msg)
        return self.canceled

    def cancel_sequence(self, finishing_type=None, test_result=None):
        if not self.canceled:
            if gsi_handlers.posture_graph_handlers.archiver.enabled:
                gsi_handlers.posture_graph_handlers.archive_canceled_transition(self.interaction.sim, self.interaction, finishing_type, test_result)
            self._canceled = True
            transition_finishing_type = finishing_type or FinishingType.TRANSITION_FAILURE
            for interaction in list(self._running_transition_interactions):
                if interaction.sim.posture.source_interaction is interaction:
                    pass
                interaction.cancel(transition_finishing_type, cancel_reason_msg='Transition Sequence Failed. Cancel all running transition interactions.')
            if not self.interaction.is_finishing:
                self.interaction.cancel(transition_finishing_type, cancel_reason_msg='Transition Sequence Failed. Cancel transition interaction.')
            for (si, cancel_info) in self.deferred_si_cancels.items():
                (finishing_type, cancel_reason_msg) = cancel_info
                si.cancel(finishing_type, cancel_reason_msg=cancel_reason_msg)
            self.deferred_si_cancels.clear()

    def is_final_transition(self, sim):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return self._get_path_spec(sim).num_remaining_transitions == 1

    def final_destinations_gen(self):
        for sim_data in self._sim_data.values():
            while sim_data.final_destination is not None:
                yield sim_data.final_destination

    def get_final_constraint(self, sim):
        sim_data = self._sim_data.get(sim)
        if sim_data is None:
            return ANYWHERE
        final_constraint = sim_data.constraint[0]
        if final_constraint is None:
            return ANYWHERE
        return final_constraint

    @staticmethod
    def _is_set_valid(source_dest_sets):
        valid = False
        for source_dest_set in source_dest_sets.values():
            while source_dest_set[0] and source_dest_set[1]:
                valid = True
                break
        return valid

    def get_sims_with_invalid_paths(self):
        permanent_failure = True
        invalid_sims = set()
        for (sim, sim_data) in self._sim_data.items():
            if not any(sim_data.connectivity):
                invalid_sims.add(sim)
                if not sim_data.constraint:
                    pass
                if self._tried_destinations[sim]:
                    pass
                must_include_sis = list(sim.si_state.all_guaranteed_si_gen(self.interaction.priority, self.interaction.group_id))
                while must_include_sis:
                    permanent_failure = False
                    (best_complete_path, source_destination_sets, source_middle_sets, middle_destination_sets) = sim_data.connectivity
                    if best_complete_path:
                        pass
                    if source_destination_sets and self._is_set_valid(source_destination_sets):
                        pass
                    if source_middle_sets and middle_destination_sets and self._is_set_valid(source_middle_sets):
                        pass
                    invalid_sims.add(sim)
            (best_complete_path, source_destination_sets, source_middle_sets, middle_destination_sets) = sim_data.connectivity
            if best_complete_path:
                pass
            if source_destination_sets and self._is_set_valid(source_destination_sets):
                pass
            if source_middle_sets and middle_destination_sets and self._is_set_valid(source_middle_sets):
                pass
            invalid_sims.add(sim)
        if invalid_sims and permanent_failure:
            return set()
        if invalid_sims:
            self.cancel_incompatible_sis_given_final_posture_states()
        return invalid_sims

    def estimate_distance(self):
        yield_to_irq()
        sim = self.interaction.sim
        sim_data = self._sim_data[sim]
        if sim_data.progress_max < TransitionSequenceStage.CONNECTIVITY:
            return (None, False, set())
        if len(self.interaction.object_reservation_tests):
            for valid_destination in sim_data.valid_dest_nodes:
                while valid_destination.body_target.may_reserve(sim):
                    break
            return (None, False, set())
        connectivity = sim_data.connectivity
        (distance, posture_change) = services.current_zone().posture_graph_service.estimate_distance_for_connectivity(sim, connectivity)
        return (distance, posture_change, sim_data.constraint[1] or set())

    def get_included_sis(self):
        included_sis = set()
        for sim_data in self._sim_data.values():
            included_sis_sim = sim_data.constraint[1]
            while included_sis_sim:
                while True:
                    for included_si_sim in included_sis_sim:
                        if included_si_sim is self.interaction:
                            pass
                        included_sis.add(included_si_sim)
        return included_sis

    def add_blocked_si(self, blocked_si):
        self._blocked_sis.append(blocked_si)

    def _wait_for_violators(self, timeline, blocked_sims):
        cancel_functions = CallableList()

        def wait_for_violators(timeline):
            then = services.time_service().sim_now
            while True:
                if self._blocked_sis:
                    for blocked_si in self._blocked_sis[:]:
                        basic_reserve = blocked_si.basic_reserve_object
                        if basic_reserve is None:
                            pass
                        handler = basic_reserve(self.sim, blocked_si)
                        while handler.may_reserve():
                            self._blocked_sis.remove(blocked_si)
                if not self._blocked_sis and not any(blocked_sim.get_stand_slot_reservation_violators() for blocked_sim in blocked_sims):
                    cancel_functions()
                    return
                now = services.time_service().sim_now
                timeout = self.SIM_MINUTES_TO_WAIT_FOR_VIOLATORS
                if self.canceled or now - then > clock.interval_in_sim_minutes(timeout):
                    for blocked_sim in blocked_sims:
                        self.derail(DerailReason.TRANSITION_FAILED, blocked_sim)
                    del self._blocked_sis[:]
                    cancel_functions()
                    return
                yield timeline.run_child(elements.SleepElement(date_and_time.create_time_span(minutes=1)))

        idle_work = [elements.GeneratorElement(wait_for_violators)]
        for blocked_sim in blocked_sims:
            (idle, cancel_fn) = blocked_sim.get_idle_element()
            cancel_functions.append(cancel_fn)
            idle_work.append(idle)
        yield self._do(timeline, self.sim, elements.AllElement(idle_work))

    def reset_derailed_transitions(self):
        sims_to_reset = []
        for (sim, derailed_reason) in self._derailed.items():
            while not derailed_reason is None:
                if derailed_reason == DerailReason.NOT_DERAILED:
                    pass
                if self._derailed[sim] != DerailReason.TRANSITION_FAILED:
                    for tried_destinations_sim in self._tried_destinations:
                        self._tried_destinations[tried_destinations_sim].clear()
                else:
                    final_destination = self._sim_data[sim].final_destination
                    if final_destination is not None:
                        tried_dests = {dest for dest in self._sim_data[sim].valid_dest_nodes if dest.body_target is final_destination.body_target}
                        self._tried_destinations[sim] |= tried_dests
                if derailed_reason != DerailReason.PRIVACY_ENGAGED:
                    sims_to_reset.append(sim)
                    if self._derailed[sim] == DerailReason.TRANSITION_FAILED and sim is self.interaction.sim and self._original_interaction_target_changed:
                        self.interaction.set_target(self._original_interaction_target)
                        self._original_interaction_target = None
                        self._original_interaction_target_changed = False
                self._derailed[sim] = DerailReason.NOT_DERAILED
                sim.validate_current_location_or_fgl()
        for sim in sims_to_reset:
            self.set_sim_progress(sim, TransitionSequenceStage.EMPTY)
        if sims_to_reset:
            self.interaction.refresh_constraints()
            self.release_stand_slot_reservations(sims_to_reset)
        self._has_tried_bring_group_along = False

    def _validate_transitions(self):
        for sim_data in self._sim_data.values():
            while sim_data.path_spec is None or sim_data.path_spec is postures.posture_graph.EMPTY_PATH_SPEC:
                self.cancel()

    def end_transition(self):
        for sim_data in self._sim_data.values():
            included_sis = sim_data.constraint[1]
            if included_sis is None:
                pass
            for included_si in included_sis:
                included_si.transition = None
                included_si.owning_transition_sequences.discard(self)
        self._clear_target_interaction()
        postures.posture_scoring.set_transition_destinations(self.sim, {})
        for (sim, sim_data) in self._sim_data.items():
            while sim_data.path_spec is not None:
                self._cleanup_path_spec(sim, sim_data.path_spec)

    def shutdown(self):
        self.clear_relevant_objects()
        for sim in self._sim_data:
            self._clear_owned_transition(sim)
            social_group = sim.get_main_group()
            while social_group is not None:
                if not sims4.math.transform_almost_equal(sim.intended_transform, sim.transform, epsilon=sims4.geometry.ANIMATION_SLOT_EPSILON):
                    social_group.refresh_social_geometry(sim=sim)
        if self._success or self.canceled:
            self.reset_all_progress()
            self.cancel_incompatible_sis_given_final_posture_states()
        services.current_zone().all_transition_controllers.discard(self)

    def cancel_incompatible_sis_given_final_posture_states(self):
        if not self.interaction.cancel_incompatible_with_posture_on_transition_shutdown:
            return
        cancel_reason_msg = "Incompatible with Sim's final transform."
        for sim in self.get_transitioning_sims():
            sim.evaluate_si_state_and_cancel_incompatible(FinishingType.INTERACTION_INCOMPATIBILITY, cancel_reason_msg)

    def _clear_cancel_by_posture_change(self):
        for sim_data in self._sim_data.values():
            while sim_data.final_included_sis:
                while True:
                    for si in sim_data.final_included_sis:
                        si.disable_cancel_by_posture_change = False

    def _clear_owned_transition(self, sim):
        sim_data = self._sim_data.get(sim)
        if sim_data.final_included_sis:
            for included_si in sim_data.final_included_sis:
                included_si.owning_transition_sequences.discard(self)
        included_sis = sim_data.constraint[1]
        if included_sis:
            for included_si in included_sis:
                included_si.owning_transition_sequences.discard(self)

    def _get_carry_transference_work(self):
        carry_transference_work_begin = collections.defaultdict(list)
        for sim in self._sim_data:
            for si in sim.si_state:
                if si._carry_transfer_animation is None:
                    pass
                end_carry_transfer = si.get_carry_transfer_end_element()
                carry_transference_work_begin[si.sim].append(build_critical_section(end_carry_transfer, flush_all_animations))
        carry_transference_sis = set()
        for sim_data in self._sim_data.values():
            additional_templates = sim_data.templates[1]
            if additional_templates:
                carry_transference_sis.update(additional_templates.keys())
            carry_si = sim_data.templates[2]
            while carry_si is not None:
                carry_transference_sis.add(carry_si)
        carry_transference_sis.discard(self.interaction)
        carry_transference_work_end = collections.defaultdict(list)
        for si in carry_transference_sis:
            if si._carry_transfer_animation is None:
                pass
            begin_carry_transfer = si.get_carry_transfer_begin_element()
            carry_transference_work_end[si.sim].append(build_critical_section(begin_carry_transfer, flush_all_animations))
        return (carry_transference_work_begin, carry_transference_work_end)

    def get_final_included_sis_for_sim(self, sim):
        if sim not in self._sim_data:
            return
        return self._sim_data[sim].final_included_sis

    def compute_transition_connectivity(self):
        gen = self.run_transitions(None, TransitionSequenceStage.CONNECTIVITY)
        try:
            next(gen)
            logger.error('run_transitions yielded when computing connectivity')
        except StopIteration as exc:
            return exc.value

    def run_transitions(self, timeline, progress_max=TransitionSequenceStage.COMPLETE):
        logger.debug('{}: Running.', self)
        callback_utils.invoke_callbacks(callback_utils.CallbackEvent.TRANSITION_SEQUENCE_ENTER)
        try:
            self._running = True
            self._progress_max = progress_max
            self.reset_derailed_transitions()
            for required_sim in self.get_transitioning_sims():
                sim_data = self._sim_data.get(required_sim)
                while sim_data is None or sim_data.progress < progress_max:
                    break
            return True
            sim = self.interaction.get_participant(ParticipantType.Actor)
            services.current_zone().all_transition_controllers.add(self)
            if progress_max < TransitionSequenceStage.COMPLETE or not self.interaction.disable_transitions:
                yield self._build_transitions(timeline)
            if self.any_derailed:
                return False
            if progress_max < TransitionSequenceStage.COMPLETE:
                services.current_zone().all_transition_controllers.remove(self)
                return True
            if self.interaction.disable_transitions:
                result = yield self.run_super_interaction(timeline, self.interaction)
                return result
            self._validate_transitions()
            (target_si, test_result) = self.interaction.get_target_si()
            if not test_result:
                self.cancel(FinishingType.FAILED_TESTS)
            if self.canceled:
                (failure_reason, failure_target) = self.get_failure_reason_and_target(sim)
                if failure_reason is not None or failure_target is not None:
                    yield self._do(timeline, sim, handle_transition_failure(sim, self.interaction.target, self.interaction, failure_reason=failure_reason, failure_object_id=failure_target))
                return False
            if target_si is not None and target_si.set_as_added_to_queue():
                target_si.transition = self
                self._target_interaction = target_si
            for sim_data in self._sim_data.values():
                while sim_data.final_included_sis:
                    while True:
                        for si in sim_data.final_included_sis:
                            si.disable_cancel_by_posture_change = True
            (carry_transference_work_begin, carry_transference_work_end) = self._get_carry_transference_work()
            if carry_transference_work_begin:
                yield self._do_must(timeline, self.sim, do_all(thread_element_map=carry_transference_work_begin))
            self._worker_all_element = elements.AllElement([build_element(self._create_next_elements)])
            result = yield self._do(timeline, None, self._worker_all_element)
            if carry_transference_work_end:
                yield self._do_must(timeline, self.sim, do_all(thread_element_map=carry_transference_work_end))
            if progress_max == TransitionSequenceStage.COMPLETE:
                blocked_sims = set()
                for (blocked_sim, reason) in self._derailed.items():
                    while reason == DerailReason.WAIT_FOR_BLOCKING_SIMS:
                        blocked_sims.add(blocked_sim)
                if blocked_sims:
                    yield self._wait_for_violators(timeline, blocked_sims)
            if self._transition_canceled:
                self.cancel()
            if self._success or self.canceled or self.is_derailed(self._interaction.sim):
                result = False
            if result:
                for (_, transition) in self.get_transitions_gen():
                    while transition:
                        result = False
                        break
            if not self._shortest_path_success[sim]:
                yield self._do(timeline, sim, handle_transition_failure(sim, self.interaction.target, self.interaction, *self.get_failure_reason_and_target(sim)))
                self.cancel()
                return False
            while result:
                self._success = True
                while not self.interaction.active and not self.interaction.is_finishing:
                    should_replace_posture_source = SuperInteraction.should_replace_posture_source_interaction(self.interaction)
                    would_replace_nonfinishing = should_replace_posture_source and not self.sim.posture.source_interaction.is_finishing
                    if would_replace_nonfinishing and not self.interaction.is_cancel_aop:
                        self.sim.posture.source_interaction.merge(self.interaction)
                        self.interaction.cancel(FinishingType.TRANSITION_FAILURE, 'Transition Sequence. Replace posture source non-finishing.')
                    else:
                        self.interaction.apply_posture_state(self.interaction.sim.posture_state)
                        result = yield self.run_super_interaction(timeline, self.interaction)
                        if not result:
                            yield self._do(timeline, sim, handle_transition_failure(self._interaction.sim, self.interaction.target, self.interaction, *self.get_failure_reason_and_target(sim)))
        except:
            logger.debug('{} RAISED EXCEPTION.', self)
            self._exited_due_to_exception = True
            for sim in self._sim_jobs:
                logger.warn('Terminating transition for Sim {}', sim)
            for sim in self._sim_idles:
                logger.warn('Terminating transition idle for Sim {}', sim)
            self._sim_jobs.clear()
            self._sim_idles.clear()
            raise
        finally:
            if self._transition_canceled:
                self.cancel()
            logger.debug('{} DONE.', self)
            self._clear_cancel_by_posture_change()
            if progress_max == TransitionSequenceStage.COMPLETE:
                sims_to_update_intended_location = set()
                for sim in self.get_transitioning_sims():
                    while not sims4.math.transform_almost_equal(sim.intended_transform, sim.transform, epsilon=sims4.geometry.ANIMATION_SLOT_EPSILON):
                        sims_to_update_intended_location.add(sim)
                self.shutdown()
                for sim in sims_to_update_intended_location:
                    sim.on_intended_location_changed(sim.intended_location)
                self.cancel_incompatible_sis_given_final_posture_states()
                self.cancel_incompatible_sis_given_final_posture_states()
                callback_utils.invoke_callbacks(callback_utils.CallbackEvent.TRANSITION_SEQUENCE_EXIT)
                if not self._success and self._interaction.must_run:
                    while True:
                        for sim in self.get_transitioning_sims():
                            while self.is_derailed(sim):
                                break
                        logger.warn('Failed to plan a must run interaction {}', self.interaction, owner='tastle')
                        while True:
                            for sim in self.get_transitioning_sims():
                                self.sim.reset(ResetReason.RESET_EXPECTED, self, 'Failed to plan must run.')
            self._running = False
        if self._sim_jobs:
            raise AssertionError('Transition Sequence: Attempted to exit when there were still existing jobs. [tastle]')
        return self._success

    @staticmethod
    def choose_hand_and_filter_specs(sim, posture_specs_and_vars, carry_target, used_hand_and_target=None):
        new_specs_and_vars = []
        already_matched = set()
        used_hand = None
        used_hand_target = None
        left_carry_target = sim.posture_state.left.target
        right_carry_target = sim.posture_state.right.target
        chosen_hand = None
        if left_carry_target == carry_target and carry_target is not None:
            chosen_hand = Hand.LEFT
        elif right_carry_target == carry_target and carry_target is not None:
            chosen_hand = Hand.RIGHT
        elif left_carry_target is None and right_carry_target is not None:
            chosen_hand = Hand.LEFT
        elif right_carry_target is None and left_carry_target is not None:
            chosen_hand = Hand.RIGHT
        elif used_hand_and_target is not None:
            (used_hand, used_hand_target) = used_hand_and_target
            if carry_target is used_hand_target:
                chosen_hand = used_hand
            else:
                chosen_hand = Hand.LEFT if used_hand != Hand.LEFT else Hand.RIGHT
        elif carry_target is not None:
            allowed_hands = carry_target.allowed_hands
            if len(allowed_hands) == 1:
                chosen_hand = allowed_hands[0]
        if chosen_hand is None:
            allowed_hands = set()
            for (_, posture_spec_vars, _) in posture_specs_and_vars:
                required_hand = posture_spec_vars.get(PostureSpecVariable.HAND)
                while required_hand is not None:
                    allowed_hands.add(required_hand)
            if used_hand is not None:
                allowed_hands.discard(used_hand)
            if not allowed_hands or sim.handedness in allowed_hands:
                chosen_hand = sim.handedness
            else:
                chosen_hand = allowed_hands.pop()
            if chosen_hand is None:
                logger.error('Failed to find a valid hand for {}', carry_target)
        if chosen_hand == used_hand and carry_target is not used_hand_target:
            logger.error('Attempt to use the same hand as another constraint spec!: {}', posture_specs_and_vars)
        hand_map = {PostureSpecVariable.HAND: chosen_hand}
        for (index_a, (posture_spec_template_a, posture_spec_vars_a, constraint_a)) in enumerate(posture_specs_and_vars):
            if index_a in already_matched:
                pass
            found_match = False
            if index_a + 1 < len(posture_specs_and_vars) and PostureSpecVariable.HAND in posture_spec_vars_a:
                for (index_b, (posture_spec_template_b, posture_spec_vars_b, constraint_b)) in enumerate(posture_specs_and_vars[index_a + 1:]):
                    real_index_b = index_b + index_a + 1
                    if posture_spec_template_a != posture_spec_template_b:
                        pass
                    vars_match = True
                    for (key_a, var_a) in posture_spec_vars_a.items():
                        if key_a == PostureSpecVariable.HAND:
                            pass
                        while key_a not in posture_spec_vars_b or posture_spec_vars_b[key_a] != var_a:
                            vars_match = False
                            break
                    if not vars_match:
                        pass
                    found_match = True
                    already_matched.add(real_index_b)
                    cur_posture_vars = frozendict(posture_spec_vars_a, hand_map)
                    hand_constraint = create_carry_constraint(carry_target, hand=chosen_hand)
                    constraint_new = constraint_a.intersect(hand_constraint)
                    if not constraint_new.valid:
                        constraint_new = constraint_b.intersect(hand_constraint)
                    while constraint_new.valid:
                        new_specs_and_vars.append((posture_spec_template_a, cur_posture_vars, constraint_new))
            while not found_match:
                cur_posture_vars = frozendict(posture_spec_vars_a, hand_map)
                new_specs_and_vars.append((posture_spec_template_a, cur_posture_vars, constraint_a))
        return (new_specs_and_vars, chosen_hand)

    @staticmethod
    def resolve_constraint_for_hands(sim, interaction, interaction_constraint, context=None):
        if not interaction_constraint.valid:
            return interaction_constraint
        if context is not None:
            carry_target = context.carry_target
        else:
            carry_target = interaction.carry_target if interaction.carry_target is not None else interaction.target
        hand_is_immutable = dict(zip((Hand.LEFT, Hand.RIGHT), (o is not None and o is not carry_target for o in sim.posture_state.carry_targets)))
        if not any(hand_is_immutable.values()):
            return interaction_constraint
        new_constraints = []
        for constraint in interaction_constraint:
            if constraint._posture_state_spec is None or not constraint._posture_state_spec.posture_manifest:
                new_constraints.append(constraint)
            valid_manifest_entries = PostureManifest()
            for entry in constraint._posture_state_spec.posture_manifest:
                (hand, entry_carry_target) = entry.carry_hand_and_target
                while not hand_is_immutable.get(hand, False) or entry_carry_target != AnimationParticipant.CREATE_TARGET:
                    valid_manifest_entries.add(entry)
            if not valid_manifest_entries:
                pass
            valid_manifest_constraint = Constraint(posture_state_spec=PostureStateSpec(valid_manifest_entries, SlotManifest().intern(), None))
            test_constraint = constraint.intersect(valid_manifest_constraint)
            if not test_constraint.valid:
                pass
            new_constraints.append(test_constraint)
        new_constraint = create_constraint_set(new_constraints)
        return new_constraint

    @staticmethod
    def _get_specs_for_constraints(sim, interaction, interaction_constraint, pick=None, carry_target=None, used_hand_and_target=None):
        target = interaction.target
        create_target = interaction.create_target
        if any(sim.posture_state.carry_targets):

            def remove_references_to_unrelated_carried_objects(obj, default):
                if obj != None and obj != carry_target and obj in sim.posture_state.carry_targets:
                    return MATCH_ANY
                return default

        else:
            remove_references_to_unrelated_carried_objects = None
        posture_specs_and_vars = interaction_constraint.get_posture_specs(remove_references_to_unrelated_carried_objects)
        (posture_specs_and_vars, used_hand) = TransitionSequenceController.choose_hand_and_filter_specs(sim, posture_specs_and_vars, carry_target, used_hand_and_target=used_hand_and_target)
        templates = collections.defaultdict(list)
        for (posture_spec_template, posture_spec_vars, constraint) in posture_specs_and_vars:
            if any(isinstance(v, PostureSpecVariable) for v in posture_spec_vars.values()):
                logger.error('posture_spec_vars contains a variable as a value: {}', posture_spec_vars)
            posture_spec_vars_updates = {}
            if PostureSpecVariable.INTERACTION_TARGET not in posture_spec_vars:
                posture_spec_vars_updates[PostureSpecVariable.INTERACTION_TARGET] = target
            if PostureSpecVariable.CARRY_TARGET not in posture_spec_vars:
                posture_spec_vars_updates[PostureSpecVariable.CARRY_TARGET] = carry_target
            if posture_spec_vars.get(PostureSpecVariable.SLOT_TEST_DEFINITION) == AnimationParticipant.CREATE_TARGET:
                posture_spec_vars_updates[PostureSpecVariable.SLOT_TEST_DEFINITION] = create_target
            if posture_spec_vars_updates:
                posture_spec_vars += posture_spec_vars_updates
            if interaction is not None and (interaction.posture_preferences is not None and (interaction.posture_preferences.prefer_clicked_part and pick is not None)) and pick.target is not None:
                best_parts = pick.target.get_closest_parts_to_position(pick.location, posture_spec=posture_spec_template)
                interaction.add_preferred_objects(best_parts)
            templates[constraint].append((posture_spec_template, posture_spec_vars))
        return (templates, used_hand)

    @staticmethod
    def get_templates_including_carry_transference(sim, interaction, interaction_constraint, included_sis, participant_type):
        potential_carry_sis = set()
        for si in included_sis:
            while not si.has_active_cancel_replacement:
                potential_carry_sis.add(si)
        carried_object_transfers = []
        for carry_posture in sim.posture_state.carry_aspects:
            if carry_posture.target is None:
                pass
            if carry_posture.owning_interactions:
                carry_interactions = carry_posture.owning_interactions
            else:
                carry_interactions = [carry_posture.source_interaction]
            for carry_interaction in carry_interactions:
                while carry_interaction is not None and carry_posture is not None:
                    if carry_interaction.target is carry_posture.target and carry_interaction in potential_carry_sis:
                        carried_object_transfers.append(carry_interaction)
                        for owning_interaction in carry_posture.owning_interactions:
                            potential_carry_sis.discard(owning_interaction)
                        potential_carry_sis.discard(carry_posture.source_interaction)
        for si in potential_carry_sis:
            while not si.is_finishing:
                if si.has_active_cancel_replacement:
                    pass
                for constraint in si.constraint_intersection(posture_state=None):
                    while constraint.posture_state_spec is not None and constraint.posture_state_spec.slot_manifest:
                        potential_carry_target = si.carry_target or si.target
                        if potential_carry_target is not None and potential_carry_target is si.target and potential_carry_target.has_component(CARRYABLE_COMPONENT):
                            carried_object_transfers.append(si)
                            break
        if interaction.create_target is not None:
            carry_target = interaction.create_target
        elif interaction.carry_target is not None:
            carry_target = interaction.carry_target
        elif interaction.target is not None and interaction.target.has_component(CARRYABLE_COMPONENT):
            carry_target = interaction.target
        else:
            carry_target = None
        if interaction.disable_transitions:
            carry_target = None
        if carry_target is not None:
            carry_target_si = interaction
            carry_target_constraint = interaction_constraint
        else:
            carry_target_si = None
            carry_target_constraint = None
        TSC = TransitionSequenceController
        constraint_resolver = interaction.get_constraint_resolver(None, participant_type=participant_type)
        additional_constraint_list = {}
        if carried_object_transfers:
            for carry_si in reversed(carried_object_transfers):
                cancel_aop_liability = carry_si.get_liability(CANCEL_AOP_LIABILITY)
                if cancel_aop_liability is not None and cancel_aop_liability.interaction_to_cancel is interaction:
                    pass
                carry_constraint = carry_si.constraint_intersection(posture_state=None)
                carry_constraint_resolved = TSC.resolve_constraint_for_hands(sim, carry_si, carry_constraint)
                carry_constraint_resolved = carry_constraint_resolved.apply_posture_state(None, constraint_resolver)
                additional_constraint_list[carry_si] = carry_constraint_resolved
                carry_target_additional = carry_si.carry_target or carry_si.target
                while carry_target_additional is not None and carry_target_additional.has_component(CARRYABLE_COMPONENT):
                    if carry_target is None or sim.posture_state.get_carry_track(carry_target_additional) is None and (sim.posture_state.get_carry_track(carry_target) is not None and carry_target is not interaction.carry_target) and carry_target is not interaction.target:
                        carry_target = carry_target_additional
                        carry_target_si = carry_si
                        carry_target_constraint = carry_constraint_resolved
        if carry_target_si is not None and carry_target_si is not interaction:
            template_constraint = interaction_constraint.intersect(carry_target_constraint)
            del additional_constraint_list[carry_target_si]
        else:
            template_constraint = interaction_constraint
        (templates, used_hand) = TSC._get_specs_for_constraints(sim, interaction, template_constraint, pick=interaction.context.pick, carry_target=carry_target)
        additional_template_list = {}
        for (carry_si, carry_constraint_resolved) in additional_constraint_list.items():
            (carry_constraint_templates, _) = TSC._get_specs_for_constraints(sim, carry_si, carry_constraint_resolved, pick=interaction.context.pick, carry_target=carry_si.carry_target or carry_si.target, used_hand_and_target=(used_hand, carry_target))
            additional_template_list[carry_si] = carry_constraint_templates
        return (templates, additional_template_list, carry_target_si)

    def _get_constraint_for_interaction(self, sim, participant_type, ignore_inertial, ignore_combinables):
        interaction = self.interaction
        interaction_constraint = interaction.constraint_intersection(sim=sim, participant_type=participant_type, posture_state=None)
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            gsi_handlers.posture_graph_handlers.add_possible_constraints(sim, interaction_constraint, 'Interaction')
        if not interaction_constraint.valid:
            return (interaction_constraint, ())
        interaction_constraint_resolved = self.resolve_constraint_for_hands(sim, self.interaction, interaction_constraint)
        if not interaction_constraint_resolved.valid:
            included_sis = [carry_si for carry_si in sim.si_state if sim.posture_state.is_carry_source_or_owning_interaction(carry_si)]
            return (interaction_constraint_resolved, included_sis)
        if self.ignore_all_other_sis:
            return (interaction_constraint, ())
        additional_included_sis = set()
        if not ignore_combinables:
            final_valid_combinables = interaction.get_combinable_interactions_with_safe_carryables()
            if interaction.is_super and final_valid_combinables and interaction.sim is sim:
                test_intersection = interaction_constraint_resolved
                interaction_constraint_no_holster = interaction.constraint_intersection(sim=sim, participant_type=participant_type, posture_state=None, allow_holster=False)
                while True:
                    for combinable in final_valid_combinables:
                        if combinable is interaction:
                            pass
                        combinable_constraint = combinable.constraint_intersection(sim=sim, posture_state=None)
                        if not combinable_constraint.valid:
                            break
                        test_intersection = test_intersection.intersect(combinable_constraint)
                        if not test_intersection.valid:
                            break
                        interaction_constraint_resolved = test_intersection
                        if combinable.targeted_carryable is not None:
                            test_intersection_no_holster = interaction_constraint_no_holster.intersect(combinable_constraint)
                            additional_included_sis.add(combinable)
                        else:
                            additional_included_sis.add(combinable)
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            gsi_handlers.posture_graph_handlers.add_possible_constraints(sim, interaction_constraint_resolved, 'Interaction Resolved')
        force_inertial_sis = self.interaction.posture_preferences.require_current_constraint or self.interaction.is_adjustment_interaction()
        if force_inertial_sis:
            ignore_inertial = False
        (si_constraint, included_sis) = sim.si_state.get_best_constraint_and_sources(interaction_constraint_resolved, self.interaction, force_inertial_sis, ignore_inertial=ignore_inertial, participant_type=participant_type)
        if additional_included_sis:
            included_sis.update(additional_included_sis)
        if not si_constraint.valid and interaction.is_cancel_aop:
            return (interaction_constraint_resolved, [])
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            gsi_handlers.posture_graph_handlers.add_possible_constraints(sim, si_constraint, 'SI Constraint')
        if not si_constraint.valid:
            if self._progress_max == TransitionSequenceStage.COMPLETE:
                self.derail(DerailReason.CONSTRAINTS_CHANGED, sim)
            return (si_constraint, included_sis)
        si_constraint_geometry_only = si_constraint.generate_geometry_only_constraint()
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            gsi_handlers.posture_graph_handlers.add_possible_constraints(sim, si_constraint_geometry_only, 'Geometry Only')
        combined_constraint = interaction_constraint_resolved.intersect(si_constraint_geometry_only)
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            gsi_handlers.posture_graph_handlers.add_possible_constraints(sim, combined_constraint, 'Int Resolved + Geometry')
        si_constraint_body_posture_only = si_constraint.generate_body_posture_only_constraint()
        final_constraint = combined_constraint.intersect(si_constraint_body_posture_only)
        return (final_constraint, included_sis)

    def get_graph_test_functions(self, sim, target_sim, target_path_spec):
        sim_data = self._sim_data[sim]
        target_transitions = None
        if target_path_spec is not None:
            target_transitions = target_path_spec.path
        if target_transitions:
            body_index = BODY_INDEX
            body_posture_type_index = BODY_POSTURE_TYPE_INDEX
            body_target_index = BODY_TARGET_INDEX
            for target_transition in reversed(target_transitions):
                target_posture_target = target_transition[body_index][body_target_index]
                while target_transition[body_index][body_posture_type_index].multi_sim:
                    break
            target_posture_target = target_transitions[-1][body_index][body_target_index]
        else:
            target_posture_target = None

        def valid_destination_test(destination_spec, var_map):

            def is_valid_destination():
                dest_body = destination_spec[BODY_INDEX]
                dest_body_target = dest_body[BODY_TARGET_INDEX]
                dest_body_posture_type = dest_body[BODY_POSTURE_TYPE_INDEX]
                if dest_body_target is not None and sim in self._tried_destinations:
                    while True:
                        for tried_destination_spec in self._tried_destinations[sim]:
                            while dest_body_target == tried_destination_spec[BODY_INDEX][BODY_TARGET_INDEX]:
                                return False
                if sim in self._tried_destinations and destination_spec in self._tried_destinations[sim]:
                    return False
                if destination_spec in sim_data.valid_dest_nodes:
                    return True
                if target_sim is None and dest_body_posture_type.multi_sim and sim.posture.posture_type is not dest_body_posture_type:
                    return False
                if dest_body_target is None:
                    return True
                if not dest_body_posture_type.is_valid_target(sim, dest_body_target, adjacent_sim=target_sim, adjacent_target=target_posture_target):
                    return False
                if not (dest_body_target.is_part and dest_body_target.supports_posture_spec(destination_spec, self.interaction)):
                    return False
                return True

            result = is_valid_destination()
            if result:
                sim_data.valid_dest_nodes.add(destination_spec)
            return result

        body_index = BODY_INDEX
        body_posture_type_index = BODY_POSTURE_TYPE_INDEX
        valid_edge_test = None
        if target_transitions is not None:
            for (transition_index, target_transition) in enumerate(target_transitions):
                target_transition_posture_type = target_transition[body_index][body_posture_type_index]
                while target_transition_posture_type.multi_sim:
                    previous_target_transition = target_transitions[transition_index - 1]
                    previous_target_transition_posture_type = previous_target_transition[body_index][body_posture_type_index]

                    def valid_edge_test(node_a, node_b):
                        posture_type_a = node_a[body_index][body_posture_type_index]
                        posture_type_b = node_b[body_index][body_posture_type_index]
                        if posture_type_b is target_transition_posture_type:
                            return posture_type_a is previous_target_transition_posture_type
                        if posture_type_a.multi_sim or posture_type_b.multi_sim:
                            return target_path_spec.edge_exists(posture_type_a, posture_type_b)
                        return True

                    break
            if valid_edge_test is None and len(target_transitions) > 1:

                def valid_edge_test(node_a, node_b):
                    posture_type_a = node_a[body_index][body_posture_type_index]
                    posture_type_b = node_b[body_index][body_posture_type_index]
                    if posture_type_a.multi_sim or posture_type_b.multi_sim:
                        return target_path_spec.edge_exists(posture_type_a, posture_type_b)
                    return True

        elif target_sim is None:

            def valid_edge_test(node_a, node_b):
                if node_b[body_index][body_posture_type_index].multi_sim:
                    return False
                return True

        return (valid_destination_test, valid_edge_test)

    def _combine_preferences(self, sim, interaction, included_sis):
        preferences = interaction.combined_posture_preferences
        posture_preferences = PosturePreferencesData(preferences.apply_penalties, preferences.find_best_posture, preferences.prefer_surface, preferences.require_current_constraint, preferences.posture_cost_overrides)
        combined_preferences = sims4.collections.AttributeDict(vars(posture_preferences))
        for si in included_sis:
            if si.has_active_cancel_replacement:
                pass
            si_preferences = si.combined_posture_preferences
            combined_preferences.apply_penalties = si_preferences.apply_penalties or combined_preferences.apply_penalties
            combined_preferences.find_best_posture = si_preferences.find_best_posture or combined_preferences.find_best_posture
            combined_preferences.prefer_surface = si_preferences.prefer_surface or combined_preferences.prefer_surface
            combined_preferences.require_current_constraint = si_preferences.require_current_constraint or combined_preferences.require_current_constraint
            for (entry, value) in si_preferences.posture_cost_overrides.items():
                if combined_preferences.posture_cost_overrides.get(entry):
                    combined_preferences.posture_cost_overrides[entry] += value
                combined_preferences.posture_cost_overrides[entry] = value
        return sims4.collections.FrozenAttributeDict(combined_preferences)

    @property
    def relevant_objects(self):
        return self._relevant_objects

    def add_relevant_object(self, obj):
        if obj is None or isinstance(obj, PostureSpecVariable) or obj.is_sim:
            return
        obj_to_add = obj if not obj.is_part else obj.part_owner
        if obj_to_add not in self._relevant_objects:
            obj_to_add.register_transition_controller(self)
            self._relevant_objects.add(obj_to_add)

    def clear_relevant_objects(self):
        for obj in self._relevant_objects:
            while obj is not None and not obj.is_sim:
                obj.unregister_transition_controller(self)
        self._relevant_objects.clear()

    def remove_relevant_object(self, obj):
        if obj is None or obj.is_sim:
            return
        obj_to_remove = obj if not obj.is_part else obj.part_owner
        if obj_to_remove not in self._relevant_objects:
            return
        obj_to_remove.unregister_transition_controller(self)
        self._relevant_objects.remove(obj_to_remove)

    def will_derail_if_given_object_is_reset(self, obj):
        if not self.succeeded and obj in self._relevant_objects:
            return True
        return False

    def _get_transitions_for_sim(self, *args, **kwargs):
        if not inject_interaction_name_in_callstack:
            result = yield self._get_transitions_for_sim_real(*args, **kwargs)
            return result
        name = self.interaction.__class__.__name__.replace('-', '_')
        name = str(self.interaction.id) + '_' + name
        name_f = create_custom_named_profiler_function(name, use_generator=True)
        result = yield name_f(lambda : self._get_transitions_for_sim_real(*args, **kwargs))
        return result

    def _get_transitions_for_sim_real(self, timeline, sim, target_sim=None, target_path_spec=None, ignore_inertial=False, ignore_combinables=False):
        global global_plan_lock
        if sim is None:
            return postures.posture_graph.EMPTY_PATH_SPEC
        participant_type = self.interaction.get_participant_type(sim)
        interaction = self.interaction
        sim_data = self._sim_data[sim]
        sim_data.progress_max = self._progress_max
        (final_constraint, included_sis) = sim_data.constraint
        if final_constraint is None:
            (final_constraint, included_sis) = self._get_constraint_for_interaction(sim, participant_type, ignore_inertial, ignore_combinables)
            if not final_constraint.valid:
                included_sis = list(sim.si_state.all_guaranteed_si_gen(priority=self.interaction.priority, group_id=self.interaction.group_id))
            sim_data.constraint = (final_constraint, included_sis)
            for si in included_sis:
                si.owning_transition_sequences.add(self)
            if gsi_handlers.interaction_archive_handlers.is_archive_enabled(self._interaction):
                if sim is interaction.sim:
                    gsi_handlers.interaction_archive_handlers.add_constraint(interaction, sim, final_constraint)
        if final_constraint is ANYWHERE:
            if gsi_handlers.posture_graph_handlers.archiver.enabled:
                gsi_handlers.posture_graph_handlers.archive_current_spec_valid(sim, self.interaction)
            if self.interaction.outfit_change is not None and self.interaction.outfit_change.on_route_change is not None:
                path_nodes = [sim.posture_state.spec, sim.posture_state.spec]
            else:
                path_nodes = [sim.posture_state.spec]
            path = postures.posture_graph.PathSpec(path_nodes, 0, {}, sim.posture_state.spec, final_constraint, final_constraint)
            if sim_data.progress_max >= TransitionSequenceStage.CONNECTIVITY:
                sim_data.connectivity = postures.posture_graph.Connectivity(path, None, None, None)
            if sim_data.progress_max >= TransitionSequenceStage.ROUTES:
                sim_data.progress = TransitionSequenceStage.ROUTES
                sim_data.path_spec = path
            return path
        if not final_constraint.valid:
            path = postures.posture_graph.EMPTY_PATH_SPEC
            if sim_data.progress_max >= TransitionSequenceStage.ROUTES:
                sim_data.progress = TransitionSequenceStage.ROUTES
                sim_data.path_spec = path
            return path
        if sim_data.progress >= TransitionSequenceStage.TEMPLATES:
            (templates, additional_template_list, carry_target_si) = sim_data.templates
        else:
            (templates, additional_template_list, carry_target_si) = self.get_templates_including_carry_transference(sim, interaction, final_constraint, included_sis, participant_type)
            if gsi_handlers.posture_graph_handlers.archiver.enabled:
                gsi_handlers.posture_graph_handlers.add_possible_constraints(sim, final_constraint, 'Final Constraint')
            sim_data.templates = (templates, additional_template_list, carry_target_si)
            sim_data.progress = TransitionSequenceStage.TEMPLATES
        (valid_destination_test, valid_edge_test) = self.get_graph_test_functions(sim, target_sim, target_path_spec)
        posture_graph = services.current_zone().posture_graph_service
        if sim_data.progress >= TransitionSequenceStage.PATHS:
            segmented_paths = sim_data.segmented_paths
        else:
            preferences = self._combine_preferences(sim, interaction, included_sis)
            segmented_paths = posture_graph.get_segmented_paths(sim, templates, additional_template_list, interaction, participant_type, valid_destination_test, valid_edge_test, preferences, final_constraint, included_sis)
            sim_data.progress = TransitionSequenceStage.PATHS
            sim_data.segmented_paths = segmented_paths
            sim_data.intended_location = sim.get_intended_location_excluding_transition(self)
        if not segmented_paths:
            return postures.posture_graph.EMPTY_PATH_SPEC
        if sim_data.progress_max < TransitionSequenceStage.CONNECTIVITY:
            return postures.posture_graph.EMPTY_PATH_SPEC
        if sim_data.progress >= TransitionSequenceStage.CONNECTIVITY:
            connectivity = sim_data.connectivity
        else:
            resolve_animation_participant = self.interaction.get_constraint_resolver(None)
            connectivity = posture_graph.generate_connectivity_handles(sim, segmented_paths, interaction, participant_type, resolve_animation_participant)
            sim_data.connectivity = connectivity
            sim_data.progress = TransitionSequenceStage.CONNECTIVITY
        if interaction.teleporting:
            path = posture_graph.handle_teleporting_path(segmented_paths)
            if sim_data.progress_max >= TransitionSequenceStage.ROUTES:
                sim_data.path_spec = path
                sim_data.progress = TransitionSequenceStage.ROUTES
            (_, source_dest_sets, _, _) = connectivity
            for (_, destination_handles, _, _, _, _) in source_dest_sets.values():
                for dest_data in destination_handles.values():
                    (_, _, _, _, dest_goals, _, _) = dest_data
                    while interaction.dest_goals is not None:
                        interaction.dest_goals.extend(dest_goals)
            return path
        if interaction.disable_transitions:
            return
        if self._progress_max < TransitionSequenceStage.ROUTES:
            return
        success = False
        path_spec = postures.posture_graph.EMPTY_PATH_SPEC
        while global_plan_lock:
            yield element_utils.run_child(timeline, elements.BusyWaitElement(soft_sleep_forever(), path_plan_allowed))
        global_plan_lock = sim.ref()
        try:
            (success, path_spec) = yield posture_graph.find_best_path_pair(self.interaction, sim, connectivity, timeline)
            if gsi_handlers.posture_graph_handlers.archiver.enabled:
                gsi_handlers.posture_graph_handlers.log_possible_segmented_paths(sim, segmented_paths)
            path_spec.finalize(sim)
            additional_sis = posture_graph.handle_additional_pickups_and_putdowns(path_spec, additional_template_list, sim)
            current_path = path_spec.remaining_original_transition_specs()
            if current_path:
                sim_data.path_spec = path_spec
                destination_node = current_path[-1]
                sim_data.final_destination = destination_node.posture_spec
                all_included_sis = set(included_sis)
                if carry_target_si is not None and carry_target_si is not self.interaction:
                    all_included_sis.add(carry_target_si)
                all_included_sis.update(additional_sis)
                sim_data.final_included_sis = all_included_sis
                for si in all_included_sis:
                    si.owning_transition_sequences.add(self)
                if sim is self.interaction.sim and destination_node.var_map:
                    self._original_interaction_target = self.interaction.target
                    self._original_interaction_target_changed = True
                    self.interaction.apply_var_map(sim, destination_node.var_map)
                if destination_node.locked_params and destination_node.mobile:
                    pass
                if not transform_almost_equal(sim.intended_location.transform, sim.location.transform, epsilon=sims4.geometry.ANIMATION_SLOT_EPSILON):
                    sim.on_intended_location_changed(sim.intended_location)
                final_constraint.create_jig_fn()
            else:
                path_spec = postures.posture_graph.EMPTY_PATH_SPEC
                sim_data.path_spec = path_spec
            sim_data.progress = TransitionSequenceStage.ROUTES
            self._shortest_path_success[sim] = success
            return path_spec
        finally:
            global_plan_lock = None

    def _is_dest_already_counted(self, posture_spec, tried_destinations, valid_route_destinations):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        for tried_spec in tried_destinations:
            while tried_spec.is_same_route_location(posture_spec):
                return True
        for already_counted_dest in valid_route_destinations:
            while already_counted_dest.is_same_route_location(posture_spec):
                return True
        return False

    def set_sim_progress(self, sim, progress):
        if sim not in self._sim_data:
            return
        sim_data = self._sim_data[sim]
        if progress > sim_data.progress:
            raise RuntimeError('Attempt to set progress for a Sim forwards: {} > {}'.format(progress, sim_data.progress))
        if progress < TransitionSequenceStage.ACTOR_TARGET_SYNC:
            sim_data.progress = TransitionSequenceStage.ROUTES
        if progress < TransitionSequenceStage.ROUTES:
            self._shortest_path_success[sim] = True
            if sim_data.path_spec is not None:
                self._cleanup_path_spec(sim, sim_data.path_spec)
                sim_data.path_spec = None
            del self._blocked_sis[:]
        if progress < TransitionSequenceStage.PATHS:
            sim_data.valid_dest_nodes = set()
            sim_data.final_destination = None
            sim_data.segmented_paths = None
        if progress < TransitionSequenceStage.CONNECTIVITY:
            sim_data.connectivity = (None, None, None, None)
        if progress < TransitionSequenceStage.TEMPLATES:
            self._clear_owned_transition(sim)
            if sim_data.final_included_sis is not None:
                for si in sim_data.final_included_sis:
                    si.disable_cancel_by_posture_change = False
                sim_data.final_included_sis = None
            sim_data.intended_location = None
            sim_data.constraint = (None, None)
            sim_data.templates = (None, None, None)
        sim_data.progress = progress

    def reset_sim_progress(self, sim):
        sim_data = self._sim_data.get(sim)
        if sim_data is not None:
            self.set_sim_progress(sim, TransitionSequenceStage.EMPTY)
            sim.queue.clear_head_cache()

    def reset_all_progress(self):
        for sim in self._sim_data:
            self.reset_sim_progress(sim)

    def _build_transitions_for_sim(self, timeline, sim, required=True, **kwargs):
        sim_data = self._sim_data.get(sim)
        if sim_data is None:
            sim_data = TransitionSequenceData()
            self._sim_data[sim] = sim_data
        else:
            needs_reset = False
            if sim_data.path_spec is not None and sim_data.path_spec is not EMPTY_PATH_SPEC:
                current_state = sim.posture_state.get_posture_spec(sim_data.path_spec.var_map)
                current_path = sim_data.path_spec.path
                if not current_path[0].same_spec_except_slot(current_state) and not current_path[0].same_spec_ignoring_surface_if_mobile(current_state):
                    needs_reset = True
            intended_location_built = sim_data.intended_location
            if not needs_reset and intended_location_built is not None:
                intended_location_current = sim.get_intended_location_excluding_transition(self)
                if not sims4.math.transform_almost_equal_2d(intended_location_built.transform, intended_location_current.transform, epsilon=sims4.geometry.ANIMATION_SLOT_EPSILON) or intended_location_built.routing_surface != intended_location_current.routing_surface:
                    needs_reset = True
            if not needs_reset:
                (_, included_sis) = sim_data.constraint
                if included_sis:
                    needs_reset = any(si.is_finishing for si in included_sis)
            if not needs_reset and sim_data.progress >= TransitionSequenceStage.PATHS:
                segmented_paths = sim_data.segmented_paths
                needs_reset = segmented_paths and not all(segmented_path.check_validity(sim) for segmented_path in segmented_paths)
            if needs_reset:
                self.reset_sim_progress(sim)
        if sim_data.path_spec is not None:
            if sim_data.progress < TransitionSequenceStage.ROUTES:
                raise RuntimeError('Sim has path specs but progress < ROUTES')
            return sim_data.path_spec
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            gsi_handlers.posture_graph_handlers.set_current_posture_interaction(sim, self.interaction)
        path_spec = yield self._get_transitions_for_sim(timeline, sim, **kwargs)
        if self.interaction.combinable_interactions:
            self.set_sim_progress(sim, TransitionSequenceStage.EMPTY)
            path_spec = yield self._get_transitions_for_sim(timeline, sim, ignore_combinables=True, **kwargs)
        if path_spec is EMPTY_PATH_SPEC and path_spec is EMPTY_PATH_SPEC:
            must_include_sis = list(sim.si_state.all_guaranteed_si_gen(self.interaction.priority, self.interaction.group_id))
            if not must_include_sis:
                self.set_sim_progress(sim, TransitionSequenceStage.EMPTY)
                path_spec = yield self._get_transitions_for_sim(timeline, sim, ignore_inertial=True, ignore_combinables=True, **kwargs)
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            try:
                gsi_handlers.posture_graph_handlers.archive_path(sim, path_spec, self._shortest_path_success[sim], self._progress_max)
            except:
                logger.exception('GSI Transition Archive Failed.')
        if self._progress_max < TransitionSequenceStage.COMPLETE or self.interaction.disable_transitions:
            return path_spec
        current_path = path_spec.remaining_path
        if not current_path:
            current_state = None
            if sim is not None and required and self.sim is sim:
                logger.info('{} could not find transitions for {}.', self, sim)
                self.cancel(test_result='No path found for sim.')
        else:
            current_state = sim.posture_state.get_posture_spec(path_spec.var_map)
            if not (current_path[0].same_spec_except_slot(current_state) or current_path[0].same_spec_ignoring_surface_if_mobile(current_state)):
                raise RuntimeError("Initial node doesn't match the Sim's current posture spec: {} (planned) != {} (actual) for interaction: {}".format(current_path[0], current_state, self.interaction))
            path_spec.flag_slot_reservations()
            result = path_spec.generate_transition_interactions(sim, self.interaction, transition_success=self._shortest_path_success[sim])
            if not result:
                logger.info('{} failed to generate transitions for {}.', self, sim)
                self.cancel(test_result='Failed to generate transition interactions for sequence.')
        if len(current_path) == 1 and current_state == current_path[0] and not current_path[0][BODY_INDEX][BODY_POSTURE_TYPE_INDEX].unconstrained:
            path_spec.completed_path = True
        return path_spec

    @staticmethod
    def do_paths_share_body_target(path_spec_a, path_spec_b):
        if path_spec_a is not None and path_spec_b is not None:
            for node_a in path_spec_a.path:
                while node_a.body_target is not None:
                    while True:
                        for node_b in path_spec_b.path:
                            while node_a.body_target == node_b.body_target:
                                return True
        return False

    def _build_transitions(self, timeline):
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            gsi_handlers.posture_graph_handlers.increment_build_pass(self.sim, self.interaction)
        actor = self.interaction.get_participant(ParticipantType.Actor)
        target = self.interaction.get_participant(ParticipantType.TargetSim)
        if target not in self.interaction.required_sims(for_threading=True):
            if target in self._sim_data:
                self.set_sim_progress(target, TransitionSequenceStage.EMPTY)
                del self._sim_data[target]
            target = None
        actor_path_spec = yield self._build_transitions_for_sim(timeline, actor, target_sim=target)
        if not self._shortest_path_success[actor]:
            return
        if not self._has_tried_bring_group_along and self._progress_max == TransitionSequenceStage.COMPLETE:
            main_group = self.sim.get_main_group()
            if main_group is not None and (main_group.has_social_geometry(self.sim) and self.interaction.context.source == InteractionSource.PIE_MENU) and not self.interaction.is_social:
                main_group.add_non_adjustable_sim(self.sim)
            self._has_tried_bring_group_along = True
            if self.interaction.should_rally:
                self._interaction.maybe_bring_group_along()
            elif self.interaction.relocate_main_group:
                if main_group is not None:
                    main_group.try_relocate_around_focus(self.sim)
        if target is not None:
            with create_puppet_postures(target):
                target_path_spec = yield self._build_transitions_for_sim(timeline, target, target_sim=actor, target_path_spec=actor_path_spec)
                if not self._shortest_path_success[target]:
                    if self._shortest_path_success[actor]:
                        self.derail(DerailReason.TRANSITION_FAILED, actor)
                        self.derail(DerailReason.TRANSITION_FAILED, target)
                    return
                if TransitionSequenceController.do_paths_share_body_target(actor_path_spec, target_path_spec):
                    self.derail(DerailReason.TRANSITION_FAILED, actor)
                    self.derail(DerailReason.TRANSITION_FAILED, target)
                    return
        else:
            target_path_spec = None
        for sim in self.get_transitioning_sims():
            while sim is not actor and sim is not target:
                if sim in self.interaction.get_participants(ParticipantType.AllSims):
                    yield self._build_transitions_for_sim(timeline, sim, required=False)
        if self._progress_max < TransitionSequenceStage.ROUTES or self.interaction.disable_transitions:
            return
        actor_data = self._sim_data[actor]
        if target is not None:
            target_data = self._sim_data[target]
        if actor_data.progress < TransitionSequenceStage.ACTOR_TARGET_SYNC and (actor_path_spec.path and target_path_spec) and target_path_spec.path:
            body_index = BODY_INDEX
            body_posture_type_index = BODY_POSTURE_TYPE_INDEX
            while True:
                for transition in actor_path_spec.path:
                    while transition is not None:
                        if transition[body_index][body_posture_type_index].multi_sim:
                            if actor_path_spec.cost <= target_path_spec.cost:
                                self.set_sim_progress(target, TransitionSequenceStage.TEMPLATES)
                                with create_puppet_postures(target):
                                    target_path_spec = yield self._build_transitions_for_sim(timeline, target, target_sim=actor, target_path_spec=actor_path_spec)
                            else:
                                self.set_sim_progress(actor, TransitionSequenceStage.TEMPLATES)
                                actor_path_spec = yield self._build_transitions_for_sim(timeline, actor, target_sim=target, target_path_spec=target_path_spec)
                            break
        actor_data.progress = TransitionSequenceStage.ACTOR_TARGET_SYNC
        if target is not None:
            target_data.progress = TransitionSequenceStage.ACTOR_TARGET_SYNC
        if not self.interaction.disable_transitions:
            for sim in self.get_transitioning_sims():
                while sim in self._sim_data:
                    path_spec = self._get_path_spec(sim)
                    if path_spec is not None:
                        if len(path_spec.path) > 1 and path_spec.path[-1][BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile and not path_spec.path[-2][BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile:
                            pass
                        final_constraint = path_spec.final_constraint
                        if final_constraint is not None:
                            interaction = self.get_interaction_for_sim(sim)
                            if interaction is None:
                                pass
                            (single_point, routing_surface) = final_constraint.single_point()
                            if single_point is not None:
                                if path_spec.final_routing_transform is not None:
                                    single_point = path_spec.final_routing_transform.translation
                                self.add_stand_slot_reservation(sim, interaction, single_point, routing_surface)
                            else:
                                sim.remove_stand_slot_reservation(interaction)
        for sim in self._sim_data:
            self.advance_path(sim, prime_path=True)

    def create_transition(self, create_posture_state_func, si, current_transition, var_map, participant_type, sim, *additional_sims):
        posture_state = create_posture_state_func(var_map)
        if posture_state is None:
            self.cancel()
            return lambda _: False
        source_interaction = None
        potential_source_sis = [source_si for source_si in sim.si_state if si is None else itertools.chain((si,), sim.si_state) if source_si.provided_posture_type is not None]
        for aspect in posture_state.aspects:
            for potential_source_si in potential_source_sis:
                while aspect.posture_type is potential_source_si.provided_posture_type:
                    if aspect.source_interaction is None:
                        aspect.source_interaction = potential_source_si
                    if aspect.source_interaction is None or potential_source_si is si:
                        source_interaction = potential_source_si
                        break
        if not posture_state.constraint_intersection.valid:
            logger.error('create_transition ended up with a constraint that is invalid: {} for interaction: {}', posture_state, self.interaction)
            return lambda _: False
        last_nonmobile_posture_with_entry_change = None
        remaining_transitions = self.get_remaining_transitions(sim)
        if sim.posture_state.body.mobile and not remaining_transitions[0].body_posture.mobile:
            for remaining_transition in reversed(remaining_transitions):
                while remaining_transition.body_posture.outfit_change and remaining_transition.body_posture.posture_type is not posture_state.body.posture_type:
                    last_nonmobile_posture_with_entry_change = remaining_transition.body_posture
                    break
        if last_nonmobile_posture_with_entry_change:
            entry_change = last_nonmobile_posture_with_entry_change.post_route_clothing_change(last_nonmobile_posture_with_entry_change, self.interaction, do_spin=True)
        elif posture_state.body.outfit_change:
            entry_change = posture_state.body.post_route_clothing_change(self.interaction, do_spin=True)
        else:
            entry_change = None
        if posture_state.body.outfit_change:
            posture_state.body.prepare_exit_clothing_change(self.interaction)
        on_route_change = None
        if not self._processed_on_route_change and entry_change is None and (sim.posture_state.body.mobile or posture_state.body.mobile):
            on_route_change = self.interaction.pre_route_clothing_change(do_spin=True)
            self._processed_on_route_change = True
        exit_change = sim.posture_state.body.exit_clothing_change(self.interaction, sim=sim, do_spin=True)
        if entry_change is not None:
            clothing_change = entry_change
        elif on_route_change is not None:
            clothing_change = on_route_change
        elif exit_change is not None:
            clothing_change = exit_change
        else:
            clothing_change = None
        if clothing_change is None and self.inappropriate_streetwear_change is not None and (sim.posture_state.body.mobile or posture_state.body.mobile):
            clothing_change = build_critical_section(sim.sim_info.sim_outfits.get_change_outfit_element(self.inappropriate_streetwear_change, do_spin=True), flush_all_animations)
        context = PostureContext(self.interaction.context.source, self.interaction.priority, self.interaction.context.pick)
        owning_interaction = None
        if source_interaction is not None:
            final_valid_combinables = self.interaction.get_combinable_interactions_with_safe_carryables()
            posture_target = source_interaction.target
            if posture_target is not None and posture_target.has_component(CARRYABLE_COMPONENT):
                interactions_set = set((self.interaction,))
                interactions_set.update(posture_state.sim.si_state)
                if final_valid_combinables is not None:
                    interactions_set.update(final_valid_combinables)
                while True:
                    for si in interactions_set:
                        si_carry_target = si.carry_target or si.target
                        while si_carry_target is posture_target:
                            owning_interaction = si
                    if posture_target is not None and final_valid_combinables:
                        if posture_target.is_part:
                            posture_target_part_owner = posture_target.part_owner
                        else:
                            posture_target_part_owner = posture_target
                        while True:
                            for combinable in final_valid_combinables:
                                while combinable != self.interaction and combinable.target is posture_target_part_owner:
                                    owning_interaction = combinable
                                    break
            elif posture_target is not None and final_valid_combinables:
                if posture_target.is_part:
                    posture_target_part_owner = posture_target.part_owner
                else:
                    posture_target_part_owner = posture_target
                while True:
                    for combinable in final_valid_combinables:
                        while combinable != self.interaction and combinable.target is posture_target_part_owner:
                            owning_interaction = combinable
                            break
        if (source_interaction is None or not source_interaction.visible) and owning_interaction is None:
            owning_interaction = self.interaction
        transition_spec = self.get_transition_spec(sim)
        if transition_spec.path is not None:
            final_node = transition_spec.path[-1]
            final_transform = sims4.math.Transform(sims4.math.Vector3(*final_node.position), sims4.math.Quaternion(*final_node.orientation))
            final_transform_constraint = interactions.constraints.Transform(final_transform, routing_surface=final_node.routing_surface_id)
            posture_state.add_constraint(final_node, final_transform_constraint)
        else:
            final_node = None
        sim.si_state.pre_resolve_posture_change(posture_state)
        if final_node is not None:
            posture_state.remove_constraint(final_node)
        if transition_spec.path is not None:
            posture_state.remove_constraint(final_node)
        transition = PostureStateTransition(posture_state, source_interaction, context, var_map, transition_spec, self.interaction, owning_interaction, self.get_transition_should_reserve(sim), self.get_destination_constraint(sim))
        if clothing_change is not None:
            if sim.posture_state.body.mobile:
                if posture_state.body.saved_exit_clothing_change is not None:
                    sequence = build_critical_section_with_finally(clothing_change, transition, lambda _: posture_state.body.ensure_exit_clothing_change_application())
                else:
                    sequence = (clothing_change, transition)
                    if posture_state.body.mobile:
                        sequence = (transition, clothing_change)
                    elif exit_change is not None:
                        posture_state.body.transfer_exit_clothing_change(sim.posture_state.body.saved_exit_clothing_change)
                        sequence = (transition,)
                    else:
                        sequence = (transition,)
            elif posture_state.body.mobile:
                sequence = (transition, clothing_change)
            elif exit_change is not None:
                posture_state.body.transfer_exit_clothing_change(sim.posture_state.body.saved_exit_clothing_change)
                sequence = (transition,)
            else:
                sequence = (transition,)
        else:
            sequence = (transition,)
        sequence = sim.without_social_focus(sequence)
        process_si_states = tuple(sim.si_state.process_gen for sim in itertools.chain((sim,), additional_sims))
        process_si_states_again = tuple(sim.si_state.process_gen for sim in itertools.chain((sim,), additional_sims))
        sequence = build_critical_section(process_si_states, sequence, process_si_states_again)
        sequence = self.with_current_transition(sim, transition, sequence)
        transition_spec.created_posture_state = posture_state
        return sequence

    def run_super_interaction(self, timeline, si, pre_run_behavior=None, linked_sim=None):
        (target_si, test_result) = si.get_target_si()
        if target_si is not None and not test_result:
            self.cancel(FinishingType.FAILED_TESTS)
            return False
        sim = si.sim
        should_wait_for_others = sim is self.sim and si is self.interaction
        start_time = services.time_service().sim_now
        import sims.sim
        maximum_wait_time = sims.sim.LOSAndSocialConstraintTuning.incompatible_target_sim_maximum_time_to_wait
        while should_wait_for_others:
            while not self._transition_canceled:
                should_wait_for_others = False
                if self.any_derailed:
                    return False
                if sim is self.sim:
                    for other_sim in self._sim_data:
                        while not other_sim is sim:
                            if other_sim is linked_sim:
                                pass
                            remaining_transitions_other = self.get_remaining_transitions(other_sim)
                            while remaining_transitions_other:
                                should_wait_for_others = True
                                break
                while should_wait_for_others:
                    now = services.time_service().sim_now
                    if now - start_time > clock.interval_in_sim_minutes(maximum_wait_time):
                        self.cancel()
                        break
                    else:
                        yield self._do(timeline, sim, (sim.posture.get_idle_behavior(), flush_all_animations, elements.SoftSleepElement(clock.interval_in_real_seconds(self.SLEEP_TIME_FOR_IDLE_WAITING))))
                        continue
        if self.canceled:
            return False
        if not si.staging and target_si is not None and target_si.staging:
            (si, target_si) = (target_si, si)
        if si.sim in self._sim_data:
            included_sis_actor = self._sim_data[si.sim].final_included_sis
        else:
            included_sis_actor = None
        result = yield si.run_direct_gen(timeline, source_interaction=self.interaction, pre_run_behavior=pre_run_behavior, included_sis=included_sis_actor)
        if result and target_si is not None:
            if target_si.sim in self._sim_data:
                included_sis_target = self._sim_data[target_si.sim].final_included_sis
            else:
                included_sis_target = None
            result = yield target_si.run_direct_gen(timeline, source_interaction=self.interaction, included_sis=included_sis_target)
        if si is self.interaction or target_si is self.interaction:
            self._success = True
            if self.interaction.is_social and self.interaction.additional_social_to_run_on_both is not None:
                result = yield self.interaction.run_additional_social_affordance_gen(timeline)
                if not result:
                    logger.warn('Failed to run additional social affordances for {}', self.interaction, owner='maxr')
                    return False
        return result

    def _create_transition_interaction(self, timeline, sim, destination_spec, create_posture_state_func, target, participant_type, target_si=None, linked_sim=None):
        if self.is_derailed(sim):
            return True
        result = True
        transition_spec = self.get_transition_spec(sim)
        current_spec = None
        if transition_spec is None or not transition_spec.test_transition_interactions(sim, self.interaction):
            return False
        for (si, var_map) in transition_spec.transition_interactions(sim):
            current_spec = sim.posture_state.get_posture_spec(var_map)
            yield_to_irq()
            has_pre_route_change = si is not None and (si.outfit_change is not None and si.outfit_change.on_route_change is not None)
            if current_spec == destination_spec and transition_spec.path is None and not has_pre_route_change:
                run_transition_gen = None
            else:

                def run_transition_gen(timeline):
                    self.interaction.add_default_outfit_priority()
                    if target is not None:
                        transition = self.create_transition(create_posture_state_func, si, destination_spec, var_map, participant_type, sim, target)
                    else:
                        transition = self.create_transition(create_posture_state_func, si, destination_spec, var_map, participant_type, sim)
                    if si is not None and not si.route_fail_on_transition_fail:
                        transition = sim.without_route_failure(transition)
                    result_transition = yield element_utils.run_child(timeline, transition)
                    if result_transition or not self.is_derailed(sim) or self._derailed[sim] == DerailReason.TRANSITION_FAILED:
                        if not self.canceled:
                            if not self._shortest_path_success[sim]:
                                self.cancel(test_result=result_transition)
                    return result_transition

            if run_transition_gen is not None:
                result = yield run_transition_gen(timeline)
            else:
                result = True
            while not (si is None and result):
                break
        if result:
            self.advance_path(sim)
            if target is not None:
                self.advance_path(target)
            if linked_sim is not None and target is not linked_sim:
                self.advance_path(linked_sim)
            return result
        if self.is_derailed(sim):
            return True
        return result

    def _create_posture_state(self, posture_state, spec, var_map):
        posture_state = PostureState(posture_state.sim, posture_state, spec, var_map)
        return posture_state

    def _create_transition_single(self, sim, transition, participant_type=ParticipantType.Actor):

        def do_transition_single(timeline):

            def create_posture_state_func(var_map):
                return self._create_posture_state(sim.posture_state, transition, var_map)

            result = yield self._create_transition_interaction(timeline, sim, transition, create_posture_state_func, None, participant_type)
            return result

        return do_transition_single

    def _create_transition_multi_entry(self, sim, sim_node, target, target_node):

        def do_transition_multi_entry(timeline):
            target_transition_spec = self._get_path_spec(target).get_transition_spec()
            target_si = target_transition_spec.get_multi_target_interaction(target)
            target_si.context.group_id = self.interaction.group_id
            if not target_si.aop.test(target_si.context):
                logger.debug('Target interaction failed for multi-entry: {}', target_si)
                return False

            def create_multi_sim_posture_state(var_map):
                master_posture_state = self._create_posture_state(sim.posture_state, sim_node, var_map)
                puppet_posture_state = self._create_posture_state(target.posture_state, target_node, var_map)
                if master_posture_state is not None and puppet_posture_state is not None:
                    master_posture_state.linked_posture_state = puppet_posture_state
                    puppet_posture_state.body.source_interaction = target_si
                return master_posture_state

            result = yield self._create_transition_interaction(timeline, sim, sim_node, create_multi_sim_posture_state, target, ParticipantType.Actor, target_si=target_si)
            return result

        return do_transition_multi_entry

    def _create_transition_multi_exit(self, sim, sim_edge):

        def do_transition_multi_exit(timeline):
            linked_sim = sim.posture.linked_sim
            linked_path_spec = self._get_path_spec(linked_sim)
            if linked_path_spec is not None:
                linked_spec = linked_path_spec.get_transition_spec()
                linked_si = linked_spec.get_multi_target_interaction(linked_sim)
            else:
                current_spec = sim.posture_state.spec
                edge_info = services.current_zone().posture_graph_service.get_edge(current_spec, sim_edge)
                aop = edge_info.operations[0].associated_aop(sim, self.get_var_map(sim))
                linked_sim = sim.posture.linked_sim
                linked_context = InteractionContext(linked_sim, self.interaction.source, self.interaction.priority, insert_strategy=QueueInsertStrategy.NEXT, must_run_next=True, group_id=self.interaction.group_id)
                linked_aop = AffordanceObjectPair(aop.affordance, linked_sim.posture.target, aop.affordance, None)
                if not linked_aop.test(linked_context):
                    self.cancel()
                    return False
                (_, linked_si, _) = linked_aop.interaction_factory(linked_context)
            posture_transition_context = PostureContext(self.interaction.context.source, self.interaction._priority, None)
            sim_edge_body = sim_edge[BODY_INDEX]
            linked_spec = sim_edge.clone(body=PostureAspectBody((sim_edge_body[BODY_POSTURE_TYPE_INDEX], linked_sim.posture.target if sim_edge_body[BODY_TARGET_INDEX] is not None else None)))
            linked_posture_state = PostureState(linked_sim, linked_sim.posture_state, linked_spec, {})
            linked_target_posture = linked_posture_state.body
            linked_target_posture.source_interaction = linked_si
            if linked_target_posture._primitive is None:
                transition = must_run(linked_target_posture.begin(None, linked_posture_state, posture_transition_context))
            else:
                transition = None
            with self.deferred_derailment():
                result = yield self.run_super_interaction(timeline, linked_si, pre_run_behavior=transition)
                if not result:
                    self.cancel()
                    return False

                def multi_posture_exit(var_map):
                    master_posture = self._create_posture_state(sim.posture_state, sim_edge, var_map)
                    if master_posture is not None and linked_target_posture is not None:
                        master_posture.linked_posture_state = linked_posture_state
                    return master_posture

                result = yield self._create_transition_interaction(timeline, sim, sim_edge, multi_posture_exit, None, ParticipantType.Actor, linked_sim=linked_sim)
                return result

        return do_transition_multi_exit

    def _get_privacy_status(self, sim):
        participant_type = self.interaction.get_participant_type(sim)
        if participant_type == ParticipantType.Actor and self.interaction.privacy:
            if not self.interaction.get_liability(PRIVACY_LIABILITY):
                remaining_transitions = self.get_remaining_transitions(sim)
                engage_privacy = False
                if sim.posture_state.body.mobile and not remaining_transitions[0].body_posture.mobile:
                    engage_privacy = True
                elif len(remaining_transitions) == 1:
                    engage_privacy = True
                if engage_privacy:
                    return self.PRIVACY_ENGAGE
                    if not self.interaction.get_liability(PRIVACY_LIABILITY).privacy.has_shooed:
                        return self.PRIVACY_SHOO
                    if self.interaction.get_liability(PRIVACY_LIABILITY).privacy.find_violating_sims():
                        return self.PRIVACY_BLOCK
            else:
                if not self.interaction.get_liability(PRIVACY_LIABILITY).privacy.has_shooed:
                    return self.PRIVACY_SHOO
                if self.interaction.get_liability(PRIVACY_LIABILITY).privacy.find_violating_sims():
                    return self.PRIVACY_BLOCK

    def _get_next_transition_info(self, sim):
        if self._get_path_spec(sim) is None:
            return (None, None, None, None, None)
        actor_transitions = self.get_remaining_transitions(sim)
        participant_type = self.interaction.get_participant_type(sim)
        if not actor_transitions:
            return (None, None, None, None, None)
        var_map = self.get_var_map(sim)
        current_state = sim.posture_state.get_posture_spec(var_map)
        next_state = actor_transitions[0]
        work = None
        privacy_status = self._get_privacy_status(sim)
        if privacy_status == self.PRIVACY_ENGAGE:
            target = next_state[BODY_POSTURE_TYPE_INDEX][BODY_TARGET_INDEX]
            self.interaction.add_liability(PRIVACY_LIABILITY, PrivacyLiability(self.interaction, target))
            sim.queue.on_required_sims_changed(self.interaction)
            if self.interaction.get_liability(PRIVACY_LIABILITY).privacy.find_violating_sims():
                work = interaction_routing.shoo(self.interaction)
        elif privacy_status == self.PRIVACY_SHOO:
            self.interaction.priority = Priority.Critical
            services.get_master_controller().reset_timestamp_for_sim(self.sim)
            self.derail(DerailReason.PRIVACY_ENGAGED, sim)
            self.interaction.get_liability(PRIVACY_LIABILITY).privacy.has_shooed = True
            self._privacy_initiation_time = services.time_service().sim_now
        elif privacy_status == self.PRIVACY_BLOCK:
            return (None, None, None, None, None)
        return (participant_type, current_state, next_state, actor_transitions, work)

    def is_multi_sim_entry(self, current_state, next_state):
        if current_state is None or next_state is None:
            return False
        return not current_state[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].multi_sim and next_state[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].multi_sim

    def is_multi_sim_exit(self, current_state, next_state):
        if current_state is None or next_state is None:
            return False
        return current_state[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].multi_sim and not next_state[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].multi_sim

    def is_multi_to_multi(self, current_state, next_state):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        if current_state is None or next_state is None:
            return False
        return current_state[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].multi_sim and next_state[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].multi_sim

    def _create_next_elements(self, timeline):
        no_work_sims = []
        executed_work = False
        any_participant_has_work = False
        for sim in self.get_transitioning_sims():
            participant_has_work = False
            if sim in self._sim_jobs:
                executed_work = True
                if sim not in self._sim_idles:
                    participant_has_work = True
            elif self._get_path_spec(sim) is not None:
                transitions_sim = self.get_remaining_transitions(sim)
                if transitions_sim:
                    if sim.posture.multi_sim and self.is_multi_sim_exit(self.get_previous_spec(sim), transitions_sim[0]) and sim.posture.linked_sim in self._sim_jobs:
                        pass
                    privacy_status = self._get_privacy_status(sim)
                    if privacy_status != self.PRIVACY_BLOCK:
                        participant_has_work = True
                    else:
                        now = services.time_service().sim_now
                        timeout = self.SIM_MINUTES_TO_WAIT_FOR_VIOLATORS
                        delta = now - self._privacy_initiation_time
                        if delta > clock.interval_in_sim_minutes(timeout):
                            self.cancel(FinishingType.TRANSITION_FAILURE)
                        else:
                            self._execute_work_as_element(timeline, sim, elements.SoftSleepElement(clock.interval_in_sim_minutes(1)))
            any_participant_has_work = any_participant_has_work or participant_has_work
            if not participant_has_work:
                no_work_sims.append(sim)
            while not not participant_has_work:
                if sim in self._sim_jobs:
                    pass
                executed_work = True
                self._sim_idles.discard(sim)
                self._execute_work_as_element(timeline, sim, functools.partial(self._execute_next_transition, sim))
        if any_participant_has_work:
            for sim in no_work_sims:
                while sim not in self._sim_idles:
                    self._execute_work_as_element(timeline, sim, functools.partial(self._execute_next_transition, sim, no_work=True))
                    self._sim_idles.add(sim)
        if any_participant_has_work and not executed_work:
            raise RuntimeError('Deadlock in the transition sequence.\n Interaction: {},\n Participants: {},\n Full path_specs: {} \n[tastle]'.format(self.interaction, self.get_transitioning_sims(), [sim_data.path_spec for sim_data in self._sim_data.values()]))

    def _execute_work_as_element(self, timeline, sim, work):
        self._sim_jobs.add(sim)
        child = build_element([build_critical_section_with_finally(work, lambda _: self._sim_jobs.discard(sim)), self._create_next_elements])
        self._worker_all_element.add_work(timeline, child)

    def _execute_next_transition(self, sim, timeline, no_work=False):
        if any(self._derailed.values()):
            return False
        selected_work = None
        if not no_work:
            (participant_type, sim_current_state, sim_next_state, _, work) = self._get_next_transition_info(sim)
            if work is not None:
                single_sim_transition = build_element(work)
                selected_work = single_sim_transition
            else:
                multi_sim_exit_sim = self.is_multi_sim_exit(sim_current_state, sim_next_state)
                if multi_sim_exit_sim:
                    target = sim.posture.linked_sim
                    sim_multi_exit = self._create_transition_multi_exit(sim, sim_next_state)
                    sim_multi_exit = build_element(sim_multi_exit)
                    selected_work = sim_multi_exit
                multi_sim_entry_sim = self.is_multi_sim_entry(sim_current_state, sim_next_state)
                if not multi_sim_exit_sim and participant_type is ParticipantType.Actor:
                    target = self.interaction.get_participant(ParticipantType.TargetSim)
                    if target is not None:
                        (_, current_state_target, next_state_target, _, _) = self._get_next_transition_info(target)
                        multi_sim_entry_target = self.is_multi_sim_entry(current_state_target, next_state_target)
                        multi_sim_entry = multi_sim_entry_sim and multi_sim_entry_target
                        if multi_sim_entry:
                            multi_sim_entry = self._create_transition_multi_entry(sim, sim_next_state, target, next_state_target)
                            multi_sim_entry = build_element(multi_sim_entry)
                            if selected_work is not None:
                                raise RuntimeError('Multiple work units planned in _execute_next_transition')
                            selected_work = multi_sim_entry
                if sim_next_state is not None and not multi_sim_entry_sim and not multi_sim_exit_sim:
                    single_sim_transition = self._create_transition_single(sim, sim_next_state, participant_type)
                    single_sim_transition = build_element(single_sim_transition)
                    if selected_work is not None:
                        raise RuntimeError('Multiple work units planned in _execute_next_transition')
                    selected_work = single_sim_transition
        if selected_work is None and sim not in self._sim_idles:

            def _do_idle_behavior(timeline):
                result = yield element_utils.run_child(timeline, (sim.posture.get_idle_behavior(), flush_all_animations, elements.SoftSleepElement(clock.interval_in_real_seconds(self.SLEEP_TIME_FOR_IDLE_WAITING))))
                return result

            selected_work = _do_idle_behavior
        if selected_work is not None:
            result = yield self._do(timeline, sim, selected_work)
            if not result:
                if self._shortest_path_success[sim]:
                    self.derail(DerailReason.TRANSITION_FAILED, sim, test_result=result)
                else:
                    self.cancel(test_result=result)
                return False
        return True

