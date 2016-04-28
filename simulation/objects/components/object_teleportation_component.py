import random
from objects.components import Component, types
from objects.components.state import TunableStateValueReference
from sims4.tuning.tunable import HasTunableFactory, TunableVariant, TunableList, TunableTuple, TunableReference, TunableRange, OptionalTunable, TunablePercent, AutoFactoryInit
import placement
import services
import sims4.log
import zone_types
logger = sims4.log.Logger('ObjectTeleportationComponent')

class ObjectTeleportationComponent(Component, HasTunableFactory, AutoFactoryInit, component_name=types.OBJECT_TELEPORTATION_COMPONENT):
    __qualname__ = 'ObjectTeleportationComponent'
    ON_CLIENT_CONNECT = 0
    FACTORY_TUNABLES = {'when_to_teleport': TunableVariant(description='\n            When this object should teleport around.\n            ', locked_args={'on_client_connect': ON_CLIENT_CONNECT}, default='on_client_connect'), 'chance_to_teleport': TunablePercent(description='\n            A percent chance that this object will teleport when the\n            appropriate situation arises.\n            ', default=100), 'required_states': OptionalTunable(TunableList(description='\n            The states this object is required to be in in order to teleport.\n            ', tunable=TunableStateValueReference())), 'objects_to_teleport_near': TunableList(description='\n            A tunable list of static commodities, weights and behavior.  When\n            choosing where to teleport, objects with higher weights have a\n            greater chance of being chosen.\n            \n            If we fail to find a valid location near an object advertising the\n            chosen static commodity, we will search try again with a new object\n            until the list has been exhausted.\n            ', tunable=TunableTuple(description='\n                A static commodity and weight.\n                ', weight=TunableRange(description='\n                    A weight, between 0 and 1, that determines how likely this\n                    static commodity is to be chosen over the others listed.\n                    ', tunable_type=float, minimum=0, maximum=1, default=1), static_commodity=TunableReference(description='\n                    Reference to a type of static commodity.\n                    ', manager=services.static_commodity_manager()), state_change=OptionalTunable(TunableStateValueReference(description='\n                    A state value to apply to the object advertising this\n                    commodity if the teleport succeeds.\n                    '))))}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        zone = services.current_zone()
        if self.when_to_teleport == self.ON_CLIENT_CONNECT and not zone.is_zone_running:
            zone.register_callback(zone_types.ZoneState.CLIENT_CONNECTED, self.teleport)

    def teleport(self):
        if random.random() > self.chance_to_teleport:
            return
        if self.required_states is not None:
            for state in self.required_states:
                while not self.owner.state_value_active(state):
                    return
        weights_and_commodities = [(obj_dict.weight, obj_dict.static_commodity, obj_dict.state_change) for obj_dict in self.objects_to_teleport_near]
        while weights_and_commodities:
            index = sims4.random._weighted(weights_and_commodities)
            (_, static_commodity, state_change) = weights_and_commodities.pop(index)
            motives = set()
            motives.add(static_commodity)
            all_objects = list(services.object_manager().valid_objects())
            random.shuffle(all_objects)
            for obj in all_objects:
                if obj is self.owner:
                    pass
                while obj.commodity_flags & motives:
                    search_flags = placement.FGLSearchFlagsDefault | placement.FGLSearchFlag.SHOULD_TEST_BUILDBUY
                    fgl_context = placement.FindGoodLocationContext(starting_position=obj.position, object_id=self.owner.id, search_flags=search_flags, object_footprints=(self.owner.get_footprint(),))
                    (position, orientation) = placement.find_good_location(fgl_context)
                    if position is not None and orientation is not None:
                        self.owner.transform = sims4.math.Transform(position, orientation)
                        if state_change is not None:
                            obj.set_state(state_change.state, state_change)
                        break

