from _weakrefset import WeakSet
from native.animation import get_joint_transform_from_rig
from weakref import WeakKeyDictionary
from interactions.utils.animation import ArbElement
from interactions.utils.routing import RouteTargetType
from objects.components.slot_component import SlotComponent
from objects.mixins import UseListMixin
from objects.proxy import ProxyObject
from objects.slots import RuntimeSlot, DecorativeSlotTuning
from postures.posture import TunablePostureTypeListSnippet
from postures.posture_specs import BODY_INDEX, BODY_POSTURE_TYPE_INDEX
from sims4.hash_util import hash32
from sims4.math import Transform
from sims4.tuning.instances import TunedInstanceMetaclass
from sims4.tuning.tunable import TunableList, TunableReference, OptionalTunable, Tunable
from sims4.tuning.tunable_base import ExportModes
from sims4.utils import Result
from singletons import DEFAULT
from snippets import TunableAffordanceFilterSnippet
import services
import sims4.callback_utils
import sims4.log
logger = sims4.log.Logger('Parts')

def purge_cache():
    ObjectPart._bone_names_for_part_suffices = None
    ObjectPart._bone_name_hashes_for_part_suffices = None

sims4.callback_utils.add_callbacks(sims4.callback_utils.CallbackEvent.TUNING_CODE_RELOAD, purge_cache)

