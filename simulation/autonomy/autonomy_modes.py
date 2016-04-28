from _weakrefset import WeakSet
import collections
import itertools
import random
import time
from autonomy.autonomy_interaction_priority import AutonomyInteractionPriority
from autonomy.autonomy_request import AutonomyDistanceEstimationBehavior, AutonomyPostureBehavior
from event_testing.results import TestResult
from interactions.aop import AffordanceObjectPair
from interactions.context import InteractionContext, InteractionSource
from sims4.tuning.geometric import TunableWeightedUtilityCurve, TunableCurve
from sims4.tuning.tunable import Tunable, TunableInterval, TunableSimMinute, TunableMapping, TunableEnumEntry, TunableReference, TunableRealSecond
from singletons import DEFAULT
from statistics.base_statistic import StatisticChangeDirection
from tag import Tag
import autonomy.autonomy_exceptions
import autonomy.content_sets
import autonomy.settings
import buffs
import clock
import date_and_time
import element_utils
import elements
import enum
import gsi_handlers
import interactions
import interactions.base
import objects.components.types
import services
import sims4.log
import sims4.random
import sims4.reload
import sims4.repr_utils
import singletons
from _collections import defaultdict
with sims4.reload.protected(globals()):
    g_affordance_times = None

def enable_gsi_logging(*args, enableLog=False, **kwargs):
    global InteractionScore, InteractionCommodityScore, ScoredStatistic
    if enableLog:
        InteractionScore = _InteractionScore
        InteractionCommodityScore = _InteractionCommodityScore
        ScoredStatistic = _ScoredStatistic
    else:
        InteractionScore = InteractionCommodityScore = lambda score, *args, **kwargs: float(score)

logger = sims4.log.Logger('Autonomy', default_owner='rez')
timeslice_logger = sims4.log.Logger('AutonomyTimeslice', default_owner='rez')

def affordance_repr(aop_affordance_or_interaction):
    affordance = getattr(aop_affordance_or_interaction, 'affordance', aop_affordance_or_interaction)
    return affordance.__name__

_AUTONOMY_TEST_RESULT_TRUE = TestResult.TRUE
_AUTONOMY_TEST_RESULT_FALSE = TestResult(False)

def AutonomyTestResult(value, message, tooltip=None):
    if value:
        return _AUTONOMY_TEST_RESULT_TRUE
    return _AUTONOMY_TEST_RESULT_FALSE

AutonomyTestResult.TRUE = _AUTONOMY_TEST_RESULT_TRUE
TimerRange = collections.namedtuple('TimerRange', ['lower_bound', 'upper_bound'])
ScoredInteractionData = collections.namedtuple('ScoredInteractionData', ['score', 'route_time', 'multitasking_percentage', 'interaction'])
_DeferredAopData = collections.namedtuple('_DeferredAopData', ['aop', 'inventory_type'])

class AutonomyMode:
    __qualname__ = 'AutonomyMode'
    FULL_AUTONOMY_DELAY = TunableInterval(TunableSimMinute, 15, 30, minimum=0, description='\n                                  Amount of time, in sim minutes, between full autonomy runs.  System will randomize between \n                                  min and max each time')
    FULL_AUTONOMY_DELAY_WITH_NO_PRIMARY_SIS = TunableInterval(TunableSimMinute, 1.5, 2.5, minimum=0, description="\n                                                      The amount of time, in sim minutes, to wait before running autonomy if a sim \n                                                      is not in any primary SI's and hasn't run a user-directed action since \n                                                      AUTONOMY_DELAY_AFTER_USER_INTERACTION.")
    FULL_AUTONOMY_DELAY_WITH_NO_RESULT = TunableInterval(description="\n                                                The amount of time, in sim minutes, to wait before running autonomy if a sim's \n                                                autonomy returned None.\n                                                ", tunable_type=TunableSimMinute, default_lower=20, default_upper=30, minimum=1)
    AUTONOMY_DELAY_AFTER_USER_INTERACTION = TunableSimMinute(25, description='\n                                                    The amount of time, in sim minutes, before a sim that performs a user-direction \n                                                    interaction will run autonomy.')
    LOCKOUT_TIME = TunableSimMinute(240, description='\n                           Number of sim minutes to lockout a failed interaction push or routing failure.')
    MAX_REAL_SECONDS_UNTIL_TIMESLICING_IS_REMOVED = TunableRealSecond(description='\n                                                        The amount of time before autonomy stops timeslicing and forces the autonomy request to \n                                                        run unimpeded.', default=1)
    FULL_AUTONOMY_STATISTIC_SCORE_VARIANCE = Tunable(float, 0.9, description='\n                                                     The percentage variance that a statistic can have from the top stat before it is \n                                                     not considered for the first round of scoring.')
    FULL_AUTONOMY_MULTIPLIER_FOR_SOLVING_THE_SAME_STAT = Tunable(float, 0.25, description='\n                                                     If a sim is currently solving a motive, this value will be multiplied into the \n                                                     commodity score of any other interactions.  This will force sims to live with \n                                                     their decisions rather than always looking for the best thing.')
    FULL_AUTONOMY_DESIRE_TO_JOIN_PLAYER_PARTIES = Tunable(float, 0, description='\n                                                          This weight is multiplied with the affordance score if the target party has \n                                                          any sims that are not autonomous.')
    FULL_AUTONOMY_ATTENTION_COST = TunableWeightedUtilityCurve(description='\n                                                             A curve that maps the total attention cost with a score multiplier.  This value will be \n                                                             multiplied with the typical autonomy score to account for multi-tasking costs.')
    FULL_AUTONOMY_MULTITASKING_PERCENTAGE_BONUS = TunableCurve(description='\n                                                             A curve that maps the commodity desire score with a percentage bonus applied to the \n                                                             base multitasking chance.')
    OFF_LOT_OBJECT_SCORE_MULTIPLIER = Tunable(description='\n                                                The autonomy score multiplier for off-lot object when a sim \n                                                is on the active lot.\n                                                ', tunable_type=float, default=0.5)
    SUBACTION_AUTONOMY_CONTENT_SCORE_UTILITY_CURVE = TunableWeightedUtilityCurve(description='\n                                                             A curve that maps the content score to the provided utility.')
    SUBACTION_MOTIVE_UTILITY_FALLBACK_SCORE = Tunable(float, 0.1, description='\n                                                      If score for sub-action motive utility is zero, use this value as the best score.')
    SUBACTION_GROUP_UNTUNED_WEIGHT = 1
    SUBACTION_GROUP_WEIGHTING = TunableMapping(description='\n                                    Mapping of mixer interaction group tags to scores.  This is used by subaction autonomy\n                                    to decide which set of mixers to run.  See the mixer_group entry in the sub_action tunable\n                                    on any mixer for details as to how the system works.\n                                    ', key_type=TunableEnumEntry(interactions.MixerInteractionGroup, interactions.MixerInteractionGroup.DEFAULT, description='\n                                        The mixer group this score applies to.\n                                        '), value_type=Tunable(int, SUBACTION_GROUP_UNTUNED_WEIGHT, description='\n                                        The weight of this group.\n                                        '))
    POSTURE_CHANGE_OPPORTUNITY_COST_MULTIPLIER = Tunable(float, 1.5, description='\n                                                        Multiplier to apply to the total opportunity cost of an aop when choosing that aop would\n                                                        force the Sim to change postures.  This makes the concept of changing postures less \n                                                        attractive to Sims.')
    AUTOMATED_RANDOMIZATION_LIST = TunableMapping(description='\n        A mapping of the commodities used for determinisitc randomization.  This is used by the automation\n        system in the min spec perf tests.\n        ', key_type=TunableReference(description='\n            The statistic we are operating on.', manager=services.statistic_manager()), value_type=Tunable(description='\n            The number of times per loop to assign this to a Sim.', tunable_type=int, default=1))
    NUMBER_OF_DUPLICATE_AFFORDANCE_TAGS_TO_SCORE = Tunable(description='\n                                                        If an affordance is tuned with duplicate_affordance_group set to anything \n                                                        except INVALID, this is the number of affordances that share this tag that\n                                                        will be scored. \n                                                        ', tunable_type=int, default=3)
    _full_autonomy_delay_override = None
    _autonomy_delay_after_user_interaction_override = None
    _disable_autonomous_multitasking_if_user_directed_override = singletons.DEFAULT
    _MINIMUM_SCORE = 1e-05

    class _AutonomyStageLabel:
        __qualname__ = 'AutonomyMode._AutonomyStageLabel'
        BEFORE_TESTS = '1 - Before Tests'
        AFTER_TESTS = '2 - After Tests'
        AFTER_POSTURE_SEARCH = '3 - After Posture Search'
        AFTER_SCORING = '4 - After Scoring'

    def __init__(self, request):
        self._request = request
        self._motive_scores = None
        self._process_start_time = None

    def __str__(self):
        return 'Unknown Mode'

    @property
    def _sim(self):
        return self._request.sim

    def run_gen(self, timeline, timeslice):
        self._motive_scores = self._score_motives()
        result = yield self._run_gen(timeline, timeslice)
        return result

    def _run_gen(self, timeline, timeslice):
        raise NotImplementedError
        yield None

    @classmethod
    def toggle_disable_autonomous_multitasking_if_user_directed(cls, to_enabled):
        if cls._disable_autonomous_multitasking_if_user_directed_override is singletons.DEFAULT:
            is_enabled = False
        else:
            is_enabled = cls._disable_autonomous_multitasking_if_user_directed_override
        if to_enabled is None:
            cls._disable_autonomous_multitasking_if_user_directed_override = not is_enabled
        else:
            cls._disable_autonomous_multitasking_if_user_directed_override = to_enabled
        return cls._disable_autonomous_multitasking_if_user_directed_override

    @classmethod
    def get_autonomy_delay_after_user_interaction(cls):
        return clock.interval_in_sim_minutes(cls._get_autonomy_delay_after_user_interaction_in_sim_minutes())

    @classmethod
    def get_negative_autonomy_delay_after_user_interaction(cls):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return clock.interval_in_sim_minutes(-cls._get_autonomy_delay_after_user_interaction_in_sim_minutes())

    @classmethod
    def _get_autonomy_delay_after_user_interaction_in_sim_minutes(cls):
        if cls._autonomy_delay_after_user_interaction_override is not None:
            return cls._autonomy_delay_after_user_interaction_override
        return cls.AUTONOMY_DELAY_AFTER_USER_INTERACTION

    @classmethod
    def get_autonomous_delay_time(cls):
        return clock.interval_in_sim_minutes(cls._get_autonomous_delay_time_in_sim_minutes())

    @classmethod
    def get_negative_autonomous_delay_time(cls):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return clock.interval_in_sim_minutes(-cls._get_autonomous_delay_time_in_sim_minutes())

    @classmethod
    def _get_autonomous_delay_time_in_sim_minutes(cls):
        raise NotImplementedError

    @classmethod
    def get_autonomous_update_delay_with_no_primary_sis(cls):
        return clock.interval_in_sim_minutes(cls._get_autonomous_update_delay_with_no_primary_sis_in_sim_minutes())

    @classmethod
    def get_negative_autonomous_update_delay_with_no_primary_sis(cls):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return clock.interval_in_sim_minutes(-cls._get_autonomous_update_delay_with_no_primary_sis_in_sim_minutes())

    @classmethod
    def _get_autonomous_update_delay_with_no_primary_sis_in_sim_minutes(cls):
        return cls.FULL_AUTONOMY_DELAY_WITH_NO_PRIMARY_SIS.random_float()

    @classmethod
    def get_no_result_delay_time(cls):
        return clock.interval_in_sim_minutes(cls.FULL_AUTONOMY_DELAY_WITH_NO_RESULT.random_float())

    @classmethod
    def override_full_autonomy_delay(cls, lower_bound, upper_bound):
        if lower_bound > upper_bound:
            logger.error('lower_bound > upper_bound in override_full_autonomy_delay()')
        else:
            cls._full_autonomy_delay_override = TimerRange(lower_bound=lower_bound, upper_bound=upper_bound)

    @classmethod
    def clear_full_autonomy_delay_override(cls):
        cls._full_autonomy_delay_override = None

    @classmethod
    def override_full_autonomy_delay_after_user_action(cls, delay):
        cls._autonomy_delay_after_user_interaction_override = delay

    @classmethod
    def clear_full_autonomy_delay_after_user_action(cls):
        cls._autonomy_delay_after_user_interaction_override = None

    @classmethod
    def test(cls, sim):
        return True

    @classmethod
    def is_silent_mode(cls):
        return False

    def set_process_start_time(self):
        self._process_start_time = time.clock()

    @classmethod
    def allows_routing(cls):
        return False

    def _allow_autonomous(self, aop):
        if self._request.ignore_user_directed_and_autonomous:
            return AutonomyTestResult.TRUE
        affordance = aop.affordance
        if not affordance.allow_autonomous:
            if self._request.record_test_result is not None:
                self._request.record_test_result(aop, 'allow_autonomous', None)
            return AutonomyTestResult(False, 'allow_autonomous is False.')
        if self._request.context.source == InteractionContext.SOURCE_AUTONOMY and affordance.is_super and not affordance.commodity_flags:
            if self._request.record_test_result is not None:
                self._request.record_test_result(aop, 'allow_autonomous', None)
            return AutonomyTestResult(False, 'No commodities were advertised.')
        if self._request.context.source == InteractionContext.SOURCE_PIE_MENU and not affordance.allow_user_directed:
            if self._request.record_test_result is not None:
                self._request.record_test_result(aop, 'allow_user_directed', None)
            return AutonomyTestResult(False, 'allow_user_directed is False.')
        return AutonomyTestResult.TRUE

    def _is_available(self, obj):
        context = self._request.context
        if context.source != context.SOURCE_AUTONOMY and not context.always_check_in_use:
            return self._get_object_result(obj, success=True, reason='Scored')
        if not self._request.ignore_lockouts and self._sim.has_lockout(obj):
            if self._request.record_test_result is not None:
                self._request.record_test_result(None, '_is_available', sims4.utils.Result(False, 'Sim has lockout.'))
            return self._get_object_result(obj, success=False, reason='Sim has lockout for this object')
        return self._get_object_result(obj, success=True, reason='Scored')

    def _get_object_result(self, obj, success, reason):
        return success

    def _score_motives(self):
        motive_scores = None
        if self._request.has_commodities:
            motive_scores = {stat.stat_type: ScoredStatistic(stat.stat_type, self._sim) for stat in tuple(itertools.chain(self._sim.scored_stats_gen(), self._request.all_commodities))}
        elif self._request.affordance_list:
            motive_scores = {stat.stat_type: ScoredStatistic(stat.stat_type, self._sim) for stat in tuple(self._sim.scored_stats_gen())}
        else:
            stats = [stat.stat_type for stat in self._sim.scored_stats_gen()]
            motive_scores = {stat_type: ScoredStatistic(stat_type, self._sim) for stat_type in stats}
        return motive_scores

    @classmethod
    def _should_log(cls, active_sim):
        if not cls.is_silent_mode():
            if active_sim is not None:
                return services.autonomy_service().should_log(active_sim)
            return False

