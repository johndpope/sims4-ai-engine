from collections import namedtuple
from contextlib import contextmanager
import itertools
from objects.definition import Definition
from objects.slots import get_slot_type_for_bone_name_hash, SlotType, RuntimeSlot
from sims4.collections import ListSet, AttributeDict
from sims4.repr_utils import standard_repr
from sims4.utils import InternMixin
from singletons import UNSET
import enum
import services
import sims4.log
import sims4.resources
logger = sims4.log.Logger('Animation')
MATCH_NONE = '-'
MATCH_ANY = '*'
HOLSTER = '?'
UPPER_BODY = 'UpperBody'
FULL_BODY = 'FullBody'
_NOT_SPECIFIC_ACTOR = (None, MATCH_ANY, MATCH_NONE, HOLSTER)
MATCH_NONE_POSTURE_PARAM = ''
_NOT_SPECIFIC_POSTURE = (None, MATCH_NONE_POSTURE_PARAM, MATCH_ANY)
SORT_ORDER = {MATCH_NONE: 0, UPPER_BODY: 1, FULL_BODY: 2, HOLSTER: 4, MATCH_ANY: 5}
SORT_ORDER_DEFAULT = 3

class AnimationParticipant(enum.Int):
    __qualname__ = 'AnimationParticipant'
    __slots__ = ()
    ACTOR = 101
    CONTAINER = 102
    TARGET = 103
    CARRY_TARGET = 104
    CREATE_TARGET = 105
    SURFACE = 106

    def __str__(self):
        return self.name

class Hand(enum.Int):
    __qualname__ = 'Hand'
    __slots__ = ()
    LEFT = 1
    RIGHT = 2

    def __str__(self):
        return self.name

TYPE_ORDER = [(type(None), 0, None), (int, 1, None), (str, 2, None), (enum.Int, 3, lambda obj: (id(type(obj)), obj)), (type, 4, lambda obj: obj.__name__), (object, 5, lambda obj: obj.id)]

def _lt_get_type_order(value):
    for (_type, order, sub_order_fn) in TYPE_ORDER:
        while isinstance(value, _type):
            sub_order = value
            if sub_order_fn is not None:
                sub_order = sub_order_fn(value)
            return (order, sub_order)

def resolve_variables_and_objects(value0, value1):
    if hasattr(value0, 'id'):
        if hasattr(value1, 'id'):
            if value0.id == value1.id:
                if value0.is_part and not value1.is_part:
                    return (None, value0)
                if value1.is_part and not value0.is_part:
                    return (None, value1)
                return (False, None)
            return (False, None)
        return (None, value0)
    if hasattr(value1, 'id'):
        return (None, value1)
    return (None, value0)

_posture_name_to_posture_type_cache = None

def _get_posture_type_for_posture_name(name):
    global _posture_name_to_posture_type_cache
    if name in _NOT_SPECIFIC_POSTURE:
        return
    if _posture_name_to_posture_type_cache is None:
        posture_manager = services.get_instance_manager(sims4.resources.Types.POSTURE)
        if not posture_manager.all_instances_loaded:
            tuning_file_name = 'posture_' + name
            result = posture_manager.get(tuning_file_name)
            if result is None:
                logger.error("Posture referenced by name ({}) in startup path doesn't have a tuning file named exactly '{}', which it must have be referenced before the posture manager starts.", name, tuning_file_name, owner='jpollak')
                return UNSET
            return result
        _posture_name_to_posture_type_cache = {}
        for posture_type in posture_manager.types.values():
            posture_name = posture_type._posture_name
            while posture_name is not None:
                _posture_name_to_posture_type_cache[posture_name] = posture_type
    if name not in _posture_name_to_posture_type_cache:
        logger.error('Attempt to get a nonexistant posture type by name: {}', name, owner='maxr')
        return UNSET
    return _posture_name_to_posture_type_cache[name]

PostureManifestOverrideKey = namedtuple('PostureManifestOverrideKey', ('actor', 'specific', 'family', 'level'))
PostureManifestOverrideValue = namedtuple('PostureManifestOverrideValue', ('left', 'right', 'surface'))

