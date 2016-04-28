import math
import random
from relationships.relationship_track import RelationshipTrack
from sims4.tuning.instances import TunedInstanceMetaclass
from sims4.tuning.tunable import TunableReference, Tunable, TunableEnumEntry, TunableList, TunableVariant, TunableTuple, TunableInterval, HasTunableSingletonFactory, HasTunableReference, TunableSet, OptionalTunable
import filters.household_template
import services
import sims.sim_info_types
import sims4.log
import sims4.resources
import statistics.skill
logger = sims4.log.Logger('SimFilter')

class FilterResult:
    __qualname__ = 'FilterResult'
    TRUE = None

    def __init__(self, *args, score=1, sim_info=None, conflicting_career_track_id=None):
        if args:
            (self._reason, self._format_args) = (args[0], args[1:])
        else:
            (self._reason, self._format_args) = (None, ())
        self.score = score
        self.sim_info = sim_info
        self.conflicting_career_track_id = conflicting_career_track_id

    @property
    def reason(self):
        if self._format_args and self._reason:
            self._reason = self._reason.format(self._format_args)
            self._format_args = ()
        return self._reason

    def __str__(self):
        if self.reason:
            return self.reason
        return str(self.score)

    def __repr__(self):
        if self.reason:
            return '<FilterResult: sim_info {0} score{1} reason {2}>'.format(self.sim_info, self.score, self.reason)
        return '<FilterResult: sim_info {0} score{1}>'.format(self.sim_info, self.score)

    def __bool__(self):
        return self.score != 0

    def combine_with_other_filter_result(self, other):
        if self.sim_info is not None:
            if self.sim_info != other.sim_info:
                raise AssertionError('Attempting to combine filter results between 2 different sim infos: {} and {}'.format(self.sim_info, other.sim_info))
        else:
            self.sim_info = other.sim_info
        if self._reason is None:
            self._reason = other._reason
            self._format_args = other._format_args
        if self.conflicting_career_track_id is None:
            self.conflicting_career_track_id = other.conflicting_career_track_id

FilterResult.TRUE = FilterResult()

class TunableBaseFilterTerm(HasTunableSingletonFactory):
    __qualname__ = 'TunableBaseFilterTerm'

    def calculate_score(self, **kwargs):
        raise NotImplementedError

    def conform_sim_creator_to_filter_term(self, **kwargs):
        return FilterResult.TRUE

    def conform_sim_info_to_filter_term(self, **kwargs):
        return FilterResult.TRUE

class TunableInvertibleFilterTerm(TunableBaseFilterTerm):
    __qualname__ = 'TunableInvertibleFilterTerm'
    FACTORY_TUNABLES = {'invert_score': Tunable(description='\n                Invert the score so that the filter term will score is the\n                opposite of what the score would be.  For example, if sim is\n                busy, normally would return 1, but if checked value would return\n                0 and would not be chosen by filter system.\n                ', tunable_type=bool, default=False)}

    def __init__(self, invert_score=False):
        self._invert_score = invert_score

    def invert_score_if_necessary(self, score):
        if self._invert_score:
            return 1 - score
        return score

def calculate_score_from_value(value, min_value, max_value, ideal_value):
    if ideal_value == value:
        return 1
    min_value -= 1
    max_value += 1
    score = 0
    if value < ideal_value:
        score = (value - min_value)/(ideal_value - min_value)
    else:
        score = (max_value - value)/(max_value - ideal_value)
    return max(0, min(1, score))

