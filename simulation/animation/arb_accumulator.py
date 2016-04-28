from weakref import WeakKeyDictionary
import time
from element_utils import must_run
from interactions.utils.animation import ArbElement, AnimationSleepElement, get_actors_for_arb_sequence
from sims4.tuning.tunable import TunableRealSecond, Tunable
import animation.arb
import distributor.system
import element_utils
import elements
import interactions.utils.animation
import services
import sims4.callback_utils
import sims4.log
import sims4.service_manager
logger = sims4.log.Logger('ArbAccumulator')
dump_logger = sims4.log.LoggerClass('ArbAccumulator')

class AccumulatorArb(animation.arb.Arb):
    __qualname__ = 'AccumulatorArb'

def _get_actors_for_arb_element_sequence(arb_element_sequence, main_timeline_only=False):
    all_actors = set()
    for arb_element in arb_element_sequence:
        for actor in arb_element._actors(main_timeline_only):
            while actor.is_sim:
                all_actors.add(actor)
    return all_actors

def with_skippable_animation_time(actors, sequence=None):

    def _with_skippable_animation_time(timeline):
        game_clock_service = services.game_clock_service()
        then = game_clock_service.now()
        yield element_utils.run_child(timeline, sequence)
        now = game_clock_service.now()
        duration = (now - then).in_real_world_seconds()
        arb_accumulator = services.current_zone().arb_accumulator_service
        for actor in actors:
            time_debt = arb_accumulator.get_time_debt((actor,))
            new_time_debt = max(0, time_debt - duration)
            arb_accumulator.set_time_debt((actor,), new_time_debt)

    return element_utils.build_element(_with_skippable_animation_time)

