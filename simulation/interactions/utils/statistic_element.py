import operator
import weakref
from autonomy.autonomy_modifier import AutonomyModifier
from element_utils import build_critical_section_with_finally, build_element, soft_sleep_forever
from event_testing.test_variants import StatThresholdTest
from interactions import ParticipantType
from sims4.math import Operator, InequalityOperator
from sims4.repr_utils import standard_repr, callable_repr
from sims4.tuning.geometric import TunableCurve
from sims4.tuning.tunable import TunableVariant, TunableReference, TunableList, TunableFactory, TunableTuple, OptionalTunable, TunableSimMinute, TunableRange, Tunable, HasTunableSingletonFactory, AutoFactoryInit, TunableEnumEntry, TunableOperator, TunableEnumFlags, HasTunableFactory
from singletons import DEFAULT
from statistics.commodity import Commodity
from statistics.skill import Skill
from statistics.statistic import Statistic
from statistics.statistic_categories import StatisticCategory
from statistics.statistic_conditions import TunableCondition, TunableTimeRangeCondition, StatisticCondition
from statistics.statistic_ops import TunableStatisticChange, StatisticChangeOp, TunableProgressiveStatisticChange, DynamicSkillLootOp, StatisticOperation, GAIN_TYPE_RATE
import alarms
import clock
import element_utils
import elements
import enum
import event_testing.test_base
import services
import sims4.log
import sims4.resources
import snippets
logger = sims4.log.Logger('Statistics')

class StatisticChangeHelper:
    __qualname__ = 'StatisticChangeHelper'

    def __init__(self, interaction, operations, periodic_statistic_change_element):
        self._interaction = interaction
        self._operations = operations
        self._periodic_statistic_change_element = periodic_statistic_change_element

    def apply(self):
        op_applied = False
        if self._operations:
            resolver = self._interaction.get_resolver()
            for op in tuple(self._operations):
                while op.test_resolver(resolver):
                    autonomy_modifiers = op.apply_to_interaction_statistic_change_element(resolver)
                    if autonomy_modifiers:
                        self._periodic_statistic_change_element.transfer_operation_to_modifier(op, autonomy_modifiers)
                    op_applied = True
        if op_applied:
            self._interaction.send_current_progress(new_interaction=False)
        return True

