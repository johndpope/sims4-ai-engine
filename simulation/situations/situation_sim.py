
class SituationSim:
    __qualname__ = 'SituationSim'

    def __init__(self, sim):
        self._sim = sim
        self._current_job_type = None
        self._current_role_state_type = None
        self._local_score = 0
        self._emotional_buff_name = 'None'
        self.buff_handle = None
        self.outfit_priority_handle = None

    def destroy(self):
        self.set_role_state_type(None)
        self._sim = None

    @property
    def current_job_type(self):
        return self._current_job_type

    @current_job_type.setter
    def current_job_type(self, value):
        self.set_role_state_type(None, None)
        self._current_job_type = value

    def set_role_state_type(self, role_state_type, affordance_target=None):
        if self._current_role_state_type is not None:
            self._sim.remove_role_of_type(self._current_role_state_type)
        self._current_role_state_type = role_state_type
        if self._current_role_state_type is not None:
            self._sim.add_role(self._current_role_state_type, affordance_target)

    @property
    def current_role_state_type(self):
        return self._current_role_state_type

    def get_total_score(self):
        return self._local_score

    def get_int_total_score(self):
        return int(round(self.get_total_score()))

    def update_score(self, delta):
        pass

    def set_emotional_buff_for_gsi(self, emotional_buff):
        if emotional_buff is not None:
            self._emotional_buff_name = emotional_buff.__name__

    @property
    def emotional_buff_name(self):
        return self._emotional_buff_name

