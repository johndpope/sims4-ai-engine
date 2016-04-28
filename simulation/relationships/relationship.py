from _collections import defaultdict
from protocolbuffers import DistributorOps_pb2, Commodities_pb2 as commodity_protocol
from protocolbuffers import SimObjectAttributes_pb2 as protocols
from distributor.ops import GenericProtocolBufferOp
from distributor.rollback import ProtocolBufferRollback
from distributor.shared_messages import send_relationship_op
from distributor.system import Distributor
from relationships import global_relationship_tuning
from relationships.relationship_bit import RelationshipBitType, RelationshipBit
from relationships.relationship_track import RelationshipTrack
from relationships.relationship_track_tracker import RelationshipTrackTracker
from sims4.tuning.tunable import Tunable
import alarms
import clock
import date_and_time
import event_testing
import services
import sims4.log
import telemetry_helper
logger = sims4.log.Logger('Relationship', default_owner='rez')
TELEMETRY_GROUP_RELATIONSHIPS = 'RSHP'
TELEMETRY_HOOK_ADD_BIT = 'BADD'
TELEMETRY_HOOK_REMOVE_BIT = 'BREM'
TELEMETRY_HOOK_CHANGE_LEVEL = 'RLVL'
TELEMETRY_FIELD_TARGET_ID = 'taid'
TELEMETRY_FIELD_REL_ID = 'rlid'
TELEMETRY_FIELD_BIT_ID = 'btid'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_RELATIONSHIPS)

class BitTimeoutData:
    __qualname__ = 'BitTimeoutData'

    def __init__(self, bit, alarm_callback):
        self._bit = bit
        self._alarm_callback = alarm_callback
        self._alarm_handle = None
        self._start_time = 0

    @property
    def bit(self):
        return self._bit

    @property
    def alarm_handle(self):
        return self._alarm_handle

    def reset_alarm(self):
        logger.assert_raise(self._bit is not None, '_bit is None in BitTimeoutData.')
        if self._alarm_handle is not None:
            self.cancel_alarm()
        self._set_alarm(self._bit.timeout)

    def cancel_alarm(self):
        if self._alarm_handle is not None:
            alarms.cancel_alarm(self._alarm_handle)
            self._alarm_handle = None

    def load(self, time):
        self.cancel_alarm()
        time_left = self._bit.timeout - time
        if time_left > 0:
            self._set_alarm(time_left)
            return True
        logger.warn('Invalid time loaded for timeout for bit {}.  This is valid if the tuning data changed.', self._bit)
        return False

    def get_elapsed_time(self):
        if self._alarm_handle is not None:
            now = services.time_service().sim_now
            delta = now - self._start_time
            return delta.in_minutes()
        return 0

    def _set_alarm(self, time):
        time_span = clock.interval_in_sim_minutes(time)
        self._alarm_handle = alarms.add_alarm(self, time_span, self._alarm_callback, repeating=False)
        logger.assert_raise(self._alarm_handle is not None, 'Failed to create timeout alarm for rel bit {}'.format(self.bit))
        self._start_time = services.time_service().sim_now

class SimKnowledge:
    __qualname__ = 'SimKnowledge'

    def __init__(self, relationship):
        self._relationship = relationship
        self._known_traits = set()
        self._num_traits = 0

    def add_known_trait(self, trait, num_traits=None, notify_client=True):
        if trait.is_personality_trait:
            self._known_traits.add(trait)
            if num_traits is not None and num_traits != self._num_traits:
                self._num_traits = num_traits
            self._relationship.send_relationship_info()
        else:
            logger.error("Try to add non personality trait {} to Sim {}'s knowledge about to Sim {}", trait, self._relationship.sim_id, self._relationship.target_sim_id)

    def set_num_traits(self, num_traits):
        self._num_traits = num_traits

    @property
    def known_traits(self):
        return self._known_traits

    @property
    def num_traits(self):
        return self._num_traits

    def get_save_data(self):
        save_data = protocols.SimKnowledge()
        for trait in self._known_traits:
            save_data.trait_ids.append(trait.guid64)
        save_data.num_traits = self._num_traits
        return save_data

    def load(self, save_data):
        trait_manager = services.get_instance_manager(sims4.resources.Types.TRAIT)
        self._num_traits = save_data.num_traits
        for trait_inst_id in save_data.trait_ids:
            trait = trait_manager.get(trait_inst_id)
            while trait is not None:
                self.known_traits.add(trait)

