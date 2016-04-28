import collections
import operator
from protocolbuffers import UI_pb2 as ui_protocols
from protocolbuffers import SimObjectAttributes_pb2 as protocols
from protocolbuffers.Localization_pb2 import LocalizedStringToken
from date_and_time import TimeSpan
from distributor.rollback import ProtocolBufferRollback
from event_testing import test_events
from interactions import ParticipantType
from interactions.utils.interaction_elements import XevtTriggeredElement
from objects.components import Component
from objects.components.inventory_item import ItemLocation
from objects.components.spawner_component import SpawnerTuning
from objects.components.state import ObjectState, ObjectStateValue, TunableStateValueReference
from objects.components.tooltip_component import TooltipProvidingComponentMixin
from objects.components.types import GARDENING_COMPONENT
from objects.slots import SlotType
from objects.system import create_object
from placement import FindGoodLocationContext, find_good_location, FGLSearchFlagsDefault, FGLSearchFlag
from scheduler import TunableWeeklyScheduleFactory
from sims4 import random
from sims4.localization import TunableLocalizedString, TunableLocalizedStringFactory, LocalizationHelperTuning
from sims4.tuning.dynamic_enum import DynamicEnumFlags
from sims4.tuning.geometric import TunableCurve
from sims4.tuning.tunable import HasTunableFactory, HasTunableSingletonFactory, TunableEnumEntry, AutoFactoryInit, Tunable, TunableList, TunableVariant, TunableReference, TunableRange, TunableInterval, OptionalTunable, TunableTuple, TunableSet, TunablePercent, TunableMapping, TunableEnumFlags
from sims4.utils import classproperty, flexmethod
from statistics.commodity import Commodity
from statistics.statistic import Statistic
import alarms
import enum
import objects.components.types
import routing
import services
import sims4.log
import sims4.resources
logger = sims4.log.Logger('Gardening', default_owner='camilogarcia')

class ParentalContribution(enum.Int):
    __qualname__ = 'ParentalContribution'
    MINIMUM = 4
    AVERAGE = 3
    MAXIMUM = 5

class MassUnit(enum.Int):
    __qualname__ = 'MassUnit'
    MILLIGRAMS = 1
    GRAMS = 2

class SplicingFamily(DynamicEnumFlags):
    __qualname__ = 'SplicingFamily'
    DEFAULT = 1

