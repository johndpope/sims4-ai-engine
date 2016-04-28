from objects.components import componentmethod
from protocolbuffers import SimObjectAttributes_pb2 as protocols
from sims.bills_enums import Utilities
from sims4.tuning.tunable import HasTunableFactory, TunableList, TunableReference
import distributor.ops
import objects.components.types
import services
import sims4.log
logger = sims4.log.Logger('LightingComponent')

class LightingComponent(objects.components.Component, HasTunableFactory, component_name=objects.components.types.LIGHTING_COMPONENT, persistence_key=protocols.PersistenceMaster.PersistableData.LightingComponent):
    __qualname__ = 'LightingComponent'
    LIGHT_STATE_STAT = TunableReference(description="\n        The stat name used to manipulate the lights' on and off states\n        that control the effects they may or may not play\n        ", manager=services.get_instance_manager(sims4.resources.Types.STATISTIC), deferred=True)
    FACTORY_TUNABLES = {'component_interactions': TunableList(TunableReference(manager=services.affordance_manager()), description='Each interaction in this list will be added to the owner of the component.')}
    LIGHT_AUTOMATION_DIMMER_VALUE = -1
    LIGHT_DIMMER_STAT_MULTIPLIER = 100
    LIGHT_DIMMER_VALUE_OFF = 0.0
    LIGHT_DIMMER_VALUE_MAX_INTENSITY = 1.0

    def __init__(self, owner, component_interactions=None):
        super().__init__(owner)
        self._user_intensity_overrides = None
        self._owner_stat_tracker = self.owner.get_tracker(self.LIGHT_STATE_STAT)
        household = services.owning_household_of_active_lot()
        if household is None or not household.bills_manager.is_utility_delinquent(Utilities.POWER):
            self.set_light_dimmer_value(self.LIGHT_DIMMER_VALUE_MAX_INTENSITY)
        else:
            self.set_light_dimmer_value(self.LIGHT_DIMMER_VALUE_OFF)
        self._pending_dimmer_value = None
        self._color = None
        self._component_interactions = component_interactions

    @distributor.fields.ComponentField(op=distributor.ops.SetLightDimmer)
    def light_dimmer(self):
        return self._light_dimmer

    _resend_lighting = light_dimmer.get_resend()

    @light_dimmer.setter
    def light_dimmer(self, value):
        self._light_dimmer = value

    @distributor.fields.ComponentField(op=distributor.ops.SetLightColor)
    def light_color(self):
        return self._color

    _resend_color = light_color.get_resend()

    @componentmethod
    def get_light_dimmer_value(self):
        return self._light_dimmer

    @componentmethod
    def set_light_dimmer_value(self, value):
        if value != self.LIGHT_AUTOMATION_DIMMER_VALUE and value != self.LIGHT_DIMMER_VALUE_OFF and self._user_intensity_overrides is not None:
            value = self._user_intensity_overrides
        else:
            value = float(value)
        self._light_dimmer = value if value == self.LIGHT_AUTOMATION_DIMMER_VALUE else sims4.math.clamp(self.LIGHT_DIMMER_VALUE_OFF, value, self.LIGHT_DIMMER_VALUE_MAX_INTENSITY)
        stat = self._owner_stat_tracker.get_statistic(self.LIGHT_STATE_STAT)
        if stat is not None:
            self._owner_stat_tracker.set_value(self.LIGHT_STATE_STAT, sims4.math.clamp(stat.min_value, value*self.LIGHT_DIMMER_STAT_MULTIPLIER, stat.max_value))
        self._resend_lighting()

    @componentmethod
    def get_light_color(self):
        return self._color

    @componentmethod
    def set_light_color(self, color):
        self._color = color
        self._resend_color()

    @componentmethod
    def set_user_intensity_override(self, value):
        self._user_intensity_overrides = value
        self.set_light_dimmer_value(value)

    @componentmethod
    def set_automated(self):
        pass

    def on_power_off(self):
        self._pending_dimmer_value = self._light_dimmer
        self.set_light_dimmer_value(self.LIGHT_DIMMER_VALUE_OFF)

    def on_power_on(self):
        if self._pending_dimmer_value is not None:
            self._light_dimmer = self._pending_dimmer_value
            self._resend_lighting()
            self._pending_dimmer_value = None

    def component_super_affordances_gen(self, **kwargs):
        for affordance in self._component_interactions:
            yield affordance

    def component_interactable_gen(self):
        if self._component_interactions:
            yield self

    @componentmethod
    def get_user_intensity_overrides(self):
        if self._user_intensity_overrides is not None:
            return self._user_intensity_overrides
        return self.LIGHT_DIMMER_VALUE_MAX_INTENSITY

    def save(self, persistence_master_message):
        persistable_data = protocols.PersistenceMaster.PersistableData()
        persistable_data.type = protocols.PersistenceMaster.PersistableData.LightingComponent
        lighting_save = persistable_data.Extensions[protocols.PersistableLightingComponent.persistable_data]
        logger.info('[PERSISTENCE]: ----Start saving lighting component of {0}.', self.owner)
        lighting_save.dimmer_setting = self._light_dimmer
        if self._color is not None:
            lighting_save.color = self._color
        if self._pending_dimmer_value is not None:
            lighting_save.pending_dimmer_setting = self._pending_dimmer_value
        persistence_master_message.data.extend([persistable_data])
        logger.info('[PERSISTENCE]: ----End saving lighting component of {0}.', self.owner)

    def load(self, lighting_component_message):
        lighting_component_data = lighting_component_message.Extensions[protocols.PersistableLightingComponent.persistable_data]
        logger.info('[PERSISTENCE]: ----Start loading lighting component of {0}.', self.owner)
        self.set_light_dimmer_value(lighting_component_data.dimmer_setting)
        if lighting_component_data.color:
            self.set_light_color(lighting_component_data.color)
        if lighting_component_data.pending_dimmer_setting:
            self._pending_dimmer_value = lighting_component_data.pending_dimmer_setting
        logger.info('[PERSISTENCE]: ----End loading lighting component of {0}.', self.owner)

