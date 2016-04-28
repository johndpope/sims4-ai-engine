from objects import ALL_HIDDEN_REASONS
from sims4.tuning.tunable import TunableSimMinute
from sims4.tuning.tunable_base import FilterTag
from situations.bouncer.bouncer_types import BouncerRequestStatus, BouncerRequestPriority, BouncerExclusivityOption, RequestSpawningOption
from uid import UniqueIdGenerator
import clock
import services
import sims4.log
import situations.bouncer.bouncer
import world
logger = sims4.log.Logger('Bouncer')

class BouncerRequest:
    __qualname__ = 'BouncerRequest'
    TARDY_SIM_TIME = TunableSimMinute(description='Amount of time until a sim coming to a situation is considered tardy', default=30, tuning_filter=FilterTag.EXPERT_MODE)
    _get_next_creation_id = UniqueIdGenerator(1)

    def __init__(self, situation, callback_data, job_type, request_priority, user_facing, exclusivity, requested_sim_id=0, accept_alternate_sim=False, blacklist_sim_ids=None, spawning_option=RequestSpawningOption.DONT_CARE, requesting_sim_info=None, expectation_preference=False, loaded=False, common_blacklist_categories=0, spawn_during_zone_spin_up=False):
        self._situation = situation
        self._callback_data = callback_data
        self._job_type = job_type
        self._sim_filter = job_type.filter
        self._spawner_tags = job_type.sim_spawner_tags
        self._spawn_action = job_type.sim_spawn_action
        self._spawn_point_option = job_type.sim_spawner_leave_option
        self._requested_sim_id = requested_sim_id
        self._constrained_sim_ids = {requested_sim_id} if requested_sim_id != 0 else None
        self._continue_if_constraints_fail = accept_alternate_sim
        self._blacklist_sim_ids = blacklist_sim_ids
        self._status = BouncerRequestStatus.INITIALIZED
        self._sim = None
        self._user_facing = user_facing
        self._request_priority = request_priority
        self._spawning_option = spawning_option
        self._requesting_sim_info = requesting_sim_info
        self._exclusivity = exclusivity
        self._creation_id = self._get_next_creation_id()
        self._expectation_preference = expectation_preference
        self._loaded = loaded
        self._common_blacklist_categories = common_blacklist_categories
        self._spawn_during_zone_spin_up = spawn_during_zone_spin_up
        if self._is_explicit:
            unfulfilled_index = 0
        else:
            unfulfilled_index = BouncerRequestPriority.COUNT*2
        unfulfilled_index += self._request_priority*2
        if not self._user_facing:
            unfulfilled_index += 1
        self._unfulfilled_index = unfulfilled_index

    def _destroy(self):
        self._status = BouncerRequestStatus.DESTROYED
        self._sim = None

    def __str__(self):
        return 'Request(situation: {}, sim id: {}, filter: {})'.format(self._situation, self._requested_sim_id, self._sim_filter)

    def _submit(self):
        self._status = BouncerRequestStatus.SUBMITTED
        self._reset_tardy()

    def _can_assign_sim_to_request(self, sim):
        return True

    def _assign_sim(self, sim, silently=False):
        if self._sim is not None:
            raise AssertionError('Attempting to assign sim: {} to a request: {} that already has a sim: {}'.format(sim, self, self._sim))
        self._status = BouncerRequestStatus.FULFILLED
        self._sim = sim
        if silently == False:
            self._situation.on_sim_assigned_to_request(sim, self)

    def _unassign_sim(self, sim, silently=False):
        if self._is_sim_assigned_to_request(sim) == False:
            raise AssertionError('Attempting to unassign sim {} from a request {} that it is not assigned to{}'.format(sim, self))
        self._sim = None
        if silently == False:
            self._situation.on_sim_unassigned_from_request(sim, self)

    def _change_assigned_sim(self, new_sim):
        old_sim = self._sim
        self._unassign_sim(old_sim, silently=True)
        self._assign_sim(new_sim, silently=True)
        self._situation.on_sim_replaced_in_request(old_sim, new_sim, self)

    def _is_sim_assigned_to_request(self, sim):
        return self._sim is sim

    @property
    def _assigned_sim(self):
        return self._sim

    @property
    def _allows_spawning(self):
        if self._spawning_option == RequestSpawningOption.CANNOT_SPAWN:
            return False
        if self._requested_sim_id == 0:
            return True
        sim_info = services.sim_info_manager().get(self._requested_sim_id)
        if sim_info is None:
            return True
        if sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) is not None:
            return False
        return True

    def _can_spawn_now(self, during_zone_spin_up_service):
        if not self._allows_spawning:
            return False
        if not during_zone_spin_up_service:
            return True
        return self._spawn_during_zone_spin_up or self._situation.spawn_sims_during_zone_spin_up

    @property
    def _requires_spawning(self):
        return self._spawning_option == RequestSpawningOption.MUST_SPAWN

    def spawner_tags(self, during_zone_spin_up=False):
        if during_zone_spin_up and self._situation.is_traveling_situation:
            return (world.spawn_point.SpawnPoint.ARRIVAL_SPAWN_POINT_TAG,)
        return self._spawner_tags

    def raw_spawner_tags(self):
        return self._spawner_tags

    @property
    def should_preroll_during_zone_spin_up(self):
        return not self._situation.is_traveling_situation

    @property
    def spawn_point_option(self):
        return self._spawn_point_option

    @property
    def _initiating_sim_info(self):
        return self._situation.initiating_sim_info

    def _get_blacklist(self):
        if self._blacklist_sim_ids:
            blacklist = set(self._blacklist_sim_ids)
        else:
            blacklist = set()
        if self._request_priority == BouncerRequestPriority.AUTO_FILL or self._request_priority == BouncerRequestPriority.AUTO_FILL_PLUS:
            blacklist = blacklist | services.get_zone_situation_manager().get_auto_fill_blacklist()
        return blacklist

    @property
    def common_blacklist_categories(self):
        return self._common_blacklist_categories

    @property
    def _is_obsolete(self):
        return self._status == BouncerRequestStatus.FULFILLED and self._sim is None

    @property
    def _is_tardy(self):
        if self._status != BouncerRequestStatus.SUBMITTED:
            return False
        return self._tardy_time < services.time_service().sim_now

    def _reset_tardy(self):
        self._tardy_time = services.time_service().sim_now + clock.interval_in_sim_minutes(BouncerRequest.TARDY_SIM_TIME)

    @property
    def _is_fulfilled(self):
        return self._status == BouncerRequestStatus.FULFILLED

    @property
    def _is_explicit(self):
        return self._requested_sim_id != 0

    @property
    def _has_assigned_sims(self):
        return self._sim is not None

    @property
    def _must_assign_on_load(self):
        return self._loaded

    def _exclusivity_compare(self, other):
        rule = situations.bouncer.bouncer.Bouncer.are_mutually_exclusive(self._exclusivity, other._exclusivity)
        if rule is None:
            return 0

        def determine_result(trumping_category):
            if self._exclusivity == trumping_category:
                return 1
            return -1

        option = rule[2]
        if option == BouncerExclusivityOption.EXPECTATION_PREFERENCE:
            if self._expectation_preference and not other._expectation_preference:
                return determine_result(self._exclusivity)
            if not self._expectation_preference and other._expectation_preference:
                return determine_result(other._exclusivity)
            if self._expectation_preference and other._expectation_preference:
                if self._creation_id >= other._creation_id:
                    return determine_result(self._exclusivity)
                return determine_result(other._exclusivity)
            return determine_result(rule[0])
        if option == BouncerExclusivityOption.NONE:
            return determine_result(rule[0])
        if option == BouncerExclusivityOption.ERROR:
            logger.error('Unexpected Bouncer exclusivity pairing Request:{}, Request:{}. Tell SScholl', self, other)
            return determine_result(rule[0])
        if option == BouncerExclusivityOption.ALREADY_ASSIGNED:
            return determine_result(self._exclusivity)

    @property
    def _is_factory(self):
        return False

    def _get_request_klout(self):
        klout = self._request_priority*2
        if not self._user_facing:
            klout += 1
        return klout

    @property
    def callback_data(self):
        return self._callback_data

    def clone_for_replace(self, only_if_explicit=False):
        if only_if_explicit and not self._is_explicit:
            return
        request = BouncerRequest(self._situation, self._callback_data, self._job_type, self._request_priority, user_facing=self._user_facing, exclusivity=self._exclusivity, blacklist_sim_ids=self._blacklist_sim_ids, spawning_option=self._spawning_option, requesting_sim_info=self._requesting_sim_info)
        return request

    @property
    def assigned_sim(self):
        return self._assigned_sim

    @property
    def requested_sim_id(self):
        return self._requested_sim_id

    @property
    def is_factory(self):
        return self._is_factory

    @property
    def job_type(self):
        return self._job_type

    @property
    def spawning_option(self):
        return self._spawning_option

    @property
    def request_priority(self):
        return self._request_priority

    @property
    def expectation_preference(self):
        return self._expectation_preference

    @property
    def accept_alternate_sim(self):
        return self._continue_if_constraints_fail