class PeriodicStatisticChangeElement(HasTunableFactory, elements.SubclassableGeneratorElement):
    __qualname__ = 'PeriodicStatisticChangeElement'
    FACTORY_TUNABLES = {'operations': TunableList(description='\n            A list of statistic operations that occur at each interval.\n            ', tunable=TunableStatisticChange(dynamic_skill=DynamicSkillLootOp.TunableFactory(locked_args={'chance': 1, 'advertise': False}), locked_args={'chance': 1}, gain_type=GAIN_TYPE_RATE)), 'operation_actions': TunableTuple(actions=TunableList(description='\n                A list of actions that occur at each interval\n                ', tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.ACTION), class_restrictions=('LootActions',), reload_dependent=True)), alarm_interval=Tunable(description='\n                Interval in sim minutes that applies operations if operation is\n                not a statistic change operation on a continious statistic and\n                not a skill loot operation.\n                \n                Example: If buff loot is in the operation list and this\n                is set to 5.  Loot op will try to be applied every 5 sim minutes\n                the sim is in the interaction.\n                Another example when this is used:\n                 - Statistic Change Op on statistic_GameForever\n                \n                If there is a statistic in operation is continuous the alarm\n                interval is not used, examples are below.\n                 - Statistic Change Op on motive_hunger\n                 - Dynamic skill on statistic_Skill_AdultMajor_Piano\n                ', tunable_type=int, default=1)), 'trigger_gain_on_start': Tunable(description='\n            If checked then we will trigger a statistic gain when we start the\n            statistic gains.  This is to make sure that things like upgrades\n            will have some statistic progress when the sim is charged for the\n            upgrade instead of loosing the payment.\n            ', tunable_type=bool, default=False)}

    def __init__(self, interaction, operations, operation_actions, trigger_gain_on_start=False, sequence=DEFAULT):
        super().__init__()
        self._interaction = interaction
        self._basic_content_operations = operations
        if operation_actions is not None:
            self._loot_operations = operation_actions.actions
            self._alarm_interval = operation_actions.alarm_interval
        else:
            self._loot_operations = None
            self._alarm_interval = StatisticOperation.STATIC_CHANGE_INTERVAL
        self._alarm_handle = None
        if sequence is DEFAULT:
            sequence = soft_sleep_forever()
        self._sequence = sequence
        self._autonomy_modifiers = weakref.WeakKeyDictionary()
        self._operations_on_alarm = []
        self._change_helper = None
        self._trigger_gain_on_start = trigger_gain_on_start

    def transfer_operation_to_modifier(self, op, autonomy_modifiers):
        self._operations_on_alarm.remove(op)
        for (sim, autonomy_modifier) in autonomy_modifiers.items():
            self._add_autonomy_modifier_to_sim(sim, autonomy_modifier)

    def _add_operation_if_valid(self, resolver, loot_op, periodic_mods_by_participant, exclusive_mods_by_participant, skip_test=False):
        is_dynamic_skill_loot_op = isinstance(loot_op, DynamicSkillLootOp)
        is_exclusive = hasattr(loot_op, 'exclusive_to_owning_si') and loot_op.exclusive_to_owning_si
        stat = loot_op.get_stat(self._interaction)
        if stat is None or not stat.continuous or not is_dynamic_skill_loot_op and not isinstance(loot_op, StatisticChangeOp):
            self._operations_on_alarm.append(loot_op)
            return
        if not skip_test and not loot_op.test_resolver(resolver):
            return
        if is_dynamic_skill_loot_op:
            inv_interval = 1/Skill.DYNAMIC_SKILL_INTERVAL
        else:
            inv_interval = 1
        participants = self._interaction.get_participants(loot_op.subject)
        actor = self._interaction.get_participant(ParticipantType.Actor)
        sims = set()
        sims.add(actor)
        for participant in participants:
            while participant.is_sim:
                sims.add(participant)
        for participant in participants:
            mod_per_sec = loot_op.get_value(obj=participant, interaction=self._interaction, sims=sims)
            mod_per_sec *= inv_interval
            if is_exclusive and participant.is_sim:
                self._add_participant_and_mod_to_dict(participant, stat, mod_per_sec, exclusive_mods_by_participant)
            else:
                self._add_participant_and_mod_to_dict(participant, stat, mod_per_sec, periodic_mods_by_participant)

    def _add_participant_and_mod_to_dict(self, participant, stat, mod_per_sec, mods_by_participant_dict):
        if participant not in mods_by_participant_dict:
            mods_by_participant_dict[participant] = {}
        if stat not in mods_by_participant_dict[participant]:
            mods_by_participant_dict[participant][stat] = 0
        mods_by_participant_dict[participant][stat] += mod_per_sec

    def _start_statistic_gains(self):
        self._end_statistic_gains()
        periodic_mods_by_participant = {}
        exclusive_mods_by_participant = {}
        interaction_resolver = self._interaction.get_resolver()
        if self._basic_content_operations:
            for stat_op in self._basic_content_operations:
                self._add_operation_if_valid(interaction_resolver, stat_op, periodic_mods_by_participant, exclusive_mods_by_participant)
        if self._loot_operations:
            for loot in self._loot_operations:
                for (loot_op, test_ran) in loot.get_loot_ops_gen(resolver=interaction_resolver):
                    self._add_operation_if_valid(interaction_resolver, loot_op, periodic_mods_by_participant, exclusive_mods_by_participant, skip_test=test_ran)
        self._create_and_add_autonomy_modifier(periodic_mods_by_participant)
        si = self._interaction if self._interaction.is_super else self._interaction.super_interaction
        self._create_and_add_autonomy_modifier(exclusive_mods_by_participant, si)
        self._change_helper = StatisticChangeHelper(self._interaction, self._operations_on_alarm, self)
        result = False
        if self._change_helper is not None:
            time_span = clock.interval_in_sim_minutes(self._alarm_interval)
            self._alarm_handle = alarms.add_alarm(self, time_span, self._do_gain, repeating=True)
            if self._trigger_gain_on_start:
                self._apply_all_valid_ops(interaction_resolver)
            result = True
        return result

    def _create_and_add_autonomy_modifier(self, mods_by_participant_dict, exclusive_si=None):
        for (participant, mods) in mods_by_participant_dict.items():
            while hasattr(participant, 'add_statistic_modifier'):
                autonomy_modifier = AutonomyModifier(statistic_modifiers=mods, exclusive_si=exclusive_si)
                self._add_autonomy_modifier_to_sim(participant, autonomy_modifier)

    def _end_statistic_gains(self):
        for (participant, handle_list) in self._autonomy_modifiers.items():
            while participant is not None:
                while True:
                    for handle in handle_list:
                        participant.remove_statistic_modifier(handle)
        if self._alarm_handle is not None:
            alarms.cancel_alarm(self._alarm_handle)
            self._alarm_handle = None
        self._change_helper = None

    def _add_autonomy_modifier_to_sim(self, sim, autonomy_modifier):
        if sim not in self._autonomy_modifiers:
            self._autonomy_modifiers[sim] = []
        handle = sim.add_statistic_modifier(autonomy_modifier)
        self._autonomy_modifiers[sim].append(handle)

    def _apply_all_valid_ops(self, interaction_resolver):
        if self._basic_content_operations:
            for stat_op in self._basic_content_operations:
                stat_op.apply_to_resolver(interaction_resolver)
        if self._loot_operations:
            for loot in self._loot_operations:
                for (loot_op, _) in loot.get_loot_ops_gen(resolver=interaction_resolver):
                    loot_op.apply_to_resolver(interaction_resolver)

    def _do_gain(self, _):
        self._change_helper.apply()

    @property
    def _sim(self):
        return self._interaction.sim

    def _run_gen(self, timeline):
        try:
            self._start_statistic_gains()
            result = yield element_utils.run_child(timeline, self._sequence)
            return result
        finally:
            self._end_statistic_gains()