class _MixerAutonomy(AutonomyMode):
    __qualname__ = '_MixerAutonomy'

    def __init__(self, request):
        super().__init__(request)
        self._positive_scoring_mixer_providers = None
        self._zero_scoring_mixer_providers = None

    def _cache_mixer_provider_scores(self, gsi_mixer_selection, gsi_sub_interactions):
        if self._positive_scoring_mixer_providers is not None and self._zero_scoring_mixer_providers is not None:
            return
        self._positive_scoring_mixer_providers = []
        self._zero_scoring_mixer_providers = []
        for mixer_provider in self._mixer_providers_gen():
            mixer_provider_score = self._score_mixer_provider(mixer_provider, gsi_mixer_selection)
            mixer_aops = mixer_provider.get_mixers(self._request)
            if mixer_aops is None:
                pass
            (scored_mixers_aops, has_score_above_zero) = self._create_and_score_mixers(mixer_provider, mixer_aops, gsi_sub_interactions)
            if scored_mixers_aops is None:
                pass
            if mixer_provider_score <= 0 or not has_score_above_zero:
                self._zero_scoring_mixer_providers.append((mixer_provider_score, (mixer_provider, scored_mixers_aops)))
            else:
                self._positive_scoring_mixer_providers.append((mixer_provider_score, (mixer_provider, scored_mixers_aops)))

    def _run_gen(self, timeline, timeslice):
        logger.assert_log(timeslice is None, 'SubActionAutonomy does not support timeslicing.')
        gsi_enabled_at_start = gsi_handlers.autonomy_handlers.archiver.enabled
        if gsi_enabled_at_start:
            gsi_mixer_provider_scoring = []
            gsi_mixer_scoring = []
        else:
            gsi_mixer_provider_scoring = None
            gsi_mixer_scoring = None
        self._cache_mixer_provider_scores(gsi_mixer_provider_scoring, gsi_mixer_scoring)
        chosen_mixer_provider = None
        mixers_from_chosen_mixer_provider = None
        if self._positive_scoring_mixer_providers:
            (chosen_mixer_provider, mixers_from_chosen_mixer_provider) = sims4.random.weighted_random_item(self._positive_scoring_mixer_providers)
        elif self._zero_scoring_mixer_providers:
            random_index = random.randint(0, len(self._zero_scoring_mixer_providers) - 1)
            (chosen_mixer_provider, mixers_from_chosen_mixer_provider) = self._zero_scoring_mixer_providers[random_index][1]
        if gsi_enabled_at_start and not self._request.gsi_data:
            self._request.gsi_data = {'Affordances': [], 'Probability': [], 'Objects': [], 'Commodities': self._motive_scores.values(), 'MixerProvider': gsi_mixer_provider_scoring, 'Mixers': gsi_mixer_scoring}
            if chosen_mixer_provider:
                self._request.gsi_data['selected_mixer_provider'] = str(chosen_mixer_provider)
        if mixers_from_chosen_mixer_provider is None:
            return None
        groups_and_weights_from_mixers = []
        for group in mixers_from_chosen_mixer_provider.keys():
            if group in self.SUBACTION_GROUP_WEIGHTING:
                groups_and_weights_from_mixers.append((self.SUBACTION_GROUP_WEIGHTING[group], group))
            else:
                logger.warn('Untuned weight for mixer group: {}', group, owner='rez')
                groups_and_weights_from_mixers.append((self.SUBACTION_GROUP_UNTUNED_WEIGHT, group))
        chosen_group = None
        if groups_and_weights_from_mixers:
            chosen_group = sims4.random.weighted_random_item(groups_and_weights_from_mixers)
        if chosen_group is None:
            return None
        final_choice = mixers_from_chosen_mixer_provider[chosen_group]
        if final_choice is None:
            return None
        valid_interactions = ValidInteractions()
        for (interaction_score, mixer_aop) in final_choice.values():
            mixer_result = mixer_aop.interaction_factory(self._request.context)
            if not mixer_result:
                pass
            mixer_interaction = mixer_result.interaction
            if mixer_interaction is not None:
                valid_interactions.add(ScoredInteractionData(interaction_score, 0, 1, mixer_interaction))
        self._request.valid_interactions = valid_interactions
        return valid_interactions
        yield None

    @classmethod
    def test(cls, sim):
        autonomy_state = sim.get_autonomy_state_setting()
        if autonomy_state <= autonomy.settings.AutonomyState.DISABLED:
            return False
        return True

    @classmethod
    def _get_autonomous_delay_time_in_sim_minutes(cls):
        return cls.SUB_ACTION_AUTONOMY_DELAY

    def _mixer_providers_gen(self):
        raise NotImplementedError
        yield None

    def _score_mixer_provider(self, mixer_provider, gsi_mixer_provider_tab):
        scored_commodity = mixer_provider.get_scored_commodity(self._motive_scores)
        motive_utility = None
        if scored_commodity:
            motive_utility = self._motive_scores.get(scored_commodity)
        if motive_utility is None:
            motive_utility = self.SUBACTION_MOTIVE_UTILITY_FALLBACK_SCORE
        else:
            motive_utility = max(motive_utility, self.SUBACTION_MOTIVE_UTILITY_FALLBACK_SCORE)
        score = motive_utility*mixer_provider.get_subaction_weight()
        if gsi_mixer_provider_tab is not None:
            score_detail_string = 'Weight: {}; ScoredCommodity: {} Commodity Score: {}'.format(mixer_provider.get_subaction_weight(), scored_commodity, motive_utility)
            gsi_mixer_provider_tab.append([str(mixer_provider), mixer_provider.target_string, score, score_detail_string])
        return score

    def _create_and_score_mixers(self, mixer_provider, mixer_aops, gsi_mixer_tab):
        mixer_scores = {}
        has_score_above_zero = False
        content_set_score = 1
        mixer_provider_is_social = mixer_provider.is_social
        for (mixer_weight, mixer_aop, _) in mixer_aops:
            mixer_aop_affordance = mixer_aop.affordance
            mixer_aop_target = mixer_aop.target
            if mixer_provider_is_social and (mixer_aop_affordance.target_type & interactions.TargetType.TARGET and mixer_aop_target.is_sim) and mixer_aop_target.ignore_autonomous_targeted_socials:
                pass
            test_result = self._allow_autonomous(mixer_aop)
            if not test_result:
                while gsi_mixer_tab is not None:
                    gsi_mixer_tab.append((0, str(mixer_provider), str(mixer_aop_affordance), str(mixer_aop_target), 'Ignored: {}'.format(str(test_result))))
                    if mixer_provider_is_social:
                        content_set_score = self._get_subaction_content_set_utility_score(mixer_aop.content_score)
                        score = mixer_weight*content_set_score
                    else:
                        score = mixer_weight
                    if score <= self._MINIMUM_SCORE:
                        score = 0
                    group = mixer_aop_affordance.sub_action.mixer_group
                    if group not in mixer_scores:
                        mixer_scores[group] = {}
                    mixer_scores[group][mixer_aop_affordance] = (score, mixer_aop)
                    if score > 0:
                        has_score_above_zero = True
                    while gsi_mixer_tab is not None:
                        score_detail_string = 'Weight: {}; Content Score: {}; Group: {}'.format(mixer_weight, content_set_score, mixer_aop_affordance.sub_action.mixer_group)
                        gsi_mixer_tab.append((score, str(mixer_provider), str(mixer_aop_affordance), str(mixer_aop_target), score_detail_string))
            if mixer_provider_is_social:
                content_set_score = self._get_subaction_content_set_utility_score(mixer_aop.content_score)
                score = mixer_weight*content_set_score
            else:
                score = mixer_weight
            if score <= self._MINIMUM_SCORE:
                score = 0
            group = mixer_aop_affordance.sub_action.mixer_group
            if group not in mixer_scores:
                mixer_scores[group] = {}
            mixer_scores[group][mixer_aop_affordance] = (score, mixer_aop)
            if score > 0:
                has_score_above_zero = True
            while gsi_mixer_tab is not None:
                score_detail_string = 'Weight: {}; Content Score: {}; Group: {}'.format(mixer_weight, content_set_score, mixer_aop_affordance.sub_action.mixer_group)
                gsi_mixer_tab.append((score, str(mixer_provider), str(mixer_aop_affordance), str(mixer_aop_target), score_detail_string))
        if not mixer_aops:
            return (None, False)
        return (mixer_scores, has_score_above_zero)

    def _get_subaction_content_set_utility_score(self, content_score):
        if content_score is None:
            return self.SUBACTION_MOTIVE_UTILITY_FALLBACK_SCORE
        utility = self.SUBACTION_AUTONOMY_CONTENT_SCORE_UTILITY_CURVE.get(content_score)
        if utility == 0:
            return self.SUBACTION_MOTIVE_UTILITY_FALLBACK_SCORE
        return utility

class SubActionAutonomy(_MixerAutonomy):
    __qualname__ = 'SubActionAutonomy'

    def __str__(self):
        return 'SubActionAutonomy'

    def _mixer_providers_gen(self):
        for si in self._sim.si_state:
            if not si.has_affordances():
                pass
            mixer_provider = _MixerProvider(si)
            yield mixer_provider
        for buff in self._sim.Buffs:
            if buff.interactions is None:
                pass
            mixer_provider = _MixerProvider(buff)
            yield mixer_provider

class SocialAutonomy(_MixerAutonomy):
    __qualname__ = 'SocialAutonomy'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __str__(self):
        return 'SocialAutonomy'

    def _run_gen(self, timeline, timeslice):
        if not self._validate_request():
            return
        result = yield super()._run_gen(timeline, timeslice)
        return result

    def _validate_request(self):
        if not self._request.static_commodity_list:
            logger.error('Failed to run SocialAutonomy: no static commodities listed.')
            return False
        if not self._request.object_list:
            logger.error('Failed to run SocialAutonomy: no objects listed.')
            return False
        return True

    def _mixer_providers_gen(self):
        for target_sim in self._request.objects_to_score_gen(self._request.static_commodity_list):
            if not target_sim.is_sim:
                pass
            if not self._is_available(target_sim):
                pass
            for affordance in target_sim.super_affordances():
                while True:
                    for static_commodity in self._request.static_commodity_list:
                        while static_commodity in affordance.static_commodities:
                            break
                aop = AffordanceObjectPair(affordance, target_sim, affordance, None)
                execute_result = aop.interaction_factory(self._request.context)
                if not execute_result:
                    logger.error('Failed to create interaction: '.format(aop))
                interaction = execute_result.interaction
                incompatible_sis = self._sim.si_state.get_incompatible(interaction)
                if incompatible_sis:
                    interaction.invalidate()
                incompatible_sis = target_sim.si_state.get_incompatible(interaction, participant_type=interactions.ParticipantType.TargetSim)
                if incompatible_sis:
                    interaction.invalidate()
                self._request.interactions_to_invalidate.append(interaction)
                yield _MixerProvider(interaction)

class _SuperInteractionAutonomy(AutonomyMode):
    __qualname__ = '_SuperInteractionAutonomy'
    UNREACHABLE_DESTINATION_COST = 1000000

    def __init__(self, request):
        super().__init__(request)
        self._actively_scored_motives = None

    def _test_aop(self, aop):
        context = self._request.context
        test_result = aop.test(context)
        if not test_result:
            if self._request.record_test_result is not None:
                self._request.record_test_result(aop, '_test_aop', test_result)
            return test_result
        return AutonomyTestResult.TRUE

    def _has_available_part(self, interaction):
        if interaction.basic_reserve_object is not None and interaction.target is not None and interaction.target.parts:
            original_target = interaction.target
            for part in interaction.target.parts:
                interaction.set_target(part)
                reserve_handler = interaction.basic_reserve_object(interaction.sim, interaction)
                reserve_result = reserve_handler.may_reserve(affordance=interaction.affordance, context=interaction.context)
                interaction.set_target(original_target)
                while reserve_result:
                    return True
            return False
        return True

    def _calculate_route_time_and_opportunity(self, interaction):
        request = self._request
        if interaction.disable_distance_estimation_and_posture_checks:
            return (0, False, set())
        if request.distance_estimation_behavior == AutonomyDistanceEstimationBehavior.BEST_ALWAYS and request.posture_behavior == AutonomyPostureBehavior.BEST_ALWAYS:
            return (0, False, set())
        if request.posture_behavior == AutonomyPostureBehavior.IGNORE_SI_STATE:
            (estimated_distance, must_change_posture, included_sis) = interaction.estimate_distance_ignoring_other_sis()
        else:
            (estimated_distance, must_change_posture, included_sis) = interaction.estimate_distance()
        if request.posture_behavior == AutonomyPostureBehavior.BEST_ALWAYS:
            must_change_posture = False
            included_sis = set()
        if request.distance_estimation_behavior == AutonomyDistanceEstimationBehavior.ALLOW_UNREACHABLE_LOCATIONS and estimated_distance is None:
            estimated_distance = _SuperInteractionAutonomy.UNREACHABLE_DESTINATION_COST
        elif request.distance_estimation_behavior == AutonomyDistanceEstimationBehavior.IGNORE_DISTANCE and estimated_distance is not None:
            estimated_distance = 0
        elif request.distance_estimation_behavior == AutonomyDistanceEstimationBehavior.BEST_ALWAYS:
            estimated_distance = 0
        route_time = None
        if estimated_distance is not None:
            route_time = estimated_distance*date_and_time.get_real_milliseconds_per_sim_second()/date_and_time.TICKS_PER_REAL_WORLD_SECOND
        return (route_time, must_change_posture, included_sis)

    def _satisfies_active_desire(self, aop):
        if not self._actively_scored_motives:
            return True
        if aop.affordance.commodity_flags & self._actively_scored_motives:
            return True
        return False

    @staticmethod
    def _is_valid_interaction(interaction):
        if not interaction.affordance.autonomy_can_overwrite_similar_affordance and interaction.sim.si_state.is_affordance_active_for_actor(interaction.affordance):
            return AutonomyTestResult(False, 'Sim is already running the same affordance.')
        return AutonomyTestResult.TRUE

    def _get_object_result(self, obj, success, reason):
        if success:
            return ObjectResult.Success(obj, relevant_desires=self._actively_scored_motives)
        return ObjectResult.Failure(obj, relevant_desires=self._actively_scored_motives, reason=reason)

    @classmethod
    def allows_routing(cls):
        return True

