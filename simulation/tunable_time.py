import date_and_time
import enum
import sims4.tuning.tunable


class Days(enum.Int):
    __qualname__ = 'Days'
    SUNDAY = 0
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6


def date_and_time_from_hours_minutes(hour, minute):
    return date_and_time.create_date_and_time(hours=hour, minutes=minute)


def date_and_time_from_days_hours_minutes(day, hour, minute):
    return date_and_time.create_date_and_time(
        days=day, hours=hour, minutes=minute)


class TunableTimeOfDay(sims4.tuning.tunable.TunableSingletonFactory):
    __qualname__ = 'TunableTimeOfDay'
    FACTORY_TYPE = staticmethod(date_and_time_from_hours_minutes)

    def __init__(
            self,
            description='An Hour(24Hr) and Minute representing a time relative to the beginning of a day.',
            default_hour=12,
            default_minute=0,
            **kwargs):
        super().__init__(
            hour=sims4.tuning.tunable.TunableRange(
                int, default_hour,
                0, 23, description='Hour of the day'),
            minute=sims4.tuning.tunable.TunableRange(
                int, default_minute,
                0, 59, description='Minute of Hour'),
            description=description,
            **kwargs)


class TunableTimeOfWeek(sims4.tuning.tunable.TunableFactory):
    __qualname__ = 'TunableTimeOfWeek'
    FACTORY_TYPE = staticmethod(date_and_time_from_days_hours_minutes)

    def __init__(
            self,
            description='A Day, Hour(24hr) and Minute representing a time relative to the beginning of a week.',
            default_day=Days.SUNDAY,
            default_hour=12,
            default_minute=0,
            **kwargs):
        super().__init__(
            day=sims4.tuning.tunable.TunableEnumEntry(Days,
                                                      default_day,
                                                      needs_tuning=True,
                                                      description=
                                                      'Day of the week'),
            hour=sims4.tuning.tunable.TunableRange(
                int, default_hour,
                0, 23, description='Hour of the day'),
            minute=sims4.tuning.tunable.TunableRange(
                int, default_minute,
                0, 59, description='Minute of Hour'),
            description=description,
            **kwargs)
