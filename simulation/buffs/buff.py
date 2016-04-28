import operator
from autonomy.autonomy_modifier import TunableAutonomyModifier, AutonomyModifier
from buffs import GameEffectType, BuffPolarity, Appropriateness
from buffs.tunable import TunableAffordanceScoringModifier, BaseGameEffectModifier, BuffReference, TunableBuffReference
from clock import interval_in_sim_minutes
from interactions.utils.loot import LootActions
from interactions.utils.routing import TunableWalkstyle
from interactions.utils.tunable import TunableAffordanceLinkList
from objects import ALL_HIDDEN_REASONS
from element_utils import build_critical_section_with_finally
from sims4.localization import TunableLocalizedString, TunableLocalizedStringFactory
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import Tunable, TunableList, TunableVariant, TunableResourceKey, OptionalTunable, TunableReference, TunableRange, TunableEnumEntry, TunableSet, HasTunableSingletonFactory, HasTunableFactory, TunableTuple, HasTunableReference, TunableSimMinute
from sims4.tuning.tunable_base import ExportModes, GroupNames
from sims4.utils import classproperty, flexproperty
from singletons import DEFAULT
from statistics.commodity import CommodityState, RuntimeCommodity, CommodityTimePassageFixupType
from statistics.skill import Skill
from statistics.statistic_categories import StatisticCategory
from tag import Tag
from vfx import PlayEffect
import event_testing.resolver
import event_testing.tests
import interactions.base.mixer_interaction
import services
import sims4.log
import sims4.resources
import statistics.commodity
import statistics.static_commodity
import tag
import topics.topic
import zone_types
logger = sims4.log.Logger('Buffs')

class EffectiveSkillModifier(HasTunableSingletonFactory, BaseGameEffectModifier):
    __qualname__ = 'EffectiveSkillModifier'
    FACTORY_TUNABLES = {'description': '\n        The modifier to change the effective skill or skill_tag tuned in the\n        modifier key The value of the modifier can be negative..\n        ', 'modifier_key': TunableVariant(description='\n            ', skill_type=Skill.TunableReference(description='\n                            What skill to apply the modifier on.'), skill_tag=TunableEnumEntry(description='\n                            What skill tag to apply the modifier on.', tunable_type=tag.Tag, default=tag.Tag.INVALID)), 'modifier_value': Tunable(description='\n            The value to change the effective skill. Can be negative.', tunable_type=int, default=0)}

    def __init__(self, modifier_key, modifier_value, **kwargs):
        BaseGameEffectModifier.__init__(self, GameEffectType.EFFECTIVE_SKILL_MODIFIER)
        self.modifier_key = modifier_key
        self.modifier_value = modifier_value

    def can_modify(self, skill):
        if self.modifier_key is skill.skill_type:
            return True
        return self.modifier_key in skill.tags

    def get_modifier_value(self, skill):
        if self.can_modify(skill):
            return self.modifier_value
        return 0

class RelationshipTrackDecayLocker(HasTunableSingletonFactory, BaseGameEffectModifier):
    __qualname__ = 'RelationshipTrackDecayLocker'
    FACTORY_TUNABLES = {'description': '\n        A modifier for locking the decay of a relationship track.\n        ', 'relationship_track': TunableReference(description='\n        The relationship track to lock.\n        ', manager=services.statistic_manager(), class_restrictions=('RelationshipTrack',))}
    tunable = (TunableReference(manager=services.get_instance_manager(sims4.resources.Types.ACTION), class_restrictions=('LootActions',)),)

    def __init__(self, relationship_track, **kwargs):
        BaseGameEffectModifier.__init__(self, GameEffectType.RELATIONSHIP_TRACK_DECAY_LOCKER, **kwargs)
        self._track_type = relationship_track
        self._owner = None

    def apply_modifier(self, owner):
        self._owner = owner
        zone = services.current_zone()
        if not zone.is_households_and_sim_infos_loaded and not zone.is_zone_running:
            zone.register_callback(zone_types.ZoneState.HOUSEHOLDS_AND_SIM_INFOS_LOADED, self._all_sim_infos_loaded_callback)
            return
        self._set_decay_lock_all_relationships(lock=True)
        self._initialize_create_relationship_callback()

    def _initialize_create_relationship_callback(self):
        tracker = self._owner.relationship_tracker
        tracker.add_create_relationship_listener(self._relationship_added_callback)

    def _all_sim_infos_loaded_callback(self):
        zone = services.current_zone()
        zone.unregister_callback(zone_types.ZoneState.HOUSEHOLDS_AND_SIM_INFOS_LOADED, self._all_sim_infos_loaded_callback)
        self._set_decay_lock_all_relationships(lock=True)
        self._initialize_create_relationship_callback()

    def _set_decay_lock_all_relationships(self, lock=True):
        tracker = self._owner.relationship_tracker
        sim_info_manager = services.sim_info_manager()
        for other_sim_id in tracker.target_sim_gen():
            other_sim_info = sim_info_manager.get(other_sim_id)
            track = tracker.get_relationship_track(other_sim_id, self._track_type, add=True)
            other_tracker = other_sim_info.relationship_tracker
            other_track = other_tracker.get_relationship_track(self._owner.id, self._track_type, add=True)
            if lock:
                track.add_decay_rate_modifier(0)
                other_track.add_decay_rate_modifier(0)
            else:
                track.remove_decay_rate_modifier(0)
                other_track.remove_decay_rate_modifier(0)

    def _relationship_added_callback(self, relationship):
        sim_a_track = relationship.get_track(self._track_type, add=True)
        sim_b_track = relationship.find_target_sim_info().relationship_tracker.get_relationship_track(relationship.sim_id, self._track_type, add=True)
        sim_a_track.add_decay_rate_modifier(0)
        sim_b_track.add_decay_rate_modifier(0)

    def remove_modifier(self, owner):
        tracker = owner.relationship_tracker
        tracker.remove_create_relationship_listener(self._relationship_added_callback)
        self._set_decay_lock_all_relationships(lock=False)

