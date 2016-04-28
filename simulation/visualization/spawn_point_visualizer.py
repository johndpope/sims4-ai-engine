from debugvis import Context
from sims4.color import Color
from sims4.tuning.tunable import TunableMapping, TunableEnumEntry, Tunable
import services
import sims4.log
logger = sims4.log.Logger('Debugvis')

class SpawnPointVisualizer:
    __qualname__ = 'SpawnPointVisualizer'
    SPAWN_POINT_COLORS = TunableMapping(description="\n        Debug Spawn Point Color mapping. This way we can map spawn point types\n        to colors. When the user types the |debugvis.spawn_points.start\n        command, they will be able to see which spawn point belongs to it's\n        appropriate color, even if the catalog side changes.\n        ", key_type=Tunable(description='\n            The ID of the Spawn Point from the Catalog under Locators.\n            ', tunable_type=int, default=8890), value_type=TunableEnumEntry(description='\n            The debug Color this Spawn Point will appear in the world.\n            ', tunable_type=Color, default=Color.WHITE), key_name='Spawn Point ID', value_name='Spawn Point Color')

    def __init__(self, layer):
        self.layer = layer
        self._start()

    def _start(self):
        zone = services.current_zone()
        for spawn_point in zone.spawn_points_gen():
            spawn_point.register_spawn_point_changed_callback(self._on_spawn_points_changed)
        self._on_spawn_points_changed()

    def stop(self):
        zone = services.current_zone()
        for spawn_point in zone.spawn_points_gen():
            spawn_point.unregister_spawn_point_changed_callback(self._on_spawn_points_changed)

    def _on_spawn_points_changed(self):
        zone = services.current_zone()
        with Context(self.layer) as layer:
            for spawn_point in zone.spawn_points_gen():
                point_color = SpawnPointVisualizer.SPAWN_POINT_COLORS.get(spawn_point.obj_def_guid, Color.WHITE)
                footprint_polygon = spawn_point.get_footprint_polygon()
                if footprint_polygon is not None:
                    layer.add_polygon(footprint_polygon, color=point_color, altitude=0.1)
                for (slot_index, slot_position) in enumerate(spawn_point.get_slot_positions()):
                    if not spawn_point.valid_slots & 1 << slot_index:
                        layer.set_color(Color.RED)
                    else:
                        layer.set_color(point_color)
                    layer.add_point(slot_position, altitude=0.1)
            layer.set_color(Color.CYAN)
            for corner in services.current_zone().lot.corners:
                layer.add_point(corner, size=1.0)

    def get_spawn_point_string_gen(self):
        zone = services.current_zone()
        for spawn_point in zone.spawn_points_gen():
            spawn_point_string = 'Spawn Point {}:'.format(spawn_point.get_name())
            spawn_point_string += '\nPosition: {}'.format(spawn_point.center)
            spawn_point_string += '\nTags: {}'.format(spawn_point.get_tags())
            yield spawn_point_string

