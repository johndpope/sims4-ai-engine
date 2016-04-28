import itertools
import math
from debugvis import Context
from interactions.constraints import RequiredSlotSingle, Anywhere, create_constraint_set
from postures import PostureEvent, PostureTrack
from sims4.color import red_green_lerp, pseudo_random_color, Color
from sims4.geometry import random_uniform_points_in_polygon, RelativeFacingRange, RelativeFacingWithCircle
import sims4.color
RANDOM_WEIGHT_DENSITY = 0.25
DONE_POSTURE_EVENTS = {PostureEvent.TRANSITION_FAIL, PostureEvent.TRANSITION_COMPLETE}
with sims4.reload.protected(globals()):
    _number_of_random_weight_points = 0

def set_number_of_random_weight_points(number_of_random_weight_points):
    global _number_of_random_weight_points
    _number_of_random_weight_points = number_of_random_weight_points

def _draw_constraint(layer, constraint, color, altitude_modifier=0, anywhere_position=None):
    if constraint is None:
        return
    if isinstance(constraint, RequiredSlotSingle):
        constraint = constraint._intersect(Anywhere())
    if constraint.IS_CONSTRAINT_SET:
        drawn_geometry = []
        for sub_constraint in constraint._constraints:
            if sub_constraint._geometry is not None:
                if sub_constraint._geometry in drawn_geometry:
                    _draw_constraint(layer, sub_constraint.generate_alternate_geometry_constraint(None), color, altitude_modifier)
                drawn_geometry.append(sub_constraint._geometry)
            _draw_constraint(layer, sub_constraint, color, altitude_modifier)
            altitude_modifier += 0.1
        return
    (r, g, b, a) = sims4.color.to_rgba(color)
    semitransparent = sims4.color.from_rgba(r, g, b, a*0.5)
    transparent = sims4.color.from_rgba(r, g, b, a*0.25)
    layer.routing_surface = constraint.routing_surface
    if constraint.geometry is not None:
        if constraint.geometry.polygon is not None:
            drawn_facings = []
            drawn_points = []
            drawn_polys = []
            for poly in constraint.geometry.polygon:
                poly_key = list(poly)
                if poly_key not in drawn_polys:
                    drawn_polys.append(poly_key)
                    layer.add_polygon(poly, color=color, altitude=altitude_modifier + 0.1)

                def draw_facing(point, color):
                    altitude = altitude_modifier + 0.1
                    (valid, interval) = constraint._geometry.get_orientation_range(point)
                    if valid and interval is not None:
                        if interval.a != interval.b:
                            if interval.angle >= sims4.math.TWO_PI:
                                angles = [(interval.ideal, True)]
                            else:
                                angles = [(interval.a, False), (interval.ideal, True), (interval.b, False)]
                        else:
                            angles = [(interval.a, True)]
                        for (angle, arrowhead) in angles:
                            facings_key = (point, angle, arrowhead)
                            while facings_key not in drawn_facings:
                                drawn_facings.append(facings_key)
                                layer.add_arrow(point, angle, end_arrow=arrowhead, length=0.2, color=color, altitude=altitude)
                    else:
                        point_key = point
                        if point_key not in drawn_points:
                            drawn_points.append(point_key)
                            layer.add_point(point, color=color, altitude=altitude)

                if not constraint.geometry.restrictions:
                    pass
                for vertex in poly:
                    draw_facing(vertex, color)
                for i in range(len(poly)):
                    v1 = poly[i]
                    v2 = poly[(i + 1) % len(poly)]
                    draw_facing(v1, transparent)
                    draw_facing(0.5*(v1 + v2), transparent)
                if _number_of_random_weight_points:
                    num_random_points = _number_of_random_weight_points
                else:
                    num_random_points = math.ceil(poly.area()*RANDOM_WEIGHT_DENSITY)
                while num_random_points:
                    while True:
                        for point in random_uniform_points_in_polygon(poly, num_random_points):
                            orientation = sims4.math.Quaternion.IDENTITY()
                            if constraint._geometry is not None:
                                (valid, quat) = constraint._geometry.get_orientation(point)
                                if quat is not None:
                                    orientation = quat
                            draw_facing(point, transparent)
                            score = constraint.get_score(point, orientation)
                            color = red_green_lerp(score, a*0.33)
                            layer.add_point(point, size=0.025, color=color)
        elif constraint.geometry.restrictions:
            for restriction in constraint.geometry.restrictions:
                if isinstance(restriction, RelativeFacingRange):
                    layer.add_point(restriction.target, color=color)
                else:
                    while isinstance(restriction, RelativeFacingWithCircle):
                        layer.add_circle(restriction.target, radius=restriction.radius, color=color)
        if isinstance(constraint, RequiredSlotSingle):
            while True:
                for (routing_transform, _) in itertools.chain(constraint._slots_to_params_entry or (), constraint._slots_to_params_exit or ()):
                    layer.add_arrow_for_transform(routing_transform, length=0.1, color=semitransparent, altitude=altitude_modifier)
                    layer.add_segment(routing_transform.translation, constraint.containment_transform.translation, color=transparent, altitude=altitude_modifier)
    elif isinstance(constraint, Anywhere) and anywhere_position is not None:
        layer.add_circle(anywhere_position, radius=0.28, color=transparent, altitude=altitude_modifier)
        layer.add_circle(anywhere_position, radius=0.3, color=semitransparent, altitude=altitude_modifier)

