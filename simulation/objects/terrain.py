from _weakrefset import WeakSet
from protocolbuffers import Consts_pb2, InteractionOps_pb2
from weakref import WeakKeyDictionary
from animation.posture_manifest import PostureManifestEntry, PostureManifest, MATCH_ANY, MATCH_NONE, SlotManifest
from animation.posture_manifest_constants import STAND_CONSTRAINT, STAND_POSTURE_STATE_SPEC, STAND_POSTURE_MANIFEST
from clock import ClockSpeedMode
from event_testing.results import TestResult
from interactions import ParticipantType
from interactions.aop import AffordanceObjectPair
from interactions.base.basic import TunableBasicContentSet
from interactions.base.immediate_interaction import ImmediateSuperInteraction
from interactions.base.super_interaction import SuperInteraction
from interactions.constraints import Constraint
from objects.components.state import TunableStateValueReference
from objects.proxy import ProxyObject
from objects.script_object import ScriptObject
from postures.posture_graph import supress_posture_graph_build
from postures.posture_state_spec import PostureStateSpec
from server.pick_info import PICK_UNGREETED
from services import definition_manager
from sims.sim_info_types import Gender, Age
from sims4.hash_util import hash32
from sims4.localization import LocalizationHelperTuning
from sims4.math import Vector2, Vector3, Quaternion, Transform, Location
from sims4.repr_utils import standard_repr, standard_float_tuple_repr
from sims4.resources import Types
from sims4.tuning.geometric import TunableVector2
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import TunableReference, Tunable, TunableTuple, TunableList, TunableRange, TunableEnumEntry, OptionalTunable
from sims4.utils import setdefault_callable, classproperty, flexmethod
from singletons import DEFAULT
from world.travel_tuning import TravelMixin
import caches
import distributor
import objects.system
import placement
import routing
import services
import sims.sim_spawner
import sims4.log
import sims4.math
import terrain
logger = sims4.log.Logger('Terrain')

def get_venue_instance_from_pick_location(pick):
    if pick is None:
        return
    lot_id = pick.lot_id
    if lot_id is None:
        return
    persistence_service = services.get_persistence_service()
    lot_owner_info = persistence_service.get_lot_proto_buff(lot_id)
    if lot_owner_info is not None:
        venue_key = lot_owner_info.venue_key
        venue_instance = services.get_instance_manager(sims4.resources.Types.VENUE).get(venue_key)
        return venue_instance

def get_zone_id_from_pick_location(pick):
    lot_id = pick.lot_id
    if lot_id is None:
        return
    persistence_service = services.get_persistence_service()
    return persistence_service.resolve_lot_id_into_zone_id(lot_id)

class TerrainInteractionMixin:
    __qualname__ = 'TerrainInteractionMixin'
    POSTURE_MANIFEST = STAND_POSTURE_MANIFEST
    POSTURE_STATE_SPEC = STAND_POSTURE_STATE_SPEC
    CONSTRAINT = STAND_CONSTRAINT

    @classmethod
    def _get_target_position_surface_and_test_off_lot(cls, target, context):
        (position, surface) = (None, None)
        if target is not None or context.pick is not None:
            (position, surface) = cls._get_position_and_surface(target, context)
            if position is None:
                return (position, surface, TestResult(False, 'Cannot Travel without a pick or target.'))
            zone = services.current_zone()
            if context.sim is not target:
                if zone.lot.is_position_on_lot(position):
                    return (position, surface, TestResult(False, 'Cannot Travel inside the bounds of the zone!'))
        return (position, surface, TestResult.TRUE)

    @classmethod
    def _get_position_and_surface(cls, target, context):
        if context.pick is not None:
            return (context.pick.location, context.pick.routing_surface)
        if target is not None:
            return (target.position, target.routing_surface)
        return (None, None)

    @classmethod
    def _define_supported_postures(cls):
        supported_postures = super()._define_supported_postures()
        if supported_postures:
            return supported_postures
        return cls.POSTURE_MANIFEST

    @classmethod
    def supports_posture_type(cls, posture_type, *args, **kwargs):
        if not posture_type.mobile:
            return False
        return super().supports_posture_type(posture_type, *args, **kwargs)

    @flexmethod
    def constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        inst_or_cls = cls if inst is None else inst
        yield inst_or_cls._constraint_gen(sim, target, participant_type)

    @classmethod
    def _constraint_gen(cls, *args, **kwargs):
        for constraint in super()._constraint_gen(*args, **kwargs):
            yield constraint
        yield cls.CONSTRAINT

