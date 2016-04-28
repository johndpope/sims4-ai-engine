from element_utils import build_element, build_critical_section_with_finally, maybe
from interactions.utils.animation import create_run_animation, flush_all_animations, flush_all_animations_instantly
from interactions.utils.reserve import create_reserver, MultiReserveObjectHandler
from postures import PostureEvent
from element_utils import CleanupType
from primitives.staged import StageControllerElement
import element_utils
import elements
import objects.system
import sims4.log
import services
logger = sims4.log.Logger('Postures')

class PosturePrimitive(StageControllerElement):
    __qualname__ = 'PosturePrimitive'

    def __init__(self, posture, animate_in, dest_state, context):
        super().__init__(posture.sim)
        self._posture = posture
        self._animate_in = animate_in
        self._dest_state = dest_state
        self._context = context
        self._posture_censor_handle = None
        self.finished = False
        self._jig_ref = None
        self._prev_posture = None
        if dest_state.body.source_interaction is None:
            logger.error('{}: Aspect has no source: {}', self, dest_state.body)

    @property
    def _jig(self):
        if self._jig_ref is not None:
            return self._jig_ref()

    @_jig.setter
    def _jig(self, value):
        if value is not None:
            self._jig_ref = value.ref()

    def __repr__(self):
        return '{}({})'.format(type(self).__name__, self._posture)

    def _clear_refs(self):
        self._animate_in = None
        self._dest_state = None
        self._context = None

    def _do_perform_gen(self, timeline):
        posture_element = self._get_behavior()
        result = yield element_utils.run_child(timeline, posture_element)
        return result

    def _get_behavior(self):
        posture = self._posture
        sim = posture.sim
        multi_sim_posture_transition = posture.multi_sim and not posture.is_puppet
        prev_posture_state = sim.posture_state
        self._prev_posture = prev_posture_state.get_aspect(posture.track)
        animate_in = None
        if multi_sim_posture_transition or self._animate_in is not None and not self._animate_in.empty:
            animate_in = create_run_animation(self._animate_in)
        my_stage = self._stage()

        def posture_change(timeline):
            posture.log_info('Change', msg='{}'.format(posture.track.name if posture.track is not None else 'NO TRACK!'))
            prev_posture_state = sim.posture_state
            prev_posture = prev_posture_state.get_aspect(posture.track)
            sim.posture_state = self._dest_state
            sim.on_posture_event(PostureEvent.POSTURE_CHANGED, self._dest_state, posture.track, prev_posture, posture)
            yield sim.si_state.notify_posture_change_and_remove_incompatible_gen(timeline, prev_posture_state, self._dest_state)
            prev_posture.clear_owning_interactions()
            if multi_sim_posture_transition:
                linked_posture_begin = posture.linked_posture.begin(self._animate_in, self._dest_state.linked_posture_state, posture._context)
                self._dest_state = None
                yield element_utils.run_child(timeline, linked_posture_begin)
            else:
                self._dest_state = None
            return True

        def end_posture_on_same_track(timeline):
            if self._prev_posture is not None and self._prev_posture is not posture:
                prev_posture = self._prev_posture
                self._prev_posture = None
                result = yield element_utils.run_child(timeline, build_element(prev_posture.end()))
                return result
            return True

        if services.current_zone().animate_instantly:
            flush = flush_all_animations_instantly
        else:
            flush = flush_all_animations
        sequence = (posture_change, animate_in, flush, end_posture_on_same_track, my_stage)
        sequence = build_element(sequence, critical=CleanupType.RunAll)
        sequence = build_critical_section_with_finally(sequence, lambda _: posture._release_animation_context())
        if self._posture.jig is not None and self._posture.target is not None and self._posture.slot_constraint is not None:

            def create_and_place_jig(_):
                self._jig = objects.system.create_object(self._posture.jig)
                for constraint in self._posture.slot_constraint:
                    self._jig.transform = constraint.containment_transform
                    break
                sim.routing_context.ignore_footprint_contour(self._jig.routing_context.object_footprint_id)

            def destroy_jig(_):
                if self._jig is not None:
                    sim.routing_context.remove_footprint_contour_override(self._jig.routing_context.object_footprint_id)
                    self._jig.destroy(source=self, cause='Destroying jig for posture.')

            sequence = build_critical_section_with_finally(create_and_place_jig, sequence, destroy_jig)
        sequence = elements.GeneratorElement(self.with_censor_grid(sim, sequence))
        if posture.target is not None:
            reserver = create_reserver(sim, posture.target, reserver=posture, handler=MultiReserveObjectHandler)
            sequence = reserver.do_reserve(sequence=sequence)

        def stage_on_fail(timeline):
            if not self.has_staged:
                yield element_utils.run_child(timeline, self._stage_fail())

        sequence = element_utils.build_critical_section(sequence, stage_on_fail)
        sequence = maybe(posture.test, sequence)
        return sequence

    def with_censor_grid(self, sim, sequence):

        def _with_censor_grid_gen(timeline):
            if self._posture.censor_level is not None:

                def _add_censor(timeline):
                    self._posture_censor_handle = sim.censorgrid_component.add_censor(self._posture.censor_level)

                def _remove_censor(timeline):
                    sim.censorgrid_component.remove_censor(self._posture_censor_handle)

                child_sequence = element_utils.build_critical_section_with_finally(_add_censor, sequence, _remove_censor)
            else:
                child_sequence = sequence
            result = yield element_utils.run_child(timeline, child_sequence)
            return result

        return _with_censor_grid_gen

    def _hard_stop(self):
        super()._hard_stop()
        if self._prev_posture is not None and self._prev_posture._primitive is not None and self._prev_posture._primitive is not self:
            self._prev_posture._primitive.trigger_hard_stop()
            self._prev_posture = None
        if self._posture is not None:
            self._posture._on_reset()
            self._posture = None

