from distributor.ops import GenericProtocolBufferOp
from protocolbuffers import DistributorOps_pb2 as protocols
from protocolbuffers.Audio_pb2 import SoundStart
from sims4.repr_utils import standard_angle_repr
from sims4.tuning.tunable import TunableFactory, TunableResourceKey
from singletons import DEFAULT
from uid import unique_id
import distributor.ops
import services
import sims4.log
logger = sims4.log.Logger('Audio')

@unique_id('channel')
class PlaySound(distributor.ops.ElementDistributionOpMixin):
    __qualname__ = 'PlaySound'

    def __init__(self, target, sound_id):
        super().__init__()
        if target is None:
            self.target = None
        elif target.is_sim:
            self.target = target
        elif target.is_part:
            self.target = target.part_owner
        else:
            self.target = target
        self.sound_id = sound_id
        self._manually_distributed = False

    def __repr__(self):
        return standard_angle_repr(self, self.channel)

    @property
    def _is_distributed(self):
        return self.is_attached or self._manually_distributed

    def start(self):
        if not self._is_distributed:
            if self.target is not None:
                self.attach(self.target)
            else:
                start_msg = self.build_sound_start_msg(self.sound_id)
                system_distributor = distributor.system.Distributor.instance()
                generic_pb_op = GenericProtocolBufferOp(protocols.Operation.SOUND_START, start_msg)
                system_distributor.add_op_with_no_owner(generic_pb_op)
                self._manually_distributed = True

    def stop(self, *_, **__):
        if self.is_attached:
            self.detach()
        elif self._manually_distributed:
            self._stop_sound()
        else:
            logger.error("Attempting to stop a sound that wasn't distributed.", owner='sscholl')

    def _stop_sound(self):
        if self._is_distributed:
            op = distributor.ops.StopSound(self.target.id, self.channel)
            distributor.ops.record(self.target, op)
            self._manually_distributed = False

    def detach(self, *objects):
        self._stop_sound()
        super().detach(*objects)

    def build_sound_start_msg(self, sound_id, target=None, channel=None):
        start_msg = SoundStart()
        if target is not None:
            start_msg.object_id = self.target.id
        if channel is not None:
            start_msg.channel = self.channel
        start_msg.sound_id = sound_id
        return start_msg

    def write(self, msg):
        start_msg = self.build_sound_start_msg(self.sound_id, self.target, self.channel)
        msg.type = protocols.Operation.SOUND_START
        msg.data = start_msg.SerializeToString()

def play_tunable_audio(tunable_play_audio, owner=DEFAULT):
    if tunable_play_audio is None:
        logger.error('Cannot play an audio clip of type None.', owner='tastle')
        return
    if owner == DEFAULT:
        client = services.client_manager().get_first_client()
        if client.active_sim is None:
            owner = None
        else:
            owner = client.active_sim
    sound = tunable_play_audio(owner)
    sound.start()
    return sound

class TunablePlayAudio(TunableFactory):
    __qualname__ = 'TunablePlayAudio'

    @staticmethod
    def _factory(owner, audio):
        return PlaySound(owner, audio.instance)

    FACTORY_TYPE = _factory

    def __init__(self, **kwargs):
        super().__init__(audio=TunableResourceKey(None, (sims4.resources.Types.PROPX,), description='The sound to play.'), **kwargs)

