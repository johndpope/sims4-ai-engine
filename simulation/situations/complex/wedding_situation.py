from autonomy.autonomy_modes import FullAutonomy
from autonomy.autonomy_request import AutonomyRequest
from date_and_time import create_time_span
from event_testing.test_events import TestEvent
from interactions.aop import AffordanceObjectPair
from interactions.context import InteractionContext
from interactions.interaction_cancel_compatibility import InteractionCancelCompatibility, InteractionCancelReason
from interactions.interaction_finisher import FinishingType
from interactions.priority import Priority
from relationships import relationship_bit
from role.role_state import RoleState
from sims4.resources import Types
from sims4.tuning.tunable import TunableSimMinute, TunableReference
from sims4.tuning.tunable_base import GroupNames
from situations.situation_complex import SituationState
from situations.situation_job import SituationJob
import alarms
import clock
import event_testing
import interactions
import services
import sims4.tuning.tunable
import situations.situation_complex

class WeddingSituation(situations.situation_complex.SituationComplexCommon):
    __qualname__ = 'WeddingSituation'
    INSTANCE_TUNABLES = {'betrothed': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                The SituationJob for the betrothed.\n                '), betrothed_gather_role_state=RoleState.TunableReference(description="\n                betrothed's role state before the ceremony.\n                "), betrothed_ceremony_role_state=RoleState.TunableReference(description="\n                betrothed's role state during the ceremony.\n                "), betrothed_reception_role_state=RoleState.TunableReference(description="\n                betrothed's role state after the ceremony.\n                "), tuning_group=GroupNames.ROLES), 'bartender': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                The SituationJob for the Bartenders.\n                '), bartender_prep_role_state=RoleState.TunableReference(description="\n                Bartender's role state for preparing for guests.\n                "), bartender_serve_role_state=RoleState.TunableReference(description="\n                Bartender's role state for serving guests.\n                "), tuning_group=GroupNames.ROLES), 'caterer': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                The SituationJob for the Caterers.\n                '), caterer_prep_role_state=RoleState.TunableReference(description="\n                Caterer's role state for preparing for guests.\n                "), caterer_serve_role_state=RoleState.TunableReference(description="\n                Caterer's role state for serving guests.\n            "), tuning_group=GroupNames.ROLES), 'entertainer': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                The SituationJob for the entertainer.\n                '), entertainer_prep_role_state=RoleState.TunableReference(description="\n                Entertainer's role state during preparation phase.\n                "), tuning_group=GroupNames.ROLES), 'guest': sims4.tuning.tunable.TunableTuple(situation_job=SituationJob.TunableReference(description='\n                The SituationJob for the Guests.\n                '), guest_gather_role_state=RoleState.TunableReference(description="\n                Guest's role state before the ceremony.\n                "), guest_gather_impatient_role_state=RoleState.TunableReference(description="\n                Guest's role state if it is taking too long for the ceremony to\n                start.\n                "), guest_ceremony_role_state=RoleState.TunableReference(description="\n                Guest's role state during the ceremony.\n                "), watch_wedding_static_commodity=TunableReference(description='\n                The static commodity that will be forced to be solved on the\n                sim when they move into the ceremony state.\n                ', manager=services.get_instance_manager(Types.STATIC_COMMODITY)), guest_reception_pre_cake_role_state=RoleState.TunableReference(description="\n                Guest's role state during the reception, before the cake is\n                cut, if the ceremony was successful.\n                "), guest_reception_post_cake_role_state=RoleState.TunableReference(description="\n                Guest's role state during the reception, after the cake is cut,\n                if the ceremony was successful.\n                "), guest_failed_reception_role_state=RoleState.TunableReference(description="\n                Guest's role state during the reception if the ceremony was a\n                unmitigated disaster.\n                "), tuning_group=GroupNames.ROLES), 'ceremony': situations.situation_complex.TunableInteractionOfInterest(description='\n            Starting this interaction starts the ceremony. Completing it starts\n            the reception.\n            ', tuning_group=GroupNames.TRIGGERS), 'cold_feet': situations.situation_complex.TunableInteractionOfInterest(description='\n            Running this mixer interaction during the ceremony causes it to\n            FAIL.\n            ', tuning_group=GroupNames.TRIGGERS), 'kiss': situations.situation_complex.TunableInteractionOfInterest(description='\n            Running this mixer interaction during the ceremony causes it to\n            SUCCEED.\n            ', tuning_group=GroupNames.TRIGGERS), 'cut_cake': situations.situation_complex.TunableInteractionOfInterest(description='\n            Once this interaction is run guests can eat cake.\n            ', tuning_group=GroupNames.TRIGGERS), 'guests_become_impatient_timeout': TunableSimMinute(description='\n            If the ceremony is not started in this amount of time the guests\n            will grow impatient.\n            ', default=60, tuning_group=GroupNames.TRIGGERS), 'guests_start_reception_timeout': TunableSimMinute(description='\n            If the party is already in the ImpatientGatherState, after this\n            amount of time we switch the party to PostCakeReceptionState\n            so everyone can enjoy.', default=120, tuning_group=GroupNames.TRIGGERS), 'engaged_bit': relationship_bit.RelationshipBit.TunableReference(description='\n            The Rel Bit to look for when auto-populating betrothed Sims.\n            ', tuning_group=GroupNames.ROLES), 'move_in_together_interaction': TunableReference(description='\n            The affordance to push on the betrothed sims when the wedding event ends.\n            ', manager=services.affordance_manager())}
    REMOVE_INSTANCE_TUNABLES = ('_NPC_host_filter', '_NPC_hosted_player_tests', 'NPC_hosted_situation_start_message', 'NPC_hosted_situation_player_job', 'NPC_hosted_situation_use_player_sim_as_filter_requester', 'venue_invitation_message', 'venue_situation_player_job')

    @staticmethod
    def _states():
        return [(1, GatherState), (2, ImpatientGatherState), (3, CeremonyState), (4, PreCakeReceptionState), (5, PostCakeReceptionState), (6, FailedReceptionState)]

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        return [(cls.betrothed.situation_job, cls.betrothed.betrothed_gather_role_state), (cls.bartender.situation_job, cls.bartender.bartender_prep_role_state), (cls.caterer.situation_job, cls.caterer.caterer_prep_role_state), (cls.guest.situation_job, cls.guest.guest_gather_role_state), (cls.entertainer.situation_job, cls.entertainer.entertainer_prep_role_state)]

    @classmethod
    def default_job(cls):
        return cls.guest.situation_job

    @classmethod
    def get_engaged_sim_id(cls, sim):
        for relationship in sim.relationship_tracker:
            while relationship.has_bit(cls.engaged_bit):
                if relationship.sim_id == sim.id:
                    return relationship.target_sim_id
                return relationship.sim_id

    @classmethod
    def get_prepopulated_job_for_sims(cls, sim, target_sim_id=None):
        prepopulate = [(sim.id, cls.betrothed.situation_job.guid64)]
        engaged_sim_id = cls.get_engaged_sim_id(sim)
        if engaged_sim_id is not None:
            prepopulate.append((engaged_sim_id, cls.betrothed.situation_job.guid64))
        return prepopulate

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._betrothed_sims = []
        self.should_push_move_in = False

    def start_situation(self):
        super().start_situation()
        self._change_state(GatherState())

    def _on_set_sim_job(self, sim, job_type):
        super()._on_set_sim_job(sim, job_type)
        if job_type is self.betrothed.situation_job:
            self._betrothed_sims.append(sim)

    def _on_sim_removed_from_situation_prematurely(self, sim):
        super()._on_sim_removed_from_situation_prematurely(sim)
        if not (sim in self._betrothed_sims and isinstance(self._cur_state, FailedReceptionState)):
            self._change_state(FailedReceptionState())

    def is_ceremony_starting(self, event, resolver):
        if event == TestEvent.InteractionStart and resolver(self.ceremony):
            participants = resolver.get_participants(interactions.ParticipantType.Actor)
            while True:
                for sim in self._betrothed_sims:
                    while sim.sim_info in participants:
                        return True
        return False

    def _save_custom_state(self, writer):
        if type(self._cur_state) is not CeremonyState:
            super()._save_custom_state(writer)
            return
        uid = self._state_type_to_uid(GatherState)
        writer.write_uint32(situations.situation_complex.SituationComplexCommon.STATE_ID_KEY, uid)
        writer.write_bool('saved_during_ceremony', True)

    def on_remove(self):
        super().on_remove()
        sim = self._betrothed_sims[0]
        target = self._betrothed_sims[1]
        if self.should_push_move_in and sim is not None and target is not None:
            priority = Priority.High
            context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, priority)
            sim.push_super_affordance(self.move_in_together_interaction, target, context)