class PostureManifestBase:
    __qualname__ = 'PostureManifestBase'
    __slots__ = ()

    def __str__(self):
        items = ', '.join(str(i) for i in self.in_best_order)
        return '{' + items + '}'

    def __repr__(self):
        items = ', '.join(repr(i) for i in self.in_best_order)
        return standard_repr(self, items)

    @property
    def in_best_order(self):
        return reversed(sorted(self))

    def intersection(self, other):
        if self is other:
            return self
        results = []
        for (entry0, entry1) in itertools.product(self, other):
            result = entry0.intersect(entry1)
            while result is not None:
                results.append(result)
        if results:
            return self.__class__(results)

    def intersection_single(self, entry):
        results = []
        for entry0 in self:
            result = entry0.intersect(entry)
            while result is not None:
                results.append(result)
        if results:
            return self.__class__(results)

    def frozen_copy(self):
        return FrozenPostureManifest(self)

    def get_holster_version(self):
        return type(self)(entry.get_holster_version() for entry in self)

    def get_constraint_version(self, for_actor=None):
        factory = type(self) if for_actor is None else PostureManifest
        return factory(entry.get_constraint_version(for_actor) for entry in self)

    def apply_actor_map(self, actor_map):
        return self.__class__(entry.apply_actor_map(actor_map) for entry in self)

class PostureManifest(PostureManifestBase, set):
    __qualname__ = 'PostureManifest'
    __slots__ = ()

    def intern(self):
        immutable_self = FrozenPostureManifest(entry.intern() for entry in self)
        return immutable_self.intern()

class FrozenPostureManifest(PostureManifestBase, frozenset, InternMixin):
    __qualname__ = 'FrozenPostureManifest'
    __slots__ = ()

    def frozen_copy(self):
        return self

@contextmanager
def ignoring_carry():
    old_value = PostureManifestEntry._attr_names_intersect_ignore
    try:
        PostureManifestEntry._attr_names_intersect_ignore = ('_left', '_right')
        yield None
    finally:
        PostureManifestEntry._attr_names_intersect_ignore = old_value

_PostureManifestEntry = namedtuple('_PostureManifestEntry', ('actor', 'specific', 'family', 'level', 'left', 'right', 'surface', 'provides'))

