from aspirations.aspiration_types import AspriationType
from event_testing import objective_tuning
from event_testing.resolver import DoubleSimResolver
from event_testing.results import TestResult
from interactions import ParticipantType
from interactions.utils.notification import NotificationElement
from sims import genealogy_tracker
from sims4.tuning.instances import HashedTunedInstanceMetaclass, lock_instance_tunables
from sims4.tuning.tunable import TunableEnumEntry, HasTunableSingletonFactory, AutoFactoryInit, TunableSet, TunableReference, OptionalTunable
from sims4.tuning.tunable_base import GroupNames, GroupNames, SourceQueries
from singletons import DEFAULT
from situations.situation_goal import TunableWeightedSituationGoalReference
from ui.ui_dialog import UiDialogResponse
from ui.ui_dialog_notification import UiDialogNotification
import enum
import event_testing
import services
import sims4.localization
import sims4.log
import sims4.tuning.tunable
import ui.screen_slam
from sims4.utils import classproperty
logger = sims4.log.Logger('AspirationTuning')

class AllCompletionType(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'AllCompletionType'
    FACTORY_TUNABLES = {'description': '\n            Choosing this will require all objectives to be completed.\n            '}

    def completion_requirement(self, aspiration):
        return len(aspiration.objectives)

class SubsetCompletionType(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'SubsetCompletionType'
    FACTORY_TUNABLES = {'description': '\n            Choosing this will require a tuned subset of objectives to be completed.\n            ', 'number_required': sims4.tuning.tunable.Tunable(description='\n            The number of objectives required for this aspiration to complete.\n            ', tunable_type=int, default=1)}

    def completion_requirement(self, aspiration):
        return self.number_required

class AspirationBasic(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.ASPIRATION)):
    __qualname__ = 'AspirationBasic'
    INSTANCE_SUBCLASSES_ONLY = True
    INSTANCE_TUNABLES = {'objectives': sims4.tuning.tunable.TunableList(description='\n            A Set of objectives for completing an aspiration.', tunable=sims4.tuning.tunable.TunableReference(description='\n                One objective for an aspiration', manager=services.get_instance_manager(sims4.resources.Types.OBJECTIVE)), export_modes=sims4.tuning.tunable_base.ExportModes.All), 'objective_completion_type': sims4.tuning.tunable.TunableVariant(description='\n            The requirement of all or a subset of objectives to complete.                           \n            ', complete_all=AllCompletionType.TunableFactory(), complete_subset=SubsetCompletionType.TunableFactory(), default='complete_all'), 'complete_only_in_sequence': sims4.tuning.tunable.Tunable(description='\n            Aspirations that will only start progress if all previous track aspirations are complete.', tunable_type=bool, default=False), 'disabled': sims4.tuning.tunable.Tunable(description='\n            Checking this box will remove this Aspiration from the event system and the UI, but preserve the tuning.', tunable_type=bool, default=False, export_modes=sims4.tuning.tunable_base.ExportModes.All), 'screen_slam': OptionalTunable(description='\n            Which screen slam to show when this aspiration is complete.\n            Localization Tokens: Sim - {0.SimFirstName}, Milestone Name - \n            {1.String}, Aspiration Track Name - {2.String}\n            ', tunable=ui.screen_slam.TunableScreenSlamSnippet())}

    @classmethod
    def get_event_list(cls):
        return {test_event for objective in cls.objectives for test_event in objective.objective_test.test_events}

    @classmethod
    def handle_event(cls, sim_info, event, resolver):
        if sim_info is not None:
            sim_info.aspiration_tracker.handle_event(cls, event, resolver)

    @classmethod
    def objective_completion_count(cls):
        return cls.objective_completion_type.completion_requirement(cls)

    @classmethod
    def aspiration_type(cls):
        return AspriationType.BASIC

    @classmethod
    def register_callbacks(cls):
        tests = [objective.objective_test for objective in cls.objectives]
        services.get_event_manager().register_tests(cls, tests)

class Aspiration(AspirationBasic):
    __qualname__ = 'Aspiration'
    INSTANCE_TUNABLES = {'display_name': sims4.localization.TunableLocalizedString(description='\n            Display name for this aspiration\n            ', export_modes=sims4.tuning.tunable_base.ExportModes.All), 'descriptive_text': sims4.localization.TunableLocalizedString(description='\n            Description for this aspiration\n            ', export_modes=sims4.tuning.tunable_base.ExportModes.All), 'is_child_aspiration': sims4.tuning.tunable.Tunable(description='\n            Child aspirations are only possible to complete as a child.\n            ', tunable_type=bool, default=False, export_modes=sims4.tuning.tunable_base.ExportModes.All), 'reward': sims4.tuning.tunable.TunableReference(description='\n            Which rewards are given when this aspiration is completed.\n            ', manager=services.get_instance_manager(sims4.resources.Types.REWARD))}

    @classmethod
    def aspiration_type(cls):
        return AspriationType.FULL_ASPIRATION

    @classmethod
    def _verify_tuning_callback(cls):
        for objective in cls.objectives:
            pass
        logger.debug('Loading asset: {0}', cls)

class AspirationSimInfoPanel(AspirationBasic):
    __qualname__ = 'AspirationSimInfoPanel'
    INSTANCE_TUNABLES = {'display_name': sims4.localization.TunableLocalizedString(description='\n            Display name for this aspiration', export_modes=sims4.tuning.tunable_base.ExportModes.All), 'descriptive_text': sims4.localization.TunableLocalizedString(description='\n            Description for this aspiration', export_modes=sims4.tuning.tunable_base.ExportModes.All), 'category': sims4.tuning.tunable.TunableReference(description='\n            The category this aspiration track goes into when displayed in the UI.', manager=services.get_instance_manager(sims4.resources.Types.ASPIRATION_CATEGORY), export_modes=sims4.tuning.tunable_base.ExportModes.All)}

    @classmethod
    def aspiration_type(cls):
        return AspriationType.SIM_INFO_PANEL

    @classmethod
    def _verify_tuning_callback(cls):
        for objective in cls.objectives:
            pass

lock_instance_tunables(AspirationSimInfoPanel, complete_only_in_sequence=False)

class AspirationNotification(AspirationBasic):
    __qualname__ = 'AspirationNotification'
    INSTANCE_TUNABLES = {'objectives': sims4.tuning.tunable.TunableList(description='\n            A Set of objectives for completing an aspiration.', tunable=sims4.tuning.tunable.TunableReference(description='\n                One objective for an aspiration', manager=services.get_instance_manager(sims4.resources.Types.OBJECTIVE))), 'disabled': sims4.tuning.tunable.Tunable(description='\n            Checking this box will remove this Aspiration from the event system and the UI, but preserve the tuning.', tunable_type=bool, default=False), 'notification': UiDialogNotification.TunableFactory(description='\n            This text will display in a notification pop up when completed.\n            ')}

    @classmethod
    def aspiration_type(cls):
        return AspriationType.NOTIFICATION

lock_instance_tunables(AspirationNotification, complete_only_in_sequence=False)

class AspirationCareer(AspirationBasic):
    __qualname__ = 'AspirationCareer'

    def reward(self, *args, **kwargs):
        pass

    @classmethod
    def aspiration_type(cls):
        return AspriationType.CAREER

    @classmethod
    def _verify_tuning_callback(cls):
        for objective in cls.objectives:
            pass

lock_instance_tunables(AspirationCareer, complete_only_in_sequence=True)

class GeneTargetFactory(sims4.tuning.tunable.TunableFactory):
    __qualname__ = 'GeneTargetFactory'

    @staticmethod
    def factory(sim_info, relationship):
        family_member_sim_id = sim_info.get_relation(relationship)
        if family_member_sim_id is None:
            return TestResult(False, 'No target Family Member Found')
        family_member_sim_info = services.sim_info_manager().get(family_member_sim_id)
        if family_member_sim_info.is_baby or family_member_sim_info.is_instanced():
            return family_member_sim_info
        return TestResult(False, 'No target Family Member Found')

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(description='\n            This option tests for completion of a tuned Achievement.\n            ', relationship=TunableEnumEntry(genealogy_tracker.FamilyRelationshipIndex, genealogy_tracker.FamilyRelationshipIndex.FATHER), **kwargs)

class RelationTargetFactory(sims4.tuning.tunable.TunableFactory):
    __qualname__ = 'RelationTargetFactory'

    @staticmethod
    def factory(sim_info, relationship_test):
        relationship_match = None
        for relation in sim_info.relationship_tracker:
            relation_sim_info = services.sim_info_manager().get(relation.relationship_id)
            while relation_sim_info is not None and (relation_sim_info.is_baby or relation_sim_info.is_instanced()):
                resolver = DoubleSimResolver(sim_info, relation_sim_info)
                relationship_match = resolver(relationship_test)
                if relationship_match:
                    return relation_sim_info
        if relationship_match is None:
            return TestResult(False, 'No target Relation Found')
        return relationship_match

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(description='\n            This option tests for completion of a tuned Achievement.\n            ', relationship_test=event_testing.test_variants.TunableRelationshipTest(description='\n                The relationship state that this goal will complete when\n                obtained.\n                ', locked_args={'subject': ParticipantType.Actor, 'tooltip': None, 'target_sim': ParticipantType.TargetSim, 'num_relations': 0}), **kwargs)

class AspirationWhimSet(AspirationBasic):
    __qualname__ = 'AspirationWhimSet'
    INSTANCE_TUNABLES = {'objectives': sims4.tuning.tunable.TunableList(description='\n            A Set of objectives for completing an aspiration.', tunable=sims4.tuning.tunable.TunableReference(description='\n                One objective for an aspiration', manager=services.get_instance_manager(sims4.resources.Types.OBJECTIVE))), 'force_target': sims4.tuning.tunable.OptionalTunable(description='\n            Upon WhimSet activation, use this option to seek out and set a specific target for this set.\n            If the desired target does not exist or is not instanced on the lot, WhimSet will not activate.\n            ', tunable=sims4.tuning.tunable.TunableVariant(genealogy_target=GeneTargetFactory(), relationship_target=RelationTargetFactory(), default='genealogy_target')), 'whims': sims4.tuning.tunable.TunableList(description='\n            List of weighted goals.', tunable=TunableWeightedSituationGoalReference()), 'connected_whims': sims4.tuning.tunable.TunableMapping(description='\n            A tunable list of whims that upon a goal from this list succeeding will activate.', key_type=TunableReference(services.get_instance_manager(sims4.resources.Types.SITUATION_GOAL), description='The goal to map.'), value_type=sims4.tuning.tunable.TunableList(description='\n                A tunable list of whim sets that upon this whim goal completing will activate', tunable=sims4.tuning.tunable.TunableReference(description='\n                    These Aspiration Whim Sets become active automatically upon completion of this whim.', manager=services.get_instance_manager(sims4.resources.Types.ASPIRATION), class_restrictions='AspirationWhimSet'))), 'connected_whim_sets': sims4.tuning.tunable.TunableList(description='\n            A tunable list of whim sets that upon a goal from this list succeeding will activate', tunable=sims4.tuning.tunable.TunableReference(description='\n                These Aspiration Whim Sets become active automatically upon completion of a whim from this set.', manager=services.get_instance_manager(sims4.resources.Types.ASPIRATION), class_restrictions='AspirationWhimSet')), 'active_timer': sims4.tuning.tunable.TunableRange(description='\n            Number of Sim minutes this set of Whims is available upon activation.', tunable_type=float, minimum=1, maximum=18000, default=60), 'cooldown_timer': sims4.tuning.tunable.TunableRange(description='\n            Number of Sim minutes this set of Whims is de-prioritized after de-activation.', tunable_type=float, minimum=0, maximum=3600, default=60), 'new_whim_delay': sims4.tuning.tunable.TunableInterval(description='\n            A tunable interval that creates a random number of Sim minutes of delay from set \n            activation to actual whim appearance. NOTE: This must not exceed the value tuned in \n            active timer, or loading callbacks will complain about how incorrect your tuning is.', tunable_type=int, default_lower=0, default_upper=0), 'whim_cancel_refresh_delay': sims4.tuning.tunable.TunableInterval(description='\n            A tunable interval that creates a random number of Sim minutes of delay after canceling \n            a whim till a new whim appearance.', tunable_type=int, default_lower=0, default_upper=0), 'disabled': sims4.tuning.tunable.Tunable(description='\n            Checking this box will remove this Aspiration from the event system and the UI, but preserve the tuning.', tunable_type=bool, default=False), 'base_priority': sims4.tuning.tunable.TunableRange(description='\n            Priority for this set to be chosen if not currently triggered by contextual events.', tunable_type=int, minimum=0, maximum=5, default=0), 'activated_priority': sims4.tuning.tunable.TunableRange(description='\n            Priority for this set to be chosen if triggered by contextual events.', tunable_type=int, minimum=0, maximum=10, default=6), 'chained_priority': sims4.tuning.tunable.TunableRange(description='\n            Priority for this set to be chosen if triggered by a previous whim set.', tunable_type=int, minimum=0, maximum=15, default=11), 'timeout_retest': sims4.tuning.tunable.TunableReference(description='\n            Tuning an objective here will re-test the WhimSet for contextual relevance upon active timer timeout;\n            If the objective test passes, the active timer will be refreshed. Note you can only use\n            tests without data passed in, other types will result in an assert on load.', manager=services.get_instance_manager(sims4.resources.Types.OBJECTIVE)), 'whimset_emotion': sims4.tuning.tunable.OptionalTunable(description='\n            Setting this field sets whims in this whimset as emotional, indicating unique \n            emotional behavior and UI treatment in the whim system.', tunable=sims4.tuning.tunable.TunableReference(description='\n                The emotion associated with this whim set.', manager=services.get_instance_manager(sims4.resources.Types.MOOD))), 'whim_reason': sims4.localization.TunableLocalizedStringFactory(description='\n            The reason that shows in the whim tooltip for the reason that this\n            whim was chosen for the sim.\n            ')}

    @classmethod
    def aspiration_type(cls):
        return AspriationType.WHIM_SET

    @classmethod
    def _verify_tuning_callback(cls):
        for objective in cls.objectives:
            pass
        for whim in cls.whims:
            pass
        if cls.new_whim_delay.upper_bound > 0:
            pass
        if cls.timeout_retest is not None:
            pass

lock_instance_tunables(AspirationWhimSet, complete_only_in_sequence=False)

class AspirationFamilialTrigger(AspirationBasic):
    __qualname__ = 'AspirationFamilialTrigger'
    INSTANCE_TUNABLES = {'objectives': sims4.tuning.tunable.TunableList(description='\n            A Set of objectives for completing an aspiration.', tunable=sims4.tuning.tunable.TunableReference(description='\n                One objective for an aspiration', manager=services.get_instance_manager(sims4.resources.Types.OBJECTIVE))), 'target_family_relationships': TunableSet(description='\n            These relations will get an event message upon Aspiration completion that they can test for.', tunable=TunableEnumEntry(genealogy_tracker.FamilyRelationshipIndex, genealogy_tracker.FamilyRelationshipIndex.FATHER)), 'disabled': sims4.tuning.tunable.Tunable(description='\n            Checking this box will remove this Aspiration from the event system and the UI, but preserve the tuning.', tunable_type=bool, default=False)}

    @classmethod
    def aspiration_type(cls):
        return AspriationType.FAMILIAL

    @classmethod
    def _verify_tuning_callback(cls):
        for objective in cls.objectives:
            pass

lock_instance_tunables(AspirationFamilialTrigger, complete_only_in_sequence=False)

class AspirationCategory(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.ASPIRATION_CATEGORY)):
    __qualname__ = 'AspirationCategory'
    INSTANCE_TUNABLES = {'display_text': sims4.localization.TunableLocalizedString(description='Text used to show the Aspiration Category name in the UI', export_modes=sims4.tuning.tunable_base.ExportModes.All), 'ui_sort_order': sims4.tuning.tunable.Tunable(description='\n            Order in which this category is sorted against other categories in the UI.\n            If two categories share the same sort order, undefined behavior will insue.\n            ', tunable_type=int, default=0, export_modes=sims4.tuning.tunable_base.ExportModes.All), 'icon': sims4.tuning.tunable.TunableResourceKey(None, resource_types=sims4.resources.CompoundTypes.IMAGE, description='\n            The icon to be displayed in the panel view.\n            ', export_modes=sims4.tuning.tunable_base.ExportModes.All, tuning_group=GroupNames.UI), 'is_sim_info_panel': sims4.tuning.tunable.Tunable(description='\n            Checking this box will mark this category for the Sim Info Panel, not the Aspirations panel.', tunable_type=bool, default=False, export_modes=sims4.tuning.tunable_base.ExportModes.All)}

