import collections
import random
from filters.tunable import TunableSimFilter
from interactions import ParticipantType
from interactions.utils.loot import WeightedSingleSimLootActions, LootActions
from interactions.utils.tunable import SetGoodbyeNotificationElement
from rewards.reward_tuning import Reward
from sims.sim_outfits import OutfitChangeReason, DefaultOutfitPriority
from sims4.localization import TunableLocalizedString
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableInterval, TunableList, TunableResourceKey, TunableReference, Tunable, TunableMapping, TunableSet, TunableEnumEntry, TunableTuple, HasDependentTunableReference, OptionalTunable, TunableSimMinute, AutoFactoryInit, HasTunableSingletonFactory, TunableRange, TunableEnumWithFilter, TunableVariant
from sims4.tuning.tunable_base import ExportModes, GroupNames, FilterTag
from singletons import DEFAULT
from situations.situation_types import SituationMedal
from situations.tunable import TunableVenueObject
from statistics.statistic_ops import TunableStatisticChange
from tag import Tag
from ui.ui_dialog_notification import TunableUiDialogNotificationSnippet
from world.spawn_actions import TunableSpawnActionVariant
from world.spawn_point import SpawnPointOption
import enum
import event_testing.test_variants
import event_testing.tests
import event_testing.tests_with_data
import interactions.base.super_interaction
import services
import sims4.log
import sims4.resources
import situations.situation_types
logger = sims4.log.Logger('Situations')
AutoPopulateInterval = collections.namedtuple('AutoPopulateInterval', ['min', 'max'])

class JobChurnOperation(enum.Int, export=False):
    __qualname__ = 'JobChurnOperation'
    DO_NOTHING = 0
    ADD_SIM = 1
    REMOVE_SIM = 2

