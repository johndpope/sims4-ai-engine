from _weakrefset import WeakSet
import weakref
from clock import ClockSpeedMode
from event_testing.resolver import InteractionResolver
from event_testing.results import TestResult
from interactions import PipelineProgress
from interactions.base.interaction import CANCEL_AOP_LIABILITY, InteractionFailureOptions, InteractionQueuePreparationStatus
from interactions.constraints import Nowhere
from interactions.context import InteractionBucketType, InteractionContext, InteractionSource, QueueInsertStrategy
from interactions.interaction_finisher import FinishingType
from interactions.priority import Priority
from interactions.si_state import can_priority_displace
from postures.transition_sequence import TransitionSequenceController, DerailReason
from server_commands.developer_commands import force_gsi_dump_on_error_or_exception
from sims.sim_log import log_interaction
from sims4.callback_utils import CallableList
from sims4.utils import EdgeWatcher
from singletons import UNSET
import clock
import element_utils
import elements
import gsi_handlers.sim_timeline_handlers
import performance.counters
import scheduling
import services
import sims4.log
__all__ = ['InteractionQueue', 'QueueView']
logger = sims4.log.Logger('Interaction Queue')

class BucketBase:
    __qualname__ = 'BucketBase'
    __slots__ = '_sim_ref'

    def __init__(self, sim):
        self._sim_ref = sim.ref()

    @property
    def _sim(self):
        if self._sim_ref is not None:
            return self._sim_ref()

    def __iter__(self):
        raise NotImplementedError()

    def __len__(self):
        raise NotImplementedError()

    def peek(self):
        for interaction in self:
            pass

    def _append(self, interaction):
        raise NotImplementedError()

    def append(self, interaction):
        log_interaction('Enqueue', interaction)
        result = self._append(interaction)
        return result

    def _insert_next(self, interaction, insert_after=None):
        raise NotImplementedError()

    def insert_next(self, interaction, **kwargs):
        log_interaction('Enqueue_Next', interaction)
        result = self._insert_next(interaction, **kwargs)
        return result

    def _clear_interaction(self, interaction):
        raise NotImplementedError()

    def clear_interaction(self, interaction):
        ret = self._clear_interaction(interaction)
        if ret:
            interaction.on_removed_from_queue()
        return ret

    def remove_for_perform(self, interaction):
        if self._clear_interaction(interaction):
            return interaction

    def on_reset(self):
        for interaction in list(self):
            try:
                log_interaction('Reset', interaction)
                self.clear_interaction(interaction)
                interaction.on_reset()
            except Exception:
                logger.exception('Exception caught while clearing interaction from bucket:')

class BucketSingle(BucketBase):
    __qualname__ = 'BucketSingle'
    __slots__ = ('_interaction',)

    def __init__(self, sim):
        super().__init__(sim)
        self._interaction = None

    def __iter__(self):
        if self._interaction is not None:
            yield self._interaction

    def __len__(self):
        if self._interaction is not None:
            return 1
        return 0

    def _enqueue(self, interaction):
        if not (self._interaction is not None and not self._interaction.is_finishing and self._interaction.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='Bucket Single Enqueue: {}'.format(interaction))):
            return TestResult(False, 'Unable to cancel existing interaction ({}) in BucketSingle.'.format(self._interaction))
        self._interaction = interaction
        return TestResult.TRUE

    def _append(self, interaction):
        result = self._enqueue(interaction)
        return result

    def _insert_next(self, interaction, insert_after=None):
        return self._enqueue(interaction)

    def _clear_interaction(self, interaction):
        if self._interaction is interaction:
            self._interaction = None
            interaction.on_removed_from_queue()
            return True
        return False

class BucketList(BucketBase):
    __qualname__ = 'BucketList'
    __slots__ = ('_interactions',)

    def __init__(self, sim):
        self._sim_ref = sim.ref()
        self._interactions = []

    def __iter__(self):
        return iter(self._interactions)

    def __len__(self):
        return len(self._interactions)

    def _append(self, interaction):
        self._interactions.append(interaction)
        return TestResult.TRUE

    def _insert_next(self, interaction, insert_after=None):
        index = 0
        if insert_after is not None:
            for (i, queued_interaction) in enumerate(self._interactions):
                while interaction.group_id == queued_interaction.group_id or queued_interaction is insert_after:
                    index = i + 1
        self._interactions.insert(index, interaction)
        return TestResult.TRUE

    def _clear_interaction(self, interaction):
        if not self._interactions or interaction not in self._interactions:
            return False
        self._interactions.remove(interaction)
        interaction.on_removed_from_queue()
        return True

class SuperInteractionBucket(BucketList):
    __qualname__ = 'SuperInteractionBucket'
    __slots__ = ()

    def peek(self):
        for si in self:
            if si.is_finishing:
                pass

    def _append(self, interaction):
        if interaction.is_super or len(self._interactions) == 0 or not interaction.should_insert_in_queue_on_append():
            self._interactions.append(interaction)
        else:
            for (i, queued_interaction) in enumerate(self._interactions):
                while queued_interaction.is_super and queued_interaction.context.insert_strategy == QueueInsertStrategy.LAST:
                    if queued_interaction.transition is not None and queued_interaction.transition.running:
                        pass
                    self._interactions.insert(i, interaction)
                    break
            self._interactions.append(interaction)
        return TestResult.TRUE

class AutonomyBucket(BucketList):
    __qualname__ = 'AutonomyBucket'
    __slots__ = ()

class SocialAdjustmentBucket(BucketSingle):
    __qualname__ = 'SocialAdjustmentBucket'
    __slots__ = ()

class BodyCancelAOPBucket(BucketList):
    __qualname__ = 'BodyCancelAOPBucket'
    __slots__ = ()

class CarryCancelAOPBucket(BucketList):
    __qualname__ = 'CarryCancelAOPBucket'
    __slots__ = ()

