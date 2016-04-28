from contextlib import contextmanager
import collections
import functools
import itertools
import operator
import re
from objects.slots import RuntimeSlot
from sims4.callback_utils import consume_exceptions
from sims4.log import Logger
from sims4.repr_utils import standard_repr
from sims4.tuning.tunable import Tunable
from singletons import DEFAULT
import animation.posture_manifest
import assertions
import enum
import event_testing
import objects.components.types
import routing
import services
import sims
import sims4.callback_utils
import sims4.reload
logger = Logger('PostureGraph')
BODY_INDEX = 0
CARRY_INDEX = 1
SURFACE_INDEX = 2
BODY_POSTURE_TYPE_INDEX = 0
BODY_TARGET_INDEX = 1
CARRY_POSTURE_TYPE_INDEX = 0
CARRY_TARGET_INDEX = 1
CARRY_HAND_INDEX = 2
SURFACE_TARGET_INDEX = 0
SURFACE_SLOT_TYPE_INDEX = 1
SURFACE_SLOT_TARGET_INDEX = 2
with sims4.reload.protected(globals()):
    _enable_cache_count = 0
    _cached_object_manager = None
    _cached_valid_objects = None
    _cached_runtime_slots = None

class PostureSpecVariable(enum.Int):
    __qualname__ = 'PostureSpecVariable'
    ANYTHING = 200
    INTERACTION_TARGET = 201
    CARRY_TARGET = 302
    SURFACE_TARGET = 203
    CONTAINER_TARGET = 204
    HAND = 205
    POSTURE_TYPE_CARRY_NOTHING = 206
    POSTURE_TYPE_CARRY_OBJECT = 207
    SLOT = 208
    SLOT_TEST_DEFINITION = 209
    DESTINATION_FILTER = 211

    def __repr__(self):
        return self.name

@contextmanager
def _cache_thread_specific_info():
    global _cached_runtime_slots, _enable_cache_count, _cached_object_manager, _cached_valid_objects
    _cached_runtime_slots = {}
    _enable_cache_count += 1
    try:
        if _enable_cache_count == 1:
            with sims4.callback_utils.invoke_enter_exit_callbacks(sims4.callback_utils.CallbackEvent.POSTURE_GRAPH_BUILD_ENTER, sims4.callback_utils.CallbackEvent.POSTURE_GRAPH_BUILD_EXIT), consume_exceptions():
                yield None
        else:
            yield None
    finally:
        _enable_cache_count -= 1
        if not _enable_cache_count:
            _cached_object_manager = None
            _cached_valid_objects = None
            _cached_runtime_slots = None

def with_caches(func):

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _cache_thread_specific_info():
            return func(*args, **kwargs)

    return wrapper

def object_manager():
    global _cached_object_manager
    if _enable_cache_count:
        if _cached_object_manager is None:
            _cached_object_manager = services.object_manager()
        return _cached_object_manager
    return services.object_manager()

def valid_objects():
    global _cached_valid_objects
    if _enable_cache_count:
        if _cached_valid_objects is None:
            _cached_valid_objects = _valid_objects_helper()
        return _cached_valid_objects
    return _valid_objects_helper()

def _valid_objects_helper():
    result = set()
    for obj in object_manager().valid_objects():
        while obj.is_valid_posture_graph_object:
            if obj.parts:
                result.update(obj.parts)
            else:
                result.add(obj)
    return frozenset(result)

def _simple_id_str(obj):
    return str(obj)

def _str_for_variable(value):
    result = 'None'
    if value is not None:
        result = str(value).split('.')[-1]
    return result

def _str_for_type(value):
    if value is None:
        return 'None'
    if isinstance(value, PostureSpecVariable):
        return _str_for_variable(value)
    return value.__name__

def _str_for_object(value):
    if value is None:
        return 'None'
    if isinstance(value, PostureSpecVariable):
        return _str_for_variable(value)
    return _simple_id_str(value)

def _str_for_slot_type(value):
    if value is None:
        return 'None'
    if isinstance(value, PostureSpecVariable):
        return _str_for_variable(value)
    return value.__name__.split('_')[-1]

def variables_match(a, b, var_map=None, allow_owner_to_match_parts=True):
    if a == b:
        return True
    if PostureSpecVariable.ANYTHING in (a, b):
        return True
    if None in (a, b):
        return False
    if var_map:
        a = var_map.get(a, a)
        b = var_map.get(b, b)
        return variables_match(a, b, None, allow_owner_to_match_parts)
    if isinstance(a, PostureSpecVariable) or isinstance(b, PostureSpecVariable):
        return True
    if a.id != b.id:
        return False
    if a.is_part and b.is_part:
        return False
    return allow_owner_to_match_parts

def _get_origin_spec(default_body_posture, origin_carry):
    origin_body = PostureAspectBody((default_body_posture, None))
    origin_surface = PostureAspectSurface((None, None, None))
    origin_node = PostureSpec((origin_body, origin_carry, origin_surface))
    return origin_node

def get_origin_carry():
    return PostureAspectCarry((PostureSpecVariable.POSTURE_TYPE_CARRY_NOTHING, None, PostureSpecVariable.HAND))

def get_origin_spec(default_body_posture):
    origin_carry = get_origin_carry()
    return _get_origin_spec(default_body_posture, origin_carry)

