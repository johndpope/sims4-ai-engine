from autonomy.autonomy_request import AutonomyDistanceEstimationBehavior
from crafting.crafting_interactions import DebugCreateCraftableInteraction
from event_testing.test_events import TestEvent
from role.role_state import RoleState
from sims4.tuning.tunable import TunableMapping
from sims4.tuning.tunable_base import GroupNames
from situations.service_npcs import ServiceNpcEndWorkReason
from situations.situation_complex import SituationComplexCommon, SituationState
from situations.situation_job import SituationJob
from ui.ui_dialog_notification import TunableUiDialogNotificationSnippet
import alarms
import clock
import interactions
import services
import sims4.log
import sims4.tuning.instances
import sims4.tuning.tunable
import situations.bouncer
logger = sims4.log.Logger('PizzaDelivery', default_owner='bhill')

class PizzaDeliverySituation(SituationComplexCommon):
    __qualname__ = 'PizzaDeliverySituation'
    INSTANCE_TUNABLES = {'pizza_delivery_job': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                A reference to the SituationJob used for the Sim performing the\n                pizza delivery.\n                '), ring_doorbell_state=RoleState.TunableReference(description='\n                The state for telling a Sim to go and ring the doorbell.  This\n                is the initial state.\n                '), no_front_door_state=RoleState.TunableReference(description='\n                The fallback state for when the delivery Sim cannot reach the\n                front door or no front door exists.\n                '), wait_to_deliver_state=RoleState.TunableReference(description='\n                The state for telling a Sim to wait for the other Sim to accept\n                the pizza delivery.\n                '), delivery_failure_state=RoleState.TunableReference(description='\n                The state that happens when the Sim has waited for the tuned\n                duration without anyone coming to accept the pizza.\n                '), leave_state=RoleState.TunableReference(description='\n                The state for the sim leaving.\n                '), tuning_group=GroupNames.SITUATION), 'delivery_completion_affordances': situations.situation_complex.TunableInteractionOfInterest(description='\n            Affordances whose completion signals that the delivery has taken place.\n            ', tuning_group=GroupNames.TRIGGERS), 'wait_for_customer_duration': sims4.tuning.tunable.TunableSimMinute(description='\n            The amount of time to wait for a Sim to accept the pizza delivery.\n            ', default=60, tuning_group=GroupNames.SITUATION), 'finish_job_notifications': TunableMapping(description='\n            Tune pairs of job finish role states with their notifications.\n            ', key_type=ServiceNpcEndWorkReason, value_type=TunableUiDialogNotificationSnippet(description='\n                Localized strings to display as notifications when this service\n                NPC finishes his/her work for the day for the matching finish\n                job reason. Parameter 0 is the funds deducted from the\n                household and parameter 1 is the amount added to bills, so you\n                can use {0.Money}, {0.Number}, {1.Money}, or {1.Number}.\n                '))}
    REMOVE_INSTANCE_TUNABLES = ('_buff', '_cost', '_NPC_host_filter', '_NPC_hosted_player_tests', 'NPC_hosted_situation_start_message', 'NPC_hosted_situation_use_player_sim_as_filter_requester', 'NPC_hosted_situation_player_job', 'venue_types', 'venue_invitation_message', 'venue_situation_player_job', 'category', 'main_goal', 'minor_goal_chains', '_level_data', '_display_name', 'max_participants', '_initiating_sim_tests', 'targeted_situation', '_resident_job', '_icon', 'situation_description')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._service_npc = None
        self._service_start_time = None
        reader = self._seed.custom_init_params_reader
        self._service_npc_type = services.service_npc_manager().get(reader.read_uint64('service_npc_type_id', 0))
        if self._service_npc_type is None:
            raise ValueError('Invalid service npc type for situation: {}'.format(self))
        self._hiring_household = services.household_manager().get(reader.read_uint64('household_id', 0))
        if self._hiring_household is None:
            raise ValueError('Invalid household for situation: {}'.format(self))
        self._object_definition_to_craft = reader.read_uint64('user_specified_data_id', 0)
        self._crafted_object_id = reader.read_uint64('crafted_object_id', 0)

    def _save_custom_situation(self, writer):
        super()._save_custom_situation(writer)
        writer.write_uint64('service_npc_type_id', self._service_npc_type.guid64)
        writer.write_uint64('household_id', self._hiring_household.id)
        writer.write_uint64('user_specified_data_id', self._object_definition_to_craft)
        writer.write_uint64('crafted_object_id', self._crafted_object_id)

    @staticmethod
    def _states():
        return [(2, _RingDoorBellState), (3, _NoFrontDoorState), (4, _WaitForCustomerState), (5, _LeaveState), (6, _DeliveryFailureState)]

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.pizza_delivery_job.situation_job, cls.pizza_delivery_job.ring_doorbell_state)]

    @classmethod
    def default_job(cls):
        return cls.pizza_delivery_job.situation_job

    def start_situation(self):
        super().start_situation()
        self._change_state(_RingDoorBellState())

    def _on_set_sim_job(self, sim, job_type):
        super()._on_set_sim_job(sim, job_type)
        self._service_npc = sim
        services.current_zone().service_npc_service.cancel_service(self._hiring_household, self._service_npc_type)

    def _on_remove_sim_from_situation(self, sim):
        super()._on_remove_sim_from_situation(sim)
        self._service_npc = None

    def _on_leaving_situation(self, end_work_reason):
        service_npc_type = self._service_npc_type
        household = self._hiring_household
        try:
            now = services.time_service().sim_now
            service_record = household.get_service_npc_record(service_npc_type.guid64)
            service_record.time_last_finished_service = now
            time_worked = now - (self._service_start_time or now)
            time_worked_in_hours = time_worked.in_hours()
            cost = service_npc_type.get_cost(time_worked_in_hours)
            if cost > 0:
                (paid_amount, billed_amount) = service_npc_type.try_charge_for_service(household, cost)
                end_work_reason = ServiceNpcEndWorkReason.NOT_PAID
            else:
                paid_amount = 0
                billed_amount = 0
            self._send_end_work_notification(end_work_reason, paid_amount, billed_amount)
        except Exception as e:
            logger.exception('Exception while executing _on_leaving_situation for situation {}', self, exc=e)

    def _send_end_work_notification(self, end_work_reason, *localization_args):
        notification = self.finish_job_notifications.get(end_work_reason)
        if notification is None:
            return
        for client in services.current_zone().client_manager.values():
            recipient = client.active_sim
            while recipient is not None:
                dialog = notification(recipient)
                dialog.show_dialog(additional_tokens=localization_args, icon_override=(None, self._service_npc))
                break

    @property
    def _should_cancel_leave_interaction_on_premature_removal(self):
        return True

