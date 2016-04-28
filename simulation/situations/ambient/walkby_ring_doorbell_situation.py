from role.role_state import RoleState
from sims4.tuning.tunable import TunableSet, TunableEnumWithFilter
from sims4.tuning.tunable_base import GroupNames
from sims4.utils import classproperty
from situations.situation_complex import SituationComplexCommon, SituationState
from situations.situation_job import SituationJob
from tag import Tag
import alarms
import clock
import interactions
import interactions.context
import services
import sims4.log
import sims4.tuning.instances
import sims4.tuning.tunable
import situations.bouncer
logger = sims4.log.Logger('Walkby')

class WalkbyRingDoorBellSituation(SituationComplexCommon):
    __qualname__ = 'WalkbyRingDoorBellSituation'
    INSTANCE_TUNABLES = {'walker_job': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                          A reference to the SituationJob used for the Sim performing the walkby\n                          '), ring_doorbell_state=RoleState.TunableReference(description='\n                          The state for telling a Sim to go and ring the doorbell.  This is the initial state.\n                          '), mailbox_state=RoleState.TunableReference(description='\n                          The state for telling a Sim to go wait by the mailbox. \n                          This is a fall back for when they cannot reach the front door.\n                          '), wait_for_invitation_state=RoleState.TunableReference(description='\n                          The state for telling a Sim to wait for the other Sim to invite them in.\n                          '), leave_state=RoleState.TunableReference(description="\n                          The state for the sim leaving if you don't invite them in.\n                          "), tuning_group=GroupNames.SITUATION), 'wait_for_invitation_delay': sims4.tuning.tunable.TunableSimMinute(description='\n                                        The amount of time to wait for a Sim to greet the walker Sim.', default=60, tuning_group=GroupNames.SITUATION), 'can_start_walkby_limiting_tags': TunableSet(description="\n                Don't start a situation of this type if another situation is\n                already running that has any of these tags in its tags field.\n                Basically we don't want two sims ringing your doorbell at the same\n                time because that would be weird.\n                ", tunable=TunableEnumWithFilter(tunable_type=Tag, default=Tag.INVALID, filter_prefixes=['situation']))}
    REMOVE_INSTANCE_TUNABLES = ('_buff', '_cost', '_NPC_host_filter', '_NPC_hosted_player_tests', 'NPC_hosted_situation_start_message', 'NPC_hosted_situation_use_player_sim_as_filter_requester', 'NPC_hosted_situation_player_job', 'venue_types', 'venue_invitation_message', 'venue_situation_player_job', 'category', 'main_goal', 'minor_goal_chains', '_level_data', '_display_name', 'max_participants', '_initiating_sim_tests', 'targeted_situation', '_resident_job', '_icon', 'situation_description')

    @staticmethod
    def _states():
        return [(2, _RingDoorBellState), (3, _MailboxState), (4, _WaitForInvitationState), (5, _LeaveState)]

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.walker_job.situation_job, cls.walker_job.ring_doorbell_state)]

    @classmethod
    def default_job(cls):
        return cls.walker_job.situation_job

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._walker = None
        self._state_interruptible_by_user_action = True

    def start_situation(self):
        super().start_situation()
        self._change_state(_RingDoorBellState())

    def _on_set_sim_job(self, sim, job_type):
        super()._on_set_sim_job(sim, job_type)
        self._walker = sim

    def _on_remove_sim_from_situation(self, sim):
        super()._on_remove_sim_from_situation(sim)
        self._walker = None

    @property
    def _should_cancel_leave_interaction_on_premature_removal(self):
        return True

    def _on_wait_for_invitation_expired(self):
        pass

    @classmethod
    def can_start_walkby(cls, lot_id):
        if services.get_zone_situation_manager().is_situation_with_tags_running(cls.can_start_walkby_limiting_tags):
            return False
        active_lot_id = services.active_household_lot_id()
        if active_lot_id is None:
            return False
        return lot_id == active_lot_id

    @classproperty
    def situation_serialization_option(cls):
        return situations.situation_types.SituationSerializationOption.OPEN_STREETS

sims4.tuning.instances.lock_instance_tunables(WalkbyRingDoorBellSituation, exclusivity=situations.bouncer.bouncer_types.BouncerExclusivityCategory.WALKBY, creation_ui_option=situations.situation_types.SituationCreationUIOption.NOT_AVAILABLE)