def get_origin_spec_carry(default_body_posture):
    origin_carry = PostureAspectCarry((PostureSpecVariable.POSTURE_TYPE_CARRY_OBJECT, PostureSpecVariable.CARRY_TARGET, PostureSpecVariable.HAND))
    return _get_origin_spec(default_body_posture, origin_carry)

def get_pick_up_spec_sequence(node_origin, surface_target, body_target=None):
    default_body_posture = node_origin[BODY_INDEX][BODY_POSTURE_TYPE_INDEX]
    default_surface_target = node_origin[SURFACE_INDEX][SURFACE_TARGET_INDEX]
    origin = get_origin_spec(default_body_posture)
    origin_carry = get_origin_spec_carry(default_body_posture)
    if body_target is None:
        slot_type = None
        target_var = None
        target = surface_target
    else:
        slot_type = PostureSpecVariable.SLOT
        target_var = PostureSpecVariable.CARRY_TARGET
        target = body_target
    move_to_surface = PostureSpec((PostureAspectBody((default_body_posture, target)), origin[CARRY_INDEX], PostureAspectSurface((None, None, None))))
    address_surface = PostureSpec((PostureAspectBody((default_body_posture, target)), origin[CARRY_INDEX], PostureAspectSurface((surface_target, slot_type, target_var))))
    address_surface_carry = PostureSpec((address_surface[BODY_INDEX], origin_carry[CARRY_INDEX], PostureAspectSurface((surface_target, None, None))))
    address_surface_target = address_surface[SURFACE_INDEX][SURFACE_TARGET_INDEX]
    if default_surface_target is address_surface_target:
        return (address_surface, address_surface_carry)
    return (move_to_surface, address_surface, address_surface_carry)

def get_put_down_spec_sequence(default_body_posture, surface_target, body_target=None):
    body_target = body_target or surface_target
    origin = get_origin_spec(default_body_posture)
    origin_carry = get_origin_spec_carry(default_body_posture)
    slot_type = PostureSpecVariable.SLOT
    target_var = PostureSpecVariable.CARRY_TARGET
    address_surface = PostureSpec((PostureAspectBody((default_body_posture, body_target)), origin[CARRY_INDEX], PostureAspectSurface((surface_target, slot_type, target_var))))
    address_surface_carry = PostureSpec((address_surface[BODY_INDEX], origin_carry[CARRY_INDEX], PostureAspectSurface((surface_target, None, None))))
    return (address_surface_carry, address_surface)

@assertions.hot_path
def node_matches_spec(node, spec, var_map, allow_owner_to_match_parts):
    node_body = node[BODY_INDEX]
    node_body_target = node_body[BODY_TARGET_INDEX]
    node_body_posture_type = node_body[BODY_POSTURE_TYPE_INDEX]
    spec_surface = spec[SURFACE_INDEX]
    node_surface = node[SURFACE_INDEX]
    spec_body = spec[BODY_INDEX]
    if spec_body is not None:
        spec_body_target = spec_body[BODY_TARGET_INDEX]
        spec_body_posture_type = spec_body[BODY_POSTURE_TYPE_INDEX]
    else:
        spec_body_target = PostureSpecVariable.ANYTHING
        spec_body_posture_type = node_body_posture_type
    if spec_body_posture_type != node_body_posture_type:
        return False
    if not variables_match(node_body_target, spec_body_target, var_map, allow_owner_to_match_parts):
        return False
    if node_body_posture_type.mobile and (node_body_target is not None and (spec_surface is None or spec_surface[SURFACE_TARGET_INDEX] is None)) and spec_body_target == PostureSpecVariable.ANYTHING:
        return False
    carry_index = CARRY_INDEX
    spec_carry = spec[carry_index]
    if spec_carry is not None:
        node_carry = node[carry_index]
        carry_posture_type_index = CARRY_POSTURE_TYPE_INDEX
        if node_carry[carry_posture_type_index] != spec_carry[carry_posture_type_index]:
            return False
        carry_target_index = CARRY_TARGET_INDEX
        if not variables_match(node_carry[carry_target_index], spec_carry[carry_target_index], var_map, allow_owner_to_match_parts):
            return False
    if (spec_surface is None or spec_surface[SURFACE_TARGET_INDEX] is None) and node_surface is not None and node_body_posture_type.mobile:
        node_surface_target = node_surface[SURFACE_TARGET_INDEX]
        if node_surface_target is not None:
            return False
    if not variables_match(node_surface[SURFACE_TARGET_INDEX], spec_surface[SURFACE_TARGET_INDEX], var_map, allow_owner_to_match_parts):
        return False
    if node_surface[SURFACE_SLOT_TYPE_INDEX] != spec_surface[SURFACE_SLOT_TYPE_INDEX]:
        return False
    if not (spec_surface is not None and variables_match(node_surface[SURFACE_SLOT_TARGET_INDEX], spec_surface[SURFACE_SLOT_TARGET_INDEX], var_map, allow_owner_to_match_parts)):
        return False
    return True

def _spec_matches_request(sim, spec, var_map):
    if spec[SURFACE_INDEX][SURFACE_SLOT_TYPE_INDEX] is not None:
        slot_manifest = var_map.get(PostureSpecVariable.SLOT)
        if slot_manifest is not None:
            surface = spec[SURFACE_INDEX][SURFACE_TARGET_INDEX]
            if not slot_manifest.slot_types.intersection(surface.get_provided_slot_types()):
                return False
            carry_target = slot_manifest.actor
            if hasattr(carry_target, 'manager') and not carry_target.has_component(objects.components.types.CARRYABLE_COMPONENT):
                current_parent_slot = carry_target.parent_slot
                if current_parent_slot is None:
                    return False
                if current_parent_slot.owner != surface:
                    return False
                if not slot_manifest.slot_types.intersection(current_parent_slot.slot_types):
                    return False
        destination_filter = var_map.get(PostureSpecVariable.DESTINATION_FILTER)
        if destination_filter is not None:
            if not destination_filter(spec, var_map):
                return False
    return True

