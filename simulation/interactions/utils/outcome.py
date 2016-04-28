import random
from element_utils import CleanupType
from element_utils import build_element, must_run
from event_testing.test_events import TestEvent
from event_testing.resolver import DoubleSimResolver
from interactions import ParticipantType, ParticipantTypeResponse, ParticipantTypeResponsePaired
from interactions.context import InteractionContext, InteractionBucketType
from interactions.interaction_finisher import FinishingType
from interactions.utils import LootType
from interactions.utils.animation import InteractionAsmType, flush_all_animations
from interactions.utils.animation_reference import TunableAnimationReference
from interactions.utils.loot import LootActions, LootOperationList, create_loot_list
from interactions.utils.outcome_enums import OutcomeResult
from interactions.utils.success_chance import SuccessChance
from interactions.utils.tunable import TunableContinuation
from objects.components.autonomy import TunableParameterizedAutonomy
from sims4.localization import TunableLocalizedString, TunableLocalizedStringFactory, LocalizationHelperTuning
from sims4.tuning.tunable import TunableFactory, TunableMapping, TunableEnumFlags, TunableList, TunableVariant, TunableTuple, Tunable, TunableSingletonFactory, OptionalTunable, TunableEnumEntry
from singletons import DEFAULT
from tunable_multiplier import TunableMultiplier
from ui.ui_dialog_notification import UiDialogNotification
import animation.arb
import element_utils
import elements
import enum
import event_testing
import services
import sims.sim_log
import sims4.log
logger = sims4.log.Logger('Interactions')

class DebugOutcomeStyle(enum.Int, export=False):
    __qualname__ = 'DebugOutcomeStyle'
    NONE = 0
    AUTO_SUCCEED = 1
    AUTO_FAIL = 2
    ROTATE = 3

with sims4.reload.protected(globals()):
    debug_outcome_style = DebugOutcomeStyle.NONE
    previous_debug_outcome = None

def _debug_outcome_result():
    global previous_debug_outcome
    if debug_outcome_style == DebugOutcomeStyle.AUTO_SUCCEED:
        previous_debug_outcome = OutcomeResult.SUCCESS
    elif debug_outcome_style == DebugOutcomeStyle.AUTO_FAIL:
        previous_debug_outcome = OutcomeResult.FAILURE
    elif debug_outcome_style == DebugOutcomeStyle.ROTATE:
        if previous_debug_outcome != OutcomeResult.SUCCESS:
            previous_debug_outcome = OutcomeResult.SUCCESS
        else:
            previous_debug_outcome = OutcomeResult.FAILURE
    return previous_debug_outcome

def _is_debug_outcome_style_cheat_active():
    if debug_outcome_style != DebugOutcomeStyle.NONE and debug_outcome_style is not False:
        return True
    return False

def build_outcome_actions(interaction, actions, setup_asm_override=DEFAULT):
    push_interaction = None
    if actions.continuation:

        def push_continuation(_):
            return interaction.push_tunable_continuation(actions.continuation)

        push_interaction = push_continuation
    parameterized_autonomy_gen = None
    if not interaction.user_canceled:

        def parameterized_autonomy_gen(timeline):
            for (participant_type, requests) in actions.parameterized_autonomy.items():
                yield interaction.super_interaction._parameterized_autonomy_helper_gen(timeline, requests, InteractionContext.SOURCE_AUTONOMY, InteractionBucketType.DEFAULT, participant_type=participant_type)

    loot = None
    if actions.loot_list is not None:
        loot_list = list(actions.loot_list)
    else:
        loot_list = []
    if actions.add_target_affordance_loot and interaction.target is not None:
        loot_list.extend(interaction.target.get_affordance_loot_list(interaction))
        if actions.consume_object:
            local_consumable_component = interaction.target.consumable_component
            if local_consumable_component is not None:
                loot_list.extend(local_consumable_component.loot_list)
    if loot_list is not None:
        loot = create_loot_list(interaction, loot_list)
    has_loot_been_awarded = False

    def on_loot(_):
        nonlocal has_loot_been_awarded
        if not has_loot_been_awarded:
            has_loot_been_awarded = True
            if loot is not None:
                loot.apply_operations()

    end_animation = None
    if actions.response is not None:

        def setup_asm_end_animation(asm):
            asm.set_parameter('Intensity', interaction.intensity.name)

        end_animation = actions.response(interaction, setup_asm_override=setup_asm_override, setup_asm_additional=setup_asm_end_animation)
    if actions.xevt is not None:
        interaction.animation_context.register_event_handler(on_loot, handler_id=actions.xevt)
    start_animation = None
    if actions.animation_ref is not None:
        start_animation = actions.animation_ref(interaction, setup_asm_override=setup_asm_override)
    social_animation = None
    if actions.social_animation is not None:
        social_group = interaction.social_group
        if social_group is not None:
            social_animation = social_group.get_social_animation_element(actions.social_animation(interaction, setup_asm_override=setup_asm_override))

    def send_events(_):
        for event_type in actions.events_to_send:
            services.get_event_manager().process_event(event_type, interaction=interaction)

    cancel_si_element = None
    if actions.cancel_si:

        def perform_cancel_si(_):
            interaction.cancel_parent_si_for_participant(actions.cancel_si, FinishingType.NATURAL, cancel_reason_msg='Canceled by cancel_si tuning in a child mixer interaction.')

        cancel_si_element = perform_cancel_si

    def allow_outcome():
        if actions.force_outcome_on_exit:
            return True
        if interaction.allow_outcomes:
            return True
        return False

    sequence = build_element((start_animation, social_animation, end_animation, flush_all_animations, on_loot, push_interaction, send_events, cancel_si_element, parameterized_autonomy_gen), CleanupType.RunAll)
    sequence = build_basic_extra_outcomes(interaction, actions.basic_extras, sequence)
    if actions.animation_ref is not None:
        listeners = list(interaction.get_participants(ParticipantType.Listeners, listener_filtering_enabled=True))
        sequence = interaction.with_listeners(listeners, sequence)
    return elements.ConditionalElement(allow_outcome, sequence, build_element(flush_all_animations))

