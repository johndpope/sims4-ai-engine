from event_testing.resolver import SingleObjectResolver
from interactions.utils.localization_tokens import LocalizationTokens
from objects.components import Component, types, componentmethod_with_fallback
from objects.hovertip import HovertipStyle, TooltipFields
from protocolbuffers import Area_pb2, Consts_pb2, UI_pb2, UI_pb2 as ui_protocols
from sims4.localization import TunableLocalizedStringFactoryVariant, LocalizationHelperTuning
from sims4.tuning.tunable import HasTunableSingletonFactory, AutoFactoryInit, OptionalTunable, TunableList, TunableTuple, TunableEnumEntry, HasTunableFactory, TunableMapping, Tunable, TunableReference
from situations.service_npcs.modify_lot_items_tuning import TunableObjectModifyTestSet
import services
import sims4.resources

class TooltipText(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'TooltipText'
    FACTORY_TUNABLES = {'text': TunableLocalizedStringFactoryVariant(description='\n            Text that will be displayed on the tuned tooltip_fields of the \n            tooltip.\n            '), 'text_tokens': OptionalTunable(description="\n            If enabled, localization tokens to be passed into 'text' can be\n            explicitly defined. For example, you could use a participant that is\n            not normally used, such as a owned sim. Or you could also\n            pass in statistic and commodity values. If disabled, the standard\n            tokens from the interaction will be used (such as Actor and\n            TargetSim).\n            Participants tuned here should only be relevant to objects.  If \n            you try to tune a participant which only exist when you run an \n            interaction (e.g. carry_target) tooltip wont show anything.\n            ", tunable=LocalizationTokens.TunableFactory())}

class TooltipProvidingComponentMixin:
    __qualname__ = 'TooltipProvidingComponentMixin'

    def on_added_to_inventory(self):
        self.owner.update_ui_metadata(use_cache=False)

class TooltipComponent(Component, TooltipProvidingComponentMixin, HasTunableFactory, AutoFactoryInit, component_name=types.TOOLTIP_COMPONENT):
    __qualname__ = 'TooltipComponent'
    FACTORY_TUNABLES = {'custom_tooltips': TunableList(description='\n            List of possible tooltips that will be displayed on an object when\n            moused over.\n            Each tooltip has its set of tests which will be evaluated whenever\n            the object its created or when its state changes.  The test that \n            passes its the tooltip that the object will display.\n            ', tunable=TunableTuple(description='\n                Variation of tooltips that may show when an object is hover \n                over.\n                Which tooltip is shows will depend on the object_tests that are \n                tuned.    \n                ', object_tests=TunableObjectModifyTestSet(description='\n                    All least one subtest group (AKA one list item) must pass\n                    within this list for the tooltip values to be valid on the \n                    object.\n                    '), tooltip_style=TunableEnumEntry(description="\n                    Types of possible tooltips that can be displayed for an\n                    object.  It's recomended to use default or \n                    HOVER_TIP_CUSTOM_OBJECT on most objects. \n                    ", tunable_type=HovertipStyle, default=HovertipStyle.HOVER_TIP_DEFAULT), tooltip_fields=TunableMapping(description='\n                    Mapping of tooltip fields to its localized values.  Since \n                    this fields are created from a system originally created \n                    for recipes, all of them may be tuned, but these are the \n                    most common fields to show on a tooltip:\n                    - recipe_name = This is the actual title of the tooltip.  \n                    This is the main text\n                    - recipe_description = This description refers to the main \n                    text that will show below the title\n                    - header = Smaller text that will show just above the title\n                    - subtext = Smaller text that will show just bellow the \n                    title\n                    ', key_type=TunableEnumEntry(description='\n                        Fields to be populated in the tooltip.  These fields\n                        will be populated with the text and tokens tuned.\n                        ', tunable_type=TooltipFields, default=TooltipFields.recipe_name), value_type=TooltipText.TunableFactory()))), 'state_value_numbers': TunableList(description='\n            Ordered list mapping a state value to a number that will be passed\n            as token to the State Value String.  Will use the number associated\n            with the first state matched.\n            \n            e.g.\n            if the object has all the states and the list looks like:\n            state value masterwork\n            state value poor quality\n            \n            then the number passed to the State Value Strings will be the number\n            associated with the masterwork state.\n            \n            Does *not* have to be the same size or states as the state value\n            strings\n            ', tunable=TunableTuple(description='\n                Map of state value to an number that will be passed as token to\n                the state value strings   \n                ', state_value=TunableReference(description='\n                    The state value for the associated number\n                    ', manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions='ObjectStateValue'), number=Tunable(description='\n                    Number passed to localization as the token for the state value\n                    strings below\n                    ', tunable_type=float, default=0))), 'state_value_strings': TunableList(description='\n            List of lists of mapping a state value to a localized string.\n            The first string mapped to a valid state in each sub list will be\n            added.\n            \n            e.g.\n            if the object has all the states and the lists look like:\n            List 1:\n                state_value masterwork\n                state_value poor quality\n            list 2:\n                state_value flirty\n                \n            then it will show the strings for masterwork and flirty, but\n            not the string for poor quality.\n            \n            Does *not* have to be the same size or states as the state value \n            numbers.  Additionally, it does *not* have to utilize the number\n            passed in as token from State Value Numbers.  i.e. if something is \n            *always* Comfort: 5, regardless of quality, the string can simply \n            be "Comfort: 5".\n            ', tunable=TunableList(description='\n                Ordered list mapping a state value to a localized string.\n                The first string mapped to a valid state will be added.\n                ', tunable=TunableTuple(description='\n                    Map of state value to a string\n                    ', state_value=TunableReference(description='\n                        The state value for the associated string\n                        ', manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions='ObjectStateValue'), text=TunableLocalizedStringFactoryVariant(description='\n                        Text that will be displayed if the object has the\n                        associated state value, with any number matched to a state\n                        in state value numbers passed in as {0.Number}, defaulting to\n                        0 if no state in the state value numbers matches\n                        '))))}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ui_metadata_handles = []

    @componentmethod_with_fallback(lambda : None)
    def update_object_tooltip(self):
        if services.client_manager() is None:
            pass
        else:
            old_handles = list(self._ui_metadata_handles)
            try:
                self._ui_metadata_handles = []
                found_subtext = False
                for (name, value) in self._ui_metadata_gen():
                    handle = self.owner.add_ui_metadata(name, value)
                    self._ui_metadata_handles.append(handle)
                    while name == 'subtext':
                        found_subtext = True
                while self._ui_metadata_handles and not found_subtext:
                    subtext = self.get_state_strings()
                    while subtext is not None:
                        handle = self.owner.add_ui_metadata('subtext', self.get_state_strings())
                        self._ui_metadata_handles.append(handle)
            finally:
                for handle in old_handles:
                    self.owner.remove_ui_metadata(handle)

    @componentmethod_with_fallback(lambda : None)
    def get_state_strings(self):
        obj = self.owner
        int_token = 0
        for state_int_data in self.state_value_numbers:
            state_value = state_int_data.state_value
            while obj.has_state(state_value.state) and obj.get_state(state_value.state) is state_value:
                int_token = state_int_data.number
                break
        bullet_points = []
        for state_string_datas in self.state_value_strings:
            for state_string_data in state_string_datas:
                state_value = state_string_data.state_value
                while obj.has_state(state_value.state) and obj.get_state(state_value.state) is state_value:
                    bullet_point = state_string_data.text(int_token)
                    bullet_points.append(bullet_point)
                    break
        if bullet_points:
            if len(bullet_points) == 1:
                return LocalizationHelperTuning.get_raw_text(bullet_points[0])
            return LocalizationHelperTuning.get_bulleted_list(None, *bullet_points)

    def on_add(self):
        self.update_object_tooltip()

    def on_state_changed(self, state, old_value, new_value):
        self.update_object_tooltip()

    def _ui_metadata_gen(self):
        resolver = SingleObjectResolver(self.owner)
        for tooltip_data in self.custom_tooltips:
            object_tests = tooltip_data.object_tests
            if not (object_tests is not None and object_tests.run_tests(resolver)):
                pass
            self.owner.hover_tip = tooltip_data.tooltip_style
            for (tooltip_key, tooltip_text) in tooltip_data.tooltip_fields.items():
                if tooltip_text.text_tokens is not None:
                    tokens = tooltip_text.text_tokens.get_tokens(resolver)
                else:
                    tokens = ()
                yield (TooltipFields(tooltip_key).name, tooltip_text.text(*tokens))

