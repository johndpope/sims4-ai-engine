from build_buy import get_all_objects_with_flags_gen, BuyCategory
from distributor.ops import ShowLightColorUI
from distributor.system import Distributor
from event_testing.results import TestResult
from interactions.base.immediate_interaction import ImmediateSuperInteraction
from objects.components.lighting_component import LightingComponent
from protocolbuffers import UI_pb2 as ui_protos, DistributorOps_pb2 as distributor_op_protos
from sims4.localization import TunableLocalizedString
from sims4.tuning.tunable import Tunable, TunableTuple, OptionalTunable, TunableList, TunableColor
from sims4.tuning.tunable_base import ExportModes
import services
import sims4.log
logger = sims4.log.Logger('LightingInteractions')

class LightColorTuning:
    __qualname__ = 'LightColorTuning'

    class TunableLightTuple(TunableTuple):
        __qualname__ = 'LightColorTuning.TunableLightTuple'

        def __init__(self, *args, **kwargs):
            super().__init__(color=TunableColor.TunableColorRGBA(description='\n                    Tunable RGBA values used to set the color of a light. \n                    Tuning the A value will not do anything as it is not used.\n                    '), name=TunableLocalizedString(description='\n                The name of the color that appears when you mouse over it.\n                '))

    LIGHT_COLOR_VARIATION_TUNING = TunableList(description='\n        A list of all of the different colors you can set the lights to be.\n        ', tunable=TunableLightTuple(), maxlength=18, export_modes=(ExportModes.ClientBinary,))

class ChangeLightColorIntensityImmediateInteraction(ImmediateSuperInteraction):
    __qualname__ = 'ChangeLightColorIntensityImmediateInteraction'
    INSTANCE_TUNABLES = {'_all_lights': Tunable(description='\n            Whether or not to apply the new color and intensity values to all\n            of the lights or not.\n            ', tunable_type=bool, default=False)}

    def _run_interaction_gen(self, timeline):
        target = self.target
        r = g = b = sims4.color.MAX_INT_COLOR_VALUE
        color = target.get_light_color()
        intensity = target.get_user_intensity_overrides()
        target.set_light_dimmer_value(intensity)
        if color is not None:
            (r, g, b, _) = sims4.color.to_rgba_as_int(color)
        op = ShowLightColorUI(r, g, b, intensity, target.id, self._all_lights)
        distributor = Distributor.instance()
        distributor.add_op_with_no_owner(op)

class SwitchLightImmediateInteraction(ImmediateSuperInteraction):
    __qualname__ = 'SwitchLightImmediateInteraction'
    INSTANCE_TUNABLES = {'lighting_settings': TunableTuple(apply_to_all=Tunable(bool, False, description='Setting this value to true will cause the interaction to apply the dimmer setting to all lights on the lot'), dimmer_value=OptionalTunable(Tunable(float, 0.0), description="\n                                                                                                     When dimmer_value is enabled, it allows you to tune the dimmer value of the target object's light. \n                                                                                                     This value should be a float between 0.0 and 1.0. A value of 0.0 is off and a value\n                                                                                                     of 1.0 is completely on.\n                                                                                                     \n                                                                                                     Any tuned values outside of the range will be clamped back to within the range. For\n                                                                                                     example a negative value cannot be tuned here and will be clamped to 0.0 or off.\n                                                                                                     \n                                                                                                     When dimmer_value is disabled this will set the light(s) to be automated by the client.\n                                                                                                     \n                                                                                                     If the Apply To All checkbox is checked, then the value set here will be\n                                                                                                     set on each light object on the lot. Otherwise this value is just set on the \n                                                                                                     light that is the target of the interaction.\n                                                                                                     "))}

    @classmethod
    def _test(cls, target, context, **kwargs):
        dimmer_value = target.get_light_dimmer_value()
        if cls.lighting_settings.dimmer_value is None and dimmer_value < 0:
            return TestResult(False, 'Light is already being automated')
        return TestResult.TRUE

    def _run_interaction_gen(self, timeline):
        dimmer_value = LightingComponent.LIGHT_AUTOMATION_DIMMER_VALUE if self.lighting_settings.dimmer_value is None else self.lighting_settings.dimmer_value
        if self.lighting_settings.apply_to_all:
            for obj in get_all_objects_with_flags_gen(services.object_manager().get_all(), BuyCategory.LIGHTING):
                if not obj.lighting_component:
                    logger.error("{} is flagged as BuyCategory.Lighting but doesn't have a lighting component.", obj)
                    logger.error('Please give it a lighting component or sort it differently')
                obj.set_light_dimmer_value(dimmer_value)
        else:
            self.target.set_light_dimmer_value(dimmer_value)

