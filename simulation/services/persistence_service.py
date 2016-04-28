import collections
from protocolbuffers import FileSerialization_pb2 as serialization, UI_pb2
from protocolbuffers.Consts_pb2 import MSG_GAME_SAVE_COMPLETE, MSG_GAME_SAVE_LOCK_UNLOCK
from distributor.system import Distributor
from sims4.localization import TunableLocalizedString, TunableLocalizedStringFactory
from sims4.service_manager import Service
from sims4.tuning.tunable import TunableRealSecond, TunableSimMinute, TunableInterval, TunableTuple
from sims4.utils import exception_protected
import camera
import element_utils
import elements
import enum
import persistence_error_types
import persistence_module
import scheduling
import services
import sims4.log
import ui.ui_dialog
logger = sims4.log.Logger('Persistence')

class PersistenceTuning:
    __qualname__ = 'PersistenceTuning'
    SAVE_GAME_COOLDOWN = TunableRealSecond(0, minimum=0, description='Cooldown on the save game button to prevent users from saving too often.')
    MAX_LOT_SIMULATE_ELAPSED_TIME = TunableSimMinute(description='\n        When we load a lot that was saved in the past and world time has\n        elapsed, this is the max amount of time the lot will pretend time will\n        elapse. EX: lot was saved at 8:00am sunday. The player goes to another\n        lot at that point and plays until 8:00am Tuesday. If max simulated time\n        is set to 1440 mins (24 hours), the lot will load and realize more than\n        24 hours have passed between sunday and tuesday, so the lot will start\n        off at time 8:00am Tuesday - 24 hours = 8:00am Monday. And then the lot\n        will progress for 24 hours forwards to Tuesday.\n        ', default=1440, minimum=0)
    MINUTES_STAY_ON_LOT_BEFORE_GO_HOME = TunableInterval(description="\n        For all sims, when the sim is saved NOT on their home lot, we use this\n        interval to determine how many minutes they'll stay on that lot before\n        they go home. \n\n        Then, if we load up the non-home lot past this amount of time, that sim\n        will no longer be on that lot because that sim will have gone home.\n        \n        If the we load up on the sim's home lot -- if less than this amount of\n        time has passed, we set an alarm so that the sim will spawn into their\n        home lot at the saved time. If equal or more than this amount of time\n        has passed, that sim will be spawned in at zone load.\n        \n        The amount of time is a range. When loading, we'll randomly pick between\n        the upper and lower limit of the range.\n        ", tunable_type=TunableSimMinute, default_lower=180, default_upper=240, minimum=0)
    SAVE_FAILED_REASONS = TunableTuple(description='\n        Localized strings to display when the user cannot save.\n        ', generic=TunableLocalizedString(description='\n            Generic message for why game cannot be saved at the moment\n            '), on_cooldown=TunableLocalizedString(description='\n            The message to show when save game failed due to save being on cooldown\n            '), exception_occurred=TunableLocalizedStringFactory(description='\n            The message to show when save game failed due to an exception occuring during save\n            '))
    LOAD_ERROR_REQUEST_RESTART = ui.ui_dialog.UiDialogOk.TunableFactory(description='\n        The dialog that will be triggered when exception occurred during load of zone and ask user to restart game.\n        ')
    LOAD_ERROR = ui.ui_dialog.UiDialogOk.TunableFactory(description='\n        The dialog that will be triggered when exception occurred during load of zone.\n        ')

class SaveGameResult(enum.Int, export=False):
    __qualname__ = 'SaveGameResult'
    SUCCESS = 0
    FAILED_ON_COOLDOWN = 1
    FAILED_EXCEPTION_OCCURRED = 2
    FAILED_SAVE_LOCKED = 3

SaveGameData = collections.namedtuple('SaveGameData', ('slot_id', 'slot_name', 'force_override', 'auto_save_slot_id'))

