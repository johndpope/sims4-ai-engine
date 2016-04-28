from weakref import WeakSet
from animation.posture_manifest import SlotManifestEntry, SlotManifest
from animation.posture_manifest_constants import STAND_OR_SIT_CONSTRAINT, STAND_POSTURE_MANIFEST, SIT_POSTURE_MANIFEST
from carry import exit_carry_while_holding, create_carry_constraint, enter_carry_while_holding, SCRIPT_EVENT_ID_START_CARRY, swap_carry_while_holding
from carry.carry_postures import CarrySystemInventoryTarget, CarrySystemTerrainTarget, CarryingObject
from event_testing.results import TestResult
from interactions import ParticipantType
from interactions.base.basic import TunableBasicContentSet
from interactions.base.super_interaction import SuperInteraction
from interactions.constraints import JigConstraint, create_constraint_set, Constraint, Nowhere
from objects.helpers.create_object_helper import CreateObjectHelper
from objects.object_enums import ResetReason
from objects.slots import get_surface_height_parameter_for_object
from objects.terrain import TerrainSuperInteraction
from postures.posture_specs import PostureSpecVariable
from postures.posture_state_spec import PostureStateSpec
from sims.sim import Sim
from sims4.tuning.tunable import Tunable, TunableTuple, TunableReference, OptionalTunable, TunableVariant
from sims4.utils import flexmethod, classproperty
import element_utils
import objects.game_object
import services
import sims4.log
logger = sims4.log.Logger('PutDownInteractions')
EXCLUSION_MULTIPLIER = None
OPTIMAL_MULTIPLIER = 0
DISCOURAGED_MULTIPLIER = 100

class PutDownChooserInteraction(SuperInteraction):
    __qualname__ = 'PutDownChooserInteraction'

    def _run_interaction_gen(self, timeline):
        context = self.context.clone_for_continuation(self)
        if self.target.carryable_component.prefer_owning_sim_inventory_when_not_on_home_lot and self.target.get_household_owner_id() == self.sim.household_id and not self.sim.on_home_lot:
            aop = self.target.get_put_down_aop(self, context, own_inventory_multiplier=OPTIMAL_MULTIPLIER, on_floor_multiplier=EXCLUSION_MULTIPLIER, visibility_override=self.visible, display_name_override=self.display_name, add_putdown_liability=True, must_run=self.must_run)
        else:
            aop = self.target.get_put_down_aop(self, context, visibility_override=self.visible, display_name_override=self.display_name, add_putdown_liability=True, must_run=self.must_run)
        execute_result = aop.test_and_execute(context)
        if not execute_result:
            logger.error('Put down test failed.\n                aop:{}\n                test result:{} [tastle/trevorlindsey]'.format(aop, execute_result.test_result))
            self.sim.reset(ResetReason.RESET_EXPECTED, self, 'Put down test failed.')
        return execute_result

    @classproperty
    def is_putdown(cls):
        return True

    @classproperty
    def requires_target_support(cls):
        return False

    @flexmethod
    def _constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        for constraint in super(SuperInteraction, cls)._constraint_gen(sim, target, participant_type=participant_type):
            yield constraint
        yield create_carry_constraint(target, debug_name='CarryForPutDown')

class PutAwayBase(SuperInteraction):
    __qualname__ = 'PutAwayBase'

    def _run_interaction_gen(self, timeline):
        yield super()._run_interaction_gen(timeline)
        main_social_group = self.sim.get_main_group()
        if main_social_group is not None:
            main_social_group.execute_adjustment_interaction(self.sim, force_allow_posture_changes=True)

