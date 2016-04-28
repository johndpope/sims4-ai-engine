from animation.posture_manifest import Hand
from interactions.aop import AffordanceObjectPair
from interactions.base.super_interaction import SuperInteraction
from postures.posture_specs import PostureOperation
from sims4.tuning.tunable import TunableReference
from sims4.utils import classproperty
import services

class HoldObjectBase(SuperInteraction):
    __qualname__ = 'HoldObjectBase'

    @classmethod
    def potential_interactions(cls, target, context, **kwargs):
        yield AffordanceObjectPair(cls, target, cls, None, hand=Hand.LEFT, **kwargs)
        yield AffordanceObjectPair(cls, target, cls, None, hand=Hand.RIGHT, **kwargs)

class HoldObject(HoldObjectBase):
    __qualname__ = 'HoldObject'
    INSTANCE_TUNABLES = {'_carry_posture_type': TunableReference(services.posture_manager(), description='The carry posture type for this version of HoldObject.')}

    @classmethod
    def get_provided_posture_change(cls, aop):
        return PostureOperation.PickUpObject(cls._carry_posture_type, aop.target)

    @classproperty
    def provided_posture_type(cls):
        return cls._carry_posture_type

class HoldNothing(HoldObjectBase):
    __qualname__ = 'HoldNothing'
    CARRY_NOTHING_POSTURE_TYPE = TunableReference(services.posture_manager(), description='The Posture Type for Carry Nothing.')

    @classmethod
    def get_provided_posture_change(cls, aop):
        return PostureOperation.PickUpObject(cls.CARRY_NOTHING_POSTURE_TYPE, None)

    @classproperty
    def provided_posture_type(cls):
        return cls.CARRY_NOTHING_POSTURE_TYPE

