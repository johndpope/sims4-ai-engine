import collections
from native.animation import get_joint_transform_from_rig, get_joint_name_for_hash_from_rig
from sims4.hash_util import hash32
from sims4.math import Transform
from sims4.repr_utils import standard_repr
from sims4.tuning.instances import TunedInstanceMetaclass
from sims4.tuning.tunable import Tunable, TunableReference, TunableSet, OptionalTunable, TunableList, TunableTuple, HasTunableReference
from sims4.tuning.tunable_base import ExportModes
from sims4.utils import classproperty, Result
from singletons import EMPTY_SET, DEFAULT
import animation
import build_buy
import services
import sims4.log
import sims4.resources
logger = sims4.log.Logger('Slots')

class SlotHeight:
    __qualname__ = 'SlotHeight'
    RANGES = TunableList(TunableTuple(parameter=Tunable(str, None, description='The ASM parameter corresponding to this height range.'), upper_bound=Tunable(float, 0, description='The upper bound of the range defining this height interval.')), description='A sorted list of ranges defining height parameters for use in ASMs.')

class SlotTypeReferences:
    __qualname__ = 'SlotTypeReferences'
    SIT_EAT_SLOT = TunableReference(description='\n        A reference to the SIT_EAT SlotType.\n        ', manager=services.get_instance_manager(sims4.resources.Types.SLOT_TYPE))

class DecorativeSlotTuning:
    __qualname__ = 'DecorativeSlotTuning'
    DECORATIVE_SLOT_TYPES = TunableList(TunableReference(services.get_instance_manager(sims4.resources.Types.SLOT_TYPE)), description='The list of gameplay-only slot types. There must be an entry for each possible decorative slot size.')
    _NO_SLOTS = EMPTY_SET

    @classmethod
    def get_slot_types_for_object(cls, deco_size):
        if deco_size == 0:
            return cls._NO_SLOTS
        deco_size -= 1
        return frozenset(cls.DECORATIVE_SLOT_TYPES[deco_size:])

    @classmethod
    def get_slot_types_for_slot(cls, deco_size):
        if deco_size == 0:
            return cls._NO_SLOTS
        deco_size -= 1
        return frozenset(cls.DECORATIVE_SLOT_TYPES[:deco_size + 1])

    @classmethod
    def slot_types_are_all_decorative(cls, slot_types):
        if not slot_types:
            return False
        if not slot_types.issubset(cls.DECORATIVE_SLOT_TYPES):
            return False
        return True

def get_surface_height_parameter_for_height(height):
    for height_range in SlotHeight.RANGES:
        while height <= height_range.upper_bound:
            break
    return height_range.parameter

def get_surface_height_parameter_for_object(obj):
    if obj.is_in_inventory():
        return 'inventory'
    terrain_height = services.terrain_service.terrain_object().get_routing_surface_height_at(obj.position.x, obj.position.z, obj.routing_surface)
    height = obj.position.y - terrain_height
    return get_surface_height_parameter_for_height(height)

def get_slot_transform(surface, slot_name):
    raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
    slot_transform = get_joint_transform_from_rig(surface.rig, slot_name)
    slot_transform = Transform.concatenate(slot_transform, surface.transform)
    return slot_transform

def get_slot_type_for_bone_name_hash(bone_name_hash):
    for slot_type in services.slot_type_manager().types.values():
        while slot_type.bone_name_hash == bone_name_hash:
            return slot_type

def get_slot_type_set_from_key(key):
    if key.instance:
        return services.slot_type_set_manager().get(key)

