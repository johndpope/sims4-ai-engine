import itertools
import random
from protocolbuffers import SimObjectAttributes_pb2 as protocols
from protocolbuffers.Localization_pb2 import LocalizedStringToken
from cas.cas import generate_offspring
from date_and_time import DateAndTime
from event_testing.resolver import SingleSimResolver, DoubleSimResolver
from event_testing.test_events import TestEvent
from interactions import ParticipantType
from interactions.utils.interaction_elements import XevtTriggeredElement
from relationships.relationship_bit import RelationshipBit
from sims.sim_dialogs import SimPersonalityAssignmentDialog
from sims.sim_info_types import Gender, Age
from sims.sim_spawner import SimSpawner, SimCreator
from sims4.math import EPSILON, clamp, MAX_UINT32
from sims4.random import pop_weighted
from sims4.tuning.tunable import TunablePercent, TunableReference, TunableEnumEntry, TunableRange, TunableList, TunableTuple, Tunable, OptionalTunable
from singletons import DEFAULT
from traits.traits import Trait
from tunable_multiplier import TunableMultiplier
from ui.ui_dialog import UiDialogOk
from ui.ui_dialog_generic import TEXT_INPUT_FIRST_NAME, TEXT_INPUT_LAST_NAME
import distributor.ops
import services
import ui

class PregnancyClientMixin:
    __qualname__ = 'PregnancyClientMixin'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pregnancy_progress = 0

    @distributor.fields.Field(op=distributor.ops.SetPregnancyProgress, default=None)
    def pregnancy_progress(self):
        return self._pregnancy_progress

    @pregnancy_progress.setter
    def pregnancy_progress(self, value):
        self._pregnancy_progress = clamp(0, value, 1) if value is not None else None

class PregnancyOffspringData:
    __qualname__ = 'PregnancyOffspringData'

    def __init__(self, gender, genetics, first_name='', last_name='', traits=DEFAULT):
        self.gender = gender
        self.genetics = genetics
        self.first_name = first_name
        self.last_name = last_name
        self.traits = [] if traits is DEFAULT else traits

    @property
    def is_female(self):
        return self.gender == Gender.FEMALE

    def populate_localization_token(self, token):
        token.type = LocalizedStringToken.SIM
        token.first_name = self.first_name
        token.last_name = self.last_name
        token.is_female = self.is_female

