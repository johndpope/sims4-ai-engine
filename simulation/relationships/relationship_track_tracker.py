from relationships.global_relationship_tuning import RelationshipGlobalTuning
from singletons import DEFAULT
from statistics.statistic_tracker import StatisticTracker
import services
import sims4.log
logger = sims4.log.Logger('Relationship', default_owner='rez')

class RelationshipTrackTracker(StatisticTracker):
    __qualname__ = 'RelationshipTrackTracker'

    def __init__(self, relationship):
        super().__init__()
        self._relationship = relationship

    @property
    def relationship(self):
        return self._relationship

    def get_statistic(self, stat_type, add=False):
        if stat_type is DEFAULT:
            stat_type = RelationshipGlobalTuning.REL_INSPECTOR_TRACK
        return super().get_statistic(stat_type, add)

    def trigger_test_event(self, sim_info, event):
        if sim_info is None:
            return
        services.get_event_manager().process_event(event, sim_info=sim_info, sim_id=self._relationship.sim_id, target_sim_id=self._relationship.target_sim_id)

    def save(self):
        raise NotImplementedError

    def load(self, load_list):
        raise NotImplementedError

    def enable_selectable_sim_track_decay(self, to_enable=True):
        for track in self._statistics.values():
            while track.decay_only_affects_selectable_sims:
                logger.debug('    Updating track {} for {}', track, self._relationship)
                track.decay_enabled = to_enable

    def are_all_tracks_that_cause_culling_at_convergence(self):
        tracks_that_cause_culling_at_convergence = [track for track in self._statistics.values() if track.causes_delayed_removal_on_convergence]
        if not tracks_that_cause_culling_at_convergence:
            return False
        for track in tracks_that_cause_culling_at_convergence:
            while not track.is_at_convergence():
                return False
        return True