class Part(ProxyObject, UseListMixin):
    __qualname__ = 'Part'
    _unproxied_attributes = ProxyObject._unproxied_attributes | {'_data', '_reservations', '_reservations_multi', '_joint_transform', '_routing_context', '_children_cache', '_is_surface', '_parts'}

    def __init__(self, owner, data):
        super().__init__(owner)
        self._data = data
        self._reservations = WeakKeyDictionary()
        self._reservations_multi = WeakKeyDictionary()
        self._joint_transform = None
        self._routing_context = None
        self._children_cache = None
        self._is_surface = {}

    def __repr__(self):
        proxied_obj = self.get_proxied_obj()
        if proxied_obj is None:
            return '<Part of Garbage Collected Object>'
        return '<part {0} on {1}>'.format(self.part_group_index, proxied_obj)

    def __str__(self):
        proxied_obj = self.get_proxied_obj()
        if proxied_obj is None:
            return '<Part of Garbage Collected Object>'
        return '{}[{}]'.format(proxied_obj, self.part_group_index)

    @property
    def is_part(self):
        return True

    @property
    def parts(self):
        pass

    @property
    def _parts(self):
        raise AttributeError()

    part_owner = ProxyObject.proxied_obj

    @property
    def part_group_index(self):
        return self.part_owner.parts.index(self)

    @property
    def part_definition(self):
        return self._data.part_definition

    @property
    def disable_sim_aop_forwarding(self):
        return self._data.disable_sim_aop_forwarding

    @property
    def disable_child_aop_forwarding(self):
        return self._data.disable_child_aop_forwarding

    @property
    def forward_direction_for_picking(self):
        offset = self._data.forward_direction_for_picking
        return sims4.math.Vector3(offset.x, 0, offset.y)

    @property
    def transform(self):
        if self.subroot_index is None:
            return self.part_owner.transform
        if self._joint_transform is None:
            target_root_joint = ArbElement._BASE_ROOT_STRING + str(self.subroot_index)
            try:
                self._joint_transform = get_joint_transform_from_rig(self.rig, target_root_joint)
            except KeyError:
                raise KeyError('Unable to find joint {} on {}'.format(target_root_joint, self))
        return Transform.concatenate(self._joint_transform, self.part_owner.transform)

    @transform.setter
    def transform(self):
        raise AttributeError("A part's Transform should never be set by hand. Only the part owner's transform should be set.")

    @property
    def routing_location(self):
        return self.get_routing_location_for_transform(self.transform)

    def on_children_changed(self):
        self._children_cache = None

    def _add_child(self, child):
        self.part_owner._add_child(child)
        self.on_children_changed()

    def _remove_child(self, child):
        self.part_owner._remove_child(child)
        self.on_children_changed()

    @property
    def children(self):
        if self._children_cache is None:
            self._children_cache = WeakSet({child for child in self.part_owner.children if self.has_slot(child.location.slot_hash or child.location.joint_name_hash)})
        return self._children_cache

    @property
    def routing_context(self):
        return self.part_owner.routing_context

    @property
    def supported_posture_types(self):
        return self.part_definition.supported_posture_types

    @property
    def _anim_overrides_internal(self):
        overrides = super()._anim_overrides_internal
        if self._data.anim_overrides:
            overrides = overrides(self._data.anim_overrides())
        return overrides

    def reset(self, reset_reason):
        super().reset(reset_reason)
        self.part_owner.reset(reset_reason)

    def adjacent_parts_gen(self):
        if self._data.adjacent_parts is not None:
            parts = self.part_owner.parts
            for adjacent_part_index in self._data.adjacent_parts:
                yield parts[adjacent_part_index]
        else:
            index = self.part_group_index
            parts = self.part_owner.parts
            if index > 0:
                yield parts[index - 1]
            if index + 1 < len(parts):
                yield parts[index + 1]

    def has_adjacent_part(self, sim):
        for part in self.adjacent_parts_gen():
            while part.may_reserve(sim):
                return True
        return False

    def is_mirrored(self, part=None):
        if part is None:
            return self._data.is_mirrored
        return self.part_group_index > part.part_group_index

    @property
    def route_target(self):
        return (RouteTargetType.PARTS, (self,))

    @property
    def is_base_part(self):
        return self.subroot_index is None

    @property
    def subroot_index(self):
        if self._data is None:
            return
        return self._data.subroot_index

    @property
    def part_suffix(self) -> str:
        subroot_index = self.subroot_index
        if subroot_index is not None:
            return str(subroot_index)

    def supports_affordance(self, affordance):
        if affordance.enable_on_all_parts_by_default:
            return True
        supported_affordance = self.part_definition.supported_affordance
        if supported_affordance is None:
            return True
        return supported_affordance(affordance)

    def supports_posture_type(self, posture_type, interaction=None):
        if interaction is not None and not self.supports_affordance(interaction.affordance):
            return False
        if posture_type is not None:
            part_supported_posture_types = None
            if self.part_definition:
                part_supported_posture_types = self.part_definition.supported_posture_types
            if part_supported_posture_types:
                for supported_posture_info in part_supported_posture_types:
                    while posture_type is supported_posture_info.posture_type:
                        return True
                return False
        return True

    def supports_posture_spec(self, posture_spec, interaction=None):
        if interaction is not None and interaction.is_super:
            affordance = interaction.affordance
            if affordance.requires_target_support and not self.supports_affordance(affordance):
                return False
        part_supported_posture_types = None
        if self.part_definition:
            part_supported_posture_types = self.part_definition.supported_posture_types
        if part_supported_posture_types:
            body_index = BODY_INDEX
            body_posture_type_index = BODY_POSTURE_TYPE_INDEX
            for supported_posture_info in part_supported_posture_types:
                while posture_spec[body_index] is None or posture_spec[body_index][body_posture_type_index] is supported_posture_info.posture_type:
                    return True
            return False
        return True

    @property
    def _bone_name_hashes(self):
        part_defintion = self.part_definition
        if part_defintion is None:
            raise ValueError('Invalid part definition for part {}'.format(self))
        result = part_defintion.get_bone_name_hashes_for_part_suffix(self.part_suffix)
        if self.is_base_part:
            result |= self.part_owner.get_deco_slot_hashes()
        return result

    def get_provided_slot_types(self):
        return self.part_owner.get_provided_slot_types(part=self)

    def get_runtime_slots_gen(self, slot_types=None, bone_name_hash=None, owner_only=False):
        for (slot_hash, slot_slot_types) in self.get_containment_slot_infos():
            if slot_types is not None and not slot_types.intersection(slot_slot_types):
                pass
            if bone_name_hash is not None and slot_hash != bone_name_hash:
                pass
            is_deco = DecorativeSlotTuning.slot_types_are_all_decorative(slot_slot_types)
            while is_deco and (self.is_base_part or self.has_slot(slot_hash)):
                yield RuntimeSlot(self, slot_hash, slot_slot_types)

    def slot_object(self, parent_slot=None, slotting_object=None):
        return self.part_owner.slot_object(parent_slot=parent_slot, slotting_object=slotting_object, target=self)

    def get_containment_slot_infos(self):
        owner = self.part_owner
        object_slots = owner.slots_resource
        if object_slots is None:
            return []
        result = SlotComponent.get_containment_slot_infos_static(object_slots, owner.rig, owner)
        bone_name_hashes = self._bone_name_hashes
        return [(slot_hash, slot_types) for (slot_hash, slot_types) in result if slot_hash in bone_name_hashes]

    def is_valid_for_placement(self, *, obj=DEFAULT, definition=DEFAULT, objects_to_ignore=DEFAULT):
        result = Result.NO_RUNTIME_SLOTS
        for runtime_slot in self.get_runtime_slots_gen():
            result = runtime_slot.is_valid_for_placement(obj=obj, definition=definition, objects_to_ignore=objects_to_ignore)
            while result:
                break
        return result

    def _find_slot_name(self, slot_type, check_occupied=False):
        slot_name = slot_type._bone_name + self.part_suffix
        if check_occupied:
            slot_hash = hash32(slot_name)
            for child in self.children:
                while child.location.joint_name_hash == slot_hash:
                    return
        return slot_name

    def has_slot(self, slot_hash):
        return slot_hash in self._bone_name_hashes

    def get_overlapping_parts(self):
        if self._data.overlapping_parts is None:
            return []
        parts = self.part_owner.parts
        return [parts[overlapping_part_index] for overlapping_part_index in self._data.overlapping_parts]

    @property
    def footprint(self):
        return self.part_owner.footprint

    @property
    def footprint_polygon(self):
        return self.part_owner.footprint_polygon

    def on_leaf_child_changed(self):
        self.part_owner.on_leaf_child_changed()

