import collections
from interactions.liability import Liability
from objects import ALL_HIDDEN_REASONS
from sims4 import random
from sims4.service_manager import Service
from singletons import EMPTY_SET
import enum
import filters.tunable
import services
import sims4.log
logger = sims4.log.Logger('SimFilter')
SIM_FILTER_GLOBAL_BLACKLIST_LIABILITY = 'SimFilterGlobalBlacklistLiability'

class SimFilterGlobalBlacklistReason(enum.Int, export=False):
    __qualname__ = 'SimFilterGlobalBlacklistReason'
    ADOPTION = 0
    PHONE_CALL = 1

class SimFilterGlobalBlacklistLiability(Liability):
    __qualname__ = 'SimFilterGlobalBlacklistLiability'

    def __init__(self, blacklist_sim_ids, reason):
        self._blacklist_sim_ids = blacklist_sim_ids
        self._reason = reason
        self._has_been_added = False

    def on_add(self, _):
        if self._has_been_added:
            return
        sim_filter_service = services.sim_filter_service()
        if sim_filter_service is not None:
            for sim_id in self._blacklist_sim_ids:
                services.sim_filter_service().add_sim_id_to_global_blacklist(sim_id, self._reason)
        self._has_been_added = True

    def release(self):
        sim_filter_service = services.sim_filter_service()
        if sim_filter_service is not None:
            for sim_id in self._blacklist_sim_ids:
                services.sim_filter_service().remove_sim_id_from_global_blacklist(sim_id, self._reason)

class SimFilterRequestState(enum.Int, export=False):
    __qualname__ = 'SimFilterRequestState'
    SETUP = Ellipsis
    RAN_QUERY = Ellipsis
    SPAWNING_SIMS = Ellipsis
    FILLED_RESUTLS = Ellipsis
    COMPLETE = Ellipsis

class _SimFilterRequest:
    __qualname__ = '_SimFilterRequest'

    def __init__(self, sim_filter, callback, callback_event_data, requesting_sim_info, sim_constraints, blacklist_sim_ids, start_time, end_time, create_if_needed, household_id, zone_id):
        self._state = SimFilterRequestState.SETUP
        if sim_filter is None:
            sim_filter = filters.tunable.TunableSimFilter.BLANK_FILTER
        self._sim_filter = sim_filter
        self._callback = callback
        self._callback_event_data = callback_event_data
        self._requesting_sim_info = requesting_sim_info
        self._sim_constraints = sim_constraints
        self._blacklist_sim_ids = blacklist_sim_ids if blacklist_sim_ids is not None else EMPTY_SET
        self._create_if_needed = create_if_needed
        self._zone_id = zone_id
        if start_time is not None:
            self._start_time = start_time.time_since_beginning_of_week()
        else:
            self._start_time = None
        if end_time is not None:
            self._end_time = end_time.time_since_beginning_of_week()
        else:
            self._end_time = None
        if household_id:
            self._household_id = household_id
        elif requesting_sim_info:
            self._household_id = requesting_sim_info.household_id
        else:
            self._household_id = 0

    @property
    def is_complete(self):
        return self._state == SimFilterRequestState.COMPLETE

    def submit(self):
        results = self._run_filter_query()
        if self._callback is not None:
            self._callback(results, self._callback_event_data)

    def run(self):
        if self._state == SimFilterRequestState.SETUP:
            self.submit()
            self._state = SimFilterRequestState.COMPLETE

    def run_without_yielding(self):
        return self._run_filter_query()

    def cancel(self):
        pass

    def _get_constrained_sims(self):
        constrained_sim_ids = self._sim_constraints
        if self._requesting_sim_info:
            relationship_constrained_sim_ids = self._sim_filter.get_relationship_constrained_sims(self._requesting_sim_info)
            if relationship_constrained_sim_ids is not None:
                if constrained_sim_ids:
                    constrained_sim_ids = list(set(constrained_sim_ids) & set(relationship_constrained_sim_ids))
                else:
                    constrained_sim_ids = relationship_constrained_sim_ids
        return constrained_sim_ids

    def _run_filter_query(self):
        sim_info_manager = services.sim_info_manager()
        constrained_sim_ids = self._get_constrained_sims()
        results = sim_info_manager.find_sims_matching_filter(self._sim_filter.get_filter_terms(), constrained_sim_ids=constrained_sim_ids, start_time=self._start_time, end_time=self._end_time, household_id=self._household_id, requesting_sim_info=self._requesting_sim_info)
        global_blacklist = services.sim_filter_service().get_global_blacklist()
        for result in tuple(results):
            while result.sim_info.id in self._blacklist_sim_ids or result.sim_info.id in global_blacklist:
                results.remove(result)
        if not results and self._create_if_needed:
            results = []
            create_result = self._sim_filter.create_sim_info(zone_id=self._zone_id, requesting_sim_info=self._requesting_sim_info, start_time=self._start_time, end_time=self._end_time)
            if create_result:
                results.append(create_result)
                logger.info('Created Sim Info with ID to match request {0}', create_result.sim_info.id)
            else:
                logger.info('Failed to create Sim info that matches filter. Reason: {}', create_result)
        return results

