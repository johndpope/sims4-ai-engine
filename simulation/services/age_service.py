from protocolbuffers import GameplaySaveData_pb2
from sims.aging import AgeSpeeds
from sims4.service_manager import Service
import services
import enum
game_play_options_enums = GameplaySaveData_pb2.GameplayOptions

class PlayedHouseholdSimAgingOptions(enum.Int, export=False):
    __qualname__ = 'PlayedHouseholdSimAgingOptions'
    DISABLED = Ellipsis
    ALL_PLAYED = Ellipsis
    ACTIVE_FAMILY_ONLY = Ellipsis

    @classmethod
    def convert_protocol_option_to_aging_option(cls, option_allow_aging):
        if option_allow_aging == game_play_options_enums.DISABLED:
            return cls.DISABLED
        if option_allow_aging == game_play_options_enums.ENABLED:
            return cls.ALL_PLAYED
        if option_allow_aging == game_play_options_enums.FOR_ACTIVE_FAMILY:
            return cls.ACTIVE_FAMILY_ONLY

    @classmethod
    def convert_aging_option_to_protocol_option(cls, aging_option):
        if aging_option == cls.DISABLED:
            return game_play_options_enums.DISABLED
        if aging_option == cls.ALL_PLAYED:
            return game_play_options_enums.ENABLED
        if aging_option == cls.ACTIVE_FAMILY_ONLY:
            return game_play_options_enums.FOR_ACTIVE_FAMILY

class AgeService(Service):
    __qualname__ = 'AgeService'
    DEFAULT_AGING_SPEED = AgeSpeeds(1)

    def __init__(self):
        self._aging_speed = AgeService.DEFAULT_AGING_SPEED
        self._played_household_aging_option = PlayedHouseholdSimAgingOptions.ACTIVE_FAMILY_ONLY
        self._unplayed_aging_enabled = False

    @property
    def aging_speed(self):
        return self._aging_speed

    def set_unplayed_aging_enabled(self, enabled_option):
        self._unplayed_aging_enabled = enabled_option
        services.sim_info_manager().set_aging_enabled_on_all_sims(self.is_aging_enabled_for_sim_info)

    def set_aging_enabled(self, enabled_option):
        self._played_household_aging_option = PlayedHouseholdSimAgingOptions(enabled_option)
        services.sim_info_manager().set_aging_enabled_on_all_sims(self.is_aging_enabled_for_sim_info)

    def is_aging_enabled_for_sim_info(self, sim_info):
        enabled = False
        if sim_info.household is None:
            return False
        if sim_info.household.is_persistent_npc:
            enabled = self._unplayed_aging_enabled
        elif self._played_household_aging_option == PlayedHouseholdSimAgingOptions.ACTIVE_FAMILY_ONLY:
            enabled = not sim_info.is_npc
        else:
            enabled = self._played_household_aging_option == PlayedHouseholdSimAgingOptions.ALL_PLAYED
        return enabled

    def set_aging_speed(self, speed):
        self._aging_speed = AgeSpeeds(speed)
        services.sim_info_manager().set_aging_speed_on_all_sims(self._aging_speed)

    def save_options(self, options_proto):
        options_proto.sim_life_span = self._aging_speed
        options_proto.allow_aging = PlayedHouseholdSimAgingOptions.convert_aging_option_to_protocol_option(self._played_household_aging_option)
        options_proto.unplayed_aging_enabled = self._unplayed_aging_enabled

    def load_options(self, options_proto):
        self._aging_speed = AgeSpeeds(options_proto.sim_life_span)
        self._played_household_aging_option = PlayedHouseholdSimAgingOptions.convert_protocol_option_to_aging_option(options_proto.allow_aging)
        self._unplayed_aging_enabled = options_proto.unplayed_aging_enabled
        services.sim_info_manager().set_aging_enabled_on_all_sims(self.is_aging_enabled_for_sim_info)
        services.sim_info_manager().set_aging_speed_on_all_sims(self._aging_speed)

