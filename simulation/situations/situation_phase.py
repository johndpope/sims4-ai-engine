
class SituationPhase:
    __qualname__ = 'SituationPhase'

    def __init__(self, job_list, exit_conditions, duration):
        self._job_list = job_list
        self._exit_conditions = exit_conditions
        self._duration = duration

    def jobs_gen(self):
        for (job, role) in self._job_list.items():
            yield (job, role)

    def exit_conditions_gen(self):
        for ec in self._exit_conditions:
            yield ec

    def get_duration(self):
        return self._duration

