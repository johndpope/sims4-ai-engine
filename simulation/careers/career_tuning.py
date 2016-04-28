import random
import protocolbuffers
from audio.primitive import TunablePlayAudio
from away_actions.away_actions import AwayAction
from buffs.tunable import TunableBuffReference
from careers import career_ops
from event_testing.resolver import SingleSimResolver
from distributor.ops import GenericProtocolBufferOp
from distributor.system import Distributor
from interactions import ParticipantType
from interactions.utils.loot import LootActions
from interactions.utils.tested_variant import TunableTestedVariant
from protocolbuffers.DistributorOps_pb2 import Operation
from sims4.localization import TunableLocalizedStringFactory, TunableLocalizedString
from sims4.tuning.geometric import TunableCurve
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableTuple, TunableEnumFlags, OptionalTunable, Tunable, TunableThreshold, TunableList, TunableReference
from sims4.tuning.tunable_base import GroupNames
from singletons import DEFAULT
from tunable_multiplier import TunableMultiplier, TestedSum
from ui.ui_dialog import UiDialogResponse, UiDialogOkCancel, UiDialogOk
from ui.ui_dialog_notification import UiDialogNotification
import careers.career_base
import distributor.shared_messages
import enum
import event_testing.resolver
import event_testing.tests
import interactions.utils.interaction_elements
import scheduler
import services
import sims4.localization
import sims4.tuning.tunable
import tag
import tunable_time
import ui.screen_slam
logger = sims4.log.Logger('CareerTuning', default_owner='tingyul')

def _get_career_notification_tunable_factory(**kwargs):
    return UiDialogNotification.TunableFactory(locked_args={'text_tokens': DEFAULT, 'icon': None, 'primary_icon_response': UiDialogResponse(text=None, ui_request=UiDialogResponse.UiDialogUiRequest.SHOW_CAREER_PANEL), 'secondary_icon': None}, **kwargs)

class CareerCategory(enum.Int):
    __qualname__ = 'CareerCategory'
    Invalid = 0
    Work = 1
    School = 2
    TeenPartTime = 3

