from event_testing.tests_with_data import TunableParticipantRanInteractionTest
from interactions.aop import AffordanceObjectPair
from interactions.utils.interaction_elements import XevtTriggeredElement
from interactions.utils.notification import NotificationElement
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import TunableTuple, OptionalTunable, TunableReference, TunableMapping, Tunable
from situations.service_npcs import ServiceNpcEndWorkReason
from situations.service_npcs.preroll_autonomy_tuning import ServicePrerollAutonomy
from situations.situation_complex import SituationComplexCommon, SituationState, TunableSituationJobAndRoleState
from situations.situation_types import SituationCreationUIOption
from ui.ui_dialog_notification import TunableUiDialogNotificationSnippet
import event_testing
import services
import sims4.resources
logger = sims4.log.Logger('Situation')

class TunableJobStateAndTest(TunableTuple):
    __qualname__ = 'TunableJobStateAndTest'

    def __init__(self, description='\n        A job state paired when a test for when the situation should transition to that job state\n        ', **kwargs):
        super().__init__(enter_state_test=TunableParticipantRanInteractionTest(locked_args={'running_time': None, 'tooltip': None}, description='Test for what interaction to listen for. If\n                    the Ran interaction test passes, the service sim in\n                    situation will transition to the tuned role state.'), role_state=TunableReference(description='\n                    The role state to set on the service sim when\n                    enter_state_test passes.\n                    ', manager=services.get_instance_manager(sims4.resources.Types.ROLE_STATE)), description=description, **kwargs)

class TunableFinishJobStateAndTest(TunableJobStateAndTest):
    __qualname__ = 'TunableFinishJobStateAndTest'

    def __init__(self, **kwargs):
        super().__init__(notification=OptionalTunable(description='\n                Localized strings to display as notifications when this service\n                NPC finishes his/her work for the day for the matching finish\n                job reason. Parameter 0 is the funds deducted from the\n                household and parameter 1 is the amount added to bills, so you\n                can use {0.Money}, {0.Number}, {1.Money}, or {1.Number}.\n                ', tunable=TunableUiDialogNotificationSnippet()), **kwargs)

