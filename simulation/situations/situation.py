import collections
import random
from buffs.tunable import TunableBuffReference
from event_testing.results import TestResult
from interactions import ParticipantTypeActorTargetSim
from relationships.relationship_bit import RelationshipBit
from rewards import reward_tuning
from sims4.localization import TunableLocalizedString, TunableLocalizedStringFactory
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableList, TunableReference, TunableTuple, Tunable, TunableResourceKey, TunableSimMinute, TunableEnumEntry, OptionalTunable, TunableVariant, HasTunableReference, TunableEntitlement, HasTunableSingletonFactory, AutoFactoryInit, TunableSet, TunableEnumWithFilter, TunableRange
from sims4.tuning.tunable_base import GroupNames
from sims4.utils import classproperty
from situations.base_situation import BaseSituation
from situations.situation_job import SituationJob
from situations.situation_types import SituationCategoryUid, SituationCreationUIOption, SituationMedal
from tag import Tag
from ui.ui_dialog import UiDialogOkCancel
import alarms
import clock
import event_testing.resolver
import event_testing.test_variants
import services
import sims4.log
import sims4.random
import sims4.resources
import situations.bouncer.bouncer_types
import situations.situation_goal_set
import ui.screen_slam
logger = sims4.log.Logger('Situations')

class TunableSituationLevel(TunableTuple):
    __qualname__ = 'TunableSituationLevel'

    def __init__(self, description='A single tunable Situation level.', **kwargs):
        super().__init__(medal=TunableEnumEntry(description='\n                The corresponding medal (Tin, Bronze, etc.) associated with this level.\n                ', tunable_type=SituationMedal, default=SituationMedal.TIN), score_delta=TunableRange(description='\n                The amount of score from the previous Situation Level that the\n                player need to acquire before the situation is considered in\n                this Situation Level.\n                ', tunable_type=int, default=30, minimum=0), level_description=TunableLocalizedString(description='\n                Description of situation at level. This message is passed to UI\n                whenever we complete the situation.\n                '), reward=reward_tuning.Reward.TunableReference(description="\n                The Reward received when reaching this level of the Situation.\n                To give a specific SituationJobReward for a specific job, \n                you can tune that information at SituationJob's rewards field.\n                "), audio_sting_on_end=TunableResourceKey(description='\n                The sound to play when a situation ends at this level.\n                ', default=None, resource_types=(sims4.resources.Types.PROPX,)), description=description, **kwargs)

class TunableSituationInitiationTestVariant(TunableVariant):
    __qualname__ = 'TunableSituationInitiationTestVariant'

    def __init__(self, description='A single tunable test.', **kwargs):
        super().__init__(test_initiating_sim_against_filter=event_testing.test_variants.TunableFilterTest(description='\n            Test the sim attempting to initiate a situation against a specific\n            filter.  Passes as long as that sim matches the filter.\n            ', locked_args={'filter_target': None, 'relative_sim': ParticipantTypeActorTargetSim.Actor}), test_all_sims_against_filter=event_testing.test_variants.TunableFilterTest(description='\n            Test all sims to see if there are any sims that match the filter.\n            Passes if any sims match the filter.\n            ', locked_args={'filter_target': None, 'relative_sim': ParticipantTypeActorTargetSim.Actor}), statistic=event_testing.test_variants.TunableStatThresholdTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor)), skill_tag=event_testing.test_variants.TunableSkillTagThresholdTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor)), sim_info=event_testing.test_variants.TunableSimInfoTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor), locked_args={'can_age_up': None}), trait=event_testing.test_variants.TunableTraitTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor)), unlock=event_testing.test_variants.TunableUnlockedTest(unlock_type_override={'allow_achievment': False}), description=description, **kwargs)

class TunableSituationInitiationSet(event_testing.tests.TestListLoadingMixin):
    __qualname__ = 'TunableSituationInitiationSet'
    DEFAULT_LIST = event_testing.tests.TestList()

    def __init__(self, description=None):
        if description is None:
            description = 'A list of tests.  All tests must succeed to pass the TestSet.'
        super().__init__(description=description, tunable=TunableSituationInitiationTestVariant())