class ContinuousStatisticModifier(HasTunableSingletonFactory, BaseGameEffectModifier):
    __qualname__ = 'ContinuousStatisticModifier'
    FACTORY_TUNABLES = {'description': "\n        The modifier to add to the current statistic modifier of this continuous statistic,\n        resulting in it's increase or decrease over time. Adding this modifier to something by\n        default doesn't change, i.e. a skill, will start that skill to be added to over time.\n        ", 'statistic': TunableReference(description='\n        "The statistic we are operating on.', manager=services.statistic_manager()), 'modifier_value': Tunable(description='\n        The value to add to the modifier. Can be negative.', tunable_type=float, default=0)}

    def __init__(self, statistic, modifier_value, **kwargs):
        BaseGameEffectModifier.__init__(self, GameEffectType.CONTINUOUS_STATISTIC_MODIFIER)
        self.statistic = statistic
        self.modifier_value = modifier_value

    def apply_modifier(self, owner):
        stat = owner.get_statistic(self.statistic)
        if stat is None:
            stat = owner.add_statistic(self.statistic)
        stat.add_statistic_modifier(self.modifier_value)
        if isinstance(stat, Skill):
            owner.current_skill_guid = stat.guid64

    def remove_modifier(self, owner):
        stat = owner.get_statistic(self.statistic)
        if stat is None:
            return
        stat.remove_statistic_modifier(self.modifier_value)
        if isinstance(stat, Skill) and stat._statistic_modifier <= 0 and owner.current_skill_guid == stat.guid64:
            owner.current_skill_guid = 0

class TunableGameEffectVariant(TunableVariant):
    __qualname__ = 'TunableGameEffectVariant'

    def __init__(self, description='A single game effect modifier.', **kwargs):
        super().__init__(autonomy_modifier=TunableAutonomyModifier(), affordance_modifier=TunableAffordanceScoringModifier(locked_args={'modifier_type': GameEffectType.AFFORDANCE_MODIFIER}), effective_skill_modifier=EffectiveSkillModifier.TunableFactory(), continuous_statistic_modifier=ContinuousStatisticModifier.TunableFactory(), relationship_track_decay_locker=RelationshipTrackDecayLocker.TunableFactory(), description=description, **kwargs)

