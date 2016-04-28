from objects.components import Component, types
from crafting.recipe import CraftingObjectType
from sims4.tuning.tunable import HasTunableFactory, TunableReference, Tunable
import services
from objects.components import componentmethod_with_fallback

class CraftingStationComponent(Component, HasTunableFactory, component_name=types.CRAFTING_STATION_COMPONENT):
    __qualname__ = 'CraftingStationComponent'
    FACTORY_TUNABLES = {'crafting_station_type': TunableReference(services.recipe_manager(), class_restrictions=CraftingObjectType, description='This specifies the crafting object type that is satisfied by this object.'), 'children_invalidate_crafting_cache': Tunable(description="\n                If this is True, anything that is attached as a child of this object will cause \n                the crafting cache to be invalidated.  If it's False, children will be ignored\n                for the purposes of the crafting cache.\n                ", tunable_type=bool, default=True)}

    def __init__(self, owner, *, crafting_station_type, children_invalidate_crafting_cache):
        super().__init__(owner)
        self.crafting_station_type = crafting_station_type
        self._children_invalidate_crafting_cache = children_invalidate_crafting_cache
        self._cached = False
        self._cached_for_autonomy = False

    def on_add(self):
        if self.crafting_station_type is not None:
            self.add_to_crafting_cache()
            self._add_state_changed_callback()

    def on_remove(self):
        if self.crafting_station_type is not None:
            self.remove_from_crafting_cache()
            self._remove_state_changed_callback()

    def on_child_added(self, child):
        if self._children_invalidate_crafting_cache and len(self.owner.children) == 1:
            self.remove_from_crafting_cache(user_directed=False)

    def on_child_removed(self, child):
        if self._children_invalidate_crafting_cache and len(self.owner.children) == 0:
            self.add_to_crafting_cache(user_directed=False)

    @componentmethod_with_fallback(lambda : None)
    def add_to_crafting_cache(self, user_directed=True, autonomy=True):
        if self.crafting_station_type is not None:
            self._add_to_cache(user_directed=user_directed, autonomy=autonomy)

    @componentmethod_with_fallback(lambda : None)
    def remove_from_crafting_cache(self, user_directed=True, autonomy=True):
        if self.crafting_station_type is not None:
            self._remove_from_cache(user_directed=user_directed, autonomy=autonomy)

    def _add_to_cache(self, user_directed=True, autonomy=True):
        user_directed &= not self._cached
        autonomy &= not self._cached_for_autonomy
        services.object_manager().crafting_cache.add_type(self.crafting_station_type, user_directed=user_directed, autonomy=autonomy)
        if autonomy:
            self._cached_for_autonomy = True
        if user_directed:
            self._cached = True

    def _remove_from_cache(self, user_directed=True, autonomy=True):
        user_directed &= self._cached
        autonomy &= self._cached_for_autonomy
        services.object_manager().crafting_cache.remove_type(self.crafting_station_type, user_directed=user_directed, autonomy=autonomy)
        if autonomy:
            self._cached_for_autonomy = False
        if user_directed:
            self._cached = False

    def _add_state_changed_callback(self):
        if self.owner.has_component(types.STATE_COMPONENT):
            self.owner.add_state_changed_callback(self._on_crafting_object_state_changed)

    def _remove_state_changed_callback(self):
        if self.owner.has_component(types.STATE_COMPONENT):
            self.owner.remove_state_changed_callback(self._on_crafting_object_state_changed)

    def _on_crafting_object_state_changed(self, owner, state, old_value, new_value):
        if not old_value.remove_from_crafting_cache and new_value.remove_from_crafting_cache:
            self.remove_from_crafting_cache()
        elif old_value.remove_from_crafting_cache and not new_value.remove_from_crafting_cache:
            self.add_to_crafting_cache()

