import collections
import math
from event_testing.resolver import SingleObjectResolver
from event_testing.tests import TunableTestSet
from objects.components.state import TunableStateValueReference
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableMapping, TunableLotDescription, TunableRegionDescription, HasTunableReference, TunableWorldDescription, TunableReference, TunableList, TunableFactory, TunableTuple, TunableVariant, Tunable
import services
import sims4.log
import situations.ambient.walkby_tuning
logger = sims4.log.Logger('LotTuning')

class LotTuning(HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.lot_tuning_manager()):
    __qualname__ = 'LotTuning'
    INSTANCE_TUNABLES = {'walkby': situations.ambient.walkby_tuning.WalkbyTuning.TunableReference()}

    @classmethod
    def _cls_repr(cls):
        return "LotTuning: <class '{}.{}'> \n\t {}".format(cls.__module__, cls.__name__, cls.walkby)

class LotTuningMaps:
    __qualname__ = 'LotTuningMaps'
    LOT_TO_LOTTUNING_MAP = TunableMapping(description="\n            Mapping of Lot Description ID to lot tuning. This is a reference to \n            a specific lot in one of our regions. e.g. Goth's mansion lot.\n            ", key_name='Lot Description ID', key_type=TunableLotDescription(), value_name='Lot Tuning', value_type=LotTuning.TunableReference())
    STREET_TO_LOTTUNING_MAP = TunableMapping(description='\n            Mapping of Street Description ID to lot tuning. Street and world\n            are analogous terms. e.g. suburbs street in Garden District.\n            \n            This represents the tuning for all lots within this street that does\n            not have a specific LotTuning specified for itself in the \n            LOT_TO_LOTTUNING_MAP.\n            ', key_name='Street Description ID', key_type=TunableWorldDescription(), value_name='Lot Tuning', value_type=LotTuning.TunableReference())
    REGION_TO_LOTTUNING_MAP = TunableMapping(description='\n            Mapping of Region Description ID to spawner tuning. Region and \n            neighborhood are analogous terms. e.g. Garden District.\n            \n            This represents the tuning for all lots in the region that does\n            not have a specific LotTuning specified for itself in either the \n            LOT_TO_LOTTUNING_MAP or via STREET_TO_LOTTUNING_MAP.\n            ', key_name='Region Description ID', key_type=TunableRegionDescription(), value_name='Lot Tuning', value_type=LotTuning.TunableReference())

    @classmethod
    def get_lot_tuning(cls):
        current_zone = services.current_zone()
        lot = current_zone.lot
        if lot is None:
            logger.warn('Attempting to get LotTuning when the current zone does not have a lot.', owner='manus')
            return
        (world_description_id, lot_description_id) = services.get_world_and_lot_description_id_from_zone_id(current_zone.id)
        lot_tuning = cls.LOT_TO_LOTTUNING_MAP.get(lot_description_id)
        if lot_tuning is not None:
            return lot_tuning
        lot_tuning = cls.STREET_TO_LOTTUNING_MAP.get(world_description_id, None)
        if lot_tuning is not None:
            return lot_tuning
        neighborhood_id = current_zone.neighborhood_id
        if neighborhood_id == 0:
            logger.warn('Attempting to get LotTuning when the current zone does not have a neighborhood.', owner='manus')
            return
        neighborhood_proto_buff = services.get_persistence_service().get_neighborhood_proto_buff(neighborhood_id)
        region_id = neighborhood_proto_buff.region_id
        lot_tuning = cls.REGION_TO_LOTTUNING_MAP.get(region_id, None)
        return lot_tuning

class AllItems(TunableFactory):
    __qualname__ = 'AllItems'

    @staticmethod
    def factory(_):
        return sims4.math.POS_INFINITY

    FACTORY_TYPE = factory

    def __init__(self, *args, **kwargs):
        super().__init__(description='\n                Process all of the objects on the lot.\n                ')