class TunableSkillFilterTerm(TunableInvertibleFilterTerm):
    __qualname__ = 'TunableSkillFilterTerm'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value._ideal_value < value._min_value or value._ideal_value > value._max_value:
            logger.error('TunableSkillFilterTerm {} has a filter term {} that is tuned with ideal_value {} outside of the minimum and maximum bounds [{}, {}].'.format(source, tunable_name, value._ideal_value, value._min_value, value._max_value))

    FACTORY_TUNABLES = {'skill': TunableReference(services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions=statistics.skill.Skill, description='The skill the range applies to.'), 'min_value': Tunable(int, 0, description='Minimum value of the skill that we are filtering against.'), 'max_value': Tunable(int, 10, description='Maximum value of the skill that we are filtering against.'), 'ideal_value': Tunable(int, 5, description='Ideal value of the skill that we are filtering against.'), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, skill, min_value, max_value, ideal_value, **kwargs):
        super().__init__(**kwargs)
        self._skill = skill
        self._min_value = min_value
        self._max_value = max_value
        self._ideal_value = ideal_value

    def calculate_score(self, sim_info, **kwargs):
        tracker = sim_info.get_tracker(self._skill)
        value = tracker.get_user_value(self._skill)
        score = calculate_score_from_value(value, self._min_value, self._max_value, self._ideal_value)
        return FilterResult(score=self.invert_score_if_necessary(score), sim_info=sim_info)

    def conform_sim_info_to_filter_term(self, created_sim_info, **kwargs):
        if not self._skill.can_add(created_sim_info):
            return FilterResult('Unable to add Skill due to entitlement restriction {}.', self._skill, score=0, sim_info=created_sim_info)
        skill_value = created_sim_info.get_stat_value(self._skill)
        if skill_value is None:
            current_user_value = self._skill.convert_to_user_value(self._skill.initial_value)
        else:
            current_user_value = self._skill.convert_to_user_value(skill_value)
        if self._invert_score != self._min_value <= current_user_value <= self._max_value:
            return FilterResult.TRUE
        if self._invert_score:
            min_range = self._min_value - self._skill.min_value_tuning
            max_range = self._skill.max_value_tuning - self._max_value
            if min_range <= 0 and max_range > 0:
                skill_user_value = random.randint(self._max_value, self._skill.max_value_tuning)
            elif min_range > 0 and max_range <= 0:
                skill_user_value = random.randint(self._skill.min_value_tuning, self._min_value)
            elif min_range > 0 and max_range > 0:
                chosen_level = random.randint(0, min_range + max_range)
                if chosen_level > min_range:
                    skill_user_value = chosen_level - min_range + self._max_value
                else:
                    skill_user_value = chosen_level + self._skill.min_value_tuning
                    FilterResult('Failed to add proper skill level to sim.', sim_info=created_sim_info, score=0)
            else:
                FilterResult('Failed to add proper skill level to sim.', sim_info=created_sim_info, score=0)
        elif self._min_value == self._max_value:
            skill_user_value = self._ideal_value
        else:
            skill_user_value = round(random.triangular(self._min_value, self._max_value, self._ideal_value))
        skill_value = self._skill.convert_from_user_value(skill_user_value)
        created_sim_info.add_statistic(self._skill, skill_value)
        return FilterResult.TRUE

class TunableTraitFilterTerm(TunableInvertibleFilterTerm):
    __qualname__ = 'TunableTraitFilterTerm'
    FACTORY_TUNABLES = {'trait': TunableReference(services.get_instance_manager(sims4.resources.Types.TRAIT), description='The skill the range applies to.')}

    def __init__(self, trait, **kwargs):
        super().__init__(**kwargs)
        self._trait = trait

    def calculate_score(self, sim_info, **kwargs):
        score = 0
        if sim_info.trait_tracker.has_trait(self._trait):
            score = 1
        return FilterResult(score=self.invert_score_if_necessary(score), sim_info=sim_info)

    def conform_sim_info_to_filter_term(self, created_sim_info, **kwargs):
        if self._invert_score != created_sim_info.trait_tracker.has_trait(self._trait):
            return FilterResult.TRUE
        if self._invert_score:
            if not created_sim_info.trait_tracker.remove_trait(self._trait):
                return FilterResult('Failed conform sim to filter by removing trait {}', self._trait, sim_info=created_sim_info, score=0)
        elif not created_sim_info.trait_tracker.add_trait(self._trait):
            return FilterResult('Failed conform sim to filter by adding trait {}', self._trait, sim_info=created_sim_info, score=0)
        return FilterResult.TRUE

