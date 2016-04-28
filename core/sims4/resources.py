from _resourceman import *
import io
import os
import _resourceman
import enum
import protocolbuffers
import sims4.callback_utils
import sims4.hash_util
import sims4.log
logger = sims4.log.Logger('Resources')
INVALID_KEY = Key(0, 0, 0)
sims4.callback_utils.add_callbacks(sims4.callback_utils.CallbackEvent.TUNING_CODE_RELOAD, purge_cache)

class InstanceTuningDefinition:
    __qualname__ = 'InstanceTuningDefinition'

    def __init__(self, type_name, type_name_plural=None, file_extension=None, resource_type=None, manager_name=None, use_guid_for_ref=True):
        if type_name_plural is None:
            type_name_plural = type_name + 's'
        if file_extension is None:
            file_extension = type_name
        if resource_type is None:
            resource_type = sims4.hash_util.hash32(file_extension)
        if manager_name is None:
            manager_name = type_name + '_manager'
        self.type_name = type_name
        self.TYPE_NAME = type_name.upper()
        self.TypeNames = type_name_plural.title().replace('_', '')
        self.file_extension = file_extension
        self.resource_type = resource_type
        self.manager_name = manager_name
        self.use_guid_for_ref = use_guid_for_ref

    @property
    def TYPE_ENUM_VALUE(self):
        return getattr(Types, self.TYPE_NAME)

INSTANCE_TUNING_DEFINITIONS = []
TYPE_RES_DICT = {}

class Types(enum.Int, export=False):
    __qualname__ = 'Types'

    def _add_inst_tuning(*args, **kwargs):
        definition = InstanceTuningDefinition(*args, **kwargs)
        INSTANCE_TUNING_DEFINITIONS.append(definition)
        TYPE_RES_DICT[definition.resource_type] = definition.file_extension
        return definition.resource_type

    INVALID = 4294967295
    MODEL = 23466547
    RIG = 2393838558
    FOOTPRINT = 3548561239
    SLOT = 3540272417
    OBJECTDEFINITION = 3235601127
    OBJCATALOG = 832458525
    MAGAZINECOLLECTION = 1946487583
    GPINI = 2249506521
    PNG = 796721156
    TGA = 796721158
    STATEMACHINE = 47570707
    PROPX = 968010314
    VP6 = 929579223
    BC_CACHE = 479834948
    AC_CACHE = 3794048034
    XML = 53690476
    TRACKMASK = 53633251
    CLIP = 1797309683
    CLIP_HEADER = 3158986820
    OBJDEF = 3625704905
    SIMINFO = 39769844
    SKINTONE = 55867754
    COMBINED_TUNING = 1659456824
    PLAYLIST = 1415235194
    TUNING = _add_inst_tuning('tuning', type_name_plural='tuning', file_extension='tun', resource_type=62078431, manager_name='module_tuning_manager')
    POSTURE = _add_inst_tuning('posture', resource_type=2909789983)
    SLOT_TYPE = _add_inst_tuning('slot_type', resource_type=1772477092, use_guid_for_ref=False)
    STATIC_COMMODITY = _add_inst_tuning('static_commodity', type_name_plural='static_commodities', file_extension='scommodity', resource_type=1359443523)
    RELATIONSHIP_BIT = _add_inst_tuning('relationship_bit', file_extension='relbit', resource_type=151314192)
    OBJECT_STATE = _add_inst_tuning('object_state', resource_type=1526890910)
    RECIPE = _add_inst_tuning('recipe', resource_type=3952605219)
    GAME_RULESET = _add_inst_tuning('game_ruleset', resource_type=3779558936)
    STATISTIC = _add_inst_tuning('statistic', resource_type=865846717)
    MOOD = _add_inst_tuning('mood', resource_type=3128647864)
    BUFF = _add_inst_tuning('buff', resource_type=1612179606)
    TRAIT = _add_inst_tuning('trait', resource_type=3412057543)
    SLOT_TYPE_SET = _add_inst_tuning('slot_type_set', resource_type=1058419973, use_guid_for_ref=False)
    PIE_MENU_CATEGORY = _add_inst_tuning('pie_menu_category', type_name_plural='pie_menu_categories', resource_type=65657188)
    ASPIRATION = _add_inst_tuning('aspiration', resource_type=683034229)
    ASPIRATION_CATEGORY = _add_inst_tuning('aspiration_category', type_name_plural='aspiration_categories', resource_type=3813727192)
    ASPIRATION_TRACK = _add_inst_tuning('aspiration_track', resource_type=3223387309)
    OBJECTIVE = _add_inst_tuning('objective', resource_type=6899006)
    TUTORIAL = _add_inst_tuning('tutorial', resource_type=3762955427)
    TUTORIAL_TIP = _add_inst_tuning('tutorial_tip', resource_type=2410930353)
    CAREER = _add_inst_tuning('career', resource_type=1939434475)
    INTERACTION = _add_inst_tuning('interaction', resource_type=3900887599, manager_name='affordance_manager')
    ACHIEVEMENT = _add_inst_tuning('achievement', resource_type=2018877086)
    ACHIEVEMENT_CATEGORY = _add_inst_tuning('achievement_category', type_name_plural='achievement_categories', resource_type=609337601)
    ACHIEVEMENT_REWARD = _add_inst_tuning('achievement_reward', resource_type=791891528)
    ACHIEVEMENT_COLLECTION = _add_inst_tuning('achievement_collection', resource_type=80917605)
    SERVICE_NPC = _add_inst_tuning('service_npc', resource_type=2629964386)
    VENUE = _add_inst_tuning('venue', use_guid_for_ref=False, resource_type=3871070174)
    REWARD = _add_inst_tuning('reward', resource_type=1873057832)
    TEST_BASED_SCORE = _add_inst_tuning('test_based_score', resource_type=1332976878)
    MAXIS_LOT = _add_inst_tuning('maxis_lot', resource_type=57040985)
    LOT_TUNING = _add_inst_tuning('lot_tuning', resource_type=3632270694)
    WALK_BY = _add_inst_tuning('walk_by', resource_type=1070998590)
    OBJECT = _add_inst_tuning('object', manager_name='definition_manager', resource_type=3055412916)
    SNIPPET = _add_inst_tuning('snippet', resource_type=2113017500)
    ANIMATION = _add_inst_tuning('animation', resource_type=3994535597)
    BALLOON = _add_inst_tuning('balloon', resource_type=3966406598)
    ACTION = _add_inst_tuning('action', resource_type=209137191)
    OBJECT_PART = _add_inst_tuning('object_part', resource_type=1900520272)
    SITUATION = _add_inst_tuning('situation', resource_type=4223905515)
    SITUATION_JOB = _add_inst_tuning('situation_job', resource_type=2617738591)
    SITUATION_GOAL = _add_inst_tuning('situation_goal', resource_type=1502554343)
    SITUATION_GOAL_SET = _add_inst_tuning('situation_goal_set', resource_type=2649944562)
    STRATEGY = _add_inst_tuning('strategy', resource_type=1646578134)
    SIM_FILTER = _add_inst_tuning('sim_filter', resource_type=1846401695)
    TOPIC = _add_inst_tuning('topic', resource_type=1938713686)
    SIM_TEMPLATE = _add_inst_tuning('sim_template', resource_type=212125579)
    SUBROOT = _add_inst_tuning('subroot', resource_type=3086978965)
    SOCIAL_GROUP = _add_inst_tuning('social_group', resource_type=776446212)
    TAG_SET = _add_inst_tuning('tag_set', resource_type=1228493570)
    TEMPLATE_CHOOSER = _add_inst_tuning('template_chooser', resource_type=1220728301)
    ROLE_STATE = _add_inst_tuning('role_state', resource_type=239932923)
    CAREER_LEVEL = _add_inst_tuning('career_level', resource_type=745582072)
    CAREER_TRACK = _add_inst_tuning('career_track', resource_type=1221024995)
    CAREER_SITUATION = _add_inst_tuning('career_situation', resource_type=4015637894)
    BROADCASTER = _add_inst_tuning('broadcaster', resource_type=3736796019)
    AWAY_ACTION = _add_inst_tuning('away_action', resource_type=2947394632)
    ROYALTY = _add_inst_tuning('royalty', resource_type=938421991)
    TDESC_DEBUG = _add_inst_tuning('tdesc_debug')
    TUNING_DESCRIPTION = 2519486516
    del _add_inst_tuning

