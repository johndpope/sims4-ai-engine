import collections
import functools
import itertools
from animation.arb_accumulator import with_skippable_animation_time
from buffs.buff import Buff
from event_testing import test_events
from event_testing.resolver import DoubleSimResolver
from event_testing.results import TestResult
from event_testing.test_variants import SocialContextTest, GenderPreferenceTest
from interactions import TargetType, ParticipantType
from interactions.base.interaction import Interaction
from interactions.base.mixer_interaction import MixerInteraction
from interactions.social import SocialInteractionMixin
from interactions.utils.outcome import TunableOutcome
from relationships.relationship_bit import SocialContextBit, RelationshipBit
from sims4.tuning.tunable import TunableMapping, Tunable
from sims4.tuning.tunable_base import GroupNames
from sims4.utils import flexmethod, classproperty
from singletons import DEFAULT
from tag import Tag
from traits.traits import Trait
import caches
import element_utils
import services
import sims4.log
import tag
logger = sims4.log.Logger('Socials')
with sims4.reload.protected(globals()):
    tunable_tests_enabled = True

class SocialMixerInteraction(SocialInteractionMixin, MixerInteraction):
    __qualname__ = 'SocialMixerInteraction'
    REMOVE_INSTANCE_TUNABLES = ('basic_reserve_object', 'basic_focus')
    basic_reserve_object = None
    GENDER_PREF_CONTENT_SCORE_PENALTY = Tunable(description='\n        Penalty applied to content score when the social fails the gender preference test.\n        ', tunable_type=int, default=-1500)
    INSTANCE_TUNABLES = {'base_score': Tunable(description=' \n            Base score when determining the content set value of this mixer\n            based on other mixers of the super affordance. This is the base\n            value used before any modification to content score.\n    \n            Modification to the content score for this affordance can come from\n            topics and moods\n    \n            USAGE: If you would like this mixer to more likely show up no matter\n            the topic and mood ons the sims tune this value higher.\n                                    \n            Formula being used to determine the autonomy score is Score =\n            Avg(Uc, Ucs) * W * SW, Where Uc is the commodity score, Ucs is the\n            content set score, W is the weight tuned the on mixer, and SW is the\n            weight tuned on the super interaction.\n            ', tuning_group=GroupNames.AUTONOMY, tunable_type=int, default=0), 'social_context_preference': TunableMapping(description='\n            A mapping of social contexts that will adjust the content score for\n            this mixer interaction. This is used conjunction with base_score.\n            ', tuning_group=GroupNames.AUTONOMY, key_type=SocialContextBit.TunableReference(), value_type=Tunable(tunable_type=float, default=0)), 'relationship_bit_preference': TunableMapping(description='\n            A mapping of relationship bits that will adjust the content score for\n            this mixer interaction. This is used conjunction with base_score.\n            ', tuning_group=GroupNames.AUTONOMY, key_type=RelationshipBit.TunableReference(), value_type=Tunable(tunable_type=float, default=0)), 'trait_preference': TunableMapping(description='\n            A mapping of traits that will adjust the content score for\n            this mixer interaction. This is used conjunction with base_score.\n            ', tuning_group=GroupNames.AUTONOMY, key_type=Trait.TunableReference(), value_type=Tunable(tunable_type=float, default=0)), 'buff_preference': TunableMapping(description='\n            A mapping of buffs that will adjust the content score for\n            this mixer interaction. This is used conjunction with base_score.\n            ', tuning_group=GroupNames.AUTONOMY, key_type=Buff.TunableReference(), value_type=Tunable(tunable_type=float, default=0)), 'test_gender_preference': Tunable(description='\n            If this is set, a gender preference test will be run between\n            the actor and target sims. If it fails, the social score will be\n            modified by a large negative penalty tuned with the tunable:\n            GENDER_PREF_CONTENT_SCORE_PENALTY\n            ', tuning_group=GroupNames.AUTONOMY, tunable_type=bool, default=False), 'outcome': TunableOutcome(allow_multi_si_cancel=True)}

    def __init__(self, target, context, *args, **kwargs):
        super().__init__(target, context, *args, **kwargs)

    @classmethod
    def _add_auto_constraint(cls, participant_type, auto_constraint):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')

    @classproperty
    def is_social(cls):
        return True

    @property
    def social_group(self):
        if self.super_interaction is not None:
            return self.super_interaction.social_group

    @staticmethod
    def _tunable_tests_enabled():
        return tunable_tests_enabled

    @classmethod
    def get_base_content_set_score(cls):
        return cls.base_score

    @classmethod
    def _test(cls, target, context, *args, **kwargs):
        if context.sim is target:
            return TestResult(False, 'Social Mixer Interactions cannot target self!')
        pick_target = context.pick.target if context.source == context.SOURCE_PIE_MENU else None
        if target is None and context.sim is pick_target:
            return TestResult(False, 'Social Mixer Interactions cannot target self!')
        return MixerInteraction._test(target, context, *args, **kwargs)

    @classmethod
    def get_score_modifier(cls, sim, target):
        if cls.test_gender_preference:
            gender_pref_test = GenderPreferenceTest(ParticipantType.Actor, ParticipantType.TargetSim, ignore_reciprocal=True)
            resolver = DoubleSimResolver(sim.sim_info, target.sim_info)
            result = resolver(gender_pref_test)
            if not result:
                return cls.GENDER_PREF_CONTENT_SCORE_PENALTY
        social_context_preference = 0
        relationship_bit_preference = 0
        trait_preference = 0
        buff_preference = 0
        if target is not None:
            sims = set(itertools.chain.from_iterable(group for group in sim.get_groups_for_sim_gen() if target in group))
            if sims:
                social_context = SocialContextTest.get_overall_short_term_context_bit(*sims)
            else:
                relationship_track = sim.relationship_tracker.get_relationship_prevailing_short_term_context_track(target.id)
                if relationship_track is not None:
                    social_context = relationship_track.get_active_bit()
                else:
                    social_context = None
            social_context_preference = cls.social_context_preference.get(social_context, 0)
            if cls.relationship_bit_preference:
                relationship_bit_preference = sum(cls.relationship_bit_preference.get(rel_bit, 0) for rel_bit in sim.relationship_tracker.get_all_bits(target_sim_id=target.id))
            if cls.trait_preference:
                trait_preference = sum(cls.trait_preference.get(trait, 0) for trait in sim.trait_tracker.equipped_traits)
            if cls.buff_preference:
                buff_preference = sum(score for (buff, score) in cls.buff_preference.items() if sim.has_buff(buff))
        score_modifier = super().get_score_modifier(sim, target) + social_context_preference + relationship_bit_preference + trait_preference + buff_preference
        return score_modifier

    def should_insert_in_queue_on_append(self):
        if super().should_insert_in_queue_on_append():
            return True
        if self.super_affordance is None:
            logger.error('{} being added to queue without a super interaction or super affordance', self)
            return False
        ui_group_tag = self.super_affordance.visual_type_override_data.group_tag
        if ui_group_tag == tag.Tag.INVALID:
            return False
        for si in self.sim.si_state:
            while si.visual_type_override_data.group_tag == ui_group_tag:
                return True
        return False

    def get_asm(self, *args, **kwargs):
        return Interaction.get_asm(self, *args, **kwargs)

    def perform_gen(self, timeline):
        if self.social_group is None:
            raise AssertionError('Social mixer interaction {} has no social group. [bhill]'.format(self))
        result = yield super().perform_gen(timeline)
        return result

    def build_basic_elements(self, sequence=()):
        sequence = super().build_basic_elements(sequence=sequence)
        if self.super_interaction.social_group is not None:
            listen_animation_factory = self.super_interaction.listen_animation
        else:
            listen_animation_factory = None
            for group in self.sim.get_groups_for_sim_gen():
                si = group.get_si_registered_for_sim(self.sim)
                while si is not None:
                    listen_animation_factory = si.listen_animation
                    break
        if listen_animation_factory is not None:
            for sim in self.required_sims():
                if sim is self.sim:
                    pass
                sequence = listen_animation_factory(sim.animation_interaction, sequence=sequence)
                sequence = with_skippable_animation_time((sim,), sequence=sequence)

        def defer_cancel_around_sequence_gen(s, timeline):
            deferred_sis = []
            for sim in self.required_sims():
                while not (sim is self.sim or self.social_group is None):
                    if sim not in self.social_group:
                        pass
                    sis = self.social_group.get_sis_registered_for_sim(sim)
                    while sis:
                        deferred_sis.extend(sis)
            with self.super_interaction.cancel_deferred(deferred_sis):
                result = yield element_utils.run_child(timeline, s)
                return result

        sequence = functools.partial(defer_cancel_around_sequence_gen, sequence)
        if self.target_type & TargetType.ACTOR:
            return element_utils.build_element(sequence)
        if self.target_type & TargetType.TARGET and self.target is not None:
            sequence = self.social_group.with_target_focus(self.sim, self.sim, self.target, sequence)
        elif self.social_group is not None:
            sequence = self.social_group.with_social_focus(self.sim, self.sim, self.required_sims(), sequence)
        else:
            for social_group in self.sim.get_groups_for_sim_gen():
                sequence = social_group.with_social_focus(self.sim, self.sim, self.required_sims(), sequence)
        communicable_buffs = collections.defaultdict(list)
        for sim in self.required_sims():
            for buff in sim.Buffs:
                while buff.communicable:
                    communicable_buffs_sim = communicable_buffs[sim]
                    communicable_buffs_sim.append(buff)
        for (sim, communicable_buffs_sim) in communicable_buffs.items():
            for other_sim in self.required_sims():
                if other_sim is sim:
                    pass
                resolver = DoubleSimResolver(sim.sim_info, other_sim.sim_info)
                for buff in communicable_buffs_sim:
                    buff.communicable.apply_to_resolver(resolver)
        return element_utils.build_element(sequence)

    def cancel_parent_si_for_participant(self, participant_type, finishing_type, cancel_reason_msg, **kwargs):
        social_group = self.social_group
        if social_group is None:
            return
        participants = self.get_participants(participant_type)
        for sim in participants:
            while sim is not None:
                social_group.remove(sim)
        group_tag = self.super_interaction.visual_type_override_data.group_tag
        if group_tag != Tag.INVALID:
            for si in self.sim.si_state:
                while si is not self.super_interaction and si.visual_type_override_data.group_tag == group_tag:
                    social_group = si.social_group
                    if social_group is not None:
                        while True:
                            for sim in participants:
                                while sim in social_group:
                                    social_group.remove(sim)

    @flexmethod
    def get_participants(cls, inst, participant_type, sim=DEFAULT, **kwargs) -> set:
        inst_or_cls = inst if inst is not None else cls
        result = super(MixerInteraction, inst_or_cls).get_participants(participant_type, sim=sim, **kwargs)
        result = set(result)
        sim = inst.sim if sim is DEFAULT else sim
        if inst is not None and inst.social_group is None and (participant_type & ParticipantType.AllSims or participant_type & ParticipantType.Listeners):
            if inst is not None and inst.target_type & TargetType.GROUP:
                while True:
                    for other_sim in itertools.chain(*list(sim.get_groups_for_sim_gen())):
                        if other_sim is sim:
                            pass
                        if other_sim.ignore_group_socials(excluded_group=inst.social_group):
                            pass
                        result.add(other_sim)
        return tuple(result)

    def _trigger_interaction_start_event(self):
        super()._trigger_interaction_start_event()
        target_sim = self.get_participant(ParticipantType.TargetSim)
        if target_sim is not None:
            services.get_event_manager().process_event(test_events.TestEvent.InteractionStart, sim_info=target_sim.sim_info, interaction=self, custom_keys=self.get_keys_to_process_events())
            self._register_target_event_auto_update()

    def required_resources(self):
        resources = super().required_resources()
        resources.add(self.social_group)
        return resources