class SituationJobChurn(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'SituationJobChurn'
    FACTORY_TUNABLES = {'min_duration': TunableSimMinute(description='\n                Minimum amount of time a sim in this job will stay before they\n                might be churned out.\n                ', default=60), 'auto_populate_by_time_of_day': TunableMapping(description="\n                Each entry in the map has two columns.\n                The first column is the hour of the day (0-24) \n                that this entry begins to control the number of sims in the job.\n                The second column is the minimum and maximum desired number\n                of sims.\n                The entry with starting hour that is closest to, but before\n                the current hour will be chosen.\n                \n                Given this tuning: \n                    beginning_hour        desired_population\n                    6                     1-3\n                    10                    3-5\n                    14                    5-7\n                    20                    7-9\n                    \n                if the hour is 11, beginning_hour will be 10 and desired is 3-5.\n                if the hour is 19, beginning_hour will be 14 and desired is 5-7.\n                if the hour is 23, beginning_hour will be 20 and desired is 7-9.\n                if the hour is 2, beginning_hour will be 20 and desired is 7-9. (uses 20 tuning because it is not 6 yet)\n                \n                The entries will be automatically sorted by time on load, so you\n                don't have to put them in order (but that would be nutty)\n                ", key_type=Tunable(tunable_type=int, default=0), value_type=TunableInterval(tunable_type=int, default_lower=0, default_upper=0), key_name='beginning_hour', value_name='desired_population'), 'chance_to_add_or_remove_sim': TunableRange(description='\n                Periodically the churn system will re-evaluate the number of sims\n                currently in the job. If the number of sims is above or below\n                the range it will add/remove one sim as appropriate. \n                If the number of sims is within the tuned\n                range it will roll the dice to determine what it should do:\n                    nothing\n                    add a sim\n                    remove a sim\n                    \n                The chance tuned here (1-100) is the chance that it will do\n                something (add/remove), as opposed to nothing. \n                \n                When it is going to do something, the determination of \n                whether to add or remove is roughly 50/50 with additional\n                checks to stay within the range of desired sims and respect the\n                min duration.\n                ', tunable_type=int, default=20, minimum=0, maximum=100)}

    def get_auto_populate_interval(self, time_of_day=None):
        if not self.auto_populate_by_time_of_day:
            return AutoPopulateInterval(min=0, max=0)
        if time_of_day is None:
            time_of_day = services.time_service().sim_now
        auto_populate = []
        for (beginning_hour, interval) in self.auto_populate_by_time_of_day.items():
            auto_populate.append((beginning_hour, interval))
        auto_populate.sort(key=lambda entry: entry[0])
        hour_of_day = time_of_day.hour()
        entry = auto_populate[-1]
        interval = AutoPopulateInterval(min=entry[1].lower_bound, max=entry[1].upper_bound)
        for entry in auto_populate:
            if entry[0] <= hour_of_day:
                interval = AutoPopulateInterval(min=entry[1].lower_bound, max=entry[1].upper_bound)
            else:
                break
        return interval

class SituationJobShifts(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'SituationJobShifts'
    FACTORY_TUNABLES = {'shift_times_and_staffing': TunableMapping(description='\n                Each entry in the map has two columns.\n                The first column is the hour of the day (0-24) \n                that this shift starts.\n                The second column is the number of sims in that shift.\n                The entry with starting hour that is closest to, but before\n                the current hour will be chosen.\n                \n                Given this tuning: \n                    beginning_hour        staffing\n                    2                     0\n                    6                     1\n                    14                    2\n                    20                    2\n                    \n                2am is a shift change that sends everybody home\n                6am is a shift change that brings in 1 employee\n                2pm is a shift change that sends the current employee home and brings in 2 new ones.\n                8pm is a shift change that sends the 2 employees home and brings in 2 new ones. \n                \n                The entries will be automatically sorted by time at runtime.\n                ', key_type=Tunable(tunable_type=int, default=0), value_type=Tunable(tunable_type=int, default=0), key_name='beginning_hour', value_name='staffing')}

    def get_sorted_shift_times(self):
        staffing = []
        for (beginning_hour, number) in self.shift_times_and_staffing.items():
            staffing.append((beginning_hour, number))
        staffing.sort(key=lambda entry: entry[0])
        return staffing

    def get_shift_staffing(self, time_of_day=None):
        if not self.shift_times_and_staffing:
            return 0
        if time_of_day is None:
            time_of_day = services.time_service().sim_now
        staffing_times = self.get_sorted_shift_times()
        hour_of_day = time_of_day.hour()
        entry = staffing_times[-1]
        number_of_sims = entry[1]
        for entry in staffing_times:
            if entry[0] <= hour_of_day:
                number_of_sims = entry[1]
            else:
                break
        return number_of_sims

    def get_time_span_to_next_shift_time(self):
        if not self.shift_times_and_staffing:
            return
        sorted_times = self.get_sorted_shift_times()
        next_shift_hour = sorted_times[0][0]
        now_hour = services.time_service().sim_now.hour()
        for (shift_hour, _) in sorted_times:
            while shift_hour > now_hour:
                next_shift_hour = shift_hour
                break
        time_span_until = services.game_clock_service().precise_time_until_hour_of_day(next_shift_hour)
        return time_span_until

class SituationJobReward(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'SituationJobReward'
    FACTORY_TUNABLES = {'reward': Reward.TunableReference(), 'loot': LootActions.TunableReference()}

    def apply(self, sim):
        if self.loot is not None:
            self.loot.apply_to_resolver(sim.get_resolver())
        if self.reward is not None:
            self.reward.give_reward(sim.sim_info)

class SituationJob(HasDependentTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.situation_job_manager()):
    __qualname__ = 'SituationJob'
    CHANGE_OUTFIT_INTERACTION = interactions.base.super_interaction.SuperInteraction.TunableReference(description='\n        A reference that should be tuned to an interaction that will just set\n        sim to their default outfit.\n        ')
    INSTANCE_TUNABLES = {'display_name': TunableLocalizedString(description='\n                Localized name of this job. This name is displayed in the situation\n                creation UI where the player is making selection of sims that belong\n                to a specific job. E.g. "Guest", "Bride or Groom", "Bartender".\n                \n                Whenever you add a display name, evaluate whether your design \n                needs or calls out for a tooltip_name.\n                ', tuning_group=GroupNames.UI), 'tooltip_name': TunableLocalizedString(description='\n                Localized name of this job that is displayed when the player hovers\n                on the sim while the situation is in progress. If this field is absent, \n                there will be no tooltip on the sim.\n                \n                This helps distinguish the cases where we want to display "Bride or Groom" \n                in the situation creation UI but only "Bride" or "Groom" on the \n                sim\'s tooltip when the player is playing with the situation. \n                ', tuning_group=GroupNames.UI), 'icon': TunableResourceKey(description='\n                Icon to be displayed for the job of the Sim\n                ', default=None, needs_tuning=True, resource_types=sims4.resources.CompoundTypes.IMAGE, tuning_group=GroupNames.UI), 'job_description': TunableLocalizedString(description='\n                Localized description of this job\n                ', tuning_group=GroupNames.UI), 'tests': event_testing.tests.TunableTestSet(), 'sim_auto_invite': TunableInterval(description="\n                On situation start it will select a random number of sims in this interval.\n                It will automatically add npcs to the situation so that it has at least\n                that many sims in this job including those the player\n                invites/hires. If the player invites/hires more than the auto\n                invite number, no npcs will be automatically added.\n                \n                Auto invite sims are considered to be invited, so they will be\n                spawned for invite only situations too. For player initiated\n                situations you probably want to set this 0. It is really meant\n                for commercial venues.\n                \n                You can use Churn tuning on this job if you want the number of\n                sims to vary over time. Churn tuning will override this one.\n                \n                For example, an ambient bar situation would have a high auto\n                invite number for the customer job because we want many sims in\n                the bar but the player doesn't invite or hire anybody for an\n                ambient situation.\n                \n                A date would have 0 for this for all jobs because the situation\n                would never spawn anybody to fill jobs, the player would have\n                to invite them all.\n                ", tunable_type=int, default_lower=0, default_upper=0, minimum=0), 'sim_auto_invite_allow_instanced_sim': Tunable(description='\n                If checked will allow instanced sims to be assigned this job\n                to fulfill auto invite spots instead of forcing the spawning\n                of new sims.\n                \n                NOTE: YOU PROBABLY WANT TO LEAVE THIS AS UNCHECKED.  PLEASE\n                CONSULT A GPE IF YOU PLAN ON TUNING IT.\n                ', tunable_type=bool, default=False), 'sim_count': TunableInterval(description='\n                The number of Sims the player is allowed to invite or hire for\n                this job.  The lower bound is the required number of sims, the\n                upper bound is the maximum.\n                \n                This only affects what the player can do in the Plan an Event UI.\n                It has no affect while the situation is running.\n                ', tunable_type=int, default_lower=1, default_upper=1, minimum=0), 'churn': OptionalTunable(description='If enabled, produces churn or turnover\n                in the sims holding this job. Periodically sims in the job will leave\n                the lot and other sims will come to fill the job. \n                \n                When a situation is first started it will automatically invite a\n                number of sims appropriate for the time of day. This supercedes\n                sim_auto_invite.\n                \n                This is primarily for commercial venue customers.\n                This is NOT compatible with Sim Shifts.\n                ', tunable=SituationJobChurn.TunableFactory(), display_name='Sim Churn'), 'sim_shifts': OptionalTunable(description='If enabled, creates shifts of\n                sims who replace the sims currently in the job.\n                \n                When a situation is first started it will automatically invite a\n                number of sims appropriate for the time of day. This supercedes\n                sim_auto_invite.\n                \n                This is primarily intended for commercial venue employees.\n                This is NOT compatible with Sim Churn.\n                ', tunable=SituationJobShifts.TunableFactory()), 'goal_scoring': Tunable(description='\n                The score for completing a goal\n                ', tunable_type=int, default=1, tuning_group=GroupNames.SCORING), 'interaction_scoring': TunableList(description='\n                Test for interactions run. Each test can have a separate score.\n                ', tunable=TunableTuple(description='\n                    Each affordance that satisfies the test will receive the\n                    same score.\n                    ', score=Tunable(description='\n                        Score for passing the test.\n                        ', tunable_type=int, default=1), affordance_list=event_testing.tests_with_data.TunableParticipantRanInteractionTest(locked_args={'participant': ParticipantType.Actor, 'tooltip': None, 'running_time': None})), tuning_group=GroupNames.SCORING), 'crafted_object_scoring': TunableList(description='\n                Test for objects crafted. Each test can have a separate score.\n                ', tunable=TunableTuple(description='\n                    Test for objects crafted. Each test can have a separate\n                    score.\n                    ', score=Tunable(description='\n                        Score for passing the test.\n                        ', tunable_type=int, default=1), object_list=event_testing.test_variants.TunableCraftedItemTest(description='\n                        A test to see if the crafted item should give score.\n                        ', locked_args={'tooltip': None})), tuning_group=GroupNames.SCORING), 'rewards': TunableMapping(description='\n                Rewards given to the sim in this job when situation reaches specific medals.\n                ', key_type=TunableEnumEntry(SituationMedal, SituationMedal.TIN, description='\n                    Medal to achieve to get the corresponding benefits.\n                    '), value_type=SituationJobReward.TunableFactory(description='\n                    Reward and LootAction benefits for accomplishing the medal.\n                    '), key_name='medal', value_name='benefit', tuning_group=GroupNames.SCORING), 'filter': TunableReference(manager=services.get_instance_manager(sims4.resources.Types.SIM_FILTER), needs_tuning=True, class_restrictions=TunableSimFilter), 'tags': TunableSet(description='\n                Designer tagging for making the game more fun.\n                ', tunable=TunableEnumEntry(tunable_type=Tag, default=Tag.INVALID)), 'job_uniform': OptionalTunable(description='\n                If enabled, when a Sim is assigned this situation job, that Sim\n                will switch into their outfit based on the Outfit Category.\n                \n                If the Outfit Category is SITUATION, then an outfit will be\n                generated based on the passed in tags and the Sim will switch\n                into that outfit.\n                ', tunable=TunableTuple(description='\n                    ', outfit_change_reason=TunableEnumEntry(description='\n                        An enum that represents a reason for outfit change for\n                        the outfit system.\n                        \n                        An outfit change reason is really a series of tests\n                        that are run to determine which outfit category that\n                        we want to switch into.\n                        \n                        In order to do this, go to the tuning file\n                        sims.sim_outfits.\n                        \n                        Add a new OutfitChangeReason enum entry for your change\n                        reason.\n                        \n                        Then go into\n                        ClothingChangeTunables->Clothing Reasons To Outfits\n                        and add a new entry to the map.\n                        \n                        Set this entry to your new enum entry.\n                        \n                        Then you can add new elements to the list of tests and\n                        outfit categories that you want it to change the sim\n                        into.\n                        ', tunable_type=OutfitChangeReason, default=OutfitChangeReason.Invalid), outfit_change_priority=TunableEnumEntry(description='\n                        The outfit change priority.  Higher priority outfit\n                        changes will override lower priority outfit changes.\n                        ', tunable_type=DefaultOutfitPriority, default=DefaultOutfitPriority.NoPriority), playable_sims_change_outfits=Tunable(description='\n                        If checked, Playable Sims will change outfit when the job is set for the Sim. This\n                        should be checked on things like user facing events,\n                        but not Venue Background Event Jobs.\n                        ', tunable_type=bool, default=True), situation_outfit_generation_tags=OptionalTunable(description="\n                        If enabled, the situation will use the outfit tags\n                        specified to generate an outfit for the sim's\n                        SITUATION outfit category.  If generating an outfit\n                        make sure to set outfit change reason to something that\n                        will put the sim into the SITUATION outfit category or\n                        you will not have the results that you expect.\n                        ", tunable=TunableSet(description='\n                            Only one of these sets is picked randomly to select the\n                            outfit tags within this set.\n                            E.g. If you want to host a costume party where the guests show\n                            up in either octopus costume or a shark costume, we would have\n                            two sets of tuning that can specify exclusive tags for the \n                            specific costumes. Thus we avoid accidentally generating a \n                            sharktopus costume.\n                            \n                            If you want your guests to always show up in sharktopus costumes \n                            then tune only one set of tags that enlist all the outfit tags\n                            that are associated with either shark or octopus.\n                            ', tunable=TunableSet(description="\n                                Tags that will be used by CAS to generate an outfit\n                                within the sim's SITUATION outfit category.\n                                ", tunable=TunableEnumWithFilter(tunable_type=Tag, filter_prefixes=['uniform', 'outfitcategory'], default=Tag.INVALID))))), disabled_name='no_uniform', enabled_name='uniform_specified'), 'can_be_hired': Tunable(description='\n                This job can be hired.\n                ', tunable_type=bool, default=True), 'hire_cost': Tunable(description='\n                The cost to hire a Sim for this job in Simoleons.\n                ', tunable_type=int, default=0), 'game_breaker': Tunable(description='\n                If True then this job must be filled by a sim\n                or the game will be broken. This is for the grim reaper and\n                the social worker.\n                ', tunable_type=bool, default=False, tuning_group=GroupNames.SPECIAL_CASES, tuning_filter=FilterTag.EXPERT_MODE), 'elevated_importance': Tunable(description='\n                If True, then filling this job with a Sim will be done before\n                filling similar jobs in this situation. This will matter when\n                starting a situation on another lot, when inviting a large number\n                of Sims, visiting commercial venues, or when at the cap on NPCs.\n                \n                Examples:\n                Wedding Situation: the Bethrothed Sims should be spawned before any guests.\n                Birthday Party: the Sims whose birthday it is should be spawned first.\n                Bar Venue: the Bartender should be spawned before the barflies.\n                \n                ', tunable_type=bool, default=False, tuning_group=GroupNames.SPECIAL_CASES, tuning_filter=FilterTag.EXPERT_MODE), 'no_show_action': TunableEnumEntry(situations.situation_types.JobHolderNoShowAction, default=situations.situation_types.JobHolderNoShowAction.DO_NOTHING, description="\n                                The action to take if no sim shows up to fill this job.\n                                \n                                Examples: \n                                If your usual maid doesn't show up, you want another one (REPLACE_THEM).\n                                If one of your party guests doesn't show up, you don't care (DO_NOTHING)\n                                If the President of the United States doesn't show up for the inauguration, you are hosed (END_SITUATION)\n                                ", tuning_group=GroupNames.SPECIAL_CASES), 'died_or_left_action': TunableEnumEntry(situations.situation_types.JobHolderDiedOrLeftAction, default=situations.situation_types.JobHolderDiedOrLeftAction.DO_NOTHING, description="\n                                    The action to take if a sim in this job dies or leaves the lot.\n                                    \n                                    Examples: \n                                    If the bartender leaves the ambient bar situation, you need a new one (REPLACE_THEM)\n                                    If your creepy uncle leaves the wedding, you don't care (DO_NOTHING)\n                                    If your maid dies cleaning the iron maiden, you are out of luck for today (END_SITUATION).\n                                    \n                                    NB: Do not use REPLACE_THEM if you are using Sim Churn for this job.\n                                    ", tuning_group=GroupNames.SPECIAL_CASES), 'sim_spawner_tags': TunableList(description='\n            A list of tags that represent where to spawn Sims for this Job when they come onto the lot.\n            NOTE: Tags will be searched in order of tuning. Tag [0] has priority over Tag [1] and so on.\n            ', tunable=TunableEnumEntry(tunable_type=Tag, default=Tag.INVALID)), 'sim_spawn_action': TunableSpawnActionVariant(description='\n            Define the methods to show the Sim after spawning on the lot.\n            '), 'sim_spawner_leave_option': TunableEnumEntry(description='\n            The method for selecting spawn points for sims that are\n            leaving the lot. \n            \n            TUNED CONSTRAINT TAGS come from the SpawnPointConstraint.\n            SAVED TAGS are the same tags that were used to spawn the sim. \n            SAME vs DIFFERENT vs ANY resolves how to use the spawn point\n            that was saved when the sim entered the lot.\n            ', tunable_type=SpawnPointOption, default=SpawnPointOption.SPAWN_SAME_POINT), 'emotional_setup': TunableList(description='\n                Apply the WeightedSingleSimLootActions on the sim that is assigned this job. These are applied\n                only on NPC sims since the tuning is forcing changes to emotions.\n                \n                E.g. an angry mob at the bar, flirty guests at a wedding party.\n                ', tunable=TunableTuple(single_sim_loot_actions=WeightedSingleSimLootActions.TunableReference(), weight=Tunable(int, 1, description='Accompanying weight of the loot.')), tuning_group=GroupNames.ON_CREATION), 'commodities': TunableList(description='\n                Update the commodities on the sim that is assigned this job. These are applied only on\n                NPC sims since the tuning is forcing changes to statistics that have player facing effects.\n             \n                E.g. The students arrive at the lecture hall with the bored and sleepy commodities.\n                ', tunable=TunableStatisticChange(locked_args={'subject': ParticipantType.Actor, 'advertise': False, 'chance': 1, 'tests': None}), tuning_group=GroupNames.ON_CREATION), 'requirement_text': TunableLocalizedString(description='\n                A string that will be displayed in the sim picker for this\n                job in the situation window.\n                '), 'goodbye_notification': TunableVariant(description='\n                The "goodbye" notification that will be set on Sims with this\n                situation job. This notification will be displayed when the\n                Sim leaves the lot (unless it gets overridden later).\n                Examples: the visitor job sets the "goodbye" notification to\n                something so the player knows when visitors leave; the party\n                guest roles use "No Notification", because we don\'t want 20-odd\n                notifications when a party ends; the leave lot jobs use "Use\n                Previous Notification" because we want leaving Sims to display\n                whatever notification was set earlier.\n                ', notification=TunableUiDialogNotificationSnippet(), locked_args={'no_notification': None, 'never_use_notification_no_matter_what': SetGoodbyeNotificationElement.NEVER_USE_NOTIFICATION_NO_MATTER_WHAT, 'use_previous_notification': DEFAULT}, default='no_notification'), 'additional_filter_for_user_selection': TunableReference(description='\n                An additional filter that will run for the situation job if\n                there should be specific additional requirements for selecting\n                specific sims for the role rather than hiring them.\n                ', manager=services.get_instance_manager(sims4.resources.Types.SIM_FILTER), needs_tuning=True), 'recommended_objects': TunableList(description='\n                A list of objects that are recommended to be on a lot to get\n                the most out of this job\n                ', tunable=TunableVenueObject(description="\n                        Specify object tag(s) that should be on this lot.\n                        Allows you to group objects, i.e. weight bench,\n                        treadmill, and basketball goals are tagged as\n                        'exercise objects.'\n                        "), export_modes=ExportModes.All)}

    @classmethod
    def _verify_tuning_callback(cls):
        messages = []
        if cls.died_or_left_action == situations.situation_types.JobHolderDiedOrLeftAction.REPLACE_THEM:
            messages.append('Died Or Left Action == REPLACE_THEM')
        if cls.churn is not None:
            messages.append('Sim Churn')
        if cls.sim_shifts is not None:
            messages.append('Sim Shifts')
        if len(messages) > 1:
            message = ', and '.join(messages)
            logger.error('Situation job :{} must use only one of {}', cls, message)

    @classmethod
    def get_score(cls, event, resolver, **kwargs):
        if event == event_testing.test_variants.TestEvent.InteractionComplete:
            for score_list in cls.interaction_scoring:
                while resolver(score_list.affordance_list):
                    return score_list.score
        elif event == event_testing.test_variants.TestEvent.ItemCrafted:
            for score_list in cls.crafted_object_scoring:
                while resolver(score_list.object_list):
                    return score_list.score
        return 0

    @classmethod
    def get_goal_score(cls):
        return cls.goal_scoring

    @classmethod
    def get_auto_invite(cls):
        if cls.churn is not None:
            interval = cls.churn.get_auto_populate_interval()
        else:
            if cls.sim_shifts is not None:
                return cls.sim_shifts.get_shift_staffing()
            if cls.sim_auto_invite.upper_bound > 0:
                interval = AutoPopulateInterval(min=cls.sim_auto_invite.lower_bound, max=cls.sim_auto_invite.upper_bound)
            else:
                return 0
        auto_invite = random.randrange(interval.min, interval.max + 1)
        return auto_invite

    @classmethod
    def can_sim_be_given_job(cls, sim_id, requesting_sim_info):
        if cls.filter is None:
            return True
        household_id = 0
        if requesting_sim_info is not None:
            household_id = requesting_sim_info.household.id
        return services.sim_filter_service().does_sim_match_filter(sim_id, sim_filter=cls.filter, requesting_sim_info=requesting_sim_info, household_id=household_id)