class PutInInventoryInteraction(PutAwayBase):
    __qualname__ = 'PutInInventoryInteraction'
    INSTANCE_TUNABLES = {'basic_content': TunableBasicContentSet(no_content=True, default='no_content')}

    @classmethod
    def _test(cls, *args, target_with_inventory=None, **interaction_parameters):
        if not isinstance(target_with_inventory, objects.game_object.GameObject):
            return TestResult(False, 'target_with_inventory must be a GameObject: {}', target_with_inventory)
        if target_with_inventory is not None and target_with_inventory.inventory_component is None:
            return TestResult(False, 'target_with_inventory must have an inventory: {}', target_with_inventory)
        return super()._test(target_with_inventory=target_with_inventory, *args, **interaction_parameters)

    def __init__(self, *args, target_with_inventory=None, **kwargs):
        super().__init__(*args, **kwargs)
        if target_with_inventory is None:
            target_with_inventory = self.sim
        self._carry_system_target = CarrySystemInventoryTarget(self.sim, self.target, True, target_with_inventory)

    @classproperty
    def is_putdown(cls):
        return True

    def build_basic_content(self, sequence, **kwargs):
        sequence = super().build_basic_content(sequence, **kwargs)
        return exit_carry_while_holding(self, sequence=sequence, use_posture_animations=True, carry_system_target=self._carry_system_target)

    @flexmethod
    def _constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        for constraint in super(SuperInteraction, cls)._constraint_gen(sim, target, participant_type=participant_type):
            yield constraint
        yield create_carry_constraint(target, debug_name='CarryForPutDown')
        if inst is not None:
            yield inst._carry_system_target.get_constraint(sim)

    @classproperty
    def requires_target_support(cls):
        return False

class CollectManyInteraction(SuperInteraction):
    __qualname__ = 'CollectManyInteraction'
    INTERACTION_TARGET = 'interaction_target'
    INSTANCE_TUNABLES = {'aggregate_object': TunableVariant(description='\n            The type of object to use as the aggregate object.  If a definition\n            is specified, the aggregate object will be created using that\n            definition.  If "interaction_target" is specified, the aggregate object\n            will be created using the definition of the interaction target.\n            ', definition=TunableReference(description='\n                A reference to the type of object that will be created as part\n                of this interaction to represent the many collected objects the\n                participant has picked up.\n                ', manager=services.definition_manager()), locked_args={'interaction_target': INTERACTION_TARGET}, default='definition'), 'destroy_original_object': Tunable(description="\n            If checked, the original object (the target of this interaction),\n            will be destroyed and replaced with the specified aggregate object.\n            If unchecked, the aggregate object will be created in the Sim's\n            hand, but the original object will not be destroyed.\n            ", tunable_type=bool, default=True)}
    DIRTY_DISH_ACTOR_NAME = 'dirtydish'
    ITEMS_PARAM = 'items'
    _object_create_helper = None
    _collected_targets = WeakSet()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_carry_target = None

    @property
    def create_object_owner(self):
        return self.sim

    @property
    def _aggregate_object_definition(self):
        if self.aggregate_object is self.INTERACTION_TARGET:
            return self.target.definition
        return self.aggregate_object

    @property
    def create_target(self):
        if self.context.carry_target is not None:
            return
        return self._aggregate_object_definition

    @property
    def created_target(self):
        return self.context.carry_target

    @classmethod
    def _test(cls, target, context, **interaction_parameters):
        if target is not None and target in cls._collected_targets:
            return TestResult(False, 'Target was already collected.')
        return super()._test(target, context, **interaction_parameters)

    def _setup_collected_object(self, obj):
        self.context.carry_target = obj

    def setup_asm_default(self, asm, *args, **kwargs):
        result = super().setup_asm_default(asm, *args, **kwargs)
        if self.target is not None:
            surface_height = get_surface_height_parameter_for_object(self.target)
            asm.set_parameter('surfaceHeight', surface_height)
            if self.target.parent is not None:
                asm.set_actor('surface', self.target.parent)
        if self._original_carry_target is not None:
            param_overrides = self._original_carry_target.get_param_overrides(self.DIRTY_DISH_ACTOR_NAME, only_for_keys=(self.ITEMS_PARAM,))
            if param_overrides is not None:
                asm.update_locked_params(param_overrides)
        return result

    def build_basic_content(self, sequence=(), **kwargs):
        self.animation_context.register_event_handler(self._xevt_callback, handler_id=SCRIPT_EVENT_ID_START_CARRY)
        if self._aggregate_object_definition is None or self.carry_target is not None and self._aggregate_object_definition is self.carry_target.definition:
            if self.context.carry_target is None:
                self._setup_collected_object(self.target)
            return super().build_basic_content(sequence, **kwargs)
        if self.carry_target is not None:
            swap_carry = True
            self._original_carry_target = self.carry_target
        else:
            swap_carry = False
        self._object_create_helper = CreateObjectHelper(self.sim, self._aggregate_object_definition.id, self, post_add=self._setup_collected_object, tag='Aggregate object created for a CollectManyInteraction.')
        super_build_basic_content = super().build_basic_content

        def grab_sequence(timeline):
            nonlocal sequence
            sequence = super_build_basic_content(sequence)
            if swap_carry:
                sequence = swap_carry_while_holding(self, self._original_carry_target, self.created_target, callback=self._object_create_helper.claim, sequence=sequence)
            else:
                sequence = enter_carry_while_holding(self, self.created_target, callback=self._object_create_helper.claim, create_si_fn=None, sequence=sequence)
            result = yield element_utils.run_child(timeline, sequence)

        return self._object_create_helper.create(grab_sequence)

    def _xevt_callback(self, *_, **__):
        if self.carry_target is not None and self.target is not None:
            if self._object_create_helper is None:
                for statistic in self.target.statistic_tracker:
                    self.carry_target.statistic_tracker.add_value(statistic.stat_type, statistic.get_value())
            elif self._original_carry_target is not None:
                for statistic in self._original_carry_target.statistic_tracker:
                    self.carry_target.statistic_tracker.add_value(statistic.stat_type, statistic.get_value())
            elif self.aggregate_object is self.INTERACTION_TARGET:
                self.carry_target.copy_state_values(self.target)
            else:
                for statistic in self.target.statistic_tracker:
                    self.carry_target.statistic_tracker.set_value(statistic.stat_type, statistic.get_value())
        if self.destroy_original_object and self.target is not None:
            self._collected_targets.add(self.target)
            self.target.transient = True
            self.target.remove_from_client()

    @classproperty
    def requires_target_support(cls):
        return False

