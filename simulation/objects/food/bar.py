from carry import enter_carry_while_holding
from carry.carry_postures import CarryingObject
from crafting.crafting_interactions import CraftingPhaseSuperInteractionMixin, CraftingPhaseCreateObjectSuperInteraction
from element_utils import build_element
from interactions.aop import AffordanceObjectPair
from interactions.base.super_interaction import SuperInteraction
from interactions.constraints import Transform, Anywhere
from interactions.context import InteractionContext, QueueInsertStrategy
from sims4.collections import FrozenAttributeDict
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import TunableReference, Tunable
import carry
import services
import sims4.log
logger = sims4.log.Logger('Bar')

class ServeDrinkSuperInteraction(CraftingPhaseCreateObjectSuperInteraction):
    __qualname__ = 'ServeDrinkSuperInteraction'
    INSTANCE_TUNABLES = {'fill_drink_xevt_id': Tunable(int, 100, description='Xevt id of fill glass event.'), 'fill_drink_actor_name': Tunable(str, 'consumable', description='Name in Swing of the actor for the glass being filled object.')}

    @property
    def disable_carry_interaction_mask(self):
        return True

    def __init__(self, *args, order_sim=None, object_info=None, deliver_part=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_sim = order_sim
        self._object_info = object_info
        self._deliver_part = deliver_part

    def setup_asm_default(self, asm, *args, **kwargs):
        asm.set_actor(self.fill_drink_actor_name, self.created_target)
        return super().setup_asm_default(asm, *args, **kwargs)

    @property
    def _apply_state_xevt_id(self):
        return self.fill_drink_xevt_id

    def _custom_claim_callback(self):
        if self.phase.object_info_is_final_product:
            self.process.apply_quality_and_value(self.created_target)
            self.created_target.on_crafting_process_finished()

class ServeDrinkToCounterSuperInteraction(ServeDrinkSuperInteraction):
    __qualname__ = 'ServeDrinkToCounterSuperInteraction'
    INSTANCE_TUNABLES = {'put_down_drink_xevt_id': Tunable(int, 101, description='Xevt id of fill glass event.')}
    old_object = None
    put_down = False

    def _custom_content_sequence(self, sequence):

        def select_serve_slot(*_, **__):
            bar_or_part = self._deliver_part or self.target
            old_age = 0
            old_slot = None
            self.dest_slot = None
            for runtime_slot in bar_or_part.get_runtime_slots_gen():
                if runtime_slot.decorative:
                    pass
                if not runtime_slot.is_valid_for_placement(obj=self.created_target, objects_to_ignore=runtime_slot.children):
                    pass
                if runtime_slot.empty:
                    self.dest_slot = runtime_slot
                    break
                else:
                    drinks = runtime_slot.children
                    for drink in drinks:
                        while drink.objectage_component:
                            current_age = drink.get_current_age()
                            if current_age > old_age:
                                self.old_object = drink
                                old_age = current_age
                                old_slot = runtime_slot
            if self.dest_slot is None and self.old_object is not None:
                self.dest_slot = old_slot

                def destroy_old_object():
                    self.old_object.destroy(source=self, cause='Destroying an old drink to make room for a new one.')
                    self.old_object = None

                self.add_exit_function(destroy_old_object)
            if self.dest_slot is not None:
                return True
            logger.error('No non-deco slots found on {} that support {}.', bar_or_part, self.created_target, owner='maxr')
            return False

        return (select_serve_slot, sequence)

    def _custom_claim_callback(self):
        super()._custom_claim_callback()
        if self.put_down:
            return
        bar = self.target
        if bar.is_part:
            bar = bar.part_owner
        if self.dest_slot is not None:
            self.dest_slot.add_child(self.created_target)
        else:
            CarryingObject.snap_to_good_location_on_floor(self.created_target)
        self.put_down = True
        logger.debug('Push customer to pick up drink')

        def push_drink():
            self._push_drink_pick_up()

        self.add_exit_function(push_drink)

    def _build_sequence_with_callback(self, callback=None, sequence=()):
        self.animation_context.register_event_handler(callback, handler_id=self.put_down_drink_xevt_id)
        sequence = self._custom_content_sequence(sequence)
        return build_element(sequence)

    def _push_drink_pick_up(self):
        if self.order_sim is None:
            return
        if self.sim is self.order_sim and (self.process.orders or not self.should_push_consume(check_phase=False)):
            return
        drink_target = self.created_target
        context = InteractionContext(self.order_sim, self.source, self.priority, insert_strategy=QueueInsertStrategy.NEXT)
        affordance = drink_target.get_consume_affordance()
        self.order_sim.push_super_affordance(affordance, drink_target, context)

class ServeDrinkToSitDrinkSlotSuperInteraction(ServeDrinkToCounterSuperInteraction):
    __qualname__ = 'ServeDrinkToSitDrinkSlotSuperInteraction'

    def _custom_content_sequence(self, sequence):

        def select_serve_slot(*_, **__):
            bar_or_part = self._deliver_part or self.target
            for runtime_slot in bar_or_part.get_runtime_slots_gen():
                while runtime_slot.is_valid_for_placement(obj=self.created_target):
                    self.dest_slot = runtime_slot
                    break
            if self.dest_slot is not None:
                return True
            return False

        return (select_serve_slot, sequence)

class ServeDrinkToCustomerSuperInteraction(ServeDrinkSuperInteraction):
    __qualname__ = 'ServeDrinkToCustomerSuperInteraction'

    def setup_asm_default(self, asm, *args, **kwargs):
        result = super().setup_asm_default(asm, *args, **kwargs)
        if result:
            asm.set_parameter(carry.PARAM_CARRY_TRACK, self._object_info.carry_track.name.lower())
        return result

    @property
    def create_object_owner(self):
        return self.order_sim

    def _build_sequence_with_callback(self, callback=None, sequence=()):

        def create_si():
            drink_target = self.created_target
            target_affordance = drink_target.get_consume_affordance()
            context = InteractionContext(self.order_sim, self.source, self.priority, insert_strategy=QueueInsertStrategy.NEXT, group_id=self.group_id)
            context.carry_target = drink_target
            aop = AffordanceObjectPair(target_affordance, drink_target, target_affordance, None)
            return (aop, context)

        return enter_carry_while_holding(self, self.created_target, create_si_fn=create_si, callback=callback, carry_sim=self.order_sim, track=self.object_info.carry_track, sequence=sequence)

class ChooseDeliverySuperInteraction(CraftingPhaseSuperInteractionMixin, SuperInteraction):
    __qualname__ = 'ChooseDeliverySuperInteraction'
    INSTANCE_TUNABLES = {'delivery_to_bar_affordance': TunableReference(services.affordance_manager(), class_restrictions=ServeDrinkToCounterSuperInteraction, description="Affordance used to deliver a drink to a slot, if the order sim doesn't sit at the barstool slot to the bar."), 'delivery_to_sit_drink_slot_affordance': TunableReference(services.affordance_manager(), class_restrictions=ServeDrinkToSitDrinkSlotSuperInteraction, description='The affordance to delivery a drink to the sit_drink slot, if the order sim sits at the barstool slot to the bar.')}

    @property
    def auto_goto_next_phase(self):
        return False

    @classmethod
    def is_guaranteed(cls, *args, **kwargs):
        return True

    def _pick_affordance(self, order_sim, object_info, context):
        deliver_part = None
        carry_track = object_info.carry_track
        deliver_to_bar = self.delivery_to_bar_affordance
        deliver_to_sit_drink_slot = self.delivery_to_sit_drink_slot_affordance
        if self.sim == order_sim or order_sim is None:
            return (deliver_to_bar, self.target, deliver_part, carry_track)
        order_surface_target = order_sim.posture_state.surface_target
        if order_surface_target is not None and order_surface_target.is_part:
            bar = None
            if self.target.is_part:
                bar = self.target.part_owner
            if order_surface_target.part_owner is bar:
                if order_surface_target.is_valid_for_placement(definition=object_info.definition):
                    deliver_part = order_surface_target
                    return (deliver_to_sit_drink_slot, self.target, deliver_part, carry_track)
        return (deliver_to_bar, self.target, deliver_part, carry_track)

    def _run_interaction_gen(self, timeline):
        (order_sim, recipe) = self.process.pop_order()
        object_info = recipe.final_product
        context = self.context.clone_for_continuation(self)
        (deliver_affordance, target, deliver_part, carry_track) = self._pick_affordance(order_sim, object_info, context)
        obj_info_copy = FrozenAttributeDict(object_info, carry_track=carry_track)
        new_process = self.process.copy_for_serve_drink(recipe)
        aop = AffordanceObjectPair(deliver_affordance, target, deliver_affordance, None, order_sim=order_sim, object_info=obj_info_copy, deliver_part=deliver_part, phase=self.process.phase, crafting_process=new_process)
        self._went_to_next_phase_or_finished_crafting = True
        return aop.test_and_execute(context)

lock_instance_tunables(ChooseDeliverySuperInteraction, basic_content=None)
