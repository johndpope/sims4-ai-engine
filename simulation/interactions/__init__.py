from animation.posture_manifest import AnimationParticipant
from sims4.log import Logger
from sims4.math import MAX_UINT32
from sims4.tuning.dynamic_enum import DynamicEnumFlags, DynamicEnum
import enum
import postures.posture_specs
logger = Logger('Interactions')

class PipelineProgress(enum.Int, export=False):
    __qualname__ = 'PipelineProgress'
    NONE = 0
    QUEUED = 1
    PRE_TRANSITIONING = 2
    PREPARED = 3
    RUNNING = 4
    STAGED = 5
    EXITED = 6

class TargetType(enum.IntFlags):
    __qualname__ = 'TargetType'
    ACTOR = 1
    TARGET = 2
    GROUP = 4
    OBJECT = 8
    TARGET_AND_GROUP = TARGET | GROUP

class ParticipantType(enum.IntFlags):
    __qualname__ = 'ParticipantType'
    _enum_export_path = 'interactions.ParticipantType'
    Invalid = 0
    Actor = 1
    Object = 2
    TargetSim = 4
    Listeners = 8
    All = 16
    AllSims = 32
    Lot = 64
    CraftingProcess = 128
    JoinTarget = 256
    CarriedObject = 512
    Affordance = 1024
    InteractionContext = 2048
    CustomSim = 4096
    AllRelationships = 8192
    CraftingObject = 16384
    ActorSurface = 32768
    ObjectChildren = 65536
    LotOwners = 131072
    CreatedObject = 262144
    PickedItemId = 524288
    StoredSim = 1048576
    PickedObject = 2097152
    SocialGroup = 4194304
    OtherSimsInteractingWithTarget = 8388608
    PickedSim = 16777216
    ObjectParent = 33554432
    SignificantOtherActor = 67108864
    SignificantOtherTargetSim = 134217728
    OwnerSim = 268435456
    StoredSimOnActor = 536870912
    Unlockable = 1073741824
    LiveDragActor = 2147483648
    LiveDragTarget = 4294967296
    PickedZoneId = 8589934592
    SocialGroupSims = 17179869184
    PregnancyPartnerActor = 34359738368
    PregnancyPartnerTargetSim = 68719476736
    SocialGroupAnchor = 137438953472

class ParticipantTypeAnimation(enum.IntFlags):
    __qualname__ = 'ParticipantTypeAnimation'
    Invalid = ParticipantType.Invalid
    Actor = ParticipantType.Actor
    TargetSim = ParticipantType.TargetSim
    Listeners = ParticipantType.Listeners
    AllSims = ParticipantType.AllSims

class ParticipantTypeSingle(enum.IntFlags):
    __qualname__ = 'ParticipantTypeSingle'
    Actor = ParticipantType.Actor
    TargetSim = ParticipantType.TargetSim
    StoredSim = ParticipantType.StoredSim
    StoredSimOnActor = ParticipantType.StoredSimOnActor
    SignificantOtherActor = ParticipantType.SignificantOtherActor
    SignificantOtherTargetSim = ParticipantType.SignificantOtherTargetSim
    PregnancyPartnerActor = ParticipantType.PregnancyPartnerActor
    PregnancyPartnerTargetSim = ParticipantType.PregnancyPartnerTargetSim
    Object = ParticipantType.Object
    SocialGroupAnchor = ParticipantType.SocialGroupAnchor

class ParticipantTypeReactionlet(enum.IntFlags):
    __qualname__ = 'ParticipantTypeReactionlet'
    Invalid = ParticipantType.Invalid
    TargetSim = ParticipantType.TargetSim
    Listeners = ParticipantType.Listeners

class ParticipantTypeActorTargetSim(enum.IntFlags):
    __qualname__ = 'ParticipantTypeActorTargetSim'
    Actor = ParticipantType.Actor
    TargetSim = ParticipantType.TargetSim

class ParticipantTypeResponse(enum.IntFlags):
    __qualname__ = 'ParticipantTypeResponse'
    Invalid = ParticipantType.Invalid
    Actor = ParticipantType.Actor
    TargetSim = ParticipantType.TargetSim
    Listeners = ParticipantType.Listeners
    AllSims = ParticipantType.AllSims

class ParticipantTypeResponsePaired(enum.IntFlags):
    __qualname__ = 'ParticipantTypeResponsePaired'
    TargetSim = ParticipantType.TargetSim

class ParticipantTypeObject(enum.IntFlags):
    __qualname__ = 'ParticipantTypeObject'
    ActorSurface = ParticipantType.ActorSurface
    CarriedObject = ParticipantType.CarriedObject
    CraftingObject = ParticipantType.CraftingObject
    Object = ParticipantType.Object
    PickedObject = ParticipantType.PickedObject
    SocialGroupAnchor = ParticipantType.SocialGroupAnchor

class MixerInteractionGroup(DynamicEnum):
    __qualname__ = 'MixerInteractionGroup'
    DEFAULT = 0

enum.warn_about_overlapping_enum_values(ParticipantType, postures.posture_specs.PostureSpecVariable, AnimationParticipant)
