from protocolbuffers import Consts_pb2, Situations_pb2
from distributor import shared_messages
from interactions import ParticipantType
from interactions.utils.interaction_elements import XevtTriggeredElement
from sims4.localization import TunableLocalizedString
from sims4.tuning.tunable import TunableVariant, TunableList, TunableReference, TunableSingletonFactory, TunableFactory, Tunable, TunableMapping, OptionalTunable, TunableThreshold, TunableTuple, TunableSimMinute, TunableEnumEntry, TunableRange
from sims4.tuning.tunable_base import ExportModes
from situations.situation_guest_list import SituationGuestList, SituationGuestInfo, SituationInvitationPurpose
from situations.situation_phase import SituationPhase
from snippets import TunableAffordanceFilterSnippet, TunableObjectListSnippet
from statistics.statistic_conditions import TunableTimeRangeCondition, TunableEventBasedCondition
import event_testing.test_variants
import services
import sims4.log
import sims4.resources
import venues.venue_constants
logger = sims4.log.Logger('Situations')

class TunableSituationCreationUI(TunableFactory):
    __qualname__ = 'TunableSituationCreationUI'

    @staticmethod
    def _factory(interaction, targeted_situation_participant, situations_available, **kwargs):

        def craft_situation(interaction, targeted_situation_participant, situations_available):
            msg = Situations_pb2.SituationPrepare()
            msg.situation_session_id = services.get_zone_situation_manager().get_new_situation_creation_session()
            msg.sim_id = interaction.sim.id
            if targeted_situation_participant is not None:
                target = interaction.get_participant(targeted_situation_participant)
                if target is not None:
                    msg.is_targeted = True
                    msg.target_id = target.id
                else:
                    logger.error('None participant for: {} on interaction: {}'.format(targeted_situation_participant, interaction), owner='rmccord')
            if situations_available is not None:
                for situation in situations_available:
                    msg.situation_resource_id.append(situation.guid64)
            shared_messages.add_message_if_selectable(interaction.sim, Consts_pb2.MSG_SITUATION_PREPARE, msg, True)
            return True

        return lambda : craft_situation(interaction, targeted_situation_participant, situations_available)

    FACTORY_TYPE = _factory

    def __init__(self, **kwargs):
        super().__init__(description='\n            Triggers the Situation Creation UI.\n            ', targeted_situation_participant=OptionalTunable(description='\n                    Tuning to make this situation creature UI to use the targeted\n                    situation UI instead of the regular situation creation UI.\n                    ', tunable=TunableEnumEntry(description='\n                        The target participant for this Situation.\n                        ', tunable_type=ParticipantType, default=ParticipantType.TargetSim)), situations_available=OptionalTunable(description="\n                An optional list of situations to filter with. This way, we can\n                pop up the plan an event flow, but restrict the situations that\n                are available. They still have to test for availability, but we\n                won't show others if one or more of these succeed.\n                \n                If the list contains any situations, other situations will not\n                show up if any in the list pass their tests. If the list is\n                empty or this field is disabled, then any situations that pass\n                their tests will be available.\n                ", tunable=TunableList(description='\n                    A list of Situations to restrict the Plan an Event flow.\n                    ', tunable=TunableReference(description='\n                        An available Situation in the Plan an Event flow.\n                        ', manager=services.situation_manager()))))

