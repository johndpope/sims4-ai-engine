import contextlib
import itertools
import operator
import random
from protocolbuffers import Commodities_pb2
from buffs.tunable import TunableBuffReference, BuffReference
from clock import interval_in_sim_minutes
from interactions.context import QueueInsertStrategy
from objects import ALL_HIDDEN_REASONS
from sims4.localization import TunableLocalizedString
from sims4.math import Threshold, EPSILON
from sims4.tuning.geometric import TunableVector2
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import Tunable, TunableList, TunableTuple, OptionalTunable, TunableReference, TunableResourceKey, TunableThreshold, HasTunableReference, TunableSingletonFactory, TunableSet, TunableSimMinute, TunableRange, TunableEnumEntry, TunableColor, TunableInterval
from sims4.tuning.tunable_base import ExportModes
from sims4.utils import classproperty
from snippets import TunableAffordanceFilterSnippet
from statistics.commodity_messages import send_sim_commodity_progress_update_message
from statistics.continuous_statistic_tuning import TunedContinuousStatistic
from statistics.statistic_categories import StatisticCategory
from statistics.tunable import TunableStatAsmParam
import date_and_time
import enum
import event_testing.resolver
import interactions.context
import interactions.priority
import services
import sims4.log
import sims4.resources
import telemetry_helper
logger = sims4.log.Logger('Commodities')
TELEMETRY_GROUP_COMMODITIES = 'COMO'
TELEMETRY_HOOK_STATE_UP = 'UPPP'
TELEMETRY_HOOK_STATE_DOWN = 'DOWN'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_COMMODITIES)

class CommodityTimePassageFixupType(enum.Int):
    __qualname__ = 'CommodityTimePassageFixupType'
    DO_NOT_FIXUP = 0
    FIXUP_USING_AUTOSATISFY_CURVE = 1
    FIXUP_USING_TIME_ELAPSED = 2

class MotiveFillColorLevel(enum.Int):
    __qualname__ = 'MotiveFillColorLevel'
    NO_FILL = 0
    FAILURE = 1
    DISTRESS = 2
    FINE = 3

class CommodityState:
    __qualname__ = 'CommodityState'

    def __init__(self, value=0, buff=None, icon=None, fill_level=None, buff_add_threshold=None, data_description=None, fill_color=None, background_color=None, tooltip_icon_list=None, loot_list_on_enter=None):
        self._value = value
        self._buff = buff
        self._icon = icon
        self._fill_level = None
        self._buff_add_threshold = buff_add_threshold
        self._data_description = data_description
        self._fill_color = fill_color
        self._background_color = background_color
        self._tooltip_icon_list = tooltip_icon_list
        self.loot_list_on_enter = loot_list_on_enter

    @property
    def fill_level(self):
        return self._fill_level

    @property
    def value(self):
        return self._value

    @property
    def buff(self):
        return self._buff

    @property
    def icon(self):
        return self._icon

    @property
    def data_description(self):
        return self._data_description

    @property
    def buff_add_threshold(self):
        return self._buff_add_threshold

    def __repr__(self):
        return 'CommodityState: lower_value:{}, buff:{}'.format(self._value, self._buff.buff_type)

class TunableCommodityState(TunableSingletonFactory):
    __qualname__ = 'TunableCommodityState'
    FACTORY_TYPE = CommodityState

    def __init__(self, **kwargs):
        super().__init__(value=Tunable(description='\n                                lower bound value of the commodity state\n                                ', tunable_type=int, default=0, export_modes=ExportModes.All), buff=TunableBuffReference(description='\n                         Buff that will get added to sim when commodity is at\n                         this current state.\n                         ', reload_dependent=True), buff_add_threshold=OptionalTunable(TunableThreshold(description='\n                         When enabled, buff will not be added unless threshold\n                         has been met. Value for threshold must be within this\n                         commodity state.\n                         ')), icon=TunableResourceKey(description='\n                         Icon that is displayed for the current state of this\n                         commodity.\n                         ', default='PNG:missing_image', resource_types=sims4.resources.CompoundTypes.IMAGE, export_modes=ExportModes.All), fill_level=TunableEnumEntry(description='\n                         If set, this will determine how to color the motive bar.\n                         ', tunable_type=MotiveFillColorLevel, default=MotiveFillColorLevel.NO_FILL, export_modes=ExportModes.All), data_description=TunableLocalizedString(description='\n                         Localized description of the current commodity state.\n                         ', export_modes=ExportModes.All), fill_color=TunableColor.TunableColorRGBA(description='\n                         Fill color for motive bar\n                         ', export_modes=(ExportModes.ClientBinary,)), background_color=TunableColor.TunableColorRGBA(description='\n                         Background color for motive bar\n                         ', export_modes=(ExportModes.ClientBinary,)), tooltip_icon_list=TunableList(description='\n                         A list of icons to show in the tooltip of this\n                         commodity state.\n                         ', tunable=TunableResourceKey(description='\n                             Icon that is displayed what types of objects help\n                             solve this motive.\n                             ', default='PNG:missing_image', resource_types=sims4.resources.CompoundTypes.IMAGE), export_modes=(ExportModes.ClientBinary,)), loot_list_on_enter=TunableList(description='\n                          List of loots that will be applied when commodity\n                          value enters this state if owner of the commodity is a sim.\n                          ', tunable=TunableReference(services.get_instance_manager(sims4.resources.Types.ACTION))), **kwargs)

