import random
from interactions import ParticipantType
from interactions.utils import LootType
from interactions.utils.loot_basic_op import BaseLootOperation, BaseTargetedLootOperation
from relationships.global_relationship_tuning import RelationshipGlobalTuning
from sims4 import math
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.tunable import Tunable, TunableVariant, TunableEnumFlags, TunableInterval, TunableEnumEntry, TunableReference, TunablePercent, TunableFactory, TunableRate, TunableList
from sims4.tuning.tunable_base import RateDescriptions
from singletons import DEFAULT
from statistics.skill import Skill, TunableSkillLootData
import enum
import interactions.utils
import services
import sims4.log
import sims4.resources
import statistics.skill
import statistics.statistic_categories
logger = sims4.log.Logger('SimStatistics')
autonomy_logger = sims4.log.Logger('Autonomy')
GAIN_TYPE_RATE = 0
GAIN_TYPE_AMOUNT = 1

class StatisticOperation(BaseLootOperation):
    __qualname__ = 'StatisticOperation'
    STATIC_CHANGE_INTERVAL = 1
    DISPLAY_TEXT = TunableLocalizedStringFactory(description='\n        A string displaying the amount that this stat operation awards. It will\n        be provided two tokens: the statistic name and the value change.\n        ')
    DEFAULT_PARTICIPANT_ARGUMENTS = {'subject_participant_type_options': {'description': '\n            The owner of the stat that we are operating on.\n            ', 'use_flags_enum': True}}
    FACTORY_TUNABLES = {'stat': TunableReference(description='\n            The statistic we are operating on.', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)), 'advertise': Tunable(description='\n            This statistic operation should advertise to autonomy.  This only\n            advertises if the statistic operation is used as part of Periodic\n            Statistic Change.\n            ', tunable_type=bool, needs_tuning=True, default=True)}

    def __init__(self, stat=None, **kwargs):
        super().__init__(**kwargs)
        self._stat = stat
        self._ad_multiplier = 1
        self._loot_type = LootType.GENERIC
        if self._stat is not None and issubclass(self._stat, Skill):
            self._loot_type = LootType.SKILL

    def __repr__(self):
        return '<{} {} {}>'.format(type(self).__name__, self.stat, self.subject)

    @property
    def stat(self):
        return self._stat

    @property
    def loot_type(self):
        return self._loot_type

    @property
    def ad_multiplier(self):
        return self._ad_multiplier

    def modify_ad_multiplier(self, multiplier):
        pass

    def _apply_to_subject_and_target(self, subject, target, resolver):
        stat = self.get_stat(None)
        if not subject.is_locked(stat):
            tracker = subject.get_tracker(stat)
            self._apply(tracker, interaction=resolver.interaction)

    def _apply(self, tracker, interaction=None):
        raise NotImplementedError

    def get_value(self, obj=None, interaction=None, sims=None):
        raise NotImplementedError

    def _attempt_to_get_real_stat_value(self, obj, interaction):
        if obj is None and interaction is not None:
            obj = interaction.get_participant(ParticipantType.Actor)
        if obj is not None:
            stat_value = obj.get_stat_value(self.stat)
            if stat_value is not None:
                return stat_value
        return self.stat.default_value

    def _get_interval(self, aop):
        return aop.super_affordance.approximate_duration

    def get_fulfillment_rate(self, interaction):
        if not self._advertise:
            return 0
        value = self.get_value(interaction=interaction)
        if interaction.target is not None:
            value *= interaction.target.get_stat_multiplier(self.stat, self.subject)
        interval = self._get_interval(interaction)
        if interval <= 0:
            logger.error('Tuning error: affordance interval should be greater than 0 (defaulting to 1)')
            interval = 1
        score = value/interval
        return score

    def _get_display_text(self):
        if self.stat.stat_name is not None:
            value = self.get_value()
            if value:
                return self.DISPLAY_TEXT(*self._get_display_text_tokens())

    def _get_display_text_tokens(self):
        return (self.stat.stat_name, self.get_value())

def _get_tunable_amount(gain_type=GAIN_TYPE_AMOUNT):
    if gain_type == GAIN_TYPE_RATE:
        return TunableRate(description='\n            The gain, per interval for this operation.\n            ', display_name='Rate', rate_description=RateDescriptions.PER_SIM_MINUTE, tunable_type=float, default=0)
    if gain_type == GAIN_TYPE_AMOUNT:
        return Tunable(description='\n            The one-time gain for this operation.\n            ', tunable_type=float, default=0)
    raise ValueError('Unsupported gain type: {}'.format(gain_type))

