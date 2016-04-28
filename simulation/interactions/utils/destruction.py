from interactions import ParticipantType
from interactions.utils.interaction_elements import XevtTriggeredElement
from protocolbuffers import Consts_pb2
from sims4.tuning.tunable import TunableEnumEntry, OptionalTunable, TunableTuple, TunableRange
from singletons import DEFAULT
from tunable_multiplier import TunableMultiplier
import algos

class ObjectDestructionElement(XevtTriggeredElement):
    __qualname__ = 'ObjectDestructionElement'
    FACTORY_TUNABLES = {'description': 'Destroy one or more participants in an interaction.', 'objects_to_destroy': TunableEnumEntry(ParticipantType, ParticipantType.Object, description='The object(s) to destroy.'), 'award_value': OptionalTunable(TunableTuple(recipients=TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who to award funds to.  If more than one participant is specified, the value will be evenly divided among the recipients.'), multiplier=TunableRange(float, 1.0, description='Value multiplier for the award.'), tested_multipliers=TunableMultiplier.TunableFactory(description='Each multiplier that passes its test set will be applied to each royalty payment.')))}

    def __init__(self, interaction, **kwargs):
        super().__init__(interaction, **kwargs)
        if self.award_value is not None:
            self.award_value_to = self.award_value.recipients
            self.value_multiplier = self.award_value.multiplier
            self.tested_multipliers = self.award_value.tested_multipliers
        else:
            self.award_value_to = None
        self._destroyed_objects = []

    @classmethod
    def on_affordance_loaded_callback(cls, affordance, object_destruction_element):

        def get_simoleon_delta(interaction, target=DEFAULT, context=DEFAULT):
            award_value = object_destruction_element.award_value
            if award_value is None:
                return 0
            target = interaction.target if target is DEFAULT else target
            sim = interaction.sim if context is DEFAULT else context.sim
            destructees = interaction.get_participants(object_destruction_element.objects_to_destroy, sim=sim, target=target)
            total_value = sum(obj.current_value for obj in destructees)
            skill_multiplier = 1 if context is DEFAULT else interaction.get_skill_multiplier(interaction.monetary_payout_multipliers, sim)
            if total_value > 0:
                total_value *= skill_multiplier
            tested_multiplier = award_value.tested_multipliers.get_multiplier(interaction.get_resolver(target=target, context=context))
            return total_value*award_value.multiplier*tested_multiplier

        affordance.register_simoleon_delta_callback(get_simoleon_delta)

    def _destroy_objects(self):
        interaction = self.interaction
        sim = self.interaction.sim
        for object_to_destroy in self._destroyed_objects:
            in_use = object_to_destroy.in_use_by(sim, owner=interaction)
            if object_to_destroy.is_part:
                obj = object_to_destroy.part_owner
            else:
                obj = object_to_destroy
            if in_use:
                obj.transient = True
                obj.remove_from_client()
            else:
                if obj is interaction.target:
                    interaction.set_target(None)
                obj.destroy(source=interaction, cause='Destroying object in basic extra.')

    def _do_behavior(self):
        if self.award_value_to is not None:
            awardees = self.interaction.get_participants(self.award_value_to)
        else:
            awardees = ()
        destructees = self.interaction.get_participants(self.objects_to_destroy)
        if destructees:
            for object_to_destroy in destructees:
                if object_to_destroy.is_in_inventory():
                    inventory = object_to_destroy.get_inventory()
                    inventory.try_remove_object_by_id(object_to_destroy.id)
                else:
                    object_to_destroy.remove_from_client()
                self._destroyed_objects.append(object_to_destroy)
                while awardees:
                    multiplier = self.tested_multipliers.get_multiplier(self.interaction.get_resolver())
                    value = int(object_to_destroy.current_value*self.value_multiplier*multiplier)
                    awards = algos.distribute_total_over_parts(value, [1]*len(awardees))
                    object_to_destroy.current_value = 0
                    interaction_tags = set()
                    if self.interaction is not None:
                        interaction_tags |= self.interaction.get_category_tags()
                    object_tags = frozenset(interaction_tags | object_to_destroy.get_tags())
                    while True:
                        for (recipient, award) in zip(awardees, awards):
                            recipient.family_funds.add(award, Consts_pb2.TELEMETRY_OBJECT_SELL, recipient, tags=object_tags)
            if self.interaction.is_finishing:
                self._destroy_objects()
            else:
                self.interaction.add_exit_function(self._destroy_objects)

