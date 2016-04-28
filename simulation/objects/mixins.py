from _weakrefset import WeakSet
from weakref import WeakKeyDictionary
import itertools
import weakref
from event_testing.results import TestResult
from objects.object_enums import ResetReason
from services.reset_and_delete_service import ResetRecord
from sims4.callback_utils import CallableList
from sims4.utils import setdefault_callable
import clock
import services
import sims4.log
logger = sims4.log.Logger('InUse')

class _CraftingLockoutData:
    __qualname__ = '_CraftingLockoutData'

    def __init__(self):
        self._crafting_lockout_ref_counts = {}

    def add_lockout(self, crafting_type):
        if self._crafting_lockout_ref_counts.get(crafting_type):
            self._crafting_lockout_ref_counts[crafting_type] += 1
        else:
            self._crafting_lockout_ref_counts[crafting_type] = 1

    def get_ref_count(self, crafting_type, from_autonomy=False):
        ref_count = self._crafting_lockout_ref_counts.get(crafting_type)
        if ref_count:
            return ref_count
        return 0

class LockoutMixin:
    __qualname__ = 'LockoutMixin'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lockouts = weakref.WeakKeyDictionary()
        self._crafting_lockouts = weakref.WeakKeyDictionary()

    def add_lockout(self, obj, duration_in_sim_minutes):
        if self is obj:
            return
        interval = clock.interval_in_sim_minutes(duration_in_sim_minutes)
        end_time = services.time_service().sim_now + interval
        lockout = self._lockouts.get(obj, None)
        if lockout is None or lockout < end_time:
            self._lockouts[obj] = end_time
        crafting_lockout = self._crafting_lockouts.get(obj, None)
        if crafting_lockout is None:
            crafting_lockout_data = None
            for super_affordance in obj.super_affordances():
                while hasattr(super_affordance, 'crafting_type_requirement') and super_affordance.crafting_type_requirement is not None:
                    if crafting_lockout_data is None:
                        crafting_lockout_data = _CraftingLockoutData()
                    crafting_lockout_data.add_lockout(super_affordance.crafting_type_requirement)
            if crafting_lockout_data is not None:
                self._crafting_lockouts[obj] = crafting_lockout_data

    def clear_all_lockouts(self):
        self._lockouts = weakref.WeakKeyDictionary()
        self._crafting_lockouts = weakref.WeakKeyDictionary()

    def has_lockout(self, obj):
        lockout = self._lockouts.get(obj, None)
        if lockout:
            if lockout < services.time_service().sim_now:
                del self._lockouts[obj]
                if obj in self._crafting_lockouts:
                    del self._crafting_lockouts[obj]
                return False
            return True
        return False

    def get_lockouts_gen(self):
        current_time = services.time_service().sim_now
        for obj in self._lockouts:
            lockout = self._lockouts.get(obj, None)
            while lockout >= current_time:
                yield (obj, lockout - current_time)

    def get_autonomous_crafting_lockout_ref_count(self, crafting_type):
        ref_count = 0
        for crafting_lockout_data in self._crafting_lockouts.values():
            ref_count += crafting_lockout_data.get_ref_count(crafting_type)
        return ref_count

class InUseError(Exception):
    __qualname__ = 'InUseError'

    def __init__(self, obj):
        self.obj = obj

    def __str__(self):
        return 'Attempt to reserve an unavailable object - ' + str(self.obj)

class NotInUseError(Exception):
    __qualname__ = 'NotInUseError'

    def __init__(self, obj):
        self.obj = obj

    def __str__(self):
        return 'Attempt to release an object that is already free - ' + str(self.obj)