class GardeningTuning:
    __qualname__ = 'GardeningTuning'

    class _Inheritance(HasTunableSingletonFactory, AutoFactoryInit):
        __qualname__ = 'GardeningTuning._Inheritance'

        @staticmethod
        def _verify_tunable_callback(instance_class, tunable_name, source, value):
            if not value.inherit_from_mother and not value.inherit_from_father:
                raise ValueError('Must inherit from at least one parent.')

        FACTORY_TUNABLES = {'inherited_state': ObjectState.TunableReference(description='\n            Controls the state value that will be inherited by offspring.\n            '), 'inherit_from_mother': Tunable(description="\n            If checked, the mother's (root stock's) state value and fitness will\n            be considered when deciding what state value the child should\n            inherit.\n            ", tunable_type=bool, needs_tuning=True, default=True), 'inherit_from_father': Tunable(description="\n            If checked, the father's (a spliced fruit's genes) state value and\n            fitness will be considered when deciding what state value the child\n            should inherit.  In the case a plant is spawning the type of fruit\n            it grew from, this will be the same as the mother's contribution.\n            ", tunable_type=bool, needs_tuning=True, default=True), 'inheritance_chance': TunablePercent(description="\n            The chance the offspring will inherit this state value from its\n            parents at all.  If the check doesn't pass, the default value for\n            the state will be used.\n            ", default=1), 'verify_tunable_callback': _verify_tunable_callback}

    def get_inherited_value(self, mother, father):
        raise NotImplementedError()

    class LamarkianInheritance(_Inheritance):
        __qualname__ = 'GardeningTuning.LamarkianInheritance'
        CALCULATIONS = {ParentalContribution.MAXIMUM: max, ParentalContribution.MINIMUM: min, ParentalContribution.AVERAGE: lambda l: sum(l)/len(l)}
        FACTORY_TUNABLES = {'_calculation': TunableEnumEntry(ParentalContribution, ParentalContribution.MINIMUM, needs_tuning=True), 'fitness_stat': Statistic.TunableReference(description='\n            This statistic is used as the x-value on the fitness curve.\n            '), 'fitness_curve_maximum': TunableCurve(description='\n            This curve maps fitness stat values to maximum state changes.\n            '), 'fitness_curve_minimum': TunableCurve(description='\n            This curve maps fitness stat values to minimum state changes.\n            ')}

        @property
        def calculation(self):
            return self.CALCULATIONS[self._calculation]

        def get_inherited_value(self, mother, father):
            values = []
            indeces = []
            if self.inherit_from_mother:
                values.append(mother.get_stat_value(self.fitness_stat))
                inherited_state_value = mother.get_state(self.inherited_state)
                indeces.append(self.inherited_state.values.index(inherited_state_value))
            if self.inherit_from_father:
                values.append(father.get_stat_value(self.fitness_stat))
                inherited_state_value = father.get_state(self.inherited_state)
                indeces.append(self.inherited_state.values.index(inherited_state_value))
            fitness_value = self.calculation(values)
            max_delta = self.fitness_curve_maximum.get(fitness_value)
            min_delta = self.fitness_curve_minimum.get(fitness_value)
            delta = round(sims4.random.uniform(min_delta, max_delta))
            index = self.calculation(indeces) + delta
            index = sims4.math.clamp(0, index, len(self.inherited_state.values))
            return self.inherited_state.values[index]

    class MendelianInheritance(_Inheritance):
        __qualname__ = 'GardeningTuning.MendelianInheritance'

        def get_inherited_value(self, mother, father):
            possibilities = set()
            if self.inherit_from_mother:
                possibilities.add(mother.get_state(self.inherited_state))
            if self.inherit_from_father:
                possibilities.add(father.get_state(self.inherited_state))
            if not possibilities:
                possibilities.update(self.inherited_state.values)
            return sims4.random.random.choice(list(possibilities))

    PLANT_GENETICS = TunableList(description='\n        Instructions for transmitting traits to later generations. These are\n        applied each time a fruit is generated by a plant.\n        ', tunable=TunableVariant(lamarkian_inheritance=LamarkianInheritance.TunableFactory(), mendelian_inheritance=MendelianInheritance.TunableFactory()))

    @classproperty
    def INHERITED_STATES(cls):
        return [inheritance.inherited_state for inheritance in cls.PLANT_GENETICS]

    SPONTANEOUS_GERMINATION_COMMODITY = Commodity.TunableReference()
    SPONTANEOUS_GERMINATION_COMMODITY_VARIANCE = TunableRange(description='\n        Max variance to apply when the spawn commodity is reset.  This helps\n        plants all not to sprout from seeds at the same time.\n        ', tunable_type=int, default=10, minimum=0)
    SCALE_COMMODITY = Commodity.TunableReference()
    SCALE_VARIANCE = TunableInterval(description="\n        Control how much the size of child fruit can vary from its father's\n        size.\n        ", tunable_type=float, default_lower=0.8, default_upper=1.2)
    SCALE_INFO_NAME = TunableLocalizedString()
    SCALE_INFO_UNIT_FORMATS = TunableMapping(key_type=TunableEnumEntry(MassUnit, MassUnit.GRAMS), value_type=TunableLocalizedStringFactory())
    STATES_WITH_STATUS_ICONS = TunableList(description='\n        The list of object states whose icons will be reflected in the gardening\n        tooltip on each plant details.  These refer to the sub icons represented\n        on the tooltip.\n        ', tunable=ObjectState.TunableReference())
    STATE_MAIN_ICON = ObjectState.TunableReference(description="\n        Object state which will represent the main icon of the gardening\n        tooltip.  This state doesn't get modified by interactions but its \n        calculated whenever the tooltip will be generated, using the states\n        tuned on STATES_WITH_STATUS_ICONS.\n        ")
    STATES_WITH_ADDITIONAL_INFO = TunableList(description="\n        The list of object states whose name and state value name will be\n        reflected in the gardening tooltip's additional information section.\n        ", tunable=ObjectState.TunableReference())
    SHOOT_DEFINITION = TunableReference(description='\n        The object definition to use when creating Shoot objects for the\n        splicing system.\n        ', manager=services.definition_manager())
    SHOOT_STATE_VALUE = ObjectStateValue.TunableReference(description="\n        The state value all Shoot objects will have.  Remember to add this as\n        the default value for a state in the Shoot's state component tuning.\n        ")
    WITHERED_STATE_VALUE = ObjectStateValue.TunableReference(description='\n        The state value when a plant is withered.\n        ')
    DISABLE_DETAILS_STATE_VALUES = TunableList(description='\n            List of object state values where the gardening details should not \n            be shown.  This is for cases like Wild plants where we dont want\n            details that will not be used.\n            ', tunable=ObjectStateValue.TunableReference(description='\n                The state that will disable the plant additional information.\n                '))
    DISABLE_TOOLTIP_STATE_VALUES = TunableList(description='\n            List of object state values where the gardening object will disable \n            its tooltip.\n            ', tunable=ObjectStateValue.TunableReference(description='\n                The state that will disable the object tooltip.\n                '))
    SPLICED_PLANT_NAME = TunableLocalizedStringFactory(description='\n        Localized name to be set when a plant is spliced. \n        ')
    SPLICED_PLANT_DESCRIPTION = TunableLocalizedStringFactory(description='\n        Localized factory that will receive two fruit names and concatenate \n        them using and in between.\n        e.g. {0.String} and {1.String} \n        ')
    SPLICED_STATE_VALUE = ObjectStateValue.TunableReference(description='\n        The state that will mean this plant has been already spliced.  \n        ')
    PICKUP_STATE_MAPPING = TunableMapping(description='\n        Mapping that will set a state that should be set on the fruit when \n        its picked up, depending on a state fruit is currently in.\n        ', key_type=ObjectStateValue.TunableReference(), value_type=ObjectStateValue.TunableReference())
    GARDENING_SLOT = TunableReference(description='\n        Slot type used by the gardening system to create its fruit.\n        ', manager=services.get_instance_manager(sims4.resources.Types.SLOT_TYPE))

    @classmethod
    def get_spliced_description(cls, fruit_names):
        if len(fruit_names) < 2:
            return sims4.localization.LocalizationHelperTuning.get_raw_text(*fruit_names)
        if len(fruit_names) > 2:
            last_fruit = fruit_names.pop()
            fruit_names_loc = sims4.localization.LocalizationHelperTuning.get_comma_separated_list(*fruit_names)
        else:
            fruit_names_loc = fruit_names[0]
            last_fruit = fruit_names[1]
        return cls.SPLICED_PLANT_DESCRIPTION(fruit_names_loc, last_fruit)

    @classmethod
    def is_spliced(cls, obj):
        if obj.has_state(cls.SPLICED_STATE_VALUE.state) and obj.get_state(cls.SPLICED_STATE_VALUE.state) == cls.SPLICED_STATE_VALUE:
            return True
        return False

    @classmethod
    def is_shoot(cls, obj):
        if obj.has_state(cls.SHOOT_STATE_VALUE.state) and obj.get_state(cls.SHOOT_STATE_VALUE.state) == cls.SHOOT_STATE_VALUE:
            return True
        return False

    SPLICING_FAMILY_INFO_NAME = TunableLocalizedString(description='\n        The label to use in the UI for splicing information.\n        ')
    SPLICING_FAMILY_NAMES = TunableMapping(description='\n        The names to use for each splicing family when displayed in the UI.\n        ', key_type=TunableEnumEntry(SplicingFamily, SplicingFamily.DEFAULT), value_type=TunableLocalizedString())
    ALWAYS_GERMINATE_IF_NOT_SPAWNED_STATE = ObjectStateValue.TunableReference(description='\n        If the specified state value is active on the gardening object, it will\n        have a 100% germination chance for when it is placed in the world in\n        any way other than through a spawner.\n        ')
    QUALITY_STATE_VALUE = ObjectState.TunableReference(description='\n        The quality state all gardening plants will have.  \n        ')

