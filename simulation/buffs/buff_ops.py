from autonomy.autonomy_modifier import AutonomyModifier
from buffs import BuffPolarity
from buffs.tunable import TunableBuffReference
from interactions import ParticipantType
from interactions.utils.loot_basic_op import BaseLootOperation, BaseTargetedLootOperation
from sims4.localization import TunableLocalizedString
from sims4.tuning.tunable import Tunable, TunableMapping, TunableReference, TunableList, OptionalTunable, TunableEnumEntry
from sims4.tuning.tunable_base import GroupNames
import services
import sims4.log
logger = sims4.log.Logger('Buffs')

class BuffOp(BaseLootOperation):
    __qualname__ = 'BuffOp'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value._buff.buff_type is None:
            logger.error('BuffOp: There is no buff set for loot op in {}:{}', instance_class, source, owner='msantander')

    FACTORY_TUNABLES = {'buff': TunableBuffReference(), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, buff, **kwargs):
        super().__init__(**kwargs)
        self._buff = buff

    def _apply_to_subject_and_target(self, subject, target, resolver):
        subject.add_buff_from_op(self._buff.buff_type, self._buff.buff_reason)

    def apply_to_interaction_statistic_change_element(self, interaction):
        if not self._buff.buff_type.commodity:
            return
        autonomy_modifier_handlers = None
        locked_stat = [self._buff.buff_type.commodity]
        for recipient in interaction.get_participants(self.subject):
            while recipient.add_buff_from_op(self._buff.buff_type, self._buff.buff_reason):
                if autonomy_modifier_handlers is None:
                    autonomy_modifier_handlers = {}
                autonomy_modifier_handlers[recipient] = AutonomyModifier(locked_stats=locked_stat)
        return autonomy_modifier_handlers

class BuffTransferOp(BaseTargetedLootOperation):
    __qualname__ = 'BuffTransferOp'
    FACTORY_TUNABLES = {'moods_only': Tunable(description='\n            Checking this box will limit buff transfer between Actor to Target Sim to only mood\n            associated buffs.', tunable_type=bool, default=True), 'buff_reason': OptionalTunable(description='\n            If set, specify a reason why the buff was added.\n            ', tunable=TunableLocalizedString(description='\n                The reason the buff was added. This will be displayed in the\n                buff tooltip.\n                ')), 'mood_types': OptionalTunable(TunableList(TunableReference(description='\n            If enabled, only transfer buffs with associated moods in this list.\n            ', manager=services.mood_manager()))), 'polarity': OptionalTunable(TunableEnumEntry(description='\n            If enabled, only transfer buffs that match the selected polarity.\n            ', tunable_type=BuffPolarity, default=BuffPolarity.NEUTRAL, needs_tuning=True, tuning_group=GroupNames.UI))}

    def __init__(self, moods_only, buff_reason, mood_types=None, polarity=None, **kwargs):
        super().__init__(**kwargs)
        self._moods_only = moods_only
        self._buff_reason = buff_reason
        self._mood_types = mood_types
        self._polarity = polarity

    def _apply_to_subject_and_target(self, subject, target, resolver):
        old_buff_types = list(subject.get_active_buff_types())
        if self._moods_only:
            for buff_entry in old_buff_types:
                while buff_entry.mood_type is not None:
                    subject.remove_buff_by_type(buff_entry)
        else:
            for buff_entry in old_buff_types:
                subject.remove_buff_by_type(buff_entry)
        for target_buff in target.get_active_buff_types():
            if self._moods_only and target_buff.mood_type is None:
                pass
            if self._mood_types is not None and target_buff.mood_type not in self._mood_types:
                pass
            if self._polarity is not None and self._polarity is not target_buff.polarity:
                pass
            buff_commodity = target_buff.commodity
            subject.add_buff(target_buff)
            while buff_commodity is not None:
                tracker = subject.get_tracker(buff_commodity)
                tracker.set_max(buff_commodity)
                subject.set_buff_reason(target_buff, self._buff_reason)

