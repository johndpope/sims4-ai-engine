import collections
import random
import weakref
from distributor.rollback import ProtocolBufferRollback
from element_utils import build_critical_section, build_critical_section_with_finally
from event_testing.tests import TunableTestSet
from interactions import ParticipantType
from interactions.utils.animation import create_run_animation, flush_all_animations
from objects import ALL_HIDDEN_REASONS
from protocolbuffers import FileSerialization_pb2 as serialization
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.dynamic_enum import DynamicEnum
from sims4.tuning.tunable import Tunable, TunableResourceKey, TunableMapping, TunableTuple, TunableList, TunableEnumEntry, OptionalTunable, TunableVariant, AutoFactoryInit, TunableSet, HasTunableSingletonFactory, HasTunableFactory, TunableEnumFlags, TunableReference
from singletons import DEFAULT
from tag import Tag
import animation
import animation.arb
import animation.asm
import element_utils
import elements
import enum
import services
import sims4.log
logger = sims4.log.Logger('SimOutfits')

class OutfitCategory(enum.Int):
    __qualname__ = 'OutfitCategory'
    EVERYDAY = 0
    FORMAL = 1
    ATHLETIC = 2
    SLEEP = 3
    PARTY = 4
    BATHING = 5
    CAREER = 6
    SITUATION = 7
    SPECIAL = 8

class OutfitChangeReason(DynamicEnum):
    __qualname__ = 'OutfitChangeReason'
    Invalid = -1
    PreviousClothing = 0
    DefaultOutfit = 1
    RandomOutfit = 2
    ExitBedNPC = 3

class DefaultOutfitPriority(DynamicEnum):
    __qualname__ = 'DefaultOutfitPriority'
    NoPriority = 0

class ForcedOutfitChanges:
    __qualname__ = 'ForcedOutfitChanges'
    INAPPROPRIATE_STREETWEAR = TunableList(description='\n        A list of outfit categories inappropriate for wearing on open streets.\n        If the Sim is in one of these categories when they first decided to go\n        off-lot, they will switch out of it beforehand.\n        ', tunable=TunableEnumEntry(tunable_type=OutfitCategory, default=OutfitCategory.EVERYDAY))

class ClothingChangeTunables:
    __qualname__ = 'ClothingChangeTunables'
    DEFAULT_ACTOR = 'x'
    clothing_change_state = Tunable(str, 'ClothesChange', description='State in the clothing_change_asm that runs clothing_change animation.')
    clothing_change_asm = TunableResourceKey(None, resource_types=[sims4.resources.Types.STATEMACHINE], description='ASM used for the clothing change.')
    clothing_reasons_to_outfits = TunableMapping(key_type=OutfitChangeReason, value_type=TunableList(TunableTuple(tests=TunableTestSet(), outfit_category=TunableEnumEntry(OutfitCategory, OutfitCategory.EVERYDAY, description='On Reason, Change Directly to Outfit')), description='List of tunable mappings of change reason to outfit change.'), key_name='OutfitChangeReason', value_name='TunableMappings')

OutfitPriority = collections.namedtuple('OutfitPriority', ['change_reason', 'priority', 'interaction_ref'])