class _MatchingFilterRequest(_SimFilterRequest):
    __qualname__ = '_MatchingFilterRequest'

    def __init__(self, number_of_sims_to_find, continue_if_constraints_fail, *args):
        super().__init__(*args)
        self._continue_if_constrains_fail = continue_if_constraints_fail
        self._number_of_sims_to_find = number_of_sims_to_find
        self._selected_sim_infos = []

    def _select_sims_from_results(self, results, sims_to_spawn):
        self._selected_sim_infos = []
        global_blacklist = services.sim_filter_service().get_global_blacklist()
        for result in tuple(results):
            while result.sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS) or result.sim_info.id in self._blacklist_sim_ids or result.sim_info.id in global_blacklist:
                results.remove(result)
        sorted_results = sorted(results, key=lambda x: x.score, reverse=True)
        if self._sim_filter.use_weighted_random:
            index = filters.tunable.TunableSimFilter.TOP_NUMBER_OF_SIMS_TO_LOOK_AT
            randomization_group = [(result.score, result.sim_info) for result in sorted_results[:index]]
            while index < len(sorted_results):
                while len(self._selected_sim_infos) < sims_to_spawn:
                    random_choice = random.pop_weighted(randomization_group)
                    randomization_group.append((sorted_results[index].score, sorted_results[index].sim_info))
                    logger.info('Sim ID matching request {0}', random_choice)
                    self._selected_sim_infos.append(random_choice)
                    index += 1
            while True:
                while randomization_group and len(self._selected_sim_infos) < self._number_of_sims_to_find:
                    random_choice = random.pop_weighted(randomization_group)
                    logger.info('Sim ID matching request {0}', random_choice)
                    self._selected_sim_infos.append(random_choice)
        else:
            for result in sorted_results:
                if len(self._selected_sim_infos) == sims_to_spawn:
                    break
                logger.info('Sim ID matching request {0}', result.sim_info)
                self._selected_sim_infos.append(result.sim_info)
        return self._selected_sim_infos

    def _run_filter_query(self):
        sim_info_manager = services.sim_info_manager()
        results = None
        constrained_sim_ids = self._get_constrained_sims()
        if constrained_sim_ids is not None:
            results = sim_info_manager.find_sims_matching_filter(self._sim_filter.get_filter_terms(), constrained_sim_ids=constrained_sim_ids, start_time=self._start_time, end_time=self._end_time, household_id=self._household_id, requesting_sim_info=self._requesting_sim_info)
            if not results and not self._continue_if_constrains_fail:
                return self._selected_sim_infos
            self._selected_sim_infos = self._select_sims_from_results(results, self._number_of_sims_to_find)
            if len(self._selected_sim_infos) == self._number_of_sims_to_find or not self._continue_if_constrains_fail:
                return self._selected_sim_infos
        results = sim_info_manager.find_sims_matching_filter(self._sim_filter.get_filter_terms(), start_time=self._start_time, end_time=self._end_time, household_id=self._household_id, requesting_sim_info=self._requesting_sim_info)
        if results:
            self._selected_sim_infos.extend(self._select_sims_from_results(results, self._number_of_sims_to_find - len(self._selected_sim_infos)))

    def _create_sim_info(self):
        create_result = self._sim_filter.create_sim_info(zone_id=self._zone_id, requesting_sim_info=self._requesting_sim_info, start_time=self._start_time, end_time=self._end_time)
        if create_result:
            self._selected_sim_infos.append(create_result.sim_info)
            logger.info('Created Sim ID to match request {0}', create_result.sim_info.id)
            return True
        logger.info('Failed to create Sim that matches filter. Reason: {}', create_result)
        return False

    def _create_sim_infos(self):
        while len(self._selected_sim_infos) < self._number_of_sims_to_find:
            while not self._create_sim_info():
                break
                continue

    def run(self):
        if self._state == SimFilterRequestState.SETUP:
            self._run_filter_query()
            if len(self._selected_sim_infos) == self._number_of_sims_to_find:
                self._state = SimFilterRequestState.FILLED_RESUTLS
            else:
                self._state = SimFilterRequestState.RAN_QUERY
        if self._state == SimFilterRequestState.RAN_QUERY:
            self._state = SimFilterRequestState.SPAWNING_SIMS
            return
        if self._state == SimFilterRequestState.SPAWNING_SIMS:
            result = self._create_sim_info()
            if not result or len(self._selected_sim_infos) == self._number_of_sims_to_find:
                self._state = SimFilterRequestState.FILLED_RESUTLS
        if self._state == SimFilterRequestState.FILLED_RESUTLS:
            self._callback(self._selected_sim_infos, self._callback_event_data)
            self._state = SimFilterRequestState.COMPLETE

    def run_without_yielding(self):
        self._run_filter_query()
        self._create_sim_infos()
        return self._selected_sim_infos