class Relationship:
    __qualname__ = 'Relationship'
    MIN_RELATIONSHIP_VALUE = Tunable(float, -100, description='The minimum value any relationship can be.')
    MAX_RELATIONSHIP_VALUE = Tunable(float, 100, description='The maximum value any relationship can be.')
    DEFAULT_RELATIONSHIP_VALUE = Tunable(float, 0, description='The default value for relationship track scores.')
    DEFAULT_SHORT_TERM_CONTEXT_TRACK = RelationshipTrack.TunableReference(description='\n        If no short-term context tracks exist for a relationship, use this\n        default as the prevailing track.\n        ')
    DELAY_UNTIL_RELATIONSHIP_IS_CULLED = Tunable(description='\n                                                    The amount of time, in sim minutes, that it takes before \n                                                    a relationship is culled once all of the tracks have reached\n                                                    convergence.\n                                                    ', tunable_type=int, default=10)
    MARRIAGE_RELATIONSHIP_BIT = RelationshipBit.TunableReference(description="\n        The marriage relationship bit. This tuning references the relationship bit signifying that \n        the sim is a spouse to someone. Whenever this bit is added to a sim's relationship, it has \n        the side effect of updating the spouse_sim_id on a sim's relationship tracker. If the bit \n        goes away, the field is cleared. \n        ")
    SIGNIFICANT_OTHER_RELATIONSHIP_BIT = RelationshipBit.TunableReference(description='\n        The significant other relationship bit. This tuning references the relationship bit signifying that \n        the sim is a significant other to someone.\n        ')

    def __init__(self, tracker, sim_id, target_sim_id):
        self._tracker = tracker
        self._sim_id = sim_id
        self._target_sim_id = target_sim_id
        self._bits = {}
        self._cached_depth = 0
        self._cached_depth_dirty = True
        self._bit_timeouts = []
        self._bit_track_tracker = RelationshipTrackTracker(self)
        self._level_change_watcher_id = self._bit_track_tracker.add_watcher(self._value_changed)
        self._knowledge = None
        self._culling_alarm_handle = None
        self.bit_added_buffs = defaultdict(list)

    def __repr__(self):
        if services.sim_info_manager():
            return 'Relationship: {} & {}'.format(self.find_sim_info(), self.find_target_sim_info())
        return 'Relationship: {} & {}'.format(self.sim_id, self.target_sim_id)

    def destroy(self, notify_client=True):
        if notify_client:
            self._send_destroy_message_to_client()
        self._bit_track_tracker.remove_watcher(self._level_change_watcher_id)
        self._level_change_watcher_id = None
        self._destroy_culling_alarm()
        self._tracker = None
        self._bits.clear()
        self.bit_added_buffs.clear()
        self._bit_timeouts.clear()
        self._bit_track_tracker.destroy()
        self._bit_track_tracker = None
        self._knowledge = None

    def _value_changed(self, stat_type, old_value, new_value):
        if stat_type.causes_delayed_removal_on_convergence:
            self._destroy_culling_alarm()

    @property
    def ID(self):
        return self.relationship_id

    @property
    def relationship_id(self):
        return self._target_sim_id

    def find_sim_info(self):
        sim_info = services.sim_info_manager().get(self.sim_id)
        return sim_info

    def find_target_sim_info(self):
        target_sim_info = services.sim_info_manager().get(self.target_sim_id)
        return target_sim_info

    def find_sim(self):
        sim_info = self.find_sim_info()
        if sim_info is not None:
            return sim_info.get_sim_instance()

    def find_target_sim(self):
        target_sim_info = self.find_target_sim_info()
        if target_sim_info is not None:
            return target_sim_info.get_sim_instance()

    def _find_matching_relationship(self):
        target_sim_info = self.find_target_sim_info()
        if target_sim_info is None:
            logger.error("Couldn't find matching relationship object for {}.", self)
            return
        target_relationship = target_sim_info.relationship_tracker._find_relationship(self._sim_id)
        return target_relationship

    @property
    def sim(self):
        logger.error('Deprecated: Use find_sim() or find_sim_info() instead.')
        return self.find_sim()

    @property
    def target(self):
        logger.error('Deprecated: Use find_target_sim() or find_target_sim_info() instead.')
        return self.find_target_sim()

    @property
    def sim_id(self):
        return self._sim_id

    @property
    def target_sim_id(self):
        return self._target_sim_id

    @property
    def bit_track_tracker(self):
        return self._bit_track_tracker

    @property
    def suppress_client_updates(self):
        return self._tracker.suppress_client_updates

    def get_knowledge(self, initialize=False):
        if initialize and self._knowledge is None:
            self._knowledge = SimKnowledge(self)
        return self._knowledge

    def get_persistance_protocol_buffer(self):
        save_data = protocols.PersistableRelationship()
        save_data.target_id = self._target_sim_id
        for bit in self._bits:
            while bit.persisted:
                save_data.bits.append(bit.guid64)
        for (bit_id, buff_ids) in self.bit_added_buffs.items():
            with ProtocolBufferRollback(save_data.bit_added_buffs) as bit_added_buff:
                bit_added_buff.bit_id = bit_id
                bit_added_buff.buff_ids.extend(buff_ids)
        for timeout in self._bit_timeouts:
            timeout_proto_buffer = save_data.timeouts.add()
            timeout_proto_buffer.timeout_bit_id_hash = timeout.bit.guid64
            timeout_proto_buffer.elapsed_time = timeout.get_elapsed_time()
        for track in self._bit_track_tracker:
            while track.persisted:
                track_proto_buffer = save_data.tracks.add()
                track_proto_buffer.track_id = track.type_id()
                track_proto_buffer.value = track.get_value()
                track_proto_buffer.visible = track.visible_to_client
        if self._knowledge is not None:
            save_data.knowledge = self._knowledge.get_save_data()
        return save_data

    def load(self, sim_info, rel_data):
        try:
            track_manager = services.get_instance_manager(sims4.resources.Types.STATISTIC)
            try:
                self._bit_track_tracker.suppress_callback_setup_during_load = True
                for track_data in rel_data.tracks:
                    track_type = track_manager.get(track_data.track_id)
                    track_inst = self._bit_track_tracker.add_statistic(track_type)
                    if track_inst is not None:
                        track_inst.set_value(track_data.value)
                        track_inst.update_instance_data()
                        track_inst.visible_to_client = track_data.visible
                        track_inst.fixup_callbacks_during_load()
                    else:
                        logger.warn('Failed to load track {} on sim {}.  This is valid if the tuning has changed.', track_type, sim_info, owner='rez')
            finally:
                self._bit_track_tracker.suppress_callback_setup_during_load = False
            bit_manager = services.get_instance_manager(sims4.resources.Types.RELATIONSHIP_BIT)
            logger.assert_raise(bit_manager, 'Unable to retrieve relationship bit manager.')
            bit_list = [bit_manager.get(bit_instance_id) for bit_instance_id in rel_data.bits]
            for bit_added_buff in rel_data.bit_added_buffs:
                self.bit_added_buffs[bit_added_buff.bit_id] = list(bit_added_buff.buff_ids)
            while len(bit_list):
                bit = bit_list.pop()
                if bit is None:
                    logger.error('Loading None bit for sim {}.', sim_info, owner='rez')
                    continue
                if self.has_bit(bit):
                    continue
                while not self.add_bit(bit, False, bit_list, bit_added_buffs=self.bit_added_buffs.get(bit.guid64, None)):
                    logger.warn('Failed to load relationship bit {} for sim {}.  This is valid if tuning has changed.', bit, sim_info)
                    continue
            if rel_data.timeouts is not None:
                for timeout_save in rel_data.timeouts:
                    bit = bit_manager.get(timeout_save.timeout_bit_id_hash)
                    timeout_data = self._find_timeout_data_by_bit(bit)
                    if timeout_data is not None:
                        self.remove_bit(bit, False)
                    else:
                        logger.warn('Attempting to load timeout value on bit {} with no timeout.  This is valid if tuning has changed.', bit)
            while rel_data.knowledge is not None:
                self._knowledge = SimKnowledge(self)
                self._knowledge.load(rel_data.knowledge)
        except Exception:
            logger.exception('Exception thrown while loading relationship data for Sim {}', sim_info, owner='rez')

    def add_neighbor_bit_if_necessary(self, sim_info):
        target_sim_info = self.find_target_sim_info()
        if target_sim_info is None:
            return
        if sim_info.household is None or target_sim_info.household is None:
            return
        home_zone_id = sim_info.household.home_zone_id
        target_home_zone_id = target_sim_info.household.home_zone_id
        if home_zone_id == target_home_zone_id:
            return
        if home_zone_id == 0 or target_home_zone_id == 0:
            return
        sim_home_zone_proto_buffer = services.get_persistence_service().get_zone_proto_buff(home_zone_id)
        target_sim_home_zone_proto_buffer = services.get_persistence_service().get_zone_proto_buff(target_home_zone_id)
        if sim_home_zone_proto_buffer is None or target_sim_home_zone_proto_buffer is None:
            logger.error('Invalid zone protocol buffer in Relationship.add_neighbor_bit_if_necessary()')
            return
        if sim_home_zone_proto_buffer.world_id != target_sim_home_zone_proto_buffer.world_id:
            return
        self.add_bit(global_relationship_tuning.RelationshipGlobalTuning.NEIGHBOR_RELATIONSHIP_BIT, notify_client=False)
        target_relationship = self._tracker._find_relationship(sim_info.id, create=False)
        if target_relationship is not None:
            target_relationship.add_bit(global_relationship_tuning.RelationshipGlobalTuning.NEIGHBOR_RELATIONSHIP_BIT, notify_client=False)

    def send_relationship_info(self, deltas=None):
        self._notify_client(deltas)

    def get_track_score(self, track):
        return self._bit_track_tracker.get_user_value(track)

    def set_track_score(self, value, track):
        self._bit_track_tracker.set_value(track, value)

    def add_track_score(self, increment, track):
        self._bit_track_tracker.add_value(track, increment)

    def enable_selectable_sim_track_decay(self, to_enable=True):
        self._bit_track_tracker.enable_selectable_sim_track_decay(to_enable)

    def get_track_utility_score(self, track):
        track_inst = self._bit_track_tracker.get_statistic(track)
        if track_inst is not None:
            return track_inst.autonomous_desire
        return track.autonomous_desire

    def get_track(self, track, add=False):
        return self._bit_track_tracker.get_statistic(track, add)

    def get_highest_priority_track_bit(self):
        highest_priority_bit = None
        for track in self._bit_track_tracker:
            bit = track.get_active_bit()
            if not bit:
                pass
            while highest_priority_bit is None or bit.priority > highest_priority_bit.priority:
                highest_priority_bit = bit
        return highest_priority_bit

    def get_prevailing_short_term_context_track(self):
        tracks = [track for track in self._bit_track_tracker if track.is_short_term_context]
        if tracks:
            return max(tracks, key=lambda t: abs(t.get_value()))
        return self.get_track(self.DEFAULT_SHORT_TERM_CONTEXT_TRACK, add=True)

    def track_reached_convergence(self, track_instance):
        if track_instance.causes_delayed_removal_on_convergence and self._can_cull_relationship():
            logger.debug('{} has been marked for culling.', self)
            self._create_culling_alarm()
        if track_instance.is_visible:
            logger.debug('Notifying client that {} has reached convergence.', self)
            self._notify_client()

    def apply_social_group_decay(self):
        for track in self._bit_track_tracker:
            track.apply_social_group_decay()
        target_relationship = self._find_matching_relationship()
        if target_relationship is not None:
            for track in target_relationship.bit_track_tracker:
                track.apply_social_group_decay()
        else:
            logger.warn("Couldn't apply social group decay to both sides of the relationship for {}", self)
            self.find_sim().log_sim_info(logger.warn)
            self.find_target_sim().log_sim_info(logger.warn)

    def remove_social_group_decay(self):
        for track in self._bit_track_tracker:
            track.remove_social_group_decay()
        target_relationship = self._find_matching_relationship()
        if target_relationship is not None:
            for track in target_relationship.bit_track_tracker:
                track.remove_social_group_decay()
        else:
            logger.warn("Couldn't remove social group decay to both sides of the relationship for {}", self)

    def add_bit(self, bit, notify_client=True, pending_bits=None, bit_added_buffs=None):
        logger.assert_raise(bit is not None, 'Error: Sim Id: {} trying to add a None relationship bit to Sim_Id: {}.'.format(self._sim_id, self._target_sim_id))
        compatibility_bit_list = [key for key in self._bits.keys()]
        if pending_bits is not None:
            compatibility_bit_list.extend(pending_bits)
        required_bit_count = len(bit.required_bits)
        bit_to_remove = None
        for curr_bit in compatibility_bit_list:
            if curr_bit is bit:
                logger.debug('Attempting to add duplicate bit {} on {}', bit, self)
                return False
            if required_bit_count and curr_bit in bit.required_bits:
                required_bit_count -= 1
            while bit.group_id != RelationshipBitType.NoGroup and bit.group_id == curr_bit.group_id:
                if bit.priority >= curr_bit.priority:
                    logger.assert_raise(bit_to_remove is None, 'Multiple relationship bits of the same type are set on a single relationship: {}'.format(self))
                    bit_to_remove = curr_bit
                else:
                    logger.debug('Failed to add bit {}; existing bit {} has higher priority for {}', bit, curr_bit, self)
                    return False
        if bit.remove_on_threshold:
            track_val = self._bit_track_tracker.get_value(bit.remove_on_threshold.track)
            if bit.remove_on_threshold.threshold.compare(track_val):
                logger.debug('Failed to add bit {}; track {} meets the removal threshold {} for {}', bit, bit.remove_on_threshold.track, bit.remove_on_threshold.threshold, self)
                return False
        if required_bit_count > 0:
            logger.debug('Failed to add bit {}; required bit count is {}', bit, required_bit_count)
            return False
        if bit_to_remove is not None:
            self.remove_bit(bit_to_remove, False)
        bit_instance = bit()
        if bit_added_buffs is not None:
            bit_instance.bit_added_buffs.extend(bit_added_buffs)
        self._bits[bit] = bit_instance
        self._cached_depth_dirty = True
        logger.debug('Added bit {} for {}', bit, self)
        sim_info = self.find_sim_info()
        if sim_info is not None:
            target_sim_info = self.find_target_sim_info()
            sim = sim_info.get_sim_instance()
            if sim is not None and target_sim_info is not None:
                bit_instance.on_add_to_relationship(sim, target_sim_info, self)
            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_ADD_BIT, sim=sim_info) as hook:
                hook.write_int(TELEMETRY_FIELD_TARGET_ID, self._target_sim_id)
                hook.write_int(TELEMETRY_FIELD_REL_ID, self.ID)
                hook.write_int(TELEMETRY_FIELD_BIT_ID, bit.guid64)
            try:
                services.get_event_manager().process_event(event_testing.test_events.TestEvent.AddRelationshipBit, sim_info=sim_info, relationship_bit=bit, sim_id=self._sim_id, target_sim_id=self._target_sim_id)
            except Exception:
                logger.warn('Threw error while attempting to process achievement on bit add.', owner='rez')
        if self.suppress_client_updates or bit is Relationship.MARRIAGE_RELATIONSHIP_BIT:
            if sim_info is not None:
                sim_info.update_spouse_sim_id(self._target_sim_id)
        if bit.timeout > 0:
            timeout_data = self._find_timeout_data_by_bit(bit)
            if timeout_data is None:
                timeout_data = BitTimeoutData(bit, self._timeout_alarm_callback)
                self._bit_timeouts.append(timeout_data)
            timeout_data.reset_alarm()
        if bit.remove_on_threshold:
            track_type = bit.remove_on_threshold.track
            listener = self._bit_track_tracker.create_and_activate_listener(track_type, bit.remove_on_threshold.threshold, self._remove_bit_due_to_track_threshold_callback)
            bit_instance.add_conditional_removal_listener(listener)
        if sim_info:
            bit_instance.add_appropriateness_buffs(sim_info)
        if notify_client is True:
            self._notify_client()
        return True

    def remove_bit(self, bit, notify_client=True):
        logger.assert_raise(bit is not None, 'Error: Sim Id: {} trying to remove a None relationship bit to Sim_Id: {}.'.format(self._sim_id, self._target_sim_id))
        if bit not in self._bits:
            logger.debug("Attempting to remove bit for {} that doesn't exist: {}", self, bit)
            return
        sim_info = self.find_sim_info()
        bit_instance = self._bits[bit]
        if self.suppress_client_updates or sim_info is not None:
            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_REMOVE_BIT, sim=sim_info) as hook:
                hook.write_int(TELEMETRY_FIELD_TARGET_ID, self._target_sim_id)
                hook.write_int(TELEMETRY_FIELD_REL_ID, self.ID)
                hook.write_int(TELEMETRY_FIELD_BIT_ID, bit.guid64)
                try:
                    services.get_event_manager().process_event(event_testing.test_events.TestEvent.RemoveRelationshipBit, sim_info=sim_info, relationship_bit=bit, sim_id=self._sim_id, target_sim_id=self._target_sim_id)
                except Exception:
                    logger.warn('Threw error while attempting to process achievement on bit add.  If you used a cheat, this is fine.', owner='rez')
            sim = sim_info.get_sim_instance()
            if sim is not None:
                target_sim_info = self.find_target_sim_info()
                if target_sim_info is not None:
                    bit_instance.on_remove_from_relationship(sim, target_sim_info)
            if bit is Relationship.MARRIAGE_RELATIONSHIP_BIT:
                sim_info.update_spouse_sim_id(None)
        del self._bits[bit]
        self._cached_depth_dirty = True
        logger.debug('Removed bit {} for {}', bit, self)
        timeout_data = self._find_timeout_data_by_bit(bit)
        if timeout_data is not None:
            timeout_data.cancel_alarm()
            self._bit_timeouts.remove(timeout_data)
        if bit.remove_on_threshold:
            listener = bit_instance.remove_conditional_removal_listener()
            if listener is not None:
                self._bit_track_tracker.remove_listener(listener)
            else:
                logger.error("Bit {} is meant to have a listener on track {} but it doesn't for {}.".format(bit, bit.remove_on_threshold.track, self))
        if sim_info:
            bit_instance.remove_appropriateness_buffs(sim_info)
        if notify_client is True:
            self._notify_client()

    def get_bits(self):
        return self._bits.keys()

    def _timeout_alarm_callback(self, alarm_handle):
        timeout_data = self._find_timeout_data_by_handle(alarm_handle)
        if timeout_data is not None:
            self.remove_bit(timeout_data.bit)
        else:
            logger.error('Failed to find alarm handle in _bit_timeouts list')

    def has_bit(self, bit):
        return any(bit.matches_bit(bit_type) for bit_type in self.get_bits())

    def get_bit_instance(self, bit_type):
        if bit_type in self._bits:
            return self._bits[bit_type]

    def get_highest_priority_bit(self):
        highest_priority_bit = None
        for bit in self._bits.keys():
            while highest_priority_bit is None or bit.priority > highest_priority_bit.priority:
                highest_priority_bit = bit
        return highest_priority_bit

    def add_historical_bits_on_age_up(self, current_age):
        historical_bits_to_add = set()
        for bit in self._bits:
            while bit.historical_bits is not None:
                while True:
                    for historical_bit_data in bit.historical_bits:
                        while historical_bit_data.age_trans_from == current_age:
                            historical_bits_to_add.add(historical_bit_data.new_historical_bit)
        for new_bit in historical_bits_to_add:
            self.add_bit(new_bit)

    def add_relationship_appropriateness_buffs(self):
        sim_info = self.find_sim_info()
        for bit in self._bits.values():
            bit.add_appropriateness_buffs(sim_info)

    def build_printable_string_of_bits(self):
        return '\t\t{}'.format('\n\t\t'.join(map(str, self._bits)))

    def build_printable_string_of_tracks(self):
        ret = ''
        for track in self._bit_track_tracker:
            ret += '\t\t{} = {}; decaying? {}; decay rate: {}\n'.format(track, track.get_value(), track.decay_enabled, track.get_decay_rate())
        return ret

    @property
    def depth(self):
        if self._cached_depth_dirty:
            self._refresh_depth_cache()
        return self._cached_depth

    def _refresh_depth_cache(self):
        self._cached_depth = 0
        for key in self._bits:
            pass
        self._cached_depth_dirty = False

    def _find_timeout_data_by_bit(self, bit):
        for data in self._bit_timeouts:
            while bit is data.bit:
                return data

    def _find_timeout_data_by_handle(self, alarm_handle):
        for data in self._bit_timeouts:
            while alarm_handle is data.alarm_handle:
                return data

    def _remove_bit_due_to_track_threshold_callback(self, track):
        for bit in self._bits.keys():
            while bit.remove_on_threshold and bit.remove_on_threshold.track is type(track):
                self.remove_bit(bit)
                return
        logger.error("Got a callback to remove a bit for track {}, but one doesn't exist.".format(track), owner='rez')

    def _build_relationship_update_proto(self, deltas=None):
        msg = commodity_protocol.RelationshipUpdate()
        msg.actor_sim_id = self._sim_id
        msg.target_id.object_id = self._target_sim_id
        msg.target_id.manager_id = services.sim_info_manager().id
        client_tracks = [track for track in self._bit_track_tracker if track.display_priority > 0]
        client_tracks.sort(key=lambda track: track.display_priority)
        track_bits = set()
        for track in client_tracks:
            if track.visible_to_client:
                with ProtocolBufferRollback(msg.tracks) as relationship_track_update:
                    relationship_track_update.track_score = track.get_value()
                    relationship_track_update.track_bit_id = track.get_bit_for_client().guid64
                    relationship_track_update.track_id = track.guid64
                    relationship_track_update.track_popup_priority = track.display_popup_priority
                    relationship_track_update.change_rate = track.get_change_rate()
                    while deltas is not None:
                        track_delta = deltas.get(track)
                        while track_delta is not None:
                            relationship_track_update.delta = track_delta
            track_bits.add(track.get_bit_for_client().guid64)
        for bit in self._bits.values():
            if not bit.visible:
                pass
            if bit.guid64 in track_bits:
                pass
            msg.bit_ids.append(bit.guid64)
        if self._knowledge is not None:
            msg.num_traits = self._knowledge.num_traits
            for trait in self._knowledge.known_traits:
                msg.known_trait_ids.append(trait.guid64)
        target_sim_info = self.find_target_sim_info()
        if target_sim_info is not None and target_sim_info.spouse_sim_id is not None:
            msg.target_sim_significant_other_id = target_sim_info.spouse_sim_id
        return msg

    def _notify_client(self, deltas=None):
        if self.suppress_client_updates:
            return
        sim_info = self.find_sim_info()
        if sim_info is not None:
            send_relationship_op(sim_info, self._build_relationship_update_proto(deltas=deltas))

    def _send_destroy_message_to_client(self):
        msg = commodity_protocol.RelationshipDelete()
        msg.actor_sim_id = self._sim_id
        msg.target_id = self._target_sim_id
        op = GenericProtocolBufferOp(DistributorOps_pb2.Operation.SIM_RELATIONSHIP_DELETE, msg)
        distributor = Distributor.instance()
        distributor.add_op(self.find_sim_info(), op)

    def _create_culling_alarm(self):
        self._destroy_culling_alarm()
        time_range = date_and_time.create_time_span(minutes=self.DELAY_UNTIL_RELATIONSHIP_IS_CULLED)
        self._culling_alarm_handle = alarms.add_alarm(self, time_range, self._cull_relationship_callback)

    def _destroy_culling_alarm(self):
        if self._culling_alarm_handle is not None:
            alarms.cancel_alarm(self._culling_alarm_handle)
            self._culling_alarm_handle = None

    def _cull_relationship_callback(self, _):
        self._destroy_culling_alarm()
        if self._can_cull_relationship():
            target_sim_info = self.find_target_sim_info()
            logger.debug('Culling {}', self)
            target_sim_info.relationship_tracker.destroy_relationship(self.sim_id)
            self._tracker.destroy_relationship(self.target_sim_id)
        else:
            logger.warn("Attempting to cull {} but it's no longer allowed.", self)

    def _can_cull_relationship(self):
        sim_info = self.find_sim_info()
        target_sim_info = self.find_target_sim_info()
        if sim_info is not None and target_sim_info is not None and sim_info.household_id == target_sim_info.household_id:
            return False
        if not self._bit_track_tracker.are_all_tracks_that_cause_culling_at_convergence():
            return False
        for bit in self._bits.values():
            while bit.prevents_relationship_culling:
                return False
        return True