class OutfitChangeBase(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'OutfitChangeBase'

    def __bool__(self):
        return True

    def get_on_entry_change(self, interaction, **kwargs):
        raise NotImplementedError

    def get_on_exit_change(self, interaction, **kwargs):
        raise NotImplementedError

    def get_on_entry_outfit(self, interaction, **kwargs):
        raise NotImplementedError

    def get_on_exit_outfit(self, interaction, **kwargs):
        raise NotImplementedError

class TunableOutfitChange(TunableVariant):
    __qualname__ = 'TunableOutfitChange'

    class _OutfitChangeNone(OutfitChangeBase):
        __qualname__ = 'TunableOutfitChange._OutfitChangeNone'

        def __bool__(self):
            return False

        def get_on_entry_change(self, interaction, **kwargs):
            pass

        def get_on_exit_change(self, interaction, **kwargs):
            pass

        def get_on_entry_outfit(self, interaction, **kwargs):
            pass

        def get_on_exit_outfit(self, interaction, **kwargs):
            pass

    class _OutfitChangeForReason(OutfitChangeBase):
        __qualname__ = 'TunableOutfitChange._OutfitChangeForReason'
        FACTORY_TUNABLES = {'description': '\n                Define individual outfit changes at the start and end of this\n                posture.\n                ', 'on_entry': OptionalTunable(description='\n                When enabled, define the change reason to apply on posture\n                entry.\n                ', tunable=TunableEnumEntry(tunable_type=OutfitChangeReason, default=OutfitChangeReason.Invalid)), 'on_exit': OptionalTunable(description='\n                When enabled, define the change reason to apply on posture\n                exit.\n                ', tunable=TunableEnumEntry(tunable_type=OutfitChangeReason, default=OutfitChangeReason.Invalid))}

        def get_on_entry_change(self, interaction, sim=DEFAULT, **kwargs):
            sim_info = interaction.sim.sim_info if sim is DEFAULT else sim.sim_info
            return sim_info.sim_outfits.get_change(interaction, self.on_entry, **kwargs)

        def get_on_exit_change(self, interaction, sim=DEFAULT, **kwargs):
            sim_info = interaction.sim.sim_info if sim is DEFAULT else sim.sim_info
            return sim_info.sim_outfits.get_change(interaction, self.on_exit, **kwargs)

        def get_on_entry_outfit(self, interaction, sim=DEFAULT):
            if self.on_entry is not None:
                sim_info = interaction.sim.sim_info if sim is DEFAULT else sim.sim_info
                return sim_info.sim_outfits.get_outfit_for_clothing_change(interaction, self.on_entry)

        def get_on_exit_outfit(self, interaction, sim=DEFAULT):
            if self.on_exit is not None:
                sim_info = interaction.sim.sim_info if sim is DEFAULT else sim.sim_info
                return sim_info.sim_outfits.get_outfit_for_clothing_change(interaction, self.on_exit)

    class _OutfitChangeForTags(OutfitChangeBase):
        __qualname__ = 'TunableOutfitChange._OutfitChangeForTags'
        FACTORY_TUNABLES = {'description': "\n                Define an outfit to apply for the duration of the OutfitChange's\n                owner generated from the specified tags.\n                ", 'tag_set': TunableSet(description='\n                Tags that determine which outfit parts are valid\n                ', tunable=TunableEnumEntry(tunable_type=Tag, default=Tag.INVALID))}

        def get_on_entry_change(self, interaction, sim=DEFAULT, **kwargs):
            sim_info = interaction.sim.sim_info if sim is DEFAULT else sim.sim_info
            for trait in sim_info.trait_tracker:
                outfit_change_reason = trait.get_outfit_change_reason(None)
                while outfit_change_reason is not None:
                    return sim_info.sim_outfits.get_change(interaction, outfit_change_reason, sim=sim, **kwargs)
            sim_info.generate_outfit(OutfitCategory.SPECIAL, 0, tag_list=self.tag_set)
            return build_critical_section(sim_info.sim_outfits.get_change_outfit_element((OutfitCategory.SPECIAL, 0), **kwargs), flush_all_animations)

        def get_on_exit_change(self, interaction, **kwargs):
            sim_info = interaction.sim.sim_info
            return sim_info.sim_outfits.get_change(interaction, OutfitChangeReason.DefaultOutfit, **kwargs)

        def get_on_entry_outfit(self, interaction, sim=DEFAULT):
            return (OutfitCategory.SPECIAL, 0)

        def get_on_exit_outfit(self, interaction, sim=DEFAULT):
            sim_info = interaction.sim.sim_info if sim is DEFAULT else sim.sim_info
            return sim_info.sim_outfits.get_outfit_for_clothing_change(interaction, OutfitChangeReason.DefaultOutfit)

    def __init__(self, allow_outfit_change=True, **kwargs):
        options = {'no_change': TunableOutfitChange._OutfitChangeNone.TunableFactory()}
        if allow_outfit_change:
            options['for_reason'] = TunableOutfitChange._OutfitChangeForReason.TunableFactory()
            options['for_tags'] = TunableOutfitChange._OutfitChangeForTags.TunableFactory()
        kwargs.update(options)
        super().__init__(default='no_change', **kwargs)

class SimOutfits:
    __qualname__ = 'SimOutfits'
    OUTFIT_CATEGORY_TUNING = TunableMapping(key_type=TunableEnumEntry(OutfitCategory, OutfitCategory.EVERYDAY, description='The outfit category enum'), value_type=TunableTuple(localized_category=TunableLocalizedStringFactory(description='Localized name of the outfit category.'), save_outfit_category=OptionalTunable(description="\n                                                                        If set to 'save_this_category', a Sim saved while wearing this \n                                                                        outfit category will change back into this outfit category on load.\n                                                                        \n                                                                        EX: you're tuning Everyday outfit, which is set as save_this_category,\n                                                                        meaning a sim wearing everyday will still be wearing everyday on load.\n                                                                        \n                                                                        Otherwise, you can set to save_as_different_category, which allows you\n                                                                        to specific another outfit category for the sim to be saved in\n                                                                        instead of this category.\n                                                                        \n                                                                        EX: if tuning Bathing category, if the sim is in the bathing category, set this to Everday so that when\n                                                                        the sim loads back up, the sim will be in Everyday wear instead of naked.\n                                                                        ", tunable=TunableEnumEntry(OutfitCategory, OutfitCategory.EVERYDAY, description='The outfit category to save as instead of this category.'), disabled_name='save_this_category', enabled_name='save_as_different_category')))
    CATEGORIES_EXEMPT_FROM_RANDOMIZATION = (OutfitCategory.BATHING,)

    def __init__(self, sim_info):
        self._sim_info_ref = weakref.ref(sim_info)
        self._initialize_outfits()
        self._default_outfit_priorities = []
        self._randomize_daily = {}
        self._last_randomize = {}
        self._daily_defaults = {}
        self.outfit_censor_handle = None
        for category in OutfitCategory:
            self._randomize_daily[category] = True
            self._last_randomize[category] = None

    def get_change(self, interaction, change_reason, sim=DEFAULT, **kwargs):
        if change_reason is not None:
            return build_critical_section(self.get_clothing_change(interaction, change_reason, **kwargs), flush_all_animations)

    def _generate_daily_outfit(self, category):
        current_time = services.time_service().sim_now
        existing_default = category in self._daily_defaults
        last_randomize_time = self._last_randomize[category]
        if not existing_default or current_time.absolute_days() - last_randomize_time.absolute_days() >= 1 or current_time.day() != last_randomize_time.day():
            index = 0
            number_of_outfits = len(self._outfits[category])
            if number_of_outfits > 1:
                if existing_default:
                    index = random.randrange(number_of_outfits - 1)
                    exclusion = self._daily_defaults[category]
                    index += 1
                else:
                    index = random.randrange(number_of_outfits)
            self._daily_defaults[category] = index
            self._last_randomize[category] = current_time
        return (category, self._daily_defaults[category])

    def __iter__(self):
        for outfit_category in self._outfits.values():
            for outfit_data in outfit_category:
                yield outfit_data

    def _initialize_outfits(self):
        self._outfits = {}
        for category in OutfitCategory:
            self._outfits[category] = []

    @property
    def _sim(self):
        return self._sim_info_ref().get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)

    def get_clothing_change(self, interaction, outfit_change_reason, do_spin=True):
        outfit_category_and_index = self.get_outfit_for_clothing_change(interaction, outfit_change_reason)
        return self.get_change_outfit_element(outfit_category_and_index, do_spin=do_spin)

    def get_change_outfit_element(self, outfit_category_and_index, do_spin=True):

        def change_outfit(timeline):
            arb = animation.arb.Arb()
            self._try_set_current_outfit(outfit_category_and_index, do_spin=do_spin, arb=arb)
            if not arb.empty:
                clothing_element = create_run_animation(arb)
                yield element_utils.run_child(timeline, clothing_element)

        return change_outfit

    def _try_set_current_outfit(self, outfit_category_and_index, do_spin=False, arb=None):
        if self._sim_info_ref().can_switch_to_outfit(outfit_category_and_index):
            if do_spin:
                sim = self._sim
                did_change = False

                def set_ending(*_, **__):
                    nonlocal did_change
                    if not did_change:
                        self._sim_info_ref().set_current_outfit(outfit_category_and_index)
                        did_change = True

                arb.register_event_handler(set_ending, handler_id=100)
                clothing_context = animation.get_throwaway_animation_context()
                clothing_change_asm = animation.asm.Asm(ClothingChangeTunables.clothing_change_asm, context=clothing_context)
                sim.posture.setup_asm_interaction(clothing_change_asm, sim, None, ClothingChangeTunables.DEFAULT_ACTOR, None)
                clothing_change_asm.request(ClothingChangeTunables.clothing_change_state, arb)
            else:
                self._sim_info_ref().set_current_outfit(outfit_category_and_index)

    def exit_change_verification(self, outfit_category_and_index):
        sim_info = self._sim_info_ref()
        if sim_info._current_outfit is not outfit_category_and_index:
            self._sim_info_ref().set_current_outfit(outfit_category_and_index)

    def get_outfit_for_clothing_change(self, interaction, reason, resolver=None):
        sim_info = self._sim_info_ref()
        for trait in sim_info.trait_tracker:
            reason = trait.get_outfit_change_reason(reason)
        if reason == OutfitChangeReason.Invalid:
            return sim_info._current_outfit
        if reason == OutfitChangeReason.DefaultOutfit:
            return self.get_default_outfit(interaction=interaction, resolver=resolver)
        if reason == OutfitChangeReason.PreviousClothing:
            return sim_info._previous_outfit
        if reason == OutfitChangeReason.RandomOutfit:
            return self.get_random_outfit(self._outfits.keys())
        if reason == OutfitChangeReason.ExitBedNPC:
            if sim_info.is_npc:
                return sim_info._previous_outfit
            return
        elif reason in ClothingChangeTunables.clothing_reasons_to_outfits:
            test_group_and_outfit_list = ClothingChangeTunables.clothing_reasons_to_outfits[reason]
            for test_group_and_outfit in test_group_and_outfit_list:
                category = test_group_and_outfit.outfit_category
                if category == OutfitCategory.BATHING and not self._outfits[OutfitCategory.BATHING]:
                    sim_info.generate_outfit(OutfitCategory.BATHING)
                if not test_group_and_outfit.tests:
                    if self._randomize_daily[category]:
                        return self._generate_daily_outfit(category)
                    return (test_group_and_outfit.outfit_category, 0)
                if resolver is None:
                    resolver = interaction.get_resolver()
                while test_group_and_outfit.tests.run_tests(resolver):
                    if self._randomize_daily[category]:
                        return self._generate_daily_outfit(category)
                    return (test_group_and_outfit.outfit_category, 0)
        return (OutfitCategory.EVERYDAY, 0)

    def get_default_outfit(self, interaction=None, resolver=None):
        default_outfit = OutfitPriority(None, 0, None)
        for outfit_priority in self._default_outfit_priorities:
            while outfit_priority.priority > default_outfit.priority:
                default_outfit = outfit_priority
        if interaction is not None or resolver is not None:
            return self.get_outfit_for_clothing_change(interaction, default_outfit.change_reason, resolver=resolver)
        if default_outfit.interaction_ref() is not None:
            return self.get_outfit_for_clothing_change(default_outfit.interaction_ref(), default_outfit.change_reason)
        return self._sim_info_ref()._current_outfit

    def get_random_outfit(self, categories, exclusion=None):
        outfits_list = []
        for category in categories:
            if category in self.CATEGORIES_EXEMPT_FROM_RANDOMIZATION:
                pass
            for index in range(len(self._outfits[category])):
                category_and_index = (category, index)
                while category_and_index != exclusion:
                    outfits_list.append(category_and_index)
        if not outfits_list:
            return (OutfitCategory.EVERYDAY, 0)
        return random.choice(outfits_list)

    def add_default_outfit_priority(self, interaction, outfit_change_reason, priority):
        outfit_priority = OutfitPriority(outfit_change_reason, priority, weakref.ref(interaction) if interaction is not None else None)
        self._default_outfit_priorities.append(outfit_priority)
        return id(outfit_priority)

    def remove_default_outfit_priority(self, outfit_priority_id):
        for (index, value) in enumerate(self._default_outfit_priorities):
            while id(value) == outfit_priority_id:
                self._default_outfit_priorities.pop(index)
                break

    def set_outfit(self, outfit_category, outfit_index, outfit_data):
        self._outfits[outfit_category][outfit_index] = outfit_data

    def add_outfit(self, outfit_category, outfit_data):
        self._outfits[outfit_category].append(outfit_data)

    def save_sim_outfits(self):
        outfit_list_msg = serialization.OutfitList()
        for outfit_category in OutfitCategory:
            while self.outfits_in_category(outfit_category) is not None:
                while True:
                    for (index, outfit_dict) in enumerate(self.outfits_in_category(outfit_category)):
                        with ProtocolBufferRollback(outfit_list_msg.outfits) as outfit_msg:
                            outfit_msg.outfit_id = outfit_dict['outfit_id']
                            outfit_msg.category = outfit_category
                            outfit_msg.outfit_index = index
                            outfit_msg.created = services.time_service().sim_now.absolute_ticks()
                            outfit_msg.parts = serialization.IdList()
                            for part in outfit_dict['parts']:
                                outfit_msg.parts.ids.append(part)
                            for body_type in outfit_dict['body_types']:
                                outfit_msg.body_types_list.body_types.append(body_type)
                            outfit_msg.match_hair_style = outfit_dict['match_hair_style']
        return outfit_list_msg

    def load_sim_outfits_from_persistence_proto(self, sim_id, outfit_list):
        self._initialize_outfits()
        if outfit_list is not None:
            for outfit_data in outfit_list.outfits:
                new_outfit = {}
                new_outfit['sim_id'] = sim_id
                new_outfit['outfit_id'] = outfit_data.outfit_id
                new_outfit['type'] = outfit_data.category
                part_list = serialization.IdList()
                part_list.MergeFrom(outfit_data.parts)
                new_outfit['parts'] = part_list.ids
                body_types_list = serialization.BodyTypesList()
                body_types_list.MergeFrom(outfit_data.body_types_list)
                new_outfit['body_types'] = body_types_list.body_types
                new_outfit['match_hair_style'] = outfit_data.match_hair_style
                self.add_outfit(OutfitCategory(outfit_data.category), new_outfit)

    def load_sim_outfits_from_cas_proto(self, outfit_data):
        self._initialize_outfits()
        if outfit_data is not None:
            for outfit in outfit_data.outfits:
                new_outfit = {}
                new_outfit['sim_id'] = outfit.sim_id
                new_outfit['outfit_id'] = outfit.outfit_id
                new_outfit['version'] = outfit.version
                new_outfit['type'] = outfit.type
                new_outfit['parts'] = outfit.part_ids
                new_outfit['body_types'] = outfit.body_types
                new_outfit['match_hair_style'] = outfit.match_hair_style
                self.add_outfit(OutfitCategory(outfit.type), new_outfit)

    def outfits_in_category(self, category):
        if category in self._outfits:
            return self._outfits[category]

    def has_outfit(self, category_and_index):
        (category, index) = category_and_index
        outfits_in_category = self._outfits.get(category)
        if outfits_in_category is None:
            return False
        if index >= len(outfits_in_category):
            return False
        return True

    def is_wearing_outfit(self, category_and_index):
        if category_and_index[0] == OutfitCategory.SITUATION:
            return False
        sim_info = self._sim_info_ref()
        return sim_info._current_outfit == category_and_index

    def get_parts_ids_for_categry_and_index(self, category, index):
        outfits_in_category = self.outfits_in_category(category)
        if outfits_in_category is not None and index < len(outfits_in_category):
            outfit = outfits_in_category[index]
            return list(outfit['parts'])

