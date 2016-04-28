import functools
from animation import get_throwaway_animation_context
from carry import hide_held_props
from interactions.constraints import Anywhere, TunableCone, TunableFacing, TunableCircle
from interactions.utils.animation import ArbElement
from interactions.utils.sim_focus import with_sim_focus, SimFocus
from objects import VisibilityState
from objects.components.types import CARRYABLE_COMPONENT
from objects.slots import get_surface_height_parameter_for_object
from placement import FGLSearchFlag
from postures.posture_specs import PostureSpecVariable, SURFACE_INDEX, SURFACE_TARGET_INDEX
from sims4.collections import frozendict
import animation
import animation.arb
import animation.asm
import build_buy
import carry
import interactions.constraints
import placement
import postures.posture
import sims4.log
import sims4.math
logger = sims4.log.Logger('Carry')

class CarryTuning:
    __qualname__ = 'CarryTuning'
    _SWIPE_DISTANCE = TunableCircle(2, description='Circle constraint used when a Sim decides to use a generic swipe to pick up / put down an object')
    _SWIPE_FACING = TunableFacing(description='The angle at which to address an object to pick up or put down.')
    _SWIPE_DISTANCE_NONMOBILE = TunableCircle(1.2, description='Circle constraint used when a Sim decides to use a generic swipe to pick up / put down an object while in a non-mobile posture. This constraint will be added to the normal constraint as another option since we want Sims to be able to to grab objects outside of their normal facing range when seated to avoid stupid transitions when getting nearby objects.')
    _SWIPE_FACING_NONMOBILE = TunableFacing(description='An expanded angle to pick up and put down objects when in a non-mobile posture such as seated at a chair. This is intersected with the nonmobile distance constraint and added as an additional option for Sims when seated.')
    _INVENTORY_SWIPE_DISTANCE = TunableCone(0.5, 1.7, 0.5*sims4.math.PI, description='The minimum distance at which to address an object inventory.')
    _INVENTORY_SWIPE_FACING = TunableFacing(description='The angle at which to address an object inventory.')

class CarrySystemTarget:
    __qualname__ = 'CarrySystemTarget'

    def __init__(self, obj, put):
        self._obj = obj
        self._put = put

    @property
    def _route_target(self):
        return self._obj

    def get_constraint(self, sim, **kwargs):
        return CarryingObject.get_carry_transition_position_constraint(self._route_target.position, self._route_target.routing_surface, **kwargs)

    @property
    def surface_height(self) -> str:
        return get_surface_height_parameter_for_object(self._obj)

    @property
    def has_custom_animation(self) -> bool:
        raise NotImplementedError()

    def append_custom_animation_to_arb(self, arb, carry_posture, normal_carry_callback):
        raise NotImplementedError()

    def carry_event_callback(self, *_, **__):
        raise NotImplementedError()

class CarrySystemTransientTarget(CarrySystemTarget):
    __qualname__ = 'CarrySystemTransientTarget'

    def __init__(self, obj, put):
        super().__init__(obj, put)

    @property
    def surface_height(self) -> str:
        return 'discard'

    @property
    def has_custom_animation(self) -> bool:
        return False

    def carry_event_callback(self, *_, **__):
        self._obj.remove_from_client()

class CarrySystemTerrainTarget(CarrySystemTarget):
    __qualname__ = 'CarrySystemTerrainTarget'

    def __init__(self, sim, obj, put, starting_transform):
        super().__init__(obj, put)
        if put and obj.carryable_component.put_down_tuning.put_down_on_terrain_facing_sim:
            angle = sims4.math.yaw_quaternion_to_angle(starting_transform.orientation) + sims4.math.deg_to_rad(180)
            starting_transform.orientation = sims4.math.angle_to_yaw_quaternion(angle)
        self._starting_transform = starting_transform

    @property
    def surface_height(self) -> str:
        return 'low'

    @property
    def has_custom_animation(self) -> bool:
        return False

    def carry_event_callback(self, *_, **__):
        if self._put:
            CarryingObject.snap_to_good_location_on_floor(self._obj, self._starting_transform)

    def get_constraint(self, sim, **kwargs):
        carryable = self._obj.get_component(CARRYABLE_COMPONENT)
        if carryable is not None and carryable.constraint_pick_up is not None:
            constraint_total = Anywhere()
            for constraint_factory in carryable.constraint_pick_up:
                constraint = constraint_factory.create_constraint(sim, target=self._obj, routing_surface=self._obj.routing_surface)
                constraint_total = constraint_total.intersect(constraint)
            return constraint_total
        return super().get_constraint(sim)

