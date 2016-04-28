from role.role_state import RoleState
from sims4.utils import classproperty
from situations.situation_complex import SituationState
from situations.situation_job import SituationJob
from situations.visiting.visiting_situation_common import VisitingNPCSituation
import interactions
import services
import sims4.tuning.instances
import sims4.tuning.tunable
import situations.bouncer
import venues

class InviteOverSituation(VisitingNPCSituation):
    __qualname__ = 'InviteOverSituation'
    INSTANCE_TUNABLES = {'invited_job': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                          A reference to the SituationJob used for the Sim invited over.\n                          '), ring_doorbell_state=RoleState.TunableReference(description='\n                          The state for telling a Sim to try to ring the doorbell followed by inviting themselves in.\n                          ')), 'purpose': sims4.tuning.tunable.TunableEnumEntry(description='\n                The purpose/reason used to create the venue type specific visit situation,\n                after the invited sim attempts to ring the door bell.\n                This should be tuned to Invite In, but since that is a dynamic enum\n                you must do it yourself.\n                ', tunable_type=venues.venue_constants.NPCSummoningPurpose, default=venues.venue_constants.NPCSummoningPurpose.DEFAULT)}

    @staticmethod
    def _states():
        return [(1, _RingDoorBellState)]

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.invited_job.situation_job, cls.invited_job.ring_doorbell_state)]

    @classmethod
    def default_job(cls):
        return cls.invited_job.situation_job

    @classproperty
    def supports_multiple_sims(cls):
        return False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._invited_sim = None

    def start_situation(self):
        super().start_situation()
        self._change_state(_RingDoorBellState())

    def _on_set_sim_job(self, sim, job_type):
        super()._on_set_sim_job(sim, job_type)
        self._invited_sim = sim

    def _on_sim_removed_from_situation_prematurely(self, sim):
        super()._on_sim_removed_from_situation_prematurely(sim)
        self._invited_sim = None

    def _invite_sim_in(self):
        if self._invited_sim is not None:
            services.current_zone().venue_service.venue.summon_npcs((self._invited_sim.sim_info,), self.purpose, self.initiating_sim_info)
        self._self_destruct()

sims4.tuning.instances.lock_instance_tunables(InviteOverSituation, exclusivity=situations.bouncer.bouncer_types.BouncerExclusivityCategory.PRE_VISIT, creation_ui_option=situations.situation_types.SituationCreationUIOption.NOT_AVAILABLE, duration=120, _implies_greeted_status=True)

class _RingDoorBellState(SituationState):
    __qualname__ = '_RingDoorBellState'

    def __init__(self):
        super().__init__()
        self._interaction = None

    def on_activate(self, reader=None):
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.invited_job.situation_job, self.owner.invited_job.ring_doorbell_state)

    def _on_set_sim_role_state(self, *args, **kwargs):
        super()._on_set_sim_role_state(*args, **kwargs)
        success = self._choose_and_run_interaction()
        if not success:
            self.owner._invite_sim_in()

    def on_deactivate(self):
        if self._interaction is not None:
            self._interaction.unregister_on_finishing_callback(self._on_finishing_callback)
            self._interaction = None
        super().on_deactivate()

    def _choose_and_run_interaction(self):
        self._interaction = self.owner._choose_role_interaction(self.owner._invited_sim, run_priority=interactions.priority.Priority.Low)
        if self._interaction is None:
            return False
        self._interaction.route_fail_on_transition_fail = False
        execute_result = interactions.aop.AffordanceObjectPair.execute_interaction(self._interaction)
        if not execute_result:
            return False
        self._interaction.register_on_finishing_callback(self._on_finishing_callback)
        return True

    def _on_finishing_callback(self, interaction):
        if self._interaction is not interaction:
            return
        self.owner._invite_sim_in()

