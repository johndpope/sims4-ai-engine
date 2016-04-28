from sims4.tuning.tunable_base import GroupNames
from sims4.utils import classproperty
from situations.bouncer.bouncer_request import RequestSpawningOption
from situations.bouncer.bouncer_types import BouncerRequestPriority
import alarms
import clock
import role.role_state
import sims4.tuning.tunable
import situations.base_situation
import situations.bouncer.bouncer_request
import situations.situation_complex
import situations.situation_guest_list
import situations.situation_job

class LeaveSituation(situations.situation_complex.SituationComplexCommon):
    __qualname__ = 'LeaveSituation'
    INSTANCE_TUNABLES = {'leaving_soon': sims4.tuning.tunable.TunableTuple(situation_job=situations.situation_job.SituationJob.TunableReference(description='\n                                The job given to sims that we want to have leave the lot soon.\n                                '), role_state=role.role_state.RoleState.TunableReference(description='\n                                The role state given to the sim that we want to have leave the lot soon.\n                                '), tuning_group=GroupNames.ROLES), 'leaving_now': sims4.tuning.tunable.TunableTuple(situation_job=situations.situation_job.SituationJob.TunableReference(description='\n                                The job given to sims that we want to have leave the lot now.\n                                '), role_state=role.role_state.RoleState.TunableReference(description='\n                                The role state given to the sim to get them off the lot now.\n                                '), tuning_group=GroupNames.ROLES)}
    REMOVE_INSTANCE_TUNABLES = ('_level_data', '_buff', '_cost', '_NPC_host_filter', '_NPC_hosted_player_tests', 'NPC_hosted_situation_start_message', 'NPC_hosted_situation_use_player_sim_as_filter_requester', 'NPC_hosted_situation_player_job', 'venue_types', 'venue_invitation_message', 'venue_situation_player_job', 'category', '_display_name', 'situation_description', '_resident_job', '_icon', '_level_data', 'main_goal', 'minor_goal_chains', 'max_participants', '_initiating_sim_tests', 'targeted_situation', 'duration')

    @staticmethod
    def _states():
        return [(1, ForeverState)]

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.leaving_soon.situation_job, cls.leaving_soon.role_state), (cls.leaving_now.situation_job, cls.leaving_now.role_state)]

    @classmethod
    def default_job(cls):
        return cls.leaving_now.situation_job

    def _get_duration(self):
        return 0

    def start_situation(self):
        super().start_situation()
        self._change_state(ForeverState())

    def _create_uninvited_request(self):
        request = situations.bouncer.bouncer_request.BouncerNPCFallbackRequestFactory(self, callback_data=situations.base_situation._RequestUserData(), job_type=self.leaving_soon.situation_job, exclusivity=self.exclusivity)
        self.manager.bouncer.submit_request(request)

    def invite_sim_to_leave(self, sim):
        guest_info = situations.situation_guest_list.SituationGuestInfo(sim.id, self.leaving_soon.situation_job, RequestSpawningOption.CANNOT_SPAWN, BouncerRequestPriority.VIP, expectation_preference=True)
        request = self._create_request_from_guest_info(guest_info)
        self.manager.bouncer.submit_request(request)

    @property
    def _should_cancel_leave_interaction_on_premature_removal(self):
        return True

    @classproperty
    def situation_serialization_option(cls):
        return situations.situation_types.SituationSerializationOption.OPEN_STREETS

class ForeverState(situations.situation_complex.SituationState):
    __qualname__ = 'ForeverState'

    def on_activate(self, reader=None):
        super().on_activate(reader)
        self._handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(5), lambda _: self.timer_expired(), repeating=True, repeating_time_span=clock.interval_in_sim_minutes(5))

    def on_deactivate(self):
        super().on_deactivate()
        if self._handle is not None:
            alarms.cancel_alarm(self._handle)

    def timer_expired(self):
        sims = list(self.owner.all_sims_in_situation_gen())
        for sim in sims:
            while self.owner.sim_has_job(sim, self.owner.leaving_soon.situation_job):
                self.owner._set_job_for_sim(sim, self.owner.leaving_now.situation_job)