class CareerToneTuning(TunableTuple):
    __qualname__ = 'CareerToneTuning'

    def __init__(self, **kwargs):
        super().__init__(default_action=AwayAction.TunableReference(description='\n                Default away action tone.\n                '), optional_actions=TunableList(description='\n                Additional selectable away action tones.\n                ', tunable=AwayAction.TunableReference()), leave_work_early=TunableReference(description='\n                Sim Info interaction to end work early.\n                ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION), class_restrictions='CareerLeaveWorkEarlyInteraction'), **kwargs)

class Career(careers.career_base.CareerBase, metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.CAREER)):
    __qualname__ = 'Career'
    NUM_CAREERS_PER_DAY = sims4.tuning.tunable.Tunable(int, 2, description='\n                                 The number of careers that are randomly selected\n                                 each day to populate career selection for the\n                                 computer and phone.\n                                 ')
    JOB_START_DELAY = sims4.tuning.tunable.TunableSimMinute(description='\n        Right after a Sim joins a career, their first day will not be until\n        this many Sim hours later.\n        ', default=480.0, minimum=0.0)
    CAREER_TONE_INTERACTION = TunableReference(description='\n        The interaction that applies the tone away action.\n        ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION))
    FIND_JOB_PHONE_INTERACTION = sims4.tuning.tunable.TunableReference(description="\n        Find job phone interaction. This will be pushed on a Sim when player\n        presses the Look For Job button on the Sim's career panel.\n        ", manager=services.affordance_manager())
    QUIT_CAREER_DIALOG = UiDialogOkCancel.TunableFactory(description='\n         This dialog asks the player to confirm that they want to quit.\n         ')
    SWITCH_JOBS_DIALOG = UiDialogOkCancel.TunableFactory(description='\n         If a Sim already has a career and is joining a new one, this dialog\n         asks the player to confirm that they want to quit the existing career.\n         \n         Params passed to Text:\n         {0.SimFirstName} and the like - Sim switching jobs\n         {1.String} - Job title of existing career\n         {2.String} - Career name of existing career\n         {3.String} - Company name of existing career\n         {4.String} - Career name of new career\n         ')
    UNRETIRE_DIALOG = UiDialogOkCancel.TunableFactory(description='\n         If a Sim is retired and is joining a career, this dialog asks the\n         player to confirm that they want to unretire and lose any retirement\n         benefits.\n         \n         Params passed to Text:\n         {0.SimFirstName} and the like - Sim switching jobs\n         {1.String} - Job title of retired career\n         {2.String} - Career name of retired career\n         {3.String} - Career name of new career\n         ')
    CAREER_PERFORMANCE_UPDATE_INTERVAL = sims4.tuning.tunable.TunableSimMinute(description="\n        In Sim minutes, how often during a work session the Sim's work\n        performance is updated.\n        ", default=30.0, minimum=0.0)
    WORK_SESSION_PERFORMANCE_CHANGE = TunableReference(description="\n        Used to track a sim's work performance change over a work session.\n        ", manager=services.get_instance_manager(sims4.resources.Types.STATISTIC))
    INSTANCE_TUNABLES = {'career_category': sims4.tuning.tunable.TunableEnumEntry(CareerCategory, CareerCategory.Invalid, description='Category for career, this will beused for aspirations and other systems whichshould trigger for careers categories but not for others', export_modes=sims4.tuning.tunable_base.ExportModes.All), 'company_names': sims4.tuning.tunable.TunableList(sims4.localization.TunableLocalizedString(description='An individual company name'), description='A list of company names that will be randomly selected from when a Sim chooses this career.', tuning_group=GroupNames.UI), 'start_track': sims4.tuning.tunable.TunableReference(description='\n                          This is the career track that a Sim would start when joining\n                          this career for the first time. Career Tracks contain a series of\n                          levels you need to progress through to finish it. Career tracks can branch at the end\n                          of a track, to multiple different tracks which is tuned within\n                          the career track tuning.\n                          ', manager=services.get_instance_manager(sims4.resources.Types.CAREER_TRACK), export_modes=sims4.tuning.tunable_base.ExportModes.All), 'career_affordance': sims4.tuning.tunable.TunableReference(services.affordance_manager(), description='SI to push to go to work.'), 'go_home_to_work_affordance': TunableReference(description='\n            Interaction pushed onto a Sim to go home and start work from there\n            if they are not on their home lot.\n            ', manager=services.affordance_manager()), 'levels_lost_on_leave': sims4.tuning.tunable.Tunable(int, 1, description='When you leave this career for any reason you will immediately lose this many levels, for rejoining the career. i.e. if you quit your job at level 8, and then rejoined with this value set to 1, you would rejoin the career at level 7.'), 'days_to_level_loss': sims4.tuning.tunable.Tunable(int, 1, description='When you leave a career, we store off the level youwould rejoin the career at. Every days_to_level_loss days you will lose another level. i.e. I quit my job at level 8. I get reducedlevel 7 right away because of levels_lost_on_leave. Then with days_to_level_loss set to 3, in 3 days I would goto level 6, in 6 days level 5, etc...'), 'start_level_modifiers': TestedSum.TunableFactory(description='\n            A tunable list of test sets and associated values to apply to the\n            starting level of this Sim.\n            '), 'promotion_buff': OptionalTunable(description='\n            The buff to trigger when this Sim is promoted in this career.', tunable=TunableBuffReference()), 'demotion_buff': OptionalTunable(description='\n            The buff to trigger when this Sim is demoted in this career.', tunable=TunableBuffReference()), 'fired_buff': OptionalTunable(description='\n            The buff to trigger when this Sim is fired from this career.', tunable=TunableBuffReference()), 'early_promotion_modifiers': TunableMultiplier.TunableFactory(description='\n            A tunable list of test sets and associated multipliers to apply to \n            the moment of promotion. A resulting modifier multiplier of 0.10 means that promotion \n            could happen up to 10% earlier. A value less than 0 has no effect.\n            '), 'early_promotion_chance': TunableMultiplier.TunableFactory(description='\n            A tunable list of test sets and associated multipliers to apply to the percentage chance, \n            should the early promotion modifier deem that early promotion is possible,\n            that a Sim is in fact given a promotion. A resolved value of 0.10 will result in a 10%\n            chance.\n            '), 'demotion_chance_modifiers': TunableMultiplier.TunableFactory(description="\n            A tunable list of test sets and associated multipliers to apply to \n            the moment of a Sim's demotion, to provide the chance that Sim will get demoted. A resultant\n            modifier value of 0.50 means at the point of work end where performance would require demotion,\n            the Sim would have a 50% chance of being demoted. Any resultant value over 1 will result in demotion.\n            "), 'career_messages': TunableTuple(join_career_notification=_get_career_notification_tunable_factory(description='\n                Message when a Sim joins a new career.\n                '), quit_career_notification=_get_career_notification_tunable_factory(description='\n                Message when a Sim quits a career.\n                '), fire_career_notification=_get_career_notification_tunable_factory(description='\n                Message when a Sim is fired from a career.\n                '), promote_career_notification=_get_career_notification_tunable_factory(description='\n                Message when a Sim is promoted in their career.\n                '), promote_career_rewardless_notification=_get_career_notification_tunable_factory(description="\n                Message when a Sim is promoted in their career and there are no\n                promotion rewards, either because there are none tuned or Sim\n                was demoted from this level in the past and so shouldn't get\n                rewards again.\n                "), demote_career_notification=_get_career_notification_tunable_factory(description='\n                Message when a Sim is demoted in their career.\n                '), career_daily_start_notification=_get_career_notification_tunable_factory(description='\n                Message on notification when sim starts his work day\n                '), career_daily_end_notification=TunableTestedVariant(description='\n                Message on notification when sim ends his work day\n                ', tunable_type=_get_career_notification_tunable_factory()), career_situation_start_notification=_get_career_notification_tunable_factory(description='\n                Message when a Sim has a career situation become available.\n                '), career_early_warning_notification=_get_career_notification_tunable_factory(description='\n                Message warning the Sim will need to leave for work soon.\n                '), career_early_warning_time=Tunable(description='\n                How many hours before a the Sim needs to go to work to show\n                the Career Early Warning Notification. If this is <= 0, the\n                notification will not be shown.\n                ', tunable_type=float, default=1), career_missing_work=TunableTuple(description='\n                Tuning for triggering the missing work flow.\n                ', dialog=UiDialogOk.TunableFactory(description='\n                    The dialog that will be triggered when the sim misses work.\n                    '), affordance=sims4.tuning.tunable.TunableReference(description='\n                    The affordance that is pushed onto the sim when the accepts\n                    the modal dialog.\n                    ', manager=services.affordance_manager())), career_performance_warning=TunableTuple(description='\n                Tuning for triggering the career performance warning flow.\n                ', dialog=UiDialogOk.TunableFactory(description='\n                    The dialog that will be triggered when when the sim falls\n                    below their performance threshold.\n                    '), threshold=TunableThreshold(description='\n                    The threshold that the performance stat value will be\n                    compared to.  If the threshold returns true then the\n                    performance warning notification will be triggered.\n                    \n                    '), affordance=sims4.tuning.tunable.TunableReference(description='\n                    The affordance that is pushed onto the sim when the accepts\n                    the modal dialog.\n                    ', manager=services.affordance_manager())), tuning_group=GroupNames.UI), 'can_be_fired': sims4.tuning.tunable.Tunable(bool, True, description='Whether or not the Sim can be fired from this career.  For example, children cannot be fired from school.'), 'can_quit': sims4.tuning.tunable.Tunable(bool, True, description='Whether or not the Sim can quit this career. Example: Teens cannot quit school.'), 'career_availablity_tests': event_testing.tests.TunableTestSet(description='\n                                       When a Sim calls to join a Career, this test set\n                                       determines if a particular career can be available to that\n                                       Sim at all.\n                                       ')}

    @classmethod
    def _verify_tuning_callback(cls):
        if cls.career_affordance is None:
            logger.error('Career: {} is missing tuning for Career Affordance', cls)
        if cls.start_track is None:
            logger.error('Career: {} is missing tuning for Start Track', cls)

    def get_random_company_name_hash(self):
        num_company_names = len(self.company_names)
        if num_company_names > 0:
            return self.company_names[random.randint(0, num_company_names - 1)].hash
        return 0

    def get_company_name_from_hash(self, hash_in):
        for name in self.company_names:
            while name.hash == hash_in:
                return name

    @classmethod
    def master_scheduler(cls):
        master_scheduler = cls.start_track.career_levels[0].work_schedule(init_only=True)
        cls.track_scheduler_merge_recurse(cls.start_track, master_scheduler)
        return master_scheduler

    @classmethod
    def track_scheduler_merge_recurse(cls, this_track, scheduler):
        scheduler.merge_schedule(this_track.levels_scheduler)
        for track in this_track.branches:
            cls.track_scheduler_merge_recurse(track, scheduler)

    @staticmethod
    def get_join_career_pb(sim_info, num_careers_to_show=0, check_for_conflicting_schedule=False):
        msg = protocolbuffers.Sims_pb2.CareerSelectionUI()
        msg.sim_id = sim_info.sim_id
        msg.is_branch_select = False
        msg.reason = career_ops.CareerOps.JOIN_CAREER
        all_possible_careers = services.get_career_service().get_shuffled_career_list()
        careers_added = 0
        resolver = event_testing.resolver.SingleSimResolver(sim_info)
        for career_tuning in all_possible_careers:
            if num_careers_to_show > 0 and careers_added >= num_careers_to_show:
                break
            test_result = career_tuning.career_availablity_tests.run_tests(resolver)
            while test_result and sim_info.career_tracker.get_career_by_uid(career_tuning.guid64) is None:
                (new_level, _, current_track) = career_tuning.get_career_entry_level(career_tuning, career_history=sim_info.career_tracker.career_history, resolver=resolver)
                if current_track is not None:
                    career_track = current_track.guid64
                elif career_tuning.start_track is not None:
                    career_track = career_tuning.start_track.guid64
                else:
                    logger.error('Career {} is unjoinable because it is missing Start Track tuning.', career_tuning)
                career_info_msg = msg.career_choices.add()
                career_info_msg.uid = career_tuning.guid64
                career_info_msg.career_track = career_track
                career_info_msg.career_level = new_level
                career_info_msg.company.hash = career_tuning.get_random_company_name_hash(career_tuning)
                career_info_msg.conflicted_schedule = sim_info.career_tracker.conflicting_with_careers(career_tuning) if check_for_conflicting_schedule else False
                careers_added += 1
        return msg

    @staticmethod
    def get_quit_career_pb(sim_info):
        msg = protocolbuffers.Sims_pb2.CareerSelectionUI()
        msg.sim_id = sim_info.sim_id
        msg.is_branch_select = False
        msg.reason = career_ops.CareerOps.QUIT_CAREER
        for career_instance in sim_info.career_tracker.careers.values():
            career_info_msg = msg.career_choices.add()
            career_info_msg.uid = career_instance.guid64
            career_info_msg.career_track = career_instance.current_track_tuning.guid64
            career_info_msg.career_level = career_instance.level
            career_info_msg.company.hash = career_instance.company_name
            career_info_msg.conflicted_schedule = False
        return msg

    @staticmethod
    def get_select_career_track_pb(sim_info, career, career_branches):
        msg = protocolbuffers.Sims_pb2.CareerSelectionUI()
        msg.sim_id = sim_info.sim_id
        msg.is_branch_select = True
        for career_track in career_branches:
            career_info_msg = msg.career_choices.add()
            career_info_msg.uid = career.guid64
            career_info_msg.career_track = career_track.guid64
            career_info_msg.career_level = 0
            career_info_msg.company.hash = career.company_name
        return msg

class TunableCareerTrack(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.CAREER_TRACK)):
    __qualname__ = 'TunableCareerTrack'
    INSTANCE_TUNABLES = {'career_name': sims4.localization.TunableLocalizedStringFactory(description='The name of this Career Track', export_modes=sims4.tuning.tunable_base.ExportModes.All, tuning_group=GroupNames.UI), 'career_description': sims4.localization.TunableLocalizedString(description='A description for this Career Track', export_modes=sims4.tuning.tunable_base.ExportModes.All, tuning_group=GroupNames.UI), 'icon': sims4.tuning.tunable.TunableResourceKey(None, resource_types=sims4.resources.CompoundTypes.IMAGE, description='Icon to be displayed for this Career Track', export_modes=sims4.tuning.tunable_base.ExportModes.All, tuning_group=GroupNames.UI), 'icon_high_res': sims4.tuning.tunable.TunableResourceKey(None, resource_types=sims4.resources.CompoundTypes.IMAGE, description='Icon to be displayed for screen slams from this career track', export_modes=sims4.tuning.tunable_base.ExportModes.All, tuning_group=GroupNames.UI), 'image': sims4.tuning.tunable.TunableResourceKey(None, resource_types=sims4.resources.CompoundTypes.IMAGE, description='Pre-rendered image to show in the branching select UI.', export_modes=sims4.tuning.tunable_base.ExportModes.All, tuning_group=GroupNames.UI), 'career_levels': sims4.tuning.tunable.TunableList(description='\n                            All of the career levels you need to be promoted through to\n                            get through this career track. When you get promoted past the\n                            end of a career track, and branches is tuned, you will get a selection\n                            UI where you get to pick the next part of your career.\n                            ', tunable=sims4.tuning.tunable.TunableReference(description='\n                                A single career track', manager=services.get_instance_manager(sims4.resources.Types.CAREER_LEVEL), reload_dependent=True), export_modes=sims4.tuning.tunable_base.ExportModes.All), 'branches': sims4.tuning.tunable.TunableList(sims4.tuning.tunable.TunableReference(description='A single career level', manager=services.get_instance_manager(sims4.resources.Types.CAREER_TRACK)), description="\n                              When you get promoted past the end of a career track, branches\n                              determine which career tracks you can progress to next. i.e.\n                              You're in the medical career and the starter track has 5 levels in\n                              it. When you get promoted to level 6, you get to choose either the\n                              surgeon track, or the organ seller track \n                            ", export_modes=sims4.tuning.tunable_base.ExportModes.All), 'busy_time_situation_picker_tooltip': sims4.localization.TunableLocalizedString(description='\n                The tooltip that will display on the situation sim picker for\n                user selectable sims that will be busy during the situation.\n                ', export_modes=sims4.tuning.tunable_base.ExportModes.All)}
    levels_scheduler = None
    parent_track = None

    @classmethod
    def post_load(cls, manager):
        cls.post_load_propagate_parent_track()
        cls.post_load_scheduler_builder()

    @classmethod
    def post_load_propagate_parent_track(cls):
        for track in cls.branches:
            if track.parent_track is not None:
                logger.error('Track {} has multiple parent tracks: {}, {}', track, track.parent_track, cls)
            else:
                track.parent_track = cls

    @classmethod
    def post_load_scheduler_builder(cls):
        for level in cls.career_levels:
            if cls.levels_scheduler is None:
                cls.levels_scheduler = level.work_schedule(init_only=True)
            else:
                cls.levels_scheduler.merge_schedule(level.work_schedule(init_only=True))

    @classmethod
    def _tuning_loaded_callback(cls):
        services.get_instance_manager(sims4.resources.Types.CAREER_TRACK).add_on_load_complete(cls.post_load)

class TunableTimePeriod(sims4.tuning.tunable.TunableTuple):
    __qualname__ = 'TunableTimePeriod'

    def __init__(self, **kwargs):
        super().__init__(start_time=tunable_time.TunableTimeOfWeek(description='Time when the period starts.'), period_duration=sims4.tuning.tunable.Tunable(float, 1.0, description='Duration of this time period in hours.'), **kwargs)

class TunableOutfit(sims4.tuning.tunable.TunableTuple):
    __qualname__ = 'TunableOutfit'

    def __init__(self, **kwargs):
        super().__init__(outfit_tags=sims4.tuning.tunable.TunableList(sims4.tuning.tunable.TunableEnumEntry(tag.Tag, tag.Tag.INVALID, description='An outfit tag describing this outfit.'), description='A List of Tags that will be sent to CAS, to generate an outfit that matches them.'), **kwargs)

class StatisticPerformanceModifier(TunableTuple):
    __qualname__ = 'StatisticPerformanceModifier'

    def __init__(self, **kwargs):
        super().__init__(statistic=TunableReference(description='\n                Statistic that contributes to this performance modifier.\n                ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)), performance_curve=TunableCurve(description='\n                Curve that maps the commodity to performance change. X is the\n                commodity value, Y is the bonus performance.\n                '), reset_at_end_of_work=Tunable(description='\n                If set, the statistic will be reset back to its default value\n                when a Sim leaves work.\n                ', tunable_type=bool, default=True), tooltip_text=OptionalTunable(description="\n                If enabled, this performance modifier's description will appear\n                in its tooltip.\n                ", tunable=TunableTuple(general_description=TunableLocalizedStringFactory(description='\n                        A description of the performance modifier. {0.String}\n                        is the thresholded description.\n                        '), thresholded_descriptions=TunableList(description='\n                        A list of thresholds and the text describing it. The\n                        thresholded description will be largest threshold\n                        value in this list that the commodity is >= to.\n                        ', tunable=TunableTuple(threshold=Tunable(description='\n                                Threshold that the commodity must >= to.\n                                ', tunable_type=float, default=0.0), text=TunableLocalizedString(description='\n                                Description for meeting this threshold.\n                                '))))), **kwargs)

class TunableWorkPerformanceMetrics(sims4.tuning.tunable.TunableTuple):
    __qualname__ = 'TunableWorkPerformanceMetrics'

    def __init__(self, **kwargs):
        super().__init__(base_performance=sims4.tuning.tunable.Tunable(float, 1.0, description='Base work performance before any modifications are applied for going to a full day of work.'), missed_work_penalty=sims4.tuning.tunable.Tunable(float, 1.0, description="Penalty that is applied to your work day performance if you don't attend a full day of work."), full_work_day_percent=sims4.tuning.tunable.TunableRange(float, 80, 1, 100, description='This is the percent of the work day you must have been running the work interaction, to get full credit for your performance on that day. Ex: If this is tuned to 80, and you have a 5 hour work day, You must be inside the work interaction for at least 4 hours to get 100% of your performance. If you only went to work for 2 hours, you would get: (base_performance + positive performance mods * 0.5) + negative performance mods'), commodity_metrics=sims4.tuning.tunable.TunableList(sims4.tuning.tunable.TunableTuple(commodity=sims4.tuning.tunable.TunableReference(description='Commodity this test should apply to on the sim.', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)), threshold=sims4.tuning.tunable.TunableThreshold(description='The amount of commodity needed to get this performance mod.'), performance_mod=sims4.tuning.tunable.Tunable(float, 1.0, description='Work Performance you get for passing the commodity threshold.'), description='DEPRECATED. USE STATISTIC METRICS INSTEAD. If the tunable commodity is within the tuned threshold, this performance mod will be applied to an individual day of work.')), mood_metrics=sims4.tuning.tunable.TunableList(sims4.tuning.tunable.TunableTuple(mood=sims4.tuning.tunable.TunableReference(description='Mood the Sim needs to get this performance change.', manager=services.get_instance_manager(sims4.resources.Types.MOOD)), performance_mod=sims4.tuning.tunable.Tunable(float, 1.0, description='Work Performance you get for having this mood.'), description='If the Sim is in this mood state, they will get this performance mod applied for a day of work')), statistic_metrics=TunableList(description='\n                             Performance modifiers based on a statistic.\n                             ', tunable=StatisticPerformanceModifier()), performance_tooltip=OptionalTunable(description='\n                             Text to show on the performance tooltip below the\n                             ideal mood bar. Any Statistic Metric tooltip text\n                             will appear below this text on a new line.\n                             ', tunable=TunableLocalizedString()), performance_per_completed_goal=Tunable(description='\n                             The performance amount to give per completed\n                             career goal each work period.\n                             ', tunable_type=float, default=0.0), tested_metrics=TunableList(description='\n                             Performance modifiers that are applied based on\n                             the test.\n                             ', tunable=TunableTuple(tests=event_testing.tests.TunableTestSet(description='\n                                    Tests that must pass to get the performance modifier.\n                                    '), performance_mod=sims4.tuning.tunable.Tunable(description='\n                                    Performance modifier the Sim receives for passing the test. Can be negative.\n                                    ', tunable_type=float, default=0.0))), **kwargs)

class CareerSituation(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.CAREER_SITUATION)):
    __qualname__ = 'CareerSituation'
    INSTANCE_TUNABLES = {'situation': sims4.tuning.tunable.TunableReference(description='The situation that will be used for this career situation', manager=services.get_instance_manager(sims4.resources.Types.SITUATION), tuning_group=GroupNames.SITUATION), 'job': sims4.tuning.tunable.TunableReference(description='\n            When this career situation starts, this is the job in the situation\n            that the career Sim will automatically get assigned to. i.e. For this\n            career situation your doing a dinner party and the career sim is playing\n            the bartender.\n            ', manager=services.get_instance_manager(sims4.resources.Types.SITUATION_JOB), tuning_group=GroupNames.SITUATION), 'base_work_performance': sims4.tuning.tunable.Tunable(float, 10.0, description='\n            The base_work_performance you get for completing this situation.\n            work performance payout for a career situation is:\n            base_work_performance + (event_modifier * event_score) + (individual_modifier * individual_score)\n            ', tuning_group=GroupNames.SCORING), 'event_modifier': sims4.tuning.tunable.Tunable(float, 1.0, description='\n            The event modifier you get toward work performance for this situation.\n            work performance payout for a career situation is:\n            base_work_performance + (event_modifier * event_score) + (individual_modifier * individual_score)\n            ', tuning_group=GroupNames.SCORING), 'individual_modifier': sims4.tuning.tunable.Tunable(float, 1.0, description='\n            The individual modifier you get toward work performance for this situation\n            work performance payout for a career situation is:\n            base_work_performance + (event_modifier * event_score) + (individual_modifier * individual_score)\n            ', tuning_group=GroupNames.SCORING), 'name': sims4.localization.TunableLocalizedString(description='The name used for this career situation.', export_modes=sims4.tuning.tunable_base.ExportModes.All, tuning_group=GroupNames.UI), 'situation_description': sims4.localization.TunableLocalizedString(description='The description shown for this career situation in the career UI.', export_modes=sims4.tuning.tunable_base.ExportModes.All, tuning_group=GroupNames.UI), 'available_time': sims4.tuning.tunable.Tunable(int, 5, description='\n            Number of hours this career situation will remain available to the Sim for.\n            ')}

class CareerLevel(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.CAREER_LEVEL)):
    __qualname__ = 'CareerLevel'
    INSTANCE_TUNABLES = {'title': sims4.localization.TunableLocalizedStringFactory(description='Your career title for this career level', export_modes=sims4.tuning.tunable_base.ExportModes.All, tuning_group=GroupNames.UI), 'title_description': sims4.localization.TunableLocalizedStringFactory(description='A description for this individual career level', export_modes=sims4.tuning.tunable_base.ExportModes.All, tuning_group=GroupNames.UI), 'promotion_notification_text': TunableLocalizedStringFactory(description="\n            This string will be appended to the career's promotion\n            notification's text when a Sim is promoted to this level.\n            ", tuning_group=GroupNames.UI), 'promotion_audio_sting': OptionalTunable(description='\n            The audio sting to play when the Sim is promoted to this Career Level.\n            ', tunable=TunablePlayAudio(), tuning_group=GroupNames.AUDIO), 'screen_slam': OptionalTunable(description='\n            Which screen slam to show when this career level is reached.\n            Localization Tokens: Sim - {0.SimFirstName}, Level Name - \n            {1.String}, Level Number - {2.Number}, Track Name - {3.String}\n            ', tunable=ui.screen_slam.TunableScreenSlamSnippet()), 'work_schedule': scheduler.TunableWeeklyScheduleFactory(description='\n                              A tunable schedule that will determine when you have\n                              to be at work.\n                              ', export_modes=sims4.tuning.tunable_base.ExportModes.All), 'situation_schedule': scheduler.TunableWeeklyScheduleFactory(description="\n                                   Times when an event can happen for this career. If you\n                                   enter an event time and your career events are not on\n                                   cooldown one will occur. A time is randomly selected in\n                                   the time window and that's when you get an optional event.\n                                   ", tuning_group=GroupNames.SITUATION), 'situation_cooldown': sims4.tuning.tunable.Tunable(int, 1, description='After you do a career situation, this is the \n                                   cooldown in days. You will not get another career event until\n                                   the cooldown has finished.\n                                   ', tuning_group=GroupNames.SITUATION), 'situation_list': sims4.tuning.tunable.TunableList(sims4.tuning.tunable.TunableReference(manager=services.get_instance_manager(sims4.resources.Types.CAREER_SITUATION), description='\n                                   An individual career situation that could be created \n                                   as an optional event.\n                                   '), description='\n                               A list of situations that will be randomly chosen \n                               from when this career tries to spawn an optional \n                               event for the career Sim to take part in.\n                               ', tuning_group=GroupNames.SITUATION), 'additional_unavailable_times': sims4.tuning.tunable.TunableList(TunableTimePeriod(description='An individual period of time in which the sim is unavailible at this Career Level.'), description='A list time periods in which the Sim is considered busy for the sake of Sim Filters in addition to the normal working hours.'), 'wakeup_time': tunable_time.TunableTimeOfDay(description="\n                                 The time when the sim needs to wake up for work.  This is used by autonomy\n                                 to determine when it's appropriate to nap vs sleep.  It also guides a series\n                                 of buffs to make the sim more inclined to sleep as their bedtime approaches.", default_hour=8, needs_tuning=True), 'work_outfit': TunableOutfit(description='Tuning for this career level outfit.'), 'aspiration': sims4.tuning.tunable.TunableReference(manager=services.get_instance_manager(sims4.resources.Types.ASPIRATION), description='The Aspiration you need to complete to be eligible for promotion.', export_modes=sims4.tuning.tunable_base.ExportModes.All), 'simoleons_per_hour': sims4.tuning.tunable.Tunable(int, 10, description='number of simoleons you get per hour this level.', export_modes=sims4.tuning.tunable_base.ExportModes.All), 'simolean_trait_bonus': sims4.tuning.tunable.TunableList(description='\n            A bonus additional income amount applied at the end of the work day to total take home pay\n            based on the presence of the tuned trait.', tunable=sims4.tuning.tunable.TunableTuple(trait=sims4.tuning.tunable.TunableReference(manager=services.get_instance_manager(sims4.resources.Types.TRAIT)), bonus=sims4.tuning.tunable.Tunable(description='\n                                                      Percentage of daily take to add as bonus income.', tunable_type=int, default=20, tuning_group=GroupNames.SCORING))), 'performance_stat': sims4.tuning.tunable.TunableReference(services.get_instance_manager(sims4.resources.Types.STATISTIC), description='Commodity used to track career performance for this level.', export_modes=sims4.tuning.tunable_base.ExportModes.All, tuning_group=GroupNames.SCORING), 'demotion_performance_level': sims4.tuning.tunable.Tunable(float, -80.0, description='Level of performance commodity to cause demotion.', tuning_group=GroupNames.SCORING), 'fired_performance_level': sims4.tuning.tunable.Tunable(float, -95.0, description='Level of performance commodity to cause being fired.', tuning_group=GroupNames.SCORING), 'promote_performance_level': sims4.tuning.tunable.Tunable(float, 100.0, description='Level of performance commodity to cause being promoted.', tuning_group=GroupNames.SCORING), 'performance_metrics': TunableWorkPerformanceMetrics(tuning_group=GroupNames.SCORING), 'promotion_reward': sims4.tuning.tunable.TunableReference(manager=services.get_instance_manager(sims4.resources.Types.REWARD), description='\n                                 Which rewards are given when this career level\n                                 is reached.\n                                 '), 'tones': CareerToneTuning(description='\n            Tuning for tones.\n            '), 'ideal_mood': sims4.tuning.tunable.TunableReference(description='\n                               The ideal mood to display to the user to be in to gain performance at this career level\n                               ', manager=services.get_instance_manager(sims4.resources.Types.MOOD), export_modes=sims4.tuning.tunable_base.ExportModes.ClientBinary, tuning_group=GroupNames.UI), 'loot_on_join': LootActions.TunableReference(description='\n            Loot to give when Sim joins the career at this career level.\n            '), 'loot_on_quit': LootActions.TunableReference(description='\n            Loot to give when Sim quits the career on this career level.\n            ')}

    @classmethod
    def get_aspiration(cls):
        return cls.aspiration

