import operator
import collections
from sims4.math import Threshold, EPSILON
from sims4.tuning.tunable import TunableList, TunableTuple, TunableReference, Tunable, TunableFactory
import services
import sims4.log
import sims4.resources
logger = sims4.log.Logger('Relationship', default_owner='rez')
TrackMean = collections.namedtuple('TrackMean', ['track', 'mean'])

class BaseRelationshipTrackData:
    __qualname__ = 'BaseRelationshipTrackData'

    def build_track_data(self):
        raise NotImplementedError

    def get_track_instance_data(self, track):
        raise NotImplementedError

    def bit_track_node_gen(self):
        yield None

    def get_track_mean_list_for_bit(self, bit):
        return []

    @classmethod
    def _create_dummy_list_node(cls, min_rel, max_rel):
        raise NotImplementedError

    @classmethod
    def sort_bit_list(cls, list_to_sort):
        final_list = []
        list_to_sort.sort(key=lambda node: node.min_rel)
        last_min = 100
        for node in reversed(list_to_sort):
            if last_min > node.max_rel:
                dummy_node = cls._create_dummy_list_node(node.max_rel, last_min)
                final_list.insert(0, dummy_node)
            elif last_min < node.max_rel:
                logger.error('Tuning error: two nodes are overlapping in relationship track: {0}', cls)
                node.max_rel = last_min
            final_list.insert(0, node)
            last_min = node.min_rel
        if final_list and final_list[0].min_rel > -100:
            dummy_node = cls._create_dummy_list_node(-100, final_list[0].min_rel)
            final_list.insert(0, dummy_node)
        return final_list

class BaseRelationshipTrackInstanceData:
    __qualname__ = 'BaseRelationshipTrackInstanceData'

    def __init__(self, track):
        self._track = track

    def __repr__(self):
        return '{}'.format(self._track)

    def setup_callbacks(self):
        raise NotImplementedError

    def get_active_bit(self):
        raise NotImplementedError

    def request_full_update(self):
        raise NotImplementedError

    @property
    def _track_data(self):
        return self._track.bit_data

    def _apply_bit_change(self, bit_to_remove, bit_to_add):
        notify_client = False
        relationship = self._track.tracker.relationship
        if bit_to_remove is not None:
            relationship.remove_bit(bit_to_remove, False)
            notify_client = True
        if bit_to_add is not None:
            relationship.add_bit(bit_to_add, False)
            notify_client = True
        if notify_client and not relationship.suppress_client_updates:
            relationship.send_relationship_info()

class BitTrackNode:
    __qualname__ = 'BitTrackNode'

    def __init__(self, bit, min_rel, max_rel):
        self.bit = bit
        self.min_rel = min_rel
        self.max_rel = max_rel
        if self.bit:
            self.bit.is_track_bit = True
            self.bit.track_min_score = min_rel
            self.bit.track_max_score = max_rel
            self.bit.track_mean_score = (min_rel + max_rel)*0.5

    def __repr__(self):
        return '<Bit:{}[{}-{}]>'.format(self.bit, self.min_rel, self.max_rel)

class TunableRelationshipBitSet(TunableList):
    __qualname__ = 'TunableRelationshipBitSet'

    def __init__(self, **kwargs):
        super().__init__(TunableTuple(bit=TunableReference(services.get_instance_manager(sims4.resources.Types.RELATIONSHIP_BIT), description='Reference to bit in set'), minimum_value=Tunable(float, -100, description='Minimum track score value for the bit.'), maximum_value=Tunable(float, 100, description='Maximum track score value for the bit.'), description='Data for this bit in the track'), **kwargs)

class SimpleRelationshipTrackData(BaseRelationshipTrackData):
    __qualname__ = 'SimpleRelationshipTrackData'

    def __init__(self, bit_data):
        super().__init__()
        self.bit_set_list = []
        self._raw_bit_data = bit_data

    def build_track_data(self):
        if self.bit_set_list:
            self.bit_set_list = []
        if not self._raw_bit_data:
            return
        temp_list = [BitTrackNode(bit_set.bit, bit_set.minimum_value, bit_set.maximum_value) for bit_set in self._raw_bit_data]
        self.bit_set_list = self.sort_bit_list(temp_list)

    def get_track_instance_data(self, track):
        return SimpleRelationshipTrackInstanceData(track)

    def bit_track_node_gen(self):
        for bit_data in self.bit_set_list:
            yield bit_data

    def get_track_mean_list_for_bit(self, bit):
        return [TrackMean(bit.triggered_track, bit.track_mean_score)]

    @classmethod
    def _create_dummy_list_node(cls, min_rel, max_rel):
        return BitTrackNode(None, min_rel, max_rel)

