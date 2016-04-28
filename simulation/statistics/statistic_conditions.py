import math
import operator
from date_and_time import TimeSpan, MINUTES_PER_HOUR
from event_testing.test_events import TestEvent
from interactions import ParticipantType, ParticipantTypeActorTargetSim
from objects.components.state import TunableStateValueReference, CommodityBasedObjectStateValue, ObjectStateMetaclass
from sims4.repr_utils import standard_repr
from sims4.tuning.tunable import Tunable, TunableEnumEntry, TunableVariant, TunableReference, TunableThreshold, TunableFactory, TunableTuple, TunableSimMinute, HasTunableFactory, AutoFactoryInit
from statistics.mood import Mood
import alarms
import clock
import date_and_time
import enum
import services
import sims4.log
import sims4.math
logger = sims4.log.Logger('Condition')

class Condition:
    __qualname__ = 'Condition'
    __slots__ = ('_satisfied', '_handle', '_owner', 'si_callback')

    def __init__(self, exit_action=None, interaction=None, situation=None):
        self._satisfied = False
        self._handle = None
        self._owner = None
        self.si_callback = None

    def _satisfy(self, *_):
        if not self._satisfied:
            self._satisfied = True
            if not self.si_callback:
                logger.callstack('Condition is missing si_callback: {}', self, level=sims4.log.LEVEL_ERROR, owner='tingyul')
                return
            self.si_callback(self._handle)

    def _unsatisfy(self, *_):
        self._satisfied = False

    @property
    def satisfied(self):
        return self._satisfied

    def attach_to_owner(self, owner, callback):
        raise NotImplementedError

    def detach_from_owner(self, owner, exiting=False):
        raise NotImplementedError

    def get_time_until_satisfy(self, interaction):
        return (None, None, None)

    def _get_target_and_tracker(self, interaction, participant, stat):
        target = interaction.get_participant(participant)
        if target is None:
            return (None, None)
        return (target, target.get_tracker(stat))

    def get_time_for_stat_satisfaction(self, interaction, subject, linked_stat, state_range):
        (target, tracker) = self._get_target_and_tracker(interaction, subject, linked_stat)
        if target is None or tracker is None:
            return (None, None, None)
        override_min_max_stats = interaction.progress_bar_enabled.override_min_max_values
        blacklist_statistics = interaction.progress_bar_enabled.blacklist_statistics
        best_time = None
        best_percent = None
        best_rate_of_change = None
        if tracker is not None:
            current_value = tracker.get_user_value(linked_stat)
            stat_op_list = interaction.instance_statistic_operations_gen()
            for stat_op in stat_op_list:
                while stat_op.stat is linked_stat:
                    if not stat_op.test_resolver(interaction.get_resolver()):
                        pass
                    if blacklist_statistics and linked_stat in blacklist_statistics:
                        return (None, None, None)
                    if override_min_max_stats is not None and override_min_max_stats.statistic is stat_op.stat:
                        override_stat_values = True
                    else:
                        override_stat_values = False
                    stat_instance = tracker.get_statistic(stat_op.stat)
                    if stat_instance is None:
                        pass
                    if stat_instance.continuous:
                        rate_change = stat_instance.get_change_rate()
                    else:
                        interval = stat_op._get_interval(interaction)
                        if not interval:
                            pass
                        rate_change = stat_op.get_value()/interval
                    if rate_change > 0:
                        if state_range is not None:
                            upper_bound = state_range.lower_bound
                        else:
                            upper_bound = self.threshold.value
                        lower_bound = linked_stat.min_value
                    else:
                        if state_range is not None:
                            lower_bound = state_range.upper_bound
                        else:
                            lower_bound = self.threshold.value
                        upper_bound = linked_stat.max_value
                    if override_min_max_stats.min_value is not None:
                        lower_bound = override_min_max_stats.min_value
                    if override_stat_values and override_min_max_stats.max_value is not None:
                        upper_bound = override_min_max_stats.max_value
                    if rate_change > 0:
                        threshold = upper_bound
                        denominator = threshold - lower_bound
                        percent = abs((current_value - lower_bound)/denominator) if denominator else 0
                    else:
                        threshold = lower_bound
                        denominator = threshold - upper_bound
                        percent = abs((current_value + denominator)/denominator) if denominator else 0
                    while not not rate_change:
                        if not denominator:
                            pass
                        time = (threshold - current_value)/rate_change
                        rate_of_change = abs((1 - percent)/time if time != 0 else 0)
                        if best_time is None or time < best_time:
                            best_time = time
                            best_percent = percent
                            best_rate_of_change = rate_of_change
        return (best_time, best_percent, best_rate_of_change)

