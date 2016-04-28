from collections import namedtuple
from away_actions.away_actions import AwayAction
from careers.career_tuning import Career, CareerCategory
from element_utils import build_critical_section_with_finally
from event_testing.results import TestResult
from interactions.aop import AffordanceObjectPair
from interactions.base.picker_interaction import PickerSuperInteraction, PickerSingleChoiceSuperInteraction
from interactions.base.super_interaction import SuperInteraction
from interactions.utils.loot import LootActions
from interactions.utils.tunable import TunableContinuation
from objects.terrain import TerrainSuperInteraction
from sims.sim_info_interactions import SimInfoInteraction
from sims4.tuning.tunable import OptionalTunable, TunableList, Tunable, TunableVariant, TunableEnumSet, HasTunableSingletonFactory, AutoFactoryInit
from sims4.tuning.tunable_base import GroupNames
from sims4.utils import flexmethod
from statistics.commodity import RuntimeCommodity, CommodityTimePassageFixupType
from ui.ui_dialog_picker import ObjectPickerRow
import alarms
import clock
import date_and_time
import event_testing
import interactions.base.super_interaction
import interactions.rabbit_hole
import services
import sims4.tuning.tunable
import terrain
logger = sims4.log.Logger('Careers')

class CareerSuperInteraction(interactions.base.super_interaction.SuperInteraction):
    __qualname__ = 'CareerSuperInteraction'

    def __init__(self, aop, context, career_uid=None, **kwargs):
        super().__init__(aop, context, **kwargs)
        if career_uid is None:
            career = self.sim.sim_info.career_tracker.career_currently_within_hours
            if career is not None:
                career_uid = career.guid64
        self._career_uid = career_uid

    @property
    def interaction_parameters(self):
        kwargs = super().interaction_parameters
        kwargs['career_uid'] = self._career_uid
        return kwargs

    @property
    def career_uid(self):
        return self._career_uid

    def get_career(self, career_id=None):
        return self.sim.sim_info.career_tracker.get_career_by_uid(self._career_uid)

    @classmethod
    def _test(cls, target, context, career_uid=None, skip_safe_tests=False, **kwargs):
        career = context.sim.sim_info.career_tracker.get_career_by_uid(career_uid)
        if career is None:
            career = context.sim.sim_info.career_tracker.career_currently_within_hours
        if career is None:
            return event_testing.results.TestResult(False, 'Sim({}) does not have career: {}.', context.sim, career_uid)
        if not career.is_work_time:
            return event_testing.results.TestResult(False, 'Not currently a work time for Sim({})', context.sim)
        return event_testing.results.TestResult.TRUE

    def on_added_to_queue(self, *args, **kwargs):
        self.add_liability(interactions.rabbit_hole.RABBIT_HOLE_LIABILTIY, interactions.rabbit_hole.RabbitHoleLiability())
        return super().on_added_to_queue(*args, **kwargs)

    def build_basic_elements(self, sequence=()):
        sequence = super().build_basic_elements(sequence=sequence)
        sequence = build_critical_section_with_finally(self.interaction_start, sequence, self.interaction_end)
        return sequence

    def interaction_start(self, _):
        career = self.get_career()
        if career is not None:
            career.attend_work(interaction=self)

    def interaction_end(self, _):
        if services.current_zone().is_zone_shutting_down:
            return
        career = self.get_career()
        if career is not None:
            career.leave_work(interaction=self)

