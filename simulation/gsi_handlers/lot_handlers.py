import itertools
from objects.game_object import GameObject
from sims4.gsi.dispatcher import GsiHandler, add_cheat_schema
from sims4.gsi.schema import GsiGridSchema, GSIGlobalCheatSchema, GsiFieldVisualizers
import gsi_handlers.gsi_utils
import services
import sims4
import build_buy
lot_info_schema = GsiGridSchema(label='Lot Info', auto_refresh=False)
lot_info_schema.add_field('neighborhood', label='Neighborhood', unique_field=True)
lot_info_schema.add_field('cur_lot', label='Current Lot', width=0.4)
lot_info_schema.add_field('region_id', label='Region ID', type=GsiFieldVisualizers.INT, width=0.5)
lot_info_schema.add_field('lot_desc_id', label='Description ID', type=GsiFieldVisualizers.INT, width=0.5)
lot_info_schema.add_field('zone_id', label='Zone ID', type=GsiFieldVisualizers.INT)
lot_info_schema.add_field('venue_type', label='Venue Type')
lot_info_schema.add_field('lot_name', label='Lot Name')

@GsiHandler('lot_info', lot_info_schema)
def generate_lot_info_data(*args, zone_id:int=None, filter=None, **kwargs):
    lot_infos = []
    current_zone = services.current_zone()
    lot = current_zone.lot
    neighborhood_id = current_zone.neighborhood_id
    lot_description_id = services.get_lot_description_id(lot.lot_id)
    world_description_id = services.get_world_description_id(current_zone.world_id)
    neighborhood_description_id = services.get_persistence_service().get_neighborhood_proto_buff(neighborhood_id).region_id
    venue_manager = services.get_instance_manager(sims4.resources.Types.VENUE)
    for neighborhood_proto in services.get_persistence_service().get_neighborhoods_proto_buf_gen():
        for lot_owner_info in neighborhood_proto.lots:
            zone_id = lot_owner_info.zone_instance_id
            while zone_id is not None:
                venue_type_id = build_buy.get_current_venue(zone_id)
                venue_type = venue_manager.get(venue_type_id)
                if venue_type is not None:
                    cur_info = {'neighborhood': neighborhood_proto.name, 'region_id': neighborhood_proto.region_id, 'lot_desc_id': lot_owner_info.lot_description_id, 'zone_id': zone_id, 'venue_type': venue_type.__name__, 'lot_name': lot_owner_info.lot_name, 'cur_lot': 'X' if lot_owner_info.zone_instance_id == lot.zone_id else ''}
                    lot_infos.append(cur_info)
    return lot_infos