sims4.tuning.instances.lock_instance_tunables(PizzaDeliverySituation, exclusivity=situations.bouncer.bouncer_types.BouncerExclusivityCategory.SERVICE, creation_ui_option=situations.situation_types.SituationCreationUIOption.NOT_AVAILABLE)

class _RingDoorBellState(SituationState):
    __qualname__ = '_RingDoorBellState'

    def __init__(self):
        super().__init__()
        self._interaction = None

    def on_activate(self, reader=None):
        logger.debug('Pizza delivery NPC is entering ring door bell state.')
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.pizza_delivery_job.situation_job, self.owner.pizza_delivery_job.ring_doorbell_state)

    def _on_set_sim_role_state(self, sim, job_type, role_state_type, role_affordance_target):
        super()._on_set_sim_role_state(sim, job_type, role_state_type, role_affordance_target)
        self._choose_and_run_interaction()

    def on_deactivate(self):
        if self._interaction is not None:
            self._interaction.unregister_on_finishing_callback(self._on_finishing_callback)
            self._interaction = None
        super().on_deactivate()

    def _choose_and_run_interaction(self):
        self._interaction = self.owner._choose_role_interaction(self.owner._service_npc, run_priority=interactions.priority.Priority.Low)
        if self._interaction is None:
            logger.debug("Pizza delivery NPC couldn't find interaction on front door.")
            self._change_state(_NoFrontDoorState())
            return
        execute_result = interactions.aop.AffordanceObjectPair.execute_interaction(self._interaction)
        if not execute_result:
            logger.debug('Pizza delivery NPC failed to execute interaction on front door.')
            self._interaction = None
            self._change_state(_NoFrontDoorState())
            return
        logger.debug('Pizza delivery NPC starting interaction on front door.')
        self._interaction.register_on_finishing_callback(self._on_finishing_callback)

    def _on_finishing_callback(self, interaction):
        if self._interaction is not interaction:
            return
        if interaction.uncanceled or interaction.was_initially_displaced:
            self._change_state(_WaitForCustomerState())
            return
        logger.debug('Pizza delivery NPC failed interaction on front door.')
        self._change_state(_NoFrontDoorState())

    def _get_role_state_overrides(self, sim, job_type, role_state_type, role_affordance_target):
        if self.owner._crafted_object_id != 0:
            target = services.current_zone().inventory_manager.get(self.owner._crafted_object_id)
        else:
            recipe = services.recipe_manager().get(self.owner._object_definition_to_craft)
            if recipe is None:
                raise ValueError('No recipe for {}'.format(self))
            target = DebugCreateCraftableInteraction.create_craftable(recipe, self.owner._service_npc, owning_household_id_override=self.owner._hiring_household.id, place_in_crafter_inventory=True)
            if target is None:
                raise ValueError('No craftable created for {} on {}'.format(recipe, self))
            self.owner._crafted_object_id = target.id
        return (role_state_type, target)

