from sims4.localization import TunableLocalizedStringFactory, TunableLocalizedStringFactoryVariant
from sims4.tuning.tunable import TunableTuple, TunableRange, Tunable, OptionalTunable
from ui.ui_dialog import UiDialog, UiDialogOkCancel, UiDialogOk, ButtonType
import services
TEXT_INPUT_FIRST_NAME = 'first_name'
TEXT_INPUT_LAST_NAME = 'last_name'

class UiDialogTextInput(UiDialog):
    __qualname__ = 'UiDialogTextInput'
    FACTORY_TUNABLES = {'text_inputs': lambda *names: TunableTuple(**{name: TunableTextInput(locked_args={'sort_order': index}) for (index, name) in enumerate(names)})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text_input_responses = {}

    def on_text_input(self, text_input_name='', text_input=''):
        if text_input_name in self.text_inputs:
            self.text_input_responses[text_input_name] = text_input
            return True
        return False

    def build_msg(self, text_input_overrides=None, additional_tokens=(), **kwargs):
        msg = super().build_msg(additional_tokens=additional_tokens, **kwargs)
        for (name, tuning) in sorted(self.text_inputs.items(), key=lambda t: t[1].sort_order):
            initial_value = None
            if tuning.initial_value is not None:
                initial_value = tuning.initial_value
            if text_input_overrides is not None:
                if name not in text_input_overrides:
                    pass
                initial_value = text_input_overrides[name] or initial_value
            text_input_msg = msg.text_input.add()
            text_input_msg.text_input_name = name
            if initial_value is not None:
                text_input_msg.initial_value = self._build_localized_string_msg(initial_value, *additional_tokens)
            if tuning.default_text is not None:
                text_input_msg.default_text = self._build_localized_string_msg(tuning.default_text, *additional_tokens)
            text_input_msg.max_length = tuning.max_length
            if tuning.min_length:
                text_input_msg.min_length = tuning.min_length.length
                if tuning.min_length.tooltip is not None:
                    text_input_msg.input_too_short_tooltip = self._build_localized_string_msg(tuning.min_length.tooltip, *additional_tokens)
            while tuning.title:
                text_input_msg.title = self._build_localized_string_msg(tuning.title, *additional_tokens)
        return msg

    def do_auto_respond(self):
        if ButtonType.DIALOG_RESPONSE_CANCEL in self.responses:
            response = ButtonType.DIALOG_RESPONSE_CANCEL
        elif ButtonType.DIALOG_RESPONSE_OK in self.responses:
            for (text_input_name, text_input_tuning) in self.text_inputs.items():
                text = '*'*text_input_tuning.min_length.length
                self.on_text_input(text_input_name, text)
            response = ButtonType.DIALOG_RESPONSE_OK
        else:
            response = ButtonType.DIALOG_RESPONSE_CLOSED
        services.ui_dialog_service().dialog_respond(self.dialog_id, response)

class TunableTextInput(TunableTuple):
    __qualname__ = 'TunableTextInput'

    def __init__(self, description='Properties of a textbox where a user can type in text', **kwargs):
        super().__init__(description=description, default_text=OptionalTunable(description="\n                             Default text that will show up when the text box is\n                             not in focus if the user hasn't entered anything in\n                             the text box yet. If only default text is set, the\n                             text box will be blank when the user puts it in\n                             focus.\n                             ", tunable=TunableLocalizedStringFactory()), initial_value=OptionalTunable(description='\n                             The initial value of the text in the textbox. This\n                             is different from default text because the initial\n                             value stays regardless of if the text box is in\n                             focus.\n                             ', tunable=TunableLocalizedStringFactoryVariant()), min_length=OptionalTunable(description="\n                             If enabled, specify the minimum length of input\n                             text the player has to enter before he/she can hit\n                             the 'OK' button.\n                             ", tunable=TunableTuple(length=TunableRange(description='\n                                     Minimum amount of characters the user must\n                                     enter in to the text box before he/she can\n                                     click on the OK button.\n                                     ', tunable_type=int, minimum=1, default=1), tooltip=OptionalTunable(description='\n                                     If enabled, allows specification of a\n                                     tooltip to display if the user has entered\n                                     text length less than min_length.\n                                     ', tunable=TunableLocalizedStringFactory())), disabled_value=0), max_length=Tunable(description='\n                             Max amount of characters the user can enter into\n                             the text box.\n                             ', tunable_type=int, default=20), title=OptionalTunable(description='\n                             Text that will be shown with the text input to\n                             describe what that user is inputing.\n                             ', tunable=TunableLocalizedStringFactory()), **kwargs)

class UiDialogTextInputOkCancel(UiDialogOkCancel, UiDialogTextInput):
    __qualname__ = 'UiDialogTextInputOkCancel'

class UiDialogTextInputOk(UiDialogOk, UiDialogTextInput):
    __qualname__ = 'UiDialogTextInputOk'

