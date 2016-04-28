from _weakrefset import WeakSet
from contextlib import contextmanager
import itertools
import operator
import weakref
from animation.posture_manifest_constants import STAND_NO_SURFACE_CONSTRAINT
from autonomy.autonomy_modes import FullAutonomy
from autonomy.parameterized_autonomy_request_info import ParameterizedAutonomyRequestInfo
from element_utils import build_element, build_critical_section, build_critical_section_with_finally
from event_testing.resolver import SingleSimResolver
from event_testing.results import TestResult
from interactions import ParticipantType, PipelineProgress, TargetType
from interactions.aop import AffordanceObjectPair
from interactions.base.basic import TunableBasicContentSet
from interactions.base.interaction import Interaction, OWNS_POSTURE_LIABILITY, CANCEL_AOP_LIABILITY, CancelAOPLiability, OwnsPostureLiability, CancelInteractionsOnExitLiability, CANCEL_INTERACTION_ON_EXIT_LIABILITY, InteractionQueuePreparationStatus
from interactions.choices import ChoiceMenu
from interactions.context import InteractionContext, InteractionBucketType, QueueInsertStrategy
from interactions.interaction_finisher import FinishingType
from interactions.privacy import TunablePrivacySnippet
from interactions.si_state import SIState
from interactions.utils.animation import flush_all_animations, InteractionAsmType
from interactions.utils.animation_reference import TunableAnimationReference
from interactions.utils.routing import TunableWalkstyle
from interactions.utils.tunable import ContentSet
from objects.components.autonomy import TunableParameterizedAutonomy
from objects.components.types import CARRYABLE_COMPONENT
from objects.object_enums import ResetReason
from postures import PostureTrack, posture_graph, PostureTransitionTargetPreferenceTag, DerailReason
from postures.posture_scoring import TunableSimAffinityPostureScoringData
from postures.posture_specs import PostureOperation, PostureSpecVariable
from primitives.staged import StageControllerElement
from scheduling import HardStopError
from sims.sim_outfits import OutfitChangeReason, DefaultOutfitPriority, TunableOutfitChange
from sims4.localization import TunableLocalizedString, TunableLocalizedStringFactory
from sims4.tuning.dynamic_enum import DynamicEnum
from sims4.tuning.geometric import TunableVector2, TunablePolygon, TunableVector3
from sims4.tuning.tunable import Tunable, TunableList, TunableReference, TunableTuple, OptionalTunable, TunableEnumEntry, TunableVariant, TunableSet, TunableMapping
from sims4.tuning.tunable_base import GroupNames, FilterTag
from sims4.utils import EdgeWatcher, flexmethod, classproperty, flexproperty
from singletons import DEFAULT
from snippets import TunableAffordanceFilterSnippet
from statistics.statistic_conditions import StatisticCondition
from tag import Tag
from ui.ui_dialog_notification import TunableUiDialogNotificationSnippet
import autonomy.autonomy_request
import caches
import element_utils
import elements
import enum
import event_testing.test_events as test_events
import event_testing.tests as tests
import gsi_handlers.interaction_archive_handlers
import interactions.priority
import postures
import services
import sims4.log
from animation.posture_manifest import _get_posture_type_for_posture_name
logger = sims4.log.Logger('Interactions')
LOCK_ENTERING_SI = 'enter_si'

class LifetimeState(enum.Int, export=False):
    __qualname__ = 'LifetimeState'
    INITIAL = 0
    RUNNING = 1
    PENDING_COMPLETE = 2
    CANCELED = 3
    EXITED = 4

class OutfitPriorityPoint(enum.Int):
    __qualname__ = 'OutfitPriorityPoint'
    OnQueue = 0
    OnSIState = 1

class ObjectPreferenceTag(DynamicEnum):
    __qualname__ = 'ObjectPreferenceTag'
    INVALID = -1

class RallyableTag(DynamicEnum):
    __qualname__ = 'RallyableTag'
    NONE = 0

class TunableAutonomyPreference(TunableTuple):
    __qualname__ = 'TunableAutonomyPreference'

    def __init__(self, is_scoring):
        super().__init__(tag=TunableEnumEntry(ObjectPreferenceTag, None, description="\n                The preference tag associated with this interaction's \n                ownership settings.\n                "), should_set=OptionalTunable(description='\n                Whether or not running this interaction sets an autonomy\n                preference for the target object.\n                ', tunable=TunableTuple(autonomous=Tunable(bool, False, description='\n                        Whether or not this should be set when this interaction \n                        is running autonomously.\n                        ')), enabled_by_default=True, disabled_value=False, disabled_name='false', enabled_name='true'), locked_args={'is_scoring': is_scoring})

