import collections
import math
import operator
from filters.tunable import TunableSimFilter
from objects import ALL_HIDDEN_REASONS
from protocolbuffers import GameplaySaveData_pb2
from sims.household import HouseholdType
from sims4.tuning.tunable import HasTunableSingletonFactory, Tunable, TunableIntervalLiteral, TunableRange, TunableTuple, AutoFactoryInit, TunableVariant, TunableSet, TunableReference, TunableMapping, TunableRegionDescription, TunablePercent, TunableInterval
from story_progression import StoryProgressionFlags
from tunable_time import TunableTimeOfDay, TunableTimeOfWeek, Days
import services
import sims4.log
import sims4.resources
import sims.genealogy_tracker
logger = sims4.log.Logger('StoryProgression')
gameplay_neighborhood_data_constants = GameplaySaveData_pb2.GameplayNeighborhoodData

class TunableStoryProgressionActionVariant(TunableVariant):
    __qualname__ = 'TunableStoryProgressionActionVariant'

    def __init__(self, **kwargs):
        super().__init__(initial_population=StoryProgressionInitialPopulation.TunableFactory(locked_args={'_time_of_week': None}), max_population=StoryProgressionActionMaxPopulation.TunableFactory(), genealogy_pruning=StoryProgressionGenealogyPruning.TunableFactory(), populate_action=StoryProgressionPopulateAction.TunableFactory(), pregnancy_progress=StoryProgressionActionPregnancy.TunableFactory())

class _StoryProgressionAction(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = '_StoryProgressionAction'
    FACTORY_TUNABLES = {'description': '\n            An action defines behavior that is to occur on a certain\n            subset of Sims affected by Story Progression.\n            '}

    def should_process(self, options):
        return True

    def process_action(self, story_progression_flags):
        raise NotImplementedError

class _StoryProgressionFilterAction(_StoryProgressionAction):
    __qualname__ = '_StoryProgressionFilterAction'
    FACTORY_TUNABLES = {'sim_filter': TunableSimFilter.TunableReference(description='\n            The subset of Sims this action can operate on.\n            ')}

    def _get_filter(self):
        return self.sim_filter()

    def _apply_action(self, sim_info):
        raise NotImplementedError

    def _pre_apply_action(self):
        pass

    def _post_apply_action(self):
        pass

    def process_action(self, story_progression_flags):

        def _on_filter_request_complete(results, *_, **__):
            if results is None:
                return
            self._pre_apply_action()
            for result in results:
                sim_info = result.sim_info
                while sim_info is not None and not sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS):
                    self._apply_action(sim_info)
            self._post_apply_action()

        services.sim_filter_service().submit_filter(self._get_filter(), _on_filter_request_complete, household_id=services.active_household_id())

class StoryProgressionActionPregnancy(_StoryProgressionFilterAction):
    __qualname__ = 'StoryProgressionActionPregnancy'

    def _apply_action(self, sim_info):
        pregnancy_tracker = sim_info.pregnancy_tracker
        pregnancy_tracker.update_pregnancy()

class StoryProgressionActionMaxPopulation(_StoryProgressionFilterAction):
    __qualname__ = 'StoryProgressionActionMaxPopulation'
    FACTORY_TUNABLES = {'max_population': TunableIntervalLiteral(description='\n            Max number of game generated sims.\n            ', tunable_type=int, default=180, minimum=0), 'relationship_depth_weight': Tunable(description='\n            Multiplier used to modify relationship depth to determine how\n            important depth is in culling score.  The higher the multiplier the\n            more relationship depth is added to culling score.  The lower the\n            culling score the more likely sim has a chance of being deleted.\n            ', tunable_type=float, default=0.5), 'relationship_tracks_multiplier': Tunable(description='\n            Multiply the number of tracks by this multiplier to provide an\n            additional score to determine if sim should be culled. The higher\n            the multiplier the more the number of tracks bonus is added to\n            culling score.  The lower the culling score the more likely sim has\n            a chance of being deleted.\n            ', tunable_type=float, default=2), 'max_last_instantiated': TunableRange(description='\n            Number of days before "last time instantiated" is no longer\n            considered for culling.\n            \n            Example: if set to 10, after 10 sim days only relationship depth\n            and track are considered when scoring sim for culling.\n            ', tunable_type=float, default=30, minimum=1), 'instantiated_weight': Tunable(description='\n            Multiplier used to modify since "last time instantiated" to determine\n            how important depth is in culling score.\n            ', tunable_type=float, default=0.5), 'time_of_day': TunableTuple(description='\n            Only run this action when it is between a certain time of day.\n            ', start_time=TunableTimeOfDay(default_hour=2), end_time=TunableTimeOfDay(default_hour=6))}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._household_scores = collections.defaultdict(list)

    def should_process(self, options):
        if len(services.sim_info_manager()) < self.max_population.random_int():
            return False
        current_time = services.time_service().sim_now
        if not current_time.time_between_day_times(self.time_of_day.start_time, self.time_of_day.end_time):
            return False
        return True

    def _get_culling_score(self, sim_info):
        total_score = 0
        for relationship in sim_info.relationship_tracker:
            rel_score = relationship.depth*self.relationship_depth_weight
            rel_score += len(relationship.bit_track_tracker)*self.relationship_tracks_multiplier
            if sim_info.time_sim_was_saved is None:
                last_time_in_days = self.max_last_instantiated/2
            else:
                last_time_in_days = services.time_service().sim_now - sim_info.time_sim_was_saved
                last_time_in_days = last_time_in_days.in_days()
            rel_score += (self.max_last_instantiated - last_time_in_days)*self.instantiated_weight
            total_score += rel_score
        return total_score

    def _apply_action(self, sim_info):
        household = sim_info.household
        if household.get_household_type() != HouseholdType.GAME_CREATED:
            return
        if household.home_zone_id != 0:
            return
        culling_score = self._get_culling_score(sim_info)
        self._household_scores[household.id].append(culling_score)

    def _pre_apply_action(self):
        self._household_scores.clear()

    def _post_apply_action(self):
        if self._household_scores:
            logger.info('Pruning households - Start - households scored: {} current sim info count: {}', len(self._household_scores), len(services.sim_info_manager()))
            household_scores = []
            household_manager = services.household_manager()
            for (household_id, score_list) in self._household_scores.items():
                household = household_manager.get(household_id)
                if len(household) != len(score_list):
                    pass
                household_scores.append((household_id, sum(score_list)/len(score_list)))
            if not household_scores:
                return
            sorted_options = sorted(household_scores, key=operator.itemgetter(1))
            max_sim_infos = self.max_population.random_int()
            sim_info_manager = services.sim_info_manager()
            while sorted_options:
                while len(sim_info_manager) >= max_sim_infos:
                    (household_id_to_remove, _) = sorted_options.pop(0)
                    logger.info('Pruning household: {}', household_id_to_remove)
                    household_manager.prune_household(household_id_to_remove)
            logger.info('Pruning households - End - current sim info count: {}', len(services.sim_info_manager()))
            self._household_scores.clear()
        else:
            logger.info('No Households to prune')

