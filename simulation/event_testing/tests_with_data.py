from clock import interval_in_sim_minutes
from date_and_time import TimeSpan
from event_testing import TargetIdTypes
from event_testing.results import TestResult, TestResultNumeric
from event_testing.test_events import TestEvent, cached_test
from event_testing.test_variants import TagTestType
from interactions import ParticipantType
from interactions.utils.outcome import OutcomeResult
from objects import ALL_HIDDEN_REASONS
from sims4.tuning.tunable import TunableEnumEntry, TunableVariant, TunableReference, TunableList, TunableSingletonFactory, TunableThreshold, OptionalTunable, Tunable, TunableSimMinute, TunableSet, TunableFactory, TunableTuple, AutoFactoryInit, HasTunableSingletonFactory
from tag import Tag
import build_buy
import careers.career_tuning
import enum
import event_testing.test_base
import event_testing.test_events
import services
import sims4.resources
logger = sims4.log.Logger('TestsWithEventData')

class InteractionTestEvents(enum.Int):
    __qualname__ = 'InteractionTestEvents'
    InteractionComplete = event_testing.test_events.TestEvent.InteractionComplete
    InteractionStart = event_testing.test_events.TestEvent.InteractionStart
    InteractionUpdate = event_testing.test_events.TestEvent.InteractionUpdate

