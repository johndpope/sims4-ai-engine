from event_testing.results import TestResult
from interactions import ParticipantType
from interactions.base.immediate_interaction import ImmediateSuperInteraction
from sims.sim_spawner import SimSpawner
from sims4.tuning.instances import lock_instance_tunables
from sims4.utils import flexmethod
from singletons import DEFAULT
import distributor
import services

class SimInfoInteraction(ImmediateSuperInteraction):
    __qualname__ = 'SimInfoInteraction'
    INSTANCE_SUBCLASSES_ONLY = True

    def __init__(self, *args, sim_info=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._sim_info = sim_info

    @flexmethod
    def get_participants(cls, inst, participant_type, sim=DEFAULT, target=DEFAULT, sim_info=None, **interaction_parameters) -> set:
        result = super(ImmediateSuperInteraction, inst if inst is not None else cls).get_participants(participant_type, sim=sim, target=target, **interaction_parameters)
        result = set(result)
        if inst is not None:
            sim_info = inst._sim_info
        if participant_type & ParticipantType.Actor and sim_info is not None:
            result.add(sim_info)
        return tuple(result)

lock_instance_tunables(SimInfoInteraction, simless=True)

class BringHereInteraction(SimInfoInteraction):
    __qualname__ = 'BringHereInteraction'

    @classmethod
    def _test(cls, *args, sim_info=None, **kwargs):
        if sim_info.zone_id == services.current_zone_id():
            return TestResult(False, 'Cannot bring a sim to a zone that is already the current zone.')
        return super()._test(*args, **kwargs)

    def _run_interaction_gen(self, timeline):
        SimSpawner.spawn_sim(self._sim_info)

class SwitchToZoneInteraction(SimInfoInteraction):
    __qualname__ = 'SwitchToZoneInteraction'

    @classmethod
    def _test(cls, *args, sim_info=None, **kwargs):
        if sim_info.zone_id == 0:
            return TestResult(False, 'Cannot travel to a zone of 0.')
        if sim_info.zone_id == services.current_zone_id():
            return TestResult(False, 'Cannot switch to zone that is the current zone.')
        return super()._test(*args, **kwargs)

    def _run_interaction_gen(self, timeline):
        op = distributor.ops.TravelSwitchToZone([self._sim_info.id, self._sim_info.household_id, self._sim_info.zone_id, self._sim_info.world_id])
        distributor.ops.record(self._sim_info, op)
        return True