class ValidInteractions:
    __qualname__ = 'ValidInteractions'

    def __init__(self):
        self._data = {}
        self._refs = {}

    def __str__(self):
        return str(self._data)

    def __repr__(self):
        return sims4.repr_utils.standard_angle_repr(self, self._data)

    def __bool__(self):
        if self._data:
            return True
        return False

    def __contains__(self, affordance):
        return affordance.get_affordance_key_for_autonomy() in self._data

    def __getitem__(self, affordance):
        return self._data[affordance.get_affordance_key_for_autonomy()]

    def add(self, scored_interaction_data):
        interaction = scored_interaction_data.interaction
        affordance_key = interaction.affordance.get_affordance_key_for_autonomy()
        self._data[affordance_key] = scored_interaction_data
        if interaction.target is not None:

            def callback(_):
                del self._data[affordance_key]
                del self._refs[affordance_key]

            self._refs[affordance_key] = interaction.target.ref(callback)
        else:
            self._refs[affordance_key] = None

    def has_score_for_aop(self, aop):
        affordance_key = aop.affordance.get_affordance_key_for_autonomy()
        if affordance_key not in self._data:
            return False
        scored_interaction_data = self._data[affordance_key]
        return scored_interaction_data.interaction.aop.is_equivalent_to(aop)

    def get_result_scores(self):
        return tuple(self._data.values())

def _dont_timeslice_gen(timeline):
    return False
    yield None

