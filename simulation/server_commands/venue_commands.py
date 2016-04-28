from venues.venue_service import VenueService
import build_buy
import services
import sims4.commands
import collections

@sims4.commands.Command('venues.set_venue')
def set_venue(venue_type, _connection=None):
    venue_tuning = services.venue_manager().get(venue_type)
    if venue_tuning is None:
        sims4.commands.output('Requesting an unknown venue type: {0}'.format(venue_type), _connection)
        return False
    services.current_zone().venue_service.set_venue_and_schedule_events(venue_tuning)
    return True

@sims4.commands.Command('venues.test_all_venues')
def test_all_venues(_connection=None):
    venue_manager = services.venue_manager()
    active_lot = services.active_lot()
    for venue_tuning_type in venue_manager.types:
        venue_tuning = venue_manager.get(venue_tuning_type)
        (result, result_message) = venue_tuning.lot_has_required_venue_objects(active_lot)
        venue_name = venue_tuning.__name__
        if result:
            sims4.commands.output('{0}: Active lot can become venue'.format(venue_name), _connection)
        else:
            sims4.commands.output('{0}: Active lot cannot become venue.\nFailure Reasons: {1}'.format(venue_name, result_message), _connection)
    return True

PrintVenueLog = collections.namedtuple('PrintVenueLog', ['Neighborhood_Name', 'Neighborhood_ID', 'Lot_Description_ID', 'Zone_Instance_ID', 'Venue_Tuning_Name', 'Lot_Name'])

@sims4.commands.Command('venues.print_venues')
def print_venues(_connection=None):
    current_zone = services.current_zone()
    lot = current_zone.lot
    neighborhood_id = current_zone.neighborhood_id
    lot_description_id = services.get_lot_description_id(lot.lot_id)
    world_description_id = services.get_world_description_id(current_zone.world_id)
    neighborhood_description_id = services.get_persistence_service().get_neighborhood_proto_buff(neighborhood_id).region_id

    def print_line():
        sims4.commands.output('-'*150, _connection)

    print_line()
    sims4.commands.output('Current Game Stats: \nLot: {}\nWorld/Street: {}\nRegion/Neighborhood: {}'.format(lot_description_id, world_description_id, neighborhood_description_id), _connection)
    print_line()
    venue_manager = services.get_instance_manager(sims4.resources.Types.VENUE)
    venues = []
    for neighborhood_proto in services.get_persistence_service().get_neighborhoods_proto_buf_gen():
        for lot_owner_info in neighborhood_proto.lots:
            zone_id = lot_owner_info.zone_instance_id
            while zone_id is not None:
                venue_type_id = build_buy.get_current_venue(zone_id)
                venue_type = venue_manager.get(venue_type_id)
                if venue_type is not None:
                    log = PrintVenueLog._make((neighborhood_proto.name, neighborhood_proto.region_id, lot_owner_info.lot_description_id, zone_id, venue_type.__name__, lot_owner_info.lot_name))
                    venues.append(log)
    str_format = '{:20} ({:{center}15}) {:{center}20} {:15} ({:{center}20}) {:20}'

    def print_columns():
        sims4.commands.output(str_format.format('Neighborhood_Name', 'Neighborhood_ID', 'Lot_Description_ID', 'Zone_Instance_ID', 'Venue_Tuning_Name', 'Lot_Name', center='^'), _connection)

    print_columns()
    print_line()
    for venue in sorted(venues):
        sims4.commands.output(str_format.format(venue.Neighborhood_Name, venue.Neighborhood_ID, venue.Lot_Description_ID, venue.Zone_Instance_ID, venue.Venue_Tuning_Name, venue.Lot_Name, center='^'), _connection)
    print_line()
    print_columns()

@sims4.commands.Command('venues.clean_lot')
def clean_lot(connection=None):
    cleanup = VenueService.VENUE_CLEANUP_ACTIONS()
    cleanup.modify_objects_on_active_lot()
    return True

