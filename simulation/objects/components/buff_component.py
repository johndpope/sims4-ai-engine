import collections
import operator
from buffs import Appropriateness
from date_and_time import create_time_span
from distributor.ops import GenericProtocolBufferOp
from distributor.system import Distributor
from event_testing import test_events
from interactions.base.picker_interaction import PickerSuperInteraction
from protocolbuffers import Commodities_pb2, Sims_pb2
from protocolbuffers.DistributorOps_pb2 import Operation
from sims4.callback_utils import CallableList
from sims4.tuning.tunable import TunableReference, Tunable, TunableRange, TunableList, TunableTuple
from sims4.utils import flexmethod
from ui.ui_dialog_picker import ObjectPickerRow
from uid import UniqueIdGenerator
import alarms
import caches
import distributor.shared_messages
import gsi_handlers
import objects.components.types
import services
import sims4.log
logger = sims4.log.Logger('BuffTracker')

class BuffComponent(objects.components.Component, component_name=objects.components.types.BUFF_COMPONENT):
    __qualname__ = 'BuffComponent'
    DEFAULT_MOOD = TunableReference(services.mood_manager(), description='The default initial mood.')
    UPDATE_INTENSITY_BUFFER = TunableRange(description="\n        A buffer that prevents a mood from becoming active unless its intensity\n        is greater than the current active mood's intensity plus this amount.\n        \n        For example, if this tunable is 1, and the Sim is in a Flirty mood with\n        intensity 2, then a different mood would become the active mood only if\n        its intensity is 3+.\n        \n        If the predominant mood has an intensity that is less than the active\n        mood's intensity, that mood will become the active mood.\n        ", tunable_type=int, default=1, minimum=0)
    EXCLUSIVE_SET = TunableList(description='\n        A list of buff groups to determine which buffs are exclusive from each\n        other within the same group.  A buff cannot exist in more than one exclusive group.\n        \n        The following rule of exclusivity for a group:\n        1. Higher weight will always be added and remove any lower weight buffs\n        2. Lower weight buff will not be added if a higher weight already exist in component\n        3. Same weight buff will always be added and remove any buff with same weight.\n        \n        Example: Group 1:\n                    Buff1 with weight of 5 \n                    Buff2 with weight of 1\n                    Buff3 with weight of 1\n                 Group 2:\n                    Buff4 with weight of 6\n        \n        If sim has Buff1, trying to add Buff2 or Buff3 will not be added.\n        If sim has Buff2, trying to add Buff3 will remove Buff2 and add Buff3\n        If sim has Buff2, trying to add Buff1 will remove Buff 2 and add Buff3\n        If sim has Buff4, trying to add Buff1, Buff2, or Buff3 will be added and Buff4 will stay \n                          on component \n        ', tunable=TunableList(tunable=TunableTuple(buff_type=TunableReference(description='\n                    Buff in exclusive group\n                    ', manager=services.get_instance_manager(sims4.resources.Types.BUFF)), weight=Tunable(description='\n                    weight to determine if this buff should be added and\n                    remove other buffs in the exclusive group or not added at all.\n                    \n                    Example: Buff1 with weight of 5 \n                             Buff2 with weight of 1\n                             Buff3 with weight of 1\n                    \n                    If sim has Buff1, trying to add Buff2 or Buff3 will not be added.\n                    If sim has Buff2, trying to add Buff3 will remove Buff2 and add Buff3\n                    if sim has Buff2, trying to add Buff1 will remove Buff 2 and add Buff3\n                    ', tunable_type=int, default=1))))

    def __init__(self, owner):
        super().__init__(owner)
        self._active_buffs = {}
        self._get_next_handle_id = UniqueIdGenerator()
        self._success_chance_modification = 0
        self._active_mood = self.DEFAULT_MOOD
        self._active_mood_intensity = 0
        self._active_mood_buff_handle = None
        self.on_mood_changed = CallableList()
        self.on_mood_changed.append(self._publish_mood_update)
        self.on_mood_changed.append(self._send_mood_changed_event)
        self.load_in_progress = False
        self.on_buff_added = CallableList()
        self.on_buff_removed = CallableList()
        self.buff_update_alarms = {}
        if self._active_mood is None:
            logger.error('No default mood tuned in buff_component.py')
        elif self._active_mood.buffs:
            initial_buff_ref = self._active_mood.buffs[0]
            if initial_buff_ref and initial_buff_ref.buff_type:
                self._active_mood_buff_handle = self.add_buff(initial_buff_ref.buff_type)

    def __iter__(self):
        return self._active_buffs.values().__iter__()

    def __len__(self):
        return len(self._active_buffs)

    def on_sim_ready_to_simulate(self):
        for buff in self:
            buff.on_sim_ready_to_simulate()
        self._publish_mood_update()

    def on_sim_removed(self, *args, **kwargs):
        for buff in self:
            buff.on_sim_removed(*args, **kwargs)

    def clean_up(self):
        for (buff_type, buff_entry) in tuple(self._active_buffs.items()):
            self.remove_auto_update(buff_type)
            buff_entry.clean_up()
        self._active_buffs.clear()
        self.on_mood_changed.clear()
        self.on_buff_added.clear()
        self.on_buff_removed.clear()

    @objects.components.componentmethod
    def add_buff_from_op(self, buff_type, buff_reason=None):
        (can_add, _) = self._can_add_buff_type(buff_type)
        if not can_add:
            return False
        buff_commodity = buff_type.commodity
        if buff_commodity is not None:
            if not buff_type.refresh_on_add and self.has_buff(buff_type):
                return False
            tracker = self.owner.get_tracker(buff_commodity)
            if buff_commodity.convergence_value == buff_commodity.max_value:
                tracker.set_min(buff_commodity)
            else:
                tracker.set_max(buff_commodity)
            self.set_buff_reason(buff_type, buff_reason, use_replacement=True)
        else:
            self.add_buff(buff_type, buff_reason=buff_reason)
        return True

    @objects.components.componentmethod
    def add_buff(self, buff_type, buff_reason=None, update_mood=True, commodity_guid=None, replacing_buff=None, timeout_string=None, transition_into_buff_id=0, change_rate=None, immediate=False):
        replacement_buff_type = self._get_replacement_buff_type(buff_type)
        if replacement_buff_type is not None:
            return self.owner.add_buff(replacement_buff_type, buff_reason=buff_reason, update_mood=update_mood, commodity_guid=commodity_guid, replacing_buff=buff_type, timeout_string=timeout_string, transition_into_buff_id=transition_into_buff_id, change_rate=change_rate, immediate=immediate)
        (can_add, conflicting_buff_type) = self._can_add_buff_type(buff_type)
        if not can_add:
            return
        buff = self._active_buffs.get(buff_type)
        if buff is None:
            buff = buff_type(self.owner, commodity_guid, replacing_buff, transition_into_buff_id)
            self._active_buffs[buff_type] = buff
            buff.on_add(self.load_in_progress)
            self._update_chance_modifier()
            if update_mood:
                self._update_current_mood()
            if self.owner.household is not None:
                services.get_event_manager().process_event(test_events.TestEvent.BuffBeganEvent, sim_info=self.owner, sim_id=self.owner.sim_id, buff=buff_type)
                self.register_auto_update(self.owner, buff_type)
            self.on_buff_added(buff_type)
        handle_id = self._get_next_handle_id()
        buff.add_handle(handle_id, buff_reason=buff_reason)
        self.send_buff_update_msg(buff, True, change_rate=change_rate, immediate=immediate)
        if conflicting_buff_type is not None:
            self.remove_buff_by_type(conflicting_buff_type)
        return handle_id

    def _get_replacement_buff_type(self, buff_type):
        if buff_type.trait_replacement_buffs is not None:
            trait_tracker = self.owner.trait_tracker
            for (trait, replacement_buff_type) in buff_type.trait_replacement_buffs.items():
                while trait_tracker.has_trait(trait):
                    return replacement_buff_type

    def register_auto_update(self, sim_info_in, buff_type_in):
        if buff_type_in in self.buff_update_alarms:
            self.remove_auto_update(buff_type_in)
        if sim_info_in.is_selectable and buff_type_in.visible:
            self.buff_update_alarms[buff_type_in] = alarms.add_alarm(self, create_time_span(minutes=15), lambda _, sim_info=sim_info_in, buff_type=buff_type_in: services.get_event_manager().process_event(test_events.TestEvent.BuffUpdateEvent, sim_info=sim_info, sim_id=sim_info.sim_id, buff=buff_type), True)

    def remove_auto_update(self, buff_type):
        if buff_type in self.buff_update_alarms:
            alarms.cancel_alarm(self.buff_update_alarms[buff_type])
            del self.buff_update_alarms[buff_type]

    @objects.components.componentmethod
    def remove_buff(self, handle_id, update_mood=True, immediate=False, on_destroy=False):
        for (buff_type, buff_entry) in self._active_buffs.items():
            while handle_id in buff_entry.handle_ids:
                should_remove = buff_entry.remove_handle(handle_id)
                if should_remove:
                    del self._active_buffs[buff_type]
                    buff_entry.on_remove(not self.load_in_progress and not on_destroy)
                    if not on_destroy:
                        if update_mood:
                            self._update_current_mood()
                        self._update_chance_modifier()
                        self.send_buff_update_msg(buff_entry, False, immediate=immediate)
                        services.get_event_manager().process_event(test_events.TestEvent.BuffEndedEvent, sim_info=self.owner, sim_id=self.owner.sim_id, buff=buff_type)
                    if buff_type in self.buff_update_alarms:
                        self.remove_auto_update(buff_type)
                    self.on_buff_removed(buff_type)
                break

    @objects.components.componentmethod
    def get_buff_type(self, handle_id):
        for (buff_type, buff_entry) in self._active_buffs.items():
            while handle_id in buff_entry.handle_ids:
                return buff_type

    @objects.components.componentmethod
    def has_buff(self, buff_type):
        return buff_type in self._active_buffs

    @objects.components.componentmethod
    def get_active_buff_types(self):
        return self._active_buffs.keys()

    @objects.components.componentmethod
    def get_buff_reason(self, handle_id):
        for buff_entry in self._active_buffs.values():
            while handle_id in buff_entry.handle_ids:
                return buff_entry.buff_reason

    @objects.components.componentmethod
    def debug_add_buff_by_type(self, buff_type):
        (can_add, conflicting_buff_type) = self._can_add_buff_type(buff_type)
        if not can_add:
            return False
        if buff_type.commodity is not None:
            tracker = self.owner.get_tracker(buff_type.commodity)
            state_index = buff_type.commodity.get_state_index_matches_buff_type(buff_type)
            if state_index is not None:
                index = state_index + 1
                if index < len(buff_type.commodity.commodity_states):
                    commodity_to_value = buff_type.commodity.commodity_states[index].value - 1
                else:
                    commodity_to_value = buff_type.commodity.max_value
                tracker.set_value(buff_type.commodity, commodity_to_value)
            else:
                logger.error('commodity ({}) has no states with buff ({}), Buff will not be added.', buff_type.commodity, buff_type)
                return False
        else:
            self.add_buff(buff_type)
        if conflicting_buff_type is not None:
            self.remove_buff_by_type(conflicting_buff_type)
        return True

    @objects.components.componentmethod
    def remove_buff_by_type(self, buff_type, on_destroy=False):
        buff_entry = self._active_buffs.get(buff_type)
        self.remove_buff_entry(buff_entry, on_destroy=on_destroy)

    @objects.components.componentmethod
    def remove_buff_entry(self, buff_entry, on_destroy=False):
        if buff_entry is not None:
            if buff_entry.commodity is not None:
                tracker = self.owner.get_tracker(buff_entry.commodity)
                commodity_inst = tracker.get_statistic(buff_entry.commodity)
                if commodity_inst is not None and commodity_inst.core:
                    if not on_destroy:
                        logger.callstack('Attempting to explicitly remove the buff {}, which is given by a core commodity.                                           This would result in the removal of a core commodity and will be ignored.', buff_entry, owner='tastle', level=sims4.log.LEVEL_ERROR)
                    return
                tracker.remove_statistic(buff_entry.commodity, on_destroy=on_destroy)
            elif buff_entry.buff_type in self._active_buffs:
                buff_entry.on_remove(on_destroy)
                del self._active_buffs[buff_entry.buff_type]
                if not on_destroy:
                    self._update_chance_modifier()
                    self._update_current_mood()
                    self.send_buff_update_msg(buff_entry, False)
                    services.get_event_manager().process_event(test_events.TestEvent.BuffEndedEvent, sim_info=self.owner, buff=type(buff_entry), sim_id=self.owner.id)

    @objects.components.componentmethod
    def set_buff_reason(self, buff_type, buff_reason, use_replacement=False):
        if use_replacement:
            replacement_buff_type = self._get_replacement_buff_type(buff_type)
            if replacement_buff_type is not None:
                buff_type = replacement_buff_type
        buff_entry = self._active_buffs.get(buff_type)
        if buff_entry is not None and buff_reason is not None:
            buff_entry.buff_reason = buff_reason
            self.send_buff_update_msg(buff_entry, True)

    @objects.components.componentmethod
    def buff_commodity_changed(self, handle_id, change_rate=None):
        for (_, buff_entry) in self._active_buffs.items():
            while handle_id in buff_entry.handle_ids:
                if buff_entry.show_timeout:
                    self.send_buff_update_msg(buff_entry, True, change_rate=change_rate)
                break

    @objects.components.componentmethod
    def get_success_chance_modifier(self):
        return self._success_chance_modification

    @objects.components.componentmethod
    def get_actor_scoring_modifier(self, affordance):
        total = 0
        for buff_entry in self._active_buffs.values():
            total += buff_entry.effect_modification.get_affordance_scoring_modifier(affordance)
        return total

    @objects.components.componentmethod
    def get_actor_success_modifier(self, affordance):
        total = 0
        for buff_entry in self._active_buffs.values():
            total += buff_entry.effect_modification.get_affordance_success_modifier(affordance)
        return total

    @objects.components.componentmethod
    def get_mood(self):
        return self._active_mood

    @objects.components.componentmethod
    def get_mood_animation_param_name(self):
        param_name = self._active_mood.asm_param_name
        if param_name is not None:
            return param_name
        (mood, _, _) = self._get_largest_mood(predicate=lambda mood: return True if mood.asm_param_name else False)
        return mood.asm_param_name

    @objects.components.componentmethod
    def get_mood_intensity(self):
        return self._active_mood_intensity

    @objects.components.componentmethod
    def get_effective_skill_level(self, skill):
        if skill.stat_type == skill:
            skill = self.owner.get_stat_instance(skill)
            if skill is None:
                return 0
        modifier = 0
        for buff_entry in self._active_buffs.values():
            modifier += buff_entry.effect_modification.get_effective_skill_modifier(skill)
        return skill.get_user_value() + modifier

    @objects.components.componentmethod
    def effective_skill_modified_buff_gen(self, skill):
        if skill.stat_type == skill:
            skill = self.owner.get_stat_instance(skill)
        for buff_entry in self._active_buffs.values():
            modifier = buff_entry.effect_modification.get_effective_skill_modifier(skill)
            while modifier != 0:
                yield (buff_entry, modifier)

    @objects.components.componentmethod
    def is_appropriate(self, tags):
        final_appropriateness = Appropriateness.DONT_CARE
        for buff in self._active_buffs:
            appropriateness = buff.get_appropriateness(tags)
            while appropriateness > final_appropriateness:
                final_appropriateness = appropriateness
        if final_appropriateness == Appropriateness.NOT_ALLOWED:
            return False
        return True

    def get_additional_create_ops_gen(self):
        yield GenericProtocolBufferOp(Operation.SIM_MOOD_UPDATE, self._create_mood_update_msg())
        for buff in self:
            while buff.visible:
                yield GenericProtocolBufferOp(Operation.SIM_BUFF_UPDATE, self._create_buff_update_msg(buff, True))

    def _publish_mood_update(self):
        if self.owner.valid_for_distribution and self.owner.visible_to_client == True:
            Distributor.instance().add_op(self.owner, GenericProtocolBufferOp(Operation.SIM_MOOD_UPDATE, self._create_mood_update_msg()))

    def _send_mood_changed_event(self):
        if not self.owner.is_npc:
            self.owner.whim_tracker.refresh_emotion_whim()
        services.get_event_manager().process_event(test_events.TestEvent.MoodChange, sim_info=self.owner)

    def _create_mood_update_msg(self):
        mood_msg = Commodities_pb2.MoodUpdate()
        mood_msg.sim_id = self.owner.id
        mood_msg.mood_key = self._active_mood.guid64
        mood_msg.mood_intensity = self._active_mood_intensity
        return mood_msg

    def _create_buff_update_msg(self, buff, equipped, change_rate=None):
        buff_msg = Sims_pb2.BuffUpdate()
        buff_msg.buff_id = buff.guid64
        buff_msg.sim_id = self.owner.id
        buff_msg.equipped = equipped
        if buff.buff_reason is not None:
            buff_msg.reason = buff.buff_reason
        if equipped and buff.show_timeout:
            (timeout, rate_multiplier) = buff.get_timeout_time()
            buff_msg.timeout = timeout
            buff_msg.rate_multiplier = rate_multiplier
            if change_rate is not None:
                if change_rate == 0:
                    progress_arrow = Sims_pb2.BUFF_PROGRESS_NONE
                elif change_rate > 0:
                    progress_arrow = Sims_pb2.BUFF_PROGRESS_UP if not buff.flip_arrow_for_progress_update else Sims_pb2.BUFF_PROGRESS_DOWN
                else:
                    progress_arrow = Sims_pb2.BUFF_PROGRESS_DOWN if not buff.flip_arrow_for_progress_update else Sims_pb2.BUFF_PROGRESS_UP
                buff_msg.buff_progress = progress_arrow
        buff_msg.is_mood_buff = buff.is_mood_buff
        buff_msg.commodity_guid = buff.commodity_guid or 0
        if buff.mood_override is not None:
            buff_msg.mood_type_override = buff.mood_override.guid64
        buff_msg.transition_into_buff_id = buff.transition_into_buff_id
        return buff_msg

    def send_buff_update_msg(self, buff, equipped, change_rate=None, immediate=False):
        if not buff.visible:
            return
        if self.owner.valid_for_distribution and self.owner.is_sim and self.owner.is_selectable:
            buff_msg = self._create_buff_update_msg(buff, equipped, change_rate=change_rate)
            if gsi_handlers.buff_handlers.sim_buff_log_archiver.enabled:
                gsi_handlers.buff_handlers.archive_buff_message(buff_msg, equipped, change_rate)
            Distributor.instance().add_op(self.owner, GenericProtocolBufferOp(Operation.SIM_BUFF_UPDATE, buff_msg))

    def _can_add_buff_type(self, buff_type):
        if not buff_type.can_add(self.owner):
            return (False, None)
        mood = buff_type.mood_type
        if mood is not None and mood.excluding_traits is not None and self.owner.trait_tracker.has_any_trait(mood.excluding_traits):
            return (False, None)
        if buff_type.exclusive_index is None:
            return (True, None)
        for conflicting_buff_type in self._active_buffs:
            while conflicting_buff_type.exclusive_index == buff_type.exclusive_index:
                if buff_type.exclusive_weight < conflicting_buff_type.exclusive_weight:
                    return (False, None)
                return (True, conflicting_buff_type)
        return (True, None)

    def _update_chance_modifier(self):
        positive_success_buff_delta = 0
        negative_success_buff_delta = 1
        for buff_entry in self._active_buffs.values():
            if buff_entry.success_modifier > 0:
                positive_success_buff_delta += buff_entry.get_success_modifier
            else:
                negative_success_buff_delta *= 1 + buff_entry.get_success_modifier
        self._success_chance_modification = positive_success_buff_delta - (1 - negative_success_buff_delta)

    def _get_largest_mood(self, predicate=None, buffs_to_ignore=()):
        weights = {}
        polarity_to_changeable_buffs = collections.defaultdict(list)
        polarity_to_largest_mood_and_weight = {}
        for buff_entry in self._active_buffs.values():
            current_mood = buff_entry.mood_type
            current_weight = buff_entry.mood_weight
            while not current_mood is None:
                if current_weight == 0:
                    pass
                if not (predicate is not None and predicate(current_mood)):
                    pass
                if buff_entry in buffs_to_ignore:
                    pass
                current_polarity = current_mood.buff_polarity
                if buff_entry.is_changeable:
                    polarity_to_changeable_buffs[current_polarity].append(buff_entry)
                total_current_weight = weights.get(current_mood, 0)
                total_current_weight += current_weight
                weights[current_mood] = total_current_weight
                (largest_mood, largest_weight) = polarity_to_largest_mood_and_weight.get(current_polarity, (None, None))
                if largest_mood is None:
                    polarity_to_largest_mood_and_weight[current_polarity] = (current_mood, total_current_weight)
                else:
                    while total_current_weight > largest_weight:
                        polarity_to_largest_mood_and_weight[current_polarity] = (current_mood, total_current_weight)
        all_changeable_buffs = []
        for (buff_polarity, changeable_buffs) in polarity_to_changeable_buffs.items():
            (largest_mood, largest_weight) = polarity_to_largest_mood_and_weight.get(buff_polarity, (None, None))
            if largest_mood is not None:
                for buff_entry in changeable_buffs:
                    if buff_entry.mood_override is not largest_mood:
                        all_changeable_buffs.append((buff_entry, largest_mood))
                    largest_weight += buff_entry.mood_weight
                polarity_to_largest_mood_and_weight[buff_polarity] = (largest_mood, largest_weight)
            else:
                weights = {}
                largest_weight = 0
                for buff_entry in changeable_buffs:
                    if buff_entry.mood_override is not None:
                        all_changeable_buffs.append((buff_entry, None))
                    current_mood = buff_entry.mood_type
                    current_weight = buff_entry.mood_weight
                    total_current_weight = weights.get(current_mood, 0)
                    total_current_weight += current_weight
                    weights[current_mood] = total_current_weight
                    while total_current_weight > largest_weight:
                        largest_weight = total_current_weight
                        largest_mood = current_mood
                while largest_mood is not None and largest_weight != 0:
                    polarity_to_largest_mood_and_weight[buff_polarity] = (largest_mood, largest_weight)
        largest_weight = 0
        largest_mood = self.DEFAULT_MOOD
        active_mood = self._active_mood
        if polarity_to_largest_mood_and_weight:
            (mood, weight) = max(polarity_to_largest_mood_and_weight.values(), key=operator.itemgetter(1))
            if weight > largest_weight or weight == largest_weight and mood is active_mood:
                largest_weight = weight
                largest_mood = mood
        return (largest_mood, largest_weight, all_changeable_buffs)

    def _update_current_mood(self):
        (largest_mood, largest_weight, changeable_buffs) = self._get_largest_mood()
        if largest_mood is not None:
            intensity = self._get_intensity_from_mood(largest_mood, largest_weight)
            if self._should_update_mood(largest_mood, intensity, changeable_buffs):
                if self._active_mood_buff_handle is not None:
                    active_mood_buff_handle = self._active_mood_buff_handle
                    self.remove_buff(active_mood_buff_handle, update_mood=False)
                    if active_mood_buff_handle == self._active_mood_buff_handle:
                        self._active_mood_buff_handle = None
                    else:
                        return
                self._active_mood = largest_mood
                self._active_mood_intensity = intensity
                if len(largest_mood.buffs) >= intensity:
                    tuned_buff = largest_mood.buffs[intensity]
                    if tuned_buff is not None and tuned_buff.buff_type is not None:
                        self._active_mood_buff_handle = self.add_buff(tuned_buff.buff_type, update_mood=False)
                if gsi_handlers.buff_handlers.sim_mood_log_archiver.enabled and self.owner.valid_for_distribution and self.owner.visible_to_client == True:
                    gsi_handlers.buff_handlers.archive_mood_message(self.owner.id, self._active_mood, self._active_mood_intensity, self._active_buffs, changeable_buffs)
                caches.clear_all_caches()
                self.on_mood_changed()
        for (changeable_buff, mood_override) in changeable_buffs:
            changeable_buff.mood_override = mood_override
            self.send_buff_update_msg(changeable_buff, True)

    def _get_intensity_from_mood(self, mood, weight):
        intensity = 0
        for threshold in mood.intensity_thresholds:
            if weight >= threshold:
                intensity += 1
            else:
                break
        return intensity

    def _should_update_mood(self, mood, intensity, changeable_buffs):
        active_mood = self._active_mood
        active_mood_intensity = self._active_mood_intensity
        if mood is active_mood:
            return intensity != active_mood_intensity
        total_weight = sum(buff_entry.mood_weight for buff_entry in self._active_buffs.values() if buff_entry.mood_type is active_mood)
        active_mood_intensity = self._get_intensity_from_mood(active_mood, total_weight)
        if changeable_buffs and not self._active_mood.is_changeable:
            buffs_to_ignore = [changeable_buff for (changeable_buff, _) in changeable_buffs]
            (largest_mood, largest_weight, _) = self._get_largest_mood(buffs_to_ignore=buffs_to_ignore)
            new_intensity = self._get_intensity_from_mood(largest_mood, largest_weight)
            if self._should_update_mood(largest_mood, new_intensity, None):
                active_mood = largest_mood
                active_mood_intensity = new_intensity
        if active_mood.is_changeable and mood.buff_polarity == active_mood.buff_polarity:
            return True
        if not intensity or intensity < active_mood_intensity:
            return True
        if intensity >= active_mood_intensity + self.UPDATE_INTENSITY_BUFFER:
            return True
        if mood is self.DEFAULT_MOOD or active_mood is self.DEFAULT_MOOD:
            return True
        return False

