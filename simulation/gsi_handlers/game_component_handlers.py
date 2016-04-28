from gsi_handlers.gameplay_archiver import GameplayArchiver
from sims4.gsi.dispatcher import GsiHandler
from sims4.gsi.schema import GsiGridSchema, GsiFieldVisualizers
import objects.components.types
import services
game_component_schema = GsiGridSchema(label='Game Component Info')
game_component_schema.add_field('current_game', label='Current Game', type=GsiFieldVisualizers.STRING)
game_component_schema.add_field('target_object', label='Target Object', type=GsiFieldVisualizers.STRING)
game_component_schema.add_field('active_sims', label='Active Sims', type=GsiFieldVisualizers.STRING)
game_component_schema.add_field('number_of_players', label='Number Of Players', type=GsiFieldVisualizers.INT)
game_component_schema.add_field('winning_sims', label='Winners', type=GsiFieldVisualizers.STRING)
game_component_schema.add_field('joinable', label='Joinable', type=GsiFieldVisualizers.STRING)
game_component_schema.add_field('requires_setup', label='Requires Setup', type=GsiFieldVisualizers.STRING)
game_component_schema.add_field('game_over', label='Game Over', type=GsiFieldVisualizers.STRING)

@GsiHandler('game_info', game_component_schema)
def generate_game_info_data():
    game_info = []
    for obj in services.object_manager().get_all_objects_with_component_gen(objects.components.types.GAME_COMPONENT):
        if obj.game_component.current_game is None:
            pass
        game = obj.game_component
        if game.active_sims:
            active_sims = ','.join([str(sim) for sim in game.active_sims])
        else:
            active_sims = 'None'
        if game.winning_team is not None:
            winning_sims = ','.join([str(sim) for sim in game.winning_team])
        else:
            winning_sims = 'None'
        entry = {'current_game': str(game.current_game), 'target_object': str(game.target_object), 'active_sims': active_sims, 'number_of_players': str(game.number_of_players), 'winning_sims': winning_sims, 'joinable': str(game.is_joinable()), 'requires_setup': str(game.requires_setup), 'game_over': str(game.game_has_ended)}
        game_info.append(entry)
    return game_info

game_log_schema = GsiGridSchema(label='Game Component Log')
game_log_schema.add_field('game_object', label='Game Object', type=GsiFieldVisualizers.STRING)
game_log_schema.add_field('log', label='Log', type=GsiFieldVisualizers.STRING, width=10)
game_log_archiver = GameplayArchiver('game_log', game_log_schema)

def archive_game_log_entry(game_object, log_entry_str):
    entry = {'game_object': str(game_object), 'log': log_entry_str}
    game_log_archiver.archive(data=entry)

