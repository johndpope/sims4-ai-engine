import collections
import weakref
from protocolbuffers import Consts_pb2, SimObjectAttributes_pb2 as protocols
from protocolbuffers import Localization_pb2
from protocolbuffers.Localization_pb2 import LocalizedString
from distributor.rollback import ProtocolBufferRollback
from event_testing.resolver import SingleSimResolver
from interactions import ParticipantType
from interactions.utils.interaction_elements import XevtTriggeredElement
from objects import ALL_HIDDEN_REASONS
from scheduler import TunableWeeklyScheduleFactory
from sims4.localization import TunableLocalizedString, LocalizationHelperTuning, TunableLocalizedStringFactory
from sims4.tuning.dynamic_enum import DynamicEnumLocked
from sims4.tuning.geometric import TunableCurve
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableEnumEntry, Tunable, TunableMapping, HasTunableReference, TunableTuple
from tunable_multiplier import TunableMultiplier
from ui.ui_dialog_notification import UiDialogNotification
import services
import sims4.log
import sims4.random
import tag
logger = sims4.log.Logger('Royalty', default_owner='trevor')

class RoyaltyType(DynamicEnumLocked):
    __qualname__ = 'RoyaltyType'
    INVALID = 0

class RoyaltyPayment(HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.ROYALTY)):
    __qualname__ = 'RoyaltyPayment'
    INSTANCE_TUNABLES = {'royalty_recipient': TunableEnumEntry(description='\n            This is the Sim earning the money.\n            This should always be a Sim (Actor, TargetSim, PickedSim, etc.).\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'royalty_type': TunableEnumEntry(description='\n            The royalty type this entry belongs to. This is the section in the notification in which it will show.\n            ', tunable_type=RoyaltyType, default=RoyaltyType.INVALID), 'royalty_subject': TunableEnumEntry(description='\n            This is the participant whose name will be used as the object that is earning the money.\n            Supported types are objects (Object, PickedObject, etc.) and Unlockable (for music).\n            Other object types might work but have not been tested.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'pay_curve': TunableCurve(description="\n            This curve represents payment over time.\n            The X-axis is payment number, and the Y-axis is the amount of money to be paid.\n            There MUST be at least two entries in this. One entry for the first payment and\n            one entry for the final payment. If you don't do this, there will be no payments received.\n            The first payment will be X=1. The player will not get any payments where X is tuned to 0.\n            ", x_axis_name='Payment Number', y_axis_name='Simoleon Amount'), 'pay_forever': Tunable(description='\n            If enabled, the final payment will continue to happen forever.\n            If disabled, the final payment will, in fact, be the final payment.\n            ', tunable_type=bool, default=False), 'payment_multipliers': TunableMultiplier.TunableFactory(description='\n            A list of test sets which, if they pass, will provide a multiplier to each royalty payment.\n            These tests are only checked when the royalties start and are applied to every payment.\n            They do not get tested before each payment is sent.\n            All tests will run, so all multipliers that pass will get multiplied together and then multiplied to each payment amount.\n            '), 'payment_deviation_percent': Tunable(description='\n            Once the payment amount is decided (using the Pay Curve and the \n            Payment Multipliers), it will be multiplied by this number then \n            added to and subtracted from the final payment amount to give a min \n            and max. Then, a random amount between the min and max will be \n            chosen and awarded to the player.\n            \n            Example: After using the Payment Curve and the Payment Multipliers,\n            we get a payment amount of $10.\n            The Payment Deviation is 0.2. $10 x 0.2 = 2\n            Min = $10 - 2 = $8\n            Max = $10 + 2 = $12\n            Final Payment will be some random amount between $8 and $12,\n            inclusively.\n            ', tunable_type=float, default=0), 'payment_tag': TunableEnumEntry(description='\n            The tag that will be passed along with the royalty payment. This\n            is the tag that will be used for aspirations/achievements.\n            ', tunable_type=tag.Tag, default=tag.Tag.INVALID)}

    @staticmethod
    def get_royalty_payment_tuning(royalty_payment_guid64):
        instance = services.get_instance_manager(sims4.resources.Types.ROYALTY).get(royalty_payment_guid64)
        if instance is None:
            logger.error('Tried getting royalty payment tuning for guid {} but got None instead.', royalty_payment_guid64)
            return
        return instance

class TunableRoyaltyPayment(XevtTriggeredElement):
    __qualname__ = 'TunableRoyaltyPayment'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, royalty_payment, **kwargs):
        pay_curve = royalty_payment.pay_curve
        if not pay_curve:
            logger.error('Tuning: Pay Curve is not tuned. It must have at least 2 entries in it and the first entry must have an X value of 1: {}', instance_class)
        elif len(pay_curve.points) < 2:
            logger.error('Tuning: Pay Curve must have at least two entries. The first entry must have an X value of 1: {}', instance_class)
        elif pay_curve.points[0][0] != 1:
            logger.error('Tuning: Pay Curve is not tuned correctly. The lowest X value must be 1: {}', instance_class)
        elif pay_curve.points[-1][0] <= 1:
            logger.error('Tuning: Pay Curve is not tuned correctly. The highest X value must be greater than 1: {}', instance_class)
        if royalty_payment.royalty_type == RoyaltyType.INVALID:
            logger.error('Tuning: Royalty Type must be set to one of the provided types. If this is a new time, then add it to the RoyaltyType enumeration: {}', instance_class)

    FACTORY_TUNABLES = {'description': '\n            Royalties, son. Gotta make that paper.\n            ', 'royalty_payment': RoyaltyPayment.TunableReference(description='\n            A reference to the royalty payment instance.\n            '), 'verify_tunable_callback': _verify_tunable_callback}

    def _do_behavior(self):
        royalty_payment = self.royalty_payment
        recipient = self.interaction.get_participant(royalty_payment.royalty_recipient)
        if recipient is None:
            logger.error("Trying to set up a royalty payment but interaction, {}, doesn't have the participant type {}.", self.interaction, royalty_payment.royalty_recipient)
        royalty_tracker = recipient.sim_info.royalty_tracker
        if royalty_tracker is None:
            logger.error('Trying to set up a royalty payment but the sim has a None royalty tracker.')
        participant = self.interaction.get_participant(royalty_payment.royalty_subject)
        if participant is None:
            logger.error("Trying to set up a royalty payment but the royalty subject, {}, doesn't exist in this interaction.", royalty_payment.royalty_subject)
        if isinstance(participant, (str, LocalizedString)):
            display_name = LocalizationHelperTuning.get_raw_text(participant)
        else:
            display_name = LocalizationHelperTuning.get_object_name(participant)
        royalty_tracker.start_royalty(royalty_payment.royalty_type, royalty_payment.guid64, display_name, royalty_payment.payment_multipliers.get_multiplier(self.interaction.get_resolver()))