def _in_var_map(obj, var_map):
    for target in var_map.values():
        while isinstance(target, objects.game_object.GameObject) and target.is_same_object_or_part(obj):
            return True
    return False

def destination_test(sim, node, destination_specs, var_map, additional_test_fn, affordance):
    sims4.sim_irq_service.yield_to_irq()
    body_target = node[BODY_INDEX][BODY_TARGET_INDEX]
    if body_target is not None and not any(_in_var_map(child, var_map) for child in body_target.parenting_hierarchy_gen()) and not sim.autonomy_component.is_object_autonomously_available(body_target):
        return False
    surface_target = node[SURFACE_INDEX][SURFACE_TARGET_INDEX]
    if body_target is None and (surface_target is not None and not any(_in_var_map(child, var_map) for child in surface_target.parenting_hierarchy_gen())) and not sim.autonomy_component.is_object_autonomously_available(surface_target):
        return False
    if not any(node_matches_spec(node, destination_spec, var_map, True) for destination_spec in destination_specs):
        return False
    if not node.validate_destination(destination_specs, var_map, affordance):
        return False
    if not (additional_test_fn is not None and additional_test_fn(node, var_map)):
        return False
    if not _spec_matches_request(sim, node, var_map):
        return False
    return True

class PostureAspectBody(tuple):
    __qualname__ = 'PostureAspectBody'
    __slots__ = ()
    posture_type = property(operator.itemgetter(BODY_POSTURE_TYPE_INDEX))
    target = property(operator.itemgetter(BODY_TARGET_INDEX))

    def __str__(self):
        return '{}@{}'.format(self[BODY_POSTURE_TYPE_INDEX].name, self[BODY_TARGET_INDEX])

    def __repr__(self):
        return standard_repr(self, tuple(self))

class PostureAspectCarry(tuple):
    __qualname__ = 'PostureAspectCarry'
    __slots__ = ()
    posture_type = property(operator.itemgetter(CARRY_POSTURE_TYPE_INDEX))
    target = property(operator.itemgetter(CARRY_TARGET_INDEX))

    def __str__(self):
        if self[CARRY_TARGET_INDEX] is None:
            return self[CARRY_POSTURE_TYPE_INDEX].name
        return '<{} {}>'.format(self[CARRY_POSTURE_TYPE_INDEX].name, self[CARRY_TARGET_INDEX])

    def __repr__(self):
        return standard_repr(self, tuple(self))

class PostureAspectSurface(tuple):
    __qualname__ = 'PostureAspectSurface'
    __slots__ = ()
    target = property(operator.itemgetter(SURFACE_TARGET_INDEX))
    slot_type = property(operator.itemgetter(SURFACE_SLOT_TYPE_INDEX))
    slot_target = property(operator.itemgetter(SURFACE_SLOT_TARGET_INDEX))

    def __str__(self):
        if self[SURFACE_SLOT_TYPE_INDEX] is None:
            if self[SURFACE_TARGET_INDEX] is None:
                return 'No Surface'
            return '@Surface: ' + str(self[SURFACE_TARGET_INDEX])
        if self[SURFACE_SLOT_TARGET_INDEX] is None:
            slot_str = '(EmptySlot)'
        else:
            slot_str = '(TargetInSlot)'
        return 'Surface: ' + str(self[SURFACE_TARGET_INDEX]) + slot_str

    def __repr__(self):
        return standard_repr(self, tuple(self))

