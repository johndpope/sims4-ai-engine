import operator
from sims4.math import Threshold
import sims4.tuning.tunable
import sims4.utils
import statistics.continuous_statistic
import statistics.tunable
logger = sims4.log.Logger('Relationship', default_owner='rez')

class _DecayOverrideNode:
    __qualname__ = '_DecayOverrideNode'

    def __init__(self, lower_bound, upper_bound, decay_override):
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.decay_override = decay_override

    def __repr__(self):
        return '_DecayOverrideNode: {} from {} to {}'.format(self.decay_override, self.lower_bound, self.upper_bound)

class TunedContinuousStatistic(statistics.continuous_statistic.ContinuousStatistic):
    __qualname__ = 'TunedContinuousStatistic'
    INSTANCE_SUBCLASSES_ONLY = True
    INSTANCE_TUNABLES = {'decay_rate': sims4.tuning.tunable.TunableRange(description='\n            The decay rate for this stat (per sim minute).\n            ', tunable_type=float, default=0.001, minimum=0.0), '_decay_rate_overrides': sims4.tuning.tunable.TunableList(description='\n            A list of decay rate overrides.  Whenever the value of the stat falls\n            into this range, the decay rate is overridden with the value specified.\n            This overrides the base decay, so all decay modifiers will still apply.\n            The ranges are inclusive on the lower bound and exclusive on the upper \n            bound.  Overlapping values are not allowed and will behave in an undefined\n            manner.\n            ', tunable=sims4.tuning.tunable.TunableTuple(description='\n                The interval/decay_override pair.\n                ', interval=sims4.tuning.tunable.TunableInterval(description='\n                    The range at which this override will apply.  It is inclusive\n                    on the lower bound and exclusive on the upper bound.\n                    ', tunable_type=float, default_lower=-100, default_upper=100), decay_override=sims4.tuning.tunable.Tunable(description='\n                    The value that the base decay will be overridden with.\n                    ', tunable_type=float, default=0.0))), '_default_convergence_value': sims4.tuning.tunable.Tunable(description='\n            The value toward which the stat decays"\n            ', tunable_type=float, default=0.0), 'stat_asm_param': statistics.tunable.TunableStatAsmParam.TunableFactory(), 'min_value_tuning': sims4.tuning.tunable.Tunable(description='\n            The minimum value for this stat.\n            ', tunable_type=float, default=-100), 'max_value_tuning': sims4.tuning.tunable.Tunable(description='\n            The maximum value for this stat.', tunable_type=float, default=100), 'initial_value': sims4.tuning.tunable.Tunable(description='\n            The initial value for this stat.', tunable_type=float, default=0.0), 'persisted_tuning': sims4.tuning.tunable.Tunable(description="\n            Whether this statistic will persist when saving a Sim or an object.\n            For example, a Sims's SI score statistic should never persist.\n            ", tunable_type=bool, default=True)}

    def __init__(self, tracker, initial_value):
        super().__init__(tracker, initial_value)
        if not self.tracker.suppress_callback_setup_during_load:
            self._add_decay_override_callbacks()

    @sims4.utils.classproperty
    def max_value(cls):
        return cls.max_value_tuning

    @sims4.utils.classproperty
    def min_value(cls):
        return cls.min_value_tuning

    def get_asm_param(self):
        return self.stat_asm_param.get_asm_param(self)

    @sims4.utils.classproperty
    def persisted(cls):
        return cls.persisted_tuning

    @classmethod
    def _tuning_loaded_callback(cls):
        cls._initialize_decay_override_list()

    @classmethod
    def _initialize_decay_override_list(cls):
        if not cls._decay_rate_overrides:
            cls._decay_override_list = ()
            return
        decay_override_list = [_DecayOverrideNode(override_data.interval.lower_bound, override_data.interval.upper_bound, override_data.decay_override) for override_data in cls._decay_rate_overrides]
        decay_override_list.sort(key=lambda node: node.lower_bound)
        final_decay_override_list = []
        last_lower_bound = cls.max_value + 1
        for node in reversed(decay_override_list):
            if last_lower_bound > node.upper_bound:
                default_node = _DecayOverrideNode(node.upper_bound, last_lower_bound, cls.decay_rate)
                final_decay_override_list.insert(0, default_node)
            elif last_lower_bound < node.upper_bound:
                logger.error('Tuning error: two nodes are overlapping in continuous statistic decay overrides: {}', cls)
                node.upper_bound = last_lower_bound
            final_decay_override_list.insert(0, node)
            last_lower_bound = node.lower_bound
        if final_decay_override_list and final_decay_override_list[0].lower_bound > cls.min_value:
            default_node = _DecayOverrideNode(cls.min_value, final_decay_override_list[0].lower_bound, cls.decay_rate)
            final_decay_override_list.insert(0, default_node)
        cls._decay_override_list = tuple(final_decay_override_list)

    def fixup_callbacks_during_load(self):
        super().fixup_callbacks_during_load()
        self._add_decay_override_callbacks()

    def _add_decay_override_callbacks(self):
        if not self._decay_rate_overrides:
            return
        for override in self._decay_override_list:
            threshold = Threshold(override.lower_bound, operator.ge)
            self.add_callback(threshold, self._on_decay_rate_override_changed)
            threshold = Threshold(override.upper_bound, operator.lt)
            self.add_callback(threshold, self._on_decay_rate_override_changed)

    def _on_decay_rate_override_changed(self, _):
        value = self.get_value()
        for override in self._decay_override_list:
            while value >= override.lower_bound and value < override.upper_bound:
                self._decay_rate_override = override.decay_override
                self._update_callbacks(resort_list=False)
                return
        logger.error('No node found for stat value of {} on {}', value, self)

