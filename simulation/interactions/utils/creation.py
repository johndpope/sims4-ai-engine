import random
from interactions import ParticipantType, ParticipantTypeActorTargetSim
from interactions.interaction_finisher import FinishingType
from interactions.utils.interaction_elements import XevtTriggeredElement
from objects.components.state import TunableStateValueReference
from objects.helpers.create_object_helper import CreateObjectHelper
from objects.system import create_object
from sims.sim_spawner import SimSpawner
from sims4.tuning.geometric import TunableVector3
from sims4.tuning.tunable import TunableReference, TunableList, TunableEnumEntry, TunableVariant, TunableTuple, Tunable, OptionalTunable, TunableInterval, AutoFactoryInit, HasTunableSingletonFactory
from world.spawn_actions import TunableSpawnActionVariant
import build_buy
import placement
import services
import sims4.math
logger = sims4.log.Logger('Creation')

class ObjectCreationElement(XevtTriggeredElement):
    __qualname__ = 'ObjectCreationElement'
    POSITION = 'position'
    INVENTORY = 'inventory'
    SLOT = 'slot'

    class ObjectDefinition(HasTunableSingletonFactory, AutoFactoryInit):
        __qualname__ = 'ObjectCreationElement.ObjectDefinition'
        FACTORY_TUNABLES = {'definition': TunableReference(description='\n                The definition of the object that is created.\n                ', manager=services.definition_manager())}

        def get_definition(self):
            return self.definition

        def setup_created_object(self, interaction, created_object):
            pass

    class RecipeDefinition(HasTunableSingletonFactory, AutoFactoryInit):
        __qualname__ = 'ObjectCreationElement.RecipeDefinition'
        FACTORY_TUNABLES = {'recipe': TunableReference(description='\n                The recipe to use to create the object.\n                ', manager=services.recipe_manager())}

        def get_definition(self):
            return self.recipe.final_product.definition

        def setup_created_object(self, interaction, created_object):
            from crafting.crafting_process import CraftingProcess
            crafting_process = CraftingProcess(crafter=interaction.sim, recipe=self.recipe)
            crafting_process.setup_crafted_object(created_object, is_final_product=True)

    FACTORY_TUNABLES = {'description': '\n            Create an object as part of an interaction.\n            ', 'creation_data': TunableVariant(description='\n            Define what to create.\n            ', definition=ObjectDefinition.TunableFactory(), recipe=RecipeDefinition.TunableFactory(), default='definition'), 'initial_states': TunableList(description='\n            A list of states to apply to the object as soon as it is created.\n            ', tunable=TunableStateValueReference()), 'destroy_on_placement_failure': Tunable(description='\n            If checked, the created object will be destroyed on placement failure.\n            If unchecked, the created object will be placed into an appropriate\n            inventory on placement failure if possible.  If THAT fails, object\n            will be destroyed.\n            ', tunable_type=bool, default=False), 'cancel_on_destroy': Tunable(description='\n            If checked, the interaction will be canceled if object is destroyed\n            due to placement failure or if destroy on placement failure is\n            unchecked and the fallback fails.\n            ', tunable_type=bool, default=True), 'transient': Tunable(description='\n            If checked, the created object will be destroyed when the interaction ends.\n            ', tunable_type=bool, default=False), 'location': TunableVariant(description='\n            Where the object should be created.\n            ', default='position', position=TunableTuple(description='\n                An in-world position based off of the chosen Participant Type.\n                ', locked_args={'location': POSITION}, location_target=TunableEnumEntry(description='\n                    Who or what to create this object next to.\n                    ', tunable_type=ParticipantType, default=ParticipantType.Actor), offset_tuning=TunableTuple(default_offset=TunableVector3(description="\n                        The default Vector3 offset from the location target's\n                        position.\n                        ", default=sims4.math.Vector3.ZERO()), x_randomization_range=OptionalTunable(TunableInterval(description='\n                        A random number in this range will be applied to the\n                        default offset along the x axis.\n                        ', tunable_type=float, default_lower=0, default_upper=0)), z_randomization_range=OptionalTunable(TunableInterval(description='\n                        A random number in this range will be applied to the\n                        default offset along the z axis.\n                        ', tunable_type=float, default_lower=0, default_upper=0))), ignore_bb_footprints=Tunable(description='\n                    Ignores the build buy object footprints when trying to find\n                    a position for creating this object.  This will allow \n                    objects to appear on top of each other.\n                    e.g. Trash cans when tipped over want to place the trash \n                    right under them so it looks like the pile came out from \n                    the object while it was tipped.\n                    ', tunable_type=bool, default=True), allow_off_lot_placement=Tunable(description='\n                    If checked, objects will be allowed to be placed off-lot.\n                    If unchecked, we will always attempt to place created\n                    objects on the active lot.\n                    ', tunable_type=bool, default=False)), inventory=TunableTuple(description='\n                An inventory based off of the chosen Participant Type.\n                ', locked_args={'location': INVENTORY}, location_target=TunableEnumEntry(description='\n                    "The owner of the inventory the object will be created in."\n                    ', tunable_type=ParticipantType, default=ParticipantType.Actor)), slot=TunableTuple(description='\n                Slot the object into the specified slot on the tuned location_target.\n                ', locked_args={'location': SLOT}, location_target=TunableEnumEntry(description='\n                    The object which will contain the specified slot.\n                    ', tunable_type=ParticipantType, default=ParticipantType.Object), parent_slot=TunableVariant(description='\n                    The slot on location_target where the object should go. This\n                    may be either the exact name of a bone on the location_target or a\n                    slot type, in which case the first empty slot of the specified type\n                    in which the child object fits will be used.\n                    ', by_name=Tunable(description='\n                        The exact name of a slot on the location_target in which the target\n                        object should go.  \n                        ', tunable_type=str, default='_ctnm_'), by_reference=TunableReference(description='\n                        A particular slot type in which the target object should go.  The\n                        first empty slot of this type found on the location_target will be used.\n                        ', manager=services.get_instance_manager(sims4.resources.Types.SLOT_TYPE))))), 'reserve_object': OptionalTunable(description='\n            If this is enabled, the created object will be reserved for use by\n            the set Sim.\n            ', tunable=TunableEnumEntry(tunable_type=ParticipantTypeActorTargetSim, default=ParticipantTypeActorTargetSim.Actor))}

    def __init__(self, interaction, *args, sequence=(), **kwargs):
        super().__init__(interaction, sequence=sequence, *args, **kwargs)
        self._placement_failed = False
        if self.reserve_object is not None:
            reserved_sim = self.interaction.get_participant(self.reserve_object)
        else:
            reserved_sim = None
        self._object_helper = CreateObjectHelper(reserved_sim, self.definition, self, init=self._setup_created_object)

    @property
    def definition(self):
        return self.creation_data.get_definition()

    @property
    def placement_failed(self):
        return self._placement_failed

    def create_object(self):
        created_object = create_object(self.definition, init=self._setup_created_object, post_add=self._place_object)
        if self._placement_failed:
            created_object.destroy(source=self.interaction, cause='Failed to place object created by basic extra.')
            return
        return created_object

    def _build_outer_elements(self, sequence):
        return self._object_helper.create(sequence)

    def _do_behavior(self):
        self._place_object(self._object_helper.object)
        if self._placement_failed:
            if self.cancel_on_destroy:
                self.interaction.cancel(FinishingType.FAILED_TESTS, cancel_reason_msg='Cannot place object')
                return False
            return True
        if not self.transient:
            self._object_helper.claim()
        return True

    def _setup_created_object(self, created_object):
        self.creation_data.setup_created_object(self.interaction, created_object)
        for initial_state in self.initial_states:
            created_object.set_state(initial_state.state, initial_state)

    def _get_ignored_object_ids(self):
        pass

    def _place_object_no_fallback(self, created_object):
        participant = self.interaction.get_participant(self.location.location_target)
        if self.location.location == self.POSITION:
            offset_tuning = self.location.offset_tuning
            default_offset = sims4.math.Vector3(offset_tuning.default_offset.x, offset_tuning.default_offset.y, offset_tuning.default_offset.z)
            x_range = offset_tuning.x_randomization_range
            z_range = offset_tuning.z_randomization_range
            start_orientation = sims4.random.random_orientation()
            if x_range is not None:
                x_axis = start_orientation.transform_vector(sims4.math.Vector3.X_AXIS())
                default_offset += x_axis*random.uniform(x_range.lower_bound, x_range.upper_bound)
            if z_range is not None:
                z_axis = start_orientation.transform_vector(sims4.math.Vector3.Z_AXIS())
                default_offset += z_axis*random.uniform(z_range.lower_bound, z_range.upper_bound)
            offset = sims4.math.Transform(default_offset, sims4.math.Quaternion.IDENTITY())
            start_position = sims4.math.Transform.concatenate(offset, participant.transform).translation
            routing_surface = participant.routing_surface
            active_lot = services.active_lot()
            search_flags = placement.FGLSearchFlagsDefault
            if self.location.allow_off_lot_placement and not active_lot.is_position_on_lot(start_position):
                created_object.location = sims4.math.Location(sims4.math.Transform(start_position, start_orientation), routing_surface)
                polygon = placement.get_accurate_placement_footprint_polygon(created_object.position, created_object.orientation, created_object.scale, created_object.get_footprint())
                context = placement.FindGoodLocationContext(starting_position=start_position, starting_orientation=start_orientation, starting_routing_surface=routing_surface, ignored_object_ids=(created_object.id,), search_flags=search_flags, object_polygons=(polygon,))
            else:
                if not self.location.ignore_bb_footprints:
                    search_flags |= placement.FGLSearchFlag.SHOULD_TEST_BUILDBUY | placement.FGLSearchFlag.STAY_IN_CURRENT_BLOCK
                    if not active_lot.is_position_on_lot(start_position):
                        start_position = active_lot.get_default_position(position=start_position)
                context = placement.FindGoodLocationContext(starting_position=start_position, starting_orientation=start_orientation, starting_routing_surface=routing_surface, object_id=created_object.id, ignored_object_ids=self._get_ignored_object_ids(), search_flags=search_flags, object_footprints=(self.definition.get_footprint(0),))
            (translation, orientation) = placement.find_good_location(context)
            if translation is not None:
                created_object.move_to(routing_surface=routing_surface, translation=translation, orientation=orientation)
                return True
        elif self.location.location == self.SLOT:
            parent_slot = self.location.parent_slot
            if participant.slot_object(parent_slot=parent_slot, slotting_object=created_object):
                return True
        return False

    def _place_object(self, created_object):
        if self._place_object_no_fallback(created_object):
            return True
        if not self.destroy_on_placement_failure:
            participant = self.interaction.get_participant(self.location.location_target)
            if participant.inventory_component is not None and created_object.inventoryitem_component is not None:
                if participant.is_sim:
                    participant_household_id = participant.household.id
                else:
                    participant_household_id = participant.get_household_owner_id()
                created_object.set_household_owner_id(participant_household_id)
                participant.inventory_component.system_add_object(created_object, participant)
                return True
            sim = self.interaction.sim
            if sim is not None:
                if not sim.household.is_npc_household:
                    try:
                        created_object.set_household_owner_id(sim.household.id)
                        build_buy.move_object_to_household_inventory(created_object)
                        return True
                    except KeyError:
                        pass
        self._placement_failed = True
        return False

