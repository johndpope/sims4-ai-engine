from event_testing.test_events import TestEvent
from interactions.interaction_cancel_compatibility import InteractionCancelCompatibility, InteractionCancelReason
from interactions.interaction_finisher import FinishingType
from role.role_state import RoleState
from sims4.tuning.tunable import Tunable, TunableSimMinute
from sims4.tuning.tunable_base import GroupNames
from situations.situation_complex import SituationComplexCommon, SituationState
from situations.situation_job import SituationJob
import services
import sims4.log
import sims4.tuning.tunable
import situations.bouncer
logger = sims4.log.Logger('Fire', default_owner='rfleig')

class FireSituation(SituationComplexCommon):
    __qualname__ = 'FireSituation'
    INSTANCE_TUNABLES = {'victim_job': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                                A reference to the SituationJob used during a fire.\n                                '), fire_panic_state=RoleState.TunableReference(description='The state while the sim is panicking due to fire.'), fire_unaware_state=RoleState.TunableReference(description='\n                                The state while the sim is unaware there is a \n                                fire on the lot.\n                                '), fire_aware_state=RoleState.TunableReference(description="\n                                The state while the Sim is aware there is a fire\n                                but hasn't seen it yet.\n                                "), fire_safe_state=RoleState.TunableReference(description='\n                                The state while the Sim has made it safely away\n                                from the fire.\n                                '), post_fire_state=RoleState.TunableReference(description='\n                                The state the Sim is in after the fire has gone\n                                out.\n                                '), tuning_group=GroupNames.SITUATION), 'got_to_safety_interaction': situations.situation_complex.TunableInteractionOfInterest(description='\n            The interaction to look for when a Sim has routed off of the lot\n            and safely escaped the fire.\n            '), 'go_back_to_panic_interactions': situations.situation_complex.TunableInteractionOfInterest(description='\n            The interactions to look for when a Sim has routed back on to a\n            lot that is on fire which will cause the Sim to go back into panic\n            mode.\n            '), 'TIME_POST_FIRE_IN_SIM_MINUTES': TunableSimMinute(description='\n            Number of Sim minutes that the situation can be in the _PostFireState\n            before the situation ends.\n            ', default=60)}
    REMOVE_INSTANCE_TUNABLES = ('_buff', '_cost', '_NPC_host_filter', '_NPC_hosted_player_tests', 'NPC_hosted_situation_start_message', 'NPC_hosted_situation_use_player_sim_as_filter_requester', 'NPC_hosted_situation_player_job', 'venue_types', 'venue_invitation_message', 'venue_situation_player_job', 'category', 'main_goal', 'minor_goal_chains', '_level_data', '_display_name', 'max_participants', '_initiating_sim_tests', 'targeted_situation', '_resident_job', '_icon', 'situation_description')

    @staticmethod
    def _states():
        return [(1, _PanicState), (2, _UnawareState), (3, _AlertedState), (4, _SafeState), (5, _PostFireState)]

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.victim_job.situation_job, cls.victim_job.fire_panic_state)]

    @classmethod
    def default_job(cls):
        return cls.victim_job.situation_job

    def start_situation(self):
        super().start_situation()
        self._change_state(_UnawareState())

    def advance_to_alerted(self):
        if type(self._cur_state) != _PanicState:
            self._change_state(_PanicState())

    def advance_to_post_fire(self):
        self._change_state(_PostFireState())

    def on_remove(self):
        fire_service = services.get_fire_service()
        if fire_service is not None:
            for sim in self.all_sims_in_situation_gen():
                fire_service.remove_fire_situation(sim)
        super().on_remove()

sims4.tuning.instances.lock_instance_tunables(FireSituation, exclusivity=situations.bouncer.bouncer_types.BouncerExclusivityCategory.NORMAL, creation_ui_option=situations.situation_types.SituationCreationUIOption.NOT_AVAILABLE, duration=0)

class _PanicState(SituationState):
    __qualname__ = '_PanicState'

    def on_activate(self, reader=None):
        logger.debug('Sim is entering the Panic State during a fire.')
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.victim_job.situation_job, self.owner.victim_job.fire_panic_state)
        self._test_event_register(TestEvent.InteractionComplete)

    def _on_set_sim_role_state(self, sim, job_type, role_state_type, role_affordance_target):
        super()._on_set_sim_role_state(sim, job_type, role_state_type, role_affordance_target)
        InteractionCancelCompatibility.cancel_interactions_for_reason(sim, InteractionCancelReason.FIRE, FinishingType.FIRE, 'Interaction was canceled due to a fire on the lot.')

    def handle_event(self, sim_info, event, resolver):
        if event is TestEvent.InteractionComplete and resolver(self.owner.got_to_safety_interaction):
            self._change_state(_SafeState())

class _UnawareState(SituationState):
    __qualname__ = '_UnawareState'

    def on_activate(self, reader=None):
        logger.debug('Sim is entering the Unaware state during a fire.')
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.victim_job.situation_job, self.owner.victim_job.fire_unaware_state)
        fire_service = services.get_fire_service()
        fire_service.register_for_panic_callback()

class _AlertedState(SituationState):
    __qualname__ = '_AlertedState'

    def on_activate(self, reader=None):
        logger.debug('Sim is entering the Alerted State during a fire.')
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.victim_job.situation_job, self.owner.victim_job.fire_alerted_state)

class _SafeState(SituationState):
    __qualname__ = '_SafeState'

    def on_activate(self, reader=None):
        logger.debug('Sim is entering the Safe State during a fire.')
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.victim_job.situation_job, self.owner.victim_job.fire_safe_state)
        self._test_event_register(TestEvent.InteractionStart)

    def handle_event(self, sim_info, event, resolver):
        if event is TestEvent.InteractionStart and resolver(self.owner.go_back_to_panic_interactions):
            if resolver.sim_info.get_sim_instance().is_on_active_lot():
                self._change_state(_PanicState())

class _PostFireState(SituationState):
    __qualname__ = '_PostFireState'

    def on_activate(self, reader=None):
        logger.debug('Sim is entering the Post Fire State during a fire.')
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.victim_job.situation_job, self.owner.victim_job.post_fire_state)
        self.owner._set_duration_alarm(duration_override=self.owner.TIME_POST_FIRE_IN_SIM_MINUTES)
        self._test_event_register(TestEvent.InteractionStart)

    def handle_event(self, sim_info, event, resolver):
        if event is TestEvent.InteractionStart and resolver(self.owner.go_back_to_panic_interactions):
            self._change_state(_UnawareState())

