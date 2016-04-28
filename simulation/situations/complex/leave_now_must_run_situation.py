from interactions.context import InteractionContext
from interactions.priority import Priority
from sims4.tuning.tunable_base import GroupNames, FilterTag
from sims4.utils import classproperty
from tag import Tag
import alarms
import clock
import role.role_state
import services
import sims4.tuning.tunable
import situations.situation_complex
import situations.situation_job

class LeaveNowMustRunSituation(situations.situation_complex.SituationComplexCommon):
    __qualname__ = 'LeaveNowMustRunSituation'
    CUSTOM_ROLE_STATE_KEY = 'custom_role_state_id'
    VERIFY_INTERACTION_INTERVAL = 60
    INSTANCE_TUNABLES = {'leaving_now': sims4.tuning.tunable.TunableTuple(situation_job=situations.situation_job.SituationJob.TunableReference(description='\n                                The job given to sims that we want to have leave the lot right now.\n                                '), role_state=role.role_state.RoleState.TunableReference(description='\n                                The role state given to the sim to get them off the lot right now.\n                                '), tuning_group=GroupNames.ROLES), 'affordance_to_push': sims4.tuning.tunable.TunableReference(description='\n                                affordance to push to drive the sim from the lot.\n                                ', manager=services.affordance_manager(), tuning_filter=FilterTag.EXPERT_MODE), 'tag_to_verify': sims4.tuning.tunable.TunableEnumEntry(description="\n                            If an interaction with this tag is not running, then push\n                            'affordance to push' tunable.\n                            ", tunable_type=Tag, default=Tag.INVALID, tuning_filter=FilterTag.EXPERT_MODE)}
    REMOVE_INSTANCE_TUNABLES = ('_level_data', '_buff', '_cost', '_NPC_host_filter', '_NPC_hosted_player_tests', 'NPC_hosted_situation_start_message', 'NPC_hosted_situation_use_player_sim_as_filter_requester', 'NPC_hosted_situation_player_job', 'venue_types', 'venue_invitation_message', 'venue_situation_player_job', 'category', '_display_name', 'situation_description', '_resident_job', '_icon', '_level_data', 'main_goal', 'minor_goal_chains', 'max_participants', '_initiating_sim_tests', 'targeted_situation', 'duration')

    @staticmethod
    def _states():
        return [(1, ForeverState)]

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.leaving_now.situation_job, cls.leaving_now.role_state)]

    @classmethod
    def default_job(cls):
        return cls.leaving_now.situation_job

    def _get_duration(self):
        return 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._leaver = None

    def start_situation(self):
        super().start_situation()
        self._change_state(ForeverState())

    def _create_uninvited_request(self):
        pass

    def _on_set_sim_job(self, sim, job_type):
        super()._on_set_sim_job(sim, job_type)
        self._leaver = sim

    def on_ask_sim_to_leave(self, sim):
        return False

    @classproperty
    def situation_serialization_option(cls):
        return situations.situation_types.SituationSerializationOption.OPEN_STREETS

class ForeverState(situations.situation_complex.SituationState):
    __qualname__ = 'ForeverState'

    def on_activate(self, reader):
        super().on_activate(reader)
        self._handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(self.owner.VERIFY_INTERACTION_INTERVAL), lambda _: self.timer_expired(), repeating=True, repeating_time_span=clock.interval_in_sim_minutes(self.owner.VERIFY_INTERACTION_INTERVAL))

    def on_deactivate(self):
        if self._handle is not None:
            alarms.cancel_alarm(self._handle)
        super().on_deactivate()

    def timer_expired(self):
        sim = self.owner._leaver
        if sim is None:
            return
        interaction_set = sim.get_running_and_queued_interactions_by_tag(frozenset((self.owner.tag_to_verify,)))
        if interaction_set:
            return
        interaction_context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.Critical)
        sim.push_super_affordance(self.owner.affordance_to_push, None, interaction_context)