class PostureManifestEntry(_PostureManifestEntry, InternMixin):
    __qualname__ = 'PostureManifestEntry'
    __slots__ = ()
    _ATTR_NAMES_DEFAULT_INTERSECT = ('actor', 'left', 'right', 'surface')
    _attr_names_intersect_ignore = ()

    def __new__(cls, actor, specific, family, level, left, right, surface, provides=False, from_asm=False):
        if provides and from_asm:
            surface = MATCH_ANY
        if family == 'none':
            family = None
        return super().__new__(cls, actor or MATCH_ANY, specific or MATCH_NONE_POSTURE_PARAM, family or MATCH_NONE_POSTURE_PARAM, level or MATCH_NONE_POSTURE_PARAM, left or MATCH_ANY, right or MATCH_ANY, surface or MATCH_ANY, provides or False)

    def _with_overrides(self, **overrides):
        init_kwargs = dict(zip(self._fields, self))
        init_kwargs.update(overrides)
        return self.__class__(**init_kwargs)

    def apply_actor_map(self, actor_map):
        actor = actor_map(self.actor or AnimationParticipant.ACTOR, self.actor) or MATCH_ANY
        left = actor_map(self.left, self.left) or MATCH_ANY
        right = actor_map(self.right, self.right) or MATCH_ANY
        surface = self.surface
        if surface == '*':
            surface = AnimationParticipant.SURFACE
        surface = actor_map(surface, self.surface) or MATCH_ANY
        return self.__class__(actor, self.specific, self.family, self.level, left, right, surface, self.provides)

    def matches_override_key(self, override_key):
        (actor, specific, family, level) = override_key
        if actor != MATCH_ANY and (actor != MATCH_NONE or self.actor is not None):
            if self.actor != actor:
                return False
        if specific != MATCH_ANY and (specific != MATCH_NONE or self.specific is not None):
            if self.specific != specific:
                return False
        if family != MATCH_ANY and (family != MATCH_NONE or self.family is not None):
            if self.family != family:
                return False
        if level != MATCH_ANY and (level != MATCH_NONE or self.level is not None):
            if self.level != level:
                return False
        return True

    def get_entries_with_override(self, override_value):
        (left, right, surface) = override_value
        if surface is None:
            surface = self.surface
        if self.left == self.right and left not in _NOT_SPECIFIC_ACTOR and right not in _NOT_SPECIFIC_ACTOR:
            return [self._with_overrides(surface=surface, left=left), self._with_overrides(surface=surface, right=right)]
        if left is None or self.left == MATCH_ANY and left != MATCH_NONE:
            left = self.left
        if right is None or self.right == MATCH_ANY and right != MATCH_NONE:
            right = self.right
        return [self._with_overrides(surface=surface, left=left, right=right)]

    def get_holster_version(self):
        if len(self.free_hands) == 2:
            return self
        if self.left is None or self.left is MATCH_NONE:
            left = HOLSTER
        else:
            left = self.left
        if self.right is None or self.right is MATCH_NONE:
            right = HOLSTER
        else:
            right = self.right
        return self._with_overrides(left=left, right=right)

    def get_constraint_version(self, for_actor=None):
        if for_actor is None or self.actor not in _NOT_SPECIFIC_ACTOR:
            return self._with_overrides(level=MATCH_NONE_POSTURE_PARAM)
        return self._with_overrides(actor=for_actor, level=MATCH_NONE_POSTURE_PARAM)

    def intern(self):
        return super().intern()

    def __repr__(self):
        return standard_repr(self, str(self))

    def __str__(self):
        if self.actor not in _NOT_SPECIFIC_ACTOR:
            format_str = '{0.actor}:{0.posture_param_value_complete}({0.left},{0.right},{0.surface})'
        else:
            format_str = '{0.posture_param_value_complete}({0.left},{0.right},{0.surface})'
        return format_str.format(self)

    @staticmethod
    def _intersect_attr(value0, value1):
        if value0 == MATCH_ANY or value0 == HOLSTER:
            return value1
        if value1 == MATCH_ANY or value1 == HOLSTER:
            return value0
        if value0 == value1:
            return value0
        if not isinstance(value0, (str, int, Definition)) and not isinstance(value1, (str, int, Definition)):
            if value0.is_part and value1.parts and value0 in value1.parts:
                return value0
            if value1.is_part and value0.parts and value1 in value0.parts:
                return value1
        else:
            if isinstance(value0, int) and value1 != MATCH_NONE:
                return value1
            if isinstance(value1, int) and value1 != MATCH_NONE:
                return value0

    def _sort_key(self):
        return (SORT_ORDER.get(self.actor, SORT_ORDER_DEFAULT), _lt_get_type_order(self.actor), SORT_ORDER.get(self.specific, SORT_ORDER_DEFAULT), _lt_get_type_order(self.specific), SORT_ORDER.get(self.family, SORT_ORDER_DEFAULT), _lt_get_type_order(self.family), SORT_ORDER.get(self.level, SORT_ORDER_DEFAULT), _lt_get_type_order(self.level), SORT_ORDER.get(self.left, SORT_ORDER_DEFAULT), _lt_get_type_order(self.left), SORT_ORDER.get(self.right, SORT_ORDER_DEFAULT), _lt_get_type_order(self.right), SORT_ORDER.get(self.surface, SORT_ORDER_DEFAULT), _lt_get_type_order(self.surface), SORT_ORDER.get(self.provides, SORT_ORDER_DEFAULT), _lt_get_type_order(self.provides))

    def __lt__(self, other_manifest_entry):
        return self._sort_key() < other_manifest_entry._sort_key()

    @property
    def valid(self):
        if not (self.specific or self.family):
            return False
        uniques = None
        for e in (self.left, self.right, self.surface):
            if e in _NOT_SPECIFIC_ACTOR:
                pass
            if uniques and e in uniques:
                return False
            if uniques is None:
                uniques = set()
            uniques.add(e)
        return True

    def intersect(self, other_manifest_entry):
        init_kwargs = AttributeDict(zip(self._fields, self))
        for attr_name in self._ATTR_NAMES_DEFAULT_INTERSECT:
            if attr_name in self._attr_names_intersect_ignore:
                pass
            attr_value = self._intersect_attr(getattr(self, attr_name), getattr(other_manifest_entry, attr_name))
            if attr_value is None:
                return
            init_kwargs[attr_name] = attr_value
        provides0 = self.provides
        provides1 = other_manifest_entry.provides
        init_kwargs.provides = provides0 or provides1
        posture_type_specific0 = self.posture_type_specific
        posture_type_specific1 = other_manifest_entry.posture_type_specific
        posture_type_family0 = self.posture_type_family
        posture_type_family1 = other_manifest_entry.posture_type_family
        if self.specific == MATCH_ANY:
            posture_type_specific0 = posture_type_specific1
            init_kwargs.specific = other_manifest_entry.specific
        elif other_manifest_entry.specific == MATCH_ANY:
            posture_type_specific1 = posture_type_specific0
        if self.family == MATCH_ANY:
            posture_type_family0 = posture_type_family1
            init_kwargs.family = other_manifest_entry.family
        elif other_manifest_entry.family == MATCH_ANY:
            posture_type_family1 = posture_type_family0
        if posture_type_specific0 is not None or posture_type_specific1 is not None:
            result_should_have_family = posture_type_family0 is not None and posture_type_family1 is not None
        else:
            result_should_have_family = posture_type_family0 is not None or posture_type_family1 is not None
        if posture_type_family0 is None and posture_type_specific0 is not None:
            posture_type_family0 = _get_posture_type_for_posture_name(posture_type_specific0.family_name) or posture_type_specific0
        if posture_type_family1 is None and posture_type_specific1 is not None:
            posture_type_family1 = _get_posture_type_for_posture_name(posture_type_specific1.family_name) or posture_type_specific1
        if posture_type_specific0 != posture_type_specific1:
            if posture_type_specific0 is not None:
                if posture_type_specific1 is not None:
                    return
                    if posture_type_specific1 is not None:
                        init_kwargs.specific = other_manifest_entry.specific
            elif posture_type_specific1 is not None:
                init_kwargs.specific = other_manifest_entry.specific
        if posture_type_family0 != posture_type_family1:
            if posture_type_family0 is not None:
                if posture_type_family1 is not None:
                    return
                init_kwargs.family = posture_type_family0.name
            else:
                init_kwargs.family = posture_type_family1.name
        elif posture_type_family0 is not None:
            init_kwargs.family = posture_type_family0.name
        else:
            init_kwargs.family = MATCH_NONE_POSTURE_PARAM
        if not result_should_have_family:
            init_kwargs.family = MATCH_NONE_POSTURE_PARAM
        posture_type_specific = _get_posture_type_for_posture_name(init_kwargs.specific)
        if init_kwargs.specific and init_kwargs.family and posture_type_specific.family_name != init_kwargs.family:
            return
        init_kwargs.level = self._intersect_attr(self.level, other_manifest_entry.level)
        if init_kwargs.level is None:
            if provides0 == provides1:
                return
            level0 = self.level
            level1 = other_manifest_entry.level
            provided_level = level0 if provides0 else level1
            if provided_level == UPPER_BODY:
                return
            init_kwargs.level = UPPER_BODY
        result = self.__class__(**init_kwargs)
        if not result.valid:
            return
        return result

    @property
    def posture_param_value_specific(self):
        if self.specific:
            return '{0.specific}--{0.level}'.format(self)

    @property
    def posture_param_value_family(self):
        if self.family:
            return '-{0.family}-{0.level}'.format(self)

    @property
    def posture_param_value_complete(self):
        return '{0.specific}-{0.family}-{0.level}'.format(self)

    @property
    def posture_type_specific(self):
        return _get_posture_type_for_posture_name(self.specific) or None

    @property
    def posture_type_family(self):
        return _get_posture_type_for_posture_name(self.family) or None

    @property
    def posture_types(self):
        p0 = self.posture_type_specific
        p1 = self.posture_type_family
        if p0 is not None:
            if p1 is not None and p0 != p1:
                return (p0, p1)
            return (p0,)
        if p1 is not None:
            return (p1,)
        return ()

    @property
    def is_overlay(self):
        return self.level == UPPER_BODY

    @property
    def carry_target(self):
        if self.left not in _NOT_SPECIFIC_ACTOR:
            return self.left
        if self.right not in _NOT_SPECIFIC_ACTOR:
            return self.right

    @property
    def surface_target(self):
        if self.surface not in _NOT_SPECIFIC_ACTOR:
            return self.surface

    @property
    def allow_surface(self):
        if self.surface and self.surface != MATCH_NONE:
            return True
        return False

    @property
    def carry_hand(self) -> Hand:
        if self.left not in _NOT_SPECIFIC_ACTOR:
            return Hand.LEFT
        if self.right not in _NOT_SPECIFIC_ACTOR:
            return Hand.RIGHT

    @property
    def free_hands(self) -> Hand:
        if self.left in (MATCH_ANY, HOLSTER):
            if self.right in (MATCH_ANY, HOLSTER):
                return (Hand.LEFT, Hand.RIGHT)
            return (Hand.LEFT,)
        if self.right in (MATCH_ANY, HOLSTER):
            return (Hand.RIGHT,)
        return ()

    @property
    def carry_hand_and_target(self) -> tuple:
        if self.left not in _NOT_SPECIFIC_ACTOR:
            return (Hand.LEFT, self.left)
        if self.right not in _NOT_SPECIFIC_ACTOR:
            return (Hand.RIGHT, self.right)
        return (None, None)

    def references_object(self, obj):
        return obj in (self.actor, self.left, self.right, self.surface)

