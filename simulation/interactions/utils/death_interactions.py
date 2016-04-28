from event_testing.resolver import SingleSimResolver
from event_testing.results import TestResult
from interactions import ParticipantType
from interactions.base.interaction import RESERVATION_LIABILITY
from interactions.base.super_interaction import SuperInteraction
from interactions.constraints import ObjectJigConstraint
from interactions.interaction_finisher import FinishingType
from interactions.priority import Priority
from interactions.utils.creation import ObjectCreationElement
from interactions.utils.death import DeathType, is_death_enabled
from interactions.utils.outcome_enums import OutcomeResult
from objects import ALL_HIDDEN_REASONS
from objects.components import types
from sims4.localization import TunableLocalizedStringFactory
from sims4.localization.localization_tunables import LocalizedStringHouseholdNameSelector
from sims4.tuning.tunable import TunableEnumEntry
from ui.ui_dialog_generic import UiDialog
import build_buy
import element_utils
import services
import sims4.telemetry
import telemetry_helper
TELEMETRY_GROUP_DEATH = 'DEAD'
TELEMETRY_HOOK_SIM_DIES = 'SDIE'
TELEMETRY_DEATH_TYPE = 'dety'
death_telemetry_writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_DEATH)

class DeathElement(ObjectCreationElement):
    __qualname__ = 'DeathElement'
    FACTORY_TUNABLES = {'description': 'Have a participant in this interaction die.'}

    def __init__(self, interaction, *args, **kwargs):
        super().__init__(interaction, *args, **kwargs)
        self._on_lot_placement_failed = False
        self._interaction = interaction

    @property
    def placement_failed(self):
        return self._on_lot_placement_failed

    def _get_ignored_object_ids(self):
        jig_liability = self._interaction.get_liability(ObjectJigConstraint.JIG_CONSTRAINT_LIABILITY)
        if jig_liability is not None and jig_liability.jig is not None:
            return (jig_liability.jig.id, self._interaction.sim.id)
        return (self._interaction.sim.id,)

    def _place_object(self, created_object):
        if created_object is None:
            return False
        if not self._place_object_no_fallback(created_object):
            self._on_lot_placement_failed = True
        return True

    def _do_behavior(self, *args, **kwargs):
        if self.definition is not None:
            super()._do_behavior(*args, **kwargs)
        object_data = None if self._object_helper.is_object_none else (self._object_helper.object, self.placement_failed)
        self._interaction.run_death_behavior(death_object_data=object_data)

    def _build_outer_elements(self, sequence):
        if self.definition is None:
            return sequence
        return super()._build_outer_elements(sequence)

    def create_object(self):
        if self.definition is None:
            return
        return super().create_object()

