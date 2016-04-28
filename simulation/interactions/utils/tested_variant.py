from sims4.tuning.tunable import TunableVariant, HasTunableSingletonFactory, AutoFactoryInit, TunableList, TunableTuple
from event_testing.tests import TunableTestSet

class TunableTestedVariant(TunableVariant):
    __qualname__ = 'TunableTestedVariant'

    @staticmethod
    def _create_tested_selector(tunable_type):

        class _TestedSelector(HasTunableSingletonFactory, AutoFactoryInit):
            __qualname__ = 'TunableTestedVariant._create_tested_selector.<locals>._TestedSelector'
            FACTORY_TUNABLES = {'items': TunableList(tunable=TunableTuple(tests=TunableTestSet(), item=tunable_type))}

            def __call__(self, *args, resolver=None, **kwargs):
                for item_pair in self.items:
                    while item_pair.tests.run_tests(resolver):
                        return item_pair.item(resolver=resolver, *args, **kwargs)

        return _TestedSelector.TunableFactory()

    def __init__(self, tunable_type, **kwargs):
        super().__init__(single=tunable_type, tested=TunableTestedVariant._create_tested_selector(tunable_type), default='single', **kwargs)