class PutAwayInteraction(SuperInteraction):
    __qualname__ = 'PutAwayInteraction'

    def _run_interaction_gen(self, timeline):
        context = self.context.clone_for_continuation(self)
        aop = self.target.get_put_down_aop(self, context, alternative_multiplier=EXCLUSION_MULTIPLIER, own_inventory_multiplier=EXCLUSION_MULTIPLIER, object_inventory_multiplier=OPTIMAL_MULTIPLIER, in_slot_multiplier=EXCLUSION_MULTIPLIER, on_floor_multiplier=EXCLUSION_MULTIPLIER, visibility_override=self.visible, display_name_override=self.display_name, additional_post_run_autonomy_commodities=self.post_run_autonomy_commodities.requests)
        if aop is not None:
            return aop.test_and_execute(context)
        return False

    @classproperty
    def is_putdown(cls):
        return True

    @classproperty
    def requires_target_support(cls):
        return False

    def _get_post_run_autonomy(self):
        pass

    @flexmethod
    def _constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        for constraint in super(SuperInteraction, cls)._constraint_gen(sim, target, participant_type=participant_type):
            yield constraint
        yield create_carry_constraint(target, debug_name='CarryForPutDown')

class PutDownQuicklySuperInteraction(PutAwayBase):
    __qualname__ = 'PutDownQuicklySuperInteraction'

    def _run_interaction_gen(self, timeline):
        context = self.context.clone_for_continuation(self)
        aop = self.target.get_put_down_aop(self, context, own_inventory_multiplier=OPTIMAL_MULTIPLIER, on_floor_multiplier=DISCOURAGED_MULTIPLIER, in_slot_multiplier=DISCOURAGED_MULTIPLIER, object_inventory_multiplier=DISCOURAGED_MULTIPLIER, visibility_override=self.visible, display_name_override=self.display_name, add_putdown_liability=True, must_run=self.must_run)
        execute_result = aop.test_and_execute(context)
        if not execute_result:
            logger.error('Put down test failed.\n                aop:{}\n                test result:{} [tastle]'.format(aop, execute_result.test_result))
            self.sim.reset(ResetReason.RESET_EXPECTED, self, 'Put down test failed.')
        return execute_result

    @classproperty
    def is_putdown(cls):
        return True

    @classproperty
    def requires_target_support(cls):
        return False

    @flexmethod
    def _constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        for constraint in super(SuperInteraction, cls)._constraint_gen(sim, target, participant_type=participant_type):
            yield constraint
        yield create_carry_constraint(target, debug_name='CarryForPutDown')