def build_basic_extra_outcomes(interaction, basic_extras, sequence=()):
    for factory in reversed(basic_extras):
        sequence = factory(interaction, sequence=sequence)
    return build_element(sequence)

class InteractionOutcome:
    __qualname__ = 'InteractionOutcome'

    @staticmethod
    def tuning_loaded_callback(affordance, field_name, source, outcome):
        if hasattr(affordance, 'register_simoleon_delta_callback'):
            affordance.register_simoleon_delta_callback(outcome.get_simoleon_delta)

    def __init__(self):
        self.interaction_cls_name = None

    @property
    def consumes_object(self):
        return False

    def build_elements(self, interaction):

        def _do(timeline):
            if interaction.outcome_result is None:
                self.decide(interaction)
            yield element_utils.run_child(timeline, must_run(self._build_elements(interaction)))

        return (_do,)

    def _build_elements(self, interaction):
        return flush_all_animations

    def decide(self, interaction):
        interaction.outcome_result = OutcomeResult.NONE
        if sims.sim_log.outcome_archiver.enabled:
            sims.sim_log.log_interaction_outcome(interaction, 'Base Interaction Outcome')

    def _get_loot_gen(self):
        pass

    def get_basic_extras_gen(self):
        pass

    def get_reactionlet(self, interaction, **kwargs):
        if interaction.outcome_result is None:
            self.decide(interaction)
        reactionlet = self._get_reactionlet(interaction)
        if reactionlet is not None:
            reactionlet = reactionlet(interaction, use_asm_cache=False, enable_auto_exit=False, **kwargs)
            if reactionlet is None:
                logger.error('Reactionlet in outcome {} has invalid selector', self)
            return reactionlet

    def _get_reactionlet(self, interaction):
        pass

    def _get_response(self, interaction):
        pass

    @property
    def associated_skill(self):
        pass

    def _get_associated_skill(self, actions):
        for loot in self._get_loot_gen():
            if loot is None:
                logger.warn('[Tuning] {} has empty item in Outcome/Actions/Loot List', self.interaction_cls_name)
            for (loot_op, _) in loot.get_loot_ops_gen():
                if loot_op is None:
                    logger.warn('[Tuning] {} has empty item in Outcome/Actions/Loot List/{}', self.interaction_cls_name, loot)
                while loot_op.loot_type == LootType.SKILL:
                    stat = loot_op.stat
                    if stat.is_skill:
                        return stat

    def get_simoleon_delta(self, interaction, target=DEFAULT, context=DEFAULT):
        max_value = 0
        for loot_list in self._get_loot_gen():
            value = 0
            for actions in loot_list:
                while actions is not None:
                    value += actions.get_simoleon_delta(interaction, target, context)
            while abs(value) > abs(max_value):
                max_value = value
        return max_value

    @property
    def has_content(self):
        return True

class InteractionOutcomeNone(InteractionOutcome):
    __qualname__ = 'InteractionOutcomeNone'

    @property
    def has_content(self):
        return False

class TunableOutcomeNone(TunableSingletonFactory):
    __qualname__ = 'TunableOutcomeNone'
    FACTORY_TYPE = InteractionOutcomeNone

class InteractionOutcomeSingle(InteractionOutcome):
    __qualname__ = 'InteractionOutcomeSingle'

    def __init__(self, actions, **kwargs):
        super().__init__()
        self._actions = actions

    @property
    def consumes_object(self):
        return self._actions.consume_object

    def _build_elements(self, interaction):
        return build_outcome_actions(interaction, self._actions)

    def decide(self, interaction):
        interaction.outcome_result = self._actions.outcome_result
        interaction.outcome_display_message = self._actions.display_message
        if sims.sim_log.outcome_archiver.enabled:
            sims.sim_log.log_interaction_outcome(interaction, 'Single Outcome')

    def _get_loot_gen(self):
        aggregate_loot_list = list(self._actions.loot_list)
        yield aggregate_loot_list

    def get_basic_extras_gen(self):
        yield self._actions.basic_extras

    def _get_reactionlet(self, interaction):
        if self._actions.animation_ref is not None:
            return self._actions.animation_ref(interaction).reactionlet

    def _get_response(self, interaction):
        return self._actions.response

    @property
    def associated_skill(self):
        return self._get_associated_skill(self._actions)