class DynamicBuffLootOp(BaseLootOperation):
    __qualname__ = 'DynamicBuffLootOp'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, value):
        if value.subject == ParticipantType.All:
            logger.error('Tuning error: DynamicBuffLootOp should not be subject All.  Use AllSims:{}, {}', instance_class, tunable_name)
        elif value.subject == ParticipantType.PickedItemId:
            logger.error('Tuning error: DynamicBuffLootOp should not be subject PickedItemId, use PickedSim:{}, {}', instance_class, tunable_name)

    FACTORY_TUNABLES = {'description': '\n        This loot will give a random buff based on the weight get tuned inside.\n        ', 'buffs': TunableMapping(description='\n            ', key_type=TunableReference(description='\n                Buff that will get this weight in the random.', manager=services.buff_manager()), value_type=Tunable(description='\n                The weight value.', tunable_type=float, default=0)), 'buff_reason': OptionalTunable(description='\n            If set, specify a reason why the buff was added.\n            ', tunable=TunableLocalizedString(description='\n                The reason the buff was added. This will be displayed in the\n                buff tooltip.\n                ')), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, buffs, buff_reason, **kwargs):
        super().__init__(**kwargs)
        self._buffs = buffs
        self._buff_reason = buff_reason
        self._random_buff = None

    def _get_random_buff(self):
        if self._random_buff is None:
            buff_pair_list = list(self._buffs.items())
            self._random_buff = sims4.random.pop_weighted(buff_pair_list, flipped=True)
        return self._random_buff

    def _apply_to_subject_and_target(self, subject, target, resolver):
        random_buff = self._get_random_buff()
        if random_buff is not None:
            if not subject.is_sim:
                logger.error('Tuning error: subject {} of DynamicBuffLootOp giving buff {} for reason {} is not a sim', self.subject, random_buff, self._buff_reason)
                return
            subject.add_buff_from_op(random_buff, self._buff_reason)

    def _on_apply_completed(self):
        random_buff = self._random_buff
        self._random_buff = None
        return random_buff

class BuffRemovalOp(BaseLootOperation):
    __qualname__ = 'BuffRemovalOp'
    FACTORY_TUNABLES = {'description': '\n        This loot will remove buffs from a Sim.\n        ', 'remove_all_visible_buffs': Tunable(description="\n        If checked, all visible buffs on the Sim, excluding those specified in\n        the 'buffs_to_ignore' list will be removed.  If unchecked, buff removal\n        will be handled by the 'buffs_to_remove' list.\n        ", tunable_type=bool, default=False), 'buffs_to_remove': TunableList(description="\n        If 'remove_all_buffs' is not checked, this is the list of buffs that\n        will be removed from the subject.  If 'remove_all_buffs' is checked,\n        this list will be ignored.\n        ", tunable=TunableReference(description='\n            Buff to be removed.\n            ', manager=services.buff_manager())), 'buffs_to_ignore': TunableList(description="\n        If 'remove_all_buffs' is checked, no buffs included in this list will\n        be removed.  If 'remove_all_buffs' is unchecked, this list will be\n        ignored.\n        ", tunable=TunableReference(description='\n            Buff to be removed.\n            ', manager=services.buff_manager()))}

    def __init__(self, remove_all_visible_buffs, buffs_to_remove, buffs_to_ignore, **kwargs):
        super().__init__(**kwargs)
        self._remove_all_visible_buffs = remove_all_visible_buffs
        self._buffs_to_remove = buffs_to_remove
        self._buffs_to_ignore = buffs_to_ignore

    def _apply_to_subject_and_target(self, subject, target, resolver):
        removal_list = []
        if self._remove_all_visible_buffs:
            removal_list.extend(subject.Buffs)
            for buff in removal_list:
                if type(buff) in self._buffs_to_ignore:
                    pass
                if not buff.visible:
                    pass
                if buff.commodity is not None:
                    tracker = subject.get_tracker(buff.commodity)
                    commodity_inst = tracker.get_statistic(buff.commodity)
                    if commodity_inst.core:
                        pass
                subject.Buffs.remove_buff_entry(buff)
        else:
            for buff_type in self._buffs_to_remove:
                subject.Buffs.remove_buff_by_type(buff_type)

