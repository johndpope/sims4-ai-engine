#ERROR: jaddr is None
from contextlib import contextmanager
import collections
import random
from autonomy.autonomy_modes import ScoredInteractionData
from gsi_handlers.performance_handlers import set_gsi_performance_metric
from sims4.callback_utils import CallbackEvent, invoke_enter_exit_callbacks
from sims4.service_manager import Service
from sims4.tuning.tunable import Tunable, TunableRealSecond
from singletons import DEFAULT
import autonomy.autonomy_exceptions
import autonomy.settings
import element_utils
import elements
import gsi_handlers.autonomy_handlers
import interactions
import performance.counters
import services
import sims4.log
import sims4.random
logger = sims4.log.Logger('Autonomy', default_owner='rez')
autonomy_queue_logger = sims4.log.Logger('AutonomyQueue', default_owner='rez')
automation_logger = sims4.log.Logger('AutonomyAutomation', default_owner='rez')

class AutonomyService(Service):
    __qualname__ = 'AutonomyService'
    NUM_INTERACTIONS = Tunable(description='\n                                    Number of interactions to consider, from the top of the scored list.', tunable_type=int, default=5)
    MAX_SECONDS_PER_LOOP = TunableRealSecond(description='\n                                                Max amount of time to spend in the autonomy service before yielding to other systems.', default=0.03333333333333333)
    MAX_OPEN_STREET_ROUTE_DISTANCE_FOR_SOCIAL_TARGET = Tunable(description="\n                                                                        When a sim considers another sim for socialization and they are both on the open\n                                                                        street, this is maximum distance that the target sim can be routing in order to \n                                                                        be valid as a social target.  For example, if a sim is routing a really long \n                                                                        distance, we don't want another sim to try and chase them down since they'll never\n                                                                        reach them so we don't allow them as a target.  If they're traveling a short \n                                                                        distance, it won't matter.\n                                                                        ", tunable_type=float, default=15)
    MAX_OPEN_STREET_ROUTE_DISTANCE_FOR_INITIATING_SOCIAL = Tunable(description="\n                                                                        When a sim considers another sim for socialization and they are both on the open\n                                                                        street, this is maximum distance that the target sim's intended position can be \n                                                                        from the actor sim's intended position.  This keeps sims from routing across the \n                                                                        world to talk with another sim.  \n                                                                        ", tunable_type=float, default=100)
    _ARTIFICIAL_MAX_ROUTE_TIME_INCREMENT = 0.0001

    def __init__(self):
        self.queue = []
        self._processor = None
        self._active_sim = None
        self.logging_sims = set()
        self._default_autonomy_settings = autonomy.settings.AutonomySettings(use_tuned_defaults=True)
        self._global_autonomy_settings = autonomy.settings.AutonomySettings()
        self._selected_sim_autonomy_enabled = True
        self._cached_autonomy_state_setting = None
        self._automated_load_test_connection = None
        self._processed_sim_count = 0
        self._automated_performance_test_connection = None
        self._automated_performance_test_sim_id = None
        self.MAX_OPEN_STREET_ROUTE_DISTANCE_FOR_SOCIAL_TARGET_SQUARED = self.MAX_OPEN_STREET_ROUTE_DISTANCE_FOR_SOCIAL_TARGET*self.MAX_OPEN_STREET_ROUTE_DISTANCE_FOR_SOCIAL_TARGET
        self.MAX_OPEN_STREET_ROUTE_DISTANCE_FOR_INITIATING_SOCIAL_SQUARED = self.MAX_OPEN_STREET_ROUTE_DISTANCE_FOR_INITIATING_SOCIAL*self.MAX_OPEN_STREET_ROUTE_DISTANCE_FOR_INITIATING_SOCIAL

    def find_best_action(self, autonomy_request, consider_all_options=False, randomization_override=DEFAULT, archive_if_enabled=True):
        result_scores = self.score_all_interactions(autonomy_request)
        return self._select_best_result(result_scores, autonomy_request, consider_all_options=consider_all_options, randomization_override=randomization_override, archive_if_enabled=archive_if_enabled)

    def find_best_action_gen(self, timeline, autonomy_request, consider_all_options=False, randomization_override=DEFAULT, archive_if_enabled=True):
        result_scores = yield self.score_all_interactions_gen(timeline, autonomy_request)
        return self._select_best_result(result_scores, autonomy_request, consider_all_options=consider_all_options, randomization_override=randomization_override, archive_if_enabled=archive_if_enabled)

    def _select_best_result(self, result_scores, autonomy_request, consider_all_options=False, randomization_override=DEFAULT, archive_if_enabled=True):
        if result_scores is None:
            logger.error("score_all_interactions() returned None, which shouldn't be possible.")
            return
        if autonomy_request.sim is None:
            logger.debug('Sim is None after processing autonomy; bailing out.')
            return
        selected_interaction = self.choose_best_interaction(result_scores, autonomy_request, consider_all_options, randomization_override)
        if selected_interaction is not None and selected_interaction.is_super and not selected_interaction.use_best_scoring_aop:
            similar_scored_interactions = autonomy_request.similar_aop_cache.get(selected_interaction.affordance)
            if similar_scored_interactions is not None:
                selected_interaction = self.choose_best_interaction(similar_scored_interactions, autonomy_request, consider_all_options=consider_all_options, randomization_override=randomization_override, interaction_prefix='**')
            else:
                logger.warn('Failed to find selected interaction {} in similar aop cache.  This is bad, but the original SI should queue.', selected_interaction)
        if archive_if_enabled and gsi_handlers.autonomy_handlers.archiver.enabled:
            gsi_handlers.autonomy_handlers.archive_autonomy_data(autonomy_request.sim, selected_interaction, autonomy_request.autonomy_mode_label, autonomy_request.gsi_data)
        autonomy_request.invalidate_created_interactions(excluded_si=selected_interaction)
        return selected_interaction

    def score_all_interactions(self, autonomy_request):
        score_gen = self.score_all_interactions_gen(None, autonomy_request)
        try:
            next(score_gen)
        except StopIteration as exc:
            return exc.value

    def score_all_interactions_gen(self, timeline, autonomy_request):
        valid_interactions = None
        if timeline is None:
            valid_interactions = yield self._execute_request_gen(timeline, autonomy_request, timeslice=None)
        else:
            sleep_element = self._register(autonomy_request)
            yield element_utils.run_child(timeline, sleep_element)
            if autonomy_request is not None:
                valid_interactions = autonomy_request.valid_interactions
            else:
                logger.error('AutonomyService.score_all_interactions_gen() returned None for the autonomy_request')
        if valid_interactions is not None:
            result_scores = valid_interactions.get_result_scores()
        else:
            result_scores = ()
        if self.should_log(autonomy_request.sim):
            logger.info('{} chose {} for {} ({})', type(autonomy_request.autonomy_mode).__name__, result_scores, autonomy_request.sim, autonomy_request.sim.persona)
        return result_scores

    def choose_best_interaction(self, scored_interactions, autonomy_request, consider_all_options=False, randomization_override=DEFAULT, interaction_prefix=''):
        chosen_scored_interaction_data = None
        if not scored_interactions:
            return
        valid_scored_interactions = [scored_interaction_data for scored_interaction_data in scored_interactions if scored_interaction_data.interaction.aop.target is not None]
        top_options = sorted(valid_scored_interactions, key=lambda scored_interaction_data: scored_interaction_data.score)
        if autonomy_request.consider_scores_of_zero and autonomy_request.autonomy_mode.allows_routing() and top_options[-1].score <= 0:
            top_options = self._recalculate_scores_based_on_route_time(top_options)
        if not consider_all_options:
            top_options = top_options[-self.NUM_INTERACTIONS:]
        if not top_options:
            return
        multitasking_roll = autonomy_request.sim.get_multitasking_roll()
        randomization = autonomy_request.context.sim.get_autonomy_randomization_setting() if randomization_override is DEFAULT else randomization_override
        if randomization == autonomy.settings.AutonomyRandomization.ENABLED:
            if not autonomy_request.consider_scores_of_zero and top_options[0].score <= 0:
                slice_index = 0
                for scored_interaction_data in top_options:
                    if scored_interaction_data.score > 0:
                        break
                    slice_index += 1
                top_options = top_options[slice_index:]
            if not top_options:
                return
            chosen_index = None
            randomization_type_str = None
            if top_options[-1].score > 0:
                chosen_index = sims4.random.weighted_random_index(top_options)
                randomization_type_str = 'Weighted Score' if not autonomy_request.consider_scores_of_zero else 'Weighted Route Dist'
            else:
                chosen_index = random.randint(0, len(top_options) - 1)
                randomization_type_str = 'Uniform'
            if chosen_index is None:
                logger.error('Somehow, chosen_index became None in choose_best_interaction()')
                return
            chosen_scored_interaction_data = top_options[chosen_index]
            if gsi_handlers.autonomy_handlers.archiver.enabled and autonomy_request.gsi_data is not None:
                if top_options[-1].score > 0:
                    summed_scores = sum([scored_interaction_data.score for scored_interaction_data in top_options])
                    _get_probability = lambda score: score/summed_scores
                else:
                    _get_probability = lambda _: 1/len(top_options)
                while True:
                    for scored_interaction_data in top_options:
                        probability = _get_probability(scored_interaction_data.score)
                        autonomy_request.gsi_data['Probability'].append(AutonomyProbabilityData(scored_interaction_data.interaction, scored_interaction_data.score, probability, multitasking_roll, randomization_type_str, interaction_prefix))
        elif autonomy_request.consider_scores_of_zero and top_options[-1].score <= 0 or top_options[-1].score > 0:
            chosen_scored_interaction_data = top_options[-1]
            if gsi_handlers.autonomy_handlers.archiver.enabled:
                autonomy_request.gsi_data['Probability'] = [AutonomyProbabilityData(chosen_scored_interaction_data.interaction, chosen_scored_interaction_data.score, 1, multitasking_roll, 'Best', interaction_prefix)]
        if chosen_scored_interaction_data is None:
            return
        if not autonomy_request.is_script_request and (autonomy_request.context.source == interactions.context.InteractionContext.SOURCE_AUTONOMY and chosen_scored_interaction_data.interaction.is_super) and multitasking_roll > chosen_scored_interaction_data.multitasking_percentage:
            return
        return chosen_scored_interaction_data.interaction

    def _recalculate_scores_based_on_route_time(self, scored_interactions):
        if not scored_interactions:
            return scored_interactions
        max_route_time = max(scored_interactions, key=lambda scored_interaction_data: scored_interaction_data.route_time).route_time
        if max_route_time == 0:
            return scored_interactions
        max_route_time += self._ARTIFICIAL_MAX_ROUTE_TIME_INCREMENT
        rescored_interactions = [self._calculate_score_based_on_route_time(scored_interaction_data, max_route_time) for scored_interaction_data in scored_interactions]
        rescored_interactions.sort(key=lambda scored_interaction_data: scored_interaction_data.score)
        return rescored_interactions

    def _calculate_score_based_on_route_time(self, scored_interaction_data, max_route_time):
        logger.assert_log(scored_interaction_data.score <= 0, 'Calling _calculate_score_based_on_route_time() on an interaction with a score > 0.  This is probably wrong.')
        logger.assert_raise(max_route_time > 0, 'About to divide by zero; max_route_time was calculated as zero.')
        score = 1 - scored_interaction_data.route_time/max_route_time
        return ScoredInteractionData(score, scored_interaction_data.route_time, scored_interaction_data.multitasking_percentage, scored_interaction_data.interaction)

    def _register(self, autonomy_request):
        if self._processor is None:
            sim_timeline = services.time_service().sim_timeline
            self._processor = sim_timeline.schedule(elements.GeneratorElement(self._process_gen))
        sleep_element = element_utils.soft_sleep_forever()
        autonomy_request.sleep_element = sleep_element
        self.queue.append(autonomy_request)
        autonomy_queue_logger.debug('Enqueuing {}', autonomy_request.sim)
        return sleep_element

    def _update_gen(self, timeline):
        while self.queue:
            cur_request = self.queue.pop(0)
            cur_request.autonomy_mode.set_process_start_time()
            try:
                next_sim = cur_request.sim
                if next_sim is not None:
                    autonomy_queue_logger.debug('Processing {}', next_sim)
                    self._active_sim = next_sim
                    yield self._execute_request_gen(timeline, cur_request, self.MAX_SECONDS_PER_LOOP)
                else:
                    autonomy_queue_logger.debug('Skipping removed sim.')
            except autonomy.autonomy_exceptions.AutonomyExitException:
                pass
            finally:
                cur_request.sleep_element.trigger_soft_stop()
                cur_request.sleep_element = None
                self._update_automation_load_test()
                self._check_for_automated_performance_test_sim()
                self._active_sim = None
            sleep_element = element_utils.sleep_until_next_tick_element()
            yield timeline.run_child(sleep_element)

    def _execute_request_gen(self, timeline, request, timeslice):
        autonomy_mode = request.autonomy_mode
        valid = autonomy_mode.run_gen(timeline, timeslice)
        return valid

    @contextmanager
    def _queue_counter(self):

        def _count_queue():
            performance.counters.set_counter(performance.counters.CounterIDs.AUTONOMY_QUEUE_LENGTH, len(self.queue))
            set_gsi_performance_metric(performance.counters.CounterIDs.AUTONOMY_QUEUE_LENGTH, len(self.queue))

        _count_queue()
        try:
            yield None
        finally:
            _count_queue()

    def _process_gen(self, timeline):
        try:
            with self._queue_counter():
                while self.queue:
                    with invoke_enter_exit_callbacks(CallbackEvent.AUTONOMY_PING_ENTER, CallbackEvent.AUTONOMY_PING_EXIT):
                        yield self._update_gen(timeline)
        finally:
            self._processor = None

    def stop(self):
        if self._processor is not None:
            self._processor.trigger_hard_stop()
            self._processor = None

    def load_options(self, options_proto):
        self._cached_autonomy_state_setting = autonomy.settings.AutonomySettings.STARTING_HOUSEHOLD_AUTONOMY_STATE
        self._selected_sim_autonomy_enabled = autonomy.settings.AutonomySettings.STARTING_SELECTED_SIM_AUTONOMY
        if options_proto is None:
            logger.error('No options protocol buffer when trying to load autonomy options.')
            return
        self._selected_sim_autonomy_enabled = options_proto.selected_sim_autonomy_enabled
        if options_proto.autonomy_level == options_proto.OFF or options_proto.autonomy_level == options_proto.LIMITED:
            self._cached_autonomy_state_setting = autonomy.settings.AutonomyState.LIMITED_ONLY
        elif options_proto.autonomy_level == options_proto.FULL:
            self._cached_autonomy_state_setting = autonomy.settings.AutonomyState.FULL
        elif options_proto.autonomy_level != options_proto.UNDEFINED:
            logger.warn('Ignoring unknown autonomy setting in gameplay options protocol buffer: {}.', options_proto.autonomy_level)

    def save_options(self, options_proto):
        if options_proto is None:
            logger.error('No options protocol buffer when trying to save autonomy options.')
            return
        client = services.client_manager().get_first_client()
        if client is None:
            logger.error("Couldn't find a reasonable client when trying to save autonomy options.")
            return
        household = client.household
        if household is None:
            logger.error("Couldn't find a household attached to the first client when trying to save autonomy options.")
            return
        options_proto.selected_sim_autonomy_enabled = self._selected_sim_autonomy_enabled
        state_setting = household.autonomy_settings.get_state_setting()
        if state_setting == autonomy.settings.AutonomyState.FULL:
            options_proto.autonomy_level = options_proto.FULL
        elif state_setting == autonomy.settings.AutonomyState.LIMITED_ONLY:
            options_proto.autonomy_level = options_proto.LIMITED
        else:
            options_proto.autonomy_level = options_proto.UNDEFINED

    def on_all_households_and_sim_infos_loaded(self, client):
        if self._cached_autonomy_state_setting is not None:
            household = client.household
            if household is not None:
                household.autonomy_settings.set_state_setting(self._cached_autonomy_state_setting)
            else:
                logger.error("Couldn't find household in on_client_connect() in the autonomy service.  Autonomy settings will not be loaded.")
        if not self._selected_sim_autonomy_enabled:
            client.register_active_sim_changed(self._on_active_sim_changed)

    @property
    def global_autonomy_settings(self):
        return self._global_autonomy_settings

    @property
    def default_autonomy_settings(self):
        return self._default_autonomy_settings

    def set_autonomy_for_active_sim(self, enabled, client=None):
        if enabled == self._selected_sim_autonomy_enabled:
            return
        if client is None:
            client = services.client_manager().get_first_client()
        if client is None:
            logger.error("Couldn't find a reasonable client when searching for the active sim.")
            return
        active_sim = client.active_sim
        if active_sim is None:
            logger.error('Failed to find active Sim')
            return
        if enabled:
            active_sim.autonomy_settings.set_state_setting(autonomy.settings.AutonomyState.UNDEFINED)
            client.unregister_active_sim_changed(self._on_active_sim_changed)
        else:
            active_sim.autonomy_settings.set_state_setting(autonomy.settings.AutonomyState.LIMITED_ONLY)
            client.register_active_sim_changed(self._on_active_sim_changed)
        self._selected_sim_autonomy_enabled = enabled

    def _on_active_sim_changed(self, old_sim, new_sim):
        if self._selected_sim_autonomy_enabled:
            logger.error('Calling _on_active_sim_changed() unnecessarily.')
            return
        if old_sim is not None:
            old_sim.autonomy_settings.set_state_setting(autonomy.settings.AutonomyState.UNDEFINED)
        if new_sim is not None:
            new_sim.autonomy_settings.set_state_setting(autonomy.settings.AutonomyState.LIMITED_ONLY)

    def start_automated_load_test(self, connection, sims_to_process_count=DEFAULT):
        if sims_to_process_count is DEFAULT:
            self._processed_sim_count = len(self._queue)
        else:
            self._processed_sim_count = sims_to_process_count
        if self._processed_sim_count <= 0:
            automation_logger.error("Failed to start automated load test.  The number of sims we're processing is {}".format(self._processed_sim_count))
            self._processed_sim_count = 0
            return
        self._automated_load_test_connection = connection
        automation_logger.debug('Starting automated load test.  Number of sims to process: {}'.format(self._processed_sim_count))

    def start_single_sim_load_test(self, connection, sim):
        if sim is None:
            automation_logger.error('Failed to start automated performance test for autonomy.  Sim is None.')
            return
        if connection is None:
            automation_logger.error('Failed to start automated performance test for autonomy.  No connection to client.')
            return
        self._automated_performance_test_connection = connection
        self._automated_performance_test_sim_id = sim.id

    def _update_automation_load_test(self):
        if self._automated_load_test_connection is None:
            return
        automation_logger.debug('Updating count: {}'.format(self._processed_sim_count))
        if self._processed_sim_count <= 0:
            self._trigger_automation_load_test_message()
            self._automated_load_test_connection = None

    def _check_for_automated_performance_test_sim(self):
        if self._automated_performance_test_connection is None:
            return
        if self._active_sim.id == self._automated_performance_test_sim_id:
            self._trigger_automation_single_sim_performance_test_message()
            self._automated_performance_test_sim_id = None
            self._automated_performance_test_connection = None

    def _trigger_automation_load_test_message(self):
        sims4.commands.automation_output('Autonomy; settled:true', self._automated_load_test_connection)
        automation_logger.debug('Autonomy has settled.')

    def _trigger_automation_single_sim_performance_test_message(self):
        sims4.commands.automation_output('Autonomy; SimId: {}'.format(self._active_sim.id), self._automated_performance_test_connection)
        automation_logger.debug('Autonomy has settled.')

    def _should_log(self, autonomy_mode=None):
        if autonomy_mode and autonomy_mode.is_silent_mode():
            return False
        return self.should_log(self._active_sim)

    def should_log(self, sim):
        return sim.is_selected or sim in self.logging_sims

AutonomyProbabilityData = collections.namedtuple('AutonomyProbabilityData', ['interaction', 'score', 'probability', 'multitask_roll', 'probability_type', 'interaction_prefix'])
