import random
from clock import interval_in_sim_minutes
from event_testing.resolver import DoubleSimResolver
from scheduler import WeeklySchedule, ScheduleEntry
from sims4.tuning.tunable import TunableTuple, Tunable, TunableList, TunableReference, TunableSimMinute, TunableRange, TunableFactory, TunableSingletonFactory
from situations.situation_guest_list import SituationGuestList, SituationGuestInfo, SituationInvitationPurpose
import services
import sims4.random
import sims4.resources
import telemetry_helper
logger = sims4.log.Logger('NPCHostedSituations')
TELEMETRY_GROUP_SITUATIONS = 'SITU'
TELEMETRY_HOOK_SITUATION_INVITED = 'INVI'
TELEMETRY_HOOK_SITUATION_ACCEPTED = 'ACCE'
TELEMETRY_HOOK_SITUATION_REJECTED = 'REJE'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_SITUATIONS)

class NPCHostedSituationEntry(ScheduleEntry):
    __qualname__ = 'NPCHostedSituationEntry'
    FACTORY_TUNABLES = {'possible_situations': TunableList(TunableTuple(situation=TunableReference(description='\n                        The situation that will attempted to be run by the NPC.\n                        ', manager=services.get_instance_manager(sims4.resources.Types.SITUATION)), weight=Tunable(description='\n                        The weight that this situation will be chosen.\n                        ', tunable_type=float, default=1.0)))}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._possible_situations = []
        for possible_situation in self.possible_situations:
            if possible_situation.situation.NPC_hosted_situation_player_job is None:
                logger.error('Situation: {} tuned in schedule entry without NPC_hosted_situation_player_job tuned.', possible_situation.situation)
            if possible_situation.situation.NPC_hosted_situation_player_job not in possible_situation.situation.get_tuned_jobs():
                logger.error('NPC_hosted_situation_player_job: {} tuned in Situation: {} that is not a possible job for that situation.', possible_situation.situation.NPC_hosted_situation_player_job, possible_situation.situation)
            self._possible_situations.append((possible_situation.weight, possible_situation.situation))
        self.duration = 0

    def select_situation(self):
        return sims4.random.weighted_random_item(self._possible_situations)

TunableNPCHostedSituationEntry = TunableSingletonFactory.create_auto_factory(NPCHostedSituationEntry)

class NPCHostedSituationSchedule(WeeklySchedule):
    __qualname__ = 'NPCHostedSituationSchedule'
    FACTORY_TUNABLES = {'schedule_entries': TunableList(description='\n                A list of event schedules. Each event is a mapping of days of\n                the week to a start_time and duration.\n                ', tunable=TunableNPCHostedSituationEntry()), 'cooldown': TunableSimMinute(description='\n                The cooldown of the scheduler.  If a situation is started\n                through it then another situation will not start for that\n                amount of time.\n                ', default=10, minimum=1), 'creation_chance': TunableRange(description='\n                Chance that a situation will start at each entry point.\n                ', tunable_type=float, default=0.5, minimum=0.0, maximum=1.0)}

    def __init__(self, schedule_entries, cooldown, creation_chance):
        super().__init__(schedule_entries, start_callback=self._try_and_create_NPC_hosted_situation, schedule_immediate=False, min_alarm_time_span=interval_in_sim_minutes(30))
        self._cooldown = interval_in_sim_minutes(cooldown)
        self._creation_chance = creation_chance

    def _try_and_create_NPC_hosted_situation(self, scheduler, alarm_data, callback_data):
        if random.random() > self._creation_chance:
            return
        if services.get_zone_situation_manager().is_user_facing_situation_running():
            return
        chosen_situation = alarm_data.entry.select_situation()
        if chosen_situation is None:
            return
        if not chosen_situation.has_venue_location():
            logger.error("Trying to create an NPC hosted situation, situation: {}, but we couldn't find the appropriate venue. There should ALWAYS be a Maxis Lot tuned for every venue type. - trevorlindsey", chosen_situation)
            return
        chosen_sims = chosen_situation.get_npc_hosted_sims()
        if chosen_sims is None:
            return
        player_sim = chosen_sims[0]
        NPC_sim_id = chosen_sims[1]

        def _create_NPC_hosted_situation(dialog):
            if not dialog.accepted:
                with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_SITUATION_REJECTED, sim=player_sim) as hook:
                    hook.write_guid('type', chosen_situation.guid64)
                return
            guest_list = SituationGuestList(host_sim_id=NPC_sim_id)
            if chosen_situation.NPC_hosted_situation_use_player_sim_as_filter_requester:
                guest_list.filter_requesting_sim_id = player_sim.id
            guest_list.add_guest_info(SituationGuestInfo.construct_from_purpose(player_sim.id, chosen_situation.NPC_hosted_situation_player_job, SituationInvitationPurpose.INVITED))
            chosen_zone_id = chosen_situation.get_venue_location()
            services.get_zone_situation_manager().create_situation(chosen_situation, guest_list=guest_list, zone_id=chosen_zone_id)
            self.add_cooldown(self._cooldown)
            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_SITUATION_ACCEPTED, sim=player_sim) as hook:
                hook.write_guid('type', chosen_situation.guid64)

        with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_SITUATION_INVITED, sim=player_sim) as hook:
            hook.write_guid('type', chosen_situation.guid64)
        target_sim = services.sim_info_manager().get(NPC_sim_id)
        dialog = chosen_situation.NPC_hosted_situation_start_message(player_sim, DoubleSimResolver(player_sim, target_sim))
        dialog.show_dialog(on_response=_create_NPC_hosted_situation)

TunableNPCHostedSituationSchedule = TunableFactory.create_auto_factory(NPCHostedSituationSchedule)