class ProgressiveStatisticChangeElement(PeriodicStatisticChangeElement):
    __qualname__ = 'ProgressiveStatisticChangeElement'

    def __init__(self, *args, additional_operations, subject, advertise, goal_value, goal_completion_time, goal_exit_condition, **kwargs):
        super().__init__(operations=additional_operations, operation_actions=None, trigger_gain_on_start=False, *args, **kwargs)
        completion_time = goal_completion_time.get_maximum_running_time(self._interaction)
        obj = self._interaction.get_participant(subject)
        stat = obj.get_stat_instance(goal_value.stat, add=True)
        commodity_range = goal_value.get_maximum_change(stat)
        base_increase = commodity_range/completion_time
        new_statistics = []
        for operation_factory in self._basic_content_operations:
            op_amount = getattr(operation_factory, '_amount', None)
            while op_amount is not None:
                percentage = op_amount/commodity_range
                amount = base_increase*percentage
                operation_factory._amount = amount
                new_statistics.append(operation_factory)
        min_value = goal_value.get_goal_value(stat) if base_increase < 0 else None
        max_value = goal_value.get_goal_value(stat) if base_increase > 0 else None
        stat_change = StatisticChangeOp(advertise=advertise, amount=base_increase, min_value=min_value, max_value=max_value, stat=stat.stat_type, subject=subject)
        new_statistics.append(stat_change)
        self._interaction.aditional_instance_ops.append(stat_change)
        self._basic_content_operations = new_statistics

