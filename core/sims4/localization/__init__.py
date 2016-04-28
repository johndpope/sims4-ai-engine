from numbers import Number
import random
from protocolbuffers.Localization_pb2 import LocalizedString, LocalizedStringToken
from sims4.tuning.tunable import Tunable, get_default_display_name, TunableVariant, TunableList, TunableFactory
from singletons import DEFAULT
import sims4.log
logger = sims4.log.Logger('Localization', default_owner='epanero')

def _create_localized_string(string_id, *tokens) -> LocalizedString:
    proto = LocalizedString()
    proto.hash = string_id
    create_tokens(proto.tokens, *tokens)
    return proto

def create_tokens(tokens_msg, *tokens):
    for token in tokens:
        token_msg = tokens_msg.add()
        token_msg.type = LocalizedStringToken.INVALID
        while token is not None:
            if hasattr(token, 'populate_localization_token'):
                token.populate_localization_token(token_msg)
            elif isinstance(token, Number):
                token_msg.type = LocalizedStringToken.NUMBER
                token_msg.number = token
            elif isinstance(token, str):
                token_msg.type = LocalizedStringToken.RAW_TEXT
                token_msg.raw_text = token
            elif isinstance(token, LocalizedString):
                token_msg.type = LocalizedStringToken.STRING
                token_msg.text_string = token

class TunableLocalizedStringFactory(Tunable):
    __qualname__ = 'TunableLocalizedStringFactory'

    class _Wrapper:
        __qualname__ = 'TunableLocalizedStringFactory._Wrapper'
        __slots__ = ('_string_id',)

        def __init__(self, string_id):
            self._string_id = string_id

        def __call__(self, *tokens):
            return _create_localized_string(self._string_id, *tokens)

        def __bool__(self):
            if self._string_id:
                return True
            return False

    def __init__(self, *, default=DEFAULT, description='A localized string that may use tokens.', **kwargs):
        if default is DEFAULT:
            default = 0
        super().__init__(int, default=default, description=description, needs_tuning=False, **kwargs)
        self.cache_key = 'LocalizedStringFactory'

    @property
    def export_class(self):
        return 'TunableLocalizedString'

    @property
    def display_name(self):
        if self._display_name is None:
            name = self.name
            if name is not None and self.name.startswith('create_'):
                name = name[7:]
            return get_default_display_name(name)
        return super().display_name

    def _export_default(self, value):
        if value is not None:
            return hex(value)
        return str(value)

    def _convert_to_value(self, string_id):
        if string_id is None:
            return
        if isinstance(string_id, str):
            string_id = int(string_id, 0)
        return TunableLocalizedStringFactory._Wrapper(string_id)

class TunableLocalizedString(TunableLocalizedStringFactory):
    __qualname__ = 'TunableLocalizedString'

    def __init__(self, *, default=DEFAULT, description='A localized string that may NOT require tokens.', **kwargs):
        super().__init__(description=description, default=default, **kwargs)
        self.cache_key = 'LocalizedString'

    def _convert_to_value(self, string_id):
        if string_id is None:
            return
        return super()._convert_to_value(string_id)()

class TunableLocalizedStringFactoryVariant(TunableVariant):
    __qualname__ = 'TunableLocalizedStringFactoryVariant'
    is_factory = True

    class TunableLocalizedStringFactoryVariation(TunableFactory):
        __qualname__ = 'TunableLocalizedStringFactoryVariant.TunableLocalizedStringFactoryVariation'

        @staticmethod
        def _factory(*args, variations, **kwargs):
            variation = random.choice(variations)
            return variation(*args, **kwargs)

        FACTORY_TYPE = _factory

        def __init__(self, description='A list of possible localized string variations.', **kwargs):
            super().__init__(variations=TunableList(TunableLocalizedStringFactory()), description=description, **kwargs)

    class TunableLocalizedStringVariation(TunableLocalizedStringFactoryVariation):
        __qualname__ = 'TunableLocalizedStringFactoryVariant.TunableLocalizedStringVariation'

        @staticmethod
        def _factory(variations):
            variation = random.choice(variations)
            return variation()

    def __init__(self, description='A localization string. This may either be a single string, or a set to pick a random string from.', **kwargs):
        super().__init__(single=TunableLocalizedStringFactory() if self.is_factory else TunableLocalizedString(), variation=self.TunableLocalizedStringFactoryVariation() if self.is_factory else self.TunableLocalizedStringVariation(), default='single', description=description, **kwargs)

    @property
    def display_name(self):
        if self._display_name is DEFAULT:
            name = self.name
            if name is not None and self.name.startswith('create_'):
                name = name[7:]
            return get_default_display_name(name)
        return super().display_name

class TunableLocalizedStringVariant(TunableVariant):
    __qualname__ = 'TunableLocalizedStringVariant'
    is_factory = False

