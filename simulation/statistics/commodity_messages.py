from distributor.ops import Op
from protocolbuffers.DistributorOps_pb2 import Operation
from distributor.system import Distributor

def send_sim_commodity_progress_update_message(sim, msg):
    if sim.is_selectable and sim.valid_for_distribution:
        distributor = Distributor.instance()
        op = SimCommodityProgressUpdateOp(msg)
        distributor.add_op(sim, op)

class SimCommodityProgressUpdateOp(Op):
    __qualname__ = 'SimCommodityProgressUpdateOp'

    def __init__(self, protocol_buffer):
        super().__init__()
        self.protocol_buffer = protocol_buffer

    def write(self, msg):
        msg.type = Operation.SIM_COMMODITY_PROGRESS_UPDATE
        msg.data = self.protocol_buffer.SerializeToString()

