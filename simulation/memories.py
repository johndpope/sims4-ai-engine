from buffs.memory import MemoryUid
from distributor.shared_messages import add_message_if_selectable
from element_utils import build_critical_section_with_finally
from protocolbuffers import Sims_pb2
from protocolbuffers.Consts_pb2 import MSG_SIM_MEMORY_TRIGGER_UPDATE
from sims4.tuning.tunable import TunableFactory, Tunable, TunableEnumEntry


class TunableMemoryTrigger(TunableFactory):
    __qualname__ = 'TunableMemoryTrigger'

    @staticmethod
    def factory(interaction, timeout=10, memory_uid=0, sequence=()):
        def trigger_memory_on(interaction):
            sim = interaction.sim
            send_memory_trigger_update(sim=sim,
                                       trigger_memory=True,
                                       timeout_time=timeout,
                                       memory_uid=memory_uid)

        def trigger_memory_off(interaction):
            sim = interaction.sim
            send_memory_trigger_update(sim=sim,
                                       trigger_memory=False,
                                       timeout_time=0,
                                       memory_uid=memory_uid)

        sequence = build_critical_section_with_finally(
            lambda _: trigger_memory_on(interaction), sequence,
            lambda _: trigger_memory_off(interaction))
        return sequence

    FACTORY_TYPE = factory

    def __init__(
            self,
            description='Trigger a memory as part of this interaction, and disable it when the interaction finishes.',
            **kwargs):
        super(
        ).__init__(timeout=Tunable(
            int,
            10,
            description=
            'Timeout (in seconds) for memory notification. Set high if interaction is long. The notification will be disabled when the interaction ends, even if timeout has not been reached.'),
                   memory_uid=TunableEnumEntry(
                       MemoryUid,
                       default=MemoryUid.Invalid,
                       description=
                       'The Type of Memory. Defined in buff.memory tuning'),
                   description=description,
                   **kwargs)


def send_memory_trigger_update(sim,
                               trigger_memory=False,
                               timeout_time=0.0,
                               memory_uid=0):
    memory_msg = Sims_pb2.MemoryTriggerUpdate()
    memory_msg.sim_id = sim.id if sim is not None else 0
    memory_msg.trigger_memory = trigger_memory
    memory_msg.timeout = timeout_time
    memory_msg.memory_id = memory_uid
    add_message_if_selectable(sim, MSG_SIM_MEMORY_TRIGGER_UPDATE, memory_msg,
                              False)
