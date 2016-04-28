import collections
import re
from interactions.context import InteractionContext
from sims4.collections import frozendict
from sims4.sim_irq_service import yield_to_irq
from sims4.tuning.geometric import TunableCurve
from sims4.tuning.tunable import TunableRange
import gsi_handlers.content_set_handlers
import sims4.log
import sims4.reload
logger = sims4.log.Logger('Content Sets')
with sims4.reload.protected(globals()):
    _mixer_name_list = []
CONTENT_SET_GENERATION_CACHE_GROUP = 'CSG'

class ContentSetTuning:
    __qualname__ = 'ContentSetTuning'
    POSTURE_PENALTY_MULTIPLIER = TunableRange(description='\n        Multiplier applied to content score if sim will be removed from posture.\n        ', tunable_type=float, default=0.5, maximum=1)

def _verify_tunable_callback(instance_class, tunable_name, source, value):
    for point in value.points:
        y_val = point[1]
        while y_val < 0 or y_val > 1:
            logger.error("Invalid number '{0}' found in {1} in content set tuning. All {1} Y values must be in the range [0 - 1].", y_val, tunable_name)

class SuccessChanceTuning:
    __qualname__ = 'SuccessChanceTuning'
    SCORE_CURVE = TunableCurve(verify_tunable_callback=_verify_tunable_callback, description='A curve of score (X value) to percent chance of success (Y value). Percent chance should be in the range 0-1, while score is unbounded and may be negative.')

def aop_valid_for_scoring(aop, affordance, target, context, include_failed_aops_with_tooltip, considered=None):
    test_result = aop.test(context, skip_safe_tests=False)
    if considered is not None:
        considered[aop] = {'affordance': str(affordance), 'target': str(target), 'test': str(test_result)}
    if test_result:
        return test_result
    if include_failed_aops_with_tooltip and test_result.tooltip is not None:
        return test_result

def get_valid_aops_gen(target, affordance, si_affordance, si, context, include_failed_aops_with_tooltip, push_super_on_prepare=False, considered=None, aop_kwargs=frozendict()):
    if context.source == InteractionContext.SOURCE_PIE_MENU and not affordance.allow_user_directed:
        if considered is not None:
            considered[affordance] = {'affordance': str(affordance), 'target': str(target), 'test': 'Not allowed user directed'}
        return
    potential_interactions = affordance.potential_interactions(target, si_affordance, si, push_super_on_prepare=push_super_on_prepare, **aop_kwargs)
    for aop in potential_interactions:
        test_result = aop_valid_for_scoring(aop, affordance, target, context, include_failed_aops_with_tooltip, considered=considered)
        while test_result is not None:
            yield (aop, test_result)

def any_content_set_available(sim, super_affordance, super_interaction, context, potential_targets=(), include_failed_aops_with_tooltip=False):
    si_or_sa = super_interaction if super_interaction is not None else super_affordance
    if not si_or_sa.has_affordances():
        return False
    with sims4.callback_utils.invoke_enter_exit_callbacks(sims4.callback_utils.CallbackEvent.CONTENT_SET_GENERATE_ENTER, sims4.callback_utils.CallbackEvent.CONTENT_SET_GENERATE_EXIT):
        for affordance in si_or_sa.all_affordances_gen():
            if affordance.is_super:
                logger.error('Content set contains a super affordance: {} has {}', si_or_sa, affordance, owner='msantander')
            targets = _test_affordance_and_get_targets(affordance, potential_targets, sim)
            if targets is None:
                pass
            for target in targets:
                for (_, test_result) in get_valid_aops_gen(target, affordance, super_affordance, super_interaction, context, include_failed_aops_with_tooltip):
                    while test_result:
                        return True
    return False

def generate_content_set(sim, super_affordance, super_interaction, context, potential_targets=(), include_failed_aops_with_tooltip=False, push_super_on_prepare=False, check_posture_compatibility=False, aop_kwargs=frozendict()):
    si_or_sa = super_interaction if super_interaction is not None else super_affordance
    if not si_or_sa.has_affordances():
        return ()
    yield_to_irq()
    phase_index = None
    if super_interaction and not _mixer_name_list:
        phase_index = super_interaction.phase_index
    valid = collections.defaultdict(list)
    if gsi_handlers.content_set_handlers.archiver.enabled:
        gsi_considered = {}
    else:
        gsi_considered = None
    if check_posture_compatibility and sim is not None and sim.posture.target is not None:
        show_posture_incompatible_icon = True
    else:
        show_posture_incompatible_icon = False
    if not si_or_sa.is_social or potential_targets:
        with sims4.callback_utils.invoke_enter_exit_callbacks(sims4.callback_utils.CallbackEvent.CONTENT_SET_GENERATE_ENTER, sims4.callback_utils.CallbackEvent.CONTENT_SET_GENERATE_EXIT):
            target_to_posture_icon_info = {}
            for affordance in si_or_sa.all_affordances_gen(phase_index=phase_index):
                if affordance.is_super:
                    logger.error('Content set contains a super affordance: {} has {}', si_or_sa, affordance)
                targets = _test_affordance_and_get_targets(affordance, potential_targets, sim, considered=gsi_considered)
                if targets is None:
                    pass
                for target in targets:
                    valid_aops_gen = get_valid_aops_gen(target, affordance, super_affordance, super_interaction, context, include_failed_aops_with_tooltip, push_super_on_prepare=push_super_on_prepare, considered=gsi_considered, aop_kwargs=aop_kwargs)
                    for (aop, test_result) in valid_aops_gen:
                        if not aop.affordance.is_super:
                            aop_show_posture_incompatible_icon = False
                            if show_posture_incompatible_icon:
                                aop_show_posture_incompatible_icon = show_posture_incompatible_icon
                                if target not in target_to_posture_icon_info:
                                    if aop.compatible_with_current_posture_state(sim):
                                        aop_show_posture_incompatible_icon = False
                                    target_to_posture_icon_info[target] = aop_show_posture_incompatible_icon
                                else:
                                    aop_show_posture_incompatible_icon = target_to_posture_icon_info[target]
                            aop.show_posture_incompatible_icon = aop_show_posture_incompatible_icon
                            mixer_weight = aop.affordance.calculate_autonomy_weight(sim)
                        else:
                            mixer_weight = 0
                        valid[affordance].append((mixer_weight, aop, test_result))
    if sim.posture.source_interaction is si_or_sa:
        for buff in sim.Buffs:
            buff_aops = get_buff_aops(sim, buff, sim.animation_interaction, context, potential_targets=potential_targets, gsi_considered=gsi_considered)
            while buff_aops:
                valid.update(buff_aops)
    if valid:
        return list(_select_affordances_gen(sim, super_affordance, valid, show_posture_incompatible_icon, gsi_considered))
    return ()

