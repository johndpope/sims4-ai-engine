#ERROR: jaddr is None
from buffs.tunable import TunableBuffReference
from event_testing.tests import TunableTestSet
from interactions.utils.tunable import ContentSet
from sims import sim_info_types
from sims.sim_outfits import OutfitChangeReason
from sims4.localization import TunableLocalizedString, TunableLocalizedStringFactory
from sims4.resources import CompoundTypes
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableResourceKey, OptionalTunable, TunableReference, TunableList, TunableEnumEntry, TunableSet, TunableMapping, Tunable, HasTunableReference
from sims4.tuning.tunable_base import ExportModes, SourceQueries
from sims4.utils import classproperty
import enum
import services
import sims4.log
import tag
logger = sims4.log.Logger('Trait', default_owner='cjiang')

class TraitType(enum.Int):
    __qualname__ = 'TraitType'
    PERSONALITY = 0
    GAMEPLAY = 1
    WALKSTYLE = 2
    HIDDEN = 4

def are_traits_conflicting(trait_a, trait_b):
    if trait_a is None or trait_b is None:
        return False
    return trait_a.is_conflicting(trait_b)

class Trait(HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.trait_manager()):
    __qualname__ = 'Trait'
    EQUIP_SLOT_NUMBER_MAP = TunableMapping(description='\n        The initial available slot number mapping to sim age.', key_type=TunableEnumEntry(description='\n            The age key for the slot number.', tunable_type=sim_info_types.Age, default=sim_info_types.Age.YOUNGADULT), value_type=Tunable(description='\n            Equip slot number.', tunable_type=int, default=3), key_name='Age', value_name='Slot Number')
    PERSONALITY_TRAIT_TAG = TunableEnumEntry(description='\n        The tag that marks trait as personality trait.', tunable_type=tag.Tag, default=tag.Tag.INVALID)
    INSTANCE_TUNABLES = {'display_name': TunableLocalizedStringFactory(description='\n            Localized name of this trait', export_modes=ExportModes.All), 'trait_asm_param': Tunable(description="\n                The asm parameter for this trait, if not set, will use the\n                tuning instance name, such as 'trait_Clumsy'", tunable_type=str, default=None), 'trait_description': TunableLocalizedString(description='\n            Localized description of this trait', export_modes=ExportModes.All), 'trait_origin_description': TunableLocalizedString(description='\n            Localized description of where the player earned this trait for the active Sim.', export_modes=ExportModes.All), 'icon': TunableResourceKey(description='\n            Icon to be displayed for the trait.', default='PNG:missing_image', resource_types=CompoundTypes.IMAGE, export_modes=ExportModes.All), 'pie_menu_icon': TunableResourceKey(description='\n            Icon to be displayed for the trait in the pie menu.', default=None, resource_types=CompoundTypes.IMAGE), 'cas_selected_icon': TunableResourceKey(description='\n            Icon to be displayed in CAS when this trait has already been applied\n            to a Sim.\n            ', default=None, resource_types=CompoundTypes.IMAGE, export_modes=(ExportModes.ClientBinary,)), 'conflicting_traits': TunableList(description='\n            The conflicting traits list of this one', tunable=TunableReference(manager=services.trait_manager()), export_modes=ExportModes.All), 'genders': TunableSet(description='\n            Trait allowed gender, empty set means not specified', tunable=TunableEnumEntry(tunable_type=sim_info_types.Gender, default=None, export_modes=ExportModes.All)), 'ages': TunableSet(description='\n            Trait allowed ages, empty set means not specified', tunable=TunableEnumEntry(tunable_type=sim_info_types.Age, default=None, export_modes=ExportModes.All)), 'interactions': OptionalTunable(description='\n            Mixer interactions to add to the Sim along with this trait.', tunable=ContentSet.TunableFactory(locked_args={'phase_affordances': {}, 'phase_tuning': None})), 'buffs': TunableList(description='\n            The buff list to trigger when this trait is equipped to Sim', tunable=TunableBuffReference()), 'buff_replacements': TunableMapping(description='\n            A mapping of buff replacement. If Sim has this trait on, whenever\n            he get the buff tuned in the key of the mapping, it will get\n            replaced by the value of the mapping.\n            ', key_type=TunableReference(description='\n                Buff that will get replaced to apply on Sim by this trait.', manager=services.buff_manager(), reload_dependent=True), value_type=TunableReference(description='\n                Buff used to replace the buff tuned as key.', manager=services.buff_manager(), reload_dependent=True)), 'excluded_mood_types': TunableList(TunableReference(description='\n            List of moods that are prevented by having this trait.\n            ', manager=services.mood_manager())), 'buffs_proximity': TunableList(TunableReference(description='\n                Proximity buffs that are active when this trait is equipped to Sim\n                ', manager=services.buff_manager())), 'relbit_replacements': TunableMapping(description='\n            A mapping of bit replacement. If Sim has this trait on, whenever he\n            get the relationship bit tuned in the key of the mapping, it will\n            be replaced by the value of the mapping.\n            ', key_type=TunableReference(description='\n                Relationship bit that will get replaced to apply on Sim by this\n                trait.', manager=services.relationship_bit_manager(), reload_dependent=True), value_type=TunableReference(description='\n                Relationship bit used to replace bit tuned as key.', manager=services.relationship_bit_manager(), reload_dependent=True)), 'outfit_replacements': TunableMapping(description="\n            A mapping of outfit replacements. If the Sim has this trait, outfit\n            change requests are intercepted to produce the tuned result. If multiple\n            traits with outfit replacements exist, the behavior is undefined.\n            \n            Tuning 'Invalid' as a key acts as a fallback and applies to all reasons.\n            Tuning 'Invalid' as a value keeps a Sim in their current outfit.\n            ", key_type=TunableEnumEntry(tunable_type=OutfitChangeReason, default=OutfitChangeReason.Invalid), value_type=TunableEnumEntry(tunable_type=OutfitChangeReason, default=OutfitChangeReason.Invalid)), 'tags': TunableList(description="\n            The associated categories of the trait. Need to distinguish among\n            'Personality Traits', 'Achievement Traits' and 'Walkstyle\n            Traits'.", tunable=TunableEnumEntry(tunable_type=tag.Tag, default=tag.Tag.INVALID), export_modes=ExportModes.All), 'cas_idle_asm_key': TunableResourceKey(description='\n            The ASM to use for CAS idle', default=None, resource_types=[sims4.resources.Types.STATEMACHINE], category='asm', export_modes=ExportModes.All), 'cas_idle_asm_state': Tunable(description='\n            The state to play for CAS idle.', tunable_type=str, default=None, source_location='cas_idle_asm_key', source_query=SourceQueries.ASMState, export_modes=ExportModes.All), 'cas_trait_asm_param': Tunable(description='\n            The asm parameter for this trait for use with CAS ASM state machine, driven by selection\n            of this Trait, i.e. when a player selects the a romantic trait, the Flirty\n            ASM is given to the state machine to play. The name tuned here must match the animation\n            state name parameter expected in Swing.', tunable_type=str, default=None, export_modes=ExportModes.All), 'trait_type': TunableEnumEntry(description='\n            The type of the trait', tunable_type=TraitType, default=TraitType.PERSONALITY, export_modes=ExportModes.All), 'can_age_up': Tunable(description='\n            When set, Sims with this trait are allowed to age up. When unset,\n            Sims are prevented from aging up.\n            ', tunable_type=bool, default=True), 'can_die': Tunable(description='\n            When set, Sims with this trait are allowed to die. When unset, Sims\n            are prevented from dying.\n            ', tunable_type=bool, default=True), 'is_npc_only': Tunable(description='\n            If checked, this trait will get removed from Sims that have a home\n            when the zone is loaded.\n            ', tunable_type=bool, default=False)}
    _asm_param_name = None

    def __repr__(self):
        return '<Trait:({})>'.format(self.__name__)

    def __str__(self):
        return '{}'.format(self.__name__)

    @classmethod
    def _cls_repr(cls):
        return '{}'.format(cls.__name__)

    @classmethod
    def get_outfit_change_reason(cls, outfit_change_reason):
        replaced_reason = cls.outfit_replacements.get(outfit_change_reason if outfit_change_reason is not None else OutfitChangeReason.Invalid)
        if replaced_reason is not None:
            return replaced_reason
        if outfit_change_reason is not None:
            replaced_reason = cls.outfit_replacements.get(OutfitChangeReason.Invalid)
            if replaced_reason is not None:
                return replaced_reason
        return outfit_change_reason

    @classmethod
    def is_conflicting(cls, trait):
        if trait is None:
            return False
        if cls.conflicting_traits and trait in cls.conflicting_traits:
            return True
        if trait.conflicting_traits and cls in trait.conflicting_traits:
            return True
        return False

    @classmethod
    def test_sim_info(cls, sim_info):
        if cls.genders and sim_info.gender not in cls.genders:
            return False
        if cls.ages and sim_info.age not in cls.ages:
            return False
        return True

    @classproperty
    def is_personality_trait(cls):
        return cls.trait_type == TraitType.PERSONALITY

    @classmethod
    def _tuning_loaded_callback(cls):
        cls._asm_param_name = cls.trait_asm_param
        if cls._asm_param_name is None:
            cls._asm_param_name = cls.__name__
        for (buff, replacement_buff) in cls.buff_replacements.items():
            if buff.trait_replacement_buffs is None:
                buff.trait_replacement_buffs = {}
            buff.trait_replacement_buffs[cls] = replacement_buff
        for (bit, replacement_bit) in cls.relbit_replacements.items():
            if bit.trait_replacement_bits is None:
                bit.trait_replacement_bits = {}
            bit.trait_replacement_bits[cls] = replacement_bit
        for mood in cls.excluded_mood_types:
            if mood.excluding_traits is None:
                mood.excluding_traits = []
            mood.excluding_traits.append(cls)

    @classproperty
    def asm_param_name(cls):
        return cls._asm_param_name

    @staticmethod
    def get_possible_traits(age, gender):
        return [trait for trait in services.trait_manager().types.values() if gender in trait.genders]

