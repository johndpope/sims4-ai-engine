from objects.components.state import ObjectStateValue
import interactions.utils.tunable
import objects.components
import sims4.tuning.tunable

class FrontDoorTuning:
    __qualname__ = 'FrontDoorTuning'
    FRONT_DOOR_ENABLED_STATE = ObjectStateValue.TunableReference(description='\n        State that will be pushed on portals whenever they are valid for being \n        set as a front door.  This state will be part of the test of many \n        front door interactions.\n        e.g. Set as front door interaction\n        ')
    FRONT_DOOR_DISABLED_STATE = ObjectStateValue.TunableReference(description='\n        State that will be pushed on portals whenever they are not valid to \n        be set as a front door.  This state will be part of the test of many \n        front door interactions.\n        e.g. Set as front door interaction\n        ')

class WelcomeComponent(objects.components.Component, sims4.tuning.tunable.HasTunableFactory, component_name=objects.components.types.WELCOME_COMPONENT, allow_dynamic=True):
    __qualname__ = 'WelcomeComponent'
    FACTORY_TUNABLES = {'affordance_links': interactions.utils.tunable.TunableAffordanceLinkList(description='\n            When an object gets this component, it will be given these affordance as potential interactions.\n            ', class_restrictions=('SuperInteraction',))}

    def __init__(self, owner, affordance_links=()):
        super().__init__(owner)
        self.affordance_links = affordance_links

    @objects.components.componentmethod_with_fallback(lambda _: [])
    def potential_component_interactions(self, context, **kwargs):
        for affordance in self.affordance_links:
            yield affordance.generate_aop(self.owner, context)