class PostureSpec(tuple):
    __qualname__ = 'PostureSpec'
    __slots__ = ()
    body = property(operator.itemgetter(BODY_INDEX))
    body_target = property(lambda self: self[BODY_INDEX] and self[BODY_INDEX][BODY_TARGET_INDEX])
    body_posture = property(lambda self: self[BODY_INDEX] and self[BODY_INDEX][BODY_POSTURE_TYPE_INDEX])
    carry = property(operator.itemgetter(CARRY_INDEX))
    carry_target = property(lambda self: self[CARRY_INDEX] and self[CARRY_INDEX][CARRY_TARGET_INDEX])
    carry_posture = property(lambda self: self[CARRY_INDEX] and self[CARRY_INDEX][CARRY_POSTURE_TYPE_INDEX])
    surface = property(operator.itemgetter(SURFACE_INDEX))
    surface_target = property(lambda self: self[SURFACE_INDEX] and self[SURFACE_INDEX][SURFACE_TARGET_INDEX])
    slot_type = property(lambda self: self[SURFACE_INDEX] and self[SURFACE_INDEX][SURFACE_SLOT_TYPE_INDEX])
    slot_target = property(lambda self: self[SURFACE_INDEX] and self[SURFACE_INDEX][SURFACE_SLOT_TARGET_INDEX])

    def clone(self, body=DEFAULT, carry=DEFAULT, surface=DEFAULT):
        if body is DEFAULT:
            body = self[BODY_INDEX]
        if carry is DEFAULT:
            carry = self[CARRY_INDEX]
        if surface is DEFAULT:
            surface = self[SURFACE_INDEX]
        return self.__class__((body, carry, surface))

    _attribute_definitions = (('_body_posture_name', str), ('_body_target_type', str), ('_body_target', str), ('_body_part', str), ('_is_carrying', str), ('_at_surface', str), ('_surface_target_type', str), ('_surface_target', str), ('_surface_part', str), ('_is_surface_full', str))

    @property
    def _body_posture_name(self):
        body = self[BODY_INDEX]
        if body is None:
            return
        body_posture_type = body[BODY_POSTURE_TYPE_INDEX]
        if body_posture_type is None:
            return
        return body_posture_type._posture_name

    @property
    def _body_target_type(self):
        body = self[BODY_INDEX]
        if body is None:
            return
        target = body[BODY_TARGET_INDEX]
        if target is None:
            return
        if target.is_part:
            target = target.part_owner
        return type(target).__name__

    @property
    def _body_target(self):
        body = self[BODY_INDEX]
        if body is None:
            return
        target = body[BODY_TARGET_INDEX]
        if target is None:
            return
        if isinstance(target, PostureSpecVariable):
            return target.name
        if target.is_part:
            return target.part_owner
        return target

    @property
    def _body_target_with_part(self):
        body = self[BODY_INDEX]
        if body is None:
            return
        target = body[BODY_TARGET_INDEX]
        if target is None:
            return
        if isinstance(target, PostureSpecVariable):
            return target.name
        return target

    @property
    def _body_part(self):
        body = self[BODY_INDEX]
        if body is None:
            return
        target = body[BODY_TARGET_INDEX]
        if target is None or isinstance(target, PostureSpecVariable):
            return
        if target.is_part:
            return target.part_group_index

    @property
    def _is_carrying(self):
        carry = self[CARRY_INDEX]
        if carry is not None and carry[CARRY_TARGET_INDEX] is not None:
            return True
        return False

    @property
    def _at_surface(self):
        surface = self[SURFACE_INDEX]
        if surface is not None and surface[SURFACE_SLOT_TYPE_INDEX] is not None:
            return True
        return False

    @property
    def _surface_target_type(self):
        surface = self[SURFACE_INDEX]
        if surface is None:
            return
        target = surface[SURFACE_TARGET_INDEX]
        if target is None:
            return
        if isinstance(target, PostureSpecVariable):
            return target.name
        if target.is_part:
            target = target.part_owner
        return type(target).__name__

    @property
    def _surface_target(self):
        surface = self[SURFACE_INDEX]
        if surface is None:
            return
        target = surface[SURFACE_TARGET_INDEX]
        if target is None:
            return
        if isinstance(target, PostureSpecVariable):
            return target.name
        if target.is_part:
            return target.part_owner
        return target

    @property
    def _surface_target_with_part(self):
        surface = self[SURFACE_INDEX]
        if surface is None:
            return
        target = surface[SURFACE_TARGET_INDEX]
        if target is None:
            return
        if isinstance(target, PostureSpecVariable):
            return target.name
        return target

    @property
    def _surface_part(self):
        surface = self[SURFACE_INDEX]
        if surface is None:
            return
        target = surface[SURFACE_TARGET_INDEX]
        if target is None or isinstance(target, PostureSpecVariable):
            return
        if target.is_part:
            return target.part_group_index

    @property
    def _is_surface_full(self):
        surface = self[SURFACE_INDEX]
        if surface[SURFACE_TARGET_INDEX] is not None:
            if surface[SURFACE_SLOT_TYPE_INDEX] is not None:
                if surface[SURFACE_SLOT_TARGET_INDEX] is not None:
                    return 'TargetInSlot'
                return 'EmptySlot'
            return 'AtSurface'

    def __repr__(self):
        result = '{}@{}'.format(self._body_posture_name, _simple_id_str(self._body_target_with_part))
        carry = self[CARRY_INDEX]
        if carry is None:
            result += ', carry:any'
        elif self[CARRY_INDEX][CARRY_TARGET_INDEX] is not None:
            result += ', carry'
        surface = self[SURFACE_INDEX]
        if surface is None:
            result += ', surface:any'
        elif surface[SURFACE_SLOT_TYPE_INDEX] is not None:
            if surface[SURFACE_SLOT_TARGET_INDEX] is not None:
                result += ', surface:target@{}'.format(_simple_id_str(self._surface_target_with_part))
            else:
                result += ', surface:empty_slot@{}'.format(_simple_id_str(self._surface_target_with_part))
        elif surface[SURFACE_TARGET_INDEX] is not None:
            result += ', surface:{}'.format(_simple_id_str(self._surface_target_with_part))
        return result

    def get_core_objects(self):
        body_target = self[BODY_INDEX][BODY_TARGET_INDEX]
        surface_target = self[SURFACE_INDEX][SURFACE_TARGET_INDEX]
        core_objects = set()
        if body_target is not None:
            core_objects.add(body_target)
            if body_target.parent is not None:
                core_objects.add(body_target.parent)
        if surface_target is not None:
            core_objects.add(surface_target)
        return core_objects

    def get_relevant_objects(self):
        body_posture = self[BODY_INDEX][BODY_POSTURE_TYPE_INDEX]
        body_target = self[BODY_INDEX][BODY_TARGET_INDEX]
        surface_target = self[SURFACE_INDEX][SURFACE_TARGET_INDEX]
        if body_posture.mobile and body_target is None and surface_target is None:
            return valid_objects()
        relevant_objects = self.get_core_objects()
        if body_target is not None:
            if body_target.is_part:
                relevant_objects.update(body_target.adjacent_parts_gen())
            relevant_objects.update(body_target.children)
        return relevant_objects

    def is_same_route_location(self, target):
        if self[BODY_INDEX][BODY_TARGET_INDEX] == target[BODY_INDEX][BODY_TARGET_INDEX] and self[SURFACE_INDEX][SURFACE_TARGET_INDEX] == target[SURFACE_INDEX][SURFACE_TARGET_INDEX] and self[SURFACE_INDEX][SURFACE_SLOT_TARGET_INDEX] == target[SURFACE_INDEX][SURFACE_SLOT_TARGET_INDEX]:
            return True
        return False

    def same_spec_except_slot(self, target):
        if self.body == target.body and self.carry == target.carry and self[SURFACE_INDEX][SURFACE_TARGET_INDEX] == target[SURFACE_INDEX][SURFACE_TARGET_INDEX]:
            return True
        return False

    def same_spec_ignoring_surface_if_mobile(self, target):
        if self.body_posture.mobile and self.body_posture == target.body_posture and self.carry == target.carry:
            return True
        return False

    def validate_destination(self, destination_specs, var_map, affordance):
        if not any(self._validate_carry(destination_spec) for destination_spec in destination_specs):
            return False
        if not self._validate_surface(var_map):
            return False
        if not self._validate_body(affordance):
            return False
        return True

    def _validate_body(self, affordance):
        body = self[BODY_INDEX]
        if body is None:
            return True
        target = body[BODY_TARGET_INDEX]
        if target is None:
            return True
        if not target.supports_affordance(affordance):
            return False
        return True

    def _validate_carry(self, destination_spec):
        dest_carry = destination_spec[CARRY_INDEX]
        if dest_carry is None or dest_carry[CARRY_TARGET_INDEX] is None:
            if self[CARRY_INDEX][CARRY_TARGET_INDEX] is None:
                return True
            return False
        if dest_carry == self[CARRY_INDEX]:
            return True
        return False

    def _validate_surface(self, var_map):
        surface_spec = self[SURFACE_INDEX]
        if surface_spec is None:
            return True
        surface = surface_spec[SURFACE_TARGET_INDEX]
        if surface is None:
            return True
        slot_type = surface_spec[SURFACE_SLOT_TYPE_INDEX]
        if slot_type is None:
            return True
        slot_manifest_entry = var_map.get(slot_type)
        if slot_manifest_entry is None:
            return False
        runtime_slots = set(surface.get_runtime_slots_gen(slot_types=slot_manifest_entry.slot_types))
        slot_target = surface_spec[SURFACE_SLOT_TARGET_INDEX]
        child = var_map.get(slot_target)
        if child is None and PostureSpecVariable.SLOT_TEST_DEFINITION not in var_map:
            for runtime_slot in runtime_slots:
                while runtime_slot.empty:
                    return True
            return False
        if child is not None:
            current_slot = child.parent_slot
            if current_slot is not None:
                if slot_manifest_entry.actor is child:
                    if current_slot in runtime_slots:
                        return True
        if PostureSpecVariable.SLOT_TEST_DEFINITION in var_map:
            slot_test_object = DEFAULT
            slot_test_definition = var_map[PostureSpecVariable.SLOT_TEST_DEFINITION]
        else:
            slot_test_object = child
            slot_test_definition = DEFAULT
        carry_target = self[CARRY_INDEX][CARRY_TARGET_INDEX]
        carry_target = var_map.get(carry_target)
        for runtime_slot in runtime_slots:
            if carry_target is not None:
                objects_to_ignore = [carry_target]
            else:
                objects_to_ignore = DEFAULT
            while runtime_slot.is_valid_for_placement(obj=slot_test_object, definition=slot_test_definition, objects_to_ignore=objects_to_ignore):
                return True
        return False

    @property
    def requires_carry_target_in_hand(self):
        return self[CARRY_INDEX][CARRY_TARGET_INDEX] is not None

    @property
    def requires_carry_target_in_slot(self):
        return self[SURFACE_INDEX][SURFACE_SLOT_TARGET_INDEX] is not None