class _RingDoorBellState(SituationState):
    __qualname__ = '_RingDoorBellState'

    def __init__(self):
        super().__init__()
        self._interaction = None

    def on_activate(self, reader=None):
        logger.debug('Walker is entering ring door bell state.')
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.walker_job.situation_job, self.owner.walker_job.ring_doorbell_state)

    def _on_set_sim_role_state(self, sim, job_type, role_state_type, role_affordance_target):
        super()._on_set_sim_role_state(sim, job_type, role_state_type, role_affordance_target)
        self._choose_and_run_interaction()

    def on_deactivate(self):
        if self._interaction is not None:
            self._interaction.unregister_on_finishing_callback(self._on_finishing_callback)
            self._interaction = None
        super().on_deactivate()

    def _choose_and_run_interaction(self):
        self._interaction = self.owner._choose_role_interaction(self.owner._walker, run_priority=interactions.priority.Priority.Low)
        if self._interaction is None:
            logger.debug("Walker couldn't find interaction on front door.")
            self._change_state(_MailboxState())
            return
        execute_result = interactions.aop.AffordanceObjectPair.execute_interaction(self._interaction)
        if not execute_result:
            logger.debug('Walker failed to execute interaction on front door.')
            self._interaction = None
            self._change_state(_MailboxState())
            return
        logger.debug('Walker starting interaction on front door.')
        self._interaction.register_on_finishing_callback(self._on_finishing_callback)

    def _on_finishing_callback(self, interaction):
        if self._interaction is not interaction:
            return
        if interaction.uncanceled or interaction.was_initially_displaced:
            self._change_state(_WaitForInvitationState())
            return
        logger.debug('Walker failed interaction on front door.')
        self._change_state(_MailboxState())

class _MailboxState(SituationState):
    __qualname__ = '_MailboxState'

    def __init__(self):
        super().__init__()
        self._interaction = None

    def on_activate(self, reader=None):
        logger.debug('Walker is entering mailbox state.')
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.walker_job.situation_job, self.owner.walker_job.mailbox_state)

    def on_deactivate(self):
        if self._interaction is not None:
            self._interaction.unregister_on_finishing_callback(self._on_finishing_callback)
            self._interaction = None
        super().on_deactivate()

    def _on_set_sim_role_state(self, *args, **kwargs):
        super()._on_set_sim_role_state(*args, **kwargs)
        self._choose_and_run_interaction()

    def _choose_and_run_interaction(self):
        self._interaction = self.owner._choose_role_interaction(self.owner._walker, run_priority=interactions.priority.Priority.Low)
        if self._interaction is None:
            logger.debug("Walker couldn't find interaction on mailbox.")
            self._interaction = None
            self._change_state(_WaitForInvitationState())
            return
        execute_result = interactions.aop.AffordanceObjectPair.execute_interaction(self._interaction)
        if not execute_result:
            logger.debug('Walker failed to execute interaction on mailbox.')
            self._change_state(_WaitForInvitationState())
            return
        logger.debug('Walker starting interaction on mailbox.')
        self._interaction.register_on_finishing_callback(self._on_finishing_callback)

    def _on_finishing_callback(self, interaction):
        if self._interaction is not interaction:
            return
        self._change_state(_WaitForInvitationState())

class _WaitForInvitationState(SituationState):
    __qualname__ = '_WaitForInvitationState'

    def __init__(self):
        super().__init__()
        self._timeout_handle = None

    def on_activate(self, reader=None):
        logger.debug('Walker is entering wait state.')
        super().on_activate(reader)
        self.owner._state_interruptible_by_user_action = False
        self.owner._set_job_role_state(self.owner.walker_job.situation_job, self.owner.walker_job.wait_for_invitation_state)
        timeout = self.owner.wait_for_invitation_delay
        self._timeout_handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(timeout), lambda _: self.timer_expired())

    def on_deactivate(self):
        if self._timeout_handle is not None:
            alarms.cancel_alarm(self._timeout_handle)
        super().on_deactivate()

    def timer_expired(self):
        logger.debug('Walker was not invited in and is heading home.')
        self.owner._on_wait_for_invitation_expired()
        self._change_state(_LeaveState())

class _LeaveState(SituationState):
    __qualname__ = '_LeaveState'

    def on_activate(self, reader=None):
        logger.debug('Walker is leaving.')
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.walker_job.situation_job, self.owner.walker_job.leave_state)

