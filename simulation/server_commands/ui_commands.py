from server_commands.argument_helpers import OptionalTargetParam
from sims4.localization import LocalizationHelperTuning
from ui.ui_dialog_notification import UiDialogNotification
import services
import sims4.commands

@sims4.commands.Command('ui.dialog.respond', command_type=sims4.commands.CommandType.Live)
def ui_dialog_respond(dialog_id, response, _connection=None):
    zone = services.current_zone()
    if not zone.ui_dialog_service.dialog_respond(dialog_id, response):
        sims4.commands.output('That is not a valid response.', _connection)
        return False
    return True

@sims4.commands.Command('ui.dialog.pick_result', command_type=sims4.commands.CommandType.Live)
def ui_dialog_pick_result(dialog_id, ingredient_check, *choices, _connection=None):
    zone = services.current_zone()
    if not zone.ui_dialog_service.dialog_pick_result(dialog_id, choices, ingredient_check=ingredient_check):
        sims4.commands.output('That is not a valid pick result.', _connection)
        return False
    return True

@sims4.commands.Command('ui.dialog.text_input', command_type=sims4.commands.CommandType.Live)
def ui_dialog_text_input(dialog_id, text_input_name, text_input_value, _connection=None):
    zone = services.current_zone()
    if not zone.ui_dialog_service.dialog_text_input(dialog_id, text_input_name, text_input_value):
        sims4.commands.output('Unable to set dialog text input for {0} to {1}'.format(text_input_name, text_input_value), _connection)
        return False
    return True

@sims4.commands.Command('ui.dialog.auto_respond', command_type=sims4.commands.CommandType.Automation)
def ui_dialog_auto_respond(enable:bool=None, _connection=None):
    zone = services.current_zone()
    auto_respond = enable if enable is not None else not zone.ui_dialog_service.auto_respond
    zone.ui_dialog_service.auto_respond = auto_respond
    sims4.commands.output('UI Dialog auto_respond set to {}'.format(auto_respond), _connection)

@sims4.commands.Command('ui.toggle_silence_phone', command_type=sims4.commands.CommandType.Live)
def toggle_silence_phone(sim_id:OptionalTargetParam=None, _connection=None):
    zone = services.current_zone()
    zone.ui_dialog_service.toggle_is_phone_silenced()
    return True

@sims4.commands.Command('ui.dialog.notification_test')
def ui_dialog_notification_test(*all_text, _connection=None):
    client = services.client_manager().get(_connection)
    all_text_str = ' '.join(all_text)
    if '/' in all_text:
        (title, text) = all_text_str.split('/')
        notification = UiDialogNotification.TunableFactory().default(client.active_sim, text=lambda **_: LocalizationHelperTuning.get_raw_text(text), title=lambda **_: LocalizationHelperTuning.get_raw_text(title))
    else:
        notification = UiDialogNotification.TunableFactory().default(client.active_sim, text=lambda **_: LocalizationHelperTuning.get_raw_text(all_text_str))
    notification.show_dialog(icon_override=(None, client.active_sim))