class StatisticCondition(Condition):
    __qualname__ = 'StatisticCondition'
    __slots__ = ('who', 'stat', 'threshold', 'absolute', '_unsatisfy_handle')

    def __init__(self, who=None, stat=None, threshold=None, absolute=False, **kwargs):
        super().__init__(**kwargs)
        self.who = who
        self.stat = stat
        self.threshold = threshold
        self.absolute = absolute
        self._unsatisfy_handle = None

    def __str__(self):
        return standard_repr(self, '{}.{} {}'.format(self.who.name, self.stat.__name__, self.threshold))

    def create_threshold(self, tracker):
        threshold = sims4.math.Threshold()
        threshold.comparison = self.threshold.comparison
        if self.absolute:
            cur_val = 0
        else:
            cur_val = tracker.get_value(self.stat, add=True)
        if self.threshold.comparison is operator.ge:
            pass
        if self.absolute or self.threshold.comparison is operator.le:
            pass
        if self.threshold.comparison is operator.ge:
            threshold.value = min([cur_val + self.threshold.value, self.stat.max_value])
        elif self.threshold.comparison is operator.le:
            threshold.value = max([cur_val + self.threshold.value, self.stat.min_value])
        else:
            raise NotImplementedError
        return threshold

    def attach_to_owner(self, owner, callback):
        self._owner = owner
        self.si_callback = callback
        (_, tracker) = self._get_target_and_tracker(owner, self.who, self.stat)
        if tracker is None:
            self._satisfy()
            return (None, None)
        threshold = self.create_threshold(tracker)
        value = tracker.get_value(self.stat)
        if threshold.compare(value):
            self._satisfy()
        self._handle = tracker.create_and_activate_listener(self.stat, threshold, self._satisfy)
        self._unsatisfy_handle = tracker.create_and_activate_listener(self.stat, threshold.inverse(), self._unsatisfy)
        return (None, None)

    def detach_from_owner(self, owner, exiting=False):
        (_, tracker) = self._get_target_and_tracker(owner, self.who, self.stat)
        if tracker is None:
            return
        tracker.remove_listener(self._handle)
        tracker.remove_listener(self._unsatisfy_handle)
        self._owner = None
        self.si_callback = None

    def get_time_until_satisfy(self, interaction):
        return self.get_time_for_stat_satisfaction(interaction, self.who, self.stat, None)

class StateCondition(Condition):
    __qualname__ = 'StateCondition'

    def __init__(self, subject, state, **kwargs):
        super().__init__(**kwargs)
        self._subject = subject
        self._state = state

    def __str__(self):
        return 'State {} on {}'.format(self._state, self._subject)

    def _on_owner_state_changed(self, owner, state, old_value, new_value):
        if state is self._state.state and self._state is new_value:
            self._satisfy(None)

    def attach_to_owner(self, owner, callback):
        subject = owner.get_participant(self._subject)
        if subject is not None and subject.state_component:
            self.si_callback = callback
            subject.add_state_changed_callback(self._on_owner_state_changed)
        return (None, None)

    def detach_from_owner(self, owner, **kwargs):
        subject = owner.get_participant(self._subject)
        if subject is not None and subject.state_component:
            subject.remove_state_changed_callback(self._on_owner_state_changed)

    def get_time_until_satisfy(self, interaction):
        if self._state.state.linked_stat is None:
            return (None, None, None)
        return self.get_time_for_stat_satisfaction(interaction, self._subject, self._state.state.linked_stat, self._state.range)