class TunableOutcomeSingle(TunableSingletonFactory):
    __qualname__ = 'TunableOutcomeSingle'
    FACTORY_TYPE = InteractionOutcomeSingle

    def __init__(self, allow_multi_si_cancel=None, allow_social_animation=None, locked_args=None, animation_callback=DEFAULT, **kwargs):
        super().__init__(description='There is a single, guaranteed outcome for this interaction.', actions=TunableOutcomeActions(allow_multi_si_cancel=allow_multi_si_cancel, allow_social_animation=allow_social_animation, locked_args=locked_args, animation_callback=animation_callback), callback=InteractionOutcome.tuning_loaded_callback, **kwargs)

class InteractionOutcomeDual(InteractionOutcome):
    __qualname__ = 'InteractionOutcomeDual'

    def __init__(self, success_chance, success_actions, failure_actions, **kwargs):
        super().__init__()
        self._success_chance = success_chance
        self._success_actions = success_actions
        self._failure_actions = failure_actions

    @property
    def consumes_object(self):
        return self._success_actions.consume_object or self._failure_actions.consume_object

    def _build_elements(self, interaction):
        if interaction.outcome_result == OutcomeResult.SUCCESS:
            return build_outcome_actions(interaction, self._success_actions)
        return build_outcome_actions(interaction, self._failure_actions)

    def _get_success_chance(self, interaction):
        chance = self._success_chance.get_chance(interaction.get_resolver())
        sim = interaction.sim
        chance += sim.get_actor_success_modifier(interaction.affordance)
        chance += sim.get_success_chance_modifier()
        chance *= interaction.get_skill_multiplier(interaction.success_chance_multipliers, sim)
        return sims4.math.clamp(0, chance, 1)

    def decide(self, interaction):
        if debug_outcome_style != DebugOutcomeStyle.NONE and debug_outcome_style is not False:
            interaction.outcome_result = _debug_outcome_result()
            if interaction.outcome_result == OutcomeResult.SUCCESS:
                interaction.outcome_display_message = self._success_actions.display_message
            else:
                interaction.outcome_display_message = self._failure_actions.display_message
            return
        rand_roll = random.random()
        success_chance = self._get_success_chance(interaction)
        if rand_roll <= success_chance:
            interaction.outcome_result = OutcomeResult.SUCCESS
            interaction.outcome_display_message = self._success_actions.display_message
        else:
            interaction.outcome_result = OutcomeResult.FAILURE
            interaction.outcome_display_message = self._failure_actions.display_message
        if sims.sim_log.outcome_archiver.enabled:
            sims.sim_log.log_interaction_outcome(interaction, 'Dual Outcome', success_chance=success_chance)

    def _get_loot_gen(self):
        aggregate_loot_list = list(self._success_actions.loot_list)
        aggregate_loot_list.extend(self._failure_actions.loot_list)
        yield aggregate_loot_list

    def get_basic_extras_gen(self):
        yield self._success_actions.basic_extras
        yield self._failure_actions.basic_extras

    def _get_reactionlet(self, interaction):
        if interaction.outcome_result == OutcomeResult.SUCCESS:
            if self._success_actions.animation_ref is not None:
                return self._success_actions.animation_ref(interaction).reactionlet
        elif self._failure_actions.animation_ref is not None:
            return self._failure_actions.animation_ref(interaction).reactionlet

    def _get_response(self, interaction):
        if interaction.outcome_result == OutcomeResult.SUCCESS:
            return self._success_actions.response
        return self._failure_actions.response

    @property
    def associated_skill(self):
        skill_stat_type = self._get_associated_skill(self._success_actions)
        if skill_stat_type is None:
            skill_stat_type = self._get_associated_skill(self._failure_actions)
        return skill_stat_type

class TunableOutcomeDual(TunableSingletonFactory):
    __qualname__ = 'TunableOutcomeDual'
    FACTORY_TYPE = InteractionOutcomeDual

    def __init__(self, allow_multi_si_cancel=None, allow_social_animation=None, locked_args=None, animation_callback=DEFAULT, **kwargs):
        super().__init__(description='\n                            There are one success and one failure outcome for\n                            this interaction.\n                            ', success_chance=SuccessChance.TunableFactory(description='\n                            The success chance of the interaction. This\n                            determines which dual outcome is run.\n                            '), success_actions=TunableOutcomeActions(allow_multi_si_cancel=allow_multi_si_cancel, allow_social_animation=allow_social_animation, locked_args=locked_args, animation_callback=animation_callback), failure_actions=TunableOutcomeActions(allow_multi_si_cancel=allow_multi_si_cancel, allow_social_animation=allow_social_animation, locked_args=locked_args, animation_callback=animation_callback), callback=InteractionOutcome.tuning_loaded_callback, **kwargs)