class ServiceNpcSituation(SituationComplexCommon):
    __qualname__ = 'ServiceNpcSituation'
    INSTANCE_TUNABLES = {'_service_npc_job': TunableSituationJobAndRoleState(description='\n            The job for service sim in this situation and the corresponding\n            starting role state for service sim. EX: the job for a maid would\n            be the maid_job.\n            ', display_name='Service Npc Job'), 'start_work_test_and_state': OptionalTunable(description="\n            If tuned, the situation will start by going to the ArriveOnLotState,\n            and the service npc won't go into their 'working state' until\n            the tuned test passes. When the test passes, the service npc will\n            go into the work state with the tuned role state.\n            \n            If this is left as None, the service npc will start the situation\n            going to the working state.\n            ", tunable=TunableJobStateAndTest()), 'finish_job_states': TunableMapping(description='\n            Tune pairs of job finish role states with job finish tests. When\n            those tests pass, the sim will transition to the paired role state.\n            The situation will also be transitioned to the Leaving situation\n            state.\n            ', key_type=ServiceNpcEndWorkReason, value_type=TunableFinishJobStateAndTest()), 'preroll_autonomy': OptionalTunable(description='\n            If enabled, we will forcefully run an autonomy request when the\n            service npc first gets spawned on the lot. The tunable specifies\n            tests/settings for how to post process a manual autonomy request on\n            the service npc. EX: preroll autonomy for the maid when she first\n            gets onto the lot has an affordance link that blacklists her from\n            doing the serviceNpc_noMoreWork interaction.\n            ', tunable=ServicePrerollAutonomy.TunableFactory()), 'fake_perform_on_preroll_failure': OptionalTunable(description="\n            Enable this ONLY if preroll_autonomy is tuned.\n            When enabled, the situation to listen to the interaction pushed by\n            preroll autonomy and check if that interaction succeeded in running.\n            If the interaction failed to run for any reason, the situation will\n            run the service npc's fake_perform_job.\n            \n            Ex: for the mailman, preroll autonomy is tuned so the mailman has\n            to delivery mail. if the delivery mail interaction is pushed,\n            but the mailman cannot route to the mailbox, we will still deliver\n            the mail using the service npc mailman tuning's fake perform job\n            ", tunable=TunableTuple(notification=OptionalTunable(description='\n                    If enabled, a notification will be displayed when the\n                    preroll fails and the fake perform modified some items.\n                    ', tunable=NotificationElement.TunableFactory(locked_args={'timing': XevtTriggeredElement.LOCKED_AT_BEGINNING, 'recipient_subject': None})))), 'fail_on_preroll_execute_failure': Tunable(description='\n            If the preroll execution failed, we consider that there was no\n            preroll done and go to the failure state.\n            ', tunable_type=bool, default=True)}
    REMOVE_INSTANCE_TUNABLES = ('_level_data', '_buff', '_cost', '_NPC_host_filter', '_NPC_hosted_player_tests', 'NPC_hosted_situation_start_message', 'venue_types', 'venue_invitation_message')
    CANCEL_SERVICE_LEAVING_REASONS = set((ServiceNpcEndWorkReason.FIRED, ServiceNpcEndWorkReason.NOT_PAID))

    @staticmethod
    def _states():
        return [(1, ArrivingOnLotSituationState), (2, WorkingSituationState), (3, LeaveSituationState)]

    @classmethod
    def default_job(cls):
        return cls._service_npc_job.job

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls._service_npc_job.job, cls._service_npc_job.role_state)]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        reader = self._seed.custom_init_params_reader
        self._service_npc_type = services.service_npc_manager().get(reader.read_uint64('service_npc_type_id', 0))
        if self._service_npc_type is None:
            raise ValueError('Invalid service npc type for situation: {}'.format(self))
        self._hiring_household = services.household_manager().get(reader.read_uint64('household_id', 0))
        if self._hiring_household is None:
            raise ValueError('Invalid household for situation: {}'.format(self))
        self._is_recurring = reader.read_bool('is_recurring', False)
        self._object_definition_to_craft = reader.read_uint64('user_specified_data_id', 0)
        self._crafted_object_id = reader.read_uint64('crafted_object_id', 0)
        self._service_start_time = services.time_service().sim_now
        self._had_preroll_work = True
        self._is_leaving = False

    def start_situation(self):
        if services.get_super_speed_three_service().in_or_has_requested_super_speed_three():
            clock_service = services.game_clock_service()
            clock_service.stop_super_speed_three()
        super().start_situation()
        self._change_state(ArrivingOnLotSituationState())

    def _save_custom_situation(self, writer):
        super()._save_custom_situation(writer)
        writer.write_uint64('household_id', self._hiring_household.id)
        writer.write_uint64('service_npc_type_id', self._service_npc_type.guid64)
        writer.write_uint64('is_recurring', self._is_recurring)
        writer.write_uint64('user_specified_data_id', self._object_definition_to_craft)
        writer.write_uint64('crafted_object_id', self._crafted_object_id)

    def _on_set_sim_job(self, sim, job_type):
        service_record = self._hiring_household.get_service_npc_record(self._service_npc_type.guid64)
        service_record.add_preferred_sim(sim.sim_info.id)
        self._service_npc_type.on_service_sim_entered_situation(sim, self)
        start_work_test = self._get_start_work_test()
        if start_work_test is None and self.start_work_test_and_state is not None:
            self._set_job_role_state(self.default_job(), self.start_work_test_and_state.role_state, role_affordance_target=self.role_affordance_target)

    def _on_set_sim_role_state(self, sim, job_type, role_state_type, role_affordance_target):
        super()._on_set_sim_role_state(sim, job_type, role_state_type, role_affordance_target)
        if self._get_start_work_test() is None:
            self._change_state(WorkingSituationState())

    def _on_remove_sim_from_situation(self, sim):
        if sim is self.service_sim() and (not self._is_recurring and not self._is_leaving) and services.current_zone().service_npc_service is not None:
            services.current_zone().service_npc_service.cancel_service(self._hiring_household, self._service_npc_type)
        super()._on_remove_sim_from_situation(sim)

    @property
    def _should_cancel_leave_interaction_on_premature_removal(self):
        return True

    def service_sim(self):
        sim = next(self.all_sims_in_job_gen(self.default_job()), None)
        return sim

    def on_ask_sim_to_leave(self, sim):
        return False

    def _on_preroll_cancelled(self, interaction):
        if interaction.uncanceled:
            return
        num_objects_modified = self._service_npc_type.fake_perform(self._hiring_household)
        if num_objects_modified > 0:
            notification = self.fake_perform_on_preroll_failure.notification
            if notification is not None:
                hiring_household_client = self._hiring_household.client
                if hiring_household_client is not None and hiring_household_client.active_sim is not None:
                    notification_element = notification(interaction)
                    notification_element.show_notification(recipients=(hiring_household_client.active_sim,))

    def _on_starting_work(self):
        if self.preroll_autonomy is not None:
            chosen_interaction = self.preroll_autonomy().run_preroll(self.service_sim())
            if chosen_interaction is None:
                self._had_preroll_work = False
            else:
                execute_result = AffordanceObjectPair.execute_interaction(chosen_interaction)
                if not execute_result:
                    if self.fail_on_preroll_execute_failure:
                        self._had_preroll_work = False
                        if self.fake_perform_on_preroll_failure is not None:
                            self._on_preroll_cancelled(chosen_interaction)
                        elif self.fake_perform_on_preroll_failure is not None:
                            chosen_interaction.register_on_cancelled_callback(self._on_preroll_cancelled)
                elif self.fake_perform_on_preroll_failure is not None:
                    chosen_interaction.register_on_cancelled_callback(self._on_preroll_cancelled)
        if not self._had_preroll_work:
            self._change_state(LeaveSituationState(ServiceNpcEndWorkReason.NO_WORK_TO_DO))

    def _situation_timed_out(self, _):
        if not self._is_leaving:
            self._change_state(LeaveSituationState(ServiceNpcEndWorkReason.FINISHED_WORK))

    def _on_leaving_situation(self, end_work_reason):
        service_npc_type = self._service_npc_type
        household = self._hiring_household
        try:
            now = services.time_service().sim_now
            time_worked = now - self._service_start_time
            time_worked_in_hours = time_worked.in_hours()
            if self._had_preroll_work:
                cost = service_npc_type.get_cost(time_worked_in_hours)
            else:
                cost = 0
            if cost > 0:
                (paid_amount, billed_amount) = service_npc_type.try_charge_for_service(household, cost)
                end_work_reason = ServiceNpcEndWorkReason.NOT_PAID
            else:
                paid_amount = 0
                billed_amount = 0
            self._send_end_work_notification(end_work_reason, paid_amount, billed_amount)
            service_record = household.get_service_npc_record(service_npc_type.guid64)
            service_record.time_last_finished_service = now
            if end_work_reason == ServiceNpcEndWorkReason.FIRED:
                service_sim = self.service_sim()
                if service_record is not None:
                    service_record.add_fired_sim(service_sim.id)
                    service_record.remove_preferred_sim(service_sim.id)
            while end_work_reason in ServiceNpcSituation.CANCEL_SERVICE_LEAVING_REASONS:
                services.current_zone().service_npc_service.cancel_service(household, service_npc_type)
        except Exception as e:
            logger.exception('Exception while executing _on_leaving_situation for situation {}', self, exc=e)
        finally:
            if not self._is_recurring:
                services.current_zone().service_npc_service.cancel_service(household, service_npc_type)
        return end_work_reason

    def _send_end_work_notification(self, end_work_reason, *localization_args):
        end_work_tuning = self.finish_job_states[end_work_reason]
        notification = end_work_tuning.notification
        if notification is None:
            return
        for client in services.current_zone().client_manager.values():
            recipient = client.active_sim
            while recipient is not None:
                dialog = notification(recipient)
                dialog.show_dialog(additional_tokens=localization_args, icon_override=(None, self.service_sim()))
                break

    @property
    def hiring_household(self):
        return self._hiring_household

    @property
    def object_definition_to_craft(self):
        return self._object_definition_to_craft

    def set_crafted_object_id(self, object_id):
        self._crafted_object_id = object_id

    @property
    def role_affordance_target(self):
        target = services.object_manager().get(self._crafted_object_id)
        if target is None:
            target = services.current_zone().inventory_manager.get(self._crafted_object_id)
        return target

    def _get_start_work_test(self):
        if self.start_work_test_and_state is not None:
            start_work_test = self.start_work_test_and_state.enter_state_test
            if start_work_test.affordances or start_work_test.tags:
                return start_work_test

    def _get_role_state_overrides(self, sim, job_type, role_state_type, role_affordance_target):
        return (role_state_type, self.role_affordance_target)

