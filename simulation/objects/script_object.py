import itertools
from carry.carry_postures import CarryingObject
from crafting.crafting_tunable import CraftingTuning
from distributor.rollback import ProtocolBufferRollback
from interactions.utils.animation import TunableAnimationObjectOverrides, AnimationOverrides, TunableAnimationOverrides
from interactions.utils.routing import RouteTargetType
from interactions.utils.sim_focus import FocusInterestLevel
from objects import slots
from objects.base_object import BaseObject, ResetReason
from objects.collection_manager import CollectableComponent
from objects.components import forward_to_components_gen, forward_to_components, get_component_priority_and_name_using_persist_id
from objects.components.affordance_tuning import AffordanceTuningComponent
from objects.components.autonomy import TunableAutonomyComponent
from objects.components.canvas_component import CanvasComponent
from objects.components.carryable_component import TunableCarryableComponent
from objects.components.censor_grid_component import TunableCensorGridComponent
from objects.components.consumable_component import ConsumableComponent
from objects.components.crafting_station_component import CraftingStationComponent
from objects.components.fishing_location_component import FishingLocationComponent
from objects.components.flowing_puddle_component import FlowingPuddleComponent
from objects.components.footprint_component import HasFootprintComponent
from objects.components.game_component import TunableGameComponent
from objects.components.gardening_components import TunableGardeningComponent
from objects.components.idle_component import IdleComponent
from objects.components.inventory import ObjectInventoryComponent
from objects.components.inventory_item import InventoryItemComponent, ItemLocation
from objects.components.lighting_component import LightingComponent
from objects.components.line_of_sight_component import TunableLineOfSightComponent
from objects.components.live_drag_target_component import LiveDragTargetComponent
from objects.components.name_component import NameComponent
from objects.components.object_age import TunableObjectAgeComponent
from objects.components.object_relationship_component import ObjectRelationshipComponent
from objects.components.object_teleportation_component import ObjectTeleportationComponent
from objects.components.ownable_component import OwnableComponent
from objects.components.proximity_component import ProximityComponent
from objects.components.slot_component import SlotComponent
from objects.components.spawner_component import SpawnerComponent
from objects.components.state import TunableStateComponent
from objects.components.statistic_component import HasStatisticComponent
from objects.components.time_of_day_component import TimeOfDayComponent
from objects.components.tooltip_component import TooltipComponent
from objects.components.video import TunableVideoComponent
from objects.components.welcome_component import WelcomeComponent
from objects.persistence_groups import PersistenceGroups
from objects.slots import SlotType
from protocolbuffers import SimObjectAttributes_pb2 as protocols
from protocolbuffers.FileSerialization_pb2 import ObjectData
from sims4.callback_utils import CallableList
from sims4.math import MAX_FLOAT
from sims4.tuning.geometric import TunableVector2
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableList, TunableReference, TunableTuple, OptionalTunable, Tunable, TunableEnumEntry, TunableMapping
from sims4.tuning.tunable_base import GroupNames, FilterTag
from sims4.utils import flexmethod, flexproperty, classproperty
from singletons import EMPTY_SET
from statistics.mood import TunableEnvironmentScoreModifiers
import caches
import distributor.fields
import objects.components.types
import objects.persistence_groups
import paths
import postures
import protocolbuffers.FileSerialization_pb2 as file_serialization
import routing
import services
import sims4.log
logger = sims4.log.Logger('Objects')