class SlotManifestBase:
    __qualname__ = 'SlotManifestBase'
    __slots__ = ()

    def __str__(self):
        items = ', '.join(str(i) for i in sorted(self))
        return '{' + items + '}'

    def __repr__(self):
        items = ', '.join(repr(i) for i in sorted(self))
        return standard_repr(self, items)

    def intersection(self, other):
        if self is other:
            return self
        results = SlotManifest()
        open_set = set(self | other)
        while open_set:
            entry0 = open_set.pop()
            to_remove = set()
            for entry1 in open_set:
                while entry0.actor == entry1.actor or entry0.target == entry1.target or entry0.slot == entry1.slot:
                    intersection = entry0.intersect(entry1)
                    if intersection is None:
                        return
                    entry0 = intersection
                    to_remove.add(entry1)
            open_set -= to_remove
            while entry0 is not None:
                results.add(entry0)
                continue
        return results

    def frozen_copy(self):
        return FrozenSlotManifest(entry for entry in self)

    def apply_actor_map(self, actor_map):
        return self.__class__(entry.apply_actor_map(actor_map) for entry in self)

class SlotManifest(SlotManifestBase, set):
    __qualname__ = 'SlotManifest'
    __slots__ = ()

    def intern(self):
        return FrozenSlotManifest(entry.intern() for entry in self).intern()

