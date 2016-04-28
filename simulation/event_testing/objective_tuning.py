from event_testing import TargetIdTypes
from event_testing.test_events import TestEvent
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableVariant, HasTunableSingletonFactory, AutoFactoryInit
from sims4.utils import classproperty
import event_testing.results as results
import event_testing.test_variants
import event_testing.tests
import event_testing.tests_with_data as tests_with_data
import services
import sims4.log
import sims4.tuning.tunable
import tag
logger = sims4.log.Logger('ObjectiveTuning')

class TunableObjectiveTestVariant(TunableVariant):
    __qualname__ = 'TunableObjectiveTestVariant'

    def __init__(self, description='A tunable test supported for use as an objective.', **kwargs):
        super().__init__(statistic=event_testing.test_variants.TunableStatThresholdTest(), skill_tag=event_testing.test_variants.TunableSkillTagThresholdTest(), trait=event_testing.test_variants.TunableTraitTest(), relationship=event_testing.test_variants.TunableRelationshipTest(), content_mode=event_testing.test_variants.TunableContentModeTest(), scoring_preference=event_testing.test_variants.TunableObjectScoringPreferenceTest(), distance=event_testing.test_variants.DistanceTest.TunableFactory(), posture=event_testing.test_variants.PostureTest.TunableFactory(), identity=event_testing.test_variants.TunableIdentityTest(), inventory=event_testing.test_variants.InventoryTest.TunableFactory(), object_purchase_test=event_testing.test_variants.TunableObjectPurchasedTest(), simoleon_value=event_testing.test_variants.TunableSimoleonsTest(), familial_trigger_test=tests_with_data.TunableFamilyAspirationTriggerTest(), whim_completed_test=tests_with_data.TunableWhimCompletedTest(), offspring_created_test=tests_with_data.OffspringCreatedTest.TunableFactory(), situation_running_test=event_testing.test_variants.TunableSituationRunningTest(), crafted_item=event_testing.test_variants.TunableCraftedItemTest(), motive=event_testing.test_variants.TunableMotiveThresholdTestTest(), collection_test=event_testing.test_variants.TunableCollectionThresholdTest(), object_ownership=event_testing.test_variants.ObjectOwnershipTest.TunableFactory(), total_simoleons_earned=event_testing.test_variants.TunableTotalSimoleonsEarnedTest(), total_time_played=event_testing.test_variants.TunableTotalTimePlayedTest(), ran_interaction_test=tests_with_data.TunableParticipantRanInteractionTest(), started_interaction_test=tests_with_data.TunableParticipantStartedInteractionTest(), unlock_earned=event_testing.test_variants.TunableUnlockedTest(), simoleons_earned=tests_with_data.TunableSimoleonsEarnedTest(), total_relationship_bit=tests_with_data.TunableTotalRelationshipBitTest(), total_zones_traveled=tests_with_data.TunableTotalTravelTest(), buff_for_amount_of_time=tests_with_data.TunableBuffForAmountOfTimeTest(), total_simoleons_earned_by_tag=tests_with_data.TunableTotalSimoleonsEarnedByTagTest(), total_interaction_time_elapsed_by_tag=tests_with_data.TunableTotalTimeElapsedByTagTest(), career_attendence=tests_with_data.TunableCareerAttendenceTest(), household_size=event_testing.test_variants.HouseholdSizeTest.TunableFactory(), buff_added=event_testing.test_variants.TunableBuffAddedTest(), mood_test=event_testing.test_variants.TunableMoodTest(), selected_aspiration_track_test=event_testing.test_variants.TunableSelectedAspirationTrackTest(), career_test=event_testing.test_variants.TunableCareerTest.TunableFactory(), has_buff=event_testing.test_variants.TunableBuffTest(), object_criteria=event_testing.test_variants.ObjectCriteriaTest.TunableFactory(), description=description, **kwargs)