class InteractionOutcomeTestBased(InteractionOutcome):
    __qualname__ = 'InteractionOutcomeTestBased'

    def __init__(self, tested_outcomes, fallback_outcomes, use_fallback_as_default, **kwargs):
        super().__init__()
        self._tested_outcomes = tested_outcomes
        self._fallback_outcomes = fallback_outcomes
        self._use_fallback_as_default = use_fallback_as_default
        self._selected_outcome = None

    @property
    def consumes_object(self):
        for outcome_tuple in self._tested_outcomes:
            for potential_outcome in outcome_tuple.potential_outcomes:
                while potential_outcome.outcome.consume_object:
                    return True
        for fallback_outcome in self._fallback_outcomes:
            while fallback_outcome.outcome.consume_object:
                return True
        return False

    def _build_elements(self, interaction):
        if self._selected_outcome is None:
            return super()._build_elements(interaction)
        return build_outcome_actions(interaction, self._selected_outcome)

    @staticmethod
    def cheat_outcome_style_test(curr_debug_style, outcome):
        if curr_debug_style == outcome.outcome_result:
            return True
        return False

    def decide(self, interaction):
        weights = []
        resolver = interaction.get_resolver()
        curr_debug_style = _debug_outcome_result()
        cheat_active = _is_debug_outcome_style_cheat_active()
        for outcome_tuple in self._tested_outcomes:
            while cheat_active or outcome_tuple.tests.run_tests(resolver):
                while True:
                    for outcome in outcome_tuple.potential_outcomes:
                        if cheat_active and not self.cheat_outcome_style_test(curr_debug_style, outcome.outcome):
                            pass
                        while interaction.allow_outcomes or outcome.outcome.force_outcome_on_exit:
                            weight = outcome.weight.get_multiplier(interaction.get_resolver())
                            weights.append((weight, outcome.outcome))
        if self._use_fallback_as_default or not weights or cheat_active:
            for outcome in self._fallback_outcomes:
                if cheat_active and not self.cheat_outcome_style_test(curr_debug_style, outcome.outcome):
                    pass
                weight = outcome.weight.get_multiplier(interaction.get_resolver())
                weights.append((weight, outcome.outcome))
        if weights:
            self._selected_outcome = sims4.random.weighted_random_item(weights)
            interaction.outcome_result = self._selected_outcome.outcome_result
        else:
            logger.warn('Tried creating a test based outcome but none of the tests passed and the default_outcomes either did not pass or were not tuned. This will now be treated as a None Outcome- trevorlindsey')
            self._selected_outcome = None

    def _get_loot_gen(self):
        if self._selected_outcome is None:
            return super()._get_loot_gen()
        for outcome_tuple in self._tested_outcomes:
            for outcome_weight_pair in outcome_tuple.potential_outcomes:
                yield outcome_weight_pair.outcome.loot_list
        for outcome_weight_pair in self._fallback_outcomes:
            yield outcome_weight_pair.outcome.loot_list

    def get_basic_extras_gen(self):
        for outcome_tuple in self._tested_outcomes:
            for outcome_weight_pair in outcome_tuple.potential_outcomes:
                yield outcome_weight_pair.outcome.basic_extras
        for outcome_weight_pair in self._fallback_outcomes:
            yield outcome_weight_pair.outcome.basic_extras

    def _get_reactionlet(self, interaction):
        if self._selected_outcome is None:
            return super()._get_reactionlet(interaction)
        if self._selected_outcome.animation_ref is not None:
            return self._selected_outcome.animation_ref(interaction).reactionlet

    def _get_response(self, interaction):
        if self._selected_outcome is None:
            return super()._get_response(interaction)
        return self._selected_outcome.response

    @property
    def associated_skill(self):
        if self._selected_outcome is None:
            return super().associated_skill()
        return self._get_associated_skill(self._selected_outcome)

class TunableOutcomeTestBased(TunableSingletonFactory):
    __qualname__ = 'TunableOutcomeTestBased'
    FACTORY_TYPE = InteractionOutcomeTestBased
    WEIGHT_DESCRIPTION = '\n        After all tests have run, the passing outcomes are randomized based on their weights.\n        Outcomes with higher weights have a higher chance of being selected while outcomes\n        with lower weights have a lower chance of being selected. Each weight\n        has a list of multipliers associated with it. Tune the base value\n        as the weight that will be applied if all of the tests fail. Otherwise\n        if all of the tests associated with a multiplier pass the base value \n        will be multiplied by that multiplier.\n        '

    def __init__(self, allow_multi_si_cancel=None, allow_social_animation=None, locked_args=None, **kwargs):
        super().__init__(description='\n            Based on the tests and the weights of the outcomes, a\n            single outcome will be selected.\n            ', tested_outcomes=TunableList(TunableTuple(description='\n                If all of the tests pass, the outcomes will be randomly selected\n                based on the provided weight.\n                ', tests=event_testing.tests.TunableTestSet(), potential_outcomes=TunableList(TunableTuple(description='\n                    List of weight/outcome pairs.\n                    ', outcome=TunableOutcomeActions(allow_multi_si_cancel=allow_multi_si_cancel, allow_social_animation=allow_social_animation, locked_args=locked_args), weight=TunableMultiplier.TunableFactory(description='\n                    A tunable list of tests and multipliers to apply to the \n                    weight of the outcome.\n                    '))))), fallback_outcomes=TunableList(TunableTuple(description='\n                These outcomes will only be considered if none of the Tested Outcomes pass their tests.\n                If Use Fallback As Default is checked, these outcomes will be considered along with any TestedOutcomes that passed.\n                ', outcome=TunableOutcomeActions(allow_multi_si_cancel=allow_multi_si_cancel, allow_social_animation=allow_social_animation, locked_args=locked_args), weight=TunableMultiplier.TunableFactory(description='\n                    A tunable list of tests and multipliers to apply to the \n                    weight of the outcome.\n                    '))), use_fallback_as_default=Tunable(description='\n                If enabled, the Fallback Outcomes list will always be considered along with any Tested Outcomes that pass their tests.\n                If disabled, the Fallback Outcomes list will only be used as a fallback if none of the Tested Outcomes pass their tests.\n                ', tunable_type=bool, default=False))

