from buffs import BuffPolarity
from buffs.tunable import TunableBuffReference
from sims import sim_info_types
from sims4.localization import TunableLocalizedString
from sims4.tuning.geometric import TunableVector3
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import Tunable, TunableMapping, TunableReference, TunableTuple, TunableList, OptionalTunable, HasTunableReference, AutoFactoryInit, HasTunableSingletonFactory, TunableResourceKey, TunableEnumEntry
from sims4.tuning.tunable_base import SourceQueries, ExportModes, GroupNames
from sims4.utils import classproperty
from statistics.base_statistic import logger
from statistics.commodity import Commodity
import services
import sims4

class TunableModifiers(TunableTuple):
    __qualname__ = 'TunableModifiers'

    def __init__(self, **kwargs):
        super().__init__(add_modifier=Tunable(description='\n                The modifier to add to a value\n                ', tunable_type=float, default=0), multiply_modifier=Tunable(description='\n                The modifier to multiply a value by\n                ', tunable_type=float, default=1))

class TunableEnvironmentScoreModifiers(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'TunableEnvironmentScoreModifiers'
    FACTORY_TUNABLES = {'mood_modifiers': TunableMapping(description='\n                Modifiers to apply to a given Mood for the environment scoring of an object.\n                ', key_type=TunableReference(description='\n                    The Mood we want to modify for objects in question.\n                    ', manager=services.get_instance_manager(sims4.resources.Types.MOOD)), value_type=TunableModifiers(description="\n                    Modifiers to apply to an object's environment score\n                    "), key_name='mood', value_name='modifiers'), 'negative_modifiers': OptionalTunable(description="\n                Modifiers for an object's negative environment score\n                ", tunable=TunableModifiers(), enabled_by_default=False), 'positive_modifiers': OptionalTunable(description="\n                Modifiers for an object's positive environment score\n                ", tunable=TunableModifiers(), enabled_by_default=False)}
    DEFAULT_MODIFIERS = (0, 1)

    def combine_modifiers(self, object_mood_modifiers, object_negative_modifiers, object_positive_modifiers):
        new_mood_modifiers = {}
        new_negative_modifiers = object_negative_modifiers
        new_positive_modifiers = object_positive_modifiers
        for (mood, modifiers) in object_mood_modifiers.items():
            new_mood_modifiers[mood] = modifiers
        for (mood, modifiers) in self.mood_modifiers.items():
            old_modifiers = new_mood_modifiers.get(mood, (0, 1))
            new_mood_modifiers[mood] = (old_modifiers[0] + modifiers.add_modifier, old_modifiers[1]*modifiers.multiply_modifier)
        new_modifiers = self.get_negative_modifiers()
        new_negative_modifiers = (new_negative_modifiers[0] + new_modifiers[0], new_negative_modifiers[1]*new_modifiers[1])
        new_modifiers = self.get_positive_modifiers()
        new_positive_modifiers = (new_positive_modifiers[0] + new_modifiers[0], new_positive_modifiers[1]*new_modifiers[1])
        return (new_mood_modifiers, new_negative_modifiers, new_positive_modifiers)

    def get_mood_modifiers(self, mood):
        mood_mods = self.mood_modifiers.get(mood)
        if mood_mods is not None:
            return (mood_mods.add_modifier, mood_mods.multiply_modifier)
        return self.DEFAULT_MODIFIERS

    def get_modified_moods(self):
        return self.mood_modifiers.Keys

    def get_negative_modifiers(self):
        if self.negative_modifiers is not None:
            return (self.negative_modifiers.add_modifier, self.negative_modifiers.multiply_modifier)
        return self.DEFAULT_MODIFIERS

    def get_positive_modifiers(self):
        if self.positive_modifiers is not None:
            return (self.positive_modifiers.add_modifier, self.positive_modifiers.multiply_modifier)
        return self.DEFAULT_MODIFIERS

class TunableMoodDescriptionTraitOverride(TunableTuple):
    __qualname__ = 'TunableMoodDescriptionTraitOverride'

    def __init__(self, **kwargs):
        super().__init__(trait=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.TRAIT)), descriptions=TunableList(description='\n                Description for the UI tooltip, per intensity.\n                ', tunable=TunableLocalizedString()), **kwargs)

