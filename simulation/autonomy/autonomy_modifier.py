import collections
from interactions import ParticipantType
from sims4.collections import FrozenAttributeDict
from sims4.repr_utils import standard_auto_repr
from sims4.tuning.tunable import TunableMapping, Tunable, TunableList, TunableSingletonFactory, TunableEnumEntry, TunableReference, OptionalTunable, TunableTuple, TunableEnumFlags, TunableVariant
from sims4.tuning.tunable_base import FilterTag
from singletons import DEFAULT
from snippets import TunableAffordanceFilterSnippet
from statistics.base_statistic import StatisticChangeDirection
from statistics.commodity import Commodity
from statistics.static_commodity import StaticCommodity
from statistics.tunable import CommodityDecayModifierMapping
import enum
import relationships.relationship_track
import services
import sims4.resources
import statistics.commodity
import statistics.skill
import statistics.statistic
import tag

class SuperAffordanceSuppression(enum.Int):
    __qualname__ = 'SuperAffordanceSuppression'
    AUTONOMOUS_ONLY = 0
    USER_DIRECTED = 1
    ALL_AFFORDANCES = 2

class OffLotAutonomyRules(enum.Int):
    __qualname__ = 'OffLotAutonomyRules'
    DEFAULT = 0
    ON_LOT_ONLY = 1
    OFF_LOT_ONLY = 2
    UNLIMITED = 3

SkillTagMultiplier = collections.namedtuple('SkillTagMultiplier', ['multiplier', 'apply_direction'])

