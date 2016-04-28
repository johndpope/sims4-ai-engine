from protocolbuffers import DistributorOps_pb2 as protocols
from protocolbuffers.VFX_pb2 import VFXStart, VFXStop
from distributor.ops import StopVFX
from distributor.system import get_current_tag_set
from element_utils import build_critical_section_with_finally
from sims4.repr_utils import standard_angle_repr
from sims4.tuning.tunable import TunableFactory, Tunable, HasTunableFactory, TunableList, AutoFactoryInit
from singletons import DEFAULT
from uid import unique_id
import distributor.ops
import services
import sims4.log
logger = sims4.log.Logger('Animation')

@unique_id('actor_id')
class PlayEffect(distributor.ops.ElementDistributionOpMixin, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'PlayEffect'

    @staticmethod
    def _verify_tunable_callback(source, *_, effect_name, joint_name, **__):
        if not effect_name:
            logger.error('VFX in {} does not specify a valid name'.format(source))
        if not joint_name:
            logger.error('VFX {} in {} does not specify a valid joint name'.format(effect_name, source))

    FACTORY_TUNABLES = {'effect_name': Tunable(description='\n            The name of the effect to play.\n            ', tunable_type=str, default=''), 'joint_name': Tunable(description='\n            The name of the slot this effect is attached to.\n            ', tunable_type=str, default='_FX_'), 'auto_on_effect': Tunable(description='\n            Starts the VFX when the light is controlled through auto lighting.\n            ', tunable_type=bool, default=False), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, target, effect_name='', joint_name_hash=DEFAULT, target_actor_id=0, target_joint_name_hash=0, joint_name='', mirror_effect=False, auto_on_effect=False, **kwargs):
        super().__init__(effect_name=effect_name, joint_name=joint_name, auto_on_effect=auto_on_effect, **kwargs)
        self.target = target
        self.effect_name = effect_name
        self.joint_name_hash = joint_name_hash if joint_name_hash is not DEFAULT else sims4.hash_util.hash32(self.joint_name)
        self.target_actor_id = target_actor_id
        self.target_joint_name_hash = target_joint_name_hash
        self.mirror_effect = mirror_effect
        self._stop_type = VFXStop.SOFT_TRANSITION

    def __repr__(self):
        return standard_angle_repr(self, self.effect_name)

    def start(self, *_, **__):
        if not self._is_valid_target():
            return
        if not self.is_attached:
            self.attach(self.target)
            logger.info('VFX {} on {} START'.format(self.effect_name, self.target))

    def start_one_shot(self):
        distributor.ops.record(self.target, self)

    def stop(self, *_, immediate=False, **kwargs):
        if not self._is_valid_target():
            return
        if self.is_attached:
            if immediate:
                self._stop_type = VFXStop.HARD_TRANSITION
            else:
                self._stop_type = VFXStop.SOFT_TRANSITION
            self.detach()

    def _is_valid_target(self):
        if not self.target.valid_for_distribution:
            zone = services.current_zone()
            if zone is not None:
                zone_spin_up_service = zone.zone_spin_up_service
                if zone_spin_up_service is None:
                    logger.callstack('zone_spin_up_service was None in PlayEffect._is_valid_target(), for effect/target: {}/{}', self, self.target, owner='johnwilkinson', level=sims4.log.LEVEL_ERROR)
                    return False
                if not zone_spin_up_service.is_finished:
                    return False
        return True

    def detach(self, *objects):
        super().detach(*objects)
        op = StopVFX(self.target.id, self.actor_id, stop_type=self._stop_type)
        distributor.ops.record(self.target, op)
        logger.info('VFX {} on {} STOP'.format(self.effect_name, self.target))

    def write(self, msg):
        start_msg = VFXStart()
        start_msg.object_id = self.target.id
        start_msg.effect_name = self.effect_name
        start_msg.actor_id = self.actor_id
        start_msg.joint_name_hash = self.joint_name_hash
        start_msg.target_actor_id = self.target_actor_id
        start_msg.target_joint_name_hash = self.target_joint_name_hash
        start_msg.mirror_effect = self.mirror_effect
        start_msg.auto_on_effect = self.auto_on_effect
        msg.type = protocols.Operation.VFX_START
        msg.data = start_msg.SerializeToString()

class PlayMultipleEffects(HasTunableFactory):
    __qualname__ = 'PlayMultipleEffects'
    FACTORY_TUNABLES = {'description': '\n            Play multiple visual effects.\n            ', 'vfx_list': TunableList(description='\n            A list of effects to play\n            ', tunable=PlayEffect.TunableFactory(description='\n                A single effect to play.\n                '))}

    def __init__(self, owner, *args, vfx_list=None, **kwargs):
        self.vfx_list = []
        for vfx_factory in vfx_list:
            self.vfx_list.append(vfx_factory(owner))

    def start(self, *args, **kwargs):
        for play_effect in self.vfx_list:
            play_effect.start(*args, **kwargs)

    def stop(self, *args, **kwargs):
        for play_effect in self.vfx_list:
            play_effect.stop(*args, **kwargs)