class FruitSpawnerData(SpawnerTuning):
    __qualname__ = 'FruitSpawnerData'
    INSTANCE_SUBCLASSES_ONLY = True

    class _SpawnerOption:
        __qualname__ = 'FruitSpawnerData._SpawnerOption'
        spawn_type = SpawnerTuning.SLOT_SPAWNER
        slot_type = None
        state_mapping = None

    def __init__(self):
        spawner_option = self._SpawnerOption()
        spawner_option.slot_type = GardeningTuning.GARDENING_SLOT
        super().__init__(object_reference=(), spawn_weight=1, spawner_option=spawner_option, spawn_times=None)

    def set_fruit(self, fruit_definition):
        pass

    @flexmethod
    def create_spawned_object(cls, inst, mother, definition, loc_type=ItemLocation.ON_LOT):
        scale = GardeningTuning.SCALE_COMMODITY.default_value
        child = None
        try:
            child = create_object(definition, loc_type=loc_type)
            while not GardeningTuning.is_shoot(child) and mother.has_state(GardeningTuning.QUALITY_STATE_VALUE):
                quality_state = mother.get_state(GardeningTuning.QUALITY_STATE_VALUE)
                child.set_state(quality_state.state, quality_state)
                scale *= GardeningTuning.SCALE_VARIANCE.random_float()
                child.set_stat_value(GardeningTuning.SCALE_COMMODITY, scale)
        except:
            logger.exception('Failed to spawn.')
            if child is not None:
                child.destroy(source=mother, cause='Exception spawning child fruit.')
                child = None
        return child

    @property
    def main_spawner(self):
        return self.object_reference[0]

