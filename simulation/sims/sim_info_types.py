from sims4.tuning.tunable import TunableEnumEntry, TunableList
from tag import Tag
import enum
import sims4.log
logger = logger = sims4.log.Logger('sim_info_types')

class Gender(enum.Int):
    __qualname__ = 'Gender'
    MALE = 4096
    FEMALE = 8192

class Age(enum.Int):
    __qualname__ = 'Age'
    BABY = 1
    UNUSED_FLAG = 2
    CHILD = 4
    TEEN = 8
    YOUNGADULT = 16
    ADULT = 32
    ELDER = 64

    @classmethod
    def next_age(cls, age):
        if age == cls.ELDER:
            raise ValueError('There is no age after Elder')
        try:
            if age == cls.BABY:
                return cls.CHILD
            if age == cls.CHILD:
                return cls.TEEN
            if age == cls.TEEN:
                return cls.YOUNGADULT
            if age == cls.YOUNGADULT:
                return cls.ADULT
            return cls.ELDER
        except ValueError:
            raise ValueError('Invalid age: {}'.format(str(age)))

    @classmethod
    def get_ages_for_animation_cache(cls):
        return (cls.ADULT, cls.CHILD)

    @property
    def age_for_animation_cache(self):
        if self <= self.CHILD:
            return self.CHILD
        return self.ADULT

    @property
    def animation_age_param(self):
        return self.name.lower()

class SimVFXOption(enum.Int):
    __qualname__ = 'SimVFXOption'
    FILTER_NONE = 0
    FILTER_PAINTERLY = 1
    FILTER_EIGHTBIT = 2

class SimInfoSpawnerTags:
    __qualname__ = 'SimInfoSpawnerTags'
    SIM_SPAWNER_TAGS = TunableList(description='\n        A list of tags for Sims to spawn when traveling and moving on/off lot.\n        Note: Tags are resolved in order until a spawn point has been found that contains the tag.\n        ', tunable=TunableEnumEntry(tunable_type=Tag, default=Tag.INVALID))

class SimSerializationOption(enum.Int, export=False):
    __qualname__ = 'SimSerializationOption'
    UNDECLARED = 0
    LOT = 1
    OPEN_STREETS = 2