class ParticipantRanInteractionTest(event_testing.test_base.BaseTest):
    __qualname__ = 'ParticipantRanInteractionTest'
    UNIQUE_TARGET_TRACKING_AVAILABLE = True
    UNIQUE_POSTURE_TRACKING_AVAILABLE = True
    TAG_CHECKLIST_TRACKING_AVAILABLE = True
    USES_EVENT_DATA = True
    FACTORY_TUNABLES = {'description': 'Check to see if the Sim ran an affordance as a particular actor', 'participant': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='This is the role the sim in question should be to pass.'), 'affordances': TunableList(TunableReference(services.affordance_manager()), description="The Sim must have run either any affordance or have a proxied affordance in this list or an interaction matching one of the tags in this tunable's Tags field."), 'interaction_outcome': OptionalTunable(TunableEnumEntry(OutcomeResult, OutcomeResult.NONE), description='participant type this interaction had to be run as.'), 'running_time': OptionalTunable(TunableSimMinute(description='\n            Amount of time in sim minutes that this interaction needs to\n            have been running for for this test to pass true.  This is not\n            a cumulative time that this particular interaction has been\n            run running, it is only counts consecutive time.  In addition,\n            this is checked at the end of an interaction and will not\n            trigger an objective when it would be completed.\n            ', default=10, minimum=0)), 'target_filters': TunableTuple(description='\n            Restrictions on the target of this interaction.\n            ', object_tags=OptionalTunable(description='\n                Object tags for limiting test success to a subset of target \n                objects.\n                ', tunable=TunableTuple(description='\n                    Target object tags and how they are tested.\n                    ', tag_set=TunableSet(description='\n                        A set of tags to test the target object for.\n                        ', tunable=TunableEnumEntry(description='\n                            A tag to test the target object for.\n                            ', tunable_type=Tag, default=Tag.INVALID)), test_type=TunableEnumEntry(description='\n                        How to test the tags in the tag set against the \n                        target object.\n                        ', tunable_type=TagTestType, default=TagTestType.CONTAINS_ANY_TAG_IN_SET)))), 'tags': TunableSet(TunableEnumEntry(Tag, Tag.INVALID), description='The Sim must have run either an interaction matching one of these Tags or an affordance from the list of Affordances in this tunable.'), 'test_event': TunableEnumEntry(description='\n            The event that we want to trigger this instance of the tuned\n            test on.\n            InteractionStart: Triggers when the interaction starts.\n            InteractionComplete: Triggers when the interaction ends.\n            InteractionUpdate: Triggers on a 15 sim minute cadence from the\n            start of the interaction.  If the interaction ends before a cycle\n            is up it does not trigger.  Do not use this for short interactions\n            as it has a possibility of never getting an update for an\n            interaction.\n            ', tunable_type=InteractionTestEvents, default=InteractionTestEvents.InteractionComplete), 'consider_cancelled_as_failure': Tunable(bool, True, description='\n            If True, test will consider the interaction outcome to be Failure if canceled by the user.\n            ')}

    def __init__(self, participant, affordances, interaction_outcome, running_time, target_filters, tags, test_event, consider_cancelled_as_failure, **kwargs):
        super().__init__(**kwargs)
        self.participant_type = participant
        self.affordances = affordances
        self.interaction_outcome = interaction_outcome
        if running_time is not None:
            self.running_time = interval_in_sim_minutes(running_time)
        else:
            self.running_time = None
        self.tags = tags
        self.object_tags = target_filters.object_tags
        if test_event == InteractionTestEvents.InteractionUpdate:
            self.test_events = (test_event, InteractionTestEvents.InteractionComplete)
        else:
            self.test_events = (test_event,)
        self.consider_cancelled_as_failure = consider_cancelled_as_failure

    def get_expected_args(self):
        return {'sims': event_testing.test_events.SIM_INSTANCE, 'interaction': event_testing.test_events.FROM_EVENT_DATA}

    @cached_test
    def __call__(self, sims=None, interaction=None):
        if interaction is None:
            return TestResult(False, 'No interaction found, this is normal during zone load.')
        for sim_info in sims:
            participant_type = interaction.get_participant_type(sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS))
            if participant_type is None:
                return TestResult(False, 'Failed participant check: {} is not an instanced sim.', sim_info)
            if participant_type != self.participant_type:
                return TestResult(False, 'Failed participant check: {} != {}', participant_type, self.participant_type)
            tag_match = len(self.tags & interaction.get_category_tags()) > 0 if self.tags else False
            if not tag_match and not (interaction.affordance in self.affordances or hasattr(interaction.affordance, 'proxied_affordance') and interaction.affordance.proxied_affordance in self.affordances):
                return TestResult(False, 'Failed affordance check: {} not in {}', interaction.affordance, self.affordances)
            if self.object_tags is not None and not self.target_matches_object_tags(interaction):
                return TestResult(False, "Target of interaction didn't match object tag requirement.")
            if self.interaction_outcome is not None:
                if self.consider_cancelled_as_failure and interaction.has_been_user_canceled and self.interaction_outcome != OutcomeResult.FAILURE:
                    return TestResult(False, 'Failed outcome check: interaction canceled by user treated as Failure')
                if self.interaction_outcome == OutcomeResult.SUCCESS:
                    if interaction.outcome_result == OutcomeResult.FAILURE:
                        return TestResult(False, 'Failed outcome check: interaction({}) failed when OutcomeResult Success or None required.', interaction.affordance)
                        if self.interaction_outcome != interaction.outcome_result:
                            return TestResult(False, 'Failed outcome check: interaction({}) result {} not {}', interaction.affordance, interaction.outcome_result, self.interaction_outcome)
                elif self.interaction_outcome != interaction.outcome_result:
                    return TestResult(False, 'Failed outcome check: interaction({}) result {} not {}', interaction.affordance, interaction.outcome_result, self.interaction_outcome)
            elif self.consider_cancelled_as_failure and interaction.has_been_user_canceled:
                return TestResult(False, 'Failed outcome check: interaction canceled by user treated as Failure')
            running_time = interaction.consecutive_running_time_span
            while self.running_time is not None and running_time < self.running_time:
                return TestResult(False, 'Failed hours check: {} < {}', running_time, self.running_time)
        return TestResult.TRUE

    def get_test_events_to_register(self):
        return ()

    def get_custom_event_registration_keys(self):
        keys = []
        for test_event in self.test_events:
            keys.extend([(test_event, affordance) for affordance in self.affordances])
            keys.extend([(test_event, tag) for tag in self.tags])
        return keys

    def get_target_id(self, sims=None, interaction=None, id_type=None):
        if interaction is None or interaction.target is None:
            return
        if id_type == TargetIdTypes.DEFAULT or id_type == TargetIdTypes.DEFINITION:
            if interaction.target.is_sim:
                return interaction.target.id
            return interaction.target.definition.id
        if id_type == TargetIdTypes.INSTANCE:
            return interaction.target.id
        if id_type == TargetIdTypes.HOUSEHOLD:
            if not interaction.target.is_sim:
                logger.error('Unique target ID type: {} is not supported for test: {} with an object as target.', id_type, self)
                return
            return interaction.target.household.id

    def get_posture_id(self, sims=None, interaction=None):
        if interaction is None or interaction.sim is None or interaction.sim.posture is None:
            return
        return interaction.sim.posture.guid64

    def get_tags(self, sims=None, interaction=None):
        if interaction is None:
            return ()
        return interaction.interaction_category_tags

    def tuning_is_valid(self):
        return len(self.tags) != 0 or len(self.affordances) != 0

    def target_matches_object_tags(self, interaction=None):
        if interaction is None or interaction.target is None or interaction.target.is_sim:
            return False
        object_id = interaction.target.definition.id
        target_object_tags = set(build_buy.get_object_all_tags(object_id))
        if self.object_tags.test_type == TagTestType.CONTAINS_ANY_TAG_IN_SET:
            return target_object_tags & self.object_tags.tag_set
        if self.object_tags.test_type == TagTestType.CONTAINS_ALL_TAGS_IN_SET:
            return target_object_tags & self.object_tags.tag_set == self.object_tags.tag_set
        if self.object_tags.test_type == TagTestType.CONTAINS_NO_TAGS_IN_SET:
            return not target_object_tags & self.object_tags.tag_set
        return False

