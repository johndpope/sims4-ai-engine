from debugvis import Context, KEEP_ALTITUDE
from sims4.color import Color
import placement
import services
import sims4.math
import terrain
from sims4.geometry import Polygon
import routing

class QuadTreeVisualizer:
    __qualname__ = 'QuadTreeVisualizer'
    ALL_LEVELS = 255

    def __init__(self, layer):
        self.layer = layer
        self._start()

    def _start(self):
        services.current_zone().on_quadtree_changed.append(self._on_quadtree_changed)
        self._on_quadtree_changed()

    def stop(self):
        services.current_zone().on_quadtree_changed.remove(self._on_quadtree_changed)

    def _on_quadtree_changed(self):
        quadtree = services.sim_quadtree()
        if quadtree is None:
            return
        zone = services.current_zone()
        pos = sims4.math.Vector2(0, 0)
        bounds = sims4.geometry.QtCircle(pos, 10000)
        all_sims_positions = quadtree.query(bounds=bounds, level=self.ALL_LEVELS, filter=placement.ItemType.SIM_POSITION, flags=sims4.geometry.ObjectQuadTreeQueryFlag.IGNORE_LEVEL)
        all_intended = quadtree.query(bounds=bounds, level=self.ALL_LEVELS, filter=placement.ItemType.SIM_INTENDED_POSITION, flags=sims4.geometry.ObjectQuadTreeQueryFlag.IGNORE_LEVEL)
        all_suppressors = quadtree.query(bounds=bounds, level=self.ALL_LEVELS, filter=placement.ItemType.ROUTE_GOAL_SUPPRESSOR, flags=sims4.geometry.ObjectQuadTreeQueryFlag.IGNORE_LEVEL)
        with Context(self.layer) as layer:
            layer.set_color(Color.GREEN)
            for o in all_sims_positions:
                height = terrain.get_lot_level_height(o[2].center.x, o[2].center.y, o[3], zone.id) + 0.1
                pos = sims4.math.Vector3(o[2].center.x, height, o[2].center.y)
                layer.add_circle(pos, o[2].radius, altitude=KEEP_ALTITUDE)
            layer.set_color(Color.YELLOW)
            for o in all_intended:
                if isinstance(o[2], Polygon):
                    routing_surface = routing.SurfaceIdentifier(zone.id, o[3], routing.SURFACETYPE_WORLD)
                    layer.add_polygon(o[2], altitude=0.1, routing_surface=routing_surface)
                else:
                    height = terrain.get_lot_level_height(o[2].center.x, o[2].center.y, o[3], zone.id) + 0.1
                    pos = sims4.math.Vector3(o[2].center.x, height, o[2].center.y)
                    layer.add_circle(pos, o[2].radius, altitude=KEEP_ALTITUDE)
            layer.set_color(Color.RED)
            for o in all_suppressors:
                if isinstance(o[2], Polygon):
                    routing_surface = routing.SurfaceIdentifier(zone.id, o[3], routing.SURFACETYPE_WORLD)
                    layer.add_polygon(o[2], altitude=0.1, routing_surface=routing_surface)
                else:
                    height = terrain.get_lot_level_height(o[2].center.x, o[2].center.y, o[3], zone.id) + 0.1
                    pos = sims4.math.Vector3(o[2].center.x, height, o[2].center.y)
                    layer.add_circle(pos, o[2].radius, altitude=KEEP_ALTITUDE)

