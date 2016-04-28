from weakref import WeakKeyDictionary
from animation.posture_manifest_constants import SIT_NO_CARRY_NO_SURFACE_CONSTRAINT, SIT_INTIMATE_CONSTRAINT
from event_testing.results import TestResult, ExecuteResult, EnqueueResult
from interactions import ParticipantType
from sims.sim_log import log_interaction
from sims4.math import MAX_UINT16
from singletons import DEFAULT
from uid import UniqueIdGenerator
import caches
import elements
import interactions.constraints
import services
import sims4.commands
import sims4.log
import telemetry_helper
logger = sims4.log.Logger('AOP')

class AffordanceObjectPair:
    __qualname__ = 'AffordanceObjectPair'
    get_next_aop_id = UniqueIdGenerator(0, MAX_UINT16)

    def __init__(self, affordance, target, sa, si, liabilities=None, skip_safe_tests=False, skip_test_on_execute=False, **kwargs):
        self.affordance = affordance
        self.super_affordance = sa
        self.aop_id = self.get_next_aop_id()
        self._constraint_cache = WeakKeyDictionary()
        self.super_interaction = si
        self.target = target
        self.content_score = None
        self.autonomy_selection_time = 0
        self.lifetime_in_steps = 1
        self._liabilities = liabilities
        self.skip_safe_tests = skip_safe_tests
        self.skip_test_on_execute = skip_test_on_execute
        self.show_posture_incompatible_icon = False
        self._kwargs = kwargs

    def is_equivalent_to(self, other):
        return type(self) == type(other) and (self.affordance == other.affordance and (self.super_affordance == other.super_affordance and (self.super_interaction == other.super_interaction and (self.target == other.target and self.interaction_parameters == other.interaction_parameters))))

    def do_affordance_and_target_match(self, other_affordance, other_target):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return self.affordance == other_affordance and self.target == other_target

    @property
    def target(self):
        if self._target:
            return self._target()

    @target.setter
    def target(self, target):
        self._target = target.ref() if target is not None else None

    def constraint_intersection(self, sim=DEFAULT, target=DEFAULT, posture_state=DEFAULT, participant_type=ParticipantType.Actor, include_super_affordance_constraint=False, **kwargs):
        if sim in self._constraint_cache:
            return self._constraint_cache[sim]
        constraint = self.affordance.constraint_intersection(sim=sim, target=self.target, posture_state=posture_state, participant_type=participant_type, **kwargs)
        if include_super_affordance_constraint:
            si_constraint = self.super_affordance.constraint_intersection(sim=sim, target=self.target, posture_state=posture_state, participant_type=participant_type, **kwargs)
            constraint = constraint.intersect(si_constraint)
        self._constraint_cache[sim] = constraint
        return constraint

    @property
    def interaction_parameters(self):
        return self._kwargs

    def test(self, context, skip_safe_tests=DEFAULT, **kwargs) -> TestResult:
        if not (self.super_interaction is not None and self.super_interaction.can_run_subinteraction(self, context=context)):
            return TestResult(False, 'SuperInteraction is finishing.')
        combined_kwargs = dict(self._kwargs)
        combined_kwargs.update(kwargs)
        if skip_safe_tests is DEFAULT:
            skip_safe_tests = self.skip_safe_tests
        return self.affordance.test(target=self.target, context=context, liabilities=self._liabilities, super_interaction=self.super_interaction, skip_safe_tests=skip_safe_tests, **combined_kwargs)

    def can_make_test_pass(self, context, **kwargs) -> TestResult:
        combined_kwargs = dict(self._kwargs)
        combined_kwargs.update(kwargs)
        return self.affordance.can_make_test_pass(self.target, context, liabilities=self._liabilities, super_interaction=self.super_interaction, **combined_kwargs)

    def make_test_pass(self, context, **kwargs) -> TestResult:
        combined_kwargs = dict(self._kwargs)
        combined_kwargs.update(kwargs)
        return self.affordance.make_test_pass(self.target, context, liabilities=self._liabilities, super_interaction=self.super_interaction, **combined_kwargs)

    @staticmethod
    def execute_interaction(interaction) -> ExecuteResult:
        if interaction:
            if interaction.affordance.cheat:
                with telemetry_helper.begin_hook(sims4.commands.cheats_writer, sims4.commands.TELEMETRY_HOOK_INTERACTION) as hook:
                    hook.write_string(sims4.commands.TELEMETRY_FIELD_NAME, interaction.__str__())
                    hook.write_string(sims4.commands.TELEMETRY_FIELD_TARGET, str(interaction.target))
            if interaction.affordance.immediate:
                interaction._trigger_interaction_start_event()
                immediate_timeline = services.time_service().sim_timeline.get_sub_timeline()
                result_element = elements.ResultElement(elements.GeneratorElement(interaction._run_gen))
                immediate_timeline.schedule(result_element)
                immediate_timeline.simulate(immediate_timeline.now)
                if immediate_timeline.heap:
                    logger.error('On immediate execute_interaction, immediate timeline is not empty')
                    immediate_timeline.heap.clear()
                run_result = result_element.result
                interaction._trigger_interaction_complete_test_event()
                if run_result:
                    exit_behavior = interaction._exit(None, False)
                    try:
                        next(exit_behavior)
                        logger.error('Running immediate exit_behavior yielded despite allow_yield=False')
                    except StopIteration:
                        pass
                execute_result = ExecuteResult(run_result, interaction, None)
                log_interaction('Immediate', interaction, '{}'.format(execute_result))
                return execute_result
            context = interaction.context
            return ExecuteResult(context.sim.queue.append(interaction), interaction, None)
        return ExecuteResult(False, None, 'Trying to execute a None interaction.')

    def execute(self, context) -> ExecuteResult:
        result = self.interaction_factory(context)
        if not result:
            return result
        return self.execute_interaction(result.interaction)

    def test_and_execute(self, context, **kwargs) -> EnqueueResult:
        test_result = self.test(context, **kwargs)
        execute_result = None
        if test_result:
            execute_result = self.execute(context)
        return EnqueueResult(test_result, execute_result)

    def is_equivalent_to_interaction(self, interaction):
        return interaction.is_equivalent(self.affordance, target=self.target)

    def is_linked_to(self, super_affordance):
        return self.super_affordance.is_linked_to(super_affordance)

    def interaction_factory(self, context) -> ExecuteResult:
        si = self.super_interaction
        if si is not None and not si.can_run_subinteraction(self, context):
            return ExecuteResult(False, None, 'SuperInteraction cannot run SubInteraction.')
        try:
            interaction = self.affordance(self, context, liabilities=self._liabilities, **self._kwargs)
        except Exception as exc:
            from interactions.base.interaction import logger
            logger.exception('{}: Error instantiating affordance:', self)
            return ExecuteResult(False, None, 'Error instantiating affordance: {}'.format(exc))
        if si is not None:
            interaction.super_interaction = si
        if context.continuation_id is not None:
            services.get_master_controller().reset_timestamp_for_sim(context.sim)
        return ExecuteResult(True, interaction, None)

    def name(self, context):
        return self.affordance.get_name(self.target, context)

    def __repr__(self):
        return '<AffordanceInstance; %s on %s>' % (self.affordance, self.target)

    def __str__(self):
        if self.affordance is not None:
            affordance_name = self.affordance.__name__
        else:
            affordance_name = 'None'
        return '%s on %s' % (affordance_name, self.target)

    def register_availability_listeners(self, target, context, callback):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        listener_handles = []
        for influence in self.affordance.influences_gen():
            handle = influence.listen_for_change(target, context, callback)
            while handle is not None:
                listener_handles.append(handle)
        return listener_handles

    def get_provided_posture_change(self):
        return self.affordance.get_provided_posture_change(self)

    @property
    def basic_content(self):
        return self.affordance.basic_content

    @property
    def provided_posture_type(self):
        return self.affordance.provided_posture_type

    def compatible_with_current_posture_state(self, sim):
        sim_constraint = self.constraint_intersection(sim=sim, posture_state=None, include_super_affordance_constraint=True)
        sim_posture_state_constraint = sim.posture_state.posture_constraint
        if self.affordance.is_social and self.target is not None and self.target.is_sim:
            target_sim = self.target
            target_sim_constraint = self.constraint_intersection(sim=target_sim, posture_state=None, participant_type=ParticipantType.TargetSim, include_super_affordance_constraint=True)
            listener_constraint = self.constraint_intersection(sim=target_sim, posture_state=None, participant_type=ParticipantType.Listeners, include_super_affordance_constraint=True)
            target_constraint = target_sim_constraint.intersect(listener_constraint)
            target_posture_state_constraint = target_sim.posture_state.posture_constraint
            if not sim.posture.mobile:
                import socials.group
                sim_social_constraint = socials.group.create_social_circle_constraint_around_sim(sim)
                if not sim_social_constraint.geometry.contains_point(target_sim.position) or not sim.can_see(target_sim):
                    return False
            if sim_constraint.intersect(SIT_INTIMATE_CONSTRAINT).valid and (self.target is not None and (self.target.is_sim and (sim.posture.target is not None and (self.target.posture.target is not None and (sim.posture.target.is_part and (target_sim.posture.target.is_part and (sim.posture.target in list(target_sim.posture.target.adjacent_parts_gen()) and sim_posture_state_constraint.intersect(SIT_NO_CARRY_NO_SURFACE_CONSTRAINT).valid))))))) and target_posture_state_constraint.intersect(SIT_NO_CARRY_NO_SURFACE_CONSTRAINT).valid:
                return True
            if sim_constraint.intersect(SIT_NO_CARRY_NO_SURFACE_CONSTRAINT).valid and (self.target is not None and (self.target.is_sim and sim_posture_state_constraint.intersect(SIT_INTIMATE_CONSTRAINT).valid)) and target_posture_state_constraint.intersect(SIT_INTIMATE_CONSTRAINT).valid:
                return True
        if not sim.posture.mobile:
            sim_transform_constraint = interactions.constraints.Transform(sim.intended_transform, routing_surface=sim.intended_routing_surface)
            sim_constraint = sim_constraint.intersect(sim_transform_constraint)
            if not sim_constraint.valid:
                return False
        sim_intersection = sim_constraint.intersect(sim_posture_state_constraint)
        if not sim_intersection.valid:
            return False
        if not target_sim.posture.mobile:
            target_sim_transform_constraint = interactions.constraints.Transform(target_sim.intended_transform, routing_surface=sim.intended_routing_surface)
            target_constraint = target_constraint.intersect(target_sim_transform_constraint)
            if not target_constraint.valid:
                return False
        target_intersection = target_constraint.intersect(target_posture_state_constraint)
        if not (self.affordance.is_social and (self.target is not None and self.target.is_sim) and target_intersection.valid):
            return False
        return True

