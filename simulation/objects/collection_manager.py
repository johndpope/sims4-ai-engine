from audio.primitive import TunablePlayAudio
from distributor.ops import GenericProtocolBufferOp
from distributor.rollback import ProtocolBufferRollback
from distributor.system import Distributor
from event_testing import test_events
from objects.components import Component, types, componentmethod_with_fallback
from protocolbuffers import Consts_pb2, UI_pb2, UI_pb2 as ui_protocols
from protocolbuffers.DistributorOps_pb2 import Operation
from sims4.localization import TunableLocalizedString
from sims4.tuning.dynamic_enum import DynamicEnum
from sims4.tuning.tunable import TunableTuple, TunableReference, TunableEnumEntry, Tunable, TunableList, TunableFactory, TunableMapping, TunableRange, HasTunableSingletonFactory, AutoFactoryInit, OptionalTunable, HasTunableFactory
from sims4.tuning.tunable_base import ExportModes
from ui.ui_dialog_notification import UiDialogNotification
import enum
import services
import sims4
import telemetry_helper
import ui.screen_slam
TELEMETRY_GROUP_COLLECTIONS = 'COLE'
TELEMETRY_HOOK_COLLECTION_COMPLETE = 'COCO'
TELEMETRY_COLLECTION_ID = 'coid'
collection_telemetry_writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_COLLECTIONS)
logger = sims4.log.Logger('Collections')

class ObjectCollectionRarity(enum.Int):
    __qualname__ = 'ObjectCollectionRarity'
    COMMON = 1
    UNCOMMON = 2
    RARE = 3

class CollectionIdentifier(DynamicEnum):
    __qualname__ = 'CollectionIdentifier'
    Unindentified = 0

class TunableCollectionTuple(TunableTuple):
    __qualname__ = 'TunableCollectionTuple'

    def __init__(self, **kwargs):
        super().__init__(collection_id=TunableEnumEntry(description='\n                            Unique Id for this collectible, cannot be re-used.\n                            ', tunable_type=CollectionIdentifier, default=CollectionIdentifier.Unindentified, export_modes=ExportModes.All), collection_name=TunableLocalizedString(description='\n                            Localization String For the name of the \n                            collection.  This will be read on the collection\n                            UI to separate each item group.\n                            ', export_modes=ExportModes.All), completed_award=TunableReference(description='\n                            Object award when the collection is completed.  \n                            This is an object that will be awarded to the Sim\n                            when all the items inside a collection have been \n                            discovered.\n                            ', manager=services.definition_manager(), export_modes=ExportModes.All), completed_award_money=TunableRange(description='\n                            Money award when the collection is completed.  \n                            ', tunable_type=int, default=100, minimum=0, export_modes=ExportModes.All), completed_award_notification=UiDialogNotification.TunableFactory(description='\n                            Notification that will be shown when the collection\n                            is completed and the completed_award is given.\n                            '), object_list=TunableList(description='\n                            List of object that belong to a collectible group.\n                            ', tunable=CollectibleTuple.TunableFactory(), export_modes=ExportModes.All), screen_slam=OptionalTunable(description='\n                             Screen slam to show when the collection is\n                             completed and the completed_award is given.\n                             Localization Tokens: Collection Name = {0.String}\n                             ', tunable=ui.screen_slam.TunableScreenSlamSnippet()), first_collected_notification=OptionalTunable(description='\n                            If enabled a notification will be displayed when\n                            the first item of this collection has been found.\n                            ', tunable=UiDialogNotification.TunableFactory(description='\n                                Notification that will be shown the first item of\n                                this collection has been found.\n                                '), disabled_name='No_notification', enabled_name='Display_notification'))

