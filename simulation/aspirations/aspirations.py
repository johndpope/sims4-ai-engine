import weakref
from protocolbuffers import Sims_pb2
from protocolbuffers.DistributorOps_pb2 import Operation, SetWhimBucks
from aspirations.aspiration_types import AspriationType
from distributor.ops import GenericProtocolBufferOp
from distributor.system import Distributor
from event_testing.resolver import SingleSimResolver, DataResolver
from event_testing.test_events import TestEvent
from sims4.localization import LocalizationHelperTuning
import distributor
import event_testing.event_data_tracker as data_tracker
import event_testing.test_events as test_events
import gsi_handlers.aspiration_handlers
import services
import sims4.log
import telemetry_helper
logger = sims4.log.Logger('Aspirations')
TELEMETRY_GROUP_ASPIRATIONS = 'ASPR'
TELEMETRY_HOOK_ADD_ASPIRATIONS = 'AADD'
TELEMETRY_HOOK_COMPLETE_MILESTONE = 'MILE'
TELEMETRY_OBJECTIVE_ID = 'obid'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_ASPIRATIONS)

class AspirationTracker(data_tracker.EventDataTracker):
    __qualname__ = 'AspirationTracker'

    def __init__(self, sim_info):
        super().__init__()
        self._owner_ref = weakref.ref(sim_info)
        self._selected_aspiration = 0
        self._whimsets_to_reset = set()
        self._active_aspiration = None

    @property
    def active_track(self):
        return services.get_instance_manager(sims4.resources.Types.ASPIRATION_TRACK).get(self.owner_sim_info.primary_aspiration)

    def _activate_aspiration(self, aspiration):
        if self._active_aspiration is aspiration:
            return
        self._active_aspiration = aspiration
        aspiration.register_callbacks()
        self.clear_objective_updates_cache(aspiration)
        self.process_test_events_for_aspiration(aspiration)
        self._send_objectives_update_to_client()
        self._send_tracker_to_client()

    def initialize_aspiration(self):
        if self.owner_sim_info is not None and not self.owner_sim_info.is_baby:
            track = self.active_track
            if track is not None:
                for (_, track_aspriation) in track.get_aspirations():
                    while not self.owner_sim_info.aspiration_tracker.milestone_completed(track_aspriation.guid64):
                        self._activate_aspiration(track_aspriation)
                        break
                services.get_event_manager().process_event(test_events.TestEvent.AspirationTrackSelected, sim_info=self.owner_sim_info)

    def process_test_events_for_aspiration(self, aspiration):
        event_manager = services.get_event_manager()
        event_manager.register_single_event(aspiration, TestEvent.UpdateObjectiveData)
        event_manager.process_test_events_for_objective_updates(self.owner_sim_info, init=False)
        event_manager.unregister_single_event(aspiration, TestEvent.UpdateObjectiveData)

    @property
    def owner_sim_info(self):
        return self._owner_ref()

    def aspiration_in_sequence(self, aspiration):
        return aspiration is self._active_aspiration

    def _should_handle_event(self, milestone, event, resolver):
        if not super()._should_handle_event(milestone, event, resolver):
            return False
        if resolver.on_zone_load:
            return True
        aspiration = milestone
        if aspiration.aspiration_type() == AspriationType.FULL_ASPIRATION and aspiration.complete_only_in_sequence:
            return self.aspiration_in_sequence(aspiration)
        return True

    def gsi_event(self, event):
        return {'sim': self._owner_ref().full_name if self._owner_ref() is not None else 'None', 'event': str(event)}

    def post_to_gsi(self, message):
        gsi_handlers.aspiration_handlers.archive_aspiration_event_set(message)

    def _send_tracker_to_client(self, init=False):
        owner = self.owner_sim_info
        if owner is None or owner.is_npc or owner.manager is None:
            return
        msg_empty = True
        msg = Sims_pb2.AspirationTrackerUpdate()
        for guid in self._completed_milestones:
            while not self.milestone_sent(guid):
                self._sent_milestones.add(guid)
                msg.aspirations_completed.append(guid)
                if msg_empty:
                    msg_empty = False
        for guid in self._completed_objectives:
            while not self.objective_sent(guid):
                self._sent_objectives.add(guid)
                msg.objectives_completed.append(guid)
                if msg_empty:
                    msg_empty = False
        if not msg_empty:
            msg.sim_id = owner.id
            msg.init_message = init
            distributor = Distributor.instance()
            distributor.add_op(owner, GenericProtocolBufferOp(Operation.SIM_ASPIRATION_TRACKER_UPDATE, msg))

    def _send_objectives_update_to_client(self):
        owner = self.owner_sim_info
        if owner is None or owner.is_npc or owner.manager is None:
            return
        msg = Sims_pb2.GoalsStatusUpdate()
        if self._update_objectives_msg_for_client(msg):
            msg.sim_id = owner.id
            distributor = Distributor.instance()
            distributor.add_op(owner, GenericProtocolBufferOp(Operation.SIM_GOALS_STATUS_UPDATE, msg))

    def required_completion_count(self, milestone):
        return milestone.objective_completion_count()

    def complete_milestone(self, aspiration, sim_info):
        aspiration_type = aspiration.aspiration_type()
        if aspiration_type == AspriationType.FULL_ASPIRATION:
            sim_info = self._owner_ref()
            if not (aspiration.is_child_aspiration and sim_info.is_child):
                return
            super().complete_milestone(aspiration, sim_info)
            if aspiration.reward is not None:
                aspiration.reward.give_reward(sim_info)
            track = self.active_track
            if track is None:
                logger.error('Active track is None when completing full aspiration.')
                return
            if aspiration in track.aspirations.values():
                if aspiration.screen_slam is not None:
                    aspiration.screen_slam.send_screen_slam_message(sim_info, sim_info, aspiration.display_name, track.display_text)
                if all(self.milestone_completed(track_aspiration.guid64) for track_aspiration in track.aspirations.values()):
                    if track.reward is not None:
                        reward_payout = track.reward.give_reward(sim_info)
                    else:
                        reward_payout = ()
                    reward_text = LocalizationHelperTuning.get_bulleted_list(None, *(reward.get_display_text() for reward in reward_payout))
                    dialog = track.notification(sim_info, SingleSimResolver(sim_info))
                    dialog.show_dialog(icon_override=(track.icon, None), secondary_icon_override=(None, sim_info), additional_tokens=(reward_text,), event_id=aspiration.guid64)
                next_aspiration = track.get_next_aspriation(aspiration)
                if next_aspiration is not None:
                    self._activate_aspiration(next_aspiration)
                    for objective in next_aspiration.objectives:
                        while objective.set_starting_point(self.data_object):
                            self.update_objective(objective.guid64, 0, objective.goal_value(), objective.is_goal_value_money)
                else:
                    self._active_aspiration = None
                with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_COMPLETE_MILESTONE, sim=sim_info.get_sim_instance()) as hook:
                    hook.write_enum('type', aspiration.aspiration_type())
                    hook.write_guid('guid', aspiration.guid64)
            services.get_event_manager().process_event(test_events.TestEvent.UnlockEvent, sim_info=sim_info, unlocked=aspiration)
        elif aspiration_type == AspriationType.FAMILIAL:
            super().complete_milestone(aspiration, sim_info)
            for relationship in aspiration.target_family_relationships:
                family_member_sim_id = sim_info.get_relation(relationship)
                family_member_sim_info = services.sim_info_manager().get(family_member_sim_id)
                while family_member_sim_info is not None:
                    services.get_event_manager().process_event(test_events.TestEvent.FamilyTrigger, sim_info=family_member_sim_info, trigger=aspiration)
        elif aspiration_type == AspriationType.WHIM_SET:
            self._whimsets_to_reset.add(aspiration.guid64)
            super().complete_milestone(aspiration, sim_info)
            self._owner_ref().whim_tracker.activate_set(aspiration)
        elif aspiration_type == AspriationType.NOTIFICATION:
            dialog = aspiration.notification(sim_info, SingleSimResolver(sim_info))
            dialog.show_dialog(event_id=aspiration.guid64)
            super().complete_milestone(aspiration, sim_info)
        else:
            super().complete_milestone(aspiration, sim_info)

    def complete_objective(self, objective_instance):
        super().complete_objective(objective_instance)
        if self._owner_ref() is not None and objective_instance.satisfaction_points > 0:
            self._owner_ref().add_whim_bucks(objective_instance.satisfaction_points, SetWhimBucks.ASPIRATION)

    def reset_milestone(self, milestone_guid):
        completed_milestone = services.get_instance_manager(sims4.resources.Types.ASPIRATION).get(milestone_guid)
        for objective in completed_milestone.objectives:
            while objective.resettable:
                objective.reset_objective(self.data_object)
                self.reset_objective(objective.guid64)
                self.update_objective(objective.guid64, 0, objective.goal_value(), objective.is_goal_value_money)
                self._send_objectives_update_to_client()
        super().reset_milestone(milestone_guid)

    def _update_timer_alarm(self, _):
        sim_info = self.owner_sim_info
        if sim_info is None:
            logger.error('No Sim info in AspirationTracker._update_timer_alarm')
            return
        self.update_timers()
        if sim_info.is_selected:
            services.get_event_manager().process_event(test_events.TestEvent.TestTotalTime, sim_info=sim_info)

    def save(self, blob=None):
        for whim_set_guid64 in self._whimsets_to_reset:
            self.reset_milestone(whim_set_guid64)
        super().save(blob)

    def force_send_data_update(self):
        for aspiration in services.get_instance_manager(sims4.resources.Types.ASPIRATION).types.values():
            if aspiration.disabled:
                pass
            if aspiration.aspiration_type() != AspriationType.FULL_ASPIRATION:
                pass
            for objective in aspiration.objectives:
                self.update_objective(objective.guid64, 0, objective.goal_value(), objective.is_goal_value_money, from_init=True)
                self._tracker_dirty = True
        self.send_if_dirty()