class TunableSituationStart(TunableFactory):
    __qualname__ = 'TunableSituationStart'

    @staticmethod
    def _factory(interaction, situation, user_facing, **kwargs):

        def start_situation(interaction, situation, user_facing):
            situation_manager = services.get_zone_situation_manager()
            guest_list = situation.get_predefined_guest_list()
            if guest_list is None:
                sim = interaction.sim
                guest_list = SituationGuestList(invite_only=True, host_sim_id=sim.id)
                if situation.targeted_situation is not None:
                    target_sim = interaction.get_participant(ParticipantType.PickedSim)
                    if target_sim is None:
                        target_sim = interaction.get_participant(ParticipantType.TargetSim)
                    target_sim_id = target_sim.id if target_sim is not None else None
                    job_assignments = situation.get_prepopulated_job_for_sims(sim, target_sim_id)
                    for (sim_id, job_type_id) in job_assignments:
                        job_type = services.situation_job_manager().get(job_type_id)
                        guest_info = SituationGuestInfo.construct_from_purpose(sim_id, job_type, SituationInvitationPurpose.INVITED)
                        guest_list.add_guest_info(guest_info)
                else:
                    default_job = situation.default_job()
                    target_sims = interaction.get_participants(ParticipantType.PickedSim)
                    if target_sims:
                        for sim_or_sim_info in target_sims:
                            guest_info = SituationGuestInfo.construct_from_purpose(sim_or_sim_info.sim_id, default_job, SituationInvitationPurpose.INVITED)
                            guest_list.add_guest_info(guest_info)
                    else:
                        target_sim = interaction.get_participant(ParticipantType.TargetSim)
                        if target_sim is not None:
                            guest_info = SituationGuestInfo.construct_from_purpose(target_sim.sim_id, default_job, SituationInvitationPurpose.INVITED)
                            guest_list.add_guest_info(guest_info)
                    guest_info = SituationGuestInfo.construct_from_purpose(sim.sim_id, default_job, SituationInvitationPurpose.INVITED)
                    guest_list.add_guest_info(guest_info)
            zone_id = interaction.get_participant(ParticipantType.PickedZoneId) or 0
            situation_manager.create_situation(situation, guest_list=guest_list, user_facing=user_facing, zone_id=zone_id)

        return lambda : start_situation(interaction, situation, user_facing)

    def __init__(self, **kwargs):
        super().__init__(situation=TunableReference(description='\n                The Situation to start when this Interaction runs.\n                ', manager=services.situation_manager()), user_facing=Tunable(description='\n                If checked, then the situation will be user facing (have goals, \n                and scoring).\n                \n                If not checked, then situation will not be user facing.\n                \n                This setting does not override the user option to make all\n                situations non-scoring.\n                \n                Example: \n                    Date -> Checked\n                    Invite To -> Not Checked\n                ', tunable_type=bool, default=True), description='Start a Situation as part of this Interaction.')

    FACTORY_TYPE = _factory

class CreateSituationElement(XevtTriggeredElement):
    __qualname__ = 'CreateSituationElement'
    FACTORY_TUNABLES = {'create_situation': TunableVariant(description='\n            Determine how to create a specific situation.\n            ', situation_creation_ui=TunableSituationCreationUI(), situation_start=TunableSituationStart())}

    def _do_behavior(self, *args, **kwargs):
        return self.create_situation(self.interaction, *args, **kwargs)()

class TunableUserAskNPCToLeave(TunableFactory):
    __qualname__ = 'TunableUserAskNPCToLeave'

    @staticmethod
    def _factory(interaction, subject, sequence=()):

        def ask_sim_to_leave(_):
            situation_manager = services.get_zone_situation_manager()
            subjects = interaction.get_participants(subject)
            for sim in subjects:
                situation_manager.user_ask_sim_to_leave_now_must_run(sim)

        return (sequence, ask_sim_to_leave)

    def __init__(self, **kwargs):
        super().__init__(subject=TunableEnumEntry(description='\n                                     Who to ask to leave.\n                                     ', tunable_type=ParticipantType, default=ParticipantType.TargetSim), description="\n                Ask the subjects to leave the lot. Only applies to NPCs who don't live here.\n                Situations the subjects are in may introduce additional behavior before they leave.\n                ")

    FACTORY_TYPE = _factory

class TunableMakeNPCLeaveMustRun(TunableFactory):
    __qualname__ = 'TunableMakeNPCLeaveMustRun'

    @staticmethod
    def _factory(interaction, subject, sequence=()):

        def make_sim_leave(_):
            situation_manager = services.get_zone_situation_manager()
            subjects = interaction.get_participants(subject)
            for sim in subjects:
                situation_manager.make_sim_leave_now_must_run(sim)

        return (sequence, make_sim_leave)

    def __init__(self, **kwargs):
        super().__init__(subject=TunableEnumEntry(description='\n                                     Who to ask to leave.\n                                     ', tunable_type=ParticipantType, default=ParticipantType.Actor), description="Make the subject leave the lot proto. E.g. for motive distress. Only applies to NPCs who don't live here.")

    FACTORY_TYPE = _factory

class TunableSituationCondition(TunableVariant):
    __qualname__ = 'TunableSituationCondition'

    def __init__(self, *args, **kwargs):
        super().__init__(time_based=TunableTimeRangeCondition(description='The minimum and maximum amount of time required to satisify this condition.'), event_based=TunableEventBasedCondition(description='A condition that is satsified by some event'), default='time_based', *args, **kwargs)