class InteractionQueue:
    __qualname__ = 'InteractionQueue'

    def __init__(self, sim):
        self._running = None
        self._super_interactions = SuperInteractionBucket(sim)
        self._autonomy = AutonomyBucket(sim)
        self._social_adjustment = SocialAdjustmentBucket(sim)
        self._body_cancel_replacements = BodyCancelAOPBucket(sim)
        self._carry_cancel_replacements = CarryCancelAOPBucket(sim)
        self._buckets = (self._social_adjustment, self._carry_cancel_replacements, self._super_interactions, self._body_cancel_replacements, self._autonomy)
        self._sim_ref = sim.ref()
        self.transition_controller = None
        self._locked = False
        self._must_run_next_interaction = None
        self.on_head_changed = CallableList()
        self._head_cache = UNSET
        self._si_state_changed_callback_sims = set()
        self._dumped_gsi_in_get_head = False

    @property
    def sim(self):
        if self._sim_ref is not None:
            return self._sim_ref()

    def __repr__(self):
        return 'InteractionQueue for {}'.format(self.sim)

    def __iter__(self):
        if self.running is not None:
            yield self.running
        for bucket in self._buckets:
            for interaction in bucket:
                if interaction is self.running:
                    pass
                yield interaction

    def __len__(self):
        return len(set(self))

    def log_interaction_queue(self, logger_func):
        logger_func('Interaction queue info for {}', self.sim)
        for bucket in list(self._buckets):
            for interaction in bucket:
                logger_func('    {}'.format(interaction))
        if self.running is not None:
            logger_func('Running interaction {}', self.sim)
            logger_func('    {}'.format(self.running))

    def _process_one_interaction_gen(self, timeline, interaction):
        result = False
        entered_si = False
        required_sims = None
        performance.counters.add_counter('PerfNumInteractions', 1)
        try:
            interaction.pipeline_progress = PipelineProgress.RUNNING
            if interaction.is_super:
                entered_si = yield interaction.enter_si_gen(timeline)
            else:
                entered_si = True
            while entered_si:
                required_sims = interaction.required_sims(for_threading=True)
                for sim in required_sims:
                    sim.queue.running = interaction
                result = yield self.run_interaction_gen(timeline, interaction)
        finally:
            if not result:
                interaction.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='process_one_interaction_gen: interaction failed to run.')
            if not entered_si:
                interaction.on_removed_from_queue()
            if required_sims:
                for sim in required_sims:
                    sim.queue.running = None
        return result

    def run_interaction_gen(self, timeline, interaction, source_interaction=None, apply_posture_state=True):
        if interaction.is_finishing:
            return False
        interaction_parameters = {}
        interaction_parameters['interaction_starting'] = True
        result = interaction.test(skip_safe_tests=True, **interaction_parameters)
        if not result:
            msg = 'Test failed at run_interaction: {}'.format(result)
            interaction.cancel(FinishingType.FAILED_TESTS, cancel_reason_msg=msg)
            log_interaction('Failed', interaction, msg=msg)
            return False
        log_interaction('Running', interaction)
        if interaction.target and interaction.target.objectage_component:
            interaction.target.update_last_used()
        if not interaction.disable_transitions:
            interaction.apply_posture_state(self.sim.posture_state)
        if interaction.is_super and (self._must_run_next_interaction is not None and (interaction.transition is not None and (interaction.transition.interaction is interaction and interaction is not self._must_run_next_interaction))) and (source_interaction is None or self._must_run_next_interaction is not source_interaction):
            self._must_run_next_interaction.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='InteractionQueue: run_interaction: must_run_next: {} canceled by {}'.format(self._must_run_next_interaction, interaction))
            self._must_run_next_interaction = None
        try:
            (result, failure_reason) = yield interaction.perform_gen(timeline)
        finally:
            interaction.on_removed_from_queue()
        if result:
            if interaction.is_super and interaction.suspended:
                log_interaction('Staged', interaction)
            else:
                log_interaction('Done', interaction)
        else:
            log_interaction('Failed', interaction, msg=failure_reason)
        return result

    def process_one_interaction_gen(self, timeline):
        head_first = self.get_head()
        while True:
            head = self.get_head()
            if head is None or head.is_finishing or head is not head_first:
                break
            result = head.test(skip_safe_tests=head.skip_test_on_execute())
            if not result:
                old_name = head.get_name()
                old_icon_info = head.get_icon_info()
                reason = result.reason if result.reason is not None else 'Interaction Queue head interaction failed tests'
                head.cancel(FinishingType.FAILED_TESTS, cancel_reason_msg=reason)
                self.remove_for_perform(head)
                if not (head.is_user_directed and (head.visible and (head.is_super and head.target_in_inventory_when_queued)) and head.target is None):
                    if not head.target.is_in_inventory():
                        continue
                    self.insert_route_failure_interaction(head, old_name, old_icon_info)
                    continue
                    continue
                    yield self.sim.si_state.process_gen(timeline)
                    if not head.is_super:
                        if head.pipeline_progress == PipelineProgress.QUEUED:
                            log_interaction('Preparing', head)
                            try:
                                result = yield head.prepare_gen(timeline)
                            except:
                                logger.exception('Error in prepare_gen for mixer interaction')
                                result = False
                            if result != InteractionQueuePreparationStatus.FAILURE:
                                head.pipeline_progress = PipelineProgress.PREPARED
                                return
                            else:
                                head.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='Failed to Prepare Interaction.')
                                continue
                                if head.prepared:
                                    head.pre_process_interaction()
                                    try:
                                        yield self._process_one_interaction_gen(timeline, head)
                                    finally:
                                        self.remove_for_perform(head)
                                    head.post_process_interaction()
                                    continue
                                    if head.pipeline_progress == PipelineProgress.QUEUED:
                                        head.pipeline_progress = PipelineProgress.PRE_TRANSITIONING
                                        if not head.run_pre_transition_behavior():
                                            log_interaction('PreTransition', head, msg='Failed')
                                            head.cancel(FinishingType.TRANSITION_FAILURE, cancel_reason_msg='Pre Transition Behavior Failed.')
                                            continue
                                        log_interaction('PreTransition', head, msg='Succeeded')
                                    if head.pipeline_progress == PipelineProgress.PRE_TRANSITIONING:
                                        log_interaction('Preparing', head)
                                        try:
                                            result = yield head.prepare_gen(timeline, cancel_incompatible_carry_interactions=True)
                                        except scheduling.HardStopError:
                                            raise
                                        except Exception:
                                            logger.exception('Exception in prepare_gen for super interaction.')
                                            result = InteractionQueuePreparationStatus.FAILURE
                                        if result == InteractionQueuePreparationStatus.NEEDS_DERAIL:
                                            (idle_element, _) = head.sim.get_idle_element(duration=1)
                                            yield element_utils.run_child(timeline, idle_element)
                                            return
                                        if result == InteractionQueuePreparationStatus.FAILURE:
                                            head.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='Failed to Prepare Interaction.')
                                        else:
                                            head.pipeline_progress = PipelineProgress.PREPARED
                                            continue
                                            if head.prepared:
                                                required_sims = head.required_sims(for_threading=True)
                                                if head.transition is None:
                                                    head.transition = TransitionSequenceController(head)
                                                for required_sim in required_sims:
                                                    required_sim.queue.transition_controller = head.transition
                                                if services.game_clock_service().clock_speed() == ClockSpeedMode.PAUSED and not services.current_zone().force_process_transitions:
                                                    sleep_paused_element = element_utils.build_element((element_utils.sleep_until_next_tick_element(), elements.SoftSleepElement(clock.interval_in_sim_seconds(1.0))))
                                                    yield element_utils.run_child(timeline, sleep_paused_element)
                                                with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self.sim, 'InteractionQueue', 'Run Transition', head):
                                                    head.sim.ui_manager.running_transition(head)
                                                    result = yield head.transition.run_transitions(timeline)
                                                for required_sim in required_sims:
                                                    required_sim.queue.transition_controller = None
                                                if head.transition is not None:
                                                    if head.transition.canceled:
                                                        head.transition = None
                                                    elif head.transition.any_derailed:
                                                        return
                                                if result or head.is_finishing:
                                                    head.transition = None
                                                    if head.is_finishing:
                                                        self.on_interaction_canceled(head)
                                                    else:
                                                        self.remove_for_perform(head)
                                                yield self.sim.si_state.process_gen(timeline)
                                    if head.prepared:
                                        required_sims = head.required_sims(for_threading=True)
                                        if head.transition is None:
                                            head.transition = TransitionSequenceController(head)
                                        for required_sim in required_sims:
                                            required_sim.queue.transition_controller = head.transition
                                        if services.game_clock_service().clock_speed() == ClockSpeedMode.PAUSED and not services.current_zone().force_process_transitions:
                                            sleep_paused_element = element_utils.build_element((element_utils.sleep_until_next_tick_element(), elements.SoftSleepElement(clock.interval_in_sim_seconds(1.0))))
                                            yield element_utils.run_child(timeline, sleep_paused_element)
                                        with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self.sim, 'InteractionQueue', 'Run Transition', head):
                                            head.sim.ui_manager.running_transition(head)
                                            result = yield head.transition.run_transitions(timeline)
                                        for required_sim in required_sims:
                                            required_sim.queue.transition_controller = None
                                        if head.transition is not None:
                                            if head.transition.canceled:
                                                head.transition = None
                                            elif head.transition.any_derailed:
                                                return
                                        if result or head.is_finishing:
                                            head.transition = None
                                            if head.is_finishing:
                                                self.on_interaction_canceled(head)
                                            else:
                                                self.remove_for_perform(head)
                                        yield self.sim.si_state.process_gen(timeline)
                        if head.prepared:
                            head.pre_process_interaction()
                            try:
                                yield self._process_one_interaction_gen(timeline, head)
                            finally:
                                self.remove_for_perform(head)
                            head.post_process_interaction()
                            continue
                            if head.pipeline_progress == PipelineProgress.QUEUED:
                                head.pipeline_progress = PipelineProgress.PRE_TRANSITIONING
                                if not head.run_pre_transition_behavior():
                                    log_interaction('PreTransition', head, msg='Failed')
                                    head.cancel(FinishingType.TRANSITION_FAILURE, cancel_reason_msg='Pre Transition Behavior Failed.')
                                    continue
                                log_interaction('PreTransition', head, msg='Succeeded')
                            if head.pipeline_progress == PipelineProgress.PRE_TRANSITIONING:
                                log_interaction('Preparing', head)
                                try:
                                    result = yield head.prepare_gen(timeline, cancel_incompatible_carry_interactions=True)
                                except scheduling.HardStopError:
                                    raise
                                except Exception:
                                    logger.exception('Exception in prepare_gen for super interaction.')
                                    result = InteractionQueuePreparationStatus.FAILURE
                                if result == InteractionQueuePreparationStatus.NEEDS_DERAIL:
                                    (idle_element, _) = head.sim.get_idle_element(duration=1)
                                    yield element_utils.run_child(timeline, idle_element)
                                    return
                                if result == InteractionQueuePreparationStatus.FAILURE:
                                    head.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='Failed to Prepare Interaction.')
                                else:
                                    head.pipeline_progress = PipelineProgress.PREPARED
                                    continue
                                    if head.prepared:
                                        required_sims = head.required_sims(for_threading=True)
                                        if head.transition is None:
                                            head.transition = TransitionSequenceController(head)
                                        for required_sim in required_sims:
                                            required_sim.queue.transition_controller = head.transition
                                        if services.game_clock_service().clock_speed() == ClockSpeedMode.PAUSED and not services.current_zone().force_process_transitions:
                                            sleep_paused_element = element_utils.build_element((element_utils.sleep_until_next_tick_element(), elements.SoftSleepElement(clock.interval_in_sim_seconds(1.0))))
                                            yield element_utils.run_child(timeline, sleep_paused_element)
                                        with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self.sim, 'InteractionQueue', 'Run Transition', head):
                                            head.sim.ui_manager.running_transition(head)
                                            result = yield head.transition.run_transitions(timeline)
                                        for required_sim in required_sims:
                                            required_sim.queue.transition_controller = None
                                        if head.transition is not None:
                                            if head.transition.canceled:
                                                head.transition = None
                                            elif head.transition.any_derailed:
                                                return
                                        if result or head.is_finishing:
                                            head.transition = None
                                            if head.is_finishing:
                                                self.on_interaction_canceled(head)
                                            else:
                                                self.remove_for_perform(head)
                                        yield self.sim.si_state.process_gen(timeline)
                            if head.prepared:
                                required_sims = head.required_sims(for_threading=True)
                                if head.transition is None:
                                    head.transition = TransitionSequenceController(head)
                                for required_sim in required_sims:
                                    required_sim.queue.transition_controller = head.transition
                                if services.game_clock_service().clock_speed() == ClockSpeedMode.PAUSED and not services.current_zone().force_process_transitions:
                                    sleep_paused_element = element_utils.build_element((element_utils.sleep_until_next_tick_element(), elements.SoftSleepElement(clock.interval_in_sim_seconds(1.0))))
                                    yield element_utils.run_child(timeline, sleep_paused_element)
                                with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self.sim, 'InteractionQueue', 'Run Transition', head):
                                    head.sim.ui_manager.running_transition(head)
                                    result = yield head.transition.run_transitions(timeline)
                                for required_sim in required_sims:
                                    required_sim.queue.transition_controller = None
                                if head.transition is not None:
                                    if head.transition.canceled:
                                        head.transition = None
                                    elif head.transition.any_derailed:
                                        return
                                if result or head.is_finishing:
                                    head.transition = None
                                    if head.is_finishing:
                                        self.on_interaction_canceled(head)
                                    else:
                                        self.remove_for_perform(head)
                                yield self.sim.si_state.process_gen(timeline)
                    else:
                        if head.pipeline_progress == PipelineProgress.QUEUED:
                            head.pipeline_progress = PipelineProgress.PRE_TRANSITIONING
                            if not head.run_pre_transition_behavior():
                                log_interaction('PreTransition', head, msg='Failed')
                                head.cancel(FinishingType.TRANSITION_FAILURE, cancel_reason_msg='Pre Transition Behavior Failed.')
                                continue
                            log_interaction('PreTransition', head, msg='Succeeded')
                        if head.pipeline_progress == PipelineProgress.PRE_TRANSITIONING:
                            log_interaction('Preparing', head)
                            try:
                                result = yield head.prepare_gen(timeline, cancel_incompatible_carry_interactions=True)
                            except scheduling.HardStopError:
                                raise
                            except Exception:
                                logger.exception('Exception in prepare_gen for super interaction.')
                                result = InteractionQueuePreparationStatus.FAILURE
                            if result == InteractionQueuePreparationStatus.NEEDS_DERAIL:
                                (idle_element, _) = head.sim.get_idle_element(duration=1)
                                yield element_utils.run_child(timeline, idle_element)
                                return
                            if result == InteractionQueuePreparationStatus.FAILURE:
                                head.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='Failed to Prepare Interaction.')
                            else:
                                head.pipeline_progress = PipelineProgress.PREPARED
                                continue
                                if head.prepared:
                                    required_sims = head.required_sims(for_threading=True)
                                    if head.transition is None:
                                        head.transition = TransitionSequenceController(head)
                                    for required_sim in required_sims:
                                        required_sim.queue.transition_controller = head.transition
                                    if services.game_clock_service().clock_speed() == ClockSpeedMode.PAUSED and not services.current_zone().force_process_transitions:
                                        sleep_paused_element = element_utils.build_element((element_utils.sleep_until_next_tick_element(), elements.SoftSleepElement(clock.interval_in_sim_seconds(1.0))))
                                        yield element_utils.run_child(timeline, sleep_paused_element)
                                    with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self.sim, 'InteractionQueue', 'Run Transition', head):
                                        head.sim.ui_manager.running_transition(head)
                                        result = yield head.transition.run_transitions(timeline)
                                    for required_sim in required_sims:
                                        required_sim.queue.transition_controller = None
                                    if head.transition is not None:
                                        if head.transition.canceled:
                                            head.transition = None
                                        elif head.transition.any_derailed:
                                            return
                                    if result or head.is_finishing:
                                        head.transition = None
                                        if head.is_finishing:
                                            self.on_interaction_canceled(head)
                                        else:
                                            self.remove_for_perform(head)
                                    yield self.sim.si_state.process_gen(timeline)
                        if head.prepared:
                            required_sims = head.required_sims(for_threading=True)
                            if head.transition is None:
                                head.transition = TransitionSequenceController(head)
                            for required_sim in required_sims:
                                required_sim.queue.transition_controller = head.transition
                            if services.game_clock_service().clock_speed() == ClockSpeedMode.PAUSED and not services.current_zone().force_process_transitions:
                                sleep_paused_element = element_utils.build_element((element_utils.sleep_until_next_tick_element(), elements.SoftSleepElement(clock.interval_in_sim_seconds(1.0))))
                                yield element_utils.run_child(timeline, sleep_paused_element)
                            with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self.sim, 'InteractionQueue', 'Run Transition', head):
                                head.sim.ui_manager.running_transition(head)
                                result = yield head.transition.run_transitions(timeline)
                            for required_sim in required_sims:
                                required_sim.queue.transition_controller = None
                            if head.transition is not None:
                                if head.transition.canceled:
                                    head.transition = None
                                elif head.transition.any_derailed:
                                    return
                            if result or head.is_finishing:
                                head.transition = None
                                if head.is_finishing:
                                    self.on_interaction_canceled(head)
                                else:
                                    self.remove_for_perform(head)
                            yield self.sim.si_state.process_gen(timeline)
            yield self.sim.si_state.process_gen(timeline)
            if not head.is_super:
                if head.pipeline_progress == PipelineProgress.QUEUED:
                    log_interaction('Preparing', head)
                    try:
                        result = yield head.prepare_gen(timeline)
                    except:
                        logger.exception('Error in prepare_gen for mixer interaction')
                        result = False
                    if result != InteractionQueuePreparationStatus.FAILURE:
                        head.pipeline_progress = PipelineProgress.PREPARED
                        return
                    else:
                        head.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='Failed to Prepare Interaction.')
                        continue
                        if head.prepared:
                            head.pre_process_interaction()
                            try:
                                yield self._process_one_interaction_gen(timeline, head)
                            finally:
                                self.remove_for_perform(head)
                            head.post_process_interaction()
                            continue
                            if head.pipeline_progress == PipelineProgress.QUEUED:
                                head.pipeline_progress = PipelineProgress.PRE_TRANSITIONING
                                if not head.run_pre_transition_behavior():
                                    log_interaction('PreTransition', head, msg='Failed')
                                    head.cancel(FinishingType.TRANSITION_FAILURE, cancel_reason_msg='Pre Transition Behavior Failed.')
                                    continue
                                log_interaction('PreTransition', head, msg='Succeeded')
                            if head.pipeline_progress == PipelineProgress.PRE_TRANSITIONING:
                                log_interaction('Preparing', head)
                                try:
                                    result = yield head.prepare_gen(timeline, cancel_incompatible_carry_interactions=True)
                                except scheduling.HardStopError:
                                    raise
                                except Exception:
                                    logger.exception('Exception in prepare_gen for super interaction.')
                                    result = InteractionQueuePreparationStatus.FAILURE
                                if result == InteractionQueuePreparationStatus.NEEDS_DERAIL:
                                    (idle_element, _) = head.sim.get_idle_element(duration=1)
                                    yield element_utils.run_child(timeline, idle_element)
                                    return
                                if result == InteractionQueuePreparationStatus.FAILURE:
                                    head.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='Failed to Prepare Interaction.')
                                else:
                                    head.pipeline_progress = PipelineProgress.PREPARED
                                    continue
                                    if head.prepared:
                                        required_sims = head.required_sims(for_threading=True)
                                        if head.transition is None:
                                            head.transition = TransitionSequenceController(head)
                                        for required_sim in required_sims:
                                            required_sim.queue.transition_controller = head.transition
                                        if services.game_clock_service().clock_speed() == ClockSpeedMode.PAUSED and not services.current_zone().force_process_transitions:
                                            sleep_paused_element = element_utils.build_element((element_utils.sleep_until_next_tick_element(), elements.SoftSleepElement(clock.interval_in_sim_seconds(1.0))))
                                            yield element_utils.run_child(timeline, sleep_paused_element)
                                        with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self.sim, 'InteractionQueue', 'Run Transition', head):
                                            head.sim.ui_manager.running_transition(head)
                                            result = yield head.transition.run_transitions(timeline)
                                        for required_sim in required_sims:
                                            required_sim.queue.transition_controller = None
                                        if head.transition is not None:
                                            if head.transition.canceled:
                                                head.transition = None
                                            elif head.transition.any_derailed:
                                                return
                                        if result or head.is_finishing:
                                            head.transition = None
                                            if head.is_finishing:
                                                self.on_interaction_canceled(head)
                                            else:
                                                self.remove_for_perform(head)
                                        yield self.sim.si_state.process_gen(timeline)
                            if head.prepared:
                                required_sims = head.required_sims(for_threading=True)
                                if head.transition is None:
                                    head.transition = TransitionSequenceController(head)
                                for required_sim in required_sims:
                                    required_sim.queue.transition_controller = head.transition
                                if services.game_clock_service().clock_speed() == ClockSpeedMode.PAUSED and not services.current_zone().force_process_transitions:
                                    sleep_paused_element = element_utils.build_element((element_utils.sleep_until_next_tick_element(), elements.SoftSleepElement(clock.interval_in_sim_seconds(1.0))))
                                    yield element_utils.run_child(timeline, sleep_paused_element)
                                with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self.sim, 'InteractionQueue', 'Run Transition', head):
                                    head.sim.ui_manager.running_transition(head)
                                    result = yield head.transition.run_transitions(timeline)
                                for required_sim in required_sims:
                                    required_sim.queue.transition_controller = None
                                if head.transition is not None:
                                    if head.transition.canceled:
                                        head.transition = None
                                    elif head.transition.any_derailed:
                                        return
                                if result or head.is_finishing:
                                    head.transition = None
                                    if head.is_finishing:
                                        self.on_interaction_canceled(head)
                                    else:
                                        self.remove_for_perform(head)
                                yield self.sim.si_state.process_gen(timeline)
                if head.prepared:
                    head.pre_process_interaction()
                    try:
                        yield self._process_one_interaction_gen(timeline, head)
                    finally:
                        self.remove_for_perform(head)
                    head.post_process_interaction()
                    continue
                    if head.pipeline_progress == PipelineProgress.QUEUED:
                        head.pipeline_progress = PipelineProgress.PRE_TRANSITIONING
                        if not head.run_pre_transition_behavior():
                            log_interaction('PreTransition', head, msg='Failed')
                            head.cancel(FinishingType.TRANSITION_FAILURE, cancel_reason_msg='Pre Transition Behavior Failed.')
                            continue
                        log_interaction('PreTransition', head, msg='Succeeded')
                    if head.pipeline_progress == PipelineProgress.PRE_TRANSITIONING:
                        log_interaction('Preparing', head)
                        try:
                            result = yield head.prepare_gen(timeline, cancel_incompatible_carry_interactions=True)
                        except scheduling.HardStopError:
                            raise
                        except Exception:
                            logger.exception('Exception in prepare_gen for super interaction.')
                            result = InteractionQueuePreparationStatus.FAILURE
                        if result == InteractionQueuePreparationStatus.NEEDS_DERAIL:
                            (idle_element, _) = head.sim.get_idle_element(duration=1)
                            yield element_utils.run_child(timeline, idle_element)
                            return
                        if result == InteractionQueuePreparationStatus.FAILURE:
                            head.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='Failed to Prepare Interaction.')
                        else:
                            head.pipeline_progress = PipelineProgress.PREPARED
                            continue
                            if head.prepared:
                                required_sims = head.required_sims(for_threading=True)
                                if head.transition is None:
                                    head.transition = TransitionSequenceController(head)
                                for required_sim in required_sims:
                                    required_sim.queue.transition_controller = head.transition
                                if services.game_clock_service().clock_speed() == ClockSpeedMode.PAUSED and not services.current_zone().force_process_transitions:
                                    sleep_paused_element = element_utils.build_element((element_utils.sleep_until_next_tick_element(), elements.SoftSleepElement(clock.interval_in_sim_seconds(1.0))))
                                    yield element_utils.run_child(timeline, sleep_paused_element)
                                with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self.sim, 'InteractionQueue', 'Run Transition', head):
                                    head.sim.ui_manager.running_transition(head)
                                    result = yield head.transition.run_transitions(timeline)
                                for required_sim in required_sims:
                                    required_sim.queue.transition_controller = None
                                if head.transition is not None:
                                    if head.transition.canceled:
                                        head.transition = None
                                    elif head.transition.any_derailed:
                                        return
                                if result or head.is_finishing:
                                    head.transition = None
                                    if head.is_finishing:
                                        self.on_interaction_canceled(head)
                                    else:
                                        self.remove_for_perform(head)
                                yield self.sim.si_state.process_gen(timeline)
                    if head.prepared:
                        required_sims = head.required_sims(for_threading=True)
                        if head.transition is None:
                            head.transition = TransitionSequenceController(head)
                        for required_sim in required_sims:
                            required_sim.queue.transition_controller = head.transition
                        if services.game_clock_service().clock_speed() == ClockSpeedMode.PAUSED and not services.current_zone().force_process_transitions:
                            sleep_paused_element = element_utils.build_element((element_utils.sleep_until_next_tick_element(), elements.SoftSleepElement(clock.interval_in_sim_seconds(1.0))))
                            yield element_utils.run_child(timeline, sleep_paused_element)
                        with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self.sim, 'InteractionQueue', 'Run Transition', head):
                            head.sim.ui_manager.running_transition(head)
                            result = yield head.transition.run_transitions(timeline)
                        for required_sim in required_sims:
                            required_sim.queue.transition_controller = None
                        if head.transition is not None:
                            if head.transition.canceled:
                                head.transition = None
                            elif head.transition.any_derailed:
                                return
                        if result or head.is_finishing:
                            head.transition = None
                            if head.is_finishing:
                                self.on_interaction_canceled(head)
                            else:
                                self.remove_for_perform(head)
                        yield self.sim.si_state.process_gen(timeline)
            else:
                if head.pipeline_progress == PipelineProgress.QUEUED:
                    head.pipeline_progress = PipelineProgress.PRE_TRANSITIONING
                    if not head.run_pre_transition_behavior():
                        log_interaction('PreTransition', head, msg='Failed')
                        head.cancel(FinishingType.TRANSITION_FAILURE, cancel_reason_msg='Pre Transition Behavior Failed.')
                        continue
                    log_interaction('PreTransition', head, msg='Succeeded')
                if head.pipeline_progress == PipelineProgress.PRE_TRANSITIONING:
                    log_interaction('Preparing', head)
                    try:
                        result = yield head.prepare_gen(timeline, cancel_incompatible_carry_interactions=True)
                    except scheduling.HardStopError:
                        raise
                    except Exception:
                        logger.exception('Exception in prepare_gen for super interaction.')
                        result = InteractionQueuePreparationStatus.FAILURE
                    if result == InteractionQueuePreparationStatus.NEEDS_DERAIL:
                        (idle_element, _) = head.sim.get_idle_element(duration=1)
                        yield element_utils.run_child(timeline, idle_element)
                        return
                    if result == InteractionQueuePreparationStatus.FAILURE:
                        head.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='Failed to Prepare Interaction.')
                    else:
                        head.pipeline_progress = PipelineProgress.PREPARED
                        continue
                        if head.prepared:
                            required_sims = head.required_sims(for_threading=True)
                            if head.transition is None:
                                head.transition = TransitionSequenceController(head)
                            for required_sim in required_sims:
                                required_sim.queue.transition_controller = head.transition
                            if services.game_clock_service().clock_speed() == ClockSpeedMode.PAUSED and not services.current_zone().force_process_transitions:
                                sleep_paused_element = element_utils.build_element((element_utils.sleep_until_next_tick_element(), elements.SoftSleepElement(clock.interval_in_sim_seconds(1.0))))
                                yield element_utils.run_child(timeline, sleep_paused_element)
                            with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self.sim, 'InteractionQueue', 'Run Transition', head):
                                head.sim.ui_manager.running_transition(head)
                                result = yield head.transition.run_transitions(timeline)
                            for required_sim in required_sims:
                                required_sim.queue.transition_controller = None
                            if head.transition is not None:
                                if head.transition.canceled:
                                    head.transition = None
                                elif head.transition.any_derailed:
                                    return
                            if result or head.is_finishing:
                                head.transition = None
                                if head.is_finishing:
                                    self.on_interaction_canceled(head)
                                else:
                                    self.remove_for_perform(head)
                            yield self.sim.si_state.process_gen(timeline)
                if head.prepared:
                    required_sims = head.required_sims(for_threading=True)
                    if head.transition is None:
                        head.transition = TransitionSequenceController(head)
                    for required_sim in required_sims:
                        required_sim.queue.transition_controller = head.transition
                    if services.game_clock_service().clock_speed() == ClockSpeedMode.PAUSED and not services.current_zone().force_process_transitions:
                        sleep_paused_element = element_utils.build_element((element_utils.sleep_until_next_tick_element(), elements.SoftSleepElement(clock.interval_in_sim_seconds(1.0))))
                        yield element_utils.run_child(timeline, sleep_paused_element)
                    with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self.sim, 'InteractionQueue', 'Run Transition', head):
                        head.sim.ui_manager.running_transition(head)
                        result = yield head.transition.run_transitions(timeline)
                    for required_sim in required_sims:
                        required_sim.queue.transition_controller = None
                    if head.transition is not None:
                        if head.transition.canceled:
                            head.transition = None
                        elif head.transition.any_derailed:
                            return
                    if result or head.is_finishing:
                        head.transition = None
                        if head.is_finishing:
                            self.on_interaction_canceled(head)
                        else:
                            self.remove_for_perform(head)
                    yield self.sim.si_state.process_gen(timeline)
        yield self.sim.si_state.process_gen(timeline)

    def insert_route_failure_interaction(self, interaction, interaction_name, interaction_icon_info):
        resolver = InteractionResolver(interaction.aop.affordance, interaction)
        anim_overrides = None
        for test_and_override in InteractionFailureOptions.FAILURE_REASON_TESTS:
            result = test_and_override.test_set.run_tests(resolver)
            while result:
                anim_overrides = test_and_override.anim_override
                break
        context = InteractionContext(interaction.sim, InteractionContext.SOURCE_SCRIPT, Priority.High, insert_strategy=QueueInsertStrategy.NEXT)
        result = self.sim.push_super_affordance(InteractionFailureOptions.ROUTE_FAILURE_AFFORDANCE, interaction.target, context, anim_overrides=anim_overrides, interaction_name=interaction_name, interaction_icon_info=interaction_icon_info)

    def needs_cancel_aop(self, aop, context):
        bucket = self._get_bucket_for_context(context)
        for cancel_si in bucket:
            while context.group_id == cancel_si.group_id:
                return False
        if self.sim.si_state.is_running_affordance(aop.affordance, target=aop.target):
            return False
        return True

    @property
    def transition_in_progress(self):
        return self.transition_controller is not None and not self.transition_controller.canceled

    @property
    def running(self):
        if self.transition_controller is not None:
            return self.transition_controller.interaction
        return self._running

    @running.setter
    def running(self, value):
        self._running = value
        if value is not None and (value.is_super and self._must_run_next_interaction is not None) and value is not self._must_run_next_interaction:
            self._must_run_next_interaction.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='Interaction is not the must_run_next interaction')

    def visible_len(self):
        return sum(1 for interaction in self if interaction.visible_as_interaction and self.running != interaction)

    def can_queue_visible_interaction(self):
        return self.visible_len() < self.sim.max_interactions

    @property
    def _head_change_watcher(self):
        return EdgeWatcher(self.get_head, lambda _, __: self._on_head_changed(), test_func_exit=self._get_head)

    def remove_for_perform(self, interaction):
        with self._head_change_watcher:
            for bucket in self._buckets:
                while bucket.remove_for_perform(interaction):
                    if interaction is self._must_run_next_interaction:
                        self._must_run_next_interaction = None
                    return interaction

    def clear_must_run_next_interaction(self, interaction):
        if interaction is self._must_run_next_interaction:
            self._must_run_next_interaction = None

    def _set_si_state_on_changed_callbacks_for_head(self, sims):
        for sim in self._si_state_changed_callback_sims:
            while sim not in sims:
                sim.si_state.on_changed.remove(self.on_si_phase_change)
        self._si_state_changed_callback_sims.intersection_update(sims)
        for sim in sims:
            if sim in self._si_state_changed_callback_sims:
                pass
            sim.si_state.on_changed.append(self.on_si_phase_change)
            self._si_state_changed_callback_sims.add(sim)

    def clear_head_cache(self):
        self._head_cache = UNSET
        self._set_si_state_on_changed_callbacks_for_head(set())

    def peek_head(self):
        if self._head_cache is UNSET:
            return
        return self._head_cache

    def get_head(self):
        if self._head_cache is UNSET:
            return self._get_head()
        return self._head_cache

    def _get_head(self):
        self.clear_head_cache()
        self._head_cache = None
        si_earlier_in_queue = False
        next_unblocked_interaction = None
        for bucket in self._buckets:
            interaction = bucket.peek()
            while not interaction is None:
                if interaction.is_finishing:
                    pass
                if not interaction.is_super or interaction.is_cancel_aop:
                    next_unblocked_interaction = interaction
                    interaction.notify_queue_head()
                    break
                if si_earlier_in_queue:
                    pass
                si_earlier_in_queue = True
                interaction.notify_queue_head()
                sims_with_invalid_paths = interaction.get_sims_with_invalid_paths()
                if sims_with_invalid_paths:
                    self._set_si_state_on_changed_callbacks_for_head(sims_with_invalid_paths)
                    interaction.on_incompatible_in_queue()
                next_unblocked_interaction = interaction
                break
        if self._head_cache is not None and self._head_cache is not UNSET:
            return self._head_cache
        if next_unblocked_interaction is not None:
            required_sims = WeakSet(next_unblocked_interaction.required_sims())

            def clear_and_remove(si, self_ref=weakref.ref(self)):
                for sim in required_sims:
                    while sim.si_state is not None:
                        sim.si_state.on_changed.remove(clear_and_remove)
                self = self_ref()
                if self is not None:
                    self.clear_head_cache()

            for sim in required_sims:
                while sim.si_state is not None:
                    sim.si_state.on_changed.append(clear_and_remove)
            for sim in required_sims:
                while sim.si_state is None:
                    if not self._dumped_gsi_in_get_head:
                        self._dumped_gsi_in_get_head = True
                        force_gsi_dump_on_error_or_exception()
                    raise RuntimeError('Deleted sim:{} found in required sims of interaction:{} {} {}'.format(sim, next_unblocked_interaction, next_unblocked_interaction._pipeline_progress, next_unblocked_interaction._required_sims))
        self._head_cache = next_unblocked_interaction
        return next_unblocked_interaction

    def _resolve_priority_pressure(self):
        highest_priority_interaction = None
        for interaction in reversed(list(self)):
            allow_clobbering = interaction.interruptible
            super_priority = interaction.super_interaction.priority if interaction.super_interaction is not None else Priority.Low
            interaction_priority = interaction.priority
            max_priority = max(super_priority, interaction_priority)
            if highest_priority_interaction is not None and not interaction.is_related_to(highest_priority_interaction) and can_priority_displace(highest_priority_interaction.priority, max_priority, allow_clobbering=allow_clobbering):
                while not interaction.source is InteractionSource.CARRY_CANCEL_AOP:
                    if interaction.source is InteractionSource.BODY_CANCEL_AOP:
                        pass
                    interaction.displace(highest_priority_interaction, cancel_reason_msg='Interaction Queue displaced from resolving priority pressure.')
                    while highest_priority_interaction is None or interaction.priority > highest_priority_interaction.priority:
                        highest_priority_interaction = interaction
            while highest_priority_interaction is None or interaction.priority > highest_priority_interaction.priority:
                highest_priority_interaction = interaction

    def _resolve_collapsible_interaction(self):
        if len(self._super_interactions) <= 1:
            return
        for (si_a, si_b) in zip(self._super_interactions, list(self._super_interactions)[1:]):
            while not not si_a.visible:
                if not si_b.visible:
                    pass
                while not si_a.is_finishing:
                    if si_b.is_finishing:
                        pass
                    while si_a.is_super and (si_a.collapsible and si_b.is_super) and si_b.collapsible:
                        si_a.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='Interaction Queue canceled because interaction is collapsible.')
                        break

    def _can_sis_pass_combinable_compatability_tests(self, first_si, second_si):
        if first_si.collapsible:
            return False
        if not self.sim.si_state.are_sis_compatible(first_si, second_si):
            return False
        return True

    def _attempt_combination(self, combined_sis, si_to_evaluate, combination_constraint):
        if not si_to_evaluate.visible or not si_to_evaluate.allowed_to_combine:
            return Nowhere()
        for combined_si in combined_sis:
            if si_to_evaluate.continuation_id is not None and si_to_evaluate.continuation_id == combined_si.continuation_id:
                return Nowhere()
            while not self._can_sis_pass_combinable_compatability_tests(combined_si, si_to_evaluate):
                return Nowhere()
        si_to_evaluate_constraint = si_to_evaluate.constraint_intersection(sim=self.sim, posture_state=None)
        if not si_to_evaluate_constraint.valid:
            return Nowhere()
        test_constraint = si_to_evaluate_constraint.intersect(combination_constraint)
        return test_constraint

    def _combine_compatible_interactions(self):
        head_interaction = self.get_head()
        if head_interaction is None or (head_interaction.is_putdown or (not head_interaction.visible or not head_interaction.is_super)) or not head_interaction.allowed_to_combine:
            return
        original_head_combinables = WeakSet(head_interaction.combinable_interactions)
        head_interaction.combinable_interactions.clear()
        head_constraint = head_interaction.constraint_intersection(sim=self.sim, posture_state=None)
        if not head_constraint.valid:
            return
        combined_included_sis = WeakSet((head_interaction,))
        if head_interaction.transition is not None:
            final_included_sis = head_interaction.transition.get_final_included_sis_for_sim(self.sim)
            if final_included_sis is not None:
                while True:
                    for final_si in final_included_sis:
                        final_si_constraint = final_si.constraint_intersection(sim=self.sim, posture_state=None)
                        if not final_si_constraint.valid:
                            return
                        head_constraint = self._attempt_combination(combined_included_sis, final_si, head_constraint)
                        if not head_constraint.valid:
                            return
                        combined_included_sis.add(final_si)
        combined_carry_targets = set()
        head_carryable = head_interaction.targeted_carryable
        if head_carryable is not None:
            combined_carry_targets.add(head_carryable)
        combined_interactions = WeakSet((head_interaction,))
        combined_constraint = head_constraint
        for queued_interaction in self._super_interactions:
            while not queued_interaction is head_interaction:
                if not queued_interaction.is_super:
                    pass
                if queued_interaction.is_putdown:
                    break
                queued_interaction.combinable_interactions.clear()
                test_intersection = self._attempt_combination(combined_interactions, queued_interaction, combined_constraint)
                if not test_intersection.valid:
                    break
                combined_constraint = test_intersection
                combined_interactions.add(queued_interaction)
                queued_carryable = queued_interaction.targeted_carryable
                while queued_carryable is not None:
                    combined_carry_targets.add(queued_carryable)
                    if len(combined_carry_targets) > 1:
                        break
        if len(combined_interactions) == 1:
            return
        for interaction in combined_interactions:
            interaction.combinable_interactions = combined_interactions
        if original_head_combinables != combined_interactions and head_interaction.transition is not None:
            if len(combined_carry_targets) > 1:
                posture_graph_service = services.current_zone().posture_graph_service
                posture_graph_service.clear_goal_costs()
            head_interaction.transition.derail(DerailReason.PROCESS_QUEUE, self.sim)

    def _get_bucket_for_context(self, context):
        bucket_type = context.bucket_type
        if bucket_type == InteractionBucketType.BASED_ON_SOURCE:
            source = context.source
            if source == InteractionContext.SOURCE_AUTONOMY:
                bucket_type = InteractionBucketType.AUTONOMY
            elif source == InteractionContext.SOURCE_SOCIAL_ADJUSTMENT:
                bucket_type = InteractionBucketType.SOCIAL_ADJUSTMENT
            elif source == InteractionContext.SOURCE_BODY_CANCEL_AOP:
                bucket_type = InteractionBucketType.BODY_CANCEL_REPLACEMENT
            elif source == InteractionContext.SOURCE_CARRY_CANCEL_AOP:
                bucket_type = InteractionBucketType.CARRY_CANCEL_REPLACEMENT
            else:
                bucket_type = InteractionBucketType.DEFAULT
        if bucket_type == InteractionBucketType.AUTONOMY:
            bucket = self._autonomy
        elif bucket_type == InteractionBucketType.SOCIAL_ADJUSTMENT:
            bucket = self._social_adjustment
        elif bucket_type == InteractionBucketType.BODY_CANCEL_REPLACEMENT:
            bucket = self._body_cancel_replacements
        elif bucket_type == InteractionBucketType.CARRY_CANCEL_REPLACEMENT:
            bucket = self._carry_cancel_replacements
        elif bucket_type == InteractionBucketType.DEFAULT:
            bucket = self._super_interactions
        else:
            raise ValueError('Unrecognized bucket_type: {}'.format(bucket_type))
        return bucket

    def _get_bucket_for_interaction(self, interaction):
        if interaction.context.bucket_type not in InteractionBucketType.values:
            logger.error('Invalid interaction bucket in context for {}', interaction, owner='rez')
        bucket = self._get_bucket_for_context(interaction.context)
        return bucket

    def append(self, interaction):
        if self.locked:
            return TestResult(False, 'Interaction queue is locked.')
        if interaction.is_finishing:
            return TestResult(False, 'Interaction is already finishing.')
        target_queue = self._get_bucket_for_interaction(interaction)
        with self._head_change_watcher:
            if interaction.context.insert_strategy == QueueInsertStrategy.NEXT or interaction.context.insert_strategy == QueueInsertStrategy.FIRST:
                if interaction.context.insert_strategy != QueueInsertStrategy.FIRST:
                    insert_after_interaction = self.running
                else:
                    insert_after_interaction = None
                success = target_queue.insert_next(interaction, insert_after=insert_after_interaction)
            else:
                insert_after_interaction = None
                success = target_queue.append(interaction)
            if not success:
                interaction.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='InteractionQueue: failed to append interaction')
                return success
            if interaction.is_user_directed:
                self._on_user_driven_action()
            interaction_id_to_insert_after = insert_after_interaction.id if insert_after_interaction is not None else None
            interaction.on_added_to_queue(interaction_id_to_insert_after=interaction_id_to_insert_after)
            if interaction.context.must_run_next:
                if self._must_run_next_interaction is not None:
                    self._must_run_next_interaction.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='must_run_next inserted again: {} canceled by {}'.format(self._must_run_next_interaction, interaction))
                    self._must_run_next_interaction = None
                self._must_run_next_interaction = interaction
            self._resolve_priority_pressure()
            self._resolve_collapsible_interaction()
            self._combine_compatible_interactions()
        if interaction.is_finishing:
            return TestResult(False, 'Interaction finished during append.  Finishing Info: {}'.format(interaction._finisher))
        return TestResult.TRUE

    def _on_user_driven_action(self):
        for interaction in list(self._autonomy):
            interaction.cancel(FinishingType.PRIORITY, cancel_reason_msg='User-directed action takes precedence over autonomous interactions.')
        for interaction in list(self._social_adjustment):
            interaction.cancel(FinishingType.PRIORITY, cancel_reason_msg='User-directed action takes precedence over social adjustment interactions.')

    def find_sub_interaction(self, super_id, aop_id):
        for interaction in self:
            while interaction.super_interaction.id == super_id and interaction.aop.aop_id == aop_id:
                return interaction

    def find_continuation_by_id(self, source_id):
        for interaction in self:
            while interaction.is_continuation_by_id(source_id):
                return interaction

    def find_pushed_interaction_by_id(self, group_id):
        for interaction in self:
            while interaction.group_id == group_id:
                return interaction

    def find_interaction_by_id(self, id_to_find):
        for interaction in self:
            while interaction.id == id_to_find:
                return interaction
        if self.transition_controller is not None and self.transition_controller.interaction.id == id_to_find:
            return self.transition_controller.interaction

    def has_adjustment_interaction(self):
        return len(self._social_adjustment) > 0

    def cancel_running(self):
        running = self.running
        if running is not None:
            running.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='InteractionQueue: running interaction canceled')

    def cancel_all(self):
        self.clear_head_cache()
        interactions = list(self)
        for interaction in interactions:
            interaction.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='InteractionQueue: all interactions canceled')

    def on_reset(self):
        if self.transition_controller is not None:
            self.transition_controller.on_reset()
            self.transition_controller.interaction.on_reset()
            self.transition_controller = None
        if self._running is not None:
            self._running.on_reset()
            self._running = None
        self.clear_head_cache()
        for bucket in self._buckets:
            try:
                bucket.on_reset()
            except Exception:
                logger.error('Exception caught while reseting interaction bucket. ListBucket.reset is not allowed to throw an exception and must always clear the bucket:')
                raise

    def on_interaction_canceled(self, interaction):
        self.clear_must_run_next_interaction(interaction)
        if self.running is interaction:
            return
        if interaction.is_super:
            si_order_changed = True
        else:
            si_order_changed = False
        log_interaction('Dequeue_Clear', interaction)
        with self._head_change_watcher:
            for bucket in self._buckets:
                while interaction in bucket:
                    if bucket.clear_interaction(interaction):
                        break
        if self.running is not None and self.running.interruptible:
            self.running.cancel(FinishingType.INTERACTION_QUEUE, cancel_reason_msg='Interaction Queue cancel running interaction to expedite SI cancel.')
        if si_order_changed:
            self._combine_compatible_interactions()
            self._resolve_collapsible_interaction()

    @property
    def locked(self):
        return self._locked

    def lock(self):
        self._locked = True

    def unlock(self):
        self._locked = False

    def on_si_phase_change(self, si):
        for interaction in self:
            if not interaction.is_super:
                pass
            interaction.on_other_si_phase_change(si)
        with self._head_change_watcher:
            self._apply_next_pressure()

    def on_element_priority_changed(self, interaction):
        with self._head_change_watcher:
            self._apply_next_pressure()

    def _on_head_changed(self):
        if services.current_zone().is_zone_shutting_down:
            return
        with self._head_change_watcher:
            self._apply_next_pressure()
        self.on_head_changed()
        self._combine_compatible_interactions()

    @staticmethod
    def _should_head_dispace_running(sim, next_interaction, running_interaction):
        if running_interaction.disable_displace(next_interaction):
            return False
        if not running_interaction.is_super and not running_interaction.interruptible:
            return False
        if next_interaction.super_interaction is running_interaction:
            return False
        cancel_aop_liability = next_interaction.get_liability(CANCEL_AOP_LIABILITY)
        if cancel_aop_liability is not None and cancel_aop_liability.interaction_to_cancel is running_interaction:
            return True
        if next_interaction.is_cancel_aop and not running_interaction.disable_transitions:
            allow_clobbering = True
        else:
            allow_clobbering = running_interaction.interruptible
        if running_interaction.is_super and running_interaction.is_guaranteed() and not can_priority_displace(next_interaction.priority, running_interaction.priority, allow_clobbering=allow_clobbering):
            return False
        if next_interaction.is_related_to(running_interaction):
            return False
        if running_interaction.is_super and next_interaction.is_super and sim.si_state.are_sis_compatible(running_interaction, next_interaction):
            return False
        return True

    def _apply_next_pressure(self):
        next_interaction = self.get_head()
        if next_interaction is None:
            return
        for sim in next_interaction.required_sims():
            running_interaction = sim.queue.running
            if next_interaction is running_interaction:
                pass
            while not running_interaction is None:
                if running_interaction.must_run:
                    pass
                if not self._should_head_dispace_running(sim, next_interaction, running_interaction):
                    while running_interaction.transition is not None and (running_interaction.sim is self.sim and not running_interaction.is_adjustment_interaction()) and not next_interaction.is_related_to(running_interaction):
                        running_interaction.transition.derail(DerailReason.PREEMPTED, sim)
                        running_interaction.displace(next_interaction, cancel_reason_msg='InteractionQueue: pressure to cancel running interaction from {}'.format(next_interaction))
                running_interaction.displace(next_interaction, cancel_reason_msg='InteractionQueue: pressure to cancel running interaction from {}'.format(next_interaction))

    def on_required_sims_changed(self, interaction):
        self.clear_head_cache()
        if self.get_head() is interaction:
            self._on_head_changed()

    def cancel_aop_exists_for_si(self, si):
        for interaction in self:
            cancel_liability = interaction.get_liability(CANCEL_AOP_LIABILITY)
            while cancel_liability is not None and si is cancel_liability.interaction_to_cancel:
                return True
        return False

    def queued_super_interactions_gen(self):
        for si in self._super_interactions:
            yield si

    def has_duplicate_super_affordance(self, super_affordance, actor, target):
        for si in self._super_interactions:
            while si.affordance is super_affordance and si.target is target and si.context.sim is actor:
                return True
        return False

