from collections import Counter
import operator
import weakref
from broadcasters.environment_score.environment_score_tuning import EnvironmentScoreTuning
import alarms
import clock
import gsi_handlers
import services
import sims4.log
import sims4.reload
logger = sims4.log.Logger('Environment Score')
with sims4.reload.protected(globals()):
    environment_score_enabled = True
    environment_score_mood_commodities = []

def _initialize_environment_score_commodities(instance_manager=None):
    global environment_score_mood_commodities
    if instance_manager is None:
        instance_manager = services.get_instance_manager(sims4.resources.Types.MOOD)
    environment_score_mood_commodities = []
    for mood in instance_manager.types.values():
        while mood.environment_scoring_commodity is not None:
            environment_score_mood_commodities.append(mood.environment_scoring_commodity)

if not sims4.reload.currently_reloading:
    services.get_instance_manager(sims4.resources.Types.MOOD).add_on_load_complete(_initialize_environment_score_commodities)

class EnvironmentScoreMixin:
    __qualname__ = 'EnvironmentScoreMixin'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._environment_score_commodity = None
        self._environment_score_broadcasters = weakref.WeakSet()
        self._environment_score_alarm_handle = None
        self._dirty = True

    def add_environment_score_broadcaster(self, broadcaster):
        self._remove_linked_broadcasters(broadcaster)
        self._environment_score_broadcasters.add(broadcaster)
        self._dirty = True
        self.schedule_environment_score_update()

    def _remove_linked_broadcasters(self, broadcaster):
        for linked_broadcaster in broadcaster.get_linked_broadcasters_gen():
            self._environment_score_broadcasters.discard(linked_broadcaster)

    def remove_environment_score_broadcaster(self, broadcaster):
        self._environment_score_broadcasters.discard(broadcaster)
        self._dirty = True
        self.schedule_environment_score_update()

    def _start_environment_score(self):
        self._clear_environment_score()
        self._dirty = True
        self.schedule_environment_score_update()

    def _stop_environment_score(self):
        self._clear_environment_score()
        self._dirty = True

    def _get_broadcasting_environment_score_objects_gen(self):
        for broadcaster in self._environment_score_broadcasters:
            if broadcaster.broadcasting_object is not None:
                yield broadcaster.broadcasting_object
            for linked_broadcaster in broadcaster.get_linked_broadcasters_gen():
                while linked_broadcaster.broadcasting_object is not None:
                    yield linked_broadcaster.broadcasting_object

    def schedule_environment_score_update(self, force_run=False):

        def _update_environment_score_callback(timeline):
            if not force_run and self.queue is not None and self.transition_controller is not None:
                self._environment_score_alarm_handle = None
                return
            self._update_environment_score()

        if self._environment_score_alarm_handle is not None and force_run:
            alarms.cancel_alarm(self._environment_score_alarm_handle)
            self._environment_score_alarm_handle = None
        if self._environment_score_alarm_handle is None:
            self._environment_score_alarm_handle = alarms.add_alarm(self, clock.interval_in_real_seconds(1.0), _update_environment_score_callback, repeating=False)

    def _update_mood_commodities(self, total_mood_scores):
        current_mood_commodity = self._environment_score_commodity
        largest_mood = None
        if total_mood_scores:
            largest_mood = total_mood_scores.most_common(1)[0][0]
        if largest_mood is not None:
            self._environment_score_commodity = largest_mood.environment_scoring_commodity
            if self._environment_score_commodity is not None:
                new_value = total_mood_scores.get(largest_mood, 0)
                if self._environment_score_commodity is current_mood_commodity:
                    self.commodity_tracker.set_value(self._environment_score_commodity, new_value)
                else:
                    self.commodity_tracker.remove_statistic(current_mood_commodity)
                    self.commodity_tracker.add_statistic(self._environment_score_commodity)
                    self.commodity_tracker.set_value(self._environment_score_commodity, new_value)
                    logger.error('Environment Scoring: {} has no commodity set for environment scoring.', largest_mood, owner='rmccord')
            else:
                logger.error('Environment Scoring: {} has no commodity set for environment scoring.', largest_mood, owner='rmccord')
        elif current_mood_commodity is not None:
            self.commodity_tracker.remove_statistic(current_mood_commodity)
        return largest_mood

    def _update_positive_and_negative_commodities(self, negative_score, positive_score):
        negative_stat = self.commodity_tracker.get_statistic(EnvironmentScoreTuning.NEGATIVE_ENVIRONMENT_SCORING, add=True)
        positive_stat = self.commodity_tracker.get_statistic(EnvironmentScoreTuning.POSITIVE_ENVIRONMENT_SCORING, add=True)
        if negative_stat.get_value() != negative_score:
            negative_stat.set_value(negative_score)
        if negative_stat.buff_handle is not None:
            contribute_positive_scoring = False
        else:
            contribute_positive_scoring = True
        if contribute_positive_scoring and positive_stat.get_value() != positive_score:
            positive_stat.set_value(positive_score)
        elif not contribute_positive_scoring:
            positive_stat.set_value(0)

    def _update_environment_score(self):
        try:
            if not self._dirty:
                return
            if not environment_score_enabled or self.is_hidden():
                self._clear_environment_score()
                return
            total_mood_scores = Counter()
            total_negative_score = 0
            total_positive_score = 0
            if gsi_handlers.sim_handlers_log.environment_score_archiver.enabled:
                contributing_objects = []
                object_contributions = []
            environment_score_objects = set(self._get_broadcasting_environment_score_objects_gen())
            for obj in environment_score_objects:
                (mood_scores, negative_score, positive_score, contributions) = obj.get_environment_score(self)
                total_negative_score += negative_score
                total_positive_score += positive_score
                total_mood_scores.update(mood_scores)
                while gsi_handlers.sim_handlers_log.environment_score_archiver.enabled and (sum(mood_scores.values()) != 0 or negative_score != 0 or positive_score != 0):
                    contributing_objects.append((obj, mood_scores, negative_score, positive_score))
                    object_contributions.extend(contributions)
            self._update_positive_and_negative_commodities(total_negative_score, total_positive_score)
            largest_mood = self._update_mood_commodities(total_mood_scores)
            if gsi_handlers.sim_handlers_log.environment_score_archiver.enabled and (contributing_objects or total_negative_score != 0 or total_positive_score != 0):
                gsi_handlers.sim_handlers_log.log_environment_score(self.id, largest_mood, total_mood_scores.get(largest_mood, 0), self._environment_score_commodity, total_negative_score, EnvironmentScoreTuning.NEGATIVE_ENVIRONMENT_SCORING, total_positive_score, EnvironmentScoreTuning.POSITIVE_ENVIRONMENT_SCORING, contributing_objects, object_contributions)
            self._dirty = False
        finally:
            self._environment_score_alarm_handle = None

    def _clear_environment_score(self):
        for commodity in environment_score_mood_commodities:
            while self.commodity_tracker.has_statistic(commodity):
                self.commodity_tracker.remove_statistic(commodity)
        self._environment_score_commodity = None
        if self.commodity_tracker.has_statistic(EnvironmentScoreTuning.NEGATIVE_ENVIRONMENT_SCORING):
            self.commodity_tracker.remove_statistic(EnvironmentScoreTuning.NEGATIVE_ENVIRONMENT_SCORING)
        if self.commodity_tracker.has_statistic(EnvironmentScoreTuning.POSITIVE_ENVIRONMENT_SCORING):
            self.commodity_tracker.remove_statistic(EnvironmentScoreTuning.POSITIVE_ENVIRONMENT_SCORING)
        if self._environment_score_alarm_handle is not None:
            alarms.cancel_alarm(self._environment_score_alarm_handle)
            self._environment_score_alarm_handle = None

