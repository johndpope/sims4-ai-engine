#ERROR: jaddr is None
from collections import OrderedDict
import itertools
from objects.object_enums import ResetReason
from services.reset_and_delete_service import ResetRecord
from sims4.repr_utils import standard_repr
from singletons import EMPTY_SET
from uid import UniqueIdGenerator
import element_utils
import elements
import gsi_handlers.master_controller_handlers
import gsi_handlers.sim_timeline_handlers
import reset
import services
import sims4.log
import sims4.service_manager
logger = sims4.log.Logger('MasterController')

class _RunWorkGenElement(elements.SubclassableGeneratorElement):
    __qualname__ = '_RunWorkGenElement'

    def __init__(self, work_entry, work_element, master_controller):
        super().__init__()
        self._work_entry = work_entry
        self._work_element = work_element
        self._master_controller = master_controller
        self.canceled = False

    def __repr__(self):
        return '{} {}'.format(super().__repr__(), self._work_element)

    def _run_gen(self, timeline):
        if self.canceled:
            return
        self._work_entry.running = True
        try:
            logger.debug('STARTING WORK: {}', self._work_entry)
            self._master_controller._gsi_add_sim_time_line_entry(self._work_entry, 'Run', 'Calling work')
            yield element_utils.run_child(timeline, self._work_element)
        finally:
            logger.debug('FINISHED WORK: {}', self._work_entry)
            self._work_entry.remove_from_master_controller()
            self._work_entry.running = False
        self._master_controller._process(*self._work_entry.resources)

class WorkEntry:
    __qualname__ = 'WorkEntry'

    def __init__(self, *, owner, master_controller, work_element=None, cancel_callable=None, resources=EMPTY_SET, additional_resources=EMPTY_SET, on_accept=None, debug_name=None):
        super().__init__()
        self._work_element = work_element
        self._run_work_gen_element = _RunWorkGenElement(self, work_element, master_controller)
        self._work_entry_element = None
        self.cancel_callable = cancel_callable
        self.resources = resources
        self.additional_resources = additional_resources
        self.master_controller = master_controller
        self.owner = owner
        self.on_accept = on_accept
        self._debug_name = debug_name
        self.running = False

    def __repr__(self):
        if self._debug_name is not None:
            main_name = self._debug_name
        elif self._work_entry_element is not None:
            main_name = str(self._work_entry_element)
        else:
            main_name = str(self._work_element)
        return standard_repr(self, main_name, self.cancel_callable, self.resources, self.additional_resources, self.master_controller, self.running)

    @property
    def is_scheduled(self):
        return self._work_entry_element is not None and self._work_entry_element.attached_to_timeline

    def start(self):
        if self.is_scheduled:
            logger.error('Attempting to schedule a single work entry twice.')
            return
        if self._run_work_gen_element is not None:
            if self.on_accept is not None:
                self.on_accept()
            self._work_entry_element = self.owner.schedule_element(self.master_controller.timeline, self._run_work_gen_element)

    @property
    def cancelable(self):
        return self.cancel_callable is not None

    def remove_from_master_controller(self):
        for sim in self.resources:
            active_work = self.master_controller._active_work.get(sim)
            while active_work is not None and active_work is self:
                del self.master_controller._active_work[sim]
        self._work_element = None
        self._work_entry_element = None
        self._run_work_gen_element = None
        self.additional_resources = EMPTY_SET

    def cancel(self):
        if not self.cancelable:
            return
        if self.running:
            self.cancel_callable()
        elif self._run_work_gen_element is not None:
            self._run_work_gen_element.canceled = True
        self.remove_from_master_controller()
        self._work_entry_element = None
        self._run_work_gen_element = None

class WorkRequest:
    __qualname__ = 'WorkRequest'
    __slots__ = ['_work_element', '_required_sims', '_additional_resources', '_on_accept', '_set_work_timestamp', '_debug_name']

    def __init__(self, *, work_element=None, required_sims=EMPTY_SET, additional_resources=EMPTY_SET, on_accept=None, set_work_timestamp=True, debug_name=None):
        self._work_element = work_element
        self._required_sims = required_sims
        self._additional_resources = additional_resources
        self._on_accept = on_accept
        self._set_work_timestamp = set_work_timestamp
        self._debug_name = debug_name

    def __str__(self):
        return standard_repr(self, self._debug_name)

    @property
    def work_element(self):
        return self._work_element

    @property
    def required_sims(self):
        return self._required_sims

    @property
    def additional_resources(self):
        return self._additional_resources

    @property
    def on_accept(self):
        return self._on_accept

    @property
    def set_work_timestamp(self):
        return self._set_work_timestamp