class SlotType(HasTunableReference, metaclass=TunedInstanceMetaclass, manager=services.slot_type_manager()):
    __qualname__ = 'SlotType'
    INSTANCE_TUNABLES = {'_bone_name': OptionalTunable(Tunable(str, None, description='The name of the bone this slot is associated to.'), enabled_name='referenced_by_animation', disabled_name='not_referenced_by_animation'), 'is_surface': Tunable(bool, True, description='\n                             This should be checked if objects can be placed in this slot by Sims \n                             or if having this slot would imply the object is considered a surface, \n                             such as slots for chairs.')}
    bone_name_hash = None

    def __repr__(self):
        return '<SlotType: {} {}>'.format(type(self).__name__, self._bone_name)

    def __str__(self):
        return '{}: {}'.format(type(self).__name__, self._bone_name)

    @classmethod
    def _tuning_loaded_callback(cls):
        cls.slot_type = cls
        if cls._bone_name:
            cls.bone_name_hash = hash32(cls._bone_name)

    @classproperty
    def is_deco_slot(cls):
        return cls.slot_type in DecorativeSlotTuning.DECORATIVE_SLOT_TYPES

class SlotTypeSet(metaclass=TunedInstanceMetaclass, manager=services.slot_type_set_manager()):
    __qualname__ = 'SlotTypeSet'
    INSTANCE_TUNABLES = {'slot_types': TunableSet(TunableReference(services.slot_type_manager()), export_modes=ExportModes.All, description='The slot types comprising this set.'), 'search_radius': Tunable(float, 0.5, description='Number of meters to search for co-located slots with different orientations.', export_modes=ExportModes.All), 'user_facing': Tunable(description='\n                             True if this slot will be available for slotting \n                             objects by the player through livedrag or Build \n                             buy.  \n                             False if its only through gameplay interactions.\n                             ', tunable_type=bool, default=True, export_modes=ExportModes.All)}

class RuntimeSlot(collections.namedtuple('_RuntimeSlot', ('owner', 'slot_name_hash', 'slot_types'))):
    __qualname__ = 'RuntimeSlot'

    @property
    def children(self):
        children = []
        for child in self.owner.children:
            while self.slot_name_hash == child.location.slot_hash or child.location.joint_name_hash:
                children.append(child)
        return children

    @property
    def empty(self):
        return not bool(self.children)

    def contains_object(self, obj):
        return obj in self.children

    @property
    def decorative(self):
        return DecorativeSlotTuning.slot_types_are_all_decorative(self.slot_types)

    @property
    def location(self):
        joint_transform = get_joint_transform_from_rig(self.owner.rig, self.slot_name_hash)
        return sims4.math.Location(joint_transform, None, parent=self.owner, slot_hash=self.slot_name_hash)

    @property
    def transform(self):
        return self.location.world_transform

    @property
    def position(self):
        return self.transform.translation

    @property
    def routing_surface(self):
        return self.owner.routing_surface

    @property
    def slot_height_and_parameter(self):
        position = self.position
        terrain_height = services.terrain_service.terrain_object().get_routing_surface_height_at(position.x, position.z, self.routing_surface)
        height = position.y - terrain_height
        return (height, get_surface_height_parameter_for_height(height))

    def add_child(self, child, joint_name_or_hash=None):
        if joint_name_or_hash is None:
            child.set_parent(self.owner, self.location.transform, slot_hash=self.slot_name_hash)
        else:
            child.set_parent(self.owner, None, joint_name_or_hash=joint_name_or_hash)

    def is_valid_for_placement(self, *, obj=DEFAULT, definition=DEFAULT, objects_to_ignore=DEFAULT):
        if obj is DEFAULT:
            obj = None
        elif obj in animation.posture_manifest._NOT_SPECIFIC_ACTOR:
            return Result(False, 'Cannot test placement for a non specific actor obj: {}'.format(obj), None)
        if definition is DEFAULT:
            definition = obj.definition
        if objects_to_ignore is DEFAULT:
            objects_to_ignore = None
        (result, errors, blocking_objects) = build_buy.test_location_for_object(obj, definition.id, self.location, objects_to_ignore, return_blocking_object_ids=True)
        return Result(result, errors, obj)

    @property
    def slot_name_or_hash(self):
        if not self.slot_name_hash:
            return '(ROOT)'
        try:
            slot_name_or_hash = get_joint_name_for_hash_from_rig(self.owner.rig, self.slot_name_hash)
        except KeyError:
            slot_name_or_hash = '{:#010x}'.format(self.slot_name_hash)
        return slot_name_or_hash

