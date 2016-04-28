from event_testing.resolver import SingleSimResolver
from interactions.base.interaction import CancelInteractionsOnExitLiability, CANCEL_INTERACTION_ON_EXIT_LIABILITY, InteractionQueuePreparationStatus
from interactions.base.super_interaction import SuperInteraction
from interactions.interaction_finisher import FinishingType
from interactions.utils.pregnancy import PregnancyTracker
from interactions.utils.tunable import SaveLockLiability
from sims.baby import create_and_place_baby, assign_bassinet_for_baby
from sims.sim_info import SimInfo
from sims4.tuning.tunable import TunableReference
from ui.ui_dialog import UiDialogOkCancel
from ui.ui_dialog_element import UiDialogElement
from ui.ui_dialog_generic import TEXT_INPUT_FIRST_NAME, TEXT_INPUT_LAST_NAME
from world.travel_tuning import TravelSimLiability, TRAVEL_SIM_LIABILITY
import element_utils
import elements
import interactions
import services

class RenameDialogElement(elements.ParentElement):
    __qualname__ = 'RenameDialogElement'

    def __init__(self, dialog, offspring_index, offspring_data, additional_tokens=()):
        super().__init__()
        self._dialog = dialog
        self._offspring_index = offspring_index
        self._offspring_data = offspring_data
        self._additional_tokens = additional_tokens
        self._result = None
        self.sleep_element = None

    def _on_response(self, dialog):
        if self._dialog is None:
            return
        first_name = dialog.text_input_responses.get(TEXT_INPUT_FIRST_NAME)
        last_name = dialog.text_input_responses.get(TEXT_INPUT_LAST_NAME) or self._offspring_data.last_name
        if not first_name or not last_name:
            self._result = False
            self.sleep_element.trigger_soft_stop()
            return
        self._offspring_data.first_name = first_name
        self._offspring_data.last_name = last_name
        self._result = True
        self.sleep_element.trigger_soft_stop()

    def _run(self, timeline):
        additional_tokens = (self._offspring_data,) + self._additional_tokens
        if isinstance(self._offspring_data, SimInfo):
            trait_overrides_for_baby = None
            gender_overrides_for_baby = None
        else:
            trait_overrides_for_baby = self._offspring_data.traits
            gender_overrides_for_baby = self._offspring_data.gender
        self._dialog.show_dialog(self._on_response, additional_tokens=additional_tokens, trait_overrides_for_baby=trait_overrides_for_baby, gender_overrides_for_baby=gender_overrides_for_baby)
        if self._result is None:
            self.sleep_element = element_utils.soft_sleep_forever()
            return timeline.run_child(self.sleep_element)
        return self._result

    def _resume(self, timeline, child_result):
        if self._result is not None:
            return self._result
        return False

    def _hard_stop(self):
        super()._hard_stop()
        if self._dialog is not None:
            services.ui_dialog_service().dialog_cancel(self._dialog.dialog_id)
            self._dialog = None

    def _soft_stop(self):
        super()._soft_stop()
        self._dialog = None

class NameOffspringSuperInteractionMixin:
    __qualname__ = 'NameOffspringSuperInteractionMixin'

    def _get_name_dialog(self):
        raise NotImplementedError

    def _do_renames_gen(self, timeline, all_offspring, additional_tokens=()):
        offspring_index = 0
        while offspring_index < len(all_offspring):
            offspring_data = all_offspring[offspring_index]
            dialog = self._get_name_dialog()
            rename_element = RenameDialogElement(dialog, offspring_index, offspring_data, additional_tokens=additional_tokens)
            result = yield element_utils.run_child(timeline, rename_element)
            if not result:
                self.cancel(FinishingType.DIALOG, cancel_reason_msg='Time out or missing first/last name')
                return False
            offspring_index += 1
        return True

class DeliverBabySuperInteraction(SuperInteraction, NameOffspringSuperInteractionMixin):
    __qualname__ = 'DeliverBabySuperInteraction'

    def _get_name_dialog(self):
        return PregnancyTracker.PREGNANCY_DIALOG(self.sim, resolver=SingleSimResolver(self.sim))

    def _build_outcome_sequence(self, *args, **kwargs):
        sequence = super()._build_outcome_sequence(*args, **kwargs)
        pregnancy_tracker = self.sim.sim_info.pregnancy_tracker
        return element_utils.must_run(element_utils.build_critical_section_with_finally(self._name_and_create_babies_gen, sequence, lambda _: pregnancy_tracker.clear_pregnancy()))

    def _name_and_create_babies_gen(self, timeline):
        pregnancy_tracker = self.sim.sim_info.pregnancy_tracker
        if not pregnancy_tracker.is_pregnant:
            return False
        pregnancy_tracker.create_offspring_data()
        result = yield self._do_renames_gen(timeline, list(pregnancy_tracker.get_offspring_data_gen()))
        if not result:
            return result
        result = yield self._complete_pregnancy_gen(timeline, pregnancy_tracker)
        return result

    def _complete_pregnancy_gen(self, timeline, pregnancy_tracker):
        offspring_data_list = list(pregnancy_tracker.get_offspring_data_gen())
        offspring_data = offspring_data_list[0]
        sim_info = pregnancy_tracker.create_sim_info(offspring_data)
        from sims.baby import set_baby_sim_info_with_switch_id
        new_target = set_baby_sim_info_with_switch_id(self.target, sim_info)
        animation_context = self.animation_context
        if animation_context is not None:
            for asm in animation_context.get_asms_gen():
                actor_name = asm.get_actor_name_from_id(self.target.id)
                while actor_name is not None:
                    asm.set_actor(actor_name, None)
                    asm.set_actor(actor_name, new_target)
        self.target.transient = True
        self.set_target(new_target)
        if animation_context is not None:

            def on_show_baby(_):
                new_target.enable_baby_state()
                show_baby_event_handler.release()

            new_target.empty_baby_state()
            show_baby_event_handler = animation_context.register_event_handler(on_show_baby, handler_id=100)

            def on_hide_belly(_):
                pregnancy_tracker.clear_pregnancy_visuals()
                hide_belly_event_handler.release()

            hide_belly_event_handler = animation_context.register_event_handler(on_hide_belly, handler_id=101)
        for offspring_data in offspring_data_list[1:]:
            sim_info = pregnancy_tracker.create_sim_info(offspring_data)
            while not assign_bassinet_for_baby(sim_info):
                create_and_place_baby(sim_info)
        pregnancy_tracker.complete_pregnancy()
        return True