class TunableAgeFilterTerm(TunableInvertibleFilterTerm):
    __qualname__ = 'TunableAgeFilterTerm'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value._ideal_value < value._min_value or value._ideal_value > value._max_value:
            logger.error('TunableAgeFilterTerm {} has a filter term {} that is tuned with ideal_value {} outside of the minimum and maximum bounds [{}, {}].'.format(source, tunable_name, value._ideal_value, value._min_value, value._max_value))

    FACTORY_TUNABLES = {'min_value': TunableEnumEntry(sims.sim_info_types.Age, sims.sim_info_types.Age.BABY, description='The minimum gender of the sim we are filtering for.'), 'max_value': TunableEnumEntry(sims.sim_info_types.Age, sims.sim_info_types.Age.ELDER, description='The maximum gender of the sim we are filtering for.'), 'ideal_value': TunableEnumEntry(sims.sim_info_types.Age, sims.sim_info_types.Age.ADULT, description='The ideal gender of the sim we are filtering for.'), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, min_value, max_value, ideal_value, **kwargs):
        super().__init__(**kwargs)
        self._min_value = min_value
        self._max_value = max_value
        self._ideal_value = ideal_value
        self._min_value_int = int(math.log(int(min_value), 2))
        self._max_value_int = int(math.log(int(max_value), 2))
        self._ideal_value_int = int(math.log(int(ideal_value), 2))

    def calculate_score(self, sim_info, **kwargs):
        value = int(math.log(int(sim_info.age), 2))
        score = calculate_score_from_value(value, self._min_value_int, self._max_value_int, self._ideal_value_int)
        return FilterResult(score=self.invert_score_if_necessary(score), sim_info=sim_info)

    def conform_sim_creator_to_filter_term(self, sim_creator, **kwargs):
        if self._invert_score and sim_creator.age != self._ideal_value != self._min_value <= sim_creator.age <= self._max_value:
            return FilterResult.TRUE
        if self._invert_score:
            if self._min_value == sim_creator.age == self._max_value:
                return FilterResult('Cannot find valid age in order to conform sim to age filter term.', score=0)
            if self._min_value == sim_creator.age:
                sim_creator.age = self._max_value
            elif self._max_value == sim_creator.age:
                sim_creator.age = self._min_value
            else:
                sim_creator.age = random.choice([self._min_value, self._max_value])
        else:
            sim_creator.age = self._ideal_value
        return FilterResult.TRUE

class TunableGenderFilterTerm(TunableBaseFilterTerm):
    __qualname__ = 'TunableGenderFilterTerm'
    FACTORY_TUNABLES = {'gender': TunableEnumEntry(sims.sim_info_types.Gender, sims.sim_info_types.Gender.MALE, description='The required gender of the sim we are filtering for.')}

    def __init__(self, gender, **kwargs):
        self._gender = gender

    def calculate_score(self, sim_info, **kwargs):
        if sim_info.gender is self._gender:
            return FilterResult(score=1, sim_info=sim_info)
        return FilterResult(score=0, sim_info=sim_info)

    def conform_sim_creator_to_filter_term(self, sim_creator, **kwargs):
        sim_creator.gender = self._gender
        return FilterResult.TRUE

class TunableIsBusyFilterTerm(TunableInvertibleFilterTerm):
    __qualname__ = 'TunableIsBusyFilterTerm'
    FACTORY_TUNABLES = {'selectable_sim_override': Tunable(bool, False, description='\n                If checked then selectable sims will always be considered not\n                busy.\n                ')}

    def __init__(self, selectable_sim_override, **kwargs):
        super().__init__(**kwargs)
        self._selectable_sim_override = selectable_sim_override

    def calculate_score(self, sim_info, start_time_ticks=None, end_time_ticks=None, **kwargs):
        is_busy = 0
        for career in sim_info.career_tracker.careers.values():
            busy_times = career.get_busy_time_periods()
            if start_time_ticks is not None and end_time_ticks is not None:
                for (busy_start_time, busy_end_time) in busy_times:
                    while start_time_ticks <= busy_end_time and end_time_ticks >= busy_start_time:
                        is_busy = 1
                        break
            else:
                current_time = services.time_service().sim_now
                current_time_in_ticks = current_time.time_since_beginning_of_week().absolute_ticks()
                for (busy_start_time, busy_end_time) in busy_times:
                    while busy_start_time <= current_time_in_ticks <= busy_end_time:
                        is_busy = 1
                        break
        score = self.invert_score_if_necessary(is_busy)
        if self._selectable_sim_override and sim_info.is_selectable and is_busy:
            return FilterResult(sim_info=sim_info, conflicting_career_track_id=career.current_track_tuning.guid64)
        return FilterResult(score=score, sim_info=sim_info)

    def conform_sim_info_to_filter_term(self, created_sim_info, **kwargs):
        return self.calculate_score(created_sim_info, **kwargs)

