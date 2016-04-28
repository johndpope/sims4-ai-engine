import itertools
import weakref
from interactions import interaction_messages, ParticipantType
from interactions.si_state import SIState
from protocolbuffers import Sims_pb2
import enum
import interactions.base.interaction
import interactions.context
import sims4.log
import sims4.resources
import sims4.tuning.tunable
import tag
import telemetry_helper
logger = sims4.log.Logger('UI_MANAGER', default_owner='msantander')
TELEMETRY_GROUP_INTERACTION = 'INTR'
TELEMETRY_HOOK_INTERACTION_QUEUE = 'QUEU'
TELEMETRY_HOOK_INTERACTION_CANCEL = 'CANC'
TELEMETRY_HOOK_OPTIONAL_ACTION = 'QUIC'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_INTERACTION)

class UIManager:
    __qualname__ = 'UIManager'

    class QueueType(enum.Int, export=False):
        __qualname__ = 'UIManager.QueueType'
        Queue = 0
        Super = 1
        Continuation = 2

    def __init__(self, sim):
        self._sim_ref = sim.ref()
        self._queued_interactions = []
        self._super_interactions = []
        self._group_interactions = {}
        self._last_running_interaction_id = 0
        self._continuation_interactions = []
        self._si_skill_mapping = {}
        self._routing_info = InteractionInfo.create_routing_info()

    @property
    def _sim(self):
        return self._sim_ref()

    @property
    def _running_interactions(self):
        for int_info in itertools.chain(self._super_interactions, *self._group_interactions.values()):
            yield int_info

    def _add_running_interaction(self, int_info):
        if int_info.visual_group_tag is None:
            self._super_interactions.append(int_info)
            return
        running_infos = self._group_interactions.get(int_info.visual_group_tag, [])
        running_infos.append(int_info)
        running_infos.sort(key=lambda x: x.visual_group_priority)
        self._group_interactions[int_info.visual_group_tag] = list(running_infos)
        return running_infos

    def _remove_running_interactions(self, int_info):
        if int_info.visual_group_tag is None:
            self._super_interactions.remove(int_info)
            return
        running_infos = self._group_interactions.get(int_info.visual_group_tag)
        running_infos.remove(int_info)
        if running_infos:
            self._group_interactions[int_info.visual_group_tag] = list(running_infos)
            return running_infos
        del self._group_interactions[int_info.visual_group_tag]

    def get_grouped_interaction_gen(self, interaction_id):
        (int_info, queue_type) = self._find_interaction(interaction_id)
        if queue_type == self.QueueType.Super:
            running_infos = self._group_interactions.get(int_info.visual_group_tag)
            if running_infos is not None:
                while True:
                    for running_info in running_infos:
                        yield running_info

    def _get_visible_grouped_interaction_id(self, interaction_id):
        (int_info, _) = self._find_interaction(interaction_id)
        if int_info is None:
            return
        if int_info.visual_group_tag is None:
            return
        running_infos = self._group_interactions.get(int_info.visual_group_tag)
        if running_infos:
            return running_infos[-1].interaction_id

    def _get_super_id_for_mixer(self, super_id):
        (int_info, queue_type) = self._find_interaction(super_id)
        if int_info is not None and queue_type == self.QueueType.Queue:
            return super_id
        return self._get_visible_grouped_interaction_id(super_id)

    def get_interactions_gen(self):
        return itertools.chain(self._queued_interactions, self._running_interactions)

    def add_queued_interaction(self, interaction, interaction_id_to_insert_after=None, notify_client=True):
        if interaction.visual_continuation_id is not None and interaction.is_super:
            (interaction_info, _) = self._find_interaction(interaction.visual_continuation_id)
            if interaction_info is not None and interaction_info.ui_state != Sims_pb2.IQ_QUEUED:
                self.add_continuation_interaction(interaction)
                return
        logger.debug('SimId:{}, Interaction added to queue:{}', self._sim.id, interaction)
        int_info = self._add_interaction(self._queued_interactions, interaction, interaction_id_to_insert_after, self.QueueType.Queue)
        if interaction.visible and notify_client:
            interaction_messages.send_interactions_add_msg(self._sim, (int_info,), self._should_msg_be_immediate(self.QueueType.Queue))
            int_info.client_notified = True

    def add_continuation_interaction(self, interaction):
        if interaction.visible:
            logger.debug('SimId:{}, Interaction added to continuation:{}', self._sim.id, interaction)
            int_info = self._add_interaction(self._continuation_interactions, interaction, None, self.QueueType.Continuation)
            int_info.source_id = interaction.visual_continuation_id

    def add_running_mixer_interaction(self, si_id, mixer, icon_info, name):
        int_info = self._add_interaction(self._super_interactions, mixer, None, self.QueueType.Super)
        super_int_info_id = self._get_visible_grouped_interaction_id(si_id)
        int_info.super_id = super_int_info_id or si_id
        int_info.set_icon_info(icon_info)
        int_info.display_name = name
        int_info.ui_state = Sims_pb2.IQ_RUNNING
        interaction_messages.send_interactions_add_msg(self._sim, (int_info,), self._should_msg_be_immediate(self.QueueType.Super))

    def running_transition(self, interaction):
        if not interaction.visible:
            return
        interaction_id = interaction.id
        for int_info in self._continuation_interactions:
            if int_info.interaction_id != interaction_id:
                pass
            int_info.ui_state = Sims_pb2.IQ_TRANSITIONING
        int_info = None
        running_info_for_group = None
        previous_visible_group_info_id = None
        for (i, int_info) in enumerate(self._queued_interactions):
            if int_info.interaction_id != interaction_id:
                pass
            int_info.ui_state = Sims_pb2.IQ_TRANSITIONING
            next_index = i + 1
            if next_index < len(self._queued_interactions):
                self._queued_interactions[next_index].insert_after_id = 0
            previous_visible_group_info_id = self._get_visible_grouped_interaction_id(int_info.interaction_id)
            self._queued_interactions.remove(int_info)
            running_info_for_group = self._add_running_interaction(int_info)
            break
        logger.debug('SimId:{}, Interaction being marked as transitioning is not in queued interaction:{}', self._sim.id, interaction)
        return
        logger.debug('SimId:{}, Interaction being marked as transitioning:{}', self._sim.id, interaction)
        should_be_immediate = self._should_msg_be_immediate(self.QueueType.Super)
        if running_info_for_group is None or previous_visible_group_info_id is None:
            self._add_routing_interaction_info(int_info)
            if int_info.client_notified:
                interaction_messages.send_interactions_update_msg(self._sim, (int_info,), should_be_immediate)
            else:
                interaction_messages.send_interactions_add_msg(self._sim, (int_info,), should_be_immediate)
                int_info.client_notified = True
        else:
            visible_int_info = running_info_for_group.pop()
            if int_info.client_notified:
                if visible_int_info is int_info:
                    self._update_mixers(previous_visible_group_info_id, visible_int_info.interaction_id)
                interaction_messages.send_interactions_remove_msg(self._sim, (int_info,), should_be_immediate)
            if visible_int_info is int_info:
                interaction_messages.send_interaction_replace_message(self._sim, previous_visible_group_info_id, int_info, should_be_immediate)
                int_info.client_notified = True

    def transferred_to_si_state(self, interaction):
        self._update_skillbar_info(interaction)
        if not interaction.visible:
            return
        int_info = None
        if interaction.is_super:
            for cur_info in self._running_interactions:
                while cur_info.interaction_id == interaction.id:
                    int_info = cur_info
                    break
        if int_info is None:
            for cur_info in self._queued_interactions:
                if cur_info.interaction_id != interaction.id:
                    pass
                if interaction.is_super:
                    self.running_transition(interaction)
                else:
                    self._queued_interactions.remove(cur_info)
                    if cur_info.super_id != 0:
                        cur_info.super_id = self._get_visible_grouped_interaction_id(cur_info.super_id) or cur_info.super_id
                    self._add_running_interaction(cur_info)
                int_info = cur_info
                break
        if int_info is None:
            logger.debug('SimId:{}, Interaction Transfer To SI State could not find interaction to update:{}', self._sim.id, interaction)
            return
        logger.debug('SimId:{}, Interaction Transfer To SI State being marked as running:{}', self._sim.id, interaction)
        int_info.ui_state = Sims_pb2.IQ_RUNNING
        (int_info.ui_visual_type, visual_type_data) = interaction.get_interaction_queue_visual_type()
        if visual_type_data.icon is not None:
            int_info.set_icon_info((visual_type_data.icon, None))
        if visual_type_data.tooltip_text is not None:
            int_info.display_name = interaction.create_localized_string(visual_type_data.tooltip_text)
        force_remove = int_info.ui_visual_type == Sims_pb2.Interaction.POSTURE
        self._remove_routing_interaction_info(int_info, force_remove=force_remove)
        if int_info.visual_group_tag is None or self._get_visible_grouped_interaction_id(int_info.interaction_id) == int_info.interaction_id:
            if int_info.client_notified:
                interaction_messages.send_interactions_update_msg(self._sim, (int_info,), False)
            else:
                interaction_messages.send_interactions_add_msg(self._sim, (int_info,), False)
                int_info.client_notified = True
        self._update_interaction_for_potential_cancel()

    def remove_queued_interaction(self, interaction):
        if not interaction.visible:
            return
        for (index, cur_info) in enumerate(self._queued_interactions):
            while interaction.id == cur_info.interaction_id:
                logger.debug('SimId:{}, Interaction Remove(from queue) is being removed from queued list:{}', self._sim.id, interaction)
                if interaction.user_canceled:
                    with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_INTERACTION_CANCEL, sim=self._sim) as hook:
                        hook.write_int('idit', interaction.id)
                        hook.write_int('queu', index)
                int_info = self._queued_interactions.pop(index)
                interaction_messages.send_interactions_remove_msg(self._sim, (int_info,), int_info.ui_state == Sims_pb2.IQ_QUEUED)
                return
        for int_info in self._running_interactions:
            while interaction.id == int_info.interaction_id and int_info.ui_state == Sims_pb2.IQ_TRANSITIONING:
                previous_visible_group_info_id = self._get_visible_grouped_interaction_id(int_info.interaction_id)
                group_interactions = self._remove_running_interactions(int_info)
                self._remove_routing_interaction_info(int_info)
                if group_interactions:
                    new_visible_interaction_info = group_interactions.pop()
                    if previous_visible_group_info_id == new_visible_interaction_info.interaction_id:
                        return
                    if new_visible_interaction_info.ui_state == Sims_pb2.IQ_RUNNING:
                        interaction_messages.send_interaction_replace_message(self._sim, int_info.interaction_id, new_visible_interaction_info, self._should_msg_be_immediate(self.QueueType.Super))
                    else:
                        interaction_messages.send_interactions_add_msg(self._sim, (new_visible_interaction_info,), self._should_msg_be_immediate(self.QueueType.Super))
                else:
                    interaction_messages.send_interactions_remove_msg(self._sim, (int_info,), immediate=interaction.collapsible)
                return
        for (index, cur_info) in enumerate(self._continuation_interactions):
            while interaction.id == cur_info.interaction_id:
                logger.debug('SimId:{}, Interaction Remove(from queue) is being removed from continuation list:{}', self._sim.id, interaction)
                self._continuation_interactions.pop(index)
                return
        logger.debug('Interaction Remove(from Queue) requested on an interaction not in the ui_manager:{}', interaction)

    def remove_from_si_state(self, interaction):
        self._update_skillbar_info(interaction, from_remove=True)
        interaction_id = interaction.id
        if not interaction.visible:
            return
        logger.debug('SimId:{}, Interaction Remove From SI State attempting to remove:{}', self._sim.id, interaction)
        for cur_info in self._running_interactions:
            if interaction_id != cur_info.interaction_id:
                pass
            int_info = cur_info
            group_interactions = self._remove_running_interactions(int_info)
            continuation_info = self._find_continuation(int_info.interaction_id)
            if continuation_info:
                logger.debug('=== Continuation Replace In Remove: ({0} => {1})', int_info.interaction_id, continuation_info.interaction_id)
                if continuation_info.client_notified:
                    logger.error('Trying to replace an interaction that client is already notified. {}, {}', int_info, continuation_info)
                else:
                    if continuation_info.ui_state == Sims_pb2.IQ_TRANSITIONING:
                        self._add_running_interaction(int_info)
                    else:
                        self._queued_interactions.insert(0, continuation_info)
                    interaction = self._sim.queue.find_interaction_by_id(continuation_info.interaction_id)
                    if interaction is not None and not interaction.get_sims_with_invalid_paths():
                        continuation_info.ui_state = Sims_pb2.IQ_TRANSITIONING
                        interaction_messages.send_interaction_replace_message(self._sim, int_info.interaction_id, continuation_info, self._should_msg_be_immediate(self.QueueType.Super))
                    else:
                        interaction_messages.send_interactions_remove_msg(self._sim, (int_info,), self._should_msg_be_immediate(self.QueueType.Super))
                        interaction_messages.send_interactions_add_msg(self._sim, (continuation_info,), self._should_msg_be_immediate(self.QueueType.Super))
                    continuation_info.client_notified = True
                    for interaction_info in tuple(self._continuation_interactions):
                        while interaction_info.source_id == interaction_id:
                            if interaction_info.ui_state == Sims_pb2.IQ_TRANSITIONING:
                                self._add_running_interaction(interaction_info)
                            else:
                                self._queued_interactions.insert(0, interaction_info)
                                interaction_info.ui_state = Sims_pb2.IQ_TRANSITIONING
                            self._continuation_interactions.remove(interaction_info)
                            interaction_messages.send_interactions_add_msg(self._sim, (interaction_info,), self._should_msg_be_immediate(self.QueueType.Super))
                            interaction_info.client_notified = True
            else:
                logger.debug('=== SimId:{}, Sending Remove MSG for:{}', self._sim.id, interaction)
                self._remove_routing_interaction_info(int_info)
                self._update_routing_interaction_info(int_info)
                if self._last_running_interaction_id == int_info.interaction_id:
                    self._last_running_interaction_id = 0
                interaction_messages.send_interactions_remove_msg(self._sim, (int_info,), self._should_msg_be_immediate(self.QueueType.Super))
                if group_interactions:
                    interaction_messages.send_interactions_add_msg(self._sim, (group_interactions.pop(),), self._should_msg_be_immediate(self.QueueType.Super))
        logger.debug('=== Interaction Remove(from SI state) requested on an interaction not in the running interaction list')

    def remove_all_interactions(self):
        del self._queued_interactions[:]
        del self._super_interactions[:]
        del self._continuation_interactions[:]
        self._group_interactions.clear()
        self._routing_info = InteractionInfo.create_routing_info()
        self._last_running_interaction_id = 0
        if self._sim is not None:
            interaction_messages.send_interactions_removeall_msg(self._sim, immediate=True)

    def refresh_ui_data(self):
        interaction_messages.send_interaction_queue_view_add_msg(self._sim, self.get_interactions_gen(), immediate=True)

    def set_interaction_canceled(self, int_id, value):
        (int_info, _) = self._find_interaction(int_id)
        if int_info is not None:
            int_info.canceled = value
            interaction_messages.send_interactions_update_msg(self._sim, (int_info,), True)
            self._remove_routing_interaction_info(int_info)

    def set_interaction_icon_and_name(self, int_id, icon, name):
        (int_info, queue_type) = self._find_interaction(int_id)
        if int_info is not None:
            send_update = False
            if icon is not None:
                int_info.set_icon_info(icon)
                send_update = True
            if name is not None:
                int_info.display_name = name
                send_update = True
            if send_update:
                interaction_messages.send_interactions_update_msg(self._sim, (int_info,), self._should_msg_be_immediate(queue_type))

    def set_interaction_outcome(self, outcome_success, outcome_result_message=None):
        interaction_messages.send_interaction_outcome_msg(self._sim, outcome_success, outcome_result_message, False)

    def set_interaction_super_interaction(self, interaction, super_id):
        (int_info, queue_type) = self._find_interaction(interaction.id)
        if int_info is not None:
            int_info.super_id = self._get_super_id_for_mixer(super_id) or super_id
            interaction_messages.send_interactions_update_msg(self._sim, (int_info,), self._should_msg_be_immediate(queue_type))

    def get_routing_owner_id(self, id_to_find):
        if id_to_find == interactions.base.interaction.ROUTING_POSTURE_INTERACTION_ID and self._routing_info.routing_owner_id is not None:
            return self._routing_info.routing_owner_id
        return id_to_find

    def _add_interaction(self, interaction_queue, interaction, interaction_id_to_insert_after, queue_type):
        skill = interaction.get_associated_skill()
        (ui_visual_type, visual_group_data) = interaction.get_interaction_queue_visual_type()
        participants = None
        social_group = interaction.social_group
        if social_group is not None:
            participants = list(social_group)
        if not participants:
            participants = interaction.get_participants(ParticipantType.TargetSim | ParticipantType.Listeners)
        int_info = InteractionInfo(interaction.id, interaction.user_facing_target, participants, interaction.is_finishing, interaction.user_cancelable, interaction.get_name(), interaction.get_icon_info(), interaction.context.insert_strategy, skill, ui_visual_type, Sims_pb2.IQ_QUEUED, visual_group_data.group_tag, visual_group_data.group_priority, interaction.priority, interaction.mood_list)
        if not interaction.is_super:
            super_interaction = interaction.super_interaction
            if super_interaction is not None and super_interaction is not interaction:
                int_info.super_id = self._get_super_id_for_mixer(super_interaction.id) or super_interaction.id
                (super_interaction_info, _) = self._find_interaction(int_info.super_id)
                sa_name = super_interaction_info.display_name if super_interaction_info is not None else None
            else:
                sa_name = interaction.super_affordance.get_name(target=interaction.target, context=interaction.context)
            sa_icon_info = interaction.super_affordance.get_icon_info(target=interaction.target, context=interaction.context)
            int_info.set_super_icon_info(sa_name, sa_icon_info)
        if queue_type == self.QueueType.Queue:
            self._add_interaction_info_to_queue(interaction_queue, int_info, interaction, interaction_id_to_insert_after)
        else:
            interaction_queue.append(int_info)
        if interaction.context.source == interactions.context.InteractionSource.PIE_MENU:
            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_INTERACTION_QUEUE, sim=self._sim) as hook:
                hook.write_guid('idix', interaction.guid64)
                hook.write_int('queu', interaction_queue.index(int_info))
        return int_info

    def _add_interaction_info_to_queue(self, interaction_queue, int_info, interaction, interaction_id_to_insert_after):
        queue_len = len(interaction_queue)
        int_info.insert_after_id = self._last_running_interaction_id
        int_info_is_super = int_info.ui_visual_type != Sims_pb2.Interaction.MIXER
        if queue_len == 0 or int_info_is_super and int_info.insert_strategy == interactions.context.QueueInsertStrategy.LAST or not int_info_is_super and not interaction.should_insert_in_queue_on_append():
            interaction_queue.append(int_info)
        elif int_info.insert_strategy != interactions.context.QueueInsertStrategy.LAST:
            index_to_add = 0
            if interaction_id_to_insert_after is not None:
                for (i, queue_info) in enumerate(interaction_queue):
                    while queue_info.interaction_id == interaction_id_to_insert_after:
                        index_to_add = i + 1
                        break
            interaction_queue.insert(index_to_add, int_info)
        else:
            for (index, cur_info) in enumerate(interaction_queue):
                while cur_info.ui_visual_type != Sims_pb2.Interaction.MIXER and cur_info.insert_strategy == interactions.context.QueueInsertStrategy.LAST:
                    interaction_queue.insert(index, int_info)
                    break
            interaction_queue.append(int_info)
        index = interaction_queue.index(int_info)
        prev_index = index - 1
        next_index = index + 1
        if prev_index >= 0:
            int_info.insert_after_id = interaction_queue[prev_index].interaction_id
        if next_index < len(interaction_queue):
            interaction_queue[next_index].insert_after_id = int_info.interaction_id

    def _find_interaction(self, int_id):
        for cur_info in self._running_interactions:
            while int_id == cur_info.interaction_id:
                return (cur_info, self.QueueType.Super)
        for cur_info in self._queued_interactions:
            while int_id == cur_info.interaction_id:
                return (cur_info, self.QueueType.Queue)
        for cur_info in self._continuation_interactions:
            while int_id == cur_info.interaction_id:
                return (cur_info, self.QueueType.Continuation)
        return (None, None)

    def _find_continuation(self, int_id):
        for (index, cur_info) in enumerate(self._continuation_interactions):
            while cur_info.source_id == int_id:
                return self._continuation_interactions.pop(index)

    def _should_msg_be_immediate(self, queue_type):
        if queue_type == self.QueueType.Super:
            return False
        return True

    def _any_interaction_of_visual_type(self, visual_type):
        return any(int_info.is_visual_type_posture() for int_info in self.get_interactions_gen())

    def _update_skillbar_info(self, interaction, from_remove=False):
        interaction_id = interaction.id
        is_super = interaction.is_super
        if not is_super and interaction.super_interaction is not None:
            interaction_id = interaction.super_interaction.id
        sim_info = self._sim.sim_info
        if from_remove:
            if not is_super and not interaction.is_social:
                return
            if interaction_id in self._si_skill_mapping:
                if sim_info is not None and sim_info.current_skill_guid == self._si_skill_mapping[interaction_id]:
                    sim_info.current_skill_guid = 0
                del self._si_skill_mapping[interaction_id]
        else:
            skill = interaction.get_associated_skill()
            if skill is not None:
                skill_id = skill.guid64
                self._si_skill_mapping[interaction_id] = skill_id
                if skill_id != self._sim.sim_info.current_skill_guid:
                    self._sim.sim_info.current_skill_guid = skill_id

    def _add_routing_interaction_info(self, routing_interaction_info):
        if self._routing_info.routing_owner_id is not None:
            return
        if self._any_interaction_of_visual_type(Sims_pb2.Interaction.POSTURE):
            return
        self._routing_info.routing_owner_id = routing_interaction_info.interaction_id
        self._routing_info.interactions_to_be_canceled.add(routing_interaction_info.interaction_id)
        self._add_running_interaction(self._routing_info)
        interaction_messages.send_interactions_add_msg(self._sim, (self._routing_info,), self._should_msg_be_immediate(self.QueueType.Super))

    def _remove_routing_interaction_info(self, removing_interaction_info, force_remove=False):
        if self._routing_info.routing_owner_id is None:
            return
        if not force_remove and self._routing_info.routing_owner_id != removing_interaction_info.interaction_id:
            return
        self._remove_running_interactions(self._routing_info)
        interaction_messages.send_interactions_remove_msg(self._sim, (self._routing_info,), self._should_msg_be_immediate(self.QueueType.Super))
        self._routing_info.routing_owner_id = None
        self._routing_info.interactions_to_be_canceled = set()

    def _update_routing_interaction_info(self, interaction_info_removed):
        if not interaction_info_removed.is_visual_type_posture():
            return
        for interaction_info in self.get_interactions_gen():
            if interaction_info == self._routing_info:
                return
            while interaction_info.ui_state == Sims_pb2.IQ_TRANSITIONING:
                self._add_routing_interaction_info(interaction_info)

    def _update_interaction_for_potential_cancel(self):
        interaction_infos_to_update = set()
        for cur_info in self._super_interactions:
            if cur_info.interaction_id == interactions.base.interaction.ROUTING_POSTURE_INTERACTION_ID:
                pass
            interaction = self._sim.find_interaction_by_id(cur_info.interaction_id)
            if interaction is None:
                pass
            potential_canceled = SIState.potential_canceled_interaction_ids(interaction)
            if not cur_info.interactions_to_be_canceled.symmetric_difference(potential_canceled):
                pass
            cur_info.interactions_to_be_canceled = potential_canceled
            interaction_infos_to_update.add(cur_info)
        if interaction_infos_to_update:
            interaction_messages.send_interactions_update_msg(self._sim, interaction_infos_to_update, self._should_msg_be_immediate(self.QueueType.Super))

    def _update_mixers(self, old_super_id, new_super_id):
        interaction_infos_to_update = []
        for int_info in self._queued_interactions:
            if int_info.super_id == 0:
                pass
            if int_info.super_id != old_super_id:
                pass
            if int_info.super_id == new_super_id:
                pass
            int_info.super_id = new_super_id
            interaction_infos_to_update.append(int_info)
        if interaction_infos_to_update:
            interaction_messages.send_interactions_update_msg(self._sim, interaction_infos_to_update, self._should_msg_be_immediate(self.QueueType.Super))