class SimCreationElement(XevtTriggeredElement):
    __qualname__ = 'SimCreationElement'
    FACTORY_TUNABLES = {'description': 'Create a Sim as part of an interaction.', 'sim_info_subject': TunableEnumEntry(description='\n            The subject from which the Sim Info used to create the new Sim\n            should be fetched.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'add_to_participant_household': OptionalTunable(description="\n            If this is enabled, the created Sim will be added to the\n            participant Sim's household.\n            ", tunable=TunableEnumEntry(tunable_type=ParticipantTypeActorTargetSim, default=ParticipantTypeActorTargetSim.Actor)), 'spawn_action': TunableSpawnActionVariant(description='\n            Define the methods to show the Sim after spawning on the lot. This\n            defaults to fading the Sim in, but can be a specific interaction or\n            an animation.\n            ')}

    def _do_behavior(self):
        stored_sim_info_object = self.interaction.get_participant(self.sim_info_subject)
        sim_info = stored_sim_info_object.get_stored_sim_info()
        if self.add_to_participant_household is not None:
            sim = self.interaction.get_participant(self.add_to_participant_household)
            if sim is None:
                logger.error('SimCreationElement: {} does not have participant {}', self.interaction, self.add_to_participant_household, owner='edwardramirez')
                return False
            household = sim.household
            if household is not sim_info.household:
                if not household.can_add_sim_info(sim_info):
                    logger.error('SimCreationElement: Trying to add {} to household {}. Household too full.', household, sim_info, owner='edwardramirez')
                    return False
                household.add_sim_info(sim_info)
                sim_info.assign_to_household(household)
        SimSpawner.spawn_sim(sim_info, stored_sim_info_object.position, spawn_action=self.spawn_action)
        client = services.client_manager().get_client_by_household_id(sim_info.household_id)
        if client is not None:
            client.add_selectable_sim_info(sim_info)
        return True

