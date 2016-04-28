import random
import weakref
from objects.components.spawner_component import SpawnerComponent
from objects.system import create_object
from placement import _placement
from sims4.service_manager import Service
from sims4.tuning.tunable import TunableMapping, Tunable, TunableRange, TunableLotDescription
from sims4.tuning.tunable_base import FilterTag
from world.lot import get_lot_id_from_instance_id
import alarms
import build_buy
import date_and_time
import placement
import routing
import services
import sims4.math

class LotSpawnerService(Service):
    __qualname__ = 'LotSpawnerService'
    FIREMETER_SPAWNER_OBJECT_CAP = Tunable(description='\n            Maximum value of spawner objects that the lot can have at any given\n            moment.\n            ', tunable_type=int, default=10)
    MAX_RANDOM_PLACEMENT_RETRIES = Tunable(description='\n            Maximum number of times to try placing a spawned object before \n            giving up. \n            ', tunable_type=int, default=10, tuning_filter=FilterTag.EXPERT_MODE)
    LOT_TO_SPAWNER_DATA = TunableMapping(description='\n            Mapping of Lot Description ID to spawner tuning.  All lots inside \n            this list will create alarms to create the data defined on the \n            spawner data\n            ', key_name='Lot Description ID', key_type=TunableLotDescription(), value_name='Spawner Data', value_type=SpawnerComponent.TunableFactory())
    LOT_SPAWNER_TIME_SETTINGS = TunableRange(description='\n            Hour of the day where the lot spawner service will check to create \n            tuned objects on the lot. \n            Warning for tuning: This should not be tuned too frequently to \n            avoid overpopulation of objects\n            ', tunable_type=int, default=12, minimum=0, maximum=23)

    def __init__(self):
        self._zone_spawner_data = weakref.WeakSet()
        self._zone_spawner_default_tuning = []
        self._zone_spawner_custom_time_tuning = []
        self._spawn_alarm_handle = None

    def setup_spawner(self):
        zone_spawner_tuning = self.get_lot_spawner_data(services.current_zone().lot.lot_id)
        if zone_spawner_tuning is None:
            return
        if self._spawn_alarm_handle is not None or self._zone_spawner_default_tuning or self._zone_spawner_default_tuning:
            return
        for lot_spawner in zone_spawner_tuning:
            if lot_spawner.spawn_times is not None:
                self._zone_spawner_custom_time_tuning.append(lot_spawner)
                lot_spawner.spawn_times(start_callback=self.trigger_lot_spawner_scheduler)
            else:
                self._zone_spawner_default_tuning.append(lot_spawner)
        if not self._zone_spawner_default_tuning:
            return
        game_clock_service = services.game_clock_service()
        repeat_length = date_and_time.create_time_span(hours=24)
        time = game_clock_service.time_until_hour_of_day(self.LOT_SPAWNER_TIME_SETTINGS)
        if time.in_ticks() <= 0:
            time = date_and_time.create_time_span(hours=24)
        self._spawn_alarm_handle = alarms.add_alarm(self, time, lambda _: self.trigger_lot_spawner_default(), repeating=True, repeating_time_span=repeat_length)

    def stop(self):
        if self._spawn_alarm_handle is not None:
            alarms.cancel_alarm(self._spawn_alarm_handle)

    def get_lot_spawner_data(self, lot_id):
        instance_ids = {}
        for guid in self.LOT_TO_SPAWNER_DATA.keys():
            instance_ids[get_lot_id_from_instance_id(guid)] = guid
        active_lot_guid = instance_ids.get(lot_id, 0)
        spawn_tuning = self.LOT_TO_SPAWNER_DATA.get(active_lot_guid, None)
        if spawn_tuning is not None:
            return spawn_tuning.spawner_data
        return spawn_tuning

    def trigger_lot_spawner_default(self):
        if not self._zone_spawner_default_tuning:
            return
        self.trigger_lot_spawner(False)

    def trigger_lot_spawner_scheduler(self, scheduler, alarm_data, trigger_cooldown):
        if not self._zone_spawner_custom_time_tuning:
            return
        self.trigger_lot_spawner(False)

    def trigger_lot_spawner(self, triggered_from_scheduler=False):
        client = services.client_manager().get_first_client()
        if client is None or client.household is None:
            return
        if triggered_from_scheduler:
            zone_spawner_tuning = self._zone_spawner_custom_time_tuning
        else:
            zone_spawner_tuning = self._zone_spawner_default_tuning
        routing_surface = routing.SurfaceIdentifier(sims4.zone_utils.get_zone_id(), 0, routing.SURFACETYPE_WORLD)
        for obj in zone_spawner_tuning:
            if not self.check_spawner_firemeter():
                return
            obj_tuple = obj.object_reference
            for obj_def in obj_tuple:
                obj_pos = self.verify_position_tests(obj.spawner_option.location_test)
                if obj_pos is None:
                    pass
                obj_location = sims4.math.Location(sims4.math.Transform(obj_pos, sims4.random.random_orientation()), routing_surface)
                (result, _) = build_buy.test_location_for_object(None, obj_def.id, obj_location, None)
                while result:
                    obj_inst = create_object(obj_def)
                    for force_state in obj.spawner_option.force_states:
                        obj_inst.set_state(force_state.state, force_state)
                    obj_inst.location = obj_location
                    self.register_spawned_object(obj_inst)

    def calculate_spawn_point(self, active_lot):
        pos = sims4.math.Vector3(0, 0, 0)
        pos.x = random.random()*active_lot.size_x
        pos.z = random.random()*active_lot.size_z
        rot = active_lot.orientation
        pos = rot.transform_vector(pos)
        pos += active_lot.position
        pos.y = services.terrain_service.terrain_object().get_height_at(pos.x, pos.z)
        return pos

    def check_spawner_firemeter(self):
        if len(self._zone_spawner_data) >= self.FIREMETER_SPAWNER_OBJECT_CAP:
            return False
        return True

    def verify_position_tests(self, location_test):
        active_lot = services.active_lot()
        for _ in range(self.MAX_RANDOM_PLACEMENT_RETRIES):
            obj_pos = self.calculate_spawn_point(active_lot)
            if location_test.is_outside is not None and location_test.is_outside != build_buy.is_location_outside(services.current_zone().id, obj_pos, 0):
                pass
            if location_test.is_natural_ground is not None and location_test.is_natural_ground != build_buy.is_location_natural_ground(services.current_zone().id, obj_pos, 0):
                pass

    def register_spawned_object(self, spawned_object):
        self._zone_spawner_data.add(spawned_object)

@sims4.commands.Command('spawners.lot.enable')
def enable_lot_spawners(enable:bool=False, _connection=None):
    if enable:
        services.lot_spawner_service_instance().setup_spawner()
    else:
        services.lot_spawner_service_instance().stop()

@sims4.commands.Command('spawners.lot.trigger')
def trigger_spawning(_connection=None):
    spawner_service = services.lot_spawner_service_instance()
    zone_spawner_tuning = spawner_service._zone_spawner_default_tuning + spawner_service._zone_spawner_custom_time_tuning
    if not zone_spawner_tuning:
        sims4.commands.output('Current lot has no spawner data tuned', _connection)
        return
    for obj_group in zone_spawner_tuning:
        for obj in obj_group.object_reference:
            sims4.commands.output('Object Tuned: {} with weight {} '.format(str(obj), obj_group.spawn_weight), _connection)
    spawner_service.trigger_lot_spawner(False)
    spawner_service.trigger_lot_spawner(True)