class PersistenceService(Service):
    __qualname__ = 'PersistenceService'

    def __init__(self):
        super().__init__()
        self._save_locks = []
        self._save_game_data_proto = serialization.SaveGameData()
        self.save_timeline = None
        self.save_error_code = persistence_error_types.ErrorCodes.NO_ERROR
        self._read_write_locked = False

    def setup(self, **kwargs):
        self._time_of_last_save = None

    def is_save_locked(self):
        if self._read_write_locked:
            return True
        if not self._save_locks:
            return False
        return True

    def get_save_lock_tooltip(self):
        if self._read_write_locked:
            return PersistenceTuning.SAVE_FAILED_REASONS.generic
        if self._save_locks:
            return self._save_locks[-1].get_lock_save_reason()

    def set_read_write_lock(self, is_locked, reference_id):
        self._read_write_locked = is_locked

    def get_save_game_data_proto(self):
        return self._save_game_data_proto

    def lock_save(self, lock_holder):
        self._save_locks.append(lock_holder)
        msg = UI_pb2.GameSaveLockUnlock()
        msg.is_locked = True
        msg.lock_reason = lock_holder.get_lock_save_reason()
        distributor = Distributor.instance()
        distributor.add_event(MSG_GAME_SAVE_LOCK_UNLOCK, msg)

    def unlock_save(self, lock_holder, send_event=True):
        if lock_holder in self._save_locks:
            self._save_locks.remove(lock_holder)
        if send_event:
            if not self.is_save_locked():
                msg = UI_pb2.GameSaveLockUnlock()
                msg.is_locked = False
                distributor = Distributor.instance()
                distributor.add_event(MSG_GAME_SAVE_LOCK_UNLOCK, msg)
            else:
                new_lock_holder = self._save_locks[-1]
                msg = UI_pb2.GameSaveLockUnlock()
                msg.is_locked = True
                msg.lock_reason = new_lock_holder.get_lock_save_reason()
                distributor = Distributor.instance()
                distributor.add_event(MSG_GAME_SAVE_LOCK_UNLOCK, msg)

    def _create_save_timeline(self):
        self._destroy_save_timeline(self.save_timeline)
        self.save_timeline = scheduling.Timeline(services.time_service().sim_now)

    def _destroy_save_timeline(self, timeline):
        if self.save_timeline is not timeline:
            raise RuntimeError('Attempting to destroy the wrong timeline!')
        if self.save_timeline is not None:
            self.save_timeline = None
            timeline.teardown()

    def save_using(self, save_generator, *args, **kwargs):

        def call_save_game_gen(timeline):
            result = yield save_generator(timeline, *args, **kwargs)
            return result

        self._create_save_timeline()
        element = elements.GeneratorElement(call_save_game_gen)
        element = elements.WithFinallyElement(element, self._destroy_save_timeline)
        element_handle = self.save_timeline.schedule(element)
        return element_handle

    def save_to_scratch_slot_gen(self, timeline):
        save_game_data = SaveGameData(0, 'scratch', True, None)
        save_result_code = yield self.save_game_gen(timeline, save_game_data, send_save_message=False, check_cooldown=False)
        return save_result_code

    def save_game_gen(self, timeline, save_game_data, send_save_message=True, check_cooldown=False):
        (result_code, failure_reason) = yield self._save_game_gen(timeline, save_game_data, check_cooldown=check_cooldown)
        if send_save_message:
            msg = UI_pb2.GameSaveComplete()
            msg.return_status = result_code
            msg.save_cooldown = self._get_cooldown()
            if failure_reason is not None:
                msg.failure_reason = failure_reason
            msg.slot_id = save_game_data.slot_id
            distributor = Distributor.instance()
            distributor.add_event(MSG_GAME_SAVE_COMPLETE, msg)
        return result_code

    def _save_game_gen(self, timeline, save_game_data, check_cooldown=True):
        save_lock_reason = self.get_save_lock_tooltip()
        if save_lock_reason is not None:
            return (SaveGameResult.FAILED_SAVE_LOCKED, save_lock_reason)
        current_time = services.server_clock_service().now()
        result_code = SaveGameResult.FAILED_ON_COOLDOWN
        if self._time_of_last_save is not None:
            cooldown = (current_time - self._time_of_last_save).in_real_world_seconds()
        else:
            cooldown = PersistenceTuning.SAVE_GAME_COOLDOWN + 1
        if not check_cooldown or cooldown > PersistenceTuning.SAVE_GAME_COOLDOWN:
            result_code = SaveGameResult.SUCCESS
            error_code_string = None
            try:
                yield self._fill_and_send_save_game_protobufs_gen(timeline, save_game_data.slot_id, save_game_data.slot_name, auto_save_slot_id=save_game_data.auto_save_slot_id)
            except Exception as e:
                result_code = SaveGameResult.FAILED_EXCEPTION_OCCURRED
                error_code_string = persistence_error_types.generate_exception_code(self.save_error_code, e)
                logger.exception('Save failed due to Exception', exc=e)
            finally:
                self.save_error_code = persistence_error_types.ErrorCodes.NO_ERROR
        if check_cooldown and result_code == SaveGameResult.SUCCESS:
            self._time_of_last_save = current_time
        failure_reason = self._get_failure_reason_for_result_code(result_code, error_code_string)
        return (result_code, failure_reason)

    def _get_failure_reason_for_result_code(self, result_code, exception_code_string):
        if result_code == SaveGameResult.SUCCESS:
            return
        if result_code == SaveGameResult.FAILED_ON_COOLDOWN:
            return PersistenceTuning.SAVE_FAILED_REASONS.on_cooldown
        if result_code == SaveGameResult.FAILED_EXCEPTION_OCCURRED:
            return PersistenceTuning.SAVE_FAILED_REASONS.exception_occurred(exception_code_string)
        return PersistenceTuning.SAVE_FAILED_REASONS.generic

    def _get_cooldown(self):
        if self._time_of_last_save is not None:
            current_time = services.server_clock_service().now()
            cooldown = PersistenceTuning.SAVE_GAME_COOLDOWN - (current_time - self._time_of_last_save).in_real_world_seconds()
            return cooldown
        return 0

    def _fill_and_send_save_game_protobufs_gen(self, timeline, slot_id, slot_name, auto_save_slot_id=None):
        self.save_error_code = persistence_error_types.ErrorCodes.SETTING_SAVE_SLOT_DATA_FAILED
        save_slot_data_msg = self.get_save_slot_proto_buff()
        save_slot_data_msg.slot_id = slot_id
        save_slot_data_msg.slot_name = slot_name
        if services.active_household_id() is not None:
            save_slot_data_msg.active_household_id = services.active_household_id()
        sims4.core_services.service_manager.save_all_services(self, persistence_error_types.ErrorCodes.CORE_SERICES_SAVE_FAILED, save_slot_data=save_slot_data_msg)
        self.save_error_code = persistence_error_types.ErrorCodes.SAVE_CAMERA_DATA_FAILED
        camera.serialize(save_slot_data=save_slot_data_msg)

        def on_save_complete(slot_id, success):
            wakeable_element.trigger_soft_stop()

        self.save_error_code = persistence_error_types.ErrorCodes.SAVE_TO_SLOT_FAILED
        wakeable_element = element_utils.soft_sleep_forever()
        persistence_module.run_persistence_operation(persistence_module.PersistenceOpType.kPersistenceOpSave, self._save_game_data_proto, slot_id, on_save_complete)
        yield element_utils.run_child(timeline, wakeable_element)
        if auto_save_slot_id is not None:
            self.save_error_code = persistence_error_types.ErrorCodes.AUTOSAVE_TO_SLOT_FAILED
            wakeable_element = element_utils.soft_sleep_forever()
            persistence_module.run_persistence_operation(persistence_module.PersistenceOpType.kPersistenceOpSave, self._save_game_data_proto, auto_save_slot_id, on_save_complete)
            yield element_utils.run_child(timeline, wakeable_element)
        self.save_error_code = persistence_error_types.ErrorCodes.NO_ERROR

    def get_lot_proto_buff(self, lot_id):
        zone_id = self.resolve_lot_id_into_zone_id(lot_id)
        if zone_id is not None:
            neighborhood_data = self.get_neighborhood_proto_buff(services.current_zone().neighborhood_id)
            if neighborhood_data is not None:
                while True:
                    for lot_owner_data in neighborhood_data.lots:
                        while zone_id == lot_owner_data.zone_instance_id:
                            return lot_owner_data

    def get_zone_proto_buff(self, zone_id):
        if self._save_game_data_proto is not None:
            for zone in self._save_game_data_proto.zones:
                while zone.zone_id == zone_id:
                    return zone

    def get_world_id_from_zone(self, zone_id):
        zone_proto = self.get_zone_proto_buff(zone_id)
        if zone_proto is None:
            return 0
        return zone_proto.world_id

    def zone_proto_buffs_gen(self):
        if self._save_game_data_proto is not None:
            for zone in self._save_game_data_proto.zones:
                yield zone

    def get_open_street_proto_buff(self, world_id):
        if self._save_game_data_proto is not None:
            for open_street in self._save_game_data_proto.streets:
                while open_street.world_id == world_id:
                    return open_street

    def add_open_street_proto_buff(self, open_street_proto):
        if self._save_game_data_proto is not None:
            self._save_game_data_proto.streets.append(open_street_proto)

    def get_household_id_from_lot_id(self, lot_id):
        lot_owner_info = self.get_lot_proto_buff(lot_id)
        if lot_owner_info is not None:
            for household in lot_owner_info.lot_owner:
                pass

    def resolve_lot_id_into_zone_id(self, lot_id, neighborhood_id=None, ignore_neighborhood_id=False):
        if neighborhood_id is None:
            neighborhood_id = services.current_zone().neighborhood_id
        if self._save_game_data_proto is not None:
            for zone in self._save_game_data_proto.zones:
                while zone.lot_id == lot_id:
                    if ignore_neighborhood_id or zone.neighborhood_id == neighborhood_id:
                        return zone.zone_id

    def get_save_slot_proto_buff(self):
        if self._save_game_data_proto is not None:
            return self._save_game_data_proto.save_slot

    def get_account_proto_buff(self):
        if self._save_game_data_proto is not None:
            return self._save_game_data_proto.account

    def get_sim_proto_buff(self, sim_id):
        if self._save_game_data_proto is not None:
            for sim in self._save_game_data_proto.sims:
                while sim.sim_id == sim_id:
                    return sim

    def get_neighborhood_proto_buff(self, neighborhood_id):
        if self._save_game_data_proto is not None:
            for neighborhood in self._save_game_data_proto.neighborhoods:
                while neighborhood.neighborhood_id == neighborhood_id:
                    return neighborhood

    def del_sim_proto_buff(self, sim_id):
        if self._save_game_data_proto is not None:
            count = 0
            for sim in self._save_game_data_proto.sims:
                if sim.sim_id == sim_id:
                    del self._save_game_data_proto.sims[count]
                    break
                count = count + 1

    def del_household_proto_buff(self, household_id):
        if self._save_game_data_proto is not None:
            count = 0
            for household in self._save_game_data_proto.households:
                if household.household_id == household_id:
                    del self._save_game_data_proto.households[count]
                    break
                count = count + 1

    def add_sim_proto_buff(self):
        return self._save_game_data_proto.sims.add()

    def get_household_proto_buff(self, household_id):
        if self._save_game_data_proto is not None:
            for household in self._save_game_data_proto.households:
                while household.household_id == household_id:
                    return household

    def add_household_proto_buff(self):
        return self._save_game_data_proto.households.add()

    def get_neighborhoods_proto_buf_gen(self):
        for neighborhood_proto_buf in self._save_game_data_proto.neighborhoods:
            yield neighborhood_proto_buf

    def all_household_proto_gen(self):
        if self._save_game_data_proto is not None:
            for household in self._save_game_data_proto.households:
                yield household

@exception_protected(None)
def c_api_get_data_readonly():
    save_game_data_proto = services.get_persistence_service().get_save_game_data_proto()
    return save_game_data_proto

@exception_protected(None)
def c_api_get_data_readwrite(reference_id):
    save_game_data_proto = services.get_persistence_service().get_save_game_data_proto()
    services.get_persistence_service().set_read_write_lock(True, reference_id)
    return save_game_data_proto

@exception_protected(None)
def c_api_save_data(reference_id):
    services.get_persistence_service().set_read_write_lock(False, reference_id)
    return True

@exception_protected(None)
def c_api_release_data(reference_id):
    services.get_persistence_service().set_read_write_lock(False, reference_id)
    return True