class ChangeOutfitElement(elements.ParentElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'ChangeOutfitElement'
    FACTORY_TUNABLES = {'description': "\n            Basic extra used to change the Sim's outfit before the starting\n            posture and after the ending posture.\n            ", 'start_outfit_change': OptionalTunable(description='\n            When enabled, the Sim will change to this outfit at the start of\n            this interaction.\n            ', tunable=TunableVariant(tag_reason=TunableSet(tunable=TunableEnumEntry(tunable_type=Tag, default=Tag.INVALID)), change_reason=TunableEnumEntry(tunable_type=OutfitChangeReason, default=OutfitChangeReason.Invalid))), 'end_outfit_change': OptionalTunable(description='\n            When enabled, the Sim will change to this outfit at the end of this\n            interaction.\n            ', tunable=TunableEnumEntry(tunable_type=OutfitChangeReason, default=OutfitChangeReason.Invalid)), 'subject': TunableEnumFlags(description='\n            The participant of who will change their outfit.\n            ', enum_type=ParticipantType, default=ParticipantType.Actor)}

    @staticmethod
    def tuning_loaded_callback(instance_class, tunable_name, source, value):
        pass

    def __init__(self, interaction, *args, sequence=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.interaction = interaction
        self.sequence = sequence
        self.subject_sim_info = self.interaction.get_participant(self.subject).sim_info
        self.subject_sim_outfits = self.subject_sim_info.sim_outfits
        outfits_to_preload = set()
        if self.start_outfit_change is not None:
            is_tag_reason = False
            if issubclass(type(self.start_outfit_change), set):
                is_tag_reason = True
            if is_tag_reason:
                for trait in self.subject_sim_info.trait_tracker:
                    start_outfit_change_reason = trait.get_outfit_change_reason(None)
                    while start_outfit_change_reason is not None:
                        self.start_outfit_change_and_index = start_outfit_change_reason
                        break
                self.subject_sim_info.generate_outfit(OutfitCategory.SPECIAL, 0, tag_list=self.start_outfit_change)
                self.start_outfit_change_and_index = (OutfitCategory.SPECIAL, 0)
            else:
                self.start_outfit_change_and_index = self.subject_sim_outfits.get_outfit_for_clothing_change(self.interaction, self.start_outfit_change)
            outfits_to_preload.add(self.start_outfit_change_and_index)
        else:
            self.start_outfit_change_and_index = None
        if self.end_outfit_change is not None:
            self.subject_sim_info.set_previous_outfit()
            self.end_outfit_change_and_index = self.subject_sim_outfits.get_outfit_for_clothing_change(self.interaction, self.end_outfit_change)
            outfits_to_preload.add(self.end_outfit_change_and_index)
        else:
            self.end_outfit_change_and_index = None
        self.interaction.sim.preload_outfit_list.extend(outfits_to_preload)

    def _run(self, timeline):
        sequence = self.sequence
        if self.start_outfit_change_and_index is not None:
            start_change = build_critical_section(self.subject_sim_outfits.get_change_outfit_element(self.start_outfit_change_and_index, do_spin=True), flush_all_animations)
            sequence = build_critical_section(start_change, sequence)
        if self.end_outfit_change_and_index is not None:
            end_change = build_critical_section(self.subject_sim_outfits.get_change_outfit_element(self.end_outfit_change_and_index, do_spin=True), flush_all_animations)
            end_change_varification = lambda _: self.subject_sim_outfits.exit_change_verification(self.end_outfit_change_and_index)
            sequence = build_critical_section(sequence, end_change)
            sequence = build_critical_section_with_finally(sequence, end_change_varification)
        return timeline.run_child(sequence)