class UseListMixin:
    __qualname__ = 'UseListMixin'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._reservations = WeakKeyDictionary()
        self._reservations_multi = WeakKeyDictionary()
        self._use_list_changed_callbacks = CallableList()

    @property
    def using_sim(self):
        if not self._reservations:
            return
        return next(self._reservations.keys())

    @property
    def in_use(self):
        if self._reservations:
            return True
        return False

    def in_use_by(self, sim, owner=None):
        owners = self._reservations.get(sim)
        if not owners:
            return False
        return owner is None or owner in owners

    def _may_reserve_obj(self, sim, affordance, context):
        if self.in_use_by(sim):
            return True
        if self.children:
            for child in self.children:
                while not child.may_reserve(sim, multi=False, affordance=affordance, context=context):
                    return False
        return not self._reservations

    def _may_reserve_part(self, sim, affordance, context, check_overlapping_parts=True):
        part_list = self.part_owner.parts
        for part in part_list:
            if part is self:
                pass
            using_sim = part.using_sim
            while not using_sim is None:
                if using_sim is sim:
                    pass
                for si in using_sim.si_state:
                    reserve_object_tests = si.object_reservation_tests
                    while reserve_object_tests:
                        reserve_result = reserve_object_tests.run_tests(si.get_resolver(target=sim))
                        if not reserve_result:
                            return reserve_result
                if using_sim.queue.transition_controller is not None:
                    transitioning_interaction = using_sim.queue.transition_controller.interaction
                    if transitioning_interaction.is_super:
                        reserve_object_tests = transitioning_interaction.object_reservation_tests
                        if reserve_object_tests:
                            target_sim = sim if transitioning_interaction.sim is not sim else using_sim
                            reserve_result = reserve_object_tests.run_tests(transitioning_interaction.get_resolver(target=target_sim))
                            if not reserve_result:
                                return reserve_result
                while affordance is not None and affordance.is_super:
                    if context is None:
                        logger.error('Attempt to call may_reserve() with an affordance but no context!', owner='maxr')
                    reserve_object_tests = affordance.object_reservation_tests
                    if reserve_object_tests:
                        reserve_result = reserve_object_tests.run_tests(affordance.get_resolver(target=using_sim, context=context))
                        if not reserve_result:
                            return reserve_result
        if affordance is not None and not self.supports_affordance(affordance):
            return TestResult(False, '{} does not support {}'.format(self, affordance))
        reserve_result = self._may_reserve_obj(sim, affordance=affordance, context=context)
        if not reserve_result:
            return reserve_result
        if check_overlapping_parts:
            for overlapping_part in self.get_overlapping_parts():
                if overlapping_part is self:
                    pass
                reserve_result = overlapping_part._may_reserve_part(sim, None, None, check_overlapping_parts=False)
                while not reserve_result:
                    return reserve_result
        return TestResult(True, 'Passed all reservation tests.')

    def may_reserve(self, sim, multi=False, affordance=None, context=None):
        if self.parts:
            logger.callstack('Cannot reserve an object that has parts: {}, for {} running {} - multi: {}', self, sim, affordance, multi, level=sims4.log.LEVEL_ERROR)
            return False
        if multi:
            return True
        if self.is_part:
            result = self._may_reserve_part(sim, affordance, context)
        else:
            result = self._may_reserve_obj(sim, affordance, context)
        return result

    def reserve(self, sim, owner, multi=False):
        use_list = self._reservations_multi if multi else self._reservations
        sim_list = setdefault_callable(use_list, sim, WeakSet)
        sim_list.add(owner)
        self._use_list_changed_callbacks(user=sim, added=True)

    def release(self, sim, owner, multi=False):
        use_list = self._reservations_multi if multi else self._reservations
        sim_list = use_list.get(sim)
        sim_list.remove(owner)
        if not sim_list:
            del use_list[sim]
        self._use_list_changed_callbacks(user=sim, added=False)
        self._destroy_if_necessary()

    def make_transient(self):
        self.transient = True
        self._destroy_if_necessary()

    def _destroy_if_necessary(self):
        if not self._reservations_multi and not self._reservations and self.transient:
            if self.is_part:
                self.part_owner.schedule_destroy_asap(source=self, cause='Destroying unused transient part.')
            else:
                self.schedule_destroy_asap(source=self, cause='Destroying unused transient object.')

    def usable_by_transition_controller(self, transition_controller):
        if transition_controller is not None:
            required_sims = transition_controller.interaction.required_sims()
            if self.is_part:
                all_overlapping_parts = self.get_overlapping_parts()
                all_overlapping_parts.append(self)
                for part in all_overlapping_parts:
                    for user in part.get_users():
                        while user not in required_sims:
                            return False
                return True
            for required_sim in required_sims:
                while self.in_use_by(required_sim):
                    return True
        return False

    def get_users(self, sims_only=False, include_multi=True):
        targets = (self,) if not self.parts else self.parts
        if include_multi:
            return {sim for target in targets for sim in itertools.chain(target._reservations, target._reservations_multi) if not sims_only or sim.is_sim}
        return {sim for target in targets for sim in target._reservations if not sims_only or sim.is_sim}

    def on_reset_get_interdependent_reset_records(self, reset_reason, reset_records):
        super().on_reset_get_interdependent_reset_records(reset_reason, reset_records)
        relevant_sims = self.get_users(sims_only=True)
        for sim in relevant_sims:
            if self.reset_reason() == ResetReason.BEING_DESTROYED:
                reset_records.append(ResetRecord(sim, ResetReason.RESET_EXPECTED, self, 'In use list of object being destroyed.'))
            body_target_part_owner = sim.posture_state.body.target
            if body_target_part_owner is not None and body_target_part_owner.is_part:
                body_target_part_owner = body_target_part_owner.part_owner
            transition_controller = sim.queue.transition_controller
            while body_target_part_owner is self or transition_controller is None or not transition_controller.will_derail_if_given_object_is_reset(self):
                reset_records.append(ResetRecord(sim, ResetReason.RESET_EXPECTED, self, 'Transitioning To or In.'))

    def register_on_use_list_changed(self, callback):
        self._use_list_changed_callbacks.append(callback)

    def unregister_on_use_list_changed(self, callback):
        if callback in self._use_list_changed_callbacks:
            self._use_list_changed_callbacks.remove(callback)

    def _print_in_use(self):
        if self._reservations:
            for sim in self._reservations:
                logger.debug('    Reservation: {}', sim)
        if self._reservations_multi:
            for sim in self._reservations_multi:
                logger.debug('    Reservation_Multi: {}', sim)

