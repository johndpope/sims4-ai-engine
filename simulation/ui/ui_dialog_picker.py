from protocolbuffers import Dialog_pb2, Consts_pb2, UI_pb2
from distributor.ops import GenericProtocolBufferOp
from distributor.shared_messages import build_icon_info_msg
from distributor.system import Distributor
from objects.slots import SlotType
from sims4.localization import LocalizationHelperTuning, TunableLocalizedString, TunableLocalizedStringFactory
from sims4.tuning.tunable import TunableEnumEntry, TunableList, OptionalTunable, Tunable, TunableResourceKey, TunableVariant, TunableTuple, HasTunableSingletonFactory, AutoFactoryInit, TunableRange
from singletons import DEFAULT
from statistics.skill import Skill
from ui.ui_dialog import UiDialogOkCancel
import build_buy
import distributor
import enum
import services
import sims4.log
import tag
logger = sims4.log.Logger('Dialog')

class ObjectPickerType(enum.Int, export=False):
    __qualname__ = 'ObjectPickerType'
    RECIPE = 1
    INTERACTION = 2
    SIM = 3
    OBJECT = 4
    PIE_MENU = 5
    CAREER = 6
    OUTFIT = 7
    PURCHASE = 8
    LOT = 9
    MAP_VIEW = 10

class ObjectPickerTuningFlags(enum.IntFlags):
    __qualname__ = 'ObjectPickerTuningFlags'
    NONE = 0
    RECIPE = 1
    INTERACTION = 2
    SIM = 4
    OBJECT = 8
    PIE_MENU = 16
    CAREER = 32
    OUTFIT = 64
    PURCHASE = 128
    LOT = 256
    MAP_VIEW = 512
    ALL = RECIPE | INTERACTION | SIM | OBJECT | PIE_MENU | CAREER | OUTFIT | PURCHASE | LOT | MAP_VIEW

class RowMapType(enum.Int):
    __qualname__ = 'RowMapType'
    NAME = 0
    ICON = 1
    SKILL_LEVEL = 2
    PRICE = 3
    INGREDIENTS = 4

ROW_MAP_NAMES = ['name', 'icon', 'skill_level', 'price', 'ingredients']

class MaxSelectableType(enum.Int):
    __qualname__ = 'MaxSelectableType'
    NONE = 1
    STATIC = 2
    SLOT_COUNT = 3