class SuperInteraction(Interaction, StageControllerElement):
    __qualname__ = 'SuperInteraction'
    MULTIPLAYER_REJECTED_TOOLTIP = TunableLocalizedString(description='Grayed out Pie Menu Text on sim has already been rejected by other player')
    DEFAULT_POSTURE_TARGET_PREFERENCES = TunableMapping(key_type=TunableEnumEntry(PostureTransitionTargetPreferenceTag, PostureTransitionTargetPreferenceTag.INVALID), value_type=Tunable(float, 0), description='\n                                                  A tunable mapping of posture tags to a goal score bonus in meters.  This is used to make some objects \n                                                  more attractive than others for the purposes of posture preference scoring.  That means that higher numbers\n                                                  are good; the Sim will go x meters out of their way to use these objects, where x is the amount tuned.\n                                                  \n                                                  For example, if one object has a score of 3 and another object has a score of 0, the object that scores \n                                                  0 will need to be more than 3 meters closer than the object that scores 3 for the Sim to choose it.\n                                                  \n                                                  Example: Let\'s say you want to make couches more desirable for watching TV.  To\n                                                  do this, you would create a new tag in PostureTransitionTargetPreferenceTag (found in Tuning->postures) \n                                                  called "ComfortableSeating".  Then you would tag all appropriate objects with that tag by adding it to \n                                                  PosturePreferenceTagList on the object.  Next, you would come in here and add a new item with a key of that \n                                                  tag and a value of 10 or so, which is about the size of the constraint to watch TV. Thus they will tend to use\n                                                  couches in the TV cone at the expense of other factors. One example downside of this is they will be less \n                                                  inclined to consider how centered they are in the TV cone and what direction the sofa is facing.\n                                                  ')
    INSTANCE_TUNABLES = {'super_affordance_compatibility': TunableAffordanceFilterSnippet(description="\n            The filter of SuperInteractions that will be allowed to run at the same time\n            as this interaction, if possible. By default, include all interactions which\n            means compatibility will be determined by posture requirements. When needed,\n            add specific interactions to the blacklist when they don't make sense to \n            multitask with this or the gameplay is not desired. When creating an interaction\n            that should generally not multitask, like motive failure, switch variant to\n            exclude_all."), 'super_affordance_klobberers': OptionalTunable(TunableAffordanceFilterSnippet(), description="\n            The filter of SuperInteractions that this interaction can clobber even if\n            they are still guaranteed. Use this for interactions where we commonly\n            want to transition to another interaction without waiting, for example\n            bed_BeIntimate needs to cancel sim_chat to run, but we don't want to wait\n            for sim_chat to go inertial. Remember that this should generally default\n            to exclude_all and you want to call out the interactions that can be\n            clobbered in the whitelist of exclude_all; interactions that pass\n            the filter will be clobbered."), '_super_affordance_can_share_target': Tunable(bool, False, description='\n            By default, SuperInteractions with the same target are considered incompatible.\n            Check this to enable compatibility with other SIs that target the same object, such\n            as for Tend Bar and Make Drink.', tuning_filter=FilterTag.EXPERT_MODE), '_super_affordance_should_persist_held_props': Tunable(bool, False, description='\n            By default, held props owned by a SuperInteraction are hidden whenever \n            mixers from another SuperInteraction are run.  Check this to guarantee\n            that the props are NEVER hidden in this scenario.  Use with EXTREME caution!', tuning_filter=FilterTag.EXPERT_MODE), 'animation_stat': OptionalTunable(TunableReference(services.get_instance_manager(sims4.resources.Types.STATISTIC), description='The stat defining the tiers of animation content to play for this interaction.')), '_provided_posture_type': TunableReference(description="\n            Posture tuning must be hooked up via an interaction that provides \n            that posture \n            Setting this tunable on an SI will cause it to provide the \n            specified posture and will create the appropriate nodes in the \n            posture graph. \n            IMPORTANT: Only one interaction can provide a given posture type on \n            a single object, otherwise there will be problems with the graph! \n            Supported Posture Type Filter is for removing supported entries \n            from that posture's manifest and is seldom used.\n            ", manager=services.get_instance_manager(sims4.resources.Types.POSTURE), category='asm', tuning_group=GroupNames.POSTURE), 'supported_posture_type_filter': TunableList(TunableTuple(participant_type=TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='The participant to which to apply this filter.'), posture_type=TunableReference(services.get_instance_manager(sims4.resources.Types.POSTURE), description='The posture being filtered'), force_carry_state=TunableList(Tunable(bool, True), maxlength=3, description='A carry state to force on the supported postures.  The list must either be empty or have exactly three elements corresponding to carry right, left, and both.')), tuning_group=GroupNames.POSTURE, description='A list of filters to apply to the postures supported by this affordance.'), 'posture_target_preference': OptionalTunable(TunableMapping(key_type=TunableEnumEntry(PostureTransitionTargetPreferenceTag, PostureTransitionTargetPreferenceTag.INVALID), value_type=Tunable(float, 0), description='\n                                                  A tunable mapping of posture tags to a goal score bonus in meters.  This is used to make some objects \n                                                  more attractive than others for the purposes of posture preference scoring.  That means that higher numbers\n                                                  are good; the Sim will go x meters out of their way to use these objects, where x is the amount tuned.\n                                                  \n                                                  For example, if one object has a score of 3 and another object has a score of 0, the object that scores \n                                                  0 will need to be more than 3 meters closer than the object that scores 3 for the Sim to choose it.\n                                                  \n                                                  Example: Let\'s say you want to make couches more desirable for watching TV.  To\n                                                  do this, you would create a new tag in PostureTransitionTargetPreferenceTag (found in Tuning->postures) \n                                                  called "ComfortableSeating".  Then you would tag all appropriate objects with that tag by adding it to \n                                                  PosturePreferenceTagList on the object.  Next, you would come in here and add a new item with a key of that \n                                                  tag and a value of 10 or so, which is about the size of the constraint to watch TV. Thus they will tend to use\n                                                  couches in the TV cone at the expense of other factors. One example downside of this is they will be less \n                                                  inclined to consider how centered they are in the TV cone and what direction the sofa is facing.\n                                                  ')), 'sim_affinity_posture_scoring_data': OptionalTunable(tunable=TunableSimAffinityPostureScoringData(), tuning_group=GroupNames.POSTURE, description='\n            Tunable preferences for doing this interaction nearby other Sims, for example eating together or watching TV on the same sofa.'), 'force_autonomy_on_inertia': Tunable(bool, False, tuning_group=GroupNames.AUTONOMY, description='Whether we should force a full autonomy ping when this interaction enters the inertial phase.'), 'force_exit_on_inertia': Tunable(description='\n            This tuning field is deprecated. Use the EXIT_NATURALLY conditional\n            action on exit conditions to force Sims to exit an interaction once\n            a condition is reached.\n            ', tunable_type=bool, default=False, tuning_group=GroupNames.DEPRECATED), 'pre_add_autonomy_commodities': TunableList(TunableParameterizedAutonomy(), tuning_group=GroupNames.AUTONOMY, description="List, in order, of parameterized autonomy requests to run prior to adding this interaction to the Sim's SI State."), 'pre_run_autonomy_commodities': TunableList(TunableParameterizedAutonomy(), tuning_group=GroupNames.AUTONOMY, description="List, in order, of parameterized autonomy requests to run prior to running this interaction but after it has been added to the Sim's SI state."), 'post_guaranteed_autonomy_commodities': TunableList(TunableParameterizedAutonomy(), tuning_group=GroupNames.AUTONOMY, description='List, on order, of parameterized autonomy requests to run when this interaction goes inertial.'), 'post_run_autonomy_commodities': TunableTuple(description='\n            Grouping of requests and fallback behavior that can happen\n            after running this interaction.\n            ', requests=TunableList(description='\n                List, in order, of parameterized autonomy requests to run after running this interaction.', tunable=TunableParameterizedAutonomy()), fallback_notification=OptionalTunable(description='\n                If set, this notification will be displayed if there is no \n                parametrized autonomy request pushed at the end of this\n                interaction.\n                ', tunable=TunableUiDialogNotificationSnippet()), tuning_group=GroupNames.AUTONOMY), 'opportunity_cost_multiplier': Tunable(float, 1, tuning_group=GroupNames.AUTONOMY, description='This will be multiplied with the calculated opportunity cost of an SI when determining the cost of leaving this SI.'), 'apply_autonomous_posture_change_cost': Tunable(bool, True, tuning_group=GroupNames.AUTONOMY, description="\n                                                        There are two places where a cost for changing postures is applied.\n                                                        1) When there is a guaranteed SI in the sim's SI state, we test out all interactions\n                                                           that require a posture change.\n                                                        2) Even when all interactions are inertial, we still apply a penalty for changing \n                                                           postures.\n                                                        If this tunable is set to True, both of these conditions are applied.  If it's False, \n                                                        neither condition is applied and the Sim will effectively ignore the posture changes\n                                                        with regards to autonomy.  Note that the posture system will still score normally.\n                                                        "), 'attention_cost': Tunable(float, 1, tuning_group=GroupNames.AUTONOMY, description="\n                                       The attention cost of this interaction.  This models the fact that humans are notoriously\n                                       bad at multi-tasking.  For example, if you are really hungry but socially satisfied, then\n                                       talking while eating is not necessarily the correct choice.\n                                       \n                                       More specifically, the total attention cost of all SI's are summed up.  This is used as the \n                                       X value for the attention utility curve and a normalized value is returned.  This value is\n                                       multiplied to the autonomy score to get the final score.  When considering a new action, the\n                                       Sim will look at the score for their current state and subtract the target score.  If this \n                                       value is less than or equal to 0, the choice will be discarded.\n                                    "), 'duplicate_affordance_group': TunableEnumEntry(description='\n                                            Autonomy will only consider a limited number of affordances that share this tag.  Each\n                                            autonomy loop, it will gather all of those aops, then score a random set of them (this\n                                            number is tuned in autonomy.autonomy_modes.NUMBER_OF_DUPLICATE_AFFORDANCE_TAGS_TO_SCORE).\n                                            \n                                            All affordances that are tagged with INVALID will be scored.  \n                                            ', tunable_type=Tag, default=Tag.INVALID, tuning_group=GroupNames.AUTONOMY), 'autonomy_can_overwrite_similar_affordance': Tunable(bool, False, needs_tuning=True, tuning_group=GroupNames.AUTONOMY, description="If True, autonomy will consider this affordance even if it's already running."), 'subaction_selection_weight': Tunable(float, 1, tuning_group=GroupNames.AUTONOMY, description='The weight for selecting subactions from this super affordance.  A higher weight means the Sim will tend to run mixers provided by this SI more often.'), 'scoring_priority': TunableEnumEntry(autonomy.autonomy_interaction_priority.AutonomyInteractionPriority, autonomy.autonomy_interaction_priority.AutonomyInteractionPriority.INVALID, tuning_group=GroupNames.AUTONOMY, description='\n                                    The priority bucket that this interaction will be scored in.  For example, if you have \n                                    three interactions that all advertise to the same commodity but want to guarantee that\n                                    one is ALWAYS chosen over the others, you can tune this value to HIGH.  Likewise, if \n                                    you want to guarantee that one or more interactions are only chosen if nothing else is\n                                    available, set this to LOW.\n                                    \n                                    It\'s important to note two things:\n                                        1) Autonomy is commodity-based.  That means it will always choose a valid SI from \n                                           a higher scoring commodity rather than a lower scoring commodity.  This tunable\n                                           is only used for bucketing SI\'s within a single commodity loop.  That means it\'s\n                                           possible for a LOW priority SI to be chosen over a HIGH priority SI.  This will \n                                           happen when the LOW priority SI\'s commodity out scores the other SI\'s commodity.\n                                        2) Under the covers, this is just a sort.  There is not special meaning for these \n                                           values; each one just maps to an integer which is used to sort the list of scored\n                                           SI\'s into buckets.  We choose an SI from the highest priority bucket.\n                                           \n                                    The classic example of this tech is autonomous eating.  A Sim should always choose to \n                                    eat food that is already prepared rather than make new food.  Furthermore, a sim should\n                                    always choose to resume cooking food that he started rather than eat food sitting out.\n                                    This is accomplished by setting the resume interactions to HIGH priority and the "make\n                                    new food" interactions to LOW priority.  Eating existing food, getting food from the \n                                    inventory, grabbing a plate, etc. can all remain NORMAL.\n                                ', needs_tuning=True), 'basic_content': TunableBasicContentSet(one_shot=True, flexible_length=True, default='flexible_length', description='The main animation and periodic stat changes for the interaction.'), 'relationship_scoring': Tunable(bool, False, needs_tuning=True, tuning_group=GroupNames.AUTONOMY, description='When True, factor the relationship and party size into the autonomy scoring for this interaction.'), '_party_size_weight_tuning': TunableList(TunableVector2(sims4.math.Vector2(0, 0), description='Point on a Curve'), tuning_group=GroupNames.AUTONOMY, description='A list of Vector2 points that define the utility curve.'), 'joinable': TunableList(TunableTuple(join_affordance=TunableVariant(affordance=TunableTuple(locked_args={'is_affordance': True}, value=OptionalTunable(TunableReference(services.get_instance_manager(sims4.resources.Types.INTERACTION)), disabled_name='this', enabled_name='custom', description='The affordance that is pushed on the joining sim.')), commodity_search=TunableTuple(locked_args={'is_affordance': False}, value=TunableTuple(commodity=TunableReference(services.get_instance_manager(sims4.resources.Types.STATIC_COMMODITY), description='Commodity searched for when finding a potential join affordance.'), radius=Tunable(int, 5, description='Max radial distance an object which satisfies the tuned commodity can be from the sim being joined.'))), default='affordance', description='You can tune join to use a specific affordance, or to search for an affordance which provides a tuned commodity.'), join_target=TunableEnumEntry(ParticipantType, ParticipantType.Object, description='This is the participant in the interaction being joined that should be target of new join interaction.'), join_available=OptionalTunable(TunableTuple(loc_custom_join_name=OptionalTunable(TunableLocalizedStringFactory(description='Use a specified string for the Join interaction instead of the standard join text.'))), description='Whether or not Join is available.'), invite_available=OptionalTunable(TunableTuple(loc_custom_invite_name=OptionalTunable(TunableLocalizedStringFactory(description='Use a specified string for the Invite interaction instead of the standard invite text.'))), description='Whether or not Ask to Join is available.'), link_joinable=Tunable(bool, False, description="If true, the joining Sim's interaction will be cancelled if the joined Sim cancels or exits their interaction.")), description="Joinable interactions for this super-interaction. A joinable interaction X means that when Sim A is running X, Sim A clicking on Sim B yields 'Ask to Join: X', whereas if Sim B is running X, Sim A clicking on Sim B yields 'Join: X'. If both cases are true, both options are yielded. If neither case is true, X is yielded."), 'rallyable': TunableList(TunableTuple(tag=TunableEnumEntry(RallyableTag, None, description='An identifying tag that determines how consecutive rallyable interactions are grouped and handled.'), behavior=TunableVariant(push_affordance=TunableTuple(loc_display_name=TunableLocalizedStringFactory(default=3390898100), affordance_target=OptionalTunable(TunableEnumEntry(ParticipantType, ParticipantType.Object), enabled_by_default=True, disabled_name='none', enabled_name='participant_type', description='the target of the pushed affordance relative to original interaction. so actor would be sim that triggered the rally. Use None for affordances like sit-smart'), affordance=TunableReference(services.affordance_manager(), description='The affordance to be pushed on Party members other than the initiating Sim. If no affordance is specified, push this affordance.'), description='Bring the Party along and push the specified interaction on all members.'), solve_static_commodity=TunableTuple(loc_display_name=TunableLocalizedStringFactory(default=180956154), static_commodity=TunableReference(services.static_commodity_manager(), description='The static commodity to be solved for all Party members other than the initiating Sim.'), description='Bring the Party along and try to solve for the specified static commodity for all members.'), default='push_affordance', description="Select the behavior this interaction will have with respect to members of the Sim's Party."), push_social=TunableReference(services.affordance_manager(), description='When rallied Sims finish their transition they will push this affordance if they are no longer in a social group. e.g. If you run GoHereTogether while your Sims are in sit_intimate, sit_intimate will cancel, so we want to put them in chat at the end.')), description='Interactions in this list will be generated in the Pie Menu when the Sim is in a Party with other Sims. All Sims will have an interaction pushed in order to keep the Party together.', needs_tuning=True), 'autonomy_preference': OptionalTunable(description='\n            Autonomy Preference related tuning options for this super interaction.\n            You can make a sim always use the same object, or use the tuned \n            preference score for certain SIs.\n            ', tunable=TunableVariant(use_preference=TunableTuple(preference=TunableAutonomyPreference(is_scoring=False)), scoring_preference=TunableTuple(preference=TunableAutonomyPreference(is_scoring=True), autonomy_score=Tunable(float, 1, description='\n                        The amount to multiply the autonomous aop score by when \n                        the Sim prefers this object.\n                        ')), default='use_preference'), needs_tuning=True, tuning_group=GroupNames.AUTONOMY), 'disable_autonomous_multitasking_if_user_directed': Tunable(description="\n            If this is checked, if this interaction is user directed and\n            guaranteed, sim will not consider running full autonomy and sim\n            cannot be a target of an full autonomy ping.\n            \n            For Example, if sim started a user directed painting, but don't\n            want sim to be interrupted by a social have this checked.\n            ", tunable_type=bool, default=False, tuning_group=GroupNames.AUTONOMY), 'use_best_scoring_aop': Tunable(bool, True, needs_tuning=True, tuning_group=GroupNames.AUTONOMY, description="\n                                               If checked, autonomy will always use the best scoring aop when there are similar aops.  \n                                               For example, checking this on view_painting will cause only the best scoring paiting \n                                               to be considered.  If you uncheck this for painting, autonomy will consider all paintings,\n                                               but will use the best scoring painting when scoring against other aops. In other words,\n                                               if you uncheck this for view_painting and have 10,000 paintings on the lot, the Sim will\n                                               consider those paintings, but it won't skew the probability. \n                                            "), 'outfit_change': TunableTuple(description='\n            A structure of outfit change tunables.\n            ', on_route_change=OptionalTunable(TunableEnumEntry(description='\n                An outfit change reason for an outfit change to execute on the\n                first mobile node of the transition to this interaction.\n                ', tunable_type=OutfitChangeReason, default=OutfitChangeReason.Invalid)), posture_outfit_change_overrides=OptionalTunable(TunableMapping(description='\n                A mapping of postures to outfit change entry and exit reason\n                overrides.\n                ', key_type=TunableReference(description="\n                    If the Sim encounters this posture during this\n                    interaction's transition sequence, the posture's outfit\n                    change reasons will be the ones specified here.\n                    ", manager=services.get_instance_manager(sims4.resources.Types.POSTURE)), value_type=TunableOutfitChange(description='\n                    Define what outfits the Sim is supposed to wear when entering or\n                    exiting this posture.\n                    '))), tuning_group=GroupNames.CLOTHING_CHANGE), 'outfit_priority': OptionalTunable(TunableTuple(outfit_change_reason=TunableEnumEntry(OutfitChangeReason, OutfitChangeReason.Invalid, description='Outfit Change Reason that is given a default priority'), step_to_add=TunableEnumEntry(OutfitPriorityPoint, OutfitPriorityPoint.OnQueue, description='Point in the Interaction where the outfit priority is set.'), priority=TunableEnumEntry(DefaultOutfitPriority, DefaultOutfitPriority.NoPriority, description="Priority Level of this Reason for selecting a sim's default outfit.")), tuning_group=GroupNames.CLOTHING_CHANGE, tuning_filter=FilterTag.EXPERT_MODE, description='Enable an outfit change to the sims default outfit during this interaction.'), 'object_reservation_tests': tests.TunableTestSet(tuning_group=GroupNames.AVAILABILITY, description='Set of Tests that must be passed for a Sim to use an adjacent part of an object while this SI is being performed.'), 'cancel_replacement_affordances': TunableMapping(key_type=TunableEnumEntry(description='\n                What posture track the specified cancel replacement affordance will run for.\n                ', tunable_type=postures.PostureTrackGroup, default=postures.PostureTrackGroup.BODY), value_type=TunableTuple(affordance=TunableReference(services.get_instance_manager(sims4.resources.Types.INTERACTION), description='\n                    The affordance to push instead of the default affordance when this interaction is canceled.\n                    The replacement interaction must be able to target the same target of this interaction, and is\n                    only applied when the interaction is a posture source interaction.\n                    '), target=OptionalTunable(TunableEnumEntry(description="\n                        The target of the cancel replacement affordance. If unspecified, the interaction's target will be used.\n                        ", tunable_type=ParticipantType, default=ParticipantType.Object)), always_run=Tunable(description='\n                    If checked, then this cancel replacement affordance is\n                    always going to run after this interaction cancels. In\n                    general, we want this to be unchecked because we do not want\n                    to run a cancel affordance if the next interaction in the\n                    queue can use the posture we are in. However, there are\n                    cases where we want to ensure that a posture is fully exited\n                    before re-entering an SI requiring that same postures, e.g.\n                    exploring space in the Rocket Ship fully exits the Rocket\n                    Ship posture if another Explore interaction is queued.\n                    ', tunable_type=bool, default=False))), 'privacy': OptionalTunable(description='\n            If enabled, this interaction requires privacy to run and will\n            create a privacy footprint before executing.\n            ', tunable=TunablePrivacySnippet()), 'provided_affordances': TunableList(TunableReference(services.get_instance_manager(sims4.resources.Types.INTERACTION), class_restrictions=('SuperInteraction',)), description="The list of affordances available in the pie menu of the Sim who's performing this super interaction as ParticipantType.Actor. The list should only be tuned on staged super interaction"), 'canonical_animation': OptionalTunable(TunableAnimationReference(description='\n            A reference to the canonical animation that represents all the valid\n            constraints for this SI."), description="If enabled, the constraints\n            for this SI will be the animation constraint generated from the\n            supplied animation reference"\n            ', callback=TunableAnimationReference.get_default_callback(InteractionAsmType.Canonical))), 'idle_animation': OptionalTunable(TunableAnimationReference(description='\n            A reference to an animation to play when the Sim is blocked from running other work\n            while running this interaction. When a Sim must idle to wait to run a real interaction,\n            we randomly chose from the idle behavior of all running SIs, with the basic posture\n            idle as a fallback.')), 'disable_transitions': Tunable(bool, False, description='\n            If set, the constraints for this interaction will only be used to determine\n            compatibility with other interactions and will not cause a posture transition \n            sequence to be built for this interaction. Caution: enable this only for \n            interactions that are meant to be proxies for other interactions which will get\n            pushed and then have their constraints solved for by the transition sequence!', tuning_filter=FilterTag.EXPERT_MODE), 'ignore_group_socials': Tunable(bool, True, needs_tuning=True, description='Whether Sims running this SuperInteraction should ignore group socials. This lets them make more progress on this interaction while socializing.'), 'ignore_autonomous_targeted_socials': Tunable(bool, False, needs_tuning=True, description="\n            Whether to zero-out the autonomous weight of targeted socials that target Sims in \n            this interaction from other Sims. True doesn't have any affect,\n            while false will cause other Sims to never autonomously choose to\n            run targeted socials on Sims who are running this interaction."), 'social_geometry_override': OptionalTunable(TunableTuple(social_space=TunablePolygon(description='Social space for this super interaction'), focal_point=TunableVector3(sims4.math.Vector3.ZERO(), description='Focal point when socializing in this super interaction, relative to Sim')), description="\n            The special geometry override for socialization in this super interaction. This defines\n            where the Sim's attention is focused and informs the social positioning system where\n            each Sim should stand to look most natural when interacting. Ex: we override the social\n            geometry for a Sim who is bartending to be a wider cone and be in front of the bar instead\n            of embedded within the bar. This encourages Sims to stand on the customer-side of the bar\n            to socialize with this Sim instead of coming around the back."), 'relocate_main_group': Tunable(bool, False, description="\n            The Sim's main social group should be relocated to the target area of this interaction\n            when it runs. This basically triggers rallyable-style behavior without needing complex\n            and sometimes unwanted rallyable functionality. Ex: Card Table games do this because\n            they already have a system of SimPicker-driven interaction pushing on the targets\n            and trying to use rallyable would fight with that.\n            "), 'acquire_targets_as_resource': Tunable(description='\n            If checked, all target Sims will be acquired as part of this\n            interaction.  If unchecked, this interaction can target Sims\n            without having to acquire them.\n            \n            Most interactions will want to acquire targeted Sims.  Not\n            acquiring target Sims will allow an interaction targeting other\n            Sims to run without having to wait for those Sims to become\n            available.\n            \n            Example Use Case: A Sim walks in on a privacy situation and needs\n            to play a reaction interaction with a thought bubble displaying an\n            image of the other Sim.  This interaction needs to target that Sim\n            in order to display their image, but also needs to execute\n            immediately and does not need to take control of that Sim at all.\n            ', tunable_type=bool, default=True, tuning_group=GroupNames.GENERAL, tuning_filter=FilterTag.EXPERT_MODE), 'collapsible': Tunable(description="\n            If checked any previous interaction of the same type will be\n            canceled from the queue.\n            \n            Example: Queue up 'Go Here' and queue up another 'Go Here' the\n            first go here will cancel.\n            ", tunable_type=bool, default=False, tuning_group=GroupNames.GENERAL), '_saveable': OptionalTunable(description='\n                If enabled, this interaction will be saved with the sim and\n                started back up when the sim loads back up.\n                ', tunable=TunableTuple(affordance_to_save=OptionalTunable(description="\n                        By default, we save the affordance that was on the sim\n                        to this super interaction. To override this behavior,\n                        tune the affordance to save instead.\n                        \n                        EX: If you want the Cook Pancake interaction to be\n                            saved, you have to override the affordance to save\n                            to be 'resume cooking' and then tune the target to\n                            be the crafting object.\n                        ", tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION), class_restrictions='SuperInteraction'), disabled_name='use_this_si', enabled_name='use_another_si'), target_to_save=TunableEnumEntry(description="\n                        We will get the participant from this\n                        interaction of this type and then save THAT object's id\n                        as the target of this interaction.\n                        ", tunable_type=ParticipantType, default=ParticipantType.Object)), tuning_group=GroupNames.GENERAL, tuning_filter=FilterTag.EXPERT_MODE), 'test_disallow_while_running': OptionalTunable(TunableTuple(description="\n            If enabled, interactions set must not be in the sim's si state\n            (running section of the queue) for this interaction to be available.\n            ", test_self=Tunable(description='\n                If checked, this affordance will not be available if it is in\n                the si state.\n                ', tunable_type=bool, default=False), affordances=TunableSet(description='\n                List of affordance to check.  If sim has any of the affordances\n                in the si state then this interaction will not be available.\n                ', tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION), class_restrictions=('SuperInteraction',)))), needs_tuning=True, tuning_group=GroupNames.AVAILABILITY), 'can_shoo': Tunable(bool, True, needs_tuning=True, description='\n                Whether this interaction can be canceled by the "Shoo" interaction'), 'enable_on_all_parts_by_default': Tunable(bool, False, description='\n                This interaction will be considered as supported by all parts on all objects.'), 'walk_style': OptionalTunable(TunableWalkstyle(description="\n                A walk style override to apply to the Sim during the\n                interaction's transition route.\n                Example: If we wanted Sims to run to everything they repaired,\n                the repair interactions would tune this to Run.\n                "), needs_tuning=True, tuning_group=GroupNames.ANIMATION), 'transition_asm_params': TunableList(TunableTuple(param_name=Tunable(description='\n                The name of the parameter to override in the transition ASM.\n                This is typically used if a posture ASM needs different VFX\n                to play based on some parameter than the SI can provide.\n                ', tunable_type=str, default=None), param_value=Tunable(description='\n                The value to set the provided parameter.\n                ', tunable_type=str, default=None))), '_carry_transfer_animation': OptionalTunable(TunableTuple(description='\n            A reference to an animation to play when starting this Interaction and to stop/restart\n            when this Interaction has a carryable target and is transferred to a different posture.\n            Ex: opening and closing the book on the surface needs to be hooked up here rather\n            than as part of basic content.', begin=TunableAnimationReference(), end=TunableAnimationReference()), tuning_group=GroupNames.POSTURE), 'carry_cancel_override_for_displaced_interactions': OptionalTunable(TunableReference(description='\n            If specified, this affordance will be used in place of the\n            default one for any interaction displaced by this one\n            and forced to run a carry cancel aop.\n            \n            If the displaced interaction has a custom carry cancel aop tuned,\n            it will ignore this override.\n            ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)))}
    _supported_posture_types = None
    _content_sets_cls = ContentSet.EMPTY_LINKS

    @flexproperty
    def _content_sets(cls, inst):
        return cls._content_sets_cls

    _has_visible_content_sets = False
    _teleporting = False
    CARRY_POSTURE_REPLACEMENT_AFFORDANCE = TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION), description='The replacement affordance for carry postures. Should only be changed with engineering support.')

    @classmethod
    def _tuning_loaded_callback(cls):
        if cls.basic_content is not None and cls.basic_content.content_set is not None:
            cls._content_sets_cls = cls.basic_content.content_set()
        super()._tuning_loaded_callback()
        if cls._content_sets.phase_tuning is not None and cls._content_sets.num_phases > 0:
            target_value = cls._content_sets.num_phases
            threshold = sims4.math.Threshold(target_value, operator.ge)

            def condition_factory(*args, **kwargs):
                condition = StatisticCondition(who=cls._content_sets.phase_tuning.target, stat=cls._content_sets.phase_tuning.turn_statistic, threshold=threshold, absolute=True, **kwargs)
                return condition

            cls.add_exit_condition([condition_factory])
        cls._has_visible_content_sets = any(affordance.visible for affordance in cls.all_affordances_gen())
        cls._group_size_weight = None
        if cls._party_size_weight_tuning:
            point_list = [(point.x, point.y) for point in cls._party_size_weight_tuning]
            cls._group_size_weight = sims4.math.WeightedUtilityCurve(point_list)
        cls._update_commodity_flags()
        transition_asm_params = {}
        for param_dict in cls.transition_asm_params:
            transition_asm_params[param_dict.param_name] = param_dict.param_value
        cls.transition_asm_params = transition_asm_params

    @classmethod
    def _verify_tuning_callback(cls):
        super()._verify_tuning_callback()
        for affordance in cls.all_affordances_gen():
            while affordance.allow_user_directed:
                if not affordance.display_name:
                    logger.error('Interaction {} on {} does not have a valid display name.', affordance.__name__, cls.__name__)
        if cls.subaction_selection_weight < 0:
            logger.warn('TUNING ERROR: The subaction selection weight tuning for {} has a value of {} which is less than 0.  This will be forced to 0.', cls.__name__, cls.subaction_selection_weight, owner='rez')
            cls.subaction_selection_weight = 0
        basic_content = cls.basic_content
        if basic_content is not None and (cls.provided_affordances and not basic_content.staging) and not basic_content.sleeping:
            logger.error('provided_affordances is tuned to non-staging affordance {}, which is invalid.{}', cls.__name__, cls.provided_affordances)

    @classmethod
    def has_slot_constraint(cls, *args, **kwargs):
        if cls.provided_posture_type is not None and not cls.provided_posture_type.mobile:
            return True
        return super().has_slot_constraint(*args, **kwargs)

    @classproperty
    def has_visible_content_sets(cls):
        return cls._has_visible_content_sets

    @classmethod
    def get_joinable_interaction(cls, interaction):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return interaction

    @classproperty
    def super_affordance_can_share_target(cls):
        return cls.provided_posture_type is not None or cls._super_affordance_can_share_target

    @classproperty
    def super_affordance_should_persist_held_props(cls):
        return cls._super_affordance_should_persist_held_props

    @classmethod
    def path(cls, target, context):
        pass

    @classmethod
    def potential_interactions(cls, target, context, **kwargs):
        if cls._can_rally(context):
            for aop in cls.get_rallyable_aops_gen(target, context, **kwargs):
                yield aop
        aop = cls.generate_aop(target, context, **kwargs)
        yield aop

    @classmethod
    def get_rallyable_aops_gen(cls, target, context, rally_constraint=None, **kwargs):
        if cls._can_rally(context):
            for entry in cls.rallyable:
                from interactions.base.rally_interaction import RallyInteraction
                rally_interaction = RallyInteraction.generate(cls, rally_tag=entry.tag, rally_level=0, rally_data=entry.behavior, rally_push_social=entry.push_social, rally_constraint=rally_constraint)
                for aop in rally_interaction.potential_interactions(target, context, **kwargs):
                    initiating_sim = context.sim
                    main_group = initiating_sim.get_visible_group()
                    while main_group:
                        while True:
                            for sim in main_group:
                                while initiating_sim is not sim:
                                    group_member_context = context.clone_for_sim(sim)
                                    result = ChoiceMenu.is_valid_aop(aop, group_member_context, False, user_pick_target=target)
                                    if not result:
                                        break
                            yield aop

    @classmethod
    def generate_aop(cls, target, context, **kwargs):
        return AffordanceObjectPair(cls, target, cls, None, **kwargs)

    @classmethod
    def _can_rally(cls, context):
        if not cls.rallyable:
            return False
        if context is None:
            return False
        if context.sim is None:
            return False
        main_group = context.sim.get_visible_group()
        if main_group is None or main_group.is_solo:
            return False
        if context.source == InteractionContext.SOURCE_AUTONOMY:
            return not any(sim.is_player_active() for sim in main_group)
        return True

    @classproperty
    def provided_posture_type(cls):
        return cls._provided_posture_type

    @classmethod
    def get_provided_posture_change(cls, aop):
        if cls._provided_posture_type is not None:
            return PostureOperation.BodyTransition(cls._provided_posture_type, aop)

    @classmethod
    def get_supported_posture_types(cls, posture_type_filter=None):
        supported_posture_types = {}
        for affordance in itertools.chain(cls.all_affordances_gen(), (cls,)):
            while affordance._supported_postures:
                while True:
                    for (participant_type, supported_posture_manifest) in affordance._supported_postures.items():
                        while supported_posture_manifest is not None:
                            if posture_type_filter is not None:
                                supported_posture_manifest = posture_type_filter(participant_type, supported_posture_manifest)
                            supported_posture_types_for_participant = postures.get_posture_types_supported_by_manifest(supported_posture_manifest)
                            if participant_type not in supported_posture_types:
                                supported_posture_types[participant_type] = supported_posture_types_for_participant
                            else:
                                supported_posture_types[participant_type] &= supported_posture_types_for_participant
        return supported_posture_types

    @flexmethod
    def supports_posture_state(cls, inst, posture_state, participant_type=ParticipantType.Actor, posture_type_filter=None, target=DEFAULT):
        inst_or_cls = inst if inst is not None else cls
        body = posture_state.body
        sim = posture_state.sim
        if not inst_or_cls.supports_posture_type(body.posture_type, participant_type=participant_type, posture_type_filter=posture_type_filter):
            return TestResult(False, 'Interaction does not support posture type: {}', body.posture_type)
        interaction_constraint = inst_or_cls.constraint_intersection(sim=sim, target=target, posture_state=None, participant_type=participant_type)
        if not interaction_constraint.valid:
            return TestResult(False, 'Interaction is incompatible with itself.')
        interaction_constraint = inst_or_cls.apply_posture_state_and_interaction_to_constraint(posture_state, interaction_constraint, participant_type=participant_type, invalid_expected=True)
        if not posture_state.compatible_with_pre_resolve(interaction_constraint):
            return TestResult(False, "Posture {}'s constraints are not compatible with {}'s constraints even before applying posture.", posture_state, inst)
        if not interaction_constraint.valid:
            return TestResult(False, "Interaction's constraint doesn't support body posture: {} and {}", interaction_constraint, body)
        return TestResult.TRUE

    @classmethod
    def supports_posture_type(cls, posture_type, participant_type=ParticipantType.Actor, posture_type_filter=None):
        if posture_type_filter is None:
            if cls._supported_posture_types is None:
                cls._cache_supported_posture_types()
            supported_posture_types = cls._supported_posture_types
        else:
            supported_posture_types = cls.get_supported_posture_types(posture_type_filter=posture_type_filter)
        supported_posture_types_for_participant = supported_posture_types.get(participant_type)
        if supported_posture_types_for_participant is not None:
            if posture_type in supported_posture_types_for_participant:
                return True
            return TestResult(False, '{} does not support posture type {}.', cls.__name__, posture_type.__name__)
        return True

    @classmethod
    def _cache_supported_posture_types(cls):
        supported_posture_type_filters = {}
        for supported_posture_type_filter in cls.supported_posture_type_filter:
            if supported_posture_type_filter.participant_type in supported_posture_type_filters:
                logger.error('{}: Multiple entries for {} specified in supported_posture_type_filter. This is invalid.', cls.__name__, supported_posture_type_filter.participant_type)
            else:
                supported_posture_type_filters[supported_posture_type_filter.participant_type] = (supported_posture_type_filter.posture_type, supported_posture_type_filter.force_carry_state)

        def _supported_posture_type_filter(participant_type, supported_posture_manifest):
            supported_posture_type_filter = supported_posture_type_filters.get(participant_type)
            if supported_posture_type_filter is not None:
                supported_posture_manifest = cls.filter_supported_postures(supported_posture_manifest, supported_posture_type_filter[0].name, supported_posture_type_filter[1] or None)
            return supported_posture_manifest

        cls._supported_posture_types = cls.get_supported_posture_types(posture_type_filter=_supported_posture_type_filter)

    @classproperty
    def teleporting(cls):
        return cls._teleporting

    @flexmethod
    def all_affordances_gen(cls, inst, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        for affordance in inst_or_cls._content_sets.all_affordances_gen(**kwargs):
            yield affordance
        if inst is not None and inst.target is not None:
            target_basic_content = inst.target.get_affordance_basic_content(inst)
            if target_basic_content is not None:
                target_content_set = target_basic_content.content_set
                if target_content_set is not None:
                    while True:
                        for affordance in target_content_set().all_affordances_gen(**kwargs):
                            yield affordance

    @flexmethod
    def has_affordances(cls, inst):
        inst_or_cls = inst if inst is not None else cls
        if inst_or_cls._content_sets.has_affordances():
            return True
        if inst is not None and inst.target is not None:
            target_basic_content = inst.target.get_affordance_basic_content(inst)
            if target_basic_content is not None:
                target_content_set = target_basic_content.content_set
                if target_content_set is not None and target_content_set().has_affordances():
                    return True
        return False

    @classmethod
    def should_autonomy_forward_to_inventory(cls):
        return False

    @classmethod
    def contains_stat(cls, stat):
        if super().contains_stat(stat):
            return True
        for affordance in cls.all_affordances_gen():
            while affordance.contains_stat(stat):
                return True
        return False

    @classmethod
    def _test(cls, target, context, **interaction_parameters):
        if cls.test_disallow_while_running is None:
            return TestResult.TRUE
        test_self = cls.test_disallow_while_running.test_self
        cls_interaction_type = cls.get_interaction_type()
        for si in context.sim.si_state:
            si_affordance = si.affordance
            while test_self and (si_affordance.get_interaction_type() is cls_interaction_type or si_affordance in cls.test_disallow_while_running.affordances):
                if 'interaction_starting' in interaction_parameters:
                    is_starting = interaction_parameters['interaction_starting']
                else:
                    is_starting = False
                if not (si.target is target and is_starting):
                    return TestResult(False, 'Currently running interaction')
                if si.target is not None:
                    if si.target.is_part and si.target.part_owner is target:
                        if not is_starting:
                            return TestResult(False, 'Currently running interaction')
        return TestResult.TRUE

    @classmethod
    def _is_linked_to(cls, super_affordance):
        if cls.super_affordance_compatibility is not None and cls.super_affordance_compatibility(super_affordance):
            return True
        return False

    @classmethod
    def consumes_object(cls):
        for affordance in cls.all_affordances_gen():
            while affordance.consumes_object():
                return True
        return False

    @flexmethod
    def is_linked_to(cls, inst, super_affordance):
        inst_or_cls = inst if inst is not None else cls
        if inst_or_cls.provided_posture_type is not None and (inst_or_cls.provided_posture_type.IS_BODY_POSTURE and super_affordance.provided_posture_type is not None) and super_affordance.provided_posture_type.IS_BODY_POSTURE:
            return False
        if inst_or_cls.provided_posture_type is not None and super_affordance.provided_posture_type is None:
            return cls._is_linked_to(super_affordance)
        if super_affordance.provided_posture_type is not None and inst_or_cls.provided_posture_type is None:
            return super_affordance._is_linked_to(cls)
        return cls._is_linked_to(super_affordance.affordance) and super_affordance._is_linked_to(cls)

    @flexmethod
    def _constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        if inst is not None and inst.is_finishing:
            return
        inst_or_cls = inst if inst is not None else cls
        found_constraint = False
        for constraint in super(SuperInteraction, inst_or_cls)._constraint_gen(sim, inst_or_cls.get_constraint_target(target), participant_type=participant_type):
            found_constraint = True
            yield constraint
        if inst is not None and inst.sim.posture.source_interaction is inst:
            slot_constraint = inst.sim.posture.slot_constraint
            if slot_constraint is not None:
                yield slot_constraint
        if target is not None and target.additional_interaction_constraints is not None:
            while True:
                for tuned_additional_constraint in target.additional_interaction_constraints:
                    constraint = tuned_additional_constraint['constraint']
                    affordance_links = tuned_additional_constraint['affordance_links']
                    found_constraint = True
                    while affordance_links is None or affordance_links(cls):
                        if constraint is not None:
                            created_constraint = target.get_created_constraint(constraint)
                            if created_constraint is not None:
                                yield created_constraint
        if not found_constraint:
            for affordance in inst_or_cls.all_affordances_gen():
                for constraint in affordance.constraint_gen(sim, inst_or_cls.get_constraint_target(target), participant_type=participant_type):
                    yield constraint

    @property
    def targeted_carryable(self):
        carry_target = self.carry_target or self.target
        if carry_target is None or carry_target.carryable_component is None:
            carry_target = self.create_target
        return carry_target

    @property
    def combined_posture_preferences(self):
        if self.combinable_interactions and self.combinable_interactions != self.get_combinable_interactions_with_safe_carryables():
            return postures.transition_sequence.PosturePreferencesData(False, False, False, False, {})
        return self.posture_preferences

    @property
    def combined_posture_target_preference(self):
        if self.combinable_interactions and self.combinable_interactions != self.get_combinable_interactions_with_safe_carryables():
            return self.DEFAULT_POSTURE_TARGET_PREFERENCES
        return self.posture_target_preference

    def remove_self_from_combinable_interactions(self):
        if self.combinable_interactions:
            self.combinable_interactions.discard(self)
            if len(self.combinable_interactions) == 1:
                self.combinable_interactions.clear()

    def test_sistate_compatibility(self):
        force_inertial_sis = self.posture_preferences.require_current_constraint or self.is_adjustment_interaction()
        return self.sim.si_state.test_compatibility(self, force_concrete=True, force_inertial_sis=force_inertial_sis)

    def on_other_si_phase_change(self, si):
        if self.transition is None or self.transition.running:
            return
        if self.is_related_to(si):
            return
        if not self.transition.get_sims_with_invalid_paths():
            included_sis = self.transition.get_included_sis()
            if si not in included_sis:
                return
        if self.transition is not None:
            self.transition.reset_all_progress()

    def _generate_connectivity(self, ignore_all_other_sis=False):
        if self.transition is None or self.transition.ignore_all_other_sis != ignore_all_other_sis:
            self.transition = postures.transition_sequence.TransitionSequenceController(self, ignore_all_other_sis=ignore_all_other_sis)
        if self.transition.running:
            return
        was_locked = self.is_required_sims_locked()
        if not was_locked:
            self.refresh_and_lock_required_sims()
        self.transition.compute_transition_connectivity()
        if not was_locked:
            self.unlock_required_sims()

    def get_sims_with_invalid_paths(self):
        if self.is_finishing or self._pipeline_progress >= PipelineProgress.RUNNING:
            return set()
        if self.transition is not None and self.transition.running:
            return set()
        self._generate_connectivity()
        if self.is_finishing:
            return set()
        return self.transition.get_sims_with_invalid_paths()

    def _estimate_distance_cache_key(self):
        required_sims = frozenset(self.required_sims())
        all_potentially_included_sis = frozenset((si, si.is_guaranteed) for sim in required_sims for si in sim.si_state if not si.is_finishing)
        return (self.constraint_intersection(posture_state=None), self.super_affordance_compatibility, self.should_rally, self.sim, required_sims, all_potentially_included_sis)

    @caches.cached(key=_estimate_distance_cache_key)
    def estimate_distance(self):
        self._generate_connectivity()
        return self.transition.estimate_distance()

    def estimate_distance_ignoring_other_sis(self):
        self._generate_connectivity(ignore_all_other_sis=True)
        try:
            result = self.transition.estimate_distance()
        finally:
            self.transition = None
        return result

    @classmethod
    def get_affordance_weight_from_group_size(cls, party_size):
        if cls._group_size_weight:
            return cls._group_size_weight.get(party_size)
        logger.error('Attempting to call get_affordance_weight_from_group_size() on an affordance with no weight curve.', owner='rez')
        return 1

    def __init__(self, aop, context, *args, exit_functions=(), force_inertial=False, additional_post_run_autonomy_commodities=None, cancel_incompatible_with_posture_on_transition_shutdown=True, disable_saving=False, **kwargs):
        StageControllerElement.__init__(self, context.sim)
        Interaction.__init__(self, aop, context, *args, **kwargs)
        self._interactions = weakref.WeakSet()
        self._exit_functions = []
        for exit_fn in exit_functions:
            self.add_exit_function(exit_fn)
        self._availability_handles = []
        self._post_guaranteed_autonomy_element = None
        self._lifetime_state = LifetimeState.INITIAL
        self._force_inertial = force_inertial
        self._guaranteed_watcher_active = 0
        self.guaranteed_locks = {}
        self._pre_exit_behavior_done = False
        self._outfit_priority_id = None
        self._rejected_account_id_requests = []
        self._cancel_deferred = None
        self._has_pushed_cancel_aop = set()
        self.disable_cancel_by_posture_change = False
        self.additional_post_run_autonomy_commodities = additional_post_run_autonomy_commodities
        self._in_cancel = False
        self._transition = None
        self.owning_transition_sequences = set()
        self.combinable_interactions = WeakSet()
        self._carry_transfer_end_required = False
        self._cancel_incompatible_with_posture_on_transition_shutdown = cancel_incompatible_with_posture_on_transition_shutdown
        self.target_in_inventory_when_queued = False
        self._disable_saving = disable_saving

    @property
    def saveable(self):
        return self._saveable is not None and not self._disable_saving

    @property
    def transition(self):
        return self._transition

    @transition.setter
    def transition(self, value):
        if value is self.transition:
            return
        if self._transition is not None and self._transition.interaction is self:
            transition = self.transition
            transition.end_transition()
            transition.shutdown()
        self._transition = value

    @property
    def cancel_incompatible_with_posture_on_transition_shutdown(self):
        return self._cancel_incompatible_with_posture_on_transition_shutdown

    @property
    def preferred_objects(self):
        return self.context.preferred_objects

    def add_preferred_object(self, *args, **kwargs):
        self.context.add_preferred_object(*args, **kwargs)

    def add_preferred_objects(self, *args, **kwargs):
        self.context.add_preferred_objects(*args, **kwargs)

    def add_exit_function(self, exit_fn):
        self._exit_functions.append(exit_fn)

    def __str__(self):
        try:
            is_guaranteed = self.is_guaranteed()
        except:
            is_guaranteed = False
        return '{4} running {0}:{2} on {1}{3}'.format(self.super_affordance.__name__, self.target, self.id, '  (guaranteed)' if is_guaranteed else '', self.sim)

    def __repr__(self):
        return '<SI {2} id:{0} sim:{1}>'.format(self.id, self.sim, self.super_affordance.__name__)

    def log_info(self, phase, msg=None):
        from sims.sim_log import log_interaction
        log_interaction(phase, self, msg=msg)

    @property
    def phase_index(self):
        if self._content_sets.phase_tuning is not None:
            participant = self.get_participant(self._content_sets.phase_tuning.target)
            tracker = participant.get_tracker(self._content_sets.phase_tuning.turn_statistic)
            return tracker.get_int_value(self._content_sets.phase_tuning.turn_statistic)

    def is_guaranteed(self) -> bool:
        if self.guaranteed_locks:
            return True
        if self.pipeline_progress < PipelineProgress.RUNNING:
            return True
        if self.force_inertial:
            return False
        if self.has_active_cancel_replacement:
            return False
        if not self.satisfied:
            return True
        return False

    @property
    def guaranteed_watcher(self):

        def on_guaranteed_edge(was_guaranteed, is_guaranteed):
            if was_guaranteed == is_guaranteed:
                return
            if self.is_finishing:
                return
            if was_guaranteed and not is_guaranteed:
                self._on_guaranteed_to_inertial()
            elif not was_guaranteed and is_guaranteed:
                self._on_inertial_to_guaranteed()

        return EdgeWatcher(self.is_guaranteed, on_guaranteed_edge)

    def get_potential_mixer_targets(self):
        if self.target is None:
            return ()
        return (self.target,)

    def _get_required_sims(self, *args, **kwargs):
        sims = set()
        required_types = ParticipantType.Actor
        if self.target_type & TargetType.TARGET:
            required_types |= ParticipantType.TargetSim
        if self.target_type & TargetType.GROUP:
            required_types |= ParticipantType.Listeners
            if not self.target_type & TargetType.TARGET:
                required_types |= ParticipantType.TargetSim
        for sim in self.get_participants(required_types):
            while self.acquire_targets_as_resource or self.get_participant_type(sim) == ParticipantType.Actor:
                if sim.posture_state is None:
                    logger.error('Found a Sim with a None posture_state. Interaction: {}, Sim: {}', self, sim)
                sims.add(sim)
                if sim.posture.multi_sim:
                    linked_sim = sim.posture.linked_sim
                    if linked_sim is not None:
                        sims.add(linked_sim)
        return sims

    def get_combinable_interactions_with_safe_carryables(self):
        if not self.combinable_interactions:
            return self.combinable_interactions
        combined_carry_targets = set()
        carry_target = self.targeted_carryable
        if carry_target is not None:
            combined_carry_targets.add(carry_target)
        valid_combinables = WeakSet()
        valid_combinables.add(self)
        for combinable in self.combinable_interactions:
            if combinable is self:
                pass
            combinable_carry = combinable.targeted_carryable
            if combinable_carry is not None and combinable_carry not in combined_carry_targets:
                if len(combined_carry_targets) > 0:
                    pass
                combined_carry_targets.add(combinable_carry)
            valid_combinables.add(combinable)
        return valid_combinables

    def get_idle_behavior(self):
        if self.idle_animation is None:
            return
        return self.idle_animation(self)

    def _pre_perform(self):
        self._setup_phase_tuning()
        if self.staging:
            with self.guaranteed_watcher:
                result = super()._pre_perform()
        else:
            result = super()._pre_perform()
        if self.sim.get_autonomy_state_setting() == autonomy.settings.AutonomyState.MEDIUM and self.is_user_directed:
            self.force_exit_on_inertia = True
        self._check_if_push_affordance_on_run()
        if self.source != InteractionContext.SOURCE_POSTURE_GRAPH and self.source != InteractionContext.SOURCE_SOCIAL_ADJUSTMENT:
            self._update_autonomy_timer()
        self.add_exit_function(self.send_end_progress)
        return result

    def _check_if_push_affordance_on_run(self):
        if not self.staging:
            return
        push_affordance_on_run = self.basic_content.push_affordance_on_run
        if push_affordance_on_run is None:
            return
        push_affordance = push_affordance_on_run.affordance
        affordance_target = self.get_participant(push_affordance_on_run.target) if push_affordance_on_run.target is not None else None
        push_kwargs = {}
        if self.is_social and push_affordance.is_social:
            push_kwargs['social_group'] = self.social_group
        for actor in self.get_participants(push_affordance_on_run.actor):
            if actor is self.sim:
                context = self.context.clone_for_concurrent_context()
            else:
                context = self.context.clone_for_sim(actor)
            for aop in push_affordance.potential_interactions(affordance_target, context, **push_kwargs):
                enqueue_result = aop.test_and_execute(context)
                if not enqueue_result:
                    pass
                interaction_pushed = enqueue_result.interaction
                while push_affordance_on_run.link_cancelling_to_affordance:
                    liability = CancelInteractionsOnExitLiability()
                    interaction_pushed.add_liability(CANCEL_INTERACTION_ON_EXIT_LIABILITY, liability)
                    liability.add_cancel_entry(actor, self)

    def _setup_phase_tuning(self):
        if self._content_sets.phase_tuning is not None and self._content_sets.num_phases > 0:
            participant = self.get_participant(self._content_sets.phase_tuning.target)
            tracker = participant.get_tracker(self._content_sets.phase_tuning.turn_statistic)
            tracker.add_statistic(self._content_sets.phase_tuning.turn_statistic)

            def remove_stat_from_target():
                participant = self.get_participant(self._content_sets.phase_tuning.target)
                tracker = participant.get_tracker(self._content_sets.phase_tuning.turn_statistic)
                tracker.remove_statistic(self._content_sets.phase_tuning.turn_statistic)

            self.add_exit_function(remove_stat_from_target)

    def _do_perform_trigger_gen(self, timeline):
        next_stage = self.next_stage()
        result = yield element_utils.run_child(timeline, next_stage)
        return result

    def _post_perform(self):
        if self.suspended:
            if self.staging:
                if gsi_handlers.interaction_archive_handlers.is_archive_enabled(self):
                    gsi_handlers.interaction_archive_handlers.archive_interaction(self.sim, self, 'Staged')
                services.get_event_manager().process_event(test_events.TestEvent.InteractionStaged, sim_info=self.sim.sim_info, interaction=self)
            return
        if not self.staging:
            self._update_autonomy_timer()
        self._lifetime_state = LifetimeState.PENDING_COMPLETE

    @property
    def visible_as_interaction(self):
        if self.started:
            return False
        return super().visible_as_interaction

    @property
    def interactions(self):
        return self._interactions

    @property
    def super_interaction(self):
        return self

    @classproperty
    def is_super(cls):
        return True

    def _set_pipeline_progress(self, value):
        with self.guaranteed_watcher:
            super()._set_pipeline_progress(value)

    def _set_satisfied(self, value):
        with self.guaranteed_watcher:
            super()._set_satisfied(value)

    @property
    def force_inertial(self):
        return self._force_inertial

    @force_inertial.setter
    def force_inertial(self, value):
        with self.guaranteed_watcher:
            self._force_inertial = value

    def queued_sub_interactions_gen(self):
        for interaction in self.sim.queue:
            while not interaction.is_super and interaction.super_interaction is self:
                yield interaction

    def can_run_subinteraction(self, interaction_or_aop, context=None):
        context = context or interaction_or_aop.context
        if interaction_or_aop.super_interaction is not self:
            return False
        return self._finisher.can_run_subinteraction()

    @property
    def canceling_incurs_opportunity_cost(self):
        return True

    def _parameterized_autonomy_helper_gen(self, timeline, commodity_info_list, context_source, context_bucket, participant_type=ParticipantType.Actor, fallback_notification=None):
        parameterized_requests = []
        for commodity_info in reversed(commodity_info_list):
            commodities = commodity_info['commodities']
            static_commodities = commodity_info['static_commodities']
            objects = None
            objects_to_ignore = None
            if commodity_info['same_target_only']:
                objects = [self.target]
            if not (self.target is not None and commodity_info['consider_same_target']):
                objects_to_ignore = [self.target]
            while commodities or static_commodities:
                request = ParameterizedAutonomyRequestInfo(commodities, static_commodities, objects, commodity_info['retain_priority'], commodity_info['retain_carry_target'], objects_to_ignore=objects_to_ignore, randomization_override=commodity_info['randomization_override'], radius_to_consider=commodity_info['radius_to_consider'], consider_scores_of_zero=commodity_info['consider_scores_of_zero'])
                parameterized_requests.append(request)
        if parameterized_requests:
            for sim in self.get_participants(participant_type):
                result = yield self._process_parameterized_autonomy_request_gen(timeline, sim, parameterized_requests, context_source, context_bucket)
                while not result:
                    if fallback_notification:
                        resolver = SingleSimResolver(sim.sim_info)
                        dialog = fallback_notification(sim, resolver)
                        dialog.text = fallback_notification.text
                        dialog.show_dialog(icon_override=(None, sim))
        return True

    def _process_parameterized_autonomy_request_gen(self, timeline, sim, parameterized_requests, context_source, context_bucket):
        context = self.context.clone_for_sim(sim)
        action_selected = False
        autonomy_service = services.autonomy_service()
        for parameterized_request in parameterized_requests:
            if parameterized_request.retain_priority:
                priority = self.priority
            else:
                priority = interactions.priority.Priority.Low
            if self.carry_target is None and self.target is not None and self.target.carryable_component is not None:
                context.carry_target = self.target
            if not parameterized_request.retain_carry_target:
                group_id = continuation_id = visual_continuation_id = None
                context.carry_target = None
            else:
                group_id = continuation_id = visual_continuation_id = DEFAULT
            if parameterized_request.randomization_override is not None:
                randomization_override = parameterized_request.randomization_override
            else:
                randomization_override = DEFAULT
            context = context.clone_for_parameterized_autonomy(self, source=context_source, priority=priority, bucket=context_bucket, group_id=group_id, continuation_id=continuation_id, visual_continuation_id=visual_continuation_id)
            autonomy_request = autonomy.autonomy_request.AutonomyRequest(sim, FullAutonomy, commodity_list=parameterized_request.commodities, static_commodity_list=parameterized_request.static_commodities, object_list=parameterized_request.objects, ignored_object_list=parameterized_request.objects_to_ignore, affordance_list=parameterized_request.affordances, apply_opportunity_cost=False, is_script_request=True, context=context, si_state_view=sim.si_state, limited_autonomy_allowed=True, radius_to_consider=parameterized_request.radius_to_consider, consider_scores_of_zero=parameterized_request.consider_scores_of_zero, autonomy_mode_label_override='ParameterizedAutonomy')
            selected_interaction = yield autonomy_service.find_best_action_gen(timeline, autonomy_request, randomization_override=randomization_override)
            if selected_interaction is None:
                pass
            result = AffordanceObjectPair.execute_interaction(selected_interaction)
            while result:
                action_selected = True
        return action_selected

    def _get_autonomy(self, commodity_info_list, fallback_notification=None):
        if commodity_info_list:

            def _on_autonomy_gen(timeline):
                yield self._parameterized_autonomy_helper_gen(timeline, commodity_info_list, InteractionContext.SOURCE_AUTONOMY, InteractionBucketType.DEFAULT, fallback_notification=fallback_notification)

            return _on_autonomy_gen

    def _get_pre_add_autonomy(self):
        return self._get_autonomy(self.pre_add_autonomy_commodities)

    def _get_pre_run_autonomy(self):
        return self._get_autonomy(self.pre_run_autonomy_commodities)

    def _get_post_guaranteed_autonomy(self):
        return self._get_autonomy(self.post_guaranteed_autonomy_commodities)

    def _get_post_run_autonomy(self):
        post_run_commodites = list()
        fallback_notification = None
        if self.post_run_autonomy_commodities is not None:
            post_run_commodites.extend(self.post_run_autonomy_commodities.requests)
            fallback_notification = self.post_run_autonomy_commodities.fallback_notification
        if self.additional_post_run_autonomy_commodities is not None:
            post_run_commodites.extend(self.additional_post_run_autonomy_commodities)
            return self._get_autonomy(post_run_commodites, fallback_notification=fallback_notification)
        return self._get_autonomy(post_run_commodites, fallback_notification=fallback_notification)

    def prepare_gen(self, timeline, cancel_incompatible_carry_interactions=False):
        if not (cancel_incompatible_carry_interactions and self.cancel_incompatible_carry_interactions()):
            return InteractionQueuePreparationStatus.NEEDS_DERAIL
        if self.source != InteractionContext.SOURCE_POSTURE_GRAPH and self.source != InteractionContext.SOURCE_SOCIAL_ADJUSTMENT:
            self.sim.skip_autonomy(self, True)
        autonomy_element = self._get_pre_add_autonomy()
        if autonomy_element is not None:
            result = yield element_utils.run_child(timeline, autonomy_element)
            if not result:
                logger.error('Failed to run pre_add_autonomy for {}', self)
        for sim in self.get_participants(ParticipantType.AllSims):
            sim.update_related_objects(self.sim, forced_interaction=self)
        if self._run_priority is not None:
            self._priority = self._run_priority
        return InteractionQueuePreparationStatus.SUCCESS

    @classproperty
    def can_holster_incompatible_carries(cls):
        allow_holster = cls.basic_content.allow_holster if cls.basic_content is not None else None
        if allow_holster is not None:
            return allow_holster
        return cls.one_shot

    @classproperty
    def allow_holstering_of_owned_carries(cls):
        return cls.staging

    def cancel_incompatible_carry_interactions(self):
        needs_derail = False
        for (owning_interaction, _) in self.get_uncarriable_objects_gen(posture_state=None):
            while not owning_interaction.is_cancel_aop:
                if owning_interaction.sim is not self.sim:
                    needs_derail = True
                owning_interaction.cancel(FinishingType.INTERACTION_INCOMPATIBILITY, cancel_reason_msg='Incompatible with carry')
        if needs_derail:
            services.get_master_controller().set_timestamp_for_sim_to_now(self.sim)
            return False
        return True

    def excluded_posture_destination_objects(self):
        return set()

    def run_pre_transition_behavior(self):
        if self.is_user_directed:
            targets = self.get_participants(ParticipantType.AllSims)
            for sim in targets:
                sim.clear_lot_routing_restrictions_ref_count()
        return self.sim.test_for_distress_compatibility_and_run_replacement(self.interaction, self.sim)

    def enter_si_gen(self, timeline, must_enter=False, pairwise_intersection=False):
        self._lifetime_state = LifetimeState.RUNNING
        for mixer in self.all_affordances_gen():
            while mixer.lock_out_time_initial is not None:
                self.sim.set_sub_action_lockout(mixer, initial_lockout=True)
        if not SIState.add(self, must_add=must_enter, pairwise_intersection=pairwise_intersection):
            return False
        yield self.si_state.process_gen(timeline)
        yield element_utils.run_child(timeline, self._get_pre_run_autonomy())
        return True

    def on_added_to_queue(self, *args, **kwargs):
        if self.target is not None and self.target.is_in_inventory():
            self.target_in_inventory_when_queued = True
        return super().on_added_to_queue(*args, **kwargs)

    def set_as_added_to_queue(self, notify_client=True):
        added_to_queue = False
        if self.pipeline_progress == PipelineProgress.NONE:
            self.on_added_to_queue(notify_client=notify_client)
            added_to_queue = True
        return added_to_queue

    def maybe_acquire_posture_ownership(self):
        if not (self.disable_transitions or self.is_compatible_with_stand_at_none):
            if self.target is not None and self.carry_target is None and not self.target.has_component(CARRYABLE_COMPONENT):
                body_posture = self.sim.posture_state.body
                if self is not body_posture.source_interaction:
                    self.acquire_posture_ownership(body_posture)

    def run_direct_gen(self, timeline, source_interaction=None, pre_run_behavior=None, included_sis=None):
        notify_client = source_interaction is self
        added_to_queue = self.set_as_added_to_queue(notify_client=notify_client)
        result = not self.is_finishing
        if result and self.pipeline_progress < PipelineProgress.PREPARED:
            status = yield self.prepare_gen(timeline)
            if status == InteractionQueuePreparationStatus.NEEDS_DERAIL and self.transition is not None:
                self.transition.derail(DerailReason.PREEMPTED, self.sim)
                return False
            result = status != InteractionQueuePreparationStatus.FAILURE
        if result and pre_run_behavior is not None:
            result = yield element_utils.run_child(timeline, pre_run_behavior)
        if result:
            result = not self.is_finishing
        if self.running:
            return result
        if result:
            self.maybe_acquire_posture_ownership()
            if included_sis:
                for included_si in included_sis:
                    included_si.maybe_acquire_posture_ownership()
            must_enter = pre_run_behavior is not None and self.provided_posture_type is not None
            pairwise_intersection = must_enter and self is not source_interaction
            self.pipeline_progress = PipelineProgress.RUNNING
            result = yield self.enter_si_gen(timeline, must_enter=must_enter, pairwise_intersection=pairwise_intersection)
            if not result:
                self.pipeline_progress = PipelineProgress.PREPARED
                if added_to_queue:
                    self.on_removed_from_queue()
                if pre_run_behavior is not None:
                    self.sim.reset(ResetReason.RESET_ON_ERROR, self, 'Failed to enter SI State')
                self.cancel(FinishingType.INTERACTION_INCOMPATIBILITY, 'Failed to enter SI state.')
                return False
            if self.transition is not None and self.transition.interaction is self:
                self.transition._success = True
            self.sim.queue.remove_for_perform(self)
            if result:
                result = yield self.sim.queue.run_interaction_gen(timeline, self, source_interaction=source_interaction)
        elif added_to_queue:
            self.cancel(FinishingType.TRANSITION_FAILURE, 'Failed to do pre-run transition')
            self.on_removed_from_queue()
        return result

    @staticmethod
    def should_replace_posture_source_interaction(new_interaction):
        if new_interaction.simless:
            return False
        if new_interaction.sim.posture.posture_type is new_interaction.provided_posture_type and new_interaction.sim.posture.source_interaction is not new_interaction and (not new_interaction.sim.posture.multi_sim or not new_interaction.sim.posture.is_puppet):
            return True
        return False

    @property
    def is_compatible_with_stand_at_none(self):
        interaction_constraint = self.constraint_intersection(posture_state=None)
        for constraint in interaction_constraint:
            posture_state_spec = constraint.posture_state_spec
            if posture_state_spec is not None:
                break
            else:
                break
        return False
        return interaction_constraint.intersect(STAND_NO_SURFACE_CONSTRAINT).valid

    def acquire_posture_ownership(self, posture):
        if posture.target is None:
            return
        if posture.track == PostureTrack.BODY and self.is_compatible_with_stand_at_none:
            return
        if self in posture.owning_interactions:
            return
        if self.provided_posture_type is posture.posture_type:
            return
        if posture.ownable:
            self.add_liability((OWNS_POSTURE_LIABILITY, posture.track), OwnsPostureLiability(self, posture))
        posture.kill_cancel_aops()

    def _run_interaction_gen(self, timeline):
        if self.should_replace_posture_source_interaction(self):
            if not self.sim.posture.source_interaction.is_finishing:
                logger.warn("Trying to replace a Posture Interaction that isn't finishing. {}", self)
            self.sim.posture.source_interaction = self
        yield super()._run_interaction_gen(timeline)
        if self.staging:
            sequence = build_critical_section(flush_all_animations, self._stage())
            yield element_utils.run_child(timeline, sequence)
        return True

    def _setup_gen(self, timeline):
        SIState.resolve(self)
        if not self.disable_transitions and not self in self.si_state:
            logger.warn('Interaction is no longer in the SIState in _setup: {}!', self)
            return False
        self._active = True
        return True
        yield None

    def get_carry_transfer_begin_element(self):

        def start_carry(timeline):
            if not self._carry_transfer_end_required:
                animation = self._carry_transfer_animation.begin(self, enable_auto_exit=False)
                yield element_utils.run_child(timeline, animation)
                self._carry_transfer_end_required = True

        return start_carry

    def get_carry_transfer_end_element(self):

        def end_carry(timeline):
            if self._carry_transfer_end_required:
                animation = self._carry_transfer_animation.end(self, enable_auto_exit=False)
                yield element_utils.run_child(timeline, animation)
                self._carry_transfer_end_required = False

        return end_carry

    def build_basic_elements(self, *args, sequence=(), **kwargs):
        commodity_flags = set()
        for provided_affordance in self.provided_affordances:
            commodity_flags |= provided_affordance.commodity_flags
        if commodity_flags:

            def add_flags(*_, **__):
                self.sim.add_dynamic_commodity_flags(self, commodity_flags)

            def remove_flags(*_, **__):
                if self.sim is not None:
                    self.sim.remove_dynamic_commodity_flags(self)

            return build_critical_section_with_finally(add_flags, super().build_basic_elements(sequence=sequence, *args, **kwargs), remove_flags)
        enable_auto_exit = self.basic_content is None or not self.basic_content.staging
        sequence = super().build_basic_elements(enable_auto_exit=enable_auto_exit, sequence=sequence, *args, **kwargs)
        if self._carry_transfer_animation is not None:
            sequence = build_critical_section(self.get_carry_transfer_begin_element(), sequence, self.get_carry_transfer_end_element())
        basic_content = self.basic_content
        if basic_content is not None and basic_content.staging:
            sequence = build_element((self._get_autonomy(basic_content.post_stage_autonomy_commodities), sequence))
        return sequence

    def kill(self):
        if self.has_been_killed:
            return False
        on_cancel_aops = self._get_cancel_replacement_aops_contexts_postures()
        if on_cancel_aops:
            self.sim.reset(ResetReason.RESET_ON_ERROR, self, 'Interaction with cancel aop killed.')
            return False
        self._finisher.on_finishing_move(FinishingType.KILLED)
        self.trigger_hard_stop()
        self._interrupt_active_work(True, finishing_type=FinishingType.KILLED)
        self._active = False
        if self.si_state is not None:
            SIState.on_interaction_canceled(self)
        if self.queue is not None:
            self.queue.on_interaction_canceled(self)
        continuation = self.sim.find_continuation_by_id(self.id)
        if continuation is not None:
            continuation.kill()
        return True

    def _get_cancel_replacement_context_for_posture(self, posture, affordance, always_run):
        if posture is None:
            context_source = InteractionContext.SOURCE_AUTONOMY
            continuation_id = None
            priority = self.priority
        elif posture.track == PostureTrack.BODY:
            context_source = InteractionContext.SOURCE_BODY_CANCEL_AOP
            continuation_id = None
            priority = interactions.priority.Priority.Low
        else:
            context_source = InteractionContext.SOURCE_CARRY_CANCEL_AOP
            continuation_id = self.id
            priority = interactions.priority.Priority.High
        if affordance.is_basic_content_one_shot:
            run_priority = None
        else:
            run_priority = interactions.priority.Priority.Low
        bucket = InteractionBucketType.DEFAULT if always_run else InteractionBucketType.BASED_ON_SOURCE
        context = InteractionContext(self.sim, source=context_source, priority=priority, carry_target=self.carry_target, group_id=self.group_id, insert_strategy=QueueInsertStrategy.NEXT, run_priority=run_priority, continuation_id=continuation_id, bucket=bucket)
        return context

    def _get_cancel_replacement_aops_contexts_postures(self, can_transfer_ownership=True, carry_cancel_override=None):
        cancel_aops_contexts_postures = []
        if self.sim is None:
            return cancel_aops_contexts_postures
        new_carry_owner = None
        carry_target = self.carry_target or self.target
        if can_transfer_ownership and (carry_target is not None and (carry_target.carryable_component is not None and carry_target.parent is self.sim)) and not self.is_putdown:
            head_interaction = self.sim.queue.get_head()
            if head_interaction is not None and head_interaction.is_super and head_interaction is not self:
                if head_interaction.carry_target is carry_target or head_interaction.target is carry_target:
                    new_carry_owner = head_interaction
        for posture in reversed(self.sim.posture_state.aspects):
            if new_carry_owner is not None and posture.target is carry_target:
                while head_interaction not in posture.owning_interactions:
                    new_carry_owner.acquire_posture_ownership(posture)
                    if self.cancel_replacement_affordances:
                        for (posture_track_group, cancel_affordance_info) in self.cancel_replacement_affordances.items():
                            if not posture_track_group & posture.track:
                                pass
                            cancel_affordance = cancel_affordance_info.affordance
                            if cancel_affordance_info.target is None:
                                target = None
                            else:
                                target = self.get_participant(cancel_affordance_info.target)
                                if target is not None and target.is_part:
                                    target = target.part_owner
                            always_run = cancel_affordance_info.always_run
                            break
                        cancel_affordance = None
                        target = None
                        always_run = False
                    else:
                        cancel_affordance = None
                        target = None
                        always_run = False
                    if cancel_affordance is not None:
                        cancel_replacement_aop = AffordanceObjectPair(cancel_affordance, target, cancel_affordance, None)
                        context = self._get_cancel_replacement_context_for_posture(posture, cancel_affordance, always_run)
                        cancel_aops_contexts_postures.append((cancel_replacement_aop, context, posture))
                    if posture.last_owning_interaction(self) and posture.source_interaction is not None and posture.source_interaction is not self:
                        cancel_aops = posture.source_interaction._get_cancel_replacement_aops_contexts_postures(can_transfer_ownership=False, carry_cancel_override=carry_cancel_override)
                        cancel_aops_contexts_postures.extend(cancel_aops)
                    if cancel_affordance is not None:
                        cancel_replacement_aop = AffordanceObjectPair(cancel_affordance, target, cancel_affordance, None)
                        replacement_aop = cancel_replacement_aop
                    elif posture.track == PostureTrack.BODY:
                        replacement_aop = posture_graph.SIM_DEFAULT_AOP
                    else:
                        while posture.target is not None and posture.target.valid_for_distribution and posture.target in self.get_participants(ParticipantType.All):
                            affordance = self.CARRY_POSTURE_REPLACEMENT_AFFORDANCE if carry_cancel_override is None else carry_cancel_override
                            replacement_aop = AffordanceObjectPair(affordance, posture.target, affordance, None)
                            context = self._get_cancel_replacement_context_for_posture(posture, replacement_aop.affordance, always_run)
                            cancel_aops_contexts_postures.append((replacement_aop, context, posture))
                    context = self._get_cancel_replacement_context_for_posture(posture, replacement_aop.affordance, always_run)
                    cancel_aops_contexts_postures.append((replacement_aop, context, posture))
            if self.cancel_replacement_affordances:
                for (posture_track_group, cancel_affordance_info) in self.cancel_replacement_affordances.items():
                    if not posture_track_group & posture.track:
                        pass
                    cancel_affordance = cancel_affordance_info.affordance
                    if cancel_affordance_info.target is None:
                        target = None
                    else:
                        target = self.get_participant(cancel_affordance_info.target)
                        if target is not None and target.is_part:
                            target = target.part_owner
                    always_run = cancel_affordance_info.always_run
                    break
                cancel_affordance = None
                target = None
                always_run = False
            else:
                cancel_affordance = None
                target = None
                always_run = False
            if cancel_affordance is not None:
                cancel_replacement_aop = AffordanceObjectPair(cancel_affordance, target, cancel_affordance, None)
                context = self._get_cancel_replacement_context_for_posture(posture, cancel_affordance, always_run)
                cancel_aops_contexts_postures.append((cancel_replacement_aop, context, posture))
            if posture.last_owning_interaction(self) and posture.source_interaction is not None and posture.source_interaction is not self:
                cancel_aops = posture.source_interaction._get_cancel_replacement_aops_contexts_postures(can_transfer_ownership=False, carry_cancel_override=carry_cancel_override)
                cancel_aops_contexts_postures.extend(cancel_aops)
            if cancel_affordance is not None:
                cancel_replacement_aop = AffordanceObjectPair(cancel_affordance, target, cancel_affordance, None)
                replacement_aop = cancel_replacement_aop
            elif posture.track == PostureTrack.BODY:
                replacement_aop = posture_graph.SIM_DEFAULT_AOP
            else:
                while posture.target is not None and posture.target.valid_for_distribution and posture.target in self.get_participants(ParticipantType.All):
                    affordance = self.CARRY_POSTURE_REPLACEMENT_AFFORDANCE if carry_cancel_override is None else carry_cancel_override
                    replacement_aop = AffordanceObjectPair(affordance, posture.target, affordance, None)
                    context = self._get_cancel_replacement_context_for_posture(posture, replacement_aop.affordance, always_run)
                    cancel_aops_contexts_postures.append((replacement_aop, context, posture))
            context = self._get_cancel_replacement_context_for_posture(posture, replacement_aop.affordance, always_run)
            cancel_aops_contexts_postures.append((replacement_aop, context, posture))
        return cancel_aops_contexts_postures

    def _on_cancel_aop_canceled(self, posture):
        self._has_pushed_cancel_aop.discard(posture)

    def _try_exit_via_cancel_aop(self, carry_cancel_override=None):
        if self.sim.is_being_destroyed:
            return False
        on_cancel_aops_contexts_postures = self._get_cancel_replacement_aops_contexts_postures(carry_cancel_override=carry_cancel_override)
        if not on_cancel_aops_contexts_postures:
            return self.sim.posture_state.is_source_interaction(self)
        prevent_from_canceling = False
        for (on_cancel_aop, context, posture) in on_cancel_aops_contexts_postures:
            if on_cancel_aop.affordance is None:
                pass
            if self in self.sim.si_state and (posture.source_interaction is self or posture is self.sim.posture):
                prevent_from_canceling = self.staging
            if not self.sim.queue.needs_cancel_aop(on_cancel_aop, context):
                pass
            if posture in self._has_pushed_cancel_aop:
                pass
            cancel_aop_result = on_cancel_aop.test(context)
            if not cancel_aop_result:
                logger.warn('Failed to push the cancelation replacement effect ({} -> {}) for {}: {}.', posture, on_cancel_aop, self, cancel_aop_result)
                self.sim.reset(ResetReason.RESET_EXPECTED, self, 'Failed to push cancel aop:{}.'.format(on_cancel_aop))
            execute_result = on_cancel_aop.interaction_factory(context)
            cancel_interaction = execute_result.interaction
            if context.source == InteractionContext.SOURCE_BODY_CANCEL_AOP:
                cancel_interaction.add_liability(CANCEL_AOP_LIABILITY, CancelAOPLiability(self.sim, cancel_interaction, self, self._on_cancel_aop_canceled, posture))
            result = AffordanceObjectPair.execute_interaction(cancel_interaction)
            while result:
                self._has_pushed_cancel_aop.add(posture)
        return prevent_from_canceling

    @staticmethod
    @contextmanager
    def cancel_deferred(sis):
        for si in sis:
            while si is not None:
                si._cancel_deferred = []
        try:
            yield None
        finally:
            for si in sis:
                while not si is None:
                    if si._cancel_deferred is None:
                        pass
                    for (args, kwargs) in si._cancel_deferred:
                        si._cancel(*args, **kwargs)
                    si._cancel_deferred = None

    def _cancel_eventually(self, *args, immediate=False, **kwargs):
        if not self.is_finishing and self._cancel_deferred is not None and not immediate:
            self.log_info('CancelEventually', msg='{}/{}'.format(args, kwargs))
            self._cancel_deferred.append((args, kwargs))
            return False
        return self._cancel(*args, **kwargs)

    def _cancel(self, finishing_type, cancel_reason_msg, notify_UI=False, lifetime_state=None, log_id=None, ignore_must_run=False, carry_cancel_override=None):
        if self._in_cancel:
            return False
        self.log_info('Cancel', msg='finishing_type={}, notify_UI={}, lifetime_state={}, log_id={}, cancel_reason_msg={}, ignore_must_run={}, user_cancel={}'.format(finishing_type, notify_UI, lifetime_state, log_id, cancel_reason_msg, ignore_must_run, self.user_canceled))
        try:
            self._in_cancel = True
            if self.must_run and not ignore_must_run:
                return False
            if self.is_finishing:
                return False
            self._finisher.on_pending_finishing_move(finishing_type)
            self.force_inertial = True
            if self.combinable_interactions:
                for combinable_interaction in set(self.combinable_interactions):
                    combinable_interaction.remove_self_from_combinable_interactions()
                    while combinable_interaction.transition is not None:
                        combinable_interaction.transition.derail(DerailReason.PROCESS_QUEUE, self.sim)
            if notify_UI and not self.is_finishing_naturally and not self._finisher.has_pending_natural_finisher:
                self.sim.ui_manager.set_interaction_canceled(self.id, True)
            if self.sim is not None and self.sim.posture.source_interaction is self:
                while True:
                    for owning_interaction in tuple(self.sim.posture.owning_interactions):
                        while owning_interaction is not self:
                            owning_interaction.cancel(finishing_type, cancel_reason_msg)
            if self._interrupt_active_work(finishing_type=finishing_type, cancel_reason_msg=cancel_reason_msg) and not self._try_exit_via_cancel_aop(carry_cancel_override=carry_cancel_override):
                self._active = False
                if finishing_type is not None:
                    self._finisher.on_finishing_move(finishing_type)
                if self.si_state is not None:
                    SIState.on_interaction_canceled(self)
                if self.queue is not None:
                    self.queue.on_interaction_canceled(self)
                for transition in self.owning_transition_sequences:
                    transition.on_owned_interaction_canceled(self)
                if self.sim is not None:
                    for posture in self.sim.posture_state.aspects:
                        while self in posture.owning_interactions and (len(posture.owning_interactions) == 1 and posture.source_interaction is not None) and posture.source_interaction is not self:
                            posture.source_interaction.cancel(FinishingType.SI_FINISHED, cancel_reason_msg='Posture Owning Interaction Canceled', carry_cancel_override=carry_cancel_override)
                if log_id is not None:
                    self.log_info(log_id, msg=cancel_reason_msg)
                if lifetime_state is not None:
                    self._lifetime_state = lifetime_state
                self._on_cancelled_callbacks(self)
                self._on_cancelled_callbacks.clear()
                return True
        except HardStopError:
            raise
        except:
            logger.exception('Exception during SI.cancel {}, cancel_reason_msg is {}:', self, cancel_reason_msg)
            logger.callstack('Invoke Callstack', level=sims4.log.LEVEL_ERROR)
            self._lifetime_state = LifetimeState.CANCELED
            if self._finisher is not None:
                self._finisher.on_finishing_move(FinishingType.KILLED)
            sim = self.sim
            if sim.ui_manager is not None:
                sim.ui_manager.set_interaction_canceled(self.id, True)
            sim.reset(ResetReason.RESET_EXPECTED, self, 'Exception during SI.cancel. {}'.format(cancel_reason_msg))
        finally:
            self._update_autonomy_timer_on_cancel(finishing_type)
            self._in_cancel = False
        return False

    def displace(self, displaced_by, **kwargs):
        if (displaced_by.source == InteractionContext.SOURCE_BODY_CANCEL_AOP or displaced_by.source == InteractionContext.SOURCE_CARRY_CANCEL_AOP) and self.transition is not None and not self.transition.succeeded:
            from postures.transition_sequence import DerailReason
            actor = self.get_participant(ParticipantType.Actor)
            self.transition.derail(DerailReason.DISPLACE, actor)
            return False
        notify_ui = True
        if self.source == InteractionContext.SOURCE_AUTONOMY and displaced_by.source == InteractionContext.SOURCE_AUTONOMY:
            notify_ui = False
        if displaced_by.is_super:
            carry_cancel_override = displaced_by.carry_cancel_override_for_displaced_interactions
        else:
            carry_cancel_override = None
        return self._cancel_eventually(FinishingType.DISPLACED, cancel_reason_msg='Interaction Displaced', notify_UI=notify_ui, log_id='Displace_SI', carry_cancel_override=carry_cancel_override)

    def _auto_complete(self, force_satisfy=False):
        if force_satisfy:
            self.satisfied = True
            self.force_inertial = True
        return self._cancel_eventually(FinishingType.NATURAL, cancel_reason_msg='Interaction Auto Completed', log_id='Complete_SI', ignore_must_run=True)

    def cancel(self, finishing_type, cancel_reason_msg, **kwargs):
        if gsi_handlers.interaction_archive_handlers.is_archive_enabled(self):
            gsi_handlers.interaction_archive_handlers.add_cancel_callstack(self)
        return self._cancel_eventually(finishing_type, cancel_reason_msg, notify_UI=True, lifetime_state=LifetimeState.CANCELED, log_id='Cancel_SI', **kwargs)

    def _interrupt_active_work(self, kill=False, finishing_type=None, cancel_reason_msg=None):
        super()._interrupt_active_work(kill=kill, finishing_type=finishing_type)
        transition_canceled = True
        if self.transition is not None:
            if kill:
                self.transition.cancel(finishing_type=finishing_type, cancel_reason_msg=cancel_reason_msg, si_to_cancel=self)
            else:
                transition_canceled = self.transition.cancel(finishing_type=finishing_type, cancel_reason_msg=cancel_reason_msg, si_to_cancel=self)
        if self._post_guaranteed_autonomy_element is not None:
            if kill:
                self._post_guaranteed_autonomy_element.trigger_hard_stop()
            else:
                self._post_guaranteed_autonomy_element.trigger_soft_stop()
        return transition_canceled

    def on_reset(self):
        if self._finisher.has_been_reset:
            return
        if self.transition is not None:
            self.transition.on_reset()
        if self.owning_transition_sequences:
            owning_transitions = self.owning_transition_sequences.copy()
            for transition in owning_transitions:
                transition.on_reset()
        super().on_reset()
        SIState.remove_immediate(self)

    def stop(self):
        logger.callstack('Calling si.stop()', level=sims4.log.LEVEL_ERROR)

    def _exit(self, timeline, allow_yield):
        if not self.affordance.immediate:
            pass
        exit_functions = self._exit_functions
        self._exit_functions = None
        exit_si_element = None
        self._lifetime_state = LifetimeState.EXITED
        if allow_yield:
            while self.started and not self.stopped:
                exit_si_element = self.next_stage()
                yield element_utils.run_child(timeline, exit_si_element)
        first_exception = None
        for exit_function in exit_functions:
            try:
                exit_function()
            except BaseException as exc:
                if first_exception is not None:
                    logger.exception('Suppressing duplicate exception when processing exit behavior {}', exit_function, exc=exc)
                else:
                    first_exception = exc
                allow_yield = False
        if first_exception is not None:
            raise first_exception
        if allow_yield and not self.user_canceled:
            post_run_autonomy_requests = self._get_post_run_autonomy()
            if post_run_autonomy_requests is not None:
                yield element_utils.run_child(timeline, post_run_autonomy_requests)

    def _update_autonomy_timer_on_cancel(self, finishing_type):
        if self.sim is None:
            return
        self.sim.skip_autonomy(self, False)
        if finishing_type == FinishingType.USER_CANCEL or self.is_user_directed:
            self._update_autonomy_timer(force_user_directed=True)
        else:
            self._update_autonomy_timer()

    def add_default_outfit_priority(self):
        if self.outfit_priority is not None and self.outfit_priority.step_to_add == OutfitPriorityPoint.OnSIState:
            self._outfit_priority_id = self.sim.sim_info.sim_outfits.add_default_outfit_priority(self, self.outfit_priority.outfit_change_reason, self.outfit_priority.priority)

    def remove_default_outfit_priority(self):
        if self._outfit_priority_id is not None:
            self.sim.sim_info.sim_outfits.remove_default_outfit_priority(self._outfit_priority_id)

    def on_transferred_to_si_state(self, participant_type=ParticipantType.Actor):
        self.log_info('Process_SI')
        if self.pipeline_progress == PipelineProgress.NONE:
            self._entered_pipeline()
        if self.staging:
            self.pipeline_progress = PipelineProgress.STAGED
        if self.should_visualize_interaction_for_sim(participant_type):
            sim = self.get_participant(participant_type)
            sim.ui_manager.transferred_to_si_state(self)
        self.remove_self_from_combinable_interactions()

    def on_removed_from_si_state(self, participant_type=ParticipantType.Actor):
        self.log_info('Remove_SI')
        if self.should_visualize_interaction_for_sim(participant_type):
            sim = self.get_participant(participant_type)
            sim.ui_manager.remove_from_si_state(self)
        if participant_type & ParticipantType.Actor:
            self._exited_pipeline()

    def _entered_pipeline(self):
        super()._entered_pipeline()
        self.add_default_outfit_priority()

    def _exited_pipeline(self):
        self.slot_manifest = None
        for sim in self.required_sims():
            sim.queue.clear_must_run_next_interaction(self)
        super()._exited_pipeline()
        self.remove_default_outfit_priority()
        self.refresh_constraints()
        if self.transition is not None and (not self.owning_transition_sequences or self.transition not in self.owning_transition_sequences):
            self.transition.shutdown()
            self.transition.end_transition()
            self.transition = None
        if self.owning_transition_sequences:
            owning_transitions = self.owning_transition_sequences.copy()
            self.owning_transition_sequences.clear()
            for transition in owning_transitions:
                transition.shutdown()
                transition.end_transition()
                transition.interaction.transiton = None
        for sim in self.get_participants(ParticipantType.AllSims):
            if sim.posture_state is not None:
                sim.posture_state.remove_constraint(self)
            sim.update_related_objects(self.sim)

    def disallows_full_autonomy(self, disable_full_autonomy=DEFAULT):
        if disable_full_autonomy is DEFAULT:
            disable_full_autonomy = self.disable_autonomous_multitasking_if_user_directed
        if disable_full_autonomy and self.is_user_directed and self.is_guaranteed():
            return True
        return False

    def do_post_guaranteed_autonomy(self):

        def _post_guaranteed_autonomy_gen(timeline):
            sim = self.sim
            if sim is not None and sim.queue is not None:
                for interaction in sim.queue:
                    while interaction.priority is interactions.priority.Priority.High:
                        return
                element = self._get_post_guaranteed_autonomy()
                if element is not None:
                    yield element_utils.run_child(timeline, element)
                self._post_guaranteed_autonomy_element = None

        self._post_guaranteed_autonomy_element = elements.GeneratorElement(_post_guaranteed_autonomy_gen)
        self.sim.schedule_element(services.time_service().sim_timeline, self._post_guaranteed_autonomy_element)

    def _on_guaranteed_to_inertial(self):
        self.queue.on_si_phase_change(self)
        if self.affordance.force_autonomy_on_inertia:
            self.sim.run_full_autonomy_next_ping()
        if self.active and self.force_exit_on_inertia:
            self._auto_complete()
        if not self._pre_exit_behavior_done:
            self._pre_exit_behavior_done = True
            if self.sim.is_simulating:
                self.do_post_guaranteed_autonomy()

    def _on_inertial_to_guaranteed(self):
        self.apply_posture_state(self.sim.posture_state)
        self.queue.on_si_phase_change(self)

    @property
    def pending_complete(self):
        return self._lifetime_state == LifetimeState.PENDING_COMPLETE or self._lifetime_state == LifetimeState.CANCELED

    @property
    def will_exit(self):
        if self.started and self.is_basic_content_one_shot:
            return True
        return self._lifetime_state >= LifetimeState.PENDING_COMPLETE or self.is_finishing

    def process_events(self):
        if self.pending_complete:
            self._auto_complete(True)

    def completed_by_mixer(self):
        self._lifetime_state = LifetimeState.PENDING_COMPLETE

    def set_to_user_driven(self):
        with self.guaranteed_watcher:
            while self.source != InteractionContext.SOURCE_PIE_MENU:
                self.context.source = InteractionContext.SOURCE_PIE_MENU
                new_priority = interactions.priority.Priority.High
                if self.priority < new_priority:
                    self.priority = new_priority
                while self.staging:
                    self.refresh_conditional_actions()

    def attach_interaction(self, interaction):
        liability = self.get_liability(CANCEL_INTERACTION_ON_EXIT_LIABILITY)
        if liability is None:
            liability = CancelInteractionsOnExitLiability()
            self.add_liability(CANCEL_INTERACTION_ON_EXIT_LIABILITY, liability)
        liability.add_cancel_entry(interaction.context.sim, interaction)
        if interaction.priority > self.priority:
            self.priority = interaction.priority
        if interaction not in self._interactions:
            self._interactions.add(interaction)
            if self.si_state is not None:
                self.si_state.notify_dirty()

    def detach_interaction(self, interaction):
        self._interactions.remove(interaction)
        liability = self.get_liability(CANCEL_INTERACTION_ON_EXIT_LIABILITY)
        if liability is not None:
            liability.remove_cancel_entry(interaction.sim, interaction)

    def set_stat_asm_parameter(self, asm, actor_name, sim):
        if self.animation_stat is not None:
            animation_stat = sim.get_stat_instance(self.animation_stat, add=True)
            if animation_stat is not None:
                (asm_param_name, asm_param_value) = animation_stat.get_asm_param()
                if asm_param_name is not None and asm_param_value is not None:
                    asm.set_actor_parameter(actor_name, sim, asm_param_name, asm_param_value)

    def request_rejected(self, initiating_sim):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        if initiating_sim.account_id in self._rejected_account_id_requests:
            return
        self._rejected_account_id_requests.append(initiating_sim.account_id)

    def has_sim_been_rejected(self, initiating_sim):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return initiating_sim.account_id in self._rejected_account_id_requests

    def perform_gen(self, timeline):
        result = yield Interaction.perform_gen(self, timeline)
        if self.one_shot:
            self.satisfied = True
        if not self.is_guaranteed() and (self.force_exit_on_inertia or self.one_shot):
            self._auto_complete()
        return result

    def _get_resource_instance_hash(self):
        if self._saveable.affordance_to_save is not None:
            return self._saveable.affordance_to_save.guid64
        return self.guid64

    def _get_save_object(self):
        save_object = self.get_participant(self._saveable.target_to_save)
        return save_object

    def fill_save_data(self, save_data):
        save_data.interaction = self._get_resource_instance_hash()
        save_target = self._get_save_object()
        if save_target is not None:
            save_data.target_id = save_target.id
            if save_target.is_part:
                save_data.target_part_group_index = save_target.part_group_index
        save_data.source = self.context.source
        save_data.priority = self.context.priority
        if self.start_time is not None:
            save_data.start_time = self.start_time.absolute_ticks()

    def pre_route_clothing_change(self, do_spin=True, **kwargs):
        return self.get_on_route_change(do_spin=do_spin, **kwargs)

    def get_on_route_change(self, **kwargs):
        if self.outfit_change is not None and self.outfit_change.on_route_change is not None:
            return self.sim.sim_info.sim_outfits.get_change(self, self.outfit_change.on_route_change, **kwargs)

    def get_on_route_outfit(self):
        if self.outfit_change is not None and self.outfit_change.on_route_change is not None:
            return self.sim.sim_info.sim_outfits.get_outfit_for_clothing_change(self, self.outfit_change.on_route_change)

    def get_tuned_outfit_changes(self, include_exit_changes=True):
        outfit_changes = set()
        pre_route_change = self.get_on_route_outfit()
        if pre_route_change is not None:
            outfit_changes.add(pre_route_change)
        if self.outfit_change is None:
            return outfit_changes
        overrides = self.outfit_change.posture_outfit_change_overrides
        if not overrides:
            return outfit_changes
        for outfit_change in overrides.values():
            on_entry = outfit_change.get_on_entry_outfit(self)
            if on_entry is not None:
                outfit_changes.add(on_entry)
            if not include_exit_changes:
                pass
            on_exit = outfit_change.get_on_exit_outfit(self)
            while on_exit is not None:
                outfit_changes.add(on_exit)
        return outfit_changes

    def add_preload_outfit_changes(self, final_preload_outfit_set):
        final_preload_outfit_set.update(self.get_tuned_outfit_changes(include_exit_changes=False))

    def get_attention_cost(self):
        return self.attention_cost

class DebugRaiseExceptioneSuperInteraction(SuperInteraction):
    __qualname__ = 'DebugRaiseExceptioneSuperInteraction'

    def _run_interaction_gen(self, timeline):
        raise RuntimeError('This is a forced error from DebugRaiseExceptionSuperInteraction')

