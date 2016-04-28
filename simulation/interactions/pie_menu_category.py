from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableReference, Tunable, TunableResourceKey, TunableEnumEntry, TunableMapping, TunableTuple
from sims4.tuning.tunable_base import ExportModes
import enum
import services
import sims4.resources

class SpecialPieMenuCategoryType(enum.Int):
    __qualname__ = 'SpecialPieMenuCategoryType'
    NO_CATEGORY = 0
    MORE_CATEGORY = 1

class PieMenuCategory(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.PIE_MENU_CATEGORY)):
    __qualname__ = 'PieMenuCategory'
    INSTANCE_TUNABLES = {'_display_name': TunableLocalizedStringFactory(description='\n            Localized name of this category', export_modes=ExportModes.All), '_icon': TunableResourceKey(description='\n            Icon to be displayed in the pie menu', default=None, resource_types=sims4.resources.CompoundTypes.IMAGE, export_modes=ExportModes.All), '_collapsible': Tunable(description='\n            If enabled, when this category only has one item inside, that item will show on the pie menu without going through this category.\n            If disabled, the user will always go through this category, regardless of the number of entries within.', tunable_type=bool, needs_tuning=True, default=True, export_modes=ExportModes.All), '_parent': TunableReference(description='\n            Parent category.', manager=services.get_instance_manager(sims4.resources.Types.PIE_MENU_CATEGORY), export_modes=ExportModes.All), '_special_category': TunableEnumEntry(description='\n            Designate this category as a special category.  Most will be NO_CATEGORY.\n            ', tunable_type=SpecialPieMenuCategoryType, default=SpecialPieMenuCategoryType.NO_CATEGORY, export_modes=ExportModes.All), '_display_priority': Tunable(description='\n            The display priority of this category.\n            ', tunable_type=int, default=1, export_modes=ExportModes.All), 'mood_overrides': TunableMapping(description='\n            If sim matches mood, tooltip and display name of category will\n            be updated with tuned values.\n            ', key_type=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.MOOD)), value_type=TunableTuple(name_override=TunableLocalizedStringFactory(description='\n                   Localized name of this category\n                   '), tooltip=TunableLocalizedStringFactory(description='\n                   Tooltip for the new category.\n                   '), export_class_name='text_overrides'), key_value_type=None, key_name='mood', value_name='override_data', tuple_name='mood_to_override_data', export_modes=(ExportModes.ClientBinary,))}

    @classmethod
    def get_display_name(cls):
        return cls._display_name

    @classmethod
    def get_icon(cls):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return cls._icon

    @classmethod
    def get_collapsible(cls):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return cls._collapsible

    @classmethod
    def get_parent(cls):
        return cls._parent

    @classmethod
    def get_special_status(cls):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return cls._special_category

