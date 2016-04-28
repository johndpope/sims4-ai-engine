import random
from cas.cas import generate_household
from protocolbuffers import FileSerialization_pb2 as serialization
from objects import ALL_HIDDEN_REASONS
from sims import sim_info_types
from sims.sim_info_types import Gender
from sims4.protocol_buffer_utils import has_field
from sims4.tuning.dynamic_enum import DynamicEnum
from sims4.tuning.tunable import TunableList, TunableMapping, TunableEnumEntry, TunableTuple, Tunable
from sims4.tuning.tunable_base import ExportModes
from singletons import DEFAULT
from world.spawn_point import SpawnPointOption
import server
import services
import sims
import sims4.log
import sims4.math
import terrain
logger = sims4.log.Logger('Sim Spawner')
disable_spawning_non_selectable_sims = False

class SimCreator:
    __qualname__ = 'SimCreator'

    def __init__(self, gender=None, age=None, first_name='', last_name='', full_name=None, tag_set=(), tunable_tag_set=None, resource_key=None):
        self.gender = random.choice(list(sim_info_types.Gender)) if gender is None else gender
        self.age = sim_info_types.Age.ADULT if age is None else age
        self.first_name = first_name
        self.last_name = last_name
        self.full_name_key = 0 if full_name is None else full_name.hash
        self.tag_set = list(tag_set)
        self.resource_key = resource_key
        if tunable_tag_set is not None:
            self.tag_set = [tag for tag in tunable_tag_set.tags]

    def build_creation_dictionary(self):
        sim_builder_dictionary = {}
        sim_builder_dictionary['age'] = self.age
        sim_builder_dictionary['gender'] = self.gender
        sim_builder_dictionary['tagSet'] = self.tag_set
        return sim_builder_dictionary

class Language(DynamicEnum, export_modes=ExportModes.All):
    __qualname__ = 'Language'
    ENGLISH = 0

DEFAULT_LOCALE = 'en-us'

