from _collections import defaultdict
from _weakrefset import WeakSet
from alarms import add_alarm_real_time, cancel_alarm
from clock import interval_in_real_seconds
from indexed_manager import CallbackTypes
from sims4.callback_utils import CallableList
from sims4.service_manager import Service
from sims4.tuning.tunable import TunableRealSecond
import services
import sims4.geometry
import sims4.log
import sims4.math
logger = sims4.log.Logger('Broadcaster', default_owner='epanero')

class BroadcasterService(Service):
    __qualname__ = 'BroadcasterService'
    INTERVAL = TunableRealSecond(description='\n        The time between broadcaster pulses. A lower number will impact\n        performance.\n        ', default=5)
    DEFAULT_QUADTREE_RADIUS = 0.1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._alarm_handle = None
        self._processing_task = None
        self._on_update_callbacks = CallableList()
        self._pending_broadcasters = []
        self._active_broadcasters = []
        self._cluster_requests = {}
        self._object_cache = None
        self._pending_update = False
        self._quadtrees = defaultdict(sims4.geometry.QuadTree)

    def start(self):
        self._alarm_handle = add_alarm_real_time(self, interval_in_real_seconds(self.INTERVAL), self._on_update, repeating=True, use_sleep_time=False)
        object_manager = services.object_manager()
        object_manager.register_callback(CallbackTypes.ON_OBJECT_LOCATION_CHANGED, self._update_object_cache)
        object_manager.register_callback(CallbackTypes.ON_OBJECT_ADD, self._update_object_cache)
        services.current_zone().wall_contour_update_callbacks.append(self._update_object_cache)

    def stop(self):
        if self._alarm_handle is not None:
            cancel_alarm(self._alarm_handle)
            self._alarm_handle = None
        if self._processing_task is not None:
            self._processing_task.stop()
            self._processing_task = None
        object_manager = services.object_manager()
        object_manager.unregister_callback(CallbackTypes.ON_OBJECT_LOCATION_CHANGED, self._update_object_cache)
        object_manager.unregister_callback(CallbackTypes.ON_OBJECT_ADD, self._update_object_cache)
        services.current_zone().wall_contour_update_callbacks.remove(self._update_object_cache)

    def add_broadcaster(self, broadcaster):
        if broadcaster not in self._pending_broadcasters:
            self._pending_broadcasters.append(broadcaster)
            self._on_update_callbacks()

    def remove_broadcaster(self, broadcaster):
        if broadcaster in self._pending_broadcasters:
            self._pending_broadcasters.remove(broadcaster)
        if broadcaster in self._active_broadcasters:
            self._remove_from_cluster_request(broadcaster)
            self._remove_broadcaster_from_quadtree(broadcaster)
            self._active_broadcasters.remove(broadcaster)
        broadcaster.on_removed()
        self._on_update_callbacks()

    def _activate_pending_broadcasters(self):
        for broadcaster in self._pending_broadcasters:
            self._active_broadcasters.append(broadcaster)
            self.update_cluster_request(broadcaster)
            self._update_object_cache()
        self._pending_broadcasters.clear()

    def _add_broadcaster_to_quadtree(self, broadcaster):
        self._remove_broadcaster_from_quadtree(broadcaster)
        broadcaster_quadtree = self._quadtrees[broadcaster.routing_surface.secondary_id]
        broadcaster_bounds = sims4.geometry.QtCircle(sims4.math.Vector2(broadcaster.position.x, broadcaster.position.z), self.DEFAULT_QUADTREE_RADIUS)
        broadcaster_quadtree.insert(broadcaster, broadcaster_bounds)
        return broadcaster_quadtree

    def _remove_broadcaster_from_quadtree(self, broadcaster):
        broadcaster_quadtree = broadcaster.quadtree
        if broadcaster_quadtree is not None:
            broadcaster_quadtree.remove(broadcaster)

    def update_cluster_request(self, broadcaster):
        if broadcaster not in self._active_broadcasters:
            return
        clustering_request = broadcaster.get_clustering()
        if clustering_request is None:
            return
        self._remove_from_cluster_request(broadcaster)
        cluster_request_key = (type(broadcaster), broadcaster.routing_surface.secondary_id)
        if cluster_request_key in self._cluster_requests:
            cluster_request = self._cluster_requests[cluster_request_key]
            cluster_request.set_object_dirty(broadcaster)
        else:
            cluster_quadtree = self._quadtrees[broadcaster.routing_surface.secondary_id]
            cluster_request = clustering_request(lambda : self._get_broadcasters_for_cluster_request_gen(*cluster_request_key), quadtree=cluster_quadtree)
            self._cluster_requests[cluster_request_key] = cluster_request
        quadtree = self._add_broadcaster_to_quadtree(broadcaster)
        broadcaster.on_added_to_quadtree_and_cluster_request(quadtree, cluster_request)

    def _remove_from_cluster_request(self, broadcaster):
        cluster_request = broadcaster.cluster_request
        if cluster_request is not None:
            cluster_request.set_object_dirty(broadcaster)

    def _update_object_cache(self, obj=None):
        if obj is None:
            self._object_cache = None
            return
        if self._object_cache is not None:
            self._object_cache.add(obj)

    def _is_valid_broadcaster(self, broadcaster):
        broadcasting_object = broadcaster.broadcasting_object
        if broadcasting_object is None:
            return False
        if broadcasting_object.is_in_inventory():
            return False
        if broadcasting_object.parent is not None and broadcasting_object.parent.is_sim:
            return False
        return True

    def _get_broadcasters_for_cluster_request_gen(self, broadcaster_type, broadcaster_level):
        for broadcaster in self._active_broadcasters:
            while broadcaster.guid == broadcaster_type.guid:
                if broadcaster.should_cluster() and broadcaster.routing_surface.secondary_id == broadcaster_level:
                    yield broadcaster

    def get_broadcasters_gen(self, inspect_only=False):
        for (cluster_request_key, cluster_request) in self._cluster_requests.items():
            is_cluster_dirty = cluster_request.is_dirty()
            if is_cluster_dirty:
                for broadcaster in self._get_broadcasters_for_cluster_request_gen(*cluster_request_key):
                    broadcaster.regenerate_constraint()
            while not is_cluster_dirty or not inspect_only:
                while True:
                    for cluster in cluster_request.get_clusters_gen():
                        broadcaster_iter = cluster.objects_gen()
                        master_broadcaster = next(broadcaster_iter)
                        master_broadcaster.set_linked_broadcasters(list(broadcaster_iter))
                        yield master_broadcaster
        for broadcaster in self._active_broadcasters:
            while not broadcaster.should_cluster():
                if self._is_valid_broadcaster(broadcaster):
                    yield broadcaster

    def get_pending_broadcasters_gen(self):
        yield self._pending_broadcasters

    def _get_all_objects_gen(self):
        if any(broadcaster.allow_objects for broadcaster in self._active_broadcasters):
            if self._object_cache is None:
                self._object_cache = WeakSet(services.object_manager().valid_objects())
            yield list(self._object_cache)
        else:
            self._object_cache = None
            yield services.sim_info_manager().instanced_sims_gen()

    def register_callback(self, callback):
        if callback not in self._on_update_callbacks:
            self._on_update_callbacks.append(callback)

    def unregister_callback(self, callback):
        if callback in self._on_update_callbacks:
            self._on_update_callbacks.remove(callback)

    def _on_update(self, _):
        self._pending_update = True

    def update(self):
        if self._pending_update:
            self._pending_update = False
            self._update()

    def _update(self):
        try:
            self._activate_pending_broadcasters()
            current_broadcasters = set(self.get_broadcasters_gen())
            for obj in self._get_all_objects_gen():
                is_affected = False
                for broadcaster in current_broadcasters:
                    while broadcaster.can_affect(obj):
                        constraint = broadcaster.get_constraint()
                        if not constraint.valid:
                            pass
                        if constraint.geometry is None or constraint.geometry.contains_point(obj.position) and constraint.routing_surface == obj.routing_surface:
                            broadcaster.apply_broadcaster_effect(obj)
                            is_affected = True
                while not is_affected:
                    if self._object_cache is not None:
                        self._object_cache.remove(obj)
            for broadcaster in current_broadcasters:
                broadcaster.on_processed()
        finally:
            self._on_update_callbacks()