def get_carry_posture_aop(sim, carry_target):
    context = sim.create_posture_interaction_context()
    for aop in carry_target.potential_interactions(context):
        from postures.posture_interactions import HoldObject
        while issubclass(aop.affordance, HoldObject):
            return aop
    logger.error('The carry_target: ({}) has no SIs of type HoldObject. Check that your object has a Carryable Component.', carry_target, owner='mduke')

class PostureOperation:
    __qualname__ = 'PostureOperation'
    COST_NOMINAL = Tunable(description='\n        A nominal cost to simple operations just to prevent them from being\n        free.\n        ', tunable_type=float, default=0.1)
    COST_STANDARD = Tunable(description='\n        A cost for standard posture operations (such as changing postures or\n        targets).\n        ', tunable_type=float, default=1.0)

    class OperationBase:
        __qualname__ = 'PostureOperation.OperationBase'
        __slots__ = ()

        def apply(self, node):
            raise NotImplementedError()

        def validate(self, node, sim, var_map):
            return True

        def cost(self, node):
            return PostureOperation.COST_NOMINAL

        @property
        def debug_cost_str_list(self):
            pass

        def associated_aop(self, sim, var_map):
            pass

        def is_equivalent_to(self, other):
            raise NotImplementedError

        def get_constraint(self, sim, node, var_map):
            pass

    class BodyTransition(OperationBase):
        __qualname__ = 'PostureOperation.BodyTransition'
        __slots__ = ('_posture_type', '_aop', '_disallowed_ages')

        def __init__(self, posture_type, aop):
            self._posture_type = posture_type
            self._aop = aop
            self._disallowed_ages = set()
            for test in aop.affordance.test_globals:
                while isinstance(test, event_testing.test_variants.SimInfoTest):
                    if test.ages is None:
                        pass
                    while True:
                        for age in sims.sim_info_types.Age:
                            while age not in test.ages:
                                self._disallowed_ages.add(age)
            self._disallowed_ages = frozenset(self._disallowed_ages)

        def is_equivalent_to(self, other):
            return type(self) == type(other) and (self._aop.is_equivalent_to(other._aop) and self._posture_type == other._posture_type)

        def __repr__(self):
            return '{}({})'.format(type(self).__name__, _str_for_type(self._posture_type))

        @property
        def posture_type(self):
            return self._posture_type

        def associated_aop(self, sim, var_map):
            return self._aop

        @property
        def target(self):
            return self._aop.target

        def cost(self, node):
            cost = 0
            cost_str_list = []
            body_index = BODY_INDEX
            body_posture_type_index = BODY_POSTURE_TYPE_INDEX
            body_target_index = BODY_TARGET_INDEX
            curr_body = node[body_index]
            curr_body_target = curr_body[body_target_index]
            curr_posture_type = curr_body[body_posture_type_index]
            next_posture_type = self._posture_type
            current_mobile = curr_posture_type.mobile
            next_mobile = next_posture_type.mobile
            next_body_target = self.target
            from postures.posture_scoring import PostureScoring
            my_cost = curr_posture_type.get_transition_cost(next_posture_type)
            if my_cost is None and curr_posture_type != next_posture_type:
                my_cost = PostureOperation.COST_STANDARD
            if my_cost is not None:
                cost += my_cost
            if current_mobile != next_mobile:
                my_cost = PostureScoring.ENTER_EXIT_OBJECT_COST
                cost += my_cost
            if curr_body_target != next_body_target and not current_mobile and not next_mobile:
                my_cost = PostureScoring.INNER_NON_MOBILE_TO_NON_MOBILE_COST
                cost += my_cost
            if curr_posture_type.multi_sim:
                my_cost = PostureOperation.COST_STANDARD
                cost += my_cost
            return cost

        @property
        def debug_cost_str_list(self):
            return []

        def apply(self, spec):
            body = spec[BODY_INDEX]
            source_target = body[BODY_TARGET_INDEX]
            surface_target = spec[SURFACE_INDEX][SURFACE_TARGET_INDEX]
            destination_target = self.target
            if spec[CARRY_INDEX][CARRY_TARGET_INDEX] is not None and not self.posture_type._supports_carry:
                return
            if surface_target is not None and destination_target is None:
                return
            if not spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].unconstrained and surface_target is not None and spec[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].unconstrained != self.posture_type.unconstrained:
                return
            dest_target_is_not_none = destination_target is not None
            if dest_target_is_not_none and (surface_target is not None and destination_target != surface_target) and destination_target.parent != surface_target:
                return
            source_posture_type = body[BODY_POSTURE_TYPE_INDEX]
            if source_posture_type == self._posture_type:
                if source_target == destination_target:
                    return
                if source_posture_type.mobile:
                    if dest_target_is_not_none and source_target is not None:
                        return
            elif source_posture_type.mobile and surface_target is None:
                if not self._posture_type.mobile:
                    if dest_target_is_not_none and source_target is not None:
                        if source_target != destination_target:
                            return
            elif not source_posture_type.mobile and self._posture_type.mobile and destination_target is not None:
                return
            if dest_target_is_not_none and destination_target.is_part and not destination_target.supports_posture_type(self._posture_type):
                return
            targets_match = source_target is destination_target or (destination_target is None or source_target is None)
            if not source_posture_type.is_valid_transition(source_posture_type, self._posture_type, targets_match):
                return
            if self._posture_type.unconstrained or destination_target is not None and surface_target is None and spec[CARRY_INDEX][CARRY_TARGET_INDEX] is not None:
                if destination_target.is_surface():
                    return
                if destination_target.parent is not None and destination_target.parent.is_surface():
                    return
            return spec.clone(body=PostureAspectBody((self._posture_type, destination_target)))

        def validate(self, node, sim, var_map):
            if sim.sim_info.age in self._disallowed_ages:
                return False
            body_target = self.target
            if body_target is None:
                return True
            for supported_posture_info in body_target.supported_posture_types:
                if supported_posture_info.posture_type is not self.posture_type:
                    pass
                required_clearance = supported_posture_info.required_clearance
                if required_clearance is None:
                    pass
                transform_vector = body_target.transform.transform_vector(sims4.math.Vector3(0, 0, required_clearance))
                new_transform = sims4.math.Transform(body_target.transform.translation + transform_vector, body_target.transform.orientation)
                (result, _) = body_target.check_line_of_sight(new_transform, verbose=True)
                while result == routing.RAYCAST_HIT_TYPE_IMPASSABLE or result == routing.RAYCAST_HIT_TYPE_LOS_IMPASSABLE:
                    return False
            return True

    class PickUpObject(OperationBase):
        __qualname__ = 'PostureOperation.PickUpObject'
        __slots__ = ('_posture_type', '_target')

        def __init__(self, posture_type, target):
            self._posture_type = posture_type
            self._target = target

        def __repr__(self):
            return '{}({}, {})'.format(type(self).__name__, _str_for_type(self._posture_type), _str_for_object(self._target))

        @classmethod
        def get_pickup_cost(self, node):
            cost = PostureOperation.COST_STANDARD
            if not node[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile:
                cost += PostureOperation.COST_NOMINAL
            return cost

        def cost(self, node):
            return self.get_pickup_cost(node)

        def is_equivalent_to(self, other):
            return type(self) == type(other) and (self._posture_type == other._posture_type and self._target == other._target)

        def associated_aop(self, sim, var_map):
            return get_carry_posture_aop(sim, var_map[self._target])

        def apply(self, node, enter_carry_while_holding=False):
            if self._target is None:
                return
            carry = node[CARRY_INDEX]
            if carry is not None and carry[CARRY_TARGET_INDEX] is not None:
                return
            if not node[BODY_INDEX][BODY_POSTURE_TYPE_INDEX]._supports_carry:
                return
            surface = node[SURFACE_INDEX]
            surface_target = surface[SURFACE_TARGET_INDEX]
            carry_aspect = PostureAspectCarry((self._posture_type, self._target, PostureSpecVariable.HAND))
            surface_aspect = PostureAspectSurface((surface_target, None, None))
            return node.clone(carry=carry_aspect, surface=surface_aspect)

        def validate(self, node, sim, var_map):
            real_target = var_map[self._target]
            if real_target is None or not real_target.has_component(objects.components.types.CARRYABLE_COMPONENT):
                return False
            body = node[BODY_INDEX]
            if body[BODY_POSTURE_TYPE_INDEX].mobile:
                surface_target = node[SURFACE_INDEX][SURFACE_TARGET_INDEX]
                if surface_target is not None:
                    if real_target.parent is None or not real_target.parent.is_same_object_or_part(surface_target):
                        return False
                        if real_target.parent is not None:
                            return False
                elif real_target.parent is not None:
                    return False
            else:
                if real_target.parent is None and real_target.is_in_sim_inventory():
                    return True
                if body[BODY_POSTURE_TYPE_INDEX].unconstrained:
                    if real_target.parent is None:
                        return False
                    if body[BODY_TARGET_INDEX] is None:
                        return False
                    parent = body[BODY_TARGET_INDEX].parent
                    if parent is None:
                        return False
                    if real_target.parent is not parent:
                        return False
                else:
                    constraint = self.get_constraint(sim, node, var_map)
                    for sub_constraint in constraint:
                        if sub_constraint.routing_surface is not None and sub_constraint.routing_surface != body[BODY_TARGET_INDEX].routing_surface:
                            pass
                        while sub_constraint.geometry is not None and sub_constraint.geometry.contains_point(body[BODY_TARGET_INDEX].position):
                            break
                    return False
            return True

        def get_constraint(self, sim, node, var_map, **kwargs):
            carry_target = var_map[PostureSpecVariable.CARRY_TARGET]
            from carry.carry_postures import CarrySystemInventoryTarget, CarrySystemRuntimeSlotTarget, CarrySystemTerrainTarget
            if carry_target.is_in_inventory():
                surface = node[SURFACE_INDEX]
                surface_target = surface[SURFACE_TARGET_INDEX]
                if surface_target is not None and surface_target.inventory_component is not None:
                    carry_system_target = CarrySystemInventoryTarget(sim, carry_target, False, surface_target)
                else:
                    carry_system_target = CarrySystemInventoryTarget(sim, carry_target, False, carry_target.get_inventory().owner)
            elif carry_target.parent_slot is not None:
                carry_system_target = CarrySystemRuntimeSlotTarget(sim, carry_target, False, carry_target.parent_slot)
            else:
                carry_system_target = CarrySystemTerrainTarget(sim, carry_target, False, carry_target.transform)
            return carry_system_target.get_constraint(sim, **kwargs)

    STANDARD_PICK_UP_OP = PickUpObject(PostureSpecVariable.POSTURE_TYPE_CARRY_OBJECT, PostureSpecVariable.CARRY_TARGET)

    class PutDownObject(OperationBase):
        __qualname__ = 'PostureOperation.PutDownObject'
        __slots__ = ('_posture_type', '_target')

        def __init__(self, posture_type, target):
            self._posture_type = posture_type
            self._target = target

        def is_equivalent_to(self, other):
            return type(self) == type(other) and (self._posture_type == other._posture_type and self._target == other._target)

        def cost(self, node):
            cost = PostureOperation.COST_STANDARD
            if not node[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile:
                cost += PostureOperation.COST_NOMINAL
            return cost

        def __repr__(self):
            return '{}({}, {})'.format(type(self).__name__, _str_for_type(self._posture_type), _str_for_object(self._target))

        def apply(self, node):
            carry_aspect = PostureAspectCarry((self._posture_type, None, PostureSpecVariable.HAND))
            return node.clone(carry=carry_aspect)

    class PutDownObjectOnSurface(OperationBase):
        __qualname__ = 'PostureOperation.PutDownObjectOnSurface'
        __slots__ = ('_posture_type', '_surface_target', '_slot_type', '_slot_target')

        def __init__(self, posture_type, surface, slot_type, target):
            self._posture_type = posture_type
            self._surface_target = surface
            self._slot_type = slot_type
            self._slot_target = target

        def is_equivalent_to(self, other):
            return type(self) == type(other) and (self._surface_target == other._surface_target and (self._slot_type == other._slot_type and (self._posture_type == other._posture_type and self._slot_target == other._slot_target)))

        def cost(self, node):
            cost = PostureOperation.COST_STANDARD
            if not node[BODY_INDEX][BODY_POSTURE_TYPE_INDEX].mobile:
                cost += PostureOperation.COST_NOMINAL
            return cost

        def __repr__(self):
            return '{}({}, {}, {}, {})'.format(type(self).__name__, _str_for_type(self._posture_type), _str_for_object(self._surface_target), _str_for_slot_type(self._slot_type), _str_for_object(self._slot_target))

        def apply(self, node):
            surface = node[SURFACE_INDEX]
            if surface[SURFACE_TARGET_INDEX] != self._surface_target:
                return
            spec_slot_type = surface[SURFACE_SLOT_TYPE_INDEX]
            if spec_slot_type is not None and spec_slot_type != self._slot_type:
                return
            if surface[SURFACE_SLOT_TARGET_INDEX] != None:
                return
            if node[CARRY_INDEX][CARRY_TARGET_INDEX] is None:
                return
            target = node[BODY_INDEX][BODY_TARGET_INDEX]
            if target is not None and not target == self._surface_target and not target.parent == self._surface_target:
                return
            carry_aspect = PostureAspectCarry((self._posture_type, None, PostureSpecVariable.HAND))
            surface_aspect = PostureAspectSurface((self._surface_target, self._slot_type, self._slot_target))
            return node.clone(carry=carry_aspect, surface=surface_aspect)

        def get_constraint(self, sim, node, var_map):
            carry_target = var_map[PostureSpecVariable.CARRY_TARGET]
            parent_slot = var_map.get(PostureSpecVariable.SLOT)
            if PostureSpecVariable.SLOT not in var_map:
                from interactions.constraints import Nowhere
                return Nowhere()
            if parent_slot is None or not isinstance(parent_slot, RuntimeSlot):
                if isinstance(parent_slot, animation.posture_manifest.SlotManifestEntry):
                    for parent_slot in self._surface_target.get_runtime_slots_gen(slot_types=parent_slot.slot_types):
                        break
                    raise RuntimeError('Failed to resolve slot on {} of type {}'.format(self._surface_target, parent_slot.slot_types))
                else:
                    for parent_slot in self._surface_target.get_runtime_slots_gen(slot_types={parent_slot}):
                        break
                    raise RuntimeError('Failed to resolve slot on {} of type {}'.format(self._surface_target, {parent_slot}))
            from carry.carry_postures import CarrySystemRuntimeSlotTarget
            carry_system_target = CarrySystemRuntimeSlotTarget(sim, carry_target, True, parent_slot)
            return carry_system_target.get_constraint(sim)

    class TargetAlreadyInSlot(OperationBase):
        __qualname__ = 'PostureOperation.TargetAlreadyInSlot'
        __slots__ = ('_slot_target', '_surface_target', '_slot_type')

        def __init__(self, slot_target, surface, slot_type):
            self._slot_target = slot_target
            self._surface_target = surface
            self._slot_type = slot_type

        def __repr__(self):
            return '{}({}, {}, {})'.format(type(self).__name__, _str_for_object(self._slot_target), _str_for_object(self._surface_target), _str_for_slot_type(self._slot_type))

        def is_equivalent_to(self, other):
            return type(self) == type(other) and (self._surface_target == other._surface_target and (self._slot_type == other._slot_type and self._slot_target == other._slot_target))

        def apply(self, node):
            if self._slot_target is not None and node[CARRY_INDEX][CARRY_TARGET_INDEX] is not None:
                return
            surface_spec = node[SURFACE_INDEX]
            if surface_spec[SURFACE_TARGET_INDEX] is not None:
                return
            if surface_spec[SURFACE_SLOT_TARGET_INDEX] is not None:
                return
            target = node[BODY_INDEX][BODY_TARGET_INDEX]
            if target is None:
                return
            if not target == self._surface_target and not target.parent == self._surface_target:
                return
            surface_aspect = PostureAspectSurface((self._surface_target, self._slot_type, self._slot_target))
            return node.clone(surface=surface_aspect)

        def validate(self, node, sim, var_map):
            slot_child = self._slot_target
            if slot_child is None:
                return True
            child = var_map.get(slot_child)
            if child is None:
                return True
            surface = self._surface_target
            if surface is None:
                return False
            if child.parent != surface:
                return False
            slot_type = self._slot_type
            if slot_type is None:
                return True
            slot_manifest = var_map.get(slot_type)
            if slot_manifest is None:
                return True
            current_slot = child.parent_slot
            if current_slot in surface.get_runtime_slots_gen(slot_types=slot_manifest.slot_types):
                return True
            return False

    class ForgetSurface(OperationBase):
        __qualname__ = 'PostureOperation.ForgetSurface'
        __slots__ = ()

        def __init__(self):
            pass

        def __repr__(self):
            return '{}()'.format(type(self).__name__)

        def is_equivalent_to(self, other):
            return type(self) == type(other)

        def apply(self, node):
            surface = node[SURFACE_INDEX]
            if surface[SURFACE_TARGET_INDEX] is not None:
                surface_aspect = PostureAspectSurface((None, None, None))
                return node.clone(surface=surface_aspect)

    FORGET_SURFACE_OP = ForgetSurface()

