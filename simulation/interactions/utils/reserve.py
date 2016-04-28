from _weakrefset import WeakSet
from event_testing.results import TestResult
from interactions import ParticipantType
from element_utils import build_critical_section_with_finally
from sims4.tuning.tunable import Tunable, TunableFactory, TunableEnumFlags, TunableVariant, TunableReference, OptionalTunable, TunableSimMinute
import services

class ReserveObjectHandler:
    __qualname__ = 'ReserveObjectHandler'
    LOCKOUT_TIME = TunableSimMinute(480, description='Number of sim minutes to lockout an in use object from autonomy.')

    def __init__(self, sim, target, reserver, all_parts=False):
        self._sim = sim
        self._target = target.ref()
        self._reserver = reserver
        self._registered = False
        self._all_parts = all_parts
        self._reserved_objects = WeakSet()

    @property
    def is_multi(self):
        return False

    def _is_valid_target(self, target):
        return True

    def get_targets(self):
        if self._target is not None:
            target = self._target()
            if not target.is_sim:
                if not self._all_parts:
                    return (target,)
                if target.is_part:
                    target = target.part_owner
                if target.parts:
                    return target.parts
                return (target,)
        return ()

    def _begin(self, element):
        if self.reserve():
            return True
        return False

    def reserve(self):
        if self._registered:
            return True
        if self.may_reserve():
            for target in self.get_targets():
                target.reserve(self._sim, self._reserver, multi=self.is_multi)
                self._reserved_objects.add(target)
            self._registered = True
            return True
        return False

    def end(self, *_, **__):
        if self._registered:
            for target in self._reserved_objects:
                target.release(self._sim, self._reserver, multi=self.is_multi)
            self._registered = False

    def may_reserve(self, *args, **kwargs):
        targets = self.get_targets()
        for target in targets:
            test_result = self._is_valid_target(target)
            if not test_result:
                return test_result
            reserve_result = target.may_reserve(self._sim, multi=self.is_multi, *args, **kwargs)
            while not reserve_result:
                return reserve_result
        return TestResult.TRUE

    def do_reserve(self, sequence=None):
        return build_critical_section_with_finally(self._begin, sequence, self.end)

class MultiReserveObjectHandler(ReserveObjectHandler):
    __qualname__ = 'MultiReserveObjectHandler'

    def __init__(self, *args, reservation_stat=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._reservation_stat = reservation_stat

    @property
    def is_multi(self):
        return True

    def _is_valid_target(self, target):
        if self._reservation_stat is not None:
            tracker = target.get_tracker(self._reservation_stat)
            reservations = tracker.get_value(self._reservation_stat) - len(target.get_users(sims_only=True))
            if reservations <= 0:
                return TestResult(False, '{} does not have enough left of {}'.format(target, self._reservation_stat))
        return TestResult.TRUE

class NestedReserveObjectHandler:
    __qualname__ = 'NestedReserveObjectHandler'

    def __init__(self):
        self._handlers = []
        self._registered = False

    def is_multi(self):
        return all(handler.is_multi for handler in self._handlers)

    def get_targets(self):
        all_targets = []
        for handler in self._handlers:
            all_targets.extend(handler.get_targets())
        return all_targets

    def add_handler(self, handler):
        self._handlers.append(handler)

    def may_reserve(self, *args, **kwargs):
        for handler in self._handlers:
            reserve_result = handler.may_reserve(*args, **kwargs)
            while not reserve_result:
                return reserve_result
        return True

    def reserve(self, *_, **__):
        if self._registered:
            return True
        if self.may_reserve():
            for handler in self._handlers:
                handler.reserve()
            self._registered = True
            return True
        return False

    def end(self, *_, **__):
        if self._registered:
            for handler in self._handlers:
                handler.end()
            self._registered = False

    def do_reserve(self, sequence=None):
        for handler in self._handlers:
            sequence = handler.do_reserve(sequence=sequence)
        return sequence

def create_reserver(sim, target, reserver=None, interaction=None, xevt=None, handler=ReserveObjectHandler, **kwargs):
    reserve_object_handler = handler(sim, target, reserver, **kwargs)
    if xevt is not None and interaction is not None:
        interaction.animation_context.register_event_handler(reserve_object_handler.end, handler_id=xevt)
    return reserve_object_handler

class TunableBasicReserveObject(TunableFactory):
    __qualname__ = 'TunableBasicReserveObject'

    @staticmethod
    def _factory(sim, obj, xevt, **kwargs):
        return create_reserver(sim, obj, xevt=xevt, **kwargs)

    FACTORY_TYPE = _factory

class TunableBasicReserveObjectAndParts(TunableFactory):
    __qualname__ = 'TunableBasicReserveObjectAndParts'

    @staticmethod
    def _factory(sim, obj, xevt, **kwargs):
        return create_reserver(sim, obj, xevt=xevt, all_parts=True, **kwargs)

    FACTORY_TYPE = _factory

class TunableMultiReserveObject(TunableFactory):
    __qualname__ = 'TunableMultiReserveObject'

    @staticmethod
    def _factory(sim, obj, xevt, reservation_stat, **kwargs):
        return create_reserver(sim, obj, xevt=xevt, handler=MultiReserveObjectHandler, reservation_stat=reservation_stat, **kwargs)

    FACTORY_TYPE = _factory

    def __init__(self, **kwargs):
        super().__init__(reservation_stat=TunableReference(services.statistic_manager(), description='The stat driving the available number of reservations.'), **kwargs)

DEFAULT_RESERVATION_PARTICIPANT_TYPES = ParticipantType.Object | ParticipantType.CarriedObject | ParticipantType.CraftingObject

class TunableReserveObject(TunableFactory, is_fragment=True):
    __qualname__ = 'TunableReserveObject'

    @staticmethod
    def _factory(sim, participant_resolver, *, reserve_type, subject, xevt, **kwargs):
        handler = NestedReserveObjectHandler()
        for obj in participant_resolver.get_participants(subject):
            while obj is not sim:
                handler.add_handler(reserve_type(sim, obj, xevt, reserver=participant_resolver, **kwargs))
        return handler

    FACTORY_TYPE = _factory

    def __init__(self, description='Tune the reservation of an object.', **kwargs):
        super().__init__(reserve_type=TunableVariant(basic=TunableBasicReserveObject(description='Reserving this object prevents other Sims from also reserving it.'), all=TunableBasicReserveObjectAndParts(description='Reserving this object and all parts (if parts) preventing other Sims from also reserving it/them.'), multi=TunableMultiReserveObject(description='Multiple reservations can be made on this object, gated by some factor.'), default='basic'), subject=TunableEnumFlags(ParticipantType, DEFAULT_RESERVATION_PARTICIPANT_TYPES, description='Who or what to reserve.'), xevt=OptionalTunable(Tunable(int, None), description='When specified, the end of the reservation is associated to this xevent.'), description=description, **kwargs)

