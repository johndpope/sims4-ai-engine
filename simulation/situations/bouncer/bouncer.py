from collections import namedtuple
import heapq
from date_and_time import DATE_AND_TIME_ZERO, create_time_span
from situations.bouncer.bouncer_types import BouncerRequestPriority, BouncerRequestStatus, BouncerExclusivityCategory, BouncerExclusivityOption
from situations.situation_types import SituationCommonBlacklistCategory
from tag import Tag
from world.spawn_point import SpawnPointOption
import services
import sims.sim_spawner
import sims4.log
import sims4.random
import sims4.tuning
import situations
logger = sims4.log.Logger('Bouncer')

class BouncerSimData:
    __qualname__ = 'BouncerSimData'

    def __init__(self, bouncer, sim):
        self._sim_ref = sim.ref(lambda _: bouncer._sim_weakref_callback(sim))
        self._requests = []

    def destroy(self):
        self._sim_ref = None
        self._requests.clear()
        self._requests = None

    def add_request(self, request):
        excluded = self._get_excluded_requests(request)
        self._requests.append(request)
        return excluded

    def remove_request(self, request):
        try:
            self._requests.remove(request)
        except ValueError:
            pass

    @property
    def requests(self):
        return set(self._requests)

    @property
    def is_obsolete(self):
        return len(self._requests) == 0

    def can_assign_to_request(self, new_request):
        if new_request in self._requests:
            return False
        for cur_request in self._requests:
            if cur_request._situation is new_request._situation:
                return False
            while cur_request._exclusivity_compare(new_request) > 0:
                return False
        return True

    def get_request_with_best_klout(self):
        best_klout = None
        best_request = None
        for request in self._requests:
            klout = request._get_request_klout()
            while best_request is None or klout < best_klout:
                best_klout = klout
                best_request = request
        return best_request

    def _get_excluded_requests(self, new_request):
        excluded = []
        for cur_request in self._requests:
            compare_result = cur_request._exclusivity_compare(new_request)
            if compare_result > 0:
                logger.error('New request: {} is excluded by existing request: {}', new_request, cur_request)
            else:
                while compare_result < 0:
                    excluded.append(cur_request)
        return excluded

class _BouncerSituationData:
    __qualname__ = '_BouncerSituationData'

    def __init__(self, situation):
        self._situation = situation
        self._requests = set()
        self._first_assignment_pass_completed = False

    def add_request(self, request):
        self._requests.add(request)

    def remove_request(self, request):
        self._requests.discard(request)

    @property
    def requests(self):
        return set(self._requests)

    @property
    def first_assignment_pass_completed(self):
        return self._first_assignment_pass_completed

    def on_first_assignment_pass_completed(self):
        self._first_assignment_pass_completed = True

class SimRequestScore(namedtuple('SimRequestScore', 'sim_id, request, score')):
    __qualname__ = 'SimRequestScore'

    def __eq__(self, o):
        return self.score == o.score

    def __ne__(self, o):
        return self.score != o.score

    def __lt__(self, o):
        return self.score > o.score

    def __le__(self, o):
        return self.score >= o.score

    def __gt__(self, o):
        return self.score < o.score

    def __ge__(self, o):
        return self.score <= o.score

class _BestRequestKlout(namedtuple('BestRequestKlout', 'request, klout')):
    __qualname__ = '_BestRequestKlout'

    def __eq__(self, o):
        return self.klout == o.klout

    def __ne__(self, o):
        return self.klout != o.klout

    def __lt__(self, o):
        return self.klout < o.klout

    def __le__(self, o):
        return self.klout <= o.klout

    def __gt__(self, o):
        return self.klout > o.klout

    def __ge__(self, o):
        return self.klout >= o.klout

class _WorstRequestKlout(namedtuple('WorstRequestKlout', 'request, klout')):
    __qualname__ = '_WorstRequestKlout'

    def __eq__(self, o):
        return self.klout == o.klout

    def __ne__(self, o):
        return self.klout != o.klout

    def __lt__(self, o):
        return self.klout > o.klout

    def __le__(self, o):
        return self.klout >= o.klout

    def __gt__(self, o):
        return self.klout < o.klout

    def __ge__(self, o):
        return self.klout <= o.klout