class BouncerRequestFactory(BouncerRequest):
    __qualname__ = 'BouncerRequestFactory'

    def __init__(self, situation, callback_data, job_type, request_priority, user_facing, exclusivity, requesting_sim_info=None):
        super().__init__(situation, callback_data, job_type=job_type, request_priority=request_priority, user_facing=user_facing, exclusivity=exclusivity, requesting_sim_info=requesting_sim_info)

    @property
    def _allows_spawning(self):
        return False

    @property
    def _requires_spawning(self):
        return False

    def _is_sim_assigned_to_request(self, sim):
        return False

    def _assign_sim(self, sim, silently=False):
        raise NotImplementedError('Cannot assign sims to a request factory: {}'.format(self))

    def _unassign_sim(self, sim, silently=False):
        raise NotImplementedError('Cannot unassign sims from a request factory: {}'.format(self))

    def _change_assigned_sim(self, sim):
        raise NotImplementedError('Attempting to change_assigned_sim on a request factory:{}'.format(self))

    @property
    def _assigned_sims(self):
        pass

    @property
    def _is_tardy(self):
        return False

    @property
    def _is_obsolete(self):
        return False

    @property
    def _is_explicit(self):
        return False

    @property
    def _has_assigned_sims(self):
        return False

    @property
    def _is_factory(self):
        return True

    def _create_request(self, sim):
        request = BouncerRequest(self._situation, self._callback_data, self._job_type, self._request_priority, user_facing=self._user_facing, exclusivity=self._exclusivity, requested_sim_id=sim.id, blacklist_sim_ids=self._blacklist_sim_ids, spawning_option=RequestSpawningOption.CANNOT_SPAWN, requesting_sim_info=self._requesting_sim_info, expectation_preference=self._expectation_preference)
        return request

    def _get_request_klout(self):
        pass

    @property
    def assigned_sim(self):
        pass

    @property
    def requested_sim_id(self):
        return 0

    def clone_for_replace(self, only_if_explicit=False):
        pass