class _SplicedFruitData:
    __qualname__ = '_SplicedFruitData'

    def __init__(self, fruit_name):
        self._fruit_name = fruit_name

    def populate_localization_token(self, token):
        token.type = LocalizedStringToken.OBJECT
        token.catalog_name_key = self._fruit_name.hash
        token.catalog_description_key = self._fruit_name.hash

class _GardeningComponent(AutoFactoryInit, Component, HasTunableFactory, TooltipProvidingComponentMixin, persistence_key=protocols.PersistenceMaster.PersistableData.GardeningComponent):
    __qualname__ = '_GardeningComponent'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ui_metadata_handles = []
        self.owner.add_statistic_component()
        self.object_addition_to_world_complete = False
        self._fruit_spawners = []
        self._spliced_description = None

    def _get_additional_information(self):
        additional_information = []
        for state in GardeningTuning.STATES_WITH_ADDITIONAL_INFO:
            if not self.owner.has_state(state):
                pass
            name = state.display_name
            state_value = self.owner.get_state(state)
            value = state_value.display_name
            while name is not None and value is not None:
                additional_information.append((state.__name__, name, value))
        return additional_information

    def _ui_metadata_gen(self):
        additional_information = self._get_additional_information()
        if additional_information and self.show_gardening_details():
            additional_information.sort()
            object_info_names = []
            object_info_descriptions = []
            bullet_points = []
            for (_, name, value) in additional_information:
                object_info_names.append(name)
                object_info_descriptions.append(value)
                bullet_point = LocalizationHelperTuning.get_name_value_pair(name, value)
                bullet_points.append(bullet_point)
            description = LocalizationHelperTuning.get_bulleted_list(None, *bullet_points)
            plant_name = LocalizationHelperTuning.get_object_name(self.owner.definition)
        else:
            object_info_names = None
            object_info_descriptions = None
            if GardeningTuning.is_spliced(self.owner):
                description = self._spliced_description
                plant_name = GardeningTuning.SPLICED_PLANT_NAME()
            else:
                if GardeningTuning.is_shoot(self.owner) and self.root_stock is not None:
                    description = LocalizationHelperTuning.get_object_name(self.root_stock.main_spawner)
                else:
                    description = LocalizationHelperTuning.get_object_description(self.owner.definition)
                plant_name = LocalizationHelperTuning.get_object_name(self.owner.definition)
        subtext = self.owner.get_state_strings()
        yield ('object_info_names', object_info_names)
        yield ('object_info_descriptions', object_info_descriptions)
        yield ('recipe_name', plant_name)
        yield ('recipe_description', description)
        if subtext is not None:
            yield ('subtext', subtext)

    def update_hovertip(self):
        if not services.client_manager():
            pass
        else:
            old_handles = list(self._ui_metadata_handles)
            try:
                self._ui_metadata_handles = []
                for (name, value) in self._ui_metadata_gen():
                    handle = self.owner.add_ui_metadata(name, value)
                    self._ui_metadata_handles.append(handle)
            finally:
                for handle in old_handles:
                    self.owner.remove_ui_metadata(handle)

    def on_client_connect(self, client):
        self.update_hovertip()

    def show_gardening_details(self):
        return not any(self.owner.state_value_active(state) for state in GardeningTuning.DISABLE_DETAILS_STATE_VALUES)

    def show_gardening_tooltip(self):
        return not any(self.owner.state_value_active(state) for state in GardeningTuning.DISABLE_TOOLTIP_STATE_VALUES)

    def object_addition_complete(self):
        self.object_addition_to_world_complete = True
        self.update_hovertip()

    @property
    def root_stock(self):
        if not self._fruit_spawners:
            return
        return self._fruit_spawners[0]

    @property
    def root_stock_name_list(self):
        if not self._fruit_spawners:
            return
        name_list = []
        for spawner in self._fruit_spawners:
            tree_fruit_name = spawner.main_spawner.cls._components.gardening_component._tuned_values.fruit_name
            while tree_fruit_name not in name_list:
                name_list.append(tree_fruit_name)
        for (index, name) in enumerate(name_list):
            name_list[index] = LocalizationHelperTuning.get_object_name(_SplicedFruitData(name))
        return name_list

    @property
    def root_stock_gardening_tuning(self):
        if self.root_stock is None:
            return
        return self.root_stock.main_spawner.cls._components.gardening_component

    def save(self, persistence_master_message):
        persistable_data = protocols.PersistenceMaster.PersistableData()
        persistable_data.type = protocols.PersistenceMaster.PersistableData.GardeningComponent
        gardening_component_data = persistable_data.Extensions[protocols.PersistableGardeningComponent.persistable_data]
        for fruit_data in self._fruit_spawners:
            with ProtocolBufferRollback(gardening_component_data.fruit_spawners) as fruit_spawners:
                fruit_spawners.definition_id = fruit_data.main_spawner.id
        persistence_master_message.data.extend([persistable_data])

    def load(self, persistable_data):
        definition_manager = services.definition_manager()
        gardening_component_data = persistable_data.Extensions[protocols.PersistableGardeningComponent.persistable_data]
        for fruit_spawner in gardening_component_data.fruit_spawners:
            spawner_data = FruitSpawnerData()
            definition = definition_manager.get(fruit_spawner.definition_id)
            spawner_data.set_fruit(definition)
            self._fruit_spawners.append(spawner_data)
            self.owner.add_spawner_data(spawner_data)
        if GardeningTuning.is_spliced(self.owner):
            tree_fruit_names = self.root_stock_name_list
            self._spliced_description = GardeningTuning.get_spliced_description(tree_fruit_names)

