import re
import sims4.log
logger = sims4.log.Logger('Services')

class Service:
    __qualname__ = 'Service'

    def setup(self, gameplay_zone_data=None, save_slot_data=None):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def pre_save(self):
        pass

    def save(self, object_list=None, zone_data=None, open_street_data=None, save_slot_data=None):
        pass

    def load(self, zone_data=None):
        pass

    def save_options(self, options_proto):
        pass

    def load_options(self, options_proto):
        pass

    def on_client_connect(self, client):
        pass

    def on_client_disconnect(self, client):
        pass

    def on_all_households_and_sim_infos_loaded(self, client):
        pass

    def on_cleanup_zone_objects(self, client):
        pass

    @property
    def can_incremental_start(self):
        return False

    def update_incremental_start(self):
        pass

    def get_zone_variable_name(self):
        return re.sub('(?<!^)(?=[A-Z])', '_', type(self).__name__).lower()

    def get_buckets_for_memory_tracking(self):
        return (self,)

    def __str__(self):
        return self.get_zone_variable_name()

class ServiceManager:
    __qualname__ = 'ServiceManager'

    def __init__(self):
        self.services = []
        self._init_critical_services = []
        self._services_to_start = []
        self._incremental_start_in_progress = False

    def register_service(self, service, is_init_critical=False):
        if not isinstance(service, Service):
            service = service()
        self.services.append(service)
        if is_init_critical:
            self._init_critical_services.append(service)

    def start_services(self, zone=None, gameplay_zone_data=None, save_slot_data=None, defer_start_to_tick=False):
        for service in self.services:
            if zone is not None:
                setattr(zone, service.get_zone_variable_name(), service)
            try:
                service.setup(gameplay_zone_data=gameplay_zone_data, save_slot_data=save_slot_data)
            except Exception:
                logger.error('Error during setup of service {}. This will likely cause additional errors in the future.', service)
        logger.info('Starting all services. zone: {}. defer: {}.', zone, defer_start_to_tick)
        if defer_start_to_tick:
            self._services_to_start = [service for service in self.services if service not in self._init_critical_services]
            for service in self._init_critical_services:
                try:
                    service.start()
                except Exception:
                    logger.exception('Error during start of service {}. This will likely cause additional errors in the future.', service)
            logger.info('Defer {} services to load separately.', len(self._services_to_start))
        else:
            for service in self.services:
                try:
                    service.start()
                except Exception:
                    logger.exception('Error during start of service {}. This will likely cause additional errors in the future.', service)

    def start_single_service(self):
        if not self._services_to_start:
            return True
        service = self._services_to_start[0]
        try:
            logger.info('Starting Service: {}. Pending services count: {}.', service, len(self._services_to_start), owner='manus')
            if self._incremental_start_in_progress:
                result = service.update_incremental_start()
                if result:
                    self._incremental_start_in_progress = False
                    self._services_to_start.pop(0)
                else:
                    logger.info('Incremental start in progress for service: {}.', service, owner='manus')
            else:
                service.start()
                if service.can_incremental_start:
                    self._incremental_start_in_progress = True
                else:
                    self._services_to_start.pop(0)
        except Exception:
            logger.exception('Error during initialization of service {}. This will likely cause additional errors in the future.', service)
            self._incremental_start_in_progress = False
            self._services_to_start.pop(0)
        if not self._services_to_start:
            return True
        return False

    def stop_services(self, zone=None):
        logger.debug('stop_services')
        while self.services:
            service = self.services.pop()
            logger.debug('Shutting Down Service: {}', service)
            try:
                service.stop()
            except Exception:
                logger.exception('Error during shutdown of service {}. This will likely cause additional errors in the future.', service)
            while zone is not None:
                setattr(zone, service.get_zone_variable_name(), None)
                continue

    def on_client_connect(self, client):
        for service in self.services:
            try:
                service.on_client_connect(client)
            except Exception:
                logger.exception('{} failed to handle client connection due to exception', service)

    def on_client_disconnect(self, client):
        for service in self.services:
            try:
                service.on_client_disconnect(client)
            except Exception:
                logger.exception('{} failed to handle client disconnect due to exception', service)

    def on_all_households_and_sim_infos_loaded(self, client):
        for service in self.services:
            try:
                service.on_all_households_and_sim_infos_loaded(client)
            except Exception:
                logger.exception('{} failed to handle on_all_households_and_sim_infos_loaded due to exception', service)

    def on_cleanup_zone_objects(self, client):
        for service in self.services:
            try:
                service.on_cleanup_zone_objects(client)
            except Exception:
                logger.exception('{} failed to handle on_cleanup_zone_objects due to exception', service)

    def save_all_services(self, persistence_service, error_code_start_value, **kwargs):
        initial_persistence_error_code = persistence_service.save_error_code if persistence_service is not None else None
        for (index, service) in enumerate(reversed(self.services)):
            try:
                service.pre_save()
            except BaseException as exc:
                if persistence_service is not None and initial_persistence_error_code == persistence_service.save_error_code:
                    persistence_service.save_error_code = int(error_code_start_value) + index
                raise
        for (index, service) in enumerate(reversed(self.services)):
            try:
                service.save(**kwargs)
            except BaseException as exc:
                if persistence_service is not None and initial_persistence_error_code == persistence_service.save_error_code:
                    persistence_service.save_error_code = int(error_code_start_value) + index
                raise

    def load_all_services(self, zone_data=None):
        for service in self.services:
            service.load(zone_data=zone_data)

    def save_options(self, options_proto):
        for service in self.services:
            service.save_options(options_proto)

    def load_options(self, options_proto):
        for service in self.services:
            try:
                service.load_options(options_proto)
            except:
                logger.exception('Failed to load options for {}', service)