TunableParticipantRanInteractionTest = TunableSingletonFactory.create_auto_factory(ParticipantRanInteractionTest)

class ParticipantStartedInteractionTest(event_testing.test_base.BaseTest):
    __qualname__ = 'ParticipantStartedInteractionTest'
    test_events = (event_testing.test_events.TestEvent.InteractionStart,)
    USES_EVENT_DATA = True
    FACTORY_TUNABLES = {'description': 'Check to see if the Sim started an affordance as a particular actor', 'participant': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='This is the role the sim in question should be to pass.'), 'affordances': TunableList(TunableReference(services.affordance_manager()), description="The Sim must have started either any affordance in this list or an interaction matching one of the tags in this tunable's Tags field."), 'tags': TunableSet(TunableEnumEntry(Tag, Tag.INVALID), description='The Sim must have run either an interaction matching one of these Tags or an affordance from the list of Affordances in this tunable.')}

    def __init__(self, participant, affordances, tags, **kwargs):
        super().__init__(**kwargs)
        self.participant_type = participant
        self.affordances = affordances
        self.tags = tags

    def get_test_events_to_register(self):
        return ()

    def get_custom_event_registration_keys(self):
        keys = [(TestEvent.InteractionStart, affordance) for affordance in self.affordances]
        keys.extend([(TestEvent.InteractionStart, tag) for tag in self.tags])
        return keys

    def get_expected_args(self):
        return {'sims': event_testing.test_events.SIM_INSTANCE, 'interaction': event_testing.test_events.FROM_EVENT_DATA}

    @cached_test
    def __call__(self, sims=None, interaction=None):
        if interaction is None:
            return TestResult(False, 'No interaction found, this is normal during zone load.')
        for sim_info in sims:
            participant_type = interaction.get_participant_type(sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS))
            if participant_type is None:
                return TestResult(False, 'Failed participant check: {} is not an instanced sim.', sim_info)
            if participant_type != self.participant_type:
                return TestResult(False, 'Failed participant check: {} != {}', participant_type, self.participant_type)
            tag_match = len(self.tags & interaction.get_category_tags()) > 0 if self.tags else False
            while not tag_match and interaction.affordance not in self.affordances:
                return TestResult(False, 'Failed affordance check: {} not in {}', interaction.affordance, self.affordances)
        return TestResult.TRUE

    def tuning_is_valid(self):
        return len(self.tags) != 0 or len(self.affordances) != 0

TunableParticipantStartedInteractionTest = TunableSingletonFactory.create_auto_factory(ParticipantStartedInteractionTest)

class SkillTestFactory(TunableFactory):
    __qualname__ = 'SkillTestFactory'

    @staticmethod
    def factory(skill_used, tags, skill_to_test):
        return skill_used is skill_to_test

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(skill_to_test=TunableReference(services.statistic_manager(), description='The skill used to earn the Simoleons, if applicable.'), **kwargs)

class TagSetTestFactory(TunableFactory):
    __qualname__ = 'TagSetTestFactory'

    @staticmethod
    def factory(skill_used, tags, tags_to_test):
        if tags is None:
            return False
        return len(set(tags) & tags_to_test) > 0

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(tags_to_test=TunableSet(TunableEnumEntry(Tag, Tag.INVALID), description='The tags on the object for selling.'), **kwargs)

