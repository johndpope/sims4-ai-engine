from event_testing.test_events import TestEvent
from event_testing.tests_with_data import TunableParticipantRanInteractionTest
from sims4.tuning.tunable import OptionalTunable, TunableVariant, TunableSimMinute
from sims4.utils import classproperty
from situations.bouncer.bouncer_types import RequestSpawningOption
from situations.situation import Situation
from situations.situation_complex import SituationComplexCommon, TunableSituationJobAndRoleState, SituationState
from situations.situation_guest_list import SituationGuestList, SituationGuestInfo
import services
import sims4.tuning
import situations.bouncer

class WorkerNpcSituation(SituationComplexCommon):
    __qualname__ = 'WorkerNpcSituation'
    INSTANCE_TUNABLES = {'_worker_npc_job': TunableSituationJobAndRoleState(description='\n            The job and corresponding role state for the worker NPC.\n            '), '_end_work_test': TunableParticipantRanInteractionTest(description='\n            When the worker NPC runs this interaction, the situation will end.\n            ', locked_args={'running_time': None, 'tooltip': None}), '_visit_duration': OptionalTunable(description='\n            If enabled, then the worker NPC will enter a visit situation for the\n            specified duration.\n            ', tunable=TunableVariant(description="\n                The duration of the worker NPC's visit situation.\n                ", specific_duration=TunableSimMinute(default=60), locked_args={'default_duration': None, 'forever': 0}, default='default_duration'), disabled_value=False)}
    REMOVE_INSTANCE_TUNABLES = Situation.NON_USER_FACING_REMOVE_INSTANCE_TUNABLES

    @staticmethod
    def _states():
        return ((1, WorkingSituationState),)

    @classproperty
    def is_unique_situation(cls):
        return True

    @classmethod
    def default_job(cls):
        return cls._worker_npc_job.job

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return ((cls._worker_npc_job.job, cls._worker_npc_job.role_state),)

    @classmethod
    def get_predefined_guest_list(cls):
        guest_list = SituationGuestList(True)
        worker_filter = cls.default_job().filter
        sim_infos = services.sim_filter_service().submit_filter(worker_filter, None, allow_yielding=False)
        if sim_infos:
            guest_list.add_guest_info(SituationGuestInfo(sim_infos[0].sim_info.sim_id, cls.default_job(), RequestSpawningOption.DONT_CARE, None))
        else:
            guest_list.add_guest_info(SituationGuestInfo(0, cls.default_job(), RequestSpawningOption.DONT_CARE, None))
        return guest_list

    def start_situation(self):
        super().start_situation()
        self._change_state(WorkingSituationState())

    def on_ask_sim_to_leave(self, sim):
        return False

    def _create_next_situation(self):
        worker_sim = next(self.all_sims_in_job_gen(self.default_job()), None)
        if worker_sim is not None:
            if worker_sim.is_on_active_lot() and self._visit_duration != False:
                services.get_zone_situation_manager().create_visit_situation(worker_sim, duration_override=self._visit_duration)
                return
            services.get_zone_situation_manager().make_sim_leave(worker_sim)

    def _end_situation(self):
        self._create_next_situation()
        self._self_destruct()

sims4.tuning.instances.lock_instance_tunables(WorkerNpcSituation, exclusivity=situations.bouncer.bouncer_types.BouncerExclusivityCategory.WORKER, creation_ui_option=situations.situation_types.SituationCreationUIOption.NOT_AVAILABLE)

class WorkingSituationState(SituationState):
    __qualname__ = 'WorkingSituationState'

    def on_activate(self, *args, **kwargs):
        self._test_event_register(TestEvent.InteractionComplete)
        return super().on_activate(*args, **kwargs)

    def handle_event(self, sim_info, event, resolver):
        if self.owner.test_interaction_complete_by_job_holder(sim_info, resolver, self.owner.default_job(), self.owner._end_work_test):
            self.owner._end_situation()

