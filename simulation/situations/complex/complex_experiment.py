from interactions import ParticipantType
from role.role_state import RoleState
from situations.situation_complex import SituationComplexCommon, SituationState
from situations.situation_job import SituationJob
import alarms
import clock
import event_testing.tests_with_data
import sims4.tuning.tunable

class SituationComplexExperiment(SituationComplexCommon):
    __qualname__ = 'SituationComplexExperiment'
    INSTANCE_TUNABLES = {'test_job': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='A reference to a SituationJob that can be performed at this Situation.'), friendly_role_state=RoleState.TunableReference(description='A role state the sim assigned to the job will perform'), angry_role_state=RoleState.TunableReference(description='A role state the sim assigned to the job will perform')), '_host_job': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='A reference to a SituationJob that can be performed at this Situation.'), default_role_state=RoleState.TunableReference(description='A role state the sim assigned to the job will perform')), 'mean_test': event_testing.tests_with_data.TunableParticipantRanInteractionTest(locked_args={'participant': ParticipantType.TargetSim, 'interaction_outcome': None, 'running_time': None, 'tooltip': None}, description='Test for a mean interaction that will trigger a state change')}

    @staticmethod
    def _states():
        return [(1, AngrySituationState), (2, FriendlySituationState)]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        reader = self._seed.custom_init_params_reader
        if reader is None:
            self._test_bool = True
        else:
            self._test_bool = reader.read_bool('test_bool', True)

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.test_job.situation_job, cls.test_job.friendly_role_state), (cls._host_job.situation_job, cls._host_job.default_role_state)]

    @classmethod
    def default_job(cls):
        return cls.test_job.situation_job

    @classmethod
    def resident_job(cls):
        return cls._host_job.situation_job

    def _save_custom_situation(self, writer):
        super()._save_custom_situation(writer)
        writer.write_bool('test_bool', False)

    def start_situation(self):
        super().start_situation()
        self._change_state(FriendlySituationState())

class AngrySituationState(SituationState):
    __qualname__ = 'AngrySituationState'

    def on_activate(self, reader):
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.test_job.situation_job, self.owner.test_job.angry_role_state)
        timeout = 10 if reader is None else reader.read_float('timer', 10)
        self._handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(timeout), lambda _: self.timer_expired())

    def save_state(self, writer):
        super().save_state(writer)
        if self._handle is not None:
            writer.write_float('timer', self._handle.get_remaining_time().in_minutes())

    def on_deactivate(self):
        if self._handle is not None:
            alarms.cancel_alarm(self._handle)
        super().on_deactivate()

    def timer_expired(self):
        self._change_state(FriendlySituationState())

class FriendlySituationState(SituationState):
    __qualname__ = 'FriendlySituationState'

    def __init__(self):
        super().__init__()
        self._test_int = 12

    def on_activate(self, reader):
        super().on_activate(reader)
        self._test_event_register(event_testing.test_events.TestEvent.InteractionComplete)
        self.owner._set_job_role_state(self.owner.test_job.situation_job, self.owner.test_job.friendly_role_state)
        if reader is not None:
            self._test_int = reader.read_uint32('test_uint32', 24)

    def save_state(self, writer):
        super().save_state(writer)
        writer.write_uint32('test_uint32', self._test_int)

    def handle_event(self, sim_info, event, resolver):
        if self.owner.test_interaction_complete_by_job_holder(sim_info, resolver, self.owner.test_job.situation_job, self.owner.mean_test):
            self._change_state(AngrySituationState())