class TunableCommodityDistress(TunableTuple):
    __qualname__ = 'TunableCommodityDistress'

    def __init__(self, **kwargs):
        super().__init__(threshold_value=Tunable(int, -80, description='Threshold for which below the sim is in commodity distress'), buff=TunableBuffReference(description='Buff that gets added to the sim when they are in the commodity distress state.'), distress_interaction=TunableReference(services.get_instance_manager(sims4.resources.Types.INTERACTION), description='The interaction to be pushed on the sim when the commodity reaches distress.'), incompatible_interactions=TunableAffordanceFilterSnippet(), replacement_affordance=TunableReference(services.get_instance_manager(sims4.resources.Types.INTERACTION), description='The affordance that will be pushed when the commodity '), priority=Tunable(int, 0, description='The relative priority of the override interaction being played over others.'), description='The behaviors that show that the commodity is in distress.', **kwargs)

class TunableCommodityFailure(TunableTuple):
    __qualname__ = 'TunableCommodityFailure'

    def __init__(self, **kwargs):
        super().__init__(threshold=TunableThreshold(value=Tunable(int, -100, description='The value of the threshold that the commodity is compared against'), description='Threshold for which the sim experiences motive failure'), failure_interactions=TunableList(description="\n                             A list of interactions to be pushed when the Sim's\n                             commodity fails. Only the first one whose test\n                             passes will run.\n                             ", tunable=TunableReference(services.get_instance_manager(sims4.resources.Types.INTERACTION), description='The interaction to be pushed on the sim when the commodity fails.')), description='The behaviors for the commodity failing.', **kwargs)

class TunableArrowData(TunableTuple):
    __qualname__ = 'TunableArrowData'

    def __init__(self, **kwargs):
        super().__init__(positive_single_arrow=Tunable(float, 1, description='If the change rate for commodity is between this value and less than second arrow value, a single arrow will show up during commodity change.'), positive_double_arrow=Tunable(float, 20, description='If the change rate for commodity is between this value and less than triple arrow value, a double arrow will show up during commodity change.'), positive_triple_arrow=Tunable(float, 30, description='If the change rate for commodity is above this value then triple arrows will show up during commodity change.'), negative_single_arrow=Tunable(float, -1, description='If the change rate for commodity is between this value and less than second arrow value, a single arrow will show up during commodity change.'), negative_double_arrow=Tunable(float, -20, description='If the change rate for commodity is between this value and less than triple arrow value, a double arrow will show up during commodity change.'), negative_triple_arrow=Tunable(float, -30, description='If the change rate for commodity is above this value then triple arrows will show up during commodity change.'), **kwargs)