class TimeBasedCondition(Condition):
    __qualname__ = 'TimeBasedCondition'
    __slots__ = '_interval'

    def __init__(self, interval_in_sim_minutes, **kwargs):
        super().__init__(**kwargs)
        self._interval = interval_in_sim_minutes

    def __str__(self):
        return 'Time Interval: {}'.format(self._interval)

    def attach_to_owner(self, owner, callback):
        self.si_callback = callback
        self._owner = owner
        time_span = clock.interval_in_sim_minutes(self._interval)
        self._handle = alarms.add_alarm(owner.sim, time_span, self._satisfy)
        return (None, self._handle)

    def detach_from_owner(self, _, exiting=False):
        alarms.cancel_alarm(self._handle)

    def get_time_until_satisfy(self, interaction):
        rounded_interval = math.floor(self._interval)
        if self._satisfied:
            remaining_time = 0
        else:
            remaining_time = math.floor(self._handle.get_remaining_time().in_minutes())
        percent_done = (rounded_interval - remaining_time)/rounded_interval
        change_rate = 0
        if self._interval != 0:
            change_rate = 1/self._interval
        return (self._interval, percent_done, change_rate)

class EventBasedCondition(Condition):
    __qualname__ = 'EventBasedCondition'
    __slots__ = '_event_type'

    def __init__(self, event_type, **kwargs):
        super().__init__(**kwargs)
        self._event_type = event_type

    def __str__(self):
        return 'Event {}'.format(self._event_type)

    def attach_to_owner(self, owner, callback):
        self._owner = owner
        self.si_callback = callback
        self._handle = services.get_event_manager().register(self, (self._event_type,))
        return (None, self._handle)

    def handle_event(self, sim_info, event, resolver):
        self._satisfy(event)

    def detach_from_owner(self, _, exiting=False):
        services.get_event_manager().unregister(self, (self._event_type,))

