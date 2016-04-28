from random import Random
import math
import random
from date_and_time import TimeSpan
from sims4.math import MAX_UINT64
from sims4.service_manager import Service
import services
import sims4.log
logger = sims4.log.Logger('Career Save Game Data')

class CareerService(Service):
    __qualname__ = 'CareerService'

    def __init__(self):
        self._shuffled_career_list = None
        self._career_list_seed = None
        self._last_day_updated = None

    def load(self, zone_data=None):
        save_slot_data_msg = services.get_persistence_service().get_save_slot_proto_buff()
        if save_slot_data_msg.gameplay_data.HasField('career_choices_seed'):
            self._career_list_seed = save_slot_data_msg.gameplay_data.career_choices_seed

    def save(self, object_list=None, zone_data=None, open_street_data=None, save_slot_data=None):
        if self._career_list_seed is not None:
            save_slot_data.gameplay_data.career_choices_seed = self._career_list_seed

    def get_days_from_time(self, time):
        return math.floor(time.absolute_days())

    def get_seed(self, days_now):
        if self._career_list_seed is None:
            self._career_list_seed = random.randint(0, MAX_UINT64)
        return self._career_list_seed + days_now

    def get_career_list(self):
        career_list = []
        career_manager = services.get_instance_manager(sims4.resources.Types.CAREER)
        for career_id in career_manager.types:
            career_tuning = career_manager.get(career_id)
            career_list.append(career_tuning)
        return career_list

    def get_shuffled_career_list(self):
        time_now = services.time_service().sim_now
        days_now = self.get_days_from_time(time_now)
        if self._shuffled_career_list is None or self._last_day_updated != days_now:
            career_seed = self.get_seed(days_now)
            career_rand = Random(career_seed)
            self._last_day_updated = days_now
            self._shuffled_career_list = self.get_career_list()
            career_rand.shuffle(self._shuffled_career_list)
        return self._shuffled_career_list

    def restore_career_state(self):
        try:
            manager = services.sim_info_manager()
            zone = services.current_zone()
            zone_restored_sis = zone.should_restore_sis()
            career_sis = set()
            for sim in manager.instanced_sims_gen():
                sim_info = sim.sim_info
                if zone_restored_sis and sim_info.has_loaded_si_state:
                    pass
                if sim_info.is_npc:
                    if sim_info.is_at_home:
                        while True:
                            for career in sim_info.career_tracker.careers.values():
                                (time_to_work, start_time, end_time) = career.get_next_work_time(check_if_can_go_now=True)
                                while time_to_work == TimeSpan.ZERO:
                                    sim.set_allow_route_instantly_when_hitting_marks(True)
                                    career.start_new_career_session(start_time, end_time)
                                    result = career.push_go_to_work_affordance()
                                    if result:
                                        manager.set_sim_at_work(sim_info)
                                        career_sis.add(result.interaction)
                                    break
                        career = sim_info.career_tracker.get_at_work_career()
                        while career is not None:
                            if not sim_info.is_at_home:
                                logger.error("Loading {} who's at work/school for {} but not on home lot. Kicking them out.", sim_info, career)
                                career.leave_work_early()
                            result = career.push_go_to_work_affordance()
                            if result:
                                sim.set_allow_route_instantly_when_hitting_marks(True)
                                manager.set_sim_at_work(sim_info)
                                career_sis.add(result.interaction)
                else:
                    career = sim_info.career_tracker.get_at_work_career()
                    while career is not None:
                        if not sim_info.is_at_home:
                            logger.error("Loading {} who's at work/school for {} but not on home lot. Kicking them out.", sim_info, career)
                            career.leave_work_early()
                        result = career.push_go_to_work_affordance()
                        if result:
                            sim.set_allow_route_instantly_when_hitting_marks(True)
                            manager.set_sim_at_work(sim_info)
                            career_sis.add(result.interaction)
        except:
            logger.exception('Exception raised while trying to restore career interactions.', owner='tingyul')

