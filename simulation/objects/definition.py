from functools import total_ordering
from build_buy import get_object_catalog_name, get_object_catalog_description, get_object_is_deletable, get_object_can_depreciate
from protocolbuffers.Localization_pb2 import LocalizedStringToken
from sims4.repr_utils import standard_angle_repr
from singletons import UNSET
import build_buy
import sims4.log
import sims4.resources
logger = sims4.log.Logger('Objects')

@total_ordering
class Definition:
    __qualname__ = 'Definition'
    _name = UNSET

    def __init__(self, properties, definition_id):
        self.id = definition_id

        def get_string(key, default=''):
            try:
                return properties.read_string8(key)
            except KeyError:
                return default

        def get_float(key, default=0):
            try:
                return properties.read_float(key)
            except KeyError:
                return default

        def get_uint32(key, default=0):
            try:
                return properties.read_uint32(key)
            except KeyError:
                return default

        def get_uint32_array(key, default=()):
            try:
                return properties.read_uint32s(key)
            except KeyError:
                return default

        def get_uint16_array(key, default=()):
            try:
                return properties.read_uint16s(key)
            except KeyError:
                return default

        def get_float_array(key, default=()):
            try:
                return properties.read_floats(key)
            except KeyError:
                return default

        def get_int64(key, default=0):
            try:
                return properties.read_int64(key)
            except KeyError:
                return default

        def get_key_property_hash32fallback(key, res_type, group):
            try:
                return properties.resourceKeys(key)
            except KeyError:
                try:
                    return (sims4.resources.Key.hash32(properties.string8(key), res_type, group),)
                except KeyError:
                    return (sims4.resources.Key(),)

        def get_key_property_hash64fallback(key, res_type, group):
            try:
                return properties.resourceKeys(key)
            except KeyError:
                try:
                    return (sims4.resources.Key.hash64(properties.string8(key), res_type, group),)
                except KeyError:
                    return (sims4.resources.Key(),)

        try:
            self._components = properties.uint32s('Components')
        except KeyError:
            self._components = None
        self._icon = get_key_property_hash64fallback('Icon', res_type=sims4.resources.Types.PNG, group=0)
        self._model = get_key_property_hash64fallback('Model', res_type=sims4.resources.Types.MODEL, group=0)
        material_variant_name = get_string('MaterialVariant')
        if material_variant_name:
            self._material_variant = sims4.hash_util.hash32(material_variant_name)
        else:
            self._material_variant = None
        self._thumbnail_geo_state_hash = get_uint32('ThumbnailGeometryState')
        self._rig = get_key_property_hash64fallback('Rig', res_type=sims4.resources.Types.RIG, group=0)
        self._footprint = get_key_property_hash64fallback('Footprint', res_type=sims4.resources.Types.FOOTPRINT, group=0)
        self._tuning_file_id = get_int64('TuningId')
        self._slot = get_key_property_hash64fallback('Slot', res_type=sims4.resources.Types.SLOT, group=0)

        def get_slot_resource(key):
            if key == sims4.resources.INVALID_KEY:
                return
            try:
                return sims4.ObjectSlots(key)
            except KeyError:
                return

        self._slots_resource = tuple(get_slot_resource(key) for key in self._slot)
        self._catalog_price = get_uint32('SimoleonPrice', default=100)
        self._environment_mood_tags = get_uint16_array('EnvironmentScoreEmotionTags')
        self._environment_scores = get_float_array('EnvironmentScores')
        self._negative_environment_score = get_float('NegativeEnvironmentScore')
        self._positive_environment_score = get_float('PositiveEnvironmentScore')
        if len(self._environment_mood_tags) != len(self._environment_scores):
            logger.error('Catalog Object {} Environment Score Tags do not line up with Scores.', self.name)
        self.build_buy_tags = frozenset()
        self._cls = None

    def __repr__(self):
        return standard_angle_repr(self, self.name or self.id)

    def __eq__(self, other):
        if type(other) != type(self):
            return False
        return (self.id, self.cls.__name__) == (other.id, other.cls.__name__)

    def __lt__(self, other):
        if type(other) != type(self):
            return NotImplemented
        return (self.id, self.cls.__name__) < (other.id, other.cls.__name__)

    def __hash__(self):
        return hash(self.id) ^ hash(self.cls.__name__)

    @property
    def name(self):
        if self._name is not UNSET:
            return self._name
        key = sims4.resources.Key(sims4.resources.Types.OBJECTDEFINITION, self.id)
        name = None
        try:
            name = sims4.hash_util.unhash(key.instance, table_type=sims4.hash_util.KEYNAMEMAPTYPE_OBJECTINSTANCES)
            name = name.replace('#', '')
        except:
            name = sims4.resources.get_name_from_key(key).split('.')[0]
            if name.startswith('0x'):
                name = None
        self._name = name
        return name

    @property
    def definition(self):
        return self

    @property
    def components(self):
        return self._components

    @property
    def icon(self):
        return self._icon[0]

    def get_model(self, index):
        return self._model[index]

    @property
    def material_variant(self):
        return self._material_variant

    def get_rig(self, index):
        return self._safe_index(self._rig, index)

    def get_footprint(self, index=0):
        return self._safe_index(self._footprint, index)

    def get_slot(self, index):
        return self._safe_index(self._slot, index)

    def get_slots_resource(self, index):
        return self._safe_index(self._slots_resource, index)

    @staticmethod
    def _safe_index(array, index):
        if not array:
            return
        if len(array) == 1:
            return array[0]
        return array[index]

    @property
    def tuning_file_id(self):
        return self._tuning_file_id

    @property
    def price(self):
        return self._catalog_price

    @property
    def environment_score_mood_tags(self):
        return self._environment_mood_tags

    @property
    def environment_scores(self):
        return self._environment_scores

    @property
    def negative_environment_score(self):
        return self._negative_environment_score

    @property
    def positive_environment_score(self):
        return self._positive_environment_score

    @property
    def thumbnail_geo_state_hash(self):
        return self._thumbnail_geo_state_hash

    def is_in_sim_inventory(self, sim=None):
        return False

    @property
    def allowed_hands(self):
        return self._cls.allowed_hands

    @property
    def parent(self):
        pass

    @property
    def parent_slot(self):
        pass

    def has_component(self, name_or_tuple):
        return False

    @property
    def cls(self):
        return self._cls

    def assign_build_buy_tags(self):
        tags = build_buy.get_object_all_tags(self.id)
        if tags is not None:
            self.build_buy_tags = frozenset(tags)

    def has_build_buy_tag(self, tag):
        if tag in self.build_buy_tags:
            return True
        return False

    def get_is_deletable(self):
        return get_object_is_deletable(self.id)

    def get_can_depreciate(self):
        return get_object_can_depreciate(self.id)

    def mro(self):
        return self.cls.mro()

    def populate_localization_token(self, token):
        token.type = LocalizedStringToken.OBJECT
        token.catalog_name_key = get_object_catalog_name(self.id)
        token.catalog_description_key = get_object_catalog_description(self.id)

    def set_class(self, cls):
        self._cls = cls

    def instantiate(self, cls_override=None, obj_state=0, **kwargs):
        cls = cls_override or self._cls
        result = cls(self, obj_state=obj_state, **kwargs)
        return result

    def is_similar(self, new_definition, ignore_rig_footprint=False):
        if self.tuning_file_id != new_definition.tuning_file_id:
            return (False, 'definition.is_similar: tuning_file_id: {} != tuning_file_id: {}'.format(self.tuning_file_id, new_definition.tuning_file_id))
        if self._components != new_definition._components:
            return (False, 'definition.is_similar: components: {} != components: {}'.format(self._components, new_definition._components))
        if self._rig != new_definition._rig:
            return (False, 'definition.is_similar: rig: {} != rig: {}'.format(self._rig, new_definition._rig))
        if ignore_rig_footprint or self._footprint != new_definition._footprint:
            return (False, 'definition.is_similar: footprint: {} != footprint: {}'.format(self._footprint, new_definition._footprint))
        return (True, True)

