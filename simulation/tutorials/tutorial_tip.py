from autonomy.autonomy_request import AutonomyDistanceEstimationBehavior, AutonomyPostureBehavior
from buffs.tunable import TunableBuffReference
from distributor.system import Distributor
from interactions import priority
from interactions.aop import AffordanceObjectPair
from interactions.context import InteractionContext, InteractionBucketType
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.tunable import TunableList, TunableReference, TunableTuple, Tunable, TunableEnumEntry, TunableSet, OptionalTunable, TunableRange, TunableResourceKey
from sims4.tuning.tunable_base import ExportModes
import autonomy
import distributor.ops
import enum
import event_testing
import services
import sims4.resources
import sims4.tuning.instances
import tutorials.tutorial

class TutorialTipGameState(enum.Int):
    __qualname__ = 'TutorialTipGameState'
    GAMESTATE_NONE = 0
    LIVE_MODE = 270579719
    BUILD_BUY = 2919482169
    CAS = 983016380
    NEIGHBORHOOD_VIEW = 3640749201
    GALLERY = 1

class TutorialTipUiElement(enum.Int):
    __qualname__ = 'TutorialTipUiElement'
    UI_INVALID = 0
    GLOBAL_ESCAPE_MENU = 1
    GLOBAL_ESCAPE_MENU_BUTTON = 2
    GLOBAL_HELP_BUTTON = 3
    CAS_PERSONALITYPANEL = 100
    CAS_ASPIRATIONS = 101
    CAS_TRAITS = 102
    CAS_SIM_HEAD = 103
    CAS_SIM_BODY = 104
    CAS_OUTFIT_BUTTON = 105
    CAS_RELATIONSHIP_BUTTON = 106
    CAS_RANDOM_BUTTON = 107
    CAS_GENETICS_BUTTON = 108
    CAS_TATTOOS_BUTTON = 109
    CAS_SKIN_COLOR_MENU = 110
    CAS_GALLERY_SAVE_BUTTON = 111
    CAS_FEATURED_LOOKS_BUTTON = 112
    CAS_DETAILED_EDIT_BUTTON = 113
    CAS_PLUMBOB_BUTTON = 114
    CAS_NAME_PANEL = 115
    CAS_PRIMARY_ASPIRATION_BUTTON = 116
    CAS_ASPIRATION_GROUP_BUTTON = 117
    CAS_ASPIRATION_TRACK_BUTTON = 118
    CAS_TRAIT_GRID_BUTTON = 119
    CAS_BONUS_TRAIT_ICON = 120
    CAS_TRAIT_CATEGORY_BUTTON = 121
    CAS_OUTFIT_TYPE_BUTTON = 122
    CAS_MENU_BODY_BUTTON = 123
    CAS_MENU_FACES_BUTTON = 124
    CAS_MULTIPLE_SIMS = 125
    CAS_SKIN_DETAILS_BUTTON = 126
    NHV_SET_HOME = 200
    NHV_WORLD_SELECT = 201
    NHV_CURRENT_LOT = 202
    NHV_OCCUPANTS = 203
    NHV_PLAY_BUTTON = 204
    NHV_MORE_BUTTON = 205
    NHV_BUILD_BUTTON = 206
    NHV_EVICT_BUTTON = 207
    NHV_MOVE_HOUSEHOLD_BUTTON = 208
    NHV_CHANGE_LOT_TYPE_BUTTON = 209
    NHV_EMPTY_LOT = 210
    NHV_MOVE_NEW_HOUSEHOLD_BUTTON = 211
    NHV_OASIS_SPRINGS_MAP = 212
    NHV_WILLOW_CREEK_SELECT = 213
    NHV_HOUSEHOLD_MANAGEMENT = 214
    NHV_EMPTY_LOT_OASIS = 215
    NHV_STARTER_WILLOW = 216
    NHV_EMPTY_LOT_MOVE_IN = 217
    LIVE_WALL_BUTTON = 300
    LIVE_NEXT_SIM = 301
    LIVE_CURRENT_SIM_PORTRAIT = 302
    LIVE_TIME_CONTROLS = 303
    LIVE_INTERACTION_QUEUE = 304
    LIVE_BUILD_BUTTON = 305
    LIVE_EMOTION = 306
    LIVE_BUFF = 307
    LIVE_MOTIVE_PANEL_BUTTON = 308
    LIVE_EMOTIONAL_WHIM = 309
    LIVE_SKILL_PANEL_BUTTON = 310
    LIVE_SIMOLEON_WALLET = 311
    LIVE_CAREER_PANEL_BUTTON = 312
    LIVE_GET_JOB_BUTTON = 313
    LIVE_CAREER_GOALS = 314
    LIVE_EVENTS_UI = 315
    LIVE_EVENT_GOALS_UI = 316
    LIVE_REL_INSPECTOR = 317
    LIVE_SIM_IN_REL_INSPECTOR = 318
    LIVE_RELATIONSHIP_PANEL_BUTTON = 319
    LIVE_ASPIRATION_PANEL_BUTTON = 320
    LIVE_ASPIRATION_ICON = 321
    LIVE_SATISFACTION_STORE_BUTTON = 322
    LIVE_CHANGE_ASPIRATION_BUTTON = 323
    LIVE_SUMMARY_PANEL_BUTTON = 324
    LIVE_TRAIT_IN_PANEL = 325
    LIVE_INVENTORY_PANEL_BUTTON = 326
    LIVE_ITEM_IN_PANEL = 327
    LIVE_SKILL_LIST = 328
    LIVE_FLOOR_BUTTON = 329
    LIVE_CAREER_ADVANCEMENT = 330
    LIVE_PHONE_BUTTON = 331
    BB_BUILD_SORT = 400
    BB_OBJECTS_BY_ROOM = 401
    BB_OBJECTS_BY_FUNCTION = 402
    BB_SEARCH_BAR = 403
    BB_FAMILY_INVENTORY = 404
    BB_CAMERA = 405
    BB_EYEDROPPER = 406
    BB_SLEDGEHAMMER = 407
    BB_DESIGN_TOOL = 408
    BB_UNDO_REDO = 409
    BB_SHARE_LOT = 410
    BB_GALLERY_BUTTON = 411
    BB_MAGALOG_CATEGORY = 412
    BB_MAGALOG_ITEM = 413
    BB_EMPTY_ROOM = 414
    BB_NAVIGATION_HOUSE = 415
    BB_STAIRS = 416
    BB_DOOR = 417
    BB_PRODUCT_CATALOG_ITEM = 418
    BB_CAMERA_FLOOR = 419
    BB_MAGALOG_BUTTON = 420
    BB_BEDBATH_DROPDOWN = 421
    BB_BULLDOZE = 422
    BB_LOTNAME = 423
    BB_FOUNDATION_BUTTON = 424
    BB_MAGALOG_FURNISHED_ROOMS = 425
    BB_LOT_INFO = 426
    BB_PRODUCT_CATALOG_STAIRS = 427
    GAL_GALLERY_UI = 500
    GAL_HOME_TAB = 501
    GAL_FEED_SECTION = 502
    GAL_HASHTAG_SECTION = 503
    GAL_SPOTLIGHT_SECTION = 504
    GAL_COMMUNITY_TAB = 505
    GAL_LIBRARY_TAB = 506
    GAL_FILTER_HEADER = 507
    GAL_FILTERS_PANEL = 508
    GAL_SEARCH_WIDGET = 509
    GAL_THUMBNAILS_WIDGET = 510
    GAL_INFO_PANEL = 511
    GAL_COMMENTS = 512
    GAL_SAVE_BUTTON = 513
    GAL_APPLY_BUTTON = 514
    GAL_PLAYER_PROFILE = 515