class TunableRelationshipBitData(TunableFactory):
    __qualname__ = 'TunableRelationshipBitData'
    FACTORY_TYPE = SimpleRelationshipTrackData

    def __init__(self, **kwargs):
        super().__init__(bit_data=TunableRelationshipBitSet(), **kwargs)

class SimpleRelationshipTrackInstanceData(BaseRelationshipTrackInstanceData):
    __qualname__ = 'SimpleRelationshipTrackInstanceData'

    def __init__(self, track):
        super().__init__(track)
        self._bit_set_index = -1

    def setup_callbacks(self):
        for node in self._track_data.bit_set_list:
            if node.bit is None:
                logger.debug('{} has a dummy node {}, please check this gap between tuned bit nodes are intentional', self, node)
            threshold = Threshold(node.min_rel, operator.ge)
            self._track.tracker.create_and_activate_listener(self._track.stat_type, threshold, self._track_update_move_up_callback)
            threshold = Threshold(node.max_rel, operator.lt)
            self._track.tracker.create_and_activate_listener(self._track.stat_type, threshold, self._track_update_move_down_callback)

    def get_active_bit(self):
        if self._bit_set_index < 0:
            return
        bit_track_node = self._track_data.bit_set_list[self._bit_set_index]
        return bit_track_node.bit

    def request_full_update(self):
        self._full_update()

    def _update(self, moving_down):
        track_data = self._track_data
        if self._bit_set_index == -1:
            return self._full_update()
        original_node = track_data.bit_set_list[self._bit_set_index]
        curr_node = original_node
        score = self._track.get_value()
        if moving_down:
            if self._bit_set_index <= 0:
                return (None, None)
            if score - EPSILON <= curr_node.min_rel:
                curr_node = track_data.bit_set_list[self._bit_set_index]
        else:
            if self._bit_set_index >= len(track_data.bit_set_list) - 1:
                return (None, None)
            if score + EPSILON >= curr_node.max_rel:
                curr_node = track_data.bit_set_list[self._bit_set_index]
        logger.debug('Updating track {}', self)
        logger.debug('   Score: {}', score)
        logger.debug('   Original node: {} - {}', original_node.min_rel, original_node.max_rel)
        logger.debug('   Current node:  {} - {}', curr_node.min_rel, curr_node.max_rel)
        logger.debug('   index: {}', self._bit_set_index)
        if curr_node == original_node:
            return (None, None)
        new_bit = track_data.bit_set_list[self._bit_set_index].bit
        logger.debug('   Old bit: {}', original_node.bit)
        logger.debug('   New bit: {}', new_bit)
        return (original_node.bit, new_bit)

    def _full_update(self):
        track_data = self._track_data
        score = self._track.get_value()
        old_bit = None
        if self._bit_set_index != -1:
            old_bit = track_data.bit_set_list[self._bit_set_index].bit
        for (i, bit_set) in enumerate(track_data.bit_set_list):
            while score >= bit_set.min_rel and score <= bit_set.max_rel:
                self._bit_set_index = i
                break
        new_bit = None
        if self._bit_set_index != -1:
            new_bit = track_data.bit_set_list[self._bit_set_index].bit
        else:
            logger.warn("There's a hole in RelationshipTrack: {}", self._track, owner='rez')
        logger.debug('Updating track (FULL) {}', self._track)
        logger.debug('   Score: {}', score)
        logger.debug('   Current node:  {} - {}', track_data.bit_set_list[self._bit_set_index].min_rel, track_data.bit_set_list[self._bit_set_index].max_rel)
        logger.debug('   Old bit: {}', old_bit)
        logger.debug('   New bit: {}', new_bit)
        logger.debug('   index: {}', self._bit_set_index)
        return (old_bit, new_bit)

    def _track_update_move_up_callback(self, _):
        logger.debug('_track_update_move_up_callback() called')
        (bit_to_remove, bit_to_add) = self._update(False)
        self._apply_bit_change(bit_to_remove, bit_to_add)

    def _track_update_move_down_callback(self, _):
        logger.debug('_track_update_move_down_callback() called')
        (bit_to_remove, bit_to_add) = self._update(True)
        self._apply_bit_change(bit_to_remove, bit_to_add)

