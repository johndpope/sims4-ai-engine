from debugvis import Context
import alarms
import autonomy.settings
import clock
import sims4.math

class AutonomyTimerVisualizer:
    __qualname__ = 'AutonomyTimerVisualizer'

    def __init__(self, sim, layer):
        self._sim = sim.ref()
        self._layer = layer
        self._alarm_handle = None
        self.start()

    @property
    def sim(self):
        if self._sim is not None:
            return self._sim()

    @property
    def layer(self):
        return self._layer

    def start(self):
        self._alarm_handle = alarms.add_alarm_real_time(self, clock.interval_in_real_seconds(1.0), self._process, repeating=True, use_sleep_time=False)

    def stop(self):
        if self._alarm_handle is not None:
            self._alarm_handle.cancel()
            self._alarm_handle = None

    def _process(self, _):
        sim = self.sim
        if sim is None:
            self.stop()
            return
        offset = sims4.math.Vector3.Y_AXIS()*0.4
        BONE_INDEX = 5
        if sim.to_skip_autonomy():
            autonomy_timer_text = 'Skipping'
        elif sim.get_autonomy_state_setting() < autonomy.settings.AutonomyState.FULL:
            autonomy_timer_text = 'Disabled'
        else:
            autonomy_timer_text = str(sim.get_time_until_next_update())
        with Context(self._layer) as context:
            context.add_text_object(self.sim, offset, autonomy_timer_text, bone_index=BONE_INDEX)

