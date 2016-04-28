from role.role_state import RoleState
from situations.situation_complex import SituationState
from situations.situation_job import SituationJob
from situations.situation_types import GreetedStatus
import services
import sims4.tuning.instances
import sims4.tuning.tunable
import situations.bouncer
import situations.situation_types
import venues

class InviteToSituation(situations.situation_complex.SituationComplexCommon):
    __qualname__ = 'InviteToSituation'
    INSTANCE_TUNABLES = {'invited_job': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                          A reference to the SituationJob used for the Sims invited to.\n                          '), invited_to_state=RoleState.TunableReference(description='\n                          The state for telling a sim to wait. They will momentarily be\n                          pulled from this situation by a visit or venue situation.\n                          ')), 'purpose': sims4.tuning.tunable.TunableEnumEntry(description='\n                The purpose/reason used to perform the venue specific operation\n                to get this sim in the appropriate situation.\n                This should be tuned to Invite In, but since that is a dynamic enum\n                you must do it yourself.\n                ', tunable_type=venues.venue_constants.NPCSummoningPurpose, default=venues.venue_constants.NPCSummoningPurpose.DEFAULT)}
    REMOVE_INSTANCE_TUNABLES = ('_buff', '_cost', '_NPC_host_filter', '_NPC_hosted_player_tests', 'NPC_hosted_situation_start_message', 'NPC_hosted_situation_use_player_sim_as_filter_requester', 'NPC_hosted_situation_player_job', 'venue_types', 'venue_invitation_message', 'venue_situation_player_job', 'category', 'main_goal', 'minor_goal_chains', 'max_participants', '_initiating_sim_tests', '_icon', 'targeted_situation', '_resident_job', 'situation_description', 'job_display_ordering', 'entitlement', '_jobs_to_put_in_party', '_relationship_between_job_members', 'main_goal_audio_sting', 'audio_sting_on_start', '_level_data', '_display_name')

    @staticmethod
    def _states():
        return [(1, _WaitState)]

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.invited_job.situation_job, cls.invited_job.invited_to_state)]

    @classmethod
    def default_job(cls):
        return cls.invited_job.situation_job

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tick_alarm_handle = None

    def start_situation(self):
        super().start_situation()
        self.manager.add_pre_bouncer_update(self)
        self._change_state(_WaitState())

    def _issue_requests(self):
        pass

    def on_pre_bouncer_update(self):
        zone = services.current_zone()
        venue = zone.venue_service.venue
        for sim_info in self._seed.invited_sim_infos_gen():
            venue.summon_npcs((sim_info,), self.purpose)

    @classmethod
    def get_player_greeted_status_from_seed(cls, situation_seed):
        for sim_info in situation_seed.invited_sim_infos_gen():
            while sim_info.is_npc and sim_info.lives_here:
                return GreetedStatus.GREETED
        return GreetedStatus.NOT_APPLICABLE

sims4.tuning.instances.lock_instance_tunables(InviteToSituation, exclusivity=situations.bouncer.bouncer_types.BouncerExclusivityCategory.PRE_VISIT, creation_ui_option=situations.situation_types.SituationCreationUIOption.NOT_AVAILABLE, duration=1, _implies_greeted_status=False)

class _WaitState(SituationState):
    __qualname__ = '_WaitState'