class FullAutonomy(_SuperInteractionAutonomy):
    __qualname__ = 'FullAutonomy'
    _GSI_IGNORES_NON_AUTONOMOUS_AFFORDANCES = True

    def __init__(self, request):
        super().__init__(request)
        self._relationship_object_value = 0
        self._found_valid_interaction = False
        self._inventory_posture_score_cache = {}
        self._motives_being_solved = None
        self._valid_interactions = {}
        for i in AutonomyInteractionPriority:
            self._valid_interactions[i] = ValidInteractions()
        self._limited_affordances = defaultdict(list)
        self._gsi_objects = []
        self._gsi_interactions = []
        self._timestamp_when_timeslicing_was_removed = None

    def _clean_up(self):
        for i in AutonomyInteractionPriority:
            for scored_interaction_data in self._valid_interactions[i].get_result_scores():
                if not scored_interaction_data.interaction.is_super:
                    pass
                scored_interaction_data.interaction.invalidate()

    def __str__(self):
        return 'FullAutonomy'

    def _run_gen(self, timeline, timeslice):
        if self._should_log(self._sim):
            logger.debug('Processing {}', self._sim)
        gsi_enabled_at_start = gsi_handlers.autonomy_handlers.archiver.enabled
        (self._actively_scored_motives, motives_not_yet_scored) = self._get_motives_to_score()
        if not self._actively_scored_motives:
            return
        self._motives_being_solved = self._get_all_motives_currently_being_solved()
        if timeslice is None:
            timeslice_if_needed_gen = _dont_timeslice_gen
        else:
            start_time = time.clock()

            def timeslice_if_needed_gen(timeline):
                nonlocal start_time
                time_now = time.clock()
                elapsed_time = time_now - start_time
                if elapsed_time < timeslice:
                    return False
                if self._timestamp_when_timeslicing_was_removed is not None:
                    enable_long_slice = False
                else:
                    total_elapsed_time = time_now - self._process_start_time
                    if total_elapsed_time > self.MAX_REAL_SECONDS_UNTIL_TIMESLICING_IS_REMOVED:
                        timeslice_logger.debug('Autonomy request for {} took too long; timeslicing is removed.', self._sim)
                        self._timestamp_when_timeslicing_was_removed = time_now
                        enable_long_slice = False
                    else:
                        enable_long_slice = True
                if enable_long_slice:
                    sleep_element = element_utils.sleep_until_next_tick_element()
                else:
                    sleep_element = elements.SleepElement(date_and_time.TimeSpan(0))
                yield timeline.run_child(sleep_element)
                if self._sim is None or not self._request.valid:
                    self._clean_up()
                    raise autonomy.autonomy_exceptions.AutonomyExitException()
                start_time = time.clock()
                return True

        while True:
            self._inventory_posture_score_cache = {}
            objects_to_score = WeakSet(self._request.objects_to_score_gen(self._actively_scored_motives))
            while True:
                yield timeslice_if_needed_gen(timeline)
                try:
                    obj = objects_to_score.pop()
                except KeyError:
                    break
                object_result = yield self._score_object_interactions_gen(timeline, obj, timeslice_if_needed_gen)
                if gsi_enabled_at_start:
                    self._gsi_objects.append(object_result)
                if not obj.is_sim:
                    inventory_component = obj.inventory_component
                    if inventory_component and inventory_component.should_score_contained_objects_for_autonomy and inventory_component.inventory_type not in self._inventory_posture_score_cache:
                        yield self._score_object_inventory_gen(timeline, inventory_component, timeslice_if_needed_gen)
            for aop_list in self._limited_affordances.values():
                valid_aop_list = [aop_data for aop_data in aop_list if aop_data.aop.target is not None]
                num_aops = len(valid_aop_list)
                if num_aops > self.NUMBER_OF_DUPLICATE_AFFORDANCE_TAGS_TO_SCORE:
                    final_aop_list = random.sample(valid_aop_list, self.NUMBER_OF_DUPLICATE_AFFORDANCE_TAGS_TO_SCORE)
                else:
                    final_aop_list = valid_aop_list
                for aop_data in final_aop_list:
                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop_data.aop, inventory_type=aop_data.inventory_type)
                    if not interaction_result:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop_data.aop, '_create_and_score_interaction', interaction_result)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(interaction_result)
                            self._process_scored_interaction(aop_data.aop, interaction, interaction_result, route_time)
                    self._process_scored_interaction(aop_data.aop, interaction, interaction_result, route_time)
            self._limited_affordances.clear()
            if self._found_valid_interaction:
                break
            if not motives_not_yet_scored:
                break
            (self._actively_scored_motives, motives_not_yet_scored) = self._get_motives_to_score(motives_not_yet_scored)
        final_valid_interactions = None
        for i in AutonomyInteractionPriority:
            while self._valid_interactions[i]:
                final_valid_interactions = self._valid_interactions[i]
                break
        self._request.valid_interactions = final_valid_interactions
        if gsi_enabled_at_start:
            self._request.gsi_data = {'Commodities': self._motive_scores.values(), 'Affordances': self._gsi_interactions, 'Probability': [], 'Objects': self._gsi_objects, 'MixerProvider': [], 'Mixers': []}
        return final_valid_interactions

    @classmethod
    def _get_autonomous_delay_time_in_sim_minutes(cls):
        if cls._full_autonomy_delay_override is None:
            return cls.FULL_AUTONOMY_DELAY.random_float()
        return random.uniform(cls._full_autonomy_delay_override.lower_bound, cls._full_autonomy_delay_override.upper_bound)

    @classmethod
    def test(cls, sim):
        if services.get_super_speed_three_service().in_or_has_requested_super_speed_three():
            return TestResult(False, 'In or has super speed three request')
        if sim.get_autonomy_state_setting() <= autonomy.settings.AutonomyState.LIMITED_ONLY:
            return TestResult(False, 'Limited autonomy and below can never run full autonomy')
        if sim.get_autonomy_state_setting() == autonomy.settings.AutonomyState.MEDIUM and sim.si_state.has_user_directed_si():
            return TestResult(False, 'Medium Autonomy but has a user directed interaction in si state.')
        if sim.queue is None:
            logger.warn('sim.queue is None in FullAutonomy.test()', owner='rez')
            return TestResult(False, 'Sim Partially destroyed.')
        result = cls._test_pending_interactions(sim)
        if not result:
            return result
        if sim.is_player_active():
            return TestResult(False, 'Sim actively being played.')
        return TestResult.TRUE

    def _is_available(self, obj):
        super_result = super()._is_available(obj)
        if not super_result:
            return super_result
        if self._request.radius_to_consider_squared > 0:
            delta = obj.intended_position - self._sim.intended_position
            if delta.magnitude_squared() > self._request.radius_to_consider_squared:
                return self._get_object_result(obj, success=False, reason='Target object is too far away from the sim.')
        context = self._request.context
        if obj.is_sim and context.source == context.SOURCE_AUTONOMY:
            for interaction in tuple(obj.si_state):
                while interaction.disallows_full_autonomy(self._disable_autonomous_multitasking_if_user_directed_override):
                    return self._get_object_result(obj, success=False, reason='Target sim is running an interaction that disallows multi tasking.')
        return super_result

    def _score_object_inventory_gen(self, timeline, inventory_component, timeslice_if_needed_gen):
        gsi_enabled_at_start = gsi_handlers.autonomy_handlers.archiver.enabled
        for inventory_obj in inventory_component.get_items_for_autonomy_gen(motives=self._actively_scored_motives):
            object_result = yield self._score_object_interactions_gen(timeline, inventory_obj, timeslice_if_needed_gen, inventory_type=inventory_component.inventory_type)
            while gsi_enabled_at_start:
                self._gsi_objects.append(object_result)

    def _score_object_interactions_gen(self, timeline, obj, timeslice_if_needed_gen, inventory_type=None):
        gsi_enabled_at_start = gsi_handlers.autonomy_handlers.archiver.enabled
        context = self._request.context
        obj_ref = obj.ref()
        is_available = self._is_available(obj)
        if not is_available:
            return is_available
        potential_interactions = list(obj.potential_interactions(context, **self._request.kwargs))
        for aop in potential_interactions:
            yielded_due_to_timeslice = yield timeslice_if_needed_gen(timeline)
            if yielded_due_to_timeslice and obj_ref() is None:
                return ObjectResult.Failure(obj, self._actively_scored_motives, 'Object deleted.')
            if aop.affordance.is_super and aop.affordance.should_autonomy_forward_to_inventory():
                aop = self._get_aop_from_inventory(aop)
                if aop is None:
                    pass
            if not aop.affordance.is_super:
                while context.sim is not self._sim:
                    logger.error('A non-super interaction was returned from potential_interactions(): {}', aop, owner='rez')
                    if self._request.affordance_list and aop.affordance not in self._request.affordance_list:
                        pass
                    if aop.affordance.target_type == interactions.TargetType.ACTOR and self._sim is not obj:
                        pass
                    if self._valid_interactions[aop.affordance.scoring_priority].has_score_for_aop(aop):
                        pass
                    test_result = self._allow_autonomous(aop)
                    if not test_result:
                        while not self._GSI_IGNORES_NON_AUTONOMOUS_AFFORDANCES:
                            if self._request.record_test_result is not None:
                                self._request.record_test_result(aop, '_allow_autonomous', None)
                            if gsi_enabled_at_start:
                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason="aop doesn't advertise to autonomy."))
                            else:
                                if obj.check_affordance_for_suppression(self._sim, aop, False):
                                    while self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, 'check_affordance_for_suppression', None)
                                        if self._request.skipped_affordance_list and aop.affordance in self._request.skipped_affordance_list:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, 'skipped_affordance_list', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Affordance in skipped_affordance_list'))
                                                if not self._satisfies_active_desire(aop):
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_satisfies_desire', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                                                        if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_satisfies_desire', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                                                if self._request.constraint is not None:
                                                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                                    if aop_constraint is not None:
                                                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                                        if not aop_constraint.valid:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                                    if crafter_id is not None:
                                                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                                        if relationship_track:
                                                                                            relationship_score = relationship_track.get_value()
                                                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                                test_result = self._test_aop(aop)
                                                                                if not test_result:
                                                                                    if self._request.record_test_result is not None:
                                                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                                                    while gsi_enabled_at_start:
                                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                                        if not interaction_result:
                                                                                            if self._request.record_test_result is not None:
                                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                                            while gsi_enabled_at_start:
                                                                                                self._gsi_interactions.append(interaction_result)
                                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                                if not interaction_result:
                                                                                    if self._request.record_test_result is not None:
                                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                                    while gsi_enabled_at_start:
                                                                                        self._gsi_interactions.append(interaction_result)
                                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                    if crafter_id is not None:
                                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                        if relationship_track:
                                                                            relationship_score = relationship_track.get_value()
                                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                test_result = self._test_aop(aop)
                                                                if not test_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        if self._request.constraint is not None:
                                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                            if aop_constraint is not None:
                                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                                if not aop_constraint.valid:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                            if crafter_id is not None:
                                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                                if relationship_track:
                                                                                    relationship_score = relationship_track.get_value()
                                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                        test_result = self._test_aop(aop)
                                                                        if not test_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                                if not interaction_result:
                                                                                    if self._request.record_test_result is not None:
                                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                                    while gsi_enabled_at_start:
                                                                                        self._gsi_interactions.append(interaction_result)
                                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_satisfies_desire', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                                        if self._request.constraint is not None:
                                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                            if aop_constraint is not None:
                                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                                if not aop_constraint.valid:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                            if crafter_id is not None:
                                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                                if relationship_track:
                                                                                    relationship_score = relationship_track.get_value()
                                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                        test_result = self._test_aop(aop)
                                                                        if not test_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                                if not interaction_result:
                                                                                    if self._request.record_test_result is not None:
                                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                                    while gsi_enabled_at_start:
                                                                                        self._gsi_interactions.append(interaction_result)
                                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if self._request.constraint is not None:
                                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                    if aop_constraint is not None:
                                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                        if not aop_constraint.valid:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                    if crafter_id is not None:
                                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                        if relationship_track:
                                                                            relationship_score = relationship_track.get_value()
                                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                test_result = self._test_aop(aop)
                                                                if not test_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if not self._satisfies_active_desire(aop):
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_satisfies_desire', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                                                if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_satisfies_desire', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                                        if self._request.constraint is not None:
                                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                            if aop_constraint is not None:
                                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                                if not aop_constraint.valid:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                            if crafter_id is not None:
                                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                                if relationship_track:
                                                                                    relationship_score = relationship_track.get_value()
                                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                        test_result = self._test_aop(aop)
                                                                        if not test_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                                if not interaction_result:
                                                                                    if self._request.record_test_result is not None:
                                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                                    while gsi_enabled_at_start:
                                                                                        self._gsi_interactions.append(interaction_result)
                                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if self._request.constraint is not None:
                                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                    if aop_constraint is not None:
                                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                        if not aop_constraint.valid:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                    if crafter_id is not None:
                                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                        if relationship_track:
                                                                            relationship_score = relationship_track.get_value()
                                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                test_result = self._test_aop(aop)
                                                                if not test_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_satisfies_desire', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                                if self._request.constraint is not None:
                                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                    if aop_constraint is not None:
                                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                        if not aop_constraint.valid:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                    if crafter_id is not None:
                                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                        if relationship_track:
                                                                            relationship_score = relationship_track.get_value()
                                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                test_result = self._test_aop(aop)
                                                                if not test_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if self._request.constraint is not None:
                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                            if aop_constraint is not None:
                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                if not aop_constraint.valid:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                            if crafter_id is not None:
                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                if relationship_track:
                                                    relationship_score = relationship_track.get_value()
                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                        test_result = self._test_aop(aop)
                                        if not test_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_test_aop', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if self._request.skipped_affordance_list and aop.affordance in self._request.skipped_affordance_list:
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, 'skipped_affordance_list', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Affordance in skipped_affordance_list'))
                                        if not self._satisfies_active_desire(aop):
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_satisfies_desire', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                                                if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_satisfies_desire', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                                        if self._request.constraint is not None:
                                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                            if aop_constraint is not None:
                                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                                if not aop_constraint.valid:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                            if crafter_id is not None:
                                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                                if relationship_track:
                                                                                    relationship_score = relationship_track.get_value()
                                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                        test_result = self._test_aop(aop)
                                                                        if not test_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                                if not interaction_result:
                                                                                    if self._request.record_test_result is not None:
                                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                                    while gsi_enabled_at_start:
                                                                                        self._gsi_interactions.append(interaction_result)
                                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if self._request.constraint is not None:
                                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                    if aop_constraint is not None:
                                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                        if not aop_constraint.valid:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                    if crafter_id is not None:
                                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                        if relationship_track:
                                                                            relationship_score = relationship_track.get_value()
                                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                test_result = self._test_aop(aop)
                                                                if not test_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_satisfies_desire', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                                if self._request.constraint is not None:
                                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                    if aop_constraint is not None:
                                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                        if not aop_constraint.valid:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                    if crafter_id is not None:
                                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                        if relationship_track:
                                                                            relationship_score = relationship_track.get_value()
                                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                test_result = self._test_aop(aop)
                                                                if not test_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if self._request.constraint is not None:
                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                            if aop_constraint is not None:
                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                if not aop_constraint.valid:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                            if crafter_id is not None:
                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                if relationship_track:
                                                    relationship_score = relationship_track.get_value()
                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                        test_result = self._test_aop(aop)
                                        if not test_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_test_aop', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if not self._satisfies_active_desire(aop):
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_satisfies_desire', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                                        if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_satisfies_desire', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                                if self._request.constraint is not None:
                                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                    if aop_constraint is not None:
                                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                        if not aop_constraint.valid:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                    if crafter_id is not None:
                                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                        if relationship_track:
                                                                            relationship_score = relationship_track.get_value()
                                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                test_result = self._test_aop(aop)
                                                                if not test_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if self._request.constraint is not None:
                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                            if aop_constraint is not None:
                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                if not aop_constraint.valid:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                            if crafter_id is not None:
                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                if relationship_track:
                                                    relationship_score = relationship_track.get_value()
                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                        test_result = self._test_aop(aop)
                                        if not test_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_test_aop', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_satisfies_desire', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                        if self._request.constraint is not None:
                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                            if aop_constraint is not None:
                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                if not aop_constraint.valid:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                            if crafter_id is not None:
                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                if relationship_track:
                                                    relationship_score = relationship_track.get_value()
                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                        test_result = self._test_aop(aop)
                                        if not test_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_test_aop', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if self._request.constraint is not None:
                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                    if aop_constraint is not None:
                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                        if not aop_constraint.valid:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                    if crafter_id is not None:
                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                        if relationship_track:
                                            relationship_score = relationship_track.get_value()
                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                test_result = self._test_aop(aop)
                                if not test_result:
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_test_aop', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                if duplicate_affordance_group != Tag.INVALID:
                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                if not interaction_result:
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(interaction_result)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if obj.check_affordance_for_suppression(self._sim, aop, False):
                        while self._request.record_test_result is not None:
                            self._request.record_test_result(aop, 'check_affordance_for_suppression', None)
                            if self._request.skipped_affordance_list and aop.affordance in self._request.skipped_affordance_list:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, 'skipped_affordance_list', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Affordance in skipped_affordance_list'))
                                    if not self._satisfies_active_desire(aop):
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_satisfies_desire', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                                            if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_satisfies_desire', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                                    if self._request.constraint is not None:
                                                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                        if aop_constraint is not None:
                                                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                            if not aop_constraint.valid:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                        if crafter_id is not None:
                                                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                            if relationship_track:
                                                                                relationship_score = relationship_track.get_value()
                                                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                    test_result = self._test_aop(aop)
                                                                    if not test_result:
                                                                        if self._request.record_test_result is not None:
                                                                            self._request.record_test_result(aop, '_test_aop', None)
                                                                        while gsi_enabled_at_start:
                                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                            if not interaction_result:
                                                                                if self._request.record_test_result is not None:
                                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                                while gsi_enabled_at_start:
                                                                                    self._gsi_interactions.append(interaction_result)
                                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                    if duplicate_affordance_group != Tag.INVALID:
                                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                    if not interaction_result:
                                                                        if self._request.record_test_result is not None:
                                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                        while gsi_enabled_at_start:
                                                                            self._gsi_interactions.append(interaction_result)
                                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                                        if crafter_id is not None:
                                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                            if relationship_track:
                                                                relationship_score = relationship_track.get_value()
                                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                    test_result = self._test_aop(aop)
                                                    if not test_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_test_aop', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            if self._request.constraint is not None:
                                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                if aop_constraint is not None:
                                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                    if not aop_constraint.valid:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                if crafter_id is not None:
                                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                    if relationship_track:
                                                                        relationship_score = relationship_track.get_value()
                                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                            test_result = self._test_aop(aop)
                                                            if not test_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                    if duplicate_affordance_group != Tag.INVALID:
                                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                    if not interaction_result:
                                                                        if self._request.record_test_result is not None:
                                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                        while gsi_enabled_at_start:
                                                                            self._gsi_interactions.append(interaction_result)
                                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_satisfies_desire', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                            if self._request.constraint is not None:
                                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                if aop_constraint is not None:
                                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                    if not aop_constraint.valid:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                if crafter_id is not None:
                                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                    if relationship_track:
                                                                        relationship_score = relationship_track.get_value()
                                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                            test_result = self._test_aop(aop)
                                                            if not test_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                    if duplicate_affordance_group != Tag.INVALID:
                                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                    if not interaction_result:
                                                                        if self._request.record_test_result is not None:
                                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                        while gsi_enabled_at_start:
                                                                            self._gsi_interactions.append(interaction_result)
                                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if self._request.constraint is not None:
                                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                        if aop_constraint is not None:
                                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                                            if not aop_constraint.valid:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                                        if crafter_id is not None:
                                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                            if relationship_track:
                                                                relationship_score = relationship_track.get_value()
                                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                    test_result = self._test_aop(aop)
                                                    if not test_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_test_aop', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if not self._satisfies_active_desire(aop):
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_satisfies_desire', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                                    if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_satisfies_desire', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                            if self._request.constraint is not None:
                                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                if aop_constraint is not None:
                                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                    if not aop_constraint.valid:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                if crafter_id is not None:
                                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                    if relationship_track:
                                                                        relationship_score = relationship_track.get_value()
                                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                            test_result = self._test_aop(aop)
                                                            if not test_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                    if duplicate_affordance_group != Tag.INVALID:
                                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                    if not interaction_result:
                                                                        if self._request.record_test_result is not None:
                                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                        while gsi_enabled_at_start:
                                                                            self._gsi_interactions.append(interaction_result)
                                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if self._request.constraint is not None:
                                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                        if aop_constraint is not None:
                                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                                            if not aop_constraint.valid:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                                        if crafter_id is not None:
                                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                            if relationship_track:
                                                                relationship_score = relationship_track.get_value()
                                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                    test_result = self._test_aop(aop)
                                                    if not test_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_test_aop', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_satisfies_desire', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                    if self._request.constraint is not None:
                                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                        if aop_constraint is not None:
                                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                                            if not aop_constraint.valid:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                                        if crafter_id is not None:
                                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                            if relationship_track:
                                                                relationship_score = relationship_track.get_value()
                                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                    test_result = self._test_aop(aop)
                                                    if not test_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_test_aop', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if self._request.constraint is not None:
                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                if aop_constraint is not None:
                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                    if not aop_constraint.valid:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                if crafter_id is not None:
                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                    if relationship_track:
                                        relationship_score = relationship_track.get_value()
                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                            test_result = self._test_aop(aop)
                            if not test_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_test_aop', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if self._request.skipped_affordance_list and aop.affordance in self._request.skipped_affordance_list:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, 'skipped_affordance_list', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Affordance in skipped_affordance_list'))
                            if not self._satisfies_active_desire(aop):
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_satisfies_desire', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                                    if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_satisfies_desire', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                            if self._request.constraint is not None:
                                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                if aop_constraint is not None:
                                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                    if not aop_constraint.valid:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                if crafter_id is not None:
                                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                    if relationship_track:
                                                                        relationship_score = relationship_track.get_value()
                                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                            test_result = self._test_aop(aop)
                                                            if not test_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                    if duplicate_affordance_group != Tag.INVALID:
                                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                    if not interaction_result:
                                                                        if self._request.record_test_result is not None:
                                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                        while gsi_enabled_at_start:
                                                                            self._gsi_interactions.append(interaction_result)
                                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if self._request.constraint is not None:
                                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                        if aop_constraint is not None:
                                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                                            if not aop_constraint.valid:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                                        if crafter_id is not None:
                                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                            if relationship_track:
                                                                relationship_score = relationship_track.get_value()
                                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                    test_result = self._test_aop(aop)
                                                    if not test_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_test_aop', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_satisfies_desire', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                    if self._request.constraint is not None:
                                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                        if aop_constraint is not None:
                                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                                            if not aop_constraint.valid:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                                        if crafter_id is not None:
                                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                            if relationship_track:
                                                                relationship_score = relationship_track.get_value()
                                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                    test_result = self._test_aop(aop)
                                                    if not test_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_test_aop', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if self._request.constraint is not None:
                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                if aop_constraint is not None:
                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                    if not aop_constraint.valid:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                if crafter_id is not None:
                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                    if relationship_track:
                                        relationship_score = relationship_track.get_value()
                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                            test_result = self._test_aop(aop)
                            if not test_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_test_aop', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if not self._satisfies_active_desire(aop):
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_satisfies_desire', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                            if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_satisfies_desire', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                    if self._request.constraint is not None:
                                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                        if aop_constraint is not None:
                                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                                            if not aop_constraint.valid:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                                        if crafter_id is not None:
                                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                            if relationship_track:
                                                                relationship_score = relationship_track.get_value()
                                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                    test_result = self._test_aop(aop)
                                                    if not test_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_test_aop', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if self._request.constraint is not None:
                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                if aop_constraint is not None:
                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                    if not aop_constraint.valid:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                if crafter_id is not None:
                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                    if relationship_track:
                                        relationship_score = relationship_track.get_value()
                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                            test_result = self._test_aop(aop)
                            if not test_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_test_aop', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_satisfies_desire', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                            if self._request.constraint is not None:
                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                if aop_constraint is not None:
                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                    if not aop_constraint.valid:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                if crafter_id is not None:
                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                    if relationship_track:
                                        relationship_score = relationship_track.get_value()
                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                            test_result = self._test_aop(aop)
                            if not test_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_test_aop', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if self._request.constraint is not None:
                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                        if aop_constraint is not None:
                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                            if not aop_constraint.valid:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                        crafter_id = obj.get_crafting_process().crafter_sim_id
                        if crafter_id is not None:
                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                            if relationship_track:
                                relationship_score = relationship_track.get_value()
                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                    test_result = self._test_aop(aop)
                    if not test_result:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_test_aop', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                    if duplicate_affordance_group != Tag.INVALID:
                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                    if not interaction_result:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(interaction_result)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
            if self._request.affordance_list and aop.affordance not in self._request.affordance_list:
                pass
            if aop.affordance.target_type == interactions.TargetType.ACTOR and self._sim is not obj:
                pass
            if self._valid_interactions[aop.affordance.scoring_priority].has_score_for_aop(aop):
                pass
            test_result = self._allow_autonomous(aop)
            if not test_result:
                while not self._GSI_IGNORES_NON_AUTONOMOUS_AFFORDANCES:
                    if self._request.record_test_result is not None:
                        self._request.record_test_result(aop, '_allow_autonomous', None)
                    if gsi_enabled_at_start:
                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason="aop doesn't advertise to autonomy."))
                    else:
                        if obj.check_affordance_for_suppression(self._sim, aop, False):
                            while self._request.record_test_result is not None:
                                self._request.record_test_result(aop, 'check_affordance_for_suppression', None)
                                if self._request.skipped_affordance_list and aop.affordance in self._request.skipped_affordance_list:
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, 'skipped_affordance_list', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Affordance in skipped_affordance_list'))
                                        if not self._satisfies_active_desire(aop):
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_satisfies_desire', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                                                if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_satisfies_desire', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                                        if self._request.constraint is not None:
                                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                            if aop_constraint is not None:
                                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                                if not aop_constraint.valid:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                            if crafter_id is not None:
                                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                                if relationship_track:
                                                                                    relationship_score = relationship_track.get_value()
                                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                        test_result = self._test_aop(aop)
                                                                        if not test_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                                if not interaction_result:
                                                                                    if self._request.record_test_result is not None:
                                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                                    while gsi_enabled_at_start:
                                                                                        self._gsi_interactions.append(interaction_result)
                                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if self._request.constraint is not None:
                                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                    if aop_constraint is not None:
                                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                        if not aop_constraint.valid:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                    if crafter_id is not None:
                                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                        if relationship_track:
                                                                            relationship_score = relationship_track.get_value()
                                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                test_result = self._test_aop(aop)
                                                                if not test_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_satisfies_desire', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                                if self._request.constraint is not None:
                                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                    if aop_constraint is not None:
                                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                        if not aop_constraint.valid:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                    if crafter_id is not None:
                                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                        if relationship_track:
                                                                            relationship_score = relationship_track.get_value()
                                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                test_result = self._test_aop(aop)
                                                                if not test_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if self._request.constraint is not None:
                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                            if aop_constraint is not None:
                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                if not aop_constraint.valid:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                            if crafter_id is not None:
                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                if relationship_track:
                                                    relationship_score = relationship_track.get_value()
                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                        test_result = self._test_aop(aop)
                                        if not test_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_test_aop', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if not self._satisfies_active_desire(aop):
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_satisfies_desire', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                                        if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_satisfies_desire', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                                if self._request.constraint is not None:
                                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                    if aop_constraint is not None:
                                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                        if not aop_constraint.valid:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                    if crafter_id is not None:
                                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                        if relationship_track:
                                                                            relationship_score = relationship_track.get_value()
                                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                test_result = self._test_aop(aop)
                                                                if not test_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if self._request.constraint is not None:
                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                            if aop_constraint is not None:
                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                if not aop_constraint.valid:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                            if crafter_id is not None:
                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                if relationship_track:
                                                    relationship_score = relationship_track.get_value()
                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                        test_result = self._test_aop(aop)
                                        if not test_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_test_aop', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_satisfies_desire', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                        if self._request.constraint is not None:
                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                            if aop_constraint is not None:
                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                if not aop_constraint.valid:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                            if crafter_id is not None:
                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                if relationship_track:
                                                    relationship_score = relationship_track.get_value()
                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                        test_result = self._test_aop(aop)
                                        if not test_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_test_aop', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if self._request.constraint is not None:
                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                    if aop_constraint is not None:
                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                        if not aop_constraint.valid:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                    if crafter_id is not None:
                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                        if relationship_track:
                                            relationship_score = relationship_track.get_value()
                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                test_result = self._test_aop(aop)
                                if not test_result:
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_test_aop', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                if duplicate_affordance_group != Tag.INVALID:
                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                if not interaction_result:
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(interaction_result)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                        if self._request.skipped_affordance_list and aop.affordance in self._request.skipped_affordance_list:
                            if self._request.record_test_result is not None:
                                self._request.record_test_result(aop, 'skipped_affordance_list', None)
                            while gsi_enabled_at_start:
                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Affordance in skipped_affordance_list'))
                                if not self._satisfies_active_desire(aop):
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_satisfies_desire', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                                        if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_satisfies_desire', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                                if self._request.constraint is not None:
                                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                    if aop_constraint is not None:
                                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                        if not aop_constraint.valid:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                    if crafter_id is not None:
                                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                        if relationship_track:
                                                                            relationship_score = relationship_track.get_value()
                                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                                test_result = self._test_aop(aop)
                                                                if not test_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                        if duplicate_affordance_group != Tag.INVALID:
                                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                        if not interaction_result:
                                                                            if self._request.record_test_result is not None:
                                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                            while gsi_enabled_at_start:
                                                                                self._gsi_interactions.append(interaction_result)
                                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if self._request.constraint is not None:
                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                            if aop_constraint is not None:
                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                if not aop_constraint.valid:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                            if crafter_id is not None:
                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                if relationship_track:
                                                    relationship_score = relationship_track.get_value()
                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                        test_result = self._test_aop(aop)
                                        if not test_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_test_aop', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_satisfies_desire', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                        if self._request.constraint is not None:
                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                            if aop_constraint is not None:
                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                if not aop_constraint.valid:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                            if crafter_id is not None:
                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                if relationship_track:
                                                    relationship_score = relationship_track.get_value()
                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                        test_result = self._test_aop(aop)
                                        if not test_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_test_aop', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if self._request.constraint is not None:
                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                    if aop_constraint is not None:
                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                        if not aop_constraint.valid:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                    if crafter_id is not None:
                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                        if relationship_track:
                                            relationship_score = relationship_track.get_value()
                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                test_result = self._test_aop(aop)
                                if not test_result:
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_test_aop', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                if duplicate_affordance_group != Tag.INVALID:
                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                if not interaction_result:
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(interaction_result)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                        if not self._satisfies_active_desire(aop):
                            if self._request.record_test_result is not None:
                                self._request.record_test_result(aop, '_satisfies_desire', None)
                            while gsi_enabled_at_start:
                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                                if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_satisfies_desire', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                        if self._request.constraint is not None:
                                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                            if aop_constraint is not None:
                                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                if not aop_constraint.valid:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                                            if crafter_id is not None:
                                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                if relationship_track:
                                                                    relationship_score = relationship_track.get_value()
                                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                        test_result = self._test_aop(aop)
                                                        if not test_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_test_aop', None)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                if duplicate_affordance_group != Tag.INVALID:
                                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                if not interaction_result:
                                                                    if self._request.record_test_result is not None:
                                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                    while gsi_enabled_at_start:
                                                                        self._gsi_interactions.append(interaction_result)
                                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                            if crafter_id is not None:
                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                if relationship_track:
                                                    relationship_score = relationship_track.get_value()
                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                        test_result = self._test_aop(aop)
                                        if not test_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_test_aop', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if self._request.constraint is not None:
                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                    if aop_constraint is not None:
                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                        if not aop_constraint.valid:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                    if crafter_id is not None:
                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                        if relationship_track:
                                            relationship_score = relationship_track.get_value()
                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                test_result = self._test_aop(aop)
                                if not test_result:
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_test_aop', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                if duplicate_affordance_group != Tag.INVALID:
                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                if not interaction_result:
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(interaction_result)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                        if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                            if self._request.record_test_result is not None:
                                self._request.record_test_result(aop, '_satisfies_desire', None)
                            while gsi_enabled_at_start:
                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                if self._request.constraint is not None:
                                    aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                    if aop_constraint is not None:
                                        aop_constraint = aop_constraint.intersect(self._request.constraint)
                                        if not aop_constraint.valid:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, 'invalid_constraint', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                                    if crafter_id is not None:
                                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                        if relationship_track:
                                                            relationship_score = relationship_track.get_value()
                                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                test_result = self._test_aop(aop)
                                                if not test_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_test_aop', None)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                        if duplicate_affordance_group != Tag.INVALID:
                                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                        if not interaction_result:
                                                            if self._request.record_test_result is not None:
                                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                            while gsi_enabled_at_start:
                                                                self._gsi_interactions.append(interaction_result)
                                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                    crafter_id = obj.get_crafting_process().crafter_sim_id
                                    if crafter_id is not None:
                                        relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                        if relationship_track:
                                            relationship_score = relationship_track.get_value()
                                            logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                            self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                test_result = self._test_aop(aop)
                                if not test_result:
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_test_aop', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                if duplicate_affordance_group != Tag.INVALID:
                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                if not interaction_result:
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(interaction_result)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                        if self._request.constraint is not None:
                            aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                            if aop_constraint is not None:
                                aop_constraint = aop_constraint.intersect(self._request.constraint)
                                if not aop_constraint.valid:
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, 'invalid_constraint', None)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                            crafter_id = obj.get_crafting_process().crafter_sim_id
                                            if crafter_id is not None:
                                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                if relationship_track:
                                                    relationship_score = relationship_track.get_value()
                                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                        test_result = self._test_aop(aop)
                                        if not test_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_test_aop', None)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                if duplicate_affordance_group != Tag.INVALID:
                                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                if not interaction_result:
                                                    if self._request.record_test_result is not None:
                                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                    while gsi_enabled_at_start:
                                                        self._gsi_interactions.append(interaction_result)
                                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                        if duplicate_affordance_group != Tag.INVALID:
                                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                        if not interaction_result:
                                            if self._request.record_test_result is not None:
                                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                            while gsi_enabled_at_start:
                                                self._gsi_interactions.append(interaction_result)
                                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                        if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                            crafter_id = obj.get_crafting_process().crafter_sim_id
                            if crafter_id is not None:
                                relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                if relationship_track:
                                    relationship_score = relationship_track.get_value()
                                    logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                    self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                        test_result = self._test_aop(aop)
                        if not test_result:
                            if self._request.record_test_result is not None:
                                self._request.record_test_result(aop, '_test_aop', None)
                            while gsi_enabled_at_start:
                                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                if duplicate_affordance_group != Tag.INVALID:
                                    self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                if not interaction_result:
                                    if self._request.record_test_result is not None:
                                        self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                    while gsi_enabled_at_start:
                                        self._gsi_interactions.append(interaction_result)
                                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                        duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                        if duplicate_affordance_group != Tag.INVALID:
                            self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                        (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                        if not interaction_result:
                            if self._request.record_test_result is not None:
                                self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                            while gsi_enabled_at_start:
                                self._gsi_interactions.append(interaction_result)
                                self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                        self._process_scored_interaction(aop, interaction, interaction_result, route_time)
            if obj.check_affordance_for_suppression(self._sim, aop, False):
                while self._request.record_test_result is not None:
                    self._request.record_test_result(aop, 'check_affordance_for_suppression', None)
                    if self._request.skipped_affordance_list and aop.affordance in self._request.skipped_affordance_list:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, 'skipped_affordance_list', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Affordance in skipped_affordance_list'))
                            if not self._satisfies_active_desire(aop):
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_satisfies_desire', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                                    if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_satisfies_desire', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                            if self._request.constraint is not None:
                                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                                if aop_constraint is not None:
                                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                                    if not aop_constraint.valid:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                                if crafter_id is not None:
                                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                                    if relationship_track:
                                                                        relationship_score = relationship_track.get_value()
                                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                            test_result = self._test_aop(aop)
                                                            if not test_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                                    if duplicate_affordance_group != Tag.INVALID:
                                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                                    if not interaction_result:
                                                                        if self._request.record_test_result is not None:
                                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                        while gsi_enabled_at_start:
                                                                            self._gsi_interactions.append(interaction_result)
                                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if self._request.constraint is not None:
                                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                        if aop_constraint is not None:
                                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                                            if not aop_constraint.valid:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                                        if crafter_id is not None:
                                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                            if relationship_track:
                                                                relationship_score = relationship_track.get_value()
                                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                    test_result = self._test_aop(aop)
                                                    if not test_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_test_aop', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_satisfies_desire', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                    if self._request.constraint is not None:
                                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                        if aop_constraint is not None:
                                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                                            if not aop_constraint.valid:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                                        if crafter_id is not None:
                                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                            if relationship_track:
                                                                relationship_score = relationship_track.get_value()
                                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                    test_result = self._test_aop(aop)
                                                    if not test_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_test_aop', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if self._request.constraint is not None:
                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                if aop_constraint is not None:
                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                    if not aop_constraint.valid:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                if crafter_id is not None:
                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                    if relationship_track:
                                        relationship_score = relationship_track.get_value()
                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                            test_result = self._test_aop(aop)
                            if not test_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_test_aop', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if not self._satisfies_active_desire(aop):
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_satisfies_desire', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                            if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_satisfies_desire', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                    if self._request.constraint is not None:
                                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                        if aop_constraint is not None:
                                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                                            if not aop_constraint.valid:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                                        if crafter_id is not None:
                                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                            if relationship_track:
                                                                relationship_score = relationship_track.get_value()
                                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                    test_result = self._test_aop(aop)
                                                    if not test_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_test_aop', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if self._request.constraint is not None:
                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                if aop_constraint is not None:
                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                    if not aop_constraint.valid:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                if crafter_id is not None:
                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                    if relationship_track:
                                        relationship_score = relationship_track.get_value()
                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                            test_result = self._test_aop(aop)
                            if not test_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_test_aop', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_satisfies_desire', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                            if self._request.constraint is not None:
                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                if aop_constraint is not None:
                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                    if not aop_constraint.valid:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                if crafter_id is not None:
                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                    if relationship_track:
                                        relationship_score = relationship_track.get_value()
                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                            test_result = self._test_aop(aop)
                            if not test_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_test_aop', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if self._request.constraint is not None:
                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                        if aop_constraint is not None:
                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                            if not aop_constraint.valid:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                        crafter_id = obj.get_crafting_process().crafter_sim_id
                        if crafter_id is not None:
                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                            if relationship_track:
                                relationship_score = relationship_track.get_value()
                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                    test_result = self._test_aop(aop)
                    if not test_result:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_test_aop', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                    if duplicate_affordance_group != Tag.INVALID:
                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                    if not interaction_result:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(interaction_result)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
            if self._request.skipped_affordance_list and aop.affordance in self._request.skipped_affordance_list:
                if self._request.record_test_result is not None:
                    self._request.record_test_result(aop, 'skipped_affordance_list', None)
                while gsi_enabled_at_start:
                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Affordance in skipped_affordance_list'))
                    if not self._satisfies_active_desire(aop):
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_satisfies_desire', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                            if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_satisfies_desire', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                                    if self._request.constraint is not None:
                                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                        if aop_constraint is not None:
                                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                                            if not aop_constraint.valid:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                                        if crafter_id is not None:
                                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                            if relationship_track:
                                                                relationship_score = relationship_track.get_value()
                                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                                    test_result = self._test_aop(aop)
                                                    if not test_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_test_aop', None)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                            if duplicate_affordance_group != Tag.INVALID:
                                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                            if not interaction_result:
                                                                if self._request.record_test_result is not None:
                                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                                while gsi_enabled_at_start:
                                                                    self._gsi_interactions.append(interaction_result)
                                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if self._request.constraint is not None:
                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                if aop_constraint is not None:
                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                    if not aop_constraint.valid:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                if crafter_id is not None:
                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                    if relationship_track:
                                        relationship_score = relationship_track.get_value()
                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                            test_result = self._test_aop(aop)
                            if not test_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_test_aop', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_satisfies_desire', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                            if self._request.constraint is not None:
                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                if aop_constraint is not None:
                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                    if not aop_constraint.valid:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                if crafter_id is not None:
                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                    if relationship_track:
                                        relationship_score = relationship_track.get_value()
                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                            test_result = self._test_aop(aop)
                            if not test_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_test_aop', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if self._request.constraint is not None:
                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                        if aop_constraint is not None:
                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                            if not aop_constraint.valid:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                        crafter_id = obj.get_crafting_process().crafter_sim_id
                        if crafter_id is not None:
                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                            if relationship_track:
                                relationship_score = relationship_track.get_value()
                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                    test_result = self._test_aop(aop)
                    if not test_result:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_test_aop', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                    if duplicate_affordance_group != Tag.INVALID:
                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                    if not interaction_result:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(interaction_result)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
            if not self._satisfies_active_desire(aop):
                if self._request.record_test_result is not None:
                    self._request.record_test_result(aop, '_satisfies_desire', None)
                while gsi_enabled_at_start:
                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed to satisfy relevant desires'))
                    if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_satisfies_desire', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                            if self._request.constraint is not None:
                                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                                if aop_constraint is not None:
                                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                                    if not aop_constraint.valid:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, 'invalid_constraint', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                                if crafter_id is not None:
                                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                                    if relationship_track:
                                                        relationship_score = relationship_track.get_value()
                                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                            test_result = self._test_aop(aop)
                                            if not test_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_test_aop', None)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                                    if duplicate_affordance_group != Tag.INVALID:
                                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                                    if not interaction_result:
                                                        if self._request.record_test_result is not None:
                                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                        while gsi_enabled_at_start:
                                                            self._gsi_interactions.append(interaction_result)
                                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                if crafter_id is not None:
                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                    if relationship_track:
                                        relationship_score = relationship_track.get_value()
                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                            test_result = self._test_aop(aop)
                            if not test_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_test_aop', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if self._request.constraint is not None:
                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                        if aop_constraint is not None:
                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                            if not aop_constraint.valid:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                        crafter_id = obj.get_crafting_process().crafter_sim_id
                        if crafter_id is not None:
                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                            if relationship_track:
                                relationship_score = relationship_track.get_value()
                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                    test_result = self._test_aop(aop)
                    if not test_result:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_test_aop', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                    if duplicate_affordance_group != Tag.INVALID:
                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                    if not interaction_result:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(interaction_result)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
            if self._request.skipped_static_commodities and self._satisfies_desire(self._request.skipped_static_commodities, aop):
                if self._request.record_test_result is not None:
                    self._request.record_test_result(aop, '_satisfies_desire', None)
                while gsi_enabled_at_start:
                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='AOP satisfies explicitly skipped commodity'))
                    if self._request.constraint is not None:
                        aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                        if aop_constraint is not None:
                            aop_constraint = aop_constraint.intersect(self._request.constraint)
                            if not aop_constraint.valid:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, 'invalid_constraint', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                        crafter_id = obj.get_crafting_process().crafter_sim_id
                                        if crafter_id is not None:
                                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                            if relationship_track:
                                                relationship_score = relationship_track.get_value()
                                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                                    test_result = self._test_aop(aop)
                                    if not test_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_test_aop', None)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                            if duplicate_affordance_group != Tag.INVALID:
                                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                            if not interaction_result:
                                                if self._request.record_test_result is not None:
                                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                                while gsi_enabled_at_start:
                                                    self._gsi_interactions.append(interaction_result)
                                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                        crafter_id = obj.get_crafting_process().crafter_sim_id
                        if crafter_id is not None:
                            relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                            if relationship_track:
                                relationship_score = relationship_track.get_value()
                                logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                    test_result = self._test_aop(aop)
                    if not test_result:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_test_aop', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                    if duplicate_affordance_group != Tag.INVALID:
                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                    if not interaction_result:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(interaction_result)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
            if self._request.constraint is not None:
                aop_constraint = aop.constraint_intersection(self._sim, target=obj, posture_state=None)
                if aop_constraint is not None:
                    aop_constraint = aop_constraint.intersect(self._request.constraint)
                    if not aop_constraint.valid:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, 'invalid_constraint', None)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.BEFORE_TESTS, self._actively_scored_motives, reason='Failed constraint intersection'))
                            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                                crafter_id = obj.get_crafting_process().crafter_sim_id
                                if crafter_id is not None:
                                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                                    if relationship_track:
                                        relationship_score = relationship_track.get_value()
                                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
                            test_result = self._test_aop(aop)
                            if not test_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_test_aop', None)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                                    if duplicate_affordance_group != Tag.INVALID:
                                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                                    if not interaction_result:
                                        if self._request.record_test_result is not None:
                                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                        while gsi_enabled_at_start:
                                            self._gsi_interactions.append(interaction_result)
                                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                            if duplicate_affordance_group != Tag.INVALID:
                                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                            if not interaction_result:
                                if self._request.record_test_result is not None:
                                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                                while gsi_enabled_at_start:
                                    self._gsi_interactions.append(interaction_result)
                                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
            if obj.has_component(objects.components.types.CRAFTING_COMPONENT):
                crafter_id = obj.get_crafting_process().crafter_sim_id
                if crafter_id is not None:
                    relationship_track = self._sim.sim_info.relationship_tracker.get_relationship_track(crafter_id)
                    if relationship_track:
                        relationship_score = relationship_track.get_value()
                        logger.assert_log(relationship_track.relationship_obj_prefence_curve is not None, 'Error: Tuning for RelationshipTrack: {}, Relationship Object Preference Curve is not tuned.'.format(type(relationship_track).__name__))
                        self._relationship_object_value = relationship_track.relationship_obj_prefence_curve.get(relationship_score)
            test_result = self._test_aop(aop)
            if not test_result:
                if self._request.record_test_result is not None:
                    self._request.record_test_result(aop, '_test_aop', None)
                while gsi_enabled_at_start:
                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason))
                    duplicate_affordance_group = aop.affordance.duplicate_affordance_group
                    if duplicate_affordance_group != Tag.INVALID:
                        self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
                    (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
                    if not interaction_result:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                        while gsi_enabled_at_start:
                            self._gsi_interactions.append(interaction_result)
                            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
            duplicate_affordance_group = aop.affordance.duplicate_affordance_group
            if duplicate_affordance_group != Tag.INVALID:
                self._limited_affordances[duplicate_affordance_group].append(_DeferredAopData(aop, inventory_type))
            (interaction_result, interaction, route_time) = self._create_and_score_interaction(aop, inventory_type=inventory_type)
            if not interaction_result:
                if self._request.record_test_result is not None:
                    self._request.record_test_result(aop, '_create_and_score_interaction', interaction_result)
                while gsi_enabled_at_start:
                    self._gsi_interactions.append(interaction_result)
                    self._process_scored_interaction(aop, interaction, interaction_result, route_time)
            self._process_scored_interaction(aop, interaction, interaction_result, route_time)
        return ObjectResult.Success(obj, relevant_desires=self._actively_scored_motives)

    def _create_and_score_interaction(self, aop, inventory_type=None):
        execute_result = aop.interaction_factory(self._request.context)
        if not execute_result:
            return (InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason='Failed to execute aop!'), None, 0)
        interaction = execute_result.interaction
        self._request.on_interaction_created(interaction)
        test_result = self._is_valid_interaction(interaction)
        if not test_result:
            if self._request.record_test_result is not None:
                self._request.record_test_result(aop, '_is_valid_aop', test_result)
            return (InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_TESTS, self._actively_scored_motives, reason=test_result.reason), None, 0)
        posture_result_tuple = None
        if inventory_type is not None:
            posture_result_tuple = self._inventory_posture_score_cache.get(inventory_type)
        if g_affordance_times is not None:
            affordance = interaction.affordance
            affordance_name = affordance.__name__
            if affordance_name in g_affordance_times:
                (rt_count, rt_total_time) = g_affordance_times[affordance_name]
            else:
                (rt_count, rt_total_time) = (0, 0.0)
            rt_start = time.time()
        posture_result_tuple = self._calculate_route_time_and_opportunity(interaction)
        if g_affordance_times is not None:
            rt_end = time.time()
            rt_delta = rt_end - rt_start
            g_affordance_times[affordance_name] = (rt_count + 1, rt_total_time + rt_delta)
        if posture_result_tuple is None and inventory_type is not None:
            self._inventory_posture_score_cache[inventory_type] = posture_result_tuple
        logger.assert_raise(posture_result_tuple is not None, "Couldn't get posture score for {}".format(aop))
        (route_time, must_change_posture, included_sis) = posture_result_tuple
        if route_time is None:
            reason = 'Failed to plan a path that would satisfy all required SIs!'
            return (InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_POSTURE_SEARCH, self._actively_scored_motives, reason=reason), None, 0)
        if must_change_posture and not self._request.is_script_request:
            for si in self._sim.si_state.all_guaranteed_si_gen(priority=self._request.context.priority, group_id=interaction.group_id):
                if not self._sim.posture_state.is_source_interaction(si):
                    if not si.apply_autonomous_posture_change_cost:
                        pass
                    return (InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_POSTURE_SEARCH, self._actively_scored_motives, reason="Can't change posture while in guaranteed SI!"), None, 0)
        (affordance_score, multitask_percentage) = self._calculate_interaction_score(interaction, route_time, must_change_posture, included_sis)
        return (InteractionResult.Success(interaction, self._actively_scored_motives, score=affordance_score, multitask_percentage=multitask_percentage), interaction, route_time)

    def _calculate_interaction_score(self, interaction, route_time, must_change_posture, included_sis):
        gsi_commodity_scores = []
        affordance = interaction.affordance
        interaction_score = 0
        approximate_duration = affordance.approximate_duration
        efficiency = approximate_duration/(approximate_duration + route_time)
        autonomy_scoring_preference = self._get_autonomy_scoring_preference(interaction)
        no_stat_ops = True
        for stat_op_list in self._applicable_stat_ops_gen(interaction, include_hidden_false_ads=True, gsi_commodity_scores=gsi_commodity_scores):
            no_stat_ops = False
            fulfillment_rate = stat_op_list.get_fulfillment_rate(interaction)
            already_solving_motive_multiplier = self.FULL_AUTONOMY_MULTIPLIER_FOR_SOLVING_THE_SAME_STAT if stat_op_list.stat in self._motives_being_solved else 1
            object_stat_use_multiplier = self._calculate_object_stat_use_multiplier(interaction.target, stat_op_list.stat, fulfillment_rate >= 0)
            modified_desire = self._motive_scores.get(stat_op_list.stat, stat_op_list.stat.autonomous_desire)
            op_score = fulfillment_rate*object_stat_use_multiplier*already_solving_motive_multiplier*efficiency*autonomy_scoring_preference*modified_desire*stat_op_list.stat.autonomy_weight
            interaction_score += op_score
            commodity_value = stat_op_list.get_value()
            gsi_commodity_scores.append(InteractionCommodityScore(op_score, stat_op_list.stat, advertise=True, commodity_value=commodity_value, interval=commodity_value/fulfillment_rate if fulfillment_rate else None, fulfillment_rate=fulfillment_rate, object_stat_use_multiplier=object_stat_use_multiplier, already_solving_motive_multiplier=already_solving_motive_multiplier, modified_desire=modified_desire))
        for static_commodity_data in interaction.affordance.static_commodities_data:
            static_commodity = static_commodity_data.static_commodity
            if not static_commodity.is_scored:
                gsi_commodity_scores.append(InteractionCommodityScore(0, static_commodity, advertise=False))
            if static_commodity not in self._motive_scores:
                gsi_commodity_scores.append(InteractionCommodityScore(0, static_commodity, advertise=True))
            no_stat_ops = False
            op_score = static_commodity.ad_data*static_commodity_data.desire*efficiency*autonomy_scoring_preference
            interaction_score += op_score
            gsi_commodity_scores.append(InteractionCommodityScore(op_score, static_commodity, advertise=True, commodity_value=static_commodity_data.desire, interval=1, fulfillment_rate=static_commodity_data.desire, modified_desire=static_commodity.ad_data))
        if no_stat_ops:
            interaction_score = efficiency
            gsi_commodity_scores.append(InteractionCommodityScore(score=efficiency, commodity=None, advertise=True))
        interaction_params = interaction.interaction_parameters
        join_target_ref = interaction_params.get('join_target_ref')
        if join_target_ref is not None:
            target_sim = join_target_ref()
        else:
            target_sim = interaction.target if interaction.target is not None and interaction.target.is_sim else None
        rel_utility_score = 1
        group_utility_score = 1
        buff_utility_score = 1
        if affordance.relationship_scoring and target_sim is not None:
            final_rel_score = 0
            final_rel_count = 0
            rel_tracker = self._sim.sim_info.relationship_tracker
            target_sims = set((target_sim,))
            for social_group in target_sim.get_groups_for_sim_gen():
                for sim in social_group:
                    target_sims.add(sim)
            for sim in target_sims:
                aggregate_track_score = [track.autonomous_desire for track in rel_tracker.relationship_tracks_gen(sim.id) if track.is_scored]
                track_score = sum(aggregate_track_score)/len(aggregate_track_score) if aggregate_track_score else 1
                bit_score = 1
                for bit in rel_tracker.get_all_bits(sim.id):
                    bit_score *= bit.autonomy_multiplier
                rel_score = track_score*bit_score
                final_rel_score += rel_score
                final_rel_count += 1
            rel_utility_score = final_rel_score/final_rel_count if final_rel_count > 0 else 1
            target_main_group = target_sim.get_main_group()
            if target_main_group:
                group_utility_score = affordance.get_affordance_weight_from_group_size(len(target_main_group))
                for group_member in target_main_group:
                    if group_member is target_sim:
                        pass
                    while group_member.is_player_active():
                        group_utility_score *= AutonomyMode.FULL_AUTONOMY_DESIRE_TO_JOIN_PLAYER_PARTIES
                        break
            relationship_score_multipliers_for_buffs = self._sim.sim_info.get_relationship_score_multiplier_for_buff_on_target()
            if relationship_score_multipliers_for_buffs:
                while True:
                    for (buff_type, multiplier) in relationship_score_multipliers_for_buffs.items():
                        while target_sim.has_buff(buff_type):
                            buff_utility_score *= multiplier
        interaction_score *= rel_utility_score*group_utility_score*buff_utility_score
        interaction_score *= 1 + self._relationship_object_value
        if interaction.target and not interaction.target.is_on_active_lot() and self._sim.is_on_active_lot(tolerance=self._sim.get_off_lot_autonomy_tolerance()):
            interaction_score *= self.OFF_LOT_OBJECT_SCORE_MULTIPLIER
        total_opportunity_cost = 0
        canceled_si_opportunity_costs = {}
        canceled_sis = [si for si in self._sim.si_state if si not in included_sis]
        if self._request.apply_opportunity_cost:
            affordance_is_active_on_actor = self._sim.si_state.is_affordance_active_for_actor(affordance)
            for canceled_si in canceled_sis:
                if not canceled_si.canceling_incurs_opportunity_cost:
                    pass
                if affordance_is_active_on_actor and canceled_si.autonomy_can_overwrite_similar_affordance:
                    pass
                if canceled_si.is_finishing:
                    pass
                canceled_si_score = self._calculate_stat_op_score_for_running_si(canceled_si)
                final_si_opportunity_cost = canceled_si_score*canceled_si.opportunity_cost_multiplier
                canceled_si_opportunity_costs[canceled_si] = final_si_opportunity_cost
                total_opportunity_cost += final_si_opportunity_cost
            if must_change_posture and interaction.apply_autonomous_posture_change_cost and self._sim.si_state.has_visible_si():
                total_opportunity_cost *= self.POSTURE_CHANGE_OPPORTUNITY_COST_MULTIPLIER
            interaction_score -= total_opportunity_cost
        remaining_sis_score = self._score_current_si_state(skip_sis=canceled_sis, gsi_commodity_scores=gsi_commodity_scores)
        interaction_score += remaining_sis_score
        attention_cost = 0
        attention_cost_scores = {}
        if interaction.target is None or not interaction.target.is_sim:
            attention_cost = self._calculate_attention_cost_for_current_si_state(self._sim, skip_sis=canceled_sis, attention_cost_scores=attention_cost_scores)
        else:
            actor_attention_cost_scores = {}
            target_attention_cost_scores = {}
            actor_cost = self._calculate_attention_cost_for_current_si_state(self._sim, skip_sis=canceled_sis, attention_cost_scores=actor_attention_cost_scores)
            target_cost = self._calculate_attention_cost_for_current_si_state(interaction.target, attention_cost_scores=target_attention_cost_scores)
            if actor_cost <= target_cost:
                attention_cost = actor_cost
                attention_cost_scores.update(actor_attention_cost_scores)
            else:
                attention_cost = target_cost
                attention_cost_scores.update(target_attention_cost_scores)
        interaction_attention_cost = interaction.get_attention_cost()
        attention_cost += interaction_attention_cost
        attention_cost_scores[interaction] = (interaction_attention_cost, True)
        base_multitasking_percentage = self.FULL_AUTONOMY_ATTENTION_COST.get(attention_cost)
        bonus_multitasking_percentage = 0
        attention_cost_bonus_scores = {}
        if not no_stat_ops:
            for stat_op_list in self._applicable_stat_ops_gen(interaction):
                modified_desire = self._motive_scores.get(stat_op_list.stat, stat_op_list.stat.autonomous_desire)
                bonus = self.FULL_AUTONOMY_MULTITASKING_PERCENTAGE_BONUS.get(modified_desire)
                bonus_multitasking_percentage += bonus
                attention_cost_bonus_scores[stat_op_list.stat] = (modified_desire, bonus)
        penalty_multitasking_percentage = 0
        attention_cost_penalty_scores = {}
        for si in included_sis:
            for stat_op_list in self._applicable_stat_ops_gen(si):
                modified_desire = self._motive_scores.get(stat_op_list.stat, stat_op_list.stat.autonomous_desire)
                penalty = self.FULL_AUTONOMY_MULTITASKING_PERCENTAGE_BONUS.get(modified_desire)
                penalty_multitasking_percentage += penalty
                attention_cost_penalty_scores[stat_op_list.stat] = (modified_desire, penalty)
        final_multitasking_percentage = base_multitasking_percentage + bonus_multitasking_percentage - penalty_multitasking_percentage
        final_score = interaction_score
        if final_score <= self._MINIMUM_SCORE:
            final_score = 0
        return (InteractionScore(final_score, interaction, gsi_commodity_scores, efficiency, approximate_duration, autonomy_scoring_preference, rel_utility_score, self._relationship_object_value, group_utility_score, opportunity_costs=canceled_si_opportunity_costs, must_change_posture=must_change_posture, base_multitasking_percentage=base_multitasking_percentage, bonus_multitasking_percentage=bonus_multitasking_percentage, penalty_multitasking_percentage=penalty_multitasking_percentage, attention_cost_scores=attention_cost_scores, attention_cost_bonus_scores=attention_cost_bonus_scores, attention_cost_penalty_scores=attention_cost_penalty_scores), final_multitasking_percentage)

    def _process_scored_interaction(self, aop, interaction, interaction_result, route_time):
        gsi_enabled_at_start = gsi_handlers.autonomy_handlers.archiver.enabled
        if not self._has_available_part(interaction):
            if self._request.record_test_result is not None:
                self._request.record_test_result(aop, '_has_available_part', None)
            if gsi_enabled_at_start:
                self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_SCORING, self._actively_scored_motives, reason="Object doesn't have an available part"))
            return False
        interaction_to_shutdown = None
        invalidate_interaction = True
        try:
            if aop.target.parts is None and (interaction.target is None or interaction.target.parts is None):
                basic_reserve = interaction.basic_reserve_object
                if basic_reserve is not None:
                    handler = basic_reserve(self._sim, interaction)
                    if not handler.may_reserve():
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, '_is_available', None)
                        if gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_SCORING, self._actively_scored_motives, reason='Interaction cannot reserve object.'))
                        interaction_to_shutdown = interaction
                        return False
            interaction_score = interaction_result.score
            scored_interaction_data = ScoredInteractionData(interaction_score, route_time, interaction_result.multitask_percentage, interaction)
            context = self._request.context
            if context.source == context.SOURCE_AUTONOMY and not self._request.consider_scores_of_zero and interaction_score <= 0:
                if self._request.record_test_result is not None:
                    self._request.record_test_result(aop, 'score_below_zero', None)
                if gsi_enabled_at_start:
                    self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_SCORING, self._actively_scored_motives, reason='Scored below zero ({})'.format(interaction_score)))
                interaction_to_shutdown = interaction
                return False
            if not interaction.use_best_scoring_aop:
                if interaction.affordance not in self._request.similar_aop_cache:
                    self._request.similar_aop_cache[interaction.affordance] = []
                self._request.similar_aop_cache[interaction.affordance].append(scored_interaction_data)
                invalidate_interaction = False
            valid_interactions_at_priority = self._valid_interactions[aop.affordance.scoring_priority]
            if aop.affordance in valid_interactions_at_priority:
                scored_interaction_data_to_compare = valid_interactions_at_priority[aop.affordance]
                replace_without_testing = False
                autonomy_preference = aop.affordance.autonomy_preference
                if autonomy_preference is not None and not autonomy_preference.preference.is_scoring:
                    tag = autonomy_preference.preference.tag
                    if self._sim.is_object_use_preferred(tag, scored_interaction_data_to_compare.interaction.target):
                        interaction_to_shutdown = interaction
                        return False
                    if self._sim.is_object_use_preferred(tag, aop.target):
                        replace_without_testing = True
                if not replace_without_testing:
                    if interaction_score < scored_interaction_data_to_compare.score:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, 'score_below_similar_aop', None)
                        if gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_SCORING, self._actively_scored_motives, reason='Score <= another affordance that has been scored ({} < {})'.format(interaction_score, scored_interaction_data_to_compare.score)))
                        interaction_to_shutdown = interaction
                        return False
                    if interaction_score == 0 and interaction_score == scored_interaction_data_to_compare.score:
                        if self._request.record_test_result is not None:
                            self._request.record_test_result(aop, 'zero_scoring_aop_is_further_away', None)
                        if gsi_enabled_at_start:
                            self._gsi_interactions.append(InteractionResult.Failure(aop, self._AutonomyStageLabel.AFTER_SCORING, self._actively_scored_motives, reason='Score == 0, but is further away than another affordance that has been scored ({} further than {})'.format(route_time, scored_interaction_data_to_compare.route_time)))
                        interaction_to_shutdown = interaction
                        return False
            logger.assert_log(self._is_valid_interaction(interaction), '_is_valid_aop() failed even though it should have succeeded earlier in the stack.')
            valid_interactions_at_priority.add(scored_interaction_data)
            self._found_valid_interaction = True
            while gsi_enabled_at_start:
                self._gsi_interactions.append(interaction_result)
        finally:
            if invalidate_interaction and interaction_to_shutdown is not None:
                interaction_to_shutdown.invalidate()
        return True

    def _calculate_stat_op_score_for_running_si(self, si):
        final_op_score = 0
        for stat_op_list in self._applicable_stat_ops_gen(si):
            stat_inst = self._sim.get_tracker(stat_op_list.stat).get_statistic(stat_op_list.stat, False)
            if not stat_inst:
                pass
            commodity_score = stat_op_list.get_fulfillment_rate(si)
            autonomy_scoring_preference = self._get_autonomy_scoring_preference(si)
            motive_score = self._motive_scores.get(stat_op_list.stat, stat_inst.autonomous_desire)
            op_score = commodity_score*autonomy_scoring_preference*motive_score*stat_inst.autonomy_weight
            final_op_score += op_score
        for static_commodity_data in si.affordance.static_commodities_data:
            static_commodity = static_commodity_data.static_commodity
            if not static_commodity.is_scored:
                pass
            if static_commodity not in self._motive_scores:
                pass
            final_op_score += static_commodity.ad_data*static_commodity_data.desire
        return final_op_score

    def _applicable_stat_ops_gen(self, interaction, include_hidden_false_ads=False, gsi_commodity_scores=None):
        for stat_op_list in interaction.affordance.autonomy_ads_gen(target=interaction.target, include_hidden_false_ads=include_hidden_false_ads):
            if not stat_op_list.stat.add_if_not_in_tracker and stat_op_list.stat not in self._motive_scores:
                while gsi_commodity_scores is not None:
                    gsi_commodity_scores.append(InteractionCommodityScore(0, stat_op_list.stat, advertise=False))
                    yield stat_op_list
            yield stat_op_list

    @staticmethod
    def _get_autonomy_scoring_preference(interaction):
        autonomy_preference = interaction.affordance.autonomy_preference
        if autonomy_preference is not None:
            preference = autonomy_preference.preference
            if preference.is_scoring and interaction.sim.is_object_scoring_preferred(preference.tag, interaction.target):
                return preference.autonomy_score
        return 1.0

    def _get_all_motives_currently_being_solved(self):
        motive_set = set()
        for si in self._sim.si_state:
            motive_set |= set([stat_op_list.stat for stat_op_list in self._applicable_stat_ops_gen(si)])
        return frozenset(motive_set)

    def _get_motives_to_score(self, stats=DEFAULT):
        motives_to_score = []
        motives_not_yet_scored = []
        if not self._request.has_commodities and not self._request.affordance_list:
            if stats is DEFAULT:
                stats = [stat.stat_type for stat in self._sim.scored_stats_gen()]
                if not stats:
                    logger.debug('No scorable stats on Sim: {}', self._request.sim)

                def _get_stat_score(stat_type):
                    scored_stat = self._motive_scores.get(stat_type)
                    if scored_stat is None:
                        scored_stat = ScoredStatistic(stat_type, self._sim)
                        self._motive_scores[stat_type] = scored_stat
                    return scored_stat

                stats.sort(key=_get_stat_score, reverse=True)
            if not stats:
                return ((), ())
            variance_score = self._motive_scores[stats[0]]*AutonomyMode.FULL_AUTONOMY_STATISTIC_SCORE_VARIANCE
            motives_to_score = set({stat.stat_type for stat in itertools.takewhile(lambda desire: self._motive_scores[desire] >= variance_score, stats)})
            motives_not_yet_scored = stats[len(motives_to_score):]
        elif self._request.has_commodities:
            motives_to_score = set({stat.stat_type for stat in self._request.all_commodities})
        return (motives_to_score, motives_not_yet_scored)

    def _calculate_object_stat_use_multiplier(self, game_object, stat_type, fulfillment_rate_is_increasing) -> float:
        if game_object is None:
            return 1
        final_multiplier = 1
        for autonomy_mofifier in game_object.autonomy_modifiers:
            if not autonomy_mofifier.statistic_multipliers:
                pass
            stat_use_multiplier = autonomy_mofifier.statistic_multipliers.get(stat_type)
            while stat_use_multiplier is not None:
                if stat_use_multiplier.apply_direction == StatisticChangeDirection.BOTH or fulfillment_rate_is_increasing and stat_use_multiplier.apply_direction == StatisticChangeDirection.INCREASE or not fulfillment_rate_is_increasing and stat_use_multiplier.apply_direction == StatisticChangeDirection.DECREASE:
                    final_multiplier *= stat_use_multiplier.multiplier
        return final_multiplier

    def _score_current_si_state(self, skip_sis=None, gsi_commodity_scores=None) -> float:
        base_score = 0
        for si in self._sim.si_state:
            if skip_sis is not None and si in skip_sis:
                pass
            base_score += self._calculate_stat_op_score_for_running_si(si)
        attention_cost = self._calculate_attention_cost_for_current_si_state(self._sim, skip_sis=skip_sis)
        normalized_attention_cost = self.FULL_AUTONOMY_ATTENTION_COST.get(attention_cost)
        final_score = base_score*normalized_attention_cost
        return final_score

    def _calculate_attention_cost_for_current_si_state(self, sim, skip_sis=None, attention_cost_scores=None):
        total_attention_cost = 0
        for si in sim.si_state:
            if not si.visible:
                pass
            if si.is_finishing:
                pass
            if skip_sis is not None and si in skip_sis:
                pass
            attention_cost = si.get_attention_cost()
            if attention_cost_scores is not None:
                attention_cost_scores[si] = (attention_cost, sim is self._sim)
            total_attention_cost += attention_cost
        return total_attention_cost

    def _get_aop_from_inventory(self, original_aop):
        inventory_component = original_aop.target.inventory_component
        if inventory_component is None:
            return
        if not inventory_component.should_score_contained_objects_for_autonomy:
            return
        for inventory_obj in inventory_component.get_items_for_autonomy_gen(motives=self._actively_scored_motives):
            potential_interactions = list(inventory_obj.potential_interactions(self._request.context, **self._request.kwargs))
            for aop in potential_interactions:
                for entry in original_aop.affordance.continuation:
                    while aop.affordance is entry.affordance:
                        return aop

    @classmethod
    def _test_pending_interactions(cls, sim):
        for interaction in sim.queue:
            if interaction is None:
                logger.error('interaction queue iterator returned None in FullAutonomy::_test_pending_interactions()')
            if interaction.pipeline_progress >= interactions.PipelineProgress.RUNNING:
                if interaction.disallows_full_autonomy(AutonomyMode._disable_autonomous_multitasking_if_user_directed_override):
                    return TestResult(False, 'None - {} in queue is disallowing autonomous multitasking.', interaction)
                    if not (interaction.source == InteractionContext.SOURCE_SOCIAL_ADJUSTMENT or interaction.source == InteractionContext.SOURCE_BODY_CANCEL_AOP):
                        if interaction.source == InteractionContext.SOURCE_GET_COMFORTABLE:
                            pass
                        return TestResult(False, 'None - {} is pending.', interaction)
            if not (interaction.source == InteractionContext.SOURCE_SOCIAL_ADJUSTMENT or interaction.source == InteractionContext.SOURCE_BODY_CANCEL_AOP):
                if interaction.source == InteractionContext.SOURCE_GET_COMFORTABLE:
                    pass
                return TestResult(False, 'None - {} is pending.', interaction)
        for interaction in tuple(sim.si_state):
            while interaction.disallows_full_autonomy(AutonomyMode._disable_autonomous_multitasking_if_user_directed_override):
                return TestResult(False, 'None - {} in si_state is disallowing autonomous multitasking.', interaction)
        return TestResult.TRUE