class TunableSummonNpc(TunableFactory):
    __qualname__ = 'TunableSummonNpc'

    @staticmethod
    def _factory(interaction, subject, purpose, sequence=None, **kwargs):
        venue = services.get_current_venue()
        if venue is None:
            return sequence

        def summon(_):
            subjects = interaction.get_participants(subject)
            sim_info_manager = services.sim_info_manager()
            sim_infos = [sim_info_manager.get(sim_or_sim_info.sim_id) for sim_or_sim_info in subjects]
            host_sim = interaction.get_participant(ParticipantType.Actor)
            venue.summon_npcs(sim_infos, purpose, host_sim.sim_info)

        return (sequence, summon)

    def __init__(self, *args, **kwargs):
        super().__init__(subject=TunableEnumEntry(description='\n                Who to summon.\n                For social interactions use TargetSim.\n                For picker based interactions (phone, rel panel) use PickedSim.\n                ', tunable_type=ParticipantType, default=ParticipantType.TargetSim), purpose=TunableEnumEntry(description='\n                The purpose/reason the NPC is being summoned.\n                ', tunable_type=venues.venue_constants.NPCSummoningPurpose, default=venues.venue_constants.NPCSummoningPurpose.DEFAULT), *args, **kwargs)

    FACTORY_TYPE = _factory

class TunableAffordanceScoring(TunableFactory):
    __qualname__ = 'TunableAffordanceScoring'

    @staticmethod
    def _factory(affordance_list, score, **kwargs):
        affordance = kwargs.get('affordance')
        if affordance and affordance_list(affordance):
            return score
        return 0

    FACTORY_TYPE = _factory

    def __init__(self, **kwargs):
        super().__init__(affordance_list=TunableAffordanceFilterSnippet(), score=Tunable(int, 1, description='score sim will receive if running affordance'))

class TunableQualityMultiplier(TunableFactory):
    __qualname__ = 'TunableQualityMultiplier'

    @staticmethod
    def _factory(obj, stat_to_check, threshold, multiplier):
        tracker = obj.get_tracker(stat_to_check)
        value = tracker.get_value(stat_to_check)
        if threshold.compare(value):
            return multiplier
        return 1

    FACTORY_TYPE = _factory

    def __init__(self, **kwargs):
        super().__init__(stat_to_check=TunableReference(services.statistic_manager()), threshold=TunableThreshold(description='Stat should be greater than this value for object creation to score.'), multiplier=Tunable(float, 1, description='Multiplier to be applied to score if object is created with this quality'))

class TunableSituationPhase(TunableSingletonFactory):
    __qualname__ = 'TunableSituationPhase'
    FACTORY_TYPE = SituationPhase

    def __init__(self, **kwargs):
        super().__init__(job_list=TunableMapping(description='A list of roles associated with the situation.', key_type=TunableReference(services.situation_job_manager(), description='Job reference'), value_type=TunableReference(services.get_instance_manager(sims4.resources.Types.ROLE_STATE), description='Role the job will perform'), key_name='job', value_name='role'), exit_conditions=TunableList(TunableTuple(conditions=TunableList(TunableSituationCondition(description='A condition for a situation or single phase.'), description='A list of conditions that all must be satisfied for the group to be considered satisfied.')), description='A list of condition groups of which if any are satisfied, the group is satisfied.'), duration=TunableSimMinute(description='\n                                                    How long the phase will last in sim minutes.\n                                                    0 means forever, which should be used on the last phase of the situation.\n                                                    ', default=60), **kwargs)

class TunableVenueObjectTags(event_testing.test_variants.NumberTaggedObjectsOwnedFactory):
    __qualname__ = 'TunableVenueObjectTags'

    def __init__(self, **kwargs):
        (super().__init__(locked_args={'desired_state': None}, **kwargs),)

class TunableVenueObject(TunableTuple):
    __qualname__ = 'TunableVenueObject'

    def __init__(self, **kwargs):
        super().__init__(object=TunableVenueObjectTags(description="\n                Specify object tag(s) that must be on this venue. Allows you to\n                group objects, i.e. weight bench, treadmill, and basketball\n                goals are tagged as\n                'exercise objects.'\n                ", export_modes=ExportModes.All), number=TunableRange(description='\n                Number of the tuned object that have to be on the venue. Ex\n                Barstools 4 means you have to have at least 4 barstools before\n                it can be this venue.\n                ', tunable_type=int, default=1, minimum=1, export_modes=ExportModes.All), object_display_name=TunableLocalizedString(description='\n                Name that will be displayed for the object(s)\n                ', export_modes=ExportModes.All), **kwargs)