class TunableInFamily(TunableInvertibleFilterTerm):
    __qualname__ = 'TunableInFamily'

    def calculate_score(self, sim_info, household_id=0, **kwargs):
        score = 1 if sim_info.household_id == household_id else 0
        return FilterResult(score=self.invert_score_if_necessary(score), sim_info=sim_info)

    def conform_sim_creator_to_filter_term(self, **kwargs):
        if not self._invert_score:
            return FilterResult('Unable to create a sim in a household.', score=0)
        return FilterResult.TRUE

class TunableIsDead(TunableInvertibleFilterTerm):
    __qualname__ = 'TunableIsDead'

    def calculate_score(self, sim_info, **kwargs):
        score = 1 if sim_info.is_dead else 0
        return FilterResult(score=self.invert_score_if_necessary(score), sim_info=sim_info)

    def conform_sim_creator_to_filter_term(self, **kwargs):
        if not self._invert_score:
            return FilterResult('Unable to create a dead sim.', score=0)
        return FilterResult.TRUE

class TunableRelationshipBit(TunableBaseFilterTerm):
    __qualname__ = 'TunableRelationshipBit'
    FACTORY_TUNABLES = {'white_list': TunableSet(description='\n                A set of relationship bits that requires the requesting sim to\n                have at least one matching relationship bit with the sims we\n                are scoring.\n                ', tunable=TunableReference(description='\n                    A relationship bit that we will use to check if the\n                    requesting sim has it with the sim we are scoring.\n                    ', manager=services.get_instance_manager(sims4.resources.Types.RELATIONSHIP_BIT))), 'black_list': TunableSet(description='\n                A set of relationship bits that requires the requesting sim to\n                not have any one matching relationship bits with the sims we\n                are scoring.\n                ', tunable=TunableReference(description='\n                    A relationship bit that we will use to check if the\n                    requesting sim has it with the sim we are scoring.\n                    ', manager=services.get_instance_manager(sims4.resources.Types.RELATIONSHIP_BIT))), 'consider_other_sim': Tunable(description="\n                Whether we should consider the other sim in the relationship. \n                If the value is True, we use the relationship bits between the\n                two sims. If the value is False, we use all the relationship \n                bits for all of the sim's relationships to compare against the\n                black and white lists.\n                ", tunable_type=bool, default=True), 'living_status': Tunable(description='\n                If true then we will only look at relationships with living\n                sims.  If false then we will only look at relationships with\n                dead sims.\n                ', tunable_type=bool, default=True), 'requesting_sim_override': Tunable(description='\n                If checked then the filter term will always return 1 if the\n                requesting sim info is the sim info we are looking at.\n                ', tunable_type=bool, default=False)}

    def __init__(self, white_list, black_list, consider_other_sim, living_status, requesting_sim_override, **kwargs):
        self._white_list = white_list
        self._black_list = black_list
        self._consider_other_sim = consider_other_sim
        self._living_status = living_status
        self._requesting_sim_override = requesting_sim_override

    def calculate_score(self, sim_info, requesting_sim_info=None, **kwargs):
        if not requesting_sim_info:
            return FilterResult(score=0, sim_info=sim_info)
        if self._requesting_sim_override and sim_info is requesting_sim_info:
            return FilterResult(score=1, sim_info=sim_info)
        other_sim_id = requesting_sim_info.id if self._consider_other_sim else None
        relationship_bits = set(sim_info.relationship_tracker.get_all_bits(target_sim_id=other_sim_id, allow_dead_targets=not self._living_status, allow_living_targets=self._living_status))
        if self._white_list and not relationship_bits & self._white_list:
            return FilterResult(score=0, sim_info=sim_info)
        if self._black_list and relationship_bits & self._black_list:
            return FilterResult(score=0, sim_info=sim_info)
        return FilterResult(score=1, sim_info=sim_info)

    def conform_sim_creator_to_filter_term(self, requesting_sim_info=None, **kwargs):
        if requesting_sim_info is None:
            return FilterResult('Unable to create sims with specific relationship-- requesting sim info is required', score=0)
        return FilterResult.TRUE

    def conform_sim_info_to_filter_term(self, created_sim_info, requesting_sim_info=None, **kwargs):
        if requesting_sim_info is None:
            return FilterResult('Unable to create sims with specific relationship-- requesting sim info is required', score=0)
        for bit in self._white_list:
            created_sim_info.relationship_tracker.add_relationship_bit(requesting_sim_info.id, bit, force_add=True)
            requesting_sim_info.relationship_tracker.add_relationship_bit(created_sim_info.id, bit, force_add=True)
        for bit in self._black_list:
            while not bit.is_track_bit:
                created_sim_info.relationship_tracker.remove_relationship_bit(requesting_sim_info.id, bit)
                requesting_sim_info.relationship_tracker.remove_relationship_bit(created_sim_info.id, bit)
        return FilterResult.TRUE

