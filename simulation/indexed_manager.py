import _weakrefutils
import argparse
import gc
import weakref
from sims4.callback_utils import CallableList
from sims4.service_manager import Service
import caches
import enum
import gsi_handlers
import id_generator
import services
import sims4.log
try:
    import _profile
    print_object_ref = _profile.print_object_ref
except ImportError:

    def print_object_ref(*_, **__):
        pass

__unittest__ = 'test.objects.manager_tests'
logger = sims4.log.Logger('IndexedManager')
production_logger = sims4.log.ProductionLogger('IndexedManager')

class TrackedIndexedObject:
    __qualname__ = 'TrackedIndexedObject'
    __slots__ = ['ref', 'gc_gen_two_iteration']

    def __init__(self, obj):
        self.ref = weakref.ref(obj)
        self.gc_gen_two_iteration = 0

class IndexedObjectTracker:
    __qualname__ = 'IndexedObjectTracker'

    def __init__(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--python_autoleak')
        parser.set_defaults(python_autoleak=False)
        (args, unused_args) = parser.parse_known_args()
        self.python_autoleak = args.python_autoleak
        self._remove_indexed_object_tracker = []
        self._should_trigger_full = False
        self.gc_callback_disable_reasons = []
        if not self.python_autoleak:
            return
        gc.callbacks.append(self._gc_callback)

    def _gc_callback(self, phase, info):
        generation = info['generation']
        if phase != 'stop' or generation < 1:
            return
        if self.gc_callback_disable_reasons:
            return
        new_list = []
        caches.clear_all_caches(force=True)
        for indexed_object in self._remove_indexed_object_tracker:
            obj = None
            if indexed_object.ref:
                obj = indexed_object.ref()
            if obj is None:
                pass
            if generation == 1:
                self._should_trigger_full = True
                new_list.append(indexed_object)
            if indexed_object.gc_gen_two_iteration > 0:
                self._print_leaked_object(obj)
                _weakrefutils.clear_weak_refs(obj)
            else:
                indexed_object.gc_gen_two_iteration = 1
                new_list.append(indexed_object)
        self._remove_indexed_object_tracker = new_list

    def _check_need_full_gc(self):
        if self._should_trigger_full:
            self._should_trigger_full = False
            caches.clear_all_caches(force=True)
            gc.collect()

    def add_object(self, obj):
        if not self.python_autoleak:
            return
        indexed_object = TrackedIndexedObject(obj)
        self._remove_indexed_object_tracker.append(indexed_object)
        self._check_need_full_gc()

    def _print_leaked_object(self, obj):
        logger.always('Possible object leak for [{0}]. For more info use |py.describe {1} ({2})', type(obj), id(obj), hex(id(obj)))
        print_object_ref(obj)

class CallbackTypes(enum.Int, export=False):
    __qualname__ = 'CallbackTypes'
    ON_OBJECT_ADD = 0
    ON_OBJECT_REMOVE = 1
    ON_OBJECT_LOCATION_CHANGED = 2

class ObjectIDError(Exception):
    __qualname__ = 'ObjectIDError'

class IndexedManager(Service):
    __qualname__ = 'IndexedManager'
    _indexed_object_tracker = IndexedObjectTracker()

    @classmethod
    def remove_gc_collect_disable_reason(cls, reason):
        if reason not in cls._indexed_object_tracker.gc_callback_disable_reasons:
            logger.error('Trying remove disable reason ({}), not added before', reason, owner='msantander')
            return
        cls._indexed_object_tracker.gc_callback_disable_reasons.remove(reason)

    @classmethod
    def add_gc_collect_disable_reason(cls, reason):
        cls._indexed_object_tracker.gc_callback_disable_reasons.append(reason)

    def __init__(self, *, manager_id=0):
        self.id = manager_id
        self._objects = {}
        self._objects_to_be_removed = []
        self._registered_callbacks = {}
        for key in CallbackTypes:
            self._registered_callbacks[key] = CallableList()

    def __contains__(self, key):
        if not isinstance(key, int):
            raise TypeError('IndexedManager keys must be integers.')
        return key in self._objects

    def __getitem__(self, key):
        if not isinstance(key, int):
            raise TypeError('IndexedManager keys must be integers.')
        return self._objects[key]

    def __iter__(self):
        return iter(self._objects)

    def __len__(self):
        return len(self._objects)

    def __bool__(self):
        if self._objects:
            return True
        return False

    def keys(self):
        return self._objects.keys()

    def values(self):
        return self._objects.values()

    def items(self):
        return self._objects.items()

    ids = property(keys)
    objects = property(values)
    id_object_pairs = property(items)

    def destroy_all_objects(self):
        cur_id = None
        while self._objects:
            try:
                (cur_id, object_being_shutdown) = next(iter(self._objects.items()))
                self.remove(object_being_shutdown)
            except Exception:
                logger.exception('Failed to remove {} from indexed manager', object_being_shutdown)
            finally:
                if cur_id in self._objects:
                    del self._objects[cur_id]

    def stop(self):
        self.destroy_all_objects()

    def register_callback(self, callback_type, callback):
        self._registered_callbacks[callback_type].append(callback)

    def unregister_callback(self, callback_type, callback):
        callback_list = self._registered_callbacks[callback_type]
        if callback in callback_list:
            callback_list.remove(callback)
        else:
            logger.warn('Attempt to remove callback that was not registered on {}: {}:{}', self, callback_type, callback, owner='maxr')

    def add(self, obj):
        new_id = obj.id or id_generator.generate_object_id()
        if new_id in self._objects:
            existing_obj = self.get(new_id)
            logger.callstack('ID collision detected. ID:{}, New Object:{}, Existing Object:{}', new_id, obj, existing_obj, level=sims4.log.LEVEL_ERROR, owner='tingyul')
            raise ObjectIDError
        self.call_pre_add(obj)
        self._objects[new_id] = obj
        obj.manager = self
        obj.id = new_id
        self.call_on_add(obj)
        return new_id

    def remove_id(self, obj_id):
        obj = self._objects.get(obj_id)
        return self.remove(obj)

    def is_removing_object(self, obj):
        if obj.id in self._objects_to_be_removed:
            return True
        return False

    def remove(self, obj):
        if obj.id not in self._objects:
            logger.error('Attempting to remove an object that is not in this manager')
            return
        if obj.id in self._objects_to_be_removed:
            logger.error('Attempting to remove an object {} that is already in the process of being removed.'.format(obj), owner='tastle')
            return
        try:
            self._objects_to_be_removed.append(obj.id)
            self.call_on_remove(obj)
            _weakrefutils.clear_weak_refs(obj)
            del self._objects[obj.id]
            self._objects_to_be_removed.remove(obj.id)
            obj.id = 0
            self.call_post_remove(obj)
            _weakrefutils.clear_weak_refs(obj)
            IndexedManager._indexed_object_tracker.add_object(obj)
        except Exception:
            logger.exception('Exception thrown while calling remove on {0}', obj)

    def get(self, obj_id):
        return self._objects.get(obj_id, None)

    def get_all(self):
        return self._objects.values()

    def call_pre_add(self, obj):
        if hasattr(obj, 'pre_add'):
            obj.pre_add(self)

    def call_on_add(self, obj):
        if hasattr(obj, 'on_add'):
            obj.on_add()
        self._registered_callbacks[CallbackTypes.ON_OBJECT_ADD](obj)

    def call_on_remove(self, obj):
        self._registered_callbacks[CallbackTypes.ON_OBJECT_REMOVE](obj)
        if hasattr(obj, 'on_remove'):
            obj.on_remove()

    def call_post_remove(self, obj):
        if hasattr(obj, 'post_remove'):
            obj.post_remove()

