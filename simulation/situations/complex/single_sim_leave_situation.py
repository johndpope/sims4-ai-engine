from event_testing.test_events import TestEvent
from interactions.context import InteractionContext
from interactions.priority import Priority
from sims4.tuning.tunable_base import GroupNames, FilterTag
from sims4.utils import classproperty
import alarms
import clock
import objects
import role.role_state
import services
import sims4.tuning.tunable
import situations.situation_complex
import situations.situation_job
logger = sims4.log.Logger('Leave')

class SingleSimLeaveSituation(situations.situation_complex.SituationComplexCommon):
    __qualname__ = 'SingleSimLeaveSituation'
    INSTANCE_TUNABLES = {'situation_role': sims4.tuning.tunable.TunableTuple(situation_job=situations.situation_job.SituationJob.TunableReference(description='\n                                The job given to sim in this situation.\n                                '), leave_role_state=role.role_state.RoleState.TunableReference(description='\n                                The role state to get the Sim out of the world now.\n                                '), imprisoned_role_state=role.role_state.RoleState.TunableReference(description='\n                                The role state for a Sim who is imprisoned on the lot.\n                                '), delay_role_state=role.role_state.RoleState.TunableReference(description='\n                                The role state for a Sim who failed the leave interaction\n                                unexpectedly. This role state gives them something to do\n                                briefly before they try to leave again. They should be\n                                limited to self affordances.\n                                '), tuning_group=GroupNames.ROLES), 'affordance_to_push': sims4.tuning.tunable.TunableReference(description='\n                                affordance to push to drive the sim from the lot.\n                                ', manager=services.affordance_manager()), 'affordances_to_monitor': situations.situation_complex.TunableInteractionOfInterest(description='\n                                Tag for the leave interaction affordances so the situation\n                                can monitor whether the interaction completed successfully.\n                                '), 'look_busy_timeout': sims4.tuning.tunable.TunableSimMinute(description='\n                                The amount of time a Sim will spending looking busy, doing self interactions,\n                                if they encounter an unexpected transition failure in the open streets\n                                when trying to leave. After the time out they will \n                                try to leave again.\n                                ', default=15, minimum=5), 'imprisoned_timeout': sims4.tuning.tunable.TunableSimMinute(description='\n                                The amount of time a Sim will spending acting like you have trapped \n                                them in your house before trying to leave again.\n                                ', default=60, minimum=5)}
    REMOVE_INSTANCE_TUNABLES = situations.situation.Situation.NON_USER_FACING_REMOVE_INSTANCE_TUNABLES
    MAX_OPEN_STREETS_FAILURES = 3
    MAX_ON_LOT_FAILURES = 2
    FAILSAFE_TIMEOUT = 60

    @staticmethod
    def _states():
        return [(1, LeaveState), (2, ImprisonedState), (3, DelayState)]

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.situation_role.situation_job, cls.situation_role.leave_role_state)]

    @classmethod
    def default_job(cls):
        return cls.situation_role.situation_job

    def _get_duration(self):
        return 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._leaver = None
        self._num_open_streets_failures = 0
        self._num_on_lot_failures = 0

    def start_situation(self):
        super().start_situation()
        self._change_state(LeaveState())

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

