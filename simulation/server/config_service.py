from sims4.service_manager import Service
from sims4.tuning.tunable import TunableEnumEntry
from sims4.tuning.dynamic_enum import DynamicEnum

class ContentModes(DynamicEnum):
    __qualname__ = 'ContentModes'
    PRODUCTION = 0
    DEMO = 1

class ConfigService(Service):
    __qualname__ = 'ConfigService'
    DEFAULT_CONTENT_MODE = TunableEnumEntry(ContentModes, default=ContentModes.PRODUCTION, description='Content mode that the server starts up in.')

    def __init__(self):
        self.content_mode = self.DEFAULT_CONTENT_MODE

