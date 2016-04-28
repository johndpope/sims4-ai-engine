import situations.situation_types
import situations.situation_complex

class VisitingNPCSituation(situations.situation_complex.SituationComplexCommon):
    __qualname__ = 'VisitingNPCSituation'
    INSTANCE_SUBCLASSES_ONLY = True
    REMOVE_INSTANCE_TUNABLES = ('_buff', '_cost', '_NPC_host_filter', '_NPC_hosted_player_tests', 'NPC_hosted_situation_start_message', 'NPC_hosted_situation_use_player_sim_as_filter_requester', 'NPC_hosted_situation_player_job', 'venue_types', 'venue_invitation_message', 'venue_situation_player_job', 'category', 'main_goal', 'minor_goal_chains', 'max_participants', '_initiating_sim_tests', '_icon', 'targeted_situation', '_resident_job', 'situation_description', 'job_display_ordering', 'entitlement', '_jobs_to_put_in_party', '_relationship_between_job_members', 'main_goal_audio_sting', 'audio_sting_on_start', '_level_data', '_display_name')

    @classmethod
    def _get_greeted_status(cls):
        return situations.situation_types.GreetedStatus.GREETED