class ArbSequenceElement(elements.SubclassableGeneratorElement):
    __qualname__ = 'ArbSequenceElement'

    def __init__(self, arb_element_sequence, *args, animate_instantly=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._arb_element_sequence = arb_element_sequence
        self._current_arb_element = None
        self._animate_instantly = animate_instantly

    def _run_gen(self, timeline):
        if not self._arb_element_sequence:
            return True
        duration_must_run = 0
        for arb_element in self._arb_element_sequence:
            (arb_duration_total, arb_duration_must_run, arb_duration_repeat) = arb_element.arb.get_timing()
            arb_duration_interrupt = arb_duration_total - arb_duration_must_run
            duration_must_run += arb_duration_must_run
            arb_element.distribute()
        duration_interrupt = arb_duration_interrupt
        duration_repeat = arb_duration_repeat
        if ArbAccumulatorService.MAXIMUM_TIME_DEBT > 0:
            actors = _get_actors_for_arb_element_sequence(self._arb_element_sequence, main_timeline_only=True)
            arb_accumulator = services.current_zone().arb_accumulator_service
            time_debt_max = arb_accumulator.get_time_debt(actors)
            shave_time_actual = arb_accumulator.get_shave_time_given_duration_and_debt(duration_must_run, time_debt_max)
            duration_must_run -= shave_time_actual
            for actor in actors:
                time_debt = arb_accumulator.get_time_debt((actor,))
                time_debt += shave_time_actual
                arb_accumulator.set_time_debt((actor,), time_debt)
        animation_sleep_element = AnimationSleepElement(duration_must_run, duration_interrupt, duration_repeat)
        if not self._animate_instantly:
            yield element_utils.run_child(timeline, animation_sleep_element)
        optional_time_elapsed = animation_sleep_element.optional_time_elapsed
        if ArbAccumulatorService.MAXIMUM_TIME_DEBT > 0 and optional_time_elapsed > 0:
            while True:
                for actor in actors:
                    time_debt = arb_accumulator.get_time_debt((actor,))
                    new_time_debt = time_debt - optional_time_elapsed
                    new_time_debt = max(new_time_debt, 0)
                    arb_accumulator.set_time_debt((actor,), new_time_debt)
        return True

class _arb_parallelizer:
    __qualname__ = '_arb_parallelizer'

    def __init__(self, arb_accumulator):
        self._arb_accumulator = arb_accumulator
        self._arb_sequence = None
        self._old_add_arb_fn = None

    def _add_arb(self, arb, on_done_fn=None):
        if arb.empty:
            return
        if self._arb_sequence is None:
            self._arb_sequence = []
        self._arb_sequence.append(arb)

    def __enter__(self):
        self._old_add_arb_fn = self._arb_accumulator.add_arb
        self._arb_accumulator.add_arb = self._add_arb

    def __exit__(self, exc_type, exc_value, traceback):
        self._arb_accumulator.add_arb = self._old_add_arb_fn
        if self._arb_sequence:
            self._arb_accumulator.add_arb(self._arb_sequence)

class ArbAccumulatorService(sims4.service_manager.Service):
    __qualname__ = 'ArbAccumulatorService'
    CUSTOM_EVENT = 901
    MAX_XEVT = 999
    MAXIMUM_TIME_DEBT = TunableRealSecond(1, description='\n    The maximum amount of time in seconds to allow the server to run ahead \n    of the client when running a contiguous block of animation/routing to \n    improve blending. Setting this to 0 will disable this feature but ruin blending.')
    MAXIMUM_SHAVE_FRAMES_PER_ANIMATION = Tunable(int, 5, description='\n    The maximum number of frames to shave off of the must-run duration of each \n    animation until we reach a total amount of time debt equal to MAXIMUM_TIME_DEBT.')
    MAXIMUM_SHAVE_ANIMATION_RATIO = Tunable(float, 2, description='\n    The maximum ratio of an animation to shave off. For example, if this\n    is tuned to 2, we will shave off at most 1/2 of the total must-run\n    duration of an animation.\n    ')

    @staticmethod
    def get_shave_time_given_duration_and_debt(duration, debt):
        shave_time_max = max(0, ArbAccumulatorService.MAXIMUM_TIME_DEBT - debt)
        shave_time_requested = min(duration/ArbAccumulatorService.MAXIMUM_SHAVE_ANIMATION_RATIO, 0.03333333333333333*ArbAccumulatorService.MAXIMUM_SHAVE_FRAMES_PER_ANIMATION)
        shave_time_actual = min(shave_time_max, shave_time_requested)
        return shave_time_actual

    def __init__(self, from_idle_fn, to_idle_fn):
        self._from_idle_func = from_idle_fn
        self._to_idle_func = to_idle_fn
        self._arb_sequence = []
        self._on_done = sims4.callback_utils.CallableList()
        self._in_flush = False
        self._custom_xevt_id_generator = self.CUSTOM_EVENT
        self._sequence_parallel = None
        self._time_debt = WeakKeyDictionary()
        self._shave_time = WeakKeyDictionary()

    def get_time_debt(self, sims):
        max_debt = 0
        for sim in sims:
            if sim not in self._time_debt:
                pass
            sim_debt = self._time_debt[sim]
            while sim_debt > max_debt:
                max_debt = sim_debt
        return max_debt

    def set_time_debt(self, sims, debt):
        for sim in sims:
            self._time_debt[sim] = debt

    def _clear(self):
        self._arb_sequence = []
        self._on_done = sims4.callback_utils.CallableList()
        self._custom_xevt_id_generator = self.CUSTOM_EVENT

    def parallelize(self):
        return _arb_parallelizer(self)

    def add_arb(self, arb, on_done_fn=None):
        if isinstance(arb, list):
            arbs = arb
        else:
            arbs = (arb,)
        for sub_arb in arbs:
            while not sub_arb._actors():
                logger.error('Attempt to play animation that has no connected actors:')
                sub_arb.log_request_history(dump_logger.error)
        if self._in_flush:
            for sub_arb in arbs:
                logger.debug('\n\nEvent-triggered ARB:\n{}\n\n', sub_arb.get_contents_as_string())
                interactions.utils.animation.ArbElement(sub_arb).distribute()
                while on_done_fn is not None:
                    on_done_fn()
            return
        self._arb_sequence.append(arb)
        if on_done_fn is not None:
            self._on_done.append(on_done_fn)

    def claim_xevt_id(self):
        event_id = self._custom_xevt_id_generator
        if self._custom_xevt_id_generator == self.MAX_XEVT:
            logger.warn('Excessive XEVT IDs claimed before a flush. This is likely caused by an error in animation requests. -RS')
        return event_id

    def _add_idles_to_arb_element(self, arb_element, on_done):
        all_actors = arb_element._actors()
        actors_with_idles = set()
        if self._to_idle_func is not None:
            for actor in all_actors:
                while actor.is_sim:
                    if not arb_element.arb._normal_timeline_ends_in_looping_content(actor.id):
                        (to_idle_arb, on_done_func) = self._to_idle_func(actor)
                        if on_done_func is not None:
                            on_done.append(on_done_func)
                        if to_idle_arb is not None:
                            arb_element.execute_and_merge_arb(to_idle_arb, False)
                            actors_with_idles.add(actor)
        return actors_with_idles

    def _begin_arb_element(self, all_actors, actors_with_idles, on_done):
        element = interactions.utils.animation.ArbElement(animation.arb.Arb(), [])
        if actors_with_idles and self._from_idle_func is not None:
            for actor in actors_with_idles:
                (from_idle_arb, on_done_idle) = self._from_idle_func(actor)
                if on_done_idle is not None:
                    on_done.append(on_done_idle)
                while from_idle_arb is not None:
                    self._append_arb_to_element(element, from_idle_arb, all_actors, False)
            actors_with_idles.clear()
        return element

    def _flush_arb_element(self, element_run_queue, arb_element, all_actors, on_done, closes_sequence):
        if not arb_element.arb.empty:
            actors_with_idles = self._add_idles_to_arb_element(arb_element, on_done)
            if not closes_sequence:
                arb_element.enable_optional_sleep_time = False
            if arb_element.arb.empty:
                raise RuntimeError('About to flush an empty Arb')
            element_run_queue.append(arb_element)
            if not closes_sequence:
                return self._begin_arb_element(all_actors, actors_with_idles, on_done)
            return
        return arb_element

    def _append_arb_to_element(self, buffer_arb_element, arb, actors, safe_mode, attach=True):
        if not arb.empty and buffer_arb_element.arb._can_append(arb, safe_mode):
            buffer_arb_element.event_records = buffer_arb_element.event_records or []
            if attach:
                buffer_arb_element.attach(*actors)
            buffer_arb_element.execute_and_merge_arb(arb, safe_mode)
            return True
        return False

    def _append_arb_element_to_element(self, buffer_arb_element, arb_element, actors, safe_mode):
        if not arb_element.arb.empty and buffer_arb_element.arb._can_append(arb_element.arb, safe_mode):
            buffer_arb_element.event_records = buffer_arb_element.event_records or []
            buffer_arb_element.attach(*actors)
            buffer_arb_element.event_records.extend(arb_element.event_records)
            buffer_arb_element.arb.append(arb_element.arb, safe_mode)
            return True
        return False

    def flush(self, timeline, animate_instantly=False):
        arb_sequence = self._arb_sequence
        on_done = self._on_done
        self._clear()
        actors = get_actors_for_arb_sequence(*arb_sequence)
        self._in_flush = True
        try:
            while len(actors) > 0:
                first_unprocessed_arb = 0
                sequence_len = len(arb_sequence)
                buffer_arb_element = None
                element_run_queue = []
                sim_actors = [actor for actor in actors if actor.is_sim]
                with distributor.system.Distributor.instance().dependent_block():
                    while first_unprocessed_arb < sequence_len:
                        if buffer_arb_element is None:
                            buffer_arb_element = self._begin_arb_element(actors, sim_actors, on_done)
                        for i in range(first_unprocessed_arb, sequence_len):
                            arb = arb_sequence[i]
                            if isinstance(arb, list):
                                combined_arb = animation.arb.Arb()
                                for sub_arb in arb:
                                    combined_arb.append(sub_arb, False, True)
                                if not buffer_arb_element.arb._can_append(combined_arb, True):
                                    break
                                buffer_arb_element.attach(*actors)
                                buffer_arb_element_parallel = self._begin_arb_element(actors, None, on_done)
                                result = self._append_arb_to_element(buffer_arb_element_parallel, combined_arb, actors, False, attach=False)
                                arb_sequence[i] = buffer_arb_element_parallel
                                arb = buffer_arb_element_parallel
                                buffer_arb_element_parallel.detach()
                            if isinstance(arb, ArbElement):
                                append_fn = self._append_arb_element_to_element
                            else:
                                append_fn = self._append_arb_to_element
                            if not append_fn(buffer_arb_element, arb, actors, True):
                                first_unprocessed_arb = i
                                break
                            first_unprocessed_arb = i + 1
                        buffer_arb_element = self._flush_arb_element(element_run_queue, buffer_arb_element, actors, on_done, first_unprocessed_arb == sequence_len)
                self._in_flush = False
                arb_sequence_element = ArbSequenceElement(element_run_queue, animate_instantly=animate_instantly)
                yield element_utils.run_child(timeline, arb_sequence_element)
        finally:
            self._in_flush = False
            on_done()