class CarrySystemCustomAnimationTarget(CarrySystemTarget):
    __qualname__ = 'CarrySystemCustomAnimationTarget'
    _custom_constraint = None
    _custom_animation = None

    def get_constraint(self, sim, **kwargs):
        if self._custom_constraint is not None:
            return self._custom_constraint
        return super().get_constraint(sim, **kwargs)

    @property
    def has_custom_animation(self) -> bool:
        return self._custom_animation is not None

    def append_custom_animation_to_arb(self, arb, carry_posture, normal_carry_callback):
        custom_carry_event_callback = self.carry_event_callback

        def _carry_event_callback(*_, **__):
            custom_carry_event_callback()
            normal_carry_callback()

        self.carry_event_callback = _carry_event_callback
        self._custom_animation(arb, carry_posture.sim, carry_posture.target, carry_posture.track, carry_posture.animation_context, self.surface_height)

class CarrySystemRuntimeSlotTarget(CarrySystemCustomAnimationTarget):
    __qualname__ = 'CarrySystemRuntimeSlotTarget'

    def __init__(self, sim, obj, put, runtime_slot):
        super().__init__(obj, put)
        if runtime_slot is None:
            raise RuntimeError('Attempt to create a CarrySystemRuntimeSlotTarget with no runtime slot!')
        self._runtime_slot = runtime_slot
        if not runtime_slot.owner.is_sim:
            self._custom_constraint = runtime_slot.owner.get_surface_access_constraint(sim, put, obj)
            self._custom_animation = runtime_slot.owner.get_surface_access_animation(put)

    @property
    def _route_target(self):
        return self._runtime_slot

    @property
    def surface_height(self) -> str:
        (_, surface_height) = self._runtime_slot.slot_height_and_parameter
        return surface_height

    def carry_event_callback(self, *_, **__):
        if self._put:
            self._runtime_slot.add_child(self._obj)

class CarrySystemInventoryTarget(CarrySystemCustomAnimationTarget):
    __qualname__ = 'CarrySystemInventoryTarget'

    def __init__(self, sim, obj, is_put, inventory_owner):
        super().__init__(obj, is_put)
        self._inventory_owner = inventory_owner
        self._custom_constraint = inventory_owner.get_inventory_access_constraint(sim, is_put, obj)
        self._custom_animation = inventory_owner.get_inventory_access_animation(is_put)

    @property
    def surface_height(self) -> str:
        if self._inventory_owner.is_sim:
            return 'inventory'
        return 'high'

    def carry_event_callback(self, *_, **__):
        if self._put:
            self._inventory_owner.inventory_component.system_add_object(self._obj, self._inventory_owner)

class CarryPosture(postures.posture.Posture):
    __qualname__ = 'CarryPosture'
    INSTANCE_SUBCLASSES_ONLY = True
    _XEVT_ID = None
    IS_BODY_POSTURE = False

    @classmethod
    def _tuning_loaded_callback(cls):
        asm = animation.asm.Asm(cls._asm_key, get_throwaway_animation_context())
        provided_postures = asm.get_supported_postures_for_actor('x')
        cls._provided_postures = provided_postures
        cls.get_provided_postures = lambda *_, **__: provided_postures

    def _event_handler_start_pose(self, *args, **kwargs):
        arb = animation.arb.Arb()
        self.asm.request(self._state_name, arb)
        ArbElement(arb).distribute()

    def append_transition_to_arb(self, arb, source_posture, in_xevt_handler=False, **kwargs):
        self.asm.context.register_custom_event_handler(functools.partial(hide_held_props, self.sim), None, 0, allow_stub_creation=True)
        super().append_transition_to_arb(arb, source_posture, **kwargs)
        if in_xevt_handler:
            self.asm.request(self._state_name, arb)
        else:
            arb.register_event_handler(self._event_handler_start_pose, animation.ClipEventType.Script, self._XEVT_ID)

    @property
    def slot_constraint(self):
        pass

class CarryingNothing(CarryPosture):
    __qualname__ = 'CarryingNothing'
    _XEVT_ID = carry.SCRIPT_EVENT_ID_STOP_CARRY

    def _setup_asm_carry_parameter(self, asm, target):
        if not asm.set_parameter(carry.PARAM_CARRY_TRACK, self.track.name.lower()):
            logger.warn('Failed to set {} on {}.', carry.PARAM_CARRY_TRACK, asm.name)

    @property
    def source_interaction(self):
        pass

    @source_interaction.setter
    def source_interaction(self, value):
        pass

    def append_transition_to_arb(self, arb, source_posture, locked_params=frozendict(), **kwargs):
        if source_posture is not None:
            target = source_posture.target
            if target is not None:
                target_anim_overrides = target.get_anim_overrides(source_posture.target_name)
                locked_params += target_anim_overrides.params
                self.asm.set_actor(source_posture.target_name, source_posture.target)
        super().append_transition_to_arb(arb, source_posture, locked_params=locked_params, **kwargs)

    def _update_non_body_posture_asm(self):
        pass

