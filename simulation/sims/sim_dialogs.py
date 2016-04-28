from protocolbuffers import Dialog_pb2
from protocolbuffers.DistributorOps_pb2 import Operation
from aspirations.aspiration_types import AspriationType
from distributor.ops import GenericProtocolBufferOp
from distributor.system import Distributor
from sims.sim_info_types import Gender
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.tunable import OptionalTunable
from ui.ui_dialog import UiDialogResponse, ButtonType
from ui.ui_dialog_generic import UiDialogTextInput
import services
import sims4

class SimPersonalityAssignmentDialog(UiDialogTextInput):
    __qualname__ = 'SimPersonalityAssignmentDialog'
    FACTORY_TUNABLES = {'secondary_title': TunableLocalizedStringFactory(description='\n                The secondary title of the dialog box.\n                '), 'age_description': TunableLocalizedStringFactory(description='\n                Text to explain the age moment.\n                '), 'naming_title_text': OptionalTunable(description='\n                If enabled, this text will appear above the fields to rename\n                the sim.\n                ', tunable=TunableLocalizedStringFactory(description='\n                    Text that will appear above the fields to rename the sim.\n                    ')), 'aspirations_and_trait_assignment': OptionalTunable(description='\n                If enabled, we will show the aspiration and trait assignment\n                portion of the dialog.\n                ', tunable=TunableLocalizedStringFactory(description='\n                    Text that will appear above aspiration and trait assignment.\n                    '))}
    DIALOG_MSG_TYPE = Operation.MSG_SIM_PERSONALITY_ASSIGNMENT

    def __init__(self, *args, assignment_sim_info=None, **kwargs):
        super().__init__(*args, **kwargs)
        if assignment_sim_info is None:
            self._assignment_sim_info = self.owner.sim_info
        else:
            self._assignment_sim_info = assignment_sim_info

    def build_msg(self, additional_tokens=(), trait_overrides_for_baby=None, gender_overrides_for_baby=None, **kwargs):
        msg = Dialog_pb2.SimPersonalityAssignmentDialog()
        msg.sim_id = self._assignment_sim_info.id
        dialog_msg = super().build_msg(additional_tokens=additional_tokens, **kwargs)
        msg.dialog = dialog_msg
        msg.secondary_title = self._build_localized_string_msg(self.secondary_title, *additional_tokens)
        msg.age_description = self._build_localized_string_msg(self.age_description, *additional_tokens)
        if self.naming_title_text is not None:
            msg.naming_title_text = self._build_localized_string_msg(self.naming_title_text, *additional_tokens)
        if gender_overrides_for_baby is None:
            gender = self._assignment_sim_info.gender
        else:
            gender = gender_overrides_for_baby
        msg.is_female = gender == Gender.FEMALE
        if self.aspirations_and_trait_assignment is not None:
            msg.aspirations_and_trait_assignment_text = self._build_localized_string_msg(self.aspirations_and_trait_assignment, *additional_tokens)
            if trait_overrides_for_baby is None:
                empty_slots = self._assignment_sim_info.trait_tracker.empty_slot_number
                current_personality_traits = self._assignment_sim_info.trait_tracker.personality_traits
            else:
                empty_slots = 0
                current_personality_traits = trait_overrides_for_baby
            msg.available_trait_slots = empty_slots
            for current_personality_trait in current_personality_traits:
                msg.current_personality_trait_ids.append(current_personality_trait.guid64)
            msg.available_trait_slots = empty_slots
            if empty_slots != 0:
                for trait in services.trait_manager().types.values():
                    if not trait.is_personality_trait:
                        pass
                    if not trait.test_sim_info(self._assignment_sim_info):
                        pass
                    for current_personality_trait in current_personality_traits:
                        while trait.guid64 == current_personality_trait.guid64 or trait.is_conflicting(current_personality_trait):
                            break
                    msg.available_personality_trait_ids.append(trait.guid64)
            if trait_overrides_for_baby is None and (self._assignment_sim_info.is_child or self._assignment_sim_info.is_teen):
                aspiration_track_manager = services.get_instance_manager(sims4.resources.Types.ASPIRATION_TRACK)
                while True:
                    for aspiration_track in aspiration_track_manager.types.values():
                        if aspiration_track.is_child_aspiration_track:
                            if self._assignment_sim_info.is_child:
                                msg.available_aspiration_ids.append(aspiration_track.guid64)
                                while self._assignment_sim_info.is_teen:
                                    msg.available_aspiration_ids.append(aspiration_track.guid64)
                        else:
                            while self._assignment_sim_info.is_teen:
                                msg.available_aspiration_ids.append(aspiration_track.guid64)
        return msg

    def distribute_dialog(self, dialog_type, dialog_msg):
        distributor = Distributor.instance()
        personality_assignement_op = GenericProtocolBufferOp(dialog_type, dialog_msg)
        distributor.add_op(self.owner, personality_assignement_op)

    @property
    def responses(self):
        return (UiDialogResponse(dialog_response_id=ButtonType.DIALOG_RESPONSE_OK, ui_request=UiDialogResponse.UiDialogUiRequest.NO_REQUEST),)