class FrozenSlotManifest(SlotManifestBase, frozenset, InternMixin):
    __qualname__ = 'FrozenSlotManifest'
    __slots__ = ()

    def frozen_copy(self):
        return self

class _SlotManifestEntrySingle(namedtuple('_SlotManifestEntrySingle', ('actor', 'target', 'slot'))):
    __qualname__ = '_SlotManifestEntrySingle'
    __slots__ = ()

    def __new__(cls, actor, target, slot):
        return super().__new__(cls, actor or MATCH_ANY, target or MATCH_NONE, slot or MATCH_NONE)

    def with_overrides(self, **overrides):
        init_kwargs = dict(zip(self._fields, self))
        init_kwargs.update(overrides)
        return self.__class__(**init_kwargs)

    def __str__(self):
        if self.slot is not None:
            return '{}@{}:{}'.format(self.actor, self.target, self.slot)
        bone_name_hash = self.bone_name_hash
        if bone_name_hash is not None:
            return '{}@{}:{:#010x}'.format(self.actor, self.target, bone_name_hash)
        return '{}@{}:None'.format(self.actor, self.target)

    @property
    def bone_name_hash(self):
        slot = self.slot
        if isinstance(slot, SlotType):
            return slot.bone_name_hash
        if isinstance(slot, int):
            return slot

    @property
    def runtime_slot(self):
        if isinstance(self.slot, RuntimeSlot):
            return self.slot

    @property
    def slot_types(self):
        slot = self.slot
        if isinstance(slot, (set, frozenset)):
            return self.slot
        if isinstance(slot, RuntimeSlot):
            return slot.slot_types
        if isinstance(slot, type) and issubclass(slot, SlotType):
            return {slot}
        if isinstance(slot, int):
            return {get_slot_type_for_bone_name_hash(slot)}

    def _sort_key(self):
        return (SORT_ORDER.get(self.actor, SORT_ORDER_DEFAULT), _lt_get_type_order(self.actor), SORT_ORDER.get(self.target, SORT_ORDER_DEFAULT), _lt_get_type_order(self.target), SORT_ORDER.get(self.slot, SORT_ORDER_DEFAULT), _lt_get_type_order(self.slot))

    def __lt__(self, other):
        return self._sort_key() < other._sort_key()

