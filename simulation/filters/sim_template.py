import random
from sims import sim_info_types
from sims4.localization import TunableLocalizedString
from sims4.tuning.instances import TunedInstanceMetaclass
from sims4.tuning.tunable import TunableEnumEntry, TunableList, TunableTuple, Tunable, TunableReference, TunableSet, HasTunableReference, OptionalTunable, TunableResourceKey, TunableFactory, TunableInterval, AutoFactoryInit, HasTunableSingletonFactory, TunableVariant
from sims4.utils import classproperty
import enum
import services
import sims.sim_spawner
import sims4.log
import sims4.resources
import statistics.skill
import tag
logger = sims4.log.Logger('SimTemplate')

class SimTemplateType(enum.Int, export=False):
    __qualname__ = 'SimTemplateType'
    SIM = 1
    HOUSEHOLD = 2

class TunableTagSet(metaclass=TunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.TAG_SET)):
    __qualname__ = 'TunableTagSet'
    INSTANCE_TUNABLES = {'tags': TunableSet(TunableEnumEntry(tag.Tag, tag.Tag.INVALID, description='A specific tag.'))}

class SkillRange(HasTunableSingletonFactory):
    __qualname__ = 'SkillRange'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        ideal_value = value.ideal_value
        if int(ideal_value) <= value._min_value or int(ideal_value) >= value._max_value:
            logger.error('Ideal value of {} in FilterRange is not within the bounds of {} - {} (inclusive).', ideal_value, value.min_value, value.max_value, owner='rez')

    FACTORY_TUNABLES = {'min_value': Tunable(description='\n            The minimum possible skill.\n            ', tunable_type=int, default=0), 'max_value': Tunable(description='\n            The maximum possible skill.\n            ', tunable_type=int, default=10), 'ideal_value': Tunable(description='\n            The ideal value for this skill. If outside of min/max, will be ignored\n            ', tunable_type=int, default=5), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, min_value, max_value, ideal_value):
        self._min_value = int(min_value) - 1
        self._max_value = int(max_value) + 1
        if int(ideal_value) <= self._min_value or int(ideal_value) >= self._max_value:
            logger.error('Ideal value of {} in FilterRange is not within the bounds of {} - {} (inclusive).', ideal_value, min_value, max_value, owner='rez')
        self._ideal_value = int(ideal_value)

    @property
    def min_value(self):
        return self._min_value + 1

    @property
    def max_value(self):
        return self._max_value - 1

    @property
    def ideal_value(self):
        return self._ideal_value

    def get_score(self, value):
        score = 0
        if value < self.ideal_value:
            score = (value - self.min_value)/(self.ideal_value - self.min_value)
        else:
            score = (self.max_value - value)/(self.max_value - self.ideal_value)
        return max(0, min(1, score))

    def random_value(self):
        if self._ideal_value < self.min_value or self._ideal_value > self.max_value:
            return random.randint(self.min_value, self.max_value)
        return round(random.triangular(self.min_value, self.max_value, self._ideal_value))