class Commodity(HasTunableReference, TunedContinuousStatistic, metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)):
    __qualname__ = 'Commodity'
    REMOVE_INSTANCE_TUNABLES = ('initial_value',)
    INSTANCE_TUNABLES = {'stat_name': TunableLocalizedString(description='\n                Localized name of this commodity.\n                ', export_modes=ExportModes.All), 'min_value_tuning': Tunable(description='\n                The minimum value for this stat.\n                ', tunable_type=float, default=-100, export_modes=ExportModes.All), 'max_value_tuning': Tunable(description='\n                The maximum value for this stat.', tunable_type=float, default=100, export_modes=ExportModes.All), 'ui_sort_order': TunableRange(description='\n                Order in which the commodity will appear in the motive panel.\n                Commodities sort from lowest to highest.\n                ', tunable_type=int, default=0, minimum=0, export_modes=ExportModes.All), 'ui_visible_distress_threshold': Tunable(description='\n                When current value of commodity goes below this value, commodity\n                will appear in the motive panel tab.\n                ', tunable_type=float, default=0, export_modes=ExportModes.All), 'ad_data': TunableList(description='\n                A list of Vector2 points that define the desire curve for this\n                commodity.\n                ', tunable=TunableVector2(description='\n                    Point on a Curve\n                    ', default=sims4.math.Vector2(0, 0), export_modes=ExportModes.All)), 'auto_satisfy_curve_tuning': TunableList(description='\n                A list of Vector2 points that define the auto-satisfy curve for\n                this commodity.\n                ', tunable=TunableVector2(description='\n                    Point on a Curve\n                    ', default=sims4.math.Vector2(0, 0))), 'auto_satisfy_curve_random_time_offset': TunableSimMinute(description='\n                An amount of time that when auto satisfy curves are being used\n                will modify the time current time being used to plus or minus\n                a random number between this value.\n                ', default=120), 'maximum_auto_satisfy_time': TunableSimMinute(description='\n                The maximum amount of time that the auto satisfy curves will\n                interpolate the values based on the current one before just\n                setting to the maximum value.\n                ', default=1440), 'initial_tuning': TunableTuple(description=' \n                The Initial value for this commodity. Can either be a single\n                value, range, or use auto satisfy curve to determine initial\n                value.  Use auto satisfy curve will take precedence over range\n                value and range value will take precedence over single value\n                range.\n                ', _use_auto_satisfy_curve_as_initial_value=Tunable(description="\n                    If checked, when we first add this commodity to a sim (sims only),\n                    the initial value of the commodity will be set according to\n                    the auto-satisfy curves defined by this commodity's tuning as\n                    opposed to the tuned initial value.    \n                    ", tunable_type=bool, needs_tuning=True, default=False), _value_range=OptionalTunable(description='\n                    If enabled then when we first add this commodity to a Sim the\n                    initial value of the commodity will be set to a random value\n                    within this interval.\n                    ', tunable=TunableInterval(description='\n                        An interval that will be used for the initial value of this\n                        commodity.\n                        ', tunable_type=int, default_lower=0, default_upper=100)), _value=Tunable(description='\n                    The initial value for this stat.', tunable_type=float, default=0.0)), 'weight': Tunable(description="\n                The weight of the Skill with regards to autonomy.  It's ignored \n                for the purposes of sorting stats, but it's applied when scoring \n                the actual statistic operation for the SI.\n                ", tunable_type=float, default=0.5), 'states': TunableList(description='\n                Commodity states based on thresholds.  This should be ordered\n                from worst state to best state.\n                ', tunable=TunableCommodityState()), 'commodity_distress': OptionalTunable(TunableCommodityDistress()), 'commodity_failure': OptionalTunable(TunableCommodityFailure()), 'remove_on_convergence': Tunable(description='\n                Commodity will be removed when convergence is met only if not\n                a core commodity.\n                ', tunable_type=bool, default=True), 'visible': Tunable(description='\n                Whether or not commodity should be sent to client.\n                ', tunable_type=bool, default=False, export_modes=ExportModes.All), '_add_if_not_in_tracker': Tunable(description="\n                If True, when we try to add or set the commodity, we will add\n                the commodity to the tracker if the tracker doesn't already have\n                it.\n                \n                e.g If a sim uses the toilet and we update bladder when that sim\n                doesn't have the bladder commodity in his/her tracker, we will\n                add the bladder commodity to that sim. \n                \n                Set this to false for the case of NPC behavior commodities like\n                Being a Maid or Being a Burglar.\n                ", tunable_type=bool, default=True), 'initial_as_default': Tunable(description='\n                Setting this to true will cause the default value returned during testing to be the \n                initial value tuned. This happens when a test is run on this commodity on a Sim that\n                does not have the commodity. Leaving this as false will instead return the convergence\n                value.\n                ', tunable_type=bool, default=False), 'arrow_data': TunableArrowData(description='\n                Used to determine when positive or negative arrows should show\n                up depending on the delta rate of the commodity.\n                ', export_modes=(ExportModes.ClientBinary,)), '_categories': TunableSet(description='\n                List of categories that this statistic is part of.\n                ', tunable=StatisticCategory), '_off_lot_simulation': OptionalTunable(TunableTuple(threshold=TunableThreshold(description='\n                    The threshold that will activate the increase in value\n                    when the commodity hits it.\n                    ', value=Tunable(description='\n                        The value that this threshold will trigger on.\n                        ', tunable_type=int, default=-50)), value=Tunable(description='\n                    The value that this commodity will increase by once it hits\n                    the tuned threshold while the sim is offlot.\n                    ', tunable_type=int, default=100), description='\n                Offlot simulation for this commodity.  The commodity will be\n                allowed to decay at a normal rate until it hits the tuned\n                threshold.  Once there it will then have its value added by the\n                tuned value.\n                ')), '_max_simulate_time_on_load': OptionalTunable(description="\n                If enabled, this commodity will only simulate for a max amount\n                of time when the player loads back into the lot with a new world\n                game time.\n                \n                By default, this is disabled. When disabled, the commodity will\n                simulate for however long between the lot's previous saved time\n                and the current world time. (Note: this is capped by PersistenceTuning.MAX_LOT_SIMULATE_ELAPSED_TIME)\n                ", tunable=TunableSimMinute(description="\n                    If set to > 0, on load, this object commodity will update its value to\n                    world time. And the commodity will simulate for the max amount of time\n                    specified in the tunable.\n                    EX: If tuned for the water commodity on plants to 6 hours --\n                    if the player leaves the lot for 4 hours and then comes back,\n                    the water commodity will update to what it should be 4 hours later.\n                    If the player leaves the lot for 8 hours and comes back, the water\n                    commodity will only update to what it should be 6 hours later.\n                    \n                    If set to 0, no matter how much time has elapsed since the\n                    player last visited the lot, this commodity's value will load\n                    to its last saved value.\n                    ", default=1440, minimum=0)), '_time_passage_fixup_type': TunableEnumEntry(description="\n            This is for commodities on SIMS only.\n            This option what we do with the commodity when the sim\n            gets instanced after time has elapsed since the last time the sim\n            was spawned.\n            \n            do not fixup: Means the commodity will stay the same value as it was\n                when the sim was last instantiated\n                \n            fixup using autosatisfy curve: The commodity's value will be set\n                based on its autosatisfy curve and the time between when the sim was\n                last saved. Note, this fixup will not occur for active household sims\n                if offlot simulation is enabled for this commodity.\n                \n            fixup using time elapsed: The commodity will decay linearly based on\n                when the sim was last saved. Use this for things like commodities\n                that control buff timers to make sure that the time remaining on\n                a buff remains consistent.\n            ", tunable_type=CommodityTimePassageFixupType, default=CommodityTimePassageFixupType.DO_NOT_FIXUP), 'use_stat_value_on_init': Tunable(description='\n            When set the initial value for the commodity will be set from the\n            commodity tuning.\n            If unchecked, the initial stat value will not be set on \n            initialization, but instead will use other systems (like the state)\n            to set its initial value.\n            ', tunable_type=bool, default=True), 'stat_asm_param': TunableStatAsmParam.TunableFactory(locked_args={'use_effective_skill_level': True})}
    initial_value = 0
    _auto_satisfy_curve = None
    use_autosatisfy_curve = True
    commodity_states = None

    @classmethod
    def _tuning_loaded_callback(cls):
        super()._tuning_loaded_callback()
        cls.initial_value = cls.initial_tuning._value
        cls._build_utility_curve_from_tuning_data(cls.ad_data)
        if cls.auto_satisfy_curve_tuning:
            point_list = [(point.x, point.y) for point in cls.auto_satisfy_curve_tuning]
            cls._auto_satisfy_curve = sims4.math.CircularUtilityCurve(point_list, 0, date_and_time.HOURS_PER_DAY)
        if cls.states:
            state_zero = cls.states[0]
            if state_zero.value < cls.min_value:
                logger.error('Worst state should not be lower than min value of commodity.  Please update tuning')
                cls.commodity_states = cls.states
            elif state_zero.value > cls.min_value:
                state = CommodityState(value=cls.min_value, buff=BuffReference())
                cls.commodity_states = (state,) + cls.states
            else:
                cls.commodity_states = cls.states
            previous_value = cls.max_value
            index = len(cls.commodity_states)
            for state in reversed(cls.commodity_states):
                index -= 1
                if state.value >= previous_value:
                    logger.error('{0} has a lower bound value of state at index:{1} that is higher than the previous state.  Please update tuning', cls, index)
                if state.buff_add_threshold is not None:
                    threshold_value = state.buff_add_threshold.value
                    if threshold_value < state.value or threshold_value > previous_value:
                        logger.error('{0} add buff threshold is out of range for state at index:{1}.  Please update tuning', cls, index)
                previous_value = state.value
                while state.buff is not None and state.buff.buff_type is not None:
                    state.buff.buff_type.add_owning_commodity(cls)

    @classmethod
    def _verify_tuning_callback(cls):
        if cls.visible and (cls.ui_visible_distress_threshold < cls.min_value or cls.ui_visible_distress_threshold > cls.max_value):
            logger.error('{} visible distress value {} is outside the min{} / max {} range.  Please update tuning', cls, cls.ui_visible_distress_threshold, cls.min_value, cls.max_value)

    def __init__(self, tracker, core=False):
        self._allow_convergence_callback_to_activate = False
        self._buff_handle = None
        super().__init__(tracker, self.get_initial_value())
        self._core = core
        self._buff_handle = None
        self._buff_threshold_callback = None
        self._current_state_index = None
        self._current_state_ge_callback_data = None
        self._current_state_lt_callback_data = None
        self._off_lot_callback_data = None
        self._distress_buff_handle = None
        self._exit_distress_callback_data = None
        self._distress_callback_data = None
        self._failure_callback_data = None
        self._convergence_callback_data = None
        self._suppress_client_updates = False
        self.force_apply_buff_on_start_up = False
        self.force_buff_reason = None
        if getattr(self.tracker.owner, 'is_simulating', True):
            activate_convergence_callback = self.default_value != self.get_value()
            self.on_initial_startup(from_init=True, activate_convergence_callback=activate_convergence_callback)

    @classproperty
    def initial_value_range(cls):
        return cls.initial_tuning._value_range

    @classproperty
    def use_auto_satisfy_curve_as_initial_value(cls):
        return cls.initial_tuning._use_auto_satisfy_curve_as_initial_value

    @classmethod
    def get_initial_value(cls):
        if cls.initial_value_range is None:
            return cls.initial_value
        return random.uniform(cls.initial_value_range.lower_bound, cls.initial_value_range.upper_bound)

    @classproperty
    def use_stat_value_on_initialization(cls):
        return cls.use_stat_value_on_init

    @property
    def core(self):
        return self._core

    @core.setter
    def core(self, value):
        self._core = value

    @property
    def is_visible(self):
        return self.visible

    def _setup_commodity_distress(self):
        if self.commodity_distress is not None:
            self._distress_callback_data = self.create_callback(Threshold(self.commodity_distress.threshold_value, operator.le), self._enter_distress)

    def _setup_commodity_failure(self):
        if self.commodity_failure is not None:
            self._failure_callback_data = self.create_callback(self.commodity_failure.threshold, self._commodity_fail)

    def on_initial_startup(self, from_init=False, activate_convergence_callback=True):
        self._setup_commodity_distress()
        if self._distress_callback_data is not None:
            self.add_callback_data(self._distress_callback_data)
        self._setup_commodity_failure()
        if self._failure_callback_data is not None:
            self.add_callback_data(self._failure_callback_data)
        if self.commodity_states:
            self._remove_state_callback()
            current_value = self.get_value()
            new_state_index = self._find_state_index(current_value)
            if self._current_state_index != new_state_index:
                self._set_state(new_state_index, current_value, from_init=from_init, send_client_update=False)
            self._add_state_callback()
        self.decay_enabled = not self.tracker.owner.is_locked(self)
        self.force_apply_buff_on_start_up = False
        if self.force_buff_reason is not None and self._buff_handle is not None:
            current_state = self.commodity_states[self._current_state_index]
            self.tracker.owner.set_buff_reason(current_state.buff.buff_type, self.force_buff_reason, use_replacement=True)
            self.force_buff_reason = None
        if self.remove_on_convergence and self._convergence_callback_data is None:
            self._convergence_callback_data = self.create_callback(Threshold(self.convergence_value, operator.eq), self._remove_self_from_tracker)
            if activate_convergence_callback:
                self.add_callback_data(self._convergence_callback_data)
                self._allow_convergence_callback_to_activate = False
            else:
                self._allow_convergence_callback_to_activate = True

    @contextlib.contextmanager
    def _suppress_client_updates_context_manager(self, from_load=False, is_rate_change=True):
        if self._suppress_client_updates:
            yield None
        else:
            self._suppress_client_updates = True
            try:
                yield None
            finally:
                self._suppress_client_updates = False
                if not from_load:
                    self.send_commodity_progress_msg(is_rate_change=is_rate_change)

    def _commodity_telemetry(self, hook, desired_state_index):
        if not self.tracker.owner.is_sim:
            return
        with telemetry_helper.begin_hook(writer, hook, sim=self.tracker.get_sim()) as hook:
            guid = getattr(self, 'guid64', None)
            if guid is not None:
                hook.write_guid('stat', self.guid64)
            else:
                logger.info('{} does not have a guid64', self)
            hook.write_int('oldd', self._current_state_index)
            hook.write_int('news', desired_state_index)

    def _update_state_up(self, stat_instance):
        with self._suppress_client_updates_context_manager():
            current_value = self.get_value()
            desired_state_index = self._find_state_index(current_value)
            if desired_state_index == self._current_state_index:
                desired_state_index = self._find_state_index(current_value + EPSILON)
            if desired_state_index != self._current_state_index:
                self._remove_state_callback()
                self._commodity_telemetry(TELEMETRY_HOOK_STATE_UP, desired_state_index)
                while self._current_state_index < desired_state_index:
                    next_index = self._current_state_index + 1
                    self._set_state(next_index, current_value, send_client_update=next_index == desired_state_index)
                self._update_state_callback(desired_state_index)
            else:
                logger.warn('{} update state up was called, but state did not change. current state_index:{}', self, self._current_state_index, owner='msantander')

    def _update_state_down(self, stat_instance):
        with self._suppress_client_updates_context_manager():
            current_value = self.get_value()
            desired_state_index = self._find_state_index(self.get_value())
            if desired_state_index == self._current_state_index:
                desired_state_index = self._find_state_index(current_value - EPSILON)
            if desired_state_index != self._current_state_index:
                self._remove_state_callback()
                self._commodity_telemetry(TELEMETRY_HOOK_STATE_DOWN, desired_state_index)
                while self._current_state_index > desired_state_index:
                    prev_index = self._current_state_index - 1
                    self._set_state(prev_index, current_value, send_client_update=prev_index == desired_state_index)
                self._update_state_callback(desired_state_index)
            else:
                logger.warn('{} update state down was called, but state did not change. current state_index:{}', self, self._current_state_index, owner='msantander')

    def _update_state_callback(self, desired_state_index):
        new_state_index = self._find_state_index(self.get_value())
        if new_state_index > desired_state_index:
            self._update_state_up(self)
        elif new_state_index < desired_state_index:
            self._update_state_down(self)
        else:
            self._add_state_callback()

    def _state_reset_callback(self, stat_instance, time):
        self._update_buff(self._get_change_rate_without_decay())

    def _remove_self_from_tracker(self, _):
        tracker = self._tracker
        if tracker is not None:
            tracker.remove_statistic(self.stat_type)

    def _off_lot_simulation_callback(self, _):
        self.add_value(self._off_lot_simulation.value)

    def start_low_level_simulation(self):
        if self._off_lot_simulation is None:
            self.decay_enabled = False
            return
        self._off_lot_callback_data = self.add_callback(self._off_lot_simulation.threshold, self._off_lot_simulation_callback)
        self.decay_enabled = True

    def stop_low_level_simulation(self):
        self.decay_enabled = False
        if self._off_lot_callback_data is not None:
            self.remove_callback(self._off_lot_callback_data)

    def stop_regular_simulation(self):
        self._remove_state_callback()
        self.decay_enabled = False
        if self._convergence_callback_data is not None:
            self.remove_callback(self._convergence_callback_data)
            self._convergence_callback_data = None
        if self._distress_callback_data is not None:
            self.remove_callback(self._distress_callback_data)
            self._distress_callback_data = None
        if self.commodity_distress is not None:
            self._exit_distress(self, True)
        if self._failure_callback_data is not None:
            self.remove_callback(self._failure_callback_data)
            self._failure_callback_data = None

    def _find_state_index(self, current_value):
        index = len(self.commodity_states) - 1
        while index >= 0:
            state = self.commodity_states[index]
            if current_value >= state.value:
                return index
            index -= 1
        return 0

    def _add_state_callback(self):
        next_state_index = self._current_state_index + 1
        if next_state_index < len(self.commodity_states):
            self._current_state_ge_callback_data = self.add_callback(Threshold(self.commodity_states[next_state_index].value, operator.ge), self._update_state_up, on_callback_alarm_reset=self._state_reset_callback)
        if self.commodity_states[self._current_state_index].value > self.min_value:
            self._current_state_lt_callback_data = self.add_callback(Threshold(self.commodity_states[self._current_state_index].value, operator.lt), self._update_state_down, on_callback_alarm_reset=self._state_reset_callback)

    def _remove_state_callback(self):
        if self._current_state_ge_callback_data is not None:
            self.remove_callback(self._current_state_ge_callback_data)
            self._current_state_ge_callback_data = None
        if self._current_state_lt_callback_data is not None:
            self.remove_callback(self._current_state_lt_callback_data)
            self._current_state_lt_callback_data = None
        if self._buff_threshold_callback is not None:
            self.remove_callback(self._buff_threshold_callback)
            self._buff_threshold_callback = None

    def _get_next_buff_commodity_decaying_to(self):
        transition_into_buff_id = 0
        if self._current_state_index is not None and self._current_state_index > 0:
            current_value = self.get_value()
            buff_tunable_ref = None
            if self.convergence_value <= current_value:
                buff_tunable_ref = self.commodity_states[self._current_state_index - 1].buff
            else:
                next_state_index = self._current_state_index + 1
                if next_state_index < len(self.commodity_states):
                    buff_tunable_ref = self.commodity_states[next_state_index].buff
            if buff_tunable_ref is not None:
                buff_type = buff_tunable_ref.buff_type
                if buff_type is not None and buff_type.visible:
                    transition_into_buff_id = buff_type.guid64
        return transition_into_buff_id

    def _add_buff_from_state(self, commodity_state):
        owner = self.tracker.owner
        if owner.is_sim:
            buff_tuning = commodity_state.buff
            transition_into_buff_id = self._get_next_buff_commodity_decaying_to() if buff_tuning.buff_type.visible else 0
            self._buff_handle = owner.add_buff(buff_tuning.buff_type, buff_reason=buff_tuning.buff_reason, commodity_guid=self.guid64, change_rate=self._get_change_rate_without_decay(), transition_into_buff_id=transition_into_buff_id)

    def _add_buff_callback(self, _):
        current_state = self.commodity_states[self._current_state_index]
        self.remove_callback(self._buff_threshold_callback)
        self._buff_threshold_callback = None
        self._add_buff_from_state(current_state)

    def _set_state(self, new_state_index, current_value, from_init=False, send_client_update=True):
        new_state = self.commodity_states[new_state_index]
        old_state_index = self._current_state_index
        self._current_state_index = new_state_index
        if self._buff_threshold_callback is not None:
            self.remove_callback(self._buff_threshold_callback)
            self._buff_threshold_callback = None
        if self._buff_handle is not None:
            self.tracker.owner.remove_buff(self._buff_handle)
            self._buff_handle = None
        if new_state.buff.buff_type:
            if new_state.buff_add_threshold is not None and not self.force_apply_buff_on_start_up and not new_state.buff_add_threshold.compare(current_value):
                self._buff_threshold_callback = self.add_callback(new_state.buff_add_threshold, self._add_buff_callback)
            else:
                self._add_buff_from_state(new_state)
        if (old_state_index is not None or from_init) and new_state.loot_list_on_enter is not None and self.tracker.owner.is_sim:
            resolver = event_testing.resolver.SingleSimResolver(self.tracker.owner)
            while True:
                for loot_action in new_state.loot_list_on_enter:
                    loot_action.apply_to_resolver(resolver)
        if send_client_update:
            self.send_commodity_progress_msg()

    def _enter_distress(self, stat_instance):
        if self.tracker.owner.get_sim_instance() is None:
            return
        if self.commodity_distress.buff.buff_type is not None:
            if self._distress_buff_handle is None:
                self._distress_buff_handle = self.tracker.owner.add_buff(self.commodity_distress.buff.buff_type, self.commodity_distress.buff.buff_reason, commodity_guid=self.guid64)
            else:
                logger.error('Distress Buff Handle is not none when entering Commodity Distress for {}.', self, owner='jjacobson')
        if self._exit_distress_callback_data is None:
            self._exit_distress_callback_data = self.add_callback(Threshold(self.commodity_distress.threshold_value, operator.gt), self._exit_distress)
        else:
            logger.error('Exit Distress Callback Data is not none when entering Commodity Distress for {}.', self, owner='jjacobson')
        self.tracker.owner.enter_distress(self)
        sim = self.tracker.owner.get_sim_instance()
        for si in itertools.chain(sim.si_state, sim.queue):
            while self.stat_type in si.commodity_flags:
                return
        context = interactions.context.InteractionContext(self.tracker.owner.get_sim_instance(), interactions.context.InteractionContext.SOURCE_AUTONOMY, interactions.priority.Priority.High, insert_strategy=QueueInsertStrategy.NEXT, bucket=interactions.context.InteractionBucketType.DEFAULT)
        self.tracker.owner.get_sim_instance().push_super_affordance(self.commodity_distress.distress_interaction, None, context)

    def _exit_distress(self, stat_instance, on_removal=False):
        if self._distress_buff_handle is not None:
            self.tracker.owner.remove_buff(self._distress_buff_handle)
            self._distress_buff_handle = None
        elif self.commodity_distress.buff.buff_type is not None and not on_removal:
            logger.error('Distress Buff Handle is none when exiting Commodity Distress for {}.', self, owner='jjacobson')
        if self._exit_distress_callback_data is not None:
            self.remove_callback(self._exit_distress_callback_data)
            self._exit_distress_callback_data = None
        elif not on_removal:
            logger.error('Exit distress called before exit distress callback has been setup for {}.', self, owner='jjacobson')
        self.tracker.owner.exit_distress(self)

    def _commodity_fail_object(self, stat_instance):
        context = interactions.context.InteractionContext(None, interactions.context.InteractionContext.SOURCE_SCRIPT, interactions.priority.Priority.Critical, bucket=interactions.context.InteractionBucketType.DEFAULT)
        owner = self.tracker.owner
        for failure_interaction in self.commodity_failure.failure_interactions:
            if not failure_interaction.immediate or not failure_interaction.simless:
                logger.error('Trying to use a non-immediate and/or non-simless\n                interaction as a commodity failure on an object. Object\n                commodity failures can only push immediate, simless\n                interactions. - trevor')
                break
            aop = interactions.aop.AffordanceObjectPair(failure_interaction, owner, failure_interaction, None)
            while aop.test_and_execute(context):
                break

    def _commodity_fail(self, stat_instance):
        owner = self.tracker.owner
        if not owner.is_sim:
            return self._commodity_fail_object(stat_instance)
        sim = owner.get_sim_instance()
        if sim is None:
            return
        context = interactions.context.InteractionContext(sim, interactions.context.InteractionContext.SOURCE_SCRIPT, interactions.priority.Priority.Critical, bucket=interactions.context.InteractionBucketType.DEFAULT)
        for failure_interaction in self.commodity_failure.failure_interactions:
            while sim.push_super_affordance(failure_interaction, None, context):
                break

    def fixup_on_sim_instantiated(self):
        sim = self.tracker.owner
        if self.time_passage_fixup_type() == CommodityTimePassageFixupType.FIXUP_USING_TIME_ELAPSED:
            time_sim_was_saved = sim.time_sim_was_saved
            if time_sim_was_saved is not None:
                if not sim.is_locked(self):
                    self.decay_enabled = True
                    self._last_update = time_sim_was_saved
                    self._update_value()
                    self.decay_enabled = False
        elif self.time_passage_fixup_type() == CommodityTimePassageFixupType.FIXUP_USING_AUTOSATISFY_CURVE and (sim.is_npc or self._off_lot_simulation is None):
            self.set_to_auto_satisfy_value()

    def set_to_auto_satisfy_value(self):
        if self.use_autosatisfy_curve and self._auto_satisfy_curve:
            now = services.time_service().sim_now
            time_sim_was_saved = self.tracker.owner.time_sim_was_saved
            if time_sim_was_saved is None and not self.use_auto_satisfy_curve_as_initial_value or time_sim_was_saved == now:
                return False
            random_time_offset = random.uniform(-1*self.auto_satisfy_curve_random_time_offset, self.auto_satisfy_curve_random_time_offset)
            now += interval_in_sim_minutes(random_time_offset)
            current_hour = now.hour() + now.minute()/date_and_time.MINUTES_PER_HOUR
            auto_satisfy_value = self._auto_satisfy_curve.get(current_hour)
            maximum_auto_satisfy_time = interval_in_sim_minutes(self.maximum_auto_satisfy_time)
            if time_sim_was_saved is None or time_sim_was_saved + maximum_auto_satisfy_time <= now:
                self._last_update = services.time_service().sim_now
                self.set_user_value(auto_satisfy_value)
                return True
            if time_sim_was_saved >= now:
                return False
            interpolation_time = (now - time_sim_was_saved).in_ticks()/maximum_auto_satisfy_time.in_ticks()
            current_value = self.get_user_value()
            new_value = (auto_satisfy_value - current_value)*interpolation_time + current_value
            self._last_update = services.time_service().sim_now
            self.set_user_value(new_value)
            return True
        return False

    def on_remove(self, on_destroy=False):
        super().on_remove(on_destroy=on_destroy)
        self.stop_regular_simulation()
        self.stop_low_level_simulation()
        if self._buff_handle is not None:
            self.tracker.owner.remove_buff(self._buff_handle, on_destroy=on_destroy)
            self._buff_handle = None
        if self._distress_buff_handle is not None:
            self.tracker.owner.remove_buff(self._distress_buff_handle, on_destroy=on_destroy)
            self._distress_buff_handle = None

    def _activate_convergence_callback(self):
        if self._allow_convergence_callback_to_activate:
            if self._convergence_callback_data is not None:
                self.add_callback_data(self._convergence_callback_data)
            self._allow_convergence_callback_to_activate = False

    def set_value(self, value, from_load=False, **kwargs):
        with self._suppress_client_updates_context_manager(from_load=from_load, is_rate_change=False):
            if not from_load:
                change = value - self.get_value()
                self._update_buff(change)
            super().set_value(value, from_load=from_load, **kwargs)
            if not from_load and self.visible:
                self.send_commodity_progress_msg(is_rate_change=False)
            self._update_buff(0)
            self._activate_convergence_callback()

    def _on_statistic_modifier_changed(self, notify_watcher=True):
        super()._on_statistic_modifier_changed(notify_watcher=notify_watcher)
        self.send_commodity_progress_msg()
        self._update_buff(self._get_change_rate_without_decay())
        self._update_callbacks()
        self._activate_convergence_callback()

    def _recalculate_modified_decay_rate(self):
        super()._recalculate_modified_decay_rate()
        if self._decay_rate_modifier > 1:
            self._update_buff(-self._decay_rate_modifier)
        else:
            self._update_buff(0)

    @property
    def buff_handle(self):
        return self._buff_handle

    def _update_buff(self, change_rate):
        if self._buff_handle is not None:
            self.tracker.owner.buff_commodity_changed(self._buff_handle, change_rate=change_rate)

    @property
    def state_index(self):
        return self._current_state_index

    @classmethod
    def get_state_index_matches_buff_type(cls, buff_type):
        if cls.commodity_states:
            for index in range(len(cls.commodity_states)):
                state = cls.commodity_states[index]
                if state.buff is None:
                    pass
                while state.buff.buff_type is buff_type:
                    return index

    @classproperty
    def max_value(cls):
        return cls.max_value_tuning

    @classproperty
    def min_value(cls):
        return cls.min_value_tuning

    @classproperty
    def autonomy_weight(cls):
        return cls.weight

    @classproperty
    def default_value(cls):
        if not cls.initial_as_default:
            return cls._default_convergence_value
        return cls.initial_value

    @classproperty
    def is_skill(cls):
        return False

    @classproperty
    def add_if_not_in_tracker(cls):
        return cls._add_if_not_in_tracker

    @classproperty
    def max_simulate_time_on_load(cls):
        return cls._max_simulate_time_on_load

    def time_passage_fixup_type(self):
        return self._time_passage_fixup_type

    @classmethod
    def get_categories(cls):
        return cls._categories

    def send_commodity_progress_msg(self, is_rate_change=True):
        commodity_msg = self.create_commmodity_update_msg(is_rate_change=is_rate_change)
        if commodity_msg is None:
            return
        send_sim_commodity_progress_update_message(self.tracker.owner, commodity_msg)

    def create_commmodity_update_msg(self, is_rate_change=True):
        if self.tracker is None or not self.tracker.owner.is_sim:
            return
        if not self.visible:
            return
        if not self.commodity_states:
            return
        if self.state_index is None:
            return
        if self._suppress_client_updates:
            return
        commodity_msg = Commodities_pb2.CommodityProgressUpdate()
        commodity_msg.commodity_id = self.guid64
        commodity_msg.current_value = self.get_value()
        commodity_msg.rate_of_change = self.get_change_rate()
        commodity_msg.commodity_state_index = self.state_index
        commodity_msg.is_rate_change = is_rate_change
        return commodity_msg

class RuntimeCommodity(Commodity):
    __qualname__ = 'RuntimeCommodity'
    INSTANCE_SUBCLASSES_ONLY = True

    @classmethod
    def generate(cls, name):
        ProxyClass = type(cls)(name, (cls,), {'INSTANCE_SUBCLASSES_ONLY': True})
        ProxyClass.reloadable = False
        key = sims4.resources.get_resource_key(name, ProxyClass.tuning_manager.TYPE)
        ProxyClass.tuning_manager.register_tuned_class(ProxyClass, key)
        return ProxyClass

