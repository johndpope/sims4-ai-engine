from interactions.context import QueueInsertStrategy
from role.role_state import RoleState
from situations.situation_complex import SituationState
from situations.situation_job import SituationJob
import interactions
import services
import sims4.tuning.instances
import sims4.tuning.tunable
import situations.bouncer

class VoodooSummonSituation(situations.situation_complex.SituationComplexCommon):
    __qualname__ = 'VoodooSummonSituation'
    INSTANCE_TUNABLES = {'summoned_job': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                          A reference to the SituationJob used for the Sim summoned.\n                          '), come_to_me_state=RoleState.TunableReference(description='\n                          The state for telling the summoned sim to come here.\n                          ')), 'come_here_affordance': sims4.tuning.tunable.TunableReference(services.affordance_manager(), description='SI to bring summoned sim to the summoner.')}
    REMOVE_INSTANCE_TUNABLES = ('_buff', '_cost', '_NPC_host_filter', '_NPC_hosted_player_tests', 'NPC_hosted_situation_start_message', 'NPC_hosted_situation_use_player_sim_as_filter_requester', 'NPC_hosted_situation_player_job', 'venue_types', 'venue_invitation_message', 'venue_situation_player_job', 'category', 'main_goal', 'minor_goal_chains', 'max_participants', '_initiating_sim_tests', '_icon', 'targeted_situation', '_resident_job', 'situation_description', 'job_display_ordering', 'entitlement', '_jobs_to_put_in_party', '_relationship_between_job_members', 'main_goal_audio_sting', 'audio_sting_on_start', '_level_data', '_display_name')

    @staticmethod
    def _states():
        return [(1, _ComeHereState)]

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.summoned_job.situation_job, cls.summoned_job.come_to_me_state)]

    @classmethod
    def default_job(cls):
        return cls.summoned_job.situation_job

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._summoned_sim = None

    def start_situation(self):
        super().start_situation()
        self._change_state(_ComeHereState())

    def _on_set_sim_job(self, sim, job_type):
        super()._on_set_sim_job(sim, job_type)
        self._summoned_sim = sim

    def _on_sim_removed_from_situation_prematurely(self, sim):
        super()._on_sim_removed_from_situation_prematurely(sim)
        self._summoned_sim = None

sims4.tuning.instances.lock_instance_tunables(VoodooSummonSituation, exclusivity=situations.bouncer.bouncer_types.BouncerExclusivityCategory.PRE_VISIT, creation_ui_option=situations.situation_types.SituationCreationUIOption.NOT_AVAILABLE, duration=120, _implies_greeted_status=True)

class _ComeHereState(SituationState):
    __qualname__ = '_ComeHereState'

    def __init__(self):
        super().__init__()
        self._interaction = None

    def on_activate(self, reader=None):
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.summoned_job.situation_job, self.owner.summoned_job.come_to_me_state)

    def _on_set_sim_role_state(self, *args, **kwargs):
        super()._on_set_sim_role_state(*args, **kwargs)
        success = self._push_interaction()
        if not success:
            self.owner._self_destruct()

    def on_deactivate(self):
        if self._interaction is not None:
            self._interaction.unregister_on_finishing_callback(self._on_finishing_callback)
            self._interaction = None
        super().on_deactivate()

    def _push_interaction(self):
        target_sim = self.owner.initiating_sim_info.get_sim_instance()
        if target_sim is None:
            return False
        context = interactions.context.InteractionContext(self.owner._summoned_sim, interactions.context.InteractionContext.SOURCE_SCRIPT, interactions.priority.Priority.High, insert_strategy=QueueInsertStrategy.NEXT)
        enqueue_result = self.owner._summoned_sim.push_super_affordance(self.owner.come_here_affordance, target_sim, context)
        if not enqueue_result or enqueue_result.interaction.is_finishing:
            return False
        self._interaction = enqueue_result.interaction
        self._interaction.register_on_finishing_callback(self._on_finishing_callback)
        return True

    def _on_finishing_callback(self, interaction):
        if self._interaction is not interaction:
            return
        self.owner._self_destruct()

