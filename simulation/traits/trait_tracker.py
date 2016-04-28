from event_testing import test_events
from interactions.base.picker_interaction import PickerSuperInteraction
from protocolbuffers import SimObjectAttributes_pb2 as protocols
from sims4 import commands
from sims4.tuning.tunable import Tunable
from sims4.utils import flexmethod
from traits.traits import logger, Trait
from ui.ui_dialog_picker import ObjectPickerRow
import services.social_service
import sims4.telemetry
import telemetry_helper
TELEMETRY_GROUP_TRAITS = 'TRAT'
TELEMETRY_HOOK_ADD_TRAIT = 'TADD'
TELEMETRY_HOOK_REMOVE_TRAIT = 'TRMV'
TELEMETRY_FIELD_TRAIT_ID = 'idtr'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_TRAITS)

class TraitTrackerSimInfo:
    __qualname__ = 'TraitTrackerSimInfo'

    def __init__(self, sim_info):
        self._sim_info = sim_info
        self._equipped_traits = set()
        self._unlocked_equip_slot = 0
        self._buff_handles = {}

    def __iter__(self):
        return self._equipped_traits.__iter__()

    def __len__(self):
        return len(self._equipped_traits)

    def can_add_trait(self, trait, display_warn=True):
        if self.has_trait(trait):
            if display_warn:
                logger.warn('Trying to equip an existing trait {} for Sim {}', trait, self._sim_info)
            return False
        if self.empty_slot_number == 0 and trait.is_personality_trait:
            if display_warn:
                logger.warn('Reach max equipment slot number {} for Sim {}', self.equip_slot_number, self._sim_info)
            return False
        if not trait.test_sim_info(self._sim_info):
            if display_warn:
                logger.warn("Trying to equip a trait {} that conflicts with Sim {}'s age {} or gender {}", trait, self._sim_info, self._sim_info.age, self._sim_info.gender)
            return False
        if self.is_conflicting(trait):
            if display_warn:
                logger.warn('Trying to equip a conflicting trait {} for Sim {}', trait, self._sim_info)
            return False
        return True

    def add_trait(self, trait):
        if not self.can_add_trait(trait):
            return False
        self._equipped_traits.add(trait)
        self._add_buffs(trait)
        self._sim_info.resend_trait_ids()
        sim = self._sim_info.get_sim_instance()
        if sim is not None:
            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_ADD_TRAIT, sim=sim) as hook:
                hook.write_int(TELEMETRY_FIELD_TRAIT_ID, trait.guid64)
            services.social_service.post_trait_message(self._sim_info, trait, added=True)
            services.get_event_manager().process_event(test_events.TestEvent.TraitAddEvent, sim_info=self._sim_info)
        return True

    def remove_trait(self, trait):
        if not self.has_trait(trait):
            logger.warn('Try to remove a non-equipped trait {}', trait)
            return False
        self._equipped_traits.remove(trait)
        self._remove_buffs(trait)
        self._sim_info.resend_trait_ids()
        sim = self._sim_info.get_sim_instance()
        if sim is not None:
            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_REMOVE_TRAIT, sim=sim) as hook:
                hook.write_int(TELEMETRY_FIELD_TRAIT_ID, trait.guid64)
            services.social_service.post_trait_message(self._sim_info, trait, added=False)
        return True

    def clear_traits(self):
        for trait in list(self._equipped_traits):
            self.remove_trait(trait)

    def has_trait(self, trait):
        return trait in self._equipped_traits

    def has_any_trait(self, traits):
        return any(t in traits for t in self._equipped_traits)

    def is_conflicting(self, trait):
        return any(t.is_conflicting(trait) for t in self._equipped_traits)

    @property
    def personality_traits(self):
        personality_traits = set()
        for trait in self:
            while trait.is_personality_trait:
                personality_traits.add(trait)
        return personality_traits

    @property
    def trait_ids(self):
        return list(t.guid64 for t in self._equipped_traits)

    @property
    def equipped_traits(self):
        return self._equipped_traits

    @property
    def equip_slot_number(self):
        equip_slot_number_map = Trait.EQUIP_SLOT_NUMBER_MAP
        age = self._sim_info.age
        slot_number = self._unlocked_equip_slot
        if age in equip_slot_number_map:
            slot_number += equip_slot_number_map[age]
        else:
            logger.warn('Trait.EQUIP_SLOT_NUMBER_MAP missing tuning for age {}', age)
        return slot_number

    @property
    def empty_slot_number(self):
        equipped_personality_traits = [trait for trait in self if trait.is_personality_trait]
        empty_slot_number = self.equip_slot_number - len(equipped_personality_traits)
        return max(empty_slot_number, 0)

    def _add_buffs(self, trait):
        buffs = trait.buffs
        buff_handles = []
        for buff in buffs:
            buff_handle = self._sim_info.add_buff(buff.buff_type, buff_reason=buff.buff_reason)
            buff_handles.append(buff_handle)
        if buff_handles:
            self._buff_handles[trait.guid64] = buff_handles

    def _remove_buffs(self, trait):
        buff_handles = self._buff_handles.get(trait.guid64, None)
        if buff_handles is not None:
            for buff_handle in buff_handles:
                self._sim_info.remove_buff(buff_handle)
            del self._buff_handles[trait.guid64]

    def save(self):
        data = protocols.PersistableTraitTracker()
        data.trait_ids.extend(self.trait_ids)
        return data

    def load(self, data):
        trait_manager = services.get_instance_manager(sims4.resources.Types.TRAIT)
        for trait_instance_id in data.trait_ids:
            trait = trait_manager.get(trait_instance_id)
            while trait is not None:
                self._equipped_traits.add(trait)
                self._add_buffs(trait)

class TraitPickerSuperInteraction(PickerSuperInteraction):
    __qualname__ = 'TraitPickerSuperInteraction'
    INSTANCE_TUNABLES = {'is_add': Tunable(description='\n                If this interaction is trying to add a trait to the sim or to\n                remove a trait from the sim.', tunable_type=bool, default=True)}

    def _run_interaction_gen(self, timeline):
        self._show_picker_dialog(self.sim, target_sim=self.sim)
        return True

    @classmethod
    def _trait_selection_gen(cls, target):
        trait_manager = services.get_instance_manager(sims4.resources.Types.TRAIT)
        trait_tracker = target.sim_info.trait_tracker
        if cls.is_add:
            for trait in trait_manager.types.values():
                while not trait_tracker.has_trait(trait):
                    yield trait
        else:
            for trait in trait_tracker.equipped_traits:
                yield trait

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        trait_tracker = target.sim_info.trait_tracker
        for trait in cls._trait_selection_gen(target):
            row = ObjectPickerRow(is_enable=not trait_tracker.is_conflicting(trait), name=trait.display_name(target), icon=trait.icon, row_description=trait.trait_description, tag=trait)
            yield row

    def on_choice_selected(self, choice_tag, **kwargs):
        trait = choice_tag
        trait_tracker = self.target.sim_info.trait_tracker
        if trait is not None:
            if self.is_add:
                trait_tracker.add_trait(trait)
            else:
                trait_tracker.remove_trait(trait)

