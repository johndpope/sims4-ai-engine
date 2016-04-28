import random
from element_utils import build_critical_section_with_finally
from elements import SubclassableGeneratorElement
from interactions import ParticipantType
from placement import FGLTuning
from sims4.callback_utils import CallableList
from sims4.math import Vector3, Vector3Immutable
from sims4.tuning.tunable import TunableEnumEntry, HasTunableFactory, AutoFactoryInit, Tunable, TunableSet, TunableEnumWithFilter
from tag import Tag
from uid import UniqueIdGenerator
import build_buy
import element_utils
import enum
import interactions.constraints
import placement
import routing
import services
import sims4.log
import tag
logger = sims4.log.Logger('Spawn Points', default_owner='rmccord')

class SpawnPointOption(enum.Int):
    __qualname__ = 'SpawnPointOption'
    SPAWN_ANY_POINT_WITH_CONSTRAINT_TAGS = 0
    SPAWN_SAME_POINT = 1
    SPAWN_ANY_POINT_WITH_SAVED_TAGS = 2
    SPAWN_DIFFERENT_POINT_WITH_SAVED_TAGS = 3

class SpawnPoint:
    __qualname__ = 'SpawnPoint'
    ARRIVAL_SPAWN_POINT_TAG = TunableEnumEntry(description='\n        The Tag associated with Spawn Points at the front of the lot.\n        ', tunable_type=Tag, default=Tag.INVALID)
    VISITOR_ARRIVAL_SPAWN_POINT_TAG = TunableEnumEntry(description='\n        The Tag associated with Spawn Points nearby the lot for visitors.\n        ', tunable_type=Tag, default=Tag.INVALID)

    def __init__(self, lot_id, zone_id, routing_surface=None):
        self.center = None
        self.lot_id = lot_id
        self._tags = set()
        if routing_surface is None:
            routing_surface = routing.SurfaceIdentifier(zone_id, 0, routing.SURFACETYPE_WORLD)
        self._routing_surface = routing_surface
        self._valid_slots = 0
        self._on_spawn_points_changed = CallableList()

    def __str__(self):
        return 'Name:{:20} Lot:{:15} Center:{:45} Tags:{}'.format(self.get_name(), self.lot_id, self.center, self.get_tags())

    @property
    def routing_surface(self):
        return self._routing_surface

    def get_name(self):
        raise NotImplementedError

    def get_tags(self):
        return self._tags

    def has_tag(self, tag):
        if tag is not None:
            return tag in self.get_tags()
        return False

    def next_spawn_spot(self):
        raise NotImplementedError

    def get_slot_pos(self, index=None):
        raise NotImplementedError

    @property
    def valid_slots(self):
        return self._valid_slots

    def reset_valid_slots(self):
        self._valid_slots = 0

    def register_spawn_point_changed_callback(self, callback):
        self._on_spawn_points_changed.append(callback)

    def unregister_spawn_point_changed_callback(self, callback):
        self._on_spawn_points_changed.remove(callback)

    def get_slot_positions(self):
        raise NotImplementedError