class CareerPickerSuperInteraction(PickerSingleChoiceSuperInteraction):
    __qualname__ = 'CareerPickerSuperInteraction'

    class CareerPickerFilter(HasTunableSingletonFactory, AutoFactoryInit):
        __qualname__ = 'CareerPickerSuperInteraction.CareerPickerFilter'

        def is_valid(self, career):
            raise NotImplementedError

    class CareerPickerFilterAll(CareerPickerFilter):
        __qualname__ = 'CareerPickerSuperInteraction.CareerPickerFilterAll'

        def is_valid(self, career):
            return True

    class CareerPickerFilterWhitelist(CareerPickerFilter):
        __qualname__ = 'CareerPickerSuperInteraction.CareerPickerFilterWhitelist'
        FACTORY_TUNABLES = {'whitelist': TunableEnumSet(description='\n                Only careers of this category are allowed. If this set is\n                empty, then no careers are allowed.\n                ', enum_type=CareerCategory)}

        def is_valid(self, career):
            return career.career_category in self.whitelist

    class CareerPickerFilterBlacklist(CareerPickerFilter):
        __qualname__ = 'CareerPickerSuperInteraction.CareerPickerFilterBlacklist'
        FACTORY_TUNABLES = {'blacklist': TunableEnumSet(description='\n                Careers of this category are not allowed. All others are\n                allowed.\n                ', enum_type=CareerCategory)}

        def is_valid(self, career):
            return career.career_category not in self.blacklist

    INSTANCE_TUNABLES = {'continuation': OptionalTunable(description='\n            If enabled, you can tune a continuation to be pushed. PickedItemId\n            will be the id of the selected career.\n            ', tunable=TunableContinuation(description='\n                If specified, a continuation to push with the chosen career.\n                '), tuning_group=GroupNames.PICKERTUNING), 'career_filter': TunableVariant(description='\n            Which career types to show.\n            ', all=CareerPickerFilterAll.TunableFactory(), blacklist=CareerPickerFilterBlacklist.TunableFactory(), whitelist=CareerPickerFilterWhitelist.TunableFactory(), default='all', tuning_group=GroupNames.PICKERTUNING)}

    @classmethod
    def _valid_careers_gen(cls, sim):
        yield (career for career in sim.sim_info.career_tracker.careers.values() if cls.career_filter.is_valid(career))

    @classmethod
    def has_valid_choice(cls, target, context, **kwargs):
        return any(cls._valid_careers_gen(context.sim))

    def _run_interaction_gen(self, timeline):
        self._show_picker_dialog(self.sim, target_sim=self.target)
        return True

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        for career in cls._valid_careers_gen(context.sim):
            track = career.current_track_tuning
            row = ObjectPickerRow(name=track.career_name(context.sim), icon=track.icon, row_description=track.career_description, tag=career)
            yield row

    def on_choice_selected(self, choice_tag, **kwargs):
        career = choice_tag
        if career is not None and self.continuation is not None:
            picked_item_set = set()
            picked_item_set.add(career.guid64)
            self.interaction_parameters['picked_item_ids'] = picked_item_set
            self.push_tunable_continuation(self.continuation, picked_item_ids=picked_item_set)

class CareerProxyInteractionMixin:
    __qualname__ = 'CareerProxyInteractionMixin'

    @classmethod
    def potential_interactions(cls, target, context, **kwargs):
        if context.sim is None:
            return
        career = context.sim.sim_info.career_tracker.career_currently_within_hours
        if career is not None and not career.currently_at_work:
            affordance = career.get_work_affordance()
            yield AffordanceObjectPair(affordance, target, affordance, None, **kwargs)

class CareerProxySuperInteraction(CareerProxyInteractionMixin, SuperInteraction):
    __qualname__ = 'CareerProxySuperInteraction'

class CareerTerrainProxySuperInteraction(CareerProxyInteractionMixin, TerrainSuperInteraction):
    __qualname__ = 'CareerTerrainProxySuperInteraction'

    @classmethod
    def potential_interactions(cls, target, context, **kwargs):
        (position, _, result) = cls._get_target_position_surface_and_test_off_lot(target, context)
        if not result:
            return
        if position is not None and not terrain.is_position_in_street(position):
            return
        yield super().potential_interactions(context.sim, context, **kwargs)

class CareerLeaveWorkEarlyInteraction(SimInfoInteraction):
    __qualname__ = 'CareerLeaveWorkEarlyInteraction'

    @classmethod
    def _test(cls, *args, sim_info=None, **kwargs):
        if sim_info is None:
            return TestResult(False, 'No sim info')
        career = sim_info.career_tracker.get_at_work_career()
        if career is None:
            return TestResult(False, 'Not currently at work')
        return super()._test(*args, **kwargs)

    def _run_interaction_gen(self, timeline):
        career = self._sim_info.career_tracker.get_at_work_career()
        if career is not None:
            career.leave_work_early()
        return True