class InUseCondition(HasTunableFactory, AutoFactoryInit, Condition):
    __qualname__ = 'InUseCondition'
    FACTORY_TUNABLES = {'description': '\n            A condition that is satisfied when an object is no longer in use,\n            optionally specifying an affordance that the user of the object must\n            be running.\n            ', 'participant': TunableEnumEntry(description='\n            The participant of the interaction used to fetch the users against\n            which the condition test is run.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'affordance': TunableReference(description='\n            If specified, then the condition is satisfied if no user of the\n            specified object is running this affordance.\n            ', manager=services.affordance_manager(), class_restrictions='SuperInteraction')}

    def __str__(self):
        return 'In Use: {}'.format(self.affordance)

    def _get_use_list_obj(self):
        obj = self._owner.get_participant(self.participant)
        if obj.is_part:
            obj = obj.part_owner
        return obj

    def _on_use_list_changed(self, **kwargs):
        obj = self._get_use_list_obj()
        if obj is not None:
            if not (self.affordance is None and obj.in_use):
                self._satisfy(None)
            for user in obj.get_users(sims_only=True):
                for si in user.si_state:
                    while si.get_interaction_type() is self.affordance:
                        return
        self._satisfy(None)

    def attach_to_owner(self, owner, callback):
        self.si_callback = callback
        self._owner = owner
        obj = self._get_use_list_obj()
        if obj is not None:
            obj.register_on_use_list_changed(self._on_use_list_changed)
        return (None, None)

    def detach_from_owner(self, *_, **__):
        obj = self._get_use_list_obj()
        if obj is not None:
            obj.unregister_on_use_list_changed(self._on_use_list_changed)

class GroupBasedCondition(Condition, HasTunableFactory):
    __qualname__ = 'GroupBasedCondition'
    FACTORY_TUNABLES = {'threshold': TunableThreshold(description='Threshold tested against group size.')}

    def __init__(self, threshold, **kwargs):
        super().__init__(**kwargs)
        self._threshold = threshold
        self._social_group = None
        self._previously_satisfied = self._threshold.compare(0)

    def __str__(self):
        return 'Group Threshold: {}'.format(self._threshold)

    def _group_changed(self, group):
        if self._threshold.compare(group.get_active_sim_count()):
            self._previously_satisfied = True
            self._satisfy()
        else:
            self._previously_satisfied = False

    def attach_to_owner(self, owner, callback):
        self.si_callback = callback
        self._owner = owner
        social_group_owner = owner.super_interaction
        self._social_group = social_group_owner.social_group
        self._social_group.on_group_changed.append(self._group_changed)
        self._group_changed(self._social_group)
        return (None, None)

    def detach_from_owner(self, *_, **__):
        if self._social_group is not None and self._group_changed in self._social_group.on_group_changed:
            self._social_group.on_group_changed.remove(self._group_changed)

class TunableCondition(TunableVariant):
    __qualname__ = 'TunableCondition'

    def __init__(self, *args, **kwargs):
        super().__init__(stat_based=TunableStatisticCondition(description='A condition based on the status of a statistic.'), state_based=TunableStateCondition(description='A condition based on the state of an object.'), time_based=TunableTimeRangeCondition(description='The minimum and maximum amount of time required to satisfy this condition.'), event_based=TunableEventBasedCondition(description='A condition that is satisfied by some event'), career_based=TunableCareerCondition(description='A condition that is satisfied by career data'), wakeup_time_based=TunableWakeupCondition(description='A condition that is satisfied by being close to the schedule time for the sims career'), sim_spawn_based=TunableSimSpawnCondition(description='A condition that is satisfied when a Sim spawns in the world.'), group_based=GroupBasedCondition.TunableFactory(), in_use_based=InUseCondition.TunableFactory(), mood_based=MoodBasedCondition.TunableFactory(), object_relationship_based=ObjectRelationshipCondition.TunableFactory(), buff_based=BuffCondition.TunableFactory(), default='stat_based', *args, **kwargs)

class TunableTimeRangeCondition(TunableFactory):
    __qualname__ = 'TunableTimeRangeCondition'

    @staticmethod
    def factory(min_time, max_time, interaction=None, **kwargs):
        import random
        if min_time is None:
            time_in_sim_minutes = max_time
        elif max_time is None:
            time_in_sim_minutes = min_time
        elif min_time == max_time:
            time_in_sim_minutes = min_time
        else:
            time_in_sim_minutes = random.uniform(min_time, max_time)
        return TimeBasedCondition(time_in_sim_minutes, interaction=interaction, **kwargs)

    @staticmethod
    def _on_tunable_loaded_callback(cls, fields, source, *, min_time, max_time):
        pass

    FACTORY_TYPE = factory

    def __init__(self, description='A time range in Sim minutes for this condition to be satisfied.', **kwargs):
        super().__init__(description=description, callback=self._on_tunable_loaded_callback, min_time=TunableSimMinute(description='\n                             Minimum amount of time (in sim minutes) for this condition to be satisfied.\n                             ', default=1), max_time=TunableSimMinute(description='\n                             Maximum amount of time (in sim minutes) for this condition to be satisfied.\n                             ', default=None), **kwargs)

class TunableStatisticCondition(TunableFactory):
    __qualname__ = 'TunableStatisticCondition'
    FACTORY_TYPE = StatisticCondition

    def __init__(self, description='Apply an operation to a statistic.', **kwargs):
        super().__init__(who=TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), stat=TunableReference(services.statistic_manager(), description='The commodity we are gaining.'), threshold=TunableThreshold(description='A commodity value and comparison that defines the exit condition hits (or hit commodity.maximum).'), absolute=Tunable(bool, True, needs_tuning=True, description="True = treat the threshold value as an absolute commodity value.  Otherwise, it is relative to the Sim's start value."), **kwargs)

class TunableStateCondition(TunableFactory):
    __qualname__ = 'TunableStateCondition'

    @staticmethod
    def factory(subject, state, **kwargs):
        if isinstance(state, ObjectStateMetaclass):
            return StateCondition(subject, state, **kwargs)
        linked_stat = state['state'].state.linked_stat
        if state['boundary']:
            threshold = sims4.math.Threshold(state['state'].range.upper_bound, operator.ge)
        else:
            threshold = sims4.math.Threshold(state['state'].range.lower_bound, operator.le)
        return StatisticCondition(subject, linked_stat, threshold, absolute=True)

    FACTORY_TYPE = factory

    def __init__(self, description='A condition to determine if an object is in a particular state.', **kwargs):
        super().__init__(subject=TunableEnumEntry(ParticipantType, ParticipantType.Object, description='The subject to check the condition on.'), state=TunableVariant(description='The state to check for.', on_trigger=TunableStateValueReference(description='Satisfy the condition when this state is triggered.'), on_boundary=TunableTuple(description='Satisfy the condition when a boundary of this stat-based state is reached', state=TunableStateValueReference(class_restrictions=CommodityBasedObjectStateValue, description='The state required to satisfy the condition'), boundary=TunableVariant(description='The boundary required to be reached for the condition to be satisfied.', locked_args={'upper': True, 'lower': False}, default='upper')), default='on_trigger'), **kwargs)

class TunableEventBasedCondition(TunableFactory):
    __qualname__ = 'TunableEventBasedCondition'

    @staticmethod
    def factory(event_to_listen_for, **kwargs):
        return EventBasedCondition(event_to_listen_for, **kwargs)

    FACTORY_TYPE = factory

    def __init__(self, description='A condition that is satisfied by some event', **kwargs):
        super().__init__(description=description, event_to_listen_for=TunableEnumEntry(TestEvent, TestEvent.Invalid, description='Event that this exit condition should listen for '), **kwargs)

class TunableCareerCondition(TunableFactory):
    __qualname__ = 'TunableCareerCondition'

    @staticmethod
    def factory(*args, **kwargs):
        return CareerCondition(*args, **kwargs)

    FACTORY_TYPE = factory

    def __init__(self, description='A Career Condition to cause an interaction to exit.', **kwargs):
        super().__init__(description=description, who=TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), **kwargs)

