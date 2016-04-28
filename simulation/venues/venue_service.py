import random
from build_buy import get_current_venue
from objects.system import create_object
from placement import FindGoodLocationContext, find_good_location
from sims4.math import vector_normalize
from sims4.service_manager import Service
from sims4.tuning.tunable import TunableSimMinute
from situations.service_npcs.modify_lot_items_tuning import ModifyAllLotItems
import alarms
import build_buy
import clock
import placement
import routing
import services
import sims4.log
import sims4.resources
try:
    import _zone
except ImportError:

    class _zone:
        __qualname__ = '_zone'

logger = sims4.log.Logger('Venue', default_owner='manus')

class VenueService(Service):
    __qualname__ = 'VenueService'
    SPECIAL_EVENT_SCHEDULE_DELAY = TunableSimMinute(description='\n        Number of real time seconds to wait after the loading screen before scheduling\n        special events.\n        ', default=10.0)
    VENUE_CLEANUP_ACTIONS = ModifyAllLotItems.TunableFactory()
    ELAPSED_TIME_SINCE_LAST_VISIT_FOR_CLEANUP = TunableSimMinute(description='\n        If more than this amount of sim minutes has elapsed since the lot was\n        last visited, the auto cleanup will happen.\n        ', default=720, minimum=0)

    def __init__(self):
        self._persisted_background_event_id = None
        self._persisted_special_event_id = None
        self._special_event_start_alarm = None
        self._venue = None

    @property
    def venue(self):
        return self._venue

    def _set_venue(self, venue_type):
        if venue_type is None:
            logger.error('Zone {} has invalid venue type.', services.current_zone().id)
            return False
        if type(self._venue) is venue_type:
            return False
        if self._venue is not None:
            self._venue.shut_down()
            if self._special_event_start_alarm is not None:
                alarms.cancel_alarm(self._special_event_start_alarm)
                self._special_event_start_alarm = None
        new_venue = venue_type()
        self._venue = new_venue
        return True

    def _get_venue_tuning(self, zone):
        venue_tuning = None
        venue_type = get_current_venue(zone.id)
        if venue_type is not None:
            venue_tuning = services.venue_manager().get(venue_type)
        return venue_tuning

    def set_venue_and_schedule_events(self, venue_type):
        type_changed = self._set_venue(venue_type)
        if type_changed and self._venue is not None:
            venue_tuning = services.venue_manager().get(venue_type)
            if venue_tuning is not None:
                self._create_automatic_objects(venue_tuning)
            self._venue.schedule_background_events(schedule_immediate=True)
            self._venue.schedule_special_events(schedule_immediate=False)

    def on_client_connect(self, client):
        zone = services.current_zone()
        venue_type = get_current_venue(zone.id)
        logger.assert_raise(venue_type is not None, ' Venue Type is None in on_client_connect for zone:{}', zone, owner='sscholl')
        venue_tuning = self._get_venue_tuning(zone)
        if venue_tuning is not None:
            type_changed = self._set_venue(venue_tuning)
            if type_changed:
                self._create_automatic_objects(venue_tuning)

    def _create_automatic_objects(self, venue_tuning):
        zone = services.current_zone()
        for tag_pair in venue_tuning.automatic_objects:
            try:
                existing_objects = set(zone.object_manager.get_objects_with_tag_gen(tag_pair.tag))
                while not existing_objects:
                    obj = create_object(tag_pair.default_value)
                    position = zone.lot.corners[1]
                    position += vector_normalize(zone.lot.position - position)
                    fgl_context = FindGoodLocationContext(starting_position=position, object_id=obj.id, ignored_object_ids=(obj.id,), search_flags=placement.FGLSearchFlagsDefault | placement.FGLSearchFlag.SHOULD_TEST_BUILDBUY, object_footprints=(obj.get_footprint(),))
                    (position, orientation) = find_good_location(fgl_context)
                    if position is not None:
                        obj.location = sims4.math.Location(sims4.math.Transform(position, orientation), routing.SurfaceIdentifier(zone.id, 0, routing.SURFACETYPE_WORLD))
                    else:
                        obj.destroy(source=zone, cause='Failed to place automatic object required by venue.')
            except:
                logger.error('Automatic object {} could not be created in venue {} (zone: {}).', obj_definition, venue_tuning, zone)

    def on_cleanup_zone_objects(self, client):
        zone = services.current_zone()
        if client.household_id != zone.lot.owner_household_id:
            time_elapsed = services.game_clock_service().time_elapsed_since_last_save()
            if time_elapsed.in_minutes() > self.ELAPSED_TIME_SINCE_LAST_VISIT_FOR_CLEANUP:
                cleanup = VenueService.VENUE_CLEANUP_ACTIONS()
                cleanup.modify_objects_on_active_lot()

    def initialize_venue_background_schedule(self):
        if self._venue is not None:
            self._venue.set_active_event_ids(self._persisted_background_event_id, self._persisted_special_event_id)
            situation_manager = services.current_zone().situation_manager
            schedule_immediate = self._persisted_background_event_id is None or self._persisted_background_event_id not in situation_manager
            self._venue.schedule_background_events(schedule_immediate=schedule_immediate)

    def setup_special_event_alarm(self):
        special_event_time_span = clock.interval_in_sim_minutes(self.SPECIAL_EVENT_SCHEDULE_DELAY)
        self._special_event_start_alarm = alarms.add_alarm(self, special_event_time_span, self._schedule_venue_special_events, repeating=False)

    def _schedule_venue_special_events(self, alarm_handle):
        if self._venue is not None:
            self._venue.schedule_special_events(schedule_immediate=True)

    def has_zone_for_venue_type(self, venue_types):
        venue_manager = services.get_instance_manager(sims4.resources.Types.VENUE)
        for neighborhood_proto in services.get_persistence_service().get_neighborhoods_proto_buf_gen():
            for lot_owner_info in neighborhood_proto.lots:
                zone_id = lot_owner_info.zone_instance_id
                while zone_id is not None:
                    venue_type_id = build_buy.get_current_venue(zone_id)
                    venue_type = venue_manager.get(venue_type_id)
                    if venue_type and venue_type in venue_types:
                        return True
        instance_manager = services.get_instance_manager(sims4.resources.Types.MAXIS_LOT)
        for lot_instance in instance_manager.types.values():
            while lot_instance.supports_any_venue_type(venue_types):
                return True
        return False

    def get_zones_for_venue_type(self, venue_type):
        possible_zones = []
        venue_manager = services.get_instance_manager(sims4.resources.Types.VENUE)
        for neighborhood_proto in services.get_persistence_service().get_neighborhoods_proto_buf_gen():
            for lot_owner_info in neighborhood_proto.lots:
                zone_id = lot_owner_info.zone_instance_id
                while zone_id is not None:
                    venue_type_id = build_buy.get_current_venue(zone_id)
                    if venue_manager.get(venue_type_id) is venue_type:
                        possible_zones.append(lot_owner_info.zone_instance_id)
        return possible_zones

    def get_zone_and_venue_type_for_venue_types(self, venue_types):
        possible_zones = []
        for venue_type in venue_types:
            venue_zones = self.get_zones_for_venue_type(venue_type)
            for zone in venue_zones:
                possible_zones.append((zone, venue_type))
        if possible_zones:
            return random.choice(possible_zones)
        instance_manager = services.get_instance_manager(sims4.resources.Types.MAXIS_LOT)
        for lot_instance in instance_manager.types.values():
            intersecting_venues = lot_instance.get_intersecting_venue_types(venue_types)
            while intersecting_venues:
                possible_zones.append((lot_instance, random.choice(intersecting_venues)))
        if possible_zones:
            (selected_zone, venue_type) = random.choice(possible_zones)
            current_zone = services.current_zone()
            zone_id = _zone.create_venue(current_zone.id, selected_zone.household_description, venue_type.guid64, current_zone.neighborhood_id, 'maxis_lot')
            return (zone_id, venue_type)
        return (None, None)

    def save(self, zone_data=None, **kwargs):
        if zone_data is not None and self._venue is not None:
            venue_data = zone_data.gameplay_zone_data.venue_data
            if self._venue.active_background_event_id is not None:
                venue_data.background_situation_id = self._venue.active_background_event_id
            if self._venue.active_special_event_id is not None:
                venue_data.special_event_id = self._venue.active_special_event_id

    def load(self, zone_data=None, **kwargs):
        if zone_data is not None and zone_data.HasField('gameplay_zone_data') and zone_data.gameplay_zone_data.HasField('venue_data'):
            venue_data = zone_data.gameplay_zone_data.venue_data
            if venue_data.HasField('background_situation_id'):
                self._persisted_background_event_id = venue_data.background_situation_id
            if venue_data.HasField('special_event_id'):
                self._persisted_special_event_id = venue_data.special_event_id