class SimoleonsEarnedTest(event_testing.test_base.BaseTest):
    __qualname__ = 'SimoleonsEarnedTest'
    test_events = (event_testing.test_events.TestEvent.SimoleonsEarned,)
    USES_EVENT_DATA = True
    FACTORY_TUNABLES = {'description': 'Require the participant(s) to (each) earn a specific amount of Simoleons for a skill or tag on an object sold.', 'event_type_to_test': TunableVariant(skill_to_test=SkillTestFactory(), tags_to_test=TagSetTestFactory(), description='Test a skill for an event or tags on an object.'), 'threshold': TunableThreshold(description='Amount in Simoleons required to pass'), 'household_fund_threshold': OptionalTunable(description='\n            Restricts test success based on household funds.\n            ', tunable=TunableTuple(description='\n                Household fund threshold and moment of evaluation.\n                ', threshold=TunableThreshold(description='\n                    Amount of simoleons in household funds required to pass.\n                    '), test_before_earnings=Tunable(description='\n                    If True, threshold will be evaluated before funds were \n                    updated with earnings.\n                    ', tunable_type=bool, default=False)))}

    def __init__(self, event_type_to_test, threshold, household_fund_threshold, **kwargs):
        super().__init__(**kwargs)
        self.event_type_to_test = event_type_to_test
        self.threshold = threshold
        self.household_fund_threshold = household_fund_threshold

    def get_expected_args(self):
        return {'sims': event_testing.test_events.SIM_INSTANCE, 'amount': event_testing.test_events.FROM_EVENT_DATA, 'skill_used': event_testing.test_events.FROM_EVENT_DATA, 'tags': event_testing.test_events.FROM_EVENT_DATA}

    @cached_test
    def __call__(self, sims=None, amount=None, skill_used=None, tags=None):
        if amount is None:
            return TestResultNumeric(False, 'SimoleonsEarnedTest: amount is none, valid during zone load.', current_value=0, goal_value=self.threshold.value, is_money=True)
        if not self.threshold.compare(amount):
            return TestResultNumeric(False, 'SimoleonsEarnedTest: not enough Simoleons earned.', current_value=amount, goal_value=self.threshold.value, is_money=True)
        if not (self.event_type_to_test is not None and self.event_type_to_test(skill_used, tags)):
            return TestResult(False, '\n                    SimoleonsEarnedTest: the skill used to earn Simoleons does\n                    not match the desired skill or tuned tags do not match\n                    object tags.\n                    ')
        if self.household_fund_threshold is not None:
            for sim_info in sims:
                household = services.household_manager().get_by_sim_id(sim_info.sim_id)
                if household is None:
                    return TestResult(False, "Couldn't find household for sim {}", sim_info)
                household_funds = household.funds.money
                if self.household_fund_threshold.test_before_earnings:
                    household_funds -= amount
                while not self.household_fund_threshold.threshold.compare(household_funds):
                    return TestResult(False, 'Threshold test on household funds failed for sim {}', sim_info)
        return TestResult.TRUE

    def goal_value(self):
        return self.threshold.value

TunableSimoleonsEarnedTest = TunableSingletonFactory.create_auto_factory(SimoleonsEarnedTest)

class FamilyAspirationTriggerTest(event_testing.test_base.BaseTest):
    __qualname__ = 'FamilyAspirationTriggerTest'
    test_events = (event_testing.test_events.TestEvent.FamilyTrigger,)
    USES_EVENT_DATA = True
    FACTORY_TUNABLES = {'description': '\n            This is a special test used to receive the completion of a Familial\n            Aspiration. To properly use this test, one would create a Familial\n            Aspiration with an objective test on it, and tune the family\n            members who would care to receive it. Then create a new Aspiration\n            for the family members to receive it, and use this test to tune the\n            Familial Aspiration you created as the sender.\n        ', 'aspiration_trigger': TunableReference(description='\n            If this aspiration is completed because a family member completed\n            the corresponding trigger, the test will pass.\n            ', manager=services.get_instance_manager(sims4.resources.Types.ASPIRATION), class_restrictions='AspirationFamilialTrigger'), 'target_family_relationships': TunableSet(description='\n            These relationship bits will get an event message upon Aspiration\n            completion that they can test for.\n            ', tunable=TunableReference(manager=services.relationship_bit_manager()))}

    def __init__(self, aspiration_trigger, target_family_relationships, **kwargs):
        super().__init__(**kwargs)
        self.aspiration_trigger = aspiration_trigger
        self.target_family_relationships = target_family_relationships

    def get_expected_args(self):
        return {'sim_infos': ParticipantType.Actor, 'trigger': event_testing.test_events.FROM_EVENT_DATA}

    @cached_test
    def __call__(self, sim_infos=None, trigger=None):
        if trigger is None:
            if sim_infos is not None:
                for sim_info in sim_infos:
                    for relationship in sim_info.relationship_tracker:
                        for relationship_bit in self.target_family_relationships:
                            while relationship.has_bit(relationship_bit):
                                target_sim_info = relationship.find_target_sim_info()
                                if target_sim_info.aspiration_tracker.milestone_completed(self.aspiration_trigger.guid64):
                                    return TestResult.TRUE
            return TestResult(False, 'FamilyAspirationTriggerTest: No valid sims with the aspiration found.')
        if self.aspiration_trigger.guid64 == trigger.guid64:
            return TestResult.TRUE
        return TestResult(False, 'FamilyAspirationTriggerTest: Tuned trigger {} does not match event trigger {}.', self.aspiration_trigger, trigger)

TunableFamilyAspirationTriggerTest = TunableSingletonFactory.create_auto_factory(FamilyAspirationTriggerTest)

