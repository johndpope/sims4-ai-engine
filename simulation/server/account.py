from protocolbuffers.Consts_pb2 import MSG_GAMEPLAY_OPTIONS
from sims4.commands import CommandType
import achievements.achievements
import protocolbuffers.FileSerialization_pb2 as file_serialization
import protocolbuffers.GameplaySaveData_pb2 as gameplay_save_data
import services
import sims4.log
import tutorials
import weakref
import paths
logger = sims4.log.Logger('Account')

class Account:
    __qualname__ = 'Account'

    def __init__(self, account_id, persona_name):
        self.id = account_id
        self._households = weakref.WeakSet()
        self._persona_name = persona_name
        self.clients = weakref.WeakSet()
        self._achievement_tracker = achievements.achievements.AchievementTracker(account_id)
        self.save_slot_id = 0
        services.account_service().add_account(self)
        self.locale = None

    def __repr__(self):
        return 'ID: {}; SaveSlotID: {}; locale:{}'.format(self.id, self.save_slot_id, self.locale)

    @property
    def achievement_tracker(self):
        return self._achievement_tracker

    @property
    def persona_name(self):
        return self._persona_name

    @property
    def has_households(self):
        return bool(self._households)

    def on_load_options(self):
        self._load_options()

    def on_all_households_and_sim_infos_loaded(self, client):
        self._achievement_tracker.set_update_alarm()

    def on_client_connect(self, client):
        self._achievement_tracker.clear_sent_milestones()

    def on_client_disconnect(self, client):
        self._achievement_tracker.clear_update_alarm()

    def add_household(self, household):
        self._households.add(household)

    def remove_household(self, household):
        self._households.discard(household)

    def get_household(self, zone_id):
        for household in self._households:
            while household.zone_id == zone_id:
                return household

    def get_client(self, zone_id):
        for client in self.clients:
            while client.zone_id == zone_id:
                return client

    def register_client(self, client):
        self.clients.add(client)

    def unregister_client(self, client):
        if client.household in self._households:
            self._households.remove(client.household)
        else:
            logger.info("unregister_client called for household not in account's households list (size={0}, household={1}).", len(self._households), client.household)
        self.clients.remove(client)

    def check_command_permission(self, command_type):
        if paths.AUTOMATION_MODE:
            return command_type == CommandType.Automation
        return True

    def _load_options(self):
        account_data_msg = services.get_persistence_service().get_account_proto_buff()
        options_proto = account_data_msg.gameplay_account_data.gameplay_options
        if options_proto is None:
            logger.warn('Trying to load options in account.py but options_proto is None.')
            return
        zone = services.current_zone()
        if zone is None:
            logger.warn('Trying to load game options but zone is None.')
            return
        zone.service_manager.load_options(options_proto)

    def _save_options(self, options_proto):
        if options_proto is None:
            logger.warn('Trying to save options in account.py but options_proto is None.')
            return
        zone = services.current_zone()
        if zone is None:
            logger.warn('Trying to save game options but the zone is None.')
            return
        zone.service_manager.save_options(options_proto)

    def load_account(self, account_proto):
        self.id = account_proto.nucleus_id
        self.save_slot_id = account_proto.save_slot_id
        self._achievement_tracker.load(account_proto.gameplay_account_data.achievement_data)

    def save_account(self):
        account_data_msg = services.get_persistence_service().get_account_proto_buff()
        account_data_msg.nucleus_id = self.id
        self.achievement_tracker.save(account_data_msg.gameplay_account_data.achievement_data)

    def send_options_to_client(self, client, get_default):
        gameplay_options = gameplay_save_data.GameplayOptions()
        if not get_default:
            self._save_options(gameplay_options)
        client.send_message(MSG_GAMEPLAY_OPTIONS, gameplay_options)

