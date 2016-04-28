import random
from sims4.tuning.tunable import TunableList
from ui.ui_dialog import UiDialogOkCancel
import services
import sims
import sims4.commands

class CheatCommandTuning:
    __qualname__ = 'CheatCommandTuning'
    ENABLE_CHEATS_DIALOG = UiDialogOkCancel.TunableFactory()
    JOKES = TunableList(str)

@sims4.commands.Command('AutomationTestingCheats', command_type=sims4.commands.CommandType.Automation)
def automation_test_cheats(enable:bool=False, _connection=None):
    tgt_client = services.client_manager().get(_connection)
    output = sims4.commands.CheatOutput(_connection)
    household = tgt_client.household
    household.cheats_enabled = enable
    if enable:
        output('Cheats are enabled.')
    else:
        output('Cheats are disabled.')

@sims4.commands.Command('testingcheats', command_type=sims4.commands.CommandType.Live)
def test_cheats(enable:bool=False, _connection=None):
    tgt_client = services.client_manager().get(_connection)
    output = sims4.commands.CheatOutput(_connection)
    household = tgt_client.household
    cheats_active = household.cheats_enabled
    if cheats_active == enable:
        if enable:
            output('Cheats are already enabled.')
        else:
            output('Cheats are already disabled.')
        return False
    household.cheats_enabled = enable
    if enable:
        output('Cheats are enabled.')
    else:
        output('Cheats are disabled.')
    return True

@sims4.commands.Command('setage', command_type=sims4.commands.CommandType.Live)
def set_age(age:str='Adult', _connection=None):
    output = sims4.commands.Output(_connection)
    tgt_client = services.client_manager().get(_connection)
    if tgt_client.active_sim is None:
        output('Set Sim Age Failure: No Sim Selected')
        return False
    age_to_set = sims.sim_info_types.Age.ADULT
    if age == 'Child':
        age_to_set = sims.sim_info_types.Age.CHILD
    elif age == 'Teen':
        age_to_set = sims.sim_info_types.Age.TEEN
    elif age == 'Young Adult':
        age_to_set = sims.sim_info_types.Age.YOUNGADULT
    elif age == 'Adult':
        age_to_set = sims.sim_info_types.Age.ADULT
    elif age == 'Elder':
        age_to_set = sims.sim_info_types.Age.ELDER
    else:
        output('Set Sim Age Failure: Invalid Age. Options are: Child, Young Adult, Adult, Elder')
        return False
    tgt_client.active_sim.sim_info.advance_age(force_age=age_to_set)
    output('Selected Sim Set to Age: ' + age)
    return True

