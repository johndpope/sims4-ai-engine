import random
from objects.definition_manager import TunableDefinitionList
from objects.puddles import PuddleChoices, PuddleLiquid, PuddleSize, create_puddle
from sims4.tuning.tunable import TunableTuple, TunableRange, TunableInterval, TunableSimMinute, Tunable
from sims4.tuning.tunable_base import GroupNames
from singletons import DEFAULT
from statistics.statistic import Statistic
import alarms
import build_buy
import date_and_time
import objects.game_object
import objects.system
import placement
import sims4.log
import sims4.random
logger = sims4.log.Logger('Puddles')

class Puddle(objects.game_object.GameObject):
    __qualname__ = 'Puddle'
    WEED_DEFINITIONS = TunableDefinitionList(description='\n        Possible weed objects which can be spawned by evaporation.')
    PLANT_DEFINITIONS = TunableDefinitionList(description='\n        Possible plant objects which can be spawned by evaporation.')
    INSTANCE_TUNABLES = {'indoor_evaporation_time': TunableInterval(description='\n            Number of SimMinutes this puddle should take to evaporate when \n            created indoors.\n            ', tunable_type=TunableSimMinute, default_lower=200, default_upper=300, minimum=1, tuning_group=GroupNames.PUDDLES), 'outdoor_evaporation_time': TunableInterval(description='\n            Number of SimMinutes this puddle should take to evaporate when \n            created outdoors.\n            ', tunable_type=TunableSimMinute, default_lower=30, default_upper=60, minimum=1, tuning_group=GroupNames.PUDDLES), 'evaporation_outcome': TunableTuple(nothing=TunableRange(int, 5, minimum=1, description='Relative chance of nothing.'), weeds=TunableRange(int, 2, minimum=0, description='Relative chance of weeds.'), plant=TunableRange(int, 1, minimum=0, description='Relative chance of plant.'), tuning_group=GroupNames.PUDDLES), 'intial_stat_value': TunableTuple(description='\n            This is the starting value for the stat specified.  This controls \n            how long it takes to mop this puddle.\n            ', stat=Statistic.TunableReference(description='\n                The stat used for mopping puddles.\n                '), value=Tunable(description='\n                The initial value this puddle should have for the mopping stat.\n                The lower the value (-100,100), the longer it takes to mop up.\n                ', tunable_type=int, default=-20), tuning_group=GroupNames.PUDDLES)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._puddle_liquid = None
        self._puddle_size = None
        self._evaporate_alarm_handle = None
        self.statistic_tracker.set_value(self.intial_stat_value.stat, self.intial_stat_value.value)

    @property
    def size_count(self):
        if self._puddle_size == PuddleSize.SmallPuddle:
            return 1
        if self._puddle_size == PuddleSize.MediumPuddle:
            return 2
        if self._puddle_size == PuddleSize.LargePuddle:
            return 3

    def place_puddle(self, target, max_distance, ids_to_ignore=DEFAULT):
        destroy_puddle = True
        try:
            if ids_to_ignore is DEFAULT:
                ids_to_ignore = (self.id,)
            else:
                ids_to_ignore.append(self.id)
            flags = placement.FGLSearchFlag.ALLOW_GOALS_IN_SIM_POSITIONS
            flags = flags | placement.FGLSearchFlag.ALLOW_GOALS_IN_SIM_INTENDED_POSITIONS
            flags = flags | placement.FGLSearchFlag.STAY_IN_SAME_CONNECTIVITY_GROUP
            if target.is_on_active_lot():
                flags = flags | placement.FGLSearchFlag.SHOULD_TEST_BUILDBUY
            else:
                flags = flags | placement.FGLSearchFlag.SHOULD_TEST_ROUTING
                flags = flags | placement.FGLSearchFlag.USE_SIM_FOOTPRINT
            flags = flags | placement.FGLSearchFlag.CALCULATE_RESULT_TERRAIN_HEIGHTS
            flags = flags | placement.FGLSearchFlag.DONE_ON_MAX_RESULTS
            radius_target = target
            while radius_target.parent is not None:
                radius_target = radius_target.parent
            if radius_target.is_part:
                radius_target = radius_target.part_owner
            fgl_context = placement.FindGoodLocationContext(starting_position=target.position + target.forward*radius_target.object_radius, starting_orientation=sims4.random.random_orientation(), starting_routing_surface=target.routing_surface, object_id=self.id, ignored_object_ids=ids_to_ignore, max_distance=max_distance, search_flags=flags)
            (position, orientation) = placement.find_good_location(fgl_context)
            if position is not None:
                destroy_puddle = False
                self.location = sims4.math.Location(sims4.math.Transform(position, orientation), target.routing_surface)
                self.fade_in()
                self.start_evaporation()
                return True
            return False
        finally:
            if destroy_puddle:
                self.destroy(source=self, cause='Failed to place puddle.')

    def try_grow_puddle(self):
        if self._puddle_size == PuddleSize.LargePuddle:
            return
        if self._puddle_size == PuddleSize.MediumPuddle:
            puddle = create_puddle(PuddleSize.LargePuddle, puddle_liquid=self._puddle_liquid)
        else:
            puddle = create_puddle(PuddleSize.MediumPuddle, puddle_liquid=self._puddle_liquid)
        if puddle.place_puddle(self, 1, ids_to_ignore=[self.id]):
            if self._evaporate_alarm_handle is not None:
                alarms.cancel_alarm(self._evaporate_alarm_handle)
            self.fade_and_destroy()
            return puddle

    def start_evaporation(self):
        if self._evaporate_alarm_handle is not None:
            alarms.cancel_alarm(self._evaporate_alarm_handle)
        if self.is_outside:
            time = self.outdoor_evaporation_time.random_float()
        else:
            time = self.indoor_evaporation_time.random_float()
        self._evaporate_alarm_handle = alarms.add_alarm(self, date_and_time.create_time_span(minutes=time), self.evaporate)

    def evaporate(self, handle):
        if self.in_use:
            self.start_evaporation()
            return
        if self.is_on_natural_ground():
            defs_to_make = sims4.random.weighted_random_item([(self.evaporation_outcome.nothing, None), (self.evaporation_outcome.weeds, self.WEED_DEFINITIONS), (self.evaporation_outcome.plant, self.PLANT_DEFINITIONS)])
            if defs_to_make:
                def_to_make = random.choice(defs_to_make)
                obj_location = sims4.math.Location(sims4.math.Transform(self.position, sims4.random.random_orientation()), self.routing_surface)
                (result, _) = build_buy.test_location_for_object(None, def_to_make.id, obj_location, [self])
                if result:
                    obj = objects.system.create_object(def_to_make)
                    obj.opacity = 0
                    obj.location = self.location
                    obj.fade_in()
        self._evaporate_alarm_handle = None
        self.fade_and_destroy()

    def load_object(self, object_data):
        super().load_object(object_data)
        if PuddleChoices.reverse_lookup is None:
            PuddleChoices.reverse_lookup = {}
            for (liquid, sizelists) in PuddleChoices.PUDDLE_DEFINITIONS.items():
                for (size, definitions) in sizelists.items():
                    for definition in definitions:
                        PuddleChoices.reverse_lookup[definition] = (liquid, size)
        if self.definition in PuddleChoices.reverse_lookup:
            (liquid, size) = PuddleChoices.reverse_lookup[self.definition]
            self._puddle_liquid = liquid
            self._puddle_size = size
            return
        logger.error('Unknown size/liquid for puddle: {} on load.', self, owner='nbaker')
        self._puddle_size = PuddleSize.MediumPuddle
        self._puddle_liquid = PuddleLiquid.WATER