class LocalizationHelperTuning:
    __qualname__ = 'LocalizationHelperTuning'
    MAX_LIST_LENGTH = 16
    BULLETED_LIST_STRUCTURE = TunableLocalizedStringFactory(description='\n        Localized string that will define the bulleted list start structure,\n        this item will receive a string followed by a bulleted item\n        e.g. {0.String}\n * {1.String}\n        ')
    BULLETED_ITEM_STRUCTURE = TunableLocalizedStringFactory(description='\n        Localized string that will define a single bulleted item.\n        e.g.  * {0.String}\n        ')
    SIM_FIRST_NAME_LOCALIZATION = TunableLocalizedStringFactory(description='\n        Localized string that will recieve a sim and will return the First Name\n        of the sim.\n        e.g. {0.SimFirstName}\n        ')
    OBJECT_NAME_LOCALIZATION = TunableLocalizedStringFactory(description='\n        Localized factory that will receive an object and will return the\n        localized catalog name of that object name\n        e.g. {0.ObjectName} \n        ')
    OBJECT_NAME_INDETERMINATE = TunableLocalizedStringFactory(description='\n        Localized factory that will receive an object and will return the object\n        name preceded by the appropriate indeterminate article.\n        e.g. A/an {0.ObjectName}\n        ')
    OBJECT_NAME_COUNT = TunableLocalizedStringFactory(description='\n        Localized string that defines the pattern for object counts.\n        e.g. {0.Number} {S0.{S1.ObjectName}}{P0.{P1.ObjectName}}\n        ')
    OBJECT_DESCRIPTION_LOCALIZATION = TunableLocalizedStringFactory(description='\n        Localized factory that will receive an object and will return the\n        localized catalog description of that object\n        e.g. {0.ObjectDescription} \n        ')
    NAME_VALUE_PAIR_STRUCTURE = TunableLocalizedStringFactory(description='\n        Localized string that will define the pattern for name-value pairs,\n        e.g. {0.String}: {1.String}\n        ')
    COMMA_LIST_STRUCTURE = TunableLocalizedStringFactory(description='\n        Localized string that will define the format for a comma-separated list.\n        e.g. {0.String}, {1.String}\n        ')
    NEW_LINE_LIST_STRUCTURE = TunableLocalizedStringFactory(description='\n        Localized string that will define the format for two new-line-seperated strings.\n        e.g. {0.String}\n{1.String}\n        ')
    RAW_TEXT = TunableLocalizedStringFactory(description='\n        Localized string that will define take a raw string and set it as a\n        localized string.\n        e.g. {0.String}\n        ')
    MONEY = TunableLocalizedStringFactory(description='\n        Localized string that outputs a Simoleon amount when provided a number.\n        e.g. {0.Money}\n        ')
    ELLIPSIS = TunableLocalizedStringFactory(description='\n        Localized string that outputs a string followed by ellipsis.\n        e.g. {0.String}...\n        ')

    @classmethod
    def get_object_name(cls, obj_def):
        return cls.OBJECT_NAME_LOCALIZATION(obj_def)

    @classmethod
    def get_sim_name(cls, sim):
        return cls.SIM_FIRST_NAME_LOCALIZATION(sim)

    @classmethod
    def get_object_name_indeterminate(cls, obj_def):
        return cls.OBJECT_NAME_INDETERMINATE(obj_def)

    @classmethod
    def get_object_count(cls, count, obj_def):
        return cls.OBJECT_NAME_COUNT(count, obj_def)

    @classmethod
    def get_object_description(cls, obj_def):
        return cls.OBJECT_DESCRIPTION_LOCALIZATION(obj_def)

    @classmethod
    def get_bulleted_list(cls, header_string, *localized_strings):
        bulleted_string = None
        for list_item in tuple(filter(None, localized_strings))[:LocalizationHelperTuning.MAX_LIST_LENGTH]:
            if bulleted_string is None:
                if header_string is None:
                    bulleted_string = cls.BULLETED_ITEM_STRUCTURE(list_item)
                else:
                    bulleted_string = cls.BULLETED_LIST_STRUCTURE(header_string, list_item)
                    bulleted_string = cls.BULLETED_LIST_STRUCTURE(bulleted_string, list_item)
            else:
                bulleted_string = cls.BULLETED_LIST_STRUCTURE(bulleted_string, list_item)
        return bulleted_string

    @classmethod
    def get_name_value_pair(cls, name_string, value_string):
        return cls.NAME_VALUE_PAIR_STRUCTURE(name_string, value_string)

    @classmethod
    def get_comma_separated_list(cls, *strings):
        return cls._get_string_separated_string(separator=cls.COMMA_LIST_STRUCTURE, *strings)

    @classmethod
    def get_new_line_separated_strings(cls, *strings):
        return cls._get_string_separated_string(separator=cls.NEW_LINE_LIST_STRUCTURE, *strings)

    @classmethod
    def _get_string_separated_string(cls, *strings, separator):
        if not strings:
            return
        result = strings[0]
        for string in strings[1:LocalizationHelperTuning.MAX_LIST_LENGTH]:
            result = separator(result, string)
        return result

    @classmethod
    def get_raw_text(cls, text):
        return cls.RAW_TEXT(text)

    @classmethod
    def get_money(cls, money_amount):
        return cls.MONEY(money_amount)

    @classmethod
    def get_ellipsized_text(cls, text):
        return cls.ELLIPSIS(text)