class WorldSpawnPoint(SpawnPoint):
    __qualname__ = 'WorldSpawnPoint'
    SPAWN_POINT_SLOTS = 8
    SLOT_START_OFFSET_FROM_CENTER = Vector3Immutable(-1.5, 0, -0.5)
    FOOTPRINT_HALF_DIMENSIONS = Vector3Immutable(2.0, 0, 1.0)
    SPAWN_POINT_SLOT_ROWS = 2
    SPAWN_POINT_SLOT_COLUMNS = 4

    def __init__(self, spawner_data, spawn_point_index, zone_id, routing_surface=None):
        super().__init__(0, zone_id, routing_surface)
        self.center = spawner_data[0]
        self.footprint_id = spawner_data[1]
        self.rotation = spawner_data[2]
        self.scale = spawner_data[3]
        self.obj_def_guid = spawner_data[4]
        if len(spawner_data) > 5:
            self.lot_id = spawner_data[5]
        else:
            self.lot_id = 0
        self.spawn_point_index = spawn_point_index
        self.spawn_point_id = spawn_point_index
        self.location = sims4.math.Location(sims4.math.Transform(self.center), routing_surface)
        self.random_indices = [x for x in range(WorldSpawnPoint.SPAWN_POINT_SLOTS)]
        random.shuffle(self.random_indices)
        self.spawn_index = 0
        self._footprint_polygon = None

    def next_spawn_spot(self):
        index = self.random_indices[self.spawn_index]
        pos = self.get_slot_pos(index)
        self.spawn_index = self.spawn_index + 1 if self.spawn_index < WorldSpawnPoint.SPAWN_POINT_SLOTS - 1 else 0
        pos.y = services.terrain_service.terrain_object().get_height_at(pos.x, pos.z)
        return (pos, None)

    def get_slot_pos(self, index=None):
        if index is None or not 0 <= index <= WorldSpawnPoint.SPAWN_POINT_SLOTS - 1:
            logger.warn('Slot Index {} for Spawn Point is out of range.', index)
            return self.center
        offset_from_start = WorldSpawnPoint.SLOT_START_OFFSET_FROM_CENTER
        offset = Vector3(offset_from_start.x, offset_from_start.y, offset_from_start.z)
        if index >= WorldSpawnPoint.SPAWN_POINT_SLOT_COLUMNS:
            pass
        return self._transform_position(offset)

    def _transform_position(self, local_position):
        scale_pos = local_position*self.scale
        rotate_pos = self.rotation.transform_vector(scale_pos)
        return rotate_pos + self.center

    def get_slot_positions(self):
        slot_positions = []
        for index in range(WorldSpawnPoint.SPAWN_POINT_SLOTS):
            pos = self.get_slot_pos(index)
            slot_positions.append(pos)
        if not slot_positions:
            pos = self.center
            pos.y = services.terrain_service.terrain_object().get_height_at(pos.x, pos.z)
            slot_positions.append(pos)
        return slot_positions

    def get_name(self):
        return build_buy.get_object_catalog_name(self.obj_def_guid)

    def get_tags(self):
        if not self._tags:
            self._tags = build_buy.get_object_all_tags(self.obj_def_guid)
        return self._tags

    def get_position_constraints(self):
        constraints = []
        for index in range(WorldSpawnPoint.SPAWN_POINT_SLOTS):
            pos = self.get_slot_pos(index)
            constraints.append(interactions.constraints.Position(pos, routing_surface=self.routing_surface, objects_to_ignore=set([self.spawn_point_id])))
        return constraints

    def validate_slots(self, dest_handles, routing_context):
        src_handles_to_indices = {}
        for index in range(WorldSpawnPoint.SPAWN_POINT_SLOTS):
            slot_pos = self.get_slot_pos(index)
            location = routing.Location(slot_pos, sims4.math.Quaternion.IDENTITY(), self.routing_surface)
            src_handles_to_indices[routing.connectivity.Handle(location)] = index
        connectivity = routing.test_connectivity_batch(set(src_handles_to_indices.keys()), dest_handles, routing_context=routing_context, flush_planner=True)
        if connectivity is not None:
            for (src, _, _) in connectivity:
                index = src_handles_to_indices.get(src)
                while index is not None:
                    self._valid_slots = self._valid_slots | 1 << index

    def get_footprint_polygon(self):
        if self._footprint_polygon is not None:
            return self._footprint_polygon
        v0 = self._transform_position(WorldSpawnPoint.FOOTPRINT_HALF_DIMENSIONS)
        v1 = self._transform_position(sims4.math.Vector3(-WorldSpawnPoint.FOOTPRINT_HALF_DIMENSIONS.x, WorldSpawnPoint.FOOTPRINT_HALF_DIMENSIONS.y, WorldSpawnPoint.FOOTPRINT_HALF_DIMENSIONS.z))
        v2 = self._transform_position(-WorldSpawnPoint.FOOTPRINT_HALF_DIMENSIONS)
        v3 = self._transform_position(sims4.math.Vector3(WorldSpawnPoint.FOOTPRINT_HALF_DIMENSIONS.x, WorldSpawnPoint.FOOTPRINT_HALF_DIMENSIONS.y, -WorldSpawnPoint.FOOTPRINT_HALF_DIMENSIONS.z))
        self._footprint_polygon = sims4.geometry.Polygon([v0, v1, v2, v3])
        return self._footprint_polygon

    def add_goal_suppression_region_to_quadtree(self):
        footprint_polygon = self.get_footprint_polygon()
        if footprint_polygon is None:
            return
        services.sim_quadtree().insert(self, self.spawn_point_id, placement.ItemType.ROUTE_GOAL_PENALIZER, footprint_polygon, self.routing_surface.secondary_id, False, 0)

