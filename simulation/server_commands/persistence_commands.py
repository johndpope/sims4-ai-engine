from services.persistence_service import SaveGameData
from sims import sim_info
from sims4.commands import CommandType
import alarms
import clock
import persistence_error_types
import persistence_module
import services
import sims4.commands
with sims4.reload.protected(globals()):
    g_soak_and_save_alarm = None
    g_soak_save_counter = 0
    g_soak_save_slot_start = 100
    g_maximum_soak_save_slots = 10

@sims4.commands.Command('persistence.save_game', command_type=CommandType.Live)
def save_game(send_save_message:bool=False, check_cooldown:bool=True, _connection=None):
    save_game_data = SaveGameData(0, 'scratch', True, None)
    persistence_service = services.get_persistence_service()
    persistence_service.save_using(persistence_service.save_game_gen, save_game_data, send_save_message=send_save_message, check_cooldown=check_cooldown)

@sims4.commands.Command('persistence.override_save_slot', command_type=CommandType.Live)
def override_save_slot(slot_id:int=0, slot_name='Unnamed', auto_save_slot_id:int=None, _connection=None):
    save_game_data = SaveGameData(slot_id, slot_name, True, auto_save_slot_id)
    persistence_service = services.get_persistence_service()
    persistence_service.save_using(persistence_service.save_game_gen, save_game_data, send_save_message=True, check_cooldown=False)

@sims4.commands.Command('persistence.save_to_new_slot', command_type=CommandType.Live)
def save_to_new_slot(slot_id:int=0, slot_name='Unnamed', auto_save_slot_id:int=None, _connection=None):
    save_game_data = SaveGameData(slot_id, slot_name, False, auto_save_slot_id)
    persistence_service = services.get_persistence_service()
    persistence_service.save_using(persistence_service.save_game_gen, save_game_data, send_save_message=True, check_cooldown=False)

@sims4.commands.Command('persistence.save_game_with_autosave', command_type=CommandType.Live)
def save_game_with_autosave(slot_id:int=0, slot_name='Unnamed', is_new_slot:bool=False, auto_save_slot_id:int=None, _connection=None):
    override_slot = not is_new_slot
    save_game_data = SaveGameData(slot_id, slot_name, override_slot, auto_save_slot_id)
    persistence_service = services.get_persistence_service()
    persistence_service.save_using(persistence_service.save_game_gen, save_game_data, send_save_message=True, check_cooldown=False)

@sims4.commands.Command('persistence.save_active_household', command_type=CommandType.Cheat)
def save_current_houshold(slot_id:int=0, slot_name='Unnamed', _connection=None):
    output = sims4.commands.Output(_connection)
    try:
        sim_info.save_active_household_command_start()
        save_slot_data_msg = services.get_persistence_service().get_save_slot_proto_buff()
        save_slot_data_msg.slot_id = slot_id
        active_household = services.active_household()
        if active_household is not None:
            save_slot_data_msg.active_household_id = active_household.id
        sims4.core_services.service_manager.save_all_services(None, persistence_error_types.ErrorCodes.CORE_SERICES_SAVE_FAILED, save_slot_data=save_slot_data_msg)
        save_game_buffer = services.get_persistence_service().get_save_game_data_proto()
        persistence_module.run_persistence_operation(persistence_module.PersistenceOpType.kPersistenceOpSaveHousehold, save_game_buffer, 0, None)
    except Exception as e:
        output('Exception thrown while executing command persistence.save_active_household.\n{}'.format(e))
        output('No household file generated. Please address all the exceptions.')
        raise
    finally:
        sim_info.save_active_household_command_stop()
    output('Exported active household to T:\\InGame\\Households\\{}.household'.format(active_household.name))
    return 1

@sims4.commands.Command('persistence.soak_and_save', command_type=CommandType.Automation)
def soak_and_save(frequency:int=60, _connection=None):
    global g_soak_and_save_alarm
    output = sims4.commands.CheatOutput(_connection)
    time_span = clock.interval_in_sim_minutes(frequency)

    def save_once(_):
        global g_soak_save_counter
        if services.get_persistence_service().is_save_locked():
            output('Saving the game skipped since saving is locked. Next attempt in {}.'.format(time_span))
            return
        save_name = 'SoakSave{}'.format(g_soak_save_counter)
        slot_id = g_soak_save_slot_start + g_soak_save_counter
        if g_soak_save_counter < g_maximum_soak_save_slots:
            save_to_new_slot(slot_id=slot_id, slot_name=save_name, _connection=_connection)
        else:
            override_save_slot(slot_id=slot_id, slot_name=save_name, _connection=_connection)
        g_soak_save_counter = (g_soak_save_counter + 1) % g_maximum_soak_save_slots
        output('Game saved {} at slot {}. Next attempt in {}.'.format(save_name, slot_id, time_span))

    if g_soak_and_save_alarm is not None:
        alarms.cancel_alarm(g_soak_and_save_alarm)
    g_soak_and_save_alarm = alarms.add_alarm(soak_and_save, time_span, save_once, repeating=True)
    output('Saving the game every {}.'.format(time_span))

