import weakref
from sims4.tuning.tunable import TunableList, TunableReference
import __hooks__
import objects.system
import protocolbuffers.FileSerialization_pb2 as file_serialization
import services
import sims4.core_services
import sims4.log
from sims4.tuning.instance_manager import InstanceManager
logger = sims4.log.Logger('DefinitionManager')

class TunableDefinitionList(TunableList):
    __qualname__ = 'TunableDefinitionList'

    def __init__(self, **kwargs):
        super().__init__(TunableReference(description='\n                The definition of the object.\n                ', manager=services.definition_manager()), **kwargs)

PROTOTYPE_INSTANCE_ID = 15013

class DefinitionManager(InstanceManager):
    __qualname__ = 'DefinitionManager'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._definitions_cache = {}
        if __hooks__.RELOADER_ENABLED:
            self._dependencies = {}

    def on_start(self):
        if __hooks__.RELOADER_ENABLED:
            sims4.core_services.file_change_manager().create_set(sims4.resources.Types.OBJECTDEFINITION, sims4.resources.Types.OBJECTDEFINITION)
        super().on_start()
        self.refresh_build_buy_tag_cache(refresh_definition_cache=False)

    def on_stop(self):
        if __hooks__.RELOADER_ENABLED:
            sims4.core_services.file_change_manager().remove_set(sims4.resources.Types.OBJECTDEFINITION)
        super().on_stop()

    def get_changed_files(self):
        changed = super().get_changed_files()
        changed.extend(sims4.core_services.file_change_manager().consume_set(sims4.resources.Types.OBJECTDEFINITION))
        return changed

    def get(self, def_id, obj_state=0, pack_safe=False):
        def_id = int(def_id)
        definition = self._definitions_cache.get((def_id, obj_state))
        if definition is not None:
            return definition
        return self._load_definition_and_tuning(def_id, obj_state)

    @property
    def loaded_definitions(self):
        return self._definitions_cache.values()

    def refresh_build_buy_tag_cache(self, refresh_definition_cache=True):
        for key in sorted(sims4.resources.list(type=sims4.resources.Types.OBJECTDEFINITION)):
            definition = self.get(key.instance)
            if definition is None:
                logger.error('Definition is None for instance id {}.', key.instance)
            definition.assign_build_buy_tags()
        if refresh_definition_cache:
            for definition in self._definitions_cache.values():
                definition.assign_build_buy_tags()

    def register_definition(self, def_id, interested_party):
        if __hooks__.RELOADER_ENABLED:
            objects_with_def = self._dependencies.get(def_id)
            if objects_with_def is None:
                objects_with_def = weakref.WeakSet()
                self._dependencies[def_id] = objects_with_def
            objects_with_def.add(interested_party)

    def unregister_definition(self, def_id, interested_party):
        if __hooks__.RELOADER_ENABLED:
            objects_with_def = self._dependencies.get(def_id)
            if objects_with_def is not None:
                objects_with_def.remove(interested_party)
                if not objects_with_def:
                    del self._dependencies[def_id]

    def reload_by_key(self, key):
        if not __debug__:
            raise RuntimeError('[manus] Reloading tuning is not supported for optimized python builds.')
        if key.type == sims4.resources.Types.OBJECTDEFINITION:
            self._reload_definition(key.instance)
        elif key.type == self.TYPE:
            super().reload_by_key(key)
            object_tuning = super().get(key)
            object_guid64 = getattr(object_tuning, 'guid64', None)
            reload_list = set()
            for ((def_id, obj_state), definition) in self._definitions_cache.items():
                def_cls = definition.cls
                def_cls_guid64 = getattr(def_cls, 'guid64', None)
                while object_guid64 is not None and def_cls_guid64 is not None and object_guid64 == def_cls_guid64:
                    reload_list.add((def_id, obj_state))
            for cache_key in reload_list:
                del self._definitions_cache[cache_key]
            for (def_id, obj_state) in reload_list:
                self._reload_definition(def_id, obj_state)

    def _reload_definition(self, def_id, state=0):
        if __hooks__.RELOADER_ENABLED:
            sims4.resources.purge_cache()
            definition = self._load_definition_and_tuning(def_id, state)
            if definition is not None and def_id in self._dependencies:
                list_copy = list(self._dependencies.get(def_id))
                self._dependencies[def_id].clear()
                for gameobject in list_copy:
                    if gameobject.is_sim:
                        pass
                    loc_type = gameobject.item_location
                    object_list = file_serialization.ObjectList()
                    save_data = gameobject.save_object(object_list.objects)
                    try:
                        gameobject.manager.remove(gameobject)
                    except:
                        logger.exception('exception in removing game object {}', gameobject)
                        continue
                    try:
                        dup = objects.system.create_object(definition, obj_id=gameobject.id, loc_type=loc_type)
                        dup.load_object(save_data)
                        if gameobject.location is not None:
                            dup.location = gameobject.location
                        inventory = dup.get_inventory()
                        if inventory is not None:
                            inventory.system_add_object(dup, None)
                        logger.error('reloading game object with ID {}', dup.id)
                    except:
                        logger.exception('exception in reinitializing game object {}', gameobject)
            return definition

    def _load_definition_and_tuning(self, def_id, obj_state):
        definition = self._load_definition(def_id)
        try:
            tuning_file_id = definition.tuning_file_id
            if tuning_file_id == 0:
                tuning_file_id = PROTOTYPE_INSTANCE_ID
            cls = super().get(tuning_file_id)
            if cls is None:
                return
            cls = cls.get_class_for_obj_state(obj_state)
        except:
            logger.exception('Unable to create a script object for definition id: {0}', def_id)
            return
        definition.set_class(cls)
        self._definitions_cache[(def_id, obj_state)] = definition
        definition.assign_build_buy_tags()
        return definition

    def _load_definition(self, def_id):
        key = sims4.resources.Key(sims4.resources.Types.OBJECTDEFINITION, def_id)
        resource = sims4.resources.load(key)
        properties = sims4.PropertyStreamReader(resource)
        return objects.definition.Definition(properties, def_id)

    def find_first_definition_by_cls(self, cls):
        for definition in self._definitions_cache.values():
            while definition.cls is cls:
                return definition

