from filters.sim_filter_service import SimFilterGlobalBlacklistReason, SIM_FILTER_GLOBAL_BLACKLIST_LIABILITY, SimFilterGlobalBlacklistLiability
from filters.tunable import TunableSimFilter
from interactions import ParticipantType
from interactions.base.picker_interaction import PickerSuperInteractionMixin
from interactions.base.picker_strategy import SimPickerEnumerationStrategy
from interactions.base.super_interaction import SuperInteraction
from interactions.interaction_finisher import FinishingType
from interactions.liability import Liability
from interactions.utils.payment import PaymentLiability
from interactions.utils.pregnancy import PregnancyTracker
from interactions.utils.pregnancy_interactions import NameOffspringSuperInteractionMixin
from interactions.utils.tunable import TunableContinuation
from objects import ALL_HIDDEN_REASONS
from sims.baby import assign_bassinet_for_baby, create_and_place_baby
from sims.genealogy_tracker import FamilyRelationshipIndex
from sims.sim_dialogs import SimPersonalityAssignmentDialog
from sims.sim_info_types import Age
from sims.sim_spawner import SimSpawner
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import TunableList, TunableTuple, TunableRange, TunableReference
from sims4.tuning.tunable_base import GroupNames
from sims4.utils import flexmethod
from ui.ui_dialog import PhoneRingType
from ui.ui_dialog_generic import TEXT_INPUT_FIRST_NAME, TEXT_INPUT_LAST_NAME
from ui.ui_dialog_picker import TunablePickerDialogVariant, ObjectPickerTuningFlags, SimPickerRow
import element_utils
import interactions
import services
import sims4.log
logger = sims4.log.Logger('adoption')
ADOPTION_LIABILTIY = 'AdoptionLiability'

class AdoptionLiability(Liability):
    __qualname__ = 'AdoptionLiability'

    def __init__(self):
        self._household = None
        self._sim_id = None

    def on_add(self, interaction):
        sim = interaction.sim
        self._household = sim.household
        self._sim_id = sim.id
        self._household.add_adopting_sim(self._sim_id)

    def release(self):
        self._household.remove_adopting_sim(self._sim_id)

class AdoptionPickerInteraction(SuperInteraction, PickerSuperInteractionMixin):
    __qualname__ = 'AdoptionPickerInteraction'
    INSTANCE_TUNABLES = {'picker_dialog': TunablePickerDialogVariant(description='\n                Sim Picker Dialog\n                ', available_picker_flags=ObjectPickerTuningFlags.SIM, tuning_group=GroupNames.PICKERTUNING), 'sim_filters': TunableList(description="\n                A list of tuples of number of sims to find and filter to find\n                them.  If there aren't enough sims to be found from a filter\n                then the filter is used to create the sims.  Sims that are\n                found from one filter are placed into the black list for\n                running the next filter in order to make sure that sims don't\n                double dip creating one filter to the next.\n                ", tunable=TunableTuple(number_of_sims=TunableRange(description='\n                        The number of sims to find using the filter.  If no\n                        sims are found then sims will be created to fit the\n                        filter.\n                        ', tunable_type=int, default=1, minimum=1), filter=TunableSimFilter.TunableReference(description='\n                        Sim filter that is used to create find the number of\n                        sims that we need for this filter request.\n                        '), description='\n                    Tuple of number of sims that we want to find and filter\n                    that will be used to find them.\n                    '), tuning_group=GroupNames.PICKERTUNING), 'actor_continuation': TunableContinuation(description='\n                A continuation that is pushed when the acting sim is selected.\n                ', locked_args={'actor': ParticipantType.Actor}, tuning_group=GroupNames.PICKERTUNING)}

    def __init__(self, *args, **kwargs):
        super().__init__(choice_enumeration_strategy=SimPickerEnumerationStrategy(), *args, **kwargs)
        self._picked_sim_id = None
        self.sim_ids = []

    def _run_interaction_gen(self, timeline):
        yield self._get_valid_choices_gen(timeline)
        self._show_picker_dialog(self.sim, target_sim=self.sim, target=self.target)
        yield element_utils.run_child(timeline, element_utils.soft_sleep_forever())
        if self._picked_sim_id is None:
            self.remove_liability(PaymentLiability.LIABILITY_TOKEN)
            return False
        picked_item_set = {self._picked_sim_id}
        self.interaction_parameters['picked_item_ids'] = frozenset(picked_item_set)
        self.push_tunable_continuation(self.actor_continuation, picked_item_ids=picked_item_set)
        return True

    def _get_valid_choices_gen(self, timeline):
        self.sim_ids = []
        requesting_sim_info = self.sim.sim_info
        blacklist = {sim_info.id for sim_info in services.sim_info_manager().instanced_sims_gen(allow_hidden_flags=ALL_HIDDEN_REASONS)}
        for sim_filter in self.sim_filters:
            for _ in range(sim_filter.number_of_sims):
                sim_infos = services.sim_filter_service().submit_matching_filter(1, sim_filter.filter, None, blacklist_sim_ids=blacklist, requesting_sim_info=requesting_sim_info, allow_yielding=False, zone_id=0)
                for sim_info in sim_infos:
                    self.sim_ids.append(sim_info.id)
                    blacklist.add(sim_info.id)
                yield element_utils.run_child(timeline, element_utils.sleep_until_next_tick_element())

    @flexmethod
    def create_row(cls, inst, tag):
        return SimPickerRow(sim_id=tag, tag=tag)

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        if inst is not None:
            for sim_id in inst.sim_ids:
                logger.info('AdoptionPicker: add sim_id:{}', sim_id)
                row = inst.create_row(sim_id)
                yield row

    def _pre_perform(self, *args, **kwargs):
        if self.sim.household.free_slot_count == 0:
            self.cancel(FinishingType.FAILED_TESTS, cancel_reason_msg="There aren't any free household slots.")
            return
        self.add_liability(ADOPTION_LIABILTIY, AdoptionLiability())
        return super()._pre_perform(*args, **kwargs)

    def on_choice_selected(self, choice_tag, **kwargs):
        sim_id = choice_tag
        if sim_id is not None:
            self._picked_sim_id = sim_id
            self.add_liability(SIM_FILTER_GLOBAL_BLACKLIST_LIABILITY, SimFilterGlobalBlacklistLiability((sim_id,), SimFilterGlobalBlacklistReason.ADOPTION))
        self.trigger_soft_stop()