class CareerPromoteSuperInteraction(PickerSuperInteraction):
    __qualname__ = 'CareerPromoteSuperInteraction'
    INSTANCE_TUNABLES = {'demote': sims4.tuning.tunable.Tunable(bool, False, description='\n                If this is set, the Sim will be demoted instead of promoted.\n                ')}

    @classmethod
    def _test(cls, target, context, **kwargs):
        result = super()._test(target, context, **kwargs)
        if not result:
            return result
        for career in target.sim_info.career_tracker.careers.values():
            while career.can_change_level(demote=cls.demote):
                return event_testing.results.TestResult.TRUE
        return event_testing.results.TestResult(False, 'Sim {} has no career that can be {}', target, 'promoted' if not cls.demote else 'demoted')

    def _run_interaction_gen(self, timeline):
        self._show_picker_dialog(self.sim, target_sim=self.target)
        return True

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        for career in target.sim_info.career_tracker.careers.values():
            if not career.can_change_level(demote=cls.demote):
                pass
            track = career.current_track_tuning
            row = ObjectPickerRow(name=track.career_name(target.sim_info), icon=track.icon, row_description=track.career_description, tag=career)
            yield row

    def on_choice_selected(self, choice_tag, **kwargs):
        career = choice_tag
        if career is not None:
            if self.demote:
                career.demote()
            else:
                career.promote()

class CareerTone(AwayAction):
    __qualname__ = 'CareerTone'
    INSTANCE_TUNABLES = {'dominant_tone_loot_actions': TunableList(description='\n            Loot to apply at the end of a work period if this tone ran for the\n            most amount of time out of all tones.\n            ', tunable=LootActions.TunableReference()), 'performance_multiplier': Tunable(description='\n            Performance multiplier applied to work performance gain.\n            ', tunable_type=float, default=1)}
    runtime_commodity = None

    @classmethod
    def _tuning_loaded_callback(cls):
        if cls.runtime_commodity is not None:
            return
        commodity = RuntimeCommodity.generate(cls.__name__)
        commodity.decay_rate = 0
        commodity.convergence_value = 0
        commodity.remove_on_convergence = True
        commodity.visible = False
        commodity.max_value_tuning = date_and_time.SECONDS_PER_WEEK
        commodity.min_value_tuning = 0
        commodity.initial_value = 0
        commodity._time_passage_fixup_type = CommodityTimePassageFixupType.DO_NOT_FIXUP
        cls.runtime_commodity = commodity

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._performance_change_alarm_handle = None
        self._last_performance_change_time = None

    def run(self, callback):
        super().run(callback)
        self._last_performance_change_time = services.time_service().sim_now
        time_span = clock.interval_in_sim_minutes(Career.CAREER_PERFORMANCE_UPDATE_INTERVAL)
        self._performance_change_alarm_handle = alarms.add_alarm(self, time_span, self._do_performance_change, repeating=True)

    def stop(self):
        if self._performance_change_alarm_handle is not None:
            alarms.cancel_alarm(self._performance_change_alarm_handle)
            self._performance_change_alarm_handle = None
        self._apply_performance_change()
        super().stop()

    def _do_performance_change(self, alarm_handle):
        self._apply_performance_change()

    def _apply_performance_change(self):
        career = self.sim_info.career_tracker.get_at_work_career()
        if career is None:
            logger.error('CareerTone {} trying to update performance when Sim {} not at work', self, self.sim_info, owner='tingyul')
            return
        now = services.time_service().sim_now
        elapsed = now - self._last_performance_change_time
        self._last_performance_change_time = now
        career.apply_performance_change(elapsed, self.performance_multiplier)
        career.resend_career_data()

    def apply_dominant_tone_loot(self):
        resolver = self.get_resolver()
        for loot in self.dominant_tone_loot_actions:
            loot.apply_to_resolver(resolver)

