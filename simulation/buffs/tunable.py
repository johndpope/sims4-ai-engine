from interactions import ParticipantType
from sims4.localization import TunableLocalizedString
from sims4.tuning.tunable import TunableSingletonFactory, Tunable, TunableList, TunableReference, TunableFactory, TunableEnumFlags, TunablePercent, TunableSet, TunableEnumEntry, OptionalTunable
from tag import Tag
import event_testing
import services
import snippets

class BuffReference:
    __qualname__ = 'BuffReference'

    def __init__(self, buff_type=None, buff_reason=None):
        self._buff_type = buff_type
        self._buff_reason = buff_reason

    @property
    def buff_type(self):
        return self._buff_type

    @property
    def buff_reason(self):
        return self._buff_reason

class TunableBuffReference(TunableSingletonFactory):
    __qualname__ = 'TunableBuffReference'
    FACTORY_TYPE = BuffReference

    def __init__(self, reload_dependent=False, **kwargs):
        super().__init__(buff_type=TunableReference(manager=services.buff_manager(), description='Buff that will get added to sim.', reload_dependent=reload_dependent), buff_reason=OptionalTunable(description='\n                            If set, specify a reason why the buff was added.\n                            ', tunable=TunableLocalizedString(description='\n                                The reason the buff was added. This will be displayed in the\n                                buff tooltip.\n                                ')), **kwargs)

class BaseGameEffectModifier:
    __qualname__ = 'BaseGameEffectModifier'

    def __init__(self, modifier_type):
        self.modifier_type = modifier_type

class AffordanceReferenceScoringModifier(BaseGameEffectModifier):
    __qualname__ = 'AffordanceReferenceScoringModifier'
    FACTORY_TUNABLES = {'content_score_bonus': Tunable(description='\n            When determine content score for affordances and afforance matches\n            tuned here, content score is increased by this amount.\n            ', tunable_type=int, default=0), 'success_modifier': TunablePercent(description='\n            Amount to adjust percent success chance. For example, tuning 10%\n            will increase success chance by 10% over the base success chance.\n            Additive with other buffs.\n            ', default=0, minimum=-100), 'affordances': TunableList(description='\n            A list of affordances that will be compared against.\n            ', tunable=TunableReference(manager=services.affordance_manager())), 'affordance_lists': TunableList(description='\n            A list of affordance snippets that will be compared against.\n            ', tunable=snippets.TunableAffordanceListReference()), 'interaction_category_tags': TunableSet(description='\n            This attribute is used to test for affordances that contain any of the tags in this set.\n            ', tunable=TunableEnumEntry(description='\n                These tag values are used for testing interactions.\n                ', tunable_type=Tag, default=Tag.INVALID))}

    def __init__(self, modifier_type=None, content_score_bonus=0, success_modifier=0, affordances=(), affordance_lists=(), interaction_category_tags=set()):
        super().__init__(modifier_type)
        self._score_bonus = content_score_bonus
        self._success_modifier = success_modifier
        self._affordances = affordances
        self._affordance_lists = affordance_lists
        self._interaction_category_tags = interaction_category_tags

    def get_score_for_type(self, affordance):
        if affordance in self._affordances:
            return self._score_bonus
        for affordances in self._affordance_lists:
            while affordance in affordances:
                return self._score_bonus
        if affordance.interaction_category_tags & self._interaction_category_tags:
            return self._score_bonus
        return 0

    def get_success_for_type(self, affordance):
        if affordance in self._affordances:
            return self._success_modifier
        for affordances in self._affordance_lists:
            while affordance in affordances:
                return self._success_modifier
        if affordance.interaction_category_tags & self._interaction_category_tags:
            return self._score_bonus
        return 0

    def debug_affordances_gen(self):
        for affordance in self._affordances:
            yield affordance.__name__
        for affordnace_snippet in self._affordance_lists:
            yield affordnace_snippet.__name__

TunableAffordanceScoringModifier = TunableSingletonFactory.create_auto_factory(AffordanceReferenceScoringModifier)

class TunableBuffElement(TunableFactory):
    __qualname__ = 'TunableBuffElement'

    @staticmethod
    def factory(interaction, subject, tests, buff_type, sequence=()):
        for sim in interaction.get_participants(subject):
            while tests.run_tests(interaction.get_resolver()):
                sequence = buff_type.buff_type.build_critical_section(sim, buff_type.buff_reason, sequence)
        return sequence

    FACTORY_TYPE = factory

    def __init__(self, description='A buff that will get added to the subject when running the interaction if the tests succeeds.', **kwargs):
        super().__init__(subject=TunableEnumFlags(ParticipantType, ParticipantType.Actor, description='Who will receive the buff.'), tests=event_testing.tests.TunableTestSet(), buff_type=TunableBuffReference(description='The buff type to be added to the Sim.'), description=description, **kwargs)