class TunableProgressiveStatisticChangeElement(TunableFactory):
    __qualname__ = 'TunableProgressiveStatisticChangeElement'
    FACTORY_TYPE = ProgressiveStatisticChangeElement

    class FixedTime(HasTunableSingletonFactory, AutoFactoryInit):
        __qualname__ = 'TunableProgressiveStatisticChangeElement.FixedTime'
        FACTORY_TUNABLES = {'completion_time': TunableSimMinute(description='\n                Number of Sim minutes it should take the specified goal\n                commodity to reach the goal value in the worst case, that is, if\n                the stat is as far from the goal value as possible.\n                ', default=None)}

        def get_maximum_running_time(self, interaction):
            return self.completion_time

    class SkillTimeRamp(HasTunableSingletonFactory, AutoFactoryInit):
        __qualname__ = 'TunableProgressiveStatisticChangeElement.SkillTimeRamp'
        FACTORY_TUNABLES = {'skill': Skill.TunableReference(description="\n                The skill that should influence the interaction's running time.\n                "), 'least_skilled_completion_time': Tunable(description='\n                Number of Sim minutes it should take the least-skilled Sim to\n                reach the goal value in the worst case, that is, if the stat is\n                as far from the goal value as possible.\n                ', tunable_type=int, default=None), 'most_skilled_completion_time': Tunable(description='\n                Number of Sim minutes it should take the most-skilled Sim to\n                reach the goal value in the worst case, that is, if the stat is\n                as far from the goal value as possible.\n                ', tunable_type=int, default=None)}

        @property
        def stat(self):
            return self.skill

        def get_maximum_running_time(self, interaction):
            skill_level = interaction.sim.get_effective_skill_level(self.skill)
            quantized_value = self.skill.convert_from_user_value(skill_level)
            p = (self.skill.max_value - quantized_value)/(self.skill.max_value - self.skill.min_value)
            time = sims4.math.interpolate(self.least_skilled_completion_time, self.most_skilled_completion_time, p)
            return time

    class SkillTimeCurve(HasTunableSingletonFactory, AutoFactoryInit):
        __qualname__ = 'TunableProgressiveStatisticChangeElement.SkillTimeCurve'
        FACTORY_TUNABLES = {'skill': Skill.TunableReference(description="\n                The skill that should influence the interaction's running time.\n                "), 'curve': TunableCurve(description="\n                A curve describing the relationship between a Sim's skill level\n                (x-axis) and the interaction's running time (y-axis).  The time\n                is the number of Sim minutes it should take the specified goal\n                commodity to reach the goal value in the worst case, that is, if\n                the stat is as far from the goal value as possible.\n                ")}

        @property
        def stat(self):
            return self.skill

        def get_maximum_running_time(self, interaction):
            skill_level = interaction.sim.get_effective_skill_level(self.skill)
            time = self.curve.get(skill_level)
            return time

    class _GoalValue(HasTunableSingletonFactory, AutoFactoryInit):
        __qualname__ = 'TunableProgressiveStatisticChangeElement._GoalValue'
        FACTORY_TUNABLES = {}

        def get_goal_value(self, stat):
            raise NotImplementedError()

        def get_maximum_change(self, stat):
            current_value = stat.get_value()
            target_value = self.get_goal_value(stat)
            max_to_value = target_value - stat.max_value
            min_to_value = target_value - stat.min_value
            if abs(max_to_value) > abs(min_to_value):
                if current_value >= target_value:
                    return max_to_value
                return -max_to_value
            if current_value < target_value:
                return min_to_value
            return -min_to_value

        def get_exit_condition_factory(self, subject):

            def goal_value_exit_condition(*, interaction, **__):
                obj = interaction.get_participant(subject)
                stat = obj.get_stat_instance(self.stat)
                stat = stat if stat is not None else self.stat
                target_value = self.get_goal_value(stat)
                current_value = stat.get_value()
                if target_value >= current_value:
                    threshold = sims4.math.Threshold(target_value, operator.ge)
                else:
                    threshold = sims4.math.Threshold(target_value, operator.le)
                return StatisticCondition(who=subject, stat=self.stat, threshold=threshold, absolute=True)

            return goal_value_exit_condition

        def get_additional_tests_gen(self, subject):
            pass

    class _StatGoalValue(_GoalValue):
        __qualname__ = 'TunableProgressiveStatisticChangeElement._StatGoalValue'
        FACTORY_TUNABLES = {'stat': TunableReference(description='\n                The commodity this interaction is trying to change.  All\n                generated commodity changes will be based on how long it\n                will take this commodity to get to the goal_value.\n                \n                Used in conjunction with the specified running_time\n                tunable to figure out the rate at which each operation\n                should increase.\n                ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC))}

    class _DirectionalGoalMixin:
        __qualname__ = 'TunableProgressiveStatisticChangeElement._DirectionalGoalMixin'
        FACTORY_TUNABLES = {'limit_direction': OptionalTunable(TunableTuple(description='\n                ', direction=TunableOperator(tunable_type=InequalityOperator, default=Operator.LESS_OR_EQUAL), tooltip=event_testing.test_base.BaseTest.FACTORY_TUNABLES['tooltip']))}

        def get_threshold_value(self, stat):
            return self.get_goal_value()

        def get_additional_tests_gen(self, subject):
            yield super().get_additional_tests_gen(subject)
            if self.limit_direction is not None:
                threshold = sims4.math.Threshold(self.get_threshold_value(), self.limit_direction.direction)
                test = StatThresholdTest(tooltip=self.limit_direction.tooltip, who=subject, stat=self.stat, threshold=threshold)
                yield test

    class MaximumValue(_StatGoalValue):
        __qualname__ = 'TunableProgressiveStatisticChangeElement.MaximumValue'

        def get_goal_value(self, stat):
            return stat.max_value

    class MinimumValue(_StatGoalValue):
        __qualname__ = 'TunableProgressiveStatisticChangeElement.MinimumValue'

        def get_goal_value(self, stat):
            return stat.min_value

    class ConvergenceValue(_StatGoalValue, _DirectionalGoalMixin):
        __qualname__ = 'TunableProgressiveStatisticChangeElement.ConvergenceValue'

        def get_goal_value(self, stat):
            return stat.convergence_value

    class SpecificValue(_StatGoalValue, _DirectionalGoalMixin):
        __qualname__ = 'TunableProgressiveStatisticChangeElement.SpecificValue'
        FACTORY_TUNABLES = {'value': Tunable(int, 0)}

        def get_goal_value(self, stat):
            return self.value

    class SpecificChange(_StatGoalValue):
        __qualname__ = 'TunableProgressiveStatisticChangeElement.SpecificChange'
        FACTORY_TUNABLES = {'delta': Tunable(float, None)}

        def get_goal_value(self, stat):
            current_value = stat.get_value()
            return current_value + self.delta

    class StateValue(_GoalValue, _DirectionalGoalMixin):
        __qualname__ = 'TunableProgressiveStatisticChangeElement.StateValue'
        FACTORY_TUNABLES = {'state_value': TunableReference(manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions=('ObjectStateValue',)), 'state_test': OptionalTunable(disabled_name='allow_any_current_state_value', enabled_name='require_different_current_state_value', tunable=TunableTuple(tooltip=event_testing.test_base.BaseTest.FACTORY_TUNABLES['tooltip']))}

        @property
        def stat(self):
            return self.state_value.state.linked_stat

        def get_goal_value(self, stat):
            if self.limit_direction:
                direction = sims4.math.Operator.from_function(self.limit_direction.direction).category
                if direction is Operator.LESS:
                    return self.state_value.high_value
                if direction is Operator.GREATER:
                    return self.state_value.low_value
            return self.state_value.value

        def get_threshold_value(self, stat):
            return self.state_value.value

        def get_additional_tests_gen(self, subject):
            yield super().get_additional_tests_gen(subject)
            if self.state_test is not None:
                yield event_testing.test_variants.StateTest(tooltip=self.state_test.tooltip, who=subject, operator=operator.ne, value=self.state_value)

    @staticmethod
    def _on_tunable_loaded_callback(affordance, *_, subject, goal_value, goal_exit_condition, **__):
        for test in goal_value.get_additional_tests_gen(subject):
            affordance.add_additional_test(test)
        if goal_exit_condition is None:
            return
        goal_condition = goal_value.get_exit_condition_factory(subject)
        new_conditions = [goal_condition]
        min_time = goal_exit_condition.minimum_running_time
        max_time = goal_exit_condition.maximum_running_time
        if min_time is not None or max_time is not None:

            def time_condition(*_, **__):
                return TunableTimeRangeCondition.factory(min_time, max_time)

            new_conditions.append(time_condition)
        affordance.add_exit_condition(new_conditions)

    def __init__(self, **kwargs):
        super().__init__(additional_operations=TunableList(description='\n                A list of additional statistic operations beyond that created\n                automatically for the goal commodity.  They also represent the\n                change in the worst-case scenario and will apply proportionally.\n                ', tunable=TunableProgressiveStatisticChange()), goal_completion_time=TunableVariant(description='\n                Controls how to determine the number of Sim minutes it should\n                take the specified goal commodity to reach the specified goal\n                value in the worst case.  Assuming goal_exit_condition is\n                enabled, this is also the longest the interaction could possibly\n                take to complete.\n                \n                This will be used to determine the rate at which each operation\n                should increase.\n                ', default='fixed', fixed=self.FixedTime.TunableFactory(), skill_based_curve=self.SkillTimeCurve.TunableFactory(), skill_based_ramp=self.SkillTimeRamp.TunableFactory()), goal_value=TunableVariant(description='\n                The target value for the goal commodity.  All generated\n                commodity changes will be based on how long it will take\n                this commodity to get to this target.\n                \n                Used in conjunction with the specified running_time tunable\n                to figure out the rate at which each operation should\n                increase.\n                ', default='maximum_value', maximum_value=self.MaximumValue.TunableFactory(), minimum_value=self.MinimumValue.TunableFactory(), convergence_value=self.ConvergenceValue.TunableFactory(), specific_value=self.SpecificValue.TunableFactory(), specific_change=self.SpecificChange.TunableFactory(), state_value=self.StateValue.TunableFactory()), subject=TunableEnumEntry(description='\n                The participant of the interaction whose commodity will change.\n                ', tunable_type=ParticipantType, default=ParticipantType.Actor), goal_exit_condition=OptionalTunable(description="\n                If enabled, the interaction will exit when the goal commodity\n                reaches the goal value.\n\n                Additionally, if either minimum/maximum running time is enabled,\n                the interaction will only exit due to reaching goal value if\n                it has run for some minimum amount of time. If only one of the\n                two running times is enabled, the required time is equal to the\n                the enabled option's time. If both are enabled, the minimum\n                time is a randomly generated time between the two options.\n                ", enabled_by_default=True, tunable=TunableTuple(minimum_running_time=OptionalTunable(Tunable(description='\n                        The minimum amount of time this interaction should run\n                        for.\n                        ', tunable_type=int, default=10)), maximum_running_time=OptionalTunable(Tunable(description='\n                        The maximum amount of time this interaction should run\n                        for.\n                        ', tunable_type=int, default=10)))), locked_args={'advertise': False}, callback=self._on_tunable_loaded_callback, **kwargs)

class ConditionalInteractionAction(enum.Int):
    __qualname__ = 'ConditionalInteractionAction'
    NO_ACTION = 0
    GO_INERTIAL = 1
    EXIT_NATURALLY = 2
    EXIT_CANCEL = 3
    LOWER_PRIORITY = 4

class ConditionalActionRestriction(enum.Int):
    __qualname__ = 'ConditionalActionRestriction'
    NO_RESTRICTIONS = 0
    USER_DIRECTED_ONLY = 1
    AUTONOMOUS_ONLY = 2

class ProgressBarAction(enum.Int):
    __qualname__ = 'ProgressBarAction'
    NO_ACTION = 0
    IGNORE_CONDITION = 1
    FORCE_USE_CONDITION = 2

class ExitCondition(HasTunableSingletonFactory):
    __qualname__ = 'ExitCondition'
    FACTORY_TUNABLES = {'conditions': TunableList(description='\n                A list of conditions that all must be satisfied for the group to be considered satisfied.\n                ', tunable=TunableCondition(description='A condition for a single motive.')), 'tests': event_testing.tests.TunableTestSet(description='\n                A set of tests to see if the condition is valid.\n                '), 'restrictions': TunableEnumEntry(description='\n                    By default, this condition applies to all interactions.\n                    This option allows you to limit this condition to only\n                    apply if the interaction was user-directed or autonomously\n                    started.\n                    ', tunable_type=ConditionalActionRestriction, default=ConditionalActionRestriction.NO_RESTRICTIONS), 'interaction_action': TunableEnumEntry(description="\n                    This controls what happens to the interaction when all the\n                    conditions are satisfied. Usages:\n\n                    NO_ACTION: Interaction state does not change.\n                    \n                    GO_INERTIAL: Interaction goes inertial.\n\n                    EXIT_NATURALLY: Interaction exits successfully. Use this\n                    for cases where the Actor is considered to have\n                    successfully completed the interaction. Examples:\n                    - Use Toilet, condition on bladder motive\n                    - Jog for X minutes: condition on time\n                    - Read skill book that stops giving skill at level X,\n                      condition on skill reaching X\n                    \n                    EXIT_CANCEL: Interaction exits as if canceled. Use this if\n                    the Actor did not successfully complete the interaction.\n                    Examples:\n                    - Object breaks.\n                    - Sim motive fails or distresses.\n                    \n                    LOWER_PRIORITY: Only relevant if guaranteed and user-\n                    directed. A guaranteed user-directed interaction with\n                    lowered priority will still behave as if guaranteed except\n                    that other user-directed interactions in queue can cancel\n                    it. This should be used sparingly. A possible use of this:\n                    - A Sim should sleep until his natural wake-up time even\n                      if his energy maxes out sooner. This will help maintain a\n                      consistent sleep schedule, and can be accomplished with\n                      EXIT_NATURALLY conditioned on the wake-up time. But say a\n                      player queues up an interaction after sleep. As it's\n                      awkward for that interaction to sit in queue for hours\n                      after energy has maxed and it's annoying to have to watch\n                      the Sim's motives and manually cancel Sleep, queued user-\n                      directed interactions should trump Sleep after energy is\n                      maxed. This can be accomplished with LOWER_PRIORITY\n                      conditioned on max energy. (Note that while GO_INERTIAL\n                      will also make Sleep cancel when a user-directed\n                      interaction is queued, it also allows autonomy to run and\n                      possibly boot Sleep in favor of something else, which\n                      will ruin the Sim's sleep schedule.)\n                    ", tunable_type=ConditionalInteractionAction, needs_tuning=True, default=ConditionalInteractionAction.GO_INERTIAL), 'loot_actions': TunableList(description='\n                    A list of loot actions that are given when the conditional\n                    action satisfies.\n                    ', tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.ACTION), class_restrictions=('LootActions',))), 'progress_bar_action': TunableEnumEntry(description='\n                    This will tell the progress bar if there is any \n                    special behavior to be done with this exit condition.\n                    Usages:\n                    NO_ACTION: Progress bar will prioritize the exit conditions\n                    as it normally does.\n                    \n                    IGNORE_CONDITION: Progress bar will not consider using\n                    this exit condition in its calculations.\n\n                    FORCE_USE_CONDITION: Progress bar will use this condition\n                    ignoring if its not an exiting exit condition, this will\n                    be used to for special cases where we want to consider\n                    special conditions for tracking the progress (like on \n                    sleeping, even if energy is not an exit condition, we will\n                    use it in the calculation by forcing it with this).\n                    ', tunable_type=ProgressBarAction, needs_tuning=True, default=ProgressBarAction.NO_ACTION)}

    def __init__(self, conditions=[], tests=None, restrictions=ConditionalActionRestriction.NO_RESTRICTIONS, interaction_action=ConditionalInteractionAction.NO_ACTION, loot_actions=None, progress_bar_action=ProgressBarAction.NO_ACTION):
        self.conditions = conditions
        self.tests = tests
        self.restrictions = restrictions
        self.interaction_action = interaction_action
        self.loot_actions = loot_actions
        self.progress_bar_action = progress_bar_action

    def __repr__(self):
        conditions = []
        for condition in self.conditions:
            if callable(condition) and not isinstance(condition, TunableFactory.TunableFactoryWrapper):
                conditions.append(callable_repr(condition))
            else:
                conditions.append(condition)
        kwargs = {}
        if self.tests is not None:
            kwargs['tests'] = self.tests
        kwargs['restrictions'] = self.restrictions
        kwargs['interaction_action'] = self.interaction_action
        kwargs['progress_bar_action'] = self.progress_bar_action
        return standard_repr(self, conditions, **kwargs)