class SlotManifestEntry(tuple, InternMixin):
    __qualname__ = 'SlotManifestEntry'
    __slots__ = ()

    def __new__(cls, actor, target, slot, additional_entries=()):
        entries = ListSet((_SlotManifestEntrySingle(actor, target, slot),))
        entries.update(additional_entries)
        return super().__new__(cls, entries)

    def __reduce__(self):
        return (self.__class__, (self.actor, self.target, self.slot, self[1:]))

    def intern(self):
        return super().intern()

    @classmethod
    def from_entries(cls, entries):
        return cls(additional_entries=entries[1:], *entries[0])

    @property
    def actor(self):
        return self[0].actor

    @property
    def target(self):
        return self[0].target

    @property
    def slot(self):
        return self[0].slot

    @property
    def bone_name_hash(self):
        return self[0].bone_name_hash

    @property
    def slot_types(self):
        return self[0].slot_types

    @property
    def runtime_slot(self):
        return self[0].runtime_slot

    def with_overrides(self, **overrides):
        return self.from_entries([entry.with_overrides(**overrides) for entry in self])

    def get_runtime_slots_gen(self):
        if self.slot is None:
            return ()
        if isinstance(self.slot, RuntimeSlot):
            return (self.slot,)
        try:
            runtime_slots_gen = self.target.get_runtime_slots_gen
        except AttributeError:
            return ()
        return runtime_slots_gen(slot_types=self.slot_types)

    def apply_actor_map(self, actor_map):
        entries = [_SlotManifestEntrySingle(actor_map(entry.actor, entry.actor), actor_map(entry.target, entry.target), actor_map(entry.slot, entry.slot)) for entry in self]
        return self.from_entries(entries)

    def __repr__(self):
        return standard_repr(self, *self)

    def __str__(self):
        return str(tuple(self))

    def intersect(self, other):
        self_entries = list(self)
        other_entries = list(other)
        added_entries = []
        for other_entry in other_entries:
            needs_add = True
            for (i, self_entry) in enumerate(self_entries):
                if self_entry.target == other_entry.target:
                    target = self_entry.target
                elif self_entry.target == MATCH_ANY:
                    target = other_entry.target
                elif other_entry.target == MATCH_ANY:
                    target = self_entry.target
                else:
                    (early_out, target) = resolve_variables_and_objects(self_entry.target, other_entry.target)
                    if early_out is not None:
                        return
                if self_entry.actor == other_entry.actor:
                    if not self_entry.slot_types.intersection(other_entry.slot_types):
                        return
                    new_slot = self_entry.runtime_slot or (other_entry.runtime_slot or (self_entry.bone_name_hash or other_entry.bone_name_hash))
                    self_entries[i] = _SlotManifestEntrySingle(self_entry.actor, target, new_slot)
                    needs_add = False
                else:
                    while self_entry.slot_types.intersection(other_entry.slot_types):
                        return
            while needs_add:
                added_entries.append(other_entry)
        self_entries += added_entries
        return self.from_entries(self_entries)

    def references_object(self, obj):
        return obj in (self.actor, self.target)

