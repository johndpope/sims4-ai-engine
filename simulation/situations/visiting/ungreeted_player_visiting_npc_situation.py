from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable_base import GroupNames
from sims4.utils import classproperty
from situations.base_situation import _RequestUserData
from situations.bouncer.bouncer_request import BouncerPlayerVisitingNPCRequestFactory
from situations.situation_types import SituationCreationUIOption, GreetedStatus
from situations.visiting.visiting_situation_common import VisitingNPCSituation
import distributor.ops
import distributor.system
import role
import services
import sims4.tuning.tunable
import situations.bouncer.bouncer_types
import situations.situation_complex

class UngreetedPlayerVisitingNPCSituation(VisitingNPCSituation):
    __qualname__ = 'UngreetedPlayerVisitingNPCSituation'
    INSTANCE_TUNABLES = {'ungreeted_player_sims': sims4.tuning.tunable.TunableTuple(situation_job=situations.situation_job.SituationJob.TunableReference(description='\n                    The job given to player sims in the ungreeted situation.\n                    '), role_state=role.role_state.RoleState.TunableReference(description='\n                    The role state given to player sims in the ungreeted situation.\n                    '), tuning_group=GroupNames.ROLES)}

    @classmethod
    def _get_greeted_status(cls):
        return situations.situation_types.GreetedStatus.WAITING_TO_BE_GREETED

    @staticmethod
    def _states():
        return [(1, UngreetedPlayerVisitingNPCState)]

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.ungreeted_player_sims.situation_job, cls.ungreeted_player_sims.role_state)]

    @classproperty
    def default_job(cls):
        return cls.ungreeted_player_sims.situation_job

    @classproperty
    def distribution_override(cls):
        return True

    def start_situation(self):
        super().start_situation()
        self._change_state(UngreetedPlayerVisitingNPCState())

    def _issue_requests(self):
        request = BouncerPlayerVisitingNPCRequestFactory(self, callback_data=_RequestUserData(role_state_type=self.ungreeted_player_sims.role_state), job_type=self.ungreeted_player_sims.situation_job, exclusivity=self.exclusivity)
        self.manager.bouncer.submit_request(request)

    def _on_sim_removed_from_situation_prematurely(self, sim):
        if self.num_of_sims > 0:
            return
        if not self.manager.is_player_greeted():
            return
        self._self_destruct()

    def get_create_op(self, *args, **kwargs):
        return distributor.ops.SetWallsUpOrDown(True)

    def get_delete_op(self):
        return distributor.ops.SetWallsUpOrDown(False)

lock_instance_tunables(UngreetedPlayerVisitingNPCSituation, exclusivity=situations.bouncer.bouncer_types.BouncerExclusivityCategory.UNGREETED, creation_ui_option=SituationCreationUIOption.NOT_AVAILABLE, duration=0)

class UngreetedPlayerVisitingNPCState(situations.situation_complex.SituationState):
    __qualname__ = 'UngreetedPlayerVisitingNPCState'

