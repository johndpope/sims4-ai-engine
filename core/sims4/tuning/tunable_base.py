import inspect
import sims4.log
import sims4.reload
import sims4.resources
logger = sims4.log.Logger('Tuning')
DELETEDMARKER = object()
with sims4.reload.protected(globals()):
    TDESC_FRAG_DICT_GLOBAL = {}
    DISABLE_FRAG_DUP_NAME_CHECK = False

class Tags:
    __qualname__ = 'Tags'
    Module = 'Module'
    Class = 'Class'
    Instance = 'Instance'
    Tunable = 'Tunable'
    List = 'TunableList'
    Variant = 'TunableVariant'
    Tuple = 'TunableTuple'
    Enum = 'TunableEnum'
    EnumItem = 'EnumItem'
    Check = 'Check'
    Deleted = 'Deleted'
    TdescFragTag = 'TdescFragTag'

class LoadingTags:
    __qualname__ = 'LoadingTags'
    Module = 'M'
    Class = 'C'
    Instance = 'I'
    Tunable = 'T'
    List = 'L'
    Variant = 'V'
    Tuple = 'U'
    Enum = 'E'

class GroupNames:
    __qualname__ = 'GroupNames'
    GENERAL = 'General'
    ANIMATION = 'Animation'
    AUDIO = 'Audio'
    AUTONOMY = 'Autonomy'
    AVAILABILITY = 'Availability'
    CLOTHING_CHANGE = 'Clothing Change'
    COMPONENTS = 'Components'
    POSTURE = 'Posture'
    UI = 'UI'
    ROLES = 'Roles'
    SCORING = 'Scoring'
    SITUATION = 'Situation'
    TRIGGERS = 'Triggers'
    SPECIAL_CASES = 'Special Cases'
    PUDDLES = 'Puddles'
    FISHING = 'Fishing'
    NPC_HOSTED_EVENTS = 'NPC Hosted Events'
    PICKERTUNING = 'Picker Tuning'
    VENUES = 'Venues'
    CREATE_CARRYABLE = 'Carry Creation'
    MULTIPLIERS = 'Multipliers'
    GOALS = 'Goals'
    ON_CREATION = 'On Creation'
    TESTS = 'Tests'
    TRAVEL = 'Travel'
    DEPRECATED = 'XXX Deprecated'

class RateDescriptions:
    __qualname__ = 'RateDescriptions'
    PER_SIM_MINUTE = 'per Sim minute'
    PER_SIM_HOUR = 'per Sim hour'

class FilterTag:
    __qualname__ = 'FilterTag'
    DEFAULT = 0
    EXPERT_MODE = 1

class LoadingAttributes:
    __qualname__ = 'LoadingAttributes'
    Name = 'n'
    Class = 'c'
    VariantType = 't'
    InstanceModule = 'm'
    InstanceClass = 'c'
    InstanceType = 'i'
    EnumValue = 'ev'

class Attributes:
    __qualname__ = 'Attributes'
    Name = 'name'
    DisplayName = 'display'
    Description = 'description'
    Group = 'group'
    Filter = 'filter'
    Type = 'type'
    Class = 'class'
    Default = 'default'
    PackSafe = 'pack_safe'
    Min = 'min'
    Max = 'max'
    RateDescription = 'rate_description'
    VariantType = 'type'
    InstanceModule = 'module'
    InstanceClass = 'class'
    InstancePath = 'path'
    InstanceParents = 'parents'
    InstanceType = 'instance_type'
    InstanceSubclassesOnly = 'instance_subclasses_only'
    InstanceUseGuidForRef = 'use_guid_for_reference'
    StaticEnumEntries = 'static_entries'
    DynamicEnumEntries = 'dynamic_entries'
    EnumValue = 'enum_value'
    EnumBitFlag = 'enum_bit_flag'
    EnumLocked = 'enum_locked'
    Deprecated = 'deprecated'
    DisplaySorted = 'enum_sorted'
    Partitioned = 'enum_partitioned'
    UniqueEntries = 'unique_entries'
    ResourceTypes = 'resource_types'
    ValidationCategory = 'category'
    ValidationMethod = 'method'
    ValidationArgument = 'argument'
    ReferenceRestriction = 'restrict'
    ExportModes = 'export_modes'
    SourceLocation = 'choice_source'
    SourceQuery = 'choice_query'
    SourceSubQuery = 'choice_subquery'
    MappingKey = 'mapping_key'
    MappingValue = 'mapping_value'
    MappingClass = 'mapping_class'
    TdescFragType = 'tdescfrag'
    TdescFragClass = 'TdescFrag'
    DynamicEntriesPrefixFilter = 'dynamic_entries_prefix'
    TuningState = 'tuning_state'
    NeedsTuning = 'NeedsTuning'

