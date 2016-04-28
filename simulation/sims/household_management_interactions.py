from distributor.ops import GenericProtocolBufferOp
from event_testing.resolver import DataResolver
from interactions import ParticipantType
from interactions.base.immediate_interaction import ImmediateSuperInteraction
from interactions.base.super_interaction import SuperInteraction
from protocolbuffers import DistributorOps_pb2, Consts_pb2, InteractionOps_pb2
from ui.ui_dialog import UiDialogOkCancel
import distributor
import event_testing.test_variants
import services

class MoveInMoveOutSuperInteraction(SuperInteraction):
    __qualname__ = 'MoveInMoveOutSuperInteraction'

    def _run_interaction_gen(self, timeline):
        msg = InteractionOps_pb2.MoveInMoveOutInfo()
        distributor.system.Distributor.instance().add_event(Consts_pb2.MSG_MOVE_IN_MOVE_OUT, msg)
        return True

class MoveInSuperInteraction(ImmediateSuperInteraction):
    __qualname__ = 'MoveInSuperInteraction'
    INSTANCE_TUNABLES = {'dialog': UiDialogOkCancel.TunableFactory(description='\n            The dialog box presented to ask if the player should move their Sims in together.'), 'situation_blacklist': event_testing.test_variants.TunableSituationRunningTest()}

    def _run_interaction_gen(self, timeline):
        services.sim_info_manager()._set_default_genealogy()
        resolver = DataResolver(self.sim.sim_info)
        if not resolver(self.situation_blacklist):
            return True
        if not self.target.is_sim:
            return True
        if self.sim.household_id == self.target.household_id:
            return True

        def on_response(dialog):
            if not dialog.accepted:
                self.cancel_user(cancel_reason_msg='Move-In. Player canceled, or move in together dialog timed out from client.')
                return
            actor = self.get_participant(ParticipantType.Actor)
            src_household_id = actor.sim_info.household.id
            target = self.target
            tgt_household_id = target.sim_info.household.id
            client_manager = services.client_manager()
            if client_manager is not None:
                client = client_manager.get_first_client()
                if client is not None:
                    active_sim_id = client.active_sim.id
            if src_household_id is not None and tgt_household_id is not None and active_sim_id is not None:
                transfer_info = InteractionOps_pb2.SimTransferRequest()
                transfer_info.source_household_id = src_household_id
                transfer_info.target_household_id = tgt_household_id
                transfer_info.active_sim_id = active_sim_id
                system_distributor = distributor.system.Distributor.instance()
                generic_pb_op = GenericProtocolBufferOp(DistributorOps_pb2.Operation.SIM_TRANSFER_REQUEST, transfer_info)
                system_distributor.add_op_with_no_owner(generic_pb_op)

        dialog = self.dialog(self.sim, self.get_resolver())
        dialog.show_dialog(on_response=on_response)
        return True