class TerrainSuperInteraction(TerrainInteractionMixin, SuperInteraction):
    __qualname__ = 'TerrainSuperInteraction'
    INSTANCE_TUNABLES = {'basic_content': TunableBasicContentSet(no_content=True, default='no_content')}

    @classmethod
    def _constraint_gen(cls, *args, **kwargs):
        for constraint in super()._constraint_gen(*args, **kwargs):
            yield constraint
        yield services.current_zone().get_spawn_point_ignore_constraint()

lock_instance_tunables(TerrainSuperInteraction, basic_reserve_object=None, basic_focus=None)

class TerrainImmediateSuperInteraction(TerrainInteractionMixin, ImmediateSuperInteraction):
    __qualname__ = 'TerrainImmediateSuperInteraction'
    INSTANCE_SUBCLASSES_ONLY = True

class TravelSuperInteraction(TravelMixin, TerrainSuperInteraction):
    __qualname__ = 'TravelSuperInteraction'

    @classmethod
    def _test(cls, target, context, **kwargs):
        (position, _, result) = cls._get_target_position_surface_and_test_off_lot(target, context)
        if not result:
            return result
        if position is not None and not terrain.is_position_in_street(position):
            return TestResult(False, 'Cannot Travel from terrain outside of the street!')
        result = cls.travel_test(context)
        if not result:
            return result
        return TestResult.TRUE

    def _run_interaction_gen(self, timeline):
        if not services.get_persistence_service().is_save_locked():
            self.show_travel_dialog()
            services.game_clock_service().set_clock_speed(ClockSpeedMode.PAUSED)