class MasterController(sims4.service_manager.Service):
    __qualname__ = 'MasterController'
    get_next_id = UniqueIdGenerator()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._enabled = True
        self._processing = False
        self._reset_in_progress = False
        self._last_work_timestamps = {}
        self._sims = set()
        self._active_work = {}
        self._denied_sims = OrderedDict()
        self._gsi_entry = None
        self._gsi_log_entries = None

    def stop(self):
        self._remove_all_sims()
        if self._sims:
            logger.error('Sims {} should be empty.  MC logic error.', self._sims, owner='mduke')
            self._sims.clear()
        if self._active_work:
            logger.error('Active Work {} should be empty.  MC logic error.', self._active_work, owner='mduke')
            self._active_work.clear()
        if self._denied_sims:
            logger.error('Denied Sims {} should be empty.  MC logic error.', self._denied_sims, owner='mduke')
            self._denied_sims.clear()

    @property
    def timeline(self):
        return services.time_service().sim_timeline

    def remove_all_sims_and_disable_on_teardown(self):
        self._enabled = False
        self._remove_all_sims()

    def _remove_all_sims(self):
        for sim in tuple(self._sims):
            self.remove_sim(sim)

    def add_sim(self, sim):
        logger.assert_raise(self._enabled == True, 'Attempting to add a sim to the master controller when it is not enabled.', owner='sscholl')
        self._sims.add(sim)
        self.set_timestamp_for_sim_to_now(sim)
        self._process(sim)

    def added_sims(self):
        return list(self._sims)

    def remove_sim(self, sim):
        self._last_work_timestamps.pop(sim, None)
        self._sims.discard(sim)
        if sim in self._denied_sims:
            del self._denied_sims[sim]
            sim.queue.on_head_changed.remove(self._process)

    def reset_timestamp_for_sim(self, sim):
        self._last_work_timestamps[sim] = 0

    def set_timestamp_for_sim_to_now(self, sim):
        self._last_work_timestamps[sim] = self.get_next_id()

    def is_sim_free(self, sim):
        if sim not in self._active_work:
            return True
        work_entry = self._active_work[sim]
        if work_entry is None:
            return True
        return work_entry.cancelable

    def on_reset_sim(self, sim, reset_reason):
        self._active_work.pop(sim, None)

    def on_reset_begin(self):
        self._reset_in_progress = True

    def on_reset_end(self, *sims):
        self._reset_in_progress = False
        self._process(*sims)

    def add_interdependent_reset_records(self, sim, records):
        work_entry = self._active_work.get(sim, None)
        if work_entry is None:
            return records
        for other_sim in work_entry.resources:
            while other_sim is not sim:
                records.append(ResetRecord(other_sim, ResetReason.RESET_EXPECTED, sim, 'Work entry resource:{}'.format(work_entry)))

    def _process_work_entry(self, sim, work_entry, requested_sims, requested_resources):
        all_free = True
        must_run = not work_entry.cancelable
        immediate_cancels = []
        if work_entry.additional_resources:
            for additional_resource in work_entry.additional_resources:
                while additional_resource in requested_resources:
                    all_free = False
                    break
            requested_resources.update(work_entry.additional_resources)
        for required_sim in work_entry.resources:
            self._gsi_add_log_entry(sim, 'PROCESS_WORK_ENTRY', 'Sim Resource: {}: testing if valid resource', required_sim)
            if required_sim not in self._sims:
                logger.error('Attempting to require a resource ({}) that is not managed by the MasterController.', required_sim)
                self._gsi_add_log_entry(sim, 'PROCESS_WORK_ENTRY', 'Denied because requested Sim not managed by the MC: {}.', required_sim)
                all_free = False
            if required_sim in requested_sims:
                all_free = False
                self._gsi_add_log_entry(sim, 'PROCESS_WORK_ENTRY', 'Already Requested')
            if required_sim in self._active_work:
                self._gsi_add_log_entry(sim, 'PROCESS_WORK_ENTRY', 'Sim Resource has Active Work: {} - ', str(self._active_work[required_sim]))
                if not must_run:
                    all_free = False
                    self._gsi_add_log_entry(sim, 'PROCESS_WORK_ENTRY', 'Work Entry is not must run')
                required_work_entry = self._active_work[required_sim]
                if not required_work_entry.cancelable:
                    all_free = False
                    requested_sims.add(required_sim)
                    self._gsi_add_log_entry(sim, 'PROCESS_WORK_ENTRY', 'Sim Resource has work entry and cannot be canceled immediately')
                self._gsi_add_log_entry(sim, 'PROCESS_WORK_ENTRY', 'Sim Resource has work entry that can be canceled added to immedeiate_cancels')
                immediate_cancels.append((required_sim, required_work_entry))
            self._gsi_add_log_entry(sim, 'PROCESS_WORK_ENTRY', 'Sim Resource is free')
        if all_free:
            for (required_sim, required_work_entry) in immediate_cancels:
                self._gsi_add_log_entry(sim, 'PROCESS_WORK_ENTRY', '{} work entry canceled called.', required_sim)
                required_work_entry.cancel()
                while required_sim in self._active_work:
                    del self._active_work[required_sim]
            for required_sim in work_entry.resources:
                self._gsi_add_log_entry(sim, 'PROCESS_WORK_ENTRY', 'work entry added to sim{}.', required_sim)
                self._active_work[required_sim] = work_entry
                requested_sims.add(required_sim)
            return True
        if sim not in self._denied_sims:
            self._gsi_add_log_entry(sim, 'PROCESS_WORK_ENTRY', 'Entry added to denied sims.')
            sim.queue.on_head_changed.append(self._process)
            self._denied_sims[sim] = work_entry
        if must_run:
            requested_sims.update(work_entry.resources)
        self._gsi_add_log_entry(sim, 'PROCESS_WORK_ENTRY', 'work entry NOT added to sim.')
        return False

    def _sorted_sims(self, sims):
        return sorted(sims, key=lambda sim: (-sim.get_next_work_priority(), self._last_work_timestamps[sim]))

    def _process(self, *sims):
        if not self._enabled or self._processing or self._reset_in_progress:
            return
        self._processing = True
        sims_filtered = list(sims)
        try:
            requested_sims = set()
            requested_resources = set()
            for work_entry in self._active_work.values():
                while work_entry.additional_resources:
                    requested_resources.update(work_entry.additional_resources)
            new_work_accepted = []
            self._gsi_entry_initialize(*sims)
            self._gsi_add_sim_time_line_for_sims(sims, 'Start', 'Begin processing')
            sims_filtered = [sim for sim in sims if sim in self._sims]
            for sim in self._sorted_sims(itertools.chain(self._denied_sims, sims_filtered)):
                self._gsi_add_log_entry(sim, 'PROCESS', '----- START -----')
                if sim not in self._sims:
                    pass
                if sim in requested_sims:
                    pass
                existing_entry = self._active_work.get(sim)
                if existing_entry is not None and not existing_entry.cancelable:
                    pass
                if sim in self._denied_sims:
                    sim.queue.on_head_changed.remove(self._process)
                try:
                    work_request = sim.get_next_work()
                finally:
                    if sim in self._denied_sims:
                        sim.queue.on_head_changed.append(self._process)
                if work_request.work_element is None:
                    self._gsi_add_log_entry(sim, 'PROCESS', 'No Work Element')
                work_entry = WorkEntry(work_element=work_request.work_element, resources=work_request.required_sims, additional_resources=work_request.additional_resources, owner=sim, master_controller=self, on_accept=work_request.on_accept, debug_name=work_request._debug_name)
                self._gsi_add_sim_time_line_for_sim(sim, 'Create', 'Work Entry Created')
                self._gsi_add_log_entry(sim, 'PROCESS', 'Work Entry Created: required_sims:{}', str(work_request.required_sims))
                while self._process_work_entry(sim, work_entry, requested_sims, requested_resources):
                    if sim in self._denied_sims:
                        sim.queue.on_head_changed.remove(self._process)
                        del self._denied_sims[sim]
                    new_work_accepted.append((sim, work_entry))
                    if work_request.set_work_timestamp:
                        self.set_timestamp_for_sim_to_now(sim)
            for (sim, work_entry) in new_work_accepted:
                self._gsi_add_log_entry(sim, 'PROCESS', 'Work Entry Start Called: {}', work_entry)
                self._gsi_add_sim_time_line_for_sim(sim, 'Start', 'Work Entry Started')
                work_entry.start()
            for sim in self._sims:
                while sim not in self._active_work:
                    (work_element_idle, cancel_callable) = sim.get_idle_element()
                    if work_element_idle is not None:
                        work_entry = WorkEntry(work_element=work_element_idle, cancel_callable=cancel_callable, resources=(sim,), owner=sim, master_controller=self)
                        self._active_work[sim] = work_entry
                        self._gsi_add_log_entry(sim, 'PROCESS', 'No active work - run idle behavior')
                        if sim not in self._denied_sims:
                            sim.queue.on_head_changed.append(self._process)
                        self._denied_sims[sim] = work_entry
                        work_entry.start()
            self._gsi_entry_finalize()
            self._processing = False
        finally:
            if self._processing:
                self._processing = False
                services.get_reset_and_delete_service().trigger_batch_reset(sims_filtered, ResetReason.RESET_ON_ERROR, None, 'Exception in _process in the MasterController.')

    def _gsi_create_active_work_entry(self):
        gsi_active_work = []
        for (sim, work_entry) in self._active_work.items():
            entry = {'sim': sim.full_name, 'work_entry': str(work_entry)}
            gsi_active_work.append(entry)
        return gsi_active_work

    def _gsi_entry_initialize(self, *sims_being_processed):
        if gsi_handlers.master_controller_handlers.archiver.enabled:
            self._gsi_entry = {'sims_with_active_work': str([sim.full_name for sim in self._active_work.keys()]), 'last_time_stamp': str(self._last_work_timestamps)}
            self._gsi_entry['active_work_start'] = self._gsi_create_active_work_entry()
            self._gsi_log_entries = []

    def _gsi_add_log_entry(self, sim, tag, log_message, *log_message_args):
        if gsi_handlers.master_controller_handlers.archiver.enabled:
            entry = {'sim': sim.full_name if sim is not None else '', 'tag': tag, 'log': log_message.format(*log_message_args)}
            self._gsi_log_entries.append(entry)

    def _gsi_add_sim_time_line_for_sim(self, sim, status, log_message):
        if gsi_handlers.sim_timeline_handlers.archiver.enabled:
            gsi_handlers.sim_timeline_handlers.archive_sim_timeline(sim, 'MasterController', status, log_message)

    def _gsi_add_sim_time_line_for_sims(self, sims, status, log_message):
        if gsi_handlers.sim_timeline_handlers.archiver.enabled:
            for sim in sims:
                gsi_handlers.sim_timeline_handlers.archive_sim_timeline(sim, 'MasterController', status, log_message)

    def _gsi_add_sim_time_line_entry(self, work_entry, status, log_message):
        if gsi_handlers.sim_timeline_handlers.archiver.enabled:
            for resource in work_entry.resources:
                if not resource.is_sim:
                    pass
                if resource is work_entry.owner:
                    message_to_log = '{}: as owner: {}'.format(log_message, resource)
                else:
                    message_to_log = '{} as resource: {}'.format(log_message, resource, log_message)
                gsi_handlers.sim_timeline_handlers.archive_sim_timeline(resource, 'MasterController', status, message_to_log)

    def _gsi_entry_finalize(self):
        if gsi_handlers.master_controller_handlers.archiver.enabled:
            self._gsi_entry['sims_with_active_work_after'] = str([sim.full_name for sim in self._active_work.keys()])
            self._gsi_entry['last_time_stamp_end'] = str(self._last_work_timestamps)
            self._gsi_entry['active_work_end'] = self._gsi_create_active_work_entry()
            self._gsi_entry['Log'] = self._gsi_log_entries
            gsi_handlers.master_controller_handlers.archive_master_controller_entry(self._gsi_entry)
            self._gsi_entry = None
            self._gsi_log_entries = None