class BouncerFallbackRequestFactory(BouncerRequestFactory):
    __qualname__ = 'BouncerFallbackRequestFactory'

    def __init__(self, situation, callback_data, job_type, user_facing, exclusivity):
        super().__init__(situation, callback_data, job_type=job_type, request_priority=BouncerRequestPriority.DEFAULT_JOB, user_facing=user_facing, exclusivity=exclusivity)

class BouncerHostRequestFactory(BouncerRequestFactory):
    __qualname__ = 'BouncerHostRequestFactory'

    def __init__(self, situation, callback_data, job_type, user_facing, exclusivity, requesting_sim_info):
        super().__init__(situation, callback_data, job_type=job_type, request_priority=BouncerRequestPriority.HOSTING, user_facing=user_facing, exclusivity=exclusivity, requesting_sim_info=requesting_sim_info)

class BouncerNPCFallbackRequestFactory(BouncerRequestFactory):
    __qualname__ = 'BouncerNPCFallbackRequestFactory'

    def __init__(self, situation, callback_data, job_type, exclusivity, request_priority=BouncerRequestPriority.LEAVE):
        super().__init__(situation, callback_data, job_type=job_type, request_priority=request_priority, user_facing=False, exclusivity=exclusivity)

    def _can_assign_sim_to_request(self, sim):
        return sim.sim_info.is_npc and not sim.sim_info.lives_here

class BouncerPlayerVisitingNPCRequestFactory(BouncerRequestFactory):
    __qualname__ = 'BouncerPlayerVisitingNPCRequestFactory'

    def __init__(self, situation, callback_data, job_type, exclusivity):
        super().__init__(situation, callback_data=callback_data, job_type=job_type, request_priority=BouncerRequestPriority.VIP, user_facing=False, exclusivity=exclusivity)

    def _can_assign_sim_to_request(self, sim):
        return sim.is_selectable