class InteractionOutcomePartial(InteractionOutcome):
    __qualname__ = 'InteractionOutcomePartial'

    def __init__(self, default_actions, total_failure, single_success_string, partial_success_string, all_success_string, single_failure_string, all_failure_string, notification, test_and_results, **kwargs):
        super().__init__()
        self._actions = None
        self._default_actions = default_actions
        self._total_failure = total_failure
        self._single_success_string = single_success_string
        self._partial_success_string = partial_success_string
        self._all_success_string = all_success_string
        self._single_failure_string = single_failure_string
        self._all_failure_string = all_failure_string
        self._notification = notification
        self._test_and_results = test_and_results

    @property
    def consumes_object(self):
        if self._actions is not None:
            return self._actions.consume_object
        return self._default_actions.consume_object or self._total_failure is not None and self._total_failure.consume_object

    def _build_elements(self, interaction):
        if self._actions is not None:
            return build_outcome_actions(interaction, self._actions)
        return build_outcome_actions(interaction, self._default_actions)

    def _get_error_and_string(self, interaction, sim):
        resolver = interaction.get_resolver(picked_item_ids=(sim.id,))
        for test_string_pair in self._test_and_results:
            while test_string_pair.test.run_tests(resolver):
                return (False, test_string_pair.result_string(sim))
        return (True, True)

    def _send_notification(self, text, sim):
        notification = self._notification(sim, text=lambda *_, **__: text)
        notification.show_dialog()

    def decide(self, interaction):
        self._actions = self._default_actions
        picked_sims = interaction.get_participants(ParticipantType.PickedSim)
        if picked_sims:
            valid_sim_ids = set()
            picked_sim_count = len(picked_sims)
            actor = interaction.sim
            if picked_sim_count == 1:
                sim = next(iter(picked_sims))
                (return_val, error_string) = self._get_error_and_string(interaction, sim)
                if not return_val:
                    if sims.sim_log.outcome_archiver.enabled:
                        sims.sim_log.log_interaction_outcome(interaction, 'partial Outcome: single fail')
                    if self._single_failure_string:
                        text = self._single_failure_string(error_string)
                        self._send_notification(text, actor)
                        if sims.sim_log.outcome_archiver.enabled:
                            sims.sim_log.log_interaction_outcome(interaction, 'partial Outcome: single success')
                        valid_sim_ids.add(sim.id)
                        if self._single_success_string:
                            text = self._single_success_string(actor, sim)
                            self._send_notification(text, actor)
                else:
                    if sims.sim_log.outcome_archiver.enabled:
                        sims.sim_log.log_interaction_outcome(interaction, 'partial Outcome: single success')
                    valid_sim_ids.add(sim.id)
                    if self._single_success_string:
                        text = self._single_success_string(actor, sim)
                        self._send_notification(text, actor)
            else:
                bullet_points = []
                for sim in picked_sims:
                    (return_val, error_string) = self._get_error_and_string(interaction, sim)
                    if not return_val:
                        bullet_points.append(error_string)
                    else:
                        valid_sim_ids.add(sim.id)
                valid_sim_count = len(valid_sim_ids)
                if valid_sim_count == picked_sim_count:
                    if sims.sim_log.outcome_archiver.enabled:
                        sims.sim_log.log_interaction_outcome(interaction, 'partial Outcome: multiple total success')
                    if self._all_success_string:
                        text = interaction.create_localized_string(self._all_success_string)
                        self._send_notification(text, actor)
                else:
                    bullet_text = LocalizationHelperTuning.get_bulleted_list(None, *bullet_points)
                    if valid_sim_count == 0:
                        if sims.sim_log.outcome_archiver.enabled:
                            sims.sim_log.log_interaction_outcome(interaction, 'partial Outcome: multiple total failure')
                        if self._all_failure_string:
                            text = self._all_failure_string(bullet_text)
                            self._send_notification(text, actor)
                    else:
                        if sims.sim_log.outcome_archiver.enabled:
                            sims.sim_log.log_interaction_outcome(interaction, 'partial Outcome: partial success')
                        if self._partial_success_string:
                            text = self._partial_success_string(bullet_text)
                            self._send_notification(text, actor)
            interaction.interaction_parameters['picked_item_ids'] = valid_sim_ids
            if not valid_sim_ids:
                if self._total_failure is not None:
                    self._actions = self._total_failure
        elif sims.sim_log.outcome_archiver.enabled:
            sims.sim_log.log_interaction_outcome(interaction, 'partial Outcome: No picked sims')
        interaction.outcome_result = self._actions.outcome_result
        interaction.outcome_display_message = self._actions.display_message

    def _get_loot_gen(self):
        if self._actions is not None:
            aggregate_loot_list = list(self._actions.loot_list)
        else:
            aggregate_loot_list = list(self._default_actions.loot_list)
            if self._total_failure is not None:
                aggregate_loot_list.extend(self._total_failure.loot_list)
        yield aggregate_loot_list

    def get_basic_extras_gen(self):
        if self._actions is not None:
            yield self._actions.basic_extras
        if self._default_actions is not None:
            yield self._default_actions.basic_extras

    def _get_reactionlet(self, interaction):
        if self._actions is not None:
            if self._actions.animation_ref is not None:
                return self._actions.animation_ref(interaction).reactionlet
        elif self._default_actions.animation_ref is not None:
            return self._default_actions.animation_ref(interaction).reactionlet

    def _get_response(self, interaction):
        if self._actions is not None:
            return self._actions.response
        return self._default_actions.response

    @property
    def associated_skill(self):
        if self._actions is not None:
            return self._get_associated_skill(self._actions)
        skill_stat_type = self._get_associated_skill(self._default_actions)
        if skill_stat_type is None and self._total_failure is not None:
            skill_stat_type = self._get_associated_skill(self._total_failure)
        return skill_stat_type

