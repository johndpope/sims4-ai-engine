from event_testing import tests_with_data
from sims4.localization import TunableLocalizedString
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableTuple, TunableResourceKey, TunableList, TunableReference, TunableVariant, Tunable
from sims4.tuning.tunable_base import ExportModes
import event_testing
import services
import sims4

class TunableTutorialTestVariant(TunableVariant):
    __qualname__ = 'TunableTutorialTestVariant'

    def __init__(self, description='A tunable test supported for use as an objective.', **kwargs):
        super().__init__(statistic=event_testing.test_variants.TunableStatThresholdTest(), skill_tag=event_testing.test_variants.TunableSkillTagThresholdTest(), trait=event_testing.test_variants.TunableTraitTest(), relationship=event_testing.test_variants.TunableRelationshipTest(), object_purchase_test=event_testing.test_variants.TunableObjectPurchasedTest(), simoleon_value=event_testing.test_variants.TunableSimoleonsTest(), familial_trigger_test=tests_with_data.TunableFamilyAspirationTriggerTest(), situation_running_test=event_testing.test_variants.TunableSituationRunningTest(), crafted_item=event_testing.test_variants.TunableCraftedItemTest(), motive=event_testing.test_variants.TunableMotiveThresholdTestTest(), collection_test=event_testing.test_variants.TunableCollectionThresholdTest(), ran_interaction_test=tests_with_data.TunableParticipantRanInteractionTest(), started_interaction_test=tests_with_data.TunableParticipantStartedInteractionTest(), unlock_earned=event_testing.test_variants.TunableUnlockedTest(), simoleons_earned=tests_with_data.TunableSimoleonsEarnedTest(), household_size=event_testing.test_variants.HouseholdSizeTest.TunableFactory(), has_buff=event_testing.test_variants.TunableBuffTest(), selected_aspiration_track_test=event_testing.test_variants.TunableSelectedAspirationTrackTest(), object_criteria=event_testing.test_variants.ObjectCriteriaTest.TunableFactory(), location=event_testing.test_variants.TunableLocationTest(), buff_added=event_testing.test_variants.TunableBuffAddedTest(), has_career=event_testing.test_variants.HasCareerTestFactory.TunableFactory(), lot_owner=event_testing.test_variants.TunableLotOwnerTest(), description=description, **kwargs)

class TunableTutorialSlideTuple(TunableTuple):
    __qualname__ = 'TunableTutorialSlideTuple'

    def __init__(self, **kwargs):
        super().__init__(description='The text for this slide.', text=TunableLocalizedString(), image=TunableResourceKey(description='\n                             The image for this slide.\n                             ', default=None, needs_tuning=True, resource_types=sims4.resources.CompoundTypes.IMAGE), **kwargs)

class TutorialCategory(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.TUTORIAL)):
    __qualname__ = 'TutorialCategory'
    INSTANCE_TUNABLES = {'name': TunableLocalizedString(description='\n            Name of the tutorial category.\n            ', export_modes=ExportModes.All)}

class Tutorial(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.TUTORIAL)):
    __qualname__ = 'Tutorial'
    INSTANCE_TUNABLES = {'name': TunableLocalizedString(description='\n            Name of the tutorial. i.e. if this is a tutorial about Build/Buy\n            you might put "Build Buy Mode"\n            ', export_modes=ExportModes.ClientBinary), 'category': TunableReference(description='\n            The tutorial category in which this tutorial belongs.\n            ', manager=services.get_instance_manager(sims4.resources.Types.TUTORIAL), class_restrictions=TutorialCategory, export_modes=ExportModes.ClientBinary), 'slides': TunableList(description='\n            These are the slides (images with a description) that create the\n            story for this tutorial. They will be shown in the order they are\n            provided, so the first slide in this list will be the first slide\n            of the tutorial.\n            ', tunable=TunableTutorialSlideTuple(), export_modes=ExportModes.ClientBinary), 'ui_sort_order': Tunable(description='\n            Order in which this tutorial is sorted against other tutorials in \n            its category in the UI. If two tutorials in a category share the \n            same sort order, undefined behavior will occur.\n            ', tunable_type=int, default=0, export_modes=ExportModes.ClientBinary)}