class Bouncer:
    __qualname__ = 'Bouncer'
    LEAVING_INTERACTION_TAGS = sims4.tuning.tunable.TunableSet(description='\n        Interaction tags to detect sims running leave lot interactions.\n        ', tunable=sims4.tuning.tunable.TunableEnumEntry(tunable_type=Tag, default=Tag.INVALID, tuning_filter=sims4.tuning.tunable_base.FilterTag.EXPERT_MODE))
    SPAWN_COOLDOWN_MINUTES = 5
    EXCLUSIVITY_RULES = [(BouncerExclusivityCategory.NORMAL, BouncerExclusivityCategory.LEAVE, BouncerExclusivityOption.EXPECTATION_PREFERENCE), (BouncerExclusivityCategory.NORMAL, BouncerExclusivityCategory.PRE_VISIT, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.WALKBY, BouncerExclusivityCategory.NORMAL, BouncerExclusivityOption.EXPECTATION_PREFERENCE), (BouncerExclusivityCategory.WALKBY, BouncerExclusivityCategory.LEAVE, BouncerExclusivityOption.EXPECTATION_PREFERENCE), (BouncerExclusivityCategory.WALKBY, BouncerExclusivityCategory.WALKBY, BouncerExclusivityOption.ALREADY_ASSIGNED), (BouncerExclusivityCategory.SERVICE, BouncerExclusivityCategory.WALKBY, BouncerExclusivityOption.ALREADY_ASSIGNED), (BouncerExclusivityCategory.SERVICE, BouncerExclusivityCategory.LEAVE, BouncerExclusivityOption.EXPECTATION_PREFERENCE), (BouncerExclusivityCategory.SERVICE, BouncerExclusivityCategory.NORMAL, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.SERVICE, BouncerExclusivityCategory.SERVICE, BouncerExclusivityOption.ALREADY_ASSIGNED), (BouncerExclusivityCategory.VISIT, BouncerExclusivityCategory.WALKBY, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.VISIT, BouncerExclusivityCategory.SERVICE, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.VISIT, BouncerExclusivityCategory.LEAVE, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.VISIT, BouncerExclusivityCategory.UNGREETED, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.VISIT, BouncerExclusivityCategory.PRE_VISIT, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.LEAVE_NOW, BouncerExclusivityCategory.LEAVE, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.LEAVE_NOW, BouncerExclusivityCategory.NORMAL, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.LEAVE_NOW, BouncerExclusivityCategory.WALKBY, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.LEAVE_NOW, BouncerExclusivityCategory.SERVICE, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.LEAVE_NOW, BouncerExclusivityCategory.VISIT, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.LEAVE_NOW, BouncerExclusivityCategory.PRE_VISIT, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.LEAVE_NOW, BouncerExclusivityCategory.LEAVE_NOW, BouncerExclusivityOption.ALREADY_ASSIGNED), (BouncerExclusivityCategory.LEAVE_NOW, BouncerExclusivityCategory.UNGREETED, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.UNGREETED, BouncerExclusivityCategory.LEAVE, BouncerExclusivityOption.EXPECTATION_PREFERENCE), (BouncerExclusivityCategory.UNGREETED, BouncerExclusivityCategory.NORMAL, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.UNGREETED, BouncerExclusivityCategory.WALKBY, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.UNGREETED, BouncerExclusivityCategory.SERVICE, BouncerExclusivityOption.ALREADY_ASSIGNED), (BouncerExclusivityCategory.PRE_VISIT, BouncerExclusivityCategory.WALKBY, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.PRE_VISIT, BouncerExclusivityCategory.SERVICE, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.PRE_VISIT, BouncerExclusivityCategory.LEAVE, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.PRE_VISIT, BouncerExclusivityCategory.UNGREETED, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.WORKER, BouncerExclusivityCategory.WALKBY, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.WORKER, BouncerExclusivityCategory.LEAVE, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.WORKER, BouncerExclusivityCategory.NORMAL, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.WORKER, BouncerExclusivityCategory.SERVICE, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.WORKER, BouncerExclusivityCategory.VISIT, BouncerExclusivityOption.NONE), (BouncerExclusivityCategory.WORKER, BouncerExclusivityCategory.PRE_VISIT, BouncerExclusivityOption.NONE)]
    MAX_UNFULFILLED_INDEX = BouncerRequestPriority.COUNT*4
    _exclusivity_rules = None
    _spawning_freeze_enabled = False
    _cap_cheat_enabled = False

    def __init__(self):
        self._unfulfilled_requests = []
        for unfulfilled_index in range(Bouncer.MAX_UNFULFILLED_INDEX):
            self._unfulfilled_requests.insert(unfulfilled_index, [])
        self._spawning_request = None
        self._spawning_sim_info = None
        self._fulfilled_requests = []
        self._sim_to_bouncer_sim_data = {}
        self._situation_to_bouncer_situation_data = {}
        self._started = False
        self._next_spawn_time = DATE_AND_TIME_ZERO
        self._spawn_cooldown = create_time_span(0, 0, Bouncer.SPAWN_COOLDOWN_MINUTES)
        self._high_freq_spawn_locked_ref_count = 0
        self._high_freq_spawn_on = False
        self._number_of_npcs_on_lot = 0
        self._number_of_npcs_leaving = 0

    def destroy(self):
        self.stop()
        self._clear_silently()

    def start(self):
        self._started = True

    def stop(self):
        self._started = False

    def reset(self):
        self.stop()
        self._clear_silently()
        self.start()

    def _clear_silently(self):
        for priority_list in self._unfulfilled_requests:
            for request in priority_list:
                request._destroy()
            priority_list.clear()
        self._spawning_request = None
        self._spawning_sim_info = None
        for request in self._fulfilled_requests:
            request._destroy()
        self._fulfilled_requests.clear()
        for data in self._sim_to_bouncer_sim_data.values():
            data.destroy()
        self._sim_to_bouncer_sim_data.clear()
        self._situation_to_bouncer_situation_data.clear()

    def submit_request(self, request):
        self._unfulfilled_requests[request._unfulfilled_index].append(request)
        request._submit()
        situation_data = self._situation_to_bouncer_situation_data.setdefault(request._situation, _BouncerSituationData(self))
        situation_data.add_request(request)

    def withdraw_request(self, request, silently=False):
        if request is None or request._status == BouncerRequestStatus.DESTROYED:
            return
        sims_removed_from_request = []
        if request._assigned_sim is not None:
            sims_removed_from_request.append(request._assigned_sim)
            self._unassign_sim_from_request(request._assigned_sim, request, silently=silently)
        if request._status == BouncerRequestStatus.FULFILLED and request in self._fulfilled_requests:
            self._fulfilled_requests.remove(request)
        elif request._status == BouncerRequestStatus.SPAWN_REQUESTED:
            self._spawning_request = None
            self._spawning_sim_info = None
        elif request._status == BouncerRequestStatus.SUBMITTED and request in self._unfulfilled_requests[request._unfulfilled_index]:
            self._unfulfilled_requests[request._unfulfilled_index].remove(request)
        situation_data = self._situation_to_bouncer_situation_data.get(request._situation, None)
        if situation_data:
            situation_data.remove_request(request)
        request._destroy()
        for sim in sims_removed_from_request:
            data = self._sim_to_bouncer_sim_data.get(sim, None)
            if data is None:
                pass
            while data.is_obsolete:
                data.destroy()
                self._sim_to_bouncer_sim_data.pop(sim)

    def remove_sim_from_situation(self, sim, situation):
        data = self._sim_to_bouncer_sim_data.get(sim, None)
        if data is None:
            return
        for request in data.requests:
            while request._situation == situation:
                self._unassign_sim_from_request_and_optionally_withdraw(sim, request)
                break

    def on_situation_loaded(self, situation):
        situation_data = self._situation_to_bouncer_situation_data.get(situation, None)
        if not situation_data:
            return True
        success = True
        for request in situation_data.requests:
            while not request._is_fulfilled and request._must_assign_on_load:
                sim = services.object_manager().get(request.requested_sim_id)
                if sim is None:
                    logger.debug('On load, sim saved in situation is not instantiated. request: {} in situation: {}', request, situation)
                    success = False
                else:
                    self._assign_sim_to_request(sim, request)
        return success

    def on_situation_destroy(self, situation):
        situation_data = self._situation_to_bouncer_situation_data.get(situation, None)
        if not situation_data:
            return
        if self._spawning_request is not None and self._spawning_request._situation == situation:
            self._spawning_request = None
            self._spawning_sim_info = None
        for request in situation_data.requests:
            self.withdraw_request(request, silently=True)
        del self._situation_to_bouncer_situation_data[situation]

    def situation_requests_gen(self, situation):
        situation_data = self._situation_to_bouncer_situation_data.get(situation, None)
        if not situation_data:
            return
        for request in situation_data.requests:
            while request._is_obsolete == False and request._status != BouncerRequestStatus.DESTROYED:
                yield request

    def pending_situation_requests_gen(self, situation):
        for request in self.situation_requests_gen(situation):
            while not request._is_fulfilled and request._allows_spawning:
                yield request

    def get_most_important_request_for_sim(self, sim):
        data = self._sim_to_bouncer_sim_data.get(sim, None)
        if data is None or not data.requests:
            return
        best_requests = []
        best_klout = None
        for request in data.requests:
            klout = request._get_request_klout()
            if klout is None:
                pass
            if best_klout is None:
                best_requests.append(request)
                best_klout = klout
            elif klout == best_klout:
                best_requests.append(request)
            else:
                while klout < best_klout:
                    best_requests.clear()
                    best_requests.append(request)
                    best_klout = klout
        if not best_requests:
            return
        best_requests.sort(key=lambda request: request._creation_id)
        return best_requests[0]

    def get_most_important_situation_for_sim(self, sim):
        request = self.get_most_important_request_for_sim(sim)
        if request is None:
            return
        return request._situation

    @property
    def high_frequency_spawn(self):
        return self._high_freq_spawn_on

    def lock_high_frequency_spawn(self):
        logger.debug('Lock high frequency spawn {}', self._high_freq_spawn_locked_ref_count)
        self._high_freq_spawn_on = True
        self._next_spawn_time = services.time_service().sim_now

    def unlock_high_frequency_spawn(self):
        if self._high_freq_spawn_locked_ref_count > 0:
            pass
        else:
            logger.error('Unbalanced call to unlock_high_frequency_spawn')
        logger.debug('Unlock high frequency spawn {}', self._high_freq_spawn_locked_ref_count)

    @classmethod
    def are_mutually_exclusive(cls, cat1, cat2):
        cls._construct_exclusivity()
        key = cat1 | cat2
        rule = cls._exclusivity_rules.get(key, None)
        return rule

    def spawning_freeze(self, value):
        self._spawning_freeze_enabled = value

    def cap_cheat(self, value):
        self._cap_cheat_enabled = value

    @classmethod
    def _construct_exclusivity(cls):
        if cls._exclusivity_rules is not None:
            return
        cls._exclusivity_rules = {}
        for rule in cls.EXCLUSIVITY_RULES:
            cat1 = rule[0]
            cat2 = rule[1]
            key = cat1 | cat2
            if cls._exclusivity_rules.get(key) is not None:
                logger.error('Duplicate situation exclusivity rule for {} and {}', cat1, cat2)
            cls._exclusivity_rules[key] = rule

    def _update(self):
        if self._started == False:
            return
        with situations.situation_manager.DelayedSituationDestruction():
            self._update_number_of_npcs_on_lot()
            self._assign_instanced_sims_to_unfulfilled_requests()
            self._consider_spawn()
            self._monitor_npc_soft_cap()
            self._check_for_tardy_requests()

    def _update_number_of_npcs_on_lot(self):
        self._number_of_npcs_on_lot = 0
        self._number_of_npcs_leaving = 0
        for sim in services.sim_info_manager().instanced_sims_gen():
            while sim.sim_info.is_npc:
                if self._sim_is_leaving(sim):
                    pass

    def _assign_instanced_sims_to_unfulfilled_requests(self):
        with situations.situation_manager.DelayedSituationDestruction():
            all_candidate_sim_ids = set()
            for sim in services.sim_info_manager().instanced_sims_gen():
                if not sim.is_simulating:
                    pass
                if not sim.visible_to_client:
                    pass
                all_candidate_sim_ids.add(sim.id)
            if len(all_candidate_sim_ids) == 0:
                return
            sim_filter_service = services.sim_filter_service()
            for unfulfilled_index in range(Bouncer.MAX_UNFULFILLED_INDEX):
                candidate_requests = list(self._unfulfilled_requests[unfulfilled_index])
                sim_request_score_heap = []
                for request in candidate_requests:
                    if request._requires_spawning:
                        pass
                    candidate_sim_ids = {sim_id for sim_id in all_candidate_sim_ids if self._can_assign_sim_id_to_request(sim_id, request)}
                    if request._constrained_sim_ids:
                        candidate_sim_ids = candidate_sim_ids & request._constrained_sim_ids
                    if not candidate_sim_ids:
                        pass
                    filter_results = sim_filter_service.submit_filter(request._sim_filter, callback=None, sim_constraints=list(candidate_sim_ids), blacklist_sim_ids=request._get_blacklist(), requesting_sim_info=request._requesting_sim_info, allow_yielding=False)
                    for filter_result in filter_results:
                        heapq.heappush(sim_request_score_heap, SimRequestScore(sim_id=filter_result.sim_info.id, request=request, score=filter_result.score))
                while sim_request_score_heap:
                    sim_request_score = heapq.heappop(sim_request_score_heap)
                    request = sim_request_score.request
                    if request._is_fulfilled:
                        continue
                    sim = services.object_manager().get(sim_request_score.sim_id)
                    if sim is None:
                        continue
                    while self._can_assign_sim_to_request(sim, request):
                        if request._is_factory:
                            request = request._create_request(sim)
                            self.submit_request(request)
                        self._assign_sim_to_request(sim, request)
                        continue
            for (situation, situation_data) in self._situation_to_bouncer_situation_data.items():
                while not situation_data.first_assignment_pass_completed:
                    situation.on_first_assignment_pass_completed()
                    situation_data.on_first_assignment_pass_completed()

    def _assign_sim_to_request(self, sim, request):
        with situations.situation_manager.DelayedSituationDestruction():
            data = self._sim_to_bouncer_sim_data.setdefault(sim, BouncerSimData(self, sim))
            excluded = data.add_request(request)
            request._assign_sim(sim)
            if self._spawning_request == request:
                self._spawning_request = None
                self._spawning_sim_info = None
            else:
                self._unfulfilled_requests[request._unfulfilled_index].remove(request)
            self._fulfilled_requests.append(request)
            for ex_request in excluded:
                self._unassign_sim_from_request_and_optionally_withdraw(sim, ex_request)

    def _unassign_sim_from_request(self, sim, request, silently=False):
        data = self._sim_to_bouncer_sim_data.get(sim, None)
        if data:
            data.remove_request(request)
        request._unassign_sim(sim, silently)

    def _unassign_sim_from_request_and_optionally_withdraw(self, sim, request, silently=False):
        self._unassign_sim_from_request(sim, request, silently)
        if request._status != BouncerRequestStatus.DESTROYED and request._is_obsolete:
            self.withdraw_request(request)

    def _can_assign_sim_id_to_request(self, sim_id, new_request):
        sim = services.object_manager().get(sim_id)
        if sim is None:
            return True
        return self._can_assign_sim_to_request(sim, new_request)

    def _can_assign_sim_to_request(self, sim, new_request):
        if not new_request._can_assign_sim_to_request(sim):
            return False
        data = self._sim_to_bouncer_sim_data.get(sim, None)
        if data is None:
            return True
        return data.can_assign_to_request(new_request)

    def _consider_spawn(self):
        if self._spawning_freeze_enabled:
            return
        if self._spawning_request is not None:
            return
        if self._next_spawn_time > services.time_service().sim_now:
            return
        active_household = services.active_household()
        if active_household is None:
            return
        active_household_sim_ids = {sim_info.sim_id for sim_info in active_household.sim_info_gen()}
        active_lot_household = services.current_zone().get_active_lot_owner_household()
        if active_lot_household is None:
            active_lot_household_sim_ids = set()
        else:
            active_lot_household_sim_ids = {sim_info.sim_id for sim_info in active_lot_household.sim_info_gen()}
        only_spawn_game_breakers = self._number_of_npcs_on_lot >= services.get_zone_situation_manager().npc_soft_cap
        during_zone_spin_up = not services.current_zone().is_zone_running
        for unfulfilled_index in range(Bouncer.MAX_UNFULFILLED_INDEX):
            requests = self._unfulfilled_requests[unfulfilled_index]
            if not requests:
                pass
            if only_spawn_game_breakers and requests[0]._request_priority != BouncerRequestPriority.GAME_BREAKER:
                pass
            requests = [request for request in requests if request._can_spawn_now(during_zone_spin_up)]
            if not requests:
                pass
            request = sims4.random.random.choice(requests)
            self._spawning_request = request
            self._unfulfilled_requests[unfulfilled_index].remove(request)
            request._status = BouncerRequestStatus.SPAWN_REQUESTED
            sim_constraints = list(request._constrained_sim_ids) if request._constrained_sim_ids else None
            blacklist = set()
            blacklist.update(request._get_blacklist())
            if request.common_blacklist_categories & SituationCommonBlacklistCategory.ACTIVE_HOUSEHOLD:
                blacklist.update(active_household_sim_ids)
            if request.common_blacklist_categories & SituationCommonBlacklistCategory.ACTIVE_LOT_HOUSEHOLD:
                blacklist.update(active_lot_household_sim_ids)
            services.sim_filter_service().submit_matching_filter(1, request._sim_filter, self._spawn_request_callback, callback_event_data=request, sim_constraints=sim_constraints, continue_if_constraints_fail=request._continue_if_constraints_fail, blacklist_sim_ids=blacklist, requesting_sim_info=request._requesting_sim_info)
            break
        if self._high_freq_spawn_on and self._high_freq_spawn_locked_ref_count == 0:
            logger.debug('high frequency spawn turning off')
            self._high_freq_spawn_on = False
            client = services.client_manager().get_first_client()
            if client:
                output = sims4.commands.AutomationOutput(client.id)
                if output:
                    output('SituationSpawning; Success:True')

    def _check_for_tardy_requests(self):
        for unfulfilled_index in range(Bouncer.MAX_UNFULFILLED_INDEX):
            requests = list(self._unfulfilled_requests[unfulfilled_index])
            for request in requests:
                while request._is_tardy:
                    request._situation.on_tardy_request(request)
                    if request._status != BouncerRequestStatus.DESTROYED:
                        request._reset_tardy()

    def _sim_is_leaving(self, sim):
        return len(sim.get_running_and_queued_interactions_by_tag(self.LEAVING_INTERACTION_TAGS)) > 0

    def _is_request_with_assigned_npc_who_is_not_leaving(self, request):
        sim = request.assigned_sim
        if sim is None or not sim.sim_info.is_npc or sim.sim_info.lives_here:
            return False
        return self._sim_is_leaving(sim) == False

    def _is_request_for_npc(self, request):
        sim = services.object_manager().get(request.requested_sim_id)
        if sim is None:
            return True
        return sim.sim_info.is_npc

    def _monitor_npc_soft_cap(self):
        if self._cap_cheat_enabled:
            return
        if services.active_household() is None:
            return
        if not services.current_zone().is_zone_running:
            return
        situation_manager = services.get_zone_situation_manager()
        if self._number_of_npcs_on_lot > situation_manager.npc_soft_cap:
            situation_manager.expedite_leaving()
        num_here_but_not_leaving = self._number_of_npcs_on_lot - self._number_of_npcs_leaving
        excess_npcs_not_leaving = num_here_but_not_leaving - situation_manager.npc_soft_cap
        if excess_npcs_not_leaving > 0:
            self._make_npcs_leave_now_must_run(excess_npcs_not_leaving)
        elif excess_npcs_not_leaving == 0:
            unfulfilled_heap = self._get_unfulfilled_request_heap_by_best_klout(filter_func=self._is_request_for_npc)
            fulfilled_heap = self._get_assigned_request_heap_by_worst_klout(filter_func=self._is_request_with_assigned_npc_who_is_not_leaving)
            if unfulfilled_heap and fulfilled_heap:
                best_unfulfilled = heapq.heappop(unfulfilled_heap)
                worst_fulfilled = heapq.heappop(fulfilled_heap)
                if best_unfulfilled.klout < worst_fulfilled.klout:
                    situation_manager.make_sim_leave_now_must_run(worst_fulfilled.request.assigned_sim)

    def _get_assigned_request_heap_by_worst_klout(self, filter_func=None):
        klout_heap = []
        for sim_data in self._sim_to_bouncer_sim_data.values():
            request = sim_data.get_request_with_best_klout()
            if request is None:
                pass
            if filter_func is not None and not filter_func(request):
                pass
            heapq.heappush(klout_heap, _WorstRequestKlout(request=request, klout=request._get_request_klout()))
        return klout_heap

    def _get_unfulfilled_request_heap_by_best_klout(self, filter_func=None):
        klout_heap = []
        for unfulfilled_index in range(Bouncer.MAX_UNFULFILLED_INDEX):
            requests = self._unfulfilled_requests[unfulfilled_index]
            for request in requests:
                klout = request._get_request_klout()
                while klout is not None:
                    if filter_func is not None and not filter_func(request):
                        pass
                    heapq.heappush(klout_heap, _BestRequestKlout(request=request, klout=klout))
        return klout_heap

    def _make_npcs_leave_now_must_run(self, sim_count):
        situation_manager = services.get_zone_situation_manager()
        klout_heap = self._get_assigned_request_heap_by_worst_klout(filter_func=self._is_request_with_assigned_npc_who_is_not_leaving)
        while klout_heap:
            while sim_count > 0:
                worst = heapq.heappop(klout_heap)
                situation_manager.make_sim_leave_now_must_run(worst.request.assigned_sim)
                sim_count -= 1

    def _spawn_request_callback(self, sim_infos, request):
        logger.debug('-'*100)
        logger.debug('_spawn_request_callback for sims {} for request {}', sim_infos, request)
        if not self._high_freq_spawn_on:
            self._next_spawn_time = services.time_service().sim_now + self._spawn_cooldown
        if request._status == BouncerRequestStatus.DESTROYED:
            return
        if request != self._spawning_request:
            logger.error('_spawn_request_callback for wrong request!')
            return
        current_zone = services.current_zone()
        if current_zone.is_zone_shutting_down:
            return
        during_zone_spin_up = not current_zone.is_zone_running
        if sim_infos:
            sim_info = sim_infos[0]
            if during_zone_spin_up and not request.should_preroll_during_zone_spin_up:
                services.sim_info_manager().exclude_sim_info_from_preroll(sim_info)
            self._spawning_sim_info = sim_info
            sims.sim_spawner.SimSpawner.spawn_sim(sim_info, None, sim_spawner_tags=request.spawner_tags(during_zone_spin_up), spawn_point_option=request.spawn_point_option, spawn_action=request._spawn_action)
            raw_spawner_tags = request.raw_spawner_tags()
            sim_info.spawner_tags = raw_spawner_tags
            sim_info.spawn_point_id = None
            sim_info.spawn_point_option = SpawnPointOption.SPAWN_ANY_POINT_WITH_SAVED_TAGS
        else:
            request._situation.on_failed_to_spawn_sim_for_request(request)
            self.withdraw_request(request)

    def on_sim_creation(self, sim):
        data = self._sim_to_bouncer_sim_data.get(sim, None)
        if data is not None:
            return
        logger.debug('on_sim_creation sim {}, spawning sim {}', sim, self._spawning_sim_info)
        was_assigned = False
        if sim.sim_info is self._spawning_sim_info:
            if self._spawning_request is not None and self._spawning_request._status != BouncerRequestStatus.DESTROYED:
                self._assign_sim_to_request(sim, self._spawning_request)
                was_assigned = True
            self._spawning_request = None
            self._spawning_sim_info = None
        if was_assigned and sim.sim_info.is_npc and services.current_zone().is_zone_running:
            sim.run_full_autonomy_next_ping()
        self._assign_instanced_sims_to_unfulfilled_requests()

    def _sim_weakref_callback(self, sim):
        logger.debug('Bouncer:_sim_weakref_callback: {}', sim, owner='sscholl')
        data = self._sim_to_bouncer_sim_data.get(sim, None)
        if data is None:
            return
        requests_sim_was_in = list(data.requests)
        data.destroy()
        self._sim_to_bouncer_sim_data.pop(sim)
        for request in requests_sim_was_in:
            self._unassign_sim_from_request_and_optionally_withdraw(sim, request)

    def _all_requests_gen(self):
        for unfulfilled_index in range(Bouncer.MAX_UNFULFILLED_INDEX):
            for request in self._unfulfilled_requests[unfulfilled_index]:
                yield request
        if self._spawning_request is not None:
            yield self._spawning_request
        for request in self._fulfilled_requests:
            yield request