class TunableOutcomePartial(TunableSingletonFactory):
    __qualname__ = 'TunableOutcomePartial'
    FACTORY_TYPE = InteractionOutcomePartial

    def __init__(self, allow_multi_si_cancel=None, allow_social_animation=None, locked_args=None, animation_callback=DEFAULT, **kwargs):
        super().__init__(description='filters the list of picked sims based on tests and sends a notification about failures', default_actions=TunableOutcomeActions(allow_multi_si_cancel=allow_multi_si_cancel, allow_social_animation=allow_social_animation, locked_args=locked_args, animation_callback=animation_callback), total_failure=OptionalTunable(description='\n                            If specified, then if all picked sims fail to pass\n                            these actions will replace the default\n                            ', tunable=TunableOutcomeActions(allow_multi_si_cancel=allow_multi_si_cancel, allow_social_animation=allow_social_animation, locked_args=locked_args, animation_callback=animation_callback)), callback=InteractionOutcome.tuning_loaded_callback, single_success_string=TunableLocalizedStringFactory(description='\n                             The text of the notification that is displayed when the only sim\n                             in the list of picked sims passes.  Arg 0 is actor, 1 is picked sim\n                             '), partial_success_string=TunableLocalizedStringFactory(description='\n                             The text of the notification that is displayed when at least 1 sim,\n                             but not all the sims, fail to pass. arg0 is a bulleted list of individual\n                             failure strings\n                             '), all_success_string=TunableLocalizedStringFactory(description='\n                             The text of the notification that is displayed when there are\n                             multiple sims and they all pass.  No args.\n                             '), single_failure_string=TunableLocalizedStringFactory(description='\n                             The text of the notification that is displayed when there is only\n                             1 sim, and it fails to pass. arg 0 is a non bulleted list of the individual\n                             failure string.\n                             '), all_failure_string=TunableLocalizedStringFactory(description='\n                             The text of the notification that is displayed when all the sims\n                             fail to pass. arg 0 is bulleted list of individual failure strings\n                             '), notification=UiDialogNotification.TunableFactory(description='\n                             The notification that is displayed.\n                             ', locked_args={'text': None}), test_and_results=TunableList(description='\n                             A list of tests and string returned if sim passes the test.\n                             ', tunable=TunableTuple(test=event_testing.tests.TunableTestSet(description='\n                                     A set of tests that are run against the prospective sims. At least\n                                     one test must pass in order for the sim to be removed from the list\n                                     and the error message displayed.\n                                     All sims will pass if there are no tests.\n                                     Picked_sim is the participant type for the prospective sim.\n                                     '), result_string=TunableLocalizedStringFactory(description='\n                                     The text that is displayed for a sim that passes a test\n                                     arg 0 is the sim\n                                     '))), **kwargs)