class CareerCondition(Condition):
    __qualname__ = 'CareerCondition'
    __slots__ = 'who'

    def __init__(self, who=None, **kwargs):
        super().__init__(**kwargs)
        self.who = who

    def __str__(self):
        return 'Career: {}'.format(self.who)

    def attach_to_owner(self, owner, callback):
        self.si_callback = callback
        career = self._get_target_career(owner)
        time_to_work_end = career.time_until_end_of_work()
        self._handle = alarms.add_alarm(owner.sim, time_to_work_end, self._satisfy)
        return (None, self._handle)

    def detach_from_owner(self, owner, exiting=False):
        alarms.cancel_alarm(self._handle)

    def _get_target_career(self, interaction, exiting=False):
        target_sim = interaction.get_participant(self.who)
        if exiting and target_sim is None:
            return
        target_career = interaction.get_career()
        return target_career

    def get_time_until_satisfy(self, interaction):
        career = self._get_target_career(interaction)
        if career is None:
            logger.error('Progress bar calculating for a condition with a non existing career for interaction {}.', interaction, owner='camilogarcia')
            return (None, None, None)
        time_to_work_end = career.time_until_end_of_work().in_minutes()
        time_worked = career.get_hours_worked()*MINUTES_PER_HOUR
        total_time = time_worked + time_to_work_end
        if total_time == 0:
            return (None, None, None)
        percentage_done = time_worked/total_time
        rate = 1/total_time
        return (time_to_work_end, percentage_done, rate)