class InteractionInfo:
    __qualname__ = 'InteractionInfo'
    ROUTING_DATA = sims4.tuning.tunable.TunableTuple(description='\n                       Display Name and icon that will be displayed in the\n                       posture area in the interaction queue while an\n                       interaction is transitioning.\n                       ', icon=sims4.tuning.tunable.TunableResourceKey(description='\n                            Icon to display in posture slot in UI while\n                            interaction is transitioning.\n                            ', default=None, resource_types=sims4.resources.CompoundTypes.IMAGE), routing_name=sims4.localization.TunableLocalizedString(description='\n                            Display name for icon when routing icon appears\n                            in posture slot of UI\n                            '))
    __slots__ = ('interaction_id', '_target_ref', 'participants', 'canceled', 'user_cancelable', 'display_name', '_icon', '_icon_object_ref', 'ui_state', 'source_id', 'associated_skill', 'super_id', 'ui_visual_type', 'insert_after_id', 'insert_strategy', 'interactions_to_be_canceled', 'visual_group_tag', 'visual_group_priority', 'routing_owner_id', 'client_notified', '_super_display_name', '_super_icon', '_super_icon_object_ref', 'mood_list', 'priority', 'interaction_weakref')

    def __init__(self, interaction_id, target, participants, canceled, user_cancelable, display_name, icon, insert_strategy, associated_skill, visual_type, ui_state, visual_group_tag, visual_group_priority, priority, mood_list):
        self.interaction_id = interaction_id
        self._target_ref = target.ref() if target is not None else None
        self.participants = participants
        self.canceled = canceled
        self.user_cancelable = user_cancelable
        self.display_name = display_name
        self.set_icon_info(icon)
        self.associated_skill = associated_skill.guid64 if associated_skill is not None else None
        self.ui_state = ui_state
        self.priority = priority
        self.source_id = 0
        self.super_id = 0
        self.ui_visual_type = visual_type
        self.visual_group_tag = visual_group_tag if visual_group_tag is not tag.Tag.INVALID else None
        self.visual_group_priority = visual_group_priority
        self.insert_strategy = insert_strategy
        self.routing_owner_id = None
        self.insert_after_id = 0
        self.interactions_to_be_canceled = set()
        self.client_notified = False
        self.mood_list = mood_list
        self._super_display_name = None
        self._super_icon = None
        self._super_icon_object_ref = None

    @property
    def target(self):
        if self._target_ref:
            return self._target_ref()

    @property
    def icon_info(self):
        return (self._icon, self._icon_object_ref() if self._icon_object_ref is not None else None)

    def set_icon_info(self, icon_info):
        self._icon = icon_info[0]
        self._icon_object_ref = icon_info[1].ref() if icon_info[1] is not None else None

    def set_super_icon_info(self, name, icon_info):
        self._super_display_name = name
        self._super_icon = icon_info[0]
        self._super_icon_object_ref = icon_info[1].ref() if icon_info[1] is not None else None

    def get_super_icon_info(self):
        return (self._super_display_name, (self._super_icon, self._super_icon_object_ref() if self._super_icon_object_ref is not None else None))

    @classmethod
    def create_routing_info(cls):
        routing_info = InteractionInfo(interactions.base.interaction.ROUTING_POSTURE_INTERACTION_ID, None, (), False, True, cls.ROUTING_DATA.routing_name, (cls.ROUTING_DATA.icon, None), None, None, Sims_pb2.Interaction.POSTURE, Sims_pb2.IQ_RUNNING, None, 0, interactions.priority.Priority.High, None)
        return routing_info

    def is_visual_type_posture(self):
        return self.ui_visual_type == Sims_pb2.Interaction.POSTURE

    def __repr__(self):
        if self.interaction_id == interactions.base.interaction.ROUTING_POSTURE_INTERACTION_ID:
            return 'Routing Interaction Info, canceled:{}'.format(self.canceled)
        return 'ID:{}, canceled:{}, ui_state:{}, visual_type:{}, super_id:{}, source_id:{}, insert_after_id:{}'.format(self.interaction_id, self.canceled, self.ui_state, self.ui_visual_type, self.super_id, self.source_id, self.insert_after_id)

