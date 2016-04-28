from distributor.ops import GenericProtocolBufferOp
from distributor.system import Distributor
from interactions import ParticipantType
from protocolbuffers import Consts_pb2, Dialog_pb2
from protocolbuffers.DistributorOps_pb2 import Operation
from sims4.tuning.tunable import TunableEnumEntry, OptionalTunable
from singletons import DEFAULT
from snippets import define_snippet
from ui.ui_dialog import UiDialog, get_defualt_ui_dialog_response
import enum

class UiDialogNotification(UiDialog):
    __qualname__ = 'UiDialogNotification'
    DIALOG_MSG_TYPE = Consts_pb2.MSG_UI_NOTIFICATION_SHOW

    class UiDialogNotificationExpandBehavior(enum.Int):
        __qualname__ = 'UiDialogNotification.UiDialogNotificationExpandBehavior'
        USER_SETTING = 0
        FORCE_EXPAND = 1

    class UiDialogNotificationUrgency(enum.Int):
        __qualname__ = 'UiDialogNotification.UiDialogNotificationUrgency'
        DEFAULT = 0
        URGENT = 1

    class UiDialogNotificationLevel(enum.Int):
        __qualname__ = 'UiDialogNotification.UiDialogNotificationLevel'
        PLAYER = 0
        SIM = 1

    class UiDialogNotificationVisualType(enum.Int):
        __qualname__ = 'UiDialogNotification.UiDialogNotificationVisualType'
        INFORMATION = 0
        SPEECH = 1
        SPECIAL_MOMENT = 2

    FACTORY_TUNABLES = {'expand_behavior': TunableEnumEntry(description="\n            Specify the notification's expand behavior.\n            ", tunable_type=UiDialogNotificationExpandBehavior, needs_tuning=True, default=UiDialogNotificationExpandBehavior.USER_SETTING), 'urgency': TunableEnumEntry(description="\n            Specify the notification's urgency.\n            ", tunable_type=UiDialogNotificationUrgency, needs_tuning=True, default=UiDialogNotificationUrgency.DEFAULT), 'information_level': TunableEnumEntry(description="\n            Specify the notification's information level.\n            ", tunable_type=UiDialogNotificationLevel, needs_tuning=True, default=UiDialogNotificationLevel.SIM), 'visual_type': TunableEnumEntry(description="\n            Specify the notification's visual treatment.\n            ", tunable_type=UiDialogNotificationVisualType, needs_tuning=True, default=UiDialogNotificationVisualType.INFORMATION), 'primary_icon_response': OptionalTunable(description='\n            If enabled, associate a response to clicking the primary icon.\n            ', tunable=get_defualt_ui_dialog_response(description='\n                The response associated to the primary icon.\n                ')), 'secondary_icon_response': OptionalTunable(description='\n            If enabled, associate a response to clicking the secondary icon.\n            ', tunable=get_defualt_ui_dialog_response(description='\n                The response associated to the secondary icon.\n                ')), 'participant': OptionalTunable(description="\n            This field is deprecated. Please use 'icon' instead.\n            ", tunable=TunableEnumEntry(tunable_type=ParticipantType, default=ParticipantType.TargetSim))}

    def distribute_dialog(self, dialog_type, dialog_msg):
        distributor = Distributor.instance()
        notification_op = GenericProtocolBufferOp(Operation.UI_NOTIFICATION_SHOW, dialog_msg)
        owner = self.owner
        if owner is not None:
            distributor.add_op(owner, notification_op)
        else:
            distributor.add_op_with_no_owner(notification_op)

    def build_msg(self, additional_tokens=(), icon_override=DEFAULT, event_id=None, career_args=None, **kwargs):
        if icon_override is DEFAULT and self.participant is not None:
            participant = self._resolver.get_participant(self.participant)
            if participant is not None:
                icon_override = (None, participant)
        msg = super().build_msg(icon_override=icon_override, additional_tokens=additional_tokens, **kwargs)
        msg.dialog_type = Dialog_pb2.UiDialogMessage.NOTIFICATION
        notification_msg = msg.Extensions[Dialog_pb2.UiDialogNotification.dialog]
        notification_msg.expand_behavior = self.expand_behavior
        notification_msg.criticality = self.urgency
        notification_msg.information_level = self.information_level
        notification_msg.visual_type = self.visual_type
        if career_args is not None:
            notification_msg.career_args = career_args
        if self.primary_icon_response is not None:
            self._build_response_arg(self.primary_icon_response, notification_msg.primary_icon_response, **kwargs)
        if self.secondary_icon_response is not None:
            self._build_response_arg(self.secondary_icon_response, notification_msg.secondary_icon_response, **kwargs)
        return msg

(TunableUiDialogNotificationReference, TunableUiDialogNotificationSnippet) = define_snippet('Notification', UiDialogNotification.TunableFactory())