class PregnancyTracker:
    __qualname__ = 'PregnancyTracker'
    PREGNANCY_COMMODITY = TunableReference(description='\n        The commodity to award if conception is successful.\n        ', manager=services.statistic_manager())
    PREGNANCY_TRAIT = TunableReference(description='\n        The trait that all pregnant Sims have during pregnancy.\n        ', manager=services.trait_manager())
    PREGNANCY_RATE = TunableRange(description='\n        The rate per Sim minute of pregnancy.\n        ', tunable_type=float, default=0.001, minimum=EPSILON)
    PREGNANCY_DIALOG = SimPersonalityAssignmentDialog.TunableFactory(description="\n        The dialog that is displayed when an offspring is created. It allows the\n        player to enter a first and last name for the Sim. An additional token\n        is passed in: the offspring's Sim data.\n        ", text_inputs=(TEXT_INPUT_FIRST_NAME, TEXT_INPUT_LAST_NAME))
    MULTIPLE_OFFSPRING_CHANCES = TunableList(description='\n        A list defining the probabilities of multiple births.\n        ', tunable=TunableTuple(size=Tunable(description='\n                The number of offspring born.\n                ', tunable_type=int, default=1), weight=Tunable(description='\n                The weight, relative to other outcomes.\n                ', tunable_type=float, default=1), npc_dialog=UiDialogOk.TunableFactory(description='\n                A dialog displayed when a NPC Sim gives birth to an offspring\n                that was conceived by a currently player-controlled Sim. The\n                dialog is specifically used when this number of offspring is\n                generated.\n                \n                Three tokens are passed in: the two parent Sims and the offspring\n                ', locked_args={'text_tokens': None}), modifiers=TunableMultiplier.TunableFactory(description='\n                A tunable list of test sets and associated multipliers to apply to \n                the total chance of this number of potential offspring.\n                '), screen_slam_one_parent=OptionalTunable(description='\n                Screen slam to show when only one parent is available.\n                Localization Tokens: Sim A - {0.SimFirstName}\n                ', tunable=ui.screen_slam.TunableScreenSlamSnippet()), screen_slam_two_parents=OptionalTunable(description='\n                Screen slam to show when both parents are available.\n                Localization Tokens: Sim A - {0.SimFirstName}, Sim B - {1.SimFirstName}\n                ', tunable=ui.screen_slam.TunableScreenSlamSnippet())))
    MONOZYGOTIC_OFFSPRING_CHANCE = TunablePercent(description='\n        The chance that each subsequent offspring of a multiple birth has the\n        same genetics as the first offspring.\n        ', default=50)
    BIRTHPARENT_BIT = RelationshipBit.TunableReference(description='\n        The bit that is added on the relationship from the Sim to any of its\n        offspring.\n        ')

    def __init__(self, sim_info):
        self._sim_info = sim_info
        self._last_modified = None
        self.clear_pregnancy()

    @property
    def account(self):
        return self._sim_info.account

    @property
    def is_pregnant(self):
        if self._seed:
            return True
        return False

    @property
    def offspring_count(self):
        return max(len(self._offspring_data), 1)

    def _get_parent(self, sim_id):
        sim_info_manager = services.sim_info_manager()
        if sim_id in sim_info_manager:
            return sim_info_manager.get(sim_id)

    def get_parents(self):
        if self._parent_ids:
            parent_a = self._get_parent(self._parent_ids[0])
            parent_b = self._get_parent(self._parent_ids[1]) or parent_a
            return (parent_a, parent_b)
        return (None, None)

    def get_partner(self):
        (owner, partner) = self.get_parents()
        if partner is not owner:
            return partner

    def start_pregnancy(self, parent_a, parent_b):
        if not self.is_pregnant:
            self._seed = random.randint(1, MAX_UINT32)
            self._parent_ids = (parent_a.id, parent_b.id)
            self._offspring_data = []
            self.enable_pregnancy()

    def enable_pregnancy(self):
        if self.is_pregnant and not self._is_enabled:
            tracker = self._sim_info.get_tracker(self.PREGNANCY_COMMODITY)
            pregnancy_commodity = tracker.get_statistic(self.PREGNANCY_COMMODITY, add=True)
            pregnancy_commodity.add_statistic_modifier(self.PREGNANCY_RATE)
            trait_tracker = self._sim_info.trait_tracker
            trait_tracker.add_trait(self.PREGNANCY_TRAIT)
            self._last_modified = None
            self._is_enabled = True

    def update_pregnancy(self):
        if self.is_pregnant:
            if self._last_modified is not None:
                tracker = self._sim_info.get_tracker(self.PREGNANCY_COMMODITY)
                pregnancy_commodity = tracker.get_statistic(self.PREGNANCY_COMMODITY, add=True)
                if pregnancy_commodity.get_value() >= self.PREGNANCY_COMMODITY.max_value:
                    self.create_offspring_data()
                    for offspring_data in self.get_offspring_data_gen():
                        offspring_data.first_name = self._get_random_first_name(offspring_data)
                        self.create_sim_info(offspring_data)
                    self._show_npc_dialog()
                    self.clear_pregnancy()
                else:
                    delta_time = services.time_service().sim_now - self._last_modified
                    delta = self.PREGNANCY_RATE*delta_time.in_minutes()
                    pregnancy_commodity.add_value(delta)
            self._last_modified = services.time_service().sim_now

    def complete_pregnancy(self):
        services.get_event_manager().process_event(TestEvent.OffspringCreated, sim_info=self._sim_info, offspring_created=self.offspring_count)
        for tuning_data in self.MULTIPLE_OFFSPRING_CHANCES:
            while tuning_data.size == self.offspring_count:
                (parent_a, parent_b) = self.get_parents()
                if parent_a is parent_b:
                    screen_slam = tuning_data.screen_slam_one_parent
                else:
                    screen_slam = tuning_data.screen_slam_two_parents
                if screen_slam is not None:
                    screen_slam.send_screen_slam_message(self._sim_info, parent_a, parent_b)
                break

    def clear_pregnancy_visuals(self):
        if self._sim_info.pregnancy_progress:
            self._sim_info.pregnancy_progress = 0

    def clear_pregnancy(self):
        self._seed = 0
        self._parent_ids = []
        self._offspring_data = []
        tracker = self._sim_info.get_tracker(self.PREGNANCY_COMMODITY)
        stat = tracker.get_statistic(self.PREGNANCY_COMMODITY)
        if stat is not None:
            tracker.set_min(self.PREGNANCY_COMMODITY)
            stat.remove_statistic_modifier(self.PREGNANCY_RATE)
        trait_tracker = self._sim_info.trait_tracker
        if trait_tracker.has_trait(self.PREGNANCY_TRAIT):
            trait_tracker.remove_trait(self.PREGNANCY_TRAIT)
        self.clear_pregnancy_visuals()
        self._is_enabled = False

    def create_sim_info(self, offspring_data):
        (parent_a, parent_b) = self.get_parents()
        sim_creator = SimCreator(gender=offspring_data.gender, age=Age.BABY, first_name=offspring_data.first_name, last_name=offspring_data.last_name)
        household = self._sim_info.household
        zone_id = household.home_zone_id
        (sim_info_list, _) = SimSpawner.create_sim_infos((sim_creator,), household=household, account=self.account, zone_id=zone_id, generate_deterministic_sim=True, creation_source='pregnancy')
        sim_info = sim_info_list[0]
        generate_offspring(parent_a._base, parent_b._base, sim_info._base, seed=offspring_data.genetics)
        sim_info.resend_physical_attributes()
        trait_tracker = sim_info.trait_tracker
        for trait in tuple(trait_tracker.personality_traits):
            trait_tracker.remove_trait(trait)
        for trait in offspring_data.traits:
            trait_tracker.add_trait(trait)
        self.initialize_sim_info(sim_info, parent_a, parent_b)
        self._sim_info.relationship_tracker.add_relationship_bit(sim_info.id, self.BIRTHPARENT_BIT)
        return sim_info

    @staticmethod
    def initialize_sim_info(sim_info, parent_a, parent_b):
        sim_info.add_parent_relations(parent_a, parent_b)
        if sim_info.household is not parent_a.household:
            parent_a.household.add_sim_info_to_household(sim_info)
        services.sim_info_manager()._set_default_genealogy()
        sim_info.set_default_relationships(reciprocal=True)
        client = services.client_manager().get_client_by_household_id(sim_info.household_id)
        if client is not None:
            client.selectable_sims.add_selectable_sim_info(sim_info)

    def _select_traits_for_offspring(self, gender):
        traits = []
        num_of_traits = Trait.EQUIP_SLOT_NUMBER_MAP[Age.BABY]
        if num_of_traits == 0:
            return traits
        possible_traits = Trait.get_possible_traits(Age.BABY, gender)
        random.shuffle(possible_traits)
        first_trait = possible_traits.pop()
        traits.append(first_trait)
        while len(traits) < num_of_traits:
            current_trait = possible_traits.pop()
            if not any(trait.is_conflicting(current_trait) for trait in traits):
                traits.append(current_trait)
            while not possible_traits:
                break
                continue
        return traits

    def create_offspring_data(self):
        r = random.Random()
        r.seed(self._seed)
        offspring_count = pop_weighted([(p.weight*p.modifiers.get_multiplier(SingleSimResolver(self._sim_info)), p.size) for p in self.MULTIPLE_OFFSPRING_CHANCES], random=r)
        offspring_count = min(self._sim_info.household.free_slot_count + 1, offspring_count)
        self._offspring_data = []
        for offspring_index in range(offspring_count):
            if offspring_index and r.random() < self.MONOZYGOTIC_OFFSPRING_CHANCE:
                gender = self._offspring_data[offspring_index - 1].gender
                genetics = self._offspring_data[offspring_index - 1].genetics
            else:
                gender = Gender.MALE if r.random() < 0.5 else Gender.FEMALE
                genetics = r.randint(1, MAX_UINT32)
            last_name = SimSpawner.get_family_name_for_gender(self._sim_info.account, self._sim_info.last_name, gender == Gender.FEMALE)
            traits = self._select_traits_for_offspring(gender)
            self._offspring_data.append(PregnancyOffspringData(gender, genetics, last_name=last_name, traits=traits))

    def get_offspring_data_gen(self):
        for offspring_data in self._offspring_data:
            yield offspring_data

    def _get_random_first_name(self, offspring_data):
        tries_left = 10

        def is_valid(first_name):
            nonlocal tries_left
            if not first_name:
                return False
            tries_left -= 1
            if tries_left and any(sim.first_name == first_name for sim in self._sim_info.household):
                return False
            if any(sim.first_name == first_name for sim in self._offspring_data):
                return False
            return True

        first_name = None
        while not is_valid(first_name):
            first_name = SimSpawner.get_random_first_name(self.account, offspring_data.is_female)
        return first_name

    def _show_npc_dialog(self):
        for tuning_data in self.MULTIPLE_OFFSPRING_CHANCES:
            while tuning_data.size == self.offspring_count:
                npc_dialog = tuning_data.npc_dialog
                if npc_dialog is not None:
                    for parent in self.get_parents():
                        parent_instance = parent.get_sim_instance()
                        while parent_instance is not None and parent_instance.client is not None:
                            additional_tokens = list(itertools.chain(self.get_parents(), self._offspring_data))
                            dialog = npc_dialog(parent_instance, DoubleSimResolver(additional_tokens[0], additional_tokens[1]))
                            dialog.show_dialog(additional_tokens=additional_tokens)
                return

    def save(self):
        data = protocols.PersistablePregnancyTracker()
        data.seed = self._seed
        if self._last_modified is not None:
            self.last_modified = self._last_modified.absolute_ticks()
        data.parent_ids.extend(self._parent_ids)
        return data

    def load(self, data):
        self._seed = int(data.seed)
        if data.HasField('last_modified'):
            self._last_modified = DateAndTime(data.last_modified)
        self._parent_ids.clear()
        self._parent_ids.extend(data.parent_ids)

class PregnancyElement(XevtTriggeredElement):
    __qualname__ = 'PregnancyElement'
    FACTORY_TUNABLES = {'description': 'Have a participant of the owning interaction become pregnant.', 'pregnancy_subject': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='The participant of this interaction that is to be impregnated.'), 'pregnancy_parent_subject': TunableEnumEntry(ParticipantType, ParticipantType.TargetSim, description='The participant of this interaction that is to be the impregnator.'), 'pregnancy_chance_and_modifiers': TunableMultiplier.TunableFactory(description='\n            A tunable list of test sets and associated multipliers to apply to \n            the total chance of pregnancy.\n            ')}

    def _do_behavior(self, *args, **kwargs):
        subject = self.interaction.get_participant(self.pregnancy_subject)
        if subject is not None and subject.household.free_slot_count and random.random() < self.pregnancy_chance_and_modifiers.get_multiplier(self.interaction.get_resolver()):
            parent_subject = self.interaction.get_participant(self.pregnancy_parent_subject) or subject
            subject.sim_info.pregnancy_tracker.start_pregnancy(subject, parent_subject)

