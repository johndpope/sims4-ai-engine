from date_and_time import DateAndTime

class ServiceNpcRecord:
    __qualname__ = 'ServiceNpcRecord'

    def __init__(self, service_id, household):
        self._service_id = service_id
        self._household = household
        self._preferred_service_sim_ids = set()
        self._fired_service_sim_ids = set()
        self.hired = False
        self.recurring = False
        self.time_last_started_service = None
        self.time_last_finished_service = None
        self.user_specified_data_id = None

    def add_fired_sim(self, sim_id):
        self._fired_service_sim_ids.add(sim_id)

    def add_preferred_sim(self, sim_id):
        return self._preferred_service_sim_ids.add(sim_id)

    def remove_preferred_sim(self, sim_id):
        if sim_id in self._preferred_service_sim_ids:
            self._preferred_service_sim_ids.remove(sim_id)

    def get_preferred_sim_id(self):
        if self._preferred_service_sim_ids:
            return next(iter(self._preferred_service_sim_ids), None)

    def save_npc_record(self, record_msg):
        record_msg.service_type = self._service_id
        record_msg.preferred_sim_ids.extend(self._preferred_service_sim_ids)
        record_msg.fired_sim_ids.extend(self._fired_service_sim_ids)
        record_msg.hired = self.hired
        if self.time_last_started_service is not None:
            record_msg.time_last_started_service = self.time_last_started_service.absolute_ticks()
        record_msg.recurring = self.recurring
        if self.time_last_finished_service is not None:
            record_msg.time_last_finished_service = self.time_last_finished_service.absolute_ticks()
        if self.user_specified_data_id is not None:
            record_msg.user_specified_data_id = self.user_specified_data_id

    def load_npc_record(self, record_msg):
        self._service_id = record_msg.service_type
        self._preferred_service_sim_ids.clear()
        self._fired_service_sim_ids.clear()
        self._preferred_service_sim_ids = set(record_msg.preferred_sim_ids)
        self._fired_service_sim_ids = set(record_msg.fired_sim_ids)
        self.hired = record_msg.hired
        if record_msg.HasField('time_last_started_service'):
            self.time_last_started_service = DateAndTime(record_msg.time_last_started_service)
        self.recurring = record_msg.recurring
        if record_msg.HasField('time_last_finished_service'):
            self.time_last_finished_service = DateAndTime(record_msg.time_last_finished_service)
        if record_msg.HasField('user_specified_data_id'):
            self.user_specified_data_id = record_msg.user_specified_data_id