class Mood(HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.mood_manager()):
    __qualname__ = 'Mood'
    INSTANCE_TUNABLES = {'mood_asm_param': OptionalTunable(description='\n            If set, then this mood will specify an asm parameter to affect\n            animations. If not set, then the ASM parameter will be determined by\n            the second most prevalent mood.\n            ', tunable=Tunable(description="\n                The asm parameter for Sim's mood, if not set, will use 'xxx'\n                from instance name pattern with 'mood_xxx'.\n                ", tunable_type=str, default='', source_query=SourceQueries.SwingEnumNamePattern.format('mood')), enabled_name='Specify', disabled_name='Determined_By_Other_Moods'), 'intensity_thresholds': TunableList(int, description='\n                List of thresholds at which the intensity of this mood levels up.\n                If empty, this mood has a single threshold and all mood tuning lists should\n                have a single item in them.\n                For each threshold added, you may add a new item to the Buffs, Mood Names,\n                Portrait Pose Indexes and Portrait Frames lists.'), 'buffs': TunableList(TunableBuffReference(reload_dependent=True), description='\n                A list of buffs that will be added while this mood is the active mood\n                on a Sim. \n                The first item is applied for the initial intensity, and each\n                subsequent item replaces the previous buff as the intensity levels up.'), 'mood_names': TunableList(TunableLocalizedString(), description='\n                A list of localized names of this mood.\n                The first item is applied for the initial intensity, and each\n                subsequent item replaces the name as the intensity levels up.', export_modes=(ExportModes.ServerXML, ExportModes.ClientBinary)), 'portrait_pose_indexes': TunableList(Tunable(tunable_type=int, default=0), description='\n                A list of the indexes of the pose passed to thumbnail generation on the\n                client to pose the Sim portrait when they have this mood.\n                You can find the list of poses in tuning\n                (Client_ThumnailPoses)\n                The first item is applied for the initial intensity, and each\n                subsequent item replaces the pose as the intensity levels up.', export_modes=(ExportModes.ClientBinary,)), 'portrait_frames': TunableList(Tunable(tunable_type=str, default=''), description='\n                A list of the frame labels (NOT numbers!) from the UI .fla file that the\n                portrait should be set to when this mood is active. Determines\n                background color, font color, etc.\n                The first item is applied for the initial intensity, and each\n                subsequent item replaces the pose as the intensity levels up.', export_modes=(ExportModes.ClientBinary,)), 'environment_scoring_commodity': Commodity.TunableReference(description="\n                Defines the ranges and corresponding buffs to apply for this\n                mood's environmental contribution.\n                \n                Be sure to tune min, max, and the different states. The\n                convergence value is what will remove the buff. Suggested to be\n                0.\n                "), 'descriptions': TunableList(TunableLocalizedString(), description='\n                Description for the UI tooltip, per intensity.', export_modes=(ExportModes.ClientBinary,)), 'icons': TunableList(TunableResourceKey(None, resource_types=sims4.resources.CompoundTypes.IMAGE), description='\n                Icon for the UI tooltip, per intensity.', export_modes=(ExportModes.ClientBinary,)), 'descriptions_age_override': TunableMapping(description='\n                Mapping of age to descriptions text for mood.  If age does not\n                exist in mapping will use default description text.\n                ', key_type=TunableEnumEntry(sim_info_types.Age, sim_info_types.Age.CHILD), value_type=TunableList(description='\n                    Description for the UI tooltip, per intensity.\n                    ', tunable=TunableLocalizedString()), key_name='Age', value_name='description_text', export_modes=(ExportModes.ClientBinary,)), 'descriptions_trait_override': TunableMoodDescriptionTraitOverride(description='\n                Trait override for mood descriptions.  If a Sim has this trait\n                and there is not a valid age override for the Sim, this\n                description text will be used.\n                ', export_modes=(ExportModes.ClientBinary,)), 'audio_stings_on_add': TunableList(description="\n                The audio to play when a mood or it's intensity changes. Tune one for each intensity on the mood.\n                ", tunable=TunableResourceKey(description='\n                    The sound to play.\n                    ', default=None, resource_types=(sims4.resources.Types.PROPX,), export_modes=ExportModes.ClientBinary)), 'mood_colors': TunableList(description='\n                A list of the colors displayed on the steel series mouse when the active Sim has this mood.  The first item is applied for the initial intensity, and each  subsequent item replaces the color as the intensity levels up.\n                ', tunable=TunableVector3(description='\n                    Color.\n                    ', default=sims4.math.Vector3.ZERO(), export_modes=ExportModes.ClientBinary)), 'mood_frequencies': TunableList(description='\n                A list of the flash frequencies on the steel series mouse when the active Sim has this mood.   The first item is applied for the initial intensity, and each  subsequent item replaces the value as the intensity levels up.  0 => solid color, otherwise, value => value hertz.\n                  ', tunable=Tunable(tunable_type=float, default=0.0, description=',\n                    Hertz.\n                    ', export_modes=ExportModes.ClientBinary)), 'buff_polarity': TunableEnumEntry(description='\n                Setting the polarity will determine how up/down arrows\n                appear for any buff that provides this mood.\n                ', tunable_type=BuffPolarity, default=BuffPolarity.NEUTRAL, tuning_group=GroupNames.UI, needs_tuning=True, export_modes=ExportModes.All), 'is_changeable': Tunable(description='\n                If this is checked, any buff with this mood will change to\n                the highest current mood of the same polarity.  If there is no mood\n                with the same polarity it will default to use this mood type\n                ', tunable_type=bool, default=False, needs_tuning=True)}
    _asm_param_name = None
    excluding_traits = None

    @classmethod
    def _tuning_loaded_callback(cls):
        cls._asm_param_name = cls.mood_asm_param
        if not cls._asm_param_name:
            name_list = cls.__name__.split('_', 1)
            if len(name_list) <= 1:
                logger.error("Mood {} has an invalid name for asm parameter, please either set 'mood_asm_param' or change the tuning file name to match the format 'mood_xxx'.", cls.__name__)
            cls._asm_param_name = name_list[1]
        cls._asm_param_name = cls._asm_param_name.lower()
        for buff_ref in cls.buffs:
            my_buff = buff_ref.buff_type
            while my_buff is not None:
                if my_buff.mood_type is not None:
                    logger.error('Mood {} will apply a buff ({}) that affects mood. This can cause mood calculation errors. Please select a different buff or remove the mood change.', cls.__name__, my_buff.mood_type.__name__)
                my_buff.is_mood_buff = True
        prev_threshold = 0
        for threshold in cls.intensity_thresholds:
            if threshold <= prev_threshold:
                logger.error('Mood {} has Intensity Thresholds in non-ascending order.')
                break
            prev_threshold = threshold

    @classmethod
    def _verify_tuning_callback(cls):
        num_thresholds = len(cls.intensity_thresholds) + 1
        if len(cls.buffs) != num_thresholds:
            logger.error('Mood {} does not have the correct number of Buffs tuned. It has {} thresholds, but {} buffs.', cls.__name__, num_thresholds, len(cls.buffs))
        if len(cls.mood_names) != num_thresholds:
            logger.error('Mood {} does not have the correct number of Mood Names tuned. It has {} thresholds, but {} names.', cls.__name__, num_thresholds, len(cls.mood_names))
        if len(cls.portrait_pose_indexes) != num_thresholds:
            logger.error('Mood {} does not have the correct number of Portrait Pose Indexes tuned. It has {} thresholds, but {} poses.', cls.__name__, num_thresholds, len(cls.portrait_pose_indexes))
        if len(cls.portrait_frames) != num_thresholds:
            logger.error('Mood {} does not have the correct number of Portrait Frames tuned. It has {} thresholds, but {} frames.', cls.__name__, num_thresholds, len(cls.portrait_frames))
        for (age, descriptions) in cls.descriptions_age_override.items():
            while len(descriptions) != num_thresholds:
                logger.error('Mood {} does not have the correct number of descriptions age override tuned. For age:({}) It has {} thresholds, but {} descriptions.', cls.__name__, age, num_thresholds, len(descriptions))
        if cls.descriptions_trait_override.trait is not None and len(cls.descriptions_trait_override.descriptions) != num_thresholds:
            logger.error('Mood {} does not have the correct number of trait override descriptions tuned. For trait:({}) It has {} thresholds, but {} descriptions.', cls.__name__, cls.descriptions_trait_override.trait.__name__, num_thresholds, len(cls.descriptions_trait_override.descriptions))

    @classproperty
    def asm_param_name(cls):
        return cls._asm_param_name

