from event_testing import test_events
from sims4.localization import TunableLocalizedString
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import HasTunableReference, Tunable, TunableResourceKey
from sims4.tuning.tunable_base import ExportModes
from sims4.utils import classproperty
from singletons import DEFAULT
from statistics.base_statistic import BaseStatistic
from statistics.tunable import TunableStatAsmParam
import services
import sims4.resources

class Statistic(HasTunableReference, BaseStatistic, metaclass=HashedTunedInstanceMetaclass, manager=services.statistic_manager()):
    __qualname__ = 'Statistic'
    INSTANCE_TUNABLES = {'stat_asm_param': TunableStatAsmParam.TunableFactory(locked_args={'use_effective_skill_level': True}), 'initial_value': Tunable(int, 0, description='The initial value of this statistic.'), 'min_value_tuning': Tunable(int, 0, description='The minimum value that this statistic can reach.', export_modes=ExportModes.All), 'max_value_tuning': Tunable(int, 100, description='The minimum value that this statistic can reach.', export_modes=ExportModes.All), 'stat_name': TunableLocalizedString(description='Localized name of this resource.', export_modes=ExportModes.All), 'icon': TunableResourceKey('PNG:missing_image', resource_types=sims4.resources.CompoundTypes.IMAGE, description='Icon to be displayed for the Statistic.'), 'persisted_tuning': Tunable(bool, True, description="Whether this statistic will persist when saving a Sim or an object. For example, a Sims's SI score statistic should never persist.")}

    def __init__(self, tracker):
        super().__init__(tracker, self.initial_value)

    @classproperty
    def name(cls):
        return cls.__name__

    @classproperty
    def max_value(cls):
        return cls.max_value_tuning

    @classproperty
    def min_value(cls):
        return cls.min_value_tuning

    @classproperty
    def persisted(cls):
        return cls.persisted_tuning

    @classproperty
    def default_value(cls):
        return cls.initial_value

    def get_asm_param(self):
        return self.stat_asm_param.get_asm_param(self)

    @classproperty
    def valid_for_stat_testing(cls):
        return True