class TunableNPCHostedPlayerTestVariant(TunableVariant):
    __qualname__ = 'TunableNPCHostedPlayerTestVariant'

    def __init__(self, description='A single tunable test.', **kwargs):
        super().__init__(statistic=event_testing.test_variants.TunableStatThresholdTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor), locked_args={'tooltip': None}), skill_tag=event_testing.test_variants.TunableSkillTagThresholdTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor), locked_args={'tooltip': None}), sim_info=event_testing.test_variants.TunableSimInfoTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor), locked_args={'tooltip': None, 'can_age_up': None}), trait=event_testing.test_variants.TunableTraitTest(participant_type_override=(ParticipantTypeActorTargetSim, ParticipantTypeActorTargetSim.Actor), locked_args={'tooltip': None}), unlock=event_testing.test_variants.TunableUnlockedTest(unlock_type_override={'allow_achievment': False}, locked_args={'tooltip': None}), user_facing_situation_running_test=event_testing.test_variants.TunableUserFacingSituationRunningTest(), description=description, **kwargs)

class TunableNPCHostedPlayerTestSet(event_testing.tests.TestListLoadingMixin):
    __qualname__ = 'TunableNPCHostedPlayerTestSet'
    DEFAULT_LIST = event_testing.tests.TestList()

    def __init__(self, description=None, **kwargs):
        if description is None:
            description = 'A list of tests.  All tests must succeed to pass the TestSet.'
        super().__init__(description=description, tunable=TunableNPCHostedPlayerTestVariant(), **kwargs)