class CollectibleTuple(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'CollectibleTuple'
    FACTORY_TUNABLES = {'collectable_item': TunableReference(description='\n            Object reference to each collectible object\n            ', manager=services.definition_manager()), 'rarity': TunableEnumEntry(description='\n            Rarity of the collectible object\n            ', tunable_type=ObjectCollectionRarity, needs_tuning=True, default=ObjectCollectionRarity.COMMON), 'discovered': Tunable(description='\n            Discovery value of an collectible.  This way we can tune a \n            collectable item to be available from the beginning without\n            having the player to find it\n            ', tunable_type=bool, needs_tuning=True, default=False)}

class ObjectCollectionData:
    __qualname__ = 'ObjectCollectionData'
    COLLECTIONS_DEFINITION = TunableList(description='\n        List of collection groups.  Will need one defined per collection id\n        ', tunable=TunableCollectionTuple())
    COLLECTION_RARITY_MAPPING = TunableMapping(description='\n            Mapping of collectible rarity to localized string for that rarity.\n            Used for displaying rarity names on the UI.', key_type=TunableEnumEntry(ObjectCollectionRarity, ObjectCollectionRarity.COMMON), value_type=TunableLocalizedString(description='\n                Localization String For the name of the collection.  \n                This will be read on the collection UI to show item rarities.\n                '))
    COLLECTION_COLLECTED_STING = TunablePlayAudio(description='\n            The audio sting that gets played when a collectable is found.\n            ')
    COLLECTION_COMPLETED_STING = TunablePlayAudio(description='\n            The audio sting that gets played when a collection is completed.\n            ')
    _COLLECTION_DATA = {}

    @classmethod
    def initialize_collection_data(cls):
        if not cls._COLLECTION_DATA:
            for collection_data in cls.COLLECTIONS_DEFINITION:
                for collectible_object in collection_data.object_list:
                    collectible_object._collection_id = collection_data.collection_id
                    cls._COLLECTION_DATA[collectible_object.collectable_item.id] = collectible_object

    @classmethod
    def get_collection_info_by_definition(cls, obj_def_id):
        if not cls._COLLECTION_DATA:
            ObjectCollectionData.initialize_collection_data()
        collectible = cls._COLLECTION_DATA.get(obj_def_id)
        if collectible:
            return (collectible._collection_id, collectible)
        return (None, None)

    @classmethod
    def get_collection_data(cls, collection_id):
        for collection_data in cls.COLLECTIONS_DEFINITION:
            while collection_data.collection_id == collection_id:
                return collection_data

class CollectionTracker:
    __qualname__ = 'CollectionTracker'

    def __init__(self, household):
        self._collections = {}
        self._owner = household

    @property
    def owner(self):
        return self._owner

    @property
    def collection_data(self):
        return self._collections

    def get_collected_items_per_collection_id(self, collection_id):
        return sum(1 for collection in self._collections.values() if collection == collection_id)

    def check_collection_complete_by_id(self, collection_id):
        collection_data = ObjectCollectionData.get_collection_data(collection_id)
        if collection_data is None:
            logger.error('Collection not found for collection id {}', collection_id, owner='camilogarcia')
            return False
        collection_count = len(collection_data.object_list)
        collected_count = self.get_collected_items_per_collection_id(collection_id)
        if collection_count and collected_count:
            return collection_count == collected_count
        return False

    def check_add_collection_item(self, household, obj_id, obj_def_id):
        (collectable_id, _collectible_data) = ObjectCollectionData.get_collection_info_by_definition(obj_def_id)
        if collectable_id is None:
            return False
        if obj_def_id not in self._collections:
            self._collections[obj_def_id] = collectable_id
            self.check_collection_complete(collectable_id)
            services.get_event_manager().process_events_for_household(test_events.TestEvent.CollectedSomething, household, collected_id=collectable_id)
            msg_type = UI_pb2.CollectibleItemUpdate.TYPE_ADD
            self.send_collection_msg(msg_type, collectable_id, household.id, obj_def_id, obj_id=obj_id)
        return True

    def check_collection_complete(self, collection_id):
        collection_data = ObjectCollectionData.get_collection_data(collection_id)
        collection_count = len(collection_data.object_list)
        collected_count = sum(1 for collection in self._collections.values() if collection == collection_id)
        if not collection_count or not collected_count:
            return
        client = services.client_manager().get_client_by_household(self._owner)
        if client is not None and client.active_sim is not None:
            message_owner_info = client.active_sim.sim_info
        else:
            message_owner_info = None
        if collection_data.first_collected_notification is not None and message_owner_info is not None and collected_count == 1:
            dialog = collection_data.first_collected_notification(message_owner_info, None)
            dialog.show_dialog()
        if collection_count == collected_count:
            if client is not None:
                with telemetry_helper.begin_hook(collection_telemetry_writer, TELEMETRY_HOOK_COLLECTION_COMPLETE, household=client.household) as hook:
                    hook.write_int(TELEMETRY_COLLECTION_ID, collection_id)
                _sting = ObjectCollectionData.COLLECTION_COMPLETED_STING(client.active_sim)
                _sting.start()
            if message_owner_info is not None:
                dialog = collection_data.completed_award_notification(message_owner_info, None)
                dialog.show_dialog()
                if collection_data.screen_slam is not None:
                    collection_data.screen_slam.send_screen_slam_message(message_owner_info, collection_data.collection_name)
            lot = services.active_lot()
            if lot is not None:
                lot.create_object_in_hidden_inventory(collection_data.completed_award)
            household = services.household_manager().get(self._owner.id)
            if household is not None:
                household.funds.add(collection_data.completed_award_money, Consts_pb2.TELEMETRY_MONEY_ASPIRATION_REWARD, None)
        elif client is not None:
            _sting = ObjectCollectionData.COLLECTION_COLLECTED_STING(client.active_sim)
            _sting.start()

    def send_collection_msg(self, msg_type, collectable_id, household_id, obj_def_id, obj_id=None):
        msg = UI_pb2.CollectibleItemUpdate()
        msg.type = msg_type
        msg.collection_id = collectable_id
        msg.household_id = household_id
        if obj_id is not None:
            msg.object_id = obj_id
        msg.object_def_id = obj_def_id
        distributor = Distributor.instance()
        distributor.add_op_with_no_owner(GenericProtocolBufferOp(Operation.SIM_COLLECTIBLE_ITEM_UPDATE, msg))

    def save_data(self, household_msg):
        for (key, value) in self._collections.items():
            with ProtocolBufferRollback(household_msg.gameplay_data.collection_data) as collection_data:
                collection_data.collectible_def_id = key
                collection_data.collection_id = value

    def load_data(self, household_msg):
        self._collections.clear()
        if self.owner.all_sims_skip_load():
            return
        msg_type = UI_pb2.CollectibleItemUpdate.TYPE_DISCOVERY
        active_household_id = services.active_household_id()
        for collection in household_msg.gameplay_data.collection_data:
            self._collections[collection.collectible_def_id] = collection.collection_id
            while active_household_id == household_msg.household_id:
                self.send_collection_msg(msg_type, collection.collection_id, household_msg.household_id, collection.collectible_def_id)

class CollectableComponent(Component, HasTunableFactory, AutoFactoryInit, component_name=types.COLLECTABLE_COMPONENT):
    __qualname__ = 'CollectableComponent'
    FACTORY_TUNABLES = {'override_slot_placement': OptionalTunable(description='\n            Whether or not this object specify the slot name where it should be \n            placed.\n            This will override the placement through slot type sets and will\n            use the hash tuned here to find where it should be placed.\n            ', tunable=Tunable(description='\n                Slot name where object should be placed.\n                ', tunable_type=str, default=''), disabled_name='No_slot_override', enabled_name='Use_custom_slot_name')}

    def on_added_to_inventory(self):
        household = services.active_household()
        if household is not None:
            household.collection_tracker.check_add_collection_item(household, self.owner.id, self.owner.definition.id)

    @componentmethod_with_fallback(lambda : None)
    def get_object_rarity(self):
        (_, collectible_data) = ObjectCollectionData.get_collection_info_by_definition(self.owner.definition.id)
        if collectible_data is None:
            return
        rarity = ObjectCollectionData.COLLECTION_RARITY_MAPPING[collectible_data.rarity]
        return rarity

    @componentmethod_with_fallback(lambda : None)
    def get_collectable_slot(self):
        slot = self.override_slot_placement
        return slot

