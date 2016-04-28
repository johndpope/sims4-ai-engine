from random import randint
import operator
import weakref
from protocolbuffers import SimObjectAttributes_pb2 as protocols
from objects.components import Component, types, componentmethod, componentmethod_with_fallback
from objects.components.inventory_item import ItemLocation
from objects.components.state import TunableStateValueReference
from objects.components.types import SPAWNER_COMPONENT
from objects.system import create_object
from placement import FGLSearchFlag
from scheduler import TunableWeeklyScheduleFactory
from sims4.random import weighted_random_item
from sims4.tuning.instances import TunedInstanceMetaclass
from sims4.tuning.tunable import TunableVariant, TunableReference, HasTunableReference, HasTunableSingletonFactory, TunableList, AutoFactoryInit, HasTunableFactory, TunableRange, TunableTuple, TunableMapping, OptionalTunable, Tunable
from sims4.utils import flexmethod
import alarms
import date_and_time
import objects.components.types
import placement
import routing
import services
import sims4
import sims4.log
logger = sims4.log.Logger('SpawnerComponent', default_owner='camilogarcia')

class GlobalObjectSpawnerTuning:
    __qualname__ = 'GlobalObjectSpawnerTuning'
    SPAWN_ON_GROUND_FGL_HEIGHT_TOLERANCE = Tunable(description='\n        Maximum height tolerance on the terrain we will use for the placement \n        of the spawned object.\n        If the spawned objects have interactions on them, this value will\n        generate a height difference between the object and the sim.  Because\n        of this if this value changes all animations on spawned objects should\n        be verified.  Include a GPE and an Animator when making changes to \n        this value. \n        ', tunable_type=float, default=0.1)

class SpawnerTuning(HasTunableReference, HasTunableSingletonFactory, AutoFactoryInit, metaclass=TunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.RECIPE)):
    __qualname__ = 'SpawnerTuning'
    GROUND_SPAWNER = 1
    SLOT_SPAWNER = 2
    INTERACTION_SPAWNER = 3
    INSTANCE_TUNABLES = {'object_reference': TunableList(description='\n            List of objects the spawner can create.  When the random check \n            picks this value from the weight calculation it will give all\n            the items tuned on this list.\n            ', tunable=TunableReference(description='\n                Object reference to the object the spawner will give.\n                ', manager=services.definition_manager())), 'spawn_weight': TunableRange(description='\n            Weight that object will have on the probability calculation \n            of which object to spawn.\n            ', tunable_type=int, default=1, minimum=0), 'spawner_option': TunableVariant(description='\n            Type of spawners to create:\n            Ground type - Spawned object will appear on the floor at a tunable \n            radius from the spawner object.\n            Slot type - Spawned object will appear on an available slot of \n            a tunable slot type in the spawner object.\n            Interaction type - Spawned objects will appear on the inventory\n            when player makes a gather-harvest-scavenge interaction on them. \n            ', ground_spawning=TunableTuple(radius=TunableRange(description='\n                    Max radius at which the spawned object should appear\n                    ', tunable_type=int, default=1, minimum=0), force_states=TunableList(description='\n                    List of states the created object will be pushed to.\n                    ', tunable=TunableStateValueReference()), force_initialization_spawn=OptionalTunable(description='\n                    If checked, objects with this component will force a \n                    spawning of objects on initialization.  This is mainly used\n                    for objects on the open street where we want to fake that \n                    some time has already passed.  \n                    Additionally, if checked, objects will force the states\n                    on this list instead of the force_states list on the \n                    general spawner tuning, this way we can add some custom\n                    states only for the initialization spawn.\n                    ', tunable=TunableList(description='\n                        List of states the created object will have when\n                        initialized.\n                        ', tunable=TunableStateValueReference())), location_test=TunableTuple(is_outside=OptionalTunable(description='\n                        If checked, will verify if the spawned object is \n                        located outside. \n                        If unchecked will test the object is not outside\n                        ', disabled_name="Don't_Test", tunable=Tunable(bool, True)), is_natural_ground=OptionalTunable(description='\n                        If checked, will verify the spawned object is on \n                        natural ground.\n                        If unchecked will test the object is not on natural \n                        ground\n                        ', disabled_name="Don't_Test", tunable=Tunable(bool, True))), locked_args={'spawn_type': GROUND_SPAWNER}), slot_spawning=TunableTuple(slot_type=TunableReference(description='\n                    Slot type where spawned objects should appear\n                    ', manager=services.get_instance_manager(sims4.resources.Types.SLOT_TYPE)), state_mapping=TunableMapping(description='\n                    Mapping of states from the spawner object into the possible\n                    states that the spawned object may have\n                    ', key_type=TunableStateValueReference(), value_type=TunableList(description='\n                        List of possible children for a parent state\n                        ', tunable=TunableTuple(description='\n                            Pair of weight and possible state that the spawned \n                            object may have\n                            ', weight=TunableRange(description='\n                                Weight that object will have on the probability calculation \n                                of which object to spawn.\n                                ', tunable_type=int, default=1, minimum=0), child_state=TunableStateValueReference()))), locked_args={'spawn_type': SLOT_SPAWNER}), interaction_spawning=TunableTuple(locked_args={'spawn_type': INTERACTION_SPAWNER})), 'spawn_times': OptionalTunable(description='\n            Schedule of when the spawners should trigger.\n            If this time is tuned spawners will trigger according to this \n            schedule instead of the spawner commodities.   \n            This should be used for spawners that are on the open neighborhood \n            so that those spawners are time based instead of commodity based.\n            ', tunable=TunableWeeklyScheduleFactory(), disabled_name='No_custom_spawn_times', enabled_name='Set_custom_spawn_times')}
    FACTORY_TUNABLES = INSTANCE_TUNABLES

    @flexmethod
    def create_spawned_object(cls, inst, spawner_object, definition, loc_type=ItemLocation.ON_LOT):
        obj = create_object(definition, loc_type=loc_type)
        if obj is not None:
            spawner_object.spawner_component._spawned_objects.add(obj)
        return obj