class Royalty:
    __qualname__ = 'Royalty'

    def __init__(self, royalty_guid64, entry_name, multiplier, starting_payment):
        self._royalty_guid64 = royalty_guid64
        self._entry_name = entry_name
        self._multiplier = multiplier
        self._current_payment = starting_payment

    @property
    def royalty_guid64(self):
        return self._royalty_guid64

    @property
    def entry_name(self):
        return self._entry_name

    @property
    def multiplier(self):
        return self._multiplier

    @property
    def current_payment(self):
        return self._current_payment

    @staticmethod
    def get_last_payment_from_curve(curve):
        if curve is None:
            logger.error('Trying to get last payment form curve on a None curve.')
            return
        return int(curve.points[-1][0])

    def update(self, royalty_tuning):
        last_payment = Royalty.get_last_payment_from_curve(royalty_tuning.pay_curve)
        if self._current_payment > last_payment:
            if royalty_tuning.pay_forever:
                self._current_payment = last_payment
            else:
                return False
        return True

def _verify_tunable_callback(instance_class, tunable_name, source, value, **kwargs):
    for royalty_type in RoyaltyType:
        if royalty_type == RoyaltyType.INVALID:
            pass
        while royalty_type not in RoyaltyTracker.TYPE_LOCALIZATION_MAP:
            logger.error('Tuning: Royalty Type {} is tuned in the dynamic enum\n                but is missing a localization mapping in TYPE_LOCALIZATION_MAP\n                for instance {}', royalty_type, instance_class)