class StatisticChangeOp(StatisticOperation):
    __qualname__ = 'StatisticChangeOp'
    FACTORY_TUNABLES = {'amount': lambda *args, **kwargs: _get_tunable_amount(*args, **kwargs), 'exclusive_to_owning_si': Tunable(description='\n            If enabled, this gain will be exclusive to the SI that created it\n            and will not be allowed to occur if the sim is running mixers from\n            a different SI.\n            If disabled, this gain will happen as long as this\n            SI is active, regardless of which SI owns the mixer the sim is\n            currently running.\n            This is only effective on Sims.\n            ', tunable_type=bool, needs_tuning=True, default=True)}

    def __init__(self, amount=0, min_value=None, max_value=None, exclusive_to_owning_si=None, **kwargs):
        super().__init__(**kwargs)
        self._amount = amount
        self._min_value = min_value
        self._max_value = max_value
        self._exclusive_to_owning_si = exclusive_to_owning_si

    @property
    def exclusive_to_owning_si(self):
        return self._exclusive_to_owning_si

    def get_value(self, obj=None, interaction=None, sims=None):
        multiplier = 1
        if sims:
            targets = sims.copy()
        elif interaction is not None:
            targets = interaction.get_participants(ParticipantType.Actor)
        else:
            targets = None
        if targets:
            multiplier = self.stat.get_skill_based_statistic_multiplier(targets, self._amount)
        return self._amount*multiplier

    def get_user_facing_change(self):
        return self._amount

    def _get_interval(self, aop):
        return StatisticOperation.STATIC_CHANGE_INTERVAL

    def _apply(self, tracker, interaction=None):
        tracker.add_value(self.stat, self._amount, min_value=self._min_value, max_value=self._max_value, interaction=interaction)

    def _remove(self, tracker, interaction=None):
        tracker.add_value(self.stat, -self._amount, min_value=self._min_value, max_value=self._max_value, interaction=interaction)

class StatisticSetOp(StatisticOperation):
    __qualname__ = 'StatisticSetOp'
    FACTORY_TUNABLES = {'value': Tunable(description='\n            The new statistic value.', tunable_type=int, default=None)}

    def __init__(self, value=None, **kwargs):
        super().__init__(**kwargs)
        self.value = value

    def __repr__(self):
        if self.stat is not None:
            return '<{}: {} set to {}>'.format(self.__class__.__name__, self.stat.__name__, self.value)
        return '<{}: Stat is None in StatisticSetOp>'.format(self.__class__.__name__)

    def get_value(self, obj=None, interaction=None, sims=None):
        stat_value = self._attempt_to_get_real_stat_value(obj, interaction)
        return self.value - stat_value

    def _apply(self, tracker, interaction=None):
        tracker.set_value(self.stat, self.value, interaction=interaction)

class StatisticSetRangeOp(StatisticOperation):
    __qualname__ = 'StatisticSetRangeOp'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value.lower_bound > value.upper_bound:
            logger.error('StatisticSetRangeOp has incorrect bounds in the range [lower_bound:{}, upper_bound:{}]. Please update tuning.', value.lower_bound, value.upper_bound)

    FACTORY_TUNABLES = {'locked_args': {'subject': ParticipantType.Actor}, 'lower_bound': Tunable(description='\n                The lower bound of the range.', tunable_type=int, default=None), 'upper_bound': Tunable(description='\n                The upper bound of the range. upper_bound >= lower_bound', tunable_type=int, default=None), 'verify_tunable_callback': _verify_tunable_callback}
    REMOVE_INSTANCE_TUNABLES = ('advertise', 'tests', 'chance')

    def __init__(self, lower_bound=None, upper_bound=None, **kwargs):
        super().__init__(**kwargs)
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound

    def __repr__(self):
        if self.stat is not None:
            return '<{}: {} set in range [{},{}]>'.format(self.__class__.__name__, self.stat.__name__, self.lower_bound, self.upper_bound)
        return '<{}: Stat is None in StatisticSetRangeOp>'.format(self.__class__.__name__)

    def get_value(self, obj=None, interaction=None, sims=None):
        stat_value = self._attempt_to_get_real_stat_value(obj, interaction)
        return self.upper_bound - stat_value

    def _apply(self, tracker, interaction=None):
        value = random.randint(self.lower_bound, self.upper_bound)
        tracker.set_value(self.stat, value, interaction=None)