(_, TunableExitConditionSnippet) = snippets.define_snippet('exit_condition', ExitCondition.TunableFactory(), use_list_reference=True)

class TunableStatisticIncrementDecrement(TunableFactory):
    __qualname__ = 'TunableStatisticIncrementDecrement'

    @staticmethod
    def _factory(interaction, stat, subject, amount, sequence=None):
        target = interaction.get_participant(subject)
        if target is not None:
            tracker = target.get_tracker(stat)

            def begin(_):
                tracker.add_value(stat, amount)

            def end(_):
                tracker.add_value(stat, -amount)

            return build_critical_section_with_finally(begin, sequence, end)
        return sequence

    FACTORY_TYPE = _factory

    def __init__(self, **kwargs):
        super().__init__(description='\n            A tunable that increments a specified statistic by a specified\n            amount, runs a sequence, and then decrements the statistic by the\n            same amount.\n            ', stat=TunableReference(description='\n                The statistic to increment and decrement.\n                ', manager=services.statistic_manager(), class_restrictions=(Statistic, Skill)), subject=TunableEnumFlags(description='\n                The participant of the interaction on which the statistic will\n                be incremented and decremented.\n                ', enum_type=ParticipantType, default=ParticipantType.Object), amount=Tunable(description='\n                The amount that will be incremented and decremented from the\n                specified statistic.\n                ', tunable_type=float, default=1), **kwargs)