class _MixerProviderType(enum.Int, export=False):
    __qualname__ = '_MixerProviderType'
    INVALID = 0
    SI = 1
    BUFF = 2

class _MixerProvider:
    __qualname__ = '_MixerProvider'

    def __init__(self, mixer_provider):
        self._mixer_provider = mixer_provider
        self._type = _MixerProviderType.INVALID
        if isinstance(mixer_provider, interactions.base.super_interaction.SuperInteraction):
            self._type = _MixerProviderType.SI
        elif isinstance(mixer_provider, buffs.buff.Buff):
            self._type = _MixerProviderType.BUFF
        else:
            logger.error('Unknown type in _MixerProvider constructor', owner='rez')

    def __str__(self):
        return str(self._mixer_provider)

    @property
    def is_social(self):
        if self._type == _MixerProviderType.SI:
            return self._mixer_provider.is_social
        return False

    @property
    def target_string(self):
        return str(getattr(self._mixer_provider, 'target', 'None'))

    def get_scored_commodity(self, motive_scores):
        if self._type == _MixerProviderType.SI:
            best_score = None
            best_stat_type = None
            for stat_type in self._mixer_provider.commodity_flags:
                score = motive_scores.get(stat_type)
                while score is not None and (best_score is None or score.score > best_score):
                    best_score = score.score
                    best_stat_type = stat_type
            return best_stat_type
        if self._type == _MixerProviderType.BUFF:
            if self._mixer_provider.interactions.scored_commodity:
                return self._mixer_provider.interactions.scored_commodity
            return
        logger.error('Unknown type in _MixerProvider.get_commodity_score()', owner='rez')
        return

    def get_subaction_weight(self):
        if self._type == _MixerProviderType.SI:
            return self._mixer_provider.subaction_selection_weight
        if self._type == _MixerProviderType.BUFF:
            return self._mixer_provider.interactions.weight
        logger.error('Unknown type in _MixerProvider.get_subaction_weight()', owner='rez')
        return 0

    def get_mixers(self, request):
        mixer_aops = None
        if self._type == _MixerProviderType.SI:
            potential_targets = self._mixer_provider.get_potential_mixer_targets()
            mixer_aops = autonomy.content_sets.generate_content_set(request.sim, self._mixer_provider.super_affordance, self._mixer_provider, request.context, potential_targets=potential_targets, push_super_on_prepare=request.push_super_on_prepare)
        elif self._type == _MixerProviderType.BUFF:
            source_interaction = request.sim.posture.source_interaction
            if source_interaction:
                potential_targets = source_interaction.get_potential_mixer_targets()
                mixer_aop_dict = autonomy.content_sets.get_buff_aops(request.sim, self._mixer_provider, source_interaction, request.context, potential_targets=potential_targets)
                mixer_aops = []
                while True:
                    for (_, scored_aop_list) in mixer_aop_dict.items():
                        for scored_aop in scored_aop_list:
                            mixer_aops.append(scored_aop)
        else:
            logger.error('Unknown type in _MixerProvider.get_mixers()', owner='rez')
            return
        return mixer_aops