class StatisticValue(TunableFactory):
    __qualname__ = 'StatisticValue'

    @staticmethod
    def factory(lot, statistic):
        statistic_value = lot.get_stat_value(statistic)
        if statistic_value is None:
            return 0
        return math.floor(statistic_value)

    FACTORY_TYPE = factory

    def __init__(self, *args, **kwargs):
        super().__init__(statistic=TunableReference(description='\n                The statistic on the lot that will be used to determine the\n                number of objects to process.\n                If the statistic is not found then the number 0 is used instead.\n                ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)), description='\n                Return the value of a statistic on the lot.  If the statistic\n                is not found then the number 0 is used instead.\n                ')

class StatisticDifference(TunableFactory):
    __qualname__ = 'StatisticDifference'

    @staticmethod
    def factory(lot, statistic_1, statistic_2):
        statistic_1_value = lot.get_stat_value(statistic_1)
        if statistic_1_value is None:
            statistic_1_value = 0
        statistic_2_value = lot.get_stat_value(statistic_2)
        if statistic_2_value is None:
            statistic_2_value = 0
        return math.floor(abs(statistic_1_value - statistic_2_value))

    FACTORY_TYPE = factory

    def __init__(self, *args, **kwargs):
        super().__init__(statistic_1=TunableReference(description='\n                The first statistic that will be used with the second statistic\n                in order to discover the number of objects on the lot to\n                process.\n                \n                If the statistic is not found then the number 0 is use instead.\n                ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)), statistic_2=TunableReference(description='\n                The second statistic that will be used with the first statistic\n                in order to discover the number of objects on the lot to\n                process.\n                \n                If the statistic is not found then the number 0 is use instead.\n                ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)), description='\n                Return the difference between two different statistics and use\n                that as the amount of objects to process.\n                If the statistics cannot be found the value 0 is used instead.\n                ')

class SetState(TunableFactory):
    __qualname__ = 'SetState'

    @staticmethod
    def factory(obj, _, state):
        if obj.state_component and obj.has_state(state.state):
            obj.set_state(state.state, state, immediate=True)

    FACTORY_TYPE = factory

    def __init__(self, *args, **kwargs):
        super().__init__(state=TunableStateValueReference(description='\n                An state that we want to set the object to.\n                '), description='\n                Change the state of an object to the tuned state.\n                ')

class DestroyObject(TunableFactory):
    __qualname__ = 'DestroyObject'

    @staticmethod
    def factory(obj, _):
        GlobalLotTuningAndCleanup.objects_to_destroy.add(obj)

    FACTORY_TYPE = factory

    def __init__(self, *args, **kwargs):
        super().__init__(description='\n                Destroy the object.\n                ')

class ConstantAmount(TunableFactory):
    __qualname__ = 'ConstantAmount'

    @staticmethod
    def factory(_, amount):
        return amount

    FACTORY_TYPE = factory

    def __init__(self, *args, **kwargs):
        super().__init__(amount=Tunable(description='\n                A constant amount to change the statistic by.\n                ', tunable_type=float, default=0.0), description='\n                A constant amount.\n                ')

class StatisticBased(TunableFactory):
    __qualname__ = 'StatisticBased'

    @staticmethod
    def factory(lot, statistic, multiplier):
        statistic_value = lot.get_stat_value(statistic)
        if statistic_value is None:
            return 0
        return statistic_value*multiplier

    FACTORY_TYPE = factory

    def __init__(self, *args, **kwargs):
        super().__init__(statistic=TunableReference(description="\n                A statistic on the lot who's value will be used as the amount\n                to modify a statistic.\n                If no value is found the number 0 is used.\n                ", manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)), multiplier=Tunable(description='\n                A multiplier on the statistic value of the statistic on the lot.\n                ', tunable_type=float, default=1.0), description='\n                An amount that is based on the statistic value of a statistic\n                on the lot.\n                ')