class CarryingObject(CarryPosture):
    __qualname__ = 'CarryingObject'
    _XEVT_ID = carry.SCRIPT_EVENT_ID_START_CARRY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.holstered = False
        self.carry_system_target = None

    def _setup_asm_carry_parameter(self, asm, target):
        carry.set_carry_track_param(asm, self._target_name, target, self.track)

    def add_transition_extras(self, sequence):
        return with_sim_focus(self.sim, self.sim, self.target, SimFocus.LAYER_INTERACTION, sequence)

    @property
    def target_is_transient(self) -> bool:
        if self.target is not None:
            return self.target.transient
        return False

    SNAP_TO_GOOD_LOCATION_SEARCH_FLAGS = FGLSearchFlag.STAY_IN_SAME_CONNECTIVITY_GROUP | FGLSearchFlag.SHOULD_TEST_ROUTING | FGLSearchFlag.CALCULATE_RESULT_TERRAIN_HEIGHTS | FGLSearchFlag.DONE_ON_MAX_RESULTS | FGLSearchFlag.SHOULD_TEST_BUILDBUY

    @staticmethod
    def snap_to_good_location_on_floor(target, starting_transform=None, starting_routing_surface=None):
        target.visibility = VisibilityState(True, True, True)
        parent = target.get_parenting_root()
        if starting_transform is None:
            starting_transform = parent.transform
            starting_transform = sims4.math.Transform(parent.position + parent.forward*parent.object_radius, starting_transform.orientation)
        if starting_routing_surface is None:
            starting_routing_surface = parent.routing_surface
        search_flags = CarryingObject.SNAP_TO_GOOD_LOCATION_SEARCH_FLAGS
        (trans, orient) = placement.find_good_location(placement.FindGoodLocationContext(starting_transform=starting_transform, starting_routing_surface=starting_routing_surface, object_footprints=(target.footprint,), object_id=target.id, search_flags=search_flags))
        if starting_transform is not None and (starting_transform.translation != trans or starting_transform.orientation != orient):
            logger.debug("snap_to_good_location_on_floor's FGL couldn't use the exact suggested starting transform.")
        if trans is not None:
            target.clear_parent(sims4.math.Transform(trans, orient), starting_routing_surface)
            return True
        logger.warn('snap_to_good_location_on_floor could not find good location for {}.', target)
        target.clear_parent(starting_transform, starting_routing_surface)
        return False

    def setup_asm_posture(self, asm, sim, target, **kwargs):
        if not super().setup_asm_posture(asm, sim, target, **kwargs):
            return False
        if 'locked_params' not in kwargs or 'surfaceHeight' not in kwargs['locked_params']:
            surface_height = get_surface_height_parameter_for_object(target)
            self.asm.set_parameter('surfaceHeight', surface_height)
        return True

    @staticmethod
    def get_carry_transition_position_constraint(position, routing_surface, cost=0, mobile=True):
        if mobile:
            swipe_constraint = CarryTuning._SWIPE_DISTANCE.create_constraint(None, None, target_position=position, routing_surface=routing_surface)
            facing_constraint = CarryTuning._SWIPE_FACING.create_constraint(None, target_position=position)
        else:
            swipe_constraint = CarryTuning._SWIPE_DISTANCE_NONMOBILE.create_constraint(None, None, target_position=position, routing_surface=routing_surface)
            facing_constraint = CarryTuning._SWIPE_FACING_NONMOBILE.create_constraint(None, target_position=position)
        constraint = swipe_constraint.intersect(facing_constraint)
        constraint = constraint.generate_constraint_with_cost(cost)
        return constraint

    def destroy_held_props(self, for_other_sis):
        sis = set()
        if self.source_interaction is not None:
            sis.add(self.source_interaction)
        for owning_interaction in self.owning_interactions:
            sis.add(owning_interaction)
        if for_other_sis:
            sis = set(self.sim.si_state) - sis
        for si in sis:
            si.animation_context.destroy_all_props(held_only=True)

    def append_transition_to_arb(self, arb, source_posture, in_xevt_handler=False, locked_params=frozendict(), posture_spec=None, **kwargs):
        if in_xevt_handler:
            locked_params += {'surfaceHeight': 'from_xevt'}
            super().append_transition_to_arb(arb, source_posture, locked_params=locked_params, in_xevt_handler=in_xevt_handler, **kwargs)
            return
        carry_system_target = CarrySystemTerrainTarget(self.sim, self.target, False, self.target.transform)
        if self.target.is_in_inventory():
            if self.target.is_in_sim_inventory():
                obj_with_inventory = self.target.get_inventory().owner
            elif posture_spec is not None:
                surface = posture_spec[SURFACE_INDEX]
                obj_with_inventory = surface[SURFACE_TARGET_INDEX]
            else:
                obj_with_inventory = None
            if obj_with_inventory is None:
                obj_with_inventory = self.target.get_inventory().owner
            carry_system_target = CarrySystemInventoryTarget(self.sim, self.target, False, obj_with_inventory)
        else:
            runtime_slot = self.target.parent_slot
            if runtime_slot is not None:
                carry_system_target = CarrySystemRuntimeSlotTarget(self.sim, self.target, False, runtime_slot)
            if self.target.parent is not None:
                self.asm.set_actor('surface', self.target.parent)
        call_super = True
        if carry_system_target.has_custom_animation:

            def normal_carry_callback():
                arb = animation.arb.Arb()
                self.append_transition_to_arb(arb, source_posture, locked_params=locked_params, in_xevt_handler=True)
                ArbElement(arb).distribute()

            carry_system_target.append_custom_animation_to_arb(arb, self, normal_carry_callback)
            call_super = False
        arb.register_event_handler(carry_system_target.carry_event_callback, animation.ClipEventType.Script, carry.SCRIPT_EVENT_ID_START_CARRY)
        if call_super:
            super().append_transition_to_arb(arb, source_posture, locked_params=locked_params, in_xevt_handler=in_xevt_handler, **kwargs)

    def append_exit_to_arb(self, arb, dest_state, dest_posture, var_map, exit_while_holding=False, **kwargs):
        if exit_while_holding:
            self.asm.set_parameter('surfaceHeight', 'from_xevt')
            if self.target_is_transient:
                self.target.remove_from_client()
            super().append_exit_to_arb(arb, dest_state, dest_posture, var_map, **kwargs)
            return
        if self.carry_system_target is None:
            if self.target_is_transient:
                self.carry_system_target = CarrySystemTransientTarget(self.target, True)
            else:
                (surface, slot_var) = dest_state.get_slot_info()
                if slot_var is None:
                    self.sim.schedule_reset_asap(cause='slot_var is None in append_exit_to_arb where we expect to be putting an object down in a slot')
                    logger.error('slot_var is None in append_exit_to_arb: arb: {} dest_state: {} dest_posture: {} var_map: {}', arb, dest_state, dest_posture, var_map, owner='tastle')
                    return
                self.asm.set_actor('surface', surface)
                slot_manifest = var_map[slot_var]
                var_map += {PostureSpecVariable.SURFACE_TARGET: surface}
                slot_manifest = slot_manifest.apply_actor_map(var_map.get)
                runtime_slot = slot_manifest.runtime_slot
                if runtime_slot is None:
                    raise RuntimeError('Attempt to create a CarrySystemRuntimeSlotTarget with no valid runtime slot: {}'.format(slot_manifest))
                self.carry_system_target = CarrySystemRuntimeSlotTarget(self.sim, self.target, True, runtime_slot)
        arb.register_event_handler(self.carry_system_target.carry_event_callback, animation.ClipEventType.Script, carry.SCRIPT_EVENT_ID_STOP_CARRY)
        if self.carry_system_target.has_custom_animation:

            def normal_carry_callback():
                arb = animation.arb.Arb()
                self.append_exit_to_arb(arb, dest_state, dest_posture, var_map, exit_while_holding=True)
                ArbElement(arb).distribute()

            self.carry_system_target.append_custom_animation_to_arb(arb, self, normal_carry_callback)
            return
        self.asm.set_parameter('surfaceHeight', self.carry_system_target.surface_height)
        super().append_exit_to_arb(arb, dest_state, dest_posture, var_map, **kwargs)

    def _drop_carried_object(self):
        if self.target is None:
            return
        if self.target_is_transient or self.target.parent is not self.sim:
            return
        if self.snap_to_good_location_on_floor(self.target):
            return
        if self.sim.household.id is self.target.get_household_owner_id() and self.sim.inventory_component.player_try_add_object(self.target):
            return
        placement_flags = build_buy.get_object_placement_flags(self.target.definition.id)
        if placement_flags & build_buy.PlacementFlags.NON_DELETEABLE and placement_flags & build_buy.PlacementFlags.NON_INVENTORYABLE:
            logger.error("Failed to find a location to place {}, which cannot be deleted or moved to the household inventory.                           Object will be placed at the Sim's feet, but this is unsafe and will probably result in the object being                           destroyed on load.", self.target, owner='tastle')
            return
        if placement_flags & build_buy.PlacementFlags.NON_INVENTORYABLE:
            self.target.destroy(source=self.sim, cause='Failed to find location to drop non inventoryable object.')
        else:
            build_buy.move_object_to_household_inventory(self.target)

    def _on_reset(self):
        super()._on_reset()
        self._drop_carried_object()