class SimInfoStatisticObjectiveTrack(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'SimInfoStatisticObjectiveTrack'
    FACTORY_TUNABLES = {'description': '\n            Track this objective as a sim info statistic.  This means that the\n            objective will never complete and instead just keep counting up.\n            '}

    def num_required(self):
        return sims4.math.MAX_INT32

    def increment_data(self, data_object, guid, objective_test, resolver):
        data_object.increment_objective_count(guid)
        num_of_iterations = data_object.get_objective_count(guid)
        return results.TestResultNumeric(False, 'Objective: not possible because sim info panel member.', current_value=num_of_iterations, goal_value=0, is_money=False)

    def check_test_validity(self, objective_test):
        return True

class IterationsObjectiveTrack(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'IterationsObjectiveTrack'
    FACTORY_TUNABLES = {'description': '\n            Track this objective as a number of iterations that the tests must\n            pass before this objective is considered complete.  \n            ', 'iterations_required_to_pass': sims4.tuning.tunable.Tunable(int, 1, description='The number of times that the objective test must pass in order for the objective to be considered complete.')}

    def num_required(self):
        return self.iterations_required_to_pass

    def increment_data(self, data_object, guid, objective_test, resolver):
        data_object.increment_objective_count(guid)
        num_of_iterations = data_object.get_objective_count(guid)
        if num_of_iterations < self.iterations_required_to_pass:
            return results.TestResultNumeric(False, 'Objective: not enough iterations.', current_value=num_of_iterations, goal_value=self.iterations_required_to_pass, is_money=False)
        return results.TestResult.TRUE

    def check_test_validity(self, objective_test):
        return True

class UniqueTargetsObjectiveTrack(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'UniqueTargetsObjectiveTrack'
    FACTORY_TUNABLES = {'description': '\n            Track unique sim targets as the count for this specific objective.\n            Only tests that implement the functionality to grab a proper target\n            id will work when this objective type is selected.\n            \n            Current tests supported:\n            ran_interaction_test -> target_sim of the interaction must be unique, stored by sim_id\n            crafted_item -> crafted object of the crafting process must be unique, stored by definition_id\n            career_test by career reference -> the career from the event must \n                be unique, stored by career guid64.\n                NOTE: This will only work if the career reference tuning is left blank.\n            ', 'unique_targets_required_to_pass': sims4.tuning.tunable.Tunable(description='\n                The number of unique targets that need to attained to pass.\n                ', tunable_type=int, default=1), 'id_to_check': sims4.tuning.tunable.TunableEnumEntry(description="\n            Uniqueness can be by either instance id or definition id. For example, crafting 2 plates\n            of mac and cheese will have the same definition id but different instance id's.", tunable_type=TargetIdTypes, default=TargetIdTypes.DEFAULT)}

    def num_required(self):
        return self.unique_targets_required_to_pass

    def increment_data(self, data_object, guid, objective_test, resolver):
        target_id = resolver.get_target_id(objective_test, self.id_to_check)
        if target_id is not None:
            data_object.add_objective_id(guid, target_id)
        num_of_iterations = data_object.get_objective_count(guid)
        if num_of_iterations < self.unique_targets_required_to_pass:
            return results.TestResultNumeric(False, 'Objective: not enough iterations.', current_value=num_of_iterations, goal_value=self.unique_targets_required_to_pass, is_money=False)
        data_object.set_objective_complete(guid)
        return results.TestResult.TRUE

    def check_test_validity(self, objective_test):
        return objective_test.UNIQUE_TARGET_TRACKING_AVAILABLE

class UniquePosturesObjectiveTrack(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'UniquePosturesObjectiveTrack'
    FACTORY_TUNABLES = {'description': '\n            Track unique sim postures as the count for this specific objective.\n            Only tests that implement the functionality to grab a proper\n            posture id will work when this objective type is selected.\n            \n            Current tests supported:\n            ran_interaction_test -> interaction.sim.posture of the \n            interaction must be unique\n            ', 'unique_postures_required_to_pass': sims4.tuning.tunable.Tunable(description='\n                The number of unique postures needed to pass.\n                ', tunable_type=int, default=1)}

    def num_required(self):
        return self.unique_postures_required_to_pass

    def increment_data(self, data_object, guid, objective_test, resolver):
        posture_id = resolver.get_posture_id(objective_test)
        if posture_id is not None:
            data_object.add_objective_id(guid, posture_id)
        num_of_iterations = data_object.get_objective_count(guid)
        if num_of_iterations < self.unique_postures_required_to_pass:
            return results.TestResultNumeric(False, 'Objective: not enough iterations.', current_value=num_of_iterations, goal_value=self.unique_postures_required_to_pass, is_money=False)
        data_object.set_objective_complete(guid)
        return results.TestResult.TRUE

    def check_test_validity(self, objective_test):
        return objective_test.UNIQUE_POSTURE_TRACKING_AVAILABLE

class TagChecklistObjectiveTrack(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'TagChecklistObjectiveTrack'
    FACTORY_TUNABLES = {'description': '\n            Track an iteration count of one completion per tag tuned on the list. Ex. Paint \n            4 paintings of different genres, in this case you would tune a count of "4" and add\n            all genre tags to the tag list. Each painting created would only count if it was not\n            from a genre tag previously entered. In order to support this functionality, each\n            painting object created would need to be tagged with it\'s genre upon creation, which can\n            be tuned in Recipe.\n            \n            Current tests supported:\n            ran_interaction_test -> first tag from checklist found on the interaction must be unique\n            crafted_item -> first tag from the checklist found on crafted object must be unique\n            ', 'unique_tags_required_to_pass': sims4.tuning.tunable.Tunable(description='\n                The number of unique tags that will count once for checking off the list.\n                ', tunable_type=int, default=1), 'tag_checklist': sims4.tuning.tunable.TunableList(description='\n            A list of single count tags that if present on the tested subject will count toward the total.', tunable=sims4.tuning.tunable.TunableEnumEntry(tag.Tag, tag.Tag.INVALID))}

    def num_required(self):
        return self.unique_tags_required_to_pass

    def increment_data(self, data_object, guid, objective_test, resolver):
        tags_to_test = resolver.get_tags(objective_test)
        for tag_from_test in tags_to_test:
            for tag_from_objective in self.tag_checklist:
                while tag_from_test is tag_from_objective:
                    data_object.add_objective_id(guid, tag_from_objective)
                    break
        num_of_iterations = data_object.get_objective_count(guid)
        if num_of_iterations < self.unique_tags_required_to_pass:
            return results.TestResultNumeric(False, 'Objective: not enough iterations.', current_value=num_of_iterations, goal_value=self.unique_tags_required_to_pass, is_money=False)
        data_object.set_objective_complete(guid)
        return results.TestResult.TRUE

    def check_test_validity(self, objective_test):
        return objective_test.TAG_CHECKLIST_TRACKING_AVAILABLE

class UniqueLocationsObjectiveTrack(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'UniqueLocationsObjectiveTrack'
    FACTORY_TUNABLES = {'description': '\n            Track unique locations as the count for this specific objective.\n            ', 'unique_locations_required_to_pass': sims4.tuning.tunable.Tunable(description='\n                The number of unique locations needed to pass.\n                ', tunable_type=int, default=1)}

    def num_required(self):
        return self.unique_locations_required_to_pass

    def increment_data(self, data_object, guid, objective_test, resolver):
        lot_id = services.get_zone(resolver.sim_info.zone_id).lot.lot_id
        if lot_id is not None:
            data_object.add_objective_id(guid, lot_id)
        num_of_iterations = data_object.get_objective_count(guid)
        if num_of_iterations < self.unique_locations_required_to_pass:
            return results.TestResultNumeric(False, 'Objective: not enough matching location iterations.', current_value=num_of_iterations, goal_value=self.unique_locations_required_to_pass, is_money=False)
        data_object.set_objective_complete(guid)
        return results.TestResult.TRUE

    def check_test_validity(self, objective_test):
        return True

class IterationsSingleSituation(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'IterationsSingleSituation'
    FACTORY_TUNABLES = {'description': '\n            Track this objective as a number of iterations that the tests must\n            pass during the same situation before this objective is considered \n            complete.\n            ', 'iterations_required_to_pass': sims4.tuning.tunable.Tunable(description='\n                The number of times that the objective test must pass in a\n                single situation for the objective to be considered complete.\n                ', tunable_type=int, default=1)}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_situation_id = 0

    def num_required(self):
        return self.iterations_required_to_pass

    def increment_data(self, data_object, guid, objective_test, resolver):
        sim = resolver.sim_info.get_sim_instance()
        if sim is None:
            return results.TestResultNumeric(False, "Couldn't find sim instance.", current_value=data_object.get_objective_count(guid), goal_value=self.iterations_required_to_pass, is_money=False)
        user_facing_situation_id = 0
        for situation in services.get_zone_situation_manager().get_situations_sim_is_in(sim):
            while situation.is_user_facing:
                user_facing_situation_id = situation.id
                break
        if user_facing_situation_id == 0:
            return results.TestResultNumeric(False, 'Sim is not currently in a situation.', current_value=data_object.get_objective_count(guid), goal_value=self.iterations_required_to_pass, is_money=False)
        if user_facing_situation_id != self.current_situation_id:
            self.current_situation_id = user_facing_situation_id
            data_object.reset_objective_count(guid)
        data_object.increment_objective_count(guid)
        num_of_iterations = data_object.get_objective_count(guid)
        if num_of_iterations < self.iterations_required_to_pass:
            return results.TestResultNumeric(False, 'Objective: not enough iterations.', current_value=num_of_iterations, goal_value=self.iterations_required_to_pass, is_money=False)
        return results.TestResult.TRUE

    def check_test_validity(self, objective_test):
        return True

class Objective(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.OBJECTIVE)):
    __qualname__ = 'Objective'
    INSTANCE_TUNABLES = {'display_text': TunableLocalizedStringFactory(description='Text used to show the progress of this objective in the UI', export_modes=sims4.tuning.tunable_base.ExportModes.All), 'objective_test': TunableObjectiveTestVariant(description='Type of test used for this objective'), 'additional_tests': event_testing.tests.TunableTestSet(description='Additional tests that must be true when the Objective Test passes in order for the Objective consider having passed.'), 'satisfaction_points': sims4.tuning.tunable.Tunable(description='\n            The number of satisfaction points, if relevant, that completion of this objective awards.', tunable_type=int, default=0, export_modes=sims4.tuning.tunable_base.ExportModes.All), 'objective_completion_type': TunableVariant(iterations=IterationsObjectiveTrack.TunableFactory(), sim_info_statistic=SimInfoStatisticObjectiveTrack.TunableFactory(), unique_targets=UniqueTargetsObjectiveTrack.TunableFactory(), unique_postures=UniquePosturesObjectiveTrack.TunableFactory(), unique_locations=UniqueLocationsObjectiveTrack.TunableFactory(), tag_checklist=TagChecklistObjectiveTrack.TunableFactory(), iterations_single_situation=IterationsSingleSituation.TunableFactory(), default='iterations', description='\n                           The type of check that will be used to determine if\n                           this objective passes or fails.\n                           \n                           iterations: This tests the total number of times\n                           that the tests have passed.  The objective is\n                           considered complete when the the number of times\n                           it has passed is equal to the tuned number of times\n                           it should pass.\n                           \n                           unique_targets: Works just like the \'iterations\'\n                           type of objective completion type but only counts\n                           unique ids of the targets of the test rather than\n                           counting all of them.  Not all tests are supported\n                           with this objective completion type.\n                           Currently supported tests:\n                           ran_interaction_test\n                           crafted_object\n                           \n                           unique_locations: Works just like unique targets, except it only\n                           increments if the objective was completed in a unique location (lot id)\n                           than any previous successful completion.\n                           \n                           sim_info_statistic: Counts the number of times that\n                           the tests have passed.  Objectives tuned with this\n                           objective completion type will never pass and\n                           instead just propagate the number of times the test\n                           has passed back to their caller.\n                           \n                           tag_checklist: Track an iteration count of one completion per tag \n                           tuned on the list. Ex. Paint 4 paintings of different genres, in this \n                           case you would tune a count of "4" and add all genre tags to the tag \n                           list. Each painting created would only count if it was not from a genre \n                           tag previously entered. In order to support this functionality, each \n                           painting object created would need to be tagged with it\'s genre upon \n                           creation, which can be tuned in Recipe.\n                           \n                           iterations_single_situation: This tests the total \n                           number of times that the tests have passed during a\n                           single situation.  If the situation ends, the count\n                           will reset when the tests pass the for first time \n                           during a new situation.  The objective is\n                           considered complete when the the number of times\n                           it has passed is equal to the tuned number of times\n                           it should pass.\n                           '), 'resettable': sims4.tuning.tunable.Tunable(description='\n            Setting this allows for this objective to reset back to zero for certain uses, such as for Whim Set activation.\n            ', tunable_type=bool, default=False), 'relative_to_unlock_moment': sims4.tuning.tunable.Tunable(description="\n            If true this objective will start counting from the moment of assignment or reset instead\n            of over the total lifetime of a Sim, most useful for Careers and Whimsets. Note:\n            this effect is only for 'Total' data tests (tests that used persisted save data)\n             ", tunable_type=bool, default=False), 'tooltip': TunableLocalizedStringFactory(description='\n            Tooltip that will display on the objective.\n            ', export_modes=sims4.tuning.tunable_base.ExportModes.All)}

    @classmethod
    def goal_value(cls):
        completion_value = cls.objective_completion_type.num_required()
        if completion_value > 1:
            return completion_value
        return cls.objective_test.goal_value()

    @classproperty
    def is_goal_value_money(cls):
        completion_value = cls.objective_completion_type.num_required()
        if completion_value > 1:
            return False
        return cls.objective_test.is_goal_value_money

    @classmethod
    def _verify_tuning_callback(cls):
        if not cls.objective_completion_type.check_test_validity(cls.objective_test):
            logger.error('{0} has objective test that is incompatible with objective completion type.', cls)
        if cls.objective_test.USES_DATA_OBJECT:
            pass

    @classmethod
    def _get_current_iterations_test_result(cls, objective_data):
        return results.TestResultNumeric(False, 'Objective: not enough iterations.', current_value=objective_data.get_objective_count(cls.guid64), goal_value=cls.objective_completion_type.num_required(), is_money=False)

    @classmethod
    def run_test(cls, event, resolver, objective_data=None):
        if event not in cls.objective_test.test_events and event != TestEvent.UpdateObjectiveData:
            return results.TestResult(False, 'Objective test not present in event set.')
        iterations_required = cls.objective_completion_type.num_required()
        test_result = resolver(cls.objective_test, objective_data, cls.guid64)
        if not test_result:
            if iterations_required > 1:
                return cls._get_current_iterations_test_result(objective_data)
            return test_result
        additional_test_results = cls.additional_tests.run_tests(resolver)
        if not additional_test_results:
            if iterations_required > 1 or isinstance(additional_test_results, results.TestResultNumeric):
                return cls._get_current_iterations_test_result(objective_data)
            return additional_test_results
        if not resolver.on_zone_load:
            return cls.objective_completion_type.increment_data(objective_data, cls.guid64, cls.objective_test, resolver)
        if iterations_required == 1 and isinstance(test_result, results.TestResultNumeric):
            test_result.result = False
            return test_result
        return cls._get_current_iterations_test_result(objective_data)

    @classmethod
    def reset_objective(cls, objective_data):
        objective_data.reset_objective_count(cls.guid64)
        cls.set_starting_point(objective_data)

    @classmethod
    def set_starting_point(cls, objective_data):
        if cls.relative_to_unlock_moment:
            cls.objective_test.save_relative_start_values(cls.guid64, objective_data)
            return True
        return False