class AddToWorldSuperInteraction(SuperInteraction):
    __qualname__ = 'AddToWorldSuperInteraction'
    INSTANCE_TUNABLES = {'basic_content': TunableBasicContentSet(no_content=True, default='no_content'), 'put_down_cost_multipliers': TunableTuple(description='\n            Multipliers to be applied to the different put downs possible when\n            determining the best put down aop.\n            ', in_slot_multiplier=OptionalTunable(enabled_by_default=True, tunable=Tunable(description='\n                    Cost multiplier for sims putting the object down in a slot.\n                    ', tunable_type=float, default=1)), on_floor_multiplier=OptionalTunable(enabled_by_default=True, tunable=Tunable(description='\n                    Cost multiplier for sims putting the object down on the\n                    floor.\n                    ', tunable_type=float, default=1)))}

    @flexmethod
    def skip_test_on_execute(cls, inst):
        return True

    def _run_interaction_gen(self, timeline):
        self.target.inventoryitem_component.clear_previous_inventory()
        context = self.context.clone_for_continuation(self)
        aop = self.target.get_put_down_aop(self, context, own_inventory_multiplier=EXCLUSION_MULTIPLIER, object_inventory_multiplier=EXCLUSION_MULTIPLIER, in_slot_multiplier=self.put_down_cost_multipliers.in_slot_multiplier, on_floor_multiplier=self.put_down_cost_multipliers.on_floor_multiplier, visibility_override=self.visible, display_name_override=self.display_name)
        if aop is not None:
            return aop.test_and_execute(context)
        return False

    @flexmethod
    def _constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        for constraint in super(SuperInteraction, cls)._constraint_gen(sim, target, participant_type=participant_type):
            yield constraint
        carry_constraint = create_carry_constraint(target, debug_name='CarryForAddInWorld')
        total_constraint = carry_constraint.intersect(STAND_OR_SIT_CONSTRAINT)
        yield total_constraint

    @classproperty
    def is_putdown(cls):
        return True

    @classproperty
    def requires_target_support(cls):
        return False

class SwipeAddToWorldSuperInteraction(SuperInteraction):
    __qualname__ = 'SwipeAddToWorldSuperInteraction'

    def _run_interaction_gen(self, timeline):
        liability = self.get_liability(JigConstraint.JIG_CONSTRAINT_LIABILITY)
        if self.sim.inventory_component.try_remove_object_by_id(self.target.id):
            new_location = self.target.location.clone()
            new_location.transform = liability.jig.transform
            new_location.routing_surface = liability.jig.routing_surface
            self.target.inventoryitem_component.clear_previous_inventory()
            self.target.opacity = 0
            self.target.location = new_location
            self.target.fade_in()

    @classproperty
    def is_putdown(cls):
        return True

class PutDownHereInteraction(TerrainSuperInteraction):
    __qualname__ = 'PutDownHereInteraction'

    def __init__(self, *args, put_down_transform, **kwargs):
        super().__init__(*args, **kwargs)
        self._carry_system_target = CarrySystemTerrainTarget(self.sim, self.target, True, put_down_transform)

    @classproperty
    def is_putdown(cls):
        return True

    def build_basic_content(self, sequence, **kwargs):
        sequence = super().build_basic_content(sequence, **kwargs)
        return exit_carry_while_holding(self, sequence=sequence, use_posture_animations=True, carry_system_target=self._carry_system_target)

    @flexmethod
    def _constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        for constraint in super(TerrainSuperInteraction, cls)._constraint_gen(sim, target, participant_type=participant_type):
            yield constraint
        yield create_carry_constraint(target, debug_name='CarryForPutDown')
        if inst is not None and inst._carry_system_target._starting_transform is not None:
            yield CarryingObject.get_carry_transition_position_constraint(inst._carry_system_target._starting_transform.translation, sim.routing_surface)

    @classproperty
    def requires_target_support(cls):
        return False

    def _run_interaction_gen(self, timeline):
        yield super()._run_interaction_gen(timeline)
        main_social_group = self.sim.get_main_group()
        if main_social_group is not None:
            main_social_group.execute_adjustment_interaction(self.sim)

