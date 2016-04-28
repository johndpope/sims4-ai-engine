from _weakrefset import WeakSet
import copy
from singletons import DEFAULT
import enum
import interactions.priority
import sims4.log
logger = sims4.log.Logger('Interactions')
__all__ = ['InteractionContext']

class InteractionSource(enum.Int):
    __qualname__ = 'InteractionSource'
    PIE_MENU = 0
    AUTONOMY = 1
    BODY_CANCEL_AOP = 2
    CARRY_CANCEL_AOP = 3
    SCRIPT = 4
    UNIT_TEST = 5
    POSTURE_GRAPH = 6
    SOCIAL_ADJUSTMENT = 7
    QUICKTIME = 8
    GET_COMFORTABLE = 9
    SCRIPT_WITH_USER_INTENT = 10

class InteractionBucketType(enum.Int, export=False):
    __qualname__ = 'InteractionBucketType'
    BASED_ON_SOURCE = 0
    AUTONOMY = 1
    SOCIAL_ADJUSTMENT = 2
    BODY_CANCEL_REPLACEMENT = 3
    CARRY_CANCEL_REPLACEMENT = 4
    DEFAULT = 5

class QueueInsertStrategy(enum.Int, export=False):
    __qualname__ = 'QueueInsertStrategy'
    LAST = 0
    NEXT = 1
    FIRST = 2

class InteractionContext:
    __qualname__ = 'InteractionContext'
    SOURCE_PIE_MENU = InteractionSource.PIE_MENU
    SOURCE_AUTONOMY = InteractionSource.AUTONOMY
    SOURCE_BODY_CANCEL_AOP = InteractionSource.BODY_CANCEL_AOP
    SOURCE_CARRY_CANCEL_AOP = InteractionSource.CARRY_CANCEL_AOP
    SOURCE_SCRIPT = InteractionSource.SCRIPT
    SOURCE_UNIT_TEST = InteractionSource.UNIT_TEST
    SOURCE_SOCIAL_ADJUSTMENT = InteractionSource.SOCIAL_ADJUSTMENT
    SOURCE_QUICKTIME = InteractionSource.QUICKTIME
    SOURCE_GET_COMFORTABLE = InteractionSource.GET_COMFORTABLE
    SOURCE_SCRIPT_WITH_USER_INTENT = InteractionSource.SCRIPT_WITH_USER_INTENT
    SOURCE_POSTURE_GRAPH = InteractionSource.POSTURE_GRAPH

    def __init__(self, sim, source, priority, run_priority=None, client=None, pick=None, insert_strategy=QueueInsertStrategy.LAST, must_run_next=False, continuation_id=None, group_id=None, shift_held=False, carry_target=None, target_sim_id=None, bucket=InteractionBucketType.BASED_ON_SOURCE, visual_continuation_id=None, restored_from_load=False, cancel_if_incompatible_in_queue=False, always_check_in_use=False, preferred_objects=()):
        self._sim = sim.ref() if sim else None
        self.source = source
        self.priority = priority
        self.client = client
        self.pick = pick
        self.insert_strategy = insert_strategy
        self.must_run_next = must_run_next
        self.shift_held = shift_held
        self.continuation_id = continuation_id
        self.visual_continuation_id = visual_continuation_id
        self.group_id = group_id
        self.carry_target = carry_target
        self.target_sim_id = target_sim_id
        self.run_priority = run_priority
        self.bucket = bucket
        self.restored_from_load = restored_from_load
        self.cancel_if_incompatible_in_queue = cancel_if_incompatible_in_queue
        self.always_check_in_use = always_check_in_use
        self.preferred_objects = WeakSet(preferred_objects)

    def _clone(self, **overrides):
        result = copy.copy(self)
        for (name, value) in overrides.items():
            if value is DEFAULT:
                pass
            getattr(result, name)
            setattr(result, name, value)
        return result

    @property
    def bucket_type(self):
        return self.bucket

    @property
    def is_cancel_aop(self):
        return self.source == InteractionSource.BODY_CANCEL_AOP or self.source == InteractionSource.CARRY_CANCEL_AOP

    def clone_for_user_directed_choice(self):
        return self._clone(source=InteractionContext.SOURCE_PIE_MENU, priority=self.client.interaction_priority, insert_strategy=QueueInsertStrategy.LAST, continuation_id=None, group_id=None)

    def clone_for_autonomous_choice(self):
        return self._clone(source=InteractionContext.SOURCE_AUTONOMY, priority=interactions.priority.Priority.Low, insert_strategy=QueueInsertStrategy.LAST, continuation_id=None, group_id=None)

    def clone_for_insert_next(self, preferred_objects=DEFAULT, **kwargs):
        if preferred_objects is DEFAULT:
            preferred_objects = self.preferred_objects
        return self._clone(insert_strategy=QueueInsertStrategy.NEXT, preferred_objects=preferred_objects, restored_from_load=False, **kwargs)

    def clone_for_continuation(self, continuation_of_si, insert_strategy=QueueInsertStrategy.NEXT, continuation_id=DEFAULT, group_id=DEFAULT, preferred_objects=DEFAULT, **kwargs):
        if not continuation_of_si.immediate:
            if continuation_id is DEFAULT:
                continuation_id = continuation_of_si.id
            group_id = continuation_of_si.group_id
        else:
            logger.error('clone_for_continuation: attempting to create a continuation of an immediate interaction, support for this is deprecated and will be removed soon: {}', continuation_of_si, owner='jpollak/tastle')
        if preferred_objects is DEFAULT:
            preferred_objects = self.preferred_objects
        return self._clone(insert_strategy=insert_strategy, continuation_id=continuation_id, group_id=group_id, preferred_objects=preferred_objects, restored_from_load=False, **kwargs)

    def clone_for_parameterized_autonomy(self, source_si, group_id=DEFAULT, continuation_id=DEFAULT, visual_continuation_id=DEFAULT, **kwargs):
        if group_id is DEFAULT:
            group_id = source_si.group_id
        if continuation_id is DEFAULT:
            continuation_id = source_si.id
        if visual_continuation_id is DEFAULT:
            visual_continuation_id = source_si.id
        return self._clone(insert_strategy=QueueInsertStrategy.FIRST, group_id=group_id, continuation_id=continuation_id, run_priority=None, visual_continuation_id=source_si.id, **kwargs)

    def clone_from_immediate_context(self, continuation_of_si, **kwargs):
        if not continuation_of_si.immediate:
            logger.error('clone_from_immediate_context: attempting to create a continuation of a non-immediate interaction.', owner='tastle/jpollak')
        return self._clone(group_id=continuation_of_si.group_id, **kwargs)

    def clone_for_sim(self, sim, **overrides):
        return self._clone(_sim=sim.ref(), **overrides)

    def clone_for_concurrent_context(self):
        return self._clone(insert_strategy=QueueInsertStrategy.FIRST)

    @property
    def sim(self):
        if self._sim:
            return self._sim()

    def add_preferred_object(self, cur_obj):
        self.preferred_objects.add(cur_obj)

    def add_preferred_objects(self, obj_list):
        pass

    @property
    def carry_target(self):
        if self._carry_target:
            return self._carry_target()

    @carry_target.setter
    def carry_target(self, value):
        self._carry_target = value.ref() if value else None

    def __repr__(self):
        return '{0}.{1}({2}, {3}, {4})'.format(self.__module__, self.__class__.__name__, repr(self.sim), self.source, repr(self.priority))

