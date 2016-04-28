import collections
import operator
from event_testing.resolver import DoubleSimResolver
from relationships.tunable import TunableRelationshipBitData, TunableRelationshipTrack2dLink
from sims4.math import Threshold
from sims4.tuning.geometric import TunableVector2, TunableWeightedUtilityCurveAndWeight
from sims4.tuning.instances import HashedTunedInstanceMetaclass, lock_instance_tunables
from sims4.tuning.tunable import TunableVariant, TunableList, TunableReference, TunableRange, HasTunableReference, Tunable, TunableSet, OptionalTunable, TunableTuple, TunableThreshold
from sims4.utils import classproperty
from singletons import DEFAULT
from statistics.continuous_statistic_tuning import TunedContinuousStatistic
import alarms
import date_and_time
import event_testing.tests
import services
import sims4.log
import sims4.resources
import sims4.tuning
import sims
logger = sims4.log.Logger('Relationship', default_owner='rez')

class RelationshipTrack(TunedContinuousStatistic, HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.statistic_manager()):
    __qualname__ = 'RelationshipTrack'
    FRIENDSHIP_TRACK = TunableReference(description='\n        A reference to the friendship track so that the client knows which\n        track is the friendship one.\n        ', manager=services.statistic_manager(), class_restrictions='RelationshipTrack', export_modes=sims4.tuning.tunable_base.ExportModes.All)
    FRIENDSHIP_TRACK_FILTER_THRESHOLD = Tunable(description='\n        Value that the client will use when filtering friendship on the Sim\n        Picker.  Sims that have a track value equal to or above this value will\n        be shown with the friendship filter.\n        ', tunable_type=int, default=0, export_modes=sims4.tuning.tunable_base.ExportModes.All)
    ROMANCE_TRACK = TunableReference(description='\n        A reference to the romance track so that the client knows which\n        track is the romance one.\n        ', manager=services.statistic_manager(), class_restrictions='RelationshipTrack', export_modes=sims4.tuning.tunable_base.ExportModes.All)
    ROMANCE_TRACK_FILTER_THRESHOLD = Tunable(description='\n        Value that the client will use when filtering romance on the Sim\n        Picker.  Sims that have a track value equal to or above this value will\n        be shown with the romance filter.\n        ', tunable_type=int, default=0, export_modes=sims4.tuning.tunable_base.ExportModes.All)
    ROMANCE_TRACK_FILTER_BITS = TunableSet(description='\n        A set of relationship bits that will be used in the Sim Picker for\n        filtering based on romance.  If a Sim has any of these bits then they\n        will be displayed in the Sim Picker when filtering for romance.\n        ', tunable=TunableReference(description='\n                A specific bit used for filtering romance in the Sim Picker.\n                ', manager=services.get_instance_manager(sims4.resources.Types.RELATIONSHIP_BIT)), export_modes=sims4.tuning.tunable_base.ExportModes.All)
    REMOVE_INSTANCE_TUNABLES = ('stat_asm_param', 'persisted_tuning')
    INSTANCE_TUNABLES = {'bit_data_tuning': TunableVariant(bit_set=TunableRelationshipBitData(), _2dMatrix=TunableRelationshipTrack2dLink()), 'ad_data': TunableList(TunableVector2(sims4.math.Vector2(0, 0), description='Point on a Curve'), description='A list of Vector2 points that define the desire curve for this relationship track.'), 'relationship_obj_prefence_curve': TunableWeightedUtilityCurveAndWeight(description="A curve that maps desire of a sim to interact with an object made by a sim of this relation to this relationship's actual score."), '_add_bit_on_threshold': OptionalTunable(description='\n                If enabled, the referenced bit will be added this track reaches the threshold.\n                ', tunable=TunableTuple(description='\n                    The bit & threshold pair.\n                    ', bit=TunableReference(description='\n                        The bit to add.\n                        ', manager=services.get_instance_manager(sims4.resources.Types.RELATIONSHIP_BIT)), threshold=TunableThreshold(description='\n                        The threshold at which to add this bit.\n                        '))), 'display_priority': TunableRange(description='\n                The display priority of this relationship track.  Tracks with a\n                display priority greater than zero will be displayed in\n                ascending order in the UI.  So a relationship track with a\n                display priority of 1 will show above a relationship track\n                with a display priority of 2.  Relationship tracks with the\n                same display priority will show up in potentially\n                non-deterministic ways.  Relationship tracks with display\n                priorities of 0 will not be shown.\n                ', tunable_type=int, default=0, minimum=0, export_modes=sims4.tuning.tunable_base.ExportModes.All), 'display_popup_priority': TunableRange(description='\n                The display popup priority.  This is the priority that the\n                relationship score increases will display. If there are\n                multiple relationship changes at the same time.\n                ', tunable_type=int, default=0, minimum=0, export_modes=sims4.tuning.tunable_base.ExportModes.All), '_neutral_bit': TunableReference(description="\n                The neutral bit for this relationship track.  This is the bit\n                that is displayed when there are holes in the relationship\n                track's bit data.\n                ", manager=services.get_instance_manager(sims4.resources.Types.RELATIONSHIP_BIT)), 'decay_only_affects_selectable_sims': Tunable(description='\n                If this is True, the decay is only enabled if one or both of \n                the sims in the relationship are selectable. \n                ', tunable_type=bool, default=False), 'delay_until_decay_is_applied': OptionalTunable(description='\n                If enabled, the decay for this track will be disabled whenever\n                the value changes by any means other than decay.  It will then \n                be re-enabled after this amount of time (in sim minutes) passes.\n                ', tunable=TunableRange(description='\n                    The amount of time, in sim minutes, that it takes before \n                    decay is enabled.\n                    ', tunable_type=int, default=10, minimum=1)), 'causes_delayed_removal_on_convergence': Tunable(description='\n                If True, this track may cause the relationship to get culled when \n                it reaches convergence.  This is not guaranteed, based on the \n                culling rules.  Sim relationships will NOT be culled if any of \n                the folling conditions are met:\n                - The sim has any relationship bits that are tuned to prevent this.\n                - The Sims are in the same household\n                ', tunable_type=bool, default=False), 'visible_test_set': OptionalTunable(event_testing.tests.TunableTestSet(description='\n                If set , tests whether relationship should be sent to client.\n                If no test given, then as soon as track is added to relationship\n                it will be visible to client.\n                '), disabled_value=DEFAULT, disabled_name='always_visible', enabled_name='run_test')}
    bit_data = None

    def __init__(self, tracker):
        super().__init__(tracker, self.initial_value)
        self._per_instance_data = self.bit_data.get_track_instance_data(self)
        self.visible_to_client = True if self.visible_test_set is DEFAULT else False
        self._decay_alarm_handle = None
        self._convergence_callback_data = None
        self._first_same_sex_relationship_callback_data = None
        self._set_initial_decay()

    @classproperty
    def is_short_term_context(cls):
        return False

    def on_add(self):
        if not self.tracker.suppress_callback_setup_during_load:
            self._per_instance_data.setup_callbacks()
            self.update_instance_data()
        if self._add_bit_on_threshold is not None:
            self.add_callback(self._add_bit_on_threshold.threshold, self._on_add_bit_from_threshold_callback)
        if self._should_initialize_first_same_sex_relationship_callback():
            self._first_same_sex_relationship_callback_data = self.add_callback(Threshold(sims.global_gender_preference_tuning.GlobalGenderPreferenceTuning.ENABLE_AUTOGENERATION_SAME_SEX_PREFERENCE_THRESHOLD, operator.ge), self._first_same_sex_relationship_callback)

    def on_remove(self, on_destroy=False):
        self.remove_callback(self._first_same_sex_relationship_callback_data)
        super().on_remove(on_destroy=on_destroy)
        self._destroy_decay_alarm()

    def get_statistic_multiplier_increase(self):
        sim_info_manager = services.sim_info_manager()
        target_sim_info = sim_info_manager.get(self.tracker.relationship.target_sim_id)
        target_sim_multiplier = 1
        if target_sim_info is not None:
            target_sim_stat = target_sim_info.relationship_tracker.get_relationship_track(self.tracker.relationship.sim_id, track=self.stat_type)
            if target_sim_stat is not None:
                target_sim_multiplier = target_sim_stat._statistic_multiplier_increase
        return self._statistic_multiplier_increase*target_sim_multiplier

    def get_statistic_multiplier_decrease(self):
        sim_info_manager = services.sim_info_manager()
        target_sim_info = sim_info_manager.get(self.tracker.relationship.target_sim_id)
        target_sim_multiplier = 1
        if target_sim_info is not None:
            target_sim_stat = target_sim_info.relationship_tracker.get_relationship_track(self.tracker.relationship.sim_id, track=self.stat_type)
            if target_sim_stat is not None:
                target_sim_multiplier = target_sim_stat._statistic_multiplier_decrease
        return self._statistic_multiplier_decrease*target_sim_multiplier

    def set_value(self, value, *args, **kwargs):
        self._update_value()
        old_value = self._value
        delta = value - old_value
        sim_info = self.tracker.relationship.find_sim_info()
        self.tracker.trigger_test_event(sim_info, event_testing.test_events.TestEvent.PrerelationshipChanged)
        super().set_value(value, *args, **kwargs)
        self._update_visiblity()
        self._reset_decay_alarm()
        self.tracker.relationship.send_relationship_info(deltas={self: delta})
        self.tracker.trigger_test_event(sim_info, event_testing.test_events.TestEvent.RelationshipChanged)

    @property
    def is_visible(self):
        return self.visible_to_client

    def fixup_callbacks_during_load(self):
        super().fixup_callbacks_during_load()
        self._per_instance_data.setup_callbacks()

    def update_instance_data(self):
        self._per_instance_data.request_full_update()

    def apply_social_group_decay(self):
        pass

    def remove_social_group_decay(self):
        pass

    def _on_statistic_modifier_changed(self, notify_watcher=True):
        super()._on_statistic_modifier_changed(notify_watcher=notify_watcher)
        if self._statistic_modifier == 0:
            self._reset_decay_alarm()
        self.tracker.relationship.send_relationship_info()

    def _update_visiblity(self):
        if not self.visible_to_client:
            sim_info_manager = services.sim_info_manager()
            actor_sim_info = sim_info_manager.get(self.tracker.relationship.sim_id)
            if actor_sim_info is None:
                return
            target_sim_info = sim_info_manager.get(self.tracker.relationship.target_sim_id)
            if target_sim_info is None:
                return
            resolver = DoubleSimResolver(actor_sim_info, target_sim_info)
            self.visible_to_client = True if self.visible_test_set.run_tests(resolver) else False

    @classmethod
    def _tuning_loaded_callback(cls):
        super()._tuning_loaded_callback()
        cls.bit_data = cls.bit_data_tuning()
        cls.bit_data.build_track_data()
        cls._build_utility_curve_from_tuning_data(cls.ad_data)

    @classmethod
    def _verify_tuning_callback(cls):
        if cls._neutral_bit is None:
            logger.error('No Neutral Bit tuned for Relationship Track: {}', cls)

    @staticmethod
    def check_relationship_track_display_priorities(statistic_manager):
        if not __debug__:
            return
        relationship_track_display_priority = collections.defaultdict(list)
        for statistic in statistic_manager.types.values():
            if not issubclass(statistic, RelationshipTrack):
                pass
            if statistic.display_priority == 0:
                pass
            relationship_track_display_priority[statistic.display_priority].append(statistic)
        for relationship_priority_level in relationship_track_display_priority.values():
            if len(relationship_priority_level) <= 1:
                pass
            logger.warn('Multiple Relationship Tracks have the same display priority: {}', relationship_priority_level)

    @classmethod
    def type_id(cls):
        return cls.guid64

    @classmethod
    def get_bit_track_node_for_bit(cls, relationship_bit):
        for node in cls.bit_data.bit_track_node_gen():
            while node.bit is relationship_bit:
                return node

    @classmethod
    def bit_track_node_gen(cls):
        for node in cls.bit_data.bit_track_node_gen():
            yield node

    @classmethod
    def get_bit_at_relationship_value(cls, value):
        for bit_node in reversed(tuple(cls.bit_track_node_gen())):
            while bit_node.min_rel <= value <= bit_node.max_rel:
                return bit_node.bit or cls._neutral_bit
        return cls._neutral_bit

    @classproperty
    def persisted(cls):
        return True

    def get_active_bit(self):
        return self._per_instance_data.get_active_bit()

    def get_bit_for_client(self):
        active_bit = self.get_active_bit()
        if active_bit is None:
            return self._neutral_bit
        return active_bit

    def _set_initial_decay(self):
        if self._should_decay():
            self.decay_enabled = True
        self._convergence_callback_data = self.add_callback(Threshold(self.convergence_value, operator.eq), self._on_convergence_callback)
        logger.debug('Setting decay on track {} to {} for {}', self, self.decay_enabled, self.tracker.relationship)

    def _should_decay(self):
        if self.decay_rate == 0:
            return False
        if self.decay_only_affects_selectable_sims:
            sim_info = self.tracker.relationship.find_sim_info()
            target_sim_info = self.tracker.relationship.find_target_sim_info()
            if sim_info is None or target_sim_info is None:
                return False
            if sim_info.is_selectable or target_sim_info.is_selectable:
                return True
        else:
            return True
        return False

    def _reset_decay_alarm(self):
        self._destroy_decay_alarm()
        if self._should_decay() and self.delay_until_decay_is_applied is not None:
            logger.debug('Resetting decay alarm for track {} for {}.', self, self.tracker.relationship)
            delay_time_span = date_and_time.create_time_span(minutes=self.delay_until_decay_is_applied)
            self._decay_alarm_handle = alarms.add_alarm(self, delay_time_span, self._decay_alarm_callback)
            self.decay_enabled = False

    def _decay_alarm_callback(self, handle):
        logger.debug('Decay alarm triggered on track {} for {}.', self, self.tracker.relationship)
        self._destroy_decay_alarm()
        self.decay_enabled = True

    def _destroy_decay_alarm(self):
        if self._decay_alarm_handle is not None:
            alarms.cancel_alarm(self._decay_alarm_handle)
            self._decay_alarm_handle = None

    def _on_convergence_callback(self, _):
        logger.debug('Track {} reached convergence; rel might get culled for {}', self, self.tracker.relationship)
        self.tracker.relationship.track_reached_convergence(self)

    def _on_add_bit_from_threshold_callback(self, _):
        logger.debug('Track {} is adding its extra bit: {}'.format(self, self._add_bit_on_threshold.bit))
        self.tracker.relationship.add_bit(self._add_bit_on_threshold.bit)

    def _should_initialize_first_same_sex_relationship_callback(self):
        if self.stat_type is not self.ROMANCE_TRACK:
            return False
        if sims.global_gender_preference_tuning.GlobalGenderPreferenceTuning.enable_autogeneration_same_sex_preference:
            return False
        sim_info_a = self.tracker.relationship.find_sim_info()
        sim_info_b = self.tracker.relationship.find_target_sim_info()
        if sim_info_a is None or sim_info_b is None:
            return False
        if sim_info_a.gender is not sim_info_b.gender:
            return False
        if sim_info_a.is_npc and sim_info_b.is_npc:
            return False
        return True

    def _first_same_sex_relationship_callback(self, _):
        sims.global_gender_preference_tuning.GlobalGenderPreferenceTuning.enable_autogeneration_same_sex_preference = True
        self.remove_callback(self._first_same_sex_relationship_callback_data)

services.get_instance_manager(sims4.resources.Types.STATISTIC).add_on_load_complete(RelationshipTrack.check_relationship_track_display_priorities)

class ShortTermContextRelationshipTrack(RelationshipTrack):
    __qualname__ = 'ShortTermContextRelationshipTrack'
    INSTANCE_TUNABLES = {'socialization_decay_modifier': TunableRange(description='\n            A multiplier to apply to the decay rate if the two Sims that this\n            relationship track applies to are socializing.\n            ', tunable_type=float, default=1, minimum=0)}

    @classproperty
    def is_short_term_context(cls):
        return True

    def on_add(self):
        super().on_add()
        sim = self.tracker.relationship.find_sim()
        target = self.tracker.relationship.find_target_sim()
        if sim is not None and target is not None and sim.is_in_group_with(target):
            self.apply_social_group_decay()

    def apply_social_group_decay(self):
        if self.socialization_decay_modifier != 1:
            self.add_decay_rate_modifier(self.socialization_decay_modifier)

    def remove_social_group_decay(self):
        if self.socialization_decay_modifier != 1:
            self.remove_decay_rate_modifier(self.socialization_decay_modifier)

lock_instance_tunables(ShortTermContextRelationshipTrack, visible_test_set=DEFAULT)