class SimSpawner:
    __qualname__ = 'SimSpawner'
    SYSTEM_ACCOUNT_ID = 1
    LOCALE_MAPPING = TunableMapping(description="\n        A mapping of locale in terms of string to a sim name language in the\n        Language enum. This allows us to use the same random sim name\n        list for multiple locales. You can add new Language enum entries\n        in sims.sim_spawner's Language\n        ", key_name='locale_string', value_name='language', key_type=str, value_type=TunableEnumEntry(Language, Language.ENGLISH, export_modes=ExportModes.All), tuple_name='TunableLocaleMappingTuple', export_modes=ExportModes.All)

    class TunableRandomNamesForLanguage(TunableTuple):
        __qualname__ = 'SimSpawner.TunableRandomNamesForLanguage'

        def __init__(self):
            super().__init__(description='\n                A list of random names to be used for a specific language.\n                ', last_names=TunableList(description='\n                    A list of the random last names that can be assigned in CAS or\n                    to randomly generated NPCs.\n                    ', tunable=Tunable(description='\n                        A random last name.\n                        ', tunable_type=str, default='')), female_last_names=TunableList(description="\n                    If the specified languages differentiate last names\n                    according to gender, this list has to be non-empty. For\n                    every last name specified in the 'last_names' list, there\n                    must be a corresponding last name in this list.\n                    \n                    Randomly generated NPCs and NPC offspring will select the\n                    corresponding female version if necessary.\n                    ", tunable=Tunable(description="\n                        The female version of the last name at the corresponding\n                        index in the 'last_name' list.\n                        ", tunable_type=str, default='')), female_first_names=TunableList(description='\n                    A list of the random female first names that can be assigned\n                    in CAS or to randomly generated NPCs.\n                    ', tunable=Tunable(description='\n                        A random female first name.\n                        ', tunable_type=str, default='')), male_first_names=TunableList(description='\n                    A list of the random male first names that can be assigned\n                    in CAS or to randomly generated NPCs.\n                    ', tunable=Tunable(description='\n                        A random male first name.\n                        ', tunable_type=str, default='')))

    RANDOM_NAME_TUNING = TunableMapping(description="\n        A mapping of sim name language to lists of random family name and first\n        names appropriate for that language. This is used to generate random sim\n        names appropriate for each account's specified locale.\n        ", key_name='language', value_name='random_name_tuning', key_type=TunableEnumEntry(Language, Language.ENGLISH, export_modes=ExportModes.All), value_type=TunableRandomNamesForLanguage(), tuple_name='TunableRandomNameMappingTuple', export_modes=ExportModes.All)

    @classmethod
    def _get_random_name_tuning(cls, language):
        tuning = SimSpawner.RANDOM_NAME_TUNING.get(language)
        if tuning is None:
            tuning = SimSpawner.RANDOM_NAME_TUNING.get(Language.ENGLISH)
        return tuning

    @classmethod
    def get_random_first_name(cls, account, is_female) -> str:
        language = cls._get_language_for_locale(account)
        return cls._get_random_first_name(language, is_female)

    @classmethod
    def _get_random_first_name(cls, language, is_female) -> int:
        tuning = cls._get_random_name_tuning(language)
        name_list = tuning.female_first_names if is_female else tuning.male_first_names
        return random.choice(name_list)

    @classmethod
    def _get_random_family_name(cls, language) -> int:
        tuning = cls._get_random_name_tuning(language)
        return random.choice(tuning.last_names)

    @classmethod
    def get_family_name_for_gender(cls, account, family_name, is_female) -> str:
        language = cls._get_language_for_locale(account)
        return cls._get_family_name_for_gender(language, family_name, is_female)

    @classmethod
    def _get_family_name_for_gender(cls, language, family_name, is_female) -> str:
        tuning = cls._get_random_name_tuning(language)
        if family_name in tuning.female_last_names:
            if is_female:
                return family_name
            index = tuning.female_last_names.index(family_name)
            return tuning.last_names[index]
        if tuning.female_last_names and family_name in tuning.last_names:
            if not is_female:
                return family_name
            index = tuning.last_names.index(family_name)
            return tuning.female_last_names[index]
        return family_name

    @classmethod
    def _get_language_for_locale(cls, account) -> Language:
        locale = account.locale if account is not None else DEFAULT_LOCALE
        language = SimSpawner.LOCALE_MAPPING.get(locale, Language.ENGLISH)
        return language

    @classmethod
    def spawn_sim(cls, sim_info, sim_position:sims4.math.Vector3=None, sim_location=None, sim_spawner_tags=None, spawn_point_option=None, spawn_action=None, additional_fgl_search_flags=None, from_load=False, is_debug=False):
        if is_debug or disable_spawning_non_selectable_sims and not sim_info.is_selectable:
            return False
        try:
            sim_info.set_zone_on_spawn()
            if not from_load:
                sim_info.spawn_point_option = spawn_point_option if spawn_point_option is not None else SpawnPointOption.SPAWN_ANY_POINT_WITH_CONSTRAINT_TAGS
            services.sim_info_manager().add_sim_info_if_not_in_manager(sim_info)
            success = sim_info.create_sim_instance(sim_position, sim_spawner_tags=sim_spawner_tags, spawn_action=spawn_action, sim_location=sim_location, additional_fgl_search_flags=additional_fgl_search_flags, from_load=from_load)
            if success and sim_info.is_selectable:
                client = services.client_manager().get_client_by_household_id(sim_info.household.id)
                if client is not None:
                    client.selectable_sims.notify_dirty()
            return success
        except Exception:
            logger.exception('Exception while creating sims, sim_id={}; failed', sim_info.id)
            return False

    @classmethod
    def load_sim(cls, sim_id, startup_location=DEFAULT):
        sim_info = services.sim_info_manager().get(sim_id)
        if sim_info is None:
            return False
        if sim_info.is_baby:
            import sims.baby
            sims.baby.on_sim_spawn(sim_info)
            return False
        if startup_location is DEFAULT:
            startup_location = sim_info.startup_sim_location
        return cls.spawn_sim(sim_info, sim_location=startup_location, from_load=True)

    @classmethod
    def _get_default_account(cls):
        client = services.client_manager().get_first_client()
        if client is not None:
            account = client.account
            if account is not None:
                return account
        account = services.account_service().get_account_by_id(cls.SYSTEM_ACCOUNT_ID)
        if account is not None:
            return account
        account = server.account.Account(cls.SYSTEM_ACCOUNT_ID, 'SystemAccount')
        return account

    @classmethod
    def create_sim_infos(cls, sim_creators, household=None, starting_funds=DEFAULT, tgt_client=None, account=None, generate_deterministic_sim=False, zone_id=None, creation_source:str='Unknown'):
        sim_info_list = []
        if account is None:
            account = cls._get_default_account()
        if household is None:
            household = sims.household.Household(account, starting_funds=starting_funds)
        sim_creation_dictionaries = tuple(sim_creator.build_creation_dictionary() for sim_creator in sim_creators)
        new_sim_data = generate_household(sim_creation_dictionaries=sim_creation_dictionaries, household_name=household.name, generate_deterministic_sim=generate_deterministic_sim)
        zone = services.current_zone()
        world_id = zone.world_id
        if zone_id is None:
            zone_id = zone.id
        language = cls._get_language_for_locale(account)
        family_name = cls._get_random_family_name(language)
        if household.id == 0:
            household.id = new_sim_data['id']
            services.household_manager().add(household)
            household.name = family_name
        for (index, sim_data) in enumerate(new_sim_data['sims']):
            sim_proto = serialization.SimData()
            sim_proto.ParseFromString(sim_data)
            first_name = sim_creators[index].first_name
            if not first_name and not sim_creators[index].full_name_key:
                first_name = cls._get_random_first_name(language, sim_proto.gender == Gender.FEMALE)
            last_name = sim_creators[index].last_name
            if not last_name and not sim_creators[index].full_name_key:
                last_name = cls._get_family_name_for_gender(language, family_name, sim_proto.gender == Gender.FEMALE)
            sim_proto.first_name = first_name
            sim_proto.last_name = last_name
            sim_proto.full_name_key = sim_creators[index].full_name_key
            sim_proto.age = sim_creators[index].age
            sim_proto.zone_id = zone_id
            sim_proto.world_id = world_id
            sim_proto.household_id = household.id
            sim_proto.gameplay_data.creation_source = creation_source
            sim_info = sims.sim_info.SimInfo(sim_proto.sim_id, account=account)
            sim_info.load_sim_info(sim_proto)
            if sim_creators[index].resource_key:
                sim_info.load_from_resource(sim_creators[index].resource_key)
                if not sim_info.first_name:
                    sim_info.first_name = sim_proto.first_name
                if not sim_info.last_name:
                    sim_info.last_name = sim_proto.last_name
                if not sim_info.full_name_key:
                    sim_info.full_name_key = sim_proto.full_name_key
            household.add_sim_info(sim_info)
            sim_info.assign_to_household(household)
            sim_info.save_sim()
            sim_info_list.append(sim_info)
            if tgt_client is not None and household is tgt_client.household:
                logger.info('Added {} Sims to the current client', len(sim_creators))
                tgt_client.set_next_sim()
            else:
                logger.info('Added {} Sims to household ID {}.', len(sim_creators), household.id)
            logger.info('Create Sims, sim_number={}; succeeded', len(sim_creators))
        household.save_data()
        return (sim_info_list, household)

    @classmethod
    def create_sims(cls, sim_creators, household=None, tgt_client=None, generate_deterministic_sim=False, sim_position:sims4.math.Vector3=None, sim_spawner_tags=None, account=None, is_debug=False, skip_offset=False, additional_fgl_search_flags=None, creation_source:str='Unknown'):
        (sim_info_list, _) = cls.create_sim_infos(sim_creators, household=household, starting_funds=DEFAULT, tgt_client=tgt_client, account=account, generate_deterministic_sim=generate_deterministic_sim)
        offset = 0.0
        for sim_info in sim_info_list:
            if sim_position is not None:
                sim_position = sims4.math.Vector3(*sim_position)
                if not skip_offset:
                    offset = 2.0
                sim_position.y = terrain.get_terrain_height(sim_position.x, sim_position.z)
            if is_debug:
                services.get_zone_situation_manager().add_debug_sim_id(sim_info.id)
            cls.spawn_sim(sim_info, sim_position, sim_spawner_tags=sim_spawner_tags, additional_fgl_search_flags=additional_fgl_search_flags, is_debug=is_debug)
            while sim_info.account is not None and tgt_client is not None:
                tgt_client.add_selectable_sim_info(sim_info)

