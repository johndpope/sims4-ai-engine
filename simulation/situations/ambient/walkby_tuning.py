from scheduler import TunableDayAvailability
from sims4 import random
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import HasTunableReference, AutoFactoryInit, HasTunableSingletonFactory, Tunable, TunableMapping, TunableList, TunableTuple
import services
import sims4.log
import situations.situation
logger = sims4.log.Logger('WalkbyTuning')

class DesiredAmbientWalkbySituations(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'DesiredAmbientWalkbySituations'
    FACTORY_TUNABLES = {'desired_sim_count': Tunable(description='\n                The number of sims desired to be walking by.\n                ', tunable_type=int, default=0), 'weighted_situations': TunableList(description='\n                A weighted list of situations to be used while fulfilling the \n                desired sim count to walk by.\n                ', tunable=TunableTuple(situation=situations.situation.Situation.TunableReference(), weight=Tunable(tunable_type=int, default=1)))}

class WalkbyTuning(HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.walk_by_manager()):
    __qualname__ = 'WalkbyTuning'
    INSTANCE_TUNABLES = {'walkby_desire_by_day_of_week': TunableList(description='\n                A list of tuples declaring a relationship between days of the week\n                and walkby desire curves.\n                ', tunable=TunableTuple(description='\n                    The first value is the day of the week that maps to a desired\n                    curve of walkby population by time of the day.\n                    \n                    days_of_the_week    walkby_desire_by_time_of_day\n                        M,Th,F                time_curve_1\n                        W,Sa                  time_curve_2\n                        \n                    By production/design request we do not support multiple population\n                    curves for the same day. e.g. if you want something special to \n                    occur at noon on a Wednesday, make a unique curve for Wednesday\n                    and apply the walkby changes to it.\n                    ', days_of_the_week=TunableDayAvailability(), walkby_desire_by_time_of_day=TunableMapping(description='\n                        Each entry in the map has two columns.\n                        The first column is the hour of the day (0-24) that maps to\n                        a desired list of walkby population (second column).\n                        \n                        The entry with starting hour that is closest to, but before\n                        the current hour will be chosen.\n                        \n                        Given this tuning: \n                            hour_of_day           desired_situations\n                            6                     [(w1, s1), (w2, s2)]\n                            10                    [(w1, s2)]\n                            14                    [(w2, s5)]\n                            20                    [(w9, s0)]\n                            \n                        if the current hour is 11, hour_of_day will be 10 and desired is [(w1, s2)].\n                        if the current hour is 19, hour_of_day will be 14 and desired is [(w2, s5)].\n                        if the current hour is 23, hour_of_day will be 20 and desired is [(w9, s0)].\n                        if the current hour is 2, hour_of_day will be 20 and desired is [(w9, s0)]. (uses 20 tuning because it is not 6 yet)\n                        \n                        The entries will be automatically sorted by time.\n                        ', key_name='hour_of_day', key_type=Tunable(tunable_type=int, default=0), value_name='desired_walkby_situations', value_type=DesiredAmbientWalkbySituations.TunableFactory())))}

    @classmethod
    def _cls_repr(cls):
        return "WalkbyTuning: <class '{}.{}'>".format(cls.__module__, cls.__name__)

    @classmethod
    def _verify_tuning_callback(cls):
        if not cls.walkby_desire_by_day_of_week:
            return
        keys = set()
        for item in cls.walkby_desire_by_day_of_week:
            days = item.days_of_the_week
            for (day, enabled) in days.items():
                while enabled:
                    if day in keys:
                        logger.error('WalkbyTuning {} has multiple population curves for the day {}.', cls, day, owner='manus')
                    else:
                        keys.add(day)
            if item.walkby_desire_by_time_of_day:
                for hour in item.walkby_desire_by_time_of_day.keys():
                    while hour < 0 or hour > 24:
                        logger.error('WalkbyTuning {} has in invalid hour of the day {}. Range: [0, 24].', cls, hour, owner='manus')
            else:
                logger.error("WalkbyTuning {}'s days {} has no walkby desire population curve.", cls, days, owner='manus')

    @classmethod
    def _get_sorted_walkby_schedule(cls, day):
        walkby_schedule = []
        for item in cls.walkby_desire_by_day_of_week:
            enabled = item.days_of_the_week.get(day, None)
            while enabled:
                while True:
                    for (beginning_hour, DesiredAmbientWalkbySituations) in item.walkby_desire_by_time_of_day.items():
                        walkby_schedule.append((beginning_hour, DesiredAmbientWalkbySituations))
        walkby_schedule.sort(key=lambda entry: entry[0])
        return walkby_schedule

    @classmethod
    def _get_desired_ambient_walkby_situations(cls):
        if not cls.walkby_desire_by_day_of_week:
            return
        time_of_day = services.time_service().sim_now
        hour_of_day = time_of_day.hour()
        day = time_of_day.day()
        walkby_schedule = cls._get_sorted_walkby_schedule(day)
        entry = walkby_schedule[-1]
        desire = entry[1]
        for entry in walkby_schedule:
            if entry[0] <= hour_of_day:
                desire = entry[1]
            else:
                break
        return desire

    @classmethod
    def get_desired_sim_count(cls):
        desire = cls._get_desired_ambient_walkby_situations()
        if desire is None:
            return 0
        return desire.desired_sim_count

    @classmethod
    def get_ambient_walkby_situation(cls):
        desire = cls._get_desired_ambient_walkby_situations()
        if desire is None:
            return
        lot_id = services.active_lot_id()
        weighted_situations = tuple((item.weight, item.situation) for item in desire.weighted_situations if item.situation.can_start_walkby(lot_id))
        sitaution = random.weighted_random_item(weighted_situations)
        return sitaution