class WhimCompletedTest(event_testing.test_base.BaseTest):
    __qualname__ = 'WhimCompletedTest'
    test_events = (event_testing.test_events.TestEvent.WhimCompleted,)
    USES_EVENT_DATA = True
    FACTORY_TUNABLES = {'description': 'This test checks for a specific tuned Whim Goal to have been completed,\n        or if not specific goal is tuned here, then completing any Whim Goal will result in this test\n        firing and resulting in a True result.', 'whim_to_check': TunableReference(description='\n            This is the whim to check for matching the completed whim, resulting in passing test.\n            ', manager=services.get_instance_manager(sims4.resources.Types.SITUATION_GOAL))}

    def __init__(self, whim_to_check=None, **kwargs):
        super().__init__(**kwargs)
        self.whim_to_check = whim_to_check

    def get_expected_args(self):
        return {'whim_completed': event_testing.test_events.FROM_EVENT_DATA}

    @cached_test
    def __call__(self, whim_completed=None):
        if whim_completed is None:
            return TestResult(False, 'WhimCompletedTest: Whim is empty, valid during zone load.')
        if self.whim_to_check is not None and self.whim_to_check.guid64 != whim_completed.guid64:
            return TestResult(False, 'WhimCompletedTest: Tuned whim to check {} does not match completed whim {}.', self.whim_to_check, whim_completed)
        return TestResult.TRUE

TunableWhimCompletedTest = TunableSingletonFactory.create_auto_factory(WhimCompletedTest)

class OffspringCreatedTest(HasTunableSingletonFactory, AutoFactoryInit, event_testing.test_base.BaseTest):
    __qualname__ = 'OffspringCreatedTest'
    test_events = (event_testing.test_events.TestEvent.OffspringCreated,)
    USES_EVENT_DATA = True
    FACTORY_TUNABLES = {'description': 'This test checks for a tuned number of offspring to have been created upon\n        the moment of the DeliverBabySuperInteraction completion.', 'offspring_threshold': TunableThreshold(description='\n            The comparison of amount of offspring created to the number desired.\n            ')}

    def get_expected_args(self):
        return {'offspring_created': event_testing.test_events.FROM_EVENT_DATA}

    @cached_test
    def __call__(self, offspring_created=None):
        if offspring_created is None:
            return TestResult(False, 'OffspringCreatedTest: Offspring count is empty, valid during zone load.')
        if not self.offspring_threshold.compare(offspring_created):
            return TestResult(False, 'OffspringCreatedTest: Not the desired amount of offspring created. {} {}', offspring_created, self.offspring_threshold)
        return TestResult.TRUE

class CareerAttendenceTest(event_testing.test_base.BaseTest):
    __qualname__ = 'CareerAttendenceTest'
    test_events = (event_testing.test_events.TestEvent.WorkdayComplete,)
    USES_DATA_OBJECT = True
    USES_EVENT_DATA = True
    FACTORY_TUNABLES = {'description': 'After a work day completes, did your sim work a desired of hours, earn a tuned amount (total over lifetime),                            at a specific or any career. Note: any career (leaving career untuned) means it checks against total of all of them.', 'career_to_test': TunableReference(manager=services.get_instance_manager(sims4.resources.Types.CAREER)), 'career_category': TunableEnumEntry(careers.career_tuning.CareerCategory, careers.career_tuning.CareerCategory.Invalid, description='Category the specified career is required to be in order to pass validation'), 'simoleons_earned': TunableThreshold(description='Amount in Simoleons required to pass'), 'hours_worked': TunableThreshold(description='Amount in hours required to pass')}

    def __init__(self, career_to_test, career_category, simoleons_earned, hours_worked, **kwargs):
        super().__init__(**kwargs)
        self.career_to_test = career_to_test
        self.simoleons_earned = simoleons_earned
        self.hours_worked = hours_worked
        self.career_category = career_category

    def get_expected_args(self):
        return {'career': event_testing.test_events.FROM_EVENT_DATA, 'data': event_testing.test_events.FROM_DATA_OBJECT, 'objective_guid64': event_testing.test_events.OBJECTIVE_GUID64}

    @cached_test
    def __call__(self, career=None, data=None, objective_guid64=None):
        if career is None:
            return TestResult(False, 'Career provided is None, valid during zone load.')
        total_money_made = 0
        total_time_worked = 0
        if not isinstance(career, self.career_to_test):
            return TestResult(False, '{} does not match tuned value {}', career, self.career_to_test)
        career_data = data.get_career_data(career)
        total_money_made = career_data.get_money_earned()
        total_time_worked = career_data.get_hours_worked()
        relative_start_values = data.get_starting_values(objective_guid64)
        money = 0
        time = 1
        total_money_made -= relative_start_values[money]
        total_time_worked -= relative_start_values[time]
        if not (self.career_to_test is not None and relative_start_values is not None and self.simoleons_earned.compare(total_money_made)):
            return TestResultNumeric(False, 'CareerAttendenceTest: not the desired amount of Simoleons.', current_value=total_money_made, goal_value=self.simoleons_earned.value, is_money=True)
        if not self.hours_worked.compare(total_time_worked):
            return TestResultNumeric(False, 'CareerAttendenceTest: not the desired amount of time worked.', current_value=total_time_worked, goal_value=self.hours_worked.value, is_money=False)
        return TestResult.TRUE

    def save_relative_start_values(self, objective_guid64, data_object):
        if self.career_to_test is not None:
            return
        career_name = self.career_to_test.__name__
        start_money = data_object.get_career_data_by_name(career_name).get_money_earned()
        start_time = data_object.get_career_data_by_name(career_name).get_hours_worked()
        data_object.set_starting_values(objective_guid64, [start_money, start_time])