class TunableRelationshipTrack(TunableBaseFilterTerm):
    __qualname__ = 'TunableRelationshipTrack'
    FACTORY_TUNABLES = {'min_value': Tunable(description='\n                The minimum value of the relationship track that we are\n                filtering against.\n                ', tunable_type=int, default=-100), 'max_value': Tunable(description='\n                The maximum value of the relationship track that we are\n                filtering against.\n                ', tunable_type=int, default=100), 'ideal_value': Tunable(description='\n                Ideal value of the relationship track that we are filtering\n                against.\n                ', tunable_type=int, default=0), 'relationship_track': RelationshipTrack.TunableReference(description='\n                The relationship track that we are filtering against.\n                ')}

    def __init__(self, min_value, max_value, ideal_value, relationship_track, **kwargs):
        self._min_value = min_value
        self._max_value = max_value
        self._ideal_value = ideal_value
        self._relationship_track = relationship_track

    def calculate_score(self, sim_info, requesting_sim_info=None, **kwargs):
        if not requesting_sim_info:
            return FilterResult(score=0, sim_info=sim_info)
        relationship_value = requesting_sim_info.relationship_tracker.get_relationship_score(sim_info.id, self._relationship_track)
        score = calculate_score_from_value(relationship_value, self._min_value, self._max_value, self._ideal_value)
        return FilterResult(score=score, sim_info=sim_info)

    def conform_sim_creator_to_filter_term(self, requesting_sim_info=None, **kwargs):
        if requesting_sim_info is None:
            return FilterResult('Unable to create sims with specific relationship-- requesting sim info is required', score=0)
        return FilterResult.TRUE

    def conform_sim_info_to_filter_term(self, created_sim_info, requesting_sim_info=None, **kwargs):
        if requesting_sim_info is None:
            return FilterResult('Unable to create sims with specific relationshis-- requesting sim info is required', score=0)
        if self._min_value == self._max_value:
            new_track_val = self._ideal_value
        else:
            new_track_val = round(random.triangular(self._min_value, self._max_value, self._ideal_value))
        created_sim_info.relationship_tracker.set_relationship_score(requesting_sim_info.id, new_track_val, self._relationship_track)
        requesting_sim_info.relationship_tracker.set_relationship_score(created_sim_info.id, new_track_val, self._relationship_track)
        return FilterResult.TRUE

class TunableCanAgeUp(TunableInvertibleFilterTerm):
    __qualname__ = 'TunableCanAgeUp'

    def calculate_score(self, sim_info, **kwargs):
        score = 1 if sim_info.can_age_up() else 0
        return FilterResult(score=self.invert_score_if_necessary(score), sim_info=sim_info)

    def conform_sim_creator_to_filter_term(self, **kwargs):
        if not self._invert_score:
            return FilterResult('Unable to create a sim that is ready to age up.', score=0)
        return FilterResult.TRUE

class TunableHasHomeZone(TunableInvertibleFilterTerm):
    __qualname__ = 'TunableHasHomeZone'

    def calculate_score(self, sim_info, **kwargs):
        score = 1 if sim_info.household.home_zone_id != 0 else 0
        return FilterResult(score=self.invert_score_if_necessary(score), sim_info=sim_info)

    def conform_sim_creator_to_filter_term(self, **kwargs):
        if not self._invert_score:
            return FilterResult('Unable to create a sim that has a home lot.', score=0)
        return FilterResult.TRUE