class DynamicInteractionSpawnPoint(SpawnPoint):
    __qualname__ = 'DynamicInteractionSpawnPoint'
    get_next_id = UniqueIdGenerator()

    def __init__(self, interaction, participant_type, distance_to_participant, tag_set, lot_id, zone_id, routing_surface=None):
        super().__init__(lot_id, zone_id, routing_surface=routing_surface)
        self.interaction = interaction
        self.participant_type = participant_type
        self.distance_to_participant = distance_to_participant
        self.obj_def_guid = 0
        self.spawn_point_id = DynamicInteractionSpawnPoint.get_next_id()
        self._tags = tag_set
        if routing_surface is None:
            self._routing_surface = routing.SurfaceIdentifier(services.current_zone().id, 0, routing.SURFACETYPE_WORLD)
        self.location = None
        self.spawn_index = 0
        self._valid_slots = 1

    @property
    def routing_surface(self):
        participant = self.get_participant()
        if participant is not None:
            self._routing_surface = participant.routing_surface
        return self._routing_surface

    def next_spawn_spot(self):
        trans = self.get_slot_pos()
        orient = self.get_orientation_to_participant(trans)
        return (trans, orient)

    def get_name(self):
        participant = self.interaction.get_participant(participant_type=self.participant_type)
        return 'Dynamic Spawn Point near {} in {}'.format(participant, self.interaction)

    def get_participant(self):
        if self.interaction is None:
            return
        return self.interaction.get_participant(self.participant_type)

    def reset_valid_slots(self):
        self._valid_slots = 1

    def get_slot_pos(self, index=None):
        participant = self.get_participant()
        trans = None
        if participant is not None:
            (trans, _) = placement.find_good_location(placement.FindGoodLocationContext(starting_location=participant.location, max_distance=FGLTuning.MAX_FGL_DISTANCE, additional_avoid_sim_radius=routing.get_default_agent_radius(), object_id=participant.id, max_steps=10, offset_distance=self.distance_to_participant, scoring_functions=(placement.ScoringFunctionRadial(participant.location.transform.translation, self.distance_to_participant, 0, FGLTuning.MAX_FGL_DISTANCE),), search_flags=placement.FGLSearchFlag.STAY_IN_CONNECTED_CONNECTIVITY_GROUP | placement.FGLSearchFlag.SHOULD_TEST_BUILDBUY | placement.FGLSearchFlag.USE_SIM_FOOTPRINT | placement.FGLSearchFlag.CALCULATE_RESULT_TERRAIN_HEIGHTS))
        if trans is None:
            fallback_point = services.current_zone().get_spawn_point(lot_id=self.lot_id)
            (trans, _) = fallback_point.next_spawn_spot()
            return trans
        return trans

    def get_orientation_to_participant(self, position):
        participant = self.get_participant()
        if participant is None:
            return sims4.math.Quaternion.IDENTITY()
        target_location = participant.location
        vec_to_target = target_location.transform.translation - position
        theta = sims4.math.vector3_angle(vec_to_target)
        return sims4.math.angle_to_yaw_quaternion(theta)

    def get_position_constraints(self):
        trans = self.get_slot_pos()
        return [interactions.constraints.Position(trans, routing_surface=self.routing_surface, objects_to_ignore=set([self.spawn_point_id]))]

    def get_footprint_polygon(self):
        pass

    def get_slot_positions(self):
        return [self.get_slot_pos()]

class DynamicSpawnPointElement(SubclassableGeneratorElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'DynamicSpawnPointElement'
    FACTORY_TUNABLES = {'description': '\n            This Element will create a Dynamic Spawn Point which is registered\n            to a particular participant within the interaction. It will be\n            added to the zone and available for use by any Sims who want to\n            spawn.\n            ', 'tags': TunableSet(description="\n            A set of tags to add to the dynamic spawn point when it's created.\n            This is how we can use this spawn point to spawn particular Sims\n            without interfering with walkbys and other standard Sims that are\n            spawned.\n            ", tunable=TunableEnumWithFilter(tunable_type=tag.Tag, default=tag.Tag.INVALID, filter_prefixes=tag.SPAWN_PREFIX)), 'participant': TunableEnumEntry(description='\n            The Participant of the interaction that we want the spawn point to be near.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'attach_to_active_lot': Tunable(description='\n            If checked, the spawn point will be attached to the active lot.\n            This helps Sims who are looking to visit the current lot find a\n            spawn point nearby.\n            ', tunable_type=bool, default=False), 'distance_to_participant': Tunable(description='\n            The Distance from the participant that Sims should spawn.\n            ', tunable_type=float, default=7.0)}

    def __init__(self, interaction, *args, sequence=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.interaction = interaction
        self.sequence = sequence
        self.spawn_point = None

    def _run_gen(self, timeline):

        def begin(_):
            zone = services.current_zone()
            lot_id = 0 if not self.attach_to_active_lot else zone.lot.lot_id
            self.spawn_point = DynamicInteractionSpawnPoint(self.interaction, self.participant, self.distance_to_participant, self.tags, lot_id=lot_id, zone_id=zone.id)
            services.current_zone().add_dynamic_spawn_point(self.spawn_point)

        def end(_):
            services.current_zone().remove_dynamic_spawn_point(self.spawn_point)
            self.spawn_point = None

        result = yield element_utils.run_child(timeline, build_critical_section_with_finally(begin, self.sequence, end))
        return result