class SimFilterService(Service):
    __qualname__ = 'SimFilterService'

    def __init__(self):
        self._filter_requests = []
        self._global_blacklist = collections.defaultdict(list)

    def update(self):
        try:
            while self._filter_requests:
                current_request = self._filter_requests[0]
                current_request.run()
                while current_request.is_complete:
                    del self._filter_requests[0]
        except Exception:
            logger.exception('Exception while updating the sim filter service..')

    def add_sim_id_to_global_blacklist(self, sim_id, reason):
        self._global_blacklist[sim_id].append(reason)

    def remove_sim_id_from_global_blacklist(self, sim_id, reason):
        reasons = self._global_blacklist.get(sim_id)
        if reasons is None:
            logger.error('Trying to remove sim id {} to global blacklist without adding it first.', sim_id, owner='jjacobson')
            return
        if reason not in reasons:
            logger.error('Trying to remove reason {} from global blacklist with sim id {} without adding it first.', reason, sim_id, owner='jjacobson')
            return
        self._global_blacklist[sim_id].remove(reason)
        if not self._global_blacklist[sim_id]:
            del self._global_blacklist[sim_id]

    def get_global_blacklist(self):
        return set(self._global_blacklist.keys())

    def submit_matching_filter(self, number_of_sim_to_find, sim_filter, callback, callback_event_data=None, sim_constraints=None, requesting_sim_info=None, blacklist_sim_ids=EMPTY_SET, continue_if_constraints_fail=False, allow_yielding=True, start_time=None, end_time=None, household_id=None, zone_id=None):
        request = _MatchingFilterRequest(number_of_sim_to_find, continue_if_constraints_fail, sim_filter, callback, callback_event_data, requesting_sim_info, sim_constraints, blacklist_sim_ids, start_time, end_time, False, household_id, zone_id)
        if allow_yielding:
            self._add_filter_request(request)
        else:
            return request.run_without_yielding()

    def submit_filter(self, sim_filter, callback, callback_event_data=None, sim_constraints=None, requesting_sim_info=None, blacklist_sim_ids=EMPTY_SET, allow_yielding=True, start_time=None, end_time=None, create_if_needed=False, household_id=None, zone_id=None):
        request = _SimFilterRequest(sim_filter, callback, callback_event_data, requesting_sim_info, sim_constraints, blacklist_sim_ids, start_time, end_time, create_if_needed, household_id, zone_id)
        if allow_yielding:
            self._add_filter_request(request)
        else:
            return request.run_without_yielding()

    def _add_filter_request(self, filter_request):
        self._filter_requests.append(filter_request)

    def does_sim_match_filter(self, sim_id, sim_filter=None, requesting_sim_info=None, start_time=None, end_time=None, household_id=None):
        result = self.submit_filter(sim_filter, None, allow_yielding=False, sim_constraints=[sim_id], requesting_sim_info=requesting_sim_info, start_time=start_time, end_time=end_time, household_id=household_id)
        if result:
            return True
        return False