TunableCareerAttendenceTest = TunableSingletonFactory.create_auto_factory(CareerAttendenceTest)

class TotalRelationshipBitTest(event_testing.test_base.BaseTest):
    __qualname__ = 'TotalRelationshipBitTest'
    test_events = (TestEvent.AddRelationshipBit,)
    USES_DATA_OBJECT = True
    FACTORY_TUNABLES = {'description': 'Gate availability by a relationship status.', 'use_current_relationships': Tunable(bool, False, description='Use the current number of relationships held at this bit rather than the total number ever had.'), 'relationship_bits': TunableSet(TunableReference(services.relationship_bit_manager(), description='The relationship bit that will be checked.', class_restrictions='RelationshipBit')), 'num_relations': TunableThreshold(description='Number of Sims with specified relationships required to pass.')}

    def __init__(self, use_current_relationships, relationship_bits, num_relations, **kwargs):
        super().__init__(**kwargs)
        self.use_current_relationships = use_current_relationships
        self.relationship_bits = relationship_bits
        self.num_relations = num_relations

    def get_expected_args(self):
        return {'data_object': event_testing.test_events.FROM_DATA_OBJECT, 'objective_guid64': event_testing.test_events.OBJECTIVE_GUID64}

    @cached_test
    def __call__(self, data_object=None, objective_guid64=None):
        current_relationships = 0
        for relationship_bit in self.relationship_bits:
            if self.use_current_relationships:
                current_relationships += data_object.get_current_total_relationships(relationship_bit)
            else:
                current_relationships += data_object.get_total_relationships(relationship_bit)
        relative_start_value = data_object.get_starting_values(objective_guid64)
        if relative_start_value is not None:
            relations = 0
            current_relationships -= relative_start_value[relations]
        if not self.num_relations.compare(current_relationships):
            return TestResultNumeric(False, 'TotalRelationshipBitTest: Not enough relationships.', current_value=current_relationships, goal_value=self.num_relations.value, is_money=False)
        return TestResult.TRUE

    def save_relative_start_values(self, objective_guid64, data_object):
        current_relationships = 0
        for relationship_bit in self.relationship_bits:
            if self.use_current_relationships:
                current_relationships += data_object.get_current_total_relationships(relationship_bit)
            else:
                current_relationships += data_object.get_total_relationships(relationship_bit)
        data_object.set_starting_values(objective_guid64, [current_relationships])

    def tuning_is_valid(self):
        if self.relationship_bits:
            return True
        return False

    def goal_value(self):
        return self.num_relations.value

TunableTotalRelationshipBitTest = TunableSingletonFactory.create_auto_factory(TotalRelationshipBitTest)

class TotalTravelTest(event_testing.test_base.BaseTest):
    __qualname__ = 'TotalTravelTest'
    test_events = (TestEvent.SimTravel,)
    USES_DATA_OBJECT = True
    FACTORY_TUNABLES = {'description': 'Gate availability by a relationship status.', 'number_of_unique_lots': Tunable(description='\n            The number of unique lots that this account has traveled to in order for this test to pass.', tunable_type=int, default=0)}

    def __init__(self, number_of_unique_lots, **kwargs):
        super().__init__(**kwargs)
        self.number_of_unique_lots = number_of_unique_lots

    def get_expected_args(self):
        return {'data_object': event_testing.test_events.FROM_DATA_OBJECT, 'objective_guid64': event_testing.test_events.OBJECTIVE_GUID64}

    @cached_test
    def __call__(self, sims=None, data_object=None, objective_guid64=None):
        zones_traveled = data_object.get_zones_traveled()
        relative_start_value = data_object.get_starting_values(objective_guid64)
        if relative_start_value is not None:
            zones = 0
            zones_traveled -= relative_start_value[zones]
        if zones_traveled >= self.number_of_unique_lots:
            return TestResult.TRUE
        return TestResultNumeric(False, 'TotalTravelTest: Not enough zones traveled to.', current_value=zones_traveled, goal_value=self.number_of_unique_lots, is_money=False)

    def save_relative_start_values(self, objective_guid64, data_object):
        zones_traveled = data_object.get_zones_traveled()
        data_object.set_starting_values(objective_guid64, [zones_traveled])

    def goal_value(self):
        return self.number_of_unique_lots