class StatisticSetMaxOp(StatisticOperation):
    __qualname__ = 'StatisticSetMaxOp'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def __repr__(self):
        if self.stat is not None:
            return '<{}: {} maximum>'.format(self.__class__.__name__, self.stat.__name__)
        return '<{}: Stat is None in StatisticSetMaxOp>'.format(self.__class__.__name__)

    def get_value(self, obj=None, interaction=None, sims=None):
        stat_value = self._attempt_to_get_real_stat_value(obj, interaction)
        return self.stat.max_value - stat_value

    def _apply(self, tracker, **kwargs):
        tracker.set_max(self.stat)

class StatisticSetMinOp(StatisticOperation):
    __qualname__ = 'StatisticSetMinOp'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def __repr__(self):
        if self.stat is not None:
            return '<{}: {} minimum>'.format(self.__class__.__name__, self.stat.__name__)
        return '<{}: Stat is None in StatisticSetMinOp>'.format(self.__class__.__name__)

    def get_value(self, obj=None, interaction=None, sims=None):
        stat_value = self._attempt_to_get_real_stat_value(obj, interaction)
        return self.stat.min_value - stat_value

    def _apply(self, tracker, **kwargs):
        tracker.set_min(self.stat)

class StatisticRemoveOp(StatisticOperation):
    __qualname__ = 'StatisticRemoveOp'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def __repr__(self):
        if self.stat is not None:
            return '<{}: {} remove/set to convergence>'.format(self.__class__.__name__, self.stat.__name__)
        return '<{}: Stat is None in StatisticRemoveOp>'.format(self.__class__.__name__)

    def get_value(self, obj=None, interaction=None, sims=None):
        return 0

    def _apply(self, tracker, **kwargs):
        tracker.remove_statistic(self.stat)

class TransferType(enum.Int):
    __qualname__ = 'TransferType'
    ADDITIVE = 0
    SUBTRACTIVE = 1
    REPLACEMENT = 2