def get_buff_aops(sim, buff, super_interaction, context, potential_targets=(), gsi_considered=None):
    if buff.interactions is None:
        return
    actual_potential_targets = potential_targets
    if not potential_targets:
        actual_potential_targets = super_interaction.get_potential_mixer_targets()
    valid = {}
    for buff_affordance in buff.interactions.interaction_items:
        targets = _test_affordance_and_get_targets(buff_affordance, actual_potential_targets, sim, considered=gsi_considered)
        if targets is None:
            pass
        for target in targets:
            for (aop, test_result) in get_valid_aops_gen(target, buff_affordance, super_interaction.super_affordance, super_interaction, context, False, considered=gsi_considered):
                interaction_constraint = aop.constraint_intersection(sim=sim, posture_state=None)
                posture_constraint = sim.posture_state.posture_constraint_strict
                constraint_intersection = interaction_constraint.intersect(posture_constraint)
                if not constraint_intersection.valid:
                    pass
                si_weight = buff.interactions.weight
                if buff_affordance not in valid:
                    valid[buff_affordance] = [(si_weight, aop, test_result)]
                else:
                    valid[buff_affordance].append((si_weight, aop, test_result))
    return valid

def _test_affordance_and_get_targets(affordance, potential_targets, sim, considered=None):
    if not (_mixer_name_list and any(name.match(affordance.__name__) for name in _mixer_name_list)):
        return
    sim_specific_lockout = affordance.lock_out_time.target_based_lock_out if affordance.lock_out_time is not None else False
    if not sim_specific_lockout:
        if sim.is_sub_action_locked_out(affordance):
            if considered is not None:
                considered[affordance] = {'affordance': str(affordance), 'target': '', 'test': 'Locked out'}
            return
        return affordance.filter_mixer_targets(potential_targets, sim)
    targets = affordance.filter_mixer_targets(potential_targets, sim, affordance=affordance)
    if targets:
        return targets
    if considered is not None:
        target_strs = [str(x) for x in potential_targets]
        considered[affordance] = {'affordance': str(affordance), 'target': ', '.join(target_strs), 'test': 'Locked out'}
    return

def _select_affordances_gen(sim, super_interaction, valid, show_posture_incompatible_icon, gsi_considered):
    if gsi_handlers.content_set_handlers.archiver.enabled:
        gsi_results = {}
    scored = {}
    for (affordance, affordance_results) in valid.items():
        base_score = affordance.get_base_content_set_score()
        buff_score_adjustment = sim.get_actor_scoring_modifier(affordance)
        topic_score = sum(topic.score_for_sim(sim) for topic in affordance.topic_preferences)
        score_modifier = sum(affordance.get_score_modifier(sim, aop.target) for (_, aop, _) in affordance_results)
        front_page_cooldown_penalty = sim.get_front_page_penalty(affordance)
        total_score = base_score + buff_score_adjustment + topic_score + score_modifier + front_page_cooldown_penalty
        if show_posture_incompatible_icon and any(aop.show_posture_incompatible_icon for (_, aop, _) in affordance_results):
            total_score *= ContentSetTuning.POSTURE_PENALTY_MULTIPLIER
        scored[affordance] = total_score
        while gsi_handlers.content_set_handlers.archiver.enabled:
            while True:
                for (_, aop, _) in valid[affordance]:
                    if aop not in gsi_considered:
                        gsi_considered[aop] = {}
                    gsi_considered[aop]['base_score'] = base_score
                    gsi_considered[aop]['buff_score_adjustment'] = buff_score_adjustment
                    gsi_considered[aop]['topic_score'] = topic_score
                    gsi_considered[aop]['score_modifier'] = score_modifier
                    gsi_considered[aop]['total_score'] = total_score
                    gsi_considered[aop]['eligible'] = ''
    for (affordance, score) in scored.items():
        score = scored[affordance]
        for (weight, aop, test_result) in valid[affordance]:
            aop.content_score = score
            if gsi_handlers.content_set_handlers.archiver.enabled:
                gsi_considered[aop]['selected'] = True
                gsi_results[aop] = {'result_affordance': str(affordance), 'result_target': str(aop.target), 'result_loc_key': aop.affordance.display_name().hash, 'result_target_loc_key': aop.affordance.display_name_target().hash}
            yield (weight, aop, test_result)
    if gsi_handlers.content_set_handlers.archiver.enabled:
        gsi_handlers.content_set_handlers.archive_content_set(sim, super_interaction, gsi_considered, gsi_results, sim.get_topics_gen())

def lock_content_sets(mixer_name_list):
    global _mixer_name_list
    _mixer_name_list = []
    for name in mixer_name_list:
        name = name.replace('*', '.*')
        name += '$'
        _mixer_name_list.append(re.compile(name))