class _RelationshipTrackData2dLinkArrayElement:
    __qualname__ = '_RelationshipTrackData2dLinkArrayElement'

    def __init__(self, bit_set, min_rel, max_rel):
        self.bit_set = self._build_node_data(bit_set)
        self.min_rel = min_rel
        self.max_rel = max_rel

    def _build_node_data(self, bit_set_nods):
        bit_set_list = []
        if not bit_set_nods:
            return bit_set_list
        bit_set_list = [BitTrackNode(bit_set.bit, bit_set.minimum_value, bit_set.maximum_value) for bit_set in bit_set_nods]
        bit_set_list = SimpleRelationshipTrackData.sort_bit_list(bit_set_list)
        return bit_set_list

class RelationshipTrackData2dLink(BaseRelationshipTrackData):
    __qualname__ = 'RelationshipTrackData2dLink'

    def __init__(self, y_axis_track, y_axis_content):
        super().__init__()
        self.bit_set_list = []
        self._y_axis_track = y_axis_track
        self._raw_y_axis_content = y_axis_content

    def build_track_data(self):
        if self.bit_set_list:
            self.bit_set_list = []
        if not self._raw_y_axis_content:
            return
        temp_list = [_RelationshipTrackData2dLinkArrayElement(y_axis_chunk.bit_set, y_axis_chunk.minimum_value, y_axis_chunk.maximum_value) for y_axis_chunk in self._raw_y_axis_content]
        self.bit_set_list = RelationshipTrackData2dLink.sort_bit_list(temp_list)

    def get_track_instance_data(self, track):
        return RelationshipTrackInstanceData2dLink(track)

    def bit_track_node_gen(self):
        for y_content in self.bit_set_list:
            for x_content in y_content.bit_set:
                yield x_content

    def get_track_mean_list_for_bit(self, bit):
        x_track = None
        y_track = self._y_axis_track
        for y_content in self.bit_set_list:
            for x_content in y_content.bit_set:
                while x_content.bit is bit:
                    x_track = x_content.bit.triggered_track
        x_track_Mean = (x_content.max_rel + x_content.min_rel)*0.5
        y_track_Mean = (y_content.max_rel + y_content.min_rel)*0.5
        track_mean_list = [TrackMean(x_track, x_track_Mean), TrackMean(y_track, y_track_Mean)]
        return track_mean_list

    @classmethod
    def _create_dummy_list_node(cls, min_rel, max_rel):
        return _RelationshipTrackData2dLinkArrayElement(None, min_rel, max_rel)

    @property
    def y_axis_track(self):
        return self._y_axis_track

class TunableRelationshipTrack2dLink(TunableFactory):
    __qualname__ = 'TunableRelationshipTrack2dLink'
    FACTORY_TYPE = RelationshipTrackData2dLink

    def __init__(self, **kwargs):
        super().__init__(y_axis_track=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions='RelationshipTrack', description='The bit track to key the Y axis off of.'), y_axis_content=TunableList(TunableTuple(bit_set=TunableRelationshipBitSet(description='The bit set representing the X axis in the matrix for this Y position.'), minimum_value=Tunable(float, -100, description='Minimum track score value for the bit.'), maximum_value=Tunable(float, 100, description='Maximum track score value for the bit.'), description='A threshold for this node in the matrix along with a bit set.'), description='A list of bit sets and thresholds.  This represents the Y axis of the matrix.'), **kwargs)