class TunableResponseSelector(TunableVariant):
    __qualname__ = 'TunableResponseSelector'

    class TunableResponsePaired(TunableFactory):
        __qualname__ = 'TunableResponseSelector.TunableResponsePaired'

        @staticmethod
        def _create_response(interaction, animation, **kwargs):
            return animation(interaction, use_asm_cache=False, **kwargs)

        FACTORY_TYPE = _create_response

        def __init__(self, description='A response that plays on both Sims.', **kwargs):
            super().__init__(animation=TunableAnimationReference(interaction_asm_type=InteractionAsmType.Response, participant_enum_override=(ParticipantTypeResponsePaired, ParticipantTypeResponsePaired.TargetSim), description='The response animation to play.'), description=description, **kwargs)

    class TunableResponseIndividual(TunableFactory):
        __qualname__ = 'TunableResponseSelector.TunableResponseIndividual'

        @staticmethod
        def _on_tunable_loaded_callback(cls, fields, source, *, animations):
            for (participant_type, animation_element) in animations.items():
                add_auto_constraints = TunableAnimationReference.get_default_callback(InteractionAsmType.Response)
                add_auto_constraints(cls, fields, source, actor_participant_type=participant_type, target_participant_type=None, factory=animation_element.factory, overrides=animation_element.overrides)

        @staticmethod
        def _create_response(interaction, *, animations, setup_asm_override=DEFAULT, **kwargs):
            participant_types = set(animations)
            sims = set()
            for participant_type in participant_types:
                sims.update(interaction.get_participants(participant_type))
            actor_in_sims = interaction.sim in sims
            sims.discard(interaction.sim)
            sims_ordered = [sim for sim in sims]
            if actor_in_sims:
                sims_ordered.insert(0, interaction.sim)

            def generate_setup_asm(sim, actor_name):

                def setup_asm(asm):
                    return sim.posture.setup_asm_interaction(asm, sim, None, actor_name, None)

                return setup_asm

            def do_responses(_):
                arb_accumulator = services.current_zone().arb_accumulator_service
                with arb_accumulator.parallelize():
                    for sim in sims_ordered:
                        best_participant_type = interaction.get_participant_type(sim, restrict_to_participant_types=participant_types)
                        response_animation = animations.get(best_participant_type)
                        if response_animation is None:
                            pass
                        if sim is not interaction.sim or setup_asm_override is DEFAULT:
                            setup_asm = generate_setup_asm(sim, response_animation.factory.actor_name)
                        else:
                            setup_asm = setup_asm_override
                        arb = animation.arb.Arb()
                        response = response_animation(interaction, setup_asm_override=setup_asm, use_asm_cache=False, **kwargs)
                        response_asm = response.get_asm()
                        response.append_to_arb(response_asm, arb)
                        posture_idle = sim.posture.idle_animation(sim.posture.source_interaction)
                        posture_asm = posture_idle.get_asm()
                        posture_idle.append_to_arb(posture_asm, arb)
                        arb_accumulator.add_arb(arb)

            work = do_responses
            if work and not actor_in_sims:
                work = (flush_all_animations, work)
            return work

        FACTORY_TYPE = _create_response

        def __init__(self, description='A response that plays distinct animations on Actor and TargetSim.', **kwargs):
            super().__init__(callback=self._on_tunable_loaded_callback, animations=TunableMapping(key_type=TunableEnumEntry(ParticipantTypeResponse, ParticipantType.Actor), key_name='target', value_type=TunableAnimationReference(callback=None, interaction_asm_type=InteractionAsmType.Response, participant_enum_override=(ParticipantTypeResponse, ParticipantTypeResponse.Invalid)), value_name='animation', description='A mapping of participants to the animation they should play. If a Sim is found more than onceit will only have the first animation played on it. Tuning this field will override animation_actorand animation_target.'), description=description, **kwargs)

    def __init__(self, description='\n        Responses are short, one-shot animations \n        that we play after the conclusion of interactions. They are usually \n        meant to convey how the Sims felt about how the interaction went and \n        are thus almost always related to emotions.\n        These can be configured to play on a specific participant or can be \n        paired between actor and target.\n        ', participant_enum_override=DEFAULT, **kwargs):
        super().__init__(paired=self.TunableResponsePaired(), individual=self.TunableResponseIndividual(), description=description, **kwargs)