class TutorialTipGroupRequirementType(enum.Int):
    __qualname__ = 'TutorialTipGroupRequirementType'
    ANY = 0
    ALL = 1

GROUP_NAME_DISPLAY_CRITERIA = 'Display Criteria'
GROUP_NAME_ACTIONS = 'Tip Actions'
GROUP_NAME_SATISFY = 'Satisfy Criteria'

class TunableTutorialTipDisplay(TunableTuple):
    __qualname__ = 'TunableTutorialTipDisplay'

    def __init__(self, **kwargs):
        super().__init__(cancelable=Tunable(description='\n                If this tutorial tip can be canceled.\n                ', tunable_type=bool, default=True), text=TunableLocalizedStringFactory(description="\n                The text for this tip.\n                Token {0} is the active sim. i.e. {0.SimFirstName}\n                Token {1.String} is a 'wildcard' string to be used for things\n                like aspiration names or buff names during the tutorial.\n                "), action_text=TunableLocalizedStringFactory(description="\n                The action the user must make for this tip to satisfy.\n                Token {0} is the active sim. i.e. {0.SimFirstName}\n                Token {1.String} is a 'wildcard' string to be used for things\n                like aspiration names or buff names during the tutorial.\n                "), timeout=TunableRange(description='\n                How long, in seconds, until this tutorial tip times out.\n                ', tunable_type=int, default=1, minimum=1), ui_element=TunableEnumEntry(description='\n                The UI element associated with this tutorial tip.\n                ', tunable_type=TutorialTipUiElement, default=TutorialTipUiElement.UI_INVALID), is_modal=Tunable(description='\n                Enable if this tip should be modal.\n                Disable, if not.\n                ', tunable_type=bool, default=False), icon=TunableResourceKey(description='\n                The icon to be displayed in a modal tutorial tip.\n                If Is Modal is disabled, this field can be ignored.\n                ', resource_types=sims4.resources.CompoundTypes.IMAGE, default=None), **kwargs)