class ExportModes:
    __qualname__ = 'ExportModes'
    ClientBinary = 'client_binary'
    ServerBinary = 'server_binary'
    ServerXML = 'server_xml'
    All = (ClientBinary, ServerBinary, ServerXML)

class SourceQueries:
    __qualname__ = 'SourceQueries'
    ASMState = 'ASM:StateNames'
    ASMActorAll = 'ASM:ActorNames'
    ASMActorSim = 'ASM:ActorNames(Sim)'
    ASMActorObject = 'ASM:ActorNames(Object)'
    ASMActorProp = 'ASM:ActorNames(Prop)'
    ASMClip = 'ASM:ClipResourcesInStates({})'
    SwingEnumNamePattern = 'SwingSupport:EnumNames({})'

class SourceSubQueries:
    __qualname__ = 'SourceSubQueries'
    ClipEffectName = 'ClipResource:ClipEventActorNames(EffectEvent)'
    ClipSoundName = 'ClipResource:ClipEventActorNames(SoundEvent)'

class TunableReadOnlyError(AttributeError):
    __qualname__ = 'TunableReadOnlyError'

    def __init__(self, name):
        self.name = name

    def __str__(self):
        return 'Attempting to write to read-only tunable - ' + self.name

class TunableAliasError(Exception):
    __qualname__ = 'TunableAliasError'

    def __init__(self, name):
        self.name = name

    def __str__(self):
        return 'Attempting to alias another tunable - ' + self.name

class TunableFileReadOnlyError(Exception):
    __qualname__ = 'TunableFileReadOnlyError'

    def __init__(self, name):
        self.name = name

    def __str__(self):
        return 'Failed to write Tuning file - ' + self.name + ', as it is marked read-only.'

class MalformedTuningSchemaError(Exception):
    __qualname__ = 'MalformedTuningSchemaError'

    def __init__(self, name):
        self.name = name

    def __str__(self):
        return 'Malformed tunable specified: ' + self.name

class TunableTypeNotSupportedError(Exception):
    __qualname__ = 'TunableTypeNotSupportedError'

    def __init__(self, t):
        self._type = t

    def __str__(self):
        return 'Bad type: {0}'.format(self._type)

class BoolWrapper:
    __qualname__ = 'BoolWrapper'
    EXPORT_STRING = 'bool'

    def __new__(cls, data):
        if isinstance(data, str):
            data_lower = data.lower()
            if data_lower == 'true' or data_lower == 't':
                return True
            if data_lower == 'false' or data_lower == 'f':
                return False
            raise ValueError("Invalid string supplied to TunableBool: {0}\nExpected 'True' or 'False'.".format(data))
        else:
            return bool(data)

tunable_type_mapping = {int: int, float: float, str: str, bool: BoolWrapper, BoolWrapper: BoolWrapper, sims4.resources.Key: sims4.resources.ResourceKeyWrapper, sims4.resources.ResourceKeyWrapper: sims4.resources.ResourceKeyWrapper}

def get_default_display_name(name):
    if name is None:
        return
    return name.replace('_', ' ').strip().title()

BASIC_DESC_KEY = (Attributes.Name, Attributes.DisplayName, Attributes.Description, Attributes.Class, Attributes.Filter, Attributes.Group, Attributes.ValidationCategory, Tags.Check, Attributes.TuningState, Attributes.ExportModes)

def export_fragment_tag(self):
    export_desc = self.frag_desc()
    for key in list(export_desc.keys()):
        while key not in BASIC_DESC_KEY:
            del export_desc[key]
    return export_desc

class TdescFragMetaClass(type):
    __qualname__ = 'TdescFragMetaClass'

    def __new__(cls, name, *args, is_fragment=False, **kwargs):
        self_cls = super().__new__(cls, name, *args, **kwargs)
        self_cls.is_fragment = is_fragment
        if is_fragment:
            if not (not DISABLE_FRAG_DUP_NAME_CHECK and name in TDESC_FRAG_DICT_GLOBAL and sims4.reload.currently_reloading):
                raise AssertionError('Frag Class with name {} already exists'.format(name))
            TDESC_FRAG_DICT_GLOBAL[name] = self_cls
            self_cls.frag_desc = self_cls.export_desc
            self_cls.FRAG_TAG_NAME = self_cls.TAGNAME
            self_cls.TAGNAME = Tags.TdescFragTag
            self_cls.export_desc = export_fragment_tag
        return self_cls

    def __init__(self, *args, **kwargs):
        super().__init__(*args)