class TunableStatisticTransferRemove(TunableFactory):
    __qualname__ = 'TunableStatisticTransferRemove'

    @staticmethod
    def _factory(interaction, stat, subject, transfer_stat, transfer_subject, sequence=None):
        target = interaction.get_participant(subject)
        transfer_target = interaction.get_participant(transfer_subject)
        if target is not None and transfer_target is not None:
            tracker = target.get_tracker(stat)
            amount = transfer_target.statistic_tracker.get_value(transfer_stat)

            def begin(_):
                tracker.add_value(stat, amount)

            def end(_):
                tracker.add_value(stat, -amount)

            return build_critical_section_with_finally(begin, sequence, end)
        return sequence

    FACTORY_TYPE = _factory

    def __init__(self, **kwargs):
        super().__init__(description='\n            A tunable that increments a specified statistic by a specified\n            amount, runs a sequence, and then decrements the statistic by the\n            same amount.\n            ', stat=Statistic.TunableReference(description='\n                The statistic to increment and decrement.\n                '), subject=TunableEnumFlags(description='\n                The participant of the interaction on which the statistic will\n                be incremented and decremented.\n                ', enum_type=ParticipantType, default=ParticipantType.Object), transfer_stat=Statistic.TunableReference(description='\n                The statistic whose value to transfer.\n                '), transfer_subject=TunableEnumFlags(description='\n                The participant of the interaction whose statistic value will\n                be transferred.\n                ', enum_type=ParticipantType, default=ParticipantType.Actor), **kwargs)

