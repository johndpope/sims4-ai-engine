from audio.primitive import TunablePlayAudio, play_tunable_audio
from distributor.shared_messages import build_icon_info_msg
from distributor.system import Distributor
from interactions.utils.localization_tokens import LocalizationTokens
from interactions.utils.tunable_icon import TunableIconVariant
from protocolbuffers import Dialog_pb2, Consts_pb2
from sims4.callback_utils import CallableList
from sims4.localization import TunableLocalizedStringFactory, TunableLocalizedStringFactoryVariant
from sims4.tuning.tunable import TunableEnumEntry, HasTunableFactory, AutoFactoryInit, OptionalTunable, HasTunableSingletonFactory, TunableList, Tunable, TunableEnumFlags
from singletons import DEFAULT
from uid import unique_id
import enum
import pythonutils
import services
import sims4.log
logger = sims4.log.Logger('Dialog')

class ButtonType(enum.Int):
    __qualname__ = 'ButtonType'
    DIALOG_RESPONSE_CLOSED = -1
    DIALOG_RESPONSE_NO_RESPONSE = 10000
    DIALOG_RESPONSE_OK = 10001
    DIALOG_RESPONSE_CANCEL = 10002

class PhoneRingType(enum.Int):
    __qualname__ = 'PhoneRingType'
    NO_RING = 0
    BUZZ = 1
    RING = 2

def get_defualt_ui_dialog_response(**kwargs):
    return UiDialogResponse.TunableFactory(locked_args={'sort_order': 0, 'dialog_response_id': ButtonType.DIALOG_RESPONSE_NO_RESPONSE}, **kwargs)

class UiDialogOption(enum.IntFlags):
    __qualname__ = 'UiDialogOption'
    DISABLE_CLOSE_BUTTON = 1
    SMALL_TITLE = 2

