from date_and_time import date_and_time_from_week_time
from sims4 import PropertyStreamWriter
from sims4.math import clamp
from sims4.service_manager import Service
from situations.situation_guest_list import SituationGuestList, SituationGuestInfo, SituationInvitationPurpose
import clock
import services
import sims4.log
logger = sims4.log.Logger('ServiceNPCManager')

class ServiceNpcSituationCreationParams:
    __qualname__ = 'ServiceNpcSituationCreationParams'

    def __init__(self, hiring_household, service_npc_type, user_specified_data_id, is_recurring):
        self.hiring_household = hiring_household
        self.service_npc_type = service_npc_type
        self.user_specified_data_id = user_specified_data_id
        self.is_recurring = is_recurring

class ServiceNpcService(Service):
    __qualname__ = 'ServiceNpcService'

    def __init__(self):
        self._service_npc_requests = []
        self._auto_scheduled_services_enabled = True

    def request_service(self, household, service_npc_tuning, from_load=False, user_specified_data_id=None, is_recurring=False):
        if self._is_service_already_in_request_list(household, service_npc_tuning):
            return
        service_record = household.get_service_npc_record(service_npc_tuning.guid64)
        if service_record.hired and not from_load:
            return
        service_record.hired = True
        service_record.recurring = is_recurring
        service_record.user_specified_data_id = user_specified_data_id
        if from_load:
            min_alarm_time_span = None
        else:
            min_alarm_time_span = clock.interval_in_sim_minutes(service_npc_tuning.request_offset)
        min_duration_remaining = service_npc_tuning.min_duration_left_for_arrival_on_lot()
        situation_creation_params = ServiceNpcSituationCreationParams(household, service_npc_tuning, user_specified_data_id, is_recurring)
        service_npc_request = service_npc_tuning.work_hours(start_callback=self._send_service_npc, min_alarm_time_span=min_alarm_time_span, min_duration_remaining=min_duration_remaining, extra_data=situation_creation_params)
        self._service_npc_requests.append(service_npc_request)
        request_trigger_time = service_npc_request.get_alarm_finishing_time()
        return request_trigger_time

    def _send_service_npc(self, scheduler, alarm_data, situation_creation_params):
        household = situation_creation_params.hiring_household
        service_npc_type = situation_creation_params.service_npc_type
        if not self._auto_scheduled_services_enabled and service_npc_type.auto_schedule_on_client_connect():
            return
        service_record = household.get_service_npc_record(service_npc_type.guid64)
        preferred_sim_id = service_record.get_preferred_sim_id()
        situation_type = service_npc_type.situation
        user_specified_data_id = situation_creation_params.user_specified_data_id
        now = services.time_service().sim_now
        if service_record.time_last_started_service is not None and alarm_data.start_time is not None:
            alarm_start_time_absolute = date_and_time_from_week_time(now.week(), alarm_data.start_time)
            if service_record.time_last_started_service >= alarm_start_time_absolute:
                return
        service_record.time_last_started_service = now
        service_record.time_last_finished_service = None
        duration = alarm_data.end_time - now.time_since_beginning_of_week()
        min_duration = service_npc_type.min_duration_left_for_arrival_on_lot()
        if duration < min_duration:
            service_npc_type.fake_perform(household)
            return
        min_duration = service_npc_type.min_work_duration()
        max_duration = service_npc_type.max_work_duration()
        duration = clamp(min_duration, duration.in_minutes(), max_duration)
        guest_list = SituationGuestList(True)
        if preferred_sim_id is not None:
            guest_list.add_guest_info(SituationGuestInfo.construct_from_purpose(preferred_sim_id, situation_type.default_job(), SituationInvitationPurpose.PREFERRED))
        situation_creation_params_writer = PropertyStreamWriter()
        situation_creation_params_writer.write_uint64('household_id', household.id)
        situation_creation_params_writer.write_uint64('service_npc_type_id', service_npc_type.guid64)
        if user_specified_data_id is not None:
            situation_creation_params_writer.write_uint64('user_specified_data_id', user_specified_data_id)
        situation_creation_params_writer.write_bool('is_recurring', situation_creation_params.is_recurring)
        self._situation_id = services.get_zone_situation_manager().create_situation(situation_type, guest_list, user_facing=False, duration_override=duration, custom_init_writer=situation_creation_params_writer)

    def cancel_service(self, household, service_npc_type):
        for request in tuple(self._service_npc_requests):
            situation_creation_params = request.extra_data
            schedule_household = situation_creation_params.hiring_household
            request_service_npc_tuning = situation_creation_params.service_npc_type
            while household == schedule_household and request_service_npc_tuning is service_npc_type:
                request.destroy()
                self._service_npc_requests.remove(request)
        service_record = household.get_service_npc_record(service_npc_type.guid64, add_if_no_record=False)
        if service_record is not None:
            service_record.hired = False
            service_record.time_last_started_service = None
            service_record.time_last_finished_service = None
            service_record.is_recurring = False

    def _is_service_already_in_request_list(self, household, service_npc_type):
        for request in self._service_npc_requests:
            situation_creation_params = request.extra_data
            schedule_household = situation_creation_params.hiring_household
            request_service_npc_tuning = situation_creation_params.service_npc_type
            while household == schedule_household and request_service_npc_tuning is service_npc_type:
                return True
        return False

    def on_all_households_and_sim_infos_loaded(self, client):
        household = client.household
        if household is None:
            return
        if household.id != services.active_lot().owner_household_id:
            return
        all_hired_service_npcs = household.get_all_hired_service_npcs()
        for service_npc_resource_key in services.service_npc_manager().types:
            service_npc_tuning = services.service_npc_manager().get(service_npc_resource_key)
            while service_npc_tuning.auto_schedule_on_client_connect() or service_npc_tuning.guid64 in all_hired_service_npcs:
                is_recurring = False
                user_specified_data_id = None
                if service_npc_tuning.auto_schedule_on_client_connect():
                    is_recurring = True
                else:
                    service_npc_record = household.get_service_npc_record(service_npc_tuning.guid64, add_if_no_record=False)
                    if service_npc_record:
                        is_recurring = service_npc_record.recurring
                        user_specified_data_id = service_npc_record.user_specified_data_id
                self.request_service(household, service_npc_tuning, from_load=True, is_recurring=is_recurring, user_specified_data_id=user_specified_data_id)

    def on_cleanup_zone_objects(self, client):
        time_of_last_save = services.game_clock_service().time_of_last_save()
        now = services.time_service().sim_now
        self._fake_perform_services_if_necessary(time_of_last_save, now)

    def _fake_perform_services_if_necessary(self, time_period_start, now):
        for scheduler in self._service_npc_requests:
            situation_creation_params = scheduler.extra_data
            household = situation_creation_params.hiring_household
            service_npc_type = situation_creation_params.service_npc_type
            service_record = household.get_service_npc_record(service_npc_type.guid64, add_if_no_record=False)
            if service_record is None:
                pass
            (time_until_service_arrives, alarm_data_entries) = scheduler.time_until_next_scheduled_event(time_period_start, schedule_immediate=True)
            if len(alarm_data_entries) != 1:
                logger.error('There are {} alarm data entries instead of 1 when fake performing services: {}', len(alarm_data_entries), alarm_data_entries, owner='bhill')
            alarm_data = alarm_data_entries[0]
            time_service_starts = time_period_start + time_until_service_arrives
            time_service_would_end = alarm_data.end_time
            min_service_duration = service_npc_type.min_duration_left_for_arrival_on_lot()
            if now + min_service_duration <= time_service_would_end:
                pass
            if service_record.time_last_started_service is not None and service_record.time_last_started_service >= time_service_starts:
                pass
            service_npc_type.fake_perform(household)
            service_record.time_last_started_service = time_service_starts
            service_record.time_last_finished_service = min(now, time_service_would_end)
            while not service_record.recurring:
                self.cancel_service(household, service_npc_type)

