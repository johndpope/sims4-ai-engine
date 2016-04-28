from objects.game_object import GameObject
from singletons import DEFAULT
import distributor.fields
import distributor.ops
import placement
import sims4.math

class Rug(GameObject):
    __qualname__ = 'Rug'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sort_order = 0

    @distributor.fields.Field(op=distributor.ops.SetSortOrder)
    def sort_order(self):
        return self._sort_order

    def object_bounds_for_flammable_object(self, location=DEFAULT, fire_retardant_bonus=0.0):
        if location is DEFAULT:
            location = sims4.math.Vector2(self.position.x, self.position.z)
        placement_footprint = placement.get_accurate_placement_footprint_polygon(self.position, self.orientation, self.scale, self.get_footprint())
        (lower_bound, upper_bound) = placement_footprint.bounds()
        bounding_box = sims4.geometry.QtRect(sims4.math.Vector2(lower_bound.x, lower_bound.z), sims4.math.Vector2(upper_bound.x, upper_bound.z))
        return bounding_box

    @sort_order.setter
    def sort_order(self, value):
        self._sort_order = value