class TunableOutcomeActions(TunableTuple):
    __qualname__ = 'TunableOutcomeActions'
    ADD_TARGET_AFFORDANCE_LOOT_KEY = 'add_target_affordance_loot'

    def __init__(self, animation_callback=DEFAULT, allow_multi_si_cancel=False, allow_social_animation=False, locked_args=None, **kwargs):
        import interactions.base.basic
        animation_ref = TunableAnimationReference(callback=animation_callback, interaction_asm_type=InteractionAsmType.Outcome, description='The one-shot animation ref to play')
        animation_ref = OptionalTunable(animation_ref)
        if allow_multi_si_cancel:
            cancel_si = OptionalTunable(TunableEnumFlags(description='\n                                                                     Every participant in this list will have the SI\n                                                                     associated with the interaction owning this outcome\n                                                                     canceled.\n                                                                     ', enum_type=ParticipantType))
        else:
            cancel_si = TunableVariant(description="\n                                        When enabled, the outcome will cancel the owning\n                                        interaction's parent SI.\n                                        ", locked_args={'enabled': ParticipantType.Actor, 'disabled': None}, default='disabled')
        if allow_social_animation:
            kwargs['social_animation'] = OptionalTunable(description='\n                If enabled, specify an animation that will be played once for\n                the entire social group.\n                ', tunable=TunableAnimationReference())
        else:
            locked_args = {} if locked_args is None else locked_args
            locked_args['social_animation'] = None
        if locked_args is None:
            locked_args = {TunableOutcomeActions.ADD_TARGET_AFFORDANCE_LOOT_KEY: True}
        elif TunableOutcomeActions.ADD_TARGET_AFFORDANCE_LOOT_KEY not in locked_args:
            locked_args.update({TunableOutcomeActions.ADD_TARGET_AFFORDANCE_LOOT_KEY: True})
        super().__init__(animation_ref=animation_ref, xevt=OptionalTunable(description='\n                             When specified, the outcome will be associated to this xevent.\n                             ', tunable=Tunable(tunable_type=int, default=None)), response=OptionalTunable(TunableResponseSelector()), force_outcome_on_exit=Tunable(description='\n                             If checked outcome will always be given even if\n                             interaction was canceled. If unchecked, outcome\n                             will only be given if mixer, one_shot, or\n                             naturally finishing interaction.\n                             ', tunable_type=bool, default=False), loot_list=TunableList(description='\n                             A list of pre-defined loot operations.\n                             ', tunable=LootActions.TunableReference()), consume_object=Tunable(description="\n                             If checked, the loot list generated in the target\n                             object's consumable component will be added to\n                             this outcome's loot list.\n                             ", tunable_type=bool, default=False), continuation=TunableContinuation(description='An affordance to be pushed as part of an outcome.'), cancel_si=cancel_si, events_to_send=TunableList(TunableEnumEntry(TestEvent, TestEvent.Invalid, description='events types to send')), display_message=OptionalTunable(description='\n                             If set, flyaway text will be shown.\n                             ', tunable=TunableLocalizedString(default=None, description='Localized string that is shown as flyaway text')), loot_offset_override=OptionalTunable(Tunable(int, 0), description="An override to interactions.utils.loot's DEFAULT_LOOT_OFFSET tuning, specifically for this outcome."), parameterized_autonomy=TunableMapping(description='\n                             Specify parameterized autonomy for the participants of the interaction.\n                             ', key_type=TunableEnumEntry(description='\n                                 The participant to run parameterized autonomy for.\n                                 ', tunable_type=ParticipantType, default=ParticipantType.Actor), value_type=TunableList(description='\n                                 A list of parameterized autonomy requests to run.\n                                 ', tunable=TunableParameterizedAutonomy())), outcome_result=TunableEnumEntry(description='\n                             The interaction outcome result to consider this interaction result. This is\n                             important for testing interactions, such as an aspiration that wants to know\n                             if a Sim has successfully kissed another Sim. All interactions that a designer\n                             would consider a success case for such a scenario would be assured here.\n                             ', tunable_type=OutcomeResult, default=OutcomeResult.SUCCESS), basic_extras=interactions.base.basic.TunableBasicExtrasCore(), locked_args=locked_args, **kwargs)

TUNABLE_OUTCOME_DESCRIPTION = '\n    An outcome defines a series of actions or effects that run and are applied\n    when an interaction completes.\n    '

class TunableOutcome(TunableVariant):
    __qualname__ = 'TunableOutcome'

    def __init__(self, description=TUNABLE_OUTCOME_DESCRIPTION, default='none', allow_none=True, allow_single=True, allow_dual=True, allow_test_based=True, allow_multi_si_cancel=None, allow_social_animation=None, outcome_locked_args=None, animation_callback=DEFAULT, allow_partial=True, **kwargs):
        outcome_kwargs = {}
        if outcome_locked_args is not None:
            outcome_kwargs['locked_args'] = outcome_locked_args
        if allow_multi_si_cancel is not None:
            outcome_kwargs['allow_multi_si_cancel'] = allow_multi_si_cancel
        if allow_social_animation is not None:
            outcome_kwargs['allow_social_animation'] = allow_social_animation
        if allow_none:
            kwargs['none'] = TunableOutcomeNone()
        if allow_single:
            kwargs['single'] = TunableOutcomeSingle(animation_callback=animation_callback, **outcome_kwargs)
        if allow_dual:
            kwargs['dual'] = TunableOutcomeDual(animation_callback=animation_callback, **outcome_kwargs)
        if allow_test_based:
            kwargs['test_based'] = TunableOutcomeTestBased(**outcome_kwargs)
        if allow_partial:
            kwargs['partial'] = TunableOutcomePartial(**outcome_kwargs)
        super().__init__(description='\n                            This is how we play different content depending on \n                            some in-game decision.\n                            Outcome animations can be used following basic \n                            content, but keep in mind that you will be using \n                            the same ASM instance if your element uses the same \n                            ASM as the basic content and thus it will be played \n                            at the last state used by that content.\n                            These should always be one-shot! We do not have \n                            duration control on outcomes. \n                            ', default=default, **kwargs)

