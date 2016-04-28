import weakref
from element_utils import must_run, build_element
from event_testing.results import TestResult
from interactions.interaction_finisher import FinishingType
from interactions.utils.animation import ArbElement, get_auto_exit
from interactions.utils.balloon import PassiveBalloons
from interactions.utils.routing import WalkStyleTuning
from postures import PostureTrack, PostureEvent
from postures.posture_specs import PostureSpecVariable
from sims4.collections import frozendict
import animation.arb
import element_utils
import elements
import enum
import sims4.log
logger = sims4.log.Logger('PostureTransition')

class PostureStateTransition(elements.SubclassableGeneratorElement):
    __qualname__ = 'PostureStateTransition'

    def __init__(self, dest_state, source_interaction, context, var_map, transition_spec, reason_interaction, owning_interaction, should_reserve, destination_constraint):
        super().__init__()
        self._dest_state = dest_state
        self._source_interaction = source_interaction
        self._context = context
        self._var_map = var_map
        self._reason_interaction_ref = weakref.ref(reason_interaction)
        self._owning_interaction_ref = weakref.ref(owning_interaction) if owning_interaction is not None else None
        self._transition = None
        self._transition_spec = transition_spec
        self._should_reserve = should_reserve
        self._destination_constraint = destination_constraint

    @property
    def is_routing(self):
        if self._transition is not None:
            return self._transition.is_routing
        return False

    def _run_gen(self, timeline):
        dest_state = self._dest_state
        sim = dest_state.sim
        source_state = sim.posture_state
        dest_aspect = None
        if source_state.body != dest_state.body:
            dest_aspect = dest_state.body
        if source_state.left != dest_state.left:
            dest_aspect = dest_state.left
        if source_state.right != dest_state.right:
            dest_aspect = dest_state.right

        def create_transition(dest_aspect):
            reserve_target_interaction = None
            if self._should_reserve:
                reserve_target_interaction = self._reason_interaction_ref()
            return PostureTransition(dest_aspect, dest_state, self._context, self._var_map, self._transition_spec, reserve_target_interaction, self._destination_constraint)

        if dest_aspect is None:
            if source_state.body.mobile and dest_state.body.mobile:
                self._transition = create_transition(dest_state.body)
                transition_result = yield element_utils.run_child(timeline, self._transition)
                if not transition_result:
                    return transition_result
            sim.posture_state = dest_state
            if self._source_interaction is not None:
                dest_state.body.source_interaction = self._source_interaction
            if self._owning_interaction_ref is not None:
                self._owning_interaction_ref().acquire_posture_ownership(dest_state.body)
            yield sim.si_state.notify_posture_change_and_remove_incompatible_gen(timeline, source_state, dest_state)
            return TestResult.TRUE
        if self._source_interaction is not None:
            dest_aspect.source_interaction = self._source_interaction
        if self._owning_interaction_ref is not None:
            self._owning_interaction_ref().acquire_posture_ownership(dest_aspect)
        self._transition = create_transition(dest_aspect)
        result = yield element_utils.run_child(timeline, self._transition)
        return result

