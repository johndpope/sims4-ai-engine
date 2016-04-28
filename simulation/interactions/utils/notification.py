from interactions import ParticipantType
from interactions.utils.interaction_elements import XevtTriggeredElement
from interactions.utils.tested_variant import TunableTestedVariant
from sims4.tuning.tunable import TunableEnumEntry, Tunable
from singletons import DEFAULT
from ui.ui_dialog_notification import TunableUiDialogNotificationSnippet

class NotificationElement(XevtTriggeredElement):
    __qualname__ = 'NotificationElement'
    FACTORY_TUNABLES = {'description': "Show a notification to a Sim's player.", 'recipient_subject': TunableEnumEntry(description="\n            The Sim's whose player will be the recipient of this notification.\n            ", tunable_type=ParticipantType, default=ParticipantType.Actor), 'limit_to_one_notification': Tunable(description='\n            If checked, this notification will only be displayed for the first\n            recipient subject. This is useful to prevent duplicates of the\n            notification from showing up when sending a notification to\n            LotOnwers or other Participant Types that have multiple Sims.\n            ', tunable_type=bool, default=False), 'dialog': TunableTestedVariant(tunable_type=TunableUiDialogNotificationSnippet()), 'allow_autonomous': Tunable(description='\n            If checked, then this notification will be displayed even if its\n            owning interaction was initiated by autonomy. If unchecked, then the\n            notification is suppressed if the interaction is autonomous.\n            ', tunable_type=bool, default=True, needs_tuning=True)}

    def _do_behavior(self, *args, **kwargs):
        return self.show_notification(*args, **kwargs)

    def show_notification(self, recipients=DEFAULT, **kwargs):
        if not self.allow_autonomous and self.interaction.is_autonomous:
            return
        if recipients is DEFAULT:
            recipients = self.interaction.get_participants(self.recipient_subject)
        simless = self.interaction.simless
        for recipient in recipients:
            while simless or recipient.is_selectable:
                resolver = self.interaction.get_resolver()
                dialog = self.dialog(recipient, resolver=resolver)
                if dialog is not None:
                    dialog.show_dialog(**kwargs)
                    if self.limit_to_one_notification:
                        break