TunableTotalTravelTest = TunableSingletonFactory.create_auto_factory(TotalTravelTest)

class BuffForAmountOfTimeTest(event_testing.test_base.BaseTest):
    __qualname__ = 'BuffForAmountOfTimeTest'
    test_events = (TestEvent.BuffEndedEvent, TestEvent.BuffUpdateEvent)
    USES_DATA_OBJECT = True
    USES_EVENT_DATA = True

    class BuffTestType(enum.Int):
        __qualname__ = 'BuffForAmountOfTimeTest.BuffTestType'
        ANY_SINGLE_BUFF = 0
        SUM_OF_BUFFS = 1

    FACTORY_TUNABLES = {'description': 'Test for the total amount of time that this buff has been on sims on this account.', 'buff_to_check': TunableList(TunableReference(services.get_instance_manager(sims4.resources.Types.BUFF), description='Buff checked for this test.')), 'length_of_time': TunableSimMinute(1, description='The total length of time that should be checked against.'), 'buff_test_type': TunableEnumEntry(description='\n            The type determines how to handle multiple buffs in the list. "Any\n            single buff" will test for the time threshold in each listed buff\n            and return true if one meets it. "Sum of buffs" will add the time\n            stored for each buff and test against the total. Note that using\n            SUM OF BUFFS will accumulate time for all buffs in the list and\n            does not separate out overlaps. So if two buffs in the list are on\n            the Sim, time will accumulate twice as much during that period.\n            ', tunable_type=BuffTestType, default=BuffTestType.ANY_SINGLE_BUFF)}

    def __init__(self, buff_to_check, length_of_time, buff_test_type, **kwargs):
        super().__init__(**kwargs)
        self.buffs_to_check = buff_to_check
        self.length_of_time = interval_in_sim_minutes(length_of_time)
        self.buff_test_type = buff_test_type

    def get_expected_args(self):
        return {'buff': event_testing.test_events.FROM_EVENT_DATA, 'data_object': event_testing.test_events.FROM_DATA_OBJECT, 'objective_guid64': event_testing.test_events.OBJECTIVE_GUID64}

    @cached_test
    def __call__(self, buff=None, data_object=None, objective_guid64=None):
        if buff is None:
            return TestResult(False, 'Buff provided is None, valid during zone load.')
        if buff not in self.buffs_to_check:
            return TestResult(False, 'Buff provided is not among the buffs you are looking for.')
        buff_uptime = TimeSpan(0)
        if self.buff_test_type == self.BuffTestType.SUM_OF_BUFFS:
            for buff_tuning in self.buffs_to_check:
                buff_uptime += data_object.get_total_buff_uptime(buff_tuning)
        else:
            buff_uptime = data_object.get_total_buff_uptime(buff)
        relative_start_value = data_object.get_starting_values(objective_guid64)
        if relative_start_value is not None:
            ticks = 0
            buff_uptime -= TimeSpan(relative_start_value[ticks])
        if buff_uptime >= self.length_of_time:
            return TestResult.TRUE
        run_time = self.length_of_time.in_hours() - (self.length_of_time - buff_uptime).in_hours()
        return TestResultNumeric(False, 'BuffForAmountOfTimeTest: Buff has not existed long enough.', current_value=run_time, goal_value=self.length_of_time.in_hours(), is_money=False)

    def save_relative_start_values(self, objective_guid64, data_object):
        buff_uptime = TimeSpan(0)
        for buff_tuning in self.buffs_to_check:
            buff_uptime += data_object.get_total_buff_uptime(buff_tuning)
        data_object.set_starting_values(objective_guid64, [buff_uptime.in_ticks()])

    def tuning_is_valid(self):
        return len(self.buffs_to_check) > 0

    def goal_value(self):
        return self.length_of_time.in_hours()

TunableBuffForAmountOfTimeTest = TunableSingletonFactory.create_auto_factory(BuffForAmountOfTimeTest)

