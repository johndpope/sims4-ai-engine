import collections
import operator
from animation.posture_manifest import Hand
from carry.carry_postures import CarryingObject
from interactions.aop import AffordanceObjectPair
from interactions.liability import Liability
from objects.base_interactions import ProxyInteraction
from objects.components import componentmethod
from objects.components.types import CARRYABLE_COMPONENT
from placement import FGLSearchFlag
from sims4.tuning.tunable import TunableReference, TunableFactory, TunableVariant, OptionalTunable, TunableList, Tunable, TunableMapping
from sims4.utils import classproperty
from snippets import TunableAffordanceFilterSnippet
from strategy import TunablePutDownStrategy
import build_buy
import interactions
import objects.components
import placement
import services
import sims4.log
import sims4.resources
PUT_DOWN_TOKEN_LIABILITY = 'PutDownContinuationToken'
logger = sims4.log.Logger('CarryableComponent')

class PutDownContinuationToken(Liability):
    __qualname__ = 'PutDownContinuationToken'

    def __init__(self, interaction, parent):
        self._interaction = interaction
        self.aop = None
        self._parent = parent

    def release(self):
        target_object = self._interaction.target
        if target_object is None:
            return
        carry_component = target_object.get_component(CARRYABLE_COMPONENT)
        if carry_component is None:
            logger.error('Interaction ({0}) has a target ({1}) without a Carryable Component', self._interaction, self._interaction.target)
            return
        if target_object.parent is not self._parent:
            carry_component.reset_put_down_count()
            return
        if not carry_component.attempted_putdown or not carry_component.attempted_alternative_putdown or target_object.transient:
            new_context = self._interaction.context.clone_for_continuation(self._interaction)
            aop = target_object.get_put_down_aop(self._interaction, new_context)
            aop.test_and_execute(new_context)
            return
        if not CarryingObject.snap_to_good_location_on_floor(target_object):
            sim = self._interaction.sim
            if sim.household.id is not target_object.get_household_owner_id() or not sim.inventory_component.player_try_add_object(target_object):
                target_object.release_sim(sim)
                build_buy.move_object_to_household_inventory(target_object)

def _create_liability_and_token(interaction, sim):
    new_token = PutDownContinuationToken(interaction, sim)
    return (((PUT_DOWN_TOKEN_LIABILITY, new_token),), new_token)

def _add_putdown_liability_to_aop(aop, interaction, **kwargs):
    (liability_list, token) = _create_liability_and_token(interaction, interaction.context.sim)
    aop._liabilities = liability_list
    token.aop = aop

def _calculated_score(base_score, distance, attenuation):
    raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
    if distance == 0 or attenuation == 0:
        return base_score
    score = base_score*(1/distance*attenuation)
    return score

ScoredAOP = collections.namedtuple('ScoredAOP', ['score', 'aop'])

class CarryTargetInteraction(ProxyInteraction):
    __qualname__ = 'CarryTargetInteraction'
    INSTANCE_SUBCLASSES_ONLY = True

    @classproperty
    def proxy_name(cls):
        return '[CarryTarget]'

    @classmethod
    def generate(cls, proxied_affordance, carry_target):
        result = super().generate(proxied_affordance)
        result._carry_target_ref = carry_target.ref()
        return result

    @property
    def carry_target(self):
        if self._carry_target_ref is not None:
            return self._carry_target_ref()

