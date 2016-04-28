from sims4.tuning.dynamic_enum import DynamicEnumLocked
import enum

class ServiceNpcEndWorkReason(enum.Int):
    __qualname__ = 'ServiceNpcEndWorkReason'
    NO_WORK_TO_DO = 0
    FINISHED_WORK = 1
    FIRED = 2
    NOT_PAID = 3
    ASKED_TO_HANG_OUT = 4
    DISMISSED = 5

