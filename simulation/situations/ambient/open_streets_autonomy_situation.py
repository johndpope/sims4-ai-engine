from role.role_state import RoleState
from sims4.tuning.tunable import TunableSet, TunableEnumWithFilter
from sims4.utils import classproperty
from situations.situation_complex import SituationState
from situations.situation_job import SituationJob
from tag import Tag
import alarms
import clock
import services
import sims4.tuning.tunable
import situations.bouncer
import situations.situation_complex
logger = sims4.log.Logger('Walkby')
DO_STUFF_TIMEOUT = 'do_stuff_timeout'

class OpenStreetsAutonomySituation(situations.situation_complex.SituationComplexCommon):
    __qualname__ = 'OpenStreetsAutonomySituation'
    INSTANCE_TUNABLES = {'role': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                  The situation job for the sim.\n                  '), do_stuff_role_state=RoleState.TunableReference(description='\n                  The role state for the sim doing stuff.  This is the initial state.\n                  '), leave_role_state=RoleState.TunableReference(description='\n                  The role state for the sim leaving.\n                  ')), 'do_stuff_timeout': sims4.tuning.tunable.TunableSimMinute(description='\n            The amount of time the sim does stuff before leaving.\n            ', default=180), 'can_start_walkby_limiting_tags': TunableSet(description="\n                Don't start a situation of this type if another situation is\n                already running that has any of these tags in its tags field.\n                \n                For instance, if you only want one Streaker at a time you would\n                create a new tag SITUATION_STREAKER. Then set that in both this\n                field and in the tags field of situation_streaker.\n                ", tunable=TunableEnumWithFilter(tunable_type=Tag, default=Tag.INVALID, filter_prefixes=['situation']))}
    REMOVE_INSTANCE_TUNABLES = situations.situation.Situation.NON_USER_FACING_REMOVE_INSTANCE_TUNABLES

    @staticmethod
    def _states():
        return [(1, _DoStuffState), (2, _LeaveState)]

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.role.situation_job, cls.role.do_stuff_role_state)]

    @classmethod
    def default_job(cls):
        return cls.role.situation_job

    def start_situation(self):
        super().start_situation()
        self._change_state(_DoStuffState())

    @classmethod
    def can_start_walkby(cls, lot_id):
        return not services.get_zone_situation_manager().is_situation_with_tags_running(cls.can_start_walkby_limiting_tags)

    @property
    def _should_cancel_leave_interaction_on_premature_removal(self):
        return True

    @classproperty
    def situation_serialization_option(cls):
        return situations.situation_types.SituationSerializationOption.OPEN_STREETS

sims4.tuning.instances.lock_instance_tunables(OpenStreetsAutonomySituation, exclusivity=situations.bouncer.bouncer_types.BouncerExclusivityCategory.WALKBY, creation_ui_option=situations.situation_types.SituationCreationUIOption.NOT_AVAILABLE, duration=0)

class _DoStuffState(SituationState):
    __qualname__ = '_DoStuffState'

    def __init__(self):
        super().__init__()
        self._timeout_handle = None

    def on_activate(self, reader=None):
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.role.situation_job, self.owner.role.do_stuff_role_state)
        timeout = self.owner.do_stuff_timeout
        if reader is not None:
            timeout = reader.read_float(DO_STUFF_TIMEOUT, timeout)
        self._timeout_handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(timeout), lambda _: self.timer_expired())

    def save_state(self, writer):
        super().save_state(writer)
        if self._timeout_handle is not None:
            writer.write_float(DO_STUFF_TIMEOUT, self._timeout_handle.get_remaining_time().in_minutes())

    def on_deactivate(self):
        if self._timeout_handle is not None:
            alarms.cancel_alarm(self._timeout_handle)
            self._timeout_handle = None
        super().on_deactivate()

    def timer_expired(self):
        self._change_state(_LeaveState())

class _LeaveState(SituationState):
    __qualname__ = '_LeaveState'

    def on_activate(self, reader=None):
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.role.situation_job, self.owner.role.leave_role_state)

