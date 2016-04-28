from collections import OrderedDict
import gc
import time
from sims4.resources import INSTANCE_TUNING_DEFINITIONS
from sims4.tuning.instance_manager import TuningInstanceManager
from sims4.tuning.tunable import Tunable, TunableReference
import paths
import sims4.reload
import sims4.service_manager
try:
    import _zone
except ImportError:

    class _zone:
        __qualname__ = '_zone'

        @staticmethod
        def invite_sims_to_zone(*_, **__):
            pass

        @staticmethod
        def get_house_description_id(*_, **__):
            pass

        @staticmethod
        def get_lot_description_id(*_, **__):
            pass

        @staticmethod
        def get_world_description_id(*_, **__):
            pass

        @staticmethod
        def get_world_and_lot_description_id_from_zone_id(*_, **__):
            pass

        @staticmethod
        def get_hide_from_lot_picker(*_, **__):
            pass

invite_sims_to_zone = _zone.invite_sims_to_zone
get_house_description_id = _zone.get_house_description_id
get_lot_description_id = _zone.get_lot_description_id
get_world_description_id = _zone.get_world_description_id
get_world_and_lot_description_id_from_zone_id = _zone.get_world_and_lot_description_id_from_zone_id
get_hide_from_lot_picker = _zone.get_hide_from_lot_picker
with sims4.reload.protected(globals()):
    INSTANCE_TUNING_MANAGER_ACCESSORS = OrderedDict()
    INSTANCE_TUNING_MANAGERS = {}
    _account_service = None
    _zone_manager = None
    _server_clock_service = None
    _persistence_service = None
    _distributor_service = None
    definition_manager = None
    snippet_manager = None
    _terrain_object = None

def _create_instance_manager(definition):
    from sims4.tuning.instance_manager import InstanceManager
    mgr_type = definition.TYPE_ENUM_VALUE
    mgr_path = paths.TUNING_ROOTS[definition.resource_type]
    mgr_factory = InstanceManager
    args = (mgr_path, mgr_type)
    kwargs = {}
    kwargs['use_guid_for_ref'] = definition.use_guid_for_ref
    if mgr_type == sims4.resources.Types.OBJECT:
        from objects.definition_manager import DefinitionManager
        mgr_factory = DefinitionManager
    elif mgr_type == sims4.resources.Types.TUNING:
        from sims4.tuning.module_tuning import ModuleTuningManager
        mgr_factory = ModuleTuningManager
    elif mgr_type == sims4.resources.Types.ASPIRATION:
        from aspirations.aspiration_instance_manager import AspirationInstanceManager
        mgr_factory = AspirationInstanceManager
    elif mgr_type == sims4.resources.Types.INTERACTION:
        from interactions.interaction_instance_manager import InteractionInstanceManager
        mgr_factory = InteractionInstanceManager
    return mgr_factory(*args, **kwargs)

def _generate_instance_manager_accessor(definition):

    def accessor():
        manager = INSTANCE_TUNING_MANAGERS.get(definition.TYPE_ENUM_VALUE)
        if manager is None:
            manager = _create_instance_manager(definition)
            INSTANCE_TUNING_MANAGERS[definition.TYPE_ENUM_VALUE] = manager
        return manager

    accessor.__docstring__ = 'Return the {}, creating it if necessary.'.format(definition.type_name.title().replace('_', ' '))
    return accessor

for definition in INSTANCE_TUNING_DEFINITIONS:
    accessor_name = definition.manager_name
    accessor = _generate_instance_manager_accessor(definition)
    globals()[accessor_name] = accessor
    INSTANCE_TUNING_MANAGER_ACCESSORS[definition.TYPE_ENUM_VALUE] = accessor
production_logger = sims4.log.ProductionLogger('Services')
logger = sims4.log.Logger('Services')
time_delta = None
gc_collection_enable = True

class TimeStampService(sims4.service_manager.Service):
    __qualname__ = 'TimeStampService'

    def start(self):
        global gc_collection_enable, time_delta
        if gc_collection_enable:
            gc.disable()
            production_logger.info('GC disabled')
            gc_collection_enable = False
        else:
            gc.enable()
            production_logger.info('GC enabled')
            gc_collection_enable = True
        time_stamp = time.time()
        production_logger.info('TimeStampService start at {}'.format(time_stamp))
        logger.info('TimeStampService start at {}'.format(time_stamp))
        if time_delta is None:
            time_delta = time_stamp
        else:
            time_delta = time_stamp - time_delta
            production_logger.info('Time delta from loading start is {}'.format(time_delta))
            logger.info('Time delta from loading start is {}'.format(time_delta))
        return True

def start_services(initial_ticks):
    global _account_service, _zone_manager, _distributor_service
    create_server_clock(initial_ticks)
    from distributor.distributor_service import DistributorService
    from server.account_service import AccountService
    from zone_manager import ZoneManager
    from services.persistence_service import PersistenceService
    from sims4.tuning.serialization import FinalizeTuningService
    from services.terrain_service import TerrainService
    _account_service = AccountService()
    _zone_manager = ZoneManager()
    _distributor_service = DistributorService()
    init_critical_services = [server_clock_service(), get_persistence_service()]
    services = [_distributor_service, TimeStampService]
    tuning_managers = []
    for accessor in INSTANCE_TUNING_MANAGER_ACCESSORS.values():
        tuning_managers.append(accessor())
    services.append(TuningInstanceManager(tuning_managers))
    services.extend([FinalizeTuningService, TimeStampService, TerrainService, _zone_manager, _account_service])
    sims4.core_services.start_services(init_critical_services, services)