class UiDialogResponse(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'UiDialogResponse'

    class UiDialogUiRequest(enum.Int):
        __qualname__ = 'UiDialogResponse.UiDialogUiRequest'
        NO_REQUEST = 0
        SHOW_LESSONS = 1
        SHOW_ACHIEVEMENTS = 2
        SHOW_GALLERY = 3
        SHOW_FAMILY_INVENTORY = 4
        SHOW_SKILL_PANEL = 5
        SHOW_SUMMARY_PANEL = 6
        SHOW_ASPIRATION_PANEL = 7
        SHOW_ASPIRATION_UI = 8
        SHOW_EVENT_UI = 9
        SHOW_CAREER_PANEL = 10
        SHOW_RELATIONSHIP_PANEL = 11
        SHOW_SIM_INVENTORY = 12
        SHOW_REWARD_STORE = 13
        SHOW_MOTIVE_PANEL = 14
        SHOW_STATS = 15
        SHOW_COLLECTIBLES = 16
        SHOW_CAREER_UI = 17
        TRANSITION_TO_NEIGHBORHOOD_SAVE = 18
        TRANSITION_TO_MAIN_MENU_NO_SAVE = 19
        SHOW_SHARE_PLAYER_PROFILE = 20
        SHOW_ASPIRATION_SELECTOR = 21

    FACTORY_TUNABLES = {'sort_order': Tunable(description='\n            The sorting order of the response button.  If the items of the\n            same order will be placed in the order that they are added.\n            ', tunable_type=int, default=0), 'dialog_response_id': TunableEnumEntry(description='\n            ', tunable_type=ButtonType, default=ButtonType.DIALOG_RESPONSE_NO_RESPONSE), 'text': TunableLocalizedStringFactory(description="\n            The prompt's text.\n            "), 'ui_request': TunableEnumEntry(description="\n            This prompt's associated UI action.\n            ", tunable_type=UiDialogUiRequest, default=UiDialogUiRequest.NO_REQUEST)}

    def __init__(self, sort_order=0, dialog_response_id=ButtonType.DIALOG_RESPONSE_NO_RESPONSE, text=None, ui_request=UiDialogUiRequest.NO_REQUEST):
        super().__init__(sort_order=sort_order, dialog_response_id=dialog_response_id, text=text, ui_request=ui_request)

@unique_id('dialog_id', 1)
class UiDialog(HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'UiDialog'
    DIALOG_MSG_TYPE = Consts_pb2.MSG_UI_DIALOG_SHOW
    FACTORY_TUNABLES = {'title': OptionalTunable(description='\n            If enabled, this dialog will include title text.\n            ', tunable=TunableLocalizedStringFactory(description="\n                The dialog's title.\n                ")), 'text': TunableLocalizedStringFactoryVariant(description="\n            The dialog's text.\n            "), 'text_tokens': OptionalTunable(description='\n            If enabled, define text tokens to be used to localized text.\n            ', tunable=LocalizationTokens.TunableFactory(description='\n                Define the text tokens that are available to all text fields in\n                the dialog, such as title, text, responses, default and initial\n                text values, tooltips, etc.\n                '), disabled_value=DEFAULT), 'icon': OptionalTunable(description='\n            If enabled, specify an icon to be displayed.\n            ', tunable=TunableIconVariant(), needs_tuning=True), 'secondary_icon': OptionalTunable(description='\n            If enabled, specify a secondary icon to be displayed. Only certain\n            dialog types may support this field.\n            ', tunable=TunableIconVariant(), needs_tuning=True), 'phone_ring_type': TunableEnumEntry(description='\n             The phone ring type of this dialog.  If tuned to anything other\n             than None this dialog will only appear after clicking on the phone.\n             ', tunable_type=PhoneRingType, needs_tuning=True, default=PhoneRingType.NO_RING), 'audio_sting': OptionalTunable(description='\n            If enabled, play an audio sting when the dialog is shown.\n            ', tunable=TunablePlayAudio()), 'ui_responses': TunableList(description='\n            A list of buttons that are mapped to UI commands.\n            ', tunable=get_defualt_ui_dialog_response()), 'dialog_options': TunableEnumFlags(description='\n            Options to apply to the dialog.\n            ', enum_type=UiDialogOption, allow_no_flags=True, default=UiDialogOption.DISABLE_CLOSE_BUTTON)}

    def __init__(self, owner, resolver=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._owner = owner.ref()
        self._resolver = resolver
        self._additional_responses = {}
        self.response = None
        self._timestamp = None
        self._listeners = CallableList()

    @property
    def accepted(self) -> bool:
        return self.response is not None and self.response != ButtonType.DIALOG_RESPONSE_CLOSED

    @property
    def responses(self):
        return tuple()

    @property
    def owner(self):
        return self._owner()

    @property
    def dialog_type(self):
        return self._dialog_type

    def add_listener(self, listener_callback):
        self._listeners.append(listener_callback)

    def set_responses(self, responses):
        self._additional_responses = tuple(responses)

    def has_responses(self):
        return self.responses or self._additional_responses

    def _get_responses_gen(self):
        yield self.responses
        yield self._additional_responses
        yield self.ui_responses

    def respond(self, response) -> bool:
        try:
            self.response = response
            self._listeners(self)
            return True
        finally:
            self.on_response_received()
        return False

    def update(self) -> bool:
        return True

    def show_dialog(self, on_response=None, **kwargs):
        if self.audio_sting is not None:
            play_tunable_audio(self.audio_sting, None)
        if on_response is not None:
            self.add_listener(on_response)
        pythonutils.try_highwater_gc()
        services.ui_dialog_service().dialog_show(self, self.phone_ring_type, **kwargs)

    def distribute_dialog(self, dialog_type, dialog_msg):
        distributor = Distributor.instance()
        distributor.add_event(dialog_type, dialog_msg)

    def _build_localized_string_msg(self, string, *additional_tokens):
        if string is None:
            logger.callstack('_build_localized_string_msg received None for the string to build. This is probably not intended.', owner='tingyul')
            return
        tokens = ()
        if self._resolver is not None:
            if self.text_tokens is DEFAULT:
                tokens = self._resolver.get_localization_tokens()
            elif self.text_tokens is not None:
                tokens = self.text_tokens.get_tokens(self._resolver)
        return string(*tokens + additional_tokens)

    def _build_response_arg(self, response, response_msg, tutorial_id=None, additional_tokens=(), **kwargs):
        response_msg.choice_id = response.dialog_response_id
        response_msg.ui_request = response.ui_request
        if response.text is not None:
            response_msg.text = self._build_localized_string_msg(response.text, *additional_tokens)
        if tutorial_id is not None:
            response_msg.tutorial_args.tutorial_id = tutorial_id

    def build_msg(self, additional_tokens=(), icon_override=DEFAULT, secondary_icon_override=DEFAULT, **kwargs):
        msg = Dialog_pb2.UiDialogMessage()
        msg.dialog_id = self.dialog_id
        msg.owner_id = self.owner.id
        msg.dialog_type = Dialog_pb2.UiDialogMessage.DEFAULT
        if self.title is not None:
            msg.title = self._build_localized_string_msg(self.title, *additional_tokens)
        msg.text = self._build_localized_string_msg(self.text, *additional_tokens)
        if icon_override is DEFAULT:
            if self.icon is not None:
                icon_info = self.icon(self._resolver)
                key = icon_info[0]
                if key is not None:
                    msg.icon.type = key.type
                    msg.icon.group = key.group
                    msg.icon.instance = key.instance
                build_icon_info_msg(icon_info, None, msg.icon_info)
        elif icon_override is not None:
            build_icon_info_msg(icon_override, None, msg.icon_info)
        if secondary_icon_override is DEFAULT:
            if self.secondary_icon is not None:
                icon_info = self.secondary_icon(self._resolver)
                build_icon_info_msg(icon_info, None, msg.secondary_icon_info)
        elif secondary_icon_override is not None:
            build_icon_info_msg(secondary_icon_override, None, msg.secondary_icon_info)
        msg.dialog_options = self.dialog_options
        responses = []
        responses.extend(self._get_responses_gen())
        responses.sort(key=lambda response: response.sort_order)
        for response in responses:
            response_msg = msg.choices.add()
            self._build_response_arg(response, response_msg, additional_tokens=additional_tokens, **kwargs)
        return msg

    def on_response_received(self):
        pass

    def do_auto_respond(self):
        if ButtonType.DIALOG_RESPONSE_CANCEL in self.responses:
            response = ButtonType.DIALOG_RESPONSE_CANCEL
        elif ButtonType.DIALOG_RESPONSE_OK in self.responses:
            response = ButtonType.DIALOG_RESPONSE_OK
        else:
            response = ButtonType.DIALOG_RESPONSE_CLOSED
        services.ui_dialog_service().dialog_respond(self.dialog_id, response)

class UiDialogOk(UiDialog):
    __qualname__ = 'UiDialogOk'
    FACTORY_TUNABLES = {'text_ok': TunableLocalizedStringFactory(description='\n            The OK button text.\n            ', default=3648501874), 'is_special_dialog': Tunable(description='\n            If checked, UI will treat this as a special ok or ok/cancel dialog \n            and represent the ok or ok/cancel options in a special way. \n            They will use the text as a tooltip for ok or ok/cancel options \n            and use particular icons for the buttons.\n            ', tunable_type=bool, default=False)}

    def build_msg(self, **kwargs):
        msg = super().build_msg(**kwargs)
        if self.is_special_dialog:
            msg.dialog_type = Dialog_pb2.UiDialogMessage.OK_CANCEL_ICONS
        return msg

    @property
    def accepted(self) -> bool:
        return self.response == ButtonType.DIALOG_RESPONSE_OK

    @property
    def responses(self):
        return (UiDialogResponse(dialog_response_id=ButtonType.DIALOG_RESPONSE_OK, text=self.text_ok, ui_request=UiDialogResponse.UiDialogUiRequest.NO_REQUEST),)

class UiDialogOkCancel(UiDialogOk):
    __qualname__ = 'UiDialogOkCancel'
    FACTORY_TUNABLES = {'text_cancel': TunableLocalizedStringFactory(description='\n            The Cancel button text.\n            ', default=3497542682)}

    @property
    def responses(self):
        return (UiDialogResponse(dialog_response_id=ButtonType.DIALOG_RESPONSE_OK, text=self.text_ok, ui_request=UiDialogResponse.UiDialogUiRequest.NO_REQUEST), UiDialogResponse(dialog_response_id=ButtonType.DIALOG_RESPONSE_CANCEL, text=self.text_cancel, ui_request=UiDialogResponse.UiDialogUiRequest.NO_REQUEST))

