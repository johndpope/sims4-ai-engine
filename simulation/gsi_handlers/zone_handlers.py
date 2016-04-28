import services
from sims4.gsi.dispatcher import GsiHandler
from sims4.gsi.schema import GsiSchema
zone_view_schema = GsiSchema()
zone_view_schema.add_field('zoneId')

@GsiHandler('zone_view', zone_view_schema)
def generate_zone_view_data():
    zone_list = []
    for zone in services._zone_manager.objects:
        while zone.is_instantiated:
            zone_list.append({'zoneId': hex(zone.id), 'zoneName': 'ZoneName'})
    return zone_list