class ObjectResult:
    __qualname__ = 'ObjectResult'

    class Success(collections.namedtuple('_ObjectResult_Success', ['obj', 'relevant_desires'])):
        __qualname__ = 'ObjectResult.Success'

        def __bool__(self):
            return True

        def __str__(self):
            return 'Not skipped'

    class Failure(collections.namedtuple('_ObjectResult_Failure', ['obj', 'relevant_desires', 'reason'])):
        __qualname__ = 'ObjectResult.Failure'

        def __bool__(self):
            return False

        def __str__(self):
            return 'Skipped because {}'.format(self.reason)

class _InteractionScore(float):
    __qualname__ = '_InteractionScore'

    def __new__(cls, score, *args, **kwargs):
        return float.__new__(cls, score)

    def __init__(self, score, interaction, commodity_scores=None, efficiency=None, duration=None, autonomy_scoring_preference=None, rel_utility_score=None, relationship_object_value=None, party_score=None, opportunity_costs=None, must_change_posture=None, base_multitasking_percentage=None, bonus_multitasking_percentage=None, penalty_multitasking_percentage=None, attention_cost_scores=None, attention_cost_bonus_scores=None, attention_cost_penalty_scores=None):
        self.interaction = interaction
        self.opportunity_costs = opportunity_costs
        self.commodity_scores = commodity_scores
        self.efficiency = None if efficiency is None else float(efficiency)
        self.duration = None if duration is None else float(duration)
        self.autonomy_scoring_preference = None if autonomy_scoring_preference is None else float(autonomy_scoring_preference)
        self.rel_utility_score = None if rel_utility_score is None else float(rel_utility_score)
        self.relationship_object_value = None if relationship_object_value is None else float(relationship_object_value)
        self.party_score = None if party_score is None else float(party_score)
        self.must_change_posture = must_change_posture
        self.base_multitasking_percentage = base_multitasking_percentage
        self.bonus_multitasking_percentage = bonus_multitasking_percentage
        self.penalty_multitasking_percentage = penalty_multitasking_percentage
        self.attention_cost_scores = attention_cost_scores
        self.attention_cost_bonus_scores = attention_cost_bonus_scores
        self.attention_cost_penalty_scores = attention_cost_penalty_scores

    @property
    def details(self):
        return self.__str__()

    def __str__(self):
        commodity_score_str = '\n'.join(map(str, self.commodity_scores))
        opportunity_costs_str = '\n'.join('        {si.super_affordance.__name__} on {si.target}:\n            Cost: {cost}'.format(si=si, cost=cost) for (si, cost) in self.opportunity_costs.items()) if self.opportunity_costs else '        None'
        commodity_score_sum = ' + '.join(['({score.modified_desire} * {score.commodity_value} / {score.interval})'.format(score=com_score) for com_score in self.commodity_scores]) if self.commodity_scores else '0'
        efficiency_details = ' = {duration} / ({duration} + {route_time})'.format(duration=self.duration, route_time=self.duration/self.efficiency - self.duration) if self.duration is not None and self.efficiency is not None else ''
        change_posture_cost = AutonomyMode.POSTURE_CHANGE_OPPORTUNITY_COST_MULTIPLIER if self.must_change_posture else 1
        change_posture_cost_str = '{} -> {}'.format(self.must_change_posture, change_posture_cost)
        total_opportunity_cost = sum(self.opportunity_costs.values())*change_posture_cost
        base_multitasking_percentage = str(self.base_multitasking_percentage) if self.base_multitasking_percentage is not None else 'None'
        bonus_multitasking_percentage = str(self.bonus_multitasking_percentage) if self.bonus_multitasking_percentage is not None else 'None'
        penalty_multitasking_percentage = str(self.penalty_multitasking_percentage) if self.penalty_multitasking_percentage is not None else 'None'
        final_multitasking_percentage = str(self.base_multitasking_percentage + self.bonus_multitasking_percentage - self.penalty_multitasking_percentage) if self.base_multitasking_percentage is not None and self.bonus_multitasking_percentage is not None and self.penalty_multitasking_percentage is not None else 'None'
        attention_cost_scores_str = '\n'.join('        {target_prefix}{si.super_affordance.__name__} on {si.target}:\n            Base Attention Cost: {attention}'.format(si=si, attention=attention_sim_pair[0], target_prefix='(target) ' if not attention_sim_pair[1] else '') for (si, attention_sim_pair) in self.attention_cost_scores.items()) if self.attention_cost_scores else '            None'
        attention_cost_bonus_scores_str = '\n'.join('        {stat_type.__name__}:\n            Modified Desire: {modified_desire}\n            Attention Bonus: {attention_bonus}'.format(stat_type=stat_type, modified_desire=float(attention_score_tuple[0]), attention_bonus=attention_score_tuple[1]) for (stat_type, attention_score_tuple) in self.attention_cost_bonus_scores.items()) if self.attention_cost_bonus_scores else '            None'
        attention_cost_penalty_scores_str = '\n'.join('        {stat_type.__name__}:\n            Modified Desire: {modified_desire}\n            Attention Penalty: {attention_penalty}'.format(stat_type=stat_type, modified_desire=float(attention_score_tuple[0]), attention_penalty=attention_score_tuple[1]) for (stat_type, attention_score_tuple) in self.attention_cost_penalty_scores.items()) if self.attention_cost_penalty_scores else '            None'
        return 'TLDR: {self:.8f}\nInteraction {self.interaction.affordance.__name__} on target {self.interaction.target}:\n    Duration: {self.duration}\n    Efficiency: {self.efficiency}{efficiency_details}\n    Object Preference: {self.autonomy_scoring_preference}\n\n{commodity_score_str}\n\n    Relationship Score:\n{self.rel_utility_score}\n\n    Crafted Object Relationship Score:\n{self.relationship_object_value}\n\n    Party Score:\n{self.party_score}\n\n    Opportunity Costs:\n{opportunity_costs}\nChanging Posture Cost: {change_posture_cost}\n    Total Opportunity Cost: {total_opportunity_cost}\n\nEquation: Efficiency * Obj Pref * Rel Score * Party Size Score * sum(Modified Desire * Commodity Value / Interval)\n\nAttention Cost:\n    Base Cost:\n{attention_cost_scores}\n    Stat Bonuses:\n{attention_cost_bonus_scores}\n    Stat Penalties:\n{attention_cost_penalty_scores}    Final Attention Cost:\n        final multitasking percentage = base + bonus - penalty\n        {final_multitasking_percentage} = {base_multitasking_percentage} + {bonus_multitasking_percentage} - {penalty_multitasking_percentage}\n\nFinal Score: {self:.8f}\n'.format(self=self, efficiency_details=efficiency_details, commodity_score_str=commodity_score_str, opportunity_costs=opportunity_costs_str, change_posture_cost=change_posture_cost_str, total_opportunity_cost=total_opportunity_cost, commodity_score_sum=commodity_score_sum, base_multitasking_percentage=base_multitasking_percentage, bonus_multitasking_percentage=bonus_multitasking_percentage, penalty_multitasking_percentage=penalty_multitasking_percentage, final_multitasking_percentage=final_multitasking_percentage, attention_cost_scores=attention_cost_scores_str, attention_cost_bonus_scores=attention_cost_bonus_scores_str, attention_cost_penalty_scores=attention_cost_penalty_scores_str)