class StoryProgressionGenealogyPruning(_StoryProgressionAction):
    __qualname__ = 'StoryProgressionGenealogyPruning'
    FACTORY_TUNABLES = {'_time_of_week': TunableTuple(description='\n        Only run this action when it is between a certain time of the week.\n        ', start_time=TunableTimeOfWeek(default_day=Days.SUNDAY, default_hour=2), end_time=TunableTimeOfWeek(default_day=Days.SUNDAY, default_hour=6))}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._last_time_checked = None

    def should_process(self, options):
        if services.active_household() is None:
            return False
        current_time = services.time_service().sim_now
        if not current_time.time_between_week_times(self._time_of_week.start_time(), self._time_of_week.end_time()):
            return False
        return True

    def process_action(self, story_progression_flags):
        self._last_time_checked = services.time_service().sim_now
        with sims.genealogy_tracker.genealogy_caching():
            for household in tuple(services.household_manager().values()):
                household.prune_distant_relatives()

class StoryProgressionPopulateAction(_StoryProgressionAction):
    __qualname__ = 'StoryProgressionPopulateAction'
    RESIDENTIAL_VENUES = TunableSet(description='\n        A set of venue references that are considered residential lots.\n        ', tunable=TunableReference(services.get_instance_manager(sims4.resources.Types.VENUE)))
    FACTORY_TUNABLES = {'_region_to_population_density': TunableMapping(description='\n        Based on region what percent of available lots will be filled.\n        ', key_name='Region Description', key_type=TunableRegionDescription(), value_name='Population Density', value_type=TunableTuple(density=TunablePercent(description='\n                Percent of how much of the residential lots will be occupied of\n                all the available lots in that region.  If the current lot\n                density is greater than this value, then no household will be\n                moved in.\n                ', default=40), min_empty=TunableRange(description='\n                Minimum number of empty lots that should stay empty for this neighborhood.\n                ', tunable_type=int, default=2, minimum=0))), '_time_of_week': TunableTuple(description='\n        Only run this action when it is between a certain time of the week.\n        ', start_time=TunableTimeOfWeek(default_day=Days.SUNDAY, default_hour=2), end_time=TunableTimeOfWeek(default_day=Days.SUNDAY, default_hour=6))}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._last_time_checked = None

    def _get_neighborhood_proto(self):
        neighborhood_id = services.current_zone().neighborhood_id
        if neighborhood_id == 0:
            return
        return services.get_persistence_service().get_neighborhood_proto_buff(neighborhood_id)

    def _get_neighborhood_availability_data(self, neighborhood_proto_buff):
        num_zones_filled = 0
        available_zone_ids = set()
        venue_manager = services.get_instance_manager(sims4.resources.Types.VENUE)
        for lot_owner_info in neighborhood_proto_buff.lots:
            while True:
                for lot_owner in lot_owner_info.lot_owner:
                    while lot_owner.household_id > 0:
                        num_zones_filled += 1
                        break
                while lot_owner_info.venue_key == 0 or venue_manager.get(lot_owner_info.venue_key) in self.RESIDENTIAL_VENUES:
                    if lot_owner_info.lot_template_id > 0:
                        available_zone_ids.add(lot_owner_info.zone_instance_id)
        return (num_zones_filled, available_zone_ids)

    def _should_process(self):
        client = services.client_manager().get_first_client()
        if client is None:
            return False
        if client.account is None or client.household is None:
            return False
        neighborhood_population_service = services.neighborhood_population_service()
        if neighborhood_population_service is None:
            return False
        if neighborhood_population_service.is_processing_requests:
            return False
        return True

    def should_process(self, options):
        if not self._should_process():
            return False
        if options & StoryProgressionFlags.ALLOW_POPULATION_ACTION:
            current_time = services.time_service().sim_now
            if not current_time.time_between_week_times(self._time_of_week.start_time(), self._time_of_week.end_time()):
                return False
            if self._last_time_checked is not None:
                time_elapsed = current_time - self._last_time_checked
                if time_elapsed.in_days() <= 1:
                    return False
        else:
            return False
        return True

    def _zone_population_completed_callback(self, success):
        pass

    def _add_population_request(self, desired_population_data, neighborhood_proto_buff, try_existing_households, max_to_fill=None):
        (num_zones_filled, available_zone_ids) = self._get_neighborhood_availability_data(neighborhood_proto_buff)
        if len(available_zone_ids) <= desired_population_data.min_empty:
            return False
        neighborhood_population_service = services.neighborhood_population_service()
        if neighborhood_population_service is None:
            return
        num_desired_zones_filled = math.floor((num_zones_filled + len(available_zone_ids))*desired_population_data.density)
        if num_zones_filled < num_desired_zones_filled:
            num_zones_to_fill = num_desired_zones_filled - num_zones_filled - desired_population_data.min_empty
            if num_zones_to_fill <= 0:
                return False
            if max_to_fill is not None:
                num_zones_to_fill = min(max_to_fill, num_zones_to_fill)
            return neighborhood_population_service.add_population_request(num_zones_to_fill, neighborhood_proto_buff.neighborhood_id, self._zone_population_completed_callback, available_zone_ids, try_existing_households)
        return False

    def process_action(self, story_progression_flags):
        self._last_time_checked = services.time_service().sim_now
        client = services.client_manager().get_first_client()
        if client is None:
            return
        neighborhood_proto_buff = self._get_neighborhood_proto()
        if neighborhood_proto_buff is None:
            return
        desired_population_data = self._region_to_population_density.get(neighborhood_proto_buff.region_id, None)
        if desired_population_data is not None:
            self._add_population_request(desired_population_data, neighborhood_proto_buff, True, max_to_fill=1)

