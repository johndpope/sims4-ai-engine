from protocolbuffers import SimObjectAttributes_pb2 as protocols, Localization_pb2
from statistics.commodity_messages import send_sim_commodity_progress_update_message
from statistics.continuous_statistic_tracker import ContinuousStatisticTracker
import services
import sims4.log
logger = sims4.log.Logger('Commodities')

class CommodityTracker(ContinuousStatisticTracker):
    __qualname__ = 'CommodityTracker'

    def __init__(self, owner):
        super().__init__(owner)

    def add_statistic(self, stat_type, **kwargs):
        commodity = super().add_statistic(stat_type, **kwargs)
        return commodity

    def remove_listener(self, listener):
        stat_type = listener.stat_type
        super().remove_listener(listener)
        self._cleanup_noncore_commodity(stat_type)

    def _cleanup_noncore_commodity(self, stat_type):
        commodity = self.get_statistic(stat_type)
        if commodity is not None and (not commodity.core and commodity.remove_on_convergence) and commodity.is_at_convergence():
            self.remove_statistic(stat_type)

    def set_value(self, stat_type, value, from_load=False, **kwargs):
        super().set_value(stat_type, value, from_load=from_load, **kwargs)
        self._cleanup_noncore_commodity(stat_type)

    def add_value(self, stat_type, increment, **kwargs):
        super().add_value(stat_type, increment, **kwargs)
        self._cleanup_noncore_commodity(stat_type)

    def send_commodity_progress_update(self):
        sim = self._owner.get_sim_instance()
        if sim is not None:
            for statistic in tuple(self._statistics_values_gen()):
                if statistic.is_skill:
                    pass
                commodity_msg = statistic.create_commmodity_update_msg()
                if commodity_msg is None:
                    pass
                send_sim_commodity_progress_update_message(sim, commodity_msg)

    def on_initial_startup(self):
        for commodity in tuple(self._statistics_values_gen()):
            commodity.on_initial_startup()
        self.send_commodity_progress_update()

    def remove_non_persisted_commodities(self):
        for commodity in tuple(self._statistics_values_gen()):
            while not commodity.persisted:
                self.remove_statistic(commodity)

    def start_low_level_simulation(self):
        self.stop_regular_simulation()
        for commodity in tuple(self._statistics_values_gen()):
            commodity.start_low_level_simulation()

    def stop_low_level_simulation(self):
        for commodity in tuple(self._statistics_values_gen()):
            commodity.stop_low_level_simulation()

    def start_regular_simulation(self):
        self.stop_low_level_simulation()
        self.on_initial_startup()

    def stop_regular_simulation(self):
        for commodity in tuple(self._statistics_values_gen()):
            commodity.stop_regular_simulation()

    def save(self):
        commodities = []
        skills = []
        for stat in tuple(self._statistics_values_gen()):
            if not stat.persisted:
                pass
            try:
                if stat.is_skill:
                    message = protocols.Skill()
                    message.name_hash = stat.guid64
                    message.value = stat.get_saved_value()
                    skills.append(message)
                else:
                    message = protocols.Commodity()
                    message.name_hash = stat.guid64
                    message.value = stat.get_saved_value()
                    message.apply_buff_on_start_up = stat.buff_handle is not None
                    if stat.buff_handle is not None:
                        buff_reason = self._owner.get_buff_reason(stat.buff_handle)
                        if buff_reason is not None:
                            message.buff_reason = buff_reason
                    elif stat.force_buff_reason is not None:
                        message.buff_reason = stat.force_buff_reason
                    commodities.append(message)
            except Exception:
                logger.exception('Exception thrown while trying to save stat {}', stat)
        return (commodities, skills)

    def load(self, statistics, skip_load=False):
        statistic_manager = services.get_instance_manager(sims4.resources.Types.STATISTIC)
        for commodity_proto in statistics:
            commodity_class = statistic_manager.get(commodity_proto.name_hash)
            if commodity_class is None:
                logger.info('Trying to load unavailable STATISTIC resource: {}', commodity_proto.name_hash, owner='rez')
            if not commodity_class.persisted:
                logger.info('Trying to load unavailable STATISTIC resource: {}', commodity_proto.name_hash, owner='rez')
            if skip_load and commodity_class.remove_on_convergence:
                logger.info('Not loading {} because load is not required.', commodity_class, owner='rez')
            self.set_value(commodity_class, commodity_proto.value, from_load=True)
            while not commodity_class.is_skill:
                stat = self.get_statistic(commodity_class)
                if stat is not None:
                    stat.force_apply_buff_on_start_up = commodity_proto.apply_buff_on_start_up
                    if commodity_proto.buff_reason.hash:
                        stat.force_buff_reason = Localization_pb2.LocalizedString()
                        stat.force_buff_reason.MergeFrom(commodity_proto.buff_reason)

    def get_sim(self):
        return self._owner.get_sim_instance()

    def update_all_commodities(self):
        commodities_to_update = tuple(self._statistics_values_gen())
        for commodity in commodities_to_update:
            commodity._update_value()

    def get_all_commodities(self):
        return tuple(self._statistics.values())