class GameEffectModifiers(HasTunableFactory):
    __qualname__ = 'GameEffectModifiers'
    FACTORY_TUNABLES = {'game_effect_modifiers': TunableList(description='\n            A list of game effect modifiers', tunable=TunableGameEffectVariant())}

    def __init__(self, owner, game_effect_modifiers):
        self._owner = owner
        self._game_effect_modifiers = game_effect_modifiers
        self._autonomy_modifier_handles = []
        self._topic_modifiers = []
        self._affordance_modifiers = []
        self._effective_skill_modifiers = []
        self._continuous_statistic_modifiers = []
        self._relationship_track_decay_lockers = []

    def on_add(self):
        for modifier in self._game_effect_modifiers:
            if isinstance(modifier, AutonomyModifier):
                handle = self._owner.add_statistic_modifier(modifier)
                self._autonomy_modifier_handles.append(handle)
            elif modifier.modifier_type == GameEffectType.AFFORDANCE_MODIFIER:
                self._affordance_modifiers.append(modifier)
            elif modifier.modifier_type == GameEffectType.EFFECTIVE_SKILL_MODIFIER:
                self._effective_skill_modifiers.append(modifier)
            elif modifier.modifier_type == GameEffectType.CONTINUOUS_STATISTIC_MODIFIER:
                modifier.apply_modifier(self._owner)
                self._continuous_statistic_modifiers.append(modifier)
            else:
                while modifier.modifier_type == GameEffectType.RELATIONSHIP_TRACK_DECAY_LOCKER:
                    modifier.apply_modifier(self._owner)
                    self._relationship_track_decay_lockers.append(modifier)

    def on_remove(self, on_destroy=False):
        if not on_destroy:
            for modifier in self._continuous_statistic_modifiers:
                while modifier.modifier_type == GameEffectType.CONTINUOUS_STATISTIC_MODIFIER:
                    modifier.remove_modifier(self._owner)
            for modifier in self._relationship_track_decay_lockers:
                while modifier.modifier_type == GameEffectType.RELATIONSHIP_TRACK_DECAY_LOCKER:
                    modifier.remove_modifier(self._owner)
            for handle in self._autonomy_modifier_handles:
                self._owner.remove_statistic_modifier(handle)
        self._autonomy_modifier_handles.clear()
        self._autonomy_modifier_handles = []
        self._effective_skill_modifiers.clear()
        self._effective_skill_modifiers = []
        self._continuous_statistic_modifiers.clear()
        self._continuous_statistic_modifiers = []
        self._relationship_track_decay_lockers.clear()
        self._relationship_track_decay_lockers = []

    def get_affordance_scoring_modifier(self, affordance):
        return sum(modifier.get_score_for_type(affordance) for modifier in self._affordance_modifiers)

    def get_affordance_success_modifier(self, affordance):
        return sum(modifier.get_success_for_type(affordance) for modifier in self._affordance_modifiers)

    def get_effective_skill_modifier(self, skill):
        return sum(modifier.get_modifier_value(skill) for modifier in self._effective_skill_modifiers)

class BuffHandler:
    __qualname__ = 'BuffHandler'

    def __init__(self, sim, buff_type, buff_reason=None):
        self._sim = sim
        self._handle_id = None
        self._buff_type = buff_type
        self._buff_reason = buff_reason

    def begin(self, _):
        self._handle_id = self._sim.add_buff(self._buff_type, self._buff_reason)

    def end(self, _):
        if self._handle_id is not None:
            self._sim.remove_buff(self._handle_id, on_destroy=self._sim.is_being_destroyed)

NO_TIMEOUT = (0, 0)