class TotalSimoleonsEarnedByTagTest(event_testing.test_base.BaseTest):
    __qualname__ = 'TotalSimoleonsEarnedByTagTest'
    test_events = (TestEvent.SimoleonsEarned,)
    USES_DATA_OBJECT = True
    FACTORY_TUNABLES = {'description': 'Test for the total simoleons earned by selling objects tagged with tag_to_test.', 'tag_to_test': TunableEnumEntry(Tag, Tag.INVALID, description='The tags on the objects for selling.'), 'threshold': TunableThreshold(description='Amount in Simoleons required to pass')}

    def __init__(self, tag_to_test, threshold, **kwargs):
        super().__init__(**kwargs)
        self.tag_to_test = tag_to_test
        self.threshold = threshold

    def get_expected_args(self):
        return {'data_object': event_testing.test_events.FROM_DATA_OBJECT, 'objective_guid64': event_testing.test_events.OBJECTIVE_GUID64}

    @cached_test
    def __call__(self, data_object=None, objective_guid64=None):
        total_simoleons_earned = data_object.get_total_tag_simoleons_earned(self.tag_to_test)
        relative_start_value = data_object.get_starting_values(objective_guid64)
        if relative_start_value is not None:
            simoleons = 0
            total_simoleons_earned -= relative_start_value[simoleons]
        if self.threshold.compare(total_simoleons_earned):
            return TestResult.TRUE
        return TestResultNumeric(False, 'TotalSimoleonsEarnedByTagTest: Not enough Simoleons earned on tag{}.', self.tag_to_test, current_value=total_simoleons_earned, goal_value=self.threshold.value, is_money=True)

    def save_relative_start_values(self, objective_guid64, data_object):
        total_simoleons_earned = data_object.get_total_tag_simoleons_earned(self.tag_to_test)
        data_object.set_starting_values(objective_guid64, [total_simoleons_earned])

    def tuning_is_valid(self):
        return self.tag_to_test is not Tag.INVALID and self.threshold.value != 0

    def goal_value(self):
        return self.threshold.value

TunableTotalSimoleonsEarnedByTagTest = TunableSingletonFactory.create_auto_factory(TotalSimoleonsEarnedByTagTest)

class TotalTimeElapsedByTagTest(event_testing.test_base.BaseTest):
    __qualname__ = 'TotalTimeElapsedByTagTest'
    test_events = (TestEvent.InteractionComplete, TestEvent.InteractionUpdate)
    USES_DATA_OBJECT = True
    FACTORY_TUNABLES = {'description': 'Test for the total amount of time that interactions with tag_to_test has elapsed.', 'tag_to_test': TunableEnumEntry(Tag, Tag.INVALID, description='The tag on the interactions.'), 'length_of_time': TunableSimMinute(1, description='The total length of time that should be checked against.')}

    def __init__(self, tag_to_test, length_of_time, **kwargs):
        super().__init__(**kwargs)
        self.tag_to_test = tag_to_test
        self.length_of_time = interval_in_sim_minutes(length_of_time)

    def get_test_events_to_register(self):
        return ()

    def get_custom_event_registration_keys(self):
        return [(TestEvent.InteractionComplete, self.tag_to_test), (TestEvent.InteractionUpdate, self.tag_to_test)]

    def get_expected_args(self):
        return {'data_object': event_testing.test_events.FROM_DATA_OBJECT, 'objective_guid64': event_testing.test_events.OBJECTIVE_GUID64}

    @cached_test
    def __call__(self, data_object=None, objective_guid64=None):
        total_time_elapsed = data_object.get_total_tag_interaction_time_elapsed(self.tag_to_test)
        relative_start_value = data_object.get_starting_values(objective_guid64)
        if relative_start_value is not None:
            time = 0
            total_time_elapsed -= interval_in_sim_minutes(relative_start_value[time])
        if total_time_elapsed >= self.length_of_time:
            return TestResult.TRUE
        return TestResultNumeric(False, 'TotalTimeElapsedByTagTest: Not enough time elapsed on tag{}.', self.tag_to_test, current_value=total_time_elapsed.in_hours(), goal_value=self.length_of_time.in_hours(), is_money=False)

    def save_relative_start_values(self, objective_guid64, data_object):
        total_time_elapsed = data_object.get_total_tag_interaction_time_elapsed(self.tag_to_test)
        data_object.set_starting_values(objective_guid64, [int(total_time_elapsed.in_minutes())])

    def tuning_is_valid(self):
        return self.tag_to_test is not Tag.INVALID

    def goal_value(self):
        return self.length_of_time.in_hours()

TunableTotalTimeElapsedByTagTest = TunableSingletonFactory.create_auto_factory(TotalTimeElapsedByTagTest)