class GatherState(SituationState):
    __qualname__ = 'GatherState'

    def on_activate(self, reader=None):
        super().on_activate(reader)
        time_out = self.owner.guests_become_impatient_timeout
        if reader is not None:
            time_out = reader.read_float('impatient_timer', time_out)
        self._impatient_alarm_handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(time_out), lambda _: self.timer_expired())
        self._test_event_register(TestEvent.InteractionStart)
        if reader is not None and reader.read_bool('saved_during_ceremony', False):
            for (job_type, role_state_type) in self.owner._get_tuned_job_and_default_role_state_tuples():
                self.owner._set_job_role_state(job_type, role_state_type)

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
        if self.owner.is_ceremony_starting(event, resolver):
            self._change_state(CeremonyState(resolver.interaction))

class ImpatientGatherState(SituationState):
    __qualname__ = 'ImpatientGatherState'

    def on_activate(self, reader=None):
        super().on_activate(reader)
        time_out = self.owner.guests_start_reception_timeout
        if reader is not None:
            time_out = reader.read_float('start_reception_timer', time_out)
        self._start_reception_alarm_handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(time_out), lambda _: self.timer_expired())
        self._test_event_register(TestEvent.InteractionStart)
        self.owner._set_job_role_state(self.owner.guest.situation_job, self.owner.guest.guest_gather_impatient_role_state)

    def save_state(self, writer):
        super().save_state(writer)
        if self._start_reception_alarm_handle is not None:
            writer.write_float('start_reception_timer', self._start_reception_alarm_handle.get_remaining_time().in_minutes())

    def on_deactivate(self):
        if self._start_reception_alarm_handle is not None:
            alarms.cancel_alarm(self._start_reception_alarm_handle)
            self._start_reception_alarm_handle = None
        super().on_deactivate()

    def timer_expired(self):
        self._change_state(PostCakeReceptionState(True))

    def handle_event(self, sim_info, event, resolver):
        if self.owner.is_ceremony_starting(event, resolver):
            self._change_state(CeremonyState(resolver.interaction))