class InteractionResult:
    __qualname__ = 'InteractionResult'

    class Success(collections.namedtuple('_InteractionResult_Success', ['interaction', 'relevant_desires', 'score', 'multitask_percentage'])):
        __qualname__ = 'InteractionResult.Success'

        def __bool__(self):
            return True

        def __str__(self):
            return 'Scored {:f}'.format(self.score)

    class Failure(collections.namedtuple('_InteractionResult_Failure', ['interaction', 'stage', 'relevant_desires', 'reason'])):
        __qualname__ = 'InteractionResult.Failure'

        def __bool__(self):
            return False

        def __str__(self):
            return 'Skipped because {}'.format(self.reason)

class _InteractionCommodityScore(float):
    __qualname__ = '_InteractionCommodityScore'
    __slots__ = ('commodity', 'advertise', 'commodity_value', 'interval', 'fulfillment_rate', 'object_stat_use_multiplier', 'already_solving_motive_multiplier', 'modified_desire')

    def __new__(cls, score, *args, **kwargs):
        return float.__new__(cls, score)

    def __init__(self, score, commodity, advertise, commodity_value=None, interval=None, fulfillment_rate=None, object_stat_use_multiplier=None, already_solving_motive_multiplier=None, modified_desire=None):
        self.commodity = commodity
        self.advertise = advertise
        self.commodity_value = None if commodity_value is None else float(commodity_value)
        self.interval = None if interval is None else float(interval)
        self.fulfillment_rate = None if fulfillment_rate is None else float(fulfillment_rate)
        self.object_stat_use_multiplier = object_stat_use_multiplier
        self.already_solving_motive_multiplier = None if already_solving_motive_multiplier is None else float(already_solving_motive_multiplier)
        self.modified_desire = None if modified_desire is None else float(modified_desire)

    def __str__(self):
        if self.advertise:
            stat_name = 'No Commodity' if self.commodity is None else self.commodity.__name__
            return '    Commodity: {stat_name}\n        Commodity Value : {self.commodity_value}\n        Interval        : {self.interval}\n        Fulfillment Rate: {self.fulfillment_rate} = {self.commodity_value} / {self.interval}\n        Object Stat Use : {self.object_stat_use_multiplier}\n        Already Solving : {self.already_solving_motive_multiplier}\n        Desire Weight   : {self.autonomy_weight}\n        Modified Desire : {self.modified_desire}\n        Score           : {score} = {self.fulfillment_rate} * {self.object_stat_use_multiplier} * {self.already_solving_motive_multiplier} * {self.modified_desire} * {self.autonomy_weight}'.format(self=self, score=float(self), stat_name=stat_name)
        return '    Commodity: {self.commodity}\n        Not advertising'.format(self=self)

    @property
    def details(self):
        return self.__str__()

    @property
    def autonomy_weight(self):
        if self.commodity is not None:
            return self.commodity.autonomy_weight
        logger.error('Invalid commodity in _InteractionCommodityScore')
        return 1

