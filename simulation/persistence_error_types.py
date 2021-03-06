import traceback
import enum
import sims4.hash_util


class ErrorCodes(enum.Int, export=False):
    __qualname__ = 'ErrorCodes'
    NO_ERROR = 0
    GENERIC_ERROR = 100
    STOP_CACHING_STATE_FAILED = 101
    LOAD_HOUSEHOLD_AND_SIM_INFO_STATE_FAILED = 102
    SET_OBJECT_OWNERSHIP_STATE_FAILED = 103
    SPAWN_SIM_STATE_FAILED = 104
    WAIT_FOR_SIM_READY_STATE_FAILED = 105
    CLEANUP_STATE_FAILED = 106
    AWAY_ACTION_STATE_FAILED = 107
    RESTORE_SI_STATE_FAILED = 108
    SITUATION_COMMON_STATE_FAILED = 109
    WAIT_FOR_BOUNCER_STATE_FAILED = 110
    FINALIZE_OBJECT_STATE_FAILED = 111
    RESTORE_CAREER_STATE_FAILED = 112
    WAIT_FOR_NAVMESH_STATE_FAILED = 113
    INITIALIZED_FRONT_DOOR_STATE_FAILED = 114
    PREROLL_STATE_FAILED = 115
    PUSH_SIMS_GO_HOME_STATE_FAILED = 116
    SET_ACTIVE_SIM_STATE_FAILED = 117
    START_UP_COMMANDS_STATE_FAILED = 118
    START_CACHING_STATE_FAILED = 119
    FINAL_PLAYABLE_STATE_FAILED = 120
    HITTING_THEIR_MARKS_STATE_FAILED = 121
    EDIT_MODE_STATE_FAILED = 122
    SETTING_SAVE_SLOT_DATA_FAILED = 300
    SAVE_TO_SLOT_FAILED = 301
    AUTOSAVE_TO_SLOT_FAILED = 302
    SAVE_CAMERA_DATA_FAILED = 303
    CORE_SERICES_SAVE_FAILED = 400
    ZONE_SERVICES_SAVE_FAILED = 500


def generate_exception_code(error_code, exception):
    exception_callstack = ''.join(traceback.format_exception(
        type(exception), exception, exception.__traceback__))
    return '{}:{}:{}'.format(
        int(error_code), sims4.hash_util.hash64(str(exception)),
        sims4.hash_util.hash64(exception_callstack))
