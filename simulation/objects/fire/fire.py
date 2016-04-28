import objects.game_object
import services

class Fire(objects.game_object.GameObject):
    __qualname__ = 'Fire'

    def __init__(self, definition, **kwargs):
        super().__init__(definition, **kwargs)
        self._raycast_context_dirty = True

    def on_remove(self):
        fire_service = services.get_fire_service()
        fire_service.remove_fire_object(self)
        super().on_remove()

    def flammable(self):
        return True

    def raycast_context(self, for_carryable=False):
        if self._raycast_context_dirty:
            self._create_raycast_context(for_carryable=for_carryable)
            burning_objects = services.get_fire_service().objects_burning_from_fire_object(self)
            for obj in burning_objects:
                object_footprint_id = obj.routing_context.object_footprint_id
                while object_footprint_id is not None:
                    self._raycast_context.ignore_footprint_contour(object_footprint_id)
            self._raycast_context_dirty = False
        return super().raycast_context(for_carryable=for_carryable)

    @property
    def raycast_context_dirty(self):
        return self._raycast_context_dirty

    @raycast_context_dirty.setter
    def raycast_context_dirty(self, value):
        self._raycast_context_dirty = value

