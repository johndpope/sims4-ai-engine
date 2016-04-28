from distributor.ops import Op
from distributor.system import Distributor
from element_utils import build_critical_section_with_finally
from protocolbuffers import DistributorOps_pb2 as protocols, Sims_pb2
from sims4.tuning.geometric import TunableVector3
from sims4.tuning.tunable import Tunable, TunableFactory
import sims4.hash_util
import sims4.math

def with_reslot_plumbbob(interaction, bone_name, offset, sequence=None):
    sim = interaction.sim
    target = interaction.target
    target_suffix = target.part_suffix
    if target_suffix is not None:
        bone_name += target_suffix
    distributor = Distributor.instance()

    def reslot(_):
        reslot_op = ReslotPlumbbob(sim.id, target.id, bone_name, offset)
        distributor.add_op(sim, reslot_op)

    def unslot(_):
        reslot_op = ReslotPlumbbob(sim.id, 0, None, sims4.math.Vector3.ZERO())
        distributor.add_op(sim, reslot_op)

    return build_critical_section_with_finally(reslot, sequence, unslot)

class TunableReslotPlumbbob(TunableFactory):
    __qualname__ = 'TunableReslotPlumbbob'
    FACTORY_TYPE = staticmethod(with_reslot_plumbbob)

    def __init__(self, **kwargs):
        super().__init__(bone_name=Tunable(str, None, description='The name of the bone to which the plumbbob should be attached.'), offset=TunableVector3(TunableVector3.DEFAULT_ZERO, description='The Vector3 offset from the bone to the plumbbob.'), **kwargs)

class ReslotPlumbbob(Op):
    __qualname__ = 'ReslotPlumbbob'

    def __init__(self, sim_id, obj_id, bone_name, offset):
        super().__init__()
        self._sim_id = sim_id
        self._obj_id = obj_id
        self._bone_hash = sims4.hash_util.hash32(bone_name) if bone_name else 0
        self._offset = offset

    def write(self, msg):
        reslot_msg = Sims_pb2.ReslotPlumbbob()
        reslot_msg.sim_id = self._sim_id
        reslot_msg.obj_id = self._obj_id
        reslot_msg.bone = self._bone_hash
        reslot_msg.offset.x = self._offset.x
        reslot_msg.offset.y = self._offset.y
        reslot_msg.offset.z = self._offset.z
        msg.type = protocols.Operation.RESLOT_PLUMBBOB
        msg.data = reslot_msg.SerializeToString()