class PostureTransition(elements.SubclassableGeneratorElement):
    __qualname__ = 'PostureTransition'

    class Status(enum.Int, export=False):
        __qualname__ = 'PostureTransition.Status'
        INITIAL = 0
        ROUTING = 1
        ANIMATING = 2
        FINISHED = 3

    IDLE_TRANSITION_XEVT = 750
    IDLE_STOP_CUSTOM_XEVT = 751

    def __init__(self, dest, dest_state, context, var_map, transition_spec=None, interaction=None, constraint=None):
        super().__init__()
        self._source = None
        self._dest = dest
        self._dest_state = dest_state
        self._context = context
        self._var_map = var_map
        self._status = self.Status.INITIAL
        self._transition_spec = transition_spec
        self._interaction = interaction
        self._constraint = constraint

    def __repr__(self):
        return '<PostureTransition: {} to {}>'.format(self._source or 'current posture', self._dest)

    @property
    def destination_posture(self):
        return self._dest

    @property
    def status(self):
        return self._status

    @property
    def is_routing(self):
        return self._status == self.Status.ROUTING

    @property
    def source(self):
        return self._source

    def _get_unholster_predicate(self, sim, interaction):

        def unholster_predicate(obj):
            if obj.carryable_component.unholster_on_long_route_only:
                path = self._transition_spec.path
                if path is not None:
                    if path.length() > WalkStyleTuning.SHORT_WALK_DIST:
                        return True
            if interaction is None:
                return True
            return interaction.should_unholster_carried_object(obj)

        return unholster_predicate

    def _do_transition(self, timeline) -> bool:
        source = self._source
        dest = self._dest
        sim = dest.sim
        posture_track = dest.track
        starting_position = sim.position

        def do_auto_exit(timeline):
            auto_exit_element = get_auto_exit((sim,), asm=source.asm)
            if auto_exit_element is not None:
                yield element_utils.run_child(timeline, auto_exit_element)

        arb = animation.arb.Arb()
        if dest.external_transition:
            dest_begin = dest.begin(None, self._dest_state, self._context)
            result = yield element_utils.run_child(timeline, must_run(dest_begin))
            return result
        try:
            sim.active_transition = self
            posture_idle_started = False

            def start_posture_idle(*_, **__):
                nonlocal posture_idle_started
                if posture_idle_started:
                    return
                dest.log_info('Idle')
                posture_idle_started = True
                idle_arb = animation.arb.Arb()
                dest.append_idle_to_arb(idle_arb)
                ArbElement(idle_arb, master=sim).distribute()

            arb.register_event_handler(start_posture_idle, handler_id=self.IDLE_TRANSITION_XEVT)
            if sim.posture.mobile and self._transition_spec.path is not None:
                yield element_utils.run_child(timeline, do_auto_exit)
                result = yield self.do_transition_route(timeline, sim, source, dest)
                if not result:
                    return result
            else:
                result = self._transition_spec.do_reservation(sim)
                if not result:
                    return result
            if self._transition_spec is not None and self._transition_spec.portal is not None:
                portal_transition = self._transition_spec.portal.get_portal_element(sim)
                yield element_utils.run_child(timeline, portal_transition)
            if source is dest:
                sim.on_posture_event(PostureEvent.POSTURE_CHANGED, self._dest_state, dest.track, source, dest)
                return TestResult.TRUE
            self._status = self.Status.ANIMATING
            source_locked_params = frozendict()
            dest_locked_params = frozendict()
            dest_posture_spec = None
            if self._transition_spec is not None and dest.track == PostureTrack.BODY:
                if not source.mobile:
                    source_locked_params = self._transition_spec.locked_params
                if not dest.mobile:
                    dest_locked_params = self._transition_spec.locked_params
                    if self._interaction is not None:
                        dest_locked_params += self._interaction.transition_asm_params
                dest_posture_spec = self._transition_spec.posture_spec

            def do_transition_animation(timeline):
                yield element_utils.run_child(timeline, do_auto_exit)
                source.append_exit_to_arb(arb, self._dest_state, dest, self._var_map, locked_params=source_locked_params)
                dest.append_transition_to_arb(arb, source, locked_params=dest_locked_params, posture_spec=dest_posture_spec)
                dest_begin = dest.begin(arb, self._dest_state, self._context)
                result = yield element_utils.run_child(timeline, [do_auto_exit, dest_begin])
                return result

            sequence = (do_transition_animation,)
            from carry import interact_with_carried_object, holster_carried_object
            if dest.track.is_carry(dest.track):
                if dest.target is not None:
                    carry_target = dest.target
                    carry_posture_state = self._dest_state
                    carry_animation_context = dest.asm.context
                else:
                    carry_target = source.target
                    carry_posture_state = sim.posture_state
                    carry_animation_context = source.asm.context
                sequence = interact_with_carried_object(sim, carry_target, posture_state=carry_posture_state, interaction=dest.source_interaction, animation_context=carry_animation_context, sequence=sequence)
            sequence = holster_carried_object(sim, dest.source_interaction, self._get_unholster_predicate(sim, dest.source_interaction), flush_before_sequence=True, sequence=sequence)
            sequence = dest.add_transition_extras(sequence)
            sis = set()
            sis.add(source.source_interaction)
            sis.add(dest.source_interaction)
            sis.update(source.owning_interactions)
            sis.update(dest.owning_interactions)
            for si in sis:
                if si is None:
                    pass
                with si.cancel_deferred(sis):
                    result = yield element_utils.run_child(timeline, must_run(sequence))
                break
            result = yield element_utils.run_child(timeline, must_run(sequence))
            if result:
                start_posture_idle()
            yield sim.si_state.process_gen(timeline)
        finally:
            sim.active_transition = None
            self._status = self.Status.FINISHED
            if self._transition_spec is not None:
                self._transition_spec.release_additional_reservation_handlers()
                self._transition_spec.remove_props_created_to_reserve_slots(sim)
        if sim.posture_state.get_aspect(posture_track) is not dest:
            logger.debug("{}: _do_transition failed: after transition Sim's posture state aspect isn't destination posture.")
            if dest.source_interaction is not None:
                dest.source_interaction.cancel(FinishingType.TRANSITION_FAILURE, cancel_reason_msg='Transition canceled during transition.')
            return TestResult(False, "After transition Sim's posture state aspect isn't destination posture.")
        if not dest.unconstrained and sim.transition_controller is not None and not sims4.math.vector3_almost_equal(sim.position, starting_position, epsilon=sims4.geometry.ANIMATION_SLOT_EPSILON):
            sim.transition_controller.release_stand_slot_reservations((sim,))
        return TestResult.TRUE

    def do_transition_route(self, timeline, sim, source, dest):
        self._status = self.Status.ROUTING
        if self._transition_spec is not None and self._transition_spec.path is not None:
            constraint = self._dest_state.constraint_intersection
            fade_sim_out = self._interaction.should_fade_sim_out() if self._interaction is not None else False
            dest_posture_route = self._transition_spec.get_transition_route(sim, fade_sim_out, dest)
            result = False
            try:
                from carry import holster_objects_for_route, holster_carried_object
                sequence = holster_objects_for_route(sim, sequence=dest_posture_route)
                if self._interaction is not None and self._interaction.walk_style is not None:
                    sim.request_walkstyle(self._interaction.walk_style, id(self))
                sequence = holster_carried_object(sim, dest.source_interaction, self._get_unholster_predicate(sim, dest.source_interaction), flush_before_sequence=True, sequence=sequence)
                if self._interaction is not None:
                    PassiveBalloons.request_routing_to_object_balloon(sim, self._interaction)
                result = yield element_utils.run_child(timeline, sequence)
                sim.schedule_environment_score_update(force_run=True)
            finally:
                sim.remove_walkstyle(id(self))
            if not result:
                logger.debug('{}: Transition canceled or failed: {}', self, result)
                return TestResult(False, 'Transition Route/Reservation Failed')
        return TestResult.TRUE

    def _run_gen(self, timeline):
        dest = self._dest
        posture_track = dest.track
        sim = dest.sim
        source = sim.posture_state.get_aspect(posture_track)
        self._source = source
        dest.log_info('Transition', msg='from {}'.format(source))
        dest.sim.on_posture_event(PostureEvent.TRANSITION_START, self._dest_state, posture_track, source, dest)
        result = yield self._do_transition(timeline)
        if result:
            dest.sim.on_posture_event(PostureEvent.TRANSITION_COMPLETE, self._dest_state, posture_track, source, dest)
        else:
            dest.sim.on_posture_event(PostureEvent.TRANSITION_FAIL, self._dest_state, posture_track, source, dest)
        return result