class StatisticChange(TunableFactory):
    __qualname__ = 'StatisticChange'

    @staticmethod
    def factory(obj, lot, statistic, amount):
        obj.add_statistic_component()
        stat_instance = obj.get_stat_instance(statistic)
        if stat_instance is None:
            return
        stat_change = amount(lot)
        stat_instance.add_value(stat_change)

    FACTORY_TYPE = factory

    def __init__(self, *args, **kwargs):
        super().__init__(statistic=TunableReference(description='\n                The statistic to be changed on the object.\n                ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)), amount=TunableVariant(constant=ConstantAmount(), statistic_based=StatisticBased(), description='\n                The amount to modify the statistic by.\n                '), description='\n                Modify the statistic value of an object.\n                ')

class GlobalLotTuningAndCleanup:
    __qualname__ = 'GlobalLotTuningAndCleanup'
    OBJECT_COUNT_TUNING = TunableMapping(description='\n        Mapping between statistic and a set of tests that are run over the\n        objects on the lot on save.  The value of the statistic is set to the\n        number of objects that pass the tests.\n        ', key_type=TunableReference(description='\n            The statistic on the lot that will be set the value of the number\n            of objects that pass the test set that it is mapped to.\n            ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)), value_type=TunableTestSet(description='\n            Test set that will be run on all objects on the lot to determine\n            what the value of the key statistic should be set to.\n            '))
    SET_STATISTIC_TUNING = TunableList(description='\n        A list of statistics and values that they will be set to on the lot\n        while saving it when the lot was running.\n        \n        These values are set before counting by tests on objects.\n        ', tunable=TunableTuple(statistic=TunableReference(description='\n                The statistic that will have its value set.\n                ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)), amount=Tunable(description='\n                The value that the statistic will be set to.\n                ', tunable_type=float, default=0.0)))
    OBJECT_CLEANUP_TUNING = TunableList(description='\n        A list of actions to take when spinning up a zone in order to fix it\n        up based on statistic values that the lot has.\n        ', tunable=TunableTuple(count=TunableVariant(all_items=AllItems(), statistic_value=StatisticValue(), statistic_difference=StatisticDifference(), default='all_items', description='\n                    The maximum number of items that will have the action run\n                    on them. \n                '), possible_actions=TunableList(description='\n                The different possible actions that can be taken on objects on\n                the lot if tests pass.\n                ', tunable=TunableTuple(actions=TunableList(description='\n                        A group of actions to be taken on the object.\n                        ', tunable=TunableVariant(set_state=SetState(), destroy_object=DestroyObject(), statistic_change=StatisticChange(), default='set_state', description='\n                                The actual action that will be performed on the\n                                object if test passes.\n                            ')), tests=TunableTestSet(description='\n                        Tests that if they pass the object will be under\n                        consideration for this action being done on them.\n                        ')))))
    objects_to_destroy = None

    @classmethod
    def calculate_object_quantity_statistic_values(cls, lot):
        for set_statatistic in cls.SET_STATISTIC_TUNING:
            lot.set_stat_value(set_statatistic.statistic, set_statatistic.amount)
        new_statistic_values = collections.defaultdict(int)
        for obj in services.object_manager().values():
            if obj.is_sim:
                pass
            if not obj.is_on_active_lot():
                pass
            resolver = SingleObjectResolver(obj)
            for (statistic, tests) in cls.OBJECT_COUNT_TUNING.items():
                while tests.run_tests(resolver):
                    new_statistic_values[statistic] += 1
        for (statistic, value) in new_statistic_values.items():
            lot.set_stat_value(statistic, value)

    @classmethod
    def cleanup_objects(cls, lot=None):
        if lot is None:
            logger.error('Lot is None when trying to run lot cleanup.', owner='jjacobson')
            return
        cls.objects_to_destroy = set()
        for cleanup in GlobalLotTuningAndCleanup.OBJECT_CLEANUP_TUNING:
            items_to_cleanup = cleanup.count(lot)
            if items_to_cleanup == 0:
                pass
            items_cleaned_up = 0
            for obj in services.object_manager().values():
                if items_cleaned_up >= items_to_cleanup:
                    break
                if obj.is_sim:
                    pass
                resolver = SingleObjectResolver(obj)
                run_action = False
                for possible_action in cleanup.possible_actions:
                    while possible_action.tests.run_tests(resolver):
                        while True:
                            for action in possible_action.actions:
                                action(obj, lot)
                                run_action = True
                while run_action:
                    items_cleaned_up += 1
        for obj in cls.objects_to_destroy:
            obj.destroy(source=lot, cause='Cleaning up the lot')
        cls.objects_to_destroy = None

