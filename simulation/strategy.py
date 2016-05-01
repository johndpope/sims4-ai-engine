from sims4.tuning.instances import TunedInstanceMetaclass
from sims4.tuning.tunable import Tunable, TunableList, TunableReference, OptionalTunable, HasTunableFactory
import services
import sims4.resources


class TunablePutDownStrategy(
        HasTunableFactory,
        metaclass=TunedInstanceMetaclass,
        manager=services.get_instance_manager(sims4.resources.Types.STRATEGY)):
    __qualname__ = 'TunablePutDownStrategy'
    INSTANCE_TUNABLES = {
        'preferred_slot_cost': OptionalTunable(
            enabled_by_default=True,
            tunable=
            Tunable(description=
                    '\n                    Base cost for a slot that this object prefers.\n                    ',
                    tunable_type=float,
                    default=0)),
        'normal_slot_cost': OptionalTunable(
            enabled_by_default=True,
            tunable=Tunable(
                description=
                '\n                    Base score for a slot that this object does not prefer.\n                    ',
                tunable_type=float,
                default=1)),
        'object_inventory_cost': OptionalTunable(
            enabled_by_default=True,
            tunable=Tunable(
                description=
                '\n                    Base cost for a sim putting the object in a valid object\n                    inventory.\n                    ',
                tunable_type=float,
                default=5)),
        'floor_cost': OptionalTunable(
            enabled_by_default=True,
            tunable=Tunable(
                description=
                '\n                    The base cost used to compare putting an object on the ground\n                    with other options.\n                    ',
                tunable_type=float,
                default=15)),
        'inventory_cost': OptionalTunable(
            enabled_by_default=True,
            tunable=Tunable(
                description=
                '\n                    Cost for how likely a sim puts the object in their inventory\n                    instead of putting it down.\n                    ',
                tunable_type=float,
                default=20)),
        'affordances': TunableList(
            description=
            '\n                A list of interactions that should be considered to be an\n                alternative to putting the object down.\n                ',
            tunable=TunableReference(services.get_instance_manager(
                sims4.resources.Types.INTERACTION))),
        'put_down_on_terrain_facing_sim': Tunable(
            description=
            "\n                If true, the object will face the Sim when placing it on\n                terrain.  Guitars and violins will enable this so they don't\n                pop 180 degrees after the Sim puts it down. \n                ",
            tunable_type=bool,
            default=False),
        'ideal_slot_type_set': OptionalTunable(TunableReference(
            description=
            "\n                 If specified, this set of slots will have the cost specified\n                 in the 'preferred_slot_cost' field in put_down_tuning.\n                 \n                 This allows us to tell Sims to weight specific slot types\n                 higher than others when considering where to put down this\n                 object.\n                 ",
            manager=services.get_instance_manager(
                sims4.resources.Types.SLOT_TYPE_SET)))
    }
    FACTORY_TUNABLES = {}
    FACTORY_TUNABLES.update(INSTANCE_TUNABLES)
