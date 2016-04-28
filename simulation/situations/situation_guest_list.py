from situations.bouncer.bouncer_request import RequestSpawningOption
from situations.bouncer.bouncer_types import BouncerRequestPriority
import enum
import services
import situations.situation_types
import world

class SituationInvitationPurpose(enum.Int, export=False):
    __qualname__ = 'SituationInvitationPurpose'
    INVITED = 1
    HIRED = 2
    PREFERRED = 3
    CAREER = 4
    WALKBY = 5
    HOSTING = 6
    AUTO_FILL = 100
    DEFAULT = 101
    LEAVE = 102

class SituationGuestInfo:
    __qualname__ = 'SituationGuestInfo'

    @classmethod
    def construct_from_purpose(cls, sim_id, job_type, invitation_purpose):
        if invitation_purpose == SituationInvitationPurpose.INVITED or invitation_purpose == SituationInvitationPurpose.CAREER or invitation_purpose == SituationInvitationPurpose.PREFERRED:
            request_priority = BouncerRequestPriority.VIP
        elif invitation_purpose == SituationInvitationPurpose.HOSTING:
            request_priority = BouncerRequestPriority.HOSTING
        elif invitation_purpose == SituationInvitationPurpose.HIRED:
            request_priority = BouncerRequestPriority.AUTO_FILL_PLUS
        elif invitation_purpose == SituationInvitationPurpose.AUTO_FILL or invitation_purpose == SituationInvitationPurpose.WALKBY:
            request_priority = BouncerRequestPriority.AUTO_FILL
        elif invitation_purpose == SituationInvitationPurpose.LEAVE:
            request_priority = BouncerRequestPriority.LEAVE
        else:
            request_priority = BouncerRequestPriority.DEFAULT_JOB
        spawning_option = RequestSpawningOption.DONT_CARE
        common_blacklist_categories = 0
        if sim_id == 0 and (invitation_purpose == SituationInvitationPurpose.HIRED or invitation_purpose == SituationInvitationPurpose.AUTO_FILL or invitation_purpose == SituationInvitationPurpose.WALKBY):
            if not (invitation_purpose == SituationInvitationPurpose.AUTO_FILL and job_type.sim_auto_invite_allow_instanced_sim):
                spawning_option = RequestSpawningOption.MUST_SPAWN
            common_blacklist_categories = situations.situation_types.SituationCommonBlacklistCategory.ACTIVE_HOUSEHOLD | situations.situation_types.SituationCommonBlacklistCategory.ACTIVE_LOT_HOUSEHOLD
        expectation_preference = invitation_purpose == SituationInvitationPurpose.INVITED
        accept_alternate_sim = False
        if sim_id != 0 and job_type.no_show_action == situations.situation_types.JobHolderNoShowAction.REPLACE_THEM and (invitation_purpose == SituationInvitationPurpose.PREFERRED or invitation_purpose == SituationInvitationPurpose.HIRED):
            accept_alternate_sim = True
        guest_info = SituationGuestInfo(sim_id, job_type, spawning_option, request_priority, expectation_preference, accept_alternate_sim, common_blacklist_categories=common_blacklist_categories)
        if invitation_purpose == SituationInvitationPurpose.HIRED:
            guest_info.hire_cost = job_type.hire_cost
        return guest_info

    def __init__(self, sim_id, job_type, spawning_option, request_priority, expectation_preference=False, accept_alternate_sim=False, common_blacklist_categories=0):
        self.sim_id = sim_id
        self.job_type = job_type
        self.spawning_option = spawning_option
        self.request_priority = request_priority
        self.expectation_preference = expectation_preference
        self.accept_alternate_sim = accept_alternate_sim
        self.persisted_role_state_type = None
        self.hire_cost = 0
        self.common_blacklist_categories = common_blacklist_categories
        if job_type.game_breaker:
            self.request_priority = BouncerRequestPriority.GAME_BREAKER
        elif job_type.elevated_importance:
            if self.request_priority == BouncerRequestPriority.VIP:
                self.request_priority = BouncerRequestPriority.VIP_PLUS
            elif self.request_priority == BouncerRequestPriority.AUTO_FILL:
                self.request_priority = BouncerRequestPriority.AUTO_FILL_PLUS
        self.spawn_during_zone_spin_up = False

    def _set_persisted_role_state_type(self, persisted_role_state_type):
        self.persisted_role_state_type = persisted_role_state_type