RESERVED_KWARGS = set(['description', 'category', 'checks', 'callback', 'verify_tunable_callback', 'export_modes', 'display_name', '_display_name', 'deferred', 'needs_tuning', 'tuning_group', 'tuning_filter', 'default', 'is_fragment', 'cache_key'])

class TunableBase(metaclass=TdescFragMetaClass):
    __qualname__ = 'TunableBase'
    __slots__ = ('name', 'description', '_category', '_checks', 'callback', 'verify_tunable_callback', 'export_modes', '_display_name', 'deferred', 'needs_deferring', 'needs_tuning', 'group', 'tuning_filter', 'is_fragment', 'cache_key', '_has_callback', '_has_verify_tunable_callback')
    TAGNAME = Tags.Tunable
    LOADING_TAG_NAME = LoadingTags.Tunable
    FRAG_TAG_NAME = None

    def __init__(self, *, description=None, category=None, checks=None, callback=None, verify_tunable_callback=None, export_modes=(), display_name=None, deferred=False, needs_tuning=False, tuning_group=GroupNames.GENERAL, tuning_filter=FilterTag.DEFAULT):
        self.description = description
        self._category = category
        self._checks = checks
        self._display_name = display_name
        self.group = tuning_group
        self.tuning_filter = tuning_filter
        if isinstance(callback, staticmethod):
            callback = callback.__func__
        self.callback = callback
        if isinstance(verify_tunable_callback, staticmethod):
            verify_tunable_callback = verify_tunable_callback.__func__
        self.verify_tunable_callback = verify_tunable_callback
        self.name = None
        if isinstance(export_modes, tuple):
            self.export_modes = export_modes
        else:
            self.export_modes = (export_modes,)
        self.deferred = deferred
        self.needs_tuning = needs_tuning
        self.needs_deferring = False
        self.cache_key = self.TAGNAME
        self._has_callback = self.callback is not None
        self._has_verify_tunable_callback = self.verify_tunable_callback is not None

    def __repr__(self):
        classname = type(self).__name__
        name = getattr(self, 'name', None)
        r = '<{}'.format(classname)
        if name:
            r = '{} {}'.format(r, name)
        r = '{}>'.format(r)
        return r

    def __set__(self, instance, owner):
        raise TunableReadOnlyError(str(self))

    @property
    def default(self):
        return self._default

    @property
    def display_name(self):
        if self._display_name is not None:
            return self._display_name
        return get_default_display_name(self.name)

    @property
    def export_class(self):
        return self.__class__.__name__

    @property
    def has_callback(self):
        return self._has_callback

    @property
    def has_verify_tunable_callback(self):
        return self._has_verify_tunable_callback

    @property
    def is_exporting_to_client(self):
        return ExportModes.ClientBinary in self.export_modes

    def export_desc(self):
        description = self.description
        if description is not None:
            description = inspect.cleandoc(description)
        export_dict = {Attributes.Name: self.name, Attributes.DisplayName: self.display_name, Attributes.Description: description, Attributes.Class: self.export_class, Attributes.Filter: self.tuning_filter, Attributes.Group: self.group}
        if self._category:
            export_dict[Attributes.ValidationCategory] = self._category
        if self._checks:
            export_dict[Tags.Check] = [{Attributes.Type: check[0], Attributes.ValidationArgument: check[1]} for check in self._checks]
        if self.needs_tuning:
            export_dict[Attributes.TuningState] = Attributes.NeedsTuning
        if self.export_modes:
            export_dict[Attributes.ExportModes] = ','.join(self.export_modes)
        return export_dict

    def _export_default(self, value):
        return str(value)

    def load_etree_node(self, **kwargs):
        raise NotImplementedError('load method for a tunable is undefined.')

    def invoke_callback(self, instance_class, tunable_name, source, value):
        if self.callback is not None:
            self.callback(instance_class, tunable_name, source, value)

    def invoke_verify_tunable_callback(self, instance_class, tunable_name, source, value):
        if self.verify_tunable_callback is not None:
            self.verify_tunable_callback(instance_class, tunable_name, source, value)