class CeremonyState(SituationState):
    __qualname__ = 'CeremonyState'
    MAKE_GUESTS_WATCH_ALARM_TIME = 3

    def __init__(self, interaction):
        super().__init__()
        self._interaction = interaction
        self._alarm_handle = None
        self._guest_sim_infos_to_force_watch = []
        if self._interaction is not None:
            self._interaction.register_on_finishing_callback(self._on_finishing_callback)

    def _make_guests_watch(self, _):
        static_commodity_list = [self.owner.guest.watch_wedding_static_commodity]
        object_list = list(self.owner.all_sims_in_job_gen(self.owner.betrothed.situation_job))
        for sim_info in tuple(self._guest_sim_infos_to_force_watch):
            sim = sim_info.get_sim_instance()
            if sim is None:
                self._guest_sim_infos_to_force_watch.remove(sim_info)
            InteractionCancelCompatibility.cancel_interactions_for_reason(sim, InteractionCancelReason.WEDDING, FinishingType.WEDDING, 'Interaction was cancelled due to the wedding situation.')
            autonomy_request = AutonomyRequest(sim, autonomy_mode=FullAutonomy, object_list=object_list, static_commodity_list=static_commodity_list, limited_autonomy_allowed=False, autonomy_mode_label_override='WeddingMakeGuestsWatch')
            selected_interaction = services.autonomy_service().find_best_action(autonomy_request)
            while selected_interaction is not None:
                if AffordanceObjectPair.execute_interaction(selected_interaction):
                    self._guest_sim_infos_to_force_watch.remove(sim_info)
        if self._guest_sim_infos_to_force_watch:
            self._alarm_handle = alarms.add_alarm(self, create_time_span(minutes=self.MAKE_GUESTS_WATCH_ALARM_TIME), self._make_guests_watch)

    def on_activate(self, reader=None):
        super().on_activate(reader)
        self._test_event_register(TestEvent.InteractionComplete)
        guest_tuple = self.owner.guest
        self.owner._set_job_role_state(guest_tuple.situation_job, guest_tuple.guest_ceremony_role_state)
        self.owner._set_job_role_state(self.owner.betrothed.situation_job, self.owner.betrothed.betrothed_ceremony_role_state)
        self._guest_sim_infos_to_force_watch = [sim.sim_info for sim in self.owner.all_sims_in_job_gen(guest_tuple.situation_job)]
        self._alarm_handle = alarms.add_alarm(self, create_time_span(minutes=self.MAKE_GUESTS_WATCH_ALARM_TIME), self._make_guests_watch)

    def on_deactivate(self):
        if self._interaction is not None:
            self._interaction.unregister_on_finishing_callback(self._on_finishing_callback)
            self._interaction = None
        if self._alarm_handle is not None:
            self._alarm_handle.cancel()
        super().on_deactivate()

    def handle_event(self, sim_info, event, resolver):
        if event == event_testing.test_events.TestEvent.InteractionComplete:
            if resolver(self.owner.kiss):
                self._change_state(PreCakeReceptionState())
            elif resolver(self.owner.cold_feet):
                self._change_state(FailedReceptionState())

    def _on_finishing_callback(self, interaction):
        if self._interaction is not interaction:
            return
        if not interaction.uncanceled:
            self._change_state(FailedReceptionState())
            return