with sims4.reload.protected(globals()):
    SpawnerInitializerSingleton = None

class SpawnerComponent(Component, HasTunableFactory, component_name=types.SPAWNER_COMPONENT, persistence_key=protocols.PersistenceMaster.PersistableData.SpawnerComponent):
    __qualname__ = 'SpawnerComponent'
    GROUND_SPAWNER_DECAY_COMMODITY = TunableReference(description='\n        Commodity which will trigger the ground spawner of an object on decay.', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC))
    SLOT_SPAWNER_DECAY_COMMODITY = TunableReference(description='\n        Commodity which will trigger the slot spawner of an object on decay.', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC))
    SPAWNER_COMMODITY_RESET_VARIANCE = TunableRange(description='\n        Max variance to apply when the spawn commodity is being reset to its\n        threshold value.  This is meant to add some randomness on how spawners\n        will create objects.  \n        e.g.  After a spawner creates an objects its spawn statistic will go \n        back to 100-RandomValue from 0 to Variance this way it wont always \n        start at the same time  \n        ', tunable_type=int, default=0, minimum=0)
    FACTORY_TUNABLES = {'spawner_data': TunableList(description='\n            Data corresponding at what objects will the spawner create and \n            their type which will define how they will be created\n            ', tunable=TunableVariant(description='\n                Option to tune the spawner data through a factory which will\n                be tuned per object, or through a reference which may be reused \n                by multiple objects \n                ', spawnerdata_factory=SpawnerTuning.TunableFactory(), spawnerdata_reference=SpawnerTuning.TunableReference())), 'spawn_firemeter': OptionalTunable(description='\n            If set, spawner will be limited to spawn this number of objects\n            at the same time.  \n            ', tunable=Tunable(description='\n                Number of objects this spawner can have created at one point.\n                ', tunable_type=int, default=1))}

    def __init__(self, owner, spawner_data, spawn_firemeter):
        super().__init__(owner)
        self._spawner_data = []
        self._spawner_stats = {}
        self._spawned_objects = weakref.WeakSet()
        self._spawned_object_ids = []
        self._spawn_firemeter = spawn_firemeter
        for spawner_data_item in spawner_data:
            self.add_spawner_data(spawner_data_item)
        self._spawner_initialized = False
        self._spawner_data_spawn_index = -1
        self._spawn_object_alarm = None

    @componentmethod
    def interaction_spawner_data(self):
        return [(data.spawn_weight, data.object_reference) for data in self._spawner_data if data.spawner_option.spawn_type == SpawnerTuning.INTERACTION_SPAWNER]

    @componentmethod
    def slot_spawner_definitions(self):
        return [data.object_reference for data in self._spawner_data if data.spawner_option.spawn_type == SpawnerTuning.SLOT_SPAWNER]

    def _get_non_interaction_spawner_data(self):
        return [(data.spawn_weight, data) for data in self._spawner_data if data.spawner_option.spawn_type != SpawnerTuning.INTERACTION_SPAWNER]

    def spawn_object_from_commodity(self, stat):
        self.reset_spawn_commodity(stat)
        self._spawn_object()

    def trigger_time_spawner(self, scheduler, alarm_data, trigger_cooldown):
        self._spawn_object()

    @componentmethod
    def force_spawn_object(self):
        self._spawn_object()

    def _spawn_object(self, spawn_type=None):
        if self._spawn_firemeter is not None and len(self._spawned_objects) >= self._spawn_firemeter:
            return
        if spawn_type:
            weight_pairs = [(data.spawn_weight, data) for data in self._spawner_data if data.spawner_option.spawn_type == spawn_type]
            force_initialization_spawn = True
        else:
            weight_pairs = self._get_non_interaction_spawner_data()
            force_initialization_spawn = False
        spawn_result = weighted_random_item(weight_pairs)
        if spawn_result:
            spawn_type = spawn_result.spawner_option.spawn_type
            if spawn_type == SpawnerTuning.GROUND_SPAWNER:
                radius = spawn_result.spawner_option.radius
                self.create_object_on_ground(self.owner, spawn_result, radius, force_initialization_spawn)
            if spawn_type == SpawnerTuning.SLOT_SPAWNER:
                slot_types = {spawn_result.spawner_option.slot_type}
                self.create_object_on_slot(self.owner, spawn_result, slot_types)

    def create_object_on_slot(self, source_object, spawner_data, slot_types):
        spawn_list = list(spawner_data.object_reference)
        parent_loc_type = self._get_inherited_spawn_location_type()
        for runtime_slot in source_object.get_runtime_slots_gen(slot_types=slot_types):
            if not spawn_list:
                return
            while runtime_slot.empty:
                obj_def = spawn_list.pop(0)
                obj = spawner_data.create_spawned_object(source_object, obj_def, loc_type=parent_loc_type)
                if obj is not None:
                    self.transfer_parent_states(obj, spawner_data.spawner_option.state_mapping)
                    runtime_slot.add_child(obj)

    def _get_inherited_spawn_location_type(self):
        parent_loc_type = self.owner.item_location
        if parent_loc_type == ItemLocation.FROM_WORLD_FILE:
            parent_loc_type = ItemLocation.FROM_OPEN_STREET
        return parent_loc_type

    def transfer_parent_states(self, child_obj, state_mapping):
        if state_mapping is None:
            return
        for parent_state in state_mapping.keys():
            while self.owner.state_value_active(parent_state):
                weight_pairs = [(data.weight, data.child_state) for data in state_mapping.get(parent_state)]
                state_result = weighted_random_item(weight_pairs)
                child_obj.set_state(state_result.state, state_result)

    def create_object_on_ground(self, source_object, spawner_data, max_distance, force_initialization_spawn):
        spawn_list = list(spawner_data.object_reference)
        parent_loc_type = self._get_inherited_spawn_location_type()
        for obj in spawn_list:
            if not services.lot_spawner_service_instance().check_spawner_firemeter():
                logger.info('SpawnerComponent: Firemeter reached, object {} will not spawn', obj)
                return
            created_obj = spawner_data.create_spawned_object(source_object, obj, loc_type=parent_loc_type)
            if created_obj is None:
                logger.error('SpawnerComponent: Spawner {} failed to create object: {}', source_object, obj, owner='camilogarcia')
                return
            created_obj.opacity = 0
            if self.owner.is_on_active_lot():
                search_flags = placement.FGLSearchFlagsDefault | FGLSearchFlag.SHOULD_TEST_BUILDBUY
                fgl_context = placement.FindGoodLocationContext(starting_position=created_obj.position, max_distance=max_distance, search_flags=search_flags, object_id=created_obj.id, height_tolerance=GlobalObjectSpawnerTuning.SPAWN_ON_GROUND_FGL_HEIGHT_TOLERANCE, object_footprints=(created_obj.definition.get_footprint(0),))
            else:
                search_flags = placement.FGLSearchFlagsDefault
                created_obj.location = sims4.math.Location(sims4.math.Transform(self.owner.position, self.owner.orientation), self.owner.routing_surface)
                polygon = placement.get_accurate_placement_footprint_polygon(created_obj.position, created_obj.orientation, created_obj.scale, created_obj.get_footprint())
                fgl_context = placement.FindGoodLocationContext(starting_position=created_obj.position, max_distance=max_distance, search_flags=search_flags, object_polygons=(polygon,), height_tolerance=GlobalObjectSpawnerTuning.SPAWN_ON_GROUND_FGL_HEIGHT_TOLERANCE, ignored_object_ids=(self.owner.id,))
            (position, orientation) = placement.find_good_location(fgl_context)
            if position is not None:
                created_obj.location = sims4.math.Location(sims4.math.Transform(position, orientation), source_object.routing_surface)
                services.lot_spawner_service_instance().register_spawned_object(created_obj)
                if force_initialization_spawn:
                    force_states = spawner_data.spawner_option.force_initialization_spawn
                else:
                    force_states = spawner_data.spawner_option.force_states
                for force_state in force_states:
                    created_obj.set_state(force_state.state, force_state)
                created_obj.fade_in()
            else:
                logger.info('SpawnerComponent: FGL failed, object {} will not spawn for spawner {}', created_obj, self.owner)
                created_obj.destroy(source=self.owner, cause='SpawnerComponent: FGL failed, object will not spawn.')

    def reset_spawn_commodity(self, stat):
        reset_value = stat.max_value - randint(0, self.SPAWNER_COMMODITY_RESET_VARIANCE)
        self.owner.commodity_tracker.set_value(stat.stat_type, reset_value)

    def _update_spawn_stat_listeners(self):
        existing_commodities = set(self._spawner_stats)
        spawn_commodities = set()
        for spawn_data in self._spawner_data:
            spawn_type = spawn_data.spawner_option.spawn_type
            if spawn_type == SpawnerTuning.GROUND_SPAWNER:
                spawn_commodities.add(self.GROUND_SPAWNER_DECAY_COMMODITY)
            while spawn_type == SpawnerTuning.SLOT_SPAWNER:
                spawn_commodities.add(self.SLOT_SPAWNER_DECAY_COMMODITY)
        for stat in spawn_commodities - existing_commodities:
            spawn_stat = self.owner.commodity_tracker.add_statistic(stat)
            threshold = sims4.math.Threshold(spawn_stat.min_value, operator.le)
            self._spawner_stats[stat] = self.owner.commodity_tracker.create_and_activate_listener(spawn_stat.stat_type, threshold, self.spawn_object_from_commodity)
        for stat in existing_commodities - spawn_commodities:
            self.owner.commodity_tracker.remove_listener(self._spawner_stats[stat])

    def _setup_time_based_spawners(self, weekly_schedule):
        self._scheduler = weekly_schedule(start_callback=self.trigger_time_spawner)

    @componentmethod_with_fallback(lambda *_: None)
    def add_spawner_data(self, spawner_data):
        self._spawner_data.append(spawner_data)
        if spawner_data.spawn_times is None:
            self._update_spawn_stat_listeners()
        else:
            self._setup_time_based_spawners(spawner_data.spawn_times)
            spawn_type = spawner_data.spawner_option.spawn_type
            if spawn_type == SpawnerTuning.GROUND_SPAWNER:
                self.owner.commodity_tracker.remove_statistic(self.GROUND_SPAWNER_DECAY_COMMODITY)
            if spawn_type == SpawnerTuning.SLOT_SPAWNER:
                self.owner.commodity_tracker.remove_statistic(self.SLOT_SPAWNER_DECAY_COMMODITY)

    def on_remove(self, *_, **__):
        self._destroy_spawner_alarm()

    def on_client_connect(self, client):
        for created_obj_id in self._spawned_object_ids:
            spawned_object = services.object_manager().get(created_obj_id)
            while spawned_object is not None:
                self._spawned_objects.add(spawned_object)
        self._spawned_object_ids = []
        SpawnerInitializer.create(client.zone_id)

    def initialize_spawning(self):
        if self._spawner_initialized:
            return
        self._spawner_initialized = True
        if self._spawner_data:
            self._spawner_data_spawn_index = 0
            self._create_spawner_alarm()

    def _create_spawner_alarm(self):
        if self._spawner_data_spawn_index >= len(self._spawner_data):
            return
        time_span = date_and_time.create_time_span(minutes=randint(SpawnerInitializer.SPAWN_DELAYED_START, SpawnerInitializer.SPAWN_DELAYED_END))
        repeating_time_span = date_and_time.create_time_span(minutes=SpawnerInitializer.SPAWN_FREQUENCY)
        self._spawn_object_alarm = alarms.add_alarm(self, time_span, self._spawn_one_object, repeating=True, repeating_time_span=repeating_time_span)

    def _destroy_spawner_alarm(self):
        if self._spawn_object_alarm is not None:
            alarms.cancel_alarm(self._spawn_object_alarm)
            self._spawn_object_alarm = None
            self._spawner_data_spawn_index = -1

    def _spawn_one_object(self, _):
        if self._spawner_data_spawn_index >= len(self._spawner_data):
            self._destroy_spawner_alarm()
            return
        spawn_data = self._spawner_data[self._spawner_data_spawn_index]
        if spawn_data.spawner_option.spawn_type == SpawnerTuning.GROUND_SPAWNER and spawn_data.spawner_option.force_initialization_spawn is not None:
            self._spawn_object(spawn_type=SpawnerTuning.GROUND_SPAWNER)

    def save(self, persistence_master_message):
        persistable_data = protocols.PersistenceMaster.PersistableData()
        persistable_data.type = protocols.PersistenceMaster.PersistableData.SpawnerComponent
        spawner_data = persistable_data.Extensions[protocols.PersistableSpawnerComponent.persistable_data]
        spawner_data.spawned_obj_ids.extend(obj.id for obj in self._spawned_objects)
        spawner_data.spawner_initialized = self._spawner_initialized
        spawner_data.spawner_data_spawn_index = self._spawner_data_spawn_index
        persistence_master_message.data.extend([persistable_data])

    def load(self, persistence_master_message):
        spawner_data = persistence_master_message.Extensions[protocols.PersistableSpawnerComponent.persistable_data]
        for object_id in spawner_data.spawned_obj_ids:
            self._spawned_object_ids.append(object_id)
        self._spawner_initialized = spawner_data.spawner_initialized
        self._spawner_data_spawn_index = spawner_data.spawner_data_spawn_index
        if self._spawner_data_spawn_index != -1:
            self._create_spawner_alarm()

