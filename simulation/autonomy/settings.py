from sims4.tuning.tunable import TunableEnumEntry, Tunable
import enum
import sims4.log
logger = sims4.log.Logger('Autonomy')

class AutonomyState(enum.Int):
    __qualname__ = 'AutonomyState'
    UNDEFINED = -1
    DISABLED = 0
    LIMITED_ONLY = 1
    MEDIUM = 2
    FULL = 3

class AutonomyRandomization(enum.Int):
    __qualname__ = 'AutonomyRandomization'
    UNDEFINED = -1
    DISABLED = 0
    ENABLED = 1

class AutonomySettingItem:
    __qualname__ = 'AutonomySettingItem'
    __slots__ = ('state', 'randomization')

    def __init__(self, state:AutonomyState=AutonomyState.UNDEFINED, randomization:AutonomyRandomization=AutonomyRandomization.UNDEFINED):
        self.state = state
        self.randomization = randomization

class AutonomySettings:
    __qualname__ = 'AutonomySettings'
    STARTING_DEFAULT_AUTONOMY_STATE = TunableEnumEntry(AutonomyState, AutonomyState.FULL, description='\n                                    The autonomy state for the "default" layer.  If a Sim doesn\'t have anything that overrides \n                                    their autonomy state, this will be used instead.  It is NOT used to define the default \n                                    option in the autonomy options menu, it applies to all Sims that don\'t have an overridden\n                                    autonomy state setting.  Sims in the playable household will all have an overridden \n                                    setting.')
    STARTING_DEFAULT_RANDOMIZATION = TunableEnumEntry(AutonomyRandomization, AutonomyRandomization.ENABLED, description='\n                                    The randomization state for the "default" layer.  If a Sim doesn\'t have anything \n                                    that overrides their randomization state, this will be used instead.')
    STARTING_HOUSEHOLD_AUTONOMY_STATE = TunableEnumEntry(AutonomyState, AutonomyState.FULL, description="\n                                    The default autonomy setting when one hasn't been loaded.  This is the default value for\n                                    the autonomy drop-down in the options menu.")
    STARTING_SELECTED_SIM_AUTONOMY = Tunable(bool, True, description="\n                                            The default autonomy setting for the selected sim's autonomy.  If checked, the selected\n                                            sim will behave normally according to the autonomy state.  If unchecked, the selected\n                                            sim will not run autonomy at all.")

    def __init__(self, use_tuned_defaults=False):
        if use_tuned_defaults:
            self._autonomy_settings = {AutonomyState: self.STARTING_DEFAULT_AUTONOMY_STATE, AutonomyRandomization: self.STARTING_DEFAULT_RANDOMIZATION}
        else:
            self._autonomy_settings = {AutonomyState: AutonomyState.UNDEFINED, AutonomyRandomization: AutonomyRandomization.UNDEFINED}

    def get_state_setting(self) -> AutonomyState:
        return self.get_setting(AutonomyState)

    def get_randomization_setting(self) -> AutonomyRandomization:
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return self.get_setting(AutonomyRandomization)

    def get_setting(self, autonomy_setting_class):
        setting = self._autonomy_settings.get(autonomy_setting_class)
        if setting is None:
            logger.error('Failed to find autonomy setting for class: {}', autonomy_setting_class, owner='rez')
        return setting

    def set_state_setting(self, setting_value):
        self.set_setting(AutonomyState, setting_value)

    def set_randomization_setting(self, setting_value):
        self.set_setting(AutonomyRandomization, setting_value)

    def set_setting(self, autonomy_setting_class, setting_value):
        self._autonomy_settings[autonomy_setting_class] = setting_value

