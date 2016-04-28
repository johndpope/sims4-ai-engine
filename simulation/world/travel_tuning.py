from protocolbuffers import DistributorOps_pb2, InteractionOps_pb2, Consts_pb2
from audio.primitive import TunablePlayAudio
from clock import ClockSpeedMode
from distributor.ops import GenericProtocolBufferOp
from event_testing.results import TestResult
from filters.tunable import TunableSimFilter
from interactions.liability import Liability
from objects import ALL_HIDDEN_REASONS
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.tunable import TunableReference, TunableSimMinute
import distributor
import services

class TravelTuning:
    __qualname__ = 'TravelTuning'
    ENTER_LOT_AFFORDANCE = TunableReference(services.affordance_manager(), description='SI to push when sim enters the lot.')
    EXIT_LOT_AFFORDANCE = TunableReference(services.affordance_manager(), description='SI to push when sim is exiting the lot.')
    NPC_WAIT_TIME = TunableSimMinute(15, description='Delay in sim minutes before pushing the ENTER_LOT_AFFORDANCE on a NPC at the spawn point if they have not moved.')
    TRAVEL_AVAILABILITY_SIM_FILTER = TunableSimFilter.TunableReference(description='Sim Filter to show what Sims the player can travel with to send to Game Entry.')
    TRAVEL_SUCCESS_AUDIO_STING = TunablePlayAudio(description='\n        The sound to play when we finish loading in after the player has traveled.\n        ')
    NEW_GAME_AUDIO_STING = TunablePlayAudio(description='\n        The sound to play when we finish loading in from a new game, resume, or\n        household move in.\n        ')

class TravelMixin:
    __qualname__ = 'TravelMixin'
    PENDING_TRAVEL_TOOLTIP = TunableLocalizedStringFactory(description='Greyed out tooltip shown when trying to travel with a pending travel reservation.')

    def __init__(self, *args, to_zone_id=0, **kwargs):
        super().__init__(to_zone_id=to_zone_id, *args, **kwargs)
        self.to_zone_id = to_zone_id

    @classmethod
    def travel_test(cls, context):
        zone = services.current_zone()
        if zone.travel_service.has_pending_travel(context.sim.account):
            return TestResult(False, 'Cannot Travel... with a pending travel already queued!', tooltip=cls.PENDING_TRAVEL_TOOLTIP)
        return TestResult.TRUE

    def show_travel_dialog(self):
        if self.sim.client is None:
            return
        travel_info = InteractionOps_pb2.TravelMenuCreate()
        travel_info.sim_id = self.sim.sim_id
        travel_info.selected_lot_id = self.to_zone_id
        travel_info.selected_world_id = self._kwargs.get('world_id', 0)
        travel_info.selected_lot_name = self._kwargs.get('lot_name', '')
        travel_info.friend_account = self._kwargs.get('friend_account', '')
        system_distributor = distributor.system.Distributor.instance()
        system_distributor.add_op_with_no_owner(GenericProtocolBufferOp(DistributorOps_pb2.Operation.TRAVEL_MENU_SHOW, travel_info))

TRAVEL_SIM_LIABILITY = 'TravelSimLiability'

class TravelSimLiability(Liability):
    __qualname__ = 'TravelSimLiability'

    def __init__(self, interaction, sim_info, to_zone_id, expecting_dialog_response=False, is_attend_career=False):
        self.interaction = interaction
        self.expecting_dialog_response = expecting_dialog_response
        self.sim_info = sim_info
        self.to_zone_id = to_zone_id
        self.is_attend_career = is_attend_career

    def should_transfer(self):
        return False

    def release(self):
        if self.interaction is not None:
            sim = self.sim_info.get_sim_instance()
            if self.interaction.allow_outcomes and not self.expecting_dialog_response:
                self._travel_sim()
            elif sim is not None and self.expecting_dialog_response:
                sim.fade_in()

    def _attend_career(self):
        career = self.sim_info.career_tracker.career_currently_within_hours
        if career is not None:
            career.attend_work()

    def _travel_sim(self):
        sim = self.sim_info.get_sim_instance()
        self.sim_info.inject_into_inactive_zone(self.to_zone_id)
        if sim is not None:
            client = services.client_manager().get_first_client()
            next_sim_info = client.selectable_sims.get_next_selectable(self.sim_info)
            next_sim = next_sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            if next_sim is not sim:
                if self.is_attend_career:
                    self._attend_career()
                if sim.is_selected:
                    client.set_next_sim_or_none()
                self.sim_info.save_sim()
                sim.schedule_destroy_asap(post_delete_func=client.send_selectable_sims_update, source=self, cause='Destroying sim in travel liability')
            else:
                sim.fade_in()

    def travel_player(self):
        sim = self.sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        travel_info = InteractionOps_pb2.TravelSimsToZone()
        travel_info.zone_id = self.to_zone_id
        travel_info.sim_ids.append(sim.id)
        self.interaction = None
        distributor.system.Distributor.instance().add_event(Consts_pb2.MSG_TRAVEL_SIMS_TO_ZONE, travel_info)
        if self.is_attend_career:
            self._attend_career()
        sim.queue.cancel_all()
        services.game_clock_service().set_clock_speed(ClockSpeedMode.PAUSED)

    def travel_dialog_response(self, dialog):
        if dialog.accepted:
            self.travel_player()
        else:
            sim = self.sim_info.get_sim_instance()
            if sim is not None:
                sim.fade_in()