class Groups(enum.Int, export=False):
    __qualname__ = 'Groups'
    INVALID = 4294967295

class CompoundTypes:
    __qualname__ = 'CompoundTypes'
    IMAGE = [Types.PNG]

extensions = {Types.TUNING_DESCRIPTION: 'tdesc'}
hot_swappable_type_ids = [Types.OBJECTDEFINITION]
for definition in INSTANCE_TUNING_DEFINITIONS:
    extensions[definition.TYPE_ENUM_VALUE] = definition.file_extension
    hot_swappable_type_ids.append(definition.TYPE_ENUM_VALUE)
for type_id in hot_swappable_type_ids:
    try:
        make_resource_hot_swappable(type_id)
    except RuntimeError:
        pass

def get_resource_key(potential_key, resource_type):
    if isinstance(potential_key, int):
        return Key(resource_type, potential_key)
    if isinstance(potential_key, str):
        try:
            instance_id = int(potential_key)
            return Key(resource_type, instance_id)
        except:
            file_portion = os.path.split(potential_key)[1]
            filename = os.path.splitext(file_portion)[0]
            resource_key = Key.hash64(filename, type=resource_type)
            return resource_key
    return potential_key

class ResourceKeyWrapper:
    __qualname__ = 'ResourceKeyWrapper'
    EXPORT_STRING = 'ResourceKey'

    def __new__(cls, data):
        data_tuple = data.split(':')
        if len(data_tuple) == 2:
            return Key.hash64(data_tuple[1], type=Types(data_tuple[0]), group=0)
        if len(data_tuple) == 3:
            return Key(int(data_tuple[0], 16), int(data_tuple[2], 16), int(data_tuple[1], 16))
        raise ValueError('Invalid string passed into TunableResource. Expected Type:Instance or Type:Instance:Group.')

class ResourceLoader:
    __qualname__ = 'ResourceLoader'

    def __init__(self, resource_key, resource_type=None):
        self.filename = resource_key
        if isinstance(resource_key, (str, int)):
            if resource_type is None:
                raise ValueError('Resource loader requires a resource_type when provided with a string: {}'.format(resource_key))
            resource_key = sims4.resources.get_resource_key(resource_key, resource_type)
        self.resource_key = resource_key

    def load(self, silent_fail=True):
        resource = None
        try:
            resource = sims4.resources.load(self.resource_key)
            return io.BytesIO(bytes(resource))
        except KeyError:
            if not silent_fail:
                log_name = self.filename
                logger.exception("File not found: '{}'", log_name)
            return

def get_debug_name(key, table_type=None):
    logger.error('Attempting to get a debug name in a non-debug build.')
    return ''

def get_all_resources_of_type(type_id):
    return sims4.resources.list(type=type_id)

def get_protobuff_for_key(key):
    if key is None:
        return
    resource_key = protocolbuffers.ResourceKey_pb2.ResourceKey()
    resource_key.type = key.type
    resource_key.group = key.group
    resource_key.instance = key.instance
    return resource_key