class TunableWakeupCondition(TunableFactory):
    __qualname__ = 'TunableWakeupCondition'

    @staticmethod
    def factory(*args, **kwargs):
        return WakeupCondition(*args, **kwargs)

    FACTORY_TYPE = factory

    def __init__(self, description='A Tunable Condition that takes into account when the Sim needs to be up for their work schedule.', **kwargs):
        super().__init__(description=description, who=TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='Who or what to apply this test to'), hours_prior_to_schedule_start=Tunable(float, 0, description='The number of hours prior to the schedule start to satisfy this condition.'), **kwargs)

class WakeupCondition(TimeBasedCondition):
    __qualname__ = 'WakeupCondition'

    def __init__(self, who=None, hours_prior_to_schedule_start=0, **kwargs):
        super().__init__(0, **kwargs)
        self.who = who
        self.hours_prior_to_schedule_start = hours_prior_to_schedule_start

    def __str__(self):
        return 'Wakeup: {}, {} hours before schedule'.format(self.who, self.hours_prior_to_schedule_start)

    def attach_to_owner(self, owner, callback):
        sim = owner.get_participant(self.who)
        if sim is None:
            return
        offset_time = date_and_time.create_time_span(hours=self.hours_prior_to_schedule_start)
        time_span_until_work_start_time = sim.get_time_until_next_wakeup(offset_time=offset_time)
        if time_span_until_work_start_time.in_ticks() <= 0:
            logger.error('Wakeup time is in the past.', owner='rez')
            time_span_until_work_start_time += date_and_time.create_time_span(days=1)
        self._interval = time_span_until_work_start_time.in_minutes()
        return super().attach_to_owner(owner, callback)

class SimSpawnCondition(Condition):
    __qualname__ = 'SimSpawnCondition'

    def __init__(self, participant_type=None, **kwargs):
        super().__init__(**kwargs)
        self._participant_type = participant_type
        self._sim_id = None

    def __str__(self):
        return 'Sim Spawn: {}'.format(self._sim_id)

    def attach_to_owner(self, owner, callback):
        self.si_callback = callback
        self._sim_id = owner.get_participant(self._participant_type)
        if self._sim_id is not None and isinstance(self._sim_id, int):
            object_manager = services.object_manager()
            object_manager.add_sim_spawn_condition(self._sim_id, self._satisfy)
        else:
            logger.error('SimSpawnCondition: invalid sim id found {} with participant type {}', self._sim_id, self._participant_type)
        return (None, None)

    def detach_from_owner(self, owner, exiting=False):
        if self._sim_id is not None and isinstance(self._sim_id, int):
            object_manager = services.object_manager()
            object_manager.remove_sim_spawn_condition(self._sim_id, self._satisfy)
        else:
            logger.error('SimSpawnCondition: invalid sim id found {} with participant type {}', self._sim_id, self._participant_type)

class TunableSimSpawnCondition(TunableFactory):
    __qualname__ = 'TunableSimSpawnCondition'

    @staticmethod
    def factory(*args, **kwargs):
        return SimSpawnCondition(*args, **kwargs)

    FACTORY_TYPE = factory

    def __init__(self, description='A Sim spawning Condition to cause an interaction to exit.', **kwargs):
        super().__init__(description=description, participant_type=TunableEnumEntry(ParticipantType, ParticipantType.PickedItemId, description='Who or what to apply this test to'), **kwargs)

