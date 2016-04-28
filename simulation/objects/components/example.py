from sims4.tuning.tunable import Tunable, TunableFactory
from objects.components import Component, componentmethod
from sims4.log import Logger
from objects.components.types import EXAMPLE_COMPONENT
logger = Logger('ExampleComponent')

class ExampleComponent(Component, component_name=EXAMPLE_COMPONENT):
    __qualname__ = 'ExampleComponent'

    def __init__(self, owner, example_name):
        super().__init__(owner)
        self.example_name = example_name

    @componentmethod
    def example_component_method(self, prefix=''):
        logger.warn('{}self={} owner={} example_name={}', prefix, self, self.owner, self.example_name)

    def on_location_changed(self, old_location):
        self.example_component_method('on_location_changed: ')

class TunableExampleComponent(TunableFactory):
    __qualname__ = 'TunableExampleComponent'
    FACTORY_TYPE = ExampleComponent

    def __init__(self, description='Example component, do not use on objects!', callback=None, **kwargs):
        super().__init__(example_name=Tunable(str, 'No name given.', description='Name to use to distinguish this component'), description=description, **kwargs)