class PickerColumn(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'PickerColumn'

    class ColumnType(enum.Int):
        __qualname__ = 'PickerColumn.ColumnType'
        TEXT = 1
        ICON = 2
        ICON_AND_TEXT = 3
        INGREDIENT_LIST = 4

    FACTORY_TUNABLES = {'column_type': TunableEnumEntry(description='\n            The type of column.\n            ', tunable_type=ColumnType, default=ColumnType.ICON_AND_TEXT), 'label': OptionalTunable(description='\n            If enabled, the text to show on the column. \n            ', tunable=TunableLocalizedString()), 'icon': OptionalTunable(description='\n            If enabled, the icon to show on the column.\n            ', tunable=TunableResourceKey(resource_types=sims4.resources.CompoundTypes.IMAGE, default=None)), 'tooltip': OptionalTunable(description='\n            If enabled, the tooltip text for the column.\n            ', tunable=TunableLocalizedString()), 'width': Tunable(description='\n            The width of the column.\n            ', tunable_type=float, default=100), 'sortable': Tunable(description='\n            Whether or not we can sort the column.\n            ', tunable_type=bool, default=True), 'column_data_name': TunableEnumEntry(description='\n            The name of the data field inside the row to show in this column,\n            name/skill/price etc.\n            ', tunable_type=RowMapType, default=RowMapType.NAME), 'column_icon_name': TunableEnumEntry(description='\n            The name of the icon field inside the row to show in this column,\n            most likely should just be icon.\n            ', tunable_type=RowMapType, default=RowMapType.ICON)}

    def populate_protocol_buffer(self, column_data):
        column_data.type = self.column_type
        if self.column_data_name is not None:
            column_data.column_data_name = ROW_MAP_NAMES[self.column_data_name]
        if self.column_icon_name is not None:
            column_data.column_icon_name = ROW_MAP_NAMES[self.column_icon_name]
        if self.label is not None:
            column_data.label = self.label
        if self.icon is not None:
            column_data.icon.type = self.icon.type
            column_data.icon.group = self.icon.group
            column_data.icon.instance = self.icon.instance
        if self.tooltip is not None:
            column_data.tooltip = self.tooltip
        column_data.width = self.width
        column_data.sortable = self.sortable

    def __format__(self, fmt):
        dump_str = 'type: {}, label:{}, icon:{}, tooltip:{}, width:{}, sortable:{}'.format(self.column_type, self.label, self.icon, self.tooltip, self.width, self.sortable)
        return dump_str

class BasePickerRow:
    __qualname__ = 'BasePickerRow'

    def __init__(self, option_id=None, is_enable=True, name=None, icon=None, row_description=None, row_tooltip=None, tag=None, icon_info=None, pie_menu_influence_by_active_mood=False):
        self.option_id = option_id
        self.tag = tag
        self.is_enable = is_enable
        self.name = name
        self.icon = icon
        self.row_description = row_description
        self.row_tooltip = row_tooltip
        self.icon_info = icon_info
        self._pie_menu_influence_by_active_mood = pie_menu_influence_by_active_mood

    def populate_protocol_buffer(self, base_row_data, name_override=DEFAULT):
        base_row_data.option_id = self.option_id
        base_row_data.is_enable = bool(self.is_enable)
        if name_override is DEFAULT:
            name_override = self.name
        if name_override is not None:
            base_row_data.name = name_override
        if self.icon is not None:
            base_row_data.icon.type = self.icon.type
            base_row_data.icon.group = self.icon.group
            base_row_data.icon.instance = self.icon.instance
        if self.icon_info is not None:
            build_icon_info_msg(self.icon_info, None, base_row_data.icon_info)
        if self.row_description is not None:
            base_row_data.description = self.row_description
        if self.row_tooltip:
            base_row_data.tooltip = self.row_tooltip()

    @property
    def available_as_pie_menu(self):
        return True

    @property
    def pie_menu_category(self):
        pass

    @property
    def pie_menu_influence_by_active_mood(self):
        return self._pie_menu_influence_by_active_mood

    def __repr__(self):
        return str(self.tag)

    def __format__(self, fmt):
        show_name = ''
        if self.tag is not None:
            show_name = '[{}]\t\t\t'.format(self.tag.__class__.__name__)
        dump_str = ' {}, enable:{}, '.format(show_name, self.is_enable)
        return dump_str

class RecipePickerRow(BasePickerRow):
    __qualname__ = 'RecipePickerRow'

    def __init__(self, price=0, skill_level=0, linked_recipe=None, display_name=DEFAULT, ingredients=None, price_with_ingredients=0, mtx_id=None, **kwargs):
        super().__init__(**kwargs)
        self.price = price
        self.skill_level = skill_level
        self.linked_recipe = linked_recipe
        self.linked_option_ids = []
        self.display_name = display_name
        self.visible_as_subrow = self.tag.visible_as_subrow
        self._pie_menu_category = self.tag.base_recipe_category
        self.ingredients = ingredients
        self.price_with_ingredients = price_with_ingredients
        self.mtx_id = mtx_id

    def populate_protocol_buffer(self, recipe_row_data):
        super().populate_protocol_buffer(recipe_row_data.base_data)
        if self.display_name is not DEFAULT:
            recipe_row_data.serving_display_name = self.display_name
        if self.price != 0:
            price = abs(self.price)
            recipe_row_data.price = int(price)
        recipe_row_data.skill_level = int(self.skill_level)
        for linked_id in self.linked_option_ids:
            recipe_row_data.linked_option_ids.append(linked_id)
        recipe_row_data.visible_as_subrow = self.visible_as_subrow
        recipe_row_data.price_with_ingredients = self.price_with_ingredients
        if self.ingredients:
            for ingredient in self.ingredients:
                ingredient_data = recipe_row_data.ingredients.add()
                ingredient_data.ingredient_name = ingredient.ingredient_name
                ingredient_data.in_inventory = ingredient.is_in_inventory
        if self.mtx_id is not None:
            recipe_row_data.mtx_id = self.mtx_id

    @property
    def available_as_pie_menu(self):
        return self.visible_as_subrow

    @property
    def pie_menu_category(self):
        return self._pie_menu_category

    def __format__(self, fmt):
        super_dump_str = super().__format__(fmt)
        dump_str = 'RecipePickerRow({}, skill:{}, price:{}, linked rows[{}])'.format(super_dump_str, self.skill_level, self.price, len(self.linked_option_ids))
        return dump_str

class SimPickerRow(BasePickerRow):
    __qualname__ = 'SimPickerRow'

    def __init__(self, sim_id=None, **kwargs):
        super().__init__(**kwargs)
        self.sim_id = sim_id

    def populate_protocol_buffer(self, sim_row_data):
        super().populate_protocol_buffer(sim_row_data.base_data)
        if self.sim_id is not None:
            sim_row_data.sim_id = self.sim_id

    def __format__(self, fmt):
        dump_str = 'SimPickerRow(Sim id:{})'.format(self.sim_id)
        return dump_str

class ObjectPickerRow(BasePickerRow):
    __qualname__ = 'ObjectPickerRow'

    def __init__(self, object_id=None, def_id=None, count=1, **kwargs):
        super().__init__(**kwargs)
        self.object_id = object_id
        self.def_id = def_id
        self.count = count

    def populate_protocol_buffer(self, object_row_data):
        super().populate_protocol_buffer(object_row_data.base_data)
        if self.object_id is not None:
            object_row_data.object_id = self.object_id
        if self.def_id is not None:
            object_row_data.def_id = self.def_id
        object_row_data.count = self.count

    def __format__(self, fmt):
        super_dump_str = super().__format__(fmt)
        dump_str = 'ObjectPickerRow({}, object_id:{}, def_id:{})'.format(super_dump_str, self.object_id, self.def_id)
        return dump_str

class CareerPickerRow(BasePickerRow):
    __qualname__ = 'CareerPickerRow'

    def __init__(self, work_days=[], **kwargs):
        super().__init__(**kwargs)
        self.work_days = work_days

    def populate_protocol_buffer(self, career_row_data):
        super().populate_protocol_buffer(career_row_data.base_data)

    def __format__(self, fmt):
        super_dump_str = super().__format__(fmt)
        dump_str = 'CareerPickerRow({})'.format(super_dump_str)
        return dump_str

class OutfitPickerRow(BasePickerRow):
    __qualname__ = 'OutfitPickerRow'

    def __init__(self, buff_id=None, **kwargs):
        super().__init__(**kwargs)
        self.buff_id = buff_id

    def populate_protocol_buffer(self, outfit_row_data):
        super().populate_protocol_buffer(outfit_row_data.base_data)
        if self.buff_id is not None:
            outfit_row_data.buff_id = self.buff_id

    def __format__(self, fmt):
        super_dump_str = super().__format__(fmt)
        dump_str = 'OutfitPickerRow({})'.format(super_dump_str)
        return dump_str

class PurchasePickerRow(BasePickerRow):
    __qualname__ = 'PurchasePickerRow'

    def __init__(self, def_id=0, num_owned=0, tags=(), **kwargs):
        super().__init__(**kwargs)
        self.def_id = def_id
        self.num_owned = num_owned
        self.tags = tags

    def populate_protocol_buffer(self, purchase_row_data):
        super().populate_protocol_buffer(purchase_row_data.base_data)
        purchase_row_data.def_id = self.def_id
        purchase_row_data.num_owned = self.num_owned
        purchase_row_data.tag_list.extend(self.tags)

    def __format__(self, fmt):
        super_dump_str = super().__format__(fmt)
        dump_str = 'PurchasePickerRow({}, def_id: {}, num_owned: {})'.format(super_dump_str, self.def_id, self.num_owned)
        return dump_str

class LotPickerRow(BasePickerRow):
    __qualname__ = 'LotPickerRow'

    def __init__(self, zone_data, **kwargs):
        super().__init__(**kwargs)
        self.zone_id = zone_data.zone_id
        self.name = zone_data.name
        self.world_id = zone_data.world_id
        self.lot_template_id = zone_data.lot_template_id
        self.lot_description_id = zone_data.lot_description_id
        venue_manager = services.get_instance_manager(sims4.resources.Types.VENUE)
        venue_type_id = build_buy.get_current_venue(zone_data.zone_id)
        if venue_type_id is not None:
            venue_type = venue_manager.get(venue_type_id)
            if venue_type is not None:
                self.venue_type_name = venue_type.display_name
        householdProto = services.get_persistence_service().get_household_proto_buff(zone_data.household_id)
        self.household_name = householdProto.name if householdProto is not None else None

    def populate_protocol_buffer(self, lot_row_data):
        super().populate_protocol_buffer(lot_row_data.base_data, name_override=LocalizationHelperTuning.get_raw_text(self.name))
        logger.assert_raise(self.zone_id is not None, 'No zone_id passed to lot picker row', owner='nbaker')
        lot_row_data.lot_info_item.zone_id = self.zone_id
        if self.name is not None:
            lot_row_data.lot_info_item.name = self.name
        if self.world_id is not None:
            lot_row_data.lot_info_item.world_id = self.world_id
        if self.lot_template_id is not None:
            lot_row_data.lot_info_item.lot_template_id = self.lot_template_id
        if self.lot_description_id is not None:
            lot_row_data.lot_info_item.lot_description_id = self.lot_description_id
        if self.venue_type_name is not None:
            lot_row_data.lot_info_item.venue_type_name = self.venue_type_name
        if self.household_name is not None:
            lot_row_data.lot_info_item.household_name = self.household_name

    def __format__(self, fmt):
        dump_str = 'LotPickerRow(Zone id:{})'.format(self.zone_id)
        return dump_str

class UiDialogObjectPicker(UiDialogOkCancel):
    __qualname__ = 'UiDialogObjectPicker'
    FACTORY_TUNABLES = {'max_selectable': TunableVariant(description='\n            Method of determining maximum selectable items.\n            ', static_count=TunableTuple(description='\n                static maximum selectable\n                ', number_selectable=TunableRange(description='\n                    Maximum items selectable\n                    ', tunable_type=int, default=1, minimum=1), locked_args={'max_type': MaxSelectableType.STATIC}), unlimited=TunableTuple(description='\n                Unlimited Selectable\n                ', locked_args={'max_type': MaxSelectableType.NONE}), slot_based_count=TunableTuple(description='\n                maximum selectable based on empty/full slots on target\n                ', slot_type=SlotType.TunableReference(description=' \n                    A particular slot type to be tested.\n                    '), require_empty=Tunable(description='\n                    based on empty slots\n                    ', tunable_type=bool, default=True), delta=Tunable(description='\n                    offset from number of empty slots\n                    ', tunable_type=int, default=0), locked_args={'max_type': MaxSelectableType.SLOT_COUNT}), default='static_count'), 'min_selectable': TunableRange(description='\n           The minimum number of items that must be selected to treat the\n           dialog as accepted and push continuations. If 0, then multi-select\n           sim pickers will push continuations even if no items are selected.\n           ', tunable_type=int, default=1, minimum=0), 'is_sortable': Tunable(description='\n           Should list of items be presented sorted\n           ', tunable_type=bool, default=False), 'hide_row_description': Tunable(description='\n            If set to True, we will not show the row description for this picker dialog.\n            ', tunable_type=bool, default=False)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.picker_rows = []
        self.picked_results = []
        self.target_sim = None
        self.target = None
        self.ingredient_check = None

    def add_row(self, row):
        if row is None:
            return
        if not self._validate_row(row):
            return
        if row.option_id is None:
            row.option_id = len(self.picker_rows)
        self._customize_add_row(row)
        self.picker_rows.append(row)

    def _validate_row(self, row):
        raise NotImplementedError

    def _customize_add_row(self, row):
        pass

    def set_target_sim(self, target_sim):
        self.target_sim = target_sim

    def set_target(self, target):
        self.target = target

    def pick_results(self, picked_results=[], ingredient_check=None):
        option_ids = [picker_row.option_id for picker_row in self.picker_rows]
        for result in picked_results:
            while result not in option_ids:
                logger.error('Player choose {0} out of provided {1} for dialog {2}', picked_results, option_ids, self)
                return False
        self.picked_results = picked_results
        self.ingredient_check = ingredient_check
        return True

    def get_result_rows(self):
        return [row for row in self.picker_rows if row.option_id in self.picked_results]

    def get_result_tags(self):
        return [row.tag for row in self.get_result_rows()]

    def get_single_result_tag(self):
        tags = self.get_result_tags()
        if not tags:
            return
        if len(tags) != 1:
            raise ValueError('Multiple selections not supported')
        return tags[0]

    def build_msg(self, **kwargs):
        msg = super().build_msg(**kwargs)
        msg.dialog_type = Dialog_pb2.UiDialogMessage.OBJECT_PICKER
        msg.picker_data = self.build_object_picker()
        return msg

    def _build_customize_picker(self, picker_data):
        raise NotImplementedError

    def build_object_picker(self):
        picker_data = Dialog_pb2.UiDialogPicker()
        picker_data.title = self._build_localized_string_msg(self.title)
        if self.picker_type is not None:
            picker_data.type = self.picker_type
        if self.max_selectable:
            if self.max_selectable.max_type == MaxSelectableType.STATIC:
                picker_data.max_selectable = self.max_selectable.number_selectable
                picker_data.multi_select = True
            elif self.max_selectable.max_type == MaxSelectableType.SLOT_COUNT:
                if self.target is not None:
                    get_slots = self.target.get_runtime_slots_gen(slot_types={self.max_selectable.slot_type}, bone_name_hash=None)
                    if self.max_selectable.require_empty:
                        picker_data.max_selectable = sum(1 for slot in get_slots if slot.empty)
                    else:
                        picker_data.max_selectable = sum(1 for slot in get_slots if not slot.empty)
                    picker_data.multi_select = True
                else:
                    logger.error('attempting to use slot based picker without a target object for dialog: {}', self, owner='nbaker')
                    picker_data.multi_select = True
            else:
                picker_data.multi_select = True
        else:
            picker_data.multi_select = True
        picker_data.owner_sim_id = self.owner.sim_id
        if self.target_sim is not None:
            picker_data.target_sim_id = self.target_sim.sim_id
        picker_data.is_sortable = self.is_sortable
        picker_data.hide_row_description = self.hide_row_description
        self._build_customize_picker(picker_data)
        return picker_data

class UiRecipePicker(UiDialogObjectPicker):
    __qualname__ = 'UiRecipePicker'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, column_sort_priorities=None, picker_columns=None, **kwargs):
        if column_sort_priorities is not None:
            length = len(picker_columns)
            if any(v >= length for v in column_sort_priorities):
                logger.error('UiRecipePicker dialog in {} has invalid column sort priority. Valid values are 0-{}', instance_class, length - 1, owner='cjiang')

    FACTORY_TUNABLES = {'skill': OptionalTunable(Skill.TunableReference(description='\n            The skill associated with the picker dialog.\n            ')), 'picker_columns': TunableList(description='\n            List of the column info\n            ', tunable=PickerColumn.TunableFactory()), 'column_sort_priorities': OptionalTunable(description='\n            If enabled, specifies column sorting.\n            ', tunable=TunableList(description='\n                The priority index for the column (column numbers are 0-based\n                index. So, if you wish to use the first column the id is 0).\n                ', tunable=int)), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.picker_type = ObjectPickerType.RECIPE

    def _customize_add_row(self, row):
        for picker_row in self.picker_rows:
            self._build_row_links(row, picker_row)
            self._build_row_links(picker_row, row)

    def _validate_row(self, row):
        return isinstance(row, RecipePickerRow)

    @staticmethod
    def _build_row_links(row1, row2):
        if row1.linked_recipe is not None and row1.linked_recipe is row2.tag:
            row2.linked_option_ids.append(row1.option_id)

    def _build_customize_picker(self, picker_data):
        for column in self.picker_columns:
            column_data = picker_data.recipe_picker_data.column_list.add()
            column.populate_protocol_buffer(column_data)
        if self.skill is not None:
            picker_data.recipe_picker_data.skill_id = self.skill.guid64
        if self.column_sort_priorities is not None:
            picker_data.recipe_picker_data.column_sort_list.extend(self.column_sort_priorities)
        for row in self.picker_rows:
            row_data = picker_data.recipe_picker_data.row_data.add()
            row.populate_protocol_buffer(row_data)

class UiSimPicker(UiDialogObjectPicker):
    __qualname__ = 'UiSimPicker'
    FACTORY_TUNABLES = {'should_show_names': Tunable(description="\n                If true then we will show the sim's names in the picker.\n                ", tunable_type=bool, default=True)}

    def __init__(self, *args, sim_filter=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.picker_type = ObjectPickerType.SIM

    def _validate_row(self, row):
        return isinstance(row, SimPickerRow)

    def _build_customize_picker(self, picker_data):
        for row in self.picker_rows:
            row_data = picker_data.sim_picker_data.row_data.add()
            row.populate_protocol_buffer(row_data)
        picker_data.sim_picker_data.should_show_names = self.should_show_names

class UiObjectPicker(UiDialogObjectPicker):
    __qualname__ = 'UiObjectPicker'

    class UiObjectPickerObjectPickerType(enum.Int):
        __qualname__ = 'UiObjectPicker.UiObjectPickerObjectPickerType'
        INTERACTION = ObjectPickerType.INTERACTION
        OBJECT = ObjectPickerType.OBJECT
        PIE_MENU = ObjectPickerType.PIE_MENU

    FACTORY_TUNABLES = {'picker_type': TunableEnumEntry(description='\n            Object picker type for the picker dialog.\n            ', tunable_type=UiObjectPickerObjectPickerType, default=UiObjectPickerObjectPickerType.OBJECT)}

    def _validate_row(self, row):
        return isinstance(row, ObjectPickerRow)

    def _build_customize_picker(self, picker_data):
        for row in self.picker_rows:
            row_data = picker_data.object_picker_data.row_data.add()
            row.populate_protocol_buffer(row_data)

class UiCareerPicker(UiDialogObjectPicker):
    __qualname__ = 'UiCareerPicker'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.picker_type = ObjectPickerType.CAREER

    def _validate_row(self, row):
        return isinstance(row, CareerPickerRow)

    def _build_customize_picker(self, picker_data):
        for row in self.picker_rows:
            row_data = picker_data.career_picker_data.row_data.add()
            row.populate_protocol_buffer(row_data)

class UiOutfitPicker(UiDialogObjectPicker):
    __qualname__ = 'UiOutfitPicker'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.picker_type = ObjectPickerType.OUTFIT

    def _validate_row(self, row):
        return isinstance(row, OutfitPickerRow)

    def _build_customize_picker(self, picker_data):
        for row in self.picker_rows:
            row_data = picker_data.outfit_picker_data.row_data.add()
            row.populate_protocol_buffer(row_data)

class UiPurchasePicker(UiDialogObjectPicker):
    __qualname__ = 'UiPurchasePicker'
    FACTORY_TUNABLES = {'categories': TunableList(description='\n            A list of categories that will be displayed in the picker.\n            ', tunable=TunableTuple(description='\n                Tuning for a single category in the picker.\n                ', tag=TunableEnumEntry(description='\n                    A single tag used for filtering items.  If an item\n                    in the picker has this tag then it will be displayed\n                    in this category.\n                    ', tunable_type=tag.Tag, default=tag.Tag.INVALID), icon=TunableResourceKey(description='\n                    Icon that represents this category.\n                    ', default=None, resource_types=sims4.resources.CompoundTypes.IMAGE), tooltip=TunableLocalizedString(description='\n                    A localized string for the tooltip of the category.\n                    ')))}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.picker_type = ObjectPickerType.PURCHASE
        self.object_id = 0
        self.show_description = 0
        self.mailman_purchase = False

    def _validate_row(self, row):
        return isinstance(row, PurchasePickerRow)

    def _build_customize_picker(self, picker_data):
        picker_data.shop_picker_data.object_id = self.object_id
        picker_data.shop_picker_data.show_description = self.show_description
        picker_data.shop_picker_data.mailman_purchase = self.mailman_purchase
        for category in self.categories:
            category_data = picker_data.shop_picker_data.categories.add()
            category_data.tag_type = category.tag
            build_icon_info_msg((category.icon, None), None, category_data.icon_info)
            category_data.description = category.tooltip
        for row in self.picker_rows:
            row_data = picker_data.shop_picker_data.row_data.add()
            row.populate_protocol_buffer(row_data)

class UiLotPicker(UiDialogObjectPicker):
    __qualname__ = 'UiLotPicker'

    def __init__(self, *args, lot_filter=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.picker_type = ObjectPickerType.LOT

    def _validate_row(self, row):
        return isinstance(row, LotPickerRow)

    def _build_customize_picker(self, picker_data):
        for row in self.picker_rows:
            row_data = picker_data.lot_picker_data.row_data.add()
            row.populate_protocol_buffer(row_data)

class UiMapViewPicker(UiDialogObjectPicker):
    __qualname__ = 'UiMapViewPicker'

    def __init__(self, *args, traveling_sims=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.picker_type = ObjectPickerType.MAP_VIEW
        self.traveling_sims = traveling_sims

    def _validate_row(self, row):
        return isinstance(row, LotPickerRow)

    def distribute_dialog(self, _, dialog_msg):
        distributor_inst = Distributor.instance()
        op = distributor.shared_messages.create_message_op(dialog_msg, Consts_pb2.MSG_SHOW_MAP_VIEW)
        owner = self.owner
        if owner is not None:
            distributor_inst.add_op(owner, op)
        else:
            distributor_inst.add_op_with_no_owner(op)

    def build_msg(self, additional_tokens=(), icon_override=DEFAULT, event_id=None, **kwargs):
        msg = UI_pb2.ShowMapView()
        msg.actor_sim_id = self.owner.id
        if self.traveling_sims is not None:
            msg.traveling_sim_ids.extend([sim.id for sim in self.traveling_sims])
        msg.lot_ids_for_travel.extend([row.zone_id for row in self.picker_rows])
        msg.dialog_id = self.dialog_id
        return msg

class TunablePickerDialogVariant(TunableVariant):
    __qualname__ = 'TunablePickerDialogVariant'

    def __init__(self, description='A tunable picker dialog variant.', available_picker_flags=ObjectPickerTuningFlags.ALL, dialog_locked_args={}, **kwargs):
        if available_picker_flags & ObjectPickerTuningFlags.SIM:
            kwargs['sim_picker'] = UiSimPicker.TunableFactory(locked_args=dialog_locked_args)
        if available_picker_flags & (ObjectPickerTuningFlags.OBJECT | ObjectPickerTuningFlags.INTERACTION | ObjectPickerTuningFlags.PIE_MENU):
            kwargs['object_picker'] = UiObjectPicker.TunableFactory(locked_args=dialog_locked_args)
        if available_picker_flags & ObjectPickerTuningFlags.CAREER:
            kwargs['career_picker'] = UiCareerPicker.TunableFactory(locked_args=dialog_locked_args)
        if available_picker_flags & ObjectPickerTuningFlags.OUTFIT:
            kwargs['outfit_picker'] = UiOutfitPicker.TunableFactory(locked_args=dialog_locked_args)
        if available_picker_flags & ObjectPickerTuningFlags.RECIPE:
            kwargs['recipe_picker'] = UiRecipePicker.TunableFactory(locked_args=dialog_locked_args)
        if available_picker_flags & ObjectPickerTuningFlags.PURCHASE:
            kwargs['purchase_picker'] = UiPurchasePicker.TunableFactory(locked_args=dialog_locked_args)
        if available_picker_flags & ObjectPickerTuningFlags.LOT:
            kwargs['lot_picker'] = UiLotPicker.TunableFactory(locked_args=dialog_locked_args)
        if available_picker_flags & ObjectPickerTuningFlags.MAP_VIEW:
            kwargs['map_view_picker'] = UiMapViewPicker.TunableFactory(locked_args=dialog_locked_args)
        super().__init__(description=description, **kwargs)