class _ScoredStatistic(float):
    __qualname__ = '_ScoredStatistic'
    __slots__ = ('_stat_type', 'autonomous_desire', 'stat_value', 'score_multiplier')

    @classmethod
    def _calculate_score(cls, stat_type, sim):
        stat_tracker = sim.get_tracker(stat_type)
        if stat_tracker is None:
            return stat_type.autonomous_desire*sim.get_score_multiplier(stat_type)
        stat = stat_tracker.get_statistic(stat_type) or stat_type
        return stat.autonomous_desire*sim.get_score_multiplier(stat_type)

    def __new__(cls, stat_type, sim):
        return float.__new__(cls, cls._calculate_score(stat_type, sim))

    def __init__(self, stat_type, sim):
        self._stat_type = stat_type
        stat_tracker = sim.get_tracker(stat_type)
        if stat_tracker is not None:
            stat = stat_tracker.get_statistic(stat_type) or stat_type
        else:
            stat = stat_type
        self.autonomous_desire = stat.autonomous_desire
        self.score_multiplier = sim.get_score_multiplier(self.stat_type)
        self.stat_value = stat.get_value() if hasattr(stat, 'get_value') else None

    def __repr__(self):
        return '{self.stat_type} ({self.score})'.format(self=self)

    def __str__(self):
        weighted_score = float(self)*self.autonomy_weight
        return '    Commodity: {self._stat_type}\n        Score            : {score}\n        Weighted Score   : {weighted_score}\n        Value            : {self.stat_value}\n        Autonomous Desire: {self.autonomous_desire}\n        Multiplier       : {self.score_multiplier}        Autonomy Weight  : {self.autonomy_weight}'.format(self=self, score=float(self), weighted_score=weighted_score)

    @property
    def details(self):
        return self.__str__()

    @property
    def stat_type(self):
        return self._stat_type

    @property
    def score(self):
        return float(self)

    @property
    def autonomy_weight(self):
        return self._stat_type.autonomy_weight

    @property
    def score_log_string(self):
        return '  Stat: {} -> {}'.format(self.stat_type, self.score)

with sims4.reload.protected(globals()):
    InteractionScore = InteractionCommodityScore = lambda score, *args, **kwargs: float(score)
    ScoredStatistic = _ScoredStatistic