class PutDownInSlotInteraction(PutAwayBase):
    __qualname__ = 'PutDownInSlotInteraction'
    INSTANCE_TUNABLES = {'basic_content': TunableBasicContentSet(no_content=True, default='no_content')}

    def __init__(self, *args, slot_types_and_costs, **kwargs):
        super().__init__(*args, **kwargs)
        self._slot_types_and_costs = slot_types_and_costs

    @classmethod
    def _test(cls, target, context, slot=None, **kwargs):
        if target.transient:
            return TestResult(False, 'Target is transient.')
        if slot is not None and not slot.is_valid_for_placement(obj=target):
            return TestResult(False, 'destination slot is occupied or not enough room for {}', target)
        return TestResult.TRUE

    @classproperty
    def is_putdown(cls):
        return True

    @classproperty
    def requires_target_support(cls):
        return False

    @flexmethod
    def _constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        inst_or_cls = inst if inst is not None else cls
        for constraint in super(SuperInteraction, inst_or_cls)._constraint_gen(sim, target, participant_type=participant_type):
            yield constraint
        if inst is not None:
            slot_constraint = create_put_down_in_slot_type_constraint(sim, target, inst._slot_types_and_costs)
            yield slot_constraint

def create_put_down_in_slot_type_constraint(sim, target, slot_types_and_costs):
    constraints = []
    for (slot_type, cost) in slot_types_and_costs:
        if cost is None:
            pass
        slot_manifest_entry = SlotManifestEntry(target, PostureSpecVariable.ANYTHING, slot_type)
        slot_manifest = SlotManifest((slot_manifest_entry,))
        posture_state_spec_stand = PostureStateSpec(STAND_POSTURE_MANIFEST, slot_manifest, PostureSpecVariable.ANYTHING)
        posture_constraint_stand = Constraint(debug_name='PutDownInSlotTypeConstraint_Stand', posture_state_spec=posture_state_spec_stand, cost=cost)
        constraints.append(posture_constraint_stand)
        posture_state_spec_sit = PostureStateSpec(SIT_POSTURE_MANIFEST, slot_manifest, PostureSpecVariable.ANYTHING)
        posture_constraint_sit = Constraint(debug_name='PutDownInSlotTypeConstraint_Sit', posture_state_spec=posture_state_spec_sit, cost=cost)
        constraints.append(posture_constraint_sit)
    if not constraints:
        return Nowhere()
    final_constraint = create_constraint_set(constraints)
    return final_constraint

def create_put_down_on_ground_constraint(sim, target, terrain_transform, cost=0):
    if cost is None or terrain_transform is None:
        return Nowhere()
    swipe_constraint = CarryingObject.get_carry_transition_position_constraint(terrain_transform.translation, sim.routing_surface)
    carry_constraint = create_carry_constraint(target, debug_name='CarryForPutDownOnGround')
    final_constraint = swipe_constraint.intersect(carry_constraint).intersect(STAND_OR_SIT_CONSTRAINT)
    return final_constraint.generate_constraint_with_cost(cost)

def create_put_down_in_inventory_constraint(inst, sim, target, targets_with_inventory, cost=0):
    if cost is None or not targets_with_inventory:
        return Nowhere()
    carry_constraint = create_carry_constraint(target, debug_name='CarryForPutDownInInventory')
    carry_constraint = carry_constraint.generate_constraint_with_cost(cost)
    object_constraints = []
    for target_with_inventory in targets_with_inventory:
        constraint = target_with_inventory.get_inventory_access_constraint(sim, True, target)
        constraint = constraint.apply_posture_state(None, inst.get_constraint_resolver(None))
        object_constraints.append(constraint)
    final_constraint = create_constraint_set(object_constraints)
    final_constraint = carry_constraint.intersect(final_constraint)
    return final_constraint