class CareerSelectElement(interactions.utils.interaction_elements.XevtTriggeredElement):
    __qualname__ = 'CareerSelectElement'
    FACTORY_TUNABLES = {'description': 'Perform an operation on a Sim Career', 'career_op': sims4.tuning.tunable.TunableEnumEntry(career_ops.CareerOps, career_ops.CareerOps.JOIN_CAREER, description='\n                                Operation this basic extra will perform on the\n                                career.  Currently supports Joining, Quitting\n                                and Playing Hooky/Calling In Sick.\n                                '), 'subject': TunableEnumFlags(description='\n            The Sim to run this career op on.\n            Currently, the only supported options are Actor and PickedSim\n            ', enum_type=ParticipantType, default=ParticipantType.Actor)}

    def _do_behavior(self):
        participants = self.interaction.get_participants(self.subject)
        if participants is None or len(participants) == 0:
            logger.error('Could not find participant type, {}, for the Career Select op on interaction, {}', self.subject, self.interaction, owner='Trevor')
            return
        if len(participants) > 1:
            logger.warn('More than one participant found of type, {}, for the Career Select op on interaction, {}', self.subject, self.interaction, owner='Dan P')
        sim_or_sim_info = next(iter(participants))
        sim_info = getattr(sim_or_sim_info, 'sim_info', sim_or_sim_info)
        if self.career_op == career_ops.CareerOps.JOIN_CAREER:
            num = Career.NUM_CAREERS_PER_DAY
            if self.interaction.debug or self.interaction.cheat:
                num = 0
            if sim_info.is_selectable and sim_info.valid_for_distribution:
                msg = Career.get_join_career_pb(sim_info, num_careers_to_show=num)
                Distributor.instance().add_op(sim_info, GenericProtocolBufferOp(Operation.SELECT_CAREER_UI, msg))
        elif self.career_op == career_ops.CareerOps.QUIT_CAREER:
            if len(sim_info.career_tracker.quittable_careers()) == 1:

                def on_quit_dialog_response(dialog):
                    if dialog.accepted:
                        sim_info.career_tracker.remove_career(career.guid64)

                while True:
                    for career in sim_info.career_tracker.quittable_careers().values():
                        career_name = career._current_track.career_name(sim_info)
                        job_title = career.current_level_tuning.title(sim_info)
                        company_name = career.get_company_name_from_hash(career._company_name)
                        dialog = Career.QUIT_CAREER_DIALOG(sim_info, SingleSimResolver(sim_info))
                        dialog.show_dialog(on_response=on_quit_dialog_response, additional_tokens=(career_name, job_title, company_name))
                    if sim_info.is_selectable and sim_info.valid_for_distribution:
                        msg = Career.get_quit_career_pb(sim_info)
                        Distributor.instance().add_op(sim_info, GenericProtocolBufferOp(Operation.SELECT_CAREER_UI, msg))
            elif sim_info.is_selectable and sim_info.valid_for_distribution:
                msg = Career.get_quit_career_pb(sim_info)
                Distributor.instance().add_op(sim_info, GenericProtocolBufferOp(Operation.SELECT_CAREER_UI, msg))
        elif self.career_op == career_ops.CareerOps.CALLED_IN_SICK:
            for career in sim_info.career_tracker.careers.values():
                career.call_in_sick()