class RoyaltyTracker:
    __qualname__ = 'RoyaltyTracker'
    PAYMENT_SCHEDULE = TunableWeeklyScheduleFactory(description='\n        The schedule for when payments should be made. This is global to all\n        sims that are receiving royalties..\n        ')
    TYPE_LOCALIZATION_MAP = TunableMapping(key_type=TunableEnumEntry(description='\n            The RoyaltyType that we want to map a localized string to.\n            ', tunable_type=RoyaltyType, default=RoyaltyType.INVALID), value_type=TunableLocalizedString(description='\n            The localized name of the RoyaltyType. This is how it will show up in the\n            Royalty notification to the player.\n            '), verify_tunable_callback=_verify_tunable_callback)
    ROYALTY_ENTRY_ITEM = TunableLocalizedStringFactory(description='\n        The localized string for a royalty entry.\n        {0.String}: {1.Money}\n        ')
    ROYALTY_NOTIFICATION = UiDialogNotification.TunableFactory(description='\n        The notification displayed when royalties are viewed.\n        ', locked_args={'text': None})
    ROYALTY_NOTIFICATION_HEADER = TunableLocalizedString(description='\n        The header for the royalty notification.\n        ')

    def __init__(self, sim_info):
        self._sim_ref = weakref.ref(sim_info)
        self._royalties = {}

    @property
    def sim_info(self):
        return self._sim_ref()

    @property
    def has_royalties(self):
        for (_, royalty_list) in self._royalties.items():
            while royalty_list:
                return True
        return False

    def start_royalty(self, royalty_type, royalty_guid64, entry_name, multiplier, starting_payment=0):
        if royalty_type not in self._royalties.keys():
            self._royalties[royalty_type] = []
        self._royalties[royalty_type].append(Royalty(royalty_guid64, entry_name, multiplier, starting_payment))

    def update_royalties_and_get_paid(self):
        if not self.has_royalties:
            return
        sim_info = self.sim_info
        if sim_info is None:
            logger.error('Trying to pay out a Sim but the Sim is None. Perhaps they died? Clearing out royalties for this Sim. Sim: {}', sim_info)
            self._royalties.clear()
            return
        tag_payment_map = {}
        royalty_payment_dict = collections.defaultdict(list)
        for royalty_list in self._royalties.values():
            for royalty in reversed(royalty_list):
                royalty_tuning = RoyaltyPayment.get_royalty_payment_tuning(royalty.royalty_guid64)
                if royalty_tuning is None:
                    logger.error('royalty_tuning is none for sim {}. royalty: {}.', sim_info, royalty)
                if royalty.update(royalty_tuning):
                    payment_tag = royalty_tuning.payment_tag
                    payment_amount = RoyaltyTracker.get_payment_amount(royalty, royalty_tuning)
                    royalty_payment_dict[royalty] = payment_amount
                    if payment_tag not in tag_payment_map:
                        tag_payment_map[payment_tag] = 0
                    tag_payment_map[payment_tag] += payment_amount
                else:
                    royalty_list.remove(royalty)
        for (payment_tag, payment_amount) in tag_payment_map.items():
            tags = None
            if payment_tag != tag.Tag.INVALID:
                tags = frozenset((payment_tag,))
            sim_info.household.funds.add(payment_amount, Consts_pb2.TELEMETRY_MONEY_ROYALTY, sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS), tags=tags)
        self.show_royalty_notification(royalty_payment_dict)

    def show_royalty_notification(self, royalty_payment_dict):
        notification_text = LocalizationHelperTuning.get_new_line_separated_strings(*(LocalizationHelperTuning.get_bulleted_list(RoyaltyTracker.get_name_for_type(royalty_type), *(RoyaltyTracker.get_line_item_string(r.entry_name, royalty_payment_dict[r]) for r in royalty_list)) for (royalty_type, royalty_list) in self._royalties.items()))
        notification_text = LocalizationHelperTuning.get_new_line_separated_strings(self.ROYALTY_NOTIFICATION_HEADER, notification_text)
        sim_info = self.sim_info
        resolver = SingleSimResolver(sim_info)
        dialog = self.ROYALTY_NOTIFICATION(sim_info, resolver, text=lambda *_: notification_text)
        dialog.show_dialog()

    @staticmethod
    def get_name_for_type(royalty_type):
        return RoyaltyTracker.TYPE_LOCALIZATION_MAP.get(royalty_type)

    @staticmethod
    def get_payment_amount(royalty, royalty_tuning):
        deviation_percent = royalty_tuning.payment_deviation_percent
        payment_amount = royalty_tuning.pay_curve.get(royalty.current_payment)*royalty.multiplier
        if deviation_percent == 0:
            return int(payment_amount)
        deviation = payment_amount*deviation_percent
        min_payment = payment_amount - deviation
        max_payment = payment_amount + deviation
        return int(sims4.random.uniform(min_payment, max_payment))

    @staticmethod
    def get_line_item_string(name, amount):
        return RoyaltyTracker.ROYALTY_ENTRY_ITEM(name, amount)

    def save(self):
        data = protocols.PersistableRoyaltyTracker()
        for (royalty_type, royalty_list) in self._royalties.items():
            for royalty in royalty_list:
                with ProtocolBufferRollback(data.royalties) as royalty_data:
                    royalty_data.royalty_type = int(royalty_type)
                    royalty_data.royalty_guid64 = royalty.royalty_guid64
                    royalty_data.entry_name = royalty.entry_name
                    royalty_data.multiplier = royalty.multiplier
                    royalty_data.current_payment = royalty.current_payment
        return data

    def load(self, data):
        for royalty_data in data.royalties:
            entry_name = Localization_pb2.LocalizedString()
            entry_name.MergeFrom(royalty_data.entry_name)
            self.start_royalty(royalty_type=RoyaltyType(royalty_data.royalty_type), royalty_guid64=royalty_data.royalty_guid64, entry_name=entry_name, multiplier=royalty_data.multiplier, starting_payment=royalty_data.current_payment)

class RoyaltyAlarmManager:
    __qualname__ = 'RoyaltyAlarmManager'

    def __init__(self):
        self._alarm_handle = None

    def start_schedule(self):
        RoyaltyTracker.PAYMENT_SCHEDULE(start_callback=self._royalty_alarm_tick, schedule_immediate=False)

    def _royalty_alarm_tick(self, *_):
        client = services.client_manager().get_first_client()
        if client is None:
            return
        household = client.household
        if household is None:
            return
        for sim_info in household.sim_info_gen():
            tracker = sim_info.royalty_tracker
            if tracker is None:
                pass
            tracker.update_royalties_and_get_paid()

