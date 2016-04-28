from protocolbuffers import Consts_pb2
from protocolbuffers.DistributorOps_pb2 import SetWhimBucks
from interactions import ParticipantType
from interactions.utils import LootType
from interactions.utils.loot_basic_op import BaseLootOperation
from objects.components.state import TunableStateValueReference
from sims import sim_info_types
from sims.unlock_tracker import TunableUnlockVariant
from sims4.tuning.tunable import Tunable, TunableRange, TunableReference, TunableEnumEntry, OptionalTunable, TunableVariant, TunableList
from ui.ui_dialog_notification import UiDialogNotification
import build_buy
import interactions
import services
import sims4.log
import tag
logger = sims4.log.Logger('LootOperations')
FLOAT_TO_PERCENT = 0.01

class BaseGameLootOperation(BaseLootOperation):
    __qualname__ = 'BaseGameLootOperation'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value._subject == interactions.ParticipantType.Invalid:
            logger.error("The 'subject' in BaseGameLootOperation {} should not be ParticipantType.Invalid.", instance_class)

    FACTORY_TUNABLES = {'locked_args': {'advertise': False}, 'verify_tunable_callback': _verify_tunable_callback}

class LifeExtensionLootOp(BaseLootOperation):
    __qualname__ = 'LifeExtensionLootOp'
    FACTORY_TUNABLES = {'description': '\n            This loot will grant a life extension.\n            ', 'bonus_days': TunableRange(description="\n            Number of bonus days to be granted to the target's life.\n            ", tunable_type=int, default=1, minimum=0), 'reset_aging_progress_in_category': Tunable(description="\n            If checked, this loot op will also reset the target's aging\n            progress in their current age category.\n            ", tunable_type=bool, default=False)}

    def __init__(self, bonus_days, reset_aging_progress_in_category, **kwargs):
        super().__init__(**kwargs)
        self.bonus_days = bonus_days
        self.reset_aging_progress_in_category = reset_aging_progress_in_category

    @property
    def loot_type(self):
        return LootType.LIFE_EXTENSION

    def _apply_to_subject_and_target(self, subject, target, resolver):
        subject.add_bonus_days(self.bonus_days)
        if self.reset_aging_progress_in_category:
            subject.reset_age_progress()

class StateChangeLootOp(BaseLootOperation):
    __qualname__ = 'StateChangeLootOp'
    FACTORY_TUNABLES = {'description': '\n            This loot will change the state of the subject.\n            ', 'state_value': TunableStateValueReference()}

    def __init__(self, state_value, **kwargs):
        super().__init__(**kwargs)
        self.state_value = state_value

    def _apply_to_subject_and_target(self, subject, target, resolver):
        subject_obj = self._get_object_from_recipient(subject)
        if subject_obj is not None:
            state_value = self.state_value
            subject_obj.set_state(state_value.state, state_value)

class NotificationLootOp(BaseLootOperation):
    __qualname__ = 'NotificationLootOp'
    FACTORY_TUNABLES = {'description': '\n            This loot will display a notification to the screen.\n            ', 'notification': UiDialogNotification.TunableFactory(description='\n            This text will display in a notification pop up when completed.\n            ')}

    def __init__(self, notification, **kwargs):
        super().__init__(**kwargs)
        self.notification = notification

    def _apply_to_subject_and_target(self, subject, target, resolver):
        if subject is not None and subject.is_selectable:
            dialog = self.notification(subject, resolver)
            dialog.show_dialog(event_id=self.notification.factory.DIALOG_MSG_TYPE)

class AddTraitLootOp(BaseLootOperation):
    __qualname__ = 'AddTraitLootOp'
    FACTORY_TUNABLES = {'description': '\n            This loot will add the specified trait.\n            ', 'trait': TunableReference(description='\n            The trait to be added.\n            ', manager=services.get_instance_manager(sims4.resources.Types.TRAIT))}

    def __init__(self, trait, **kwargs):
        super().__init__(**kwargs)
        self._trait = trait

    def _apply_to_subject_and_target(self, subject, target, resolver):
        subject.trait_tracker.add_trait(self._trait)

class RemoveTraitLootOp(BaseLootOperation):
    __qualname__ = 'RemoveTraitLootOp'
    FACTORY_TUNABLES = {'description': '\n            This loot will remove the specified trait\n            ', 'trait': TunableReference(description='\n            The trait to be removed.\n            ', manager=services.get_instance_manager(sims4.resources.Types.TRAIT))}

    def __init__(self, trait, **kwargs):
        super().__init__(**kwargs)
        self._trait = trait

    def _apply_to_subject_and_target(self, subject, target, resolver):
        subject.trait_tracker.remove_trait(self._trait)

class HouseholdFundsInterestLootOp(BaseLootOperation):
    __qualname__ = 'HouseholdFundsInterestLootOp'
    FACTORY_TUNABLES = {'description': '\n            This loot will deliver interest income to the current Household for their current funds,\n            based on the percentage tuned against total held. \n        ', 'interest_rate': Tunable(description='\n            The percentage of interest to apply to current funds.\n            ', tunable_type=int, default=0), 'notification': OptionalTunable(description='\n            If enabled, this notification will display when this interest payment is made.\n            Token 0 is the Sim - i.e. {0.SimFirstName}\n            Token 1 is the interest payment amount - i.e. {1.Money}\n            ', tunable=UiDialogNotification.TunableFactory())}

    def __init__(self, interest_rate, notification, **kwargs):
        super().__init__(**kwargs)
        self._interest_rate = interest_rate
        self._notification = notification

    def _apply_to_subject_and_target(self, subject, target, resolver):
        pay_out = int(subject.household.funds.money*self._interest_rate*FLOAT_TO_PERCENT)
        subject.household.funds.add(pay_out, Consts_pb2.TELEMETRY_INTERACTION_REWARD, self._get_object_from_recipient(subject))
        if self._notification is not None:
            dialog = self._notification(subject, resolver)
            dialog.show_dialog(event_id=self._notification.factory.DIALOG_MSG_TYPE, additional_tokens=(pay_out,))

