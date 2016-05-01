from sims4.color import Color
from sims4.geometry import CompoundPolygon, make_perturb_gen
from terrain import get_terrain_height
import services
import sims4.math
try:
    import _debugvis
    Layer = _debugvis.Layer
    get_layer = _debugvis.get_layer
except:

    class Layer:
        __qualname__ = 'Layer'

        def open(self, *args, **kwargs):
            pass

        def clear(self, *args, **kwargs):
            pass

        def commit(self, *args, **kwargs):
            pass

        def add_segment(self, *args, **kwargs):
            pass

        def add_text_screen(self, *args, **kwargs):
            pass

        def add_text_world(self, *args, **kwargs):
            pass

        def add_text_object(self, *args, **kwargs):
            pass

    def get_layer(*args, **kwargs):
        return Layer()


def _get_perpendicular_vector(axis=sims4.math.UP_AXIS):
    v = sims4.math.vector_cross(axis, sims4.math.Vector3.Z_AXIS())
    if sims4.math.vector3_almost_equal(v, sims4.math.Vector3.ZERO()):
        v = sims4.math.vector_cross(axis, sims4.math.Vector3.X_AXIS())
    v = sims4.math.vector_normalize(v)
    return v


def _get_vector_from_offset_angle(offset, angle, length):
    v = sims4.math.FORWARD_AXIS
    v = sims4.math.angle_to_yaw_quaternion(angle).transform_vector(v)
    v = sims4.math.vector_normalize(v) * length
    return offset + v


KEEP_ALTITUDE = object()
LINE_THICKNESS = 1
LINE_THICKNESS_SCALE = 0.007


class Context:
    __qualname__ = 'Context'

    def __init__(self,
                 name,
                 preserve=False,
                 color=Color.WHITE,
                 altitude=0.05,
                 zone_id=None,
                 routing_surface=None):
        if zone_id is None:
            zone_id = services.current_zone().id
        self.layer = get_layer(name, zone_id)
        self.preserve = preserve
        self.default_color = color
        self.default_altitude = altitude
        self.routing_surface = routing_surface

    def __enter__(self):
        self.layer.open()
        if not self.preserve:
            self.layer.clear()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.layer.commit()

    def set_color(self, color):
        self.default_color = color

    def set_altitude(self, altitude):
        self.default_altitude = altitude

    def add_segment(
            self, a,
            b, color=None,
            altitude=None,
            routing_surface=None):
        if color is None:
            color = self.default_color
        if altitude is None:
            altitude = self.default_altitude
        a = self._apply_altitude(a, altitude, routing_surface=routing_surface)
        b = self._apply_altitude(b, altitude, routing_surface=routing_surface)
        perturb_gen = make_perturb_gen(scale=LINE_THICKNESS_SCALE)
        for (_, perturb_fn) in zip(range(LINE_THICKNESS), perturb_gen):
            a = perturb_fn(a)
            b = perturb_fn(b)
            self.layer.add_segment(a, b, color)

    def add_point(self,
                  p,
                  size=0.1,
                  color=None,
                  altitude=None,
                  routing_surface=None):
        if color is None:
            color = self.default_color
        if altitude is None:
            altitude = self.default_altitude
        p = self._apply_altitude(p, altitude, routing_surface=routing_surface)
        perturb_gen = make_perturb_gen(scale=LINE_THICKNESS_SCALE)
        for (_, perturb_fn) in zip(range(LINE_THICKNESS), perturb_gen):
            p = perturb_fn(p)
            self.layer.add_point(p, size, color)

    def add_polygon(self,
                    vertices,
                    color=None,
                    altitude=None,
                    routing_surface=None):
        if isinstance(vertices, CompoundPolygon):
            polygons = vertices
            for polygon in polygons:
                self.add_polygon(polygon,
                                 color,
                                 altitude,
                                 routing_surface=routing_surface)
            return
        l = list(vertices)
        if len(l) == 1:
            self.add_point(l[0],
                           size=0.2,
                           color=color,
                           altitude=altitude,
                           routing_surface=routing_surface)
            return
        for (a, b) in zip(l, l[1:] + l[:1]):
            self.add_segment(a,
                             b,
                             color=color,
                             altitude=altitude,
                             routing_surface=routing_surface)

    def add_circle(self,
                   p,
                   radius=1.0,
                   axis=sims4.math.UP_AXIS,
                   num_points=12,
                   color=None,
                   altitude=None,
                   routing_surface=None):
        v = _get_perpendicular_vector(axis) * radius
        vertices = [p + sims4.math.Quaternion.from_axis_angle(
            i * sims4.math.TWO_PI / num_points, axis).transform_vector(v)
                    for i in range(num_points)]
        self.add_polygon(vertices,
                         color=color,
                         altitude=altitude,
                         routing_surface=routing_surface)

    def add_arrow(self,
                  p,
                  angle,
                  length=0.5,
                  start_arrow=False,
                  start_len=0.1,
                  start_angle=sims4.math.PI / 6,
                  end_arrow=True,
                  end_len=0.1,
                  end_angle=sims4.math.PI / 6,
                  color=None,
                  altitude=None,
                  routing_surface=None):
        if length != 0:
            endpoint = _get_vector_from_offset_angle(p, angle, length)
            self.add_segment(p,
                             endpoint,
                             color=color,
                             altitude=altitude,
                             routing_surface=routing_surface)
        else:
            endpoint = p
        if start_arrow and start_len != 0:
            for head_angle in (sims4.math.PI + angle - start_angle,
                               sims4.math.PI + angle + start_angle):
                head_end = _get_vector_from_offset_angle(p, head_angle,
                                                         start_len)
                self.add_segment(p,
                                 head_end,
                                 color=color,
                                 altitude=altitude,
                                 routing_surface=routing_surface)
        if end_arrow and end_len != 0:
            for head_angle in (sims4.math.PI + angle - end_angle,
                               sims4.math.PI + angle + end_angle):
                head_end = _get_vector_from_offset_angle(endpoint, head_angle,
                                                         end_len)
                self.add_segment(endpoint,
                                 head_end,
                                 color=color,
                                 altitude=altitude,
                                 routing_surface=routing_surface)

    def add_arrow_for_transform(
            self, transform,
            length=0.5, color=None,
            altitude=None):
        angle = sims4.math.yaw_quaternion_to_angle(transform.orientation)
        self.add_arrow(transform.translation,
                       angle,
                       length=length,
                       color=color,
                       altitude=altitude)

    def add_text_screen(self, p, text, **kwargs):
        self.layer.add_text_screen(p, text, **kwargs)

    def add_text_world(
            self, p,
            text, altitude=None,
            routing_surface=None,
            **kwargs):
        if altitude is None:
            altitude = self.default_altitude
        p = self._apply_altitude(p, altitude, routing_surface=routing_surface)
        self.layer.add_text_world(p, text, **kwargs)

    def add_text_object(self, obj, offset, text, bone_index=-1, **kwargs):
        self.layer.add_text_object(
            obj.id, offset,
            text, bone_index=bone_index,
            **kwargs)

    def _apply_altitude(self, v, altitude, routing_surface=None):
        if altitude is None or altitude is KEEP_ALTITUDE:
            return v
        final_surface = routing_surface if routing_surface is not None else self.routing_surface
        h = get_terrain_height(v.x, v.z, routing_surface=final_surface)
        return sims4.math.Vector3(v.x, h + altitude, v.z)