class RelationshipTrackInstanceData2dLink(BaseRelationshipTrackInstanceData):
    __qualname__ = 'RelationshipTrackInstanceData2dLink'

    def __init__(self, track):
        super().__init__(track)
        self._x_index = -1
        self._y_index = -1
        self._x_callback_handles = []

    def setup_callbacks(self):
        y_track = self._get_y_track()
        for y_node in self._track_data.bit_set_list:
            threshold = Threshold(y_node.min_rel, operator.gt)
            y_track.tracker.create_and_activate_listener(y_track.stat_type, threshold, self._y_track_update_move_up_callback)
            threshold = Threshold(y_node.max_rel, operator.lt)
            y_track.tracker.create_and_activate_listener(y_track.stat_type, threshold, self._y_track_update_move_down_callback)
        self._y_index = self._get_y_axis_index()
        self._set_x_callbacks()

    def get_active_bit(self):
        if self._y_index < 0 or self._x_index < 0:
            return
        return self._track_data.bit_set_list[self._y_index].bit_set[self._x_index].bit

    def request_full_update(self):
        self._full_y_update()
        self._full_x_update()

    def _get_y_track(self):
        return self._track.tracker.get_statistic(self._track_data.y_axis_track, True)

    def _get_y_axis_index(self):
        track_data = self._track_data
        score = self._track.tracker.get_value(track_data.y_axis_track)
        for (index, bit_set) in enumerate(track_data.bit_set_list):
            while score >= bit_set.min_rel and score <= bit_set.max_rel:
                break
        return index

    def _get_x_bit_set(self):
        if self._y_index < 0:
            return
        return self._track_data.bit_set_list[self._y_index].bit_set

    def _set_x_callbacks(self):
        for handle in self._x_callback_handles:
            self._track.remove_callback(handle)
        self._x_callback_handles = []
        x_bit_set = self._get_x_bit_set()
        if x_bit_set is not None:
            for x_node in x_bit_set:
                threshold = Threshold(x_node.min_rel, operator.gt)
                handle = self._track.tracker.create_and_activate_listener(self._track.stat_type, threshold, self._x_track_update_move_up_callback)
                self._x_callback_handles.append(handle)
                threshold = Threshold(x_node.max_rel, operator.lt)
                handle = self._track.tracker.create_and_activate_listener(self._track.stat_type, threshold, self._x_track_update_move_down_callback)
                self._x_callback_handles.append(handle)
        else:
            logger.error('x_bit_set is None for {}', self._track, owner='rez')

    def _update_y_track(self, moving_down):
        y_track = self._get_y_track()
        track_data = self._track_data
        original_bit = self.get_active_bit()
        if self._y_index < 0:
            return self._full_y_update()
        original_node = track_data.bit_set_list[self._y_index]
        curr_node = original_node
        score = y_track.get_value()
        if moving_down:
            if score - EPSILON <= curr_node.min_rel:
                if self._y_index > 0:
                    curr_node = track_data.bit_set_list[self._y_index]
        elif score + EPSILON >= curr_node.max_rel and self._y_index < len(track_data.bit_set_list) - 1:
            curr_node = track_data.bit_set_list[self._y_index]
        if curr_node == original_node:
            return (None, None)
        self._x_index = -1
        (_, new_bit) = self._full_x_update()
        if new_bit == original_bit:
            return (None, None)
        logger.debug('   Old bit: {}', original_bit)
        logger.debug('   New bit: {}', new_bit)
        return (original_bit, new_bit)

    def _full_y_update(self):
        track_data = self._track_data
        track = self._get_y_track()
        score = track.get_value()
        old_bit = self.get_active_bit()
        for (i, bit_set) in enumerate(track_data.bit_set_list):
            while score >= bit_set.min_rel and score <= bit_set.max_rel:
                self._y_index = i
                break
        self._x_index = -1
        (_, new_bit) = self._full_x_update()
        logger.debug('Old bit: {}', old_bit)
        logger.debug('New bit: {}', new_bit)
        return (old_bit, new_bit)

    def _update_x_track(self, moving_down):
        x_bit_set = self._get_x_bit_set()
        original_bit = self.get_active_bit()
        if self._x_index < 0:
            return self._full_x_update()
        original_node = x_bit_set[self._x_index]
        curr_node = original_node
        score = self._track.get_value()
        if moving_down:
            while score <= curr_node.min_rel:
                if self._x_index == 0:
                    break
                curr_node = x_bit_set[self._x_index]
                continue
        else:
            while score >= curr_node.max_rel:
                if self._x_index == len(x_bit_set) - 1:
                    break
                curr_node = x_bit_set[self._x_index]
        if curr_node == original_node:
            return (None, None)
        new_bit = x_bit_set[self._x_index].bit
        logger.debug('   Old bit: {}', original_bit)
        logger.debug('   New bit: {}', new_bit)
        return (original_bit, new_bit)

    def _full_x_update(self):
        score = self._track.get_value()
        old_bit = self.get_active_bit()
        bit_list = self._get_x_bit_set()
        for (i, bit_set) in enumerate(bit_list):
            while score >= bit_set.min_rel and score <= bit_set.max_rel:
                self._x_index = i
                break
        new_bit = None
        if self._x_index >= 0:
            new_bit = self.get_active_bit()
        else:
            logger.warn("There's a hole in RelationshipTrack: {}", self._track, owner='rez')
        return (old_bit, new_bit)

    def _x_track_update_move_up_callback(self, _):
        (bit_to_remove, bit_to_add) = self._update_x_track(False)
        self._apply_bit_change(bit_to_remove, bit_to_add)

    def _x_track_update_move_down_callback(self, _):
        (bit_to_remove, bit_to_add) = self._update_x_track(True)
        self._apply_bit_change(bit_to_remove, bit_to_add)

    def _y_track_update_move_up_callback(self, _):
        (bit_to_remove, bit_to_add) = self._update_y_track(False)
        self._apply_bit_change(bit_to_remove, bit_to_add)

    def _y_track_update_move_down_callback(self, _):
        (bit_to_remove, bit_to_add) = self._update_y_track(True)
        self._apply_bit_change(bit_to_remove, bit_to_add)

