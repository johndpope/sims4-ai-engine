from event_testing.test_events import TestEvent
from interactions import ParticipantType
from role.role_state import RoleState
from sims4.tuning.tunable import TunableSimMinute
from sims4.tuning.tunable_base import GroupNames
from situations.situation_complex import SituationComplexCommon, TunableInteractionOfInterest, SituationState
from situations.situation_job import SituationJob
import alarms
import clock
import sims4.tuning.tunable

class BirthdayPartySituation(SituationComplexCommon):
    __qualname__ = 'BirthdayPartySituation'
    INSTANCE_TUNABLES = {'celebrant': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                        The SituationJob for the celebrant.'), celebrant_gather_role_state=RoleState.TunableReference(description="\n                        Celebrant's role state before the celebration (gather phase)."), celebrant_reception_role_state=RoleState.TunableReference(description="\n                        Celebrant's role state after the celebration (eat, drink, socialize, dance)."), tuning_group=GroupNames.ROLES), 'bartender': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                        The SituationJob for the Bartender.'), bartender_pre_reception_role_state=RoleState.TunableReference(description="\n                        Bartender's role state to prepare drinks and socialize with guests."), bartender_reception_role_state=RoleState.TunableReference(description="\n                        Bartender's role state to prepare drinks, socialize, etc. during the reception."), tuning_group=GroupNames.ROLES), 'caterer': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                        The SituationJob for the caterer.'), caterer_prep_role_state=RoleState.TunableReference(description="\n                        Caterer's role state for preparing cake and meal for guests."), caterer_serve_role_state=RoleState.TunableReference(description="\n                        Caterer's role state for serving the guests."), tuning_group=GroupNames.ROLES), 'entertainer': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                        The SituationJob for the entertainer.'), entertainer_prep_reception_state=RoleState.TunableReference(description="\n                        Entertainer's role state before reception."), entertainer_reception_role_state=RoleState.TunableReference(description="\n                        Entertainer's role state during reception."), tuning_group=GroupNames.ROLES), 'guest': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                        The SituationJob for the Guests.'), guest_gather_role_state=RoleState.TunableReference(description="\n                        Guest's role state before the celebration (gather phase)."), guest_gather_impatient_role_state=RoleState.TunableReference(description="\n                        Guest's role state if it is taking too long for the celebration to start."), guest_reception_role_state=RoleState.TunableReference(description="\n                        Guest's role state after the celebration (now they can eat the cake)."), tuning_group=GroupNames.ROLES), 'start_reception': TunableInteractionOfInterest(description='\n                        This is a birthday cake interaction where starting this interaction starts \n                        the cake reception phase.', tuning_group=GroupNames.TRIGGERS), 'guests_become_impatient_timeout': TunableSimMinute(description='\n                        If the celebration is not started in this amount of time the guests will grow impatient.', default=120, tuning_group=GroupNames.TRIGGERS)}
    REMOVE_INSTANCE_TUNABLES = ('_NPC_host_filter', '_NPC_hosted_player_tests', 'NPC_hosted_situation_start_message', 'NPC_hosted_situation_player_job', 'NPC_hosted_situation_use_player_sim_as_filter_requester', 'venue_invitation_message', 'venue_situation_player_job')

    @staticmethod
    def _states():
        return [(1, GatherState), (2, ImpatientGatherState), (3, ReceptionState)]

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.celebrant.situation_job, cls.celebrant.celebrant_gather_role_state), (cls.bartender.situation_job, cls.bartender.bartender_pre_reception_role_state), (cls.caterer.situation_job, cls.caterer.caterer_prep_role_state), (cls.entertainer.situation_job, cls.entertainer.entertainer_prep_reception_state), (cls.guest.situation_job, cls.guest.guest_gather_role_state)]

    @classmethod
    def default_job(cls):
        return cls.guest.situation_job

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._celebrant_id = None

    def start_situation(self):
        super().start_situation()
        self._change_state(GatherState())

    def _on_set_sim_job(self, sim, job_type):
        super()._on_set_sim_job(sim, job_type)
        if job_type is self.celebrant.situation_job:
            self._celebrant_id = sim.sim_id

    def _is_birthday_starting(self, event, resolver):
        if event == TestEvent.InteractionStart and resolver(self.start_reception):
            participants = resolver.get_participants(ParticipantType.Actor)
            while True:
                for sim_info in participants:
                    while sim_info.id == self._celebrant_id:
                        return True
        return False

class GatherState(SituationState):
    __qualname__ = 'GatherState'

    def on_activate(self, reader=None):
        super().on_activate(reader)
        time_out = self.owner.guests_become_impatient_timeout
        if reader is not None:
            time_out = reader.read_float('impatient_timer', time_out)
        self._impatient_alarm_handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(time_out), lambda _: self.timer_expired())
        self._test_event_register(TestEvent.InteractionStart)

    def save_state(self, writer):
        super().save_state(writer)
        if self._impatient_alarm_handle is not None:
            writer.write_float('impatient_timer', self._impatient_alarm_handle.get_remaining_time().in_minutes())

    def on_deactivate(self):
        if self._impatient_alarm_handle is not None:
            alarms.cancel_alarm(self._impatient_alarm_handle)
            self._impatient_alarm_handle = None
        super().on_deactivate()

    def timer_expired(self):
        self._change_state(ImpatientGatherState())

    def handle_event(self, sim_info, event, resolver):
        if self.owner._is_birthday_starting(event, resolver):
            self._change_state(ReceptionState())

class ImpatientGatherState(SituationState):
    __qualname__ = 'ImpatientGatherState'

    def on_activate(self, reader=None):
        super().on_activate(reader)
        self._test_event_register(TestEvent.InteractionStart)
        self.owner._set_job_role_state(self.owner.guest.situation_job, self.owner.guest.guest_gather_impatient_role_state)

    def handle_event(self, sim_info, event, resolver):
        if self.owner._is_birthday_starting(event, resolver):
            self._change_state(ReceptionState())

class ReceptionState(SituationState):
    __qualname__ = 'ReceptionState'

    def on_activate(self, reader=None):
        super().on_activate(reader)
        self.owner._set_job_role_state(self.owner.celebrant.situation_job, self.owner.celebrant.celebrant_reception_role_state)
        self.owner._set_job_role_state(self.owner.bartender.situation_job, self.owner.bartender.bartender_reception_role_state)
        self.owner._set_job_role_state(self.owner.caterer.situation_job, self.owner.caterer.caterer_serve_role_state)
        self.owner._set_job_role_state(self.owner.entertainer.situation_job, self.owner.entertainer.entertainer_reception_role_state)
        self.owner._set_job_role_state(self.owner.guest.situation_job, self.owner.guest.guest_reception_role_state)

