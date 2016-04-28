import weakref
from objects.components import Component, types
from objects.puddles import PuddleSize, create_puddle, PuddleLiquid
from primitives import routing_utils
from protocolbuffers import SimObjectAttributes_pb2 as protocols
from sims4.tuning.tunable import HasTunableFactory, TunableSimMinute, Tunable, TunableEnumEntry, AutoFactoryInit
import alarms
import date_and_time
import services

class FlowingPuddleComponent(Component, HasTunableFactory, AutoFactoryInit, component_name=types.FLOWING_PUDDLE_COMPONENT, persistence_key=protocols.PersistenceMaster.PersistableData.FlowingPuddleComponent, persistence_priority=25):
    __qualname__ = 'FlowingPuddleComponent'
    FACTORY_TUNABLES = {'spawn_rate': TunableSimMinute(description='\n                Length of time between puddle spawns when this object is broken.\n                ', default=20), 'max_distance': Tunable(description='\n                Max distance from this object a puddle can be spawned.  If we \n                fail to find a position in this radius, no puddle will be \n                spawned at all.\n                ', tunable_type=float, default=2.5), 'max_num_puddles': Tunable(description='\n                The maximum number of puddles this object can have created at \n                any time.  Once this number is hit, no more will be spawned \n                unless one is mopped up or evaporates. Medium Puddles count as \n                2, Large count as 3.\n                ', tunable_type=int, default=3), 'puddle_liquid': TunableEnumEntry(description='\n                The liquid of the puddle that are spawned by this component.\n                ', tunable_type=PuddleLiquid, default=PuddleLiquid.WATER)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._is_active = False
        self._puddle_alarm_handle = None
        self._puddle_refs = weakref.WeakSet()
        self._puddle_load_ids = []

    @property
    def flowing_puddle_enabled(self) -> bool:
        return self._is_active

    @flowing_puddle_enabled.setter
    def flowing_puddle_enabled(self, value):
        if self._is_active == value:
            return
        if self._is_active:
            alarms.cancel_alarm(self._puddle_alarm_handle)
            self._puddle_alarm_handle = None
        else:
            self.try_create_puddle()
            self.create_alarm()
        self._is_active = value

    def create_alarm(self):
        time_span = date_and_time.create_time_span(minutes=self.spawn_rate)
        self._puddle_alarm_handle = alarms.add_alarm(self.owner, time_span, self.try_create_puddle, repeating=True, repeating_time_span=time_span)

    def try_create_puddle(self, *args):
        count = 0
        removals = []
        for puddle in self._puddle_refs:
            dist = routing_utils.estimate_distance(self.owner, puddle)
            if dist > self.max_distance:
                removals.append(puddle)
            else:
                count += puddle.size_count
                puddle.start_evaporation()
        for puddle in removals:
            self._puddle_refs.remove(puddle)
        if count >= self.max_num_puddles:
            return False
        for puddle in self._puddle_refs:
            if puddle.in_use:
                return False
            new_puddle = puddle.try_grow_puddle()
            while new_puddle is not None:
                self._puddle_refs.remove(puddle)
                self._puddle_refs.add(new_puddle)
                return True
        puddle = create_puddle(PuddleSize.SmallPuddle, puddle_liquid=self.puddle_liquid)
        if puddle.place_puddle(self.owner, self.max_distance):
            self._puddle_refs.add(puddle)
            return True
        return False

    def save(self, persistence_master_message):
        if not self._puddle_refs and not self.flowing_puddle_enabled:
            return
        persistable_data = protocols.PersistenceMaster.PersistableData()
        persistable_data.type = protocols.PersistenceMaster.PersistableData.FlowingPuddleComponent
        puddle_component_data = persistable_data.Extensions[protocols.PersistableFlowingPuddleComponent.persistable_data]
        for puddle in self._puddle_refs:
            puddle_component_data.puddle_ids.extend((puddle.id,))
        puddle_component_data.is_active = self._is_active
        persistence_master_message.data.extend([persistable_data])

    def load(self, persistable_data):
        puddle_component_data = persistable_data.Extensions[protocols.PersistableFlowingPuddleComponent.persistable_data]
        for puddle_id in puddle_component_data.puddle_ids:
            self._puddle_load_ids.append(puddle_id)
        self._is_active = puddle_component_data.is_active
        if self._is_active:
            self.create_alarm()

    def on_finalize_load(self):
        obj_manager = services.object_manager()
        for puddle_id in self._puddle_load_ids:
            puddle = obj_manager.get(puddle_id)
            while puddle is not None:
                self._puddle_refs.add(puddle)
        self._puddle_load_ids = []