class GardeningFruitComponent(_GardeningComponent, component_name=objects.components.types.GARDENING_COMPONENT, persistence_key=protocols.PersistenceMaster.PersistableData.GardeningComponent):
    __qualname__ = 'GardeningFruitComponent'
    FACTORY_TUNABLES = {'plant': TunableReference(description='\n        The plant that this fruit will grow into if planted or if it\n        spontaneously germinates.\n        ', manager=services.definition_manager()), 'splicing_families': TunableEnumFlags(description='\n        The set of splicing families compatible with this fruit.  Any fruit\n        matching one of these families may be spliced with a plant grown from\n        this fruit.\n        ', enum_type=SplicingFamily, needs_tuning=True, default=SplicingFamily(0)), 'splicing_recipies': TunableMapping(description='\n        The set of splicing recipes for this fruit.  If a plant grown from this\n        fruit is spliced with one of these other fruits, the given type of fruit\n        will be also be spawned.\n        ', key_type=TunableReference(services.definition_manager()), value_type=TunableReference(services.definition_manager())), 'spawn_slot': SlotType.TunableReference(), 'spawn_state_mapping': TunableMapping(description='\n        Mapping of states from the spawner object into the possible\n        states that the spawned object may have\n        ', key_type=TunableStateValueReference(), value_type=TunableList(description='\n            List of possible childs for a parent state\n            ', tunable=TunableTuple(description='\n                Pair of weight and possible state that the spawned \n                object may have\n                ', weight=TunableRange(description='\n                    Weight that object will have on the probability calculation \n                    of which object to spawn.\n                    ', tunable_type=int, default=1, minimum=0), child_state=TunableStateValueReference()))), 'spawn_times': OptionalTunable(description='\n        Schedule of when the fruit spawners should trigger.\n        If this is set, spawn commodities will be removed and it will spawn\n        based on the times set.\n        ', tunable=TunableWeeklyScheduleFactory(), disabled_name='No_custom_spawn_times', enabled_name='Set_custom_spawn_times'), 'base_weight': Tunable(description="\n        The base weight of a fruit if its size gene's value is 1.  The value of\n        that gene is controlled by the range of the SCALE_COMMODITY.\n        ", tunable_type=float, default=100), 'weight_units': TunableEnumEntry(MassUnit, MassUnit.GRAMS, needs_tuning=True), 'fruit_fall_behavior': OptionalTunable(description='\n        Controls automatic fruit-fall behavior.\n        ', disabled_name='fruit_does_not_fall', enabled_name='fruit_falls_to_ground', tunable=TunableTuple(fall_at_state_value=ObjectStateValue.TunableReference(), search_radius=TunableInterval(tunable_type=float, default_lower=0.5, default_upper=3))), 'fruit_name': TunableLocalizedString(description='\n        Fruit name that will be used on the spliced plant description.\n        ')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._germination_handle = None
        self._fall_to_ground_retry_alarm_handle = None

    def on_add(self, *_, **__):
        self.start_germination_timer()
        self.owner.hover_tip = ui_protocols.UiObjectMetadata.HOVER_TIP_GARDENING

    def on_remove(self, *_, **__):
        self.stop_germination_timer()
        self._cancel_fall_to_ground_retry_alarm()

    def scale_modifiers_gen(self):
        yield self.owner.get_stat_value(GardeningTuning.SCALE_COMMODITY)

    def on_state_changed(self, state, old_value, new_value):
        if not self.object_addition_to_world_complete:
            return
        if self.fruit_fall_behavior is not None and new_value == self.fruit_fall_behavior.fall_at_state_value:
            self._fall_to_ground()
        self.update_hovertip()

    def on_added_to_inventory(self):
        for (on_state_value, to_state_value) in GardeningTuning.PICKUP_STATE_MAPPING.items():
            while self.owner.has_state(on_state_value):
                self.owner.set_state(to_state_value)

    def start_germination_timer(self):
        if self._germination_handle is not None:
            return
        germinate_stat = self.owner.commodity_tracker.add_statistic(GardeningTuning.SPONTANEOUS_GERMINATION_COMMODITY)
        value = random.uniform(germinate_stat.initial_value - GardeningTuning.SPONTANEOUS_GERMINATION_COMMODITY_VARIANCE, germinate_stat.initial_value)
        germinate_stat.set_value(value)
        threshold = sims4.math.Threshold(germinate_stat.convergence_value, operator.le)
        self._germination_handle = self.owner.commodity_tracker.create_and_activate_listener(germinate_stat.stat_type, threshold, self.germinate)

    def stop_germination_timer(self):
        if self._germination_handle is None:
            return
        self.owner.commodity_tracker.remove_listener(self._germination_handle)
        self._germination_handle = None

    def _cancel_fall_to_ground_retry_alarm(self):
        if self._fall_to_ground_retry_alarm_handle is not None:
            alarms.cancel_alarm(self._fall_to_ground_retry_alarm_handle)
            self._fall_to_ground_retry_alarm_handle = None

    def germinate(self, *_, **__):
        self.stop_germination_timer()
        result = None
        try:
            result = self._germinate()
        except:
            self.start_germination_timer()
            raise
        if result == False:
            self.start_germination_timer()
        if result is None:
            self.stop_germination_timer()
        return result

    def _germinate(self):
        plant = None
        try:
            plant = create_object(self.plant)
            location = self._find_germinate_location(plant)
            if location is None:
                logger.warn('Failed to germinate: No location found')
                plant.destroy(source=self.owner, cause='Failed to germinate: No location found')
                plant = None
                return False
            if self.owner.parent_slot is not None:
                self.owner.parent_slot.add_child(plant)
            else:
                plant.location = location
            plant.gardening_component.add_fruit(self.owner, sprouted_from=True)
            created_object_quality = self.owner.get_state(GardeningTuning.QUALITY_STATE_VALUE)
            current_household = services.owning_household_of_active_lot()
            if current_household is not None:
                plant.set_household_owner_id(current_household.id)
                services.get_event_manager().process_events_for_household(test_events.TestEvent.ItemCrafted, current_household, crafted_object=plant, skill=None, quality=created_object_quality, masterwork=None)
            if self.owner.in_use:
                self.owner.transient = True
            else:
                self.owner.destroy(source=self.owner, cause='Successfully germinated.')
                return
        except:
            logger.exception('Failed to germinate.')
            if plant is not None:
                plant.destroy(source=self.owner, cause='Failed to germinate.')
                plant = None
                return False
        return plant

    def _find_germinate_location(self, plant):
        if self.owner.parent_slot is not None:
            result = self.owner.parent_slot.is_valid_for_placement(definition=self.plant, objects_to_ignore=(self.owner,))
            if not result:
                return
            location = self.owner.location
        else:
            search_flags = FGLSearchFlagsDefault | FGLSearchFlag.ALLOW_GOALS_IN_SIM_INTENDED_POSITIONS | FGLSearchFlag.ALLOW_GOALS_IN_SIM_POSITIONS | FGLSearchFlag.SHOULD_TEST_BUILDBUY
            context = FindGoodLocationContext(starting_location=self.owner.location, ignored_object_ids=(self.owner.id,), object_id=plant.id, object_footprints=(plant.get_footprint(),), search_flags=search_flags)
            (translation, orientation) = find_good_location(context)
            if translation is None or orientation is None:
                return
            location = sims4.math.Location(sims4.math.Transform(translation, orientation), self.owner.routing_surface)
        return location

    @property
    def is_on_tree(self):
        if self.owner.parent_slot is not None and self.spawn_slot in self.owner.parent_slot.slot_types:
            return True
        return False

    def _fall_to_ground(self):
        self._cancel_fall_to_ground_retry_alarm()
        if not self.is_on_tree:
            return
        if self.owner.in_use:
            self._fall_to_ground_retry_alarm_handle = alarms.add_alarm(self.owner, TimeSpan.in_real_world_seconds(10), self._fall_to_ground)
            return
        parent_obj = self.owner.parent
        if parent_obj is None:
            logger.warn('{}: Fruit failed to fall, it is no longer parented.', self.owner)
            return
        target_location = routing.Location(self.owner.routing_location.position, parent_obj.routing_location.orientation, parent_obj.routing_location.routing_surface)
        context = FindGoodLocationContext(starting_routing_location=target_location, object_footprints=(self.plant.get_footprint(0),), max_distance=self.fruit_fall_behavior.search_radius.upper_bound)
        (translation, orientation) = find_good_location(context)
        if translation is None or orientation is None:
            logger.warn('{}: Failed to fall because FGL failed.', self.owner)
            self.owner.destroy(source=parent_obj, cause='Failed to fall because FGL failed')
            return
        if self.owner.parent is not None:
            self.owner.clear_parent(sims4.math.Transform(translation, orientation), self.owner.routing_surface)
        else:
            self.owner.set_location(sims4.math.Location(sims4.math.Transform(translation, orientation), self.owner.routing_surface))

    def on_parent_wilted(self):
        if self.is_on_tree:
            self.owner.destroy(source=self.owner.parent, cause='Parent plant wilted')

    @property
    def show_splicing_families_in_tooltip(self):
        return GardeningTuning.is_shoot(self.owner)

class GardeningPlantComponent(_GardeningComponent, component_name=objects.components.types.GARDENING_COMPONENT, persistence_key=protocols.PersistenceMaster.PersistableData.GardeningComponent):
    __qualname__ = 'GardeningPlantComponent'
    FACTORY_TUNABLES = {'states_that_support_fruit': TunableSet(description='\n        Any time the plant goes from a state in this list to one that is not,\n        all fruit currently on the plant will be destroyed.\n        ', tunable=ObjectStateValue.TunableReference())}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        threshold = sims4.math.Threshold(GardeningTuning.WITHERED_STATE_VALUE.high_value, operator.le)
        self._withered_alarm = self.owner.commodity_tracker.create_and_activate_listener(GardeningTuning.WITHERED_STATE_VALUE.state.linked_stat.stat_type, threshold, self._on_withered_state)

    def on_add(self, *_, **__):
        self.owner.hover_tip = ui_protocols.UiObjectMetadata.HOVER_TIP_GARDENING

    def on_remove(self, *_, **__):
        if self._withered_alarm is not None:
            self.owner.commodity_tracker.remove_listener(self._withered_alarm)
            self._withered_alarm = None

    def on_state_changed(self, state, old_value, new_value):
        if not self.object_addition_to_world_complete:
            return
        if old_value in self.states_that_support_fruit and new_value not in self.states_that_support_fruit:
            for fruit in list(self.owner.children):
                while fruit.gardening_component is not None:
                    fruit.gardening_component.on_parent_wilted()
        self.update_hovertip()

    def scale_modifiers_gen(self):
        yield self.owner.get_stat_value(GardeningTuning.SCALE_COMMODITY)

    @property
    def splicing_families(self):
        gardening_tuning = self.root_stock_gardening_tuning
        if gardening_tuning is None:
            return
        return SplicingFamily(gardening_tuning.splicing_families)

    def add_fruit(self, fruit, sprouted_from=False):
        if sprouted_from:
            for state in GardeningTuning.INHERITED_STATES:
                state_value = fruit.get_state(state)
                self.owner.set_state(state, state_value)
        else:
            splicing_recipies = self.root_stock_gardening_tuning.splicing_recipies
            if fruit.gardening_component.root_stock.main_spawner in splicing_recipies:
                spawner_data = FruitSpawnerData()
                spawner_data.set_fruit(splicing_recipies[fruit.definition])
                self._fruit_spawners.append(spawner_data)
                self.owner.add_spawner_data(spawner_data)
        spawner_data = FruitSpawnerData()
        if GardeningTuning.is_shoot(fruit):
            spawner_data.set_fruit(fruit.gardening_component.root_stock.main_spawner)
        else:
            spawner_data.set_fruit(fruit.definition)
        self._fruit_spawners.append(spawner_data)
        self.owner.add_spawner_data(spawner_data)
        self.update_hovertip()

    def create_shoot(self):
        if not self.root_stock:
            self._initialize_root_stock_from_spawner_component()
        if self.root_stock is None:
            logger.error('Gardening object without a root stock, this is caused by missing spawner component for open street objects or broken fruit reference on the gardening plant component')
            return
        shoot = self.root_stock.create_spawned_object(self.owner, GardeningTuning.SHOOT_DEFINITION)
        shoot.gardening_component.fruit_spawner_data = self.root_stock
        shoot.gardening_component._fruit_spawners.append(self.root_stock)
        shoot.gardening_component.update_hovertip()
        return shoot

    def _initialize_root_stock_from_spawner_component(self):
        for spawn_obj_def in self.owner.slot_spawner_definitions():
            spawner_data = FruitSpawnerData()
            spawner_data.set_fruit(spawn_obj_def[0])
            self._fruit_spawners.append(spawner_data)

    def can_splice_with(self, shoot):
        return GardeningTuning.is_shoot(shoot)

    @property
    def show_splicing_families_in_tooltip(self):
        return True

    _UiIcon = collections.namedtuple('_UiIcon', ('severity', 'order', 'icon'))

    def _ui_metadata_gen(self):
        if not self.show_gardening_tooltip():
            self.owner.hover_tip = ui_protocols.UiObjectMetadata.HOVER_TIP_DISABLED
        icons = []
        states_min = 999
        for state in GardeningTuning.STATES_WITH_STATUS_ICONS:
            if state.linked_stat:
                state_value = self.owner.get_stat_value(state.linked_stat)
                if state_value < states_min:
                    states_min = state_value
            state_value = self.owner.get_state(state)
            icon = state_value.icon
            while icon is not None:
                icon = sims4.resources.get_protobuff_for_key(icon)
                icons.append(self._UiIcon(state_value.severity, state.__name__, icon))
        main_state = GardeningTuning.STATE_MAIN_ICON
        if icons:
            self.owner.set_stat_value(main_state.linked_stat, states_min)
        main_state_value = self.owner.get_state(main_state)
        main_icon = None
        if self.show_gardening_details():
            main_icon = sims4.resources.get_protobuff_for_key(main_state_value.icon)
        yield ('main_icon', main_icon)
        yield super()._ui_metadata_gen()

    def _on_withered_state(self, stat):
        while self.owner.children:
            fruit_inst = self.owner.children.pop()
            fruit_inst.destroy(source=self.owner, cause='Plant wilted so destroying children.')

class TunableGardeningComponent(TunableVariant):
    __qualname__ = 'TunableGardeningComponent'

    def __init__(self, **kwargs):
        super().__init__(fruit_component=GardeningFruitComponent.TunableFactory(), plant_component=GardeningPlantComponent.TunableFactory(), locked_args={'disabled': None}, default='disabled', **kwargs)

class SlotItemHarvest(XevtTriggeredElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'SlotItemHarvest'
    FACTORY_TUNABLES = {'description': '\n            Transfer all objects slotted to target object into the sim \n            inventory\n            ', 'participant': TunableEnumEntry(description="\n            The participant of the interaction whose slots will be checked \n            for objects to be gathered into the sim's inventory\n            ", tunable_type=ParticipantType, default=ParticipantType.Object)}

    def _do_behavior(self):
        gather_obj = self.interaction.get_participant(self.participant)
        if gather_obj is None:
            return False
        sim = self.interaction.sim
        sim_inventory = sim.inventory_component
        while gather_obj.children:
            child_inst = gather_obj.children.pop()
            child_inst.update_ownership(sim)
            sim_inventory.player_try_add_object(child_inst)

@sims4.commands.Command('gardening.cleanup_gardening_objects')
def cleanup_gardening_objects(_connection=None):
    for obj in services.object_manager().get_all_objects_with_component_gen(GARDENING_COMPONENT):
        if not isinstance(obj.gardening_component, GardeningFruitComponent):
            pass
        while obj.parent is None and not obj.is_in_inventory() and not obj.is_on_active_lot():
            sims4.commands.output('Destroyed object {} on open street was found without a parent at position {}, parent_type {}.'.format(obj, obj.position, obj.parent_type), _connection)
            obj.destroy(source=obj, cause='Fruit/Flower with no parent on open street')
    sims4.commands.output('Gardening cleanup complete', _connection)

