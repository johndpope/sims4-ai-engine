from event_testing.resolver import SingleSimResolver
from scheduler import TunableSituationWeeklyScheduleFactory
from sims4.localization import TunableLocalizedString, TunableLocalizedStringFactory
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import Tunable, TunableList, TunableTuple, TunableResourceKey, TunableHouseDescription, TunableReference, AutoFactoryInit, HasTunableSingletonFactory, TunableVariant, OptionalTunable, TunableEnumEntry
from sims4.tuning.tunable_base import ExportModes, GroupNames
from sims4.utils import classproperty
from situations import situation_guest_list
from situations.situation import Situation
from situations.situation_guest_list import SituationGuestList, SituationInvitationPurpose, SituationGuestInfo
from situations.situation_job import SituationJob
from situations.situation_types import GreetedStatus
from situations.tunable import TunableVenueObject
import date_and_time
import distributor
import services
import sims4.log
import sims4.resources
import sims4.tuning
import tag
import venues.venue_constants
logger = sims4.log.Logger('Venues')

class CreateAndAddToSituation(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'CreateAndAddToSituation'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value.situation_to_create is None:
            logger.error('CreateAndAddToSituation {} has no situation specified', source, owner='manus')
        elif value.situation_job is not None:
            jobs = value.situation_to_create.get_tuned_jobs()
            if value.situation_job not in jobs:
                logger.error('CreateAndAddToSituation {} references a job {} that is not tuned in the situation {}.', source, value.situation_job, value.situation_to_create, owner='manus')
        elif value.situation_to_create.default_job() is None:
            logger.error('CreateAndAddToSituation {} references a situation {} \n                without referencing a job and the situation does not have a default job.\n                Either tune a default job on the situation or tune a job reference\n                here.', source, value.situation_to_create, owner='sscholl')

    FACTORY_TUNABLES = {'description': 'Create a new situation of this type and add the NPC to its tuned job.', 'situation_to_create': Situation.TunableReference(), 'situation_job': SituationJob.TunableReference(description="\n                            The situation job to assign the sim to. If set to None\n                            the sim will be assigned to the situation's default job.\n                            "), 'verify_tunable_callback': _verify_tunable_callback}

    def __call__(self, all_sim_infos, host_sim_info=None):
        host_sim_id = host_sim_info.sim_id if host_sim_info is not None else 0
        situation_job = self.situation_job if self.situation_job is not None else self.situation_to_create.default_job()

        def _create_situation(sim_infos):
            guest_list = SituationGuestList(invite_only=True, host_sim_id=host_sim_id)
            for sim_info in sim_infos:
                guest_info = situation_guest_list.SituationGuestInfo.construct_from_purpose(sim_info.sim_id, situation_job, situation_guest_list.SituationInvitationPurpose.INVITED)
                guest_list.add_guest_info(guest_info)
            services.get_zone_situation_manager().create_situation(self.situation_to_create, guest_list=guest_list, user_facing=False)

        if self.situation_to_create.supports_multiple_sims:
            _create_situation(all_sim_infos)
        else:
            for one_sim_info in all_sim_infos:
                _create_situation((one_sim_info,))

class AddToBackgroundSituation(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'AddToBackgroundSituation'

    def __call__(self, sim_infos, host_sim_info=None):
        venue_type = services.get_current_venue()
        if venue_type is None or venue_type.active_background_event_id is None:
            return
        situation = services.get_zone_situation_manager().get(venue_type.active_background_event_id)
        if situation is not None:
            for sim_info in sim_infos:
                situation.invite_sim_to_default_job(sim_info)

class ResidentialLotArrivalBehavior(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'ResidentialLotArrivalBehavior'
    FACTORY_TUNABLES = {'description': '\n            NPC behavior on a residential lot. The behavior is different depending \n            on the lot belonging to the player versus NPC. Greeted behavior can \n            modify behavior as well.\n            ', 'player_sim_lot': CreateAndAddToSituation.TunableFactory(), 'npc_lot_greeted': CreateAndAddToSituation.TunableFactory(), 'npc_lot_ungreeted': CreateAndAddToSituation.TunableFactory()}

    def __call__(self, sim_infos, host_sim_info=None):
        npc_infos = []
        selectable_and_resident_infos = []
        for sim_info in sim_infos:
            if sim_info.is_npc and not sim_info.lives_here:
                npc_infos.append(sim_info)
            else:
                selectable_and_resident_infos.append(sim_info)
        if npc_infos:
            player_lot_id = services.active_household_lot_id()
            active_lot_id = services.active_lot_id()
            if active_lot_id == player_lot_id:
                if self.player_sim_lot is not None:
                    self.player_sim_lot(npc_infos, host_sim_info)
                    if services.get_zone_situation_manager().is_player_greeted():
                        if self.npc_lot_greeted is not None:
                            self.npc_lot_greeted(npc_infos, host_sim_info)
                            if self.npc_lot_ungreeted is not None:
                                self.npc_lot_ungreeted(npc_infos, host_sim_info)
                    elif self.npc_lot_ungreeted is not None:
                        self.npc_lot_ungreeted(npc_infos, host_sim_info)
            elif services.get_zone_situation_manager().is_player_greeted():
                if self.npc_lot_greeted is not None:
                    self.npc_lot_greeted(npc_infos, host_sim_info)
                    if self.npc_lot_ungreeted is not None:
                        self.npc_lot_ungreeted(npc_infos, host_sim_info)
            elif self.npc_lot_ungreeted is not None:
                self.npc_lot_ungreeted(npc_infos, host_sim_info)
        for sim_info in selectable_and_resident_infos:
            while sim_info.get_sim_instance() is None:
                op = distributor.ops.TravelBringToZone([sim_info.sim_id, 0, services.current_zone().id, 0])
                distributor.system.Distributor.instance().add_op_with_no_owner(op)

class ResidentialZoneFixupForNPC(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'ResidentialZoneFixupForNPC'
    FACTORY_TUNABLES = {'description': '\n            Specify what to do with a non resident NPC on a residential lot\n            when the zone has to be fixed up on load. \n            This fix up will occur if sim time or the\n            active household has changed since the zone was last saved.\n            ', 'player_lot_greeted': CreateAndAddToSituation.TunableFactory(), 'npc_lot_greeted': CreateAndAddToSituation.TunableFactory(), 'npc_lot_ungreeted': CreateAndAddToSituation.TunableFactory()}

    def __call__(self, npc_infos):
        situation_manager = services.get_zone_situation_manager()
        player_lot_id = services.active_household_lot_id()
        active_lot_id = services.active_lot_id()
        for sim_info in npc_infos:
            npc = sim_info.get_sim_instance()
            if npc is None:
                pass
            greeted_status = situation_manager.get_npc_greeted_status_during_zone_fixup(sim_info)
            if active_lot_id == player_lot_id:
                logger.debug('Player lot greeted {} during zone fixup', sim_info, owner='sscholl')
                self.player_lot_greeted((sim_info,))
            elif greeted_status == GreetedStatus.WAITING_TO_BE_GREETED:
                logger.debug('NPC lot waiting to be greeted {} during zone fixup', sim_info, owner='sscholl')
                self.npc_lot_ungreeted((sim_info,))
            elif greeted_status == GreetedStatus.GREETED:
                logger.debug('NPC lot greeted {} during zone fixup', sim_info, owner='sscholl')
                self.npc_lot_greeted((sim_info,))
            else:
                logger.debug('No option for {} during zone fixup', sim_info, owner='sscholl')

class ResidentialTravelDisplayName(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'ResidentialTravelDisplayName'
    FACTORY_TUNABLES = {'description': '\n        Specify the contextual string for when a user clicks to travel to an\n        adjacent lot in the street.\n        ', 'ring_doorbell_name': TunableLocalizedStringFactory(description='\n            The interaction name for when the actor doesn\'t know any Sims that live on the\n            destination lot.\n            \n            Tokens: 0:ActorSim\n            Example: "Ring Doorbell"\n            '), 'visit_sim_name': TunableLocalizedStringFactory(description='\n            The interaction name for when the actor knows exactly one Sim that lives on the\n            destination lot.\n            \n            Tokens: 0:ActorSim, 1:Sim known\n            Example: "Visit {1.SimName}"\n            '), 'visit_household_name': TunableLocalizedStringFactory(description='\n            The interaction name for when the actor knows more than one Sim\n            that lives on the destination lot, or the Sim they know is not at\n            home.\n            \n            Tokens: 0:ActorSim, 1:Household Name\n            Example: "Visit The {1.String} Household"\n            '), 'visit_the_household_plural_name': TunableLocalizedStringFactory(description='\n            The interaction name for when the actor knows more than one Sim\n            that lives on the destination lot, or the Sim they know is not at\n            home, and everyone who lives there has the same household name as\n            their last name.\n            \n            Tokens: 0:ActorSim, 1:Household Name\n            Example: "Visit The {1.String|enHouseholdNamePlural}"\n            '), 'no_one_home_encapsulation': TunableLocalizedStringFactory(description='\n            The string that gets appended on the end of our interaction string\n            if none of the household Sims at the destination lot are home.\n            \n            Tokens: 0:Interaction Name\n            Example: "{0.String} (No One At Home)"\n            '), 'go_here_name': TunableLocalizedStringFactory(description='\n            The interaction name for when no household lives on the destination\n            lot.\n            \n            Tokens: 0:ActorSim\n            Example: "Go Here"\n            '), 'go_home_name': TunableLocalizedStringFactory(description='\n            The interaction name for when the actor\'s home lot is the\n            destination lot.\n            \n            Tokens: 0:ActorSim\n            Example: "Go Home"\n            ')}

    def __call__(self, target, context):
        sim = context.sim
        lot_id = context.pick.lot_id
        if lot_id is None:
            return
        persistence_service = services.get_persistence_service()
        to_zone_id = persistence_service.resolve_lot_id_into_zone_id(lot_id)
        if to_zone_id is None:
            return
        if sim.household.home_zone_id == to_zone_id:
            return self.go_home_name(sim)
        household_id = None
        lot_owner_info = persistence_service.get_lot_proto_buff(lot_id)
        if lot_owner_info is not None:
            for household in lot_owner_info.lot_owner:
                household_id = household.household_id
                break
        if household_id:
            household = services.household_manager().get(household_id)
        else:
            household = None
        if household is None:
            return self.go_here_name(sim)
        sim_infos_known = False
        sim_infos_known_at_home = []
        sim_infos_at_home = False
        same_last_name = True
        for sim_info in household.sim_info_gen():
            if sim_info.relationship_tracker.get_all_bits(sim.id):
                sim_infos_known = True
                if sim_info.zone_id == to_zone_id:
                    sim_infos_known_at_home.append(sim_info)
            elif sim_info.zone_id == to_zone_id:
                sim_infos_at_home = True
            while not sim_info.last_name == household.name:
                same_last_name = False
        if not sim_infos_known:
            travel_name = self.ring_doorbell_name(sim)
        else:
            if len(sim_infos_known_at_home) == 1:
                return self.visit_sim_name(sim, sim_infos_known_at_home[0])
            if same_last_name:
                travel_name = self.visit_the_household_plural_name(sim, household.name)
            else:
                travel_name = self.visit_household_name(sim, household.name)
        if not sim_infos_at_home:
            return self.no_one_home_encapsulation(travel_name)
        return travel_name

class Venue(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.VENUE)):
    __qualname__ = 'Venue'
    INSTANCE_TUNABLES = {'display_name': TunableLocalizedString(description='\n            Name that will be displayed for the venue\n            ', export_modes=ExportModes.All), 'display_name_incomplete': TunableLocalizedString(description='\n            Name that will be displayed for the incomplete venue\n            ', export_modes=ExportModes.All), 'venue_description': TunableLocalizedString(description='Description of Venue that will be displayed', export_modes=ExportModes.All), 'venue_icon': TunableResourceKey(None, resource_types=sims4.resources.CompoundTypes.IMAGE, description='Venue Icon for UI', export_modes=ExportModes.All), 'venue_thumbnail': TunableResourceKey(None, resource_types=sims4.resources.CompoundTypes.IMAGE, description='Image of Venue that will be displayed', export_modes=ExportModes.All), 'allow_game_triggered_events': Tunable(description='\n            Whether this venue can have game triggered events. ex for careers\n            ', tunable_type=bool, default=False), 'background_event_schedule': TunableSituationWeeklyScheduleFactory(description='\n            The Background Events that run on this venue. They run underneath\n            any user facing Situations and there can only be one at a time. The\n            schedule times and durations are windows in which background events\n            can start.\n            '), 'special_event_schedule': TunableSituationWeeklyScheduleFactory(description='\n            The Special Events that run on this venue. These run on top of\n            Background Events. We run only one user facing event at a time, so\n            if the player started something then this may run in the\n            background, otherwise the player will be invited to join in on this\n            Venue Special Event.\n            '), 'required_objects': TunableList(description='\n            A list of objects that are required to be on a lot before\n            that lot can be labeled as this venue.\n            ', tunable=TunableVenueObject(description="\n                    Specify object tag(s) that must be on this venue.\n                    Allows you to group objects, i.e. weight bench,\n                    treadmill, and basketball goals are tagged as\n                    'exercise objects.'\n                    \n                    This is not the same as automatic objects tuning. \n                    Please read comments for both the fields.\n                    "), export_modes=ExportModes.All), 'npc_summoning_behavior': sims4.tuning.tunable.TunableMapping(description='\n            Whenever an NPC is summoned to a lot by the player, determine\n            which action to take based on the summoning purpose. The purpose\n            is a dynamic enum: venues.venue_constants.NPCSummoningPurpose.\n            \n            The action will generally involve either adding a sim to an existing\n            situation or creating a situation then adding them to it.\n            \n            \\depot\\Sims4Projects\\Docs\\Design\\Open Streets\\Open Street Invite Matrix.xlsx\n            \n            residential: This is behavior pushed on the NPC if this venue was a residential lot.\n            create_situation: Place the NPC in the specified situation/job pair.\n            add_to_background_situation: Add the NPC the currently running background \n            situation in the venue.\n            ', key_type=sims4.tuning.tunable.TunableEnumEntry(venues.venue_constants.NPCSummoningPurpose, venues.venue_constants.NPCSummoningPurpose.DEFAULT), value_type=TunableVariant(locked_args={'disabled': None}, residential=ResidentialLotArrivalBehavior.TunableFactory(), create_situation=CreateAndAddToSituation.TunableFactory(), add_to_background_situation=AddToBackgroundSituation.TunableFactory(), default='disabled'), tuning_group=GroupNames.TRIGGERS), 'player_requires_visitation_rights': OptionalTunable(description='If enabled, then lots of this venue type  \n            will require player Sims that are not on their home lot to go through \n            the process of being greeted before they are\n            given full rights to using the lot.\n            ', tunable=TunableTuple(ungreeted=Situation.TunableReference(description='\n                    The situation to create for ungreeted player sims on this lot.', display_name='Player Ungreeted Situation'), greeted=Situation.TunableReference(description='\n                    The situation to create for greeted player sims on this lot.', display_name='Player Greeted Situation'))), 'zone_fixup': TunableVariant(description='\n            Specify what to do with a non resident NPC\n            when the zone has to be fixed up on load. \n            This fix up will occur if sim time or the\n            active household has changed since the zone was last saved.\n            ', residential=ResidentialZoneFixupForNPC.TunableFactory(), create_situation=CreateAndAddToSituation.TunableFactory(), add_to_background_situation=AddToBackgroundSituation.TunableFactory(), default='residential', tuning_group=GroupNames.SPECIAL_CASES), 'travel_interaction_name': TunableVariant(description='\n            Specify what name a travel interaction gets when this Venue is an\n            adjacent lot.\n            ', visit_residential=ResidentialTravelDisplayName.TunableFactory(description='\n                The interaction name for when the destination lot is a\n                residence.\n                '), visit_venue=TunableLocalizedStringFactory(description='\n                The interaction name for when the destination lot is a\n                commercial venue.\n                Tokens: 0:ActorSim\n                Example: "Visit The Bar"\n                '), tuning_group=GroupNames.SPECIAL_CASES), 'travel_with_interaction_name': TunableVariant(description='\n            Specify what name a travel interaction gets when this Venue is an\n            adjacent lot.\n            ', visit_residential=ResidentialTravelDisplayName.TunableFactory(description='\n                The interaction name for when the destination lot is a\n                residence and the actor Sim is traveling with someone.\n                '), visit_venue=TunableLocalizedStringFactory(description='\n                The interaction name for when the destination lot is a\n                commercial venue and the actor is traveling with someone.\n                Tokens: 0:ActorSim\n                Example: "Visit The Bar With..."\n                '), tuning_group=GroupNames.SPECIAL_CASES), 'venue_requires_front_door': Tunable(description='\n            True if this venue should run the front door generation code. \n            If it runs, venue will have the ring doorbell interaction and \n            its additional behavior.\n            ', tunable_type=bool, default=False), 'automatic_objects': TunableList(description='\n            A list of objects that is required to exist on this venue (e.g. the\n            mailbox). If any of these objects are missing from this venue, they\n            will be auto-placed on zone load.', tunable=TunableTuple(description="\n                An item that is required to be present on this venue. The object's tag \n                will be used to determine if any similar objects are present. If no \n                similar objects are present, then the object's actual definition is used to \n                create an object of this type.\n                \n                This is not the same as required objects tuning. Please read comments \n                for both the fields.\n                \n                E.g. To require a mailbox to be present on a lot, tune a hypothetical basicMailbox \n                here. The code will not trigger as long as a basicMailbox, fancyMailbox, or \n                cheapMailbox are present on the lot. If none of them are, then a basicMailbox \n                will be automatically created.\n                ", default_value=TunableReference(manager=services.definition_manager(), description='The default object to use if no suitably tagged object is present on the lot.'), tag=TunableEnumEntry(description='The tag to search for', tunable_type=tag.Tag, default=tag.Tag.INVALID))), 'hide_from_buildbuy_ui': Tunable(description='\n            If True, this venue type will not be available in the venue picker\n            in build/buy.\n            ', tunable_type=bool, default=False, export_modes=ExportModes.All), 'allows_fire': Tunable(description='\n            If True a fire can happen on this venue, \n            otherwise fires will not spawn on this venue.\n            ', tunable_type=bool, default=False), 'allow_rolestate_routing_on_navmesh': Tunable(description='\n            Allow all RoleStates routing permission on lot navmeshes of this\n            venue type. This is particularly useful for outdoor venue types\n            (lots with no walls), where it is awkward to have to "invite a sim\n            in" before they may route on the lot, be called over, etc.\n            \n            This tunable overrides the "Allow Npc Routing On Active Lot"\n            tunable of individual RoleStates.\n            ', tunable_type=bool, default=False)}

    @classmethod
    def _verify_tuning_callback(cls):
        if cls.special_event_schedule is not None:
            for entry in cls.special_event_schedule.schedule_entries:
                while entry.situation.venue_situation_player_job is None:
                    logger.error('Venue Situation Player Job {} tuned in Situation: {}', entry.situation.venue_situation_player_job, entry.situation)

    def __init__(self, **kwargs):
        self._active_background_event_id = None
        self._active_special_event_id = None
        self._background_event_schedule = None
        self._special_event_schedule = None

    def set_active_event_ids(self, background_event_id=None, special_event_id=None):
        self._active_background_event_id = background_event_id
        self._active_special_event_id = special_event_id

    @property
    def active_background_event_id(self):
        return self._active_background_event_id

    @property
    def active_special_event_id(self):
        return self._active_special_event_id

    def schedule_background_events(self, schedule_immediate=True):
        self._background_event_schedule = self.background_event_schedule(start_callback=self._start_background_event, schedule_immediate=False)
        if schedule_immediate:
            (best_time_span, best_data_list) = self._background_event_schedule.time_until_next_scheduled_event(services.time_service().sim_now, schedule_immediate=True)
            if best_time_span is not None and best_time_span == date_and_time.TimeSpan.ZERO:
                while True:
                    for best_data in best_data_list:
                        self._start_background_event(self._background_event_schedule, best_data)

    def schedule_special_events(self, schedule_immediate=True):
        self._special_event_schedule = self.special_event_schedule(start_callback=self._try_start_special_event, schedule_immediate=schedule_immediate)

    def _start_background_event(self, scheduler, alarm_data, extra_data=None):
        entry = alarm_data.entry
        situation = entry.situation
        situation_manager = services.get_zone_situation_manager()
        if self._active_background_event_id is not None and self._active_background_event_id in situation_manager:
            situation_manager.destroy_situation_by_id(self._active_background_event_id)
        situation_id = services.get_zone_situation_manager().create_situation(situation, user_facing=False, spawn_sims_during_zone_spin_up=True)
        self._active_background_event_id = situation_id

    def _try_start_special_event(self, scheduler, alarm_data, extra_data):
        entry = alarm_data.entry
        situation = entry.situation
        situation_manager = services.get_zone_situation_manager()
        if self._active_special_event_id is None:
            client_manager = services.client_manager()
            client = next(iter(client_manager.values()))
            invited_sim = client.active_sim
            active_sim_available = situation.is_situation_available(invited_sim)

            def _start_special_event(dialog):
                guest_list = None
                if dialog.accepted:
                    start_user_facing = True
                    guest_list = SituationGuestList()
                    guest_info = SituationGuestInfo.construct_from_purpose(invited_sim.id, situation.venue_situation_player_job, SituationInvitationPurpose.INVITED)
                    guest_list.add_guest_info(guest_info)
                else:
                    start_user_facing = False
                situation_id = situation_manager.create_situation(situation, guest_list=guest_list, user_facing=start_user_facing)
                self._active_special_event_id = situation_id

            if not situation_manager.is_user_facing_situation_running() and active_sim_available:
                dialog = situation.venue_invitation_message(invited_sim, SingleSimResolver(invited_sim))
                dialog.show_dialog(on_response=_start_special_event, additional_tokens=(situation.display_name, situation.venue_situation_player_job.display_name))
            else:
                situation_id = situation_manager.create_situation(situation, user_facing=False)
                self._active_special_event_id = situation_id

    def shut_down(self):
        if self._background_event_schedule is not None:
            self._background_event_schedule.destroy()
        if self._special_event_schedule is not None:
            self._special_event_schedule.destroy()
        situation_manager = services.get_zone_situation_manager()
        if self._active_background_event_id is not None:
            situation_manager.destroy_situation_by_id(self._active_background_event_id)
            self._active_background_event_id = None
        if self._active_special_event_id is not None:
            situation_manager.destroy_situation_by_id(self._active_special_event_id)
            self._active_special_event_id = None

    @classmethod
    def lot_has_required_venue_objects(cls, lot):
        failure_reasons = []
        for required_object_tuning in cls.required_objects:
            object_test = required_object_tuning.object
            object_list = object_test()
            num_objects = len(object_list)
            while num_objects < required_object_tuning.number:
                pass
        failure_message = None
        failure = len(failure_reasons) > 0
        if failure:
            failure_message = ''
            for message in failure_reasons:
                failure_message += message + '\n'
        return (not failure, failure_message)

    def summon_npcs(self, npc_infos, purpose, host_sim_info=None):
        if self.npc_summoning_behavior is None:
            return
        summon_behavior = self.npc_summoning_behavior.get(purpose)
        if summon_behavior is None:
            summon_behavior = self.npc_summoning_behavior.get(venues.venue_constants.NPCSummoningPurpose.DEFAULT)
            if summon_behavior is None:
                return
        summon_behavior(npc_infos, host_sim_info)

    @classproperty
    def requires_visitation_rights(cls):
        return cls.player_requires_visitation_rights is not None

    @classproperty
    def player_ungreeted_situation_type(cls):
        if cls.player_requires_visitation_rights is None:
            return
        return cls.player_requires_visitation_rights.ungreeted

    @classproperty
    def player_greeted_situation_type(cls):
        if cls.player_requires_visitation_rights is None:
            return
        return cls.player_requires_visitation_rights.greeted

class MaxisLotData(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.MAXIS_LOT)):
    __qualname__ = 'MaxisLotData'
    INSTANCE_TUNABLES = {'household_description': TunableHouseDescription(description='\n                The household description for this static lot.\n                '), 'venue_types': TunableList(tunable=TunableReference(description='\n                    Venue types for which this venue lot is valid.\n                    ', manager=services.get_instance_manager(sims4.resources.Types.VENUE), class_restrictions=Venue))}

    @classmethod
    def supports_any_venue_type(cls, venue_types):
        for venue_type in cls.venue_types:
            while venue_type in venue_types:
                return True
        return False

    @classmethod
    def get_intersecting_venue_types(cls, venue_types):
        intersecting_venues = []
        for venue_type in cls.venue_types:
            while venue_type in venue_types:
                intersecting_venues.append(venue_type)
        if intersecting_venues:
            return intersecting_venues