class FireLootOp(BaseLootOperation):
    __qualname__ = 'FireLootOp'

    def _apply_to_subject_and_target(self, subject, target, resolver):
        if subject is None:
            logger.error('Invalid subject specified for this loot operation. {}  Please fix in tuning.', self)
            return
        subject_obj = self._get_object_from_recipient(subject)
        if subject_obj is None:
            logger.error('No valid object for subject specified for this loot operation. {}  Please fix in tuning.', resolver)
            return
        fire_service = services.get_fire_service()
        fire_service.spawn_fire_at_object(subject_obj)

class UnlockLootOp(BaseLootOperation):
    __qualname__ = 'UnlockLootOp'
    FACTORY_TUNABLES = {'description': '\n            This loot will give Sim an unlock item like recipe etc. \n            ', 'unlock_item': TunableUnlockVariant(description='\n            The unlock item that will give to the Sim.\n            ')}

    def __init__(self, unlock_item, **kwargs):
        super().__init__(**kwargs)
        self._unlock_item = unlock_item

    def _apply_to_subject_and_target(self, subject, target, resolver):
        if subject is None:
            logger.error('Subject {} is None for the loot {}..', self.subject, self)
            return
        if not subject.is_sim:
            logger.error('Subject {} is not Sim for the loot {}.', self.subject, self)
            return
        subject.unlock_tracker.add_unlock(self._unlock_item, None)

class CollectibleShelveItem(BaseLootOperation):
    __qualname__ = 'CollectibleShelveItem'

    def __init__(self, *args, **kwargs):
        super().__init__(target_participant_type=ParticipantType.Object, *args, **kwargs)

    def _apply_to_subject_and_target(self, subject, target, resolver):
        target_slot = subject.get_collectable_slot()
        if target_slot:
            for runtime_slot in target.get_runtime_slots_gen(bone_name_hash=sims4.hash_util.hash32(target_slot)):
                while runtime_slot and runtime_slot.empty:
                    runtime_slot.add_child(subject)
                    return True
        return False

class FireDeactivateSprinklerLootOp(BaseLootOperation):
    __qualname__ = 'FireDeactivateSprinklerLootOp'

    def _apply_to_subject_and_target(self, subject, target, resolver):
        fire_service = services.get_fire_service()
        if fire_service is not None:
            fire_service.deactivate_sprinkler_system()

class FireCleanScorchLootOp(BaseLootOperation):
    __qualname__ = 'FireCleanScorchLootOp'

    def _apply_to_subject_and_target(self, subject, target, resolver):
        if subject is None:
            logger.error('Subject {} is None for the loot {}..', self.subject, self)
            return
        if not subject.is_sim:
            logger.error('Subject {} is not Sim for the loot {}.', self.subject, self)
            return
        fire_service = services.get_fire_service()
        if fire_service is None:
            logger.error('Fire Service in none when calling the lootop: {}.', self)
            return
        sim = self._get_object_from_recipient(subject)
        location = sims4.math.Vector3(*sim.location.transform.translation) + sim.forward
        level = sim.location.level
        scorch_locations = fire_service.find_cleanable_scorch_mark_locations_within_radius(location, level, fire_service.SCORCH_TERRAIN_CLEANUP_RADIUS)
        if scorch_locations:
            zone_id = sims4.zone_utils.get_zone_id()
            build_buy.begin_update_floor_features(zone_id, build_buy.FloorFeatureType.BURNT)
            for scorch_location in scorch_locations:
                build_buy.set_floor_feature(zone_id, build_buy.FloorFeatureType.BURNT, scorch_location, level, 0)
            build_buy.end_update_floor_features(zone_id, build_buy.FloorFeatureType.BURNT)

class ExtinguishNearbyFireLootOp(BaseLootOperation):
    __qualname__ = 'ExtinguishNearbyFireLootOp'

    def _apply_to_subject_and_target(self, subject, target, resolver):
        if subject is None:
            logger.error('Subject {} is None for the loot {}..', self.subject, self)
            return
        fire_service = services.get_fire_service()
        if fire_service is None:
            logger.error('Fire Service in none when calling the lootop: {}.', self)
            return
        subject = self._get_object_from_recipient(subject)
        fire_service.extinguish_nearby_fires(subject)
        return True

class AwardWhimBucksLootOp(BaseLootOperation):
    __qualname__ = 'AwardWhimBucksLootOp'
    FACTORY_TUNABLES = {'description': '\n            This loot will give the specified number of whim bucks to the sim. \n            ', 'whim_bucks': TunableRange(description='\n            The number of whim bucks to give.\n            ', tunable_type=int, default=1, minimum=1)}

    def __init__(self, whim_bucks, **kwargs):
        super().__init__(**kwargs)
        self._whim_bucks = whim_bucks

    def _apply_to_subject_and_target(self, subject, target, resolver):
        if subject is None:
            logger.error('Subject {} is None for the loot {}..', self.subject, self)
            return False
        subject.add_whim_bucks(self._whim_bucks, SetWhimBucks.COMMAND)