class StatisticTransferOp(StatisticOperation):
    __qualname__ = 'StatisticTransferOp'
    FACTORY_TUNABLES = {'statistic_donor': TunableEnumEntry(description='\n            The owner of the statistic we are transferring the value from.\n            ', tunable_type=ParticipantType, default=ParticipantType.TargetSim), 'transferred_stat': TunableReference(description='\n            The statistic whose value to transfer.\n            ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)), 'transfer_type': TunableEnumEntry(description='\n            Type of statistic transfer to use.\n            ', tunable_type=TransferType, default=TransferType.ADDITIVE)}

    def __init__(self, statistic_donor=None, transferred_stat=None, transfer_type=None, **kwargs):
        super().__init__(**kwargs)
        self._statistic_donor = statistic_donor
        self._transferred_stat = transferred_stat
        self._transfer_type = transfer_type
        self._donors = None

    def __repr__(self):
        if self.stat is not None:
            return '<{}: {} transfer>'.format(self.__class__.__name__, self.stat.__name__)
        return '<{}: Stat is None in StatisticTransferOp>'.format(self.__class__.__name__)

    def get_value(self, obj=None, interaction=None, sims=None):
        return self.stat.get_value()

    def _apply_to_subject_and_target(self, subject, target, resolver):
        self._donors = resolver.get_participants(self._statistic_donor)
        super()._apply_to_subject_and_target(subject, target, resolver)

    def _apply(self, tracker, interaction=None):
        donors = self._donors if self._donors is not None else interaction.get_participants(self._statistic_donor)
        for donor in donors:
            transfer_value = donor.statistic_tracker.get_value(self._transferred_stat)
            if self._transfer_type == TransferType.ADDITIVE:
                tracker.add_value(self.stat, transfer_value, interaction=interaction)
            elif self._transfer_type == TransferType.SUBTRACTIVE:
                tracker.add_value(self.stat, -transfer_value, interaction=interaction)
            else:
                while self._transfer_type == TransferType.REPLACEMENT:
                    tracker.set_value(self.stat, transfer_value, interaction=interaction)

class NormalizeStatisticsOp(BaseTargetedLootOperation):
    __qualname__ = 'NormalizeStatisticsOp'
    FACTORY_TUNABLES = {'stats_to_normalize': TunableList(description='\n            Stats to be affected by the normalization.\n            ', tunable=TunableReference(services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions=statistics.commodity.Commodity)), 'normalize_percent': TunablePercent(description='\n            In seeking the average value, this is the percent of movement toward the average value \n            the stat will move to achieve the new value. For example, if you have a Sim with 50 \n            fun, and a Sim with 100 fun, and want to normalize them exactly halfway to their \n            average of 75, tune this to 100%. A value of 50% would move one Sim to 67.5 and the other\n            to 77.5\n            ', default=100, maximum=100, minimum=0)}

    def __init__(self, stats_to_normalize, normalize_percent, **kwargs):
        super().__init__(**kwargs)
        self._stats = stats_to_normalize
        self._normalize_percent = normalize_percent

    def _apply_to_subject_and_target(self, subject, target, resolver):
        for stat_type in self._stats:
            source_tracker = target.get_tracker(stat_type)
            if not source_tracker.has_statistic(stat_type):
                pass
            target_tracker = subject.get_tracker(stat_type)
            source_value = source_tracker.get_value(stat_type)
            target_value = target_tracker.get_value(stat_type)
            average_value = (source_value + target_value)/2
            source_percent_gain = (source_value - average_value)*self._normalize_percent
            target_percent_gain = (target_value - average_value)*self._normalize_percent
            target_tracker.set_value(stat_type, source_value - source_percent_gain)
            source_tracker.set_value(stat_type, target_value - target_percent_gain)

class RelationshipOperation(StatisticOperation, BaseTargetedLootOperation):
    __qualname__ = 'RelationshipOperation'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, relationship_operation=None, **tuned_values):
        if relationship_operation.target_participant_type is None or relationship_operation.target_participant_type == ParticipantType.Invalid:
            logger.error('Relationship Operation: {} has no Target Participant Type tuned.', instance_class)

    FACTORY_TUNABLES = {'track': TunableReference(description='\n            The track to be manipulated.', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions='RelationshipTrack'), 'track_range': TunableInterval(description='\n            The relationship track must > lower_bound and <= upper_bound for\n            the operation to apply.', tunable_type=float, default_lower=-101, default_upper=100), 'locked_args': {'advertise': False}, 'verify_tunable_callback': _verify_tunable_callback}
    DEFAULT_PARTICIPANT_ARGUMENTS = {'subject_participant_type_options': {'description': '\n            The owner Sim for this relationship change. Relationship is\n            applied to all Sims in this list, to all Sims in the Target\n            Participant Type list\n            ', 'use_flags_enum': True}, 'target_participant_type_options': {'description': "\n            The target Sim for this relationship change. Any\n            relationship that would be given to 'self' is discarded.\n            ", 'use_flags_enum': True}}

    def __init__(self, track_range=None, track=DEFAULT, **kwargs):
        super().__init__(**kwargs)
        self._track_range = track_range
        self._track = track
        if self._track is None:
            self._track = DEFAULT
        self._loot_type = LootType.RELATIONSHIP

    def get_stat(self, interaction, source=None, target=None):
        if source is None:
            actors = interaction.get_participants(self.subject)
            source = next(iter(actors))
        if target is None:
            targets = interaction.get_participants(self.target_participant_type)
            for potential_target in targets:
                while potential_target is not source:
                    target = potential_target
                    break
        if target is None:
            return
        if isinstance(target, int):
            target_sim_id = target
        else:
            target_sim_id = target.sim_id
        return source.sim_info.relationship_tracker.get_relationship_track(target_sim_id, self._track, True)

    def _get_interval(self, aop):
        return StatisticOperation.STATIC_CHANGE_INTERVAL

    def _apply_to_subject_and_target(self, subject, target, resolver):
        source_sim_info = self._get_sim_info_from_participant(subject)
        if not source_sim_info:
            return
        target_sim_info = self._get_sim_info_from_participant(target)
        if not target_sim_info:
            return
        self._apply_to_sim_info(source_sim_info, target_sim_info.sim_id, resolver.interaction)
        self._apply_to_sim_info(target_sim_info, source_sim_info.sim_id, resolver.interaction)

    def _get_sim_info_from_participant(self, participant):
        if isinstance(participant, int):
            sim_info_manager = services.sim_info_manager()
            if sim_info_manager is None:
                return
            sim_info = sim_info_manager.get(participant)
        else:
            sim_info = getattr(participant, 'sim_info', participant)
        if sim_info is None:
            logger.error('Could not get Sim Info from {0} in StatisticAddRelationship loot op.', participant)
        return sim_info

    def _apply_to_sim_info(self, source_sim_info, target_sim_id, interaction):
        if self._track is DEFAULT:
            self._track = RelationshipGlobalTuning.REL_INSPECTOR_TRACK
        rel_stat = source_sim_info.relationship_tracker.get_relationship_track(target_sim_id, self._track, True)
        if rel_stat is not None:
            self._maybe_apply_op(rel_stat.tracker, source_sim_info, interaction=interaction)

    def _maybe_apply_op(self, tracker, target_sim, **kwargs):
        value = tracker.get_value(self._track)
        if self._track_range.lower_bound < value <= self._track_range.upper_bound:
            self._apply(tracker, target_sim, **kwargs)

class StatisticAddRelationship(RelationshipOperation):
    __qualname__ = 'StatisticAddRelationship'
    FACTORY_TUNABLES = {'amount': lambda *args, **kwargs: _get_tunable_amount(*args, **kwargs)}

    def __init__(self, amount, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._amount = amount

    def get_value(self, **kwargs):
        return self._amount

    def _apply(self, tracker, target_sim, **kwargs):
        tracker.add_value(self._track, self._amount, **kwargs)

class StatisticSetRelationship(RelationshipOperation):
    __qualname__ = 'StatisticSetRelationship'
    FACTORY_TUNABLES = {'value': Tunable(description='\n                The value to set the relationship to.', tunable_type=float, default=0)}

    def __init__(self, value, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._value = value

    def get_value(self, **kwargs):
        return self._value - self._track.default_value

    def _apply(self, tracker, target_sim, **kwargs):
        tracker.set_value(self._track, self._value, **kwargs)

class SkillEffectivenessLoot(StatisticChangeOp):
    __qualname__ = 'SkillEffectivenessLoot'
    FACTORY_TUNABLES = {'subject': TunableEnumEntry(description='\n            The sim(s) to operation is applied to.', tunable_type=ParticipantType, default=ParticipantType.Actor), 'effectiveness': TunableEnumEntry(description='\n            Enum to determine which curve to use when giving points to sim.', tunable_type=statistics.skill.SkillEffectiveness, needs_tuning=True, default=statistics.skill.SkillEffectiveness.STANDARD), 'level': Tunable(description='\n            x-point on skill effectiveness curve.', tunable_type=int, default=0), 'locked_args': {'amount': 0}}

    def __init__(self, stat, amount, effectiveness, level, **kwargs):
        if stat is None:
            final_amount = 0
        else:
            final_amount = stat.get_skill_effectiveness_points_gain(effectiveness, level)
        super().__init__(stat=stat, amount=final_amount, **kwargs)

class TunableStatisticChange(TunableVariant):
    __qualname__ = 'TunableStatisticChange'

    def __init__(self, *args, locked_args=None, variant_locked_args=None, gain_type=GAIN_TYPE_AMOUNT, include_relationship_ops=True, **kwargs):
        if include_relationship_ops:
            kwargs['relationship_change'] = StatisticAddRelationship.TunableFactory(description='\n                Adds to the relationship score statistic for this Super Interaction\n                ', amount=gain_type, **RelationshipOperation.DEFAULT_PARTICIPANT_ARGUMENTS)
            kwargs['relationship_set'] = StatisticSetRelationship.TunableFactory(description='\n                Sets the relationship score statistic to a specific value.\n                ', **RelationshipOperation.DEFAULT_PARTICIPANT_ARGUMENTS)
        super().__init__(description='A variant of statistic operations.', statistic_change=StatisticChangeOp.TunableFactory(description='\n                Modify the value of a statistic.\n                ', locked_args=locked_args, amount=gain_type, **StatisticOperation.DEFAULT_PARTICIPANT_ARGUMENTS), statistic_remove=StatisticRemoveOp.TunableFactory(description='Attempt to remove the specified statistic.', locked_args=locked_args, **StatisticOperation.DEFAULT_PARTICIPANT_ARGUMENTS), statistic_set=StatisticSetOp.TunableFactory(description='Set a statistic to the provided value.', locked_args=locked_args, **StatisticOperation.DEFAULT_PARTICIPANT_ARGUMENTS), statistic_set_max=StatisticSetMaxOp.TunableFactory(description='Set a statistic to its maximum value.', locked_args=locked_args, **StatisticOperation.DEFAULT_PARTICIPANT_ARGUMENTS), statistic_set_min=StatisticSetMinOp.TunableFactory(description='Set a statistic to its minimum value.', locked_args=locked_args, **StatisticOperation.DEFAULT_PARTICIPANT_ARGUMENTS), statistic_set_in_range=StatisticSetRangeOp.TunableFactory(description='Set a statistic to a random value in the tuned range.', locked_args=locked_args, **StatisticOperation.DEFAULT_PARTICIPANT_ARGUMENTS), statistic_transfer=StatisticTransferOp.TunableFactory(description='Transfer a statistic value from one target to another.', locked_args=locked_args, **StatisticOperation.DEFAULT_PARTICIPANT_ARGUMENTS), statistic_remove_by_category=RemoveStatisticByCategory.TunableFactory(description='Remove all statistics of a specific category.'), statistic_change_by_category=ChangeStatisticByCategory.TunableFactory(description='Change value of  all statistics of a specific category.'), locked_args=variant_locked_args, *args, **kwargs)

class TunableProgressiveStatisticChange(TunableVariant):
    __qualname__ = 'TunableProgressiveStatisticChange'

    def __init__(self, *args, locked_args=None, **kwargs):
        super().__init__(description='A variant of statistic operations.', statistic_change=StatisticChangeOp.TunableFactory(description='\n                Modify the value of a statistic.\n                ', locked_args=locked_args, **StatisticOperation.DEFAULT_PARTICIPANT_ARGUMENTS), relationship_change=StatisticAddRelationship.TunableFactory(description='\n                Adds to the relationship score statistic for this Super Interaction\n                ', **RelationshipOperation.DEFAULT_PARTICIPANT_ARGUMENTS), *args, **kwargs)

class DynamicSkillLootOp(BaseLootOperation):
    __qualname__ = 'DynamicSkillLootOp'
    FACTORY_TUNABLES = {'skill_loot_data_override': TunableSkillLootData(description="\n            This data will override loot data in the interaction. In\n            interaction, tuning field 'skill_loot_data' is used to determine\n            skill loot data."), 'exclusive_to_owning_si': Tunable(description='\n            If enabled, this gain will be exclusive to the SI that created it\n            and will not be allowed to occur if the sim is running mixers from\n            a different SI.\n            If disabled, this gain will happen as long as this\n            SI is active, regardless of which SI owns the mixer the sim is\n            currently running.\n            This is only effective on Sims.\n            ', tunable_type=bool, needs_tuning=True, default=True)}

    def __init__(self, skill_loot_data_override, exclusive_to_owning_si, **kwargs):
        super().__init__(**kwargs)
        self._skill_loot_data_override = skill_loot_data_override
        self._exclusive_to_owning_si = exclusive_to_owning_si

    @property
    def exclusive_to_owning_si(self):
        return self._exclusive_to_owning_si

    def _get_skill_level_data(self, interaction):
        stat = self._skill_loot_data_override.stat
        if stat is None and interaction is not None:
            stat = interaction.stat_from_skill_loot_data
            if stat is None:
                logger.error('There is no stat tuned for this loot operation in {}', interaction)
                return (None, None, None)
        effectiveness = self._skill_loot_data_override.effectiveness
        if effectiveness is None and interaction is not None:
            effectiveness = interaction.skill_effectiveness_from_skill_loot_data
            if effectiveness is None:
                logger.error('Skill Effectiveness is not tuned for this loot operation in {}', interaction)
                return (None, None, None)
        level_range = self._skill_loot_data_override.level_range
        if level_range is None and interaction is not None:
            level_range = interaction.level_range_from_skill_loot_data
        return (stat, effectiveness, level_range)

    def get_stat(self, interaction):
        stat = self._skill_loot_data_override.stat
        if stat is None:
            stat = interaction.stat_from_skill_loot_data
        return stat

    def get_value(self, obj=None, interaction=None, sims=None):
        amount = 0
        multiplier = 1
        if obj is not None and interaction is not None:
            (stat_type, effectiveness, level_range) = self._get_skill_level_data(interaction)
            tracker = obj.get_tracker(stat_type)
            amount = self._get_change_amount(tracker, stat_type, effectiveness, level_range)
            if sims:
                targets = sims.copy()
            else:
                targets = interaction.get_participants(ParticipantType.Actor)
            if targets:
                multiplier = stat_type.get_skill_based_statistic_multiplier(targets, amount)
        return amount*multiplier

    def _apply_to_subject_and_target(self, subject, target, resolver):
        (stat_type, effectiveness, level_range) = self._get_skill_level_data(resolver.interaction)
        if stat_type is None:
            return
        tracker = subject.get_tracker(stat_type)
        amount = self._get_change_amount(tracker, stat_type, effectiveness, level_range)
        tracker.add_value(stat_type, amount, interaction=resolver.interaction)

    def _get_change_amount(self, tracker, stat_type, effectiveness, level_range):
        cur_level = tracker.get_user_value(stat_type)
        if level_range is not None:
            point_level = math.clamp(level_range.lower_bound, cur_level, level_range.upper_bound)
        else:
            point_level = cur_level
        amount = stat_type.get_skill_effectiveness_points_gain(effectiveness, point_level)
        return amount

class BaseStatisticByCategoryOp(BaseLootOperation):
    __qualname__ = 'BaseStatisticByCategoryOp'
    FACTORY_TUNABLES = {'statistic_category': TunableEnumEntry(statistics.statistic_categories.StatisticCategory, statistics.statistic_categories.StatisticCategory.INVALID, description='The category of commodity to remove.', needs_tuning=True)}

    def __init__(self, statistic_category, **kwargs):
        super().__init__(**kwargs)
        self._category = statistic_category

class RemoveStatisticByCategory(BaseStatisticByCategoryOp):
    __qualname__ = 'RemoveStatisticByCategory'

    def _apply_to_subject_and_target(self, subject, target, resolver):
        category = self._category
        for commodity in tuple(subject.commodity_tracker):
            while category in commodity.get_categories():
                subject.commodity_tracker.remove_statistic(type(commodity))

class TunableChangeAmountFactory(TunableFactory):
    __qualname__ = 'TunableChangeAmountFactory'

    @staticmethod
    def apply_change(sim, statistic, change_amout):
        stat_type = type(statistic)
        tracker = sim.get_tracker(type(statistic))
        tracker.add_value(stat_type, change_amout)

    FACTORY_TYPE = apply_change

    def __init__(self, **kwargs):
        super().__init__(change_amout=Tunable(description='\n                            Amount of change to be applied to statistics that match category.', tunable_type=float, default=0), **kwargs)

class TunablePercentChangeAmountFactory(TunableFactory):
    __qualname__ = 'TunablePercentChangeAmountFactory'

    @staticmethod
    def apply_change(subject, statistic, percent_change_amount):
        stat_type = type(statistic)
        tracker = subject.get_tracker(stat_type)
        current_value = tracker.get_value(stat_type)
        change_amount = current_value*percent_change_amount
        tracker.add_value(stat_type, change_amount)

    FACTORY_TYPE = apply_change

    def __init__(self, **kwargs):
        super().__init__(percent_change_amount=TunablePercent(description='\n                             Percent of current value of statistic should amount\n                             be changed.  If you want to decrease the amount by\n                             50% enter -50% into the tuning field.', default=-50, minimum=-100), **kwargs)

class ChangeStatisticByCategory(BaseStatisticByCategoryOp):
    __qualname__ = 'ChangeStatisticByCategory'
    FACTORY_TUNABLES = {'change': TunableVariant(stat_change=TunableChangeAmountFactory(), percent_change=TunablePercentChangeAmountFactory())}

    def __init__(self, change, **kwargs):
        super().__init__(**kwargs)
        self._change = change

    def _apply_to_subject_and_target(self, subject, target, resolver):
        category = self._category
        for commodity in tuple(subject.commodity_tracker):
            while category in commodity.get_categories():
                self._change(subject, commodity)

class ObjectStatisticChangeOp(StatisticChangeOp):
    __qualname__ = 'ObjectStatisticChangeOp'
    FACTORY_TUNABLES = {'locked_args': {'subject': None, 'advertise': False, 'tests': [], 'chance': None, 'exclusive_to_owning_si': False}}

    def apply_to_object(self, obj):
        tracker = obj.get_tracker(self.stat)
        self._apply(tracker)

    def remove_from_object(self, obj):
        tracker = obj.get_tracker(self.stat)
        self._remove(tracker)

    def get_fulfillment_rate(self, interaction):
        return 0