class AspirationTrackLevels(enum.Int):
    __qualname__ = 'AspirationTrackLevels'
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3
    LEVEL_4 = 4
    LEVEL_5 = 5
    LEVEL_6 = 6

TRACK_LEVEL_MAX = 6

class AspirationTrack(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.ASPIRATION_TRACK)):
    __qualname__ = 'AspirationTrack'
    INSTANCE_TUNABLES = {'display_text': sims4.localization.TunableLocalizedString(description='\n            Text used to show the Aspiration Track name in the UI', export_modes=sims4.tuning.tunable_base.ExportModes.All), 'description_text': sims4.localization.TunableLocalizedString(description='\n            Text used to show the Aspiration Track description in the UI', export_modes=sims4.tuning.tunable_base.ExportModes.All), 'icon': sims4.tuning.tunable.TunableResourceKey(None, resource_types=sims4.resources.CompoundTypes.IMAGE, description='\n            The icon to be displayed in the panel view.\n            ', export_modes=sims4.tuning.tunable_base.ExportModes.All, tuning_group=GroupNames.UI), 'icon_high_res': sims4.tuning.tunable.TunableResourceKey(None, resource_types=sims4.resources.CompoundTypes.IMAGE, description='\n            The icon to be displayed in aspiration track selection.\n            ', export_modes=sims4.tuning.tunable_base.ExportModes.All, tuning_group=GroupNames.UI), 'category': sims4.tuning.tunable.TunableReference(description='\n            The category this aspiration track goes into when displayed in the UI.', manager=services.get_instance_manager(sims4.resources.Types.ASPIRATION_CATEGORY), export_modes=sims4.tuning.tunable_base.ExportModes.All), 'primary_trait': sims4.tuning.tunable.TunableReference(description='\n            This is the primary Aspiration reward trait that is applied upon selection from CAS.', manager=services.get_instance_manager(sims4.resources.Types.TRAIT), export_modes=sims4.tuning.tunable_base.ExportModes.All), 'aspirations': sims4.tuning.tunable.TunableMapping(description='\n            A Set of objectives for completing an aspiration.', key_type=TunableEnumEntry(AspirationTrackLevels, AspirationTrackLevels.LEVEL_1), value_type=sims4.tuning.tunable.TunableReference(description='\n                One aspiration in the track, associated for a level', manager=services.get_instance_manager(sims4.resources.Types.ASPIRATION), class_restrictions='Aspiration', reload_dependent=True), export_modes=sims4.tuning.tunable_base.ExportModes.All), 'reward': sims4.tuning.tunable.TunableReference(description='\n            Which rewards are given when this aspiration track is completed.', manager=services.get_instance_manager(sims4.resources.Types.REWARD), export_modes=sims4.tuning.tunable_base.ExportModes.All), 'notification': UiDialogNotification.TunableFactory(description='\n            This text will display in a notification pop up when completed.\n            ', locked_args={'text_tokens': DEFAULT, 'icon': None, 'primary_icon_response': UiDialogResponse(text=None, ui_request=UiDialogResponse.UiDialogUiRequest.SHOW_ASPIRATION_SELECTOR), 'secondary_icon': None}), 'mood_asm_param': sims4.tuning.tunable.Tunable(description="\n            The asm parameter for Sim's mood for use with CAS ASM state machine, driven by selection\n            of this AspirationTrack, i.e. when a player selects the a romantic aspiration track, the Flirty\n            ASM is given to the state machine to play. The name tuned here must match the animation\n            state name parameter expected in Swing.", tunable_type=str, default=None, source_query=SourceQueries.SwingEnumNamePattern.format('mood'), export_modes=sims4.tuning.tunable_base.ExportModes.All)}
    _sorted_aspirations = None

    @classmethod
    def get_aspirations(cls):
        return cls._sorted_aspirations

    @classmethod
    def get_next_aspriation(cls, current_aspiration):
        next_aspiration_level = None
        current_aspiration_guid = current_aspiration.guid64
        for (level, track_aspiration) in cls.aspirations.items():
            while track_aspiration.guid64 == current_aspiration_guid:
                next_aspiration_level = int(level) + 1
                break
        if next_aspiration_level in cls.aspirations:
            return cls.aspirations[next_aspiration_level]

    @classproperty
    def is_child_aspiration_track(cls):
        return cls._sorted_aspirations[0][1].is_child_aspiration

    @classmethod
    def _tuning_loaded_callback(cls):
        cls._sorted_aspirations = tuple(sorted(cls.aspirations.items()))

    @classmethod
    def _verify_tuning_callback(cls):
        logger.debug('Loading asset: {}', cls, owner='ddriscoll')
        if cls.category == None:
            logger.error('{} Aspiration Track has no category set.', cls, owner='ddriscoll')
        if len(cls.aspirations) == 0:
            logger.error('{} Aspiration Track has no aspirations mapped to levels.', cls, owner='ddriscoll')
        else:
            aspiration_list = cls.aspirations.values()
            aspiration_set = set(aspiration_list)
            if len(aspiration_set) != len(aspiration_list):
                logger.error('{} Aspiration Track has repeating aspiration values in the aspiration map.', cls, owner='ddriscoll')