class HaveBabyAtHospitalInteraction(DeliverBabySuperInteraction):
    __qualname__ = 'HaveBabyAtHospitalInteraction'
    INSTANCE_TUNABLES = {'partner_affordance': TunableReference(description='\n             When the Pregnant Sim leaves the lot to give birth, this is the affordance \n             that will get pushed on the other Sim involved with the pregnancy if\n             there is one and the Sim is on lot.\n             ', manager=services.affordance_manager()), 'off_lot_birth_dialog': UiDialogOkCancel.TunableFactory(description='\n            This dialog informs the player that the babies are on the home lot\n            and they can follow the birthing Sim to their home lot. We always\n            display this, even if the birthing Sim is not the last selectable\n            one on the lot.\n            ')}

    def _pre_perform(self, *args, **kwargs):
        self.add_liability(interactions.rabbit_hole.RABBIT_HOLE_LIABILTIY, interactions.rabbit_hole.RabbitHoleLiability())
        return super()._pre_perform(*args, **kwargs)

    def _complete_pregnancy_gen(self, timeline, pregnancy_tracker):
        is_off_lot_birth = False
        for offspring_data in pregnancy_tracker.get_offspring_data_gen():
            sim_info = pregnancy_tracker.create_sim_info(offspring_data)
            current_zone = services.current_zone()
            if current_zone.id == sim_info.zone_id:
                create_and_place_baby(sim_info, ignore_daycare=True)
            else:
                is_off_lot_birth = True
        offspring_count = pregnancy_tracker.offspring_count
        pregnancy_tracker.complete_pregnancy()
        pregnancy_tracker.clear_pregnancy()
        if is_off_lot_birth:
            travel_liability = TravelSimLiability(self, self.sim.sim_info, self.sim.sim_info.household.home_zone_id, expecting_dialog_response=True)
            self.add_liability(TRAVEL_SIM_LIABILITY, travel_liability)

            def on_travel_dialog_response(dialog):
                if dialog.accepted:
                    save_lock_liability = self.get_liability(SaveLockLiability.LIABILITY_TOKEN)
                    if save_lock_liability is not None:
                        save_lock_liability.release()
                    travel_liability.travel_dialog_response(dialog)

            travel_dialog_element = UiDialogElement(self.sim, self.get_resolver(), dialog=self.off_lot_birth_dialog, on_response=on_travel_dialog_response, additional_tokens=(offspring_count,))
            result = yield element_utils.run_child(timeline, travel_dialog_element)
            return result
        return True

    def prepare_gen(self, timeline, *args, **kwargs):
        result = yield super().prepare_gen(timeline, *args, **kwargs)
        if result != InteractionQueuePreparationStatus.FAILURE:
            self._push_spouse_to_hospital()
        return result

    def _push_spouse_to_hospital(self):
        pregnancy_tracker = self.sim.sim_info.pregnancy_tracker
        sim_info = None
        (parent_a, parent_b) = pregnancy_tracker.get_parents()
        if parent_a is not None and parent_b is not None:
            if parent_a.sim_id == self.sim.sim_id:
                sim_info = parent_b
            else:
                sim_info = parent_a
        if sim_info is None:
            return
        sim = sim_info.get_sim_instance()
        if sim is None:
            return
        if sim.queue.has_duplicate_super_affordance(self.partner_affordance, sim, None):
            return
        context = interactions.context.InteractionContext(sim, interactions.context.InteractionContext.SOURCE_SCRIPT, interactions.priority.Priority.High)
        result = sim.push_super_affordance(self.partner_affordance, sim, context)
        if result:
            interaction = result.interaction
            interaction.add_liability(interactions.rabbit_hole.RABBIT_HOLE_LIABILTIY, interactions.rabbit_hole.RabbitHoleLiability())
            liability = CancelInteractionsOnExitLiability()
            self.add_liability(CANCEL_INTERACTION_ON_EXIT_LIABILITY, liability)
            liability.add_cancel_entry(parent_b, interaction)
        return result