class SituationGuestList:
    __qualname__ = 'SituationGuestList'

    def __init__(self, invite_only=False, host_sim_id=0, filter_requesting_sim_id=0):
        self._job_type_to_guest_infos = {}
        self._invite_only = invite_only
        self._host_sim_id = host_sim_id
        self.filter_requesting_sim_id = filter_requesting_sim_id

    def _destroy(self):
        self._job_type_to_guest_infos = None

    @property
    def invite_only(self):
        return self._invite_only

    @property
    def host_sim_id(self):
        return self._host_sim_id

    @property
    def host_sim(self):
        return services.object_manager().get(self._host_sim_id)

    def get_filter_requesting_sim_info(self):
        requesting_sim_info = services.sim_info_manager().get(self.filter_requesting_sim_id)
        if requesting_sim_info is None:
            requesting_sim_info = services.sim_info_manager().get(self._host_sim_id)
        return requesting_sim_info

    def get_traveler(self):
        sim = self.host_sim
        if sim is not None and sim.is_selectable:
            return sim
        for guest_infos in self._job_type_to_guest_infos.values():
            for guest_info in guest_infos:
                if guest_info.sim_id == 0:
                    pass
                sim = services.object_manager().get(guest_info.sim_id)
                while sim is not None and sim.is_selectable:
                    return sim

    def get_other_travelers(self, traveling_sim):
        traveling_sim_ids = set()
        npc_guest_infos = []
        sim_info_manager = services.sim_info_manager()
        for guest_infos in self._job_type_to_guest_infos.values():
            for guest_info in guest_infos:
                while not guest_info.sim_id == 0:
                    if guest_info.sim_id == traveling_sim.id:
                        pass
                    sim_info = sim_info_manager.get(guest_info.sim_id)
                    while sim_info is not None:
                        if sim_info.is_selectable:
                            traveling_sim_ids.add(guest_info.sim_id)
                        else:
                            npc_guest_infos.append(guest_info)
        max_allowed = world.spawn_point.WorldSpawnPoint.SPAWN_POINT_SLOTS - 1
        npc_guest_infos.sort(key=lambda guest_info: guest_info.request_priority)
        for guest_info in npc_guest_infos:
            if len(traveling_sim_ids) < max_allowed:
                traveling_sim_ids.add(guest_info.sim_id)
            else:
                break
        return list(traveling_sim_ids)

    def add_guest_info(self, guest_info):
        guest_infos = self._job_type_to_guest_infos.setdefault(guest_info.job_type, [])
        guest_infos.append(guest_info)

    def get_guest_info_for_sim(self, sim):
        return self.get_guest_info_for_sim_id(sim.id)

    def get_guest_info_for_sim_id(self, sim_id):
        for guest_infos in self._job_type_to_guest_infos.values():
            for guest_info in guest_infos:
                while guest_info.sim_id == sim_id:
                    return guest_info

    def get_guest_infos_for_job(self, job_type):
        return list(self._job_type_to_guest_infos.get(job_type, []))

    def get_set_of_jobs(self):
        return {job_type for job_type in self._job_type_to_guest_infos.keys()}

    def get_hire_cost(self):
        total_hire_cost = 0
        for guest_infos in self._job_type_to_guest_infos.values():
            for guest_info in guest_infos:
                total_hire_cost += guest_info.hire_cost
        return total_hire_cost

    def guest_info_gen(self):
        for guest_infos in self._job_type_to_guest_infos.values():
            for guest_info in guest_infos:
                yield guest_info

    def invited_sim_infos_gen(self):
        for guest_infos in self._job_type_to_guest_infos.values():
            for guest_info in guest_infos:
                while guest_info.sim_id is not None and guest_info.sim_id != 0:
                    sim_info = services.sim_info_manager().get(guest_info.sim_id)
                    if sim_info is not None:
                        yield sim_info

    def invited_guest_infos_gen(self):
        for guest_infos in self._job_type_to_guest_infos.values():
            for guest_info in guest_infos:
                while guest_info.sim_id is not None and guest_info.sim_id != 0:
                    yield guest_info

