from collections import namedtuple
import random
from interactions import ParticipantType
from interactions.utils.loot_basic_op import BaseLootOperation, BaseTargetedLootOperation
from interactions.utils.notification import NotificationElement
from element_utils import build_critical_section_with_finally
from sims4.localization import LocalizationHelperTuning
from sims4.tuning.tunable import TunableList, TunableTuple, TunableReference, TunableEnumEntry, TunableFactory, OptionalTunable, TunableVariant, TunableRange
from traits.traits import Trait
import enum
import interactions.utils
import services
import sims4.log
logger = sims4.log.Logger('Relationship')

class RelationshipBitOperationType(enum.Int):
    __qualname__ = 'RelationshipBitOperationType'
    INVALID = 0
    ADD = 1
    REMOVE = 2

_BitOperationTuple = namedtuple('_BitOperationTuple', ['operation', 'bit', 'recipients', 'targets'])

class RelationshipBitChange(BaseLootOperation):
    __qualname__ = 'RelationshipBitChange'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        for op in value._bit_operations:
            pass

    FACTORY_TUNABLES = {'bit_operations': TunableList(description='\n            List of operations to perform.', tunable=TunableTuple(description='\n                Tuple describing the operation to perform', bit=TunableReference(description='\n                    The bit to be manipulated', manager=services.get_instance_manager(sims4.resources.Types.RELATIONSHIP_BIT)), operation=TunableEnumEntry(description='\n                    The operation to perform.', tunable_type=RelationshipBitOperationType, default=RelationshipBitOperationType.INVALID), recipients=TunableEnumEntry(description='\n                    The sim(s) to apply the bit operation to.', tunable_type=ParticipantType, default=ParticipantType.Invalid), targets=TunableEnumEntry(description='\n                    The target sim(s) for each bit interaction.', tunable_type=ParticipantType, default=ParticipantType.Invalid))), 'locked_args': {'subject': ParticipantType.Invalid}, 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, bit_operations, **kwargs):
        super().__init__(**kwargs)
        self._bit_operations = []
        if bit_operations:
            for bit_operation in bit_operations:
                unpacked_bit_operation = _BitOperationTuple(operation=bit_operation.operation, bit=bit_operation.bit, recipients=bit_operation.recipients, targets=bit_operation.targets)
                if unpacked_bit_operation.operation == RelationshipBitOperationType.INVALID:
                    logger.error('Operation set to <invalid> on bit {0}', bit_operation.bit)
                if unpacked_bit_operation.bit is None:
                    logger.error('Bit is invalid on interaction')
                if unpacked_bit_operation.recipients is None:
                    logger.error('No recipiets for bit {0}', bit_operation.bit)
                if unpacked_bit_operation.targets is None:
                    logger.error('No targets for bit {0}', bit_operation.bit)
                self._bit_operations.append(unpacked_bit_operation)

    @property
    def subject(self):
        for bit_op in self._bit_operations:
            pass

    @property
    def loot_type(self):
        return interactions.utils.LootType.RELATIONSHIP_BIT

    def apply_to_resolver(self, resolver, skip_test=False):
        if not skip_test and not self.test_resolver(resolver):
            return (False, None)
        participant_cache = dict()
        for bit_operation in self._bit_operations:
            if bit_operation.recipients not in participant_cache:
                participant_cache[bit_operation.recipients] = resolver.get_participants(bit_operation.recipients)
            while bit_operation.targets not in participant_cache:
                participant_cache[bit_operation.targets] = resolver.get_participants(bit_operation.targets)
        for bit_operation in self._bit_operations:
            for recipient in participant_cache[bit_operation.recipients]:
                for target in participant_cache[bit_operation.targets]:
                    if recipient == target:
                        pass
                    if bit_operation.operation == RelationshipBitOperationType.ADD:
                        recipient.relationship_tracker.add_relationship_bit(target.sim_id, bit_operation.bit)
                    elif bit_operation.operation == RelationshipBitOperationType.REMOVE:
                        recipient.relationship_tracker.remove_relationship_bit(target.sim_id, bit_operation.bit)
                    else:
                        raise NotImplementedError
        return True