class Buff(HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.BUFF)):
    __qualname__ = 'Buff'
    INSTANCE_TUNABLES = {'buff_name': TunableLocalizedString(description='\n        Name of buff.\n        ', tuning_group=GroupNames.UI, export_modes=ExportModes.All), 'buff_description': TunableLocalizedString(description='\n        Tooltip description of the Buff Effect.\n        ', tuning_group=GroupNames.UI, export_modes=ExportModes.All), 'icon': TunableResourceKey(description='\n        Icon to be displayed for buff\n        ', default=None, needs_tuning=True, resource_types=sims4.resources.CompoundTypes.IMAGE, tuning_group=GroupNames.UI, export_modes=ExportModes.All), 'icon_highlight': TunableResourceKey(description=" \n        Icon to be displayed for when Mood Type is the Sim's active mood.\n        ", default=None, resource_types=sims4.resources.CompoundTypes.IMAGE, tuning_group=GroupNames.UI, export_modes=ExportModes.All), 'ui_sort_order': Tunable(description='\n        Order buff should be sorted in UI.\n        ', tunable_type=int, tuning_group=GroupNames.UI, default=1, export_modes=ExportModes.All), 'visible': Tunable(description='\n        Whether this buff should be visible in the UI.\n        ', tunable_type=bool, default=True, tuning_group=GroupNames.UI), 'audio_sting_on_remove': TunableResourceKey(description='\n        The sound to play when this buff is removed.\n        ', default=None, resource_types=(sims4.resources.Types.PROPX,), export_modes=ExportModes.All), 'audio_sting_on_add': TunableResourceKey(description='\n        The sound to play when this buff is added.\n        ', default=None, resource_types=(sims4.resources.Types.PROPX,), export_modes=ExportModes.All), 'show_timeout': Tunable(description='\n        Whether timeout should be shown in the UI.\n        ', tunable_type=bool, default=True, tuning_group=GroupNames.UI), 'success_modifier': Tunable(description='\n        Base chance delta for interaction success\n        ', tunable_type=int, default=0), 'interactions': OptionalTunable(TunableTuple(weight=Tunable(description='\n            The selection weight to apply to all interactions added by this\n            buff. This takes the place of the SI weight that would be used on\n            SuperInteractions.\n            ', tunable_type=float, default=1), scored_commodity=statistics.commodity.Commodity.TunableReference(description="\n            The commodity that is scored when deciding whether or not to \n            perform these interactions.  This takes the place of the commodity\n            scoring for the SuperInteraction when Subaction Autonomy scores\n            all of the SI's in the SI State.  If this is None, the default \n            value of autonomy.autonomy_modes.SUBACTION_MOTIVE_UTILITY_FALLBACK_SCORE \n            will be used.\n            "), interaction_items=TunableAffordanceLinkList(description='\n            Mixer interactions to add to the Sim when this buff is active.\n            ', class_restrictions=(interactions.base.mixer_interaction.MixerInteraction,))), tuning_group=GroupNames.ANIMATION), 'topics': TunableList(description='\n        Topics that should be added to sim when buff is added.\n        ', tunable=TunableReference(manager=services.topic_manager(), class_restrictions=topics.topic.Topic)), 'game_effect_modifiers': GameEffectModifiers.TunableFactory(description="\n        A list of effects that that can modify a Sim's behavior.\n        "), 'mood_type': TunableReference(description='\n        The mood that this buff pushes onto the owning Sim. If None, does\n        not affect mood.\n        ', manager=services.mood_manager(), needs_tuning=True, export_modes=ExportModes.All), 'mood_weight': TunableRange(description='\n        Weight for this mood. The active mood is determined by summing all\n        buffs and choosing the mood with the largest weight.\n        ', tunable_type=int, default=0, minimum=0, export_modes=ExportModes.All), 'proximity_detection_tests': OptionalTunable(description="\n        Whether or not this buff should be added because of a Sim's proximity\n        to an object with a Proximity Component with this buff in its buffs\n        list.\n        ", tunable=event_testing.tests.TunableTestSet(description="\n            A list of tests groups. At least one must pass all its sub-tests to\n            pass the TestSet.\n            \n            Actor is the one who receives the buff.\n            \n            If this buff is for two Sims in proximity to each other, only Actor\n            and TargetSim should be tuned as Participant Types. Example: A Neat\n            Sim is disgusted when around a Sim that has low hygiene. The test\n            will be for Actor having the Neat trait and for TargetSim with low\n            hygiene motive.\n\n            If this buff is for a Sim near an object, only use participant\n            types Actor and Object. Example: A Sim who likes classical music\n            should get a buff when near a stereo that's playing classical\n            music. The test will be for Actor liking classical music and for\n            Object in the state of playing classical music.\n            "), enabled_by_default=False, disabled_name='no_proximity_detection', enabled_name='proximity_tests'), 'proximity_buff_added_reason': OptionalTunable(tunable=TunableLocalizedString(description="\n            If this is a proximity buff, this field will be the reason for why\n            the Sim received this buff. Doesn't use tokens.\n            "), enabled_by_default=False, disabled_name='no_proximity_add_reason', enabled_name='proximity_add_reason'), '_add_test_set': OptionalTunable(description='\n        Whether or not this buff should be added.\n        ', tunable=event_testing.tests.TunableTestSet(description='\n            A list of tests groups. At least one must pass all its sub-tests to\n            pass the TestSet. Only Actor should be tuned as Participant\n            Types.The Actor is the Sim that will receive the buff if all tests\n            pass."\n            '), enabled_by_default=False, disabled_name='always_allowed', enabled_name='tests_set'), 'walkstyle': OptionalTunable(TunableWalkstyle(description="\n        A walkstyle override to apply to the Sim while this buff is active.\n        Example: you can have Sims with the 'bummed' buff walk in a sad\n        fashion.\n        "), needs_tuning=True, tuning_group=GroupNames.ANIMATION), 'allow_running_for_long_distance_routes': Tunable(bool, True, description='\n        Sims will run when routing long distances outside. Setting this to False\n        will disable that functionality. Example: pregnant Sims and walk-by Sims\n        should probably never run for this reason.'), 'vfx': OptionalTunable(description='\n        vfx to play on the sim when buff is added.\n        ', tunable=PlayEffect.TunableFactory(), disabled_name='no_effect', enabled_name='play_effect', tuning_group=GroupNames.ANIMATION), 'static_commodity_to_add': TunableSet(description='\n        Static commodity that is added to the sim when buff is added to sim.\n        ', tunable=TunableReference(manager=services.static_commodity_manager(), class_restrictions=statistics.static_commodity.StaticCommodity)), '_operating_commodity': statistics.commodity.Commodity.TunableReference(description='\n        This is the commodity that is considered the owning commodity of the\n        buff.  Multiple commodities can reference the same buff.  This field\n        is used to determine which commodity is considered the authoritative\n        commodity.  This only needs to be filled if there are more than one\n        commodity referencing this buff.\n        \n        For example, motive_hunger and starvation_commodity both reference\n        the same buff.  Starvation commodity is marked as the operating\n        commodity.  If outcome action asks the buff what commodity it should\n        apply changes to it will modify the starvation commodity.\n        '), '_temporary_commodity_info': OptionalTunable(TunableTuple(description='\n        Tunables relating to the generation of a temporary commodity to control\n        the lifetime of this buff.  If enabled, this buff has no associated\n        commodities and will create its own to manage its lifetime.\n        ', max_duration=Tunable(description='\n            The maximum time buff can last for.  Example if set to 100, buff\n            only last at max 100 sim minutes.  If washing hands gives +10 sim\n            minutes for buff. Trying to run interaction for more than 10 times,\n            buff time will not increase\n            ', tunable_type=int, default=100), categories=TunableSet(description='\n                List of categories that this commodity is part of. Used for buff\n                removal by category.\n                ', tunable=StatisticCategory, needs_tuning=True))), '_appropriateness_tags': TunableSet(description='\n            A set of tags that define the appropriateness of the\n            interactions allowed by this buff.  All SIs are allowed by\n            default, so adding this tag generally implies that it is always\n            allowed even if another buff has said that it is\n            inappropriate.\n            ', tunable=TunableEnumEntry(tunable_type=Tag, default=Tag.INVALID)), '_inappropriateness_tags': TunableSet(description="\n            A set of tags that define the inappropriateness of the\n            interactions allowed by this buff.  All SIs are allowed by\n            default, so adding this tag generally implies that it's not\n            allowed.\n            ", tunable=TunableEnumEntry(tunable_type=Tag, default=Tag.INVALID)), 'communicable': OptionalTunable(tunable=LootActions.TunableReference(description='\n            The loot to give to Sims that this Sim interacts with while the buff is active.\n            This models transmitting the buff, so make sure to tune a percentage chance\n            on the loot action to determine the chance of the buff being transmitted.\n            ')), '_add_buff_on_remove': OptionalTunable(tunable=TunableBuffReference(description='\n            A buff to add to the Sim when this buff is removed.\n            ')), '_loot_on_addition': TunableList(description='\n        Loot that will be applied when buff is added to sim.\n        ', tunable=LootActions.TunableReference()), '_loot_on_removal': TunableList(description='\n        Loot that will be applied when buff is removed from sim.\n        ', tunable=LootActions.TunableReference()), 'refresh_on_add': Tunable(description='\n        This buff will have its duration refreshed if it gets added to a Sim\n        who already has the same buff.\n        ', tunable_type=bool, needs_tuning=True, default=True), 'flip_arrow_for_progress_update': Tunable(description='\n        This only for visible buffs with an owning commodity.\n        \n        If unchecked and owning commodity is increasing an up arrow will\n        appear on the buff and if owning commodity is decreasing a down arrow\n        will appear.\n        \n        If checked and owning commodity is increasing then a down arrow will\n        appear on the buff and if owning commodity is decreasing an up arrow\n        will appear.\n        \n        Example of being checked is motive failing buffs, when the commodity is\n        increasing we need to show down arrows for the buff.\n        ', tunable_type=bool, default=False, tuning_group=GroupNames.UI), 'timeout_string': TunableLocalizedStringFactory(description='\n        String to override the the timeout text. The first token (0.TimeSpan)\n        will be the timeout time and the second token will (1.String) will be\n        the  buff this buff is transitioning to.\n        \n        If this buff is not transitioning to another buff the only token valid\n        in string is 0.Timespan\n        \n        Example: If this is the hungry buff, then the commodity is decaying to\n        starving buff. Normally timeout in tooltip will say \'5 hours\'. With\n        this set it will pass in the next buff name as the first token into\n        this localized string.  So if string provided is \'Becomes {1.String}\n        in: {0.TimeSpan}. Timeout tooltip for buff now says \'Becomes Starving\n        in: 5 hours\'.\n        \n        Example: If buff is NOT transitioning into another buff. Localized\n        string could be "Great time for :{0.Timespan}". Buff will now say\n        "Great time for : 5 hours"\n        ', tuning_group=GroupNames.UI, export_modes=(ExportModes.ClientBinary,))}
    is_mood_buff = False
    exclusive_index = None
    exclusive_weight = None
    trait_replacement_buffs = None
    _owning_commodity = None

    @classmethod
    def _verify_tuning_callback(cls):
        if cls.visible and not cls.mood_type:
            logger.error('No mood type set for visible buff: {}.  Either provide a mood or make buff invisible.', cls, owner='Tuning')

    @classmethod
    def _tuning_loaded_callback(cls):
        if cls._temporary_commodity_info is not None:
            if cls._owning_commodity is None:
                cls._create_temporary_commodity()
            elif issubclass(cls._owning_commodity, RuntimeCommodity):
                cls._create_temporary_commodity(proxied_commodity=cls._owning_commodity)

    def __init__(self, owner, commodity_guid, replacing_buff_type, transition_into_buff_id):
        self._owner = owner
        self.commodity_guid = commodity_guid
        self.effect_modification = self.game_effect_modifiers(owner)
        self.buff_reason = None
        self.handle_ids = []
        self._static_commodites_added = None
        self._replacing_buff_type = replacing_buff_type
        self._mood_override = None
        self._vfx = None
        self.transition_into_buff_id = transition_into_buff_id
        self._walkstyle_active = False

    @classmethod
    def _cls_repr(cls):
        return '{}'.format(cls.__name__)

    @classmethod
    def can_add(cls, owner):
        if cls._add_test_set is not None:
            resolver = event_testing.resolver.SingleSimResolver(owner)
            result = cls._add_test_set.run_tests(resolver)
            if not result:
                return False
        return True

    @classproperty
    def polarity(cls):
        if cls.mood_type is not None:
            return cls.mood_type.buff_polarity
        return BuffPolarity.NEUTRAL

    @classproperty
    def buff_type(cls):
        return cls

    @classproperty
    def get_success_modifier(cls):
        return cls.success_modifier/100

    @classproperty
    def is_changeable(cls):
        if cls.mood_type is not None:
            return cls.mood_type.is_changeable
        return False

    @classmethod
    def add_owning_commodity(cls, commodity):
        if cls._owning_commodity is None:
            cls._owning_commodity = commodity
        elif cls._operating_commodity is None and cls._owning_commodity is not commodity:
            logger.error('Please fix tuning: Multiple commodities reference {} : commodity:{},  commodity:{}, Set _operating_commodity to authoratative commodity', cls, cls._owning_commodity, commodity)

    @flexproperty
    def commodity(cls, inst):
        if inst is not None and inst._replacing_buff_type is not None:
            return inst._replacing_buff_type.commodity
        return cls._operating_commodity or cls._owning_commodity

    @classmethod
    def build_critical_section(cls, sim, buff_reason, *sequence):
        buff_handler = BuffHandler(sim, cls, buff_reason=buff_reason)
        return build_critical_section_with_finally(buff_handler.begin, sequence, buff_handler.end)

    @classmethod
    def _create_temporary_commodity(cls, proxied_commodity=None, create_buff_state=True, initial_value=DEFAULT):
        if proxied_commodity is None:
            proxied_commodity = RuntimeCommodity.generate(cls.__name__)
        proxied_commodity.decay_rate = 1
        proxied_commodity.convergence_value = 0
        proxied_commodity.remove_on_convergence = True
        proxied_commodity.visible = False
        proxied_commodity.max_value_tuning = cls._temporary_commodity_info.max_duration
        proxied_commodity.min_value_tuning = 0
        proxied_commodity.initial_value = initial_value if initial_value is not DEFAULT else cls._temporary_commodity_info.max_duration
        proxied_commodity._categories = cls._temporary_commodity_info.categories
        proxied_commodity._time_passage_fixup_type = CommodityTimePassageFixupType.FIXUP_USING_TIME_ELAPSED
        if create_buff_state:
            buff_to_add = BuffReference(buff_type=cls)
            new_state_add_buff = CommodityState(value=0.1, buff=buff_to_add)
            new_state_remove_buff = CommodityState(value=0, buff=BuffReference())
            proxied_commodity.commodity_states = [new_state_remove_buff, new_state_add_buff]
        cls.add_owning_commodity(proxied_commodity)

    @classmethod
    def get_appropriateness(cls, tags):
        if cls._appropriateness_tags & tags:
            return Appropriateness.ALLOWED
        if cls._inappropriateness_tags & tags:
            return Appropriateness.NOT_ALLOWED
        return Appropriateness.DONT_CARE

    @property
    def mood_override(self):
        return self._mood_override

    @mood_override.setter
    def mood_override(self, value):
        if not self.is_changeable:
            logger.error('Trying to override mood for buff:{}, but mood for this is not considered changeable.', self, owner='msantander')
        self._mood_override = value

    def on_add(self, load_in_progress):
        self.effect_modification.on_add()
        for topic_type in self.topics:
            self._owner.add_topic(topic_type)
        tracker = self._owner.static_commodity_tracker
        for static_commodity_type in self.static_commodity_to_add:
            tracker.add_statistic(static_commodity_type)
            if self._static_commodites_added is None:
                self._static_commodites_added = []
            self._static_commodites_added.append(static_commodity_type)
        self._apply_walkstyle()
        self.apply_interaction_lockout_to_owner()
        if not load_in_progress:
            sim = self._owner.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            if sim is not None:
                self._start_vfx()
                if self._loot_on_addition:
                    self._apply_all_loot_actions()

    def _apply_all_loot_actions(self):
        sim = self._owner.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if sim is not None:
            resolver = sim.get_resolver()
            for loot_action in self._loot_on_addition:
                loot_action.apply_to_resolver(resolver)

    def on_remove(self, apply_loot_on_remove=True):
        self.effect_modification.on_remove()
        for topic_type in self.topics:
            self._owner.remove_topic(topic_type)
        if self._static_commodites_added is not None:
            tracker = self._owner.static_commodity_tracker
            for static_commodity_type in self._static_commodites_added:
                tracker.remove_statistic(static_commodity_type)
        if self._add_buff_on_remove is not None:
            self._owner.add_buff_from_op(self._add_buff_on_remove.buff_type, self._add_buff_on_remove.buff_reason)
        self._release_walkstyle()
        self.on_sim_removed()
        if apply_loot_on_remove:
            sim = self._owner.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            if sim is not None:
                resolver = sim.get_resolver()
                while True:
                    for loot_action in self._loot_on_removal:
                        loot_action.apply_to_resolver(resolver)

    def clean_up(self):
        self.effect_modification.on_remove(on_destroy=True)
        self._release_walkstyle()
        self.on_sim_removed()
        if self._static_commodites_added:
            self._static_commodites_added.clear()
            self._static_commodites_added = None

    def on_sim_ready_to_simulate(self):
        for topic_type in self.topics:
            self._owner.add_topic(topic_type)
        self.apply_interaction_lockout_to_owner()
        self._start_vfx()

    def _apply_walkstyle(self):
        if self.walkstyle is not None and not self._walkstyle_active:
            self._owner.request_walkstyle(self.walkstyle, id(self))
            self._walkstyle_active = True

    def _release_walkstyle(self):
        if self._walkstyle_active:
            self._owner.remove_walkstyle(id(self))
            self._walkstyle_active = False

    def on_sim_removed(self, immediate=False):
        if self._vfx is not None:
            self._vfx.stop(immediate=immediate)
            self._vfx = None

    def apply_interaction_lockout_to_owner(self):
        if self.interactions is not None:
            for mixer_affordance in self.interactions.interaction_items:
                while mixer_affordance.lock_out_time_initial is not None:
                    self._owner.set_sub_action_lockout(mixer_affordance, initial_lockout=True)

    def add_handle(self, handle_id, buff_reason=None):
        self.handle_ids.append(handle_id)
        self.buff_reason = buff_reason

    def remove_handle(self, handle_id):
        if handle_id not in self.handle_ids:
            return False
        self.handle_ids.remove(handle_id)
        if self.handle_ids:
            return False
        return True

    def _start_vfx(self):
        if self._vfx is None and self.vfx:
            sim = self._owner.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            self._vfx = self.vfx(sim)
            self._vfx.start()

    def _get_tracker(self):
        if self.commodity is not None:
            return self._owner.get_tracker(self.commodity)

    def _get_commodity_instance(self):
        if self.commodity is None:
            return
        tracker = self._get_tracker()
        if tracker is None:
            return
        commodity_instance = tracker.get_statistic(self.commodity)
        if commodity_instance is None:
            return
        return commodity_instance

    def _get_absolute_timeout_time(self, commodity_instance, threshold):
        rate_multiplier = commodity_instance.get_decay_rate_modifier()
        if rate_multiplier < 1:
            time = commodity_instance.get_decay_time(threshold)
            rate_multiplier = 1
        else:
            time = commodity_instance.get_decay_time(threshold, use_decay_modifier=False)
        if time is not None and time != 0:
            time_now = services.time_service().sim_now
            time_stamp = time_now + interval_in_sim_minutes(time)
            return (time_stamp.absolute_ticks(), rate_multiplier)
        return NO_TIMEOUT

    def get_timeout_time(self):
        commodity_instance = self._get_commodity_instance()
        if commodity_instance is None:
            return NO_TIMEOUT
        buff_type = self.buff_type
        if self._replacing_buff_type is not None:
            buff_type = self._replacing_buff_type
        else:
            buff_type = self.buff_type
        state_index = commodity_instance.get_state_index_matches_buff_type(buff_type)
        if state_index is None:
            return NO_TIMEOUT
        state_lower_bound_value = commodity_instance.commodity_states[state_index].value
        if commodity_instance.convergence_value <= state_lower_bound_value:
            threshold_value = state_lower_bound_value
            comparison = operator.le
        else:
            comparison = operator.ge
            next_state_index = state_index + 1
            if next_state_index >= len(commodity_instance.commodity_states):
                threshold_value = commodity_instance.convergence_value
            else:
                threshold_value = commodity_instance.commodity_states[next_state_index].value
        threshold = sims4.math.Threshold(threshold_value, comparison)
        return self._get_absolute_timeout_time(commodity_instance, threshold)