lock_instance_tunables(ServiceNpcSituation, creation_ui_option=SituationCreationUIOption.NOT_AVAILABLE, NPC_hosted_situation_player_job=None, venue_situation_player_job=None)

class ServiceNpcBaseSituationState(SituationState):
    __qualname__ = 'ServiceNpcBaseSituationState'

    def on_activate(self, reader):
        super().on_activate(reader)
        self._test_event_register(event_testing.test_events.TestEvent.InteractionComplete)
        self._test_event_register(event_testing.test_events.TestEvent.InteractionStart)

    def handle_event(self, sim_info, event, resolver):
        pass

class ArrivingOnLotSituationState(SituationState):
    __qualname__ = 'ArrivingOnLotSituationState'

    def on_activate(self, reader):
        super().on_activate(reader)
        start_work_test = self.owner._get_start_work_test()
        if start_work_test is not None:
            for event in start_work_test.test_events:
                self._test_event_register(event)

    def handle_event(self, sim_info, event, resolver):
        start_work_test = self.owner._get_start_work_test()
        if self.owner.test_interaction_complete_by_job_holder(sim_info, resolver, self.owner.default_job(), start_work_test):
            self.owner._set_job_role_state(self.owner.default_job(), self.owner.start_work_test_and_state.role_state, role_affordance_target=self.owner.role_affordance_target)
            self._change_state(WorkingSituationState())

