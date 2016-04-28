from sims4.tuning.tunable import TunableList, TunableTuple
from situations.situation import Situation
from situations.tunable import TunableSituationPhase, TunableSituationCondition
import alarms
import clock
import interactions.utils.exit_condition_manager
import services
import sims4.log
logger = sims4.log.Logger('Situations')

class SituationSimple(Situation):
    __qualname__ = 'SituationSimple'
    INSTANCE_TUNABLES = {'_phases': TunableList(tunable=TunableSituationPhase(description='\n                    Situation reference.\n                    ')), '_exit_conditions': TunableList(description='\n                A list of condition groups of which if any are satisfied, the group is satisfied.\n                ', tunable=TunableTuple(conditions=TunableList(description='\n                        A list of conditions that all must be satisfied for the\n                        group to be considered satisfied.\n                        ', tunable=TunableSituationCondition(description='\n                            A condition for a situation or single phase.\n                            '))))}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._phase = None
        self._phase_index = -1
        self._exit_condition_manager = interactions.utils.exit_condition_manager.ConditionalActionManager()
        self._phase_exit_condition_manager = interactions.utils.exit_condition_manager.ConditionalActionManager()
        self._phase_duration_alarm_handle = None

    def _destroy(self):
        self._remove_exit_conditions()
        self._remove_phase_exit_conditions()
        super()._destroy()

    def _initialize_situation_jobs(self):
        initial_phase = self.get_initial_phase_type()
        for job_tuning in initial_phase.jobs_gen():
            self._add_job_type(job_tuning[0], job_tuning[1])

    def start_situation(self):
        super().start_situation()
        self._attach_exit_conditions()
        self._transition_to_next_phase()

    def _load_situation_states_and_phases(self):
        super()._load_situation_states_and_phases()
        self._attach_exit_conditions()
        self._load_phase()

    def _save_custom(self, seed):
        super()._save_custom(seed)
        remaining_time = 0 if self._phase_duration_alarm_handle is None else self._phase_duration_alarm_handle.get_remaining_time().in_minutes()
        seed.add_situation_simple_data(self._phase_index, remaining_time)
        return seed

    @classmethod
    def _verify_tuning_callback(cls):
        super()._verify_tuning_callback()
        if len(cls._phases) == 0:
            logger.error('Simple Situation {} has no tuned phases.', cls, owner='sscholl')
        if cls._phases[len(cls._phases) - 1].get_duration() != 0:
            logger.error('Situation {} last phase does not have a duration of 0.', cls, owner='sscholl')

    @classmethod
    def get_tuned_jobs(cls):
        job_list = []
        initial_phase = cls.get_initial_phase_type()
        for job in initial_phase.jobs_gen():
            job_list.append(job[0])
        return job_list

    @classmethod
    def get_initial_phase_type(cls):
        return cls._phases[0]

    @classmethod
    def get_phase(cls, index):
        if cls._phases == None or index >= len(cls._phases):
            return
        return cls._phases[index]

    def _transition_to_next_phase(self, conditional_action=None):
        new_index = self._phase_index + 1
        new_phase = self.get_phase(new_index)
        logger.debug('Transitioning from phase {} to phase {}', self._phase_index, new_index)
        self._remove_phase_exit_conditions()
        self._phase_index = new_index
        self._phase = new_phase
        self._attach_phase_exit_conditions()
        for (job_type, role_state_type) in new_phase.jobs_gen():
            self._set_job_role_state(job_type, role_state_type)
        client = services.client_manager().get_first_client()
        if client:
            output = sims4.commands.AutomationOutput(client.id)
            if output:
                output('SituationPhaseTransition; Phase:{}'.format(new_index))

    def _load_phase(self):
        seedling = self._seed.situation_simple_seedling
        logger.debug('Loading phase {}', seedling.phase_index)
        self._phase_index = seedling.phase_index
        self._phase = self.get_phase(self._phase_index)
        self._attach_phase_exit_conditions(seedling.remaining_phase_time)

    def get_phase_state_name_for_gsi(self):
        return str(self._phase_index)

    def _attach_phase_exit_conditions(self, duration_override=None):
        self._phase_exit_condition_manager.attach_conditions(self, self._phase.exit_conditions_gen(), self._transition_to_next_phase)
        duration = duration_override if duration_override is not None else self._phase.get_duration()
        if duration != 0:
            self._phase_duration_alarm_handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(duration), self._transition_to_next_phase)

    def _remove_phase_exit_conditions(self):
        self._phase_exit_condition_manager.detach_conditions(self)
        if self._phase_duration_alarm_handle is not None:
            alarms.cancel_alarm(self._phase_duration_alarm_handle)
            self._phase_duration_alarm_handle = None

    def _attach_exit_conditions(self):
        self._remove_exit_conditions()
        self._exit_condition_manager.attach_conditions(self, self.exit_conditions_gen(), self._situation_ended_callback)

    def _remove_exit_conditions(self):
        self._exit_condition_manager.detach_conditions(self)

    def exit_conditions_gen(self):
        for ec in self._exit_conditions:
            yield ec

    def _situation_ended_callback(self, conditional_action=None):
        logger.debug('Situation exit condition met: {}', self)
        self._self_destruct()

