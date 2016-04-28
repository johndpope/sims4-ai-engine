from protocolbuffers import SimObjectAttributes_pb2 as protocols
import services
import sims4.log
import statistics.base_statistic_tracker
logger = sims4.log.Logger('Statistic')

class StatisticTracker(statistics.base_statistic_tracker.BaseStatisticTracker):
    __qualname__ = 'StatisticTracker'

    def save(self):
        save_list = []
        for stat in self._statistics_values_gen():
            while stat.persisted:
                try:
                    statistic_data = protocols.Statistic()
                    statistic_data.name_hash = stat.guid64
                    statistic_data.value = stat.get_saved_value()
                    save_list.append(statistic_data)
                except Exception:
                    logger.exception('Exception thrown while trying to save stat {}', stat, owner='rez')
        return save_list

    def load(self, statistics):
        statistics_manager = services.get_instance_manager(sims4.resources.Types.STATISTIC)
        for statistics_data in statistics:
            stat_cls = statistics_manager.get(statistics_data.name_hash)
            if stat_cls is not None:
                self.set_value(stat_cls, statistics_data.value, from_load=True)
            else:
                logger.warn('Sim has a saved value for a statistic which is no longer defined in tuning. Discarding value.', stat_cls)