class _NoFrontDoorState(SituationState):
    __qualname__ = '_NoFrontDoorState'

    def __init__(self):
        super().__init__()
        self._interaction = None

    def on_activate(self, reader=None):
        logger.debug('Pizza delivery NPC is entering the no front door state.')
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.pizza_delivery_job.situation_job, self.owner.pizza_delivery_job.no_front_door_state)

    def on_deactivate(self):
        if self._interaction is not None:
            self._interaction.unregister_on_finishing_callback(self._on_finishing_callback)
            self._interaction = None
        super().on_deactivate()

    def _on_set_sim_role_state(self, *args, **kwargs):
        super()._on_set_sim_role_state(*args, **kwargs)
        self._choose_and_run_interaction()

    def _choose_and_run_interaction(self):
        self._interaction = self.owner._choose_role_interaction(self.owner._service_npc, run_priority=interactions.priority.Priority.Low, allow_failed_path_plans=True)
        if self._interaction is None:
            logger.debug("Pizza delivery NPC couldn't find the fallback behavior.")
            self._change_state(_DeliveryFailureState())
            return
        execute_result = interactions.aop.AffordanceObjectPair.execute_interaction(self._interaction)
        if not execute_result:
            logger.debug("Pizza delivery NPC couldn't do the fallback behavior.")
            self._change_state(_WaitForCustomerState())
            return
        logger.debug('Pizza delivery NPC doing the fallback behavior.')
        self._interaction.register_on_finishing_callback(self._on_finishing_callback)

    def _on_finishing_callback(self, interaction):
        if self._interaction is not interaction:
            return
        self._change_state(_WaitForCustomerState())

class _WaitForCustomerState(SituationState):
    __qualname__ = '_WaitForCustomerState'

    def __init__(self):
        super().__init__()
        self._timeout_handle = None

    def on_activate(self, reader=None):
        logger.debug('Pizza delivery NPC is entering wait state.')
        super().on_activate(reader)
        self.owner._service_start_time = services.time_service().sim_now
        self.owner._set_job_role_state(self.owner.pizza_delivery_job.situation_job, self.owner.pizza_delivery_job.wait_to_deliver_state)
        timeout = self.owner.wait_for_customer_duration
        self._timeout_handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(timeout), lambda _: self.timer_expired())
        self._test_event_register(TestEvent.InteractionComplete)

    def on_deactivate(self):
        if self._timeout_handle is not None:
            alarms.cancel_alarm(self._timeout_handle)
        super().on_deactivate()

    def handle_event(self, sim_info, event, resolver):
        if event == TestEvent.InteractionComplete and resolver(self.owner.delivery_completion_affordances) and sim_info is self.owner._service_npc.sim_info:
            self._change_state(_LeaveState(ServiceNpcEndWorkReason.FINISHED_WORK))

    def timer_expired(self):
        logger.debug('No one took the pizza delivery and the delivery Sim is sick of waiting.')
        self._change_state(_DeliveryFailureState())

class _DeliveryFailureState(SituationState):
    __qualname__ = '_DeliveryFailureState'

    def on_activate(self, reader=None):
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.pizza_delivery_job.situation_job, self.owner.pizza_delivery_job.delivery_failure_state)
        self._change_state(_LeaveState(ServiceNpcEndWorkReason.NO_WORK_TO_DO))

class _LeaveState(SituationState):
    __qualname__ = '_LeaveState'

    def __init__(self, leave_role_reason):
        super().__init__()
        self._leave_role_reason = leave_role_reason

    def on_activate(self, reader=None):
        logger.debug('Pizza delivery NPC is leaving.')
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.pizza_delivery_job.situation_job, self.owner.pizza_delivery_job.leave_state)
        if reader is None:
            self.owner._on_leaving_situation(self._leave_role_reason)