class WorkingSituationState(ServiceNpcBaseSituationState):
    __qualname__ = 'WorkingSituationState'

    def on_activate(self, reader):
        super().on_activate(reader)
        if reader is None:
            self.owner._on_starting_work()

    def _test_event(self, event, sim_info, resolver, test):
        if event in test.test_events:
            return self.owner.test_interaction_complete_by_job_holder(sim_info, resolver, self.owner.default_job(), test)
        return False

    def handle_event(self, sim_info, event, resolver):
        finish_job_states = self.owner.finish_job_states
        for (finish_reason, finish_job_state) in finish_job_states.items():
            while self._test_event(event, sim_info, resolver, finish_job_state.enter_state_test):
                self._change_state(LeaveSituationState(finish_reason, resolver))
                break

class LeaveSituationState(SituationState):
    __qualname__ = 'LeaveSituationState'

    def __init__(self, leave_role_reason=None, triggering_resolver=None):
        super().__init__()
        self._leave_role_reason = leave_role_reason
        self._triggering_resolver = triggering_resolver

    def on_activate(self, reader):
        super().on_activate(reader)
        self.owner._is_leaving = True
        if reader is None:
            self._leave_role_reason = self.owner._on_leaving_situation(self._leave_role_reason)
            leave_role_state = self.owner.finish_job_states[self._leave_role_reason].role_state
            service_sim = self.owner.service_sim()
            if service_sim is None:
                logger.warn('Service sim is None for {}.', self, owner='bhill')
                return
            if self._leave_role_reason == ServiceNpcEndWorkReason.ASKED_TO_HANG_OUT:
                services.get_zone_situation_manager().create_visit_situation(service_sim)
            elif self._leave_role_reason == ServiceNpcEndWorkReason.FIRED or self._leave_role_reason == ServiceNpcEndWorkReason.DISMISSED:
                services.get_zone_situation_manager().make_sim_leave_now_must_run(service_sim)
            elif self._leave_role_reason == ServiceNpcEndWorkReason.NOT_PAID:
                if leave_role_state is not None:
                    self.owner._set_job_role_state(self.owner.default_job(), leave_role_state, role_affordance_target=self.owner.role_affordance_target)
                    services.get_zone_situation_manager().make_sim_leave(service_sim)
                else:
                    services.get_zone_situation_manager().make_sim_leave_now_must_run(service_sim)
                    if leave_role_state is not None:
                        self.owner._set_job_role_state(self.owner.default_job(), leave_role_state, role_affordance_target=self.owner.role_affordance_target)
                    else:
                        services.get_zone_situation_manager().make_sim_leave(service_sim)
            elif leave_role_state is not None:
                self.owner._set_job_role_state(self.owner.default_job(), leave_role_state, role_affordance_target=self.owner.role_affordance_target)
            else:
                services.get_zone_situation_manager().make_sim_leave(service_sim)