class TunableAgeProgressFilterTerm(TunableBaseFilterTerm):
    __qualname__ = 'TunableAgeProgressFilterTerm'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value._ideal_value < value._min_value or value._ideal_value > value._max_value:
            logger.error('TunableAgeProgressFilterTerm {} has a filter term {} that is tuned with ideal_value {} outside of the minimum and maximum bounds [{}, {}].'.format(source, tunable_name, value._ideal_value, value._min_value, value._max_value))

    FACTORY_TUNABLES = {'min_value': Tunable(float, 0, description='Minimum value of age progress.'), 'max_value': Tunable(float, 10, description='Maximum value of age progress.'), 'ideal_value': Tunable(float, 5, description='Ideal value of age progress.'), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, min_value, max_value, ideal_value, **kwargs):
        super().__init__(**kwargs)
        self._min_value = min_value
        self._max_value = max_value
        self._ideal_value = ideal_value

    def calculate_score(self, sim_info, **kwargs):
        value = sim_info.age_progress
        score = calculate_score_from_value(value, self._min_value, self._max_value, self._ideal_value)
        return FilterResult(score=score, sim_info=sim_info)

    def conform_sim_info_to_filter_term(self, created_sim_info, **kwargs):
        current_value = created_sim_info.age_progress
        if self._min_value <= current_value <= self._max_value:
            return FilterResult.TRUE
        if self._min_value == self._max_value:
            new_age_progress_value = self._ideal_value
        else:
            new_age_progress_value = round(random.triangular(self._min_value, self._max_value, self._ideal_value))
        created_sim_info.age_progress = new_age_progress_value
        return FilterResult.TRUE