class LeaveState(situations.situation_complex.SituationState):
    __qualname__ = 'LeaveState'

    def on_activate(self, reader):
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.situation_role.situation_job, self.owner.situation_role.leave_role_state)
        self._test_event_register(TestEvent.InteractionExitedPipeline)
        self._handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(self.owner.FAILSAFE_TIMEOUT), lambda _: self.timer_expired(), repeating=True, repeating_time_span=clock.interval_in_sim_minutes(self.owner.FAILSAFE_TIMEOUT))

    def on_deactivate(self):
        if self._handle is not None:
            alarms.cancel_alarm(self._handle)
            self._handle = None
        super().on_deactivate()

    def _on_set_sim_role_state(self, sim, job_type, role_state_type, role_affordance_target):
        super()._on_set_sim_role_state(sim, job_type, role_state_type, role_affordance_target)
        self._push_interaction()

    def _push_interaction(self):
        sim = self.owner._leaver
        interaction_context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.Critical)
        enqueue_result = sim.push_super_affordance(self.owner.affordance_to_push, None, interaction_context)
        if not enqueue_result or enqueue_result.interaction.is_finishing:
            logger.debug('Leaver :{} failed to push leave interaction', self.owner._leaver)
            return self.owner._change_state(DelayState())
        logger.debug('Leaver :{} pushed leave interaction', sim)

    def handle_event(self, sim_info, event, resolver):
        if event == TestEvent.InteractionExitedPipeline and (self.owner._leaver is not None and sim_info is self.owner._leaver.sim_info) and resolver(self.owner.affordances_to_monitor):
            interaction = resolver.interaction
            leaver = self.owner._leaver
            if interaction is not None and not isinstance(interaction, objects.base_interactions.AggregateSuperInteraction):
                if interaction.transition_failed:
                    if leaver.is_on_active_lot():
                        logger.debug('Leaver :{} transition failed on active lot {} times', leaver, self.owner._num_on_lot_failures)
                        if self.owner._num_on_lot_failures >= self.owner.MAX_ON_LOT_FAILURES:
                            self.owner._change_state(ImprisonedState())
                        else:
                            self.owner._change_state(DelayState())
                            if self.owner._num_open_streets_failures >= self.owner.MAX_OPEN_STREETS_FAILURES:
                                leaver.sim_info.save_sim()
                                leaver.schedule_destroy_asap(source=self, cause='Repeated leave lot transition failures in open streets.')
                            else:
                                self.owner._change_state(DelayState())
                                logger.debug('Leaver :{} leave interaction finished:{}.', self.owner._leaver, interaction.finisher_repr())
                                self.owner._change_state(DelayState())
                    elif self.owner._num_open_streets_failures >= self.owner.MAX_OPEN_STREETS_FAILURES:
                        leaver.sim_info.save_sim()
                        leaver.schedule_destroy_asap(source=self, cause='Repeated leave lot transition failures in open streets.')
                    else:
                        self.owner._change_state(DelayState())
                        logger.debug('Leaver :{} leave interaction finished:{}.', self.owner._leaver, interaction.finisher_repr())
                        self.owner._change_state(DelayState())
                else:
                    logger.debug('Leaver :{} leave interaction finished:{}.', self.owner._leaver, interaction.finisher_repr())
                    self.owner._change_state(DelayState())

    def timer_expired(self):
        sim = self.owner._leaver
        if sim is None:
            return
        interaction_set = sim.get_running_and_queued_interactions_by_tag(frozenset(self.owner.affordances_to_monitor.tags))
        if interaction_set:
            return
        self._push_interaction()

class DelayState(situations.situation_complex.SituationState):
    __qualname__ = 'DelayState'

    def on_activate(self, reader):
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.situation_role.situation_job, self.owner.situation_role.delay_role_state)
        self._handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(self.owner.look_busy_timeout), lambda _: self.timer_expired())
        logger.debug('Leaver :{} entering DelayState.', self.owner._leaver)

    def on_deactivate(self):
        logger.debug('Leaver :{} exiting DelayState.', self.owner._leaver)
        if self._handle is not None:
            alarms.cancel_alarm(self._handle)
            self._handle = None
        super().on_deactivate()

    def timer_expired(self):
        self.owner._change_state(LeaveState())

class ImprisonedState(situations.situation_complex.SituationState):
    __qualname__ = 'ImprisonedState'

    def on_activate(self, reader):
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.situation_role.situation_job, self.owner.situation_role.imprisoned_role_state)
        self._handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(self.owner.imprisoned_timeout), lambda _: self.timer_expired())
        logger.debug('Leaver :{} entering ImprisonedState.', self.owner._leaver)

    def on_deactivate(self):
        logger.debug('Leaver :{} exiting ImprisonedState.', self.owner._leaver)
        if self._handle is not None:
            alarms.cancel_alarm(self._handle)
            self._handle = None
        super().on_deactivate()

    def timer_expired(self):
        self.owner._change_state(LeaveState())