def _update_buffs_with_exclusive_data(buff_manager):
    for (index, exclusive_set) in enumerate(BuffComponent.EXCLUSIVE_SET):
        for buff_type_data in exclusive_set:
            buff_type = buff_type_data.buff_type
            buff_type.exclusive_index = index
            buff_type.exclusive_weight = buff_type_data.weight

if not sims4.reload.currently_reloading:
    services.get_instance_manager(sims4.resources.Types.BUFF).add_on_load_complete(_update_buffs_with_exclusive_data)

class BuffPickerSuperInteraction(PickerSuperInteraction):
    __qualname__ = 'BuffPickerSuperInteraction'
    INSTANCE_TUNABLES = {'is_add': Tunable(description='\n                If this interaction is trying to add a buff to the target sim\n                or to remove a buff from the target sim.', tunable_type=bool, default=True)}

    def _run_interaction_gen(self, timeline):
        self._show_picker_dialog(self.sim, target_sim=self.sim)
        return True

    @classmethod
    def _buff_type_selection_gen(cls, target):
        buff_manager = services.get_instance_manager(sims4.resources.Types.BUFF)
        if cls.is_add:
            for buff_type in buff_manager.types.values():
                while not target.has_buff(buff_type):
                    yield buff_type
        else:
            for buff_type in target.get_active_buff_types():
                yield buff_type

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        for buff_type in cls._buff_type_selection_gen(target):
            is_enable = True
            if cls.is_add:
                is_enable = buff_type.can_add(target.sim_info)
            row = ObjectPickerRow(is_enable=is_enable, name=buff_type.buff_name, icon=buff_type.icon, row_description=buff_type.buff_description, tag=buff_type)
            yield row

    def on_choice_selected(self, choice_tag, **kwargs):
        buff_type = choice_tag
        if buff_type is not None:
            if self.is_add:
                self.target.debug_add_buff_by_type(buff_type)
            else:
                self.target.remove_buff_by_type(buff_type)