lock_instance_tunables(AdoptionPickerInteraction, pie_menu_option=None)

class AdoptionInteraction(SuperInteraction, NameOffspringSuperInteractionMixin):
    __qualname__ = 'AdoptionInteraction'
    INSTANCE_TUNABLES = {'dialog': SimPersonalityAssignmentDialog.TunableFactory(description="\n                The dialog that is displayed (and asks for the user to enter a first\n                name and last name) before assigning the sim to your household.\n                \n                An additional token is passed in: the adopted Sim's data.\n                ", text_inputs=(TEXT_INPUT_FIRST_NAME, TEXT_INPUT_LAST_NAME), locked_args={'phone_ring_type': PhoneRingType.NO_RING}), 'adoption_trait': TunableReference(description='\n                Trait that represents the sim being considered adoptable.  The\n                trait will be removed from the sim being adopted upon adoption\n                being completed.\n                ', manager=services.get_instance_manager(sims4.resources.Types.TRAIT))}

    def _pre_perform(self, *args, **kwargs):
        self.add_liability(interactions.rabbit_hole.RABBIT_HOLE_LIABILTIY, interactions.rabbit_hole.RabbitHoleLiability())
        return super()._pre_perform(*args, **kwargs)

    def _build_outcome_sequence(self, *args, **kwargs):
        sequence = super()._build_outcome_sequence(*args, **kwargs)
        return element_utils.build_critical_section(self._name_and_create_adoptee_gen, sequence)

    def _get_name_dialog(self):
        adopted_sim_info = self.get_participant(ParticipantType.PickedSim)
        return self.dialog(self.sim, assignment_sim_info=adopted_sim_info, resolver=self.get_resolver())

    def _name_and_create_adoptee_gen(self, timeline):
        adopted_sim_info = self.get_participant(ParticipantType.PickedSim)
        last_name = SimSpawner.get_family_name_for_gender(self.sim.account, self.sim.last_name, adopted_sim_info.is_female)
        result = yield self._do_renames_gen(timeline, (adopted_sim_info,), additional_tokens=(last_name,))
        if not result:
            return result
        adopted_sim_info = self.get_participant(ParticipantType.PickedSim)
        parent_a = self.sim.sim_info
        parent_b = services.sim_info_manager().get(parent_a.spouse_sim_id)
        adopted_sim_info.relationship_tracker._clear_relationships()
        for relation in FamilyRelationshipIndex:
            relation_id = adopted_sim_info.get_relation(relation)
            relation_info = services.sim_info_manager().get(relation_id)
            if relation_info is not None:
                adopted_sim_info.genealogy.remove_family_link(relation)
                family_relation = relation_info.genealogy.get_family_relationship_bit(adopted_sim_info.sim_id)
                relation_info.genealogy.clear_family_relation(family_relation)
                relation_info.relationship_tracker.destroy_relationship(adopted_sim_info.sim_id)
            adopted_sim_info.genealogy.clear_family_relation(relation)
        if adopted_sim_info.household is not parent_a.household:
            adopted_sim_info.household.remove_sim_info(adopted_sim_info)
        PregnancyTracker.initialize_sim_info(adopted_sim_info, parent_a, parent_b)
        adopted_sim_info.trait_tracker.remove_trait(self.adoption_trait)
        if adopted_sim_info.age == Age.BABY:
            adopted_sim_info.set_zone_on_spawn()
            create_and_place_baby(adopted_sim_info, ignore_daycare=True)
        else:
            SimSpawner.spawn_sim(adopted_sim_info, sim_position=self.sim.position)
        return True