class MoodBasedCondition(HasTunableFactory, AutoFactoryInit, Condition):
    __qualname__ = 'MoodBasedCondition'
    FACTORY_TUNABLES = {'description': '\n            A condition that is satisfied when a Sim enters a specific mood.\n            ', 'participant': TunableEnumEntry(description="\n            The Sim whose mood we're checking against.\n            ", tunable_type=ParticipantType, default=ParticipantType.Actor), 'mood': Mood.TunableReference(description='\n            The mood that satisfies the condition.\n            ', needs_tuning=True), 'invert': Tunable(description='\n            If enabled, this condition will satisfy when the Sim is not in this\n            mood.\n            ', tunable_type=bool, default=False)}

    def __str__(self):
        if self.invert:
            return 'Not in Mood: {}'.format(self.mood)
        return 'Mood: {}'.format(self.mood)

    def _on_mood_changed(self):
        sim = self._owner.get_participant(self.participant)
        if sim is None:
            logger.error('MoodBasedCondition: Failed to find Sim for participant {} in {}', self.participant, self._owner)
            return
        in_mood = sim.get_mood() is self.mood
        if in_mood == self.invert:
            self._unsatisfy()
        else:
            self._satisfy()

    def attach_to_owner(self, owner, callback):
        self.si_callback = callback
        self._owner = owner
        sim = owner.get_participant(self.participant)
        sim.Buffs.on_mood_changed.append(self._on_mood_changed)
        self._on_mood_changed()
        return (None, None)

    def detach_from_owner(self, owner, exiting=False):
        sim = owner.get_participant(self.participant)
        if sim is not None and self._on_mood_changed in sim.Buffs.on_mood_changed:
            sim.Buffs.on_mood_changed.remove(self._on_mood_changed)

class ObjectRelationshipCondition(HasTunableFactory, AutoFactoryInit, Condition):
    __qualname__ = 'ObjectRelationshipCondition'
    FACTORY_TUNABLES = {'description': '\n            A condition that is satisfied when a Sim reaches a specific object\n            relationship threshold.\n            ', 'sim': TunableEnumEntry(description="\n            The Sim whose object relationship we're checking.\n            ", tunable_type=ParticipantType, default=ParticipantType.Actor), 'object': TunableEnumEntry(description="\n            The object whose object relationship we're checking.\n            ", tunable_type=ParticipantType, default=ParticipantType.Object), 'threshold': TunableThreshold(description='\n            The relationship threshold that will trigger this condition.\n            ')}

    def __init__(self, interaction=None, **kwargs):
        super().__init__(**kwargs)
        self._interaction = interaction

    def __str__(self):
        return 'Object Relationship: {} {}'.format(self.threshold.comparison, self.threshold.value)

    def _on_relationship_changed(self):
        sim = self._owner.get_participant(self.sim)
        obj = self._owner.get_participant(self.object)
        relationship_value = obj.objectrelationship_component.get_relationship_value(sim.id)
        if relationship_value is not None and self.threshold.compare(relationship_value):
            self._satisfy()
            if self._interaction:
                self._interaction._send_progress_bar_update_msg(1, 0, self._owner)
        if not self._satisfied and self._interaction:
            initial_value = obj.objectrelationship_component.get_relationship_initial_value()
            denominator = self.threshold.value - initial_value
            if denominator != 0:
                rate_change = relationship_value - initial_value/self.threshold.value - initial_value
                self._owner._send_progress_bar_update_msg(rate_change/100, 0, self._owner)

    def attach_to_owner(self, owner, callback):
        self.si_callback = callback
        self._owner = owner
        sim = owner.get_participant(self.sim)
        obj = self._owner.get_participant(self.object)
        if sim is None:
            logger.error('Trying to add a condition for {} to test object relationship, but the                           ParticipantType {} tuned for Sim is not valid.', self._owner, sim, owner='tastle')
        elif obj is None:
            logger.error('Trying to add a condition for {} to test object relationship, but the                           ParticipantType {} tuned for Object is not valid.', self._owner, obj, owner='tastle')
        elif obj.objectrelationship_component is None:
            logger.error('Trying to add a condition on interaction {} to test object relationship, but                           {} has no object relationship component.', self._owner, obj, owner='tastle')
        else:
            obj.objectrelationship_component.add_relationship_changed_callback_for_sim_id(sim.sim_id, self._on_relationship_changed)
            self._on_relationship_changed()
        return (None, None)

    def detach_from_owner(self, owner, exiting=False):
        sim = owner.get_participant(self.sim)
        obj = self._owner.get_participant(self.object)
        if sim is None or obj is None:
            return
        if obj.objectrelationship_component is not None:
            obj.objectrelationship_component.remove_relationship_changed_callback_for_sim_id(sim.sim_id, self._on_relationship_changed)

