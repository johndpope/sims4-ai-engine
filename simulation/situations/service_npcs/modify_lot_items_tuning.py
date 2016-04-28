from event_testing.resolver import SingleObjectResolver
from interactions import ParticipantType
from objects.components.inventory import InventoryTransferFakePerform, DeliverBillFakePerform
from objects.components.state import TunableStateValueReference
from sims4.tuning.tunable import HasTunableFactory, TunableList, TunableTuple, AutoFactoryInit, TunableVariant, TunableSingletonFactory
import event_testing.results
import event_testing.test_base
import event_testing.test_variants
import event_testing.tests
import services

class TunableObjectModifyTestVariant(TunableVariant):
    __qualname__ = 'TunableObjectModifyTestVariant'

    def __init__(self, description='A single tunable test.', test_excluded=(), **kwargs):
        super().__init__(description=description, state=event_testing.test_variants.TunableStateTest(locked_args={'who': ParticipantType.Object, 'tooltip': None, 'fallback_behavior': event_testing.test_variants.StateTest.ALWAYS_FAIL}), object_definition=TunableObjectMatchesDefinitionOrTagTest(), inventory=event_testing.test_variants.InventoryTest.TunableFactory(locked_args={'tooltip': None}), custom_name=event_testing.test_variants.CustomNameTest.TunableFactory(locked_args={'tooltip': None}), **kwargs)

class TunableObjectModifyTestSet(event_testing.tests.CompoundTestListLoadingMixin):
    __qualname__ = 'TunableObjectModifyTestSet'
    DEFAULT_LIST = event_testing.tests.CompoundTestList()

    def __init__(self, description=None, **kwargs):
        super().__init__(description=description, tunable=TunableList(TunableObjectModifyTestVariant(), description='A list of tests.  All of these must pass for the group to pass.'), **kwargs)

class ObjectMatchesDefinitionOrTagTest(event_testing.test_base.BaseTest):
    __qualname__ = 'ObjectMatchesDefinitionOrTagTest'
    FACTORY_TUNABLES = {'description': 'Check to see if the specified object matches either a static definition or a set of tags', 'item': TunableVariant(actual_item=event_testing.test_variants.CraftActualItemFactory(), tagged_item=event_testing.test_variants.CraftTaggedItemFactory(), default='tagged_item', description='Whether to test for a specific item or item that has a set of tags')}

    def __init__(self, item, **kwargs):
        super().__init__(**kwargs)
        self.item = item

    def get_expected_args(self):
        return {'objects': ParticipantType.Object}

    def __call__(self, objects=None):
        obj = next(iter(objects))
        match = self.item(obj, None)
        if not match:
            return event_testing.results.TestResult(False, 'ObjectMatchesDefinitionOrTagTest: Object did not match specified checks.')
        return event_testing.results.TestResult.TRUE

TunableObjectMatchesDefinitionOrTagTest = TunableSingletonFactory.create_auto_factory(ObjectMatchesDefinitionOrTagTest)

class ModifyAllLotItems(HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'ModifyAllLotItems'
    DESTROY_OBJECT = 0
    SET_STATE = 1
    INVENTORY_TRANSFER = 2
    DELIVER_BILLS = 3
    FACTORY_TUNABLES = {'description': '\n        Tune modifications to apply to all objects on a lot.\n        Can do state changes, destroy certain items, etc.\n        \n        EX: for auto cleaning, tune to have objects with Dirtiness state that\n        equals dirty to be set to the clean state and tune to have dirty dishes\n        and spoiled food to be deleted\n        ', 'modifications': TunableList(description="\n            A list of where the elements define how to modify objects on the\n            lot. Each entry is a triplet of an object modification action\n            (currently either destroy the object or set its state), a list of\n            tests to run on the object to determine if we should actually apply\n            the modification, and a priority in case some modifications should\n            take precedence over other ones when both of their tests pass.\n            \n            EX: test list: object's dirtiness state != dirtiness clean\n            action: set state to Dirtiness_clean\n            \n            So dirty objects will become clean\n            ", tunable=TunableTuple(action=TunableVariant(set_state=TunableTuple(action_value=TunableStateValueReference(description='An object state to set the object to'), locked_args={'action_type': SET_STATE}), destroy_object=TunableTuple(locked_args={'action_type': DESTROY_OBJECT}), inventory_transfer=TunableTuple(action_value=InventoryTransferFakePerform.TunableFactory(), locked_args={'action_type': INVENTORY_TRANSFER}), deliver_bills=TunableTuple(action_value=DeliverBillFakePerform.TunableFactory(), locked_args={'action_type': DELIVER_BILLS})), tests=TunableObjectModifyTestSet(description='\n                    All least one subtest group (AKA one list item) must pass\n                    within this list before the action associated with this\n                    tuning will be run.\n                    ')))}

    def modify_objects_on_active_lot(self, modify_open_streets=False):
        objects_to_destroy = []
        num_modified = 0
        for obj in services.object_manager().values():
            if obj.is_sim:
                pass
            while not (modify_open_streets and obj.is_on_active_lot()):
                if obj.in_use:
                    pass
                resolver = SingleObjectResolver(obj)
                modified = False
                for action_and_test in self.modifications:
                    if not action_and_test.tests.run_tests(resolver):
                        pass
                    modified = True
                    action = action_and_test.action
                    action_type = action.action_type
                    if action_type == ModifyAllLotItems.DESTROY_OBJECT:
                        objects_to_destroy.append(obj)
                        break
                    elif action_type == ModifyAllLotItems.SET_STATE:
                        new_state_value = action.action_value
                        if obj.state_component and obj.has_state(new_state_value.state):
                            obj.set_state(new_state_value.state, new_state_value, immediate=True)
                            if action_type in (ModifyAllLotItems.INVENTORY_TRANSFER, ModifyAllLotItems.DELIVER_BILLS):
                                element = action.action_value()
                                element._do_behavior()
                            else:
                                raise NotImplementedError
                    elif action_type in (ModifyAllLotItems.INVENTORY_TRANSFER, ModifyAllLotItems.DELIVER_BILLS):
                        element = action.action_value()
                        element._do_behavior()
                    else:
                        raise NotImplementedError
                while modified:
                    num_modified += 1
        for obj in objects_to_destroy:
            obj.destroy(source=self, cause='Destruction requested by modify lot tuning')
        objects_to_destroy = None
        return num_modified