class TunableSimFilter(HasTunableReference, metaclass=TunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.SIM_FILTER)):
    __qualname__ = 'TunableSimFilter'
    MIN_RELATIONSHIP_VALUE = -100.0
    MAX_RELATIONSHIP_VALUE = 100.0
    TOP_NUMBER_OF_SIMS_TO_LOOK_AT = Tunable(int, 5, description='When running a filter request and doing a weighted random, how many of the top scorers will be used to get the results.')
    BLANK_FILTER = TunableReference(services.get_instance_manager(sims4.resources.Types.SIM_FILTER), description='A filter that is used when a filter of None is passed in.  This filter should have no filter terms.')
    ANY_FILTER = TunableReference(services.get_instance_manager(sims4.resources.Types.SIM_FILTER), description='A filter used for creating debug sims in your neighborhood.')
    INSTANCE_TUNABLES = {'_filter_terms': TunableList(description='\n            A list of filter terms that will be used to query the townie pool\n            for sims.\n            ', tunable=TunableVariant(description='\n                A variant of all the possible filter terms.\n                ', skill=TunableSkillFilterTerm.TunableFactory(), trait=TunableTraitFilterTerm.TunableFactory(), age=TunableAgeFilterTerm.TunableFactory(), gender=TunableGenderFilterTerm.TunableFactory(), is_busy=TunableIsBusyFilterTerm.TunableFactory(), in_family=TunableInFamily.TunableFactory(), is_dead=TunableIsDead.TunableFactory(), relationship_bit=TunableRelationshipBit.TunableFactory(), relationship_track=TunableRelationshipTrack.TunableFactory(), can_age_up=TunableCanAgeUp.TunableFactory(), has_home_zone=TunableHasHomeZone.TunableFactory(), age_progress=TunableAgeProgressFilterTerm.TunableFactory(), default='skill')), '_template_chooser': TunableReference(description='\n            A reference to a template chooser.  In the case that the filter\n            fails to find any sims that match it, the template chooser will\n            select a template to use that will be used to create a sim.  After\n            that sim is created then the filter will fix up the sim further in\n            order to insure that the template that the sim defines still meets\n            the criteria of the filter.\n            ', manager=services.get_instance_manager(sims4.resources.Types.TEMPLATE_CHOOSER)), '_relationship_constraints': TunableTuple(track=TunableReference(description='\n                The track to be checked against.\n                ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions='RelationshipTrack'), relationship_range=TunableInterval(description='\n                The range that the relationship score must be within in order\n                for this test to pass.\n                ', tunable_type=float, default_lower=MIN_RELATIONSHIP_VALUE, default_upper=MAX_RELATIONSHIP_VALUE, minimum=MIN_RELATIONSHIP_VALUE, maximum=MAX_RELATIONSHIP_VALUE)), 'use_weighted_random': Tunable(description='\n            If checked will do a weighted random of top results rather than\n            just choosing the best ones.\n            ', tunable_type=bool, default=False, needs_tuning=True), '_set_household_as_hidden': Tunable(description="\n            If checked, the household created for this template will be hidden.\n            Normally used with household_template_override. e.g. Death's\n            household.\n            ", tunable_type=bool, default=False), '_household_templates_override': OptionalTunable(description='\n            If enabled, when creating sim info use the household template\n            specified.\n            ', tunable=TunableList(tunable=filters.household_template.HouseholdTemplate.TunableReference()))}

    @classmethod
    def get_filter_terms(cls):
        return cls._filter_terms

    @classmethod
    def choose_template(cls):
        if cls._template_chooser is not None:
            return cls._template_chooser.choose_template()

    @classmethod
    def has_template(cls):
        return cls._template_chooser is not None

    @classmethod
    def create_sim_info(cls, zone_id, **kwargs):
        template = cls.choose_template()
        if not template:
            return FilterResult('No template selected, template chooser might not be tuned properly.', score=0)
        sim_creator = template.sim_creator
        for filter_term in cls._filter_terms:
            result = filter_term.conform_sim_creator_to_filter_term(sim_creator=sim_creator, **kwargs)
            while not result:
                return result
        (household_template_type, insertion_indexes_to_sim_creators) = cls.find_household_template_that_contains_sim_filter((sim_creator,))
        if household_template_type is None:
            return FilterResult('No template selected, there is no household template with minimum age and matching gender of sim_template.', score=0)
        (household, created_sim_infos) = household_template_type.get_sim_infos_from_household(zone_id, insertion_indexes_to_sim_creators, creation_source='filter: {}'.format(cls.__name__))
        household.hidden = cls._set_household_as_hidden
        created_sim_info = created_sim_infos.pop()
        template.add_template_data_to_sim(created_sim_info)
        for filter_term in cls._filter_terms:
            result = filter_term.conform_sim_info_to_filter_term(created_sim_info=created_sim_info, **kwargs)
            while not result:
                result.sim = created_sim_info
                return result
        return FilterResult('SimInfo created successfully', sim_info=created_sim_info)

    @classmethod
    def get_relationship_constrained_sims(cls, sim_info):
        possible_sims = []
        if cls._relationship_constraints.track is None:
            return
        rel_tracker = sim_info.relationship_tracker
        for target_sim in rel_tracker.target_sim_gen():
            rel_score = rel_tracker.get_relationship_score(target_sim, cls._relationship_constraints.track)
            while cls._relationship_constraints.relationship_range.lower_bound <= rel_score <= cls._relationship_constraints.relationship_range.upper_bound:
                possible_sims.append(target_sim)
        return possible_sims

    @classmethod
    def confirm_has_in_family_term(cls):
        for filter_term in cls._filter_terms:
            while isinstance(filter_term, TunableInFamily):
                return True
        return False

    @classmethod
    def find_household_template_that_contains_sim_filter(cls, sim_creations_to_match):
        valid_filter_template_type = []
        if cls._household_templates_override:
            templates_to_iterate_over = cls._household_templates_override
        else:
            templates_to_iterate_over = services.get_instance_manager(sims4.resources.Types.SIM_TEMPLATE).types.values()
        for filter_template_type in templates_to_iterate_over:
            if filter_template_type.template_type == filters.sim_template.SimTemplateType.SIM:
                pass
            index_to_sim_creation = {}
            for sim_creation in sim_creations_to_match:
                for (index, household_member_data) in enumerate(filter_template_type.get_household_members()):
                    if index in index_to_sim_creation:
                        pass
                    if household_member_data.sim_template._sim_creation_info.age_variant is not None and sim_creation.age != household_member_data.sim_template._sim_creation_info.age_variant.min_age:
                        pass
                    possible_gender = household_member_data.sim_template._sim_creation_info.gender
                    if possible_gender is not None and possible_gender != sim_creation.gender:
                        pass
                    index_to_sim_creation[index] = sim_creation
            while len(index_to_sim_creation) == len(sim_creations_to_match):
                valid_filter_template_type.append((filter_template_type, index_to_sim_creation))
        if valid_filter_template_type:
            return random.choice(valid_filter_template_type)
        return (None, None)