class AutonomyModifier:
    __qualname__ = 'AutonomyModifier'
    STATISTIC_RESTRICTIONS = (statistics.commodity.Commodity, statistics.statistic.Statistic, statistics.skill.Skill)
    FACTORY_TUNABLES = {'description': "\n            An encapsulation of a modification to Sim behavior.  These objects\n            are passed to the autonomy system to affect things like scoring,\n            which SI's are available, etc.\n            ", 'super_affordance_compatibility': TunableAffordanceFilterSnippet(description='\n            Tune this to provide suppression to certain affordances when an object has\n            this autonomy modifier.\n            EX: Tune this to exclude all on the buff for the maid to prevent\n                other sims from trying to chat with the maid while the maid is\n                doing her work.\n            To tune if this restriction is for autonomy only, etc, see\n            super_affordance_suppression_mode.\n            Note: This suppression will also apply to the owning sim! So if you\n                prevent people from autonomously interacting with the maid, you\n                also prevent the maid from doing self interactions. To disable\n                this, see suppress_self_affordances.\n            '), 'super_affordance_suppression_mode': TunableEnumEntry(description='\n            Setting this defines how to apply the settings tuned in Super Affordance Compatibility.', tunable_type=SuperAffordanceSuppression, default=SuperAffordanceSuppression.AUTONOMOUS_ONLY), 'super_affordance_suppress_on_add': Tunable(description='\n            If checked, then the suppression rules will be applied when the\n            modifier is added, potentially canceling interactions the owner is\n            running.\n            ', tunable_type=bool, default=False), 'suppress_self_affordances': Tunable(description="\n            If checked, the super affordance compatibility tuned for this \n            autonomy modifier will also apply to the sim performing self\n            interactions.\n            \n            If not checked, we will not do super_affordance_compatibility checks\n            if the target of the interaction is the same as the actor.\n            \n            Ex: Tune the maid's super_affordance_compatibility to exclude all\n                so that other sims will not chat with the maid. But disable\n                suppress_self_affordances so that the maid can still perform\n                interactions on herself (such as her No More Work interaction\n                that tells her she's finished cleaning).\n            ", tunable_type=bool, default=True), 'score_multipliers': TunableMapping(description='\n                Mapping of statistics to multipliers values to the autonomy\n                scores.  EX: giving motive_bladder a multiplier value of 2 will\n                make it so that that motive_bladder is scored twice as high as\n                it normally would be.\n                ', key_type=TunableReference(services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions=STATISTIC_RESTRICTIONS, description='\n                    The stat the multiplier will apply to.\n                    '), value_type=Tunable(float, 1, description='\n                    The autonomy score multiplier for the stat.  Multiplies\n                    autonomy scores by the tuned value.\n                    ')), 'static_commodity_score_multipliers': TunableMapping(description='\n                Mapping of statistics to multipliers values to the autonomy\n                scores.  EX: giving motive_bladder a multiplier value of 2 will\n                make it so that that motive_bladder is scored twice as high as\n                it normally would be.\n                ', key_type=TunableReference(services.get_instance_manager(sims4.resources.Types.STATIC_COMMODITY), description='\n                    The static commodity the multiplier will apply to.\n                    '), value_type=Tunable(float, 1, description='\n                    The autonomy score multiplier for the static commodity.  Multiplies\n                    autonomy scores by the tuned value.\n                    ')), 'relationship_score_multiplier_with_buff_on_target': TunableMapping(description="\n                Mapping of buffs to multipliers.  The buff must exist on the TARGET sim.\n                If it does, this value will be multiplied into the relationship score.\n                \n                Example: The make children desire to socialize with children, you can add \n                this autonomy modifier to the child's age buff.  You can then map it with \n                a key to the child buff to apply a positive multiplier.  An alternative \n                would be to create a mapping to every other age and apply a multiplier that \n                is smaller than 1.\n                ", key_type=TunableReference(services.get_instance_manager(sims4.resources.Types.BUFF), description='\n                    The buff that the target sim must have to apply this multiplier.\n                    '), value_type=Tunable(float, 1, description='\n                    The multiplier to apply.\n                    ')), 'locked_stats': TunableList(TunableReference(services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions=STATISTIC_RESTRICTIONS, description='\n                    The stat the modifier will apply to.\n                    '), description='\n                List of the stats we locked from this modifier.  Locked stats\n                are set to their maximum values and then no longer allowed to\n                decay.\n                '), 'decay_modifiers': CommodityDecayModifierMapping(description='\n                Statistic to float mapping for decay modifiers for\n                statistics.  All decay modifiers are multiplied together along\n                with the decay rate.\n                '), 'skill_tag_modifiers': TunableMapping(description='\n                The skill_tag to float mapping of skill modifiers.  Skills with\n                these tags will have their amount gained multiplied by the\n                sum of all the tuned values.\n                ', key_type=TunableEnumEntry(tag.Tag, tag.Tag.INVALID, description='\n                    What skill tag to apply the modifier on.\n                    '), value_type=Tunable(float, 0)), 'commodities_to_add': TunableList(TunableReference(services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions=statistics.commodity.Commodity), description='\n                Commodites that are added while this autonomy modifier is\n                active.  These commodities are removed when the autonomy\n                modifier is removed.\n                '), 'only_scored_stats': OptionalTunable(TunableList(TunableReference(services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions=STATISTIC_RESTRICTIONS), description='\n                    List of statistics that will only be considered when doing\n                    autonomy.\n                    '), tuning_filter=FilterTag.EXPERT_MODE, description="\n                If enabled, the sim in this role state will consider ONLY these\n                stats when doing autonomy. EX: for the maid, only score\n                commodity_maidrole_clean so she doesn't consider doing things\n                that she shouldn't care about.\n                "), 'only_scored_static_commodities': OptionalTunable(TunableList(StaticCommodity.TunableReference(), description='\n                    List of statistics that will only be considered when doing\n                    autonomy.\n                    '), tuning_filter=FilterTag.EXPERT_MODE, description='\n                If enabled, the sim in this role state will consider ONLY these\n                static commodities when doing autonomy. EX: for walkbys, only\n                consider the ringing the doorbell\n                '), 'stat_use_multiplier': TunableMapping(description='\n                List of stats and multiplier to affect their increase-decrease.\n                All stats on this list whenever they get modified (e. by a \n                constant modifier on an interaction, an interaction result...)\n                will apply the multiplier to their modified values. \n                e. A toilet can get a multiplier to decrease the repair rate\n                when its used, for this we would tune the commodity\n                brokenness and the multiplier 0.5 (to decrease its effect)\n                This tunable multiplier will affect the object statistics\n                not the ones for the sims interacting with it.\n                ', key_type=TunableReference(services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions=STATISTIC_RESTRICTIONS, description='\n                    The stat the multiplier will apply to.\n                    '), value_type=TunableTuple(description='\n                    Float value to apply to the statistic whenever its\n                    affected.  Greater than 1.0 if you want to increase.\n                    Less than 1.0 if you want a decrease (>0.0). \n                    A value of 0 is considered invalid and is skipped.\n                    ', multiplier=Tunable(description='\n                        Float value to apply to the statistic whenever its\n                        affected.  Greater than 1.0 if you want to increase.\n                        Less than 1.0 if you want a decrease (>0.0). \n                        A value of 0 is considered invalid and is skipped.\n                        ', tunable_type=float, default=1.0), apply_direction=TunableEnumEntry(StatisticChangeDirection, StatisticChangeDirection.BOTH, description='\n                        Direction on when the multiplier should work on the \n                        statistic.  For example a decrease on an object \n                        brokenness rate, should not increase the time it takes to \n                        repair it.\n                        '))), 'relationship_multipliers': TunableMapping(description='\n                List of relationship tracks and multiplier to affect their\n                increase or decrease of track value. All stats on this list\n                whenever they get modified (e. by a constant modifier on an\n                interaction, an interaction result...) will apply the\n                multiplier to their modified values. e.g. A LTR_Friendship_Main\n                can get a multiplier to decrease the relationship decay when\n                interacting with someone with a given trait, for this we would\n                tune the relationship track LTR_Friendship_Main and the\n                multiplier 0.5 (to decrease its effect)\n                ', key_type=relationships.relationship_track.RelationshipTrack.TunableReference(description='\n                    The Relationship track the multiplier will apply to.\n                    '), value_type=TunableTuple(description="\n                    Float value to apply to the statistic whenever it's\n                    affected.  Greater than 1.0 if you want to increase.\n                    Less than 1.0 if you want a decrease (>0.0).\n                    ", multiplier=Tunable(tunable_type=float, default=1.0), apply_direction=TunableEnumEntry(description='\n                        Direction on when the multiplier should work on the \n                        statistic.  For example a decrease on an object \n                        brokenness rate, should not increase the time it takes to \n                        repair it.\n                        ', tunable_type=StatisticChangeDirection, default=StatisticChangeDirection.BOTH))), 'off_lot_autonomy_rule': OptionalTunable(TunableVariant(description="\n                The rules to apply for how autonomy handle on-lot and off-lot\n                targets.\n                \n                DEFAULT:\n                    Sims will behave according to their default behavior.  Off-\n                    lot sims who are outside the lot's tolerance will not\n                    autonomously perform interactions on the lot.  Sims will\n                    only autonomously perform off-lot interactions within their\n                    off-lot radius.\n                ON_LOT_ONLY:\n                    Sims will only consider targets on the active lot.  They\n                    will ignore the off lot radius and off lot tolerance\n                    settings.\n                OFF_LOT_ONLY:\n                    Sims will only consider targets that are off the active lot.\n                    They will ignore the off lot tolerance settings, but they\n                    will respect the off lot radius.\n                UNLIMITED:\n                    Sims will consider all objects regardless of on/off lot\n                    status.\n                ", default_behavior=TunableTuple(description="\n                    Sims will behave according to their default behavior.  Off-\n                    lot sims who are outside the lot's tolerance will not\n                    autonomously perform interactions on the lot.  Sims will\n                    only autonomously perform off-lot interactions within their\n                    off-lot radius.\n                    ", locked_args={'rule': OffLotAutonomyRules.DEFAULT}, tolerance=Tunable(description='\n                        This is how many meters the Sim can be off of the lot while still being \n                        considered on the lot for the purposes of autonomy.  For example, if \n                        this is set to 5, the sim can be 5 meters from the edge of the lot and \n                        still consider all the objects on the lot for autonomy.  If the sim were \n                        to step 6 meters from the lot, the sim would be considered off the lot \n                        and would only score off-lot objects that are within the off lot radius.\n                        \n                        Note: If this value is set to anything below 0, it will use the global \n                        default in autonomy.autonomy_modes.OFF_LOT_TOLERANCE.\n                        ', tunable_type=float, default=-1), radius=Tunable(description='\n                        The radius around the sim in which he will consider off-lot objects.  If it is \n                        0, the Sim will not consider off-lot objects at all.  This is not recommended \n                        since it will keep them from running any interactions unless they are already \n                        within the tolerance for that lot (set with Off Lot Tolerance).\n                        \n                        Note: If this value is less than zero, the range is considered infinite.  The \n                        sim will consider every off-lot object.\n                        ', tunable_type=float, default=0)), on_lot_only=TunableTuple(description='\n                    Sims will only consider targets on the active lot.\n                    ', locked_args={'rule': OffLotAutonomyRules.ON_LOT_ONLY, 'tolerance': 0, 'radius': 0}), off_lot_only=TunableTuple(description='\n                    Sims will only consider targets that are off the active lot. \n                    ', locked_args={'rule': OffLotAutonomyRules.OFF_LOT_ONLY, 'tolerance': 0}, radius=Tunable(description='\n                        The radius around the sim in which he will consider off-lot objects.  If it is \n                        0, the Sim will not consider off-lot objects at all.  This is not recommended \n                        since it will keep them from running any interactions unless they are already \n                        within the tolerance for that lot (set with Off Lot Tolerance).\n                        \n                        Note: If this value is less than zero, the range is considered infinite.  The \n                        sim will consider every off-lot object.\n                        ', tunable_type=float, default=-1)), unlimited=TunableTuple(description='\n                    Sims will consider all objects regardless of on/off lot\n                    status.\n                    ', locked_args={'rule': OffLotAutonomyRules.UNLIMITED, 'tolerance': 0, 'radius': 0}), default='default_behavior')), 'override_convergence_value': OptionalTunable(description="\n            If enabled it will set a new convergence value to the tuned\n            statistics.  The decay of those statistics will start moving\n            toward the new convergence value.\n            Convergence value will apply as long as these modifier is active,\n            when modifier is removed, convergence value will return to default\n            tuned value.\n            As a tuning restriction when this modifier gets removed we will \n            reset the convergence to its original value.  This means that we \n            don't support two states at the same time overwriting convergence\n            so we should'nt tune multiple convergence overrides on the same \n            object.\n            ", tunable=TunableMapping(description='\n                Mapping of statistic to new convergence value.\n                ', key_type=Commodity.TunableReference(), value_type=Tunable(description='\n                    Value to which the statistic should convert to.\n                    ', tunable_type=int, default=0)), disabled_name='Use_default_convergence', enabled_name='Set_new_convergence_value'), 'subject': TunableVariant(description='\n            Specifies to whom this autonomy modifier will apply.\n            - Apply to owner: Will apply the modifiers to the object or sim who \n            is triggering the modifier.  \n            e.g Buff will apply the modifiers to the sim when he gets the buff.  \n            An object will apply the modifiers to itself when it hits a state.\n            - Apply to interaction participant:  Will save the modifiers to \n            be only triggered when the object/sim who holds the modifier \n            is on an interaction.  When the interaction starts the the subject\n            tuned will get the modifiers during the duration of the interaction. \n            e.g A sim with modifiers to apply on an object will only trigger \n            when the sim is interactin with an object.\n            ', apply_on_interaction_to_participant=OptionalTunable(TunableEnumFlags(description='\n                    Subject on which the modifiers should apply.  When this is set\n                    it will mean that the autonomy modifiers will trigger on a \n                    subect different than the object where they have been added.\n                    e.g. a shower ill have hygiene modifiers that have to affect \n                    the Sim ', enum_type=ParticipantType, default=ParticipantType.Object)), default='apply_to_owner', locked_args={'apply_to_owner': False})}

    def __init__(self, score_multipliers=None, static_commodity_score_multipliers=None, relationship_score_multiplier_with_buff_on_target=None, super_affordance_compatibility=None, super_affordance_suppression_mode=SuperAffordanceSuppression.AUTONOMOUS_ONLY, suppress_self_affordances=False, super_affordance_suppress_on_add=False, locked_stats=set(), decay_modifiers=None, statistic_modifiers=None, skill_tag_modifiers=None, commodities_to_add=(), only_scored_stats=None, only_scored_static_commodities=None, stat_use_multiplier=None, relationship_multipliers=None, off_lot_autonomy_rule=None, override_convergence_value=None, subject=None, exclusive_si=None):
        self._super_affordance_compatibility = super_affordance_compatibility
        self._super_affordance_suppression_mode = super_affordance_suppression_mode
        self._suppress_self_affordances = suppress_self_affordances
        self._super_affordance_suppress_on_add = super_affordance_suppress_on_add
        self._score_multipliers = score_multipliers
        self._locked_stats = set(locked_stats)
        self._decay_modifiers = decay_modifiers
        self._statistic_modifiers = statistic_modifiers
        self._relationship_score_multiplier_with_buff_on_target = relationship_score_multiplier_with_buff_on_target
        self._skill_tag_modifiers = skill_tag_modifiers
        self._commodities_to_add = commodities_to_add
        self._stat_use_multiplier = stat_use_multiplier
        self._relationship_multipliers = relationship_multipliers
        self._off_lot_autonomy_rule = off_lot_autonomy_rule
        self._subject = subject
        self._override_convergence_value = override_convergence_value
        self._exclusive_si = exclusive_si
        self._skill_tag_modifiers = {}
        if skill_tag_modifiers:
            for (skill_tag, skill_tag_modifier) in skill_tag_modifiers.items():
                skill_modifier = SkillTagMultiplier(skill_tag_modifier, StatisticChangeDirection.INCREASE)
                self._skill_tag_modifiers[skill_tag] = skill_modifier
        if static_commodity_score_multipliers:
            if self._score_multipliers is not None:
                self._score_multipliers = FrozenAttributeDict(self._score_multipliers, static_commodity_score_multipliers)
            else:
                self._score_multipliers = static_commodity_score_multipliers
        self._static_commodity_score_multipliers = static_commodity_score_multipliers
        self._only_scored_stat_types = None
        if only_scored_stats is not None:
            self._only_scored_stat_types = []
            self._only_scored_stat_types.extend(only_scored_stats)
        if only_scored_static_commodities is not None:
            if self._only_scored_stat_types is None:
                self._only_scored_stat_types = []
            self._only_scored_stat_types.extend(only_scored_static_commodities)

    def __repr__(self):
        return standard_auto_repr(self)

    @property
    def exclusive_si(self):
        return self._exclusive_si

    def affordance_suppressed(self, sim, aop_or_interaction, user_directed=DEFAULT):
        user_directed = aop_or_interaction.is_user_directed if user_directed is DEFAULT else user_directed
        if not self._suppress_self_affordances and aop_or_interaction.target == sim:
            return False
        affordance = aop_or_interaction.affordance
        if self._super_affordance_compatibility is None:
            return False
        if user_directed and self._super_affordance_suppression_mode == SuperAffordanceSuppression.AUTONOMOUS_ONLY:
            return False
        if not user_directed and self._super_affordance_suppression_mode == SuperAffordanceSuppression.USER_DIRECTED:
            return False
        return not self._super_affordance_compatibility(affordance)

    def locked_stats_gen(self):
        for stat in self._locked_stats:
            yield stat

    def get_score_multiplier(self, stat_type):
        if self._score_multipliers is not None and stat_type in self._score_multipliers:
            return self._score_multipliers[stat_type]
        return 1

    def get_stat_multiplier(self, stat_type, participant_type):
        if self._stat_use_multiplier is None:
            return 1
        if self._subject == participant_type and stat_type in self._stat_use_multiplier:
            return self._stat_use_multiplier[stat_type].multiplier
        return 1

    @property
    def subject(self):
        return self._subject

    @property
    def statistic_modifiers(self):
        return self._statistic_modifiers

    @property
    def statistic_multipliers(self):
        return self._stat_use_multiplier

    @property
    def relationship_score_multiplier_with_buff_on_target(self):
        return self._relationship_score_multiplier_with_buff_on_target

    @property
    def relationship_multipliers(self):
        return self._relationship_multipliers

    @property
    def decay_modifiers(self):
        return self._decay_modifiers

    @property
    def skill_tag_modifiers(self):
        return self._skill_tag_modifiers

    @property
    def commodities_to_add(self):
        return self._commodities_to_add

    @property
    def override_convergence(self):
        return self._override_convergence_value

    def is_locked(self, stat_type):
        if self._locked_stats and stat_type in self._locked_stats:
            return True
        return False

    def is_scored(self, stat_type):
        if self._only_scored_stat_types is None or stat_type in self._only_scored_stat_types:
            return True
        return False

    @property
    def off_lot_autonomy_rule(self):
        return self._off_lot_autonomy_rule

    @property
    def super_affordance_suppress_on_add(self):
        return self._super_affordance_suppress_on_add

TunableAutonomyModifier = TunableSingletonFactory.create_auto_factory(AutonomyModifier)
