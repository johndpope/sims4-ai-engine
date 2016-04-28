import services
import element_utils
import elements
import enum
import sims4.log
logger = sims4.log.Logger('Stage Controller')

class _StageProgress(enum.Int, export=False):
    __qualname__ = '_StageProgress'
    Init = 0
    FirstStage = 1
    Sleeping = 2
    SecondStage = 3
    Done = 4

class StageControllerElement(elements.ParentElement):
    __qualname__ = 'StageControllerElement'

    def __init__(self, sim):
        super().__init__()
        self._sim = sim
        self._progress = _StageProgress.Init
        self._wakeable_element = None
        self._sleeping_element = None

    @property
    def started(self):
        return self._progress >= _StageProgress.FirstStage

    @property
    def suspended(self):
        return self._progress == _StageProgress.Sleeping

    @property
    def stopped(self):
        return self._progress >= _StageProgress.Done

    @property
    def has_staged(self):
        return self._progress >= _StageProgress.Sleeping

    def _run(self, timeline):
        first_stage = element_utils.build_element(self._do_perform_gen)
        self._progress = _StageProgress.FirstStage
        return timeline.run_child(first_stage)

    def _resume(self, timeline, child_result):
        if self._progress == _StageProgress.FirstStage:
            self._progress = _StageProgress.Done
            self._wake_wakeable()
            return child_result
        if self._progress == _StageProgress.SecondStage:
            self._progress = _StageProgress.Done
            self._wake_wakeable()
            return child_result
        raise RuntimeError('Unexpected progress in {} _resume'.format(self._progress))

    def _teardown(self):
        self._progress = _StageProgress.Done
        self._sim = None
        super()._teardown()

    def _hard_stop(self):
        super()._hard_stop()
        self._progress = _StageProgress.Done

    def _get_behavior(self):
        raise NotImplementedError('Must implement in subclass')

    def _stage(self):
        self._sleeping_element = element_utils.soft_sleep_forever()
        stage_element = element_utils.build_critical_section_with_finally(self._set_suspended, self._sleeping_element, self._end_suspended)
        return element_utils.return_true_wrapper(element_utils.must_run(stage_element))

    def _stage_fail(self):
        stage_element = self._stage()
        return elements.OverrideResultElement(stage_element, False)

    def next_stage(self):
        if self._progress == _StageProgress.Init:
            timeline = services.time_service().sim_timeline
            self._sim.schedule_element(timeline, self)
        if self._progress == _StageProgress.Done:
            raise RuntimeError('StageControllElement is past the point of sleeping')
        if self._wakeable_element is not None:
            raise RuntimeError("Attempting to get an element from next_stage on '{}' before consuming the previous one ({})".format(self, self._progress))
        self._wakeable_element = element_utils.soft_sleep_forever()
        if self._progress != _StageProgress.Sleeping:
            sequence = self._wakeable_element
        else:
            sequence = element_utils.build_element([lambda _: self._wake(), self._wakeable_element])
        sequence = element_utils.return_true_wrapper(element_utils.must_run(sequence))
        return sequence

    def _wake(self):
        if self._sleeping_element is not None:
            sleeping_element = self._sleeping_element
            self._sleeping_element = None
            sleeping_element.trigger_soft_stop()
            return True
        logger.error('Attempting to wake a non-sleeping stage control element, progress {}'.format(self._progress))
        return False

    def _set_suspended(self, timeline):
        if self._progress != _StageProgress.FirstStage:
            raise RuntimeError('Can only _set_suspended from FirstStage, not {}'.format(self._progress))
        self._progress = _StageProgress.Sleeping
        self._wake_wakeable()

    def _end_suspended(self, timeline):
        if self._progress != _StageProgress.Sleeping:
            raise RuntimeError('StageControllerElement _end_suspended expected progress Sleeping, not {}'.format(self._progress))
        self._progress = _StageProgress.SecondStage

    def _wake_wakeable(self):
        if self._wakeable_element is not None:
            wakeable_element = self._wakeable_element
            self._wakeable_element = None
            if wakeable_element.attached_to_timeline:
                wakeable_element.trigger_soft_stop()
            else:
                logger.error('Attempted to wake a wakeable that was not ready')

