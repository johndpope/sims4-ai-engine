from collections import namedtuple
import collections
from objects.components import Component, types
from sims4.tuning.tunable import TunableFactory
from uid import UniqueIdGenerator
import enum
import sims4.log
logger = sims4.log.Logger('CensorGridComponent')

class CensorState(enum.Int):
    __qualname__ = 'CensorState'
    OFF = 3188902525
    TORSO = 3465735571
    TORSO_PELVIS = 2022575029
    PELVIS = 2484305261
    FULLBODY = 958941257
    RHAND = 90812611
    LHAND = 2198569869

CensorRule = namedtuple('CensorRule', ['test', 'result'])
CENSOR_LOOKUP = (CensorRule(set([CensorState.FULLBODY]), CensorState.FULLBODY), CensorRule(set([CensorState.LHAND, CensorState.RHAND]), CensorState.FULLBODY), CensorRule(set([CensorState.LHAND, CensorState.TORSO]), CensorState.FULLBODY), CensorRule(set([CensorState.LHAND, CensorState.PELVIS]), CensorState.FULLBODY), CensorRule(set([CensorState.LHAND, CensorState.TORSO_PELVIS]), CensorState.FULLBODY), CensorRule(set([CensorState.RHAND, CensorState.LHAND]), CensorState.FULLBODY), CensorRule(set([CensorState.RHAND, CensorState.TORSO]), CensorState.FULLBODY), CensorRule(set([CensorState.RHAND, CensorState.PELVIS]), CensorState.FULLBODY), CensorRule(set([CensorState.RHAND, CensorState.TORSO_PELVIS]), CensorState.FULLBODY), CensorRule(set([CensorState.LHAND]), CensorState.LHAND), CensorRule(set([CensorState.RHAND]), CensorState.RHAND), CensorRule(set([CensorState.TORSO_PELVIS]), CensorState.TORSO_PELVIS), CensorRule(set([CensorState.TORSO, CensorState.PELVIS]), CensorState.TORSO_PELVIS), CensorRule(set([CensorState.TORSO]), CensorState.TORSO), CensorRule(set([CensorState.PELVIS]), CensorState.PELVIS), CensorRule(set(), CensorState.OFF))

class CensorGridComponent(Component, component_name=types.CENSOR_GRID_COMPONENT):
    __qualname__ = 'CensorGridComponent'

    def __init__(self, owner):
        super().__init__(owner)
        self._censor_grid_handles = collections.defaultdict(list)
        self._censor_state = CensorState.OFF
        self._get_next_handle = UniqueIdGenerator()

    def add_censor(self, state):
        handle = self._get_next_handle()
        self._censor_grid_handles[handle] = state
        self._update_censor_state()
        return handle

    def remove_censor(self, handle):
        self._censor_grid_handles.pop(handle)
        self._update_censor_state()

    def _update_censor_state(self):
        new_state = self._censor_state
        handle_values = set(self._censor_grid_handles.values())
        for rule in CENSOR_LOOKUP:
            while rule.test.issubset(handle_values):
                new_state = rule.result
                break
        if new_state != self._censor_state:
            self.owner.censor_state = new_state
            self._censor_state = new_state

class TunableCensorGridComponent(TunableFactory):
    __qualname__ = 'TunableCensorGridComponent'
    FACTORY_TYPE = CensorGridComponent

    def __init__(self, description='Manages censor grid handles on an object.', **kwargs):
        super().__init__(description=description, **kwargs)