class PutDownAnywhereInteraction(PutAwayBase):
    __qualname__ = 'PutDownAnywhereInteraction'

    def __init__(self, *args, slot_types_and_costs, world_cost, sim_inventory_cost, object_inventory_cost, terrain_transform, objects_with_inventory, visibility_override=None, display_name_override=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._slot_types_and_costs = slot_types_and_costs
        self._world_cost = world_cost
        self._sim_inventory_cost = sim_inventory_cost
        self._object_inventory_cost = object_inventory_cost
        self._terrain_transform = terrain_transform
        self._objects_with_inventory = objects_with_inventory
        self._slot_constraint = None
        self._world_constraint = None
        self._sim_inventory_constraint = None
        self._object_inventory_constraint = None
        if visibility_override is not None:
            self.visible = visibility_override
        if display_name_override is not None:
            self.display_name = display_name_override

    @classproperty
    def is_putdown(cls):
        return True

    @classproperty
    def requires_target_support(cls):
        return False

    def build_basic_content(self, sequence, **kwargs):
        sequence = super().build_basic_content(sequence, **kwargs)
        constraint_intersection = self.sim.posture_state.constraint_intersection
        if self.target is not None and (self.target.parent is not None and not self.target.parent.is_sim) and constraint_intersection.intersect(self._slot_constraint).valid:
            return sequence
        if self.target is not None and self.target.parent is not None and self.target.parent is self.sim:
            if constraint_intersection.intersect(self._object_inventory_constraint).valid:
                carry_system_target = CarrySystemInventoryTarget(self.sim, self.target, True, self.sim.posture_state.surface_target)
                return exit_carry_while_holding(self, use_posture_animations=True, carry_system_target=carry_system_target, sequence=sequence)
            world_valid = constraint_intersection.intersect(self._world_constraint).valid and self._world_cost is not None
            sim_inventory_valid = constraint_intersection.intersect(self._sim_inventory_constraint).valid and self._sim_inventory_cost is not None
            if world_valid and sim_inventory_valid:
                sim_inv_chosen = self._sim_inventory_cost <= self._world_cost
            else:
                sim_inv_chosen = sim_inventory_valid
            if sim_inv_chosen:
                carry_system_target = CarrySystemInventoryTarget(self.sim, self.target, True, self.sim)
                return exit_carry_while_holding(self, use_posture_animations=True, carry_system_target=carry_system_target, sequence=sequence)
            carry_system_target = CarrySystemTerrainTarget(self.sim, self.target, True, self._terrain_transform)
            return exit_carry_while_holding(self, use_posture_animations=True, carry_system_target=carry_system_target, sequence=sequence)

    @flexmethod
    def _constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        if inst is not None:
            inst._slot_constraint = create_put_down_in_slot_type_constraint(sim, target, inst._slot_types_and_costs)
            inst._world_constraint = create_put_down_on_ground_constraint(sim, target, inst._terrain_transform, cost=inst._world_cost)
            inst._sim_inventory_constraint = create_put_down_in_inventory_constraint(inst, sim, target, targets_with_inventory=[sim], cost=inst._sim_inventory_cost)
            inst._object_inventory_constraint = create_put_down_in_inventory_constraint(inst, sim, target, targets_with_inventory=inst._objects_with_inventory, cost=inst._object_inventory_cost)
            constraints = [inst._slot_constraint, inst._world_constraint, inst._sim_inventory_constraint, inst._object_inventory_constraint]
            final_constraint = create_constraint_set(constraints)
            yield final_constraint

    @flexmethod
    def apply_posture_state_and_interaction_to_constraint(cls, inst, posture_state, *args, invalid_expected=False, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        result = super(SuperInteraction, inst_or_cls).apply_posture_state_and_interaction_to_constraint(posture_state, invalid_expected=True, *args, **kwargs)
        if not result.valid and not invalid_expected:
            logger.error('Failed to resolve {} with posture state {}.', inst_or_cls, posture_state, owner='maxr')
        return result

