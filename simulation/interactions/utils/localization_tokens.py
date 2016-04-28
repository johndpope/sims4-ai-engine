import collections
from interactions import ParticipantType
from objects.game_object_properties import GameObjectProperty
from sims4.tuning.tunable import AutoFactoryInit, HasTunableSingletonFactory, TunableList, TunableVariant, TunableTuple, TunableEnumEntry, TunableReference
import services

class LocalizationTokens(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'LocalizationTokens'
    TOKEN_PARTICIPANT = 0
    TOKEN_MONEY = 1
    TOKEN_STATISTIC = 2
    TOKEN_OBJECT_PROPERTY = 3
    TOKEN_INTERACTION_COST = 4
    TOKEN_DEFINITION = 5
    _DatalessToken = collections.namedtuple('_DatalessToken', 'token_type')
    FACTORY_TUNABLES = {'tokens': TunableList(description="\n            A list of tokens that will be returned by this factory. Any string\n            that uses this token will have token '0' be set to the first\n            element, '1' to the second element, and so on. Do not let the list\n            inheritance values confuse you; regardless of what the list element\n            index is, the first element will always be 0, the second element 1,\n            and so on.\n            ", tunable=TunableVariant(description='\n                Define what the token at the specified index is.\n                ', participant_type=TunableTuple(description='\n                    The token is a Sim or object participant from the\n                    interaction.\n                    ', locked_args={'token_type': TOKEN_PARTICIPANT}, participant=TunableEnumEntry(tunable_type=ParticipantType, default=ParticipantType.Actor)), definition=TunableTuple(description="\n                    A catalog definition to use as a token. This is useful if\n                    you want to properly localize an object's name or\n                    description.\n                    ", locked_args={'token_type': TOKEN_DEFINITION}, definition=TunableReference(manager=services.definition_manager())), money_amount=TunableTuple(description='\n                    The token is a number representing the amount of Simoleons\n                    that were awarded in loot to the specified participant.\n                    ', locked_args={'token_type': TOKEN_MONEY}, participant=TunableEnumEntry(description='\n                        The participant for whom we fetch the earned amount of\n                        money.\n                        ', tunable_type=ParticipantType, default=ParticipantType.Actor)), statistic_value=TunableTuple(description='\n                    The token is a number representing the value of a specific\n                    statistic from the selected participant.\n                    ', locked_args={'token_type': TOKEN_STATISTIC}, participant=TunableEnumEntry(description="\n                        The participant from whom we will fetch the specified\n                        statistic's value.\n                        ", tunable_type=ParticipantType, default=ParticipantType.Actor), statistic=TunableReference(description="\n                        The statistic's whose value we want to fetch.\n                        ", manager=services.statistic_manager())), object_property=TunableTuple(description='\n                    The token is a property of a game object.  This could be \n                    catalog properties like its price or its rarity which is a \n                    property given by a component.\n                    ', locked_args={'token_type': TOKEN_OBJECT_PROPERTY}, obj_property=TunableEnumEntry(description='\n                        The property of the object that we will request.\n                        ', tunable_type=GameObjectProperty, default=GameObjectProperty.CATALOG_PRICE)), locked_args={'interaction_cost': _DatalessToken(token_type=TOKEN_INTERACTION_COST)}, default='participant_type'))}

    def _get_token(self, resolver, token_data):
        if token_data.token_type == self.TOKEN_PARTICIPANT:
            participant = resolver.get_participant(participant_type=token_data.participant)
            return participant
        if token_data.token_type == self.TOKEN_DEFINITION:
            return token_data.definition
        if token_data.token_type == self.TOKEN_MONEY:
            interaction = getattr(resolver, 'interaction', None)
            if interaction is not None:
                from interactions.money_payout import MoneyLiability
                money_liability = interaction.get_liability(MoneyLiability.LIABILITY_TOKEN)
                if money_liability is not None:
                    return money_liability.amounts[token_data.participant]
                return 0
        if token_data.token_type == self.TOKEN_STATISTIC:
            participant = resolver.get_participant(participant_type=token_data.participant)
            if participant is not None:
                tracker = participant.get_tracker(token_data.statistic)
                if tracker is not None:
                    return tracker.get_value(token_data.statistic)
        if token_data.token_type == self.TOKEN_OBJECT_PROPERTY:
            participant = resolver._obj.get_object_property(token_data.obj_property)
            return participant
        if token_data.token_type == self.TOKEN_INTERACTION_COST:
            interaction = getattr(resolver, 'interaction', None)
            if interaction is not None:
                return interaction.get_simoleon_cost()

    def get_tokens(self, resolver):
        return tuple(self._get_token(resolver, token_data) for token_data in self.tokens)

