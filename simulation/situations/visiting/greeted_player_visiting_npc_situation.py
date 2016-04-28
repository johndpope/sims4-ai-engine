from animation.posture_manifest_constants import STAND_CONSTRAINT
from interactions.context import InteractionContext
from interactions.utils.satisfy_constraint_interaction import ForceSatisfyConstraintSuperInteraction
from objects.components.line_of_sight_component import TunableLineOfSightFactory
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import Tunable
from sims4.tuning.tunable_base import GroupNames
from sims4.utils import classproperty
from situations.base_situation import _RequestUserData
from situations.bouncer.bouncer_request import BouncerPlayerVisitingNPCRequestFactory
from situations.situation_types import SituationCreationUIOption, GreetedStatus
from situations.visiting.visiting_situation_common import VisitingNPCSituation
import interactions
import role
import sims4.tuning.tunable
import situations.bouncer.bouncer_types
import situations.situation_complex

class GreetedPlayerVisitingNPCSituation(VisitingNPCSituation):
    __qualname__ = 'GreetedPlayerVisitingNPCSituation'
    INSTANCE_TUNABLES = {'greeted_player_sims': sims4.tuning.tunable.TunableTuple(situation_job=situations.situation_job.SituationJob.TunableReference(description='\n                    The job given to player sims in the visiting situation.\n                    '), role_state=role.role_state.RoleState.TunableReference(description='\n                    The role state given to player sims in the visiting situation.\n                    '), tuning_group=GroupNames.ROLES), '_line_of_sight_factory': TunableLineOfSightFactory(description='\n                Tuning to generate a light of sight constraint in front of the\n                sim who rang the doorbell in order to make the sims in this\n                situation move into the house.\n                '), '_line_of_sight_generation_distance': Tunable(description='\n                The distance in front of the sim that rang the doorbell that we\n                generate the line of sight constraint.\n                ', tunable_type=float, default=2.0)}

    @staticmethod
    def _states():
        return [(1, GreetedPlayerVisitingNPCState)]

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.greeted_player_sims.situation_job, cls.greeted_player_sims.role_state)]

    @classproperty
    def default_job(cls):
        return cls.greeted_player_sims.situation_job

    def start_situation(self):
        super().start_situation()
        self._change_state(GreetedPlayerVisitingNPCState())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._line_of_sight = None
        if self._seed.custom_init_params_reader is None and self.initiating_sim_info is not None:
            sim = self.initiating_sim_info.get_sim_instance()
            self._line_of_sight = self._line_of_sight_factory()
            position = sim.position
            position += sim.forward*self._line_of_sight_generation_distance
            self._line_of_sight.generate(position, sim.routing_surface)

    def _issue_requests(self):
        request = BouncerPlayerVisitingNPCRequestFactory(self, callback_data=_RequestUserData(role_state_type=self.greeted_player_sims.role_state), job_type=self.greeted_player_sims.situation_job, exclusivity=self.exclusivity)
        self.manager.bouncer.submit_request(request)

    def _on_add_sim_to_situation(self, sim, job_type, role_state_type_override=None):
        super()._on_add_sim_to_situation(sim, job_type, role_state_type_override=role_state_type_override)
        if self._line_of_sight is not None:
            context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, interactions.priority.Priority.High)
            constraint_to_satisfy = STAND_CONSTRAINT.intersect(self._line_of_sight.constraint)
            sim.push_super_affordance(ForceSatisfyConstraintSuperInteraction, None, context, constraint_to_satisfy=constraint_to_satisfy, name_override='MoveInsideHouseFromGreetedSituation')

lock_instance_tunables(GreetedPlayerVisitingNPCSituation, exclusivity=situations.bouncer.bouncer_types.BouncerExclusivityCategory.VISIT, creation_ui_option=SituationCreationUIOption.NOT_AVAILABLE, duration=0, _implies_greeted_status=True)

class GreetedPlayerVisitingNPCState(situations.situation_complex.SituationState):
    __qualname__ = 'GreetedPlayerVisitingNPCState'