class PreCakeReceptionState(SituationState):
    __qualname__ = 'PreCakeReceptionState'

    def on_activate(self, reader=None):
        super().on_activate(reader)
        self._test_event_register(TestEvent.InteractionComplete)
        self.owner._set_job_role_state(self.owner.guest.situation_job, self.owner.guest.guest_reception_pre_cake_role_state)
        self.owner._set_job_role_state(self.owner.betrothed.situation_job, self.owner.betrothed.betrothed_reception_role_state)
        self.owner._set_job_role_state(self.owner.bartender.situation_job, self.owner.bartender.bartender_serve_role_state)
        self.owner._set_job_role_state(self.owner.caterer.situation_job, self.owner.caterer.caterer_serve_role_state)
        self.owner.should_push_move_in = True

    def handle_event(self, sim_info, event, resolver):
        if event == TestEvent.InteractionComplete and resolver(self.owner.cut_cake):
            self._change_state(PostCakeReceptionState())

class PostCakeReceptionState(SituationState):
    __qualname__ = 'PostCakeReceptionState'

    def __init__(self, set_caterer_to_serve=False):
        super().__init__()
        self._set_caterer_to_serve = set_caterer_to_serve

    def on_activate(self, reader=None):
        super().on_activate(reader)
        if self._set_caterer_to_serve:
            self.owner._set_job_role_state(self.owner.caterer.situation_job, self.owner.caterer.caterer_serve_role_state)
        self.owner._set_job_role_state(self.owner.guest.situation_job, self.owner.guest.guest_reception_post_cake_role_state)

class FailedReceptionState(SituationState):
    __qualname__ = 'FailedReceptionState'

    def on_activate(self, reader):
        super().on_activate(reader)
        self._test_event_register(TestEvent.InteractionStart)
        self.owner._set_job_role_state(self.owner.guest.situation_job, self.owner.guest.guest_failed_reception_role_state)
        self.owner._set_job_role_state(self.owner.betrothed.situation_job, self.owner.betrothed.betrothed_reception_role_state)
        self.should_push_move_in = False

    def handle_event(self, sim_info, event, resolver):
        if self.owner.is_ceremony_starting(event, resolver):
            self._change_state(CeremonyState(resolver.interaction))

