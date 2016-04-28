from collections import defaultdict, namedtuple
import os.path
import time
from sims4.callback_utils import CallableList
from sims4.service_manager import Service
from sims4.tuning.merged_tuning_manager import get_manager
from sims4.tuning.tunable import UnavailablePackSafeResourceError
import sims4.core_services
import sims4.log
import sims4.reload
import sims4.resources
import sims4.tuning.serialization
logger = sims4.log.Logger('Tuning', default_owner='cjiang')
status_logger = sims4.log.Logger('Status', default_owner='manus')
with sims4.reload.protected(globals()):
    pass
TUNING_CALLBACK_YIELD_TIME_INTERVAL = 0.25
TUNING_LOADED_CALLBACK = '_tuning_loaded_callback'
VERIFY_TUNING_CALLBACK = '_verify_tuning_callback'
TuningCallbackHelper = namedtuple('TuningCallbackHelper', ('template', 'name', 'source', 'value'))
CREATING_INSTANCES = 'TuningInstanceManager: Creating instances for all InstanceManagers.'
LOADING_INSTANCES = 'TuningInstanceManager: Loading data into instances for all InstanceManagers.'
INVOKING_CALLBACKS = 'TuningInstanceManager: Invoking registered callbacks for all InstanceManagers.'
INVOKING_ON_START = 'TuningInstanceManager: Invoking on_start for all InstanceManagers.'
tuning_callback_counts = [0, 0]

class TuningInstanceManager(Service):
    __qualname__ = 'TuningInstanceManager'

    def __init__(self, instance_manager_list):
        self._instance_managers = instance_manager_list
        self._tuning_generator = None
        self._total_time = 0

    def start(self):
        self._tuning_generator = self._execute_gen()

    @property
    def can_incremental_start(self):
        return True

    def update_incremental_start(self):
        time_stamp = time.time()
        while not next(self._tuning_generator):
            delta = time.time() - time_stamp
            while delta > TUNING_CALLBACK_YIELD_TIME_INTERVAL:
                logger.debug('Just yielded from TuningInstanceManager. Time: {:2}.', delta, owner='manus')
                return False
        return True

    def execute(self, log_fn=None):
        for _ in self._execute_gen(log_fn=log_fn):
            pass

    def _execute_gen(self, log_fn=None):
        if log_fn is None:
            log_fn = logger.debug
        log_fn(CREATING_INSTANCES)
        for instance_manager in self._instance_managers:
            instance_manager.create_class_instances()
        yield False
        log_fn(LOADING_INSTANCES)
        for instance_manager in self._instance_managers:
            instance_manager.load_data_into_class_instances()
            yield False
        log_fn(INVOKING_CALLBACKS)
        for instance_manager in self._instance_managers:
            yield instance_manager.invoke_registered_callbacks_gen()
        log_fn(INVOKING_ON_START)
        for instance_manager in self._instance_managers:
            instance_manager.on_start()
        status_logger.always('Tuning load completed. Total Time: {:0.02f} seconds. #callbacks: {} #verification callbacks: {}', self._total_time, tuning_callback_counts[0], tuning_callback_counts[1], owner='manus', color=50)
        yield True

    def stop(self):
        for instance_manager in self._instance_managers:
            instance_manager.on_stop()

    def get_buckets_for_memory_tracking(self):
        return self._instance_managers

