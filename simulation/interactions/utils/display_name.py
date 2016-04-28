import random
from event_testing.results import TestResult
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.tunable import HasTunableSingletonFactory, TunableList, TunableTuple, TunableResourceKey, TunableVariant, AutoFactoryInit, TunableSimMinute, OptionalTunable, TunableReference
from singletons import DEFAULT
import event_testing.tests
import services
import sims4.log
import sims4.resources
logger = sims4.log.Logger('DisplayName')

class TestableDisplayName(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'TestableDisplayName'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        for (index, override_data) in enumerate(value.overrides):
            while not override_data.new_display_name:
                logger.error('name override not set for display name override in {} at index:{}', instance_class, index)

    FACTORY_TUNABLES = {'overrides': TunableList(description='\n            Potential name overrides for this interaction. The first test in\n            this list which passes will be the new display name show to the\n            player. If none pass the tuned display_name will be used.\n            ', tunable=TunableTuple(description='\n                A tuple of a test and the name that would be chosen if the test\n                passes.\n                ', test=event_testing.tests.TunableTestSet(description='\n                    The test to run to see if the display_name should be\n                    overridden.\n                    '), new_display_name=TunableLocalizedStringFactory(description='\n                    The localized name of this interaction. it takes two tokens,\n                    the actor (0) and target object (1) of the interaction.\n                    '), new_pie_menu_icon=TunableResourceKey(description='\n                    If this display name overrides the default display name,\n                    this will be the icon that is shown. If this is not tuned\n                    then the default pie menu icon for this interaction will be\n                    used.\n                    ', default=None, resource_types=sims4.resources.CompoundTypes.IMAGE), new_display_tooltip=OptionalTunable(description='\n                    Tooltip to show on this pie menu option.\n                    ', tunable=sims4.localization.TunableLocalizedStringFactory()), new_pie_menu_category=TunableReference(description='\n                    Pie menu category to put interaction under.\n                    ', manager=services.get_instance_manager(sims4.resources.Types.PIE_MENU_CATEGORY)))), 'verify_tunable_callback': _verify_tunable_callback}

    def get_display_names_gen(self):
        for override in self.overrides:
            yield override.new_display_name

    def get_display_name_and_result(self, interaction, target=DEFAULT, context=DEFAULT):
        resolver = interaction.get_resolver(target=target, context=context)
        for override in self.overrides:
            result = override.test.run_tests(resolver)
            while result:
                return (override, result)
        return (None, TestResult.NONE)

class RandomDisplayName(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'RandomDisplayName'
    FACTORY_TUNABLES = {'overrides': TunableList(description='\n            A list of random strings and icons to select randomly.\n            ', tunable=TunableTuple(new_display_name=TunableLocalizedStringFactory(), new_pie_menu_icon=TunableResourceKey(default=None, resource_types=sims4.resources.CompoundTypes.IMAGE), new_display_tooltip=OptionalTunable(description='\n                    Tooltip to show on this pie menu option.\n                    ', tunable=sims4.localization.TunableLocalizedStringFactory()), locked_args={'new_pie_menu_category': None})), 'timeout': TunableSimMinute(description='\n            The time it will take for a new string to be generated given the\n            same set of data.\n            ', minimum=0, default=10)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._key_map = {}

    def get_display_names_gen(self):
        for override in self.overrides:
            yield override.new_display_name

    def get_display_name_and_result(self, interaction, target=DEFAULT, context=DEFAULT):
        context = interaction.context if context is DEFAULT else context
        target = interaction.target if target is DEFAULT else target
        key = (context.sim.id, 0 if target is None else target.id, interaction.affordance)
        random_names = getattr(context, 'random_names', dict())
        result = random_names.get(key)
        if result is not None:
            return (result, TestResult.NONE)
        now = services.time_service().sim_now
        result_and_timestamp = self._key_map.get(key)
        if result_and_timestamp is not None:
            time_delta = now - result_and_timestamp[1]
            if self.timeout > time_delta.in_minutes():
                self._key_map[key] = (result_and_timestamp[0], now)
                return (result_and_timestamp[0], TestResult.NONE)
        result = random.choice(self.overrides)
        random_names[key] = result
        setattr(context, 'random_names', random_names)
        self._key_map[key] = (result, now)
        return (result, TestResult.NONE)

class TunableDisplayNameVariant(TunableVariant):
    __qualname__ = 'TunableDisplayNameVariant'

    def __init__(self, **kwargs):
        super().__init__(testable=TestableDisplayName.TunableFactory(), random=RandomDisplayName.TunableFactory(), **kwargs)

class HasDisplayTextMixin:
    __qualname__ = 'HasDisplayTextMixin'
    TEXT_USE_DEFAULT = 0
    TEXT_NONE = 1
    FACTORY_TUNABLES = {'text': TunableVariant(description='\n            Specify the display text to use for this tunable.\n            ', override=TunableLocalizedStringFactory(description='\n                Specify a string override. The tokens are different depending on\n                the type of tunable.\n                '), locked_args={'use_default': TEXT_USE_DEFAULT, 'no_text': TEXT_NONE}, default='use_default')}

    def __init__(self, *args, text=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._HasDisplayTextMixin__display_text = text

    def get_display_text(self):
        if self._HasDisplayTextMixin__display_text == self.TEXT_USE_DEFAULT:
            return self._get_display_text()
        if self._HasDisplayTextMixin__display_text == self.TEXT_NONE:
            return
        return self._HasDisplayTextMixin__display_text(*self._get_display_text_tokens())

    def _get_display_text(self):
        pass

    def _get_display_text_tokens(self):
        return ()

