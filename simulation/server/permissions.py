from protocolbuffers import SimObjectAttributes_pb2 as protocols
from sims4.tuning.tunable import Tunable
import enum
import sims4.log
logger = sims4.log.Logger('Permissions')

class SimPermissions:
    __qualname__ = 'SimPermissions'

    class Settings(enum.Int):
        __qualname__ = 'SimPermissions.Settings'
        VisitationAllowed = 0
        RomanceAllowed = 1
        RomanticRelationships = 2
        PregnancyAllowed = 3
        CohabBuildBuy = 4

    DEFAULT_VISITATION_ALLOWED = Tunable(bool, True, description='Default value for Visitation Allowed permission.')
    DEFAULT_ROMANCE_ALLOWED = Tunable(bool, True, description='Default value for Romance Allowed permission.')
    DEFAULT_ROMANTIC_RELATIONSHIPS = Tunable(bool, False, description='Default value for Romantic Relationships permission.')
    DEFAULT_PREGNANCY_ALLOWED = Tunable(bool, False, description='Default value for Pregnancy Allowed permission.')
    DEFAULT_COHAB_BUILD_BUY = Tunable(bool, True, description='Default value for Cohab Build/Buy permission.')

    def __init__(self):
        self.permissions = {self.Settings.VisitationAllowed: self.DEFAULT_VISITATION_ALLOWED, self.Settings.RomanceAllowed: self.DEFAULT_ROMANCE_ALLOWED, self.Settings.RomanticRelationships: self.DEFAULT_ROMANTIC_RELATIONSHIPS, self.Settings.PregnancyAllowed: self.DEFAULT_PREGNANCY_ALLOWED, self.Settings.CohabBuildBuy: self.DEFAULT_COHAB_BUILD_BUY}

    def save(self):
        enabled_permissions = []
        for perm in SimPermissions.Settings:
            while self.permissions[perm] is True:
                enabled_permissions.append(perm)
        data = protocols.PersistableSimPermissions()
        data.enabled_permissions.extend(enabled_permissions)
        return data

    def load(self, data):
        for perm in self.permissions:
            if perm in data.enabled_permissions:
                self.permissions[perm] = True
            else:
                self.permissions[perm] = False

    def is_permission_enabled(self, permission):
        if permission in self.permissions:
            return self.permissions[permission]
        logger.error('get_permission on SimPermissions does not contain the requested permission: {}', permission)
        return False