def stop_services():
    global _zone_manager, _account_service, _event_manager, _server_clock_service, _persistence_service, _distributor_service
    _zone_manager.shutdown()
    _zone_manager = None
    INSTANCE_TUNING_MANAGERS.clear()
    _account_service = None
    _event_manager = None
    _server_clock_service = None
    _persistence_service = None
    _distributor_service = None

def get_instance_manager(instance_type):
    return INSTANCE_TUNING_MANAGER_ACCESSORS[instance_type]()

def get_zone_manager():
    return _zone_manager

def current_zone():
    if _zone_manager is not None:
        return _zone_manager.get_current_zone()

def current_zone_id():
    if _zone_manager is not None:
        zone = _zone_manager.get_current_zone()
        if zone is not None:
            return zone.id

def get_zone(zone_id, allow_uninstantiated_zones=False):
    if _zone_manager is not None:
        return _zone_manager.get(zone_id, allow_uninstantiated_zones=allow_uninstantiated_zones)

def active_lot():
    zone = current_zone()
    if zone is not None:
        return zone.lot

def active_lot_id():
    lot = active_lot()
    if lot is not None:
        return lot.lot_id

def client_object_managers(zone_id=None):
    if zone_id is None:
        zone = current_zone()
    else:
        zone = _zone_manager.get(zone_id)
    if zone is not None:
        return zone.client_object_managers
    return ()

def sim_info_manager(zone_id=None):
    if zone_id is None:
        return current_zone().sim_info_manager
    return _zone_manager.get(zone_id).sim_info_manager

def object_manager(zone_id=None):
    if zone_id is None:
        zone = current_zone()
        if zone is not None:
            return zone.object_manager
        return
    return _zone_manager.get(zone_id).object_manager

def inventory_manager(zone_id=None):
    if zone_id is None:
        zone = current_zone()
        if zone is not None:
            return zone.inventory_manager
        return
    return _zone_manager.get(zone_id).inventory_manager

def prop_manager(zone_id=None):
    if zone_id is None:
        zone = current_zone()
    else:
        zone = _zone_manager.get(zone_id)
    if zone is not None:
        return zone.prop_manager

def social_group_manager():
    return current_zone().social_group_manager

def client_manager():
    return current_zone().client_manager

def owning_household_of_active_lot():
    zone = current_zone()
    if zone is not None:
        return zone.household_manager.get(zone.lot.owner_household_id)

def active_household():
    client = client_manager().get_first_client()
    if client is not None:
        return client.household

def active_household_id():
    client = client_manager().get_first_client()
    if client is not None:
        return client.household_id

def active_household_lot_id():
    household = active_household()
    if household is not None:
        home_zone = get_zone(household.home_zone_id)
        if home_zone is not None:
            lot = home_zone.lot
            if lot is not None:
                return lot.lot_id

def privacy_service():
    return current_zone().privacy_service

def autonomy_service():
    return current_zone().autonomy_service

def get_age_service():
    return current_zone().age_service

def neighborhood_population_service():
    return current_zone().neighborhood_population_service

def get_reset_and_delete_service():
    return current_zone().reset_and_delete_service

def venue_service():
    return current_zone().venue_service

def zone_spin_up_service():
    return current_zone().zone_spin_up_service

def lot_spawner_service_instance():
    return current_zone().lot_spawner_service

def household_manager(zone_id=None):
    if zone_id is None:
        zone = current_zone()
        if zone is not None:
            return zone.household_manager
        return
    return _zone_manager.get(zone_id).household_manager

def ui_dialog_service():
    return current_zone().ui_dialog_service

def config_service():
    return current_zone().config_service

def travel_service():
    return current_zone().travel_service

def sim_quadtree():
    return current_zone().sim_quadtree

def single_part_condition_list():
    return current_zone().single_part_condition_list

def multi_part_condition_list():
    return current_zone().multi_part_condition_list

def get_event_manager():
    return current_zone().event_manager

def get_current_venue():
    service = venue_service()
    if service is not None:
        return service.venue

def get_zone_situation_manager(zone_id=None):
    if zone_id is None:
        return current_zone().situation_manager
    return _zone_manager.get(zone_id).situation_manager

def sim_filter_service(zone_id=None):
    if zone_id is None:
        return current_zone().sim_filter_service
    return _zone_manager.get(zone_id).sim_filter_service

def social_group_cluster_service():
    return current_zone().social_group_cluster_service

def on_client_connect(client):
    sims4.core_services.service_manager.on_client_connect(client)
    current_zone().service_manager.on_client_connect(client)

def on_client_disconnect(client):
    sims4.core_services.service_manager.on_client_disconnect(client)
    current_zone().service_manager.on_client_disconnect(client)

def account_service():
    return _account_service

def time_service():
    zone = current_zone()
    if zone is None:
        return
    return zone.time_service

def game_clock_service():
    zone = current_zone()
    if zone is None:
        return
    return zone.game_clock

def server_clock_service():
    if _server_clock_service is None:
        return
    return _server_clock_service

def create_server_clock(initial_ticks):
    global _server_clock_service
    import clock
    _server_clock_service = clock.ServerClock(ticks=initial_ticks)

def get_master_controller():
    return current_zone().master_controller

def get_persistence_service():
    global _persistence_service
    if _persistence_service is None:
        from services.persistence_service import PersistenceService
        _persistence_service = PersistenceService()
    return _persistence_service

def get_distributor_service():
    return _distributor_service

def get_fire_service():
    return current_zone().fire_service

def get_super_speed_three_service():
    return current_zone().super_speed_three_service

def get_career_service():
    return current_zone().career_service