class ScriptObject(BaseObject, HasStatisticComponent, HasFootprintComponent, metaclass=HashedTunedInstanceMetaclass, manager=services.definition_manager()):
    __qualname__ = 'ScriptObject'
    INSTANCE_TUNABLES = {'_super_affordances': TunableList(description='\n            Super affordances on this object.\n            ', tunable=TunableReference(description='\n                A super affordance on this object.\n                ', manager=services.affordance_manager(), class_restrictions=('SuperInteraction',), pack_safe=True)), '_part_data': TunableList(description='\n            Use this to define parts for an object. Parts allow multiple Sims to\n            use an object in different or same ways, at the same time. The model\n            and the animations for this object will have to support parts.\n            Ensure this is the case with animation and modeling.\n           \n            There will be one entry in this list for every part the object has.\n           \n            e.g. The bed has six parts (two sleep parts, and four sit parts).\n              add two entries for the sleep parts add four entries for the sit\n              parts\n            ', tunable=TunableTuple(description='\n                Data that is specific to this part.\n                ', part_definition=TunableReference(description='\n                    The part definition data.\n                    ', manager=services.object_part_manager()), subroot_index=OptionalTunable(description='\n                    If enabled, this part will have a subroot index associated\n                    with it. This will affect the way Sims animate, i.e. they\n                    will animate relative to the position of the part, not\n                    relative to the object.\n                    ', tunable=Tunable(description='\n                        The subroot index/suffix associated to this part.\n                        ', tunable_type=int, default=0, needs_tuning=False), enabled_by_default=True), overlapping_parts=TunableList(description="\n                    The indices of parts that are unusable when this part is in\n                    use. The index is the zero-based position of the part within\n                    the object's Part Data list.\n                    ", tunable=int), adjacent_parts=OptionalTunable(description='\n                    Define adjacent parts. If disabled, adjacent parts will be\n                    generated automatically based on indexing. If enabled,\n                    adjacent parts must be specified here.\n                    ', tunable=TunableList(description="\n                        The indices of parts that are adjacent to this part. The\n                        index is the zero-based position of the part within the\n                        object's Part Data list.\n                        \n                        An empty list indicates that no part is ajdacent to this\n                        part.\n                        ", tunable=int)), is_mirrored=OptionalTunable(description='\n                    Specify whether or not solo animations played on this part\n                    should be mirrored or not.\n                    ', tunable=Tunable(description='\n                        If checked, mirroring is enabled. If unchecked,\n                        mirroring is disabled.\n                        ', tunable_type=bool, default=False)), forward_direction_for_picking=TunableVector2(description="\n                    When you click on the object this part belongs to, this\n                    offset will be applied to this part when determining which\n                    part is closest to where you clicked. By default, the\n                    object's forward vector will be used. It should only be\n                    necessary to tune this value if multiple parts overlap at\n                    the same location (e.g. the single bed).\n                    ", default=sims4.math.Vector2(0, 1), x_axis_name='x', y_axis_name='z'), disable_sim_aop_forwarding=Tunable(description='\n                    If checked, Sims using this specific part will never forward\n                    AOPs.\n                    ', tunable_type=bool, default=False), disable_child_aop_forwarding=Tunable(description='\n                    If checked, objects parented to this specific part will\n                    never forward AOPs.\n                    ', tunable_type=bool, default=False), anim_overrides=TunableAnimationOverrides(description='Animation overrides for this part.'))), 'custom_posture_target_name': Tunable(description='\n            An additional non-virtual actor to set for this object when used as\n            a posture target.\n            \n            This tunable is used when the object has parts. In most cases, the\n            state machines will only have one actor for the part that is\n            involved in animation. In that case, this field should not be set.\n            \n            e.g. The Sit posture requires the sitTemplate actor to be set, but\n            does not make a distinction between, for instance, Chairs and Sofas,\n            because no animation ever involves the whole object.\n            \n            However, there may be cases when, although we are dealing with\n            parts, the animation will need to also reference the entire object.\n            In that case, the ASM will have an extra actor to account for the\n            whole object, in addition to the part. Set this field to be that\n            actor name.\n            \n            e.g. The Sleep posture on the bed animates the Sim on one part.\n            However, the sheets and pillows need to animate on the entire bed.\n            In that case, we need to set this field on Bed so that the state\n            machine can have this actor set.\n            ', tunable_type=str, default=None), 'posture_transition_target_tag': TunableEnumEntry(description='\n            A tag to apply to this script object so that it is taken into\n            account for posture transition preference scoring.  For example, you\n            could tune this object (and others) to be a DINING_SURFACE.  Any SI\n            that is set up to have posture preference scoring can override the\n            score for any objects that are tagged with DINING_SURFACE.\n            \n            For a more detailed description of how posture preference scoring\n            works, see the posture_target_preference tunable field description\n            in SuperInteraction.\n            ', tunable_type=postures.PostureTransitionTargetPreferenceTag, default=postures.PostureTransitionTargetPreferenceTag.INVALID), '_anim_overrides': OptionalTunable(description='\n            If enabled, specify animation overrides for this object.\n            ', tunable=TunableAnimationObjectOverrides()), '_focus_score': TunableEnumEntry(description='\n            Determines how likely a Sim is to look at this object when focusing\n            ambiently.  A higher value means this object is more likely to draw\n            Sim focus.\n            ', tunable_type=FocusInterestLevel, default=FocusInterestLevel.LOW, needs_tuning=True), 'social_clustering': OptionalTunable(description='\n            If enabled, specify how this objects affects clustering for\n            preferred locations for socialization.\n            ', tunable=TunableTuple(is_datapoint=Tunable(description='\n                     Whether or not this object is a data point for social\n                     clusters.\n                     ', tunable_type=bool, default=True))), '_should_search_forwarded_sim_aop': Tunable(description="\n            If enabled, interactions on Sims using this object will appear in\n            this object's pie menu as long as they are also tuned to allow\n            forwarding.\n            ", tunable_type=bool, default=False), '_should_search_forwarded_child_aop': Tunable(description="\n            If enabled, interactions on children of this object will appear in\n            this object's pie menu as long as they are also tuned to allow\n            forwarding.\n            ", tunable_type=bool, default=False), '_disable_child_footprint_and_shadow': Tunable(description="\n            If checked, all objects parented to this object will have their\n            footprints and dropshadows disabled.\n            \n            Example Use: object_sim has this checked so when a Sim picks up a\n            plate of food, the plate's footprint and dropshadow turn off\n            temporarily.\n            ", tunable_type=bool, default=False), 'disable_los_reference_point': Tunable(description='\n            If checked, goal points for this interaction will not be discarded\n            if a ray-test from the object fails to connect without intersecting\n            walls or other objects.  The reason for allowing this, is for\n            objects like the door where we want to allow the sim to interact\n            with the object, but since the object doesnt have a footprint we\n            want to allow him to use the central point as a reference point and\n            not fail the LOS test.\n            ', tunable_type=bool, default=False), '_components': TunableTuple(description='\n            The components that instances of this object should have.\n            ', tuning_group=GroupNames.COMPONENTS, affordance_tuning=OptionalTunable(AffordanceTuningComponent.TunableFactory()), autonomy=OptionalTunable(TunableAutonomyComponent()), canvas=OptionalTunable(CanvasComponent.TunableFactory()), carryable=OptionalTunable(TunableCarryableComponent()), censor_grid=OptionalTunable(TunableCensorGridComponent()), collectable=OptionalTunable(CollectableComponent.TunableFactory()), consumable=OptionalTunable(ConsumableComponent.TunableFactory()), crafting_station=OptionalTunable(CraftingStationComponent.TunableFactory()), fishing_location=OptionalTunable(FishingLocationComponent.TunableFactory()), flowing_puddle=OptionalTunable(FlowingPuddleComponent.TunableFactory()), game=OptionalTunable(TunableGameComponent()), gardening_component=TunableGardeningComponent(), idle_component=OptionalTunable(IdleComponent.TunableFactory()), inventory=OptionalTunable(ObjectInventoryComponent.TunableFactory()), inventory_item=OptionalTunable(InventoryItemComponent.TunableFactory()), lighting=OptionalTunable(LightingComponent.TunableFactory()), line_of_sight=OptionalTunable(TunableLineOfSightComponent()), live_drag_target=OptionalTunable(LiveDragTargetComponent.TunableFactory()), name=OptionalTunable(NameComponent.TunableFactory()), object_age=OptionalTunable(TunableObjectAgeComponent()), object_relationships=OptionalTunable(ObjectRelationshipComponent.TunableFactory()), object_teleportation=OptionalTunable(ObjectTeleportationComponent.TunableFactory()), ownable_component=OptionalTunable(OwnableComponent.TunableFactory()), proximity_component=OptionalTunable(ProximityComponent.TunableFactory()), spawner_component=OptionalTunable(SpawnerComponent.TunableFactory()), state=OptionalTunable(TunableStateComponent()), time_of_day_component=OptionalTunable(TimeOfDayComponent.TunableFactory()), tooltip_component=OptionalTunable(TooltipComponent.TunableFactory()), video=OptionalTunable(TunableVideoComponent()), welcome_component=OptionalTunable(WelcomeComponent.TunableFactory())), '_components_native': TunableTuple(description='\n            Tuning for native components, those that an object will have even\n            if not tuned.\n            ', tuning_group=GroupNames.COMPONENTS, Slot=OptionalTunable(SlotComponent.TunableFactory())), '_persists': Tunable(description='\n            Whether object should persist or not.\n            ', tunable_type=bool, default=True, tuning_filter=FilterTag.EXPERT_MODE), '_world_file_object_persists': Tunable(description="\n            If object is from world file, check this if object state should\n            persist. \n            Example:\n                If grill is dirty, but this is unchecked and it won't stay\n                dirty when reloading the street. \n                If Magic tree has this checked, all object relationship data\n                will be saved.\n            ", tunable_type=bool, default=False, tuning_filter=FilterTag.EXPERT_MODE), '_object_state_remaps': TunableList(description='\n            If this object is part of a Medator object suite, this list\n            specifies which object tuning file to use for each catalog object\n            state.\n            ', tunable=TunableReference(description='\n                Current object state.\n                ', manager=services.definition_manager(), tuning_filter=FilterTag.EXPERT_MODE)), 'environment_score_trait_modifiers': TunableMapping(description='\n            Each trait can put modifiers on any number of moods as well as the\n            negative environment scoring.\n            \n            If tuning becomes a burden, consider making prototypes for many\n            objects and tuning the prototype.\n            \n            Example: A Sim with the Geeky trait could have a modifier for the\n            excited mood on objects like computers and tablets.\n            \n            Example: A Sim with the Loves Children trait would have a modifier\n            for the happy mood on toy objects.\n            \n            Example: A Sim that has the Hates Art trait could get an Angry\n            modifier, and should set modifiers like Happy to multiply by 0.\n            ', key_type=TunableReference(description='\n                The Trait that the Sim must have to enable this modifier.\n                ', manager=services.get_instance_manager(sims4.resources.Types.TRAIT)), value_type=TunableEnvironmentScoreModifiers.TunableFactory(description='\n                The Environmental Score modifiers for a particular trait.\n                '), key_name='trait', value_name='modifiers'), 'slot_cost_modifiers': TunableMapping(description="\n            A mapping of slot types to modifier values.  When determining slot\n            scores in the transition sequence, if the owning object of a slot\n            has a modifier for its type specified here, that slot will have the\n            modifier value added to its cost.  A positive modifier adds to the\n            cost of a path using this slot and means that a slot will be less\n            likely to be chosen.  A negative modifier subtracts from the cost\n            of a path using this slot and means that a slot will be more likely\n            to be chosen.\n            \n            ex: Both bookcases and toilets have deco slots on them, but you'd\n            rather a Sim prefer to put down an object in a bookcase than on the\n            back of a toilet.\n            ", key_type=SlotType.TunableReference(description='\n                A reference to the type of slot to be given a score modifier\n                when considered for this object.\n                '), value_type=Tunable(description='\n                A tunable float specifying the score modifier for the\n                corresponding slot type on this object.\n                ', tunable_type=float, default=0)), 'fire_retardant': Tunable(description='\n            If an object is fire retardant then not only will it not burn, but\n            it also cannot overlap with fire, so fire will not spread into an\n            area occupied by a fire retardant object.\n            ', tunable_type=bool, default=False)}
    _commodity_flags = None
    additional_interaction_constraints = None

    def __init__(self, definition, **kwargs):
        super().__init__(definition, tuned_native_components=self._components_native, **kwargs)
        self._dynamic_commodity_flags_map = dict()
        for component_factory in self._components.values():
            while component_factory is not None:
                self.add_component(component_factory(self))
        self.item_location = ItemLocation.INVALID_LOCATION
        if self._persists:
            self._persistence_group = PersistenceGroups.OBJECT
        else:
            self._persistence_group = PersistenceGroups.NONE
        self._registered_transition_controllers = set()
        if self.definition.negative_environment_score != 0 or (self.definition.positive_environment_score != 0 or self.definition.environment_score_mood_tags) or self.environment_score_trait_modifiers:
            self.add_dynamic_component(objects.components.types.ENVIRONMENT_SCORE_COMPONENT.instance_attr)

    def on_reset_early_detachment(self, reset_reason):
        super().on_reset_early_detachment(reset_reason)
        for transition_controller in self._registered_transition_controllers:
            transition_controller.on_reset_early_detachment(self, reset_reason)

    def on_reset_get_interdependent_reset_records(self, reset_reason, reset_records):
        super().on_reset_get_interdependent_reset_records(reset_reason, reset_records)
        for transition_controller in self._registered_transition_controllers:
            transition_controller.on_reset_add_interdependent_reset_records(self, reset_reason, reset_records)

    def on_reset_internal_state(self, reset_reason):
        if reset_reason == ResetReason.BEING_DESTROYED:
            self._registered_transition_controllers.clear()
        else:
            if not (self.parent is not None and self.parent.is_sim and self.parent.posture_state.is_carrying(self)):
                if not CarryingObject.snap_to_good_location_on_floor(self, self.parent.transform, self.parent.routing_surface):
                    self.clear_parent(self.parent.transform, self.parent.routing_surface)
            self.location = self.location
        super().on_reset_internal_state(reset_reason)

    def register_transition_controller(self, controller):
        self._registered_transition_controllers.add(controller)

    def unregister_transition_controller(self, controller):
        self._registered_transition_controllers.discard(controller)

    @classmethod
    def _verify_tuning_callback(cls):
        for (i, part_data) in enumerate(cls._part_data):
            while part_data.forward_direction_for_picking.magnitude() != 1.0:
                logger.warn('On {}, forward_direction_for_picking is {} on part {}, which is not a normalized vector.', cls, part_data.forward_direction_for_picking, i, owner='bhill')
        for sa in cls._super_affordances:
            if sa.allow_user_directed and not sa.display_name:
                logger.error('Interaction {} on {} does not have a valid display name.', sa.__name__, cls.__name__)
            while sa.consumes_object() or sa.contains_stat(CraftingTuning.CONSUME_STATISTIC):
                logger.error('ScriptObject: Interaction {} on {} is consume affordance, should tune on ConsumableComponent of the object.', sa.__name__, cls.__name__, owner='tastle/cjiang')

    @flexmethod
    def update_commodity_flags(cls, inst):
        commodity_flags = set()
        inst_or_cls = inst if inst is not None else cls
        for sa in inst_or_cls.super_affordances():
            commodity_flags |= sa.commodity_flags
        if commodity_flags:
            cls._commodity_flags = frozenset(commodity_flags)
        else:
            cls._commodity_flags = EMPTY_SET

    @flexproperty
    def commodity_flags(cls, inst):
        if cls._commodity_flags is None:
            if inst is not None:
                inst.update_commodity_flags()
            else:
                cls.update_commodity_flags()
        if inst is not None:
            dynamic_commodity_flags = set()
            for dynamic_commodity_flags_entry in inst._dynamic_commodity_flags_map.values():
                dynamic_commodity_flags.update(dynamic_commodity_flags_entry)
            return frozenset(cls._commodity_flags | dynamic_commodity_flags)
        return cls._commodity_flags

    def add_dynamic_commodity_flags(self, key, commodity_flags):
        self._dynamic_commodity_flags_map[key] = commodity_flags

    def remove_dynamic_commodity_flags(self, key):
        if key in self._dynamic_commodity_flags_map:
            del self._dynamic_commodity_flags_map[key]

    @classproperty
    def tuned_components(cls):
        return cls._components

    @flexproperty
    def allowed_hands(cls, inst):
        if inst is not None:
            carryable = inst.carryable_component
            if carryable is not None:
                return carryable.allowed_hands
            return ()
        carryable_tuning = cls._components.carryable
        if carryable_tuning is not None:
            return carryable_tuning.allowed_hands
        return ()

    @flexproperty
    def holster_while_routing(cls, inst):
        if inst is not None:
            carryable = inst.carryable_component
            if carryable is not None:
                return carryable.holster_while_routing
            return False
        carryable_tuning = cls._components.carryable
        if carryable_tuning is not None:
            return carryable_tuning.holster_while_routing
        return False

    def is_surface(self, *args, **kwargs):
        return False

    @classproperty
    def _anim_overrides_cls(cls):
        if cls._anim_overrides is not None:
            return cls._anim_overrides(None)

    @property
    def object_routing_surface(self):
        pass

    @property
    def _anim_overrides_internal(self):
        params = {'isParented': self.parent is not None, 'heightAboveFloor': slots.get_surface_height_parameter_for_object(self)}
        if self.is_part:
            params['subroot'] = self.part_suffix
            params['isMirroredPart'] = True if self.is_mirrored() else False
        overrides = AnimationOverrides(params=params)
        for component_overrides in self.component_anim_overrides_gen():
            overrides = overrides(component_overrides())
        if self._anim_overrides is not None:
            return overrides(self._anim_overrides())
        return overrides

    @forward_to_components_gen
    def component_anim_overrides_gen(self):
        pass

    @property
    def parent(self):
        pass

    def ancestry_gen(self):
        obj = self
        while obj is not None:
            yield obj
            if obj.is_part:
                obj = obj.part_owner
            else:
                obj = obj.parent

    @property
    def parent_slot(self):
        pass

    def get_closest_parts_to_position(self, position, posture=None, posture_spec=None):
        best_parts = set()
        best_distance = MAX_FLOAT
        if position is not None and self.parts is not None:
            while True:
                for part in self.parts:
                    while (posture is None or part.supports_posture_type(posture)) and (posture_spec is None or part.supports_posture_spec(posture_spec)):
                        dist = (part.position_with_forward_offset - position).magnitude_2d_squared()
                        if dist < best_distance:
                            best_parts.clear()
                            best_parts.add(part)
                            best_distance = dist
                        elif dist == best_distance:
                            best_parts.add(part)
        return best_parts

    def num_valid_parts(self, posture):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        if self.parts is not None:
            return sum(part.supports_posture_type(posture.posture_type) for part in self.parts)
        return 0

    def is_same_object_or_part(self, obj):
        if not isinstance(obj, ScriptObject):
            return False
        if obj is self:
            return True
        if obj.is_part and obj.part_owner is self or self.is_part and self.part_owner is obj:
            return True
        return False

    def is_same_object_or_part_of_same_object(self, obj):
        if not isinstance(obj, ScriptObject):
            return False
        if self.is_same_object_or_part(obj):
            return True
        if self.is_part and obj.is_part and self.part_owner is obj.part_owner:
            return True
        return False

    def get_compatible_parts(self, posture, interaction=None):
        if posture is not None and posture.target is not None and posture.target.is_part:
            return (posture.target,)
        return self.get_parts_for_posture(posture, interaction)

    def get_parts_for_posture(self, posture, interaction=None):
        if self.parts is not None:
            return (part for part in self.parts if part.supports_posture_type(posture.posture_type, interaction))
        return ()

    def get_parts_for_affordance(self, affordance):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        if self.parts is not None and affordance is not None:
            return (part for part in self.parts if part.supports_affordance(affordance))
        return ()

    def may_reserve(self, *args, **kwargs):
        return True

    def reserve(self, *args, **kwargs):
        pass

    def release(self, *args, **kwargs):
        pass

    @property
    def build_buy_lockout(self):
        return False

    @property
    def route_target(self):
        return (RouteTargetType.NONE, None)

    @flexmethod
    def super_affordances(cls, inst, context=None):
        from objects.base_interactions import BaseInteractionTuning
        inst_or_cls = inst if inst is not None else cls
        component_affordances_gen = inst.component_super_affordances_gen() if inst is not None else EMPTY_SET
        super_affordances = itertools.chain(inst_or_cls._super_affordances, BaseInteractionTuning.GLOBAL_AFFORDANCES, component_affordances_gen)
        super_affordances = list(super_affordances)
        shift_held = False
        if context is not None:
            shift_held = context.shift_held
        for sa in super_affordances:
            if shift_held:
                if sa.cheat:
                    yield sa
                elif sa.debug and __debug__:
                    yield sa
                elif sa.automation and paths.AUTOMATION_MODE:
                    yield sa
                    while not sa.debug and not sa.cheat:
                        yield sa
            else:
                while not sa.debug and not sa.cheat:
                    yield sa

    @forward_to_components_gen
    def component_super_affordances_gen(self):
        pass

    @caches.cached_generator
    def posture_interaction_gen(self):
        for affordance in self._super_affordances:
            while not affordance.debug:
                if affordance._provided_posture_type is not None:
                    while True:
                        for aop in affordance.potential_interactions(self, None):
                            yield aop

    def supports_affordance(self, affordance):
        return True

    def potential_interactions(self, context, get_interaction_parameters=None, allow_forwarding=True, **kwargs):
        try:
            for affordance in self.super_affordances(context):
                if not self.supports_affordance(affordance):
                    pass
                if get_interaction_parameters is not None:
                    interaction_parameters = get_interaction_parameters(affordance, kwargs)
                else:
                    interaction_parameters = kwargs
                for aop in affordance.potential_interactions(self, context, **interaction_parameters):
                    yield aop
            for aop in self.potential_component_interactions(context):
                yield aop
            while allow_forwarding and (self._should_search_forwarded_sim_aop or self._should_search_forwarded_child_aop):
                for aop in self._search_forwarded_interactions(context, self._should_search_forwarded_sim_aop, self._should_search_forwarded_child_aop, get_interaction_parameters=get_interaction_parameters, **kwargs):
                    yield aop
        except Exception:
            logger.exception('Exception while generating potential interactions for {}:', self)

    def supports_posture_type(self, posture_type):
        for super_affordance in self._super_affordances:
            while super_affordance.provided_posture_type == posture_type:
                return True
        return False

    def _search_forwarded_interactions(self, context, search_sim_aops, search_child_aops, **kwargs):
        if search_sim_aops:
            for part_or_object in (self,) if not self.parts else self.parts:
                user_list = part_or_object.get_users(sims_only=True)
                for user in user_list:
                    if part_or_object.is_part and part_or_object.disable_child_aop_forwarding:
                        pass
                    for aop in user.potential_interactions(context, **kwargs):
                        while aop.affordance.allow_forward:
                            yield aop
        if not search_child_aops:
            return
        for child in self.children:
            if child.parent.is_part and child.parent.disable_child_aop_forwarding:
                pass
            for aop in child.potential_interactions(context, **kwargs):
                while aop.affordance.allow_forward:
                    yield aop

    def add_dynamic_component(self, *args, **kwargs):
        result = super().add_dynamic_component(*args, **kwargs)
        if result:
            self.resend_interactable()
        return result

    @distributor.fields.Field(op=distributor.ops.SetInteractable, default=False)
    def interactable(self):
        if self.build_buy_lockout:
            return False
        if self._super_affordances:
            return True
        for _ in self.component_interactable_gen():
            pass
        return False

    resend_interactable = interactable.get_resend()

    @forward_to_components_gen
    def component_interactable_gen(self):
        pass

    @caches.cached(maxsize=20)
    def check_line_of_sight(self, transform, verbose=False):
        top_level_parent = self
        while top_level_parent.parent is not None:
            top_level_parent = top_level_parent.parent
        if top_level_parent.wall_or_fence_placement:
            if verbose:
                return (routing.RAYCAST_HIT_TYPE_NONE, None)
            return (True, None)
        if self.is_in_inventory():
            if verbose:
                return (routing.RAYCAST_HIT_TYPE_NONE, None)
            return (True, None)
        slot_routing_location = self.get_routing_location_for_transform(transform)
        if verbose:
            ray_test = routing.ray_test_verbose
        else:
            ray_test = routing.ray_test
        return ray_test(slot_routing_location, self.routing_location, self.raycast_context(), return_object_id=True)

    clear_check_line_of_sight_cache = check_line_of_sight.cache.clear

    def _create_raycast_context(self, *args, **kwargs):
        super()._create_raycast_context(*args, **kwargs)
        if not self.is_sim:
            self.clear_check_line_of_sight_cache()

    @property
    def connectivity_handles(self):
        routing_context = self.get_or_create_routing_context()
        return routing_context.connectivity_handles

    def _clear_connectivity_handles(self):
        if self._routing_context is not None:
            self._routing_context.connectivity_handles.clear()

    @property
    def focus_bone(self):
        return 0

    @forward_to_components
    def on_state_changed(self, state, old_value, new_value):
        pass

    @forward_to_components
    def on_post_load(self):
        pass

    @forward_to_components
    def on_finalize_load(self):
        pass

    @property
    def attributes(self):
        pass

    @property
    def flammable(self):
        return False

    @attributes.setter
    def attributes(self, value):
        logger.debug('PERSISTENCE: Attributes property on {0} were set', self)
        try:
            object_data = ObjectData()
            object_data.ParseFromString(value)
            self.load_object(object_data)
        except:
            logger.exception('Exception applying attributes to object {0}', self)

    def load_object(self, object_data):
        save_data = protocols.PersistenceMaster()
        save_data.ParseFromString(object_data.attributes)
        self.load(save_data)
        self.on_post_load()

    def is_persistable(self):
        if self.persistence_group == objects.persistence_groups.PersistenceGroups.OBJECT:
            return True
        if self.item_location == ItemLocation.FROM_WORLD_FILE:
            return self._world_file_object_persists
        if self.item_location == ItemLocation.ON_LOT or self.item_location == ItemLocation.FROM_OPEN_STREET:
            return self._persists
        if self.persistence_group == objects.persistence_groups.PersistenceGroups.IN_OPEN_STREET and self.item_location == ItemLocation.INVALID_LOCATION:
            return self._persist
        return False

    def save_object(self, object_list, item_location=ItemLocation.ON_LOT, container_id=0):
        if not self.is_persistable():
            return
        with ProtocolBufferRollback(object_list) as save_data:
            attribute_data = self.get_attribute_save_data()
            save_data.object_id = self.id
            if attribute_data is not None:
                save_data.attributes = attribute_data.SerializeToString()
            save_data.guid = self.definition.id
            save_data.loc_type = item_location
            save_data.container_id = container_id
            return save_data

    def get_attribute_save_data(self):
        attribute_data = protocols.PersistenceMaster()
        self.save(attribute_data)
        return attribute_data

    @forward_to_components
    def save(self, persistence_master_message):
        pass

    def load(self, persistence_master_message):
        component_priority_list = []
        for persistable_data in persistence_master_message.data:
            component_priority_list.append((get_component_priority_and_name_using_persist_id(persistable_data.type), persistable_data))
        component_priority_list.sort(key=lambda priority: priority[0][0], reverse=True)
        for ((_, (_, inst_comp)), persistable_data) in component_priority_list:
            while inst_comp:
                self.add_dynamic_component(inst_comp)
                if self.has_component(inst_comp):
                    getattr(self, inst_comp).load(persistable_data)

    def finalize(self, **kwargs):
        self.on_finalize_load()

    def clone(self, **kwargs):
        clone = objects.system.create_object(self.definition, **kwargs)
        object_list = file_serialization.ObjectList()
        save_data = self.save_object(object_list.objects)
        clone.load_object(save_data)
        return clone