class TravelHereSuperInteraction(TravelSuperInteraction):
    __qualname__ = 'TravelHereSuperInteraction'

    def __init__(self, *args, picked_item_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._traveling_sim_ids = set()
        if picked_item_ids is not None:
            self._traveling_sim_ids = picked_item_ids

    @flexmethod
    def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        if hasattr(context, 'pick'):
            venue_instance = get_venue_instance_from_pick_location(context.pick)
            if venue_instance is not None:
                return venue_instance.travel_interaction_name(target, context)
        return super(__class__, inst_or_cls)._get_name(target=target, context=context, **kwargs)

    @classmethod
    def _test(cls, target, context, **kwargs):
        (position, surface, result) = cls._get_target_position_surface_and_test_off_lot(target, context)
        if not result:
            return result
        location = routing.Location(position, sims4.math.Quaternion.IDENTITY(), surface)
        routable = routing.test_connectivity_permissions_for_handle(routing.connectivity.Handle(location), context.sim.routing_context)
        if routable:
            return TestResult(False, 'Cannot Travel from routable terrain !')
        result = cls.travel_test(context)
        if not result:
            return result
        to_zone_id = get_zone_id_from_pick_location(context.pick)
        if to_zone_id is None:
            return TestResult(False, 'Could not resolve lot id: {} into a valid zone id.', context.pick.lot_id)
        return TestResult.TRUE

    def _run_interaction_gen(self, timeline):
        to_zone_id = get_zone_id_from_pick_location(self.context.pick)
        if to_zone_id is None:
            logger.error('Could not resolve lot id: {} into a valid zone id when traveling to adjacent lot.', self.context.pick.lot_id, owner='rmccord')
            return
        if services.get_persistence_service().is_save_locked():
            return
        travel_info = InteractionOps_pb2.TravelSimsToZone()
        travel_info.zone_id = to_zone_id
        travel_info.sim_ids.append(self.sim.id)
        for traveling_sim_id in self._traveling_sim_ids:
            travel_info.sim_ids.append(traveling_sim_id)
        distributor.system.Distributor.instance().add_event(Consts_pb2.MSG_TRAVEL_SIMS_TO_ZONE, travel_info)
        services.game_clock_service().set_clock_speed(ClockSpeedMode.PAUSED)

class GoHereSuperInteraction(TerrainSuperInteraction):
    __qualname__ = 'GoHereSuperInteraction'
    POSTURE_MANIFEST = PostureManifest((PostureManifestEntry(None, 'stand', '', 'FullBody', MATCH_ANY, MATCH_ANY, MATCH_NONE),)).intern()
    POSTURE_STATE_SPEC = PostureStateSpec(POSTURE_MANIFEST, SlotManifest().intern(), None)
    CONSTRAINT = Constraint(debug_name='GoHere', posture_state_spec=POSTURE_STATE_SPEC, allow_small_intersections=True)
    _ignores_spawn_point_footprints = True

    @classmethod
    def _test(cls, target, context, **kwargs):
        (position, surface) = cls._get_position_and_surface(target, context)
        if position is None:
            return TestResult(False, 'Cannot go here without a pick or target.')
        routing_location = routing.Location(position, sims4.math.Quaternion.IDENTITY(), surface)
        if not routing.test_connectivity_permissions_for_handle(routing.connectivity.Handle(routing_location), context.sim.routing_context):
            return TestResult(False, 'Cannot GoHere! Unroutable area.')
        return TestResult.TRUE

    @classmethod
    def potential_interactions(cls, target, context, **kwargs):
        (position, surface) = cls._get_position_and_surface(target, context)
        if position is not None and context is not None and context.sim is not None:
            main_group = context.sim.get_visible_group()
            if main_group is not None and not main_group.is_solo:
                group_constraint = next(iter(main_group.get_constraint(context.sim)))
                if group_constraint is not None and group_constraint.routing_surface == surface:
                    while True:
                        for constraint in group_constraint:
                            group_geometry = constraint.geometry
                            while group_geometry is not None and group_geometry.contains_point(position):
                                yield AffordanceObjectPair(cls, target, cls, None, ignore_party=True, **kwargs)
                                return
        if cls._can_rally(context):
            for aop in cls.get_rallyable_aops_gen(target, context, **kwargs):
                yield aop
        yield cls.generate_aop(target, context, **kwargs)

class DebugSetupLotInteraction(TerrainImmediateSuperInteraction):
    __qualname__ = 'DebugSetupLotInteraction'
    INSTANCE_TUNABLES = {'setup_lot_destroy_old_objects': Tunable(bool, False, description='Destroy objects previously created by this interaction.'), 'setup_lot_objects': TunableList(TunableTuple(definition=TunableReference(definition_manager()), position=TunableVector2(Vector2.ZERO()), angle=TunableRange(int, 0, -360, 360), children=TunableList(TunableTuple(definition=TunableReference(definition_manager(), description='The child object to create.  It will appear in the first available slot in which it fits, subject to additional restrictions specified in the other values of this tuning.'), part_index=OptionalTunable(Tunable(int, 0, description='If specified, restrict slot selection to the given part index.')), bone_name=OptionalTunable(Tunable(str, '_ctnm_chr_', description='If specified, restrict slot selection to one with this exact bone name.')), slot_type=OptionalTunable(TunableReference(manager=services.get_instance_manager(Types.SLOT_TYPE), description='If specified, restrict slot selection to ones that support this type of slot.')), init_state_values=TunableList(description='\n                                List of states the children object will be set to.\n                                ', tunable=TunableStateValueReference()))), init_state_values=TunableList(description='\n                    List of states the created object will be pushed to.\n                    ', tunable=TunableStateValueReference())))}
    _zone_to_cls_to_created_objects = WeakKeyDictionary()

    @classproperty
    def destroy_old_objects(cls):
        return cls.setup_lot_destroy_old_objects

    @classproperty
    def created_objects(cls):
        created_objects = cls._zone_to_cls_to_created_objects.setdefault(services.current_zone(), {})
        return setdefault_callable(created_objects, cls, WeakSet)

    def _run_interaction_gen(self, timeline):
        with supress_posture_graph_build():
            if self.destroy_old_objects:
                while self.created_objects:
                    obj = self.created_objects.pop()
                    obj.destroy(source=self, cause='Destroying old objects in setup debug lot.')
            position = self.context.pick.location
            self.spawn_objects(position)
        return True

    def _create_object(self, definition_id, position=Vector3.ZERO(), orientation=Quaternion.IDENTITY(), level=0):
        obj = objects.system.create_object(definition_id)
        if obj is not None:
            transform = Transform(position, orientation)
            location = Location(transform, self.context.pick.routing_surface)
            obj.location = location
            self.created_objects.add(obj)
        return obj

    def spawn_objects(self, position):
        root = sims4.math.Vector3(float(position.x), 0, float(position.z))
        zone = services.current_zone()
        lot = zone.lot
        if not self.contained_in_lot(lot, root):
            closest_point = self.find_nearest_point_on_lot(lot, root)
            if closest_point is None:
                return False
            radius = (self.top_right_pos - self.bottom_left_pos).magnitude_2d()/2
            root = closest_point + sims4.math.vector_normalize(sims4.math.vector_flatten(lot.center) - closest_point)*(radius + 1)
            if not self.contained_in_lot(lot, root):
                sims4.log.warn('Placement', "Placed the lot objects but the entire bounding box isn't inside the lot. This is ok. If you need them to be inside the lot run the interaction again at a diffrent location.")

        def _generate_vector(offset_x, offset_z):
            ground_obj = services.terrain_service.terrain_object()
            ret_vector = sims4.math.Vector3(root.x + offset_x, 0, root.z + offset_z)
            ret_vector.y = ground_obj.get_height_at(ret_vector.x, ret_vector.z)
            return ret_vector

        def _generate_quat(rot):
            return sims4.math.Quaternion.from_axis_angle(rot, sims4.math.Vector3(0, 1, 0))

        for info in self.setup_lot_objects:
            new_pos = _generate_vector(info.position.x, info.position.y)
            new_rot = _generate_quat(sims4.math.PI/180*info.angle)
            new_obj = self._create_object(info.definition, new_pos, new_rot)
            if new_obj is None:
                sims4.log.error('SetupLot', 'Unable to create object: {}', info)
            for state_value in info.init_state_values:
                new_obj.set_state(state_value.state, state_value)
            for child_info in info.children:
                slot_owner = new_obj
                if child_info.part_index is not None:
                    for obj_part in new_obj.parts:
                        while obj_part.subroot_index == child_info.part_index:
                            slot_owner = obj_part
                            break
                bone_name_hash = None
                if child_info.bone_name is not None:
                    bone_name_hash = hash32(child_info.bone_name)
                slot_type = None
                if child_info.slot_type is not None:
                    slot_type = child_info.slot_type
                while True:
                    for runtime_slot in slot_owner.get_runtime_slots_gen(slot_types={slot_type}, bone_name_hash=bone_name_hash):
                        while runtime_slot.is_valid_for_placement(definition=child_info.definition):
                            break
                    sims4.log.error('SetupLot', 'Unable to find slot for child object: {}', child_info)
                child = self._create_object(child_info.definition)
                if child is None:
                    sims4.log.error('SetupLot', 'Unable to create child object: {}', child_info)
                runtime_slot.add_child(child)
                for state_value in child_info.init_state_values:
                    child.set_state(state_value.state, state_value)

    def contained_in_lot(self, lot, root):
        self.find_corner_points(root)
        return True

    def find_corner_points(self, root):
        max_x = 0
        min_x = 0
        max_z = 0
        min_z = 0
        for info in self.setup_lot_objects:
            if info.position.x > max_x:
                max_x = info.position.x
            if info.position.x < min_x:
                min_x = info.position.x
            if info.position.y > max_z:
                max_z = info.position.y
            while info.position.y < min_z:
                min_z = info.position.y
        self.top_right_pos = sims4.math.Vector3(root.x + max_x, 0, root.z + max_z)
        self.bottom_right_pos = sims4.math.Vector3(root.x + max_x, 0, root.z + min_z)
        self.top_left_pos = sims4.math.Vector3(root.x + min_x, 0, root.z + max_z)
        self.bottom_left_pos = sims4.math.Vector3(root.x + min_x, 0, root.z + min_z)

    def find_nearest_point_on_lot(self, lot, root):
        lot_corners = lot.corners
        segments = [(lot_corners[0], lot_corners[1]), (lot_corners[1], lot_corners[2]), (lot_corners[2], lot_corners[3]), (lot_corners[3], lot_corners[1])]
        dist = 0
        closest_point = None
        for segment in segments:
            new_point = sims4.math.get_closest_point_2D(segment, root)
            new_distance = (new_point - root).magnitude()
            if dist == 0:
                dist = new_distance
                closest_point = new_point
            else:
                while new_distance < dist:
                    dist = new_distance
                    closest_point = new_point
        return closest_point

class DebugCreateSimInteraction(TerrainImmediateSuperInteraction):
    __qualname__ = 'DebugCreateSimInteraction'

    def _run_interaction_gen(self, timeline):
        position = self.context.pick.location
        sims.sim_spawner.SimSpawner.create_sims([sims.sim_spawner.SimCreator()], sim_position=position, tgt_client=self.context.client, household=self.context.client.household, account=self.context.client.account, is_debug=True, creation_source='cheat: DebugCreateSimInteraction')
        return True

class DebugCreateSimWithGenderAndAgeInteraction(TerrainImmediateSuperInteraction):
    __qualname__ = 'DebugCreateSimWithGenderAndAgeInteraction'
    INSTANCE_TUNABLES = {'gender': TunableEnumEntry(Gender, Gender.MALE, description='The gender of the Sim to be created.'), 'age': TunableEnumEntry(Age, Age.ADULT, description='The age of the Sim to be created.')}

    def _run_interaction_gen(self, timeline):
        position = self.context.pick.location
        if self.age == Age.BABY:
            routing_surface = self.context.pick.routing_surface
            from sims.baby import debug_create_baby
            debug_create_baby(self.sim, position, gender=self.gender, routing_surface=routing_surface)
            return True
        sim_creator = sims.sim_spawner.SimCreator(age=self.age, gender=self.gender)
        sims.sim_spawner.SimSpawner.create_sims([sim_creator], sim_position=position, account=self.context.client.account, is_debug=True, creation_source='cheat: DebugCreateSimInteraction')
        return True

class DebugFindGoodLocationInteraction(TerrainImmediateSuperInteraction):
    __qualname__ = 'DebugFindGoodLocationInteraction'
    INSTANCE_TUNABLES = {'test_definition': TunableReference(description='\n            The object definition used to test Find Good Location.\n            ', manager=services.definition_manager())}

    def _run_interaction_gen(self, timeline):
        obj = objects.system.create_object(self.test_definition)
        if obj is not None:
            obj.move_to(translation=self.context.pick.location)
        (position, orientation) = placement.find_good_location(placement.FindGoodLocationContext(starting_position=self.context.pick.location, ignored_object_ids=(obj.id,), object_id=obj.id, position_increment=0.6, search_flags=placement.FGLSearchFlagsDefault | placement.FGLSearchFlag.SHOULD_TEST_BUILDBUY | placement.FGLSearchFlag.DONE_ON_MAX_RESULTS | placement.FGLSearchFlag.STAY_IN_CURRENT_BLOCK, object_footprints=(self.test_definition.get_footprint(0),)))
        if position is None or orientation is None:
            if obj is not None:
                obj.destroy(source=self, cause='Failed to find good location in debug find good location interaction.')
            return False
        loc = sims4.math.Transform(position, orientation)
        sims4.log.info('Placement', 'Found good location:\n    Pos: {0}\n    Ori: {1}', position, orientation)
        if obj is not None:
            obj.transform = loc
            return True
        return False

class Terrain(ScriptObject):
    __qualname__ = 'Terrain'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.visible_to_client = True
        self._raycast_context = routing.PathPlanContext()
        self._raycast_context.footprint_key = sims.sim_info.SimInfo.SIM_DEFINITION.get_footprint(0)
        self._raycast_context.agent_id = 0
        self._raycast_context.agent_radius = routing.get_default_agent_radius()
        self._raycast_context.set_key_mask(routing.FOOTPRINT_KEY_ON_LOT | routing.FOOTPRINT_KEY_OFF_LOT)

    @property
    def persistence_group(self):
        pass

    def raycast_context(self, for_carryable=False):
        return self._raycast_context

    def get_height_at(self, x, z):
        return terrain.get_terrain_height(x, z)

    def get_routing_surface_height_at(self, x, z, routing_surface):
        if routing_surface is None:
            return 0
        if routing_surface.type == routing.SURFACETYPE_WORLD:
            return terrain.get_lot_level_height(x, z, routing_surface.secondary_id, routing_surface.primary_id)
        if routing_surface.type == routing.SURFACETYPE_OBJECT:
            height = terrain.get_lot_level_height(x, z, routing_surface.secondary_id, services.current_zone().id)
            height = height + 1.0
            return height

    def get_center(self):
        return services.active_lot().center

    def is_position_on_lot(self, position):
        return services.active_lot().is_position_on_lot(position)

    def _get_ungreeted_overrides(self, context, **kwargs):
        if context.pick.pick_type not in PICK_UNGREETED:
            return
        if not context.pick.lot_id or context.pick.lot_id != services.active_lot().lot_id:
            return
        if not services.get_zone_situation_manager().is_player_waiting_to_be_greeted():
            return
        active_lot = services.active_lot()
        front_door = services.object_manager().get(active_lot.front_door_id)
        if front_door is None:
            return
        yield front_door.potential_interactions(context, **kwargs)

    def potential_interactions(self, context, **kwargs):
        yield super().potential_interactions(context, **kwargs)
        yield self._get_ungreeted_overrides(context, **kwargs)

    @property
    def routing_location(self):
        lot = services.active_lot()
        return routing.Location(lot.position, orientation=lot.orientation, routing_surface=routing.SurfaceIdentifier(services.current_zone().id, 0, routing.SURFACETYPE_WORLD))

    def get_routing_location_for_transform(self, transform):
        return routing.Location(transform.translation, transform.orientation, routing_surface=self.routing_location.routing_surface)

    check_line_of_sight = caches.uncached(ScriptObject.check_line_of_sight)

lock_instance_tunables(Terrain, _persists=False, _world_file_object_persists=False)

class TerrainPoint(ProxyObject):
    __qualname__ = 'TerrainPoint'
    _unproxied_attributes = ProxyObject._unproxied_attributes | {'_pick_location'}

    @staticmethod
    def create_for_position_and_orientation(position, routing_surface):
        pick_location = sims4.math.Location(sims4.math.Transform(position), routing_surface)
        return TerrainPoint(pick_location)

    def __new__(cls, location):
        return super().__new__(cls, services.terrain_service.terrain_object())

    def __init__(self, location):
        super().__init__(services.terrain_service.terrain_object())
        self._pick_location = location

    def __repr__(self):
        return standard_repr(self, standard_float_tuple_repr(*self.position))

    @property
    def transform(self):
        return self._pick_location.transform

    @property
    def position(self):
        return self.transform.translation

    @property
    def orientation(self):
        return self.transform.orientation

    @property
    def forward(self):
        return self.transform.orientation.transform_vector(sims4.math.Vector3.Z_AXIS())

    @property
    def routing_surface(self):
        return self._pick_location.routing_surface

    @property
    def intended_transform(self):
        return self.transform

    @property
    def intended_position(self):
        return self.position

    @property
    def intended_forward(self):
        return self.forward

    @property
    def intended_routing_surface(self):
        return self.routing_surface

    def get_or_create_routing_context(self):
        pass

    @property
    def routing_location(self):
        return routing.Location(self._pick_location.transform.translation, orientation=self._pick_location.transform.orientation, routing_surface=self._pick_location.routing_surface)

    def check_line_of_sight(self, transform, verbose=False):
        (result, _) = Terrain.check_line_of_sight(self, transform, verbose=True)
        if result == routing.RAYCAST_HIT_TYPE_IMPASSABLE:
            result = routing.RAYCAST_HIT_TYPE_NONE
        if verbose:
            return (result, 0)
        return (result == routing.RAYCAST_HIT_TYPE_NONE, 0)

    @property
    def routing_context(self):
        pass

    @property
    def footprint_polygon(self):
        return sims4.geometry.Polygon((self.position,))

    @property
    def object_radius(self):
        return 0.0

    @object_radius.setter
    def object_radius(self, value):
        logger.error('Object radius set on proxy: {}', self)

    @property
    def connectivity_handles(self):
        pass

    @property
    def children(self):
        return ()

    @property
    def is_sim(self):
        return False