class TutorialTipGroup(metaclass=sims4.tuning.instances.HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.TUTORIAL_TIP)):
    __qualname__ = 'TutorialTipGroup'
    INSTANCE_TUNABLES = {'tips': TunableList(description='\n            The tips that are associated with this tip group.\n            ', tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.TUTORIAL_TIP), class_restrictions='TutorialTip', export_modes=ExportModes.ClientBinary)), 'group_requirement': TunableEnumEntry(description='\n            The requirement for completing this tip group. ANY means any of the\n            tips in this group need to be completed for the group to be\n            considered complete. ALL means all of the tips in this group need\n            to be completed for the group to be considered complete.\n            ', tunable_type=TutorialTipGroupRequirementType, default=TutorialTipGroupRequirementType.ALL, export_modes=ExportModes.ClientBinary)}

    def __init__(self):
        raise NotImplementedError

class TutorialTip(metaclass=sims4.tuning.instances.HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.TUTORIAL_TIP)):
    __qualname__ = 'TutorialTip'
    INSTANCE_TUNABLES = {'required_tip_groups': TunableList(description='\n            The Tip Groups that must be complete for this tip to be valid.\n            ', tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.TUTORIAL_TIP), class_restrictions='TutorialTipGroup'), tuning_group=GROUP_NAME_DISPLAY_CRITERIA, export_modes=ExportModes.ClientBinary), 'required_ui_list': TunableList(description='\n            The UI elements that are required to be present in order for this\n            tutorial tip to be valid.\n            ', tunable=TunableEnumEntry(tunable_type=TutorialTipUiElement, default=TutorialTipUiElement.UI_INVALID), tuning_group=GROUP_NAME_DISPLAY_CRITERIA, export_modes=ExportModes.ClientBinary), 'required_game_state': TunableEnumEntry(description='\n            The state the game must be in for this tutorial tip to be valid.\n            ', tunable_type=TutorialTipGameState, default=TutorialTipGameState.GAMESTATE_NONE, tuning_group=GROUP_NAME_DISPLAY_CRITERIA, export_modes=ExportModes.ClientBinary), 'required_tips_not_satisfied': TunableList(description='\n            This is a list of tips that must be un-satisfied in order for this\n            tip to activate. If any tip in this list is satisfied, this tip will\n            not activate.\n            ', tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.TUTORIAL_TIP), class_restrictions='TutorialTip'), tuning_group=GROUP_NAME_DISPLAY_CRITERIA, export_modes=ExportModes.ClientBinary), 'display': TunableTutorialTipDisplay(description='\n            This display information for this tutorial tip.\n            ', tuning_group=GROUP_NAME_ACTIONS, export_modes=ExportModes.ClientBinary), 'buffs': TunableList(description='\n            Buffs that will be applied at the start of this tutorial tip.\n            ', tunable=TunableBuffReference(), tuning_group=GROUP_NAME_ACTIONS), 'commodities_to_solve': TunableSet(description="\n            A set of commodities we will attempt to solve. This will result in\n            the Sim's interaction queue being filled with various interactions.\n            ", tunable=TunableReference(services.statistic_manager()), tuning_group=GROUP_NAME_ACTIONS), 'timeout_satisfies': Tunable(description='\n            If enabled, this tip is satisfied when the timeout is reached.\n            If disabled, this tip will not satisfy when the timeout is reached.\n            ', tunable_type=bool, default=True, tuning_group=GROUP_NAME_SATISFY, export_modes=ExportModes.ClientBinary), 'gameplay_test': OptionalTunable(description='\n            Tests that, if passed, will satisfy this tutorial tip.\n            Only one test needs to pass to satisfy. These are intended for tips\n            where the satisfy message should be tested and sent at a later time.\n            ', tunable=tutorials.tutorial.TunableTutorialTestVariant(), tuning_group=GROUP_NAME_SATISFY), 'gameplay_immediate_test': OptionalTunable(description='\n            Tests that, if passed, will satisfy this tutorial tip.\n            Only one test needs to pass to satisfy. These are intended for tips\n            where the satisfy message should be tested and sent back immediately.\n            ', tunable=tutorials.tutorial.TunableTutorialTestVariant(), tuning_group=GROUP_NAME_SATISFY), 'satisfy_on_activate': Tunable(description="\n            If enabled, this tip is satisfied immediately when all of it's\n            preconditions have been met.\n            ", tunable_type=bool, default=False, tuning_group=GROUP_NAME_SATISFY, export_modes=ExportModes.ClientBinary)}

    def __init__(self):
        raise NotImplementedError

    @classmethod
    def activate(cls):
        client = services.client_manager().get_first_client()
        active_sim = client.active_sim
        if cls.gameplay_immediate_test is not None:
            resolver = event_testing.resolver.SingleSimResolver(active_sim.sim_info)
            if resolver(cls.gameplay_immediate_test):
                cls.satisfy()
            else:
                return
        for buff_ref in cls.buffs:
            active_sim.add_buff_from_op(buff_ref.buff_type, buff_reason=buff_ref.buff_reason)
        if cls.gameplay_test is not None:
            services.get_event_manager().register_tests(cls, [cls.gameplay_test])
        if cls.commodities_to_solve:
            context = InteractionContext(active_sim, InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT, priority.Priority.High, bucket=InteractionBucketType.DEFAULT)
            for commodity in cls.commodities_to_solve:
                if not active_sim.queue.can_queue_visible_interaction():
                    break
                autonomy_request = autonomy.autonomy_request.AutonomyRequest(active_sim, autonomy_mode=autonomy.autonomy_modes.FullAutonomy, commodity_list=(commodity,), context=context, consider_scores_of_zero=True, posture_behavior=AutonomyPostureBehavior.IGNORE_SI_STATE, distance_estimation_behavior=AutonomyDistanceEstimationBehavior.ALLOW_UNREACHABLE_LOCATIONS, allow_opportunity_cost=False, autonomy_mode_label_override='Tutorial')
                selected_interaction = services.autonomy_service().find_best_action(autonomy_request)
                AffordanceObjectPair.execute_interaction(selected_interaction)

    @classmethod
    def handle_event(cls, sim_info, event, resolver):
        if cls.gameplay_test is not None and resolver(cls.gameplay_test):
            cls.satisfy()

    @classmethod
    def satisfy(cls):
        op = distributor.ops.SetTutorialTipSatisfy(cls.guid64)
        distributor_instance = Distributor.instance()
        distributor_instance.add_op_with_no_owner(op)

    @classmethod
    def deactivate(cls):
        if cls.gameplay_test is not None:
            services.get_event_manager().unregister_tests(cls, (cls.gameplay_test,))