class SpawnerInitializer:
    __qualname__ = 'SpawnerInitializer'
    SPAWN_FREQUENCY = Tunable(description='\n        This is the frequency at which the spawner components spawn the\n        individual objects for the first time you are playing in the zone.\n        Please talk with a GPE about performance concerns if you tune this\n        value.\n        ', tunable_type=int, default=5)
    SPAWN_DELAYED_START = Tunable(description='\n        This is the minimum amount of sim minutes we wait before we start\n        spawning objects for the first time in the zone at SPAWN_FREQUENCY. We\n        pick a random time between the start and end delayed time.\n        ', tunable_type=int, default=15)
    SPAWN_DELAYED_END = Tunable(description='\n        This is the maximum amount of sim minutes we wait before we start\n        spawning objects for the first time in the zone at SPAWN_FREQUENCY. We\n        pick a random time between the start and end delayed time.\n        ', tunable_type=int, default=60)

    @classmethod
    def create(cls, zone_id):
        global SpawnerInitializerSingleton
        if SpawnerInitializerSingleton is not None and SpawnerInitializerSingleton.zone_id != zone_id:
            SpawnerInitializerSingleton.destroy()
        if SpawnerInitializerSingleton is None:
            SpawnerInitializerSingleton = SpawnerInitializer(zone_id)

    @classmethod
    def destroy(cls):
        global SpawnerInitializerSingleton
        SpawnerInitializerSingleton = None

    def __init__(self, zone_id):
        self._zone_id = zone_id

    @property
    def zone_id(self):
        return self._zone_id

    def spawner_spawn_objects_post_nav_mesh_load(self, zone_id):
        if zone_id == self._zone_id:
            with sims4.zone_utils.global_zone_lock(self._zone_id):
                for obj in services.object_manager(self._zone_id).get_all_objects_with_component_gen(SPAWNER_COMPONENT):
                    obj.spawner_component.initialize_spawning()
        else:
            logger.info('Mismatched zone id in Spawner initialization. Fence Zone id: {}. Registered Zone id: {}', zone_id, self._zone_id)
            self.destroy()

@sims4.commands.Command('spawners.force_spawn_objects')
def force_spawn_objects(_connection=None):
    for obj in services.object_manager().get_all_objects_with_component_gen(objects.components.types.SPAWNER_COMPONENT):
        obj.force_spawn_object()