class CarryableComponent(objects.components.Component, component_name=objects.components.types.CARRYABLE_COMPONENT):
    __qualname__ = 'CarryableComponent'
    DEFAULT_CARRY_AFFORDANCES = TunableList(TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), description='A list of default carry affordances.')
    PUT_IN_INVENTORY_AFFORDANCE = TunableReference(description='\n        The affordance used by carryable component to put objects in inventory.\n        ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION))
    PUT_DOWN_HERE_AFFORDANCE = TunableReference(description='\n        The affordance used by carryable component to put down here via the\n        PutDownContinuationToken liability.\n        ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION))
    PUT_DOWN_ANYWHERE_AFFORDANCE = TunableReference(description='\n        The affordance used by carryable component to put down objects anywhere\n        via the PutDownContinuationToken liability.\n        ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION))

    def __init__(self, owner, put_down_tuning, state_based_put_down_tuning, carry_affordances, provided_affordances, allowed_hands, holster_while_routing, holster_compatibility, unholster_on_long_route_only, prefer_owning_sim_inventory_when_not_on_home_lot, constraint_pick_up, visibility_override=None, display_name_override=None):
        super().__init__(owner)
        self.put_down_tuning = put_down_tuning
        self.state_based_put_down_tuning = state_based_put_down_tuning
        self.provided_affordances = provided_affordances
        self._attempted_putdown = False
        self._attempted_alternative_putdown = False
        self._carry_affordances = carry_affordances
        self.allowed_hands = allowed_hands
        self.holster_while_routing = holster_while_routing
        self.holster_compatibility = holster_compatibility
        self.unholster_on_long_route_only = unholster_on_long_route_only
        self.constraint_pick_up = constraint_pick_up
        self.prefer_owning_sim_inventory_when_not_on_home_lot = prefer_owning_sim_inventory_when_not_on_home_lot
        self._current_put_down_strategy = self.put_down_tuning

    @property
    def attempted_putdown(self):
        return self._attempted_putdown

    @property
    def attempted_alternative_putdown(self):
        return self._attempted_alternative_putdown

    @property
    def current_put_down_strategy(self):
        return self._current_put_down_strategy

    @property
    def ideal_slot_type_set(self):
        return self.current_put_down_strategy.ideal_slot_type_set

    @componentmethod
    def get_provided_affordances_gen(self):
        for affordance in self.provided_affordances:
            yield CarryTargetInteraction.generate(affordance, self.owner)

    def component_super_affordances_gen(self, **kwargs):
        if self._carry_affordances is None:
            affordances = self.DEFAULT_CARRY_AFFORDANCES
        else:
            affordances = self._carry_affordances
        for affordance in affordances:
            yield affordance

    def component_interactable_gen(self):
        yield self

    def on_state_changed(self, state, old_value, new_value):
        if new_value in self.state_based_put_down_tuning or old_value in self.state_based_put_down_tuning:
            self._generate_put_down_tuning()

    def _generate_put_down_tuning(self):
        for (state_value, put_down_strategy) in self.state_based_put_down_tuning.items():
            while self.owner.state_value_active(state_value):
                self._current_put_down_strategy = put_down_strategy
                break
        self._current_put_down_strategy = self.put_down_tuning

    @objects.components.componentmethod
    def get_put_down_aop(self, interaction, context, alternative_multiplier=1, own_inventory_multiplier=1, object_inventory_multiplier=1, in_slot_multiplier=1, on_floor_multiplier=1, visibility_override=None, display_name_override=None, additional_post_run_autonomy_commodities=None, add_putdown_liability=False, **kwargs):
        sim = interaction.sim
        owner = self.owner
        if not owner.transient:
            if not self.current_put_down_strategy.affordances:
                self._attempted_alternative_putdown = True
            if not self._attempted_alternative_putdown:
                self._attempted_alternative_putdown = True
                scored_aops = []
                for scored_aop in self._gen_affordance_score_and_aops(interaction, multiplier=alternative_multiplier):
                    while scored_aop.aop.test(context):
                        scored_aops.append(scored_aop)
                if scored_aops:
                    scored_aops.sort(key=operator.itemgetter(0))
                    return scored_aops[-1].aop
            affordance = CarryableComponent.PUT_DOWN_ANYWHERE_AFFORDANCE
            slot_types_and_costs = self._get_slot_types_and_costs(multiplier=in_slot_multiplier)
            terrain_transform = self._get_terrain_transform(interaction)
            objects = self._get_objects_with_inventory(interaction)
            objects = [obj for obj in objects if obj.inventory_component.allow_putdown_in_inventory]
            if self.current_put_down_strategy.floor_cost is not None and on_floor_multiplier is not None:
                world_cost = self.current_put_down_strategy.floor_cost*on_floor_multiplier
            else:
                world_cost = None
            if self.current_put_down_strategy.inventory_cost is not None and own_inventory_multiplier is not None:
                sim_inventory_cost = self.current_put_down_strategy.inventory_cost*own_inventory_multiplier
            else:
                sim_inventory_cost = None
            if self.current_put_down_strategy.object_inventory_cost is not None and object_inventory_multiplier is not None:
                object_inventory_cost = self.current_put_down_strategy.object_inventory_cost*object_inventory_multiplier
            else:
                object_inventory_cost = None
            aop = AffordanceObjectPair(affordance, self.owner, affordance, None, slot_types_and_costs=slot_types_and_costs, world_cost=world_cost, sim_inventory_cost=sim_inventory_cost, object_inventory_cost=object_inventory_cost, terrain_transform=terrain_transform, objects_with_inventory=objects, visibility_override=visibility_override, display_name_override=display_name_override, additional_post_run_autonomy_commodities=additional_post_run_autonomy_commodities, **kwargs)
            if add_putdown_liability:
                _add_putdown_liability_to_aop(aop, interaction)
            self._attempted_putdown = True
            return aop
        return self._get_destroy_aop(sim, **kwargs)

    def _gen_affordance_score_and_aops(self, interaction, multiplier=1, add_putdown_liability=False):
        for affordance in self.current_put_down_strategy.affordances:
            aop = AffordanceObjectPair(affordance, self.owner, affordance, None)
            if add_putdown_liability:
                _add_putdown_liability_to_aop(aop, interaction)
            yield ScoredAOP(multiplier, aop)

    def _get_cost_for_slot_type(self, slot_type):
        if slot_type in self.owner.ideal_slot_types:
            return self.current_put_down_strategy.preferred_slot_cost
        return self.current_put_down_strategy.normal_slot_cost

    def _get_slot_types_and_costs(self, multiplier=1):
        slot_types_and_costs = []
        for slot_type in self.owner.all_valid_slot_types:
            cost = self._get_cost_for_slot_type(slot_type)
            if cost is not None and multiplier is not None:
                cost *= multiplier
            else:
                cost = None
            slot_types_and_costs.append((slot_type, cost))
        return slot_types_and_costs

    def _get_terrain_transform(self, interaction):
        if self.owner.footprint_component is not None:
            sim = interaction.sim
            additional_put_down_distance = sim.posture_state.body.additional_put_down_distance
            starting_position = sim.position + sim.forward*(sim.object_radius + additional_put_down_distance)
            sim_los_constraint = sim.lineofsight_component.constraint
            if not sims4.geometry.test_point_in_compound_polygon(starting_position, sim_los_constraint.geometry.polygon):
                starting_position = sim.position
            search_flags = FGLSearchFlag.STAY_IN_CURRENT_BLOCK | FGLSearchFlag.SHOULD_TEST_ROUTING | FGLSearchFlag.CALCULATE_RESULT_TERRAIN_HEIGHTS | FGLSearchFlag.DONE_ON_MAX_RESULTS | FGLSearchFlag.SHOULD_TEST_BUILDBUY
            MAX_PUTDOWN_STEPS = 8
            MAX_PUTDOWN_DISTANCE = 10
            (position, orientation) = placement.find_good_location(placement.FindGoodLocationContext(starting_position=starting_position, starting_orientation=sim.orientation, starting_routing_surface=sim.routing_surface, object_footprints=(self.owner.get_footprint(),), object_id=self.owner.id, max_steps=MAX_PUTDOWN_STEPS, max_distance=MAX_PUTDOWN_DISTANCE, search_flags=search_flags))
            if position is not None:
                put_down_transform = sims4.math.Transform(position, orientation)
                return put_down_transform

    def _get_objects_with_inventory(self, interaction):
        objects = []
        inventory_item = self.owner.inventoryitem_component
        if inventory_item is not None and CarryableComponent.PUT_IN_INVENTORY_AFFORDANCE is not None:
            while True:
                for obj in inventory_item.valid_object_inventory_gen():
                    objects.append(obj)
        return objects

    def _get_destroy_aop(self, sim, **kwargs):
        affordance = CarryableComponent.PUT_DOWN_HERE_AFFORDANCE
        return AffordanceObjectPair(affordance, self.owner, affordance, None, put_down_transform=None, **kwargs)

    def reset_put_down_count(self):
        self._attempted_alternative_putdown = False
        self._attempted_putdown = False

class TunableCarryableComponent(TunableFactory):
    __qualname__ = 'TunableCarryableComponent'
    FACTORY_TYPE = CarryableComponent

    def __init__(self, description='Holds information about carrying and putting down an object.', **kwargs):
        super().__init__(put_down_tuning=TunableVariant(reference=TunableReference(description='\n                    Tuning for how to score where a Sim might want to set an\n                    object down.\n                    ', manager=services.get_instance_manager(sims4.resources.Types.STRATEGY)), literal=TunablePutDownStrategy().TunableFactory(), default='literal'), state_based_put_down_tuning=TunableMapping(description='\n                A mapping from a state value to a putdownstrategy. If the\n                owning object is in any of the states tuned here, it will use\n                that state\'s associated putdownstrategy in place of the one\n                putdownstrategy tuned in the "put_down_tuning" field. If the\n                object is in multiple states listed in this mapping, the\n                behavior is undefined.\n                ', key_type=TunableReference(description='\n                    The state value this object must be in in order to use the\n                    associated putdownstrategy.\n                    ', manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE)), value_type=TunableVariant(reference=TunableReference(description='\n                        Tuning for how to score where a Sim might want to set\n                        an object down.\n                        ', manager=services.get_instance_manager(sims4.resources.Types.STRATEGY)), literal=TunablePutDownStrategy().TunableFactory()), key_name='State', value_name='PutDownStrategy'), carry_affordances=OptionalTunable(TunableList(TunableReference(description='\n                    The versions of the HoldObject affordance that this object\n                    supports.\n                    ', manager=services.affordance_manager())), disabled_name='use_default_affordances', enabled_name='use_custom_affordances'), provided_affordances=TunableList(description='\n                A list of affordances that are generated when a Sim holding\n                this object selects another Sim to interact with. The generated\n                interactions will target the selected Sim but will have this\n                object set as their carry target.\n                ', tunable=TunableReference(manager=services.affordance_manager())), constraint_pick_up=OptionalTunable(description='\n                A list of constraints that must be fulfilled in order to\n                interact with this object.\n                ', tunable=TunableList(tunable=interactions.constraints.TunableConstraintVariant(description='\n                        A constraint that must be fulfilled in order to\n                        interact with this object.\n                        '))), allowed_hands=TunableVariant(locked_args={'both': (Hand.LEFT, Hand.RIGHT), 'left_only': (Hand.LEFT,), 'right_only': (Hand.RIGHT,)}, default='both'), holster_while_routing=Tunable(description='\n                If True, the Sim will holster the object before routing and\n                unholster when the route is complete.\n                ', tunable_type=bool, default=False), holster_compatibility=TunableAffordanceFilterSnippet(description='\n                Define interactions for which holstering this object is\n                explicitly disallowed.\n                \n                e.g. The Scythe is tuned to be holster-incompatible with\n                sitting, meaning that Sims will holster the Sctyhe when sitting.\n                '), unholster_on_long_route_only=Tunable(description='\n                If True, then the Sim will not unholster this object (assuming\n                it was previously holstered) unless a transition involving a\n                long route is about to happen.\n                \n                If False, then the standard holstering rules apply.\n                ', tunable_type=bool, default=False), prefer_owning_sim_inventory_when_not_on_home_lot=Tunable(description="\n                If checked, this object will highly prefer to be put into the\n                owning Sim's inventory when being put down by the owning Sim on\n                a lot other than their home lot.\n                \n                Certain objects, like consumables, should be exempt from this.\n                ", tunable_type=bool, default=True), description=description, **kwargs)