class StoryProgressionInitialPopulation(StoryProgressionPopulateAction):
    __qualname__ = 'StoryProgressionInitialPopulation'
    FACTORY_TUNABLES = {'_homeless_households': TunableInterval(description='\n        Random number of homeless households to create.\n        ', tunable_type=int, default_lower=1, default_upper=3, minimum=0)}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._homeless_households_completed = False

    @property
    def _initial_population_complete(self):
        if not self._homeless_households_completed:
            return False
        neighborhood_proto_buff = self._get_neighborhood_proto()
        if neighborhood_proto_buff is None:
            return True
        return neighborhood_proto_buff.gameplay_data.npc_population_state == gameplay_neighborhood_data_constants.COMPLETED

    def should_process(self, options):
        if not self._should_process():
            return False
        if self._initial_population_complete:
            return False
        return True

    def _zone_population_completed_callback(self, success):
        neighborhood_proto_buff = self._get_neighborhood_proto()
        if success:
            neighborhood_proto_buff.gameplay_data.npc_population_state = gameplay_neighborhood_data_constants.COMPLETED

    def _homeless_household_completed_callback(self, success):
        self._homeless_households_completed = success

    def process_action(self, story_progression_flags):
        neighborhood_population_service = services.neighborhood_population_service()
        if neighborhood_population_service is None:
            return
        households = services.household_manager().values()
        num_homeless_households = sum(1 for household in households if household.home_zone_id == 0)
        if num_homeless_households >= self._homeless_households.lower_bound:
            self._homeless_household_completed_callback(True)
        else:
            neighborhood_population_service.add_homeless_household_request(self._homeless_households.random_int(), self._homeless_household_completed_callback)
        neighborhood_proto_buff = self._get_neighborhood_proto()
        if neighborhood_proto_buff is None:
            return
        if StoryProgressionFlags.ALLOW_INITIAL_POPULATION not in story_progression_flags:
            self._zone_population_completed_callback(True)
            return
        if neighborhood_proto_buff.gameplay_data.npc_population_state != gameplay_neighborhood_data_constants.COMPLETED:
            neighborhood_proto_buff.gameplay_data.npc_population_state = gameplay_neighborhood_data_constants.STARTED
            desired_population_data = self._region_to_population_density.get(neighborhood_proto_buff.region_id, None)
            if desired_population_data is not None:
                self._add_population_request(desired_population_data, neighborhood_proto_buff, False)
            else:
                self._zone_population_completed_callback(True)