class TunableRelationshipBitElement(TunableFactory):
    __qualname__ = 'TunableRelationshipBitElement'

    @staticmethod
    def _factory(interaction, relationship_bits_begin, relationship_bits_end, sequence=()):

        def begin(_):
            relationship_bits_begin.apply_to_resolver(interaction.get_resolver())

        def end(_):
            relationship_bits_end.apply_to_resolver(interaction.get_resolver())

        return build_critical_section_with_finally(begin, sequence, end)

    def __init__(self, description='A book-ended set of relationship bit operations.', **kwargs):
        super().__init__(relationship_bits_begin=RelationshipBitChange.TunableFactory(description='A list of relationship bit operations to perform at the beginning of the interaction.'), relationship_bits_end=RelationshipBitChange.TunableFactory(description='A list of relationship bit operations to performn at the end of the interaction'), description=description)

    FACTORY_TYPE = _factory

class KnowOtherSimTraitOp(BaseTargetedLootOperation):
    __qualname__ = 'KnowOtherSimTraitOp'
    TRAIT_SPECIFIED = 0
    TRAIT_RANDOM = 1
    TRAIT_ALL = 2
    FACTORY_TUNABLES = {'traits': TunableVariant(description='\n            The traits that the subject may learn about the target.\n            ', specified=TunableTuple(description='\n                Specify individual traits that can be learned.\n                ', locked_args={'learned_type': TRAIT_SPECIFIED}, potential_traits=TunableList(description='\n                    A list of traits that the subject may learn about the target.\n                    ', tunable=Trait.TunableReference())), random=TunableTuple(description='\n                Specify a random number of traits to learn.\n                ', locked_args={'learned_type': TRAIT_RANDOM}, count=TunableRange(description='\n                    The number of potential traits the subject may learn about\n                    the target.\n                    ', tunable_type=int, default=1, minimum=1)), all=TunableTuple(description="\n                The subject Sim may learn all of the target's traits.\n                ", locked_args={'learned_type': TRAIT_ALL}), default='specified'), 'notification': OptionalTunable(description="\n            Specify a notification that will be displayed for every subject if\n            information is learned about each individual target_subject. This\n            should probably be used only if you can ensure that target_subject\n            does not return multiple participants. The first two additional\n            tokens are the Sim and target Sim, respectively. A third token\n            containing a string with a bulleted list of trait names will be a\n            String token in here. If you are learning multiple traits, you\n            should probably use it. If you're learning a single trait, you can\n            get away with writing specific text that does not use this token.\n            ", tunable=NotificationElement.TunableFactory(locked_args={'recipient_subject': None})), 'notification_no_more_traits': OptionalTunable(description='\n            Specify a notification that will be displayed when a Sim knows\n            all traits of another target Sim.\n            ', tunable=NotificationElement.TunableFactory(locked_args={'recipient_subject': None}))}

    def __init__(self, *args, traits, notification, notification_no_more_traits, **kwargs):
        super().__init__(*args, **kwargs)
        self.traits = traits
        self.notification = notification
        self.notification_no_more_traits = notification_no_more_traits

    @property
    def loot_type(self):
        return interactions.utils.LootType.RELATIONSHIP_BIT

    @staticmethod
    def _select_traits(knowledge, trait_tracker, random_count=None):
        traits = tuple(trait for trait in trait_tracker.personality_traits if trait not in knowledge.known_traits)
        if random_count is not None and traits:
            return random.sample(traits, min(random_count, len(traits)))
        return traits

    def _apply_to_subject_and_target(self, subject, target, resolver):
        knowledge = subject.relationship_tracker.get_knowledge(target.sim_id, initialize=True)
        trait_tracker = target.trait_tracker
        knowledge.set_num_traits(len(trait_tracker.personality_traits))
        if self.traits.learned_type == self.TRAIT_SPECIFIED:
            traits = tuple(trait for trait in self.traits.potential_traits if trait_tracker.has_trait(trait) and trait not in knowledge.known_traits)
        elif self.traits.learned_type == self.TRAIT_ALL:
            traits = self._select_traits(knowledge, trait_tracker)
        elif self.traits.learned_type == self.TRAIT_RANDOM:
            traits = self._select_traits(knowledge, trait_tracker, random_count=self.traits.count)
            if not traits and self.notification_no_more_traits is not None:
                interaction = resolver.interaction
                if interaction is not None:
                    self.notification_no_more_traits(interaction).show_notification(additional_tokens=(subject, target), recipients=(subject,), icon_override=(None, target))
        for trait in traits:
            knowledge.add_known_trait(trait)
        if traits:
            interaction = resolver.interaction
            if interaction is not None and self.notification is not None:
                trait_string = LocalizationHelperTuning.get_bulleted_list(None, *(trait.display_name(target) for trait in traits))
                self.notification(interaction).show_notification(additional_tokens=(subject, target, trait_string), recipients=(subject,), icon_override=(None, target))

