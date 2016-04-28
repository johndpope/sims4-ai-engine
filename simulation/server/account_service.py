import weakref
from protocolbuffers import FileSerialization_pb2 as serialization
from server import account
from sims.sim_spawner import SimSpawner
from sims4.commands import CommandType
from sims4.service_manager import Service
import services
import sims4.log
logger = sims4.log.Logger('AccountService')

class AccountService(Service):
    __qualname__ = 'AccountService'

    def __init__(self):
        self._accounts = weakref.WeakValueDictionary()
        sims4.commands.permissions_provider = self.check_command_permission

    def get_account_by_id(self, account_id, try_load_account=False):
        account = self._accounts.get(account_id, None)
        if not account and try_load_account:
            account = self._load_account_by_id(account_id)
        return account

    def get_account_by_persona(self, persona_name):
        for account in self._accounts.values():
            while account.persona_name == persona_name:
                return account

    def add_account(self, new_account):
        if new_account.id in self._accounts:
            logger.warn('Trying to add Account that is already in the Account Service')
        self._accounts[new_account.id] = new_account

    def check_command_permission(self, client_id, command_type):
        tgt_client = services.client_manager().get(client_id)
        if tgt_client is None:
            return False
        if command_type == CommandType.Cheat:
            household = tgt_client.household
            if household is not None:
                return household.cheats_enabled
        return tgt_client.account.check_command_permission(command_type)

    def on_load_options(self, client):
        client.account.on_load_options()

    def on_all_households_and_sim_infos_loaded(self, client):
        client.account.on_all_households_and_sim_infos_loaded(client)

    def on_client_connect(self, client):
        client.account.on_client_connect(client)

    def on_client_disconnect(self, client):
        client.account.on_client_disconnect(client)

    def _load_account_by_id(self, account_id):
        if account_id == SimSpawner.SYSTEM_ACCOUNT_ID:
            new_account = account.Account(SimSpawner.SYSTEM_ACCOUNT_ID, 'SystemAccount')
            return new_account
        account_proto = services.get_persistence_service().get_account_proto_buff()
        new_account = account.Account(account_proto.nucleus_id, account_proto.persona_name)
        new_account.load_account(account_proto)
        return new_account

    def save(self, **kwargs):
        for account in self._accounts.values():
            account.save_account()

