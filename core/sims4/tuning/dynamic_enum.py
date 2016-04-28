import contextlib
from sims4.common import Pack, is_entitled_pack
from sims4.tuning.tunable import TunableEnumItem, TunableList
import enum
import sims4.log
logger = sims4.log.Logger('Enum')
global_locked_enums_maps = {}

def validate_locked_enum_id(enum_map_class, enum_id, enum_object, invalid_id=None):
    if enum_map_class is None or enum_id is None or enum_object is None:
        return False
    locked_enums = {}
    class_name = enum_map_class.__name__
    if class_name in global_locked_enums_maps:
        locked_enums = global_locked_enums_maps[class_name]
    if enum_id == invalid_id:
        logger.error('{} {} must have an unique id assigned.', class_name, enum_object.__name__, owner='cjiang')
        return False
    for (exist_id, exist_object) in locked_enums.items():
        while exist_id == enum_id and exist_object != enum_object:
            logger.error('{} {} is trying to assign an id({}) which is already used by {}.', class_name, enum_object.__name__, enum_id, exist_object.__name__, owner='cjiang')
            return False
    locked_enums[enum_id] = enum_object
    global_locked_enums_maps[class_name] = locked_enums
    return True

def _get_pack_from_enum_value(enum_value):
    if enum_value < 8192:
        return Pack.BASE_GAME
    return Pack((enum_value - 8192)//2048 + 1)

class TunableDynamicEnumElements(TunableList):
    __qualname__ = 'TunableDynamicEnumElements'

    def __init__(self, finalize, description='The list of elements in the dynamic enumeration.', **kwargs):
        super().__init__(TunableEnumItem(), description=description, unique_entries=True, **kwargs)
        self._finalize = finalize
        self.needs_deferring = False

    def load_etree_node(self, source=None, **kwargs):
        value = super().load_etree_node(source=source, **kwargs)
        self._finalize(*value)

class DynamicEnumMetaclass(enum.Metaclass):
    __qualname__ = 'DynamicEnumMetaclass'

    @staticmethod
    @contextlib.contextmanager
    def make_mutable(enum_type):
        old_value = enum_type._mutable
        type.__setattr__(enum_type, '_mutable', True)
        try:
            yield None
        finally:
            enum_type._mutable = old_value

    def __new__(meta, classname, bases, class_dict, export_modes=(), dynamic_entry_owner=None, **kwargs):
        enum_type = super().__new__(meta, classname, bases, class_dict, **kwargs)

        def finalize(*tuned_elements):
            if not hasattr(enum_type, '_static_index'):
                with meta.make_mutable(enum_type):
                    static_index = -1
                    for i in enum_type:
                        static_index += 1
                    enum_type._static_index = static_index
            index = enum_type._static_index + 1
            names = list(enum_type.names)
            for i in range(index, len(names)):
                item_name = names[i]
                delattr(enum_type, item_name)
                enum_type.values.remove(i)
                if item_name in enum_type.names:
                    enum_type.names.remove(item_name)
                del enum_type._to_name[i]
                del enum_type._items[item_name]
            with meta.make_mutable(enum_type):
                for element in tuned_elements:
                    enum_name = element.enum_name
                    enum_value = element.enum_value
                    if not (enum_type.partitioned and not enum_type.locked and is_entitled_pack(_get_pack_from_enum_value(enum_value))):
                        pass
                    setattr(enum_type, enum_name, type.__call__(enum_type, enum_value))
                    enum_type.names.append(enum_name)
                    enum_type.values.add(enum_value)
                    enum_type._items[enum_name] = enum_value
                    enum_type._to_name[enum_value] = enum_name

        with meta.make_mutable(enum_type):
            if dynamic_entry_owner is None:
                enum_type._elements = TunableDynamicEnumElements(finalize, export_modes=export_modes)
            enum_type._dynamic_entry_owner = dynamic_entry_owner
        return enum_type

class DynamicEnumFlagsMetaclass(DynamicEnumMetaclass):
    __qualname__ = 'DynamicEnumFlagsMetaclass'

class DynamicEnum(metaclass=DynamicEnumMetaclass):
    __qualname__ = 'DynamicEnum'

class DynamicEnumLocked(metaclass=DynamicEnumMetaclass, locked=True):
    __qualname__ = 'DynamicEnumLocked'

class DynamicEnumFlags(metaclass=DynamicEnumFlagsMetaclass, flags=True):
    __qualname__ = 'DynamicEnumFlags'