class StatisticDecayByCategory(elements.ParentElement):
    __qualname__ = 'StatisticDecayByCategory'

    def __init__(self, interaction, subject, categories, rate, sequence=DEFAULT):
        super().__init__()
        self._subject = subject
        self._interaction = interaction
        self._categories = set(categories)
        self._rate = rate
        if sequence is DEFAULT:
            sequence = soft_sleep_forever()
        self._sequence = sequence
        self._affected_commodities = []

    def _start_decay_effects(self):
        for target in self._interaction.get_participants(self._subject):
            if not hasattr(target, 'commodity_tracker'):
                logger.error('Attempting to modify stat decay rate on an object with no commodity tracker.')
            for commodity in target.commodity_tracker.get_all_commodities():
                commodity_categories = set(commodity.get_categories())
                while commodity_categories.intersection(self._categories):
                    commodity.add_decay_rate_modifier(self._rate)
                    self._affected_commodities.append(commodity)
        return True

    def _end_decay_effects(self):
        for commodity in self._affected_commodities:
            commodity.remove_decay_rate_modifier(self._rate)

    def _run(self, timeline):
        return timeline.run_child(build_critical_section_with_finally(lambda _: self._start_decay_effects(), self._sequence, lambda _: self._end_decay_effects()))

class TunableStatisticDecayByCategory(TunableFactory):
    __qualname__ = 'TunableStatisticDecayByCategory'
    FACTORY_TYPE = StatisticDecayByCategory

    def __init__(self, **kwargs):
        super().__init__(subject=TunableEnumFlags(description='\n                The participant of the interaction on which the statistic will\n                be incremented and decremented.\n                ', enum_type=ParticipantType, default=ParticipantType.Actor), rate=TunableRange(description="\n                Units per second to remove of the target's commodities.", tunable_type=float, default=1, minimum=0, maximum=None), categories=TunableList(description='\n                Will reduce all commodities that match any category in this list.', tunable=TunableEnumEntry(StatisticCategory, StatisticCategory.INVALID), needs_tuning=True), **kwargs)