class BuffCondition(HasTunableFactory, AutoFactoryInit, Condition):
    __qualname__ = 'BuffCondition'

    class Timing(enum.Int):
        __qualname__ = 'BuffCondition.Timing'
        ON_ADD = 0
        ON_REMOVE = 1
        HAS_BUFF = 2
        NOT_HAS_BUFF = 3

    FACTORY_TUNABLES = {'description': '\n            A condition that is satisfied when a Sim gains or loses a buff.\n            ', 'participant': TunableEnumEntry(description="\n            The participant whose buffs we're checking.\n            ", tunable_type=ParticipantTypeActorTargetSim, default=ParticipantTypeActorTargetSim.Actor), 'buff': TunableReference(description="\n            The buff we're checking.\n            ", manager=services.buff_manager()), 'timing': TunableEnumEntry(description='\n            When the condition satisfies.\n            Choices:\n            ON_ADD: Only check the condition on the edge of the buff being\n            added.  This will not satisfy if you have the buff when the\n            interaction starts.\n            ON_REMOVE: Only check the condition on the edge of the buff being\n            removed.  This will not satisfy if you do not have the buff when\n            the interaction starts.\n            HAS_BUFF: Check for the buff existing at any time this condition\n            is active.  This will satisfy if you have the buff when the\n            interaction starts.\n            NOT_HAS_BUFF: Check for the buff not existing at any time this\n            condition is active.  This will satisfy if you do not have the buff\n            when the interaction starts.\n            ', tunable_type=Timing, default=Timing.ON_ADD)}

    def __str__(self):
        return 'BuffCondition: {} {} {}'.format(self.participant, self.buff, self.timing)

    def attach_to_owner(self, owner, callback):
        self.si_callback = callback
        self._owner = owner
        sim = self._owner.get_participant(self.participant)
        if self.timing == BuffCondition.Timing.HAS_BUFF:
            if sim.has_buff(self.buff):
                self._satisfy()
        elif not (self.timing == BuffCondition.Timing.NOT_HAS_BUFF and sim.has_buff(self.buff)):
            self._satisfy()
        self._enable_buff_watcher()
        return (None, None)

    def detach_from_owner(self, owner, exiting=False):
        self._disable_buff_watcher()

    def _enable_buff_watcher(self):
        sim = self._owner.get_participant(self.participant)
        sim.Buffs.on_buff_added.append(self._on_buff_added)
        sim.Buffs.on_buff_removed.append(self._on_buff_removed)

    def _disable_buff_watcher(self):
        sim = self._owner.get_participant(self.participant)
        if self._on_buff_added in sim.Buffs.on_buff_added:
            sim.Buffs.on_buff_added.remove(self._on_buff_added)
        if self._on_buff_removed in sim.Buffs.on_buff_removed:
            sim.Buffs.on_buff_removed.remove(self._on_buff_removed)

    def _on_buff_added(self, buff_type):
        if buff_type is self.buff:
            if self.timing == BuffCondition.Timing.ON_ADD or self.timing == BuffCondition.Timing.HAS_BUFF:
                self._satisfy()
            else:
                self._unsatisfy()

    def _on_buff_removed(self, buff_type):
        if buff_type is self.buff:
            if self.timing == BuffCondition.Timing.ON_REMOVE or self.timing == BuffCondition.Timing.NOT_HAS_BUFF:
                self._satisfy()
            else:
                self._unsatisfy()