class TargetedSituationSpecific(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'TargetedSituationSpecific'
    FACTORY_TUNABLES = {'target_job': SituationJob.TunableReference(description='\n            This is the job for the target sim, the one being asked.\n            After a player selects a target sim they will\n            be given a list of situations to choose from. Only situations\n            in which their selected sim matches the filter on this job will\n            be included.\n    \n            This field is required for targeted situations.\n            '), 'actor_job': SituationJob.TunableReference(description='\n            This is the job for the actor sim, the one doing the asking.\n            A sim will only be able to initiate this situation\n            if they match the filter in this job and pass the \n            initiating_sim_tests (another tuning field on situations).\n            It will be common for the filter in this job to be None.\n            \n            This field is required for targeted situations.\n            ')}

class Situation(BaseSituation, HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.SITUATION)):
    __qualname__ = 'Situation'
    INSTANCE_SUBCLASSES_ONLY = True
    INSTANCE_TUNABLES = {'category': TunableEnumEntry(description='\n                The Category that the Situation belongs to.\n                ', tunable_type=SituationCategoryUid, default=SituationCategoryUid.DEFAULT, tuning_group=GroupNames.UI), '_display_name': TunableLocalizedString(description='\n                Display name for situation\n                ', tuning_group=GroupNames.UI), 'situation_description': TunableLocalizedString(description='\n                Situation Description\n                ', tuning_group=GroupNames.UI), 'entitlement': TunableEntitlement(description='\n                Entitlement required to plan this event.\n                ', tuning_group=GroupNames.UI), '_default_job': TunableReference(description='\n                The default job for Sims in this situation\n                ', manager=services.situation_job_manager()), '_resident_job': SituationJob.TunableReference(description='\n                The job to assign to members of the host sims household.\n                Make sure to use the in_family filter term in the filter\n                of the job you reference here.\n                It is okay if this tunable is None.\n                '), '_icon': TunableResourceKey(description='\n                Icon to be displayed in the situation UI.\n                ', default=None, resource_types=sims4.resources.CompoundTypes.IMAGE, tuning_group=GroupNames.UI), '_level_data': TunableTuple(tin=TunableSituationLevel(description='\n                    Tuning for the Tin level of this situation.  This level has\n                    a score delta of 0 as it is considered the default level\n                    of any situation.\n                    ', locked_args={'medal': SituationMedal.TIN, 'score_delta': 0}), bronze=TunableSituationLevel(description='\n                    Tuning for the Bronze level of this situation.\n                    ', locked_args={'medal': SituationMedal.BRONZE}), silver=TunableSituationLevel(description='\n                    Tuning for the Silver level of this situation.\n                    ', locked_args={'medal': SituationMedal.SILVER}), gold=TunableSituationLevel(description='\n                    Tuning for the Gold level of this situation.\n                    ', locked_args={'medal': SituationMedal.GOLD}), description='\n                    Tuning for the different situation levels and rewards that\n                    are associated with them.\n                    '), 'job_display_ordering': OptionalTunable(description='\n            An optional list of the jobs in the order you want them displayed\n            in the Plan an Event UI.\n            ', tunable=TunableList(tunable=TunableReference(manager=services.situation_job_manager())), tuning_group=GroupNames.UI), 'recommended_job_object_notification': ui.ui_dialog_notification.UiDialogNotification.TunableFactory(description='\n            The notification that is displayed when one or more recommended objects\n            for a job are missing.\n            ', locked_args={'text': None}), 'recommended_job_object_text': TunableLocalizedStringFactory(description='\n            The text of the notification that is displayed when one or more recommended\n            objects for a job are missing.\n            \n            The localization tokens for the Text field are:\n            {0.String} = bulleted list of strings for the missing objects\n            '), '_buff': TunableBuffReference(description='\n                Buff that will get added to sim when commodity is at this\n                current state.\n                '), '_cost': Tunable(description='\n                The cost of this situation\n                ', tunable_type=int, default=0), 'exclusivity': TunableEnumEntry(description='\n            Defines the exclusivity category for the situation which is used to prevent sims assigned\n            to this situation from being assigned to situations from categories excluded by this\n            category and vice versa.\n            ', tunable_type=situations.bouncer.bouncer_types.BouncerExclusivityCategory, default=situations.bouncer.bouncer_types.BouncerExclusivityCategory.NORMAL), 'main_goal': TunableReference(description='The main goal of the situation. e.g. Get Married.', manager=services.get_instance_manager(sims4.resources.Types.SITUATION_GOAL), tuning_group=GroupNames.GOALS), 'main_goal_audio_sting': TunableResourceKey(description='\n                The sound to play when the main goal of this situation\n                completes.\n                ', default=None, resource_types=(sims4.resources.Types.PROPX,), tuning_group=GroupNames.AUDIO), 'minor_goal_chains': TunableList(description='\n                A list of goal sets, each one starting a chain of goal sets, for selecting minor goals.\n                The list is in priority order, first being the most important.\n                At most one goal will be selected from each chain.\n                ', tunable=situations.situation_goal_set.SituationGoalSet.TunableReference(), tuning_group=GroupNames.GOALS), 'force_invite_only': Tunable(description='\n                If True, the situation is invite only. Otherwise, it is not.\n                For a date situation, this would be set to True.\n                ', tunable_type=bool, default=False), 'creation_ui_option': TunableEnumEntry(description='\n                Determines if the situation can be created from the Plan Event\n                UI triggered from the phone.\n                \n                NOT_AVAILABLE - situation is not available in the creation UI.\n                \n                AVAILABLE - situation is available in the creation UI.\n                \n                DEBUG_AVAILABLE - situation is only available in the UI if\n                you have used the |situations.allow_debug_situations command\n                ', tunable_type=SituationCreationUIOption, default=SituationCreationUIOption.AVAILABLE, tuning_group=GroupNames.UI), 'audio_sting_on_start': TunableResourceKey(description='\n                The sound to play when the Situation starts.\n                ', default=None, resource_types=(sims4.resources.Types.PROPX,), tuning_group=GroupNames.AUDIO), 'duration': TunableSimMinute(description='\n                How long the situation will last in sim minutes. 0 means forever.\n                ', default=60), 'max_participants': Tunable(description='\n                Maximum number of Sims the player is allowed to invite to this Situation.\n                ', tunable_type=int, default=16, tuning_group=GroupNames.UI), '_initiating_sim_tests': TunableSituationInitiationSet('\n            A set of tests that will be run on a sim attempting to initiate a\n            situation.  If these tests do not pass than this situation will not\n            be able to be chosen from the UI.\n            '), 'targeted_situation': OptionalTunable(description='\n                If enabled, the situation can be used as a targeted situation,\n                such as a Date.\n                ', tunable=TargetedSituationSpecific.TunableFactory()), '_NPC_host_filter': TunableReference(description='\n                A sim filter that will be used to get NPC sims to host this\n                situation if it is connected to an NPC hosted event.\n                ', manager=services.get_instance_manager(sims4.resources.Types.SIM_FILTER), tuning_group=GroupNames.NPC_HOSTED_EVENTS), '_NPC_hosted_player_tests': TunableNPCHostedPlayerTestSet(description='\n                A series of tests that will be run on all of the active sims on\n                the family to determine if this sim can be asked to attend an\n                NPC hosted event.\n                ', tuning_group=GroupNames.NPC_HOSTED_EVENTS), 'NPC_hosted_situation_start_message': UiDialogOkCancel.TunableFactory(description='\n                The message that will be displayed when this situation\n                tries to start for the initiating sim.\n                ', tuning_group=GroupNames.NPC_HOSTED_EVENTS), 'NPC_hosted_situation_player_job': TunableReference(description='\n                The job that the player will be put into when they they are\n                invited into an NPC hosted version of this event.\n                ', manager=services.get_instance_manager(sims4.resources.Types.SITUATION_JOB), tuning_group=GroupNames.NPC_HOSTED_EVENTS), 'NPC_hosted_situation_use_player_sim_as_filter_requester': Tunable(description='\n                If checked then when gathering sims for an NPC hosted situation\n                the filter system will look at households and and relationships\n                relative to the player sim rather than the NPC host.\n                ', tunable_type=bool, default=False, tuning_group=GroupNames.NPC_HOSTED_EVENTS), 'venue_types': TunableList(description='\n                In the Plan an Event UI, lots that are of these venue types\n                will be added to the list of lots on which the player can throw\n                the event. The player can always choose their own lot and lots of their guests.\n                ', tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.VENUE), tuning_group=GroupNames.VENUES)), 'venue_invitation_message': UiDialogOkCancel.TunableFactory(description="\n                The message that will be displayed when this situation\n                tries to start for the venue.\n                \n                Two additional tokens are passed in: the situation's name and the job's name.\n                ", tuning_group=GroupNames.VENUES), 'venue_situation_player_job': TunableReference(description="\n                The job that the player will be put into when they join in a\n                user_facing special situation at a venue.\n                \n                Note: This must be tuned to allow this situation to be in a\n                venue's special event schedule. The job also must be a part of\n                the Situation.\n                ", manager=services.get_instance_manager(sims4.resources.Types.SITUATION_JOB), tuning_group=GroupNames.VENUES), 'tags': TunableSet(description='\n                Tags for arbitrary groupings of situation types.\n                ', tunable=TunableEnumWithFilter(tunable_type=Tag, filter_prefixes=['situation'], default=Tag.INVALID)), '_relationship_between_job_members': TunableList(description="\n                Whenever a sim joins either job_x or job_y, the sim is granted \n                the tuned relationship bit with every sim in the other job. The\n                relationship bits are added and remain as long as the sims are\n                assigned to the tuned pair of jobs.\n                \n                This creates a relationship between the two sims if one does not exist.\n                \n                E.g. Date situation uses this feature to add bits to the sims'\n                relationship in order to drive autonomous behavior during the \n                lifetime of the date. \n                ", tunable=TunableTuple(job_x=SituationJob.TunableReference(), job_y=SituationJob.TunableReference(), relationship_bits_to_add=TunableSet(description='\n                        A set of RelationshipBits to add to relationship between the sims.\n                        ', tunable=RelationshipBit.TunableReference())), tuning_group=GroupNames.TRIGGERS), '_jobs_to_put_in_party': TunableSet(description='\n                Sims belonging to these jobs are added to a party. This gives the player\n                an additional control over the new group of sims.\n                \n                Use this field with caution. We only support a party of two sims.\n                The date situation adds the two participating sims in their \n                respective jobs into a party.\n                ', tunable=SituationJob.TunableReference(), tuning_group=GroupNames.TRIGGERS), '_implies_greeted_status': Tunable(description='\n                If checked then a sim, in this situation, on a residential lot\n                they do not own, is consider greeted on that lot.\n                \n                Greeted status related design documents:\n                //depot/Sims4Projects/docs/Design/Gameplay/HouseholdState/Ungreeted_Lot_Behavior_DD.docx\n                //depot/Sims4Projects/docs/Design/Gameplay/Simulation/Active Lot Changing Edge Cases.docx\n                ', tunable_type=bool, default=False), 'screen_slam_no_medal': OptionalTunable(description='\n            Screen slam to show when this situation is completed and no\n            medal is earned.\n            Localization Tokens: Event Name - {0.String}, Medal Awarded - \n            {1.String}\n            ', tunable=ui.screen_slam.TunableScreenSlamSnippet()), 'screen_slam_bronze': OptionalTunable(description='\n            Screen slam to show when this situation is completed and a\n            bronze medal is earned.\n            Localization Tokens: Event Name - {0.String}, Medal Awarded - \n            {1.String}\n            ', tunable=ui.screen_slam.TunableScreenSlamSnippet()), 'screen_slam_silver': OptionalTunable(description='\n            Screen slam to show when this situation is completed and a\n            silver medal is earned.\n            Localization Tokens: Event Name - {0.String}, Medal Awarded - \n            {1.String}\n            ', tunable=ui.screen_slam.TunableScreenSlamSnippet()), 'screen_slam_gold': OptionalTunable(description='\n            Screen slam to show when this situation is completed and a\n            bronze medal is earned.\n            Localization Tokens: Event Name - {0.String}, Medal Awarded - \n            {1.String}\n            ', tunable=ui.screen_slam.TunableScreenSlamSnippet())}
    NON_USER_FACING_REMOVE_INSTANCE_TUNABLES = ('_buff', '_cost', '_NPC_host_filter', '_NPC_hosted_player_tests', 'NPC_hosted_situation_start_message', 'NPC_hosted_situation_use_player_sim_as_filter_requester', 'NPC_hosted_situation_player_job', 'venue_types', 'venue_invitation_message', 'venue_situation_player_job', 'category', 'main_goal', 'minor_goal_chains', 'max_participants', '_initiating_sim_tests', '_icon', 'targeted_situation', '_resident_job', 'situation_description', 'job_display_ordering', 'entitlement', '_jobs_to_put_in_party', '_relationship_between_job_members', 'main_goal_audio_sting', 'audio_sting_on_start', '_level_data', '_display_name', 'screen_slam_gold', 'screen_slam_silver', 'screen_slam_bronze', 'screen_slam_no_medal', 'force_invite_only')
    situation_level_data = None
    SituationLevel = collections.namedtuple('SituationLevel', ['min_score_threshold', 'level_data'])

    @classmethod
    def _tuning_loaded_callback(cls):
        cls.situation_level_data = []
        current_score = cls._level_data.tin.score_delta
        cls.situation_level_data.append(Situation.SituationLevel(current_score, cls._level_data.tin))
        current_score += cls._level_data.bronze.score_delta
        cls.situation_level_data.append(Situation.SituationLevel(current_score, cls._level_data.bronze))
        current_score += cls._level_data.silver.score_delta
        cls.situation_level_data.append(Situation.SituationLevel(current_score, cls._level_data.silver))
        current_score += cls._level_data.gold.score_delta
        cls.situation_level_data.append(Situation.SituationLevel(current_score, cls._level_data.gold))

    @classmethod
    def _verify_tuning_callback(cls):
        if cls._resident_job is not None and cls._resident_job.filter is None:
            logger.error('Resident Job: {} has no filter,', cls._resident_job, owner='manus')
        if cls.targeted_situation is not None and (cls.targeted_situation.target_job is None or cls.targeted_situation.actor_job is None):
            logger.error('target_job and actor_job are required if targeted_situation is enabled.', owner='manus')
        tuned_jobs = frozenset(cls.get_tuned_jobs())
        for job_relationships in cls.relationship_between_job_members:
            if job_relationships.job_x not in tuned_jobs:
                logger.error('job_x: {} has relationship tuning but is not functionally used in situation {}.', job_relationships.job_x, cls, owner='manus')
            if job_relationships.job_y not in tuned_jobs:
                logger.error('job_y: {} has relationship tuning but is not functionally used in situation {}.', job_relationships.job_y, cls, owner='manus')
            if len(job_relationships.relationship_bits_to_add) == 0:
                logger.error("relationship_bits_to_add cannot be empty for situation {}'s job pairs {} and {}.", cls, job_relationships.job_x, job_relationships.job_y, owner='manus')
            else:
                for bit in job_relationships.relationship_bits_to_add:
                    while bit is None:
                        logger.error("relationship_bits_to_add cannot contain empty bit for situation {}'s job pairs {} and {}.", cls, job_relationships.job_x, job_relationships.job_y, owner='manus')
        if len(cls.jobs_to_put_in_party) > 0:
            defaulters = (tuned_jobs | cls.jobs_to_put_in_party) - tuned_jobs
            if len(defaulters) > 0:
                logger.error('Jobs: {} are tuned in jobs_to_put_in_party tuning but not functionally used in situation {}.', defaulters, cls, owner='manus')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._duration_alarm_handle = None
        self._goal_tracker = None

    @classmethod
    def level_data_gen(cls):
        for level in cls.situation_level_data:
            yield level

    @classmethod
    def get_level_data(cls, medal:SituationMedal=SituationMedal.TIN):
        if cls.situation_level_data == None:
            return
        return cls.situation_level_data[medal].level_data

    @classmethod
    def get_level_min_threshold(cls, medal:SituationMedal=SituationMedal.TIN):
        if cls.situation_level_data == None:
            return
        return cls.situation_level_data[medal].min_score_threshold

    @classmethod
    def default_job(cls):
        return cls._default_job

    @classmethod
    def resident_job(cls):
        return cls._resident_job

    @classmethod
    def get_prepopulated_job_for_sims(cls, sim, target_sim_id=None):
        if target_sim_id and cls.targeted_situation is not None:
            sim_info = services.sim_info_manager().get(target_sim_id)
            if sim_info is None:
                return
            prepopulated = [(sim.id, cls.targeted_situation.actor_job.guid64), (target_sim_id, cls.targeted_situation.target_job.guid64)]
            return prepopulated

    def _display_role_objects_notification(self, sim, bullets):
        text = self.recommended_job_object_text(bullets)
        notification = self.recommended_job_object_notification(sim, text=lambda *_, **__: text)
        notification.show_dialog()

    @property
    def pie_menu_icon(self):
        return self._pie_menu_icon

    @property
    def display_name(self):
        return self._display_name

    @property
    def description(self):
        return self.situation_description

    @property
    def icon(self):
        return self._icon

    @property
    def start_audio_sting(self):
        return self.audio_sting_on_start

    @property
    def end_audio_sting(self):
        current_level = self.get_level(self._score)
        level_data = self.get_level_data(current_level)
        if level_data is not None and level_data.audio_sting_on_end is not None:
            return level_data.audio_sting_on_end
        return

    @classproperty
    def relationship_between_job_members(cls):
        return cls._relationship_between_job_members

    @classproperty
    def jobs_to_put_in_party(cls):
        return cls._jobs_to_put_in_party

    @classproperty
    def implies_greeted_status(cls):
        return cls._implies_greeted_status

    @classmethod
    def cost(cls):
        return cls._cost

    def _get_duration(self):
        if self._seed.duration_override is not None:
            return self._seed.duration_override
        return self.duration

    def _get_remaining_time(self):
        if self._duration_alarm_handle is None:
            return
        return self._duration_alarm_handle.get_remaining_time()

    def _get_remaining_time_in_minutes(self):
        time_span = self._get_remaining_time()
        if time_span is None:
            return 0
        return time_span.in_minutes()

    def _get_goal_tracker(self):
        return self._goal_tracker

    def _save_custom(self, seed):
        super()._save_custom(seed)
        if self._goal_tracker is not None:
            self._goal_tracker.save_to_seed(seed)

    def start_situation(self):
        super().start_situation()
        self._set_duration_alarm()
        if self.is_user_facing and self.scoring_enabled:
            self._goal_tracker = situations.situation_goal_tracker.SituationGoalTracker(self)

    def _load_situation_states_and_phases(self):
        super()._load_situation_states_and_phases()
        self._set_duration_alarm()
        if self._seed.goal_tracker_seedling:
            self._goal_tracker = situations.situation_goal_tracker.SituationGoalTracker(self)

    def _set_duration_alarm(self, duration_override=None):
        if duration_override is not None:
            duration = duration_override
        else:
            duration = self._get_duration()
        self.set_end_time(duration)
        if duration > 0:
            if self._duration_alarm_handle is not None:
                alarms.cancel_alarm(self._duration_alarm_handle)
            self._duration_alarm_handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(duration), self._situation_timed_out)

    def _destroy(self):
        if self._duration_alarm_handle is not None:
            alarms.cancel_alarm(self._duration_alarm_handle)
        if self._goal_tracker is not None:
            self._goal_tracker.destroy()
            self._goal_tracker = None
        super()._destroy()

    def _situation_timed_out(self, _):
        logger.debug('Situation time expired: {}', self)
        self._self_destruct()

    @classmethod
    def get_tuned_jobs(cls):
        pass

    @classmethod
    def is_situation_available(cls, initiating_sim, target_sim_id=0):
        is_targeted = cls.targeted_situation is not None and cls.targeted_situation.target_job is not None
        if is_targeted and target_sim_id:
            if not cls.targeted_situation.target_job.can_sim_be_given_job(target_sim_id, initiating_sim.sim_info):
                return TestResult(False)
        elif target_sim_id == 0 != is_targeted == False:
            return TestResult(False)
        single_sim_resolver = event_testing.resolver.SingleSimResolver(initiating_sim.sim_info)
        return cls._initiating_sim_tests.run_tests(single_sim_resolver)

    @classmethod
    def get_npc_hosted_sims(cls):
        possible_pairs = []
        client = services.client_manager().get_first_client()
        if client is None:
            return
        client_household = client.household
        if client_household is None:
            return
        blacklist_sim_ids = {sim.id for sim in services.sim_info_manager().instanced_sims_gen()}
        for sim_info in client_household.sim_info_gen():
            blacklist_sim_ids.add(sim_info.id)
        for sim in client_household.instanced_sims_gen():
            single_sim_resolver = event_testing.resolver.SingleSimResolver(sim.sim_info)
            if not cls._NPC_hosted_player_tests.run_tests(single_sim_resolver):
                pass
            results = services.sim_filter_service().submit_filter(cls._NPC_host_filter, None, requesting_sim_info=sim.sim_info, allow_yielding=False, blacklist_sim_ids=blacklist_sim_ids)
            if not results:
                pass
            chosen_NPC_id = sims4.random.weighted_random_item([(result.score, result.sim_info.id) for result in results])
            possible_pairs.append((sim, chosen_NPC_id))
        if not possible_pairs:
            return
        return random.choice(possible_pairs)

    @classmethod
    def get_predefined_guest_list(cls):
        pass

    @classmethod
    def get_venue_location(cls):
        (zone_id, _) = services.current_zone().venue_service.get_zone_and_venue_type_for_venue_types(cls.venue_types)
        return zone_id

    @classmethod
    def has_venue_location(cls):
        return services.current_zone().venue_service.has_zone_for_venue_type(cls.venue_types)

    def get_situation_affordance_target(self, target_type):
        pass