class InstanceManager:
    __qualname__ = 'InstanceManager'

    def __init__(self, path, type_enum, use_guid_for_ref=False):
        self._tuned_classes = {}
        self._callback_helper = {}
        self._verify_tunable_callback_helper = {}
        self._class_templates = []
        self.PATH = path
        self.TYPE = type_enum
        self._load_all_complete = False
        self._load_all_complete_callbacks = CallableList()
        self._use_guid_for_ref = use_guid_for_ref

    def add_on_load_complete(self, callback):
        if not self._load_all_complete:
            self._load_all_complete_callbacks.append(callback)
        else:
            callback(self)

    @property
    def all_instances_loaded(self):
        return self._load_all_complete

    def __str__(self):
        return 'InstanceManager_{}'.format(self.TYPE.name.lower())

    def get_changed_files(self):
        return sims4.core_services.file_change_manager().consume_set(self.TYPE)

    def reload_by_key(self, key):
        if not __debug__:
            raise RuntimeError('[manus] Reloading tuning is not supported for optimized python builds.')
        cls = self._tuned_classes.get(key)
        if cls is None:
            self.get(key)
            return
        try:
            sims4.tuning.serialization.restore_class_instance(cls)
            (tuning_callbacks, verify_callbacks) = sims4.tuning.serialization.load_from_xml(key, self.TYPE, cls, from_reload=True)
            if tuning_callbacks:
                for helper in tuning_callbacks:
                    helper.template.invoke_callback(cls, helper.name, helper.source, helper.value)
            if verify_callbacks:
                for helper in verify_callbacks:
                    helper.template.invoke_verify_tunable_callback(cls, helper.name, helper.source, helper.value)
            if hasattr(cls, TUNING_LOADED_CALLBACK):
                cls._tuning_loaded_callback()
            while hasattr(cls, VERIFY_TUNING_CALLBACK):
                cls._verify_tuning_callback()
        except:
            name = sims4.resources.get_name_from_key(key)
            logger.exception('Failed to reload tuning for {} (key:{}).', name, key, owner='manus')
            return
        return reload_dependencies_dict[key]

    @property
    def types(self):
        if not self.all_instances_loaded:
            logger.warn("Attempt to access instance types on '{}' before all instances are loaded", self)
        return self._tuned_classes

    def get_ordered_types(self, only_subclasses_of=object):

        def key(cls):
            result = tuple(x.__name__.lower() for x in reversed(cls.__mro__[:-1]))
            return (len(result), result)

        result = [c for c in self.types.values() if issubclass(c, only_subclasses_of)]
        result = sorted(result, key=key)
        return result

    @property
    def use_guid_for_ref(self):
        return self._use_guid_for_ref

    def register_class_template(self, template):
        self._class_templates.append(template)

    def register_tuned_class(self, instance, resource_key):
        if resource_key in self._tuned_classes:
            logger.info('Attempting to re-register class instance {} (Key:{}) with {}.', self._tuned_classes[resource_key], resource_key, self, owner='manus')
            return
        self._tuned_classes[resource_key] = instance
        instance.resource_key = resource_key
        if self.use_guid_for_ref:
            instance.guid64 = resource_key.instance

    def on_start(self):
        if sims4.core_services.SUPPORT_RELOADING_RESOURCES:
            file_change_manager = sims4.core_services.file_change_manager()
            if file_change_manager is not None:
                file_change_manager.create_set(self.TYPE, self.TYPE)

    def on_stop(self):
        if sims4.core_services.SUPPORT_RELOADING_RESOURCES:
            file_change_manager = sims4.core_services.file_change_manager()
            if file_change_manager is not None:
                file_change_manager.remove_set(self.TYPE)

    def create_class_instances(self):
        mtg = get_manager()
        res_id_list = mtg.get_all_res_ids(self.TYPE)
        logger.info('Creating {:4} tuning class instances managed by {}.', len(res_id_list), self, owner='manus')
        for (group_id, instance_id) in res_id_list:
            res_key = sims4.resources.Key(self.TYPE, instance_id, group_id)
            self._create_class_instance(res_key)

    def _create_class_instance(self, resource_key):
        cls = None
        try:
            registered_resource_key = sims4.resources.Key(self.TYPE, resource_key.instance)
            cls = sims4.tuning.serialization.create_class_instance(resource_key, self.TYPE)
            while cls is not None:
                self.register_tuned_class(cls, registered_resource_key)
        except Exception:
            if registered_resource_key in self._tuned_classes:
                del self._tuned_classes[registered_resource_key]
            logger.exception('An error occurred while attempting to create tuning instance: {}. Resource Key: {}.', cls, resource_key, owner='manus')

    def load_data_into_class_instances(self):
        logger.info('Loading {:4} tuning class instances managed by {}.', len(self._tuned_classes), self, owner='manus')
        for (key, cls) in self._tuned_classes.items():
            try:
                (tuning_callback_helpers, verify_tunable_callback_helpers) = sims4.tuning.serialization.load_from_xml(key, self.TYPE, cls)
                while tuning_callback_helpers:
                    self._callback_helper[cls] = tuning_callback_helpers
            except Exception:
                logger.exception('Exception while finalizing tuning for {}.', cls, owner='manus')

    def invoke_registered_callbacks_gen(self):
        logger.info('Invoking callbacks for {:4} tuning class instances managed by {}.', len(self._tuned_classes), self, owner='manus')
        invoke_verifications = False
        for cls in self._tuned_classes.values():
            self._invoke_tunable_callbacks(cls)
            if invoke_verifications:
                self._invoke_verify_tunable_callbacks(cls)
            try:
                if hasattr(cls, TUNING_LOADED_CALLBACK):
                    cls._tuning_loaded_callback()
                while invoke_verifications and hasattr(cls, VERIFY_TUNING_CALLBACK):
                    cls._verify_tuning_callback()
            except Exception:
                logger.exception('Exception in {}.{}.', cls, TUNING_LOADED_CALLBACK, owner='manus')
            yield False
        self._callback_helper = None
        self._verify_tunable_callback_helper = None
        self._load_all_complete = True
        self._load_all_complete_callbacks(self)

    def _invoke_tunable_callbacks(self, cls):
        tuning_callbacks = self._callback_helper.get(cls)
        if tuning_callbacks is None:
            return
        for helper in tuning_callbacks:
            try:
                helper.template.invoke_callback(cls, helper.name, helper.source, helper.value)
            except Exception:
                logger.exception('Exception in a tunable callback for variable {} in instance class {}.', helper.name, cls, owner='manus')

    def _invoke_verify_tunable_callbacks(self, cls):
        tuning_callbacks = self._verify_tunable_callback_helper.get(cls)
        if tuning_callbacks is None:
            return
        for helper in tuning_callbacks:
            try:
                helper.template.invoke_verify_tunable_callback(cls, helper.name, helper.source, helper.value)
            except Exception:
                logger.exception('Exception in a verify tunable callback for variable {} in instance class {}.', helper.name, cls, owner='manus')

    def get(self, name_or_id_or_key, pack_safe=False):
        key = sims4.resources.get_resource_key(name_or_id_or_key, self.TYPE)
        cls = self._tuned_classes.get(key)
        if cls is None:
            if not pack_safe:
                return
            raise UnavailablePackSafeResourceError
        return cls

    def _instantiate(self, target_type):
        return target_type()

    def export_descriptions(self, export_path, filter_fn=None):
        export_path = os.path.join(os.path.dirname(export_path), os.path.basename(self.PATH))
        export_path = os.path.join(export_path, 'Descriptions')
        to_export = {}
        for cls in sorted(self._class_templates, key=lambda cls: cls.__name__):
            cls_name = cls.__name__
            while filter_fn is None or filter_fn(cls):
                to_export[cls_name] = cls
        error_count = 0
        logger.info('TDESCs for {}: {}', self.TYPE.name, ', '.join([cls.__name__ for cls in to_export.values()]))
        for cls in to_export.values():
            result = sims4.tuning.serialization.export_class(cls, export_path, self.TYPE)
            while not result:
                error_count += 1
        return error_count

    def get_debug_statistics(self):
        result = []
        result.append(('TYPE', str(self.TYPE)))
        result.append(('PATH', str(self.PATH)))
        result.append(('UseGuidForReference', str(self._use_guid_for_ref)))
        result.append(('#TuningFiles', str(len(self._tuned_classes))))
        result.append(('#ClassTemplates', str(len(self._class_templates))))
        result.append(('LoadAllComplete', str(self._load_all_complete)))
        result.append(('#LoadAllCompelteCallbacks', str(len(self._load_all_complete_callbacks))))
        return result

def increment_tunable_callback_count(count):
    tuning_callback_counts[0] += count

def increment_verify_tunable_callback_count(count):
    tuning_callback_counts[1] += count

