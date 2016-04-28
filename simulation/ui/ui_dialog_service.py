from distributor.ops import SetPhoneSilence
from distributor.system import Distributor
from protocolbuffers import Consts_pb2, Dialog_pb2
from sims4.service_manager import Service
from ui.ui_dialog import PhoneRingType
import services

class UiDialogService(Service):
    __qualname__ = 'UiDialogService'

    def __init__(self):
        self._active_dialogs = {}
        self.auto_respond = False
        self._is_phone_silenced = False
        self._enabled = True

    def disable_on_teardown(self):
        self._enabled = False

    @property
    def is_phone_silenced(self):
        return self._is_phone_silenced

    def _set_is_phone_silenced(self, value):
        self._is_phone_silenced = value
        op = SetPhoneSilence(self._is_phone_silenced)
        distributor = Distributor.instance()
        distributor.add_op_with_no_owner(op)

    def toggle_is_phone_silenced(self):
        self._set_is_phone_silenced(not self._is_phone_silenced)

    def dialog_show(self, dialog, phone_ring_type, **kwargs):
        if not self._enabled:
            return
        self._active_dialogs[dialog.dialog_id] = dialog
        if dialog.has_responses() and self.auto_respond:
            dialog.do_auto_respond()
            return
        dialog_msg = dialog.build_msg(**kwargs)
        if phone_ring_type != PhoneRingType.NO_RING:
            if self._is_phone_silenced:
                return
            msg_type = Consts_pb2.MSG_UI_PHONE_RING
            msg_data = Dialog_pb2.UiPhoneRing()
            msg_data.phone_ring_type = phone_ring_type
            msg_data.dialog = dialog_msg
            distributor = Distributor.instance()
            distributor.add_event(msg_type, msg_data)
        else:
            msg_type = dialog.DIALOG_MSG_TYPE
            msg_data = dialog_msg
            dialog.distribute_dialog(msg_type, msg_data)

    def _dialog_cancel_internal(self, dialog):
        msg = Dialog_pb2.UiDialogCloseRequest()
        msg.dialog_id = dialog.dialog_id
        distributor = Distributor.instance()
        distributor.add_event(Consts_pb2.MSG_UI_DIALOG_CLOSE, msg)
        del self._active_dialogs[dialog.dialog_id]

    def dialog_cancel(self, dialog_id):
        dialog = self._active_dialogs.get(dialog_id, None)
        if dialog is not None:
            self._dialog_cancel_internal(dialog)

    def dialog_respond(self, dialog_id, response, client=None) -> bool:
        dialog = self._active_dialogs.get(dialog_id, None)
        if dialog is not None:
            try:
                if dialog.respond(response):
                    self._dialog_cancel_internal(dialog)
                    return True
            except:
                self._dialog_cancel_internal(dialog)
                raise
        return False

    def dialog_pick_result(self, dialog_id, picked_results=[], ingredient_check=None) -> bool:
        dialog = self._active_dialogs.get(dialog_id, None)
        if dialog is not None and dialog.pick_results(picked_results, ingredient_check):
            return True
        return False

    def dialog_text_input(self, dialog_id, text_input_name, text_input_value) -> bool:
        dialog = self._active_dialogs.get(dialog_id, None)
        if dialog is not None and dialog.on_text_input(text_input_name, text_input_value):
            return True
        return False

    def send_dialog_options_to_client(self):
        save_slot_data_msg = services.get_persistence_service().get_save_slot_proto_buff()
        self._set_is_phone_silenced(save_slot_data_msg.gameplay_data.is_phone_silenced)

    def save(self, save_slot_data=None, **kwargs):
        save_slot_data.gameplay_data.is_phone_silenced = self._is_phone_silenced

