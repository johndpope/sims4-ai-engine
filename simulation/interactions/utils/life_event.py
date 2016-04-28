from distributor.ops import GenericProtocolBufferOp
from distributor.system import Distributor
from interactions import ParticipantTypeSingle
from element_utils import build_critical_section
from protocolbuffers import Social_pb2
from protocolbuffers.DistributorOps_pb2 import Operation
from sims4.tuning.dynamic_enum import DynamicEnumLocked
from sims4.tuning.tunable import TunableEnumEntry, TunableList, TunableFactory

class LifeEventCategory(DynamicEnumLocked):
    __qualname__ = 'LifeEventCategory'
    INVALID = 0

class TunableLifeEventElement(TunableFactory):
    __qualname__ = 'TunableLifeEventElement'

    @staticmethod
    def _factory(interaction, life_event_category, participants, sequence=None, **kwargs):

        def trigger(_):
            msg = Social_pb2.LifeEventMessage()
            msg.type = life_event_category
            participant_ids = []
            for participant_types in participants:
                participant = interaction.get_participant(participant_types)
                if participant is None:
                    participant_ids.append(0)
                else:
                    participant_ids.append(participant.id)
            msg.sim_ids.extend(participant_ids)
            distributor = Distributor.instance()
            distributor.add_op_with_no_owner(GenericProtocolBufferOp(Operation.LIFE_EVENT_SEND, msg))

        return build_critical_section(sequence, trigger)

    def __init__(self, *args, **kwargs):
        super().__init__(description='Trigger a Life Event', life_event_category=TunableEnumEntry(description='\n                Category of life event', tunable_type=LifeEventCategory, default=LifeEventCategory.INVALID), participants=TunableList(description='\n                    A list of participants that will be sent as part of the event.\n                    Order matters.  (i.e. if the string expects actor then target, order should be actor then target)\n                    ', tunable=TunableEnumEntry(description='\n                        participant to include in life event', tunable_type=ParticipantTypeSingle, default=ParticipantTypeSingle.Actor)), *args, **kwargs)

    FACTORY_TYPE = _factory