class SolvableBuff(Buff):
    __qualname__ = 'SolvableBuff'

    def on_add(self, *args, **kwargs):
        super().on_add(*args, **kwargs)
        tracker = self._get_tracker()
        tracker.set_max(self.commodity)

    def on_remove(self, *args, **kwargs):
        super().on_remove(*args, **kwargs)
        tracker = self._get_tracker()
        tracker.remove_statistic(self.commodity)

    def remove_handle(self, handle_id):
        if handle_id not in self.handle_ids:
            return False
        super().remove_handle(handle_id)
        return True

class ClothingBuff(Buff):
    __qualname__ = 'ClothingBuff'
    INSTANCE_TUNABLES = {'removal_minutes': TunableSimMinute(description='\n            Number of sim minutes till buff is removed.  This meant to be used\n            in conjunction with temporary commodity but if using a commodity\n            that already exist commodity convergence value must be minimum\n            value of commodity.\n            ', default=40)}

    @classmethod
    def can_add(cls, owner):
        if cls.commodity is None:
            return True
        tracker = owner.get_tracker(cls.commodity)
        value = tracker.get_value(cls.commodity)
        if value is None:
            return True
        if value < cls.commodity.max_value:
            return True
        return False

    @classmethod
    def _create_temporary_commodity(cls, *args, **kwargs):
        super()._create_temporary_commodity(create_buff_state=False, initial_value=1, *args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._commodity_callback = None
        self._autonomy_handle = None

    def _remove_buff_statistic_callback(self, stat_instance):
        if not self.handle_ids:
            return
        self._owner.remove_buff(self.handle_ids[0])
        stat_instance.decay_enabled = False

    def on_add(self, *args, **kwargs):
        super().on_add(*args, **kwargs)
        if self.commodity is None:
            return
        tracker = self._get_tracker()
        stat = tracker.add_statistic(self.commodity)
        threshold = sims4.math.Threshold(stat.max_value, operator.ge)
        self._commodity_callback = tracker.create_and_activate_listener(self.commodity, threshold, self._remove_buff_statistic_callback)
        tracker.activate_listener(self._commodity_callback)
        modification = (stat.max_value - stat.min_value)/self.removal_minutes
        auto_mod = AutonomyModifier(statistic_modifiers={self.commodity: modification})
        self._autonomy_handle = self._owner.add_statistic_modifier(auto_mod)

    def on_remove(self, *args, **kwargs):
        super().on_remove(*args, **kwargs)
        if self.commodity is None:
            return
        if self._commodity_callback is not None:
            tracker = self._get_tracker()
            tracker.remove_listener(self._commodity_callback)
            self._commodity_callback = None
        if self._autonomy_handle is not None:
            self._owner.remove_statistic_modifier(self._autonomy_handle)
            self._autonomy_handle = None

    def get_timeout_time(self):
        commodity_instance = self._get_commodity_instance()
        if commodity_instance is None:
            return NO_TIMEOUT
        threshold = sims4.math.Threshold(commodity_instance.max_value, operator.ge)
        return self._get_absolute_timeout_time(commodity_instance, threshold)