class ObjectPart(metaclass=TunedInstanceMetaclass, manager=services.object_part_manager()):
    __qualname__ = 'ObjectPart'
    INSTANCE_TUNABLES = {'supported_posture_types': TunablePostureTypeListSnippet(description='The postures supported by this part. If empty, assumes all postures are supported.'), 'supported_affordance': OptionalTunable(TunableAffordanceFilterSnippet(description='Affordances supported by the part')), 'bone_names': TunableList(Tunable(str, '_ctnm_XXX_'), description='The list of bone names that make up this part.'), 'subroot': TunableReference(services.subroot_manager(), description='The reference of the subroot definition in the part.')}
    _bone_names_for_part_suffices = None
    _bone_name_hashes_for_part_suffices = None

    @classmethod
    def get_bone_names_for_part_suffix(cls, part_suffix):
        if cls._bone_names_for_part_suffices is None:
            cls._bone_names_for_part_suffices = {}
        if part_suffix in cls._bone_names_for_part_suffices:
            return cls._bone_names_for_part_suffices[part_suffix]
        subroot_bone_names = []
        if cls.subroot is not None:
            subroot_bone_names = cls.subroot.bone_names
        else:
            subroot_bone_names = cls.bone_names
        if part_suffix:
            bone_names = frozenset(bone_name + part_suffix for bone_name in subroot_bone_names)
        else:
            bone_names = frozenset(subroot_bone_names)
        cls._bone_names_for_part_suffices[part_suffix] = bone_names
        return bone_names

    @classmethod
    def get_bone_name_hashes_for_part_suffix(cls, part_suffix):
        if cls._bone_name_hashes_for_part_suffices is None:
            cls._bone_name_hashes_for_part_suffices = {}
        if part_suffix in cls._bone_name_hashes_for_part_suffices:
            return cls._bone_name_hashes_for_part_suffices[part_suffix]
        bone_names = cls.get_bone_names_for_part_suffix(part_suffix)
        bone_name_hashes = frozenset(hash32(bone_name) for bone_name in bone_names)
        cls._bone_name_hashes_for_part_suffices[part_suffix] = bone_name_hashes
        return bone_name_hashes

class Subroot(metaclass=TunedInstanceMetaclass, manager=services.subroot_manager()):
    __qualname__ = 'Subroot'
    INSTANCE_TUNABLES = {'bone_names': TunableList(Tunable(str, '_ctnm_XXX_'), export_modes=ExportModes.All, description='The list of bone names that make up this subroot.')}