class LiteralAge(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'LiteralAge'
    FACTORY_TUNABLES = {'literal_age': TunableEnumEntry(description="\n            The Sim's age.\n            ", tunable_type=sim_info_types.Age, needs_tuning=True, default=sim_info_types.Age.ADULT)}

    @property
    def min_age(self):
        return self.literal_age

    def get_age(self):
        return self.literal_age

class RandomAge(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'RandomAge'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value.min_age > value.max_age:
            logger.error('Tuning error for {}: Min age is greater than max age'.instance_class)

    FACTORY_TUNABLES = {'min_age': TunableEnumEntry(description='\n            The minimum age for creation.\n            ', tunable_type=sim_info_types.Age, needs_tuning=True, default=sim_info_types.Age.ADULT), 'max_age': TunableEnumEntry(description='\n            The maximum Age for creation\n            ', tunable_type=sim_info_types.Age, needs_tuning=True, default=sim_info_types.Age.ADULT), 'verify_tunable_callback': _verify_tunable_callback}

    def get_age(self):
        age_range = [age for age in sim_info_types.Age if self.min_age <= age <= self.max_age]
        return random.choice(age_range)

class TunableSimCreator(TunableFactory):
    __qualname__ = 'TunableSimCreator'

    @staticmethod
    def factory(age_variant=None, **kwargs):
        if age_variant is not None:
            age_of_sim = age_variant.get_age()
        else:
            age_of_sim = sim_info_types.Age.ADULT
        return sims.sim_spawner.SimCreator(age=age_of_sim, **kwargs)

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(gender=TunableEnumEntry(description="\n                The Sim's gender.\n                ", tunable_type=sim_info_types.Gender, needs_tuning=True, default=None), age_variant=TunableVariant(description="\n                The sim's age for creation. Can be a literal age or random\n                between two ages.\n                ", literal=LiteralAge.TunableFactory(), random=RandomAge.TunableFactory(), needs_tuning=True), resource_key=OptionalTunable(description='\n                If enabled, the Sim will be created using a saved SimInfo file.\n                ', tunable=TunableResourceKey(description='\n                    The SimInfo file to use.\n                    ', default=None, resource_types=(sims4.resources.Types.SIMINFO,))), full_name=OptionalTunable(description="\n                If specified, then the Sim's name will be determined by this\n                localized string. Their first, last and full name will all be\n                set to this.\n                ", tunable=TunableLocalizedString()), tunable_tag_set=TunableReference(description='\n                The set of tags that this template uses for CAS creation.\n                ', manager=services.get_instance_manager(sims4.resources.Types.TAG_SET)), **kwargs)

class TunableSimTemplate(HasTunableReference, metaclass=TunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.SIM_TEMPLATE)):
    __qualname__ = 'TunableSimTemplate'
    INSTANCE_TUNABLES = {'_sim_creation_info': TunableSimCreator(description='\n                The sim creation info that is passed into CAS in order to create the sim.\n                '), '_skills': TunableTuple(description='\n                Skill that will be added to created sim.\n                ', explicit=TunableList(description='\n                    Skill that will be added to sim\n                    ', tunable=TunableTuple(skill=statistics.skill.Skill.TunableReference(description='\n                            The skill that will be added. If left blank a\n                            random skill will be chosen that is not in the\n                            blacklist.\n                            '), range=SkillRange.TunableFactory(description='\n                            The possible skill range for a skill that will be\n                            added to the generated sim.\n                            '))), random=OptionalTunable(description='\n                    Enable if you want random amount of skills to be added to sim.\n                    ', tunable=TunableTuple(interval=TunableInterval(description='\n                            Additional random number skills to be added from\n                            the random list.\n                            ', tunable_type=int, default_lower=1, default_upper=1, minimum=0), choices=TunableList(description='\n                            A list of skills that will be chose for random\n                            update.\n                            ', tunable=TunableTuple(skill=statistics.skill.Skill.TunableReference(description='\n                                    The skill that will be added. If left blank a\n                                    random skill will be chosen that is not in the\n                                    blacklist.\n                                    '), range=SkillRange.TunableFactory(description='\n                                    The possible skill range for a skill that will be\n                                    added to the generated sim.\n                                    ')))), disabled_name='no_extra_random', enabled_name='additional_random'), blacklist=TunableSet(description='\n                    A list of skills that that will not be chosen if looking to\n                    set a random skill.\n                    ', tunable=statistics.skill.Skill.TunableReference()), needs_tuning=True), '_traits': TunableTuple(description='\n                Traits that will be added to the generated template.\n                ', explicit=TunableList(description='\n                    A trait that will always be added to sim.\n                    ', tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.TRAIT))), num_random=OptionalTunable(description='\n                    If enabled a random number of personality traits that will\n                    be added to generated sim.\n                    ', tunable=TunableInterval(tunable_type=int, default_lower=1, default_upper=1, minimum=0)), blacklist=TunableSet(description='\n                    A list of traits that will not be considered when giving random skills.\n                    ', tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.TRAIT))), needs_tuning=True)}

    @classmethod
    def _verify_tuning_callback(cls):
        for trait in cls._traits.explicit:
            while trait is not None and trait in cls._traits.blacklist:
                logger.error('SimTemplate: {} - explicit trait ({}) in blacklist.Either update explicit list or remove from blacklist', cls.__name__, trait.__name__, owner='designer')
        for skill_data in cls._skills.explicit:
            while skill_data.skill is not None and skill_data.skill in cls._skills.blacklist:
                logger.error('SimTemplate: {} - in explicit skill ({}) in blacklist.Either update explicit list or remove from blacklist', cls.__name__, skill_data.skill.__name__, owner='designer')
        if cls._skills.random:
            random_skill_available = any(skill_data.skill is None for skill_data in cls._skills.random.choices)
            if not random_skill_available and len(cls._skills.random.choices) < cls._skills.random.interval.upper_bound:
                logger.error('SimTemplate: {} - There is not enough entries {} in the random choices to support the upper bound {} of the random amount to add.\n  Possible Fixes:\n    Add a random option into the random->choices \n    Add more options in random->choices\n    or decrease upper bound of random amount.', cls.__name__, len(cls._skills.random.choices), cls._skills.random.interval.upper_bound, owner='designer')
            for skill_data in cls._skills.random.choices:
                while skill_data.skill is not None and skill_data.skill in cls._skills.blacklist:
                    logger.error('SimTemplate: {} - in random choices skill {} in blacklist.Either update explicit list or remove from blacklist', cls.__name__, skill_data.skill, owner='designer')

    @classproperty
    def template_type(cls):
        return SimTemplateType.SIM

    @classproperty
    def sim_creator(cls):
        return cls._sim_creation_info()

    @classmethod
    def add_template_data_to_sim(cls, sim_info):
        cls._add_skills(sim_info)
        cls._add_traits(sim_info)
        cls._add_gender_preference(sim_info)

    @classmethod
    def _add_skills(cls, sim_info):
        if not cls._skills.explicit and not cls._skills.random:
            return
        statistic_manager = services.statistic_manager()
        available_skills_types = list(set([stat for stat in statistic_manager.types.values() if stat.is_skill]) - cls._skills.blacklist)
        for skill_data in cls._skills.explicit:
            cls._add_skill_type(sim_info, skill_data, available_skills_types)
        if cls._skills.random:
            num_to_add = cls._skills.random.interval.random_int()
            available_random_skill_data = list(cls._skills.random.choices)
            while num_to_add > 0 and available_random_skill_data and available_skills_types:
                random_skill_data = random.choice(available_random_skill_data)
                if random_skill_data.skill is not None:
                    available_random_skill_data.remove(random_skill_data)
                #ERROR: Unexpected statement:   298 POP_BLOCK  |   299 JUMP_FORWARD 

                if cls._add_skill_type(sim_info, random_skill_data, available_skills_types):
                    num_to_add -= 1
                    continue
                    continue
                continue

    @classmethod
    def _add_skill_type(cls, sim_info, skill_data, available_skills_types):
        skill_type = skill_data.skill
        if skill_type is None:
            skill_type = random.choice(available_skills_types)
        if skill_type in available_skills_types:
            available_skills_types.remove(skill_type)
        if skill_type is not None and skill_type.can_add(sim_info):
            skill_value = skill_type.convert_from_user_value(skill_data.range.random_value())
            sim_info.add_statistic(skill_type, skill_value)
            return True
        return False

    @classmethod
    def _add_traits(cls, sim_info):
        trait_tracker = sim_info.trait_tracker
        for trait in tuple(trait_tracker.personality_traits):
            trait_tracker.remove_trait(trait)
        for trait in cls._traits.explicit:
            trait_tracker.add_trait(trait)
        if cls._traits.num_random:
            num_to_add = cls._traits.num_random.random_int()
            if num_to_add > 0:
                trait_manager = services.trait_manager()
                available_trait_types = set([trait for trait in trait_manager.types.values() if trait.is_personality_trait])
                available_trait_types = list(available_trait_types - cls._traits.blacklist - set(cls._traits.explicit))
                while True:
                    while num_to_add > 0 and available_trait_types:
                        trait = random.choice(available_trait_types)
                        available_trait_types.remove(trait)
                        if not trait_tracker.can_add_trait(trait, display_warn=False):
                            continue
                        trait_tracker.add_trait(trait)
                        num_to_add -= 1

    @classmethod
    def _add_gender_preference(cls, sim_info):
        if sims.global_gender_preference_tuning.GlobalGenderPreferenceTuning.enable_autogeneration_same_sex_preference:
            gender_choices = [(gender_info.weight, gender_info.gender_preference) for gender_info in sims.global_gender_preference_tuning.GlobalGenderPreferenceTuning.ENABLED_AUTOGENERATION_SAME_SEX_PREFERENCE_WEIGHTS]
        else:
            gender_choices = [(gender_info.weight, gender_info.gender_preference) for gender_info in sims.global_gender_preference_tuning.GlobalGenderPreferenceTuning.GENDER_PREFERENCE_WEIGHTS]
        gender_choice = sims4.random.weighted_random_item(gender_choices)
        for gender_preference in sims.global_gender_preference_tuning.GlobalGenderPreferenceTuning.GENDER_PREFERENCE_MAPPING[gender_choice][sim_info.gender]:
            sim_info.add_statistic(gender_preference, gender_preference.max_value)

class TunableTemplateChooser(metaclass=TunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.TEMPLATE_CHOOSER)):
    __qualname__ = 'TunableTemplateChooser'
    INSTANCE_TUNABLES = {'_templates': TunableList(TunableTuple(template=TunableSimTemplate.TunableReference(description='A template that can be chosen.'), weight=Tunable(int, 1, description='Weight of this template being chosen.')))}

    @classmethod
    def choose_template(cls):
        possible_templates = [(template_weight_pair.weight, template_weight_pair.template) for template_weight_pair in cls._templates]
        return sims4.random.pop_weighted(possible_templates)