class DeathSuperInteraction(SuperInteraction):
    __qualname__ = 'DeathSuperInteraction'
    INSTANCE_TUNABLES = {'death_element': DeathElement.TunableFactory(description='\n            Define what object is created by the dying Sim.\n            ', locked_args={'destroy_on_placement_failure': False}), 'death_subject': TunableEnumEntry(description='\n            The participant whose death will be occurring.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'death_type': TunableEnumEntry(description="\n            The subject's death type will be set to this value.\n            ", tunable_type=DeathType, default=DeathType.NONE), 'death_dialog': UiDialog.TunableFactory(description='\n            A dialog informing the Player that their last selectable Sim is\n            dead, prompting them to either save and quit, or quit.\n            ', text=LocalizedStringHouseholdNameSelector.TunableFactory()), 'save_lock_tooltip': TunableLocalizedStringFactory(description='\n            The tooltip/message to show when the player tries to save the game\n            while the death interaction is happening\n            ')}

    def __init__(self, *args, **kwargs):
        self._removed_sim = None
        self._client = None
        super().__init__(*args, **kwargs)
        self._priority = Priority.Critical
        self._run_priority = self._priority
        self._death_object_data = None
        self._has_completed_death = False
        self._has_finalized_death = False

    @classmethod
    def _test(cls, target, context, **kwargs):
        if not is_death_enabled():
            return TestResult(False, 'Death is disabled.')
        sim_info = context.sim.sim_info
        if sim_info.is_death_disabled():
            return TestResult(False, '{} is not allowed to die.', sim_info)
        return super()._test(target, context, **kwargs)

    @property
    def sim(self):
        if self._removed_sim is not None:
            return self._removed_sim
        return super().sim

    @property
    def should_die_on_transition_failure(self):
        return self.target is self.sim or self.target is None

    def on_added_to_queue(self, *args, **kwargs):
        services.get_persistence_service().lock_save(self)
        return super().on_added_to_queue(*args, **kwargs)

    def _exited_pipeline(self, *args, **kwargs):
        try:
            should_die_on_transition_failure = self.should_die_on_transition_failure
            super()._exited_pipeline(*args, **kwargs)
        finally:
            try:
                if not should_die_on_transition_failure and self.finishing_type == FinishingType.TRANSITION_FAILURE:
                    return
                while self.outcome_result != OutcomeResult.SUCCESS:
                    self.run_death_behavior(from_reset=True)
            finally:
                services.get_persistence_service().unlock_save(self)

    def build_outcome(self, *args, **kwargs):
        outcome_sequence = super().build_outcome(*args, **kwargs)

        def _do(timeline):
            nonlocal outcome_sequence
            self.outcome.decide(self)
            if self.outcome_result == OutcomeResult.FAILURE:
                outcome_sequence = self.death_element(self, sequence=outcome_sequence)
            result = yield element_utils.run_child(timeline, outcome_sequence)
            return result

        return (_do,)

    def run_death_behavior(self, death_object_data=None, from_reset=False):
        if self._death_object_data is not None:
            return
        if death_object_data is None:
            death_element = self.death_element(self)
            death_object_data = (death_element.create_object(), death_element.placement_failed)
        self._death_object_data = death_object_data
        self.sim.sim_info.career_tracker.on_death()
        self.sim.inventory_component.push_items_to_household_inventory()
        with telemetry_helper.begin_hook(death_telemetry_writer, TELEMETRY_HOOK_SIM_DIES, sim=self.sim.sim_info) as hook:
            hook.write_int(TELEMETRY_DEATH_TYPE, self.death_type)
        for si in list(self.sim.interaction_refs):
            si.refresh_conditional_actions()
            si.set_target(None)
            si.remove_liability(RESERVATION_LIABILITY)
        self.sim.remove_from_client()
        self._removed_sim = self.sim
        self._client = self.sim.client
        if from_reset:
            self._finalize_death()
            self.sim.schedule_destroy_asap(source=self.sim, cause='Sim reset during death.')
        else:
            self.add_exit_function(self.run_post_death_behavior)

    def _finalize_death(self):
        if self._has_finalized_death:
            return
        self._has_finalized_death = True
        sim_info = self.sim.sim_info
        current_household = sim_info.household
        death_object = self._death_object_data[0]
        if death_object is not None:
            death_object.add_dynamic_component(types.STORED_SIM_INFO_COMPONENT.instance_attr, sim_id=sim_info.id)
            death_object.update_object_tooltip()
            death_object.set_household_owner_id(sim_info.household.id)
            if self._death_object_data[1]:
                build_buy.move_object_to_household_inventory(death_object)
        death_tracker = sim_info.death_tracker
        death_tracker.set_death_type(self.death_type)
        if self._client is not None:
            self._client.set_next_sim_or_none(only_if_this_active_sim_info=sim_info)
            self._client.selectable_sims.remove_selectable_sim_info(sim_info)
            if not any(sim.is_teen_or_older for sim in self._client.selectable_sims):
                self._show_death_dialog()
                persistence_service = services.get_persistence_service()
                sim_info_manager = services.sim_info_manager()
                for selectable_sim_info in self._client.selectable_sims:
                    sim_id = selectable_sim_info.id
                    sim_to_destroy = selectable_sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
                    if sim_to_destroy is not None:
                        sim_to_destroy.destroy(source=sim_to_destroy, cause='Last adult sim dieing, destroying dependent sims.')
                    persistence_service.del_sim_proto_buff(sim_id)
                    sim_info_manager.remove_permanently(selectable_sim_info)
                self._client.clear_selectable_sims()
                zone_id = services.current_zone_id()
                current_household.clear_household_lot_ownership(zone_id)
                current_household.hidden = True
                fire_service = services.get_fire_service()
                if fire_service is not None:
                    fire_service.kill()

    def run_post_death_behavior(self):
        if self._has_completed_death:
            return
        self._has_completed_death = True
        self.sim.schedule_destroy_asap(post_delete_func=self._finalize_death, source=self.sim, cause='Sim died.')

    def _show_death_dialog(self):
        if self._client is not None:
            dialog = self.death_dialog(self.sim, text=lambda *args, **kwargs: self.death_dialog.text(household=self._client.household, *args, **kwargs), resolver=SingleSimResolver(self.sim))
            dialog.show_dialog()

    def get_lock_save_reason(self):
        return self.create_localized_string(self.save_lock_tooltip)