class SimLOSVisualizer:
    __qualname__ = 'SimLOSVisualizer'

    def __init__(self, sim, layer):
        self._sim_ref = sim.ref()
        self.layer = layer
        self._color = pseudo_random_color(sim.id)
        color2 = pseudo_random_color(-sim.id)
        (r, g, b, a) = sims4.color.to_rgba(color2)
        (gr, gg, gb, ga) = sims4.color.to_rgba(Color.GREY)
        self._color_semitrans = sims4.color.from_rgba((gr + r)/2, (gg + g)/2, (gb + b)/2, (ga + a)/2*0.4)
        self._start()

    @property
    def _sim(self):
        if self._sim_ref is not None:
            return self._sim_ref()

    def _start(self):
        self._sim.on_posture_event.append(self._on_posture_event)
        self._sim.si_state.on_changed.append(self._redraw)
        self._redraw()

    def stop(self):
        if self._on_posture_event in self._sim.on_posture_event:
            self._sim.on_posture_event.remove(self._on_posture_event)
        if self._redraw in self._sim.si_state.on_changed:
            self._sim.si_state.on_changed.remove(self._redraw)

    def _on_posture_event(self, change, dest_state, track, source_posture, dest_posture):
        if self._sim is None or not PostureTrack.is_body(track):
            return
        if change in DONE_POSTURE_EVENTS:
            self._redraw()

    def _redraw(self, _=None):
        los_constraint = self._sim.los_constraint
        with Context(self.layer, routing_surface=los_constraint.routing_surface) as layer:
            _draw_constraint(layer, los_constraint, self._color)
            _draw_constraint(layer, self._sim.get_social_group_constraint(None), self._color_semitrans)

class SimConstraintVisualizer:
    __qualname__ = 'SimConstraintVisualizer'

    def __init__(self, sim, layer):
        self._sim = sim.ref()
        self.layer = layer
        self._social_groups = []
        self._start()

    @property
    def sim(self):
        if self._sim is not None:
            return self._sim()

    def _start(self):
        self.sim.on_posture_event.append(self._on_posture_event)
        self._on_posture_event(PostureEvent.TRANSITION_COMPLETE, self.sim.posture_state, PostureTrack.BODY, None, self.sim.posture)

    def stop(self):
        if self._on_posture_event in self.sim.on_posture_event:
            self.sim.on_posture_event.remove(self._on_posture_event)
        self._on_posture_event(PostureEvent.TRANSITION_COMPLETE, self.sim.posture_state, PostureTrack.BODY, self.sim.posture, None)

    def redraw(self, sim, constraint):
        color = pseudo_random_color(sim.id)
        (r, g, b, a) = sims4.color.to_rgba(color)
        (gr, gg, gb, ga) = sims4.color.to_rgba(Color.GREY)
        semitransparent = sims4.color.from_rgba((gr + r)/2, (gg + g)/2, (gb + b)/2, (ga + a)/2*0.4)
        transparent = sims4.color.from_rgba((gr + r)/2, (gg + g)/2, (gb + b)/2, (ga + a)/2*0.15)
        with Context(self.layer, routing_surface=constraint.routing_surface) as layer:
            direction_constraint = None
            direction_constraints = []
            for sub_constraint in constraint:
                while sub_constraint._geometry is not None and sub_constraint._geometry.polygon is None and sub_constraint._geometry.restrictions is not None:
                    direction_constraints.append(sub_constraint)
            if direction_constraints:
                direction_constraint = create_constraint_set(direction_constraints)
            for si in sim.si_state:
                participant_type = si.get_participant_type(sim)
                for si_constraint in si.constraint_intersection(participant_type=participant_type):
                    if direction_constraint is not None:
                        si_constraint = direction_constraint.intersect(si_constraint)
                    si_color = transparent
                    si_altitude = 0.01
                    if si.is_guaranteed():
                        si_color = semitransparent
                        si_altitude = 0.02
                    _draw_constraint(layer, si_constraint, si_color, altitude_modifier=si_altitude)
            _draw_constraint(layer, constraint, color, altitude_modifier=0.03, anywhere_position=sim.position)

    def _on_posture_event(self, change, dest_state, track, source_posture, dest_posture):
        if not PostureTrack.is_body(track):
            return
        sim = dest_state.sim
        if change == PostureEvent.TRANSITION_START:
            if sim.queue.running is not None and sim.queue.running.is_super:
                constraint = sim.queue.running.transition.get_final_constraint(sim)
            else:
                constraint = Anywhere()
        elif change in DONE_POSTURE_EVENTS:
            constraint = sim.si_state.get_total_constraint(include_inertial_sis=True)
            self._dest_state = dest_state
        else:
            return
        self._register_on_constraint_changed_for_groups()
        if dest_state is not None:
            self._on_rebuild(sim, constraint)

    def _register_on_constraint_changed_for_groups(self):
        for group in self._social_groups:
            while self._on_constraint_changed in group.on_constraint_changed:
                group.on_constraint_changed.remove(self._on_constraint_changed)
        del self._social_groups[:]
        sim = self.sim
        if sim is not None:
            self._social_groups.extend(sim.get_groups_for_sim_gen())
            for group in self._social_groups:
                group.on_constraint_changed.append(self._on_constraint_changed)

    def _on_constraint_changed(self):
        sim = self.sim
        constraint = sim.si_state.get_total_constraint(include_inertial_sis=True, force_inertial_sis=True)
        self._on_rebuild(sim, constraint)

    def _on_rebuild(self, sim, constraint):
        self.redraw(sim, constraint)

