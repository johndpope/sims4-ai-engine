from sims4.tuning.tunable import TunableTuple, Tunable, TunableEnumEntry, OptionalTunable
import clock
import services
import sims4.log
logger = sims4.log.Logger('AdaptiveClockSpeed', default_owner='trevor')
with sims4.reload.protected(globals()):
    first_tick_above_threshold = None
    first_tick_below_threshold = None


class TunableAdaptiveSpeed(TunableTuple):
    __qualname__ = 'TunableAdaptiveSpeed'

    def __init__(self, **kwargs):
        super().__init__(
            multipler_type=TunableEnumEntry(
                description=
                '\n                The clock multiplier type that governs the speed\n                multipliers used by the game.\n                ',
                tunable_type=clock.ClockSpeedMultiplierType,
                default=clock.ClockSpeedMultiplierType.DEFAULT),
            threshold=Tunable(
                description
                =
                '\n                A threshold to compare against the different between the\n                sim_now and game_now clock ticks. This must be a non negative\n                number. Units: ticks.\n                ',
                tunable_type=int,
                default=10000),
            duration=Tunable(
                description=
                '\n                The duration for which the game has to cross the threshold to\n                consider switching the multipler_type. Tune this to zero to\n                disable a duration before transition to the other multipliers.\n                ',
                tunable_type=int,
                default=10000),
            **kwargs)


class AdaptiveClockSpeed:
    __qualname__ = 'AdaptiveClockSpeed'
    TIME_DIFFERENCE_THRESHOLD = OptionalTunable(
        description=
        "\n        If enabled, the game will drop into the given time speed multipliers \n        when the difference in ticks between sim_now and game_clock_now\n        goes beyond a threshold for a fixed duration.\n        \n        NOTE: This tuning is shared for all machine specifications and build\n        configurations! Its important to note this distinction since you have\n        to consider the wide range between the player's build and a GPE's build\n        setup.\n        ",
        tunable=TunableTuple(
            default_speed_multiplier=TunableAdaptiveSpeed(
                description=
                '\n                The default clock speed multiplier. The game starts with this\n                speed multiplier type and always attempts to come back to it if\n                the sim_now and game_now clocks are close to each other.\n                \n                We switch to the reduced speed multiplier only after the\n                simulation has deviated for beyond the tuned threshold\n                consistently for the tuned duration.\n                '),
            reduced_speed_multiplier=TunableAdaptiveSpeed(
                description=
                '\n                The clock speed multiplier used when the difference in ticks\n                between sim_now and game_now goes beyond the threshold\n                consistently for a specified duration of ticks.\n                \n                Tune the threshold and duration that decide whether we have to\n                switch back to the default speed multipliers.\n                ')))

    @classmethod
    def update_adaptive_speed(cls):
        global first_tick_above_threshold, first_tick_below_threshold
        if not cls.TIME_DIFFERENCE_THRESHOLD:
            return
        game_clock = services.game_clock_service()
        game_speed = game_clock.clock_speed()
        if game_speed == clock.ClockSpeedMode.NORMAL or game_speed == clock.ClockSpeedMode.PAUSED:
            first_tick_above_threshold = None
            first_tick_below_threshold = None
            return
        game_clock_now_ticks = game_clock.now().absolute_ticks()
        diff = game_clock_now_ticks - services.time_service(
        ).sim_now.absolute_ticks()
        (threshold, duration) = cls._get_threshold_and_duration(game_clock)
        phase_duration = None
        if diff > threshold:
            first_tick_below_threshold = None
            if first_tick_above_threshold is None:
                first_tick_above_threshold = game_clock_now_ticks
            phase_duration = game_clock_now_ticks - first_tick_above_threshold
            if phase_duration > duration:
                multiplier_type = cls.TIME_DIFFERENCE_THRESHOLD.reduced_speed_multiplier.multipler_type
                if game_clock._set_clock_speed_multiplier_type(
                        multiplier_type):
                    first_tick_above_threshold = None
                    logger.info(
                        '[game_clock_now - sim_now] {} > {}. Switching speed multiplier type to {}.',
                        diff, threshold, multiplier_type)
        else:
            first_tick_above_threshold = None
            if first_tick_below_threshold is None:
                first_tick_below_threshold = game_clock_now_ticks
            phase_duration = game_clock_now_ticks - first_tick_below_threshold
            if phase_duration > duration:
                multiplier_type = cls.TIME_DIFFERENCE_THRESHOLD.default_speed_multiplier.multipler_type
                if game_clock._set_clock_speed_multiplier_type(
                        multiplier_type):
                    first_tick_below_threshold = None
                    logger.info(
                        '[game_clock_now - sim_now] {} < {}. Switching speed multiplier type to {}.',
                        diff, threshold, multiplier_type)
        logger.debug('{!s:35} {:7} {} {:7} Duration: {}'.format(
            game_clock.clock_speed_multiplier_type, diff, '<' if diff <
            threshold else '>', threshold, phase_duration))

    @classmethod
    def _get_threshold_and_duration(cls, game_clock):
        if game_clock.clock_speed_multiplier_type == cls.TIME_DIFFERENCE_THRESHOLD.default_speed_multiplier:
            threshold = cls.TIME_DIFFERENCE_THRESHOLD.default_speed_multiplier.threshold
            duration = cls.TIME_DIFFERENCE_THRESHOLD.default_speed_multiplier.duration
        else:
            threshold = cls.TIME_DIFFERENCE_THRESHOLD.reduced_speed_multiplier.threshold
            duration = cls.TIME_DIFFERENCE_THRESHOLD.reduced_speed_multiplier.duration
        return (threshold, duration)

    @classmethod
    def get_debugging_metrics(cls):
        game_clock = services.game_clock_service()
        game_clock_now_ticks = game_clock.now().absolute_ticks()
        deviance = game_clock.now().absolute_ticks() - services.time_service(
        ).sim_now.absolute_ticks()
        (threshold, duration) = cls._get_threshold_and_duration(game_clock)
        phase_duration = None
        if deviance > threshold:
            if first_tick_above_threshold is not None:
                phase_duration = game_clock_now_ticks - first_tick_above_threshold
        elif first_tick_below_threshold is not None:
            phase_duration = game_clock_now_ticks - first_tick_below_threshold
        return (deviance, threshold, phase_duration, duration)
